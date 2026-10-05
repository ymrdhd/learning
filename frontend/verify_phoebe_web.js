// ==============================================================
// 能力契约｜验证：庆祝浮层（phoebe.js）素材路径 / 三页调用守卫 / 样式存在
// 入口：脚本自身：node frontend/verify_phoebe_web.js
// 依赖：Node fs/vm（沙箱加载 phoebe.js，并字符串断言 app.js / diagnostic_test.js / wrong_book.js / style.css）
// 不负责：业务渲染 → 各页验证脚本
// 验证：node frontend/verify_phoebe_web.js
// 被调用：verify_all.py（套件 phoebeweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 前端菲比庆祝模块测试。
 *
 * 覆盖：素材文件齐全、答对弹出随机表情包、连对计数、答错清零、
 *       诊断页短闪现、三个答题页都引入了 phoebe.js。
 *
 * 用法：node frontend/verify_phoebe_web.js
 * 全部通过时退出码为 0。
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = __dirname;
const ASSET_DIR = path.join(DIR, "assets", "phoebe");
let ok = true;

function check(name, cond, extra) {
    console.log((cond ? "PASS  " : "FAIL  ") + name + (extra === undefined ? "" : "  | " + extra));
    if (!cond) ok = false;
}

function readFile(name) {
    return fs.readFileSync(path.join(DIR, name), "utf8");
}

/* ---------------- 1. 素材文件 ---------------- */

const phoebe = require(path.join(DIR, "phoebe.js"));

check("phoebe.js 导出 celebrateCorrect", typeof phoebe.celebrateCorrect === "function");
check("phoebe.js 导出 resetStreak", typeof phoebe.resetStreak === "function");
check("表情包至少有 2 张（能随机切换）", phoebe.IMAGES.length >= 2, phoebe.IMAGES.join(", "));

const allImages = phoebe.IMAGES.every(name => {
    const file = path.join(ASSET_DIR, name);
    return fs.existsSync(file) && fs.statSync(file).size > 1000;
});
check("声明的表情包图片都已下载", allImages, phoebe.IMAGES.join(", "));

const allSounds = phoebe.SOUNDS.every(name =>
    fs.existsSync(path.join(ASSET_DIR, name)) && fs.statSync(path.join(ASSET_DIR, name)).size > 1000);
check("声明的音效都已下载", allSounds, phoebe.SOUNDS.join(", "));

const pngOk = phoebe.IMAGES.every(name => {
    const head = fs.readFileSync(path.join(ASSET_DIR, name)).subarray(0, 8);
    return head.equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
});
check("表情包都是合法 PNG", pngOk);

check("素材说明文件存在", fs.existsSync(path.join(ASSET_DIR, "manifest.json")));
check("样式表有庆祝弹窗样式", readFile("style.css").includes(".phoebe-celebrate"));

/* ---------------- 2. 庆祝逻辑（DOM 打桩） ---------------- */

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

function makeNode(id) {
    const node = {
        id,
        innerHTML: "",
        className: "",
        dataset: {},
        children: [],
        setAttribute() {},
        appendChild(child) { this.children.push(child); return child; },
    };
    node.classList = makeClassList();
    return node;
}

function makeDocument() {
    const body = makeNode("body");
    const byId = {};

    // 真实 DOM 里 append 之后就能 getElementById 找到，打桩保持一致
    const realAppend = body.appendChild.bind(body);
    body.appendChild = node => {
        realAppend(node);
        if (node.id) byId[node.id] = node;
        return node;
    };

    return {
        body,
        byId,
        getElementById(id) { return byId[id] || null; },
        createElement: makeNode,
    };
}

function loadPhoebeInSandbox() {
    const document = makeDocument();
    const sandbox = { document, console, setTimeout, clearTimeout, Math, Date };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;

    vm.createContext(sandbox);
    vm.runInContext(readFile("phoebe.js"), sandbox, { filename: "phoebe.js" });
    return { sandbox, document };
}

const { sandbox, document: doc } = loadPhoebeInSandbox();

check("沙箱里注册了全局 celebrateCorrect", typeof sandbox.celebrateCorrect === "function");
check("初始连对数为 0", sandbox.phoebe.currentStreak() === 0);

sandbox.celebrateCorrect({ duration: 20 });

const overlay = doc.byId["phoebe-celebrate"];
check("答对后创建了庆祝弹窗", Boolean(overlay));
check("弹窗带 show 类（触发动画）", overlay && overlay.className.includes("show"));
check("弹窗里渲染了表情包图片",
    Boolean(overlay) && /assets\/phoebe\/(phoebe(_\d)?\.png)/.test(overlay.innerHTML),
    overlay && overlay.innerHTML.slice(0, 90));
check("弹窗里有庆祝文案", Boolean(overlay) && overlay.innerHTML.includes("phoebe-word"));
check("连对数累加到 1", sandbox.phoebe.currentStreak() === 1);

sandbox.celebrateCorrect({ duration: 20 });
check("再答对连对数累加到 2", sandbox.phoebe.currentStreak() === 2);

sandbox.phoebe.resetStreak();
check("答错后连对数清零", sandbox.phoebe.currentStreak() === 0);

/* 素材路径是相对页面的，前四个页面都在 frontend 根目录下 */
check("图片路径使用相对目录",
    readFile("phoebe.js").includes('ASSET_DIR = "assets/phoebe/"'));

/* ---------------- 3. 三个答题页都接入了庆祝 ---------- */

const PAGES = [
    { html: "index.html", js: "app.js" },
    { html: "diagnostic_test.html", js: "diagnostic_test.js" },
    { html: "wrong_book.html", js: "wrong_book.js" },
];

for (const page of PAGES) {
    const html = readFile(page.html);
    check(`${page.html} 引入了 phoebe.js`, html.includes('src="phoebe.js"'));
    check(`${page.html} 先加载 phoebe.js 再加载 ${page.js}`,
        html.indexOf('src="phoebe.js"') < html.indexOf(`src="${page.js}"`));
}

check("练习页把对错交给庆祝函数", readFile("app.js").includes("celebrateAnswer(d.correct, upgrade)"));
check("练习页答对调用 celebrateCorrect", readFile("app.js").includes("celebrateCorrect("));
check("练习页答错清零连对", readFile("app.js").includes("phoebeResetStreak()"));
check("诊断页答对也弹表情包", readFile("diagnostic_test.js").includes("celebrateCorrect({"));
check("诊断页用短闪现且不配音效",
    /celebrateCorrect\(\{\s*duration:\s*\d+,\s*sound:\s*false/.test(readFile("diagnostic_test.js")));
check("错题本答对也弹表情包", readFile("wrong_book.js").includes("celebrateCorrect({"));
check("庆祝调用有 typeof 守卫",
    readFile("app.js").includes('typeof celebrateCorrect !== "function"')
    && readFile("diagnostic_test.js").includes('typeof celebrateCorrect !== "function"')
    && readFile("wrong_book.js").includes('typeof celebrateCorrect === "function"'));
check("练习页守卫生成了独立函数", readFile("app.js").includes("function celebrateAnswer(correct, upgrade)"));

/* ---------------- 汇总 ---------------- */

console.log("\nRESULT: " + (ok ? "ALL PASS" : "HAS FAILURES"));
process.exit(ok ? 0 : 1);
