# -*- coding: utf-8 -*-
# ==============================================================
# 能力契约｜AI 错题康复教学：四级分层提示 + 变式题生成（规则优先，DeepSeek 可选）
# 入口：ai_enabled／level_name／levels／fallback_hint／error_location／build_full_explanation／AIRecoveryTeacher／teach／VariantQuestionGenerator／generate_variants／validate_variant／DEFAULT_TEACHER／DEFAULT_GENERATOR
# 依赖：os／re／json／unicodedata／requests／deepseek（KEY / API_URL / _extract_json）／validator（QuestionValidator）
# 不负责：康复状态机与落库 → recovery/state.py 与 recovery/engine.py；判分 → grading.py
# 验证：python backend/check_cards.py；PHOEBE_AI_OFFLINE=1 四级提示与变式题自测
# 被调用：recovery/engine.py；（可选）ai_recovery_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复的 AI 教学层（SPEC §5.1）。

两条硬语义（会被测试断言）：

1. **四级提示逐级给信息**：L1 只给方向、L2 指出错在哪一步、L3 给步骤骨架，
   L1/L2/L3 **都不含最终答案**，只有 L4 才给完整讲解与答案。
2. **变式题必须过审**：每题都过 ``validator.QuestionValidator.validate``，
   ``validation["passed"] == False`` 的题一律丢弃，不足 ``count`` 时用规则模板补足。

可用性优先：没有 key、``PHOEBE_AI_OFFLINE=1``、网络异常、模型返回格式不对，
统统降级为 ``fallback_hint`` / 规则模板，**绝不向调用方抛异常**。
"""

import json
import os
import re
import unicodedata

import requests

import deepseek
from validator import QuestionValidator

OFFLINE_ENV = "PHOEBE_AI_OFFLINE"
OFFLINE_VALUES = ("1", "true", "yes", "on")
AI_TIMEOUT = 12

#: level → 中文名（SPEC §5.1：1 方向提示 / 2 错误定位 / 3 步骤引导 / 4 完整讲解）
LEVEL_NAMES = {1: "方向提示", 2: "错误定位", 3: "步骤引导", 4: "完整讲解"}

#: 每级给出什么 / 不给什么（levels() 与 AI_RECOVERY_DESIGN.md 共用同一份真相）
LEVEL_SPECS = (
    {"level": 1, "name": "方向提示", "text": "只给思考方向：考什么、该看哪一部分",
     "gives": "方向", "withhold": "最终答案"},
    {"level": 2, "name": "错误定位", "text": "指出错在哪一步并说明为什么错，仍不给答案",
     "gives": "错在哪一步", "withhold": "最终答案"},
    {"level": 3, "name": "步骤引导", "text": "给出完整解题步骤骨架（答案用 □ 占位），仍不给最终答案",
     "gives": "解题步骤", "withhold": "最终答案"},
    {"level": 4, "name": "完整讲解", "text": "完整讲解 + 正确答案 + 解析，鼓励孩子复述一遍",
     "gives": "完整讲解与答案", "withhold": "无"},
)

_OPERATORS = {"+": "+", "-": "-", "×": "*", "x": "*", "X": "*", "*": "*", "÷": "/", "/": "/"}
_OP_WORDS = {"+": "加", "-": "减", "*": "乘", "/": "除"}
EXPR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([+\-×xX*÷/])\s*(\d+(?:\.\d+)?)")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
ASCII_WORD_RE = re.compile(r"[A-Za-z]{2,}")

AI_PROMPT = """你是小学{subject}老师，正在帮一个孩子攻克一道错题。
题目：{question}
标准答案（**严禁出现在 Level 1~3 的任何文字里**）：{answer}
知识点：{knowledge}
孩子的错因：{error_type}

现在请给出【Level {level}：{level_text}】的提示。
硬性要求：
1. 只输出 JSON，不要 Markdown、不要多余文字。
2. {rule}
3. 用小学生听得懂的口语，不说教、不批评孩子。
4. 字段：hint（一句话提示）、error_location（只对 Level 2 必填，指出错在哪一步）、
   steps（字符串数组，只对 Level 3 必填，给步骤；**最后一步的答案写成 □ 占位**）、
   full_explanation（只对 Level 4 必填，完整讲解并写出正确答案）。
5. 不明白就按常识讲，不要编造题目里没有的条件。
"""


# ---------------- 通用小工具 ----------------

def ai_enabled():
    """能不能用大模型：配了 key 且没有打开离线开关（与 phoebe_ai.ai_enabled 同款）。"""
    if os.getenv(OFFLINE_ENV, "").strip().lower() in OFFLINE_VALUES:
        return False
    return bool(getattr(deepseek, "KEY", ""))


def level_name(level):
    """1 方向提示 / 2 错误定位 / 3 步骤引导 / 4 完整讲解（越界值归一到 1）。"""
    return LEVEL_NAMES[_coerce_level(level)]


def levels():
    """四级提示元数据（静态，供前端渲染与测试对照）。

    每项同时带 ``name`` / ``text``（SPEC §5.1）与 ``level_text``（任务书），互为同义字段。
    """
    items = []
    for spec in LEVEL_SPECS:
        item = dict(spec)
        if not item.get("level_text"):
            item["level_text"] = level_name(item["level"])
        items.append(item)
    return items


def _coerce_level(level):
    try:
        value = int(level)
    except (TypeError, ValueError):
        return 1
    return value if 1 <= value <= 4 else 1


def _row_value(question_row, key, default=""):
    """从 ORM 行 / dict / None 里安全取一个字段。"""
    if question_row is None:
        return default
    if isinstance(question_row, dict):
        value = question_row.get(key, default)
    else:
        value = getattr(question_row, key, default)
    return default if value is None else value


def _normalize(text):
    return unicodedata.normalize("NFKC", str(text or "")).strip().lower().replace(" ", "")


def _options_of(question_row):
    options = _row_value(question_row, "options", "")
    if isinstance(options, str):
        try:
            options = json.loads(options) if options.strip() else {}
        except ValueError:
            options = {}
    return options if isinstance(options, dict) else {}


def _correct_answer(question_row):
    """正确答案文本（选择题把字母答案换算成选项内容）。"""
    raw = str(_row_value(question_row, "answer", "")).strip()
    for key, value in _options_of(question_row).items():
        if raw and str(key).strip().upper() == raw.upper():
            return str(value).strip()
    return raw


def _answer_in(text, question_row):
    """文本里是否出现了最终答案（用于「L1~L3 不给答案」的硬校验）。"""
    answer = _normalize(_correct_answer(question_row))
    return bool(answer) and answer in _normalize(text)


def _math_expression(question_row):
    """题干里唯一的「a 运算 b」算式（多步题返回 None）。"""
    matches = EXPR_RE.findall(str(_row_value(question_row, "question", "")))
    return matches[0] if len(matches) == 1 else None


def build_full_explanation(question_row):
    """L4 的完整讲解：题干 + 正确答案 + 原解析（可选）。"""
    question = str(_row_value(question_row, "question", "")).strip()
    answer = _correct_answer(question_row)
    analysis = str(_row_value(question_row, "analysis", "")).strip()
    parts = [f"题目：{question}", f"正确答案：{answer or '（本题未登记答案）'}"]
    if analysis:
        parts.append(f"解析：{analysis}")
    parts.append("现在请你合上答案，用自己的话把这个思路讲一遍，讲清楚了才算真的会了。")
    return "\n".join(parts)


# ---------------- 规则提示（离线可用） ----------------

def _math_steps(question_row, knowledge):
    expression = _math_expression(question_row)
    if expression:
        left, symbol, right = expression
        word = _OP_WORDS.get(_OPERATORS.get(symbol, ""), "运算")
        return [f"算式里是 {left} 与 {right} 两个数做{word}。",
                f"先算 {left} {symbol} {right}，把结果写成 □。",
                "再回头读一遍题目，确认 □ 就是题目在问的那个数。"]
    return [f"先读题，圈出「{knowledge or '题目'}」相关的条件（已知什么、要求什么）。",
            "把条件和问题对齐，弄清楚先求什么、再求什么，再列算式。",
            "算出结果后写进 □，最后检查一遍计算和单位。"]


def _chinese_steps(question_row, knowledge):
    return [f"先读题，抓住关键信息（考的是「{knowledge or '字词'}」）。",
            "把每个选项放回题目或句子里读一遍，看哪个读得通、意思对。",
            "把选中的答案写进 □，再从头读一遍确认没有语病。"]


def _english_steps(question_row, knowledge):
    return [f"先看题目在问什么（考的是「{knowledge or '单词句型'}」）。",
            "把每个选项代进句子读一遍，注意单词拼写和词形。",
            "把选中的答案写进 □，再拼读一遍检查拼写。"]


def _hint_steps(question_row, knowledge):
    """按科目选步骤生成器（L3 步骤骨架，答案用 □ 占位）。"""
    subject = str(_row_value(question_row, "subject", "")).strip()
    if subject == "数学":
        return _math_steps(question_row, knowledge)
    if subject == "语文":
        return _chinese_steps(question_row, knowledge)
    return _english_steps(question_row, knowledge)


def error_location(question_row, error_type=""):
    """L2 用：指出错在哪一步（文字里不出现答案）。"""
    subject = str(_row_value(question_row, "subject", "")).strip()
    kind = str(error_type or "").strip()
    expression = _math_expression(question_row)

    if subject == "数学":
        base = {"计算错误": "错在计算这一步：思路是对的，但加减乘除算错了。",
                "审题错误": "错在读题这一步：题目在问什么还没看准就动笔了。",
                "单位错误": "错在收尾这一步：数的部分对了，单位写错或者忘写了。",
                "步骤错误": "错在中间步骤：先算什么、再算什么这一步顺序乱了。",
                "概念错误": "错在理解这一步：这个知识点的意思还没弄清楚就套公式了。",
                }.get(kind, "错在这一步：算式列出来之后，算出来的数和正确答案对不上。")
        if expression:
            left, symbol, right = expression
            word = _OP_WORDS.get(_OPERATORS.get(symbol, ""), "运算")
            base += f"（要先算 {left} {symbol} {right} 的{word}结果）"
        return base

    if subject == "语文":
        return {"字词错误": "错在字词这一步：形近字或读音混了，把字放进词语里再读一遍。",
                "信息定位错误": "错在定位这一步：答案在短文里的那句话没有划出来。",
                "阅读理解错误": "错在理解这一步：句子的意思还没有读懂就去选了。",
                "表达错误": "错在表达这一步：意思想到了，但句子写得不通顺。",
                }.get(kind, "错在这一步：把选项放回原句里读，会发现有一个字（词）用得不对。")

    return {"单词错误": "错在选词这一步：把意思看错了，句子需要的是另一个词。",
            "拼写错误": "错在拼写这一步：字母顺序错了或者漏写字母了。",
            "语法错误": "错在语法这一步：词形（时态、单复数）和句子对不上。",
            "阅读错误": "错在定位这一步：关键句没有在短文里找到。",
            }.get(kind, "错在这一步：把选项代进句子里读一遍，会发现有一个位置不对。")


def fallback_hint(question_row, level, error_type=""):
    """离线 / 调用失败时的规则文案（纯函数：不联网、不抛异常）。"""
    level = _coerce_level(level)
    subject = str(_row_value(question_row, "subject", "")).strip()
    knowledge = str(_row_value(question_row, "knowledge", "")).strip()
    result = {"level": level, "level_text": level_name(level), "hint": "",
              "error_location": "", "steps": [], "full_explanation": ""}

    if level == 1:
        if subject == "数学":
            result["hint"] = (f"这道题考的是「{knowledge}」。先读两遍题，圈出已知的数和要求的问题，"
                              "想清楚它们之间是加减乘除里的哪一种，再动笔。")
        elif subject == "语文":
            result["hint"] = (f"这道题考的是「{knowledge}」。先读题，再想想考的是读音、字形、"
                              "词义还是句子的意思，别急着选。")
        else:
            result["hint"] = (f"这道题考的是「{knowledge}」。先看看题目在问什么，"
                              "把每个选项读一遍，注意单词的拼写和词形。")
        return result

    if level == 2:
        result["error_location"] = error_location(question_row, error_type)
        result["hint"] = result["error_location"] + " 慢慢来，我们把这一步单独练一遍。"
        return result

    if level == 3:
        result["steps"] = _hint_steps(question_row, knowledge)
        result["hint"] = "按下面三步自己做一遍，最后一步的 □ 请你来填：\n" + \
            "\n".join(f"{index}. {step}" for index, step in enumerate(result["steps"], 1))
        return result

    result["steps"] = _hint_steps(question_row, knowledge)
    result["full_explanation"] = build_full_explanation(question_row)
    result["hint"] = result["full_explanation"]
    return result


# ---------------- 四级提示老师 ----------------

class AIRecoveryTeacher:
    """分层提示老师：L1 方向 → L2 定位 → L3 步骤 → L4 完整讲解（含答案）。"""

    @staticmethod
    def levels():
        """四级元数据：[{level, name, text, gives, withhold}, ...]。"""
        return levels()

    @staticmethod
    def level_name(level):
        """1 方向提示 / 2 错误定位 / 3 步骤引导 / 4 完整讲解。"""
        return level_name(level)

    @staticmethod
    def fallback_hint(question_row, level, error_type=""):
        """离线规则文案。"""
        return fallback_hint(question_row, level, error_type)

    def teach(self, question_row, *, knowledge=None, error_type="", level=1,
              student=None, use_ai=True):
        """给一道错题生成第 ``level`` 级提示。

        返回 ``{level, level_text, hint, source, error_location, steps, full_explanation}``。
        ``source`` 为 ``"ai"`` 或 ``"fallback_offline" / "fallback_no_key" /
        "fallback_error" / "fallback_disabled"``。任何异常都降级，**不抛**。
        """
        level = _coerce_level(level)
        if knowledge:
            row = dict(_row_dict(question_row))
            row["knowledge"] = knowledge
            question_row = row

        rule = fallback_hint(question_row, level, error_type)
        result = dict(rule)
        result["source"] = "rule"

        if not use_ai:
            result["source"] = "fallback_disabled"
            return result
        if not ai_enabled():
            offline = os.getenv(OFFLINE_ENV, "").strip().lower() in OFFLINE_VALUES
            result["source"] = "fallback_offline" if offline else "fallback_no_key"
            return result

        payload, reason = _ai_teach(question_row, level=level, error_type=error_type)
        if payload is None:
            result["source"] = f"fallback_{reason.split(':')[0]}"
            return result

        merged = _merge_ai(result, payload, level)
        if not _level_pure(merged, level, question_row):
            result["source"] = "fallback_answer_leak"
            return result
        merged["source"] = "ai"
        return merged

    def explain(self, question_row, *, knowledge=None, error_type="", student=None, use_ai=True):
        """便捷入口：直接要 L4 完整讲解。"""
        return self.teach(question_row, knowledge=knowledge, error_type=error_type,
                          level=4, student=student, use_ai=use_ai)


def _row_dict(question_row):
    if isinstance(question_row, dict):
        return question_row
    if question_row is None:
        return {}
    return {key: _row_value(question_row, key, "") for key in
            ("subject", "knowledge", "difficulty", "question", "answer", "qtype",
             "options", "analysis")}


def _ai_teach(question_row, *, level, error_type):
    """调 DeepSeek 取一级提示。返回 ``(payload, reason)``，失败时 payload 为 None。"""
    rule_hint = {1: "只给思考方向，说清楚这道题在考什么、先看哪里；**不要**提到任何数或答案。",
                 2: "指出孩子错在哪一步，说清楚为什么这一步会错；**不要**说出正确答案。",
                 3: "把解题步骤一步一步写出来；最后一步的答案用 □ 代替，**不要**写出答案。",
                 4: "完整讲解这道题，必须明确指出正确答案，并说清为什么是这个答案。"}[level]
    prompt = AI_PROMPT.format(
        subject=_row_value(question_row, "subject", ""),
        question=_row_value(question_row, "question", ""),
        answer=_correct_answer(question_row),
        knowledge=_row_value(question_row, "knowledge", "") or "（未标注）",
        error_type=error_type or "（未标注）",
        level=level, level_text=level_name(level), rule=rule_hint)

    try:
        response = requests.post(
            deepseek.API_URL,
            headers={"Authorization": f"Bearer {getattr(deepseek, 'KEY', '')}"},
            json={"model": "deepseek-chat",
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"},
                  "temperature": 0.5},
            timeout=AI_TIMEOUT)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
    except Exception as exc:                                  # noqa: BLE001 - 一律降级
        return None, f"error:{type(exc).__name__}"

    if not isinstance(parsed, dict):
        return None, "error:parse"
    text = str(parsed.get("hint") or "").strip()
    if not text:
        return None, "error:empty"
    return parsed, "ai"


def _extract_json(content):
    """优先用 deepseek 的解析器，失败则自己截取第一个 JSON 对象。"""
    try:
        parsed = deepseek._extract_json(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:                                         # noqa: BLE001
        pass
    match = re.search(r"\{.*\}", str(content or ""), re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


def _merge_ai(rule_result, payload, level):
    """把 AI 返回的字段并进规则结果（规则文案永远保留为兜底）。"""
    merged = dict(rule_result)
    merged["hint"] = str(payload.get("hint") or "").strip() or rule_result["hint"]
    steps = payload.get("steps")
    if isinstance(steps, list) and steps:
        merged["steps"] = [str(item).strip() for item in steps if str(item).strip()]
    if level == 2:
        merged["error_location"] = (str(payload.get("error_location") or "").strip()
                                    or rule_result["error_location"])
    if level == 4:
        merged["full_explanation"] = (str(payload.get("full_explanation") or "").strip()
                                      or rule_result["full_explanation"])
    return merged


def _level_pure(result, level, question_row):
    """L1~L3 不允许出现最终答案；出现即判为不合格（降级回规则文案）。"""
    if level >= 4:
        return True
    texts = [result.get("hint"), result.get("error_location"), result.get("full_explanation")]
    texts += list(result.get("steps") or [])
    return not any(_answer_in(text, question_row) for text in texts if text)


# ---------------- 变式题生成 ----------------

LEVEL_CHOICES_LETTERS = ("A", "B", "C", "D")


def _make_choice(question, answer, distractors, analysis):
    """组一道选择题：正确答案 + 3 个干扰项洗牌后分配 A/B/C/D。"""
    import random

    items = [answer] + [item for item in distractors if str(item) != str(answer)][:3]
    if len(items) < 4:
        return None
    random.shuffle(items)
    options = {letter: items[index] for index, letter in enumerate(LEVEL_CHOICES_LETTERS[:len(items)])}
    correct = next(letter for letter, value in options.items() if value == answer)
    return {"question": str(question), "answer": correct, "options": options,
            "qtype": "choice", "analysis": str(analysis)}


def _math_template(seed, difficulty, variant=0):
    import random

    knowledge = str(seed.get("knowledge") or "")
    pairs = _math_number_pairs(variant)
    if "周长" in knowledge:
        length, width = _math_number_pairs(variant)[variant % len(_math_number_pairs(variant))]
        return _make_choice(
            f"一个长方形的长是 {length} 厘米，宽是 {width} 厘米，它的周长是多少厘米？",
            f"{(length + width) * 2}厘米",
            [f"{length * width}厘米", f"{length + width}厘米", f"{(length + width) * 2 + 2}厘米"],
            f"长方形周长 =（长 + 宽）× 2 =（{length} + {width}）× 2 = {(length + width) * 2} 厘米。")
    if "面积" in knowledge:
        length, width = _math_number_pairs(variant)[variant % len(_math_number_pairs(variant))]
        return _make_choice(
            f"一个长方形的长是 {length} 米，宽是 {width} 米，它的面积是多少平方米？",
            f"{length * width}平方米",
            [f"{(length + width) * 2}平方米", f"{length + width}平方米", f"{length * width + 1}平方米"],
            f"长方形面积 = 长 × 宽 = {length} × {width} = {length * width} 平方米。")

    top = (10 if int(difficulty or 50) < 50 else 100) + int(variant) * 3
    operators = _math_operators(seed)
    operator = operators[variant % len(operators)]
    if operator == "+":
        a, b = random.randint(5, top), random.randint(5, top)
        answer, task = a + b, f"算一算：{a} + {b} = ？"
    elif operator == "-":
        a = random.randint(max(2, top // 2), top)
        b = random.randint(1, a)
        answer, task = a - b, f"算一算：{a} − {b} = ？"
    elif operator == "*":
        a, b = random.randint(2, 9), random.randint(2, 9)
        answer, task = a * b, f"算一算：{a} × {b} = ？"
    else:
        b = random.randint(2, 9)
        answer = random.randint(2, 9)
        a = b * answer
        task = f"算一算：{a} ÷ {b} = ？"

    distractors = [f"{answer + 1}", f"{answer - 1}", f"{answer + 10}"]
    return _make_choice(task, f"{answer}", distractors,
                        f"认真算一遍：{task.replace('算一算：', '').replace(' = ？', '')} = {answer}。")


def _math_operators(seed):
    """根据知识点 / 题干词识别适用运算符；识别不出时给出四则混合候选。"""
    text = f"{seed.get('knowledge') or ''}{seed.get('question') or ''}"
    operators = []
    if any(token in text for token in ("除法", "除", "÷")):
        operators.append("/")
    if any(token in text for token in ("乘法", "乘", "×", "口诀")):
        operators.append("*")
    if any(token in text for token in ("减法", "减", "−", "-")):
        operators.append("-")
    if any(token in text for token in ("加法", "加", "和是", "一共", "+")):
        operators.append("+")
    return operators or ["+", "-", "*"]


def _math_number_pairs(variant):
    """周长 / 面积题的数字池：池内每个组合互不相同，同一次生成按 variant 直接取用。"""
    return [(5, 3), (6, 4), (8, 2), (7, 5), (9, 3), (10, 4), (12, 5), (4, 4)]


def _pick(items, variant):
    """按 ``variant`` 确定性地池中取一项（不同 variant 取不同项，保证一次生成内题干互不相同）。"""
    if not items:
        return None
    return items[int(variant) % len(items)]


_METAPHOR_CASES = [
    ("弯弯的月亮像一只小船。", "小鸟在树上唱歌。", "我今天很高兴。"),
    ("妹妹的脸蛋红得像苹果。", "弟弟跑得很快。", "妈妈在厨房做饭。"),
    ("白白的云朵像一团棉花。", "天上的云朵真漂亮。", "风把门吹开了。"),
    ("荷叶圆圆的像一把绿伞。", "池子里有很多小鱼。", "夏天的荷花开得漂亮。"),
    ("蒙蒙的细雨像一根根细丝。", "外面下着小雨。", "小明撑着一把伞。"),
    ("天上的星星像一颗颗宝石。", "夜里很安静。", "月亮升起来了。"),
]


def _chinese_template(seed, difficulty, variant=0):
    import random

    knowledge = str(seed.get("knowledge") or "")
    if "反义词" in knowledge:
        pairs = [("大", "小", ["多", "高", "长"]), ("上", "下", ["左", "右", "前"]),
                 ("冷", "热", ["凉", "暖", "湿"]), ("弯", "直", ["曲", "软", "斜"]),
                 ("高兴", "难过", ["快乐", "开心", "欢喜"]), ("开", "关", ["推", "拉", "开"]),
                 ("多", "少", ["忙", "闲", "满"]), ("快", "慢", ["急", "忙", "双"])]
        word, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{word}」的反义词是下面哪一个词？", answer, wrong,
                            f"「{word}」和「{answer}」意思相反，是一对反义词。")
    if "近义词" in knowledge or "词语搭配" in knowledge:
        pairs = [("高兴", "快乐", ["难过", "生气", "伤心"]), ("美丽", "漂亮", ["难看", "丑陋", "丑恶"]),
                 ("著名", "有名", ["无名", "普通", "平凡"]), ("立刻", "马上", ["慢慢", "以后", "从前"]),
                 ("寒冷", "冰冷", ["炎热", "温暖", "凉爽"]), ("辽阔", "宽广", ["狭窄", "拥挤", "短小"]),
                 ("仔细", "细心", ["粗心", "马匹", "大意"])]
        word, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{word}」的近义词是哪一个词？", answer, wrong,
                            f"「{word}」和「{answer}」意思很接近，是近义词。")
    if "量词" in knowledge or "组词" in knowledge:
        pairs = [("一（  ）小鸟", "只", ["条", "本", "棵"]), ("一（  ）铅笔", "支", ["头", "张", "条"]),
                 ("一（  ）大树", "棵", ["只", "把", "块"]), ("一（  ）白云", "朵", ["条", "张", "片"]),
                 ("一（  ）教室", "间", ["块", "头", "只"]), ("一（  ）花园", "座", ["把", "朵", "条"]),
                 ("一（  ）书本", "本", ["支", "棵", "朵"])]
        task, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"{task}，括号里应该填哪个字？", answer, wrong,
                            f"{task.replace('（  ）', answer)} 是这个量词的常见搭配。")
    if "笔画" in knowledge or "笔顺" in knowledge:
        pairs = [("「十」一共有几画？", "2画", ["1画", "3画", "4画"]),
                 ("「口」一共有几画？", "3画", ["2画", "4画", "5画"]),
                 ("「人」一共有几画？", "2画", ["1画", "3画", "4画"]),
                 ("「小」一共有几画？", "3画", ["2画", "4画", "5画"]),
                 ("「山」一共有几画？", "3画", ["2画", "4画", "5画"]),
                 ("「日」一共有几画？", "4画", ["3画", "5画", "6画"]),
                 ("「月」一共有几画？", "4画", ["3画", "5画", "6画"])]
        task, answer, wrong = _pick(pairs, variant)
        return _make_choice(task, answer, wrong, f"{task}{answer}，照着笔顺数一数就清楚了。")
    if "比喻" in knowledge or "修辞" in knowledge:
        good, m2, m3, m4, m5, m6 = [item[0] for item in _METAPHOR_CASES]
        plain1, plain2, plain3 = _METAPHOR_CASES[0][1], _METAPHOR_CASES[0][2], _METAPHOR_CASES[1][1]
        # 同一知识点下 5 种不同问法，保证一次生成内题干互不相同
        frames = [
            ("下面哪一句用了比喻的手法？", good,
             [plain1, plain2, m2, plain3], "把一样事物比作另一样，就是比喻句。"),
            ("下面哪一句**没有**用比喻？", plain1,
             [good, plain2, m3, m4], "比喻句一定有「像 / 好像 / 仿佛」把两样事物连起来。"),
            ("下面哪一句把事物比作了另一样事物？", m3,
             [plain2, plain3, good, m6], "把两样事物放在一起比，才是比喻。"),
            ("下面哪一句是比喻句？", m5,
             [plain1, plain2, plain3, m4], "比喻句里本体和喻体都要出现。"),
            ("下面哪一句不是比喻句？", plain2,
             [m6, good, m3, m5], "没有「像」也不用两样事物相比的句子不是比喻。"),
            ("哪一句用了打比方的方法？", m4,
             [plain1, plain3, plain2, m2], "打比方就是比喻，要找到本体和喻体。"),
        ]
        task, answer, wrong, analysis = _pick(frames, variant)
        return _make_choice(task, answer, wrong, analysis)
    pairs = [("「大」的拼音是？", "dà", ["dá", "tà", "bà"]), ("「花」的拼音是？", "huā", ["huá", "hà", "guā"]),
             ("「水」的拼音是？", "shuǐ", ["shuī", "suǐ", "shǔi"]), ("「天」的拼音是？", "tiān", ["tān", "diān", "tiàn"]),
             ("「火」的拼音是？", "huǒ", ["huō", "hǒu", "huò"]), ("「土」的拼音是？", "tǔ", ["tū", "dǔ", "tù"]),
             ("「云」的拼音是？", "yún", ["yūn", "yǔn", "yuán"])]
    task, answer, wrong = _pick(pairs, variant)
    return _make_choice(task, answer, wrong, f"{task}{answer}，读的时候注意声调。")




def _english_template(seed, difficulty, variant=0):
    import random

    knowledge = str(seed.get("knowledge") or "")
    if "复数" in knowledge:
        pairs = [("book", "books", ["bookes", "book", "bookies"]), ("box", "boxes", ["boxs", "box", "boxen"]),
                 ("child", "children", ["childs", "childes", "child"]),
                 ("bus", "buses", ["buss", "busen", "bus"]),
                 ("apple", "apples", ["applies", "applees", "apple"]),
                 ("man", "men", ["mans", "mens", "man"])]
        word, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{word}」的复数形式是下面哪一个？", answer, wrong,
                            f"「{word}」的复数是「{answer}」，要按规则变化。")
    if "过去" in knowledge or "ed" in knowledge:
        pairs = [("play", "played", ["playd", "plaied", "playing"]),
                 ("study", "studied", ["studyed", "studys", "studing"]),
                 ("stop", "stopped", ["stoped", "stoping", "stops"]),
                 ("look", "looked", ["lookd", "lookied", "looking"]),
                 ("watch", "watched", ["watchs", "watcheded", "watching"]),
                 ("go", "went", ["goed", "going", "gos"])]
        word, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{word}」的过去式是下面哪一个？", answer, wrong,
                            f"「{word}」的过去式是「{answer}」。")
    if "进行时" in knowledge or "doing" in knowledge or "分词" in knowledge:
        pairs = [("run", "running", ["runing", "runs", "runned"]),
                 ("write", "writing", ["writting", "writes", "writed"]),
                 ("eat", "eating", ["eateing", "eats", "eated"]),
                 ("read", "reading", ["readding", "reads", "readed"]),
                 ("swim", "swimming", ["swiming", "swims", "swimed"]),
                 ("make", "making", ["makeing", "makes", "maked"])]
        word, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{word}」的现在分词是下面哪一个？", answer, wrong,
                            f"「{word}」的现在分词是「{answer}」，注意词尾变化。")
    if "颜色" in knowledge:
        pairs = [("红色", "red", ["blue", "green", "black"]), ("蓝色", "blue", ["red", "yellow", "white"]),
                 ("黄色", "yellow", ["green", "orange", "pink"]), ("绿色", "green", ["grey", "brown", "purple"]),
                 ("黑色", "black", ["white", "blue", "brown"]), ("白色", "white", ["black", "red", "pink"])]
        meaning, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{meaning}」用英语怎么说？", answer, wrong,
                            f"「{meaning}」的英语单词是「{answer}」，属于颜色类词汇。")
    if "动物" in knowledge:
        pairs = [("猫", "cat", ["dog", "pig", "cow"]), ("狗", "dog", ["cat", "duck", "fish"]),
                 ("鸟", "bird", ["bear", "horse", "sheep"]), ("鱼", "fish", ["bird", "cat", "frog"]),
                 ("马", "horse", ["house", "sheep", "mouse"]), ("兔子", "rabbit", ["tiger", "monkey", "panda"])]
        meaning, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{meaning}」用英语怎么说？", answer, wrong,
                            f"「{meaning}」的英语单词是「{answer}」，属于动物类词汇。")
    if "数字" in knowledge:
        pairs = [("三", "three", ["tree", "thirteen", "thirty"]), ("五", "five", ["fifth", "four", "nine"]),
                 ("八", "eight", ["eighty", "eighteen", "egg"]), ("一", "one", ["two", "once", "on"]),
                 ("九", "nine", ["ninety", "nineteen", "nice"]), ("十", "ten", ["teen", "tenth", "tent"])]
        meaning, answer, wrong = _pick(pairs, variant)
        return _make_choice(f"「{meaning}」用英语怎么写？", answer, wrong,
                            f"「{meaning}」的英语单词是「{answer}」，属于数字类词汇。")
    pairs = [("I ___ a student.", "am", ["is", "are", "be"]), ("She ___ my friend.", "is", ["am", "are", "be"]),
             ("They ___ in the classroom.", "are", ["am", "is", "be"]),
             ("He ___ a doctor.", "is", ["am", "are", "be"]),
             ("We ___ good friends.", "are", ["am", "is", "be"]),
             ("You ___ very kind.", "are", ["am", "is", "be"])]
    task, answer, wrong = _pick(pairs, variant)
    return _make_choice(f"选一选，把句子补完整：{task}", answer, wrong,
                        f"「{task.replace('___', answer)}」主语和 be 动词要对应。")


def _rule_template(seed, difficulty, variant=0):
    subject = str(seed.get("subject") or "").strip()
    if subject == "语文":
        return _chinese_template(seed, difficulty, variant)
    if subject == "英语":
        return _english_template(seed, difficulty, variant)
    return _math_template(seed, difficulty, variant)


class VariantQuestionGenerator:
    """变式题生成器：AI 生成 → 过审 → 不过审丢弃 → 规则模板补足。"""

    def __init__(self, validator=None):
        self.validator = validator or QuestionValidator()

    def validate_variant(self, data, *, subject, knowledge, difficulty):
        """调用 ``validator.QuestionValidator.validate`` 做质量审核（唯一真相源）。"""
        payload = dict(data or {})
        payload.setdefault("subject", subject)
        if knowledge:
            payload.setdefault("knowledge", knowledge)
        return self.validator.validate(payload, subject=subject, knowledge=knowledge,
                                       difficulty=difficulty)

    def generate(self, question_row, *, count=1, difficulty=None, knowledge=None, use_ai=True):
        """生成 ``count`` 道同知识点的变式题（每题都带 ``validation``）。"""
        import random

        try:
            total = max(0, int(count))
        except (TypeError, ValueError):
            total = 1
        if total == 0:
            return []

        seed = _row_dict(question_row)
        row_subject = str(seed.get("subject") or "").strip() or "数学"
        target_knowledge = str(knowledge or seed.get("knowledge") or "").strip()
        target_difficulty = difficulty if difficulty is not None else (seed.get("difficulty") or 50)

        items, seen = [], set()
        if use_ai and ai_enabled():
            for candidate in self._ai_variants(seed, total=total, difficulty=target_difficulty):
                item = self._finalize(candidate, row_subject, target_knowledge, target_difficulty)
                if item and item["question"] not in seen:
                    seen.add(item["question"])
                    items.append(item)
                if len(items) >= total:
                    return items[:total]

        pool = list(range(6))
        attempt = 0
        while attempt < max(48, total * 6) and len(items) < total:
            variant = _pick(pool, attempt)
            attempt += 1
            candidate = _rule_template(seed, target_difficulty, variant)
            if not candidate:
                continue
            item = self._finalize(candidate, row_subject, target_knowledge, target_difficulty)
            if not item or item["question"] in seen:
                continue
            seen.add(item["question"])
            items.append(item)

        index = 0
        while len(items) < total and items:              # 模板池很小时允许重复复用
            items.append(dict(items[index % len(items)]))
            index += 1
        return items[:total]

    def _finalize(self, candidate, subject, knowledge, difficulty):
        """补字段 + 过审；``passed`` 为假的题返回 None（丢弃）。"""
        data = dict(candidate)
        data.setdefault("subject", subject)
        data["knowledge"] = knowledge or data.get("knowledge") or ""
        data["difficulty"] = int(difficulty or 50)
        data["qtype"] = data.get("qtype") or "choice"
        data["options"] = data.get("options") or {}
        data["source"] = "rule"
        validation = self.validate_variant(data, subject=subject, knowledge=data["knowledge"],
                                           difficulty=data["difficulty"])
        if not (isinstance(validation, dict) and validation.get("passed")):
            return None
        return {"question": str(data.get("question") or "").strip(),
                "answer": str(data.get("answer") or "").strip(),
                "options": data["options"], "qtype": data["qtype"],
                "knowledge": data["knowledge"], "difficulty": data["difficulty"],
                "analysis": str(data.get("analysis") or "").strip(),
                "source": data["source"], "validation": validation}

    def _ai_variants(self, seed, *, total, difficulty):
        """调 DeepSeek 生成变式题（失败返回空列表，交给规则模板补足）。"""
        prompt = f"""你是小学{seed.get('subject') or ''}老师。请照着一道错题出 {total} 道同知识点的变式题。
原题：{seed.get('question')}
知识点：{seed.get('knowledge')}；难度：{difficulty}/100
只输出 JSON，格式：
{{"variants":[{{"question":"题干","options":{{"A":"","B":"","C":"","D":""}},"answer":"正确选项字母","analysis":"解析"}}]}}
要求：选项 4 个且互不相同，答案必须是正确选项字母，不能出现「以上都对」这类选项。"""
        try:
            response = requests.post(
                deepseek.API_URL,
                headers={"Authorization": f"Bearer {getattr(deepseek, 'KEY', '')}"},
                json={"model": "deepseek-chat",
                      "messages": [{"role": "user", "content": prompt}],
                      "response_format": {"type": "json_object"},
                      "temperature": 0.8},
                timeout=AI_TIMEOUT)
            response.raise_for_status()
            parsed = _extract_json(response.json()["choices"][0]["message"]["content"])
            variants = (parsed or {}).get("variants") or []
        except Exception:                                     # noqa: BLE001 - 降级到规则模板
            return []

        results = []
        for candidate in variants:
            if not isinstance(candidate, dict):
                continue
            candidate = dict(candidate)
            candidate["source"] = "ai"
            results.append(candidate)
        return results


DEFAULT_TEACHER = AIRecoveryTeacher()
DEFAULT_GENERATOR = VariantQuestionGenerator()


def teach(question_row, *, knowledge=None, error_type="", level=1, student=None, use_ai=True):
    """模块级入口：默认老师的 ``teach``。"""
    return DEFAULT_TEACHER.teach(question_row, knowledge=knowledge, error_type=error_type,
                                 level=level, student=student, use_ai=use_ai)


def generate_variants(question_row, *, count=1, difficulty=None, knowledge=None, use_ai=True):
    """模块级入口：默认生成器的 ``generate``。"""
    return DEFAULT_GENERATOR.generate(question_row, count=count, difficulty=difficulty,
                                      knowledge=knowledge, use_ai=use_ai)


def validate_variant(data, *, subject, knowledge, difficulty):
    """模块级入口：默认生成器的 ``validate_variant``。"""
    return DEFAULT_GENERATOR.validate_variant(data, subject=subject, knowledge=knowledge,
                                              difficulty=difficulty)
