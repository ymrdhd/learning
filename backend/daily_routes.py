# ==============================================================
# 能力契约｜/api/daily-summary/{student_id} 每日总结（今日完成页 + 儿童成长反馈 + 学习目标）
# 入口：router / daily_summary
# 依赖：habit（DEFAULT_ENGINE.today / profile）、active_recall（DEFAULT_ENGINE.summary）、
#       recovery.scheduler（DEFAULT_SCHEDULER.summarize）、models（Student / WrongQuestionRecovery）、database.get_db
# 不负责：任务生成与配比算法 → habit.py；主动回忆判分 → active_recall.py；错题康复状态机 → recovery/
# 验证：python backend/verify_active_recall.py（含每日总结用例）
# 被调用：main.py（注册 router）、frontend/daily.html
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 每日总结 API（需求 §18-§20、§23-§24）。

    GET /api/daily-summary/{student_id}   今日完成情况 + 儿童版成长反馈 + 学习目标（SYSTEM）

孩子看到的只有四档成长反馈（🌱 正在学习 / 🌿 基本会了 / 🌳 已经掌握 / ⭐ 记得很牢）与
「今天完成啦」的结束文案；真实数值只出现在 debug / 家长字段里。

纪律：按 ``student_id`` 隔离；学生不存在返回 200 空结构；``date`` 非法返回 400；异常兜住 → 不 500。
"""

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import active_recall
import habit
from database import get_db
from models import Student, WrongQuestionRecovery
from recovery.scheduler import DEFAULT_SCHEDULER as RECOVERY_SCHEDULER

router = APIRouter(prefix="/api", tags=["每日总结 V2.5"])

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FINISH_TEXT = "🎉 今天完成啦！"
REST_TEXT = "今天可以休息啦！"
KEEP_GOING_TEXT = "今天的任务还没做完，加油～"

TASK_ICON = {
    "new_learning": "🌱",
    "weakness": "🌿",
    "review": "🌳",
    "wrong_recovery": "⚔️",
    "active_recall": "🧠",
}

TASK_UNIT = {
    "new_learning": ("学会", "个新知识"),
    "weakness": ("补强", "个薄弱点"),
    "review": ("巩固", "个旧知识"),
    "wrong_recovery": ("攻克", "道错题"),
    "active_recall": ("主动回忆", "张卡"),
}


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


def _student_exists(db, student_id):
    try:
        return db.query(Student).filter(Student.id == student_id).first() is not None
    except Exception:                          # noqa: BLE001
        return False


def _empty_task_summary():
    return {"total": 0, "done": 0, "pending": 0, "completion_rate": 0.0, "minutes": 0,
            "mix": {key: 0 for key in habit.MIX}, "mix_tasks": {key: 0 for key in habit.MIX}}


def _empty_goal():
    return {"text": "", "source": "SYSTEM", "subject": "", "knowledge": "", "kind": TASK_ICON["new_learning"]}


def _empty_summary(student_id, day=None):
    return {
        "student_id": student_id,
        "date": day or _today_text(),
        "finished": False,
        "message": KEEP_GOING_TEXT,
        "rest_text": REST_TEXT,
        "child": {"new_learning": 0, "weakness": 0, "review": 0, "wrong_recovery": 0,
                  "active_recall": 0, "minutes": 0},
        "lines": [],
        "tasks": _empty_task_summary(),
        "habit": {},
        "recall": {"total": 0, "correct": 0, "partial": 0, "wrong": 0, "accuracy": 0.0,
                   "minutes": 0, "items": []},
        "recovery": {"total": 0, "mastered": 0, "mastered_today": 0},
        "goal": _empty_goal(),
        "debug": {"task_summary": _empty_task_summary(), "profile": {}},
    }


def _tasks_of(db, student_id, day=None):
    today = _safe(db, lambda: habit.DEFAULT_ENGINE.today(db, student_id, date=day or None), None)
    if not today:
        return _empty_task_summary()
    return today.get("summary") or _empty_task_summary()


def _profile_of(db, student_id, day=None):
    data = _safe(db, lambda: habit.DEFAULT_ENGINE.profile(db, student_id, date=day or None), None)
    return data or {}


def _recall_of(db, student_id, day=None):
    return _safe(db, lambda: active_recall.DEFAULT_ENGINE.summary(db, student_id, day=day or None),
                 {"total": 0, "correct": 0, "partial": 0, "wrong": 0, "accuracy": 0.0,
                  "minutes": 0, "items": []})


def _mastered_today(db, student_id, day=None):
    if day:
        start = datetime.strptime(str(day)[:10], "%Y-%m-%d")
    else:
        now = datetime.now()
        start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    try:
        return db.query(WrongQuestionRecovery).filter(
            WrongQuestionRecovery.student_id == student_id,
            WrongQuestionRecovery.mastered_time >= start,
            WrongQuestionRecovery.mastered_time < end).count()
    except Exception:                          # noqa: BLE001
        return 0


def _recovery_of(db, student_id, day=None):
    data = _safe(db, lambda: RECOVERY_SCHEDULER.summarize(db, student_id), None) or {}
    result = {"total": int(data.get("total") or 0),
              "mastered": int(data.get("mastered") or 0),
              "mastered_today": _mastered_today(db, student_id, day)}
    for key in ("new", "analyzing", "learning", "practicing", "verifying"):
        if key in data:
            result[key] = data[key]
    return result


def _goal_of(db, student_id):
    method = getattr(habit.DEFAULT_ENGINE, "goal", None)
    if callable(method):
        data = _safe(db, lambda: method(db, student_id), None)
        if data:
            return data
    return _empty_goal()


def _counts_of(tasks, recall, recovery):
    """今日各类完成数：任务类看 COMPLETED 任务，主动回忆看卡片，错题看今日 MASTERED。"""
    done = {"new_learning": 0, "weakness": 0, "review": 0}
    try:
        for item in tasks.get("tasks") or []:
            key = item.get("task_type")
            if key in done and item.get("status") == "done":
                done[key] += 1
    except Exception:                          # noqa: BLE001
        pass
    done["wrong_recovery"] = int(recovery.get("mastered_today") or 0)
    done["active_recall"] = int(recall.get("total") or 0)
    return done


def _lines_of(counts, minutes):
    lines = []
    for key in ("new_learning", "weakness", "review", "wrong_recovery", "active_recall"):
        value = int(counts.get(key) or 0)
        if value <= 0:
            continue
        verb, unit = TASK_UNIT.get(key, ("完成", "个任务"))
        lines.append(f"{TASK_ICON.get(key, '✅')} {verb}{value}{unit}")
    lines.append(f"⏱ 学习{int(minutes or 0)}分钟")
    return lines


@router.get("/daily-summary/{student_id}")
def daily_summary(student_id: int, date: str = "", db: Session = Depends(get_db)):
    """今天的完整收尾：任务汇总 + 习惯画像 + 主动回忆 + 错题康复 + 儿童版反馈 + 学习目标。"""
    day = _day_or_400(date)
    if student_id < 1 or not _student_exists(db, student_id):
        return _empty_summary(student_id, day)

    today = _safe(db, lambda: habit.DEFAULT_ENGINE.today(db, student_id, date=day or None), None) or {}
    tasks = today.get("summary") or _empty_task_summary()
    tasks["tasks"] = today.get("tasks") or []
    profile = _profile_of(db, student_id, day)
    recall = _recall_of(db, student_id, day)
    recovery = _recovery_of(db, student_id, day)

    counts = _counts_of(tasks, recall, recovery)
    minutes = int(profile.get("today_minutes") or 0)
    total = int(tasks.get("total") or 0)
    done = int(tasks.get("done") or 0)
    finished = bool(total) and done >= total

    return {
        "student_id": student_id,
        "date": today.get("date") or day or _today_text(),
        "finished": finished,
        "message": FINISH_TEXT if finished else KEEP_GOING_TEXT,
        "rest_text": REST_TEXT if finished else "",
        "child": {**counts, "minutes": minutes},
        "lines": _lines_of(counts, minutes) if finished else [],
        "tasks": tasks,
        "habit": profile,
        "recall": recall,
        "recovery": recovery,
        "goal": _goal_of(db, student_id),
        "debug": {"task_summary": {key: value for key, value in tasks.items() if key != "tasks"},
                  "profile": {"current_streak": profile.get("current_streak", 0),
                              "completion_rate": profile.get("completion_rate", 0.0),
                              "total_minutes": profile.get("total_minutes", 0)}},
    }
