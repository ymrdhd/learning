# ==============================================================
# 能力契约｜MemoryState 与成熟度模型（纯函数）：掌握度/稳定性/个人难度/成熟度
# 入口：initial_learn_state / migrate_state / relearn_state / maturity_of / action_of / state_summary / needs_relearn / personal_difficulty / memory_strength_of
# 依赖：math datetime
# 不负责：间隔计算 → interval.py；遗忘风险 → forgetting.py；落库 → review/engine.py
# 验证：python backend/verify_memory.py
# 被调用：review/engine.py、review_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 · 记忆状态 MemoryState。

掌握度回答"会不会"，记忆状态回答"**还记不记得、能撑多久**"。

- `memory_strength`（0~100）：当前记忆强度 = (0.55×掌握度 + 0.45×稳定性分) × 当前保持度
- `stability`（天）：记忆稳定性，越大越耐忘，允许更长间隔
- `difficulty`（0~1）：**这个学生在这个知识点上的个人难度**（不是知识点固定难度）
- `maturity_level`：成熟度六级，儿童端显示成树的成长状态

成熟度对照：

| 后端 | 家长端 | 儿童端 | 知识森林（V2.6 预留） |
| --- | --- | --- | --- |
| `NEW` | 刚接触 | 🌱 刚学会 | 种子 |
| `LEARNING` | 正在学习 | 🌱 刚学会 | 幼苗 |
| `SHORT_TERM` | 短期掌握 | 🌿 正在巩固 | 小树 |
| `CONSOLIDATING` | 巩固中 | 🌿 正在巩固 | 成长树 |
| `STABLE` | 稳定掌握 | 🌳 记得很牢 | 大树 |
| `LONG_TERM` | 长期掌握 | ⭐ 长期掌握 | 星光树 |

`mastery < 60` 时标记 `needs_relearn`：这种情况不该做纯复习，
要交回 `AdaptiveLearningEngine` 重新学（API 里 action 返回 `RELEARN`）。
"""

import math
from datetime import datetime, timedelta

MATURITY_LEVELS = ("NEW", "LEARNING", "SHORT_TERM", "CONSOLIDATING", "STABLE", "LONG_TERM")

MATURITY_TEXT = {
    "NEW": "刚接触",
    "LEARNING": "正在学习",
    "SHORT_TERM": "短期掌握",
    "CONSOLIDATING": "巩固中",
    "STABLE": "稳定掌握",
    "LONG_TERM": "长期掌握",
}

# 儿童端：只给四种说法，不出现英文与复杂指标
MATURITY_CHILD = {
    "NEW": "🌱 刚学会",
    "LEARNING": "🌱 刚学会",
    "SHORT_TERM": "🌿 正在巩固",
    "CONSOLIDATING": "🌿 正在巩固",
    "STABLE": "🌳 记得很牢",
    "LONG_TERM": "⭐ 长期掌握",
}

# 知识森林（V2.6 预留，本版本只输出字段）
MATURITY_FOREST = {
    "NEW": "种子", "LEARNING": "幼苗", "SHORT_TERM": "小树",
    "CONSOLIDATING": "成长树", "STABLE": "大树", "LONG_TERM": "星光树",
}
MATURITY_FOREST_ICON = {
    "NEW": "🌰", "LEARNING": "🌱", "SHORT_TERM": "🌿",
    "CONSOLIDATING": "🌳", "STABLE": "🌲", "LONG_TERM": "⭐",
}

RELEARN_LINE = 60           # 掌握度低于它 → 重新学，不做纯复习
CONSOLIDATE_LINE = 70       # 低于它算"正在学习"
STABLE_LINE = 80            # 稳定掌握的掌握度线
STABLE_STABILITY = 21.0     # 稳定掌握的稳定性线（天）
LONG_TERM_STABILITY = 60.0  # 长期掌握的稳定性线（天）
LONG_TERM_REVIEWS = 5       # 长期掌握需要的成功复习次数
STABILITY_MAX = 180.0
ACTION_TEXT = {"RELEARN": "重新学习", "REVIEW": "间隔复习", "OK": "状态良好"}


def clamp(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(low)
    if number != number:
        number = float(low)
    return max(float(low), min(float(high), number))


def stability_score(stability):
    """稳定性（天）→ 0~100 的可读分数：0.5 天≈0 分，90 天≈100 分。"""
    value = clamp(stability, 0.0, STABILITY_MAX)
    return min(100.0, 100.0 * math.log(1.0 + value) / math.log(1.0 + 90.0))


def personal_difficulty(mastery_score, failed_reviews=0, successful_reviews=0,
                        recent_correct=None):
    """个人难度 0~1：掌握度越低、失败越多 → 越难。"""
    value = (0.5 + (70.0 - clamp(mastery_score, 0, 100)) / 100.0
             + 0.08 * max(0, int(failed_reviews or 0))
             - 0.03 * max(0, int(successful_reviews or 0)))
    if recent_correct is False:
        value += 0.08
    return round(clamp(value, 0.1, 0.9), 3)


def memory_strength_of(mastery_score, stability, forgetting_risk=0.0):
    """当前记忆强度 0~100。"""
    base = 0.55 * clamp(mastery_score, 0, 100) + 0.45 * stability_score(stability)
    keep = 0.6 + 0.4 * (1.0 - clamp(forgetting_risk, 0, 1))
    return int(round(clamp(base * keep, 0, 100)))


def maturity_of(mastery_score, stability=1.0, successful_reviews=0, review_count=0,
                needs_relearn=False):
    """成熟度判定（可解释、单调）。"""
    mastery = clamp(mastery_score, 0, 100)
    stability_value = clamp(stability, 0.0, STABILITY_MAX)
    successful = max(0, int(successful_reviews or 0))
    practiced = max(0, int(review_count or 0)) + successful

    if mastery < RELEARN_LINE or needs_relearn:
        return "LEARNING" if practiced > 0 else "NEW"
    if mastery < CONSOLIDATE_LINE:
        return "LEARNING"
    if stability_value >= LONG_TERM_STABILITY and mastery >= 85 and successful >= LONG_TERM_REVIEWS:
        return "LONG_TERM"
    if stability_value >= STABLE_STABILITY and mastery >= STABLE_LINE:
        return "STABLE"
    if mastery >= 85:
        return "STABLE"                     # 迁移来的老数据：掌握很好，只是还没经过复习确认
    if stability_value >= 7.0 or successful >= 2:
        return "CONSOLIDATING"
    return "SHORT_TERM"


def needs_relearn(mastery_score, consecutive_failures=0):
    """掌握度太低或连续复习失败 → 交回自适应引擎重新学。"""
    return clamp(mastery_score, 0, 100) < RELEARN_LINE or int(consecutive_failures or 0) >= 2


# ---------------- 初始状态 ----------------

def initial_learn_state(mastery_score, confidence=0.5, now=None):
    """**刚刚学会**一个新知识点：1 天后第一次复习。"""
    now = now or datetime.now()
    mastery = int(round(clamp(mastery_score, 0, 100)))
    state = {
        "mastery_score": mastery,
        "stability": 1.0,
        "current_interval_days": 1.0,
        "successful_reviews": 0,
        "failed_reviews": 0,
        "consecutive_failures": 0,
        "review_streak": 0,
        "confidence": round(clamp(confidence, 0, 1), 3),
        "last_learned_at": now,
        "last_reviewed_at": None,
        "next_review_at": now + timedelta(days=1.0),
        "forgetting_risk": 0.0,
        "needs_relearn": False,
    }
    state["difficulty"] = personal_difficulty(mastery, 0, 0)
    state["maturity_level"] = maturity_of(mastery, state["stability"], 0, 0, False)
    state["memory_strength"] = memory_strength_of(mastery, state["stability"], 0.0)
    return state


def migrate_state(mastery_score, confidence=0.5, now=None, last_learned_at=None):
    """V2.3 → V2.4 迁移：按掌握度给一份合理的初始记忆状态。

    | 掌握度 | 初始成熟度 | 初始间隔 | 初始稳定性 |
    | --- | --- | --- | --- |
    | ≥85 | `STABLE` | 14 天 | 21 |
    | 70~84 | `CONSOLIDATING` | 7 天 | 7 |
    | 60~69 | `LEARNING` | 3 天 | 3 |
    | <60 | `LEARNING` + `needs_relearn` | 1 天 | 1 |
    """
    now = now or datetime.now()
    mastery = int(round(clamp(mastery_score, 0, 100)))

    if mastery >= 85:
        interval, stability = 14.0, 21.0
    elif mastery >= 70:
        interval, stability = 7.0, 7.0
    elif mastery >= RELEARN_LINE:
        interval, stability = 3.0, 3.0
    else:
        interval, stability = 1.0, 1.0

    relearn = mastery < RELEARN_LINE
    state = {
        "mastery_score": mastery,
        "stability": stability,
        "current_interval_days": interval,
        "successful_reviews": 0,
        "failed_reviews": 0,
        "consecutive_failures": 0,
        "review_streak": 0,
        "confidence": round(clamp(confidence, 0, 1), 3),
        "last_learned_at": last_learned_at or now,
        "last_reviewed_at": None,
        # 迁移过来的知识默认"现在就该看一眼"，让第一天的队列有内容可排
        "next_review_at": now,
        "forgetting_risk": 0.0,
        "needs_relearn": relearn,
    }
    state["difficulty"] = personal_difficulty(mastery, 0, 0)
    # 需要重学的知识点：已经学过但没掌握，成熟度记 LEARNING（不是刚接触的 NEW）
    state["maturity_level"] = "LEARNING" if relearn else maturity_of(mastery, stability, 0, 0, False)
    state["memory_strength"] = memory_strength_of(mastery, stability, 0.0)
    return state


def relearn_state(state, now=None):
    """确认遗忘：成熟度降到 LEARNING，间隔压缩，交给重新学习。"""
    now = now or datetime.now()
    mastery = clamp(state.get("mastery_score") if isinstance(state, dict)
                    else getattr(state, "mastery_score", 0), 0, 100)
    updated = dict(state) if isinstance(state, dict) else {}
    updated.update({
        "mastery_score": int(round(mastery)),
        "needs_relearn": True,
        "current_interval_days": 1.0,
        "next_review_at": now,
    })
    updated["maturity_level"] = "LEARNING"
    updated["memory_strength"] = memory_strength_of(mastery, 1.0, 1.0)
    return updated


def action_of(state):
    """这个知识点现在该做什么：RELEARN / REVIEW / OK。"""
    get = (state.get if isinstance(state, dict) else lambda name, default=None:
           getattr(state, name, default))
    if bool(get("needs_relearn", False)) or clamp(get("mastery_score", 0) or 0, 0, 100) < RELEARN_LINE:
        return "RELEARN"
    next_review = get("next_review_at", None)
    if next_review is not None and isinstance(next_review, datetime) and next_review <= datetime.now():
        return "REVIEW"
    return "OK"


def state_summary(state, now=None):
    """记忆状态 → API / 前端用的 dict（含儿童文案与森林字段）。"""
    now = now or datetime.now()
    get = (state.get if isinstance(state, dict) else lambda name, default=None:
           getattr(state, name, default))

    maturity = str(get("maturity_level", "NEW") or "NEW").upper()
    risk = clamp(get("forgetting_risk", 0.0) or 0.0, 0, 1)
    next_review = get("next_review_at", None)

    from review import forgetting as forgetting_module

    level = forgetting_module.risk_level(risk)
    action = action_of(state)

    return {
        "subject": get("subject", ""),
        "knowledge_id": get("knowledge_id", "") or get("knowledge", ""),
        "mastery_score": int(round(clamp(get("mastery_score", 0) or 0, 0, 100))),
        "memory_strength": int(round(clamp(get("memory_strength", 0) or 0, 0, 100))),
        "stability": round(clamp(get("stability", 1.0) or 1.0, 0, STABILITY_MAX), 2),
        "difficulty": round(clamp(get("difficulty", 0.5) or 0.5, 0, 1), 3),
        "forgetting_risk": round(risk, 3),
        "risk_percent": int(round(risk * 100)),
        "risk_level": level,
        "risk_text": forgetting_module.RISK_TEXT.get(level, ""),
        "current_interval_days": round(clamp(get("current_interval_days", 1.0) or 1.0, 1, STABILITY_MAX), 1),
        "review_count": int(get("review_count", 0) or 0),
        "successful_reviews": int(get("successful_reviews", 0) or 0),
        "failed_reviews": int(get("failed_reviews", 0) or 0),
        "consecutive_failures": int(get("consecutive_failures", 0) or 0),
        "last_learned_at": _fmt(get("last_learned_at", None)),
        "last_reviewed_at": _fmt(get("last_reviewed_at", None)),
        "next_review_at": _fmt(next_review),
        "next_review_date": next_review.strftime("%Y-%m-%d") if isinstance(next_review, datetime) else "",
        "overdue": bool(isinstance(next_review, datetime) and next_review <= now),
        "maturity_level": maturity,
        "maturity_text": MATURITY_TEXT.get(maturity, ""),
        "maturity_child": MATURITY_CHILD.get(maturity, ""),
        "forest": MATURITY_FOREST.get(maturity, ""),
        "forest_icon": MATURITY_FOREST_ICON.get(maturity, ""),
        "needs_relearn": bool(get("needs_relearn", False)),
        "action": action,
        "action_text": ACTION_TEXT.get(action, ""),
    }


def _fmt(moment):
    return moment.strftime("%Y-%m-%d %H:%M") if isinstance(moment, datetime) else ""
