# 菲比同学 · 儿童端 UI/UX 重设计 — 设计说明（Spec）

- 日期：2026-10-05
- 状态：待用户复审
- 范围：仅儿童端 UI / UX / 信息架构 / 交互 / 响应式 / Design System / 微交互 / 易用性
- 明确不改：能力诊断算法、自适应学习算法、知识掌握算法、间隔复习算法、错题康复算法、DeepSeek 调用逻辑、数据库核心结构

---

## 0. 已获用户批准的决策（m00070「按推荐方案」）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 菲比立牌行为 | **保留现状**：无宿主时自动挂左侧固定立牌（`phoebe3d.js` + `.p3d-stage.p3d-floating`）。新增「专注模式 / 减少动画」设置让立牌淡出，**不重写**现有立牌 CSS 契约与断言 |
| D2 | 儿童端隐藏算法指标 | **改写前端儿童文案断言**为儿童化契约；家长端 `memory_debug.html` 保留原始指标，其断言不动 |
| D3 | 主品牌色 | `--color-primary: #5B6EF5`（柔和蓝紫）+ `--color-accent: #FFB84D`（暖黄辅助），替代现状 `#4a7cf3` |

### 0.1 一处需在复审时确认的细节

用户简报 §16 给出的 5 档里，`🌿` 被复用于「正在学习」与「基本会了」两档。为满足 §32「状态不能只靠颜色区分」，本设计将第 3 档图标改为 `🍀`，**文字标签严格沿用用户原文**：

```
🌱 刚开始   🌿 正在学习   🍀 基本会了   🌳 已经掌握   ⭐ 记得很牢
```

若坚持两档同用 `🌿`，第 3 档将无独立视觉标识，退化为仅靠颜色/文字位置区分。

---

## 1. 目标与成功标准

### 1.1 目标
1. 孩子首次打开 3 秒内知道「现在该做什么」。
2. 学习过程零干扰：一屏一题、一屏一个主行动。
3. 学习结束后集中给成长反馈；每日任务有**明确结束状态**。
4. 建立一套 Design System，消灭「每页自定义样式」。
5. 建立 4 项一级导航 + 统一 `currentStudent` 状态，消灭每页重复的学生切换代码。
6. 分龄（JUNIOR / MIDDLE / SENIOR）+ 响应式（手机 / 平板竖屏 / 平板横屏 / 桌面）。

### 1.2 长期 UI 原则（写入 `ARCHITECTURE.md`）
- 「菲比同学儿童端首先帮助孩子完成学习，而不是最大化使用时长。」
- 「学习过程中减少干扰，学习结束后集中提供成长反馈。」
- 「儿童页面不直接展示复杂学习算法指标。」

### 1.3 非目标（本阶段不做）
金币商城、排行榜、公开社交、复杂宠物系统、抽卡、盲盒、活动中心、付费弹窗、正式家长 Dashboard。

---

## 2. 硬约束（不可协商）

| 约束 | 来源 | 影响 |
|---|---|---|
| 零构建：禁止 npm / bundler / CDN / ES `import`·`export` | `AI_RULES.md` §13.7 | 共享代码只能靠**新增普通 `<script>` 标签**顺序加载 |
| 一页 = 同名 `.html` + 同名 `.js` | 同上 | 新增页面也必须成对创建 |
| `phoebe.js` 必须排在业务 js 之前；`phoebe3d.js` 紧随其后 | 同上 | 新共享脚本插入位置须固定 |
| 改前端必须跑对应 `frontend/verify_*.js` | 同上 | 每个改动的文件都要有对应套件 |
| 测试端口固定，禁止并发跑多套件 | §13.8 | 验证串行执行 |
| 禁止写 `backend/learning.db` | §13.9 | 只用 `_verify_*.db` |
| 不引入新测试框架（无 pytest） | §13.8 | 复用 `verify_all.py` + `verify_*.js` |
| 已发布 API 只允许新增字段，不改语义；前端禁止碰判分逻辑 | §13.3 / §13.5 | UI 只消费现有接口 |
| 后端（本次不涉及）单文件 ≤250 行 + 契约卡 | §5.1 | 本次不新增后端文件 |

### 2.1 必须原样保留的 CSS 契约（`frontend/style.css`）

`frontend/verify_phoebe3d_web.js` 用**紧凑正则**锁死了以下三条，重写 `style.css` 时必须逐字保留（无空格、无换行变化）：

1. `.p3d-stage.p3d-floating{position:fixed;left:...}` —— 且**不得**含 `right:`
2. `@media (max-width:1280px){.p3d-stage.p3d-floating{left:10px;width:250px...}}`
3. `@media (max-width:1060px){.p3d-stage.p3d-floating{width:200px...}}`

### 2.2 现有学生状态字面值（不得更改）
- localStorage key：`xiaozhi.student`（14 个文件各自定义常量）
- 语音开关 key：`xiaozhi.voice`（`app.js:46`）、`xiaozhi.voiceRate`（`app.js:47`）
- 立牌语音 key：`xiaozhi.phoebeVoice`（`phoebe3d.js:196`）

新 `ui-shell.js` 必须复用同一 key 字面值，保证既有用户选择不丢失。

---

## 3. Design Tokens（`frontend/style.css` 顶部 `:root`）

### 3.1 颜色

```
/* 品牌 */
--color-primary:        #5B6EF5
--color-primary-soft:   #EAEDFE
--color-primary-hover:  #4E62E8
--color-primary-strong: #4453D6
--color-accent:         #FFB84D
--color-accent-soft:    #FFF3DC

/* 状态 */
--color-success:        #2FA84F    --color-success-soft: #E6F6EA
--color-warning:        #E8A33D    --color-warning-soft: #FDF1DC
--color-attention:      #F0A93B    --color-attention-soft: #FFF4E5   /* 答错/再想一下，柔和橙 */
--color-error:          #D9534F    --color-error-soft: #FDECEC       /* 仅危险操作 */

/* 表面 */
--color-background:     #F5F7FC
--color-surface:        #FFFFFF
--color-surface-soft:   #F0F3FA
--color-border:         #DDE4F2
--color-border-strong:  #C7D2E8

/* 文本 */
--color-text-primary:   #1F2A44
--color-text-secondary: #5C6B8A
--color-text-muted:     #8A97B0
--color-text-on-primary:#FFFFFF
```

**用色纪律**
- 答错**禁止**大面积鲜红；统一走 `--color-attention` + `🤔 这里再想一下`。
- `--color-error` 只用于真正危险操作（删除/重置/切换学生后的不可逆提示）。
- 状态一律「图标 + 文字 + 颜色」三重表达，禁止只靠颜色。

### 3.2 圆角 / 间距 / 阴影

```
--radius-small:  10px     --radius-medium: 16px     --radius-large: 22px     --radius-pill: 999px
--space-xs: 4px  --space-sm: 8px  --space-md: 12px  --space-lg: 16px  --space-xl: 24px  --space-2xl: 32px
--shadow-sm: 0 2px 8px rgba(70,110,180,.08)
--shadow-md: 0 6px 20px rgba(70,110,180,.12)
--shadow-lg: 0 12px 32px rgba(70,110,180,.16)
--border-hairline: 1px solid var(--color-border)
```

层级纪律（用户 §28）：页面最多 3 层 —— 背景 / 卡片 / 内容。**禁止卡片套卡片套卡片。**

### 3.3 字体与字阶

```
--font-family: "PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,-apple-system,sans-serif
--text-body:   17px   /* 正文，1.5 行高 */
--text-label:  15px
--text-title:  28px   /* 主标题 24-32 */
--text-question: 22px /* 题目 20-28 */
--leading-base: 1.5
--leading-loose: 1.6
```

不使用艺术化儿童字体。低年级字阶见 §4。

### 3.4 动效

```
--motion-fast: 200ms   --motion-base: 300ms   --motion-slow: 600ms   --motion-celebrate: 1200ms
--ease-out: cubic-bezier(.22,.61,.36,1)
```

**双开关**：`@media (prefers-reduced-motion: reduce)` 与用户设置 `html[data-reduce-motion="on"]` 都强制把动效时长归零。
上限纪律（用户 §29）：普通点击 200-400ms；普通答对 <600ms；知识升级 1-2s；今日完成可稍丰富。**禁止无法跳过的长动画。**

### 3.5 触控尺寸

```
--tap-min: 44px        /* 通用最小点击区 */
--tap-junior: 56px     /* 低年级主操作 */
```

---

## 4. 分龄系统

### 4.1 推导规则
`grade` 来自 `GET /students` 的 `student.grade`（`backend/main.py:268-275` 已返回）。

```
ageMode = grade <= 2 ? "junior" : grade <= 4 ? "middle" : "senior"
```

写入 `<html data-age-mode="junior|middle|senior">`，由 `ui-shell.js` 在拿到学生列表后设置。CSS 按属性选择器调整，**不复制页面**。

### 4.2 各档规则

| 维度 | JUNIOR (1-2) | MIDDLE (3-4) | SENIOR (5-6) |
|---|---|---|---|
| 正文 | ≥18px | 17px | 17px |
| 题目 | 24-28px | 22-24px | 20-22px |
| 主操作按钮高 | ≥56px | ≥48px | ≥44px |
| 选项卡片 | 全宽大卡，纯图标+短词 | 全宽卡 | 全宽卡 |
| 数字呈现 | 尽量少 | 今日目标/完成度 | 学习计划/能力趋势 |
| 语音读题 | 默认显眼 | 提供 | 提供 |
| 可见模块 | 一屏一题，无地图 | + 简单知识地图、成长状态、错题状态 | + 学习计划、能力趋势、成长数据 |
| 上限 | 无 Dashboard | 简单 | 仍非成人 Dashboard |

`[data-age-mode="junior"]` 额外：隐藏一切百分比数字，进度用「星星/段条」图形表达。

### 4.3 已知限制与处理
项目当前两个本地学生 `grade` 均为 1（`backend/local_users.py:15-16`），因此默认落在 JUNIOR。为了让三档都可验证，`verify_ui_shell.js` 直接对 `ageModeOf()` 做纯函数断言（1..6 全覆盖），不依赖真实学生数据。

---

## 5. 儿童化语言映射（唯一实现：`frontend/kid-lang.js`）

### 5.1 掌握度 → 五档

| mastery | 图标 | 标签 | tone |
|---|---|---|---|
| `>= 90` | ⭐ | 记得很牢 | solid |
| `>= 75` | 🌳 | 已经掌握 | success |
| `>= 55` | 🍀 | 基本会了 | success-soft |
| `>= 30` | 🌿 | 正在学习 | warning |
| `< 30` | 🌱 | 刚开始 | neutral |
| 无数据 | 🌱 | 还没开始学 | neutral |

**全产品统一使用这套语言**，禁止儿童端出现 `Mastery: 76.8`、`Stability: 5.6`、`Forgetting Risk: 72%`。

### 5.2 其它映射

| 内部概念 | 儿童表达 |
|---|---|
| 遗忘风险 76% | 「🌱 今天有 3 个知识需要照顾。」 |
| 复习成功升级 | 「🌿 → 🌳　这个知识记得更牢啦！」 |
| 答错 | 「🤔 这里再想一下」+ 小提示 + 「我再试试」 |
| 提交 | 「我做好了」 |
| 知识点掌握度提升 | 「这个知识你已经记得更牢啦！」 |
| 错题状态 | 🔴 待攻克 / 🟡 训练中 / 🟢 已攻克 |
| 错误数据库 | 「我的挑战」 |

### 5.3 错题帮助的逐级递进（UI 表现，不改算法）

| 第几次答错 | UI 呈现 |
|---|---|
| 1 | 方向提示 |
| 2 | 关键条件 |
| 3 | 步骤提示 |
| 4 | 完整讲解 |

呈现口径：「菲比在帮助我」，不是「系统在处罚我」。具体提示内容仍来自后端既有接口（`/api/recovery/hint` 等），UI 只负责措辞与视觉分级。

---

## 6. 信息架构与导航壳

### 6.1 一级导航（恰好 4 项）

| Tab | 图标 | 落地页 | 说明 |
|---|---|---|---|
| 今天 | 🏠 | `today.html` | 今日任务主入口；复习(知识浇水)与主动回忆作为任务流内步骤 |
| 成长 | 🗺 | **新增 `growth.html`** | 本周成长 + 知识地图 + 能力趋势聚合 |
| 错题 | ⚔️ | `wrong_book.html`（改造为「我的挑战」） | 点击进入既有错题康复流程 |
| 我的 | 👤 | **新增 `profile.html`** | 头像/昵称/年级/切换学生/声音/显示/减少动画 |

### 6.2 响应式导航形态（同一份 IA）

| 视口 | 形态 |
|---|---|
| `< 720px`（手机） | 底部固定导航 |
| `720px – 1023px`（平板竖屏） | 底部固定导航 |
| `>= 1024px`（平板横屏 / 桌面） | 左侧边栏 |

### 6.3 旧页面归位（保留文件，移出主流程）

| 页面 | 新位置 |
|---|---|
| `index.html` 自由练习 | 「今天」页与「我的」页的次级入口（Secondary 按钮） |
| `review.html` 知识浇水 | 「今天」任务流步骤；也可由「成长」页次级入口进入 |
| `recall.html` 主动回忆 | 「今天」任务流步骤 |
| `daily.html` 今日完成 | 「今天」任务流终点的完成页 |
| `habit.html` 学习习惯简报 | 「成长」页次级入口 |
| `ability.html` 能力水平 | 「成长」页内嵌或次级入口 |
| `knowledge_map.html` 知识地图 | 「成长」页内嵌或次级入口 |
| `study_advice.html` 学习建议 | 「成长」页次级入口 |
| `recovery.html` 错题康复 | 由「错题」页进入 |
| `memory_debug.html` 记忆调试 | **家长端**，保留，不进儿童导航 |
| `diagnostic*.html` 三页 | 保留，不进儿童导航 |

**移除**：现有每页底部硬编码的 10 个 `.link-row` 链接，由导航壳统一承担。

### 6.4 视觉信息层级
每个页面**最多 1 个 Primary Action**：

| 页面 | Primary Action |
|---|---|
| 今天 | 开始今天的学习 |
| 学习页 | 我做好了 |
| 每日完成页 | 查看我的成长 |
| 成长 | （无主按钮，纯浏览） |
| 我的挑战 | （进入康复流程的卡片本身） |
| 我的 | （无主按钮） |

其余按钮一律 Secondary / Tertiary 样式。

---

## 7. 共享前端层（3 个新脚本，普通 `<script>`）

加载顺序固定为：`ui-shell.js` → `kid-lang.js` → `ui-components.js` → `phoebe.js` → `phoebe3d.js` → 业务 js。

> 说明：`phoebe.js`/`phoebe3d.js` 必须在业务 js 之前（§13.7 契约）。新脚本放在最前，可让 `ui-shell.js` 之后所有脚本（含 `phoebe3d.js`）复用统一学生状态；`verify_phoebe3d_web.js` 只断言 phoebe3d 与业务 js 的相对顺序，在其之前插入脚本不违反其契约（实施时逐个套件回归确认）。

### 7.1 `frontend/ui-shell.js`

```js
window.UIShell = {
  STUDENT_KEY: "xiaozhi.student",
  SETTINGS_KEY: "xiaozhi.uiSettings",

  ageModeOf(grade),                  // (1..6) -> "junior"|"middle"|"senior"
  applyAgeMode(grade),               // 写 <html data-age-mode>

  getStudentId(),                    // 读 localStorage，缺省 "1"
  loadStudents(),                    // GET /students -> [{id,name,grade,grade_text}]
  setStudentId(id),                  // 写 localStorage 并广播
  onStudentChange(handler),          // 订阅；切换后业务页重新渲染

  getSettings(),                     // {sound:true, reduceMotion:false, fontScale:1, focusMode:false}
  setSettings(patch),
  applySettings(),                   // 写 <html data-*> 属性

  mountNav(activeTab),               // 渲染底部导航 / 侧边栏
  confirmSwitch(student),            // 返回 Promise<boolean>，「确定切换到小朋友B吗？」
  createStudentSwitcher(el)          // 统一的学生切换控件（避免误触）
}
```

**切换学生防误触（用户 §24）**：点击目标学生 → 弹确认「确定切换到 XX 吗？」→ 确认后写 localStorage → 调 `onStudentChange` 订阅者刷新**全部**当前学生 UI 状态（今日计划、任务、错题、成长数据）。

`ui-shell.js` 只做**状态与壳**，不发起业务请求。

### 7.2 `frontend/kid-lang.js`

```js
window.KidLang = {
  statusOf(mastery),                 // -> {key, icon, label, tone}
  statusLabel(mastery),              // -> "🌳 已经掌握"
  forgettingText(count),             // -> "🌱 今天有 3 个知识需要照顾。"
  noReviewText(),                    // -> "🌳 今天没有知识需要复习。"
  noWrongText(),                     // -> "🎉 暂时没有需要攻克的错题！"
  upgradeText(from, to, name),       // -> "🌿 → 🌳　这个知识记得更牢啦！"
  wrongFeedback(round),              // -> 分级帮助标题/按钮文案
  encourage(seed)                    // 菲比固定鼓励语，非随机赌博式奖励
}
```

### 7.3 `frontend/ui-components.js`

```js
window.UIComponents = {
  progressBar({value, max, label, tone}),   // 图形 + 文字，不只靠颜色
  emptyState({icon, title, hint, action}),  // 空状态
  loadingState({text}),                     // 默认「菲比正在准备一道适合你的题……」
  errorState({title, retryLabel, onRetry}), // 「菲比刚刚没拿到题目，我们再试一次。」+「再试一次」
  hintPanel({level, title, body, onRetry}), // 逐级帮助
  questionCard({subject, knowledge, index, total, question, onSpeak}),
  answerOption({text, index, state}),       // 整块可点，state: idle|selected|right|wrong
  taskCard({title, subtitle, minutes, done}),
  dailyPlanCard({minutes, taskCount, tasks, onStart}),
  knowledgeStatus({mastery, compact}),
  knowledgeMap({domains}),                  // 地图/森林/山谷/城堡 探索式
  growthSummary({days, newMastered, wrongFixed, consolidated}),
  wrongQuestionCard({title, status, onOpen}),
  bottomNavigation({activeTab, items}),
  completionCard({items, onGrowth, onHome})
}
```

无框架、无虚拟 DOM：每个函数返回 HTML 字符串或挂载到指定 DOM，用事件委托绑定交互。所有文本经 `esc()` 转义。

### 7.4 统一前端状态（用户 §34）

`ui-shell.js` 持有并暴露：`currentStudent` / `currentGrade` / `ageMode` / `uiSettings`。
页面级 `dailyPlan` / `currentTask` / `currentQuestion` / `learningProgress` 由各业务页持有（生命周期本来就是单页），但**必须**订阅 `UIShell.onStudentChange` 以便切换学生时重取。

**禁止**再新增第 15 个 `currentStudentId()` 私有实现；存量各页的私有实现改为委托 `UIShell.getStudentId()`（保留原函数名以免破坏导出断言）。

---

## 8. 页面设计（14 项）

### 8.1 今日首页 `today.html`（改造）

```
[顶部] 头像 · 名字 · 年级 · 切换学习者按钮
[菲比问候] 「今天我们用 15 分钟完成 3 个小任务。」
[核心] 今日学习卡
      数学 · 应用题强化 · 6分钟
      英语 · 单词复习   · 4分钟
      错题挑战 · 2题    · 5分钟
[Primary] ▶ 开始今天的学习          ← 全局最大、品牌主色
[次要] 今日完成度 · 需要复习数量（图形化，不给算法数字）
```

禁止出现：复杂能力数据、遗忘概率、大量统计表。
数据来源：`GET /api/tasks/today/{sid}`、`GET /api/learning/plan/{sid}`（现有接口）。

### 8.2 学习/答题页（`index.html` + `today.html` 练习区改造）

最安静的页面：

```
顶部：数学 · 应用题                右上：3 / 8
中间：题目（20-28px，一屏一题）
下方：作答区域
底部：🔊 读题   💡 提示
主按钮：我做好了
```

**禁止同时出现**：金币、商城、排行榜、成就墙、宠物升级、活动 Banner、大量动画。

**一屏一题**：禁止一页多题；完成后自然进入下一题。

**题型 UI（用户 §12）**
| 题型 | 交互 |
|---|---|
| 选择题 | **整张选项卡片可点击**，不是只能点单选圆点 |
| 填空 | 输入区足够大 |
| 数学 | 尽量用自定义数字键盘 |
| 排序 | 卡片可拖动 |
| 低年级英语 | 字母块 |
| 高年级 | 允许键盘输入 |

原则：不让操作本身比题目更难。

**读题（§13）**：每题旁提供 🔊 读题，1-2 年级默认显眼但**不得比答题按钮更抢眼**。读题失败不得影响学习（静默降级 + 一行轻提示）。

### 8.3 答对反馈（§14）

- 普通答对：`✓ 对啦`，不每道题全屏烟花。
- 连续答对：`🔥 连续 3 题正确`。
- 只有知识点升级才允许更明显动画（1-2s）：
  `🌳 升级！` `「两位数乘法」` `🌿 基本会了 → 🌳 已经掌握`

### 8.4 答错/提示状态（§15）

- 禁止大面积 `❌ 错误！`，禁止强烈震动。
- 呈现：`🤔 这里再想一下` + 小提示 + 按钮 `我再试试`。
- 再次错误逐级增加帮助（见 §5.3）。
- 语调：菲比在帮助我，不是系统在处罚我。

### 8.5 今日完成页 `daily.html`（改造，§21/§22）

```
🎉 今天完成啦！
今天你：
🌱 学会 1 个新知识
🌳 巩固 3 个知识
⚔️ 攻克 2 道错题
⏱ 学习 15 分钟
今天可以休息啦！
[Primary] 查看我的成长      [Secondary] 返回首页
```

**禁止**把「继续再做 10 题」设为主按钮。成长反馈优先用「学会了什么」，而非「做了多少题」。

### 8.6 成长首页 `growth.html`（新增，§17/§18）

回答「我最近变强了吗？」

```
本周学习：5 天
新掌握：4 个知识
攻克错题：8 道
巩固成功：12 个知识
↓
知识地图（见 8.7）
```

**不把做题总量作为主要成长指标。**

### 8.7 知识地图（成长页内 / `knowledge_map.html` 改造，§18）

```
数学世界
🏡 数与计算   🌲 乘法森林   ⛰ 应用题山谷   🏰 几何城堡
进入「乘法森林」：
🌳 乘法口诀   🌳 两位数乘法   🌿 三位数乘法   🌱 乘法应用题
```

地图只回答三件事：学到哪里 / 哪里已掌握 / 下一步是什么。**不做复杂游戏地图。**

### 8.8 错题中心 `wrong_book.html`（改造，§19）

标题改为「我的挑战」，不叫「错误数据库」。

```
🔴 待攻克   🟡 训练中   🟢 已攻克
[错题卡] 只显示必要信息 → 点击进入既有错题康复流程
```

### 8.9 复习页面 `review.html`（改造，§20）

- 不显示「遗忘风险 76%」。
- 儿童表达：「🌱 今天有 3 个知识需要照顾。」
- 完成后：「🌿 → 🌳　这个知识记得更牢啦！」

### 8.10 我的页面 `profile.html`（新增，§23）

只保留：头像、昵称、年级、切换学生、声音设置、显示设置（字号）、减少动画设置。
**禁止出现**：DeepSeek API Key、数据库路径、算法参数、Debug 数据、高级管理配置。

### 8.11 用户切换（§24）

- 默认两个本地学生（朵朵 / 童童）。
- 入口清晰；点击后弹确认「确定切换到 XX 吗？」；确认后**刷新全部当前学生 UI 状态**。
- 避免误触：切换需要二次确认，`Esc`/点遮罩取消。

### 8.12–8.14 空 / Loading / Error 状态（§39/§40/§41）

| 状态 | 文案 |
|---|---|
| 无错题 | `🎉 暂时没有需要攻克的错题！` |
| 无复习任务 | `🌳 今天没有知识需要复习。` |
| Loading（DeepSeek 生成题目） | `菲比正在准备一道适合你的题……` + 简单轻动画；**不得空白**；等待久时保持明确状态 |
| Error（API 失败） | `菲比刚刚没拿到题目，我们再试一次。` + 按钮「再试一次」 |

**绝不显示 HTTP 502 等技术错误给儿童**；真实技术错误写入日志。

---

## 9. 验证契约变更清单（D2 的落地细节）

### 9.1 必须改写的前端断言（儿童化文案）

| 文件 | 位置 | 现状要求 | 改为 |
|---|---|---|---|
| `frontend/verify_web.js` | `:224-225` | 「艾宾浩斯复习」+「掌握度 18%」 | 复习徽标改儿童化：仅「🌿 正在学习」+ 照顾提示，不出现裸百分比 |
| `frontend/verify_adaptive_web.js` | `:317` | `renderWhy` 含「掌握度60，需要强化」 | `KidLang` 儿童化理由 |
| `frontend/verify_adaptive_web.js` | `:368` | `#adaptive-badge` 含「掌握度 60」 | 含五档儿童标签 |
| `frontend/verify_adaptive_web.js` | `:379-381` | `#result` 含「掌握度 58」 | 含 `🌳 已经掌握` / `🍀 基本会了` 儿童标签 |
| `frontend/verify_knowledge_web.js` | `:346` | 含「68.5」 | 儿童化汇总 |
| `frontend/verify_knowledge_web.js` | `:352` | 含 `>82<` | 儿童状态标签 |
| `frontend/verify_knowledge_web.js` | `:558/596` | 含「掌握度 45」「巩固表内乘法」 | 儿童化 |
| `frontend/verify_knowledge_web.js` | `:602-604` | 含「掌握度 88」「平均掌握度 68.5」「★★★☆☆」 | 儿童化 |

### 9.2 明确**不改**的断言

- `frontend/verify_memory_web.js:335-337`（已断言儿童端**不**显示「遗忘风险」「稳定性」）—— 与本设计一致，保留。
- `frontend/verify_memory_web.js:365-366`、`:441-442`（家长端 `memory_debug.html` 必须显示原始指标）—— 保留。
- `frontend/verify_phoebe3d_web.js` 全部立牌断言与 `style.css` 正则 —— 保留（D1）。
- `frontend/verify_web.js` 的朗读/转义/静音断言（`oralText`、`data-speaking`、`&lt;script&gt;`、`xiaozhi.voice`）—— 保留。

### 9.3 新增验证套件

| 新套件 | 覆盖 | 关键断言 |
|---|---|---|
| `frontend/verify_ui_shell.js` | `ui-shell.js`、`kid-lang.js`、`ui-components.js` | `ageModeOf` 1..6 全覆盖；`statusOf` 五档边界（29/30/54/55/74/75/89/90）；无数据降级；`esc()` 转义；`confirmSwitch` 确认流程；切换后订阅者被调用；空/Loading/Error 三态渲染文案；设置写入 `xiaozhi.uiSettings` |
| `frontend/verify_growth_profile_web.js` | `growth.html`+`growth.js`、`profile.html`+`profile.js` | 成长页不出现裸百分比指标；「我的」页不出现 API Key/DB 路径/算法参数；4 项导航渲染；分龄属性生效 |

两个新套件需：
1. 注册进 `backend/verify_all.py` 的 `SUITES`（前端套件，无端口，用 `node_exe()`）。
2. 登记进 `docs/MODULE_MAP.md` §1.1 与 §3。

> 注意：新增套件会改变 `verify_all.py` 的断言计数基线（现为 849）。这是预期变更，须在实施报告中说明新基线数字，并同步更新 `backup/baseline_verify_all.txt` 之外的任何"基线"引用说明（不覆盖用户既有基线文件，另存新档）。

### 9.4 文档同步（强制）

- `docs/MODULE_MAP.md`：§3 页面→脚本→验证表新增 3 个共享脚本、2 个新页面；§4 速查表新增行；§1.1 新增两套件。
- `ARCHITECTURE.md`（§44 强制）：更新 Product Name、前端架构、页面信息架构、公共 UI 组件、导航结构、`currentStudent` 状态管理、分龄 UI 规则、Design System、知识状态儿童化映射、主要页面与 API 关系、三条长期 UI 原则。
  - **不得**把未实现页面记录为已完成。
  - **不得**包含任何 API Key。

---

## 10. 实施顺序与写入范围

| 阶段 | 内容 | 写入范围 | 验证 |
|---|---|---|---|
| P0 | 基线 | （只读） | `python backend/verify_all.py` 记录基线；已快照 `backup/snapshots/ui_redesign_20261005_130224` |
| P1 | Design Tokens + 全站基础骨架 | `frontend/style.css` | `verify_phoebe3d_web.js`（CSS 正则契约）+ 全前端套件 |
| P2 | 共享层 | 新增 `ui-shell.js`、`kid-lang.js`、`ui-components.js`、`verify_ui_shell.js` | `node frontend/verify_ui_shell.js` |
| P3 | 导航壳接入现有页 | 全部 `frontend/*.html`（插入 3 个 script + 移除 `.link-row`） | 全前端套件 |
| P4 | 今日 + 学习 + 反馈 + 完成 | `today.html/js`、`index.html`、`app.js`、`daily.html/js` | `verify_adaptive_web.js`、`verify_web.js` |
| P5 | 成长 + 知识地图 + 错题 + 复习 | 新增 `growth.html/js`、`profile.html/js`、`knowledge_map.*`、`wrong_book.*`、`review.*` | `verify_knowledge_web.js`、`verify_memory_web.js`、`verify_growth_profile_web.js` |
| P6 | 空/Loading/Error + 家长端隔离复核 | `ui-components.js` + 各页 | 全前端套件 |
| P7 | 断言改写（§9.1） | 4 个 `verify_*_web.js` | 逐个套件 |
| P8 | 文档 | `MODULE_MAP.md`、`ARCHITECTURE.md`、交付 10 项文档 | `python backend/check_cards.py`；`verify_all.py` 全量 |

**串行执行**，不并发跑多套件（§13.8）。

---

## 11. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `style.css` 重写破坏 `.p3d-*` 紧凑正则契约 | 高 | `verify_phoebe3d_web.js` 失败 | §2.1 三条样式逐字保留；P1 后立即跑该套件 |
| 批量改 HTML 破坏元素 id / 脚本顺序 | 高 | 多个前端套件失败 | 改 id 前先 grep 全部 `verify_*` 引用；一页一改一验 |
| 改写断言时误删算法验证 | 中 | 掩盖真实回归 | 只改**文案/展示**断言，不动数值/接口/判分断言；逐个 diff 复核 |
| 共享脚本加载顺序与 phoebe 契约冲突 | 中 | 立牌/浮层失效 | 新脚本置于最前；每加一页即跑对应套件 |
| 零构建下共享代码膨胀 | 中 | 页面变慢 | 三个脚本总行数控制在 ~900 行内；不引入框架 |
| `data/*.json` 或 `backend/learning.db` 被误写 | 低 | 用户真实数据损坏 | 测试一律 `_verify_*.db`；不触碰 `data/` |

**回滚**：整目录快照已存 `backup/snapshots/ui_redesign_20261005_130224/`（frontend 70 文件 + `ARCHITECTURE.md` + `MODULE_MAP.md`）。回滚 = 覆盖还原该目录，无需 git。

---

## 12. 验收清单（用户 §42 十问）

| # | 问题 | 判定方式 |
|---|---|---|
| 1 | 首次打开 3 秒内知道哪里开始？ | 首页唯一 Primary Action 位于首屏、尺寸最大；启发式走查 + 截图证据 |
| 2 | 主要按钮足够明显？ | 每页恰好 1 个 Primary，颜色/尺寸/位置对比检查 |
| 3 | 学习时存在无关干扰？ | 学习页 DOM 中无金币/商城/排行/成就/宠物/活动节点；自动化断言 |
| 4 | 答错后仍愿意继续？ | 无鲜红、无震动、有「我再试试」+ 逐级帮助；文案走查 |
| 5 | 是否存在过多文字？ | JUNIOR 档文案 ≤ 阈值；逐页统计 |
| 6 | 低年级可不用理解复杂菜单？ | JUNIOR 档 4 tab 纯图标+短词；走查 |
| 7 | 完成后是否明显知道今天结束？ | 完成页有明确结束语 + 无「继续再做」主按钮 |
| 8 | 是否可以看到长期成长？ | 「成长」页展示周成长 + 知识地图 |
| 9 | 两学生易切换但不易误切？ | 切换需二次确认；`verify_ui_shell.js` 断言 |
| 10 | 平板是否好用？ | 720/1024/1280 断点走查 + 横竖屏截图 |

> **诚实声明**：本项目为本地单机应用，无真实儿童被试。§12 的结果属于**启发式评估 + 自动化契约断言**，不是受控用户研究。交付文档将如实标注方法与证据来源，不宣称做过用户测试。

---

## 13. 最终交付物（用户 §43）

1. `docs/UI_DESIGN.md` — UI 设计说明（视觉方向、原则、用色纪律）
2. `docs/UI_DESIGN_TOKENS.md` — Design Tokens 参考（与 `style.css` `:root` 一一对应）
3. `docs/UI_PAGE_STRUCTURE.md` — 页面结构
4. `docs/UI_COMPONENTS.md` — 组件结构（3 个共享脚本的 API 与用法）
5. `docs/UI_MIGRATION.md` — 新增页面 / 修改页面 / **前后对比说明**
6. `docs/UI_RESPONSIVE.md` — 响应式方案（含断点表）
7. `docs/UI_AGE_TIERS.md` — 分龄方案
8. `docs/UI_USABILITY_REVIEW.md` — 可用性评估结果（§12 十问 + 方法诚实标注 + 自动化证据）
9. `ARCHITECTURE.md` — 强制更新（§44）
10. `docs/MODULE_MAP.md` — 页面/脚本/验证登记同步

---

## 14. 自审记录

- 占位符扫描：无 TBD / TODO 遗留。
- 内部一致性：§3 token 与 §7 组件、§8 页面用色口径一致；D1/D2/D3 与 §2 硬约束无冲突。
- 范围检查：单一实施计划可承载（8 个阶段，串行）。
- 歧义检查：`🍀` 图标替换已在 §0.1 显式标注并说明理由；断言改写边界在 §9.1/§9.2 两侧逐一列出，不留「视情况而定」。
