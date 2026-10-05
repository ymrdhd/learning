# ==============================================================
# 能力契约｜错题康复纯状态机：六态流转 + 连对/连错计数规则（绝不碰数据库）
# 入口：RecoveryState / transition / apply_result / next_action / is_active / state_text / VERIFY_STREAK
# 依赖：无（纯标准库常量与纯函数，不 import 数据库、不 import models）
# 不负责：策略与提示层级 → recovery/strategy.py；落库与判分 → recovery/engine.py
# 验证：python backend/verify_recovery.py（Agent 7 门禁）
# 被调用：recovery/engine.py、recovery/strategy.py、recovery/scheduler.py、recovery_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复状态机（纯函数：无数据库、无 AI、无副作用）。

状态图（文字版，见 SPEC.md §4）：

    NEW ──analyze──▶ ANALYZING ──hint──▶ LEARNING
                                            │ 答对 → 进入练习
                                            ▼
    NEW ◀── 连错 2 次（fail_count % 2 == 0）── PRACTICING ◀──┐
                                            │ 变式题连对 2 次   │ 验证未过 / 超时
                                            ▼                   │
                                        VERIFYING ──────────────┘
                                            │ 原题（同知识点题）答对
                                            ▼
                                        MASTERED（再次答错 → NEW）

计数规则（SPEC.md §4 逐条实现，engine 只负责把它落到表行上）：
- PRACTICING 每答对 1 次 ``consecutive_correct += 1``；``>= 2`` → VERIFYING（1 天后验证）。
- PRACTICING 答错 → ``consecutive_correct = 0``、``fail_count += 1``；``fail_count % 2 == 0`` → NEW。
- VERIFYING 答对 → MASTERED；答错 / 超时 → PRACTICING（连对清零）。
- 任何状态再次答错原题 → NEW，``state_before`` 记原状态，``fail_count += 1``（事件 ``relearn``）。
"""

NEW = "NEW"
ANALYZING = "ANALYZING"
LEARNING = "LEARNING"
PRACTICING = "PRACTICING"
VERIFYING = "VERIFYING"
MASTERED = "MASTERED"

EVENT_ANALYZE = "analyze"
EVENT_HINT = "hint"
EVENT_PRACTICE = "practice"
EVENT_CORRECT = "correct"
EVENT_WRONG = "wrong"
EVENT_VERIFY_PASS = "verify_pass"
EVENT_VERIFY_FAIL = "verify_fail"
EVENT_VERIFY_TIMEOUT = "verify_timeout"
EVENT_RELEARN = "relearn"

VERIFY_STREAK = 2          # 变式题连对几次进 VERIFYING
RELEARN_FAIL_STEP = 2      # 每累计错几次回炉 NEW
VERIFY_DAYS = 1            # VERIFYING 到期天数

ACTION_BY_STATE = {
    NEW: "analyze",
    ANALYZING: "hint",
    LEARNING: "hint",
    PRACTICING: "practice",
    VERIFYING: "verify",
    MASTERED: "celebrate",
}


class RecoveryState:
    """康复状态常量：6 态 + 顺序 + 中文文案（SPEC §3.1 / §4.1）。"""

    NEW = NEW
    ANALYZING = ANALYZING
    LEARNING = LEARNING
    PRACTICING = PRACTICING
    VERIFYING = VERIFYING
    MASTERED = MASTERED

    ORDER = (NEW, ANALYZING, LEARNING, PRACTICING, VERIFYING, MASTERED)
    ALL = ORDER
    ACTIVE = (NEW, ANALYZING, LEARNING, PRACTICING, VERIFYING)
    TEXT = {
        NEW: "刚进康复队列，还没分析",
        ANALYZING: "正在找错因，准备讲解",
        LEARNING: "跟着分层提示学",
        PRACTICING: "练同知识点的变式题",
        VERIFYING: "原题验证中",
        MASTERED: "已康复",
    }


EVENTS = (EVENT_ANALYZE, EVENT_HINT, EVENT_PRACTICE, EVENT_CORRECT, EVENT_WRONG,
          EVENT_VERIFY_PASS, EVENT_VERIFY_FAIL, EVENT_VERIFY_TIMEOUT, EVENT_RELEARN)


def _as_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def normalize(state):
    """状态归一化：去空白、转大写；未知值原样返回（调用方自行降级）。"""
    return str(state or "").strip().upper()


def state_text(state):
    """状态的中文文案；未知状态返回原值字符串。"""
    name = normalize(state)
    return RecoveryState.TEXT.get(name, str(state or ""))


def is_active(state):
    """是否仍在康复流程中（MASTERED 视为已完成，不活跃）。"""
    return normalize(state) in RecoveryState.ACTIVE


def next_action(state):
    """下一步该干什么：analyze / hint / practice / verify / celebrate。"""
    return ACTION_BY_STATE.get(normalize(state), "analyze")


def _advance(state, correct, consecutive_correct, fail_count):
    """按当前状态 + 本次对错，算出 (next_state, cc, fail_count, reason, mastered, enter_verifying)。"""
    cc = max(0, _as_int(consecutive_correct))
    fails = max(0, _as_int(fail_count))

    if state == MASTERED:
        if correct:
            return MASTERED, cc, fails, "已康复，原题答对不改变状态", False, False
        return NEW, 0, fails + 1, "已康复的题再次答错 → 回炉 NEW", False, False

    if state == VERIFYING:
        if correct:
            return MASTERED, cc, fails, "原题验证通过 → MASTERED", True, False
        return PRACTICING, 0, fails + 1, "验证未过 → 回 PRACTICING 继续练", False, False

    if state == PRACTICING:
        if correct:
            cc += 1
            if cc >= VERIFY_STREAK:
                return VERIFYING, cc, fails, f"变式题连对 {VERIFY_STREAK} 次 → VERIFYING", False, True
            return PRACTICING, cc, fails, f"变式题答对（连对 {cc}/{VERIFY_STREAK}）", False, False
        fails += 1
        if fails % RELEARN_FAIL_STEP == 0:
            return NEW, 0, fails, f"变式题连错 {RELEARN_FAIL_STEP} 次 → 回炉 NEW", False, False
        return PRACTICING, 0, fails, "变式题答错（再错一次回炉）", False, False

    # NEW / ANALYZING / LEARNING（教学阶段）
    if correct:
        return PRACTICING, min(cc + 1, VERIFY_STREAK - 1), fails, "教学阶段答对 → 进入 PRACTICING", False, False
    return NEW, 0, fails + 1, "答错原题 → 回炉 NEW", False, False


def _build(before, after, cc, fails, reason, mastered=False, enter_verifying=False):
    return {
        "state": after,                 # 迁移后的目标状态（与 next_state 同义）
        "next_state": after,
        "state_before": before if after != before else "",
        "changed": after != before,
        "reason": reason,
        "consecutive_correct": max(0, _as_int(cc)),
        "fail_count": max(0, _as_int(fails)),
        "mastered": bool(mastered),
        "enter_verifying": bool(enter_verifying),
        "verify_delay_days": VERIFY_DAYS if enter_verifying else 0,
        "next_action": next_action(after),
    }


def transition(state, event, *, consecutive_correct=0, fail_count=0):
    """状态迁移：``state`` + 事件 → dict(state, changed, reason, next_state, ...)。

    返回字段：``state``/``next_state``（迁移后的状态，两者同义）、``state_before``（原状态，
    未变化时为空串）、``changed``（状态是否变化，布尔）、``reason``（中文原因）、
    ``consecutive_correct`` / ``fail_count``（更新后的计数）、``mastered``、``enter_verifying``、
    ``verify_delay_days``（进 VERIFYING 时的天数）、``next_action``。
    """
    before = normalize(state)
    name = str(event or "").strip().lower()
    cc = max(0, _as_int(consecutive_correct))
    fails = max(0, _as_int(fail_count))

    if name in (EVENT_CORRECT, EVENT_VERIFY_PASS):
        return _build(before, *_advance(before, True, cc, fails))
    if name in (EVENT_WRONG, EVENT_VERIFY_FAIL):
        return _build(before, *_advance(before, False, cc, fails))
    if name == EVENT_RELEARN:                      # 任何状态再次答错原题
        return _build(before, NEW, 0, fails + 1, "再次答错原题 → 回炉 NEW", False, False)
    if name == EVENT_VERIFY_TIMEOUT:
        if before == VERIFYING:
            return _build(before, PRACTICING, cc, fails, "验证到期未通过 → 回 PRACTICING", False, False)
        return _build(before, before, cc, fails, "当前状态无需验证", False, False)
    if name == EVENT_ANALYZE:
        if before == NEW:
            return _build(before, ANALYZING, cc, fails, "开始定位错因 → ANALYZING", False, False)
        return _build(before, before, cc, fails, "已在分析之后，状态不变", False, False)
    if name == EVENT_HINT:
        if before in (NEW, ANALYZING, LEARNING):
            return _build(before, LEARNING, cc, fails, "进入分层提示教学 → LEARNING", False, False)
        return _build(before, before, cc, fails, "当前状态无需讲解", False, False)
    if name == EVENT_PRACTICE:
        if before in (NEW, ANALYZING, LEARNING, PRACTICING):
            return _build(before, PRACTICING, cc, fails, "开始练变式题 → PRACTICING", False, False)
        return _build(before, before, cc, fails, "当前状态不出练习变式题", False, False)

    return _build(before, before, cc, fails, f"未知事件 {name or '(空)'}：状态不变", False, False)


def apply_result(state, correct, *, consecutive_correct=0, fail_count=0):
    """一次作答的结果推进（对 = correct 事件，错 = wrong 事件），返回字段同 transition。"""
    event = EVENT_CORRECT if correct else EVENT_WRONG
    result = transition(state, event, consecutive_correct=consecutive_correct,
                        fail_count=fail_count)
    result["correct"] = bool(correct)
    return result
