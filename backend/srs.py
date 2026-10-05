# ==============================================================
# 能力契约｜V2.1 艾宾浩斯复习阶梯（11 级）与 reviews 表调度（纯函数）
# 入口：review / apply_state / state_from_row / due_items / select_knowledge / mastery / is_due / format_interval / now_ts / to_dt / INTERVALS / MASTERED_STAGE
# 依赖：datetime（纯函数）
# 不负责：V2.4 记忆状态体系 → review/（新，另一套表）；掌握度 → mastery.py
# 验证：python backend/verify_review.py
# 被调用：main.py（/question、/submit、/reviews）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""艾宾浩斯记忆曲线的复习调度（纯函数，方便直接单测）。

设计要点：
1. 时间单位统一用“秒”，数据库里存整数时间戳，避免时区与字符串格式问题。
2. 复习间隔按固定阶梯递增；答错立即退回第一级，当天再复习一次。
3. 同一个知识点连续答对 3 次才算进入下一级，避免“蒙对一次就拉长间隔”。
"""

from datetime import datetime

# 艾宾浩斯遗忘曲线的小学生实用版间隔（秒）
INTERVALS = [
    5 * 60,        # 5 分钟后：刚学完的第一次强化
    30 * 60,       # 30 分钟后
    12 * 60 * 60,  # 12 小时后（当天睡前再来一次）
    24 * 60 * 60,  # 1 天
    2 * 24 * 60 * 60,
    4 * 24 * 60 * 60,
    7 * 24 * 60 * 60,
    15 * 24 * 60 * 60,
    30 * 24 * 60 * 60,
    60 * 24 * 60 * 60,
    120 * 24 * 60 * 60,  # 120 天后视为长期掌握
]

# 每个阶段需要连续答对几次才前进一级
STREAK_TO_ADVANCE = 3
MASTERED_STAGE = len(INTERVALS)
_UNITS = ((24 * 3600, "天"), (3600, "小时"), (60, "分钟"), (1, "秒"))


def now_ts():
    return int(datetime.now().timestamp())


def to_dt(value):
    """整数时间戳 → datetime，供 SQLAlchemy 的 DateTime 列使用。"""
    return datetime.fromtimestamp(int(value))


def format_interval(seconds):
    """把间隔秒数写成小朋友能看懂的话，例如 1800 → '30分钟后'。"""
    seconds = int(seconds)
    if seconds <= 0:
        return "现在"
    for size, unit in _UNITS:
        if seconds >= size:
            return f"{seconds // size}{unit}后"
    return f"{seconds}秒后"


def normalize(interval, stage=0, due_at=None, last_result=None, streak=0):
    """补齐复习计划字段，兼容从未复习过的知识点和空值。

    due_at 为 0/None 表示"还没复习过"，此时默认标记为立即到期（安排 5 分钟后
    也说得通，但首次学习的孩子当下就该练，所以直接算到期）。
    """
    interval = int(interval or 0)
    if interval <= 0:
        interval = INTERVALS[0]

    due_at = int(due_at or 0)
    if due_at <= 0:
        due_at = now_ts()

    stage = max(0, min(MASTERED_STAGE, int(stage or 0)))

    return {
        "interval": interval,
        "stage": stage,
        "due_at": due_at,
        "last_result": last_result,
        "streak": max(0, int(streak or 0)),
        "mastered": stage >= MASTERED_STAGE,
    }


def is_due(state, now=None):
    """是否到了该复习的时间；stage 0 的新知识点或从未复习过的一律算到期。"""
    if state.get("mastered"):
        return False
    return int(state.get("due_at") or 0) <= (now or now_ts())


def review(state, correct, now=None):
    """交一次作业后推进复习计划。

    答对：连续答对满 STREAK_TO_ADVANCE 次，间隔升一级。
    答错：间隔打回第一级，当天再巩固一次。
    """
    now = int(now or now_ts())
    before = normalize(state.get("interval"), state.get("stage"), state.get("due_at"),
                       state.get("last_result"), state.get("streak"))

    if correct:
        streak = before["streak"] + 1
        if streak >= STREAK_TO_ADVANCE:
            stage = min(MASTERED_STAGE, before["stage"] + 1)
            streak = 0
        else:
            stage = before["stage"]
    else:
        stage = 0
        streak = 0

    interval = INTERVALS[min(stage, len(INTERVALS) - 1)]
    due_at = now + interval
    after = normalize(interval, stage, due_at, bool(correct), streak)

    if after["mastered"]:
        message = "连续答对，这个知识点已经掌握啦，之后偶尔复习一次就行～"
    elif correct:
        need = STREAK_TO_ADVANCE - after["streak"]
        if after["stage"] > before["stage"]:
            message = f"升级啦！下次复习：{format_interval(interval)}"
        else:
            message = f"记忆稳固中，再连续答对 {need} 次就能拉长复习间隔。下次复习：{format_interval(interval)}"
    else:
        message = f"答错要马上巩固，{format_interval(interval)}我们再练一遍这个知识点。"

    after["message"] = message
    after["advanced"] = after["stage"] > before["stage"]
    return after


def mastery(state):
    """掌握度百分比：按复习阶段估算，给小朋友一个直观的进度。"""
    state = normalize(state.get("interval"), state.get("stage"), state.get("due_at"),
                      state.get("last_result"), state.get("streak"))
    if state["mastered"]:
        return 100
    if state["stage"] == 0 and state["last_result"] is False:
        return 0
    return round(100 * state["stage"] / MASTERED_STAGE)


# 前端复习面板最多同时展示几个到期知识点，避免小朋友一次看到一长串任务
TOP_N = 3


def select_knowledge(rows, due_rows=(), preferred=""):
    """挑出这一次该练的知识点。

    复习优先于新学：只要填了知识点，就先按它来，保证孩子不会在还没巩固
    前面内容时一路往前刷新知识；只有完全没填知识点时才交给复习队列。

    返回 {"knowledge": ..., "is_review": ...}。is_review 表示"这是回头再练
    已经做过的知识点"；从没做过的新知识点算第一次学习，不算复习。
    """
    preferred = (preferred or "").strip()
    by_name = {row["knowledge"]: row for row in rows}

    if preferred:
        row = by_name.get(preferred)
        return {
            "knowledge": preferred,
            # 做过才叫复习：从没做过的知识点属于第一次学习
            "is_review": bool(row and (row.get("review_count") or 0) > 0),
        }

    if due_rows:
        due_rows = sorted(due_rows, key=lambda row: (row["due_at"], row["knowledge"]))
        row = due_rows[0]
        return {
            "knowledge": row["knowledge"],
            "is_review": (row.get("review_count") or 0) > 0,
        }

    if rows:
        row = min(rows, key=lambda item: (item["stage"], item["knowledge"]))
        return {"knowledge": row["knowledge"], "is_review": False}

    return {"knowledge": "", "is_review": False}


def due_items(rows, now=None, limit=TOP_N, practiced_only=False):
    """到期复习清单，按“最久没复习”排序，供前端面板展示。

    practiced_only=True 时只留下做过的知识点：从没做过的不算"该复习"，
    不该出现在复习提醒里。
    """
    now = now or now_ts()
    items = [
        dict(row) for row in rows
        if is_due(row, now) and (not practiced_only or (row.get("review_count") or 0) > 0)
    ]
    items.sort(key=lambda row: (row["due_at"], row["knowledge"]))

    for item in items:
        overdue = now - int(item["due_at"])
        item["overdue_text"] = (
            f"已超时{format_interval(overdue).rstrip('后')}" if overdue > 0 else "现在可以复习"
        )
        item["interval_text"] = format_interval(item["interval"])
        item["mastery"] = mastery(item)

    return items[:limit]


def state_from_row(row):
    """models.Review 行 → 调度用的 dict。"""
    return normalize(
        row.interval,
        row.stage,
        int(row.next_review_at.timestamp()) if row.next_review_at else 0,
        row.last_result,
        row.streak,
    )


def apply_state(row, state):
    """把调度结果写回 models.Review 行。"""
    row.stage = state["stage"]
    row.interval = state["interval"]
    row.streak = state["streak"]
    row.last_result = state["last_result"]
    row.next_review_at = to_dt(state["due_at"])
    return row
