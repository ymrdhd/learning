# ==============================================================
# 能力契约｜遗忘风险引擎（纯函数）：按遗忘曲线算风险与等级
# 入口：ForgettingRiskEngine.calculate_forgetting_risk / calculate_forgetting_risk / risk_level / success_rate / DEFAULT_ENGINE
# 依赖：math datetime
# 不负责：队列排序 → scheduler.py
# 验证：python backend/verify_memory.py
# 被调用：review/engine.py、review_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 · 遗忘风险模型 `ForgettingRiskEngine.calculate_forgetting_risk()`。

回答一个问题：**这个知识点现在有多大概率已经忘了？**（0~1）

第一版用简单可解释的公式：

```text
overdue     = 距上次复习天数 / 原定间隔天数        （>1 表示已经逾期）
time_risk   = overdue / (overdue + 0.35)           （逾期越久越接近 1）
risk        = time_risk
              × 稳定性因子     1 / (1 + 0.08 × ln(1 + stability))
              × 掌握度因子     1.3 − 0.5 × mastery/100    （夹到 0.75~1.3）
              × 个人难度因子   1 + 0.3 × difficulty
              × 历史成功率因子 1.2 − 0.4 × success_rate
              × 上次表现因子   上次失败 ×1.2
              × 成熟度因子     LONG_TERM ×0.8 / STABLE ×0.9
```

分级：`>=0.75` 高风险（系统自动加入今日任务）、`>=0.45` 中风险、其余低风险。

例：某知识点上次复习在 10 天前、原定 7 天 → `overdue≈1.43`、
`time_risk≈0.78`，再按稳定性/掌握度打折后落在高风险区间，自动进今日复习队列。
"""

import math
from datetime import datetime

HIGH_RISK = 0.75
MEDIUM_RISK = 0.45
RISK_TEXT = {"高": "快要忘了", "中": "该复习了", "低": "还记得"}


def clamp01(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return max(0.0, min(1.0, number))


def _as_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
    return None


def risk_level(risk):
    """风险 → 高 / 中 / 低（给调试页与调度器用）。"""
    value = clamp01(risk)
    if value >= HIGH_RISK:
        return "高"
    if value >= MEDIUM_RISK:
        return "中"
    return "低"


def success_rate(successful_reviews, failed_reviews, default=0.8):
    """历史复习成功率；没有任何复习记录时给一个中性先验。"""
    success = max(0, int(successful_reviews or 0))
    failed = max(0, int(failed_reviews or 0))
    total = success + failed
    if total <= 0:
        return float(default)
    return success / float(total)


class ForgettingRiskEngine:
    """遗忘风险计算器（纯函数，不碰数据库，方便直接单测）。"""

    def calculate_forgetting_risk(self, state=None, now=None, elapsed_days=None,
                                  expected_interval=None, stability=None, difficulty=None,
                                  mastery_score=None, rate=None, last_result=None,
                                  maturity_level=None):
        """算出遗忘风险 0~1。

        state 可以直接传 `KnowledgeMemoryState` 行、dict，或者完全不传而用关键字参数；
        `elapsed_days` 不传时用 `state.last_reviewed_at / last_learned_at` 与 now 现算。
        """
        state = state or {}
        now = now or datetime.now()

        def pick(name, explicit):
            if explicit is not None:
                return explicit
            if isinstance(state, dict):
                return state.get(name)
            return getattr(state, name, None)

        mastery = float(pick("mastery_score", mastery_score) or 0)
        stability_value = float(pick("stability", stability) or 1.0)
        personal_difficulty = float(pick("difficulty", difficulty) or 0.5)
        expected = float(pick("current_interval_days", expected_interval) or 1.0)
        maturity = str(pick("maturity_level", maturity_level) or "").upper()
        last = pick("last_result", last_result)

        # 上次复习时间：优先 last_reviewed_at，其次 last_learned_at
        if elapsed_days is None:
            moment = _as_dt(pick("last_reviewed_at", None)) or _as_dt(pick("last_learned_at", None))
            elapsed = max(0.0, (now - moment).total_seconds() / 86400.0) if moment else 0.0
        else:
            elapsed = max(0.0, float(elapsed_days))

        expected = max(1.0, expected)
        overdue = elapsed / expected
        time_risk = overdue / (overdue + 0.35)

        if rate is None:
            rate = success_rate(pick("successful_reviews", None), pick("failed_reviews", None))

        factors = {
            "time": round(time_risk, 4),
            "stability": round(1.0 / (1.0 + 0.08 * math.log(1.0 + max(0.0, stability_value))), 4),
            "mastery": round(max(0.75, min(1.3, 1.3 - 0.5 * mastery / 100.0)), 4),
            "difficulty": round(1.0 + 0.3 * max(0.0, min(1.0, personal_difficulty)), 4),
            "history": round(1.2 - 0.4 * clamp01(rate), 4),
            "last_result": 1.2 if last is False else 1.0,
            "maturity": {"LONG_TERM": 0.8, "STABLE": 0.9}.get(maturity, 1.0),
        }

        risk = 1.0
        for value in factors.values():
            risk *= value
        risk = clamp01(risk)

        level = risk_level(risk)
        reason = (f"距上次复习 {elapsed:.1f} 天 / 原定 {expected:g} 天"
                  f"（逾期 {max(0.0, elapsed - expected):.1f} 天），"
                  f"稳定性 {stability_value:.1f}，风险 {risk:.2f}（{level}）")

        return {
            "risk": round(risk, 4),
            "level": level,
            "level_text": RISK_TEXT.get(level, ""),
            "elapsed_days": round(elapsed, 2),
            "expected_interval": round(expected, 2),
            "overdue_days": round(max(0.0, elapsed - expected), 2),
            "overdue_ratio": round(overdue, 3),
            "stability": round(stability_value, 3),
            "success_rate": round(clamp01(rate), 3),
            "factors": factors,
            "reason": reason,
        }


DEFAULT_ENGINE = ForgettingRiskEngine()


def calculate_forgetting_risk(state=None, **kwargs):
    """模块级快捷入口。"""
    return DEFAULT_ENGINE.calculate_forgetting_risk(state, **kwargs)
