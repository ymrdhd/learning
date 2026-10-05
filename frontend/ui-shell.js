// ==============================================================
// 能力契约｜全局学生状态 / 分龄 / 显示设置 / 一级导航壳
// 入口：UIShell.ageModeOf / applyAgeMode / getStudentId / setStudentId /
//       onStudentChange / loadStudents / getSettings / setSettings /
//       applySettings / mountNav / confirmSwitch / createStudentSwitcher
// 依赖：无（零构建；KidLang 同页共存但非必需）
// 不负责：页面业务逻辑 → 各页 js；组件 HTML → ui-components.js
// 验证：node frontend/verify_ui_shell.js
// 被调用：所有儿童端页面（**必须先于业务 js 加载**）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 儿童端唯一的"当前学生"来源。
 *
 * 在这之前每个页面各自读 localStorage["xiaozhi.student"]，切换学生后别的
 * 页面不知道。现在统一走这里：getStudentId() / setStudentId() / onStudentChange()。
 *
 * 切换学生是**破坏性操作**（会把作答写到另一个孩子名下），所以必须二次确认：
 * confirmSwitch() 返回 Promise<boolean>，取消时任何状态都不改变。
 *
 * 用法：<script src="ui-shell.js"></script>，页面里 UIShell.mountNav("today")。
 */

(function (root) {
    "use strict";

    var STUDENT_KEY = "xiaozhi.student";
    var SETTINGS_KEY = "xiaozhi.uiSettings";
    var DEFAULT_STUDENT = "1";

    var API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
        ? location.origin.replace(/\/app\/?$/, "")
        : "http://127.0.0.1:8000";

    // 一级导航 5 项：今天 / 成长 / 错题 / 商城 / 我的。
    // 仍不加排行榜、活动、宠物、AI、测评等一级入口。
    // V2.8：积分商城是「今天」页里的一张卡片 + 一张独立页面（挑战下方入口，只展示不兑换）。
    var NAV_TABS = [
        { tab: "today", icon: "🏠", label: "今天", href: "today.html" },
        { tab: "growth", icon: "🗺", label: "成长", href: "growth.html" },
        { tab: "wrong", icon: "⚔️", label: "挑战", href: "challenge.html" },
        { tab: "shop", icon: "🛍️", label: "商城", href: "shop.html" },
        { tab: "profile", icon: "👤", label: "我的", href: "profile.html" }
    ];

    var DEFAULT_SETTINGS = { sound: true, reduceMotion: false, fontScale: 1, focusMode: false };

    /* ---------------- 本地存储（隐私模式下降级为内存） ---------------- */

    var memory = {};

    function readStore(key) {
        try {
            if (typeof localStorage !== "undefined" && localStorage) {
                return localStorage.getItem(key);
            }
        } catch (err) {
            // 隐私模式下 localStorage 不可用，走内存
        }
        return Object.prototype.hasOwnProperty.call(memory, key) ? memory[key] : null;
    }

    function writeStore(key, value) {
        memory[key] = String(value);
        try {
            if (typeof localStorage !== "undefined" && localStorage) {
                localStorage.setItem(key, String(value));
            }
        } catch (err) {
            // 静默降级
        }
    }

    function esc(s) {
        return String(s === undefined || s === null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function docRoot() {
        return (typeof document !== "undefined" && document && document.documentElement) ? document.documentElement : null;
    }

    function setDataAttr(name, value) {
        var el = docRoot();
        if (!el || !el.setAttribute) return;
        var attr = "data-" + String(name).replace(/([A-Z])/g, function (m, c) { return "-" + c.toLowerCase(); });
        el.setAttribute(attr, String(value));
    }

    /* ---------------- 分龄 ---------------- */

    // 1-2 年级 JUNIOR，3-4 年级 MIDDLE，5-6 年级 SENIOR。
    // 年级未知时保守按 JUNIOR（字更大、按钮更大，对小孩子更安全）。
    function ageModeOf(grade) {
        var g = typeof grade === "number" ? grade : parseInt(grade, 10);
        if (isNaN(g) || g <= 2) return "junior";
        if (g <= 4) return "middle";
        return "senior";
    }

    function applyAgeMode(grade) {
        var mode = ageModeOf(grade);
        setDataAttr("ageMode", mode);
        return mode;
    }

    /* ---------------- 当前学生 ---------------- */

    var subscribers = [];

    function getStudentId() {
        var v = readStore(STUDENT_KEY);
        return (v === null || v === "") ? DEFAULT_STUDENT : String(v);
    }

    function setStudentId(id) {
        var next = (id === null || id === undefined || id === "") ? DEFAULT_STUDENT : String(id);
        writeStore(STUDENT_KEY, next);
        for (var i = 0; i < subscribers.length; i++) {
            try {
                subscribers[i](next);
            } catch (err) {
                // 单个订阅者出错不影响其他页面刷新
            }
        }
        return next;
    }

    function onStudentChange(handler) {
        if (typeof handler === "function") subscribers.push(handler);
    }

    function loadStudents() {
        if (typeof fetch !== "function") return Promise.resolve([]);
        return fetch(API + "/students")
            .then(function (res) { return res.ok ? res.json() : []; })
            .then(function (data) { return Array.isArray(data) ? data : []; })
            .catch(function () { return []; });
    }

    /* ---------------- 显示设置 ---------------- */

    function getSettings() {
        var out = {
            sound: DEFAULT_SETTINGS.sound,
            reduceMotion: DEFAULT_SETTINGS.reduceMotion,
            fontScale: DEFAULT_SETTINGS.fontScale,
            focusMode: DEFAULT_SETTINGS.focusMode
        };
        var raw = readStore(SETTINGS_KEY);
        if (raw) {
            try {
                var parsed = JSON.parse(raw);
                if (parsed && typeof parsed === "object") {
                    if (typeof parsed.sound === "boolean") out.sound = parsed.sound;
                    if (typeof parsed.reduceMotion === "boolean") out.reduceMotion = parsed.reduceMotion;
                    if (typeof parsed.fontScale === "number") out.fontScale = parsed.fontScale;
                    if (typeof parsed.focusMode === "boolean") out.focusMode = parsed.focusMode;
                }
            } catch (err) {
                // 数据损坏时回退默认值
            }
        }
        return out;
    }

    function applySettings(settings) {
        var s = settings || getSettings();
        setDataAttr("reduceMotion", s.reduceMotion ? "on" : "off");
        setDataAttr("focusMode", s.focusMode ? "on" : "off");
        setDataAttr("fontScale", String(s.fontScale));
        return s;
    }

    function setSettings(patch) {
        var next = getSettings();
        if (patch && typeof patch === "object") {
            for (var k in patch) {
                if (Object.prototype.hasOwnProperty.call(next, k) && patch[k] !== undefined) {
                    next[k] = patch[k];
                }
            }
        }
        writeStore(SETTINGS_KEY, JSON.stringify(next));
        applySettings(next);
        return next;
    }

    /* ---------------- 一级导航 ---------------- */

    function navItemHtml(item, activeTab) {
        var active = item.tab === activeTab;
        return '<a class="ph-nav-item' + (active ? " is-active" : "") + '"'
            + ' data-tab="' + esc(item.tab) + '"'
            + ' href="' + esc(item.href) + '"'
            + (active ? ' aria-current="page"' : "")
            + '><span class="ph-nav-icon" aria-hidden="true">' + esc(item.icon) + '</span>'
            + '<span class="ph-nav-label">' + esc(item.label) + '</span></a>';
    }

    function ensureNav(className, label) {
        var el = document.querySelector("." + className);
        if (!el) {
            el = document.createElement("nav");
            el.className = "ph-nav " + className;
            el.setAttribute("aria-label", label);
            document.body.appendChild(el);
        }
        return el;
    }

    function mountNav(activeTab) {
        if (typeof document === "undefined" || !document || !document.body) return null;
        if (document.body.classList) document.body.classList.add("ph-has-nav");
        var html = NAV_TABS.map(function (t) { return navItemHtml(t, activeTab); }).join("");
        var bottom = ensureNav("ph-nav--bottom", "主导航");
        bottom.innerHTML = html;
        var side = ensureNav("ph-nav--side", "主导航");
        side.innerHTML = html;
        return bottom;
    }

    /* ---------------- 学生切换（硬门禁） ---------------- */

    function confirmSwitch(student) {
        return new Promise(function (resolve) {
            if (typeof document === "undefined" || !document || !document.body) {
                resolve(false);
                return;
            }
            var name = (student && student.name) ? String(student.name) : "";

            var overlay = document.createElement("div");
            overlay.className = "ph-confirm";
            overlay.setAttribute("role", "dialog");
            overlay.setAttribute("aria-modal", "true");
            overlay.innerHTML =
                '<div class="ph-confirm-box">'
                + '<p class="ph-confirm-title">确定切换到' + esc(name) + '吗？</p>'
                + '<div class="ph-confirm-actions">'
                + '<button type="button" class="ph-btn ph-btn--secondary" data-confirm="no">再想想</button>'
                + '<button type="button" class="ph-btn ph-btn--primary" data-confirm="yes">确定</button>'
                + '</div></div>';
            document.body.appendChild(overlay);

            var settled = false;

            function finish(ok) {
                if (settled) return;
                settled = true;
                if (overlay.remove) overlay.remove();
                resolve(ok);
            }

            overlay.addEventListener("click", function (ev) {
                if (ev && ev.target === overlay) finish(false);
            });

            var buttons = overlay.querySelectorAll("button");
            for (var i = 0; i < buttons.length; i++) {
                (function (btn) {
                    btn.addEventListener("click", function () {
                        finish(btn.getAttribute("data-confirm") === "yes");
                    });
                })(buttons[i]);
            }
        });
    }

    function createStudentSwitcher(el) {
        if (!el || !el.querySelectorAll) return;
        var items = el.querySelectorAll("[data-student-id]");
        for (var i = 0; i < items.length; i++) {
            (function (item) {
                item.addEventListener("click", function () {
                    var id = item.getAttribute("data-student-id");
                    if (id === null || id === "") return;
                    if (String(id) === getStudentId()) return;
                    var name = item.getAttribute("data-student-name")
                        || String(item.textContent || "").replace(/\s+/g, "");
                    confirmSwitch({ id: id, name: name }).then(function (yes) {
                        if (yes) setStudentId(id);
                    });
                });
            })(items[i]);
        }
    }

    root.UIShell = {
        STUDENT_KEY: STUDENT_KEY,
        SETTINGS_KEY: SETTINGS_KEY,
        DEFAULT_STUDENT: DEFAULT_STUDENT,
        NAV_TABS: NAV_TABS,
        DEFAULT_SETTINGS: DEFAULT_SETTINGS,
        API: API,
        ageModeOf: ageModeOf,
        applyAgeMode: applyAgeMode,
        getStudentId: getStudentId,
        setStudentId: setStudentId,
        onStudentChange: onStudentChange,
        loadStudents: loadStudents,
        getSettings: getSettings,
        setSettings: setSettings,
        applySettings: applySettings,
        mountNav: mountNav,
        confirmSwitch: confirmSwitch,
        createStudentSwitcher: createStudentSwitcher
    };
})(typeof window !== "undefined" ? window : this);
