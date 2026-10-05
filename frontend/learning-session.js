// ==============================================================
// 能力契约｜统一学习会话（V2.6）：一次「开始今天的学习」跑完今天所有微任务，跑完就结束
// 入口：LearningSession.init / start / choose / tick / completeCurrent / recordAnswer /
//       mayContinue / progress / currentTask / pendingTasks / syncTask / finish / reset / studentChanged
// 依赖：fetch（零构建，无框架）；可选读取 window.UIShell 取当前学生
// 不负责：题目渲染与判分 → today.js / app.js；出题与自适应算法 → 后端 adaptive / habit / review
// 验证：node frontend/verify_v26_web.js
// 被调用：today.html（学习页），其它儿童端页面可选
// 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
// ==============================================================
/*
 * 孩子点一次「开始今天的学习」，剩下的都由本模块串起来：
 *
 *     开始今天的学习 → 任务1 → 任务2 → 任务3 → 今日完成（结束）
 *
 * 三条硬规矩（对应 V2.6 §13 / §19 / §20）：
 *  1. 完成一个任务后**不回首页重新选**，直接进下一个任务；
 *  2. 今日任务全部完成后 `mayContinue()` 立刻变 false —— 调用方必须停在这里，
 *     不允许"再来一题""再学 5 分钟"（没有无限学习流）；
 *  3. 切换学生时 `studentChanged()` 清空全部会话状态，绝不残留上一个孩子的数据。
 */
(function (root) {
    "use strict";

    var API = (typeof location !== "undefined" && /^https?:$/.test(location.protocol || ""))
        ? location.origin.replace(/\/app\/?$/, "")
        : "http://127.0.0.1:8000";

    var PET_TEXT = {
        new_learning: "🌱 新知识",
        weakness: "🌿 薄弱训练",
        review: "🌳 复习",
        wrong_recovery: "⚔️ 挑战",
        active_recall: "🧠 主动回忆"
    };

    var handlers = { onReady: null, onTask: null, onProgress: null, onFinish: null, onReset: null };

    var session = {
        studentId: 0,
        tasks: [],
        currentIndex: -1,
        done: {},
        minutes: 0,
        finished: false,
        loaded: false
    };

    function noop() {}

    function emit(name, payload) {
        var fn = handlers[name];
        if (typeof fn === "function") {
            try {
                fn(payload);
            } catch (err) {
                // 页面回调出错不能打断学习流程
            }
        }
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

    function studentIdOf() {
        if (session.studentId) return session.studentId;
        if (root.UIShell && root.UIShell.getStudentId) {
            var id = parseInt(root.UIShell.getStudentId(), 10);
            if (!isNaN(id)) return id;
        }
        return 1;
    }

    function taskIdOf(task) {
        return parseInt((task || {}).task_id || 0, 10) || 0;
    }

    function taskKey(task) {
        var t = task || {};
        return taskIdOf(t) + "|" + (t.task_type || "") + "|" + (t.subject || "") + "|" + (t.knowledge || "");
    }

    function isDone(task) {
        var t = task || {};
        if (t.status === "done") return true;
        return !!session.done[taskKey(t)] || !!session.done[String(taskIdOf(t))];
    }

    function pendingTasks() {
        return session.tasks.filter(function (task) { return !isDone(task); });
    }

    function progress() {
        var total = session.tasks.length;
        var done = session.tasks.filter(isDone).length;
        return {
            total: total,
            done: done,
            remaining: Math.max(0, total - done),
            minutes: session.minutes,
            percent: total ? Math.round(done * 100 / total) : 0,
            finished: session.finished || (total > 0 && done >= total)
        };
    }

    /* 全部今日任务已完成 → 学习必须结束（V2.6 §19）。 */
    function mayContinue() {
        if (!session.loaded) return true;
        var p = progress();
        if (session.finished && p.total > 0) return false;
        return p.remaining > 0;
    }

    function currentTask() {
        return session.currentIndex >= 0 ? (session.tasks[session.currentIndex] || null) : null;
    }

    /* V2.6：当前题型已经刷完（或压根没有当前任务）→ 自动切到下一个未完成的题型。
       返回 { continue, changed, task }：
         continue=false —— 今天没有可做的任务了（调用方必须停下，让今日完成页接住）
         changed=true   —— 已切到新题型（onTask → beginTask 会重新出题，调用方本次不要重复出题）
       出题前必须先过这一关，否则会出现「这个题型已经刷完，还继续出它」。 */
    function syncTask() {
        if (!session.loaded) return { continue: true, changed: false, task: null };
        var task = currentTask();
        if (task && !isDone(task)) return { continue: true, changed: false, task: task };

        var next = pendingTasks()[0];
        if (!next) {
            if (task) finish();
            return { continue: false, changed: false, task: null };
        }
        choose(taskIdOf(next));
        return { continue: true, changed: true, task: next };
    }

    function init(options) {
        var opts = options || {};
        handlers.onReady = opts.onReady || null;
        handlers.onTask = opts.onTask || null;
        handlers.onProgress = opts.onProgress || null;
        handlers.onFinish = opts.onFinish || null;
        handlers.onReset = opts.onReset || null;
        return session;
    }

    function reset(silent) {
        session.tasks = [];
        session.currentIndex = -1;
        session.done = {};
        session.minutes = 0;
        session.finished = false;
        session.loaded = false;
        if (!silent) emit("onReset", null);
    }

    function setTasks(tasks) {
        session.tasks = (tasks || []).slice(0);
        session.loaded = true;
        return session.tasks;
    }

    /* 开始今天的学习：POST /api/tasks/start 拿到今日固定边界内的微任务清单。 */
    function start() {
        session.studentId = studentIdOf();
        reset(true);
        var sid = session.studentId;
        return postJson(API + "/api/tasks/start", { student_id: sid })
            .then(function (data) {
                setTasks((data || {}).tasks || []);
                session.finished = session.tasks.length === 0;
                emit("onReady", { tasks: session.tasks, plan: (data || {}).plan || null,
                    summary: (data || {}).summary || null });
                emit("onProgress", progress());
                var first = pendingTasks()[0];
                if (first) choose(taskIdOf(first)); else finish();
                return data;
            });
    }

    /* 有限自主选择：孩子可以决定先做哪个任务，知识点与难度仍由系统决定。 */
    function choose(taskId) {
        var id = parseInt(taskId, 10) || 0;
        var index = -1;
        for (var i = 0; i < session.tasks.length; i++) {
            if (taskIdOf(session.tasks[i]) === id) { index = i; break; }
        }
        if (index < 0) index = session.tasks.indexOf(pendingTasks()[0]);
        if (index < 0) return null;
        session.currentIndex = index;
        emit("onTask", session.tasks[index]);
        return session.tasks[index];
    }

    function taskLabel(task) {
        var t = task || {};
        if (t.task_type_text) return t.task_type_text;
        return PET_TEXT[t.task_type] || "今天的小任务";
    }

    function completeCurrent() {
        var task = currentTask();
        if (!task) return Promise.resolve(null);
        return acknowledge(task, task.target_minutes || task.minutes || 0);
    }

    /* 把一个任务标记完成（后端累计时长与题量，达到目标就 status=done）。 */
    function acknowledge(task, minutes) {
        var sid = studentIdOf();
        var id = taskIdOf(task);
        var spent = Math.max(0, parseInt(minutes, 10) || 0);
        session.done[taskKey(task)] = true;
        if (id) session.done[String(id)] = true;
        session.minutes += spent;
        var payload = { student_id: sid, task_id: id, minutes: spent, done: true };
        var request = id
            ? postJson(API + "/api/tasks/complete", payload).catch(function () { return null; })
            : Promise.resolve(null);
        return request.then(function () {
            emit("onProgress", progress());
            var next = pendingTasks()[0];
            if (next) {
                choose(taskIdOf(next));
            } else {
                finish();
            }
            return task;
        });
    }

    /* 每答一题都看一眼：任务做够了就自动收尾，孩子不用回首页。 */
    function tick(options) {
        var info = options || {};
        if (!session.loaded || session.finished) return progress();
        var task = currentTask();
        if (!task) return progress();
        var target = parseInt(task.target_count || task.target_minutes || 0, 10) || 0;
        // V2.6：complete_count 只是任务快照（不会随后端累加自动更新），必须本地累计；
        // 否则 target>1 的任务每次都只算 1 题，永远判不达标 —— 孩子会一直刷同一科
        var asked = (parseInt(task.complete_count || 0, 10) || 0) + (info.count || 1);
        task.complete_count = asked;
        emit("onProgress", progress());
        if (target && asked >= target) {
            acknowledge(task, parseInt(task.duration_minutes || task.minutes || 0, 10) || 0);
        }
        return progress();
    }

    function recordAnswer(correct, minutes) {
        return tick({ count: 1, correct: !!correct, minutes: minutes || 0 });
    }

    /* 今日完成页：孩子看到今天学了多少，然后可以离开（不再提供加练按钮）。 */
    function finish() {
        if (session.finished && session.summary) return Promise.resolve(session.summary);
        session.finished = true;
        session.currentIndex = -1;
        var sid = studentIdOf();
        return jsonFetch(API + "/api/daily-summary/" + sid)
            .then(function (data) { return remember(data); })
            .catch(function () { return remember(null); });
    }

    function remember(data) {
        session.summary = data || null;
        emit("onProgress", progress());
        emit("onFinish", session.summary);
        return session.summary;
    }

    function studentChanged(id) {
        session.studentId = parseInt(id, 10) || 0;
        reset(false);
        return session;
    }

    function state() {
        return {
            studentId: studentIdOf(),
            loaded: session.loaded,
            finished: session.finished,
            current: currentTask(),
            tasks: session.tasks.slice(0),
            progress: progress()
        };
    }

    root.LearningSession = {
        API: API,
        PET_TEXT: PET_TEXT,
        init: init,
        start: start,
        choose: choose,
        chooseTask: choose,
        taskLabel: taskLabel,
        tick: tick,
        recordAnswer: recordAnswer,
        completeCurrent: completeCurrent,
        acknowledge: acknowledge,
        mayContinue: mayContinue,
        progress: progress,
        currentTask: currentTask,
        pendingTasks: pendingTasks,
        isDone: isDone,
        syncTask: syncTask,
        setTasks: setTasks,
        finish: finish,
        reset: reset,
        studentChanged: studentChanged,
        state: state,
        _noop: noop
    };
})(typeof window !== "undefined" ? window : this);
