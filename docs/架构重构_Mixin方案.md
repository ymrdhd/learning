# 架构重构方案：Mixin 切片 + 契约卡 + 能力索引

> 状态：**P0 + P1 已执行完成（零逻辑风险阶段）**，基线见 §9.2，执行记录见 `backup/ledger_P0_P1.md`；**P2 起尚未执行**
> 适用范围：`backend/` 全部、`frontend/` 静态页面与脚本
> 本文档是重构的唯一执行依据；执行时逐阶段照 §8 推进，不要另行临时设计。

---

## 0. 本文档给 AI agent 的用法

1. **定位阶段**：先读 §3 能力索引表 → 直接跳到目标文件，**禁止**全仓 `grep` 扫描后才定位。
2. **修改阶段**：读目标文件的契约卡（文件头 10 行 docstring）→ 只读该文件（≤250 行）与其纯函数依赖。
3. **验证阶段**：按 §3.3 任务速查表跑**对应套件**，不要默认跑全量。
4. 本文档 §6 红线在任何阶段都不得违反，即使"看起来更优雅"。

---

## 1. 背景与目标

### 1.1 起因

当前后端 48 个 py 文件、14018 行；前端 16 个 js、4656 行。存在多个"上帝类/上帝文件"，
导致 agent 每次改动都要跨文件反复查找、读取大量无关代码，token 与时间浪费严重。

### 1.2 目标（按优先级）

| # | 目标 | 可衡量判据 |
|---|---|---|
| G1 | 每个子程序功能专一 | 单文件 ≤250 行；单文件单职责，文件名即能力名 |
| G2 | 减少反复查找 | 单任务工具调用 ≤2 次；读取 ≤2 文件、≤400 行 |
| G3 | 降低 token | 单任务读取 ≤6k token（现状 13k~16k，降约 65%） |
| G4 | 降低编程时间 | 定位不再依赖"读实现才知道入口" |

### 1.3 非目标（本次明确不做）

- 不改任何 API 路径、字段语义、错误语义
- 不改数据库表结构与迁移策略（本方案**零 schema 变更**）
- 不改判分、难度、掌握度、诊断、复习的算法与阈值
- 不引入构建工具、不引入新依赖、不引入 ES module
- 不引入 pytest 或任何新测试框架

---

## 2. 现状测量（P1 完成后重新实测）

> 行数为 **P1 注入契约卡之后**的实测值（每个文件 +9 行契约卡，逻辑零改动）。
> 撰写方案时的初测值与执行期变动见 `backup/ledger_P0_P1.md`「执行期发现」。

### 2.1 后端最大文件

| 文件 | 行数 | 估算 token | 备注 |
|---|---|---|---|
| `backend/review/engine.py` | 952 | 13501 | ReviewEngine 25 个方法，最长方法 `submit_review` 172 行 |
| `backend/verify_memory.py` | 774 | 11454 | V2.4 复习套件（已注册进 verify_all，端口 8906） |
| `backend/adaptive/engine.py` | 684 | 9188 | AdaptiveLearningEngine 25 个方法 |
| `backend/verify_knowledge.py` | 615 | 9095 | — |
| `backend/verify_adaptive.py` | 611 | 9075 | — |
| `backend/adaptive/strategy.py` | 564 | 7515 | — |
| `backend/bank_english.py` | 560 | 12216 | 题库数据 |
| `backend/diagnostic_routes.py` | 550 | 6229 | 路由 + 出题 + 审核 + profile 存储混杂 |
| `backend/main.py` | 549 | 6480 | `question` 183 行 + `submit` 129 行 |
| `backend/diagnostic_bank.py` | 525 | 6437 | 题库数据 |
| `backend/knowledge_routes.py` | 497 | 6237 | 掌握度写入口 + 报告 + 错因 + 错题 + 知识树混杂 |

> 全量：后端 44 个 py（不含 `_legacy/` 的 4 个）= 14347 行 ≈ 20.4 万 token；前端 17 个 js = 5222 行 ≈ 6.2 万 token。

### 2.2 前端最大文件

| 文件 | 行数 | 备注 |
|---|---|---|
| `frontend/verify_knowledge_web.js` | 646 | 沙箱加载 knowledge_map / wrong_book / study_advice |
| `frontend/verify_memory_web.js` | 444 | 沙箱加载 review（儿童端「知识浇水」）+ memory_debug（家长端记忆数据） |
| `frontend/today.js` | 443 | 30 个函数（渲染 + 事件 + 工具混排） |
| `frontend/app.js` | 440 | 28 个函数（语音 + 出题 + 复习面板混排） |
| `frontend/verify_diagnostic_web.js` | 405 | — |
| `frontend/verify_adaptive_web.js` | 374 | — |
| `frontend/review.js` | 352 | — |

### 2.3 重复实现清单

| 重复函数 | 出现位置 |
|---|---|
| `_fmt` | `knowledge_routes.py`、`review/engine.py`、`adaptive/engine.py` |
| `_as_dt` / `_parse_dt` / `to_dt` | `adaptive/strategy.py`、`review/forgetting.py`、`review/memory.py`、`srs.py` |
| `clamp01` / `clamp` | `adaptive/strategy.py`、`review/forgetting.py` |
| `_json_dumps` | `review/engine.py`（函数内 import json） |
| `grade_text` | `review/engine.py`、`main.py` |
| `$` / `esc` / `jsonFetch` / `currentStudentId` | 前端 **9 个 js 各写一份**（零构建约束下无法 import） |

### 2.4 定位歧义源

| 歧义 | 说明 | P1 处理后 |
|---|---|---|
| 复习双体系 | `srs.py`（V2.1，`reviews` 表，被 `main.py` `/submit` 与 `/reviews` 使用）与 `review/`（V2.4，`KnowledgeMemoryState`/`ReviewQueue` 表，被 `review_routes.py` 使用）并存 | 未消除（属 P2+ 范围），已在 `docs/MODULE_MAP.md` §1/§2 标注「旧体系 / 新体系」 |
| 自适应同名 | `backend/adaptive.py`（235B 死代码）与 `backend/adaptive/`（活代码子包）同名不同物 | **已消除**：死代码移至 `backend/_legacy/` |
| 死代码 | `adaptive.py`、`algorithm.py`、`ai_question.py`、`reward.py` —— 已 grep 确认全项目**零引用** | **已归档**至 `backend/_legacy/`（含 README 与「禁止接线」约束） |
| 测试索引缺口 | `verify_memory.py` 未注册进 `verify_all.py`，改 `review/` 时从编排里看不到该跑哪套 | **已消除**（执行期发现另一会话已补齐）：全量现为 **12 套件**，含 `memory`(8906) 与 `memweb` |

### 2.5 token 浪费的四个机制

1. **定位成本**：文件大 → grep 命中后必须读数百行上下文。
2. **歧义成本**：同名概念多套实现 → 找错文件、误判哪套是活的。
3. **契约缺失**：48 个后端模块只有 2 个 `__init__.py` 有分工表，其余要读实现才知道入口。
4. **重复实现**：同一工具函数多处重写，重复阅读与重复修改。

---

## 3. 能力索引表

> P1 阶段把本节内容落盘为 `docs/MODULE_MAP.md`，并在 `AI_RULES.md` 增加 §3.3 的任务速查表。
> 表名/类名在落盘时用 `grep -n "__tablename__" backend/models.py` 校验一次。

### 3.1 后端能力 → 文件 → 入口

| 能力 | 主文件 | 对外入口 | 模型类 | 验证套件 |
|---|---|---|---|---|
| 能力阶段 / 知识点唯一来源 | `stages.py` | `all_keys` `normalize_key` `difficulty_of` `knowledge_of` `advance` | — | 全部 |
| 知识点树 | `knowledge_tree.py` | `seed` `ensure_seeded` `link_mastery` `node_rows` | `KnowledgePoint` | knowledge |
| 掌握度模型 | `mastery.py` | `MasteryEngine.calculate_mastery` `level_of` `next_review_time` | `StudentKnowledgeMastery` | knowledge |
| 掌握度**唯一写入口** | `knowledge_routes.py` | `update_mastery` | `StudentKnowledgeMastery` | knowledge / flow / diagnostic |
| 错因分析 | `error_analysis.py` | `analyze` `rule_analyze` `summary` `dominant_error` `backfill` | `AnswerErrorAnalysis` | knowledge |
| 错题本 | `wrong_book.py` | `record_wrong` `record_correct` `items_for` `stats_for` | `WrongQuestion` | knowledge |
| 判分（唯一真相） | `grading.py` | `is_correct` `parse_options` `parse_acceptable` | — | flow |
| 题目质量审核 | `validator.py` | `QuestionValidator.validate` | — | flow / knowledge |
| AI 出题与错因深化 | `deepseek.py` | `generate_question` `analyze_error` `ability_block` | — | flow |
| 日常练习 API | `main.py` | `home` `students` `question` `submit` `reviews` | `Question` `AnswerRecord` `Ability` `Review` | flow |
| 艾宾浩斯复习（V2.1） | `srs.py` | `review` `apply_state` `due_items` `select_knowledge` `mastery` | `Review` | review |
| 诊断状态机 | `diagnostic.py` | `new_state` `record_answer` `evaluate_stage` `calculate_ability` `build_report` | — | diagnostic |
| 诊断题库 | `diagnostic_bank.py` `bank_chinese.py` `bank_english.py` | `build_question` `bank_size` | — | diagnostic |
| 诊断 API | `diagnostic_routes.py` | `start` `next_question` `submit_answer` `report` `profiles` | `DiagnosticSession` `DiagnosticRecord` `AbilityProfile` | diagnostic |
| 间隔复习（V2.4）门面 | `review/engine.py` | `ReviewEngine.today` `submit_review` `memory_map` `review_question` | `KnowledgeMemoryState` `ReviewQueue` `ReviewRecord` `ReviewStrategyLog` | memory |
| 记忆状态模型 | `review/memory.py` | `initial_learn_state` `maturity_of` `action_of` `state_summary` | — | memory |
| 遗忘风险 | `review/forgetting.py` | `ForgettingRiskEngine.calculate_forgetting_risk` | — | memory |
| 复习间隔 | `review/interval.py` | `calculate_next_interval` `quality_of` `ladder_preview` | — | memory |
| 复习队列调度 | `review/scheduler.py` | `ReviewScheduler.build` `summarize` | `ReviewQueue` | memory |
| 复习出题 | `review/selector.py` | `ReviewQuestionSelector.build` | `Question` | memory |
| 每日配比 | `review/mix.py` | `calculate_daily_mix` `split_counts` | — | memory / adaptive |
| 复习 API | `review_routes.py` | `/api/review/*` | — | memory |
| 自适应策略 | `adaptive/strategy.py` | `LearningStrategy.rank` `choose` `foundation_weight` | — | adaptive |
| 难度控制 | `adaptive/difficulty.py` | `DifficultyController.adjust` `stage_step` | — | adaptive |
| 自适应选题 | `adaptive/selector.py` | `QuestionSelector.select` `select_from_decision` | — | adaptive |
| 每日计划 | `adaptive/planner.py` | `DailyLearningPlanner.build` `ensure` `summary` | `LearningPlan` | adaptive |
| 自适应门面 | `adaptive/engine.py` | `AdaptiveLearningEngine.recommend` `next_spec` `plan` `start` `feedback` | `LearningStrategyLog` `LearningFeedback` | adaptive |
| 自适应 API | `adaptive_routes.py` | `/api/learning/*` | — | adaptive |
| 数据库与迁移 | `database.py` | `ensure_schema` `migrate_data` `get_db` | — | knowledge |
| 表模型 | `models.py` | `Base` + 15 个模型类 | 全部 | 全部 |
| 验证编排 | `verify_all.py` | `main` `SUITES` | — | — |

### 3.2 前端页面 → 脚本 → 验证

| 页面 | 脚本 | 验证脚本 |
|---|---|---|
| `index.html` | `app.js`（+ `phoebe.js`） | `verify_web.js`、`verify_phoebe_web.js` |
| `today.html` | `today.js` | `verify_adaptive_web.js` |
| `diagnostic.html` | `diagnostic.js` | `verify_diagnostic_web.js` |
| `diagnostic_test.html` | `diagnostic_test.js`（+ `phoebe.js`） | `verify_diagnostic_web.js`、`verify_phoebe_web.js` |
| `diagnostic_report.html` | `diagnostic_report.js` | `verify_diagnostic_web.js` |
| `knowledge_map.html` | `knowledge_map.js` | `verify_knowledge_web.js` |
| `wrong_book.html` | `wrong_book.js`（+ `phoebe.js`） | `verify_knowledge_web.js`、`verify_phoebe_web.js` |
| `study_advice.html` | `study_advice.js` | `verify_knowledge_web.js` |
| `review.html` | `review.js` | —（无独立前端套件，靠后端 memory 套件 + 人工） |
| `memory_debug.html` | `memory_debug.js` | —（调试页） |

### 3.3 任务速查表（改 X 只需读这些 + 跑这套）

| 需求 | 读这些文件 | 验证命令 |
|---|---|---|
| 调整复习间隔阶梯 | `review/interval.py` | `python backend/verify_memory.py` |
| 调整遗忘风险公式 | `review/forgetting.py` | `python backend/verify_memory.py` |
| 改复习队列优先级/每日上限 | `review/scheduler.py` `review/mix.py` | `python backend/verify_memory.py` |
| 改复习提交后的状态推进 | `review/engine.py`（`submit_review`）+ `review/interval.py` | `python backend/verify_memory.py` |
| 改艾宾浩斯旧阶梯 | `srs.py` | `python backend/verify_review.py` |
| 改难度升降阈值 | `adaptive/difficulty.py` | `python backend/verify_adaptive.py` |
| 改知识点优先级/依赖门控 | `adaptive/strategy.py` | `python backend/verify_adaptive.py` |
| 改下一题推荐配比 | `adaptive/selector.py` | `python backend/verify_adaptive.py` |
| 改今日计划分配 | `adaptive/planner.py` | `python backend/verify_adaptive.py` |
| 改 `/submit` 写库步骤 | `main.py`（`submit`）+ `knowledge_routes.py`（`update_mastery`）+ `srs.py` | `python backend/verify_flow.py --self-serve` |
| 改出题与审核 | `deepseek.py` `validator.py` | `python backend/verify_flow.py --self-serve` |
| 改掌握度模型 | `mastery.py` | `python backend/verify_knowledge.py` |
| 改错因规则/文案 | `error_analysis.py` | `python backend/verify_knowledge.py` |
| 改错题本状态机 | `wrong_book.py` | `python backend/verify_knowledge.py` |
| 改诊断阶段判定 | `diagnostic.py` | `python backend/verify_diagnostic.py` |
| 加/改知识点或阶段 | `stages.py` + `knowledge_tree.py` + `adaptive/strategy.py`（依赖表） | `python backend/verify_all.py`（全套） |
| 改今日学习页 | `frontend/today.js` `frontend/today.html` | `node frontend/verify_adaptive_web.js` |
| 改练习页 | `frontend/app.js` | `node frontend/verify_web.js` |
| 改庆祝浮层 | `frontend/phoebe.js` | `node frontend/verify_phoebe_web.js` |
| 改知识三页 | `frontend/knowledge_map.js` `wrong_book.js` `study_advice.js` | `node frontend/verify_knowledge_web.js` |

---

## 4. 目标架构规范

### 4.1 三条铁律

- **R1 一文件一能力**：文件名即能力名；单文件 **≤250 行**（≈3k token，可一次读完）。超限必须继续切片。
- **R2 一能力一入口**：对外只暴露一个类或一组同名函数，其余以 `_` 前缀私有。
- **R3 每模块必带契约卡**：文件头固定 10 行模板（见 §4.3）。

### 4.2 Mixin 使用规范（防止"拆完更难找"）

1. **只在「数据库门面/编排类」上用 mixin**（`ReviewEngine`、`AdaptiveLearningEngine`）。
   纯算法模块（`interval` `memory` `forgetting` `strategy` `difficulty` `selector` `planner` `mix`）**不做 mixin** —— 它们已是纯函数，加 mixin 只是增加间接层。
2. **Mixin 之间只能通过 `self.` 公共方法互相调用**；`_private` 方法仅限本 mixin 内部使用。
3. **方法名全局唯一**：多继承下同名方法静默覆盖 → 新增 `backend/check_mixin_conflicts.py`（ast 扫描全部 mixin 的重复方法名），纳入 `verify_all.py` 作为第 0 个检查项。
4. **门面只做组装**：`engine.py` 只含 `class XxxEngine(MixinA, MixinB, ...)` + `DEFAULT_ENGINE` + 模块常量，不含业务逻辑。
5. **超 40 行的过程必须下沉**：抽为同级纯函数模块（如 `review/quality.py`），保持无 DB 依赖、可单独断言。

### 4.3 契约卡模板（文件头，固定顺序）

```python
"""<能力名> · <一句话职责>

职责：<这个文件负责什么，1~3 条>
入口：<对外符号清单>
依赖：<import 的模块/表>
不负责：<容易混淆的邻居职责> → 见 <正确文件>
验证：python backend/verify_xxx.py
被调用：<哪些模块引用它>
"""
```

### 4.4 shim 兼容层规范

重构中需要"移动文件但保持旧 import 路径可用"时，旧文件降级为 shim：

- **只允许** `from <新位置> import <符号>` 与 `__all__`，**禁止任何逻辑**。
- 文件头第一行注明：`"""兼容层（shim）· 逻辑已迁至 xxx/yyy.py，勿在此修改业务。"""`
- 目的：让 `verify_*.py` 与既有 `from X import Y` 全部不改动即可通过。

---

## 5. 拆分清单（P2~P5 执行时照此落地）

### 5.1 `backend/review/engine.py`：937 行 → 门面 + 8 mixin

| 目标文件 | 收纳方法 | 约行数 |
|---|---|---|
| `review/engine.py` | 组装 mixin + `DEFAULT_ENGINE` + 常量 | 80 |
| `review/mixins/state.py` | `state_row` `states_of` `state_summary` `ensure_states` `_apply_state` | 140 |
| `review/mixins/learning.py` | `record_learning` | 70 |
| `review/mixins/risk.py` | `refresh_risks` | 40 |
| `review/mixins/queue.py` | `queue_for` `schedule` `today` `due` `_mark_queue` `_child_title` | 180 |
| `review/mixins/practice.py` | `review_question` `submit_review` `_child_message` | 150 |
| `review/quality.py`（新纯函数） | `_grade_review` `_advance_after_review` `_handle_failure` `_append_verify`（拆解 172 行的 `submit_review`） | 120 |
| `review/mixins/feedback.py` | `skip` `apply_feedback` | 90 |
| `review/mixins/report.py` | `memory_map` `stats` `mix_for` | 80 |
| `review/mixins/log.py` | `log_strategy` `strategy_logs` `review_history` | 70 |
| `review/mixins/__init__.py` | 契约卡 + **方法 → mixin 文件**索引表 | 30 |

**外部接口保持不变**：`from review import engine` → `engine.DEFAULT_ENGINE.*`（方法名与签名一字不改）。

### 5.2 `backend/adaptive/engine.py`：677 行 → 门面 + 6 mixin

| 目标文件 | 收纳方法 | 约行数 |
|---|---|---|
| `adaptive/engine.py` | 组装 + `DEFAULT_ENGINE` | 80 |
| `adaptive/mixins/profile.py` | `ability_of` `error_counts` `recent_records` `recent_knowledge` `last_feel` `memory_rows` `profile` `profiles` | 150 |
| `adaptive/mixins/decision.py` | `difficulty_state` `decision_for` `next_spec` | 130 |
| `adaptive/mixins/plan.py` | `plan` | 60 |
| `adaptive/mixins/recommend.py` | `recommend` `_review_action` `_message_of` | 110 |
| `adaptive/mixins/session.py` | `start` `feedback` `_feedback_message` `_advance_plan` | 130 |
| `adaptive/mixins/log.py` | `log` `strategy_logs` `feedback_history` | 70 |
| `adaptive/mixins/__init__.py` | 契约卡 + 方法索引 | 30 |

**注意**：`adaptive/engine.py` 有 `from knowledge_routes import _mastery_items`，拆 mixin 后该 import 落在 `mixins/profile.py`，`knowledge_routes` 的 shim 必须继续导出 `_mastery_items`。

### 5.3 路由层拆分

| 现状 | 目标 |
|---|---|
| `main.py` 541 行 | 只留 app 装配 + CORS + router 注册 + `/app` 挂载 + **import 期副作用**（≤110 行）；业务迁 `practice_routes.py` |
| `main.py:question` 183 行 | `practice/question_service.py`：`select_knowledge` `generate_and_validate` `persist_question` `public_payload`（各 ≤40 行） |
| `main.py:submit` 129 行 | `practice/submit_service.py`：判分 → 能力 → 复习 → 掌握度 → 错因 → 错题本 六步各一函数 |
| `knowledge_routes.py` 490 行 | `knowledge/mastery_routes.py`（含 `update_mastery` `_mastery_items`）`report_routes.py` `error_routes.py` `wrong_routes.py` `tree_routes.py`；原文件降级 shim |
| `diagnostic_routes.py` 543 行 | `diagnostic/session_routes.py` `profile_routes.py` `question_service.py`；原文件降级 shim |
| `adaptive_routes.py` / `review_routes.py`（各 ~180 行） | 只加契约卡 + 去重 `_subject_or_400` |

**硬约束**：`adaptive/engine.py` 内部 `import main` 复用 `main.question` → `main` 模块**必须继续存在 `question` 符号**（薄壳委派给 `practice/question_service.py`）。

### 5.4 共享纯函数与模型拆包（P4）

| 目标文件 | 收纳 | 替换点 |
|---|---|---|
| `util/timeutil.py` | `now_ts` `to_dt` `parse_dt` `fmt` `day_start` `clamp01` | `srs.py`、`review/engine.py`、`review/forgetting.py`、`review/memory.py`、`adaptive/engine.py`、`adaptive/strategy.py` |
| `util/textutil.py` | `normalize` `json_dumps` | `grading.py`、`review/engine.py`、`error_analysis.py` |
| `util/grade.py` | `grade_text` | `review/engine.py`、`main.py` |
| `models/` 包 | `base.py` `student.py` `practice.py` `diagnostic.py` `knowledge.py` `memory.py` `adaptive.py` | `models.py` 降级 shim |

**关键坑**：`models.py` 降级 shim 时**必须 import 全部子模块**（否则 `Base.metadata.create_all` 漏建表）；`srs.py` 被 `verify_review.py` 直接断言 → 只换内部实现，**函数签名与返回值一字不改**。

### 5.5 前端（P5）

分 4 步，每步可独立验收：

1. **页内分区 + 契约卡**（零风险）：每个业务 js 顶部加契约卡，函数按 `// ==== 工具 / 渲染 / 事件 / 初始化 ====` 分区。
2. **页内重排**（零风险）：同类函数相邻，不改函数名、不改 DOM id。
3. **抽 `frontend/shared/core.js`**：全局命名空间 `window.XZ`，收纳 `$` `esc` `jsonFetch` `query` `currentStudentId` `store` `restore` `percent` `starText` `barWidth` `masteryClass` `levelClass`。各页 HTML 在业务 js **之前**引入。
   ⚠️ **同步成本**：`verify_web.js`（`app.js`）、`verify_diagnostic_web.js`、`verify_adaptive_web.js`、`verify_knowledge_web.js`、`verify_phoebe_web.js` 用 vm 沙箱按**固定 js 清单**加载并断言全局函数名 —— 新增脚本必须同步改这些测试的加载列表与断言，否则全红。**测试改动必须与代码同批完成。**
4. **逐页瘦身**：每页 js 只留页面专属渲染与交互。

---

## 6. 红线（任何阶段都不得违反）

| # | 约束 | 依据 |
|---|---|---|
| 1 | 接口只允许新增字段，禁止删除/改名/改语义；非法参数 400、资源不存在 404 保持不变 | `AI_RULES.md` 13.5 |
| 2 | 表结构零变化；迁移只允许 `ALTER TABLE ADD COLUMN`，回填幂等 | 13.2 |
| 3 | 建表 / `ensure_schema` / `migrate_data` / `init_default_users` / `ensure_seeded` / `link_mastery` / `error_analysis.backfill` **必须留在 `main.py` 的 import 期** | 13.2 |
| 4 | 24 阶段与每科 24 知识点为全局不变量；`stages.py`、`knowledge_tree.py` 仍是唯一真相源 | 13.1 |
| 5 | 判分只走 `grading.is_correct`；掌握度写入口只走 `update_mastery`；`reviews` 的 `stage/streak/next_review_at` 只经 `srs.review`+`srs.apply_state` | 13.3 / 13.4 |
| 6 | 诊断链路不写 `answer_records`、不改 `abilities`；出题接口不下发 `answer`/`analysis` | 13.4 / 13.3 |
| 7 | 题库题入库前必须过 `validator.QuestionValidator.validate` | 13.3 |
| 8 | 外部调用必须有本地兜底且不阻塞 `/submit` 与诊断答题（`use_ai=False`）；密钥只从 env/`.env` 读 | 13.6 |
| 9 | 前端零构建：禁 npm/bundler/CDN/ES module；`phoebe.js` 必须先于业务 js 加载；改前端跑对应 `verify_*_web.js` | 13.7 |
| 10 | 验证只走 `verify_all.py` 与既有套件；禁止并发跑多套件；测试必须用 `_verify_*.db` 临时库，禁止写 `backend/learning.db` | 13.8 |
| 11 | 验证脚本的既有 import 路径必须原样可用（`from adaptive import difficulty...`、`import srs`、`from models import ...`） | 测试基线 |
| 12 | 死代码（`adaptive.py` `algorithm.py` `ai_question.py` `reward.py`）只允许**归档**，禁止接线或删除 | 13.9 |

---

## 7. token 收益量化

| 场景 | 现状（估） | 目标 |
|---|---|---|
| 调整复习间隔阶梯 | grep → 读 `review/interval.py` + 误入 `srs.py` + 翻 `review/engine.py` 调用段 ≈ 900~1200 行 / 13k token | 契约卡 + `review/interval.py` ≤350 行 / 4.5k token |
| 改 `/submit` 写库步骤 | 读 `main.py` `submit` 129 行 + 上下文 ≈ 500 行 | 读 `practice/submit_service.py` ≤250 行 |
| 改前端某页工具函数 | 9 份重复逐个确认 | 读 `shared/core.js` 一处 |
| 单任务平均 | 2~4 文件、600~1200 行、3~6 次工具调用 | **≤2 文件、≤400 行、≤6k token、≤2 次调用** |

---

## 8. 实施路线与验收

| 阶段 | 内容 | 风险 | 验收判据 | 回退 |
|---|---|---|---|---|
| **P0 准备** ✅ | ① ~~`git init`~~（**本机未安装 git** → 改用目录快照）② 备份 `learning.db` + 全项目快照到 `backup/snapshots/P0_baseline/` ③ 跑 `verify_all.py` 记录基线 | 无 | 基线写入 §9.2；快照 102 文件 / 1.87 MB 存在 | 从快照复制回退 |
| **P1 零逻辑风险** ✅ | ① 死代码归档 `backend/_legacy/`（4 个文件 + README）② **65 个模块**补契约卡（48 py + 17 js）③ 建 `docs/MODULE_MAP.md` + `AI_RULES.md` §3/§5.1/§11 ④ `verify_memory.py` 进编排（**执行期发现另一会话已完成**，无需改动） | 无 | `verify_all.py` 全绿且**断言数 = 基线 849** | 从 `backup/snapshots/P0_baseline/` 复制回退 |
| **P2 后端 mixin 化** | 先 `review/engine.py`（测试最厚：memory/review/flow/knowledge）→ 再 `adaptive/engine.py`；每拆一个 mixin 跑对应套件 | 中 | 每步：对应套件 + `verify_all.py` 全绿；`check_mixin_conflicts.py` 无冲突 | git 回退该阶段提交 |
| **P3 路由拆分** | `main.py` → `practice_routes.py` + `question_service.py` + `submit_service.py`；`knowledge_routes.py` / `diagnostic_routes.py` → 包 + shim | 中 | flow / knowledge / diagnostic / adaptive 四套件 + 全量 | 同上 |
| **P4 去重** | `util/` 共享纯函数 + `models/` 拆包（shim 必须 import 全部子模块） | 中低 | `verify_all.py` + `verify_memory.py` 全绿；`create_all` 建表数与基线一致 | 同上 |
| **P5 前端** | 4 步走，第 3 步起必须同步改 5 个前端测试 | 中 | `verify_*_web.js` 全绿 + 浏览器强刷人工确认 | 同上 |
| **P6 收尾** | 更新 `PROJECT_CONTEXT.md` §3/§4/§5 与 `AI_RULES.md` §5 例外条款 | 无 | 文档与代码一致 | — |

**阶段执行纪律**：① 每阶段一次 git 提交；② 每阶段结束跑一次 `verify_all.py`（约 74s，可接受）；③ 阶段内小步改动只跑对应套件，不重复全量。

---

## 9. 已确认决策

### 9.1 本轮确认结果

| 项 | 决定 | 执行结果 |
|---|---|---|
| 执行范围 | **先做 P0 + P1（零逻辑风险）** | ✅ 已完成（见 §9.2） |
| 安全网 | 允许 `git init` + 初始提交 | ⚠️ **本机未安装 git** → 改用 `backup/snapshots/` 目录快照（`backup/README.md` 含回退命令） |
| 附加范围（总范围，按阶段落地） | 死代码归档（P1）、补 `verify_memory` 进编排（P1）、`backend/util/`（P4）、`models/` 拆包（P4）、前端 `shared/core.js`（P5） | P1 两项完成（编排项经查已由另一会话先行完成）；`util/`、`models/`、`shared/core.js` 待 P4/P5 |
| 方案落盘 | 已落盘为本文件 | ✅ 另有 `docs/MODULE_MAP.md`、`backup/ledger_P0_P1.md` |
| 当前状态 | — | ✅ **P0 + P1 完成；P2 起未执行** |

> 附加范围与阶段的关系：勾选项进入**总范围**，但 `util/` `models/` `shared/core.js` 属于 P4/P5，**不在 P1 执行**。

### 9.2 验证基线（实测）

| 项 | 值 |
|---|---|
| `python backend/verify_all.py`（P0 基线） | `RESULT: ALL PASS`，12 套件，**PASS=849 / FAIL=0**，99.2s |
| `python backend/verify_memory.py`（P0 基线） | `RESULT: ALL PASS`，**PASS=145 / FAIL=0**（该套件已含在 verify_all 的 `memory` 项内） |
| `python backend/verify_all.py`（**P1 复验**） | `RESULT: ALL PASS`，12 套件，**PASS=849 / FAIL=0**，101.1s → **断言数与基线完全一致，证明零逻辑改动** |
| 契约卡重定位后（**最终复验**） | `RESULT: ALL PASS`，12 套件，**PASS=849 / FAIL=0**，102.8s（日志 `backup/post_p1_final_verify_all.txt`） |
| 契约卡覆盖度 | 后端 **48/48**、前端 **17/17**，全部落在文件**前 12 行内** |
| 审查修复后（**终态**） | `RESULT: ALL PASS`，12 套件，**PASS=849 / FAIL=0**，99.4s（日志 `backup/post_review_verify_all.txt`） |
| 契约卡门禁 | `python backend/check_cards.py` → 66 模块 / 失实符号 **0** / 退出码 0（**刻意不纳入 verify_all**，以免改变 849 基线） |
| 语法校验（注入契约卡后） | `ast.parse` 48/48 通过；`node --check` 17/17 通过 |
| git 初始提交 hash | 不适用（本机未安装 git） |
| 快照路径 | `backup/snapshots/P0_baseline/`（102 文件 / 1.87 MB）+ `learning.db.P0-backup` |
| 日志 | `backup/baseline_verify_all.txt`、`backup/baseline_verify_memory.txt`、`backup/post_p1_verify_all.txt`、`backup/post_p1_final_verify_all.txt` |
| 执行记录 | `backup/ledger_P0_P1.md`（含执行期发现 T/U/V/W 与全部 Ruling） |

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 多继承同名方法静默覆盖 | `backend/check_mixin_conflicts.py`（ast 扫描）纳入 `verify_all.py` |
| 拆完调用链跨文件，grep 找方法要多跳 | `mixins/__init__.py` 契约卡内放**方法 → mixin 文件**索引表 |
| mixin 私有方法被跨文件调用形成隐式耦合 | §4.2 规范 2；review 检查项 |
| 循环 import | mixins 只依赖 `models` + 同级纯函数模块；组装只在 `engine.py`；`review/__init__.py` 已确立"`engine` 不进 `__init__` 导入链"的既有做法，沿用 |
| shim 层堆积成新迷宫 | shim 只许 re-export，禁止逻辑，文件头标注 |
| `models/` 拆包漏表 | shim `models.py` 必须 import 全部子模块；P4 后断言建表数量 |
| 前端测试断言全局函数名与 DOM id | 前端改动与测试改动同批提交，否则不合并 |
| 与 `AI_RULES.md` §5"不引入新架构层"冲突 | 本次为明确授权的架构重构；P1 阶段即更新 §5 例外条款与 `PROJECT_CONTEXT.md` §8 决策记录 |
| 项目无 git / `learning.db` 是真实数据 | P0 强制 git init + 初始提交 + 单独备份 db |

---

## 11. 验证命令速查

```powershell
# 全量（12 个套件，串行，各自独立端口与临时库）
python backend\verify_all.py

# 子集（示例）
python backend\verify_all.py adaptive adaptweb

# 单套件
python backend\verify_review.py          # 艾宾浩斯旧体系，端口 8899
python backend\verify_flow.py --self-serve   # 学习闭环，端口 8900
python backend\verify_diagnostic.py      # 能力诊断，端口 8902
python backend\verify_knowledge.py       # 知识/错因/错题，端口 8904
python backend\verify_adaptive.py        # 自适应引擎，端口 8905
python backend\verify_memory.py          # V2.4 间隔复习，端口 8906（已含在 verify_all 的 memory 项内）
python backend\verify_port_guard.py      # 端口守卫，与全量互斥

# 前端（系统无 node 时用捆绑 node）
node frontend\verify_web.js
node frontend\verify_diagnostic_web.js
node frontend\verify_knowledge_web.js
node frontend\verify_adaptive_web.js
node frontend\verify_memory_web.js
node frontend\verify_phoebe_web.js
# 捆绑 node：C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe
```

**纪律**：端口被占用时套件**故意失败**（防止"假通过"），不要改成自动换端口；禁止并发跑多套件；测试只用 `_verify_*.db`。
