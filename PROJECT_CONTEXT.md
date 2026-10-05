# Project Context

> AI 项目记忆文件
> 每次重大修改后更新

# 1. Project Overview

项目名称：AI小学学习系统（FastAPI app 标题为 `AI小学学习系统 V2.5`，见 `backend/main.py`）

项目用途：面向小学 1~6 年级学生的本地单机自适应练习系统。浏览器中完成「出题 → 作答 → 即时判分」，并配套能力诊断、知识掌握地图、错题本、学习建议、艾宾浩斯复习与语音读题。

当前阶段：**V2.5 已完成可用**——在 V2.4（间隔复习系统）之上，新增**菲比三视图互动公仔**（可拖拽旋转、**6 种表情随点击 / 答对 / 答错 / 连对 / 错题重练 / 空闲自动切换**、答对跳跃 / 答错摇头、浏览器语音 + 屏幕字幕、答对弹表情包）、
**答对自动跳下一题 / 答错停留看解析**、以及**训练成绩自动能力诊断**（不再要求额外做一次专门诊断，`/api/ability/auto/{student_id}` 从答题记录推断三科阶段）、**错题康复**（六态生命周期 + 四级提示 + 变式训练 + 延迟验证，答对一次不会 MASTERED）、**每日学习习惯**（孩子只点「开始今天的学习」，五段动态配比 + 按年级限时 + 「🎉 今天完成啦！」结束点 + 每月 2 次休息保护）、**主动回忆基础版**（24 张卡片，先自己写、不给选项）。
下一阶段待办见 §7。

主要用户/使用场景：家庭内 1~2 名小学生（默认学生「朵朵」「童童」，由 `local_users.py` 首次启动写入；老库里的旧默认名「小朋友A/B」会在启动时幂等改名）；本机访问 `http://127.0.0.1:8000/app/`，同一网段的手机/平板访问 `http://<本机局域网IP>:8000/app/`，无注册、无登录；科目为数学/语文/英语，接口默认科目为数学。

# 2. Technology Stack

## Frontend

Framework: 无（原生 HTML + 原生 `<script src>`，无 npm、无 bundler、无构建步骤、无 CDN 依赖）

Language: HTML + CSS + 原生 JavaScript（普通脚本，非 ES module）

UI: 手写 CSS，全站唯一样式表 `frontend/style.css`；无 UI 组件库

Build: 无构建。静态文件由后端挂载：`app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True))`

## Backend

Framework: FastAPI

Language: Python（本机实测 3.13.16；项目未固定版本，无 pyproject/setup.py）

API: REST + JSON；请求体用 pydantic BaseModel，响应为普通 dict；CORS `allow_origins=["*"]`

Runtime: uvicorn（`uvicorn[standard]`），`0.0.0.0:8000`（固定端口只写在 `start.bat` 中，Python 代码内无端口常量；监听所有网卡，便于同一网段的手机/平板访问）

Database: SQLite（文件 `backend/learning.db`，可用环境变量 `DATABASE_URL` 覆盖；另有 `learning.db.v15-backup`）→ 见 §2 下方「Data」

## Data

Database: SQLite，单文件

ORM: SQLAlchemy ORM（25 张表；仅 PRAGMA / ALTER TABLE 用 `exec_driver_sql`）
  V2.3 自适应学习引擎新增 3 张：`learning_plan`（今日计划）、`learning_strategy_log`（策略日志）、`learning_feedback`（学习反馈）
  V2.4 间隔复习系统新增 4 张：`knowledge_memory_state`（记忆状态）、`review_records`（复习明细）、`review_queue`（每日队列）、`review_strategy_log`（复习算法日志）
  V2.5 错题康复 / 习惯 / 主动回忆新增 4 张：`wrong_question_recovery`（康复状态机）、`daily_learning_task`（每日任务）、`learning_habit_profile`（习惯画像）、`active_recall_record`（主动回忆记录，表数 19 → 23）
  V2.8 积分系统新增 2 张：`student_point`（积分账户：余额 / 累计获得，学生唯一）、`point_record`（积分流水：事件 / 分值 / `once_key` 幂等键，表数 23 → 25）

Cache: 无

Storage: 本地文件系统；题库、阶段表、知识点树、复习间隔等**全部硬编码在 Python 模块内**，不读 `data/` 目录（见 §9、§11）

## Infrastructure

Deployment: 家庭局域网内运行；双击 `start.bat` 启动（固定 8000 端口；已在本机运行且局域网可达则直接打开浏览器并退出，否则以 `--host 0.0.0.0` 启动新实例）

CI/CD: 无（项目不是 git 仓库，无 CI 配置）

Environment: Windows；依赖见 `backend/requirements.txt`（`fastapi` / `uvicorn[standard]` / `sqlalchemy` / `requests` / `python-dotenv` / `pydantic`，均无版本约束）；`backend/.env` 目前只有一个键 `DEEPSEEK_API_KEY`

# 3. Directory Structure

说明主要目录（后端为扁平单层 .py + 两个子包）：

```text
ai_learning_system/
├── start.bat              启动后端；固定 8000 端口 + 监听所有网卡（手机同网段可访问）；启动前先对比仓库版本
├── version.json           版本号唯一真相（本机与 GitHub 仓库同一份：自动更新、start.bat、根接口都读它）
├── PROJECT_CONTEXT.md     本文件（AI 长期上下文）
├── AI_RULES.md            项目级 AI 开发规则
├── backend/               后端全部代码、题库、数据库与验证脚本
│   └── _legacy/           已归档死代码（4 个 .py + README；零引用、禁止接线）
├── frontend/              纯静态前端：10 个页面 + 同名 js + style.css
│   └── assets/phoebe/     答对庆祝素材（4 张 PNG + 3 段 MP3 + manifest.json）
├── data/                  教材/课程 JSON（当前无任何代码引用，见 §9）
├── docs/                  版本功能说明 + MODULE_MAP.md（能力索引表）+ 架构重构_Mixin方案.md
├── tools/                 开发期脚本（`publish.py` 打包上传 GitHub、`v25_schema_snapshot.py` 等）
└── backup/                快照与回退网（已被 .gitignore 排除，不参与运行）
```

**定位代码先读 `docs/MODULE_MAP.md`**（能力 → 文件 → 入口 → 表 → 验证套件）；每个模块文件头都带「能力契约」注释块（职责 / 入口 / 依赖 / 不负责 / 验证 / 被调用）。

backend/ 文件分组：

| 分组 | 文件 |
|---|---|
| 应用装配 | `main.py`（入口 + 核心闭环 API）、`database.py`、`models.py`、`local_users.py` |
| 能力阶段与诊断 | `stages.py`、`diagnostic.py`、`diagnostic_bank.py`、`diagnostic_routes.py`、`ability.py`、`bank_chinese.py`、`bank_english.py` |
| 知识掌握与错题 | `knowledge_tree.py`、`mastery.py`、`knowledge_routes.py`、`wrong_book.py`、`error_analysis.py` |
| 自适应学习引擎（V2.3） | `adaptive/`（子包：`strategy.py`、`difficulty.py`、`selector.py`、`planner.py`、`engine.py`）、`adaptive_routes.py` |
| 间隔复习（V2.4） | `review/`（子包：`memory.py`、`forgetting.py`、`interval.py`、`scheduler.py`、`selector.py`、`mix.py`、`engine.py`）、`review_routes.py` |
| 训练成绩自动诊断（V2.5） | `auto_ability.py`、`ability_routes.py` |
| 菲比 AI 陪伴（V2.5） | `phoebe_ai.py`、`phoebe_routes.py` |
| 出题与判分 | `deepseek.py`、`validator.py`、`grading.py`、`srs.py` |
| 版本与自动更新（V2.8） | `updater.py`、`update_check.py`；项目根 `version.json` + `tools/publish.py` |
| 验证脚本 | `verify_all.py`、`verify_review.py`、`verify_flow.py`、`verify_diagnostic.py`、`verify_knowledge.py`、`verify_adaptive.py`、`verify_memory.py`、`verify_ability.py`、`verify_phoebe_ai.py`、`verify_port_guard.py` |
| 已归档死代码 | `_legacy/`：`adaptive.py`（**与上面的 `adaptive/` 子包无关**）、`algorithm.py`、`ai_question.py`、`reward.py` —— 零引用、禁止接线 |

frontend/ 组织方式：一页 = 同名 `.html` + 同名 `.js`；`index.html` 为入口（练习页），`today.html` 为今日学习页（V2.3 自适应 + V2.5 自动跳题/错题解析），`ability.html` 为**我的能力水平**（V2.5 训练成绩自动诊断），`diagnostic*.html` 为诊断三页（V2.5 起不再出现在主流程入口，页面保留），`knowledge_map.html` / `wrong_book.html` / `study_advice.html` 为知识三页；`phoebe.js` 为答对庆祝浮层（表情包 + 音效），`phoebe3d.js` 为**菲比三视图互动立牌**（拖拽旋转 / 动作 / 语音字幕 / 6 情绪表情 + 答题反馈），两者都必须排在业务 js 之前、缺失时静默降级。

# 4. Important Files

| 文件 | 作用 |
|-|-|
| `backend/main.py` | 应用装配（CORS、路由注册、`/app` 静态挂载）+ 核心闭环 API（`/`、`/students`、`/question`、`/submit`、`/reviews`）；建表/迁移/灌知识树/错因回填在 **import 期**执行 |
| `backend/database.py` | engine 与 Session、`ensure_schema` 补列、`migrate_data` 迁移、`get_db` 每请求会话 |
| `backend/models.py` | **25 张表**模型（schema 唯一真相）：students、abilities、answer_records、reviews、questions、diagnostic_sessions、diagnostic_records、ability_profile、student_knowledge_mastery、knowledge_points、answer_error_analysis、wrong_questions、learning_plan、learning_strategy_log、learning_feedback、knowledge_memory_state、review_records、review_queue、review_strategy_log、wrong_question_recovery、daily_learning_task、learning_habit_profile、active_recall_record、student_point、point_record |
| `backend/stages.py` | 能力阶段唯一来源：72 阶段（每年级 12 块：上册一~六 + 下册一~六）、难度映射、三科×72 知识点、升降级阈值 |
| `backend/deepseek.py` | DeepSeek 出题/错因分析 + 内置兜底题；`generate_question` 可传 `history`（防雷同：prompt 回避 + 本地复核，最多 3 次）；`_load_key()` 手动解析 `backend/.env`，`KEY` 在 import 时求值一次 |
| `backend/question_dedupe.py` | 题干雷同判定**唯一真相**：`normalize_stem` / `numbers_of` / `similarity` / `is_duplicate`（数字变＝新题；日常练习与间隔复习共用） |
| `backend/validator.py` | 题目质量审核（格式/答案/难度/知识点/歧义），error 级拦截 |
| `backend/mastery.py` | MasteryEngine 掌握度模型（加权正确率 + 题量收缩 + 连错惩罚 + 复习加成 + 时间衰减） |
| `backend/srs.py` | 艾宾浩斯间隔阶梯（11 级）与复习调度，`STREAK_TO_ADVANCE=3` |
| `backend/knowledge_tree.py` | 284 节点知识点树（硬编码 DOMAINS/SUBPOINTS）+ 灌库与掌握度关联 |
| `backend/adaptive/engine.py` | AdaptiveLearningEngine 门面：profile / decision_for / next_spec（`avoid_knowledge`：刚练过的知识点不锁定）/ start / feedback / plan / recommend / log（唯一碰数据库的自适应模块） |
| `backend/adaptive/strategy.py` | LearningStrategy 知识点选择 + 知识依赖表（69 条边）+ 依赖门控 |
| `backend/adaptive/difficulty.py` | DifficultyController 难度动态调整（连对 +5 / 连错 −10 / 正确率窗口升降阶段） |
| `backend/adaptive/selector.py` | QuestionSelector 下一题推荐（40% 薄弱 + 30% 匹配 + 20% 遗忘 + 10% 探索）+ `repeat_penalty_of` 同知识点软避让（最近 5 题窗口，0.35 / 0.22 / 0.12，不压过薄弱权重） |
| `backend/adaptive/planner.py` | DailyLearningPlanner 每日计划（时间/题量分配 + 幂等落库） |
| `backend/adaptive_routes.py` | `/api/learning/recommend|plan|start|next-question|feedback|strategy-log` |
| `backend/review/engine.py` | ReviewEngine 门面：记忆状态 / 今日队列 / 复习出题 / 复习作答 / 记忆地图 / 统计 / 迁移（唯一碰数据库的复习模块） |
| `backend/review/memory.py` | MemoryState：记忆强度、稳定性、个人难度、成熟度六级（含儿童文案与知识森林字段） |
| `backend/review/forgetting.py` | ForgettingRiskEngine：遗忘风险 0~1 与高/中/低分级 |
| `backend/review/interval.py` | `calculate_next_interval()`：阶梯起步 + 稳定性驱动的自适应间隔（1~180 天） |
| `backend/review/scheduler.py` | ReviewScheduler：P0~P3 优先级、每科 ≤8 / 每天 ≤15 / 每个 1~3 题 |
| `backend/review/selector.py` | ReviewQuestionSelector：50/30/20 模式配比 + 重复检测（复习题不重复旧题；`is_duplicate`/`similarity` 复用 `question_dedupe`） |
| `backend/review/mix.py` | `calculate_daily_mix()`：新学 / 补强 / 复习 的比例与题量拆分 |
| `backend/review_routes.py` | `/api/review/today|due|question|answer|memory-map|stats|strategy-log|skip|feedback` |
| `backend/recovery/engine.py` | WrongQuestionRecoveryEngine 门面：list_items / detail / stats / start / hint / next_question / answer / verify / sync_from_wrong_book（`/submit` 钩子） |
| `backend/recovery/state.py` | 康复六态状态机（NEW→ANALYZING→LEARNING→PRACTICING→VERIFYING→MASTERED，验证失败回落；VERIFY_STREAK=2） |
| `backend/recovery/strategy.py` + `scheduler.py` | 错因驱动策略 / 入队与到期验证、超时回落 PRACTICING |
| `backend/recovery_routes.py` | `/api/recovery/*`（list / start / question / answer / verify / hint + 兼容 path 形式） |
| `backend/habit.py` | HabitEngine：三段基础任务（50/30/20 幂等落库）+ 五段每日计划 `plan`/`start_today`（40/25/20/10/5 动态）+ `minutes_for_grade` + `rest_status`/`use_rest_protection` + `goal` |
| `backend/task_routes.py` | `/api/tasks/today|plan/{sid}|start|complete|{task_id}/complete` |
| `backend/habit_routes.py` | `/api/habit/profile|stats|rest|goal`（含 path 形式） |
| `backend/active_recall.py` | ActiveRecallEngine：24 张内置卡片、`judge`、`child_level`、记忆增益（独立想起 3.0 / 用满提示 1.05） |
| `backend/active_recall_routes.py` | `/api/active-recall/start|answer|summary` |
| `backend/daily_routes.py` | `GET /api/daily-summary/{student_id}`：任务完成 + 儿童文案 + 「今天可以休息啦！」 |
| `frontend/review.js` | 儿童端知识浇水：卡片渲染、复习题作答、感受反馈（不显示风险指标） |
| `frontend/memory_debug.js` | 家长/开发端：记忆状态表格、今日队列、算法日志 |
| `frontend/today.js` | 今日学习页 + 学习反馈页逻辑；纯函数 `starsOf/starText/percent/remainText/actionText/feelButtonsHtml` |
| `backend/verify_all.py` | 全量验证入口：串行编排 **25 个套件**，各自独立端口与临时库 |
| `docs/MODULE_MAP.md` | **能力索引表**：能力 → 文件 → 入口 → 表 → 验证套件、25 张表归属、前端页面映射、任务速查表；新增/改名模块**必须**同步 |
| `start.bat` | 启动后端（固定 8000 端口、`--host 0.0.0.0`），打印本机与手机访问地址 |
| `frontend/app.js` | 练习页主逻辑（出题/作答/语音/复习面板/V2.8 今日题单 sheet 模式）；API 基址跟着 `location.origin` 走（手机经局域网访问时不打回 127.0.0.1） |
| `frontend/shop.html` + `shop.js` | **V2.8「🛍️ 商城」一级页**（挂在右侧「挑战」下方）：余额卡 / 商品占位（只展示不兑换）/ **第一版奖励行为明细 14 条**（★星级 · 分值区间 · 三态徽标）/ 我的积分流水；数据只读 `GET /api/points/{student_id}`，打卡 `POST /api/points/{student_id}/checkin` |
| `frontend/phoebe.js` | 答对庆祝浮层（表情包 + 音效），零后端依赖；三处答题页依赖它 |
| `frontend/phoebe3d.js` | 菲比三视图互动立牌（旋转 / 拖拽 / 跳跃摇头 / 语音 + 字幕 / **6 情绪表情切换** / **点击触发 AI 台词**）；挂在**浏览器左侧固定**位置，四个页面依赖它，素材在 `frontend/assets/phoebe3d/`（18 张 `{情绪}_{视角}.png`） |
| `frontend/ability.js` | 「我的能力水平」页：只读 `/api/ability/auto/{id}`，展示三科自动推断的阶段与依据 |
| `backend/auto_ability.py` | V2.5 训练成绩自动能力诊断（纯函数 + 只读统计），返回结构见 `docs/V2.5功能说明.md` §4 |
| `backend/phoebe_ai.py` | V2.5 菲比台词：学习数据快照 → DeepSeek 说一句 → 清洗；无 key / 离线 / 超时自动降级（只读，返回结构见 §2.7） |
| `backend/points.py` | **V2.8 积分系统**（只加不减、事件幂等）：`RULES`（答对 2 / 每日打卡 10 / 每日首次登录 10 / 计划做完后继续练 3 / 任务收工 5）、**打卡由「今天的小任务全部收工」自动生成**（`award_after_answer` 与 `award_task_done` 两处结算；`checkin()` 保留但要求 `plan_finished`）、`SHOP_ITEMS`（兑 iPad 时间·玩具·蛋仔充值，比例占位）、`award` / `award_after_answer` / `award_task_done` / `login` / `checkin` / `summary` / `balance_of` / `streak_days` |
| `backend/points_rewards.py` | **V2.8 积分明细**（第一版奖励行为表，只描述规则、不判定不加分）：`REWARDS`（14 条：`key`/`label`/`points_min`/`points_max`/`stars`/`note`/`state`/`event`）、`REWARD_STATES`（live / planned / never）、`reward_table` / `rewards_of` / `points_text` |
| `backend/points_routes.py` | **V2.8 积分 API**：`GET /api/points/{student_id}`（余额 / 今日 / 打卡 / 规则 / 商城占位 / 最近流水 / **第一版奖励明细 `rewards` + `reward_version` + `reward_states`**）、`GET /shop`、`POST /login`（每日首次登录 +10，幂等）、`POST /checkin`（小任务没做完 → `need_finish`；前端已无手动打卡按钮）；商城 `enabled=False`，**不实装兑换** |
| `version.json` | **V2.8 版本号唯一真相**（`version` / `released` / `repo` / `branch` / `notes`）：本机与 GitHub 仓库同一份；`backend/main.py` 的根接口与 `start.bat` 都读它，不要再手写版本号 |
| `backend/updater.py` | **V2.8 版本对比与自动更新**：`local_version`（读 version.json）、`is_newer`、`remote_manifest`（raw → jsDelivr → codeload 归档三路兜底）、`download_archive`、`apply`（覆盖源码文件 + 改前备份到 `backup/pre-update-<旧版本>/`）、`run`；**保护名单**：`*.db` / `.env` / `backup/` / 日志 / `_verify_*` 一概不碰 |
| `backend/update_check.py` | **V2.8 启动时自动更新入口**：`--apply`（start.bat 用）/ `--force` / `--json` / `--version`（打印本机版本号）/ `--self-test`（离线自检 25 项）；连不上仓库只打印一行，**绝不影响启动** |
| `tools/publish.py` | **V2.8 打包上传**：`--dry-run` 打包 `dist/learning-<版本>.zip`；`--push` 走 GitHub Git Data API（免 git 客户端，只传与远端不同的 blob）；令牌读 `GITHUB_TOKEN` 或 `tools/.github_token`（已 gitignore） |
| `backend/net_fallback.py` | **V2.8 直连兜底**：hosts 把 `github.com` / `api.github.com` / `raw.githubusercontent.com` 指到 127.0.0.1 时，用 DoH（阿里/腾讯）解析真实 IP + SNI/Host 头直连；TLS 仍按真实域名校验证书；只在正常 DNS 失败时启用 |

# 5. Architecture

## Data Flow

用户

↓

Frontend（`/app/` 静态页面，原生 JS，fetch + JSON）

↓

API（FastAPI：`main.py` 核心闭环 / `/api/diagnostic/*` / `/api/*`）

↓

Backend 业务模块（`deepseek` 出题 → `validator` 审核 → `grading` 判分 → `srs` 复习调度 → `mastery` 掌握度 → `error_analysis` 错因 → `wrong_book` 错题本）

↓

Database（SQLAlchemy ORM → SQLite `backend/learning.db`）

三条主链路：

1. **日常练习**：`GET /question`（按复习队列/知识点出题并落库，**不下发答案与解析**）→ `POST /submit`（服务端判分，写 `answer_records`，更新 `abilities` / `reviews` / `student_knowledge_mastery` / `wrong_questions` / `answer_error_analysis`）
2. **能力诊断**：`POST /api/diagnostic/start` → 循环 `GET /api/diagnostic/question` + `POST /api/diagnostic/answer` → 结束时写 `ability_profile` → `GET /api/diagnostic/report`
3. **知识复习与错题**：`GET /reviews`、`GET /api/mastery/{student_id}`、`GET /api/wrong_questions/{student_id}`、`GET /api/report/knowledge` 读取掌握度/错题/建议；`POST /api/error/analyze` 补充 AI 错因
4. **自适应学习闭环（V2.3）**：`GET /api/learning/recommend/{id}` 决策（写 `learning_strategy_log`）→ `GET /api/learning/plan/{id}` 今日计划（写 `learning_plan`）→ `POST /api/learning/start` 锁定知识点与难度 → `GET /api/learning/next-question` 出题（内部复用 `main.question`，只指定难度）→ `POST /submit` 判分并更新能力/掌握度 → `POST /api/learning/feedback` 记录主观感受（写 `learning_feedback`，推进计划完成数）
5. **间隔复习闭环（V2.4）**：学习（`/submit` 或复习重新学）→ `MemoryState`（掌握度/稳定性/个人难度/成熟度/下次复习）→ `ReviewScheduler` 今日队列（`review_queue`，按天缓存）→ `GET /api/review/question` 取复习题（变式、不重复旧题）→ `POST /api/review/answer` 判分 → 新间隔/新稳定性/新成熟度（写 `review_records` + `review_strategy_log`）→ 失败进错题康复，连续失败转 `RELEARN` 回自适应引擎

关键边界：

- **前端**：只做渲染与交互，不含业务规则，拿不到答案
- **API 层**：只做参数校验与编排，算法交给纯函数模块
- **业务逻辑**：判分、阶段判定、掌握度、复习调度、题目审核均可在无网络下运行（本地兜底）
- **持久化**：一律经 SQLAlchemy ORM，数据以 `student_id` 归属，无鉴权
- **外部服务**：仅 DeepSeek HTTP API（`https://api.deepseek.com/chat/completions`，模型 `deepseek-chat`，超时 30s、无重试）；任何失败都降级到本地题库/规则/兜底题

# 6. Core Modules

### main.py（应用装配 + 核心闭环 API）

职责：创建 FastAPI 应用、注册 CORS 与路由、挂载 `/app` 静态目录；实现出题/判分/复习总览

入口：模块级 `app` 对象（无 `if __name__ == "__main__"`，由 uvicorn 加载）；路由函数 `home`、`students`、`question`、`submit`、`reviews`

依赖：`database`、`models`、`deepseek`、`grading`、`validator`、`ability`、`srs`、`stages`、`mastery`、`wrong_book`、`error_analysis`、`knowledge_tree`、`local_users`、两个 router

注意事项：建表、`ensure_schema`、`migrate_data`、`init_default_users`、`knowledge_tree.ensure_seeded/link_mastery`、`error_analysis.backfill(limit=200)` 全在 **import 期**执行（非 lifespan），多 worker 启动会重复执行

### stages.py（能力阶段模型）

职责：定义 72 个能力阶段（1.1~6.12，每年级 12 块：上册一~六 + 下册一~六）、0~71 线性坐标、难度值（15~95）、三科×72 知识点、阶段升降函数

入口：`all_keys`、`normalize_key`、`key_of`、`index_of`、`label`、`difficulty_of`、`knowledge_of`、`next_key`、`prev_key`、`advance`、`stars`

依赖：无（纯标准库）

注意事项：**全后端的能力阶段/知识点唯一来源**，改动会同时影响诊断、出题难度、知识点树与掌握度；`advance` 阈值 0.90 / 0.85 写死在此

### 能力诊断（diagnostic.py + diagnostic_routes.py + diagnostic_bank.py）

职责：阶段化动态诊断状态机与评分（`diagnostic.py` 纯函数）、诊断 REST 接口（`diagnostic_routes.py`，prefix `/api/diagnostic`）、分阶段题库（`diagnostic_bank.py`：数学程序化生成，语文/英语取 `bank_chinese` / `bank_english`）

入口：`diagnostic.new_state/record_answer/evaluate_stage/calculate_ability/build_report`；路由 `start`、`next_question`、`submit_answer`、`session_detail`、`profiles`、`report`、`list_stages`；`diagnostic_bank.build_question`

依赖：`stages`、`validator`、`deepseek`、`grading`、`error_analysis`、`knowledge_routes.update_mastery`、`models`

注意事项：诊断题只写 `diagnostic_records` 等诊断表，**不写 `answer_records`、不改 `abilities`**（避免污染日常练习统计）；参数写死在 `diagnostic.py`：每阶段 5 题、上限 60 题、优秀 0.90 / 通过 0.85 / 边界 0.60

### knowledge_routes.py（知识掌握 / 错因 / 错题本 / 知识树 API）

职责：prefix `/api`；掌握度明细与报告、错因统计与 AI 深化、错题本查询、知识点树与重新灌库；含掌握度落库函数 `update_mastery`

入口：`update_mastery`、`mastery_detail`、`knowledge_report`、`errors`、`analyze_error`、`wrong_questions`、`knowledge_tree_api`、`knowledge_sync`

依赖：`mastery`、`wrong_book`、`error_analysis`、`knowledge_tree`、`stages`、`models`

注意事项：`update_mastery` 被 `main.py /submit`、诊断答题、错题再练三处共用，是掌握度的唯一写入口；`ERROR_TIPS` 与 `error_analysis.SUGGESTIONS` 是两套文案

### mastery.py（掌握度模型）

职责：由某学生+科目+知识点的全部历史记录算出掌握度（0~100）、置信度、掌握等级、下次复习时间

入口：`MasteryEngine.calculate_mastery`、`level_of`、`confidence_of`、`next_review_time`；模块级 `DEFAULT_ENGINE`、`calculate`、`aggregate`

依赖：仅 `datetime`（纯函数）

注意事项：**每次按全部历史重算**（非累加），连错降档与时间衰减才会生效；题量收缩 `SHRINK_K=7.5`；掌握等级带与复习计划（熟练 +7 天等）写死在此

### srs.py（艾宾浩斯复习调度）

职责：维护每个知识点的复习阶段与间隔（11 级：5 分钟 → 120 天），决定何时到期、何时升级

入口：`review`、`state_from_row`、`apply_state`、`due_items`、`select_knowledge`、`mastery`、`is_due`

依赖：仅 `datetime`（纯函数）

注意事项：答错直接打回阶段 0；答对需**连续 3 次**才升一级；满级（10 级）视为长期掌握、退出复习队列；这里维护的 `reviews.next_review_at` 与 `wrong_questions.next_review_time` **是两套互不同步的时间**（见 §9）

### wrong_book.py（错题本状态机）

职责：错题登记与状态推进 NEW → LEARNING → MASTERED

入口：`record_wrong`、`record_correct`、`stats_for`、`items_for`；常量 `MASTER_STREAK=2`

依赖：`mastery`、`stages`、`datetime`

注意事项：「答对」按**同科目+同知识点**推进，练相似题同样算数；答错会把已 MASTERED 的错题退回 LEARNING

### error_analysis.py（错因分析）

职责：规则优先的错因判定（离线、瞬时），可选 AI 深化；提供统计与历史回填

入口：`analyze(db, ...)`、`rule_analyze`、`ai_analyze`、`summary`、`dominant_error`、`backfill`

依赖：`deepseek`、`grading.parse_options`、`models`

注意事项：`/submit` 与诊断答题**显式传 `use_ai=False`**，即主流程不调 AI；只有 `POST /api/error/analyze` 默认走 AI 深化；三科错误类型表在此

### 出题与质量审核（deepseek.py + validator.py）

职责：调用 DeepSeek 生成题目与解析（`deepseek.py`），并对生成题做格式/答案/难度/知识点/歧义审核（`validator.py`）

入口：`deepseek.generate_question`（可传 `history` 防雷同）、`deepseek.avoid_repeat_block`、`deepseek.analyze_error`、`deepseek.ability_block`；`question_dedupe.is_duplicate`；`QuestionValidator.validate`

依赖：`requests`、`re`、`unicodedata`

注意事项：无 API Key、异常或审核两次不合格时使用内置兜底题（`FALLBACK`），**绝不把不合格题目发给孩子**；题库自带题目跳过「知识点对不上」检查；审核结果随出题以 `audit` 字段返回；**出题防雷同**：`/question` 会把最近 6 道原题传给模型要求换数字/换情境，返回后再用 `question_dedupe.is_duplicate` 复核，命中就重出（最多 `MAX_GENERATION_ATTEMPTS=3` 次，全失败则发最后一版并标 `repeated`，**不因此退回兜底题**）；同知识点连续出题另由 `avoid_knowledge` + `repeat_penalty_of` 软避让（不硬禁，隔几道还能再练）

### grading.py（判分）

职责：服务端答案归一化与判定（选择题字母/内容、填空题可接受答案）

入口：`is_correct`、`normalize`、`parse_options`、`parse_acceptable`

依赖：`json`、`re`、`unicodedata`

注意事项：判分是唯一真相，前端不解答案；`questions.options` / `acceptable` 以 JSON 字符串存 Text 列

### knowledge_tree.py（知识点树）

职责：定义三科 284 节点知识点树（3 科目根 + 16 章节领域 + 216 知识点 + 49 子知识点）、启动灌库、与掌握度关联

入口：`seed`、`ensure_seeded`、`link_mastery`、`node_rows`、`domains_for`

依赖：`stages`

注意事项：每科 72 个知识点必须与 `stages.py` 的 72 阶段逐一对应，`seed()` 时缺一会直接报错；原 24 个大知识点固定在每年级第 1/4/7/10 块，细分块的知识点名称不得与 `SUBPOINTS` 同名；节点数据硬编码在本文件

### adaptive/（自适应学习引擎，V2.3）

职责：根据能力阶段、知识掌握度、错因与历史表现，自动决定「学什么知识点、出什么难度、下一题是什么、什么时候升降难度、今天怎么安排」，形成闭环

入口：`adaptive_routes.py`（`/api/learning/*`）→ `adaptive.engine.DEFAULT_ENGINE`；
算法层为纯函数：`strategy.DEFAULT_STRATEGY.rank/choose`、`difficulty.DEFAULT_CONTROLLER.adjust`、`selector.DEFAULT_SELECTOR.select`、`planner.DEFAULT_PLANNER.build/ensure`

依赖：`knowledge_routes._mastery_items`（知识点+掌握度合成视图）、`error_analysis`、`stages`、`knowledge_tree`、`mastery`、`models`

注意事项：

- **难度状态不落库**：连对/连错/最近 10 题正确率由 `answer_records` 现算，避免状态表与实际记录不一致
- **依赖门控**只在"前置练过、掌握度 <70、且比当前项更薄弱"时生效（没练过 ≠ 没学会）
- 主观感受 `feel` 只在最近 2 小时内影响难度（`engine.FEEL_WINDOW_HOURS`）
- `next-question` 在函数内 `import main` 复用出题逻辑（避免循环导入），`main.question` 因此新增可选参数 `difficulty`（0 = 不指定，走原有规则）
- `learning_plan` 按 `(student_id, date, subject, knowledge_id)` 唯一，`ensure()` 幂等；不在新计划里的空计划标记 `expired`
- 新增知识点要同时改三处：`stages.KNOWLEDGE`、`knowledge_tree.DOMAINS`、`strategy.DEPENDENCIES`

### review/（间隔复习系统，V2.4）

职责：回答"学会了之后怎么不忘"——每个学生每个知识点的记忆状态、遗忘风险、下次复习时间、复习题量与题型、复习成败后的间隔调整

入口：`review_routes.py`（`/api/review/*`）→ `review.engine.DEFAULT_ENGINE`；
算法层纯函数：`memory`（成熟度/记忆强度）、`forgetting.calculate_forgetting_risk`、`interval.calculate_next_interval`、`scheduler.build_queue`、`selector.ReviewQuestionSelector`、`mix.calculate_daily_mix`

依赖：`grading`、`knowledge_routes.update_mastery`、`error_analysis`、`wrong_book`、`diagnostic_bank`（复习题来源）、`stages`、`knowledge_tree`；`adaptive.strategy.foundation_weight` 由调用方传入（延迟导入，避免与 adaptive 循环依赖）

注意事项：

- **间隔算法是两段式**：前 4 次走阶梯 1/3/7/14/30（GOOD 正好命中需求数字），之后进入稳定性驱动；间隔恒在 1~180 天
- **复习答题也写 `answer_records`**，掌握度/错因/错题本与日常练习完全同一套链路
- **风险增量刷新**：只有变化 ≥0.05 或已到期的记录才写库；**队列按天缓存**（同一天不重排，`?refresh=true` 才重排）
- **长期掌握偶尔错 1 题不重置**：只压缩间隔 + 追加 `need_verify` 验证题；连续失败 2 次或掌握度 <60 才转 `RELEARN`
- **复习题不能重复旧题**：AI（可选）→ `diagnostic_bank.build_question(avoid=历史题)` → 兜底变式；生成后统一过 `selector.is_duplicate` 检测（数字变了不算重复）
- 儿童端（`review.html`）**不显示**遗忘风险/稳定性等指标，只有"浇水/树的成长"；真实数据在 `memory_debug.html`
- 迁移入口：`review.engine.ensure_states(db)`（启动时对全部学生幂等执行），分档见 §8 决策

### verify_all.py（验证编排）

职责：串行跑 8 个验证套件（review / flow / web / diagnostic / diagweb / knowledge / knowweb / phoebeweb），只输出 `RESULT: ALL PASS` 或 `HAS FAILURES` 并用退出码表达

入口：`python backend/verify_all.py`（可跟套件名跑子集）

依赖：`subprocess`，内部用绝对路径

注意事项：每套件先查端口占用（占用即 FAIL 跳过，避免连上别人的服务造成"假通过"）；单套件超时 300s；不含 `verify_port_guard.py`

# 7. Current Status

## Completed

- V1.5：教材知识库结构、DeepSeek 自动出题、自适应难度、XP/金币/连续学习/宠物/成就（激励部分见 §9 遗留说明）
- V2.1：艾宾浩斯复习闭环（`srs.py` + `/reviews` + 复习面板）、浏览器语音朗读题目与解析
- V2.2：24 阶段能力诊断系统（动态诊断算法、能力评分与星级、`ability_profile`、诊断三页、`verify_diagnostic.py` + `verify_diagnostic_web.js`）
- V2.3：知识点树（139 节点）、MasteryEngine 掌握度、错因分析、错题本、题目质量审核、V2.2→V2.3 数据库迁移、知识三页、`verify_knowledge.py` + `verify_knowledge_web.js`
- V2.3 自适应学习引擎：`adaptive/` 五模块（策略/难度/选题/计划/门面）、`adaptive_routes.py` 6 个接口、`learning_plan` + `learning_strategy_log` + `learning_feedback` 三张表、今日学习页 + 学习反馈页（`today.html` / `today.js`）、`verify_adaptive.py` + `verify_adaptive_web.js`
- V2.4 间隔复习系统：`review/` 七模块（记忆状态/遗忘风险/间隔计算/调度/选题/配比/门面）、`review_routes.py` 9 个接口、`knowledge_memory_state` + `review_records` + `review_queue` + `review_strategy_log` 四张表、儿童端知识浇水页 + 家长端记忆数据页、每日计划接入 50/30/20 配比、`verify_memory.py`（145 项）+ `verify_memory_web.js`（60 项）
- 本地双用户模型与数据隔离（默认「朵朵」「童童」；旧默认名「小朋友A/B」在启动时幂等改名）
- V2.6 需求调整（2026-10-05）：默认学生改名朵朵/童童；「开始今日学习」由本页出题改为**整页跳转**到 `index.html?student_id&subject&knowledge&from=today&autostart=1`；自由练习页与今日学习页都按已掌握知识**自动选知识点**（`frontend/app.js` 的 `pickKnowledge/applyAutoKnowledge` + `adaptive/strategy.rank` 的阶段适配加成）；能力阶段由 24 扩到 **每科 72 块**（每年级 12 块：上册一~六 + 下册一~六，对应人教版单元）
- 全量验证入口可用：8 个套件实测 `RESULT: ALL PASS`（合计 73.6s，退出码 0，见 §10）
- V2.8（2026-10-05）：积分系统（`points.py` + `points_routes.py` + 两张表 + 首页积分卡与商城占位）；**商城页 `frontend/shop.html` + `shop.js` 挂在一级导航第 4 项（右侧「挑战」下方），内含商品与第一版奖励行为明细（`backend/points_rewards.py`，`summary()` 返回 `rewards`），一级导航由 4 项扩到 5 项**；**每日首次登录自动 +10（`POST /api/points/{id}/login`，幂等），「每日打卡」不再手动点、改由当天小任务全部收工后自动生成（`points.plan_finished`，`award_after_answer` / `award_task_done` 两处结算）**；不再出需要配图的题（`deepseek.py` 提示词 + `validator._check_image_dependency`）；版本号唯一真相 `version.json` + 启动时对比 GitHub 仓库自动更新（`updater.py` / `update_check.py` / `start.bat`）+ `tools/publish.py` 打包上传

## In Progress

- 无未完成的在建项；`docs/TODO_V1.6-V2.0.md` 的勾选状态滞后于代码（见 §9）

## Pending

- 能力雷达图（V2.2/V2.3 文档明确列出；当前用知识点条形图 + 星级代替）
- 错因趋势图（按周看某类错误是否减少）、掌握度历史曲线
- 家长端周报/学习报告页（自适应策略日志已可通过 `/api/learning/strategy-log/{id}`、
  复习算法日志可通过 `/api/review/strategy-log/{id}` 查看，尚无独立报告页）
- 知识森林可视化（V2.6 预留；后端已输出 `forest` / `forest_icon` 字段，本版本只做卡片展示）
- 复习日历与记忆衰减曲线（数据已齐全：`review_records` + `knowledge_memory_state`，缺展示）
- 知识点库已扩到每科 72 块（每年级 12 块，对应人教版单元）；细分阶段暂用 `stages.legacy_key` 取大知识点题库兜底，可继续补细分阶段自有题目
- 语文/英语分阶段题库扩容（当前每阶段 6 题，目标 10 题以上）
- 激励机制（XP/金币/宠物/成就）真正接线（见 §9）
- AI 出题 A/B 质量评估（记录审核拦截率与题型分布）

# 8. Important Decisions

### 2026-10-05 能力阶段从 24 扩到 72（每年级 12 块）

决定：`stages.LEVELS` 改为每年级 12 块（上册一~六 + 下册一~六），`MAX_INDEX = 71`；原 24 个大知识点**固定在每年级第 1/4/7/10 块**，其余 48 块是新细分内容（每科 72 个知识点，共 216 个）。

原因：用户要求「小学课程更精细、涵盖全部教材章节」；保留大知识点的原名称与原有 24 个键位语义，旧库的 `student_knowledge_mastery` / `answer_records.knowledge` 不丢数据。

影响：
- 细分阶段还没有自有题库，`diagnostic_bank._bank_pool/_math_maker` 用 `stages.legacy_key(key)`（新块 → 旧 4 等级键）取大知识点题库兜底；`adaptive/strategy.prerequisites` 对没有显式依赖的新块按教材顺序依赖上一块。
- `diagnostic.QUESTIONS_PER_STAGE` 保持 5（试过 3：3 题全对的 mastery=64 <70 会产生「假短板」；5 题全对 mastery=70 刚好达标）。
- `stages.advance` 满分从「跳级」改为跳过一个大知识点的剩余两块（+3），其余 +1。
- `knowledge_tree.ensure_seeded` 改为每次都跑幂等 `seed()`（否则旧库不会补上新增的 145 个节点）；真实库已从 139 节点补到 284 节点。
- 旧库 `student_knowledge_mastery.stage` 里的旧键值不主动迁移，下次作答重算时自愈。

> 日期依据 `docs/*.md` 文件修改时间（均为 2026-10-04）；文档正文未标注决策日期。

### 2026-10-04 能力用 24 阶段表示，而不是学生自报年级

决定：能力以「年级.等级」24 阶段坐标表达，起点固定 1.1，按答题表现上探/回退

原因：只看答出来的表现；四年级孩子若只会 20 以内加减法，就应如实报告为一年级基础

影响：诊断、出题难度、知识点树、掌握度全部围绕 `stages.py`；改动该文件影响面最大

### 2026-10-04 能力分与掌握度分开计算

决定：能力分 = 0.5×阶段基准分 + 0.5×加权正确率×100（每题权重 1+难度/100）；掌握度（V2.2 口径）= 该知识点正确率，不减难度分

原因：避免"一年级全对"被显示成 95 分而凭空产生假短板；难度信息交给能力阶段单独表达

影响：两套分数并存且含义不同，读代码时不可混用

### 2026-10-04 所有生成题目保存前必须过审

决定：本地题库与 AI 生成题入库前一律过 `QuestionValidator`，不合格重试一次，仍不合格用内置兜底题

原因：绝不把错题发给孩子

影响：出题路径较长（生成 → 审核 → 兜底），解题/排查出题问题需沿这条链看

### 2026-10-04 诊断题只写诊断表

决定：诊断答题只写 `diagnostic_records` 等诊断表，不写 `answer_records`、不改 `abilities`

原因：不污染日常练习的统计与能力数据

影响：诊断与练习是两套独立数据；能力画像 `ability_profile` 用 `source` 区分来源

### 2026-10-04 错因分析规则优先、AI 可选

决定：答错先由本地规则瞬时判定并落库；`POST /api/error/analyze` 再可选走 AI 深化

原因：`/submit` 不能被网络阻塞，也不能依赖外网

影响：主流程默认 `use_ai=False`（容易误判为"AI 错因没生效"）；三科错误类型与建议文案需分别维护

### 2026-10-04 复习采用艾宾浩斯 11 级间隔，答对连续 3 次才升级

决定：`srs.py` 维护 5 分钟~120 天共 11 级间隔，答对连续 3 次升一级，答错直接回阶段 0

原因：避免"蒙对一次就拉长间隔"

影响：`reviews` 表的 stage/streak/next_review_at 是复习调度的核心状态，不要手工改

### 2026-10-04 数据库演进用补列 + 幂等回填，不重建

决定：`ensure_schema` 按表 `PRAGMA table_info` 缺失列则 `ALTER TABLE ADD COLUMN`；`migrate_data` 做幂等 UPDATE；旧列保留

原因：不重建、不丢数据、随时可回退；老库首次启动自动迁移

影响：属高风险改动（AI_RULES.md 将 migration 列入需扩大验证范围）；回填只处理最近 200 条；迁移失败被 `except` 吞掉，不阻塞启动（排查问题时注意这点）

### 2026-10-04 测试统一入口 + 独立端口 + 端口占用即失败

决定：`verify_all.py` 串行编排 8 个套件，各用独立端口与临时库；端口被占用时立刻失败

原因：避免连上别人的服务跑出"假通过"；跑完不留残留进程与临时库

影响：跑测试前不要占用 8899/8900/8902/8904；`verify_port_guard.py` 与全量测试不能并行

### 2026-10-04 前端不引入框架与构建

决定：原生 HTML/CSS/JS，无 npm、无 bundler、无 CDN，由后端 `/app` 直接挂载

原因：本地单机、零构建部署，双击 `start.bat` 即用

影响：没有构建产物可查，改完前端必须强制刷新；公共工具函数在各 js 中重复实现

### 2026-10-04 数据不引入账号系统

决定：不做登录鉴权，所有数据以 `student_id` 归属（接口默认 1）

原因：家庭本地自用

影响：接口无身份校验，不可直接暴露到公网

### 2026-10（V2.3 自适应）难度状态不建表，全部由答题记录现算

决定：连对/连错、最近 10 题正确率都在 `AdaptiveLearningEngine.difficulty_state` 里由 `answer_records` 现算

原因：避免"状态表与实际答题记录不一致"的经典 bug，也让难度算法可独立单测

影响：每次决策多一次 20 条记录的查询（量级可忽略）；难度只与记录有关，可随时重放

### 2026-10（V2.3 自适应）知识点依赖用显式表，不从阶段顺序推导

决定：`strategy.DEPENDENCIES` 手写三科共 69 条依赖边，并实现"先补基础"的依赖门控

原因：阶段顺序只表示出题难度递增，不代表学习先后（"长度单位与测量"与"表内乘法"互不依赖）

影响：新增知识点必须同步补依赖；门控只在"前置练过且 <70 且比当前项更薄弱"时生效

### 2026-10（V2.3 自适应）主观难度感受只认最近 2 小时

决定：`learning_feedback.feel` 影响难度，但 `engine.FEEL_WINDOW_HOURS = 2` 之外的历史反馈不再参与

原因：防止几天前一次"有点难"反复拉低难度，导致难度漂移

影响：窗口常量是唯一调节点；`feedback` 接口同时返回 `next_difficulty` 供前端展示

### 2026-10（V2.3 自适应）出题复用主流程，只新增难度覆盖参数

决定：`/api/learning/next-question` 内部调用 `main.question`，`main.question` 新增可选 `difficulty`（0 = 不指定）

原因：题库、质量审核、兜底题、复习面板逻辑不重复实现（Minimal Diff）

影响：改 `main.question` 签名时，`adaptive_routes.learning_next_question` 是唯一外部调用方

### 2026-10（V2.3 自适应）新增第三张表 learning_feedback

决定：需求只列了 `learning_plan` 与 `learning_strategy_log`，这里额外增加 `learning_feedback`

原因："难度感受"是难度模型的重要输入，塞进策略日志会让语义混乱

影响：多一张小表；`create_all` 自动建，无迁移成本

### 2026-10（V2.4 间隔复习）间隔算法用"阶梯 + 稳定性"两段式

决定：前 4 次复习成功走固定阶梯 1/3/7/14/30，之后才交给稳定性驱动的乘数公式

原因：既要满足需求的阶梯数字，又要让长期复习能动态扩大（避免永远 30 天上限）

影响：`interval.calculate_next_interval` 返回 `segment` 字段区分阶段；阶梯阶段刻意不叠乘其它因子，保证 GOOD 序列可预期

### 2026-10（V2.4 间隔复习）遗忘风险增量刷新 + 队列按天缓存

决定：风险只在变化 ≥0.05 或已到期时写库；今日队列落 `review_queue`，同一天不重排

原因：性能要求——不能每次打开页面都重算全部知识点

影响：跨天自动重排；同一天想强制重排要用 `/api/review/today/{id}?refresh=true`

### 2026-10（V2.4 间隔复习）长期掌握的知识偶尔错 1 题不重置

决定：`STABLE`/`LONG_TERM` 首次答错只压缩间隔、降低稳定性并追加 1 道验证题；连续失败 2 次或掌握度 <60 才转 `RELEARN`

原因：一次偶发错误不等于遗忘，直接降档会让孩子的努力白费

影响：`submit_review` 返回 `need_verify`；RELEARN 的知识点不进复习队列，交给自适应引擎重学

### 2026-10（V2.4 间隔复习）复习题走"AI → 题库 → 兜底变式"三级

决定：优先 AI（带历史原题约束），其次 `diagnostic_bank.build_question(avoid=历史题)`，最后兜底题换数字；生成后统一做重复检测

原因：复习要考迁移，不能让孩子背答案；同时离线也必须可用

影响：`selector.is_duplicate` 用"数字序列 + 文字相似度"判定，换数字不算重复；数学靠生成器天然不重复，语文/英语靠题库轮换

### 2026-10（V2.4 间隔复习）复习答题复用主流程数据

决定：`/api/review/answer` 也写 `answer_records` 并调用 `knowledge_routes.update_mastery`

原因：掌握度、错因、错题本、统计只应有一套真相

影响：复习数据与日常练习在同一张表，诊断/报告页自动包含复习表现

### 2026-10（架构重构）用 mixin 切片 + 契约卡 + 能力索引表降低维护成本

决定：按「能力切片 + 文件头契约卡 + `docs/MODULE_MAP.md` 能力索引表」组织代码；数据库门面类（ReviewEngine / AdaptiveLearningEngine）用 mixin 组合拆分

原因：单文件最大 952 行（`review/engine.py`，25 个方法，最长方法 `submit_review` 172 行），定位代码需跨文件反复读取，token 与时间成本高

影响：新增硬约束 **单文件 ≤250 行**；每个模块文件头必须有契约卡（职责/入口/依赖/不负责/验证/被调用）；新增或改名模块**必须**同步 `docs/MODULE_MAP.md`；阶段计划见 `docs/架构重构_Mixin方案.md`（**P0 + P1 已完成**）

### 2026-10（架构重构）死代码归档而不是删除

决定：`adaptive.py` / `algorithm.py` / `ai_question.py` / `reward.py` 移入 `backend/_legacy/`（保留不删除）

原因：项目**无 git**，删除不可回退；且 `adaptive.py` 与 `adaptive/` 子包同名，留在根目录会误导 agent 定位代码

影响：`backend/` 根目录保持「每个文件都是活的」；`_legacy/` 内文件禁止接线、禁止复制回根目录

### 2026-10-05 出题难度与能力评价锚定「知识点固有难度」（修复「评价五年级、练习一年级」）

决定：
- `main.question` 无诊断画像时，出题难度 = `0.5 × ability.score + 0.5 × knowledge_tree.difficulty_of(知识点)`（与 `adaptive/strategy.suggest_difficulty` 的 base 同口径）。
- `/submit` 的能力分加上限 `知识点固有难度 + ABILITY_CEILING_MARGIN(15)`，不再靠简单题的高正确率一路顶到 100。
- `auto_ability` 每条答题记录的 difficulty 先与知识点固有难度取小（知识树查得到才取），能力评价只认真实练的知识点。
- `adaptive/strategy.rank`：阶段适配度改为按「这个知识点有没有练过」判断；新增 `SATURATION_TOTAL=12` / `SATURATION_MASTERY=60`，练够题的薄弱项不再无限霸榜、也不再当拦路虎。

原因：难度分由全局正确率单调上抬并写入 `answer_records`，`/question` 又直接拿它当难度，`auto_ability` 再把这份难度平均成「能力水平」—— 三个环节互相印证，结果是一年级知识点被标成难度 100、孩子被评成「五年级下册六」，而每日练习永远停在一年级。

影响：历史 `answer_records.difficulty` 仍偏高，但能力评价取小后立即回归真实（真实库朵朵数学 81.8/五年级 → 17.2/一年级上册三）；出题难度不再虚标。

### 2026-10-05 「我的」页新增家长端「备份并重置」

决定：新增 `backend/user_routes.py`（`GET /api/user/{student_id}/reset-preview`、`POST /api/user/{student_id}/reset`）与「我的」页家长操作区（`frontend/profile.js`）。**先备份、后清空**：备份 JSON 落在 `backup/user_reset/<名字>_<id>_<时间戳>.json`，写失败直接 500 且**不清空任何数据**；只清空含 `student_id` 的 20 张表，`students` 行本身**保留**；重置前必须在前端二次确认（复用 `.ph-confirm`）。

原因：家长需要一个「把孩子数据清零、重新开始」的入口，但不能误点、不能丢数据。

影响：新增第 24 个验证套件 `userreset`（端口 8914）；改动后跑 `python backend/verify_all.py userreset growthweb`。

### 2026-10-05 儿童端三项体验升级（combo 及时反馈 / 学习日历 / 目标时长自适应）

决定：
- **及时反馈**：`frontend/today.js` 新增 `comboLevel` / `comboHtml`（连对 ≥2 起显示 `COMBO ×N` 浮层，3 / 5 / 8 三档），样式在 `frontend/style.css` 的 `.ph-combo` + `@keyframes ph-combo-pop`；答对仍自动跳下一题、完成当日任务仍进今日完成卡。
- **学习日历**：`backend/habit.py` 新增 `calendar()`（打卡 = 当天有完成的任务，完成即自动打卡），`backend/habit_routes.py` 新增 `GET /api/habit/calendar`（`month=YYYY-MM`，非法 400）；`frontend/growth.html` + `growth.js` 新增日历区块 `renderCalendar`。
- **目标时长自适应**：`learning_habit_profile` 加列 `target_minutes` / `target_synced_date`；`habit.next_target_minutes` 纯函数（首次 10 分钟；签到 +2~5，连续越久加得越多；断签 −5~8，漏得越久减得越狠；恒在 10~40）；`plan()` 不再按年级写死时长，`refresh()` 在「今天首次完成学习任务」时签到上调，`_sync_target()` 每天只结算一次漏签（幂等）。

原因：孩子需要马上知道「我做对了 / 我连对了好几题 / 我今天打成卡了」；每日目标时长应该随坚持情况长起来，而不是按年级一刀切。

影响：`plan()` 返回的 `min_minutes` / `max_minutes` 从年级区间改为 10 / 40，`verify_habit.py` 与 `verify_active_recall.py` 的时长断言已同步（共 11 条新断言）；改 `frontend/growth.js` / `growth.html` 后跑 `python backend/verify_all.py growthweb`，改 `today.js` / `style.css` 后跑 `v26web`。

# 9. Known Issues

### docs/TODO 勾选状态滞后于代码

问题：`docs/TODO_V1.6-V2.0.md` 中「错题本」「完整知识点数据库」「一年级-六年级教材结构」仍标未完成，实际 V2.3 已实现；V1.8 区块标题写"待完成"但内部多为 `[x]`

影响：按 TODO 估工作量会重复劳动

解决方案：以代码与 V2.3 文档为准，需要时回勾 TODO

### 三套「下次复习时间」并存且互不同步

问题：`reviews.next_review_at`（V2.1 srs.py 调度）、`knowledge_memory_state.next_review_at`（V2.4 记忆状态）、
`wrong_questions.next_review_time`（mastery 计划）三处各自维护

影响：同一知识点在复习面板、知识浇水页、错题本中可能显示不同的下次复习时间

解决方案：**以 V2.4 `knowledge_memory_state` 为准**（`/api/review/*` 全部读它）；
V2.1 艾宾浩斯面板保留兼容但不再扩展；改动任一侧前先确认是否需要统一

### 掌握度口径在 V2.2 与 V2.3 之间变化且文档未同步

问题：V2.2 文档定义掌握度 = 正确率；V2.3 的 MasteryEngine 改为难度加权 + 题量收缩 + 连错惩罚，但 V2.2 文档未回改

影响：对照文档理解掌握度数值会得出错误结论

解决方案：以 `mastery.py` 实现为准

### 激励系统（XP/金币/宠物/成就）实际未接线

问题：V1.5 文档称已新增，TODO 的 V2.5 仍列为未完成；`reward.py` 全项目无人 import，且其读写的 `Student.experience/coins/pet_level/streak` 列在 `models.py` 中不存在

影响：一旦接线会直接 `AttributeError`；`frontend/phoebe.js`（庆祝浮层）是唯一实际生效的激励类功能

解决方案：接线前先补 `Student` 列或重写 `reward.py`

### 未接线死代码（已归档）

问题：`adaptive.py`、`algorithm.py`、`ai_question.py`、`reward.py` 无任何 import；`ai_question.py` 内含硬编码占位密钥 `YOUR_DEEPSEEK_KEY`

影响：曾易被误读为生效逻辑；特别注意 **`backend/adaptive.py`（旧文件）与 `backend/adaptive/`（V2.3 自适应子包，已接线）同名但无关**

解决方案：**已归档到 `backend/_legacy/`**（架构重构 P1），归档前经全项目 grep 复验零引用；**保留不删除、禁止接线**，详见 `backend/_legacy/README.md` 与 §8「架构重构用 mixin 切片」决策

### 验证脚本在 GBK 控制台会因 emoji 报 UnicodeEncodeError

问题：重定向到文件或部分终端下，`verify_adaptive.py` / `verify_memory.py` 打印 😊 等字符会抛 `UnicodeEncodeError`

影响：整个套件中途中断（断言本身未必失败）

解决方案：脚本内已用 `if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 规避，新增带 emoji 的脚本请沿用

### 复习队列会"顺延"，不是丢了

问题：一天最多排 15 个复习任务，超出的写入后续日期（`review_queue.scheduled_at = 明天起`）

影响：长期没登录后，即使有 40 个到期知识点，儿童端也只看到 15 个；剩余的在后面几天陆续出现

解决方案：设计如此（保护孩子）；家长端 `/api/review/due/{id}` 能看到全部到期项

### data/ 目录未被任何代码引用

问题：`data/curriculum.json`（3 科 6 年级清单）与 `data/changsha_primary_math.json`（仅 2 条教材记录）在 backend / frontend 中 grep 不到引用；真实生效的知识点与题库全在 Python 内

影响：改这两个文件不会改变系统行为

解决方案：未定；若要与 V1.5 的"教材知识库"目标对齐，需真正接入

### 前端静态资源无缓存版本控制

问题：后端静态挂载未设置 `Cache-Control`，页面也没有 `?v=` 查询串

影响：改完 JS/CSS 后浏览器可能仍用旧文件，最容易误判为"改了没生效"

解决方案：改动前端后强制刷新（Ctrl+F5）

### 主流程默认不调用 AI 错因

问题：`/submit` 与 `/api/diagnostic/answer` 均显式 `use_ai=False`，只有 `POST /api/error/analyze` 默认 `use_ai=True`；`use_ai` 内部还会二次判断

影响：误以为 AI 错因失效或未配置

解决方案：以 `source` 字段（rule / ai）判断实际来源

### 接口无鉴权、无越权校验

问题：所有接口仅凭 `student_id` 查询，未做任何身份校验

影响：家庭自用可接受，但不可将服务暴露到公网

解决方案：设计如此；如要外网访问需先补鉴权

### 语音朗读依赖系统中文语音包

问题：前端用浏览器 `speechSynthesis`；找不到中文音色时回退系统默认音色

影响：Windows 上若未安装中文语音，会把内容按英文读（拼音易读错）

解决方案：在系统「设置 → 时间和语言 → 语音」添加中文语音

### 出题依赖外部接口时约 1.3s/题

问题：无 `DEEPSEEK_API_KEY` 时走内置兜底题（快），有 key 时走 HTTP 生成

影响：出题是全流程最慢一环，验证脚本已避免重复出题

解决方案：性能敏感场景优先使用题库/兜底题

# 10. Validation Commands

只记录真实存在、已实测可用的命令。项目**无** linter、无 type checker、无 pytest。

**实测基线（2026-10-04）**：`python backend/verify_all.py` → `RESULT: ALL PASS（合计 73.6s）`，退出码 0。各套件耗时：复习闭环 9.8s、学习闭环回归 11.2s、前端语音/复习 0.1s、能力诊断引擎 12.7s、前端诊断页 0.3s、知识掌握与错因 39.3s、前端知识地图/错题本 0.2s、菲比庆祝 0.1s。改动后若耗时显著偏离（尤其知识套件 39s），需留意是否引入了额外出题/网络调用。

**V2.3 自适应新增（实测）**：`verify_adaptive.py` → `ALL PASS（110 PASS / 0 FAIL）`；`verify_adaptive_web.js` → `ALL PASS（41 项）`；回归 `verify_knowledge.py` → `ALL PASS（112 PASS / 0 FAIL）`。加入 `verify_all.py` 后全量为 10 个套件（新增 `adaptive` 端口 8905、`adaptweb` 无端口）。

**V2.4 间隔复习新增（实测）**：`verify_memory.py` → `ALL PASS（145 PASS / 0 FAIL）`；`verify_memory_web.js` → `ALL PASS（60 项）`；`verify_all.py memory memweb` → `ALL PASS（合计 8.0s）`；回归 `verify_adaptive.py`、`verify_knowledge.py`、其余 4 个前端套件全部通过。加入 `verify_all.py` 后全量为 12 个套件（新增 `memory` 端口 8906、`memweb` 无端口）。

**V2.5 菲比互动 + 自动能力诊断新增（实测，2026-10-04）**：`python backend\verify_all.py` → `RESULT: ALL PASS（合计 108.4s）`，退出码 0，全量 **15 个套件**。各套件耗时：复习闭环 9.2s、学习闭环回归 10.8s、前端语音/复习 0.1s、能力诊断引擎 12.2s、前端诊断页 0.3s、知识掌握与错因 37.3s、前端知识地图/错题本 0.2s、自适应引擎 18.1s、前端今日学习 0.2s、间隔复习 8.5s、前端知识浇水 0.3s、菲比庆祝 0.1s、**菲比三视图立牌 0.1s**、**训练数据自动能力诊断 10.9s**、**前端能力水平页 0.2s**。
新增套件单独实测：`verify_ability.py` → `ALL PASS（90 项断言，端口 8907）`；`verify_phoebe3d_web.js` → `ALL PASS（71 项）`；`verify_ability_web.js` → `ALL PASS（29 项）`；`check_cards.py` → `校验模块数 73 / 失实符号 0`。
端到端（真实 uvicorn + 临时库 + 8011 端口，非 8000）29 项全通过：`/` 版本 2.5、12 个页面/静态资源与三视图 PNG 全部 200、`/api/ability/auto/1` 无记录时三科 `unknown`、真实 `/question` + `/submit` 后自动诊断为 `warming` 并给出中文依据。
**V2.5 第二轮（菲比 AI 陪伴 + 立牌改位，实测 2026-10-04）**：`python backend\verify_all.py` → `RESULT: ALL PASS（合计 114.8s，复跑 110.3s）`，退出码 0，全量 **16 个套件**（新增 `phoebeai` 端口 8908）。另外单独实测：`verify_phoebe_ai.py` → `ALL PASS（59 项断言，强制离线不联网）`；`verify_phoebe3d_web.js` → `ALL PASS（83 项，含"点击触发 AI / 失败兜底 / 固定在左侧 / 鼠标不改变位置"）`。
**真实 DeepSeek 链路实测（非打桩）**：临时后端 + 临时库 + 真实 `.env` key，`POST /api/phoebe/chat` 三种触发全部 `source=ai`，耗时 click 760ms / correct 833ms / wrong 656ms，台词样例——"今天你答对六道题真棒，数学两位数除法有点不稳，错题本里还有一道等着你一起看看呢。"（确实结合了当日题量、薄弱知识点与错题数，没有编造）。
**V2.5 第三轮（菲比「6 情绪 × 3 视角」表情立牌 + 表头改「菲比同学」，实测 2026-10-04）**：`python backend\verify_all.py` → `RESULT: ALL PASS（合计 110.7s）`，退出码 0，全量 **16 个套件**。
`verify_phoebe3d_web.js` 由 83 项增至 **116 项断言**（新增：18 张素材齐全 / 画布统一 338×210 / manifest 声明 6 情绪 / 切表情与预载失败降级 / 答对→开心·连对≥2→点赞·答错→难过·错题本再练→加油 / 空闲 60s→鼓励 / 立牌按素材接近 1:1 显示 322×200 + 窄屏断点 / wrong_book.html 接入 / 11 个页面表头是「菲比同学」）。
素材 18 张由 `python tools/crop_phoebe3d_sheet.py` 从 `frontend/assets/phoebe3d/source.png`（1536×1024 宫格图）一次性离线裁出；旧的三视图素材已移到 `backup/phoebe3d_v25_assets/` 备查。
`start.bat` 的自动开网页链路用"写文件代替真的开浏览器"验证通过：`start "" powershell -WindowStyle Hidden -Command "... '%APP_URL%'"` 能正确展开并执行。

**注意**：后端套件必须用系统 Python（`C:\Python313\python.exe`，已装 `requests`/`fastapi`）；DSH 捆绑 Python 没有项目依赖，会直接 `ModuleNotFoundError: requests`。

### Fast Check

```bash
python backend/verify_flow.py --self-serve
```

P0 冒烟：库结构、判分、出题不泄漏答案、作答落库、能力更新、难度自适应、填空、跨域、异常兜底。端口 8900，用临时库。**不要**省略 `--self-serve`——默认模式会连 `127.0.0.1:8000` 并真实写入 `backend/learning.db`。

### Unit Test

```bash
python backend/verify_review.py
python backend/verify_diagnostic.py
python backend/verify_knowledge.py
python backend/verify_adaptive.py
python backend/verify_memory.py
python backend/verify_port_guard.py
```

按模块的验证脚本（各自拉临时后端 + 临时库）：复习闭环（8899）、诊断引擎（8902）、知识/错因/错题/审核（8904）、自适应学习引擎（8905，110 项断言）、间隔复习系统（8906，145 项断言）、端口占用保护（单独跑，与全量测试互斥）。

### Lint

```bash
（项目未引入 linter）
```

### Type Check

```bash
（项目未引入 type checker）
```

### Full Test

```bash
python backend/verify_all.py
```

全量入口：串行跑 16 个套件，不需要预先启动后端。子集写法：`python backend/verify_all.py knowledge knowweb adaptive adaptweb memory memweb ability abilityweb phoebe3dweb phoebeai`。

### 版本对比与自动更新（V2.8）

```bash
python backend/update_check.py --self-test   # 离线自检（版本比较 / 保护名单 / 临时目录试同步 / 启动接线）
python backend/update_check.py               # 只对比仓库版本号（本机 version.json vs GitHub）
python backend/update_check.py --apply       # start.bat 每次启动跑的就是这条：有新版本就覆盖代码文件
python tools/publish.py --dry-run            # 发版前本地打包 dist/learning-<版本>.zip
python tools/publish.py --push               # 真正上传（需 GITHUB_TOKEN 或 tools/.github_token）
```

### 前端逻辑测试（需要 Node）

```bash
node frontend/verify_web.js
node frontend/verify_diagnostic_web.js
node frontend/verify_knowledge_web.js
node frontend/verify_adaptive_web.js
node frontend/verify_memory_web.js
node frontend/verify_phoebe_web.js
```

不需要浏览器和后端（fetch 全部打桩）、不写文件。若 PATH 中没有 node，用绝对路径 `C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`，或直接跑 `verify_all.py`（它内部会优先选该 node）。

### 启动服务

```bash
start.bat
```

固定 8000 端口：已在本机运行且局域网可达则直接打开浏览器并退出；否则 `cd backend` 后执行 `python -m uvicorn main:app --host 0.0.0.0 --port 8000`。本机访问 `http://127.0.0.1:8000/app/`；手机/平板连同一个 Wi-Fi，访问 `http://<本机局域网IP>:8000/app/`（脚本启动时会打印这个地址；第一次运行需在 Windows 防火墙弹窗里允许 python 访问“专用网络”）

### V2.6 需求调整（实测后补）

**72 阶段能力模型 + 三条需求改动（实测）**：`python backend\verify_all.py` → `RESULT: ALL PASS（合计 114.0s）`，退出码 0，仍为 **16 个套件**。
单独实测：`verify_diagnostic.py` → `ALL PASS（72 阶段模型 / 三科每阶段都能出题 / 阶段字典 72）`；`verify_knowledge.py` → `ALL PASS（每科 72 知识点 / 284 节点知识树 / 「/api/mastery」返回 72 条）`；`verify_ability.py` → `ALL PASS（90 项断言）`；`verify_adaptive.py`、`verify_memory.py`、`verify_flow.py --self-serve`、`verify_phoebe_ai.py`（59 项）均 `ALL PASS`；`frontend/verify_web.js`、`frontend/verify_adaptive_web.js` 均 `ALL PASS`；`python backend/check_cards.py` 退出码 0。
真实库（`backend/learning.db`）已执行：学生 id1 朵朵 / id2 童童；`knowledge_points` 由 139 节点幂等补到 **284 节点**；掌握度行重新 link。

# 11. AI Notes

## 不要重复读取

- `docs/` 下四份版本说明的正文（结论已提炼进 §7、§8）；需要细节时再定点读
- `backend/bank_chinese.py`、`backend/bank_english.py`、`backend/diagnostic_bank.py` 的题库数据体（数万字符，只在改题库时才读）
- `frontend/assets/phoebe/` 下的二进制素材
- 本文件 §6 已覆盖的模块，不必为"了解职责"再通读源码

## 修改注意

- 改 `stages.py`（阶段/知识点/阈值）影响诊断、出题难度、知识点树、掌握度四处，必须先跑 `verify_diagnostic.py` 与 `verify_knowledge.py`
- 改 `database.py` / `models.py`（迁移）属高风险：只能加列、保留旧列，跑 `verify_knowledge.py`（含迁移回填断言）
- 改前端任何 js/css 后，浏览器必须强刷；同时跑对应 `frontend/verify_*.js`
- 改 `adaptive/` 任一算法（策略/难度/选题/计划）后跑 `verify_adaptive.py`（纯函数断言 + API 全流程一起覆盖）
- 改 `main.question` 签名或出题上下文时，注意 `adaptive_routes.learning_next_question` 是唯一外部调用方，
  且 `deepseek.ability_block()` 会把这些字段写进 prompt
- 改 `knowledge_routes._mastery_items` 的返回字段时，`adaptive/engine.profile` 会受影响（它把两个时间字段解析回 datetime）
- 改 `review/` 任一算法后跑 `verify_memory.py`（纯函数 + API + 迁移 + 隔离一起覆盖）
- 改 `adaptive/planner.build` 的条目结构时，注意 `learning_plan.item_type` 列与前端 `today.js` 的徽标、
  以及 `verify_adaptive.py` 里"数学计划：一天共 10 题"这类聚合断言
- 改 `review/engine.today()` 返回结构时，`adaptive/engine`（review 段 + review_first）、
  `review.js`、`memory_debug.js` 三处都要同步
- 新增复习相关字段时记得同步 `review/memory.MATURITY_CHILD`（儿童文案不能出现英文）与 `docs/V2.4间隔复习系统说明.md`
- 改 `frontend/phoebe3d.js`（旋转换算 / 动作 / 字幕 / 答题反馈 / **表情切换**）后跑 `node frontend/verify_phoebe3d_web.js`
- 换 `frontend/assets/phoebe3d/` 的表情素材时：18 张 `{情绪}_{视角}.png` 必须**画布一致（338×210）+ 底对齐**，
  并同步 `manifest.json`；重新裁图跑 `python tools/crop_phoebe3d_sheet.py`（输入 `frontend/assets/phoebe3d/source.png`），
  再用 `python tools/make_phoebe3d_doc_preview.py` 刷新文档预览图 `docs/images/phoebe3d_views.png`，
  最后跑 `node frontend/verify_phoebe3d_web.js` 与 `python backend/verify_all.py`
- 改 `backend/auto_ability.py`（权重 / 窗口 / 置信度阈值 / 状态分级）后跑 `python backend/verify_ability.py`
- 改 `backend/phoebe_ai.py`（prompt / 学习数据范围 / 兜底文案 / 清洗规则）后跑 `python backend/verify_phoebe_ai.py`；
  该套件**强制离线**（`PHOEBE_AI_OFFLINE=1`），不会真的调 DeepSeek，也不会花 token
- 想验证"真的接上了 DeepSeek"：起后端后 `POST /api/phoebe/chat`，看返回的 `source` 是不是 `ai`
  （`fallback_*` 说明没走大模型，原因见 `source` 后缀）
- 改 `frontend/today.js` / `frontend/app.js` 的自动跳题与错题解析后，跑 `verify_adaptive_web.js` / `verify_web.js`；
  两页都必须保证"每题只提交一次 `/api/learning/feedback`"，否则今日计划完成数会重复累加
- 新增依赖前先看 `requirements.txt` 是否已有等价能力（如已有 `python-dotenv`，但代码实际是 `deepseek.py` 自己解析 `.env`）
- 不要顺手接线或删除 §9 的未接线死代码，先确认

## 容易误判的点

- **`/question` 响应里的 `stage` 是 `abilities.stage`（浮点数，如 1.0）**，与能力阶段字符串（如 `"3.2"`）不是同一概念
- **`stages.py` 的 72 阶段与 `knowledge_tree.py` 的每科 72 个知识点一一对应**，不是"知识点共 72 个"（知识点树实际 284 节点）
- **复习起始阶段是 0，满级是 10**；验证输出中出现的 `stage=11` 是"已掌握"标记位
- **`.env` 生效但不是 python-dotenv 的功劳**：`deepseek.py:_load_key()` 手动逐行解析，且 `KEY` 在 import 时求值一次，改 `.env` 后必须重启进程
- **`GET /question` 不会下发答案与解析**，判分只在服务端；如果看到前端"知道"答案，那是从 `/submit` 的响应拿到的
- **端口占用会让验证套件直接失败**（这是刻意设计，不是环境问题）
- **`backend/adaptive.py`（旧死代码）与 `backend/adaptive/`（V2.3 自适应子包）同名但完全无关**，别改错文件
- **`/question` 的 `difficulty=0` 表示"不指定"**（由 `/question` 自己按画像算），只有 `/api/learning/next-question` 会传真实值
- **自适应难度调整一次最多 ±10，且难度恒在 1~100**；测试里 `delta` 与 `difficulty` 的差值可能被区间夹住，断言要区分 `delta` 与 `focus_delta`
- **连对/连错与正确率窗口不重复计分**：连对 5 题只 +5（正确率窗口这时只改 `stage_action`），不要误判为"少加了一次"
- **V2.4 的 `memory.state_summary` 里 `difficulty` 是"个人难度 0~1"**，不是出题难度（出题难度要用 `mastery_score` 或
  `knowledge_tree.difficulty_of`），别混用
- **间隔算法的阶梯只在成功复习的前 4 次生效**（`successful_reviews < 5`），之后才走稳定性驱动；
  测试期望 1/3/7/14/30 时不要叠加其它因子
- **复习队列按天缓存**：同一天改了记忆状态也不会自动重排，需要 `?refresh=true`
- **V2.5 起 `/` 返回 `version: "2.5"`**（V2.4 时期是 `"2.4"`，需要的断言已同步）
- **今日计划的 `completed_count` 只在 `/api/learning/feedback` 里 +1**（`adaptive/engine._advance_plan`）：
  今日学习页"答对自动跳下一题"必须补交一次反馈（`sendAutoFeedback`，`feel` 留空、`note="auto"`），
  否则进度条永远不动；`feedbackSent` 保证每题只提交一次，不会因自动 + 手动重复计数
- **菲比立牌素材是「6 情绪 × 3 视角」共 18 张**：`frontend/assets/phoebe3d/{情绪}_{视角}.png`，
  情绪 = `happy/sad/like/cheer/cute/encourage`（开心/难过/点赞/加油/可爱/鼓励），视角 = `front/side/back`；
  真实视角只有 3 个，第 4 个角度（270°）是侧面的水平镜像；
  18 张图画布统一 **338×210**、底对齐，换素材时必须保持画布一致，否则旋转/换表情时脚底会跳
- **表情切换靠换 `src`，不是加图层**：4 个旋转图层始终只有 4 个 `<img>`，
  `setMood(mood)` 先把三个视角 `new Image()` 预载好，全部 `onload` 才一次性换图；
  任何一张加载失败就**保留当前形象**（绝不白屏或半新半旧），自增 `moodToken` 保证只有最后一次请求生效
- **触发映射**：点击立牌 → 可爱 `cute` + AI 台词；答对 → 开心 `happy` + 跳跃转圈；连对 ≥2 题 → 点赞 `like`；
  答错 → 难过 `sad` + 摇头 + 语音；错题本再练答对 → 加油 `cheer`（`phoebe3dFeedback(true,{mood:"cheer"})`）；
  空闲 60s 没操作 → 鼓励 `encourage`；待机默认 `like`（最中性，答对换成开心才有对比）
- **`phoebe3d.js` 会自己挂载**：页面有 `[data-phoebe3d]` 容器就挂进去，否则挂成右下角浮动立牌；
  Node 测试里可用 `window.__PHOEBE3D_NO_AUTO__ = true` 关掉自动挂载
- **答对时不播 TTS**：表情包浮层自带欢呼人声，同时播会互相盖住；语音只用于答错提示与点击互动
- **`ability.html` 是只读页**：`/api/ability/auto/{id}` 不写任何表，学生无记录时返回 `status="unknown"` 而不是 404
- **菲比立牌挂在浏览器左侧固定位置**（`.p3d-stage.p3d-floating`，`position:fixed; left:18px`）：
  四个页面都**不放** `[data-phoebe3d]` 宿主，所以一直走浮动模式；≤900px 会隐藏（没有左侧空白）
- **鼠标移动永远不会改变立牌位置**：拖拽只改 `state.angle`，代码里不写 `style.left/top`；
  想改位置只能改 `style.css` 的 `.p3d-stage.p3d-floating`
- **菲比每次点击都会调 `/api/phoebe/chat`**：`source=ai` 才是真走了 DeepSeek，
  `fallback_no_key` / `fallback_offline` / `fallback_error` 分别是"没配 key / 设了离线开关 / 调用失败"；
  设 `PHOEBE_AI_OFFLINE=1` 可整体关掉联网（`.env` 里有 key 时也优先看这个开关）
- **V2.8 积分只加不减，且绝不回滚判分**：`points.award_after_answer` 在 `/submit` 里是独立 `try/except + db.rollback()`，积分出错只丢分不影响作答返回；
  两条 `once_key`（`checkin:{日期}` / `task:任务号`）保证「打卡」「收工」同一事件只记一次，重复调用返回 `reason="already"`
- **「每日打卡」不是分开的按钮才算**：当天第一次答对就顺手记一次打卡（+10），手动 `POST /api/points/{id}/checkin` 必须先答对过一题（没做过题 → `reason="need_answer"`）
- **积分商城只展示不兑换**：`points.SHOP_ENABLED = False`，所以 `shop.items[].affordable` 恒为 `False`；`（占位）`与「兑换比例先占位，兑换功能还没实装」文案是刻意的，改前端时别把它做成可点的按钮
- **版本号只认 `version.json`**：根接口 `/`、`start.bat` 的 `TARGET_VERSION`、自动更新比较，全部读同一个文件；要发新版先改它（再 `python tools/publish.py --push`），不要在 Python 里另写版本号
- **菲比的答对/答错文案仍是本地即时文案**，只有"点击"走 AI —— 别以为答题反馈也联网了
- 项目不是 git 仓库，**没有版本历史可回溯**；改动前请自行备份 `backend/learning.db`
- 改 `main.question` 的出题难度公式、`/submit` 的能力分上限或 `auto_ability` 的难度口径后，跑 `python backend/verify_flow.py --self-serve` + `verify_ability.py`；改 `adaptive/strategy.rank` 的档位/阶段加成后跑 `verify_adaptive.py`（改契约卡后还要 `python backend/check_cards.py`）
- 改积分规则 / 第一版奖励行为明细（`backend/points.py` / `points_rewards.py` / `points_routes.py` / `frontend/shop.js`）后跑 `python backend/verify_points.py` + `node frontend/verify_shop_web.js`；改一级导航（`frontend/ui-shell.js` 的 `NAV_TABS`）后跑 `node frontend/verify_ui_shell.js` + `node frontend/verify_shop_web.js`；改前端后浏览器强刷
