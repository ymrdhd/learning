# FRONTEND_CHANGE.md — V2.5 前端改动说明（错题康复页 + 今日任务区块）

> 任务：Agent 6 Frontend Engineer（swarm run《菲比同学》V2.5）
> 日期：2026-10-05 ｜ 工作目录：`C:\Users\1\Desktop\ai_learning_system`
> 规格来源：`SPEC.md` §7.1（错题康复）/ §7.2（每日任务）/ §8（前端硬要求）、`AI_RULES.md` §13.7（零构建前端）

## 1. 改动文件清单

| 文件 | 状态 | 行数 | 说明 |
| --- | --- | --- | --- |
| `frontend/recovery.html` | 新建 | 70 | 错题康复页骨架；脚本顺序 `phoebe.js → phoebe3d.js → recovery.js` |
| `frontend/recovery.js` | 新建 | 438 | 错题康复交互：队列 / 开始 / 出题 / 提示 / 判分 / 解析 / 完成 |
| `frontend/today.html` | 新增区块 | 80 | 顶部插入「今日任务」区块（`#task-block`），其余保持原样 |
| `frontend/today.js` | 新增区块 | 696 | 新增 `TASK_MIX_LABEL / taskMixText / taskSummaryText / taskDone / taskItemHtml / renderTaskBlock / loadTasks / completeTask`；原今日学习流程未改 |
| `frontend/style.css` | 只在末尾追加 | 1295–1625（+331 行） | 追加 `.btn / .recovery-* / .task-* / .habit-*` 样式块；**第 1–1294 行一个字符未动**（既有选择器零修改） |
| `frontend/verify_recovery_web.js` | 新建 | 540 | 新增前端回归脚本（node + DOM 打桩，77 条断言） |
| `FRONTEND_CHANGE.md` | 新建 | — | 本文件 |

未改动（严禁改动且已确认未动）：`backend/**`、`frontend/app.js`、`frontend/phoebe3d.js`、`frontend/phoebe.js`、`index.html`、`SPEC.md`、`AI_RULES.md`、`docs/**`。

## 2. 儿童友好设计要点（可被测试按代码断言）

### 2.1 主操作按钮尺寸 / 字号（`frontend/style.css` 追加块）

| 选择器 | min-height | font-size | 备注 |
| --- | --- | --- | --- |
| `.btn` | 56px | 18px | 全站大按钮基线，`border-radius:18px`、`padding:14px 22px` |
| `.btn-primary` | 56px | 18px | 主色 `#ff8fb8`，按下有 2px 位移反馈 |
| `.recovery-main-btn` / `.recovery-hint-btn` / `.recovery-explain-btn` | 56px | 18px | `width:100%`，拇指可及 |
| `.recovery-refresh-btn` | 56px | 18px | 刷新错题队列 |
| `.recovery-options .option` | 56px | 18px | 选择题每一个选项都是大按钮 |
| `.task-complete-btn` | 56px | 18px | 「✅ 完成这一项」打卡按钮，`width:100%` |

### 2.2 单屏可见文字块 ≤ 3

`recovery.js` 用 `visibleTextBlocks()` 把「当前真正看得见的文字块」定义为最多 5 个候选：
`recovery-pick`（当前状态一行）、`question`（题干）、`hint-box`（提示）、`result`（判分反馈）、`recovery-done`（康复完成层）。
规则：
- 隐藏的块不计（`classList.contains("hidden")` 判空）；
- 藏在 `<div id="recovery-work" class="hidden">` 里的子块在完成态整组不计（`WORK_CHILD_IDS`）。

各阶段实测：选中错题 1 块 → 出题+提示 3 块 → 判分后 3 块（答错/答对都会先收起提示，避免提示与反馈两块同时抢注意力）→ 全部康复 1 块。

### 2.3 提示逐级展开（最多 4 级）

- 每次只显示一级：`renderHint()` 整体重写 `#hint-box`，不追加、不堆叠；
- `nextHintLevel(level)`：`0→1`，其后 `+1`，上限 4；`showNextHint()` 在第 4 级直接给出「菲比已经讲完啦，试着做做看 💪」并停止请求；
- 按钮文案（`HINT_NEXT_TEXT`）：第 1 级「还是不会」→ 第 2 级「看看怎么做」→ 第 3 级「给我完整讲解」→ 第 4 级「知道了」；
- 提示取不到时不打断做题，只把 `#hint-box` 换成「提示暂时取不到，先自己试试吧～」。

### 2.4 答对 / 答错分支

| 分支 | 视觉 | 动作 |
| --- | --- | --- |
| 答对 | 绿色 ✅（`.recovery-feedback.ok`，背景 `#e5f7ec` / 字色 `#1f7a45`）+「✅ 答对啦！」 | 收起提示、`state === "MASTERED"` 时进入完成层，调用菲比开心 |
| 答错 | 橙色 ❌（`.recovery-feedback.bad`，背景 `#fff1e3` / 字色 `#b85c00`）+「❌ 再想想～」 | 显示「正确答案：13」+「看看解析」按钮；`showAnalysis()` 展开 `📖 错题解析` |

菲比联动统一走 `phoebeRecoveryFeedback(correct, word)`：

```js
if (typeof phoebe3dFeedback !== "function") return;   // 静默降级，模块没加载也不报错
try { phoebe3dFeedback(!!correct, { text: word }); } catch (err) { /* 动画/语音失败不影响做题 */ }
```

`recovery.js` 不重新引入 `phoebe3d.js`（由 `recovery.html` / `today.html` 各引入一次）。

## 3. 与后端的接口契约（前端实际发起的请求）

| 页面 | 方法 + 路径 | 请求体 / 参数 | 用到的响应字段 |
| --- | --- | --- | --- |
| recovery | `GET /api/recovery/list` | `?student_id=1` | `items[].{recovery_id,subject,knowledge,state,state_text,consecutive_correct}` |
| recovery | `POST /api/recovery/start` | `{student_id, recovery_id}` | `teaching.{level,level_text,hint}`、`item` |
| recovery | `POST /api/recovery/question` | `{student_id, recovery_id, hint_level?}` | `question.{question_id,question,qtype,options,knowledge}`、`teaching` |
| recovery | `POST /api/recovery/hint` | `{student_id, recovery_id, level}` | `{level, level_text, hint}` |
| recovery | `POST /api/recovery/answer` | `{student_id, recovery_id, question_id, answer, hint_level}` | `correct, correct_answer, analysis, state, state_text` |
| today | `GET /api/tasks/today` | `?student_id=1` | `tasks[].{task_id,task_type_text,title,subject,complete_count,target_count,duration_minutes,target_minutes,status,status_text}`、`summary.{total,done,completion_rate,minutes,mix{new_learning,weakness,review}}` |
| today | `POST /api/tasks/complete` | `{student_id, task_id, done:true}` | `summary`（用于立即刷新完成率/时长） |

`/api/recovery/verify`（定时验证）本期前端未接入口：康复完成由 `answer` 返回的 `state === "MASTERED"` 驱动，验证时机仍由后端 `next_verify_time` 决定，属后端调度，前端不重复触发。

降级行为：
- 任务接口失败 → `#task-mix` 显示「任务暂时排不出来，先照下面的计划练 ➡️」，**不影响**原有今日学习（不写 `#status`、不阻塞计划与做题）；
- 打卡失败 → `#task-mix` 显示「没记上，等一会儿再试一次～」，可再点一次；
- 康复接口失败 → `#status` / `#question` 给出中文错误提示，不抛异常。

## 4. 验证脚本与运行结果

新增 `frontend/verify_recovery_web.js`（仿 `verify_adaptive_web.js`：node + DOM 打桩 + fetch 打桩，无需浏览器、无需后端）。

```powershell
cd C:\Users\1\Desktop\ai_learning_system\frontend
& "C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" verify_recovery_web.js
& "C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" verify_adaptive_web.js
```

实测结果（2026-10-05）：

| 脚本 | 断言数 | 结果 | 退出码 |
| --- | --- | --- | --- |
| `verify_recovery_web.js` | 77 | `RESULT: ALL PASS` | 0 |
| `verify_adaptive_web.js` | 41 | `RESULT: ALL PASS` | 0 |
前端全套回归（`frontend/` 下 9 个 `verify_*.js` 全跑一遍）均为 `RESULT: ALL PASS` 且退出码 0：
`verify_web.js` / `verify_adaptive_web.js` / `verify_ability_web.js` / `verify_diagnostic_web.js` /
`verify_knowledge_web.js` / `verify_memory_web.js` / `verify_phoebe_web.js` / `verify_phoebe3d_web.js` / `verify_recovery_web.js`。

覆盖范围：
1. **结构 / 零构建**：脚本加载顺序 `phoebe.js → phoebe3d.js → 业务 js`、`phoebe3d.js` 只引入一次、无 CDN、无 `type="module"`、无 `import/export`；
2. **元素一致性**：`recovery.js` / `today.js` 里每个 `$("id")` 都能在对应页面找到（防手写 id 打错）；
3. **CSS 断言**：8 个按钮选择器 `min-height ≥ 56px` 且 `font-size ≥ 18px`；答对反馈色为绿、答错反馈色为橙；`.recovery-* / .task-* / .habit-*` 样式块存在；
4. **康复流程**：队列 → 选中 → 开始（带 `recovery_id`）→ 出题（带 `student_id`）→ 提示 1→2→3→4 级封顶 → 答错（❌ + 正确答案 + 看看解析 + 菲比 `false`）→ 答对（✅ + 收起提示 + 菲比 `true`）→ 完成层（康复进度 + 菲比庆祝）；每一步都断言**单屏可见文字块 ≤3**；
5. **静默降级**：在没有 `phoebe3dFeedback` 的环境里跑完整流程不报错；
6. **今日任务**：`GET /api/tasks/today`（带 `student_id`）→ 完成率/时长/50-30-20 配比/任务卡片 → `POST /api/tasks/complete`（带 `student_id`/`task_id`/`done`）→ 完成率与时长刷新；接口 404 时降级文案出现且原有流程不中断。

## 5. 与 SPEC 的偏差 / 遗留问题（需 Lead 决策）

1. **首页入口未加**：`SPEC.md` §8/§11 要求首页（`index.html`）与今日学习页都加「错题康复」入口，本任务写入范围**不含 `index.html`**，故只做了 `recovery.html` 底部导航 + `today.html` / `recovery.html` 的 `link-row` 互链。`index.html` 的导航补一行 `<a href="recovery.html">🩺 错题康复</a>` 即可，需由拥有该文件写权限的 Agent 或 Lead 落地。
2. **未做真机联调**：本脚本用 DOM 打桩验证前端逻辑与契约字段，未启动后端；端到端由 Lead 的 `backend/verify_all.py` 与浏览器实测覆盖。
3. **`hintMoreText` 文案口径**：按 SPEC §8「点『还是不会』再给下一级」，按钮文案按**当前层级**取名（1 级显示「还是不会」），而非下一级名称；如需改为「按钮写下一级动作」，只需改 `HINT_NEXT_TEXT` 索引。
