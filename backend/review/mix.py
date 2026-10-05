# ==============================================================
# 能力契约｜每日新学 / 薄弱补强 / 间隔复习的配比（纯函数）
# 入口：calculate_daily_mix / split_counts
# 依赖：无
# 不负责：队列排序与上限 → scheduler.py
# 验证：python backend/verify_memory.py
# 被调用：review/engine.py、review_routes.py、adaptive/planner.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 · 每日学习内容配比 `calculate_daily_mix()`。

V2.3 的每日计划升级成三类内容按比例分配：

| 内容 | 默认比例 | 说明 |
| --- | --- | --- |
| `new_learning` | 50% | 当前进度的新知识点（能力阶段对应） |
| `weakness` | 30% | 薄弱知识补强（掌握度 <70） |
| `review` | 20% | 间隔复习（ReviewScheduler 排出来的到期任务） |

比例由 `AdaptiveLearningEngine` 动态调整：

- 队列里 **没有**复习任务 → `review` 降到 5%（省下的给新学与补强）
- 复习任务 ≤2 个 → `review` 10%
- 高风险任务 ≥3 个，或平均风险 ≥0.6 → `review` 提到 **40%**（先保住旧知识）
- 需要重学（`RELEARN`）的知识点多 → 从复习里切一半给薄弱补强（重新学）
"""

DEFAULT_MIX = {"new_learning": 0.50, "weakness": 0.30, "review": 0.20}
MIN_REVIEW = 0.05
MAX_REVIEW = 0.40
HIGH_RISK_COUNT = 3
HIGH_RISK_AVERAGE = 0.6


def _normalize(mix):
    """把三项比例归一化到合计 1.0（保留两位小数，最后一项兜底补齐）。"""
    total = sum(max(0.0, float(value)) for value in mix.values())
    if total <= 0:
        return dict(DEFAULT_MIX)

    normalized = {key: round(max(0.0, float(value)) / total, 2) for key, value in mix.items()}
    diff = round(1.0 - sum(normalized.values()), 2)
    if diff:
        key = max(normalized, key=lambda name: normalized[name])
        normalized[key] = round(normalized[key] + diff, 2)
    return normalized


def calculate_daily_mix(review_due=0, high_risk=0, average_risk=0.0, weakness_count=0,
                        relearn_count=0, has_new_learning=True):
    """算出今天三类内容的比例。

    返回 `{new_learning_ratio, weakness_ratio, review_ratio, reason, counts}`。
    """
    review_due = max(0, int(review_due or 0))
    high_risk = max(0, int(high_risk or 0))
    weakness_count = max(0, int(weakness_count or 0))
    relearn_count = max(0, int(relearn_count or 0))
    average_risk = max(0.0, min(1.0, float(average_risk or 0.0)))

    reasons = []

    if review_due == 0:
        review_ratio = MIN_REVIEW
        reasons.append("今天没有到期复习任务，复习比例降到 5%")
    elif high_risk >= HIGH_RISK_COUNT or average_risk >= HIGH_RISK_AVERAGE:
        review_ratio = MAX_REVIEW
        reasons.append(f"有 {high_risk} 个高风险知识点（平均风险 {average_risk:.0%}），"
                       f"复习提到 {int(MAX_REVIEW * 100)}%")
    elif review_due <= 2:
        review_ratio = 0.10
        reasons.append(f"只有 {review_due} 个待复习知识点，复习占 10%")
    else:
        review_ratio = DEFAULT_MIX["review"]
        reasons.append(f"{review_due} 个待复习知识点，按默认 20% 安排")

    weakness_ratio = DEFAULT_MIX["weakness"]
    new_ratio = DEFAULT_MIX["new_learning"]

    # 需要重学的知识点：把复习的一半额度换成"薄弱补强"（重新学）
    if relearn_count >= 1:
        moved = round(review_ratio * 0.5, 2)
        review_ratio = round(review_ratio - moved, 2)
        weakness_ratio = round(weakness_ratio + moved, 2)
        reasons.append(f"{relearn_count} 个知识点需要重新学，从复习里匀出 {int(moved * 100)}% 给补强")

    if not has_new_learning:
        # 没有能力画像（还没诊断）时不做"新学"，全部给补强与复习
        weakness_ratio = round(weakness_ratio + new_ratio, 2)
        new_ratio = 0.0
        reasons.append("还没有能力画像，先以补强和复习为主")

    if weakness_count == 0 and new_ratio > 0:
        # 没有薄弱知识点：把补强的额度让给新学
        new_ratio = round(new_ratio + weakness_ratio, 2)
        weakness_ratio = 0.0
        reasons.append("暂时没有薄弱知识点，额度让给新学")

    mix = _normalize({
        "new_learning": new_ratio,
        "weakness": weakness_ratio,
        "review": review_ratio,
    })

    return {
        "new_learning_ratio": mix["new_learning"],
        "weakness_ratio": mix["weakness"],
        "review_ratio": mix["review"],
        "reason": "；".join(reasons),
        "counts": {
            "review_due": review_due,
            "high_risk": high_risk,
            "average_risk": round(average_risk, 3),
            "weakness_count": weakness_count,
            "relearn_count": relearn_count,
        },
    }


def split_counts(total, mix):
    """把总题量按比例拆成三类题量（至少保证 review 为 0 时不给题）。"""
    total = max(0, int(total or 0))
    plan = {}
    assigned = 0
    for key in ("new_learning", "weakness", "review"):
        ratio = float(mix.get(f"{key}_ratio", 0.0) or 0.0)
        count = int(round(total * ratio))
        plan[key] = count
        assigned += count

    # 四舍五入的零头补给占比最大的一类
    diff = total - assigned
    if diff:
        key = max(plan, key=lambda name: plan[name])
        plan[key] = max(0, plan[key] + diff)
    return plan


DEFAULT_MIX_RESULT = calculate_daily_mix()
