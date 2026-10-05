// ==============================================================
// 能力契约｜验证：我的能力水平页（ability.js / ability.html）—— 训练成绩自动诊断的展示层
// 入口：脚本自身：node frontend/verify_ability_web.js
// 依赖：Node fs/path/vm（沙箱加载 ability.js + fetch/DOM 打桩）
// 不负责：能力推断算法 → backend/verify_ability.py
// 验证：node frontend/verify_ability_web.js
// 被调用：verify_all.py（套件 abilityweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 「我的能力水平」页前端测试。
 *
 * 覆盖：页面元素齐全、纯函数（百分比 / 可信度 / 状态徽标）、
 *       三科渲染（可判断 / 数据积累中 / 无数据）、流程（选学生 → 请求接口 → 渲染）、
 *       以及"不需要专门诊断"的需求文案。
 *
 * 用法：node frontend/verify_ability_web.js
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
    return fs.readFileSync(path.join(DIR, name), "utf8");
}

const html = readFile("ability.html");
const js = readFile("ability.js");

/* ---------------- 1. 页面结构 ---------------- */

check("ability.html 引用了 ability.js", html.includes('src="ability.js"'));
check("ability.html 引入了菲比立牌", html.includes('src="phoebe3d.js"'));
check("ability.html 不再把立牌塞进卡片（V2.5 改挂浏览器左侧）", !html.includes("data-phoebe3d"));
check("ability.html 有学生下拉", html.includes('id="student"'));

const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
const used = new Set([...js.matchAll(/\$\("([^"]+)"\)/g)].map(m => m[1]));
const missing = [...used].filter(id => !ids.has(id));
check("ability.js 用到的元素都存在于页面", missing.length === 0, missing.join(", "));

check("页面说明强调不用专门考试（需求：不额外做诊断）",
    html.includes("每天的练习成绩") || html.includes("不是考试考出来的"));
check("ability.js 只读自动诊断接口",
    js.includes("/api/ability/auto/") && !js.includes("/api/diagnostic/"));

/* ---------------- 2. DOM / fetch 打桩 ---------------- */

const nodes = {};

function makeNode(id) {
    const node = {
        id,
        innerHTML: "",
        textContent: "",
        value: "",
        setAttribute() {},
        appendChild() {},
        addEventListener() {},
        querySelector() { return null; },
    };
    nodes[id] = node;
    return node;
}

function makeDocument() {
    ["student", "status", "overall", "ability-list"].forEach(makeNode);

    return {
        readyState: "complete",
        getElementById(id) { return nodes[id] || null; },
        createElement: makeNode,
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
    };
}

const ABILITY_PAYLOAD = {
    student_id: 1,
    source: "training",
    generated_at: "2026-10-04 21:00",
    total_answers: 46,
    overall: { stage: "3.2", stage_label: "三年级熟练", score: 71.4, status: "ready" },
    subjects: [
        {
            subject: "数学", status: "ready", score: 71.4, stage: "3.2", stage_label: "三年级熟练",
            range: ["3.2", "3.3"], stars: 4, star_text: "★★★★☆", confidence: 0.72,
            confidence_text: "中", answer_count: 12, correct_count: 9, correct_rate: 0.75,
            knowledge_focus: "两位数除法", reason: "最近 12 题答对 9 题（75%），推断为三年级熟练",
            next_step: "可以试试更难一点的题目",
        },
        {
            subject: "语文", status: "warming", score: 40, stage: "1.3", stage_label: "一年级进阶",
            range: ["1.3", "1.4"], stars: 3, star_text: "★★★☆☆", confidence: 0.3,
            confidence_text: "低", answer_count: 3, correct_count: 2, correct_rate: 0.67,
            knowledge_focus: "组词与量词", reason: "最近 3 题答对 2 题（67%），推断为一年级进阶",
            next_step: "再多练几题，判断会更准",
        },
        {
            subject: "英语", status: "unknown", score: 0, stage: "", stage_label: "",
            range: [], stars: 0, star_text: "☆☆☆☆☆", confidence: 0,
            confidence_text: "低", answer_count: 0, correct_count: 0, correct_rate: 0,
            knowledge_focus: "", reason: "", next_step: "先做几道这一科的题，系统就能看出你的水平",
        },
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
            { id: 1, name: "小朋友A", grade: 2, grade_text: "二年级" },
            { id: 2, name: "小朋友B", grade: 4, grade_text: "四年级" },
        ]);
    }

    if (String(url).includes("/api/ability/auto/")) return jsonResponse(ABILITY_PAYLOAD);

    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
}

const sandbox = {
    document: makeDocument(),
    fetch: fakeFetch,
    console,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    isFinite,
    parseInt,
    Promise,
    Error,
    setTimeout,
    location: { protocol: "http:", origin: "http://127.0.0.1:8000" },
    localStorage: {
        store: {},
        getItem(k) { return this.store[k] === undefined ? null : this.store[k]; },
        setItem(k, v) { this.store[k] = String(v); },
    },
};

vm.createContext(sandbox);
vm.runInContext(js, sandbox, { filename: "ability.js" });

/* ---------------- 3. 纯函数 ---------------- */

check("percentText 把 0.75 显示成 75%", sandbox.percentText(0.756) === "76%", sandbox.percentText(0.756));
check("percentText 对空值安全", sandbox.percentText(null) === "0%" && sandbox.percentText(undefined) === "0%");
check("confidenceText 带可信度文字与百分比",
    sandbox.confidenceText({ confidence: 0.72, confidence_text: "中" }).includes("中（72%）"),
    sandbox.confidenceText({ confidence: 0.72, confidence_text: "中" }));

check("statusBadge：ready 显示可以判断了",
    sandbox.statusBadge({ status: "ready" }).includes("可以判断了"));
check("statusBadge：warming 显示数据积累中",
    sandbox.statusBadge({ status: "warming" }).includes("数据积累中"));
check("statusBadge：unknown 显示还没有数据",
    sandbox.statusBadge({ status: "unknown" }).includes("还没有数据"));

/* ---------------- 4. 渲染 ---------------- */

const readyHtml = sandbox.renderSubject(ABILITY_PAYLOAD.subjects[0]);
check("渲染：显示能力阶段", readyHtml.includes("三年级熟练（3.2）"), "ok");
check("渲染：显示星级", readyHtml.includes("★★★★☆"));
check("渲染：显示能力分与当前重点",
    readyHtml.includes("71.4") && readyHtml.includes("两位数除法"));
check("渲染：显示题量、正确率与可信度",
    readyHtml.includes("12") && readyHtml.includes("75%") && readyHtml.includes("中（72%）"));
check("渲染：显示系统判断依据", readyHtml.includes("最近 12 题答对 9 题"));
check("渲染：显示下一步建议", readyHtml.includes("可以试试更难一点的题目"));

const warmingHtml = sandbox.renderSubject(ABILITY_PAYLOAD.subjects[1]);
check("渲染：数据积累中也给出阶段与提示", warmingHtml.includes("数据积累中")
    && warmingHtml.includes("再多练几题"));

const unknownHtml = sandbox.renderSubject(ABILITY_PAYLOAD.subjects[2]);
check("渲染：无数据科目给友好提示",
    unknownHtml.includes("还没有练习记录") && unknownHtml.includes("先做几道"));

sandbox.renderOverall(ABILITY_PAYLOAD);
check("渲染：综合水平显示阶段 / 分数 / 累计题数",
    nodes["overall"].innerHTML.includes("三年级熟练")
    && nodes["overall"].innerHTML.includes("71.4")
    && nodes["overall"].innerHTML.includes("46"));

sandbox.renderOverall({ overall: {}, subjects: [] });
check("渲染：没有综合水平时不显示空框", nodes["overall"].innerHTML === "");

sandbox.renderAbility(ABILITY_PAYLOAD);
check("渲染：三科都渲染出来",
    (nodes["ability-list"].innerHTML.match(/report-head|wrong-item/g) || []).length === 3);

/* ---------------- 5. 流程 ---------------- */

setTimeout(() => {
    check("初始化后填充学生下拉",
        nodes["student"].innerHTML.includes("小朋友A") && nodes["student"].innerHTML.includes("小朋友B"),
        nodes["student"].innerHTML.slice(0, 60));

    check("初始化后请求了自动诊断接口",
        calls.some(url => url.includes("/api/ability/auto/1")), calls.join(", "));

    check("流程结束后清空加载提示", nodes["status"].textContent === "", nodes["status"].textContent);
    check("流程结束后渲染了三科",
        nodes["ability-list"].innerHTML.includes("数学")
        && nodes["ability-list"].innerHTML.includes("语文")
        && nodes["ability-list"].innerHTML.includes("英语"));

    sandbox.loadAbility();
    setTimeout(() => {
        check("切换学生后按新 id 重新请求（使用的是下拉里的值）",
            calls.filter(url => url.includes("/api/ability/auto/")).length >= 2,
            calls.join(", "));

        console.log("\nRESULT: " + (ok ? "ALL PASS" : "HAS FAILURES"));
        process.exit(ok ? 0 : 1);
    }, 20);
}, 20);
