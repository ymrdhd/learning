// ==============================================================
// 能力契约｜验证：菲比三视图立牌（phoebe3d.js）素材 / 纯函数 / DOM 行为 / 页面接入
// 入口：脚本自身：node frontend/verify_phoebe3d_web.js
// 依赖：Node fs/path/vm（沙箱加载 phoebe3d.js + DOM 打桩），字符串断言各页面接入
// 不负责：业务答题流程 → verify_adaptive_web.js / verify_web.js
// 验证：node frontend/verify_phoebe3d_web.js
// 被调用：verify_all.py（套件 phoebe3dweb）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 菲比三视图 3D 立牌前端测试。
 *
 * 覆盖：素材齐全、旋转角度→视角/权重换算、拖拽后的角度归一化、
 *       答对/答错的立牌动作与字幕、两个答题页的接入与加载顺序。
 *
 * 用法：node frontend/verify_phoebe3d_web.js
 * 全部通过时退出码为 0。
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = __dirname;
const ASSET_DIR = path.join(DIR, "assets", "phoebe3d");
let ok = true;

function check(name, cond, extra) {
    console.log((cond ? "PASS  " : "FAIL  ") + name + (extra === undefined ? "" : "  | " + extra));
    if (!cond) ok = false;
}

function readFile(name) {
    return fs.readFileSync(path.join(DIR, name), "utf8");
}

/* ---------------- 1. 素材文件 ---------------- */

const phoebe3d = require(path.join(DIR, "phoebe3d.js"));

check("phoebe3d.js 导出 mount", typeof phoebe3d.mount === "function");
check("phoebe3d.js 导出 feedback", typeof phoebe3d.feedback === "function");
check("四个旋转视角（360° 一圈）", phoebe3d.FRAMES.length === 4, phoebe3d.FRAMES.map(f => f.key + "@" + f.angle).join(", "));

/* 素材：6 情绪 × 3 视角 = 18 张，画布统一、底对齐 */
const MOOD_KEYS = ["happy", "sad", "like", "cheer", "cute", "encourage"];
const MOOD_VIEWS = ["front", "side", "back"];
const moodFiles = [];
MOOD_KEYS.forEach(m => MOOD_VIEWS.forEach(v => moodFiles.push(m + "_" + v + ".png")));

const missingFiles = moodFiles.filter(name => {
    const file = path.join(ASSET_DIR, name);
    return !fs.existsSync(file) || fs.statSync(file).size <= 1000;
});
check("18 张表情素材都已生成（6 情绪 × 3 视角）", missingFiles.length === 0, missingFiles.join(", ") || "全部就位");

const badPng = moodFiles.filter(name => {
    const file = path.join(ASSET_DIR, name);
    if (!fs.existsSync(file)) return true;
    const head = fs.readFileSync(file).subarray(0, 8);
    return !head.equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
});
check("18 张表情素材都是合法 PNG", badPng.length === 0, badPng.join(", ") || "全部通过");

const pngCanvas = name => {
    const buf = fs.readFileSync(path.join(ASSET_DIR, name));
    return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
};
const canvases = moodFiles.map(pngCanvas);
const canvas0 = canvases[0];
const sameCanvas = canvases.every(s => s[0] === canvas0[0] && s[1] === canvas0[1]);
check("18 张素材画布尺寸完全一致（旋转/换表情不跳动）", sameCanvas,
    canvases.map(s => s.join("x")).filter((s, i, a) => a.indexOf(s) === i).join(", "));

const manifestFile = path.join(ASSET_DIR, "manifest.json");
check("素材说明文件存在", fs.existsSync(manifestFile));
if (fs.existsSync(manifestFile)) {
    const manifest = JSON.parse(fs.readFileSync(manifestFile, "utf8"));
    check("manifest 声明了三个画布一致的视图",
        Array.isArray(manifest.views) && manifest.views.length >= 3,
        (manifest.views || []).map(v => v.key).join(", "));
    check("manifest 记录底对齐（旋转不跳动）", manifest.bottom_aligned === true);
    check("manifest 声明 6 种情绪",
        Array.isArray(manifest.moods) && manifest.moods.length === 6,
        (manifest.moods || []).map(m => m.key).join(", "));
    check("manifest 记录统一画布与格子尺寸",
        Array.isArray(manifest.canvas) && manifest.canvas[0] > 0 && manifest.canvas[1] > 0 &&
        Array.isArray(manifest.cell_size) && manifest.cell_size[0] <= manifest.canvas[0] &&
        manifest.cell_size[1] <= manifest.canvas[1],
        JSON.stringify(manifest.canvas) + " / " + JSON.stringify(manifest.cell_size));
    check("manifest 的 files 覆盖全部 18 张素材",
        !!manifest.files && moodFiles.every(n => manifest.files[n.replace(/\.png$/, "")] === n),
        manifest.files ? Object.keys(manifest.files).length + " 项" : "缺失");
    check("素材画布与 manifest.canvas 一致",
        Array.isArray(manifest.canvas) && canvas0[0] === manifest.canvas[0] && canvas0[1] === manifest.canvas[1],
        canvas0.join("x") + " vs " + JSON.stringify(manifest.canvas));
}

/* ---------------- 2. 纯函数：角度 → 视角 ---------------- */

const near = (a, b) => Math.abs(a - b) < 1e-6;

check("normalizeAngle 处理负数与超界",
    phoebe3d.normalizeAngle(-90) === 270 && phoebe3d.normalizeAngle(450) === 90,
    [phoebe3d.normalizeAngle(-90), phoebe3d.normalizeAngle(450)].join(", "));

check("angleDistance 取最短夹角",
    phoebe3d.angleDistance(350, 10) === 20 && phoebe3d.angleDistance(0, 180) === 180);

check("视角名：0/90/180/270",
    phoebe3d.viewKeyForAngle(0) === "front"
    && phoebe3d.viewKeyForAngle(90) === "side"
    && phoebe3d.viewKeyForAngle(180) === "back"
    && phoebe3d.viewKeyForAngle(270) === "side-mirror",
    [0, 90, 180, 270].map(a => a + "=" + phoebe3d.viewKeyForAngle(a)).join(" "));

check("权重：正对视角时只有一帧可见",
    near(phoebe3d.frameWeights(0)[0], 1) && near(phoebe3d.frameWeights(0)[1], 0)
    && near(phoebe3d.frameWeights(90)[1], 1),
    JSON.stringify(phoebe3d.frameWeights(0)));

const mid = phoebe3d.frameWeights(45);
check("权重：两个视角中间各占一半",
    near(mid[0], 0.5) && near(mid[1], 0.5), JSON.stringify(mid.map(v => Number(v.toFixed(3)))));

const sumOk = [0, 33, 90, 137, 180, 250, 300, 359].every(angle => {
    const total = phoebe3d.frameWeights(angle).reduce((a, b) => a + b, 0);
    return Math.abs(total - 1) < 1e-9;
});
check("权重永远归一化（和为 1）", sumOk);

check("权重：270° 用侧面镜像",
    near(phoebe3d.frameWeights(270)[3], 1) && phoebe3d.FRAMES[3].mirror === true);
check("权重：负角度等价于 270°", near(phoebe3d.frameWeights(-90)[3], 1));

check("nearestFrameAngle：350° 归到正面 0°（不是 270°）",
    phoebe3d.nearestFrameAngle(350) === 0 && phoebe3d.nearestFrameAngle(10) === 0);
check("nearestFrameAngle：60° 归到侧面 90°", phoebe3d.nearestFrameAngle(60) === 90);
check("nearestFrameAngle：200° 归到背面 180°", phoebe3d.nearestFrameAngle(200) === 180);
check("shortestDelta：350° → 0° 是 +10（走近路不绕圈）",
    near(phoebe3d.shortestDelta(350, 0), 10));
check("shortestDelta：10° → 350° 是 -20", near(phoebe3d.shortestDelta(10, 350), -20));

/* ---------------- 3. DOM 行为（打桩） ---------------- */

function makeNode(tag) {
    const set = new Set();
    const node = {
        tagName: String(tag || "div").toUpperCase(),
        id: "",
        innerHTML: "",
        textContent: "",
        style: {},
        dataset: {},
        children: [],
        attributes: {},
        parentNode: null,
        _listeners: {},
        setAttribute(key, value) { this.attributes[key] = value; },
        getAttribute(key) { return this.attributes[key]; },
        appendChild(child) {
            child.parentNode = this;
            this.children.push(child);
            if (child.id) document.byId[child.id] = child;
            return child;
        },
        removeChild(child) {
            const index = this.children.indexOf(child);
            if (index >= 0) this.children.splice(index, 1);
            child.parentNode = null;
            return child;
        },
        addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); },
        removeEventListener() {},
        querySelector() { return null; },
        focus() {},
    };

    /* 真实 DOM 里 className 与 classList 是同一份数据，打桩必须保持一致 */
    node.classList = {
        add: (...cs) => { cs.forEach(c => set.add(c)); return node.className; },
        remove: (...cs) => cs.forEach(c => set.delete(c)),
        contains: c => set.has(c),
        toggle: (c, force) => {
            const on = force === undefined ? !set.has(c) : !!force;
            if (on) set.add(c); else set.delete(c);
            return on;
        },
        _set: set,
    };
    Object.defineProperty(node, "className", {
        get() { return Array.from(set).join(" "); },
        set(value) {
            set.clear();
            String(value == null ? "" : value).split(/\s+/).filter(Boolean).forEach(c => set.add(c));
        },
        enumerable: true,
    });

    /* 真实 DOM 给 innerHTML 赋值会清空/替换子节点；打桩保持一致，否则重复渲染会累积 */
    let innerHTMLValue = "";
    Object.defineProperty(node, "innerHTML", {
        get() { return innerHTMLValue; },
        set(value) {
            innerHTMLValue = value == null ? "" : String(value);
            if (innerHTMLValue === "") {
                node.children.forEach(child => { child.parentNode = null; });
                node.children.length = 0;
            }
        },
        enumerable: true,
    });

    return node;
}

const body = makeNode("body");
const document = {
    body,
    byId: {},
    readyState: "complete",
    createElement: makeNode,
    getElementById(id) { return this.byId[id] || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
};

const rafCallbacks = [];
const rootListeners = {};
const sandbox = {
    document,
    console,
    Math,
    Date,
    Number,
    String,
    Array,
    Object,
    isFinite,
    JSON,
    setTimeout: () => 1,
    clearTimeout: () => {},
    requestAnimationFrame: cb => { rafCallbacks.push(cb); return rafCallbacks.length; },
    cancelAnimationFrame: () => {},
    addEventListener: (type, fn) => { (rootListeners[type] = rootListeners[type] || []).push(fn); },
    removeEventListener: () => {},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.__PHOEBE3D_NO_AUTO__ = false;

vm.createContext(sandbox);
vm.runInContext(readFile("phoebe3d.js"), sandbox, { filename: "phoebe3d.js" });

check("沙箱里注册了全局 phoebe3dFeedback", typeof sandbox.phoebe3dFeedback === "function");
check("DOM 就绪后自动挂载了浮动立牌", Boolean(sandbox.phoebe3dViewer()));

const viewer = sandbox.phoebe3dViewer();
const stage = viewer && viewer.el;
check("立牌容器带上 p3d-stage", Boolean(stage) && stage.className.indexOf("p3d-stage") === 0, stage && stage.className);
check("没有宿主容器时退化为右下角浮动", Boolean(stage) && stage.className.indexOf("p3d-floating") >= 0);
check("立牌里有 4 个视角图层", Boolean(stage) && stage.children[0].children.filter(c => c.tagName === "IMG").length === 4);

const defaultSrc = viewer.images.map(img => img.src).join(" ");
check("立牌默认是中性偏好的「点赞」表情", viewer.mood() === "like", viewer.mood());
check("默认表情的 4 个图层都指向 like 素材",
    defaultSrc.includes("like_front.png") && defaultSrc.includes("like_side.png")
    && defaultSrc.includes("like_back.png"), defaultSrc);

viewer.setAngle(90);
check("setAngle(90) 后视角为侧面", viewer.viewKey() === "side");
const sideOpacity = viewer.images.map(img => Number(img.style.opacity));
check("只有侧面图层可见（opacity 1）", sideOpacity[1] === 1 && sideOpacity[0] === 0, JSON.stringify(sideOpacity));

viewer.setAngle(-30);
check("负角度自动归一化到 330", Math.abs(viewer.getAngle() - 330) < 1e-6, String(viewer.getAngle()));
const edgeOpacity = viewer.images.map(img => Number(img.style.opacity));
check("330° 时正面权重最高（离正面 30°，离镜像侧面 60°）",
    edgeOpacity[0] > edgeOpacity[3] && edgeOpacity[0] > edgeOpacity[1],
    JSON.stringify(edgeOpacity));

const caption = stage.children[1];
check("立牌带字幕气泡节点", Boolean(caption) && caption.className.indexOf("p3d-caption") === 0);

viewer.say("答对啦，你太厉害了");
check("say() 写入字幕文本", caption.innerHTML.includes("答对啦"), caption.innerHTML);
check("say() 让字幕显示（p3d-caption-show）", caption.classList.contains("p3d-caption-show"));

check("say() 做 HTML 转义（不注入标签）",
    viewer.say("<b>x</b>") && caption.innerHTML.includes("&lt;b&gt;"));

const figure = viewer.figure;
viewer.react("happy");
check("react('happy') 加上跳跃类", figure.classList.contains("p3d-happy"));
viewer.react("sad");
check("react('sad') 加上摇头类", figure.classList.contains("p3d-sad"));
check("动作互斥（happy 会被移除）", !figure.classList.contains("p3d-happy"));

let celebrateCalled = 0;
sandbox.celebrateCorrect = () => { celebrateCalled += 1; };

sandbox.phoebe3dFeedback(true, {});
check("答对：立牌跳跃", figure.classList.contains("p3d-happy"));
check("答对：弹出表情包浮层（调用 celebrateCorrect）", celebrateCalled === 1, String(celebrateCalled));
check("答对：字幕给出鼓励文案", caption.classList.contains("p3d-caption-show"));

sandbox.phoebe3dFeedback(false, {});
check("答错：立牌摇头", figure.classList.contains("p3d-sad"));
check("答错：字幕给出提示文案", caption.classList.contains("p3d-caption-show"));

/* ---------------- 2.1 表情（6 情绪 × 3 视角） ---------------- */

const srcOf = v => v.images.map(img => img.src).join(" ");

check("moodFile 按「情绪_视角.png」拼路径",
    phoebe3d.moodFile("cheer", "side") === "assets/phoebe3d/cheer_side.png", phoebe3d.moodFile("cheer", "side"));
check("MOODS 声明 6 种情绪", phoebe3d.MOODS.length === 6, phoebe3d.MOODS.join(", "));
check("isMood 只认合法情绪", phoebe3d.isMood("sad") === true && phoebe3d.isMood("nope") === false);

viewer.setMood("cute");
check("setMood('cute') 切到可爱表情", viewer.mood() === "cute", viewer.mood());
check("换表情时 4 个图层一起换成 cute 素材（270° 复用侧面）",
    srcOf(viewer).includes("cute_front.png") && srcOf(viewer).includes("cute_side.png")
    && srcOf(viewer).includes("cute_back.png"), srcOf(viewer));
check("非法情绪被忽略，保留当前表情",
    viewer.setMood("nope") === "cute" && viewer.mood() === "cute", viewer.mood());

check("phoebe3dMood() 无参返回当前表情", sandbox.phoebe3dMood() === "cute", String(sandbox.phoebe3dMood()));
sandbox.phoebe3dMood("encourage");
check("phoebe3dMood(mood) 切换表情", viewer.mood() === "encourage", viewer.mood());

/* 预载成功后一次性换图；预载失败保留原形象（不白屏、不半新半旧） */
const savedImage = sandbox.Image;
sandbox.Image = function () {
    const probe = this;
    probe.onload = null;
    probe.onerror = null;
    Object.defineProperty(probe, "src", {
        configurable: true,
        get() { return probe._src; },
        set(value) { probe._src = value; if (probe.onload) probe.onload(); },
    });
};
viewer.setMood("cheer");
check("三张视角预载完成后才换图",
    viewer.mood() === "cheer" && srcOf(viewer).includes("cheer_front.png"), viewer.mood());

sandbox.Image = function () {
    const probe = this;
    probe.onload = null;
    probe.onerror = null;
    Object.defineProperty(probe, "src", {
        configurable: true,
        get() { return probe._src; },
        set(value) { probe._src = value; if (probe.onerror) probe.onerror(); },
    });
};
viewer.setMood("sad");
check("素材加载失败时保留原来那张表情", viewer.mood() === "cheer" && srcOf(viewer).includes("cheer_"), viewer.mood());
sandbox.Image = savedImage;

/* 答对 → 开心；连对 ≥2 → 点赞；答错 → 难过；可显式指定（错题本再练 → 加油） */
let streakStub = 1;
sandbox.celebrateCorrect = () => { celebrateCalled += 1; return streakStub; };

viewer.setMood("encourage");
streakStub = 1;
sandbox.phoebe3dFeedback(true, {});
check("答对：立牌换成开心表情", viewer.mood() === "happy", viewer.mood());

viewer.setMood("encourage");
streakStub = 3;
sandbox.phoebe3dFeedback(true, {});
check("连对 ≥2 题：立牌换成点赞表情", viewer.mood() === "like", viewer.mood());

viewer.setMood("encourage");
sandbox.phoebe3dFeedback(false, {});
check("答错：立牌换成难过表情", viewer.mood() === "sad", viewer.mood());

viewer.setMood("sad");
sandbox.phoebe3dFeedback(true, { mood: "cheer" });
check("答对可显式指定表情（错题本再练答对 → 加油）", viewer.mood() === "cheer", viewer.mood());

check("语音开关可读写", sandbox.phoebe3dSetVoice(false) === false
    && sandbox.PHOEBE3D.voiceEnabled() === false);
sandbox.phoebe3dSetVoice(true);

/* ---------------- 3.1 停靠 / 惯性 / 转圈（驱动 rAF 循环） ---------------- */

let frameClock = 0;
function runFrames(count) {
    for (let i = 0; i < count; i++) {
        frameClock += 16;
        const cb = rafCallbacks.pop();
        if (!cb) break;
        cb(frameClock);
    }
}

/* 每段测试前把立牌恢复成干净状态（前面的 react("happy") 会留下转圈余量与速度） */
function resetViewer(angle) {
    viewer.state.spinRemaining = 0;
    viewer.state.velocity = 0;
    viewer.state.dragging = false;
    viewer.setAngle(angle);
    viewer.state.baseAngle = angle;
}

resetViewer(60);
runFrames(30);
check("松手后自动停靠到最近的视角（60° → 侧面 90°），不会停在重影角度",
    Math.abs(viewer.state.baseAngle - 90) < 0.01, String(viewer.state.baseAngle));
check("停靠后视角就是侧面", viewer.viewKey() === "side");
check("停稳后进入轻微摆动（角度在 90° 附近小幅浮动）",
    Math.abs(viewer.getAngle() - 90) <= 8.5, String(viewer.getAngle().toFixed(1)));

resetViewer(200);
runFrames(30);
check("200° 停靠到背面 180°", viewer.viewKey() === "back"
    && Math.abs(viewer.state.baseAngle - 180) < 0.01, String(viewer.state.baseAngle));

resetViewer(350);
runFrames(30);
check("350° 走近路停靠到正面（基准角回到 0° 附近，而不是绕到 270°）",
    viewer.viewKey() === "front" && Math.abs(viewer.state.baseAngle) < 0.01,
    String(viewer.state.baseAngle));

/* 拖拽 → 松手 → 惯性滑行 → 停靠：不该停在两个视角中间的插值角度 */
const figureEl = viewer.figure;
resetViewer(0);
figureEl._listeners.pointerdown[0]({ clientX: 300, pointerId: 1, preventDefault() {} });
for (let x = 305; x <= 360; x += 5) {
    (rootListeners.pointermove || []).forEach(fn => fn({ clientX: x }));
}
(rootListeners.pointerup || []).forEach(fn => fn({}));
runFrames(200);
// 拖动位移 + 惯性滑行共同决定最终落到哪个视角，但**必须**落在某个正视角上
const settledOnFrame = [0, 90, 180, 270].some(angle =>
    Math.abs(phoebe3d.shortestDelta(viewer.state.baseAngle, angle)) < 0.01);
check("拖动松手（含惯性滑行）后停在某个正视角，不停在中间的插值角度",
    settledOnFrame, `baseAngle=${viewer.state.baseAngle}, view=${viewer.viewKey()}`);

resetViewer(0);
runFrames(5);
const beforeSpin = viewer.getAngle();
viewer.spinOnce();
runFrames(Math.ceil(360 / 7) + 6);
const afterSpin = viewer.getAngle();
const spinDrift = Math.abs(phoebe3d.shortestDelta(beforeSpin, afterSpin));
check("庆祝转圈是连续转满一圈后回到原位（不是瞬间跳变）",
    viewer.state.spinRemaining === 0 && spinDrift <= 8.5, `${beforeSpin} → ${afterSpin}`);

check("惯性初速有上限（快速甩动不会转过好几圈）",
    readFile("phoebe3d.js").includes("MAX_VELOCITY") && readFile("phoebe3d.js").includes("SETTLE_STEP"));

/* ---------------- 3.2 点击 → 触发后端 AI 反馈 ---------------- */

const fetchCalls = [];
let fetchMode = "ok";

sandbox.localStorage = {
    store: { "xiaozhi.student": "2" },
    getItem(key) { return this.store[key] === undefined ? null : this.store[key]; },
    setItem(key, value) { this.store[key] = String(value); },
};

sandbox.fetch = (url, options) => {
    fetchCalls.push({ url: String(url), options: options || {} });

    if (fetchMode === "fail") return Promise.reject(new Error("network down"));

    return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ text: "今天练了 5 题，两位数除法还有点不稳，一起再练两道吧。", source: "ai" }),
    });
};

function clickViewer() {
    resetViewer(0);
    figureEl._listeners.pointerdown[0]({ clientX: 300, pointerId: 1, preventDefault() {} });
    (rootListeners.pointerup || []).forEach(fn => fn({}));
}

clickViewer();
const firstCall = fetchCalls[0];
check("点击立牌会请求后端 AI 接口",
    fetchCalls.length === 1 && firstCall.url.endsWith("/api/phoebe/chat"), firstCall && firstCall.url);
check("请求用 POST",
    firstCall && firstCall.options.method === "POST", firstCall && firstCall.options.method);
check("请求体带上当前学生 id（读 localStorage）与 trigger",
    firstCall && (() => {
        const body = JSON.parse(firstCall.options.body);
        return body.student_id === 2 && body.trigger === "click";
    })(), firstCall && firstCall.options.body);
check("请求期间先给出'正在看学习情况'的占位字幕",
    caption.innerHTML.includes("学习情况"), caption.innerHTML);

/* ---------------- 4. 页面接入 ---------------- */

function pageHasViewer(html, businessJs) {
    const text = readFile(html);
    return {
        script: text.includes('src="phoebe3d.js"'),
        order: text.indexOf('src="phoebe3d.js"') >= 0
            && text.indexOf('src="phoebe3d.js"') < text.indexOf(`src="${businessJs}"`),
        host: text.includes("data-phoebe3d"),
    };
}

const today = pageHasViewer("today.html", "today.js");
check("today.html 引入了 phoebe3d.js", today.script);
check("today.html 先加载 phoebe3d.js 再加载 today.js", today.order);
check("today.html 不再把立牌塞进提示框（改挂浏览器左侧）", !today.host);

const practice = pageHasViewer("index.html", "app.js");
check("index.html 引入了 phoebe3d.js", practice.script);
check("index.html 先加载 phoebe3d.js 再加载 app.js", practice.order);
check("index.html 不再把立牌塞进提示框（改挂浏览器左侧）", !practice.host);

const wrongBook = pageHasViewer("wrong_book.html", "wrong_book.js");
check("wrong_book.html 引入了 phoebe3d.js", wrongBook.script);
check("wrong_book.html 先加载 phoebe3d.js 再加载 wrong_book.js", wrongBook.order);
check("wrong_book.html 不再把立牌塞进提示框（改挂浏览器左侧）", !wrongBook.host);
check("错题本再练答对时让立牌换成「加油」表情",
    readFile("wrong_book.js").includes('mood: "cheer"'));
check("错题本再练答错时把立牌换成难过（不出声打扰）",
    readFile("wrong_book.js").includes('phoebe3dMood("sad")'));

const p3dJs = readFile("phoebe3d.js");
check("素材路径改成「情绪_视角.png」拼装（不再硬编码 front/side/back.png）",
    !/["'](front|side|back)\.png["']/.test(p3dJs) && p3dJs.includes("moodFile("));
check("立牌空闲 60 秒后自动换成「鼓励」表情",
    /IDLE_MOOD_MS = 60000/.test(p3dJs) && /IDLE_MOOD = "encourage"/.test(p3dJs));
check("11 个页面表头改成「菲比同学」",
    !readFile("index.html").includes("小智学伴") && readFile("index.html").includes("菲比同学")
    && readFile("today.html").includes("菲比同学"));

check("今日学习页答对后自动跳题", readFile("today.js").includes("scheduleAutoNext()"));
check("自动跳题有延迟常量", /const AUTO_NEXT_MS = \d+/.test(readFile("today.js")));
check("自动跳题前补交学习反馈（计划完成数靠它推进）",
    readFile("today.js").includes("sendAutoFeedback(result)"));
check("每题只提交一次反馈", readFile("today.js").includes("if (feedbackSent)"));
check("今日学习页答错时渲染解析框", readFile("today.js").includes("explain-box"));
check("今日学习页接入了菲比反馈", readFile("today.js").includes("phoebe3dFeedback("));
check("今日学习页有菲比语音开关", readFile("today.js").includes("phoebe3dSetVoice"));

check("自由练习页答对后也自动跳题", readFile("app.js").includes("scheduleAutoNext()"));
check("自由练习页接入了菲比反馈", readFile("app.js").includes("phoebe3dFeedback("));
check("自由练习页保留 celebrateAnswer 兼容旧浮层",
    readFile("app.js").includes("function celebrateAnswer(correct, upgrade)")
    && readFile("app.js").includes("celebrateCorrect("));

const css = readFile("style.css");
const compactCss = css.replace(/\s+/g, "");
check("样式表有立牌样式", css.includes(".p3d-stage"));
check("样式表有字幕气泡样式", css.includes(".p3d-caption"));
check("样式表有欢呼动画", css.includes("@keyframes p3d-jump"));
check("样式表有摇头动画", css.includes("@keyframes p3d-shake"));

/* 新素材画布 338×210（内容 136–194px 高），立牌按接近 1:1 显示才不会发糊 */
const figureRule = (compactCss.match(/\.p3d-figure\{[^}]*\}/) || [""])[0];
check("立牌按素材画布接近 1:1 显示（322×200，不放大糊掉）",
    /width:322px/.test(figureRule) && /height:200px/.test(figureRule), figureRule);
const captionRule = (compactCss.match(/\.p3d-caption\{[^}]*\}/) || [""])[0];
check("字幕气泡跟着加宽", /max-width:280px/.test(captionRule), captionRule);
check("窄屏断点同步缩小立牌",
    /max-width:1280px\)\{\.p3d-stage\.p3d-floating\{left:10px;width:250px/.test(compactCss),
    "≤1280px → 250px");
check("更窄的屏幕断点也同步缩小",
    /max-width:1060px\)\{\.p3d-stage\.p3d-floating\{width:200px/.test(compactCss), "≤1060px → 200px");

/* 位置需求：固定在浏览器左侧空白处，且不随鼠标/滚动/拖拽移动 */
check("立牌用 position:fixed + left 固定在左侧",
    /\.p3d-stage\.p3d-floating\{position:fixed;left:/.test(compactCss));
check("立牌不再用 right 定位",
    !/\.p3d-stage\.p3d-floating\{[^}]*right:/.test(compactCss));
check("拖拽只改旋转角度，不修改立牌位置",
    !/\.style\.(left|top|right|bottom|position)\s*=/.test(readFile("phoebe3d.js")));
check("源码里没有把立牌跟着鼠标移动的逻辑",
    !readFile("phoebe3d.js").includes("clientX - state.startX")
    && !readFile("phoebe3d.js").includes("style.transform = \"translate(\""));

/* ---------------- 3.3 V2.6 菲比收藏：等级提升 → 左侧多一只 ---------------- */

function collectN(sid, times) {
    sandbox.localStorage.store["xiaozhi.student"] = String(sid);
    const got = [];
    for (let i = 0; i < times; i += 1) got.push(sandbox.phoebe3dCollect());
    return got;
}

sandbox.localStorage.store["xiaozhi.student"] = "1";
check("菲比收藏一开始是空的", sandbox.phoebe3dCollection().length === 0);

const shownMood = sandbox.phoebe3dMood();
const got3 = collectN(1, 3);
check("每提升一次等级就多一只菲比", sandbox.phoebe3dCollection().length === 3, String(got3.length));
check("只收藏「喜欢/欢呼/可爱/鼓励」四种表情（排除答对 happy 与答错 sad）",
    got3.every(m => ["like", "cheer", "cute", "encourage"].indexOf(m) >= 0), got3.join(","));
check("新收藏的表情和立牌当前表情不一样",
    got3.every(m => m !== shownMood), "shown=" + shownMood + " got=" + got3.join(","));
check("优先收藏还没收集过的表情（前 3 只互不重复）", new Set(got3).size === 3, got3.join(","));

sandbox.localStorage.store["xiaozhi.student"] = "2";
check("换一个小朋友后收藏是空的（按学生分键隔离）", sandbox.phoebe3dCollection().length === 0);
collectN(2, 1);
check("第二个小朋友的收藏独立计数", sandbox.phoebe3dCollection().length === 1);
sandbox.localStorage.store["xiaozhi.student"] = "1";
check("切回来还是原来那个小朋友的收藏", sandbox.phoebe3dCollection().length === 3);

collectN(1, 30);
check("收藏有上限（最多 " + sandbox.PHOEBE3D.COLLECT_MAX + " 只，屏幕不会被挤满）",
    sandbox.phoebe3dCollection().length === sandbox.PHOEBE3D.COLLECT_MAX,
    String(sandbox.phoebe3dCollection().length));

sandbox.phoebe3dRenderCollection();
const collectBoxes = sandbox.document.body.children.filter(n => n && String(n.className).split(/\s+/).indexOf("p3d-collection") >= 0);
check("收藏画在左侧同一块容器里（不会每次升级新建一块）", collectBoxes.length === 1, String(collectBoxes.length));
const fumoImgs = collectBoxes.length ? collectBoxes[0].children : [];
check("每只收藏都用菲比正面素材渲染",
    fumoImgs.length === sandbox.PHOEBE3D.COLLECT_MAX && fumoImgs.every(img => /_front\.png$/.test(String(img.src))),
    fumoImgs.length + " 只");
check("收藏容器不挡小朋友点击（pointer-events:none）",
    /\.p3d-collection\{[^}]*pointer-events:none/.test(compactCss));
check("窄屏断点会把收藏缩放/隐藏",
    /\.p3d-collection\{[^}]*1280px/.test(compactCss) === false
    && compactCss.indexOf(".p3d-collection-hidden{display:none}") >= 0);

/* ---------------- 汇总（等两次 AI 请求的微任务跑完） ---------------- */

function finalize() {
    console.log("\nRESULT: " + (ok ? "ALL PASS" : "HAS FAILURES"));
    process.exit(ok ? 0 : 1);
}

setTimeout(() => {
    check("AI 返回的台词显示在字幕里",
        caption.innerHTML.includes("两位数除法"), caption.innerHTML);
    check("AI 台词会替换掉'正在看学习情况'占位",
        !caption.innerHTML.includes("学习情况"), caption.innerHTML);

    // 网络失败 → 必须退回本地文案，绝不让立牌卡住
    fetchMode = "fail";
    clickViewer();

    setTimeout(() => {
        check("AI 请求失败时退回本地文案", caption.innerHTML.length > 0
            && !caption.innerHTML.includes("两位数除法"), caption.innerHTML);
        check("失败兜底后可以再次点击（不会一直卡在 pending）", (() => {
            fetchMode = "ok";
            clickViewer();
            return fetchCalls.length >= 3;
        })(), "calls=" + fetchCalls.length);

        finalize();
    }, 30);
}, 30);
