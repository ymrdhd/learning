# ==============================================================
# 能力契约｜/api/tasks/* 每日学习任务接口（今日三段任务 + 上报完成 / 时长 / 数量）
# 入口：router / tasks_today / tasks_complete / tasks_today_path / tasks_plan / tasks_start / tasks_complete_path
# 依赖：habit（DEFAULT_ENGINE / MIX / STATUS_TEXT）、database.get_db
# 不负责：任务生成、习惯画像与奖励 → habit.py；习惯查询接口 → habit_routes.py；错题康复 → recovery_routes.py
# 验证：python backend/verify_habit.py（Agent 7 门禁）
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 每日任务 API（SPEC §7.2 前半）。

    GET  /api/tasks/today     今日任务（首次访问即生成，幂等）：三段混排 + 汇总
    POST /api/tasks/complete  上报完成（minutes / count / done），返回任务与当日汇总 + 习惯画像

纪律：按 ``student_id`` 过滤（A=1 / B=2 隔离）；学生不存在或任务不属于该学生时返回**空结构**
而不是 404，且不泄露他人任务；``date`` 非法返回 400；内部异常一律兜住 → 绝不 500。
"""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import habit
from database import get_db

router = APIRouter(prefix="/api/tasks", tags=["每日任务 V2.5"])

ENGINE = habit.DEFAULT_ENGINE

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CompleteIn(BaseModel):
    student_id: int = Field(..., ge=1)
    task_id: int = Field(0, ge=0)
    minutes: int = Field(0, ge=0, le=1440)
    count: int = Field(0, ge=0)
    done: bool = True


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


def _empty_summary():
    mix = {key: 0 for key in habit.MIX}
    if not mix:
        mix = {key: 0 for key in habit.TYPE_ORDER}
    mix.setdefault("new_learning", 0)
    mix.setdefault("weakness", 0)
    mix.setdefault("review", 0)
    return {"total": 0, "done": 0, "pending": 0, "completion_rate": 0.0,
            "minutes": 0, "mix": mix}


def _empty_today(student_id, day=None):
    return {"student_id": student_id, "date": day or _today_text(),
            "generated": False, "tasks": [], "summary": _empty_summary()}


def _summary_of(db, student_id):
    today = _safe(db, lambda: ENGINE.today(db, student_id), None) or {}
    return today.get("summary") or _empty_summary()


def _profile(db, student_id):
    return _safe(db, lambda: ENGINE.profile(db, student_id), {"student_id": student_id})


def _award_task_points(db, student_id, task_id, data):
    """V2.8：任务收工（status=done）时给积分，同一项只记一次；积分出问题绝不影响任务接口返回。"""
    try:
        import points

        if (data or {}).get("status") == "done":
            points.award_task_done(db, student_id, task_id, status="done")
    except Exception:                              # noqa: BLE001 - 兜底，任务接口照常返回
        db.rollback()


@router.get("/today")
def tasks_today(student_id: int = Query(..., ge=1), date: str = "",
                db: Session = Depends(get_db)):
    """今日任务：``{student_id, date, generated, tasks[], summary{total,done,pending,completion_rate,minutes,mix}}``。"""
    day = _day_or_400(date)
    data = _safe(db, lambda: ENGINE.today(db, student_id, date=day or None),
                 _empty_today(student_id, day))
    data["student_id"] = student_id
    return data


@router.post("/complete")
def tasks_complete(payload: CompleteIn, db: Session = Depends(get_db)):
    """上报任务完成：``minutes`` / ``count`` / ``done``；返回任务状态、当日汇总与习惯画像。"""
    empty = {"student_id": payload.student_id, "task_id": payload.task_id,
             "status": "", "status_text": "", "complete_count": 0, "duration_minutes": 0,
             "summary": _summary_of(db, payload.student_id), "profile": _profile(db, payload.student_id)}
    if not payload.task_id:
        return empty

    data = _safe(db, lambda: ENGINE.complete_task(
        db, payload.student_id, payload.task_id, minutes=payload.minutes,
        count=payload.count or None, done=payload.done), None)
    if not data:
        return empty

    today = _safe(db, lambda: ENGINE.today(db, payload.student_id), None) or {}
    data["student_id"] = payload.student_id
    data["summary"] = today.get("summary") or _empty_summary()
    data["profile"] = _profile(db, payload.student_id)
    _award_task_points(db, payload.student_id, payload.task_id, data)
    return data


# ---------- V2.5 兼容入口（需求 §25 的 path 形式，语义与上面完全一致，不建第二套） ----------


class StartIn(BaseModel):
    student_id: int = Field(..., ge=1)
    date: str = ""
    minutes: int = Field(0, ge=0, le=1440)


class TaskCompleteIn(BaseModel):
    student_id: int = Field(..., ge=1)
    minutes: int = Field(0, ge=0, le=1440)
    count: int = Field(0, ge=0)
    done: bool = True


@router.get("/today/{student_id}")
def tasks_today_path(student_id: int, date: str = "", db: Session = Depends(get_db)):
    """path 形式（等价 ``GET /api/tasks/today?student_id=``）：今日任务。"""
    day = _day_or_400(date)
    data = _safe(db, lambda: ENGINE.today(db, student_id, date=day or None),
                 _empty_today(student_id, day))
    data["student_id"] = student_id
    return data


@router.get("/plan/{student_id}")
def tasks_plan(student_id: int, date: str = "", minutes: int = Query(0, ge=0, le=1440),
               db: Session = Depends(get_db)):
    """今日计划预览（开始前）：五段任务 + 分钟数（只读，不落库）。"""
    day = _day_or_400(date)
    empty = {"student_id": student_id, "date": day or _today_text(), "items": [],
             "minutes": 0, "message": "", "goal": {}, "adjust": []}
    return _safe(db, lambda: ENGINE.plan(db, student_id, date=day or None,
                                         minutes=minutes or None), empty)


@router.post("/start")
def tasks_start(payload: StartIn, db: Session = Depends(get_db)):
    """孩子点「开始今天的学习」：三段任务 + 五段计划落库（幂等）并返回任务与汇总。"""
    day = _day_or_400(payload.date)
    empty = {"student_id": payload.student_id, "date": day or _today_text(), "minutes": 0,
             "message": "", "plan": {"items": []}, "tasks": [], "summary": _empty_summary()}
    return _safe(db, lambda: ENGINE.start_today(db, payload.student_id, date=day or None,
                                                minutes=payload.minutes or None), empty)


@router.post("/{task_id}/complete")
def tasks_complete_path(task_id: int, payload: TaskCompleteIn, db: Session = Depends(get_db)):
    """path 形式（等价 ``POST /api/tasks/complete``）：上报任务完成。"""
    empty = {"student_id": payload.student_id, "task_id": task_id, "status": "",
             "status_text": "", "complete_count": 0, "duration_minutes": 0,
             "summary": _summary_of(db, payload.student_id),
             "profile": _profile(db, payload.student_id)}
    if task_id <= 0:
        return empty
    data = _safe(db, lambda: ENGINE.complete_task(
        db, payload.student_id, task_id, minutes=payload.minutes,
        count=payload.count or None, done=payload.done), None)
    if not data:
        return empty
    today = _safe(db, lambda: ENGINE.today(db, payload.student_id), None) or {}
    data["student_id"] = payload.student_id
    data["summary"] = today.get("summary") or _empty_summary()
    data["profile"] = _profile(db, payload.student_id)
    _award_task_points(db, payload.student_id, task_id, data)
    return data
