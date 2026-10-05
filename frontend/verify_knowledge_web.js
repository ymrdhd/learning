// ==============================================================
// 能力契约｜验证：知识三页（知识地图/错题本/学习建议）DOM id 与渲染逻辑
// 入口：脚本自身：node frontend/verify_knowledge_web.js
// 依赖：Node fs/vm（loadModule 加载 html + js + 模拟 fetch）
// 不负责：诊断页 → verify_diagnostic_web.js
// 验证：node frontend/verify_knowledge_web.js
// 被调用：verify_all.py（套件 knowweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * V2.3 知识与错题前端测试：知识掌握地图 / 错题中心 / 学习建议 三个页面 + 各自的 JS 逻辑。
 *
 * 用 VM + DOM 打桩跑真实的 frontend/*.js，不需要浏览器、不需要后端。
 * 覆盖：页面与脚本引用一致、$("id") 引用的元素都真实存在、入口链接、
 *       领域卡片与展开收起、错题统计与相似题作答、学习建议渲染顺序、
 *       以及星级 / 百分比 / 状态文案等纯函数（分母为 0、超过 100% 等边界）。
 *
 * 用法：node frontend/verify_knowledge_web.js
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

/* ---------------- 1. 页面与脚本一致性 ---------------- */

const PAGES = [
    { html: "knowledge_map.html", js: "knowledge_map.js" },
    { html: "wrong_book.html", js: "wrong_book.js" },
    { html: "study_advice.html", js: "study_advice.js" },
];

const PAGE_LINKS = ["index.html", "diagnostic.html", "knowledge_map.html", "wrong_book.html", "study_advice.html"];

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
        && PAGE_LINKS.filter(link => link !== page.html).every(link => html.includes(`href="${link}"`)));

    check(`${page.js} 顶部使用统一的 API 常量`,
        js.includes('location.protocol') && js.includes('"http://127.0.0.1:8000"'));
}

const indexHtml = readFile("index.html");
check("index.html 有知识地图入口", indexHtml.includes('href="knowledge_map.html"'));
check("index.html 有错题中心入口", indexHtml.includes('href="wrong_book.html"'));
// V2.5 需求变更：能力水平改由训练成绩自动推断，练习页入口换成 ability.html
check("index.html 入口指向自动能力水平页",
    indexHtml.includes('href="ability.html"'));

const styleCss = readFile("style.css");
check("style.css 追加了 V2.3 样式且保留 V2.2 样式",
    styleCss.includes("V2.3") && styleCss.includes(".km-row") && styleCss.includes(".domain-card")
    && styleCss.includes(".wrong-item") && styleCss.includes(".badge.st-new"));

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

/* 把一段 HTML 里的 <button> 解析成假的按钮对象 */
function parseButtons(html) {
    return parseButtonTags(String(html || ""), /<button\b([^>]*)>/g);
}

function parseButtonTags(html, tagRe) {
    const found = [];
    let match;

    while ((match = tagRe.exec(html)) !== null) {
        const attrs = parseAttrs(match[1]);
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
            onclick: attrs.onclick || "",
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

function parseAttrs(text) {
    const attrs = {};
    const attrRe = /([a-zA-Z-]+)(?:="([^"]*)")?/g;
    let a;
    while ((a = attrRe.exec(text)) !== null) {
        attrs[a[1]] = a[2] === undefined ? "" : a[2];
    }
    return attrs;
}

/* 页面里静态写死的 select：取第一个 option 的 value 作为默认值 */
function parseSelectDefaults(html) {
    const defaults = {};
    const re = /<select\b([^>]*)>([\s\S]*?)<\/select>/g;
    let m;
    while ((m = re.exec(html)) !== null) {
        const attrs = parseAttrs(m[1]);
        const option = /<option([^>]*)>([^<]*)<\/option>/.exec(m[2]);
        if (!attrs.id || !option) continue;
        const oattrs = parseAttrs(option[1]);
        defaults[attrs.id] = oattrs.value === undefined ? option[2].trim() : oattrs.value;
    }
    return defaults;
}

function parseTags(html) {
    const tags = {};
    const re = /<(select|input|div|p|span|ul|ol)\b([^>]*)>/g;
    let m;
    while ((m = re.exec(html)) !== null) {
        const attrs = parseAttrs(m[2]);
        if (attrs.id) tags[attrs.id] = m[1];
    }
    return tags;
}

function buildContext(htmlFile, payloads, search) {
    const html = readFile(htmlFile);
    const ids = [...new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]))];
    const tags = parseTags(html);
    const selectDefaults = parseSelectDefaults(html);
    const staticButtons = parseButtonTags(html, /<button\b([^>]*)>/g);
    const nodes = {};
    const calls = [];

    for (const id of ids) {
        const el = {
            id,
            value: Object.prototype.hasOwnProperty.call(selectDefaults, id) ? selectDefaults[id] : "",
            checked: false,
            disabled: false,
            textContent: "",
            dataset: {},
            style: {},
            href: "",
            focus() {},
        };
        el.classList = makeClassList("");

        // select 的选项是 innerHTML 填进去的：填完自动选中第一项，跟浏览器一致
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

    const document = {
        getElementById: id => nodes[id] || null,
        querySelectorAll: selector => {
            const key = selector.replace(/^[.#]/, "");
            let results = staticButtons.filter(b => b._classes.has(key));
            for (const id of Object.keys(nodes)) {
                results = results.concat(parseButtons(nodes[id].innerHTML).filter(b => b._classes.has(key)));
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
            origin: ORIGIN,
            search: search || "",
            href: "",
        },
        sessionStorage: {
            store: {},
            getItem(k) { return Object.prototype.hasOwnProperty.call(this.store, k) ? this.store[k] : null; },
            setItem(k, v) { this.store[k] = String(v); },
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
        SpeechSynthesisUtterance: function (text) { this.text = text; },
        URLSearchParams,
        Number,
        Math,
        JSON,
    };
    context.window = context;
    context.globalThis = context;

    return { context, nodes, calls, staticButtons };
}

function loadModule(htmlFile, jsFile, payloads, exportsSource, search) {
    const { context, nodes, calls, staticButtons } = buildContext(htmlFile, payloads, search);
    const html = readFile(htmlFile);
    const source = readFile(jsFile) + "\n;globalThis.__x = {" + exportsSource + "};";
    vm.createContext(context);
    // 页面里真实加载的共享 UI 层（浏览器里就是普通 <script>，测试必须保持一致）
    for (const shared of ["ui-shell.js", "kid-lang.js", "ui-components.js"]) {
        if (html.includes('src="' + shared + '"')) {
            vm.runInContext(readFile(shared), context, { filename: shared });
        }
    }
    vm.runInContext(source, context, { filename: jsFile });
    return { context, nodes, calls, staticButtons, api: context.__x };
}

const EX = name => `${name}: typeof ${name} === "function" ? ${name} : null`;

/* ---------------- 2. 知识掌握地图 ---------------- */

const MASTERY = {
    student_id: 1,
    subject: "数学",
    subjects_summary: [{ subject: "数学", average_mastery: 68.5 }, { subject: "语文", average_mastery: 0 }],
    summary: { knowledge_count: 12, mastered: 4, learning: 5, weak: 3, average_mastery: 68.5 },
    domains: [
        {
            domain: "计算",
            mastery_score: 82,
            stars: 4,
            star_text: "★★★★☆",
            knowledge_count: 6,
            children: [
                {
                    knowledge_id: "表内乘法", knowledge_point_id: 12, grade: 2, semester: "上册", chapter: "计算",
                    mastery_score: 88, confidence: 0.7, level: "熟练", total_questions: 12, correct_questions: 10,
                    wrong_questions: 2, last_practice_time: "2026-10-04 20:39",
                    next_review_time: "2026-10-05 20:39", path: "数学 / 计算 / 表内乘法",
                },
                { knowledge_id: "除法初步", mastery_score: 55, level: "巩固中", total_questions: 4, correct_questions: 2 },
            ],
        },
        {
            domain: "应用题",
            mastery_score: 45,
            star_text: "★★☆☆☆",
            knowledge_count: 6,
            children: [{ knowledge_id: "两步计算应用题", mastery_score: 45, level: "薄弱", total_questions: 6, correct_questions: 2 }],
        },
    ],
    knowledge: [
        { knowledge_id: "表内乘法", mastery_score: 88, level: "熟练", total_questions: 12, correct_questions: 10 },
        { knowledge_id: "除法初步", mastery_score: 55, level: "巩固中", total_questions: 4, correct_questions: 2 },
        { knowledge_id: "两步计算应用题", mastery_score: 45, level: "薄弱", total_questions: 6, correct_questions: 2 },
    ],
};

async function testKnowledgeMap() {
    const mod = loadModule(
        "knowledge_map.html",
        "knowledge_map.js",
        url => {
            if (url.includes("/students")) {
                return [{ id: 1, name: "小朋友A", grade_text: "一年级" }];
            }
            if (url.includes("/api/mastery/")) return MASTERY;
            return undefined;
        },
        [
            EX("barWidth"), EX("masteryClass"), EX("starCount"), EX("starText"), EX("percent"),
            EX("levelClass"), EX("renderSummary"), EX("renderDomains"), EX("renderMastery"),
            EX("toggleDomain"), EX("selectSubject"), EX("isExpanded"), EX("jsonFetch"),
            "getSubject: () => selectedSubject",
        ].join(",")
    );

    await sleep(30);
    const { nodes, calls, api, context } = mod;
    const summary = nodes["summary"].innerHTML;
    const domains = nodes["domains"].innerHTML;

    check("地图页列出学生", nodes["student"].innerHTML.includes("小朋友A"));
    check("地图页汇总知识点总数", summary.includes(">12<") && summary.includes("知识点总数"));
    check("地图页汇总已掌握/巩固中/薄弱",
        summary.includes("已掌握") && summary.includes("巩固中") && summary.includes("薄弱"));
    check("地图页汇总用儿童状态代替裸百分比",
        summary.includes("整体状态") && summary.includes("ph-status") && !summary.includes("68.5"), summary);
    check("地图页请求带学生与科目",
        calls.some(c => c.url.includes("/api/mastery/1?subject=%E6%95%B0%E5%AD%A6")), calls[1] && calls[1].url);

    check("地图页渲染领域卡片（带探索图标）",
        domains.includes("计算") && domains.includes("应用题") && domains.includes("🏡"));
    check("地图页渲染领域星级", domains.includes("★★★★☆") && domains.includes("★★☆☆☆"));
    check("地图页领域用儿童状态标签代替裸分数",
        domains.includes("ph-status") && !domains.includes(">82<"), domains.slice(0, 160));
    check("地图页默认展开知识点", domains.includes("表内乘法") && domains.includes("两步计算应用题"));
    check("知识点行有进度条宽度", domains.includes('style="width:88%"'), domains.slice(0, 120));
    check("知识点行有分数与题数", domains.includes(">88<") && domains.includes("10/12 题"));
    check("知识点行有等级徽标", domains.includes("lv-good") && domains.includes("熟练"));
    check("掌握度配色分档（55 分偏低）", domains.includes("width:55%") && domains.includes("low"), "");

    check("领域默认展开", api.isExpanded("计算") === true);
    api.toggleDomain("计算");
    check("点一次领域收起了知识点",
        api.isExpanded("计算") === false && !nodes["domains"].innerHTML.includes("表内乘法")
        && nodes["domains"].innerHTML.includes("计算"), "");
    api.toggleDomain("计算");
    check("再点一次又展开",
        api.isExpanded("计算") === true && nodes["domains"].innerHTML.includes("表内乘法"));

    check("条形宽度按分数", api.barWidth(88) === 88);
    check("分数超过 100 截断到 100%", api.barWidth(150) === 100 && api.barWidth(100) === 100);
    check("负分不出现负数宽度", api.barWidth(-5) === 0);
    check("没有分数时不崩", api.barWidth(null) === 0 && api.barWidth(undefined) === 0 && api.barWidth("abc") === 0);
    check("掌握度配色分档",
        api.masteryClass(88) === "good" && api.masteryClass(80) === "good"
        && api.masteryClass(65) === "mid" && api.masteryClass(60) === "mid"
        && api.masteryClass(59) === "low" && api.masteryClass(0) === "low");
    check("星级换算", api.starCount(68.5) === 3 && api.starCount(82) === 4 && api.starCount(100) === 5);
    check("没有数据时 0 颗星", api.starCount(0) === 0 && api.starCount(null) === 0 && api.starText(0) === "☆☆☆☆☆");
    check("星级文案", api.starText(68.5) === "★★★☆☆" && api.starText(95) === "★★★★★");
    check("百分比分母为 0 不崩", api.percent(0, 0) === 0 && api.percent(3, 0) === 0);
    check("百分比超过 100% 截断", api.percent(30, 15) === 100 && api.percent(1, 2) === 50);
    check("等级徽标映射",
        api.levelClass("熟练") === "lv-good" && api.levelClass("初步掌握") === "lv-ok"
        && api.levelClass("巩固中") === "lv-mid" && api.levelClass("薄弱") === "lv-low"
        && api.levelClass("未练习") === "lv-none" && api.levelClass("") === "lv-none");

    api.selectSubject("语文");
    check("科目切换记录选择", api.getSubject() === "语文", api.getSubject());
    check("科目切换会重新拉数据",
        calls.some(c => decodeURIComponent(c.url).includes("subject=语文")), calls[calls.length - 1].url);
    const englishBtn = mod.staticButtons.filter(b => b.dataset.subject === "语文")[0];
    check("科目切换会高亮卡片", englishBtn && englishBtn.classList.contains("active"));

    const rejected = await api.jsonFetch(ORIGIN + "/api/not-exist")
        .then(() => false).catch(() => true);
    check("jsonFetch 对非 200 抛错", rejected === true);

    api.renderMastery({ summary: {}, domains: [], knowledge: [] });
    check("没有数据时给友好提示与诊断入口",
        nodes["domains"].innerHTML.includes("还没有知识地图数据")
        && nodes["domains"].innerHTML.includes("diagnostic.html"));
    check("没有数据时汇总不崩", nodes["summary"].innerHTML.includes("知识点总数"));
    check("空数据下展开状态不崩", api.toggleDomain("不存在") === false || true);
    context.location.href = "";
}

/* ---------------- 3. 错题中心 ---------------- */

const WRONG = {
    student_id: 1,
    stats: { NEW: 12, LEARNING: 8, MASTERED: 20, total: 40 },
    items: [{
        id: 3, question_id: 25, subject: "数学", knowledge: "两步计算应用题", status: "NEW", status_text: "未掌握",
        wrong_count: 2, correct_streak: 0, last_error_type: "审题错误", last_wrong_time: "2026-10-04 20:39",
        question: "小明有12个苹果，吃掉3个，还剩多少？", correct_answer: "9",
        analysis: "没有看清题目问的是还剩多少。", next_review_time: "2026-10-05 20:39",
    }],
};

const SIMILAR = {
    question_id: 31, qtype: "choice", subject: "数学", knowledge: "两步计算应用题", difficulty: 55,
    question: "小红有15颗糖，送给弟弟5颗，还剩多少颗？",
    options: { A: "20", B: "10", C: "5", D: "15" },
    stage: 3.2, is_review: false, due_reviews: [], due_count: 0,
};

const SUBMIT_RIGHT = {
    correct: true, correct_answer: "B", correct_text: "10", analysis: "", qtype: "choice", stage: 3.2,
    score: 60, total_count: 5, correct_count: 4, knowledge: "两步计算应用题", error_analysis: null,
};

const SUBMIT_WRONG = {
    correct: false, correct_answer: "B", correct_text: "10", analysis: "答案不对。", qtype: "choice", stage: 3.2,
    score: 40, total_count: 5, correct_count: 3, knowledge: "两步计算应用题",
    error_analysis: {
        error_type: "概念错误",
        analysis: "把减少理解成了增加，所以用加法算成了 20。",
        suggestion: "重新练习：减法的含义（拿走、减少用减法）",
    },
};

async function testWrongBook() {
    const mod = loadModule(
        "wrong_book.html",
        "wrong_book.js",
        (url, options) => {
            if (url.includes("/submit")) {
                const body = JSON.parse(options.body || "{}");
                return body.answer === "B" ? SUBMIT_RIGHT : SUBMIT_WRONG;
            }
            if (url.includes("/question?")) return SIMILAR;
            if (url.includes("/api/wrong_questions/")) return WRONG;
            if (url.includes("/students")) return [{ id: 1, name: "小朋友A", grade_text: "一年级" }];
            return undefined;
        },
        [
            EX("statusText"), EX("statusClass"), EX("percent"), EX("renderStats"), EX("renderList"),
            EX("openPractice"), EX("answerPractice"), EX("selectStatus"), EX("onSubjectChange"),
            "getStatus: () => selectedStatus", "getItems: () => wrongItems",
        ].join(",")
    );

    await sleep(30);
    const { nodes, calls, api, staticButtons } = mod;
    const statHtml = nodes["stats"].innerHTML;
    const listHtml = nodes["list"].innerHTML;

    check("错题页渲染待攻克统计", statHtml.includes(">12<") && statHtml.includes("待攻克"));
    check("错题页渲染训练中统计", statHtml.includes(">8<") && statHtml.includes("训练中"));
    check("错题页渲染已攻克统计", statHtml.includes(">20<") && statHtml.includes("已攻克"));
    check("错题页渲染题干", listHtml.includes("小明有12个苹果"), listHtml.slice(0, 60));
    check("错题页渲染知识点与状态徽标",
        listHtml.includes("两步计算应用题") && listHtml.includes("待攻克") && listHtml.includes("st-new"));
    check("错题页渲染错误次数与错因",
        listHtml.includes("错了 2 次") && listHtml.includes("审题错误") && listHtml.includes("没有看清题目问的是还剩多少"));
    check("错题页显示正确答案", listHtml.includes("正确答案：9"));
    check("错题页有练一练按钮", listHtml.includes("练一练相似题") && listHtml.includes("openPractice(3)"));

    const before = calls.filter(c => c.url.includes("/api/wrong_questions/")).length;
    await api.openPractice(3);
    const withQuestion = nodes["list"].innerHTML;
    check("练一练拉了同知识点的相似题",
        calls.some(c => decodeURIComponent(c.url).includes("/question?")
            && decodeURIComponent(c.url).includes("knowledge=两步计算应用题")
            && c.url.includes("qtype=choice")),
        calls[calls.length - 1].url);
    check("相似题请求带学生与科目",
        calls.some(c => decodeURIComponent(c.url).includes("student_id=1") && decodeURIComponent(c.url).includes("subject=数学")));
    check("卡片内直接渲染相似题与选项",
        withQuestion.includes("小红有15颗糖") && withQuestion.includes("A. 20") && withQuestion.includes("D. 15"));
    check("相似题不泄露答案字段", !withQuestion.includes("correct_answer") && !withQuestion.includes("正确答案：10"));

    await api.answerPractice(3, "A");
    const post = calls.filter(c => c.url.includes("/submit"))[0];
    check("提交相似题答案调用 /submit", Boolean(post), post && post.url);
    check("提交内容含 question_id / answer / student_id",
        post && JSON.parse(post.options.body).question_id === 31
        && JSON.parse(post.options.body).answer === "A"
        && JSON.parse(post.options.body).student_id === 1,
        post && post.options.body);

    let box = nodes["list"].innerHTML;
    box = box.slice(box.lastIndexOf('class="practice-box"'));
    check("答错先讲原因", box.includes("把减少理解成了增加"), box.slice(0, 80));
    check("答错给出重新练习建议", box.includes("重新练习：减法的含义"));
    check("答错不拿正确答案当重点", !box.includes("正确答案"), box.slice(0, 120));
    check("作答后重新拉错题刷新状态",
        calls.filter(c => c.url.includes("/api/wrong_questions/")).length > before);

    await api.answerPractice(3, "B");
    box = nodes["list"].innerHTML;
    box = box.slice(box.lastIndexOf('class="practice-box"'));
    check("答对给出正向反馈", box.includes("✓ 对啦") && box.includes("训练中"), box.slice(0, 80));

    check("状态文案映射",
        api.statusText("NEW") === "🔴 待攻克" && api.statusText("LEARNING") === "🟡 训练中"
        && api.statusText("MASTERED") === "🟢 已攻克" && api.statusText("X") === "未知");
    check("状态徽标映射",
        api.statusClass("NEW") === "st-new" && api.statusClass("LEARNING") === "st-learning"
        && api.statusClass("MASTERED") === "st-mastered" && api.statusClass("X") === "st-unknown");
    check("错题百分比分母为 0 不崩", api.percent(0, 0) === 0 && api.percent(5, 0) === 0);
    check("错题百分比截断到 100%", api.percent(60, 40) === 100);

    api.selectStatus("LEARNING");
    check("状态筛选记录选择", api.getStatus() === "LEARNING", api.getStatus());
    check("状态筛选带 status 参数",
        calls.some(c => c.url.includes("status=LEARNING")), calls[calls.length - 1].url);
    const activeBtn = staticButtons.filter(b => b.dataset.status === "LEARNING")[0];
    const allBtn = staticButtons.filter(b => b.dataset.status === "")[0];
    check("状态按钮高亮切换",
        activeBtn && activeBtn.classList.contains("active") && allBtn && !allBtn.classList.contains("active"));

    nodes["subject"].value = "数学";
    api.onSubjectChange();
    await sleep(10);
    check("科目筛选带 subject 参数",
        calls.some(c => decodeURIComponent(c.url).includes("subject=数学") && c.url.includes("status=LEARNING")),
        calls[calls.length - 1].url);

    api.renderList([]);
    check("没有错题时给鼓励文案", nodes["list"].innerHTML.includes("暂时没有需要攻克的错题"));
    check("错题列表状态被清空", api.getItems().length === 0);
}

/* ---------------- 4. 学习建议页 ---------------- */

const ADVICE_REPORT = {
    student_id: 1,
    subject: "数学",
    available: true,
    average_mastery: 68.5,
    stars: 3,
    star_text: "★★★☆☆",
    domain_summary: [{ domain: "计算", mastery_score: 82, stars: 4, star_text: "★★★★☆", knowledge_count: 6 }],
    mastered: [{ knowledge: "表内乘法", mastery_score: 88, confidence: 0.7, level: "熟练", total_questions: 12, correct_questions: 10 }],
    weak: [{ knowledge: "两步计算应用题", mastery_score: 45, confidence: 0.5, level: "薄弱", total_questions: 6, correct_questions: 2 }],
    error_summary: [{ error_type: "审题错误", count: 3 }],
    advice: [
        "今天建议先复习：两步计算应用题（掌握度 45）",
        "练习 5 道两位数加法，做完读一遍题目",
        "巩固表内乘法，争取全部答对",
    ],
    generated_time: "2026-10-04 20:45",
};

async function testStudyAdvice() {
    const mod = loadModule(
        "study_advice.html",
        "study_advice.js",
        url => {
            if (url.includes("/students")) return [{ id: 1, name: "小朋友A", grade_text: "一年级" }];
            if (url.includes("/api/report/knowledge")) return ADVICE_REPORT;
            return undefined;
        },
        [
            EX("barWidth"), EX("masteryClass"), EX("starCount"), EX("starText"), EX("percent"),
            EX("levelClass"), EX("renderAdvice"), EX("renderWeak"), EX("renderErrors"),
            EX("renderMastered"), EX("renderFooter"), EX("renderReport"), EX("selectSubject"),
            "getSubject: () => selectedSubject",
        ].join(",")
    );

    await sleep(30);
    const { nodes, calls, api } = mod;
    const advice = nodes["advice"].innerHTML;
    const weak = nodes["weak"].innerHTML;
    const errors = nodes["errors"].innerHTML;
    const mastered = nodes["mastered"].innerHTML;
    const footer = nodes["footer"].innerHTML;

    check("建议页按顺序编号渲染 advice",
        advice.includes("1. 今天建议先复习")
        && advice.indexOf("1. 今天建议先复习") < advice.indexOf("2. 练习 5 道两位数加法")
        && advice.indexOf("2. 练习 5 道两位数加法") < advice.indexOf("3. 巩固表内乘法"),
        advice.slice(0, 80));
    check("建议页建议文案已儿童化（不出现裸掌握度）",
        advice.includes("两步计算应用题（🌿 正在学习）") && advice.includes("巩固表内乘法")
        && !advice.includes("掌握度 45"));

    check("建议页渲染需要提升的知识点",
        weak.includes("两步计算应用题") && weak.includes(">45<") && weak.includes("2/6 题")
        && weak.includes("薄弱") && weak.includes("low"));
    check("建议页渲染错因提示", errors.includes("审题错误") && errors.includes("3 次"));
    check("建议页已经掌握用儿童状态标签",
        mastered.includes("表内乘法") && mastered.includes("ph-status") && !mastered.includes("掌握度"));
    check("建议页底部用儿童状态与星级代替平均掌握度",
        footer.includes("★★★☆☆") && footer.includes("ph-status") && !footer.includes("平均掌握度"));
    check("建议页底部有跳转链接",
        footer.includes("knowledge_map.html") && footer.includes("wrong_book.html"));

    const page = ["advice", "weak", "errors", "mastered", "footer"].map(id => nodes[id].innerHTML).join("");
    check("页面顺序：advice → weak → error_summary",
        page.indexOf("今天建议") < page.indexOf("需要提升的知识点")
        && page.indexOf("需要提升的知识点") < page.indexOf("错因提示")
        && page.indexOf("错因提示") < page.indexOf("已经掌握"));

    check("建议页请求带学生与科目",
        calls.some(c => c.url.includes("/api/report/knowledge?student_id=1&subject=%E6%95%B0%E5%AD%A6")),
        calls[1] && calls[1].url);

    check("星级/百分比纯函数可用",
        api.starText(68.5) === "★★★☆☆" && api.barWidth(150) === 100 && api.percent(2, 0) === 0
        && api.masteryClass(45) === "low" && api.levelClass("薄弱") === "lv-low");

    check("没有错因时给鼓励提示", api.renderErrors([]).includes("还没有错题记录，继续保持！"));
    api.renderReport(Object.assign({}, ADVICE_REPORT, { error_summary: [] }));
    check("接口没给错因时页面也提示",
        nodes["errors"].innerHTML.includes("还没有错题记录，继续保持！"));

    api.renderReport({ available: false, student_id: 1, subject: "数学", message: "还没有做过这项能力诊断" });
    check("未诊断时给友好提示与诊断入口",
        nodes["advice"].innerHTML.includes("还没有做过这项能力诊断")
        && nodes["advice"].innerHTML.includes("diagnostic.html"));
    check("未诊断时清空其它区块",
        nodes["weak"].innerHTML === "" && nodes["errors"].innerHTML === ""
        && nodes["mastered"].innerHTML === "" && nodes["footer"].innerHTML === "");

    api.selectSubject("英语");
    check("建议页科目切换记录选择", api.getSubject() === "英语", api.getSubject());
    check("建议页科目切换会重新拉数据",
        calls.some(c => decodeURIComponent(c.url).includes("subject=英语")), calls[calls.length - 1].url);
    const btn = mod.staticButtons.filter(b => b.dataset.subject === "英语")[0];
    check("建议页科目卡片高亮", btn && btn.classList.contains("active"));
}

/* ---------------- 运行 ---------------- */

(async () => {
    try {
        await testKnowledgeMap();
        await testWrongBook();
        await testStudyAdvice();
    } catch (err) {
        check("前端测试执行未抛异常", false, err && err.stack ? err.stack.split("\n").slice(0, 2).join(" ") : err);
    }

    console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
    process.exit(ok ? 0 : 1);
})();
