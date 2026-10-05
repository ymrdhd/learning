# ==============================================================
# 能力契约｜每日习惯套件：任务配比 / 幂等生成 / 完成率 / 连续天数 / 六徽章 / 学生隔离 / V2.4 兼容
# 入口：check / compat_case / split_case / streak_case / badge_case / record_answer_case / start_server / main
# 依赖：os sys json socket sqlite3 subprocess、requests、habit、database、models、planner
# 不负责：修 bug（只记录缺陷）→ Lead；配比与画像算法 → habit.py；其它套件 → verify_all.py
# 验证：python backend/verify_habit.py（端口 8911 · 临时库 _verify_habit.db）
# 被调用：人工 / verify_all.py（套件 key = habit）
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================

"""V2.5 每日学习习惯门禁套件（SPEC §9 · key=habit · port=8911）。

覆盖：50/30/20 配比算术（合计等于 total 且每类 ≥1）/ 同日重复 generate 幂等（行数不变）/
complete_task 后完成率与汇总正确 / 连续天数四规则（昨天 +1、今天不变、更早重置、refresh 归零）/
六个徽章全部触发 / 四个接口的真实 HTTP 断言 / A·B 学生隔离 / 无 learning_plan 时三科降级生成 /
记录作答按 task_id 精确落到对应题型（V2.8 题单模式，同科目同知识点也不串味、旧调用向后兼容）/
V2.4 十九张旧表行数与列结构不变、迁移幂等 / 失败路径（422·400·空结构）。

纪律：临时库 _verify_habit.db（跑完删除）· 绝不写 learning.db · 端口被占用故意失败（不换端口）。
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta

BACKEND = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BACKEND)
DB_PATH = os.path.join(BACKEND, "_verify_habit.db")
BASELINE = os.path.join(ROOT, ".v25_schema_baseline.json")
PORT = int(os.getenv("VERIFY_HABIT_PORT", "8911"))
BASE = "http://127.0.0.1:%d" % PORT
NEW_TABLES = ("wrong_question_recovery", "daily_learning_task", "learning_habit_profile")
STUDENT_A, STUDENT_B, STUDENT_X = 1, 2, 999
STUDENT_STREAK, STUDENT_BADGE = 4, 5
STUDENT_SHEET = 6

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

import habit  # noqa: E402
from adaptive import planner  # noqa: E402
from database import (SessionLocal, engine as db_engine, ensure_schema,  # noqa: E402
                      migrate_data)
from models import (Base, DailyLearningTask, LearningHabitProfile,  # noqa: E402
                    StudentKnowledgeMastery)
from habit import BADGE_KEYS, TYPE_ORDER, next_target_minutes, split_by_mix  # noqa: E402

PASSED = 0
FAILED = 0
TASK_FIELDS = {"task_id", "task_type", "task_type_text", "title", "subject", "knowledge",
               "target_count", "complete_count", "duration_minutes", "target_minutes",
               "status", "status_text", "priority", "goal", "reason"}
PROFILE_FIELDS = {"student_id", "current_streak", "longest_streak", "total_days", "total_tasks",
                  "completed_tasks", "completion_rate", "total_minutes", "today_minutes", "level",
                  "level_text", "badges", "last_active_date", "recent", "target_minutes"}


def check(name, cond, extra=""):
    """记一条断言：打印 PASS/FAIL，并累计计数。"""
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("PASS  " + name + (("  | " + str(extra)) if extra != "" else ""))
    else:
        FAILED += 1
        print("FAIL  " + name + (("  | " + str(extra)) if extra != "" else ""))
    return bool(cond)


def day(offset=0):
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 库快照工具

def q(text):
    con = sqlite3.connect(DB_PATH)
    try:
        result = con.execute(text).fetchall()
        con.commit()          # 允许用 q() 做测试数据准备（INSERT/UPDATE 必须提交）
        return result
    finally:
        con.close()


def table_names():
    return {row[0] for row in q("select name from sqlite_master where type='table'")}


def row_counts(names):
    return {name: q('select count(*) from "%s"' % name)[0][0] for name in names}


def columns_of(names):
    return {name: {row[1]: str(row[2] or "").upper()
                   for row in q('PRAGMA table_info("%s")' % name)} for name in names}


def count_tasks(sid, date_text):
    return q("select count(*) from daily_learning_task where student_id=%d and date='%s'"
             % (sid, date_text))[0][0]


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
                    (STUDENT_A, "学生A", "boy", 1, now))
        con.execute("INSERT INTO students (id,name,avatar,grade,created_at) VALUES (?,?,?,?,?)",
                    (STUDENT_B, "学生B", "girl", 2, now))
        for knowledge, score in (("两位数乘法", 40), ("三位数乘法", 80)):
            con.execute(
                "INSERT INTO student_knowledge_mastery (student_id,subject,knowledge_id,stage,"
                "mastery_score,questions,correct,difficulty_sum,updated_time)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (STUDENT_A, "数学", knowledge, "1.1", score, 10, 6, 20.0, now))
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
    """V2.4 数据兼容：19 张旧表 + 样例数据 → create_all / ensure_schema / migrate_data 不破坏。"""
    baseline = build_v24_db()
    names = list(baseline)
    rows_before = row_counts(names)
    cols_before = columns_of(names)
    check("V2.4 兼容：先建 19 张旧表并塞入样例数据",
          len(names) == 19 and rows_before["students"] == 2
          and rows_before["student_knowledge_mastery"] == 2
          and rows_before["learning_plan"] == 1,
          "tables=%d students=%d" % (len(names), rows_before["students"]))

    Base.metadata.create_all(db_engine)
    ensure_schema(Base)
    first = migrate_data()
    rows_after = row_counts(names)
    cols_after = columns_of(names)

    check("V2.4 兼容：create_all + ensure_schema + migrate_data 后 19 张旧表行数全不变",
          rows_after == rows_before,
          [k for k in rows_before if rows_before[k] != rows_after[k]] or "全部一致")
    lost = [k for k in cols_before if not set(cols_before[k]) <= set(cols_after[k])]
    retyped = [k for k in cols_before if k not in lost
               and any(cols_before[k][c] != cols_after[k][c] for c in cols_before[k])]
    check("V2.4 兼容：旧表列没被删除 / 改名 / 改类型（只允许新增列）",
          not lost and not retyped, "lost=%s retyped=%s" % (lost, retyped))
    check("V2.4 兼容：3 张 V2.5 新表由 create_all 建出",
          set(NEW_TABLES) <= table_names(), sorted(set(NEW_TABLES) & table_names()))
    mastery = q("select total_questions,correct_questions,wrong_questions,confidence,"
                "last_practice_time is not null from student_knowledge_mastery where student_id=1"
                " order by knowledge_id")
    check("V2.4 兼容：迁移把 questions/correct 回填成 total/correct/wrong",
          len(mastery) == 2 and all(tuple(row) == (10, 6, 4, 0.57, 1) for row in mastery), mastery)
    check("V2.4 兼容：首次迁移确有改动（非空跑）", sum(first) > 0, first)
    second = migrate_data()
    check("V2.4 兼容：二次迁移幂等（无行被改动）", sum(second) == 0, second)
    check("V2.4 兼容：二次迁移后行数 / 列结构仍不变",
          row_counts(names) == rows_before and columns_of(names) == cols_after)


# ---------------------------------------------------------------- 数据工具

def seed_task(sid, date_text, task_type="new_learning", subject="数学", status="done",
              minutes=5, count=1, target=1, knowledge="两位数乘法"):
    """直接落一行任务（用于构造历史 / 连续天数 / 徽章场景）。"""
    db = SessionLocal()
    try:
        row = DailyLearningTask(
            student_id=sid, date=date_text, task_type=task_type, title="seed",
            subject=subject, knowledge_id=knowledge, target_count=target, complete_count=count,
            duration_minutes=minutes, target_minutes=10, status=status, priority=1,
            source="verify", created_time=datetime.now(), updated_time=datetime.now())
        if status == "done":
            row.completed_time = datetime.now()
        db.add(row)
        db.commit()
        return int(row.id or 0)
    finally:
        db.close()


def refresh(sid, date_text=None):
    """调引擎重算并落库画像（返回画像 dict）。"""
    db = SessionLocal()
    try:
        return habit.DEFAULT_ENGINE.refresh(db, sid, date=date_text)
    finally:
        db.close()


def profile_row(sid):
    db = SessionLocal()
    try:
        row = db.query(LearningHabitProfile).filter(
            LearningHabitProfile.student_id == sid).first()
        if row is None:
            return None
        return {"current_streak": int(row.current_streak or 0),
                "longest_streak": int(row.longest_streak or 0),
                "last_active_date": row.last_active_date or "",
                "badges": json.loads(row.badges or "[]")}
    finally:
        db.close()


def set_profile_row(sid, *, streak=0, last_active=""):
    db = SessionLocal()
    try:
        row = db.query(LearningHabitProfile).filter(
            LearningHabitProfile.student_id == sid).first()
        if row is None:
            row = LearningHabitProfile(student_id=sid, created_time=datetime.now())
            db.add(row)
        row.current_streak, row.last_active_date = int(streak), last_active
        db.commit()
    finally:
        db.close()


def get(path, **params):
    return requests.get(BASE + path, params=params, timeout=30)


def post(path, payload):
    return requests.post(BASE + path, json=payload, timeout=60)


def today_tasks(sid, date_text=""):
    return get("/api/tasks/today", student_id=sid, date=date_text).json()


def task_rows(sid, date_text):
    return q("select id,task_type,subject,target_count,complete_count,status,duration_minutes"
             " from daily_learning_task where student_id=%d and date='%s'"
             " order by priority asc, id asc" % (sid, date_text))


# ---------------------------------------------------------------- 用例

def mix_case():
    body = today_tasks(STUDENT_A)
    tasks = body.get("tasks") or []
    check("today：HTTP 200 且首次访问即生成（generated=true）",
          body.get("student_id") == STUDENT_A and body.get("date") == day()
          and body.get("generated") is True and len(tasks) == 9, len(tasks))
    check("today：任务字段齐全（SPEC §7.2）",
          bool(tasks) and TASK_FIELDS <= set(tasks[0]),
          sorted(TASK_FIELDS - set(tasks[0])) or "齐全")
    check("today：三科 × 三段 = 9 条（每科 3 条、每段 3 条）",
          {t["subject"] for t in tasks} == {"数学", "语文", "英语"}
          and all(sum(1 for t in tasks if t["subject"] == s) == 3 for s in ("数学", "语文", "英语"))
          and all(sum(1 for t in tasks if t["task_type"] == k) == 3 for k in TYPE_ORDER))
    check("today：prompt 优先级 1..9 且不重复",
          sorted(t["priority"] for t in tasks) == list(range(1, 10)))
    check("today：标题为「学科 · 阶段文案」且 knowledge 非空",
          all(" · " in t["title"] and t["knowledge"] for t in tasks))
    check("today：summary.mix_tasks 每段各 3 条",
          body["summary"]["mix_tasks"] == {k: 3 for k in TYPE_ORDER}, body["summary"]["mix_tasks"])
    check("today：summary.total = 9 且 mix 合计 = 全部 target_count 之和",
          body["summary"]["total"] == 9
          and sum(body["summary"]["mix"].values()) == sum(t["target_count"] for t in tasks))

    for subject in ("数学", "语文", "英语"):
        counts = {k: sum(t["target_count"] for t in tasks
                         if t["subject"] == subject and t["task_type"] == k) for k in TYPE_ORDER}
        check("%s：50/30/20 配比算术（合计 = total 且每类 ≥1）" % subject,
              sum(counts.values()) >= 3 and min(counts.values()) >= 1
              and counts == split_by_mix(sum(counts.values())), counts)

    check("knowledge：new_learning(数学) 取当天 learning_plan 的知识点与理由",
          all(t["knowledge"] == "两位数乘法" and "来自今日学习计划" in t["reason"]
              for t in tasks if t["subject"] == "数学" and t["task_type"] == "new_learning"))
    check("knowledge：weakness 取掌握度最低、review 取掌握度最高（40 / 80）",
          [t["knowledge"] for t in tasks if t["subject"] == "数学"
           and t["task_type"] == "weakness"] == ["两位数乘法"]
          and [t["knowledge"] for t in tasks if t["subject"] == "数学"
               and t["task_type"] == "review"] == ["三位数乘法"])


def split_case():
    check("split_by_mix(10) = 5/3/2", split_by_mix(10) == {"new_learning": 5, "weakness": 3,
                                                           "review": 2}, split_by_mix(10))
    check("split_by_mix(3) 每类 ≥1 且合计 3",
          split_by_mix(3) == {"new_learning": 1, "weakness": 1, "review": 1}, split_by_mix(3))
    bad = []
    for total in range(1, 61):
        counts = split_by_mix(total)
        want = max(3, total)
        if sum(counts.values()) != want or min(counts.values()) < 1:
            bad.append((total, counts))
        if set(counts) != set(TYPE_ORDER):
            bad.append((total, "keys"))
    check("split_by_mix：total 1..60 合计恒等于 max(3,total) 且每类 ≥1", not bad, bad[:3])
    check("split_by_mix：new_learning 恒为最大类",
          all(split_by_mix(t)["new_learning"] == max(split_by_mix(t).values())
              for t in range(3, 61)))
    # V2.6 目标时长自适应（纯函数）
    check("目标时长：首次 10 分钟起步（10 → 12）",
          next_target_minutes(0, signed_in=True, streak=1) == 12,
          next_target_minutes(0, signed_in=True, streak=1))
    check("目标时长：单次签到 +2~5 分钟（连续越久加得越多）",
          next_target_minutes(10, signed_in=True, streak=9) == 15
          and next_target_minutes(20, signed_in=True, streak=3) == 23,
          (next_target_minutes(10, signed_in=True, streak=9),
           next_target_minutes(20, signed_in=True, streak=3)))
    check("目标时长：最长 40 分钟", next_target_minutes(38, signed_in=True, streak=9) == 40,
          next_target_minutes(38, signed_in=True, streak=9))
    check("目标时长：漏签一次 −5~8 分钟",
          next_target_minutes(20, signed_in=False, missed_days=1) == 15
          and next_target_minutes(20, signed_in=False, missed_days=4) == 12,
          (next_target_minutes(20, signed_in=False, missed_days=1),
           next_target_minutes(20, signed_in=False, missed_days=4)))
    check("目标时长：最低 10 分钟（漏签也不会低于 10）",
          next_target_minutes(12, signed_in=False, missed_days=9) == 10
          and next_target_minutes(10, signed_in=False, missed_days=1) == 10,
          (next_target_minutes(12, signed_in=False, missed_days=9),
           next_target_minutes(10, signed_in=False, missed_days=1)))


def target_case():
    """V2.6 目标时长自适应：首次 10 分钟；签到 +2~5（≤40）；漏签 −5~8（≥10）。"""
    sid = 7
    q("insert into students (id, name, avatar, grade) values (%d, '时长测试', 'boy', 3)" % sid)
    first = get("/api/habit/profile", student_id=sid).json()
    check("目标时长：首次学习 = 10 分钟", int(first.get("target_minutes") or 0) == 10,
          first.get("target_minutes"))
    tasks = today_tasks(sid).get("tasks") or []
    check("目标时长：新学生今日任务已生成", len(tasks) >= 9, len(tasks))
    if tasks:
        done = post("/api/tasks/complete",
                    {"student_id": sid, "task_id": tasks[0].get("task_id"),
                     "done": True}).json()
        done_profile = done.get("profile") or {}
        check("目标时长：完成任务后画像能看到上调过头寸",
              int(done_profile.get("target_minutes") or 0) >= 10,
              (done.get("status"), done_profile.get("current_streak"),
               done_profile.get("target_minutes")))
    after = get("/api/habit/profile", student_id=sid).json()
    value = int(after.get("target_minutes") or 0)
    check("目标时长：签到后 +2~5 分钟（12~15）", 12 <= value <= 15, value)

    again = get("/api/habit/profile", student_id=sid).json()
    check("目标时长：同一天重复查看不会重复加",
          int(again.get("target_minutes") or 0) == value, again.get("target_minutes"))

    q("update learning_habit_profile set last_active_date='%s', target_synced_date='' "
      "where student_id=%d" % (day(-3), sid))
    get("/api/tasks/plan/%d" % sid)      # 打开今日计划时结算漏签（_sync_target）
    missed = get("/api/habit/profile", student_id=sid).json()
    check("目标时长：漏签后下调且不低于 10 分钟",
          10 <= int(missed.get("target_minutes") or 0) < value, missed.get("target_minutes"))


def idempotent_case():
    before = count_tasks(STUDENT_A, day())
    ids_before = [row[0] for row in task_rows(STUDENT_A, day())]
    body = today_tasks(STUDENT_A)
    check("today：同一天重复访问幂等（generated=false、行数不变、task_id 不变）",
          body.get("generated") is False and count_tasks(STUDENT_A, day()) == before
          and [t["task_id"] for t in body["tasks"]] == ids_before, before)
    db = SessionLocal()
    try:
        first = [int(r.id or 0) for r in habit.DEFAULT_ENGINE.generate_daily_tasks(db, STUDENT_A)]
        second = [int(r.id or 0) for r in habit.DEFAULT_ENGINE.generate_daily_tasks(db, STUDENT_A)]
    finally:
        db.close()
    check("generate_daily_tasks：直接调用两次返回同一批行（不新增）",
          first == second and len(first) == 9 and count_tasks(STUDENT_A, day()) == before)
    y = day(-1)
    body = today_tasks(STUDENT_B, y)
    check("today：换日期生成的是那一天自己的任务（行按 date 分开）",
          body.get("date") == y and len(body.get("tasks") or []) == 9
          and count_tasks(STUDENT_B, y) == 9, body.get("date"))
    body = today_tasks(STUDENT_B)
    check("today：同一学生不同日期互不覆盖（9 + 9 = 18 行）",
          len(body.get("tasks") or []) == 9 and count_tasks(STUDENT_B, day()) == 9
          and count_tasks(STUDENT_B, y) == 9)


def complete_case():
    rows = task_rows(STUDENT_A, day())
    task_id, target_count = rows[0][0], rows[0][3]
    body = post("/api/tasks/complete",
                {"student_id": STUDENT_A, "task_id": task_id, "minutes": 12}).json()
    check("complete：任务置为 done 且 complete_count 补满 target_count",
          body.get("status") == "done" and body.get("status_text") == "已完成"
          and body.get("complete_count") == target_count, body.get("status"))
    check("complete：返回当日汇总（done=1、minutes=12、完成率 = 1/9）",
          body["summary"]["done"] == 1 and body["summary"]["minutes"] == 12
          and abs(body["summary"]["completion_rate"] - round(1 / 9.0, 4)) < 1e-9,
          body["summary"])
    check("complete：返回习惯画像（streak=1、today_minutes=12、首日徽章）",
          body["profile"]["current_streak"] == 1 and body["profile"]["today_minutes"] == 12
          and body["profile"]["total_minutes"] == 12
          and any(b["key"] == "first_day" and b["got"] for b in body["profile"]["badges"]))

    big = next((row for row in rows if row[3] > 1 and row[0] != task_id), None)
    check("complete：存在 target_count>1 的任务可做部分完成", big is not None)
    if big:
        body = post("/api/tasks/complete",
                    {"student_id": STUDENT_A, "task_id": big[0], "count": 1,
                     "done": False}).json()
        check("complete：部分完成 → status=doing 且 complete_count=1",
              body.get("status") == "doing" and body.get("complete_count") == 1, body.get("status"))
        body = post("/api/tasks/complete", {"student_id": STUDENT_A, "task_id": big[0]}).json()
        check("complete：再报完成 → done 且 complete_count=target_count",
              body.get("status") == "done" and body.get("complete_count") == big[3])
    check("complete：重复上报同一任务不再改变汇总（done 仍为 2、完成率 = 2/9）",
          abs(post("/api/tasks/complete", {"student_id": STUDENT_A,
                                           "task_id": task_id}).json()
              ["summary"]["completion_rate"] - round(2 / 9.0, 4)) < 1e-9)
    check("complete：落库状态与接口一致（2 条 done）",
          sum(1 for row in task_rows(STUDENT_A, day()) if row[5] == "done") == 2)


def record_answer_case():
    """V2.8 题单模式：一次作答按 task_id 精确记到那一项头上（同科目同知识点也不串味）。"""
    text = day()
    db = SessionLocal()
    try:
        engine = habit.DEFAULT_ENGINE
        engine.generate_daily_tasks(db, STUDENT_SHEET, date=text, force=True)
        rows = (db.query(DailyLearningTask)
                .filter(DailyLearningTask.student_id == STUDENT_SHEET,
                        DailyLearningTask.date == text)
                .order_by(DailyLearningTask.id).all())
        check("题单记分：备好同科目同知识点的两项任务（数学 · 新知识 / 数学 · 薄弱训练）",
              len(rows) >= 2, len(rows))
        first, second = rows[0], rows[1]
        first.subject = second.subject = "数学"
        first.knowledge_id = second.knowledge_id = "20以内加减法"
        first.target_count, first.complete_count, first.status = 5, 3, "doing"
        second.target_count, second.complete_count, second.status = 4, 0, "pending"
        db.commit()

        result = engine.record_answer(db, STUDENT_SHEET, subject="数学",
                                      knowledge="20以内加减法", correct=True,
                                      task_id=first.id)
        db.refresh(first)
        db.refresh(second)
        check("题单记分：带 task_id 的作答只加在那一项上（3/5 → 4/5）",
              result.get("task_id") == first.id and first.complete_count == 4
              and second.complete_count == 0,
              (result.get("task_id"), first.complete_count, second.complete_count))
        check("题单记分：没做满 target_count 时这一项仍是 doing（不提前收工）",
              first.status == "doing" and result.get("status") == "doing",
              (first.status, result.get("status")))

        result = engine.record_answer(db, STUDENT_SHEET, subject="数学",
                                      knowledge="20以内加减法", correct=True,
                                      task_id=first.id)
        db.refresh(first)
        check("题单记分：第 5 题做完这一项收工（5/5 → done）",
              first.complete_count == 5 and first.status == "done"
              and result.get("status") == "done",
              (first.complete_count, first.status))

        result = engine.record_answer(db, STUDENT_SHEET, subject="数学",
                                      knowledge="20以内加减法", correct=True)
        db.refresh(first)
        db.refresh(second)
        check("题单记分：不带 task_id 的老调用仍能按科目+知识点记分（向后兼容）",
              result.get("matched") is True and second.complete_count == 1
              and first.complete_count == 5,
              (result.get("matched"), first.complete_count, second.complete_count))
    finally:
        db.close()

def streak_case():
    refresh(STUDENT_STREAK, day(-1))
    set_profile_row(STUDENT_STREAK, streak=4, last_active=day(-1))
    seed_task(STUDENT_STREAK, day(-1), status="done", minutes=5)
    seed_task(STUDENT_STREAK, day(), status="done", minutes=5)
    data = refresh(STUDENT_STREAK, day())
    check("连续天数：昨天活跃 + 今天活跃 → 昨天 +1（4 → 5）",
          data["current_streak"] == 5 and data["last_active_date"] == day(),
          data["current_streak"])
    again = refresh(STUDENT_STREAK, day())
    check("连续天数：今天重复刷新不再 +1（今天不变）",
          again["current_streak"] == 5 and again["longest_streak"] == 5)

    set_profile_row(STUDENT_STREAK, streak=4, last_active=day(-3))
    db = SessionLocal()
    try:
        row = db.query(DailyLearningTask).filter(
            DailyLearningTask.student_id == STUDENT_STREAK,
            DailyLearningTask.date == day()).first()
        row.status, row.complete_count, row.duration_minutes = "pending", 0, 0
        db.commit()
    finally:
        db.close()
    data = refresh(STUDENT_STREAK, day())
    check("连续天数：最后活跃早于昨天且今天无活动 → 重置为 0",
          data["current_streak"] == 0, data["current_streak"])
    stored = profile_row(STUDENT_STREAK)
    check("连续天数：refresh 已把归零结果落库",
          stored is not None and stored["current_streak"] == 0, stored)
    check("连续天数：longest_streak 只增不减（保留历史最长 5）",
          stored["longest_streak"] == 5, stored["longest_streak"])


def badge_case():
    for offset in range(30, 0, -1):
        date_text = day(-offset)
        seed_task(STUDENT_BADGE, date_text, status="done", minutes=5)
        refresh(STUDENT_BADGE, date_text)
    data = refresh(STUDENT_BADGE, day())
    stored = profile_row(STUDENT_BADGE)
    gotten = sorted(key for key in (stored["badges"] if stored else []) if key in BADGE_KEYS)
    check("徽章：连续 30 天后六个徽章全部触发",
          gotten == sorted(BADGE_KEYS), gotten)
    check("徽章：累计天数 30 / 最长连续 30 / 完成率 1.0",
          data["total_days"] == 30 and data["longest_streak"] == 30
          and data["current_streak"] == 30 and data["completion_rate"] == 1.0,
          (data["total_days"], data["longest_streak"], data["current_streak"]))
    check("徽章：总时长 150 分钟（30 × 5）触发 minutes_100",
          data["total_minutes"] == 150, data["total_minutes"])
    check("徽章：等级 = 1 + min(6, streak//3) + rate_80 = 8",
          data["level"] == 8 and data["level_text"], data["level"])
    body = get("/api/habit/profile", student_id=STUDENT_BADGE).json()
    check("徽章：接口返回 6 个徽章且 got 全为真",
          len(body["badges"]) == 6 and all(b["got"] for b in body["badges"]),
          [b["key"] for b in body["badges"]])


def isolation_case():
    a_ids = {t["task_id"] for t in today_tasks(STUDENT_A)["tasks"]}
    body = today_tasks(STUDENT_B)
    b_ids = {t["task_id"] for t in body["tasks"]}
    check("隔离：B 的今日任务与 A 完全不重叠（task_id 交集为空）",
          bool(b_ids) and not (a_ids & b_ids), (len(a_ids), len(b_ids)))
    check("隔离：B 的 summary/profile 只统计自己",
          body["summary"]["total"] == 9
          and get("/api/habit/profile", student_id=STUDENT_B).json()["student_id"] == STUDENT_B)
    leaked = [key for key in ("来自今日学习计划", "三位数乘法") if key in json.dumps(
        body, ensure_ascii=False)]
    check("隔离：B 的响应体不出现 A 的计划 / 知识点", not leaked, leaked)

    victims = task_rows(STUDENT_A, day())
    target = next(row for row in victims if row[5] == "done")
    body = post("/api/tasks/complete",
                {"student_id": STUDENT_B, "task_id": target[0], "minutes": 30}).json()
    check("隔离：B 完成 A 的任务 → 空结构（status 空、count 0、不泄露）",
          body.get("status") == "" and body.get("complete_count") == 0
          and body.get("profile", {}).get("student_id") == STUDENT_B, body.get("status"))
    after = next(row for row in task_rows(STUDENT_A, day()) if row[0] == target[0])
    check("隔离：A 的任务未被 B 改动（complete_count / minutes 不变）",
          after[4] == target[4] and after[6] == target[6], (after[4], target[4]))
    check("隔离：B 未因此新增任何任务行或时长",
          count_tasks(STUDENT_B, day()) == 9
          and get("/api/habit/profile", student_id=STUDENT_B).json()["total_minutes"] == 0)
    empty = get("/api/habit/profile", student_id=STUDENT_X).json()
    check("隔离：未知 student_id 画像 → 200 空结构（全 0 + 徽章未获得，不是 404/500）",
          empty["current_streak"] == 0 and empty["longest_streak"] == 0
          and empty["total_tasks"] == 0 and empty["level"] == 1
          and all(not b["got"] for b in empty["badges"])
          and len(empty["recent"]) == 7
          and all(item["total"] == 0 and item["minutes"] == 0 for item in empty["recent"]))
    check("隔离：未知 student_id 的 stats → 200 全 0 序列",
          get("/api/habit/stats", student_id=STUDENT_X).json()["total_minutes"] == 0
          and len(get("/api/habit/stats", student_id=STUDENT_X).json()["items"]) == 7)


def degraded_case():
    body = today_tasks(STUDENT_B)
    tasks = body.get("tasks") or []
    check("降级：B 无 learning_plan / 无掌握度画像时仍生成 9 条任务",
          len(tasks) == 9, len(tasks))
    check("降级：三科都能出题（数学 / 语文 / 英语 各 3 条）",
          {t["subject"] for t in tasks} == {"数学", "语文", "英语"}
          and all(sum(1 for t in tasks if t["subject"] == s) == 3 for s in ("数学", "语文", "英语")))
    check("降级：三段配比仍然满足合计 = total 且每类 ≥1",
          all(t["target_count"] >= 1 for t in tasks)
          and sum(body["summary"]["mix"].values())
          == sum(t["target_count"] for t in tasks))
    check("降级：知识点回退到知识点体系（非空，不报错）",
          all(t["knowledge"] for t in tasks))


def failure_case():
    check("失败路径：/api/tasks/today 缺 student_id → 422",
          get("/api/tasks/today").status_code == 422)
    check("失败路径：/api/tasks/today student_id=0 → 422",
          get("/api/tasks/today", student_id=0).status_code == 422)
    check("失败路径：/api/tasks/today date=13/01/2025 → 400",
          get("/api/tasks/today", student_id=STUDENT_A, date="13/01/2025").status_code == 400)
    check("失败路径：/api/tasks/today date=2025-13-01 → 400",
          get("/api/tasks/today", student_id=STUDENT_A, date="2025-13-01").status_code == 400)
    check("失败路径：/api/tasks/complete task_id=0 → 200 空结构（不是 404/500）",
          post("/api/tasks/complete", {"student_id": STUDENT_A, "task_id": 0}).json()
          .get("status") == "")
    check("失败路径：/api/tasks/complete 不存在 / 不属于自己的 task_id → 200 空结构",
          post("/api/tasks/complete", {"student_id": STUDENT_A,
                                       "task_id": 999999}).json().get("status") == "")
    check("失败路径：/api/habit/profile 缺 student_id → 422",
          get("/api/habit/profile").status_code == 422)
    check("失败路径：/api/habit/profile date 非法 → 400",
          get("/api/habit/profile", student_id=STUDENT_A, date="2025-02-30").status_code == 400)
    check("失败路径：/api/habit/stats days=0 → 422（边界）",
          get("/api/habit/stats", student_id=STUDENT_A, days=0).status_code == 422)
    check("失败路径：/api/habit/stats days=91 → 422（边界）",
          get("/api/habit/stats", student_id=STUDENT_A, days=91).status_code == 422)


def stats_case():
    body = get("/api/habit/stats", student_id=STUDENT_A, days=7).json()
    check("stats：HTTP 200 且返回 7 天序列（含今天）",
          body["student_id"] == STUDENT_A and body["days"] == 7 and len(body["items"]) == 7
          and body["items"][-1]["date"] == day(), body["items"][-1]["date"])
    check("stats：序列字段齐全且 total_minutes = 各天之和",
          {"date", "done", "total", "minutes", "rate"} <= set(body["items"][0])
          and body["total_minutes"] == sum(item["minutes"] for item in body["items"]))
    check("stats：avg_rate = 7 天完成率均值（4 位小数）",
          abs(body["avg_rate"] - round(sum(item["rate"] for item in body["items"]) / 7.0, 4))
          < 1e-9, body["avg_rate"])
    check("stats：今天的 done/rate 与 /api/tasks/today 汇总一致",
          body["items"][-1]["done"] == today_tasks(STUDENT_A)["summary"]["done"]
          and abs(body["items"][-1]["rate"]
                  - today_tasks(STUDENT_A)["summary"]["completion_rate"]) < 1e-9)
    check("stats：days=3 → 只返回 3 天",
          len(get("/api/habit/stats", student_id=STUDENT_A, days=3).json()["items"]) == 3)

    body = get("/api/habit/profile", student_id=STUDENT_A).json()
    check("profile：字段齐全（画像 14 项）", PROFILE_FIELDS <= set(body),
          sorted(PROFILE_FIELDS - set(body)) or "齐全")
    check("profile：完成 2/9 时 completion_rate = 0.2222、completed_tasks = 2",
          body["completed_tasks"] == 2 and body["total_tasks"] == 9
          and abs(body["completion_rate"] - 0.2222) < 1e-9,
          (body["completed_tasks"], body["total_tasks"], body["completion_rate"]))
    check("profile：今日时长 = 12、累计时长 = 12（B 的 30 分钟没有串进来）",
          body["today_minutes"] == 12 and body["total_minutes"] == 12,
          (body["today_minutes"], body["total_minutes"]))
    check("profile：recent 为近 7 天曲线且末位是今天",
          len(body["recent"]) == 7 and body["recent"][-1]["date"] == day())
    check("profile：6 个徽章 + first_day 已获得",
          len(body["badges"]) == 6
          and [b["key"] for b in body["badges"] if b["got"]] == ["first_day"],
          [b["key"] for b in body["badges"] if b["got"]])


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
    """起一个自带路由的临时后端（不依赖 main.py 是否已注册 V2.5 路由）。"""
    if port_in_use():
        check("端口未占用（%d 被占用则故意失败，不自动换端口）" % PORT, False, "端口已被占用")
        finish(None)
    code = (
        "import uvicorn\n"
        "from fastapi import FastAPI\n"
        "import habit_routes, task_routes\n"
        "app = FastAPI(title='verify-habit')\n"
        "app.include_router(task_routes.router)\n"
        "app.include_router(habit_routes.router)\n"
        "@app.get('/')\n"
        "def _root():\n"
        "    return {'ok': True, 'suite': 'habit'}\n"
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
                check("临时后端启动（端口 %d，自带 tasks/habit 路由）" % PORT, True)
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
    compat_case()
    proc = start_server()
    try:
        mix_case()
        split_case()
        target_case()
        idempotent_case()
        complete_case()
        record_answer_case()
        streak_case()
        badge_case()
        isolation_case()
        degraded_case()
        failure_case()
        stats_case()
    finally:
        print("耗时 %.1fs" % (time.time() - start))
        finish(proc)


if __name__ == "__main__":
    main()
