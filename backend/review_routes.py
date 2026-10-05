# ==============================================================
# 能力契约｜/api/review/* 间隔复习接口
# 入口：router / review_today / review_due / review_question / review_answer / review_memory_map / review_stats / review_strategy_log / review_skip / review_feedback
# 依赖：review.engine / review.interval / review.memory / review.mix / review.scheduler / stages / database
# 不负责：复习算法 → review/ 各纯函数模块；旧艾宾浩斯 → srs.py
# 验证：python backend/verify_memory.py
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 API。

    GET  /api/review/today/{student_id}         今日复习任务（儿童端友好文案）
    GET  /api/review/due/{student_id}           所有到期 / 高风险知识点
    GET  /api/review/question                   获取复习题（不重复历史原题）
    POST /api/review/answer                     提交复习答案（更新记忆状态）
    GET  /api/review/memory-map/{student_id}    各知识点记忆状态（家长/调试）
    GET  /api/review/stats/{student_id}         今日复习 / 完成 / 即将遗忘 / 长期掌握
    GET  /api/review/strategy-log/{student_id}  复习算法日志（为什么改复习日期）
    POST /api/review/skip                       跳过今天的某个复习任务
    POST /api/review/feedback                   孩子对复习题的主观感受（微调间隔）
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import stages
from database import get_db
from review import engine as review_engine
from review import interval, memory, mix, scheduler

router = APIRouter(prefix="/api/review", tags=["间隔复习 V2.4"])

ENGINE = review_engine.DEFAULT_ENGINE


class ReviewAnswerIn(BaseModel):
    student_id: int = 1
    question_id: int = 0
    answer: str = ""
    response_time: float = 0.0          # 作答耗时（秒）
    difficulty_feedback: str = ""       # easy / normal / hard / lost（孩子自评）


class SkipIn(BaseModel):
    student_id: int = 1
    queue_id: int = 0


class FeelIn(BaseModel):
    student_id: int = 1
    question_id: int = 0
    feel: str = ""                      # easy / normal / hard / lost


def _subject_or_400(subject):
    text = str(subject or "").strip()
    if text not in stages.SUBJECTS:
        raise HTTPException(status_code=400,
                            detail=f"科目必须是：{'、'.join(stages.SUBJECTS)}")
    return text


@router.get("/today/{student_id}")
def review_today(student_id: int, refresh: bool = False, db: Session = Depends(get_db)):
    """今日复习任务：几个知识需要"浇水"、各自什么状态、每题出几道。"""
    data = ENGINE.today(db, student_id, refresh=refresh)
    data["maturity_child"] = memory.MATURITY_CHILD
    data["priority_text"] = scheduler.PRIORITY_TEXT
    return data


@router.get("/due/{student_id}")
def review_due(student_id: int, limit: int = 100, db: Session = Depends(get_db)):
    """所有到期 / 高风险知识点（含遗忘风险与成熟度）。"""
    return ENGINE.due(db, student_id, limit=limit)


@router.get("/question")
def review_question(student_id: int = 1, subject: str = stages.DEFAULT_SUBJECT,
                    knowledge_id: str = "", difficulty: int = 0, use_ai: bool = False,
                    db: Session = Depends(get_db)):
    """获取一道复习题（同一知识点不会重复出旧题）。"""
    subject = _subject_or_400(subject)
    knowledge = str(knowledge_id or "").strip()
    if not knowledge:
        raise HTTPException(status_code=400, detail="必须指定 knowledge_id")

    return ENGINE.review_question(db, student_id, subject, knowledge,
                                  difficulty=difficulty or None, use_ai=use_ai)


@router.post("/answer")
def review_answer(payload: ReviewAnswerIn, db: Session = Depends(get_db)):
    """提交复习答案：返回判分、复习质量、新的记忆强度 / 稳定性 / 下次复习时间。"""
    feedback = str(payload.difficulty_feedback or "").strip().lower()
    if feedback and feedback not in ("easy", "normal", "hard", "lost", ""):
        raise HTTPException(status_code=400,
                            detail="难度感受只能是 easy / normal / hard / lost")

    result = ENGINE.submit_review(db, payload.student_id, {
        "question_id": payload.question_id,
        "answer": payload.answer,
        "response_time": payload.response_time,
        "difficulty_feedback": feedback,
    })
    if result is None:
        raise HTTPException(status_code=404, detail="复习题不存在，请重新获取题目")

    result["quality_text"] = interval.QUALITY_TEXT
    result["maturity_levels"] = list(memory.MATURITY_LEVELS)
    return result


@router.get("/memory-map/{student_id}")
def review_memory_map(student_id: int, subject: str = "", db: Session = Depends(get_db)):
    """各知识点的记忆状态（掌握度 / 稳定性 / 遗忘风险 / 成熟度）——家长与调试用。"""
    if subject:
        subject = _subject_or_400(subject)

    return ENGINE.memory_map(db, student_id, subject=subject or None)


@router.get("/stats/{student_id}")
def review_stats(student_id: int, db: Session = Depends(get_db)):
    """今日复习数量 / 完成数量 / 即将遗忘数量 / 长期掌握数量。"""
    data = ENGINE.stats(db, student_id)
    data["maturity_child"] = memory.MATURITY_CHILD
    return data


@router.get("/strategy-log/{student_id}")
def review_strategy_log(student_id: int, limit: int = 20,
                        db: Session = Depends(get_db)):
    """复习算法日志 + 复习明细：每次改复习日期的原因。"""
    return {
        "student_id": student_id,
        "logs": ENGINE.strategy_logs(db, student_id, limit=limit),
        "history": ENGINE.review_history(db, student_id, limit=limit),
        "today_mix": ENGINE.mix_for(db, student_id),
        "mix_default": mix.DEFAULT_MIX,
        "interval_ladder": list(interval.LADDER),
        "quality_text": interval.QUALITY_TEXT,
    }


@router.post("/skip")
def review_skip(payload: SkipIn, db: Session = Depends(get_db)):
    """跳过今天某个复习任务（不惩罚，只是今天不复习它）。"""
    result = ENGINE.skip(db, payload.student_id, payload.queue_id)
    if result is None:
        raise HTTPException(status_code=404, detail="复习任务不存在")
    return result


@router.post("/feedback")
def review_feedback(payload: FeelIn, db: Session = Depends(get_db)):
    """孩子对这道复习题的主观感受：只轻微调整下次间隔（±5%）。"""
    feel = str(payload.feel or "").strip().lower()
    if feel not in ("easy", "normal", "hard", "lost"):
        raise HTTPException(status_code=400,
                            detail="难度感受只能是 easy / normal / hard / lost")

    result = ENGINE.apply_feedback(db, payload.student_id, {
        "question_id": payload.question_id, "feel": feel})
    if result is None:
        raise HTTPException(status_code=404, detail="找不到对应的复习记录")
    return result
