# 能力契约｜积分账本（加分规则 / 打卡幂等 / 余额与流水 / 商城占位道具）
# 职责：积分账本 —— 加分规则（每日首次登录 / 每日打卡 / 每答对一题 / 计划做完后继续练 / 任务收工）、
#       每日打卡幂等、连续打卡天数、余额与流水查询、商城里「先占位」的兑换道具
# 入口：award / award_after_answer / award_task_done / login / checkin / summary / balance_of / streak_days / RULES / SHOP_ITEMS
# 依赖：models（StudentPoint / PointRecord / DailyLearningTask）、datetime、points_rewards（积分明细分值口径）
# 不负责：真实兑换与发放（比例先占位、不实装）——只加账不扣账；HTTP 接口 → points_routes.py
# 验证：python backend/verify_points.py
# 被调用：main.py（/submit 答对后加分）、task_routes.py（任务收工加分）、points_routes.py
# 索引：docs/MODULE_MAP.md

"""V2.8 积分系统：孩子靠学习挣积分，首页商城按占位比例展示可兑换道具（暂不实装兑换）。"""

from datetime import datetime, timedelta

import models
import points_rewards

# ---------- 加分规则（比例先占位，以后调数值只改这里） ----------
RULES = (
    {"event": "answer_correct", "label": "答对一题", "points": 2},
    {"event": "daily_checkin", "label": "每日打卡", "points": 10},
    {"event": "daily_login", "label": "每日首次登录", "points": 10},
    {"event": "free_practice", "label": "计划做完后继续练", "points": 3},
    {"event": "task_done", "label": "一项任务收工", "points": 5},
)
RULE_POINTS = {item["event"]: int(item["points"]) for item in RULES}
RULE_LABEL = {item["event"]: item["label"] for item in RULES}

# ---------- 商城道具（兑换比例先占位：只展示，不实装兑换） ----------
SHOP_ENABLED = False
SHOP_NOTE = "兑换比例先占位，兑换功能还没实装"
SHOP_ITEMS = (
    {"key": "ipad_time", "emoji": "📱", "label": "iPad 使用时间 10 分钟", "cost": 200, "note": "和家长约定好时间"},
    {"key": "toy_20", "emoji": "🧸", "label": "20 元以下小玩具", "cost": 400, "note": "占位价"},
    {"key": "toy_50", "emoji": "🎁", "label": "50 元以下玩具", "cost": 900, "note": "占位价"},
    {"key": "toy_100", "emoji": "🎀", "label": "100 元以下玩具", "cost": 1600, "note": "占位价"},
    {"key": "eggy_recharge", "emoji": "🥚", "label": "蛋仔派对充值 5 元", "cost": 300, "note": "占位价"},
)

RECORD_LIMIT = 10


def today_text(date=None):
    """当天日期文本（YYYY-MM-DD）；``date`` 可传 datetime。"""
    return (date or datetime.now()).strftime("%Y-%m-%d")


def _account(db, student_id, create=True):
    """取这个孩子的积分账户；``create=True`` 时没有就建一个（余额 0）。"""
    row = db.query(models.StudentPoint).filter(
        models.StudentPoint.student_id == student_id).first()
    if row is None and create:
        row = models.StudentPoint(student_id=student_id, balance=0, total_earned=0)
        db.add(row)
        db.flush()
    return row


def balance_of(db, student_id):
    """当前可用积分（没有账户就是 0）。"""
    account = _account(db, student_id, create=False)
    return int(account.balance or 0) if account else 0


def award(db, student_id, event, *, points=None, note="", once_key=None, date=None, commit=True):
    """给一个孩子加一次分。

    ``once_key`` 非空时同一个人只能记一次（每日打卡 / 任务收工用它），重复调用返回
    ``{"awarded": False, "reason": "already"}``；``points=None`` 时按 ``RULES`` 的占位分值算。
    """
    day = today_text(date)
    if once_key:
        exists = db.query(models.PointRecord).filter(
            models.PointRecord.student_id == student_id,
            models.PointRecord.once_key == once_key).first()
        if exists is not None:
            return {"awarded": False, "event": event, "points": 0, "reason": "already",
                    "date": day, "balance": balance_of(db, student_id)}
    value = int(RULE_POINTS.get(event, 0) if points is None else points)
    if value <= 0:
        return {"awarded": False, "event": event, "points": 0, "reason": "no_rule",
                "date": day, "balance": balance_of(db, student_id)}
    account = _account(db, student_id)
    record = models.PointRecord(
        student_id=student_id, date=day, event=event, label=RULE_LABEL.get(event, event),
        points=value, note=note, once_key=once_key or None, created_at=datetime.now())
    db.add(record)
    account.balance = int(account.balance or 0) + value
    account.total_earned = int(account.total_earned or 0) + value
    account.updated_at = datetime.now()
    if commit:
        db.commit()
    else:
        db.flush()
    return {"awarded": True, "event": event, "points": value, "reason": "",
            "balance": int(account.balance or 0), "date": day,
            "label": record.label, "note": note}


def plan_finished(db, student_id, day):
    """当天的每日任务是不是全部收工（没有任务时算「没收工」）。"""
    rows = db.query(models.DailyLearningTask).filter(
        models.DailyLearningTask.student_id == student_id,
        models.DailyLearningTask.date == day).all()
    return bool(rows) and all((row.status or "") == "done" for row in rows)


def award_after_answer(db, student_id, *, correct, subject="", knowledge="", date=None):
    """答完一题后结算：答对得分；当天小任务全部收工那一刻顺手记「每日打卡」；再做还有「继续练」。"""
    day = today_text(date)
    if not correct:
        return {"awarded": False, "gained": 0, "events": [], "date": day,
                "balance": balance_of(db, student_id)}
    gained = 0
    events = []

    def take(event, note="", once_key=None):
        nonlocal gained
        result = award(db, student_id, event, note=note, once_key=once_key,
                       date=date, commit=False)
        if result.get("awarded"):
            gained += int(result.get("points") or 0)
            events.append({"event": result["event"], "points": result["points"],
                           "label": result.get("label", "")})
        return result

    take("answer_correct", note=("%s %s" % (subject, knowledge)).strip())
    if plan_finished(db, student_id, day):
        take("daily_checkin", once_key="checkin:%s" % day, note="今天的小任务都做完了")
        take("free_practice", note="今天的小任务都做完了，还继续练")
    db.commit()
    return {"awarded": bool(events), "gained": gained, "events": events, "date": day,
            "balance": balance_of(db, student_id)}


def award_task_done(db, student_id, task_id, status="", date=None):
    """一项每日任务收工（``status == "done"``）时记一次分；同一项只记一次。

    收工后若当天小任务全做完，顺手记「每日打卡」（``checkin`` 字段带回结果，幂等）。
    """
    if (status or "") != "done" or not task_id:
        return {"awarded": False, "points": 0, "reason": "not_done"}
    result = award(db, student_id, "task_done", once_key="task:%d" % int(task_id),
                   note="任务 #%d 收工" % int(task_id), date=date)
    day = today_text(date)
    if plan_finished(db, student_id, day):
        result["checkin"] = award(db, student_id, "daily_checkin",
                                  once_key="checkin:%s" % day,
                                  note="今天的小任务都做完了", date=date)
    return result


def login(db, student_id, date=None):
    """每日首次登录：一天只记一次（幂等，第二次返回「今天已经领过啦」）。"""
    day = today_text(date)
    result = award(db, student_id, "daily_login", once_key="login:%s" % day,
                   note="今天第一次打开学习页", date=date)
    if result.get("awarded"):
        result["message"] = "登录奖励 +%d 分" % int(result.get("points") or 0)
    else:
        result["message"] = "今天已经领过登录奖励啦"
    return result


def checkin(db, student_id, date=None):
    """每日打卡：今天的小任务全部收工后自动记一次；手动入口只做同一件事（幂等）。"""
    day = today_text(date)
    if not plan_finished(db, student_id, day):
        return {"awarded": False, "reason": "need_finish", "date": day,
                "message": "先把今天的小任务做完，打卡会自己来哦",
                "balance": balance_of(db, student_id)}
    result = award(db, student_id, "daily_checkin", once_key="checkin:%s" % day,
                   note="今天的小任务都做完了", date=date)
    result["message"] = "打卡成功！" if result.get("awarded") else "今天已经打过卡啦"
    return result


def streak_days(db, student_id, date=None):
    """连续打卡天数（从今天往回数；今天还没打卡就从昨天开始数）。"""
    cursor = (date or datetime.now()).date()
    rows = db.query(models.PointRecord.date).filter(
        models.PointRecord.student_id == student_id,
        models.PointRecord.event == "daily_checkin").all()
    days = {str(item[0] or "") for item in rows}
    if cursor.strftime("%Y-%m-%d") not in days:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor.strftime("%Y-%m-%d") in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def summary(db, student_id, date=None):
    """积分总览：余额 / 今日获得 / 打卡与连续天数 / 规则 / 商城占位道具 / 最近流水。"""
    day = today_text(date)
    account = _account(db, student_id)
    db.commit()
    today_rows = db.query(models.PointRecord).filter(
        models.PointRecord.student_id == student_id,
        models.PointRecord.date == day).all()
    records = db.query(models.PointRecord).filter(
        models.PointRecord.student_id == student_id).order_by(
        models.PointRecord.id.desc()).limit(RECORD_LIMIT).all()
    balance = int(account.balance or 0)
    items = []
    for item in SHOP_ITEMS:
        entry = dict(item)
        entry["affordable"] = bool(SHOP_ENABLED) and balance >= int(item["cost"])
        items.append(entry)
    return {
        "student_id": student_id, "date": day, "balance": balance,
        "total_earned": int(account.total_earned or 0),
        "today_points": sum(int(row.points or 0) for row in today_rows),
        "today_count": len(today_rows),
        "checked_in": any((row.event or "") == "daily_checkin" for row in today_rows),
        "streak": streak_days(db, student_id, date=date),
        "rules": [dict(item) for item in RULES],
        "rewards": points_rewards.reward_table(),
        "reward_version": points_rewards.REWARD_VERSION,
        "reward_states": dict(points_rewards.REWARD_STATES),
        "shop": {"enabled": bool(SHOP_ENABLED), "note": SHOP_NOTE, "items": items},
        "records": [{"date": row.date, "event": row.event, "label": row.label,
                     "points": int(row.points or 0), "note": row.note,
                     "time": row.created_at.strftime("%m-%d %H:%M") if row.created_at else ""}
                    for row in records],
    }
