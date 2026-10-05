# Project AI Rules

> 本文件定义当前项目专属的 AI 开发规则。
> 全局规则由 DSH `AGENTS.md` 提供。
> 本文件只记录项目特有约束，不重复全局规则。

## 1. Project Priority

本项目优先级：

1. 正确性。
2. 向后兼容。
3. 稳定性。
4. 可维护性。
5. 最小修改。
6. 性能优化。

## 2. Scope Control

每次任务只修改完成目标所需的最小范围。

禁止：

- 无关重构。
- 无要求的目录调整。
- 无要求的命名批量修改。
- 无要求的依赖升级。
- 顺手修复与当前任务无关的问题。

发现无关问题时，只报告，不自动扩大任务范围。

## 3. Code Reading

优先读取：

1. `docs/MODULE_MAP.md` —— 能力索引表（能力 → 文件 → 入口 → 表 → 验证套件），**定位代码的唯一入口**，禁止跳过它直接全仓扫描
2. `PROJECT_CONTEXT.md`
3. 当前任务明确涉及的文件
4. 直接调用链
5. 相关测试
6. 必要配置

默认不要读取：

- `node_modules/`
- `vendor/`
- `dist/`
- `build/`
- `.git/`
- 自动生成文件
- 大型日志
- 与当前任务无关的历史文件

除非任务证据明确要求。

## 4. Editing

采用 `Minimal Diff`。

优先：

- 修改已有函数。
- 复用已有工具函数。
- 复用已有组件。
- 复用已有项目模式。
- 保持现有命名风格。
- 保持现有目录结构。

避免：

- 为局部问题创建过度抽象。
- 新建不必要的 wrapper/helper。
- 重写整个文件。
- 改变公共接口。

如果公共接口必须改变，应先确认所有直接调用方。

## 5. Architecture

遵守现有架构。

在没有明确必要性的情况下：

- 不引入新的架构层。
- 不引入新的状态管理方案。
- 不引入新的通信机制。
- 不改变数据流方向。
- 不替换已有技术栈。

如果现有架构已有明确模式，优先复用。

### 5.1 已授权例外（架构重构）

`docs/架构重构_Mixin方案.md` 定义的架构重构**已获用户明确授权**，允许在方案范围内：

- 按能力切片拆分现有模块，新增 `backend/review/mixins/`、`backend/adaptive/mixins/`、`backend/practice/`、`backend/knowledge/`、`backend/diagnostic/` 等子包。
- 新增 `backend/util/` 共享纯函数层（消除 `_fmt` / `_as_dt` / `clamp01` 等重复实现）。
- 将 `models.py` 拆为 `models/` 包，原文件降级为只做 re-export 的 shim。
- 旧文件降级为 shim 兼容层（只允许 re-export，禁止承载逻辑）；门面类用 mixin 组合。

该例外**仅限方案列出的范围**。方案之外，§5 原有约束（不引入新技术栈、不引入新状态管理、不改变数据流方向）继续有效。
同时新增硬约束：**单文件 ≤250 行**（超出必须按能力继续切片）；每个模块文件头必须有契约卡（职责 / 入口 / 依赖 / 不负责 / 验证命令）；**改动任何契约卡后必须运行 `python backend/check_cards.py`**（校验卡片里列出的入口符号真实存在 —— 写不存在的符号比不写卡片更糟，会让 agent 按卡 grep 后扑空；该脚本刻意不纳入 `verify_all`，以免改变其 849 断言基线）。

## 6. Dependencies

新增依赖前确认：

1. 项目是否已有等价能力。
2. 标准库或现有依赖是否足够。
3. 新依赖是否真的必要。
4. 是否会增加构建体积、复杂度或维护成本。

没有明显收益时，不新增依赖。

## 7. Debugging

调试顺序：

1. 错误信息。
2. 最近相关修改。
3. 目标函数。
4. 直接调用链。
5. 输入数据。
6. 相关测试。
7. 必要时再扩大范围。

不要一开始扫描整个项目。

每次应优先验证最高概率假设。

## 8. Testing Strategy

默认验证顺序：

```text
targeted test
    ↓
related test file
    ↓
affected module
    ↓
lint / typecheck
    ↓
full suite（仅必要时）
```

小范围、低风险修改：

- 运行直接相关测试。
- 不默认执行完整回归。

高风险修改：

- authentication
- authorization
- database
- migration
- concurrency
- async lifecycle
- shared state
- cache consistency
- transaction
- public API
- network protocol

需要扩大验证范围，但仍避免重复验证。

## 9. Test Reuse

如果以下内容均未变化：

- 被测代码。
- 测试代码。
- 依赖。
- 配置。
- 环境变量。
- fixture / 数据输入。

则之前成功的测试结果可以继续视为有效证据。

不要仅为了“再次确认”而重复运行相同测试。

## 10. Validation Commands

优先使用项目已有脚本。

如果存在以下命令，应优先使用项目实际定义的版本：

```text
check-fast
check-affected
check-full
test-fast
test-unit
test-all
lint
typecheck
verify
```

不要重新拼装与项目已有脚本等价的一长串命令。

## 11. Context Updates

以下变化完成后，**必须**更新 `docs/MODULE_MAP.md`（能力索引表）：新增 / 删除 / 改名任何模块、入口符号或验证套件。索引表未同步 = 改动未完成。

以下变化完成后，更新 `PROJECT_CONTEXT.md`：

- 技术栈变化。
- 新增核心模块。
- 删除核心模块。
- 目录职责发生变化。
- API / 数据流发生变化。
- 新的重要架构决策。
- 新的重要限制。
- 项目验证命令发生变化。

不要因为普通局部 bug fix 更新大量项目上下文。

## 12. Output

默认使用简洁格式：

```text
修改：
- ...

原因：
- ...

验证：
- ...
```

代码修改优先展示 diff 或关键改动。

除非用户明确要求，否则不要：

- 输出整个大型文件。
- 重复解释项目背景。
- 输出无关教程。
- 复述所有工具调用过程。

## 13. Project-Specific Rules

以下为本项目独有的硬约束（依据实际代码与 `PROJECT_CONTEXT.md` 整理）。
违反任一条都可能破坏数据、判分或测试基线；确需突破时，先在本文件与 `PROJECT_CONTEXT.md` 中记录原因。

### 13.1 单一真相源

- 能力阶段、难度值、知识点、升降级阈值**只能**定义在 `backend/stages.py`；知识点树节点**只能**定义在 `backend/knowledge_tree.py`。禁止在其他模块另写一套阶段表或知识点表。
- **24 阶段（1.1~6.4）与每科 24 个知识点是全局不变量**：诊断题库（`diagnostic_bank.py`、`bank_chinese.py`、`bank_english.py`）、掌握度、前端均按此对齐。改动阶段数量或顺序必须同步全部相关模块，并跑 `verify_diagnostic.py` + `verify_knowledge.py`。
- 科目固定数学/语文/英语，年级固定 1~6。新增科目必须同时补齐：`stages.SUBJECTS`、`stages.KNOWLEDGE`、`error_analysis` 错误类型表、`validator` 学科分支、分级题库、前端默认知识点。
- `data/` 下的 JSON **不是运行时数据源**，改它们不影响系统行为。不要在未同步更新 `PROJECT_CONTEXT.md` 的前提下新增对 `data/` 的读取依赖。

### 13.2 数据库与迁移

- 迁移**只能加列**（`database.ensure_schema` 的 `ALTER TABLE ... ADD COLUMN`）：禁止删表、重建表、删除或改名旧列；新字段的回填必须是幂等的（`migrate_data`）。
- 旧列必须原样保留，保证随时可回退。
- 任何 schema / 迁移改动后必须跑 `python backend/verify_knowledge.py`（内含 V2.2→V2.3 迁移与回填断言）。
- 启动副作用（建表、迁移、灌知识点树、错因回填）**必须留在 `main.py` 的 import 期**，不要挪到 lifespan 或首个请求里。若要启用多 worker，必须先把这些副作用移出 import 期。

### 13.3 判分与答案

- 出题接口（`GET /question`、`GET /api/diagnostic/question`）**禁止**下发 `answer` / `analysis`。
- 判分只能走 `grading.is_correct`，前端不得保存、缓存或推断答案。
- 所有题目入库前**必须**过 `validator.QuestionValidator.validate`；不合格重试一次，仍不合格必须回落到内置兜底题。禁止绕过审核或直接返回未审题目。

### 13.4 数据隔离与写入路径

- 诊断链路禁止写 `answer_records`、禁止修改 `abilities`；诊断数据只进 `diagnostic_sessions` / `diagnostic_records` / `ability_profile`。
- 掌握度写入统一走 `knowledge_routes.update_mastery`（`/submit`、诊断答题、错题再练三处均复用它）。不要在别处直接 upsert `student_knowledge_mastery` 或自行累加分数——MasteryEngine 每次按该知识点全量历史重算。
- `reviews` 表的 `stage` / `streak` / `next_review_at` 只能经 `srs.review` + `srs.apply_state` 变更；禁止在路由或前端直接改这些字段。

### 13.5 接口兼容

- 已发布接口（`GET /question`、`POST /submit`、`GET /reviews`、`/api/diagnostic/*`、`/api/*`）只允许**新增**字段；禁止删除、改名或改变既有字段含义。
- 保持现有错误语义：非法参数 400、资源不存在 404。

### 13.6 外部依赖

- 任何外部调用都必须有本地兜底路径，且**不得阻塞** `/submit` 与诊断答题（这两条链路按设计传 `use_ai=False`）。
- 禁止硬编码密钥；密钥只从环境变量 `DEEPSEEK_API_KEY` 或 `backend/.env` 读取（`deepseek.py:_load_key()`）。`KEY` 在 import 时求值一次，改 `.env` 后必须重启进程。
- 语音朗读必须使用浏览器原生 Web Speech API，不得引入付费 TTS 服务。

### 13.7 前端

- 保持零构建：禁止引入 npm、bundler、CDN 或 ES module `import`/`export`；保持「一页 = 同名 `.html` + 同名 `.js`」。
- `phoebe.js` 必须在业务 js **之前**加载（练习页、诊断答题页、错题页）。
- 改任何 `frontend/*.js|html|css` 后必须跑对应的 `frontend/verify_*.js`。这些测试会断言 HTML 元素 id、脚本引用与加载顺序，改 id 或函数名会连带失败。
- 静态资源无缓存版本串，改完前端必须强制刷新浏览器。

### 13.8 测试纪律

- 验证只能通过 `python backend/verify_all.py` 或其套件（`verify_review` / `verify_flow` / `verify_diagnostic` / `verify_knowledge` / `verify_port_guard`）以及 `frontend/verify_*.js`。项目**无** pytest，不要引入新的测试框架。
- 套件端口固定为 8899 / 8900 / 8902 / 8904。端口被占用时套件会**故意失败**（防止连上别人的服务造成"假通过"），这是设计，不要改成自动换端口。
- 禁止并发运行多个套件；`verify_port_guard.py` 与全量测试互斥。
- 测试必须使用 `_verify_*.db` 临时库，**禁止**让测试写入 `backend/learning.db`：跑 `verify_flow.py` 时必须带 `--self-serve`。

### 13.9 禁区

- `backend/adaptive.py`、`algorithm.py`、`ai_question.py`、`reward.py` 是未接线死代码：未经确认不要接线或删除。其中 `reward.py` 引用了 `Student` 上不存在的列，一旦接线即 `AttributeError`。
- `backend/learning.db` 是真实使用数据：调试与测试禁止写入。项目无 git，改动前先手工备份。
- 文档与代码冲突时以**代码实现**为准，并更新文档；不要为了让代码符合旧文档而改动已生效逻辑。
