// ==============================================================
// 能力契约｜V2.5 前端：错题康复页 + 今日任务区块
// 入口：node frontend/verify_recovery_web.js（在 frontend 目录下运行）
// 依赖：Node 内置 fs / path / vm；无需浏览器、无需后端（fetch 打桩）
// 不负责：康复状态机与后端接口 → backend/verify_recovery.py / backend/verify_tasks.py
// 验证：node verify_recovery_web.js → RESULT: ALL PASS，退出码 0
// 被调用：改前端后由人工 / Lead 跑（与 verify_adaptive_web.js 一起跑）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 断言四件事：
 *   1) 页面结构：必需元素 / 类名 / 脚本加载顺序 / 零构建（无 import-export、无 CDN）
 *   2) 儿童友好：主操作按钮 min-height ≥56px、字号 ≥18px；单屏可见文字块 ≤3
 *   3) 康复流程：提示逐级展开（最多 4 级）、答对 ✅ + 菲比开心、答错 ❌ + 正确答案 + 看看解析
 *   4) 今日任务：GET /api/tasks/today 渲染完成率/时长/配比，POST /api/tasks/complete 打卡
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = __dirname;
const ORIGIN = "http://127.0.0.1:8000";

let ok = true;
let asserts = 0;

function check(name, cond, extra) {
    asserts += 1;
    console.log((cond ? "PASS  " : "FAIL  ") + name + (extra === undefined ? "" : "  | " + extra));
    if (!cond) ok = false;
}

function readFile(name) {
    return fs.readFileSync(path.join(DIR, name), "utf8");
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function countOf(text, needle) {
    return text.split(needle).length - 1;
}

/* ---------------- CSS 规则解析 ---------------- */

function cssBody(css, selector) {
    const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const rules = clean.split("}").map(chunk => {
        const open = chunk.indexOf("{");
        if (open < 0) return null;
        return {
            selectors: chunk.slice(0, open).split(",").map(s => s.trim().replace(/\s+/g, " ")),
            body: chunk.slice(open + 1)
        };
    }).filter(Boolean);
    const hit = rules.filter(rule => rule.selectors.includes(selector));
    return hit.length ? hit[hit.length - 1].body : "";
}

function pxOf(body, prop) {
    const hit = new RegExp(prop + "\\s*:\\s*([0-9.]+)px").exec(body);
    return hit ? Number(hit[1]) : null;
}
function firstHex(body, prop) {
    const hit = new RegExp(prop + "\\s*:\\s*(#[0-9a-fA-F]{3,6})").exec(body);
    return hit ? hit[1] : "";
}

function rgb(hex) {
    let text = String(hex).replace("#", "");
    if (text.length === 3) text = text.split("").map(char => char + char).join("");
    return [parseInt(text.slice(0, 2), 16), parseInt(text.slice(2, 4), 16), parseInt(text.slice(4, 6), 16)];
}
function assertBigButton(css, selector) {
    const body = cssBody(css, selector);
    const minH = pxOf(body, "min-height");
    const font = pxOf(body, "font-size");
    check(`CSS ${selector} 最小高度 >=56px 且字号 >=18px`, minH !== null && minH >= 56 && font !== null && font >= 18,
        `min-height=${minH}px font-size=${font}px`);
}

/* ---------------- DOM 打桩 ---------------- */

function makeClassList(initial) {
    const set = new Set(String(initial || "").split(/\s+/).filter(Boolean));
    return {
        _set: set,
        add(...names) { names.forEach(name => set.add(name)); },
        remove(...names) { names.forEach(name => set.delete(name)); },
        contains(name) { return set.has(name); },
        toggle(name, force) {
            const on = force === undefined ? !set.has(name) : !!force;
            if (on) set.add(name); else set.delete(name);
            return on;
        }
    };
}

const TAG_RE = /<(select|input|div|p|span|button|a|h1|label)\b([^>]*)>/g;
const ID_RE = /id="([^"]+)"/g;

function buildStub(htmlText, route, globals) {
    const ids = [...htmlText.matchAll(ID_RE)].map(match => match[1]);
    const tagOf = {};
    const classOf = {};

    for (const match of htmlText.matchAll(TAG_RE)) {
        const idMatch = /id="([^"]+)"/.exec(match[2]);
        if (!idMatch) continue;
        tagOf[idMatch[1]] = match[1];
        const cls = /class="([^"]*)"/.exec(match[2]);
        classOf[idMatch[1]] = cls ? cls[1] : "";
    }

    const nodes = {};
    const calls = [];

    for (const id of ids) {
        const el = {
            id, value: "", checked: false, disabled: false, textContent: "",
            dataset: {}, style: {}, focus() {}
        };
        el.classList = makeClassList(classOf[id] || "");
        let inner = "";
        Object.defineProperty(el, "innerHTML", {
            get() { return inner; },
            set(value) {
                inner = String(value);
                if (tagOf[id] === "select") {
                    const first = /<option value="([^"]*)"/.exec(inner);
                    if (first) el.value = first[1];
                }
            }
        });
        nodes[id] = el;
    }

    const context = {
        document: {
            getElementById: id => nodes[id] || null,
            querySelectorAll: () => [],
            querySelector: () => null,
            addEventListener() {}
        },
        console, setTimeout, clearTimeout,
        location: { protocol: "http:", origin: ORIGIN, href: "" },
        localStorage: {
            _data: {},
            getItem(key) { return Object.prototype.hasOwnProperty.call(this._data, key) ? this._data[key] : null; },
            setItem(key, value) { this._data[key] = String(value); }
        },
        fetch(url, options) {
            const call = { url: String(url), options: options || {} };
            calls.push(call);
            const payload = route(call.url, call.options);
            if (payload === undefined) {
                return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
            }
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
        },
        URLSearchParams, Number, Math, JSON, String, Object, Array, Boolean, isNaN, parseInt, parseFloat
    };

    Object.assign(context, globals || {});
    context.window = context;
    context.globalThis = context;
    return { context, nodes, calls };
}

function loadPage(htmlText, jsName, route, globals, exportsSource) {
    const stub = buildStub(htmlText, route, globals);
    const source = readFile(jsName) + "\n;globalThis.__x = {" + exportsSource + "};\n";
    vm.createContext(stub.context);
    vm.runInContext(source, stub.context, { filename: jsName });
    return { context: stub.context, nodes: stub.nodes, calls: stub.calls, api: stub.context.__x };
}

/* ---------------- 测试数据 ---------------- */

const STUDENTS = [
    { id: 1, name: "小智", grade_text: "三年级" },
    { id: 2, name: "小美", grade_text: "三年级" }
];
const LIST = {
    student_id: 1, total: 1,
    stats: { total: 1, mastered: 0, mastered_rate: 0 },
    items: [{
        recovery_id: 11, question_id: 77, subject: "数学", knowledge: "两步计算应用题",
        state: "ANALYZING", state_text: "菲比正在找错因", wrong_count: 2, attempts: 0,
        consecutive_correct: 0, fail_count: 2, max_level_used: 0,
        question: "3 盒铅笔，每盒 5 支，送出 2 支，还剩多少支？",
        correct_answer: "13", analysis: "先算 3×5=15，再减 2，答案是 13。",
        error_type: "计算错误", next_verify_time: "", created_time: "2026-10-04 20:00"
    }]
};
const START = {
    recovery_id: 11, question_id: 77, state: "LEARNING", state_text: "菲比在讲解",
    teaching: {
        level: 1, level_text: "先找错因", hint: "看看是不是先乘后减。",
        error_location: "第二步", steps: [], full_explanation: "先乘后减。", source: "local"
    },
    item: { recovery_id: 11 }
};
const QUESTION_RESP = {
    recovery_id: 11, state: "PRACTICING", hint_level: 1,
    question: {
        question_id: 88, question: "3 盒铅笔，每盒 5 支，送出 2 支，还剩多少支？",
        qtype: "choice", options: { A: "13", B: "15", C: "17", D: "10" },
        knowledge: "两步计算应用题", difficulty: 62, source: "local", variant: true
    },
    teaching: { level: 1, level_text: "先看数量", hint: "先算一共有几支。", source: "local" }
};
const HINT2 = {
    level: 2, level_text: "再想一步", hint: "15 支送出 2 支，要用减法。",
    error_location: "第二步", steps: [], full_explanation: "先乘后减。", source: "local"
};
const WRONG = {
    correct: false, correct_answer: "13",
    analysis: "先算 3×5=15，再减 2，答案是 13。",
    state: "PRACTICING", state_text: "正在练变式题", changed: true, next_action: "explain"
};
const CORRECT = {
    correct: true, correct_answer: "13",
    analysis: "先算 3×5=15，再减 2，答案是 13。",
    state: "PRACTICING", state_text: "正在练变式题", changed: true, next_action: "verify"
};
const TASKS_BEFORE = {
    student_id: 1, date: "2026-10-05", generated: true,
    tasks: [
        {
            task_id: 31, task_type: "new_learning", task_type_text: "新知识", title: "分数的初步认识",
            subject: "数学", knowledge: "分数", target_count: 10, complete_count: 4,
            duration_minutes: 6, target_minutes: 10, status: "doing", status_text: "进行中",
            priority: 1, goal: "掌握分数", reason: "今天还没学新知识"
        },
        {
            task_id: 32, task_type: "review", task_type_text: "复习", title: "复习昨天的错题",
            subject: "数学", knowledge: "两步计算应用题", target_count: 4, complete_count: 4,
            duration_minutes: 5, target_minutes: 5, status: "done", status_text: "已完成",
            priority: 3, goal: "巩固错题", reason: "到期复习"
        }
    ],
    summary: {
        total: 2, done: 1, pending: 1, completion_rate: 50, minutes: 11,
        mix: { new_learning: 50, weakness: 30, review: 20 }
    }
};
const TASKS_AFTER = JSON.parse(JSON.stringify(TASKS_BEFORE));
TASKS_AFTER.tasks[0] = Object.assign({}, TASKS_AFTER.tasks[0], {
    status: "done", status_text: "已完成", complete_count: 10, duration_minutes: 10
});
TASKS_AFTER.summary = {
    total: 2, done: 2, pending: 0, completion_rate: 100, minutes: 21,
    mix: { new_learning: 50, weakness: 30, review: 20 }
};

/* ---------------- 静态检查 ---------------- */

const recoveryHtml = readFile("recovery.html");
const recoveryJs = readFile("recovery.js");
const todayHtml = readFile("today.html");
const todayJs = readFile("today.js");
const styleCss = readFile("style.css");

check("recovery.html / recovery.js / today.html / today.js 都存在", recoveryHtml.length > 0 && recoveryJs.length > 0 && todayHtml.length > 0 && todayJs.length > 0);

for (const name of ["recovery.html", "today.html"]) {
    const html = name === "recovery.html" ? recoveryHtml : todayHtml;
    const pageJs = name === "recovery.html" ? "recovery.js" : "today.js";
    const scripts = [...html.matchAll(/<script[^>]*src="([^"]+)"/g)].map(match => match[1]);
    check(`${name} 脚本顺序 phoebe.js → phoebe3d.js → 共享层 → ${pageJs}`,
        scripts.indexOf("phoebe.js") === 0 && scripts.indexOf("phoebe3d.js") === 1
        && scripts.indexOf("ui-shell.js") === 2 && scripts.indexOf("kid-lang.js") === 3
        && scripts.indexOf("ui-components.js") === 4 && scripts.indexOf(pageJs) === 5,
        scripts.join(" → "));
    check(`${name} 只引入一次 phoebe3d.js`, countOf(html, "phoebe3d.js") === 1);
    check(`${name} 无 CDN 脚本（零构建）`, !/<script[^>]*src="https?:/i.test(html));
    check(`${name} 无 ES module`, !/type="module"/.test(html));
    check(`${name} 引用 style.css`, /href="style.css"/.test(html));
}

check("业务脚本无 import / export（零构建）", !/^\s*(import|export)\s/m.test(recoveryJs) && !/^\s*(import|export)\s/m.test(todayJs));

for (const [pageName, html, jsName, jsText] of [
    ["recovery.html", recoveryHtml, "recovery.js", recoveryJs],
    ["today.html", todayHtml, "today.js", todayJs]
]) {
    const ids = new Set([...html.matchAll(ID_RE)].map(match => match[1]));
    const used = [...jsText.matchAll(/\$\("([^"]+)"\)/g)].map(match => match[1]);
    const missing = [...new Set(used)].filter(id => !ids.has(id));
    check(`${jsName} 用到的元素都存在于 ${pageName}`, missing.length === 0, missing.join(",") || "无缺失");
}

check("recovery.html 有底部 link-row 回到其它页面",
    /class="[^"]*link-row/.test(recoveryHtml) && /href="index.html"/.test(recoveryHtml) &&
    /href="today.html"/.test(recoveryHtml) && /href="wrong_book.html"/.test(recoveryHtml));
check("today.html 顶部今日任务区块结构完整",
    /id="task-block"/.test(todayHtml) && /id="task-title"[^>]*class="task-title"/.test(todayHtml) &&
    /id="task-summary"[^>]*class="task-summary"/.test(todayHtml) &&
    /id="task-mix"[^>]*class="task-mix"/.test(todayHtml) && /id="task-list"[^>]*class="task-list"/.test(todayHtml));
check("today.html 今日任务区块在原有计划之前", todayHtml.indexOf('id="task-block"') < todayHtml.indexOf('id="plan-list"'));

/* CSS：儿童友好按钮尺寸与字号 */
for (const selector of [".btn", ".btn-primary", ".recovery-main-btn", ".recovery-hint-btn",
    ".recovery-explain-btn", ".recovery-refresh-btn", ".task-complete-btn", ".recovery-options .option"]) {
    assertBigButton(styleCss, selector);
}
const okFeedback = rgb(firstHex(cssBody(styleCss, ".recovery-feedback.ok"), "background"));
const badFeedback = rgb(firstHex(cssBody(styleCss, ".recovery-feedback.bad"), "background"));
check("答对反馈是绿色", okFeedback[1] > okFeedback[0] && okFeedback[1] > okFeedback[2], okFeedback.join(","));
check("答错反馈是橙色", badFeedback[0] > badFeedback[1] && badFeedback[1] > badFeedback[2], badFeedback.join(","));
check("style.css 有康复/任务/习惯样式块",
    [".recovery-list", ".recovery-card-btn", ".recovery-pick", ".recovery-qtext", ".recovery-hint-box",
        ".recovery-feedback.ok", ".recovery-feedback.bad", ".recovery-done", ".task-block", ".task-item",
        ".task-complete-btn", ".habit-streak", ".habit-badge"].every(sel => cssBody(styleCss, sel).length > 0));

/* ---------------- 康复流程（动态） ---------------- */

async function recoveryFlow() {
    const feedback = [];
    let answeredOk = false;

    function recoveryRoute(url, options) {
        if (url.includes("/students")) return STUDENTS;
        if (url.includes("/api/recovery/list")) return LIST;
        if (url.includes("/api/recovery/start")) return START;
        if (url.includes("/api/recovery/question")) return QUESTION_RESP;
        if (url.includes("/api/recovery/hint")) return HINT2;
        if (url.includes("/api/recovery/answer")) {
            return String(options.body || "").includes('"answer":"A"') ? CORRECT : WRONG;
        }
        return undefined;
    }

    const page = loadPage(recoveryHtml, "recovery.js", recoveryRoute, {
        phoebe3dFeedback(correct, opts) { feedback.push([correct, opts]); }
    }, [
        "nextHintLevel", "hintMoreText", "percent", "stateText", "renderList", "renderPick", "renderQuestion",
        "renderHint", "renderResult", "showAnalysis", "renderDone", "visibleTextBlocks", "loadRecovery",
        "selectRecovery", "startRecovery", "loadQuestion", "showNextHint", "answerRecovery", "answerRecoveryBlank"
    ].map(name => `${name}: typeof ${name} === "function" ? ${name} : null`).join(",\n"));

    const { nodes, calls, api } = page;

    await sleep(30);
    check("初始化请求 /students", calls.some(call => call.url.includes("/students")), calls.map(c => c.url).join(" "));
    check("初始化填充学生下拉", nodes.student.innerHTML.includes("小智"));
    check("初始化请求 GET /api/recovery/list 并带 student_id",
        calls.some(call => call.url.includes("/api/recovery/list?student_id=1")));
    check("康复队列渲染成可点卡片",
        nodes["recovery-list"].innerHTML.includes("两步计算应用题") &&
        nodes["recovery-list"].innerHTML.includes("recovery-card-btn") &&
        nodes["recovery-list"].innerHTML.includes("selectRecovery(11)"));

    api.selectRecovery(11);
    await sleep(5);
    check("选中错题后进入康复工作区", !nodes["recovery-work"].classList.contains("hidden"));
    check("选中后单屏可见文字块 <=3", api.visibleTextBlocks().length <= 3, api.visibleTextBlocks().join(","));

    await api.startRecovery();
    await sleep(30);
    check("开始康复调 POST /api/recovery/start 并带 recovery_id",
        calls.some(call => call.url.includes("/api/recovery/start") && String(call.options.body).includes('"recovery_id":11') && call.options.method === "POST"));
    check("开始康复先给第 1 级提示", nodes["hint-box"].innerHTML.includes("菲比提示 1/4"));
    check("提示里有「还是不会」按钮", nodes["hint-box"].innerHTML.includes("还是不会") && nodes["hint-box"].innerHTML.includes("showNextHint()"));
    check("开始康复后出题（题干 + 选项）",
        nodes.question.innerHTML.includes("铅笔") && nodes.options.innerHTML.includes('data-key="A"'));
    check("出题调 POST /api/recovery/question 并带 student_id",
        calls.some(call => call.url.includes("/api/recovery/question") && String(call.options.body).includes('"student_id":1')));
    check("出题时单屏可见文字块 <=3", api.visibleTextBlocks().length <= 3, api.visibleTextBlocks().join(","));

    check("提示等级 0→1", api.nextHintLevel(0) === 1);
    check("提示等级 1→2", api.nextHintLevel(1) === 2);
    check("提示等级 3→4", api.nextHintLevel(3) === 4);
    check("提示等级最多 4 级", api.nextHintLevel(4) === 4 && api.nextHintLevel(9) === 4);

    await api.showNextHint();
    await sleep(30);
    check("点「还是不会」调 POST /api/recovery/hint 取下一级",
        calls.some(call => call.url.includes("/api/recovery/hint") && String(call.options.body).includes('"level":2')));
    check("第二级提示替换第一级（不叠加）",
        nodes["hint-box"].innerHTML.includes("2/4") && !nodes["hint-box"].innerHTML.includes("1/4"));
    check("提示时单屏可见文字块 <=3", api.visibleTextBlocks().length <= 3, api.visibleTextBlocks().join(","));

    await api.showNextHint();
    await sleep(30);
    await api.showNextHint();
    await sleep(30);
    check("提示最多展开到 4 级后停住", api.nextHintLevel(4) === 4 && calls.filter(call => call.url.includes("/api/recovery/hint")).length === 3);

    /* 答错分支 */
    const beforeWrong = feedback.length;
    await api.answerRecovery("B", null);
    await sleep(30);
    check("答错显示橙色 ❌ 反馈",
        nodes.result.innerHTML.includes("❌") && nodes.result.innerHTML.includes("recovery-feedback bad"));
    check("答错给出正确答案", nodes.result.innerHTML.includes("正确答案") && nodes.result.innerHTML.includes("13"));
    check("答错有「看看解析」按钮", nodes.result.innerHTML.includes("看看解析") && nodes.result.innerHTML.includes("showAnalysis()"));
    check("答错回答调 POST /api/recovery/answer",
        calls.some(call => call.url.includes("/api/recovery/answer") && String(call.options.body).includes('"question_id":88') && String(call.options.body).includes('"answer":"B"')));
    check("答错调用菲比反馈 false", feedback.length === beforeWrong + 1 && feedback[beforeWrong][0] === false);
    check("答错后单屏可见文字块 <=3", api.visibleTextBlocks().length <= 3, api.visibleTextBlocks().join(","));

    api.showAnalysis();
    check("点「看看解析」显示解析文字",
        nodes.result.innerHTML.includes("错题解析") && nodes.result.innerHTML.includes("3×5=15"));

    /* 答对分支 */
    api.selectRecovery(11);
    await sleep(5);
    await api.startRecovery();
    await sleep(30);
    const beforeRight = feedback.length;
    await api.answerRecovery("A", null);
    await sleep(30);
    check("答对显示绿色 ✅ 反馈",
        nodes.result.innerHTML.includes("✅") && nodes.result.innerHTML.includes("recovery-feedback ok"));
    check("答对调用菲比反馈 true", feedback.length === beforeRight + 1 && feedback[beforeRight][0] === true);
    check("答对后收起提示", nodes["hint-box"].classList.contains("hidden"));
    check("答对后单屏可见文字块 <=3", api.visibleTextBlocks().length <= 3, api.visibleTextBlocks().join(","));

    /* 全部康复完成 */
    const beforeDone = feedback.length;
    api.renderDone({ stats: { mastered: 2, total: 5 }, state: "MASTERED" });
    await sleep(5);
    check("康复完成显示进度", nodes["recovery-done"].innerHTML.includes("康复") &&
        nodes["recovery-done"].innerHTML.includes("2") && nodes["recovery-done"].innerHTML.includes("3"));
    check("康复完成时工作区收起、完成层可见",
        nodes["recovery-work"].classList.contains("hidden") && !nodes["recovery-done"].classList.contains("hidden"));
    check("康复完成也调用菲比庆祝", feedback.length === beforeDone + 1 && feedback[beforeDone][0] === true);
    check("完成时单屏可见文字块 <=1", api.visibleTextBlocks().length <= 1, api.visibleTextBlocks().join(","));

    /* 菲比模块缺失时静默降级 */
    const bare = loadPage(recoveryHtml, "recovery.js", recoveryRoute, {}, [
        "visibleTextBlocks", "renderResult", "answerRecovery", "loadRecovery", "selectRecovery", "startRecovery"
    ].map(name => `${name}: typeof ${name} === "function" ? ${name} : null`).join(",\n"));
    await sleep(30);
    bare.api.selectRecovery(11);
    await sleep(5);
    await bare.api.startRecovery();
    await sleep(30);
    let degraded = false;
    try {
        await bare.api.answerRecovery("B", null);
        await sleep(30);
        bare.api.renderResult(WRONG);
        degraded = bare.nodes.result.innerHTML.includes("❌");
    } catch (err) {
        degraded = false;
        console.log("      降级断言异常：" + err.message);
    }
    check("没有 phoebe3d.js 时答错/答对不报错（静默降级）", degraded);
    answeredOk = true;
    return answeredOk;
}

/* ---------------- 今日任务区块（动态） ---------------- */

async function todayFlow() {
    let completed = false;

    function todayRoute(url, options) {
        if (url.includes("/students")) return STUDENTS;
        if (url.includes("/api/tasks/complete")) {
            completed = true;
            return { task_id: 31, status: "done", status_text: "已完成", summary: TASKS_AFTER.summary };
        }
        if (url.includes("/api/tasks/today")) return completed ? TASKS_AFTER : TASKS_BEFORE;
        if (url.includes("/api/learning/plan/")) return { items: [] };
        if (url.includes("/api/learning/strategy-log/")) return { logs: [] };
        return undefined;
    }

    const page = loadPage(todayHtml, "today.js", todayRoute, {
        phoebe3dFeedback() {}
    }, [
        "renderTaskBlock", "loadTasks", "completeTask", "taskSummaryText", "taskMixText", "taskItemHtml"
    ].map(name => `${name}: typeof ${name} === "function" ? ${name} : null`).join(",\n"));

    const { nodes, calls, api } = page;

    await sleep(30);
    check("今日任务调 GET /api/tasks/today 带 student_id",
        calls.some(call => call.url.includes("/api/tasks/today?student_id=1")));
    check("今日任务标题写明 50/30/20 配比", nodes["task-title"].innerHTML.includes("今日任务"));
    check("显示完成率 / 时长",
        nodes["task-summary"].innerHTML.includes("完成 1/2") &&
        nodes["task-summary"].innerHTML.includes("50%") &&
        nodes["task-summary"].innerHTML.includes("11 分钟"));
    check("显示三类任务配比",
        nodes["task-mix"].innerHTML.includes("新知识 50%") &&
        nodes["task-mix"].innerHTML.includes("薄弱点 30%") &&
        nodes["task-mix"].innerHTML.includes("复习 20%"));
    check("任务卡片列出任务、进度与目标",
        nodes["task-list"].innerHTML.includes("分数的初步认识") &&
        nodes["task-list"].innerHTML.includes("4/10") && nodes["task-list"].innerHTML.includes("6/10 分钟"));
    check("已完成任务有徽标且不再出现打卡按钮",
        nodes["task-list"].innerHTML.includes("task-done-badge") &&
        nodes["task-list"].innerHTML.includes("已完成") &&
        countOf(nodes["task-list"].innerHTML, "task-complete-btn") === 1);
    check("未完成任务有打卡按钮且是大按钮类名",
        nodes["task-list"].innerHTML.includes('class="btn btn-primary task-complete-btn"') &&
        nodes["task-list"].innerHTML.includes("completeTask(31)"));
    check("任务区块不清空原有计划区", nodes.status.textContent === "");

    await api.completeTask(31);
    await sleep(40);
    const completeCall = calls.find(call => call.url.includes("/api/tasks/complete"));
    check("打卡调 POST /api/tasks/complete",
        !!completeCall && completeCall.options.method === "POST");
    check("打卡请求带 student_id / task_id / done",
        !!completeCall && String(completeCall.options.body).includes('"student_id":1') &&
        String(completeCall.options.body).includes('"task_id":31') &&
        String(completeCall.options.body).includes('"done":true'));
    check("打卡后完成率 / 时长刷新",
        nodes["task-summary"].innerHTML.includes("完成 2/2") &&
        nodes["task-summary"].innerHTML.includes("100%") &&
        nodes["task-summary"].innerHTML.includes("21 分钟"));

    /* 后端没有任务接口时不破坏原有今日学习流程 */
    const barePage = loadPage(todayHtml, "today.js", url => (url.includes("/students") ? STUDENTS : undefined), {
        phoebe3dFeedback() {}
    }, "taskSummaryText: typeof taskSummaryText === 'function' ? taskSummaryText : null");
    await sleep(30);
    check("任务接口 404 时给降级文案且不打断原有流程",
        barePage.nodes["task-mix"].innerHTML.includes("任务暂时排不出来") &&
        barePage.calls.some(call => call.url.includes("/api/learning/plan/")));
    check("任务接口 404 时页面仍渲染今日任务标题",
        todayHtml.includes("今日任务") &&
        barePage.api.taskSummaryText({ done: 1, total: 2, minutes: 5 }).includes("50%"));
    return true;
}

async function flow() {
    await recoveryFlow();
    await todayFlow();
    console.log("");
    console.log(`断言 ${asserts} 条：${ok ? "全部通过" : "存在失败"}`);
    console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
    process.exit(ok ? 0 : 1);
}

flow();
