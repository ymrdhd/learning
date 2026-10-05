# ==============================================================
# 能力契约｜康复队列与到期调度：错题入队（幂等）、VERIFYING 到期、状态汇总
# 入口：RecoveryScheduler（enqueue / due_verify / apply_overdue / summarize）/ DEFAULT_SCHEDULER
# 依赖：models、recovery.state
# 不负责：状态机规则 → recovery/state.py；判分与门面 → recovery/engine.py
# 验证：python backend/verify_recovery.py（Agent 7 门禁）
# 被调用：recovery/engine.py、recovery_routes.py、main.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复队列调度。

- ``enqueue``：把 ``wrong_questions`` 里状态是 NEW / LEARNING 的题补进
  ``wrong_question_recovery``（靠 ``ix_recovery_unique(student_id, question_id)`` 保证不重复），
  同一道题重复调用只入队一次 —— 幂等。
- ``due_verify``：VERIFYING 且已经到期（``next_verify_time <= now``，或为空）的康复项。
- ``apply_overdue``：把到期未验证的项按状态机回落 PRACTICING（SPEC §4「超时未验证」）。
- ``summarize``：各状态计数 + total + mastered_rate（字段名与 API 契约 §7.1 一致）。
"""

from datetime import datetime

from models import WrongQuestion, WrongQuestionRecovery
from recovery.state import (
    EVENT_VERIFY_TIMEOUT, MASTERED, NEW, PRACTICING, RecoveryState, VERIFYING, normalize,
    transition,
)

ENQUEUE_STATES = (NEW, "LEARNING")
LOWER_ORDER = tuple(name.lower() for name in RecoveryState.ORDER)


def _as_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


class RecoveryScheduler:
    """康复队列（入队 / 到期 / 汇总）。只由 engine 调用，路由不直接碰表。"""

    def enqueue(self, db, student_id, limit=20):
        """把尚未进队列的 NEW/LEARNING 错题补进康复队列，返回**本次新建**的行列表（幂等）。"""
        limit = max(0, _as_int(limit, 20))
        if not limit or not student_id:
            return []

        candidates = db.query(WrongQuestion).filter(
            WrongQuestion.student_id == student_id,
            WrongQuestion.status.in_(ENQUEUE_STATES),
        ).order_by(WrongQuestion.id.asc()).all()

        existing = {
            _as_int(question_id)
            for (question_id,) in db.query(WrongQuestionRecovery.question_id).filter(
                WrongQuestionRecovery.student_id == student_id)
        }
        now = datetime.now()
        created = []
        for wrong in candidates:
            question_id = _as_int(getattr(wrong, "question_id", 0))
            if not question_id or question_id in existing:
                continue
            row = WrongQuestionRecovery(
                student_id=student_id,
                subject=str(getattr(wrong, "subject", "") or ""),
                knowledge_id=str(getattr(wrong, "knowledge_id", "") or ""),
                question_id=question_id,
                wrong_question_id=_as_int(getattr(wrong, "id", 0)),
                state=NEW,
                state_before="",
                attempts=0,
                correct_count=0,
                consecutive_correct=0,
                fail_count=0,
                max_level_used=0,
                variant_count=0,
                source="wrong_book",
                last_state_change=now,
                created_time=now,
                updated_time=now,
            )
            db.add(row)
            existing.add(question_id)
            created.append(row)
            if len(created) >= limit:
                break

        if created:
            try:
                db.flush()
                db.commit()
            except Exception:                      # 并发下唯一索引冲突：回滚后按库内实况返回
                db.rollback()
                question_ids = [_as_int(row.question_id) for row in created]
                return db.query(WrongQuestionRecovery).filter(
                    WrongQuestionRecovery.student_id == student_id,
                    WrongQuestionRecovery.question_id.in_(question_ids),
                ).order_by(WrongQuestionRecovery.id.asc()).all()
        return created

    def due_verify(self, db, student_id, now=None):
        """VERIFYING 且到期的康复项（``next_verify_time`` 为空视为已到期）。"""
        moment = now or datetime.now()
        rows = db.query(WrongQuestionRecovery).filter(
            WrongQuestionRecovery.student_id == student_id,
            WrongQuestionRecovery.state == VERIFYING,
        ).order_by(WrongQuestionRecovery.id.asc()).all()
        return [row for row in rows
                if row.next_verify_time is None or row.next_verify_time <= moment]

    def apply_overdue(self, db, student_id, now=None):
        """到期未验证 → 回落 PRACTICING（超时未过），返回被处理的康复项列表。"""
        rows = self.due_verify(db, student_id, now=now)
        if not rows:
            return []
        moment = now or datetime.now()
        for row in rows:
            result = transition(row.state, EVENT_VERIFY_TIMEOUT,
                                consecutive_correct=_as_int(row.consecutive_correct),
                                fail_count=_as_int(row.fail_count))
            if result.get("changed"):
                row.state_before = result.get("state_before") or normalize(row.state)
                row.state = result["next_state"]
                row.last_state_change = moment
            row.consecutive_correct = result["consecutive_correct"]
            row.fail_count = result["fail_count"]
            if row.state != VERIFYING:
                row.next_verify_time = None
            row.updated_time = moment
        db.commit()
        return rows

    def summarize(self, rows):
        """各状态计数 + total + mastered_rate（键名与 §7.1 的 stats 一致）。"""
        counts = {name: 0 for name in LOWER_ORDER}
        total = 0
        for row in rows or []:
            name = normalize(getattr(row, "state", "")).lower()
            counts[name] = counts.get(name, 0) + 1
            total += 1
        for name in LOWER_ORDER:
            counts.setdefault(name, 0)
        mastered = counts.get(MASTERED.lower(), 0)
        summary = {name: counts.get(name, 0) for name in LOWER_ORDER}
        summary["total"] = total
        summary["mastered_rate"] = round(mastered / total, 4) if total else 0.0
        return summary


DEFAULT_SCHEDULER = RecoveryScheduler()
