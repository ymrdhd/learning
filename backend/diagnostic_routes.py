# ==============================================================
# 能力契约｜/api/diagnostic/* 诊断接口（start / question / answer / report / profiles / stages）
# 入口：router / start / next_question / submit_answer / session_detail / profiles / report / list_stages
# 依赖：diagnostic diagnostic_bank validator deepseek grading error_analysis knowledge_routes.update_mastery models
# 不负责：诊断算法 → diagnostic.py；日常练习 → main.py；自适应 → adaptive_routes.py
# 验证：python backend/verify_diagnostic.py
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.0 能力诊断 API（挂载在 /api/diagnostic 下）。

四个主接口：
    POST /api/diagnostic/start      开始诊断 → session_id
    GET  /api/diagnostic/question   取下一题（不下发答案）
    POST /api/diagnostic/answer     提交答案（只回对错，不给正确答案）
    GET  /api/diagnostic/report     生成能力报告

三个辅助接口：
    GET  /api/diagnostic/session    查询某场诊断的进度
    GET  /api/diagnostic/profiles   查学生各科能力画像
    GET  /api/diagnostic/stages     72 个能力阶段字典
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import diagnostic
import diagnostic_bank
import error_analysis
import stages
import validator
from database import get_db
from deepseek import CHOICE, FALLBACK, generate_question
from grading import is_correct
from knowledge_routes import update_mastery
from models import (
    AbilityProfile,
    DiagnosticRecord,
    DiagnosticSession,
    Question,
    Student,
    StudentKnowledgeMastery,
)

router = APIRouter(prefix="/api/diagnostic", tags=["能力诊断"])


class StartIn(BaseModel):
    student_id: int = 1
    subject: str = stages.DEFAULT_SUBJECT


class AnswerIn(BaseModel):
    session_id: int
    question_id: int
    answer: str


def _dumps(value):
    return json.dumps(value, ensure_ascii=False)


def _ensure_student(db: Session, student_id: int) -> Student:
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        student = Student(id=student_id, name=f"小朋友{student_id}", grade=1)
        db.add(student)
        db.flush()
    return student


def _normalize_subject(subject) -> str:
    text = str(subject or "").strip()
    if text not in stages.SUBJECTS:
        raise HTTPException(status_code=400, detail=f"科目必须是：{'、'.join(stages.SUBJECTS)}")
    return text


def _get_session(db: Session, session_id: int) -> DiagnosticSession:
    row = db.query(DiagnosticSession).filter(DiagnosticSession.id == session_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="诊断会话不存在，请重新开始诊断")
    return row


def _session_ability(db: Session, session_row: DiagnosticSession):
    """按本场记录重新算一次能力画像（也用于诊断结束时的落库）。"""
    # 刚提交的那条记录还在当前事务里，autoflush 关闭时查询看不到它
    db.flush()

    records = [
        {"stage": row.stage, "difficulty": row.difficulty, "correct": bool(row.correct),
         "knowledge": row.knowledge_point}
        for row in db.query(DiagnosticRecord)
        .filter(DiagnosticRecord.session_id == session_row.id)
        .order_by(DiagnosticRecord.id.asc())
        .all()
    ]
    state = diagnostic.load_state(session_row.state)
    ability = diagnostic.calculate_ability(records, diagnostic.final_key(state))
    ability["student_id"] = session_row.student_id
    ability["subject"] = session_row.subject
    return ability, records, state


def _save_profile(db: Session, student_id: int, subject: str, ability: dict):
    row = db.query(AbilityProfile).filter(
        AbilityProfile.student_id == student_id,
        AbilityProfile.subject == subject,
    ).first()

    if row is None:
        row = AbilityProfile(student_id=student_id, subject=subject)
        db.add(row)

    row.ability_stage = ability["stage"]
    row.ability_score = ability["score"]
    row.confidence = ability["confidence"]
    row.lower_stage, row.upper_stage = ability["range"]
    row.questions = ability["questions"]
    row.correct = ability["correct"]
    row.source = "diagnostic"
    row.updated_time = datetime.now()
    return row


def _ability_context(db: Session, session_row: DiagnosticSession, state: dict):
    """出题时带给模型的能力上下文（V2.0：不再只传年级）。"""
    stage = state["stage"]
    knowledge = stages.knowledge_of(session_row.subject, stage)
    mastery = db.query(StudentKnowledgeMastery).filter(
        StudentKnowledgeMastery.student_id == session_row.student_id,
        StudentKnowledgeMastery.subject == session_row.subject,
        StudentKnowledgeMastery.knowledge_id == knowledge,
    ).first()

    student = db.query(Student).filter(Student.id == session_row.student_id).first()
    grade_text = f"{student.grade}年级" if student and isinstance(student.grade, int) else ""

    return {
        "grade": grade_text,
        "subject": session_row.subject,
        "stage": stage,
        "stage_label": stages.label(stage),
        "target_stage": stages.next_key(stage),
        "target_label": stages.label(stages.next_key(stage)),
        "knowledge": knowledge,
        "mastery": mastery.mastery_score if mastery else None,
    }


def _audit(data, subject, knowledge, difficulty, stage):
    """V2.3：诊断题也要过一遍质量审核，不合格的题目直接丢掉换一道。"""
    if not data:
        return None

    report = validator.validate(data, subject=subject, knowledge=knowledge,
                                difficulty=difficulty, stage=stage)
    return data if report["passed"] else None


def _create_question(db: Session, session_row: DiagnosticSession, state: dict):
    """按被测阶段出题：本地分阶段题库优先，其次交给 DeepSeek（带能力上下文）。"""
    stage = state["stage"]
    subject = session_row.subject
    knowledge = stages.knowledge_of(subject, stage)
    difficulty = stages.difficulty_of(stage)

    data = None
    for _ in range(4):
        candidate = diagnostic_bank.build_question(subject, stage, avoid=state.get("asked") or [])
        if candidate is None:
            break
        data = _audit(candidate, subject, knowledge, difficulty, stage)
        if data:
            break

    error = ""

    if data is None:
        # 题库没有覆盖（例如新增科目）时退回模型出题，prompt 里带上能力上下文
        data = generate_question(
            subject,
            stages.grade_text(stage),
            knowledge,
            difficulty,
            CHOICE,
            ability=_ability_context(db, session_row, state),
        )
        if not _audit(data, subject, knowledge, difficulty, stage):
            data = dict(FALLBACK[CHOICE])
            data.update(qtype=CHOICE, source="fallback",
                        error="生成的题目未通过质量审核，已使用内置练习题")

        error = data.get("error") or ""

    row = Question(
        subject=subject,
        grade=stages.grade_of(stage),
        knowledge=knowledge,
        difficulty=difficulty,
        question=data["question"],
        answer=data["answer"],
        qtype=data["qtype"],
        options=_dumps(data.get("options") or {}),
        acceptable=_dumps(data.get("acceptable") or []),
        analysis=data.get("analysis") or "",
    )
    db.add(row)
    db.flush()

    state["pending_question_id"] = row.id
    state["asked"] = (state.get("asked") or [])[-39:] + [row.question]

    return row, data, error


def _public_question(row: Question, session_row: DiagnosticSession, state: dict):
    """下发给前端：只给题干和选项，答案留在服务端。"""
    try:
        options = json.loads(row.options) if row.options else {}
    except ValueError:
        options = {}

    return {
        "session_id": session_row.id,
        "question_id": row.id,
        "qtype": row.qtype,
        "subject": session_row.subject,
        "stage": state["stage"],
        "stage_label": stages.label(state["stage"]),
        "knowledge": row.knowledge,
        "difficulty": row.difficulty,
        "question": row.question,
        "options": options,
        "progress": diagnostic.progress_of(state),
        "finished": False,
    }


@router.get("/stages")
def list_stages():
    """24 个能力阶段字典，前端用来显示"正在测试：二年级进阶"。"""
    return {
        "total": len(stages.all_keys()),
        "levels": list(stages.LEVELS),
        "subjects": list(stages.SUBJECTS),
        "stages": [
            {
                "key": key,
                "label": stages.label(key),
                "grade": stages.grade_of(key),
                "level": stages.level_of(key),
                "level_name": stages.level_name(key),
                "difficulty": stages.difficulty_of(key),
            }
            for key in stages.all_keys()
        ],
    }


@router.post("/start")
def start(payload: StartIn, db: Session = Depends(get_db)):
    """开始一场能力诊断：永远从一年级基础开始，不看学生当前年级。"""
    subject = _normalize_subject(payload.subject)
    _ensure_student(db, payload.student_id)

    # 上一场没做完的会话先收尾，避免同一科目出现两场"进行中"
    stale = db.query(DiagnosticSession).filter(
        DiagnosticSession.student_id == payload.student_id,
        DiagnosticSession.subject == subject,
        DiagnosticSession.status == "in_progress",
    ).all()
    for row in stale:
        row.status = "finished"
        row.end_time = datetime.now()
        state = diagnostic.load_state(row.state)
        state["finished"] = True
        state["reason"] = state.get("reason") or "重新开始诊断"
        row.state = diagnostic.dump_state(state)
        row.final_stage = row.final_stage or diagnostic.final_key(state)

    state = diagnostic.new_state()
    row = DiagnosticSession(
        student_id=payload.student_id,
        subject=subject,
        start_time=datetime.now(),
        current_stage=state["stage"],
        status="in_progress",
        total_count=0,
        correct_count=0,
        state=diagnostic.dump_state(state),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        "session_id": row.id,
        "student_id": row.student_id,
        "subject": subject,
        "stage": state["stage"],
        "stage_label": stages.label(state["stage"]),
        "progress": diagnostic.progress_of(state),
        "message": "我们从一年级基础开始，答对越多，题目会越难哦～",
    }


@router.get("/question")
def next_question(session_id: int, db: Session = Depends(get_db)):
    """取下一道诊断题；已经结束的会话返回 finished 与报告地址。"""
    session_row = _get_session(db, session_id)
    state = diagnostic.load_state(session_row.state)

    if session_row.status == "finished" or state["finished"]:
        return {
            "session_id": session_row.id,
            "finished": True,
            "stage": session_row.final_stage or diagnostic.final_key(state),
            "final_stage": session_row.final_stage or diagnostic.final_key(state),
            "final_score": session_row.final_score,
            "confidence": session_row.confidence,
            "report_url": f"/api/diagnostic/report?student_id={session_row.student_id}&subject={session_row.subject}",
        }

    # 同一道题没答之前反复刷新，不应该重复出题
    pending_id = state.get("pending_question_id")
    if pending_id:
        pending = db.query(Question).filter(Question.id == pending_id).first()
        if pending is not None:
            return _public_question(pending, session_row, state)

    row, data, error = _create_question(db, session_row, state)
    session_row.current_stage = state["stage"]
    session_row.state = diagnostic.dump_state(state)
    db.commit()

    payload = _public_question(row, session_row, state)
    payload["source"] = data.get("source")
    if error:
        payload["error"] = error
    return payload


@router.post("/answer")
def submit_answer(payload: AnswerIn, db: Session = Depends(get_db)):
    """提交答案：只告诉孩子对错和进度，不下发正确答案。"""
    session_row = _get_session(db, payload.session_id)

    if session_row.status == "finished":
        raise HTTPException(status_code=400, detail="这场诊断已经结束，请查看能力报告")

    state = diagnostic.load_state(session_row.state)

    if state.get("pending_question_id") != payload.question_id:
        raise HTTPException(status_code=400, detail="题目不匹配，请先获取下一题")

    row = db.query(Question).filter(Question.id == payload.question_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="题目不存在")

    correct = is_correct(row, payload.answer)
    stage = state["stage"]

    db.add(DiagnosticRecord(
        session_id=session_row.id,
        student_id=session_row.student_id,
        subject=session_row.subject,
        stage=stage,
        knowledge_point=row.knowledge,
        difficulty=row.difficulty,
        correct=correct,
        question_id=row.id,
        submitted=payload.answer,
    ))

    # V2.3：诊断题答错也记录错因（诊断题不写常规答题记录，所以 answer_record_id 留空）
    if not correct:
        error_analysis.analyze(db, session_row.student_id, row, payload.answer, use_ai=False)

    # V2.3：掌握度按这个知识点的全部历史记录重算（包含诊断题）
    update_mastery(db, session_row.student_id, session_row.subject, row.knowledge, stage=stage)

    diagnostic.record_answer(state, correct)
    session_row.total_count = state["total"]
    session_row.correct_count = state["correct"]

    verdict = None
    message = "答对啦，真棒！" if correct else "没关系，我们继续看看别的题～"

    if diagnostic.stage_round_finished(state):
        entry = diagnostic.evaluate_stage(state)
        verdict = entry["verdict"]
        message = {
            "excellent": "这一组掌握得很好，我们去试试更难的题！",
            "good": "不错！我们进入下一个年级的基础题。",
            "boundary": "这里开始有点难了，我们再确认一组。",
            "fail": "这一级还有点难，我们已经找到你的水平啦。",
        }[verdict]

    finished = bool(state["finished"])
    session_row.current_stage = state["stage"]
    session_row.state = diagnostic.dump_state(state)

    result = {
        "session_id": session_row.id,
        "correct": correct,
        "stage": state["stage"],
        "stage_label": stages.label(state["stage"]),
        "verdict": verdict,
        "message": message,
        "progress": diagnostic.progress_of(state),
        "finished": finished,
    }

    if finished:
        ability, _records, _state = _session_ability(db, session_row)
        session_row.status = "finished"
        session_row.end_time = datetime.now()
        session_row.final_stage = ability["stage"]
        session_row.final_score = ability["score"]
        session_row.confidence = ability["confidence"]
        _save_profile(db, session_row.student_id, session_row.subject, ability)

        result.update({
            "final_stage": ability["stage"],
            "final_stage_label": ability["stage_label"],
            "final_score": ability["score"],
            "confidence": ability["confidence"],
            "range_label": ability["range_label"],
            "star_text": ability["star_text"],
            "report_url": f"/api/diagnostic/report?student_id={session_row.student_id}&subject={session_row.subject}",
        })

    db.commit()
    return result


@router.get("/session")
def session_detail(session_id: int, db: Session = Depends(get_db)):
    session_row = _get_session(db, session_id)
    state = diagnostic.load_state(session_row.state)
    return {
        "session_id": session_row.id,
        "student_id": session_row.student_id,
        "subject": session_row.subject,
        "status": session_row.status,
        "start_time": session_row.start_time.strftime("%Y-%m-%d %H:%M") if session_row.start_time else "",
        "end_time": session_row.end_time.strftime("%Y-%m-%d %H:%M") if session_row.end_time else "",
        "current_stage": session_row.current_stage,
        "final_stage": session_row.final_stage,
        "final_score": session_row.final_score,
        "confidence": session_row.confidence,
        "progress": diagnostic.progress_of(state),
        "history": state.get("history") or [],
    }


def _profile_payload(row: AbilityProfile):
    lower = row.lower_stage or row.ability_stage
    upper = row.upper_stage or stages.next_key(row.ability_stage)
    return {
        "student_id": row.student_id,
        "subject": row.subject,
        "stage": row.ability_stage,
        "stage_label": stages.label(row.ability_stage),
        "range": [lower, upper],
        "range_label": lower if lower == upper else f"{lower}～{upper}",
        "score": row.ability_score,
        "confidence": row.confidence,
        "stars": stages.stars(row.ability_score),
        "star_text": stages.star_text(row.ability_score),
        "questions": row.questions or 0,
        "correct": row.correct or 0,
        "updated_time": row.updated_time.strftime("%Y-%m-%d %H:%M") if row.updated_time else "",
    }


@router.get("/profiles")
def profiles(student_id: int = 1, db: Session = Depends(get_db)):
    """学生各科能力画像（入口页显示"当前能力"）。"""
    rows = db.query(AbilityProfile).filter(AbilityProfile.student_id == student_id).all()
    by_subject = {row.subject: row for row in rows}

    return {
        "student_id": student_id,
        "profiles": [_profile_payload(by_subject[subject]) for subject in stages.SUBJECTS
                     if subject in by_subject],
    }


@router.get("/report")
def report(student_id: int = 1, subject: str = stages.DEFAULT_SUBJECT,
           session_id: int = 0, db: Session = Depends(get_db)):
    """能力报告：能力画像 + 知识点细分 + 优势 / 需要提升 / 建议。"""
    subject = _normalize_subject(subject)

    profile = db.query(AbilityProfile).filter(
        AbilityProfile.student_id == student_id,
        AbilityProfile.subject == subject,
    ).first()

    if profile is None:
        return {
            "available": False,
            "student_id": student_id,
            "subject": subject,
            "message": "还没有做过这项能力诊断，先来做一次吧～",
        }

    if session_id:
        session_row = _get_session(db, session_id)
    else:
        session_row = (
            db.query(DiagnosticSession)
            .filter(
                DiagnosticSession.student_id == student_id,
                DiagnosticSession.subject == subject,
                DiagnosticSession.status == "finished",
            )
            .order_by(DiagnosticSession.id.desc())
            .first()
        )

    history = []
    if session_row is not None:
        history = diagnostic.load_state(session_row.state).get("history") or []

    mastery_rows = db.query(StudentKnowledgeMastery).filter(
        StudentKnowledgeMastery.student_id == student_id,
        StudentKnowledgeMastery.subject == subject,
    ).all()

    masteries = [
        {
            "knowledge": row.knowledge_id,
            "knowledge_id": row.knowledge_id,
            "mastery_score": row.mastery_score or 0,
            "questions": row.questions or 0,
            "correct": row.correct or 0,
            "stage": row.stage or "",
            "stage_label": stages.label(row.stage) if stages.is_valid(row.stage) else "",
        }
        for row in mastery_rows
    ]

    ability = _profile_payload(profile)
    payload = diagnostic.build_report(subject, ability, masteries, history)
    payload.update({
        "available": True,
        "student_id": student_id,
        "session_id": session_row.id if session_row is not None else 0,
        "updated_time": ability["updated_time"],
    })
    return payload
