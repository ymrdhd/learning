// ==============================================================
// 能力契约｜儿童端公共 UI 组件（只输出 HTML 字符串，不绑定事件）
// 入口：UIComponents.esc / progressBar / emptyState / loadingState / errorState /
//       hintPanel / questionCard / answerOption / taskCard / dailyPlanCard /
//       knowledgeStatus / knowledgeMap / growthSummary / wrongQuestionCard /
//       completionCard
// 依赖：KidLang（知识状态文案；缺失时保守降级）
// 不负责：事件绑定 → 调用页用 data-action / data-index 做事件委托
// 验证：node frontend/verify_ui_shell.js
// 被调用：所有儿童端页面（**必须先于业务 js 加载**）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 组件一律返回 HTML 字符串，由调用页决定挂到哪里、怎么交互。
 * 这样避免"多个页面复制同一段 HTML"，又不需要引入任何框架。
 *
 * 约定：
 *   - 所有外部文本经 esc() 转义后再拼进 HTML
 *   - 交互入口用 data-action（speak / retry / growth …）与 data-index
 *   - 状态不只靠颜色：图标 + 文字 + 颜色三重表达
 *   - 面向儿童的文案里不出现算法指标、HTTP 状态码
 */

(function (root) {
    "use strict";

    function esc(s) {
        return String(s === undefined || s === null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function pick(value, fallback) {
        return (value === undefined || value === null || value === "") ? fallback : value;
    }

    function escapeAll(list) {
        return (Array.isArray(list) ? list : []).map(esc);
    }

    function kidLang() {
        return root.KidLang || null;
    }

    function fallbackStatus() {
        return { key: "sprout", icon: "🌱", label: "刚开始", tone: "neutral" };
    }

    /* ---------------- 进度 ---------------- */

    function progressBar(opt) {
        opt = opt || {};
        var value = Number(opt.value) || 0;
        var max = Number(opt.max) || 0;
        var pct = max > 0 ? Math.max(0, Math.min(100, Math.round(value / max * 100))) : 0;
        var label = pick(opt.label, max > 0 ? value + " / " + max : String(value));
        return '<div class="ph-progress" role="progressbar"'
            + ' aria-valuemin="0" aria-valuemax="' + esc(max) + '" aria-valuenow="' + esc(value) + '"'
            + ' aria-label="' + esc(label) + '">'
            + '<div class="ph-progress-fill" style="width:' + pct + '%"></div></div>'
            + '<div class="ph-progress-text ph-num">' + esc(label) + '</div>';
    }

    /* ---------------- 空 / Loading / Error ---------------- */

    function emptyState(opt) {
        opt = opt || {};
        return '<div class="ph-state ph-state--empty">'
            + '<span class="ph-state-icon" aria-hidden="true">' + esc(pick(opt.icon, "🙂")) + '</span>'
            + '<p class="ph-state-title">' + esc(pick(opt.title, "")) + '</p>'
            + (opt.hint ? '<p class="ph-state-hint">' + esc(opt.hint) + '</p>' : "")
            + '</div>';
    }

    function loadingState(opt) {
        opt = opt || {};
        var text = pick(opt.text, "菲比正在准备一道适合你的题……");
        return '<div class="ph-state ph-state--loading" role="status" aria-live="polite">'
            + '<span class="ph-state-icon ph-breathe" aria-hidden="true">🐳</span>'
            + '<p class="ph-state-title">' + esc(text) + '</p>'
            + (opt.hint ? '<p class="ph-state-hint">' + esc(opt.hint) + '</p>' : "")
            + '</div>';
    }

    function errorState(opt) {
        opt = opt || {};
        var title = pick(opt.title, "菲比刚刚没拿到题目，我们再试一次。");
        var retryLabel = pick(opt.retryLabel, "再试一次");
        // 重试动作由调用页传入，组件本身不绑事件（保持"只输出 HTML"）
        var action = opt.retryAction ? ' onclick="' + esc(opt.retryAction) + '"' : "";
        return '<div class="ph-state ph-state--error" role="alert">'
            + '<span class="ph-state-icon" aria-hidden="true">🐳</span>'
            + '<p class="ph-state-title">' + esc(title) + '</p>'
            + '<button type="button" class="ph-btn ph-btn--primary" data-action="retry"' + action + '>'
            + esc(retryLabel) + '</button></div>';
    }

    /* ---------------- 提示（答错逐级帮助） ---------------- */

    function hintPanel(opt) {
        opt = opt || {};
        return '<div class="ph-hint ph-card" data-level="' + esc(pick(opt.level, "")) + '">'
            + '<p class="ph-hint-title">' + esc(pick(opt.title, "🤔 这里再想一下"))
            + (opt.level ? '<span class="ph-hint-level">' + esc(opt.level) + '</span>' : "") + '</p>'
            + (opt.body ? '<p class="ph-hint-body">' + esc(opt.body) + '</p>' : "")
            + '<button type="button" class="ph-btn ph-btn--secondary" data-action="retry">'
            + esc(pick(opt.retryLabel, "我再试试")) + '</button></div>';
    }

    /* ---------------- 题卡 ---------------- */

    function questionCard(opt) {
        opt = opt || {};
        var subject = pick(opt.subject, "");
        var knowledge = pick(opt.knowledge, "");
        var total = Number(opt.total) || 0;
        var head = '<div class="ph-qhead">'
            + '<span class="ph-qsubject">' + esc(subject)
            + (knowledge ? ' · ' + esc(knowledge) : "") + '</span>'
            + (total > 0 ? '<span class="ph-qindex ph-num">' + esc((Number(opt.index) || 0) + " / " + total) + '</span>' : "")
            + '</div>';
        var speak = opt.canSpeak === false ? ""
            : '<button type="button" class="ph-btn ph-btn--speak" data-speaking="0" data-action="speak"'
                + (opt.speakAction ? ' onclick="' + esc(opt.speakAction) + '"' : "")
                + '>🔊 读题目</button>';
        return '<section class="ph-question ph-card">' + head
            + '<p class="ph-qtext">' + esc(pick(opt.question, "")) + '</p>'
            + speak + '</section>';
    }

    function answerOption(opt) {
        opt = opt || {};
        var state = pick(opt.state, "idle");
        var cls = "ph-option" + (state === "idle" ? "" : " is-" + state);
        var aria = state === "right" ? ' aria-label="答对了"'
            : (state === "wrong" ? ' aria-label="再想一想"' : '');
        return '<button type="button" class="' + esc(cls) + '"'
            + ' data-index="' + esc(opt.index) + '"' + aria + '>'
            + esc(pick(opt.text, "")) + '</button>';
    }

    /* ---------------- 今日计划 ---------------- */

    function taskCard(opt) {
        opt = opt || {};
        return '<div class="ph-card ph-card--task' + (opt.done ? " is-done" : "") + '">'
            + '<div class="ph-task-main">'
            + '<span class="ph-task-title">' + esc(pick(opt.title, "")) + '</span>'
            + (opt.subtitle ? '<span class="ph-task-sub">' + esc(opt.subtitle) + '</span>' : "")
            + '</div>'
            + '<span class="ph-task-min ph-num">' + esc(pick(opt.minutes, 0)) + ' 分钟</span>'
            + '</div>';
    }

    function dailyPlanCard(opt) {
        opt = opt || {};
        var tasks = Array.isArray(opt.tasks) ? opt.tasks : [];
        var list = tasks.map(function (t) {
            return '<li class="ph-plan-item">'
                + '<span class="ph-plan-item-title">' + esc(pick(t.title, "")) + '</span>'
                + (t.minutes ? '<span class="ph-plan-item-min ph-num">' + esc(t.minutes) + ' 分钟</span>' : "")
                + '</li>';
        }).join("");
        return '<div class="ph-card ph-plan-card">'
            + (opt.greeting ? '<p class="ph-greeting">' + esc(opt.greeting) + '</p>' : "")
            + '<p class="ph-plan-sum">今天我们用 ' + esc(pick(opt.minutes, 0)) + ' 分钟完成 '
            + esc(pick(opt.taskCount, tasks.length)) + ' 个小任务。</p>'
            + (list ? '<ul class="ph-plan-list">' + list + '</ul>' : "")
            + '</div>';
    }

    /* ---------------- 知识状态与知识地图 ---------------- */

    function knowledgeStatus(opt) {
        opt = opt || {};
        var lang = kidLang();
        var st = lang ? lang.statusOf(opt.mastery) : fallbackStatus();
        if (opt.compact) {
            return '<span class="ph-status-dot" data-status="' + esc(st.key) + '">'
                + '<span aria-hidden="true">' + esc(st.icon) + '</span>' + esc(st.label) + '</span>';
        }
        return '<span class="ph-status ph-status--' + esc(st.key) + '">'
            + '<span class="ph-status-icon" aria-hidden="true">' + esc(st.icon) + '</span>'
            + '<span class="ph-status-label">' + esc(st.label) + '</span></span>';
    }

    function knowledgeMap(opt) {
        opt = opt || {};
        var domains = Array.isArray(opt.domains) ? opt.domains : [];
        var html = domains.map(function (d) {
            var name = pick(d.name, "");
            return '<button type="button" class="ph-tile" data-domain="' + esc(pick(d.key, name)) + '">'
                + '<span class="ph-tile-icon" aria-hidden="true">' + esc(pick(d.icon, "🌱")) + '</span>'
                + '<span class="ph-tile-name">' + esc(name) + '</span>'
                + '<span class="ph-tile-count ph-num">' + esc(pick(d.count, 0)) + ' 个知识</span>'
                + '</button>';
        }).join("");
        return '<div class="ph-map">' + html + '</div>';
    }

    /* ---------------- 成长与完成 ---------------- */

    function growthSummary(opt) {
        opt = opt || {};
        var rows = (Array.isArray(opt.rows) && opt.rows.length) ? opt.rows : [
            { icon: "📅", label: "本周学习", value: pick(opt.days, 0), unit: "天" },
            { icon: "🌳", label: "新掌握", value: pick(opt.newMastered, 0), unit: "个知识" },
            { icon: "⚔️", label: "攻克错题", value: pick(opt.wrongFixed, 0), unit: "道" },
            { icon: "🍀", label: "巩固成功", value: pick(opt.consolidated, 0), unit: "个知识" }
        ];
        var list = rows.map(function (row) {
            return '<li><span aria-hidden="true">' + esc(pick(row.icon, "")) + '</span>'
                + esc(pick(row.label, "")) + ' <b class="ph-num">' + esc(pick(row.value, 0))
                + '</b> ' + esc(pick(row.unit, "")) + '</li>';
        }).join("");
        return '<div class="ph-card ph-growth">'
            + '<p class="ph-growth-title">' + esc(pick(opt.title, "我最近变强了吗？")) + '</p>'
            + '<ul class="ph-growth-list">' + list + '</ul></div>';
    }

    function completionCard(opt) {
        opt = opt || {};
        var items = escapeAll(opt.items);
        var list = items.map(function (t) { return '<li>' + t + '</li>'; }).join("");
        var title = opt.title === undefined ? "🎉 今天完成啦！" : opt.title;
        var rest = opt.restLabel === undefined ? "今天可以休息啦！" : opt.restLabel;
        return '<div class="ph-card ph-complete">'
            + (title ? '<p class="ph-complete-title">' + esc(title) + '</p>' : "")
            + (list ? '<ul class="ph-complete-list">' + list + '</ul>' : "")
            + (rest ? '<p class="ph-complete-rest">' + esc(rest) + '</p>' : "")
            + '<button type="button" class="ph-btn ph-btn--primary" data-action="growth">'
            + esc(pick(opt.primaryLabel, "查看我的成长")) + '</button></div>';
    }

    /* ---------------- 错题卡 ---------------- */

    var WRONG_STATUS = {
        todo: { icon: "🔴", label: "待攻克" },
        training: { icon: "🟡", label: "训练中" },
        cleared: { icon: "🟢", label: "已攻克" }
    };

    function wrongQuestionCard(opt) {
        opt = opt || {};
        var key = pick(opt.statusKey, "todo");
        var st = WRONG_STATUS[key] || WRONG_STATUS.todo;
        return '<button type="button" class="ph-card ph-wrong" data-status="' + esc(key) + '">'
            + '<span class="ph-wrong-title">' + esc(pick(opt.title, "")) + '</span>'
            + '<span class="ph-wrong-status">' + esc(st.icon + " " + st.label) + '</span>'
            + '</button>';
    }

    root.UIComponents = {
        esc: esc,
        WRONG_STATUS: WRONG_STATUS,
        progressBar: progressBar,
        emptyState: emptyState,
        loadingState: loadingState,
        errorState: errorState,
        hintPanel: hintPanel,
        questionCard: questionCard,
        answerOption: answerOption,
        taskCard: taskCard,
        dailyPlanCard: dailyPlanCard,
        knowledgeStatus: knowledgeStatus,
        knowledgeMap: knowledgeMap,
        growthSummary: growthSummary,
        completionCard: completionCard,
        wrongQuestionCard: wrongQuestionCard
    };
})(typeof window !== "undefined" ? window : this);
