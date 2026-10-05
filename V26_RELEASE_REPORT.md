# V2.6 开发报告 — 儿童体验重构 + 健康学习习惯 + 知识地图 + 成长中心 + 分龄 UI

- 产品：**菲比同学**（AI 小学学习系统，本地单机，两个小朋友独立数据）
- 版本：**V2.6**（兼容 V2.0 ~ V2.5 全部功能）
- 技术栈：Python + FastAPI、原生 HTML/CSS/JS、SQLite（SQLAlchemy）、DeepSeek API（可选，未配置即降级）
- 本版定位：**不新增学习算法**，只做产品整合、UI/UX、流程、展示层与必要的聚合 API
- 验证环境：`C:\Python313\python.exe`（Python 3.13）、DSH 自带 Node（`frontend/verify_*.js`）

---

## 1. 本版本实际完成功能

| 用户目标 | 完成情况 | 落地位置 |
|---|---|---|
| ① 孩子打开软件知道从哪里开始 | ✅ | `frontend/today.html`+`today.js` 改为儿童首页「今天」；`start.bat` 默认打开 `/app/today.html`；`GET /api/home/{student_id}` 一次给齐 |
| ② 入口复杂、认知负担高 | ✅ | 一级导航收敛为 4 项（🏠 今天 / 🗺 成长 / ⚔️ 挑战 / 👤 我的），`frontend/ui-shell.js` 的 `NAV_TABS` 统一挂载 |
| ③ 学习过程与成长反馈儿童化 | ✅ | `backend/kid_status.py` + `frontend/kid-lang.js` 唯一口径：🌱 刚开始 / 🌿 正在学习 / 🍀 基本会了 / 🌳 已经掌握 / ⭐ 记得很牢 |
| ④ 看见长期成长而非只看正确率 | ✅ | 成长中心（`GET /api/growth/{student_id}`、`frontend/growth.html`）+ 知识地图（`GET /api/knowledge-map/{student_id}`） |
| ⑤ 「每天愿意回来，完成后能自然离开」 | ✅ | 统一 `LearningSession` + 明确结束点（`mayContinue()` 在任务做完后返回 `false`）+ 今日完成页（无加练入口） |
| ⑥ 把 V2.0-V2.5 算法包装成统一简单体验 | ✅ | 首页聚合接口 + 学习会话编排 + 挑战中心复用 V2.5 `WrongQuestionRecoveryEngine`，**未写第二套算法** |

三条硬约束由测试锁死：**每天必须有固定边界**（`v26` 套件断言完成后任务数不再增长）、**完成任务后不能无限继续**（`v26web` 断言 `setTasks([{status:"done"}])` 后 `mayContinue() === false`）、**没有沉迷机制**（前端套件黑名单扫描 Loot Box / 抽卡 / 再加练 / 断签清零等文案）。

---

## 2. UI/UX 变化

- 首页从「功能入口集合」变成只回答一个问题：「我今天要做什么」。顶部是学生头像 + 昵称 + 年级 + 切换学生，中间是菲比问候「今天我们用 N 分钟完成 M 个小任务。」与今日任务清单，主按钮「开始今天的学习」是全页最显眼元素。
- 首页**不显示**能力百分比、遗忘概率、复杂图表、长期数据列表与大量统计数字；只保留今日计划、今日进度、需要照顾的知识、一个成长亮点（来自真实数据的 `growth_highlight`）。
- 做题页成为全系统最安静的页面：顶部科目·知识点 + 进度，中间一屏一题，下面答题区，底部固定 🔊 读题 / 💡 提示，主按钮「我做好了」；金币、商城、排行榜、宠物升级、活动 Banner、复杂成长信息全部不出现。
- 正确反馈分级：普通答对只轻量「✓ 对啦」；只有真正成长事件（升档、长期复习成功、攻克错题）才用强化反馈。
- 答错反馈去掉红叉与处罚感，改为「🤔 这里再想一下」+「看看提示 / 我再试试」，多级提示继续走 V2.5 的 `hint_level`。
- 结束页「🎉 今天完成啦！」集中给成长反馈：学会 / 巩固 / 攻克 / 主动回忆 / 学习分钟数，主按钮「完成」，次按钮「看看我的成长」。
- Loading 用「菲比正在准备一道适合你的题……」，Error 不出现 HTTP 码 / Traceback，Empty 用「🎉 暂时没有需要攻克的挑战！」「🌳 今天没有知识需要复习。」。

---

## 3. 新增页面

| 页面 | 说明 |
|---|---|
| `frontend/challenge.html` | ⚔️ 我的挑战：错题中心的儿童化包装，按 🔴 等我攻克 / 🟡 正在训练 / 🟢 已经攻克 分组 |
| `frontend/growth.html` | 🗺 成长中心：本周学会什么、记住什么、攻克什么 + 成长时间线（V2.6 前已建壳，本版接入导航与真实数据） |
| `frontend/today.html`（改造） | 由 V2.5「今日学习」升级为儿童首页「今天」，新增 `#session-bar`、`#completion`、`#read-btn`、`#hint-box` |
| `frontend/knowledge_map.html`（扩展） | 保留 V2.5 领域星级明细，新增「🗺 探索进度」区域地图 `#map-regions` |

---

## 4. 新增组件

| 组件 | 位置 | 职责 |
|---|---|---|
| Design Tokens | `frontend/style.css` 顶部 `:root` | 颜色 / 字体 / 字号 / Spacing / Radius / Shadow / Motion / Breakpoints，全站唯一来源 |
| 公共样式族 | `frontend/style.css` | `.ph-btn`(+`--primary`/`--secondary`/`--ghost`/`--speak`)、`.ph-card`(+`--task`/`--region`)、`.ph-status`(+四档)、`.ph-progress`、`.ph-confirm`（Modal）、`.ph-state`（Loading/Empty/Error）、`.ph-nav--bottom`/`.ph-nav--side`、`.ph-hint`、`.ph-complete`、`.ph-option`（整块可点）、`.ph-chip`、`.ph-map`/`.ph-tile`、`.ph-quiet-tools` |
| `LearningSession` | `frontend/learning-session.js` | currentStudent / dailyPlan / currentTask / currentQuestion / taskProgress / sessionProgress / completedTasks |
| 儿童语言层 | `frontend/kid-lang.js`、`backend/kid_status.py` | 数值 → 儿童语言（前后端同阈值 90/75/55/30） |
| 语音读题 | `frontend/today.js` 的 `readQuestion` / `stopReading` / `speechUsable` | 浏览器原生 `SpeechSynthesis`，播放 / 停止 / 重复，失败不影响答题 |
| 菲比角色 | `frontend/phoebe.js`、`phoebe3d.js` + `.ph-avatar` | 只出现在每日开始 / 卡住时 / 重要成长时 / 今日结束，状态 normal / thinking / encourage / happy |

---

## 5. 新增 / 修改 API

**新增（全部为只读聚合，不重复实现已有算法）**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/home/{student_id}` | student / daily_plan / daily_progress / review_due_count / recovery_count / growth_highlight / phoebe_message + 主按钮文案；已开跑则报真实落库任务 |
| GET | `/api/knowledge-map/{student_id}?subject=` | regions / knowledge_nodes（ui_status / children / is_unlocked / recommended）+ totals |
| GET | `/api/growth/{student_id}?days=&date=` | week{} / highlights / ability / timeline / streak / message |
| GET | `/api/challenge/{student_id}?subject=&limit=` | counts{red,yellow,green} / groups / items（**剔除答案与解析**）/ tones / next |

**修改**

| 位置 | 变化 |
|---|---|
| `backend/main.py` | `FastAPI(title="菲比同学 V2.6")`；注册 4 个新 router；`GET /` 返回 `version="2.6"` 并追加 9 条特性 |
| `backend/verify_all.py` | `SUITES` 增加 `v26`（端口 8913）与 `v26web`（无端口），共 **23 个套件** |
| `backend/verify_knowledge.py` / `verify_adaptive.py` / `verify_memory.py` | 版本断言由 2.5 升到 2.6（断言意图不变） |
| `frontend/ui-shell.js` | 导航第三项由「错题 → wrong_book.html」改为「挑战 → challenge.html」 |
| `frontend/style.css` | 追加 V2.6 组件样式与响应式断点 |
| `start.bat` | 默认落地页由 `/app/` 改为 `/app/today.html` |

---

## 6. Design System 变化

本版把散落的样式收敛成一套令牌 + 公共组件：

- 颜色：主品牌色 `--color-primary:#5B6EF5` + `--color-accent` + Success / Warning / Attention / Soft Error / Neutral 与对应 `-soft` 变体；不使用满屏高饱和色。
- 字号：`--text-body:17px` / `--text-label:15px` / `--text-question:22px` / `--text-title:28px`；JUNIOR 档正文 ≥18px、题目 24-28px。
- 尺寸：`--tap-min:44px`、`--tap-junior:56px`，Primary Button 56px 高；选择题整张卡片可点，不需要精确点小圆点。
- 动效：`--motion-fast:200ms` / `--motion-base:300ms` / `--motion-slow:600ms` / `--motion-celebrate:1200ms` + `--ease-out`；`@media (prefers-reduced-motion: reduce)` 生效，动画不阻塞答题。
- 断点：手机 / 平板竖屏 / 平板横屏 / 桌面（`1024px`、`1281px` 两处媒体查询 + 底部导航与侧边导航切换）。

---

## 7. AgeMode 实现

`frontend/ui-shell.js` 的 `ageModeOf(grade)`：1-2 年级 `junior`、3-4 年级 `middle`、5-6 年级 `senior`（年级未知按 `junior` 保守处理），结果写到 `documentElement` 的 `data-age-mode`，样式由 CSS 按属性选择器分支：

- **JUNIOR**：大按钮、大字号、少文字、多图标、明显读题入口、一屏一题；不用折线图与复杂统计。
- **MIDDLE**：可显示知识地图、成长数量、今日计划、知识状态、挑战状态，保持低信息密度。
- **SENIOR**：减少幼儿化元素，允许学习计划、简单趋势、阶段目标与成长统计，仍不做成人办公 Dashboard。

---

## 8. Knowledge Map 实现

- 数据来源：`knowledge_tree.domains_for/subpoints_of`（真实知识点树）+ `StudentKnowledgeMastery`（掌握度）+ `review.engine.states_of` / `review.memory.state_summary`（记忆成熟度）。**前端不写死任何状态**。
- 每个节点的 `ui_status` 由 `backend/kid_status.py` 计算（掌握度主档 90/75/55/30，记忆成熟度只做下限抬档，例如 `LONG_TERM → ⭐`）。
- 区域聚合：`{icon} {domain}` 标题、`grown / total 知识已成长`（`GROWN_RANK = 2`，即 🌿 及以上算长大）、`percent`。
- 解锁：区域内第一个节点恒为 `true`，其余要求前一节点已长大或掌握度 ≥ 30（`UNLOCK_LINE`）——**只能由真实学习数据解锁**，在线时长 / 金币 / 签到无法解锁。
- 推荐：`recommended` 取已解锁、尚未掌握（rank < 3）的节点，按 `(rank, grade, difficulty)` 排序取前 3。
- 接口原始字段（`mastery_score` / `maturity_level` / `difficulty` / `grade`）保留在响应里，儿童 UI 默认不展示。
- 实现文件：`backend/knowledge_map_routes.py`；前端 `frontend/knowledge_map.js` 的 `renderKnowledgeMap` / `renderRegion` / `statusChip`。

---

## 9. Growth Center 实现

- 接口 `GET /api/growth/{student_id}?days=7&date=`，返回 `week{study_days,new_mastered,long_term,challenges,review_success,recall_success,minutes}`、`highlights`、`ability`（三科能力阶段变化，如 `3.2 → 3.3`）、`timeline`、`streak{current,longest,month_days,rest_left,text}`、`message`。
- 反馈优先级：学会什么 / 记住什么 / 攻克什么 / 进步在哪里；**不使用累计做题数、在线时长作为主指标**。
- Growth Timeline：取掌握、长期记忆、错题攻克、复习成功等真实事件，按时间倒序给「今天 / 昨天 / 周几 + 图标 + 一句话」，不做社交 Feed。
- 连续学习：显示本月学习天数 / 当前连续 / 最长连续；休息一天不清空历史（V2.5 的休息保护 `REST_PROTECTION_LIMIT = 2` 在 UI 中以「还可以休息 N 天」体现），不做断签焦虑。
- 前端 `frontend/growth.js` 的四项周数字继续复用 V2.5 既有接口（`/api/habit/stats`、`/api/mastery/`、`/api/recovery/list/`），`/api/growth` 作为增强数据源（失败不影响页面）。

---

## 10. Healthy Engagement 实现

以产品原则形式固化，并在代码与数据里留出可统计的钩子：

- 原则原文已写入 `ARCHITECTURE.md`：**「菲比同学儿童端优先帮助儿童完成学习，而不是最大化使用时长。」「孩子应该期待明天再来，而不是今天停不下来。」「奖励真正学习，不奖励单纯在线。」「学习过程中减少干扰，完成后集中提供成长反馈。」「每日学习必须存在明确结束点。」**
- 奖励只给学习成果：第一次真正掌握知识、长期复习成功、错题康复 → 高价值成长反馈（升档卡 / 星标 / 攻克）；重复刷已经完全掌握的简单题不给额外反馈（成长亮点只取真实事件，没有事件时显示「今天完成第一个小任务，就会看到成长啦！」）。
- 明确结束点：`LearningSession.mayContinue()` 在 `finished` 或 `remaining == 0` 时返回 `false`，自动跳题定时器与 `nextQuestion()` 同时停下；完成页主按钮是「完成」，没有任何「再学 5 分钟」入口。
- 无沉迷机制：不做 Loot Box、抽卡、随机高价值奖励、断签清零、宠物死亡退化、限时 FOMO、强制倒计时、无限滚动学习流、在线时长奖励、公开排行榜。
- 可统计基础：每日任务表（`daily_learning_tasks`）保留 `target_count` / `complete_count` / `duration_minutes` / `status` / 来源，复习记录保留 `response_time` / `review_quality`，康复表保留 `attempts` / `fail_count` / `mastered_time`，成长接口按日期窗口聚合——**未来的 Daily Plan 完成率、7/30 日规律学习率、超长 Session 比例、简单题重复刷取比例等指标都可由现有数据算出，本版未新建分析平台**。

---

## 11. 自动化测试结果

| 套件 | 端口 | 断言数 | 结果 |
|---|---|---|---|
| `backend/verify_v26.py` | 8913 | 63 | ✅ RESULT: ALL PASS |
| `frontend/verify_v26_web.js` | 无 | 65 | ✅ RESULT: ALL PASS |

`backend/verify_v26.py` 覆盖：首页聚合字段与口径、完成态不再增加任务数、知识地图真实数据与解锁规则、两学生状态差异、成长中心周数据与时间线、挑战中心三色分组与「不泄露答案」、学习会话与今日完成、V2.0~V2.5 接口回归。它通过 `import main; uvicorn.run(main.app, …)` 起**真实应用**，因此同时验证了 router 注册与启动期副作用。

`frontend/verify_v26_web.js` 覆盖：三页 HTML/JS 引用与 id 交叉检查、儿童四档状态文案、答错反馈文案、`LearningSession` 完整 API 与「做完就停」、完成页文案与无加练入口、挑战中心分组渲染、知识地图渲染、分龄切换、导航四个 href 真实存在、双学生订阅、沉迷机制黑名单。

`python backend/check_cards.py` → 退出码 0（114 个模块 / 无卡片 0 / 失实符号 0）。

---

## 12. 回归测试结果

`python backend\verify_all.py`（**23 个套件串行**，各自独立端口与临时库）：

- 全部 23 个套件 `RESULT: ALL PASS`（**合计 182.1s**），总退出码 0；其中本版新增的 `v26` 8.2s、`v26web` 0.2s、`phoebe3dweb` 0.3s。
- 上线后试用反馈三修（`start.bat` 旧版本探测 / 语音读题强制朗读 / 菲比收藏）额外跑了一次全量：同一条命令仍为 **23 个套件 `RESULT: ALL PASS`（合计 182.1s）**、退出码 0；`frontend/verify_phoebe3d_web.js` 新增 11 项收藏断言（初始为空 / 每次 +1 / 只用 like·cheer·cute·encourage / 不等于立牌当前表情 / 不重复 / 换学生隔离 / 上限 12 / 单容器 / 正面素材 / 不挡点击 / 窄屏隐藏）。
- 本版新增的 `v26` 与 `v26web` 已编入套件表，与 `v26` 同名端口 8913 不冲突。
- V2.3 / V2.4 时代的三个套件（`knowledge` / `adaptive` / `memory`）里有硬编码版本断言，随 `GET /` 升到 `2.6` 同步更新为 `"2.6"`（断言意图「版本已升级、旧能力保留」不变）；这是每次版本号提升时的既定做法（`backup/snapshots/` 里可见 V2.5 当时同样把 2.4 改成了 2.5）。
- 前端既有套件（web / diagweb / knowweb / adaptweb / memweb / phoebeweb / phoebe3dweb / uishell / growthweb / abilityweb）全部通过，说明 `today.html`、`ui-shell.js`、`style.css`、`knowledge_map.*` 的改动没有破坏既有断言。

---

## 13. 数据隔离测试结果

- `verify_v26.py` 的 `seed_case` 只给小朋友 A（`student_id=1`）写入掌握度 / 每日任务 / 已攻克错题，随后断言：同一个知识点「表内乘法」在 A 侧是 `{key: solid, label: 记得很牢, rank: 4}`，在 B 侧（`student_id=2`）是 `{key: sprout, label: 还没开始学, rank: 0}`；A 的本周成长非 0 而 B 全 0；A 的挑战 `green=1` 而 B 为空；`student_id=999` 不存在时四个接口都返回空结构（200，而非 404）。
- 前端：`frontend/ui-shell.js` 的 `createStudentSwitcher` / `confirmSwitch` 先弹「确定切换到 X 吗？」，确认后才广播；`today.js`、`challenge.js` 都订阅 `UIShell.onStudentChange`，回调里**先清空会话、进度条、完成卡与列表，再按新 `student_id` 重新拉取**，因此不会短暂显示上一个孩子的数据。
- 既有两学生隔离断言（知识报告 / 掌握度 / 复习队列 / 每日计划 / 策略日志 / 反馈）在 `knowledge`、`adaptive`、`memory` 套件中继续全部通过。

---

## 14. 已知问题

1. **前端无缓存版本串**：`frontend/` 静态资源没有 query 版本号，改完必须强制刷新（V2.5 起就存在，非本版引入）。
2. **语音读题依赖系统中文语音包**：`SpeechSynthesis` 在缺少中文语音的机器上会读不出声，此时按钮显示「🔊 读题（本机暂不支持）」，不影响答题。
3. **知识地图区域图标是展示层映射**：`REGION_ICON` 按领域名硬编码图标，未列出的领域回落 `📘`——新增领域需同步该映射（数据本身仍来自真实知识点树）。
4. **`index.html` 仍是自由练习页**：产品默认落地页改为 `today.html`（`start.bat`），`index.html` 保留为单题自由练习与 `autostart` 跳转目标。
5. **成长页数字来源双轨**：`growth.js` 的四项周数字走 V2.5 既有接口，`/api/growth` 提供更细的 highlights / timeline / ability；两者口径一致但字段不同，属有意的向后兼容。
6. **接口无鉴权、无账号**：与 V2.0~V2.5 一致，本地单机设定，非本版目标。

---

## 15. 未完成项目

- 本版**非目标**（明确不做）：复杂宠物养成、金币经济、商城、抽卡 / Loot Box、排行榜、公开社交、正式家长端、正式账号、云同步、复杂 AI 自由聊天、复杂 3D 世界、大型剧情系统。
- 沿用 V2.5 遗留：`backend/ai_recovery_routes.py` 未实现；`frontend/verify_recovery_web.js` 未编入 `verify_all.py` 的 `SUITES`；`PARENT`/`STUDENT` 学习目标仅有字段无入口；主动回忆仍是 24 张内置卡片、无 AI 扩题；变式题 AI 生成未全学科覆盖；历史临时文件（`backend/_probe*.db`、`learning.db.v15-backup`）未清理。
- 内部健康指标（7 日 / 30 日规律学习率、超长 Session 比例、简单题重复刷取比例等）本版只保证**数据可统计**，未建数据看板。

---

## 16. ARCHITECTURE.md 更新确认

已更新并通过阅读比对：

1. 文件头 `Current Product: 菲比同学` / `Current Version: V2.6` + 最近一次架构变化（**未新增表、未新增列、未改算法**）。
2. §1 系统定位重写：默认学生「朵朵」「童童」，`student_id` 1/2，儿童端目标，**五句健康使用原则原文**逐条记录。
3. §2.2 后端模块表：`main.py`（15 个 router、`GET /` 返回 `2.6`）、`models.py`（23 张表）、`local_users.py`（朵朵 / 童童）。
4. §2.3 `stages.py`：72 个能力阶段（1.1 ~ 6.12、0 ~ 71）、三科各 72 个知识点、`legacy_key` 兼容旧 24 阶段。
5. §2.12 前端页面表：`today.html`（含 `learning-session.js` 的脚本顺序）、`knowledge_map.html`，新增 `challenge.html` / `growth.html`。
6. **新增 §2.14 V2.6 儿童体验层**：6 个新文件的职责与入口、信息架构、统一学习流程、结束机制、儿童状态映射阈值、AgeMode、Design System、双学生隔离。
7. **新增 §4.11 V2.6 儿童体验接口**：4 个接口的参数、返回字段与约定。
8. §7 测试：端口列表加 8913，套件表加 `v26` / `v26web`（共 23 个）。
9. §5 数据表：沿用 23 张表，本次只更新运行时行为说明，无 schema 变更。
10. §8 TODO：V2.6 已完成项、V2.7 候选、仍留待办。

未记录任何真实 API Key；未复制大段源码；TODO 与已完成严格区分。

---

## 17. 下一阶段 TODO

1. 合并旧的错题入口：`wrong_book.html` 与新的 `challenge.html` 是否收敛为一个页面（当前挑战中心复用康复流程，错题本保留原始列表）。
2. AI 动态扩题：主动回忆题库与错题变式全学科覆盖。
3. `ai_recovery_routes.py` 补齐，把 `frontend/verify_recovery_web.js` 编入 `SUITES`。
4. 家长端（学习目标设置 + 报告导出），仍不做正式账号。
5. 健康指标看板：Daily Plan 完成率、7/30 日规律学习率、主动启动学习比例、每日完成后正常结束比例、超长 Session 比例、简单题重复刷取比例。
6. 静态资源加缓存版本串，避免每次改前端都要教孩子强制刷新。
