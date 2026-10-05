# ==============================================================
# 能力契约｜V2.7 变式阶梯：标准题→近似变式→表达变式→情境变式→结构迁移→综合应用的升级/保持/回退状态机（纯函数）
# 入口：LADDER_STEPS / STEP_BY_LEVEL / UPGRADE_STREAK / DOWNGRADE_STREAK / MAX_STEPS_PER_ROUND /
#       VariantLadder / DEFAULT_ENGINE / step_of / ladder_steps / initial_state / apply_attempt /
#       decide / plan / round_summary
# 依赖：deep_learning.transfer_engine（等级定义与判定）
# 不负责：出题 → transfer_engine.py；落库 → deep_learning/engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py、deep_learning/routes.py、habit 每日计划（TRANSFER 任务）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 变式阶梯（需求 §十五 / §十六 / §三十一 / §四十二）。

    标准题 → 近似变式 → 表达变式 → 情境变式 → 结构迁移 → 综合应用

根据学生表现**升级 / 保持 / 回退**。三条硬约束：

1. **绝不一上来就 T5**（需求 §十四）—— 起始等级由 ``transfer_engine.suggest_level`` 决定；
2. **一轮最多 ``MAX_STEPS_PER_ROUND`` 题**（需求 §三十一 / §四十二：不能因为迁移失败不断追加题目）；
3. 迁移失败只记 ``TRANSFER_GAP``，**基础 mastery 只做有限调整**（需求 §十六）。
"""

from deep_learning import transfer_engine

UPGRADE_STREAK = 2        # 同等级连对 2 次（无提示）→ 升一级
DOWNGRADE_STREAK = 2      # 连错 2 次 → 退一级
MAX_STEPS_PER_ROUND = 3   # 一轮迁移最多出几题（时间预算内）
ROUND_MINUTES = 4         # 一轮迁移的默认时长预算（分钟）
MINUTES_PER_QUESTION = 1.5

# 阶梯台阶（需求 §十五 的六个台阶，与 transfer_engine 的 T0~T5 一一对应）
LADDER_STEPS = (
    {"index": 0, "level": 0, "name": "标准题", "desc": "刚学过的原题，先把方法做对"},
    {"index": 1, "level": 1, "name": "近似变式", "desc": "只换数字，方法不变"},
    {"index": 2, "level": 2, "name": "表达变式", "desc": "换一种说法，意思不变"},
    {"index": 3, "level": 3, "name": "情境变式", "desc": "换一个生活场景"},
    {"index": 4, "level": 4, "name": "结构迁移", "desc": "信息顺序或问题形式变了"},
    {"index": 5, "level": 5, "name": "综合应用", "desc": "数字、情境、结构一起变"},
)

STEP_BY_LEVEL = {item["level"]: dict(item) for item in LADDER_STEPS}

ACTION_TEXT = {
    "upgrade": "这一级已经稳了，我们换更难一点的样子。",
    "hold": "再练一道同样难度的，把方法记牢。",
    "downgrade": "这一级有点难，我们退回去一点，从更简单的样子开始。",
    "stop": "今天的变式就到这里，剩下的时间留给别的任务。",
}
ACTION_CHILD = {
    "upgrade": "太棒了，我们升级！",
    "hold": "再来一道差不多的～",
    "downgrade": "没关系，我们换个简单点的说法。",
    "stop": "今天这个知识点练得很好，先到这里吧！",
}


def step_of(level):
    return dict(STEP_BY_LEVEL.get(transfer_engine.clamp_level(level), STEP_BY_LEVEL[0]))


def ladder_steps():
    return [dict(item) for item in LADDER_STEPS]


def _get(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class VariantLadder:
    """变式阶梯状态机（纯函数）。"""

    # ---------- 状态 ----------

    def initial_state(self, level=0):
        used = transfer_engine.clamp_level(level)
        return {
            "level": used,
            "start_level": used,
            "best_level": used,
            "total": 0,
            "correct": 0,
            "wrong": 0,
            "streak_correct": 0,
            "streak_wrong": 0,
            "hint_used": 0,
            "cleared": [],
            "gap": False,
            "finished": False,
        }

    def apply_attempt(self, state, correct, hint_used=0, confidence=""):
        """把一次作答并入阶梯状态（返回新的 state，不改原对象）。"""
        out = dict(state or self.initial_state())
        out["cleared"] = list(out.get("cleared") or [])

        hints = _int(hint_used)
        sure = str(confidence or "").strip().lower()
        out["total"] = _int(out.get("total")) + 1
        out["hint_used"] = _int(out.get("hint_used")) + hints
        out["level"] = transfer_engine.clamp_level(out.get("level"))

        clean = bool(correct) and hints == 0 and sure != "guess"
        if clean:
            out["correct"] = _int(out.get("correct")) + 1
            out["streak_correct"] = _int(out.get("streak_correct")) + 1
            out["streak_wrong"] = 0
        elif correct:
            out["correct"] = _int(out.get("correct")) + 1
            out["streak_correct"] = 0
            out["streak_wrong"] = 0
        else:
            out["wrong"] = _int(out.get("wrong")) + 1
            out["streak_wrong"] = _int(out.get("streak_wrong")) + 1
            out["streak_correct"] = 0
            if out["level"] >= 2:
                out["gap"] = True

        level = out["level"]
        if clean and out["streak_correct"] >= UPGRADE_STREAK and level < transfer_engine.MAX_LEVEL:
            if level not in out["cleared"]:
                out["cleared"].append(level)
        return out

    # ---------- 升降级 ----------

    def decide(self, state, remaining=None, minutes=None):
        """返回 ``{"action", "level", "reason", "child", "stop"}``（需求 §十五）。"""
        state = dict(state or self.initial_state())
        level = transfer_engine.clamp_level(state.get("level"))
        budget = self.budget(minutes) if remaining is None else _int(remaining, 0)

        if budget <= 0:
            return self._out("stop", level, "今天的迁移时间用完了，剩下的任务放到明天。")

        if _int(state.get("streak_correct")) >= UPGRADE_STREAK:
            if level >= transfer_engine.MAX_LEVEL:
                return self._out("stop", level, "最高一级（综合应用）也稳了，这个知识点的迁移已经完成。")
            return self._out("upgrade", level + 1,
                             "连续 %d 次无提示做对，可以升到「%s」。" % (UPGRADE_STREAK, step_of(level + 1)["name"]))

        if _int(state.get("streak_wrong")) >= DOWNGRADE_STREAK:
            if level <= 0:
                return self._out("stop", 0, "标准题还没稳，先回到基础练习，今天不继续迁移。")
            return self._out("downgrade", level - 1,
                             "连续 %d 次没做出来，先退回「%s」。" % (DOWNGRADE_STREAK, step_of(level - 1)["name"]))

        return self._out("hold", level, "保持「%s」再练一道。" % step_of(level)["name"])

    @staticmethod
    def _out(action, level, reason):
        return {
            "action": action,
            "level": transfer_engine.clamp_level(level),
            "step": step_of(level),
            "reason": reason,
            "child": ACTION_CHILD.get(action, ""),
            "text": ACTION_TEXT.get(action, ""),
            "stop": action == "stop",
        }

    # ---------- 时间预算 ----------

    def budget(self, minutes=None):
        """本轮还能出几题（需求 §三十一：深度学习不能无限延长 Session）。"""
        try:
            total = float(minutes) if minutes is not None else ROUND_MINUTES
        except (TypeError, ValueError):
            total = ROUND_MINUTES
        count = int(total // MINUTES_PER_QUESTION)
        return max(0, min(MAX_STEPS_PER_ROUND, count))

    # ---------- 一轮的完整计划 ----------

    def plan(self, level=0, minutes=None, mastery_score=0, deep_level=0, variant_failures=0):
        """生成一轮迁移的题目安排（只给等级与顺序，不出题）。"""
        start = transfer_engine.clamp_level(level)
        if level is None:
            start = transfer_engine.suggest_level(mastery_score, deep_level, variant_failures)["level"]

        state = self.initial_state(start)
        steps = self.budget(minutes)
        plan = []
        for _ in range(steps):
            decision = self.decide(state, remaining=steps - len(plan))
            if decision["stop"]:
                break
            state["level"] = decision["level"]
            plan.append({
                "order": len(plan) + 1,
                "level": decision["level"],
                "step": decision["step"],
                "variant_change": transfer_engine.level_dict(decision["level"])["change"],
                "action": decision["action"],
            })
        return {
            "mode": "TRANSFER_LADDER",
            "start_level": start,
            "steps": plan,
            "count": len(plan),
            "minutes": round(len(plan) * MINUTES_PER_QUESTION, 1),
            "max_steps": MAX_STEPS_PER_ROUND,
            "message": "今天用 %d 道变式题看看你是不是真的会了。" % len(plan),
            "ladder": ladder_steps(),
        }

    # ---------- 收尾 ----------

    def round_summary(self, state, mastery_score=0):
        """一轮结束后的总结与下一步（需求 §十六：迁移失败给出可执行的下一步）。"""
        state = dict(state or self.initial_state())
        level = transfer_engine.clamp_level(state.get("level"))
        wrong = _int(state.get("wrong"))
        gap = bool(state.get("gap"))
        cleared = list(state.get("cleared") or [])

        next_action = transfer_engine.gap_action(level, wrong == 0, mastery_score) if wrong else \
            {"action": "UPGRADE", "name": "继续升级", "reason": "这一轮全对。", "child": "下一轮我们试更难的样子。"}

        if not wrong:
            text = "换了样子也都会做，这是很扎实的迁移证据。"
        elif gap and _int(state.get("correct")) > 0:
            text = "标准题会做、换了样子不太稳 —— 这是迁移还没到位，不是整个知识不会。"
        else:
            text = "这一轮变式有困难，我们先补一补关系再回来。"

        return {
            "level": level,
            "best_level": transfer_engine.clamp_level(state.get("best_level", level)),
            "cleared": cleared,
            "total": _int(state.get("total")),
            "correct": _int(state.get("correct")),
            "wrong": wrong,
            "transfer_gap": gap,
            "mastery_penalty": 0.5 if gap else 1.0,
            "evidence": "TRANSFER",
            "next": next_action,
            "message": text,
        }


DEFAULT_ENGINE = VariantLadder()


def step_of_level(level):
    return step_of(level)


def initial_state(level=0):
    return DEFAULT_ENGINE.initial_state(level)


def apply_attempt(state, correct, hint_used=0, confidence=""):
    return DEFAULT_ENGINE.apply_attempt(state, correct, hint_used, confidence)


def decide(state, remaining=None, minutes=None):
    return DEFAULT_ENGINE.decide(state, remaining, minutes)


def plan(level=0, minutes=None, mastery_score=0, deep_level=0, variant_failures=0):
    return DEFAULT_ENGINE.plan(level, minutes, mastery_score, deep_level, variant_failures)


def round_summary(state, mastery_score=0):
    return DEFAULT_ENGINE.round_summary(state, mastery_score)
