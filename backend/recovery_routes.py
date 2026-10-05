# ==============================================================
# 能力契约｜/api/recovery/* 错题康复接口（列表 / 开始教学 / 出题 / 判分 / 原题验证 / 分层提示）
# 入口：router / recovery_list / recovery_start / recovery_question / recovery_answer / recovery_verify / recovery_hint
#        / recovery_list_path / recovery_next_question / recovery_detail_path
# 依赖：recovery.engine（DEFAULT_ENGINE）、recovery.state、models.Question、stages、database.get_db
# 不负责：康复状态机与提示层级 → recovery/ 三模块与 ai_recovery.py；今日任务与习惯 → habit_routes.py / task_routes.py
# 验证：python backend/verify_recovery.py（Agent 7 门禁）
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复 API（SPEC §7.1）。

    GET  /api/recovery/list      康复列表 + 六态计数 + mastered_rate
    POST /api/recovery/start     开始教学（NEW → ANALYZING → LEARNING）
    POST /api/recovery/question  出下一题（变式题 / 原题）+ 本级提示
    POST /api/recovery/answer    判分 + 状态推进 + 下次验证时间
    POST /api/recovery/verify    VERIFYING 原题验证（答对 → MASTERED）
    POST /api/recovery/hint      单独取第 level 级提示

纪律：
1. 所有查询 / 写入都按 ``student_id`` 过滤（学生 A=1 / B=2 完全隔离）。
2. 学生不存在、没有康复项、``recovery_id`` 不属于该学生时返回**空结构**而不是 404，
   响应体里不出现任何他人的题目 / 答案 / 解析。
3. 参数非法返回 400（Pydantic 类型 / 范围错误由 FastAPI 返回 422），任何内部异常都被兜住 → 绝不 500。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import stages
from database import get_db
from models import Question
from recovery import engine as recovery_engine
from recovery.state import RecoveryState

router = APIRouter(prefix="/api/recovery", tags=["错题康复 V2.5"])

ENGINE = recovery_engine.DEFAULT_ENGINE

POLITE_400 = "state 只能是：" + "、".join(RecoveryState.ORDER)


class StartIn(BaseModel):
    student_id: int = Field(..., ge=1)
    recovery_id: int = Field(0, ge=0)
    question_id: int = Field(0, ge=0)


class QuestionIn(BaseModel):
    student_id: int = Field(..., ge=1)
    recovery_id: int = Field(0, ge=0)
    hint_level: int = Field(0, ge=0, le=4)


class AnswerIn(BaseModel):
    student_id: int = Field(..., ge=1)
    recovery_id: int = Field(0, ge=0)
    answer: str = ""
    question_id: int = Field(0, ge=0)
    hint_level: int = Field(0, ge=0, le=4)
    minutes: int = Field(0, ge=0)


class VerifyIn(BaseModel):
    student_id: int = Field(..., ge=1)
    recovery_id: int = Field(0, ge=0)
    answer: str = ""


class HintIn(BaseModel):
    student_id: int = Field(..., ge=1)
    recovery_id: int = Field(0, ge=0)
    level: int = Field(0, ge=0, le=4)


# ---------------------------------------------------------------- 工具


def _safe(db, call, fallback):
    """接口层最后一道防线：内部异常一律返回 fallback，绝不让接口 500。"""
    try:
        return call()
    except HTTPException:
        raise
    except Exception:                          # noqa: BLE001 - 兜底，不暴露内部细节
        try:
            db.rollback()
        except Exception:                      # noqa: BLE001
            pass
        return fallback


def _empty_teaching():
    return {"level": 0, "level_text": "", "hint": "", "error_location": "",
            "steps": [], "full_explanation": "", "source": ""}


def _empty_question():
    return {"question_id": 0, "question": "", "qtype": "", "options": [],
            "knowledge": "", "difficulty": 0, "source": "", "variant": False}


def _zero_stats():
    stats = {name.lower(): 0 for name in RecoveryState.ORDER}
    stats["total"] = 0
    stats["mastered_rate"] = 0.0
    return stats


def _student_stats(db, student_id):
    return _safe(db, lambda: ENGINE.stats(db, student_id), _zero_stats())


def _state_or_400(value):
    text = str(value or "").strip().upper()
    if text and text not in RecoveryState.ORDER:
        raise HTTPException(status_code=400, detail=POLITE_400)
    return text


def _subject_or_400(value):
    text = str(value or "").strip()
    if text and text not in stages.SUBJECTS:
        raise HTTPException(status_code=400,
                            detail="科目必须是：" + "、".join(stages.SUBJECTS))
    return text


def _empty_result(db, student_id, mastered=None):
    """空作答结果（未知学生 / 不属于该学生的康复项）。"""
    data = {"student_id": student_id, "correct": False, "correct_answer": "",
            "analysis": "", "state": "", "state_text": "", "changed": False,
            "next_action": "", "hint_level": 0, "hint": "", "variant": False,
            "stats": _student_stats(db, student_id), "review_next": ""}
    if mastered is not None:
        data["mastered"] = mastered
    return data


def _review_next(db, student_id, recovery_id):
    """下次原题验证到期时间（VERIFYING 阶段才有值，格式 YYYY-MM-DD HH:MM）。"""
    detail = _safe(db, lambda: ENGINE.detail(db, student_id, recovery_id), None)
    return str((detail or {}).get("next_verify_time") or "")


def _find_recovery_id(db, student_id, question_id):
    def find():
        items = ENGINE.list_items(db, student_id, limit=1000).get("items") or []
        for item in items:
            if int(item.get("question_id") or 0) == int(question_id):
                return int(item.get("recovery_id") or 0)
        return 0

    return _safe(db, find, 0)


def _recovery_id_of(db, student_id, question_id):
    """按 student_id + question_id 找康复项；没有就把这道题补进队列（幂等，含学生过滤）。"""
    found = _find_recovery_id(db, student_id, question_id)
    if found or not question_id:
        return found
    question = _safe(db, lambda: db.query(Question).filter(Question.id == question_id).first(), None)
    if question is None:
        return 0
    _safe(db, lambda: ENGINE.sync_from_wrong_book(db, student_id, question, False), None)
    return _find_recovery_id(db, student_id, question_id)


# ---------------------------------------------------------------- 接口


@router.get("/list")
def recovery_list(student_id: int = Query(..., ge=1), subject: str = "", state: str = "",
                  limit: int = Query(50, ge=0, le=500), db: Session = Depends(get_db)):
    """康复列表：``{student_id, total, stats{六态计数+total+mastered_rate}, items[]}``。"""
    subject = _subject_or_400(subject)
    state = _state_or_400(state)
    empty = {"student_id": student_id, "total": 0, "stats": _zero_stats(), "items": []}
    return _safe(db, lambda: ENGINE.list_items(db, student_id, subject=subject or None,
                                               state=state or None, limit=limit), empty)


@router.post("/start")
def recovery_start(payload: StartIn, db: Session = Depends(get_db)):
    """开始康复教学：``recovery_id`` 或 ``question_id`` 二选一，返回 ``teaching`` + ``item``。"""
    recovery_id = int(payload.recovery_id or 0)
    question_id = int(payload.question_id or 0)
    if not recovery_id and question_id:
        recovery_id = _recovery_id_of(db, payload.student_id, question_id)

    empty = {"student_id": payload.student_id, "recovery_id": 0, "question_id": question_id,
             "state": "", "state_text": "", "teaching": _empty_teaching(), "item": None}
    if not recovery_id:
        return empty

    data = _safe(db, lambda: ENGINE.start(db, payload.student_id, recovery_id), None)
    if not data:
        return empty
    data["student_id"] = payload.student_id
    return data


@router.post("/question")
def recovery_question(payload: QuestionIn, db: Session = Depends(get_db)):
    """出下一题：练习阶段出变式题（AI 失败降级既存题），验证阶段出原题。"""
    empty = {"student_id": payload.student_id, "recovery_id": 0, "state": "", "hint_level": 0,
             "question": _empty_question(), "teaching": _empty_teaching()}
    if not payload.recovery_id:
        return empty

    data = _safe(db, lambda: ENGINE.next_question(db, payload.student_id, payload.recovery_id,
                                                  hint_level=payload.hint_level or None), None)
    if not data:
        return empty
    data["student_id"] = payload.student_id
    return data


@router.post("/answer")
def recovery_answer(payload: AnswerIn, db: Session = Depends(get_db)):
    """作答：``grading.is_correct`` 判分 → 状态机推进；``minutes`` 由任务系统单独上报。"""
    data = _safe(db, lambda: ENGINE.answer(db, payload.student_id, payload.recovery_id,
                                           payload.answer, question_id=payload.question_id or None,
                                           hint_level=payload.hint_level or None), None)
    if not data:
        return _empty_result(db, payload.student_id)

    data["student_id"] = payload.student_id
    data["review_next"] = _review_next(db, payload.student_id, payload.recovery_id)
    return data


@router.post("/verify")
def recovery_verify(payload: VerifyIn, db: Session = Depends(get_db)):
    """原题验证（只用原题，不判变式题）：答对 → MASTERED，答错 → 回炉。"""
    data = _safe(db, lambda: ENGINE.verify(db, payload.student_id, payload.recovery_id,
                                           payload.answer), None)
    if not data:
        return _empty_result(db, payload.student_id, mastered=False)

    data["student_id"] = payload.student_id
    data["review_next"] = _review_next(db, payload.student_id, payload.recovery_id)
    return data


@router.post("/hint")
def recovery_hint(payload: HintIn, db: Session = Depends(get_db)):
    """取第 ``level`` 级提示（1 方向 / 2 定位 / 3 步骤 / 4 完整讲解，0=按策略自动）。"""
    teaching = _safe(db, lambda: ENGINE.hint(db, payload.student_id, payload.recovery_id,
                                             level=payload.level or None), None)
    if not teaching:
        return {"student_id": payload.student_id, **_empty_teaching()}
    return {"student_id": payload.student_id, **teaching}


# ---------- V2.5 兼容入口（需求 §25 的 path 形式，复用同一套语义，不建第二套） ----------


@router.get("/list/{student_id}")
def recovery_list_path(student_id: int, subject: str = "", state: str = "",
                       limit: int = Query(50, ge=0, le=500), db: Session = Depends(get_db)):
    """path 形式（等价 ``GET /api/recovery/list?student_id=``）：康复列表。"""
    return recovery_list(student_id=student_id, subject=subject, state=state, limit=limit, db=db)


@router.get("/next-question")
def recovery_next_question(student_id: int = Query(..., ge=1),
                           recovery_id: int = Query(..., ge=1),
                           hint_level: int = Query(0, ge=0, le=4),
                           db: Session = Depends(get_db)):
    """下一题（等价 ``POST /api/recovery/question`` 的只读 GET 形式）。"""
    data = _safe(db, lambda: ENGINE.next_question(db, student_id, recovery_id,
                                                  hint_level=hint_level or None), None)
    if not data:
        return {"student_id": student_id, **_empty_question()}
    return {"student_id": student_id, **data}


@router.get("/{recovery_id}")
def recovery_detail_path(recovery_id: int, student_id: int = Query(..., ge=1),
                         db: Session = Depends(get_db)):
    """path 形式（等价只读详情）：单条康复记录。"""
    data = _safe(db, lambda: ENGINE.detail(db, student_id, recovery_id), None)
    if not data:
        return _empty_result(db, student_id)
    data["student_id"] = student_id
    return data
