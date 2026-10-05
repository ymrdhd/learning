// ==============================================================
// 能力契约｜今日学习页：今日计划 + 自适应出题 + 难度感受反馈 + 答对自动跳题 + 错题解析 + 菲比语音字幕
// 入口：init / loadPlan / loadTasks / renderTaskBlock / completeTask / taskMixText / taskSummaryText / startTask / practiceJumpUrl / loadNext / nextQuestion / submitAnswer / sendFeedback / sendAutoFeedback / phoebeAnswerFeedback / onPhoebeVoiceToggle / starsOf / starText / feelButtonsHtml / planVoiceText / planItemsHtml / loadDailyPlan / startToday / loadPoints / renderPoints / claimDailyLogin
// 依赖：phoebe.js（表情包浮层）、phoebe3d.js（三视图立牌 + 语音字幕）——都是可选，缺失时静默降级
// 不负责：3D 立牌与语音实现 → phoebe3d.js；表情包 → phoebe.js
// 验证：node frontend/verify_adaptive_web.js（+ node frontend/verify_phoebe3d_web.js）
// 被调用：today.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 今日学习首页 + 学习反馈页（V2.3 自适应学习引擎）。

   接口：
     GET  /students                                学生列表
     GET  /api/learning/plan/{student_id}          今日计划（自适应生成）
     GET  /api/learning/recommend/{student_id}     今日推荐（含理由）
     POST /api/learning/start                      开始学习任务
     GET  /api/learning/next-question              下一题（知识点与难度自适应）
     POST /submit                                  判分
     POST /api/learning/feedback                   难度感受反馈
     GET  /api/learning/strategy-log/{student_id}  策略日志（为什么这么安排）
     GET  /api/tasks/today                        今日任务（V2.5 每日学习习惯，50/30/20 配比）
     POST /api/tasks/complete                     完成今日任务的一项 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

const STUDENT_KEY = "xiaozhi.student";

/* 难度感受选项：题目结束后问一句，用来优化难度模型 */
const FEEL_OPTIONS = [
    { value: "easy", text: "😊 简单" },
    { value: "normal", text: "🙂 正常" },
    { value: "hard", text: "🤔 有点难" },
    { value: "lost", text: "😵 不会" }
];

const ACTION_TEXT = {
    practice: "强化练习",
    review: "复习巩固",
    challenge: "挑战提升",
    diagnostic: "能力诊断"
};

let currentTask = null;      // 当前学习任务（科目 + 知识点 + 难度）
let currentQuestion = null;  // 当前题目
let answered = false;
let lastResult = null;
let autoNextTimer = null;    // 答对后自动跳下一题的定时器
let feedbackSent = false;    // 每道题只提交一次学习反馈（今日计划完成数靠它推进）
let recentKnowledge = [];    // 最近几题练过的知识点（去重，最近的在最后）
let lastTaskData = null;     // 最近一次 /api/tasks/today 的数据（开学时挑未完成的小任务用）

// 同知识点软避让窗口：默认学习任务锁定的知识点，如果落在最近 2 题里就交给后端换一个，
// 但过几道还能再练同一个知识点（只降密度，不禁止反复练习）
const AVOID_RECENT_COUNT = 2;
const AVOID_LIST_LIMIT = 5;

function noteKnowledge(knowledge) {
    const name = String(knowledge || "").trim();
    if (!name) return;

    recentKnowledge = recentKnowledge.filter(item => item !== name);
    recentKnowledge.push(name);
    if (recentKnowledge.length > AVOID_LIST_LIMIT) {
        recentKnowledge = recentKnowledge.slice(-AVOID_LIST_LIMIT);
    }
}

function knowledgeLocked(knowledge) {
    const name = String(knowledge || "").trim();
    return !name || !recentKnowledge.slice(-AVOID_RECENT_COUNT).includes(name);
}
const AUTO_NEXT_MS = 1700;   // 答对后停留多久自动进入下一题（留出庆祝时间）

function $(id) {
    return document.getElementById(id);
}

function esc(text) {
    return String(text == null ? "" : text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

/* ---------------- 儿童化文案与共享 UI 层（简报 §16 / §22 / §41） ---------------- */

/*
 * 共享层（ui-shell / kid-lang / ui-components）排在本文件之后加载，
 * 所以只能在“调用时”再去取，不能在文件顶层取。缺失时全部走安静降级。
 */
function uc() {
    return (typeof window !== "undefined" && window.UIComponents) || null;
}

function kidLang() {
    return (typeof window !== "undefined" && window.KidLang) || null;
}

/* 后端 reason / 文案里可能出现「掌握度60」「遗忘风险 72%」，儿童端一律换成成长语言。 */
function kidText(text) {
    const lang = kidLang();
    return String(text == null ? "" : text)
        .replace(/掌握度\s*([0-9]+(?:\.[0-9]+)?)/g, (all, num) => {
            if (!lang) return "已经在进步";
            const st = lang.statusOf(Number(num));
            return st.icon + st.label;
        })
        .replace(/遗忘风险\s*[0-9]+%?/g, "需要再照顾一下")
        .replace(/稳定性\s*[0-9.]+/g, "记得越来越牢");
}

function kidStatus(score) {
    const lang = kidLang();
    if (!lang) return "🌱 刚开始";
    const st = lang.statusOf(score);
    return st.icon + " " + st.label;
}

function loadingHtml(text) {
    const c = uc();
    return c ? c.loadingState({ text: text }) : `<p class="meta">⏳ ${esc(text)}</p>`;
}

/* 错误状态底部的「再试一次」用内联 onclick 接回原请求函数，不暴露任何技术细节。 */
function errorHtml(title, handlerName) {
    const c = uc();
    const html = c
        ? c.errorState({ title: title })
        : `<p class="meta">🐼 ${esc(title)}</p>`
            + `<button type="button" class="ph-btn ph-btn--primary" data-action="retry">再试一次</button>`;
    return html.replace('data-action="retry"',
        'data-action="retry" onclick="' + handlerName + '()"');
}

/* ---------------- 答对 / 答错分级（用户简报 §14 / §15） ---------------- */

let answerStreak = 0;   // 连续答对，答错清零（跨题保持）
let wrongRound = 0;     // 本题答错次数（1~4），换题清零
const levelSeen = {};   // 知识点 -> 上次的儿童化状态，只用来识别「升级」

/* 只有档位上升才算重要成长；第一次见到这个知识点不算升级。 */
function upgradeOf(mastery) {
    const lang = kidLang();
    if (!lang || !lang.isUpgrade || !mastery || !mastery.knowledge) return null;
    const name = String(mastery.knowledge);
    const next = lang.statusOf(mastery.mastery_score);
    const prev = levelSeen[name];
    levelSeen[name] = next;
    return lang.isUpgrade(prev && prev.key, next.key) ? { from: prev, to: next, name: name } : null;
}

/* 连续答对 3 题起才给额外鼓励，不做每题的烟花。 */
function streakLine() {
    return answerStreak >= 3
        ? `<p class="ph-streak">🔥 连续 ${answerStreak} 题正确</p>`
        : "";
}

/* 连对 combo（V2.6 即时反馈）：从第 2 题起给一个越来越热闹的浮层，纯展示、不参与判分 */
function comboLevel(count) {
    if (count >= 8) return { tier: "super", text: "太厉害了！" };
    if (count >= 5) return { tier: "hot", text: "手速好快" };
    if (count >= 3) return { tier: "good", text: "越做越顺" };
    return { tier: "start", text: "连对啦" };
}

function comboHtml(streak) {
    const count = Number(streak === undefined ? answerStreak : streak) || 0;
    if (count < 2) return "";
    const level = comboLevel(count);
    return `<div class="ph-combo is-${esc(level.tier)}" role="status" aria-live="polite">`
        + `<span class="ph-combo-num">COMBO ×${esc(count)}</span>`
        + `<span class="ph-combo-text">${esc(level.text)}</span></div>`;
}

/* 答错后逐级增加帮助：提示内容全部取自后端返回，前端不生成答案（§13.3）。 */
function hintTextOf(round, info) {
    const ea = (info && info.error_analysis) || {};
    if (round <= 1) {
        return ea.error_type
            ? `这次是「${ea.error_type}」。先想清楚题目在问什么，再看要算哪一步。`
            : "先想一想：题目问的是什么？给了哪些条件？";
    }
    if (round === 2) return ea.analysis || "再看看题目里的关键条件，它们决定了要怎么做。";
    if (round === 3) return ea.suggestion || "一步一步来：把每一步都写下来，再往下算。";
    return info && info.analysis ? info.analysis : "";
}

function hintHtmlOf(round, info) {
    const lang = kidLang();
    const c = uc();
    const hint = lang
        ? lang.wrongFeedback(round)
        : { title: "🤔 这里再想一下", level: "方向提示", retryLabel: "我再试试" };
    if (c && c.hintPanel) {
        return c.hintPanel({
            level: hint.level,
            title: hint.title,
            body: hintTextOf(round, info),
            retryLabel: hint.retryLabel
        }).replace('data-action="retry"', 'data-action="retry" onclick="retryQuestion()"');
    }
    return `<div class="ph-hint"><p class="ph-hint-title">${esc(hint.title)}</p>`
        + `<p class="ph-hint-body">${esc(hintTextOf(round, info))}</p>`
        + `<button type="button" class="ph-btn ph-btn--secondary" onclick="retryQuestion()">${esc(hint.retryLabel)}</button></div>`;
}

/* 「我再试试」：把同一道题重新打开，不清空题目，也不额外泄露答案。 */
function retryQuestion() {
    if (!currentQuestion) return;
    answered = false;
    clearAutoNext();
    $("blank-input").disabled = false;
    document.querySelectorAll(".option").forEach(item => {
        item.disabled = false;
        item.classList.remove("is-wrong", "is-right", "wrong", "right");
    });
    $("result").innerHTML = "";
    $("feel-box").classList.add("hidden");
}

/* ---------------- 顶部：当前学习者与切换入口（简报 §8 / §24） ---------------- */

let studentList = [];

function currentStudentItem() {
    const id = String(($("student") && $("student").value) || "1");
    return studentList.filter(item => String(item.id) === id)[0] || null;
}

/* 切换学生后必须刷新当前学生的全部 UI 状态（简报 §24） */
function updateWho() {
    const me = currentStudentItem();
    if (!me) return;
    if ($("who-name")) $("who-name").textContent = me.name || "小朋友";
    if ($("who-grade")) $("who-grade").textContent = me.grade_text || "";
    if (window.UIShell && UIShell.applyAgeMode) UIShell.applyAgeMode(me.grade);
}

function renderStudentPicker() {
    const box = $("student-picker");
    if (!box) return;
    box.innerHTML = studentList.map(item =>
        `<button type="button" class="ph-btn ph-btn--secondary" data-student-id="${esc(item.id)}"`
        + ` data-student-name="${esc(item.name)}">${esc(item.name)}（${esc(item.grade_text)}）</button>`
    ).join("");
    if (window.UIShell && UIShell.createStudentSwitcher) {
        try {
            UIShell.createStudentSwitcher(box);
        } catch (err) {
            console.error("[today] 学生切换绑定失败", err);
        }
    }
}

function toggleStudentPicker() {
    const box = $("student-picker");
    const btn = $("switch-student");
    if (!box) return;
    const hidden = box.classList.toggle("hidden");
    if (btn && btn.setAttribute) btn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function jsonFetch(url, options) {
    return fetch(url, options).then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    });
}

/* ---------------- 纯函数（方便直接单测） ---------------- */

/* 掌握度 → 1~5 颗星，与后端 stages.stars 保持一致 */
function starsOf(score) {
    const value = Number(score) || 0;
    if (value <= 0) return 0;
    return Math.max(1, Math.min(5, Math.floor(value / 20) + 1));
}

function starText(score) {
    const count = starsOf(score);
    return "★".repeat(count) + "☆".repeat(5 - count);
}

/* 完成进度：分母为 0 时返回 0，超过 100% 截断 */
function percent(done, total) {
    const all = Number(total) || 0;
    if (all <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((Number(done) || 0) / all * 100)));
}

function actionText(action) {
    return ACTION_TEXT[action] || "练习";
}

/* 计划条目：剩余多少题 / 完成到什么程度 */
function remainText(item) {
    const info = item || {};
    const remain = Number(info.remain_count) || 0;
    if (remain <= 0) return "今天的任务完成啦 🎉";
    const unit = info.subject === "英语" ? "个" : "题";
    return `剩余：${remain} ${unit}`;
}

function feelButtonsHtml() {
    return FEEL_OPTIONS.map(item =>
        `<button class="feel-btn" data-feel="${esc(item.value)}" onclick="sendFeedback('${esc(item.value)}', false)">${esc(item.text)}</button>`
    ).join("");
}

/* ---------------- 渲染 ---------------- */

function renderPlanHead(plan) {
    const info = plan || {};
    const items = info.items || [];

    if (!items.length) {
        // V2.5：不再要求先做一次能力诊断，随便练几题系统就能自动看出水平
        return `<p class="diag-intro">今天还没有安排：先自由练几道题，系统会自动看出你的水平，
            再给你排今天的任务。</p>
            <p class="link-row"><a href="index.html">🏠 去自由练习</a>
            <a href="ability.html">📊 看看我的能力水平</a></p>`;
    }

    const nextItem = items.find(item => Number(item.remain_count) > 0) || items[0];

    return `
        <div class="plan-today">
            <p class="plan-title">今天的学习目标（共 ${esc(info.minutes || 0)} 分钟）</p>
            <div class="progress-bar"><div class="progress-fill" style="width:${percent(info.completed_count, info.target_count)}%"></div></div>
            <p class="meta">已完成 ${esc(info.completed_count || 0)} / ${esc(info.target_count || 0)}
                · 进度 ${percent(info.completed_count, info.target_count)}%</p>
            <button id="main-btn" class="start-btn" onclick="startToday()">
                🚀 开始今日学习
            </button>
        </div>`;
}

function renderPlanList(plan) {
    const items = (plan || {}).items || [];
    if (!items.length) return "";

    return items.map(item => `
        <div class="plan-item ${Number(item.remain_count) > 0 ? "" : "done"}">
            <div class="plan-line">
                <span class="plan-subject">${esc(item.subject)}</span>
                <span class="plan-stars">${starText(item.target_mastery)}</span>
                <span class="badge">${esc(item.item_type_text || "")}</span>
                <span class="badge">${esc(actionText(item.action))}</span>
            </div>
            <div class="plan-knowledge">${esc(item.knowledge_id)}</div>
            <div class="plan-goal">目标：${esc(item.goal)}</div>
            <div class="plan-meta">${esc(remainText(item))} · ${esc(item.duration_minutes)} 分钟
                · 难度 ${esc(item.difficulty)} · ${esc(item.status_text)}</div>
            <button class="mode-btn" onclick="startToday()">开始这一科</button>
        </div>`).join("");
}

function renderWhy(logs) {
    const items = (logs || {}).logs || [];
    if (!items.length) return "";

    return `<p class="why-title">🧠 为什么这样安排</p>` + items.slice(0, 3).map(item => `
        <div class="why-item">
            <span class="badge">${esc(actionText(item.action))}</span>
            <span>${esc(item.subject)} · ${esc(item.knowledge)} · 难度 ${esc(item.difficulty)}</span>
            <div class="why-reason">${esc(kidText(item.reason))}</div>
        </div>`).join("");
}

function renderQuestion(data) {
    const info = data || {};
    const adaptive = info.adaptive || {};

    $("question").innerHTML = `
        <span class="qtext-main">${esc(info.question)}</span>`;

    $("adaptive-badge").innerHTML = adaptive.knowledge
        ? `🎯 ${esc(adaptive.knowledge)} · 难度 ${esc(adaptive.difficulty)}
           · ${esc(adaptive.action_text || actionText(adaptive.action))}
           <br><span class="meta">${esc(kidText(adaptive.reason || ""))}</span>`
        : "";

    $("adaptive-badge").classList.toggle("hidden", !adaptive.knowledge);

    if (info.qtype === "blank") {
        $("options").innerHTML = "";
        $("blank-box").classList.remove("hidden");
        $("blank-input").value = "";
        $("blank-input").disabled = false;
        $("blank-input").focus();
        return;
    }

    $("blank-box").classList.add("hidden");

    const keys = Object.keys(info.options || {}).sort();
    $("options").innerHTML = keys.map(key => `
        <button type="button" class="option ph-option" data-key="${esc(key)}" onclick="submitAnswer('${esc(key)}', this)">
            <b>${esc(key)}.</b> ${esc(info.options[key])}
        </button>`).join("");

    if (!keys.length) {
        $("options").innerHTML = `<p class="meta">模型没有返回选项，请重新出一题。</p>`;
    }
}

function renderResult(data) {
    const info = data || {};
    const mastery = info.mastery || {};
    const masteryLine = mastery.knowledge
        ? `<p class="meta">「${esc(mastery.knowledge)}」${esc(kidStatus(mastery.mastery_score))}</p>`
        : "";

    if (info.correct) {
        answerStreak += 1;
        wrongRound = 0;
    } else {
        answerStreak = 0;
        wrongRound = Math.min(wrongRound + 1, 4);
    }
    // 只有知识点档位上升才给更明显的动画（用户简报 §14）
    const upgrade = info.correct ? upgradeOf(mastery) : null;
    // V2.6：等级真的提升一次，左侧菲比收藏 +1（学习成果驱动，不看在线时长）
    if (upgrade) phoebeCollect();

    if (info.correct) {
        // 答对：报喜后自动进入下一题，不打断节奏
        $("result").innerHTML = `
            ${comboHtml()}
            <p class="verdict ok">${upgrade ? "🌳 升级！" : "✓ 对啦"}</p>
            ${upgrade ? `<p class="ph-upgrade">${esc(kidLang().upgradeText(upgrade.from, upgrade.to, upgrade.name))}</p>` : ""}
            ${streakLine()}
            ${masteryLine}
            <p class="next-tip" id="next-tip">菲比正在庆祝，马上进入下一题…</p>`;
        return;
    }

    // 答错：先「这里再想一下」+ 小提示，孩子点「我再试试」就能重做同一题；
    // 每再错一次就多给一点帮助（方向 → 条件 → 步骤 → 完整讲解）。
    const correctLine = info.correct_text
        ? `<p>正确答案：<b>${esc(info.correct_answer)}. ${esc(info.correct_text)}</b></p>`
        : `<p>正确答案：<b>${esc(info.correct_answer)}</b></p>`;

    $("result").innerHTML = `
        ${hintHtmlOf(wrongRound, info)}
        ${correctLine}
        <div class="explain-box">
            <p class="explain-title">📖 错题解析</p>
            <p class="explain-text">${esc(info.analysis)}</p>
        </div>
        ${masteryLine}`;
}

function renderFeelPrompt() {
    $("feel-box").innerHTML = `
        <p class="feel-title">这道题感觉怎么样？</p>
        <div class="feel-row">
            ${feelButtonsHtml()}
            <button class="feel-btn help-btn" onclick="sendFeedback('hard', true)">🆘 需要帮助</button>
            <button class="feel-btn skip-btn" onclick="nextQuestion()">我明白了，下一题 ➡️</button>
        </div>`;
    $("feel-box").classList.remove("hidden");
}

function renderFeedback(data) {
    const info = data || {};
    $("feel-box").innerHTML = `
        <p class="feel-title">${esc(info.message || "收到啦")}</p>
        <p class="meta">下一题难度：${esc(info.next_difficulty)}（${esc(kidText(info.difficulty_reason || ""))}）</p>
        <button id="next-btn" class="mode-btn" onclick="nextQuestion()">下一题 ➡️</button>`;
    $("feel-box").classList.remove("hidden");
}

/* ---------------- V2.5 今日任务区块（每日学习习惯 50/30/20） ---------------- */

/* 三类任务的固定配比：新知识 50% / 薄弱点 30% / 复习 20% */
const TASK_MIX_LABEL = [
    { key: "new_learning", text: "新知识" },
    { key: "weakness", text: "薄弱点" },
    { key: "review", text: "复习" }
];

function taskMixText(mix) {
    const info = mix || {};
    return TASK_MIX_LABEL.map(item => `${item.text} ${Number(info[item.key]) || 0}%`).join(" · ");
}

/* 完成率 / 时长一行说清楚，不堆文字 */
function taskSummaryText(summary) {
    const info = summary || {};
    const done = Number(info.done) || 0;
    const total = Number(info.total) || 0;
    return `完成 ${done}/${total} · 完成率 ${percent(done, total)}% · 已学 ${Number(info.minutes) || 0} 分钟`;
}

function taskDone(task) {
    const info = task || {};
    const status = String(info.status || "").trim();
    // 后端状态是唯一真相：只有 done 算完成（doing 也不能算）
    if (status) return status === "done";
    // 老接口没给 status 时才退回文案判断；注意「待完成 / 未完成」里也含「完成」二字
    const text = String(info.status_text || "");
    return text.includes("完成") && !text.includes("待") && !text.includes("未");
}

/* V2.6：答题型任务由答题自动完成（做够题数就标记 done），只有需要去其它页面完成的
   「错题康复 / 主动回忆」才留手动打卡按钮，避免孩子以为每项都要自己点 */
const AUTO_DONE_TYPES = ["new_learning", "weakness", "review"];

function taskItemHtml(task) {
    const info = task || {};
    const done = taskDone(info);
    return `
        <div class="task-item ${done ? "done" : ""}">
            <span class="task-item-title">${esc(info.title || info.task_type_text || "今日任务")}${
                done ? '<span class="task-done-badge">已完成</span>' : ""}</span>
            <span class="task-item-meta">${esc(info.task_type_text || "")} · ${esc(info.subject || "")}
                · ${esc(Number(info.complete_count) || 0)}/${esc(Number(info.target_count) || 0)}
                · ${esc(Number(info.duration_minutes) || 0)}/${esc(Number(info.target_minutes) || 0)} 分钟</span>
            ${done || AUTO_DONE_TYPES.indexOf(info.task_type || "") >= 0 ? "" : `<button class="btn btn-primary task-complete-btn" onclick="completeTask(${Number(info.task_id) || 0})">✅ 完成这一项</button>`}
        </div>`;
}

/* 单屏可见文字块最多 3 个：标题 / 完成率与时长 / 三类配比；任务卡片是按钮，不算文字块 */
function renderTaskBlock(data) {
    const info = data || {};
    const summary = info.summary || {};
    const tasks = info.tasks || [];

    $("task-title").innerHTML = "📌 今日任务（新知识 50 / 薄弱点 30 / 复习 20）";
    $("task-summary").innerHTML = taskSummaryText(summary);
    $("task-mix").innerHTML = taskMixText(summary.mix);
    $("task-list").innerHTML = tasks.length
        ? tasks.map(taskItemHtml).join("")
        : '<p class="meta">今天还没有任务，先自由练几道题吧。</p>';
}
/* V2.8 今日题单预览：在「今天的安排」里写清楚每一项还剩多少题（3/5），
   做完的项不再出题；点「开始今天的学习」后练习页就是按这张单子统一出题的。 */
function sheetRowHtml(task) {
    const info = task || {};
    const done = taskDone(info);
    const target = Number(info.target_count) || 0;
    const complete = Number(info.complete_count) || 0;
    const remain = Math.max(0, target - complete);
    const tag = info.title || `${info.subject || ""} · ${info.task_type_text || ""}`;

    return `
        <div class="plan-sheet-item ${done ? "done" : ""}">
            <span class="plan-sheet-tag">${done ? "✅" : "📝"} ${esc(tag)}</span>
            <span class="meta">${esc(complete)}/${esc(target)} 题${done ? " · 已完成" : ` · 还差 ${esc(remain)} 题`}</span>
        </div>`;
}

function renderSheetPreview(data) {
    const box = $("plan-sheet");
    if (!box) return;

    const tasks = ((data || {}).tasks || []);
    if (!tasks.length) {
        box.innerHTML = "";
        return;
    }

    box.innerHTML = `<p class="plan-sheet-title">📝 今天的题目（一项做完就收工）</p>`
        + tasks.map(sheetRowHtml).join("");
}

/* ---------------- V2.8 积分：每日首次登录 / 每日打卡（任务全部收工自动） / 每答对一题 / 计划做完后继续练 / 任务收工 ---------------- */

let pointsState = null;
let pointsMessage = "";

/* 加分规则一行写完（分值来自后端 points.RULES，前端不写死比例） */
function pointsRuleText(rules) {
    return (rules || []).map(item => `${item.label} +${item.points}`).join(" · ");
}

function pointsShopRowHtml(item, balance) {
    const info = item || {};
    const cost = Number(info.cost) || 0;
    const gap = Math.max(0, cost - (Number(balance) || 0));
    return `
        <div class="points-shop-item">
            <span class="points-shop-label">${esc(info.emoji || "🎁")} ${esc(info.label || "")}</span>
            <span class="meta">${esc(cost)} 积分${gap ? ` · 还差 ${esc(gap)}` : " · 够啦"}</span>
        </div>`;
}

function pointsRecordLine(row) {
    const info = row || {};
    return `<li>+${esc(info.points)} ${esc(info.label || info.event || "")}`
        + ` <span class="meta">${esc(info.time || "")}</span></li>`;
}

/* 积分卡：余额 / 今日获得 / 打卡 / 怎么挣 / 商城占位道具 / 最近挣到的 */
function renderPoints(data) {
    const box = $("points-card");
    if (!box) return;

    const info = data || {};
    if (info.error) {
        box.innerHTML = `<p class="points-title">📱 我的积分</p><p class="meta">${esc(info.error)}</p>`;
        return;
    }

    const balance = Number(info.balance) || 0;
    const today = Number(info.today_points) || 0;
    const streak = Number(info.streak) || 0;
    const shop = info.shop || {};
    const items = shop.items || [];
    const records = (info.records || []).slice(0, 3);
    const checkin = info.checked_in
        ? `<span class="points-checked">✅ 今天已打卡${streak ? ` · 连续 ${esc(streak)} 天` : ""}</span>`
        : `<span class="meta">做完今天的小任务，打卡自己就来啦</span>`;

    box.innerHTML = `
        <p class="points-title">📱 我的积分</p>
        <p class="points-balance"><strong class="ph-num">${esc(balance)}</strong> 积分
            <span class="meta">今日 +${esc(today)}${streak ? ` · 连续打卡 ${esc(streak)} 天` : ""}</span></p>
        <p class="points-checkin-row">${checkin}</p>
        ${pointsMessage ? `<p class="points-tip">${esc(pointsMessage)}</p>` : ""}
        <p class="points-sub">怎么挣积分</p>
        <p class="meta points-rules">${esc(pointsRuleText(info.rules))}</p>
        <p class="points-sub">🛍️ 积分商城${shop.enabled ? "" : "（占位）"}</p>
        <div class="points-shop">${items.map(item => pointsShopRowHtml(item, balance)).join("")}</div>
        <p class="meta points-note">${esc(shop.note || "")}</p>
        ${records.length ? `<p class="points-sub">最近挣到的</p>`
            + `<ul class="points-records">${records.map(pointsRecordLine).join("")}</ul>` : ""}
        <p class="meta points-note">攒够积分和爸爸妈妈一起换（现在先攒着哦）。</p>`;
}

function loadPoints() {
    const box = $("points-card");
    if (!box) return Promise.resolve(null);

    return claimDailyLogin().then(() => jsonFetch(`${API}/api/points/${currentStudentId()}`))
        .then(data => {
            pointsState = data;
            renderPoints(data);
            return data;
        })
        .catch(err => {
            /* 积分读不出来不影响今天的任务与练习 */
            console.error("[today] 积分读不出来", err);
            box.innerHTML = "";
            return null;
        });
}

/* 每日首次登录奖励：后端幂等（一天只记一次），页面一打开就顺手领 */
function claimDailyLogin() {
    return postJson(`${API}/api/points/${currentStudentId()}/login`, {})
        .then(data => {
            if (data && data.awarded) pointsMessage = data.message || "";
            return data;
        })
        .catch(err => {
            /* 领不上不影响看积分、也不影响做今天的任务 */
            console.error("[today] 登录奖励没领上", err);
            return null;
        });
}

function loadTasks() {
    $("task-status").textContent = "⏳ 正在排今天的任务...";

    return jsonFetch(`${API}/api/tasks/today?student_id=${currentStudentId()}`)
        .then(data => {
            $("task-status").textContent = "";
            lastTaskData = data;
            renderTaskBlock(data);
            renderSheetPreview(data);
            return data;
        })
        .catch(() => {
            // 任务区块取不到不影响原有今日学习流程
            $("task-status").textContent = "";
            $("task-mix").innerHTML = "任务暂时排不出来，先照下面的计划练 ➡️";
            return null;
        });
}

function completeTask(taskId) {
    return jsonFetch(API + "/api/tasks/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            student_id: currentStudentId(),
            task_id: Number(taskId) || 0,
            done: true
        })
    })
        .then(data => {
            const info = data || {};
            const summary = info.summary || {};
            $("task-summary").innerHTML = taskSummaryText(summary);
            $("task-mix").innerHTML = taskMixText(summary.mix);
            return loadTasks();
        })
        .catch(() => {
            // 打卡失败不阻塞做题，孩子可以再点一次
            $("task-mix").innerHTML = "没记上，等一会儿再试一次～";
            return null;
        });
}

/* ---------------- 菲比联动 / 自动跳题 ---------------- */

/* 菲比反馈：答对弹表情包 + 跳跃欢呼，答错摇头 + 语音 + 字幕（模块没加载时静默跳过） */
/* V2.6 菲比收藏：每发生一次「等级提升」，左侧收藏栏就多一只菲比。
   奖励的是学习成果（真正学会一个知识的更高档位），不是在线时长，也没有随机大奖。 */
function phoebeCollect() {
    if (typeof phoebe3dCollect !== "function") return null;
    try {
        return phoebe3dCollect();
    } catch (err) {
        return null;
    }
}

function phoebeAnswerFeedback(result) {
    if (typeof phoebe3dFeedback !== "function") return;

    try {
        phoebe3dFeedback(!!(result || {}).correct, {});
    } catch (err) {
        // 庆祝/语音失败都不影响做题
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

/* ---------------- V2.6 统一学习会话：一条线跑完今天的所有微任务 ---------------- */

function sessionApi() {
    return (typeof window !== "undefined" && window.LearningSession) || null;
}

/* 答完一题报给会话：任务做够了就自动进下一个任务，全部做完就进今日完成页 */
/* 出题前先问会话：当前题型刷完了吗？刷完就自动切到下一个未完成的题型（不再出它） */
function sessionSync() {
    const s = sessionApi();
    if (!s || typeof s.syncTask !== "function") return null;
    return s.syncTask();
}

function sessionTick(correct) {
    const s = sessionApi();
    if (!s) return null;
    return s.recordAnswer(!!correct, 0);
}

function sessionArea() {
    return $("task-status") || $("plan-status");
}

/* 顶部会话进度：已完成 2/3 个小任务（孩子看得懂的进度，不是百分比） */
function renderSessionBar(progress) {
    const box = $("session-bar");
    if (!box || !progress) return;
    const s = sessionApi();
    const task = s ? s.currentTask() : null;
    const name = task
        ? `${esc(s.taskLabel(task))}${task.subject ? " · " + esc(task.subject) : ""}${task.knowledge ? " " + esc(task.knowledge) : ""}`
        : "今天的学习";
    box.classList.remove("hidden");
    box.innerHTML =
        `<p class="ph-task-sub">${name}</p>`
        + `<div class="ph-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${progress.total}" aria-valuenow="${progress.done}">`
        + `<div class="ph-progress-fill" style="width:${progress.percent}%"></div></div>`
        + `<p class="meta">已完成 ${progress.done} / ${progress.total} 个小任务</p>`;
}

/* 有限自主选择：只让孩子决定「先做哪一个」，知识点与难度仍由系统决定 */
function renderTaskChooser() {
    const s = sessionApi();
    if (!s) return "";
    const tasks = s.pendingTasks();
    if (tasks.length < 2) return "";
    return '<p class="ph-lead">今天想先做哪一个？</p>'
        + tasks.map(task =>
            `<button type="button" class="ph-btn ph-btn--secondary"`
            + ` onclick="chooseTask(${parseInt(task.task_id || 0, 10)})">`
            + `${esc(task.icon || "✅")} ${esc(s.taskLabel(task))}${task.subject ? " · " + esc(task.subject) : ""}</button>`
        ).join(" ");
}

function chooseTask(taskId) {
    const s = sessionApi();
    if (!s) return;
    s.choose(taskId);
    const area = sessionArea();
    if (area) area.innerHTML = "";
}

/* 一个任务开始：锁住这个任务的科目与知识点，然后直接出题 */
function beginTask(task) {
    const t = task || {};
    resetPractice();
    currentTask = {
        subject: t.subject || "",
        knowledge: t.knowledge || "",
        task_id: t.task_id || 0,
        task_type: t.task_type || "",
        target_count: t.target_count || 0,
        complete_count: t.complete_count || 0
    };
    $("practice").classList.remove("hidden");
    const area = sessionArea();
    if (area) area.innerHTML = "";
    loadNext();
}

/* 今日完成页（V2.6 P0）：所有任务做完后必须停在这里，不提供「再来一题」 */
function renderCompletion(summary) {
    const box = $("completion");
    if (!box) return;
    const child = (summary || {}).child || {};
    const lines = (summary || {}).lines || [];
    const items = lines.length ? lines : [
        `🌱 学会 ${child.new_learning || 0} 个新知识`,
        `🌳 巩固 ${child.review || 0} 个旧知识`,
        `⚔️ 攻克 ${child.wrong_recovery || 0} 个挑战`,
        `🧠 主动回忆 ${child.active_recall || 0} 张卡`,
        `⏱ 学习 ${child.minutes || 0} 分钟`
    ];
    box.classList.remove("hidden");
    box.innerHTML =
        '<h2 class="ph-complete-title">🎉 今天完成啦！</h2>'
        + '<p class="ph-lead">今天你：</p>'
        + '<ul class="ph-complete-list">' + items.map(text => `<li>${esc(kidText(String(text)))}</li>`).join("") + "</ul>"
        + '<p class="ph-complete-rest">🐼 菲比：今天已经完成啦，可以去休息了！</p>'
        + '<div class="ph-complete-actions">'
        + '<button type="button" class="ph-btn ph-btn--primary" onclick="closeCompletion()">完成</button>'
        + '<a class="ph-btn ph-btn--secondary" href="growth.html">看看我的成长</a></div>';
    $("practice").classList.add("hidden");
    if ($("session-bar")) $("session-bar").classList.add("hidden");
    if (box.scrollIntoView) box.scrollIntoView({ block: "start" });
}

function closeCompletion() {
    if ($("completion")) $("completion").classList.add("hidden");
    if ($("practice")) $("practice").classList.add("hidden");
    if (typeof window !== "undefined" && window.scrollTo) window.scrollTo(0, 0);
}

function initSession() {
    const s = sessionApi();
    if (!s) return;
    s.init({
        onReady: () => renderSessionBar(s.progress()),
        onTask: task => { renderSessionBar(s.progress()); beginTask(task); },
        onProgress: progress => renderSessionBar(progress),
        onFinish: summary => renderCompletion(summary),
        onReset: () => { if ($("completion")) $("completion").classList.add("hidden"); }
    });
}

/* ---------------- 读题（浏览器原生语音，失败不影响答题） ---------------- */

function speechUsable() {
    return typeof window !== "undefined" && !!window.speechSynthesis
        && typeof window.SpeechSynthesisUtterance === "function";
}

function stopReading() {
    if (!speechUsable()) return;
    try { window.speechSynthesis.cancel(); } catch (err) { /* 静默 */ }
}

function readQuestion() {
    const button = $("read-btn");
    if (!speechUsable()) {
        if (button) button.textContent = "🔊 读题（本机暂不支持）";
        return;
    }

    const q = currentQuestion || {};
    const text = String(q.question || "") + " " + ((q.options || []).join(" "));
    if (!text.trim()) return;

    const done = () => { if (button) button.textContent = "🔊 读题"; };
    try {
        const synth = window.speechSynthesis;
        // Chrome 里 cancel() 之后立刻 speak() 会被吞掉（点了没声音），所以先停、再稍后读
        let delay = 0;
        if (synth.speaking || synth.pending) {
            stopReading();
            delay = 120;
        }
        if (synth.paused && synth.resume) synth.resume();

        const utter = new window.SpeechSynthesisUtterance(text);
        utter.lang = "zh-CN";
        utter.rate = 0.85;
        utter.volume = 1;
        if (button) button.textContent = "⏹ 停止读题";
        utter.onend = done;
        utter.onerror = event => {
            done();
            console.warn("[today] 读题失败", (event && event.error) || "");
            if (button) button.textContent = "🔊 读题（本机没声音）";
        };

        const fire = () => {
            try {
                synth.speak(utter);
            } catch (err) {
                // 读题失败不影响孩子继续答题
                done();
            }
        };
        if (delay) setTimeout(fire, delay);
        else fire();
    } catch (err) {
        // 读题失败不影响孩子继续答题
        done();
    }
}

/* 提示：先给方向，不直接给答案（真正的分级提示由 V2.5 的 result.hint 提供） */
function hintTextOfResult() {
    if (!lastResult) return "";
    if (typeof hintTextOf === "function") {
        const text = hintTextOf(lastResult.hint_level || lastResult.round || 0, lastResult);
        if (text) return text;
    }
    return lastResult.hint || lastResult.hint_text || "";
}

function showHint() {
    const box = $("hint-box");
    if (!box) return;
    const levels = (typeof KidLang !== "undefined" && KidLang.HELP_LEVELS) || [];
    const text = hintTextOfResult() || levels[0] || "读一遍题目，先找出已知的数字试试～";
    box.classList.remove("hidden");
    box.innerHTML = `<p class="ph-hint-title">💡 提示</p><p class="ph-hint-body">${esc(text)}</p>`;
}

function hideHint() {
    const box = $("hint-box");
    if (!box) return;
    box.classList.add("hidden");
    box.innerHTML = "";
}

/* 底部「我做好了」：填空直接交，选择题提醒孩子点答案卡片 */
function submitAnswerFromBox() {
    const blank = $("blank-box");
    if (blank && !blank.classList.contains("hidden")) {
        submitBlank();
        return;
    }
    if (answered) return;
    const box = $("result");
    if (box) box.innerHTML = '<p class="meta">点一下你选的答案卡片，再找我哦～</p>';
}

function clearAutoNext() {
    if (autoNextTimer) {
        clearTimeout(autoNextTimer);
        autoNextTimer = null;
    }
}

/* 答对后自动进入下一题，孩子不用再点一次按钮 */
function scheduleAutoNext() {
    clearAutoNext();
    autoNextTimer = setTimeout(() => {
        autoNextTimer = null;
        const s = sessionApi();
        if (s && !s.mayContinue()) return;   // 今日任务已完成：停在这里，不再自动出题
        loadNext();
    }, AUTO_NEXT_MS);
}

function refreshPlanHead() {
    return jsonFetch(`${API}/api/learning/plan/${currentStudentId()}`)
        .then(plan => {
            $("plan-head").innerHTML = renderPlanHead(plan);
            $("plan-list").innerHTML = renderPlanList(plan);
        })
        .catch(() => {
            // 进度条刷新失败不影响继续做题
        });
}

/**
 * 自动提交学习反馈（feel 留空 = 孩子没有表态）。
 * 今日计划的完成数由这个接口推进，所以答对自动跳题前必须补一次。
 */
function sendAutoFeedback(result) {
    if (feedbackSent) return Promise.resolve(null);
    feedbackSent = true;

    const question = currentQuestion || {};
    const task = currentTask || {};

    return jsonFetch(API + "/api/learning/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            student_id: currentStudentId(),
            subject: question.subject || task.subject || "",
            knowledge: question.knowledge || task.knowledge || "",
            question_id: question.question_id || 0,
            difficulty: question.difficulty || 0,
            correct: result ? !!result.correct : null,
            feel: "",
            need_help: false,
            note: "auto"
        })
    })
        .then(data => {
            refreshPlanHead();
            return data;
        })
        .catch(() => {
            // 反馈失败不阻塞下一题
            return null;
        });
}

/* 统一出口：无论答对自动跳题还是答错后点"下一题"，都保证每题只提交一次反馈 */
function nextQuestion() {
    clearAutoNext();

    const s = sessionApi();
    if (s && !s.mayContinue()) {
        // 今日任务已完成：不能继续刷题，直接看今日完成
        if ($("feel-box")) $("feel-box").classList.add("hidden");
        return;
    }


    if (feedbackSent) {
        loadNext();
        return;
    }

    sendAutoFeedback(lastResult).then(loadNext, loadNext);
}

/* ---------------- 流程 ---------------- */

function currentStudentId() {
    return parseInt(($("student") && $("student").value) || "1", 10);
}

/* ---------------- V2.5 学习启动仪式（今日计划预览 + 一键开始，孩子不用选知识点 / 难度） ---------------- */

let dailyPlan = null;

function planVoiceText(plan) {
    const minutes = Number((plan || {}).target_minutes || (plan || {}).minutes || 0);
    const count = ((plan || {}).items || []).length;
    if (!minutes || !count) return "🐼 菲比：今天先准备好你的小任务～";
    return `🐼 菲比：今天我们用 ${minutes} 分钟完成 ${count} 个小任务。`;
}

function planItemsHtml(plan) {
    const items = (plan || {}).items || [];
    const c = uc();
    if (c && c.dailyPlanCard) {
        return c.dailyPlanCard({
            minutes: (plan || {}).target_minutes || (plan || {}).minutes || 0,
            taskCount: items.length,
            tasks: items.map(item => ({
                title: `${item.icon || "✅"} ${item.subject} · ${item.knowledge}`,
                minutes: item.minutes
            }))
        });
    }
    return items.map(item =>
        `<div class="plan-item"><span>${esc(item.icon || "✅")} ${esc(item.subject)} · ${esc(item.knowledge)}</span>`
        + `<span class="meta"> ${esc(item.minutes)} 分钟</span></div>`).join("");
}

function postJson(url, payload) {
    return jsonFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
}

function loadDailyPlan() {
    const sid = $("student").value;
    if (!sid) return;
    jsonFetch(`${API}/api/tasks/plan/${sid}`)
        .then(plan => {
            dailyPlan = plan;
            const greeting = planVoiceText(plan);
            if ($("phoebe-greeting")) $("phoebe-greeting").textContent = greeting;
            $("plan-voice").textContent = "📋 今天的安排";
            $("plan-preview").innerHTML = planItemsHtml(plan);
            const notes = (plan.adjust || []).map(text => `· ${esc(kidText(text))}`).join(" ");
            $("plan-status").innerHTML = notes ? `<p class="meta">安排理由：${notes}</p>` : "";
        })
        .catch(err => {
            console.error("[today] 今日计划加载失败", err);
            $("plan-status").innerHTML = errorHtml("菲比刚刚没拿到今天的安排，我们再试一次。", "loadDailyPlan");
        });
}

function startToday() {
    const sid = $("student").value;
    if (!sid) return;

    // V2.6 需求：点「开始今天的学习」→ **新标签页**直接刷题（本页不再把题目展开在下方）。
    // 练习页带着 from=today&autostart=1 打开，会自动出“第一个未完成的小任务”的题，
    // 做完由 /submit 自动标记该项完成（无需手动点「完成这一项」）。
    const openPractice = data => {
        const pending = ((data || {}).tasks || []).filter(item => !taskDone(item))[0];
        if (!pending) {
            $("plan-status").textContent = "今天的学习已经完成啦，可以去休息了～";
            return;
        }
        // V2.8：剩下的题由练习页按题型统一出，这里只负责带 sheet=1 打开
        const url = practiceJumpUrl(pending.subject || "数学", pending.knowledge || "", true);
        if (typeof window !== "undefined" && typeof window.open === "function") {
            window.open(url, "_blank");
            $("plan-status").textContent = "已经在新页面打开今天的练习啦，做完会自动记好～";
            return;
        }
        location.href = url;            // 弹窗被浏览器拦住时退回整页跳转
    };

    if (lastTaskData) {
        openPractice(lastTaskData);
        return;
    }
    loadTasks().then(openPractice);
}

function init() {
    initSession();
    initPhoebeVoice();

    jsonFetch(API + "/students")
        .then(list => {
            studentList = list;
            $("student").innerHTML = list.map(item =>
                `<option value="${item.id}">${esc(item.name)}（${esc(item.grade_text)}）</option>`
            ).join("");

            let saved = null;
            try {
                saved = localStorage.getItem(STUDENT_KEY);
            } catch (err) {
                saved = null;
            }
            /* 共享层是当前学生的唯一真相源，能读到时以它为准 */
            if (window.UIShell && UIShell.getStudentId) {
                const uid = UIShell.getStudentId();
                if (uid && list.some(item => String(item.id) === String(uid))) saved = uid;
            }
            if (saved && list.some(item => String(item.id) === String(saved))) {
                $("student").value = saved;
            }

            renderStudentPicker();
            updateWho();
            bindStudentChange();

            loadTasks();
            loadPlan();
            loadDailyPlan();
            loadPoints();
        })
        .catch(err => {
            console.error("[today] 无法连接后端", err);
            $("status").innerHTML = errorHtml("菲比现在连不上服务器，我们等一会儿再试。", "init")
                + `<p class="meta">请先启动后端：双击 start.bat</p>`;
        });
}

/* 在别的入口（顶部「切换学习者」）改了学生时，本页要跟着刷新 */
function bindStudentChange() {
    if (!window.UIShell || !UIShell.onStudentChange) return;
    UIShell.onStudentChange(function (id) {
        if ($("student")) $("student").value = String(id);
        updateWho();
        resetPractice();
        loadTasks();
        loadPlan();
        loadDailyPlan();
        loadPoints();
    });
    UIShell.onStudentChange(function () {
        // 切换学生：会话状态立即清空，绝不残留上一个孩子的数据
        if (sessionApi()) sessionApi().reset();
        if ($("session-bar")) $("session-bar").classList.add("hidden");
        if ($("completion")) $("completion").classList.add("hidden");
    });
}

function onStudentChange() {
    try {
        localStorage.setItem(STUDENT_KEY, $("student").value);
    } catch (err) {
        // 隐私模式下不记忆选择，不影响使用
    }
    updateWho();
    resetPractice();
    loadTasks();
    loadPlan();
    loadDailyPlan();
    loadPoints();
}

function resetPractice() {
    clearAutoNext();
    currentTask = null;
    currentQuestion = null;
    answered = false;
    lastResult = null;
    feedbackSent = false;
    $("practice").classList.add("hidden");
    wrongRound = 0;
    $("question").innerHTML = "";
    $("options").innerHTML = "";
    $("result").innerHTML = "";
    $("adaptive-badge").innerHTML = "";
    $("feel-box").innerHTML = "";
    $("feel-box").classList.add("hidden");
}

function loadPlan() {
    $("status").innerHTML = loadingHtml("菲比正在安排今天的学习……");

    jsonFetch(`${API}/api/learning/plan/${currentStudentId()}`)
        .then(plan => {
            $("plan-head").innerHTML = renderPlanHead(plan);
            $("plan-list").innerHTML = renderPlanList(plan);
            $("status").textContent = "";
            return loadWhy();
        })
        .catch(err => {
            console.error("[today] 加载今日计划失败", err);
            $("status").innerHTML = errorHtml("菲比刚刚没拿到今天的学习计划，我们再试一次。", "loadPlan");
        });
}

function loadWhy() {
    return jsonFetch(`${API}/api/learning/strategy-log/${currentStudentId()}?limit=3`)
        .then(logs => {
            $("why").innerHTML = renderWhy(logs);
            $("why").classList.toggle("hidden", !$("why").innerHTML);
        })
        .catch(() => {
            // 日志只是"解释给家长听"，取不到不影响孩子学习
        });
}

/* 开始今日学习：整页跳到自由练习页答题（题目不再堆在本页下方）

   带过去的参数：
     student_id / subject / knowledge —— 练习页直接锁定这个学生与知识点
     from=today + autostart=1          —— 练习页自动出第一题
   本页不调 /api/learning/start：计划和进度仍由 /api/learning/plan 与
   /api/learning/feedback 维护，练习页用同一个 student_id 写 answer_records。 */
function practiceJumpUrl(subject, knowledge, withSheet) {
    const params = new URLSearchParams({
        student_id: String(currentStudentId()),
        subject: subject || "",
        knowledge: knowledge || "",
        from: "today",
        autostart: "1"
    });
    // V2.8 题单模式：练习页先读「今天还剩多少题、都是什么题型」再统一出题
    // （每页仍然只显示一道题，一道题带一个内部标记，做完一项就跳过它）
    if (withSheet) params.set("sheet", "1");
    return "index.html?" + params.toString();
}

function startTask(subject, knowledge) {
    location.href = practiceJumpUrl(subject, knowledge);
}

function loadNext() {
    // V2.6：出题前先确认「当前题型还没刷完」；刷完了就自动切到下一个未完成的题型，
    // 绝不再出已经刷完的那种题型（一门学科全刷完就直接进下一科）
    const sync = sessionSync();
    if (sync && !sync.continue) return;   // 今天都做完了：今日完成页会接住
    if (sync && sync.changed) return;     // 已切到新题型：onTask → beginTask 会重新出题

    const task = currentTask || {};
    const subject = task.subject || "数学";

    clearAutoNext();
    answered = false;
    feedbackSent = false;
    lastResult = null;
    wrongRound = 0;
    $("result").innerHTML = "";
    $("feel-box").innerHTML = "";
    $("feel-box").classList.add("hidden");
    $("question").innerHTML = loadingHtml("菲比正在准备一道适合你的题……");
    $("options").innerHTML = "";
    $("blank-box").classList.add("hidden");
    hideHint();

    // 同一个知识点刚练过就不锁定它（交给后端选择器换一个），避免一种题连着出好几道
    const params = new URLSearchParams({
        student_id: String(currentStudentId()),
        subject: subject,
        qtype: "choice",
        avoid: recentKnowledge.join(",")
    });

    if (knowledgeLocked(task.knowledge)) {
        params.set("knowledge", task.knowledge || "");
    }

    jsonFetch(API + "/api/learning/next-question?" + params.toString())
        .then(data => {
            currentQuestion = data;
            noteKnowledge(data.knowledge || task.knowledge || "");
            renderQuestion(data);
        })
        .catch(err => {
            console.error("[today] 出题失败", err);
            $("question").innerHTML = errorHtml("菲比刚刚没拿到题目，我们再试一次。", "loadNext");
        });
}

function submitBlank() {
    const value = $("blank-input").value.trim();
    if (!value) {
        $("result").innerHTML = '<p class="meta">先写上答案，再点「我做好了」哦～</p>';
        return;
    }
    submitAnswer(value, null);
}

function submitAnswer(value, btn) {
    if (!currentQuestion || answered) return;

    answered = true;
    $("blank-input").disabled = true;
    document.querySelectorAll(".option").forEach(item => { item.disabled = true; });

    jsonFetch(API + "/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            question_id: currentQuestion.question_id,
            answer: value,
            student_id: currentStudentId()
        })
    })
        .then(result => {
            if (btn) {
                btn.classList.add(result.correct ? "right" : "wrong");
                btn.classList.add(result.correct ? "is-right" : "is-wrong");
            }
            if (!result.correct && result.correct_answer) {
                const right = document.querySelector(`.option[data-key="${result.correct_answer}"]`);
                if (right) right.classList.add("right", "is-right");
            }
            lastResult = result;
            feedbackSent = false;
            renderResult(result);
            phoebeAnswerFeedback(result);
            sessionTick(result.correct);
            hideHint();

            if (result.correct) {
                // 答对：先提交反馈（推进今日计划），再自动进入下一题
                sendAutoFeedback(result);
                scheduleAutoNext();
            } else {
                // 答错：留在解析页，让孩子自己决定什么时候继续
                renderFeelPrompt();
            }
        })
        .catch(err => {
            answered = false;
            $("blank-input").disabled = false;
            document.querySelectorAll(".option").forEach(item => { item.disabled = false; });
            console.error("[today] 提交失败", err);
            $("result").innerHTML = '<p class="meta">😕 菲比刚刚没收到你的答案，我们再试一次。</p>';
        });
}

function sendFeedback(feel, needHelp) {
    if (feedbackSent) {
        // 这题已经自动提交过反馈（例如答对后自动跳题），不重复计数
        $("feel-box").innerHTML = `
            <p class="feel-title">这题已经记下啦</p>
            <button class="mode-btn" onclick="nextQuestion()">下一题 ➡️</button>`;
        $("feel-box").classList.remove("hidden");
        return;
    }

    feedbackSent = true;

    const question = currentQuestion || {};
    const task = currentTask || {};

    jsonFetch(API + "/api/learning/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            student_id: currentStudentId(),
            subject: question.subject || task.subject || "",
            knowledge: question.knowledge || task.knowledge || "",
            question_id: question.question_id || 0,
            difficulty: question.difficulty || 0,
            correct: lastResult ? !!lastResult.correct : null,
            feel: feel || "",
            need_help: !!needHelp
        })
    })
        .then(data => {
            renderFeedback(data);
            // 反馈会推进今日计划的完成数，顺手刷新一下进度
            refreshPlanHead();
        })
        .catch(err => {
            feedbackSent = false;
            console.error("[today] 感受提交失败", err);
            $("feel-box").innerHTML = `<p class="meta">😕 菲比刚刚没记下你的感受，不过没关系，继续加油～</p>
                <button class="mode-btn" onclick="nextQuestion()">下一题 ➡️</button>`;
        });
}

init();
