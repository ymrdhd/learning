# CHANGELOG — 菲比同学（AI 小学学习系统）

> 记录每个版本的**真实**变更：新增文件、数据库迁移、接口变化、测试基线。
> 未完成的功能不会写进「已完成」，只出现在 [docs/TODO.md](docs/TODO.md)。

---

## 未发版 — 积分商城页（挑战下方）+ 第一版奖励行为明细

> 工作区变更，**尚未升 `version.json`、尚未发版**；发版时把版本号升到 `2.8.1` 并同步本节标题。

### 1. 新增「🛍️ 商城」一级页（挂在右侧「挑战」下方）

- `frontend/shop.html` + `frontend/shop.js`：余额卡（余额 / 今天获得 / 打卡状态 / 连续天数）、商品区（5 件道具 + 「还差 N 分」）、积分明细区、我的积分流水；数据只读 `GET /api/points/{student_id}`，打开页面顺手领 `POST /api/points/{student_id}/login`。
- `frontend/ui-shell.js`：`NAV_TABS` 由 4 项扩到 **5 项**，商城插在「挑战」之后（右侧边栏 ≥1024px 显示，手机底部导航同步）。
- `frontend/style.css`：底部导航改**五列**；新增 `.shop-*` / `.points-row*` 样式（明细三态有颜色区分）。
- 纪律不变：商城**只展示不兑换**（`points.SHOP_ENABLED = False`），页面没有兑换按钮，也没有时长 / 点击奖励。

### 2. 第一版奖励行为明细（`backend/points_rewards.py`）

- 新增积分明细的唯一真相：14 条奖励行为（分值区间 / 星级 / 为什么给分 / 状态），与需求逐条一致：首次真正掌握知识点 +100★★★★★、Deep Mastery 升级 +80、错题完整康复 +80、7 天后仍记得 +70、综合迁移题 +60~80、讲给菲比听 +50、无提示主动回忆 +40、前置知识修复 +40~60、完成今日学习计划 +30、间隔复习成功 +20~40、提示后独立完成 +10~20、普通适龄题独立答对 +2~5、已掌握简单题重复答对 0~1、登录停留点击 0 分。
- `points.py` 的 `summary()` 与 `points_routes.py` 的兜底返回新增 `rewards` / `reward_version` / `reward_states` 三个字段；**加分逻辑与账本一律未改**。
- 状态口径：`live` 已经在自动记分（目前只有「普通适龄题独立答对」，对应 `RULES.answer_correct +2`）、`planned` 先展示规则（12 条，判定尚未接线，**不虚报分数**）、`never` 永不给分（屏幕时间）。

### 3. 验证

- 新增 `frontend/verify_shop_web.js`（套件 `shopweb`，无端口）：48 项断言全通过。
- `backend/verify_points.py` 扩到 47 项断言（奖励行为表 12 项 + 接口明细 1 项 + 登录 / 自动打卡 5 项）：`PASS 47 / FAIL 0`。
- `frontend/verify_ui_shell.js`、`frontend/verify_v26_web.js` 断言随导航 5 项同步，均 ALL PASS。

### 4. 打卡改为「做完今天的学习任务」自动生成 + 新增「每日首次登录 +10」

- `backend/points.py`：`RULES` 新增 `daily_login`（每日首次登录 +10，共 5 条）；新增 `login()`（`once_key="login:<日期>"` 幂等）。
  **打卡不再由「答对一题」触发**，改为当天小任务全部收工（`plan_finished()`）时自动记 `daily_checkin`（`once_key="checkin:<日期>"`）；
  `award_after_answer()` 与 `award_task_done()` 两条完成路径都会结算（`award_task_done` 返回值多一个 `checkin` 字段带回打卡结果）。
- `backend/points_routes.py`：新增 `POST /api/points/{student_id}/login`；`POST /checkin` 端点保留兼容，但语义改为「小任务没做完 → `reason=need_finish`，只提示不给分」。
- `frontend/today.js` / `frontend/shop.js`：**删掉手动打卡按钮与 `doPointsCheckin` / `doCheckin`**，改成一句「做完今天的小任务，打卡自己就来啦」；
  两页打开时自动调 `POST /api/points/{id}/login` 领登录奖励（幂等，失败不影响看积分与做任务）。
- `backend/points_rewards.py`：第一版明细里「登录、停留、点击 0 分」改为「停留、点击、刷页面 0 分」——登录现在另有 +10 奖励，避免明细自相矛盾。

---

## V2.6 — 儿童体验重构 + 健康学习习惯 + 知识地图 + 成长中心 + 分龄 UI

本版**不新增学习算法**，目标是把 V2.0-V2.5 的七套引擎包装成孩子自己能每天用的连续体验：打开就是「今天」，点一次「开始今天的学习」连续走完当天任务，**做完进入明确结束页**，不做无限加题。

### 1. 儿童端信息架构与首页聚合

- 一级导航收敛为 4 个：🏠 今天 / 🗺 成长 / ⚔️ 挑战 / 👤 我的（`frontend/ui-shell.js` 的 `NAV_TABS`）；复习 / 主动回忆 / 测评 / 错题本不再是一级入口，统一由今日学习流程调度。
- `start.bat` 启动后直接打开儿童首页 `/app/today.html`；`index.html` 保留为自由练习页（默认落地不再走它）。
- 新增聚合接口 `GET /api/home/{student_id}`（`backend/home_routes.py`）：一次返回 `student / daily_plan / daily_progress / review_due_count / recovery_count / growth_highlight / phoebe_message` + 主按钮文案，**只聚合、不重算任何学习算法**；已经开跑就报真实落库任务，没开始才给只读预览（`habit.plan(persist=False)`）。
- 新增 `backend/kid_status.py`：数值 → 儿童语言的**唯一** UI 适配器（掌握度 90/75/55/30 → ⭐ 记得很牢 / 🌳 已经掌握 / 🍀 基本会了 / 🌿 正在学习 / 🌱 刚开始），成熟度只做「下限抬档」，**不改任何底层算法**；前端同口径在 `frontend/kid-lang.js`。

### 2. 统一学习会话 LearningSession

- 新增 `frontend/learning-session.js`：管理 currentStudent / dailyPlan / currentTask / currentQuestion / taskProgress / sessionProgress / completedTasks；`start()` 调 `POST /api/tasks/start`，`choose(taskId)` 允许孩子决定**先做哪个任务**（知识点 / 题目 / 难度仍由系统决定），`tick()` 完成一个小任务后自动切下一个，全部完成后 `finish()` 拉 `GET /api/daily-summary/{student_id}` 进结束页。
- `mayContinue()` 是**结束机制的技术实现**：`finished` 或 `remaining == 0` 时返回 `false`，`today.js` 的自动跳题与 `nextQuestion()` 都会因此停下，不会无限推荐下一题。
- `frontend/today.js` 新增会话条（已完成 N / M 个小任务）、任务选择器、结束卡；所有会话调用都走 `sessionApi()`，拿不到时完全退回 V2.5 行为（不影响既有断言）。

### 3. 做题页去干扰与儿童化反馈

- 做题页只留：科目/知识点 + 进度、题目、答题区、🔊 读题 / 💡 提示、「我做好了」主按钮；无金币 / 商城 / 排行榜 / 活动 Banner。
- 新增统一 🔊 读题（浏览器原生 `SpeechSynthesis`，支持播放/停止，**失败不影响答题**）与答错后的 💡 分级提示入口（复用 V2.5 `hint_level`）。
- 答错文案改为「🤔 这里再想一下」+ 看看提示 / 我再试试；普通答对保持轻量「✓ 对啦」，只有真实成长事件（升档 / 长期复习成功）才给强化反馈。

### 4. 结束机制（本版 P0）

- 所有今日任务完成后进入 Daily Completion：「🎉 今天完成啦！」+ 今天你学会了几个 / 巩固几个 / 攻克几个 / 主动回忆几次 / 学习分钟数 + 菲比「今天已经完成啦，可以去休息了！」，主按钮「完成」、次按钮「看看我的成长」。
- **没有任何「再做 10 题 / 再学 5 分钟 / 领取额外奖励」入口**；本版也不引入 Loot Box / 抽卡 / 随机大奖 / 断签清零 / 在线时长奖励 / 排行榜。

### 5. 知识地图

- 新增 `backend/knowledge_map_routes.py` + `GET /api/knowledge-map/{student_id}?subject=`：区域（region）+ 知识节点（`ui_status` / `children` / `is_unlocked` / `recommended`），**全部来自真实知识点树 + 掌握度 + 记忆状态**，前端不写死任何状态。
- 区域进度只按真实成长计数（如「12 / 16 知识已成长」）；解锁条件是「已练过（rank ≥ 1）或掌握度 ≥ 30」，**不能用时长 / 签到 / 金币解锁「已掌握」**。
- `frontend/knowledge_map.html` + `knowledge_map.js` 增加探索进度区（区域卡片 + 节点状态胶囊），V2.5 的领域星级明细列表原样保留。

### 6. 成长中心

- 新增 `backend/growth_routes.py` + `GET /api/growth/{student_id}?days=7&date=`：本周学习天数 / 新掌握知识 / 记得更牢 / 攻克挑战 / 复习成功 / 主动回忆成功 / 学习分钟数 + 三科能力阶段变化（`auto_ability` 只读复用）+ 成长时间线（最近 12 条真实事件）。
- 只讲「学会了什么 / 记住了什么 / 攻克了什么」，**不把累计题量、在线时长当作成长**；连续学习显示本月天数 / 当前连续 / 最长连续，并保留 V2.5 的休息保护入口，休息一天不清空历史。
- `frontend/growth.html` / `growth.js` 已接入（保留原有三接口渲染，`/api/growth` 作为可选增强）。

### 7. 挑战中心

- 新增 `backend/challenge_routes.py` + `GET /api/challenge/{student_id}?subject=&limit=`：把错题中心包装成「⚔️ 我的挑战」，按 🔴 等我攻克 / 🟡 正在训练 / 🟢 已经攻克 分组，**底层完全复用 V2.5 `WrongQuestionRecoveryEngine`，没有第二套康复算法**。
- 列表**刻意剔除 `correct_answer` / `analysis`**（遵守「出题接口不下发答案」）；新增 `frontend/challenge.html` + `challenge.js`，点「去攻克」走既有 `POST /api/recovery/start` 后跳转康复页。

### 8. 分龄 UI、Design Tokens 与响应式

- `frontend/ui-shell.js` 的 `ageModeOf(grade)`：1-2 年级 `junior`（大按钮 56px / 大字号 / 一屏一题 / 明显读题入口）、3-4 `middle`、5-6 `senior`，写入 `documentElement` 的 `data-age-mode`。
- `frontend/style.css` 顶部为唯一 Design Tokens 来源（颜色 / 字号 / Spacing / Radius / Shadow / Motion / Breakpoints），并补齐儿童端公共组件：Button（primary/secondary/ghost/speak）、Card、Status Badge、Progress、Modal（学生切换二次确认）、Toast、BottomNavigation、Loading / EmptyState / ErrorState。
- 交互区 ≥ 44px（JUNIOR 56px）、整个答案卡片可点；尊重 `prefers-reduced-motion`；手机 / 平板竖屏 / 平板横屏 / 桌面四档断点。

### 9. 双学生隔离

- 切换学生必须二次确认（「确定切换到 X 吗？」），确认后由 `UIShell.onStudentChange` 统一清空并重拉首页 / 计划 / 成长 / 知识地图 / 挑战数据；`today.js` / `growth.js` / `challenge.js` 都在切换时先清空再请求，**不会短暂显示上一个孩子的数据**。

### 10. 测试与文档

- `verify_all.py` 套件从 21 个扩到 **23 个**：新增 `v26`（端口 8913，后端聚合 / 知识地图 / 成长 / 挑战 / 隔离 / 回归，63 项断言）与 `v26web`（前端今天页 / 挑战页 / 知识地图页 / 学习会话，65 项断言）。
- 新增 `backend/verify_v26.py`、`frontend/verify_v26_web.js`；`frontend/verify_ui_shell.js` 新增 V2.6 壳校验。
- 数据库**没有新表、没有新列**（纯展示层 + 聚合层），V2.5 数据与算法完全不变。
- 更新 `README.md`、`docs/TODO.md`、`ARCHITECTURE.md`；新增 `V26_RELEASE_REPORT.md`。

### 11. 上线后试用反馈修复

- **「开始今天的学习」点不动**：根因是旧进程仍占着 `8000`（只 import 了旧版 Python 代码，静态文件却是磁盘上新版），于是 V2.6 的 `/api/home/*`、`/api/tasks/*` 全部 404。`start.bat` 改为**先读 8000 上的 `version`**：已是 `2.6` 就直接开浏览器，否则在 8000–8010 里挑第一个能绑定的空闲端口启动新版，并在控制台提示「8000 上是旧版本」。
- **🔊 读题目没声音**：`app.js` / `today.js` 的朗读改为**孩子主动点按即强制朗读**（不再被语音开关挡住），修掉 Chrome「`cancel()` 后立刻 `speak()` 被吞掉」的时序问题（先停再延迟 120ms 读），补 `resume()` / `volume=1` / `onerror` 提示；朗读失败只提示，**不影响答题**。
- **菲比收藏（新）**：知识等级提升（🌿→🌳 等）时，`phoebe3d.js` 在**左侧空白处多放一只菲比**（`phoebe3dCollect()`）；表情只从 `like` / `cheer` / `cute` / `encourage` 里挑（**不含答对 happy、答错 sad**），且不用立牌当前正在显示的那张；优先挑没收藏过的；上限 12 只；按学生分键存 `localStorage`（`xiaozhi.phoebe.fumo.{student_id}`），换孩子互不串。奖励的是**知识等级提升**，不是在线时长。
- `frontend/verify_phoebe3d_web.js` 新增 11 项收藏断言（初始为空 / 每次 +1 / 表情范围 / 不等于当前表情 / 不重复 / 换学生隔离 / 上限 / 单容器 / 正面素材 / 不挡点击 / 窄屏隐藏），并让沙箱 DOM 的 `innerHTML` 赋值真正清空子节点（与浏览器一致）。
### 12. 知识点目标按能力动态调整（第二次试用反馈）

- **问题**：自由练习页（`index.html`）的「知识点」写死 `value="20以内加减法"`，语文 / 英语各只有一句固定默认值——孩子的能力涨了，目标也不动。
- **做法**：`app.js` 的 `applyAutoKnowledge()` 改为**首选 V2.3 自适应引擎的 `GET /api/learning/recommend/{student_id}?subject=`**（知识点 / 难度 / 动作 / 理由都由引擎算；零记录学生它也会给出「当前能力阶段的重点」），`pickRecommendedKnowledge(data)` 依次取 `primary.knowledge → next_action.knowledge`；引擎拿不到时才退回旧的 `/api/ability/auto` + `/api/mastery` 启发式，最后才是 `DEFAULT_KNOWLEDGE`。**不重复实现任何学习算法。**
- **提示儿童化**：新增 `#knowledge-hint` 提示行，文案按引擎动作映射（`review` → 「这个知识有点快忘了，今天再看一眼」、`practice` → 「这个知识再练几遍就更牢啦」、`diagnostic` → 「先做几道题，菲比就能看清你的水平」），**不显示掌握度 / 遗忘风险等算法数字**（`knowledgeHintFor()`）。
- **跟着能力走**：换学生 / 换科目重新挑；每答完一题 `renderResult()` 末尾 `applyAutoKnowledge(true)` 重挑一次；孩子自己改过知识点后 `manualKnowledge` 置位，菲比不再覆盖（只更新提示）。
- 实测（`/api/learning/recommend`）：朵朵（有记录）数学 `10以内加减法`（间隔复习）/ 语文 `古诗名句` / 英语 `26个字母`，三科各不相同；童童（零记录）语文 `拼音与声调` / 英语 `26个字母`。
- `frontend/verify_web.js` 新增 10 项断言（HTML 不再写死默认值 / 有提示行 / 源码走 recommend 接口 / `primary` 取值 / 退回 `next_action` / 空数据返回 `null` / 三科各自取目标 / 答完一题按能力重挑 / 提示行不含算法数字 / 孩子改过不覆盖），该套件共 44 项全绿。

## V2.5 — 错题康复 + 每日学习习惯 + 主动回忆基础系统

本版在原「菲比互动 / 自动能力诊断」的基础上，补齐学习科学闭环的后半段：**答错之后怎么办**、**每天学什么由系统决定**、**复习不只靠重新做题**。

### 1. 错题康复（Wrong Question Recovery）

- 新增 `backend/recovery/`：`engine.py`（门面 `WrongQuestionRecoveryEngine`）、`state.py`（六态生命周期）、`strategy.py`（错因驱动策略）、`scheduler.py`（入队 / 到期验证 / 超时回落）。
- 生命周期：`NEW → ANALYZING → LEARNING → PRACTICING → VERIFYING → MASTERED`；验证失败 `VERIFYING → PRACTICING` 或 `LEARNING`；**答对一次永远不会直接 MASTERED**（`MASTERED` 需要一次即时恢复成功 + 一次延迟验证成功）。
- 新表 `wrong_question_recovery`：严格按 `student_id` 隔离，唯一索引 `(student_id, question_id)`，另含 `state / state_before / attempts / correct_count / consecutive_correct / fail_count / max_level_used / variant_count / last_state_change / next_verify_time / mastered_time / source`。
- 提示分级：`POST /api/recovery/hint` 提供 1 思考方向 / 2 关键条件 / 3 解决步骤 / 4 完整讲解；用提示后答对的掌握度与记忆增益**低于**独立答对。
- AI 讲解：复用既有 DeepSeek 链路（未配置 Key 时自动降级为规则讲解）。
- 与 V2.4 打通：答错通过 `review.engine.record_learning` 降 `memory_strength` / `stability`；恢复成功提高 `mastery_score`；延迟验证成功提高 `stability`；`MASTERED` 后知识点继续由 `ReviewScheduler` 长期维护。

### 2. 每日学习习惯（Daily Habit）

- `backend/habit.py` 新增五段每日计划：`plan()` / `start_today()`，权重起步 **40% 新学习 / 25% 薄弱补强 / 20% 复习 / 10% 错题康复 / 5% 主动回忆**，并按「未掌握错题数」与「到期复习数」动态调整（错题积压提高错题康复；复习到期提高复习；没有到期复习把时间转给新学习与薄弱补强）。
- 总时长按年级限制：1-2 年级 10-15 分钟 / 3-4 年级 15-20 / 5-6 年级 20-30（`GRADE_MINUTES` + `minutes_for_grade`）。
- 孩子只点一次「▶️ 开始今天的学习」（`POST /api/tasks/start`），系统自行安排知识点；`POST /api/tasks/{task_id}/complete` 上报完成与用时。
- 学习仪式与结束点：`GET /api/tasks/plan/{student_id}` 返回「今天我们用 N 分钟完成 M 个小任务。」；全部完成后 `GET /api/daily-summary/{student_id}` 返回 `finished=true` + `🎉 今天完成啦！` + 儿童版清单 + `今天可以休息啦！`，不再默认继续出题。
- 新表 `daily_learning_task`（按 `student_id + date + task_type + subject + knowledge` 唯一，生成幂等）与 `learning_habit_profile`（连续 / 最长连续 / 累计天数与时长 / 完成率 / 徽章 / 等级）。
- 画像新增 `monthly_learning_days` / `average_daily_minutes` / `preferred_learning_time` / `rest_protection_count` / `rest_protection_month` / `rest_protection_left`。
- **休息保护**（`GET /api/habit/rest/{student_id}`、`POST /api/habit/rest`）：每月上限 2 次，使用后不打断连续学习、**不归零任何历史成长数据**，且不提供购买。
- 学习目标基础版（`GET /api/habit/goal/{student_id}`）：来源 `SYSTEM`，`PARENT` / `STUDENT` 仅预留 `sources`。
- 修复：`_profile_dict` 中把日期字符串集合当字典集合索引导致的 `TypeError`（会让画像接口整体降级为空结构）；`today()` 对不存在的学生返回空结构，不再生成幽灵任务。

### 3. 主动回忆基础系统（Active Recall）

- 新增 `backend/active_recall.py` + `backend/active_recall_routes.py`：内置 24 张卡片（数学 / 语文 / 英语各 8 张，覆盖公式、概念、古诗名句、字词、英语单词与句型）。
- 出卡**只给题面与提示，不给选项**；孩子自己写出答案后由 `judge()` 判 `correct` / `partial` / `wrong`。
- 记忆增益：完全独立回忆成功 `BASE_GAIN = 3.0`；用满提示后成功仅 `1.05`（`HINT_FACTOR`），部分正确 0.5 倍，回忆失败会压低稳定性。
- 结果同时影响 `KnowledgeMastery` 与 `MemoryState`：写 `answer_records` → `knowledge_routes.update_mastery` → `review.engine.record_learning` → `refresh_risks(force=True)`。
- 新表 `active_recall_record`（题面 / 学生输入 / 判定 / 提示等级 / 响应时间 / 记忆增益）。
- 儿童反馈四档：🌱 正在学习 / 🌿 基本会了 / 🌳 已经掌握 / ⭐ 记得很牢；调试与家长接口仍保留真实数值。

### 4. 集成与前端

- `backend/main.py`：注册 `recovery` / `habit` / `task` / `active_recall` / `daily` 五个 router，`/submit` 增加错题康复与习惯钩子，启动时补做错题入队与当天任务生成，应用标题升级为 V2.5。
- 新增兼容 path 接口（不改动原有接口，避免第二套 API）：`GET /api/recovery/list/{student_id}`、`GET /api/recovery/{recovery_id}`、`GET /api/recovery/next-question`、`GET /api/tasks/today/{student_id}`、`GET /api/tasks/plan/{student_id}`、`POST /api/tasks/start`、`POST /api/tasks/{task_id}/complete`、`GET /api/habit/profile/{student_id}`、`GET /api/habit/rest/{student_id}`、`POST /api/habit/rest`、`GET /api/habit/goal/{student_id}`。
- 前端新增 4 组页面：`recovery.html`+`recovery.js`、`recall.html`+`recall.js`、`daily.html`+`daily.js`、`habit.html`+`habit.js`；`today.html`/`today.js` 增加学习启动仪式（「开始今天的学习」）与三个新页面入口；`style.css` 追加 46 行样式。仍为零构建原生页面。

### 5. 数据库迁移

- **只新增表与列**，不删除、不重建、不清空：`ensure_schema` 自动 `ALTER TABLE ... ADD COLUMN`。
- 新增 4 张表：`wrong_question_recovery`、`daily_learning_task`、`learning_habit_profile`、`active_recall_record`（共 23 张表）。
- `learning_habit_profile` 加两列 `rest_protection_month` / `rest_protection_count`。
- V2.4 数据（`answer_records` / `student_knowledge_mastery` / `knowledge_memory_state` / 各复习表）行数与列均不变，迁移幂等（二次迁移改动 0 行）。

### 6. 测试与文档

- `verify_all.py` 套件从 16 个扩到 19 个：新增 `recovery`(8910)、`habit`(8911)、`recall`(8912)。
- 新增 `backend/verify_active_recall.py`（62 项断言）、以及 `recall` 套件内的前端页面静态检查（`page_case`）。
- 集成回归与修复：①`frontend/today.js` 学习启动仪式插入时误删 `.then(...)` 收尾 `})`，`node --check` 报 `today.js:562 SyntaxError: Unexpected token '.'` 并使 `adaptweb` 套件失败，已修复；②`verify_habit.py` 两条日期分区断言原用不存在的 `student_id = 9` 并依赖「幽灵任务」落库，已改用真实 `STUDENT_B`，与新契约（未知学生 → 200 空结构、不写任务行）对齐，测试意图不变。
- 新增文档：`CHANGELOG.md`、`docs/TODO.md`、`V25_RELEASE_REPORT.md`；更新 `README.md`、`docs/MODULE_MAP.md`、`ARCHITECTURE.md`、`API_UPDATE.md`、`TEST_REPORT.md`。
- 全量基线（实测）：`verify_all.py` → `RESULT: ALL PASS（合计 169.3s）`，退出码 0（19 个套件）；`check_cards.py` → 模块 98 / 缺卡片 0 / 失真 0 / 需人工确认 9，退出码 0。
- 已知未完成项见 [docs/TODO.md](docs/TODO.md)（例如 `frontend/verify_recovery_web.js` 仍未编入 `SUITES`、`ai_recovery_routes.py` 未实现）。

---

## V2.4 — 间隔复习系统

- `backend/review/`：`memory.py`（记忆状态与成熟度）、`forgetting.py`（遗忘风险）、`interval.py`（自适应间隔 1→3→7→14→30 天起步）、`scheduler.py`（复习队列优先级）、`selector.py`（复习题不重复旧题）、`mix.py`（每日配比）、`engine.py`（门面）。
- 新表 `knowledge_memory_state` / `review_records` / `review_queue` / `review_strategy_log`；`/api/review/*` 13 个接口。
- 儿童端「知识浇水」页 `review.html`；家长端记忆数据 `memory_debug.html`。
- 日计划配比 50% 新学 / 30% 薄弱补强 / 20% 间隔复习。

## V2.3 — 知识掌握模型 + 错因分析 + 自适应学习

- `mastery.py`（掌握度 / 置信度 / 下次复习）、`knowledge_tree.py`（知识点树）、`error_analysis.py`（错因分析）、`wrong_book.py`（错题本状态机）、`validator.py`（AI 题目审核）。
- `backend/adaptive/`：策略 / 难度控制 / 下一题推荐 / 每日计划 / 门面；新表 `student_knowledge_mastery`、`knowledge_points`、`answer_error_analysis`、`wrong_questions`、`learning_plan` 等。
- `knowledge_routes.update_mastery` 成为**掌握度唯一写入口**。

## V2.2 — 能力诊断

- 24 个能力阶段（如 3.2 = 三年级熟练）、诊断状态机与三科题库、诊断报告页。

## V2.1 — 艾宾浩斯复习闭环

- `srs.py` 复习计划与状态推进，`/reviews` 面板，语音朗读。

## V1.5 — 基础练习闭环

- `main.py` 出题 → 判分 → 记录 → 复习，`grading.py` 作为判分唯一真相，原生 HTML/CSS/JS 前端 + SQLite。
