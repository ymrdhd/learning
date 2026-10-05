// ==============================================================
// 能力契约｜我的挑战页：待攻克/训练中/已攻克列表 + 错题再练 + 答对庆祝
// 入口：init / loadWrongQuestions / renderItem / renderStats / renderPractice / openPractice / answerPractice / selectStatus / statusText
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js（须先于业务 js 加载）；phoebe.js
// 不负责：错因分析 → backend/error_analysis.py
// 验证：node frontend/verify_knowledge_web.js；node frontend/verify_phoebe_web.js
// 被调用：wrong_book.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 错题中心（V2.3）：错题列表 + 状态统计 + 相似题再练。
   接口：GET /students、GET /api/wrong_questions/{student_id}、
        GET /question、POST /submit */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

/* 状态码 → 中文文案 / 徽标配色（纯函数，方便单测） */
const STATUS_TEXT = { NEW: "🔴 待攻克", LEARNING: "🟡 训练中", MASTERED: "🟢 已攻克" };
const STATUS_CLASS = { NEW: "st-new", LEARNING: "st-learning", MASTERED: "st-mastered" };

let selectedStatus = "";
let wrongItems = [];
let stats = {};
const practiceQuestions = {};   // 错题 id -> 相似题
const practiceResults = {};     // 错题 id -> 作答结果

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

function emptyStateOf(opt) {
    const c = uc();
    const o = opt || {};
    if (c) return c.emptyState({ icon: o.icon, title: o.title, hint: o.hint });
    return `<p class="diag-intro">${esc(o.title || "")}</p>`;
}

function loadingOf(text) {
    const c = uc();
    return c ? c.loadingState({ text: text })
        : `<p class="diag-intro">${esc(text)}</p>`;
}

function errorOf(title, hint) {
    const c = uc();
    if (c) return c.errorState({ title: title, hint: hint, retryLabel: "再试一次", retryAction: "loadWrongQuestions()" });
    return `<p class="diag-intro">${esc(title)}</p>`;
}

function statusText(status) {
    return STATUS_TEXT[status] || "未知";
}

function statusClass(status) {
    return STATUS_CLASS[status] || "st-unknown";
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

function renderStats(data) {
    const info = data || {};
    const cards = [
        [info.NEW || 0, STATUS_TEXT.NEW],
        [info.LEARNING || 0, STATUS_TEXT.LEARNING],
        [info.MASTERED || 0, STATUS_TEXT.MASTERED],
    ];

    return cards.map(card => `<div class="stat-card">
        <span class="stat-num">${esc(card[0])}</span>
        <span class="meta">${esc(card[1])}</span>
    </div>`).join("");
}

/* 卡片内直接渲染相似题：没取题 → 提示；取到题 → 选项；作答过 → 反馈 */
function renderPractice(item) {
    const question = practiceQuestions[item.id];
    if (!question) return "";

    const head = `<p class="practice-title">✍️ 相似题练习</p>
        <p class="qtext">${esc(question.question || "")}</p>`;
    const result = practiceResults[item.id];

    if (!result) {
        const options = question.options || {};
        const buttons = Object.keys(options).map(key =>
            `<button type="button" class="option ph-option" onclick="answerPractice(${item.id},'${esc(key)}')">${esc(key)}. ${esc(options[key])}</button>`
        ).join("");
        return head + `<div class="options">${buttons}</div>`;
    }

    if (result.correct) {
        const next = item.status === "NEW" ? STATUS_TEXT.LEARNING : STATUS_TEXT.MASTERED;
        return head + `<p class="verdict ok">✓ 对啦，这道挑战${next}</p>
            <p class="meta">正确答案：${esc(result.correct_answer || "")}</p>`;
    }

    /* 答错时先讲原因，不给答案当重点 */
    const err = result.error_analysis || {};
    return head + `<p class="verdict bad">${esc(kidLang() ? kidLang().wrongFeedback(1).title : "🤔 这里再想一下")}</p>
        <p class="wrong-analysis">${esc(err.analysis || result.analysis || "这道题还需要再读一遍题目。")}</p>
        <p class="meta">💡 ${esc(err.suggestion || "把这个知识点再练一遍吧。")}</p>`;
}

function renderItem(item) {
    return `<div class="wrong-item">
        <p class="wrong-question">${esc(item.question || "")}</p>
        <p class="wrong-meta">
            <span class="badge ${statusClass(item.status)}">${esc(STATUS_TEXT[item.status] || item.status_text || statusText(item.status))}</span>
            <span class="meta">${esc(item.subject || "")} · ${esc(item.knowledge || "")}</span>
            <span class="meta">错了 ${esc(item.wrong_count || 0)} 次</span>
        </p>
        <p class="meta">最近错因：${esc(item.last_error_type || "暂无")} · ${esc(item.last_wrong_time || "")}</p>
        ${item.analysis ? `<p class="wrong-analysis">${esc(item.analysis)}</p>` : ""}
        <p class="meta">正确答案：${esc(item.correct_answer || "")} · 下次复习：${esc(item.next_review_time || "—")}</p>
        <p class="ph-wrong-actions">
            <button type="button" class="voice-btn ph-btn ph-btn--secondary" onclick="openPractice(${item.id})">✍️ 练一练相似题</button>
            <a class="ph-btn ph-btn--secondary" href="recovery.html">⚔️ 去错题康复</a>
        </p>
        <div class="practice-box">${renderPractice(item)}</div>
    </div>`;
}

function renderList(list) {
    wrongItems = list || [];
    if (!wrongItems.length) {
        $("list").innerHTML = emptyStateOf({
            icon: "🎉",
            title: kidLang() ? kidLang().noWrongText() : "🎉 暂时没有需要攻克的错题！",
            hint: "今天先去做别的小任务吧。"
        });
        return;
    }
    $("list").innerHTML = wrongItems.map(renderItem).join("");
}

function renderWrongBook(data) {
    const info = data || {};
    stats = info.stats || {};
    $("stats").innerHTML = renderStats(stats);
    renderList(info.items || []);
}

function loadWrongQuestions() {
    if (!$("student").value) return Promise.resolve();

    $("list").innerHTML = loadingOf("菲比正在整理你的挑战……");
    $("hint").textContent = "";

    const params = new URLSearchParams({ student_id: currentStudentId() });
    const subject = $("subject").value;
    if (subject) params.set("subject", subject);
    if (selectedStatus) params.set("status", selectedStatus);

    return jsonFetch(API + "/api/wrong_questions/" + currentStudentId() + "?" + params.toString())
        .then(renderWrongBook)
        .catch(err => {
            $("list").innerHTML = "";
            console.error("[wrong_book] 错题读取失败", err);
            $("hint").innerHTML = errorOf("菲比刚刚没拿到你的挑战，我们再试一次。", "点下面的按钮就行。");
        });
}

/* 找一道同科目、同知识点的相似题 */
function openPractice(wrongId) {
    const item = wrongItems.filter(x => x.id === wrongId)[0];
    if (!item) return Promise.resolve();

    const params = new URLSearchParams({
        student_id: currentStudentId(),
        subject: item.subject,
        knowledge: item.knowledge,
        qtype: "choice",
    });

    $("hint").innerHTML = "🕒 正在找一道相似题……";

    return jsonFetch(API + "/question?" + params.toString())
        .then(question => {
            practiceQuestions[wrongId] = question;
            $("hint").textContent = "";
            renderList(wrongItems);
            return question;
        })
        .catch(err => {
            console.error("[wrong_book] 相似题加载失败", err);
            $("hint").innerHTML = errorOf("菲比刚刚没找到相似题，我们再试一次。");
        });
}

/* 提交相似题答案，然后刷新错题状态 */
function answerPractice(wrongId, answer) {
    const question = practiceQuestions[wrongId];
    if (!question) return Promise.resolve();

    return jsonFetch(API + "/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            question_id: question.question_id,
            answer: answer,
            student_id: currentStudentId(),
        }),
    })
        .then(result => {
            practiceResults[wrongId] = result;

            // 再练答对：弹菲比表情包，并把立牌换成「加油」（菲比三视图没加载时退回旧浮层）
            if (result.correct) {
                if (typeof phoebe3dFeedback === "function") {
                    phoebe3dFeedback(true, { word: "错题攻克啦，菲比为你欢呼！", mood: "cheer" });
                } else if (typeof celebrateCorrect === "function") {
                    celebrateCorrect({ word: "错题攻克啦，菲比为你欢呼！" });
                }
            } else {
                if (typeof phoebeResetStreak === "function") phoebeResetStreak();
                if (typeof phoebe3dMood === "function") phoebe3dMood("sad");
            }

            renderList(wrongItems);
            return loadWrongQuestions();
        })
        .catch(err => {
            console.error("[wrong_book] 提交失败", err);
            $("hint").innerHTML = errorOf("菲比刚刚没收到你的答案，再试一次吧。");
        });
}

function selectStatus(status) {
    selectedStatus = status;
    document.querySelectorAll(".status-btn").forEach(btn => {
        btn.classList.toggle("active", (btn.dataset.status || "") === status);
    });
    loadWrongQuestions();
}

function onSubjectChange() {
    loadWrongQuestions();
}

function onStudentChange() {
    loadWrongQuestions();
}

function loadStudents() {
    return jsonFetch(API + "/students")
        .then(list => {
            $("student").innerHTML = (list || []).map(s =>
                `<option value="${s.id}">${esc(s.name)}（${esc(s.grade_text)}）</option>`
            ).join("");
        })
        .catch(err => {
            console.error("[wrong_book] 连接后端失败", err);
            $("hint").innerHTML = errorOf("菲比现在连不上，请先双击 start.bat。");
        });
}

function init() {
    loadStudents().then(loadWrongQuestions);
}

init();
