# ==============================================================
# 能力契约｜应用装配（FastAPI/CORS/路由注册/静态挂载）+ 核心闭环 API（出题、判分、复习总览）
# 入口：app / home / students / question / submit / reviews
# 依赖：database models deepseek(含 history 防雷同) grading validator ability srs stages mastery wrong_book error_analysis knowledge_tree local_users + 各 router
# 不负责：业务算法（阶段判定/掌握度/复习调度/自适应）→ stages.py / mastery.py / srs.py / review/ / adaptive/
# 验证：python backend/verify_flow.py --self-serve
# 被调用：uvicorn 加载入口；adaptive/engine.py 函数内 import 复用 question
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

import json
import os
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ability import calculate_stage, next_difficulty
from ability_routes import router as ability_router
from adaptive_routes import router as adaptive_router
from database import SessionLocal, engine, ensure_schema, get_db, migrate_data
from deepseek import CHOICE, FALLBACK, generate_question
from diagnostic_routes import router as diagnostic_router
import error_analysis
from grading import is_correct
from knowledge_routes import router as knowledge_router, update_mastery
import knowledge_tree
from local_users import init_default_users
import mastery
from models import (
    Ability,
    AbilityProfile,
    AnswerRecord,
    Base,
    Question,
    Review,
    Student,
    StudentKnowledgeMastery,
)
from habit_routes import router as habit_router
from active_recall_routes import router as active_recall_router
from daily_routes import router as daily_router
from phoebe_routes import router as phoebe_router
from recovery_routes import router as recovery_router
from task_routes import router as task_router
# V2.6 儿童体验层：首页聚合 / 成长中心 / 知识地图 / 挑战中心
from home_routes import router as home_router
from growth_routes import router as growth_router
from knowledge_map_routes import router as knowledge_map_router
from challenge_routes import router as challenge_router
from user_routes import router as user_router
# V2.7 深度学习层：/api/deep-mastery、/api/root-cause、/api/transfer、/api/explain、/api/confidence、/api/learning-efficiency
from deep_learning_routes import router as deep_learning_router
# V2.8 积分系统：学习挣积分（每日打卡 / 答对一题 / 计划做完后继续练 / 任务收工）+ 首页商城（比例先占位、不实装）
from points_routes import router as points_router
import srs
import stages
import validator
import wrong_book
from review_routes import router as review_router

Base.metadata.create_all(engine)
ensure_schema(Base)
# V2.3：把 V2.2 的掌握度列搬到新的掌握模型列上（幂等）
migrate_data()

# V2.8：应用版本号唯一真相 = 项目根 version.json（自动更新与「对比仓库版本号」都读它）
try:
    import updater as _updater

    APP_VERSION = _updater.local_version()
except Exception:  # 版本文件缺失/损坏时退回内置号，绝不拦启动
    APP_VERSION = "2.8.0"

app = FastAPI(title="菲比同学 V" + APP_VERSION)

# 前端用 file:// 或 Live Server 打开时都是跨域请求，不加这个浏览器会直接拦掉
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# V2.6：/app 下的前端静态资源一律不缓存 —— 改完 js/css 刷新即生效，不用再手动强刷
@app.middleware("http")
async def no_store_frontend(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# V2.2 能力诊断：/api/diagnostic/start|question|answer|report
app.include_router(diagnostic_router)

# V2.3 知识掌握 / 错因分析 / 错题本：/api/mastery、/api/errors、/api/wrong_questions ...
app.include_router(knowledge_router)

# V2.3 自适应学习引擎：/api/learning/recommend|start|next-question|feedback|plan
app.include_router(adaptive_router)

# V2.4 间隔复习系统：/api/review/today|due|question|answer|memory-map|stats
app.include_router(review_router)

# V2.5 训练数据自动能力诊断：/api/ability/auto/{student_id}
app.include_router(ability_router)

# V2.5 菲比陪伴对话：/api/phoebe/chat（读学习数据 + DeepSeek 生成一句给孩子听的话）
app.include_router(phoebe_router)

# V2.5 错题康复：/api/recovery/list|start|question|answer|verify|hint
app.include_router(recovery_router)

# V2.5 每日任务与学习习惯：/api/tasks/today|complete、/api/habit/profile|stats
app.include_router(task_router)
app.include_router(habit_router)

# V2.5 主动回忆（基础版）：/api/active-recall/start|answer|summary
app.include_router(active_recall_router)

# V2.5 每日总结与学习目标：/api/daily-summary/{student_id}
app.include_router(daily_router)

# V2.6 儿童端聚合与展示层：/api/home、/api/growth、/api/knowledge-map、/api/challenge
app.include_router(home_router)
app.include_router(growth_router)
app.include_router(knowledge_map_router)
app.include_router(challenge_router)
# 家长端：备份并重置某个小朋友的学习数据（/api/user/...）
app.include_router(user_router)

# V2.7 深度学习 / 主动记忆 / 知识迁移 / 薄弱根因：/api/deep-mastery|root-cause|transfer|explain|confidence|learning-efficiency
app.include_router(deep_learning_router)
# V2.8 积分：/api/points/{student_id}、/api/points/{student_id}/shop、/api/points/{student_id}/checkin
app.include_router(points_router)
_db = SessionLocal()
init_default_users(_db)
# V2.3：知识点树灌库 → 把已有掌握度挂到树上 → 给历史错题补错因
knowledge_tree.ensure_seeded(_db)
knowledge_tree.link_mastery(_db)
error_analysis.backfill(_db, limit=200)
# V2.4：按 V2.3 的掌握度初始化记忆状态（幂等，老数据安全升级）
import review.engine as review_engine_module

review_engine_module.DEFAULT_ENGINE.ensure_states(_db)

# V2.5：历史错题补进康复队列 + 给每个学生备好今天的任务（两者都幂等，失败不影响启动）
try:
    from recovery import scheduler as recovery_scheduler

    import habit

    for _student in _db.query(Student).all():
        recovery_scheduler.DEFAULT_SCHEDULER.enqueue(_db, _student.id, limit=20)
        habit.DEFAULT_ENGINE.generate_daily_tasks(_db, _student.id)
except Exception:
    _db.rollback()
_db.close()

# 家庭自用阶段先只做数学；语文/英语的知识点库属于 V1.6 范围
DEFAULT_KNOWLEDGE = {
    "数学": "20以内加减法",
    "语文": "拼音与组词",
    "英语": "26个字母",
}

# V2.6：能力分相对「这次练的知识点固有难度」允许的最大上浮。
# 没有这条时，孩子反复练简单的 20 以内加减法也能把能力分一路顶到 100，
# 出题难度与能力评价跟着虚高成「六年级」。
ABILITY_CEILING_MARGIN = 15


class SubmitIn(BaseModel):
    question_id: int
    answer: str
    student_id: int = 1
    confidence: str = ""          # V2.7 自信度：sure / maybe / guess / unknown / ""
    hint_level: int = 0           # V2.7 Recall Hint Ladder 提示层级 0~4
    response_time: float = 0.0    # V2.7 作答耗时（秒），只用于猜测检测，不作为效率指标
    task_id: int = 0              # V2.8 题单模式：这次作答属于哪一项今日任务（0=不指定，按科目+知识点匹配）


def _grade_text(grade):
    if isinstance(grade, int):
        return f"{grade}年级"
    return str(grade or "一年级")


def _get_or_create_student(db: Session, student_id: int) -> Student:
    student = db.query(Student).filter(Student.id == student_id).first()

    if student is None:
        student = Student(id=student_id, name=f"小朋友{student_id}", grade=1)
        db.add(student)
        db.flush()

    return student


def _get_or_create_ability(db: Session, student_id: int, subject: str) -> Ability:
    ability = db.query(Ability).filter(
        Ability.student_id == student_id,
        Ability.subject == subject,
    ).first()

    if ability is None:
        ability = Ability(student_id=student_id, subject=subject)
        db.add(ability)
        db.flush()

    return ability


def _dumps(value):
    return json.dumps(value, ensure_ascii=False)


def _get_or_create_review(db: Session, student_id: int, subject: str, knowledge: str) -> Review:
    """取这个学生的知识点复习计划；第一次碰到就立刻建立，并标记为"现在就该练"。"""
    row = db.query(Review).filter(
        Review.student_id == student_id,
        Review.subject == subject,
        Review.knowledge == knowledge,
    ).first()

    if row is None:
        row = Review(
            student_id=student_id,
            subject=subject,
            knowledge=knowledge,
            stage=0,
            interval=srs.INTERVALS[0],
            streak=0,
            review_count=0,
            correct_count=0,
            next_review_at=srs.to_dt(srs.now_ts()),
        )
        db.add(row)
        db.flush()

    return row


def recent_question_stems(db, student_id, subject, knowledge="", limit=6):
    """这个学生最近做过的题干（优先同知识点），供出题防雷同。

    出题前把最近原题传给 AI，prompt 里明确要求换数字 / 换情境；
    模型偶尔还是会吐旧题，所以 deepseek.generate_question 还会本地复核。
    """
    limit = max(1, int(limit))

    def _stems(query):
        rows = query.order_by(Question.id.desc()).limit(limit).all()
        return [row.question for row in rows if row.question]

    if knowledge:
        same = _stems(
            db.query(Question).join(AnswerRecord, AnswerRecord.question_id == Question.id)
            .filter(AnswerRecord.student_id == student_id,
                    AnswerRecord.subject == subject,
                    AnswerRecord.knowledge == knowledge))
        if same:
            return same

    return _stems(
        db.query(Question).join(AnswerRecord, AnswerRecord.question_id == Question.id)
        .filter(AnswerRecord.student_id == student_id,
                AnswerRecord.subject == subject))


def _row_state(row: Review):
    """把复习记录转成调度用的 dict（时间戳单位统一为秒）。"""
    state = srs.state_from_row(row)

    return dict(
        state,
        subject=row.subject,
        knowledge=row.knowledge,
        review_count=row.review_count or 0,
        correct_count=row.correct_count or 0,
    )


@app.get("/")
def home():
    return {
        "version": APP_VERSION,
        "features": [
            "本地双用户",
            "语数英能力模型",
            "自适应学习",
            "艾宾浩斯复习计划",
            "题目语音朗读",
            "能力诊断引擎（72 个能力阶段）",
            "学生能力画像与知识点掌握度",
            "知识点体系与掌握模型（MasteryEngine）",
            "错因分析与错题本（NEW/LEARNING/MASTERED）",
            "AI 题目质量审核（QuestionValidator）",
            "自适应学习引擎（LearningStrategy 学习策略 + DifficultyController 难度控制）",
            "每日学习计划与下一题推荐（DailyLearningPlanner / QuestionSelector）",
            "间隔复习系统（MemoryState 记忆状态 + ForgettingRiskEngine 遗忘风险 + ReviewScheduler）",
            "复习题变式生成（ReviewQuestionSelector：不重复历史原题）",
            "训练数据自动能力诊断（AutoAbility：由每日训练与自由练习成绩推断能力阶段，无需专门诊断）",
            "菲比 AI 陪伴（PhoebeChat：点击立牌即读学习数据，由 DeepSeek 生成一句给孩子听的话）",
            "错题康复系统（RecoveryEngine：NEW→ANALYZING→LEARNING→PRACTICING→VERIFYING→MASTERED，四级提示 + 变式题过审）",
            "每日学习习惯与任务（HabitEngine：50/30/20 新学 / 薄弱 / 复习三类任务，连续天数 + 徽章 + 等级）",
            "儿童端信息架构（🏠 今天 / 🗺 成长 / ⚔️ 挑战 / 👤 我的，最多四个一级入口）",
            "首页聚合接口（/api/home/{student_id}：今日计划 + 今日进度 + 复习 + 挑战 + 成长亮点 + 菲比问候）",
            "统一 LearningSession（微任务连续学习：开始今天的学习 → 逐个任务 → 今日完成）",
            "知识地图（/api/knowledge-map/{student_id}：真实掌握度与记忆状态 → 🌱🌿🌳⭐ 区域成长）",
            "成长中心（/api/growth/{student_id}：本周学习天数 / 新掌握 / 长期记住 / 攻克挑战 / 成长时间线）",
            "挑战中心（/api/challenge/{student_id}：V2.5 错题康复的儿童化三色视图 🔴🟡🟢）",
            "分龄 UI（JUNIOR / MIDDLE / SENIOR）与儿童端 Design Tokens",
            "健康学习结束机制（每日任务完成 → 今日完成页，不提供继续加练入口）",
            "Deep Mastery 深度学习模型（DeepMasteryEngine：识别→理解→应用→迁移→解释→长期记住 六级，与 mastery_score、memory_state 三层并列）",
            "统一学习证据（Learning Evidence：STANDARD / RECALL / TRANSFER / EXPLANATION / DELAYED_REVIEW / RECOVERY / PREREQUISITE_CHECK，权重各不相同）",
            "薄弱根因分析（RootCauseAnalyzer：概念缺口 / 前置缺口 / 计算错 / 读题错 / 关系建模错 / 步骤错 / 单位错 / 回忆失败 / 偶然失误）",
            "前置知识追踪与最小回补（PrerequisiteTracer / Minimal Repair：只补最小缺失能力，不重学整章）",
            "知识迁移与变式阶梯（TransferEngine / VariantLadder：T0~T5，升级 / 保持 / 回退，一轮最多 3 题）",
            "主动回忆 2.0（Recall Hint Ladder 0~4：无提示成功证据最强，越依赖提示证据越弱）",
            "自信度与猜测检测（Confidence Feedback：正确性 × 自信度，猜对只给弱证据并安排一题快速验证）",
            "疑似概念性误解检测（Misconception Detection：同类错误逻辑反复 + 高自信 → 先重讲概念再验证）",
            "讲给菲比听（ExplanationEngine：只判断概念对不对，不因表达不完整判错）",
            "学习效率（LearningEfficiencyEngine：看真实收益而不是做题速度，儿童端只说「今天 N 分钟学会了 M 个知识」）",
        ],
    }


@app.get("/students")
def students(db: Session = Depends(get_db)):
    return [
        {
            "id": student.id,
            "name": student.name,
            "avatar": student.avatar,
            "grade": student.grade,
            "grade_text": _grade_text(student.grade),
        }
        for student in db.query(Student).all()
    ]


@app.get("/question")
def question(
    student_id: int = 1,
    subject: str = "数学",
    knowledge: str = "",
    qtype: str = CHOICE,
    difficulty: int = 0,
    db: Session = Depends(get_db),
):
    # V2.3 自适应学习引擎允许外部（/api/learning/next-question）指定难度，
    # 传 0 表示"没指定"，仍按下面的原有规则自己算
    forced_difficulty = max(0, min(100, int(difficulty or 0)))

    student = _get_or_create_student(db, student_id)
    ability = _get_or_create_ability(db, student_id, subject)

    requested = (knowledge or "").strip()

    # 复习优先：先把这次要练的知识点确定下来，再决定出什么题
    requested_knowledge = requested or DEFAULT_KNOWLEDGE.get(subject, "基础练习")
    review_row = _get_or_create_review(db, student_id, subject, requested_knowledge)

    states = [_row_state(review_row)]
    states += [
        _row_state(other)
        for other in db.query(Review).filter(
            Review.student_id == student_id,
            Review.subject == subject,
            Review.id != review_row.id,
        ).all()
    ]

    due = srs.due_items(states)
    picked = srs.select_knowledge(states, due, requested)
    knowledge = picked["knowledge"] or DEFAULT_KNOWLEDGE.get(subject, "基础练习")
    is_review = picked["is_review"]

    if knowledge != requested_knowledge:
        review_row = _get_or_create_review(db, student_id, subject, knowledge)

    review_state = srs.state_from_row(review_row)

    # 复习面板：只列"做过且到期"的知识点，提醒还有哪些要巩固
    pending = [item for item in srs.due_items(states, practiced_only=True) if item["knowledge"] != knowledge]

    # 出题难度：有诊断画像时围绕"下一个能力阶段"出题（比当前能力略高一点）；
    # 还没做过诊断时沿用原有逻辑（能力分即下一题的难度）
    profile = db.query(AbilityProfile).filter(
        AbilityProfile.student_id == student_id,
        AbilityProfile.subject == subject,
    ).first()

    # V2.3：这个学生在这个知识点上最常犯的错，出题时针对性设计
    error_focus = error_analysis.dominant_error(
        db, student_id, knowledge=knowledge, subject=subject, top=1)
    focus_text = f"，重点针对「{error_focus[0]}」" if error_focus else ""

    ability_context = {
        "grade": _grade_text(student.grade),
        "student": student.name,
        "subject": subject,
        "knowledge": knowledge,
        "error_focus": error_focus[0] if error_focus else "",
    }
    profile_payload = None

    if profile is not None and stages.is_valid(profile.ability_stage):
        target = stages.next_key(profile.ability_stage)
        difficulty = int(round(
            0.5 * float(profile.ability_score or 50) + 0.5 * stages.difficulty_of(target)
        ))
        mastery_row = db.query(StudentKnowledgeMastery).filter(
            StudentKnowledgeMastery.student_id == student_id,
            StudentKnowledgeMastery.subject == subject,
            StudentKnowledgeMastery.knowledge_id == knowledge,
        ).first()

        ability_context.update({
            "stage": profile.ability_stage,
            "stage_label": stages.label(profile.ability_stage),
            "target_stage": target,
            "target_label": stages.label(target),
            "mastery": mastery_row.mastery_score if mastery_row else None,
            # V2.3 自适应：告诉模型这次要把掌握度提到多少（薄弱题的目标）
            "mastery_goal": (min(90, int(mastery_row.mastery_score or 0) + 10)
                             if mastery_row else 70),
            "goal": f"生成一道略高于当前能力（{target} 阶段）的训练题{focus_text}",
        })
        profile_payload = {
            "stage": profile.ability_stage,
            "stage_label": stages.label(profile.ability_stage),
            "target_stage": target,
            "target_label": stages.label(target),
            "score": profile.ability_score,
            "confidence": profile.confidence,
        }
    else:
        # V2.6：难度以「知识点固有难度」为主锚（与 adaptive.strategy.suggest_difficulty
        # 的 base 口径一致）：能力分再高，也不能把一年级知识点当成 100 难度的题出，
        # 否则题目难度分与真实内容脱钩，能力评价会被自己的难度分带着虚高
        knowledge_difficulty = knowledge_tree.difficulty_of(subject, knowledge)
        difficulty = int(round(
            0.5 * float(ability.score or 50) + 0.5 * float(knowledge_difficulty)))
        ability_context["goal"] = f"生成一道适合当前能力、略有挑战的训练题{focus_text}"

    # V2.3 自适应引擎指定了难度就采用它（DifficultyController 已经算好升降幅度）
    if forced_difficulty:
        difficulty = forced_difficulty
        ability_context["difficulty"] = difficulty
        ability_context["goal"] = (
            f"按自适应难度 {difficulty}/100 出题，略高于当前能力，"
            f"让孩子努力一下能做对{focus_text}")

    # 出题防雷同：把最近练过的原题带上，避免同一道经典题在一次练习里连出好几遍
    history = recent_question_stems(db, student_id, subject, knowledge)

    data = generate_question(
        subject,
        _grade_text(student.grade),
        knowledge,
        difficulty,
        qtype,
        ability=ability_context,
        history=history,
    )

    # V2.3：不论题目来自题库还是模型，保存前都要过一遍质量审核；
    # 不合格就重试一次，再不合格改用内置兜底题，绝不把错题发给小朋友
    report = validator.validate(data, subject=subject, knowledge=knowledge,
                                difficulty=difficulty)
    if not report["passed"]:
        retry = generate_question(subject, _grade_text(student.grade), knowledge,
                                  difficulty, qtype, ability=ability_context,
                                  history=history)
        retry_report = validator.validate(retry, subject=subject, knowledge=knowledge,
                                          difficulty=difficulty)
        if retry_report["passed"]:
            data, report = retry, retry_report
        else:
            fallback_type = data.get("qtype") or CHOICE
            data = dict(FALLBACK[fallback_type])
            data.update(qtype=fallback_type, source="fallback",
                        error="生成的题目未通过质量审核，已使用内置练习题")

    row = Question(
        subject=subject,
        grade=student.grade if isinstance(student.grade, int) else 1,
        knowledge=knowledge,
        difficulty=difficulty,
        question=data["question"],
        answer=data["answer"],
        qtype=data["qtype"],
        options=_dumps(data.get("options") or {}),
        acceptable=_dumps(data.get("acceptable") or []),
        analysis=data.get("analysis") or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # 答案与解析不下发，判分完全由服务端完成
    return {
        "question_id": row.id,
        "qtype": row.qtype,
        "subject": subject,
        "knowledge": knowledge,
        "difficulty": difficulty,
        "question": row.question,
        "options": data.get("options") or {},
        "stage": ability.stage,
        "source": data.get("source"),
        "repeated": bool(data.get("repeated")),   # 与最近原题雷同（防雷同重试后仍相似），前端可提示换题
        "error": data.get("error"),
        "is_review": is_review,
        "review": {
            "stage": review_state["stage"],
            "mastery": srs.mastery(review_state),
            "next_review_text": srs.format_interval(review_state["interval"]),
            "due": srs.is_due(review_state),
        },
        # 复习面板：列出其它"做过且到期"的知识点，提醒还有哪些要巩固
        "due_reviews": pending,
        "due_count": len(pending),
        # V2.0 诊断画像（没做过诊断时为 None，前端可以不显示）
        "ability": profile_payload,
        # V2.3 这道题的质量审核结果
        "audit": {
            "passed": report["passed"],
            "score": report["score"],
            "issues": [item["code"] for item in report["issues"]],
        },
    }


@app.post("/submit")
def submit(payload: SubmitIn, db: Session = Depends(get_db)):
    row = db.query(Question).filter(Question.id == payload.question_id).first()

    if row is None:
        raise HTTPException(status_code=404, detail="题目不存在，请重新生成题目")

    correct = is_correct(row, payload.answer)

    record = AnswerRecord(
        student_id=payload.student_id,
        subject=row.subject,
        knowledge=row.knowledge,
        difficulty=row.difficulty,
        correct=correct,
        question_id=row.id,
        submitted=payload.answer,
    )
    db.add(record)
    db.flush()          # 先拿到 record.id，错因分析要挂在它上面

    ability = _get_or_create_ability(db, payload.student_id, row.subject)
    ability.total_count += 1
    if correct:
        ability.correct_count += 1

    rate = ability.correct_count / max(1, ability.total_count)
    # stage 用于展示；能力分由 next_difficulty 递推，即下一题的难度
    ability.stage, _ = calculate_stage(ability.total_count, ability.correct_count, row.difficulty)
    # V2.6：能力分上限锚定「这次练的知识点固有难度 + 余量」，不再允许靠简单题的
    # 高正确率无限上抬（否则天天练 20 以内加减法也会显示成 100 分六年级）
    ceiling = knowledge_tree.difficulty_of(row.subject, row.knowledge) + ABILITY_CEILING_MARGIN
    ability.score = min(next_difficulty(rate, ability.score or 50),
                        max(1, min(stages.MAX_DIFFICULTY, ceiling)))

    # 艾宾浩斯：按这次对错推进该知识点的复习计划
    review_row = _get_or_create_review(db, payload.student_id, row.subject, row.knowledge)
    state = srs.review(srs.state_from_row(review_row), correct)
    srs.apply_state(review_row, state)
    review_row.review_count += 1
    if correct:
        review_row.correct_count += 1

    # V2.3：答错先分析"为什么错"，答对则推进这个知识点的错题状态
    error_info = None
    if correct:
        wrong_book.record_correct(db, payload.student_id, row)
    else:
        error_info = error_analysis.analyze(
            db, payload.student_id, row, payload.answer,
            answer_record_id=record.id, use_ai=False,
        )
        wrong_book.record_wrong(db, payload.student_id, row, error_info["error_type"])

    # V2.3：掌握度按这个知识点的全部历史记录重算
    #（连续错误降档、多次复习加成、久不练习衰减都会生效）
    mastery_row = update_mastery(
        db,
        payload.student_id,
        row.subject,
        row.knowledge,
        stage=stages.key_of_difficulty(row.difficulty),
    )

    db.commit()

    # V2.4：把这次学习同步进记忆状态（第一次真正学会 → 1 天后第一次复习）。
    # 单独一步、单独提交：复习系统出问题也不影响判分主流程。
    memory_summary = None
    try:
        import review.engine as review_engine_module

        review_engine_module.DEFAULT_ENGINE.record_learning(
            db, payload.student_id, row.subject, row.knowledge,
            mastery_score=mastery_row.mastery_score if mastery_row else None,
            confidence=mastery_row.confidence if mastery_row else 0,
            correct=correct, when=datetime.now())
        db.commit()
        memory_summary = review_engine_module.DEFAULT_ENGINE.state_summary(
            db, payload.student_id, row.subject, row.knowledge)
    except Exception:
        db.rollback()

    # V2.5：这次练习同步进错题康复队列（答错入队 / 答对推进状态）。
    # 与记忆状态一样单独 try/except + 独立提交，康复系统出问题绝不影响判分返回。
    try:
        import recovery.engine as recovery_engine_module

        recovery_engine_module.DEFAULT_ENGINE.sync_from_wrong_book(
            db, payload.student_id, row, correct)
        db.commit()
    except Exception:
        db.rollback()

    # V2.5：把这次作答算进当天的每日任务（题单模式按 task_id 精确记账，
    # 否则同科目同知识点的未完成任务优先）
    try:
        import habit

        habit.DEFAULT_ENGINE.record_answer(
            db, payload.student_id, subject=row.subject, knowledge=row.knowledge,
            correct=correct, task_id=payload.task_id)
    except Exception:
        db.rollback()

    # V2.8：这次作答给自己挣积分（答对 +2；当天第一次答对顺便把「每日打卡」记上；
    # 当天任务全部收工后还继续练，额外给「计划做完后继续练」分）。
    # 与记忆状态 / 康复队列 / 每日任务一样独立 try/except + 独立提交：积分出问题绝不影响判分返回。
    try:
        import points

        points.award_after_answer(
            db, payload.student_id, correct=correct,
            subject=row.subject, knowledge=row.knowledge)
    except Exception:
        db.rollback()
    # V2.7：这次作答统一落成 Learning Evidence，并据此更新 Deep Mastery（需求 §六 / §二十六）。
    # 与记忆状态、康复队列一样独立 try/except + 独立提交：深度学习出问题绝不影响判分返回。
    deep_summary = None
    confidence_summary = None
    try:
        import deep_learning.engine as deep_engine_module

        deep = deep_engine_module.DEFAULT_ENGINE
        confidence_summary = deep.confidence_plan(
            correct=correct,
            confidence_key=str(payload.confidence or "").strip().lower(),
            mastery_score=(mastery_row.mastery_score if mastery_row else 0),
            response_time=payload.response_time,
        )
        deep.record_evidence(
            db, payload.student_id, row.subject, row.knowledge,
            evidence_type="STANDARD", result="correct" if correct else "wrong",
            question_id=row.id, difficulty=row.difficulty or 50,
            hint_level=payload.hint_level, confidence=payload.confidence,
            response_time=payload.response_time, source="submit",
            detail=str((error_info or {}).get("error_type", "")), commit=False,
        )
        if not correct:
            deep.analyze_root_cause(
                db, payload.student_id, row.subject, row.knowledge,
                question=row.question or "", student_answer=payload.answer,
                correct_answer=row.answer or "",
                error_type=str((error_info or {}).get("error_type", "")),
                response_time=payload.response_time, hint_usage=payload.hint_level,
                confidence=payload.confidence, answer_record_id=record.id,
                question_id=row.id, use_ai=False, commit=False,
            )
        db.commit()
        deep_summary = deep.detail(db, payload.student_id, row.subject, row.knowledge)
    except Exception:
        db.rollback()

    correct_text = ""
    if row.options:
        try:
            correct_text = (json.loads(row.options) or {}).get((row.answer or "").upper(), "")
        except ValueError:
            correct_text = ""

    return {
        "correct": correct,
        "correct_answer": row.answer,
        "correct_text": correct_text,
        "analysis": row.analysis or "",
        "qtype": row.qtype,
        "stage": ability.stage,
        "score": ability.score,
        "total_count": ability.total_count,
        "correct_count": ability.correct_count,
        "knowledge": row.knowledge,
        "review": {
            "stage": state["stage"],
            "interval": state["interval"],
            "interval_text": srs.format_interval(state["interval"]),
            "next_review_at": review_row.next_review_at.strftime("%Y-%m-%d %H:%M"),
            "mastery": srs.mastery(state),
            "mastered": state["mastered"],
            "message": state["message"],
            "review_count": review_row.review_count,
        },
        # V2.3 错因分析（答对时为 null）
        "error_analysis": error_info,
        # V2.3 这个知识点的掌握度（答完立刻更新）
        "mastery": {
            "knowledge": row.knowledge,
            "mastery_score": mastery_row.mastery_score if mastery_row else None,
            "confidence": mastery_row.confidence if mastery_row else None,
            "level": (mastery.DEFAULT_ENGINE.level_of(mastery_row.mastery_score)
                      if mastery_row else None),
            "total_questions": mastery_row.total_questions if mastery_row else 0,
            "correct_questions": mastery_row.correct_questions if mastery_row else 0,
            "wrong_questions": mastery_row.wrong_questions if mastery_row else 0,
            "next_review_time": (mastery_row.next_review_time.strftime("%Y-%m-%d %H:%M")
                                 if mastery_row and mastery_row.next_review_time else ""),
        },
        # V2.3 错题本概览（未掌握 / 巩固中 / 已攻克）
        "wrong_book": wrong_book.stats_for(db, payload.student_id, subject=row.subject),
        # V2.4 这个知识点的记忆状态（记忆强度 / 稳定性 / 下次复习 / 成熟度）
        "memory": memory_summary,
        # V2.7 深度掌握（识别→理解→应用→迁移→解释→长期记住）与本次自信度判断
        "deep_mastery": deep_summary,
        "confidence": confidence_summary,
    }


@app.get("/reviews")
def reviews(
    student_id: int = 1,
    subject: str = "",
    db: Session = Depends(get_db),
):
    """复习计划总览：哪些知识点今天该复习、掌握到什么程度。"""
    query = db.query(Review).filter(Review.student_id == student_id)
    if subject:
        query = query.filter(Review.subject == subject)

    rows = query.order_by(Review.next_review_at.asc()).all()

    now = srs.now_ts()
    items = []
    for row in rows:
        state = srs.state_from_row(row)
        items.append({
            "subject": row.subject,
            "knowledge": row.knowledge,
            "stage": state["stage"],
            "mastered": state["mastered"],
            "due": srs.is_due(state, now),
            "mastery": srs.mastery(state),
            "interval_text": srs.format_interval(state["interval"]),
            "next_review_at": row.next_review_at.strftime("%Y-%m-%d %H:%M") if row.next_review_at else "",
            "review_count": row.review_count or 0,
            "correct_count": row.correct_count or 0,
            "last_result": row.last_result,
        })

    return {
        "student_id": student_id,
        "due_count": sum(1 for item in items if item["due"]),
        "mastered_count": sum(1 for item in items if item["mastered"]),
        "total": len(items),
        "items": items,
    }


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
