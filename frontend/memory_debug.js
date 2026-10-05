// ==============================================================
// 能力契约｜家长端记忆调试页：记忆状态表 / 队列 / 策略日志（只读诊断用）
// 入口：init / loadAll / renderTable / renderQueue / renderLogs / maturityCell / riskText
// 依赖：无（零构建）
// 不负责：复习状态写入 → backend/review/engine.py
// 验证：node frontend/verify_memory_web.js
// 被调用：memory_debug.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 记忆数据页（V2.4，家长 / 开发用）。

   这里才显示真实算法指标：掌握度、记忆强度、稳定性、个人难度、遗忘风险、
   下次复习时间、成熟度，以及每次改复习日期的原因。儿童端不显示这些。

   接口：
     GET /students
     GET /api/review/memory-map/{student_id}?subject=
     GET /api/review/today/{student_id}
     GET /api/review/strategy-log/{student_id}
     GET /api/review/stats/{student_id} */

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

function jsonFetch(url) {
    return fetch(url).then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    });
}

/* ---------------- 纯函数（可单测） ---------------- */

/* 遗忘风险 → 中文等级 + 颜色类名 */
function riskClass(risk) {
    const value = Number(risk) || 0;
    if (value >= 0.75) return "risk-high";
    if (value >= 0.45) return "risk-mid";
    return "risk-low";
}

function riskText(risk) {
    const value = Number(risk) || 0;
    if (value >= 0.75) return "高（快忘了）";
    if (value >= 0.45) return "中（该复习）";
    return "低（还记得）";
}

/* 间隔用"天"显示，不足 1 天显示小时 */
function intervalText(days) {
    const value = Number(days) || 0;
    if (value >= 1) return `${Math.round(value * 10) / 10} 天`;
    return `${Math.max(1, Math.round(value * 24))} 小时`;
}

function maturityCell(item) {
    const info = item || {};
    return `${esc(info.forest_icon || "")} ${esc(info.maturity_text || info.maturity_level || "")}
        <span class="meta">(${esc(info.maturity_level || "")})</span>`;
}

function renderStats(stats, map) {
    const info = stats || {};
    const summary = (map || {}).summary || {};
    const cards = [
        [info.due_count || 0, "今日复习"],
        [info.completed_count || 0, "已完成"],
        [info.high_risk_count || 0, "即将遗忘"],
        [info.long_term_count || 0, "长期掌握"],
        [summary.average_stability || 0, "平均稳定性(天)"],
        [summary.average_memory_strength || 0, "平均记忆强度"],
    ];

    return cards.map(card => `<div class="summary-item">
        <span class="summary-num">${esc(card[0])}</span>
        <span class="meta">${esc(card[1])}</span>
    </div>`).join("");
}

function renderTable(map) {
    const items = (map || {}).items || [];
    if (!items.length) {
        return `<p class="meta">还没有记忆数据：先做一次能力诊断或练几道题，系统就会开始跟踪记忆状态。</p>`;
    }

    const rows = items.map(item => `
        <div class="memory-row">
            <span class="memory-name">${esc(item.subject)} · ${esc(item.knowledge_id)}</span>
            <span class="badge">掌握度 ${esc(item.mastery_score)}</span>
            <span class="badge">记忆强度 ${esc(item.memory_strength)}</span>
            <span class="badge">稳定性 ${esc(intervalText(item.stability))}</span>
            <span class="badge">个人难度 ${esc(item.difficulty)}</span>
            <span class="badge ${riskClass(item.forgetting_risk)}">遗忘风险 ${esc(item.risk_percent)}%</span>
            <span class="badge">下次复习 ${esc(item.next_review_date || "—")}</span>
            <span class="badge">${maturityCell(item)}</span>
            <span class="meta">${esc(item.action_text || "")}
                ${item.needs_relearn ? "（需要重新学）" : ""}</span>
        </div>`).join("");

    return `<div class="memory-head">
            <span>知识点</span><span>掌握度</span><span>记忆强度</span><span>稳定性</span>
            <span>个人难度</span><span>遗忘风险</span><span>下次复习</span><span>成熟度</span>
            <span>状态</span>
        </div>${rows}`;
}

function renderQueue(today) {
    const items = (today || {}).items || [];
    if (!items.length) {
        return `<p class="meta">今天没有到期复习任务。</p>`;
    }

    return items.map(item => `<div class="history-row">
        <span class="badge">${esc(item.priority)}</span>
        <span>${esc(item.subject)} · ${esc(item.knowledge_id)}</span>
        <span>风险 ${esc(item.risk_percent)}%</span>
        <span>计划 ${esc(item.target_count)} 题</span>
        <span>已完成 ${esc(item.completed_count)} 题</span>
        <span>${esc(item.status)}</span>
        <span class="meta">${esc(item.queue_reason || "")}</span>
    </div>`).join("");
}

function renderLogs(logs) {
    const items = (logs || {}).logs || [];
    if (!items.length) {
        return `<p class="meta">还没有复习策略日志。</p>`;
    }

    return items.map(item => `<div class="history-row">
        <span class="badge">${esc(item.quality || item.source || "")}</span>
        <span>${esc(item.subject)} · ${esc(item.knowledge)}</span>
        <span>间隔 ${esc(item.old_interval)} → ${esc(item.new_interval)} 天</span>
        <span>稳定性 ${esc(item.old_stability)} → ${esc(item.new_stability)}</span>
        <span class="meta">${esc(item.created_time)}</span>
        <div class="why-reason">${esc(item.reason)}</div>
    </div>`).join("");
}

/* ---------------- 流程 ---------------- */

function currentStudentId() {
    return parseInt(($("student") && $("student").value) || "1", 10);
}

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

            loadAll();
        })
        .catch(err => {
            console.error("[memory_debug] 连接后端失败", err);
            $("status").innerHTML = `<p class="diag-intro">连不上后端，请先双击 start.bat。</p>`;
        });
}

function onStudentChange() {
    try {
        localStorage.setItem(STUDENT_KEY, $("student").value);
    } catch (err) {
        // 隐私模式下不记忆选择
    }
    loadAll();
}

function loadAll(refresh) {
    const studentId = currentStudentId();
    const subject = $("subject").value;
    const query = subject ? "?subject=" + encodeURIComponent(subject) : "";

    $("status").textContent = "⏳ 正在读取记忆数据...";

    Promise.all([
        jsonFetch(`${API}/api/review/memory-map/${studentId}${query}`),
        jsonFetch(`${API}/api/review/stats/${studentId}`),
        jsonFetch(`${API}/api/review/today/${studentId}` + (refresh ? "?refresh=true" : "")),
        jsonFetch(`${API}/api/review/strategy-log/${studentId}?limit=15`)
    ])
        .then(([map, stats, today, logs]) => {
            $("status").textContent = "";
            $("stats-box").innerHTML = renderStats(stats, map);
            $("memory-table").innerHTML = renderTable(map);
            $("queue-box").innerHTML = renderQueue(today);
            $("log-box").innerHTML = renderLogs(logs);
        })
        .catch(err => {
            console.error("[memory_debug] 读取失败", err);
            $("status").innerHTML = `<p class="diag-intro">记忆数据刚刚没读到，请再试一次。</p>`;
        });
}

init();
