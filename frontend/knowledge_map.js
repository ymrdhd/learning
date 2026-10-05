// ==============================================================
// 能力契约｜知识掌握地图页：领域星级 + 知识点掌握度 + 展开折叠
// 入口：init / loadMastery / renderMastery / renderDomains / renderSummary / renderKnowledgeRow / renderDomain / toggleDomain / barWidth / starText
// 依赖：style.css；ui-shell.js / kid-lang.js / ui-components.js（须先于业务 js 加载）
// 不负责：学习建议 → study_advice.js；错题 → wrong_book.js
// 验证：node frontend/verify_knowledge_web.js
// 被调用：knowledge_map.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/* 知识掌握地图（V2.3）：按领域看知识点掌握度、星级与掌握等级。
   接口：GET /students、GET /api/mastery/{student_id}?subject=数学 */

const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin
    : "http://127.0.0.1:8000";

let selectedSubject = "数学";
let students = [];
let lastDomains = [];
const expandedDomains = {};   // 领域名 -> 是否展开（默认展开）

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

/* 领域 → 探索图标（只做视觉映射，不改后端任何领域定义） */
const DOMAIN_ICONS = {
    "计算": "🏡", "数与代数": "🏡", "图形与几何": "🏰", "应用题": "⛰", "统计与概率": "📊",
    "识字与写字": "📖", "阅读": "📖", "表达": "✍️", "积累与运用": "📚", "古诗文": "🎋",
    "听力": "👂", "口语": "💬", "词汇": "🔤", "语法": "🔤", "阅读与理解": "📖"
};

function domainIcon(name) {
    return DOMAIN_ICONS[name] || "🌱";
}

/* 掌握度 → 儿童状态标签（文字 + 图标，不靠颜色单独表达） */
function statusBadge(mastery) {
    const c = uc();
    return c ? c.knowledgeStatus({ mastery: mastery })
        : `<span class="ph-status">${esc(kidLang() ? kidLang().statusLabel(mastery) : "")}</span>`;
}

function statusDot(mastery) {
    const c = uc();
    return c ? c.knowledgeStatus({ mastery: mastery, compact: true })
        : `<span class="ph-status-dot">${esc(kidLang() ? kidLang().statusLabel(mastery) : "")}</span>`;
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

/* 进度条宽度：分数裁剪到 0~100（纯函数，方便单测） */
function barWidth(score) {
    const value = Number(score);
    if (!isFinite(value)) return 0;   // 没有数据时也不崩
    return Math.max(0, Math.min(100, Math.round(value)));
}

/* 掌握度配色：>=80 好、>=60 中、否则偏低（纯函数） */
function masteryClass(score) {
    const value = Number(score) || 0;
    if (value >= 80) return "good";
    if (value >= 60) return "mid";
    return "low";
}

/* 星级换算：每 20 分一颗星，最多 5 颗；没数据 0 颗（纯函数） */
function starCount(score) {
    const value = Number(score);
    if (!isFinite(value) || value <= 0) return 0;
    return Math.max(1, Math.min(5, Math.round(value / 20)));
}

/* 星级文案，例如 ★★★☆☆（纯函数） */
function starText(score) {
    const count = starCount(score);
    return "★".repeat(count) + "☆".repeat(5 - count);
}

/* 百分比：分母为 0 返回 0，超过 100% 截断（纯函数） */
function percent(part, total) {
    const all = Number(total) || 0;
    if (all <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((Number(part) || 0) / all * 100)));
}

/* 掌握等级 → 徽标配色（纯函数） */
function levelClass(level) {
    if (level === "熟练") return "lv-good";
    if (level === "初步掌握") return "lv-ok";
    if (level === "巩固中") return "lv-mid";
    if (level === "薄弱") return "lv-low";
    return "lv-none";
}

/* 领域默认展开，点过一次就按用户的选择来 */
function isExpanded(name) {
    return expandedDomains[name] !== false;
}

function currentStudentId() {
    return parseInt($("student").value || "1", 10);
}

function renderSummary(summary) {
    const data = summary || {};
    const items = [
        [data.knowledge_count || 0, "知识点总数"],
        [data.mastered || 0, "已掌握"],
        [data.learning || 0, "巩固中"],
        [data.weak || 0, "薄弱"],
    ];

    let html = items.map(item => `<div class="summary-item">
        <span class="summary-num">${esc(item[0])}</span>
        <span class="meta">${esc(item[1])}</span>
    </div>`).join("");

    if (data.average_mastery != null) {
        html += `<div class="summary-item summary-item--status">
            ${statusBadge(data.average_mastery)}
            <span class="meta">整体状态</span>
        </div>`;
    }

    return html;
}

function knowledgeName(item) {
    return item.knowledge || item.knowledge_id || "未命名知识点";
}

function renderKnowledgeRow(item) {
    return `<div class="knowledge-row km-row">
        <span class="knowledge-name">${esc(knowledgeName(item))}</span>${statusDot(item.mastery_score)}
        <span class="knowledge-bar"><i class="${masteryClass(item.mastery_score)}"
            style="width:${barWidth(item.mastery_score)}%"></i></span>
        <span class="knowledge-score">${esc(barWidth(item.mastery_score))}</span>
        <span class="meta">${esc(item.correct_questions || 0)}/${esc(item.total_questions || 0)} 题</span>
        <span class="badge ${levelClass(item.level)}">${esc(item.level || "未练习")}</span>
    </div>`;
}

function renderDomain(domain) {
    const name = domain.domain || "未分组";
    const open = isExpanded(name);
    const children = domain.children || [];
    const count = domain.knowledge_count == null ? children.length : domain.knowledge_count;

    return `<div class="domain-card">
        <div class="domain-head" onclick="toggleDomain('${esc(name)}')">
            <span class="domain-name">${open ? "▾" : "▸"} <span aria-hidden="true">${esc(domainIcon(name))}</span> ${esc(name)}</span>
            <span class="domain-stars">${esc(domain.star_text || starText(domain.mastery_score))}</span>
            ${statusBadge(domain.mastery_score)}
            <span class="meta">${esc(count)} 个知识点</span>
        </div>
        ${open ? `<div class="knowledge-list km-list">${children.map(renderKnowledgeRow).join("")}</div>` : ""}
    </div>`;
}

/* 没有任何数据时的友好提示 */
function renderEmpty() {
    lastDomains = [];
    $("domains").innerHTML = emptyStateOf({
        icon: "🌱",
        title: "这位同学还没有知识地图数据，先做一次能力诊断，星星就会出现啦～",
        hint: "做完诊断就能看到自己的成长啦。"
    }) + `<p><a href="diagnostic.html">🧪 去做能力诊断</a></p>`;
}

function renderDomains(domains) {
    lastDomains = domains || [];
    if (!lastDomains.length) {
        renderEmpty();
        return;
    }
    $("domains").innerHTML = lastDomains.map(renderDomain).join("");
}

/* 展开 / 收起某个领域的知识点（状态存在 expandedDomains 里） */
function toggleDomain(name) {
    expandedDomains[name] = !isExpanded(name);
    renderDomains(lastDomains);
    return isExpanded(name);
}

function renderMastery(data) {
    const info = data || {};
    $("summary").innerHTML = renderSummary(info.summary);

    const domains = info.domains || [];
    const knowledge = info.knowledge || [];
    if (!domains.length && !knowledge.length) {
        renderEmpty();
        return;
    }
    renderDomains(domains);
}

/* ---------------- V2.6 儿童探索地图（真实掌握度 → 🌱🌿🌳⭐） ---------------- */

let mapNodes = [];   // 最近一次 /api/knowledge-map 的 knowledge_nodes

/* 一个知识节点的儿童状态芯片；默认只读：知识点、题目、难度仍由系统决定 */
function statusChip(node) {
    const st = node.ui_status || {};
    const mark = node.recommended ? " · 菲比推荐" : "";
    return `<span class="ph-chip ph-chip--${esc(st.key || "sprout")}" data-status="${esc(st.key || "sprout")}">`
        + `${esc(st.icon || "🌱")} ${esc(node.name || node.knowledge_id || "")}${esc(mark)}</span>`;
}

function nodesOfRegion(region) {
    const keys = region.nodes || [];
    return keys.map(key => mapNodes.filter(n => n.knowledge_id === key)[0]).filter(Boolean);
}

function renderRegion(region) {
    const data = region || {};
    return `<div class="ph-card ph-card--region">
        <p class="ph-tile-name">${esc(data.title || data.name || "")}</p>
        <p class="meta">${esc(data.progress_text || "")}</p>
        <div class="ph-progress"><div class="ph-progress-fill"
            style="width:${barWidth(data.percent)}%"></div></div>
        <div class="ph-chips">${nodesOfRegion(data).map(statusChip).join("")}</div>
    </div>`;
}

function renderKnowledgeMap(data) {
    const info = data || {};
    mapNodes = info.knowledge_nodes || [];
    const regions = info.regions || [];
    const box = $("map-regions");
    const status = $("map-status");
    if (!box) return;

    box.innerHTML = regions.length
        ? regions.map(renderRegion).join("")
        : emptyStateOf({ icon: "🌱", title: "这张地图还在等你开始探索～" });

    if (status) {
        const totals = info.totals || {};
        const next = (info.recommended || [])[0] || "由菲比按今天的状态安排";
        status.textContent = "🌳 " + (totals.grown || 0) + " 个知识已经长大 · ⭐ "
            + (totals.long_term || 0) + " 个记得很牢 · 菲比推荐先学：" + next;
    }
}

function loadKnowledgeMap() {
    if (!$("student").value) return Promise.resolve();
    const box = $("map-regions");
    if (box) box.innerHTML = loadingOf("菲比正在整理探索地图……");
    const params = new URLSearchParams({ subject: selectedSubject });
    return jsonFetch(API + "/api/knowledge-map/" + currentStudentId() + "?" + params.toString())
        .then(renderKnowledgeMap)
        .catch(err => {
            // 新接口不可用时旧接口的明细列表照常展示，不阻止孩子看地图
            console.error("[knowledge_map] 探索地图读取失败", err);
            if ($("map-status")) $("map-status").textContent = "";
            if (box) box.innerHTML = "";
        });
}

function loadMastery() {
    if (!$("student").value) return Promise.resolve();

    $("domains").innerHTML = loadingOf("菲比正在整理知识地图……");
    $("hint").textContent = "";

    const params = new URLSearchParams({ subject: selectedSubject });
    const promise = jsonFetch(API + "/api/mastery/" + currentStudentId() + "?" + params.toString())
        .then(renderMastery)
        .catch(err => {
            console.error("[knowledge_map] 知识地图读取失败", err);
            $("domains").innerHTML = emptyStateOf({ icon: "🐳", title: "菲比刚刚没拿到知识地图，我们再试一次。" });
        });

    loadKnowledgeMap();   // V2.6 探索地图（与明细列表并行，互不阻塞）
    return promise;
}

function loadStudents() {
    return jsonFetch(API + "/students")
        .then(list => {
            students = list || [];
            $("student").innerHTML = students.map(s =>
                `<option value="${s.id}">${esc(s.name)}（${esc(s.grade_text)}）</option>`
            ).join("");
        })
        .catch(err => {
            console.error("[knowledge_map] 连接后端失败", err);
            $("hint").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;
        });
}

function onStudentChange() {
    loadMastery();
}

function selectSubject(subject) {
    selectedSubject = subject;
    document.querySelectorAll(".subject-card").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.subject === subject);
    });
    if (students.length) loadMastery();
}

function init() {
    selectSubject("数学");
    loadStudents().then(loadMastery);
}

init();
