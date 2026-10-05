# ==============================================================
# 能力契约｜V2.7 学习效率引擎：判断学习投入是否产生真实收益（不看做题速度），只给 Adaptive/Daily Plan/家长报告用
# 入口：EFFICIENCY_BANDS / GAIN_FIELDS / WEIGHTS / PENALTY_WEIGHTS / LearningEfficiencyEngine /
#       DEFAULT_ENGINE / clamp_gain / evaluate / band_of / child_text / parent_text / advice / aggregate
# 依赖：无（纯函数；数据库聚合由 deep_learning/engine.py 提供）
# 不负责：儿童端展示数字分数（禁止，需求 §二十九：儿童端只说"今天15分钟学会了2个知识"）
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py、deep_learning/routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 学习效率引擎（需求 §二十八 / §二十九）。

目的：判断**学习投入是否产生真实收益**。

参考量（需求 §二十八 原文）：learning_minutes / mastery_gain / deep_mastery_gain /
memory_gain / recovery_gain / hint_dependency / repeated_failure。

**明令禁止**：把做题速度当主要效率指标（需求 §二十八）。

用途（需求 §二十九）：Adaptive Engine、Daily Plan、未来家长报告。
**儿童端不要显示「效率 63 分」**，只能说「今天 15 分钟学会了 2 个知识」。
"""

# 收益项：字段 → 权重（掌握 + 深度理解是主体，记忆次之，康复再次）
WEIGHTS = {
    "mastery_gain": 0.30,
    "deep_mastery_gain": 0.30,
    "memory_gain": 0.25,
    "recovery_gain": 0.15,
}

GAIN_FIELDS = tuple(WEIGHTS.keys())

# 惩罚项：提示依赖与反复失败都说明"看起来在学，其实没长进"
PENALTY_WEIGHTS = {
    "hint_dependency": 20.0,
    "repeated_failure": 5.0,
}
MAX_PENALTY = 35.0

# 单次会话（或一周）里，单项收益最多算到这里，防止刷题把分数顶满
GAIN_CAP = 30.0
BASE_SCORE = 40.0
GAIN_SCALE = 5.0

# 效率档位（内部 + 家长报告用；儿童端不出现）
EFFICIENCY_BANDS = (
    {"key": "high", "min": 75, "text": "学得很扎实", "parent": "投入产出比高，当前方法有效"},
    {"key": "mid", "min": 55, "text": "正常进度", "parent": "有稳定收益，可以继续当前节奏"},
    {"key": "low", "min": 35, "text": "收益偏少", "parent": "花了时间但掌握提升有限，建议调整方法"},
    {"key": "poor", "min": 0, "text": "需要换方法", "parent": "重复投入没有产生掌握提升，优先换讲解方式而不是加量"},
)
BAND_UNKNOWN = {"key": "unknown", "min": 0, "text": "还没有足够数据", "parent": "数据不足，无法评估"}

# 建议（给 Adaptive Engine / Daily Plan 用）
ADVICE = {
    "hint_dependency": "下一个任务先用「自己想」的形式出题，减少提示层级",
    "repeated_failure": "换一种讲解方式（讲解 / 变式 / 讲给菲比听），不要继续刷同类题",
    "low_deep_gain": "标准题会做了但深度没上来，安排一次变式或解释练习",
    "low_memory_gain": "记忆没稳住，把这块放进间隔复习队列",
    "good": "保持当前节奏，不需要额外加量",
}

MIN_MINUTES = 1
SPEED_NOTE = "效率不使用做题速度作为指标"


def clamp_gain(value):
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(-GAIN_CAP, min(GAIN_CAP, number))


class LearningEfficiencyEngine:
    """学习效率评估（纯函数）。"""

    def evaluate(self, learning_minutes=0, mastery_gain=0.0, deep_mastery_gain=0.0,
                 memory_gain=0.0, recovery_gain=0.0, hint_dependency=0.0,
                 repeated_failure=0, learned_count=0, evidence_count=0):
        """评估一次会话 / 一段时间的效率。

        返回 ``{score, band, band_text, real_gain, gains{}, penalties{}, child_text,
        parent_text, advice[], has_data, ...}``。
        """
        gains = {
            "mastery_gain": clamp_gain(mastery_gain),
            "deep_mastery_gain": clamp_gain(deep_mastery_gain),
            "memory_gain": clamp_gain(memory_gain),
            "recovery_gain": clamp_gain(recovery_gain),
        }
        real_gain = sum(gains[field] * weight for field, weight in WEIGHTS.items())

        try:
            hint = max(0.0, min(1.0, float(hint_dependency or 0.0)))
        except (TypeError, ValueError):
            hint = 0.0
        try:
            failures = max(0, int(repeated_failure or 0))
        except (TypeError, ValueError):
            failures = 0

        penalties = {
            "hint_dependency": round(PENALTY_WEIGHTS["hint_dependency"] * hint, 3),
            "repeated_failure": round(min(20.0, PENALTY_WEIGHTS["repeated_failure"] * failures), 3),
        }
        penalty = min(MAX_PENALTY, sum(penalties.values()))

        try:
            minutes = max(0, int(learning_minutes or 0))
        except (TypeError, ValueError):
            minutes = 0

        has_data = bool(evidence_count) or minutes > 0 or abs(real_gain) > 0.001

        score = BASE_SCORE + real_gain * GAIN_SCALE - penalty
        score = int(max(0, min(100, round(score)))) if has_data else 0

        band = self.band_of(score) if has_data else dict(BAND_UNKNOWN)

        return {
            "score": score,
            "band": band["key"],
            "band_text": band["text"],
            "real_gain": round(real_gain, 3),
            "gains": gains,
            "penalties": penalties,
            "penalty": round(penalty, 3),
            "learning_minutes": minutes,
            "learned_count": int(learned_count or 0),
            "evidence_count": int(evidence_count or 0),
            "hint_dependency": round(hint, 3),
            "repeated_failure": failures,
            "has_data": has_data,
            "child_text": self.child_text(minutes, learned_count),
            "parent_text": self.parent_text(score, band, real_gain, penalty),
            "advice": self.advice(hint_dependency=hint, repeated_failure=failures,
                                  deep_mastery_gain=gains["deep_mastery_gain"],
                                  memory_gain=gains["memory_gain"], score=score),
            "note": SPEED_NOTE,
        }

    def band_of(self, score):
        try:
            value = float(score or 0)
        except (TypeError, ValueError):
            value = 0.0
        for item in EFFICIENCY_BANDS:
            if value >= item["min"]:
                return dict(item)
        return dict(EFFICIENCY_BANDS[-1])

    def child_text(self, minutes=0, learned_count=0):
        """儿童端文案（需求 §二十九）：**不出现分数**。"""
        try:
            minutes = max(0, int(minutes or 0))
        except (TypeError, ValueError):
            minutes = 0
        try:
            learned = max(0, int(learned_count or 0))
        except (TypeError, ValueError):
            learned = 0

        if learned <= 0:
            if minutes > 0:
                return "今天你坚持练了 %d 分钟，菲比都看到了～" % minutes
            return "今天还没开始，我们慢慢来。"
        if minutes <= 0:
            return "今天你学会了 %d 个知识！" % learned
        return "今天 %d 分钟学会了 %d 个知识。" % (minutes, learned)

    def parent_text(self, score, band, real_gain=0.0, penalty=0.0):
        """家长报告用一句话（可以出现数字）。"""
        return "效率 %d 分（%s）：真实掌握提升 %.1f 分，扣分 %.1f 分（提示依赖 / 反复失败）。" % (
            int(score or 0), band.get("text", ""), float(real_gain or 0.0), float(penalty or 0.0))

    def advice(self, hint_dependency=0.0, repeated_failure=0, deep_mastery_gain=0.0,
               memory_gain=0.0, score=70):
        out = []
        if float(hint_dependency or 0) >= 0.6:
            out.append(ADVICE["hint_dependency"])
        if int(repeated_failure or 0) >= 2:
            out.append(ADVICE["repeated_failure"])
        if float(deep_mastery_gain or 0) <= 0.5:
            out.append(ADVICE["low_deep_gain"])
        if float(memory_gain or 0) <= 0.5:
            out.append(ADVICE["low_memory_gain"])
        if not out:
            out.append(ADVICE["good"])
        return out

    def aggregate(self, rows, days=7):
        """把多条明细聚合成一次效率评估。

        ``rows`` 每项可含 ``{minutes, mastery_gain, deep_mastery_gain, memory_gain,
        recovery_gain, hint_level, correct, learned}``。
        """
        minutes = 0
        totals = {field: 0.0 for field in GAIN_FIELDS}
        hint_sum = 0.0
        hint_count = 0
        failures = 0
        learned = 0
        count = 0

        for row in rows or ():
            item = row or {}
            count += 1
            try:
                minutes += max(0, int(item.get("minutes") or 0))
            except (TypeError, ValueError):
                pass
            for field in GAIN_FIELDS:
                totals[field] += clamp_gain(item.get(field) or 0.0)
            try:
                hint_sum += max(0.0, float(item.get("hint_level") or 0.0))
                hint_count += 1
            except (TypeError, ValueError):
                pass
            if item.get("correct") is False:
                failures += 1
            if item.get("learned"):
                learned += 1

        hint_dependency = (hint_sum / hint_count / 4.0) if hint_count else 0.0

        return self.evaluate(
            learning_minutes=minutes,
            mastery_gain=totals["mastery_gain"],
            deep_mastery_gain=totals["deep_mastery_gain"],
            memory_gain=totals["memory_gain"],
            recovery_gain=totals["recovery_gain"],
            hint_dependency=hint_dependency,
            repeated_failure=failures,
            learned_count=learned,
            evidence_count=count,
        )


DEFAULT_ENGINE = LearningEfficiencyEngine()



def evaluate(**kwargs):
    return DEFAULT_ENGINE.evaluate(**kwargs)


def band_of(score):
    return DEFAULT_ENGINE.band_of(score)


def child_text(minutes=0, learned_count=0):
    return DEFAULT_ENGINE.child_text(minutes, learned_count)


def parent_text(score, band, real_gain=0.0, penalty=0.0):
    return DEFAULT_ENGINE.parent_text(score, band, real_gain, penalty)


def advice(**kwargs):
    return DEFAULT_ENGINE.advice(**kwargs)


def aggregate(rows, days=7):
    return DEFAULT_ENGINE.aggregate(rows, days)
