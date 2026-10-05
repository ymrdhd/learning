# ==============================================================
# 能力契约｜/api/challenge/{student_id} 挑战中心（把 V2.5 错题康复儿童化：🔴🟡🟢 三色看板）
# 入口：router / challenge / _tone_node / EMPTY_TEXT
# 依赖：recovery.engine（DEFAULT_ENGINE.list_items/stats，唯一康复算法来源）、recovery.state、
#       kid_status（challenge_status 三色映射）、stages、database.get_db
# 不负责：康复状态机 / 提示层级 / 变式题 → recovery/ 与 ai_recovery.py（本模块只读列表与分组）；
#         康复操作接口 → recovery_routes.py（挑战中心前端直接复用，不新开一套）
# 验证：python backend/verify_v26.py（含挑战中心与 recovery 一致性用例）
# 被调用：main.py（注册 router）、frontend/challenge.js
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================
"""V2.6 挑战中心 API（需求 §29）。

同一批错题，换一种孩子看得懂的说法：**🔴 等我攻克 / 🟡 正在训练 / 🟢 已经攻克**。

    GET /api/challenge/{student_id}?subject=&limit=50

纪律：
1. 只用 V2.5 ``WrongQuestionRecoveryEngine.list_items`` 的**真实状态**，绝不重算、
   绝不新开第二套康复算法；康复操作（开始教学 / 提示 / 判分 / 验证）仍走 ``/api/recovery/*``。
2. 列表不下发 ``correct_answer`` / ``analysis``（出题与列表接口不得泄露答案，AI_RULES §13.3）。
3. 学生不存在返回 200 空结构；``subject`` 非法 400；任何内部异常兜住 → 绝不 500。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import kid_status
import stages
from database import get_db
from recovery import engine as recovery_engine

router = APIRouter(prefix="/api", tags=["挑战中心 V2.6"])

ENGINE = recovery_engine.DEFAULT_ENGINE

EMPTY_TEXT = "🎉 暂时没有需要攻克的挑战！"
DONE_TEXT = "🟢 这些挑战你都攻克啦，真棒！"
TONE_TITLE = {"red": "🔴 等我攻克", "yellow": "🟡 正在训练", "green": "🟢 已经攻克"}
LIMIT_DEFAULT = 60
LIMIT_MAX = 200


def _safe(db, call, fallback):
    """接口层兜底：任何异常都回退 fallback，绝不 500。"""
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


def _subject_or_400(value):
    text = str(value or "").strip()
    if text and text not in stages.SUBJECTS:
        raise HTTPException(status_code=400,
                            detail="科目必须是：" + "、".join(stages.SUBJECTS))
    return text


def _tone_node(item):
    """一条挑战的三色视图（不含答案与解析）。"""
    status = kid_status.challenge_status(item.get("state"))
    knowledge = item.get("knowledge") or ""
    return {
        "recovery_id": int(item.get("recovery_id") or 0),
        "question_id": int(item.get("question_id") or 0),
        "subject": item.get("subject") or "",
        "knowledge": knowledge,
        "state": item.get("state") or "",
        "state_text": item.get("state_text") or "",
        "tone": status["key"],
        "icon": status["icon"],
        "tone_text": status["label"],
        "attempts": int(item.get("attempts") or 0),
        "consecutive_correct": int(item.get("consecutive_correct") or 0),
        "fail_count": int(item.get("fail_count") or 0),
        "max_level_used": int(item.get("max_level_used") or 0),
        "next_verify_time": item.get("next_verify_time") or "",
        "question": item.get("question") or "",
        "line": "{0} 「{1}」".format(stages.SUBJECTS and (item.get("subject") or ""), knowledge),
    }


def _empty_challenge(student_id):
    return {"student_id": student_id, "total": 0,
            "counts": {"red": 0, "yellow": 0, "green": 0, "active": 0, "mastered_rate": 0.0},
            "groups": {"red": [], "yellow": [], "green": []},
            "items": [], "tones": dict(TONE_TITLE),
            "next": None, "message": EMPTY_TEXT, "empty_text": EMPTY_TEXT}


def challenge(db, student_id, subject="", limit=LIMIT_DEFAULT):
    """挑战看板：真实康复状态 → 三色分组 + 建议先攻克哪个。"""
    data = _safe(db, lambda: ENGINE.list_items(db, student_id,
                                               subject=subject or None,
                                               limit=limit), None)
    if not data:
        return _empty_challenge(student_id)
    nodes = [_tone_node(item) for item in (data.get("items") or [])]
    groups = {"red": [], "yellow": [], "green": []}
    for node in nodes:
        groups[node["tone"]].append(node)
    stats = data.get("stats") or {}
    counts = {
        "red": len(groups["red"]),
        "yellow": len(groups["yellow"]),
        "green": len(groups["green"]),
        "active": len(groups["red"]) + len(groups["yellow"]),
        "mastered_rate": float(stats.get("mastered_rate") or 0.0),
    }
    total = int(data.get("total") or len(nodes))
    next_node = (groups["red"] or groups["yellow"] or [None])[0]
    if not total:
        message = EMPTY_TEXT
    elif counts["active"]:
        message = "先看看「{0}」这道挑战吧。".format(next_node["knowledge"] or "错题")
    else:
        message = DONE_TEXT
    return {
        "student_id": student_id,
        "total": total,
        "counts": counts,
        "groups": groups,
        "items": nodes,
        "tones": dict(TONE_TITLE),
        "next": next_node,
        "message": message,
        "empty_text": EMPTY_TEXT,
    }


@router.get("/challenge/{student_id}")
def challenge_api(student_id: int, subject: str = "", limit: int = LIMIT_DEFAULT,
                  db: Session = Depends(get_db)):
    """挑战中心：🔴 等我攻克 / 🟡 正在训练 / 🟢 已经攻克（数据来自 V2.5 错题康复）。"""
    name = _subject_or_400(subject)
    size = max(1, min(LIMIT_MAX, int(limit or LIMIT_DEFAULT)))
    if student_id < 1:
        return _empty_challenge(student_id)
    return _safe(db, lambda: challenge(db, student_id, name, size),
                 _empty_challenge(student_id))
