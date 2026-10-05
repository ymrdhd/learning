# ==============================================================
# 能力契约｜22 张表的 SQLAlchemy 模型定义（schema 唯一真相）
# 入口：Base + 22 个模型类（Student/Ability/AnswerRecord/Review/Question/...）
# V2.5 新增：WrongQuestionRecovery / DailyLearningTask / LearningHabitProfile（文件末尾）
# 依赖：sqlalchemy
# 不负责：建表与迁移逻辑 → database.py；业务读写 → 各业务模块
# 验证：python backend/verify_all.py（建表断言分散在各套件）
# 被调用：全部业务模块与验证脚本
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True)
    name = Column(String, default="小朋友")
    avatar = Column(String, default="boy")
    grade = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)


class Ability(Base):
    __tablename__ = "abilities"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    stage = Column(Float, default=1.0)
    score = Column(Float, default=50)
    correct_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)


class AnswerRecord(Base):
    __tablename__ = "answer_records"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge = Column(String)
    difficulty = Column(Integer)
    correct = Column(Boolean)
    question_id = Column(Integer)
    submitted = Column(String)
    created_at = Column(DateTime, default=datetime.now)


class Review(Base):
    """艾宾浩斯复习计划：一个学生 + 一个知识点一行。"""

    __tablename__ = "reviews"
    __table_args__ = (Index("ix_reviews_student_due", "student_id", "next_review_at"),)

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge = Column(String)
    stage = Column(Integer, default=0)          # 当前复习阶段，等于 len(srs.INTERVALS) 即已掌握
    interval = Column(Integer, default=300)     # 当前复习间隔（秒），与 stage 对应的阶梯值
    streak = Column(Integer, default=0)         # 当前阶段内连续答对次数
    review_count = Column(Integer, default=0)   # 累计作答次数
    correct_count = Column(Integer, default=0)
    last_result = Column(Boolean)
    next_review_at = Column(DateTime)           # 下次复习时间
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    subject = Column(String)
    grade = Column(Integer)
    knowledge = Column(String)
    difficulty = Column(Integer)
    question = Column(String)
    answer = Column(String)
    qtype = Column(String, default="choice")
    options = Column(Text)
    acceptable = Column(Text)
    analysis = Column(Text)


class DiagnosticSession(Base):
    """一场能力诊断（V2.0）。

    state 列存 JSON：当前阶段第几题、每个阶段的正确率、边界候选等运行时状态，
    避免为每种中间状态都加一列；下面这些列是查询/展示用的关键字段。
    """

    __tablename__ = "diagnostic_sessions"
    __table_args__ = (Index("ix_diag_sessions_student", "student_id", "subject", "status"),)

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    start_time = Column(DateTime, default=datetime.now)
    end_time = Column(DateTime)
    current_stage = Column(String, default="1.1")     # 当前正在测的能力阶段
    final_stage = Column(String)                      # 诊断出的最终能力阶段
    final_score = Column(Float)                       # 最终能力分
    confidence = Column(Float, default=0)             # 置信度
    status = Column(String, default="in_progress")    # in_progress / finished
    total_count = Column(Integer, default=0)
    correct_count = Column(Integer, default=0)
    state = Column(Text)                              # JSON 运行时状态
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DiagnosticRecord(Base):
    """诊断过程中的每一道题（V2.0）。"""

    __tablename__ = "diagnostic_records"
    __table_args__ = (Index("ix_diag_records_session", "session_id"),)

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer)
    student_id = Column(Integer)
    subject = Column(String)
    stage = Column(String)                 # 这道题属于哪个能力阶段
    knowledge_point = Column(String)
    difficulty = Column(Integer)
    correct = Column(Boolean)
    answer_time = Column(DateTime, default=datetime.now)
    question_id = Column(Integer)
    submitted = Column(String)


class AbilityProfile(Base):
    """学生能力画像：一个学生 + 一个科目一行（V2.0）。"""

    __tablename__ = "ability_profile"
    __table_args__ = (Index("ix_ability_profile_student", "student_id", "subject", unique=True),)

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    ability_stage = Column(String, default="1.1")
    ability_score = Column(Float, default=0)
    confidence = Column(Float, default=0)
    lower_stage = Column(String)           # 能力区间下沿
    upper_stage = Column(String)           # 能力区间上沿
    questions = Column(Integer, default=0)
    correct = Column(Integer, default=0)
    source = Column(String, default="diagnostic")   # diagnostic / practice
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class StudentKnowledgeMastery(Base):
    """知识点掌握度：一个学生 + 一个科目 + 一个知识点一行。

    V2.2 只有正确率（questions/correct），V2.3 扩展成真正的掌握模型：
    置信度、错题数、最近练习时间、下次复习时间（旧列保留，启动时自动回填）。
    """

    __tablename__ = "student_knowledge_mastery"
    __table_args__ = (
        Index("ix_mastery_student", "student_id", "subject", "knowledge_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)          # 知识点名称
    knowledge_point_id = Column(Integer)   # 对应的 knowledge_points.id（V2.3）
    grade = Column(Integer, default=1)     # 知识点所在年级（V2.3）
    stage = Column(String)                 # 主要命中的能力阶段
    mastery_score = Column(Integer, default=0)
    confidence = Column(Float, default=0)          # V2.3 掌握度置信度
    total_questions = Column(Integer, default=0)   # V2.3 累计题量
    correct_questions = Column(Integer, default=0)  # V2.3 答对数
    wrong_questions = Column(Integer, default=0)   # V2.3 答错数
    consecutive_wrong = Column(Integer, default=0)  # V2.3 最近连续错几道
    questions = Column(Integer, default=0)         # V2.2 旧列（启动时回填到 total_questions）
    correct = Column(Integer, default=0)           # V2.2 旧列
    difficulty_sum = Column(Float, default=0)
    last_practice_time = Column(DateTime)          # V2.3
    next_review_time = Column(DateTime)            # V2.3
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class KnowledgePoint(Base):
    """知识点体系（V2.3）：科目 → 章节领域 → 知识点 → 子知识点，用 parent_id 串成树。"""

    __tablename__ = "knowledge_points"
    __table_args__ = (
        Index("ix_knowledge_points_name", "subject", "knowledge_name", unique=True),
        Index("ix_knowledge_points_parent", "parent_id"),
    )

    id = Column(Integer, primary_key=True)
    subject = Column(String)
    grade = Column(Integer, default=1)
    semester = Column(String, default="上册")     # 上册 / 下册 / 全册
    chapter = Column(String)                     # 章节领域，如「计算」
    knowledge_name = Column(String)
    parent_id = Column(Integer)                  # 父知识点 id（自关联成树）
    difficulty = Column(Integer, default=50)
    path = Column(String)                        # 完整路径：数学 / 计算 / 表内乘法
    is_leaf = Column(Boolean, default=True)
    created_time = Column(DateTime, default=datetime.now)


class AnswerErrorAnalysis(Base):
    """错因分析（V2.3）：每次答错记录错误类型、原因与下一步建议。"""

    __tablename__ = "answer_error_analysis"
    __table_args__ = (
        Index("ix_error_analysis_student", "student_id", "subject"),
        Index("ix_error_analysis_question", "question_id"),
    )

    id = Column(Integer, primary_key=True)
    answer_record_id = Column(Integer)     # 对应 answer_records.id（诊断题没有常规记录，可为空）
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)
    question_id = Column(Integer)
    error_type = Column(String)            # 概念错误 / 计算错误 / 审题错误 ...
    analysis = Column(Text)                # 错误原因
    suggestion = Column(Text)              # 下一步建议（V2.3 扩展）
    source = Column(String, default="rule")  # rule / ai
    created_time = Column(DateTime, default=datetime.now)


class LearningPlan(Base):
    """每日学习计划（V2.3 自适应引擎）：一个学生 + 一天 + 一科 + 一个知识点一行。

    由 DailyLearningPlanner 生成，孩子每答一题 completed_count +1；
    completed_count 达到 target_count 即 status = done。
    """

    __tablename__ = "learning_plan"
    __table_args__ = (
        Index("ix_learning_plan_student_date", "student_id", "date"),
        Index("ix_learning_plan_unique", "student_id", "date", "subject", "knowledge_id",
              unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    date = Column(String)                      # YYYY-MM-DD
    subject = Column(String)
    knowledge_id = Column(String)
    target_count = Column(Integer, default=0)  # 今天要做几题
    completed_count = Column(Integer, default=0)
    status = Column(String, default="pending")  # pending / doing / done / expired
    duration_minutes = Column(Integer, default=0)
    action = Column(String, default="practice")  # practice / review / challenge
    item_type = Column(String, default="new_learning")  # V2.4 new_learning / weakness / review
    difficulty = Column(Integer, default=50)
    goal = Column(String)                      # 给小朋友看的目标文案
    reason = Column(String)                    # 为什么安排这个
    target_mastery = Column(Integer, default=70)
    priority = Column(Integer, default=1)
    created_time = Column(DateTime, default=datetime.now)
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class LearningStrategyLog(Base):
    """学习策略日志（V2.3 自适应引擎）：记录"为什么推荐这个学习"。"""

    __tablename__ = "learning_strategy_log"
    __table_args__ = (Index("ix_strategy_log_student", "student_id", "created_time"),)

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    action = Column(String)                    # practice / review / challenge / diagnostic
    reason = Column(Text)
    subject = Column(String)
    knowledge_id = Column(String)
    difficulty = Column(Integer)
    mode = Column(String)
    priority_score = Column(Float, default=0)
    source = Column(String, default="recommend")  # recommend / start / next_question / plan
    created_time = Column(DateTime, default=datetime.now)


class LearningFeedback(Base):
    """学习反馈（V2.3 自适应引擎）：孩子对每道题的主观感受，用来优化难度模型。"""

    __tablename__ = "learning_feedback"
    __table_args__ = (Index("ix_learning_feedback_student", "student_id", "created_time"),)

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)
    question_id = Column(Integer)
    difficulty = Column(Integer)
    correct = Column(Boolean)
    feel = Column(String)                      # easy / normal / hard / lost
    need_help = Column(Boolean, default=False)
    note = Column(Text)
    created_time = Column(DateTime, default=datetime.now)


class WrongQuestion(Base):
    """错题本（V2.3）：NEW 未掌握 → LEARNING 巩固中 → MASTERED 已攻克。"""

    __tablename__ = "wrong_questions"
    __table_args__ = (
        Index("ix_wrong_questions_student", "student_id", "status"),
        Index("ix_wrong_questions_unique", "student_id", "question_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)
    question_id = Column(Integer)
    stage = Column(String)                 # 错题所属能力阶段
    status = Column(String, default="NEW")
    wrong_count = Column(Integer, default=1)
    correct_streak = Column(Integer, default=0)
    last_error_type = Column(String)
    first_wrong_time = Column(DateTime)
    last_wrong_time = Column(DateTime)
    next_review_time = Column(DateTime)
    created_time = Column(DateTime, default=datetime.now)
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class KnowledgeMemoryState(Base):
    """V2.4 记忆状态：一个学生 + 一个科目 + 一个知识点一行。

    掌握度回答"会不会"，记忆状态回答"还记不记得、能撑多久"：

    | 字段 | 含义 |
    | --- | --- |
    | mastery_score | 0~100 知识理解与掌握（沿用 MasteryEngine 的结果） |
    | memory_strength | 0~100 当前记忆强度（掌握 + 稳定性 × 当前保持度） |
    | stability | 记忆稳定性（天）：越大越耐忘，允许更长间隔 |
    | difficulty | 0~1 这个学生在这个知识点上的**个人难度**（不是知识点固定难度） |
    | current_interval_days | 当前复习间隔（天） |
    | forgetting_risk | 0~1 遗忘风险 |
    | maturity_level | NEW / LEARNING / SHORT_TERM / CONSOLIDATING / STABLE / LONG_TERM |
    | needs_relearn | mastery < 60 时为 True：不该做纯复习，交给自适应引擎重新学 |
    """

    __tablename__ = "knowledge_memory_state"
    __table_args__ = (
        Index("ix_memory_state_student", "student_id", "subject", "knowledge_id", unique=True),
        Index("ix_memory_state_due", "student_id", "next_review_at"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)
    mastery_score = Column(Integer, default=0)
    memory_strength = Column(Integer, default=0)
    stability = Column(Float, default=1.0)            # 记忆稳定性（天）
    difficulty = Column(Float, default=0.5)           # 个人难度 0~1
    review_count = Column(Integer, default=0)
    successful_reviews = Column(Integer, default=0)
    failed_reviews = Column(Integer, default=0)
    confidence = Column(Float, default=0)             # 掌握度置信度（题量）
    last_learned_at = Column(DateTime)
    last_reviewed_at = Column(DateTime)
    next_review_at = Column(DateTime)
    current_interval_days = Column(Float, default=1.0)
    forgetting_risk = Column(Float, default=0.0)
    maturity_level = Column(String, default="NEW")
    needs_relearn = Column(Boolean, default=False)
    consecutive_failures = Column(Integer, default=0)  # 连续复习失败次数（判定遗忘）
    review_streak = Column(Integer, default=0)         # 连续复习成功次数
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ReviewRecord(Base):
    """V2.4 每次复习的明细：一次复习就是一条记录（算法可复盘）。"""

    __tablename__ = "review_records"
    __table_args__ = (
        Index("ix_review_records_student", "student_id", "subject", "knowledge_id"),
        Index("ix_review_records_time", "student_id", "reviewed_at"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)
    question_id = Column(Integer)
    reviewed_at = Column(DateTime, default=datetime.now)
    correct = Column(Boolean, default=False)
    review_quality = Column(String, default="GOOD")     # AGAIN / HARD / GOOD / EASY
    response_time = Column(Float, default=0.0)          # 作答耗时（秒）
    expected_time = Column(Float, default=0.0)          # 该题型的期望耗时（秒）
    previous_interval = Column(Float, default=1.0)
    next_interval = Column(Float, default=1.0)
    previous_stability = Column(Float, default=1.0)
    new_stability = Column(Float, default=1.0)
    memory_strength = Column(Integer, default=0)
    forgetting_risk = Column(Float, default=0.0)
    maturity_level = Column(String)
    reason = Column(Text)
    created_time = Column(DateTime, default=datetime.now)


class ReviewQueue(Base):
    """V2.4 每日复习队列：一天一批任务，状态 PENDING → IN_PROGRESS → COMPLETED/SKIPPED。"""

    __tablename__ = "review_queue"
    __table_args__ = (
        Index("ix_review_queue_student", "student_id", "scheduled_at"),
        Index("ix_review_queue_unique", "student_id", "scheduled_at", "subject", "knowledge_id",
              unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)
    scheduled_at = Column(DateTime, default=datetime.now)   # 计划复习日期（当天 0 点起算）
    priority = Column(String, default="P0")                 # P0 / P1 / P2 / P3
    risk = Column(Float, default=0.0)                       # 入队时的遗忘风险
    target_count = Column(Integer, default=1)               # 这次复习出几题（1~3）
    completed_count = Column(Integer, default=0)
    status = Column(String, default="PENDING")
    reason = Column(Text)
    created_time = Column(DateTime, default=datetime.now)
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ReviewStrategyLog(Base):
    """V2.4 复习策略日志：每次改变复习日期都记录原因，方便调算法。"""

    __tablename__ = "review_strategy_log"
    __table_args__ = (Index("ix_review_strategy_log_student", "student_id", "created_time"),)

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    subject = Column(String)
    knowledge_id = Column(String)
    old_interval = Column(Float, default=0.0)
    new_interval = Column(Float, default=0.0)
    old_stability = Column(Float, default=0.0)
    new_stability = Column(Float, default=0.0)
    old_maturity = Column(String)
    new_maturity = Column(String)
    quality = Column(String)
    reason = Column(Text)
    source = Column(String, default="review")   # learn / review / migrate / queue
    created_time = Column(DateTime, default=datetime.now)


class WrongQuestionRecovery(Base):
    """V2.5 错题康复：一道错题在康复队列里的一行（状态机 NEW→…→MASTERED）。

    `state` 是康复状态，与 `wrong_questions.stage`（能力阶段）互不影响。
    """

    __tablename__ = "wrong_question_recovery"
    __table_args__ = (
        Index("ix_recovery_student_state", "student_id", "state"),
        Index("ix_recovery_unique", "student_id", "question_id", unique=True),
        Index("ix_recovery_verify_due", "student_id", "next_verify_time"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                    # 隔离键
    subject = Column(String)
    knowledge_id = Column(String)                   # 知识点名称
    question_id = Column(Integer)                   # 原错题 questions.id
    wrong_question_id = Column(Integer, default=0)  # 对应 wrong_questions.id（无则 0）
    state = Column(String, default="NEW")           # NEW/ANALYZING/LEARNING/PRACTICING/VERIFYING/MASTERED
    state_before = Column(String, default="")       # 上一次状态（审计）
    attempts = Column(Integer, default=0)
    correct_count = Column(Integer, default=0)
    consecutive_correct = Column(Integer, default=0)  # 连对计数（晋级用的就是它）
    fail_count = Column(Integer, default=0)
    max_level_used = Column(Integer, default=0)     # 已用到的最高提示层级 0~4
    variant_count = Column(Integer, default=0)
    last_state_change = Column(DateTime)
    next_verify_time = Column(DateTime)             # VERIFYING 到期时间
    mastered_time = Column(DateTime)
    source = Column(String, default="wrong_book")   # wrong_book / manual
    created_time = Column(DateTime, default=datetime.now)
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DailyLearningTask(Base):
    """V2.5 每日学习任务：一个学生 + 一天 + 一类任务一行（50/30/20 三类）。"""

    __tablename__ = "daily_learning_task"
    __table_args__ = (
        Index("ix_daily_task_student_date", "student_id", "date"),
        Index("ix_daily_task_unique", "student_id", "date", "task_type", "subject",
              "knowledge_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                      # 隔离键
    date = Column(String)                             # YYYY-MM-DD
    task_type = Column(String, default="new_learning")  # new_learning / weakness / review
    title = Column(String)                            # 儿童文案标题
    subject = Column(String)
    knowledge_id = Column(String)
    target_count = Column(Integer, default=0)
    complete_count = Column(Integer, default=0)
    duration_minutes = Column(Integer, default=0)     # 该任务累计学习时长（分钟）
    target_minutes = Column(Integer, default=0)
    status = Column(String, default="pending")        # pending / doing / done
    priority = Column(Integer, default=1)             # 数字越小越先做
    source = Column(String, default="plan")           # plan / review_queue / habit
    plan_id = Column(Integer, default=0)
    knowledge_ids = Column(Text, default="[]")        # JSON 数组
    goal = Column(String, default="")
    reason = Column(String, default="")
    completed_time = Column(DateTime)
    created_time = Column(DateTime, default=datetime.now)
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class LearningHabitProfile(Base):
    """V2.5 学习习惯画像：一个学生一行（连续天数 / 完成率 / 时长 / 徽章 / 等级）。"""

    __tablename__ = "learning_habit_profile"
    __table_args__ = (
        Index("ix_habit_profile_student", "student_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                    # 隔离键，一个学生一行
    current_streak = Column(Integer, default=0)     # 当前连续学习天数
    longest_streak = Column(Integer, default=0)
    total_days = Column(Integer, default=0)
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    total_minutes = Column(Integer, default=0)
    today_minutes = Column(Integer, default=0)      # 跨天自动归零重算
    completion_rate = Column(Float, default=0.0)    # 完成数 / 任务数
    last_active_date = Column(String, default="")   # YYYY-MM-DD
    badges = Column(Text, default="[]")             # JSON 数组
    level = Column(Integer, default=1)
    created_time = Column(DateTime, default=datetime.now)
    updated_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    rest_protection_month = Column(String, default="")   # 休息保护：使用月份 YYYY-MM
    rest_protection_count = Column(Integer, default=0)   # 该月已用次数（每月上限 2）
    # V2.6 目标时长自适应：10 分钟起步，签到 +2~5、断签 −5~8，恒在 10~40 分钟
    target_minutes = Column(Integer, default=10)         # 当前每日学习目标时长（分钟）
    target_synced_date = Column(String, default="")      # 目标时长上次结算日期（YYYY-MM-DD，幂等用）


class ActiveRecallRecord(Base):
    """V2.5 主动回忆记录：一次闪卡式回忆检测（学生主动输入 → 判分 → 记忆增益）。"""

    __tablename__ = "active_recall_record"
    __table_args__ = (
        Index("ix_recall_student_created", "student_id", "created_at"),
        Index("ix_recall_student_knowledge", "student_id", "knowledge"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                    # 隔离键
    subject = Column(String)
    knowledge = Column(String)                      # 知识点名称（与知识点树一致）
    knowledge_id = Column(Integer)                  # 可空：knowledge_points.id
    card_id = Column(String)                        # 卡片键（内置卡片库）
    kind = Column(String)                           # word / phrase / poem / formula / concept / basic
    prompt = Column(Text)                           # 题面（回忆提示语）
    answer = Column(Text)                           # 学生主动输入
    expected = Column(Text)                         # 可接受答案（JSON 数组）
    result = Column(String)                         # correct / partial / wrong
    hint_level = Column(Integer, default=0)         # 0 = 完全独立回忆（未用提示）
    response_time = Column(Integer, default=0)      # 秒
    confidence_feedback = Column(String, default="")
    memory_gain = Column(Float, default=0.0)        # 本次记忆稳定性增益（天）
    created_at = Column(DateTime, default=datetime.now)


# ==============================================================
# V2.7 Deep Mastery 层：深度学习 / 学习证据 / 根因 / 迁移 / 解释
# 与 mastery_score（会不会做）、memory_state（还记不记得）并列的第三层，
# 回答「是不是真的理解、能不能迁移、能不能讲清楚、过段时间还记不记得」。
# 全部按 student_id 隔离；迁移幂等（create_all 建新表，不改旧表）。
# ==============================================================


class DeepMasteryState(Base):
    """V2.7 深度掌握状态：一个学生 + 一个科目 + 一个知识点一行。

    六个维度各自 0~100，``deep_mastery_score`` 是加权汇总（**儿童端禁止直接展示**）。
    升级必须同时满足分数门槛、证据数量与证据来源多样性，见
    ``deep_learning/deep_mastery.py`` 的 ``DeepMasteryModel.level_of``。
    """

    __tablename__ = "deep_mastery_state"
    __table_args__ = (
        Index("ix_deep_mastery_student", "student_id", "subject", "knowledge_id", unique=True),
        Index("ix_deep_mastery_level", "student_id", "current_level"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                        # 隔离键
    subject = Column(String)
    knowledge_id = Column(String)
    knowledge_point_id = Column(Integer, default=0)
    grade = Column(Integer, default=1)

    deep_mastery_score = Column(Integer, default=0)
    recognition_score = Column(Integer, default=0)      # 能识别
    understanding_score = Column(Integer, default=0)    # 理解概念
    application_score = Column(Integer, default=0)      # 会做标准题
    transfer_score = Column(Integer, default=0)         # 会灵活运用
    explanation_score = Column(Integer, default=0)      # 能讲清楚
    retention_score = Column(Integer, default=0)        # 长期记住

    current_level = Column(Integer, default=0)          # 0 UNKNOWN ~ 6 RETAIN
    level_key = Column(String, default="UNKNOWN")
    evidence_count = Column(Integer, default=0)
    standard_count = Column(Integer, default=0)
    recall_count = Column(Integer, default=0)
    transfer_count = Column(Integer, default=0)
    explanation_count = Column(Integer, default=0)
    delayed_count = Column(Integer, default=0)
    recovery_count = Column(Integer, default=0)
    prerequisite_count = Column(Integer, default=0)
    hint_dependency = Column(Float, default=0.0)        # 提示依赖 0~1（越高越依赖提示）
    guess_count = Column(Integer, default=0)            # 「我猜的」次数
    misconception_flag = Column(Boolean, default=False)  # 疑似概念性误解
    last_evidence_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class LearningEvidence(Base):
    """V2.7 统一学习证据：一切影响 Deep Mastery 的作答都落成一行证据。

    ``evidence_type`` 见 ``deep_learning/evidence.py``；``weight`` 是这条证据的
    强度（0.05~1.0），由证据类型 × 提示层级 × 自信度共同决定 ——
    无提示主动回忆、迁移题正确、延迟后正确都是强证据，猜对与依赖高级提示是弱证据。
    """

    __tablename__ = "learning_evidence"
    __table_args__ = (
        Index("ix_evidence_student", "student_id", "subject", "knowledge_id"),
        Index("ix_evidence_type", "student_id", "evidence_type", "created_at"),
        Index("ix_evidence_question", "student_id", "question_id"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                        # 隔离键
    subject = Column(String)
    knowledge_id = Column(String)
    evidence_type = Column(String, default="STANDARD")  # STANDARD/RECALL/TRANSFER/...
    question_id = Column(Integer, default=0)
    result = Column(String, default="wrong")           # correct / partial / wrong
    correct = Column(Boolean, default=False)
    difficulty = Column(Integer, default=50)
    hint_level = Column(Integer, default=0)             # 0~4（Recall Hint Ladder）
    confidence = Column(String, default="")            # sure / maybe / guess / unknown / ""
    response_time = Column(Float, default=0.0)
    weight = Column(Float, default=0.0)                 # 证据强度 0.05~1.0
    dimensions = Column(Text, default="[]")             # 命中维度（JSON 数组）
    source = Column(String, default="submit")           # submit / transfer / recall / explain / review
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)


class RootCauseRecord(Base):
    """V2.7 薄弱根因记录：不只「应用题做错了」，而是「为什么错」。"""

    __tablename__ = "root_cause_record"
    __table_args__ = (
        Index("ix_root_cause_student", "student_id", "subject", "knowledge_id"),
        Index("ix_root_cause_type", "student_id", "root_cause_type", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                        # 隔离键
    subject = Column(String)
    knowledge_id = Column(String)
    answer_record_id = Column(Integer, default=0)
    question_id = Column(Integer, default=0)
    root_cause_type = Column(String, default="CONCEPT_GAP")
    root_cause_confidence = Column(Float, default=0.0)
    related_knowledge_ids = Column(Text, default="[]")  # JSON 数组
    recommended_action = Column(String, default="")
    analysis = Column(Text, default="")
    source = Column(String, default="rule")             # rule / ai
    created_at = Column(DateTime, default=datetime.now)


class TransferAttempt(Base):
    """V2.7 迁移尝试：一次变式题作答（T0~T5）。"""

    __tablename__ = "transfer_attempt"
    __table_args__ = (
        Index("ix_transfer_student", "student_id", "subject", "knowledge_id"),
        Index("ix_transfer_level", "student_id", "knowledge_id", "transfer_level"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                        # 隔离键
    subject = Column(String)
    knowledge_id = Column(String)
    transfer_level = Column(Integer, default=0)         # T0~T5
    question_id = Column(Integer, default=0)
    correct = Column(Boolean, default=False)
    hint_used = Column(Integer, default=0)              # 用到的提示层级
    response_time = Column(Float, default=0.0)
    source = Column(String, default="transfer")         # ai / local / existing / fallback
    child_message = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class ExplanationAttempt(Base):
    """V2.7 解释尝试：「讲给菲比听」的一次回答与概念覆盖评估。"""

    __tablename__ = "explanation_attempt"
    __table_args__ = (
        Index("ix_explain_student", "student_id", "subject", "knowledge_id"),
        Index("ix_explain_created", "student_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                        # 隔离键
    subject = Column(String)
    knowledge_id = Column(String)
    question = Column(Text, default="")
    student_response = Column(Text, default="")
    concept_coverage = Column(Float, default=0.0)       # 0~1
    quality_score = Column(Integer, default=0)
    core_concept_correct = Column(Boolean, default=False)
    missing_concepts = Column(Text, default="[]")       # JSON 数组
    possible_misconceptions = Column(Text, default="[]")
    feedback = Column(Text, default="")
    source = Column(String, default="rule")             # rule / ai
    created_at = Column(DateTime, default=datetime.now)


class StudentPoint(Base):
    """V2.8 积分账户：每个孩子一个余额（只记加法的账，商城兑换暂不实装）。"""

    __tablename__ = "student_point"
    __table_args__ = (
        Index("ix_point_account_student", "student_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                        # 隔离键
    balance = Column(Integer, default=0)                # 当前可用积分
    total_earned = Column(Integer, default=0)           # 累计获得
    updated_at = Column(DateTime, default=datetime.now)
    created_at = Column(DateTime, default=datetime.now)


class PointRecord(Base):
    """V2.8 积分流水：加一次分记一条；``once_key`` 非空时同一个孩子只能记一次。"""

    __tablename__ = "point_record"
    __table_args__ = (
        Index("ix_point_record_student_date", "student_id", "date"),
        Index("ix_point_record_once", "student_id", "once_key", unique=True),
    )

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)                        # 隔离键
    date = Column(String, default="")                  # YYYY-MM-DD
    event = Column(String, default="")                 # answer_correct / daily_checkin / free_practice / task_done
    label = Column(String, default="")                 # 展示用文案
    points = Column(Integer, default=0)
    note = Column(String, default="")
    once_key = Column(String, nullable=True, default=None)   # NULL=可重复记；有值=同人唯一
    created_at = Column(DateTime, default=datetime.now)
