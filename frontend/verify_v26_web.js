// ==============================================================
// 能力契约｜验证：V2.6 儿童端（今天 / 我的挑战 / 知识地图 / 统一学习会话）
// 入口：脚本自身：node frontend/verify_v26_web.js
// 依赖：Node fs/path/vm（沙箱加载 ui-shell.js + kid-lang.js + ui-components.js + learning-session.js + 页面 js）
// 不负责：后端口径与数据隔离 → backend/verify_v26.py
// 验证：node frontend/verify_v26_web.js
// 被调用：verify_all.py（套件 v26web）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 《菲比同学》V2.6 儿童端前端测试。
 *
 * 覆盖：默认首页「今天」的启动仪式与安静做题页、统一 LearningSession 的边界
 *       （做完就停，不出现无限加练入口）、儿童错误反馈与读题降级、
 *       ⚔️ 我的挑战儿童化（复用 V2.5 康复且不泄露答案）、
 *       🗺 知识地图使用真实接口且状态只读、分龄 UI 生效、双学生切换即时清空。
 *
 * 每个页面在自己的 vm 沙箱里加载（页面脚本都用 var 声明同名全局，不能共用一个上下文）。
 *
 * 用法：node frontend/verify_v26_web.js
 * 全部通过时退出码为 0。
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = __dirname;
let ok = true;

function check(name, cond, extra) {
    console.log((cond ? "PASS  " : "FAIL  ") + name + (extra === undefined ? "" : "  | " + extra));
    if (!cond) ok = false;
}

function readFile(name) {
    try {
        return fs.readFileSync(path.join(DIR, name), "utf8");
    } catch (err) {
        return "";
    }
}

const todayHtml = readFile("today.html");
const todayJs = readFile("today.js");
const sessionJs = readFile("learning-session.js");
const challengeHtml = readFile("challenge.html");
const challengeJs = readFile("challenge.js");
const mapHtml = readFile("knowledge_map.html");
const mapJs = readFile("knowledge_map.js");
const shellJs = readFile("ui-shell.js");
const kidLangJs = readFile("kid-lang.js");
const css = readFile("style.css");

/* ---------------- 1. 页面结构：今天 / 挑战 / 知识地图 ---------------- */

check("today.html 引用了 today.js", todayHtml.includes('src="today.js"'));
check("today.html 载入统一学习会话层", todayHtml.includes('src="learning-session.js"'));
check("learning-session.js 在 today.js 之前加载", (function () {
    const a = todayHtml.indexOf('src="learning-session.js"');
    const b = todayHtml.indexOf('src="today.js"');
    return a > -1 && b > -1 && a < b;
})());
check("today.html 有会话条与今日完成卡", todayHtml.includes('id="session-bar"')
    && todayHtml.includes('id="completion"'));
check("today.html 有读题/提示与安静做题区", todayHtml.includes('id="read-btn"')
    && todayHtml.includes('id="hint-box"') && todayHtml.includes("ph-quiet-tools"));
check("today.html 主按钮是儿童口吻（我做好了）", todayHtml.includes("我做好了"));
check("today.html 保留其它页面入口（老断言）",
    todayHtml.includes('class="meta link-row"') && todayHtml.includes('href="index.html"')
    && todayHtml.includes('href="ability.html"') && todayHtml.includes('href="wrong_book.html"'));

check("challenge.html 引用了 challenge.js", challengeHtml.includes('src="challenge.js"'));
check("challenge.html 挂了共享 UI 层", challengeHtml.includes('src="ui-shell.js"')
    && challengeHtml.includes('src="kid-lang.js"') && challengeHtml.includes('src="ui-components.js"'));
check("challenge.html 引用了 style.css", challengeHtml.includes('href="style.css"'));
check("挑战中心挂在一级导航里（不新增一级入口）", challengeHtml.includes('mountNav("wrong")'));

check("knowledge_map.html 有探索地图容器", mapHtml.includes('id="map-regions"')
    && mapHtml.includes('id="map-status"'));
check("knowledge_map.js 读 V2.6 知识地图接口", mapJs.includes("/api/knowledge-map/"));

function idCrossCheck(html, js, label) {
    const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
    const used = [...js.matchAll(/\$\("([^"]+)"\)/g)].map(m => m[1]);
    const missing = [...new Set(used)].filter(id => !ids.has(id));
    check(label + " 用到的元素都存在于页面", missing.length === 0, missing.join(", "));
}

idCrossCheck(todayHtml, todayJs, "today.js");
idCrossCheck(challengeHtml, challengeJs, "challenge.js");
idCrossCheck(mapHtml, mapJs, "knowledge_map.js");

/* ---------------- 2. 不出现沉迷机制（完成标准 P） ---------------- */

const DARK_PAGE = /抽卡|开箱|Loot\s*Box|排行榜|金币|断签|倒计时|再学\s*\d|再来一题|额外奖励|连续签到/;
const DARK_JS = /抽卡|开箱|Loot\s*Box|排行榜|金币|断签|倒计时|再学\s*\d|额外奖励|连续签到/;
check("今天页没有沉迷型入口", !DARK_PAGE.test(todayHtml) && !DARK_JS.test(todayJs));
check("挑战页没有沉迷型入口", !DARK_PAGE.test(challengeHtml) && !DARK_JS.test(challengeJs));
check("今日完成页只提供结束与看成长（无加练主按钮）",
    /ph-btn--primary" onclick="closeCompletion\(\)">完成</.test(todayJs)
    && todayJs.includes("看看我的成长"));
check("Design System 覆盖新增区块", css.includes(".ph-chip--sprout")
    && css.includes(".ph-card--region") && css.includes(".ph-wrong-group"));

/* ---------------- 3. 每页一个沙箱（页面脚本同名的全局变量互不干扰） ---------------- */

function buildSandbox(html, nodeStore) {
    function makeNode(id) {
        const node = {
            id,
            innerHTML: "",
            textContent: "",
            value: "",
            className: "",
            style: {},
            dataset: {},
            children: [],
            setAttribute(k, v) {
                this[k] = v;
                if (String(k).indexOf("data-") === 0) {
                    const key = String(k).slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
                    this.dataset[key] = String(v);
                }
            },
            getAttribute(k) { return this[k] === undefined ? null : this[k]; },
            appendChild(child) { this.children.push(child); return child; },
            removeChild(child) { return child; },
            remove() {},
            addEventListener() {},
            querySelector() { return null; },
            querySelectorAll() { return []; },
            classList: {
                add() {}, remove() {},
                toggle() { return true; },
                contains() { return false; },
            },
        };
        nodeStore[id] = node;
        return node;
    }

    [...html.matchAll(/id="([^"]+)"/g)].forEach(m => makeNode(m[1]));

    const documentElement = {
        dataset: {},
        style: {},
        setAttribute(k, v) {
            this[k] = v;
            if (String(k).indexOf("data-") === 0) {
                const key = String(k).slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
                this.dataset[key] = String(v);
            }
        },
        getAttribute(k) { return this[k] === undefined ? null : this[k]; },
    };

    const documentStub = {
        documentElement: documentElement,
        body: { classList: { add() {}, remove() {}, toggle() { return true; }, contains() { return false; } } },
        readyState: "complete",
        getElementById(id) { return nodeStore[id] || null; },
        createElement: makeNode,
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
    };

    const sandbox = {
        document: documentStub,
        fetch: fakeFetch,
        console,
        Math, Number, String, Boolean, Array, Object, JSON, isFinite,
        parseInt, parseFloat, Promise, Error, Date, RegExp, Set, Map,
        encodeURIComponent, decodeURIComponent, URLSearchParams,
        setTimeout, clearTimeout,
        location: { protocol: "http:", origin: "http://127.0.0.1:8000", href: "", search: "" },
        localStorage: {
            store: {},
            getItem(k) { return this.store[k] === undefined ? null : this.store[k]; },
            setItem(k, v) { this.store[k] = String(v); },
        },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    return { sandbox: sandbox, documentElement: documentElement };
}

function jsonResponse(data) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
}

const CHALLENGE = {
    student_id: 1,
    total: 3,
    counts: { red: 1, yellow: 1, green: 1, active: 2, mastered_rate: 0.33 },
    groups: {
        red: [{ recovery_id: 11, question_id: 101, tone: "red", icon: "🔴", tone_text: "等我攻克",
            subject: "数学", knowledge: "两位数乘法", question: "12 × 3 = ?" }],
        yellow: [{ recovery_id: 12, question_id: 102, tone: "yellow", icon: "🟡", tone_text: "正在训练",
            subject: "语文", knowledge: "近义词", question: "选择近义词" }],
        green: [{ recovery_id: 13, question_id: 103, tone: "green", icon: "🟢", tone_text: "已经攻克",
            subject: "英语", knowledge: "apple", question: "apple 的意思" }],
    },
    tones: { red: "🔴 等我攻克", yellow: "🟡 正在训练", green: "🟢 已经攻克" },
    next: { tone: "red", text: "先去攻克这 1 道吧。" },
    message: "今天有 3 道挑战在等你。",
};

const MAP = {
    student_id: 1,
    subject: "数学",
    regions: [
        { key: "乘法森林", name: "乘法森林", title: "🌲 乘法森林", icon: "🌲",
            total: 4, grown: 2, mastered: 1, percent: 50,
            progress_text: "2 / 4 知识已成长", nodes: ["乘法口诀", "两位数乘法"] },
    ],
    knowledge_nodes: [
        { knowledge_id: "乘法口诀", name: "乘法口诀", region: "乘法森林", is_unlocked: true,
            recommended: false, ui_status: { key: "solid", icon: "⭐", label: "记得很牢", rank: 4 } },
        { knowledge_id: "两位数乘法", name: "两位数乘法", region: "乘法森林", is_unlocked: true,
            recommended: true, ui_status: { key: "mastered", icon: "🌳", label: "已经掌握", rank: 3 } },
    ],
    recommended: ["两位数乘法"],
    totals: { total: 4, practiced: 2, grown: 2, mastered: 1, long_term: 1 },
    message: "乘法森林已经长出 2 个知识啦。",
};

function fakeFetch(url) {
    const text = String(url);
    if (text.endsWith("/students")) {
        return jsonResponse([
            { id: 1, name: "朵朵", grade: 1, grade_text: "一年级" },
            { id: 2, name: "童童", grade: 4, grade_text: "四年级" },
        ]);
    }
    if (text.includes("/api/challenge/")) return jsonResponse(CHALLENGE);
    if (text.includes("/api/knowledge-map/")) return jsonResponse(MAP);
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
}

const SHARED = ["ui-shell.js", "kid-lang.js", "ui-components.js"];

const todayNodes = {};
const todayEnv = buildSandbox(todayHtml, todayNodes);
SHARED.forEach(name => vm.runInContext(readFile(name), todayEnv.sandbox, { filename: name }));
vm.runInContext(sessionJs, todayEnv.sandbox, { filename: "learning-session.js" });
vm.runInContext(todayJs, todayEnv.sandbox, { filename: "today.js" });

const challengeNodes = {};
const challengeEnv = buildSandbox(challengeHtml, challengeNodes);
SHARED.forEach(name => vm.runInContext(readFile(name), challengeEnv.sandbox, { filename: name }));
vm.runInContext(challengeJs, challengeEnv.sandbox, { filename: "challenge.js" });

const mapNodes = {};
const mapEnv = buildSandbox(mapHtml, mapNodes);
SHARED.forEach(name => vm.runInContext(readFile(name), mapEnv.sandbox, { filename: name }));
vm.runInContext(mapJs, mapEnv.sandbox, { filename: "knowledge_map.js" });

const kidLang = todayEnv.sandbox.KidLang;
check("共享 UI 层与学习会话层都已加载",
    !!(todayEnv.sandbox.UIShell && kidLang && todayEnv.sandbox.UIComponents
        && todayEnv.sandbox.LearningSession));

/* ---------------- 4. 儿童知识状态只走 UI Adapter ---------------- */

const L = v => (kidLang.statusOf(v) || {}).label;
check("🌱刚开始 / 🌿正在学习 / 🌳已经掌握 / ⭐记得很牢 四档映射正确",
    L(0) === "刚开始" && L(30) === "正在学习" && L(75) === "已经掌握" && L(90) === "记得很牢",
    [L(0), L(30), L(75), L(90)].join(" / "));
check("没有学过的知识不显示成 0 分", (kidLang.statusOf(null) || {}).key === "sprout");
check("回答错的时候不说「你答错了」",
    /这里再想一下/.test(kidLang.wrongFeedback(1).title)
    && !/答错/.test(kidLang.wrongFeedback(1).title));
check("后端阈值与前端口径一致（90/75/55/30）",
    kidLangJs.includes("90") && kidLangJs.includes("75")
    && kidLangJs.includes("55") && kidLangJs.includes("30"));

/* ---------------- 5. 统一 LearningSession：做完就停 ---------------- */

const S = todayEnv.sandbox.LearningSession;
check("learning-session.js 导出完整会话 API",
    !!(S && S.start && S.choose && S.tick && S.mayContinue && S.progress
        && S.currentTask && S.finish && S.reset && S.studentChanged));
check("还没载入今日计划时不拦截旧的自由练习流程", S.mayContinue() === true);

S.setTasks([
    { task_id: 1, task_type: "new_learning", subject: "数学", knowledge: "两位数乘法",
        target_count: 1, complete_count: 0, status: "pending" },
    { task_id: 2, task_type: "review", subject: "英语", knowledge: "apple",
        target_count: 1, complete_count: 0, status: "pending" },
]);
const p0 = S.progress();
check("会话进度按小任务计数（不是百分比 / 不是时长）",
    p0.total === 2 && p0.done === 0 && p0.remaining === 2 && p0.finished === false,
    JSON.stringify(p0));
check("有限自主选择：可以决定先做哪一个", S.choose(2) && S.currentTask().task_id === 2);
check("系统仍掌握知识点（孩子只选顺序）", S.currentTask().knowledge === "apple");

const doneBefore = S.progress().done;
S.recordAnswer(true, 3);
check("答完一题就推进任务进度", S.progress().done > doneBefore,
    JSON.stringify(S.progress()));
check("任务进度不超过今日计划（不会无限加题）",
    S.progress().done <= S.progress().total && S.progress().remaining >= 0);
/* 多题任务必须按题数累计 —— 否则 target>1 的任务永远判不达标，孩子会一直刷同一科（真实 bug） */
S.setTasks([
    { task_id: 3, task_type: "new_learning", subject: "数学", knowledge: "20以内加减法",
        target_count: 3, complete_count: 0, status: "pending" },
    { task_id: 4, task_type: "new_learning", subject: "语文", knowledge: "拼音与声调",
        target_count: 3, complete_count: 0, status: "pending" },
]);
S.choose(3);
check("多题任务从 0 开始：第 1 题不算完成",
    S.progress().done === 0 && S.currentTask().task_id === 3,
    JSON.stringify(S.progress()));
S.recordAnswer(true, 0);
S.recordAnswer(true, 0);
check("多题任务答到第 2 题仍未完成（不会一直不结束也不会提前结束）",
    S.progress().done === 0 && S.currentTask().task_id === 3,
    JSON.stringify(S.progress()));
S.recordAnswer(true, 0);
check("答满 target_count（3 题）后任务完成",
    S.progress().done === 1, JSON.stringify(S.progress()));

S.setTasks([
    { task_id: 9, task_type: "review", subject: "数学", knowledge: "表内乘法",
        target_count: 1, complete_count: 1, status: "done" },
]);
check("今日计划全部做完后学习必须停下（mayContinue 为 false）",
    S.mayContinue() === false && S.progress().finished === true,
    JSON.stringify(S.progress()));

S.reset(true);
check("切换学生后会话立即清空（绝不残留上一个孩子的数据）",
    S.state().tasks.length === 0 && S.progress().total === 0 && S.currentTask() === null);

/* ---------------- 6. 今天页：安静做题 + 明确的结束点 ---------------- */
/* 任务完成判定：只有后端 status=done 才算完成 ——「待完成」里也含「完成」二字，不能误判 */
const todayApi = todayEnv.sandbox;
check("任务完成判定：pending / 待完成 / 进行中 都不算完成",
    typeof todayApi.taskDone === "function"
    && todayApi.taskDone({ status: "pending", status_text: "待完成" }) === false
    && todayApi.taskDone({ status: "doing", status_text: "进行中" }) === false
    && todayApi.taskDone({ status: "done", status_text: "已完成" }) === true);
const pendingTaskHtml = todayApi.taskItemHtml
    ? todayApi.taskItemHtml({ task_id: 9, subject: "数学", task_type: "wrong_recovery",
        status: "pending", status_text: "待完成", complete_count: 0,
        target_count: 1, target_minutes: 2 })
    : "";
check("需要手动打卡的任务（错题康复）仍显示「完成这一项」",
    pendingTaskHtml.includes("完成这一项") && !pendingTaskHtml.includes("已完成"),
    pendingTaskHtml.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 120));
const autoTaskHtml = todayApi.taskItemHtml
    ? todayApi.taskItemHtml({ task_id: 11, subject: "语文", task_type: "new_learning",
        status: "pending", status_text: "待完成", complete_count: 1,
        target_count: 5, target_minutes: 5 })
    : "";
check("答题型任务不再显示手动完成按钮（做够题数自动完成）",
    !autoTaskHtml.includes("完成这一项") && !autoTaskHtml.includes("已完成"),
    autoTaskHtml.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 120));
const doneTaskHtml = todayApi.taskItemHtml
    ? todayApi.taskItemHtml({ task_id: 19, subject: "数学", task_type: "new_learning",
        status: "done", status_text: "已完成", complete_count: 5,
        target_count: 5, target_minutes: 8 })
    : "";
check("已完成的任务显示「已完成」徽章、不再给按钮",
    doneTaskHtml.includes("已完成") && !doneTaskHtml.includes("完成这一项"));

check("点「开始今天的学习」在新标签页刷题（本页不再展开题目）",
    todayJs.includes("window.open(") && todayJs.includes('"_blank"')
    && todayJs.includes("practiceJumpUrl(pending.subject")
    && todayJs.includes("lastTaskData"));

/* V2.8 积分系统（m00845）：首页允许出现「积分商城」卡片（占位道具、只展示不兑换），
   但依然不出现排行榜 / 抽卡 / 宠物升级 / 金币这类成瘾入口，也不出现在做题页。 */
check("做题页只有读题与提示，不出现排行榜/抽卡/宠物升级/金币",
    !/排行榜|抽卡|宠物升级|金币/.test(todayJs));
check("首页有积分卡：余额 + 今日打卡 + 商城占位道具（读 /api/points/）",
    todayJs.includes("/api/points/") && todayJs.includes("function loadPoints")
    && todayJs.includes("function renderPoints") && todayJs.includes("points-card"));
check("积分打卡不再手动点：每日首次登录走 /login（幂等）",
    todayJs.includes("/login") && todayJs.includes("function claimDailyLogin")
    && !todayJs.includes("doPointsCheckin"));
check("商城只展示占位道具：写清「占位」与后端 note，不给兑换按钮",
    todayJs.includes("（占位）") && todayJs.includes("shop.note")
    && !todayJs.includes("doPointsRedeem"));

/* 连对 combo（V2.6 即时反馈） */
const styleCss = readFile("style.css");
check("今天页有连对 combo 动画（样式 + keyframes）",
    styleCss.includes(".ph-combo") && styleCss.includes("@keyframes ph-combo-pop")
    && todayJs.includes("comboHtml()"));
check("连对 1 题不显示 combo", todayEnv.sandbox.comboHtml(1) === "");
check("连对 2 题起显示连击数与档位",
    todayEnv.sandbox.comboHtml(2).includes("COMBO ×2")
    && todayEnv.sandbox.comboHtml(2).includes("is-start"));
check("连对越多档位越高（3 good / 5 hot / 8 super）",
    todayEnv.sandbox.comboHtml(3).includes("is-good")
    && todayEnv.sandbox.comboHtml(5).includes("is-hot")
    && todayEnv.sandbox.comboHtml(8).includes("is-super"));
check("combo 只是即时反馈，不泄露判分信息",
    !/score|correct_answer|mastery/i.test(todayEnv.sandbox.comboHtml(6)));
check("完成当日任务仍有明确结束点（今日完成卡）",
    typeof todayEnv.sandbox.renderCompletion === "function");

todayEnv.sandbox.renderCompletion({
    child: { new_learning: 1, review: 3, wrong_recovery: 2, active_recall: 4, minutes: 16 },
    lines: [],
});
const completionHtml = (todayNodes.completion || {}).innerHTML || "";
check("今日完成卡说清今天学到什么",
    completionHtml.includes("🎉 今天完成啦！") && completionHtml.includes("学会 1 个新知识")
    && completionHtml.includes("巩固 3 个旧知识") && completionHtml.includes("攻克 2 个挑战"),
    completionHtml.replace(/<[^>]+>/g, " "));
check("今日完成卡明确告诉孩子可以停下来",
    completionHtml.includes("今天已经完成啦，可以去休息了"));
check("今日完成卡不提供无限学习入口",
    !/再学|再来一题|继续挑战|额外奖励|加练/.test(completionHtml));

todayEnv.sandbox.renderSessionBar({ total: 3, done: 1, remaining: 2, percent: 33, minutes: 5 });
const barHtml = (todayNodes["session-bar"] || {}).innerHTML || "";
check("会话条给孩子看得懂的进度",
    barHtml.includes("已完成 1 / 3 个小任务"), barHtml);

check("没有语音能力时读题自动降级且不影响答题", (function () {
    if (todayEnv.sandbox.speechUsable()) return false;
    try {
        todayEnv.sandbox.readQuestion();
    } catch (err) {
        return false;
    }
    return true;
})());

/* ---------------- 7. ⚔️ 我的挑战（复用 V2.5 康复） ---------------- */

const ChallengePage = challengeEnv.sandbox.ChallengePage;
check("challenge.js 导出 ChallengePage",
    !!(ChallengePage && ChallengePage.init && ChallengePage.renderSummary && ChallengePage.renderGroups));

const challengeSummary = ChallengePage.renderSummary(CHALLENGE);
check("挑战中心用 🔴🟡🟢 表达状态",
    challengeSummary.includes("等我攻克") && challengeSummary.includes("正在训练")
    && challengeSummary.includes("已经攻克") && challengeSummary.includes(">1<"),
    challengeSummary.replace(/<[^>]+>/g, " "));

const challengeEmpty = ChallengePage.renderSummary({ empty: true });
check("没有挑战时是轻松文案", challengeEmpty.includes("🎉") && !/无数据|No data/i.test(challengeEmpty));
check("挑战中心不出现裸算法指标", !/掌握度\s*\d|稳定性|遗忘风险\s*\d/.test(challengeSummary));

const challengeGroups = ChallengePage.renderGroups(CHALLENGE);
check("挑战列表显示科目与知识点",
    challengeGroups.includes("数学") && challengeGroups.includes("两位数乘法"));
check("已攻克的挑战不再需要操作", challengeGroups.includes("已经掌握了"));
check("挑战列表不泄露答案与解析",
    !challengeJs.includes("correct_answer") && !challengeJs.includes("analysis"));
check("去攻克复用 V2.5 康复流程（不新开算法）",
    challengeJs.includes("/api/recovery/start") && challengeJs.includes("recovery.html"));

/* ---------------- 8. 🗺 知识地图用真实数据 ---------------- */

mapEnv.sandbox.renderKnowledgeMap(MAP);
const mapHtmlOut = (mapNodes["map-regions"] || {}).innerHTML || "";
check("知识地图使用接口返回的真实区域与状态",
    mapHtmlOut.includes("🌲 乘法森林") && mapHtmlOut.includes("2 / 4 知识已成长")
    && mapHtmlOut.includes("⭐ 乘法口诀") && mapHtmlOut.includes("🌳 两位数乘法"), mapHtmlOut);
check("知识地图状态只读（不让孩子自选知识点与难度）",
    mapHtmlOut.indexOf("onclick") === -1);
check("知识地图不显示后台算法字段",
    !/mastery_score|forgetting_risk|stability/.test(mapHtmlOut));

/* ---------------- 9. 分龄与双学生隔离 ---------------- */

check("一年级 = junior / 四年级 = middle / 六年级 = senior", (function () {
    const shell = todayEnv.sandbox.UIShell;
    shell.applyAgeMode(1);
    const junior = todayEnv.documentElement.dataset.ageMode === "junior";
    shell.applyAgeMode(4);
    const middle = todayEnv.documentElement.dataset.ageMode === "middle";
    shell.applyAgeMode(6);
    const senior = todayEnv.documentElement.dataset.ageMode === "senior";
    return junior && middle && senior;
})(), todayEnv.documentElement.dataset.ageMode);

check("一级导航都指向真实页面（今天/成长/挑战/商城/我的）", (function () {
    const tabs = [...shellJs.matchAll(/href:\s*"([a-z_]+\.html)"/g)].map(m => m[1]);
    const all = [...new Set(tabs)];
    return all.length >= 4 && all.every(name => fs.existsSync(path.join(DIR, name)));
})(), [...new Set([...shellJs.matchAll(/href:\s*"([a-z_]+\.html)"/g)].map(m => m[1]))].join(", "));

check("切换学生必须二次确认（不能悄悄换）",
    shellJs.includes("confirmSwitch") && !/setStudentId\(/.test(challengeJs));
check("每个页面都订阅了学生切换（换人立刻刷新）",
    challengeJs.includes("onStudentChange") && todayJs.includes("onStudentChange"));

/* 任务完成后会切到下一科（acknowledge 里 postJson 回来才 choose），单独重跑一遍流程再断言 */
setTimeout(function () {
    /* 题型轮转：刷完的题型不再出、优先未完成、一科做完切下一科 */
    check("learning-session 导出题型轮转接口 syncTask", typeof S.syncTask === "function");
    check("今天页出题前先过题型轮转（不再出已刷完的题型）",
        todayJs.includes("sessionSync()") && todayJs.includes("sync.changed"));

    S.reset(true);
    S.setTasks([
        { task_id: 51, task_type: "new_learning", subject: "数学", knowledge: "20以内加减法",
            target_count: 2, complete_count: 2, status: "done" },
        { task_id: 52, task_type: "new_learning", subject: "语文", knowledge: "拼音与声调",
            target_count: 2, complete_count: 0, status: "pending" },
        { task_id: 53, task_type: "review", subject: "英语", knowledge: "26个字母",
            target_count: 2, complete_count: 0, status: "pending" },
    ]);
    const sw1 = S.syncTask();
    check("刷完的题型自动让位：优先切到下一个未完成题型",
        sw1.changed === true && sw1.task && sw1.task.task_id === 52
        && S.currentTask() && S.currentTask().subject === "语文",
        JSON.stringify({ changed: sw1.changed, task: sw1.task && sw1.task.task_id,
            current: S.currentTask() && S.currentTask().subject }));
    const sw2 = S.syncTask();
    check("未完成的题型保持当前，不会被跳过",
        sw2.changed === false && sw2.continue === true && sw2.task.task_id === 52,
        JSON.stringify(sw2));

    S.reset(true);
    S.setTasks([
        { task_id: 31, task_type: "new_learning", subject: "数学", knowledge: "20以内加减法",
            target_count: 3, complete_count: 0, status: "pending" },
        { task_id: 32, task_type: "new_learning", subject: "语文", knowledge: "拼音与声调",
            target_count: 3, complete_count: 0, status: "pending" },
    ]);
    S.choose(31);
    S.recordAnswer(true, 0);
    S.recordAnswer(true, 0);
    S.recordAnswer(true, 0);
    setTimeout(function () {
        check("答满 3 题后自动切到下一科（不再卡在同一科刷题）",
            S.currentTask() && S.currentTask().task_id === 32,
            JSON.stringify({ current: S.currentTask() && S.currentTask().task_id,
                progress: S.progress() }));

        console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
        process.exit(ok ? 0 : 1);
    }, 60);
}, 10);
