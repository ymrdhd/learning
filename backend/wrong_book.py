# ==============================================================
# 能力契约｜错题登记与状态推进 NEW → LEARNING → MASTERED
# 入口：record_wrong / record_correct / items_for / stats_for / MASTER_STREAK
# 依赖：mastery、stages、models
# 不负责：错因分类 → error_analysis.py；复习调度 → srs.py / review/
# 验证：python backend/verify_knowledge.py
# 被调用：main.py、knowledge_routes.py、review/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 错题本：NEW（未掌握）→ LEARNING（巩固中）→ MASTERED（已攻克）。

流程（和孩子的真实学习节奏对齐）：

    第一次答错 → 加入错题本（NEW）+ 生成错因分析
        ↓ 看讲解、练相似题
    答对一次   → LEARNING（巩固中）
        ↓ 再答对一次
    答对两次   → MASTERED（已攻克，移出错题本主列表）
        ↓ 万一又错了
    重新回到   → LEARNING

"答对"是按**知识点**推进的：练相似题（同一知识点的另一道题）同样算数，
所以孩子不需要重做原题也能把错题攻克掉。
"""

from datetime import datetime

import mastery
import stages

STATUS_TEXT = {"NEW": "未掌握", "LEARNING": "巩固中", "MASTERED": "已攻克"}
STATUS_ORDER = ("NEW", "LEARNING", "MASTERED")
MASTER_STREAK = 2          # 连对几次算攻克


def _stage_of(question_row):
    try:
        return stages.key_of_difficulty(getattr(question_row, "difficulty", 50))
    except (TypeError, ValueError):
        return stages.START_KEY


def _find(db, student_id, question_id):
    from models import WrongQuestion

    return db.query(WrongQuestion).filter(
        WrongQuestion.student_id == student_id,
        WrongQuestion.question_id == question_id,
    ).first()


def record_wrong(db, student_id, question_row, error_type=None):
    """答错：进错题本 / 次数 +1 / 已攻克的回到巩固中。"""
    from models import WrongQuestion

    now = datetime.now()
    row = _find(db, student_id, getattr(question_row, "id", None))
    subject = str(getattr(question_row, "subject", "") or "数学")
    knowledge = str(getattr(question_row, "knowledge", "") or "")

    if row is None:
        row = WrongQuestion(
            student_id=student_id,
            subject=subject,
            knowledge_id=knowledge,
            question_id=getattr(question_row, "id", None),
            stage=_stage_of(question_row),
            status="NEW",
            wrong_count=1,
            correct_streak=0,
            last_error_type=error_type or "",
            first_wrong_time=now,
            last_wrong_time=now,
            next_review_time=mastery.DEFAULT_ENGINE.next_review_time(0, now),
            created_time=now,
        )
        db.add(row)
        db.flush()
        return row

    row.wrong_count = (row.wrong_count or 0) + 1
    row.correct_streak = 0
    if (row.status or "NEW") == "MASTERED":
        row.status = "LEARNING"
    row.last_error_type = error_type or row.last_error_type
    row.last_wrong_time = now
    row.next_review_time = mastery.DEFAULT_ENGINE.next_review_time(0, now)
    return row


def record_correct(db, student_id, question_row):
    """答对：把该知识点下还没攻克的错题推进一格（连对 2 次即攻克）。"""
    from models import WrongQuestion

    now = datetime.now()
    subject = str(getattr(question_row, "subject", "") or "")
    knowledge = str(getattr(question_row, "knowledge", "") or "")

    rows = db.query(WrongQuestion).filter(
        WrongQuestion.student_id == student_id,
        WrongQuestion.subject == subject,
        WrongQuestion.knowledge_id == knowledge,
        WrongQuestion.status != "MASTERED",
    ).all()

    advanced = []
    for row in rows:
        row.correct_streak = (row.correct_streak or 0) + 1
        row.status = "MASTERED" if row.correct_streak >= MASTER_STREAK else "LEARNING"
        row.next_review_time = mastery.DEFAULT_ENGINE.next_review_time(
            90 if row.status == "MASTERED" else 70, now)
        advanced.append(row)

    return advanced


def stats_for(db, student_id, subject=None):
    """未掌握 / 巩固中 / 已攻克 的题数统计。"""
    from models import WrongQuestion

    query = db.query(WrongQuestion).filter(WrongQuestion.student_id == student_id)
    if subject:
        query = query.filter(WrongQuestion.subject == subject)

    stats = {status: 0 for status in STATUS_ORDER}
    for row in query.all():
        status = row.status or "NEW"
        stats[status] = stats.get(status, 0) + 1
    stats["total"] = sum(stats[status] for status in STATUS_ORDER)
    return stats


def items_for(db, student_id, subject=None, status=None, limit=50):
    """错题列表：带上题干、正确答案和最近一次错因分析。"""
    from models import AnswerErrorAnalysis, Question, WrongQuestion

    query = db.query(WrongQuestion).filter(WrongQuestion.student_id == student_id)
    if subject:
        query = query.filter(WrongQuestion.subject == subject)
    if status:
        query = query.filter(WrongQuestion.status == status)

    rows = query.order_by(WrongQuestion.id.desc()).limit(max(1, int(limit or 50))).all()

    items = []
    for row in rows:
        question = db.query(Question).filter(Question.id == row.question_id).first()
        latest = db.query(AnswerErrorAnalysis).filter(
            AnswerErrorAnalysis.student_id == student_id,
            AnswerErrorAnalysis.question_id == row.question_id,
        ).order_by(AnswerErrorAnalysis.id.desc()).first()

        items.append({
            "id": row.id,
            "question_id": row.question_id,
            "subject": row.subject,
            "knowledge": row.knowledge_id,
            "stage": row.stage,
            "status": row.status or "NEW",
            "status_text": STATUS_TEXT.get(row.status or "NEW", "未掌握"),
            "wrong_count": row.wrong_count or 0,
            "correct_streak": row.correct_streak or 0,
            "last_error_type": row.last_error_type or (latest.error_type if latest else ""),
            "analysis": latest.analysis if latest else "",
            "suggestion": latest.suggestion if latest else "",
            "last_wrong_time": row.last_wrong_time.strftime("%Y-%m-%d %H:%M") if row.last_wrong_time else "",
            "next_review_time": row.next_review_time.strftime("%Y-%m-%d %H:%M") if row.next_review_time else "",
            "question": question.question if question else "",
            "correct_answer": question.answer if question else "",
            "difficulty": question.difficulty if question else 0,
        })

    return items
