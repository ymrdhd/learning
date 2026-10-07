# 能力索引表（MODULE_MAP）

> **用途**：AI agent 定位代码的**唯一入口**。改任何功能前，先在本表查到「能力 → 文件 → 入口 → 表 → 验证套件」，再打开目标文件。
> **禁止**：跳过本表直接全仓 grep / 递归扫描。
> **维护规则（强制）**：新增、删除、改名任何模块、入口符号或验证套件时，**必须同步更新本表**，否则视为改动未完成。
> 相关文档：[架构重构方案](架构重构_Mixin方案.md)、[PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md)、[AI_RULES.md](../AI_RULES.md)

---

## 1. 后端能力表

| 能力 | 主文件 | 对外入口 | 相关表 | 验证套件 |
|---|---|---|---|---|
| 能力阶段 / 知识点**唯一来源** | `backend/stages.py` | `all_keys` `normalize_key` `key_of` `difficulty_of` `knowledge_of` `advance` `stars` `parent_key` `legacy_key` | — | 全部套件 |
| 能力阶段推进 / 下一题难度（轻量纯函数） | `backend/ability.py` | `calculate_stage` `next_difficulty` | — | flow |
| 知识点树（284 节点） | `backend/knowledge_tree.py` | `seed` `ensure_seeded` `link_mastery` `node_rows` `domains_for` `path_of` | `knowledge_points` | knowledge |
| 掌握度模型 | `backend/mastery.py` | `MasteryEngine.calculate_mastery` `level_of` `confidence_of` `next_review_time` `DEFAULT_ENGINE` | `student_knowledge_mastery` | knowledge |
| 掌握度**唯一写入口** | `backend/knowledge_routes.py` | `update_mastery` | `student_knowledge_mastery` | knowledge / flow / diagnostic |
| 错因分析 | `backend/error_analysis.py` | `analyze` `rule_analyze` `ai_analyze` `summary` `dominant_error` `backfill` | `answer_error_analysis` | knowledge |
| 错题本状态机 | `backend/wrong_book.py` | `record_wrong` `record_correct` `items_for` `stats_for` | `wrong_questions` | knowledge |
| 判分（**唯一真相**） | `backend/grading.py` | `is_correct` `normalize` `parse_options` `parse_acceptable` | — | flow |
| 题目质量审核 | `backend/validator.py` | `QuestionValidator.validate` | — | flow / knowledge |
| 题干**雷同判定**（唯一真相） | `backend/question_dedupe.py` | `normalize_stem` `numbers_of` `similarity` `is_duplicate` `DUPLICATE_THRESHOLD` | — | flow / memory |
| AI 出题与错因深化 | `backend/deepseek.py` | `generate_question`（可传 `history` 防雷同）`avoid_repeat_block` `analyze_error` `ability_block` `generate_review_question` | — | flow |
| 日常练习 API（核心闭环） | `backend/main.py` | `home` `students` `question` `submit` `reviews` | `questions` `answer_records` `abilities` `reviews` | flow |
| 艾宾浩斯复习（V2.1 旧体系） | `backend/srs.py` | `review` `apply_state` `due_items` `select_knowledge` `state_from_row` `mastery` `is_due` | `reviews` | review |
| 诊断状态机（纯函数） | `backend/diagnostic.py` | `new_state` `record_answer` `evaluate_stage` `calculate_ability` `build_report` | — | diagnostic |
| 诊断题库（数学程序化） | `backend/diagnostic_bank.py` | `build_question` `bank_size` | — | diagnostic |
| 诊断题库（语文 / 英语） | `backend/bank_chinese.py` `backend/bank_english.py` | 题库数据 + 取题 | — | diagnostic |
| 诊断 API | `backend/diagnostic_routes.py` | `start` `next_question` `submit_answer` `report` `profiles` `list_stages` | `diagnostic_sessions` `diagnostic_records` `ability_profile` | diagnostic |
| 知识 / 错因 / 错题 / 知识树 API | `backend/knowledge_routes.py` | `mastery_detail` `knowledge_report` `errors` `analyze_error` `wrong_questions` `knowledge_tree_api` `knowledge_sync` | 见 §2 | knowledge |
| 间隔复习（V2.4 新体系）门面 | `backend/review/engine.py` | `ReviewEngine.today` `review_question` `submit_review` `memory_map` `record_learning` `DEFAULT_ENGINE` | `knowledge_memory_state` `review_queue` `review_records` `review_strategy_log` | memory |
| 记忆状态模型 | `backend/review/memory.py` | `initial_learn_state` `maturity_of` `action_of` `state_summary` `relearn_state` | — | memory |
| 遗忘风险 | `backend/review/forgetting.py` | `ForgettingRiskEngine.calculate_forgetting_risk` `risk_level` | — | memory |
| 复习间隔 | `backend/review/interval.py` | `calculate_next_interval` `quality_of` `initial_interval_days` `ladder_preview` | — | memory |
| 复习队列调度 | `backend/review/scheduler.py` | `ReviewScheduler.build` `summarize` `priority_of` `next_batch_date` | `review_queue` | memory |
| 复习出题（防重复） | `backend/review/selector.py` | `ReviewQuestionSelector.build` `choose_mode`（`is_duplicate`/`similarity`/`normalize_stem` 复用 `question_dedupe`） | `questions` | memory |
| 每日新学/补强/复习配比 | `backend/review/mix.py` | `calculate_daily_mix` `split_counts` | — | memory / adaptive |
| 复习 API | `backend/review_routes.py` | `/api/review/*` | 见 §2 | memory |
| 自适应策略（学什么） | `backend/adaptive/strategy.py` | `LearningStrategy.rank` `choose` `prerequisites` `foundation_weight` `DEPENDENCIES` | — | adaptive |
| 难度动态控制 | `backend/adaptive/difficulty.py` | `DifficultyController.adjust` `stage_step` `DEFAULT_CONTROLLER` | — | adaptive |
| 下一题推荐 | `backend/adaptive/selector.py` | `QuestionSelector.select` `select_from_decision` `match_score` `repeat_penalty_of`（最近 0.35 / 次近 0.22 / 更早 0.12，均 ≤ weakness 权重 0.40） | — | adaptive |
| 每日学习计划 | `backend/adaptive/planner.py` | `DailyLearningPlanner.build` `ensure` `summary` `allocate` | `learning_plan` | adaptive |
| 自适应门面（唯一碰库的自适应模块） | `backend/adaptive/engine.py` | `AdaptiveLearningEngine.recommend` `next_spec`（含 `avoid_knowledge` 软避让）`plan` `start` `feedback` `profile` `DEFAULT_ENGINE` | `learning_plan` `learning_strategy_log` `learning_feedback` | adaptive |
| 自适应 API | `backend/adaptive_routes.py` | `/api/learning/*` | 同上 | adaptive |
| 训练数据自动能力诊断（V2.5，**只读**） | `backend/auto_ability.py` | `subject_profile` `overall_profile` `profile_for` `confidence_text` | 只读 `answer_records` | ability |
| 自动能力诊断 API（V2.5） | `backend/ability_routes.py` | `/api/ability/auto/{student_id}` | 只读 `answer_records` | ability |
| 菲比 AI 陪伴（V2.5，**只读**） | `backend/phoebe_ai.py` | `learning_snapshot` `build_prompt` `clean_line` `fallback_line` `ai_line` `ai_enabled` `phoebe_line` | 只读 `answer_records` / `student_knowledge_mastery` / `wrong_questions` | phoebeai |
| 菲比对话 API（V2.5） | `backend/phoebe_routes.py` | `/api/phoebe/chat` | 只读（同上） | phoebeai |
| 错题康复状态机（V2.5） | `backend/recovery/engine.py`（+ `state.py` / `strategy.py` / `scheduler.py`） | `WrongQuestionRecoveryEngine.list_items` `stats` `detail` `start` `hint` `next_question` `answer` `verify` `sync_from_wrong_book` `DEFAULT_ENGINE` | `wrong_question_recovery` `wrong_questions` | recovery |
| 错题康复 API（V2.5） | `backend/recovery_routes.py` | `/api/recovery/*`（含 `GET /api/recovery/list/{student_id}`、`GET /api/recovery/{recovery_id}`、`GET /api/recovery/next-question`） | 见 §2 | recovery |
| 每日学习习惯 / 五段每日计划 / 目标时长自适应（V2.5→V2.6） | `backend/habit.py` | `HabitEngine.generate_daily_tasks` `plan` `start_today` `today` `task_dict_list` `complete_task` `profile` `stats` `calendar` `refresh` `goal` `minutes_for_grade` `rest_status` `use_rest_protection` `next_target_minutes` `target_minutes_of` `TARGET_MIN` `TARGET_MAX` `DEFAULT_ENGINE` | `daily_learning_task` `learning_habit_profile` | habit / recall |
| 每日任务 API（V2.5） | `backend/task_routes.py` | `/api/tasks/*`（`today`、`today/{sid}`、`plan/{sid}`、`start`、`complete`、`{task_id}/complete`） | 同上 | habit / recall |
| 习惯 / 学习日历 / 学习目标 API（V2.5→V2.6） | `backend/habit_routes.py` | `/api/habit/profile` `stats` `calendar` `rest` `goal`（含 path 形式） | 同上 | habit / recall |
| 主动回忆（V2.5，基础版） | `backend/active_recall.py` | `ActiveRecallEngine.start` `answer` `history` `summary` `card_bank` `card_dict` `judge` `child_level` `DEFAULT_ENGINE` | `active_recall_record` `answer_records` `knowledge_memory_state` | recall |
| 主动回忆 API（V2.5） | `backend/active_recall_routes.py` | `/api/active-recall/start` `answer` `summary` | 同上 | recall |
| 每日总结（V2.5，**只读聚合**） | `backend/daily_routes.py` | `GET /api/daily-summary/{student_id}` | 只读（任务 / 画像 / 回忆 / 康复 / 目标） | recall |
| 数据库与迁移 | `backend/database.py` | `ensure_schema` `migrate_data` `KNOWLEDGE_RENAMES` `get_db` `SessionLocal` `engine` | — | knowledge |
| 表模型 | `backend/models.py` | `Base` + 25 个模型类 | 全部 | 全部 |
| 默认用户 | `backend/local_users.py` | `init_default_users` | `students` | flow |
| 用户数据备份与重置（家长端） | `backend/user_routes.py` | `reset_preview` `reset_student` `router`（`GET /api/user/{student_id}/reset-preview`、`POST /api/user/{student_id}/reset`） | 备份并清空 20 张含 `student_id` 的表（保留 `students` 行本身） | userreset |
| 积分系统（V2.8，只加不减、事件幂等） | `backend/points.py` | `award` `award_after_answer` `award_task_done` `login` `checkin` `summary` `balance_of` `streak_days` `RULES`（5 条：答对 2 / 打卡 10 / 登录 10 / 继续练 3 / 收工 5）`SHOP_ITEMS` | `student_point` `point_record` | points |
| 积分明细（第一版奖励行为表，只描述规则、不判定不加分） | `backend/points_rewards.py` | `REWARD_VERSION` `REWARD_STATES` `REWARDS` `reward_table` `rewards_of` `points_text` | 只读常量与纯函数（不碰数据库） | points |
| 积分 API（V2.8，商城占位、兑换不实装） | `backend/points_routes.py` | `points_summary` `points_shop` `points_login` `points_checkin`（`GET /api/points/{student_id}` 带第一版奖励明细 / `GET /shop` / `POST /login` 每日首次登录 +10 / `POST /checkin` 小任务全部收工后自动打卡） | 同上 | points |
| 版本对比与自动更新（V2.8） | `backend/updater.py` | `local_version` `parse_version` `is_newer` `remote_manifest` `download_archive` `apply` `run` | 只覆盖源码文件（**永不碰** `*.db` / `.env` / `backup/` / 日志） | `update_check.py --self-test` |
| 启动时自动更新入口（V2.8） | `backend/update_check.py` | `main` `self_test` `print_result`（`python backend/update_check.py --apply`） | 同上 | `update_check.py --self-test` |
| 打包上传 GitHub（V2.8） | `tools/publish.py` | `main` `collect_files` `build_zip` `ensure_repo` `push` | 读项目文件 + GitHub API；令牌走 `GITHUB_TOKEN` / `tools/.github_token`（不入库） | `python tools/publish.py --dry-run` |
| 局域网访问修复（手机/平板连不上时） | `tools/fix_lan_access.bat` | 删除 Windows 防火墙里名为 `Python` 的入站 Block 规则 + 放行 `python.exe` 与 TCP 8000 + 网络设为专用 + 打印手机地址 | **只改 Windows 防火墙规则**，不碰项目数据；需管理员权限（脚本自提权） | 手动双击运行（本机自测会打印 `LAN self-test: OK`） |
| 直连兜底（V2.8） | `backend/net_fallback.py` | `http_request` `resolve_ips` | 只在正常 DNS 连不上时启用；TLS 仍按真实域名校验 | `python backend/update_check.py --self-test` |
| 验证编排 | `backend/verify_all.py` | `main` `SUITES` `node_exe` | — | — |

### 1.1 验证脚本 → 覆盖对象（26 个套件 + 2 个独立自检/门禁，端口固定）

| 脚本 | 套件 key | 端口 | 覆盖对象 |
|---|---|---|---|
| `backend/verify_review.py` | `review` | 8899 | `srs.py`（V2.1 艾宾浩斯旧体系） |
| `backend/verify_flow.py` | `flow` | 8900 | `main.py` 出题/判分/能力闭环 + 出题防雷同（**必须带 `--self-serve`**） |
| `backend/verify_diagnostic.py` | `diagnostic` | 8902 | `diagnostic.py` + `diagnostic_bank.py` + 诊断接口 |
| `backend/verify_knowledge.py` | `knowledge` | 8904 | `mastery.py` / `knowledge_tree.py` / `error_analysis.py` / `wrong_book.py` / `validator.py` + V2.2→V2.3 迁移 |
| `backend/verify_adaptive.py` | `adaptive` | 8905 | `adaptive/` 五模块（含同知识点软避让）+ `/api/learning/*` |
| `backend/verify_memory.py` | `memory` | 8906 | `review/` 七模块 + `/api/review/*` + V2.3→V2.4 迁移 + `question_dedupe` 共用判定 |
| `backend/verify_ability.py` | `ability` | 8907 | `auto_ability.py` + `/api/ability/auto/{id}`（训练成绩自动诊断） |
| `backend/verify_phoebe_ai.py` | `phoebeai` | 8908 | `phoebe_ai.py` + `/api/phoebe/chat`（学习数据快照 / AI 台词 / 降级路径；**强制离线，不联网**） |
| `backend/verify_recovery.py` | `recovery` | 8910 | `recovery/` 子包 + `/api/recovery/*` + 错题生命周期 / 提示分级 / 延迟验证 + V2.4→V2.5 迁移 |
| `backend/verify_habit.py` | `habit` | 8911 | `habit.py` + `/api/tasks/*` + `/api/habit/*` + 50/30/20 配比 + 幂等生成 + 连续天数 / 徽章 + A/B 隔离 |
| `backend/verify_active_recall.py` | `recall` | 8912 | 主动回忆（不给选项 / 提示降增益）+ 五段计划与年级时长 + 每日总结结束文案 + 画像新字段 + 休息保护 + 兼容 path + 隔离 + 前端三页静态检查 |
| `backend/verify_user_reset.py` | `userreset` | 8914 | `user_routes.py` + `/api/user/*`（先备份后清空 / 备份内容 / 学生间隔离 / 幂等 / 失败路径 / 重置后仍可出题） |
| `backend/verify_points.py` | `points` | 8915 | `points.py` + `points_rewards.py`（第一版奖励行为表 14 条 · 区间分值 · 星级 · 三态）+ `/api/points/*` + 五条规则分值 + 每日首次登录幂等 + 「任务全部收工自动打卡」（need_finish / award_task_done 的 checkin）+ 计划做完后继续练 + 任务收工幂等 + A/B/E/F 隔离 + 接线（`main.py` / `task_routes.py` 源码断言）|
| `backend/update_check.py --self-test` | —（离线自检） | — | 版本号比较 / 保护名单（数据库·.env·backup 不被覆盖）/ 临时目录试同步 / 启动接线（不联网、不占端口）|
| `backend/verify_port_guard.py` | —（未编入） | — | 端口守卫；与全量互斥，单独运行 |
| `backend/check_cards.py` | —（静态门禁） | — | 校验 98 个模块契约卡的「入口」符号是否真实存在（**刻意不纳入 verify_all**） |
| `frontend/verify_web.js` | `web` | — | `app.js`（语音 / 复习面板） |
| `frontend/verify_diagnostic_web.js` | `diagweb` | — | 诊断三页 |
| `frontend/verify_knowledge_web.js` | `knowweb` | — | 知识三页 |
| `frontend/verify_adaptive_web.js` | `adaptweb` | — | `today.js` |
| `frontend/verify_memory_web.js` | `memweb` | — | `review.js` + `memory_debug.js` |
| `frontend/verify_phoebe_web.js` | `phoebeweb` | — | `phoebe.js` + 三处答题页调用守卫 |
| `frontend/verify_phoebe3d_web.js` | `phoebe3dweb` | — | `phoebe3d.js`（三视图立牌：旋转换算 / 动作 / 字幕 / **6 情绪表情**）+ 18 张素材 + 三处答题页接入 |
| `frontend/verify_ability_web.js` | `abilityweb` | — | `ability.js` + `ability.html`（能力水平页渲染与接口调用） |
| `frontend/verify_ui_shell.js` | `uishell` | — | `kid-lang.js`（儿童化语言映射）+ `ui-shell.js`（共享状态 / 导航壳 / 学生切换）+ `ui-components.js`（公共组件 HTML） |
| `frontend/verify_growth_profile_web.js` | `growthweb` | — | `growth.js` + `profile.js` + 两个新一级页（成长 / 我的） |
| `frontend/verify_shop_web.js` | `shopweb` | — | `shop.js` + `shop.html`（挑战下方新一级页：商品 + 第一版奖励行为明细 + 流水 + 余额卡；导航 5 项且商城紧跟挑战） |

> 子包入口（`backend/adaptive/__init__.py`、`backend/review/__init__.py`）各自带模块分工表契约卡，故不单列。
> 文件名冲突提醒：`backend/_legacy/adaptive.py`（235 B 死代码）与 `backend/adaptive/`（活子包）**无关**；死代码已归档，**禁止接线**。

---

## 2. 数据库表归属（25 张）

> 依 `backend/models.py` 的 `__tablename__` 与当前实现整理。
> **写入路径纪律**见 `AI_RULES.md` §13.2 / §13.4：掌握度只走 `update_mastery`；`reviews` 的 `stage/streak/next_review_at` 只走 `srs.review` + `srs.apply_state`。

| 表名 | 模型类 | 主要写入口 | 主要读入口 |
|---|---|---|---|
| `students` | `Student` | `local_users.init_default_users` | `main.students` |
| `abilities` | `Ability` | `main.submit`（能力分更新） | `main.question`、诊断 |
| `answer_records` | `AnswerRecord` | `main.submit`、`review/engine.submit_review` | `knowledge_routes.collect_records`、`adaptive/engine.profile`、`auto_ability.profile_for` |
| `reviews` | `Review` | `srs.review` + `srs.apply_state`（经 `main.submit`） | `main.question`（选题）、`main.reviews` |
| `questions` | `Question` | `main.question`、`review/engine.review_question`、`diagnostic_routes._create_question` | 判分 / 重练 |
| `diagnostic_sessions` | `DiagnosticSession` | `diagnostic_routes.start` | `next_question` / `submit_answer` |
| `diagnostic_records` | `DiagnosticRecord` | `diagnostic_routes.submit_answer` | 报告 |
| `ability_profile` | `AbilityProfile` | `diagnostic_routes._save_profile` | `diagnostic_routes.profiles` / `report` |
| `student_knowledge_mastery` | `StudentKnowledgeMastery` | **`knowledge_routes.update_mastery`（唯一）** | `mastery_detail`、`adaptive/engine.profile` |
| `knowledge_points` | `KnowledgePoint` | `knowledge_tree.seed` | `knowledge_routes.knowledge_tree_api` |
| `answer_error_analysis` | `AnswerErrorAnalysis` | `error_analysis.analyze` / `backfill` | `knowledge_routes.errors` |
| `wrong_questions` | `WrongQuestion` | `wrong_book.record_wrong` / `record_correct` | `knowledge_routes.wrong_questions` |
| `learning_plan` | `LearningPlan` | `adaptive/planner.ensure`（幂等） | `adaptive/engine.plan` |
| `learning_strategy_log` | `LearningStrategyLog` | `adaptive/engine.log` | `adaptive/engine.strategy_logs` |
| `learning_feedback` | `LearningFeedback` | `adaptive/engine.feedback` | `adaptive/engine.feedback_history` |
| `knowledge_memory_state` | `KnowledgeMemoryState` | `review/engine.record_learning` / `submit_review` | `review/engine.memory_map` |
| `review_records` | `ReviewRecord` | `review/engine.submit_review` | `review/engine.review_history` |
| `review_queue` | `ReviewQueue` | `review/engine.schedule`（按天缓存） | `review/engine.today` |
| `review_strategy_log` | `ReviewStrategyLog` | `review/engine.log_strategy` | `review/engine.strategy_logs` |
| `wrong_question_recovery` | `WrongQuestionRecovery` | `recovery/engine.sync_from_wrong_book`（`main.submit` 钩子）/ `scheduler.enqueue` | `recovery/engine.list_items` / `detail` / `stats` |
| `daily_learning_task` | `DailyLearningTask` | `habit.generate_daily_tasks` / `_persist_plan`（`POST /api/tasks/start`） | `habit.today` / `task_dict_list` |
| `learning_habit_profile` | `LearningHabitProfile` | `habit.refresh` | `habit.profile` / `_profile_dict` |
| `active_recall_record` | `ActiveRecallRecord` | `active_recall.answer` | `active_recall.history` / `summary` |
| `student_point` | `StudentPoint` | **`points.award`（唯一写入口）** | `points.summary` / `points_routes.points_summary` |
| `point_record` | `PointRecord` | **`points.award`（唯一写入口，`once_key` 保证同一事件只记一次）** | `points.summary` / `points.streak_days` / `verify_points.py` |
---

## 3. 前端页面 → 脚本 → 验证

| 页面 | 脚本（加载顺序） | 验证脚本 |
|---|---|---|
| `frontend/index.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `app.js` | `verify_web.js`、`verify_phoebe_web.js`、`verify_phoebe3d_web.js` |
| `frontend/today.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `today.js` | `verify_adaptive_web.js`、`verify_phoebe3d_web.js` |
| `frontend/ability.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `ability.js` | `verify_ability_web.js`（V2.5 训练成绩自动能力水平） |
| `frontend/diagnostic.html` | 共享层 → `diagnostic.js` | `verify_diagnostic_web.js`（家长/工具页，**不挂儿童导航**） |
| `frontend/diagnostic_test.html` | `phoebe.js` → 共享层 → `diagnostic_test.js` | `verify_diagnostic_web.js`、`verify_phoebe_web.js`（**不挂儿童导航**） |
| `frontend/diagnostic_report.html` | 共享层 → `diagnostic_report.js` | `verify_diagnostic_web.js`（**不挂儿童导航**） |
| `frontend/knowledge_map.html` | 共享层 → `knowledge_map.js` | `verify_knowledge_web.js` |
| `frontend/wrong_book.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `wrong_book.js` | `verify_knowledge_web.js`、`verify_phoebe_web.js`、`verify_phoebe3d_web.js` |
| `frontend/study_advice.html` | 共享层 → `study_advice.js` | `verify_knowledge_web.js` |
| `frontend/review.html` | 共享层 → `review.js` | `verify_memory_web.js`（儿童端「知识浇水」） |
| `frontend/memory_debug.html` | 共享层 → `memory_debug.js` | `verify_memory_web.js`（家长端记忆数据，**不挂儿童导航**、保留原始指标） |
| `frontend/recovery.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `recovery.js` | `verify_recovery_web.js`（V2.5 错题康复） |
| `frontend/recall.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `recall.js` | `verify_active_recall.py` 的 `page_case`（V2.5 主动回忆，**不出选项**） |
| `frontend/daily.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `daily.js` | 同上（V2.5 今日完成） |
| `frontend/habit.html` | `phoebe.js` → `phoebe3d.js` → 共享层 → `habit.js` | 同上（V2.5 学习习惯简报） |
| `frontend/growth.html` | 共享层 → `growth.js` | `verify_growth_profile_web.js`（2026-10-05 新增「成长」一级页） |
| `frontend/profile.html` | 共享层 → `profile.js` | `verify_growth_profile_web.js`（2026-10-05 新增「我的」一级页） |
| `frontend/shop.html` | 共享层 → `shop.js` | `verify_shop_web.js`（2026-10-05 新增「🛍️ 商城」一级页：商品 + 积分明细，挂在挑战下方） |
| `frontend/{ui-shell,kid-lang,ui-components}.js` | 共享层，顺序固定 `ui-shell.js` → `kid-lang.js` → `ui-components.js`（排在业务 js **之前**） | `verify_ui_shell.js` |

> **共享 UI 层（2026-10-05 儿童端 UI/UX 重设计）**：全部 19 个 `frontend/*.html` 都加载
> `ui-shell.js` → `kid-lang.js` → `ui-components.js`（上表简写为「共享层」），再接一段内联初始化脚本
> （`UIShell.applySettings()` / `UIShell.mountNav(...)` / `UIShell.loadStudents()`）。
> 一级导航 5 项：`today.html`（今天）/ `growth.html`（成长）/ `challenge.html`（挑战，tab=wrong）/ `shop.html`（商城，**紧跟挑战**）/ `profile.html`（我的）。
> **顺序契约**：共享层必须排在业务 js **之前** —— 业务 js 末尾会立即 `init()`，共享层缺席时首屏只能走纯文本降级。
> `verify_recovery_web.js` 断言 `recovery.html` 脚本数组为 `phoebe.js`(0) → `phoebe3d.js`(1) → `ui-shell.js`(2) → `kid-lang.js`(3) → `ui-components.js`(4) → `recovery.js`(5)。
> `ui-shell.js` 是 `currentStudent`（localStorage 键 `xiaozhi.student`）的**唯一读写口**，并提供 `ageMode`、
> `xiaozhi.uiSettings`、底部/侧栏导航 `mountNav`；`kid-lang.js` 提供知识状态儿童化映射（🌱 刚开始 / 🌿 正在学习 / 🍀 基本会了 / 🌳 已经掌握 / ⭐ 记得很牢）；
> `ui-components.js` 提供公共组件 HTML（`progressBar` / `emptyState` / `loadingState` / `errorState` / …）。
> 家长端 `memory_debug.html` 与 `diagnostic*.html` 只 `applySettings()`，**不挂儿童导航**，并保留原始算法指标。
> **不挂导航的 4 个页面**：`memory_debug.html`（家长端）与 `diagnostic.html` / `diagnostic_test.html` / `diagnostic_report.html`
> 只调 `UIShell.applySettings()`，不调 `mountNav`。
> 页脚 `<p class="meta link-row">` **保留**（降级为次要入口），不是一级导航；儿童端一级导航 5 项（今天 / 成长 / 挑战 / 商城 / 我的）。

> 全站唯一样式表 `frontend/style.css`（2026-10-05 起首部定义 Design Tokens `:root{…}`，末尾追加 `.ph-*` 组件类）；
> `phoebe.js`（表情包浮层）与 `phoebe3d.js`（三视图立牌 + 语音字幕 + 6 情绪表情）都必须排在业务 js **之前**，
> 而共享 UI 层三脚本（`ui-shell.js` → `kid-lang.js` → `ui-components.js`）必须排在业务 js **之后**。
> V2.5 起能力水平不再要求"额外做一次诊断"：`ability.html` 读 `/api/ability/auto/{id}`；
> `diagnostic*.html` 三页保留但不再出现在主流程入口。
> **菲比立牌素材是 18 张 `{情绪}_{视角}.png`**（`frontend/assets/phoebe3d/`，情绪 = happy/sad/like/cheer/cute/encourage），
> 画布统一 338×210 且底对齐；切表情是**换 `src`**（先预载，失败保留旧图），不是加图层。
> **菲比立牌不再放进提示框**：页面里不写 `[data-phoebe3d]` 宿主，`phoebe3d.js` 会自动挂成
> 浏览器**左侧固定**立牌（`.p3d-stage.p3d-floating`，`position:fixed; left`），
> 页面滚动、鼠标移动、拖拽旋转都不会改变它的位置；点击它才触发 `/api/phoebe/chat`。

---

## 4. 任务速查表（改 X → 读这些 → 跑这套）

| 需求 | 读这些文件 | 验证命令 |
|---|---|---|
| 调整复习间隔阶梯 | `review/interval.py` | `python backend/verify_memory.py` |
| 调整遗忘风险公式 | `review/forgetting.py` | `python backend/verify_memory.py` |
| 改复习队列优先级 / 每日上限 | `review/scheduler.py`、`review/mix.py` | `python backend/verify_memory.py` |
| 改复习提交后的状态推进 | `review/engine.py`（`submit_review`）+ `review/interval.py` | `python backend/verify_memory.py` |
| 改艾宾浩斯旧阶梯 | `srs.py` | `python backend/verify_review.py` |
| 改难度升降阈值 | `adaptive/difficulty.py` | `python backend/verify_adaptive.py` |
| 改知识点优先级 / 依赖门控 | `adaptive/strategy.py` | `python backend/verify_adaptive.py` |
| 改下一题推荐配比 | `adaptive/selector.py` | `python backend/verify_adaptive.py` |
| 改今日计划分配 | `adaptive/planner.py` | `python backend/verify_adaptive.py` |
| 改 `/submit` 写库步骤 | `main.py`（`submit`）、`knowledge_routes.py`（`update_mastery`）、`srs.py` | `python backend/verify_flow.py --self-serve` |
| 改出题与审核 | `deepseek.py`、`validator.py` | `python backend/verify_flow.py --self-serve` |
| 改掌握度模型 | `mastery.py` | `python backend/verify_knowledge.py` |
| 改错因规则 / 文案 | `error_analysis.py` | `python backend/verify_knowledge.py` |
| 改错题本状态机 | `wrong_book.py` | `python backend/verify_knowledge.py` |
| 改诊断阶段判定 | `diagnostic.py` | `python backend/verify_diagnostic.py` |
| 加 / 改知识点或阶段 | `stages.py` + `knowledge_tree.py` + `adaptive/strategy.py`（依赖表） | `python backend/verify_all.py`（全套） |
| 改今日学习页 | `frontend/today.js`、`frontend/today.html` | `node frontend/verify_adaptive_web.js` |
| 改积分规则 / 商城占位道具 / 奖励行为明细 | `backend/points.py`（`RULES` / `SHOP_ITEMS`）、`backend/points_rewards.py`（第一版奖励行为表）、`backend/points_routes.py`、`frontend/today.js`（`renderPoints`）、`frontend/shop.js` | `python backend/verify_points.py`、`node frontend/verify_shop_web.js`、`node frontend/verify_adaptive_web.js`、`node frontend/verify_v26_web.js` |
| 改商城页 / 一级导航 | `frontend/shop.html` + `shop.js`、`frontend/ui-shell.js`（`NAV_TABS`）、`frontend/style.css`（`.shop-*` / `.points-row*` / 底部导航五列） | `node frontend/verify_shop_web.js`、`node frontend/verify_ui_shell.js` |
| 改版本号 / 启动自动更新 | `version.json`（唯一真相）、`backend/updater.py`、`backend/update_check.py`、`start.bat` | `python backend/update_check.py --self-test` |
| 发版：打包并上传到 GitHub | `version.json`（先升版本号）、`tools/publish.py` | `python tools/publish.py --dry-run`（本地打包）→ `--push`（需令牌） |
| 改练习页 | `frontend/app.js` | `node frontend/verify_web.js` |
| 改今日题单（每页一题 / 题型内部标记 / 按项记 3/5、做完的项跳过） | `frontend/app.js`（sheet 模式）、`frontend/today.js`、`frontend/today.html`、`backend/habit.py`（`record_answer(task_id=…)`） | `node frontend/verify_web.js`、`node frontend/verify_adaptive_web.js`、`python backend/verify_habit.py` |
| 改庆祝浮层 | `frontend/phoebe.js` | `node frontend/verify_phoebe_web.js` |
| 改菲比三视图立牌 / 拖拽旋转 / 字幕语音 / **表情切换与触发映射** | `frontend/phoebe3d.js`、`frontend/style.css`（`.p3d-*`） | `node frontend/verify_phoebe3d_web.js` |
| 改菲比台词（prompt / 学习数据范围 / 兜底文案） | `backend/phoebe_ai.py` | `python backend/verify_phoebe_ai.py` |
| 改立牌位置 / 屏幕适配 | `frontend/style.css`（`.p3d-stage.p3d-floating`） | `node frontend/verify_phoebe3d_web.js` |
| 换表情素材（重裁公仔图） | `frontend/assets/phoebe3d/`（18 张 `{情绪}_{视角}.png` + `manifest.json`） | `python tools/crop_phoebe3d_sheet.py` → `python tools/make_phoebe3d_doc_preview.py`（刷新文档预览图） → `node frontend/verify_phoebe3d_web.js` |
| 改答对自动跳题 / 错题解析停留 | `frontend/today.js`、`frontend/app.js` | `node frontend/verify_adaptive_web.js`、`node frontend/verify_web.js` |
| 改能力自动诊断算法（阈值 / 权重 / 置信度） | `backend/auto_ability.py` | `python backend/verify_ability.py` |
| 改能力水平页 | `frontend/ability.js`、`frontend/ability.html` | `node frontend/verify_ability_web.js` |
| 改启动行为 / 固定端口 / 内网（同网段手机）访问 | `start.bat` | `node frontend/verify_ui_shell.js`（静态断言：8000 固定端口 + `--host 0.0.0.0` + 手机地址）；人工：双击后自动弹出 `/app/` |
| 改手机端观感 / 页面 viewport | `frontend/style.css`（≤720px 手机档）、各 `frontend/*.html` 的 viewport 元信息 | `node frontend/verify_ui_shell.js` |
| 改知识三页 | `frontend/knowledge_map.js`、`wrong_book.js`、`study_advice.js` | `node frontend/verify_knowledge_web.js` |
| 改复习页 / 记忆调试页 | `frontend/review.js`、`memory_debug.js` | `node frontend/verify_memory_web.js` |
| 改数据库 schema / 迁移 | `models.py`、`database.py`（**只能加列**；知识点改名走 `KNOWLEDGE_RENAMES`） | `python backend/verify_knowledge.py` |
| 改错题康复状态机 / 策略 / 提示分级 | `recovery/state.py`、`recovery/strategy.py`、`recovery/engine.py` | `python backend/verify_recovery.py` |
| 改每日计划配比 / 年级时长 / 休息保护 | `habit.py`、`models.py`（`LearningHabitProfile`） | `python backend/verify_habit.py`、`python backend/verify_active_recall.py` |
| 加 / 改主动回忆卡片与记忆增益 | `active_recall.py` | `python backend/verify_active_recall.py` |
| 改今日完成页 / 习惯简报 / 主动回忆页 | `frontend/daily.js`、`habit.js`、`recall.js` | `python backend/verify_active_recall.py`（静态检查） |
| 改儿童端导航 / 学生切换 / 分龄 / 显示设置 | `frontend/ui-shell.js`（`NAV_TABS` 现为 5 项：今天 / 成长 / 挑战 / 商城 / 我的） | `python backend/verify_all.py uishell shopweb` |
| 改成长页 / 我的页 | `frontend/growth.js`、`frontend/profile.js` | `python backend/verify_all.py growthweb` |
| 改家长端备份并重置 | `backend/user_routes.py`、`frontend/profile.js`、`frontend/profile.html` | `python backend/verify_all.py userreset growthweb` |
| 改公共 UI 组件（空 / 加载 / 错误 / 题卡 / 进度 / 弹窗） | `frontend/ui-components.js` | `python backend/verify_all.py uishell` |
| 改儿童化语言 / 知识状态文案 | `frontend/kid-lang.js` | `python backend/verify_all.py uishell` |
| 改设计 token / 全局样式 / 响应式断点 | `frontend/style.css`（`:root` 与 `.ph-*`） | `node frontend/verify_phoebe3d_web.js`（立牌正则契约）+ 人工刷新各页 |

---

## 5. 历史遗留与死代码

| 文件 | 状态 | 处理 |
|---|---|---|
| `backend/_legacy/adaptive.py` | 未接线死代码（与 `adaptive/` 子包无关） | 已归档，**禁止接线或删除**（`AI_RULES.md` §13.9） |
| `backend/_legacy/algorithm.py` | 未接线死代码 | 同上 |
| `backend/_legacy/ai_question.py` | 未接线死代码 | 同上 |
| `backend/_legacy/reward.py` | 未接线死代码（引用 `Student` 上不存在的列，接线即 `AttributeError`） | 同上 |
| `backend/learning.db` | **真实使用数据** | 禁止写入；改动前先备份 |
| `data/*.json` | 非运行时数据源 | 改它们不影响系统行为 |

---

## 6. 验证命令速查

```powershell
# 全量（26 个套件，串行，各自独立端口与临时库）
python backend\verify_all.py

# 子集
python backend\verify_all.py adaptive adaptweb phoebe3dweb phoebeai

# 单套件（端口固定，被占用会“故意失败”，不要改成自动换端口）
python backend\verify_review.py                 # 8899  艾宾浩斯旧体系
python backend\verify_flow.py --self-serve      # 8900  学习闭环（必带 --self-serve）
python backend\verify_diagnostic.py             # 8902  能力诊断
python backend\verify_knowledge.py              # 8904  知识/错因/错题
python backend\verify_adaptive.py               # 8905  自适应引擎
python backend\verify_memory.py                 # 8906  V2.4 间隔复习
python backend\verify_ability.py                # 8907  V2.5 训练成绩自动能力诊断
python backend\verify_phoebe_ai.py              # 8908  V2.5 菲比 AI 陪伴（不联网）
python backend\verify_recovery.py                # 8910  V2.5 错题康复
python backend\verify_habit.py                   # 8911  V2.5 每日任务与习惯
python backend\verify_active_recall.py          # 8912  V2.5 主动回忆与每日总结
python backend\verify_points.py                 # 8915  V2.8 积分（答对 / 打卡 / 继续练 / 收工）
python backend\verify_port_guard.py             # 端口守卫（与全量互斥）
python backend\check_cards.py                   # 契约卡门禁：改动任何卡片后必跑（静态，快）
python backend\update_check.py --self-test     # V2.8 版本对比 / 自动更新（离线自检，不占端口）
python tools\publish.py --dry-run               # V2.8 打包 dist/learning-<版本>.zip（上传前先本地验证）

# 前端（系统无 node 时用捆绑 node）
node frontend\verify_web.js
node frontend\verify_diagnostic_web.js
node frontend\verify_knowledge_web.js
node frontend\verify_adaptive_web.js
node frontend\verify_memory_web.js
node frontend\verify_phoebe_web.js
node frontend\verify_phoebe3d_web.js
node frontend\verify_ability_web.js
node frontend\verify_recovery_web.js
node frontend\verify_ui_shell.js
node frontend\verify_growth_profile_web.js
node frontend\verify_shop_web.js
# 捆绑 node：C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe
```

**纪律**：禁止并发跑多套件；测试只允许写 `_verify_*.db`；绝不能写 `backend/learning.db`。
