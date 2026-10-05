# ==============================================================
# 能力契约｜复习门面：记忆状态、风险刷新、队列、出题、提交判分、反馈、报表、策略日志（唯一碰库的复习模块）
# 入口：ReviewEngine（state_row/states_of/ensure_states/record_learning/refresh_risks/queue_for/schedule/today/due/review_question/submit_review/skip/apply_feedback/memory_map/stats/mix_for/log_strategy/strategy_logs/review_history）/ DEFAULT_ENGINE
# 依赖：review 各纯函数模块、error_analysis、grading、knowledge_tree、stages、wrong_book、models
# 不负责：算法细节 → review/memory|interval|forgetting|scheduler|selector|mix；旧体系 → srs.py
# 验证：python backend/verify_memory.py
# 被调用：main.py（import 期 ensure_states、/submit record_learning）、review_routes.py、adaptive/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 · ReviewEngine（数据库门面）。

把纯函数算法与 SQLite 串成闭环：

```text
学习（/submit 或复习重新学）
  → MemoryState：掌握度 / 稳定性 / 个人难度 / 成熟度 / 下次复习时间
  → ReviewScheduler：今日复习队列（P0~P3，每科 ≤8、每天 ≤15、每个 1~3 题）
  → ReviewQuestionSelector：复习题（不重复历史原题，50/30/20 模式配比）
  → /api/review/answer：判分 → 复习质量 → 新间隔 / 新稳定性 / 新成熟度
  → 复习失败：错因分析 + 错题本 + 稳定性下降；连续失败 → RELEARN 回自适应引擎
```

设计要点：

1. **每个学生 × 每科 × 每个知识点一行 `knowledge_memory_state`**，互不影响。
2. **风险按需增量刷新**：只有变化超过 0.05、或已经到期的记录才写库，页面刷新不重算全表。
3. **队列按天缓存**：同一天第二次打开页面直接读 `review_queue`，不重新调度（性能要求）。
4. **复习答题也写 `answer_records`**，所以掌握度、错因、错题本、统计与日常练习完全一致。
5. **长期掌握的知识偶尔错一题不重置**：间隔只压缩、成熟度按掌握度与稳定性重新判定，
   并追加 1 道验证题；连续失败才确认遗忘并转入 `RELEARN`。
"""

from datetime import datetime, time as day_time, timedelta

import error_analysis
import grading
import knowledge_tree
import stages
import wrong_book
from models import (
    AnswerRecord,
    KnowledgeMemoryState,
    Question,
    ReviewQueue,
    ReviewRecord,
    ReviewStrategyLog,
    Student,
    StudentKnowledgeMastery,
)
from review import forgetting, interval, memory, mix, scheduler, selector

FEEL_TO_FEEDBACK = {"easy": "easy", "normal": "", "hard": "hard", "lost": "hard"}
RISK_REFRESH_DELTA = 0.05
DEFAULT_DIFFICULTY = 50
VERIFY_EXTRA_LINE = ("STABLE", "LONG_TERM")
CHILD_DONE_TEXT = "🎉 今天的知识都照顾好啦！"
CHILD_EMPTY_TEXT = "今天的知识都很健康，不用浇水啦～"


def _json_dumps(value):
    import json

    return json.dumps(value, ensure_ascii=False)


def _fmt(moment):
    return moment.strftime("%Y-%m-%d %H:%M") if isinstance(moment, datetime) else ""


def day_start(moment=None):
    """当天 0 点，用于按天缓存队列。"""
    moment = moment or datetime.now()
    return datetime.combine(moment.date(), day_time.min)


def grade_text(grade):
    if isinstance(grade, int) and 1 <= grade <= 6:
        return f"{stages.GRADE_NAMES[grade - 1]}年级"
    return str(grade or "三年级")


class ReviewEngine:
    """间隔复习引擎门面（所有复习相关的数据库读写都在这里）。"""

    # ---------------- 记忆状态 ----------------

    def state_row(self, db, student_id, subject, knowledge, create=True):
        """取这个学生这个知识点的记忆状态行。"""
        row = db.query(KnowledgeMemoryState).filter(
            KnowledgeMemoryState.student_id == student_id,
            KnowledgeMemoryState.subject == subject,
            KnowledgeMemoryState.knowledge_id == knowledge,
        ).first()

        if row is None and create:
            row = KnowledgeMemoryState(
                student_id=student_id,
                subject=subject,
                knowledge_id=knowledge,
                mastery_score=0,
                memory_strength=0,
                stability=1.0,
                difficulty=0.5,
                current_interval_days=1.0,
                maturity_level="NEW",
                needs_relearn=True,
                created_at=datetime.now(),
            )
            db.add(row)
            db.flush()

        return row

    def states_of(self, db, student_id, subject=None):
        query = db.query(KnowledgeMemoryState).filter(
            KnowledgeMemoryState.student_id == student_id)
        if subject:
            query = query.filter(KnowledgeMemoryState.subject == subject)
        return query.all()

    def state_summary(self, db, student_id, subject, knowledge, now=None):
        row = self.state_row(db, student_id, subject, knowledge)
        return memory.state_summary(row, now=now)

    def ensure_states(self, db, student_id=None, subject=None, force=False):
        """V2.3 → V2.4 迁移：按 `student_knowledge_mastery` 补齐记忆状态。

        | 掌握度 | 初始成熟度 | 初始间隔 |
        | --- | --- | --- |
        | ≥85 | STABLE | 14 天 |
        | 70~84 | CONSOLIDATING | 7 天 |
        | 60~69 | LEARNING | 3 天 |
        | <60 | LEARNING + 需要重新学 | 1 天 |

        `student_id` 省略时给全部学生补（启动时的幂等迁移）。
        """
        query = db.query(StudentKnowledgeMastery)
        if student_id:
            query = query.filter(StudentKnowledgeMastery.student_id == student_id)
        if subject:
            query = query.filter(StudentKnowledgeMastery.subject == subject)

        existing = {
            (row.student_id, row.subject, row.knowledge_id): row
            for row in db.query(KnowledgeMemoryState).all()
        }

        created = 0
        updated = 0
        now = datetime.now()

        for mastery_row in query.all():
            key = (mastery_row.student_id, mastery_row.subject, mastery_row.knowledge_id)
            mastery_score = int(mastery_row.mastery_score or 0)
            total = int(mastery_row.total_questions or 0)

            if key in existing:
                row = existing[key]
                if force or int(row.mastery_score or 0) != mastery_score:
                    self._apply_state(row, memory.migrate_state(
                        mastery_score, float(mastery_row.confidence or 0), now,
                        last_learned_at=mastery_row.last_practice_time))
                    row.review_count = max(int(row.review_count or 0), total)
                    updated += 1
                continue

            state = memory.migrate_state(mastery_score,
                                         float(mastery_row.confidence or 0), now,
                                         last_learned_at=mastery_row.last_practice_time)
            row = KnowledgeMemoryState(student_id=mastery_row.student_id,
                                       subject=mastery_row.subject,
                                       knowledge_id=mastery_row.knowledge_id)
            self._apply_state(row, state)
            row.review_count = total
            db.add(row)
            created += 1

        db.commit()
        return {"created": created, "updated": updated}

    @staticmethod
    def _apply_state(row, state):
        """把一份记忆状态 dict 写进行对象。"""
        row.mastery_score = state.get("mastery_score", row.mastery_score or 0)
        row.stability = state.get("stability", row.stability or 1.0)
        row.current_interval_days = state.get("current_interval_days",
                                              row.current_interval_days or 1.0)
        row.successful_reviews = state.get("successful_reviews", row.successful_reviews or 0)
        row.failed_reviews = state.get("failed_reviews", row.failed_reviews or 0)
        row.consecutive_failures = state.get("consecutive_failures",
                                            row.consecutive_failures or 0)
        row.review_streak = state.get("review_streak", row.review_streak or 0)
        row.confidence = state.get("confidence", row.confidence or 0)
        row.last_learned_at = state.get("last_learned_at", row.last_learned_at)
        row.last_reviewed_at = state.get("last_reviewed_at", row.last_reviewed_at)
        row.next_review_at = state.get("next_review_at", row.next_review_at)
        row.forgetting_risk = state.get("forgetting_risk", row.forgetting_risk or 0)
        row.difficulty = state.get("difficulty", row.difficulty or 0.5)
        row.maturity_level = state.get("maturity_level", row.maturity_level or "NEW")
        row.needs_relearn = state.get("needs_relearn", row.needs_relearn or False)
        row.memory_strength = state.get("memory_strength", row.memory_strength or 0)
        row.updated_at = datetime.now()
        return row

    # ---------------- 学习后同步 ----------------

    def record_learning(self, db, student_id, subject, knowledge, mastery_score=None,
                        confidence=0.0, correct=True, when=None):
        """日常练习 / 新学习之后同步记忆状态。

        - 第一次真正学会（掌握度 ≥60 且还没复习过）→ **1 天后**第一次复习
        - 掌握度掉到 60 以下 → 标记需要重新学（不做纯复习）
        - 其它情况只刷新掌握度、个人难度、成熟度、遗忘风险
        """
        if not knowledge:
            return None

        now = when or datetime.now()
        row = self.state_row(db, student_id, subject, knowledge)

        if mastery_score is None:
            mastery_score = row.mastery_score or 0
        mastery_score = int(max(0, min(100, int(mastery_score))))

        is_new_learning = (bool(correct) and mastery_score >= memory.RELEARN_LINE
                           and int(row.review_count or 0) == 0)
        relearned = (bool(correct) and mastery_score >= memory.RELEARN_LINE
                     and bool(row.needs_relearn))

        row.mastery_score = mastery_score
        row.confidence = round(float(confidence or 0), 3)
        row.difficulty = memory.personal_difficulty(
            mastery_score, row.failed_reviews or 0, row.successful_reviews or 0,
            None if correct is None else bool(correct))

        if is_new_learning or relearned:
            state = memory.initial_learn_state(mastery_score, confidence, now)
            self._apply_state(row, state)
            row.needs_relearn = False
            source = "learn" if is_new_learning else "relearn"
            self.log_strategy(db, student_id, subject, knowledge,
                              old_interval=0.0, new_interval=row.current_interval_days,
                              old_stability=0.0, new_stability=row.stability,
                              quality="LEARN", source=source,
                              reason=f"掌握度 {mastery_score}，安排 1 天后第一次复习")
        else:
            row.needs_relearn = bool(
                mastery_score < memory.RELEARN_LINE and int(row.review_count or 0) > 0
                or int(row.consecutive_failures or 0) >= 2)
            if row.last_learned_at is None:
                row.last_learned_at = now
            row.maturity_level = memory.maturity_of(
                mastery_score, row.stability or 1.0, row.successful_reviews or 0,
                row.review_count or 0, row.needs_relearn)
            if row.next_review_at is None:
                row.next_review_at = now + timedelta(days=interval.initial_interval_days())

        risk = forgetting.calculate_forgetting_risk(row, now=now)
        row.forgetting_risk = risk["risk"]
        row.memory_strength = memory.memory_strength_of(
            row.mastery_score, row.stability or 1.0, row.forgetting_risk)

        db.flush()
        return row

    def refresh_risks(self, db, student_id, rows=None, now=None, force=False):
        """增量刷新遗忘风险（只写变化明显的记录）。"""
        now = now or datetime.now()
        rows = rows if rows is not None else self.states_of(db, student_id)
        changed = 0

        for row in rows:
            result = forgetting.calculate_forgetting_risk(row, now=now)
            risk = result["risk"]
            due = isinstance(row.next_review_at, datetime) and row.next_review_at <= now
            if force or due or abs(risk - float(row.forgetting_risk or 0)) >= RISK_REFRESH_DELTA:
                row.forgetting_risk = risk
                row.memory_strength = memory.memory_strength_of(
                    row.mastery_score, row.stability or 1.0, risk)
                changed += 1

        if changed:
            db.commit()
        return changed

    # ---------------- 今日队列 ----------------

    def queue_for(self, db, student_id, day=None, refresh=False, now=None):
        """当天复习队列（按天缓存；refresh=True 重新调度未完成的部分）。"""
        now = now or datetime.now()
        start = day_start(day or now)
        end = start + timedelta(days=1)

        rows = db.query(ReviewQueue).filter(
            ReviewQueue.student_id == student_id,
            ReviewQueue.scheduled_at >= start,
            ReviewQueue.scheduled_at < end,
        ).order_by(ReviewQueue.id.asc()).all()

        if rows and not refresh:
            return rows

        states = self.states_of(db, student_id)
        self.refresh_risks(db, student_id, states, now=now)
        built = self.schedule(db, student_id, states, now=now)
        return built["rows"]

    def schedule(self, db, student_id, states=None, now=None, replace=True):
        """重新排今天的复习队列（把结果写进 review_queue）。"""
        from adaptive import strategy as strategy_module

        now = now or datetime.now()
        start = day_start(now)
        states = states if states is not None else self.states_of(db, student_id)
        state_map = {(row.subject, row.knowledge_id): row for row in states}

        built = scheduler.build_queue(
            states, now=now,
            foundation_of=strategy_module.foundation_weight)

        existing = {
            (row.scheduled_at.date(), row.subject, row.knowledge_id): row
            for row in db.query(ReviewQueue).filter(
                ReviewQueue.student_id == student_id,
                ReviewQueue.scheduled_at >= start).all()
        }

        rows = []
        for item in built["items"]:
            key = (start.date(), item["subject"], item["knowledge_id"])
            row = existing.get(key)
            if row is None:
                row = ReviewQueue(
                    student_id=student_id,
                    subject=item["subject"],
                    knowledge_id=item["knowledge_id"],
                    scheduled_at=start,
                    priority=item["priority"],
                    risk=item["risk"],
                    target_count=item["target_count"],
                    status="PENDING",
                    reason=item["reason"],
                    created_time=now,
                )
                db.add(row)
                db.flush()
            elif row.status == "SKIPPED":
                continue
            rows.append(row)

        # 长期没登录：把顺延的任务摊到后面几天，每天不超过上限
        for index, item in enumerate(built["deferred"]):
            offset = 1 + index // max(1, scheduler.MAX_PER_DAY)
            planned = start + timedelta(days=offset)
            key = (planned.date(), item["subject"], item["knowledge_id"])
            if key in existing:
                continue
            row = ReviewQueue(
                student_id=student_id, subject=item["subject"],
                knowledge_id=item["knowledge_id"], scheduled_at=planned,
                priority=item["priority"], risk=item["risk"],
                target_count=item["target_count"], status="PENDING",
                reason=item["reason"] + "（上次没排上，顺延）", created_time=now)
            db.add(row)
            existing[key] = row

        db.commit()
        self.log_strategy(db, student_id, "", "", old_interval=0, new_interval=0,
                          quality="", source="queue",
                          reason=(f"排今日复习队列：{len(rows)} 个知识点"
                                  f"（{built['summary']['questions']} 题），"
                                  f"顺延 {built['deferred_count']} 个"))
        return {"rows": rows, "built": built, "state_map": state_map}

    def today(self, db, student_id, refresh=False, now=None):
        """今日复习任务（儿童端 + 家长端共用）。"""
        now = now or datetime.now()
        rows = self.queue_for(db, student_id, now=now, refresh=refresh)
        items = []
        relearn = []

        for row in rows:
            if (row.status or "") == "SKIPPED":
                continue
            state = self.state_row(db, student_id, row.subject, row.knowledge_id)
            summary = memory.state_summary(state, now=now)
            if summary["needs_relearn"]:
                continue

            items.append(dict(summary, **{
                "queue_id": row.id,
                "priority": row.priority,
                "priority_text": scheduler.PRIORITY_TEXT.get(row.priority, ""),
                "target_count": int(row.target_count or 1),
                "completed_count": int(row.completed_count or 0),
                "status": row.status or "PENDING",
                "queue_reason": row.reason or "",
                "scheduled_date": row.scheduled_at.strftime("%Y-%m-%d") if row.scheduled_at else "",
            }))

        # 需要重学的知识点不会进复习队列，直接从记忆状态里挑出来
        # （mastery < 60 或连续复习失败 → 交给自适应引擎重新学）
        for state in self.states_of(db, student_id):
            summary = memory.state_summary(state, now=now)
            if not summary["needs_relearn"]:
                continue
            relearn.append({
                "subject": summary["subject"],
                "knowledge_id": summary["knowledge_id"],
                "mastery_score": summary["mastery_score"],
                "reason": f"掌握度 {summary['mastery_score']}，先重新学会再来复习",
            })

        total = len(items)
        done = sum(1 for item in items if item["status"] in ("COMPLETED", "SKIPPED"))
        remaining = total - done

        return {
            "student_id": student_id,
            "date": now.strftime("%Y-%m-%d"),
            "items": items,
            "relearn": relearn,
            "total": total,
            "completed": done,
            "remaining": remaining,
            "child_title": self._child_title(remaining, total),
            "child_message": (CHILD_DONE_TEXT if total and remaining == 0
                              else self._child_title(remaining, total)),
            "by_priority": {key: sum(1 for item in items if item["priority"] == key)
                            for key in scheduler.PRIORITY_ORDER},
            "planned_questions": sum(item["target_count"] for item in items),
            "updated_time": now.strftime("%Y-%m-%d %H:%M"),
        }

    @staticmethod
    def _child_title(remaining, total):
        if total <= 0:
            return CHILD_EMPTY_TEXT
        if remaining <= 0:
            return CHILD_DONE_TEXT
        return f"今天有 {remaining} 个知识需要浇水"

    def due(self, db, student_id, now=None, limit=100):
        """所有到期 / 高风险知识点（家长端与调试用）。"""
        now = now or datetime.now()
        states = self.states_of(db, student_id)
        self.refresh_risks(db, student_id, states, now=now)

        items = []
        for row in states:
            summary = memory.state_summary(row, now=now)
            if summary["needs_relearn"]:
                summary["action"] = "RELEARN"
            if summary["overdue"] or summary["forgetting_risk"] >= scheduler.HIGH_RISK:
                items.append(summary)

        items.sort(key=lambda item: (-item["forgetting_risk"], item["next_review_at"]))
        return {
            "student_id": student_id,
            "date": now.strftime("%Y-%m-%d"),
            "total": len(items),
            "items": items[:max(1, int(limit))],
        }

    # ---------------- 复习出题 ----------------

    def review_question(self, db, student_id, subject, knowledge, difficulty=None,
                        use_ai=False, rng=None, now=None):
        """生成一道复习题（保证与历史原题不同）并落库。"""
        now = now or datetime.now()
        state = self.state_row(db, student_id, subject, knowledge)
        student = db.query(Student).filter(Student.id == student_id).first()
        grade = grade_text(student.grade if student else 3)

        if difficulty is None:
            stage_key = (knowledge_tree.stage_of_any(subject, knowledge)
                         or stages.key_of_difficulty(state.mastery_score or DEFAULT_DIFFICULTY))
            base = stages.difficulty_of(stage_key)
            difficulty = int(round(0.5 * float(state.mastery_score or base) + 0.5 * base))
        difficulty = int(max(1, min(100, int(difficulty))))

        data = selector.DEFAULT_SELECTOR.build(
            db, student_id, subject, knowledge, difficulty=difficulty,
            maturity_level=state.maturity_level or "LEARNING", rng=rng, use_ai=use_ai,
            grade=grade)

        row = Question(
            subject=subject,
            grade=student.grade if student and isinstance(student.grade, int) else 3,
            knowledge=knowledge,
            difficulty=difficulty,
            question=data["question"],
            answer=data["answer"],
            qtype=data["qtype"],
            options=_json_dumps(data.get("options") or {}),
            acceptable=_json_dumps(data.get("acceptable") or []),
            analysis=data.get("analysis") or "",
        )
        db.add(row)
        db.flush()

        self._mark_queue(db, student_id, subject, knowledge, status="IN_PROGRESS", now=now)
        db.commit()

        return {
            "student_id": student_id,
            "subject": subject,
            "knowledge": knowledge,
            "question_id": row.id,
            "qtype": row.qtype,
            "question": row.question,
            "options": data.get("options") or {},
            "difficulty": difficulty,
            "mode": data.get("mode"),
            "mode_text": data.get("mode_text"),
            "source": data.get("source"),
            "repeated": bool(data.get("repeated")),
            "expected_seconds": float(data.get("expected_seconds") or selector.EXPECTED_SECONDS),
            "memory": memory.state_summary(state, now=now),
        }

    # ---------------- 复习作答 ----------------

    def submit_review(self, db, student_id, payload, now=None):
        """提交复习答案：判分 → 复习质量 → 新间隔 / 新稳定性 / 新成熟度。"""
        from knowledge_routes import update_mastery

        now = now or datetime.now()
        payload = payload or {}
        question_id = int(payload.get("question_id") or 0)

        row = db.query(Question).filter(Question.id == question_id).first()
        if row is None:
            return None

        subject = row.subject or "数学"
        knowledge = row.knowledge or ""
        answer = str(payload.get("answer") or "")
        response_time = float(payload.get("response_time") or 0)
        feedback = str(payload.get("difficulty_feedback") or payload.get("feel") or "").strip().lower()
        confidence_feedback = FEEL_TO_FEEDBACK.get(feedback, feedback)

        correct = grading.is_correct(row, answer)
        state = self.state_row(db, student_id, subject, knowledge)
        expected_time = float(payload.get("expected_time") or selector.EXPECTED_SECONDS)

        quality = interval.quality_of(correct, response_time, expected_time,
                                     confidence_feedback)
        previous_interval = float(state.current_interval_days or interval.MIN_INTERVAL)
        previous_stability = float(state.stability or 1.0)
        previous_maturity = state.maturity_level or "NEW"

        # 1) 先按主流程记录答题与掌握度，保证与日常练习完全一致
        record = AnswerRecord(
            student_id=student_id, subject=subject, knowledge=knowledge,
            difficulty=row.difficulty, correct=correct, question_id=row.id,
            submitted=answer, created_at=now)
        db.add(record)
        db.flush()

        if correct:
            wrong_book.record_correct(db, student_id, row)
        else:
            error_info = error_analysis.analyze(db, student_id, row, answer,
                                                answer_record_id=record.id, use_ai=False)
            wrong_book.record_wrong(db, student_id, row, error_info["error_type"])

        mastery_row = update_mastery(db, student_id, subject, knowledge,
                                     stage=stages.key_of_difficulty(row.difficulty),
                                     when=now)
        mastery_score = int(mastery_row.mastery_score if mastery_row else state.mastery_score or 0)

        # 2) 更新记忆状态（间隔 / 稳定性 / 成熟度 / 风险）
        result = interval.calculate_next_interval(
            current_interval=previous_interval,
            mastery_score=mastery_score,
            stability=previous_stability,
            difficulty=float(state.difficulty or 0.5),
            review_result=quality,
            response_time=response_time,
            confidence_feedback=confidence_feedback,
            successful_reviews=int(state.successful_reviews or 0),
            expected_time=expected_time,
            confidence=float(state.confidence or 0) or 1.0,
            maturity_level=previous_maturity,
            now=now,
        )

        state.mastery_score = mastery_score
        state.review_count = int(state.review_count or 0) + 1
        if correct:
            state.successful_reviews = int(state.successful_reviews or 0) + 1
            state.review_streak = int(state.review_streak or 0) + 1
            state.consecutive_failures = 0
        else:
            state.failed_reviews = int(state.failed_reviews or 0) + 1
            state.consecutive_failures = int(state.consecutive_failures or 0) + 1
            state.review_streak = 0
        state.last_reviewed_at = now
        state.current_interval_days = result["next_interval"]
        state.stability = result["new_stability"]
        state.next_review_at = result["next_review_at"]
        state.difficulty = memory.personal_difficulty(
            mastery_score, state.failed_reviews, state.successful_reviews, correct)
        state.confidence = float(mastery_row.confidence if mastery_row else state.confidence or 0)
        state.needs_relearn = memory.needs_relearn(mastery_score,
                                                   state.consecutive_failures)
        state.maturity_level = memory.maturity_of(
            mastery_score, state.stability, state.successful_reviews,
            state.review_count, state.needs_relearn)
        risk = forgetting.calculate_forgetting_risk(state, now=now)
        state.forgetting_risk = risk["risk"]
        state.memory_strength = memory.memory_strength_of(
            mastery_score, state.stability, state.forgetting_risk)

        if state.needs_relearn:
            state.current_interval_days = 1.0
            state.next_review_at = now

        # 3) 复习明细 + 策略日志
        detail = ReviewRecord(
            student_id=student_id, subject=subject, knowledge_id=knowledge,
            question_id=row.id, reviewed_at=now, correct=correct,
            review_quality=quality, response_time=response_time,
            expected_time=expected_time, previous_interval=previous_interval,
            next_interval=result["next_interval"],
            previous_stability=previous_stability, new_stability=result["new_stability"],
            memory_strength=state.memory_strength, forgetting_risk=state.forgetting_risk,
            maturity_level=state.maturity_level, reason=result["reason"], created_time=now)
        db.add(detail)

        reason = result["reason"]
        if state.needs_relearn:
            reason += "；已确认遗忘，转为重新学习（RELEARN）"
        self.log_strategy(db, student_id, subject, knowledge,
                          old_interval=previous_interval,
                          new_interval=result["next_interval"],
                          old_stability=previous_stability,
                          new_stability=result["new_stability"],
                          old_maturity=previous_maturity,
                          new_maturity=state.maturity_level,
                          quality=quality, source="review", reason=reason)

        # 4) 推进队列
        queue_row = self._mark_queue(db, student_id, subject, knowledge,
                                     status=None, now=now, advance=True)
        db.commit()

        # 5) 长期掌握的知识偶尔错一题 → 追加验证题，不直接推翻结论
        need_verify = (not correct) and previous_maturity in VERIFY_EXTRA_LINE \
            and int(state.consecutive_failures or 0) < 2

        child_message = self._child_message(correct, quality, previous_maturity,
                                            state.maturity_level, need_verify)

        return {
            "student_id": student_id,
            "subject": subject,
            "knowledge": knowledge,
            "question_id": row.id,
            "correct": correct,
            "correct_answer": row.answer,
            "analysis": row.analysis or "",
            "review_quality": quality,
            "review_quality_text": interval.QUALITY_TEXT.get(quality, ""),
            "response_time": response_time,
            "previous_interval": previous_interval,
            "next_interval": result["next_interval"],
            "previous_stability": round(previous_stability, 2),
            "new_stability": round(result["new_stability"], 2),
            "memory_strength": state.memory_strength,
            "forgetting_risk": round(float(state.forgetting_risk or 0), 3),
            "maturity_level": state.maturity_level,
            "maturity_text": memory.MATURITY_TEXT.get(state.maturity_level, ""),
            "maturity_child": memory.MATURITY_CHILD.get(state.maturity_level, ""),
            "maturity_upgraded": (memory.MATURITY_LEVELS.index(state.maturity_level)
                                  > memory.MATURITY_LEVELS.index(previous_maturity)
                                  if previous_maturity in memory.MATURITY_LEVELS else False),
            "next_review_at": _fmt(state.next_review_at),
            "next_review_date": state.next_review_at.strftime("%Y-%m-%d")
            if state.next_review_at else "",
            "action": "RELEARN" if state.needs_relearn else "REVIEW",
            "need_verify": need_verify,
            "reason": reason,
            "child_message": child_message,
            "queue": {
                "id": queue_row.id if queue_row else 0,
                "completed_count": int(queue_row.completed_count or 0) if queue_row else 0,
                "target_count": int(queue_row.target_count or 0) if queue_row else 0,
                "status": queue_row.status if queue_row else "",
            },
            "wrong_book": wrong_book.stats_for(db, student_id, subject=subject),
        }

    @staticmethod
    def _child_message(correct, quality, previous_maturity, maturity, need_verify):
        if not correct:
            if need_verify:
                return "别急，再来一道同类题验证一下，很可能只是这次没看清题目～"
            return "这个知识有点忘了，没关系，我们把它重新种一遍！"
        if quality == "EASY":
            return "太厉害了，记得非常牢！下次复习会晚一点再来找你～"
        if maturity and previous_maturity and \
                memory.MATURITY_LEVELS.index(maturity) > memory.MATURITY_LEVELS.index(previous_maturity):
            return "你已经记得更牢了！"
        return "复习成功，记忆又结实了一点～"

    def _mark_queue(self, db, student_id, subject, knowledge, status=None, now=None,
                    advance=False):
        """找到今天这一条队列项，推进状态 / 完成数。"""
        now = now or datetime.now()
        start = day_start(now)
        row = db.query(ReviewQueue).filter(
            ReviewQueue.student_id == student_id,
            ReviewQueue.subject == subject,
            ReviewQueue.knowledge_id == knowledge,
            ReviewQueue.scheduled_at >= start,
            ReviewQueue.scheduled_at < start + timedelta(days=1),
        ).order_by(ReviewQueue.id.desc()).first()

        if row is None:
            return None

        if advance:
            row.completed_count = int(row.completed_count or 0) + 1
            if row.completed_count >= int(row.target_count or 1):
                row.status = "COMPLETED"
            else:
                row.status = "IN_PROGRESS"
        elif status:
            row.status = status

        row.updated_time = now
        return row

    def skip(self, db, student_id, queue_id, now=None):
        """孩子跳过某个复习任务（不惩罚，只是今天不复习它）。"""
        now = now or datetime.now()
        row = db.query(ReviewQueue).filter(
            ReviewQueue.id == int(queue_id),
            ReviewQueue.student_id == student_id,
        ).first()
        if row is None:
            return None

        row.status = "SKIPPED"
        row.updated_time = now
        self.log_strategy(db, student_id, row.subject, row.knowledge_id,
                          old_interval=0, new_interval=0, quality="SKIP",
                          source="queue", reason="孩子跳过了这次复习")
        db.commit()
        return {"queue_id": row.id, "status": row.status}

    def apply_feedback(self, db, student_id, payload, now=None):
        """孩子对复习题的主观感受（简单 / 有点难 / 不会）跟着调一次间隔。

        只做 ±5% 的轻微修正：主观感受有权重，但不能盖过客观表现。
        """
        now = now or datetime.now()
        payload = payload or {}
        question_id = int(payload.get("question_id") or 0)
        feel = str(payload.get("feel") or payload.get("difficulty_feedback") or "").strip().lower()
        if not question_id or not feel:
            return None

        record = db.query(ReviewRecord).filter(
            ReviewRecord.student_id == student_id,
            ReviewRecord.question_id == question_id,
        ).order_by(ReviewRecord.id.desc()).first()
        if record is None:
            return None

        state = self.state_row(db, student_id, record.subject, record.knowledge_id)
        factor = interval.feedback_factor(feel)
        old_interval = float(state.current_interval_days or interval.MIN_INTERVAL)
        adjusted = interval.round_half_up(interval.clamp_f(
            old_interval * (1.0 + (factor - 1.0) * 0.5),
            interval.MIN_INTERVAL, interval.MAX_INTERVAL))

        base = state.last_reviewed_at or now
        state.current_interval_days = adjusted
        state.next_review_at = base + timedelta(days=adjusted)
        state.maturity_level = memory.maturity_of(
            state.mastery_score, state.stability or 1.0, state.successful_reviews or 0,
            state.review_count or 0, bool(state.needs_relearn))
        risk = forgetting.calculate_forgetting_risk(state, now=now)
        state.forgetting_risk = risk["risk"]
        state.memory_strength = memory.memory_strength_of(
            state.mastery_score, state.stability or 1.0, state.forgetting_risk)
        state.updated_at = now

        self.log_strategy(db, student_id, record.subject, record.knowledge_id,
                          old_interval=old_interval, new_interval=adjusted,
                          old_stability=state.stability, new_stability=state.stability,
                          quality=str(feel).upper(), source="feedback",
                          reason=(f"孩子反馈「{interval.QUALITY_TEXT.get(str(feel).upper(), feel)}」，"
                                  f"间隔 {old_interval:g} → {adjusted:g} 天"))
        db.commit()

        return {
            "saved": True,
            "question_id": question_id,
            "subject": record.subject,
            "knowledge": record.knowledge_id,
            "feel": feel,
            "old_interval": old_interval,
            "next_interval": adjusted,
            "next_review_at": _fmt(state.next_review_at),
            "memory": memory.state_summary(state, now=now) if state else None,
        }

    # ---------------- 统计 / 地图 / 日志 ----------------

    def memory_map(self, db, student_id, subject=None, now=None):
        """各知识点的记忆状态（家长端 / 调试页）。"""
        now = now or datetime.now()
        rows = self.states_of(db, student_id, subject)
        self.refresh_risks(db, student_id, rows, now=now)

        items = [memory.state_summary(row, now=now) for row in rows]
        items.sort(key=lambda item: (-item["forgetting_risk"], item["knowledge_id"]))

        by_maturity = {level: 0 for level in memory.MATURITY_LEVELS}
        for item in items:
            by_maturity[item["maturity_level"]] = by_maturity.get(item["maturity_level"], 0) + 1

        strengths = [item["memory_strength"] for item in items]
        stabilities = [item["stability"] for item in items]

        return {
            "student_id": student_id,
            "subject": subject or "",
            "date": now.strftime("%Y-%m-%d"),
            "total": len(items),
            "items": items,
            "summary": {
                "by_maturity": by_maturity,
                "maturity_text": memory.MATURITY_TEXT,
                "maturity_child": memory.MATURITY_CHILD,
                "forest": memory.MATURITY_FOREST,
                "average_memory_strength": int(round(sum(strengths) / len(strengths)))
                if strengths else 0,
                "average_stability": round(sum(stabilities) / len(stabilities), 2)
                if stabilities else 0,
                "high_risk": sum(1 for item in items
                                 if item["forgetting_risk"] >= scheduler.HIGH_RISK),
                "due": sum(1 for item in items if item["overdue"]),
                "relearn": sum(1 for item in items if item["needs_relearn"]),
            },
        }

    def stats(self, db, student_id, now=None):
        """今日复习数量 / 完成数量 / 即将遗忘数量 / 长期掌握数量。"""
        now = now or datetime.now()
        today = self.today(db, student_id, now=now)
        states = self.states_of(db, student_id)
        self.refresh_risks(db, student_id, states, now=now)

        counts = {level: 0 for level in memory.MATURITY_LEVELS}
        for row in states:
            level = row.maturity_level or "NEW"
            counts[level] = counts.get(level, 0) + 1

        return {
            "student_id": student_id,
            "date": now.strftime("%Y-%m-%d"),
            "due_count": today["total"],
            "completed_count": today["completed"],
            "remaining_count": today["remaining"],
            "planned_questions": today["planned_questions"],
            "high_risk_count": sum(1 for row in states
                                   if float(row.forgetting_risk or 0) >= scheduler.HIGH_RISK),
            "relearn_count": sum(1 for row in states if row.needs_relearn),
            "long_term_count": counts.get("LONG_TERM", 0),
            "stable_count": counts.get("STABLE", 0),
            "consolidating_count": counts.get("CONSOLIDATING", 0),
            "learning_count": counts.get("LEARNING", 0) + counts.get("NEW", 0),
            "total_knowledge": len(states),
            "by_maturity": counts,
            "child_message": today["child_message"],
            "today": today,
        }

    def mix_for(self, db, student_id, now=None):
        """计算今天的学习内容配比（给自适应引擎的计划用）。"""
        now = now or datetime.now()
        today = self.today(db, student_id, now=now)
        risks = [item["forgetting_risk"] for item in today["items"]]
        average_risk = sum(risks) / len(risks) if risks else 0.0
        high_risk = sum(1 for item in today["items"]
                        if item["forgetting_risk"] >= scheduler.HIGH_RISK)

        return mix.calculate_daily_mix(
            review_due=today["total"],
            high_risk=high_risk,
            average_risk=average_risk,
            relearn_count=len(today["relearn"]),
        )

    def log_strategy(self, db, student_id, subject, knowledge, old_interval=0,
                     new_interval=0, old_stability=0, new_stability=0, quality="",
                     reason="", source="review", old_maturity=None, new_maturity=None):
        """写一条复习策略日志（每次改复习日期都要能解释原因）。"""
        row = ReviewStrategyLog(
            student_id=student_id, subject=subject, knowledge_id=knowledge,
            old_interval=round(float(old_interval or 0), 2),
            new_interval=round(float(new_interval or 0), 2),
            old_stability=round(float(old_stability or 0), 2),
            new_stability=round(float(new_stability or 0), 2),
            old_maturity=old_maturity, new_maturity=new_maturity,
            quality=quality, reason=reason, source=source, created_time=datetime.now())
        db.add(row)
        db.flush()
        return row.id

    def strategy_logs(self, db, student_id, limit=20):
        rows = db.query(ReviewStrategyLog).filter(
            ReviewStrategyLog.student_id == student_id,
        ).order_by(ReviewStrategyLog.id.desc()).limit(max(1, int(limit))).all()

        return [
            {
                "id": row.id,
                "subject": row.subject,
                "knowledge": row.knowledge_id,
                "old_interval": row.old_interval,
                "new_interval": row.new_interval,
                "old_stability": row.old_stability,
                "new_stability": row.new_stability,
                "old_maturity": row.old_maturity,
                "new_maturity": row.new_maturity,
                "quality": row.quality,
                "reason": row.reason,
                "source": row.source,
                "created_time": _fmt(row.created_time),
            }
            for row in rows
        ]

    def review_history(self, db, student_id, subject=None, knowledge=None, limit=20):
        query = db.query(ReviewRecord).filter(ReviewRecord.student_id == student_id)
        if subject:
            query = query.filter(ReviewRecord.subject == subject)
        if knowledge:
            query = query.filter(ReviewRecord.knowledge_id == knowledge)

        rows = query.order_by(ReviewRecord.id.desc()).limit(max(1, int(limit))).all()
        counter = {}
        for row in rows:
            counter[row.review_quality] = counter.get(row.review_quality, 0) + 1

        return {
            "total": len(rows),
            "by_quality": counter,
            "items": [
                {
                    "id": row.id, "subject": row.subject, "knowledge": row.knowledge_id,
                    "correct": row.correct, "review_quality": row.review_quality,
                    "response_time": row.response_time,
                    "previous_interval": row.previous_interval,
                    "next_interval": row.next_interval,
                    "previous_stability": row.previous_stability,
                    "new_stability": row.new_stability,
                    "maturity_level": row.maturity_level,
                    "reason": row.reason,
                    "reviewed_at": _fmt(row.reviewed_at),
                }
                for row in rows
            ],
        }


DEFAULT_ENGINE = ReviewEngine()
