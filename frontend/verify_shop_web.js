// ==============================================================
// 能力契约｜验证：积分商城页（shop.js / shop.html）
// 入口：脚本自身：node frontend/verify_shop_web.js
// 依赖：Node fs/path/vm（沙箱加载 ui-shell.js + kid-lang.js + ui-components.js + shop.js）
// 不负责：积分明细的分值口径（第一版奖励行为表）→ backend/points_rewards.py，由
//         `python backend/verify_points.py` 覆盖；真实兑换（比例占位，不实装）
// 验证：node frontend/verify_shop_web.js
// 被调用：verify_all.py（套件 shopweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 「🛍️ 积分商城」页测试（挑战下方新增的一级页）。
 *
 * 覆盖：页面结构（容器 / 脚本顺序 / mountNav("shop")）、一级导航 5 项且商城紧跟挑战之后、
 *       星级与分值文案纯函数、积分明细三态徽标、商品「还差 N 分」、流水空态与有数据、
 *       余额卡打卡按钮、渲染流程真的把数据填进容器、没有兑换按钮 / 没有沉迷型用语。
 *
 * 用法：node frontend/verify_shop_web.js
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

const shopHtml = readFile("shop.html");
const shopJs = readFile("shop.js");
const shellJs = readFile("ui-shell.js");
const styleCss = readFile("style.css");

/* ---------------- 1. 页面结构 ---------------- */

check("shop.html 引用了 shop.js", shopHtml.includes('src="shop.js"'));
check("shop.html 引用了 style.css", shopHtml.includes('href="style.css"'));
check("shop.html 挂了共享 UI 层（三脚本齐全）",
    shopHtml.includes('src="ui-shell.js"') && shopHtml.includes('src="kid-lang.js"')
    && shopHtml.includes('src="ui-components.js"'));
check("共享 UI 层排在业务 js 之前",
    shopHtml.indexOf('src="ui-shell.js"') < shopHtml.indexOf('src="shop.js"')
    && shopHtml.indexOf('src="ui-components.js"') < shopHtml.indexOf('src="shop.js"'));
check("商城页挂在一级导航里（mountNav(\"shop\")，不是另起菜单）",
    shopHtml.includes('mountNav("shop")') && shopHtml.includes("ShopPage.init()"));

check("商城页有余额 / 商品 / 明细 / 流水四个容器",
    ["shop-status", "shop-balance", "shop-goods", "shop-rewards", "shop-records", "shop-note"]
        .every(id => shopHtml.includes('id="' + id + '"')));

// shop.js 用到的元素必须都在页面里（防"改 id 忘了改页面"）
(function idCrossCheck() {
    const ids = new Set([...shopHtml.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
    const used = [...shopJs.matchAll(/\$\("([^"]+)"\)/g)].map(m => m[1]);
    const missing = [...new Set(used)].filter(id => !ids.has(id));
    check("shop.js 用到的元素都存在于页面", missing.length === 0, missing.join(", "));
})();

check("商城页明细文案来自后端（前端不写死分值口径）",
    !/首次真正掌握|\+100|Deep Mastery/.test(shopJs));
check("商城页没有兑换按钮 / 没有沉迷型入口",
    !/兑换按钮|doExchange|exchange\(|抽奖|再来一题|额外奖励|加练|排行榜/.test(shopHtml + shopJs));
check("商城页只读积分接口（不新增后端写接口；登录奖励走 /login）",
    shopJs.includes("/api/points/") && shopJs.includes("/login"));
check("商城页自己不做加法（不出现前端加分数值）",
    !/balance\s*[+-]=\s*\d|points\s*\+\s*\d/.test(shopJs));

/* ---------------- 2. 一级导航：商城紧跟挑战之后 ---------------- */

(function navCase() {
    const tabs = [...shellJs.matchAll(/tab:\s*"([a-z]+)",\s*icon:\s*"[^"]*",\s*label:\s*"([^"]+)",\s*href:\s*"([a-z_]+\.html)"/g)]
        .map(m => ({ tab: m[1], label: m[2], href: m[3] }));
    check("一级导航 5 项：今天 / 成长 / 挑战 / 商城 / 我的",
        tabs.map(t => t.tab).join(",") === "today,growth,wrong,shop,profile",
        tabs.map(t => t.tab).join(","));
    const wrong = tabs.findIndex(t => t.tab === "wrong");
    const shop = tabs.findIndex(t => t.tab === "shop");
    check("商城就挂在「挑战」下方（紧邻后一项）", shop === wrong + 1, `wrong=${wrong} shop=${shop}`);
    check("商城入口指向真实存在的 shop.html", (tabs.find(t => t.tab === "shop") || {}).href === "shop.html"
        && fs.existsSync(path.join(DIR, "shop.html")));
})();

check("底部导航给 5 个一级项留位（grid 五列）",
    /\.ph-nav--bottom\{[^}]*/.test(styleCss)
    && /grid-template-columns:repeat\(5,1fr\)/.test(styleCss));
check("商城明细 / 商品样式已进全站样式表",
    styleCss.includes(".points-row") && styleCss.includes(".shop-item")
    && styleCss.includes('.points-row[data-state="live"]'));

/* ---------------- 3. DOM / fetch 打桩 ---------------- */

const nodes = {};
const attrs = {};

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
            toggle() { return false; },
            contains() { return false; },
        },
    };
    nodes[id] = node;
    return node;
}

[...shopHtml.matchAll(/id="([^"]+)"/g)].forEach(m => makeNode(m[1]));

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
    body: { classList: { add() {}, remove() {}, toggle() { return false; }, contains() { return false; } } },
    readyState: "complete",
    getElementById(id) { return nodes[id] || null; },
    createElement: makeNode,
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
};

/* 后端 /api/points/{id} 的真实返回结构（含第一版奖励行为明细） */
const REWARDS = [
    { key: "first_mastery", label: "首次真正掌握一个知识点", points_min: 100, points_max: 100,
        stars: 5, note: "最核心学习成果", state: "planned", event: "" },
    { key: "transfer_question", label: "综合迁移题成功", points_min: 60, points_max: 80,
        stars: 5, note: "检验真实理解", state: "planned", event: "" },
    { key: "answer_correct", label: "普通适龄题独立答对", points_min: 2, points_max: 5,
        stars: 2, note: "即时反馈，但不能成为主要积分来源", state: "live", event: "answer_correct" },
    { key: "screen_time", label: "停留、点击、刷页面", points_min: 0, points_max: 0,
        stars: 0, note: "绝不奖励屏幕时间", state: "never", event: "" },
];

const POINTS = {
    student_id: 1, date: "2026-10-05", balance: 128, total_earned: 300,
    today_points: 14, today_count: 3, checked_in: false, streak: 2,
    rules: [
        { event: "answer_correct", label: "答对一题", points: 2 },
        { event: "daily_checkin", label: "每日打卡", points: 10 },
        { event: "free_practice", label: "计划做完后继续练", points: 3 },
        { event: "task_done", label: "一项任务收工", points: 5 },
        { event: "daily_login", label: "每日首次登录", points: 10 },
    ],
    rewards: REWARDS,
    reward_version: "第一版",
    reward_states: { live: "✅ 已经在记分", planned: "🔜 先给你看规则", never: "🚫 永不给分" },
    shop: {
        enabled: false, note: "兑换比例先占位，兑换功能还没实装",
        items: [
            { key: "ipad_time", emoji: "📱", label: "iPad 使用时间 30 分钟", cost: 200, note: "和家长约定好时间", affordable: false },
            { key: "toy_20", emoji: "🧸", label: "20 元以下小玩具", cost: 400, note: "占位价", affordable: false },
        ],
    },
    records: [
        { date: "2026-10-05", event: "answer_correct", label: "答对一题", points: 2, note: "数学 两位数乘法", time: "10-05 09:12" },
        { date: "2026-10-05", event: "daily_checkin", label: "每日打卡", points: 10, note: "今天第一次答对题", time: "10-05 09:12" },
    ],
};

const calls = [];

function jsonResponse(data) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
}

function fakeFetch(url) {
    calls.push(String(url));
    if (String(url).endsWith("/students")) {
        return jsonResponse([
            { id: 1, name: "朵朵", grade: 1, grade_text: "一年级" },
            { id: 2, name: "童童", grade: 4, grade_text: "四年级" },
        ]);
    }
    if (String(url).includes("/api/points/")) return jsonResponse(POINTS);
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
}

const sandbox = {
    document: documentStub,
    fetch: fakeFetch,
    console,
    Math, Number, String, Boolean, Array, Object, JSON, isFinite,
    parseInt, parseFloat, Promise, Error, setTimeout, clearTimeout,
    location: { protocol: "http:", origin: "http://127.0.0.1:8000", href: "" },
    localStorage: {
        store: {},
        getItem(k) { return this.store[k] === undefined ? null : this.store[k]; },
        setItem(k, v) { this.store[k] = String(v); },
    },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
["ui-shell.js", "kid-lang.js", "ui-components.js"].forEach(name => {
    vm.runInContext(readFile(name), sandbox, { filename: name });
});
check("共享 UI 层三脚本都已加载",
    !!(sandbox.UIShell && sandbox.KidLang && sandbox.UIComponents));

vm.runInContext(shopJs, sandbox, { filename: "shop.js" });
const ShopPage = sandbox.ShopPage;
check("shop.js 导出 ShopPage", !!ShopPage && typeof ShopPage.loadShop === "function");

/* ---------------- 4. 纯函数：星级与分值文案 ---------------- */

check("五星满档 = ★★★★★", ShopPage.starsText(5) === "★★★★★", ShopPage.starsText(5));
check("四星 = ★★★★☆", ShopPage.starsText(4) === "★★★★☆", ShopPage.starsText(4));
check("没星的条目给横线（不假装有星）", ShopPage.starsText(0) === "—", ShopPage.starsText(0));
check("分值单点 = +100", ShopPage.pointsText({ points_min: 100, points_max: 100 }) === "+100");
check("分值区间 = +60~80", ShopPage.pointsText({ points_min: 60, points_max: 80 }) === "+60~80");
check("零分条目 = 0 分（不是 +0）", ShopPage.pointsText({ points_min: 0, points_max: 0 }) === "0 分");

/* ---------------- 5. 渲染：明细 / 商品 / 流水 / 余额 ---------------- */

(function rewardsCase() {
    const html = ShopPage.renderRewards(POINTS);
    check("明细列出后端给的每一条（不写死条数）",
        (html.match(/class="points-row"/g) || []).length === REWARDS.length,
        (html.match(/class="points-row"/g) || []).length);
    check("明细带星级 + 规则名 + 分值 + 为什么给分",
        html.includes("★★★★★") && html.includes("首次真正掌握一个知识点")
        && html.includes("+100") && html.includes("最核心学习成果"));
    check("区间分值与单点分值都按后端口径显示",
        html.includes("+60~80") && html.includes("+2~5"));
    check("三种状态都有徽标（✅ 已经在记分 / 🔜 先给你看规则 / 🚫 永不给分）",
        html.includes("✅ 已经在记分") && html.includes("🔜 先给你看规则")
        && html.includes("🚫 永不给分"));
    check("明细标出规则版本", html.includes("第一版"));
    check("明细里不出现裸算法指标",
        !/mastery_score|forgetting_risk|stability|interval_days/.test(html));

    const empty = ShopPage.renderRewards({});
    check("明细为空时给儿童友好空态（不是空白）", empty.includes("积分明细"), empty.slice(0, 60));
})();

(function goodsCase() {
    const html = ShopPage.renderGoods(POINTS);
    check("商品列出后端给的每一件", html.includes("iPad 使用时间 30 分钟") && html.includes("20 元以下小玩具"));
    check("商品显示价格与「还差 N 分」（余额 128）",
        html.includes("200 积分") && html.includes("还差 72 分"), html.match(/还差[^<]*/));
    check("攒够了的商品说「已经攒够啦」",
        ShopPage.renderGoods({ balance: 500, shop: POINTS.shop }).includes("已经攒够啦"));
    check("商品区没有兑换按钮（比例先占位，不实装）",
        !/兑换|button/i.test(html), html.slice(0, 80));
})();

(function recordsCase() {
    const html = ShopPage.renderRecords(POINTS);
    check("流水显示分值 + 事件名 + 时间",
        html.includes("+2 答对一题") && html.includes("+10 每日打卡") && html.includes("10-05 09:12"));
    check("没有流水时给儿童友好空态", ShopPage.renderRecords({}).includes("还没有挣到积分"));
})();

(function balanceCase() {
    const before = ShopPage.renderBalance(POINTS);
    check("没有手动打卡按钮：小任务做完，打卡自己就来",
        before.includes("做完今天的小任务") && !before.includes("doCheckin"));
    check("余额卡显示余额 / 今天获得 / 现在正在记的日常分",
        before.includes("128") && before.includes("今天 +14")
        && before.includes("答对一题 +2") && before.includes("每日首次登录 +10")
        && before.includes("一项任务收工 +5"));
    const after = ShopPage.renderBalance(Object.assign({}, POINTS, { checked_in: true }));
    check("打过卡就不再显示打卡按钮，改成「今天已打卡 · 连续 N 天」",
        after.includes("今天已打卡") && after.includes("连续 2 天") && !after.includes("doCheckin"));
})();

/* ---------------- 6. 跑一遍 init：数据真的会填进容器 ---------------- */

if (ShopPage && typeof ShopPage.init === "function") {
    ShopPage.init();
}

setTimeout(function () {
    const balance = nodes["shop-balance"] ? String(nodes["shop-balance"].innerHTML || "") : "";
    const goods = nodes["shop-goods"] ? String(nodes["shop-goods"].innerHTML || "") : "";
    const rewards = nodes["shop-rewards"] ? String(nodes["shop-rewards"].innerHTML || "") : "";
    const records = nodes["shop-records"] ? String(nodes["shop-records"].innerHTML || "") : "";
    const status = nodes["shop-status"] ? String(nodes["shop-status"].innerHTML || "") : "";

    check("渲染流程把余额填进余额卡", balance.includes("128"), balance.slice(0, 90));
    check("渲染流程把商品填进商品区", goods.includes("iPad 使用时间 30 分钟"));
    check("渲染流程把积分明细填进明细区",
        rewards.includes("首次真正掌握一个知识点") && rewards.includes("+100"));
    check("渲染流程把流水填进流水区", records.includes("+10 每日打卡"));
    check("加载成功后清空 loading 状态", status === "", status.slice(0, 80));
    check("打开商城页会顺手领每日首次登录奖励（POST /login）",
        calls.some(u => /\/api\/points\/1\/login$/.test(u)), calls.join(" , "));
    check("只请求当前学生的积分接口",
        calls.some(u => /\/api\/points\/1$/.test(u)), calls.join(" , "));
    check("页面里没有出现「兑换」按钮或沉迷型引导",
        !/兑换|再来一题|额外奖励|加练/.test(balance + goods + rewards + records));

    console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
    process.exit(ok ? 0 : 1);
}, 80);
