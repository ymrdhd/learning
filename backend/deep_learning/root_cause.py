# ==============================================================
# 能力契约｜V2.7 薄弱根因分析：不只「应用题做错了」，而是「为什么错」（纯函数，不碰数据库）
# 入口：ROOT_CAUSES / CAUSE_TEXT / CAUSE_ACTION / RootCauseAnalyzer / DEFAULT_ANALYZER /
#       analyze / causes_for / cause_text / action_of / slip_suspected
# 依赖：无（纯标准库；可独立单测，不 import 任何项目模块）
# 不负责：错因中文描述与错题本 → error_analysis.py；掌握度调整 → mastery.py；落库 → deep_learning/engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py（POST /submit 与 /api/root-cause）、daily_routes.py（前置回补任务）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 薄弱根因分析（需求 §七 / §八 / §九 / §十 / §十一）。

V2.2 的 ``error_analysis.py`` 回答的是"错在哪一类（中文描述）"；本模块回答的是
**"为什么错"**，并给出一条可执行的推荐动作。输入是作答现场的全部信号：

    student_id / subject / knowledge_id / question / student_answer / correct_answer /
    error_type / recent_history / mastery_state / memory_state / prerequisite_state /
    response_time / hint_usage / confidence

输出四件东西：``root_cause_type`` / ``root_cause_confidence`` /
``related_knowledge_ids`` / ``recommended_action``。

三条纪律：

1. **不因为一次错误就判定知识点完全不会**（需求 §八 / §十）——
   历史长期稳定 + 最近多次正确 + 这次突然答错，优先判 ``CARELESS_OR_SLIP``。
2. **不做 AI 判断**：全部规则 + 历史数据 + 知识图谱（需求 §三十四）。
3. 前置知识明显薄弱时才判 ``PREREQUISITE_GAP``，且必须给出**最小**回补对象
   （由 ``prerequisite_tracer.py`` 计算，本模块只消费它的结果）。
"""

# --------------------------------------------------------------
# 根因类型（需求 §八 / §九；英语预留听力）
# --------------------------------------------------------------

MATH_CAUSES = (
    "CONCEPT_GAP",
    "PREREQUISITE_GAP",
    "CALCULATION_ERROR",
    "READING_ERROR",
    "RELATIONSHIP_MODEL_ERROR",
    "PROCEDURE_ERROR",
    "UNIT_ERROR",
    "MEMORY_RECALL_FAILURE",
    "CARELESS_OR_SLIP",
)

CHINESE_CAUSES = (
    "VOCABULARY_GAP",
    "TEXT_INFORMATION_MISSED",
    "INFERENCE_ERROR",
    "CONCEPT_GAP",
    "EXPRESSION_ERROR",
    "MEMORY_RECALL_FAILURE",
    "READING_COMPREHENSION_GAP",
)

ENGLISH_CAUSES = (
    "VOCABULARY_GAP",
    "SPELLING_ERROR",
    "GRAMMAR_GAP",
    "READING_ERROR",
    "MEMORY_RECALL_FAILURE",
    "TRANSFER_GAP",
    "LISTENING_ERROR",          # 预留：未来听力题启用（需求 §九）
)

ROOT_CAUSES = tuple(dict.fromkeys(MATH_CAUSES + CHINESE_CAUSES + ENGLISH_CAUSES))

CAUSES_BY_SUBJECT = {
    "数学": MATH_CAUSES,
    "语文": CHINESE_CAUSES,
    "英语": ENGLISH_CAUSES,
}

DEFAULT_CAUSE = {
    "数学": "CONCEPT_GAP",
    "语文": "READING_COMPREHENSION_GAP",
    "英语": "VOCABULARY_GAP",
}

CAUSE_TEXT = {
    "CONCEPT_GAP": "概念没建立起来",
    "PREREQUISITE_GAP": "前面有个更基础的知识没打牢",
    "CALCULATION_ERROR": "会做，但算错了",
    "READING_ERROR": "题目没读准 / 看漏了条件",
    "RELATIONSHIP_MODEL_ERROR": "数量关系没想明白",
    "PROCEDURE_ERROR": "步骤或方法用错了",
    "UNIT_ERROR": "单位或进率弄错了",
    "MEMORY_RECALL_FAILURE": "学过，但一时想不起来",
    "CARELESS_OR_SLIP": "这次是偶然失误",
    "VOCABULARY_GAP": "字词不认识或不理解",
    "TEXT_INFORMATION_MISSED": "原文里的信息没找全",
    "INFERENCE_ERROR": "推断的方向偏了",
    "EXPRESSION_ERROR": "意思懂，但表达不到位",
    "READING_COMPREHENSION_GAP": "阅读理解的抓手还没建立",
    "SPELLING_ERROR": "单词拼写错了",
    "GRAMMAR_GAP": "语法规则没掌握",
    "TRANSFER_GAP": "背下来了，但换个用法就不会",
    "LISTENING_ERROR": "听力信息没抓准",
}

CAUSE_ACTION = {
    "CONCEPT_GAP": "先重新讲一遍这个概念的意义，再做 1 道例题巩固",
    "PREREQUISITE_GAP": "先做一个短的前置知识任务，验证通过再回到当前知识",
    "CALCULATION_ERROR": "不用重学，做 2 道同类型计算题把准确率提回来",
    "READING_ERROR": "练习圈关键词：先找出题目给了什么、问什么",
    "RELATIONSHIP_MODEL_ERROR": "先画一画数量关系图，再说出每一步为什么这样列式",
    "PROCEDURE_ERROR": "把解题步骤拆开，一步一步对着做一遍",
    "UNIT_ERROR": "把单位之间的进率说出来，再检查一次答案的单位",
    "MEMORY_RECALL_FAILURE": "安排一次主动回忆（先自己想，想不起来再给提示）",
    "CARELESS_OR_SLIP": "不用紧张，再快速做 1 道同类型题确认一下就好",
    "VOCABULARY_GAP": "把这个字词的意思讲清楚，并放进一个句子里",
    "TEXT_INFORMATION_MISSED": "回到原文，把相关信息一句一句划出来",
    "INFERENCE_ERROR": "一起找线索：文中哪句话支持这个结论",
    "EXPRESSION_ERROR": "先口头说一遍意思，再整理成一句话",
    "READING_COMPREHENSION_GAP": "先概括一段话的主要意思，再做题",
    "SPELLING_ERROR": "把单词按音节读出来再拼一遍",
    "GRAMMAR_GAP": "先对比正确说法和错误说法的差别，再各造一个句子",
    "TRANSFER_GAP": "多做几个变式，重点练「换个说法还认不认得」",
    "LISTENING_ERROR": "先听关键词，再听细节",
}

# 同名根因在不同科目下说法不同（英语的 READING_ERROR 不是数学的"题目没读准"）
CAUSE_TEXT_BY_SUBJECT = {
    "英语": {"READING_ERROR": "英文短文没读懂"},
}
CAUSE_ACTION_BY_SUBJECT = {
    "英语": {"READING_ERROR": "先通读短文，找出每段在说什么，再回答题目"},
}

# 中文错因（V2.2 error_analysis 的 error_type）→ 根因类型
ERROR_TYPE_MAP = {
    "数学": (
        (("单位", "进率", "换算"), "UNIT_ERROR"),
        (("计算", "粗心", "算错", "抄错", "口算", "笔算"), "CALCULATION_ERROR"),
        (("审题", "读题", "看错", "漏看", "条件", "题意"), "READING_ERROR"),
        (("数量关系", "关系", "列式", "等量"), "RELATIONSHIP_MODEL_ERROR"),
        (("步骤", "过程", "方法", "解法", "顺序"), "PROCEDURE_ERROR"),
        (("遗忘", "记不", "想不", "忘记", "公式忘"), "MEMORY_RECALL_FAILURE"),
        (("概念", "定义", "意义", "含义", "性质"), "CONCEPT_GAP"),
        (("前置", "基础", "以前学过"), "PREREQUISITE_GAP"),
        (("粗心大意", "马虎", "偶然"), "CARELESS_OR_SLIP"),
    ),
    "语文": (
        (("字词", "读音", "拼音", "词语", "成语", "近义", "反义"), "VOCABULARY_GAP"),
        (("信息", "提取", "原文", "细节", "找出"), "TEXT_INFORMATION_MISSED"),
        (("推断", "推理", "言外之意", "含义", "深层"), "INFERENCE_ERROR"),
        (("表达", "语句", "通顺", "病句", "写作", "造句"), "EXPRESSION_ERROR"),
        (("古诗", "背诵", "默写", "遗忘", "记不"), "MEMORY_RECALL_FAILURE"),
        (("阅读", "理解", "概括", "主旨", "段意"), "READING_COMPREHENSION_GAP"),
        (("概念", "常识", "文体", "修辞", "手法"), "CONCEPT_GAP"),
    ),
    "英语": (
        (("拼写", "字母", "拼错"), "SPELLING_ERROR"),
        (("单词", "词汇", "词义", "词形"), "VOCABULARY_GAP"),
        (("语法", "时态", "单复数", "第三人称", "介词", "语序"), "GRAMMAR_GAP"),
        (("阅读", "短文", "理解", "文章"), "READING_ERROR"),
        (("听力", "听不", "听错"), "LISTENING_ERROR"),
        (("迁移", "变式", "运用", "换个说法"), "TRANSFER_GAP"),
        (("遗忘", "记不", "忘记", "背了"), "MEMORY_RECALL_FAILURE"),
    ),
}

# 计算类关键词（判断"其实会做，只是算错"）
CALC_HINT = ("计算", "口算", "笔算", "竖式", "脱式", "算一算", "=", "＋", "－", "×", "÷", "+", "-", "*", "/")

# 稳定历史阈值（偶然失误判定，需求 §十）
STABLE_MIN_HISTORY = 3
STABLE_CORRECT_RATIO = 0.75
STABLE_MASTERY = 70
FAST_SECONDS = 8              # 异常快
SLOW_SECONDS = 180            # 异常慢/走神

SLIP_CONFIDENCE = 0.72
BASE_CONFIDENCE = 0.45
MAX_CONFIDENCE = 0.92


def _num(text):
    """从文本里抽出第一个数字（含小数/分数转小数），抽不到返回 None。"""
    import re

    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _text_of(value):
    return str(value or "").strip()


def causes_for(subject):
    """某科目允许出现的根因类型。"""
    return CAUSES_BY_SUBJECT.get(_text_of(subject), MATH_CAUSES)


def cause_text(root_cause_type, subject=""):
    """根因类型 → 一句儿童/家长都能懂的中文描述（同名根因可按科目覆写）。"""
    key = _text_of(root_cause_type)
    override = CAUSE_TEXT_BY_SUBJECT.get(_text_of(subject), {})
    return override.get(key) or CAUSE_TEXT.get(key, CAUSE_TEXT["CONCEPT_GAP"])


def action_of(root_cause_type, subject=""):
    key = _text_of(root_cause_type)
    override = CAUSE_ACTION_BY_SUBJECT.get(_text_of(subject), {})
    return override.get(key) or CAUSE_ACTION.get(key, CAUSE_ACTION["CONCEPT_GAP"])


def slip_suspected(*, recent_history=None, mastery_state=None, response_time=0,
                   hint_usage=0, confidence=""):
    """偶然失误判定：历史长期稳定 + 最近多次正确 + 这次突然错 + 没有依赖提示。"""
    if int(hint_usage or 0) > 0:
        return False
    if str(confidence or "").strip().lower() == "guess":
        return False

    history = list(recent_history or ())
    if len(history) < STABLE_MIN_HISTORY:
        return False

    correct = 0
    for item in history[:6]:
        if isinstance(item, dict):
            value = item.get("correct", item.get("result"))
        else:
            value = item
        if value is True or str(value).strip().lower() in ("correct", "true", "1", "对"):
            correct += 1

    examined = min(len(history), 6)
    if examined <= 0 or (correct / examined) < STABLE_CORRECT_RATIO:
        return False

    mastery = None
    if isinstance(mastery_state, dict):
        mastery = mastery_state.get("mastery_score")
    elif mastery_state is not None:
        mastery = getattr(mastery_state, "mastery_score", None)
    if mastery is not None:
        try:
            if float(mastery) < STABLE_MASTERY:
                return False
        except (TypeError, ValueError):
            pass

    return True


class RootCauseAnalyzer:
    """规则版根因分析器（需求 §七）。不调用 AI、不碰数据库。"""

    # ---------- 对外 ----------

    def analyze(self, *, subject="数学", knowledge_id="", question="", student_answer="",
                correct_answer="", error_type="", recent_history=None, mastery_state=None,
                memory_state=None, prerequisite_state=None, response_time=0, hint_usage=0,
                confidence="", variant=False, result="wrong"):
        subject = _text_of(subject) or "数学"
        signals = {}

        cause, confidence_value = self._decide(
            subject=subject, knowledge_id=knowledge_id, question=question,
            student_answer=student_answer, correct_answer=correct_answer,
            error_type=error_type, recent_history=recent_history,
            mastery_state=mastery_state, memory_state=memory_state,
            prerequisite_state=prerequisite_state, response_time=response_time,
            hint_usage=hint_usage, confidence=confidence, variant=variant,
            signals=signals, result=result,
        )

        related = self._related(prerequisite_state)
        allowed = causes_for(subject)
        if cause not in allowed:
            cause = DEFAULT_CAUSE.get(subject, "CONCEPT_GAP")

        return {
            "subject": subject,
            "knowledge_id": _text_of(knowledge_id),
            "root_cause_type": cause,
            "root_cause_confidence": round(min(MAX_CONFIDENCE, max(0.0, confidence_value)), 2),
            "related_knowledge_ids": related,
            "recommended_action": action_of(cause, subject),
            "root_cause_text": cause_text(cause, subject),
            "analysis": self._analysis_text(cause, signals),
            "signals": signals,
            "source": "rule",
        }

    # ---------- 判定 ----------

    def _decide(self, **kw):
        signals = kw["signals"]
        subject = kw["subject"]
        confidence_value = BASE_CONFIDENCE

        # 1) 偶然失误：历史稳 + 最近多对 + 这次突然错（需求 §十）
        if slip_suspected(recent_history=kw["recent_history"],
                          mastery_state=kw["mastery_state"],
                          response_time=kw["response_time"],
                          hint_usage=kw["hint_usage"],
                          confidence=kw["confidence"]):
            signals["stable_history"] = True
            signals["sudden_error"] = True
            return "CARELESS_OR_SLIP", SLIP_CONFIDENCE

        # 2) 前置知识缺口（需求 §十一 / §十二）：前置明显薄弱且当前基础也不稳
        prereq = self._weak_prerequisite(kw["prerequisite_state"])
        if prereq and not self._mastery_high(kw["mastery_state"]):
            signals["weak_prerequisite"] = prereq
            return "PREREQUISITE_GAP", 0.80

        # 3) 迁移失败：标准题会做，换形式不会（需求 §十六）
        if kw["variant"] and self._mastery_high(kw["mastery_state"], line=55):
            signals["variant"] = True
            return "TRANSFER_GAP" if "TRANSFER_GAP" in causes_for(subject) else "PROCEDURE_ERROR", 0.75

        # 4) 记忆提取失败：记忆状态显示需要重学或遗忘风险高（需求 §七）
        if self._memory_failed(kw["memory_state"]):
            signals["memory_state"] = self._memory_snapshot(kw["memory_state"])
            return "MEMORY_RECALL_FAILURE", 0.70

        # 5) 中文错因映射（V2.2 error_type）
        mapped = self._from_error_type(subject, kw["error_type"])
        if mapped:
            signals["error_type"] = _text_of(kw["error_type"])
            confidence_value += 0.15

        # 6) 内容信号：单位 / 计算 / 审题
        content = self._from_content(subject, kw["question"], kw["student_answer"], kw["correct_answer"])
        if content:
            signals.update(content["signals"])
            if mapped is None:
                mapped = content["cause"]
                confidence_value += 0.10

        if mapped:
            return mapped, confidence_value

        # 7) 兜底：按科目给最可能的"概念没建立"
        signals["fallback"] = True
        return DEFAULT_CAUSE.get(subject, "CONCEPT_GAP"), BASE_CONFIDENCE

    # ---------- 信号 ----------

    @staticmethod
    def _mastery_high(mastery_state, line=70):
        value = None
        if isinstance(mastery_state, dict):
            value = mastery_state.get("mastery_score")
        elif mastery_state is not None:
            value = getattr(mastery_state, "mastery_score", None)
        if value is None:
            return False
        try:
            return float(value) >= float(line)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _weak_prerequisite(prerequisite_state):
        """从前置链路里挑出第一个"练过但薄弱"的知识（最小缺失能力）。"""
        if not prerequisite_state:
            return None
        items = prerequisite_state
        if isinstance(items, dict):
            items = items.get("items") or items.get("weak") or []
        for item in items or ():
            if isinstance(item, dict):
                if item.get("weak"):
                    return item
            elif getattr(item, "weak", False):
                return {"knowledge": getattr(item, "knowledge", ""),
                        "mastery_score": getattr(item, "mastery_score", None)}
        return None

    @staticmethod
    def _memory_snapshot(memory_state):
        if memory_state is None:
            return None
        if isinstance(memory_state, dict):
            return {k: memory_state.get(k) for k in ("memory_strength", "forgetting_risk",
                                                     "needs_relearn", "maturity_level")
                    if k in memory_state}
        return {k: getattr(memory_state, k, None) for k in ("memory_strength", "forgetting_risk",
                                                            "needs_relearn", "maturity_level")}

    def _memory_failed(self, memory_state):
        if memory_state is None:
            return False
        if isinstance(memory_state, dict):
            getter = memory_state.get
        else:
            getter = lambda key, default=None: getattr(memory_state, key, default)  # noqa: E731

        if bool(getter("needs_relearn")):
            return True
        risk = getter("forgetting_risk")
        try:
            risk = float(risk or 0.0)
        except (TypeError, ValueError):
            risk = 0.0
        strength = getter("memory_strength") or getter("stability") or 0
        try:
            strength = float(strength or 0.0)
        except (TypeError, ValueError):
            strength = 0.0
        return risk >= 0.6 and strength <= 1.0

    @staticmethod
    def _from_error_type(subject, error_type):
        text = _text_of(error_type)
        if not text:
            return None
        for keywords, cause in ERROR_TYPE_MAP.get(subject, ()):
            for word in keywords:
                if word in text:
                    return cause
        return None

    def _from_content(self, subject, question, student_answer, correct_answer):
        """从题面与答案本身抽信号：单位错 / 算错 / 审题漏条件。"""
        out = {"cause": None, "signals": {}}

        expected = _num(correct_answer)
        got = _num(student_answer)

        if expected is not None and got is not None and expected != got:
            ratio = abs(got) / abs(expected) if expected else 0.0
            if 9.5 <= ratio <= 10.5 or 0.095 <= ratio <= 0.105:
                out["cause"] = "UNIT_ERROR"
                out["signals"]["unit_mismatch"] = True
                return out
            gap = abs(got - expected)
            if gap <= max(1.0, abs(expected) * 0.2):
                out["cause"] = "CALCULATION_ERROR"
                out["signals"]["near_miss"] = True
                return out

        if "单位" in _text_of(question) and out["cause"] is None:
            out["signals"]["unit_words"] = True

        short = len(_text_of(student_answer))
        if _text_of(question) and short <= 1 and subject != "数学":
            out["cause"] = "READING_ERROR" if subject == "英语" else "TEXT_INFORMATION_MISSED"
            out["signals"]["empty_answer"] = True
            return out

        return out

    @staticmethod
    def _related(prerequisite_state):
        if not prerequisite_state:
            return []
        items = prerequisite_state
        if isinstance(items, dict):
            items = items.get("items") or items.get("weak") or []
        out = []
        for item in items or ():
            if isinstance(item, dict):
                if item.get("weak") and item.get("knowledge"):
                    out.append(item.get("knowledge"))
            elif getattr(item, "weak", False):
                name = getattr(item, "knowledge", None)
                if name:
                    out.append(name)
        return out[:5]

    @staticmethod
    def _analysis_text(cause, signals):
        """给家长/教师看的一句话（儿童端不下发根因术语，只下发友好提示）。"""
        text = cause_text(cause)
        if signals.get("stable_history"):
            return "这个知识一直做得挺稳，这次出错更像是偶然失误，先别急着降低掌握度。"
        if signals.get("weak_prerequisite"):
            name = signals["weak_prerequisite"].get("knowledge") if isinstance(
                signals["weak_prerequisite"], dict) else None
            return "当前知识卡住，更可能卡在更基础的知识上%s。" % ("（%s）" % name if name else "")
        if signals.get("near_miss"):
            return "答案很接近正确答案，属于会做但算错的情况。"
        if signals.get("unit_mismatch"):
            return "答案数量级差了 10 倍左右，判断是单位或进率的问题。"
        if signals.get("variant"):
            return "标准题能做、换形式就卡住，属于迁移缺口而不是完全不会。"
        return "初步判断是%s。" % text


DEFAULT_ANALYZER = RootCauseAnalyzer()


def analyze(**kwargs):
    """模块级快捷入口：DEFAULT_ANALYZER.analyze(**kwargs)。"""
    return DEFAULT_ANALYZER.analyze(**kwargs)
