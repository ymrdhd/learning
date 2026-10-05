# ==============================================================
# 能力契约｜/api/learning/* 自适应学习接口
# 入口：router / learning_recommend / learning_plan / learning_start / learning_next_question / learning_feedback / learning_strategy_log
# 依赖：adaptive.engine / adaptive.difficulty / adaptive.planner / stages / database
# 不负责：自适应算法 → adaptive/ 各纯函数模块；出题 → main.question
# 验证：python backend/verify_adaptive.py
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎 API。

    GET  /api/learning/recommend/{student_id}   今日推荐学习内容（含理由）
    POST /api/learning/start                    开始学习任务（锁定知识点与难度）
    GET  /api/learning/next-question            获取下一题（自适应出题）
    POST /api/learning/feedback                 提交学习反馈（对错/难度感受/是否需要帮助）
    GET  /api/learning/plan/{student_id}        查看今日计划
    GET  /api/learning/strategy-log/{student_id} 查看策略日志（为什么这么推荐）
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import stages
import habit
from adaptive import difficulty, engine, planner
from database import get_db

router = APIRouter(prefix="/api", tags=["自适应学习"])

ENGINE = engine.DEFAULT_ENGINE


class StartIn(BaseModel):
    student_id: int = 1
    subject: str = stages.DEFAULT_SUBJECT
    knowledge: str = ""
    plan_id: int = 0


class FeedbackIn(BaseModel):
    student_id: int = 1
    subject: str = ""
    knowledge: str = ""
    question_id: int = 0
    difficulty: int = 0
    correct: Optional[bool] = None
    feel: str = ""
    need_help: bool = False
    note: str = ""


def _subject_or_400(subject):
    text = str(subject or "").strip()
    if text not in stages.SUBJECTS:
        raise HTTPException(status_code=400,
                            detail=f"科目必须是：{'、'.join(stages.SUBJECTS)}")
    return text


@router.get("/learning/recommend/{student_id}")
def learning_recommend(student_id: int, subject: str = "", db: Session = Depends(get_db)):
    """今日推荐学习内容：先学哪一科、哪个知识点、什么难度，以及为什么。"""
    if subject:
        subject = _subject_or_400(subject)

    return ENGINE.recommend(db, student_id, subject=subject or None)


@router.get("/learning/plan/{student_id}")
def learning_plan(student_id: int, date: str = "", refresh: bool = False,
                  db: Session = Depends(get_db)):
    """查看今日计划（没有就按当前画像自动生成，刷新页面不会丢进度）。"""
    # V2.6：计划总时长用「自适应目标时长」（首次 10 分钟起步），与今日任务页口径一致
    minutes = habit.DEFAULT_ENGINE.target_minutes_of(db, student_id, date=date or None)
    if refresh:
        return ENGINE.plan(db, student_id, plan_date=date or None, refresh=True,
                           total_minutes=minutes)

    return ENGINE.plan(db, student_id, plan_date=date or None, total_minutes=minutes)


@router.post("/learning/start")
def learning_start(payload: StartIn, db: Session = Depends(get_db)):
    """开始学习任务：确定今天这一科练哪个知识点、用什么难度。"""
    subject = _subject_or_400(payload.subject)
    knowledge = str(payload.knowledge or "").strip()

    return ENGINE.start(db, payload.student_id, subject, knowledge=knowledge or None,
                        plan_id=payload.plan_id or None)


@router.get("/learning/next-question")
def learning_next_question(student_id: int = 1, subject: str = stages.DEFAULT_SUBJECT,
                           knowledge: str = "", qtype: str = "choice",
                           avoid: str = "",
                           db: Session = Depends(get_db)):
    """获取下一题：知识点与难度都由自适应引擎决定。

    avoid：逗号分隔的"最近刚练过的知识点"。命中的知识点不再锁定，
    交给选择器换一个候选，避免同一种题连着出（不硬禁，过几道还能再练）。
    """
    subject = _subject_or_400(subject)
    knowledge = str(knowledge or "").strip() or None
    avoid_knowledge = tuple(part.strip() for part in str(avoid or "").split(",") if part.strip())

    spec = ENGINE.next_spec(db, student_id, subject, knowledge=knowledge,
                            avoid_knowledge=avoid_knowledge)

    # 出题逻辑复用主流程（/question）：题库、质量审核、兜底题全部一致，
    # 只是难度由自适应引擎指定，不再按固定规则重算。
    import main

    data = main.question(student_id=student_id, subject=subject,
                         knowledge=spec["knowledge"], qtype=qtype,
                         difficulty=spec["difficulty"], db=db)

    ENGINE.log(db, student_id, spec, source="next_question")

    return dict(data, adaptive={
        "action": spec.get("action"),
        "action_text": spec.get("action_text"),
        "mode": spec.get("mode"),
        "knowledge": spec["knowledge"],
        "avoided": bool(spec.get("avoided")),
        "avoided_knowledge": spec.get("avoided_knowledge") or "",
        "difficulty": spec["difficulty"],
        "reason": spec.get("reason"),
        "score": spec.get("score"),
        "breakdown": spec.get("breakdown"),
        "alternatives": spec.get("alternatives"),
        "difficulty_state": spec.get("difficulty_state"),
        "decision": spec.get("decision"),
    })


@router.post("/learning/feedback")
def learning_feedback(payload: FeedbackIn, db: Session = Depends(get_db)):
    """提交学习反馈：这道题对不对、感觉难不难、需不需要帮助。"""
    feel = str(payload.feel or "").strip().lower()
    if feel and feel not in difficulty.FEEL_DELTA:
        raise HTTPException(
            status_code=400,
            detail="难度感受只能是：easy（简单）/ normal（正常）/ hard（有点难）/ lost（不会）")

    if payload.subject:
        _subject_or_400(payload.subject)

    result = ENGINE.feedback(db, payload.student_id, {
        "subject": payload.subject,
        "knowledge": payload.knowledge,
        "question_id": payload.question_id,
        "difficulty": payload.difficulty,
        "correct": payload.correct,
        "feel": feel,
        "need_help": payload.need_help,
        "note": payload.note,
    })
    result["feel_options"] = [
        {"value": "easy", "text": "😊 简单"},
        {"value": "normal", "text": "🙂 正常"},
        {"value": "hard", "text": "🤔 有点难"},
        {"value": "lost", "text": "😵 不会"},
    ]
    return result


@router.get("/learning/strategy-log/{student_id}")
def learning_strategy_log(student_id: int, limit: int = 20,
                          db: Session = Depends(get_db)):
    """策略日志 + 学习反馈历史：系统为什么这样安排。"""
    return {
        "student_id": student_id,
        "logs": ENGINE.strategy_logs(db, student_id, limit=limit),
        "feedback": ENGINE.feedback_history(db, student_id, limit=limit),
        "feel_text": difficulty.FEEL_TEXT,
        "planning": {
            "default_minutes": planner.DEFAULT_MINUTES,
            "total_minutes": planner.DEFAULT_TOTAL_MINUTES,
            "status_text": planner.STATUS_TEXT,
        },
    }
