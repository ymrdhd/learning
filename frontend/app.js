// ==============================================================
// 能力契约｜练习页主逻辑：出题 / 作答 / 语音朗读 / 艾宾浩斯复习面板 / 答对自动跳题 / 菲比庆祝联动
// 入口：init / loadQuestion / renderQuestion / submitAnswer / speakQuestion / speakAnalysis / celebrateAnswer / retryQuestion / scheduleAutoNext
// 依赖：无（零构建，禁 import/export）；phoebe.js（表情包）与 phoebe3d.js（三视图立牌 + 语音字幕）必须先加载，但缺失时静默降级
// 不负责：庆祝动画、3D 立牌与语音实现 → phoebe.js / phoebe3d.js
// 验证：node frontend/verify_web.js（+ node frontend/verify_phoebe3d_web.js）
// 被调用：index.html
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

// API 基址：页面本身怎么被访问（本机 127.0.0.1 还是手机走局域网 IP），请求就打回哪个源；
// 手机浏览器上写死 127.0.0.1 会把请求打回手机自己，所以这里必须跟着 location.origin 走。
const API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
    ? location.origin : "http://127.0.0.1:8000";

const DEFAULT_KNOWLEDGE = {
    "数学": "20以内加减法",
    "语文": "拼音与声调",
    "英语": "26个字母"
};

// 每学年 12 个能力等级（上册 6 + 下册 6）：改这个常量必须同步 backend/stages.py 的 LEVELS_PER_GRADE
const LEVELS_PER_GRADE = 12;

let current = null;     // 当前题目
let mode = "choice";    // choice | blank
let answered = false;   // 每题只能作答一次
let progress = null;    // 最近一次的能力数据
let autoKnowledgeLoaded = false;   // 这一科已经按能力挑好了（下次换科目/换人才重挑）
let manualKnowledge = false;       // 孩子自己改过知识点：菲比不再自动覆盖，只更新提示
let autoKnowledgeSeq = 0;          // 自动选点的请求序号，避免慢请求覆盖新选择
let studentList = [];              // 学生列表（含年级），零记录学生自动选点时做兜底

const AUTO_NEXT_MS = 1700;   // 答对后停留多久自动进入下一题（留出庆祝时间）
let autoNextTimer = null;    // 答对自动跳题定时器

function $(id) {
    return document.getElementById(id);
}

function esc(text) {
    return String(text == null ? "" : text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

/* ---------------- 儿童端共享层（ui-shell.js / kid-lang.js / ui-components.js） ---------------- */

function uc() {
    if (typeof window !== "undefined" && window.UIComponents) return window.UIComponents;
    return typeof UIComponents !== "undefined" ? UIComponents : null;
}

function kidLang() {
    if (typeof window !== "undefined" && window.KidLang) return window.KidLang;
    return typeof KidLang !== "undefined" ? KidLang : null;
}

/* 把后台的算法字段换成孩子看得懂的话。共享层缺失时保守降级，绝不把原始数字漏出去。 */
function kidText(text) {
    const lang = kidLang();
    const raw = String(text == null ? "" : text);
    if (!lang) return raw;
    return raw
        .replace(/掌握度\s*(\d+(?:\.\d+)?)/g, (m, n) => lang.statusLabel(parseFloat(n)))
        .replace(/遗忘风险\s*(\d+(?:\.\d+)?)\s*%?/g, "需要再照顾一下")
        .replace(/稳定性\s*(\d+(?:\.\d+)?)/g, "记得越来越牢");
}

function kidStatus(score) {
    const lang = kidLang();
    return lang ? lang.statusLabel(score) : "🌱 还没开始学";
}

function setVoiceStatus(text) {
    if ($("voice-status")) $("voice-status").textContent = text || "";
}

function loadingHtml(text) {
    const c = uc();
    return c ? c.loadingState({ text: text }) : `<p class="meta">⏳ ${esc(text)}</p>`;
}

function errorHtml(title, handlerName) {
    const c = uc();
    return c
        ? c.errorState({ title: title, retryAction: handlerName ? handlerName + "()" : "" })
        : `<p class="meta">${esc(title)}</p><button type="button" class="ph-btn ph-btn--primary" onclick="${esc(handlerName || "")}">再试一次</button>`;
}

/* 答对/答错都用同一套状态类：颜色 + 图标 + 文案三重表达（不只靠颜色） */
function markOption(btn, state) {
    if (!btn || !btn.classList) return;
    btn.classList.add(state);
    btn.classList.add(state === "right" ? "is-right" : "is-wrong");
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
    if (!current) return;
    answered = false;
    clearAutoNext();
    $("blank-input").disabled = false;
    document.querySelectorAll(".option").forEach(item => {
        item.disabled = false;
        item.classList.remove("is-wrong", "is-right");
    });
    $("main-btn").disabled = false;
    $("feedback").innerHTML = kidLang()
        ? `<p class="meta">${esc(kidLang().encourage(wrongRound))}</p>`
        : "";
}

/* ---------------- 语音朗读 ---------------- */

const VOICE_KEY = "xiaozhi.voice";
const VOICE_RATE_KEY = "xiaozhi.voiceRate";
const speech = {
    muted: false,       // 勾掉复选框即静音
    rate: 0.85,
    voice: null,
    supported: typeof window !== "undefined" && "speechSynthesis" in window
};

function store(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (err) {
        // 隐私模式下 localStorage 不可用，静默降级为不记忆设置
    }
}

function restore(key) {
    try {
        return localStorage.getItem(key);
    } catch (err) {
        return null;
    }
}

// 优先挑中文语音，避免用英文音色读拼音
function pickChineseVoice() {
    if (!speech.supported) return null;

    const voices = window.speechSynthesis.getVoices() || [];
    const zh = voices.filter(v => (v.lang || "").toLowerCase().indexOf("zh") === 0);

    return zh.find(v => /xiaoxiao|yaoyao|huihui|kangkang|chinese|中文|普通话/i.test(v.name))
        || zh[0]
        || null;
}

function refreshVoices() {
    speech.voice = pickChineseVoice();

    if (!speech.supported) {
        $("voice-enabled").disabled = true;
        setVoiceStatus("当前浏览器不支持语音朗读");
        return;
    }

    setVoiceStatus(speech.voice ? "" : "未找到中文语音，将使用系统默认音色");
}

function initVoice() {
    speech.muted = restore(VOICE_KEY) === "off";
    speech.rate = parseFloat(restore(VOICE_RATE_KEY)) || 0.85;

    $("voice-enabled").checked = !speech.muted;
    $("voice-rate").value = String(speech.rate);

    refreshVoices();
    // Chrome 的语音列表是异步加载的，第一次拿到后要重新选一次
    if (speech.supported) {
        window.speechSynthesis.onvoiceschanged = refreshVoices;
    }
}

function onVoiceToggle() {
    speech.muted = !$("voice-enabled").checked;
    store(VOICE_KEY, speech.muted ? "off" : "on");

    if (speech.muted) {
        stopSpeak();
    } else if (current) {
        speakQuestion();
    }
}

function onVoiceRateChange() {
    speech.rate = parseFloat($("voice-rate").value) || 0.85;
    store(VOICE_RATE_KEY, String(speech.rate));
}

function speechSupported() {
    return speech.supported && !speech.muted;
}

/* 读题失败不能影响学习：任何一步出错都只降级为"先自己看看"。
   force=true 表示孩子主动点的朗读（即使之前关过自动朗读，这一次也要读出来）。 */
function speak(text, force) {
    if (!text) return;

    if (!speech.supported) {
        setVoiceStatus("当前浏览器不支持语音朗读");
        return;
    }
    if (speech.muted && !force) return;

    // 读题失败不能影响学习：任何一步出错都只降级为"先自己看看"
    if (typeof window === "undefined" || !window.speechSynthesis
        || typeof SpeechSynthesisUtterance === "undefined") {
        setVoiceStatus("这台设备暂时读不了题，先自己看看～");
        return;
    }

    if (force && speech.muted) {
        // 主动点朗读 = 孩子想听：顺手把开关打开，界面状态和实际行为保持一致
        speech.muted = false;
        store(VOICE_KEY, "on");
        if ($("voice-enabled")) $("voice-enabled").checked = true;
    }

    try {
        const synth = window.speechSynthesis;
        // Chrome 里 cancel() 之后立刻 speak() 会被吞掉（点了没声音），所以先停、再稍后读
        let delay = 0;
        if (synth.speaking || synth.pending) {
            synth.cancel();
            delay = 120;
        }
        if (synth.paused && synth.resume) synth.resume();

        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = "zh-CN";
        utter.rate = speech.rate;
        utter.pitch = 1.05;
        utter.volume = 1;
        if (speech.voice) utter.voice = speech.voice;

        markSpeaking(true);
        utter.onend = () => markSpeaking(false);
        utter.onerror = event => {
            markSpeaking(false);
            const code = (event && event.error) || "";
            console.warn("[app] 读题失败", code);
            setVoiceStatus(code === "not-allowed"
                ? "浏览器没允许朗读，再点一次「🔊 读题目」试试～"
                : "这台设备暂时读不了题，先自己看看～");
        };

        const fire = () => {
            try {
                synth.speak(utter);
            } catch (err) {
                console.error("[app] 读题失败", err);
                markSpeaking(false);
                setVoiceStatus("这台设备暂时读不了题，先自己看看～");
            }
        };
        if (delay) setTimeout(fire, delay);
        else fire();
    } catch (err) {
        console.error("[app] 读题失败", err);
        markSpeaking(false);
        setVoiceStatus("这台设备暂时读不了题，先自己看看～");
    }
}

function stopSpeak() {
    if (speech.supported) window.speechSynthesis.cancel();
    markSpeaking(false);
}

function markSpeaking(active) {
    document.querySelectorAll("[data-speaking]").forEach(btn => {
        btn.dataset.speaking = active ? "1" : "0";
        btn.classList.toggle("speaking", active);
    });
}

/* 把题目/选项的口语化文本拼出来，浏览器语音读符号很难听，先替换掉 */
function oralText(text) {
    return String(text == null ? "" : text)
        .replace(/_{2,}/g, "空格")
        .replace(/[（(]\s*[)）]/g, "括号")
        .replace(/[×✕]/g, "乘")
        .replace(/[÷]/g, "除以")
        .replace(/[＋]/g, "加")
        .replace(/[－—]/g, "减")
        .replace(/[＝]/g, "等于")
        .replace(/[＞]/g, "大于")
        .replace(/[＜]/g, "小于")
        .replace(/[？?]/g, "。")
        .replace(/\s+/g, " ")
        // 句末的空白和停顿符统一去掉，交给调用方决定怎么断句
        .replace(/[\s。，、；：,.;:!！]+$/, "")
        .trim();
}

function questionSpeechText() {
    if (!current) return "";

    // 先去掉句末停顿，避免拼上选项时出现"。。"
    const stem = oralText(current.question);
    let text = stem + "。";

    const options = current.options || {};
    Object.keys(options).sort().forEach(key => {
        text += `选项${key}：${oralText(options[key])}。`;
    });

    return text;
}

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

function speakQuestion(force) {
    speak(questionSpeechText(), force !== false);
}

function speakAnalysis() {
    if (!progress) return;

    let text = progress.correct ? "答对了，真棒。" : "答错了，我们一起看看。";
    if (!progress.correct) {
        text += progress.correct_text
            ? `正确答案是${progress.correct_answer}，${oralText(progress.correct_text)}。`
            : `正确答案是${oralText(progress.correct_answer)}。`;
    }
    if (progress.analysis) text += oralText(progress.analysis);

    speak(text, true);   // 主动点「读解析」：即使关过自动朗读也要读
}

/* ---------------- 出题与作答 ---------------- */

function init() {
    initVoice();
    bindKnowledgeInput();

    fetch(API + "/students")
        .then(r => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(list => {
            studentList = list;
            $("student").innerHTML = list.map(s =>
                `<option value="${s.id}">${esc(s.name)}（${esc(s.grade_text)}）</option>`
            ).join("");

            // 今日学习页跳过来时带 student / subject / knowledge / autostart
            applyUrlPreset();
            $("main-btn").disabled = false;

            if (urlParam("sheet") === "1") {
                // V2.8 题单模式：先把「今天还剩多少题、都是什么题型」读回来，再统一出题
                $("main-btn").disabled = true;
                $("question").innerHTML = loadingHtml("菲比正在数一数今天还剩几道题……");
                initSheet().then(() => {
                    $("main-btn").disabled = false;
                    if (urlParam("autostart") === "1") loadQuestion();
                });
                return;
            }

            if (urlParam("autostart") === "1") {
                loadQuestion();
            } else {
                applyAutoKnowledge();
            }
        })
        .catch(err => {
            console.error("[app] 加载学生失败", err);
            $("question").innerHTML = errorHtml("菲比现在连不上服务器，我们等一会儿再试。", "init");
        });
}

/* 读取 URL 参数（今日学习页整页跳转时用） */
function urlParam(name) {
    if (typeof location === "undefined" || !location.search) return "";
    try {
        return new URLSearchParams(location.search).get(name) || "";
    } catch (err) {
        return "";
    }
}

function applyUrlPreset() {
    const studentId = urlParam("student_id");
    const subject = urlParam("subject");
    const knowledge = urlParam("knowledge");

    if (studentId && $("student") && $("student").options.length) {
        $("student").value = studentId;
    }

    if (subject && $("subject")) {
        const matched = [...$("subject").options]
            .some(item => item.value === subject || item.text === subject);
        if (matched) $("subject").value = subject;
    }

    if (knowledge) {
        $("knowledge").value = knowledge;
        autoKnowledgeLoaded = true;   // 跳转带来的知识点优先，不要被自动选择覆盖
    }
}

/* 按这个学生已经掌握的知识自动选知识点：优先薄弱项，其次当前能力阶段还没练过的 */
function pickKnowledge(ability, mastery) {
    const info = ability || {};
    const items = ((mastery || {}).knowledge || []).filter(item => item && item.knowledge_id);
    const practiced = items.filter(item => Number(item.total_questions) > 0);

    const weak = practiced.filter(item => Number(item.mastery_score) < 70)
        .sort((a, b) => Number(a.mastery_score) - Number(b.mastery_score));
    if (weak.length) return weak[0].knowledge_id;

    const focus = String(info.knowledge_focus || "");
    const focusItem = items.find(item => item.knowledge_id === focus);
    if (focusItem) return focusItem.knowledge_id;

    // 还没有能力阶段时，用学生年级的「基础」级当目标阶段
    let targetStage = stagesIndexOf(info.stage);
    if (!Number.isFinite(targetStage)) targetStage = gradeFallbackStage();
    const fresh = items.filter(item => !Number(item.total_questions))
        .map(item => ({ item, distance: Math.abs((stagesIndexOf(item.stage) || 0) - targetStage) }))
        .sort((a, b) => a.distance - b.distance);
    if (fresh.length) return fresh[0].item.knowledge_id;

    return info.knowledge_focus || DEFAULT_KNOWLEDGE[$("subject").value] || "";
}

/* 当前选中学生的年级（零记录学生只有这一个信号） */
function currentGrade() {
    const row = studentList.find(item => String(item.id) === String($("student").value));
    return (row && Number(row.grade)) || 1;
}

function gradeFallbackStage() {
    return (currentGrade() - 1) * LEVELS_PER_GRADE;
}

/* 阶段字符串 "3.2" → 线性坐标（每学年 LEVELS_PER_GRADE 个等级） */
function stagesIndexOf(key) {
    const text = String(key || "");
    const parts = text.split(".");
    if (parts.length !== 2) return NaN;
    const grade = Number(parts[0]);
    const level = Number(parts[1]);
    if (!grade || !level) return NaN;
    return (grade - 1) * LEVELS_PER_GRADE + (level - 1);
}

/* 菲比按「这个学生这一科」的当前能力挑目标知识点（V2.6：跟着能力走，不再是写死的默认值） */
function pickRecommendedKnowledge(data) {
    const payload = data || {};
    const primary = payload.primary || {};
    const next = payload.next_action || {};
    const knowledge = String(primary.knowledge || next.knowledge || "").trim();
    if (!knowledge) return null;
    return {
        knowledge: knowledge,
        reason: String(primary.reason || next.reason || "").trim(),
        difficulty: Number(primary.difficulty || next.difficulty) || 0,
        action: String(primary.action || next.action || "").trim(),
    };
}

/* 儿童文案：掌握度 / 遗忘风险这类算法数字不给孩子看（V2.6 原则 6） */
const KNOWLEDGE_HINT_BY_ACTION = {
    review: "这个知识有点快忘了，今天再看一眼",
    practice: "这个知识再练几遍就更牢啦",
    diagnostic: "先做几道题，菲比就能看清你的水平",
};

function knowledgeHintFor(pick) {
    if (!pick) return "";
    const line = KNOWLEDGE_HINT_BY_ACTION[pick.action] || "这是菲比按你现在的能力挑的";
    return `菲比按你现在的能力挑了「${pick.knowledge}」：${line}`;
}

function setKnowledgeHint(text) {
    const node = $("knowledge-hint");
    if (!node) return;
    node.textContent = text || "";
    if (node.classList) node.classList.toggle("hidden", !text);
}

/* 孩子自己改了知识点：记录下来，菲比不再覆盖（只更新提示） */
function bindKnowledgeInput() {
    const input = $("knowledge");
    if (!input || typeof input.addEventListener !== "function") return;
    input.addEventListener("input", () => {
        manualKnowledge = true;
        const picked = String(input.value || "").trim();
        setKnowledgeHint(picked
            ? `你自己选的知识点：${picked}`
            : "菲比正在看你的水平，帮你挑一个知识点…");
    });
}

function applyAutoKnowledge(force) {
    const input = $("knowledge");
    if (!input || manualKnowledge) return;
    if (!force && autoKnowledgeLoaded) return;
    if (!String(input.value || "").trim()) {
        input.value = DEFAULT_KNOWLEDGE[$("subject").value] || "";
    }

    const studentId = $("student").value || "1";
    const subject = $("subject").value || "数学";
    const token = ++autoKnowledgeSeq;

    if (force) setKnowledgeHint("菲比正在重新看你的水平…");

    const recommendUrl = `${API}/api/learning/recommend/${studentId}`
        + `?subject=${encodeURIComponent(subject)}`;
    const abilityUrl = `${API}/api/ability/auto/${studentId}`
        + `?subject=${encodeURIComponent(subject)}`;
    const masteryUrl = `${API}/api/mastery/${studentId}`
        + `?subject=${encodeURIComponent(subject)}`;

    // 首选自适应引擎的推荐（知识点、难度、理由都由 V2.3 引擎算），拿不到再退回本地兜底
    fetch(recommendUrl)
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null)
        .then(data => {
            if (token !== autoKnowledgeSeq || manualKnowledge) return null;
            const pick = pickRecommendedKnowledge(data);
            if (pick) {
                input.value = pick.knowledge;
                autoKnowledgeLoaded = true;
                setKnowledgeHint(knowledgeHintFor(pick));
                return null;
            }
            return Promise.all([
                fetch(abilityUrl).then(r => (r.ok ? r.json() : null)).catch(() => null),
                fetch(masteryUrl).then(r => (r.ok ? r.json() : null)).catch(() => null)
            ]);
        })
        .then(pair => {
            if (!pair || token !== autoKnowledgeSeq || manualKnowledge) return;
            const [ability, mastery] = pair;
            const pick = pickKnowledge(ability, mastery);
            if (!pick) return;
            input.value = pick;
            autoKnowledgeLoaded = true;
            setKnowledgeHint(`先练「${pick}」，菲比会跟着你的水平调整`);
        })
        .catch(() => {
            // 自动选点失败就保留默认知识点，不影响手动出题
        });
}

function onSubjectChange() {
    // V2.8：孩子自己换科目 = 离开今天的题单，回到自由练习
    if (sheetActive) exitSheet();
    $("knowledge").value = DEFAULT_KNOWLEDGE[$("subject").value] || "";
    autoKnowledgeLoaded = false;
    manualKnowledge = false;            // 换科目 = 换一个能力目标，重新让引擎挑
    setKnowledgeHint("菲比正在看你的水平，帮你挑一个知识点…");
    applyAutoKnowledge();
    resetBoard();
    $("question").innerHTML = "";
}

/* 换学生：重新按这个学生已经掌握的知识选知识点 */
function onStudentChange() {
    // V2.8 题单模式：换人 = 重新读这个小朋友今天还剩哪些题
    if (urlParam("sheet") === "1") {
        autoKnowledgeLoaded = false;
        manualKnowledge = false;
        exitSheet();
        $("main-btn").disabled = true;
        $("question").innerHTML = loadingHtml("菲比正在数一数这个小朋友今天还剩几道题……");
        initSheet().then(() => {
            $("main-btn").disabled = false;
            loadQuestion();
        });
        return;
    }

    autoKnowledgeLoaded = false;
    manualKnowledge = false;            // 换小朋友 = 换一套画像，重新让引擎挑
    setKnowledgeHint("菲比正在看你的水平，帮你挑一个知识点…");
    applyAutoKnowledge();
    resetBoard();
    $("question").innerHTML = "";
}

function setMode(next) {
    mode = next;
    $("mode-choice").classList.toggle("active", next === "choice");
    $("mode-blank").classList.toggle("active", next === "blank");
    resetBoard();
    $("question").innerHTML = "";
}

function resetBoard() {
    clearAutoNext();
    current = null;
    answered = false;
    progress = null;
    wrongRound = 0;
    stopSpeak();
    $("options").innerHTML = "";
    $("feedback").innerHTML = "";
    $("review-panel").innerHTML = "";
    $("review-panel").classList.add("hidden");
    $("blank-box").classList.add("hidden");
    $("blank-input").value = "";
    $("blank-input").disabled = false;
    $("main-btn").disabled = false;
    $("main-btn").textContent = "开始学习";
}

/* ---------------- V2.8 今日题单（sheet）：先读剩余题型，再逐项统一出题 ----------------

   需求（用户：更改开始今天的学习的出题逻辑）：点「开始今天的学习」→ 先读「今天还剩多少
   题、都是什么题型」，统一出题；每页仍然只显示一道题，每道题带内部标记（如「数学 · 新知识」
   /「数学 · 薄弱训练」）；一项做完视为收工，重新出题时跳过它；一项里有 5 道题只做完 3 道，
   首页就显示 3/5，下次继续出剩下 2 道。

   实现：题单 = 今天 status 不是 done、且还剩题数的 daily_learning_task，按 priority 排序；
   一次出一道题，答完把 task_id 一起提交，后端按这一项精确记 complete_count。 */
let sheet = null;         // { buckets: [...], index: 0 }：今天还要做的题型桶
let sheetActive = false;  // 是否处于今天的题单模式
let sheetDone = false;    // 今天所有项都做完了

function sheetBucket() {
    if (!sheet) return null;
    return sheet.buckets[sheet.index] || null;
}

/* 读今天的任务，筛出「还没做完且还剩题数」的项，按后端给的顺序统一出题 */
function buildSheet() {
    const sid = $("student").value || "1";

    return fetch(`${API}/api/tasks/today?student_id=${encodeURIComponent(sid)}`)
        .then(r => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(data => {
            const buckets = ((data || {}).tasks || [])
                .filter(item => String(item.status || "") !== "done")
                .filter(item => Number(item.target_count || 0) - Number(item.complete_count || 0) > 0)
                .sort((a, b) => (Number(a.priority) || 0) - (Number(b.priority) || 0))
                .map(item => ({
                    task_id: Number(item.task_id) || 0,
                    tag: item.title || `${item.subject || ""} · ${item.task_type_text || ""}`,
                    subject: item.subject || "数学",
                    knowledge: item.knowledge || "",
                    target: Number(item.target_count) || 1,
                    done: Number(item.complete_count) || 0
                }));

            sheet = { buckets: buckets, index: 0 };
            sheetDone = buckets.length === 0;
            return sheet;
        });
}

function initSheet() {
    return buildSheet()
        .then(() => {
            sheetActive = true;
            renderSheetTag();
            return sheet;
        })
        .catch(err => {
            // 题单读不到也不能把孩子卡住：退回自由练习
            console.error("[app] 今日题单加载失败", err);
            sheet = null;
            sheetActive = false;
            sheetDone = false;
            renderSheetTag();
            return null;
        });
}

/* 离开题单模式（孩子自己改了科目等），回到普通自由练习 */
function exitSheet() {
    sheet = null;
    sheetActive = false;
    sheetDone = false;
    renderSheetTag();
}

/* 页面上的内部标记 + 这一项的进度（3/5）：孩子看得懂，也方便家长核对 */
function renderSheetTag() {
    const box = $("sheet-tag");
    if (!box) return;

    const bucket = sheetBucket();
    if (!sheetActive || !bucket) {
        box.classList.add("hidden");
        box.innerHTML = "";
        return;
    }

    const remain = Math.max(0, bucket.target - bucket.done);
    box.classList.remove("hidden");
    box.innerHTML = `<span class="sheet-tag-title">📝 ${esc(bucket.tag)}</span>`
        + `<span class="meta"> 已完成 ${esc(bucket.done)}/${esc(bucket.target)} · 还差 ${esc(remain)} 题</span>`;
}

/* 答完一题：当前这一项 +1；做满 target_count 就收工换下一项；全部做完就整张题单收工 */
function sheetAdvance() {
    const bucket = sheetBucket();
    if (!bucket) return { finished: false, allDone: sheetDone, tag: "" };

    bucket.done = Math.min(bucket.target, bucket.done + 1);
    const finished = bucket.done >= bucket.target;
    if (finished) sheet.index += 1;
    if (sheet.index >= sheet.buckets.length) sheetDone = true;
    renderSheetTag();
    return { finished: finished, allDone: sheetDone, tag: bucket.tag };
}

/* 今天的小任务全部做完：停在完成页，不再出题（与今日学习页的完成页保持一致） */
function renderSheetDone() {
    resetBoard();
    $("main-btn").disabled = true;
    $("main-btn").textContent = "今天做完啦";

    const box = $("sheet-tag");
    if (box) {
        box.classList.add("hidden");
        box.innerHTML = "";
    }

    $("question").innerHTML = `
        <p class="qtext">🎉 今天的学习完成啦！</p>
        <p class="meta">今天安排的小任务都收工了，去休息一下吧。</p>
        <p class="meta"><a href="today.html">📅 回到今日学习</a></p>
    `;
    $("options").innerHTML = "";
    $("blank-box").classList.add("hidden");
    $("progress").innerHTML = "今天的学习 · 全部完成";
}

function loadQuestion() {

    // V2.8 题单模式：今天的小任务都做完了就停在完成页，不再出题
    if (sheetActive && sheetDone) {
        renderSheetDone();
        return;
    }

    const bucket = sheetActive ? sheetBucket() : null;
    if (bucket) {
        // 出题前把页面上的科目 / 知识点对齐到「现在这一项」，这一题就属于这一项
        if ($("subject")) $("subject").value = bucket.subject;
        $("knowledge").value = bucket.knowledge;
    }

    resetBoard();
    $("main-btn").disabled = true;
    $("question").innerHTML = loadingHtml("菲比正在准备一道适合你的题……");

    const params = new URLSearchParams({
        student_id: $("student").value || "1",
        subject: bucket ? bucket.subject : $("subject").value,
        knowledge: bucket ? bucket.knowledge : $("knowledge").value.trim(),
        qtype: mode
    });

    fetch(API + "/question?" + params.toString())
        .then(r => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(d => {
            current = d;
            answered = false;
            $("main-btn").disabled = false;
            $("main-btn").textContent = "换一题";
            renderQuestion(d);
            renderSheetTag();
            // 自动读题：小朋友可以不看字先听懂题目（跟随语音开关，不强制出声）
            speakQuestion(false);
        })
        .catch(err => {
            $("main-btn").disabled = false;
            console.error("[app] 出题失败", err);
            $("question").innerHTML = errorHtml("菲比刚刚没拿到题目，我们再试一次。", "loadQuestion");
        });
}

function renderQuestion(d) {

    const card = uc();

    $("question").innerHTML = card
        ? card.questionCard({
            subject: d.subject,
            knowledge: d.knowledge,
            question: d.question,
            speakAction: "speakQuestion()"
        })
        : `
        <p class="qtext">${esc(d.question)}</p>
        <p class="meta">${esc(d.subject)} · ${esc(d.knowledge)}</p>
        <button type="button" class="voice-btn" data-speaking="0" onclick="speakQuestion()">🔊 读题目</button>
    `;

    if (d.is_review && d.review) {
        // 儿童端不出现"掌握度 N%"，统一换成 🌱/🌿/🍀/🌳/⭐
        $("question").innerHTML += `<p class="review-badge">🔁 这个知识该复习啦 · ${esc(kidStatus(d.review.mastery))}</p>`;
    }

    if (d.error) {
        // 真实技术错误只写日志，不暴露给孩子
        console.error("[app] 已使用内置题目", d.error);
        $("question").innerHTML += `<p class="meta">📚 这次先用系统里准备好的题目。</p>`;
    }

    renderReviewPanel(d);

    if (d.qtype === "blank") {
        $("options").innerHTML = "";
        $("blank-box").classList.remove("hidden");
        $("blank-input").focus();
        return;
    }

    $("blank-box").classList.add("hidden");

    const keys = Object.keys(d.options || {}).sort();
    $("options").innerHTML = keys.map(k => `
        <button type="button" class="option ph-option" data-key="${esc(k)}" onclick="submitAnswer('${esc(k)}', this)">
            <b>${esc(k)}.</b> ${esc(d.options[k])}
        </button>
    `).join("");

    if (!keys.length) {
        $("options").innerHTML = `<p class="meta">😕 这次没拿到选项，我们换一题试试。</p>`;
    }
}

function renderReviewPanel(d) {
    const items = d.due_reviews || [];

    if (!items.length) {
        $("review-panel").classList.add("hidden");
        $("review-panel").innerHTML = "";
        return;
    }

    $("review-panel").innerHTML = `
        <p class="review-title">⏰ 还有 ${esc(d.due_count)} 个知识点到期该复习了</p>
        ${items.map(item => `
            <div class="review-item">
                <span>${esc(item.knowledge)} · ${esc(kidStatus(item.mastery))} · ${esc(item.overdue_text)}</span>
                <button class="mode-btn" onclick="startReview('${esc(item.knowledge)}')">立即复习</button>
            </div>
        `).join("")}
    `;
    $("review-panel").classList.remove("hidden");
}

function startReview(knowledge) {
    $("knowledge").value = knowledge;
    loadQuestion();
}

function submitBlank() {
    const value = $("blank-input").value.trim();
    if (!value) {
        $("feedback").innerHTML = `<p class="meta">先写上答案，再点「我做好了」哦～</p>`;
        return;
    }
    submitAnswer(value, null);
}

function submitAnswer(value, btn) {

    if (!current || answered) return;

    answered = true;
    stopSpeak();
    $("blank-input").disabled = true;
    document.querySelectorAll(".option").forEach(b => b.disabled = true);

    fetch(API + "/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            question_id: current.question_id,
            answer: value,
            student_id: parseInt($("student").value || "1", 10),
            // V2.8 题单模式：把「这一题属于哪一项今日任务」交给后端，按项精确记 3/5
            task_id: sheetActive && sheetBucket() ? sheetBucket().task_id : 0
        })
    })
        .then(r => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(d => {
            markOption(btn, d.correct ? "right" : "wrong");
            if (!d.correct && d.correct_answer) {
                markOption(document.querySelector(`.option[data-key="${d.correct_answer}"]`), "right");
            }
            progress = d;
            renderResult(d);
        })
        .catch(err => {
            answered = false;
            $("blank-input").disabled = false;
            document.querySelectorAll(".option").forEach(b => b.disabled = false);
            console.error("[app] 提交失败", err);
            $("feedback").innerHTML = `<p class="meta">😕 菲比刚刚没收到你的答案，我们再试一次。</p>`;
        });
}

function renderResult(d) {

    // 连续答对：答错清零；答对累加（跨题保持）
    if (d.correct) {
        answerStreak += 1;
        wrongRound = 0;
    } else {
        answerStreak = 0;
        wrongRound = Math.min(wrongRound + 1, 4);
    }

    // 只有知识点档位上升才给更明显的动画（用户简报 §14）
    const upgrade = d.correct ? upgradeOf(d.mastery) : null;
    // V2.6：等级真的提升一次，左侧菲比收藏 +1（学习成果驱动，不看在线时长）
    if (upgrade) phoebeCollect();

    const head = d.correct
        ? (upgrade ? "🌳 升级！" : "✓ 对啦")
        : "🤔 这里再想一下";

    let correctLine = "";
    if (!d.correct) {
        correctLine = d.correct_text
            ? `<p>正确答案：<b>${esc(d.correct_answer)}. ${esc(d.correct_text)}</b></p>`
            : `<p>正确答案：<b>${esc(d.correct_answer)}</b></p>`;
    }

    const review = d.review || {};
    const reviewLine = review.message
        ? `<p class="review-tip">🧠 ${esc(review.message)}
             <span class="meta">（下次复习：${esc(review.next_review_at || "")}｜${esc(kidStatus(review.mastery))}）</span>
           </p>`
        : "";

    $("feedback").innerHTML = `
        <p class="verdict ${d.correct ? "ok" : "bad"}">${head}</p>
        ${upgrade ? `<p class="ph-upgrade">${esc(kidLang().upgradeText(upgrade.from, upgrade.to, upgrade.name))}</p>` : ""}
        ${streakLine()}
        ${correctLine}
        ${d.correct ? "" : hintHtmlOf(wrongRound, d)}
        <p class="analysis">解析：${esc(d.analysis)}</p>
        ${reviewLine}
        <button class="voice-btn" data-speaking="0" onclick="speakAnalysis()">🔊 读解析</button>
    `;

    $("progress").innerHTML =
        `本次练习 · 累计答对 ${Number(d.correct_count) || 0} / ${Number(d.total_count) || 0} 题`;

    $("main-btn").disabled = false;
    $("main-btn").textContent = "下一题";

    // 答对就弹出菲比表情包庆祝，答错则清空连胜
    celebrateAnswer(d.correct, upgrade);
    // V2.8 题单模式：这一题记进「现在这一项」；做满 target_count 就收工，换下一项
    let sheetNote = "";
    if (sheetActive) {
        const step = sheetAdvance();
        if (step.allDone) sheetNote = "🎉 今天安排的小任务都做完啦！";
        else if (step.finished) sheetNote = `✅ ${step.tag} 收工啦，接着做下一项～`;
    }

    if (d.correct) {
        // V2.5：答对自动进入下一题（先让孩子看完庆祝）
        $("feedback").innerHTML += `<p class="next-tip">🎉 马上进入下一题…</p>`;
        scheduleAutoNext();
    } else {
        // 答错停留在解析页，孩子看完再点"下一题"
        clearAutoNext();
    }

    // 题单模式：这一项收工 / 今天全部做完，都在解析下面说清楚
    if (sheetNote) $("feedback").innerHTML += `<p class="next-tip">${esc(sheetNote)}</p>`;

    // V2.6：这题练完，能力画像可能变了 —— 让知识点目标跟着能力走（孩子自己改过就不覆盖）
    // V2.8：题单模式的知识点由「现在还剩哪一项」决定，不能被自动选点覆盖
    if (!sheetActive) applyAutoKnowledge(true);
}

/* ---------------- V2.5 自动跳题 ---------------- */

function clearAutoNext() {
    if (autoNextTimer) {
        clearTimeout(autoNextTimer);
        autoNextTimer = null;
    }
}

function scheduleAutoNext() {
    clearAutoNext();
    autoNextTimer = setTimeout(() => {
        autoNextTimer = null;
        if (!answered) return;        // 已经手动切题了就不再自动跳
        loadQuestion();
    }, AUTO_NEXT_MS);
}

/* 菲比庆祝：phoebe.js 未加载时静默跳过，不影响答题。
   phoebe3d.js 在的时候由它统一负责（立牌动作 + 语音 + 字幕 + 表情包）。 */
function celebrateAnswer(correct, upgrade) {
    if (typeof phoebe3dFeedback === "function") {
        try {
            phoebe3dFeedback(!!correct, {});
        } catch (err) {
            // 立牌/语音出错都不影响做题
        }
        if (!upgrade) return;
    }

    if (typeof celebrateCorrect !== "function") return;
    if (correct) {
        // 知识点升级：更明显、稍长的动画 + 升级文案（用户简报 §14）；
        // 普通答对走 phoebe.js 默认的轻量庆祝。
        celebrateCorrect(upgrade && kidLang()
            ? { word: kidLang().upgradeText(upgrade.from, upgrade.to, upgrade.name), duration: 1800 }
            : undefined);
    } else {
        phoebeResetStreak();
    }
}

init();
