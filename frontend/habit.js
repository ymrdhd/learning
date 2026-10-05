// 能力契约｜学习习惯简报页：本月天数 / 连续天数 / 最长连续 / 完成率 / 徽章 / 休息保护
// 入口：init / loadProfile / renderNumbers / renderDays / renderBadges / loadRest / useRest
// 依赖：style.css；后端 /api/habit/profile/{student_id}、/api/habit/rest/{student_id}、POST /api/habit/rest
// 不负责：习惯数据计算（backend/habit.py）、连续天数规则与休息保护上限
// 验证：backend/verify_active_recall.py（habit_case 接口断言 + 页面静态检查）
// 被调用：habit.html
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

/* ---------------- 纯函数（方便直接单测） ---------------- */

/* 儿童版连续学习文案：本月学习 18 天 / 当前连续 5 天 / 最长连续 9 天 */
function streakText(profile) {
    const data = profile || {};
    return `本月学习 ${data.monthly_learning_days || 0} 天 · 当前连续 ${data.current_streak || 0} 天`
        + ` · 最长连续 ${data.longest_streak || 0} 天`;
}

/* 完成率 → 儿童能懂的话 */
function rateText(rate) {
    const value = Number(rate) || 0;
    if (value >= 0.9) return "每次都能完成";
    if (value >= 0.6) return "大部分能完成";
    if (value > 0) return "有时候没做完";
    return "还没有开始";
}

function numberCard(label, value, suffix) {
    return `<div class="habit-num"><strong>${esc(value)}${esc(suffix || "")}</strong>${esc(label)}</div>`;
}

let profile = null;

/* ---------------- 页面 ---------------- */

function init() {
    loadStudents().then(() => {
        loadProfile();
        loadRest();
    });
}

function loadStudents() {
    const select = $("student");
    return jsonFetch(`${API}/students`).then(list => {
        select.innerHTML = (list || []).map(item =>
            `<option value="${item.id}">${esc(item.name)}（${esc(item.grade_text || "")}）</option>`).join("");
        const saved = localStorage.getItem(STUDENT_KEY);
        if (saved && (list || []).some(item => String(item.id) === String(saved))) {
            select.value = saved;
        }
        select.addEventListener("change", () => {
            localStorage.setItem(STUDENT_KEY, select.value);
            loadProfile();
            loadRest();
        });
    }).catch(err => {
        console.error("[habit] 连接后端失败", err);
        $("habit-streak").textContent = "菲比现在连不上，请先双击 start.bat。";
    });
}

function loadProfile() {
    const sid = $("student").value;
    if (!sid) return;
    jsonFetch(`${API}/api/habit/profile/${sid}`).then(data => {
        profile = data;
        $("habit-streak").textContent = streakText(data);
        const levelText = data.level_text ? ` · ${data.level_text}` : "";
        $("habit-level").textContent = `学习等级 ${data.level || 1}${levelText} · 完成情况：${rateText(data.completion_rate)}`;
        renderNumbers(data);
        renderDays(data.recent || []);
        renderBadges(data.badges || []);
    }).catch(err => {
        console.error("[habit] 学习记录读取失败", err);
        $("habit-streak").textContent = "菲比刚刚没拿到学习记录，我们再试一次。";
    });
}

function renderNumbers(data) {
    $("habit-numbers").innerHTML =
        numberCard("本月学习", data.monthly_learning_days || 0, " 天")
        + numberCard("当前连续", data.current_streak || 0, " 天")
        + numberCard("最长连续", data.longest_streak || 0, " 天")
        + numberCard("累计学习", data.total_days || 0, " 天")
        + numberCard("累计时长", data.total_minutes || 0, " 分钟")
        + numberCard("平均每天", data.average_daily_minutes || 0, " 分钟")
        + numberCard("完成率", Math.round((Number(data.completion_rate) || 0) * 100), "%")
        + numberCard("常在这个时间学", data.preferred_learning_time || "还没记录", "");
}

function renderDays(recent) {
    $("habit-days").innerHTML = (recent || []).map(item => {
        const done = Number(item.done) || 0;
        const total = Number(item.total) || 0;
        const icon = total === 0 ? "🌙" : (done >= total ? "✅" : "🕐");
        return `<div class="task-item${done >= total && total > 0 ? " done" : ""}">`
            + `<span class="task-item-title">${icon} ${esc(item.date)}</span>`
            + `<span class="task-item-meta">完成 ${done}/${total} · ${esc(item.minutes || 0)} 分钟</span></div>`;
    }).join("");
}

function renderBadges(badges) {
    $("habit-badges").innerHTML = (badges || []).map(item =>
        `<span class="habit-badge${item.got ? " habit-got" : ""}">${esc(item.icon)} ${esc(item.name)}`
        + `${item.got ? "" : "（还没得到）"}</span>`).join("");
}

function loadRest() {
    const sid = $("student").value;
    if (!sid) return;
    jsonFetch(`${API}/api/habit/rest/${sid}`).then(data => {
        $("habit-rest-text").textContent =
            `本月还可以休息 ${data.rest_protection_left} 次（已用 ${data.rest_protection_count} 次，`
            + `每月上限 ${data.rest_protection_limit} 次，不使用也可以继续学习）`;
    }).catch(() => { /* 休息状态失败不影响主数据 */ });
}

function useRest() {
    const sid = $("student").value;
    if (!sid) return;
    const now = new Date();
    const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    postJson(`${API}/api/habit/rest`, { student_id: Number(sid), date: day }).then(data => {
        $("habit-rest-result").textContent = data.ok
            ? `🌙 ${data.reason || "今天休息一下，连续学习不会断"}`
            : `🙂 ${data.reason || "暂时无法使用休息保护"}`;
        loadRest();
        loadProfile();
    }).catch(err => {
        console.error("[habit] 休息保护失败", err);
        $("habit-rest-result").textContent = "菲比刚刚没处理好，我们再试一次。";
    });
}

if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", init);
}
