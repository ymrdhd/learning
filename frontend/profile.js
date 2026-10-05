// ==============================================================
// 能力契约｜页面：我的（头像 / 昵称 / 年级 / 切换学生 / 声音 · 显示 · 减少动画）
// 入口：init / renderProfile / renderSettings / toggleSetting / setFontScale / renderDataSection / confirmReset / resetUser
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js；GET /students
// 不负责：账号体系（本地双用户由 backend/local_users.py 提供）
// 验证：node frontend/verify_growth_profile_web.js
// 被调用：profile.html
// 索引：docs/MODULE_MAP.md · SPEC.md §8
// ==============================================================

// 儿童端「我的」只放孩子自己能看懂、能改的东西：
// 头像、昵称、年级、切换学生、声音、显示、减少动画。
// 不放任何密钥、数据库路径、算法参数或管理配置。

var STUDENT_KEY = "xiaozhi.student";

var students = [];
// 家长操作区状态：预览（有多少条要清）/ 提示文案（上次操作的结果）
var resetPreview = null;
var resetNotice = "";
var FONT_SCALES = [
    { value: "1", label: "正常" },
    { value: "1.15", label: "大一点" },
    { value: "1.3", label: "更大" }
];

function $(id) { return document.getElementById(id); }
function uc() { return (typeof UIComponents !== "undefined") ? UIComponents : null; }
function shell() { return (typeof UIShell !== "undefined") ? UIShell : null; }

function esc(text) {
    return String(text === undefined || text === null ? "" : text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ---------------- 渲染（纯函数，便于验证） ---------------- */

function avatarOf(student) {
    return (student && student.avatar === "girl") ? "🐰" : "🐼";
}

function findStudent(id) {
    var target = String(id === undefined || id === null ? "" : id);
    for (var i = 0; i < students.length; i++) {
        if (String(students[i].id) === target) return students[i];
    }
    return null;
}

// 返回「我是谁」+「切换学生」两段内容。二次确认由 ui-shell 的 createStudentSwitcher 负责。
function renderProfile(student, list) {
    student = student || {};
    var items = Array.isArray(list) ? list : students;
    if (!items.length && student.name) items = [student];

    var head = '<div class="ph-profile-head">'
        + '<span class="ph-avatar ph-avatar--big" aria-hidden="true">' + esc(avatarOf(student)) + '</span>'
        + '<div class="ph-who">'
        + '<span class="ph-who-name">' + esc(student.name || "小朋友") + '</span>'
        + (student.grade_text ? '<span class="ph-who-grade">' + esc(student.grade_text) + '</span>' : "")
        + '</div></div>';

    var currentId = shell() ? shell().getStudentId() : "";
    var buttons = items.map(function (s) {
        var active = String(s.id) === String(currentId);
        return '<button type="button" class="ph-student' + (active ? " is-active" : "") + '"'
            + ' data-student-id="' + esc(s.id) + '" data-student-name="' + esc(s.name || "") + '">'
            + esc(s.name || "小朋友")
            + '<span class="ph-student-grade">' + esc(s.grade_text || "") + '</span></button>';
    }).join("");

    return head
        + '<h2 class="ph-section-title">切换学生</h2>'
        + '<p class="ph-lead">换人之前，菲比会先问你一句「确定要换吗」，不会点错就换掉。</p>'
        + '<div class="ph-students">' + (buttons || '<p class="ph-state-hint">这台电脑上只有你一个小朋友。</p>') + '</div>';
}

function toggleRow(key, label, hint, on) {
    return '<li class="ph-setting">'
        + '<span class="ph-setting-main"><span class="ph-setting-label">' + esc(label) + '</span>'
        + '<span class="ph-setting-hint">' + esc(hint) + '</span></span>'
        + '<button type="button" class="ph-switch' + (on ? " is-on" : "") + '" role="switch"'
        + ' aria-checked="' + (on ? "true" : "false") + '" aria-label="' + esc(label) + '"'
        + ' onclick="ProfilePage.toggleSetting(\'' + esc(key) + '\')">'
        + '<span class="ph-switch-text">' + (on ? "开着" : "关掉") + '</span></button></li>';
}

function selectRow(key, label, hint, options, value) {
    var opts = options.map(function (o) {
        return '<option value="' + esc(o.value) + '"'
            + (String(o.value) === String(value) ? " selected" : "") + '>' + esc(o.label) + '</option>';
    }).join("");
    return '<li class="ph-setting">'
        + '<span class="ph-setting-main"><span class="ph-setting-label">' + esc(label) + '</span>'
        + '<span class="ph-setting-hint">' + esc(hint) + '</span></span>'
        + '<label class="ph-setting-control"><span class="ph-visually-hidden">' + esc(label) + '</span>'
        + '<select id="' + esc(key) + '" onchange="ProfilePage.setFontScale(this.value)">' + opts + '</select></label></li>';
}

function renderSettings(settings) {
    var s = settings || (shell() ? shell().getSettings() : null) || {};
    return '<ul class="ph-settings">'
        + toggleRow("sound", "声音", "读题和做对时的提示音，随时可以关掉", s.sound !== false)
        + selectRow("fontScale", "显示", "字大一点，看得更清楚", FONT_SCALES, s.fontScale || 1)
        + toggleRow("reduceMotion", "减少动画", "不想看动画的时候就打开", s.reduceMotion === true)
        + '</ul>';
}

/* ---------------- 家长操作：先备份，再重置 ---------------- */

// 表名 → 儿童/家长看得懂的说法（与 backend/user_routes.py 的表清单对应）
var RESET_TABLE_LABELS = {
    answer_records: "答题记录",
    abilities: "能力分数",
    student_knowledge_mastery: "知识掌握度",
    reviews: "复习计划",
    wrong_questions: "错题",
    answer_error_analysis: "错因分析",
    ability_profile: "能力画像",
    diagnostic_sessions: "能力诊断",
    diagnostic_records: "诊断作答",
    learning_plan: "学习计划",
    learning_strategy_log: "策略日志",
    learning_feedback: "学习感受",
    knowledge_memory_state: "记忆状态",
    review_records: "复习记录",
    review_queue: "复习队列",
    review_strategy_log: "复习日志",
    wrong_question_recovery: "错题康复",
    daily_learning_task: "每日任务",
    learning_habit_profile: "学习习惯",
    active_recall_record: "主动回忆"
};

function apiBase() {
    var shellApi = shell();
    return (shellApi && shellApi.API) ? shellApi.API : "";
}

function resetCountHtml(tables) {
    var keys = Object.keys(tables || {});
    if (!keys.length) return "";
    return '<ul class="ph-settings">' + keys.map(function (key) {
        var label = RESET_TABLE_LABELS[key] || key;
        return '<li class="ph-setting"><span class="ph-setting-main">'
            + '<span class="ph-setting-label">' + esc(label) + '</span>'
            + '<span class="ph-setting-hint">' + esc(String(tables[key])) + ' 条</span></span></li>';
    }).join("") + '</ul>';
}

// 家长操作区（纯函数，便于验证）：说明 + 「备份并重置」按钮
function renderDataSection(student, preview) {
    student = student || {};
    var name = esc(student.name || "这个小朋友");
    var info = preview || {};
    var total = Number(info.total || 0);
    var detail = total > 0 ? resetCountHtml(info.tables) : "";
    var countLine = total > 0
        ? "现在有 " + total + " 条学习记录，点一下会在确认后先备份、再清空。"
        : "点一下会先告诉你有多少条记录，确认之后才会备份并清空。";
    return '<p class="ph-lead">重新开始之前，菲比会先把' + name + '的学习记录备份成一个文件'
        + '（放在电脑上的 backup/user_reset 文件夹里），再清空记录。'
        + '另一个小朋友的数据不受影响。</p>'
        + '<p class="ph-state-hint">' + esc(countLine) + '</p>'
        + detail
        + '<p class="ph-row-secondary">'
        + '<button type="button" class="ph-btn ph-btn--secondary"'
        + ' onclick="ProfilePage.resetUser()">备份并重置' + name + '的数据</button></p>';
}

// 重置前必须二次确认（复用 ui-shell 的 .ph-confirm 样式；取消则什么都不做）
function confirmReset(name, total) {
    return new Promise(function (resolve) {
        var host = (typeof document !== "undefined") ? document.body : null;
        if (!host || typeof host.appendChild !== "function"
            || typeof document.createElement !== "function") {
            resolve(false);
            return;
        }
        var overlay = document.createElement("div");
        overlay.className = "ph-confirm";
        overlay.innerHTML = '<div class="ph-confirm-box">'
            + '<p class="ph-confirm-title">确定要重置' + esc(name) + '吗？</p>'
            + '<p class="ph-state-hint">菲比会先把 ' + esc(String(total || 0)) + ' 条学习记录备份成文件，'
            + '然后清空。成绩、错题、复习进度都会回到刚建号的样子，这一步不能撤销。</p>'
            + '<div class="ph-confirm-actions">'
            + '<button type="button" class="ph-btn ph-btn--secondary" data-confirm="no">再想想</button>'
            + '<button type="button" class="ph-btn ph-btn--primary" data-confirm="yes">先备份，再重置</button>'
            + '</div></div>';
        function finish(ok) {
            if (typeof overlay.remove === "function") overlay.remove();
            resolve(ok);
        }
        if (typeof overlay.addEventListener === "function") {
            overlay.addEventListener("click", function (ev) {
                var node = ev && ev.target;
                while (node && node !== overlay) {
                    if (typeof node.getAttribute === "function"
                        && node.getAttribute("data-confirm")) {
                        finish(node.getAttribute("data-confirm") === "yes");
                        return;
                    }
                    node = node.parentNode;
                }
            });
        }
        host.appendChild(overlay);
    });
}

function renderData(preview) {
    var box = $("profile-data");
    if (!box) return;
    if (preview !== undefined) resetPreview = preview;
    var shellApi = shell();
    var student = (shellApi ? findStudent(shellApi.getStudentId()) : null) || {};
    box.innerHTML = renderDataSection(student, resetPreview)
        + (resetNotice ? '<p class="ph-state-hint">' + esc(resetNotice) + '</p>' : "");
}

function setResetNotice(text) {
    resetNotice = text || "";
    renderData();
}

// 备份并重置：先取预览 → 二次确认 → POST 重置（后端先备份成功才清空）
function resetUser() {
    var shellApi = shell();
    if (!shellApi || !$("profile-data")) return;
    var studentId = shellApi.getStudentId();
    if (!studentId) return;
    var student = findStudent(studentId) || {};
    var url = apiBase() + "/api/user/" + encodeURIComponent(studentId);

    setResetNotice("菲比正在看看" + (student.name || "小朋友") + "有多少条记录…");
    fetch(url + "/reset-preview")
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (preview) {
            if (!preview) throw new Error("preview failed");
            renderData(preview);
            return confirmReset(preview.name || student.name || "小朋友", preview.total)
                .then(function (yes) { return yes ? true : null; });
        })
        .then(function (go) {
            if (!go) { setResetNotice("好的，什么都没动。"); return null; }
            setResetNotice("正在备份并重置…");
            return fetch(url + "/reset", { method: "POST" })
                .then(function (res) { return res.ok ? res.json() : null; })
                .then(function (data) {
                    if (!data) throw new Error("reset failed");
                    resetPreview = null;
                    setResetNotice("已经备份成 " + (data.backup_file || "备份文件")
                        + "，并清空了 " + (data.total_cleared || 0) + " 条记录。"
                        + (student.name || "小朋友") + "从今天重新开始啦。");
                    return shellApi.loadStudents();
                });
        })
        .then(function (list) {
            if (Array.isArray(list)) students = list;
        })
        .catch(function () {
            setResetNotice("刚刚没成功，数据没有动，再试一次吧。");
        });
}

/* ---------------- 交互 ---------------- */

function toggleSetting(key) {
    var shellApi = shell();
    if (!shellApi) return;
    var current = shellApi.getSettings();
    var patch = {};
    patch[key] = !current[key];
    shellApi.setSettings(patch);
    renderAll(null, students);
}

function setFontScale(value) {
    var shellApi = shell();
    if (!shellApi) return;
    shellApi.setSettings({ fontScale: value });
    renderAll(null, students);
}

function wireSwitcher() {
    var shellApi = shell();
    var box = $("profile-card");
    if (shellApi && box && typeof shellApi.createStudentSwitcher === "function") {
        shellApi.createStudentSwitcher(box);
    }
}

function renderAll(current, list) {
    var shellApi = shell();
    var card = $("profile-card");
    if (card) {
        card.innerHTML = renderProfile(current || (shellApi ? findStudent(shellApi.getStudentId()) : null) || {},
            list || students);
    }
    var box = $("profile-settings");
    if (box) box.innerHTML = renderSettings(shellApi ? shellApi.getSettings() : null);
    wireSwitcher();
    renderData();
    var status = $("profile-status");
    if (status) status.textContent = "";
}

/* ---------------- 初始化 ---------------- */

function init() {
    var shellApi = shell();
    if (!shellApi) {
        renderAll(null, []);
        return;
    }
    shellApi.applySettings();
    shellApi.onStudentChange(function () {
        var cur = findStudent(shellApi.getStudentId());
        if (cur) shellApi.applyAgeMode(cur.grade);
        renderAll(cur, students);
    });
    shellApi.loadStudents().then(function (list) {
        students = Array.isArray(list) ? list : [];
        var cur = findStudent(shellApi.getStudentId()) || students[0] || null;
        if (cur) shellApi.applyAgeMode(cur.grade);
        renderAll(cur, students);
    });
}

// 页面对外入口（HTML 内联初始化与 frontend/verify_growth_profile_web.js 共用）
if (typeof window !== "undefined") {
    window.ProfilePage = {
        init: init,
        renderProfile: renderProfile,
        renderSettings: renderSettings,
        toggleSetting: toggleSetting,
        setFontScale: setFontScale,
        renderDataSection: renderDataSection,
        confirmReset: confirmReset,
        resetUser: resetUser
    };
}
