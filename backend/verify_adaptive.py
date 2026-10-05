# ==============================================================
# 能力契约｜验证：自适应引擎（策略排序/难度升降/选题配比/每日计划/接口），端口 8905
# 入口：脚本自身：python backend/verify_adaptive.py
# 依赖：adaptive.strategy adaptive.difficulty adaptive.selector adaptive.planner knowledge_tree stages models database
# 不负责：复习体系 → verify_memory.py
# 验证：python backend/verify_adaptive.py
# 被调用：verify_all.py（套件 adaptive）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎（Adaptive Learning Engine）测试。

覆盖：

  难度控制器 DifficultyController（连对 +5 / 连错 -10 / 正确率窗口升降阶段 /
      难度 1~100 夹取 / 主观感受微调）
  → 学习策略 LearningStrategy（薄弱优先、知识依赖门控"先补乘法"、
      基础知识权重、遗忘风险、理由文案）
  → 下一题推荐 QuestionSelector（40/30/20/10 权重、70/20/10 题源配比、
      同知识点回避）
  → 每日计划 DailyLearningPlanner（15/10/10 分钟、10 题 / 20 个单词、
      熟练科目让时间）
  → API 全流程（recommend / plan / start / next-question / feedback /
      strategy-log）
  → 学生 A：应用题连续答错 3 题 → 难度降低
  → 学生 A：乘法连续答对 5 题 → 难度提升
  → 学生 B：独立计划、独立日志（数据隔离）
  → 前端今日学习页可访问

用法：python backend/verify_adaptive.py     （自拉临时后端，端口 VERIFY_ADAPTIVE_PORT，默认 8905）
全部通过时退出码为 0。
"""

import os
import random
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta

PORT = int(os.getenv("VERIFY_ADAPTIVE_PORT", "8905"))

_db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_adaptive.db")
for _suffix in ("", "-journal", "-wal", "-shm"):
    if os.path.exists(_db_file + _suffix):
        os.remove(_db_file + _suffix)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
os.environ["DEEPSEEK_API_KEY"] = ""      # 全程本地规则 + 内置兜底题，不依赖外网

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK，打印 🙂 这类表情会直接抛 UnicodeEncodeError，
# 这里统一切到 UTF-8（无法改编码时退化为替换字符，不影响断言结果）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

import knowledge_tree
import stages
from adaptive import difficulty, planner, selector, strategy
from database import SessionLocal, engine as db_engine
from models import Base, LearningFeedback, LearningPlan, LearningStrategyLog, Question

# 测试进程也要先建表：临时库是空的
Base.metadata.create_all(db_engine)

BASE = f"http://127.0.0.1:{PORT}"
NOW = datetime(2026, 3, 1, 10, 0)
ok = True
proc = None
http = requests.Session()


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


def records(pattern, difficulty_value=50, start=None):
    """按"从旧到新"的对错序列造答题记录。"""
    start = start or datetime(2026, 3, 1, 9, 0)
    return [{"correct": bool(flag), "difficulty": difficulty_value,
             "time": start + timedelta(minutes=index)}
            for index, flag in enumerate(pattern)]


# ================= 1. DifficultyController =================

controller = difficulty.DEFAULT_CONTROLLER

five_right = controller.adjust(50, records([True] * 5))
check("连续答对 5 题 → 难度 +5", five_right["delta"] == 5, five_right["delta"])
check("连续答对 5 题 → 记录连对次数", five_right["streak"] == {"kind": "correct", "count": 5},
      five_right["streak"])
check("正确率 100% → 进入提升阶段", five_right["stage_action"] == "up", five_right["stage_action"])
check("难度上限不超过 100", controller.adjust(98, records([True] * 5))["difficulty"] == 100,
      controller.adjust(98, records([True] * 5))["difficulty"])

three_wrong = controller.adjust(50, records([False] * 3))
check("连续答错 3 题 → 难度 -10", three_wrong["delta"] == -10, three_wrong["delta"])
check("连续答错 3 题 → 记录连错次数", three_wrong["streak"] == {"kind": "wrong", "count": 3},
      three_wrong["streak"])
check("样本不足 5 题时不改阶段", three_wrong["stage_action"] == "hold", three_wrong["stage_action"])
check("持续答错 → 降低阶段",
      controller.adjust(50, records([False] * 6))["stage_action"] == "down",
      controller.adjust(50, records([False] * 6))["stage_action"])
check("难度下限不低于 1", controller.adjust(3, records([False] * 6))["difficulty"] == 1,
      controller.adjust(3, records([False] * 6))["difficulty"])

# 没有连对/连错，但整体正确率高 → 只靠正确率窗口推难度
mixed_high = controller.adjust(50, records([True, True, False, True, True, True, True, True, True, True]))
check("最近 10 题 90% 正确率 → 提升阶段", mixed_high["stage_action"] == "up", mixed_high["stage_action"])
check("连对未触发时正确率窗口也调难度", mixed_high["delta"] == 5, mixed_high["delta"])

mixed_low = controller.adjust(50, records([False, True, False, False, True, False, False, True, False, False]))
check("最近 10 题低于 50% → 降低阶段", mixed_low["stage_action"] == "down", mixed_low["stage_action"])
check("正确率窗口下调难度", mixed_low["delta"] == -5, mixed_low["delta"])

steady = controller.adjust(50, records([True, False, True, True, False, True]))
check("正确率 67% → 难度不变、保持阶段",
      steady["delta"] == 0 and steady["stage_action"] == "hold", steady)

easy = controller.adjust(50, records([True]), feel="easy")
hard = controller.adjust(50, records([True]), feel="hard")
lost = controller.adjust(50, records([True]), feel="lost")
check("觉得简单 → 难度上调", easy["delta"] == 3, easy["delta"])
check("觉得有点难 → 难度下调", hard["delta"] == -3, hard["delta"])
check("完全不会 → 难度多降一点", lost["delta"] == -6, lost["delta"])

check("最佳学习区间按 70%~85% 判定",
      controller.adjust(50, records([True] * 8 + [False] * 2))["on_target"] is True,
      controller.adjust(50, records([True] * 8 + [False] * 2))["window_rate"])
check("样本太少不按正确率乱调",
      controller.adjust(50, records([False, False]))["stage_action"] == "hold",
      controller.adjust(50, records([False, False])))
check("难度恒在 1~100",
      all(1 <= controller.adjust(base, records([True] * 3))["difficulty"] <= 100
          for base in (1, 50, 100)))
check("阶段推进：up 进入下一阶段", difficulty.stage_step("up", "3.2") == "3.3")
check("阶段回退：down 返回上一阶段", difficulty.stage_step("down", "3.2") == "3.1")


# ================= 2. LearningStrategy =================

def make_item(subject, name, mastery, total):
    return {
        "knowledge_id": name,
        "mastery_score": int(mastery),
        "confidence": 0.5,
        "total_questions": int(total),
        "correct_questions": int(round(total * mastery / 100.0)),
        "wrong_questions": int(total) - int(round(total * mastery / 100.0)),
        "consecutive_wrong": 0,
        "stage": knowledge_tree.stage_of(subject, name),
        "chapter": knowledge_tree.domain_of(subject, name),
        "last_practice_time": NOW - timedelta(days=1),
        "next_review_time": NOW + timedelta(days=3),
    }


def profile_with(entries, subject="数学", stage="3.2", score=72):
    items = [make_item(subject, name, mastery, total)
             for name, (mastery, total) in entries.items()]
    known = {item["knowledge_id"] for item in items}
    for name in knowledge_tree.all_names(subject):
        if name not in known:
            items.append(make_item(subject, name, 0, 0))

    return {
        "student_id": 1,
        "student_name": "小朋友A",
        "subject": subject,
        "ability": {"stage": stage, "label": stages.label(stage), "score": score},
        "knowledge": items,
        "error_counts": {},
        "recent": [],
        "now": NOW,
    }


# 用户给的验收场景：数学 3.2、应用题掌握 60 → 推荐应用题训练
case_a = strategy.DEFAULT_STRATEGY.choose(
    profile_with({"两步计算应用题": (60, 8), "表内乘法": (78, 10)}))
check("掌握度 62 场景：推荐薄弱的应用题训练", case_a["knowledge"] == "两步计算应用题",
      case_a["knowledge"])
check("推荐动作是强化练习", case_a["action"] == "practice", case_a["action"])
check("理由含掌握度与原因", "掌握度60" in case_a["reason"] and "强化" in case_a["reason"],
      case_a["reason"])
check("给出题的难度在 1~100", 1 <= case_a["difficulty"] <= 100, case_a["difficulty"])

# 需求里的依赖例子：乘法 50、应用题 60，但应用题依赖乘法 → 先补乘法
case_dep = strategy.DEFAULT_STRATEGY.choose(
    profile_with({"两步计算应用题": (60, 8), "表内乘法": (50, 10)}))
check("依赖门控：乘法 50、应用题 60 时先补乘法",
      case_dep["knowledge"] == "表内乘法", case_dep["knowledge"])
check("依赖门控理由说明它是基础", "基础" in case_dep["reason"], case_dep["reason"])

# 乘法从没练过，不构成"拦路虎"：仍然先练薄弱的应用题
case_unpracticed = strategy.DEFAULT_STRATEGY.choose(
    profile_with({"两步计算应用题": (60, 8)}))
check("前置没练过时不误判为拦路虎", case_unpracticed["knowledge"] == "两步计算应用题",
      case_unpracticed["knowledge"])

check("基础知识权重：乘法高于应用题",
      strategy.foundation_weight("数学", "表内乘法")
      > strategy.foundation_weight("数学", "两步计算应用题"),
      (strategy.foundation_weight("数学", "表内乘法"),
       strategy.foundation_weight("数学", "两步计算应用题")))
check("依赖关系可查：应用题依赖乘法",
      "表内乘法" in strategy.prerequisites("数学", "两步计算应用题"),
      strategy.prerequisites("数学", "两步计算应用题"))
check("依赖链可读", len(strategy.dependency_chain("数学", "两步计算应用题")) >= 2,
      strategy.dependency_chain("数学", "两步计算应用题"))
check("依赖关系覆盖三科", all(subject in strategy.DEPENDENCIES for subject in stages.SUBJECTS),
      list(strategy.DEPENDENCIES))

# 即将遗忘：昨天练过、但复习时间已经过了 → 排到前面
stale = profile_with({"两步计算应用题": (78, 10), "表内乘法": (78, 10)})
for item in stale["knowledge"]:
    if item["knowledge_id"] == "表内乘法":
        item["next_review_time"] = NOW - timedelta(days=2)
        item["last_practice_time"] = NOW - timedelta(days=9)
choose_stale = strategy.DEFAULT_STRATEGY.choose(stale)
check("即将遗忘的知识点会被优先安排", choose_stale["knowledge"] == "表内乘法",
      choose_stale["knowledge"])
check("遗忘场景动作是复习或强化",
      choose_stale["action"] in ("review", "practice"), choose_stale["action"])

# 没有诊断也没有练习 → 先做诊断
blank = profile_with({})
blank["ability"] = {}
blank["recent"] = []
check("完全没有数据时先做诊断",
      strategy.DEFAULT_STRATEGY.choose(blank)["action"] == "diagnostic",
      strategy.DEFAULT_STRATEGY.choose(blank)["action"])

# 已经熟练掌握 → 挑战
strong = profile_with({name: (92, 12) for name in knowledge_tree.all_names("数学")})
strong["error_counts"] = {}
choose_strong = strategy.DEFAULT_STRATEGY.choose(strong)
check("全部熟练时给挑战题", choose_strong["action"] == "challenge", choose_strong["action"])


# ================= 3. QuestionSelector =================

rng = random.Random(20260301)
modes = [selector.DEFAULT_SELECTOR.choose_mode(rng) for _ in range(2000)]
ratio_practice = modes.count("practice") / 2000.0
ratio_review = modes.count("review") / 2000.0
ratio_challenge = modes.count("challenge") / 2000.0
check("题源配比：当前薄弱约 70%", 0.66 <= ratio_practice <= 0.74, round(ratio_practice, 3))
check("题源配比：复习旧知识约 20%", 0.16 <= ratio_review <= 0.24, round(ratio_review, 3))
check("题源配比：挑战知识约 10%", 0.06 <= ratio_challenge <= 0.14, round(ratio_challenge, 3))

candidates = [
    {"knowledge": "两步计算应用题", "mastery": 40, "weakness": 0.6, "difficulty": 58,
     "forgetting": 0.2, "practiced": True},
    {"knowledge": "表内乘法", "mastery": 82, "weakness": 0.18, "difficulty": 55,
     "forgetting": 0.1, "practiced": True},
    {"knowledge": "20以内加减法", "mastery": 95, "weakness": 0.05, "difficulty": 30,
     "forgetting": 0.0, "practiced": True},
]
picked = [selector.DEFAULT_SELECTOR.select(candidates, target_difficulty=60,
                                           mode="practice",
                                           rng=random.Random(index))
          for index in range(200)]
hit = sum(1 for item in picked if item["knowledge"] == "两步计算应用题")
check("40% 薄弱度权重：最薄弱的被选中最多", hit >= 120, hit)

repeat_check = selector.DEFAULT_SELECTOR.select(candidates, target_difficulty=60,
                                                mode="practice",
                                                rng=random.Random(5),
                                                recent_knowledge=("两步计算应用题",))
check("同知识点回避：刚练过的不再连出", repeat_check["knowledge"] != "两步计算应用题",
      repeat_check["knowledge"])
check("同知识点软避让：最近一道扣得最重（不硬禁，隔几道还能再练）",
      selector.repeat_penalty_of("两步计算应用题", ("两步计算应用题",))
      == selector.REPEAT_PENALTY_NEAREST)
check("同知识点软避让：最近 2 题内扣分低于上一题",
      selector.repeat_penalty_of("两步计算应用题", ("表内乘法", "两步计算应用题"))
      == selector.REPEAT_PENALTY_RECENT)
check("同知识点软避让：隔几道题只扣基准值（仍可反复练习）",
      selector.repeat_penalty_of("两步计算应用题", ("20以内加减法", "表内乘法", "两步计算应用题"))
      == selector.REPEAT_PENALTY)
check("同知识点软避让：没练过的知识点不扣分",
      selector.repeat_penalty_of("两步计算应用题", ("表内乘法",)) == 0.0)
check("同知识点软避让：罚分不超过薄弱项权重（避免软避让变成硬禁）",
      selector.REPEAT_PENALTY_NEAREST <= selector.WEIGHTS["weakness"]
      and selector.REPEAT_PENALTY_RECENT < selector.REPEAT_PENALTY_NEAREST
      and selector.REPEAT_PENALTY < selector.REPEAT_PENALTY_RECENT,
      (selector.REPEAT_PENALTY, selector.REPEAT_PENALTY_RECENT, selector.REPEAT_PENALTY_NEAREST))
check("打分包含四项证据", {"weakness", "match", "forgetting", "random"} <= set(
    selector.DEFAULT_SELECTOR.select(candidates, rng=random.Random(1))["breakdown"]))
check("能力匹配度随难度差单调下降",
      selector.match_score(60, 60) > selector.match_score(60, 90), "ok")
check("空候选时不会崩", selector.DEFAULT_SELECTOR.select([])["knowledge"] == "")


# ================= 4. DailyLearningPlanner =================

def plan_profile(subject, knowledge, mastery, action="practice", difficulty=60,
                 practiced=8, average=None):
    return {
        "subject": subject,
        "summary": {"practiced": practiced,
                    "average_mastery": mastery if average is None else average},
        "decision": {"knowledge": knowledge, "action": action, "difficulty": difficulty,
                     "reason": f"掌握度{mastery}，需要强化",
                     "evidence": {"mastery": mastery}},
    }


plan_profiles = [
    plan_profile("数学", "两步计算应用题", 60),
    plan_profile("英语", "颜色", 55),
    plan_profile("语文", "记叙文阅读理解", 58),
]
minutes = planner.DEFAULT_PLANNER.allocate(plan_profiles)
check("默认时间分配：数学 15 分钟", minutes["数学"] == 15, minutes)
check("默认时间分配：语文 / 英语各 10 分钟",
      minutes["语文"] == 10 and minutes["英语"] == 10, minutes)

plans = planner.DEFAULT_PLANNER.build(plan_profiles)
by_subject = {item["subject"]: item for item in plans}
math_total = sum(item["target_count"] for item in plans if item["subject"] == "数学")
english_total = sum(item["target_count"] for item in plans if item["subject"] == "英语")
check("数学计划：一天共 10 题", math_total == 10, math_total)
check("英语计划：复习 20 个单词", english_total == 20
      and "个单词" in by_subject["英语"]["goal"], by_subject["英语"]["goal"])
check("语文阅读计划：读一篇短文", "短文" in by_subject["语文"]["goal"],
      by_subject["语文"]["goal"])
check("计划目标与掌握度挂钩（60 → 70）", by_subject["数学"]["target_mastery"] == 70,
      by_subject["数学"]["target_mastery"])

give_back = planner.DEFAULT_PLANNER.allocate([
    plan_profile("数学", "两步计算应用题", 90),
    plan_profile("英语", "颜色", 40),
    plan_profile("语文", "记叙文阅读理解", 45),
])
check("已经熟练的科目让出 5 分钟", give_back["数学"] == 10, give_back)
check("让出的时间补给最薄弱的科目", give_back["英语"] == 15, give_back)

scaled = planner.DEFAULT_PLANNER.allocate(plan_profiles, total_minutes=70)
check("总时长可缩放", sum(scaled.values()) == 70, scaled)
check("日期统一成 YYYY-MM-DD", planner.date_text(datetime(2026, 3, 1, 8, 0)) == "2026-03-01")
check("掌握度目标上限 90", planner.target_mastery_of(88) == 90, planner.target_mastery_of(88))


# ================= 5. 启动临时后端 =================

def port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect(("127.0.0.1", PORT))
        except OSError:
            return False
        except Exception:
            return True
    return False


def start_server():
    if port_in_use():
        print(f"FAIL  端口 {PORT} 已被占用，请先关掉占用该端口的进程再跑本测试。")
        sys.exit(1)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    child = subprocess.Popen(
        [sys.executable, "-c",
         f"import uvicorn, main; uvicorn.run(main.app, host='127.0.0.1', port={PORT}, log_level='warning')"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env,
    )

    deadline = time.time() + 40
    while time.time() < deadline:
        if child.poll() is not None:
            break
        try:
            if http.get(BASE + "/", timeout=2).status_code == 200:
                return child
        except requests.RequestException:
            time.sleep(0.2)

    child.terminate()
    child.wait(timeout=10)
    print(f"FAIL  临时后端启动失败（端口 {PORT}）")
    sys.exit(1)


proc = start_server()

KNOWLEDGE = "两步计算应用题"
MULTIPLY = "表内乘法"


def truth_of(question_id):
    session = SessionLocal()
    row = session.query(Question).filter(Question.id == question_id).first()
    answer = row.answer if row else ""
    session.close()
    return answer


def wrong_of(question):
    truth = truth_of(question["question_id"])
    options = question.get("options") or {}
    return next((key for key in options if key != truth), "Z")


def next_question(student_id, knowledge="", subject="数学"):
    return http.get(BASE + "/api/learning/next-question",
                    params={"student_id": student_id, "subject": subject,
                            "knowledge": knowledge, "qtype": "choice"}, timeout=60).json()


# 同知识点软避让的参数版（V2.5：刚练过的知识点不锁定）
def next_question_avoid(student_id, knowledge="", avoid="", subject="数学"):
    return http.get(BASE + "/api/learning/next-question",
                    params={"student_id": student_id, "subject": subject,
                            "knowledge": knowledge, "avoid": avoid, "qtype": "choice"},
                    timeout=60).json()

def submit(student_id, question, answer):
    return http.post(BASE + "/submit",
                     json={"question_id": question["question_id"], "answer": answer,
                           "student_id": student_id}, timeout=30).json()


def recommend(student_id, subject=""):
    return http.get(f"{BASE}/api/learning/recommend/{student_id}",
                    params={"subject": subject} if subject else {}, timeout=30).json()


# ================= 6. 今日推荐 / 今日计划 =================

first = recommend(1)
check("推荐接口返回下一步动作", bool(first["next_action"]["knowledge"]),
      first["next_action"])
check("推荐接口给出理由", bool(first["next_action"]["reason"]), first["next_action"]["reason"])
check("推荐接口带今日计划", len(first["plan"]["items"]) >= 1, first["plan"]["items"])
check("推荐接口写入策略日志", bool(first.get("strategy_log_id")), first.get("strategy_log_id"))
check("推荐消息说清今天练什么", "今天先练" in first["message"], first["message"])
check("推荐接口覆盖三科画像", len(first["subjects"]) == 3,
      [item["subject"] for item in first["subjects"]])
check("推荐带难度状态", "difficulty" in first["primary"]["difficulty_state"],
      first["primary"].get("difficulty_state"))

plan_api = http.get(f"{BASE}/api/learning/plan/1", timeout=20).json()
check("今日计划接口可用", len(plan_api["items"]) >= 1, plan_api["items"])
check("计划条目字段完整",
      all({"id", "subject", "knowledge_id", "target_count", "completed_count",
           "status", "duration_minutes", "goal", "remain_count", "progress"} <= set(item)
          for item in plan_api["items"]), plan_api["items"][:1])
check("计划总进度可计算", 0 <= plan_api["progress"] <= 100, plan_api["progress"])
check("计划状态文案是中文",
      all(item["status_text"] for item in plan_api["items"]), plan_api["items"][:1])
check("非法科目返回 400",
      http.get(f"{BASE}/api/learning/recommend/1", params={"subject": "科学"},
               timeout=10).status_code == 400)


# ================= 7. 学生 A：应用题连续答错 3 题 → 难度降低 =================

start_task = http.post(BASE + "/api/learning/start",
                       json={"student_id": 1, "subject": "数学", "knowledge": KNOWLEDGE},
                       timeout=30).json()
check("开始学习返回任务", start_task["knowledge"] == KNOWLEDGE, start_task["knowledge"])
check("开始学习锁定难度", 1 <= start_task["difficulty"] <= 100, start_task["difficulty"])
check("开始学习返回今日计划与目标题量",
      start_task["target_count"] >= 1 and "items" in start_task["plan"], start_task["plan"])

avoided_question = next_question_avoid(1, KNOWLEDGE, avoid=KNOWLEDGE)
check("API 同知识点软避让：刚练过的知识点不再锁定",
      avoided_question.get("adaptive", {}).get("avoided") is True
      and avoided_question.get("adaptive", {}).get("avoided_knowledge") == KNOWLEDGE,
      avoided_question.get("adaptive"))
check("API 同知识点软避让：换成了别的知识点",
      bool(avoided_question.get("knowledge"))
      and avoided_question.get("knowledge") != KNOWLEDGE,
      avoided_question.get("knowledge"))

before_question = next_question(1, KNOWLEDGE)
before_difficulty = before_question["adaptive"]["difficulty"]
check("下一题接口返回自适应难度", 1 <= before_difficulty <= 100, before_difficulty)
check("下一题接口返回推荐理由", bool(before_question["adaptive"]["reason"]),
      before_question["adaptive"]["reason"])
check("题目难度与自适应难度一致",
      before_question["difficulty"] == before_difficulty,
      (before_question["difficulty"], before_difficulty))
check("下一题接口带四项打分证据",
      {"weakness", "match", "forgetting", "random"} <= set(
          before_question["adaptive"]["breakdown"] or {}),
      before_question["adaptive"]["breakdown"])

answer_scores = []
for _ in range(3):
    question = next_question(1, KNOWLEDGE)
    result = submit(1, question, wrong_of(question))
    answer_scores.append(result["mastery"]["mastery_score"])

check("连续答错掌握度下降", answer_scores[-1] < answer_scores[0], answer_scores)

after_question = next_question(1, KNOWLEDGE)
after_difficulty = after_question["adaptive"]["difficulty"]
check("连续答错 3 题 → 难度降低", after_difficulty < before_difficulty,
      (before_difficulty, after_difficulty))
check("连续答错 3 题 → 控制器给出负调整",
      after_question["adaptive"]["difficulty_state"]["delta"] <= -10,
      after_question["adaptive"]["difficulty_state"])
check("连续答错 3 题 → 记录连错次数",
      after_question["adaptive"]["difficulty_state"]["streak"]["count"] >= 3,
      after_question["adaptive"]["difficulty_state"]["streak"])


# ================= 8. 学生 A：乘法连续答对 5 题 → 难度提升 =================

before_up = next_question(1, MULTIPLY)
before_up_difficulty = before_up["adaptive"]["difficulty"]

for index in range(5):
    question = next_question(1, MULTIPLY)
    result = submit(1, question, truth_of(question["question_id"]))
    if not result["correct"]:
        check(f"第 {index + 1} 道乘法题判对", False, result)
        break
else:
    check("连续答对 5 道乘法题", True)

after_up = next_question(1, MULTIPLY)
after_up_difficulty = after_up["adaptive"]["difficulty"]
check("连续答对 5 题 → 难度提升", after_up_difficulty > before_up_difficulty,
      (before_up_difficulty, after_up_difficulty))
check("连续答对 5 题 → 控制器给出正调整",
      after_up["adaptive"]["difficulty_state"]["delta"] >= 5,
      after_up["adaptive"]["difficulty_state"])
check("连续答对 5 题 → 记录连对次数",
      after_up["adaptive"]["difficulty_state"]["streak"]["count"] >= 5,
      after_up["adaptive"]["difficulty_state"]["streak"])
check("难度始终不越界", 1 <= after_up_difficulty <= 100, after_up_difficulty)


# ================= 9. 学习反馈 =================

feedback = http.post(BASE + "/api/learning/feedback",
                     json={"student_id": 1, "subject": "数学", "knowledge": MULTIPLY,
                           "question_id": after_up["question_id"], "correct": False,
                           "feel": "hard", "need_help": True, "note": "不会列式"},
                     timeout=20).json()
check("反馈已保存", feedback["saved"] is True and feedback["id"] > 0, feedback["id"])
check("反馈返回难度感受文案", feedback["feel_text"] == "有点难", feedback["feel_text"])
check("反馈给出下一次难度建议", 1 <= feedback["next_difficulty"] <= 100,
      feedback["next_difficulty"])
check("需要帮助时给出安抚与降难度提示", "下一题难度会降" in feedback["message"],
      feedback["message"])
check("反馈带四种表情选项", len(feedback["feel_options"]) == 4, feedback["feel_options"])
check("反馈推进今日计划完成数", feedback["plan"]["completed_count"] >= 1,
      feedback["plan"])
check("非法难度感受返回 400",
      http.post(BASE + "/api/learning/feedback",
                json={"student_id": 1, "feel": "very-easy"}, timeout=10).status_code == 400)

easy_feedback = http.post(BASE + "/api/learning/feedback",
                          json={"student_id": 1, "subject": "数学", "knowledge": MULTIPLY,
                                "feel": "easy", "correct": True}, timeout=20).json()
check("觉得简单 → 难度建议上调", easy_feedback["difficulty_delta"] >= 3,
      easy_feedback["difficulty_delta"])

logs = http.get(f"{BASE}/api/learning/strategy-log/1", timeout=20).json()
check("策略日志记录了推荐原因",
      any("掌握度" in item["reason"] for item in logs["logs"]), logs["logs"][:2])
check("策略日志区分来源",
      len({item["source"] for item in logs["logs"]}) >= 2,
      {item["source"] for item in logs["logs"]})
check("反馈历史可查", logs["feedback"]["total"] >= 2, logs["feedback"]["total"])
check("反馈按感受统计", logs["feedback"]["by_feel"].get("hard") == 1,
      logs["feedback"]["by_feel"])
check("计划参数可查", logs["planning"]["total_minutes"] == 35, logs["planning"])


# ================= 10. 学生 B：数据隔离 =================

second = recommend(2, "数学")
check("学生 B 也有独立推荐", bool(second["next_action"]["knowledge"]),
      second["next_action"]["knowledge"])
check("学生 B 推荐里掌握度是空的（没练过）",
      all(item["decision"]["evidence"]["mastery"] == 0 for item in second["subjects"]),
      [item["subject"] for item in second["subjects"]])

plan_b = http.get(f"{BASE}/api/learning/plan/2", timeout=20).json()
check("学生 A 与学生 B 的今日计划各自独立",
      plan_b["student_id"] == 2 and plan_b["completed_count"] == 0,
      (plan_b["student_id"], plan_b["completed_count"]))

db = SessionLocal()
a_plans = db.query(LearningPlan).filter(LearningPlan.student_id == 1).count()
b_plans = db.query(LearningPlan).filter(LearningPlan.student_id == 2).count()
a_logs = db.query(LearningStrategyLog).filter(LearningStrategyLog.student_id == 1).count()
b_logs = db.query(LearningStrategyLog).filter(LearningStrategyLog.student_id == 2).count()
a_feedback = db.query(LearningFeedback).filter(LearningFeedback.student_id == 1).count()
b_feedback = db.query(LearningFeedback).filter(LearningFeedback.student_id == 2).count()
db.close()

check("学生 A 的计划已落库", a_plans >= 1, a_plans)
check("学生 B 的计划独立落库", b_plans >= 1, b_plans)
check("两个学生的策略日志各自记录", a_logs >= 5 and b_logs >= 1, (a_logs, b_logs))
check("学生 B 没有学习反馈", b_feedback == 0 and a_feedback >= 2, (a_feedback, b_feedback))

logs_b = http.get(f"{BASE}/api/learning/strategy-log/2", timeout=20).json()
check("学生 B 的推荐理由里没有学生 A 的练习数据",
      all("掌握度" not in item["reason"] for item in logs_b["logs"]),
      [item["reason"] for item in logs_b["logs"]][:2])


# ================= 11. 接口契约与前端页面 =================

root = http.get(BASE + "/", timeout=10).json()
check("版本已是 2.6（V2.3 能力保留）", root["version"] == "2.6", root["version"])
check("首页列出自适应学习引擎",
      any("自适应" in item for item in root["features"]), root["features"][-2:])

plain = http.get(BASE + "/question", params={"student_id": 1, "subject": "数学",
                                             "knowledge": KNOWLEDGE}, timeout=60).json()
check("原有出题接口仍然可用（向后兼容）", bool(plain.get("question_id")), plain.get("question_id"))

for page in ("today.html",):
    response = http.get(f"{BASE}/app/{page}", timeout=10)
    check(f"新页面可访问 {page}",
          response.status_code == 200 and "<html" in response.text.lower(),
          response.status_code)

for asset in ("today.js",):
    response = http.get(f"{BASE}/app/{asset}", timeout=10)
    check(f"新页面脚本可访问 {asset}",
          response.status_code == 200 and len(response.text) > 200, response.status_code)


# ================= 收尾 =================

if proc is not None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    db_engine.dispose()

    db_file = os.environ["DATABASE_URL"].replace("sqlite:///", "")
    for suffix in ("", "-journal", "-wal", "-shm"):
        if os.path.exists(db_file + suffix):
            os.remove(db_file + suffix)

print("\nRESULT:", "ALL PASS" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)
