# ==============================================================
# 能力契约｜复习队列构建：P0~P3 优先级、每科上限、每天上限、每知识点 1~3 题
# 入口：ReviewScheduler.build / build_queue / priority_of / summarize / next_batch_date / target_count_of
# 依赖：datetime
# 不负责：每日新学/补强/复习配比 → mix.py
# 验证：python backend/verify_memory.py
# 被调用：review/engine.py、review_routes.py、adaptive/planner.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 · 今日复习队列 ReviewScheduler。

每天给每个学生排一批复习任务，规则（优先级从高到低）：

| 优先级 | 条件 | 说明 |
| --- | --- | --- |
| `P0` | 已经超过 `next_review_at` | 到期了，必须复习 |
| `P1` | `forgetting_risk >= 0.75` | 还没到期，但快忘了 |
| `P2` | 最近 3 天刚学会、成熟度还低 | 早期巩固，趁热打铁 |
| `P3` | 重要前置知识（被依赖度高）且 `risk >= 0.5` | 基础不能塌 |

三条限流（避免一天塞爆孩子）：

1. 每科最多 **8 个**知识点；
2. 每天最多 **15 个**知识点 → 超出的顺延到后面几天（长期没登录也不会一次安排 100 个任务）；
3. 每个知识点 **1~3 题**：风险 ≥0.75 出 3 题、≥0.5 出 2 题、其余 1 题。

`needs_relearn` 的知识点**不进复习队列**，单独返回给自适应引擎重新学。
"""

from datetime import datetime, timedelta

PRIORITY_ORDER = ("P0", "P1", "P2", "P3")
PRIORITY_TEXT = {
    "P0": "已经到期",
    "P1": "快忘记了",
    "P2": "刚学会，趁热巩固",
    "P3": "重要基础快忘了",
}

MAX_PER_SUBJECT = 8
MAX_PER_DAY = 15

MIN_TARGET = 1
MAX_TARGET = 3
HIGH_RISK = 0.75
MEDIUM_RISK = 0.5
EARLY_DAYS = 3.0            # "刚学会"的时间窗（天）
FOUNDATION_LINE = 0.34      # 被依赖度达到它才算"重要基础"


def target_count_of(risk, maturity_level=""):
    """风险越高，这次多验证几题（1~3）。"""
    if risk >= HIGH_RISK:
        return 3
    if risk >= MEDIUM_RISK:
        return 2
    return MIN_TARGET


def priority_of(state, risk, now=None, foundation=0.0):
    """给一个记忆状态定优先级；返回 "" 表示今天不用复习它。"""
    now = now or datetime.now()
    get = (state.get if isinstance(state, dict) else lambda name, default=None:
           getattr(state, name, default))

    next_review = get("next_review_at", None)
    mastery = float(get("mastery_score", 0) or 0)
    maturity = str(get("maturity_level", "") or "").upper()
    last_learned = get("last_learned_at", None)

    if bool(get("needs_relearn", False)):
        return ""

    if isinstance(next_review, datetime) and next_review <= now:
        return "P0"
    if risk >= HIGH_RISK:
        return "P1"
    if isinstance(last_learned, datetime):
        learned_days = (now - last_learned).total_seconds() / 86400.0
        if 0 <= learned_days <= EARLY_DAYS and maturity in ("NEW", "LEARNING", "SHORT_TERM"):
            return "P2"
    if risk >= MEDIUM_RISK and foundation >= FOUNDATION_LINE:
        return "P3"
    return ""


def _sort_key(item):
    return (
        PRIORITY_ORDER.index(item["priority"]) if item["priority"] in PRIORITY_ORDER else 9,
        -float(item.get("risk") or 0),
        item.get("next_review_at") or datetime.max,
        str(item.get("subject") or ""),
        str(item.get("knowledge_id") or ""),
    )


def build_queue(states, now=None, risks=None, max_per_subject=MAX_PER_SUBJECT,
                max_per_day=MAX_PER_DAY, foundation_of=None):
    """把记忆状态列表排成今日复习队列（纯函数）。

    states:        [dict | KnowledgeMemoryState, ...]
    risks:         {knowledge_id: risk}，不传则用状态里的 forgetting_risk 字段
    foundation_of: 可选函数 (subject, knowledge) -> 0~1，用于 P3 判定
    """
    from review import forgetting as forgetting_module

    now = now or datetime.now()
    foundation_of = foundation_of or (lambda subject, knowledge: 0.0)
    risks = risks or {}

    items = []
    relearn = []

    for state in states or ():
        get = (state.get if isinstance(state, dict) else lambda name, default=None:
               getattr(state, name, default))

        subject = str(get("subject", "") or "")
        knowledge = str(get("knowledge_id", "") or "")
        if not knowledge:
            continue

        mastery = float(get("mastery_score", 0) or 0)
        needs_relearn = bool(get("needs_relearn", False)) or mastery < 60
        if needs_relearn:
            relearn.append({
                "subject": subject,
                "knowledge_id": knowledge,
                "mastery_score": int(round(mastery)),
                "reason": f"掌握度 {int(round(mastery))}，先重新学会再来复习",
            })
            continue

        risk = float(risks.get(knowledge, get("forgetting_risk", 0.0) or 0.0))
        foundation = float(foundation_of(subject, knowledge) or 0.0)
        priority = priority_of(state, risk, now, foundation)
        if not priority:
            continue

        items.append({
            "subject": subject,
            "knowledge_id": knowledge,
            "priority": priority,
            "priority_text": PRIORITY_TEXT.get(priority, ""),
            "risk": round(risk, 3),
            "risk_level": forgetting_module.risk_level(risk),
            "target_count": target_count_of(risk, get("maturity_level", "")),
            "maturity_level": str(get("maturity_level", "") or ""),
            "next_review_at": get("next_review_at", None),
            "interval_days": float(get("current_interval_days", 1.0) or 1.0),
            "mastery_score": int(round(mastery)),
            "reason": _reason_of(priority, risk, get),
        })

    items.sort(key=_sort_key)

    # 1) 每科限量
    kept = []
    per_subject = {}
    deferred = []
    for item in items:
        count = per_subject.get(item["subject"], 0)
        if count >= max(1, int(max_per_subject)):
            deferred.append(item)
            continue
        per_subject[item["subject"]] = count + 1
        kept.append(item)

    # 2) 每日总量限量（长期没登录时顺延）
    if len(kept) > max(1, int(max_per_day)):
        deferred.extend(kept[max(1, int(max_per_day)):])
        kept = kept[:max(1, int(max_per_day))]

    for index, item in enumerate(kept):
        item["order"] = index + 1

    by_subject = {}
    for item in kept:
        by_subject[item["subject"]] = by_subject.get(item["subject"], 0) + 1

    return {
        "date": now.strftime("%Y-%m-%d"),
        "items": kept,
        "relearn": relearn,
        "deferred": deferred,
        "deferred_count": len(deferred),
        "total": len(kept),
        "by_subject": by_subject,
        "summary": summarize(kept, relearn, deferred),
    }


def _reason_of(priority, risk, get):
    mastery = int(round(float(get("mastery_score", 0) or 0)))
    if priority == "P0":
        next_review = get("next_review_at", None)
        if isinstance(next_review, datetime):
            overdue = max(0.0, (datetime.now() - next_review).total_seconds() / 86400.0)
            if overdue >= 1:
                return f"该复习了（已超期 {overdue:.0f} 天），掌握度 {mastery}"
        return f"该复习了，掌握度 {mastery}"
    if priority == "P1":
        return f"快忘记了（风险 {risk:.0%}），掌握度 {mastery}"
    if priority == "P2":
        return "刚学会不久，趁热再巩固一次"
    if priority == "P3":
        return "它是后面知识的基础，先确认还记得"
    return f"掌握度 {mastery}"


def summarize(items, relearn=None, deferred=None):
    """队列统计：急需复习 / 需要重学 / 顺延。"""
    items = items or []
    return {
        "total": len(items),
        "high_risk": sum(1 for item in items if item["risk"] >= HIGH_RISK),
        "due": sum(1 for item in items if item["priority"] == "P0"),
        "relearn": len(relearn or []),
        "deferred": len(deferred or []),
        "questions": sum(int(item.get("target_count") or 1) for item in items),
        "by_priority": {key: sum(1 for item in items if item["priority"] == key)
                        for key in PRIORITY_ORDER},
    }


def next_batch_date(now=None, offset_days=1):
    """被顺延的任务排到后面哪一天。"""
    now = now or datetime.now()
    return (now + timedelta(days=max(1, int(offset_days)))).replace(
        hour=0, minute=0, second=0, microsecond=0)


class ReviewScheduler:
    """复习调度器（纯函数；落库由 `review.engine` 负责）。"""

    def build(self, states, now=None, risks=None, foundation_of=None,
              max_per_subject=MAX_PER_SUBJECT, max_per_day=MAX_PER_DAY):
        return build_queue(states, now=now, risks=risks, foundation_of=foundation_of,
                           max_per_subject=max_per_subject, max_per_day=max_per_day)


DEFAULT_SCHEDULER = ReviewScheduler()
