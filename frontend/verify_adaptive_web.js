// ==============================================================
// 能力契约｜验证：今日学习页（today.js）计划渲染 / 出题 / 反馈逻辑
// 入口：脚本自身：node frontend/verify_adaptive_web.js
// 依赖：Node fs/vm（沙箱加载 today.html + today.js）
// 不负责：复习页 → 无（人工）
// 验证：node frontend/verify_adaptive_web.js
// 被调用：verify_all.py（套件 adaptweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * V2.3 自适应学习引擎前端测试：今日学习页（today.html / today.js）+ 学习反馈。
 *
 * 用 VM + DOM 打桩跑真实的 frontend/today.js，不需要浏览器、不需要后端。
 * 覆盖：页面与脚本引用一致、$("id") 引用的元素都真实存在、入口链接、
 *       今日计划渲染、开始学习 → 出题 → 判分 → 难度感受反馈全流程，
 *       以及星级 / 进度百分比 / 剩余题量文案等纯函数（边界值）。
 *
 * 用法：node frontend/verify_adaptive_web.js
 * 全部通过时退出码为 0。
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = __dirname;
const ORIGIN = "http://127.0.0.1:8000";
let ok = true;

function check(name, cond, extra) {
    console.log((cond ? "PASS  " : "FAIL  ") + name + (extra === undefined ? "" : "  | " + extra));
    if (!cond) ok = false;
}

function readFile(name) {
    return fs.readFileSync(path.join(DIR, name), "utf8");
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/* 儿童端共享层（kid-lang.js）也要在本测试自己的作用域里加载一份，
 * 这样断言可以直接引用同一套阀值，而不是把文案再拄一遍。 */
const langSandbox = {};
vm.createContext(langSandbox);
vm.runInContext(readFile("kid-lang.js"), langSandbox, { filename: "kid-lang.js" });
const KidLang = langSandbox.KidLang;

check("kid-lang.js 能在当前环境加载", !!KidLang && typeof KidLang.statusOf === "function");

/* ---------------- 1. 静态一致性 ---------------- */

const html = readFile("today.html");
const js = readFile("today.js");

check("today.html 引用了 today.js", html.includes('src="today.js"'));

const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
const used = new Set([...js.matchAll(/\$\("([^"]+)"\)/g)].map(m => m[1]));
const missing = [...used].filter(id => !ids.has(id));
check("today.js 用到的元素都存在于页面", missing.length === 0, missing.join(", "));

// V2.5 需求变更：不再要求"先做一次能力诊断"，入口换成自动能力水平页
check("today.html 有底部 link-row 回到其它页面",
    html.includes('class="meta link-row"')
    && ["index.html", "ability.html", "wrong_book.html"].every(link => html.includes(`href="${link}"`)));

check("today.js 顶部使用统一的 API 常量",
    js.includes("location.protocol") && js.includes('"http://127.0.0.1:8000"'));

const indexHtml = readFile("index.html");
check("index.html 有今日学习入口", indexHtml.includes('href="today.html"'));
// V2.5 需求变更：能力水平由训练成绩自动推断，练习页入口改为 ability.html
check("index.html 入口指向自动能力水平与知识地图",
    indexHtml.includes('href="ability.html"') && indexHtml.includes('href="knowledge_map.html"'));

const styleCss = readFile("style.css");
check("style.css 追加了自适应学习样式且保留旧样式",
    ["V2.3 自适应学习引擎", ".plan-item", ".start-btn", ".feel-btn", ".why-box", ".domain-card"].every(
        token => styleCss.includes(token)));

/* ---------------- 2. DOM 打桩 ---------------- */

function makeClassList(initial) {
    const set = new Set(String(initial || "").split(/\s+/).filter(Boolean));
    return {
        add: c => set.add(c),
        remove: c => set.delete(c),
        contains: c => set.has(c),
        toggle: (c, force) => {
            const on = force === undefined ? !set.has(c) : !!force;
            if (on) set.add(c); else set.delete(c);
            return on;
        },
        _set: set,
    };
}

function buildContext(payloads) {
    const tags = {};
    for (const match of html.matchAll(/<(select|input|div|p|span)\b([^>]*)>/g)) {
        const idMatch = /id="([^"]+)"/.exec(match[2]);
        if (idMatch) tags[idMatch[1]] = match[1];
    }

    const nodes = {};
    const calls = [];

    for (const id of ids) {
        const el = {
            id,
            value: "",
            checked: false,
            disabled: false,
            textContent: "",
            dataset: {},
            style: {},
            focus() {},
        };
        el.classList = makeClassList("");

        let inner = "";
        Object.defineProperty(el, "innerHTML", {
            get() { return inner; },
            set(value) {
                inner = String(value);
                if (tags[id] === "select") {
                    const first = /<option value="([^"]*)"/.exec(inner);
                    if (first) el.value = first[1];
                }
            },
        });

        nodes[id] = el;
    }

    const store = {};
    const context = {
        document: {
            getElementById: id => nodes[id] || null,
            querySelectorAll: () => [],
            querySelector: () => null,
            addEventListener() {},
        },
        console,
        setTimeout,
        clearTimeout,
        location: { protocol: "http:", origin: ORIGIN, href: "" },
        localStorage: {
            getItem: key => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
            setItem: (key, value) => { store[key] = String(value); },
        },
        fetch: (url, options) => {
            const call = { url: String(url), options: options || {} };
            calls.push(call);
            const payload = payloads(call.url, call.options);
            if (payload === undefined) {
                return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
            }
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
        },
        URLSearchParams,
        Number,
        Math,
        JSON,
    };
    context.window = context;
    context.globalThis = context;

    return { context, nodes, calls };
}

function loadModule(payloads, exportsSource) {
    const { context, nodes, calls } = buildContext(payloads);
    vm.createContext(context);
    // 真实页面的加载顺序：业务 js 在前，共享层（ui-shell / kid-lang / ui-components）在后。
    vm.runInContext(readFile("today.js"), context, { filename: "today.js" });
    vm.runInContext(readFile("ui-shell.js"), context, { filename: "ui-shell.js" });
    vm.runInContext(readFile("kid-lang.js"), context, { filename: "kid-lang.js" });
    vm.runInContext(readFile("ui-components.js"), context, { filename: "ui-components.js" });
    vm.runInContext(";globalThis.__x = {" + exportsSource + "};", context, { filename: "exports.js" });
    return { context, nodes, calls, api: context.__x };
}

/* ---------------- 3. 接口数据 ---------------- */

const PLAN = {
    student_id: 1,
    date: "2026-10-04",
    minutes: 35,
    target_count: 30,
    completed_count: 10,
    progress: 33,
    items: [
        {
            id: 1, subject: "数学", knowledge_id: "两步计算应用题", action: "practice",
            difficulty: 62, duration_minutes: 15, target_count: 10, completed_count: 2,
            remain_count: 8, status: "doing", status_text: "进行中",
            goal: "应用题强化，完成 10 题", reason: "掌握度60，需要强化", target_mastery: 70,
        },
        {
            id: 2, subject: "英语", knowledge_id: "颜色", action: "review",
            difficulty: 45, duration_minutes: 10, target_count: 20, completed_count: 5,
            remain_count: 15, status: "doing", status_text: "进行中",
            goal: "复习 20 个单词", reason: "掌握度55，需要强化", target_mastery: 65,
        },
    ],
};

const LOGS = {
    student_id: 1,
    logs: [
        { id: 3, action: "practice", reason: "掌握度60，需要强化", subject: "数学",
          knowledge: "两步计算应用题", difficulty: 62, mode: "practice", source: "recommend",
          created_time: "2026-10-04 20:00" },
        { id: 2, action: "review", reason: "颜色已经到复习时间", subject: "英语",
          knowledge: "颜色", difficulty: 45, mode: "review", source: "start",
          created_time: "2026-10-04 19:50" },
    ],
    feedback: { total: 1, by_feel: { hard: 1 }, need_help: 1, items: [] },
    feel_text: { hard: "有点难" },
    planning: { default_minutes: { 数学: 15, 语文: 10, 英语: 10 }, total_minutes: 35 },
};

const TASK = {
    student_id: 1, subject: "数学", knowledge: "两步计算应用题", difficulty: 62,
    mode: "practice", reason: "掌握度60，需要强化", target_count: 10, completed_count: 2,
    plan_id: 1, plan: PLAN, difficulty_state: { difficulty: 62, delta: 5 },
};

const QUESTION = {
    question_id: 88,
    qtype: "choice",
    subject: "数学",
    knowledge: "两步计算应用题",
    difficulty: 62,
    question: "小明有 3 盒铅笔，每盒 5 支，送给同学 2 支，还剩多少支？",
    options: { A: "13", B: "15", C: "17", D: "10" },
    adaptive: {
        action: "practice", action_text: "强化练习", mode: "practice",
        knowledge: "两步计算应用题", difficulty: 62,
        reason: "薄弱知识优先：两步计算应用题（掌握度 60）",
        score: 0.62, breakdown: { weakness: 0.4, match: 0.9, forgetting: 0.2, random: 0.5 },
        difficulty_state: { difficulty: 62, delta: 5 },
    },
};

const SUBMIT_RESULT = {
    correct: false, correct_answer: "A", correct_text: "13",
    analysis: "先算 3×5=15，再减 2，答案是 13。", qtype: "choice",
    knowledge: "两步计算应用题",
    mastery: { knowledge: "两步计算应用题", mastery_score: 58, level: "巩固中" },
};

const FEEDBACK = {
    saved: true, id: 1, subject: "数学", knowledge: "两步计算应用题",
    feel: "hard", feel_text: "有点难", need_help: true,
    next_difficulty: 52, difficulty_delta: -10,
    difficulty_reason: "连续答错 3 题，难度 -10",
    message: "没关系，觉得难说明正在进步：下一题难度会降一点，先把基础打牢。",
    feel_options: [
        { value: "easy", text: "😊 简单" }, { value: "normal", text: "🙂 正常" },
        { value: "hard", text: "🤔 有点难" }, { value: "lost", text: "😵 不会" },
    ],
    plan: { id: 1, completed_count: 3, target_count: 10, status: "doing" },
};

function route(url) {
    if (url.includes("/students")) return [{ id: 1, name: "小朋友A", grade_text: "一年级" },
                                           { id: 2, name: "小朋友B", grade_text: "一年级" }];
    if (url.includes("/api/learning/next-question")) return QUESTION;
    if (url.includes("/api/learning/start")) return TASK;
    if (url.includes("/api/learning/feedback")) return FEEDBACK;
    if (url.includes("/api/learning/strategy-log/")) return LOGS;
    if (url.includes("/api/learning/plan/")) return PLAN;
    if (url.includes("/submit")) return SUBMIT_RESULT;
    return undefined;
}

/* ---------------- 4. 纯函数 ---------------- */

const loaded = loadModule(route, [
    "starsOf: typeof starsOf === 'function' ? starsOf : null",
    "starText: typeof starText === 'function' ? starText : null",
    "percent: typeof percent === 'function' ? percent : null",
    "remainText: typeof remainText === 'function' ? remainText : null",
    "actionText: typeof actionText === 'function' ? actionText : null",
    "feelButtonsHtml: typeof feelButtonsHtml === 'function' ? feelButtonsHtml : null",
    "renderPlanHead: typeof renderPlanHead === 'function' ? renderPlanHead : null",
    "renderPlanList: typeof renderPlanList === 'function' ? renderPlanList : null",
    "renderWhy: typeof renderWhy === 'function' ? renderWhy : null",
    "startTask: typeof startTask === 'function' ? startTask : null",
    "practiceJumpUrl: typeof practiceJumpUrl === 'function' ? practiceJumpUrl : null",
    "submitAnswer: typeof submitAnswer === 'function' ? submitAnswer : null",
    "sendFeedback: typeof sendFeedback === 'function' ? sendFeedback : null",
    "sheetRowHtml: typeof sheetRowHtml === 'function' ? sheetRowHtml : null",
    "renderSheetPreview: typeof renderSheetPreview === 'function' ? renderSheetPreview : null",
    "renderPoints: typeof renderPoints === 'function' ? renderPoints : null",
    "pointsShopRowHtml: typeof pointsShopRowHtml === 'function' ? pointsShopRowHtml : null",
].join(","));

const api = loaded.api;

check("星级：0 分不给星", api.starsOf(0) === 0, api.starsOf(0));
check("星级：62 分三颗星", api.starsOf(62) === 4 || api.starsOf(62) === 3, api.starsOf(62));
check("星级：100 分五颗星", api.starsOf(100) === 5, api.starsOf(100));
check("星级文案含空心星", api.starText(85) === "★★★★★" && api.starText(0) === "☆☆☆☆☆",
    api.starText(85));
check("进度百分比：分母为 0 返回 0", api.percent(3, 0) === 0, api.percent(3, 0));
check("进度百分比：超过 100% 截断", api.percent(12, 10) === 100, api.percent(12, 10));
check("进度百分比：正常取整", api.percent(1, 3) === 33, api.percent(1, 3));
check("剩余题量文案（数学按题）", api.remainText({ subject: "数学", remain_count: 8 }) === "剩余：8 题",
    api.remainText({ subject: "数学", remain_count: 8 }));
check("剩余题量文案（英语按个）", api.remainText({ subject: "英语", remain_count: 15 }) === "剩余：15 个",
    api.remainText({ subject: "英语", remain_count: 15 }));
check("完成时给鼓励文案", api.remainText({ subject: "数学", remain_count: 0 }).includes("完成"));
check("动作文案中文", api.actionText("review") === "复习巩固", api.actionText("review"));
check("四个难度感受选项", (api.feelButtonsHtml().match(/feel-btn/g) || []).length === 4,
    api.feelButtonsHtml());

check("计划头部有开始今日学习按钮",
    api.renderPlanHead(PLAN).includes("开始今日学习"), "ok");
check("计划头部显示总时长", api.renderPlanHead(PLAN).includes("35 分钟"), "ok");
check("计划卡片显示知识点与剩余题量",
    api.renderPlanList(PLAN).includes("两步计算应用题")
    && api.renderPlanList(PLAN).includes("剩余：8 题"), "ok");
// V2.5 需求变更：计划为空时不再要求孩子先做诊断，而是引导自由练习后自动判断水平
check("计划为空时引导先自由练习并给出能力水平入口",
    api.renderPlanHead({ items: [] }).includes("自由练习")
    && api.renderPlanHead({ items: [] }).includes("ability.html"), "ok");
check("为什么这样安排展示推荐理由（儿童化，不出现掌握度）",
    api.renderWhy(LOGS).includes(KidLang.statusOf(60).label)
    && !api.renderWhy(LOGS).includes("掌握度"), "ok");

/* V2.8 需求：每道题带内部标记（如「数学 · 新知识」），一项里 5 道只做完 3 道就显示 3/5，
   完成后这一项视为收工，重新出题时直接跳过它。 */
api.renderSheetPreview({
    tasks: [
        { title: "数学 · 新知识", subject: "数学", target_count: 5, complete_count: 3, status: "doing", priority: 1 },
        { title: "语文 · 复习恢复", subject: "语文", target_count: 2, complete_count: 2, status: "done", priority: 6 },
    ],
});
const sheetHtml = loaded.nodes["plan-sheet"].innerHTML;
const sheetText = sheetHtml.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

check("题单：只做完 3/5 的一项也列出来，写清还剩几题",
    sheetText.includes("数学 · 新知识") && sheetText.includes("3/5") && sheetText.includes("还差 2 题"),
    sheetText.slice(0, 120));
check("题单：做完的一项标 ✅ 已完成（重新出题不再出它）",
    sheetText.includes("✅") && sheetText.includes("已完成"), sheetText.slice(0, 120));
check("题单：标题说明「一项做完就收工」", sheetText.includes("一项做完就收工"), sheetText.slice(0, 120));

api.renderSheetPreview({ tasks: [] });
check("题单：今天没有剩题时不渲染空清单", loaded.nodes["plan-sheet"].innerHTML === "");

/* V2.8 需求（m00845）：首页有积分卡（每日打卡 / 每答对一题 / 计划做完后继续练 / 任务收工），
   商城只展示占位道具：兑换比例先占位、不实装（不给兑换按钮）。 */
api.renderPoints({
    balance: 22, today_points: 22, streak: 1, checked_in: true,
    rules: [{ event: "answer_correct", label: "答对一题", points: 2 },
            { event: "daily_checkin", label: "每日打卡", points: 10 }],
    shop: { enabled: false, note: "兑换比例先占位，兑换功能还没实装",
            items: [{ key: "ipad_time", emoji: "📱", label: "iPad 使用时间 30 分钟",
                      cost: 200, affordable: false }] },
    records: [{ date: "2026-10-05", event: "task_done", label: "一项任务收工", points: 5,
                time: "10-05 17:58" }],
});
const pointsHtml = loaded.nodes["points-card"].innerHTML;
const pointsText = pointsHtml.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

check("积分：首页显示余额与今日获得",
    pointsText.includes("22") && pointsText.includes("今日 +22"), pointsText.slice(0, 120));
check("积分：已打卡就显示「今天已打卡」，不再给打卡按钮",
    pointsText.includes("今天已打卡") && !pointsHtml.includes("doPointsCheckin()"),
    pointsText.slice(0, 160));
check("积分：怎么挣积分来自后端规则（答对一题 +2 / 每日打卡 +10）",
    pointsText.includes("答对一题 +2") && pointsText.includes("每日打卡 +10"),
    pointsText.slice(0, 200));
check("积分：商城是占位（写清占位与说明、道具带积分价、还差多少）",
    pointsText.includes("积分商城") && pointsText.includes("（占位）")
    && pointsText.includes("iPad 使用时间 30 分钟") && pointsText.includes("200 积分")
    && pointsText.includes("还差 178") && pointsText.includes("兑换功能还没实装"),
    pointsText.slice(0, 220));
check("积分：最近挣到的流水带「+多少分 + 哪一类」",
    pointsText.includes("最近挣到的") && pointsText.includes("+5 一项任务收工"),
    pointsText.slice(0, 220));
api.renderPoints({ error: "积分暂时读不出来，过一会儿再试" });
check("积分：读不出来时只提示一句，不炸整页（也不显示商城）",
    loaded.nodes["points-card"].innerHTML.includes("积分暂时读不出来")
    && !loaded.nodes["points-card"].innerHTML.includes("商城"), "");

/* ---------------- 5. 页面流程 ---------------- */

async function flow() {
    await sleep(20);

    check("初始化后填充学生下拉", loaded.nodes.student.innerHTML.includes("小朋友A"),
        loaded.nodes.student.innerHTML.slice(0, 40));
    check("初始化后渲染今日目标",
        loaded.nodes["plan-head"].innerHTML.includes("今天的学习目标"),
        loaded.nodes["plan-head"].innerHTML.slice(0, 40));
    check("初始化后渲染三科计划卡片",
        loaded.nodes["plan-list"].innerHTML.includes("两步计算应用题")
        && loaded.nodes["plan-list"].innerHTML.includes("复习 20 个单词"), "ok");
    check("初始化后展示推荐理由", loaded.nodes.why.innerHTML.includes("为什么这样安排"), "ok");
    check("初始化调用今日计划接口",
        loaded.calls.some(call => call.url.includes("/api/learning/plan/1")), "ok");

    check("开始今日学习改为整页跳到练习页（不再调 /api/learning/start）",
        api.practiceJumpUrl("数学", "两步计算应用题") === "index.html?student_id=1&subject=%E6%95%B0%E5%AD%A6&knowledge=%E4%B8%A4%E6%AD%A5%E8%AE%A1%E7%AE%97%E5%BA%94%E7%94%A8%E9%A2%98&from=today&autostart=1"
        && api.practiceJumpUrl("数学", "两步计算应用题").includes("autostart=1")
        && api.practiceJumpUrl("数学", "两步计算应用题").includes("from=today"),
        api.practiceJumpUrl("数学", "两步计算应用题"));
    check("V2.8 题单：开始今天的学习带上 sheet=1（先读剩余题型再统一出题）",
        api.practiceJumpUrl("数学", "两步计算应用题", true).includes("sheet=1")
        && api.practiceJumpUrl("数学", "两步计算应用题", true).includes("from=today")
        && api.practiceJumpUrl("数学", "两步计算应用题", true).includes("autostart=1"),
        api.practiceJumpUrl("数学", "两步计算应用题", true));
    check("开始今日学习按钮改为新标签页刷题（未完成的小任务优先）",
        api.renderPlanHead(PLAN).includes('onclick="startToday()"')
        && api.renderPlanHead(PLAN).includes("开始今日学习"),
        api.renderPlanHead(PLAN).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 120));
}

/* V2.5+ 需求变更：开始今日学习改为整页跳转到自由练习页答题（题目不再堆在计划页下方） */
function practiceFlow() {
    return sleep(20).then(() => {
        const fresh = loadModule(route, [
            "renderQuestion: typeof renderQuestion === 'function' ? renderQuestion : null",
            "submitAnswer: typeof submitAnswer === 'function' ? submitAnswer : null",
            "sendFeedback: typeof sendFeedback === 'function' ? sendFeedback : null",
            "setTask: value => { currentTask = value; }",
            "loadNext: typeof loadNext === 'function' ? loadNext : null",
            "retryQuestion: typeof retryQuestion === 'function' ? retryQuestion : null",
        ].join(","));

        fresh.api.setTask({ subject: "数学", knowledge: "两步计算应用题", difficulty: 62 });
        fresh.api.loadNext();
        return sleep(20).then(() => {
            check("跳转后的练习页按今日知识点请求自适应出题",
                fresh.calls.some(call => call.url.includes("next-question")
                    && call.url.includes(encodeURIComponent("两步计算应用题").replace(/%2F/g, "/"))), "ok");
            check("显示自适应标签（知识点 + 难度 + 儿童化状态）",
                fresh.nodes["adaptive-badge"].innerHTML.includes("两步计算应用题")
                && fresh.nodes["adaptive-badge"].innerHTML.includes("难度 62")
                && fresh.nodes["adaptive-badge"].innerHTML.includes(KidLang.statusOf(60).label)
                && !fresh.nodes["adaptive-badge"].innerHTML.includes("掌握度"),
                fresh.nodes["adaptive-badge"].innerHTML.slice(0, 60));
            check("渲染题目与选项",
                fresh.nodes.question.innerHTML.includes("铅笔")
                && fresh.nodes.options.innerHTML.includes("13"), "ok");
            fresh.api.submitAnswer("B", null);
            return sleep(20);
        }).then(() => {
            // 第一次答错：温和提示 + 第一级帮助，不能出现 ❌
            check("判分后先给「这里再想一下」而不是错误处罚",
                fresh.nodes.result.innerHTML.includes(KidLang.wrongFeedback(1).title)
                && !fresh.nodes.result.innerHTML.includes("❌"),
                fresh.nodes.result.innerHTML.slice(0, 40));
            check("答错第一级给出方向提示与「我再试试」",
                fresh.nodes.result.innerHTML.includes(KidLang.wrongFeedback(1).level)
                && fresh.nodes.result.innerHTML.includes(KidLang.wrongFeedback(1).retryLabel), "ok");

            // 点「我再试试」重做同一题，再错一次 → 帮助升一级
            fresh.api.retryQuestion();
            fresh.api.submitAnswer("A", null);
            return sleep(20);
        }).then(() => {
            check("再错一次升到第二级帮助",
                fresh.nodes.result.innerHTML.includes(KidLang.wrongFeedback(2).level), "ok");
            check("判分后显示解析与儿童化状态",
                fresh.nodes.result.innerHTML.includes("解析")
                && fresh.nodes.result.innerHTML.includes(KidLang.statusOf(58).label)
                && !fresh.nodes.result.innerHTML.includes("掌握度"), "ok");
            check("题目结束后询问难度感受",
                fresh.nodes["feel-box"].innerHTML.includes("这道题感觉")
                && fresh.nodes["feel-box"].innerHTML.includes("😊 简单")
                && fresh.nodes["feel-box"].innerHTML.includes("😵 不会"), "ok");
            check("感受区提供需要帮助按钮",
                fresh.nodes["feel-box"].innerHTML.includes("需要帮助"), "ok");

            fresh.api.sendFeedback("hard", true);
            return sleep(20);
        }).then(() => {
            const feedbackCall = fresh.calls.find(call => call.url.includes("/api/learning/feedback"));
            check("反馈请求带上难度感受与求助标记",
                feedbackCall && feedbackCall.options.body.includes('"feel":"hard"')
                && feedbackCall.options.body.includes('"need_help":true'), feedbackCall && feedbackCall.options.body);
            check("反馈后显示下一题难度建议",
                fresh.nodes["feel-box"].innerHTML.includes("下一题难度")
                && fresh.nodes["feel-box"].innerHTML.includes("52"), "ok");
            check("反馈后显示系统回复",
                fresh.nodes["feel-box"].innerHTML.includes("先把基础打牢"), "ok");
            check("反馈后刷新今日进度",
                fresh.nodes["plan-head"].innerHTML.includes("今天的学习目标"), "ok");

            console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
            process.exit(ok ? 0 : 1);
        });
    });
}

flow().then(practiceFlow);
