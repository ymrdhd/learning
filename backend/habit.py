# ==============================================================
# 能力契约｜每日学习习惯：50/30/20 三类任务生成（幂等）/ 完成 / 画像（连续天数·徽章·等级）
# 入口：HabitEngine / DEFAULT_ENGINE / MIX / MIX_TEXT / split_by_mix / next_target_minutes / plan / start_today / use_rest_protection
# 依赖：datetime json、models、knowledge_tree、adaptive.planner
# 不负责：学校计划生成 → adaptive/planner.py；错题康复 → recovery.py；HTTP 路由 → task_routes.py
# 验证：python backend/verify_habit.py（自测脚本用 DATABASE_URL 指向临时库）
# 被调用：main.py、task_routes.py、habit_routes.py、daily_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 每日学习习惯系统 · HabitEngine。

三类任务按 MIX = 50% 新知识 / 30% 薄弱训练 / 20% 复习恢复 分配（算术见 HABIT_DESIGN.md）。
数据来源：当天 learning_plan（有则用其知识点，source="plan"），否则降级用
student_knowledge_mastery 的薄弱知识点（掌握度升序，source="habit"）。全程不依赖 DeepSeek。
"""

import json
from datetime import datetime, timedelta

import knowledge_tree
from models import (DailyLearningTask, LearningHabitProfile, LearningPlan,
                    StudentKnowledgeMastery)
from adaptive import planner

MIX = {"new_learning": 0.5, "weakness": 0.3, "review": 0.2}
MIX_TEXT = {"new_learning": "新知识", "weakness": "薄弱训练", "review": "复习恢复"}
TYPE_ORDER = ("new_learning", "weakness", "review")
SUBJECTS = ("数学", "语文", "英语")
STATUS_TEXT = {"pending": "待完成", "doing": "进行中", "done": "已完成"}
BADGE_CATALOG = (
    ("first_day", "第一次学习", "🐣"),
    ("streak_3", "坚持三天", "🔥"),
    ("streak_7", "坚持一周", "⭐"),
    ("streak_30", "坚持一月", "👑"),
    ("rate_80", "高效完成", "🎯"),
    ("minutes_100", "学习百分钟", "⏰"),
)
BADGE_KEYS = tuple(key for key, _, _ in BADGE_CATALOG)
LEVEL_TEXT = {1: "学习小鲸鱼", 2: "坚持小水手", 3: "每日小达人", 4: "一周小能手",
              5: "习惯小明星", 6: "学习小船长", 7: "坚持小超人", 8: "自律小达人",
              9: "习惯大师", 10: "终身学习者"}


# ---------- 目标时长自适应（V2.6）----------
TARGET_MIN = 10        # 首次学习目标（也是最低值）
TARGET_MAX = 40        # 最长 40 分钟
TARGET_UP = (2, 5)     # 每完成一次签到：+2~5 分钟
TARGET_DOWN = (5, 8)   # 每少一次签到：−5~8 分钟


def next_target_minutes(current, *, signed_in, streak=0, missed_days=1):
    """纯函数：算「下一天的每日目标时长」（分钟）。

    需求：首次 10 分钟；每完成一次签到 +2~5 分钟（最长 40）；
    少一次签到 −5~8 分钟（最低 10）。

    步长在区间内按「连续天数 / 漏签天数」取 —— 越连续加得越多、漏得越久减得越狠，
    但永远落在 [TARGET_MIN, TARGET_MAX] 内，且结果可预期（便于单测）。
    """
    base = int(current or 0) or TARGET_MIN
    if signed_in:
        step = TARGET_UP[0] + min(TARGET_UP[1] - TARGET_UP[0], max(0, int(streak) - 1) // 2)
        value = base + step
    else:
        step = TARGET_DOWN[0] + min(TARGET_DOWN[1] - TARGET_DOWN[0], max(0, int(missed_days) - 1))
        value = base - step
    return max(TARGET_MIN, min(TARGET_MAX, value))


def _month_days(year, month):
    """这个月有多少天（学习日历用）。"""
    nxt = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return (nxt - datetime(year, month, 1)).days


def split_by_mix(total):
    """总题量 → {new_learning, weakness, review}：round(50%)/round(30%)/余额，且每类 ≥1。"""
    total = max(3, int(total or 0))
    counts = {"new_learning": int(round(total * MIX["new_learning"])),
              "weakness": int(round(total * MIX["weakness"]))}
    counts["review"] = total - counts["new_learning"] - counts["weakness"]
    # 边界取整：末类可能被小数取整压到 0（如 total=3 → 2/1/0），从最大类借 1 题，直到每类 ≥1
    while min(counts.values()) < 1:
        donor = max(TYPE_ORDER, key=lambda key: counts[key])
        if counts[donor] <= 1:
            break
        counts[donor] -= 1
        counts[min(TYPE_ORDER, key=lambda key: counts[key])] += 1
    return counts


def _prev_day(day):
    return (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def _day_range(day, days):
    """截止 day 的连续 days 天（升序，含 day）。"""
    end = datetime.strptime(day, "%Y-%m-%d")
    return [(end - timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(max(1, int(days)) - 1, -1, -1)]


def _rate(done, total):
    return round(done / float(total), 4) if total else 0.0


class HabitEngine:
    """每日任务 + 习惯画像门面（所有查询按 student_id 过滤）。"""

    MIX = MIX
    MIX_TEXT = MIX_TEXT

    # V2.5 每日计划（需求 §14-§15）：基础比例之上按学生状态动态调整，总量按年级限时
    PLAN_MIX = {"new_learning": 0.40, "weakness": 0.25, "review": 0.20,
                "wrong_recovery": 0.10, "active_recall": 0.05}
    PLAN_TEXT = {"new_learning": "新知识", "weakness": "薄弱训练", "review": "复习恢复",
                 "wrong_recovery": "错题康复", "active_recall": "主动回忆"}
    PLAN_ICON = {"new_learning": "🌱", "weakness": "🌿", "review": "🌳",
                 "wrong_recovery": "⚔️", "active_recall": "🧠"}
    PLAN_ORDER = ("new_learning", "weakness", "review", "wrong_recovery", "active_recall")
    GRADE_MINUTES = ((2, 10, 15), (4, 15, 20), (6, 20, 30))   # (年级上限, 下限, 上限)
    REST_PROTECTION_LIMIT = 2                                  # 每月休息保护次数（禁止付费购买）
    # ---------- 生成（幂等） ----------

    def generate_daily_tasks(self, db, student_id, *, date=None, minutes=None, force=False):
        """生成 / 复用当天任务（同一天重复调用不新增行）。"""
        day = planner.date_text(date)
        if minutes is None:
            # V2.6：任务分钟数与「自适应目标时长」同源，否则会出现两处时长不一致
            minutes = self._sync_target(db, student_id, day)
        rows = self._day_rows(db, student_id, day)
        if rows and not force:
            return rows

        index = {(row.task_type, row.subject): row for row in rows}
        for item in self._build_items(db, student_id, day, minutes):
            row = index.get((item["task_type"], item["subject"]))
            if row is None:
                row = DailyLearningTask(
                    student_id=student_id, date=day, task_type=item["task_type"],
                    title=item["title"], subject=item["subject"],
                    knowledge_id=item["knowledge_id"], target_count=item["target_count"],
                    complete_count=0, duration_minutes=0,
                    target_minutes=item["target_minutes"], status="pending",
                    priority=item["priority"], source=item["source"],
                    plan_id=item["plan_id"], goal=item["goal"], reason=item["reason"],
                    created_time=datetime.now())
                db.add(row)
                index[(item["task_type"], item["subject"])] = row
                continue
            if int(row.complete_count or 0) > 0 and row.knowledge_id != item["knowledge_id"]:
                continue        # 已有进度：不覆盖孩子正在做的任务
            for field in ("title", "knowledge_id", "target_count", "target_minutes",
                          "priority", "source", "plan_id", "goal", "reason"):
                setattr(row, field, item[field])
            row.updated_time = datetime.now()
        db.commit()
        return self._day_rows(db, student_id, day)

    def _build_items(self, db, student_id, day, minutes):
        plans = db.query(LearningPlan).filter(
            LearningPlan.student_id == student_id,
            LearningPlan.date == day,
            LearningPlan.status != "expired",
        ).all()
        plan_index = {(row.item_type or "new_learning", row.subject): row for row in plans}

        mastery = db.query(StudentKnowledgeMastery).filter(
            StudentKnowledgeMastery.student_id == student_id,
        ).order_by(StudentKnowledgeMastery.mastery_score.asc(),
                   StudentKnowledgeMastery.knowledge_id.asc()).all()
        by_subject = {}
        for row in mastery:
            by_subject.setdefault(row.subject, []).append(row)

        base_total = float(sum(planner.DEFAULT_MINUTES.values()))
        scale = (float(minutes) / base_total) if minutes else 1.0
        items = []
        order = 0
        for subject in SUBJECTS:
            subject_minutes = max(planner.MIN_MINUTES,
                                  int(round(planner.DEFAULT_MINUTES.get(subject, 10) * scale)))
            total = planner.target_count_of(subject, subject_minutes)
            counts = split_by_mix(total)
            ranked = by_subject.get(subject) or []
            fresh = [row for row in ranked if int(row.total_questions or 0) <= 0]
            for task_type in TYPE_ORDER:
                order += 1
                count = counts[task_type]
                knowledge, plan_id, source, reason = self._knowledge(
                    task_type, subject, ranked, fresh, plan_index.get((task_type, subject)))
                items.append({
                    "task_type": task_type,
                    "title": f"{subject} · {MIX_TEXT[task_type]}",
                    "subject": subject,
                    "knowledge_id": knowledge,
                    "target_count": count,
                    "target_minutes": max(1, int(round(subject_minutes * count / float(total)))),
                    "priority": order,
                    "source": source,
                    "plan_id": plan_id,
                    "goal": self._goal_text(task_type, knowledge, count),
                    "reason": reason,
                })
        return items

    @staticmethod
    def _knowledge(task_type, subject, ranked, fresh, plan_row):
        """选知识点：优先当天 learning_plan，其次掌握度升序画像，最后知识点体系兜底。"""
        if plan_row is not None and plan_row.knowledge_id:
            return (plan_row.knowledge_id, int(plan_row.id or 0), "plan",
                    plan_row.reason or f"{MIX_TEXT[task_type]}：来自今日学习计划")
        if ranked:
            if task_type == "weakness":
                pick = ranked[0]
                reason = f"掌握度 {int(pick.mastery_score or 0)}，先把薄弱点补起来"
            elif task_type == "review":
                pick = ranked[-1]
                reason = f"「{pick.knowledge_id}」最近练过，隔几天再复习一次"
            else:
                pick = fresh[0] if fresh else ranked[min(1, len(ranked) - 1)]
                reason = ("还没练过的新知识点，今天先认识一下" if fresh
                          else f"掌握度 {int(pick.mastery_score or 0)}，继续往上学一层")
            return (pick.knowledge_id, 0, "habit", reason)
        names = knowledge_tree.all_names(subject)
        return (names[0] if names else subject, 0, "habit",
                "还没有练习记录，先从最基础的知识点开始")

    @staticmethod
    def _goal_text(task_type, knowledge, count):
        if task_type == "weakness":
            return f"补强「{knowledge}」，做 {count} 题"
        if task_type == "review":
            return f"复习「{knowledge}」，做 {count} 题看看还记得吗"
        return f"认识新知识「{knowledge}」，做 {count} 题"

    # ---------- 查询 ----------

    def today(self, db, student_id, *, date=None):
        """今日任务总览（先确保当天任务已生成；学生不存在则返回空结构，不生成幽灵任务）。"""
        day = planner.date_text(date)
        if not self._student_exists(db, student_id):
            return {"student_id": student_id, "date": day, "generated": False,
                    "tasks": [], "summary": self._summary([])}
        existed = bool(self._day_rows(db, student_id, day))
        rows = self.generate_daily_tasks(db, student_id, date=day)
        return {"student_id": student_id, "date": day,
                "generated": bool(rows) and not existed,
                "tasks": [self.task_dict(row) for row in rows],
                "summary": self._summary(rows)}

    def task_dict(self, row):
        return {
            "task_id": int(row.id or 0),
            "task_type": row.task_type or "new_learning",
            "task_type_text": MIX_TEXT.get(row.task_type or "new_learning", "新知识"),
            "title": row.title or "",
            "subject": row.subject or "",
            "knowledge": row.knowledge_id or "",
            "target_count": int(row.target_count or 0),
            "complete_count": int(row.complete_count or 0),
            "duration_minutes": int(row.duration_minutes or 0),
            "target_minutes": int(row.target_minutes or 0),
            "status": row.status or "pending",
            "status_text": STATUS_TEXT.get(row.status or "pending", "待完成"),
            "priority": int(row.priority or 0),
            "goal": row.goal or "",
            "reason": row.reason or "",
        }

    def _summary(self, rows):
        total = len(rows)
        done = sum(1 for row in rows if row.status == "done")
        mix = {key: sum(int(row.target_count or 0) for row in rows
                        if row.task_type == key) for key in TYPE_ORDER}
        return {
            "total": total,
            "done": done,
            "pending": total - done,
            "completion_rate": _rate(done, total),
            "minutes": sum(int(row.duration_minutes or 0) for row in rows),
            "mix": mix,
            "mix_tasks": {key: sum(1 for row in rows if row.task_type == key)
                          for key in TYPE_ORDER},
        }

    def profile(self, db, student_id, *, date=None):
        """习惯画像（只读，含连续天数 / 完成率 / 时长 / 徽章 / 等级 / 近 7 天曲线）。"""
        day = planner.date_text(date)
        return self._profile_dict(db, student_id, day, self._profile_row(db, student_id))

    def stats(self, db, student_id, *, days=7, date=None):
        """近 N 天完成率 / 时长序列。"""
        day = planner.date_text(date)
        days = max(1, int(days or 7))
        rows = self._all_rows(db, student_id)
        items = [self._day_stat(rows, item) for item in _day_range(day, days)]
        return {
            "student_id": student_id,
            "days": days,
            "items": items,
            "avg_rate": round(sum(item["rate"] for item in items) / float(len(items)), 4)
            if items else 0.0,
            "total_minutes": sum(item["minutes"] for item in items),
        }
    def calendar(self, db, student_id, *, month=None, date=None):
        """学习日历（只读）：当月每一天是否打卡 —— 打卡 = 当天有完成的任务。

        ``month`` 形如 ``YYYY-MM``，缺省取 ``date``（默认今天）所在月。
        """
        day = planner.date_text(date)
        text = str(month or day)[:7]
        try:
            year, mon = int(text[:4]), int(text[5:7])
            first_day = datetime(year, mon, 1)
        except (TypeError, ValueError):
            text = day[:7]
            year, mon = int(text[:4]), int(text[5:7])
            first_day = datetime(year, mon, 1)
        days_in_month = _month_days(year, mon)

        by_day = {}
        for item in self._all_rows(db, student_id):
            key = str(item["date"])[:10]
            stat = by_day.setdefault(key, {"done": 0, "total": 0, "minutes": 0})
            stat["total"] += 1
            if item["status"] == "done" or item["complete_count"] > 0:
                stat["done"] += 1
            stat["minutes"] += item["duration_minutes"]

        items = []
        for index in range(days_in_month):
            key = "%s-%02d" % (text, index + 1)
            stat = by_day.get(key) or {"done": 0, "total": 0, "minutes": 0}
            items.append({"date": key, "day": index + 1, "checked": stat["done"] > 0,
                          "done": stat["done"], "total": stat["total"],
                          "minutes": stat["minutes"], "is_today": key == day,
                          "is_future": key > day})

        return {"student_id": student_id, "month": text,
                "first_weekday": first_day.weekday(), "days_in_month": days_in_month,
                "checked_count": sum(1 for item in items if item["checked"]),
                "today": day, "items": items}

    # ---------- 完成 / 答题钩子 ----------

    def complete_task(self, db, student_id, task_id, *, minutes=0, count=None, done=True):
        """完成 / 部分完成：累加时长，complete_count >= target_count 自动 done。"""
        row = db.query(DailyLearningTask).filter(
            DailyLearningTask.id == task_id,
            DailyLearningTask.student_id == student_id,
        ).first()
        if row is None:
            return {}
        if minutes:
            row.duration_minutes = int(row.duration_minutes or 0) + max(0, int(minutes))
        if count is not None:
            row.complete_count = int(row.complete_count or 0) + max(0, int(count))
        if done:
            row.complete_count = max(int(row.complete_count or 0), int(row.target_count or 0))
        if int(row.complete_count or 0) >= int(row.target_count or 0):
            row.status = "done"
            row.completed_time = row.completed_time or datetime.now()
        elif int(row.complete_count or 0) > 0:
            row.status = "doing"
        row.updated_time = datetime.now()
        db.commit()
        return {
            "student_id": student_id,
            "task_id": int(row.id or 0),
            "task_type": row.task_type or "",
            "status": row.status or "pending",
            "status_text": STATUS_TEXT.get(row.status or "pending", "待完成"),
            "complete_count": int(row.complete_count or 0),
            "target_count": int(row.target_count or 0),
            "duration_minutes": int(row.duration_minutes or 0),
            "summary": self._summary(self._day_rows(db, student_id, row.date)),
            "profile": self.refresh(db, student_id, date=row.date),
        }

    def record_answer(self, db, student_id, *, subject, knowledge, correct, minutes=0, date=None,
                      task_id=0):
        """答题钩子：把作答算进当天任务（匹配任务 complete_count += 1）与时长，绝不抛给主流程。

        task_id 是题单模式带过来的「内部标记」（练习页按剩余题型统一出题时，记下孩子此刻在做的
        那一项）：给了它就优先记到那一项头上，不再只靠 科目+知识点 猜桶，避免记错项。
        """
        day = planner.date_text(date)
        rows = self._day_rows(db, student_id, day)
        if not rows:
            rows = self.generate_daily_tasks(db, student_id, date=day)
        result = {"student_id": student_id, "date": day, "subject": subject or "",
                  "knowledge": knowledge or "", "correct": bool(correct),
                  "matched": False, "task_id": 0, "task_type": "", "complete_count": 0}
        row = None
        if task_id:
            row = next((item for item in rows
                        if int(item.id or 0) == int(task_id) and item.status != "done"), None)
        if row is None:
            row = next((item for item in rows if item.subject == subject
                        and item.knowledge_id == knowledge and item.status != "done"), None)
        if row is None:
            row = next((item for item in rows
                        if item.subject == subject and item.status != "done"), None)
        if row is None:
            return result
        row.complete_count = int(row.complete_count or 0) + 1
        if minutes:
            row.duration_minutes = int(row.duration_minutes or 0) + max(0, int(minutes))
        if row.complete_count >= int(row.target_count or 0):
            row.status = "done"
            row.completed_time = row.completed_time or datetime.now()
        else:
            row.status = "doing"
        row.updated_time = datetime.now()
        db.commit()
        result.update(matched=True, task_id=int(row.id or 0), task_type=row.task_type or "",
                      status=row.status, complete_count=int(row.complete_count or 0))
        result["profile"] = self.refresh(db, student_id, date=day)
        return result

    # ---------- 画像落库 ----------

    def refresh(self, db, student_id, *, date=None):
        """重算并落库 learning_habit_profile（徽章只增不减）。"""
        day = planner.date_text(date)
        row = self._profile_row(db, student_id, create=True)
        data = self._profile_dict(db, student_id, day, row)
        row.current_streak = data["current_streak"]
        row.longest_streak = data["longest_streak"]
        row.total_days = data["total_days"]
        row.total_tasks = data["total_tasks"]
        row.completed_tasks = data["completed_tasks"]
        row.total_minutes = data["total_minutes"]
        row.today_minutes = data["today_minutes"]
        row.completion_rate = data["completion_rate"]
        # V2.6：目标时长自适应 —— 今天第一次完成学习任务 = 签到（+2~5，最长 40）；
        # 中间漏签由 _sync_target 结算（每天一次）
        was_active = str(row.last_active_date or "")
        target = self._sync_target(db, student_id, day, row=row)
        if data["last_active_date"] == day and was_active != day:
            target = next_target_minutes(target, signed_in=True,
                                         streak=int(data["current_streak"] or 1))
        row.target_minutes = target
        row.last_active_date = data["last_active_date"]
        row.rest_protection_count = data["rest_protection_count"]
        row.rest_protection_month = data["rest_protection_month"]
        row.badges = json.dumps([item["key"] for item in data["badges"] if item["got"]],
                                ensure_ascii=False)
        row.level = data["level"]
        row.updated_time = datetime.now()
        db.commit()
        return data

    def _profile_dict(self, db, student_id, day, row):
        rows = self._all_rows(db, student_id)
        active = sorted({item["date"] for item in rows
                         if item["status"] == "done" or item["complete_count"] > 0})
        today_active = day in active
        stored_streak = int(row.current_streak or 0) if row is not None else 0
        last_active = (row.last_active_date or "") if row is not None else ""
        yesterday = _prev_day(day)

        if today_active:                       # 状态转移：昨天 → +1；今天 → 不变；更早/空 → 1
            if last_active == day:
                current = max(stored_streak, 1)
            elif last_active == yesterday:
                current = stored_streak + 1
            else:
                current = 1
            last_active = day
        else:                                  # 今天还没学：早于昨天则归零，昨天则保持
            current = stored_streak if last_active and last_active >= yesterday else 0

        longest = max(int(row.longest_streak or 0) if row is not None else 0, current)
        total_tasks = len(rows)
        completed_tasks = sum(1 for item in rows if item["status"] == "done")
        completion_rate = _rate(completed_tasks, total_tasks)
        total_minutes = sum(item["duration_minutes"] for item in rows)
        today_minutes = sum(item["duration_minutes"] for item in rows if item["date"] == day)
        month = str(day)[:7]
        monthly_days = len({text for text in active if str(text)[:7] == month})
        avg_daily = round(total_minutes / float(len(active)), 1) if active else 0.0
        preferred = self._preferred_time(rows)
        rest_used = self._rest_used(db, student_id, month, row)

        stored_badges = set(json.loads((row.badges if row is not None else "") or "[]") or [])
        earned = set(key for key in stored_badges if key in BADGE_KEYS)
        if len(active) >= 1:
            earned.add("first_day")
        for need, key in ((3, "streak_3"), (7, "streak_7"), (30, "streak_30")):
            if longest >= need:
                earned.add(key)
        if total_tasks >= 5 and completion_rate >= 0.8:
            earned.add("rate_80")
        if total_minutes >= 100:
            earned.add("minutes_100")

        level = min(10, 1 + min(6, current // 3) + (1 if "rate_80" in earned else 0))
        return {
            "student_id": student_id,
            "current_streak": current,
            "longest_streak": longest,
            "total_days": len(active),
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "completion_rate": completion_rate,
            "total_minutes": total_minutes,
            "today_minutes": today_minutes,
            "monthly_learning_days": monthly_days,
            "average_daily_minutes": avg_daily,
            "preferred_learning_time": preferred,
            "rest_protection_count": rest_used,
            "rest_protection_month": month,
            "rest_protection_left": max(0, self.REST_PROTECTION_LIMIT - rest_used),
            "level": level,
            "level_text": LEVEL_TEXT.get(level, LEVEL_TEXT[1]),
            "badges": [{"key": key, "name": name, "icon": icon, "got": key in earned}
                       for key, name, icon in BADGE_CATALOG],
            "target_minutes": (int(row.target_minutes or 0) or TARGET_MIN)
            if row is not None else TARGET_MIN,
            "last_active_date": last_active,
            "recent": [self._day_stat(rows, item) for item in _day_range(day, 7)],
        }

    # ---------- 今日计划（五段动态配比 + 时长上限） ----------

    def minutes_for_grade(self, grade):
        """按年级给建议时长区间（分钟）：1-2 年级 10-15 / 3-4 年级 15-20 / 5-6 年级 20-30。"""
        try:
            value = min(6, max(1, int(grade or 1)))
        except (TypeError, ValueError):
            value = 1
        for top, low, high in self.GRADE_MINUTES:
            if value <= top:
                return low, high
        return 20, 30

    def _sync_target(self, db, student_id, day, row=None):
        """结算「漏签」对目标时长的影响：每天只结算一次（靠 target_synced_date 幂等）。"""
        row = row or self._profile_row(db, student_id, create=True)
        current = int(row.target_minutes or 0) or TARGET_MIN
        if str(row.target_synced_date or "") == day:
            return current

        last_active = str(row.last_active_date or "")
        if last_active:
            try:
                gap = (datetime.strptime(day, "%Y-%m-%d").date()
                       - datetime.strptime(last_active, "%Y-%m-%d").date()).days
            except ValueError:
                gap = 0
            for index in range(max(0, gap - 1)):          # 中间漏掉的天数（不含今天）
                current = next_target_minutes(current, signed_in=False, missed_days=index + 1)

        row.target_minutes = current
        row.target_synced_date = day
        db.commit()
        return current

    def target_minutes_of(self, db, student_id, *, date=None):
        """当前每日目标时长（分钟）：顺带结算一次漏签（幂等），供其它模块只读调用。"""
        return self._sync_target(db, student_id, planner.date_text(date))

    def goal(self, db, student_id):
        """当前学习目标（本版本只启用 SYSTEM 来源；PARENT / STUDENT 预留）。"""
        ranked = self._ranked_points(db, student_id, limit=1)
        subject, knowledge = ranked[0] if ranked else ("数学", "两步计算应用题")
        return {"text": "当前目标：提升{0}·{1}".format(subject, knowledge),
                "source": "SYSTEM", "subject": subject, "knowledge": knowledge, "kind": "SYSTEM",
                "sources": ["SYSTEM", "PARENT", "STUDENT"]}

    def rest_status(self, db, student_id, *, date=None):
        """休息保护状态：本月已用 / 剩余（每月上限 2 次）。"""
        day = planner.date_text(date)
        month = str(day)[:7]
        used = self._rest_used(db, student_id, month, self._profile_row(db, student_id))
        return {"date": day, "month": month, "rest_protection_count": used,
                "rest_protection_left": max(0, self.REST_PROTECTION_LIMIT - used),
                "rest_protection_limit": self.REST_PROTECTION_LIMIT}

    def use_rest_protection(self, db, student_id, *, date=None):
        """使用一次休息保护：不打断连续学习，也不清零任何历史成长数据。"""
        day = planner.date_text(date)
        month = str(day)[:7]
        row = self._profile_row(db, student_id, create=True)
        used = self._rest_used(db, student_id, month, row)
        if used >= self.REST_PROTECTION_LIMIT:
            return {"ok": False, "reason": "本月的休息保护已经用完了",
                    "rest_protection_count": used, "rest_protection_left": 0}
        row.rest_protection_month = month
        row.rest_protection_count = used + 1
        previous = _prev_day(day)
        if (row.last_active_date or "") < previous:
            row.last_active_date = previous      # 视作昨天学过 → 今天休息不扣连续天数
        row.updated_time = datetime.now()
        db.commit()
        data = self._profile_dict(db, student_id, day, row)
        self.refresh(db, student_id, date=day)
        data.update({"ok": True, "reason": "今天休息一下，连续学习不会断",
                     "rest_protection_count": used + 1,
                     "rest_protection_left": max(0, self.REST_PROTECTION_LIMIT - (used + 1))})
        return data

    def plan(self, db, student_id, *, date=None, minutes=None, persist=False):
        """今日学习计划：五段任务 + 分钟数；按年级限时，比例随学生状态动态调整。"""
        day = planner.date_text(date)
        grade = self._grade_of(db, student_id)
        # V2.6：总量不再按年级写死，而是用「自适应目标时长」（首次 10 分钟起步，10~40）
        target = self._sync_target(db, student_id, day)
        try:
            wanted = int(minutes) if minutes else target
        except (TypeError, ValueError):
            wanted = target
        total = min(TARGET_MAX, max(TARGET_MIN, wanted))
        weights, notes = self._plan_weights(db, student_id, day)
        goal = self.goal(db, student_id)
        ranked = self._ranked_points(db, student_id)
        fallback = ranked[0] if ranked else ("数学", "两步计算应用题")
        items = []
        for index, kind in enumerate(self.PLAN_ORDER):
            weight = float(weights.get(kind, 0.0))
            minutes_k = max(1, int(round(total * weight))) if weight > 0 else 0
            if minutes_k <= 0:
                continue
            subject, knowledge = self._point_for(db, student_id, kind, ranked, fallback, index)
            items.append({"task_type": kind, "task_type_text": self.PLAN_TEXT.get(kind, kind),
                          "icon": self.PLAN_ICON.get(kind, "✅"), "subject": subject,
                          "knowledge": knowledge, "knowledge_id": knowledge, "minutes": minutes_k,
                          "target_count": max(1, minutes_k // 2),
                          "title": "{0}·{1}".format(self.PLAN_TEXT.get(kind, kind), knowledge),
                          "goal": goal["text"],
                          "reason": "；".join(notes) or "按今日状态生成的默认计划",
                          "source": "plan", "weight": weight})
        # V2.6：各段四舍五入会带来 ±1 分钟零头，补给最大的一段，保证「总时长 = 各段之和」
        if items:
            diff = int(total) - sum(item["minutes"] for item in items)
            if diff:
                main = max(items, key=lambda item: item["minutes"])
                main["minutes"] = max(1, main["minutes"] + diff)
                main["target_count"] = max(1, main["minutes"] // 2)
        plan = {"student_id": student_id, "date": day, "grade": grade, "mode": "DAILY_PLAN",
                "minutes": sum(item["minutes"] for item in items) or total,
                "target_minutes": total, "min_minutes": TARGET_MIN, "max_minutes": TARGET_MAX,
                "message": "今天我们用 {0} 分钟完成 {1} 个小任务。".format(total, len(items)),
                "items": items, "adjust": notes, "goal": goal}
        if persist:
            self.generate_daily_tasks(db, student_id, date=day)
            self._persist_plan(db, student_id, day, items)
            plan["tasks"] = self.task_dict_list(db, student_id, day)
        return plan

    def start_today(self, db, student_id, *, date=None, minutes=None):
        """孩子点「开始今天的学习」：生成三段基础任务 + 五段计划并落库。"""
        plan = self.plan(db, student_id, date=date, minutes=minutes, persist=True)
        today = self.today(db, student_id, date=date)
        return {"student_id": student_id, "date": plan["date"], "minutes": plan["minutes"],
                "message": plan["message"], "plan": plan,
                "tasks": today.get("tasks") or [], "summary": today.get("summary") or {}}

    def task_dict_list(self, db, student_id, day):
        """当天任务字典列表（供计划落库后立即回显）。"""
        return [self.task_dict(row) for row in self._day_rows(db, student_id, day)]

    def _persist_plan(self, db, student_id, day, items):
        """把计划新增的两类（错题康复 / 主动回忆）落库；三段基础任务仍由 generate_daily_tasks 负责。"""
        rows = self._day_rows(db, student_id, day)
        index = {(row.task_type, row.subject, row.knowledge_id or ""): row for row in rows}
        changed = False
        for item in items:
            if item["task_type"] in TYPE_ORDER:
                continue
            key = (item["task_type"], item["subject"], item["knowledge_id"])
            if key in index:
                continue
            db.add(DailyLearningTask(
                student_id=student_id, date=day, task_type=item["task_type"],
                title=item["title"], subject=item["subject"], knowledge_id=item["knowledge_id"],
                target_count=item["target_count"], complete_count=0, duration_minutes=0,
                target_minutes=item["minutes"], status="pending", priority=1,
                source=item["source"], plan_id=None, goal=item["goal"], reason=item["reason"],
                created_time=datetime.now()))
            index[key] = item
            changed = True
        if changed:
            try:
                db.commit()
            except Exception:                  # noqa: BLE001 - unique 索引冲突：按库内实况返回
                db.rollback()
        return changed

    def _plan_weights(self, db, student_id, day):
        """基础比例 40/25/20/10/5 之上，按当日状态动态调整（最后归一化）。"""
        weights = dict(self.PLAN_MIX)
        notes = []
        pending = self._pending_recovery(db, student_id)
        due = self._due_review(db, student_id, day)
        if pending >= 3:
            add = min(0.15, 0.03 * (pending // 3))
            weights["wrong_recovery"] += add
            weights["new_learning"] = max(0.15, weights["new_learning"] - add / 2.0)
            weights["weakness"] = max(0.10, weights["weakness"] - add / 2.0)
            notes.append("错题积压 {0} 条：提高错题康复".format(pending))
        if due >= 3:
            add = min(0.10, 0.02 * (due // 3))
            weights["review"] += add
            weights["new_learning"] = max(0.15, weights["new_learning"] - add)
            notes.append("复习到期 {0} 条：提高复习".format(due))
        elif due <= 0:
            move = weights["review"] * 0.5
            weights["review"] -= move
            weights["new_learning"] += move * 0.6
            weights["weakness"] += move * 0.4
            notes.append("没有到期复习：时间转给新学习与薄弱补强")
        total = sum(weights.values()) or 1.0
        return {key: round(value / total, 4) for key, value in weights.items()}, notes

    @staticmethod
    def _student_exists(db, student_id):
        """学生是否存在：不存在时今日任务 / 计划一律返回空结构。"""
        try:
            from models import Student
            return db.query(Student).filter(Student.id == student_id).first() is not None
        except Exception:                      # noqa: BLE001
            return False

    @staticmethod
    def _grade_of(db, student_id):
        """学生年级（1-6），决定每日时长区间。"""
        try:
            from models import Student
            student = db.query(Student).filter(Student.id == student_id).first()
            return int(getattr(student, "grade", 1) or 1) if student else 1
        except Exception:                      # noqa: BLE001
            return 1

    @staticmethod
    def _ranked_points(db, student_id, limit=8):
        """掌握度升序的薄弱知识点列表 [(subject, knowledge), ...]。"""
        try:
            rows = db.query(StudentKnowledgeMastery).filter(
                StudentKnowledgeMastery.student_id == student_id,
            ).order_by(StudentKnowledgeMastery.mastery_score.asc(),
                       StudentKnowledgeMastery.knowledge_id.asc()).all()
        except Exception:                      # noqa: BLE001
            return []
        out = []
        for row in rows:
            name = row.knowledge_id or ""
            if not name:
                continue
            out.append((row.subject or "数学", name))
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _point_for(db, student_id, kind, ranked, fallback, index):
        """每个任务段挑一个知识点：错题康复优先用待康复错题。"""
        if kind == "wrong_recovery":
            point = HabitEngine._recovery_point(db, student_id)
            if point:
                return point
        if not ranked:
            return fallback
        return ranked[index % len(ranked)]

    @staticmethod
    def _recovery_point(db, student_id):
        try:
            from models import WrongQuestionRecovery
            row = db.query(WrongQuestionRecovery).filter(
                WrongQuestionRecovery.student_id == student_id,
                WrongQuestionRecovery.state != "MASTERED",
            ).order_by(WrongQuestionRecovery.id.asc()).first()
            if row is not None:
                return (row.subject or "数学", row.knowledge_id or "")
        except Exception:                      # noqa: BLE001
            pass
        return None

    @staticmethod
    def _pending_recovery(db, student_id):
        """未真正掌握的错题条数（错题积压 → 提高错题康复占比）。"""
        try:
            from models import WrongQuestionRecovery
            return db.query(WrongQuestionRecovery).filter(
                WrongQuestionRecovery.student_id == student_id,
                WrongQuestionRecovery.state != "MASTERED").count()
        except Exception:                      # noqa: BLE001
            return 0

    @staticmethod
    def _due_review(db, student_id, day):
        """到期该复习的记忆状态条数（没有则把复习时间转给新学习）。"""
        try:
            from models import KnowledgeMemoryState
            now = datetime.now()
            return db.query(KnowledgeMemoryState).filter(
                KnowledgeMemoryState.student_id == student_id,
                KnowledgeMemoryState.next_review_at <= now).count()
        except Exception:                      # noqa: BLE001
            return 0

    @staticmethod
    def _preferred_time(rows):
        """基础版偏好时段：最近一次有学习活动的整点（HH:00），无记录返回空串。"""
        stamps = [item.get("at") for item in rows
                  if item.get("at") is not None
                  and (item.get("status") == "done" or int(item.get("complete_count") or 0) > 0)]
        if not stamps:
            return ""
        return "{0:02d}:00".format(int(max(stamps).hour))

    @staticmethod
    def _rest_used(db, student_id, month, row):
        """本月已用休息保护次数（跨月自动归零）。"""
        if row is None or (row.rest_protection_month or "") != month:
            return 0
        return max(0, int(row.rest_protection_count or 0))

    # ---------- 底层 ----------

    def _profile_row(self, db, student_id, create=False):
        row = db.query(LearningHabitProfile).filter(
            LearningHabitProfile.student_id == student_id).first()
        if row is None and create:
            row = LearningHabitProfile(student_id=student_id, created_time=datetime.now())
            db.add(row)
            db.flush()
        return row

    def _all_rows(self, db, student_id):
        rows = db.query(DailyLearningTask).filter(
            DailyLearningTask.student_id == student_id).all()
        return [{"id": int(item.id or 0), "date": item.date or "",
                 "task_type": item.task_type or "", "status": item.status or "pending",
                 "complete_count": int(item.complete_count or 0),
                 "duration_minutes": int(item.duration_minutes or 0),
                 "at": item.updated_time or item.created_time} for item in rows]

    def _day_rows(self, db, student_id, day):
        return db.query(DailyLearningTask).filter(
            DailyLearningTask.student_id == student_id,
            DailyLearningTask.date == day,
        ).order_by(DailyLearningTask.priority.asc(), DailyLearningTask.id.asc()).all()

    @staticmethod
    def _day_stat(rows, day):
        day_rows = [item for item in rows if item["date"] == day]
        done = sum(1 for item in day_rows if item["status"] == "done")
        return {"date": day, "done": done, "total": len(day_rows),
                "minutes": sum(item["duration_minutes"] for item in day_rows),
                "rate": _rate(done, len(day_rows))}


DEFAULT_ENGINE = HabitEngine()
