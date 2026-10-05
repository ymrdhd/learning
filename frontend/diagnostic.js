// ==============================================================
// 能力契约｜能力诊断入口页：选学生与科目、开始诊断、历史画像列表
// 入口：init / loadStudents / loadProfiles / selectSubject / startDiagnostic
// 依赖：无（零构建）
// 不负责：答题流程 → diagnostic_test.js；报告 → diagnostic_report.js
// 验证：node frontend/verify_diagnostic_web.js
// 被调用：diagnostic.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 能力诊断入口页（V2.0）：
   选学生 + 选科目 → 开始诊断 → 跳到诊断过程页。 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

const SESSION_KEY = "xiaozhi.diagSession";
const SUBJECTS = ["数学", "语文", "英语"];

let selectedSubject = "数学";
let students = [];

function $(id) {
    return document.getElementById(id);
}

function esc(text) {
    return String(text == null ? "" : text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function jsonFetch(url, options) {
    return fetch(url, options).then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    });
}

function currentStudentId() {
    return parseInt($("student").value || "1", 10);
}

/* 把一张画像渲染成一行小卡片 */
function profileLine(profile) {
    return `<div class="profile-item">
        <span class="profile-subject">${esc(profile.subject)}</span>
        <span class="profile-stage">${esc(profile.stage_label)}（${esc(profile.stage)}）</span>
        <span class="profile-stars">${esc(profile.star_text)}</span>
        <span class="meta">能力分 ${esc(profile.score)} · 置信度 ${esc(profile.confidence)}</span>
    </div>`;
}

function renderProfiles(list) {
    if (!list.length) {
        $("profile-box").innerHTML = `<p class="diag-title">还没有做过能力诊断</p>`;
        $("profile-box").classList.remove("hidden");
        return;
    }

    $("profile-box").innerHTML =
        `<p class="diag-title">当前能力画像</p>` + list.map(profileLine).join("");
    $("profile-box").classList.remove("hidden");
}

function loadProfiles() {
    return jsonFetch(API + "/api/diagnostic/profiles?student_id=" + currentStudentId())
        .then(data => {
            renderProfiles(data.profiles || []);
            return data;
        })
        .catch(err => {
            $("profile-box").innerHTML =
                `<p class="meta">⚠️ 读取能力画像失败：${esc(err.message)}（请先启动后端 start.bat）</p>`;
            $("profile-box").classList.remove("hidden");
        });
}

function loadStudents() {
    return jsonFetch(API + "/students")
        .then(list => {
            students = list || [];
            $("student").innerHTML = students.map(s =>
                `<option value="${s.id}">${esc(s.name)}（${esc(s.grade_text)}）</option>`
            ).join("");
            $("start-btn").disabled = false;
            $("hint").textContent = "";
        })
        .catch(err => {
            console.error("[diagnostic] 连接后端失败", err);
            $("hint").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;
        });
}

function onStudentChange() {
    loadProfiles();
}

function selectSubject(subject) {
    selectedSubject = subject;
    document.querySelectorAll(".subject-card").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.subject === subject);
    });
}

function startDiagnostic() {
    $("start-btn").disabled = true;
    $("hint").textContent = "正在准备题目...";

    jsonFetch(API + "/api/diagnostic/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: currentStudentId(), subject: selectedSubject })
    })
        .then(data => {
            try {
                sessionStorage.setItem(SESSION_KEY, String(data.session_id));
                sessionStorage.setItem(SESSION_KEY + ".subject", selectedSubject);
            } catch (err) {
                // 隐私模式下 sessionStorage 不可用，改用 URL 传参
            }
            location.href = "diagnostic_test.html?session_id=" + encodeURIComponent(data.session_id)
                + "&subject=" + encodeURIComponent(selectedSubject);
        })
        .catch(err => {
            $("start-btn").disabled = false;
            console.error("[diagnostic] 开始诊断失败", err);
            $("hint").innerHTML = `<p class="diag-intro">菲比刚刚没能开始，我们再试一次。</p>`;
        });
}

function init() {
    $("report-link").href = "diagnostic_report.html";
    selectSubject("数学");
    loadStudents().then(loadProfiles);
}

init();
