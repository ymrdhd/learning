# ==============================================================
# 能力契约｜复习质量 → 下次间隔的计算（纯函数，含掌握度/难度/稳定性/时间/反馈因子）
# 入口：calculate_next_interval / quality_of / initial_interval_days / ladder_preview / mastery_factor / difficulty_factor / stability_factor
# 依赖：math datetime
# 不负责：旧 11 级阶梯 → srs.py（另一套体系）
# 验证：python backend/verify_memory.py
# 被调用：review/engine.py、review_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 · 自适应间隔计算 `calculate_next_interval()`。

不是机械复制艾宾浩斯曲线，而是"**阶梯起步 + 稳定性驱动**"的可解释算法：

```text
初始学习成功            → 1 天后复习
第 1 次复习成功（GOOD） → 3 天
第 2 次                 → 7 天
第 3 次                 → 14 天
第 4 次                 → 30 天
之后                    → 按记忆稳定性动态扩大（最长 180 天）
```

每一档还会按复习质量缩放：

| review_quality | 含义 | 间隔乘数 | 阶梯加成 |
| --- | --- | --- | --- |
| `AGAIN` | 完全忘记 | ×0.35 | 直接压缩，回短周期 |
| `HARD` | 想了很久 | ×1.0 | ×0.7 |
| `GOOD` | 正常想起来 | ×1.4 | ×1.0 |
| `EASY` | 非常容易 | ×1.8 | ×1.5 |

约束：间隔恒在 **1~180 天**；失败时按 0.35 压缩；稳定性驱动阶段还会限制
"间隔不超过新稳定性的 3 倍"，避免安排一个记不住的超长间隔。

各因子（都可在返回值的 `factors` 里查到）：

- **掌握度**：≥85 ×1.15 / 70~84 ×1.0 / 60~69 ×0.85 / <60 ×0.7
- **个人难度**：`× (1 − 0.3 × difficulty)`，越难的知识间隔涨得越慢
- **稳定性**：`× (1 + 0.15 × min(1.5, stability/30))`，已经记牢的可以拉更长
- **答题速度**：正确且用时 < 期望时间一半 ×1.1；> 1.5 倍 ×0.9
- **学生自评**：简单 ×1.1；有点难 ×0.9
- **掌握度置信度**：题量少（<0.4）时 ×0.8，先短间隔确认
"""

import math
from datetime import datetime, timedelta

QUALITY_ORDER = ("AGAIN", "HARD", "GOOD", "EASY")
QUALITY_TEXT = {
    "AGAIN": "完全忘记",
    "HARD": "想了很久",
    "GOOD": "正常想起来",
    "EASY": "非常容易",
}

# 复习质量 → 间隔乘数（需求给定）
QUALITY_MULTIPLIER = {"AGAIN": 0.35, "HARD": 1.0, "GOOD": 1.4, "EASY": 1.8}
# 阶梯阶段的质量加成（保证 GOOD 正好走 1/3/7/14/30）
LADDER_BONUS = {"HARD": 0.7, "GOOD": 1.0, "EASY": 1.5}

LADDER = (1.0, 3.0, 7.0, 14.0, 30.0)
MIN_INTERVAL = 1.0
MAX_INTERVAL = 180.0
MIN_STABILITY = 0.5
MAX_STABILITY = 180.0

STABILITY_GROWTH = {"HARD": 0.25, "GOOD": 0.5, "EASY": 0.9}
FAIL_STABILITY_DECAY = 0.45          # 复习失败：稳定性打折
STABILITY_INTERVAL_CAP = 3.0         # 间隔最多不超过新稳定性的几倍

DEFAULT_EXPECTED_SECONDS = 60.0      # 期望作答时间（秒）
FAST_RATIO = 0.5                     # 快于期望时间的一半算"非常容易"
SLOW_RATIO = 1.5                     # 慢于期望时间 1.5 倍算"想了很久"

QUALITY_ALIASES = {
    "again": "AGAIN", "forgot": "AGAIN", "wrong": "AGAIN", "忘记": "AGAIN", "完全忘记": "AGAIN",
    "hard": "HARD", "difficult": "HARD", "难": "HARD", "有点难": "HARD", "想了很久": "HARD",
    "good": "GOOD", "normal": "GOOD", "正常": "GOOD", "正常想起来": "GOOD",
    "easy": "EASY", "简单": "EASY", "非常容易": "EASY",
}


def clamp_f(value, low, high):
    """浮点夹取；非法输入按 low 处理。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(low)
    if number != number:                 # NaN
        number = float(low)
    return max(float(low), min(float(high), number))


def round_half_up(value):
    """四舍五入（Python 内置 round 是银行家舍入，间隔计算需要可预期）。"""
    return float(math.floor(float(value) + 0.5))


def normalize_quality(value):
    """把各种写法统一成 AGAIN / HARD / GOOD / EASY；无法识别返回 ""。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.upper() in QUALITY_ORDER:
        return text.upper()
    return QUALITY_ALIASES.get(text.lower(), "")


def quality_of(correct, response_time=0, expected_time=0, confidence_feedback=""):
    """对错 + 答题时间 + 学生自评 → 复习反馈等级。

    错误 → AGAIN；正确但很慢 → HARD；正确且正常 → GOOD；正确且很快 → EASY。
    学生主动反馈优先于答题时间。
    """
    if not correct:
        return "AGAIN"

    feedback = str(confidence_feedback or "").strip().lower()
    if feedback in ("hard", "difficult", "难", "有点难"):
        return "HARD"
    if feedback in ("easy", "简单", "非常容易"):
        return "EASY"

    try:
        elapsed = float(response_time or 0)
        expected = float(expected_time or 0)
    except (TypeError, ValueError):
        return "GOOD"

    if elapsed > 0 and expected > 0:
        ratio = elapsed / expected
        if ratio <= FAST_RATIO:
            return "EASY"
        if ratio >= SLOW_RATIO:
            return "HARD"

    return "GOOD"


# ---------------- 各调整因子 ----------------

def mastery_factor(mastery_score):
    """>=85 ×1.15 / 70~84 ×1.0 / 60~69 ×0.85 / <60 ×0.7"""
    mastery = clamp_f(mastery_score or 0, 0, 100)
    if mastery >= 85:
        return 1.15
    if mastery >= 70:
        return 1.0
    if mastery >= 60:
        return 0.85
    return 0.7


def difficulty_factor(difficulty):
    """个人难度越高，间隔涨得越慢：× (1 − 0.3 × difficulty)。"""
    return round(1.0 - 0.3 * clamp_f(difficulty if difficulty is not None else 0.5, 0, 1), 3)


def stability_factor(stability):
    """稳定性越高允许越长：× (1 + 0.15 × min(1.5, stability/30))。"""
    value = clamp_f(stability or 1.0, MIN_STABILITY, MAX_STABILITY)
    return round(1.0 + 0.15 * min(1.5, value / 30.0), 3)


def time_factor(quality, response_time=0, expected_time=0):
    """答题速度微调（只在正确时生效）。"""
    if quality == "AGAIN":
        return 1.0
    try:
        elapsed = float(response_time or 0)
        expected = float(expected_time or 0)
    except (TypeError, ValueError):
        return 1.0
    if elapsed <= 0 or expected <= 0:
        return 1.0

    ratio = elapsed / expected
    if ratio <= FAST_RATIO:
        return 1.1
    if ratio >= SLOW_RATIO:
        return 0.9
    return 1.0


def feedback_factor(confidence_feedback=""):
    """学生自评：简单 ×1.1；有点难 ×0.9。"""
    text = str(confidence_feedback or "").strip().lower()
    if text in ("easy", "简单", "非常容易"):
        return 1.1
    if text in ("hard", "difficult", "难", "有点难"):
        return 0.9
    return 1.0


def confidence_factor(confidence):
    """题量置信度低（<0.4）时先短间隔确认：×0.8。"""
    return 0.8 if clamp_f(confidence if confidence is not None else 1.0, 0, 1) < 0.4 else 1.0


def maturity_interval_factor(maturity_level):
    """成熟度对稳定性增长的轻微加成：越成熟的记忆越"抗遗忘"。"""
    return {
        "NEW": 0.8, "LEARNING": 0.9, "SHORT_TERM": 1.0,
        "CONSOLIDATING": 1.05, "STABLE": 1.1, "LONG_TERM": 1.2,
    }.get(str(maturity_level or "").upper(), 1.0)


# ---------------- 主入口 ----------------

def calculate_next_interval(current_interval=1.0, mastery_score=70, stability=1.0,
                            difficulty=0.5, review_result="GOOD", response_time=0,
                            confidence_feedback="", successful_reviews=0,
                            expected_time=DEFAULT_EXPECTED_SECONDS, confidence=1.0,
                            maturity_level="LEARNING", now=None):
    """算出下一次该隔多久复习。

    输入：当前间隔、掌握度、稳定性、个人难度、复习结果、作答时间、学生自评
    输出：next_interval（天）、next_review_at、new_stability 以及可解释的 factors/reason
    """
    now = now or datetime.now()

    quality = normalize_quality(review_result) or quality_of(
        str(review_result).lower() not in ("false", "0"), response_time,
        expected_time, confidence_feedback)
    success = quality != "AGAIN"

    prev_interval = clamp_f(current_interval or MIN_INTERVAL, MIN_INTERVAL, MAX_INTERVAL)
    prev_stability = clamp_f(stability or 1.0, MIN_STABILITY, MAX_STABILITY)
    mastery = clamp_f(mastery_score or 0, 0, 100)
    personal_difficulty = clamp_f(difficulty if difficulty is not None else 0.5, 0, 1)
    successes = max(0, int(successful_reviews or 0))

    factors = {
        "quality_multiplier": QUALITY_MULTIPLIER[quality],
        "mastery_factor": mastery_factor(mastery),
        "difficulty_factor": difficulty_factor(personal_difficulty),
        "stability_factor": stability_factor(prev_stability),
        "time_factor": time_factor(quality, response_time, expected_time),
        "feedback_factor": feedback_factor(confidence_feedback),
        "confidence_factor": confidence_factor(confidence),
        "maturity_factor": maturity_interval_factor(maturity_level),
    }

    if not success:
        # 复习失败：直接压缩间隔 + 稳定性打折
        segment = "relapse"
        raw = prev_interval * QUALITY_MULTIPLIER["AGAIN"] * factors["mastery_factor"] \
            * factors["confidence_factor"]
        next_interval = round_half_up(clamp_f(raw, MIN_INTERVAL, MAX_INTERVAL))
        new_stability = clamp_f(prev_stability * FAIL_STABILITY_DECAY,
                                MIN_STABILITY, MAX_STABILITY)
        reason = (f"{QUALITY_TEXT[quality]}：间隔 {prev_interval:g} → {next_interval:g} 天，"
                  f"稳定性 {prev_stability:.1f} → {new_stability:.1f}")
    else:
        growth = (STABILITY_GROWTH[quality] * (1 - 0.5 * personal_difficulty)
                  * factors["mastery_factor"] * factors["maturity_factor"])
        new_stability = clamp_f(prev_stability * (1 + growth), MIN_STABILITY, MAX_STABILITY)

        if successes < len(LADDER):
            # 阶梯阶段：GOOD 走 1→3→7→14→30，EASY 更快、HARD 更慢
            #（successful_reviews 是"本次之前"的成功次数，所以目标档位要 +1）
            segment = "ladder"
            index = min(successes + 1, len(LADDER) - 1)
            target = LADDER[index] * LADDER_BONUS[quality]
            extended = (prev_interval * QUALITY_MULTIPLIER[quality]
                        * factors["mastery_factor"] * factors["stability_factor"])
            next_interval = round_half_up(
                clamp_f(max(target, extended), MIN_INTERVAL, MAX_INTERVAL))
            reason = (f"{QUALITY_TEXT[quality]}：阶梯推进到 {next_interval:g} 天"
                      f"（第 {successes + 1} 次复习成功），稳定性 {prev_stability:.1f} → {new_stability:.1f}")
        else:
            # 稳定性驱动阶段：全部因子生效
            segment = "stability"
            raw = (prev_interval * QUALITY_MULTIPLIER[quality] * factors["mastery_factor"]
                   * factors["difficulty_factor"] * factors["stability_factor"]
                   * factors["time_factor"] * factors["feedback_factor"]
                   * factors["confidence_factor"])
            next_interval = round_half_up(clamp_f(raw, MIN_INTERVAL, MAX_INTERVAL))
            cap = max(prev_interval, new_stability * STABILITY_INTERVAL_CAP)
            if next_interval > cap:
                next_interval = round_half_up(clamp_f(cap, MIN_INTERVAL, MAX_INTERVAL))
                reason_extra = "，受稳定性上限约束"
            else:
                reason_extra = ""
            reason = (f"{QUALITY_TEXT[quality]} + 稳定性驱动：间隔 {prev_interval:g} → "
                      f"{next_interval:g} 天{reason_extra}，稳定性 {prev_stability:.1f} → {new_stability:.1f}")

    next_interval = max(MIN_INTERVAL, next_interval)
    next_review_at = now + timedelta(days=next_interval)

    return {
        "quality": quality,
        "correct": success,
        "segment": segment,
        "previous_interval": prev_interval,
        "next_interval": next_interval,
        "next_review_at": next_review_at,
        "previous_stability": round(prev_stability, 3),
        "new_stability": round(new_stability, 3),
        "ladder_index": successes + 1 if success else successes,
        "factors": factors,
        "reason": reason,
    }


def initial_interval_days():
    """刚刚学会的新知识：1 天后第一次复习。"""
    return LADDER[0]


def ladder_preview(quality="GOOD", count=5):
    """给文档/测试用：纯阶梯情况下的前几个间隔。"""
    interval = MIN_INTERVAL
    preview = [interval]

    for index in range(max(0, int(count) - 1)):
        result = calculate_next_interval(
            current_interval=interval, mastery_score=75, stability=1.0 + index,
            difficulty=0.4, review_result=quality, successful_reviews=index)
        interval = result["next_interval"]
        preview.append(interval)

    return preview
