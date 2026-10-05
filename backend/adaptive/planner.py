# ==============================================================
# 能力契约｜每日学习计划（时间/题量分配 + 幂等落库），复用复习配比与新学/补强块
# 入口：DailyLearningPlanner.build / ensure / summary / allocate / date_text / target_count_of / goal_text / DEFAULT_PLANNER
# 依赖：knowledge_tree review.mix review.scheduler datetime
# 不负责：推荐决策 → adaptive/engine.recommend
# 验证：python backend/verify_adaptive.py
# 被调用：adaptive/engine.py、adaptive_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎 · 每日学习计划 DailyLearningPlanner。

输入：各科学生画像（能力阶段 + 薄弱知识点）+ 今天能用的学习时间
输出：今日计划（今天学哪几科、每科学什么、多少分钟、做多少题）

默认分配（数学优先，符合家庭辅导的日常节奏）：

```
数学 15 分钟 → 薄弱知识点 10 题
语文 10 分钟 → 阅读/基础 10 题
英语 10 分钟 → 单词复习 20 个
```

三条规则：

1. **时间先按科目固定分配**，再按总时长等比缩放（下限 5 分钟）。
2. **已经熟练（≥85 分）的科目让出 5 分钟**，转给最薄弱的科目。
3. **同一学生同一天幂等**：已生成的计划直接复用，完成进度不会因为刷新页面丢。
"""

from datetime import datetime

import knowledge_tree
from review import mix as review_mix
from review import scheduler as review_scheduler

DEFAULT_MINUTES = {"数学": 15, "语文": 10, "英语": 10}
DEFAULT_TOTAL_MINUTES = sum(DEFAULT_MINUTES.values())      # 35 分钟

# 平均每题耗时（秒）：数学要动笔、英语单词快
SECONDS_PER_QUESTION = {"数学": 90, "语文": 60, "英语": 30}

MIN_MINUTES = 5
MAX_MINUTES = 30
MASTERED_GIVE_BACK = 5        # 已经熟练的科目让出几分钟
MASTERED_LINE = 85
STATUS_PENDING = "pending"
STATUS_DOING = "doing"
STATUS_DONE = "done"
STATUS_EXPIRED = "expired"

STATUS_TEXT = {"pending": "待完成", "doing": "进行中", "done": "已完成", "expired": "已过期"}

# V2.4 计划条目类型（前端用来区分"新学 / 补强 / 复习"）
ITEM_TYPE_TEXT = {"new_learning": "新学", "weakness": "补强", "review": "复习"}


def date_text(plan_date=None):
    """计划日期统一用 YYYY-MM-DD 字符串，SQLite 里直接可比大小。"""
    if isinstance(plan_date, datetime):
        return plan_date.strftime("%Y-%m-%d")
    if plan_date:
        return str(plan_date)[:10]
    return datetime.now().strftime("%Y-%m-%d")


def target_mastery_of(mastery, step=10, cap=90):
    """这次练习想达到的掌握度：比现在高 10 分，最多 90。"""
    mastery = int(mastery or 0)
    if mastery <= 0:
        return 70
    return min(cap, mastery + step)


def target_count_of(subject, minutes):
    """分钟数 → 题量（英语按"个单词"算）。"""
    seconds = SECONDS_PER_QUESTION.get(subject, 60)
    count = int(round(max(0, int(minutes)) * 60 / float(seconds)))
    return max(3, count)


def goal_text(subject, domain, count, target_mastery):
    """给小朋友看的目标文案。"""
    if subject == "英语" and domain in ("词汇", "字母与语音"):
        return f"复习 {count} 个单词"
    if subject == "语文" and domain == "阅读理解":
        return f"读一篇短文，完成 {count} 题"
    if subject == "语文" and domain == "古诗文":
        return f"背诵理解 {count} 题"
    if subject == "数学" and domain == "应用题":
        return f"应用题强化，完成 {count} 题"
    return f"完成 {count} 题，把掌握度提到 {target_mastery} 以上"


class DailyLearningPlanner:
    """每日计划生成器（build 是纯函数，ensure 负责落库）。"""

    def allocate(self, profiles, total_minutes=None):
        """科目 → 分钟数。"""
        profiles = [item for item in (profiles or ()) if item]
        subjects = [str(item.get("subject")) for item in profiles] or ["数学"]
        minutes = {name: DEFAULT_MINUTES.get(name, 10) for name in subjects}

        target_total = int(total_minutes) if total_minutes else DEFAULT_TOTAL_MINUTES
        base_total = sum(minutes.values())

        if base_total > 0 and target_total != base_total:
            ratio = target_total / float(base_total)
            # V2.6：明确给了总时长（自适应目标可能小于默认 35 分钟）时允许单科低于
            # MIN_MINUTES —— 否则三科各抬到 5 分钟，总量就永远回不到孩子真实目标
            floor = MIN_MINUTES if not total_minutes else 1
            for name in minutes:
                minutes[name] = max(floor,
                                    min(MAX_MINUTES, int(round(minutes[name] * ratio))))

        # 已经熟练的科目让出时间，补给最薄弱的科目
        averages = {}
        for item in profiles:
            summary = item.get("summary") or {}
            if int(summary.get("practiced") or 0) > 0:
                averages[str(item.get("subject"))] = int(summary.get("average_mastery") or 0)

        if averages:
            weakest = min(averages, key=lambda name: (averages[name], name))
            for name, average in averages.items():
                if name == weakest or average < MASTERED_LINE:
                    continue
                give = min(MASTERED_GIVE_BACK, minutes.get(name, MIN_MINUTES) - MIN_MINUTES)
                if give > 0:
                    minutes[name] -= give
                    minutes[weakest] = min(MAX_MINUTES, minutes.get(weakest, MIN_MINUTES) + give)

        return minutes

    def build(self, profiles, total_minutes=None, plan_date=None, review_items=None,
              relearn_items=None):
        """生成今日计划条目（纯函数，不落库）。

        V2.4 起每科按 `calculate_daily_mix()` 拆成三类：

        - `new_learning` 当前学习内容（50%）
        - `weakness`     薄弱知识补强（30%）
        - `review`       间隔复习（20%，来自 ReviewScheduler 的今日队列）

        某一类没有内容时，额度会自动让给其它两类（例如今天没有到期复习任务，
        复习比例降到 5%）。
        """
        profiles = [item for item in (profiles or ()) if item]
        minutes = self.allocate(profiles, total_minutes=total_minutes)
        day = date_text(plan_date)
        review_items = [item for item in (review_items or ()) if item]
        relearn_items = [item for item in (relearn_items or ()) if item]
        plans = []
        order = 0

        for profile in profiles:
            subject = str(profile.get("subject"))
            decision = profile.get("decision") or {}
            decision_knowledge = decision.get("knowledge") or ""
            duration = int(minutes.get(subject, MIN_MINUTES))
            total_count = target_count_of(subject, duration)

            subject_reviews = [item for item in review_items
                               if str(item.get("subject")) == subject]
            subject_relearn = [item for item in relearn_items
                               if str(item.get("subject")) == subject]
            weak_candidates = self._weak_candidates(profile, decision_knowledge)

            mix_result = profile.get("mix") or review_mix.calculate_daily_mix(
                review_due=len(subject_reviews),
                high_risk=sum(1 for item in subject_reviews
                              if float(item.get("forgetting_risk") or 0)
                              >= review_scheduler.HIGH_RISK),
                average_risk=(sum(float(item.get("forgetting_risk") or 0)
                                  for item in subject_reviews) / len(subject_reviews)
                              if subject_reviews else 0.0),
                weakness_count=len(weak_candidates),
                relearn_count=len(subject_relearn),
            )
            counts = review_mix.split_counts(total_count, mix_result)

            blocks = []
            blocks.extend(self._review_blocks(subject, subject_reviews, counts["review"]))
            blocks.extend(self._weakness_blocks(subject, weak_candidates,
                                                counts["weakness"]))
            blocks.extend(self._new_blocks(subject, decision, decision_knowledge,
                                           counts["new_learning"]))

            # 某一类今天没有内容（例如没有到期复习任务）时，把没用完的额度补给新学，
            # 避免"计划 10 题只排了 9 题"
            gap = int(total_count) - sum(int(block["target_count"]) for block in blocks)
            if gap > 0 and blocks:
                target_block = next((block for block in blocks
                                     if block["item_type"] == "new_learning"), blocks[0])
                target_block["target_count"] = int(target_block["target_count"]) + gap

            for block in blocks:
                block["goal"] = self._goal_for(subject, block)
                order += 1
                count = int(block["target_count"])
                plans.append({
                    "date": day,
                    "subject": subject,
                    "knowledge_id": block["knowledge_id"],
                    "item_type": block["item_type"],
                    "action": block["action"],
                    "difficulty": int(block["difficulty"]),
                    "duration_minutes": max(1, int(round(
                        duration * count / float(max(1, total_count))))),
                    "target_count": count,
                    "goal": block["goal"],
                    "reason": block["reason"],
                    "target_mastery": int(block["target_mastery"]),
                    "priority": order,
                })

        plans.sort(key=lambda item: (item["priority"], item["subject"]))
        for index, item in enumerate(plans):
            item["priority"] = index + 1
        return plans

    # ---------- 三类内容 ----------

    @staticmethod
    def _goal_for(subject, block):
        """按条目类型生成给小朋友看的目标文案。"""
        count = int(block["target_count"])
        knowledge = str(block["knowledge_id"])
        item_type = block["item_type"]

        if item_type == "review":
            return f"复习 {knowledge}，做 {count} 题看看还记得吗"
        if item_type == "weakness":
            return f"补强 {knowledge}，做 {count} 题"
        return goal_text(subject, knowledge_tree.domain_of(subject, knowledge), count,
                         int(block["target_mastery"]))

    @staticmethod
    def _weak_candidates(profile, exclude_knowledge="", limit=2):
        """薄弱知识补强的候选（掌握度 <70，排除已经安排为新学的那一个）。"""
        ranked = (profile.get("decision") or {}).get("ranked") or []
        picked = []
        for entry in ranked:
            if entry.get("knowledge") == exclude_knowledge:
                continue
            if int(entry.get("mastery") or 0) >= 70:
                continue
            if int(entry.get("total") or 0) <= 0:
                continue
            picked.append(entry)
            if len(picked) >= limit:
                break
        return picked

    @staticmethod
    def _review_blocks(subject, review_items, quota):
        """复习块：每个知识点 1~3 题，总量受复习额度限制。"""
        order = {name: index for index, name in enumerate(review_scheduler.PRIORITY_ORDER)}
        items = sorted(review_items, key=lambda item: (
            order.get(str(item.get("priority")), 9),
            -float(item.get("forgetting_risk") or 0),
            str(item.get("knowledge_id") or "")))

        blocks = []
        remaining = max(0, int(quota))
        for item in items:
            if remaining <= 0:
                break
            knowledge = str(item.get("knowledge_id") or "")
            if not knowledge:
                continue
            want = max(1, min(int(item.get("target_count") or 1),
                              remaining, review_scheduler.MAX_TARGET))
            remaining -= want
            mastery = int(item.get("mastery_score") or 0)
            blocks.append({
                "item_type": "review",
                "action": "review",
                "knowledge_id": knowledge,
                "difficulty": int(item.get("difficulty")
                                  or knowledge_tree.difficulty_of(subject, knowledge)),
                "target_count": want,
                "reason": item.get("reason") or f"{item.get('priority_text') or '间隔复习'}",
                "target_mastery": target_mastery_of(mastery),
            })
        return blocks

    @staticmethod
    def _weakness_blocks(subject, weak_candidates, quota):
        """补强块：把额度分给最薄弱的 1~2 个知识点。"""
        blocks = []
        remaining = max(0, int(quota))
        if not weak_candidates or remaining <= 0:
            return blocks

        share = max(1, remaining // len(weak_candidates))
        for entry in weak_candidates:
            if remaining <= 0:
                break
            want = max(1, min(share, remaining))
            remaining -= want
            knowledge = str(entry.get("knowledge") or "")
            mastery = int(entry.get("mastery") or 0)
            blocks.append({
                "item_type": "weakness",
                "action": "practice",
                "knowledge_id": knowledge,
                "difficulty": int(entry.get("difficulty") or 50),
                "target_count": want,
                "reason": entry.get("blocked_by") and (
                    f"{knowledge}依赖{entry['blocked_by']}，先补基础") or f"掌握度{mastery}，需要强化",
                "target_mastery": target_mastery_of(mastery),
            })
        return blocks

    @staticmethod
    def _new_blocks(subject, decision, decision_knowledge, quota):
        """新学块：当前能力阶段该学的知识点。"""
        if not decision_knowledge or int(quota or 0) <= 0:
            return []

        mastery = int((decision.get("evidence") or {}).get("mastery") or 0)
        target_mastery = target_mastery_of(mastery)
        count = max(1, int(quota))

        return [{
            "item_type": "new_learning",
            "action": decision.get("action") or "practice",
            "knowledge_id": decision_knowledge,
            "difficulty": int(decision.get("difficulty") or 50),
            "target_count": count,
            "reason": decision.get("reason") or "",
            "target_mastery": target_mastery,
        }]

    # ---------- 落库 ----------

    def ensure(self, db, student_id, profiles=None, total_minutes=None, plan_date=None,
               review_items=None, relearn_items=None):
        """确认今天的计划已经生成（幂等），返回计划总览。"""
        from models import LearningPlan

        day = date_text(plan_date)
        profiles = [item for item in (profiles or ()) if item]
        items = self.build(profiles, total_minutes=total_minutes, plan_date=day,
                           review_items=review_items, relearn_items=relearn_items)

        rows = db.query(LearningPlan).filter(
            LearningPlan.student_id == student_id,
            LearningPlan.date == day,
        ).all()
        existing = {(row.subject, row.knowledge_id): row for row in rows}

        for item in items:
            key = (item["subject"], item["knowledge_id"])
            row = existing.get(key)

            if row is None:
                row = LearningPlan(
                    student_id=student_id,
                    date=day,
                    subject=item["subject"],
                    knowledge_id=item["knowledge_id"],
                    target_count=item["target_count"],
                    completed_count=0,
                    status=STATUS_PENDING,
                    duration_minutes=item["duration_minutes"],
                    action=item["action"],
                    item_type=item.get("item_type") or "new_learning",
                    difficulty=item["difficulty"],
                    goal=item["goal"],
                    reason=item["reason"],
                    target_mastery=item["target_mastery"],
                    priority=item["priority"],
                    created_time=datetime.now(),
                )
                db.add(row)
                db.flush()
                existing[key] = row
                continue

            # 已完成/进行中的计划不覆盖，保证进度不丢
            if (row.status or STATUS_PENDING) in (STATUS_DONE, STATUS_DOING):
                continue

            row.target_count = item["target_count"]
            row.duration_minutes = item["duration_minutes"]
            row.action = item["action"]
            row.item_type = item.get("item_type") or "new_learning"
            row.difficulty = item["difficulty"]
            row.goal = item["goal"]
            row.reason = item["reason"]
            row.target_mastery = item["target_mastery"]
            row.priority = item["priority"]
            row.updated_time = datetime.now()

        # 今天已经不在计划里的空计划：标记过期，不再出现在今日任务里
        keep = {(item["subject"], item["knowledge_id"]) for item in items}
        for key, row in existing.items():
            if key in keep:
                continue
            if int(row.completed_count or 0) == 0 and (row.status or "") == STATUS_PENDING:
                row.status = STATUS_EXPIRED

        db.commit()
        return self.summary(db, student_id, day)

    def summary(self, db, student_id, plan_date=None):
        """今日计划总览（含进度）。"""
        from models import LearningPlan

        day = date_text(plan_date)
        rows = db.query(LearningPlan).filter(
            LearningPlan.student_id == student_id,
            LearningPlan.date == day,
            LearningPlan.status != STATUS_EXPIRED,
        ).order_by(LearningPlan.priority.asc(), LearningPlan.id.asc()).all()

        items = []
        for row in rows:
            target = int(row.target_count or 0)
            done = int(row.completed_count or 0)
            items.append({
                "id": row.id,
                "date": row.date,
                "subject": row.subject,
                "knowledge_id": row.knowledge_id,
                "action": row.action or "practice",
                "item_type": row.item_type or "new_learning",
                "item_type_text": ITEM_TYPE_TEXT.get(row.item_type or "new_learning", "新学"),
                "difficulty": int(row.difficulty or 50),
                "duration_minutes": int(row.duration_minutes or 0),
                "target_count": target,
                "completed_count": done,
                "remain_count": max(0, target - done),
                "status": row.status or STATUS_PENDING,
                "status_text": STATUS_TEXT.get(row.status or STATUS_PENDING, "待完成"),
                "goal": row.goal or "",
                "reason": row.reason or "",
                "target_mastery": int(row.target_mastery or 0),
                "progress": int(round(100 * done / target)) if target else 0,
            })

        total_target = sum(item["target_count"] for item in items)
        total_done = sum(item["completed_count"] for item in items)
        by_type = {}
        for item in items:
            key = item["item_type"]
            bucket = by_type.setdefault(key, {"item_type": key,
                                              "item_type_text": ITEM_TYPE_TEXT.get(key, "新学"),
                                              "target_count": 0, "completed_count": 0,
                                              "knowledge_count": 0})
            bucket["target_count"] += item["target_count"]
            bucket["completed_count"] += item["completed_count"]
            bucket["knowledge_count"] += 1

        return {
            "student_id": student_id,
            "date": day,
            "minutes": sum(item["duration_minutes"] for item in items),
            "target_count": total_target,
            "completed_count": total_done,
            "progress": int(round(100 * total_done / total_target)) if total_target else 0,
            "done": bool(items) and total_done >= total_target,
            "by_type": list(by_type.values()),
            "items": items,
        }


DEFAULT_PLANNER = DailyLearningPlanner()
