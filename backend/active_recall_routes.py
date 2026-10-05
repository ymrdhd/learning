# ==============================================================
# 能力契约｜/api/active-recall/* 主动回忆接口（出卡 / 提交回忆 / 当天小结）
# 入口：router / recall_start / recall_answer / recall_hint / recall_summary
# 依赖：active_recall（DEFAULT_ENGINE / child_level）、models.Student、database.get_db
# 不负责：选卡与判分算法 → active_recall.py；每日任务与完成页 → task_routes.py / daily_routes.py
# 验证：python backend/verify_active_recall.py
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 主动回忆 API（需求 §21-§22）。

    POST /api/active-recall/start    出卡（只给提示语，**不给选项**）
    POST /api/active-recall/answer   提交学生自己输入的回忆答案
    POST /api/active-recall/hint     取某一级回忆提示（Recall Hint Ladder 0~4，V2.7）
    GET  /api/active-recall/summary  当天主动回忆小结

纪律：按 ``student_id`` 过滤（A=1 / B=2 隔离）；学生不存在、卡片不存在、答案为空时返回
**空结构**而不是 404；``date`` 非法返回 400；内部异常一律兜住 → 绝不 500。
"""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import active_recall
from database import get_db
from models import Student

router = APIRouter(prefix="/api/active-recall", tags=["主动回忆 V2.5"])

ENGINE = active_recall.DEFAULT_ENGINE

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class StartIn(BaseModel):
    student_id: int = Field(..., ge=1)
    subject: str = ""
    count: int = Field(active_recall.DEFAULT_COUNT, ge=1, le=active_recall.MAX_COUNT)


class AnswerIn(BaseModel):
    student_id: int = Field(..., ge=1)
    card_id: str = ""
    answer: str = ""
    response_time: int = Field(0, ge=0, le=86400)
    hint_level: int = Field(0, ge=0, le=4)
    confidence_feedback: str = ""


class HintIn(BaseModel):
    """V2.7 回忆提示阶梯（需求 §十八）：0 无提示 / 1 关键词 / 2 部分结构 / 3 选择提示 / 4 完整答案。"""

    student_id: int = Field(..., ge=1)
    card_id: str = ""
    level: int = Field(0, ge=0, le=active_recall.MAX_HINT_LEVEL)

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


def _day_or_400(value):
    """日期参数统一 ``YYYY-MM-DD``；空串表示"今天"。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if not DAY_RE.match(text):
        raise HTTPException(status_code=400, detail="date 必须是 YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date 必须是 YYYY-MM-DD") from None
    return text


def _today_text():
    return datetime.now().strftime("%Y-%m-%d")


def _subject_or_400(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text not in active_recall.SUBJECTS:
        raise HTTPException(status_code=400, detail="科目必须是：" + "、".join(active_recall.SUBJECTS))
    return text


def _student_exists(db, student_id):
    try:
        return db.query(Student).filter(Student.id == student_id).first() is not None
    except Exception:                          # noqa: BLE001
        return False


def _ctx(student_id):
    return {"student_id": student_id, "subject": "", "knowledge": "", "kind": "", "kind_text": "",
            "prompt": "", "answer": "", "expected": [], "correct": False, "hint_level": 0,
            "response_time": 0, "memory_gain": 0.0, "stability": 0.0, "mastery_score": None}


def _empty_start(student_id):
    return {"student_id": student_id, "subject": "", "count": 0, "minutes": 0,
            "mode": "ACTIVE_RECALL", "message": "", "cards": []}


def _empty_answer(student_id):
    data = _ctx(student_id)
    data.update({"card_id": "", "result": "", "result_text": "", "hint": "",
                 "child": active_recall.child_level(0, 0.0)})
    return data


def _empty_hint(student_id, level=0):
    return {"student_id": student_id, "card_id": "", "level": level, "level_key": "",
            "level_name": "", "level_text": active_recall.hint_level_text(level), "text": "",
            "reveal_answer": False, "weight": 0.0, "payload": {},
            "ladder": active_recall.hint_ladder()}


def _empty_summary(student_id, day=None):
    return {"student_id": student_id, "date": day or _today_text(), "total": 0, "correct": 0,
            "partial": 0, "wrong": 0, "accuracy": 0.0, "minutes": 0, "items": []}


def _record_deep_evidence(db, payload, data):
    """V2.7：把这次回忆落成 RECALL 学习证据（需求 §六 / §十八）。

    独立 try/except + 独立提交：深度掌握出问题绝不影响回忆判分与记忆增益。
    """
    knowledge = str(data.get("knowledge") or "").strip()
    subject = str(data.get("subject") or "").strip()
    if not knowledge or not subject:
        return None
    try:
        import deep_learning.engine as deep_engine_module

        deep = deep_engine_module.DEFAULT_ENGINE
        deep.record_evidence(
            db, payload.student_id, subject, knowledge,
            evidence_type="RECALL", result=str(data.get("result") or "wrong"),
            difficulty=40, hint_level=int(data.get("hint_level") or 0),
            confidence=str(payload.confidence_feedback or ""),
            response_time=float(payload.response_time or 0), source="recall",
            detail="card=%s" % (data.get("card_id") or ""))
        return deep.detail(db, payload.student_id, subject, knowledge)
    except Exception:                          # noqa: BLE001 - 深度学习不得阻塞主动回忆
        try:
            db.rollback()
        except Exception:                      # noqa: BLE001
            pass
        return None

@router.post("/start")
def recall_start(payload: StartIn, db: Session = Depends(get_db)):
    """出卡：``{student_id, subject, count, minutes, cards[{card_id, subject, knowledge, kind_text, prompt, hint}]}``。"""
    subject = _subject_or_400(payload.subject)
    if not _student_exists(db, payload.student_id):
        return _empty_start(payload.student_id)
    data = _safe(db, lambda: ENGINE.start(db, payload.student_id, subject=subject or None,
                                          count=payload.count),
                 _empty_start(payload.student_id))
    data["student_id"] = payload.student_id
    return data


@router.post("/answer")
def recall_answer(payload: AnswerIn, db: Session = Depends(get_db)):
    """提交主动回忆：判分 + 记忆增益 + 儿童反馈；完全独立回忆成功增益最高。"""
    if not _student_exists(db, payload.student_id):
        return _empty_answer(payload.student_id)
    if not str(payload.card_id or "").strip() or not str(payload.answer or "").strip():
        return _empty_answer(payload.student_id)
    data = _safe(db, lambda: ENGINE.answer(
        db, payload.student_id, payload.card_id, payload.answer,
        response_time=payload.response_time, hint_level=payload.hint_level,
        confidence_feedback=payload.confidence_feedback), None)
    if not data:
        return _empty_answer(payload.student_id)
    data["deep_mastery"] = _record_deep_evidence(db, payload, data)
    return data


@router.post("/hint")
def recall_hint(payload: HintIn, db: Session = Depends(get_db)):
    """取回忆提示：一级一级来，学生用了哪一级提示会被记下来（无提示成功证据最强）。"""
    if not _student_exists(db, payload.student_id):
        return _empty_hint(payload.student_id, payload.level)
    if not str(payload.card_id or "").strip():
        return _empty_hint(payload.student_id, payload.level)
    data = _safe(db, lambda: ENGINE.hint(payload.card_id, payload.level), None)
    if not data:
        return _empty_hint(payload.student_id, payload.level)
    data["student_id"] = payload.student_id
    return data


@router.get("/summary")
def recall_summary(student_id: int = Query(..., ge=1), date: str = "",
                   db: Session = Depends(get_db)):
    """当天主动回忆小结：总数 / 正确 / 部分 / 未想起 / 时长 / 明细。"""
    day = _day_or_400(date)
    if not _student_exists(db, student_id):
        return _empty_summary(student_id, day)
    data = _safe(db, lambda: ENGINE.summary(db, student_id, day=day or None),
                 _empty_summary(student_id, day))
    data["student_id"] = student_id
    return data
