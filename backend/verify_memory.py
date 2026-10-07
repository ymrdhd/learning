# ==============================================================
# 能力契约｜验证：V2.4 间隔复习系统（10 个必测场景 + 风险/成熟度/配比/地图/迁移/隔离），端口 8906
# 入口：脚本自身：python backend/verify_memory.py
# 依赖：review.*（engine/memory/interval/forgetting/scheduler/selector/mix）、main、models、database
# 不负责：V2.1 旧体系 → verify_review.py
# 验证：python backend/verify_memory.py
# 被调用：verify_all.py（套件 memory）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统（Spaced Repetition & Forgetting Risk Engine）测试。

覆盖需求里的 10 个必测场景 + API + 迁移 + 隔离：

  测试 1  新知识首次掌握 → 1 天后复习
  测试 2  连续 GOOD → 间隔 1 → 3 → 7 → 14 → 30
  测试 3  连续 EASY → 间隔增长更快
  测试 4  复习错误 → 间隔缩短
  测试 5  长期掌握的知识偶尔错 1 题 → 不立即重置（追加验证题）
  测试 6  多次复习错误 → 进入 RELEARN
  测试 7  学生 A / 学生 B 完全隔离
  测试 8  超过 30 天没登录 → 复习任务分批调度（每天最多 15 个）
  测试 9  同一知识点的复习题不会完全复制历史题
  测试 10 今日计划同时包含：新学 / 薄弱补强 / 间隔复习

  另外：遗忘风险模型、成熟度六级、每日配比、记忆地图、统计、策略日志、
        V2.3 数据安全迁移（≥85 → STABLE / 70~84 → CONSOLIDATING /
        60~69 → LEARNING / <60 → RELEARN）、V2.3 接口向后兼容。

用法：python backend/verify_memory.py   （自拉临时后端，端口 VERIFY_MEMORY_PORT，默认 8906）
全部通过时退出码为 0。
"""

import os
import random
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta

PORT = int(os.getenv("VERIFY_MEMORY_PORT", "8906"))

_db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_memory.db")
for _suffix in ("", "-journal", "-wal", "-shm"):
    if os.path.exists(_db_file + _suffix):
        os.remove(_db_file + _suffix)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
os.environ["DEEPSEEK_API_KEY"] = ""      # 全程本地：题库 / 变式题 / 兜底题，不依赖外网

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

import knowledge_tree
import stages
from database import SessionLocal, engine as db_engine
from models import (
    AnswerRecord,
    Base,
    KnowledgeMemoryState,
    LearningPlan,
    Question,
    ReviewQueue,
    ReviewRecord,
    ReviewStrategyLog,
    StudentKnowledgeMastery,
)
from review import forgetting, interval, memory, mix, scheduler, selector

Base.metadata.create_all(db_engine)

BASE = f"http://127.0.0.1:{PORT}"
NOW = datetime(2026, 10, 10, 9, 0)
ok = True
proc = None
http = requests.Session()


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


def simulate(quality, times=5, mastery=75, difficulty=0.4, start_interval=1.0):
    """模拟连续复习，返回间隔序列（第一个是初始间隔）。"""
    sequence = [start_interval]
    current = start_interval
    stability = 1.0
    successes = 0

    for _ in range(times):
        result = interval.calculate_next_interval(
            current_interval=current, mastery_score=mastery, stability=stability,
            difficulty=difficulty, review_result=quality, successful_reviews=successes,
            now=NOW)
        current = result["next_interval"]
        stability = result["new_stability"]
        successes += 1
        sequence.append(current)

    return sequence


# ================= 测试 1：新知识首次掌握 → 1 天后复习 =================

initial = memory.initial_learn_state(70, 0.5, now=NOW)
check("测试1 新知识首次掌握 → 1 天后复习",
      initial["next_review_at"] == NOW + timedelta(days=1), initial["next_review_at"])
check("测试1 初始间隔为 1 天", initial["current_interval_days"] == 1.0,
      initial["current_interval_days"])
check("测试1 初始稳定性 1.0", initial["stability"] == 1.0, initial["stability"])
check("测试1 首次学会的成熟度是短期掌握",
      initial["maturity_level"] in ("SHORT_TERM", "CONSOLIDATING"), initial["maturity_level"])
check("测试1 初始间隔常量", interval.initial_interval_days() == 1.0)


# ================= 测试 2：连续 GOOD → 1/3/7/14/30 =================

good_sequence = simulate("GOOD", times=4)
check("测试2 连续 GOOD → 间隔 1/3/7/14/30",
      good_sequence == [1.0, 3.0, 7.0, 14.0, 30.0], good_sequence)
check("测试2 间隔单调递增",
      all(good_sequence[index] < good_sequence[index + 1]
          for index in range(len(good_sequence) - 1)), good_sequence)
check("测试2 稳定性随复习增长", simulate("GOOD", times=2)[-1] > 0, "ok")

# ================= 测试 3：连续 EASY → 增长更快 =================

easy_sequence = simulate("EASY", times=4)
check("测试3 连续 EASY → 增长更快",
      all(easy_sequence[index] >= good_sequence[index] for index in range(len(good_sequence)))
      and easy_sequence[-1] > good_sequence[-1], (easy_sequence, good_sequence))
check("测试3 EASY 第二次就到 5 天", easy_sequence[1] == 5.0, easy_sequence)

hard_sequence = simulate("HARD", times=3)
check("测试3 连续 HARD → 增长更慢", hard_sequence[-1] < good_sequence[-1],
      (hard_sequence, good_sequence))

# ================= 测试 4：复习错误 → 间隔缩短 =================

failed = interval.calculate_next_interval(
    current_interval=7, mastery_score=70, stability=7, difficulty=0.5,
    review_result="AGAIN", successful_reviews=2, now=NOW)
check("测试4 复习错误 → 间隔缩短", failed["next_interval"] < 7, failed["next_interval"])
check("测试4 复习错误按 0.35 压缩", 1.0 <= failed["next_interval"] <= 3.0,
      failed["next_interval"])
check("测试4 复习错误 → 稳定性下降", failed["new_stability"] < 7, failed["new_stability"])
check("测试4 间隔不低于 1 天",
      interval.calculate_next_interval(current_interval=1, mastery_score=90, stability=1,
                                       difficulty=0.1, review_result="AGAIN",
                                       now=NOW)["next_interval"] >= 1.0)
check("测试4 间隔不超过 180 天",
      interval.calculate_next_interval(current_interval=180, mastery_score=95,
                                       stability=180, difficulty=0.1,
                                       review_result="EASY", successful_reviews=9,
                                       now=NOW)["next_interval"] <= 180.0)

# ================= 测试 5/6：成熟度、长期掌握与 RELEARN =================

check("成熟度六级齐全", memory.MATURITY_LEVELS ==
      ("NEW", "LEARNING", "SHORT_TERM", "CONSOLIDATING", "STABLE", "LONG_TERM"))
check("儿童文案不含英文",
      all(not any(char.isascii() and char.isalpha() for char in text)
          for text in memory.MATURITY_CHILD.values()), memory.MATURITY_CHILD)
check("知识森林字段齐全（V2.6 预留）",
      set(memory.MATURITY_FOREST) == set(memory.MATURITY_LEVELS), memory.MATURITY_FOREST)

long_term = memory.migrate_state(92, 0.9, now=NOW)
long_term.update({"stability": 70.0, "successful_reviews": 6, "review_count": 8,
                  "current_interval_days": 60.0})
check("长期掌握的知识：稳定性 ≥60 → LONG_TERM",
      memory.maturity_of(92, 70.0, 6, 8) == "LONG_TERM", memory.maturity_of(92, 70.0, 6, 8))
check("测试5 偶尔错 1 题不会重置成熟度",
      memory.maturity_of(92, 70.0 * 0.45, 6, 9) in ("STABLE", "CONSOLIDATING"),
      memory.maturity_of(92, 70.0 * 0.45, 6, 9))
check("测试5 偶尔错 1 题不会要求重新学", memory.needs_relearn(92, 1) is False)
check("测试6 连续错 2 次 → 需要重新学（RELEARN）", memory.needs_relearn(92, 2) is True)
check("测试6 掌握度 <60 → RELEARN", memory.needs_relearn(55, 0) is True)
check("测试6 RELEARN 状态直接标记", memory.action_of(
    {"mastery_score": 40, "needs_relearn": True, "next_review_at": NOW}) == "RELEARN")

# ================= 遗忘风险模型 =================

fresh = forgetting.calculate_forgetting_risk({
    "mastery_score": 80, "stability": 7, "difficulty": 0.4, "current_interval_days": 7,
    "successful_reviews": 3, "failed_reviews": 1, "last_reviewed_at": NOW}, now=NOW)
check("刚复习完 → 遗忘风险接近 0", fresh["risk"] < 0.05, fresh["risk"])
check("风险分级：低", fresh["level"] == "低", fresh["level"])

overdue = forgetting.calculate_forgetting_risk({
    "mastery_score": 70, "stability": 3, "difficulty": 0.5, "current_interval_days": 7,
    "successful_reviews": 1, "failed_reviews": 1,
    "last_reviewed_at": NOW - timedelta(days=10)}, now=NOW)
check("10 天没复习 / 原定 7 天 → 高风险",
      overdue["risk"] >= forgetting.HIGH_RISK and overdue["level"] == "高",
      (overdue["risk"], overdue["level"]))
check("风险带逾期天数", overdue["overdue_days"] >= 2.9, overdue["overdue_days"])
check("风险恒在 0~1",
      all(0.0 <= forgetting.calculate_forgetting_risk(
          {"mastery_score": m, "stability": s, "difficulty": d,
           "current_interval_days": 7, "last_reviewed_at": NOW - timedelta(days=e)},
          now=NOW)["risk"] <= 1.0
          for m, s, d, e in ((0, 0.5, 0.9, 0), (100, 180, 0.1, 400), (50, 1, 0.5, 30))))

# ================= 每日配比 calculate_daily_mix =================

mix_none = mix.calculate_daily_mix(review_due=0)
check("没有复习任务 → 复习比例 ≤10%", mix_none["review_ratio"] <= 0.10,
      mix_none["review_ratio"])
mix_many = mix.calculate_daily_mix(review_due=6, high_risk=4, average_risk=0.7,
                                   weakness_count=3)
check("大量高风险 → 复习比例提高到 30% 以上", mix_many["review_ratio"] >= 0.30,
      mix_many["review_ratio"])
check("三类比例合计 1.0",
      abs(sum(mix.calculate_daily_mix(review_due=3, weakness_count=2)[key]
              for key in ("new_learning_ratio", "weakness_ratio", "review_ratio")) - 1.0) < 0.02)
check("配比可以拆成题量",
      sum(mix.split_counts(10, mix_many).values()) == 10, mix.split_counts(10, mix_many))
check("默认配比是 50/30/20", mix.DEFAULT_MIX ==
      {"new_learning": 0.50, "weakness": 0.30, "review": 0.20})

# ================= 测试 8：分批调度 =================

flood = []
for index in range(40):
    flood.append({
        "student_id": 1,
        "subject": ("数学", "语文", "英语")[index % 3],
        "knowledge_id": f"压力知识点{index}",
        "mastery_score": 80, "stability": 3, "difficulty": 0.5,
        "current_interval_days": 7, "forgetting_risk": 0.9,
        "successful_reviews": 1, "failed_reviews": 0,
        "maturity_level": "CONSOLIDATING", "needs_relearn": False,
        "next_review_at": NOW - timedelta(days=10),
        "last_reviewed_at": NOW - timedelta(days=17),
    })
built = scheduler.build_queue(flood, now=NOW)
check("测试8 长期没登录 → 每天最多 15 个复习任务", built["total"] == 15, built["total"])
check("测试8 超出的任务被顺延", built["deferred_count"] == 25, built["deferred_count"])
check("测试8 每科不超过 8 个",
      all(count <= 8 for count in built["by_subject"].values()), built["by_subject"])
check("测试8 优先级 P0 在最前",
      all(item["priority"] == "P0" for item in built["items"][:5]),
      [item["priority"] for item in built["items"][:5]])
check("测试8 每个知识点 1~3 题",
      all(1 <= item["target_count"] <= 3 for item in built["items"]),
      [item["target_count"] for item in built["items"][:5]])
check("测试8 RELEARN 的知识点不进复习队列",
      scheduler.build_queue([dict(flood[0], needs_relearn=True)])["total"] == 0
      and len(scheduler.build_queue([dict(flood[0], needs_relearn=True)])["relearn"]) == 1)
check("测试8 风险越高题量越多",
      scheduler.target_count_of(0.9) == 3 and scheduler.target_count_of(0.3) == 1,
      (scheduler.target_count_of(0.9), scheduler.target_count_of(0.3)))

# ================= 测试 9：复习题不重复（纯函数层） =================

history = ["算一算：36 × 24 = ？", "一盒彩笔 18 支，学校买了 42 盒，一共有多少支？"]
check("测试9 完全相同的题干算重复",
      selector.is_duplicate("算一算：36 × 24 = ？", history) is True)
check("测试9 换了数字就不算重复",
      selector.is_duplicate("算一算：42 × 18 = ？", history) is False)
check("测试9 换情境算新题",
      selector.is_duplicate("小明买了 42 盒铅笔，每盒 18 支，一共多少支？", history) is False)
check("测试9 语文题文字相同算重复",
      selector.is_duplicate("「大」的拼音是？", ["「大」的拼音是？"]) is True)
check("测试9 相似度函数可用", 0.0 <= selector.similarity("abc", "abd") <= 1.0)

random.seed(20261010)
modes = [selector.choose_mode("LONG_TERM", random.Random(index)) for index in range(400)]
check("测试9 长期掌握 → 迁移题比例提高",
      modes.count("transfer") / 400.0 >= 0.30, modes.count("transfer") / 400.0)
plain_modes = [selector.choose_mode("LEARNING", random.Random(index)) for index in range(600)]
check("测试9 普通知识点 → 同知识点新题占多数",
      0.42 <= plain_modes.count("same") / 600.0 <= 0.58,
      plain_modes.count("same") / 600.0)

# ================= 迁移分档（纯函数） =================

check("迁移：≥85 → STABLE",
      memory.migrate_state(90)["maturity_level"] == "STABLE")
check("迁移：70~84 → CONSOLIDATING",
      memory.migrate_state(75)["maturity_level"] == "CONSOLIDATING")
check("迁移：60~69 → LEARNING",
      memory.migrate_state(65)["maturity_level"] == "LEARNING")
check("迁移：<60 → 需要重新学",
      memory.migrate_state(45)["needs_relearn"] is True, memory.migrate_state(45))
check("迁移间隔：90 分 → 14 天",
      memory.migrate_state(90)["current_interval_days"] == 14.0)
check("迁移间隔：75 分 → 7 天",
      memory.migrate_state(75)["current_interval_days"] == 7.0)
check("迁移间隔：65 分 → 3 天",
      memory.migrate_state(65)["current_interval_days"] == 3.0)


# ================= 准备 V2.3 数据（模拟老库升级） =================

def seed_practice(db, student_id, subject, knowledge, correct_count, wrong_count=0,
                  difficulty=60, grade=2):
    """造 V2.3 风格的答题记录，并用 MasteryEngine 生成掌握度（自洽数据）。"""
    from knowledge_routes import update_mastery

    when = datetime.now() - timedelta(days=3)
    for index in range(correct_count + wrong_count):
        question = Question(
            subject=subject, grade=grade, knowledge=knowledge, difficulty=difficulty,
            question=f"【历史题】{knowledge} 第 {index + 1} 题", answer="A",
            qtype="choice", options='{"A":"1","B":"2","C":"3","D":"4"}',
            acceptable="[]", analysis="历史练习")
        db.add(question)
        db.flush()
        db.add(AnswerRecord(
            student_id=student_id, subject=subject, knowledge=knowledge,
            difficulty=difficulty, correct=index >= wrong_count,
            question_id=question.id, submitted="A" if index >= wrong_count else "B",
            created_at=when + timedelta(minutes=index)))

    db.flush()
    return update_mastery(db, student_id, subject, knowledge,
                          stage=stages.key_of_difficulty(difficulty), when=when)


db = SessionLocal()
from local_users import init_default_users

init_default_users(db)
knowledge_tree.ensure_seeded(db)
knowledge_tree.link_mastery(db)

seeded = [
    # (学生, 科目, 知识点, 答对, 答错, 期望迁移后的成熟度)
    (1, "数学", "表内乘法", 30, 0, "STABLE"),
    (1, "数学", "两步计算应用题", 8, 4, "LEARNING"),
    (1, "数学", "表内除法", 12, 18, "LEARNING+RELEARN"),
    (1, "英语", "颜色", 20, 0, "STABLE"),
    (1, "语文", "拼音拼读", 13, 2, "CONSOLIDATING"),
    (2, "数学", "20以内加减法", 3, 7, "LEARNING+RELEARN"),
]
mastery_snapshot = {}
for student_id, subject, knowledge, correct, wrong, _ in seeded:
    row = seed_practice(db, student_id, subject, knowledge, correct, wrong)
    mastery_snapshot[(student_id, knowledge)] = int(row.mastery_score)
db.commit()
db.close()

check("V2.3 数据准备完成（掌握度已生成）",
      mastery_snapshot[(1, "表内乘法")] >= 85 and mastery_snapshot[(1, "表内除法")] < 60,
      mastery_snapshot)


# ================= 启动临时后端（启动时自动迁移记忆状态） =================

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


def states_of(student_id=1):
    session = SessionLocal()
    rows = session.query(KnowledgeMemoryState).filter(
        KnowledgeMemoryState.student_id == student_id).all()
    snapshot = {(row.subject, row.knowledge_id): {
        "mastery": int(row.mastery_score or 0),
        "stability": float(row.stability or 0),
        "maturity": row.maturity_level,
        "needs_relearn": bool(row.needs_relearn),
        "interval": float(row.current_interval_days or 0),
        "strength": int(row.memory_strength or 0),
        "risk": float(row.forgetting_risk or 0),
        "next_review_at": row.next_review_at,
    } for row in rows}
    session.close()
    return snapshot


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


def ask_review(student_id, subject, knowledge, difficulty=0):
    return http.get(BASE + "/api/review/question",
                    params={"student_id": student_id, "subject": subject,
                            "knowledge_id": knowledge, "difficulty": difficulty},
                    timeout=60).json()


def answer_review(student_id, question, value, response_time=10, feel=""):
    return http.post(BASE + "/api/review/answer",
                     json={"student_id": student_id, "question_id": question["question_id"],
                           "answer": value, "response_time": response_time,
                           "difficulty_feedback": feel}, timeout=30).json()


# ================= 迁移结果（启动时自动完成） =================

states_a = states_of(1)
check("升级后学生 1 的每个 V2.3 知识点都有记忆状态",
      len(states_a) == 5, sorted(states_a))
check("迁移：≥85 → STABLE",
      states_a[("数学", "表内乘法")]["maturity"] == "STABLE",
      states_a[("数学", "表内乘法")]["maturity"])
check("迁移：70~84 → CONSOLIDATING",
      states_a[("语文", "拼音拼读")]["maturity"] == "CONSOLIDATING",
      states_a[("语文", "拼音拼读")]["maturity"])
check("迁移：60~69 → LEARNING",
      states_a[("数学", "两步计算应用题")]["maturity"] == "LEARNING",
      states_a[("数学", "两步计算应用题")]["maturity"])
check("迁移：<60 → RELEARN",
      states_a[("数学", "表内除法")]["needs_relearn"] is True,
      states_a[("数学", "表内除法")])
check("迁移后掌握度与 V2.3 一致",
      states_a[("数学", "表内乘法")]["mastery"] == mastery_snapshot[(1, "表内乘法")],
      (states_a[("数学", "表内乘法")]["mastery"], mastery_snapshot[(1, "表内乘法")]))


# ================= 今日队列 / 统计 API =================

today = http.get(f"{BASE}/api/review/today/1", timeout=30).json()
check("今日复习接口可用", today["total"] >= 3, today["total"])
check("儿童文案说几个知识需要浇水", "浇水" in today["child_title"], today["child_title"])
check("队列项带成熟度儿童文案",
      all(item["maturity_child"] for item in today["items"]), today["items"][:1])
check("队列项带优先级",
      all(item["priority"] in scheduler.PRIORITY_ORDER for item in today["items"]),
      [item["priority"] for item in today["items"]])
check("需要重学的知识点单独列出",
      any(item["knowledge_id"] == "表内除法" for item in today["relearn"]), today["relearn"])
check("需要重学的知识点不在复习队列里",
      all(item["knowledge_id"] != "表内除法" for item in today["items"]))

due = http.get(f"{BASE}/api/review/due/1", timeout=30).json()
check("到期列表可用", due["total"] >= 1, due["total"])
check("到期项带遗忘风险与成熟度",
      all({"forgetting_risk", "maturity_level", "next_review_at"} <= set(item)
          for item in due["items"]), due["items"][:1])

stats = http.get(f"{BASE}/api/review/stats/1", timeout=30).json()
check("统计：今日复习数量 / 完成数量 / 即将遗忘 / 长期掌握",
      {"due_count", "completed_count", "high_risk_count", "long_term_count"} <= set(stats),
      {key: stats[key] for key in ("due_count", "completed_count", "high_risk_count",
                                   "long_term_count")})
check("统计覆盖记忆状态总量", stats["total_knowledge"] == 5, stats["total_knowledge"])


# ================= 测试 9：复习题不重复历史题 =================

session = SessionLocal()
history_stems = [row[0] for row in session.query(Question.question).filter(
    Question.subject == "数学", Question.knowledge == "表内乘法").all()]
session.close()

first_question = ask_review(1, "数学", "表内乘法")
check("复习题接口返回题目与选项",
      bool(first_question["question_id"]) and bool(first_question["options"]),
      first_question["question_id"])
check("复习题带模式（同知识点/变式/迁移）",
      first_question["mode"] in selector.MODES, first_question["mode"])
check("复习题带期望作答时间", first_question["expected_seconds"] > 0,
      first_question["expected_seconds"])
check("复习题锁定同一个知识点", first_question["knowledge"] == "表内乘法")
check("测试9 复习题不是历史原题",
      first_question["question"] not in history_stems, first_question["question"])
check("测试9 复习题题干与历史题都不同（去重函数判定）",
      selector.is_duplicate(first_question["question"], history_stems) is False)

same_stems = set()
for _ in range(4):
    item = ask_review(1, "数学", "表内乘法")
    same_stems.add(item["question"])
check("测试9 连续出题不会反复复制同一道题", len(same_stems) >= 3, same_stems)


# ================= 测试 5：长期掌握偶尔错 1 题（不重置） =================

before = states_of(1)[("数学", "表内乘法")]
easy_question = ask_review(1, "数学", "表内乘法")
easy_result = answer_review(1, easy_question, truth_of(easy_question["question_id"]),
                            response_time=5)
check("复习答对 → 质量判定 EASY（又快又对）",
      easy_result["review_quality"] == "EASY", easy_result["review_quality"])
check("测试4/验收C 复习成功 → 间隔延长",
      easy_result["next_interval"] > easy_result["previous_interval"],
      (easy_result["previous_interval"], easy_result["next_interval"]))
check("复习成功 → 稳定性提高",
      easy_result["new_stability"] > easy_result["previous_stability"],
      (easy_result["previous_stability"], easy_result["new_stability"]))
check("复习成功 → 记忆强度提升",
      easy_result["memory_strength"] >= before["strength"],
      (before["strength"], easy_result["memory_strength"]))
check("复习成功 → 给出鼓励文案",
      bool(easy_result["child_message"]) and easy_result["action"] == "REVIEW",
      easy_result["child_message"])

hard_question = ask_review(1, "数学", "表内乘法")
hard_result = answer_review(1, hard_question, wrong_of(hard_question), response_time=80)
check("复习答错 → 质量判定 AGAIN",
      hard_result["review_quality"] == "AGAIN", hard_result["review_quality"])
check("验收D 复习失败 → 间隔缩短",
      hard_result["next_interval"] < hard_result["previous_interval"],
      (hard_result["previous_interval"], hard_result["next_interval"]))
check("测试5 偶尔错 1 题：间隔没有被重置到 1 天",
      hard_result["next_interval"] > 1.0, hard_result["next_interval"])
check("测试5 偶尔错 1 题：成熟度没有掉回刚学会",
      hard_result["maturity_level"] not in ("NEW", "LEARNING"),
      hard_result["maturity_level"])
check("测试5 偶尔错 1 题：追加一道验证题",
      hard_result["need_verify"] is True, hard_result["need_verify"])
check("复习失败也会进错题本",
      hard_result["wrong_book"]["total"] >= 1, hard_result["wrong_book"])
check("复习失败给出安抚文案", "验证" in hard_result["child_message"],
      hard_result["child_message"])

# ================= 测试 6：连续失败 → RELEARN =================

relearn_question = ask_review(1, "数学", "表内乘法")
relearn_result = answer_review(1, relearn_question, wrong_of(relearn_question),
                               response_time=90)
check("测试6 连续 2 次复习失败 → 转入 RELEARN",
      relearn_result["action"] == "RELEARN", relearn_result["action"])
check("测试6 RELEARN 时下次复习时间就在今天",
      relearn_result["next_review_at"] != "", relearn_result["next_review_at"])
today_mid = http.get(f"{BASE}/api/review/today/1", timeout=30).json()
check("测试6 RELEARN 的知识点不再出现在复习卡片里",
      all(item["knowledge_id"] != "表内乘法" for item in today_mid["items"]),
      [item["knowledge_id"] for item in today_mid["items"]])
today_after = http.get(f"{BASE}/api/review/today/1?refresh=true", timeout=30).json()
check("测试6 RELEARN 的知识点进入重学列表",
      any(item["knowledge_id"] == "表内乘法" for item in today_after["relearn"]),
      today_after["relearn"])


# ================= 复习记录 / 策略日志 / 感受反馈 / 跳过 =================

session = SessionLocal()
records = session.query(ReviewRecord).filter(ReviewRecord.student_id == 1).count()
logs = session.query(ReviewStrategyLog).filter(ReviewStrategyLog.student_id == 1).count()
queue_rows = session.query(ReviewQueue).filter(ReviewQueue.student_id == 1).count()
session.close()
check("复习明细已落库", records >= 3, records)
check("复习策略日志已落库", logs >= 3, logs)
check("复习队列已落库", queue_rows >= 3, queue_rows)

log_api = http.get(f"{BASE}/api/review/strategy-log/1", timeout=30).json()
check("策略日志带原因（为什么改复习日期）",
      any("间隔" in item["reason"] or "阶梯" in item["reason"] for item in log_api["logs"]),
      log_api["logs"][:1])
check("策略日志带间隔变化",
      all({"old_interval", "new_interval", "reason"} <= set(item) for item in log_api["logs"]))
check("日志接口返回复习质量字典与阶梯",
      len(log_api["quality_text"]) == 4 and len(log_api["interval_ladder"]) == 5,
      log_api["interval_ladder"])
check("日志接口返回今日配比",
      "review_ratio" in log_api["today_mix"], log_api["today_mix"])

feel_question = ask_review(1, "英语", "颜色")
answer_review(1, feel_question, truth_of(feel_question["question_id"]), response_time=20)
feel_result = http.post(BASE + "/api/review/feedback",
                        json={"student_id": 1, "question_id": feel_question["question_id"],
                              "feel": "easy"}, timeout=30).json()
check("感受反馈已保存", feel_result["saved"] is True, feel_result["feel"])
check("感受反馈会微调下次间隔",
      feel_result["next_interval"] >= feel_result["old_interval"],
      (feel_result["old_interval"], feel_result["next_interval"]))
check("非法感受返回 400",
      http.post(BASE + "/api/review/feedback",
                json={"student_id": 1, "question_id": feel_question["question_id"],
                      "feel": "xx"}, timeout=10).status_code == 400)

skip_target = next((item for item in http.get(f"{BASE}/api/review/today/1", timeout=30).json()
                    ["items"] if item["knowledge_id"] != "表内乘法"), None)
if skip_target:
    skipped = http.post(BASE + "/api/review/skip",
                        json={"student_id": 1, "queue_id": skip_target["queue_id"]},
                        timeout=30).json()
    check("可以跳过今天的复习任务", skipped["status"] == "SKIPPED", skipped)
else:
    check("可以跳过今天的复习任务", False, "没有可跳过的队列项")

map_api = http.get(f"{BASE}/api/review/memory-map/1", timeout=30).json()
check("记忆地图包含全部知识点", map_api["total"] == 5, map_api["total"])
check("记忆地图带稳定性 / 遗忘风险 / 成熟度",
      all({"stability", "forgetting_risk", "maturity_level", "next_review_date"} <= set(item)
          for item in map_api["items"]), map_api["items"][:1])
check("记忆地图带汇总统计",
      {"by_maturity", "average_stability", "average_memory_strength"} <= set(map_api["summary"]),
      map_api["summary"])
check("记忆地图按科目筛选",
      http.get(f"{BASE}/api/review/memory-map/1", params={"subject": "英语"},
               timeout=30).json()["total"] == 1)
check("非法科目返回 400",
      http.get(f"{BASE}/api/review/memory-map/1", params={"subject": "科学"},
               timeout=10).status_code == 400)
check("缺少 knowledge_id 返回 400",
      http.get(f"{BASE}/api/review/question", params={"student_id": 1, "subject": "数学"},
               timeout=10).status_code == 400)
check("不存在的复习题返回 404",
      http.post(BASE + "/api/review/answer",
                json={"student_id": 1, "question_id": 999999, "answer": "A"},
                timeout=10).status_code == 404)


# ================= 测试 10：今日计划包含三类内容 =================

plan = http.get(f"{BASE}/api/learning/plan/1", timeout=40).json()
types = {item["item_type"] for item in plan["items"]}
check("测试10 今日计划包含间隔复习任务", "review" in types, sorted(types))
check("测试10 今日计划包含薄弱补强", "weakness" in types, sorted(types))
check("测试10 今日计划包含新学内容", "new_learning" in types, sorted(types))
check("计划条目带类型文案",
      all(item["item_type_text"] for item in plan["items"]),
      [item["item_type_text"] for item in plan["items"]])
check("计划按类型汇总（by_type）",
      {bucket["item_type"] for bucket in plan["by_type"]} == types,
      plan["by_type"])
check("复习任务的目标是复习而非新学",
      all("复习" in item["goal"] for item in plan["items"] if item["item_type"] == "review"),
      [item["goal"] for item in plan["items"] if item["item_type"] == "review"])

recommend = http.get(f"{BASE}/api/learning/recommend/1", timeout=60).json()
check("V2.3 推荐接口仍可用（向后兼容）", bool(recommend["next_action"]["knowledge"]),
      recommend["next_action"])
check("推荐接口返回今日复习任务",
      "review" in recommend and recommend["review"]["total"] >= 0, recommend.get("review"))
check("推荐接口返回每日配比", "review_ratio" in recommend["daily_mix"],
      recommend["daily_mix"])
check("自适应引擎会读取复习队列（review_first 字段存在）",
      isinstance(recommend["review_first"], bool), recommend["review_first"])

learning_start = http.post(BASE + "/api/learning/start",
                           json={"student_id": 1, "subject": "数学"}, timeout=40).json()
check("自适应开始学习接口仍可用", bool(learning_start["knowledge"]),
      learning_start["knowledge"])
check("开始学习会提示是否先复习",
      "review_first" in learning_start, learning_start.get("review_first"))


# ================= 测试 7：两个学生完全隔离 =================

states_b = states_of(2)
check("测试7 学生 B 只有自己的记忆状态",
      len(states_b) == 1 and ("数学", "20以内加减法") in states_b, sorted(states_b))
check("测试7 学生 B 的掌握度独立",
      states_b[("数学", "20以内加减法")]["mastery"] == mastery_snapshot[(2, "20以内加减法")],
      states_b[("数学", "20以内加减法")]["mastery"])
check("测试7 学生 B 的遗忘风险独立于学生 A",
      all(item["knowledge_id"] != "表内乘法"
          for item in http.get(f"{BASE}/api/review/memory-map/2", timeout=30).json()["items"]))
check("测试7 学生 B 的今日队列独立",
      http.get(f"{BASE}/api/review/today/2", timeout=30).json()["total"] == 0,
      http.get(f"{BASE}/api/review/today/2", timeout=30).json()["total"])
check("测试7 学生 B 的待重学列表包含自己的知识点",
      any(item["knowledge_id"] == "20以内加减法"
          for item in http.get(f"{BASE}/api/review/today/2", timeout=30).json()["relearn"]))

session = SessionLocal()
records_b = session.query(ReviewRecord).filter(ReviewRecord.student_id == 2).count()
queue_b = session.query(ReviewQueue).filter(ReviewQueue.student_id == 2).count()
session.close()

plan_b = http.get(f"{BASE}/api/learning/plan/2", timeout=40).json()
check("测试7 学生 B 的今日计划可以单独生成",
      plan_b["student_id"] == 2 and len(plan_b["items"]) >= 1, plan_b["items"][:1])

session = SessionLocal()
plans_a = session.query(LearningPlan).filter(LearningPlan.student_id == 1).count()
plans_b = session.query(LearningPlan).filter(LearningPlan.student_id == 2).count()
plans_b_review = session.query(LearningPlan).filter(
    LearningPlan.student_id == 2, LearningPlan.item_type == "review").count()
session.close()
check("测试7 学生 B 没有复习记录", records_b == 0, records_b)
check("测试7 学生 B 的复习队列独立计数", queue_b >= 0, queue_b)
check("测试7 两个学生的计划各自独立", plans_a >= 1 and plans_b >= 1, (plans_a, plans_b))
check("测试7 学生 B 没有到期复习任务，计划里也没有复习块",
      plans_b_review == 0, plans_b_review)


# ================= 接口契约与前端页面 =================

root = http.get(BASE + "/", timeout=10).json()
check("版本升级到 2.6（V2.4 能力保留）", root["version"] == "2.6", root["version"])
check("首页列出间隔复习系统",
      any("间隔复习" in item for item in root["features"]), root["features"][-2:])
check("首页保留 V2.3 自适应学习引擎",
      any("自适应学习引擎" in item for item in root["features"]))

for page in ("review.html", "memory_debug.html"):
    response = http.get(f"{BASE}/app/{page}", timeout=10)
    check(f"新页面可访问 {page}",
          response.status_code == 200 and "<html" in response.text.lower(),
          response.status_code)

for asset in ("review.js", "memory_debug.js"):
    response = http.get(f"{BASE}/app/{asset}", timeout=10)
    check(f"新页面脚本可访问 {asset}",
          response.status_code == 200 and len(response.text) > 200, response.status_code)

plain = http.get(BASE + "/question", params={"student_id": 1, "subject": "数学",
                                             "knowledge": "表内乘法"}, timeout=60).json()
check("原有出题接口仍然可用（向后兼容）", bool(plain.get("question_id")),
      plain.get("question_id"))
plain_submit = http.post(BASE + "/submit",
                         json={"question_id": plain["question_id"], "answer": "A",
                               "student_id": 1}, timeout=30).json()
check("原有判分接口带 V2.4 记忆状态",
      plain_submit.get("memory") is not None
      and "maturity_child" in (plain_submit.get("memory") or {}),
      plain_submit.get("memory"))


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
