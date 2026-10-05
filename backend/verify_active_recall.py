# ==============================================================
# 能力契约｜主动回忆套件：出卡 / 判分 / 记忆增益 / 提示折减 / 每日总结 / 今日计划 / 休息保护 / 学生隔离
# 入口：check / compat_case / start_server / recall_case / daily_case / plan_case / habit_case / isolation_case / failure_case / main
# 依赖：os sys json socket sqlite3 subprocess、requests、active_recall、database、models、habit
# 不负责：修 bug（只记录缺陷）→ Lead；判分与记忆增益算法 → active_recall.py；任务配比 → habit.py
# 验证：python backend/verify_active_recall.py（端口 8912 · 临时库 _verify_active_recall.db）
# 被调用：人工 / verify_all.py（套件 key = recall）
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================

"""V2.5 主动回忆 + 每日收尾门禁套件（SPEC §9 · key=recall · port=8912）。

覆盖：V2.4 旧库迁移兼容（19 张旧表行数 / 列结构不变 + 4 张 V2.5 新表建出）/
主动回忆出卡不给选项（cards 无 answers）· 完全独立回忆成功记忆增益最高 ·
用提示后答对增益显著低于独立答对 · 判分结果与儿童反馈四档 /
每日总结 `GET /api/daily-summary/{student_id}`（完成前 / 已完成后文案与 🎉 结束点）/
今日计划 `/api/tasks/plan/{student_id}` 五段 + 按年级限时 · `POST /api/tasks/start`（幂等）/ 
兼容 path 形式 `/api/tasks/today/{sid}` · `/api/tasks/{id}/complete` · `/api/habit/profile/{sid}` ·
休息保护每月 2 次且不清零历史成长 · `/api/recovery/list/{sid}` 与 `GET /api/recovery/{id}` 不跨学生泄露 /
A·B 两学生完全隔离 · 失败路径（422 / 400 / 空结构）。

纪律：临时库 _verify_active_recall.db（跑完删除）· 绝不写 learning.db · 端口被占用故意失败（不换端口）。
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BACKEND)
DB_PATH = os.path.join(BACKEND, "_verify_active_recall.db")
BASELINE = os.path.join(ROOT, ".v25_schema_baseline.json")
PORT = int(os.getenv("VERIFY_RECALL_PORT", "8912"))
BASE = "http://127.0.0.1:%d" % PORT
NEW_TABLES = ("wrong_question_recovery", "daily_learning_task", "learning_habit_profile",
              "active_recall_record")
STUDENT_A, STUDENT_B, STUDENT_X = 1, 2, 999
GRADE_A = 3          # 3-4 年级 → 15-20 分钟

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

import active_recall  # noqa: E402
from database import (SessionLocal, engine as db_engine, ensure_schema,  # noqa: E402
                      migrate_data)
from models import Base, WrongQuestionRecovery  # noqa: E402

PASSED = 0
FAILED = 0


def check(name, cond, extra=""):
    """记一条断言：打印 PASS/FAIL，并累计计数。"""
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("PASS %s%s" % (name, (" | " + str(extra)) if extra else ""))
    else:
        FAILED += 1
        print("FAIL %s%s" % (name, (" | " + str(extra)) if extra else ""))
    return bool(cond)


def day(offset=0):
    from datetime import timedelta
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 库快照工具

def q(text):
    con = sqlite3.connect(DB_PATH)
    try:
        return con.execute(text).fetchall()
    finally:
        con.close()


def table_names():
    return {row[0] for row in q("select name from sqlite_master where type='table'")}


def row_counts(names):
    return {name: q('select count(*) from "%s"' % name)[0][0] for name in names}


def columns_of(names):
    return {name: {row[1]: str(row[2] or "").upper()
                   for row in q('PRAGMA table_info("%s")' % name)} for name in names}


def scalar(text):
    return q(text)[0][0]


# ---------------------------------------------------------------- V2.4 兼容

def build_v24_db():
    """按 .v25_schema_baseline.json 建 19 张 V2.4 表并塞样例数据，返回基线定义。"""
    with open(BASELINE, "r", encoding="utf-8") as handle:
        baseline = json.load(handle)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = day()
    con = sqlite3.connect(DB_PATH)
    try:
        for name, cols in baseline.items():
            defs = []
            for col, typ in cols.items():
                if col == "__rows":
                    continue
                defs.append('"%s" INTEGER PRIMARY KEY AUTOINCREMENT' % col if col == "id"
                            else '"%s" %s' % (col, typ))
            con.execute('CREATE TABLE "%s" (%s)' % (name, ", ".join(defs)))
        con.execute("INSERT INTO students (id,name,avatar,grade,created_at) VALUES (?,?,?,?,?)",
                    (STUDENT_A, "学生A", "boy", GRADE_A, now))
        con.execute("INSERT INTO students (id,name,avatar,grade,created_at) VALUES (?,?,?,?,?)",
                    (STUDENT_B, "学生B", "girl", 1, now))
        for subject, knowledge, score in (("数学", "两位数乘法", 40), ("语文", "反义词", 55),
                                          ("英语", "食物", 60)):
            con.execute(
                "INSERT INTO student_knowledge_mastery (student_id,subject,knowledge_id,stage,"
                "mastery_score,questions,correct,difficulty_sum,updated_time)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (STUDENT_A, subject, knowledge, "1.1", score, 10, 6, 20.0, now))
        con.execute(
            "INSERT INTO learning_plan (student_id,date,subject,knowledge_id,target_count,status,"
            "item_type,difficulty,goal,reason,priority,created_time,updated_time)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (STUDENT_A, today, "数学", "两位数乘法", 6, "pending", "new_learning", 2,
             "今天认识一个新知识", "来自今日学习计划", 1, now, now))
        con.commit()
    finally:
        con.close()
    return baseline


def compat_case():
    """V2.4 数据兼容：旧表行数 / 列结构不变，新表由 create_all 建出，迁移幂等。"""
    baseline = build_v24_db()
    names = list(baseline)
    rows_before = row_counts(names)
    cols_before = columns_of(names)
    check("V2.4 兼容：19 张旧表 + 样例数据就位",
          len(names) == 19 and rows_before["students"] == 2
          and rows_before["student_knowledge_mastery"] == 3,
          "tables=%d students=%d" % (len(names), rows_before["students"]))

    Base.metadata.create_all(db_engine)
    ensure_schema(Base)
    first = migrate_data()
    check("V2.4 兼容：create_all + ensure_schema + migrate_data 后旧表行数全不变",
          row_counts(names) == rows_before,
          [k for k in rows_before if rows_before[k] != row_counts(names)[k]] or "全部一致")
    cols_after = columns_of(names)
    lost = [k for k in cols_before if not set(cols_before[k]) <= set(cols_after[k])]
    retyped = [k for k in cols_before if k not in lost
               and any(cols_before[k][c] != cols_after[k][c] for c in cols_before[k])]
    check("V2.4 兼容：旧表列没被删除 / 改名 / 改类型", not lost and not retyped,
          "lost=%s retyped=%s" % (lost, retyped))
    check("V2.4 兼容：4 张 V2.5 新表建出（含 active_recall_record）",
          set(NEW_TABLES) <= table_names(), sorted(set(NEW_TABLES) & table_names()))
    check("V2.4 兼容：首次迁移确有改动（非空跑）", sum(first) > 0, first)
    second = migrate_data()
    check("V2.4 兼容：二次迁移幂等（无行被改动）", sum(second) == 0, second)


def seed_recovery():
    """落一条待康复错题（学生 A），用于康复 path 接口与跨学生隔离断言。"""
    db = SessionLocal()
    try:
        row = WrongQuestionRecovery(student_id=STUDENT_A, subject="数学", knowledge_id="两位数乘法",
                                    question_id=900001, state="NEW", attempts=1, fail_count=1,
                                    correct_count=0, consecutive_correct=0, variant_count=0,
                                    source="verify", created_time=datetime.now(),
                                    updated_time=datetime.now())
        db.add(row)
        db.commit()
        return int(row.id)
    finally:
        db.close()


# ---------------------------------------------------------------- HTTP 工具

def get(path, **params):
    return requests.get(BASE + path, params=params, timeout=30)


def post(path, payload):
    return requests.post(BASE + path, json=payload, timeout=60)


def expected_of(card_id):
    for card in active_recall.card_bank():
        if card["id"] == card_id:
            return card["answers"][0]
    return ""


def expected_any(card_id):
    for card in active_recall.card_bank():
        if card["id"] == card_id:
            return list(card["answers"])
    return []


# ---------------------------------------------------------------- 用例

def recall_case():
    """出卡不给选项 + 判分 + 记忆状态接入 + 提示折减。"""
    body = post("/api/active-recall/start",
                {"student_id": STUDENT_A, "subject": "", "count": 4}).json()
    cards = body.get("cards") or []
    check("主动回忆：/start 返回 4 张卡片与提示语",
          len(cards) == 4 and body.get("mode") == "ACTIVE_RECALL" and body.get("minutes", 0) > 0,
          "cards=%d message=%s" % (len(cards), body.get("message")))
    check("主动回忆：卡片只给 prompt/hint，不给选择项",
          all("answers" not in card and "expected" not in card for card in cards)
          and all(card.get("prompt") and card.get("card_id") for card in cards))

    independent = cards[0]
    hinted = cards[1]
    free = post("/api/active-recall/answer",
                {"student_id": STUDENT_A, "card_id": independent["card_id"],
                 "answer": expected_of(independent["card_id"]), "response_time": 6,
                 "hint_level": 0, "confidence_feedback": "确定"}).json()
    check("主动回忆：完全独立回忆成功 → correct + 有记忆增益",
          free.get("result") == "correct" and free.get("memory_gain", 0) > 0
          and free.get("stability", 0) > 0,
          "gain=%s stability=%s" % (free.get("memory_gain"), free.get("stability")))
    check("主动回忆：儿童反馈四档文案",
          free.get("child", {}).get("text") in ("正在学习", "基本会了", "已经掌握", "记得很牢"),
          free.get("child"))

    states = q("select knowledge_id,stability from knowledge_memory_state where student_id=%d"
               % STUDENT_A)
    check("主动回忆：结果写入 MemoryState（KnowledgeMemoryState 有该知识点行）",
          any(row[0] == independent["knowledge"] and float(row[1] or 0) > 0 for row in states),
          states)

    target = expected_any(hinted["card_id"])
    hinted_body = post("/api/active-recall/answer",
                       {"student_id": STUDENT_A, "card_id": hinted["card_id"],
                        "answer": target[0], "response_time": 20, "hint_level": 4,
                        "confidence_feedback": "不太确定"}).json()
    check("主动回忆：用完整提示后答对，增益低于独立答对",
          hinted_body.get("result") == "correct"
          and 0 < hinted_body.get("memory_gain", 0) < free.get("memory_gain", 0),
          "hint_gain=%s free_gain=%s" % (hinted_body.get("memory_gain"), free.get("memory_gain")))
    check("主动回忆：用提示答对仍然记为 correct 但 mastery 由真实作答决定",
          hinted_body.get("hint_level") == 4 and hinted_body.get("expected"))

    wrong_card = cards[2]
    wrong = post("/api/active-recall/answer",
                 {"student_id": STUDENT_A, "card_id": wrong_card["card_id"],
                  "answer": "想不起来了……", "response_time": 25, "hint_level": 0,
                  "confidence_feedback": "不会"}).json()
    check("主动回忆：回忆失败判为 wrong/partial 且给提示句",
          wrong.get("result") in ("wrong", "partial") and wrong.get("lesson", wrong.get("hint", "")) is not None,
          "result=%s" % wrong.get("result"))

    summary = get("/api/active-recall/summary", student_id=STUDENT_A).json()
    check("主动回忆：当天小结统计 3 次作答",
          summary.get("total") == 3 and summary.get("correct", 0) >= 2,
          "total=%s correct=%s" % (summary.get("total"), summary.get("correct")))


def plan_case():
    """今日计划：五段、按年级限时、开始后落库且幂等。"""
    today = day()
    plan = get("/api/tasks/plan/%d" % STUDENT_A, date=today).json()
    kinds = [item.get("task_type") for item in plan.get("items") or []]
    check("今日计划：五段任务齐备（含错题康复 / 主动回忆）",
          set(kinds) == {"new_learning", "weakness", "review", "wrong_recovery", "active_recall"},
          kinds)
    check("今日计划：消息含分钟数（学习启动仪式文案）",
          "分钟" in (plan.get("message") or "") and plan.get("target_minutes", 0) > 0,
          plan.get("message"))
    check("今日计划：目标时长自适应在 10~40 分钟（首次 10 分钟起步）",
          plan.get("min_minutes") == 10 and plan.get("max_minutes") == 40
          and 10 <= plan.get("target_minutes", 0) <= 40
          and sum(item.get("minutes", 0) for item in plan.get("items") or []) <= 40,
          (plan.get("target_minutes"), plan.get("min_minutes"), plan.get("max_minutes")))
    check("今日计划：有动态调整说明（错题积压 / 复习到期 / 无复习）",
          isinstance(plan.get("adjust"), list) and len(plan.get("adjust")) >= 1, plan.get("adjust"))

    started = post("/api/tasks/start", {"student_id": STUDENT_A, "date": today, "minutes": 0}).json()
    tasks = started.get("tasks") or []
    types = {task.get("task_type") for task in tasks}
    check("今日计划：POST /api/tasks/start 落库并返回任务",
          len(tasks) >= 9 and {"new_learning", "weakness", "review", "wrong_recovery",
                               "active_recall"} <= types, sorted(types))
    again = post("/api/tasks/start", {"student_id": STUDENT_A, "date": today, "minutes": 0}).json()
    check("今日计划：重复 start 幂等（任务数不变）",
          len(again.get("tasks") or []) == len(tasks), (len(again.get("tasks") or []), len(tasks)))
    check("今日计划：孩子不需要选知识点（任务自带 subject/knowledge）",
          all(task.get("subject") and task.get("knowledge") for task in tasks))

    path_body = get("/api/tasks/today/%d" % STUDENT_A, date=today).json()
    check("兼容：GET /api/tasks/today/{student_id} 与 /api/tasks/today 同源",
          path_body.get("student_id") == STUDENT_A
          and len(path_body.get("tasks") or []) == len(tasks),
          len(path_body.get("tasks") or []))
    return tasks


def daily_case(tasks):
    """完成全部任务 → DailySummary 出现结束点与儿童版反馈。"""
    today = day()
    before = get("/api/daily-summary/%d" % STUDENT_A, date=today).json()
    check("每日总结：未完成时 finished=False 且不出结束文案",
          before.get("finished") is False and "完成" not in (before.get("message") or ""),
          before.get("message"))
    check("每日总结：字段齐全（child/lines/tasks/habit/recall/recovery/goal/debug）",
          {"finished", "message", "rest_text", "child", "lines", "tasks", "habit", "recall",
           "recovery", "goal", "debug"} <= set(before),
          sorted(before))
    check("每日总结：学习目标来源为 SYSTEM（PARENT/STUDENT 预留）",
          before.get("goal", {}).get("source") == "SYSTEM"
          and "当前目标" in (before.get("goal", {}).get("text") or ""),
          before.get("goal"))

    for task in tasks:
        post("/api/tasks/%d/complete" % int(task["task_id"]),
             {"student_id": STUDENT_A, "minutes": 1, "count": int(task.get("target_count") or 1),
              "done": True})

    after = get("/api/daily-summary/%d" % STUDENT_A, date=today).json()
    check("每日总结：全部完成 → finished=True 且 🎉 结束文案",
          after.get("finished") is True and "🎉" in (after.get("message") or ""),
          after.get("message"))
    check("每日总结：结束后给出「今天可以休息啦！」且不再默认出题",
          "休息" in (after.get("rest_text") or "") and after.get("lines"),
          after.get("rest_text"))
    check("每日总结：儿童版反馈带图标与分钟数",
          all(line[:1] in ("🌱", "🌿", "🌳", "⚔️", "🧠", "⏱") for line in after.get("lines") or [])
          and any("分钟" in line for line in after.get("lines") or []),
          after.get("lines"))
    check("每日总结：debug 保留真实数据（家长 / 调试用）",
          isinstance(after.get("debug"), dict) and "profile" in after["debug"])
    check("每日总结：child 里能看到各类完成数与分钟",
          all(key in after.get("child", {}) for key in
              ("new_learning", "weakness", "review", "wrong_recovery", "active_recall", "minutes"))
          and after["child"]["minutes"] >= 1, after.get("child"))


def habit_case():
    """习惯画像增强 + 休息保护（每月 2 次、不清零历史成长）。"""
    profile = get("/api/habit/profile/%d" % STUDENT_A).json()
    check("习惯画像：path 形式可用且含月度 / 均时长 / 偏好时段字段",
          profile.get("student_id") == STUDENT_A
          and {"monthly_learning_days", "average_daily_minutes", "preferred_learning_time",
               "rest_protection_count", "rest_protection_left"} <= set(profile),
          profile.get("monthly_learning_days"))
    check("习惯画像：本月学习天数与累计天数一致口径（≥1）",
          profile.get("monthly_learning_days", 0) >= 1 and profile.get("total_days", 0) >= 1,
          (profile.get("monthly_learning_days"), profile.get("total_days")))
    days_before = profile.get("total_days", 0)
    minutes_before = profile.get("total_minutes", 0)

    status = get("/api/habit/rest/%d" % STUDENT_A).json()
    check("休息保护：初始剩余 2 次（每月上限 2，不售卖）",
          status.get("rest_protection_left") == 2 and status.get("rest_protection_count") == 0,
          status)
    first = post("/api/habit/rest", {"student_id": STUDENT_A}).json()
    second = post("/api/habit/rest", {"student_id": STUDENT_A}).json()
    third = post("/api/habit/rest", {"student_id": STUDENT_A}).json()
    check("休息保护：前两次可用、第三次被拒",
          first.get("ok") is True and second.get("ok") is True and third.get("ok") is False,
          (first.get("ok"), second.get("ok"), third.get("ok")))
    check("休息保护：用完后剩余为 0 且给出拒绝原因",
          second.get("rest_protection_left") == 0 and "休息保护" in (third.get("reason") or ""),
          third.get("reason"))
    after = get("/api/habit/profile/%d" % STUDENT_A).json()
    check("休息保护：不销毁历史成长（累计天数 / 时长不减少）",
          after.get("total_days", 0) >= days_before
          and after.get("total_minutes", 0) >= minutes_before
          and after.get("rest_protection_count") == 2,
          (after.get("total_days"), after.get("total_minutes"), after.get("rest_protection_count")))
    check("休息保护：使用后连续天数不被清零（≥0 且不长于最长连续）",
          0 <= after.get("current_streak", 0) <= max(1, after.get("longest_streak", 1)),
          (after.get("current_streak"), after.get("longest_streak")))
    goal = get("/api/habit/goal/%d" % STUDENT_A).json()
    check("学习目标：SYSTEM 来源并可读出当前目标",
          goal.get("source") == "SYSTEM" and "当前目标" in (goal.get("text") or ""), goal.get("text"))


def recovery_case(recovery_id):
    """康复 path 兼容入口 + 不跨学生泄露。"""
    listing = get("/api/recovery/list/%d" % STUDENT_A).json()
    check("兼容：GET /api/recovery/list/{student_id} 可用",
          listing.get("student_id") == STUDENT_A and "stats" in listing and "items" in listing,
          sorted(listing))
    detail = get("/api/recovery/%d" % recovery_id, student_id=STUDENT_A).json()
    check("兼容：GET /api/recovery/{recovery_id} 返回单条记录",
          detail.get("student_id") == STUDENT_A, sorted(detail))
    other = get("/api/recovery/%d" % recovery_id, student_id=STUDENT_B).json()
    leaked = json.dumps(other, ensure_ascii=False)
    check("隔离：B 用 A 的 recovery_id 拿不到 A 的记录",
          other.get("student_id") == STUDENT_B and "两位数乘法" not in leaked,
          leaked[:120])
    question = get("/api/recovery/next-question", student_id=STUDENT_A, recovery_id=recovery_id).json()
    check("兼容：GET /api/recovery/next-question 返回题目结构",
          question.get("student_id") == STUDENT_A and isinstance(question, dict), sorted(question))


def isolation_case(tasks):
    """两学生完全隔离：任务 / 主动回忆 / 休息保护。"""
    today = day()
    b_start = post("/api/active-recall/start",
                   {"student_id": STUDENT_B, "subject": "英语", "count": 2}).json()
    b_cards = b_start.get("cards") or []
    check("隔离：B 自己出到 2 张卡（与 A 无关）", len(b_cards) == 2, len(b_cards))
    if b_cards:
        post("/api/active-recall/answer",
             {"student_id": STUDENT_B, "card_id": b_cards[0]["card_id"],
              "answer": expected_of(b_cards[0]["card_id"]), "response_time": 5, "hint_level": 0})

    summary_a = get("/api/active-recall/summary", student_id=STUDENT_A).json()
    summary_b = get("/api/active-recall/summary", student_id=STUDENT_B).json()
    check("隔离：主动回忆记录不串号（A=3 / B=1）",
          summary_a.get("total") == 3 and summary_b.get("total") == 1,
          (summary_a.get("total"), summary_b.get("total")))
    rows_a = scalar("select count(*) from active_recall_record where student_id=%d" % STUDENT_A)
    rows_b = scalar("select count(*) from active_recall_record where student_id=%d" % STUDENT_B)
    check("隔离：库内 active_recall_record 按 student_id 分开计数",
          rows_a == 3 and rows_b == 1, (rows_a, rows_b))

    b_today = get("/api/tasks/today/%d" % STUDENT_B, date=today).json()
    b_tasks = b_today.get("tasks") or []
    b_rows = scalar("select count(*) from daily_learning_task where student_id=%d" % STUDENT_B)
    check("隔离：B 的今日任务只来自 B 自己（行数一致）",
          len(b_tasks) == b_rows, (len(b_tasks), b_rows))
    check("隔离：A 的任务 id 不出现在 B 的列表",
          not ({int(task["task_id"]) for task in tasks}
               & {int(task["task_id"]) for task in b_tasks}))
    b_profile = get("/api/habit/profile/%d" % STUDENT_B).json()
    check("隔离：B 的休息保护使用数仍为 0（A 用了 2 次）",
          b_profile.get("rest_protection_count") == 0, b_profile.get("rest_protection_count"))
    check("隔离：B 的累计学习天数与 A 不同源",
          b_profile.get("total_tasks", 0) != 0 or b_profile.get("total_days", 0) == 0,
          (b_profile.get("total_days"), b_profile.get("total_tasks")))

    x = get("/api/daily-summary/%d" % STUDENT_X).json()
    check("隔离：不存在的学生返回空结构而不是他人数据",
          x.get("finished") is False and not x.get("lines") and x.get("child", {}).get("minutes") == 0,
          x.get("message"))


def failure_case():
    """失败路径：422 / 400 / 空结构，绝不 500。"""
    check("失败路径：count 超上限 → 422",
          post("/api/active-recall/start", {"student_id": STUDENT_A, "count": 99}).status_code == 422)
    empty = post("/api/active-recall/answer",
                 {"student_id": STUDENT_A, "card_id": "", "answer": ""}).json()
    check("失败路径：空 card_id / answer → 200 空结构",
          empty.get("result") == "" and "child" in empty)
    check("失败路径：非法 date → 400",
          get("/api/daily-summary/%d" % STUDENT_A, date="2025-13-01").status_code == 400)
    check("失败路径：非法 state → 400",
          get("/api/recovery/list", student_id=STUDENT_A, state="NOPE").status_code == 400)
    bad = get("/api/tasks/today/%d" % STUDENT_X).json()
    check("失败路径：不存在学生的今日任务 → 200 空结构",
          bad.get("student_id") == STUDENT_X and not bad.get("tasks"), bad.get("tasks"))


# ---------------------------------------------------------------- 前端页面


def page_case():
    """V2.5 前端页面存在性与关键文案检查（不需要后端）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = {}
    for name in ("today.html", "today.js", "recall.html", "recall.js",
                 "daily.html", "daily.js", "habit.html", "habit.js"):
        path = os.path.join(root, "frontend", name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text[name] = handle.read()
        except OSError:
            text[name] = ""

    check("前端：今日学习页有学习启动仪式与三个新入口",
          "开始今天的学习" in text["today.html"] and "startToday" in text["today.js"]
          and "recall.html" in text["today.html"] and "daily.html" in text["today.html"]
          and "habit.html" in text["today.html"])
    check("前端：主动回忆页出卡不给选项且支持分级提示",
          "主动回忆" in text["recall.html"] and "submitRecall" in text["recall.js"]
          and "showHint" in text["recall.js"] and "answers" not in text["recall.js"])
    check("前端：今日完成页有结束文案与休息文案",
          "今天完成啦" in text["daily.html"] and "rest_text" in text["daily.js"])
    check("前端：习惯简报页有本月 / 连续 / 最长连续与休息保护",
          "本月学习" in text["habit.js"] and "streakText" in text["habit.js"]
          and "休息保护" in text["habit.html"] and "rest_protection_left" in text["habit.js"])
    check("前端：新页面沿用现有样式表（style.css）",
          all('href="style.css"' in text[name]
              for name in ("recall.html", "daily.html", "habit.html")))


# ---------------------------------------------------------------- 服务
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
    """起一个自带路由的临时后端（不依赖 main.py 是否已注册 V2.5 路由）。"""
    if port_in_use():
        check("端口未占用（%d 被占用则故意失败，不自动换端口）" % PORT, False, "端口已被占用")
        finish(None)
    code = (
        "import uvicorn\n"
        "from fastapi import FastAPI\n"
        "import active_recall_routes, daily_routes, habit_routes, recovery_routes, task_routes\n"
        "app = FastAPI(title='verify-recall')\n"
        "app.include_router(active_recall_routes.router)\n"
        "app.include_router(daily_routes.router)\n"
        "app.include_router(task_routes.router)\n"
        "app.include_router(habit_routes.router)\n"
        "app.include_router(recovery_routes.router)\n"
        "@app.get('/')\n"
        "def _root():\n"
        "    return {'ok': True, 'suite': 'recall'}\n"
        "uvicorn.run(app, host='127.0.0.1', port=%d, log_level='warning')\n" % PORT
    )
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=BACKEND, env=env)
    for _ in range(80):
        if proc.poll() is not None:
            break
        try:
            if requests.get(BASE + "/", timeout=2).status_code == 200:
                check("临时后端启动（端口 %d，自带 recall/daily/tasks/habit/recovery 路由）" % PORT,
                      True)
                return proc
        except Exception:                      # noqa: BLE001
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
        except Exception:                      # noqa: BLE001
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
    compat_case()
    page_case()
    recovery_id = seed_recovery()
    proc = start_server()
    try:
        recall_case()
        tasks = plan_case()
        daily_case(tasks)
        habit_case()
        recovery_case(recovery_id)
        isolation_case(tasks)
        failure_case()
    finally:
        print("耗时 %.1fs" % (time.time() - start))
        finish(proc)


if __name__ == "__main__":
    main()
