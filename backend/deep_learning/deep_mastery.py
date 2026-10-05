# ==============================================================
# 能力契约｜V2.7 Deep Mastery 模型：6 个深度等级 + 6 个维度 + 证据驱动升/降级规则（纯函数）
# 入口：LEVELS / LEVEL_BY_KEY / DIMENSIONS / DIMENSION_WEIGHTS / CHILD_STAGES /
#       DeepMasteryModel / DEFAULT_MODEL / level_of / score_of / child_stage / abilities /
#       upgrade_gap / level_dict
# 依赖：deep_learning.evidence（证据强度与命中维度）
# 不负责：掌握度 → mastery.py；记忆状态 → review/memory.py；落库 → deep_learning/engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py、deep_learning/variant_ladder.py、knowledge_map_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 Deep Mastery 模型（需求 §三 / §四 / §五 / §二十六 / §二十七）。

三层分数**不得合并**，各自回答一个不同的问题：

| 层 | 字段 | 回答的问题 | 计算者 |
| --- | --- | --- | --- |
| 掌握度 | ``mastery_score`` | 这个知识**会不会做**？ | mastery.py |
| 深度掌握 | ``deep_mastery`` | 是不是**真的理解**并能灵活迁移？ | 本模块 |
| 记忆状态 | ``memory_state`` | 过一段时间**还记不记得**？ | review/ |

六个维度：recognition（识别）/ understanding（理解）/ application（会做标准题）/
transfer（会灵活运用）/ explanation（能讲清楚）/ retention（长期记住）。

等级与教材年级无关（**不是** ability_stage 的替代品）：

    LEVEL 0 UNKNOWN      信息不足
    LEVEL 1 RECOGNIZE    能够识别
    LEVEL 2 UNDERSTAND   理解概念
    LEVEL 3 APPLY        能做标准题
    LEVEL 4 TRANSFER     换表达或情境仍会做
    LEVEL 5 EXPLAIN      可以用自己的话解释
    LEVEL 6 RETAIN       延迟后仍能独立回忆和使用

关键纪律（需求 §二十七）：**一次正确不能跳到高等级**。升级必须同时满足
分数门槛 + 证据数量 + 证据来源多样性；``RETAIN`` 必须真的有延迟学习证据。
"""

from deep_learning import evidence as evidence_module

# --------------------------------------------------------------
# 等级表（0~6）
# --------------------------------------------------------------

LEVELS = (
    {"level": 0, "key": "UNKNOWN", "label": "信息不足", "icon": "❔",
     "child": "还想考考你", "desc": "还没有足够的证据判断深度"},
    {"level": 1, "key": "RECOGNIZE", "label": "能识别", "icon": "👀",
     "child": "看到会认出来", "desc": "能认出这个知识、但不一定理解"},
    {"level": 2, "key": "UNDERSTAND", "label": "理解概念", "icon": "💡",
     "child": "知道是什么意思", "desc": "理解了概念的含义"},
    {"level": 3, "key": "APPLY", "label": "会做标准题", "icon": "🌿",
     "child": "会做基础题", "desc": "标准题能独立做对"},
    {"level": 4, "key": "TRANSFER", "label": "会灵活运用", "icon": "🌳",
     "child": "换个样子也会做", "desc": "换数字/换说法/换情境仍会做"},
    {"level": 5, "key": "EXPLAIN", "label": "能讲清楚", "icon": "🗣️",
     "child": "能讲给菲比听", "desc": "能用自己的话解释为什么"},
    {"level": 6, "key": "RETAIN", "label": "长期记住", "icon": "⭐",
     "child": "过段时间还记得", "desc": "延迟后仍能独立回忆和使用"},
)

LEVEL_BY_KEY = {item["key"]: item for item in LEVELS}
LEVEL_KEYS = tuple(item["key"] for item in LEVELS)
MAX_LEVEL = 6

# 维度
DIMENSIONS = ("recognition", "understanding", "application",
              "transfer", "explanation", "retention")

DIMENSION_WEIGHTS = {
    "recognition": 0.10,
    "understanding": 0.15,
    "application": 0.30,
    "transfer": 0.20,
    "explanation": 0.10,
    "retention": 0.15,
}

DIMENSION_TEXT = {
    "recognition": "我能认出来",
    "understanding": "我知道为什么",
    "application": "我会做",
    "transfer": "我会应用",
    "explanation": "我能讲清楚",
    "retention": "我过段时间还记得",
}

# 儿童端四阶段（需求 §三十二：🌱 刚开始 / 🌿 会做基础题 / 🌳 会应用 / ⭐ 灵活运用且长期记住）
CHILD_STAGES = (
    {"key": "sprout", "icon": "🌱", "label": "刚开始", "rank": 0},
    {"key": "basic", "icon": "🌿", "label": "会做基础题", "rank": 1},
    {"key": "apply", "icon": "🌳", "label": "会应用", "rank": 2},
    {"key": "star", "icon": "⭐", "label": "能灵活运用且长期记住", "rank": 3},
)
CHILD_STAGE_BY_KEY = {item["key"]: item for item in CHILD_STAGES}
CHILD_STAGE_OF_LEVEL = {0: "sprout", 1: "sprout", 2: "basic",
                        3: "basic", 4: "apply", 5: "star", 6: "star"}

# 各维度的等级门槛
RECOGNIZE_LINE = 30
UNDERSTAND_LINE = 45
APPLY_LINE = 60
TRANSFER_LINE = 60
EXPLAIN_LINE = 60
RETAIN_LINE = 70

# 升级门槛（数量 + 多样性）
UNDERSTAND_MIN_EVIDENCE = 2
APPLY_MIN_EVIDENCE = 3
APPLY_MIN_STANDARD = 2
TRANSFER_MIN_EVIDENCE = 5
TRANSFER_MIN_DISTINCT = 3
RETAIN_DELAYED_TYPES = ("DELAYED_REVIEW",)
DISTINCT_TYPES = ("STANDARD", "RECALL", "TRANSFER", "EXPLANATION", "DELAYED_REVIEW", "RECOVERY")

# 单条证据对单个维度的最大位移（防止一次作答直接顶满）
EVIDENCE_LEARNING_RATE = 0.45
MAX_STEP = 0.50


class DeepMasteryModel:
    """深度掌握模型（纯函数，不碰数据库，方便直接单测）。"""

    # ---------- 状态 ----------

    def blank(self):
        """空白状态：六个维度 0 分、0 条证据（＝ UNKNOWN）。"""
        state = {name: 0.0 for name in DIMENSIONS}
        state.update({"evidence_count": 0, "hint_sum": 0.0, "hint_dependency": 0.0,
                      "guess_count": 0, "strong_count": 0})
        return state

    @staticmethod
    def _alpha(weight):
        """证据强度 → 本次允许的位移比例（有上限，单题不可能顶满）。"""
        try:
            value = float(weight or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        return max(0.0, min(MAX_STEP, value * EVIDENCE_LEARNING_RATE))

    def apply_evidence(self, state, item):
        """把一条证据作用到状态上，返回**新**状态（不修改入参）。

        ``item`` = {"evidence_type", "result", "hint_level", "confidence", "weight"(可省)}
        """
        current = dict(state or {})
        out = {name: float(current.get(name) or 0.0) for name in DIMENSIONS}

        kind = evidence_module.normalize_type((item or {}).get("evidence_type"))
        result = (item or {}).get("result")
        level = (item or {}).get("hint_level") or 0
        confidence = (item or {}).get("confidence") or ""

        weight = (item or {}).get("weight")
        if weight is None:
            weight = evidence_module.weight_of(kind, result, level, confidence)

        target = 100.0 * evidence_module.result_value(result)

        for name, factor in evidence_module.dimensions_of(kind).items():
            alpha = self._alpha(float(weight) * float(factor))
            if alpha <= 0:
                continue
            out[name] = out[name] + (target - out[name]) * alpha

        count = int(current.get("evidence_count") or 0) + 1
        try:
            hint_value = float(level)
        except (TypeError, ValueError):
            hint_value = 0.0
        hint_sum = float(current.get("hint_sum") or 0.0) + hint_value

        out["evidence_count"] = count
        out["hint_sum"] = round(hint_sum, 3)
        out["hint_dependency"] = round(min(1.0, (hint_sum / count) / 4.0), 4) if count else 0.0
        out["guess_count"] = int(current.get("guess_count") or 0) + (
            1 if str(confidence).strip().lower() == "guess" else 0)
        out["strong_count"] = int(current.get("strong_count") or 0) + (
            1 if evidence_module.is_strong(weight) else 0)
        return out

    def replay(self, items):
        """按时间顺序重放证据列表 → 最终状态（幂等，可随时从证据表重建）。"""
        state = self.blank()
        for item in items or ():
            state = self.apply_evidence(state, item)
        return state

    # ---------- 分数 ----------

    def score_of(self, state):
        """六维加权汇总 → deep_mastery_score（0~100）。

        **儿童端禁止直接展示这个数字**（需求 §二十六 / §二十九）。
        """
        total = 0.0
        for name in DIMENSIONS:
            weight = float(DIMENSION_WEIGHTS.get(name) or 0.0)
            try:
                value = float((state or {}).get(name) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            total += value * weight
        return int(round(max(0.0, min(100.0, total))))

    def dimension_scores(self, state):
        out = {}
        for name in DIMENSIONS:
            try:
                value = float((state or {}).get(name) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            out[name] = int(round(max(0.0, min(100.0, value))))
        return out

    # ---------- 等级 ----------

    @staticmethod
    def _count(counts, key):
        try:
            return int((counts or {}).get(key) or 0)
        except (TypeError, ValueError):
            return 0

    def distinct_types(self, counts):
        """有几类不同来源的证据（升级多样性的判据）。"""
        return sum(1 for key in DISTINCT_TYPES if self._count(counts, key) > 0)

    def level_of(self, state, counts=None, evidence_count=None):
        """状态 + 证据分布 → 0~6 的深度等级（带数量与多样性门槛）。

        设计要点：一次正确永远到不了高等级 —— 门槛里既有分数，也有证据条数。
        """
        counts = counts or {}
        total = int(evidence_count) if evidence_count is not None else sum(
            self._count(counts, key) for key in evidence_module.EVIDENCE_TYPE_KEYS)
        if total <= 0:
            return 0

        state = state or {}
        recognition = self._value(state, "recognition")
        understanding = self._value(state, "understanding")
        application = self._value(state, "application")
        transfer = self._value(state, "transfer")
        explanation = self._value(state, "explanation")
        retention = self._value(state, "retention")

        if recognition < RECOGNIZE_LINE:
            return 0

        level = 1
        if understanding >= UNDERSTAND_LINE and total >= UNDERSTAND_MIN_EVIDENCE:
            level = 2

        applied = self._count(counts, "STANDARD") + self._count(counts, "RECOVERY")
        if (level >= 2 and application >= APPLY_LINE and total >= APPLY_MIN_EVIDENCE
                and applied >= APPLY_MIN_STANDARD):
            level = 3

        if (level >= 3 and transfer >= TRANSFER_LINE
                and self._count(counts, "TRANSFER") >= 1
                and total >= TRANSFER_MIN_EVIDENCE
                and self.distinct_types(counts) >= TRANSFER_MIN_DISTINCT):
            level = 4

        if (level >= 4 and explanation >= EXPLAIN_LINE
                and self._count(counts, "EXPLANATION") >= 1):
            level = 5

        delayed = sum(self._count(counts, key) for key in RETAIN_DELAYED_TYPES)
        if level >= 5 and retention >= RETAIN_LINE and delayed >= 1:
            level = 6

        return level

    def upgrade_gap(self, state, counts=None, evidence_count=None):
        """距离下一等级还差什么（给"下一步怎么做"与调试用，不下发儿童端数字）。"""
        counts = counts or {}
        total = int(evidence_count) if evidence_count is not None else sum(
            self._count(counts, key) for key in evidence_module.EVIDENCE_TYPE_KEYS)
        current = self.level_of(state, counts, total)
        if current >= MAX_LEVEL:
            return {"level": current, "next_level": None, "missing": []}

        missing = []
        if current < 1 and self._value(state, "recognition") < RECOGNIZE_LINE:
            missing.append("还需要一些基础练习，先认得这个知识")
        if current < 2 and self._value(state, "understanding") < UNDERSTAND_LINE:
            missing.append("再理解一下概念（可以用自己的话说一遍）")
        if current < 3 and self._value(state, "application") < APPLY_LINE:
            missing.append("再做几道标准题，把它练熟")
        if current < 3 and total < APPLY_MIN_EVIDENCE:
            missing.append("证据还不够（%d/%d）" % (total, APPLY_MIN_EVIDENCE))
        if current < 4:
            if self._count(counts, "TRANSFER") < 1:
                missing.append("换一种形式的题也试试")
            if self._value(state, "transfer") < TRANSFER_LINE:
                missing.append("多练几次变式，把方法用出来")
        if current < 5 and self._count(counts, "EXPLANATION") < 1:
            missing.append("讲给菲比听一次")
        if current < 6 and sum(self._count(counts, k) for k in RETAIN_DELAYED_TYPES) < 1:
            missing.append("过几天再回来复习一次")

        return {"level": current, "next_level": min(MAX_LEVEL, current + 1), "missing": missing}

    @staticmethod
    def _value(state, name):
        try:
            return float((state or {}).get(name) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # ---------- 儿童语言 ----------

    def child_stage(self, level):
        """等级 → 儿童端四阶段 {key, icon, label, rank}。"""
        key = CHILD_STAGE_OF_LEVEL.get(int(level or 0), "sprout")
        return dict(CHILD_STAGE_BY_KEY[key])

    def abilities(self, state, counts=None):
        """知识地图点开节点时展示的四句话（全部来自真实证据，不编）。"""
        counts = counts or {}
        application = self._value(state, "application")
        transfer = self._value(state, "transfer")
        explanation = self._value(state, "explanation")
        retention = self._value(state, "retention")
        recognition = self._value(state, "recognition")

        return {
            "can_recall": {
                "ok": recognition >= RECOGNIZE_LINE and self._count(counts, "RECALL") >= 1,
                "text": "我能回忆",
                "detail": "不看答案也能想起来" if recognition >= RECOGNIZE_LINE else "还没试过自己想",
            },
            "can_do": {
                "ok": application >= APPLY_LINE,
                "text": "我会做",
                "detail": "标准题能做对" if application >= APPLY_LINE else "标准题还要多练几遍",
            },
            "can_apply": {
                "ok": transfer >= TRANSFER_LINE and self._count(counts, "TRANSFER") >= 1,
                "text": "我会应用",
                "detail": "换一种问法也会做" if transfer >= TRANSFER_LINE else "还没试过变式题",
            },
            "can_explain": {
                "ok": explanation >= EXPLAIN_LINE and self._count(counts, "EXPLANATION") >= 1,
                "text": "我能讲清楚",
                "detail": "能讲给菲比听" if explanation >= EXPLAIN_LINE else "还没讲给菲比听过",
            },
            "can_remember": {
                "ok": retention >= RETAIN_LINE and sum(
                    self._count(counts, k) for k in RETAIN_DELAYED_TYPES) >= 1,
                "text": "我过段时间还记得",
                "detail": "延迟复习也做对了" if retention >= RETAIN_LINE else "还没有延迟复习记录",
            },
        }


DEFAULT_MODEL = DeepMasteryModel()


# --------------------------------------------------------------
# 模块级快捷入口
# --------------------------------------------------------------

def level_of(state, counts=None, evidence_count=None):
    return DEFAULT_MODEL.level_of(state, counts, evidence_count)


def score_of(state):
    return DEFAULT_MODEL.score_of(state)


def child_stage(level):
    return DEFAULT_MODEL.child_stage(level)


def abilities(state, counts=None):
    return DEFAULT_MODEL.abilities(state, counts)


def upgrade_gap(state, counts=None, evidence_count=None):
    return DEFAULT_MODEL.upgrade_gap(state, counts, evidence_count)


def level_dict(level):
    """等级 → 结构化描述（含儿童语言）；越界收敛到合法等级。"""
    try:
        value = int(level or 0)
    except (TypeError, ValueError):
        value = 0
    value = 0 if value < 0 else (MAX_LEVEL if value > MAX_LEVEL else value)
    item = dict(LEVELS[value])
    item["child_stage"] = DEFAULT_MODEL.child_stage(value)
    return item
