# ==============================================================
# 能力契约｜/api/points/* 积分与商城接口（余额 / 今日获得 / 打卡 / 占位兑换项）
# 入口：router / points_summary / points_shop / points_login / points_checkin
# 依赖：points（summary / checkin / RULES / SHOP_ITEMS）、points_rewards（积分明细）、models（学生校验）、database.get_db
# 不负责：加分时机与账本 → points.py（main.py 的 /submit、task_routes.py 的任务收工调用它）；
#         真实兑换与发放（比例先占位、不实装）→ 本层只读账 + 打卡
# 验证：python backend/verify_points.py
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.8 积分 API。

    GET  /api/points/{student_id}          积分总览（余额 / 今日获得 / 打卡与连续天数 / 规则 / 商城占位道具 / 最近流水）
    GET  /api/points/{student_id}/shop     商城道具（比例先占位，兑换不实装）
    POST /api/points/{student_id}/login     每日首次登录奖励（幂等，一天一次 +10）
    POST /api/points/{student_id}/checkin  每日打卡（幂等；今天的小任务全部收工后自动记一次）

纪律：按 ``student_id`` 过滤（A=1 / B=2 隔离）；学生不存在返回 404；内部异常一律兜住 → 绝不 500。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import points
import points_rewards
from database import get_db

router = APIRouter(prefix="/api/points", tags=["积分 V2.8"])


def _student_or_404(db, student_id):
    """只允许查存在的学习者，避免给不存在的人凭空建账户。"""
    row = db.query(models.Student).filter(models.Student.id == student_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="学习者不存在")
    return row


def _empty_shop():
    return {"enabled": False, "note": points.SHOP_NOTE,
            "items": [dict(item) for item in points.SHOP_ITEMS]}


@router.get("/{student_id}")
def points_summary(student_id: int, db: Session = Depends(get_db)):
    """积分总览：余额 / 今日获得 / 打卡状态与连续天数 / 加分规则 / 商城占位道具 / 最近流水。"""
    _student_or_404(db, student_id)
    try:
        return points.summary(db, student_id)
    except Exception:                              # noqa: BLE001 - 兜底，不暴露内部细节
        db.rollback()
        return {"student_id": student_id, "balance": 0, "total_earned": 0, "today_points": 0,
                "today_count": 0, "checked_in": False, "streak": 0,
                "rules": [dict(item) for item in points.RULES],
                "rewards": points_rewards.reward_table(),
                "reward_version": points_rewards.REWARD_VERSION,
                "reward_states": dict(points_rewards.REWARD_STATES),
                "shop": _empty_shop(),
                "records": [], "error": "积分暂时读不出来，过一会儿再试"}


@router.get("/{student_id}/shop")
def points_shop(student_id: int, db: Session = Depends(get_db)):
    """商城道具：兑换比例先占位，兑换功能还没实装（只展示）。"""
    _student_or_404(db, student_id)
    balance = 0
    try:
        balance = points.balance_of(db, student_id)
    except Exception:                              # noqa: BLE001
        db.rollback()
    data = _empty_shop()
    data["student_id"] = student_id
    data["balance"] = balance
    return data


@router.post("/{student_id}/login")
def points_login(student_id: int, db: Session = Depends(get_db)):
    """每日首次登录奖励：一天只记一次（幂等，第二次返回「今天已经领过啦」）。"""
    _student_or_404(db, student_id)
    try:
        return points.login(db, student_id)
    except Exception:                              # noqa: BLE001
        db.rollback()
        return {"awarded": False, "reason": "error", "date": points.today_text(),
                "message": "登录奖励没记上，过一会儿再试", "balance": 0}


@router.post("/{student_id}/checkin")
def points_checkin(student_id: int, db: Session = Depends(get_db)):
    """每日打卡：今天的小任务全部收工后自动记一次（幂等）；还没做完只提示，不给分。"""
    _student_or_404(db, student_id)
    try:
        return points.checkin(db, student_id)
    except Exception:                              # noqa: BLE001
        db.rollback()
        return {"awarded": False, "reason": "error", "date": points.today_text(),
                "message": "打卡没成功，过一会儿再试", "balance": 0}
