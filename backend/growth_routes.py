# ==============================================================
# 能力契约｜/api/growth/{student_id} 成长中心（本周学会什么 / 记住什么 / 攻克什么 + 成长时间线）
# 入口：router / growth / _period / timeline
# 依赖：models（StudentKnowledgeMastery/DailyLearningTask/WrongQuestionRecovery/
#       KnowledgeMemoryState/ActiveRecallRecord/AnswerRecord）、stages（阶段口径）、
#       knowledge_tree（知识点 → 阶段）、habit（习惯画像唯一来源）、database.get_db
# 不负责：掌握度计算 → mastery.py；记忆成熟度 → review/memory.py；错题康复 → recovery/；
#         习惯连续天数 → habit.py；前端渲染 → frontend/growth.js
# 验证：python backend/verify_v26.py（含成长中心用例）
# 被调用：main.py（注册 router）、frontend/growth.js
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================
"""V2.6 成长中心 API（需求 §26-§28）。

回答孩子一个问题：**"我最近真的变强了吗？"**
所以这里优先统计"学会什么 / 记住什么 / 攻克什么"，而不是做题总量与在线时长。

    GET /api/growth/{student_id}?days=7&date=YYYY-MM-DD

口径说明（写进 ARCHITECTURE 的已知问题）：
- "本周新掌握" = 最近一次练习落在统计窗口内、当前掌握度 ≥ 75 的知识点。
  数据库没有"跨过 🌳 那一刻"的历史记录，因此这是**近似口径**，不做假数据。
- "记得更牢" = 记忆状态在本窗口被更新、且成熟度到达 STABLE / LONG_TERM 的知识点。
- 所有数字都来自真实表，学生不存在返回 200 空结构，``date`` 非法返回 400，绝不 500。
"""

from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import knowledge_tree
import stages
from database import get_db
from models import (ActiveRecallRecord, AnswerRecord, DailyLearningTask,
                    KnowledgeMemoryState, StudentKnowledgeMastery,
                    WrongQuestionRecovery)
from models import Student

router = APIRouter(prefix="/api", tags=["成长中心 V2.6"])

MASTERED_LINE = 75              # 与 kid_status 🌳 的档位保持一致
LONG_TERM_KEYS = ("STABLE", "LONG_TERM")
PERIOD_DEFAULT = 7
PERIOD_MAX = 30
TIMELINE_LIMIT = 12
WEEKDAY_TEXT = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _safe(db, call, fallback):
    """接口层兜底：任何异常都回退到 fallback，绝不 500。"""
    try:
        return call()
    except HTTPException:
        raise
    except Exception:                          # noqa: BLE001
        try:
            db.rollback()
        except Exception:                      # noqa: BLE001
            pass
        return fallback


def _day_or_400(value):
    """date 参数必须是 YYYY-MM-DD，否则 400（与其它接口语义一致）。"""
    if not value:
        return date_cls.today()
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="date 必须是 YYYY-MM-DD")


def _period(day, days):
    """统计窗口：含今天的 N 天（[since 00:00, 明天 00:00)）。"""
    span = max(1, min(PERIOD_MAX, int(days or PERIOD_DEFAULT)))
    since = datetime.combine(day - timedelta(days=span - 1), datetime.min.time())
    until = datetime.combine(day + timedelta(days=1), datetime.min.time())
    return span, since, until


def _student_exists(db, student_id):
    return (db.query(Student.id).filter(Student.id == student_id).first() is not None)


def _aware(value):
    """SQLite 存的是 naive datetime，统一成 naive 便于比较。"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return None


def _in_window(value, since, until):
    stamp = _aware(value)
    return stamp is not None and since <= stamp < until


def _day_text(day, today):
    """今天 / 昨天 / 周一 / 5月8日——儿童能读懂的日期说法。"""
    if day == today:
        return "今天"
    if day == today - timedelta(days=1):
        return "昨天"
    if today - day < timedelta(days=7):
        return WEEKDAY_TEXT[day.weekday()]
    return "{0}月{1}日".format(day.month, day.day)


def _stamp_day(value):
    stamp = _aware(value)
    return stamp.date() if stamp else None


# ---------------------------------------------------------------- 周数据
def _study_days(db, student_id, day, since, until):
    """窗口内有真实学习的日期集合（做题或产生时长才算）。"""
    rows = _safe(db, lambda: (db.query(DailyLearningTask.date, DailyLearningTask.status,
                                       DailyLearningTask.complete_count,
                                       DailyLearningTask.duration_minutes)
                              .filter(DailyLearningTask.student_id == student_id).all()), [])
    days = set()
    for item in rows or []:
        text = item[0] or ""
        if not text:
            continue
        try:
            current = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (since.date() <= current < until.date()):
            continue
        if (item[2] or 0) > 0 or (item[3] or 0) > 0 or (item[1] == "done"):
            days.add(current)
    return days


def _minutes_of(db, student_id, since, until):
    rows = _safe(db, lambda: (db.query(DailyLearningTask.date,
                                       DailyLearningTask.duration_minutes)
                              .filter(DailyLearningTask.student_id == student_id).all()), [])
    total = 0
    for text, minutes in rows or []:
        try:
            current = datetime.strptime(text or "", "%Y-%m-%d").date()
        except ValueError:
            continue
        if since.date() <= current < until.date():
            total += int(minutes or 0)
    return total


def _mastered_rows(db, student_id, since, until):
    """窗口内达到 🌳 的知识点（近似口径，见模块 docstring）。"""
    rows = _safe(db, lambda: (db.query(StudentKnowledgeMastery)
                              .filter(StudentKnowledgeMastery.student_id == student_id,
                                      StudentKnowledgeMastery.mastery_score >= MASTERED_LINE)
                              .all()), [])
    return [row for row in rows or [] if _in_window(row.last_practice_time, since, until)]


def _memory_rows(db, student_id, since, until):
    """窗口内进入长期牢记的知识点（成熟度 STABLE / LONG_TERM）。"""
    rows = _safe(db, lambda: (db.query(KnowledgeMemoryState)
                              .filter(KnowledgeMemoryState.student_id == student_id,
                                      KnowledgeMemoryState.maturity_level.in_(LONG_TERM_KEYS))
                              .all()), [])
    return [row for row in rows or [] if _in_window(row.updated_at, since, until)]


def _recovery_rows(db, student_id, since, until):
    rows = _safe(db, lambda: (db.query(WrongQuestionRecovery)
                              .filter(WrongQuestionRecovery.student_id == student_id,
                                      WrongQuestionRecovery.state == "MASTERED")
                              .all()), [])
    return [row for row in rows or [] if _in_window(row.mastered_time, since, until)]


def _review_success(db, student_id, since, until):
    from models import ReviewRecord
    rows = _safe(db, lambda: (db.query(ReviewRecord)
                              .filter(ReviewRecord.student_id == student_id,
                                      ReviewRecord.correct.is_(True)).all()), [])
    return len([row for row in rows or [] if _in_window(row.reviewed_at, since, until)])


def _recall_rows(db, student_id, since, until):
    rows = _safe(db, lambda: (db.query(ActiveRecallRecord)
                              .filter(ActiveRecallRecord.student_id == student_id,
                                      ActiveRecallRecord.result == "correct").all()), [])
    return [row for row in rows or [] if _in_window(row.created_at, since, until)]


def _month_days(db, student_id, today):
    """本月学习天数（不清零历史：休息一天也保留）。"""
    rows = _safe(db, lambda: (db.query(DailyLearningTask.date,
                                       DailyLearningTask.complete_count,
                                       DailyLearningTask.duration_minutes)
                              .filter(DailyLearningTask.student_id == student_id).all()), [])
    days = set()
    for text, count, minutes in rows or []:
        try:
            current = datetime.strptime(text or "", "%Y-%m-%d").date()
        except ValueError:
            continue
        if current.year == today.year and current.month == today.month:
            if (count or 0) > 0 or (minutes or 0) > 0:
                days.add(current)
    return len(days)


# ---------------------------------------------------------------- 能力阶段
def _stage_pair(db, student_id, subject, since, until):
    """本窗口的能力阶段：第一次练的知识点 → 最近练的知识点（阶段取 knowledge_tree）。"""
    rows = _safe(db, lambda: (db.query(AnswerRecord.knowledge, AnswerRecord.created_at)
                              .filter(AnswerRecord.student_id == student_id,
                                      AnswerRecord.subject == subject)
                              .order_by(AnswerRecord.created_at.asc()).all()), [])
    keys = []
    for knowledge, stamp in rows or []:
        if not _in_window(stamp, since, until):
            continue
        key = _key_for(subject, knowledge)
        if key:
            keys.append(key)
    if not keys:
        return None, None
    return keys[0], keys[-1]


def _key_for(subject, knowledge):
    """知识点 → 能力阶段 key（knowledge_tree 是知识点的唯一真相源）。"""
    if not knowledge:
        return None
    key = None
    for probe in (lambda: knowledge_tree.stage_of(subject, knowledge),
                  lambda: knowledge_tree.stage_of_any(subject, knowledge)):
        try:
            key = probe()
        except Exception:                      # noqa: BLE001
            key = None
        if key:
            break
    if not key:
        return None
    try:
        return stages.normalize_key(key)
    except Exception:                          # noqa: BLE001
        return None


def ability_of(db, student_id, since, until):
    """三科能力阶段：{subject: {...}}——数值口径沿用 stages（单一真相源）。"""
    result = {}
    for subject in stages.SUBJECTS:
        try:
            from_key, to_key = _stage_pair(db, student_id, subject, since, until)
        except Exception:                      # noqa: BLE001
            from_key, to_key = None, None
        if not to_key and not from_key:
            result[subject] = {"subject": subject, "from_key": "", "from_label": "",
                               "to_key": "", "to_label": "", "changed": False,
                               "text": "{0}还没有开始练习。".format(subject)}
            continue
        to_key = to_key or from_key
        from_key = from_key or to_key
        changed = stages.index_of(to_key) > stages.index_of(from_key)
        if changed:
            text = "{0}能力：{1} → {2}".format(subject, from_key, to_key)
        elif not from_key:
            text = "{0}能力：{1}".format(subject, to_key)
        else:
            text = "{0}能力：保持在 {1}".format(subject, to_key)
        result[subject] = {
            "subject": subject,
            "from_key": from_key, "from_label": stages.label(from_key),
            "to_key": to_key, "to_label": stages.label(to_key),
            "changed": bool(changed), "text": text,
        }
    return result


# ---------------------------------------------------------------- 时间线
def timeline(db, student_id, since, until, today):
    """成长时间线：只记录真实成长事件（不做社交 Feed）。"""
    events = []
    for row in _mastered_rows(db, student_id, since, until):
        events.append({"at": row.last_practice_time, "icon": "🌳",
                       "text": "掌握「{0}」".format(row.knowledge_id or ""),
                       "type": "mastered", "subject": row.subject or ""})
    for row in _recovery_rows(db, student_id, since, until):
        events.append({"at": row.mastered_time, "icon": "⚔️",
                       "text": "攻克「{0}」的一道挑战".format(row.knowledge_id or "错题"),
                       "type": "recovery", "subject": row.subject or ""})
    for row in _memory_rows(db, student_id, since, until):
        events.append({"at": row.updated_at, "icon": "⭐",
                       "text": "「{0}」进入长期掌握".format(row.knowledge_id or ""),
                       "type": "long_term", "subject": row.subject or ""})
    for row in _recall_rows(db, student_id, since, until):
        events.append({"at": row.created_at, "icon": "🧠",
                       "text": "主动回忆成功「{0}」".format(row.knowledge or ""),
                       "type": "recall", "subject": row.subject or ""})
    events = [item for item in events if _aware(item["at"]) is not None]
    events.sort(key=lambda item: _aware(item["at"]), reverse=True)
    result = []
    for item in events[:TIMELINE_LIMIT]:
        day = _stamp_day(item["at"])
        item = dict(item)
        item["day"] = day.strftime("%Y-%m-%d") if day else ""
        item["day_text"] = _day_text(day, today) if day else ""
        item["at"] = _aware(item["at"]).strftime("%Y-%m-%d %H:%M")
        item["line"] = "{0} {1}".format(item["icon"], item["text"])
        result.append(item)
    return result


# ---------------------------------------------------------------- 汇总
def _empty_growth(student_id, day, span):
    return {"student_id": student_id, "date": day.strftime("%Y-%m-%d"), "period_days": span,
            "week": {"study_days": 0, "new_mastered": 0, "long_term": 0, "challenges": 0,
                     "review_success": 0, "recall_success": 0, "minutes": 0},
            "highlights": [], "ability": {}, "timeline": [],
            "streak": {"current": 0, "longest": 0, "month_days": 0, "rest_left": 0,
                       "text": "还没有开始记录哦。"},
            "message": "完成第一个小任务，成长就会从这里长出来。"}


def growth(db, student_id, day, days):
    """成长中心汇总：本周成果 + 能力阶段 + 时间线 + 连续学习（真实数据）。"""
    import habit

    span, since, until = _period(day, days)
    mastered = _mastered_rows(db, student_id, since, until)
    memories = _memory_rows(db, student_id, since, until)
    recoveries = _recovery_rows(db, student_id, since, until)
    recalls = _recall_rows(db, student_id, since, until)
    study_days = _study_days(db, student_id, day, since, until)
    review_success = _review_success(db, student_id, since, until)
    minutes = _minutes_of(db, student_id, since, until)
    profile = _safe(db, lambda: habit.HabitEngine().profile(db, student_id, date=day), {}) or {}
    rest_left = _safe(db, lambda: (habit.HabitEngine().rest_status(db, student_id, date=day) or {}).get("rest_protection_left", 0), 0)
    week = {
        "study_days": len(study_days),
        "new_mastered": len(mastered),
        "long_term": len(memories),
        "challenges": len(recoveries),
        "review_success": int(review_success or 0),
        "recall_success": len(recalls),
        "minutes": int(minutes or 0),
    }
    highlights = _highlights(week)
    streak = {
        "current": int(profile.get("current_streak") or 0),
        "longest": int(profile.get("longest_streak") or 0),
        "month_days": _month_days(db, student_id, day),
        "rest_left": int(rest_left or 0),
        "text": _streak_text(profile, day),
    }
    ability = _safe(db, lambda: ability_of(db, student_id, since, until), {})
    events = _safe(db, lambda: timeline(db, student_id, since, until, day), [])

    return {
        "student_id": student_id,
        "date": day.strftime("%Y-%m-%d"),
        "period_days": span,
        "since": since.strftime("%Y-%m-%d"),
        "until": until.strftime("%Y-%m-%d"),
        "week": week,
        "highlights": highlights,
        "ability": ability,
        "timeline": events,
        "streak": streak,
        "message": _message(week),
    }


def _highlights(week):
    """"这周你："——学会什么 / 记住什么 / 攻克什么，优先于使用量。"""
    lines = []
    if week["study_days"]:
        lines.append({"icon": "📅", "text": "学习 {0} 天".format(week["study_days"])})
    if week["new_mastered"]:
        lines.append({"icon": "🌳", "text": "新掌握 {0} 个知识".format(week["new_mastered"])})
    if week["long_term"]:
        lines.append({"icon": "⭐", "text": "{0} 个知识记得更牢".format(week["long_term"])})
    if week["challenges"]:
        lines.append({"icon": "⚔️", "text": "攻克 {0} 个挑战".format(week["challenges"])})
    if week["review_success"]:
        lines.append({"icon": "🧠", "text": "复习成功 {0} 次".format(week["review_success"])})
    if week["recall_success"]:
        lines.append({"icon": "✨", "text": "主动回忆成功 {0} 次".format(week["recall_success"])})
    return lines


def _streak_text(profile, day):
    current = int(profile.get("current_streak") or 0)
    longest = int(profile.get("longest_streak") or 0)
    if not current and not longest:
        return "休息一天不会清空历史成长，随时可以回来～"
    return "当前连续 {0} 天，最长连续 {1} 天。休息一天也不会清空成长。".format(current, longest)


def _message(week):
    if not week["study_days"]:
        return "这周还没开始，学一个小任务就能看到成长啦。"
    if week["new_mastered"] or week["long_term"]:
        return "这段时间你真的变强了，学会的和记住的都算数。"
    if week["challenges"] or week["review_success"]:
        return "你把以前不会的补上来了，继续这样就好。"
    return "你坚持来了 {0} 天，复习和练习都在积累。".format(week["study_days"])


@router.get("/growth/{student_id}")
def growth_api(student_id: int, days: int = PERIOD_DEFAULT, date: str = "",
               db: Session = Depends(get_db)):
    """成长中心：本周学会什么、记住什么、攻克什么，以及成长时间线。"""
    day = _day_or_400(date)
    span = max(1, min(PERIOD_MAX, int(days or PERIOD_DEFAULT)))
    if student_id < 1 or not _safe(db, lambda: _student_exists(db, student_id), False):
        return _empty_growth(student_id, day, span)
    return _safe(db, lambda: growth(db, student_id, day, span), _empty_growth(student_id, day, span))
