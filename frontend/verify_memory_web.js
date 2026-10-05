// ==============================================================
// 能力契约｜验证：间隔复习前端（review.html/review.js 知识浇水 + memory_debug.html/memory_debug.js 记忆数据）
// 入口：脚本自身：node frontend/verify_memory_web.js
// 依赖：Node fs/vm（沙箱加载 html + js，DOM 打桩）
// 不负责：今日学习页 → verify_adaptive_web.js；诊断三页 → verify_diagnostic_web.js
// 验证：node frontend/verify_memory_web.js
// 被调用：verify_all.py（套件 memweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * V2.4 间隔复习系统前端测试：知识浇水（儿童端 review.html/review.js）
 *                            + 记忆数据（家长端 memory_debug.html/memory_debug.js）。
 *
 * 用 VM + DOM 打桩跑真实的 frontend/*.js，不需要浏览器、不需要后端。
 * 覆盖：页面与脚本引用一致、$("id") 引用的元素都真实存在、入口链接、
 *       儿童端只出现"浇水/树的成长"说法（没有风险百分比）、
 *       复习出题 → 作答 → 感受反馈全流程、家长端表格与算法日志渲染，
 *       以及成熟度文案 / 风险分级 / 间隔显示等纯函数边界。
 *
 * 用法：node frontend/verify_memory_web.js
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

/* ---------------- 1. 静态一致性 ---------------- */

const PAGES = [
    { html: "review.html", js: "review.js" },
    { html: "memory_debug.html", js: "memory_debug.js" },
];

const LINKS = ["index.html", "today.html", "review.html", "knowledge_map.html", "wrong_book.html"];

for (const page of PAGES) {
    const html = readFile(page.html);
    const js = readFile(page.js);

    check(`${page.html} 引用了 ${page.js}`, html.includes(`src="${page.js}"`));

    const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
    const used = new Set([...js.matchAll(/\$\("([^"]+)"\)/g)].map(m => m[1]));
    const missing = [...used].filter(id => !ids.has(id));
    check(`${page.js} 用到的元素都存在于页面`, missing.length === 0, missing.join(", "));

    check(`${page.html} 有底部 link-row 回到其它页面`,
        html.includes('class="meta link-row"')
        && LINKS.filter(link => link !== page.html).every(link => html.includes(`href="${link}"`)));

    check(`${page.js} 顶部使用统一的 API 常量`,
        js.includes("location.protocol") && js.includes('"http://127.0.0.1:8000"'));
}

const indexHtml = readFile("index.html");
check("index.html 有知识浇水入口", indexHtml.includes('href="review.html"'));
check("index.html 保留今日学习入口", indexHtml.includes('href="today.html"'));

const todayHtml = readFile("today.html");
check("today.html 有知识浇水入口", todayHtml.includes('href="review.html"'));

const styleCss = readFile("style.css");
check("style.css 追加了 V2.4 样式且保留 V2.3 样式",
    ["V2.4 间隔复习", ".memory-card", ".memory-row", ".risk-high", ".risk-low", ".plan-item"]
        .every(token => styleCss.includes(token)));

/* ---------------- 2. DOM 打桩 ---------------- */

function makeClassList() {
    const set = new Set();
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

function buildContext(htmlFile, payloads) {
    const html = readFile(htmlFile);
    const ids = [...new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]))];
    const nodes = {};
    const calls = [];

    for (const id of ids) {
        const el = {
            id,
            value: "",
            disabled: false,
            textContent: "",
            dataset: {},
            style: {},
            focus() {},
        };
        el.classList = makeClassList();

        let inner = "";
        Object.defineProperty(el, "innerHTML", {
            get() { return inner; },
            set(value) {
                inner = String(value);
                const first = /<option value="([^"]*)"/.exec(inner);
                if (first && id === "student") el.value = first[1];
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
        Date,
    };
    context.window = context;
    context.globalThis = context;

    return { context, nodes, calls };
}

function loadModule(htmlFile, jsFile, payloads, exportsSource) {
    const { context, nodes, calls } = buildContext(htmlFile, payloads);
    const source = readFile(jsFile) + "\n;globalThis.__x = {" + exportsSource + "};";
    vm.createContext(context);
    vm.runInContext(source, context, { filename: jsFile });
    return { context, nodes, calls, api: context.__x };
}

/* ---------------- 3. 接口数据 ---------------- */

const TODAY = {
    student_id: 1,
    date: "2026-10-10",
    items: [
        {
            subject: "数学", knowledge_id: "表内乘法", queue_id: 1, priority: "P0",
            priority_text: "已经到期", target_count: 3, completed_count: 0, status: "PENDING",
            maturity_level: "STABLE", maturity_child: "🌳 记得很牢", forest_icon: "🌲",
            forgetting_risk: 0.8, risk_percent: 80, mastery_score: 88,
            queue_reason: "该复习了，掌握度 88",
        },
        {
            subject: "数学", knowledge_id: "两步计算应用题", queue_id: 2, priority: "P0",
            priority_text: "已经到期", target_count: 1, completed_count: 0, status: "PENDING",
            maturity_level: "CONSOLIDATING", maturity_child: "🌿 正在巩固", forest_icon: "🌳",
            forgetting_risk: 0.5, risk_percent: 50, mastery_score: 62,
            queue_reason: "该复习了，掌握度 62",
        },
    ],
    relearn: [{ subject: "数学", knowledge_id: "表内除法", mastery_score: 42,
                reason: "掌握度 42，先重新学会再来复习" }],
    total: 2,
    completed: 0,
    remaining: 2,
    child_title: "今天有 2 个知识需要浇水",
    child_message: "今天有 2 个知识需要浇水",
    planned_questions: 4,
    by_priority: { P0: 2, P1: 0, P2: 0, P3: 0 },
};

const QUESTION = {
    question_id: 9, subject: "数学", knowledge: "表内乘法", qtype: "choice",
    question: "算一算：7 × 8 = ？",
    options: { A: "54", B: "56", C: "48", D: "64" },
    difficulty: 60, mode: "variant", mode_text: "变式题",
    expected_seconds: 45, repeated: false, source: "review_bank",
    memory: { knowledge_id: "表内乘法", maturity_level: "STABLE",
              maturity_child: "🌳 记得很牢", mastery_score: 88, stability: 21 },
};

const ANSWER = {
    correct: true, review_quality: "EASY", review_quality_text: "非常容易",
    previous_interval: 14, next_interval: 32, new_stability: 40.1,
    memory_strength: 90, maturity_level: "STABLE", maturity_child: "🌳 记得很牢",
    maturity_upgraded: false, next_review_at: "2026-11-11 09:00",
    next_review_date: "2026-11-11", action: "REVIEW", need_verify: false,
    child_message: "太厉害了，记得非常牢！下次复习会晚一点再来找你～",
    review_quality: "EASY",
};

const FEELBACK = {
    saved: true, question_id: 9, feel: "easy", old_interval: 32, next_interval: 35,
    next_review_at: "2026-11-14 09:00",
    memory: { maturity_child: "🌳 记得很牢", maturity_level: "STABLE" },
};

const MAP = {
    student_id: 1, date: "2026-10-10", total: 2,
    items: [
        { subject: "数学", knowledge_id: "表内乘法", mastery_score: 88, memory_strength: 90,
          stability: 21, difficulty: 0.3, forgetting_risk: 0.2, risk_percent: 20,
          next_review_date: "2026-10-12", maturity_level: "STABLE", maturity_text: "稳定掌握",
          forest_icon: "🌲", action_text: "间隔复习", needs_relearn: false },
        { subject: "数学", knowledge_id: "表内除法", mastery_score: 42, memory_strength: 30,
          stability: 1, difficulty: 0.8, forgetting_risk: 0.9, risk_percent: 90,
          next_review_date: "2026-10-10", maturity_level: "LEARNING", maturity_text: "正在学习",
          forest_icon: "🌱", action_text: "重新学习", needs_relearn: true },
    ],
    summary: { by_maturity: { STABLE: 1, LEARNING: 1 }, average_stability: 11,
               average_memory_strength: 60, high_risk: 1, due: 1, relearn: 1 },
};

const STATS = {
    student_id: 1, date: "2026-10-10", due_count: 2, completed_count: 1,
    remaining_count: 1, high_risk_count: 1, long_term_count: 0, stable_count: 1,
    relearn_count: 1, total_knowledge: 2, by_maturity: { STABLE: 1, LEARNING: 1 },
};

const LOGS = {
    student_id: 1,
    logs: [{
        id: 1, subject: "数学", knowledge: "表内乘法", old_interval: 14, new_interval: 32,
        old_stability: 21, new_stability: 40.1, quality: "EASY",
        reason: "非常容易：阶梯推进到 32 天（第 1 次复习成功）", source: "review",
        created_time: "2026-10-10 09:00",
    }],
    history: { total: 1, by_quality: { EASY: 1 }, items: [] },
    today_mix: { review_ratio: 0.2, new_learning_ratio: 0.5, weakness_ratio: 0.3 },
    interval_ladder: [1, 3, 7, 14, 30],
    quality_text: { AGAIN: "完全忘记", HARD: "想了很久", GOOD: "正常想起来", EASY: "非常容易" },
};

function route(url) {
    if (url.includes("/students")) {
        return [{ id: 1, name: "小朋友A", grade_text: "一年级" },
                { id: 2, name: "小朋友B", grade_text: "一年级" }];
    }
    if (url.includes("/api/review/today/")) return TODAY;
    if (url.includes("/api/review/question")) return QUESTION;
    if (url.includes("/api/review/answer")) return ANSWER;
    if (url.includes("/api/review/feedback")) return FEELBACK;
    if (url.includes("/api/review/memory-map/")) return MAP;
    if (url.includes("/api/review/stats/")) return STATS;
    if (url.includes("/api/review/strategy-log/")) return LOGS;
    return undefined;
}

/* ---------------- 4. 儿童端纯函数 ---------------- */

const reviewLoaded = loadModule("review.html", "review.js", route, [
    "childMaturity: typeof childMaturity === 'function' ? childMaturity : null",
    "forestIcon: typeof forestIcon === 'function' ? forestIcon : null",
    "remainingCount: typeof remainingCount === 'function' ? remainingCount : null",
    "gardenTitle: typeof gardenTitle === 'function' ? gardenTitle : null",
    "nextWaterText: typeof nextWaterText === 'function' ? nextWaterText : null",
    "feelButtonsHtml: typeof feelButtonsHtml === 'function' ? feelButtonsHtml : null",
    "renderGarden: typeof renderGarden === 'function' ? renderGarden : null",
    "startReview: typeof startReview === 'function' ? startReview : null",
    "submitAnswer: typeof submitAnswer === 'function' ? submitAnswer : null",
    "sendFeel: typeof sendFeel === 'function' ? sendFeel : null",
].join(","));
const reviewApi = reviewLoaded.api;

check("成熟度：稳定掌握 → 🌳 记得很牢", reviewApi.childMaturity("STABLE") === "🌳 记得很牢",
    reviewApi.childMaturity("STABLE"));
check("成熟度：长期掌握 → ⭐ 长期掌握", reviewApi.childMaturity("LONG_TERM") === "⭐ 长期掌握",
    reviewApi.childMaturity("LONG_TERM"));
check("成熟度：儿童文案没有英文",
    !/[A-Za-z]/.test(Object.values({ NEW: reviewApi.childMaturity("NEW"),
                                     LEARNING: reviewApi.childMaturity("LEARNING"),
                                     SHORT_TERM: reviewApi.childMaturity("SHORT_TERM"),
                                     CONSOLIDATING: reviewApi.childMaturity("CONSOLIDATING") }).join("")),
    reviewApi.childMaturity("CONSOLIDATING"));
check("森林图标：长期掌握 → ⭐", reviewApi.forestIcon("LONG_TERM") === "⭐");
check("还需要浇水的数量", reviewApi.remainingCount(TODAY) === 2,
    reviewApi.remainingCount(TODAY));
check("完成一个后剩一个",
    reviewApi.remainingCount({ items: [{ status: "COMPLETED" }, { status: "PENDING" }] }) === 1);
check("标题：说几个知识需要照顾",
    reviewApi.gardenTitle(TODAY).includes("2 个知识需要照顾"), reviewApi.gardenTitle(TODAY));
check("标题：没有任务时说今天不用复习",
    reviewApi.gardenTitle({ total: 0, items: [] }).includes("没有知识需要复习"),
    reviewApi.gardenTitle({ total: 0, items: [] }));
check("标题：全部完成时给完成祝贺",
    reviewApi.gardenTitle({ total: 2, items: [{ status: "COMPLETED" }, { status: "COMPLETED" }] })
        .includes("照顾好啦"));
check("下次浇水：32 天 → 大约 32 天后再来",
    reviewApi.nextWaterText({ next_interval: 32 }).includes("32 天"),
    reviewApi.nextWaterText({ next_interval: 32 }));
check("下次浇水：不足一天 → 等会儿再复习",
    reviewApi.nextWaterText({ next_interval: 0.5 }).includes("等会儿"),
    reviewApi.nextWaterText({ next_interval: 0.5 }));
check("四个感受按钮", (reviewApi.feelButtonsHtml().match(/feel-btn/g) || []).length === 4,
    reviewApi.feelButtonsHtml());
check("儿童端卡片不显示遗忘风险百分比",
    !reviewApi.renderGarden(TODAY).includes("遗忘风险")
    && !reviewApi.renderGarden(TODAY).includes("稳定性"), "ok");
check("儿童端卡片显示树的成长状态与知识点",
    reviewApi.renderGarden(TODAY).includes("表内乘法")
    && reviewApi.renderGarden(TODAY).includes("记得很牢"), "ok");
check("儿童端提示需要重新种的知识",
    reviewApi.renderGarden(TODAY).includes("重新种"), "ok");

/* ---------------- 5. 家长端纯函数 ---------------- */

const debugLoaded = loadModule("memory_debug.html", "memory_debug.js", route, [
    "riskClass: typeof riskClass === 'function' ? riskClass : null",
    "riskText: typeof riskText === 'function' ? riskText : null",
    "intervalText: typeof intervalText === 'function' ? intervalText : null",
    "renderTable: typeof renderTable === 'function' ? renderTable : null",
    "renderStats: typeof renderStats === 'function' ? renderStats : null",
    "renderQueue: typeof renderQueue === 'function' ? renderQueue : null",
    "renderLogs: typeof renderLogs === 'function' ? renderLogs : null",
].join(","));
const debugApi = debugLoaded.api;

check("风险分级样式：高风险", debugApi.riskClass(0.8) === "risk-high", debugApi.riskClass(0.8));
check("风险分级样式：中风险", debugApi.riskClass(0.5) === "risk-mid", debugApi.riskClass(0.5));
check("风险分级样式：低风险", debugApi.riskClass(0.1) === "risk-low", debugApi.riskClass(0.1));
check("风险文案：高", debugApi.riskText(0.8).includes("快忘了"), debugApi.riskText(0.8));
check("风险文案：低", debugApi.riskText(0.1).includes("还记得"), debugApi.riskText(0.1));
check("间隔显示：21 天", debugApi.intervalText(21) === "21 天", debugApi.intervalText(21));
check("间隔显示：0.5 天 → 小时", debugApi.intervalText(0.5).includes("小时"),
    debugApi.intervalText(0.5));
check("表格显示真实指标（掌握度 / 稳定性 / 遗忘风险）",
    ["掌握度", "稳定性", "遗忘风险", "成熟度"].every(token =>
        debugApi.renderTable(MAP).includes(token)), "ok");
check("表格标出需要重新学的知识点",
    debugApi.renderTable(MAP).includes("需要重新学"), "ok");
check("空数据时给出提示",
    debugApi.renderTable({ items: [] }).includes("还没有记忆数据"), "ok");
check("统计卡片含今日复习与即将遗忘",
    debugApi.renderStats(STATS, MAP).includes("今日复习")
    && debugApi.renderStats(STATS, MAP).includes("即将遗忘"), "ok");
check("队列显示优先级与计划题量",
    debugApi.renderQueue(TODAY).includes("P0") && debugApi.renderQueue(TODAY).includes("计划 3 题"),
    "ok");
check("日志显示间隔变化与原因",
    debugApi.renderLogs(LOGS).includes("阶梯推进"), "ok");

/* ---------------- 6. 儿童端流程 ---------------- */

async function flow() {
    await sleep(20);

    check("初始化后填充学生下拉",
        reviewLoaded.nodes.student.innerHTML.includes("小朋友A"), "ok");
    check("初始化后渲染浇水标题",
        reviewLoaded.nodes["garden-head"].innerHTML.includes("需要照顾"), "ok");
    check("初始化后渲染知识卡片",
        reviewLoaded.nodes.garden.innerHTML.includes("表内乘法")
        && reviewLoaded.nodes.garden.innerHTML.includes("两步计算应用题"), "ok");
    check("初始化调用今日复习接口",
        reviewLoaded.calls.some(call => call.url.includes("/api/review/today/1")), "ok");

    reviewApi.startReview("数学", "表内乘法");
    await sleep(20);

    check("开始复习会请求复习题",
        reviewLoaded.calls.some(call => call.url.includes("/api/review/question")
            && call.url.includes("knowledge_id=")), "ok");
    check("渲染复习题与选项",
        reviewLoaded.nodes.question.innerHTML.includes("7 × 8")
        && reviewLoaded.nodes.options.innerHTML.includes("56"), "ok");
    check("显示这是复习题（换数字再考一次）",
        reviewLoaded.nodes["memory-badge"].innerHTML.includes("复习题"), "ok");

    reviewApi.submitAnswer("B", null);
    await sleep(20);

    check("提交答案会调用复习作答接口",
        reviewLoaded.calls.some(call => call.url.includes("/api/review/answer")), "ok");
    check("作答请求带 response_time",
        reviewLoaded.calls.some(call => call.url.includes("/api/review/answer")
            && call.options.body.includes("response_time")), "ok");
    check("显示复习成功与鼓励文案",
        reviewLoaded.nodes.result.innerHTML.includes("✓ 对啦")
        && reviewLoaded.nodes.result.innerHTML.includes("记得非常牢"), "ok");
    check("显示下次浇水时间（儿童化）",
        reviewLoaded.nodes.result.innerHTML.includes("天后再来浇水"), "ok");
    check("作答后询问感受",
        reviewLoaded.nodes["feel-box"].innerHTML.includes("😊 简单")
        && reviewLoaded.nodes["feel-box"].innerHTML.includes("😵 不会"), "ok");

    reviewApi.sendFeel("easy");
    await sleep(20);

    check("感受反馈走单独的反馈接口（不重复判分）",
        reviewLoaded.calls.some(call => call.url.includes("/api/review/feedback")), "ok");
    check("反馈请求带上感受",
        reviewLoaded.calls.some(call => call.url.includes("/api/review/feedback")
            && call.options.body.includes('"feel":"easy"')), "ok");
    check("感受不影响作答次数（answer 只调用一次）",
        reviewLoaded.calls.filter(call => call.url.includes("/api/review/answer")).length === 1,
        reviewLoaded.calls.filter(call => call.url.includes("/api/review/answer")).length);

    /* 家长端流程 */
    await sleep(20);
    check("家长端渲染记忆表格",
        debugLoaded.nodes["memory-table"].innerHTML.includes("表内乘法"), "ok");
    check("家长端显示遗忘风险百分比",
        debugLoaded.nodes["memory-table"].innerHTML.includes("遗忘风险 20%"), "ok");
    check("家长端渲染今日队列",
        debugLoaded.nodes["queue-box"].innerHTML.includes("P0"), "ok");
    check("家长端渲染算法日志",
        debugLoaded.nodes["log-box"].innerHTML.includes("阶梯推进"), "ok");
    check("家长端渲染统计卡片",
        debugLoaded.nodes["stats-box"].innerHTML.includes("长期掌握"), "ok");

    console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
    process.exit(ok ? 0 : 1);
}

flow();
