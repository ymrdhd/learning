// ==============================================================
// 能力契约｜验证：诊断三页（入口/答题/报告）DOM id、脚本引用与渲染逻辑
// 入口：脚本自身：node frontend/verify_diagnostic_web.js
// 依赖：Node fs/vm（沙箱加载 html + js）
// 不负责：知识三页 → verify_knowledge_web.js
// 验证：node frontend/verify_diagnostic_web.js
// 被调用：verify_all.py（套件 diagweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * V2.0 能力诊断前端测试：三个诊断页面 + 各自的 JS 逻辑。
 *
 * 用 VM + DOM 打桩跑真实的 frontend/diagnostic*.js，不需要浏览器、不需要后端。
 * 覆盖：页面与脚本引用一致、$("id") 引用的元素都真实存在、
 *       进度文案/进度条、选项渲染与提交、报告渲染、知识点条形与掌握度配色。
 *
 * 用法：node frontend/verify_diagnostic_web.js
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

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/* ---------------- 1. 页面与脚本一致性 ---------------- */

const PAGES = [
    { html: "diagnostic.html", js: "diagnostic.js" },
    { html: "diagnostic_test.html", js: "diagnostic_test.js" },
    { html: "diagnostic_report.html", js: "diagnostic_report.js" },
];

for (const page of PAGES) {
    const html = readFile(page.html);
    const js = readFile(page.js);

    check(`${page.html} 引用了 ${page.js}`, html.includes(`src="${page.js}"`));

    const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
    const used = new Set([...js.matchAll(/\$\("([^"]+)"\)/g)].map(m => m[1]));
    const missing = [...used].filter(id => !ids.has(id));
    check(`${page.js} 用到的元素都存在于页面`, missing.length === 0, missing.join(", "));
}

// V2.5 需求变更：常规流程不再要求"额外做一次能力诊断"，
// 练习页入口换成自动能力水平页；诊断页本身保留，仍可直接访问。
check("练习页入口改为自动能力水平页", readFile("index.html").includes("ability.html"));
check("诊断页本身保留（仍可从 URL 直接访问）",
    fs.existsSync(path.join(DIR, "diagnostic.html"))
    && fs.existsSync(path.join(DIR, "diagnostic_report.html")));
check("诊断页有回到练习的链接", readFile("diagnostic.html").includes("index.html"));

/* ---------------- DOM 打桩 ---------------- */

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

// 从 innerHTML 里解析出按钮，供 querySelectorAll(".option") / ".subject-card" 使用
function parseButtons(container) {
    const found = [];
    const html = container.innerHTML || "";
    const tagRe = /<button\b([^>]*)>/g;
    let match;

    while ((match = tagRe.exec(html)) !== null) {
        const attrs = {};
        const attrRe = /([a-zA-Z-]+)(?:="([^"]*)")?/g;
        let a;
        while ((a = attrRe.exec(match[1])) !== null) {
            attrs[a[1]] = a[2] === undefined ? "" : a[2];
        }
        const dataset = {};
        for (const key of Object.keys(attrs)) {
            if (key.startsWith("data-")) {
                const camel = key.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
                dataset[camel] = attrs[key];
            }
        }
        const classes = new Set(String(attrs.class || "").split(/\s+/).filter(Boolean));
        found.push({
            tag: "button",
            dataset,
            disabled: false,
            classList: {
                add: c => classes.add(c),
                remove: c => classes.delete(c),
                contains: c => classes.has(c),
                toggle: (c, force) => {
                    const on = force === undefined ? !classes.has(c) : !!force;
                    if (on) classes.add(c); else classes.delete(c);
                    return on;
                },
                _set: classes,
            },
            _classes: classes,
        });
    }

    return found;
}

function buildContext(htmlFile, payloads, search) {
    const html = readFile(htmlFile);
    const ids = [...new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]))];
    const nodes = {};
    const calls = [];

    for (const id of ids) {
        const el = {
            id,
            innerHTML: "",
            value: id === "subject" ? "数学" : "",
            checked: false,
            disabled: false,
            textContent: "",
            dataset: {},
            style: {},
            href: "",
            focus() {},
        };
        el.classList = makeClassList("");
        nodes[id] = el;
    }

    const document = {
        getElementById: id => nodes[id] || null,
        querySelectorAll: selector => {
            const key = selector.replace(/^[.#]/, "");
            const results = [];
            for (const id of Object.keys(nodes)) {
                results.push(...parseButtons(nodes[id]).filter(b => b._classes.has(key)));
            }
            return results;
        },
        addEventListener() {},
    };

    const context = {
        document,
        console,
        setTimeout,
        clearTimeout,
        location: {
            protocol: "http:",
            origin: "http://127.0.0.1:8000",
            search: search || "",
            href: "",
        },
        sessionStorage: {
            store: {},
            getItem(k) { return Object.prototype.hasOwnProperty.call(this.store, k) ? this.store[k] : null; },
            setItem(k, v) { this.store[k] = String(v); },
        },
        fetch: (url, options) => {
            calls.push({ url: String(url), options: options || {} });
            const payload = payloads(String(url));
            if (payload === undefined) {
                return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
            }
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
        },
        SpeechSynthesisUtterance: function (text) { this.text = text; },
        URLSearchParams,
        Number,
        Math,
        JSON,
    };
    context.window = context;
    context.globalThis = context;

    return { context, nodes, calls };
}

function loadModule(htmlFile, jsFile, payloads, exportsSource, search) {
    const { context, nodes, calls } = buildContext(htmlFile, payloads, search);
    const source = readFile(jsFile) + "\n;globalThis.__x = {" + exportsSource + "};";
    vm.createContext(context);
    vm.runInContext(source, context, { filename: jsFile });
    return { context, nodes, calls, api: context.__x, exports: context.__x };
}

const EX = name => `${name}: typeof ${name} === "function" ? ${name} : null`;

/* ---------------- 2. 诊断过程页 ---------------- */

const DIAG_QUESTION = {
    session_id: 7,
    question_id: 11,
    qtype: "choice",
    subject: "数学",
    stage: "2.3",
    stage_label: "二年级进阶",
    knowledge: "两步计算应用题",
    difficulty: 45,
    question: "每盒有 3 个乒乓球，买了 4 盒，一共有多少个？",
    options: { A: "7", B: "12", C: "34", D: "10" },
    progress: { stage: "2.3", stage_label: "二年级进阶", answered: 3, total: 15, finished: false },
    finished: false,
};

const ANSWER_OK = {
    session_id: 7,
    correct: true,
    stage: "2.3",
    stage_label: "二年级进阶",
    message: "答对啦，真棒！",
    progress: { stage: "2.3", stage_label: "二年级进阶", answered: 4, total: 15, finished: false },
    finished: false,
};

async function testTestPage() {
    const mod = loadModule(
        "diagnostic_test.html",
        "diagnostic_test.js",
        url => {
            if (url.includes("/api/diagnostic/session")) {
                return { session_id: 7, student_id: 1, subject: "数学", status: "in_progress" };
            }
            if (url.includes("/api/diagnostic/question")) return DIAG_QUESTION;
            if (url.includes("/api/diagnostic/answer")) return ANSWER_OK;
            return undefined;
        },
        [EX("progressText"), EX("progressPercent"), EX("oralText"), EX("questionSpeechText"),
         EX("updateProgress"), EX("submitAnswer"), EX("loadQuestion"), EX("esc")].join(","),
        "?session_id=7"
    );

    await sleep(30);
    const { nodes, calls, api } = mod;

    check("诊断页渲染科目", nodes["subject-text"].textContent === "数学", nodes["subject-text"].textContent);
    check("诊断页渲染当前阶段", nodes["stage-text"].textContent === "二年级进阶",
          nodes["stage-text"].textContent);
    check("进度文案是 3/15", nodes["progress-text"].textContent === "3/15",
          nodes["progress-text"].textContent);
    check("进度条按比例走", nodes["progress-fill"].style.width === "20%",
          nodes["progress-fill"].style.width);
    check("候选进度纯函数", api.progressPercent({ answered: 7, total: 14 }) === 50);
    check("进度分母为 0 不崩", api.progressPercent({ answered: 3, total: 0 }) === 0);
    check("进度不超出 100%", api.progressPercent({ answered: 30, total: 15 }) === 100);

    const options = nodes["options"].innerHTML;
    check("渲染出 4 个选项", (options.match(/class="option"/g) || []).length === 4);
    check("题干来自接口", nodes["question"].innerHTML.includes("乒乓球"));
    check("诊断页不显示答案文本", !nodes["question"].innerHTML.includes("正确答案"));
    check("题目请求带 session_id", calls.some(c => c.url.includes("/api/diagnostic/question?session_id=7")));

    check("朗读文本带选项", api.questionSpeechText(DIAG_QUESTION).includes("选项A"),
          api.questionSpeechText(DIAG_QUESTION).slice(0, 40));
    check("符号口语化", api.oralText("3×4=？____") === "3乘4等于。空格", api.oralText("3×4=？____"));

    const btn = { classList: makeClassList("") };
    api.submitAnswer("B", btn);
    await sleep(30);

    const post = calls.find(c => c.url.includes("/api/diagnostic/answer"));
    check("提交答案调用后端", Boolean(post), post && post.url);
    check("提交内容含 session/题目/答案",
          post && JSON.parse(post.options.body).answer === "B"
          && JSON.parse(post.options.body).question_id === 11,
          post && post.options.body);
    check("答对给正向反馈", nodes["feedback"].innerHTML.includes("答对"), nodes["feedback"].innerHTML);
    check("答对的选项标绿", btn.classList.contains("right"));
    check("反馈里不出现正确答案", !nodes["feedback"].innerHTML.includes("正确答案"));
}

/* ---------------- 3. 能力报告页 ---------------- */

const REPORT = {
    available: true,
    student_id: 1,
    subject: "数学",
    stage: "3.2",
    stage_label: "三年级熟练",
    range_label: "3.2～3.3",
    score: 76,
    confidence: 0.82,
    star_text: "★★★★☆",
    stars: 4,
    ability: { questions: 30, correct: 24 },
    knowledge: [
        { knowledge: "表内乘法", mastery_score: 88, questions: 5, correct: 4 },
        { knowledge: "两步计算应用题", mastery_score: 61, questions: 5, correct: 3 },
    ],
    strengths: [{ knowledge: "表内乘法", mastery_score: 88 }],
    weaknesses: [{ knowledge: "两步计算应用题", mastery_score: 61 }],
    advice: ["每天训练 10 分钟。"],
    history: [{ stage: "3.2", label: "三年级熟练", count: 5, correct: 4, rate: 0.8, verdict_text: "到了能力边界" }],
};

async function testReportPage() {
    const mod = loadModule(
        "diagnostic_report.html",
        "diagnostic_report.js",
        url => {
            if (url.includes("/students")) {
                return [{ id: 1, name: "小朋友A", grade_text: "一年级" }];
            }
            if (url.includes("/api/diagnostic/report")) return REPORT;
            return undefined;
        },
        [EX("barWidth"), EX("masteryClass"), EX("renderKnowledge"), EX("renderReport")].join(",")
    );

    await sleep(30);
    const { nodes, api, context } = mod;

    check("报告页显示星级", nodes["report"].innerHTML.includes("★★★★☆"));
    check("报告页显示能力阶段", nodes["report"].innerHTML.includes("三年级熟练"));
    check("报告页显示能力区间", nodes["report"].innerHTML.includes("3.2～3.3"));
    check("报告页显示知识点", nodes["report"].innerHTML.includes("两步计算应用题"));
    check("报告页显示优势与短板",
          nodes["report"].innerHTML.includes("优势") && nodes["report"].innerHTML.includes("需要提升"));
    check("报告页显示学习建议", nodes["report"].innerHTML.includes("每天训练 10 分钟"));
    check("报告页显示测试过程", nodes["report"].innerHTML.includes("到了能力边界"));
    check("条形宽度按分数", api.barWidth(88) === 88 && api.barWidth(150) === 100 && api.barWidth(-5) === 0);
    check("掌握度配色分档",
          api.masteryClass(88) === "good" && api.masteryClass(65) === "mid" && api.masteryClass(30) === "low");
    check("知识点渲染含分数", api.renderKnowledge(REPORT.knowledge).includes(">88<"));

    context.location.search = "?student_id=1&subject=%E6%95%B0%E5%AD%A6";
    api.renderReport({ available: false, message: "还没有做过这项能力诊断" });
    check("未诊断时给出提示", nodes["report"].innerHTML.includes("还没有做过这项能力诊断"));
}

/* ---------------- 4. 诊断入口页 ---------------- */

async function testEntryPage() {
    const mod = loadModule(
        "diagnostic.html",
        "diagnostic.js",
        url => {
            if (url.includes("/students")) {
                return [
                    { id: 1, name: "小朋友A", grade_text: "四年级" },
                    { id: 2, name: "小朋友B", grade_text: "一年级" },
                ];
            }
            if (url.includes("/api/diagnostic/profiles")) {
                return {
                    student_id: 1,
                    profiles: [{ subject: "数学", stage: "3.2", stage_label: "三年级熟练", star_text: "★★★★☆", score: 76, confidence: 0.82 }],
                };
            }
            if (url.includes("/api/diagnostic/start")) {
                return { session_id: 9, student_id: 1, subject: "英语" };
            }
            return undefined;
        },
        [EX("esc"), EX("selectSubject"), EX("renderProfiles"), EX("startDiagnostic"), EX("currentStudentId"),
         "getSubject: () => selectedSubject"].join(",")
    );

    await sleep(30);
    const { nodes, api, context } = mod;

    check("入口页列出两个学生", (nodes["student"].innerHTML.match(/<option/g) || []).length === 2);
    check("入口页显示已有画像", nodes["profile-box"].innerHTML.includes("三年级熟练"));
    check("入口页显示星级", nodes["profile-box"].innerHTML.includes("★★★★☆"));
    check("开始按钮可用", nodes["start-btn"].disabled === false);
    check("转义防注入", api.esc("<b>") === "&lt;b&gt;");

    api.selectSubject("英语");
    check("科目切换记录选择", api.getSubject() === "英语", api.getSubject());

    api.startDiagnostic();
    await sleep(30);
    check("开始诊断后跳到诊断过程页",
          context.location.href.includes("diagnostic_test.html") && context.location.href.includes("session_id=9"),
          context.location.href);
    check("会话写入 sessionStorage", context.sessionStorage.getItem("xiaozhi.diagSession") === "9",
          context.sessionStorage.getItem("xiaozhi.diagSession"));
}

/* ---------------- 运行 ---------------- */

(async () => {
    try {
        await testTestPage();
        await testReportPage();
        await testEntryPage();
    } catch (err) {
        check("前端测试执行未抛异常", false, err && err.stack ? err.stack.split("\n")[0] : err);
    }

    console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
    process.exit(ok ? 0 : 1);
})();
