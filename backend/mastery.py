# ==============================================================
# 能力契约｜MasteryEngine 掌握度模型（加权正确率 + 题量收缩 + 连错惩罚 + 复习加成 + 时间衰减）
# 入口：MasteryEngine（calculate_mastery/level_of/confidence_of/next_review_time）/ calculate / aggregate / DEFAULT_ENGINE
# 依赖：datetime（纯函数）
# 不负责：掌握度落库 → knowledge_routes.update_mastery；能力分 → ability.py / diagnostic.py
# 验证：python backend/verify_knowledge.py
# 被调用：main.py、knowledge_routes.py、wrong_book.py、adaptive/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 知识掌握模型 MasteryEngine。

回答一个问题：**这个学生在这个知识点上到底掌握到什么程度？**

输入：该知识点的历史答题记录（对错、难度、错误类型、时间）
输出：`mastery_score`（0~100）、`confidence`（0~1）、掌握等级、下次复习时间

算法由四部分组成：

1. **加权正确率**：难题答对更值钱（权重 = 1 + 难度/100）。
2. **题量收缩**：题做得少就不能给高分，分数向 50 分收缩：
   `score = 50 + (正确率×100 − 50) × n/(n+8)`
   → 5 题全对 ≈ 69 分（初步掌握），42/50 ≈ 79 分（接近熟练）。
3. **连续错误惩罚**：最近连着错 k 道扣 `4k` 分，最多扣 20 分（连续答错直接掉档）。
4. **复习稳定加成 / 时间衰减**：跨 2 个以上不同日期练习算"多次复习"最多 +6 分；
   超过 14 天没练，每多一周扣 1 分（最多扣 8 分），提醒孩子该复习了。

置信度按题量算：`n/(n+7.5)` → 5 题 0.40，50 题 0.87（题越多越可信）。
"""

from datetime import datetime, timedelta

# 等级分档（从高到低）
LEVEL_BANDS = ((85, "熟练"), (70, "初步掌握"), (50, "巩固中"), (1, "薄弱"), (0, "未练习"))

# 掌握度 → 下次复习间隔
REVIEW_PLAN = ((85, timedelta(days=7)), (70, timedelta(days=3)),
               (50, timedelta(days=1)), (0, timedelta(hours=4)))


class MasteryEngine:
    """知识点掌握度计算器（纯函数，不碰数据库，方便直接单测）。"""

    SHRINK_K = 7.5             # 题量收缩系数：5 题全对正好 70 分（初步掌握）
    CONFIDENCE_K = 7.5         # 置信度系数：5 题 → 0.40，50 题 → 0.87
    CONFIDENCE_MAX = 0.98
    STREAK_PENALTY = 4.0       # 每连续错一道扣几分
    STREAK_PENALTY_MAX = 20.0
    REVIEW_BONUS = 2.0         # 每多一个复习日加分
    REVIEW_BONUS_MAX = 6.0
    DECAY_AFTER_DAYS = 14      # 超过这么多天没练开始衰减
    DECAY_PER_WEEK = 1.0
    DECAY_MAX = 8.0

    # ---------- 基础指标 ----------

    @staticmethod
    def level_of(score):
        try:
            score = float(score)
        except (TypeError, ValueError):
            return "未练习"

        for floor, name in LEVEL_BANDS:
            if score >= floor:
                return name
        return "未练习"

    @staticmethod
    def confidence_of(total):
        """题量 → 置信度：5 题 0.40、20 题 0.73、50 题 0.87。"""
        total = max(0, int(total or 0))
        if total <= 0:
            return 0.0

        value = total / (total + MasteryEngine.CONFIDENCE_K)
        return round(min(MasteryEngine.CONFIDENCE_MAX, value), 2)

    @staticmethod
    def weighted_rate(records):
        """加权正确率：难题答对更值钱。"""
        weight_sum = 0.0
        hit_sum = 0.0

        for record in records or ():
            difficulty = float(record.get("difficulty") or 50)
            weight = 1.0 + max(0.0, min(100.0, difficulty)) / 100.0
            weight_sum += weight
            if record.get("correct"):
                hit_sum += weight

        return hit_sum / weight_sum if weight_sum else 0.0

    @staticmethod
    def consecutive_wrong(ordered):
        """从最新一条往前数，连续错了几道。"""
        count = 0
        for record in reversed(ordered):
            if record.get("correct"):
                break
            count += 1
        return count

    @staticmethod
    def review_days(ordered):
        """练习覆盖了多少个不同日期（>=2 表示有回访复习）。"""
        days = set()
        for record in ordered:
            moment = record.get("time")
            if isinstance(moment, datetime):
                days.add(moment.date())
        return len(days)

    # ---------- 主入口 ----------

    def calculate_mastery(self, records, now=None):
        """历史答题记录 → 掌握度画像。

        records: [{"correct": True, "difficulty": 55,
                   "error_type": "计算错误" | None, "time": datetime | None}, ...]
        """
        records = [item for item in (records or []) if item]
        total = len(records)
        now = now or datetime.now()

        if total == 0:
            return {
                "mastery_score": 0,
                "confidence": 0.0,
                "level": "未练习",
                "total_questions": 0,
                "correct_questions": 0,
                "wrong_questions": 0,
                "weighted_rate": 0.0,
                "consecutive_wrong": 0,
                "review_days": 0,
                "error_types": {},
                "last_practice_time": None,
                "next_review_time": None,
            }

        ordered = sorted(records, key=lambda item: item.get("time") or datetime.min)
        correct_count = sum(1 for item in ordered if item.get("correct"))
        rate = self.weighted_rate(ordered)

        # 1) 正确率 + 题量收缩
        shrink = total / (total + self.SHRINK_K)
        score = 50.0 + (rate * 100.0 - 50.0) * shrink

        # 2) 连续错误惩罚
        streak = self.consecutive_wrong(ordered)
        if streak:
            score -= min(self.STREAK_PENALTY_MAX, streak * self.STREAK_PENALTY)

        # 3) 多次复习加成
        days = self.review_days(ordered)
        if days >= 2:
            score += min(self.REVIEW_BONUS_MAX, self.REVIEW_BONUS * (days - 1))

        # 4) 长时间不练的衰减
        moments = [item["time"] for item in ordered if isinstance(item.get("time"), datetime)]
        last_time = max(moments) if moments else None
        if last_time is not None:
            idle_days = (now - last_time).days
            if idle_days > self.DECAY_AFTER_DAYS:
                weeks = (idle_days - self.DECAY_AFTER_DAYS) // 7 + 1
                score -= min(self.DECAY_MAX, self.DECAY_PER_WEEK * weeks)

        score = int(round(max(0.0, min(100.0, score))))

        error_types = {}
        for item in ordered:
            kind = item.get("error_type")
            if kind:
                error_types[kind] = error_types.get(kind, 0) + 1

        return {
            "mastery_score": score,
            "confidence": self.confidence_of(total),
            "level": self.level_of(score),
            "total_questions": total,
            "correct_questions": correct_count,
            "wrong_questions": total - correct_count,
            "weighted_rate": round(rate, 3),
            "consecutive_wrong": streak,
            "review_days": days,
            "error_types": error_types,
            "last_practice_time": last_time,
            "next_review_time": self.next_review_time(score, now),
        }

    # ---------- 复习计划 ----------

    @staticmethod
    def next_review_time(score, now=None):
        """掌握度 → 下次该复习的时间：越熟间隔越长。"""
        now = now or datetime.now()
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0

        for floor, gap in REVIEW_PLAN:
            if score >= floor:
                return now + gap
        return now + timedelta(hours=4)


DEFAULT_ENGINE = MasteryEngine()


def calculate(records, now=None):
    """模块级快捷入口。"""
    return DEFAULT_ENGINE.calculate_mastery(records, now=now)


def aggregate(items):
    """把若干知识点的掌握度按题量加权平均，用于领域/整体汇总。

    items: [{"mastery_score": 82, "total_questions": 12}, ...]
    """
    weight_sum = 0
    score_sum = 0.0

    for item in items or ():
        weight = max(1, int(item.get("total_questions") or 0))
        weight_sum += weight
        score_sum += float(item.get("mastery_score") or 0) * weight

    if not weight_sum:
        return 0

    return int(round(score_sum / weight_sum))
