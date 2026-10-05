// ==============================================================
// 能力契约｜间隔复习页（V2.4）：记忆花园 / 今日队列 / 复习答题 / 主观感受
// 入口：init / loadToday / renderGarden / renderResult / startReview / submitAnswer / sendFeel / gardenTitle / childMaturity / forestIcon
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js（须先于业务 js 加载）
// 不负责：复习算法 → backend/review/*；旧艾宾浩斯面板 → app.js；家长端原始指标 → memory_debug.html
// 验证：node frontend/verify_memory_web.js
// 被调用：review.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 今天的知识浇水（V2.4 间隔复习，儿童端）。

   接口：
     GET  /students                              学生列表
     GET  /api/review/today/{student_id}         今日复习任务（儿童化文案）
     GET  /api/review/question                   获取复习题（不重复旧题）
     POST /api/review/answer                     提交并更新记忆状态
     GET  /api/review/stats/{student_id}         今日统计

   儿童端只显示"哪个知识该浇水 + 树的成长状态"，
   不显示遗忘风险 / 稳定性这类复杂指标（那些在 memory_debug.html）。 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

const STUDENT_KEY = "xiaozhi.student";

/* 成熟度 → 儿童文案 + 知识森林图标（后端也会返回，这里本地兜底） */
const MATURITY_CHILD = {
    NEW: "🌱 刚学会",
    LEARNING: "🌱 刚学会",
    SHORT_TERM: "🌿 正在巩固",
    CONSOLIDATING: "🌿 正在巩固",
    STABLE: "🌳 记得很牢",
    LONG_TERM: "⭐ 长期掌握"
};

const FOREST_ICON = {
    NEW: "🌰", LEARNING: "🌱", SHORT_TERM: "🌿",
    CONSOLIDATING: "🌳", STABLE: "🌲", LONG_TERM: "⭐"
};

const FEEL_OPTIONS = [
    { value: "easy", text: "😊 简单" },
    { value: "normal", text: "🙂 正常" },
    { value: "hard", text: "🤔 有点难" },
    { value: "lost", text: "😵 不会" }
];

let currentTask = null;      // { subject, knowledge_id }
let currentQuestion = null;
let answered = false;
let questionStartAt = 0;     // 用于算 response_time
let questionMaturityBefore = "";   // 本题开始前这个知识的成熟度，用来判断“记得更牢了”
let lastReviewTask = null;   // 取题失败时“再试一次”要重发的任务

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

/* 共享 UI 层：script 顺序保证已加载；万一没加载，降级成朴素 HTML，页面不会白屏 */
function uc() {
    return (typeof window !== "undefined" && window.UIComponents) || null;
}

function kidLang() {
    return (typeof window !== "undefined" && window.KidLang) || null;
}

function loadingOf(text) {
    const c = uc();
    return c ? c.loadingState({ text: text })
        : `<p class="ph-state--plain">${esc(text)}</p>`;
}

function errorOf(title, retryAction) {
    const c = uc();
    if (c) return c.errorState({ title: title, retryAction: retryAction });
    return `<p class="diag-intro">${esc(title)}</p>`;
}

function emptyOf(opt) {
    const c = uc();
    const o = opt || {};
    if (c) return c.emptyState({ icon: o.icon, title: o.title, hint: o.hint });
    return `<p class="diag-intro">${esc(o.title || "")}</p>`;
}

/* ---------------- 纯函数 ---------------- */

function childMaturity(level) {
    return MATURITY_CHILD[String(level || "").toUpperCase()] || "🌱 刚学会";
}

function forestIcon(level) {
    return FOREST_ICON[String(level || "").toUpperCase()] || "🌰";
}

/* 成熟度 -> 卡片上的树图标（取儿童文案的第一个字符，保证文字与图标一致） */
function maturityIcon(level) {
    return String(childMaturity(level)).split(" ")[0] || "🌱";
}

/* 还需要浇水的数量（未完成的卡片数） */
function remainingCount(today) {
    const items = (today || {}).items || [];
    return items.filter(item => (item.status || "PENDING") !== "COMPLETED").length;
}

/* 下次浇水的说法：把日期变成"几天后" */
function nextWaterText(result) {
    const info = result || {};
    const days = Number(info.next_interval);
    if (!days || days <= 0) return "下次再来看看";
    if (days < 1) return "等会儿再复习一次";
    return `大约 ${Math.round(days)} 天后再来浇水`;
}

function gardenTitle(today) {
    const info = today || {};
    const lang = kidLang();
    const remain = remainingCount(info);
    if (!info.total) {
        return lang ? lang.noReviewText() : "🌳 今天没有知识需要复习。";
    }
    if (remain <= 0) return "🎉 今天的知识都照顾好啦！";
    return lang ? lang.forgettingText(remain) : `🌱 今天有 ${remain} 个知识需要照顾。`;
}

function feelButtonsHtml() {
    return FEEL_OPTIONS.map(item =>
        `<button class="feel-btn" data-feel="${esc(item.value)}" onclick="sendFeel('${esc(item.value)}')">${esc(item.text)}</button>`
    ).join("");
}

/* ---------------- 渲染 ---------------- */

function renderGarden(today) {
    const info = today || {};
    const items = info.items || [];

    const headHtml = `
        <div class="plan-today">
            <p class="plan-title">${esc(gardenTitle(info))}</p>
            <p class="meta">共 ${esc(info.total || 0)} 个知识 · 计划 ${esc(info.planned_questions || 0)} 题
                · 已完成 ${esc(info.completed || 0)} 个</p>
            ${info.relearn && info.relearn.length
                ? `<p class="meta">🌰 ${info.relearn.length} 个知识需要重新种一遍（先学再复习）</p>` : ""}
        </div>`;

    $("garden-head").innerHTML = headHtml;

    if (!items.length) {
        const emptyHtml = emptyOf({
            icon: "🌳",
            title: kidLang() ? kidLang().noReviewText() : "🌳 今天没有知识需要复习。",
            hint: "先去「今天」的小任务里学点新东西吧。"
        }) + '<p class="meta"><a href="today.html">🏠 回到今天</a></p>';
        $("garden").innerHTML = emptyHtml;
        return headHtml + emptyHtml;
    }

    const cardsHtml = items.map(item => `
        <div class="memory-card ${item.status === "COMPLETED" ? "done" : ""}">
            <div class="memory-line">
                <span class="forest-icon">${esc(item.forest_icon || forestIcon(item.maturity_level))}</span>
                <span class="memory-knowledge">${esc(item.knowledge_id)}</span>
                <span class="badge">${esc(item.maturity_child || childMaturity(item.maturity_level))}</span>
            </div>
            <div class="memory-meta">${esc(item.subject)} · 该浇水啦 · 计划 ${esc(item.target_count)} 题</div>
            <button class="mode-btn" onclick="startReview('${esc(item.subject)}', '${esc(item.knowledge_id)}')">
                ${item.status === "COMPLETED" ? "再练一次" : "开始复习"}
            </button>
        </div>`).join("");

    $("garden").innerHTML = cardsHtml;
    return headHtml + cardsHtml;
}

function renderQuestion(data) {
    const info = data || {};
    const memory = info.memory || {};

    $("question").innerHTML = `<span class="qtext-main">${esc(info.question)}</span>`;

    $("memory-badge").innerHTML =
        `${esc(forestIcon(memory.maturity_level))} ${esc(info.knowledge)}
         · ${esc(memory.maturity_child || childMaturity(memory.maturity_level))}
         <br><span class="meta">这是复习题，换个数字看看你还记得吗</span>`;
    questionMaturityBefore = memory.maturity_level || "";
    $("memory-badge").classList.remove("hidden");

    const keys = Object.keys(info.options || {}).sort();
    $("options").innerHTML = keys.map(key => `
        <button type="button" class="option ph-option" data-key="${esc(key)}" onclick="submitAnswer('${esc(key)}', this)">
            <b>${esc(key)}.</b> ${esc(info.options[key])}
        </button>`).join("");

    if (!keys.length) {
        $("options").innerHTML = `<p class="meta">这道题没有选项，请重新获取。</p>`;
    }
}

function renderResult(data) {
    const info = data || {};
    const lang = kidLang();
    const beforeIcon = questionMaturityBefore ? maturityIcon(questionMaturityBefore) : "";
    const afterIcon = info.maturity_level ? maturityIcon(info.maturity_level) : "";
    const upgraded = Boolean(info.maturity_upgraded)
        || (info.correct && beforeIcon && afterIcon && beforeIcon !== afterIcon);
    const head = info.correct ? "✓ 对啦" : (lang ? lang.wrongFeedback(1).title : "🤔 这里再想一下");

    let correctLine = "";
    if (!info.correct) {
        correctLine = `<p>正确答案：<b>${esc(info.correct_answer)}</b></p>`;
    }

    let upgradeLine = "";
    if (upgraded) {
        const name = info.knowledge || (currentTask && currentTask.knowledge_id) || "";
        upgradeLine = `<p class="ph-upgrade">` + (lang
            ? esc(lang.upgradeText({ icon: beforeIcon || "🌿" }, { icon: afterIcon || "🌳" }, name))
            : esc(`${beforeIcon || "🌿"} → ${afterIcon || "🌳"}\u3000「${name}」这个知识记得更牢啦！`)) + `</p>`;
    }

    $("result").innerHTML = `
        <p class="verdict ${info.correct ? "ok" : "bad"}">${head}</p>
        ${upgradeLine}
        ${correctLine}
        <p class="memory-tip">${esc(info.child_message || "")}</p>
        <p class="meta">${esc(info.maturity_child || "")} ·
            ${esc(nextWaterText(info))} · 复习质量：${esc(info.review_quality_text || "")}</p>`;
}

function renderFeel() {
    $("feel-box").innerHTML = `
        <p class="feel-title">这次想起来的感觉是？</p>
        <div class="feel-row">
            ${feelButtonsHtml()}
            <button class="feel-btn skip-btn" onclick="loadToday()">先不回答</button>
        </div>`;
    $("feel-box").classList.remove("hidden");
}

/* ---------------- 流程 ---------------- */

/* 取题失败时「再试一次」：回到刚才那个知识，重新要一道题 */
function retryReview() {
    if (!lastReviewTask) {
        loadToday();
        return;
    }
    startReview(lastReviewTask.subject, lastReviewTask.knowledge_id);
}

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

            loadToday();
        })
        .catch(err => {
            console.error("[review] 连接后端失败", err);
            $("status").innerHTML = errorOf("菲比现在连不上，请先双击 start.bat。", "init()");
        });
}

function onStudentChange() {
    try {
        localStorage.setItem(STUDENT_KEY, $("student").value);
    } catch (err) {
        // 隐私模式下不记忆选择
    }
    resetPractice();
    loadToday();
}

function resetPractice() {
    currentTask = null;
    currentQuestion = null;
    answered = false;
    $("practice").classList.add("hidden");
    $("question").innerHTML = "";
    $("options").innerHTML = "";
    $("result").innerHTML = "";
    $("memory-badge").innerHTML = "";
    $("feel-box").innerHTML = "";
    $("feel-box").classList.add("hidden");
}

function loadToday(refresh) {
    $("status").innerHTML = loadingOf("菲比正在看看哪些知识该浇水……");

    const url = `${API}/api/review/today/${currentStudentId()}` + (refresh ? "?refresh=true" : "");
    jsonFetch(url)
        .then(today => {
            $("status").textContent = "";
            renderGarden(today);
        })
        .catch(err => {
            console.error("[review] 复习任务加载失败", err);
            $("status").innerHTML = errorOf("菲比刚刚没拿到复习任务，我们再试一次。", "loadToday()");
        });
}

function startReview(subject, knowledge) {
    currentTask = { subject: subject, knowledge_id: knowledge };
    lastReviewTask = { subject: subject, knowledge_id: knowledge };
    questionMaturityBefore = "";
    answered = false;

    $("practice").classList.remove("hidden");
    $("result").innerHTML = "";
    $("feel-box").innerHTML = "";
    $("feel-box").classList.add("hidden");
    $("question").innerHTML = loadingOf("菲比正在准备一道适合你的题……");
    $("options").innerHTML = "";

    const params = new URLSearchParams({
        student_id: String(currentStudentId()),
        subject: subject,
        knowledge_id: knowledge
    });

    jsonFetch(API + "/api/review/question?" + params.toString())
        .then(data => {
            currentQuestion = data;
            questionStartAt = Date.now();
            renderQuestion(data);
        })
        .catch(err => {
            console.error("[review] 复习题获取失败", err);
            $("question").innerHTML = errorOf("菲比刚刚没拿到题目，我们再试一次。", "retryReview()");
        });
}

function submitAnswer(value, btn) {
    if (!currentQuestion || answered) return;

    answered = true;
    const elapsed = Math.max(1, Math.round((Date.now() - questionStartAt) / 1000));

    jsonFetch(API + "/api/review/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            student_id: currentStudentId(),
            question_id: currentQuestion.question_id,
            answer: value,
            response_time: elapsed,
            difficulty_feedback: ""
        })
    })
        .then(result => {
            if (btn) btn.classList.add(result.correct ? "right" : "wrong");
            if (!result.correct && result.correct_answer) {
                const right = document.querySelector(`.option[data-key="${result.correct_answer}"]`);
                if (right) right.classList.add("right");
            }
            renderResult(result);
            renderFeel();
            loadToday();
        })
        .catch(err => {
            answered = false;
            console.error("[review] 提交失败", err);
            $("result").innerHTML = '<p class="meta">😕 菲比刚刚没收到你的答案，再点一下选项试试。</p>';
        });
}

/* 孩子自评难度：只微调下次复习间隔（不会重复判分） */
function sendFeel(feel) {
    if (!currentQuestion) return;

    $("feel-box").innerHTML = "<p class='meta'>已经记住你的感受啦～</p>";

    return jsonFetch(API + "/api/review/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            student_id: currentStudentId(),
            question_id: currentQuestion.question_id,
            feel: feel
        })
    })
        .then(data => {
            $("feel-box").innerHTML = `
                <p class="memory-tip">收到啦！${esc((data.memory || {}).maturity_child || "")}</p>
                <p class="meta">下次复习：${esc(data.next_review_at || "")}</p>
                <button class="mode-btn" onclick="loadToday()">继续浇水 ➡️</button>`;
            loadToday();
        })
        .catch(() => {
            $("feel-box").innerHTML = "<p class='meta'>感受没记上，不过没关系，继续加油～</p>";
        });
}

init();
