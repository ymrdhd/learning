// ==============================================================
// 能力契约｜验证：成长页与我的页（growth.js / growth.html、profile.js / profile.html）
// 入口：脚本自身：node frontend/verify_growth_profile_web.js
// 依赖：Node fs/path/vm（沙箱加载 ui-shell.js + kid-lang.js + ui-components.js + 页面 js）
// 不负责：成长口径计算 → backend/habit.py、backend/knowledge_routes.py
// 验证：node frontend/verify_growth_profile_web.js
// 被调用：verify_all.py（套件 growthweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 「成长」页与「我的」页前端测试。
 *
 * 覆盖：页面结构、生命周期脚本齐全、儿童可见文案（无裸算法指标 / 无做题总量主指标）、
 *       四格周成长、知识地图真实领域、我的页只留儿童设置项、二次确认切换学生、四导航指向真实页面。
 *
 * 用法：node frontend/verify_growth_profile_web.js
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

const growthHtml = readFile("growth.html");
const growthJs = readFile("growth.js");
const profileHtml = readFile("profile.html");
const profileJs = readFile("profile.js");
const shellJs = readFile("ui-shell.js");
const langJs = readFile("kid-lang.js");
const compJs = readFile("ui-components.js");

/* ---------------- 1. 页面结构 ---------------- */

check("growth.html 引用了 growth.js", growthHtml.includes('src="growth.js"'));
check("growth.html 引用了 style.css", growthHtml.includes('href="style.css"'));
check("growth.html 挂了共享 UI 层", growthHtml.includes('src="ui-shell.js"')
    && growthHtml.includes('src="kid-lang.js"') && growthHtml.includes('src="ui-components.js"'));
check("profile.html 引用了 profile.js", profileHtml.includes('src="profile.js"'));
check("profile.html 引用了 style.css", profileHtml.includes('href="style.css"'));

function idCrossCheck(html, js, label) {
    const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
    const used = [...js.matchAll(/\$\("([^"]+)"\)/g)].map(m => m[1]);
    const missing = [...new Set(used)].filter(id => !ids.has(id));
    check(`${label} 用到的元素都存在于页面`, missing.length === 0, missing.join(", "));
}

idCrossCheck(growthHtml, growthJs, "growth.js");
idCrossCheck(profileHtml, profileJs, "profile.js");

check("成长页只读既有接口（不新增后端字段）",
    growthJs.includes("/api/habit/stats") && growthJs.includes("/api/mastery/")
    && growthJs.includes("/api/recovery/list/") && growthJs.includes("/api/habit/calendar"));

/* ---------------- 2. DOM / fetch 打桩 ---------------- */

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

function collectIds(html) {
    [...html.matchAll(/id="([^"]+)"/g)].forEach(m => makeNode(m[1]));
}

collectIds(growthHtml);
collectIds(profileHtml);

const documentElement = {
    dataset: {},
    style: {},
    attrs: attrs,
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

const HABIT = {
    student_id: 1, days: 7, avg_rate: 0.5, total_minutes: 42,
    items: [
        { date: "2026-09-29", done: 2, total: 3, minutes: 12, rate: 0.67 },
        { date: "2026-09-30", done: 0, total: 0, minutes: 0, rate: 0 },
        { date: "2026-10-01", done: 3, total: 3, minutes: 15, rate: 1 },
        { date: "2026-10-02", done: 1, total: 3, minutes: 6, rate: 0.33 },
        { date: "2026-10-03", done: 3, total: 3, minutes: 18, rate: 1 },
        { date: "2026-10-04", done: 2, total: 3, minutes: 11, rate: 0.67 },
        { date: "2026-10-05", done: 3, total: 3, minutes: 14, rate: 1 },
    ],
};

const MASTERY = {
    student_id: 1,
    subject: "数学",
    subjects: ["数学", "语文", "英语"],
    summary: { knowledge_count: 24, practiced: 8, mastered: 4, learning: 3, weak: 1, average_mastery: 68.5 },
    domains: [
        { domain: "数与代数", mastery_score: 82, stars: 4, star_text: "★★★★☆", knowledge_count: 6, practiced_count: 4, children: [] },
        { domain: "图形与几何", mastery_score: 55, stars: 3, star_text: "★★★☆☆", knowledge_count: 5, practiced_count: 2, children: [] },
        { domain: "应用题", mastery_score: 45, stars: 2, star_text: "★★☆☆☆", knowledge_count: 5, practiced_count: 2, children: [] },
    ],
};

const RECOVERY = { student_id: 1, total: 9, stats: { new: 1, analyzing: 1, mastered: 8, total: 9, mastered_rate: 0.8 }, items: [] };

const calls = [];

function jsonResponse(data) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
}

const CALENDAR = {
    student_id: 1, month: "2026-10", first_weekday: 3, days_in_month: 31,
    checked_count: 2, today: "2026-10-05",
    items: [
        { date: "2026-10-01", day: 1, checked: true, done: 3, total: 9, minutes: 15, is_today: false, is_future: false },
        { date: "2026-10-02", day: 2, checked: false, done: 0, total: 0, minutes: 0, is_today: false, is_future: false },
        { date: "2026-10-05", day: 5, checked: true, done: 2, total: 9, minutes: 8, is_today: true, is_future: false },
        { date: "2026-10-06", day: 6, checked: false, done: 0, total: 0, minutes: 0, is_today: false, is_future: true },
    ],
};

function fakeFetch(url) {
    calls.push(String(url));
    if (String(url).endsWith("/students")) {
        return jsonResponse([
            { id: 1, name: "朵朵", grade: 1, grade_text: "一年级" },
            { id: 2, name: "童童", grade: 4, grade_text: "四年级" },
        ]);
    }
    if (String(url).includes("/api/habit/stats")) return jsonResponse(HABIT);
    if (String(url).includes("/api/mastery/")) return jsonResponse(MASTERY);
    if (String(url).includes("/api/recovery/list/")) return jsonResponse(RECOVERY);
    if (String(url).includes("/api/habit/calendar")) return jsonResponse(CALENDAR);
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
}

const sandbox = {
    document: documentStub,
    fetch: fakeFetch,
    console,
    Math,
    Number,
    String,
    Boolean,
    Array,
    Object,
    JSON,
    isFinite,
    parseInt,
    parseFloat,
    Promise,
    Error,
    setTimeout,
    clearTimeout,
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

vm.runInContext(growthJs, sandbox, { filename: "growth.js" });
vm.runInContext(profileJs, sandbox, { filename: "profile.js" });

const GrowthPage = sandbox.GrowthPage;
const ProfilePage = sandbox.ProfilePage;

check("growth.js 导出 GrowthPage", !!(GrowthPage && typeof GrowthPage.init === "function"
    && typeof GrowthPage.renderSummary === "function" && typeof GrowthPage.renderMap === "function"));
check("profile.js 导出 ProfilePage", !!(ProfilePage && typeof ProfilePage.init === "function"
    && typeof ProfilePage.renderProfile === "function" && typeof ProfilePage.renderSettings === "function"));

/* ---------------- 3. 成长页文案与数据 ---------------- */

const summaryHtml = GrowthPage ? GrowthPage.renderSummary({
    days: 6, mastered: 4, wrongFixed: 8, learning: 3,
}) : "";

check("成长页出现四项周成长",
    ["本周学习", "已经掌握", "攻克错题", "还在变熟"].every(k => summaryHtml.includes(k)),
    summaryHtml.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
check("成长页不出现裸算法指标",
    !/掌握度\s*\d|稳定性|遗忘风险\s*\d|Mastery|Stability/i.test(summaryHtml));
check("成长页不以做题总量为主指标", !/完成\s*\d+\s*题/.test(summaryHtml));
check("成长页数字来自接口（6 天 / 4 个 / 8 道 / 3 个）",
    summaryHtml.includes(">6<") && summaryHtml.includes(">4<")
    && summaryHtml.includes(">8<") && summaryHtml.includes(">3<"));

const mapHtml = GrowthPage ? GrowthPage.renderMap(MASTERY.domains) : "";
check("成长页知识地图显示真实领域名",
    mapHtml.includes("数与代数") && mapHtml.includes("应用题") && mapHtml.includes("图形与几何"));
check("成长页知识地图不含裸掌握度数字", !/掌握度\s*\d/.test(mapHtml));

const calHtml = GrowthPage ? GrowthPage.renderCalendar(CALENDAR) : "";
check("学习日历有星期表头与格子",
    calHtml.includes("ph-cal-grid") && calHtml.includes("ph-cal-head")
    && (calHtml.match(/ph-cal-cell/g) || []).length >= 7, calHtml.slice(0, 90));
check("打卡的日子亮起来、今天有标记",
    calHtml.includes("is-checked") && calHtml.includes("is-today")
    && calHtml.includes("☀️"));
check("学习日历显示本月已打卡天数", calHtml.includes("已经打卡") && calHtml.includes(">2<"));
check("学习日历给每个格子写了可读说明",
    calHtml.includes("完成 3 个小任务") && calHtml.includes("还没有完成"));
const calEmptyHtml = GrowthPage ? GrowthPage.renderCalendar(null) : "";
check("学习日历空数据是儿童文案",
    calEmptyHtml.includes("还没有记录") && !/No data|无数据/i.test(calEmptyHtml));

const emptyHtml = GrowthPage ? GrowthPage.renderSummary({ empty: true }) : "";
check("成长页空状态是儿童文案", emptyHtml.includes("成长") && !/No data|无数据/i.test(emptyHtml));

/* ---------------- 4. 我的页只留儿童设置 ---------------- */

const profileText = ProfilePage
    ? ProfilePage.renderProfile({ id: 1, name: "朵朵", grade: 1, grade_text: "一年级" })
        + ProfilePage.renderSettings({ sound: true, reduceMotion: false, fontScale: 1, focusMode: false })
    : "";
const profilePlain = profileText.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

check("我的页只保留儿童设置项",
    ["切换学生", "声音", "显示", "减少动画"].every(k => profilePlain.includes(k)), profilePlain);
check("我的页不含任何密钥或技术配置",
    !/API\s*Key|api_key|数据库|DATABASE|mastery_threshold|debug/i.test(profilePlain));
check("我的页不出现 DeepSeek 字样", !/DeepSeek/i.test(profilePlain));
check("我的页没有算法参数项",
    !/阈值|遗忘风险|稳定性|遗忘曲线|间隔复习参数/.test(profilePlain));

/* ---------------- 4.5 家长操作：备份并重置 ---------------- */

check("我的页挂出家长操作区", profileHtml.includes('id="profile-data"'));
check("家长操作区标题写着是家长的事", profileHtml.includes("家长操作"));

const dataHtml = (ProfilePage && typeof ProfilePage.renderDataSection === "function")
    ? ProfilePage.renderDataSection({ id: 1, name: "朵朵" },
        { total: 12, tables: { answer_records: 8, abilities: 1, wrong_questions: 3 } })
    : "";
const dataPlain = dataHtml.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

check("说明会先备份再清空、且不影响另一个小朋友",
    dataPlain.includes("备份") && dataPlain.includes("清空") && dataPlain.includes("不受影响"),
    dataPlain);
check("会先把要清空的条数与类别说清楚",
    dataPlain.includes("12") && dataPlain.includes("答题记录") && dataPlain.includes("错题"));
check("按钮写明是备份并重置", dataHtml.includes("备份并重置"));
check("重置必须二次确认（有取消与确认两条路）",
    typeof ProfilePage.confirmReset === "function"
    && profileJs.includes('data-confirm="yes"') && profileJs.includes('data-confirm="no"')
    && profileJs.includes("再想想"));
check("重置走 /api/user 的预览与重置接口",
    profileJs.includes("/api/user/") && profileJs.includes("/reset-preview")
    && profileJs.includes('"/reset"'));
check("重置结果会说清备份文件名与清空条数",
    profileJs.includes("backup_file") && profileJs.includes("total_cleared"));
check("家长操作区不出现密钥或算法参数",
    !/API\s*Key|api_key|mastery_threshold|遗忘风险/i.test(dataPlain));

/* ---------------- 5. 状态与导航 ---------------- */

check("我的页切换学生走共享组件（带二次确认）",
    profileJs.includes("createStudentSwitcher") && !/UIShell\.setStudentId\(/.test(profileJs));

check("四个导航项都指向真实页面", (function () {
    const hrefs = [...shellJs.matchAll(/file:\s*"([a-z_]+\.html)"/g)].map(m => m[1]);
    const tabs = [...shellJs.matchAll(/href:\s*"([a-z_]+\.html)"/g)].map(m => m[1]);
    const all = [...new Set(hrefs.concat(tabs))];
    if (all.length < 4) return false;
    return all.every(name => fs.existsSync(path.join(DIR, name)));
})(), [...shellJs.matchAll(/href:\s*"([a-z_]+\.html)"/g)].map(m => m[1]).join(", "));

check("分龄属性影响成长页", (function () {
    sandbox.UIShell.applyAgeMode(1);
    const junior = documentElement.dataset.ageMode === "junior";
    sandbox.UIShell.applyAgeMode(5);
    const senior = documentElement.dataset.ageMode === "senior";
    return junior && senior;
})(), documentElement.dataset.ageMode);

check("成长页与我的页都挂在一级导航里（不是新增菜单）",
    growthHtml.includes('mountNav("growth")') && profileHtml.includes('mountNav("profile")'));

/* ---------------- 6. 家长操作区真的会被渲染（跑一遍 init 流程） ---------------- */

if (ProfilePage && typeof ProfilePage.init === "function") {
    ProfilePage.init();
}

setTimeout(function () {
    const box = nodes["profile-data"];
    const html = box ? String(box.innerHTML || "") : "";
    check("渲染流程会把「备份并重置」按钮填进家长操作区",
        html.includes("备份并重置") && html.includes("ProfilePage.resetUser()"),
        html.slice(0, 120));
    check("渲染出来的家长操作区不带密钥 / 算法参数",
        !/api_key|mastery_threshold|遗忘风险/i.test(html));

    console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
    process.exit(ok ? 0 : 1);
}, 80);
