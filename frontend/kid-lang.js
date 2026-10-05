// ==============================================================
// 能力契约｜儿童化语言映射（知识状态 / 复习 / 答错帮助 / 鼓励），全站唯一实现
// 入口：KidLang.statusOf / statusLabel / forgettingText / noReviewText /
//       noWrongText / upgradeText / wrongFeedback / encourage
// 依赖：无（零构建，不依赖其他脚本）
// 不负责：DOM 渲染 → ui-components.js；学生状态 → ui-shell.js
// 验证：node frontend/verify_ui_shell.js
// 被调用：所有儿童端页面（**必须先于业务 js 加载**）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 把后台算法指标翻译成 1-6 年级孩子看得懂的话。
 *
 * 儿童端**不允许**出现 Mastery / Stability / Forgetting Risk / 掌握度 / 稳定性 /
 * 遗忘风险。所有需要表达"学到什么程度"的地方，一律走本文件。
 *
 * 用法：<script src="kid-lang.js"></script>，然后 KidLang.statusOf(76).label
 */

(function (root) {
    "use strict";

    // 五档知识状态。图标互不复用（🌿 与 🍀 必须可区分），
    // 因为状态不能只靠颜色表达 —— 颜色 + 图标 + 文字三重表达。
    var LEVELS = [
        { key: "solid", icon: "⭐", label: "记得很牢", tone: "solid", min: 90 },
        { key: "mastered", icon: "🌳", label: "已经掌握", tone: "success", min: 75 },
        { key: "basic", icon: "🍀", label: "基本会了", tone: "success-soft", min: 55 },
        { key: "learning", icon: "🌿", label: "正在学习", tone: "warning", min: 30 },
        { key: "sprout", icon: "🌱", label: "刚开始", tone: "neutral", min: -Infinity }
    ];

    var UNKNOWN = { key: "sprout", icon: "🌱", label: "还没开始学", tone: "neutral" };

    function copy(src) {
        return { key: src.key, icon: src.icon, label: src.label, tone: src.tone };
    }

    // 掌握度 -> 儿童化状态。非数字（null/undefined/""/NaN）返回"还没开始学"。
    function statusOf(mastery) {
        if (mastery === null || mastery === undefined || mastery === "") return copy(UNKNOWN);
        var n = typeof mastery === "number" ? mastery : parseFloat(mastery);
        if (isNaN(n)) return copy(UNKNOWN);
        for (var i = 0; i < LEVELS.length; i++) {
            if (n >= LEVELS[i].min) return copy(LEVELS[i]);
        }
        return copy(LEVELS[LEVELS.length - 1]);
    }

    function statusLabel(mastery) {
        var st = statusOf(mastery);
        return st.icon + " " + st.label;
    }

    function noReviewText() {
        return "🌳 今天没有知识需要复习。";
    }

    function noWrongText() {
        return "🎉 暂时没有需要攻克的错题！";
    }

    // 「今天有 3 个知识需要照顾。」—— 不说遗忘风险。
    function forgettingText(count) {
        var n = parseInt(count, 10);
        if (isNaN(n) || n <= 0) return noReviewText();
        return "🌱 今天有 " + n + " 个知识需要照顾。";
    }

    // 升级文案：「🌿 → 🌳　这个知识记得更牢啦！」
    function upgradeText(from, to, name) {
        var f = (from && from.icon) ? from.icon : UNKNOWN.icon;
        var t = (to && to.icon) ? to.icon : UNKNOWN.icon;
        var head = name ? "「" + name + "」" : "";
        return f + " → " + t + "\u3000" + head + "这个知识记得更牢啦！";
    }

    // 五档高低：sprout < learning < basic < mastered < solid。
    // 只有档位**上升**才算重要成长，才允许更明显的动画（用户简报 §14）。
    var RANK = { sprout: 0, learning: 1, basic: 2, mastered: 3, solid: 4 };

    function rankOf(key) {
        return Object.prototype.hasOwnProperty.call(RANK, key) ? RANK[key] : 0;
    }

    // 判断这次是不是「升级了」。prevKey 为空表示第一次见到这个知识点，不算升级。
    function isUpgrade(prevKey, nextKey) {
        if (!prevKey || !nextKey) return false;
        return rankOf(nextKey) > rankOf(prevKey);
    }

    // 答错后逐级增加帮助：方向 -> 条件 -> 步骤 -> 完整讲解。
    // 表现为「菲比在帮助我」，不是「系统在处罚我」。
    var HELP_LEVELS = ["方向提示", "关键条件", "步骤提示", "完整讲解"];

    function wrongFeedback(round) {
        var r = parseInt(round, 10);
        if (isNaN(r) || r < 1) r = 1;
        if (r > HELP_LEVELS.length) r = HELP_LEVELS.length;
        return {
            title: "🤔 这里再想一下",
            level: HELP_LEVELS[r - 1],
            round: r,
            retryLabel: "我再试试"
        };
    }

    // 固定鼓励表：按下标取，禁止 Math.random()
    //（随机奖励属于用户明令禁止的"赌博式奖励"）。
    var ENCOURAGE = [
        "加油，你可以的！",
        "再想一想，菲比陪着你。",
        "慢慢来，做对一题就很好。",
        "你比刚才更熟练啦！",
        "再试一次，这次一定行。"
    ];

    function encourage(seed) {
        var i = Math.abs(parseInt(seed, 10));
        if (isNaN(i)) i = 0;
        return ENCOURAGE[i % ENCOURAGE.length];
    }

    root.KidLang = {
        LEVELS: LEVELS,
        HELP_LEVELS: HELP_LEVELS,
        statusOf: statusOf,
        statusLabel: statusLabel,
        noReviewText: noReviewText,
        noWrongText: noWrongText,
        forgettingText: forgettingText,
        upgradeText: upgradeText,
        rankOf: rankOf,
        isUpgrade: isUpgrade,
        wrongFeedback: wrongFeedback,
        encourage: encourage
    };
})(typeof window !== "undefined" ? window : this);
