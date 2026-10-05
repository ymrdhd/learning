# ==============================================================
# 能力契约｜康复策略纯函数：下一步动作、提示层级 1~4、难度、题型与题量
# 入口：RecoveryStrategy（plan / hint_level_for / should_vary）/ DEFAULT_STRATEGY
# 依赖：recovery.state（纯状态机）
# 不负责：状态落库与判分 → recovery/engine.py；AI 文案生成 → ai_recovery.py
# 验证：python backend/verify_recovery.py（Agent 7 门禁）
# 被调用：recovery/engine.py、recovery_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复策略（纯函数，不碰数据库、不调 AI）。

规则：
1. ``plan()`` 把「一个康复项现在该干什么」翻译成 action / hint_level / difficulty /
   question_type / target_count 五件事，供 engine 出题与写日志。
2. 提示层级只升不降：``hint_level_for`` 的结果不会低于该行已用过的 ``max_level_used``（0~4）。
3. 练变式题连错时逐级降难度（每次 -5，最多 -20），原题验证（VERIFYING）沿用原题难度。
4. ``should_vary`` 决定出「变式题」还是「原题」：VERIFYING 出原题，教学/练习阶段出变式题。
"""

from recovery.state import (
    ANALYZING, LEARNING, MASTERED, NEW, PRACTICING, VERIFYING,
    next_action as state_action,
)

HINT_MIN, HINT_MAX = 1, 4
DIFFICULTY_MIN, DIFFICULTY_MAX = 10, 95

TARGET_COUNT = {NEW: 1, ANALYZING: 1, LEARNING: 1, PRACTICING: 3, VERIFYING: 1, MASTERED: 0}

ACTION_TEXT = {
    "analyze": "先定位错因",
    "hint": "给分层提示讲解",
    "practice": "练同知识点的变式题",
    "verify": "用原题验证是否真的会了",
    "celebrate": "已康复，可以庆祝",
}


def _value(item, key, default=None):
    """兼容 dict / ORM 行两种入参。"""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _as_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


def _mastery_score(mastery):
    """mastery 可以是数字，也可以是带 mastery_score / score 的 dict 或 ORM 行。"""
    if mastery is None:
        return None
    if isinstance(mastery, (int, float)):
        return _as_int(mastery, 0)
    score = _value(mastery, "mastery_score", None)
    if score is None:
        score = _value(mastery, "score", None)
    return None if score is None else _as_int(score, 0)


def _difficulty(item, mastery=None):
    """出题难度基准：掌握度 → item.difficulty → 关联题目 difficulty → 50。"""
    score = _mastery_score(mastery)
    if score is None:
        score = _value(item, "difficulty", None)
    if score is None:
        question = _value(item, "question_row", None)
        score = _value(question, "difficulty", None) if question is not None else None
    value = _as_int(score, 50)
    return value if value > 0 else 50


class RecoveryStrategy:
    """错题康复策略：决定下一个动作、提示层级、难度与题量（纯计算）。"""

    def plan(self, item, *, mastery=None, hint_level=0):
        """给出一个康复项的下一步计划。

        返回 ``{"action", "hint_level", "difficulty", "question_type", "target_count", "reason"}``。
        ``hint_level`` 为 0 只在 MASTERED（celebrate）时出现，其余状态为 1~4。
        """
        state = str(_value(item, "state", "") or NEW).strip().upper()
        attempts = max(0, _as_int(_value(item, "attempts", 0)))
        fails = max(0, _as_int(_value(item, "fail_count", 0)))
        max_used = _as_int(_value(item, "max_level_used", 0))

        action = state_action(state)
        level = self.hint_level_for(attempts, max_used, fails)
        if hint_level:
            level = _clamp(_as_int(hint_level, HINT_MIN), HINT_MIN, HINT_MAX)
        if action == "celebrate":
            level = 0
        elif action == "analyze" and not hint_level:
            level = HINT_MIN

        original = _difficulty(item)
        difficulty = _difficulty(item, mastery)
        if state == PRACTICING and fails:
            difficulty -= 5 * min(fails, 4)
        difficulty = _clamp(difficulty, DIFFICULTY_MIN, DIFFICULTY_MAX)
        if state == VERIFYING:                       # 原题验证：沿用原题难度
            difficulty = _clamp(original, 1, 100)

        question_type = _value(item, "qtype", None)
        if not question_type:
            question_row = _value(item, "question_row", None)
            question_type = _value(question_row, "qtype", None) if question_row is not None else None

        target_count = TARGET_COUNT.get(state, 1)
        reason = (f"{ACTION_TEXT.get(action, action)}；提示 Level{level}，"
                  f"难度 {difficulty}，计划 {target_count} 题")
        return {
            "action": action,
            "hint_level": level,
            "difficulty": difficulty,
            "question_type": question_type or "choice",
            "target_count": target_count,
            "reason": reason,
        }

    def hint_level_for(self, attempts, max_level_used, fail_count):
        """该给到第几级提示（1~4）：答得越多 / 错得越多给得越细，且不低于已用层级。"""
        attempts = max(0, _as_int(attempts))
        used = max(0, _as_int(max_level_used))
        fails = max(0, _as_int(fail_count))
        level = _clamp(1 + attempts // 2 + fails, HINT_MIN, HINT_MAX)
        if used > 0:
            level = max(level, _clamp(used, HINT_MIN, HINT_MAX))
        return level

    def should_vary(self, state, attempts=0):
        """是否出「变式题」：VERIFYING 用原题；教学 / 练习阶段用变式题。"""
        name = str(state or "").strip().upper()
        if name in (VERIFYING, MASTERED):
            return False
        if name in (PRACTICING, LEARNING):
            return True
        return _as_int(attempts) > 0 and name == ANALYZING


DEFAULT_STRATEGY = RecoveryStrategy()
