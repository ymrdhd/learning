# ==============================================================
# 能力契约｜V2.7 概念性误解检测与纠偏：同一错误逻辑反复出现且自信度高时标记 misconception（纯函数）
# 入口：MISCONCEPTION_TEXT / CONFLICT_PAIRS / DETECT_WINDOW / MIN_REPEAT / SURE_KEYS /
#       MisconceptionEngine / DEFAULT_ENGINE / detect / remediation / conflict_pair / summarize
# 依赖：deep_learning.root_cause（根因类型与中文标签）
# 不负责：根因判定本身 → root_cause.py；掌握度调整 → mastery.py；落库 → deep_learning/engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py（作答后与每日计划生成时）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 概念性误解（Misconception）检测与纠偏（需求 §二十二）。

触发条件（**两个都要满足**）：

1. 同一知识上**多次采用同一种错误逻辑**（同一 ``root_cause_type`` 反复出现）；
2. 学生对这些题**自信度较高**（🙂 很确定 / 🤔 有点确定）。

处理方式**不是继续刷题**，而是：

    重新解释概念 → 对比错误逻辑与正确逻辑 → 然后重新验证

本模块只做判定与话术，不调用 AI、不碰数据库。
"""

from deep_learning import root_cause as root_cause_module

# 判定窗口与阈值
DETECT_WINDOW = 6          # 只看最近 6 条记录
MIN_REPEAT = 2             # 同一错误逻辑出现 >= 2 次
SURE_KEYS = ("sure", "maybe")   # 自信度较高的两档

MISCONCEPTION_TEXT = {
    "CONCEPT_GAP": "对概念的理解整块偏了",
    "RELATIONSHIP_MODEL_ERROR": "数量关系的理解整块偏了",
    "PROCEDURE_ERROR": "一直用错了步骤顺序",
    "UNIT_ERROR": "单位/进率一直记反了",
    "READING_ERROR": "读题时总是抓错重点",
    "INFERENCE_ERROR": "推断时总是用错了线索",
    "VOCABULARY_GAP": "对某些字词的理解一直偏了",
    "GRAMMAR_GAP": "某条语法规则一直记成了错的版本",
    "SPELLING_ERROR": "拼写时一直用同一个错的组合",
    "TEXT_INFORMATION_MISSED": "读文时总是漏掉同一类信息",
    "TRANSFER_GAP": "把方法记成了只会用在原题型上",
}

# 错误逻辑 vs 正确逻辑（需求 §二十二：对比错误逻辑与正确逻辑）
CONFLICT_PAIRS = {
    "CONCEPT_GAP": ("觉得只要记住算法的样子就行", "先说清楚它到底在表示什么，再算"),
    "RELATIONSHIP_MODEL_ERROR": ("看到两个数就直接相加减", "先想清楚谁和谁有关系、关系是什么"),
    "PROCEDURE_ERROR": ("先算哪一步凭感觉", "固定的顺序：先看清问题，再列式，最后算"),
    "UNIT_ERROR": ("单位只是写在答案后面的字", "单位必须同时参与计算，答案也要带单位"),
    "READING_ERROR": ("题目扫一眼就开始算", "先圈出题目给了什么、问的是什么"),
    "INFERENCE_ERROR": ("按自己的想法猜结论", "结论必须有原文里的句子支持"),
    "VOCABULARY_GAP": ("遇到不认识的字词就跳过", "先猜意思，再放到句子里验证"),
    "GRAMMAR_GAP": ("按中文语序直接说英文", "先判断时态和主语，再决定动词形式"),
    "SPELLING_ERROR": ("按读音随便拼", "按音节拆开，一个音节一个音节拼"),
    "TEXT_INFORMATION_MISSED": ("凭印象回答", "回到原文一句一句找依据"),
    "TRANSFER_GAP": ("只照着例题的样子做", "先问自己：这道题真正要我做什么"),
}

DEFAULT_PAIR = ("按自己熟悉的做法直接上手", "先停下来想一想这道题的核心知识是什么")

# 纠偏动作（明确禁止：单纯继续大量刷题，需求 §二十二）
REMEDIATION_STEPS = (
    "重新解释概念（用孩子听得懂的话说一遍）",
    "把孩子原来的想法说出来，再和正确的想法对比",
    "只做 1~2 道验证题，确认想法已经改过来了",
)
FORBIDDEN = "不要在这时候继续大量刷同类题 —— 刷题只会把错的思路练得更熟。"


class MisconceptionEngine:
    """概念性误解检测器（纯函数）。"""

    def detect(self, records, window=DETECT_WINDOW, min_repeat=MIN_REPEAT):
        """records 为时间倒序的作答记录（dict 或对象）。

        每条形如 ``{"root_cause_type", "confidence", "correct", "knowledge_id"}``。
        返回 ``{"possible_misconception", "root_cause_type", "count", "confidence",
        "text", "message"}``。
        """
        recent = list(records or ())[: max(1, int(window or DETECT_WINDOW))]

        buckets = {}
        sure_total = 0
        wrong_total = 0

        for item in recent:
            if self._get(item, "correct") is True:
                continue
            if str(self._get(item, "result") or "").strip().lower() == "correct":
                continue

            wrong_total += 1
            key = str(self._get(item, "confidence") or "").strip().lower()
            cause = str(self._get(item, "root_cause_type") or "").strip().upper()
            if not cause:
                continue
            buckets.setdefault(cause, []).append(key)
            if key in SURE_KEYS:
                sure_total += 1

        if not buckets:
            return self._empty()

        best_cause = None
        best_count = 0
        best_sure = 0
        for cause, keys in buckets.items():
            sure = sum(1 for key in keys if key in SURE_KEYS)
            if len(keys) > best_count or (len(keys) == best_count and sure > best_sure):
                best_cause, best_count, best_sure = cause, len(keys), sure

        if best_cause is None or best_count < int(min_repeat or MIN_REPEAT) or best_sure < 1:
            return self._empty()

        confidence = min(0.95, 0.45 + 0.15 * best_count + 0.10 * best_sure)
        text = MISCONCEPTION_TEXT.get(best_cause, "同一个地方一直理解偏了")

        return {
            "possible_misconception": True,
            "root_cause_type": best_cause,
            "count": best_count,
            "sure_count": best_sure,
            "wrong_total": wrong_total,
            "confidence": round(confidence, 2),
            "text": text,
            "message": "他在同一个地方用同一种想法做错了 %d 次，而且挺有把握 —— 建议先纠正想法，别急着刷题。" % best_count,
        }

    def remediation(self, knowledge="", root_cause_type=""):
        """纠偏方案（重新解释 → 对比逻辑 → 重新验证）。"""
        cause = str(root_cause_type or "").strip().upper()
        pair = CONFLICT_PAIRS.get(cause, DEFAULT_PAIR)
        return {
            "mode": "MISCONCEPTION_REMEDIATION",
            "knowledge": knowledge,
            "root_cause_type": cause,
            "title": "先把想法改过来",
            "wrong_logic": pair[0],
            "right_logic": pair[1],
            "steps": list(REMEDIATION_STEPS),
            "forbidden": FORBIDDEN,
            "verify_count": 2,
            "verify_evidence": "PREREQUISITE_CHECK" if cause == "CONCEPT_GAP" else "STANDARD",
            "child_message": "菲比发现你在一个小地方想反了，我们一起把它掰正，只要两题就好～",
        }

    def conflict_pair(self, root_cause_type):
        pair = CONFLICT_PAIRS.get(str(root_cause_type or "").strip().upper(), DEFAULT_PAIR)
        return {"wrong_logic": pair[0], "right_logic": pair[1]}

    def summarize(self, records, **kwargs):
        result = self.detect(records, **kwargs)
        if result.get("possible_misconception"):
            result["remediation"] = self.remediation(
                root_cause_type=result.get("root_cause_type"))
        else:
            result["remediation"] = None
        return result

    # ---------- 内部 ----------

    @staticmethod
    def _get(item, key, default=None):
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    @staticmethod
    def _empty():
        return {
            "possible_misconception": False,
            "root_cause_type": "",
            "count": 0,
            "sure_count": 0,
            "wrong_total": 0,
            "confidence": 0.0,
            "text": "",
            "message": "",
        }


DEFAULT_ENGINE = MisconceptionEngine()


def detect(records, window=DETECT_WINDOW, min_repeat=MIN_REPEAT):
    return DEFAULT_ENGINE.detect(records, window, min_repeat)


def remediation(knowledge="", root_cause_type=""):
    return DEFAULT_ENGINE.remediation(knowledge, root_cause_type)


def conflict_pair(root_cause_type):
    return DEFAULT_ENGINE.conflict_pair(root_cause_type)


def summarize(records, **kwargs):
    return DEFAULT_ENGINE.summarize(records, **kwargs)


def cause_text(root_cause_type):
    """根因类型的中文描述（转调 root_cause，保持单一出口）。"""
    return root_cause_module.cause_text(root_cause_type)
