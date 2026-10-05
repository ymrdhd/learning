// ==============================================================
// 能力契约｜验证：儿童端共享 UI 层（kid-lang / ui-shell / ui-components）+ 页面手机端元信息与内网启动脚本
// 入口：脚本自身：node frontend/verify_ui_shell.js
// 依赖：Node fs/vm/path + 本文件内置迷你 DOM（不依赖浏览器）
// 不负责：各业务页面逻辑 → 各自的 verify_*_web.js
// 验证：node frontend/verify_ui_shell.js
// 被调用：verify_all.py（套件 uishell）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 共享 UI 层验证：儿童化语言映射、全局学生状态/分龄/设置、公共组件输出。
 *
 * 用 VM + 迷你 DOM 跑真实的 frontend/kid-lang.js、ui-shell.js、ui-components.js，
 * 不需要浏览器、不连后端（fetch 打桩为失败，用于验证降级路径）。
 *
 * 用法：node frontend/verify_ui_shell.js
 * 全部通过时退出码为 0。
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

let ok = true;

function check(name, cond, extra) {
    console.log((cond ? "PASS  " : "FAIL  ") + name + (extra === undefined ? "" : "  | " + extra));
    if (!cond) ok = false;
}

/* ---------------- 迷你 DOM ---------------- */

const VOID_TAGS = { br: 1, img: 1, input: 1, hr: 1, meta: 1, link: 1, source: 1 };

function MiniNode(tag) {
    this.tag = String(tag || "").toLowerCase();
    this.attrs = {};
    this.childNodes = [];
    this.parentNode = null;
    this._text = "";
    this._html = "";
    this._listeners = {};
    this.style = {};
}

MiniNode.prototype.setAttribute = function (k, v) { this.attrs[String(k)] = String(v); };
MiniNode.prototype.getAttribute = function (k) {
    return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null;
};
MiniNode.prototype.hasAttribute = function (k) { return this.getAttribute(k) !== null; };
MiniNode.prototype.removeAttribute = function (k) { delete this.attrs[k]; };

function makeClassList(node) {
    function list() {
        return String(node.attrs["class"] || "").split(/\s+/).filter(Boolean);
    }
    return {
        add: c => { const l = list(); if (l.indexOf(c) === -1) { l.push(c); node.attrs["class"] = l.join(" "); } },
        remove: c => { node.attrs["class"] = list().filter(x => x !== c).join(" "); },
        contains: c => list().indexOf(c) !== -1,
        toggle: (c, force) => {
            const on = force === undefined ? !list().includes(c) : !!force;
            if (on) node.classList.add(c); else node.classList.remove(c);
            return on;
        },
    };
}

Object.defineProperty(MiniNode.prototype, "classList", {
    get() {
        if (!this._classList) this._classList = makeClassList(this);
        return this._classList;
    },
});

Object.defineProperty(MiniNode.prototype, "className", {
    get() { return this.attrs["class"] || ""; },
    set(v) { this.attrs["class"] = String(v); },
});

Object.defineProperty(MiniNode.prototype, "dataset", {
    get() {
        const out = {};
        for (const k of Object.keys(this.attrs)) {
            if (k.indexOf("data-") === 0) {
                out[k.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = this.attrs[k];
            }
        }
        return out;
    },
});

Object.defineProperty(MiniNode.prototype, "textContent", {
    get() {
        let out = this._text;
        for (const c of this.childNodes) out += c.textContent;
        return out;
    },
    set(v) { this.childNodes = []; this._text = String(v); },
});

Object.defineProperty(MiniNode.prototype, "innerHTML", {
    get() { return this._html; },
    set(v) {
        this._html = String(v);
        this.childNodes = parseHTML(this._html);
        for (const c of this.childNodes) c.parentNode = this;
    },
});

MiniNode.prototype.appendChild = function (n) { n.parentNode = this; this.childNodes.push(n); return n; };
MiniNode.prototype.removeChild = function (n) {
    const i = this.childNodes.indexOf(n);
    if (i >= 0) { this.childNodes.splice(i, 1); n.parentNode = null; }
    return n;
};
MiniNode.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
MiniNode.prototype.focus = function () {};
MiniNode.prototype.addEventListener = function (type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
};
MiniNode.prototype.dispatchEvent = function (ev) {
    const e = Object.assign({ target: this, type: ev && ev.type, preventDefault() {}, stopPropagation() {} }, ev);
    for (const fn of (this._listeners[e.type] || []).slice()) fn(e);
    return true;
};
MiniNode.prototype.click = function () { this.dispatchEvent({ type: "click" }); };
MiniNode.prototype.querySelector = function (sel) {
    const r = queryAll(this, sel);
    return r.length ? r[0] : null;
};
MiniNode.prototype.querySelectorAll = function (sel) { return queryAll(this, sel); };

function allDescendants(node, out) {
    out = out || [];
    for (const c of node.childNodes) { out.push(c); allDescendants(c, out); }
    return out;
}

function matchesSelector(node, sel) {
    const m = /^([a-zA-Z][a-zA-Z0-9-]*)?((?:\.[A-Za-z0-9_-]+)*)((?:\[[^\]]+\])*)$/.exec(sel.trim());
    if (!m) return false;
    if (m[1] && node.tag !== m[1].toLowerCase()) return false;
    for (const c of (m[2] || "").split(".").filter(Boolean)) {
        if (!node.classList.contains(c)) return false;
    }
    const attrRe = /\[([^\]=\s]+)(?:=["']?([^"'\]]*)["']?)?\]/g;
    let a;
    while ((a = attrRe.exec(m[3] || "")) !== null) {
        const v = node.getAttribute(a[1]);
        if (v === null) return false;
        if (a[2] !== undefined && a[2] !== "" && v !== a[2]) return false;
    }
    return true;
}

function queryAll(root, sel) {
    const out = [];
    for (const part of String(sel).split(",")) {
        const chain = part.trim().split(/\s+/).filter(Boolean);
        if (!chain.length) continue;
        let current = [root];
        for (const step of chain) {
            const next = [];
            for (const base of current) {
                for (const n of allDescendants(base)) {
                    if (matchesSelector(n, step) && next.indexOf(n) === -1) next.push(n);
                }
            }
            current = next;
        }
        for (const n of current) if (out.indexOf(n) === -1) out.push(n);
    }
    return out;
}

function parseAttrs(raw, node) {
    const re = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
    let m;
    while ((m = re.exec(raw || "")) !== null) {
        const val = m[2] !== undefined ? m[2] : (m[3] !== undefined ? m[3] : (m[4] !== undefined ? m[4] : ""));
        node.setAttribute(m[1], val);
    }
}

function appendText(node, text) {
    if (/^\s+$/.test(text)) {
        // 保留空白文本对 textContent 无意义，直接忽略纯空白
        return;
    }
    node._text += text;
}

function parseHTML(html) {
    const root = new MiniNode("#fragment");
    const stack = [root];
    const re = /<!--[\s\S]*?-->|<\/?([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^<>]*?)?)\s*(\/?)>/g;
    let last = 0;
    let m;
    while ((m = re.exec(html)) !== null) {
        const text = html.slice(last, m.index);
        if (text) appendText(stack[stack.length - 1], text);
        last = re.lastIndex;
        if (m[0].indexOf("<!--") === 0) continue;
        const closing = m[0][1] === "/";
        const tag = m[1].toLowerCase();
        if (closing) {
            for (let i = stack.length - 1; i > 0; i--) {
                if (stack[i].tag === tag) { stack.length = i; break; }
            }
            continue;
        }
        const node = new MiniNode(tag);
        parseAttrs(m[2], node);
        stack[stack.length - 1].appendChild(node);
        if (!m[3] && !VOID_TAGS[tag]) stack.push(node);
    }
    const tail = html.slice(last);
    if (tail) appendText(stack[stack.length - 1], tail);
    return root.childNodes;
}

function makeStorage(store) {
    return {
        getItem: k => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: k => { delete store[k]; },
        clear: () => { for (const k of Object.keys(store)) delete store[k]; },
    };
}

function makeSandbox(opts) {
    opts = opts || {};
    const documentElement = new MiniNode("html");
    const body = new MiniNode("body");
    documentElement.appendChild(body);

    const document = {
        documentElement,
        body,
        getElementById: id => queryAll(documentElement, "#" + String(id))[0] || null,
        querySelector: sel => queryAll(documentElement, String(sel))[0] || null,
        querySelectorAll: sel => queryAll(documentElement, String(sel)),
        createElement: tag => new MiniNode(tag),
        createTextNode: text => { const n = new MiniNode("#text"); n._text = String(text); return n; },
        addEventListener() {},
    };

    const sb = {
        console,
        document,
        Math,
        JSON,
        Date,
        Promise,
        setTimeout,
        clearTimeout,
        location: { protocol: "http:", origin: "http://127.0.0.1:8000", href: "http://127.0.0.1:8000/app/today.html" },
        navigator: { userAgent: "node-verify" },
        fetch: () => Promise.reject(new Error("offline in verify")),
    };
    sb.window = sb;
    sb.globalThis = sb;
    sb.self = sb;
    if (opts.withStorage !== false) {
        sb.localStorage = makeStorage(opts.store || {});
    }
    return sb;
}

function loadInto(sb, file) {
    const full = path.join(__dirname, file);
    if (!fs.existsSync(full)) return sb;   // 实现文件未创建时保持 undefined，让断言显式 FAIL
    const code = fs.readFileSync(full, "utf8");
    vm.runInNewContext(code, sb, { filename: file });
    return sb;
}

const store = {};
const sb = makeSandbox({ store });
loadInto(sb, "kid-lang.js");
loadInto(sb, "ui-shell.js");
loadInto(sb, "ui-components.js");

const K = sb.KidLang;
const S = sb.UIShell;
const C = sb.UIComponents;
const doc = sb.document;

if (!K || !S || !C) {
    const missing = !K ? "kid-lang.js" : (!S ? "ui-shell.js" : "ui-components.js");
    check("共享 UI 层三个脚本都可加载", false, missing + " 未加载");
    console.log("\nRESULT: HAS FAILURES");
    process.exit(1);
}
/* ---------------- 断言：kid-lang ---------------- */

check("KidLang 已挂载", !!K && typeof K.statusOf === "function");
check("UIShell 已挂载", !!S && typeof S.ageModeOf === "function");
check("UIComponents 已挂载", !!C && typeof C.progressBar === "function");

check("ageModeOf 1-2 年级为 junior", S.ageModeOf(1) === "junior" && S.ageModeOf(2) === "junior");
check("ageModeOf 3-4 年级为 middle", S.ageModeOf(3) === "middle" && S.ageModeOf(4) === "middle");
check("ageModeOf 5-6 年级为 senior", S.ageModeOf(5) === "senior" && S.ageModeOf(6) === "senior");
check("无学生数据时分龄保守为 junior", S.ageModeOf(undefined) === "junior");

check("掌握度 90 为记得很牢", K.statusOf(90).label === "记得很牢" && K.statusOf(90).icon === "⭐");
check("掌握度 89 为已经掌握", K.statusOf(89).label === "已经掌握" && K.statusOf(89).icon === "🌳");
check("掌握度 75 为已经掌握", K.statusOf(75).label === "已经掌握");
check("掌握度 74 为基本会了", K.statusOf(74).label === "基本会了" && K.statusOf(74).icon === "🍀");
check("掌握度 55 为基本会了", K.statusOf(55).label === "基本会了");
check("掌握度 54 为正在学习", K.statusOf(54).label === "正在学习" && K.statusOf(54).icon === "🌿");
check("掌握度 30 为正在学习", K.statusOf(30).label === "正在学习");
check("掌握度 29 为刚开始", K.statusOf(29).label === "刚开始" && K.statusOf(29).icon === "🌱");
check("无掌握度降级为还没开始学",
    K.statusOf(null).label === "还没开始学" && K.statusOf(undefined).label === "还没开始学");
check("复习提醒走儿童语言", K.forgettingText(3) === "🌱 今天有 3 个知识需要照顾。");
check("无复习任务走空状态文案", K.forgettingText(0) === "🌳 今天没有知识需要复习。");
check("无错题走空状态文案", K.noWrongText() === "🎉 暂时没有需要攻克的错题！");
check("升级文案带前后状态",
    K.upgradeText(K.statusOf(60), K.statusOf(80), "两位数乘法").includes("🍀 → 🌳")
    && K.upgradeText(K.statusOf(60), K.statusOf(80), "两位数乘法").includes("两位数乘法")
    && K.upgradeText(K.statusOf(60), K.statusOf(80), "两位数乘法").includes("这个知识记得更牢啦！"));
check("升级文案也能表达正在学习到掌握",
    K.upgradeText(K.statusOf(40), K.statusOf(80)).includes("🌿 → 🌳"));
check("升级文案不出现掌握度之类的指标",
    !/掌握度|稳定性|遗忘风险/.test(K.upgradeText(K.statusOf(40), K.statusOf(95), "长度单位")));
check("答错第一级给方向提示",
    K.wrongFeedback(1).level === "方向提示"
    && K.wrongFeedback(1).title === "🤔 这里再想一下"
    && K.wrongFeedback(1).retryLabel === "我再试试");
check("答错逐级加帮助",
    K.wrongFeedback(2).level === "关键条件"
    && K.wrongFeedback(3).level === "步骤提示"
    && K.wrongFeedback(4).level === "完整讲解");
check("答错超过四级仍给完整讲解", K.wrongFeedback(9).level === "完整讲解");
check("鼓励语是固定表不是随机", K.encourage(0) === K.encourage(0) && K.encourage(0) !== K.encourage(1));
check("儿童语言不含裸算法指标",
    !/掌握度|稳定性|遗忘风险|Mastery|Stability/.test(
        JSON.stringify(K.statusOf(76)) + K.forgettingText(2) + K.upgradeText(K.statusOf(60), K.statusOf(80), "x")));

/* ---------------- 断言：ui-shell ---------------- */

check("默认学生 id 为 1", sb.localStorage.getItem("xiaozhi.student") === null && S.getStudentId() === "1");
check("分龄属性写到 html 上", (S.applyAgeMode(4), doc.documentElement.dataset.ageMode === "middle"));
check("设置默认值",
    JSON.stringify(S.getSettings()) === JSON.stringify({ sound: true, reduceMotion: false, fontScale: 1, focusMode: false }));
check("设置写入本地存储",
    (S.setSettings({ reduceMotion: true }), JSON.parse(sb.localStorage.getItem("xiaozhi.uiSettings")).reduceMotion === true));
check("减少动画写到 html 属性", doc.documentElement.dataset.reduceMotion === "on");
check("挂载五个一级导航项", (S.mountNav("today"), doc.querySelectorAll(".ph-nav-item").length === 10),
    doc.querySelectorAll(".ph-nav-item").length);
check("当前页高亮",
    !!doc.querySelector(".ph-nav--bottom .is-active")
    && doc.querySelector(".ph-nav--bottom .is-active").getAttribute("data-tab") === "today");
check("切换标签时高亮跟随",
    (S.mountNav("growth"),
        doc.querySelectorAll(".ph-nav-item.is-active").length === 2
        && doc.querySelector(".ph-nav--bottom .is-active").getAttribute("data-tab") === "growth"));
check("导航只有五个一级项（今天/成长/挑战/商城/我的）", S.NAV_TABS.length === 5
    && S.NAV_TABS.map(t => t.tab).join(",") === "today,growth,wrong,shop,profile");

(async function main() {
    /* 切换学生：二次确认（硬门禁） */
    const host = doc.createElement("div");
    host.innerHTML = '<button class="ph-student-item" data-student-id="2" data-student-name="童童">童童</button>';
    doc.body.appendChild(host);
    sb.localStorage.setItem("xiaozhi.student", "1");

    let broadcast = null;
    S.onStudentChange(id => { broadcast = id; });
    S.createStudentSwitcher(host);

    const item = host.querySelectorAll("[data-student-id]")[0];
    item.click();

    const box = doc.querySelector(".ph-confirm");
    check("点击学生弹出确认层", !!box);
    check("确认层文案带名字", !!box && box.textContent.includes("确定切换到童童吗？"), box && box.textContent);
    check("未确认前不改变当前学生", S.getStudentId() === "1", S.getStudentId());

    const yes = box.querySelectorAll("button").find(b => b.getAttribute("data-confirm") === "yes");
    check("确认层有确认按钮", !!yes);
    yes.click();
    await new Promise(r => setTimeout(r, 0));
    check("确认后才切换学生并广播", S.getStudentId() === "2" && broadcast === "2", broadcast);
    check("确认层已移除", !doc.querySelector(".ph-confirm"));

    /* 取消切换：不改变任何状态 */
    sb.localStorage.setItem("xiaozhi.student", "1");
    broadcast = null;
    const p2 = S.confirmSwitch({ id: "2", name: "童童" });
    const box2 = doc.querySelector(".ph-confirm");
    const no = box2.querySelectorAll("button").find(b => b.getAttribute("data-confirm") === "no");
    no.click();
    const cancelled = await p2;
    check("取消返回 false", cancelled === false);
    check("取消切换不改变学生", S.getStudentId() === "1" && broadcast === null);

    /* 学生列表失败降级 */
    const list = await S.loadStudents();
    check("学生列表请求失败返回空数组", Array.isArray(list) && list.length === 0, JSON.stringify(list));

    /* 无 localStorage 的沙箱不得抛异常 */
    let threw = null;
    try {
        const sb2 = makeSandbox({ withStorage: false });
        loadInto(sb2, "kid-lang.js");
        loadInto(sb2, "ui-shell.js");
        sb2.UIShell.getStudentId();
        sb2.UIShell.setSettings({ sound: false });
        sb2.UIShell.getSettings();
    } catch (err) {
        threw = err;
    }
    check("无 localStorage 时不抛异常", threw === null, threw && threw.message);

    /* ---------------- 断言：ui-components ---------------- */

    check("进度条不只靠颜色",
        C.progressBar({ value: 3, max: 8, label: "3 / 8" }).includes('role="progressbar"')
        && C.progressBar({ value: 3, max: 8 }).includes("3 / 8"));
    check("空状态不用 No data",
        C.emptyState({ icon: "🎉", title: "暂时没有需要攻克的错题！" }).includes("🎉")
        && !/No data|no data/.test(C.emptyState({ icon: "x", title: "y" })));
    check("Loading 用菲比文案", C.loadingState({}).includes("菲比正在准备一道适合你的题"));
    check("错误状态不含技术错误码",
        !/HTTP|502|500/.test(C.errorState({}))
        && C.errorState({}).includes("菲比刚刚没拿到题目，我们再试一次。")
        && C.errorState({}).includes("再试一次"));
    check("提示面板带我再试试与当前帮助级别",
        C.hintPanel({ level: "方向提示", title: "🤔 这里再想一下", body: "先看看单位", retryLabel: "我再试试" }).includes("我再试试")
        && C.hintPanel({ level: "关键条件", title: "🤔 这里再想一下", body: "x" }).includes("关键条件")
        && C.hintPanel({ title: "🤔 这里再想一下" }).includes("🤔 这里再想一下"));
    check("升级判定只认档位上升",
        typeof K.isUpgrade === "function"
        && K.isUpgrade("learning", "mastered") === true
        && K.isUpgrade("mastered", "learning") === false
        && K.isUpgrade(undefined, "mastered") === false
        && K.rankOf("solid") > K.rankOf("sprout"));
    check("题卡含读题入口",
        C.questionCard({ subject: "数学", knowledge: "应用题", index: 3, total: 8, question: "小明有 5 个苹果", canSpeak: true }).includes("读题目")
        && C.questionCard({ subject: "数学", knowledge: "应用题", index: 3, total: 8, question: "x" }).includes('data-speaking="0"'));
    check("题卡右上有进度",
        C.questionCard({ subject: "数学", knowledge: "应用题", index: 3, total: 8, question: "x" }).includes("3 / 8"));
    check("选项整块可点",
        C.answerOption({ text: "8", index: 1, state: "idle" }).includes("<button")
        && C.answerOption({ text: "8", index: 1, state: "idle" }).includes("ph-option"));
    check("答错选项用柔和橙不用红", C.answerOption({ text: "8", index: 1, state: "wrong" }).includes("is-wrong"));
    check("知识状态走儿童语言",
        C.knowledgeStatus({ mastery: 80 }).includes("🌳") && C.knowledgeStatus({ mastery: 80 }).includes("已经掌握"));
    check("组件全部转义",
        C.esc("<script>") === "&lt;script&gt;"
        && C.questionCard({ subject: "s", knowledge: "k", index: 1, total: 1, question: "<script>alert(1)</script>" }).indexOf("<script>") === -1);
    check("成长摘要是学会什么不是做多少题",
        !/做了|共完成|总题量/.test(C.growthSummary({ days: 5, newMastered: 4, wrongFixed: 8, consolidated: 12 }))
        && C.growthSummary({ days: 5, newMastered: 4, wrongFixed: 8, consolidated: 12 }).includes("新掌握"));
    check("完成卡主打查看成长",
        C.completionCard({ items: ["🌱 学会 1 个新知识"], primaryLabel: "查看我的成长" }).includes("查看我的成长"));
    /* ---------------- 断言：手机 / 内网访问（V2.8） ---------------- */
    const pages = fs.readdirSync(__dirname).filter(function (f) { return /\.html$/.test(f); });
    const noViewport = pages.filter(function (f) {
        return !/name="viewport"/.test(fs.readFileSync(path.join(__dirname, f), "utf8"));
    });
    check("每个页面都声明 viewport（手机不会缩成桌面版）",
        pages.length >= 18 && noViewport.length === 0, noViewport.join(",") || (pages.length + " 页"));
    const noCover = pages.filter(function (f) {
        return fs.readFileSync(path.join(__dirname, f), "utf8").indexOf("viewport-fit=cover") === -1;
    });
    check("viewport 允许刘海安全区（viewport-fit=cover）", noCover.length === 0, noCover.join(","));
    const cssSrc = fs.readFileSync(path.join(__dirname, "style.css"), "utf8");
    check("手机档样式存在（≤720px 单列 + 底部导航让出安全区 + 不缩放字号）",
        /@media\s*\(max-width:720px\)/.test(cssSrc)
        && cssSrc.indexOf("safe-area-inset-bottom") !== -1
        && cssSrc.indexOf("-webkit-text-size-adjust") !== -1);
    const batSrc = fs.readFileSync(path.join(__dirname, "..", "start.bat"), "utf8");
    check("启动脚本固定 8000 端口并监听所有网卡（同一网段的手机可访问）",
        batSrc.indexOf('set "PORT=8000"') !== -1
        && batSrc.indexOf("--host 0.0.0.0") !== -1
        && batSrc.indexOf("%LAN_IP%") !== -1
        && batSrc.indexOf("PHONE_URL") !== -1);

    console.log("\nRESULT:", ok ? "ALL PASS" : "HAS FAILURES");
    process.exit(ok ? 0 : 1);
})();
