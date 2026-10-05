# TEST_REPORT.md — V2.5「错题康复系统 + 每日学习习惯系统」验证报告

- 负责人：Agent 7（Testing Engineer），任务 `qa-suites`
- 交付物：`backend/verify_recovery.py`（新建）、`backend/verify_habit.py`（新建）、本报告
- 环境：`C:\Python313\python.exe`（Python 3.13 / fastapi 0.142.2 / sqlalchemy 2.1.3 / requests）
- 测试方式：项目自有套件形态（自建临时子进程后端 + 临时 SQLite 库 + 固定端口 + `RESULT` 行 + 退出码 0/1），不引入 pytest 或任何新依赖
- 未触碰：`backend/learning.db`（两套件均通过 `DATABASE_URL` 指向 `backend/_verify_recovery.db` / `backend/_verify_habit.db`，跑完删除；实测两库无残留，且 `learning.db` 在被另一进程占用期间 mtime 未变）

## 1. 运行命令与实测结果

严格串行（端口固定 8910 / 8911，被占用即故意失败，不做自动换端口）：

```powershell
C:\Python313\python.exe backend\verify_recovery.py
C:\Python313\python.exe backend\verify_habit.py
C:\Python313\python.exe backend\check_cards.py   # 模块契约卡自检
```

| 命令 | 断言 | 结果 | 耗时 | 退出码 |
|---|---|---|---|---|
| `verify_recovery.py` | 94 | PASS 94 / FAIL 0 · `RESULT: ALL PASS` | 4.4s | 0 |
| `verify_habit.py` | 79 | PASS 79 / FAIL 0 · `RESULT: ALL PASS` | 5.3s | 0 |
| `check_cards.py` | — | 校验模块数 90 / 无卡片 0 / 失实符号 0 / 需人工确认 9（均为既有套件） | — | 0 |

**断言总数 173**（recovery 94 + habit 79），全部通过；两套件均打印断言条数并输出 `RESULT: ALL PASS`。

`check_cards.py` 的「需人工确认 9」全部是既有套件（verify_ability/adaptive/diagnostic/flow/knowledge/memory/phoebe_ai/port_guard/review），本次新增的两个套件不在该清单内。

## 2. 覆盖项与断言点（分用例实测）

两套件均自建临时 app（子进程 `uvicorn` 内联 FastAPI，只 include 被测 router），**不依赖 `main.py` 是否已注册**：recovery 套件 include `recovery_routes.router`，habit 套件 include `task_routes.router` + `habit_routes.router`。所有 HTTP 断言都是真实请求（`requests` → 127.0.0.1:PORT）。

### 2.1 `backend/verify_recovery.py`（key `recovery` · port 8910）

| 用例 | 断言 | 断言点与实测 |
|---|---|---|
| `compat_case` | 9 | V2.4 数据兼容（见 §3），含临时后端启动 1 项 |
| `list_case` | 14 | `GET /api/recovery/list` 200 且字段齐全；`stats` 六态 + `total` + `mastered_rate`；`stats.total == len(items) == 5`；item 字段齐全；新入队项 `NEW` + 中文文案；`state=NEW` 过滤命中 5；`subject=数学` 过滤命中 5；非法 `state`/`subject` → 400；缺 `student_id`、`student_id=0` → 422；未知 `student_id` → 200 空结构；`limit=0` → items 空但 stats 仍统计全部 |
| `state_case` | 19 | q1 全生命周期：`NEW` → `start` → `LEARNING`；教学态答对 → `PRACTICING`（落库 `cc=1`，见 §4.1）；`PRACTICING` 出变式题（`source` 合法、非原题）；变式答错 → `cc=0`、`fail_count=2`（偶数）→ `NEW`；答对原题 → 再进 `PRACTICING`（`fail_count` 不变）；变式再答错 → `fail_count=3`（奇数）→ 留 `PRACTICING`；变式答对 → `cc=1` 仍 `PRACTICING`；连对 2 次 → `VERIFYING` 且 `next_verify_time` 在 23h~25h（≈1 天后）；`verify` 答错 → 回 `PRACTICING`（`cc=0`、`mastered=false`、`next_verify_time` 清空）；再连对 2 次回 `VERIFYING`；`verify` 答对 → `MASTERED` + `mastered_time` 已写；`list?state=MASTERED` 命中且 `mastered_rate>0` |
| `parity_case` | 7 | q2：教学态答对 → `PRACTICING` 且 `fail_count=1`（奇数）；变式答错 → `fail_count` 递增 1→2、`cc=0`；`fail_count%2==0` → 回 `NEW` 且 `state_before=PRACTICING`；`NEW` 再答对 → `PRACTICING`（`fail_count` 保持 2）；再错一次 → `fail_count=3`（奇数）留 `PRACTICING` |
| `relearn_case` | 4 | q3：教学态答对 → `PRACTICING`；**任意状态答错原题** → `NEW` 且 `state_before=PRACTICING`、`fail_count` 递增；教学态（`NEW`）答错原题 → 仍 `NEW` 且 `fail_count` 继续递增 |
| `hint_case` | 13 | `POST /api/recovery/hint` L1~L4：每级 200 且 `level/level_text/hint` 非空（4 项）；L1、L3 **不含正确答案**；L4 完整讲解含「正确答案」与答案文本；四级文案互不相同（逐级给信息）；L3 有分步骤 `steps`；`source` 合法（`fallback_offline` / `fallback` / `ai`）；`max_level_used` 落库为 4；取提示不推进状态；未知 `recovery_id` → 空提示而非报错 |
| `analyzing_case` | 6 | `ANALYZING` 纯状态机可达（`NEW --analyze--> ANALYZING`）；中文文案与下一步动作齐全；`list?state=ANALYZING` 能读到（接口层可达）；`state_text` 中文正确；`start` 从 `ANALYZING` 推进 → `LEARNING`；`LEARNING` 答错原题 → `NEW`（`state_before=LEARNING`） |
| `start_by_question_case` | 4 | q6 尚未入队（`recovery_id=0` 前置条件）；只给 `question_id` 时 `start` 自动入队并开始教学；入队后 `list` 能查到；非法 `recovery_id` → 空结构（不 404/500） |
| `isolation_case` | 8 | A=1 / B=2 隔离，见 §3.1 |
| `offline_case` | 4 | `PHOEBE_AI_OFFLINE=1` 时 `ai_enabled()` 为假；`teach` / `generate_variants` 不抛异常；`teach` 降级返回规则提示；变式题降级为规则题（`source=rule`）；接口层全流程（start/出题/判分）可用 |
| `variant_case` | 5 | 变式题 ≥1 道；`source` 合法（`rule`/`ai`）；**每题 `validation.passed` 为真**（`QuestionValidator.validate` 为唯一真相）；题干/答案/选项齐全且答案在选项内；二次独立校验仍通过 |
| `coverage_case` | 1 | 六态 `NEW/ANALYZING/LEARNING/PRACTICING/VERIFYING/MASTERED` 全部被观察到（合计 94 项断言） |
| 后端启动 | 1 | 端口未占用则启动（被占用时故意失败，不换端口）；40s 未就绪 → FAIL |

### 2.2 `backend/verify_habit.py`（key `habit` · port 8911）

| 用例 | 断言 | 断言点与实测 |
|---|---|---|
| `compat_case` | 9 | V2.4 数据兼容（见 §3），含临时后端启动 1 项 |
| `mix_case` | 12 | `GET /api/tasks/today` 200 且首访即生成（`generated=true`）；任务字段齐全；三科 × 三段 = 9 条；`prompt` 优先级 1..9 不重复；标题为「学科 · 阶段文案」且 `knowledge` 非空；`summary.mix_tasks` 每段各 3；`summary.total=9` 且 `mix` 合计 = 各 task `target_count` 之和；三科逐一验证 **50/30/20** 配比算术：合计 = total 且每类 ≥1（实测 数学/语文 5/3/2、英语 10/6/4）；`knowledge`：`new_learning`(数学) 取当天 `learning_plan` 的知识点与理由；`weakness` 取掌握度最低、`review` 取掌握度最高（40 / 80） |
| `split_case` | 4 | `split_by_mix(10)=5/3/2`；`split_by_mix(3)` 每类 ≥1 且合计 3；`total 1..60` 合计恒等于 `max(3,total)` 且每类 ≥1（0 例外）；`new_learning` 恒为最大类 |
| `idempotent_case` | 4 | 同一天重复访问幂等（`generated=false`、行数不变、`task_id` 不变）；直接调 `generate_daily_tasks` 两次返回同一批行；换日期生成该日期自己的任务；同一学生不同日期互不覆盖（9 + 9 = 18 行） |
| `complete_case` | 8 | `POST /api/tasks/complete`：置 `done` 且 `complete_count` 补满 `target_count`；返回当日汇总（done=1、minutes=12、完成率 1/9=0.1111）；返回习惯画像（streak=1、today_minutes=12、首日徽章）；存在 `target_count>1` 的任务可部分完成；部分完成 → `status=doing`、`complete_count=1`；再报完成 → `done` 且 `complete_count=target_count`；重复上报同一任务不改变汇总（done 仍 2、完成率 2/9=0.2222）；落库状态与接口一致（2 条 `done`） |
| `streak_case` | 5 | 昨天活跃 + 今天活跃 → 昨天 +1（4→5）；今天重复刷新不再 +1；最后活跃早于昨天且今天无活动 → 重置为 0；`refresh` 已把归零结果落库；`longest_streak` 只增不减（保留历史最长 5） |
| `badge_case` | 5 | 连续 30 天后**六个徽章**全部触发（`first_day/streak_3/streak_7/streak_30/rate_80/minutes_100`）；累计天数 30 / 最长连续 30 / 完成率 1.0；总时长 150 分钟触发 `minutes_100`；等级 = 1 + min(6, 30//3) + 1 = 8；接口返回 6 个徽章且 `got` 全为真 |
| `isolation_case` | 8 | A=1 / B=2 隔离，见 §3.1 |
| `degraded_case` | 4 | 无 `learning_plan` / 无掌握度画像时仍生成 9 条；三科都能出题（各 3 条）；三段配比仍满足合计 = total 且每类 ≥1；知识点回退到知识点体系（非空、不报错） |
| `failure_case` | 10 | `/api/tasks/today` 缺 `student_id` → 422、`student_id=0` → 422、`date=13/01/2025` → 400、`date=2025-13-01` → 400；`/api/tasks/complete` `task_id=0` → 200 空结构、不存在/不属于自己的 `task_id` → 200 空结构（不是 404/500）；`/api/habit/profile` 缺 `student_id` → 422、非法 `date` → 400；`/api/habit/stats` `days=0` → 422、`days=91` → 422（边界） |
| `stats_case` | 10 | `GET /api/habit/stats` 200 且 7 天序列含今天；序列字段齐全且 `total_minutes` = 各天之和；`avg_rate` = 7 天完成率均值（4 位小数）；今天 done/rate 与 `/api/tasks/today` 汇总一致；`days=3` → 只返回 3 天；`GET /api/habit/profile` 画像 14 项齐全；完成 2/9 时 `completion_rate=0.2222`、`completed_tasks=2`；今日时长 12 / 累计时长 12（B 的 30 分钟未串入）；`recent` 为近 7 天曲线且末位是今天；6 个徽章 + `first_day` 已获得 |
| 后端启动 | 1 | 端口未占用则启动（被占用时故意失败）；40s 未就绪 → FAIL |

## 3. 实测证据

### 3.1 学生 A/B 隔离

- recovery（A=1 / B=2，共 8 项）：B 用 A 的 `recovery_id` 调 `start` → 空结构；B 取不到 A 的题目；B 提交 A 的正确答案仍判否，且响应体不泄露答案/解析；B `verify` A 的项 → `mastered=false` 空结构；B 取不到 A 的提示（`hint=""`）；B 的列表只有自己 1 道题（q7）；B 的列表响应体不出现 A 的题干/答案；B 的 `stats` 不含 A 的量。
- habit（A=1 / B=2，共 8 项）：B 的今日任务与 A `task_id` 交集为空；B 的 `summary/profile` 只统计自己；B 响应体不出现 A 的计划/知识点；B 完成 A 的任务 → 空结构（`status` 空、`count=0`、不泄露）；A 的任务未被 B 改动（`complete_count` / `minutes` 不变）；B 未因此新增任务行或时长；未知 `student_id` 画像 → 200 全 0 且 6 个徽章均未获得、`recent` 为 7 个零项（不是 404/500）；未知 `student_id` 的 `stats` → 200 全 0 序列。

### 3.2 V2.4 数据兼容（两套件各 8 项，共 16 项）

临时库中先按 `.v25_schema_baseline.json` 重建 **19 张 V2.4 表**并塞入样例数据（`id` 列按 V2.4 真实结构建为 `INTEGER PRIMARY KEY AUTOINCREMENT`），随后执行 `create_all` + `ensure_schema` + `migrate_data`：

- 19 张旧表行数全部不变；
- 旧表列结构不变（无删除/改名/改类型，只允许新增列）；
- V2.5 新表由 `create_all` 建出；
- `migrate_data` 把 `questions.correct` 回填为 `total/correct/wrong`（实测 `(10, 6, 4, 0.57, 1)`）；
- 首次迁移确有改动（非空跑，统计和 > 0）；
- **再跑一次迁移幂等**：0 行被改动，行数 / 列结构仍不变；
- 二次迁移后所有断言仍通过。

### 3.3 失败路径

- 参数校验：缺参 / `student_id=0` / `days=0` / `days=91` → 422；非法 `date`（格式错与日历错两种）→ 400；非法 `state` / `subject` → 400。
- 资源不存在或不归属：未知 `recovery_id` / `student_id`、`task_id=0`、非本人 `task_id` → 一律 200 空结构或全 0 结构，**不出现 404/500**；且不泄露他人数据。
- 降级路径：`PHOEBE_AI_OFFLINE=1`（且 `DEEPSEEK_API_KEY` 置空）时提示与变式题走本地规则，全流程可用、不抛异常；无 `learning_plan` / 无掌握度画像时习惯任务仍三科出题。
- 端口被占用：套件刻意失败（校验逻辑为「端口未占用」断言），不自动换端口。

## 4. 口径观察与缺陷记录（本任务不修改他人文件，仅报告）

1. **（medium · SPEC 口径偏差）教学态晋级把 `consecutive_correct` 预置为 1。** `backend/recovery/state.py:147` 中教学阶段答对的分支返回 `min(cc + 1, VERIFY_STREAK - 1)`，`VERIFY_STREAK = 2`（`backend/recovery/state.py:50`），因此康复项带着 `cc=1` 进入 `PRACTICING`；此后 `PRACTICING` 第 **1** 次变式答对即 `cc=2` → `VERIFYING`（`backend/recovery/state.py:137-138`）。SPEC.md:174 要求「`PRACTICING` 阶段每答对 1 次 `consecutive_correct += 1`；`consecutive_correct >= 2` → `VERIFYING`」，按字面应从 `PRACTICING` 起算 2 次答对。用户可见影响：从教学态进入练习后，只需 1 道变式题答对就能进验证阶段。**本套件按实现口径断言并显式标注**（`state_case` 中「教学态答对按 VERIFY_STREAK-1 记一次连对」），是否按 SPEC 收紧由 Lead 决定。
2. **（low · 可观测性）`_safe` 兜底掩盖内部异常。** `backend/recovery_routes.py` 的 `_safe(db, call, fallback)` 把任何内部异常转换为 200 空结构，异常排查时看不到堆栈；出现「意外的空响应」通常意味着下游引擎抛异常（本次调试中已遇到一次：变式题主键为 NULL 时静默降级为空题）。建议保留但加日志。
3. **（nit）同一语义的降级来源字符串不一致。** 离线提示在 `ai_recovery.teach` 中为 `source="fallback_offline"`，而引擎 `_teach` 的兜底为 `"fallback"`、答案泄露拦截为 `"fallback_answer_leak"`；三者在测试中均按合法值接受，但建议统一。
4. **（nit）`habit_routes` 的 `_empty_profile` / `_empty_stats` 在正常路径不可达**：未知 `student_id` 走引擎正常路径返回全 0 结构，仅内部异常时才用空结构，属防御性死代码。
5. 未发现阻断级（critical/high）缺陷；判分与题目质量分别由 `backend/grading.py is_correct`、`backend/validator.py QuestionValidator.validate` 作为唯一真相被间接验证（变式题 5 项断言 + 二次独立校验）。

## 5. 已知未覆盖项

1. **前端 `frontend/verify_*.js` 未运行**（不属于本任务写入范围，前端验证由对应 Agent / Lead 执行）。
2. **`backend/verify_all.py` 未运行**（按纪律由 Lead 在集成阶段统一跑，它会占用全部套件端口）。
3. **`ANALYZING` 无 HTTP 入口**：接口层只能读到 `ANALYZING` 状态的项并推进，无法经 HTTP 进入该状态；套件用纯状态机 `transition` 直接验证其可达性。
4. **真实 DeepSeek 联网路径未覆盖**（`source="ai"`）：套件强制离线；在线路径需要 `DEEPSEEK_API_KEY`，会产生外部依赖与非确定性。
5. **`VERIFYING` 到期回落（超时）未做真实等待验证**：只断言 `next_verify_time ≈ 24h` 与在期验证行为；`scheduler.apply_overdue` / `EVENT_VERIFY_TIMEOUT` 的真实到期回落需要操纵系统时间或直接以 `now` 参数调引擎，本套件未覆盖。
6. **并发 / 多进程同时写同一康复项或同一份习惯任务**未覆盖（套件为单进程串行）。
7. **非 SQLite 数据库后端**的迁移兼容未覆盖（临时库均为 SQLite）。
8. `POST /api/tasks/complete` 的 `minutes` 上限（1440）边界与 `count` 上限未做 422 断言（其余参数边界已覆盖）。

## 6. 与 SPEC 的偏差

- 套件名/端口/覆盖项与文件所有权均按 SPEC.md §9（第 326-327 行）实现：`backend/verify_recovery.py`（key `recovery`，8910）、`backend/verify_habit.py`（key `habit`，8911）。
- SPEC §9 描述 V2.4 兼容用例为「17 张 V2.4 表」，实际基线（`.v25_schema_baseline.json`）为 **19 张表**；本套件按真实基线 19 张表验证，与任务书一致。
- 唯一功能口径偏差见 §4.1（已按实现口径断言并上报，未修改他人代码）。

---

## 7. V2.5 集成验证（Lead，集成后实测）

环境：`C:\Python313\python.exe`；所有套件串行、各自固定端口与临时库；`backend/learning.db` 未被写入。

### 7.1 全量套件（19 个）

```powershell
C:\Python313\python.exe backend\verify_all.py     # 日志：backend/_verify_all_v25_final.log
```

| 套件 | 结果 | 耗时 |
|---|---|---|
| 艾宾浩斯复习闭环 (review 8899) | ✅ | 14.3s |
| 学习闭环回归 (flow 8900) | ✅ | 13.6s |
| 前端语音 / 复习逻辑 (web) | ✅ | 0.1s |
| 能力诊断引擎 (diagnostic 8902) | ✅ | 16.7s |
| 前端诊断页面逻辑 (diagweb) | ✅ | 0.4s |
| 知识掌握与错因分析 (knowledge 8904) | ✅ | 44.1s |
| 前端知识地图 / 错题本逻辑 (knowweb) | ✅ | 0.3s |
| 自适应学习引擎 (adaptive 8905) | ✅ | 23.8s |
| 前端今日学习 / 反馈逻辑 (adaptweb) | ✅ | 0.3s |
| 间隔复习系统 (memory 8906) | ✅ | 10.7s |
| 前端知识浇水 / 记忆数据逻辑 (memweb) | ✅ | 0.3s |
| 前端菲比庆祝模块 (phoebeweb) | ✅ | 0.1s |
| 前端菲比三视图立牌 (phoebe3dweb) | ✅ | 0.3s |
| 训练数据自动能力诊断 (ability 8907) | ✅ | 13.2s |
| 前端能力水平页逻辑 (abilityweb) | ✅ | 0.2s |
| 菲比 AI 陪伴对话 (phoebeai 8908，强制离线) | ✅ | 7.3s |
| 错题康复系统 (recovery 8910) | ✅ | 7.6s |
| 每日学习习惯系统 (habit 8911) | ✅ | 7.2s |
| 主动回忆与每日总结 (recall 8912) | ✅ | 8.8s |

**`RESULT: ALL PASS（合计 169.3s）`，退出码 0。**

单套件断言数：`verify_recovery.py` 94 项、`verify_habit.py` 79 项、`verify_active_recall.py` 62 项（含前端三页静态检查），均 `PASS / FAIL 0`。

### 7.2 契约卡门禁

```powershell
C:\Python313\python.exe backend\check_cards.py
```

模块总数 **98**、缺卡片 **0**、失真（入口符号不存在）**0**、需人工确认 **9**（均为既有脚本类模块），退出码 0。

### 7.3 集成阶段发现并修复的两个回归

1. **`frontend/today.js` 语法错误（阻断前端套件）**：学习启动仪式插入代码时误删了 `loadStudents` 里 `.then(list => { ... })` 的收尾 `})`，导致 `node --check frontend\today.js` 报 `today.js:562 SyntaxError: Unexpected token '.'`，前端今日学习套件（adaptweb）因此失败。修复后 `node --check` 退出码 0，adaptweb `RESULT: ALL PASS`。
2. **`verify_habit.py` 两条日期断言与「未知学生不生成幽灵任务」契约冲突**：断言原以不存在的 `student_id = 9` 取任务（旧实现会为不存在的学生落 9 条任务行），而 V2.5 起 `habit.today()` 对不存在的学生返回空结构（与 `/api/habit/profile`、`/api/daily-summary` 一致，且不再污染任务表）。已将这两条断言改用真实 `STUDENT_B`，**保留「不同日期互不覆盖」的原始测试意图**，habit 套件仍为 79 项全绿。此行为变更记入 `CHANGELOG.md`（与「幽灵任务」修复同源）。

### 7.4 未在本轮覆盖（除既有 §5 之外）

- `frontend/verify_recovery_web.js` 仍未纳入 `verify_all.py`（需单独 `node` 运行）。
- 浏览器真实交互（点击「开始今天的学习」、拖拽菲比）仍靠静态断言 + 接口断言代理，未做端到端 UI 自动化。
