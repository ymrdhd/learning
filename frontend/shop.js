// ==============================================================
// 能力契约｜页面：积分商城（商品 + 积分明细 + 我的积分流水）
// 入口：init / loadShop / claimDailyLogin / toggleStudentPicker / renderBalance /
//       renderGoods / renderRewards / renderRecords / starsText / pointsText
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js；
//       GET /students、GET /api/points/{sid}、POST /api/points/{sid}/login（每日首次登录奖励）
// 不负责：分值口径 → backend/points_rewards.py（第一版奖励行为表，唯一真相）；
//         加分的判定与账本 → backend/points.py；真实兑换（比例先占位，不实装）
// 验证：node frontend/verify_shop_web.js
// 被调用：shop.html
// 索引：docs/MODULE_MAP.md
// ==============================================================

// 商城页只回答两件事：「我现在有多少积分、能换什么？」和「分是怎么挣来的？」
// 商品与明细全部来自后端（points_rewards.REWARDS / points.SHOP_ITEMS），前端不写死分值。

var STUDENT_KEY = "xiaozhi.student";
var API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin : "http://127.0.0.1:8000";

var students = [];
var shopMessage = "";

function $(id) { return document.getElementById(id); }
function uc() { return (typeof UIComponents !== "undefined") ? UIComponents : null; }
function shell() { return (typeof UIShell !== "undefined") ? UIShell : null; }

function esc(text) {
    return String(text === undefined || text === null ? "" : text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function jsonFetch(url, options) {
    return fetch(url, options).then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
    });
}

function postJson(url, payload) {
    return jsonFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
}

function loadingHtml(text) {
    var c = uc();
    return c ? c.loadingState({ text: text })
        : '<div class="ph-state ph-state--loading"><p class="ph-state-title">' + esc(text) + '</p></div>';
}

function errorHtml(title, handlerName) {
    var c = uc();
    return c ? c.errorState({ title: title, retryAction: handlerName + "()" })
        : '<div class="ph-state ph-state--error"><p class="ph-state-title">' + esc(title) + '</p>'
            + '<button type="button" class="ph-btn ph-btn--primary" onclick="' + esc(handlerName) + '()">再试一次</button></div>';
}

function num(value) {
    var n = parseInt(value, 10);
    return isNaN(n) ? 0 : n;
}

function currentStudentId() {
    var s = shell();
    if (s && s.getStudentId) return s.getStudentId();
    try { return localStorage.getItem(STUDENT_KEY) || "1"; } catch (err) { return "1"; }
}

/* ---------------- 渲染（纯函数，便于验证） ---------------- */

// ★n + ☆补足到 5；0 星（屏幕时间那类）给一条横线，不假装有星
function starsText(stars) {
    var n = num(stars);
    if (n <= 0) return "—";
    if (n > 5) n = 5;
    return new Array(n + 1).join("★") + new Array(6 - n).join("☆");
}

// 分值文案：单点 / 区间 / 零分（分值全部由后端给，前端只排版）
function pointsText(item) {
    var info = item || {};
    var low = num(info.points_min);
    var high = num(info.points_max);
    if (low === 0 && high === 0) return "0 分";
    if (low === high) return "+" + low;
    return "+" + low + "~" + high;
}

function stateText(states, state) {
    var map = states || {};
    return map[state] || "";
}

function rewardRowHtml(item, states) {
    var info = item || {};
    var state = info.state || "planned";
    return '<li class="points-row" data-state="' + esc(state) + '">'
        + '<span class="points-row-head">'
        + '<span class="points-row-star" aria-hidden="true">' + esc(starsText(info.stars)) + '</span>'
        + '<span class="points-row-label">' + esc(info.label || "") + '</span>'
        + '<span class="points-row-points ph-num">' + esc(pointsText(info)) + '</span></span>'
        + '<span class="points-row-note">' + esc(info.note || "") + '</span>'
        + '<span class="points-row-state">' + esc(stateText(states, state)) + '</span></li>';
}

function renderRewards(data) {
    data = data || {};
    var items = Array.isArray(data.rewards) ? data.rewards : [];
    if (!items.length) {
        return uc() ? uc().emptyState({ icon: "📒", title: "积分明细还没准备好", hint: "过一会儿再来看看。" })
            : '<p class="ph-lead">积分明细还没准备好。</p>';
    }
    var states = data.reward_states || {};
    return '<ul class="points-rows">' + items.map(function (item) {
        return rewardRowHtml(item, states);
    }).join("") + '</ul>'
        + '<p class="points-note">规则版本：' + esc(data.reward_version || "第一版")
        + ' · 带 ✅ 的已经在自动记分，带 🔜 的先把规则告诉你，判定接上就会开始记。</p>';
}

function goodsRowHtml(item, balance) {
    var info = item || {};
    var cost = num(info.cost);
    var left = cost - num(balance);
    var gap = left > 0 ? ("还差 " + left + " 分") : "已经攒够啦";
    return '<li class="shop-item">'
        + '<span class="shop-item-label">' + esc(info.emoji || "🎁") + " " + esc(info.label || "") + '</span>'
        + '<span class="shop-item-cost ph-num">' + esc(cost) + ' 积分</span>'
        + '<span class="shop-item-gap">' + esc(gap)
        + (info.note ? ' · ' + esc(info.note) : "") + '</span></li>';
}

function renderGoods(data) {
    data = data || {};
    var shop = data.shop || {};
    var items = Array.isArray(shop.items) ? shop.items : [];
    if (!items.length) return '<p class="ph-lead">商城还在上架，过一会儿再来看看。</p>';
    return '<ul class="shop-items">' + items.map(function (item) {
        return goodsRowHtml(item, data.balance);
    }).join("") + '</ul>';
}

function recordLine(row) {
    var info = row || {};
    return '<li class="points-record">'
        + '<span class="points-record-main">+' + esc(num(info.points)) + " "
        + esc(info.label || info.event || "") + '</span>'
        + (info.note ? '<span class="points-record-note">' + esc(info.note) + '</span>' : "")
        + '<span class="points-record-time ph-num">' + esc(info.time || "") + '</span></li>';
}

function renderRecords(data) {
    data = data || {};
    var records = Array.isArray(data.records) ? data.records : [];
    if (!records.length) {
        return uc() ? uc().emptyState({ icon: "🧾", title: "还没有挣到积分的记录", hint: "做对一题就开始有啦。" })
            : '<p class="ph-lead">还没有挣到积分的记录。</p>';
    }
    return '<ul class="points-records">' + records.map(recordLine).join("") + '</ul>';
}

// 余额卡：余额 / 今日获得 / 打卡 / 连续天数 + 「现在正在记的日常分」（后端 RULES）
function renderBalance(data) {
    data = data || {};
    var balance = num(data.balance);
    var today = num(data.today_points);
    var streak = num(data.streak);
    var checkin = data.checked_in
        ? '<span class="points-checked">✅ 今天已打卡' + (streak ? " · 连续 " + esc(streak) + " 天" : "") + '</span>'
        : '<span class="meta">做完今天的小任务，打卡自己就来啦</span>';
    var rules = (Array.isArray(data.rules) ? data.rules : []).map(function (item) {
        return esc(item.label || "") + " +" + esc(num(item.points));
    }).join(" · ");
    return '<div class="ph-card points-card">'
        + '<p class="points-title">📱 我的积分</p>'
        + '<p class="points-balance"><strong class="ph-num">' + esc(balance) + '</strong> 积分'
        + '<span class="meta">今天 +' + esc(today) + '</span></p>'
        + '<p class="points-checkin-row">' + checkin + '</p>'
        + (shopMessage ? '<p class="points-tip">' + esc(shopMessage) + '</p>' : "")
        + '<p class="points-sub">现在正在记的日常分</p>'
        + '<p class="meta points-rules">' + esc(rules) + '</p>'
        + '<p class="meta points-note">攒够积分和爸爸妈妈一起换（现在先攒着哦）。</p></div>';
}

/* ---------------- 数据 ---------------- */

function setStatus(html) {
    var box = $("shop-status");
    if (box) box.innerHTML = html || "";
}

function fill(id, html) {
    var box = $(id);
    if (box) box.innerHTML = html || "";
}

function loadShop() {
    var sid = currentStudentId();
    setStatus(loadingHtml("菲比正在算你的积分……"));
    fill("shop-balance", "");
    fill("shop-goods", "");
    fill("shop-rewards", "");
    fill("shop-records", "");
    return claimDailyLogin().then(function () {
        return jsonFetch(API + "/api/points/" + encodeURIComponent(sid));
    })
        .then(function (data) {
            setStatus("");
            fill("shop-balance", renderBalance(data));
            fill("shop-goods", renderGoods(data));
            fill("shop-rewards", renderRewards(data));
            fill("shop-records", renderRecords(data));
            var note = $("shop-note");
            if (note) note.textContent = ((data || {}).shop || {}).note || "";
            if (data && data.error) setStatus(errorHtml(data.error, "loadShop"));
        })
        .catch(function (err) {
            console.error("[shop] 加载失败", err);
            setStatus(errorHtml("菲比刚刚没拿到积分数据，我们再试一次。", "loadShop"));
        });
}

/* 每日首次登录奖励：后端幂等（一天只记一次），页面一打开就顺手领 */
function claimDailyLogin() {
    var sid = currentStudentId();
    return postJson(API + "/api/points/" + encodeURIComponent(sid) + "/login", {})
        .then(function (data) {
            if (data && data.awarded) shopMessage = data.message || "";
            return data;
        })
        .catch(function (err) {
            console.error("[shop] 登录奖励没领上", err);
            return null;
        });
}

/* ---------------- 顶部学生条（与挑战页同一套交互） ---------------- */

function updateWho() {
    var sid = currentStudentId();
    var me = students.filter(function (s) { return String(s.id) === String(sid); })[0];
    var name = $("who-name");
    var grade = $("who-grade");
    if (name) name.textContent = me ? me.name : "小朋友";
    if (grade) grade.textContent = me ? (me.grade_text || "") : "";
    if (me && shell() && shell().applyAgeMode) shell().applyAgeMode(me.grade);
    var picker = $("student-picker");
    if (picker) {
        picker.innerHTML = students.map(function (s) {
            var active = String(s.id) === String(sid);
            return '<button type="button" class="ph-student' + (active ? " is-active" : "")
                + '" data-student-id="' + esc(s.id) + '">'
                + esc(s.name) + ' · ' + esc(s.grade_text || "") + '</button>';
        }).join("");
    }
}

function toggleStudentPicker() {
    var picker = $("student-picker");
    var button = $("switch-student");
    if (!picker) return;
    var hidden = picker.classList.toggle("hidden");
    if (button) button.setAttribute("aria-expanded", hidden ? "false" : "true");
    if (hidden) return;
    var s = shell();
    if (s && s.createStudentSwitcher) s.createStudentSwitcher(picker);
    var list = s && s.loadStudents ? s.loadStudents() : Promise.resolve([]);
    Promise.resolve(list).then(function (items) {
        students = items || [];
        updateWho();
    });
}

function init() {
    var s = shell();
    if (s && s.onStudentChange) {
        s.onStudentChange(function () {
            // 切换学生：先清空上一个孩子的积分，再重新拉取
            shopMessage = "";
            loadShop();
            updateWho();
        });
    }
    var list = s && s.loadStudents ? s.loadStudents() : Promise.resolve([]);
    Promise.resolve(list).then(function (items) {
        students = items || [];
        updateWho();
        loadShop();
    });
}

var root = (typeof window !== "undefined") ? window : this;
root.ShopPage = {
    init: init,
    loadShop: loadShop,
    claimDailyLogin: claimDailyLogin,
    toggleStudentPicker: toggleStudentPicker,
    renderBalance: renderBalance,
    renderGoods: renderGoods,
    renderRewards: renderRewards,
    renderRecords: renderRecords,
    goodsRowHtml: goodsRowHtml,
    rewardRowHtml: rewardRowHtml,
    starsText: starsText,
    pointsText: pointsText
};
