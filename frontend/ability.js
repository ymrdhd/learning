// ==============================================================
// 能力契约｜我的能力水平页：由每日训练 / 自由练习成绩自动推断的能力阶段（无需专门做诊断）
// 入口：init / loadAbility / onStudentChange / renderSubject / renderOverall / statusBadge / confidenceText
// 依赖：后端 GET /api/ability/auto/{student_id}（backend/ability_routes.py）；phoebe3d.js 可选（立牌陪伴）
// 不负责：能力推断算法 → backend/auto_ability.py；专门的能力诊断 → diagnostic*.html（保留但不进入主流程）
// 验证：node frontend/verify_ability_web.js
// 被调用：ability.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 我的能力水平（V2.5 训练数据自动诊断）。

   用户需求：不额外进行能力诊断，通过每日训练和自由练习的成绩
   系统自动诊断能力水平。所以本页只读 /api/ability/auto/{id}，
   展示"系统从练习记录里看出来的水平"和判断依据。 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

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

function currentStudentId() {
    return parseInt(($("student") && $("student").value) || "1", 10);
}

/* ---------------- 纯函数（方便单测） ---------------- */

function percentText(rate) {
    const value = Number(rate);
    if (!isFinite(value)) return "0%";
    return Math.round(Math.max(0, Math.min(1, value)) * 100) + "%";
}

function confidenceText(item) {
    const info = item || {};
    const value = Math.round((Number(info.confidence) || 0) * 100);
    return `可信度 ${esc(info.confidence_text || "低")}（${value}%）`;
}

function statusBadge(item) {
    const info = item || {};

    if (info.status === "unknown") return `<span class="badge lv-none">还没有数据</span>`;
    if (info.status === "warming") return `<span class="badge lv-mid">数据积累中</span>`;
    return `<span class="badge lv-good">可以判断了</span>`;
}

/* ---------------- 渲染 ---------------- */

function renderOverall(data) {
    const overall = (data || {}).overall || {};
    const total = Number((data || {}).total_answers) || 0;

    if (!overall.stage) {
        $("overall").innerHTML = "";
        return;
    }

    $("overall").innerHTML = `
        <div class="summary-box">
            <div class="summary-item">
                <span class="meta">综合水平</span>
                <span class="summary-num">${esc(overall.stage_label || overall.stage)}</span>
            </div>
            <div class="summary-item">
                <span class="meta">综合能力分</span>
                <span class="summary-num">${esc(overall.score)}</span>
            </div>
            <div class="summary-item">
                <span class="meta">累计练习题数</span>
                <span class="summary-num">${esc(total)}</span>
            </div>
        </div>`;
}

function renderSubject(item) {
    const info = item || {};

    if (info.status === "unknown") {
        return `
            <div class="wrong-item">
                <p class="wrong-question">${esc(info.subject)}：还没有练习记录</p>
                <p class="meta">先做几道这一科的题，系统就能看出你的水平。</p>
                <p class="meta">${esc(info.next_step || "")}</p>
            </div>`;
    }

    return `
        <div class="report-head">
            <p class="report-subject">${esc(info.subject)} ${statusBadge(info)}</p>
            <p class="report-stars">${esc(info.star_text)}</p>
            <p class="report-stage">${esc(info.stage_label)}（${esc(info.stage)}）</p>
            <p class="diag-line">能力分 <b>${esc(info.score)}</b>
                · 当前重点：<b>${esc(info.knowledge_focus)}</b></p>
            <p class="diag-line">练了 ${esc(info.answer_count)} 题 · 正确率
                ${percentText(info.correct_rate)} · ${confidenceText(info)}</p>
            <p class="memory-tip">🧠 系统为什么这么判断：${esc(info.reason)}</p>
            <p class="meta">下一步：${esc(info.next_step)}</p>
        </div>`;
}

function renderAbility(data) {
    const subjects = (data || {}).subjects || [];
    $("ability-list").innerHTML = subjects.map(renderSubject).join("");
}

/* ---------------- 流程 ---------------- */

function init() {
    jsonFetch(API + "/students")
        .then(list => {
            $("student").innerHTML = list.map(item =>
                `<option value="${item.id}">${esc(item.name)}（${esc(item.grade_text)}）</option>`
            ).join("");

            let saved = null;
            try {
                saved = localStorage.getItem(STUDENT_KEY);
            } catch (err) {
                saved = null;
            }
            if (saved && list.some(item => String(item.id) === String(saved))) {
                $("student").value = saved;
            }

            loadAbility();
        })
        .catch(err => {
            console.error("[ability] 连接后端失败", err);
            $("status").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;
        });
}

function onStudentChange() {
    try {
        localStorage.setItem(STUDENT_KEY, $("student").value);
    } catch (err) {
        // 隐私模式下不记忆选择，不影响使用
    }
    loadAbility();
}

function loadAbility() {
    $("status").textContent = "⏳ 正在根据练习记录判断水平...";

    jsonFetch(`${API}/api/ability/auto/${currentStudentId()}`)
        .then(data => {
            $("status").textContent = "";
            renderOverall(data);
            renderAbility(data);
        })
        .catch(err => {
            console.error("[ability] 能力水平读取失败", err);
            $("status").innerHTML = `<p class="diag-intro">菲比刚刚没拿到能力水平，我们再试一次。</p>`;
        });
}

if (typeof document !== "undefined") init();
