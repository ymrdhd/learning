// ==============================================================
// 能力契约｜错题康复页：错题队列 + 开始康复 + 逐级提示（最多 4 级）+ 判分反馈 + 菲比开心庆祝
// 入口：init / loadRecovery / selectRecovery / startRecovery / loadQuestion / renderHint / showNextHint / showAnalysis / renderResult / renderDone / visibleTextBlocks / nextHintLevel / hintMoreText / phoebeRecoveryFeedback / onPhoebeVoiceToggle
// 依赖：phoebe.js（表情包浮层）、phoebe3d.js（三视图立牌 feedback）——都是可选，缺失时静默降级
// 不负责：康复状态机与判分 → backend/recovery/engine.py；出题 → backend/ai_recovery.py
// 验证：node frontend/verify_recovery_web.js
// 被调用：recovery.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 错题康复中心（V2.5 错题康复系统儿童端）。

   接口：
     GET  /students                     学生列表
     GET  /api/recovery/list            康复队列（按 student_id 隔离）
     POST /api/recovery/start           开始康复（进入 ANALYZING/LEARNING）
     POST /api/recovery/question        出下一题（变式题或原题）
     POST /api/recovery/answer          提交康复练习答案
     POST /api/recovery/hint            取第 N 级提示（读接口，不推进状态）

   儿童友好：单屏只出现「题目」一块文字；提示逐级展开，孩子点「还是不会」才给下一级；
   答对 → 绿色 ✅ + 菲比开心；答错 → 橙色 ❌ + 正确答案 + 「看看解析」。 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

const STUDENT_KEY = "xiaozhi.student";

const HINT_LEVEL_MAX = 4;
const HINT_NEXT_TEXT = { 1: "还是不会", 2: "看看怎么做", 3: "给我完整讲解", 4: "知道了" };

let currentStudent = 1;
let items = [];
let activeRecovery = null;   // 选中的康复条目（来自 /api/recovery/list）
let currentQuestion = null;  // 当前作答的题目
let hintLevel = 0;           // 已展示的最高提示层级 0~4
let answered = false;
let lastResult = null;

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

/* 提示层级只能 0~4 逐级上升，到 4 级封顶（儿童不会一次被灌一堆讲解） */
function nextHintLevel(level) {
    const value = Math.floor(Number(level) || 0);
    if (value < 1) return 1;
    return Math.min(HINT_LEVEL_MAX, value + 1);
}

function percent(done, total) {
    const all = Number(total) || 0;
    if (all <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((Number(done) || 0) / all * 100)));
}

/* 一级一屏：只有还没到 4 级时才给「还是不会」 */
function hintMoreText(level) {
    return HINT_NEXT_TEXT[Number(level) || 1] || "知道了";
}

function stateText(state) {
    const table = {
        NEW: "还没开始", ANALYZING: "菲比正在找错因", LEARNING: "菲比在讲解",
        PRACTICING: "正在练变式题", VERIFYING: "再验证一遍", MASTERED: "已经康复啦"
    };
    return table[state] || "错题康复中";
}

/* ---------------- 菲比联动（模块缺失时静默降级） ---------------- */

function phoebeRecoveryFeedback(correct, word) {
    if (typeof phoebe3dFeedback !== "function") return;
    try {
        phoebe3dFeedback(!!correct, word ? { word: word } : {});
    } catch (err) {
        // 立牌或语音失败都不影响做题
    }
}

function onPhoebeVoiceToggle() {
    const box = $("phoebe-voice");
    if (box && typeof phoebe3dSetVoice === "function") phoebe3dSetVoice(box.checked);
}

function initPhoebeVoice() {
    const box = $("phoebe-voice");
    if (!box) return;
    box.checked = typeof phoebe3dVoiceEnabled === "function" ? phoebe3dVoiceEnabled() : true;
}

/* ---------------- 渲染 ---------------- */

function renderList(data) {
    const list = (data || {}).items || [];
    items = list;

    if (!list.length) {
        $("recovery-list").innerHTML = `
            <p class="recovery-empty">🎉 现在没有要康复的错题，去练几道新题吧！</p>
            <p class="link-row"><a href="index.html">🏠 去自由练习</a>
            <a href="today.html">📅 今日学习</a></p>`;
        $("recovery-work").classList.add("hidden");
        return;
    }

    $("recovery-list").innerHTML = list.map(item => `
        <button class="btn recovery-card-btn" onclick="selectRecovery(${Number(item.recovery_id) || 0})">
            <span class="recovery-card-title">${esc(item.subject)} · ${esc(item.knowledge || "综合")}</span>
            <span class="recovery-card-meta">${esc(item.state_text || stateText(item.state))}
                · 连对 ${esc(item.consecutive_correct || 0)} 次</span>
        </button>`).join("");
}

function renderPick() {
    const item = activeRecovery || {};
    $("recovery-pick").innerHTML = `
        <span class="recovery-state-badge">${esc(item.state_text || stateText(item.state))}</span>
        <span>${esc(item.subject)} · ${esc(item.knowledge || "综合")}</span>`;
    $("recovery-work").classList.remove("hidden");
    $("recovery-start-btn").classList.remove("hidden");
}

function renderQuestion(data) {
    const info = data || {};
    const q = info.question || info;

    $("recovery-start-btn").classList.add("hidden");
    $("blank-box").classList.add("hidden");
    $("result").innerHTML = "";

    currentQuestion = q;
    answered = false;

    $("question").innerHTML = `${esc(q.question || "")}`;

    if (q.qtype === "blank") {
        $("options").innerHTML = "";
        $("blank-box").classList.remove("hidden");
    } else {
        const keys = Object.keys(q.options || {}).sort();
        $("options").innerHTML = keys.map(key => `
            <button class="option" data-key="${esc(key)}" onclick="answerRecovery('${esc(key)}', this)">
                <b>${esc(key)}.</b> ${esc(q.options[key])}
            </button>`).join("");
        if (!keys.length) $("options").innerHTML = `<p class="meta">菲比还在出题，请稍等。</p>`;
    }

    if (info.teaching) renderHint(info.teaching);
}

/* 逐级展开：一次只显示一级提示，孩子点「还是不会」才给下一级 */
function renderHint(teaching) {
    const info = teaching || {};
    const level = Number(info.level) || 1;
    hintLevel = level;

    $("hint-box").innerHTML = `
        <p class="recovery-hint-title">💡 菲比提示 ${level}/${HINT_LEVEL_MAX}：${esc(info.level_text || "")}</p>
        <p class="recovery-hint-text">${esc(info.hint || "")}</p>
        <button class="btn btn-primary recovery-hint-btn" onclick="showNextHint()">${esc(hintMoreText(level))}</button>`;
    $("hint-box").classList.remove("hidden");
}

function renderResult(data) {
    const info = data || {};
    lastResult = info;

    if (info.correct) {
        hintLevel = 0;
        $("hint-box").classList.add("hidden");
        $("result").innerHTML = `
            <div class="recovery-feedback ok">✅ 答对啦！</div>
            <p class="recovery-result-meta">现在：${esc(info.state_text || stateText(info.state))}</p>`;
        phoebeRecoveryFeedback(true);
        return;
    }

    /* 答错时收起提示：正确答案 + 「看看解析」才是这一刻最该看的一块文字 */
    hintLevel = 0;
    $("hint-box").classList.add("hidden");
    $("result").innerHTML = `
        <div class="recovery-feedback bad">❌ 再想想～</div>
        <p class="recovery-answer">正确答案：<b>${esc(info.correct_answer)}</b></p>
        <button class="btn btn-primary recovery-explain-btn" onclick="showAnalysis()">看看解析</button>`;
    phoebeRecoveryFeedback(false);
}

function showAnalysis() {
    const info = lastResult || {};
    $("result").innerHTML = `
        <div class="recovery-feedback bad">❌ 再想想～</div>
        <p class="recovery-answer">正确答案：<b>${esc(info.correct_answer)}</b></p>
        <div class="recovery-explain">
            <p class="recovery-explain-title">📖 错题解析</p>
            <p class="recovery-explain-text">${esc(info.analysis || "菲比再给你讲一遍～")}</p>
        </div>`;
}

function renderDone(data) {
    const stats = (data || {}).stats || {};
    $("recovery-work").classList.add("hidden");
    $("recovery-done").innerHTML = `
        <p class="recovery-done-title">🎉 这道错题康复啦！</p>
        <p class="recovery-done-meta">已经康复 ${esc(stats.mastered || 0)} 道 ·
            还剩 ${esc(Math.max(0, (Number(stats.total) || 0) - (Number(stats.mastered) || 0)))} 道</p>
        <button class="btn btn-primary recovery-main-btn" onclick="loadRecovery()">继续康复下一道 ➡️</button>`;
    $("recovery-done").classList.remove("hidden");
    phoebeRecoveryFeedback(true, "这道错题康复啦！");
}

/* 单屏可见文字块：任何时刻都不超过 3 块（题目 / 提示 / 反馈 / 完成层）
   注意：藏在 <div id="recovery-work" class="hidden"> 里的块在屏幕上根本看不见 */
const TEXT_BLOCK_IDS = ["recovery-pick", "question", "hint-box", "result", "recovery-done"];
const WORK_CHILD_IDS = ["recovery-pick", "question", "hint-box", "result"];

function visibleTextBlocks() {
    const work = $("recovery-work");
    const workHidden = !work || work.classList.contains("hidden");

    return TEXT_BLOCK_IDS.filter(id => {
        if (workHidden && WORK_CHILD_IDS.includes(id)) return false;
        const el = $(id);
        if (!el || (el.classList && el.classList.contains("hidden"))) return false;
        return String(el.innerHTML || "").trim().length > 0;
    });
}

/* ---------------- 流程 ---------------- */

function loadRecovery() {
    $("status").textContent = "⏳ 正在找你的错题...";
    $("recovery-done").classList.add("hidden");
    $("recovery-work").classList.add("hidden");

    return jsonFetch(`${API}/api/recovery/list?student_id=${currentStudent}`)
        .then(data => {
            $("status").textContent = "";
            renderList(data);
        })
        .catch(err => {
            console.error("[recovery] 错题加载失败", err);
            $("status").innerHTML = `<p class="diag-intro">菲比刚刚没拿到错题，我们再试一次。</p>`;
        });
}

function selectRecovery(recoveryId) {
    activeRecovery = items.find(item => Number(item.recovery_id) === Number(recoveryId)) || null;
    currentQuestion = null;
    hintLevel = 0;
    answered = false;
    $("question").innerHTML = "";
    $("options").innerHTML = "";
    $("hint-box").classList.add("hidden");
    $("result").innerHTML = "";
    renderPick();
}

function startRecovery() {
    const item = activeRecovery || {};
    $("recovery-start-btn").classList.add("hidden");
    $("question").innerHTML = "⏳ 菲比正在看这道错题...";

    return postJson(API + "/api/recovery/start", {
        student_id: currentStudent,
        recovery_id: Number(item.recovery_id) || 0
    })
        .then(data => {
            const info = data || {};
            activeRecovery = Object.assign({}, item, info.item || {});
            if (info.teaching) renderHint(info.teaching);
            return loadQuestion();
        })
        .catch(err => {
            console.error("[recovery] 开始康复失败", err);
            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没能开始，我们再试一次。</p>`;
            $("recovery-start-btn").classList.remove("hidden");
        });
}

function loadQuestion() {
    const item = activeRecovery || {};
    $("question").innerHTML = "⏳ 菲比正在出题...";
    $("options").innerHTML = "";
    $("result").innerHTML = "";
    answered = false;

    return postJson(API + "/api/recovery/question", {
        student_id: currentStudent,
        recovery_id: Number(item.recovery_id) || 0,
        hint_level: hintLevel || undefined
    })
        .then(data => renderQuestion(data))
        .catch(err => {
            console.error("[recovery] 出题失败", err);
            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没拿到题目，我们再试一次。</p>`;
        });
}

/* 点「还是不会」→ 取下一级提示；到第 4 级就不再往下要 */
function showNextHint() {
    const item = activeRecovery || {};
    const next = nextHintLevel(hintLevel);

    if (hintLevel >= HINT_LEVEL_MAX) {
        $("hint-box").innerHTML = `<p class="recovery-hint-text">菲比已经讲完啦，试着做做看 💪</p>`;
        return Promise.resolve(null);
    }

    return postJson(API + "/api/recovery/hint", {
        student_id: currentStudent,
        recovery_id: Number(item.recovery_id) || 0,
        level: next
    })
        .then(data => {
            renderHint(Object.assign({ level: next }, data || {}));
            return data;
        })
        .catch(() => {
            // 取提示失败不打断做题，只提示重试
            $("hint-box").innerHTML = `<p class="recovery-hint-text">提示暂时取不到，先自己试试吧～</p>`;
            return null;
        });
}

function answerRecoveryBlank() {
    const box = $("blank-input");
    const value = box ? String(box.value || "").trim() : "";
    if (!value) {
        $("result").innerHTML = `<p class="recovery-result-meta">先写上你的答案哦</p>`;
        return Promise.resolve(null);
    }
    return answerRecovery(value, null);
}

function answerRecovery(value, btn) {
    if (!currentQuestion || answered) return Promise.resolve(null);
    answered = true;

    const item = activeRecovery || {};
    const question = currentQuestion || {};

    if (btn) btn.classList.add("right");

    return postJson(API + "/api/recovery/answer", {
        student_id: currentStudent,
        recovery_id: Number(item.recovery_id) || 0,
        question_id: Number(question.question_id) || 0,
        answer: value,
        hint_level: hintLevel
    })
        .then(data => {
            const info = data || {};
            if (info.correct) {
                renderResult(info);
                if (info.state === "MASTERED") renderDone(info);
                return info;
            }

            renderResult(info);
            if (btn) {
                btn.classList.remove("right");
                btn.classList.add("wrong");
            }
            return info;
        })
        .catch(err => {
            answered = false;
            console.error("[recovery] 提交失败", err);
            $("result").innerHTML = `<p class="recovery-result-meta">😕 菲比刚刚没收到你的答案，再试一次吧。</p>`;
            return null;
        });
}

function onStudentChange() {
    const box = $("student");
    currentStudent = parseInt((box && box.value) || "1", 10);
    try {
        localStorage.setItem(STUDENT_KEY, currentStudent);
    } catch (err) {
        // 隐私模式下不记忆选择，不影响使用
    }
    activeRecovery = null;
    $("recovery-done").classList.add("hidden");
    loadRecovery();
}

function init() {
    initPhoebeVoice();

    jsonFetch(API + "/students")
        .then(list => {
            $("student").innerHTML = (list || []).map(item =>
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
            currentStudent = parseInt($("student").value || "1", 10);

            loadRecovery();
        })
        .catch(err => {
            console.error("[recovery] 连接后端失败", err);
            $("status").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;
        });
}

init();
