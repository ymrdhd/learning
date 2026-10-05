// ==============================================================
// 能力契约｜诊断答题页：进度条 / 答题 / 语音朗读 / 答对庆祝
// 入口：init / loadQuestion / renderQuestion / updateProgress / submitAnswer / showFeedback / gotoReport / speakQuestion
// 依赖：无（零构建）；phoebe.js 必须先加载
// 不负责：诊断算法 → backend/diagnostic.py
// 验证：node frontend/verify_diagnostic_web.js；node frontend/verify_phoebe_web.js
// 被调用：diagnostic_test.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 诊断过程页（V2.0）：显示当前阶段与进度，只回对错、不显示答案。 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

const SESSION_KEY = "xiaozhi.diagSession";

let sessionId = 0;
let studentId = 1;
let subject = "数学";
let current = null;
let answered = false;
let voiceOn = true;

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

function restore(key) {
    try {
        return sessionStorage.getItem(key);
    } catch (err) {
        return null;
    }
}

/* 进度文案与进度条宽度：做成纯函数，方便直接单测 */
function progressText(progress) {
    if (!progress) return "0/0";
    return `${progress.answered || 0}/${progress.total || 0}`;
}

function progressPercent(progress) {
    if (!progress || !progress.total) return 0;
    return Math.max(0, Math.min(100, Math.round(100 * (progress.answered || 0) / progress.total)));
}

/* ---------------- 语音朗读（与练习页一致，用浏览器自带语音） ---------------- */

function speechSupported() {
    return voiceOn && typeof window !== "undefined" && "speechSynthesis" in window;
}

function oralText(text) {
    return String(text == null ? "" : text)
        .replace(/_{2,}/g, "空格")
        .replace(/[×✕]/g, "乘")
        .replace(/[÷]/g, "除以")
        .replace(/[＋+]/g, "加")
        .replace(/[－—]/g, "减")
        .replace(/[＝=]/g, "等于")
        .replace(/[？?]/g, "。");
}

function questionSpeechText(data) {
    if (!data) return "";

    let text = oralText(data.question) + "。";
    const options = data.options || {};
    Object.keys(options).sort().forEach(key => {
        text += `选项${key}：${oralText(options[key])}。`;
    });
    return text;
}

function speak(text) {
    if (!speechSupported() || !text) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "zh-CN";
    utter.rate = 0.85;
    window.speechSynthesis.speak(utter);
}

function speakQuestion() {
    speak(questionSpeechText(current));
}

/* ---------------- 诊断流程 ---------------- */

function updateProgress(progress) {
    if (!progress) return;
    $("stage-text").textContent = progress.stage_label || progress.stage || "";
    $("progress-text").textContent = progressText(progress);
    $("progress-fill").style.width = progressPercent(progress) + "%";
}

function renderQuestion(data) {
    updateProgress(data.progress);

    $("question").innerHTML = `
        <p class="qtext">${esc(data.question)}</p>
        <p class="meta">${esc(data.knowledge)} · 难度 ${esc(data.difficulty)}</p>
    `;

    const keys = Object.keys(data.options || {}).sort();
    $("options").innerHTML = keys.map(key => `
        <button class="option" data-key="${esc(key)}" onclick="submitAnswer('${esc(key)}', this)">
            <b>${esc(key)}.</b> ${esc(data.options[key])}
        </button>
    `).join("");

    if (!keys.length) {
        $("options").innerHTML = `<p class="meta">这一题没有选项，正在重新出题...</p>`;
    }
}

function loadQuestion() {
    answered = false;
    $("feedback").innerHTML = "";
    $("options").innerHTML = "";
    $("question").innerHTML = "⏳ 正在出题...";

    jsonFetch(`${API}/api/diagnostic/question?session_id=${sessionId}`)
        .then(data => {
            if (data.finished) {
                gotoReport(data);
                return;
            }
            current = data;
            renderQuestion(data);
            speakQuestion();
        })
        .catch(err => {
            console.error("[diagnostic_test] 出题失败", err);
            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没拿到题目，我们再试一次。</p>`;
        });
}

function showFeedback(data) {
    $("feedback").innerHTML = `
        <p class="verdict ${data.correct ? "ok" : "bad"}">${data.correct ? "✅ 答对了！" : "❌ 这题没答对"}</p>
        <p class="meta">${esc(data.message || "")}</p>
    `;

    /* 诊断页节奏快（答完就跳下一题），表情包只闪现一下、不配音效 */
    if (typeof celebrateCorrect !== "function") return;
    if (data.correct) {
        celebrateCorrect({ duration: 1200, sound: false });
    } else {
        phoebeResetStreak();
    }
}

function submitAnswer(value, btn) {
    if (!current || answered) return;

    answered = true;
    document.querySelectorAll(".option").forEach(item => { item.disabled = true; });

    jsonFetch(API + "/api/diagnostic/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            session_id: sessionId,
            question_id: current.question_id,
            answer: value
        })
    })
        .then(data => {
            if (btn) btn.classList.add(data.correct ? "right" : "wrong");
            if (data.progress) updateProgress(data.progress);
            showFeedback(data);

            if (data.finished) {
                setTimeout(() => gotoReport(data), 1200);
            } else {
                setTimeout(loadQuestion, 800);
            }
        })
        .catch(err => {
            answered = false;
            document.querySelectorAll(".option").forEach(item => { item.disabled = false; });
            console.error("[diagnostic_test] 提交失败", err);
            $("feedback").innerHTML = `<p class="diag-intro">菲比刚刚没收到你的答案，我们再试一次。</p>`;
        });
}

function gotoReport() {
    location.href = `diagnostic_report.html?student_id=${encodeURIComponent(studentId)}`
        + `&subject=${encodeURIComponent(subject)}`;
}

function init() {
    const fromUrl = parseInt(query("session_id") || "0", 10);
    sessionId = fromUrl || parseInt(restore(SESSION_KEY) || "0", 10);

    $("voice-status").textContent = speechSupported() ? "" : "当前浏览器不支持语音朗读";

    if (!sessionId) {
        $("question").innerHTML = `❌ 没有找到诊断记录，请回到 <a href="diagnostic.html">能力诊断</a> 重新开始。`;
        return;
    }

    jsonFetch(`${API}/api/diagnostic/session?session_id=${sessionId}`)
        .then(info => {
            studentId = info.student_id;
            subject = info.subject || "数学";
            $("subject-text").textContent = subject;

            if (info.status === "finished") {
                gotoReport();
                return;
            }
            loadQuestion();
        })
        .catch(err => {
            console.error("[diagnostic_test] 诊断记录读取失败", err);
            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没拿到题目，我们再试一次。</p>`;
        });
}

init();
