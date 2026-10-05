# ==============================================================
# 能力契约｜V2.6 儿童体验套件：首页聚合 / 知识地图 / 成长中心 / 挑战中心 / 学习会话边界 / 双学生隔离
# 入口：check / home_case / map_case / growth_case / challenge_case / seed_case /
#       session_case / regression_case / start_server / main
# 依赖：os sys json socket subprocess time、requests、main（真实 app）、kid_status、
#       database（SessionLocal/engine）、models、kid_status
# 不负责：修 bug（只记录缺陷）→ Lead；算法实现 → 各引擎模块；其它套件 → verify_all.py
# 验证：python backend/verify_v26.py（端口 8913 · 临时库 _verify_v26.db）
# 被调用：人工 / verify_all.py（套件 key = v26）
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================

"""V2.6 儿童体验门禁套件（SPEC §四十九 · key=v26 · port=8913）。

覆盖：首页聚合接口一次给全（学生/今日计划/进度/待复习/待挑战/成长亮点/菲比问候，主按钮文案正确，
不暴露算法原始字段）/ 学生不存在返回 200 空结构 / date 非法 400 / 知识地图来自真实掌握度且未学知识
不显示成 0 分、未掌握知识不能被解锁 / 成长中心周数据与时间线、days 上限 30 / 挑战中心 🔴🟡🟢 与
V2.5 康复数据一致且不泄露答案 / 今日计划完成边界（不再生成新任务）/ A·B 两学生严格隔离 /
V2.0-V2.5 核心接口回归 200。

纪律：临时库 _verify_v26.db（跑完删除）· 绝不写 learning.db · 端口被占用故意失败（不换端口）。
"""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta

BACKEND = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BACKEND)
DB_PATH = os.path.join(BACKEND, "_verify_v26.db")
PORT = int(os.getenv("VERIFY_V26_PORT", "8913"))
BASE = "http://127.0.0.1:%d" % PORT
STUDENT_A, STUDENT_B, STUDENT_X = 1, 2, 999
KNOW = "表内乘法"
TODAY = datetime.now().strftime("%Y-%m-%d")

for _suffix in ("", "-journal", "-wal", "-shm"):
    try:
        os.remove(DB_PATH + _suffix)
    except OSError:
        pass

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH.replace("\\", "/")
os.environ["PHOEBE_AI_OFFLINE"] = "1"
os.environ["DEEPSEEK_API_KEY"] = ""
sys.path.insert(0, BACKEND)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

import kid_status  # noqa: E402
from database import SessionLocal, engine as db_engine  # noqa: E402
from models import (DailyLearningTask, StudentKnowledgeMastery,  # noqa: E402
                    WrongQuestionRecovery)

PASSED = 0
FAILED = 0
CHILD_LABELS = set(level["label"] for level in kid_status.LEVELS) | {kid_status.UNKNOWN["label"]}


# ---------------------------------------------------------------- 基础工具

def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("PASS  " + name + (("  | " + str(extra)) if extra else ""))
    else:
        FAILED += 1
        print("FAIL  " + name + (("  | " + str(extra)) if extra else ""))


def get(path, **params):
    return requests.get(BASE + path, params=params, timeout=30)


def post(path, payload):
    return requests.post(BASE + path, json=payload, timeout=60)


def body(resp):
    try:
        return resp.json()
    except Exception:                              # noqa: BLE001
        return {}


def node_of(data, name):
    for node in (data.get("knowledge_nodes") or []):
        if node.get("name") == name:
            return node
    return None


def unlocked_per_region(data):
    buckets = {}
    for node in (data.get("knowledge_nodes") or []):
        buckets.setdefault(node.get("region") or "", []).append(bool(node.get("is_unlocked")))
    return dict((key, sum(1 for item in value if item)) for key, value in buckets.items())


# ---------------------------------------------------------------- 造真实数据（只给学生 A）

def seed_case():
    """给 A 造三条真实学习数据，用来检查「儿童端只反映真实学习结果」与两学生隔离。"""
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        db.add(StudentKnowledgeMastery(
            student_id=STUDENT_A, subject="数学", knowledge_id=KNOW, knowledge_point_id=KNOW,
            mastery_score=90, confidence=0.9, total_questions=8, correct_questions=8,
            consecutive_wrong=0, last_practice_time=now, updated_time=now))
        db.add(DailyLearningTask(
            student_id=STUDENT_A, date=yesterday, task_type="review", title="复习·" + KNOW,
            subject="数学", knowledge_id=KNOW, target_count=2, complete_count=2,
            duration_minutes=8, target_minutes=8, status="done", priority=1, source="verify_v26"))
        db.add(WrongQuestionRecovery(
            student_id=STUDENT_A, subject="数学", knowledge_id=KNOW, question_id=873001,
            wrong_question_id=0, state="MASTERED", attempts=3, correct_count=3,
            consecutive_correct=2, fail_count=0, mastered_time=now, last_state_change=now))
        db.commit()
        check("给 A 造真实学习数据（掌握 + 昨天学习 + 攻克挑战）", True)
    except Exception as error:                     # noqa: BLE001
        db.rollback()
        check("给 A 造真实学习数据（掌握 + 昨天学习 + 攻克挑战）", False, repr(error))
    finally:
        db.close()


# ---------------------------------------------------------------- 首页聚合

def home_case():
    root = body(get("/"))
    check("根接口版本号已升到 2.6", root.get("version") == "2.6", root.get("version"))

    home = body(get("/api/home/%d" % STUDENT_A))
    plan = home.get("daily_plan") or {}
    items = plan.get("items") or []
    start = home.get("start") or {}
    check("首页一次拿全「今天要做什么」", bool(start) and home.get("student", {}).get("name"),
          home.get("student", {}).get("name"))
    check("首页主按钮文案由接口给出", start.get("label") == "开始今天的学习", start.get("label"))
    check("任务数 = 今日计划条数（不多不少）", start.get("task_count") == len(items),
          "%s / %s" % (start.get("task_count"), len(items)))
    check("每条微任务都有明确时长（不出现「今天学习 30 分钟」）",
          all(int(item.get("minutes") or 0) > 0 for item in items),
          [item.get("minutes") for item in items])
    check("菲比告诉孩子今天几个任务、大约多久",
          (not items) or ("分钟" in plan.get("message") or "" and "任务" in plan.get("message") or ""),
          plan.get("message"))
    message = home.get("phoebe_message") or {}
    check("菲比这一屏只说一句话且状态在四态内",
          bool(message.get("text")) and message.get("state") in ("normal", "thinking", "encourage", "happy"),
          message)
    check("首页给一个简单成长亮点", bool(home.get("growth_highlight", {}).get("text")),
          home.get("growth_highlight", {}).get("text"))
    check("首页不暴露后台算法字段",
          not ({"mastery_score", "stability", "forgetting_risk", "difficulty_score"} & set(home.keys())),
          sorted(home.keys()))
    check("首页不显示累计做题量与在线时长",
          not ({"total_questions", "total_minutes", "online_minutes"} & set(home.keys())))
    check("学生不存在返回 200 空结构而不是 404",
          get("/api/home/%d" % STUDENT_X).status_code == 200
          and body(get("/api/home/%d" % STUDENT_X)).get("daily_plan", {}).get("items") == [])
    check("date 非法返回 400", get("/api/home/%d" % STUDENT_A, date="2026/01/01").status_code == 400)


# ---------------------------------------------------------------- 知识地图

def map_case():
    data = body(get("/api/knowledge-map/%d" % STUDENT_A, subject="数学"))
    nodes = data.get("knowledge_nodes") or []
    check("知识地图返回区域与知识节点", bool(data.get("regions")) and len(nodes) > 0,
          len(nodes))
    check("知识地图节点都带儿童状态（🌱🌿🌳⭐）",
          all((node.get("ui_status") or {}).get("label") in CHILD_LABELS for node in nodes))
    check("知识地图区域显示「N / M 知识已成长」",
          all("知识已成长" in (region.get("progress_text") or "") for region in (data.get("regions") or [])))
    check("知识地图不把没学过的知识显示成 0 分",
          all(node.get("ui_status", {}).get("key") == "sprout"
              for node in nodes if not node.get("practiced")),
          [node.get("name") for node in nodes if not node.get("practiced")][:3])

    other = body(get("/api/knowledge-map/%d" % STUDENT_B, subject="数学"))
    buckets = unlocked_per_region(other)
    check("未掌握的知识不能被解锁（解锁只来自真实学习数据）",
          bool(buckets) and all(value <= 1 for value in buckets.values()), buckets)
    check("知识地图按真实掌握度上色", (node_of(data, KNOW) or {}).get("ui_status", {}).get("rank", 0) >= 3,
          (node_of(data, KNOW) or {}).get("ui_status"))
    check("另一个学生地图里同一知识点仍是「刚开始」",
          (node_of(other, KNOW) or {}).get("ui_status", {}).get("rank", -1) == 0,
          (node_of(other, KNOW) or {}).get("ui_status"))
    check("知识地图三个学科都可用",
          all(get("/api/knowledge-map/%d" % STUDENT_A, subject=subject).status_code == 200
              for subject in ("数学", "语文", "英语")))
    check("知识地图科目非法返回 400",
          get("/api/knowledge-map/%d" % STUDENT_A, subject="科学").status_code == 400)
    check("不存在的学生返回空地图而不是 404",
          get("/api/knowledge-map/%d" % STUDENT_X, subject="数学").status_code == 200)


# ---------------------------------------------------------------- 成长中心

def growth_case():
    data = body(get("/api/growth/%d" % STUDENT_A))
    week = data.get("week") or {}
    check("成长中心回答「我最近学会什么」（七项周数据）",
          {"study_days", "new_mastered", "long_term", "challenges", "review_success",
           "recall_success", "minutes"} <= set(week), sorted(week.keys()))
    check("成长中心的周数字来自真实学习数据",
          week.get("new_mastered") >= 1 and week.get("challenges") >= 1 and week.get("study_days") >= 1,
          week)
    check("成长中心有成长时间线（不做社交 Feed）",
          isinstance(data.get("timeline"), list)
          and all("line" in event for event in data.get("timeline") or []),
          (data.get("timeline") or [{}])[0].get("line"))
    check("成长中心给出连续学习与本月天数，且不清零历史",
          {"current", "longest", "month_days"} <= set(data.get("streak") or {}),
          data.get("streak"))
    check("成长中心不把使用量当成果（周数据没有做题总数 / 在线时长）",
          "questions" not in week and "online_minutes" not in week)
    check("成长中心 days 上限 30", body(get("/api/growth/%d" % STUDENT_A, days=99)).get("period_days") == 30)

    other = body(get("/api/growth/%d" % STUDENT_B))
    check("另一个学生成长中心仍是零（不串数据）",
          other.get("week", {}).get("new_mastered") == 0
          and other.get("week", {}).get("study_days") == 0, other.get("week"))
    check("不存在的学生成长中心返回 200 空结构",
          get("/api/growth/%d" % STUDENT_X).status_code == 200
          and body(get("/api/growth/%d" % STUDENT_X)).get("week", {}).get("study_days") == 0)
    check("成长中心 date 非法返回 400", get("/api/growth/%d" % STUDENT_A, date="2026/01/01").status_code == 400)


# ---------------------------------------------------------------- 挑战中心

def challenge_case():
    data = body(get("/api/challenge/%d" % STUDENT_A))
    counts = data.get("counts") or {}
    items = data.get("items") or []
    check("挑战中心用 🔴🟡🟢 表达状态",
          {"red", "yellow", "green"} <= set(counts) and len(data.get("tones") or {}) == 3,
          counts)
    check("挑战中心与 V2.5 康复数据一致",
          counts.get("green") >= 1 and any(item.get("tone") == "green" for item in items), items[:1])
    check("挑战列表不泄露答案与解析",
          all("correct_answer" not in item and "analysis" not in item for item in items))
    check("挑战列表显示科目与知识点",
          all(item.get("subject") and item.get("knowledge") for item in items))
    check("没有挑战时是轻松文案",
          data.get("empty_text") == "🎉 暂时没有需要攻克的挑战！", data.get("empty_text"))

    recovery = body(get("/api/recovery/list/%d" % STUDENT_A))
    same = [item.get("recovery_id") for item in recovery.get("items") or []]
    check("挑战中心的康复项就是 V2.5 的康复项（不新开算法）",
          bool(same) and sorted(item.get("recovery_id") for item in items) == sorted(same)[:len(items)],
          same)
    check("另一个学生挑战中心为空（严格隔离）",
          body(get("/api/challenge/%d" % STUDENT_B)).get("total") == 0)
    check("不存在的学生挑战中心返回 200 空结构",
          get("/api/challenge/%d" % STUDENT_X).status_code == 200
          and body(get("/api/challenge/%d" % STUDENT_X)).get("total") == 0)


# ---------------------------------------------------------------- 学习会话边界

def session_case():
    start = body(post("/api/tasks/start", {"student_id": STUDENT_A, "date": TODAY, "minutes": 15}))
    tasks = start.get("tasks") or []
    total = len(tasks)
    check("统一学习会话能一次拿到今日任务清单",
          total > 0 and (start.get("summary") or {}).get("total") == total, total)
    for task in tasks:
        post("/api/tasks/complete", {
            "student_id": STUDENT_A, "task_id": task.get("task_id"),
            "minutes": int(task.get("minutes") or task.get("target_minutes") or 3),
            "count": int(task.get("target_count") or 1), "done": True})

    summary = body(get("/api/daily-summary/%d" % STUDENT_A))
    check("今日任务全部完成后进入「今天完成啦」",
          summary.get("finished") is True and summary.get("message") == "🎉 今天完成啦！",
          summary.get("message"))
    check("今日完成页说清今天学到什么（无使用量堆砌）",
          isinstance(summary.get("child"), dict) and "minutes" in summary["child"],
          summary.get("child"))
    check("今日完成页没有加练入口",
          not any(word in json.dumps(summary, ensure_ascii=False)
                  for word in ("再来一题", "继续挑战", "额外奖励", "再学 5 分钟")))
    again = body(post("/api/tasks/start", {"student_id": STUDENT_A, "date": TODAY, "minutes": 15}))
    check("完成后不会再生成新的微任务（每日计划有固定边界）",
          len(again.get("tasks") or []) == total, len(again.get("tasks") or []))
    home = body(get("/api/home/%d" % STUDENT_A))
    check("完成状态下菲比让孩子去休息",
          home.get("phoebe_message", {}).get("state") == "happy"
          and "休息" in (home.get("phoebe_message", {}).get("text") or ""),
          home.get("phoebe_message"))
    check("完成状态下首页不再增加任务数", home.get("start", {}).get("task_count") == total,
          home.get("start"))


# ---------------------------------------------------------------- V2.0-V2.5 回归

def regression_case():
    pairs = [
        ("/students", {}),
        ("/api/daily-summary/1", {}),
        ("/api/mastery/1", {"subject": "数学"}),
        ("/api/knowledge/tree", {"subject": "数学"}),
        ("/api/habit/profile/1", {}),
        ("/api/habit/goal/1", {}),
        ("/api/recovery/list/1", {}),
        ("/api/review/today/1", {}),
        ("/api/ability/auto/1", {}),
        ("/api/active-recall/summary", {"student_id": 1}),
        ("/api/learning/plan/1", {}),
        ("/api/diagnostic/stages", {}),
        ("/api/wrong_questions/1", {}),
        ("/api/tasks/today", {"student_id": 1}),
    ]
    for path, params in pairs:
        response = get(path, **params)
        check("V2.0-V2.5 回归：%s" % path, response.status_code == 200, response.status_code)
    students = body(get("/students"))
    check("两个本地学生都在，且名字与年级可用",
          isinstance(students, list) and len(students) >= 2
          and all(item.get("name") and item.get("grade_text") for item in students[:2]),
          students[:2])


# ---------------------------------------------------------------- 临时后端

def port_in_use():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def start_server():
    """起真实 app（main.py），验证注册与启动副作用都是产品实际路径。"""
    if port_in_use():
        check("端口未占用（%d 被占用则故意失败，不自动换端口）" % PORT, False, "端口已被占用")
        finish(None)
    code = (
        "import uvicorn\n"
        "import main\n"
        "uvicorn.run(main.app, host='127.0.0.1', port=%d, log_level='warning')\n" % PORT
    )
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=BACKEND, env=env)
    for _ in range(80):
        if proc.poll() is not None:
            break
        try:
            if requests.get(BASE + "/", timeout=2).status_code == 200:
                check("临时后端启动（端口 %d，真实 main.app）" % PORT, True)
                return proc
        except Exception:                              # noqa: BLE001
            pass
        time.sleep(0.5)
    proc.terminate()
    check("临时后端启动（端口 %d）" % PORT, False, "40 秒内未就绪")
    finish(proc)
    return proc


def finish(proc):
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:                              # noqa: BLE001
            proc.kill()
    try:
        db_engine.dispose()
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(DB_PATH + suffix)
            except OSError:
                pass
    total = PASSED + FAILED
    print("\n合计 %d 项断言：PASS %d / FAIL %d" % (total, PASSED, FAILED))
    print("RESULT: ALL PASS" if FAILED == 0 else "RESULT: HAS FAILURES")
    sys.exit(0 if FAILED == 0 else 1)


def main():
    start = time.time()
    proc = start_server()
    try:
        seed_case()
        home_case()
        map_case()
        growth_case()
        challenge_case()
        session_case()
        regression_case()
    finally:
        print("耗时 %.1fs" % (time.time() - start))
        finish(proc)


if __name__ == "__main__":
    main()
