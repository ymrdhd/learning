# ==============================================================
# 能力契约｜错题康复套件：六态流转 / 连对晋级 / 回炉 / 提示分级 / 变式题 / 学生隔离 / V2.4 兼容
# 入口：check / compat_case / start_server / main
# 依赖：os sys json socket sqlite3 subprocess、requests、recovery.engine、recovery.state、ai_recovery、database、models、validator
# 不负责：修 bug（只记录缺陷）→ Lead；状态机与提示实现 → recovery/ 三模块与 ai_recovery.py；其它套件 → verify_all.py
# 验证：python backend/verify_recovery.py（端口 8910 · 临时库 _verify_recovery.db）
# 被调用：人工 / verify_all.py（套件 key = recovery）
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复门禁套件（SPEC §9 · key=recovery · port=8910）。

覆盖：六态可达 / PRACTICING 连对 2 次晋级 VERIFYING（next_verify_time ≈ +1 天）/
PRACTICING 答错计数（fail_count 递增、连对清零、偶数回 NEW）/ VERIFYING 对 → MASTERED、
错 → PRACTICING / 教学态与任意态答错原题 → NEW 且记 state_before / 四级提示逐级且 L1·L3 不泄答案、
L4 含答案 / 变式题 validation.passed / AI 离线降级 / 五个接口的真实 HTTP 断言 / A·B 学生隔离 /
未知 student_id 空结构 / V2.4 十九张旧表行数与列结构不变、迁移幂等。

纪律：临时库 _verify_recovery.db（跑完删除）· 绝不写 learning.db · 端口被占用故意失败（不换端口）。
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
DB_PATH = os.path.join(BACKEND, "_verify_recovery.db")
BASELINE = os.path.join(ROOT, ".v25_schema_baseline.json")
PORT = int(os.getenv("VERIFY_RECOVERY_PORT", "8910"))
BASE = "http://127.0.0.1:%d" % PORT
NEW_TABLES = ("wrong_question_recovery", "daily_learning_task", "learning_habit_profile")
STUDENT_A, STUDENT_B, STUDENT_X = 1, 2, 999

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

import ai_recovery  # noqa: E402
import validator  # noqa: E402
from database import SessionLocal, engine as db_engine, ensure_schema, migrate_data  # noqa: E402
from models import Base, Question, WrongQuestionRecovery  # noqa: E402
from recovery import engine as recovery_engine  # noqa: E402
from recovery.state import next_action, state_text, transition  # noqa: E402

PASSED = 0
FAILED = 0
OBSERVED = set()

# V2.4 样例数据：题库（选择题，options 为 {字母: 选项内容} 的 JSON）
SEED_QUESTIONS = (
    (1, "12 × 12 = ？", {"A": "124", "B": "144", "C": "134", "D": "154"}, "B", 2,
     "把 12 拆成 10 和 2 分别去乘，再加起来。"),
    (2, "11 × 11 = ？", {"A": "121", "B": "111", "C": "131", "D": "112"}, "A", 2,
     "11 × 11 就是 11 个 11 相加。"),
    (3, "13 × 13 = ？", {"A": "159", "B": "169", "C": "139", "D": "179"}, "B", 3,
     "13 × 13 = 13 × 10 + 13 × 3。"),
    (4, "14 × 12 = ？", {"A": "158", "B": "168", "C": "178", "D": "148"}, "B", 3,
     "14 × 12 = 14 × 10 + 14 × 2。"),
    (5, "15 × 15 = ？", {"A": "215", "B": "245", "C": "225", "D": "235"}, "C", 3,
     "15 × 15 = 15 × 10 + 15 × 5。"),
    (6, "16 × 12 = ？", {"A": "182", "B": "192", "C": "202", "D": "172"}, "B", 4,
     "16 × 12 = 16 × 10 + 16 × 2。"),
    (7, "21 × 21 = ？", {"A": "441", "B": "421", "C": "451", "D": "431"}, "A", 4,
     "21 × 21 = 21 × 20 + 21。"),
    (8, "18 × 12 = ？", {"A": "206", "B": "216", "C": "226", "D": "196"}, "B", 4,
     "18 × 12 = 18 × 10 + 18 × 2。"),
)
SPEC_ITEM_KEYS = {"recovery_id", "question_id", "subject", "knowledge", "state", "state_text",
                  "wrong_count", "attempts", "consecutive_correct", "fail_count", "max_level_used",
                  "question", "correct_answer", "analysis", "error_type", "next_verify_time",
                  "created_time"}
VAR_SOURCES = ("rule", "ai", "existing")


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


def saw(state):
    """记录观察到的康复状态（用于「六态可达」汇总断言）。"""
    OBSERVED.add(str(state or "").upper())


# ---------------------------------------------------------------- 库快照工具

def q(text):
    """执行一条只读 SQL 并返回全部行。"""
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


# ---------------------------------------------------------------- V2.4 兼容

def build_v24_db():
    """按 .v25_schema_baseline.json 建 19 张 V2.4 表并塞样例数据，返回基线定义。"""
    with open(BASELINE, "r", encoding="utf-8") as handle:
        baseline = json.load(handle)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    try:
        for name, cols in baseline.items():
            parts = []
            for col, typ in cols.items():
                if col == "__rows":
                    continue
                # id 在 SQLite 里是 INTEGER PRIMARY KEY AUTOINCREMENT（行号别名），
                # 基线 JSON 只存类型，这里按真实 V2.4 结构还原，否则新插入行拿不到自增主键。
                parts.append('"%s" INTEGER PRIMARY KEY AUTOINCREMENT' % col if col == "id"
                             else '"%s" %s' % (col, typ))
            con.execute('CREATE TABLE "%s" (%s)' % (name, ", ".join(parts)))
        con.execute("INSERT INTO students (id,name,avatar,grade,created_at) VALUES (?,?,?,?,?)",
                    (STUDENT_A, "学生A", "boy", 1, now))
        con.execute("INSERT INTO students (id,name,avatar,grade,created_at) VALUES (?,?,?,?,?)",
                    (STUDENT_B, "学生B", "girl", 2, now))
        for qid, question, options, answer, level, analysis in SEED_QUESTIONS:
            con.execute(
                "INSERT INTO questions (id,subject,grade,knowledge,difficulty,question,answer,"
                "qtype,options,acceptable,analysis) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (qid, "数学", 3, "两位数乘法", level, question, answer, "choice",
                 json.dumps(options, ensure_ascii=False), "[]", analysis))
        for sid, qid in ((STUDENT_A, 1), (STUDENT_A, 2), (STUDENT_A, 3), (STUDENT_B, 7)):
            con.execute(
                "INSERT INTO wrong_questions (student_id,subject,knowledge_id,question_id,stage,"
                "status,wrong_count,correct_streak,last_error_type,first_wrong_time,last_wrong_time,"
                "created_time,updated_time) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, "数学", "两位数乘法", qid, "1.1", "NEW", 1, 0, "计算错误", now, now, now, now))
        for sid in (STUDENT_A, STUDENT_B):
            con.execute(
                "INSERT INTO student_knowledge_mastery (student_id,subject,knowledge_id,stage,"
                "mastery_score,questions,correct,difficulty_sum,updated_time)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, "数学", "两位数乘法", "1.1", 40, 10, 6, 20.0, now))
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
          and rows_before["questions"] == len(SEED_QUESTIONS)
          and rows_before["wrong_questions"] == 4 and rows_before["student_knowledge_mastery"] == 2,
          "tables=%d students=%d questions=%d" % (len(names), rows_before["students"],
                                                  rows_before["questions"]))

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
                "last_practice_time is not null from student_knowledge_mastery where student_id=1")
    check("V2.4 兼容：迁移把 questions/correct 回填成 total/correct/wrong",
          mastery and tuple(mastery[0]) == (10, 6, 4, 0.57, 1), mastery)
    check("V2.4 兼容：首次迁移确有改动（非空跑）", sum(first) > 0, first)
    second = migrate_data()
    check("V2.4 兼容：二次迁移幂等（无行被改动）", sum(second) == 0, second)
    check("V2.4 兼容：二次迁移后行数 / 列结构仍不变",
          row_counts(names) == rows_before and columns_of(names) == cols_after)
    return True


# ---------------------------------------------------------------- 数据准备

def seed_recovery():
    """把 6 道错题同步进康复队列（学生 A 五道 / 学生 B 一道）。"""
    db = SessionLocal()
    try:
        for sid, qid in ((STUDENT_A, 1), (STUDENT_A, 2), (STUDENT_A, 3), (STUDENT_A, 4),
                         (STUDENT_A, 5), (STUDENT_B, 7)):
            row = db.query(Question).filter(Question.id == qid).first()
            recovery_engine.DEFAULT_ENGINE.sync_from_wrong_book(db, sid, row, False)
        db.commit()
    finally:
        db.close()


def snapshot(sid, qid):
    """康复项落库快照（字典，避免 ORM 行脱离会话）。"""
    db = SessionLocal()
    try:
        row = db.query(WrongQuestionRecovery).filter(
            WrongQuestionRecovery.student_id == sid,
            WrongQuestionRecovery.question_id == qid).first()
        if row is None:
            return None
        return {"id": int(row.id or 0), "state": str(row.state or ""),
                "before": str(row.state_before or ""), "attempts": int(row.attempts or 0),
                "cc": int(row.consecutive_correct or 0), "fail": int(row.fail_count or 0),
                "level": int(row.max_level_used or 0), "variants": int(row.variant_count or 0),
                "next_verify": row.next_verify_time, "mastered": row.mastered_time}
    finally:
        db.close()


def answer_text(qid):
    """题目的标准答案（服务端保存的答案，测试端直读库）。"""
    db = SessionLocal()
    try:
        row = db.query(Question).filter(Question.id == qid).first()
        return str(row.answer or "") if row else ""
    finally:
        db.close()


def option_text(qid):
    """选择题正确答案对应的选项内容（提示不得泄露的就是它）。"""
    db = SessionLocal()
    try:
        row = db.query(Question).filter(Question.id == qid).first()
        if row is None:
            return ""
        options = json.loads(row.options or "{}")
        return str(options.get(str(row.answer or "").upper(), row.answer or ""))
    finally:
        db.close()


def http_get(path, **params):
    return requests.get(BASE + path, params=params, timeout=30)


def http_post(path, payload):
    return requests.post(BASE + path, json=payload, timeout=60)


def rec_id(sid, qid):
    body = http_get("/api/recovery/list", student_id=sid, limit=500).json()
    for item in body.get("items") or []:
        if int(item.get("question_id") or 0) == qid:
            return int(item.get("recovery_id") or 0)
    return 0


def submit(sid, rid, answer, qid):
    return http_post("/api/recovery/answer",
                     {"student_id": sid, "recovery_id": rid, "answer": answer, "question_id": qid})


def next_variant(sid, rid):
    body = http_post("/api/recovery/question", {"student_id": sid, "recovery_id": rid}).json()
    return body.get("question") or {}


def see_response(body):
    saw((body or {}).get("state"))
    return body


# ---------------------------------------------------------------- 用例

def list_case():
    r = http_get("/api/recovery/list", student_id=STUDENT_A)
    body = r.json()
    check("list：HTTP 200 且返回student_id/total/stats/items",
          r.status_code == 200 and body.get("student_id") == STUDENT_A
          and isinstance(body.get("items"), list) and "stats" in body)
    check("list：stats 六态 + total + mastered_rate 字段齐全",
          set(body["stats"]) == {"new", "analyzing", "learning", "practicing", "verifying",
                                 "mastered", "total", "mastered_rate"}, sorted(body["stats"]))
    check("list：stats.total = 学生 A 的康复项数（5）", body["stats"]["total"] == 5,
          body["stats"])
    check("list：total 与 items 长度一致", body["total"] == len(body["items"]) == 5)
    check("list：item 字段齐全（SPEC §7.1）",
          bool(body["items"]) and SPEC_ITEM_KEYS <= set(body["items"][0]),
          sorted(SPEC_ITEM_KEYS - set(body["items"][0])) or "齐全")
    check("list：新入队项为 NEW + 中文状态文案",
          all(i["state"] == "NEW" and i["state_text"] for i in body["items"]))
    check("list：state=NEW 过滤命中 5 条",
          http_get("/api/recovery/list", student_id=STUDENT_A, state="NEW").json()["total"] == 5)
    check("list：subject=数学 过滤命中 5 条",
          http_get("/api/recovery/list", student_id=STUDENT_A, subject="数学").json()["total"] == 5)
    check("list：非法 state → 400（失败路径）",
          http_get("/api/recovery/list", student_id=STUDENT_A, state="BOGUS").status_code == 400)
    check("list：非法 subject → 400（失败路径）",
          http_get("/api/recovery/list", student_id=STUDENT_A,
                   subject="不存在的科目").status_code == 400)
    check("list：缺 student_id → 422（失败路径）", http_get("/api/recovery/list").status_code == 422)
    check("list：student_id=0 → 422（失败路径）",
          http_get("/api/recovery/list", student_id=0).status_code == 422)
    r6 = http_get("/api/recovery/list", student_id=STUDENT_X)
    check("list：未知 student_id → 200 空结构（不是 404/500）",
          r6.status_code == 200 and r6.json()["items"] == []
          and r6.json()["stats"]["total"] == 0 and r6.json()["stats"]["mastered_rate"] == 0.0)
    r7 = http_get("/api/recovery/list", student_id=STUDENT_A, limit=0)
    check("list：limit=0 → items 空但 stats 仍统计全部",
          r7.status_code == 200 and r7.json()["items"] == []
          and r7.json()["stats"]["total"] == 5)


def state_case():
    rid = rec_id(STUDENT_A, 1)
    check("初始：q1 康复项 NEW", snapshot(STUDENT_A, 1)["state"] == "NEW")
    r = http_post("/api/recovery/start", {"student_id": STUDENT_A, "recovery_id": rid})
    body = see_response(r.json())
    check("start：NEW → LEARNING 且返回 teaching/item",
          r.status_code == 200 and body.get("state") == "LEARNING" and body.get("state_text")
          and body["teaching"].get("hint") and body.get("item"), body.get("state"))
    check("start：状态已落库", snapshot(STUDENT_A, 1)["state"] == "LEARNING")

    body = see_response(submit(STUDENT_A, rid, answer_text(1), 1).json())
    check("answer：教学态答对 → PRACTICING（changed=true）",
          body.get("correct") is True and body.get("state") == "PRACTICING"
          and body.get("changed") is True, body.get("state"))
    check("answer：回传 correct_answer / next_action / stats",
          body.get("correct_answer") == "B" and body.get("next_action") == "practice"
          and body.get("stats", {}).get("total") == 5)
    check("answer：教学态答对按 VERIFY_STREAK-1 记一次连对（落库 cc=1）",
          snapshot(STUDENT_A, 1)["cc"] == 1)

    variant = next_variant(STUDENT_A, rid)
    check("question：PRACTICING 出变式题（source 合法、非原题）",
          variant.get("variant") is True and variant.get("source") in VAR_SOURCES
          and int(variant.get("question_id") or 0) != 1, variant.get("source"))
    v1 = int(variant.get("question_id") or 0)
    body = see_response(submit(STUDENT_A, rid, "Z", v1).json())
    check("PRACTICING 变式题答错：连对清零（fail=%d）" % snapshot(STUDENT_A, 1)["fail"],
          body.get("correct") is False and snapshot(STUDENT_A, 1)["cc"] == 0, body.get("state"))
    body = see_response(submit(STUDENT_A, rid, answer_text(1), 1).json())
    check("NEW 答对原题 → 再进 PRACTICING（fail_count 不变）",
          body.get("state") == "PRACTICING" and snapshot(STUDENT_A, 1)["fail"] % 2 == 0)
    variant = next_variant(STUDENT_A, rid)
    vid = int(variant.get("question_id") or 0)
    body = see_response(submit(STUDENT_A, rid, "Z", vid).json())
    check("PRACTICING 变式题再答错：fail_count 递增为奇数 → 留在 PRACTICING",
          body.get("state") == "PRACTICING" and snapshot(STUDENT_A, 1)["fail"] % 2 == 1,
          snapshot(STUDENT_A, 1)["fail"])
    variant = next_variant(STUDENT_A, rid)
    v2 = int(variant.get("question_id") or 0)
    body = see_response(submit(STUDENT_A, rid, answer_text(v2), v2).json())
    check("PRACTICING 第 1 次答对：仍在 PRACTICING 且连对=1",
          body.get("state") == "PRACTICING" and snapshot(STUDENT_A, 1)["cc"] == 1, body.get("state"))
    variant = next_variant(STUDENT_A, rid)
    v3 = int(variant.get("question_id") or 0)
    body = see_response(submit(STUDENT_A, rid, answer_text(v3), v3).json())
    check("PRACTICING 连对 2 次 → VERIFYING", body.get("state") == "VERIFYING", body.get("state"))
    snap = snapshot(STUDENT_A, 1)
    delta = (snap["next_verify"] - datetime.now()) if snap["next_verify"] else timedelta(0)
    check("VERIFYING：next_verify_time ≈ 1 天后（23h~25h）",
          timedelta(hours=23) < delta < timedelta(hours=25), delta)

    body = see_response(http_post("/api/recovery/verify",
                                  {"student_id": STUDENT_A, "recovery_id": rid,
                                   "answer": "Z"}).json())
    check("VERIFYING 答错 → 回 PRACTICING 且连对清零",
          body.get("state") == "PRACTICING" and snapshot(STUDENT_A, 1)["cc"] == 0, body.get("state"))
    check("VERIFYING 答错：mastered=false 且 next_verify_time 清空",
          body.get("mastered") is False and snapshot(STUDENT_A, 1)["next_verify"] is None)

    for _ in range(2):
        variant = next_variant(STUDENT_A, rid)
        vid = int(variant.get("question_id") or 0)
        submit(STUDENT_A, rid, answer_text(vid), vid)
    check("再次连对 2 次 → 回到 VERIFYING", snapshot(STUDENT_A, 1)["state"] == "VERIFYING")
    body = see_response(http_post("/api/recovery/verify",
                                  {"student_id": STUDENT_A, "recovery_id": rid,
                                   "answer": answer_text(1)}).json())
    check("VERIFYING 答对 → MASTERED（mastered=true）",
          body.get("state") == "MASTERED" and body.get("mastered") is True, body.get("state"))
    check("MASTERED：mastered_time 已写入", snapshot(STUDENT_A, 1)["mastered"] is not None)
    check("MASTERED：list?state=MASTERED 命中且 mastered_rate>0",
          http_get("/api/recovery/list", student_id=STUDENT_A, state="MASTERED").json()["total"] == 1
          and http_get("/api/recovery/list", student_id=STUDENT_A).json()["stats"]["mastered_rate"] > 0)


def parity_case():
    rid = rec_id(STUDENT_A, 2)
    http_post("/api/recovery/start", {"student_id": STUDENT_A, "recovery_id": rid})
    body = see_response(submit(STUDENT_A, rid, answer_text(2), 2).json())
    check("q2：教学态答对后进 PRACTICING 且 fail_count=1（奇数）",
          body.get("state") == "PRACTICING" and snapshot(STUDENT_A, 2)["fail"] == 1)
    variant = next_variant(STUDENT_A, rid)
    vid = int(variant.get("question_id") or 0)
    body = see_response(submit(STUDENT_A, rid, "Z", vid).json())
    snap = snapshot(STUDENT_A, 2)
    check("PRACTICING 变式题答错：fail_count 递增 1→2", body.get("correct") is False
          and snap["fail"] == 2, snap["fail"])
    check("PRACTICING 答错：连对清零", snap["cc"] == 0)
    check("fail_count%2==0 → 回 NEW 且 state_before 记 PRACTICING",
          body.get("state") == "NEW" and snap["before"] == "PRACTICING", snap["before"])

    body = see_response(submit(STUDENT_A, rid, answer_text(2), 2).json())
    check("NEW 再答对 → PRACTICING（fail_count 保持 2）",
          body.get("state") == "PRACTICING" and snapshot(STUDENT_A, 2)["fail"] == 2)
    variant = next_variant(STUDENT_A, rid)
    vid = int(variant.get("question_id") or 0)
    body = see_response(submit(STUDENT_A, rid, "Z", vid).json())
    snap = snapshot(STUDENT_A, 2)
    check("fail_count%2!=0（3）→ 留在 PRACTICING（再错一次才回炉）",
          body.get("state") == "PRACTICING" and snap["fail"] == 3, snap["fail"])
    check("PRACTICING 答错：连对再次清零", snap["cc"] == 0)


def relearn_case():
    rid = rec_id(STUDENT_A, 3)
    http_post("/api/recovery/start", {"student_id": STUDENT_A, "recovery_id": rid})
    body = see_response(submit(STUDENT_A, rid, answer_text(3), 3).json())
    check("q3：教学态答对 → PRACTICING", body.get("state") == "PRACTICING")
    body = see_response(submit(STUDENT_A, rid, "Z", 3).json())
    snap = snapshot(STUDENT_A, 3)
    check("任意状态答错原题 → NEW（state_before=PRACTICING）",
          body.get("state") == "NEW" and snap["before"] == "PRACTICING", snap["before"])
    check("答错原题：fail_count 递增", snap["fail"] == 2, snap["fail"])
    body = see_response(submit(STUDENT_A, rid, "Z", 3).json())
    check("教学态（NEW）答错原题 → 仍 NEW 且 fail_count 继续递增",
          body.get("state") == "NEW" and snapshot(STUDENT_A, 3)["fail"] == 3)


def hint_case():
    rid = rec_id(STUDENT_A, 4)
    answer = option_text(4)
    seen, blobs = {}, {}
    for level in (1, 2, 3, 4):
        r = http_post("/api/recovery/hint", {"student_id": STUDENT_A, "recovery_id": rid,
                                             "level": level})
        body = r.json()
        seen[level] = body
        blobs[level] = " ".join([str(body.get("hint") or ""),
                                 str(body.get("error_location") or ""),
                                 " ".join(body.get("steps") or []),
                                 str(body.get("full_explanation") or "")])
        check("hint L%d：HTTP 200 且 level/level_text/hint 非空" % level,
              r.status_code == 200 and body.get("level") == level and body.get("level_text")
              and body.get("hint"))
    check("hint L1：不含正确答案（%s）" % answer, answer not in blobs[1])
    check("hint L3：不含正确答案（%s）" % answer, answer not in blobs[3])
    check("hint L4：完整讲解含「正确答案」与答案文本",
          "正确答案" in (seen[4].get("full_explanation") or "")
          and answer in (seen[4].get("full_explanation") or ""))
    check("hint：四级逐级给信息（四段文案互不相同）", len(set(blobs.values())) == 4)
    check("hint L3：给出分步骤（steps 非空）", bool(seen[3].get("steps")))
    check("hint：source 合法", all(seen[lv].get("source") in
                                  ("rule", "ai", "fallback", "fallback_offline",
                                   "fallback_answer_leak")
                                  for lv in (1, 2, 3, 4)),
          [seen[lv].get("source") for lv in (1, 2, 3, 4)])
    snap = snapshot(STUDENT_A, 4)
    check("hint：max_level_used 落库为 4", snap["level"] == 4, snap["level"])
    check("hint：取提示不推进状态（仍 NEW）", snap["state"] == "NEW")
    check("hint：未知 recovery_id → 空提示而非报错",
          http_post("/api/recovery/hint", {"student_id": STUDENT_A,
                                           "recovery_id": 999999, "level": 4}).json()["hint"] == "")


def analyzing_case():
    check("ANALYZING：纯状态机可达（NEW --analyze--> ANALYZING）",
          transition("NEW", "analyze")["next_state"] == "ANALYZING")
    check("ANALYZING：中文文案与下一步动作齐全",
          state_text("ANALYZING") == "正在找错因，准备讲解"
          and next_action("ANALYZING") == "hint")
    saw("ANALYZING")
    db = SessionLocal()
    try:
        row = db.query(Question).filter(Question.id == 8).first()
        recovery_engine.DEFAULT_ENGINE.sync_from_wrong_book(db, STUDENT_A, row, False)
        item = db.query(WrongQuestionRecovery).filter(
            WrongQuestionRecovery.student_id == STUDENT_A,
            WrongQuestionRecovery.question_id == 8).first()
        item.state, item.state_before = "ANALYZING", "NEW"
        db.commit()
        rid = int(item.id or 0)
    finally:
        db.close()
    body = http_get("/api/recovery/list", student_id=STUDENT_A, state="ANALYZING").json()
    check("ANALYZING：list?state=ANALYZING 能读到（接口层可达）",
          body["total"] == 1 and body["items"][0]["state"] == "ANALYZING")
    check("ANALYZING：state_text 中文正确",
          body["items"][0]["state_text"] == "正在找错因，准备讲解")
    body = see_response(http_post("/api/recovery/start",
                                  {"student_id": STUDENT_A, "recovery_id": rid}).json())
    check("ANALYZING：start 继续推进到 LEARNING", body.get("state") == "LEARNING")
    body = see_response(submit(STUDENT_A, rid, "Z", 8).json())
    check("LEARNING 答错原题 → NEW（state_before=LEARNING）",
          body.get("state") == "NEW" and snapshot(STUDENT_A, 8)["before"] == "LEARNING")


def start_by_question_case():
    """不带 recovery_id，只给 question_id 的入队路径。"""
    rid = rec_id(STUDENT_A, 6)
    check("start：q6 尚未入队（按 question_id 入队路径前置条件）", rid == 0)
    body = http_post("/api/recovery/start", {"student_id": STUDENT_A, "question_id": 6}).json()
    check("start：只给 question_id 自动入队并开始教学",
          int(body.get("recovery_id") or 0) > 0 and body.get("question_id") == 6
          and body.get("state") == "LEARNING", body.get("state"))
    check("start：入队后 list 能查到",
          rec_id(STUDENT_A, 6) == int(body.get("recovery_id") or 0))
    check("start：非法 recovery_id → 空结构（不 404/500）",
          http_post("/api/recovery/start", {"student_id": STUDENT_A,
                                            "recovery_id": 987654}).json()["recovery_id"] == 0)


def isolation_case():
    rid_a = rec_id(STUDENT_A, 1)
    body = http_post("/api/recovery/start", {"student_id": STUDENT_B, "recovery_id": rid_a}).json()
    check("隔离：学生 B 用 A 的 recovery_id 调 start → 空结构",
          body.get("recovery_id") == 0 and body.get("item") is None
          and not body["teaching"].get("hint"))
    body = http_post("/api/recovery/question",
                     {"student_id": STUDENT_B, "recovery_id": rid_a}).json()
    check("隔离：学生 B 取不到 A 的题目",
          int(body["question"]["question_id"] or 0) == 0 and body["question"]["question"] == "")
    body = http_post("/api/recovery/answer", {"student_id": STUDENT_B, "recovery_id": rid_a,
                                              "answer": answer_text(1)}).json()
    check("隔离：学生 B 提交 A 的正确答案仍判否且不泄露答案 / 解析",
          body.get("correct") is False and body.get("correct_answer") == ""
          and body.get("analysis") == "")
    body = http_post("/api/recovery/verify", {"student_id": STUDENT_B, "recovery_id": rid_a,
                                              "answer": answer_text(1)}).json()
    check("隔离：学生 B verify A 的项 → mastered=false 空结构",
          body.get("mastered") is False and body.get("state") == "")
    body = http_post("/api/recovery/hint", {"student_id": STUDENT_B, "recovery_id": rid_a,
                                            "level": 4}).json()
    check("隔离：学生 B 取不到 A 的提示", body.get("hint") == ""
          and body.get("full_explanation") == "")
    r = http_get("/api/recovery/list", student_id=STUDENT_B)
    body = r.json()
    check("隔离：B 的列表只有自己的 1 道题（q7）",
          body["total"] == 1 and {i["question_id"] for i in body["items"]} == {7})
    leaked = [text for text in ("12 × 12", "144", "两位数乘法")
              if text in r.text and text != "两位数乘法"]
    check("隔离：B 的列表响应体不出现 A 的题干 / 答案", not leaked, leaked)
    check("隔离：B 的 stats 不含 A 的量",
          body["stats"]["total"] == 1
          and http_get("/api/recovery/list", student_id=STUDENT_A).json()["stats"]["total"] >= 4)


def offline_case():
    check("AI 离线：PHOEBE_AI_OFFLINE=1 时 ai_enabled() 为假", ai_recovery.ai_enabled() is False)
    db = SessionLocal()
    try:
        row = db.query(Question).filter(Question.id == 5).first()
        try:
            hint = ai_recovery.teach(row, knowledge="两位数乘法", error_type="计算错误", level=2)
            variants = ai_recovery.generate_variants(row, count=2)
        except Exception as exc:                      # noqa: BLE001 - 离线降级不允许抛异常
            check("AI 离线：teach / generate_variants 不抛异常", False, repr(exc))
        else:
            check("AI 离线：teach 降级返回规则提示（不报错）",
                  bool(hint.get("hint")) and int(hint.get("level") or 0) == 2)
            check("AI 离线：变式题降级为规则题（source=rule）",
                  bool(variants) and all(v.get("source") == "rule" for v in variants),
                  [v.get("source") for v in variants])
    finally:
        db.close()
    rid = rec_id(STUDENT_A, 5)
    body = http_post("/api/recovery/start", {"student_id": STUDENT_A, "recovery_id": rid}).json()
    check("AI 离线：接口层全流程可用（start/出题/判分）",
          body.get("state") == "LEARNING"
          and int(next_variant(STUDENT_A, rid).get("question_id") or 0) > 0)


def variant_case():
    db = SessionLocal()
    try:
        original = db.query(Question).filter(Question.id == 3).first()
        variants = ai_recovery.generate_variants(original, count=3,
                                                difficulty=original.difficulty,
                                                knowledge=original.knowledge)
    finally:
        db.close()
    check("变式题：至少生成 1 道", len(variants) >= 1, len(variants))
    check("变式题：source 合法（rule / ai）",
          all(v.get("source") in ("rule", "ai") for v in variants),
          [v.get("source") for v in variants])
    check("变式题：每题 validation.passed 为真（题目质量唯一真相）",
          all((v.get("validation") or {}).get("passed") for v in variants),
          [v.get("question") for v in variants if not (v.get("validation") or {}).get("passed")])
    check("变式题：题干 / 答案 / 选项齐全且答案在选项内",
          all(v.get("question") and str(v.get("answer") or "").upper() in
              {str(k).upper() for k in (v.get("options") or {})} for v in variants))
    check("变式题：二次独立校验（QuestionValidator.validate）仍通过",
          all(validator.DEFAULT_VALIDATOR.validate(v, subject="数学", knowledge="两位数乘法",
                                                   difficulty=3)["passed"] for v in variants))


def coverage_case():
    check("六态可达：NEW/ANALYZING/LEARNING/PRACTICING/VERIFYING/MASTERED 全部观察到",
          {"NEW", "ANALYZING", "LEARNING", "PRACTICING", "VERIFYING", "MASTERED"} <= OBSERVED,
          sorted(OBSERVED))


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
        "import recovery_routes\n"
        "app = FastAPI(title='verify-recovery')\n"
        "app.include_router(recovery_routes.router)\n"
        "@app.get('/')\n"
        "def _root():\n"
        "    return {'ok': True, 'suite': 'recovery'}\n"
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
                check("临时后端启动（端口 %d，自带 recovery 路由）" % PORT, True)
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
    seed_recovery()
    proc = start_server()
    try:
        list_case()
        state_case()
        parity_case()
        relearn_case()
        hint_case()
        analyzing_case()
        start_by_question_case()
        isolation_case()
        offline_case()
        variant_case()
        coverage_case()
    finally:
        print("耗时 %.1fs" % (time.time() - start))
        finish(proc)


if __name__ == "__main__":
    main()
