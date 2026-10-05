# ==============================================================
# 能力契约｜/api/deep-mastery/* /api/root-cause/* /api/transfer/* /api/explain/* /api/confidence /api/learning-efficiency/* 深度学习接口
# 入口：router / deep_mastery_map / deep_mastery_summary / deep_mastery_growth / deep_mastery_detail / root_cause_detail / learning_efficiency / transfer_start / transfer_answer / explain_start / explain_submit / confidence_feedback
# 依赖：deep_learning.engine（DEFAULT_ENGINE）、deep_learning.confidence_engine、deep_learning.transfer_engine、deep_learning.variant_ladder、models、database.get_db、grading.is_correct、stages
# 不负责：算法与阈值 → deep_learning/*.py；旧主动回忆接口 → active_recall_routes.py（本文件不重复 /api/active-recall/*）
# 验证：python backend/verify_v27.py
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 深度学习 API（需求 §三十九）。

    GET  /api/deep-mastery/{student_id}/{knowledge_id}   三层并列状态（mastery / deep / memory）
    GET  /api/deep-mastery/map/{student_id}              知识地图深度状态
    GET  /api/deep-mastery/summary/{student_id}          深度掌握汇总
    GET  /api/deep-mastery/growth/{student_id}           深度成长（本周）
    GET  /api/root-cause/{student_id}/{knowledge_id}     薄弱根因 + 最小回补
    GET  /api/learning-efficiency/{student_id}           学习效率（内部指标，儿童端只用 child_text）
    POST /api/transfer/start                             变式阶梯出题（T0~T5）
    POST /api/transfer/answer                            变式作答（判分在服务端）
    POST /api/explain/start                              是否要求「讲给菲比听」
    POST /api/explain/submit                             提交解释并评估概念覆盖
    POST /api/confidence                                 自信度选项 / 提交自信度（正确性 × 自信度）

纪律（与 V2.0~V2.6 一致，需求 §四十 / §四十二）：

* 全部按 ``student_id`` 过滤，A（1）的数据绝不被 B（2）读到；
* 学生不存在、题目不存在、参数为空一律返回**空结构**，只有 ``date`` / ``subject`` 非法才 400；
* 内部异常由 ``_safe`` 兜住，**绝不 500**；AI 异常一律本地降级（需求 §三十七）；
* 儿童端只拿到 ``child_text`` / ``child_stage``，**永远拿不到 deep_mastery_score 数字**（需求 §二十六）。
"""

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import grading
import stages
from database import get_db
from deep_learning import confidence_engine
from deep_learning import engine as deep_engine
from deep_learning import transfer_engine
from deep_learning import variant_ladder
from models import LearningEvidence, Question, Student

router = APIRouter(prefix="/api", tags=["深度学习 V2.7"])

ENGINE = deep_engine.DEFAULT_ENGINE

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_TRANSFER_QUESTIONS = variant_ladder.MAX_STEPS_PER_ROUND

TRANSFER_DONE_TEXT = "这一轮变式练习完成啦，菲比已经把结果记下来～"


# --------------------------------------------------------------
# 入参
# --------------------------------------------------------------

class TransferStartIn(BaseModel):
    student_id: int = Field(..., ge=1)
    subject: str = "数学"
    knowledge_id: str = ""
    grade: int = Field(0, ge=0, le=6)
    minutes: int = Field(0, ge=0, le=60)
    use_ai: bool = True


class TransferAnswerIn(BaseModel):
    student_id: int = Field(..., ge=1)
    question_id: int = Field(..., ge=1)
    answer: str = ""
    subject: str = ""
    knowledge_id: str = ""
    transfer_level: int = Field(-1, ge=-1, le=5)
    hint_used: int = Field(0, ge=0, le=4)
    response_time: float = Field(0.0, ge=0.0, le=86400.0)
    confidence: str = ""
    state: dict = Field(default_factory=dict)


class ExplainStartIn(BaseModel):
    student_id: int = Field(..., ge=1)
    subject: str = "数学"
    knowledge_id: str = ""
    question: str = ""
    transfer_failed: bool = False


class ExplainSubmitIn(BaseModel):
    student_id: int = Field(..., ge=1)
    subject: str = "数学"
    knowledge_id: str = ""
    question: str = ""
    response: str = ""
    grade: int = Field(0, ge=0, le=6)
    transfer_failed: bool = False
    use_ai: bool = True


class ConfidenceIn(BaseModel):
    student_id: int = Field(..., ge=1)
    subject: str = ""
    knowledge_id: str = ""
    confidence: str = ""
    correct: bool = True
    scene: str = ""
    response_time: float = Field(0.0, ge=0.0, le=86400.0)
    difficulty: int = Field(50, ge=0, le=100)
    hint_level: int = Field(0, ge=0, le=4)
    apply_to_evidence: bool = True


# --------------------------------------------------------------
# 兜底工具（与 active_recall_routes.py 同款纪律）
# --------------------------------------------------------------

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


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _subject_or_400(value, default=""):
    text = str(value or "").strip()
    if not text:
        return default
    if text not in stages.SUBJECTS:
        raise HTTPException(status_code=400,
                            detail="科目必须是：" + "、".join(stages.SUBJECTS))
    return text


def _day_or_400(value):
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


def _student_exists(db, student_id):
    try:
        return db.query(Student).filter(Student.id == student_id).first() is not None
    except Exception:                          # noqa: BLE001
        return False


def _dumps(value):
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"


# --------------------------------------------------------------
# 空结构（学生不存在 / 无数据时返回，绝不 404）
# --------------------------------------------------------------

def _empty_detail(student_id, subject, knowledge):
    return {
        "student_id": student_id, "subject": subject, "knowledge": knowledge,
        "has_data": False, "level": 0, "level_key": "UNKNOWN", "level_info": None,
        "child_stage": None, "abilities": {}, "dimensions": {}, "dimension_text": {},
        "evidence_count": 0, "counts": {}, "hint_dependency": 0.0, "guess_count": 0,
        "misconception_flag": False, "upgrade": {}, "child_text": "",
    }


def _empty_map(student_id):
    return {"student_id": student_id, "stage_keys": [], "child_stages": {},
            "levels": {}, "total": 0}


def _empty_summary(student_id):
    return {"student_id": student_id, "total": 0, "levels": {}, "by_level": {},
            "child_stages": {}, "dimensions": {}, "weakest": [], "strongest": []}


def _empty_growth(student_id, days=7):
    return {"student_id": student_id, "days": days, "active_count": 0, "apply_count": 0,
            "apply_total": 0, "star_count": 0, "new_star_count": 0, "items": [],
            "stars": [], "child_text": ""}


def _empty_repair(student_id, subject, knowledge):
    return {"student_id": student_id, "subject": subject, "knowledge": knowledge,
            "has_data": False, "level": 0, "level_key": "UNKNOWN", "items": [],
            "latest": None, "repair": None, "misconception": {}, "child_text": ""}


def _empty_efficiency(student_id, days=7):
    return {"student_id": student_id, "days": days, "score": 0, "band": "unknown",
            "band_text": "", "has_data": False, "child_text": "", "parent_text": "",
            "advice": [], "note": ""}


def _empty_transfer(student_id, subject, knowledge):
    return {"student_id": student_id, "subject": subject, "knowledge": knowledge,
            "mode": "TRANSFER_LADDER", "start_level": 0, "steps": [], "count": 0,
            "minutes": 0, "max_steps": MAX_TRANSFER_QUESTIONS, "message": "",
            "question": None, "question_id": 0, "state": {}, "levels": [],
            "available": False, "child_text": "今天没有变式练习，我们先把基础练牢～"}


def _empty_explain_start(student_id, subject, knowledge):
    return {"student_id": student_id, "subject": subject, "knowledge": knowledge,
            "ask": False, "reason": "", "reasons": [], "text": "", "child": "",
            "prompt": {"knowledge": knowledge, "question": "", "text": "", "child": ""},
            "asked_before": 0, "options": []}


def _empty_explain_submit(student_id, subject, knowledge):
    return {"student_id": student_id, "subject": subject, "knowledge": knowledge,
            "core_concept_correct": False, "concept_coverage": 0.0,
            "quality_score": 0, "missing_concepts": [], "possible_misconceptions": [],
            "feedback": "", "child_feedback": "", "result": "", "evidence": None}


# --------------------------------------------------------------
# 出题落库（迁移题必须服务端保存答案，前端拿不到）
# --------------------------------------------------------------

def _persist_question(db, subject, grade, knowledge, data):
    """把生成出来的迁移题写进 questions 表，返回 (row, level)。"""
    if not isinstance(data, dict):
        return None, 0
    text = _text(data.get("question"))
    answer = _text(data.get("answer"))
    if not text or not answer:
        return None, 0
    try:
        level = transfer_engine.clamp_level(data.get("level", 0))
    except Exception:                          # noqa: BLE001
        level = 0
    row = Question(
        subject=subject,
        grade=int(grade or 3),
        knowledge=knowledge,
        difficulty=int(data.get("difficulty") or 50),
        question=text,
        answer=answer,
        qtype=_text(data.get("qtype"), "choice"),
        options=_dumps(data.get("options") or {}),
        acceptable=_dumps(data.get("acceptable") or []),
        analysis=_text(data.get("analysis")),
    )
    db.add(row)
    db.flush()
    return row, level


def _question_payload(row, level, data=None):
    """下发给儿童端的题目：**只有题干与选项，没有答案**。"""
    data = data if isinstance(data, dict) else {}
    options = data.get("options")
    if not options:
        try:
            options = json.loads(row.options or "{}")
        except (TypeError, ValueError):
            options = {}
    return {
        "question_id": row.id,
        "subject": row.subject,
        "knowledge": row.knowledge,
        "question": row.question,
        "qtype": row.qtype,
        "options": options,
        "difficulty": row.difficulty,
        "transfer_level": level,
        "level_info": transfer_engine.level_dict(level),
        "source": _text(data.get("source"), "local"),
        "variant_change": _text(data.get("variant_change")),
        "child_text": _text((data.get("level_info") or {}).get("child")) if isinstance(
            data.get("level_info"), dict) else "",
    }


# --------------------------------------------------------------
# 深度掌握状态
# --------------------------------------------------------------

@router.get("/deep-mastery/map/{student_id}")
def deep_mastery_map(student_id: int, subject: str = Query(""), db: Session = Depends(get_db)):
    """知识地图用的深度状态表：``{知识点: {level, stage_key, icon, text}}``（需求 §三十二）。"""
    subject = _subject_or_400(subject)
    if not _student_exists(db, student_id):
        return _empty_map(student_id)
    data = _safe(db, lambda: ENGINE.map_levels(db, student_id, subject or None), None)
    if not data:
        return _empty_map(student_id)
    levels = data
    return {
        "student_id": student_id,
        "subject": subject,
        "stage_keys": [item.get("stage_key") for item in levels.values()],
        "child_stages": {name: item.get("stage_key") for name, item in levels.items()},
        "levels": levels,
        "total": len(levels),
    }


@router.get("/deep-mastery/summary/{student_id}")
def deep_mastery_summary(student_id: int, subject: str = Query(""),
                         db: Session = Depends(get_db)):
    """深度掌握汇总：等级分布 + 六维平均（内部指标，儿童端不展示数字）。"""
    subject = _subject_or_400(subject)
    if not _student_exists(db, student_id):
        return _empty_summary(student_id)
    data = _safe(db, lambda: ENGINE.summary(db, student_id, subject or None), None)
    if not data:
        return _empty_summary(student_id)
    data["student_id"] = student_id
    return data


@router.get("/deep-mastery/growth/{student_id}")
def deep_mastery_growth(student_id: int, days: int = Query(7, ge=1, le=90),
                        db: Session = Depends(get_db)):
    """深度成长（需求 §三十三）：本周几个知识从「会做」升到「会应用」、几个达到 ⭐。"""
    if not _student_exists(db, student_id):
        return _empty_growth(student_id, days)
    data = _safe(db, lambda: ENGINE.growth(db, student_id, days=days), None)
    if not data:
        return _empty_growth(student_id, days)
    data["student_id"] = student_id
    return data


@router.get("/deep-mastery/{student_id}/{knowledge_id}")
def deep_mastery_detail(student_id: int, knowledge_id: str, subject: str = Query("数学"),
                        db: Session = Depends(get_db)):
    """三层并列：``mastery``（会不会做）/ ``deep_mastery``（真懂并能迁移）/ ``memory``（还记不记得）。"""
    subject = _subject_or_400(subject, stages.DEFAULT_SUBJECT)
    knowledge = _text(knowledge_id)
    if not _student_exists(db, student_id) or not knowledge:
        return _empty_detail(student_id, subject, knowledge)
    detail = _safe(db, lambda: ENGINE.detail(db, student_id, subject, knowledge), None)
    if not detail:
        return _empty_detail(student_id, subject, knowledge)
    status = _safe(db, lambda: ENGINE.status(db, student_id, subject, knowledge), {}) or {}
    miscon = _safe(db, lambda: ENGINE.misconception(db, student_id, subject, knowledge), {}) or {}
    return {
        "student_id": student_id,
        "subject": subject,
        "knowledge": knowledge,
        "has_data": bool(detail.get("evidence_count")),
        "level": detail.get("level", 0),
        "level_key": detail.get("level_key", "UNKNOWN"),
        "level_info": detail.get("level_info"),
        "child_stage": detail.get("child_stage"),
        "abilities": detail.get("abilities") or {},
        "dimensions": detail.get("dimensions") or {},
        "dimension_text": detail.get("dimension_text") or {},
        "evidence_count": detail.get("evidence_count", 0),
        "counts": detail.get("counts") or {},
        "hint_dependency": detail.get("hint_dependency", 0.0),
        "guess_count": detail.get("guess_count", 0),
        "misconception_flag": detail.get("misconception_flag", False),
        "upgrade": detail.get("upgrade") or {},
        "misconception": miscon,
        "mastery": status.get("mastery") or {},
        "memory": status.get("memory") or {},
        "separate": True,
        # 儿童端只用这句话；deep_mastery_score 数字不出现在儿童端
        "child_text": "菲比觉得这个知识你已经%s啦" % (
            (detail.get("level_info") or {}).get("child", "开始接触")),
    }


# --------------------------------------------------------------
# 根因 / 效率
# --------------------------------------------------------------

@router.get("/root-cause/{student_id}/{knowledge_id}")
def root_cause_detail(student_id: int, knowledge_id: str, subject: str = Query("数学"),
                      limit: int = Query(5, ge=1, le=20), db: Session = Depends(get_db)):
    """薄弱根因：不只「应用题做错了」，而是「为什么错」（需求 §七~§十二）。"""
    subject = _subject_or_400(subject, stages.DEFAULT_SUBJECT)
    knowledge = _text(knowledge_id)
    if not _student_exists(db, student_id) or not knowledge:
        return _empty_repair(student_id, subject, knowledge)
    data = _safe(db, lambda: ENGINE.root_cause_detail(db, student_id, knowledge=knowledge,
                                                      subject=subject, limit=limit), None)
    if not data:
        return _empty_repair(student_id, subject, knowledge)
    repair = data.get("repair")
    child = "我们先补一个小前置知识，再回来做这个～" if repair else (
        data.get("child_text") or "菲比还在观察这个知识点～")
    data.update({"student_id": student_id, "subject": subject, "knowledge": knowledge,
                 "has_data": bool(data.get("latest") or data.get("items")),
                 "child_text": child})
    return data


@router.get("/learning-efficiency/{student_id}")
def learning_efficiency(student_id: int, days: int = Query(7, ge=1, le=90),
                        db: Session = Depends(get_db)):
    """学习效率（需求 §二十八 / §二十九）：给 Adaptive / Daily Plan / 家长报告用，儿童端只看 child_text。"""
    if not _student_exists(db, student_id):
        return _empty_efficiency(student_id, days)
    data = _safe(db, lambda: ENGINE.efficiency(db, student_id, days=days), None)
    if not data:
        return _empty_efficiency(student_id, days)
    data["student_id"] = student_id
    data["days"] = days
    return data


# --------------------------------------------------------------
# 知识迁移（变式阶梯）
# --------------------------------------------------------------

@router.post("/transfer/start")
def transfer_start(payload: TransferStartIn, db: Session = Depends(get_db)):
    """开始一轮变式练习：一轮最多 3 题（需求 §十五 / §四十二，不无限追加）。"""
    subject = _subject_or_400(payload.subject, stages.DEFAULT_SUBJECT)
    knowledge = _text(payload.knowledge_id)
    if not _student_exists(db, payload.student_id) or not knowledge:
        return _empty_transfer(payload.student_id, subject, knowledge)
    plan = _safe(db, lambda: ENGINE.transfer_plan(
        db, payload.student_id, subject, knowledge,
        minutes=payload.minutes or None, use_ai=payload.use_ai,
        grade=payload.grade or None), None)
    if not plan:
        return _empty_transfer(payload.student_id, subject, knowledge)

    data = plan.get("question")
    question_row, level = (None, 0)
    if isinstance(data, dict):
        question_row, level = _safe(db, lambda: _persist_question(
            db, subject, payload.grade or plan.get("grade") or 3, knowledge, data), (None, 0))
        if question_row is not None:
            db.commit()

    state = variant_ladder.DEFAULT_ENGINE.initial_state(
        level=int(plan.get("start_level") or level or 0))
    out = dict(plan)
    out.update({
        "student_id": payload.student_id,
        "subject": subject,
        "knowledge": knowledge,
        "question_id": question_row.id if question_row is not None else 0,
        "question": _question_payload(question_row, level, data) if question_row is not None else None,
        "state": state,
        "max_steps": MAX_TRANSFER_QUESTIONS,
        "levels": transfer_engine.levels(),
        "available": question_row is not None,
        "child_text": "我们换一种问法试试，看看是不是真的会啦～" if question_row is not None
        else "今天没有合适的变式题，我们先把基础练牢～",
    })
    return out


@router.post("/transfer/answer")
def transfer_answer(payload: TransferAnswerIn, db: Session = Depends(get_db)):
    """提交变式作答：判分在服务端（前端拿不到答案），结果落 transfer_attempt + TRANSFER 证据。"""
    if not _student_exists(db, payload.student_id):
        return _empty_transfer(payload.student_id, _text(payload.subject), _text(payload.knowledge_id))
    row = _safe(db, lambda: db.query(Question).filter(Question.id == payload.question_id).first(), None)
    if row is None:
        return _empty_transfer(payload.student_id, _text(payload.subject), _text(payload.knowledge_id))

    subject = _subject_or_400(payload.subject, row.subject or stages.DEFAULT_SUBJECT)
    knowledge = _text(payload.knowledge_id, row.knowledge or "")
    level = payload.transfer_level
    if level < 0:
        level = _safe(db, lambda: _level_of_attempt(db, payload.student_id, subject, knowledge,
                                                    payload.question_id), 0)

    correct = bool(grading.is_correct(row, payload.answer))

    data = _safe(db, lambda: ENGINE.record_transfer(
        db, payload.student_id, subject, knowledge,
        level=level, correct=correct, question_id=row.id,
        hint_used=payload.hint_used, response_time=payload.response_time,
        source="api", confidence=payload.confidence), None)
    if not data:
        return _empty_transfer(payload.student_id, subject, knowledge)

    # 变式阶梯：根据表现升级 / 保持 / 回退（需求 §十五），一轮最多 3 题
    state = payload.state if isinstance(payload.state, dict) and payload.state else \
        variant_ladder.DEFAULT_ENGINE.initial_state(level)
    new_state = variant_ladder.DEFAULT_ENGINE.apply_attempt(
        state, correct, payload.hint_used, payload.confidence)
    tried = int(new_state.get("total") or 0)
    remaining = max(0, MAX_TRANSFER_QUESTIONS - tried)
    decision = variant_ladder.DEFAULT_ENGINE.decide(
        new_state, remaining=remaining, minutes=0)
    summary = variant_ladder.DEFAULT_ENGINE.round_summary(
        new_state, mastery_score=ENGINE._mastery_of(db, payload.student_id, subject, knowledge))

    opportunity = None
    if not decision.get("stop") and remaining > 0:
        nxt = _safe(db, lambda: transfer_engine.DEFAULT_ENGINE.make_question(
            subject, knowledge, decision.get("level", level),
            grade=row.grade or 3, use_ai=False), None)
        next_row, next_level = (None, 0)
        if isinstance(nxt, dict):
            next_row, next_level = _safe(db, lambda: _persist_question(
                db, subject, row.grade or 3, knowledge, nxt), (None, 0))
            if next_row is not None:
                db.commit()
        if next_row is not None:
            opportunity = _question_payload(next_row, next_level, nxt)

    judgment = data.get("judgment") or {}
    child = judgment.get("message") or TRANSFER_DONE_TEXT
    if not correct and level >= 2:
        child = "换个问法你还有点不确定，这说明不是不会做，是还没完全理解关系～"
    elif decision.get("child"):
        child = decision.get("child")

    out = dict(data)
    out.update({
        "student_id": payload.student_id,
        "subject": subject,
        "knowledge": knowledge,
        "correct": correct,
        "correct_answer": row.answer,
        "transfer_level": level,
        "state": new_state,
        "decision": decision,
        "summary": summary,
        "next_question": opportunity,
        "max_steps": MAX_TRANSFER_QUESTIONS,
        "available": True,
        "child_text": child,
    })
    return out


def _level_of_attempt(db, student_id, subject, knowledge, question_id):
    try:
        from models import TransferAttempt

        row = (db.query(TransferAttempt)
               .filter(TransferAttempt.student_id == student_id,
                       TransferAttempt.question_id == question_id)
               .order_by(TransferAttempt.id.desc()).first())
        return int(row.transfer_level) if row is not None else 0
    except Exception:                          # noqa: BLE001
        return 0


# --------------------------------------------------------------
# 解释（讲给菲比听）
# --------------------------------------------------------------

@router.post("/explain/start")
def explain_start(payload: ExplainStartIn, db: Session = Depends(get_db)):
    """是否值得要求解释（需求 §二十五：只用于核心知识 / 多次错误 / 迁移失败 / 疑似机械记忆）。"""
    subject = _subject_or_400(payload.subject, stages.DEFAULT_SUBJECT)
    knowledge = _text(payload.knowledge_id)
    if not _student_exists(db, payload.student_id) or not knowledge:
        return _empty_explain_start(payload.student_id, subject, knowledge)
    data = _safe(db, lambda: ENGINE.explain_should_ask(
        db, payload.student_id, subject, knowledge,
        transfer_failed=payload.transfer_failed), None)
    if not data:
        return _empty_explain_start(payload.student_id, subject, knowledge)
    prompt = _safe(db, lambda: ENGINE.explain_prompt(subject, knowledge, payload.question), {}) or {}
    data.update({"student_id": payload.student_id, "subject": subject, "knowledge": knowledge,
                 "prompt": prompt})
    return data


@router.post("/explain/submit")
def explain_submit(payload: ExplainSubmitIn, db: Session = Depends(get_db)):
    """提交「讲给菲比听」：概念覆盖评估 → EXPLANATION 证据 → Deep Mastery 更新。

    AI 只做辅助评价，**不得直接修改 mastery / deep_mastery**（需求 §三十六）。
    """
    subject = _subject_or_400(payload.subject, stages.DEFAULT_SUBJECT)
    knowledge = _text(payload.knowledge_id)
    if not _student_exists(db, payload.student_id) or not knowledge:
        return _empty_explain_submit(payload.student_id, subject, knowledge)
    if not _text(payload.response):
        return _empty_explain_submit(payload.student_id, subject, knowledge)
    data = _safe(db, lambda: ENGINE.record_explanation(
        db, payload.student_id, subject, knowledge,
        question=payload.question, student_response=payload.response,
        grade=payload.grade or 3, transfer_failed=payload.transfer_failed,
        use_ai=payload.use_ai), None)
    if not data:
        return _empty_explain_submit(payload.student_id, subject, knowledge)
    out = dict(data)
    out.update({"student_id": payload.student_id, "subject": subject, "knowledge": knowledge})
    return out


# --------------------------------------------------------------
# 自信度（正确性 × 自信度）
# --------------------------------------------------------------

@router.post("/confidence")
def confidence_feedback(payload: ConfidenceIn, db: Session = Depends(get_db)):
    """自信度：不带 ``confidence`` 时返回选项与「是否该问」；带了则按矩阵回写证据权重。"""
    options = confidence_engine.CONFIDENCE_OPTIONS
    subject = _subject_or_400(payload.subject, stages.DEFAULT_SUBJECT)
    knowledge = _text(payload.knowledge_id)
    key = _text(payload.confidence).lower()

    if not _student_exists(db, payload.student_id) or not knowledge:
        return {"student_id": payload.student_id, "subject": subject, "knowledge": knowledge,
                "options": [dict(item) for item in options], "confidence_key": key,
                "matrix": {}, "verify": {}, "saved": False,
                "should_ask": False, "child_text": ""}

    mastery = _safe(db, lambda: ENGINE._mastery_of(db, payload.student_id, subject, knowledge), 0)
    should_ask = _safe(db, lambda: ENGINE.confidence_should_ask(
        payload.scene, payload.difficulty, payload.hint_level, payload.correct,
        payload.response_time, mastery), False)

    if not key:
        return {"student_id": payload.student_id, "subject": subject, "knowledge": knowledge,
                "options": [dict(item) for item in options], "confidence_key": "",
                "matrix": {}, "verify": {}, "saved": False,
                "should_ask": bool(should_ask), "child_text": ""}

    plan = _safe(db, lambda: ENGINE.confidence_plan(
        correct=payload.correct, confidence_key=key, mastery_score=mastery,
        response_time=payload.response_time), {}) or {}

    saved = False
    if payload.apply_to_evidence:
        saved = bool(_safe(db, lambda: _apply_confidence(
            db, payload.student_id, subject, knowledge, key), False))

    return {
        "student_id": payload.student_id,
        "subject": subject,
        "knowledge": knowledge,
        "options": [dict(item) for item in options],
        "confidence_key": key,
        "matrix": plan.get("matrix") or {},
        "verify": plan.get("verify") or {},
        "should_ask": bool(should_ask),
        "saved": saved,
        "child_text": (plan.get("verify") or {}).get("child_message", ""),
    }


def _apply_confidence(db, student_id, subject, knowledge, key):
    """把自信度打到最近一条还没有自信度的证据上，并按矩阵重算权重（需求 §二十）。"""
    from deep_learning import evidence as evidence_module

    row = (db.query(LearningEvidence)
           .filter(LearningEvidence.student_id == student_id,
                   LearningEvidence.subject == subject,
                   LearningEvidence.knowledge_id == knowledge)
           .order_by(LearningEvidence.id.desc()).first())
    if row is None:
        return False
    row.confidence = key
    row.weight = evidence_module.weight_of(
        row.evidence_type, row.result, row.hint_level or 0, key)
    db.commit()
    ENGINE.refresh(db, student_id, subject, knowledge)
    return True
