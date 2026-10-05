// ==============================================================
// 能力契约｜页面：我的挑战（把 V2.5 错题康复讲成「⚔️ 我的挑战」）
// 入口：init / renderSummary / renderGroups / loadChallenge / toggleStudentPicker
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js；
//       GET /students、GET /api/challenge/{sid}、POST /api/recovery/start
// 不负责：康复状态机 / 提示层级 / 变式题（backend/recovery/）、判分（backend/grading.py）
// 验证：node frontend/verify_v26_web.js
// 被调用：challenge.html
// 索引：docs/MODULE_MAP.md · ARCHITECTURE.md §挑战中心
// ==============================================================

// 挑战页只回答一件事：「我还有哪些错题没攻克？」
// 三色看板的颜色与文字全部来自后端 kid_status.challenge_status，前端不自己判状态。

var STUDENT_KEY = "xiaozhi.student";
var API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin : "http://127.0.0.1:8000";

var students = [];
var GROUPS = ["red", "yellow", "green"];

function $(id) { return document.getElementById(id); }
function uc() { return (typeof UIComponents !== "undefined") ? UIComponents : null; }
function shell() { return (typeof UIShell !== "undefined") ? UIShell : null; }
function kid() { return (typeof KidLang !== "undefined") ? KidLang : null; }

function esc(text) {
    return String(text === undefined || text === null ? "" : text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function jsonFetch(url, options) {
    return fetch(url, options).then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
    });
}

function postJson(url, payload) {
    return jsonFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
}

function loadingHtml(text) {
    var c = uc();
    return c ? c.loadingState({ text: text })
        : '<div class="ph-state ph-state--loading"><p class="ph-state-title">' + esc(text) + '</p></div>';
}

function errorHtml(title, handlerName) {
    var c = uc();
    return c ? c.errorState({ title: title, retryAction: handlerName + "()" })
        : '<div class="ph-state ph-state--error"><p class="ph-state-title">' + esc(title) + '</p>'
            + '<button type="button" class="ph-btn ph-btn--primary" onclick="' + esc(handlerName) + '()">再试一次</button></div>';
}

function num(value) {
    var n = parseInt(value, 10);
    return isNaN(n) ? 0 : n;
}

function currentStudentId() {
    var s = shell();
    if (s && s.getStudentId) return s.getStudentId();
    try { return localStorage.getItem(STUDENT_KEY) || "1"; } catch (err) { return "1"; }
}

/* ---------------- 渲染（纯函数，便于验证） ---------------- */

// data = { total, counts: { red, yellow, green } } 或 { empty: true }
function renderSummary(data) {
    data = data || {};
    var counts = data.counts || {};
    if (data.empty || !num(data.total)) {
        var emptyText = (kid() && kid().noWrongText) ? kid().noWrongText() : "🎉 暂时没有需要攻克的错题！";
        var c = uc();
        return c ? c.emptyState({ icon: "🎉", title: emptyText })
            : '<div class="ph-state ph-state--empty"><p class="ph-state-title">' + esc(emptyText) + '</p></div>';
    }
    var rows = [
        { icon: "🔴", label: "等我攻克", value: num(counts.red), unit: "道" },
        { icon: "🟡", label: "正在训练", value: num(counts.yellow), unit: "道" },
        { icon: "🟢", label: "已经攻克", value: num(counts.green), unit: "道" }
    ];
    return '<div class="ph-card ph-growth"><p class="ph-growth-title">你有 '
        + esc(num(data.total)) + ' 道挑战</p><ul class="ph-growth-list">'
        + rows.map(function (row) {
            return '<li><span aria-hidden="true">' + esc(row.icon) + '</span>'
                + esc(row.label) + ' <b class="ph-num">' + esc(row.value) + '</b> ' + esc(row.unit) + '</li>';
        }).join("") + '</ul></div>';
}

function itemHtml(node) {
    var title = node.question ? String(node.question) : (node.knowledge || "这道题");
    if (title.length > 40) title = title.slice(0, 40) + "…";
    return '<li class="ph-wrong" data-status="' + esc(node.tone) + '">'
        + '<span class="ph-wrong-title">' + esc(title) + '</span>'
        + '<span class="ph-wrong-sub">' + esc(node.subject || "") + ' · ' + esc(node.knowledge || "") + '</span>'
        + '<span class="ph-wrong-status">' + esc(node.icon || "") + " " + esc(node.tone_text || "") + '</span>'
        + '<span class="ph-wrong-actions">'
        + '<button type="button" class="ph-btn ph-btn--primary" onclick="startRecovery(' + esc(num(node.recovery_id)) + ')"'
        + (node.tone === "green" ? ' disabled' : "") + '>'
        + (node.tone === "green" ? "已经掌握了" : "去攻克") + '</button></span></li>';
}

// data = { groups: { red: [...], yellow: [...], green: [...] }, tones: {...} }
function renderGroups(data) {
    data = data || {};
    var groups = data.groups || {};
    var tones = data.tones || { red: "🔴 等我攻克", yellow: "🟡 正在训练", green: "🟢 已经攻克" };
    var blocks = GROUPS.map(function (key) {
        var items = groups[key] || [];
        if (!items.length) return "";
        return '<section class="ph-wrong-group"><h3 class="ph-section-title">'
            + esc(tones[key] || "")
            + ' <span class="ph-num">' + esc(items.length) + '</span></h3><ul class="ph-wrong-list">'
            + items.map(itemHtml).join("") + '</ul></section>';
    }).join("");
    if (!blocks) {
        var emptyText = (kid() && kid().noWrongText) ? kid().noWrongText() : "🎉 暂时没有需要攻克的错题！";
        return '<p class="ph-lead">' + esc(emptyText) + '</p>';
    }
    return blocks;
}

/* ---------------- 数据 ---------------- */

function setStatus(html) {
    var box = $("challenge-status");
    if (box) box.innerHTML = html || "";
}

function loadChallenge() {
    var sid = currentStudentId();
    setStatus(loadingHtml("菲比正在看你的挑战……"));
    var summary = $("challenge-summary");
    var groups = $("challenge-groups");
    if (summary) summary.innerHTML = "";
    if (groups) groups.innerHTML = "";
    jsonFetch(API + "/api/challenge/" + encodeURIComponent(sid))
        .then(function (data) {
            setStatus("");
            if (summary) {
                summary.innerHTML = renderSummary((data && data.total)
                    ? data : { empty: true });
            }
            if (groups) groups.innerHTML = renderGroups(data);
            if (data && data.message) {
                var greet = $("phoebe-greeting");
                if (greet) greet.textContent = "🐼 菲比：" + data.message;
            }
        })
        .catch(function (err) {
            console.error("[challenge] 加载失败", err);
            setStatus(errorHtml("菲比刚刚没拿到挑战列表，我们再试一次。", "loadChallenge"));
        });
}

// 去攻克：复用 V2.5 的康复流程（/api/recovery/start），再进康复页继续
function startRecovery(recoveryId) {
    var sid = currentStudentId();
    setStatus(loadingHtml("正在准备这道挑战……"));
    postJson(API + "/api/recovery/start", { student_id: Number(sid), recovery_id: Number(recoveryId) })
        .then(function () {
            location.href = "recovery.html?student_id=" + encodeURIComponent(sid)
                + "&recovery_id=" + encodeURIComponent(recoveryId);
        })
        .catch(function (err) {
            console.error("[challenge] 开始康复失败", err);
            setStatus(errorHtml("菲比刚刚没准备好这道挑战，我们再试一次。", "loadChallenge"));
        });
}

/* ---------------- 顶部学生条（与成长页同一套交互） ---------------- */

function updateWho() {
    var sid = currentStudentId();
    var me = students.filter(function (s) { return String(s.id) === String(sid); })[0];
    var name = $("who-name");
    var grade = $("who-grade");
    if (name) name.textContent = me ? me.name : "小朋友";
    if (grade) grade.textContent = me ? (me.grade_text || "") : "";
    if (me && shell() && shell().applyAgeMode) shell().applyAgeMode(me.grade);
    var picker = $("student-picker");
    if (picker) {
        picker.innerHTML = students.map(function (s) {
            var active = String(s.id) === String(sid);
            return '<button type="button" class="ph-student' + (active ? " is-active" : "")
                + '" data-student-id="' + esc(s.id) + '">'
                + esc(s.name) + ' · ' + esc(s.grade_text || "") + '</button>';
        }).join("");
    }
}

function toggleStudentPicker() {
    var picker = $("student-picker");
    var button = $("switch-student");
    if (!picker) return;
    var hidden = picker.classList.toggle("hidden");
    if (button) button.setAttribute("aria-expanded", hidden ? "false" : "true");
    if (hidden) return;
    var s = shell();
    if (s && s.createStudentSwitcher) {
        s.createStudentSwitcher(picker);
    }
    var list = s && s.loadStudents ? s.loadStudents() : Promise.resolve([]);
    Promise.resolve(list).then(function (items) {
        students = items || [];
        updateWho();
    });
}

function init() {
    var s = shell();
    if (s && s.onStudentChange) {
        s.onStudentChange(function () {
            // 切换学生：先清空上一个孩子的挑战，再重新拉取
            var summary = $("challenge-summary");
            var groups = $("challenge-groups");
            if (summary) summary.innerHTML = "";
            if (groups) groups.innerHTML = "";
            setStatus(loadingHtml("正在换到另一位小朋友……"));
            loadChallenge();
            updateWho();
        });
    }
    var list = s && s.loadStudents ? s.loadStudents() : Promise.resolve([]);
    Promise.resolve(list).then(function (items) {
        students = items || [];
        updateWho();
        loadChallenge();
    });
}

var root = (typeof window !== "undefined") ? window : this;
root.ChallengePage = {
    init: init,
    renderSummary: renderSummary,
    renderGroups: renderGroups,
    loadChallenge: loadChallenge,
    toggleStudentPicker: toggleStudentPicker
};
