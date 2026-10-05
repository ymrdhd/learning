// 能力契约｜主动回忆页：出卡（不给选项）→ 主动输入 → 分级提示 → 记忆增益反馈
// 入口：init / startRecall / renderCard / showHint / submitRecall / nextCard / loadSummary
// 依赖：style.css；后端 /api/active-recall/start|answer|summary、/students
// 不负责：题面与判分（backend/active_recall.py）、记忆状态写入（backend/review/engine.py）
// 验证：backend/verify_active_recall.py（recall_case 接口断言 + 页面静态检查）
// 被调用：recall.html
// 索引：docs/MODULE_MAP.md · SPEC.md §8

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin : "http://127.0.0.1:8000";
const STUDENT_KEY = "xiaozhi.student";
const HINT_LEVELS = 4;
const HINT_LABEL = ["", "想一想它属于哪一类知识。", "关键是：", "再想想完整的说法：", "完整提示："];

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

/* 提示等级 → 展示句子：0 表示没有用提示 */
function hintText(card, level) {
    const value = Math.max(0, Math.min(HINT_LEVELS, Number(level) || 0));
    if (!value) return "";
    return HINT_LABEL[value] + ((card && card.hint) || "先自己回忆一下，再试一次。");
}

/* 记忆增益 → 儿童能懂的话 */
function gainText(gain) {
    const value = Number(gain) || 0;
    if (value <= 0) return "这次没记住，等会儿再来一次";
    if (value < 1.5) return "有点印象啦";
    return "记得更牢了";
}

let cards = [];
let index = 0;
let hintLevel = 0;
let startedAt = 0;
let answered = false;

/* ---------------- 页面 ---------------- */

function setStatus(text) {
    $("recall-status").textContent = text;
}

function init() {
    loadStudents().then(loadSummary);
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
            loadSummary();
        });
        $("subject").addEventListener("change", loadSummary);
    }).catch(err => {
        setStatus(`❌ 无法连接后端 (${API})：${err.message}。请先双击 start.bat 启动后端。`);
    });
}

function startRecall() {
    const sid = $("student").value;
    if (!sid) return;
    setStatus("菲比正在挑卡片…");
    postJson(`${API}/api/active-recall/start`, {
        student_id: Number(sid),
        subject: $("subject").value || null,
        count: Number($("count").value)
    }).then(data => {
        cards = data.cards || [];
        index = 0;
        if (!cards.length) {
            setStatus("暂时没有适合的卡片，先去今日学习看看吧～");
            return;
        }
        setStatus(data.message || "先自己想一想，再把答案写出来～");
        renderCard();
    }).catch(err => {
        setStatus(`❌ 出卡失败：${err.message}`);
    });
}

function renderCard() {
    const card = cards[index];
    if (!card) return;
    answered = false;
    hintLevel = 0;
    startedAt = Date.now();
    $("recall-card").style.display = "block";
    $("card-meta").textContent =
        `第 ${index + 1} / ${cards.length} 张 · ${card.subject} · ${card.knowledge} · ${card.kind_text}`;
    $("card-prompt").textContent = card.prompt;
    $("card-hint").textContent = "";
    $("card-answer").value = "";
    $("card-answer").disabled = false;
    $("card-feedback").innerHTML = "";
    $("next-btn").style.display = "none";
    $("next-btn").textContent = "下一张 ➡️";
    $("card-answer").focus();
}

function showHint() {
    if (answered) return;
    hintLevel = Math.min(HINT_LEVELS, hintLevel + 1);
    $("card-hint").textContent = hintText(cards[index], hintLevel);
}

function submitRecall() {
    if (answered) return;
    const sid = $("student").value;
    const card = cards[index];
    if (!sid || !card) return;
    const answer = $("card-answer").value.trim();
    if (!answer && !hintLevel) {
        setStatus("先自己写一句，或者点「想不起来，给点提示」～");
        return;
    }
    const seconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
    postJson(`${API}/api/active-recall/answer`, {
        student_id: Number(sid),
        card_id: card.card_id,
        answer: answer,
        response_time: seconds,
        hint_level: hintLevel,
        confidence_feedback: ""
    }).then(data => {
        answered = true;
        $("card-answer").disabled = true;
        const child = data.child || {};
        $("card-feedback").innerHTML =
            `<p class="task-item-title">${esc(data.result_text || "")}</p>`
            + `<p class="meta">正确答案：${esc((data.expected || []).join(" / "))}</p>`
            + `<p class="meta">${esc(child.icon || "🌱")} ${esc(child.text || "")} · `
            + `${esc(gainText(data.memory_gain))}（+${esc(data.memory_gain)}） · 用了 ${esc(seconds)} 秒`
            + (data.hint_level ? ` · 提示等级 ${esc(data.hint_level)}` : "") + `</p>`
            + (data.hint ? `<p class="meta">💡 ${esc(data.hint)}</p>` : "");
        $("next-btn").style.display = "inline-block";
        if (index >= cards.length - 1) $("next-btn").textContent = "看小结 🎉";
        loadSummary();
    }).catch(err => {
        setStatus(`❌ 提交失败：${err.message}`);
    });
}

function nextCard() {
    if (index >= cards.length - 1) {
        $("recall-card").style.display = "none";
        setStatus("今天的主动回忆完成啦！明天再来几张新的～");
        loadSummary();
        return;
    }
    index += 1;
    renderCard();
}

function loadSummary() {
    const sid = $("student").value;
    if (!sid) return;
    jsonFetch(`${API}/api/active-recall/summary?student_id=${sid}`).then(data => {
        $("recall-total").textContent =
            `今天回忆 ${data.total} 张：完全想起来 ${data.correct} 张，`
            + `想起来一点 ${data.partial} 张，没想起来 ${data.wrong} 张`
            + `（用时约 ${data.minutes} 分钟）`;
        $("recall-list").innerHTML = (data.items || []).map(item => {
            const icon = item.result === "correct" ? "✅" : (item.result === "partial" ? "🌿" : "🔁");
            return `<div class="task-item done"><span class="task-item-title">${icon} ${esc(item.prompt)}</span>`
                + `<span class="task-item-meta">${esc(item.result_text || item.result)} · `
                + `+${esc(item.memory_gain)}</span></div>`;
        }).join("");
    }).catch(() => { /* 小结失败不影响做题 */ });
}

if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", init);
}
