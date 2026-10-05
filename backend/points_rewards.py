# ==============================================================
# 能力契约｜积分明细（第一版奖励行为表：只描述规则，自己不判定、不加分）
# 入口：REWARD_VERSION / REWARDS / REWARD_STATES / reward_table / rewards_of / points_text
# 依赖：无（纯常量 + 纯函数，可离线单测）
# 不负责：判断"这件事发生了没有"与写账本 → points.py（award / award_after_answer /
#         award_task_done / checkin）；HTTP 接口 → points_routes.py
# 验证：python backend/verify_points.py
# 被调用：points.py（summary 里拼进积分明细）、frontend/shop.js（渲染商城明细）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""第一版奖励行为表（积分明细的唯一真相）。

这张表是「🛍️ 积分商城」页里给孩子和家长看的规则清单，**只描述规则**。每条给出：

    points_min / points_max  分值（区间表示"按表现取区间内的分"）
    stars                    重要程度 ★1~5（0 = 不给星）
    note                     为什么给这份分
    state                    当前状态：
                             live    已经在自动记分（event 指向 points.RULES 的事件）
                             planned 规则已定，判定还没接（第一版先展示，不虚报分数）
                             never   永远不给分（登录 / 停留 / 点击，屏幕时间绝不奖励）

纪律：这里的分值是**用户定的第一版口径**，改动前先确认；判定接线时把 event 填上，
不要在 points.py 里另写一套分值。
"""

REWARD_VERSION = "第一版"

REWARD_STATES = {
    "live": "✅ 已经在记分",
    "planned": "🔜 先给你看规则",
    "never": "🚫 永不给分",
}

# 分值区间按 (points_min, points_max)；event 为空表示自动判定还没接。
REWARDS = (
    {"key": "first_mastery", "label": "首次真正掌握一个知识点",
     "points_min": 100, "points_max": 100, "stars": 5,
     "note": "最核心学习成果", "state": "planned", "event": ""},
    {"key": "deep_mastery_upgrade", "label": "Deep Mastery 升级：会做→会迁移",
     "points_min": 80, "points_max": 80, "stars": 5,
     "note": "证明不是机械套题", "state": "planned", "event": ""},
    {"key": "wrong_recovery_done", "label": "错题完整康复",
     "points_min": 80, "points_max": 80, "stars": 5,
     "note": "奖励面对弱点", "state": "planned", "event": ""},
    {"key": "memory_after_days", "label": "7天/更长时间后仍记得",
     "points_min": 70, "points_max": 70, "stars": 5,
     "note": "奖励长期记忆", "state": "planned", "event": ""},
    {"key": "transfer_question", "label": "综合迁移题成功",
     "points_min": 60, "points_max": 80, "stars": 5,
     "note": "检验真实理解", "state": "planned", "event": ""},
    {"key": "teach_phoebe", "label": "「讲给菲比听」成功",
     "points_min": 50, "points_max": 50, "stars": 4,
     "note": "奖励解释和深度理解", "state": "planned", "event": ""},
    {"key": "recall_without_hint", "label": "无提示主动回忆成功",
     "points_min": 40, "points_max": 40, "stars": 4,
     "note": "强化记忆提取", "state": "planned", "event": ""},
    {"key": "prerequisite_fix", "label": "完成前置知识修复",
     "points_min": 40, "points_max": 60, "stars": 4,
     "note": "修复真正基础漏洞", "state": "planned", "event": ""},
    {"key": "daily_plan_done", "label": "完成今日学习计划",
     "points_min": 30, "points_max": 30, "stars": 4,
     "note": "培养稳定习惯", "state": "planned", "event": ""},
    {"key": "review_success", "label": "间隔复习成功",
     "points_min": 20, "points_max": 40, "stars": 4,
     "note": "按间隔和难度调整", "state": "planned", "event": ""},
    {"key": "hint_then_solo", "label": "使用低级提示后独立完成",
     "points_min": 10, "points_max": 20, "stars": 3,
     "note": "奖励坚持，但低于独立完成", "state": "planned", "event": ""},
    {"key": "answer_correct", "label": "普通适龄题独立答对",
     "points_min": 2, "points_max": 5, "stars": 2,
     "note": "即时反馈，但不能成为主要积分来源", "state": "live",
     "event": "answer_correct"},
    {"key": "mastered_repeat", "label": "已掌握简单题重复答对",
     "points_min": 0, "points_max": 1, "stars": 1,
     "note": "防止刷分", "state": "planned", "event": ""},
    {"key": "screen_time", "label": "停留、点击、刷页面",
     "points_min": 0, "points_max": 0, "stars": 0,
     "note": "绝不奖励屏幕时间", "state": "never", "event": ""},
)


def reward_table():
    """积分明细（第一版奖励行为表）——每条一个 dict，按重要性从高到低排列。"""
    return [dict(item) for item in REWARDS]


def rewards_of(state):
    """按状态筛出条目（``live`` / ``planned`` / ``never``）。"""
    return [dict(item) for item in REWARDS if item.get("state") == state]


def points_text(item):
    """一条规则的分值文案：``+100`` / ``+60~80`` / ``0 分``。"""
    low = int(item.get("points_min") or 0)
    high = int(item.get("points_max") or 0)
    if low == 0 and high == 0:
        return "0 分"
    if low == high:
        return "+%d" % low
    return "+%d~%d" % (low, high)
