// ==============================================================
// 能力契约｜页面：我的成长（回答「我最近变强了吗」）
// 入口：init / renderSummary / renderMap / renderCalendar / loadGrowth / toggleStudentPicker
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js；
//       GET /students、GET /api/habit/stats、GET /api/habit/calendar、GET /api/mastery/{sid}、GET /api/recovery/list/{sid}
// 不负责：成长口径计算（backend/habit.py）、掌握度计算（backend/mastery.py）
// 验证：node frontend/verify_growth_profile_web.js
// 被调用：growth.html
// 索引：docs/MODULE_MAP.md · SPEC.md §8
// ==============================================================

// 成长页只回答一个问题：「我最近变强了吗？」
// 所以这里只显示 学会 / 记牢 / 攻克 这类成长，不显示做题总量，也不显示裸算法数字。

var STUDENT_KEY = "xiaozhi.student";
var API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin : "http://127.0.0.1:8000";

var students = [];

function $(id) { return document.getElementById(id); }
function uc() { return (typeof UIComponents !== "undefined") ? UIComponents : null; }
function shell() { return (typeof UIShell !== "undefined") ? UIShell : null; }

function esc(text) {
    return String(text === undefined || text === null ? "" : text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function jsonFetch(url) {
    return fetch(url).then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
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

/* ---------------- 知识地图的区域图标 ---------------- */

// 后端唯一的领域名来自 backend/knowledge_tree.py 的 domains_for：
// 数学 计算/数与代数/图形与几何/应用题/统计与概率，语文与英语另有各自领域。
// 这里只做「区域图标」的视觉映射，不改任何领域定义。
var DOMAIN_ICONS = {
    "计算": "🏡", "数与代数": "🏡", "图形与几何": "🏰", "应用题": "⛰", "统计与概率": "📊",
    "拼音": "🔤", "汉字": "📖", "阅读": "📚", "古诗": "🏮", "写作": "✏️",
    "字母": "🔠", "词汇": "🧩", "语法": "🧱", "口语": "🗣", "句型": "💬"
};

function domainIcon(name) {
    var key = String(name || "");
    if (Object.prototype.hasOwnProperty.call(DOMAIN_ICONS, key)) return DOMAIN_ICONS[key];
    for (var k in DOMAIN_ICONS) {
        if (Object.prototype.hasOwnProperty.call(DOMAIN_ICONS, k) && key.indexOf(k) >= 0) return DOMAIN_ICONS[k];
    }
    return "🌱";
}

function num(value) {
    var n = parseInt(value, 10);
    return isNaN(n) ? 0 : n;
}

/* ---------------- 渲染（纯函数，便于验证） ---------------- */

// data = { days, mastered, wrongFixed, learning } 或 { empty: true }
function renderSummary(data) {
    data = data || {};
    var c = uc();
    if (data.empty) {
        var emptyText = "还没有成长记录，完成今天的小任务就会看到啦。";
        return c ? c.emptyState({ icon: "🌱", title: emptyText, hint: "先去「今天」看看要做什么吧。" })
            : '<p class="ph-lead">' + esc(emptyText) + '</p>';
    }
    var rows = [
        { icon: "📅", label: "本周学习", value: num(data.days), unit: "天" },
        { icon: "🌳", label: "已经掌握", value: num(data.mastered), unit: "个知识" },
        { icon: "⚔️", label: "攻克错题", value: num(data.wrongFixed), unit: "道" },
        { icon: "🌿", label: "还在变熟", value: num(data.learning), unit: "个知识" }
    ];
    if (c) return c.growthSummary({ rows: rows, title: "我最近变强了吗？" });
    return '<div class="ph-card ph-growth"><ul class="ph-growth-list">'
        + rows.map(function (r) {
            return '<li><span aria-hidden="true">' + esc(r.icon) + '</span>' + esc(r.label)
                + ' <b class="ph-num">' + esc(r.value) + '</b> ' + esc(r.unit) + '</li>';
        }).join("")
        + '</ul></div>';
}

// domains = GET /api/mastery/{sid} 的 domains（{domain, mastery_score, knowledge_count, ...}）
function renderMap(domains) {
    var c = uc();
    var list = (Array.isArray(domains) ? domains : []).map(function (d) {
        var name = String((d && (d.domain || d.name)) || "");
        var count = d && (d.knowledge_count !== undefined ? d.knowledge_count : d.count);
        return { key: name, name: name, icon: domainIcon(name), count: num(count) };
    }).filter(function (d) { return d.name !== ""; });

    if (!list.length) {
        var emptyText = "还没有可以探索的知识地图。";
        return c ? c.emptyState({ icon: "🗺", title: emptyText })
            : '<p class="ph-lead">' + esc(emptyText) + '</p>';
    }
    return c ? c.knowledgeMap({ domains: list })
        : '<div class="ph-map">' + list.map(function (d) {
            return '<span class="ph-tile">' + esc(d.icon) + ' ' + esc(d.name) + '</span>';
        }).join("") + '</div>';
}

/* ---------------- 学习日历（完成当天任务自动打卡） ---------------- */

var WEEK_TEXT = ["一", "二", "三", "四", "五", "六", "日"];

// data = GET /api/habit/calendar 的返回（items / first_weekday / checked_count / today）
function renderCalendar(data) {
    var info = data || {};
    var items = Array.isArray(info.items) ? info.items : [];
    if (!items.length) {
        return '<p class="ph-lead">这个月还没有记录，完成今天的小任务就会亮起来。</p>';
    }

    var head = WEEK_TEXT.map(function (text) {
        return '<span class="ph-cal-head">' + esc(text) + '</span>';
    }).join("");

    var pad = Math.max(0, Math.min(6, num(info.first_weekday)));
    var blanks = "";
    for (var i = 0; i < pad; i++) blanks += '<span class="ph-cal-cell is-blank"></span>';

    var cells = items.map(function (item) {
        var day = num(item && item.day);
        var checked = !!(item && item.checked);
        var cls = "ph-cal-cell" + (checked ? " is-checked" : "")
            + ((item && item.is_today) ? " is-today" : "")
            + ((item && item.is_future) ? " is-future" : "");
        var label = checked
            ? ("第 " + day + " 天，完成 " + num(item && item.done) + " 个小任务")
            : ("第 " + day + " 天，还没有完成");
        var body = checked ? '<span aria-hidden="true">☀️</span>'
            : '<span class="ph-cal-day">' + esc(day) + '</span>';
        return '<span class="' + cls + '" title="' + esc(label)
            + '" aria-label="' + esc(label) + '">' + body + '</span>';
    }).join("");

    return '<p class="ph-cal-summary">这个月已经打卡 <b class="ph-num">'
        + esc(num(info.checked_count)) + '</b> 天</p>'
        + '<div class="ph-cal-grid">' + head + blanks + cells + '</div>';
}

/* ---------------- 我是谁 ---------------- */

function findStudent(id) {
    var target = String(id === undefined || id === null ? "" : id);
    for (var i = 0; i < students.length; i++) {
        if (String(students[i].id) === target) return students[i];
    }
    return null;
}

function updateWho(student) {
    if (!student) return;
    var name = $("who-name");
    var grade = $("who-grade");
    if (name) name.textContent = student.name || "小朋友";
    if (grade) grade.textContent = student.grade_text || "";
    var shellApi = shell();
    if (shellApi) shellApi.applyAgeMode(student.grade);
}

function renderStudentPicker() {
    var box = $("student-picker");
    if (!box) return;
    var current = shell() ? shell().getStudentId() : "";
    box.innerHTML = students.map(function (s) {
        var active = String(s.id) === String(current);
        return '<button type="button" class="ph-student' + (active ? " is-active" : "") + '"'
            + ' data-student-id="' + esc(s.id) + '" data-student-name="' + esc(s.name || "") + '">'
            + esc(s.name || "小朋友")
            + '<span class="ph-student-grade">' + esc(s.grade_text || "") + '</span></button>';
    }).join("");
    var shellApi = shell();
    if (shellApi && typeof shellApi.createStudentSwitcher === "function") {
        shellApi.createStudentSwitcher(box);
    }
}

function toggleStudentPicker() {
    var box = $("student-picker");
    if (!box) return;
    box.classList.toggle("hidden");
}

/* ---------------- 拉数据 ---------------- */

function studentId() {
    var shellApi = shell();
    if (shellApi) return String(shellApi.getStudentId());
    try {
        var saved = localStorage.getItem(STUDENT_KEY);
        return (saved === null || saved === "") ? "1" : String(saved);
    } catch (err) {
        return "1";
    }
}

function loadGrowth() {
    var sid = studentId();
    var box = $("growth-summary");
    var mapBox = $("growth-map");
    var calBox = $("growth-calendar");
    var status = $("growth-status");
    if (box) box.innerHTML = loadingHtml("菲比正在整理你的成长……");
    if (mapBox) mapBox.innerHTML = "";
    if (calBox) calBox.innerHTML = "";
    if (status) status.textContent = "";

    return Promise.all([
        jsonFetch(API + "/api/habit/stats?student_id=" + encodeURIComponent(sid) + "&days=7").catch(function (err) {
            console.error("[growth] 读取学习天数失败", err);
            return null;
        }),
        jsonFetch(API + "/api/mastery/" + encodeURIComponent(sid)).catch(function (err) {
            console.error("[growth] 读取知识地图失败", err);
            return null;
        }),
        jsonFetch(API + "/api/recovery/list/" + encodeURIComponent(sid)).catch(function (err) {
            console.error("[growth] 读取错题进度失败", err);
            return null;
        }),
        jsonFetch(API + "/api/habit/calendar?student_id=" + encodeURIComponent(sid)).catch(function (err) {
            console.error("[growth] 读取学习日历失败", err);
            return null;
        })
    ]).then(function (results) {
        var habit = results[0];
        var mastery = results[1];
        var recovery = results[2];
        var calendar = results[3];

        var items = (habit && habit.items) || [];
        var days = items.filter(function (it) {
            return num(it.minutes) > 0 || num(it.done) > 0;
        }).length;
        var summary = (mastery && mastery.summary) || {};
        var stats = (recovery && recovery.stats) || {};

        // 从没学过才显示空状态；只要有一点点痕迹就显示真实成长。
        var hasAny = days > 0 || num(summary.practiced) > 0 || num(summary.mastered) > 0
            || num(stats.total) > 0;
        var data = hasAny ? {
            days: days,
            mastered: num(summary.mastered),
            wrongFixed: num(stats.mastered),
            learning: num(summary.learning)
        } : { empty: true };

        if (box) box.innerHTML = renderSummary(data);
        if (mapBox) mapBox.innerHTML = renderMap((mastery && mastery.domains) || []);
        if (calBox) calBox.innerHTML = renderCalendar(calendar);
        if (status) status.textContent = "";
        return data;
    }).catch(function (err) {
        console.error("[growth] 读取成长数据失败", err);
        if (box) box.innerHTML = errorHtml("菲比刚刚没拿到你的成长，我们再试一次。", "loadGrowth");
    });
}

/* ---------------- 初始化 ---------------- */

function init() {
    var shellApi = shell();
    if (shellApi) {
        shellApi.applySettings();
        shellApi.onStudentChange(function () {
            var cur = findStudent(shellApi.getStudentId());
            if (cur) updateWho(cur);
            renderStudentPicker();
            loadGrowth();
        });
    }
    if (!shellApi) {
        loadGrowth();
        return;
    }
    shellApi.loadStudents().then(function (list) {
        students = Array.isArray(list) ? list : [];
        var cur = findStudent(shellApi.getStudentId()) || students[0] || null;
        if (cur) {
            updateWho(cur);
            if (String(shellApi.getStudentId()) !== String(cur.id)) shellApi.setStudentId(cur.id);
        }
        renderStudentPicker();
        loadGrowth();
    });
}

// 页面对外入口（HTML 内联初始化与 frontend/verify_growth_profile_web.js 共用）
if (typeof window !== "undefined") {
    window.GrowthPage = {
        init: init,
        renderSummary: renderSummary,
        renderMap: renderMap,
        loadGrowth: loadGrowth,
        toggleStudentPicker: toggleStudentPicker,
        renderCalendar: renderCalendar
    };
}
