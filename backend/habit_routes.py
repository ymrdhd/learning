# ==============================================================
# 能力契约｜/api/habit/* 学习习惯接口（画像：连续天数·完成率·时长·徽章 / 近 N 天曲线）
# 入口：router / habit_profile / habit_stats / habit_calendar / habit_profile_path / habit_rest_status / habit_rest_use / habit_goal
# 依赖：habit（DEFAULT_ENGINE / LEVEL_TEXT / BADGE_CATALOG）、database.get_db
# 不负责：习惯算法与任务生成 → habit.py；今日任务接口 → task_routes.py；错题康复 → recovery_routes.py
# 验证：python backend/verify_habit.py（Agent 7 门禁）
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 每日学习习惯 API（SPEC §7.2 后半）。

    GET /api/habit/profile   习惯画像（连续天数 / 最长连续 / 完成率 / 时长 / 等级 / 徽章 / 近 7 天）
    GET /api/habit/stats     近 N 天完成率与时长序列

纪律：按 ``student_id`` 过滤（A=1 / B=2 隔离）；学生不存在时返回**空结构**（全 0 + 徽章未获得）
而不是 404；``date`` 必须是 ``YYYY-MM-DD``，非法值返回 400；内部异常一律兜住 → 绝不 500。
"""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import habit
from database import get_db

router = APIRouter(prefix="/api/habit", tags=["每日习惯 V2.5"])

ENGINE = habit.DEFAULT_ENGINE

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


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


def _zero_badges():
    return [{"key": key, "name": name, "icon": icon, "got": False}
            for key, name, icon in habit.BADGE_CATALOG]


def _empty_profile(student_id):
    return {"student_id": student_id, "current_streak": 0, "longest_streak": 0,
            "total_days": 0, "total_tasks": 0, "completed_tasks": 0,
            "completion_rate": 0.0, "total_minutes": 0, "today_minutes": 0,
            "level": 1, "level_text": habit.LEVEL_TEXT.get(1, ""),
            "badges": _zero_badges(), "last_active_date": "", "recent": []}


def _empty_stats(student_id, days):
    return {"student_id": student_id, "days": days, "items": [],
            "avg_rate": 0.0, "total_minutes": 0}


@router.get("/profile")
def habit_profile(student_id: int = Query(..., ge=1), date: str = "",
                  db: Session = Depends(get_db)):
    """习惯画像：连续打卡天数、完成率、累计/今日时长、等级、徽章与近 7 天曲线。"""
    day = _day_or_400(date)
    data = _safe(db, lambda: ENGINE.profile(db, student_id, date=day or None),
                 _empty_profile(student_id))
    data["student_id"] = student_id
    return data


def _month_or_400(value):
    """月份参数统一 ``YYYY-MM``；空串表示"这个月"。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if not MONTH_RE.match(text):
        raise HTTPException(status_code=400, detail="month 必须是 YYYY-MM")
    try:
        datetime.strptime(text, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="month 必须是 YYYY-MM") from None
    return text


def _empty_calendar(student_id, month):
    return {"student_id": student_id, "month": str(month or _today_text())[:7],
            "first_weekday": 0, "days_in_month": 0, "checked_count": 0,
            "today": _today_text(), "items": []}


@router.get("/calendar")
def habit_calendar(student_id: int = Query(..., ge=1), month: str = "", date: str = "",
                   db: Session = Depends(get_db)):
    """学习日历：当月每天的打卡情况（打卡 = 当天完成过任务；完成即自动打卡）。"""
    day = _day_or_400(date)
    wanted = _month_or_400(month)
    data = _safe(db,
                 lambda: ENGINE.calendar(db, student_id, month=wanted or None,
                                         date=day or None),
                 _empty_calendar(student_id, wanted or day))
    data["student_id"] = student_id
    return data


@router.get("/stats")
def habit_stats(student_id: int = Query(..., ge=1), days: int = Query(7, ge=1, le=90),
                date: str = "", db: Session = Depends(get_db)):
    """近 ``days`` 天（含 ``date``，默认今天）的完成 / 总任务 / 时长 / 完成率序列。"""
    day = _day_or_400(date)
    data = _safe(db, lambda: ENGINE.stats(db, student_id, days=days, date=day or None),
                 _empty_stats(student_id, days))
    data["student_id"] = student_id
    data["days"] = int(days)
    return data


# ---------- V2.5 兼容入口（需求 §18 / §25：path 形式 + 休息保护 + SYSTEM 学习目标） ----------

from pydantic import BaseModel, Field  # noqa: E402


class RestIn(BaseModel):
    student_id: int = Field(..., ge=1)
    date: str = ""


@router.get("/profile/{student_id}")
def habit_profile_path(student_id: int, date: str = "", db: Session = Depends(get_db)):
    """path 形式（等价 ``GET /api/habit/profile?student_id=``）：习惯画像。"""
    day = _day_or_400(date)
    data = _safe(db, lambda: ENGINE.profile(db, student_id, date=day or None),
                 _empty_profile(student_id))
    data["student_id"] = student_id
    return data


@router.get("/rest/{student_id}")
def habit_rest_status(student_id: int, date: str = "", db: Session = Depends(get_db)):
    """休息保护状态：本月已用 / 剩余（每月上限 2 次，不打断连续学习）。"""
    day = _day_or_400(date)
    empty = {"date": day or _today_text(), "month": (day or _today_text())[:7],
             "rest_protection_count": 0, "rest_protection_left": 2, "rest_protection_limit": 2}
    data = _safe(db, lambda: ENGINE.rest_status(db, student_id, date=day or None), empty)
    data["student_id"] = student_id
    return data


@router.post("/rest")
def habit_rest_use(payload: RestIn, db: Session = Depends(get_db)):
    """使用一次休息保护：不打断连续学习，也不清零任何历史成长（且不可付费购买）。"""
    day = _day_or_400(payload.date)
    empty = {"ok": False, "reason": "暂时无法使用休息保护", "rest_protection_count": 0,
             "rest_protection_left": 0}
    data = _safe(db, lambda: ENGINE.use_rest_protection(db, payload.student_id, date=day or None),
                 empty)
    data["student_id"] = payload.student_id
    return data


@router.get("/goal/{student_id}")
def habit_goal(student_id: int, db: Session = Depends(get_db)):
    """当前学习目标（本版本只启用 SYSTEM 来源；PARENT / STUDENT 预留）。"""
    empty = {"text": "", "source": "SYSTEM", "subject": "", "knowledge": ""}
    data = _safe(db, lambda: ENGINE.goal(db, student_id), empty)
    data["student_id"] = student_id
    return data
