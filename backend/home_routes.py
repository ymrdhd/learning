# ==============================================================
# 能力契约｜/api/home/{student_id} 儿童首页聚合接口（今天要做什么，一次拿全）
# 入口：router / home / growth_highlight / phoebe_message / deep_plan
# 依赖：habit（DEFAULT_ENGINE.plan/today）、review.engine（DEFAULT_ENGINE.today）、
#       deep_learning.engine（DEFAULT_ENGINE.plan_hint/growth，可选，失败即降级）、
#       recovery.scheduler（DEFAULT_SCHEDULER.summarize）、kid_status、models、database.get_db
# 不负责：任务配比 → habit.py；复习队列 → review/；康复状态机 → recovery/；儿童语言 → kid_status.py
# 验证：python backend/verify_v26.py（含首页聚合用例）
# 被调用：main.py（注册 router）、frontend/today.html（today.js）
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================
"""V2.6 首页聚合 API（需求 §10）。

    GET /api/home/{student_id}?date=YYYY-MM-DD

一次返回"今天要做什么"需要的全部数据：学生、今日计划、今日进度、待复习数、待攻克挑战数、
一个成长亮点、菲比问候语。**不实现任何新算法**，全部复用 V2.0~V2.5 已有引擎；
算法原始数值只出现在 ``debug`` 里，儿童端默认不展示。

纪律：按 ``student_id`` 隔离；学生不存在返回 200 空结构；``date`` 非法返回 400；
内部异常一律兜住 → 绝不 500；本接口只读（``plan(persist=False)``）。
"""

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import habit
import kid_status
from database import get_db
from models import Student, StudentKnowledgeMastery, WrongQuestionRecovery
from recovery.scheduler import DEFAULT_SCHEDULER as RECOVERY_SCHEDULER
from review import engine as review_engine
from deep_learning.engine import DEFAULT_ENGINE as DEEP_ENGINE

router = APIRouter(prefix="/api", tags=["首页聚合 V2.6"])

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REVIEW_ENGINE = review_engine.DEFAULT_ENGINE

START_LABEL = "开始今天的学习"
EMPTY_HIGHLIGHT = "今天完成第一个小任务，就会看到成长啦！"
# ---------------- V2.7 深度学习任务（需求 §三十 / §三十一 ----------------
# 新增任务类型：不强制每天都出现，由 plan_hint 根据学生状态选择（最多 2 个），
# 且增量时长不超过原预算的 40%——深度学习**不扩张**今日总时长，只在预算内重新分配。
DEEP_TASK_TEXT = {
    "PREREQUISITE_REPAIR": "补一个小基础",
    "TRANSFER": "换个说法再试试",
    "ACTIVE_RECALL": "先自己回忆一遍",
    "EXPLAIN": "讲给菲比听",
}
DEEP_TASK_ICON = {
    "PREREQUISITE_REPAIR": "🧩",
    "TRANSFER": "🔀",
    "ACTIVE_RECALL": "🧠",
    "EXPLAIN": "🗣",
}
DEEP_TIME_RATIO = 1.4          # 硬上限：含深度任务的今日总时长 ≤ 原预算 × 1.4
MIN_DEEP_ITEMS = 1             # 计划里一条任务都没有时不塞深度任务
DEEP_GROWTH_DAYS = 7           # 首页「深度成长」统计窗口（与成长中心同口径）
DEEP_EMPTY_GROWTH = {"active_count": 0, "apply_count": 0, "apply_total": 0,
                    "star_count": 0, "new_star_count": 0, "items": [], "stars": [],
                    "child_text": ""}


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


def _icon_of(task_type):
    """任务类型 → 图标（复用 habit 的展示表，缺失时给中性图标）。"""
    return (getattr(habit, "PLAN_ICON", None) or {}).get(task_type) or "✅"


def _minutes_of_row(row):
    """落库任务的时长：已发生时长 → 目标时长 → 按题量估算（至少 1 分钟）。"""
    for key in ("duration_minutes", "target_minutes", "minutes"):
        value = int(row.get(key) or 0)
        if value > 0:
            return value
    return max(1, int(row.get("target_count") or 1) // 2)


def deep_plan(db, student_id, plan):
    """V2.7：在**不扩张今日总时长**的前提下，把深度学习任务插进今日计划。

    需求 §三十：允许 Daily Plan 出现 TRANSFER / ACTIVE_RECALL / EXPLAIN /
    PREREQUISITE_REPAIR 四类新任务，但**每天不要全部强制出现**，由学生状态决定；
    需求 §三十一：深度学习不能无限拉长 Session 时间——本函数保证
    ``原预算 + 增量 ≤ 原预算 × DEEP_TIME_RATIO``，超出的一律不要（剩余任务自然推迟）。

    返回 (plan, deep)：``plan`` 是被补上深度任务的计划字典；任何异常都退回原计划。
    """
    out = dict(plan or {})
    items = list(out.get("items") or [])
    minutes = int(out.get("minutes") or 0)
    empty = {"tasks": [], "extra_minutes": 0, "minutes": minutes,
             "note": "今天没有额外的深度学习任务，按上面的安排来就好。"}
    if student_id < 1 or len(items) < MIN_DEEP_ITEMS or minutes <= 0:
        out["deep"] = empty
        return out, empty

    hint = _safe(db, lambda: DEEP_ENGINE.plan_hint(db, student_id, minutes=minutes), {}) or {}
    tasks = list(hint.get("tasks") or [])
    focus = hint.get("focus") or {}
    cap = int(round(minutes * DEEP_TIME_RATIO))
    extra = 0
    added = []
    for task in tasks:
        task_type = str(task.get("task_type") or "")
        cost = max(1, int(task.get("minutes") or 0))
        if minutes + extra + cost > cap:
            continue
        if task_type not in DEEP_TASK_TEXT:
            continue
        extra += cost
        added.append({
            "task_type": task_type,
            "task_type_text": DEEP_TASK_TEXT[task_type],
            "icon": DEEP_TASK_ICON[task_type],
            "title": "{0}·{1}".format(DEEP_TASK_TEXT[task_type],
                                      focus.get("knowledge") or ""),
            "subject": focus.get("subject") or "",
            "knowledge": focus.get("knowledge") or "",
            "minutes": cost,
            "target_count": 1,
            "goal": task.get("reason") or "",
            "deep": True,
        })
    if not added:
        out["deep"] = empty
        return out, empty

    items.extend(added)
    total = minutes + extra
    out["items"] = items
    out["minutes"] = total
    out["message"] = "今天我们用 {0} 分钟完成 {1} 个小任务，其中有 {2} 个是菲比特意为你准备的。".format(
        total, len(items), len(added))
    deep = {
        "tasks": [item["task_type"] for item in added],
        "extra_minutes": extra,
        "minutes": total,
        "budget_minutes": minutes,
        "budget_cap": cap,
        "reasons": list(hint.get("reasons") or []),
        "focus": focus,
        "items": added,
        "note": hint.get("note") or "",
    }
    out["deep"] = deep
    return out, deep


def _student_of(db, student_id):
    try:
        row = db.query(Student).filter(Student.id == student_id).first()
    except Exception:                          # noqa: BLE001
        return None
    if row is None:
        return None
    return {"id": int(row.id), "name": row.name or "", "avatar": row.avatar or "🐼",
            "grade": int(row.grade or 1), "grade_text": _grade_text(row.grade)}


def _grade_text(grade):
    try:
        number = int(grade or 1)
    except (TypeError, ValueError):
        number = 1
    names = {1: "一年级", 2: "二年级", 3: "三年级", 4: "四年级", 5: "五年级", 6: "六年级"}
    return names.get(number, "{0}年级".format(number))



def _plan_of(db, student_id, day, student=None, progress=None):
    """今日计划：已经开始学习就报真实任务清单，还没开始就给只读预览（不落库）。"""
    rows = (progress or {}).get("tasks") or []
    if rows:
        items = []
        for row in rows:
            items.append({"task_type": row.get("task_type") or "",
                          "task_type_text": row.get("task_type_text") or "",
                          "icon": _icon_of(row.get("task_type")),
                          "title": row.get("title") or "",
                          "subject": row.get("subject") or "",
                          "knowledge": row.get("knowledge") or "",
                          "minutes": _minutes_of_row(row),
                          "target_count": int(row.get("target_count") or 0),
                          "goal": row.get("goal") or ""})
        minutes = sum(item["minutes"] for item in items)
        return {"student_id": student_id,
                "date": (progress or {}).get("date") or day or _today_text(),
                "grade": int((student or {}).get("grade") or 1),
                "minutes": minutes, "target_minutes": minutes,
                "message": "今天我们用 {0} 分钟完成 {1} 个小任务。".format(minutes, len(items)),
                "items": items, "goal": {}, "adjust": [],
                # 已经开始学习：按真实落库任务清单走，深度任务只在开写前的计划里出示
                "deep": {"tasks": [], "extra_minutes": 0, "minutes": minutes,
                         "note": "今天的深度学习任务在选择计划时出示。"}}
    data = _safe(db, lambda: habit.DEFAULT_ENGINE.plan(db, student_id, date=day or None), None)
    if not data:
        return {"student_id": student_id, "date": day or _today_text(), "minutes": 0,
                "items": [], "message": "", "goal": {}, "adjust": [],
                "deep": {"tasks": [], "extra_minutes": 0, "minutes": 0, "note": ""}}
    items = []
    for item in data.get("items") or []:
        items.append({"task_type": item.get("task_type") or "",
                      "task_type_text": item.get("task_type_text") or "",
                      "icon": item.get("icon") or "✅",
                      "title": item.get("title") or "",
                      "subject": item.get("subject") or "",
                      "knowledge": item.get("knowledge") or "",
                      "minutes": int(item.get("minutes") or 0),
                      "target_count": int(item.get("target_count") or 0),
                      "goal": item.get("goal") or ""})
    plan = {"student_id": student_id, "date": data.get("date") or day or _today_text(),
            "grade": int(data.get("grade") or 1),
            "minutes": int(data.get("minutes") or 0),
            "target_minutes": int(data.get("target_minutes") or 0),
            "message": data.get("message") or "",
            "items": items,
            "goal": data.get("goal") or {},
            "adjust": list(data.get("adjust") or [])}
    plan, _deep = deep_plan(db, student_id, plan)
    return plan


def _progress_of(db, student_id, day):
    """今日已完成情况：任务表实况（含错题康复 / 主动回忆两类落库任务）。"""
    data = _safe(db, lambda: habit.DEFAULT_ENGINE.today(db, student_id, date=day or None), None) or {}
    summary = data.get("summary") or {}
    total = int(summary.get("total") or 0)
    done = int(summary.get("done") or 0)
    return {"date": data.get("date") or day or _today_text(),
            "total": total, "done": done, "pending": max(0, total - done),
            "minutes": int(summary.get("minutes") or 0),
            "completion_rate": float(summary.get("completion_rate") or 0.0),
            "percent": int(round(100.0 * done / total)) if total else 0,
            "finished": bool(total) and done >= total,
            "tasks": data.get("tasks") or []}


def _review_due(db, student_id):
    """待复习知识点数（复用 V2.4 复习队列，不重算算法）。"""
    data = _safe(db, lambda: REVIEW_ENGINE.today(db, student_id), None)
    if not data:
        return {"due_count": 0, "relearn_count": 0, "text": kid_status.no_review_text()}
    remaining = int(data.get("remaining") or 0)
    relearn = len(data.get("relearn") or [])
    return {"due_count": remaining, "relearn_count": relearn,
            "text": (kid_status.forgetting_text(remaining + relearn) if (remaining + relearn)
                     else kid_status.no_review_text())}


def _recovery_of(db, student_id):
    """挑战中心概要（复用 V2.5 康复调度器）。todo = 还没攻克的数量。"""
    data = _safe(db, lambda: RECOVERY_SCHEDULER.summarize(db, student_id), None) or {}
    total = int(data.get("total") or 0)
    mastered = int(data.get("mastered") or 0)
    return {"total": total, "mastered": mastered, "todo": max(0, total - mastered),
            "red": int(data.get("new") or 0) + int(data.get("analyzing") or 0),
            "yellow": (int(data.get("learning") or 0) + int(data.get("practicing") or 0)
                       + int(data.get("verifying") or 0)),
            "green": mastered}


def growth_highlight(db, student_id):
    """一个简单成长亮点（需求 §9）：只讲"学会了 / 记住了 / 攻克了"，不讲使用量。

    顺序：昨天攻克的挑战 → 最近进入长期记忆的知识 → 最近练成"已经掌握"的知识 →
    连续学习天数。全部来自真实学习数据；没有任何记录时给启动引导文案。
    """
    recent = _safe(db, lambda: (
        db.query(WrongQuestionRecovery)
        .filter(WrongQuestionRecovery.student_id == student_id,
                WrongQuestionRecovery.mastered_time.isnot(None),
                WrongQuestionRecovery.mastered_time >= datetime.now() - timedelta(days=2))
        .order_by(WrongQuestionRecovery.mastered_time.desc()).first()), None)
    if recent is not None:
        when = "今天" if str(recent.mastered_time)[:10] == _today_text() else "昨天"
        name = recent.knowledge_id or recent.subject or "一个挑战"
        return {"kind": "challenge", "icon": "⚔️",
                "text": "{0}你攻克了「{1}」！".format(when, name)}

    since = datetime.now() - timedelta(days=3)
    long_term = _safe(db, lambda: (
        db.query(StudentKnowledgeMastery)
        .filter(StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.mastery_score >= 90,
                StudentKnowledgeMastery.updated_time.isnot(None),
                StudentKnowledgeMastery.updated_time >= since)
        .order_by(StudentKnowledgeMastery.updated_time.desc()).first()), None)
    if long_term is not None:
        return {"kind": "memory", "icon": "⭐",
                "text": "⭐ 「{0}」你已经记得很牢啦！".format(long_term.knowledge_point_id)}

    mastered = _safe(db, lambda: (
        db.query(StudentKnowledgeMastery)
        .filter(StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.mastery_score >= 75,
                StudentKnowledgeMastery.updated_time.isnot(None),
                StudentKnowledgeMastery.updated_time >= since)
        .order_by(StudentKnowledgeMastery.updated_time.desc()).first()), None)
    if mastered is not None:
        return {"kind": "mastered", "icon": "🌳",
                "text": "🌳 「{0}」你已经掌握了！".format(mastered.knowledge_point_id)}

    profile = _safe(db, lambda: habit.DEFAULT_ENGINE.profile(db, student_id), None) or {}
    streak = int(profile.get("current_streak") or 0)
    if streak >= 2:
        return {"kind": "streak", "icon": "📅",
                "text": "你已经连续学习 {0} 天啦！".format(streak)}
    return {"kind": "none", "icon": "🌱", "text": EMPTY_HIGHLIGHT}


def phoebe_message(plan, progress, review, recovery):
    """菲比这一屏只说一句话（需求 §11 / §31），并给出头像状态。"""
    minutes = int(plan.get("minutes") or 0)
    count = len(plan.get("items") or [])
    if progress.get("finished"):
        return {"text": "今天已经完成啦，可以去休息了！", "state": "happy"}
    if progress.get("done"):
        return {"text": "已经完成 {0}/{1} 个任务，继续加油！".format(
            progress.get("done"), progress.get("total")), "state": "encourage"}
    if count:
        return {"text": "今天我们用 {0} 分钟完成 {1} 个小任务。".format(minutes, count),
                "state": "normal"}
    if review.get("due_count") or recovery.get("todo"):
        return {"text": "今天没有固定计划，先把需要照顾的知识看一眼吧。", "state": "thinking"}
    return {"text": "今天没有安排任务，可以自由练习一会儿。", "state": "normal"}


def _empty_home(student_id, day=None):
    return {"student_id": student_id, "date": day or _today_text(), "student": {},
            "daily_plan": {"items": [], "minutes": 0, "message": "",
                           "deep": {"tasks": [], "extra_minutes": 0, "minutes": 0, "note": ""}},
            "daily_progress": {"total": 0, "done": 0, "pending": 0, "minutes": 0,
                               "completion_rate": 0.0, "percent": 0, "finished": False,
                               "tasks": []},
            "review_due_count": 0, "recovery_count": 0,
            "review": {"due_count": 0, "text": kid_status.no_review_text()},
            "recovery": {"total": 0, "mastered": 0, "todo": 0, "red": 0, "yellow": 0, "green": 0},
            "growth_highlight": {"kind": "none", "icon": "🌱", "text": EMPTY_HIGHLIGHT},
            "phoebe_message": {"text": "先选一个小朋友吧～", "state": "normal"},
            "phoebe_state": "normal",
            "child_status": dict(kid_status.UNKNOWN),
            "start": {"label": START_LABEL, "minutes": 0, "task_count": 0},
            "deep_growth": DEEP_EMPTY_GROWTH,
            "finished": False, "debug": {}}


@router.get("/home/{student_id}")
def home(student_id: int, date: str = "", db: Session = Depends(get_db)):
    """孩子打开软件看到的第一屏：我今天要做什么。"""
    day = _day_or_400(date)
    student = _student_of(db, student_id) if student_id >= 1 else None
    if student is None:
        return _empty_home(student_id, day)
    progress = _progress_of(db, student_id, day)
    plan = _plan_of(db, student_id, day, student, progress)
    review = _review_due(db, student_id)
    recovery = _recovery_of(db, student_id)
    highlight = growth_highlight(db, student_id)
    message = phoebe_message(plan, progress, review, recovery)

    return {
        "student_id": student_id,
        "date": progress.get("date") or day or _today_text(),
        "student": student,
        "daily_plan": plan,
        "daily_progress": progress,
        "review_due_count": int(review.get("due_count") or 0),
        "recovery_count": int(recovery.get("todo") or 0),
        "review": review,
        "recovery": recovery,
        "growth_highlight": highlight,
        "deep_growth": _safe(db, lambda: DEEP_ENGINE.growth(db, student_id, DEEP_GROWTH_DAYS),
                             DEEP_EMPTY_GROWTH) or DEEP_EMPTY_GROWTH,
        "phoebe_message": message,
        "phoebe_state": message.get("state") or "normal",
        "child_status": dict(kid_status.UNKNOWN),
        "start": {"label": START_LABEL, "minutes": int(plan.get("minutes") or 0),
                  "task_count": len(plan.get("items") or [])},
        "finished": bool(progress.get("finished")),
        "debug": {"task_summary": {key: value for key, value in progress.items()
                                   if key not in ("tasks",)},
                  "plan_minutes": int(plan.get("minutes") or 0),
                  "adjust": plan.get("adjust") or [],
                  "deep": plan.get("deep") or {}},
    }
