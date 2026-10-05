# ==============================================================
# 能力契约｜题目质量审核（格式/答案/难度/知识点/歧义/图片依赖），error 级拦截
# 入口：QuestionValidator.validate；模块级 validate
# 依赖：re unicodedata
# 不负责：题目生成 → deepseek.py
# 验证：python backend/verify_knowledge.py（审核规则断言）、python backend/verify_flow.py --self-serve
# 被调用：main.py、diagnostic_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 AI 题目质量审核 QuestionValidator。

所有 AI（以及本地题库）生成的题目在保存前都要过一遍审核：

    DeepSeek 生成 → 格式检查 → 答案验证 → 难度验证 → 知识点验证 → 通过 → 保存

审核分两级：
* `error`：必须拦下来的硬伤（题干空、选项不足/重复、答案不在选项中、算式与答案不符、要孩子看一张没给出的图）。
* `warn`：可疑但不拦（数字规模与阶段不符、可能超纲、题干出现答案原文、知识点对不上）。

特别地，数学题会做**算式自检**：题干里只有一个"a 运算 b"时，直接算一遍和答案比对，
这样生成器写错、模型算错都能当场发现。
"""

import re
import unicodedata

# 这些选项对小学生没有区分度，属于歧义选项
AMBIGUOUS_OPTIONS = ("以上都对", "以上都不对", "都不对", "都对", "不确定", "以上都是", "以上均对")

# 系统不出带图的题：这些说法都要孩子看一张根本没有给出的图
IMAGE_REFERENCE_WORDS = (
    "看图", "图中", "如图", "如下图", "如上图", "下图", "上图", "图片", "插图", "图案",
    "照片", "这幅图", "这幅画", "哪幅图", "哪一幅图", "哪张图", "图里",
)
# 「看图写话 / 看图说话」+ 题干已用文字描述图上内容 → 孩子读文字就能答，不算依赖配图
IMAGE_TASK_SELF_CONTAINED_RE = re.compile(r"看图(?:写话|说话)")
IMAGE_DESCRIBED_RE = re.compile(r"图(?:上|中|里)?画(?:着|的是|有)|画着|画的是")
# 图形类题目：出现这些搭配时同样需要一张图
GRAPHICS_WORDS = ("图形", "统计图", "示意图", "线段图", "钟面", "方格纸", "数轴", "展开图", "立体图形")
GRAPHICS_POINTERS = ("下面", "如下", "看图", "观察", "如图", "这个图", "该图", "这幅", "上图", "下图")
# 要孩子比较「写 / 画得对不对」的字母、汉字题（没有配图时无从判断）
SHAPE_WORDS = ("字母", "汉字", "生字", "拼音", "笔画")
HANDWRITING_WORDS = ("写得", "写法", "字形", "书写", "占格")

# 口头运算符 → Python 运算符
OPERATORS = {"+": "+", "-": "-", "×": "*", "x": "*", "X": "*", "*": "*", "÷": "/", "/": "/"}

# 恰好一个"两数运算"的题干才做算式自检（两步题、分数题会被自动跳过）
EXPR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([+\-×xX*÷/])\s*(\d+(?:\.\d+)?)")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

UNITS = (
    "平方厘米", "平方分米", "平方米", "立方厘米", "立方分米", "立方米",
    "厘米", "分米", "毫米", "千米", "米", "元", "角", "分", "个", "只", "朵",
    "本", "支", "人", "岁", "天", "小时", "分钟", "秒", "千克", "克", "吨", "升", "毫升",
)

# 超纲词 → 第一次出现这个概念大致对应的难度
SCOPE_TERMS = (
    ("分数", 45), ("小数", 60), ("方程", 70), ("因数", 74), ("倍数", 74),
    ("比例", 84), ("圆", 88), ("百分数", 90), ("统计", 90),
)

SEVERITY_PENALTY = {"error": 25, "warn": 5}


class QuestionValidator:
    """题目质量审核器（纯函数，不碰数据库）。"""

    MAX_OPTIONS = 4
    MIN_OPTIONS = 2

    # ---------- 小工具 ----------

    @staticmethod
    def _normalize(text):
        return unicodedata.normalize("NFKC", str(text or "")).strip().lower().replace(" ", "")

    @classmethod
    def _to_number(cls, text):
        """把 "12"、"12厘米"、"12.5平方厘米" 转成数字；不是数值就返回 None。"""
        value = str(text or "").strip()
        for unit in UNITS:
            value = value.replace(unit, "")

        value = value.strip()
        try:
            return float(value)
        except ValueError:
            return None

    @classmethod
    def _same_value(cls, left, right):
        if cls._normalize(left) == cls._normalize(right):
            return True
        a, b = cls._to_number(left), cls._to_number(right)
        return a is not None and b is not None and a == b

    @staticmethod
    def _issue(code, message, severity="error", detail=None):
        item = {"code": code, "message": message, "severity": severity}
        if detail is not None:
            item["detail"] = detail
        return item

    # ---------- 各专项检查 ----------

    def _check_image_dependency(self, data, options, issues):
        """系统不出带图的题：题目必须只靠文字就能作答（图片依赖按 error 拦下）。

        * 本地题库 / 兜底题是人工把关的纯文字内容，不再拦。
        * 「看图写话 / 看图说话」类题干如果已经用文字把图上内容写清楚，孩子读文字就能答。
        """
        source = str(data.get("source") or "")
        if "bank" in source or source == "fallback":
            return                     # 本地题库 / 兜底题是人工把关的纯文字内容

        question = str(data.get("question") or "")
        text = " ".join([question] + [str(value) for value in (options or {}).values()])

        if data.get("needs_image"):
            issues.append(self._issue("IMAGE_DEPENDENT",
                                      "这道题自己说要配图才能作答，系统不给题目配图", "error"))
            return

        if IMAGE_TASK_SELF_CONTAINED_RE.search(text) and IMAGE_DESCRIBED_RE.search(text):
            return

        for word in IMAGE_REFERENCE_WORDS:
            if word in text:
                issues.append(self._issue("IMAGE_DEPENDENT",
                                          f"题目里出现「{word}」，孩子看不到图就没法作答",
                                          "error", word))
                return

        if any(word in text for word in GRAPHICS_WORDS) and any(p in text for p in GRAPHICS_POINTERS):
            issues.append(self._issue("IMAGE_DEPENDENT",
                                      "题目指向一张图形 / 示意图，孩子看不到图就没法作答", "error"))
            return

        if any(word in question for word in SHAPE_WORDS) and any(word in question for word in HANDWRITING_WORDS):
            issues.append(self._issue("IMAGE_DEPENDENT",
                                      "题目要孩子比较字母 / 汉字的写法，没有配图无从判断", "error"))

    def _check_format(self, data, qtype, issues):
        question = str(data.get("question") or "").strip()
        answer = str(data.get("answer") or "").strip()
        options = data.get("options") or {}

        if not question:
            issues.append(self._issue("FORMAT_EMPTY_QUESTION", "题干为空"))

        if len(question) > 400:
            issues.append(self._issue("FORMAT_TOO_LONG", "题干过长，可能不是一道小题",
                                      "warn", len(question)))

        if not answer:
            issues.append(self._issue("FORMAT_ANSWER_EMPTY", "缺少标准答案"))

        if qtype != "choice":
            return options

        if len(options) < self.MIN_OPTIONS:
            issues.append(self._issue("FORMAT_OPTION_COUNT", "选项少于 2 个", "error", len(options)))
            return options

        if len(options) != self.MAX_OPTIONS:
            issues.append(self._issue("FORMAT_OPTION_COUNT", "选项不是 4 个", "warn", len(options)))

        values = list(options.values())
        for index, value in enumerate(values):
            for other in values[index + 1:]:
                if self._same_value(value, other):
                    issues.append(self._issue("FORMAT_OPTION_DUPLICATE", "存在两个相同的选项",
                                              "error", [value, other]))
                    break

        if answer.upper() not in {str(key).upper() for key in options}:
            issues.append(self._issue("FORMAT_ANSWER_NOT_IN_OPTIONS",
                                      "答案字母不在选项里", "error", answer))

        return options

    def _check_ambiguity(self, data, options, issues):
        texts = [str(value) for value in (options or {}).values()]
        texts.append(str(data.get("question") or ""))

        for text in texts:
            for word in AMBIGUOUS_OPTIONS:
                if word in text:
                    issues.append(self._issue("AMBIGUOUS_OPTION", f"出现歧义选项「{word}」",
                                              "error", text))
                    return

    def _check_answer_leak(self, data, options, issues):
        question = self._normalize(data.get("question"))
        answer = str(data.get("answer") or "").strip()
        qtype = str(data.get("qtype") or "choice")

        text = str((options or {}).get(answer.upper(), "")) if qtype == "choice" else answer
        normalized = self._normalize(text)

        # 纯数字答案在题干里出现很正常（题干本来就有数字），只查文字答案
        if not normalized or normalized.isdigit() or self._to_number(text) is not None:
            return

        if len(normalized) >= 2 and normalized in question:
            issues.append(self._issue("FORMAT_QUESTION_LEAKS_ANSWER",
                                      "题干里直接出现了答案原文", "warn", text))

    def _check_math_expression(self, data, options, issues):
        """算式自检：题干只有一个两数运算时，算一遍和答案比对。"""
        question = str(data.get("question") or "")
        matches = EXPR_RE.findall(question)

        if len(matches) != 1:
            return None                       # 两步题 / 无算式 / 分数题：跳过

        left, symbol, right = matches[0]
        operator = OPERATORS.get(symbol)
        if operator is None:
            return None

        a, b = float(left), float(right)
        if operator == "+":
            expected = a + b
        elif operator == "-":
            expected = a - b
        elif operator == "*":
            expected = a * b
        else:
            if b == 0:
                issues.append(self._issue("MATH_DIVIDE_BY_ZERO", "算式中出现了除以 0", "error"))
                return None
            expected = a / b

        qtype = str(data.get("qtype") or "choice")
        answer = str(data.get("answer") or "").strip()
        answer_text = str((options or {}).get(answer.upper(), "")) if qtype == "choice" else answer

        got = self._to_number(answer_text)
        if got is None:
            return None                       # 答案是分数、比、单位换算等，跳过

        # "除不尽时保留两位小数"这类题允许四舍五入误差
        tolerance = 0.011 if ("保留" in question or "约" in question) else 0.001

        if abs(got - expected) > tolerance:
            issues.append(self._issue(
                "MATH_EXPRESSION_MISMATCH",
                f"答案与算式不符：{left} {symbol} {right} = {round(expected, 4)}，但答案是 {answer_text}",
                "error", {"expected": expected, "got": got},
            ))

        return expected

    def _check_difficulty(self, data, difficulty, stage, issues, subject=None):
        if difficulty is None:
            return

        numbers = [float(item) for item in NUMBER_RE.findall(str(data.get("question") or ""))]
        biggest = max(numbers) if numbers else 0
        difficulty = float(difficulty)

        if difficulty <= 30 and biggest > 100:
            issues.append(self._issue("DIFFICULTY_SCALE", "低阶段题目里出现了超过 100 的数",
                                      "warn", biggest))

        if difficulty <= 45 and biggest > 10000:
            issues.append(self._issue("DIFFICULTY_SCALE", "题目数字规模明显超出当前阶段",
                                      "warn", biggest))

        question = str(data.get("question") or "")
        for word, floor in SCOPE_TERMS:
            if word in question and difficulty < floor - 5:
                issues.append(self._issue("DIFFICULTY_SCOPE",
                                          f"可能超出当前阶段：出现「{word}」但难度只有 {round(difficulty)}",
                                          "warn", word))
                break

        if subject == "数学" and biggest == 0 and len(question) < 12:
            issues.append(self._issue("FORMAT_TOO_SHORT", "数学题里没有数字，可能有问题",
                                      "warn", question))

    def _check_knowledge(self, data, subject, knowledge, issues):
        if not knowledge:
            return

        # 本地题库的题目由"阶段 → 知识点"映射保证，不需要再做关键词匹配
        if str(data.get("source") or "") == "bank":
            return

        question = self._normalize(data.get("question"))
        name = self._normalize(knowledge)

        # 中文没有天然分词，用 2 字滑窗做弱匹配，命中任意一个就算对得上
        grams = {name[i:i + 2] for i in range(max(1, len(name) - 1))}
        if grams and not any(gram in question for gram in grams):
            issues.append(self._issue("KNOWLEDGE_MISMATCH",
                                      f"题干看不出在考「{knowledge}」", "warn", knowledge))

    def _check_subject_scope(self, data, subject, options, issues):
        """选择题的选项应该同类型，避免"数字题里混进三个文字选项"这类怪题。"""
        if not options:
            return

        numbers = sum(1 for value in options.values() if self._to_number(value) is not None)
        if 0 < numbers < len(options):
            issues.append(self._issue("OPTION_TYPE_MIXED", "选项里数字和文字混在一起",
                                      "warn", numbers))

    # ---------- 主入口 ----------

    def validate(self, data, subject=None, grade=None, knowledge=None,
                 difficulty=None, stage=None):
        """返回 {"passed", "issues", "score", "checks"}。

        passed 只由 error 级问题决定；warn 级问题只提示、不拦题。
        """
        data = data or {}
        qtype = str(data.get("qtype") or "choice")
        issues = []

        options = self._check_format(data, qtype, issues)
        self._check_image_dependency(data, options, issues)
        self._check_ambiguity(data, options, issues)
        self._check_answer_leak(data, options, issues)
        expected = self._check_math_expression(data, options, issues)
        self._check_difficulty(data, difficulty, stage, issues, subject=subject)
        self._check_knowledge(data, subject, knowledge, issues)
        self._check_subject_scope(data, subject, options, issues)

        score = 100
        for item in issues:
            score -= SEVERITY_PENALTY.get(item["severity"], 5)
        score = max(0, score)

        errors = [item for item in issues if item["severity"] == "error"]
        warnings = [item for item in issues if item["severity"] == "warn"]

        return {
            "passed": not errors,
            "score": score,
            "issues": issues,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "checks": {
                "format": not any(item["code"].startswith("FORMAT") for item in errors),
                "answer": not any(item["code"].startswith(("MATH_", "FORMAT_ANSWER")) for item in errors),
                "difficulty": not any(item["code"].startswith("DIFFICULTY") for item in errors),
                "knowledge": not any(item["code"] == "KNOWLEDGE_MISMATCH" for item in errors),
                "self_contained": not any(item["code"] == "IMAGE_DEPENDENT" for item in errors),
                "expression_expected": expected,
            },
        }


DEFAULT_VALIDATOR = QuestionValidator()


def validate(data, subject=None, grade=None, knowledge=None, difficulty=None, stage=None):
    """模块级快捷入口。"""
    return DEFAULT_VALIDATOR.validate(data, subject=subject, grade=grade,
                                      knowledge=knowledge, difficulty=difficulty, stage=stage)
