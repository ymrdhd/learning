# ==============================================================
# 能力契约｜V2.7 统一学习证据：证据类型 / 证据强度 / 命中维度（纯函数，不碰数据库）
# 入口：EVIDENCE_TYPES / EVIDENCE_TYPE_KEYS / HINT_FACTOR / GUESS_FACTOR / STRONG_LINE /
#       weight_of / dimensions_of / normalize_type / result_value / is_strong / summarize / type_label
# 依赖：无（纯标准库，可独立单测；不 import 任何项目模块）
# 不负责：证据落库与深度状态更新 → deep_learning/engine.py；掌握度 → mastery.py；记忆 → review/
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/deep_mastery.py、deep_learning/recall_ladder.py、deep_learning/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 统一学习证据（Learning Evidence，需求 §六 / §二十 / §二十一）。

V2.3 之前系统只记 ``correct / wrong``；同一个"对"可能是**无提示独立回忆**（强证据），
也可能是**依赖第 4 级提示后照抄**或**四选一猜中**（弱证据）。本模块把"这次作答值多少分"
变成一条可计算的证据强度：

    证据强度 = 类型基础强度 × 提示折损 × 自信度系数 × 结果系数      （截断到 0.05~1.0）

* 普通基础题正确 → 弱到中等（BASE 0.45）
* 无提示主动回忆成功 → 最强（BASE 1.00 × 1.00）
* 迁移题正确 → 强（BASE 0.90）
* 延迟后正确 → 强记忆证据（BASE 1.00）
* 依赖高级 Hint 答对 → 弱（× 0.20~0.30）
* 猜对 → 弱（× 0.35）

本模块只做纯计算，**不碰数据库、不改任何状态**；落库与状态更新统一走
``deep_learning/engine.py``（DeepLearningEngine，Deep Mastery 唯一写入口）。
"""

# --------------------------------------------------------------
# 证据类型（需求 §六 规定的 7 类，不多不少）
# --------------------------------------------------------------

EVIDENCE_TYPES = {
    "STANDARD": {
        "label": "普通练习",
        "icon": "📝",
        "base": 0.45,
        "dimensions": {"application": 1.0, "recognition": 0.9, "understanding": 0.6},
    },
    "RECALL": {
        "label": "主动回忆",
        "icon": "🧠",
        "base": 1.00,
        "dimensions": {"recognition": 1.0, "retention": 0.8, "understanding": 0.4},
    },
    "TRANSFER": {
        "label": "变式迁移",
        "icon": "🔀",
        "base": 0.90,
        "dimensions": {"transfer": 1.0, "application": 0.3},
    },
    "EXPLANATION": {
        "label": "讲一讲",
        "icon": "🗣️",
        "base": 0.80,
        "dimensions": {"explanation": 1.0, "understanding": 0.6},
    },
    "DELAYED_REVIEW": {
        "label": "延迟复习",
        "icon": "⏳",
        "base": 1.00,
        "dimensions": {"retention": 1.0, "recognition": 0.4},
    },
    "RECOVERY": {
        "label": "错题康复",
        "icon": "⚔️",
        "base": 0.65,
        "dimensions": {"application": 1.0, "understanding": 0.3},
    },
    "PREREQUISITE_CHECK": {
        "label": "前置验证",
        "icon": "🧱",
        "base": 0.50,
        "dimensions": {"understanding": 1.0, "recognition": 0.6},
    },
}

EVIDENCE_TYPE_KEYS = tuple(EVIDENCE_TYPES)

DEFAULT_TYPE = "STANDARD"

# 强度达到它才算"强证据"（用于升级门槛与前端"这次学得很扎实"的判断）
STRONG_LINE = 0.60

# 提示层级折损（Recall Hint Ladder，需求 §十八）：无提示最高
HINT_FACTOR = {0: 1.00, 1: 0.60, 2: 0.45, 3: 0.30, 4: 0.20}

# 自信度系数（需求 §二十 / §二十一）
GUESS_FACTOR = 0.35        # 🎲 我猜的
SURE_FACTOR = 1.15         # 🙂 很确定
UNSURE_FACTOR = 0.70       # 😵 不会
CONFIDENCE_FACTOR = {
    "sure": SURE_FACTOR,
    "maybe": 1.0,
    "guess": GUESS_FACTOR,
    "unknown": UNSURE_FACTOR,
    "": 1.0,
}

# 结果系数：部分正确打折；答错再打折一点（需求 §十：单题错误不要当成"完全不会"）
PARTIAL_FACTOR = 0.55
WRONG_FACTOR = 0.70

MIN_WEIGHT = 0.05
MAX_WEIGHT = 1.00

# 同一知识点的两条证据间隔超过它，第二条就算"延迟证据"（RETAIN 的必要条件）
DELAYED_HOURS = 20

SUCCESS_RESULTS = ("correct",)
RESULT_VALUE = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}


# --------------------------------------------------------------
# 工具
# --------------------------------------------------------------

def normalize_type(evidence_type):
    """把任意输入收敛到合法证据类型（未知一律当普通练习）。"""
    key = str(evidence_type or "").strip().upper()
    return key if key in EVIDENCE_TYPES else DEFAULT_TYPE


def type_label(evidence_type):
    """证据类型的中文标签。"""
    return EVIDENCE_TYPES[normalize_type(evidence_type)]["label"]


def base_of(evidence_type):
    """证据类型的基础强度。"""
    return float(EVIDENCE_TYPES[normalize_type(evidence_type)]["base"])


def dimensions_of(evidence_type):
    """这条证据命中哪些维度、各占多少系数（返回维度 → 0~1 系数）。"""
    return dict(EVIDENCE_TYPES[normalize_type(evidence_type)]["dimensions"])


def hint_factor(hint_level):
    """提示层级 → 折损系数（0 无提示最高，4 完整答案最低）。"""
    try:
        level = int(hint_level or 0)
    except (TypeError, ValueError):
        level = 0
    level = 0 if level < 0 else (4 if level > 4 else level)
    return float(HINT_FACTOR.get(level, HINT_FACTOR[4]))


def result_value(result):
    """作答结果 → 0~1 的达成度（驱动维度向 100 或 0 靠拢）。"""
    return float(RESULT_VALUE.get(str(result or "").strip().lower(), 0.0))


def is_correct(result):
    return str(result or "").strip().lower() == "correct"


def weight_of(evidence_type, result="correct", hint_level=0, confidence=""):
    """证据强度 0.05~1.0：类型 × 提示折损 × 自信度 × 结果。

    这是 V2.7 的核心口径之一 —— "答对了"不再是二元事实，而是有强弱的证据。
    """
    weight = base_of(evidence_type)
    weight *= hint_factor(hint_level)
    weight *= float(CONFIDENCE_FACTOR.get(str(confidence or "").strip().lower(), 1.0))

    text = str(result or "").strip().lower()
    if text == "partial":
        weight *= PARTIAL_FACTOR
    elif text != "correct":
        weight *= WRONG_FACTOR

    return round(max(MIN_WEIGHT, min(MAX_WEIGHT, weight)), 4)


def is_strong(weight):
    """是不是强证据（无提示回忆成功 / 迁移成功 / 延迟后正确 都会落在这一档）。"""
    try:
        return float(weight or 0.0) >= STRONG_LINE
    except (TypeError, ValueError):
        return False


def summarize(rows):
    """证据列表 → 各类型条数与加权强度均值（供接口与效率引擎使用）。"""
    counts = {key: 0 for key in EVIDENCE_TYPE_KEYS}
    strong = 0
    weight_sum = 0.0
    total = 0

    for row in rows or ():
        if isinstance(row, dict):
            kind = row.get("evidence_type")
            weight = row.get("weight")
        else:
            kind = getattr(row, "evidence_type", None)
            weight = getattr(row, "weight", None)

        key = normalize_type(kind)
        counts[key] = counts.get(key, 0) + 1
        total += 1

        try:
            value = float(weight or 0.0)
        except (TypeError, ValueError):
            value = 0.0

        weight_sum += value
        if is_strong(value):
            strong += 1

    return {
        "total": total,
        "counts": counts,
        "strong": strong,
        "average_weight": round(weight_sum / total, 4) if total else 0.0,
    }
