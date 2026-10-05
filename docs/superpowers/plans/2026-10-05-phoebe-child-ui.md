# 菲比同学 · 儿童端 UI/UX 重设计 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把《菲比同学》儿童端从「每页各写一套样式的桌面网页」重构为带 Design System、4 项一级导航、统一 `currentStudent` 状态、分龄与响应式的儿童学习界面。

**Architecture:** 纯前端重构，零构建约束下通过**新增 3 个普通 `<script>` 共享脚本**（`ui-shell.js` / `kid-lang.js` / `ui-components.js`）承载状态、儿童化语言与公共组件；`frontend/style.css` 顶部建立 `:root` Design Tokens 并全量替换硬编码值；新增 2 个页面（`growth.html`、`profile.html`）。后端与算法**完全不改**，UI 只消费既有接口。

**Tech Stack:** 原生 HTML/CSS/JS（无框架、无 bundler、无 ES module）、Node 24（捆绑版）跑 `frontend/verify_*.js` DOM 打桩测试、Python 3.13 跑 `backend/verify_all.py`。

**Spec:** `docs/superpowers/specs/2026-10-05-phoebe-child-ui-design.md`

## Global Constraints

- **零构建**：禁止 npm / bundler / CDN / ES module `import`·`export`。共享代码只能靠新增普通 `<script>` 标签顺序加载（`AI_RULES.md` §13.7）。
- **一页 = 同名 `.html` + 同名 `.js`**（同上）。
- **脚本加载顺序**：`ui-shell.js` → `kid-lang.js` → `ui-components.js` → `phoebe.js` → `phoebe3d.js` → 业务 js。
- **禁止引入新测试框架**（无 pytest）；只用 `python backend/verify_all.py [套件…]` 或 `node frontend/verify_*.js`。
- **禁止并发跑多套件**；套件端口固定，占用即故意失败（§13.8）。
- **禁止写 `backend/learning.db`**；测试只用 `_verify_*.db`。
- **不改后端**：能力诊断/自适应/掌握度/间隔复习/错题康复/DeepSeek 调用/数据库结构一律不动。已发布 API 只消费，不新增语义。
- **前端禁止碰判分**：不得保存或推断答案，判分只能走后端（§13.3）。
- **localStorage key 字面值不得更改**：`xiaozhi.student`、`xiaozhi.voice`、`xiaozhi.voiceRate`、`xiaozhi.phoebeVoice`；新增 `xiaozhi.uiSettings`。
- **`frontend/style.css` 的 `.p3d-*` 契约**（`verify_phoebe3d_web.js:543` 先做 `compactCss = css.replace(/\s+/g, "")` 再匹配，故源文件可多行书写，但**压缩空白后必须命中**）：
  1. `/`\.p3d-stage\.p3d-floating\{position:fixed;left:/` 命中 —— 且 `!/`\.p3d-stage\.p3d-floating\{[^}]*right:/`（该选择器的**每一条**规则都不得含 `right:`）
  2. `/max-width:1280px\)\{\.p3d-stage\.p3d-floating\{left:10px;width:250px/`
  3. `/max-width:1060px\)\{\.p3d-stage\.p3d-floating\{width:200px/`
- **立牌实测几何（决定所有让位尺寸）**：`position:fixed;left:18px;top:50%`，默认宽 322px；`≤1280px` → `left:10px;width:250px`；`≤1060px` → `width:200px`；**`≤900px` → `display:none`**。因此桌面侧边栏**必须放右侧**（或 ≥1024px 不使用侧边栏），否则与立牌在同一水平区间重叠。
- **儿童端禁止出现**：`掌握度 76.8` / `稳定性 5.6` / `遗忘风险 72%` / `HTTP 502` / DeepSeek API Key / 数据库路径 / 算法参数 / Debug 数据。
- **颜色纪律**：答错用 `--color-attention`（柔和橙）不使用 `--color-error`；状态一律「图标+文字+颜色」三重表达。
- **每页最多 1 个 Primary Action**；页面最多 3 层（背景/卡片/内容）。
- **无 git**：本计划用 `backup/` 目录快照代替 commit。

## Review Focus

以下 5 类输入/失败模式 spec 隐含但未被单个任务的测试覆盖，最可能伤到真实使用者，各任务须针对它们补测试：

1. **立牌与侧边栏空间冲突** — `.p3d-stage.p3d-floating` 实测固定在**左侧**（`left:18px`，宽 322px；`≤1280px` 时 `left:10px;width:250px`；`≤1060px` 时 `width:200px`；`≤900px` 时 `display:none`），而契约禁止该规则使用 `right:`。因此**桌面侧边栏必须放右侧**，内容区再按立牌断点分档让位（`body` 的 `padding-left` 358/276/226px）。期望：立牌不被侧边栏遮挡，也不遮挡题目。
2. **切换学生时正在答题** — 切换必须清空未提交的当前题与输入内容，绝不允许把学生 A 的作答写成学生 B 的记录。
3. **无 Web Speech API / 读题失败** — `speechSynthesis` 不存在或播放失败时，学习流程必须照常可完成，只给一行轻提示，不阻塞。
4. **`/students` 请求失败或返回空** — `ui-shell.js` 必须降级到缺省 `id=1` 与保守 `ageMode`，页面不白屏。
5. **`localStorage` 不可用（隐私模式）** — 读写必须静默降级、不抛异常（参照 `frontend/app.js:55-66` 既有先例）。

---

## File Structure

| 文件 | 职责 | 状态 |
|---|---|---|
| `frontend/style.css` | 唯一样式表：Design Tokens、基础元素、导航壳、分龄、响应式、`.p3d-*` 原契约 | 改造 |
| `frontend/ui-shell.js` | 学生状态 + 分龄 + 设置 + 导航壳；不发业务请求 | **新增** |
| `frontend/kid-lang.js` | 儿童化语言映射（五档状态、复习/错题/反馈文案） | **新增** |
| `frontend/ui-components.js` | 公共 UI 组件（进度条/空/Loading/Error/提示/题卡/选项…） | **新增** |
| `frontend/verify_ui_shell.js` | 覆盖上述 3 个共享脚本 | **新增** |
| `frontend/verify_growth_profile_web.js` | 覆盖 `growth.js` / `profile.js` | **新增** |
| `frontend/growth.html` + `growth.js` | 成长首页（本周成长 + 知识地图） | **新增** |
| `frontend/profile.html` + `profile.js` | 我的页面 | **新增** |
| `frontend/today.html` + `today.js` | 今日首页 + 练习区 | 改造 |
| `frontend/index.html` + `app.js` | 自由练习页 | 改造 |
| `frontend/daily.html` + `daily.js` | 今日完成页 | 改造 |
| `frontend/knowledge_map.html` + `.js` | 知识地图 | 改造 |
| `frontend/wrong_book.html` + `.js` | 我的挑战 | 改造 |
| `frontend/review.html` + `review.js` | 知识浇水 | 改造 |
| `frontend/*.html`（其余） | 插入 3 个 script、移除 `.link-row` | 改造 |
| `backend/verify_all.py` | `SUITES` 注册 2 个新前端套件 | 改造 |
| `docs/MODULE_MAP.md`、`ARCHITECTURE.md`、`docs/UI_*.md` | 文档同步与交付 | 改造/新增 |

---

## Task 1: Design Tokens 落地（`frontend/style.css`）

**Files:**
- Modify: `frontend/style.css`（1670 行，顶部新增 `:root`，全文替换硬编码色值）
- Test: `frontend/verify_phoebe3d_web.js`（CSS 正则契约）

**Interfaces:**
- Produces: `:root` 上的全部 token 变量名（供 Task 2-14 的 CSS 使用）——完整清单见 spec §3，必须逐字一致：`--color-primary`、`--color-primary-soft`、`--color-primary-hover`、`--color-primary-strong`、`--color-accent`、`--color-accent-soft`、`--color-success`、`--color-success-soft`、`--color-warning`、`--color-warning-soft`、`--color-attention`、`--color-attention-soft`、`--color-error`、`--color-error-soft`、`--color-background`、`--color-surface`、`--color-surface-soft`、`--color-border`、`--color-border-strong`、`--color-text-primary`、`--color-text-secondary`、`--color-text-muted`、`--color-text-on-primary`、`--radius-small|medium|large|pill`、`--space-xs|sm|md|lg|xl|2xl`、`--shadow-sm|md|lg`、`--font-family`、`--text-body|label|title|question`、`--leading-base|loose`、`--motion-fast|base|slow|celebrate`、`--ease-out`、`--tap-min`、`--tap-junior`。

- [ ] **Step 1: 记录改动前的 CSS 契约基线**

Run: `python backend\verify_all.py phoebe3dweb`
Expected: 全部通过，记下断言总数（改动后必须一致）。

- [ ] **Step 2: 在 `frontend/style.css` 第 1 行之前插入 `:root` 块**

按 spec §3.1–3.5 逐字写入所有 token。`--font-family` 值为 `"PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,-apple-system,sans-serif`。颜色值逐字照抄 spec §3.1 表格，不得自行调色。

- [ ] **Step 3: 把 `body` 与通用元素的硬编码值换成 token 引用**

`body{font-family:var(--font-family);background:var(--color-background);color:var(--color-text-primary)}`；`.card{background:var(--color-surface);box-shadow:var(--shadow-md);border-radius:var(--radius-large)}`；`button` 的 `border-radius:var(--radius-small)`；`#main-btn{background:var(--color-primary);border-color:var(--color-primary);color:var(--color-text-on-primary)}`；`.mode-btn.active{background:var(--color-primary)}`。
**保持 `.card` 的 `width:620px;max-width:92vw;margin:40px auto;padding:28px` 不变**；圆角由原 20px 统一为 `--radius-large`(22px)。

- [ ] **Step 4: 复核 `.p3d-*` 三条契约未被改动**

Run: `$css=(Get-Content -Raw frontend\style.css) -replace '\s+',''; "1280: " + [regex]::IsMatch($css,'max-width:1280px\)\{\.p3d-stage\.p3d-floating\{left:10px;width:250px'); "1060: " + [regex]::IsMatch($css,'max-width:1060px\)\{\.p3d-stage\.p3d-floating\{width:200px'); "left-fixed: " + [regex]::IsMatch($css,'\.p3d-stage\.p3d-floating\{position:fixed;left:'); "has-right: " + [regex]::IsMatch($css,'\.p3d-stage\.p3d-floating\{[^}]*right:')`
（**必须先用 `-replace '\s+',''` 压缩空白** —— 直接对原始 CSS 测紧凑正则会全部误报 False。）
Expected: `true true true`

- [ ] **Step 5: 跑验证**

Run: `python backend\verify_all.py phoebe3dweb web knowweb memweb`
Expected: 全部通过，断言数与 Step 1 一致。

- [ ] **Step 6: 快照**

```powershell
$d="backup\snapshots\ui_T1_$(Get-Date -Format yyyyMMdd_HHmmss)"; New-Item -ItemType Directory -Force $d|Out-Null; Copy-Item frontend\style.css $d
```

---

## Task 2: 基础骨架、导航壳样式、分龄与响应式（`frontend/style.css`）

**Files:**
- Modify: `frontend/style.css`（追加样式，不改动已有规则）
- Test: `frontend/verify_phoebe3d_web.js`

**Interfaces:**
- Consumes: Task 1 的全部 token。
- Produces: CSS 类名契约，供 Task 4/6/7-13 的 HTML 使用：
  `.ph-app`（页面网格）、`.ph-app-main`（内容区）、`.ph-nav`、`.ph-nav--bottom`、`.ph-nav--side`、`.ph-nav-item`、`.ph-nav-item.is-active`、`.ph-topbar`、`.ph-avatar`、`.ph-greeting`、`.ph-card`、`.ph-card--task`、`.ph-btn`、`.ph-btn--primary`、`.ph-btn--secondary`、`.ph-btn--ghost`、`.ph-btn--speak`、`.ph-progress`、`.ph-progress-fill`、`.ph-status-dot`、`.ph-option`、`.ph-option.is-right`、`.ph-option.is-wrong`、`.ph-blank`、`.ph-state`（空/加载/错误共用容器）、`.ph-tile`（知识地图区块）、`.ph-chip`。

- [ ] **Step 1: 追加布局骨架**

```
.ph-app{display:grid;min-height:100dvh;background:var(--color-background)}
.ph-app-main{width:100%;max-width:720px;margin:0 auto;padding:var(--space-lg) var(--space-lg) calc(var(--tap-min) + var(--space-2xl))}
.ph-nav--bottom{position:fixed;left:0;right:0;bottom:0;display:grid;grid-template-columns:repeat(4,1fr);background:var(--color-surface);border-top:var(--border-hairline);z-index:20}
.ph-nav-item{min-height:var(--tap-min);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;color:var(--color-text-secondary)}
.ph-nav-item.is-active{color:var(--color-primary);font-weight:600}
```
`.ph-nav--side` 默认 `display:none`。

- [ ] **Step 2: 追加响应式断点（必须放在文件**末尾**，避免被后置规则覆盖）**

```
/* 桌面/平板横屏：侧边栏放**右侧**，立牌固定在左侧，二者互不遮挡 */
@media (min-width:1024px){
.ph-nav--side{display:flex;flex-direction:column;gap:var(--space-sm);position:fixed;right:0;top:0;bottom:0;width:232px;padding:var(--space-lg);border-left:var(--border-hairline);z-index:20}
.ph-nav--bottom{display:none}
body{padding-right:232px}
}
/* 给固定立牌让位。宽 <900px 时立牌 display:none，无需让位 */
@media (min-width:1281px){ body{padding-left:358px} }   /* 立牌 322px @ left:18 → 占 18-340 */
@media (min-width:1024px) and (max-width:1280px){ body{padding-left:276px} }  /* 立牌 250px @ left:10 → 占 10-260 */
@media (min-width:901px) and (max-width:1023px){ body{padding-left:226px} }   /* 立牌 200px @ left:10 → 占 10-210 */
```
> 说明：`.p3d-stage.p3d-floating` 在 ≤1280px 时 `left:10px;width:250px`、≤1060px 时 `width:200px`。上面用 `padding-left`/`margin-left` 让内容避开立牌，**不改动立牌自身规则**。

- [ ] **Step 3: 追加组件基础样式**

`.ph-btn` 基线：`min-height:var(--tap-min);padding:var(--space-md) var(--space-xl);border-radius:var(--radius-small);font-size:var(--text-body);border:var(--border-hairline);background:var(--color-surface);cursor:pointer`。
`.ph-btn--primary{min-height:56px;font-size:19px;font-weight:600;background:var(--color-primary);color:var(--color-text-on-primary);border-color:var(--color-primary);width:100%}`。
`.ph-card{border-radius:var(--radius-large);background:var(--color-surface);box-shadow:var(--shadow-sm);padding:var(--space-lg)}`（**卡片内不得再嵌 `.ph-card`**）。
`.ph-option{display:block;width:100%;text-align:left;min-height:var(--tap-min);padding:var(--space-lg);border-radius:var(--radius-medium);border:var(--border-hairline);background:var(--color-surface);font-size:var(--text-question)}`。
`.ph-option.is-right{background:var(--color-success-soft);border-color:var(--color-success)}`。
`.ph-option.is-wrong{background:var(--color-attention-soft);border-color:var(--color-attention)}` —— **注意不是红色**。

- [ ] **Step 4: 追加分龄规则（文件末尾）**

```
html[data-age-mode="junior"]{--text-body:19px;--text-question:26px}
html[data-age-mode="junior"] .ph-btn--primary{min-height:var(--tap-junior)}
html[data-age-mode="junior"] .ph-option{min-height:64px}
html[data-age-mode="junior"] .ph-num{display:none}      /* 低年级隐藏裸百分比 */
```
并追加 `@media (prefers-reduced-motion: reduce)` 与 `html[data-reduce-motion="on"]` 两条规则，把 `*{animation-duration:.001ms!important;transition-duration:.001ms!important}`。

- [ ] **Step 5: 验证立牌契约与全套件**

Run: `python backend\verify_all.py phoebe3dweb web knowweb memweb adaptweb`
Expected: 全部通过。

- [ ] **Step 6: 快照**

同 Task 1 Step 6，目录名改 `ui_T2_`。

---

## Task 3: `frontend/kid-lang.js`（儿童化语言，唯一实现）

**Files:**
- Create: `frontend/kid-lang.js`
- Create: `frontend/verify_ui_shell.js`（本任务先建骨架与 kid-lang 断言）

**Interfaces:**
- Produces: `window.KidLang`，方法签名与返回结构：
  - `statusOf(mastery) -> {key:"sprout"|"learning"|"basic"|"mastered"|"solid", icon:string, label:string, tone:"neutral"|"warning"|"success-soft"|"success"|"solid"}`
  - `statusLabel(mastery) -> string`（`icon + " " + label`）
  - `forgettingText(count) -> string` → `"🌱 今天有 3 个知识需要照顾。"`；`count<=0` 时返回 `noReviewText()`
  - `noReviewText() -> string` → `"🌳 今天没有知识需要复习。"`
  - `noWrongText() -> string` → `"🎉 暂时没有需要攻克的错题！"`
  - `upgradeText(from, to, name) -> string` → `"🌿 → 🌳　这个知识记得更牢啦！"`（`from`/`to` 为 `statusOf` 返回对象）
  - `wrongFeedback(round) -> {title:string, level:string, retryLabel:"我再试试"}`，`round` 为第几次答错（1..4，>4 按 4 处理），`level` 依次为 `"方向提示"|"关键条件"|"步骤提示"|"完整讲解"`，`title` 恒为 `"🤔 这里再想一下"`
  - `encourage(seed) -> string` —— 从**固定数组**按下标取，禁止 `Math.random()`

- [ ] **Step 1: 新建 `frontend/verify_ui_shell.js`，写入 kid-lang 的失败测试**

照抄现有套件风格（`frontend/verify_web.js` 的 `check(name, ok, extra)` + 末尾打印 `❌ 失败 N 项` 并以 `process.exitCode = 1` 收尾；`node frontend/verify_ui_shell.js` 可独立运行）。断言：

```js
check("ageModeOf 1-2 年级为 junior", ctx.UIShell.ageModeOf(1) === "junior" && ctx.UIShell.ageModeOf(2) === "junior");
check("ageModeOf 3-4 年级为 middle", ctx.UIShell.ageModeOf(3) === "middle" && ctx.UIShell.ageModeOf(4) === "middle");
check("ageModeOf 5-6 年级为 senior", ctx.UIShell.ageModeOf(5) === "senior" && ctx.UIShell.ageModeOf(6) === "senior");
check("掌握度 90 为记得很牢", K.statusOf(90).label === "记得很牢" && K.statusOf(90).icon === "⭐");
check("掌握度 89 为已经掌握", K.statusOf(89).label === "已经掌握" && K.statusOf(89).icon === "🌳");
check("掌握度 75 为已经掌握", K.statusOf(75).label === "已经掌握");
check("掌握度 74 为基本会了", K.statusOf(74).label === "基本会了" && K.statusOf(74).icon === "🍀");
check("掌握度 55 为基本会了", K.statusOf(55).label === "基本会了");
check("掌握度 54 为正在学习", K.statusOf(54).label === "正在学习" && K.statusOf(54).icon === "🌿");
check("掌握度 30 为正在学习", K.statusOf(30).label === "正在学习");
check("掌握度 29 为刚开始", K.statusOf(29).label === "刚开始" && K.statusOf(29).icon === "🌱");
check("无掌握度降级为还没开始学", K.statusOf(null).label === "还没开始学" && K.statusOf(undefined).label === "还没开始学");
check("复习提醒走儿童语言", K.forgettingText(3) === "🌱 今天有 3 个知识需要照顾。");
check("无复习任务走空状态文案", K.forgettingText(0) === "🌳 今天没有知识需要复习。");
check("无错题走空状态文案", K.noWrongText() === "🎉 暂时没有需要攻克的错题！");
check("升级文案带前后状态", K.upgradeText(K.statusOf(60), K.statusOf(80), "两位数乘法").includes("🌿 → 🌳") && K.upgradeText(K.statusOf(60), K.statusOf(80), "两位数乘法").includes("这个知识记得更牢啦！"));
check("答错第一级给方向提示", K.wrongFeedback(1).level === "方向提示" && K.wrongFeedback(1).title === "🤔 这里再想一下" && K.wrongFeedback(1).retryLabel === "我再试试");
check("答错逐级加帮助", K.wrongFeedback(2).level === "关键条件" && K.wrongFeedback(3).level === "步骤提示" && K.wrongFeedback(4).level === "完整讲解");
check("答错超过四级仍给完整讲解", K.wrongFeedback(9).level === "完整讲解");
check("鼓励语是固定表不是随机", K.encourage(0) === K.encourage(0) && K.encourage(0) !== K.encourage(1));
check("儿童语言不含裸算法指标", !/掌握度|稳定性|遗忘风险|Mastery|Stability/.test(JSON.stringify(K.statusOf(76)) + K.forgettingText(2) + K.upgradeText(K.statusOf(60), K.statusOf(80), "x")));
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node frontend\verify_ui_shell.js`
（无系统 node 时用捆绑版：`C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`）
Expected: FAIL —— 大量 `undefined` 断言失败。

- [ ] **Step 3: 实现 `frontend/kid-lang.js`**

用 `vm` 可加载的**普通脚本**（无 IIFE 包裹导致 `window` 不可达的问题；参照 `frontend/phoebe.js` 的写法：`(function (root) { ... root.KidLang = {...}; })(typeof window !== "undefined" ? window : this);`）。
在 `verify_ui_shell.js` 中按现有套件方式用 `vm.runInNewContext(code, sandbox)` 注入 `window` 并取回 `sandbox.window.KidLang`，同时把 `UIShell` 也挂到同一 sandbox。
阈值严格按 spec §5.1：`>=90 ⭐ 记得很牢`、`>=75 🌳 已经掌握`、`>=55 🍀 基本会了`、`>=30 🌿 正在学习`、`<30 🌱 刚开始`、非数字 `🌱 还没开始学`。

- [ ] **Step 4: 跑测试确认通过**

Run: `node frontend\verify_ui_shell.js`
Expected: kid-lang 项全部 PASS（`UIShell` 项因 Task 4 未做仍失败，属预期）。

---

## Task 4: `frontend/ui-shell.js`（学生状态 + 分龄 + 设置 + 导航壳）

**Files:**
- Create: `frontend/ui-shell.js`
- Modify: `frontend/verify_ui_shell.js`（补齐 UIShell 断言）

**Interfaces:**
- Consumes: Task 3 的 `window.KidLang`（不依赖，但同页共存）。
- Produces: `window.UIShell`：
  - `STUDENT_KEY = "xiaozhi.student"`、`SETTINGS_KEY = "xiaozhi.uiSettings"`
  - `ageModeOf(grade:number) -> "junior"|"middle"|"senior"`；非 1..6 的数字按就近收敛（≤0 或非数字 → `"junior"`，>6 → `"senior"`）
  - `applyAgeMode(grade)` → 设 `document.documentElement.dataset.ageMode`
  - `getStudentId() -> string`（默认 `"1"`）
  - `loadStudents() -> Promise<Array<{id,name,grade,grade_text}>>`（`GET <API>/students`，失败返回 `[]`）
  - `setStudentId(id)` → 写 localStorage + 调用全部订阅者
  - `onStudentChange(handler)` → 注册订阅者
  - `getSettings() -> {sound:boolean, reduceMotion:boolean, fontScale:number, focusMode:boolean}`（默认 `{sound:true, reduceMotion:false, fontScale:1, focusMode:false}`）
  - `setSettings(patch)` → 合并写 `xiaozhi.uiSettings` 并调 `applySettings()`
  - `applySettings()` → 设 `document.documentElement.dataset.reduceMotion`（`"on"|"off"`）、`data-focus-mode`、`data-font-scale`
  - `mountNav(activeTab: "today"|"growth"|"wrong"|"profile")` → 渲染 `.ph-nav--bottom` 与 `.ph-nav--side` 进 `document.body`（若已存在则更新 `is-active`）
  - `confirmSwitch(student: {id,name}) -> Promise<boolean>` → 渲染确认弹层（文案 `确定切换到${name}吗？`），确认 `resolve(true)`，取消/`Esc`/点遮罩 `resolve(false)`
  - `createStudentSwitcher(el)` → 绑定点击；点击学生 → `confirmSwitch` → 为真则 `setStudentId(id)`，为假则**不改变任何状态**

- [ ] **Step 1: 在 `verify_ui_shell.js` 追加失败测试**

```js
check("默认学生 id 为 1", sb.localStorage.getItem("xiaozhi.student") === null && S.getStudentId() === "1");
check("分龄属性写到 html 上", (S.applyAgeMode(4), doc.documentElement.dataset.ageMode === "middle"));
check("设置默认值", JSON.stringify(S.getSettings()) === JSON.stringify({sound:true,reduceMotion:false,fontScale:1,focusMode:false}));
check("设置写入本地存储", (S.setSettings({reduceMotion:true}), JSON.parse(sb.localStorage.getItem("xiaozhi.uiSettings")).reduceMotion === true));
check("减少动画写到 html 属性", doc.documentElement.dataset.reduceMotion === "on");
check("挂载四个一级导航项", (S.mountNav("today"), doc.querySelectorAll(".ph-nav-item").length === 8));  // 底部+侧栏各 4
check("当前页高亮", doc.querySelector(".ph-nav--bottom .is-active").getAttribute("data-tab") === "today");
check("切换学生需二次确认", /* 调 createStudentSwitcher 后模拟点击，未确认前 localStorage 不变且订阅者未被调用 */ true);
check("确认后才广播", /* 点确认后 setStudentId 生效且订阅者收到新 id */ true);
check("取消切换不改变学生", /* 点取消后 getStudentId() 仍是旧值 */ true);
check("学生列表请求失败返回空数组", /* fetch 抛错时 loadStudents() resolve [] */ true);
check("无 localStorage 时不抛异常", /* sandbox 不给 localStorage，调用 getStudentId/setSettings 不抛 */ true);
check("无学生数据时分龄保守为 junior", S.ageModeOf(undefined) === "junior");
```
> 上面 4 个用注释占位的 `true` 必须在实现时替换为真实断言（模拟 DOM 事件或直接调用确认弹层返回的 Promise）。

- [ ] **Step 2: 跑测试确认失败**

Run: `node frontend\verify_ui_shell.js`
Expected: FAIL —— `UIShell` 未定义。

- [ ] **Step 3: 实现 `frontend/ui-shell.js`**

要点：
- `localStorage` 访问全部包在 `try/catch`，降级为内存变量（Review Focus 5），参照 `frontend/app.js:55-66`。
- `loadStudents()` 用 `fetch(API + "/students")`；`API` 沿用其他脚本的写法 `const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || "")) ? location.origin.replace(/\/app\/?$/, "") : "http://127.0.0.1:8000";` —— **照抄 `frontend/today.js:25-27` 的实际实现**，不要自创。
- `mountNav` 用 `innerHTML` 渲染固定 4 项：`{tab:"today",icon:"🏠",label:"今天",href:"today.html"}`、`{tab:"growth",icon:"🗺",label:"成长",href:"growth.html"}`、`{tab:"wrong",icon:"⚔️",label:"错题",href:"wrong_book.html"}`、`{tab:"profile",icon:"👤",label:"我的",href:"profile.html"}`。
- `confirmSwitch` 用 `position:fixed` 遮罩 `.ph-confirm`，含 `确定` / `再想想` 两个按钮；返回 Promise。
- 所有文案经 `esc()` 转义后插入。

- [ ] **Step 4: 跑测试确认通过**

Run: `node frontend\verify_ui_shell.js`
Expected: 全部 PASS。

---

## Task 5: `frontend/ui-components.js`（公共组件）

**Files:**
- Create: `frontend/ui-components.js`
- Modify: `frontend/verify_ui_shell.js`

**Interfaces:**
- Produces: `window.UIComponents`，全部返回 HTML 字符串，全部经 `esc()` 转义：
  - `esc(s) -> string`
  - `progressBar({value:number, max:number, label?:string, tone?:string}) -> string`，输出含 `.ph-progress` + `role="progressbar"` + `aria-valuenow`
  - `emptyState({icon:string, title:string, hint?:string}) -> string`
  - `loadingState({text?:string}) -> string`，默认文案 `"菲比正在准备一道适合你的题……"`
  - `errorState({title?:string, retryLabel?:string}) -> string`，默认 `"菲比刚刚没拿到题目，我们再试一次。"` + `"再试一次"`，含 `data-action="retry"`，**不含任何 HTTP 状态码**
  - `hintPanel({level:string, title:string, body:string, retryLabel:string}) -> string`，含 `data-action="retry"`
  - `questionCard({subject, knowledge, index, total, question, canSpeak}) -> string`，含 `data-speaking="0"`、读题按钮文案含 `"读题目"`、右上角 `index / total`
  - `answerOption({text:string, index:number, state:"idle"|"selected"|"right"|"wrong"}) -> string`，`<button class="ph-option" data-index="…">` 整块可点
  - `taskCard({title, subtitle, minutes, done}) -> string`
  - `dailyPlanCard({minutes, taskCount, tasks, greeting}) -> string`
  - `knowledgeStatus({mastery, compact}) -> string`，调用 `KidLang.statusOf`
  - `knowledgeMap({domains}) -> string`，渲染 `.ph-tile`
  - `growthSummary({days, newMastered, wrongFixed, consolidated}) -> string`
  - `wrongQuestionCard({title, status, statusKey}) -> string`，`statusKey ∈ "todo"|"training"|"cleared"`
  - `completionCard({items, primaryLabel}) -> string`

- [ ] **Step 1: 在 `verify_ui_shell.js` 追加失败测试**

```js
check("进度条不只靠颜色", C.progressBar({value:3,max:8,label:"3 / 8"}).includes('role="progressbar"') && C.progressBar({value:3,max:8}).includes("3 / 8"));
check("空状态不用 No data", C.emptyState({icon:"🎉",title:"暂时没有需要攻克的错题！"}).includes("🎉") && !/No data|no data/.test(C.emptyState({icon:"x",title:"y"})));
check("Loading 用菲比文案", C.loadingState({}).includes("菲比正在准备一道适合你的题"));
check("错误状态不含技术错误码", !/HTTP|502|500/.test(C.errorState({})) && C.errorState({}).includes("菲比刚刚没拿到题目，我们再试一次。") && C.errorState({}).includes("再试一次"));
check("提示面板带我再试试", C.hintPanel({level:"方向提示",title:"🤔 这里再想一下",body:"先看看单位",retryLabel:"我再试试"}).includes("我再试试"));
check("题卡含读题入口", C.questionCard({subject:"数学",knowledge:"应用题",index:3,total:8,question:"小明有 5 个苹果",canSpeak:true}).includes("读题目") && C.questionCard({subject:"数学",knowledge:"应用题",index:3,total:8,question:"x"}).includes('data-speaking="0"'));
check("题卡右上有进度", C.questionCard({subject:"数学",knowledge:"应用题",index:3,total:8,question:"x"}).includes("3 / 8"));
check("选项整块可点", C.answerOption({text:"8",index:1,state:"idle"}).includes("<button") && C.answerOption({text:"8",index:1,state:"idle"}).includes("ph-option"));
check("答错选项用柔和橙不用红", C.answerOption({text:"8",index:1,state:"wrong"}).includes("is-wrong"));
check("知识状态走儿童语言", C.knowledgeStatus({mastery:80}).includes("🌳") && C.knowledgeStatus({mastery:80}).includes("已经掌握"));
check("组件全部转义", C.esc("<script>") === "&lt;script&gt;" && C.questionCard({subject:"s",knowledge:"k",index:1,total:1,question:"<script>alert(1)</script>"}).indexOf("<script>") === -1);
check("成长摘要是学会什么不是做多少题", !/做了|共完成|总题量/.test(C.growthSummary({days:5,newMastered:4,wrongFixed:8,consolidated:12})) && C.growthSummary({days:5,newMastered:4,wrongFixed:8,consolidated:12}).includes("新掌握"));
check("完成卡主打查看成长", C.completionCard({items:["🌱 学会 1 个新知识"],primaryLabel:"查看我的成长"}).includes("查看我的成长"));
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node frontend\verify_ui_shell.js`
Expected: FAIL —— `UIComponents` 未定义。

- [ ] **Step 3: 实现 `frontend/ui-components.js`**

与 `kid-lang.js` 同款普通脚本包裹方式。所有 DOM 只输出字符串，不自行绑定事件；交互由调用页用事件委托处理（`data-action` / `data-index`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `node frontend\verify_ui_shell.js`
Expected: 全部 PASS。

- [ ] **Step 5: 注册新套件并全量验证**

在 `backend/verify_all.py` 的 `SUITES` 中新增一项（**照抄 `abilityweb` 项的结构**，`title` 用 `"前端共享UI层"`，`cmd` 为 `[node_exe(), os.path.join(FRONTEND, "verify_ui_shell.js")]`，套件键名 `uishell`）。

Run: `python backend\verify_all.py uishell`
Expected: 通过，输出断言计数。

- [ ] **Step 6: 快照**

目录名 `ui_T5_`，复制 `frontend/ui-shell.js`、`frontend/kid-lang.js`、`frontend/ui-components.js`、`frontend/verify_ui_shell.js`、`backend/verify_all.py`。

---

## Task 6: 导航壳接入全部现有页面

**Files:**
- Modify: 全部 `frontend/*.html`（`index.html`、`today.html`、`daily.html`、`habit.html`、`recall.html`、`recovery.html`、`review.html`、`memory_debug.html`、`ability.html`、`knowledge_map.html`、`wrong_book.html`、`study_advice.html`、`diagnostic*.html`）
- Test: 全部 `frontend/verify_*_web.js`

**Interfaces:**
- Consumes: `UIShell.mountNav(tab)`（Task 4）、`.ph-nav*` 类（Task 2）。
- Produces: 每页 `<body>` 内的 `<div class="ph-app-main">` 包裹原 `.card`（**不改动任何元素 id**）。

- [ ] **Step 1: 逐页插入 3 个 script 并移除 `.link-row`**

在原第一个 `<script src="phoebe.js">` **之前**插入：

```html
<script src="ui-shell.js"></script>
<script src="kid-lang.js"></script>
<script src="ui-components.js"></script>
```

删除底部 `.link-row`（class 含 `link-row` 的 `<div>` 及其全部 `<a>`）。
在业务 js 之后追加初始化调用：

```html
<script>
  if (window.UIShell) {
    UIShell.applySettings();
    UIShell.mountNav("today");   // 每页按 6.1 表填 today/growth/wrong/profile；非一级页留空串
    UIShell.loadStudents().then(function (list) {
      var me = list.filter(function (s) { return String(s.id) === UIShell.getStudentId(); })[0];
      if (me) UIShell.applyAgeMode(me.grade);
    });
  }
</script>
```

`memory_debug.html` 与 `diagnostic*.html` 不挂 `mountNav`（家长端/诊断页，不在儿童导航内），但仍可加载共享脚本。

- [ ] **Step 2: 逐页验证（一次一页）**

每改一页立刻跑该页对应的套件，例如改完 `review.html` 跑：
Run: `python backend\verify_all.py memweb`
Expected: 通过。
（`index.html`→`web`；`today.html`→`adaptweb` 与 `phoebe3dweb`；`ability.html`→`abilityweb`；`knowledge_map.html`/`wrong_book.html`/`study_advice.html`→`knowweb`；`diagnostic*.html`→`diagweb`；`recovery.html`→`recoveryweb`；`recall.html`/`daily.html`/`habit.html`→`python backend\verify_active_recall.py`。）

- [ ] **Step 3: 全量回归**

Run: `python backend\verify_all.py`
Expected: 全部套件通过；断言总数 = Task 1 基线 + Task 5 新增套件断言数。

- [ ] **Step 4: 快照 + 登记**

目录名 `ui_T6_`，复制整个 `frontend`。
在 `docs/MODULE_MAP.md` §3 的页面表中为每个页面补上 3 个前置脚本。

---

## Task 7: 今日首页（`today.html` + `today.js`）

**Files:**
- Modify: `frontend/today.html`、`frontend/today.js`（29080 B）
- Modify: `frontend/verify_adaptive_web.js`（断言改写，见 Step 5）
- Test: `frontend/verify_adaptive_web.js`

**Interfaces:**
- Consumes: `UIComponents.dailyPlanCard/taskCard/loadingState/errorState`、`UIShell.onStudentChange/getStudentId`、既有接口 `GET /api/tasks/today/{sid}`、`GET /api/learning/plan/{sid}`。
- Produces: 保留既有元素 id 不变：`student`、`refresh-btn`、`daily-plan`、`plan-voice`、`plan-preview`、`start-day-btn`、`plan-status`、`task-block`、`task-title`、`task-summary`、`task-mix`、`task-list`、`task-status`、`plan-head`、`plan-list`、`practice`、`question`、`adaptive-badge`、`options`、`blank-box`、`blank-input`、`blank-submit`、`result`、`feel-box`、`why`、`status`。导出函数名不变：`startToday()`、`init()`、`loadPlan()`、`renderWhy(logs)`。

- [ ] **Step 1: 改造 `today.html` 顶部区**

```
<div class="ph-topbar">
  <span class="ph-avatar">🐼</span>
  <span class="ph-name" id="who-name">…</span>
  <span class="ph-grade ph-num" id="who-grade">…</span>
  <button class="ph-btn ph-btn--ghost" id="switch-student">切换学习者</button>
</div>
<p class="ph-greeting" id="phoebe-greeting">今天我们用 15 分钟完成 3 个小任务。</p>
```
保留 `#student` select 作为隐藏的真实状态源（`class="ph-sr-only"`，不能删除，因为套件断言它存在）。
`#start-day-btn` 加 class `ph-btn ph-btn--primary`。

- [ ] **Step 2: 用组件渲染今日学习卡**

`#daily-plan` 内改用 `UIComponents.dailyPlanCard`；每张任务卡用 `UIComponents.taskCard`。禁止出现任何百分比/掌握度数字；完成度用 `UIComponents.progressBar`。

- [ ] **Step 3: 加载/错误状态接入**

`loadPlan()` 请求期间把 `#plan-status` 渲染为 `UIComponents.loadingState({})`；失败渲染 `UIComponents.errorState({})` 并把「再试一次」按钮委托到 `loadPlan()`。**不得**把 `err.message` 写进儿童可见区域（写入 `console.error`）。

- [ ] **Step 4: 订阅学生切换**

`init()` 中调用 `UIShell.onStudentChange(function () { resetPractice(); loadPlan(); })`，`resetPractice()` 清空 `#practice` 当前题、`#blank-input` 内容、`#options`、`#result`、`#adaptive-badge`（Review Focus 2）。

- [ ] **Step 5: 改写儿童文案断言**

按 spec §9.1 修改 `frontend/verify_adaptive_web.js`：
- `:317` 断言 `renderWhy(LOGS)` 含「掌握度60，需要强化」→ 改为含 `KidLang.statusOf(60).label`（即「基本会了」）且**不含** `掌握度`。
- `:368` 断言 `#adaptive-badge` 含「掌握度 60」→ 改为含 `🌿/🍀` 图标 + 对应 label 且不含 `掌握度`。
- `:379-381` 断言 `#result` 含「掌握度 58」→ 改为含 `KidLang.statusOf(58).label`（「基本会了」）且不含 `掌握度`。

- [ ] **Step 6: 跑验证**

Run: `python backend\verify_all.py adaptweb phoebe3dweb`
Expected: 全部通过。

- [ ] **Step 7: 快照**

目录名 `ui_T7_`，复制 `frontend/today.html`、`frontend/today.js`、`frontend/verify_adaptive_web.js`。

---

## Task 8: 学习/答题页（`index.html` + `app.js`）

**Files:**
- Modify: `frontend/index.html`、`frontend/app.js`
- Modify: `frontend/verify_web.js`（仅在 Step 5 的断言改写范围内）
- Test: `frontend/verify_web.js`

**Interfaces:**
- Consumes: `UIComponents.questionCard/answerOption/progressBar/hintPanel/loadingState/errorState`。
- Produces: 保留 `frontend/verify_web.js` 断言的**全部导出符号与元素 id**：`speech`、`oralText`、`speakQuestion`、`speakAnalysis`、`renderQuestion`、`renderResult`、`resetBoard`、`onVoiceToggle`、`current`、`progress`；id `student,subject,knowledge,mode-choice,mode-blank,main-btn,question,options,blank-box,blank-input,feedback,progress,review-panel,voice-enabled,voice-rate,voice-status`。

- [ ] **Step 1: 改造 `index.html` 的题区结构**

`#question` 外层用 `UIComponents.questionCard` 生成的结构（顶部 `数学 · 应用题`、右上 `3 / 8`、读题按钮文案含「读题目」）。**`#question` 元素自身与 `data-speaking` 属性必须保留**（套件断言 `data-speaking="0"`）。
`#options` 内每个选项改用 `UIComponents.answerOption`，**整个按钮可点**（现状已是 `<button class="option">`，只需补 `.ph-option` 类与样式，确保点击区域为整块）。
`#blank-box` 内输入区加 `.ph-blank` 保证足够大（`min-height:var(--tap-min)`、`font-size:var(--text-question)`）。
`#main-btn` 文案由「提交答案」类改为 **「我做好了」**（注意 `verify_web.js` 若无该文案断言则安全）。

- [ ] **Step 2: 加入「一屏一题」纪律**

确认 `#options` 与 `#blank-box` 一次只渲染当前题的作答区；不得同时铺开多题。若发现任何批量渲染路径，收敛为单题渲染。

- [ ] **Step 3: 读题失败静默降级（Review Focus 3）**

在 `speakQuestion`/`speakAnalysis` 内：

```js
try {
  if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") {
    setVoiceStatus("这台设备暂时读不了题，先自己看看～");
    return;
  }
  …
} catch (e) {
  console.error("[voice]", e);
  setVoiceStatus("这台设备暂时读不了题，先自己看看～");
}
```
`#voice-status` 保留原 id。**读题失败绝不能阻止答题。**

- [ ] **Step 4: 接入 Loading / Error**

题目生成等待期在 `#question` 位置渲染 `UIComponents.loadingState({})`；请求失败渲染 `UIComponents.errorState({})`，重试按钮重新触发同一请求函数。技术错误只进 `console.error`。

- [ ] **Step 5: 改写儿童文案断言（spec §9.1 第 1 行）**

`frontend/verify_web.js:224-225`：复习徽标断言由「艾宾浩斯复习」+「掌握度 18%」改为儿童化 —— 断言徽标含 `KidLang.statusOf(18).label`（「刚开始」）且**不含** `掌握度`。
`frontend/verify_web.js:279`：保留「答错要马上巩固」或改为 `KidLang.wrongFeedback(1).title`（「🤔 这里再想一下」）——**二选一后必须与 `app.js` 实际输出一致**。
其余断言（`oralText`、`data-speaking`、`&lt;script&gt;`、`xiaozhi.voice`、`speechSynthesis.cancel()`、复习面板超时文案）**一律不动**。

- [ ] **Step 6: 跑验证**

Run: `python backend\verify_all.py web`
Expected: 全部通过。

- [ ] **Step 7: 快照**

目录名 `ui_T8_`。

---

## Task 9: 答对反馈 / 答错与逐级帮助

**Files:**
- Modify: `frontend/app.js`、`frontend/today.js`（`renderResult` 与练习区判分渲染）
- Test: `frontend/verify_web.js`、`frontend/verify_adaptive_web.js`

**Interfaces:**
- Consumes: `KidLang.wrongFeedback(round)`、`UIComponents.hintPanel`、既有 `phoebe.js` 庆祝浮层（不改其 API）。
- Produces: 页面级 `wrongRound`（每题重置为 0）与 `renderFeedback(correct, payload)`。

- [ ] **Step 1: 实现答对反馈分级**

- 普通答对：`✓ 对啦`（**不触发全屏烟花**）。
- 连续答对第 3 题起：追加 `🔥 连续 3 题正确`。用一个 `streak` 计数器，答错清零。
- 仅在知识点升级时调用 `phoebe.js` 的更明显动画（1-2s），文案用 `KidLang.upgradeText(from, to, name)`。

- [ ] **Step 2: 实现答错反馈（禁止鲜红）**

`renderFeedback(false, …)` 输出 `KidLang.wrongFeedback(wrongRound).title`（`🤔 这里再想一下`）+ 小提示，按钮文案「我再试试」。**不得**输出 `❌ 错误！`，**不得**触发 `navigator.vibrate`。

- [ ] **Step 3: 实现逐级帮助**

每次再次答错把 `wrongRound` 加 1（上限 4），用 `UIComponents.hintPanel({level: KidLang.wrongFeedback(wrongRound).level, …})` 渲染。第 4 级给完整讲解。提示内容取自后端既有响应字段，**前端不生成答案**（§13.3）。

- [ ] **Step 4: 跑验证**

Run: `python backend\verify_all.py web adaptweb`
Expected: 通过。

- [ ] **Step 5: 快照**

目录名 `ui_T9_`。

---

## Task 10: 今日完成页（`daily.html` + `daily.js`）

**Files:**
- Modify: `frontend/daily.html`、`frontend/daily.js`
- Test: `python backend\verify_active_recall.py`（静态检查）

**Interfaces:**
- Consumes: `UIComponents.completionCard`、`KidLang`。
- Produces: 完成页视图；`查看我的成长` 链接到 `growth.html`，`返回首页` 链接到 `today.html`。

- [ ] **Step 1: 改造页面结构**

```
🎉 今天完成啦！
今天你：
🌱 学会 1 个新知识      ← 用 KidLang 图标
🌳 巩固 3 个知识
⚔️ 攻克 2 道错题
⏱ 学习 15 分钟
今天可以休息啦！
[Primary] 查看我的成长   [Secondary] 返回首页
```
数字全部来自既有接口（`GET /api/daily-summary/{sid}` 等），**不新增字段**。

- [ ] **Step 2: 删除「继续再做 N 题」类主按钮**

若存在任何 `继续` 类主按钮，降级为 Secondary 或删除。确认主按钮唯一且为「查看我的成长」。

- [ ] **Step 3: 成长指标口径复核**

页面不得以「今天完成 42 题」作为主指标；主指标必须是「学会了什么」（新知识名 / 巩固的知识名）。

- [ ] **Step 4: 跑验证**

Run: `python backend\verify_active_recall.py`
Expected: 通过（该套件对 `daily.html` 做静态页面检查）。

- [ ] **Step 5: 快照**

目录名 `ui_T10_`。

---

## Task 11: 成长页与我的页（新增）

**Files:**
- Create: `frontend/growth.html`、`frontend/growth.js`
- Create: `frontend/profile.html`、`frontend/profile.js`
- Create: `frontend/verify_growth_profile_web.js`

**Interfaces:**
- Consumes: `UIComponents.growthSummary/knowledgeMap/knowledgeStatus`、`UIShell.loadStudents/getStudentId/confirmSwitch/setStudentId/getSettings/setSettings`。
- Produces: `window.GrowthPage = {renderSummary(data), renderMap(domains), init()}`、`window.ProfilePage = {renderProfile(student), renderSettings(settings), init()}`（导出名供测试注入）。

- [ ] **Step 1: 新建 `frontend/verify_growth_profile_web.js` 失败测试**

照抄 `frontend/verify_ability_web.js` 的 `vm` + DOM 打桩 + `fetch` mock 结构。断言：

```js
check("成长页出现四项周成长", out.some(t => t.includes("本周学习")) && out.some(t => t.includes("新掌握")) && out.some(t => t.includes("攻克错题")) && out.some(t => t.includes("巩固成功")));
check("成长页不出现裸算法指标", !/掌握度\s*\d|稳定性|遗忘风险\s*\d|Mastery|Stability/.test(allText));
check("成长页不做题量为主指标", !/完成\s*\d+\s*题/.test(allText));
check("成长页展示知识地图区块", allText.includes("数与计算") && allText.includes("乘法森林"));
check("我的页只保留儿童设置项", ["切换学生","声音","显示","减少动画"].every(k => allText.includes(k)));
check("我的页不含任何密钥或技术配置", !/API\s*Key|api_key|数据库|DATABASE|mastery_threshold|debug/i.test(allText));
check("我的页不出现 DeepSeek 字样", !/DeepSeek/i.test(allText));
check("切换学生需要确认", /* 点学生 → 弹确认 → 未确认前 UIShell.getStudentId() 不变 */ true);
check("四个导航项都指向真实页面", /* 读 ui-shell.js 的 NAV 常量，断言 4 个 href 文件均存在 */ true);
check("分龄属性影响成长页", /* applyAgeMode(1) 后 doc.documentElement.dataset.ageMode === "junior" */ true);
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node frontend\verify_growth_profile_web.js`
Expected: FAIL。

- [ ] **Step 3: 实现 `frontend/growth.html` + `frontend/growth.js`**

内容：`growthSummary` 四格 → 知识地图区块（`knowledgeMap`）→ 次级入口（学习建议 `study_advice.html`、习惯简报 `habit.html`、能力水平 `ability.html`）。
数据源只用既有接口：`GET /api/daily-summary/{sid}`、`GET /api/habit/profile/{sid}`、`GET /api/mastery/{sid}`。
**不显示任何裸百分比**；掌握状态一律 `UIComponents.knowledgeStatus`。不设 Primary 按钮（纯浏览页）。

- [ ] **Step 4: 实现 `frontend/profile.html` + `frontend/profile.js`**

只保留：头像、昵称、年级、切换学生、声音设置、显示设置（字号 `fontScale` 1/1.15/1.3）、减少动画设置。
**禁止**出现 API Key、数据库路径、算法参数、Debug 数据、高级管理配置。页面底部提供次级入口「自由练习」（`index.html`）。

- [ ] **Step 5: 注册套件**

在 `backend/verify_all.py` 的 `SUITES` 新增 `growthweb`（`title` = `"前端成长/我的页"`，`cmd` = `[node_exe(), os.path.join(FRONTEND, "verify_growth_profile_web.js")]`）。

Run: `python backend\verify_all.py growthweb`
Expected: 通过。

- [ ] **Step 6: 快照**

目录名 `ui_T11_`。

---

## Task 12: 知识地图 / 错题中心 / 复习页改造

**Files:**
- Modify: `frontend/knowledge_map.html`、`frontend/knowledge_map.js`
- Modify: `frontend/wrong_book.html`、`frontend/wrong_book.js`
- Modify: `frontend/review.html`、`frontend/review.js`
- Modify: `frontend/verify_knowledge_web.js`、`frontend/verify_memory_web.js`（仅 spec §9.1/§9.2 指定范围）
- Test: `frontend/verify_knowledge_web.js`、`frontend/verify_memory_web.js`

**Interfaces:**
- Consumes: `UIComponents.knowledgeMap/wrongQuestionCard/emptyState/knowledgeStatus`、`KidLang.noWrongText/noReviewText/forgettingText/upgradeText`。
- Produces: 保留 `knowledge_map.js`、`wrong_book.js`、`review.js` 的既有导出符号与元素 id。

- [ ] **Step 1: 知识地图改用探索式视觉**

领域层级：`🏡 数与计算`、`🌲 乘法森林`、`⛰ 应用题山谷`、`🏰 几何城堡`；进入领域显示知识点状态（`🍀`/`🌳`/`🌿`/`🌱`）。
只回答三件事：学到哪里 / 哪里已掌握 / 下一步是什么。**不做复杂游戏地图**（不加路径动画、不加角色移动）。

- [ ] **Step 2: 错题页更名「我的挑战」**

标题改为「我的挑战」。分组标签：`🔴 待攻克` / `🟡 训练中` / `🟢 已攻克`。每卡只用 `UIComponents.wrongQuestionCard`，只显示必要信息。点击进入既有 `recovery.html` 康复流程（沿用现有跳转方式）。空列表用 `UIComponents.emptyState({icon:"🎉", title: KidLang.noWrongText()})`。

- [ ] **Step 3: 复习页改儿童语言**

- 移除「遗忘风险 76%」类展示，改 `KidLang.forgettingText(n)`。
- 完成后显示 `KidLang.upgradeText(from, to, name)`。
- **保留** `verify_memory_web.js:335-337` 要求的行为（儿童端不出现「遗忘风险」「稳定性」）与家长端 `memory_debug.html` 的全部原始指标展示（`verify_memory_web.js:365-366`、`:441-442`）。

- [ ] **Step 4: 改写 `verify_knowledge_web.js` 的儿童文案断言（spec §9.1）**

- `:346` 含「68.5」→ 改为含 `KidLang` 汇总文案（不含裸百分比）。
- `:352` 含 `>82<` → 改为含 `🌳` 或对应 label。
- `:558/:596` 含「掌握度 45」「巩固表内乘法」→ 前者改儿童标签，后者（知识点名）保留。
- `:602-604` 含「掌握度 88」「平均掌握度 68.5」「★★★☆☆」→ 前三项改儿童标签；星级若为儿童可见的鼓励性展示可保留。

- [ ] **Step 5: 跑验证**

Run: `python backend\verify_all.py knowweb memweb`
Expected: 通过。

- [ ] **Step 6: 快照**

目录名 `ui_T12_`。

---

## Task 13: 空 / Loading / Error 状态收口 + 家长端隔离复核

**Files:**
- Modify: `frontend/ui-components.js`（收口）、各业务页
- Modify: `frontend/verify_ui_shell.js`
- Test: 全部前端套件

**Interfaces:**
- Consumes: Task 5 组件。
- Produces: 全站统一三态；`docs/UI_USABILITY_REVIEW.md` 的证据来源。

- [ ] **Step 1: 逐页检查三态覆盖**

对 `today`、`index`、`growth`、`wrong_book`、`review` 五页，确认：请求中→ `loadingState`，失败→ `errorState` + 可重试，空数据→ 对应 `emptyState`（错题 `🎉 暂时没有需要攻克的错题！`、复习 `🌳 今天没有知识需要复习。`）。补齐缺失项。

- [ ] **Step 2: 技术错误不外泄复核**

全站 grep 确认儿童可见区域不出现 `HTTP`、状态码、`err.message`、堆栈：

Run: `python -c "import re,pathlib;bad=[];[bad.append((p.name,i+1,l.strip())) for p in pathlib.Path('frontend').glob('*.js') if not p.name.startswith('verify_') for i,l in enumerate(p.read_text(encoding='utf-8').splitlines()) if re.search(r'(innerHTML|textContent)\s*=.*(err\.message|error\.message|HTTP\s*\d{3})', l)];print(bad)"`
Expected: `[]`（空列表）。

- [ ] **Step 3: 家长端隔离复核**

确认 `memory_debug.html` 与 `diagnostic*.html` 不出现儿童底部导航（未调 `mountNav`），且 `memory_debug.html` 仍展示原始指标。

Run: `python backend\verify_all.py memweb diagweb`
Expected: 通过。

- [ ] **Step 4: 全量验证**

Run: `python backend\verify_all.py`
Expected: 全部套件通过。

- [ ] **Step 5: 快照**

目录名 `ui_T13_`，并保存本次全量输出到 `backup/snapshots/ui_T13_verify_all.txt`。

---

## Task 14: 文档与交付

**Files:**
- Modify: `ARCHITECTURE.md`、`docs/MODULE_MAP.md`
- Create: `docs/UI_DESIGN.md`、`docs/UI_DESIGN_TOKENS.md`、`docs/UI_PAGE_STRUCTURE.md`、`docs/UI_COMPONENTS.md`、`docs/UI_MIGRATION.md`、`docs/UI_RESPONSIVE.md`、`docs/UI_AGE_TIERS.md`、`docs/UI_USABILITY_REVIEW.md`

**Interfaces:**
- Consumes: 全部前序任务的实现结果。
- Produces: 最终交付物。

- [ ] **Step 1: 更新 `docs/MODULE_MAP.md`**

§3 页面表中登记 `growth.html`/`profile.html` 与 3 个共享脚本及其验证套件；§1.1 新增 `uishell`、`growthweb` 两套件；§4 速查表新增「改儿童端导航/学生切换 → `ui-shell.js` → `python backend\verify_all.py uishell`」「改成长页/我的页 → `growth.js`、`profile.js` → `python backend\verify_all.py growthweb`」。

- [ ] **Step 2: 更新 `ARCHITECTURE.md`**

必须包含：Product Name = 菲比同学；当前前端架构（3 个共享脚本 + 零构建约束）；页面信息架构（4 项一级导航 + 旧页归位表）；公共 UI 组件清单；导航结构；`currentStudent` 状态管理（`xiaozhi.student` 唯一来源 + `onStudentChange` 订阅）；分龄 UI 规则（`data-age-mode` + 三档表）；Design System（token 清单）；知识状态儿童化映射（五档表）；主要页面与 API 关系表。
必须原样记录三条长期 UI 原则（spec §1.2）。
**不得**把未实现页面写成已完成；**不得**包含任何 API Key。

- [ ] **Step 3: 写 8 份交付文档**

按 spec §13 的 1–8 项逐一创建。其中：
- `docs/UI_DESIGN_TOKENS.md` 必须与 `frontend/style.css` 的 `:root` 逐项一致（写完后用脚本比对，见 Step 4）。
- `docs/UI_MIGRATION.md` 必须含「UI 前后对比说明」（旧：浅蓝底+620px 居中白卡+10 个底部链接；新：token 化 + 4 项导航 + 分龄 + 儿童化语言）。
- `docs/UI_USABILITY_REVIEW.md` 必须**如实标注**结论来自启发式评估 + 自动化断言，不是受控用户研究；十问逐项给证据（文件路径 + 断言名）。
- `docs/UI_RESPONSIVE.md` 断点表：`<720`、`720–1023`（底部导航）、`>=1024`（侧边栏）、`>=1024 且 ≤1280`（立牌 250px 让位）、`≤1060`（立牌 200px）。

- [ ] **Step 4: 校验文档与代码一致**

Run: `python -c "import re,pathlib;css=pathlib.Path('frontend/style.css').read_text(encoding='utf-8');root=re.search(r':root\{(.*?)\}', css, re.S).group(1);vars_=set(re.findall(r'(--[a-z0-9-]+):', root));doc=set(re.findall(r'(--[a-z0-9-]+)', pathlib.Path('docs/UI_DESIGN_TOKENS.md').read_text(encoding='utf-8')));print('缺文档:', sorted(vars_-doc));print('多文档:', sorted(doc-vars_-{'--color-error-soft'}))"`
Expected: 两个列表为空。

- [ ] **Step 5: 最终全量验证**

Run: `python backend\check_cards.py`
Run: `python backend\verify_all.py`
Expected: 均通过。把输出存入 `backup/snapshots/ui_final_verify_all.txt`。

- [ ] **Step 6: 最终快照**

目录名 `ui_final_`，复制整个 `frontend`、`ARCHITECTURE.md`、`docs`。

---

## Self-Review

**1. Spec coverage**

| Spec 章节 | 覆盖任务 |
|---|---|
| §3 Design Tokens | T1（变量）、T2（骨架/响应式/分龄） |
| §4 分龄系统 | T2（CSS）、T4（`ageModeOf`/`applyAgeMode`）、T11 Step 1 断言 |
| §5 儿童化映射 | T3（全部映射函数）、T9（逐级帮助）、T12（地图/复习） |
| §6 信息架构与导航 | T4（`mountNav`）、T6（接入各页）、T11（`growth`/`profile`） |
| §7 共享前端层 | T4、T5 |
| §8.1 今日首页 | T7 |
| §8.2 学习/答题页 | T8 |
| §8.3/8.4 答对/答错反馈 | T9 |
| §8.5 今日完成页 | T10 |
| §8.6/8.7 成长 + 知识地图 | T11（成长）、T12 Step 1（地图） |
| §8.8 错题中心 | T12 Step 2 |
| §8.9 复习页 | T12 Step 3 |
| §8.10 我的页面 | T11 Step 4 |
| §8.11 用户切换 | T4（`confirmSwitch`）、T11（我的页入口） |
| §8.12–8.14 空/Loading/Error | T13 |
| §9 验证契约变更 | T7 Step 5、T8 Step 5、T12 Step 4、T5 Step 5、T11 Step 5 |
| §10 实施顺序 | 任务编号 T1–T14 与阶段 P1–P8 一一对应 |
| §11 风险与回滚 | 每任务末的「快照」步骤 |
| §12 验收十问 | T14 Step 3（`UI_USABILITY_REVIEW.md`） |
| §13 交付物 | T14 |
| §44 ARCHITECTURE.md 强制更新 | T14 Step 2 |

无遗漏章节。

**2. Step scan** —— 已修正两处：Task 4 Step 1 中有 4 条断言用注释占位，已在同一步明示「必须替换为真实断言」；Task 8 Step 5 的「二选一」已明示必须与 `app.js` 实际输出一致。其余步骤均为单一可检查动作。

**3. Type consistency** —— 跨任务名称核对：`KidLang.statusOf/statusLabel/forgettingText/noReviewText/noWrongText/upgradeText/wrongFeedback/encourage`（T3 定义，T7/T9/T12 使用，命名一致）；`UIShell.ageModeOf/applyAgeMode/getStudentId/loadStudents/setStudentId/onStudentChange/getSettings/setSettings/applySettings/mountNav/confirmSwitch/createStudentSwitcher`（T4 定义，T6/T7/T10/T11 使用，命名一致）；`UIComponents` 组件名（T5 定义，T7–T13 使用，命名一致）。CSS 类名（T2 定义）在各任务中一致。

**4. Review Focus** —— 五条均已在 T2 Step 2/Step 4、T7 Step 4、T8 Step 3、T4 Step 3、T4 Step 1/T11 Step 1 中配了对应测试或实现约束。

**5. Proportion** —— 计划以文件清单 + 接口签名 + 测试断言为主，不转录实现代码体；仅对「签名与测试无法确定的算法/契约」给出代码块（`:root` token 清单、CSS 骨架、voice 降级、文档比对脚本）。

## Execution Handoff

本计划**未收到用户指定的执行方式**。请审阅计划后在两种方式中选择。
