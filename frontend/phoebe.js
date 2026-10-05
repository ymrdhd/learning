// ==============================================================
// 能力契约｜答对庆祝浮层（菲比素材 + 音效），零后端依赖，三处答题页共用
// 入口：celebrateCorrect / phoebeResetStreak / phoebe / ASSET_DIR
// 依赖：无（零构建）；素材在 assets/phoebe/
// 不负责：业务答题逻辑 → 各页脚本
// 验证：node frontend/verify_phoebe_web.js
// 被调用：index.html、diagnostic_test.html、wrong_book.html（**必须先于业务 js 加载**）
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================

/*
 * 菲比（Phoebe）答对庆祝模块。
 *
 * 素材来自 https://github.com/Genius-Society/phoebe_chubby
 * 放在 assets/phoebe/ 下，答对时随机弹出一张表情包并播放音效。
 *
 * 用法：页面里先引入本文件（<script src="phoebe.js"></script>），
 *       答对时调用 celebrateCorrect() 即可。
 *
 * 该文件不依赖任何其他脚本或后端接口，可以单独在浏览器里跑。
 */

(function (root) {
    "use strict";

    var ASSET_DIR = "assets/phoebe/";

    // 表情包图片：来自仓库 img/ 目录
    var IMAGES = [
        "phoebe_0.png",
        "phoebe_1.png",
        "phoebe_2.png",
        "phoebe.png"
    ];

    // 音效：来自仓库 audio/ 目录，短促的人声片段
    var SOUNDS = [
        "cheer_0.mp3",
        "cheer_1.mp3",
        "cheer_2.mp3"
    ];

    // 庆祝文案，随机搭配，避免每道题看到同一句话
    var WORDS = [
        "答对啦，菲比给你比个耶！",
        "太厉害了，菲比都惊呆了！",
        "完全正确，继续保持！",
        "这道题难不倒你，菲比为你鼓掌！",
        "漂亮！菲比给你点赞 👍"
    ];

    var OVERLAY_ID = "phoebe-celebrate";
    var AUTO_HIDE_MS = 1600;   // 自动消失时间，不挡住下一题
    var NEXT_WORD_EVERY = 3;   // 连续答对多少题换一句更兴奋的文案

    var streak = 0;            // 连续答对计数
    var hideTimer = null;
    var lastImage = "";

    function pickRandom(list) {
        if (!list || !list.length) return "";
        return list[Math.floor(Math.random() * list.length)];
    }

    /* 尽量不和上一张重复，让表情包有变化 */
    function pickImage() {
        if (IMAGES.length < 2) return IMAGES[0] || "";
        var next = pickRandom(IMAGES);
        if (next === lastImage) {
            next = IMAGES[(IMAGES.indexOf(next) + 1) % IMAGES.length];
        }
        lastImage = next;
        return next;
    }

    function pickWord() {
        // 连续答对越多，越容易抽到夸奖；简单起见按连胜数轮换
        if (streak >= NEXT_WORD_EVERY) {
            return "连对 " + streak + " 题！菲比给你撒花 🎉";
        }
        return pickRandom(WORDS);
    }

    function playSound() {
        if (typeof root.Audio !== "function") return;

        try {
            var audio = new root.Audio(ASSET_DIR + pickRandom(SOUNDS));
            audio.volume = 0.6;
            var played = audio.play();
            // 浏览器自动播放策略可能拒绝，静默忽略即可（图片照常显示）
            if (played && typeof played.catch === "function") played.catch(function () {});
        } catch (err) {
            // 音频不可用时不影响庆祝动画
        }
    }

    function buildOverlay() {
        var box = document.createElement("div");
        box.id = OVERLAY_ID;
        box.className = "phoebe-celebrate";
        box.setAttribute("role", "status");
        box.setAttribute("aria-live", "polite");
        document.body.appendChild(box);
        return box;
    }

    function getOverlay() {
        if (typeof document === "undefined" || !document.body) return null;
        return document.getElementById(OVERLAY_ID) || buildOverlay();
    }

    function hideOverlay(box) {
        box.className = "phoebe-celebrate";
        box.innerHTML = "";
    }

    /**
     * 答对后的庆祝动画：随机弹出一张菲比表情包 + 播放音效。
     * 参数 options：
     *   word    自定义文案（不传则随机）
     *   sound   是否播放音效，默认 true
     *   duration 显示时长（毫秒），默认 1600
     * 返回当前连续答对题数。
     */
    function celebrateCorrect(options) {
        var opts = options || {};
        streak += 1;

        var box = getOverlay();
        if (!box) return streak;   // 非浏览器环境（如无 DOM 的测试）直接跳过

        if (hideTimer) {
            clearTimeout(hideTimer);
            hideTimer = null;
        }

        var word = opts.word || pickWord();
        var img = pickImage();

        box.innerHTML =
            '<div class="phoebe-card">' +
                '<img class="phoebe-img" src="' + ASSET_DIR + img + '" alt="菲比庆祝表情包">' +
                '<p class="phoebe-word">' + word + "</p>" +
            "</div>";
        box.className = "phoebe-celebrate show";

        if (opts.sound !== false) playSound();

        var duration = typeof opts.duration === "number" ? opts.duration : AUTO_HIDE_MS;
        hideTimer = setTimeout(function () {
            hideOverlay(box);
            hideTimer = null;
        }, duration);

        return streak;
    }

    /* 答错时重置连胜，不影响界面 */
    function resetStreak() {
        streak = 0;
    }

    function currentStreak() {
        return streak;
    }

    var api = {
        celebrateCorrect: celebrateCorrect,
        resetStreak: resetStreak,
        currentStreak: currentStreak,
        IMAGES: IMAGES,
        SOUNDS: SOUNDS
    };

    root.celebrateCorrect = celebrateCorrect;
    root.phoebeResetStreak = resetStreak;
    root.phoebe = api;

    // 便于 Node 里直接 require 做单测
    if (typeof module !== "undefined" && module.exports) module.exports = api;

})(typeof window !== "undefined" ? window : globalThis);
