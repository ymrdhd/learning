// ==============================================================
// 能力契约｜学习建议页：复习 / 练习 / 巩固建议 + 错因提醒 + 已掌握列表
// 入口：init / loadAdvice / renderAdvice / renderWeak / renderErrors / renderMastered / renderFooter
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js（须先于业务 js 加载）
// 不负责：掌握度计算 → backend/mastery.py + knowledge_routes.py
// 验证：node frontend/verify_knowledge_web.js
// 被调用：study_advice.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 学习建议页（V2.3）：今天的建议 + 需要提升 + 错因提示 + 已经掌握。
   接口：GET /students、GET /api/report/knowledge?student_id=1&subject=数学 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

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

/* 共享 UI 层：script 顺序保证已加载；万一没加载，降级成朴素 HTML */
function uc() {
    return (typeof window !== "undefined" && window.UIComponents) || null;
}

function kidLang() {
    return (typeof window !== "undefined" && window.KidLang) || null;
}

/* 掌握度 → 儿童状态标签（文字 + 图标，不靠颜色单独表达） */
function statusBadge(mastery) {
    const c = uc();
    return c ? c.knowledgeStatus({ mastery: mastery })
        : `<span class="ph-status">${esc(kidLang() ? kidLang().statusLabel(mastery) : "")}</span>`;
}

function statusDot(mastery) {
    const c = uc();
    return c ? c.knowledgeStatus({ mastery: mastery, compact: true })
        : `<span class="ph-status-dot">${esc(kidLang() ? kidLang().statusLabel(mastery) : "")}</span>`;
}

/* 把文案里的「掌握度 45」换成孩子看得懂的「🌿 正在学习」 */
function kidText(text) {
    const lang = kidLang();
    const raw = String(text == null ? "" : text);
    if (!lang) return raw;
    return raw.replace(/掌握度\s*(\d+(?:\.\d+)?)/g, function (all, num) {
        return lang.statusLabel(Number(num));
    });
}

function loadingOf(text) {
    const c = uc();
    return c ? c.loadingState({ text: text })
        : `<p class="diag-intro">${esc(text)}</p>`;
}

function errorOf(title, hint) {
    const c = uc();
    if (c) return c.errorState({ title: title, hint: hint, retryLabel: "再试一次", retryAction: "loadAdvice()" });
    return `<p class="diag-intro">${esc(title)}</p>`;
}

/* 进度条宽度：分数裁剪到 0~100（纯函数，方便单测） */
function barWidth(score) {
    const value = Number(score);
    if (!isFinite(value)) return 0;
    return Math.max(0, Math.min(100, Math.round(value)));
}

/* 掌握度配色：>=80 好、>=60 中、否则偏低（纯函数） */
function masteryClass(score) {
    const value = Number(score) || 0;
    if (value >= 80) return "good";
    if (value >= 60) return "mid";
    return "low";
}

/* 星级换算：每 20 分一颗星，最多 5 颗（纯函数） */
function starCount(score) {
    const value = Number(score);
    if (!isFinite(value) || value <= 0) return 0;
    return Math.max(1, Math.min(5, Math.round(value / 20)));
}

function starText(score) {
    const count = starCount(score);
    return "★".repeat(count) + "☆".repeat(5 - count);
}

/* 正确率百分比：分母为 0 返回 0，超过 100% 截断（纯函数） */
function percent(part, total) {
    const all = Number(total) || 0;
    if (all <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((Number(part) || 0) / all * 100)));
}

function currentStudentId() {
    return parseInt($("student").value || "1", 10);
}

/* 今天建议：逐条编号，按接口给出的顺序展示 */
function renderAdvice(advice) {
    const list = advice || [];
    if (!list.length) {
        return `<p class="meta">今天还没有新建议，先做几道题就会有啦～</p>`;
    }
    return `<ul class="advice-list">` + list.map((text, index) =>
        `<li>${index + 1}. ${esc(kidText(text))}</li>`).join("") + `</ul>`;
}

/* 需要提升的知识点：掌握度 + 正确/总题数 */
function renderWeak(items) {
    const list = items || [];
    if (!list.length) {
        return `<p class="meta">暂时没有特别薄弱的知识点，很棒！</p>`;
    }
    return `<div class="knowledge-list">` + list.map(item => `
        <div class="knowledge-row km-row">
            <span class="knowledge-name">${esc(item.knowledge)}</span>
            <span class="knowledge-bar"><i class="${masteryClass(item.mastery_score)}"
                style="width:${barWidth(item.mastery_score)}%"></i></span>
            <span class="knowledge-score">${esc(barWidth(item.mastery_score))}</span>
            <span class="meta">${esc(item.correct_questions || 0)}/${esc(item.total_questions || 0)} 题</span>
            <span class="badge ${levelClass(item.level)}">${esc(item.level || "待提升")}</span>
        </div>
    `).join("") + `</div>`;
}

/* 掌握等级 → 徽标配色（纯函数） */
function levelClass(level) {
    if (level === "熟练") return "lv-good";
    if (level === "初步掌握") return "lv-ok";
    if (level === "巩固中") return "lv-mid";
    if (level === "薄弱") return "lv-low";
    return "lv-none";
}

/* 错因提示：审题错误 3 次 …… */
function renderErrors(errorSummary) {
    const list = errorSummary || [];
    if (!list.length) {
        return `<p class="diag-intro">还没有错题记录，继续保持！</p>`;
    }
    return `<ul class="advice-list">` + list.map(item =>
        `<li>${esc(item.error_type || "其他")} ${esc(item.count || 0)} 次</li>`).join("") + `</ul>`;
}

/* 已经掌握：给点正向鼓励 */
function renderMastered(items) {
    const list = items || [];
    if (!list.length) {
        return `<p class="meta">再练一练，很快就有掌握的知识点啦～</p>`;
    }
    return `<ul class="advice-list">` + list.map(item =>
        `<li><span class="ph-li-name">🎉 ${esc(item.knowledge)}</span> ${statusDot(item.mastery_score)}（答对 ${esc(item.correct_questions || 0)} 题）</li>`
    ).join("") + `</ul>`;
}

function renderFooter(data) {
    const info = data || {};
    const average = info.average_mastery == null ? 0 : info.average_mastery;
    return `<div class="report-head">
        <p class="report-stars">${esc(info.star_text || starText(average))}</p>
        <p class="report-stage">${statusBadge(average)}<span class="meta">整体状态</span></p>
        <p class="meta link-row">
            <a href="knowledge_map.html">🗺 我的成长</a>
            <a href="wrong_book.html">⚔️ 我的挑战</a>
        </p>
    </div>`;
}

function renderReport(data) {
    const info = data || {};

    if (!info.available) {
        $("advice").innerHTML = `
            <p class="diag-intro">${esc(info.message || "这位同学还没有学习数据～")}</p>
            <p><a href="diagnostic.html">🧪 去做能力诊断</a></p>
        `;
        $("weak").innerHTML = "";
        $("errors").innerHTML = "";
        $("mastered").innerHTML = "";
        $("footer").innerHTML = "";
        return;
    }

    $("advice").innerHTML = `<p class="diag-title">📅 今天建议</p>` + renderAdvice(info.advice);
    $("weak").innerHTML = `<p class="diag-title">🎯 需要提升的知识点</p>` + renderWeak(info.weak);
    $("errors").innerHTML = `<p class="diag-title">🔍 错因提示</p>` + renderErrors(info.error_summary);
    $("mastered").innerHTML = `<p class="diag-title">💪 已经掌握</p>` + renderMastered(info.mastered);
    $("footer").innerHTML = renderFooter(info);
}

function loadAdvice() {
    if (!$("student").value) return Promise.resolve();

    $("advice").innerHTML = loadingOf("菲比正在整理今天的小建议……");
    $("hint").textContent = "";

    const params = new URLSearchParams({
        student_id: currentStudentId(),
        subject: selectedSubject,
    });

    return jsonFetch(API + "/api/report/knowledge?" + params.toString())
        .then(renderReport)
        .catch(err => {
            console.error("[study_advice] 学习建议读取失败", err);
            $("advice").innerHTML = errorOf("菲比刚刚没拿到学习建议，我们再试一次。");
        });
}

function loadStudents() {
    return jsonFetch(API + "/students")
        .then(list => {
            students = list || [];
            $("student").innerHTML = students.map(s =>
                `<option value="${s.id}">${esc(s.name)}（${esc(s.grade_text)}）</option>`
            ).join("");
        })
        .catch(err => {
            console.error("[study_advice] 连接后端失败", err);
            $("hint").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;
        });
}

function onStudentChange() {
    loadAdvice();
}

function selectSubject(subject) {
    selectedSubject = subject;
    document.querySelectorAll(".subject-card").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.subject === subject);
    });
    if (students.length) loadAdvice();
}

function init() {
    selectSubject("数学");
    loadStudents().then(loadAdvice);
}

init();
