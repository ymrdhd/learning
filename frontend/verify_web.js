// ==============================================================
// 能力契约｜验证：练习页（app.js）语音朗读 / 复习面板 / 判分渲染逻辑（vm 沙箱）
// 入口：脚本自身：node frontend/verify_web.js
// 依赖：Node fs/vm/path（读取 app.js 并在沙箱执行）
// 不负责：诊断页 → verify_diagnostic_web.js
// 验证：node frontend/verify_web.js
// 被调用：verify_all.py（套件 web）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 前端逻辑测试：语音朗读 + 复习面板。
 *
 * 用 VM + DOM 打桩跑真实的 frontend/app.js，不需要浏览器。
 * 覆盖：语音支持检测、中文音色选择、静音开关、题目/选项朗读文本、
 *       解析朗读、复习徽标与到期面板、答错后的复习提示。
 *
 * 用法：node frontend/verify_web.js
 * 全部通过时退出码为 0。
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const APP = path.join(__dirname, "app.js");
let ok = true;

function check(name, cond, extra) {
    console.log((cond ? "PASS  " : "FAIL  ") + name + (extra === undefined ? "" : "  | " + extra));
    if (!cond) ok = false;
}

/* ---------------- DOM 打桩 ---------------- */

const ELEMENT_IDS = [
    "student", "subject", "knowledge", "mode-choice", "mode-blank", "main-btn",
    "question", "options", "blank-box", "blank-input", "feedback", "progress",
    "review-panel", "voice-enabled", "voice-rate", "voice-status",
    "knowledge-hint", "sheet-tag",
];

function makeClassList(initial) {
    const set = new Set();
    if (initial) String(initial).split(/\s+/).filter(Boolean).forEach(c => set.add(c));
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

const nodes = {};

for (const id of ELEMENT_IDS) {
    const el = {
        id,
        innerHTML: "",
        value: "",
        checked: false,
        disabled: false,
        textContent: "",
        dataset: {},
        listeners: {},
        style: {},
        addEventListener(type, fn) {
            (this.listeners[type] = this.listeners[type] || []).push(fn);
        },
        focus() {},
    };
    el.classList = makeClassList("");
    nodes[id] = el;
}
nodes["review-panel"].classList.add("hidden");
nodes["blank-box"].classList.add("hidden");

// 渲染出来的按钮（选项、朗读按钮）即时解析，供 querySelectorAll("[data-speaking]") 找到
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
        found.push({
            tag: "button",
            dataset,
            disabled: false,
            classList: makeClassList(attrs.class || ""),
            addEventListener() {},
        });
    }
    return found;
}

const document = {
    getElementById: id => nodes[id] || null,
    querySelector(sel) {
        const key = /data-key="([^"]+)"/.exec(sel);
        if (key) {
            return parseButtons(nodes.options).find(b => b.dataset.key === key[1]) || null;
        }
        return null;
    },
    querySelectorAll(sel) {
        if (sel === ".option") return parseButtons(nodes.options);
        if (sel === "[data-speaking]") {
            return parseButtons(nodes.question).concat(parseButtons(nodes.feedback));
        }
        return [];
    },
    createElement: tag => ({ tag, innerHTML: "", classList: makeClassList(""), addEventListener() {} }),
};

/* ---------------- 语音与存储打桩 ---------------- */

const spoken = [];
const voices = [
    { name: "Microsoft Huihui", lang: "zh-CN" },
    { name: "Alex", lang: "en-US" },
];

class SpeechSynthesisUtterance {
    constructor(text) {
        this.text = text;
    }
}

const speechSynthesis = {
    onvoiceschanged: null,
    cancelled: 0,
    getVoices: () => voices,
    cancel() {
        this.cancelled += 1;
    },
    speak(utter) {
        spoken.push(utter);
        if (typeof utter.onend === "function") utter.onend();
    },
};

const store = {};

const sandbox = {
    document,
    window: { document, speechSynthesis, SpeechSynthesisUtterance },
    speechSynthesis,
    SpeechSynthesisUtterance,
    localStorage: {
        getItem: key => (key in store ? store[key] : null),
        setItem: (key, value) => { store[key] = String(value); },
    },
    console,
    setTimeout,
    clearTimeout,
    fetch: () => new Promise(() => {}),   // init() 里的 /students 请求挂起即可
    URLSearchParams,
};

vm.createContext(sandbox);

// app.js 用 const/let 声明的顶层变量不会挂到全局对象上，这里统一导出给测试使用。
// current / progress 必须用 setter 写回，直接赋属性只会改到导出对象的副本。
const EXPORTS = `
;globalThis.__app = {
    speech, oralText, speakQuestion, speakAnalysis, renderQuestion, renderResult,
    resetBoard, retryQuestion, onVoiceToggle,
    pickRecommendedKnowledge, applyAutoKnowledge,
    setManualKnowledge: value => { manualKnowledge = value; },
    setCurrent: value => { current = value; },
    setProgress: value => { progress = value; },
    getCurrent: () => current,
    getProgress: () => progress,
    setSheet: value => { sheet = value; },
    setSheetActive: value => { sheetActive = value; },
    sheetBucket: typeof sheetBucket === "function" ? sheetBucket : null,
    sheetAdvance: typeof sheetAdvance === "function" ? sheetAdvance : null,
    renderSheetTag: typeof renderSheetTag === "function" ? renderSheetTag : null,
    buildSheet: typeof buildSheet === "function" ? buildSheet : null,
    getSheetState: () => ({ active: sheetActive, done: sheetDone, index: sheet ? sheet.index : -1 }),
};`;

// 真实页面加载顺序：业务 js 在前，共享层（kid-lang / ui-components）在后。
// 这里按同样顺序注入，保证验证跑的是真实代码路径。
const sharedLayer = ["kid-lang.js", "ui-components.js"]
    .map(name => fs.readFileSync(path.join(__dirname, name), "utf8"))
    .join("\n");
vm.runInContext(sharedLayer + "\n" + fs.readFileSync(APP, "utf8") + EXPORTS, sandbox, { filename: "app.js" });

const app = sandbox.__app;

check("共享层 kid-lang.js / ui-components.js 已随页面加载",
    !!(sandbox.window && sandbox.window.KidLang && sandbox.window.UIComponents));

/* ---------------- 断言：初始化 ---------------- */

check("检测到浏览器支持语音", app.speech.supported === true);
check("自动选中中文音色", app.speech.voice && app.speech.voice.lang === "zh-CN",
    app.speech.voice && app.speech.voice.name);
check("默认不静音", app.speech.muted === false);

/* ---------------- 断言：题目渲染与朗读 ---------------- */

const question = {
    question_id: 7,
    qtype: "choice",
    subject: "数学",
    knowledge: "20以内加减法",
    difficulty: 50,
    stage: 1.5,
    question: "算一算：5 + 3 = ____ ？",
    options: { A: "7", B: "8", C: "9", D: "6" },
    is_review: true,
    review: { stage: 2, mastery: 18, next_review_text: "30分钟后", due: true },
    due_reviews: [{ knowledge: "乘法口诀", mastery: 27, overdue_text: "已超时2小时" }],
    due_count: 2,
};

app.setCurrent(question);
app.renderQuestion(question);

check("题目区渲染出朗读按钮",
    /data-speaking="0"/.test(nodes.question.innerHTML) && /读题目/.test(nodes.question.innerHTML));
check("复习题显示儿童化复习提示（不出现掌握度）",
    /这个知识该复习啦/.test(nodes.question.innerHTML)
    && nodes.question.innerHTML.indexOf("🌱 刚开始") >= 0
    && nodes.question.innerHTML.indexOf("掌握度") < 0);
check("选项按钮全部渲染", parseButtons(nodes.options).length === 4);

check("到期复习面板列出知识点",
    /乘法口诀/.test(nodes["review-panel"].innerHTML) && /已超时2小时/.test(nodes["review-panel"].innerHTML));
check("面板给出立即复习按钮", /startReview\('乘法口诀'\)/.test(nodes["review-panel"].innerHTML));
check("面板已显示", nodes["review-panel"].classList.contains("hidden") === false);

app.speakQuestion();
const readText = spoken.length ? spoken[spoken.length - 1].text : "";
check("朗读题目含题干并把问号读成停顿",
    readText.indexOf("算一算：5 + 3 = 空格。选项A：7。") === 0, readText);
check("朗读题目逐个念选项",
    ["选项A：7", "选项B：8", "选项C：9", "选项D：6"].every(t => readText.indexOf(t) >= 0), readText);
check("朗读使用中文语音", spoken[spoken.length - 1].lang === "zh-CN");
check("朗读应用慢语速", spoken[spoken.length - 1].rate === 0.85, spoken[spoken.length - 1].rate);

check("乘号读作乘", app.oralText("3 × 4") === "3 乘 4", app.oralText("3 × 4"));
check("空括号读作括号", app.oralText("( )") === "括号", app.oralText("( )"));

/* ---------------- 断言：静音开关 ---------------- */

spoken.length = 0;
sandbox.document.getElementById("voice-enabled").checked = false;   // 取消勾选 = 静音
app.onVoiceToggle();
check("取消勾选后不再朗读", spoken.length === 0);
check("静音设置已写入本地存储", store["xiaozhi.voice"] === "off", store["xiaozhi.voice"]);

sandbox.document.getElementById("voice-enabled").checked = true;    // 重新勾选
app.onVoiceToggle();
check("重新勾选后立即朗读当前题目", spoken.length === 1, spoken.length);
check("语音开关已写入本地存储", store["xiaozhi.voice"] === "on", store["xiaozhi.voice"]);

/* ---------------- 断言：作答反馈 ---------------- */

spoken.length = 0;
app.setProgress({
    correct: false,
    correct_answer: "B",
    correct_text: "8",
    analysis: "5 和 3 合起来是 8。",
    error_analysis: {
        error_type: "计算错误",
        analysis: "你把 5 + 3 算成了 7，再看一眼加法。",
        suggestion: "先算 5 + 3，再加上后面的数。",
    },
    score: 55,
    stage: 1.2,
    total_count: 4,
    correct_count: 2,
    review: {
        message: "答错要马上巩固，5分钟后我们再练一遍这个知识点。",
        next_review_at: "2026-10-04 20:30",
        mastery: 0,
    },
});
app.renderResult(app.getProgress());

check("反馈显示正确答案", /正确答案：<b>B\. 8<\/b>/.test(nodes.feedback.innerHTML));
check("反馈显示艾宾浩斯复习提示",
    /答错要马上巩固/.test(nodes.feedback.innerHTML)
    && /下次复习：2026-10-04 20:30/.test(nodes.feedback.innerHTML));
check("反馈区渲染朗读解析按钮", /读解析/.test(nodes.feedback.innerHTML));
check("答错先给「这里再想一下」与小提示，不出现 ❌",
    /🤔 这里再想一下/.test(nodes.feedback.innerHTML)
    && /计算错误/.test(nodes.feedback.innerHTML)
    && nodes.feedback.innerHTML.indexOf("❌") < 0);
check("答错第一级显示方向提示与「我再试试」",
    /方向提示/.test(nodes.feedback.innerHTML)
    && /我再试试/.test(nodes.feedback.innerHTML));

// 连着再错一次就升到第二级；「我再试试」不影响已经渲染的小提示（重新尝试也要能看到帮助）
app.renderResult(app.getProgress());
check("再错一次升到关键条件（逐级增加帮助）",
    /关键条件/.test(nodes.feedback.innerHTML)
    && /5 \+ 3 算成了 7/.test(nodes.feedback.innerHTML)
    && /再看一眼加法/.test(nodes.feedback.innerHTML));

app.speakAnalysis();
const analysisText = spoken.length ? spoken[spoken.length - 1].text : "";
check("朗读解析含正确答案与讲解",
    analysisText.indexOf("答错了，我们一起看看。") === 0
    && analysisText.indexOf("正确答案是B，8。") > 0
    && analysisText.indexOf("5 和 3 合起来是 8") > 0,
    analysisText);

spoken.length = 0;
app.setProgress(Object.assign({}, app.getProgress(), { correct: true }));
app.renderResult(app.getProgress());
app.speakAnalysis();
check("答对时朗读鼓励语",
    (spoken[spoken.length - 1].text || "").indexOf("答对了，真棒。") === 0,
    spoken[spoken.length - 1].text);

/* 答对分级：普通答对只给 ✓，连对 3 题起才额外鼓励（不洏烟花） */
app.renderResult(app.getProgress());
check("普通答对只说 ✓ 对啦，不出现掌握度",
    nodes.feedback.innerHTML.indexOf("✓ 对啦") >= 0
    && nodes.feedback.innerHTML.indexOf("掌握度") < 0
    && nodes.feedback.innerHTML.indexOf("🔥") < 0);
app.renderResult(app.getProgress());
check("连续答对 3 题才出现 🔥 连续 3 题正确",
    nodes.feedback.innerHTML.indexOf("🔥 连续 3 题正确") >= 0);

/* ---------------- 断言：换题清理 ---------------- */

speechSynthesis.cancelled = 0;
app.resetBoard();
check("换题时停止朗读", speechSynthesis.cancelled >= 1);
check("换题时清空复习面板",
    nodes["review-panel"].innerHTML === "" && nodes["review-panel"].classList.contains("hidden") === true);

/* ---------------- 断言：转义 ---------------- */

app.renderQuestion({
    question_id: 1,
    qtype: "blank",
    subject: "数学",
    knowledge: "<img src=x>",
    difficulty: 50,
    stage: 1,
    question: "<script>alert(1)</script>",
    options: {},
    due_reviews: [],
    due_count: 0,
    review: { stage: 0, mastery: 0, next_review_text: "5分钟后" },
});
check("题目文本被转义",
    nodes.question.innerHTML.indexOf("&lt;script&gt;") > 0
    && nodes.question.innerHTML.indexOf("<script>") < 0);
check("填空题显示输入框", nodes["blank-box"].classList.contains("hidden") === false);

/* ---------------- 断言：知识点目标跟着能力走（V2.6 修正：不再写死 20以内加减法） ---------------- */

const APP_SRC = fs.readFileSync(APP, "utf8");
const HTML_SRC = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const STYLE_SRC = fs.readFileSync(path.join(__dirname, "style.css"), "utf8");

check("知识点输入框不再写死默认值",
    HTML_SRC.indexOf('id="knowledge"') >= 0 && HTML_SRC.indexOf('value="20以内加减法"') < 0);
check("知识点旁边有菲比的推荐提示行", HTML_SRC.indexOf('id="knowledge-hint"') >= 0);
check("自动选点改走自适应引擎的推荐接口", APP_SRC.indexOf("/api/learning/recommend/") >= 0);

/* V2.8 需求：点「开始今天的学习」先进题单模式 —— 先读今天还剩多少题、都是什么题型 */
check("题单模式：练习页先读今天的任务（剩余题数 + 题型）",
    APP_SRC.indexOf("/api/tasks/today?student_id=") >= 0
    && APP_SRC.indexOf('urlParam("sheet") === "1"') >= 0);
check("题单模式：答题时把 task_id 交给后端（按项记 3/5，不错记到别的题型）",
    APP_SRC.indexOf("task_id: sheetActive && sheetBucket()") >= 0);
check("题单模式：题目上方有内部标记位（数学 · 新知识 / 已完成 3/5）",
    HTML_SRC.indexOf('id="sheet-tag"') >= 0 && STYLE_SRC.indexOf(".sheet-tag") >= 0);
check("手机 / 局域网访问时 API 不写死 127.0.0.1（跟着页面来源走）",
    APP_SRC.indexOf("location.protocol") >= 0 && APP_SRC.indexOf("location.origin") >= 0);

const pickOne = app.pickRecommendedKnowledge;
const primaryPick = pickOne({ primary: { knowledge: "两位数乘法", difficulty: 57, reason: "掌握度68，需要强化", action: "practice" } });
check("从 primary 取知识点、难度与动作",
    !!primaryPick && primaryPick.knowledge === "两位数乘法"
    && primaryPick.difficulty === 57 && primaryPick.action === "practice",
    primaryPick && primaryPick.knowledge);
check("primary 缺失时退回 next_action",
    (pickOne({ next_action: { knowledge: "古诗名句", difficulty: 83 } }) || {}).knowledge === "古诗名句");
check("两处都没有就返回 null（不覆盖孩子手填的知识点）",
    pickOne({ primary: {}, next_action: {} }) === null && pickOne(null) === null);
check("三科各自按自己的能力取目标",
    (pickOne({ primary: { knowledge: "20以内加减法" } }) || {}).knowledge === "20以内加减法"
    && (pickOne({ primary: { knowledge: "古诗名句" } }) || {}).knowledge === "古诗名句"
    && (pickOne({ primary: { knowledge: "26个字母" } }) || {}).knowledge === "26个字母");

/* V2.8 题单模式：一页一题；一项做满就收工，做完的项不再出题 */
app.setSheetActive(true);
app.setSheet({
    buckets: [
        { task_id: 11, tag: "数学 · 新知识", subject: "数学", knowledge: "20以内加减法", target: 5, done: 3 },
        { task_id: 12, tag: "数学 · 薄弱训练", subject: "数学", knowledge: "20以内加减法", target: 1, done: 0 },
    ],
    index: 0,
});
app.renderSheetTag();
check("题单：题目上方写清内部标记与这一项的进度 3/5",
    nodes["sheet-tag"].innerHTML.includes("数学 · 新知识")
    && nodes["sheet-tag"].innerHTML.includes("3/5")
    && nodes["sheet-tag"].innerHTML.includes("还差 2 题"),
    nodes["sheet-tag"].innerHTML);

const sheetStep1 = app.sheetAdvance();
check("题单：只做了 3/5 的项再答一题只到 4/5，不换项",
    sheetStep1.finished === false && app.sheetBucket().done === 4 && app.getSheetState().index === 0,
    JSON.stringify(sheetStep1));
const sheetStep2 = app.sheetAdvance();
check("题单：做满 5 题这一项收工，自动换下一项",
    sheetStep2.finished === true && app.getSheetState().index === 1 && app.getSheetState().done === false,
    JSON.stringify(sheetStep2));
app.sheetAdvance();
check("题单：最后一项做完 = 今天全部收工（不再出题）",
    app.getSheetState().done === true && app.getSheetState().index === 2,
    JSON.stringify(app.getSheetState()));
app.setSheetActive(false);

/* 行为：换成真的 fetch，验证「答完一题按能力重挑」与「孩子自己改过就不覆盖」 */
const realFetch = sandbox.fetch;
sandbox.fetch = () => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
        primary: { knowledge: "两位数乘法", difficulty: 57, reason: "掌握度68，需要强化", action: "practice" },
    }),
});

nodes["knowledge"].value = "20以内加减法";
app.setManualKnowledge(false);
app.applyAutoKnowledge(true);

setTimeout(() => {
    check("答完一题后知识点按能力重挑", nodes["knowledge"].value === "两位数乘法",
        nodes["knowledge"].value);
    const hintText = String(nodes["knowledge-hint"].textContent);
    check("提示行说明为什么练这个（不含掌握度/遗忘风险等算法数字）",
        hintText.indexOf("两位数乘法") > 0 && hintText.indexOf("再练几遍") > 0
        && !/掌握度|遗忘风险|[0-9]/.test(hintText),
        hintText);

    app.setManualKnowledge(true);
    nodes["knowledge"].value = "我自己选的";
    app.applyAutoKnowledge(true);

    setTimeout(() => {
        check("孩子自己改过之后菲比不再覆盖", nodes["knowledge"].value === "我自己选的",
            nodes["knowledge"].value);

        // V2.8 题单模式：buildSheet 先读「今天还剩多少题、都是什么题型」，做完的项不再出题
        sandbox.fetch = () => Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                tasks: [
                    { task_id: 31, title: "数学 · 新知识", subject: "数学", knowledge: "20以内加减法",
                      target_count: 5, complete_count: 3, status: "doing", priority: 1 },
                    { task_id: 32, title: "数学 · 薄弱训练", subject: "数学", knowledge: "20以内加减法",
                      target_count: 2, complete_count: 2, status: "done", priority: 2 },
                    { task_id: 33, title: "语文 · 复习恢复", subject: "语文", knowledge: "古诗名句",
                      target_count: 4, complete_count: 0, status: "pending", priority: 3 },
                ],
            }),
        });
        app.buildSheet().then(sheet => {
            check("题单：读完只剩 2 项（做完的那一项不再出题）",
                sheet.buckets.length === 2
                && sheet.buckets[0].task_id === 31 && sheet.buckets[0].done === 3 && sheet.buckets[0].target === 5
                && sheet.buckets[1].task_id === 33,
                JSON.stringify(sheet.buckets.map(b => [b.task_id, b.done, b.target])));
            check("题单：内部标记沿用今日任务的题型标题",
                sheet.buckets[0].tag === "数学 · 新知识", sheet.buckets[0].tag);

            sandbox.fetch = realFetch;
            console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
            process.exit(ok ? 0 : 1);
        });
    }, 20);
}, 20);
