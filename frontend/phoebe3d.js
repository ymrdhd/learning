// ==============================================================
// 能力契约｜菲比三视图 3D 立牌：拖拽旋转 / 点击触发 AI 反馈 / 6 情绪表情 / 语音 + 字幕 / 答题反馈动作
// 入口：phoebe3dMount / phoebe3dAutoMount / phoebe3dAsk / phoebe3dSay / phoebe3dReact / phoebe3dFeedback / phoebe3dMood / PHOEBE3D
// 依赖：后端 POST /api/phoebe/chat（DeepSeek + 学习数据，见 backend/phoebe_ai.py）；
//       素材 assets/phoebe3d/{mood}_{view}.png（6 情绪 × 3 视角 = 18 张）；表情包浮层为可选调用（phoebe.js）
// 不负责：学习数据聚合与台词生成 → backend/phoebe_ai.py；表情包浮层与 mp3 音效 → phoebe.js
// 验证：node frontend/verify_phoebe3d_web.js
// 被调用：today.html、index.html、ability.html、wrong_book.html（**必须先于业务 js 加载**）；没有宿主容器时自动挂左侧固定立牌
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 菲比（Phoebe）毛绒公仔三视图立牌。
 *
 * 素材来自用户提供的「6 情绪 × 3 视角」表情宫格图（开心 / 难过 / 点赞 / 加油 / 可爱 / 鼓励
 * × 正面 / 侧面 / 背面），由 tools/crop_phoebe3d_sheet.py 裁成 18 张透明背景 PNG，
 * 共用同一画布、底部对齐，因此换情绪或旋转时脚底都不会跳动。
 *
 * 只有三个真实视角，第四个视角（270°）用侧面的水平镜像补足，
 * 形成"正面 → 侧面 → 背面 → 另一侧 → 正面"的完整一圈。
 *
 * 交互：
 *   1. 按住左右拖动 → 旋转，松手带惯性并停靠到最近的正视角；空闲时轻微摆动
 *   2. 点击公仔 → 换成「可爱」，并让后端读这个孩子的学习数据，由 DeepSeek 说一句话（语音 + 字幕）
 *   3. phoebe3dReact("happy" | "sad") → 跳跃欢呼 / 摇头，同时换成对应情绪
 *   4. phoebe3dFeedback(correct) → 答对换「开心」跳跃转圈 + 弹表情包；答错换「难过」摇头 + 语音
 *   5. 情绪切换：phoebe3dMood("cheer")；连续答对 ≥2 题自动换「点赞」，错题重练答对换「加油」，
 *      空闲 60 秒换「鼓励」，让立牌一直有反应而不是一张静止图
 *
 * 位置：默认挂在浏览器**左侧空白处**（position:fixed），页面滚动、鼠标移动、
 *       拖拽旋转都不会改变它的位置；只有旋转角度与表情会变。
 *
 * 该文件不依赖任何其他脚本，也不阻塞业务逻辑：
 * 任何一步失败（没有 DOM、没有语音、图片加载失败、后端没有 key、网络超时）
 * 都静默降级到本地文案与当前表情，绝不让立牌卡住。
 */

(function (root) {
    "use strict";

    var ASSET_DIR = "assets/phoebe3d/";

    /* 四个旋转视角：0=正面 90=侧面 180=背面 270=侧面镜像。
       view 是素材文件的视角后缀（文件名为 {mood}_{view}.png，情绪在运行时切换）。 */
    var FRAMES = [
        { key: "front", view: "front", angle: 0, mirror: false },
        { key: "side", view: "side", angle: 90, mirror: false },
        { key: "back", view: "back", angle: 180, mirror: false },
        { key: "side-mirror", view: "side", angle: 270, mirror: true }
    ];

    /* 六种情绪表情（与 assets/phoebe3d/manifest.json 的 moods 一致） */
    var MOODS = [
        { key: "happy", label: "开心" },
        { key: "sad", label: "难过" },
        { key: "like", label: "点赞" },
        { key: "cheer", label: "加油" },
        { key: "cute", label: "可爱" },
        { key: "encourage", label: "鼓励" }
    ];

    /* 三张真实视角（预载与换图都按这个顺序，对应 FRAMES 的前三项） */
    var MOOD_VIEWS = ["front", "side", "back"];

    var DEFAULT_MOOD = "like";     // 待机默认表情：微笑点赞，最接近"中性"，答对换开心才有对比
    var CLICK_MOOD = "cute";       // 点击公仔
    var OK_MOOD = "happy";         // 答对
    var STREAK_MOOD = "like";      // 连续答对 ≥2 题
    var WRONG_MOOD = "sad";        // 答错
    var REVIEW_MOOD = "cheer";     // 错题重练答对
    var IDLE_MOOD = "encourage";   // 长时间没动静

    var SENSITIVITY = 0.65;      // 每像素拖动旋转多少度
    var MAX_VELOCITY = 18;       // 惯性初速上限（度/帧），防止快速甩动转过好几圈
    var FRICTION = 0.92;         // 惯性衰减
    var FLOAT_AMPLITUDE = 8;     // 空闲摆动的角度幅度（越小越不容易看出两个视角的重影）
    var FLOAT_PERIOD = 6400;     // 空闲摆动周期（毫秒）
    var SETTLE_STEP = 4;         // 松手后每秒帧向最近视角靠拢的角度
    var SPIN_STEP = 7;           // 庆祝转圈时每帧转多少度（360 / 7 ≈ 51 帧 ≈ 0.9s）
    var CAPTION_MS = 3600;       // 字幕默认停留时间
    var IDLE_MOOD_MS = 60000;    // 空闲多久换成「鼓励」
    var STREAK_MOOD_FROM = 2;    // 连续答对到第几题换「点赞」

    /* 点击公仔时随机说一句（可根据 mood 分组） */
    var IDLE_WORDS = [
        "我是菲比，按住我左右拖一拖，看看我的背面～",
        "今天也要一起加油哦！",
        "有不认识的题就多想想，我会陪着你的。",
        "转一转我，正面、侧面、背面都看看～",
        "学累了就休息一下，我在这儿等你。"
    ];

    var HAPPY_WORDS = [
        "答对啦，太棒了！",
        "完全正确，你越来越厉害了！",
        "漂亮！菲比给你点赞～",
        "这道题难不倒你！"
    ];

    var SAD_WORDS = [
        "差一点点，我们一起看看解析吧。",
        "没关系，错了才知道哪里要补。",
        "别灰心，看完解析就会啦。",
        "再想一想，菲比相信你。"
    ];

    /* ---------------- 纯函数（可单测，不碰 DOM） ---------------- */

    function normalizeAngle(angle) {
        var value = Number(angle);
        if (!isFinite(value)) return 0;
        var result = value % 360;
        return result < 0 ? result + 360 : result;
    }

    /* 两个角度之间的最短夹角（0~180） */
    function angleDistance(a, b) {
        var diff = Math.abs(normalizeAngle(a) - normalizeAngle(b));
        return diff > 180 ? 360 - diff : diff;
    }

    /* 当前角度 → 四个视角的显示权重（相邻两个视角交叉淡化，权重和为 1） */
    function frameWeights(angle) {
        var raw = FRAMES.map(function (frame) {
            return Math.max(0, 1 - angleDistance(angle, frame.angle) / 90);
        });
        var total = raw.reduce(function (sum, value) { return sum + value; }, 0);
        if (total <= 0) {
            var fallback = raw.map(function () { return 0; });
            fallback[nearestFrameIndex(angle)] = 1;
            return fallback;
        }
        return raw.map(function (value) { return value / total; });
    }

    function nearestFrameIndex(angle) {
        var best = 0;
        var bestDistance = Infinity;
        FRAMES.forEach(function (frame, index) {
            var distance = angleDistance(angle, frame.angle);
            if (distance < bestDistance) {
                bestDistance = distance;
                best = index;
            }
        });
        return best;
    }

    /* 最接近的视角名（"front" / "side" / "back" / "side-mirror"） */
    function viewKeyForAngle(angle) {
        return FRAMES[nearestFrameIndex(angle)].key;
    }

    /* 最接近的视角角度（350° → 0°，而不是 → 270°） */
    function nearestFrameAngle(angle) {
        return FRAMES[nearestFrameIndex(angle)].angle;
    }

    /* 从 from 转到 to 的最短带符号角度差（-180 ~ 180） */
    function shortestDelta(from, to) {
        var diff = normalizeAngle(to) - normalizeAngle(from);
        if (diff > 180) diff -= 360;
        if (diff < -180) diff += 360;
        return diff;
    }

    /* 情绪名是否合法（拿不准的输入一律忽略，不换图） */
    function isMood(key) {
        return MOODS.some(function (mood) { return mood.key === key; });
    }

    function moodLabel(key) {
        var hit = MOODS.filter(function (mood) { return mood.key === key; })[0];
        return hit ? hit.label : "";
    }

    /* 情绪 + 视角 → 素材文件名 */
    function moodFile(mood, view) {
        return ASSET_DIR + (isMood(mood) ? mood : DEFAULT_MOOD) + "_" + view + ".png";
    }

    function pickRandom(list) {
        if (!list || !list.length) return "";
        return list[Math.floor(Math.random() * list.length)];
    }

    function esc(text) {
        return String(text == null ? "" : text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    /* ---------------- 语音（浏览器 TTS，可选） ---------------- */

    var VOICE_KEY = "xiaozhi.phoebeVoice";
    var STUDENT_KEY = "xiaozhi.student";

    /* 走后端 /api/phoebe/chat：读这个孩子的学习数据，由 DeepSeek 说一句 */
    var API = (typeof root.location !== "undefined" && /^https?:$/.test(root.location.protocol || ""))
        ? root.location.origin
        : "http://127.0.0.1:8000";
    var AI_TIMEOUT_MS = 14000;   // 前端等待上限（后端自己还有 8s 超时）
    var aiPending = false;       // 同一时间只发一个请求，狂点不会打出并发风暴

    var voice = {
        enabled: true,
        rate: 0.95,
        supported: typeof root.speechSynthesis !== "undefined"
            && typeof root.SpeechSynthesisUtterance === "function",
        voiceObj: null
    };

    function restoreVoiceSetting() {
        try {
            voice.enabled = root.localStorage.getItem(VOICE_KEY) !== "off";
        } catch (err) {
            voice.enabled = true;
        }
    }

    function storeVoiceSetting() {
        try {
            root.localStorage.setItem(VOICE_KEY, voice.enabled ? "on" : "off");
        } catch (err) {
            // 隐私模式下不记忆设置，不影响使用
        }
    }

    /* 优先挑中文音色，避免用英文音色读中文 */
    function pickChineseVoice() {
        if (!voice.supported) return null;
        var voices = root.speechSynthesis.getVoices() || [];
        var zh = voices.filter(function (item) {
            return (item.lang || "").toLowerCase().indexOf("zh") === 0;
        });
        return zh.find(function (item) {
            return /xiaoxiao|yaoyao|huihui|kangkang|chinese|中文|普通话/i.test(item.name);
        }) || zh[0] || null;
    }

    function refreshVoices() {
        voice.voiceObj = pickChineseVoice();
    }

    function stopSpeak() {
        if (!voice.supported) return;
        try {
            root.speechSynthesis.cancel();
        } catch (err) {
            // 语音服务不可用时忽略
        }
    }

    function speak(text) {
        if (!voice.supported || !voice.enabled || !text) return;

        try {
            stopSpeak();
            var utter = new root.SpeechSynthesisUtterance(String(text));
            utter.lang = "zh-CN";
            utter.rate = voice.rate;
            utter.pitch = 1.15;
            if (voice.voiceObj) utter.voice = voice.voiceObj;
            root.speechSynthesis.speak(utter);
        } catch (err) {
            // 朗读失败不影响字幕与动画
        }
    }

    function setVoiceEnabled(on) {
        voice.enabled = !!on;
        storeVoiceSetting();
        if (!voice.enabled) stopSpeak();
        return voice.enabled;
    }

    function currentStudentId() {
        try {
            var saved = root.localStorage ? root.localStorage.getItem(STUDENT_KEY) : null;
            var value = parseInt(saved || "1", 10);
            return isFinite(value) && value > 0 ? value : 1;
        } catch (err) {
            return 1;
        }
    }

    /* ---------------- 立牌实例 ---------------- */

    var activeViewer = null;

    function createViewer(container, options) {
        if (typeof document === "undefined" || !document.body) return null;

        var opts = options || {};
        var state = {
            angle: typeof opts.angle === "number" ? normalizeAngle(opts.angle) : 0,
            baseAngle: 0,
            dragging: false,
            velocity: 0,
            lastX: 0,
            moved: 0,
            floating: true,
            spinRemaining: 0,     // 庆祝转圈还剩多少度
            mood: DEFAULT_MOOD,   // 当前表情（与画面上真正显示的图一致）
            rafId: 0
        };
        state.baseAngle = state.angle;

        var stage = document.createElement("div");
        stage.className = "p3d-stage" + (opts.compact ? " p3d-compact" : "");

        var figure = document.createElement("div");
        figure.className = "p3d-figure";
        figure.setAttribute("role", "img");
        figure.setAttribute("aria-label", "菲比毛绒公仔，可左右拖动旋转");
        figure.tabIndex = 0;

        var images = FRAMES.map(function (frame) {
            var img = document.createElement("img");
            img.className = "p3d-frame" + (frame.mirror ? " p3d-mirror" : "");
            img.alt = "";
            img.draggable = false;
            figure.appendChild(img);
            return img;
        });

        var shadow = document.createElement("div");
        shadow.className = "p3d-shadow";
        figure.appendChild(shadow);

        var caption = document.createElement("p");
        caption.className = "p3d-caption";
        caption.setAttribute("role", "status");
        caption.setAttribute("aria-live", "polite");

        var hint = document.createElement("p");
        hint.className = "p3d-hint";
        hint.textContent = "按住拖动可以转身";

        stage.appendChild(figure);
        stage.appendChild(caption);
        stage.appendChild(hint);

        if (container && container.appendChild) {
            container.appendChild(stage);
        } else if (document.body) {
            stage.classList.add("p3d-floating");
            document.body.appendChild(stage);
        }

        var captionTimer = 0;
        var actionTimer = 0;
        var idleTimer = 0;
        var moodToken = 0;

        function render() {
            var weights = frameWeights(state.angle);
            images.forEach(function (img, index) {
                img.style.opacity = String(weights[index]);
            });
        }

        function setAngle(next) {
            state.angle = normalizeAngle(next);
            render();
            return state.angle;
        }

        /* ---------------- 表情（6 情绪 × 3 视角） ---------------- */

        /* 真正换图：4 个图层里 front/side/back 用新情绪的同名视角，270° 复用侧面的镜像 */
        function applyMood(mood) {
            state.mood = mood;
            images.forEach(function (img, index) {
                img.src = moodFile(mood, FRAMES[index].view);
            });
            return state.mood;
        }

        /**
         * 换表情。先把三个视角都预载好再一次性换 src，
         * 任何一张加载失败就**保持当前形象**（绝不留下白屏或者半新半旧）。
         * 返回目标情绪；实际换图可能在图片加载完成后（下一次事件循环）才发生。
         */
        function setMood(mood) {
            if (!isMood(mood)) return state.mood;
            scheduleIdleMood();

            moodToken += 1;
            var token = moodToken;
            if (mood === state.mood) return state.mood;

            /* 没有 Image（Node 单测 / 老浏览器）：直接换，不做预载 */
            if (typeof root.Image !== "function") return applyMood(mood);

            var urls = MOOD_VIEWS.map(function (view) { return moodFile(mood, view); });
            var loaded = 0;
            var failed = false;

            urls.forEach(function (url) {
                var probe = new root.Image();
                probe.onload = function () {
                    if (failed || token !== moodToken) return;
                    loaded += 1;
                    if (loaded === urls.length) applyMood(mood);
                };
                probe.onerror = function () {
                    // 某张图缺失：留在当前表情，立牌继续可用
                    failed = true;
                };
                probe.src = url;
            });

            return mood;
        }

        function currentMood() {
            return state.mood;
        }

        /* ---------------- 空闲换表情 ---------------- */

        function scheduleIdleMood() {
            if (idleTimer) root.clearTimeout(idleTimer);
            idleTimer = root.setTimeout(function () {
                idleTimer = 0;
                setMood(IDLE_MOOD);
            }, IDLE_MOOD_MS);
        }

        /* 空闲摆动 + 惯性 + 停靠 + 庆祝转圈，统一在这一个循环里推进 */
        function tick(time) {
            state.rafId = root.requestAnimationFrame(tick);

            if (state.dragging) {
                state.velocity = 0;
                return;
            }

            /* 1) 庆祝转圈：连续转，不是瞬间跳变 */
            if (state.spinRemaining > 0) {
                var spin = Math.min(SPIN_STEP, state.spinRemaining);
                state.angle = normalizeAngle(state.angle + spin);
                state.baseAngle = normalizeAngle(state.baseAngle + spin);
                state.spinRemaining -= spin;
                render();
                return;
            }

            /* 2) 拖动惯性 */
            if (Math.abs(state.velocity) > 0.05) {
                state.angle = normalizeAngle(state.angle + state.velocity);
                state.velocity *= FRICTION;
                state.baseAngle = state.angle;
                render();
                return;
            }

            state.velocity = 0;

            /* 3) 停靠：慢慢转到最近的视角。
                  三个真实视角之间的角度是插值出来的"重影"，停在那里不好看，
                  所以松手后自动归到最近的正面 / 侧面 / 背面。 */
            var target = nearestFrameAngle(state.baseAngle);
            var diff = shortestDelta(state.baseAngle, target);
            if (Math.abs(diff) > 0.5) {
                var step = (diff > 0 ? 1 : -1) * Math.min(Math.abs(diff), SETTLE_STEP);
                state.baseAngle = normalizeAngle(state.baseAngle + step);
                state.angle = state.baseAngle;
                render();
                return;
            }

            /* 4) 已经停稳：轻微摆动，让公仔看起来是活的 */
            if (opts.autoFloat === false) return;

            var phase = (time % FLOAT_PERIOD) / FLOAT_PERIOD * Math.PI * 2;
            state.angle = normalizeAngle(state.baseAngle + Math.sin(phase) * FLOAT_AMPLITUDE);
            render();
        }

        function onPointerDown(event) {
            state.dragging = true;
            state.moved = 0;
            state.velocity = 0;
            state.lastX = event.clientX;
            scheduleIdleMood();
            stage.classList.add("p3d-grabbing");
            if (figure.setPointerCapture && event.pointerId !== undefined) {
                try {
                    figure.setPointerCapture(event.pointerId);
                } catch (err) {
                    // 某些浏览器不支持指针捕获，退化为窗口监听
                }
            }
            if (event.preventDefault) event.preventDefault();
        }

        function onPointerMove(event) {
            if (!state.dragging) return;
            var dx = event.clientX - state.lastX;
            state.lastX = event.clientX;
            state.moved += Math.abs(dx);

            var delta = dx * SENSITIVITY;
            if (delta > MAX_VELOCITY) delta = MAX_VELOCITY;
            if (delta < -MAX_VELOCITY) delta = -MAX_VELOCITY;

            state.velocity = delta;
            state.angle = normalizeAngle(state.angle + delta);
            state.baseAngle = state.angle;
            render();
        }

        function onPointerUp() {
            if (!state.dragging) return;
            state.dragging = false;
            stage.classList.remove("p3d-grabbing");
            // 拖动距离很短才算"点击"：这时换成可爱表情，并让菲比结合学习数据说一句
            if (state.moved < 6) askAi("click");
        }

        function onKeyDown(event) {
            var step = event.key === "ArrowLeft" ? -15 : (event.key === "ArrowRight" ? 15 : 0);
            if (!step) return;
            state.baseAngle = normalizeAngle(state.baseAngle + step);
            setAngle(state.baseAngle);
            scheduleIdleMood();
            if (event.preventDefault) event.preventDefault();
        }

        figure.addEventListener("pointerdown", onPointerDown);
        figure.addEventListener("keydown", onKeyDown);
        if (root.addEventListener) {
            root.addEventListener("pointermove", onPointerMove);
            root.addEventListener("pointerup", onPointerUp);
            root.addEventListener("pointercancel", onPointerUp);
        }

        /* 动作：跳跃 / 摇头，CSS 动画驱动，不阻塞拖动；顺便把表情换成对应的那张 */
        function react(kind) {
            var cls = kind === "happy" ? "p3d-happy" : (kind === "sad" ? "p3d-sad" : "p3d-think");
            figure.classList.remove("p3d-happy", "p3d-sad", "p3d-think");
            // 强制重排，保证同一个动作可以连续触发
            void figure.offsetWidth;
            figure.classList.add(cls);
            if (actionTimer) root.clearTimeout(actionTimer);
            actionTimer = root.setTimeout(function () {
                figure.classList.remove(cls);
                actionTimer = 0;
            }, kind === "happy" ? 1400 : 1000);

            if (kind === "happy") {
                setMood(OK_MOOD);
                // 欢呼时原地转一圈（在 tick 里连续推进，避免瞬间跳变）
                state.velocity = 0;
                state.spinRemaining += 360;
            } else if (kind === "sad") {
                setMood(WRONG_MOOD);
            }
            return kind;
        }

        /* 原地转一圈（外部也可调用，例如答对时的额外庆祝） */
        function spinOnce() {
            state.velocity = 0;
            state.spinRemaining += 360;
            return true;
        }

        function showCaption(text, duration) {
            if (!text) return "";
            caption.innerHTML = esc(text);
            caption.classList.add("p3d-caption-show");
            if (captionTimer) root.clearTimeout(captionTimer);
            captionTimer = root.setTimeout(function () {
                caption.classList.remove("p3d-caption-show");
                captionTimer = 0;
            }, typeof duration === "number" ? duration : CAPTION_MS);
            return text;
        }

        function say(text, options) {
            var conf = options || {};
            if (!text) return "";
            scheduleIdleMood();
            showCaption(text, conf.duration);
            if (conf.speak !== false) speak(text);
            return text;
        }

        /* 台词显示多久：按字数估朗读时间，长句子不要一闪而过 */
        function lineDuration(text) {
            var length = String(text || "").length;
            return Math.max(3200, Math.min(12000, length * 260));
        }

        /**
         * 让后端说一句话（DeepSeek + 这个孩子的学习数据）。
         * 点击立牌时调用；请求期间先显示"正在看你的学习情况…"，
         * 失败 / 超时 / 后端没有 key 都退回本地文案，绝不让立牌卡住。
         */
        function askAi(trigger, options) {
            var conf = options || {};
            var fallbackWord = conf.fallback || pickRandom(IDLE_WORDS);

            /* 点击就换个表情，哪怕后端没返回也已经有反馈 */
            setMood(conf.mood || CLICK_MOOD);

            if (aiPending) return null;
            if (typeof root.fetch !== "function") {
                say(fallbackWord, { duration: lineDuration(fallbackWord) });
                return null;
            }

            aiPending = true;
            showCaption(conf.thinking || "让菲比看看你的学习情况…", AI_TIMEOUT_MS);

            var finished = false;
            var timer = root.setTimeout(function () {
                finish(fallbackWord);
            }, AI_TIMEOUT_MS);

            function finish(text) {
                if (finished) return;
                finished = true;
                aiPending = false;
                root.clearTimeout(timer);
                say(text, { duration: lineDuration(text) });
            }

            try {
                root.fetch(API + "/api/phoebe/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        student_id: currentStudentId(),
                        trigger: trigger || "click",
                        knowledge: conf.knowledge || "",
                        correct: typeof conf.correct === "boolean" ? conf.correct : null
                    })
                })
                    .then(function (response) {
                        if (!response.ok) throw new Error("HTTP " + response.status);
                        return response.json();
                    })
                    .then(function (data) {
                        var text = (data && data.text) || "";
                        if (!text) throw new Error("empty line");
                        finish(text);
                        return text;
                    })
                    .catch(function () {
                        finish(fallbackWord);
                    });
            } catch (err) {
                finish(fallbackWord);
            }

            return null;
        }

        function destroy() {
            if (state.rafId) root.cancelAnimationFrame(state.rafId);
            if (captionTimer) root.clearTimeout(captionTimer);
            if (actionTimer) root.clearTimeout(actionTimer);
            if (idleTimer) root.clearTimeout(idleTimer);
            if (root.removeEventListener) {
                root.removeEventListener("pointermove", onPointerMove);
                root.removeEventListener("pointerup", onPointerUp);
                root.removeEventListener("pointercancel", onPointerUp);
            }
            if (stage.parentNode) stage.parentNode.removeChild(stage);
        }

        var viewer = {
            el: stage,
            figure: figure,
            images: images,
            state: state,
            setAngle: setAngle,
            getAngle: function () { return state.angle; },
            viewKey: function () { return viewKeyForAngle(state.angle); },
            react: react,
            spinOnce: spinOnce,
            setMood: setMood,
            mood: currentMood,
            moodLabel: function () { return moodLabel(state.mood); },
            askAi: askAi,
            say: say,
            showCaption: showCaption,
            speak: speak,
            destroy: destroy
        };

        render();
        applyMood(state.mood);
        scheduleIdleMood();
        if (root.requestAnimationFrame) {
            state.rafId = root.requestAnimationFrame(tick);
        }
        renderCollection();
        activeViewer = viewer;
        return viewer;
    }

    function phoebe3dMount(container, options) {
        return createViewer(container, options);
    }

    /* 页面里放了 <div data-phoebe3d></div> 就挂进去，否则挂成左侧浮动立牌 */
    function phoebe3dAutoMount(options) {
        if (typeof document === "undefined" || !document.body) return null;
        if (activeViewer) return activeViewer;

        var host = document.querySelector ? document.querySelector("[data-phoebe3d]") : null;
        return createViewer(host || null, options);
    }

    function phoebe3dViewer() {
        return activeViewer;
    }

    /* 全局快捷：作用于当前立牌 */
    function phoebe3dSay(text, options) {
        return activeViewer ? activeViewer.say(text, options) : "";
    }

    function phoebe3dReact(kind, options) {
        if (!activeViewer) return "";
        var conf = options || {};
        activeViewer.react(kind);
        if (conf.mood) activeViewer.setMood(conf.mood);
        if (conf.text) activeViewer.say(conf.text, conf);
        return kind;
    }

    /* 让菲比结合学习数据说一句（走后端 + DeepSeek） */
    function phoebe3dAsk(trigger, options) {
        return activeViewer ? activeViewer.askAi(trigger, options) : null;
    }

    /**
     * 换表情（不传参数就是读当前表情）。
     * phoebe3dMood("cheer") → 换成"加油"；返回生效/待生效的情绪名。
     */
    function phoebe3dMood(mood) {
        if (!activeViewer) return "";
        if (mood === undefined || mood === null) return activeViewer.mood();
        return activeViewer.setMood(mood);
    }

    /**
     * 答题反馈统一入口（今日学习页 / 自由练习页 / 错题本共用）。
     * 参数：
     *   correct  是否答对
     *   options.word      自定义字幕文案
     *   options.mood      指定表情（例：错题本重练传 "cheer"）
     *   options.celebrateDuration  表情包浮层停留时间
     * 答对：换"开心"跳跃转圈 + 弹菲比表情包（若 phoebe.js 已加载）+ 字幕；
     *       连续答对 ≥2 题换成"点赞"
     * 答错：换"难过"摇头 + 语音提示 + 字幕
     */
    function phoebe3dFeedback(correct, options) {
        var opts = options || {};
        var text = opts.word || (correct ? pickRandom(HAPPY_WORDS) : pickRandom(SAD_WORDS));

        if (correct) {
            /* celebrateCorrect 会累计连对数（phoebe.js 没加载时拿不到，按 1 处理） */
            var streak = 1;
            if (typeof root.celebrateCorrect === "function") {
                var reported = Number(root.celebrateCorrect({ word: text, duration: opts.celebrateDuration }));
                if (isFinite(reported) && reported > 0) streak = reported;
            }
            if (activeViewer) {
                activeViewer.react("happy");
                activeViewer.setMood(opts.mood || (streak >= STREAK_MOOD_FROM ? STREAK_MOOD : OK_MOOD));
                // 表情包浮层自带欢呼人声，这里只出字幕不出 TTS，避免两个声音打架
                activeViewer.showCaption(text, opts.duration);
            }
        } else {
            if (typeof root.phoebeResetStreak === "function") root.phoebeResetStreak();
            if (activeViewer) {
                if (opts.mood) activeViewer.setMood(opts.mood);
                activeViewer.react("sad");
                activeViewer.say(text, { duration: opts.duration });
            }
        }

        return text;
    }

    /* 语音开关（页面上可以放一个勾选框调用它） */
    function phoebe3dSetVoice(on) {
        return setVoiceEnabled(on);
    }

    function phoebe3dVoiceEnabled() {
        return voice.enabled;
    }

    restoreVoiceSetting();
    if (voice.supported) {
        refreshVoices();
        try {
            root.speechSynthesis.onvoiceschanged = refreshVoices;
        } catch (err) {
            // 忽略：拿不到音色列表时用系统默认音色
        }
    }

    /* ---------------- V2.6 菲比收藏：等级每提升一次，左侧空白处就多一只菲比 ---------------- */

    var COLLECT_PREFIX = "xiaozhi.phoebe.fumo.";   // 按学生分键，两个小朋友的收藏互不串
    var COLLECT_MOODS = ["like", "cheer", "cute", "encourage"];  // 排除答对(happy)/答错(sad)两种表情
    var COLLECT_MAX = 12;                          // 左栏最多留 12 只，不挤满屏幕

    function collectKey() {
        return COLLECT_PREFIX + currentStudentId();
    }

    /* 读收藏：读不到或数据坏了都当空数组，绝不影响学习 */
    function readCollection() {
        var raw = null;
        try {
            raw = root.localStorage ? root.localStorage.getItem(collectKey()) : null;
        } catch (err) {
            raw = null;
        }
        if (!raw) return [];

        var list = null;
        try {
            list = JSON.parse(raw);
        } catch (err) {
            list = null;
        }
        if (!list || !list.length) return [];

        return list.filter(function (mood) {
            return isMood(mood) && COLLECT_MOODS.indexOf(mood) !== -1;
        });
    }

    function writeCollection(list) {
        try {
            if (root.localStorage) root.localStorage.setItem(collectKey(), JSON.stringify(list));
        } catch (err) {
            // 本地存储不可用（隐私模式等）：收藏只在本次页面里存在，不影响学习
        }
    }

    /* 收藏容器只建一次：缓存引用，避免每次升级都新建一块（也便于 Node 沙箱里测试） */
    var collectionEl = null;

    function collectionBox() {
        if (typeof document === "undefined" || !document.body) return null;
        if (collectionEl) return collectionEl;

        var box = document.getElementById ? document.getElementById("p3d-collection") : null;
        if (!box) {
            box = document.createElement("div");
            box.id = "p3d-collection";
            box.className = "p3d-collection";
            box.setAttribute("aria-hidden", "true");
            document.body.appendChild(box);
        }
        collectionEl = box;
        return box;
    }

    /* 把收藏画到左侧空白处；一只都没有就整块隐藏，不占位置 */
    function renderCollection() {
        var box = collectionBox();
        if (!box) return [];

        var list = readCollection();
        box.innerHTML = "";
        if (!list.length) {
            box.classList.add("p3d-collection-hidden");
            return list;
        }

        box.classList.remove("p3d-collection-hidden");
        list.forEach(function (mood) {
            var img = document.createElement("img");
            img.className = "p3d-fumo";
            img.src = moodFile(mood, "front");
            img.alt = "菲比收藏：" + moodLabel(mood);
            img.draggable = false;
            box.appendChild(img);
        });
        return list;
    }

    /**
     * 新增一只菲比（等级提升时调用）。
     * 规则：只从 like/cheer/cute/encourage 里挑；不用现在立牌上正在显示的那张表情；
     * 优先挑还没收藏过的，全收藏过就循环；超过上限先丢最旧的。
     * 返回真正加进去的表情名。
     */
    function collectFumo(mood) {
        var list = readCollection();
        var shown = activeViewer && activeViewer.mood ? activeViewer.mood() : "";
        var pick = (mood && isMood(mood) && COLLECT_MOODS.indexOf(mood) !== -1) ? mood : "";

        if (!pick || pick === shown) {
            var pool = COLLECT_MOODS.filter(function (item) { return item !== shown; });
            var fresh = pool.filter(function (item) { return list.indexOf(item) === -1; });
            pick = (fresh.length ? fresh : pool)[0] || COLLECT_MOODS[0];
        }

        list.push(pick);
        while (list.length > COLLECT_MAX) list.shift();
        writeCollection(list);
        renderCollection();
        return pick;
    }

    var api = {
        ASSET_DIR: ASSET_DIR,
        FRAMES: FRAMES,
        MOODS: MOODS,
        MOOD_VIEWS: MOOD_VIEWS,
        DEFAULT_MOOD: DEFAULT_MOOD,
        IDLE_MOOD: IDLE_MOOD,
        IDLE_MOOD_MS: IDLE_MOOD_MS,
        IDLE_WORDS: IDLE_WORDS,
        HAPPY_WORDS: HAPPY_WORDS,
        SAD_WORDS: SAD_WORDS,
        normalizeAngle: normalizeAngle,
        angleDistance: angleDistance,
        frameWeights: frameWeights,
        nearestFrameIndex: nearestFrameIndex,
        nearestFrameAngle: nearestFrameAngle,
        shortestDelta: shortestDelta,
        viewKeyForAngle: viewKeyForAngle,
        isMood: isMood,
        moodLabel: moodLabel,
        moodFile: moodFile,
        mount: phoebe3dMount,
        autoMount: phoebe3dAutoMount,
        viewer: phoebe3dViewer,
        say: phoebe3dSay,
        react: phoebe3dReact,
        ask: phoebe3dAsk,
        feedback: phoebe3dFeedback,
        mood: phoebe3dMood,
        setVoice: phoebe3dSetVoice,
        voiceEnabled: phoebe3dVoiceEnabled,
        currentStudentId: currentStudentId,
        API: API,
        COLLECT_MOODS: COLLECT_MOODS,
        COLLECT_MAX: COLLECT_MAX,
        collect: collectFumo,
        collection: readCollection,
        renderCollection: renderCollection
    };

    root.PHOEBE3D = api;
    root.phoebe3dMount = phoebe3dMount;
    root.phoebe3dAutoMount = phoebe3dAutoMount;
    root.phoebe3dViewer = phoebe3dViewer;
    root.phoebe3dSay = phoebe3dSay;
    root.phoebe3dReact = phoebe3dReact;
    root.phoebe3dAsk = phoebe3dAsk;
    root.phoebe3dFeedback = phoebe3dFeedback;
    root.phoebe3dMood = phoebe3dMood;
    root.phoebe3dSetVoice = phoebe3dSetVoice;
    root.phoebe3dCollect = collectFumo;
    root.phoebe3dCollection = readCollection;
    root.phoebe3dRenderCollection = renderCollection;
    /* 页面没有自己挂载时，DOM 就绪后自动挂一个浮动立牌 */
    if (typeof document !== "undefined" && document.addEventListener && !root.__PHOEBE3D_NO_AUTO__) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", function () { phoebe3dAutoMount(); });
        } else {
            phoebe3dAutoMount();
        }
    }

    // 便于 Node 里直接 require 做单测
    if (typeof module !== "undefined" && module.exports) module.exports = api;

})(typeof window !== "undefined" ? window : globalThis);
