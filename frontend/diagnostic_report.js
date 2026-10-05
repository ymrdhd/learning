// ==============================================================
// 能力契约｜诊断报告页：能力阶段、星级、知识点掌握、历史记录
// 入口：init / loadReport / loadStudents / renderReport / renderKnowledge / renderHistory / barWidth
// 依赖：无（零构建）
// 不负责：诊断计算 → backend/diagnostic_routes.py report
// 验证：node frontend/verify_diagnostic_web.js
// 被调用：diagnostic_report.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 能力报告页（V2.0）：能力画像 + 知识点细分 + 优势 / 需要提升 / 建议。 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

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

function query(name) {
    try {
        return new URLSearchParams(location.search).get(name) || "";
    } catch (err) {
        return "";
    }
}

function currentStudentId() {
    return parseInt($("student").value || "1", 10);
}

/* 知识点条形的宽度（纯函数，方便单测） */
function barWidth(score) {
    const value = Number(score) || 0;
    return Math.max(0, Math.min(100, Math.round(value)));
}

function masteryClass(score) {
    if (score >= 80) return "good";
    if (score >= 60) return "mid";
    return "low";
}

function renderKnowledge(items) {
    if (!items || !items.length) {
        return `<p class="meta">还没有知识点数据，先做一次诊断吧～</p>`;
    }

    return `<div class="knowledge-list">` + items.map(item => `
        <div class="knowledge-row">
            <span class="knowledge-name">${esc(item.knowledge)}</span>
            <span class="knowledge-bar"><i class="${masteryClass(item.mastery_score)}"
                style="width:${barWidth(item.mastery_score)}%"></i></span>
            <span class="knowledge-score">${esc(item.mastery_score)}</span>
            <span class="meta">${esc(item.correct)}/${esc(item.questions)} 题</span>
        </div>
    `).join("") + `</div>`;
}

function renderHistory(history) {
    if (!history || !history.length) return "";

    return `
        <p class="diag-title">测试过程</p>
        <div class="history-list">${history.map(item => `
            <div class="history-row">
                <span>${esc(item.label || item.stage)}（${esc(item.stage)}）</span>
                <span>${esc(item.correct)}/${esc(item.count)} 题</span>
                <span>正确率 ${Math.round((item.rate || 0) * 100)}%</span>
                <span class="meta">${esc(item.verdict_text || "")}</span>
            </div>
        `).join("")}</div>
    `;
}

function renderReport(data) {
    if (!data.available) {
        $("report").innerHTML = `
            <p class="diag-intro">${esc(data.message || "还没有能力数据")}</p>
            <p><a href="diagnostic.html">🧪 现在去做能力诊断</a></p>
        `;
        return;
    }

    const strengths = (data.strengths || []).map(item =>
        `<li>${esc(item.knowledge)} · 掌握度 ${esc(item.mastery_score)}</li>`).join("") ||
        "<li>继续加油，马上就有啦～</li>";
    const weaknesses = (data.weaknesses || []).map(item =>
        `<li>${esc(item.knowledge)} · 掌握度 ${esc(item.mastery_score)}</li>`).join("") ||
        "<li>暂时没有明显短板，很棒！</li>";
    const advice = (data.advice || []).map(text => `<li>${esc(text)}</li>`).join("");

    $("report").innerHTML = `
        <div class="report-head">
            <p class="report-subject">${esc(data.subject)}</p>
            <p class="report-stars">${esc(data.star_text)}</p>
            <p class="report-stage">${esc(data.stage_label)}（${esc(data.stage)}）</p>
            <p class="meta">能力区间：${esc(data.range_label)} 阶段 · 能力分 ${esc(data.score)}
                · 置信度 ${esc(data.confidence)}</p>
            <p class="meta">共测 ${esc(data.ability ? data.ability.questions : 0)} 题，
                答对 ${esc(data.ability ? data.ability.correct : 0)} 题</p>
        </div>

        <p class="diag-title">知识点掌握情况</p>
        ${renderKnowledge(data.knowledge)}

        <div class="two-col">
            <div class="col">
                <p class="diag-title">💪 优势</p>
                <ul class="advice-list">${strengths}</ul>
            </div>
            <div class="col">
                <p class="diag-title">🎯 需要提升</p>
                <ul class="advice-list">${weaknesses}</ul>
            </div>
        </div>

        <p class="diag-title">📅 学习建议</p>
        <ul class="advice-list">${advice}</ul>

        ${renderHistory(data.history)}
    `;
}

function loadReport() {
    $("report").innerHTML = "⏳ 正在生成能力报告...";

    const params = new URLSearchParams({
        student_id: currentStudentId(),
        subject: $("subject").value
    });

    jsonFetch(API + "/api/diagnostic/report?" + params.toString())
        .then(renderReport)
        .catch(err => {
            console.error("[diagnostic_report] 报告读取失败", err);
            $("report").innerHTML = `<p class="diag-intro">菲比刚刚没拿到报告，我们再试一次。</p>`;
        });
}

function loadStudents() {
    return jsonFetch(API + "/students")
        .then(list => {
            $("student").innerHTML = (list || []).map(s =>
                `<option value="${s.id}">${esc(s.name)}（${esc(s.grade_text)}）</option>`
            ).join("");

            const want = parseInt(query("student_id") || "0", 10);
            if (want) $("student").value = String(want);

            const subject = query("subject");
            if (subject) $("subject").value = subject;
        })
        .catch(err => {
            console.error("[diagnostic_report] 连接后端失败", err);
            $("report").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;
        });
}

function onStudentChange() {
    loadReport();
}

function init() {
    loadStudents().then(loadReport);
}

init();
