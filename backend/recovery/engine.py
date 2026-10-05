# ==============================================================
# 能力契约｜错题康复门面：入队、开始教学、出题、判分推进、原题验证、统计（唯一碰库的康复模块）
# 入口：RecoveryEngine（list_items / start / hint / next_question / answer / verify / sync_from_wrong_book / stats / detail）/ DEFAULT_ENGINE
# 依赖：grading、models、recovery.state、recovery.strategy、recovery.scheduler、ai_recovery（函数内延迟导入）
# 不负责：状态机规则 → recovery/state.py；策略与提示层级 → recovery/strategy.py；队列与到期 → recovery/scheduler.py
# 验证：python backend/verify_recovery.py（Agent 7 门禁）
# 被调用：recovery_routes.py、main.py（/submit 的 sync_from_wrong_book 钩子）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复系统 · RecoveryEngine（唯一碰 ``wrong_question_recovery`` 的数据库门面）。

闭环：

```text
wrong_questions（NEW/LEARNING）
  → enqueue：补进 wrong_question_recovery（幂等，唯一索引 student_id+question_id）
  → start：NEW → ANALYZING → LEARNING（分层提示 Level1）
  → next_question：变式题（ai_recovery.VariantQuestionGenerator，失败降级同知识点题）
  → answer：grading.is_correct 判分 → 状态机推进（连对 2 → VERIFYING，连错 2 → NEW）
  → verify：VERIFYING 原题答对 → MASTERED（写 mastered_time）
  → stats / detail：康复看板
```

设计要点：

1. 判分唯一真相是 ``grading.is_correct``，与 ``main.submit`` 同源；本模块不写第二套判分。
2. AI 只经 ``ai_recovery``，**函数内延迟 import + try/except**：Agent 3 未就绪或离线时直接降级，
   提示文案用规则兜底，绝不抛异常。
3. ``sync_from_wrong_book`` 是 ``main.submit`` 的钩子：内部全量 try/except，只记日志、
   出错回滚，**绝不影响判分返回**。
4. 所有查询都按 ``student_id`` 过滤（学生 A=1 / 学生 B=2 完全隔离）。
"""

from datetime import datetime, timedelta

import grading
from models import AnswerRecord, Question, WrongQuestion, WrongQuestionRecovery
from recovery.scheduler import DEFAULT_SCHEDULER
from recovery.state import (
    EVENT_ANALYZE, EVENT_HINT, EVENT_RELEARN, MASTERED, NEW,
    RecoveryState, apply_result, is_active, next_action, transition,
)
from recovery.strategy import DEFAULT_STRATEGY

STATE_TEXT = RecoveryState.TEXT
VERIFY_DAYS = 1
TIME_FMT = "%Y-%m-%d %H:%M"
FALLBACK_HINTS = {
    1: "先想想这道题在考什么，把题目里最重要的条件圈出来。",
    2: "再看一眼你出错的那一步，是不是算错了、或者看漏了条件？",
    3: "我们一步一步来：先理清条件，再列式，最后算结果。",
    4: "完整讲解：看一遍标准做法，再自己把思路讲一遍。",
}
LEVEL_TEXTS = {1: "方向提示", 2: "错误定位", 3: "步骤引导", 4: "完整讲解"}


def _as_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


def _fmt(moment):
    return moment.strftime(TIME_FMT) if isinstance(moment, datetime) else ""


def _options_json(value):
    import json

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.strip():
        return value
    return ""


class RecoveryEngine:
    """错题康复门面（唯一碰库）：列表 / 教学 / 出题 / 判分 / 验证 / 统计。"""

    def __init__(self):
        self._last_question = {}

    # ---------------- 读 ----------------
    def list_items(self, db, student_id, subject=None, state=None, limit=50):
        """康复列表：``{student_id, total, stats, items}``（stats 覆盖该学生全部康复项）。"""
        rows = self._query(db, student_id)
        picked = [row for row in rows
                  if (not subject or row.subject == subject)
                  and (not state or str(row.state or "").upper() == str(state).upper())]
        limit = max(0, _as_int(limit, 50))
        items = [self._item(db, row) for row in picked[:limit]]
        return {
            "student_id": student_id,
            "total": len(items),
            "stats": DEFAULT_SCHEDULER.summarize(rows),
            "items": items,
        }

    def stats(self, db, student_id):
        """各状态计数 + total + mastered_rate（字段名同 §7.1 stats）。"""
        return DEFAULT_SCHEDULER.summarize(self._query(db, student_id))

    def detail(self, db, student_id, recovery_id):
        """单个康复项详情（列表字段 + plan + history）；不属于该学生返回 None。"""
        row = self._row(db, student_id, recovery_id)
        if row is None:
            return None
        item = self._item(db, row)
        item["state_before"] = row.state_before or ""
        item["active"] = is_active(row.state)
        item["plan"] = DEFAULT_STRATEGY.plan(row)
        item["history"] = self._history(db, student_id, row)
        return item

    # ---------------- 教学 ----------------
    def start(self, db, student_id, recovery_id):
        """开始康复教学：NEW → ANALYZING → LEARNING，返回 ``item + teaching``。"""
        row = self._prepared(db, student_id, recovery_id)
        if row is None:
            return None
        question = self._question(db, row.question_id)
        teaching = self._teach(question, 1, error_type=self._error_type(db, row))
        now = datetime.now()
        if str(row.state or "").upper() in (NEW, "ANALYZING", "LEARNING"):
            self._move(row, EVENT_ANALYZE, level=1, now=now)
            self._move(row, EVENT_HINT, level=1, now=now)
            db.commit()
        return {
            "recovery_id": row.id,
            "question_id": row.question_id,
            "state": row.state,
            "state_text": STATE_TEXT.get(row.state, ""),
            "teaching": teaching,
            "item": self._item(db, row),
        }

    def hint(self, db, student_id, recovery_id, level=None):
        """取第 ``level`` 级提示（不推进状态，只更新已用最高层级）。"""
        row = self._row(db, student_id, recovery_id)
        if row is None:
            return None
        plan = DEFAULT_STRATEGY.plan(row, hint_level=level or 0)
        chosen = _clamp(_as_int(level, 0) or _as_int(plan.get("hint_level"), 1), 1, 4)
        question = self._question(db, row.question_id)
        teaching = self._teach(question, chosen, error_type=self._error_type(db, row))
        row.max_level_used = max(_as_int(row.max_level_used), chosen)
        row.updated_time = datetime.now()
        db.commit()
        return teaching

    # ---------------- 出题 ----------------
    def next_question(self, db, student_id, recovery_id, hint_level=None):
        """出题：练习/教学阶段出变式题（失败降级同知识点题），VERIFYING 出原题。"""
        row = self._prepared(db, student_id, recovery_id)
        if row is None:
            return None
        original = self._question(db, row.question_id)
        plan = DEFAULT_STRATEGY.plan(row, hint_level=hint_level or 0)
        level = _clamp(_as_int(plan.get("hint_level"), 1) or 1, 1, 4)
        question, source, variant = None, "original", False
        if DEFAULT_STRATEGY.should_vary(row.state, _as_int(row.attempts)):
            question, source = self._variant(db, row, original, plan)
            variant = question is not None
        if question is None:
            question = original
        teaching = self._teach(question, level, error_type=self._error_type(db, row))
        row.max_level_used = max(_as_int(row.max_level_used), level)
        row.updated_time = datetime.now()
        self._remember(student_id, row, question)
        db.commit()
        return {
            "recovery_id": row.id,
            "state": row.state,
            "hint_level": level,
            "question": {
                "question_id": getattr(question, "id", None),
                "question": getattr(question, "question", "") or "",
                "qtype": getattr(question, "qtype", "choice") or "choice",
                "options": grading.parse_options(getattr(question, "options", "")),
                "knowledge": getattr(question, "knowledge", "") or row.knowledge_id or "",
                "difficulty": _as_int(getattr(question, "difficulty", 0), 0),
                "source": source,
                "variant": bool(variant),
            },
            "teaching": teaching,
        }

    # ---------------- 判分 ----------------
    def answer(self, db, student_id, recovery_id, answer, *, question_id=None, hint_level=None):
        """作答：``grading.is_correct`` 判分 → 状态机推进 → 写 ``answer_records``。

        返回字段固定为 ``{correct, correct_answer, analysis, state, state_text, changed,
        next_action, hint_level, hint, variant, stats}``（SPEC §4.1）。
        """
        return self._submit(db, student_id, recovery_id, answer, question_id=question_id,
                            hint_level=hint_level, original_only=False)

    def verify(self, db, student_id, recovery_id, answer, *, question_id=None):
        """VERIFYING 原题验证：字段同 ``answer``，另含 ``mastered``。"""
        payload = self._submit(db, student_id, recovery_id, answer, question_id=question_id,
                               hint_level=None, original_only=True)
        if payload is None:
            return None
        payload["mastered"] = payload["state"] == MASTERED
        return payload

    def sync_from_wrong_book(self, db, student_id, question_row, correct):
        """``main.submit`` 钩子：答错入队（NEW），答对推进；幂等且**绝不抛异常**。"""
        try:
            question_id = _as_int(getattr(question_row, "id", 0))
            if not question_id or not student_id:
                return None
            now = datetime.now()
            row = db.query(WrongQuestionRecovery).filter(
                WrongQuestionRecovery.student_id == student_id,
                WrongQuestionRecovery.question_id == question_id,
            ).first()
            if row is None:
                if correct:
                    return None
                row = WrongQuestionRecovery(
                    student_id=student_id,
                    subject=str(getattr(question_row, "subject", "") or ""),
                    knowledge_id=str(getattr(question_row, "knowledge", "") or ""),
                    question_id=question_id,
                    wrong_question_id=self._wrong_question_id(db, student_id, question_id),
                    state=NEW,
                    state_before="",
                    attempts=1,
                    correct_count=0,
                    consecutive_correct=0,
                    fail_count=1,
                    max_level_used=0,
                    variant_count=0,
                    source="wrong_book",
                    last_state_change=now,
                    created_time=now,
                    updated_time=now,
                )
                db.add(row)
                db.commit()
                return row

            cc, fails = _as_int(row.consecutive_correct), _as_int(row.fail_count)
            if correct:
                result = apply_result(row.state, True, consecutive_correct=cc, fail_count=fails)
            else:
                result = transition(row.state, EVENT_RELEARN,
                                    consecutive_correct=cc, fail_count=fails)
            self._apply(row, result, now)
            row.attempts = _as_int(row.attempts) + 1
            if correct:
                row.correct_count = _as_int(row.correct_count) + 1
            row.updated_time = now
            db.commit()
            return row
        except Exception:                              # main.submit 的主流程优先
            try:
                db.rollback()
            except Exception:                          # noqa: BLE001 - 回滚失败也不能抛
                pass
            return None

    # ---------------- 内部 ----------------
    def _submit(self, db, student_id, recovery_id, submitted, *, question_id,
                hint_level, original_only):
        row = self._prepared(db, student_id, recovery_id)
        if row is None:
            return None
        now = datetime.now()
        question = self._resolve_question(db, student_id, row, question_id, original_only)
        correct = bool(question is not None and grading.is_correct(question, submitted))
        is_original = question is not None and _as_int(question.id) == _as_int(row.question_id)
        plan = DEFAULT_STRATEGY.plan(row)
        level = _clamp(_as_int(hint_level, 0) or _as_int(plan.get("hint_level"), 1), 1, 4)
        cc, fails = _as_int(row.consecutive_correct), _as_int(row.fail_count)
        state_name = str(row.state or "").upper()
        if (not correct) and is_original and state_name not in (NEW, str(RecoveryState.VERIFYING)):
            result = transition(row.state, EVENT_RELEARN,
                                consecutive_correct=cc, fail_count=fails)
        else:
            result = apply_result(row.state, correct,
                                  consecutive_correct=cc, fail_count=fails)
        row.attempts = _as_int(row.attempts) + 1
        if correct:
            row.correct_count = _as_int(row.correct_count) + 1
        self._apply(row, result, now)
        if hint_level:
            row.max_level_used = max(_as_int(row.max_level_used), level)
        row.updated_time = now
        teaching = self._teach(question or self._question(db, row.question_id), level,
                               error_type=self._error_type(db, row))
        db.add(AnswerRecord(
            student_id=student_id,
            subject=(getattr(question, "subject", "") or row.subject or ""),
            knowledge=(getattr(question, "knowledge", "") or row.knowledge_id or ""),
            difficulty=_as_int(getattr(question, "difficulty", 0), 0),
            correct=correct,
            question_id=getattr(question, "id", None),
            submitted=str(submitted or ""),
        ))
        self._remember(student_id, row, question)
        db.commit()
        return {
            "correct": correct,
            "correct_answer": getattr(question, "answer", "") or "",
            "analysis": getattr(question, "analysis", "") or "",
            "state": row.state,
            "state_text": STATE_TEXT.get(row.state, ""),
            "changed": bool(result.get("changed")),
            "next_action": next_action(row.state),
            "hint_level": level,
            "hint": teaching.get("hint", ""),
            "variant": bool(question is not None and not is_original),
            "stats": self.stats(db, student_id),
        }

    def _apply(self, row, result, now):
        """把状态机结果落到行上（计数、时间、state_before、mastered/next_verify）。"""
        if result.get("changed"):
            row.state_before = result.get("state_before") or str(row.state or "")
            row.state = result["next_state"]
            row.last_state_change = now
        row.consecutive_correct = _as_int(result.get("consecutive_correct"))
        row.fail_count = _as_int(result.get("fail_count"))
        if result.get("mastered"):
            row.mastered_time = now
        if result.get("enter_verifying"):
            row.next_verify_time = now + timedelta(days=VERIFY_DAYS)
        elif str(row.state or "").upper() != str(RecoveryState.VERIFYING):
            row.next_verify_time = None
        row.updated_time = now
        return result

    def _move(self, row, event, *, level=None, now=None):
        result = transition(row.state, event,
                            consecutive_correct=_as_int(row.consecutive_correct),
                            fail_count=_as_int(row.fail_count))
        self._apply(row, result, now or datetime.now())
        if level:
            row.max_level_used = max(_as_int(row.max_level_used), _as_int(level))
        return result

    def _prepared(self, db, student_id, recovery_id):
        """读行前先把到期的 VERIFYING 项按状态机回落（超时未过）。"""
        try:
            DEFAULT_SCHEDULER.apply_overdue(db, student_id)
        except Exception:                              # 到期处理失败不影响主流程
            try:
                db.rollback()
            except Exception:                          # noqa: BLE001
                pass
        return self._row(db, student_id, recovery_id)

    def _row(self, db, student_id, recovery_id):
        return db.query(WrongQuestionRecovery).filter(
            WrongQuestionRecovery.student_id == student_id,
            WrongQuestionRecovery.id == recovery_id,
        ).first()

    def _query(self, db, student_id):
        return db.query(WrongQuestionRecovery).filter(
            WrongQuestionRecovery.student_id == student_id,
        ).order_by(WrongQuestionRecovery.id.asc()).all()

    def _question(self, db, question_id):
        if not question_id:
            return None
        return db.query(Question).filter(Question.id == question_id).first()

    def _resolve_question(self, db, student_id, row, question_id, original_only):
        if original_only:
            return self._question(db, row.question_id)
        if question_id:
            return self._question(db, question_id)
        remembered = self._last_question.get((student_id, row.id))
        return self._question(db, remembered) or self._question(db, row.question_id)

    def _remember(self, student_id, row, question):
        self._last_question[(student_id, row.id)] = getattr(question, "id", None)

    def _wrong(self, db, student_id, question_id):
        return db.query(WrongQuestion).filter(
            WrongQuestion.student_id == student_id,
            WrongQuestion.question_id == question_id,
        ).first()

    def _wrong_question_id(self, db, student_id, question_id):
        return _as_int(getattr(self._wrong(db, student_id, question_id), "id", 0))

    def _error_type(self, db, row):
        try:
            wrong = self._wrong(db, row.student_id, row.question_id)
        except Exception:                              # noqa: BLE001
            return ""
        return str(getattr(wrong, "last_error_type", "") or "")

    def _item(self, db, row):
        question = self._question(db, row.question_id)
        wrong = self._wrong(db, row.student_id, row.question_id)
        return {
            "recovery_id": row.id,
            "question_id": row.question_id,
            "subject": row.subject or "",
            "knowledge": row.knowledge_id or "",
            "state": row.state,
            "state_text": STATE_TEXT.get(row.state, ""),
            "wrong_count": _as_int(getattr(wrong, "wrong_count", 0)) or 1,
            "attempts": _as_int(row.attempts),
            "consecutive_correct": _as_int(row.consecutive_correct),
            "fail_count": _as_int(row.fail_count),
            "max_level_used": _as_int(row.max_level_used),
            "question": getattr(question, "question", "") or "",
            "correct_answer": getattr(question, "answer", "") or "",
            "analysis": getattr(question, "analysis", "") or "",
            "error_type": str(getattr(wrong, "last_error_type", "") or ""),
            "next_verify_time": _fmt(row.next_verify_time),
            "created_time": _fmt(row.created_time),
        }

    def _history(self, db, student_id, row):
        records = db.query(AnswerRecord).filter(
            AnswerRecord.student_id == student_id,
            AnswerRecord.question_id == row.question_id,
        ).order_by(AnswerRecord.id.desc()).limit(10).all()
        return [{"correct": bool(record.correct), "submitted": record.submitted or "",
                 "created_time": _fmt(record.created_at)} for record in records]

    def _teach(self, question, level, error_type=""):
        """经 ``ai_recovery`` 取提示；缺失 / 异常一律降级为本地规则文案。"""
        level = _clamp(_as_int(level, 1) or 1, 1, 4)
        try:
            import ai_recovery

            result = ai_recovery.teach(question, knowledge=getattr(question, "knowledge", None),
                                       error_type=error_type, level=level)
            if isinstance(result, dict) and result.get("hint"):
                return result
        except Exception:                              # noqa: BLE001 - Agent 3 未就绪/离线
            pass
        return {"level": level, "level_text": LEVEL_TEXTS.get(level, ""),
                "hint": FALLBACK_HINTS.get(level, ""), "source": "fallback",
                "error_location": "", "steps": [], "full_explanation": ""}

    def _variant(self, db, row, original, plan):
        """优先 AI 变式题（过审才用），失败降级同知识点已有题目。返回 ``(row, source)``。"""
        if original is None:
            return None, "original"
        item = self._generate(original, row, plan)
        if item is not None:
            question = Question(
                subject=str(item.get("subject") or row.subject or original.subject or ""),
                grade=_as_int(getattr(original, "grade", 0), 0),
                knowledge=str(item.get("knowledge") or row.knowledge_id or ""),
                difficulty=_as_int(item.get("difficulty"), _as_int(original.difficulty, 50)),
                question=str(item.get("question") or ""),
                answer=str(item.get("answer") or ""),
                qtype=str(item.get("qtype") or "choice"),
                options=_options_json(item.get("options")),
                acceptable=_options_json(item.get("acceptable")) if item.get("acceptable") else "",
                analysis=str(item.get("analysis") or ""),
            )
            try:
                with db.begin_nested():
                    db.add(question)
                    db.flush()
                row.variant_count = _as_int(row.variant_count) + 1
                return question, str(item.get("source") or "rule")
            except Exception:                          # noqa: BLE001 - 落库失败就降级
                pass
        return self._fallback_question(db, row, original), "existing"

    def _generate(self, original, row, plan):
        try:
            import ai_recovery

            items = ai_recovery.generate_variants(
                original, count=1, difficulty=plan.get("difficulty"),
                knowledge=row.knowledge_id or None)
        except Exception:                              # noqa: BLE001 - 离线/异常即降级
            return None
        for item in items or []:
            if not isinstance(item, dict) or not str(item.get("question") or "").strip():
                continue
            validation = item.get("validation")
            if isinstance(validation, dict) and validation.get("passed") is False:
                continue
            return item
        return None

    def _fallback_question(self, db, row, original):
        """降级：同 subject + knowledge、难度最接近的既有题目（排除原题）。"""
        base = _as_int(getattr(original, "difficulty", 50), 50)
        query = db.query(Question).filter(Question.subject == (row.subject or ""),
                                          Question.knowledge == (row.knowledge_id or ""))
        if original is not None and original.id:
            query = query.filter(Question.id != original.id)
        candidates = query.all()
        if not candidates:                             # 知识点无题 → 放宽到同科
            query = db.query(Question).filter(Question.subject == (row.subject or ""))
            if original is not None and original.id:
                query = query.filter(Question.id != original.id)
            candidates = query.all()
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: abs(_as_int(item.difficulty, 50) - base))[0]


DEFAULT_ENGINE = RecoveryEngine()
