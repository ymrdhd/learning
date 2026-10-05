# TODO — 菲比同学

> 规则：**只有真正跑通并有测试证据的功能才打 `[x]`**；没做完的一律留在 `[ ]`，不允许把未完成写成已完成。
> V2.5 的开发报告见 [V25_RELEASE_REPORT.md](../V25_RELEASE_REPORT.md)，V2.6 的开发报告见 [V26_RELEASE_REPORT.md](../V26_RELEASE_REPORT.md)，架构说明见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

---

## V2.6 已完成（`[x]`，均有自动化测试证据）

### 模块 A｜儿童端信息架构与首页

- [x] 一级导航收敛为 4 项（🏠 今天 / 🗺 成长 / ⚔️ 挑战 / 👤 我的）；`start.bat` 默认打开 `/app/today.html`，`index.html` 保留为自由练习页。
- [x] 新增聚合接口 `GET /api/home/{student_id}`：student / daily_plan / daily_progress / review_due_count / recovery_count / growth_highlight / phoebe_message + 主按钮文案，**只聚合不重算算法**；已开跑就报真实落库任务。
- [x] `backend/kid_status.py` 儿童知识状态唯一适配器（90 / 75 / 55 / 30 → ⭐ / 🌳 / 🍀 / 🌿 / 🌱），前端 `frontend/kid-lang.js` 同口径。
- [x] 首页只显示今日计划 / 今日进度 / 需要照顾的知识 / 一个成长亮点，未变成 Dashboard。
- [x] 菲比问候「今天我们用 N 分钟完成 M 个小任务」+ 主按钮「开始今天的学习」为全页最明显按钮。

### 模块 B｜统一学习会话与结束机制

- [x] `frontend/learning-session.js`：`start` / `choose` / `tick` / `completeCurrent` / `mayContinue` / `progress` / `finish` / `reset` / `studentChanged`。
- [x] 微任务连续学习：完成一个任务自动切下一个，不需要回首页重选；孩子可用 `choose(taskId)` 决定**先做哪个任务**（知识点 / 题目 / 难度仍由系统决定）。
- [x] 结束机制：`mayContinue()` 在 `finished` 或 `remaining == 0` 时返回 `false`，自动跳题与 `nextQuestion()` 停下；完成卡「🎉 今天完成啦！」+ 菲比「今天已经完成啦，可以去休息了！」+ 主按钮「完成」、次按钮「看看我的成长」。
- [x] 无 Loot Box / 抽卡 / 随机大奖 / 断签清零 / 在线时长奖励 / 排行榜 / 加练入口（前端套件黑名单断言）。

### 模块 C｜做题页与儿童化反馈

- [x] 做题页去干扰：科目·知识点 + 进度、题目、答题区、🔊 读题 / 💡 提示、「我做好了」。
- [x] 浏览器原生 `SpeechSynthesis` 读题（播放 / 停止 / 重复），失败不影响答题。
- [x] 答错「🤔 这里再想一下」+ 看看提示 / 我再试试（复用 V2.5 `hint_level`）；普通答对保持轻量「✓ 对啦」。

### 模块 D｜知识地图 / 成长中心 / 挑战中心

- [x] `GET /api/knowledge-map/{student_id}?subject=`：区域 + 节点（`ui_status` / `children` / `is_unlocked` / `recommended`），数据来自真实知识点树 + 掌握度 + 记忆状态；解锁条件 = 已练过（rank ≥ 1）或掌握度 ≥ 30。
- [x] `knowledge_map.html` / `knowledge_map.js` 增加探索进度区（保留 V2.5 的领域星级明细列表）。
- [x] `GET /api/growth/{student_id}?days=&date=`：本周学习天数 / 新掌握 / 记得更牢 / 攻克挑战 / 复习成功 / 主动回忆 / 学习分钟数 + 三科能力阶段变化 + 成长时间线。
- [x] `GET /api/challenge/{student_id}`：三色分组（🔴 等我攻克 / 🟡 正在训练 / 🟢 已经攻克），底层复用 V2.5 `WrongQuestionRecoveryEngine`，**不下发答案与解析**；`challenge.html` 点「去攻克」走既有康复流程。

### 模块 E｜分龄 UI / Design System / 双学生隔离

- [x] `frontend/ui-shell.js` 的 `ageModeOf(grade)`：1-2 `junior` / 3-4 `middle` / 5-6 `senior`，写 `documentElement` 的 `data-age-mode`。
- [x] `frontend/style.css` 顶部 `:root` 为唯一 Design Tokens 来源，公共组件覆盖 Button / Card / Status Badge / Progress / Modal / Toast / BottomNavigation / Loading / EmptyState / ErrorState。
- [x] 交互区 ≥ 44px（JUNIOR 56px）、整张答案卡片可点、`prefers-reduced-motion` 生效、手机 / 平板竖屏 / 平板横屏 / 桌面四档响应式。
- [x] 切换学生二次确认后先清空再重拉，home / 计划 / 成长 / 知识地图 / 挑战 / 习惯全部刷新，无跨学生残留。

### 测试与文档

- [x] `backend/verify_v26.py`（63 项断言，端口 8913）+ `frontend/verify_v26_web.js`（65 项断言），均编入 `verify_all.py`（**23 个套件**）。
- [x] `python backend/check_cards.py` 退出码 0（114 个模块 / 无卡片 0 / 失实符号 0）。
- [x] 数据库**无新表无新列**，V2.5 能力零破坏（`v26` 套件的回归用例断言 V2.0~V2.5 接口全部 200）。
- [x] 更新 `README.md` / `CHANGELOG.md` / `ARCHITECTURE.md`（V2.6，含 19 项架构条目与五句健康使用原则原文）。

---

## V2.5 已完成（`[x]`，均有自动化测试证据）

### 模块 A｜错题康复

- [x] `WrongQuestionRecoveryEngine`（`backend/recovery/engine.py`）门面：列表 / 详情 / 统计 / 开始 / 出题 / 作答 / 验证 / 提示。
- [x] 六态生命周期 `NEW → ANALYZING → LEARNING → PRACTICING → VERIFYING → MASTERED`，验证失败回落 `PRACTICING` / `LEARNING`。
- [x] **答对一次不会直接 MASTERED**：需要即时恢复成功 + 延迟验证成功（`verify_all.py recovery` 套件断言）。
- [x] `wrong_question_recovery` 表 + 严格 `student_id` 隔离（唯一索引 `(student_id, question_id)`）。
- [x] 错因驱动策略（`recovery/strategy.py`）：计算 / 概念 / 审题 / 单位 / 步骤错误走不同训练。
- [x] 四级提示（1 思考方向 / 2 关键条件 / 3 解决步骤 / 4 完整讲解），记录 `max_level_used`。
- [x] 用提示后答对与独立答对**不等价**（掌握度与记忆增益更低）。
- [x] AI 讲解走既有 DeepSeek 链路，未配 Key 时降级为规则讲解。
- [x] 变式题不复制原题（换数字 / 情境 / 题型），并复用 `validator.QuestionValidator`。
- [x] 康复接入 `MemoryState`：答错降强度、恢复成功提掌握度、延迟验证成功提稳定性。
- [x] `MASTERED` 后知识点继续进入 `ReviewScheduler`。

### 模块 B｜每日学习习惯

- [x] `HabitEngine`（`backend/habit.py`）三段基础任务保持 50/30/20 且生成幂等（既有 `habit` 套件 79 项断言不回归）。
- [x] 五段每日计划 `plan()` / `start_today()`：40/25/20/10/5 起步，按错题积压与复习到期动态调整。
- [x] 按年级限时：1-2 年级 10-15 / 3-4 年级 15-20 / 5-6 年级 20-30 分钟。
- [x] 学习启动仪式：`GET /api/tasks/plan/{student_id}` + `POST /api/tasks/start`，孩子不选知识点与难度。
- [x] 明确结束点：`GET /api/daily-summary/{student_id}` 的 `finished` + `🎉 今天完成啦！` + `今天可以休息啦！`，不默认继续出题。
- [x] `daily_learning_task` 表（生成幂等）与 `learning_habit_profile` 表。
- [x] 画像新增本月学习天数 / 平均每日时长 / 偏好时段 / 休息保护计数。
- [x] 休息保护每月 2 次，不打断连续、不归零历史成长、不可购买。
- [x] 学习目标基础版（`SYSTEM` 来源）。
- [x] 修复 `_profile_dict` 的 `TypeError` 崩溃与 `today()` 幽灵任务。

### 模块 C｜主动回忆基础版

- [x] `ActiveRecallEngine`（`backend/active_recall.py`）+ 24 张内置卡片（数学 / 语文 / 英语各 8）。
- [x] 出卡**不给选项与答案**，孩子主动输入。
- [x] `active_recall_record` 表：题面 / 输入 / 判定 / 提示等级 / 响应时间 / 记忆增益。
- [x] 结果写入 `KnowledgeMastery` 与 `MemoryState`（走 `answer_records` 唯一链路）。
- [x] 完全独立回忆增益（3.0）显著高于用满提示（1.05）。
- [x] 儿童四档反馈文案（🌱 / 🌿 / 🌳 / ⭐），调试接口保留真实数值。

### 集成 / 前端 / 数据库 / 测试 / 文档

- [x] `main.py` 注册 recovery / habit / task / active_recall / daily 五个 router，版本号 V2.5，`/submit` 加康复与习惯钩子，启动补做入队与任务生成。
- [x] 兼容 path 接口全部可用（`/api/recovery/list/{student_id}`、`/api/recovery/{recovery_id}`、`/api/recovery/next-question`、`/api/tasks/today/{student_id}`、`/api/tasks/plan/{student_id}`、`POST /api/tasks/start`、`POST /api/tasks/{task_id}/complete`、`GET /api/habit/profile/{student_id}`、`GET /api/habit/rest/{student_id}`、`POST /api/habit/rest`、`GET /api/habit/goal/{student_id}`），且**没有创建第二套重复 API**。
- [x] 前端新增 `recovery.html` / `recall.html` / `daily.html` / `habit.html`（+ 对应 js），`today.html` 加学习启动仪式与入口。
- [x] 数据库只新增 4 张表 + `learning_habit_profile` 两列；V2.4 数据零删除、迁移幂等。
- [x] 两学生（A=1 / B=2）错题 / 任务 / 主动回忆 / 习惯数据完全隔离（含越权 recovery_id、幽灵任务等边界）。
- [x] `verify_all.py` 扩到 19 个套件；新增 `verify_active_recall.py`（62 项断言）。
- [x] 文档：`CHANGELOG.md`、`docs/TODO.md`、`V25_RELEASE_REPORT.md`、`README.md`、`docs/MODULE_MAP.md`、`ARCHITECTURE.md`、`API_UPDATE.md`、`TEST_REPORT.md`。

---

## V2.5 没做完 / 明确留给后续（`[ ]`）

- [ ] `frontend/verify_recovery_web.js` 仍未编入 `verify_all.py` 的 `SUITES`（它是无端口的前端套件，需要手动 `node` 运行）。
- [ ] `backend/ai_recovery_routes.py`（可选只读 `GET /api/recovery/hint/{recovery_id}`）未实现——当前取提示走 `POST /api/recovery/hint`。
- [ ] `PARENT` / `STUDENT` 来源的学习目标只预留了 `sources` 字段，没有入口与界面。
- [ ] 主动回忆题库是内置 24 张卡片（`CARD_BANK`），**没有** AI 动态扩题；也没有做孩子自定义卡片。
- [ ] `backend/_probe*.db`、`learning.db.v15-backup` 等历史探针/备份文件仍在仓库中（不参与运行），未清理。
- [ ] 错题康复的「变式题」目前以既有题库 + 规则变换为主，AI 变式生成未做全学科覆盖。

## V2.7 计划（本版明确不做）

- [ ] 复杂宠物系统、金币商城、排行榜、社交。
- [ ] 正式账号系统、云同步、多设备。
- [ ] 家长端目标设置与学习报告导出。
- [ ] AI 动态扩题（主动回忆题库 + 错题变式全学科覆盖）。
