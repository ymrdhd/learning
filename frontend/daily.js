// 能力契约｜今日完成页：完成情况与明确结束点（🎉 文案 + 儿童版反馈 + 今天可以休息啦）
// 入口：init / loadDaily / startDay / renderTasks / completeTask / toggleStudentPicker / completionHtml
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js；后端 /api/daily-summary/{student_id}、/api/tasks/start、/api/tasks/{task_id}/complete
// 不负责：任务生成（backend/habit.py）、完成度统计口径（backend/daily_routes.py）
// 验证：backend/verify_active_recall.py（daily_case 接口断言 + 页面静态检查）
// 被调用：daily.html
// 索引：docs/MODULE_MAP.md · SPEC.md §8

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin : "http://127.0.0.1:8000";
const STUDENT_KEY = "xiaozhi.student";

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

function postJson(url, payload) {
    return jsonFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
}

/* ---------------- 共享 UI 层（零构建，缺失时降级） ---------------- */

function uc() {
    if (typeof window !== "undefined" && window.UIComponents) return window.UIComponents;
    return (typeof UIComponents !== "undefined") ? UIComponents : null;
}

function kidLang() {
    if (typeof window !== "undefined" && window.KidLang) return window.KidLang;
    return (typeof KidLang !== "undefined") ? KidLang : null;
}

/* 把后端的算法口径（掌握度 / 遗忘风险 / 稳定性）换成儿童看得懂的话 */
function kidText(text) {
    const lang = kidLang();
    const raw = String(text == null ? "" : text);
    if (!lang) return raw;
    return raw
        .replace(/掌握度\s*(\d+(?:\.\d+)?)/g, (m, n) => lang.statusLabel(parseFloat(n)))
        .replace(/遗忘风险\s*\d+(?:\.\d+)?%?/g, "需要再照顾一下")
        .replace(/稳定性\s*\d+(?:\.\d+)?/g, "记得越来越牢");
}

function loadingHtml(text) {
    const c = uc();
    const tip = text || "菲比正在准备一道适合你的题……";
    return c ? c.loadingState({ text: tip }) : `<p class="meta">${esc(tip)}</p>`;
}

function errorHtml(title, handlerName) {
    const c = uc();
    if (c) return c.errorState({ title: title, retryAction: handlerName + "()" });
    return `<p class="meta">${esc(title)}</p>`
        + `<button type="button" class="ph-btn ph-btn--primary" onclick="${esc(handlerName)}()">再试一次</button>`;
}

/* ---------------- 纯函数（方便直接单测） ---------------- */

/* 儿童版反馈行：🌱 学会1个新知识 / 🌿 补强2个薄弱点 … */
function childLine(icon, count, unit) {
    const value = Number(count) || 0;
    if (value <= 0) return "";
    return `${icon} ${unit} ${value} 个`;
}

/* 任务类型 → 儿童图标（与 daily_routes.TASK_ICON 一致） */
function taskIcon(taskType) {
    const table = {
        new_learning: "🌱",
        weakness: "🌿",
        review: "🌳",
        wrong_recovery: "⚔️",
        active_recall: "🧠"
    };
    return table[taskType] || "✅";
}

let summary = null;
let students = [];

/* ---------------- 顶部区与学习者切换 ---------------- */

function currentStudentItem() {
    const sid = $("student").value;
    return students.filter(item => String(item.id) === String(sid))[0] || null;
}

function updateWho() {
    const me = currentStudentItem();
    if (!me) return;
    const name = $("who-name");
    const grade = $("who-grade");
    if (name) name.textContent = me.name || "小朋友";
    if (grade) grade.textContent = me.grade_text || "";
}

function renderStudentPicker() {
    const box = $("student-picker");
    if (!box) return;
    box.innerHTML = students.map(item =>
        `<button type="button" class="ph-student" data-student-id="${esc(item.id)}"`
        + ` data-student-name="${esc(item.name)}">`
        + `<span>${esc(item.name)}</span>`
        + `<span class="ph-grade">${esc(item.grade_text || "")}</span></button>`).join("");
    if (typeof window !== "undefined" && window.UIShell) window.UIShell.createStudentSwitcher(box);
}

function toggleStudentPicker() {
    const box = $("student-picker");
    if (!box) return;
    const hidden = box.classList.toggle("hidden");
    const btn = $("switch-student");
    if (btn) btn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function bindStudentChange() {
    if (typeof window === "undefined" || !window.UIShell) return;
    window.UIShell.onStudentChange(id => {
        $("student").value = String(id);
        updateWho();
        loadDaily();
    });
}

/* ---------------- 成长反馈（主指标：学会了什么） ---------------- */

function completionHtml(data) {
    const c = uc();
    const items = data.lines || [];
    const card = c
        ? c.completionCard({ title: "", restLabel: "", items: items, primaryLabel: "查看我的成长" })
        : `<div class="ph-complete"><ul class="ph-complete-list">`
            + items.map(line => `<li>${esc(line)}</li>`).join("")
            + `</ul></div>`;
    return `<p class="ph-complete-lead">今天你：</p>` + card
        + `<p class="ph-complete-actions"><a class="ph-btn ph-btn--secondary" href="today.html">返回首页</a></p>`;
}

function wireCompletion() {
    const box = $("daily-child");
    if (!box) return;
    const btn = box.querySelector('[data-action="growth"]');
    if (btn) btn.onclick = () => { location.href = "growth.html"; };
}

/* ---------------- 页面 ---------------- */

function init() {
    bindStudentChange();
    loadStudents().then(loadDaily);
}

function loadStudents() {
    const select = $("student");
    return jsonFetch(`${API}/students`).then(list => {
        select.innerHTML = (list || []).map(item =>
            `<option value="${item.id}">${esc(item.name)}（${esc(item.grade_text || "")}）</option>`).join("");
        students = list || [];
        const saved = (typeof window !== "undefined" && window.UIShell && window.UIShell.getStudentId())
            || localStorage.getItem(STUDENT_KEY);
        if (saved && (list || []).some(item => String(item.id) === String(saved))) {
            select.value = saved;
        }
        updateWho();
        renderStudentPicker();
        select.addEventListener("change", () => {
            localStorage.setItem(STUDENT_KEY, select.value);
            loadDaily();
        });
    }).catch(err => {
        console.error("[daily] 加载学生失败", err);
        $("daily-message").innerHTML = errorHtml("菲比现在连不上服务器，我们等一会儿再试。", "init");
        $("daily-rest").textContent = "";
    });
}

function loadDaily() {
    const sid = $("student").value;
    if (!sid) return;
    jsonFetch(`${API}/api/daily-summary/${sid}`).then(data => {
        summary = data;
        const title = $("daily-title");
        if (title) title.textContent = data.finished ? "🎉 今天完成啦" : "今天还没完成哦";
        $("daily-message").textContent = data.finished ? "" : (data.message || "");
        $("daily-rest").textContent = data.rest_text || "";
        $("daily-child").innerHTML = data.finished ? completionHtml(data) : "";
        wireCompletion();
        const tasks = data.tasks || [];
        $("daily-progress").textContent = tasks.length
            ? `已完成 ${(data.debug && data.debug.task_summary && data.debug.task_summary.done) || 0} / ${tasks.length} 个任务`
            : "今天还没有任务，点「开始今天的学习」让菲比安排吧～";
        renderTasks(tasks);
        $("daily-goal").textContent = kidText((data.goal && data.goal.text) || "还没有生成目标～");
        const debugBox = $("daily-debug");
        if (debugBox) debugBox.textContent = JSON.stringify(data.debug || {}, null, 0);
    }).catch(err => {
        console.error("[daily] 读取今天情况失败", err);
        $("daily-child").innerHTML = "";
        $("daily-message").innerHTML = errorHtml("菲比刚刚没拿到今天的情况，我们再试一次。", "loadDaily");
    });
}

function renderTasks(tasks) {
    $("daily-tasks").innerHTML = (tasks || []).map(task => {
        const done = task.status === "done";
        const button = done
            ? `<span class="task-done-badge">已完成</span>`
            : `<button class="task-complete-btn" onclick="completeTask(${esc(task.task_id)})">完成了</button>`;
        return `<div class="task-item${done ? " done" : ""}">`
            + `<span class="task-item-title">${esc(taskIcon(task.task_type))} ${esc(task.title)}`
            + ` · ${esc(task.knowledge || "")}</span>`
            + `<span class="task-item-meta">${esc(task.target_minutes || 0)} 分钟 · `
            + `${esc(task.status_text || "")}</span>${button}</div>`;
    }).join("");
}

function startDay() {
    const sid = $("student").value;
    if (!sid) return;
    $("daily-message").innerHTML = loadingHtml("菲比正在准备今天的任务……");
    postJson(`${API}/api/tasks/start`, { student_id: Number(sid) })
        .then(data => {
            $("daily-message").textContent = data.message || "今天的学习开始啦！";
            loadDaily();
        })
        .catch(err => {
            console.error("[daily] 开始失败", err);
            $("daily-message").innerHTML = errorHtml("菲比刚刚没准备好，我们再试一次。", "startDay");
        });
}

function completeTask(taskId) {
    const sid = $("student").value;
    if (!sid) return;
    const task = ((summary && summary.tasks) || []).filter(item => item.task_id === taskId)[0] || {};
    postJson(`${API}/api/tasks/${taskId}/complete`, {
        student_id: Number(sid),
        minutes: Number(task.target_minutes || 0),
        count: Number(task.target_count || 0),
        done: true
    }).then(loadDaily).catch(err => {
        console.error("[daily] 完成任务失败", err);
        $("daily-message").innerHTML = errorHtml("菲比刚刚没记下这一项，再试一次吧。", "loadDaily");
    });
}

if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", init);
}
