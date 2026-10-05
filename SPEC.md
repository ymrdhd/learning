# V2.5 实施规格（SPEC）— Lead Architect 冻结版

> **这份文件是 V2.5 的唯一接口契约。** 所有 Agent 开工前必须读完本文与 `docs/MODULE_MAP.md`；
> 文中出现的表名、字段名、函数签名、路由路径、响应字段**不得擅自更改**。
> 确实需要改动时，先在群里（swarm report）通知 Lead Architect，由 Lead 改本文后再动代码。
>
> 记录时间：V2.5 开发启动前（基线见 §1）。

---

## 0. 本次交付物（Release 层）

| 交付 | 内容 |
|---|---|
| 版本 | `V2.4` → `V2.5`（`backend/main.py` 的 `FastAPI(title="AI小学学习系统 V2.5")`） |
| 功能 1 | **错题康复系统**：错题生命周期 `NEW → ANALYZING → LEARNING → PRACTICING → VERIFYING → MASTERED` |
| 功能 2 | **每日学习习惯系统**：每日任务生成、连续打卡、完成率、学习时长 |
| 文档 | `ARCHITECTURE.md`（新建，根目录）、`CHANGELOG.md`（新建，根目录）、`docs/MODULE_MAP.md`（更新）、`docs/TODO.md`（新建）、各 Agent 设计文档 |
| 报告 | `TEST_REPORT.md`、`V25_RELEASE_REPORT.md` |

---

## 1. 基线事实（Lead 已实测，不要推翻）

- 工程根：`C:\Users\1\Desktop\ai_learning_system`，**不是 git 仓库**（无版本控制，改动前自己留备份）。
- 运行环境：系统 Python `3.13`（`fastapi 0.142.2`、`sqlalchemy 2.1.3`）。**后端套件必须用系统 python**；
  DSH 捆绑 Python 没有项目依赖，会 `ModuleNotFoundError: requests`。
- 现有 19 张表（`backend/learning.db`，行数快照 `.v25_schema_baseline.json`）：
  `abilities(4)` `answer_error_analysis(17)` `answer_records(69)` `diagnostic_records(1)` `diagnostic_sessions(1)`
  `knowledge_memory_state(5)` `knowledge_points(139)` `learning_feedback(4)` `learning_plan(4)`
  `learning_strategy_log(17)` `questions(94)` `review_queue(1)` `review_strategy_log(9)` `reviews(6)`
  `student_knowledge_mastery(5)` `students(2)` `wrong_questions(10)`（另有 `sqlite_sequence`、`sqlite_stat1`）。
- 学生：`students` 表 2 行（学生 A / 学生 B），**双用户隔离是本项目一等约束**。
- 契约卡门禁：`python backend/check_cards.py` → `缺卡片: 0 失真条目: 0`（当前 76 个模块）。
- 全量验证：`python backend/verify_all.py`（16 个套件，各用独立端口 8899~8908 + 独立临时库）。
- 代码前 8 行是**模块契约卡**（`# 能力契约｜…` / `# 入口：` / `# 依赖：` / `# 不负责：` / `# 验证：` / `# 被调用：` / `# 索引：`），
  新建模块必须照抄这个格式，否则 `check_cards.py` 会报缺卡片。

---

## 2. 硬约束（违反即打回）

1. 后端 FastAPI、数据库 SQLite（`backend/learning.db`，SQLAlchemy 2.x），不引入新依赖（`backend/requirements.txt` 不动）。
2. **双学生数据隔离**：所有新表必须带 `student_id` 列，所有查询必须按 `student_id` 过滤，禁止跨学生聚合。
3. 语数英三科 + 1~6 年级语义不变；沿用 `backend/stages.py` 的能力阶段体系，不另造一套。
4. DeepSeek 只能通过已有 `backend/deepseek.py` 调用；**没有 key / 设了 `PHOEBE_AI_OFFLINE=1` / 超时必须走本地降级**，
   任何 AI 路径都不能让答题主流程失败。
5. **V2.4 数据兼容**：只能新增表 / 新增列，禁止删列、改列名、改类型、清表。迁移必须幂等（重复启动结果一致）。
6. `wrong_questions` 表 V2.4 已有 `NEW / LEARNING / MASTERED` 三态和 10 行数据：
   **`stage` 列是能力阶段（`"3.2"` 这种），不是康复状态**。V2.5 的康复状态放在新表，别去改 `wrong_questions.stage` 的含义。
7. 判分唯一真相是 `grading.is_correct`；题目质量唯一真相是 `validator.QuestionValidator`；不要自己写第二套。
8. Minimal Diff：不重构与需求无关的代码，不动 `backend/_legacy/`。

---

## 3. 数据库设计（Agent 1 = Database，唯一负责人）

新增 **3 张表**，全部放在 `backend/models.py` 末尾（模型名 / 表名 / 列名 / 类型以下表为准）。

### 3.1 `wrong_question_recovery` → 类 `WrongQuestionRecovery`

| 列 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | Integer PK | | |
| `student_id` | Integer | | 隔离键 |
| `subject` | String | | 数学 / 语文 / 英语 |
| `knowledge_id` | String | | 知识点名称 |
| `question_id` | Integer | | 原错题 `questions.id` |
| `wrong_question_id` | Integer | | 对应 `wrong_questions.id`（无则 0） |
| `state` | String | `"NEW"` | 见 §4 状态机，6 态 |
| `state_before` | String | `""` | 上一次状态（审计） |
| `attempts` | Integer | 0 | 康复练习作答次数 |
| `correct_count` | Integer | 0 | 康复练习答对次数 |
| `consecutive_correct` | Integer | 0 | 当前连对（**晋级用的就是它**） |
| `fail_count` | Integer | 0 | 康复期内累计答错 |
| `max_level_used` | Integer | 0 | 已用到的最高提示层级 0~4（§5.2） |
| `variant_count` | Integer | 0 | 已生成变式题数 |
| `last_state_change` | DateTime | | 状态最近一次变化时间 |
| `next_verify_time` | DateTime | | VERIFYING 到期时间（到期即判定提升 / 回落） |
| `mastered_time` | DateTime | | 进入 MASTERED 的时间 |
| `source` | String | `"wrong_book"` | 来源：`wrong_book` / `manual` |
| `created_time` | DateTime | now | |
| `updated_time` | DateTime | now(onupdate) | |

索引：`Index("ix_recovery_student_state", "student_id", "state")`、
`Index("ix_recovery_unique", "student_id", "question_id", unique=True)`、
`Index("ix_recovery_verify_due", "student_id", "next_verify_time")`。

### 3.2 `daily_learning_task` → 类 `DailyLearningTask`

| 列 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | Integer PK | | |
| `student_id` | Integer | | 隔离键 |
| `date` | String | | `YYYY-MM-DD`（复用 `adaptive/planner.date_text`） |
| `task_type` | String | `"new_learning"` | `new_learning` / `weakness` / `review`（= 50/30/20 三类） |
| `title` | String | | 儿童文案标题 |
| `subject` | String | | |
| `knowledge_id` | String | | |
| `target_count` | Integer | 0 | 目标题量 |
| `complete_count` | Integer | 0 | 已完成题量 |
| `duration_minutes` | Integer | 0 | 该任务累计学习时长（分钟） |
| `target_minutes` | Integer | 0 | 计划时长 |
| `status` | String | `"pending"` | `pending` / `doing` / `done` |
| `priority` | Integer | 1 | 数字越小越先做 |
| `source` | String | `"plan"` | `plan`（由 `learning_plan` 转来）/ `review_queue` / `habit` |
| `plan_id` | Integer | 0 | 关联 `learning_plan.id`（无则 0） |
| `knowledge_ids` | Text | `"[]"` | JSON 数组，复习类任务可能含多个知识点 |
| `goal` | String | `""` | 给孩子看的一句话目标 |
| `reason` | String | `""` | 为什么安排 |
| `completed_time` | DateTime | | 全部完成时间 |
| `created_time` | DateTime | now | |
| `updated_time` | DateTime | now(onupdate) | |

索引：`Index("ix_daily_task_student_date", "student_id", "date")`、
`Index("ix_daily_task_unique", "student_id", "date", "task_type", "subject", "knowledge_id", unique=True)`。

### 3.3 `learning_habit_profile` → 类 `LearningHabitProfile`

| 列 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `id` | Integer PK | | |
| `student_id` | Integer | | 一个学生一行（唯一） |
| `current_streak` | Integer | 0 | 当前连续学习天数 |
| `longest_streak` | Integer | 0 | 历史最长连续天数 |
| `total_days` | Integer | 0 | 累计有学习记录的天数 |
| `total_tasks` | Integer | 0 | 累计任务数 |
| `completed_tasks` | Integer | 0 | 累计完成任务数 |
| `total_minutes` | Integer | 0 | 累计学习时长（分钟） |
| `today_minutes` | Integer | 0 | 今日时长（跨天自动归零重算） |
| `completion_rate` | Float | 0.0 | 完成率 0~1（完成数 / 任务数） |
| `last_active_date` | String | `""` | `YYYY-MM-DD`，判定连续天数用 |
| `badges` | Text | `"[]"` | JSON 数组，徽章 key 列表 |
| `level` | Integer | 1 | 习惯等级（由连续天数与完成率推出，≥1） |
| `created_time` | DateTime | now | |
| `updated_time` | DateTime | now(onupdate) | |

索引：`Index("ix_habit_profile_student", "student_id", unique=True)`。

### 3.4 迁移要求

- `backend/database.py`：新增 `ensure_schema` 调用即可覆盖新表新列（`create_all` 建新表，`ensure_schema` 补列）；
  如需数据迁移，追加到 `MIGRATIONS` 元组，**必须是幂等 SQL**。
- 迁移必须**不改变** §1 里 17 张有数据表的行数。
- 交付 `DATABASE_CHANGE.md`（根目录）：新旧结构对照、迁移步骤、回滚方式、实测证据。

---

## 4. 错题康复状态机（Agent 2 = Recovery Core）

```
NEW ──analyze──▶ ANALYZING ──hint(Level1/2)──▶ LEARNING
                                                  │  答对 / 生成变式题
                                                  ▼
NEW ◀────────── 连错 2 次回炉 ──────────────── PRACTICING ◀──┐
                                                  │  变式题连对 2 次     │ 验证未过
                                                  ▼                    │
                                              VERIFYING ────────────────┘
                                                  │  原题（或同知识点题）答对
                                                  ▼
                                              MASTERED
```

| 状态 | 含义 | 进入条件 | 允许的下一步 |
|---|---|---|---|
| `NEW` | 刚进康复队列，还没分析 | 错题登记 / 回炉 | → ANALYZING |
| `ANALYZING` | AI 已定位错因，准备讲解 | `start` 后（有错因分析或生成成功） | → LEARNING |
| `LEARNING` | 分层提示教学中 | 用了 Level1~4 提示 | → PRACTICING |
| `PRACTICING` | 练变式题 | 生成 ≥1 道变式题并作答 | → VERIFYING（连对 2）/ 留在 PRACTICING / 回 NEW（连错 2） |
| `VERIFYING` | 原题验证 | 变式题连对 2 次 | → MASTERED（原题答对）/ → PRACTICING（答错或超时未验证） |
| `MASTERED` | 已康复 | VERIFYING 答对 | 再次答错 → NEW（重新入队） |

**计数规则（必须一致，测试会核对）**：
- `PRACTICING` 阶段每答对 1 次 `consecutive_correct += 1`；`consecutive_correct >= 2` → `VERIFYING`，并置 `next_verify_time = now + 1 天`。
- `PRACTICING` 阶段答错 → `consecutive_correct = 0`，`fail_count += 1`；`fail_count` 使 `fail_count % 2 == 0` 时回 `NEW`（回炉重学）。
- `VERIFYING` 答对 → `MASTERED`，写 `mastered_time`。
- `VERIFYING` 答错 → 回 `PRACTICING`（`consecutive_correct = 0`）。
- 任何状态再次答错原题 → `NEW`，`state_before` 记原状态，`fail_count += 1`。

### 4.1 包结构（`backend/recovery/`）

| 文件 | 职责 | 必须导出的入口 |
|---|---|---|
| `backend/recovery/__init__.py` | 子包分工表契约卡（照抄 `backend/review/__init__.py` 的风格） | `__all__` |
| `backend/recovery/state.py` | 纯状态机，**不碰数据库** | `RecoveryState`（常量类：`NEW/ANALYZING/LEARNING/PRACTICING/VERIFYING/MASTERED`、`ALL`、`TEXT`、`ORDER`）<br>`transition(state, event, *, consecutive_correct=0, fail_count=0)` → `dict(state, changed, reason, next_state)`<br>`apply_result(state, correct, *, consecutive_correct=0, fail_count=0)` → `dict`<br>`next_action(state)` → `str`（`"analyze" / "hint" / "practice" / "verify" / "celebrate"`）<br>`is_active(state)` → `bool` |
| `backend/recovery/strategy.py` | 纯策略：决定一个错题下一步该干什么、用哪级提示、出什么题 | `RecoveryStrategy.plan(item, *, mastery=None, hint_level=0)` → `dict(action, hint_level, difficulty, question_type, target_count, reason)`<br>`RecoveryStrategy.hint_level_for(attempts, max_level_used, fail_count)` → `int`（1~4）<br>`RecoveryStrategy.should_vary(state, attempts)` → `bool`<br>`DEFAULT_STRATEGY` |
| `backend/recovery/scheduler.py` | 队列与到期调度（可碰库，只读为主，负责入队） | `RecoveryScheduler.enqueue(db, student_id, limit=20)` → `list[WrongQuestionRecovery]`（把 `wrong_questions` 里 NEW/LEARNING 的题补进康复队列，幂等）<br>`RecoveryScheduler.due_verify(db, student_id, now=None)` → `list`<br>`RecoveryScheduler.summarize(rows)` → `dict`（各状态计数 + `total` + `mastered_rate`）<br>`DEFAULT_SCHEDULER` |
| `backend/recovery/engine.py` | **唯一碰库的康复门面** | `RecoveryEngine.list_items(db, student_id, subject=None, state=None, limit=50)`<br>`start(db, student_id, recovery_id)`（→ ANALYZING/LEARNING，返回 `item + teaching`）<br>`next_question(db, student_id, recovery_id, hint_level=None)`（出题：变式题或原题）<br>`answer(db, student_id, recovery_id, answer, *, question_id=None, hint_level=None)`（判分 + 状态推进 + 写 `answer_records`）<br>`verify(db, student_id, recovery_id, answer, *, question_id=None)`（VERIFYING 原题验证）<br>`sync_from_wrong_book(db, student_id, question_row, correct)`（`main.submit` 挂钩，答错入队 / 答对推进）<br>`stats(db, student_id)`<br>`detail(db, student_id, recovery_id)`<br>`DEFAULT_ENGINE` |

**契约细节**：
- `engine.DEFAULT_ENGINE` 之外的模块不得直接写 `wrong_question_recovery` 表。
- `answer` 必须返回统一结构：`{correct, correct_answer, analysis, state, state_text, changed, next_action, hint_level, hint, variant, stats}`。
- 判分调用 `grading.is_correct(row, answer)`，与 `main.submit` 同源。
- 出题优先用 `ai_recovery.VariantQuestionGenerator`（Agent 3）；生成失败/离线时**降级**为「同知识点已有题目」（`questions` 表查同 subject+knowledge+difficulty 附近的行）。
- `sync_from_wrong_book` 必须是**幂等且不抛异常**的：内部 try/except，出错只记日志，绝不影响 `main.submit` 的判分返回。

交付 `RECOVERY_DESIGN.md`（根目录）：状态机图、事件表、计数规则、与 `wrong_questions` 的关系、降级路径、实测证据。

---

## 5. AI 错题教学（Agent 3 = AI）

### 5.1 `backend/ai_recovery.py`

| 入口 | 签名 | 说明 |
|---|---|---|
| `AIRecoveryTeacher` | 类 | 分层提示老师 |
| `AIRecoveryTeacher.teach` | `(question_row, *, knowledge=None, error_type="", level=1, student=None, use_ai=True) -> dict` | 返回 `{level, level_text, hint, source, error_location, steps, full_explanation}` |
| `AIRecoveryTeacher.levels` | `() -> list[dict]` | 静态：`[{"level":1,"name":"方向提示","text":"..."}, ... Level4]` |
| `level_name` | `(level) -> str` | `1 方向提示 / 2 错误定位 / 3 步骤引导 / 4 完整讲解` |
| `VariantQuestionGenerator` | 类 | 变式题生成器 |
| `VariantQuestionGenerator.generate` | `(question_row, *, count=1, difficulty=None, knowledge=None, use_ai=True) -> list[dict]` | 每题形如 `{question, answer, options, qtype, knowledge, difficulty, analysis, source, validation}` |
| `VariantQuestionGenerator.validate_variant` | `(data, *, subject, knowledge, difficulty) -> dict` | **必须**调用 `validator.QuestionValidator.validate`（或模块级 `validate`） |
| `ai_enabled` | `() -> bool` | 与 `phoebe_ai.ai_enabled` 同款：没有 key 或 `PHOEBE_AI_OFFLINE=1` 则 False |
| `fallback_hint` | `(question_row, level, error_type="") -> dict` | 离线/失败时的规则文案 |

**硬规则**：
- 生成变式题必须过 `QuestionValidator`，`passed == False` 的题**一律丢弃**（记 `validation` 字段便于取证），丢弃后不足 `count` 时用规则模板补。
- 变式题的 `source` 只能是 `"ai"` / `"rule"`（`ai` 只在真实 DeepSeek 返回且通过审核时写）。
- 四级提示逐级给信息：Level1 只给方向（不给答案）、Level2 指出错在哪一步、Level3 给步骤（仍不给最终答案）、Level4 完整讲解含答案。
- 任何异常都要降级到 `fallback_hint`，不得向上抛。
- 交付 `AI_RECOVERY_DESIGN.md`（根目录）。

### 5.2 `backend/ai_recovery_routes.py`（可选，若 Agent 3 需要暴露调试接口）

只允许 `GET /api/recovery/hint/{recovery_id}?level=1`（读，不推进状态）。其余康复接口统一由 Agent 5 负责。

---

## 6. 每日学习习惯（Agent 4 = Habit）

### 6.1 `backend/habit.py`

| 入口 | 签名 | 说明 |
|---|---|---|
| `HabitEngine` | 类 | 习惯系统门面 |
| `HabitEngine.MIX` | 类属性 | `{"new_learning": 0.5, "weakness": 0.3, "review": 0.2}`（**50% / 30% / 20%**） |
| `HabitEngine.MIX_TEXT` | 类属性 | `{"new_learning": "新知识", "weakness": "薄弱训练", "review": "复习恢复"}` |
| `HabitEngine.generate_daily_tasks` | `(db, student_id, *, date=None, minutes=None, force=False) -> list[DailyLearningTask]` | 生成 / 复用当天任务，**幂等**（同一天重复调用不新增行） |
| `HabitEngine.today` | `(db, student_id, *, date=None) -> dict` | `{date, tasks:[...], summary:{total, done, pending, completion_rate, minutes, mix:{new_learning, weakness, review}}, generated}` |
| `HabitEngine.complete_task` | `(db, student_id, task_id, *, minutes=0, count=None, done=True) -> dict` | 完成 / 部分完成，累加 `duration_minutes`，`complete_count >= target_count` 自动 `done` |
| `HabitEngine.record_answer` | `(db, student_id, *, subject, knowledge, correct, minutes=0, date=None) -> dict` | 答题钩子：把作答算进当天任务（找到匹配任务 `complete_count += 1`）与时长 |
| `HabitEngine.profile` | `(db, student_id, *, date=None) -> dict` | 习惯画像（含连续天数、完成率、时长、徽章、等级、近 7 天曲线） |
| `HabitEngine.stats` | `(db, student_id, *, days=7, date=None) -> dict` | 近 N 天完成率 / 时长序列 |
| `HabitEngine.refresh` | `(db, student_id, *, date=None) -> dict` | 重算并落库 `learning_habit_profile` |
| `DEFAULT_ENGINE` | 实例 | |

**配比规则**：三类任务的题量按 `MIX` 分配 —— 给定总题量 `total`（默认由 `adaptive.planner.target_count_of` 推）：
`new_learning = round(total*0.5)`、`weakness = round(total*0.3)`、`review = total - 前两者`（保证合计 = total，且每类 ≥1 题）。
用 `review.mix.split_counts`（若签名匹配）或自己实现，但**必须**在 `HABIT_DESIGN.md` 写清算术。

**连续天数规则**：当天有任意任务完成（`status == "done"` 或 `complete_count > 0`）即算「今天学了」；
`last_active_date` 是昨天 → `current_streak += 1`；是今天 → 不变；更早或为空 → 重置为 1。
`refresh` 时若 `last_active_date` 早于昨天，`current_streak` 归零。

**徽章**：`first_day`（首次）、`streak_3`、`streak_7`、`streak_30`、`rate_80`（完成率 ≥ 0.8 且任务数 ≥ 5）、`minutes_100`（累计 ≥100 分钟）。
徽章只增不减（`badges` JSON 去重合并）。

**降级规则**：没有 `learning_plan` 时，用 `student_knowledge_mastery` 的薄弱知识点（`mastery_score` 升序）自造三类任务；
三科都要能生成，不依赖 DeepSeek。

交付 `HABIT_DESIGN.md`（根目录）。

---

## 7. API 契约（Agent 5 = API）

统一前缀 `/api`，`student_id` 出现在查询串或请求体，**每个接口都必须按 `student_id` 过滤**；
返回 JSON 一律含 `student_id`；学生不存在时返回**空结构而不是 404**（与 `ability_routes` 一致）。

### 7.1 错题康复

| 方法 | 路径 | 请求 | 响应关键字段 |
|---|---|---|---|
| GET | `/api/recovery/list` | `student_id`（必）, `subject?`, `state?`, `limit?` | `student_id, total, stats{new,analyzing,learning,practicing,verifying,mastered,total,mastered_rate}, items[{recovery_id, question_id, subject, knowledge, state, state_text, wrong_count, attempts, consecutive_correct, fail_count, max_level_used, question, correct_answer, analysis, error_type, next_verify_time, created_time}]` |
| POST | `/api/recovery/start` | `{student_id, recovery_id}` 或 `{student_id, question_id}` | `recovery_id, question_id, state, state_text, teaching{level, level_text, hint, error_location, steps, full_explanation, source}, item` |
| POST | `/api/recovery/question` | `{student_id, recovery_id, hint_level?}` | `recovery_id, state, hint_level, question{question_id, question, qtype, options, knowledge, difficulty, source, variant}, teaching{...}` |
| POST | `/api/recovery/answer` | `{student_id, recovery_id, answer, question_id?, hint_level?, minutes?}` | `correct, correct_answer, analysis, state, state_text, changed, next_action, hint_level, hint, stats, review_next` |
| POST | `/api/recovery/verify` | `{student_id, recovery_id, answer}` | 同 `/answer`，另含 `mastered: bool` |
| POST | `/api/recovery/hint` | `{student_id, recovery_id, level?}` | `level, level_text, hint, error_location, steps, full_explanation, source` |

### 7.2 每日任务与习惯

| 方法 | 路径 | 请求 | 响应关键字段 |
|---|---|---|---|
| GET | `/api/tasks/today` | `student_id`（必）, `date?` | `student_id, date, generated, tasks[{task_id, task_type, task_type_text, title, subject, knowledge, target_count, complete_count, duration_minutes, target_minutes, status, status_text, priority, goal, reason}], summary{total, done, pending, completion_rate, minutes, mix{new_learning, weakness, review}}` |
| POST | `/api/tasks/complete` | `{student_id, task_id, minutes?, count?, done?}` | `task_id, status, status_text, complete_count, duration_minutes, summary, profile{...}` |
| GET | `/api/habit/profile` | `student_id`（必）, `date?` | `student_id, current_streak, longest_streak, total_days, total_tasks, completed_tasks, completion_rate, total_minutes, today_minutes, level, level_text, badges[{key, name, icon, got}], last_active_date, recent[{date, done, total, minutes, rate}]` |
| GET | `/api/habit/stats` | `student_id`（必）, `days?` | `student_id, days, items[{date, done, total, minutes, rate}], avg_rate, total_minutes` |

**路由文件切分**（减少并发改写冲突）：
- `backend/recovery_routes.py`：§7.1 全部接口。
- `backend/habit_routes.py`：§7.2 全部接口。
- `backend/task_routes.py`：**只放** `GET /api/tasks/today` 与 `POST /api/tasks/complete`，内部调用 `habit.DEFAULT_ENGINE`。

交付 `API_UPDATE.md`（根目录）：每个接口的请求 / 响应样例（真实 curl 或 `requests` 实测输出）+ 错误码说明。

---

## 8. 前端（Agent 6 = Frontend）

| 页面 | 文件 | 入口 |
|---|---|---|
| 错题中心 | `frontend/recovery.html` + `frontend/recovery.js` | 首页 / 今日学习页导航加「错题康复」 |
| 今日学习（改造） | `frontend/today.html` + `frontend/today.js` | 顶部加「今日任务」区块，调用 `/api/tasks/today` 与 `/api/tasks/complete` |
| 学习完成反馈 | `frontend/recovery.js` 内的完成弹层 + `frontend/style.css` | 康复完成时显示 |

**儿童友好硬要求**（测试会按代码断言）：
- 大按钮：主操作按钮 CSS 最小高度 ≥ 56px、字号 ≥ 18px，类名沿用 `.btn`/`.btn-primary`/`.recovery-*`。
- 少文字：单屏可见文字块 ≤ 3；提示逐级展开（先给 Level1，点「还是不会」再给下一级）。
- 明确反馈：正确 → 绿色 ✅ + 菲比开心（调用已有 `phoebe3dFeedback(true)`，模块缺失时静默降级）；
  错误 → 橙色 ❌ + 正确答案 + 「看看解析」按钮。
- 复用已有立牌：`phoebe3d.js` 已在页面引入时不要重复引入；`phoebe3dFeedback` 调用要有 `typeof` 守卫。
- **不改** `frontend/app.js`、`frontend/phoebe3d.js`、`frontend/phoebe.js` 的既有行为（只有 `today.js`/`today.html` 允许改）。

交付 `FRONTEND_CHANGE.md`（根目录）。

---

## 9. 测试（Agent 7 = QA）

新增两个后端套件（端口不能与现有 8899~8908 冲突）：

| 脚本 | 套件 key | 端口 | 覆盖 |
|---|---|---|---|
| `backend/verify_recovery.py` | `recovery` | 8910 | 状态机 6 态全流转、`/api/recovery/*`、连对/连错规则、变式题过审、AI 降级、A/B 隔离 |
| `backend/verify_habit.py` | `habit` | 8911 | 50/30/20 配比、幂等生成、完成率、连续天数、徽章、`/api/tasks/*` 与 `/api/habit/*`、A/B 隔离 |

要求：
- 复用现有套件风格（自带临时后端 + 临时库 + 独立端口，`VERIFY_*_PORT` 环境变量，末尾打印 `RESULT: ALL PASS` / `HAS FAILURES`，退出码 0/1）。
- **每个套件必须打印断言条数**，并包含 **V2.4 数据兼容**用例：在临时库上先建 17 张 V2.4 表并塞入样例数据 → 跑迁移 → 校验行数与旧列不变。
- 必须包含失败路径：康复答错回炉、AI 离线降级、未知 `student_id`、跨学生越权访问（学生 A 的 `recovery_id` 用 B 的 `student_id` 请求 → 返回空 / 404 语义明确且不泄露 A 的数据）。
- 交付 `TEST_REPORT.md`（根目录）：命令、断言总数、通过/失败明细、被跳过项与原因（禁止隐藏失败）。

---

## 10. 集成与文档（Agent A = 集成/文档，Lead 直接执行）

1. `backend/main.py`：注册 `recovery_routes` / `habit_routes` / `task_routes` 三个 router（**由 Lead 统一改，Agent 5 不要动 main.py**）；
   版本号 `V2.4` → `V2.5`；启动时调用 `recovery.DEFAULT_ENGINE.sync_from_wrong_book`（历史错题入队，幂等）与 `habit` 的当天任务生成（容错）。
2. `backend/main.py` 的 `submit`：答题后挂钩 `recovery.DEFAULT_ENGINE.sync_from_wrong_book(...)` 与 `habit.DEFAULT_ENGINE.record_answer(...)`，**各自 try/except 独立提交**，绝不改变现有返回结构。
3. `backend/verify_all.py`：`SUITES` 增加 `recovery`(8910) / `habit`(8911) 两个套件（顺序放在末尾）。
4. 文档：根目录 `ARCHITECTURE.md`、`CHANGELOG.md`、`docs/TODO.md`；更新 `docs/MODULE_MAP.md`（能力表 + 表归属 + 套件表）、`README.md`、`PROJECT_CONTEXT.md`。
   `ARCHITECTURE.md` 必须写：Current Version `V2.5`、模块结构、数据模型、API 清单、学习流程、TODO。**不写开发日志。**
5. 最终交付 `V25_RELEASE_REPORT.md`（根目录）与验收判定。

---

## 11. 文件所有权（并发写入唯一真相 — 违反即冲突）

| 文件 / 目录 | 唯一负责人 |
|---|---|
| `backend/models.py`、`backend/database.py`、`DATABASE_CHANGE.md` | Agent 1 |
| `backend/recovery/**`、`RECOVERY_DESIGN.md` | Agent 2 |
| `backend/ai_recovery.py`、`backend/ai_recovery_routes.py`、`AI_RECOVERY_DESIGN.md` | Agent 3 |
| `backend/habit.py`、`HABIT_DESIGN.md` | Agent 4 |
| `backend/recovery_routes.py`、`backend/habit_routes.py`、`backend/task_routes.py`、`API_UPDATE.md` | Agent 5 |
| `frontend/recovery.html`、`frontend/recovery.js`、`frontend/today.html`、`frontend/today.js`（仅新增区块）、`FRONTEND_CHANGE.md` | Agent 6 |
| `backend/verify_recovery.py`、`backend/verify_habit.py`、`TEST_REPORT.md` | Agent 7 |
| `backend/main.py`、`backend/verify_all.py`、`ARCHITECTURE.md`、`CHANGELOG.md`、`docs/TODO.md`、`docs/MODULE_MAP.md`、`README.md`、`PROJECT_CONTEXT.md`、`V25_RELEASE_REPORT.md`、`backend/verify_v25_e2e.py` | Lead Architect（Agent A） |

**共享只读**：`docs/MODULE_MAP.md`、`docs/V2.5功能说明.md`、`AI_RULES.md`、`PROJECT_CONTEXT.md`（只读参考，不要改）。
`frontend/style.css`：Agent 6 可追加 `.recovery-*` / `.habit-*` / `.task-*` 样式块，**不得修改已有选择器**。

---

## 12. 验收标准（Release 判定）

- ✅ 错题生命周期完整（6 态可达、可回炉、可康复）
- ✅ AI 错题讲解（四级提示）、变式题生成（**全部过 QuestionValidator**）、错题重新验证
- ✅ 每日学习任务（50/30/20）、学习习惯统计（连续天数 / 完成率 / 时长）
- ✅ V2.4 数据兼容（19 张旧表行数不变 + 迁移幂等）
- ✅ 双用户隔离（A/B 互不可见）
- ✅ `python backend/verify_all.py` 全绿（16 + 2 = 18 个套件）
- ✅ `python backend/check_cards.py` 缺卡片 0 / 失真 0
- ✅ `ARCHITECTURE.md` / `CHANGELOG.md` / `docs/TODO.md` / `docs/MODULE_MAP.md` 更新到位
