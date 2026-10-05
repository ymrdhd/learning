# ==============================================================
# 能力契约｜验证：学习闭环回归（建表/判分/出题不下发答案/能力更新/兜底题/题单按项记分），端口 8900
# 入口：脚本自身：python backend/verify_flow.py --self-serve（**必须带 --self-serve**，否则会写真实库）
# 依赖：main、grading、deepseek、models、database
# 不负责：知识域接口 → verify_knowledge.py；自适应 → verify_adaptive.py
# 验证：python backend/verify_flow.py --self-serve
# 被调用：verify_all.py（套件 flow）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""P0 冒烟测试：验证学习闭环与关键护栏。

覆盖：库结构 → 判分逻辑 → 出题（不泄漏答案）→ 作答判分 → 答题落库
      → 能力更新 → 难度自适应 → 填空模式 → 跨域 → 异常兜底
      → 题单模式：带 task_id 的一次作答只记到对应题型（V2.8 需求）

两种用法：
  1. 先启动后端，再跑（默认连 127.0.0.1:8000，可用 VERIFY_BASE 改）
         python backend/verify_flow.py
  2. 传 --self-serve，脚本自拉一个临时后端 + 临时库（端口取 VERIFY_FLOW_PORT，默认 8900），
     不再依赖外面有没有起服务，也不会写进 learning.db
         python backend/verify_flow.py --self-serve

全部通过时退出码为 0。
"""

import json
import os
import socket
import subprocess
import sys
import time

SELF_SERVE = "--self-serve" in sys.argv
PORT = int(os.getenv("VERIFY_FLOW_PORT", "8900"))

if SELF_SERVE:
    # 必须在 import database 之前设好：DATABASE_URL 是模块级读取的
    _db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_flow.db")
    for _suffix in ("", "-journal", "-wal", "-shm"):
        if os.path.exists(_db_file + _suffix):
            os.remove(_db_file + _suffix)
    os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
    os.environ["DEEPSEEK_API_KEY"] = ""      # 走内置兜底题，测试不依赖外网

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import deepseek
import knowledge_tree
from database import SessionLocal, engine
from grading import is_correct
from models import Ability, AnswerRecord, Question

BASE = os.getenv("VERIFY_BASE") or (
    f"http://127.0.0.1:{PORT}" if SELF_SERVE else "http://127.0.0.1:8000"
)
STUDENT_ID = 1
ok = True
proc = None

# 复用连接：整个套件要发十几次请求，省掉每次的 TCP 握手
http = requests.Session()


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


def port_in_use():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
            return True
    return False


def start_server():
    """自拉临时后端，返回进程对象。端口被占用直接失败，避免连上别人的服务跑出假通过。"""
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


if SELF_SERVE:
    proc = start_server()


# ---------- 1. 库结构 ----------
with engine.connect() as conn:
    tables = {r[0] for r in conn.exec_driver_sql("select name from sqlite_master where type='table'")}
    q_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(questions)")}
    ar_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(answer_records)")}
    s_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(students)")}

check("存在 abilities / answer_records 表", {"abilities", "answer_records"} <= tables, sorted(tables))
check("questions 含选项与解析列", {"qtype", "options", "acceptable", "analysis"} <= q_cols)
check("answer_records 含题目与作答内容", {"question_id", "submitted"} <= ar_cols, sorted(ar_cols))
check("students 含 avatar / created_at", {"avatar", "created_at"} <= s_cols, sorted(s_cols))


# ---------- 2. 判分逻辑 ----------
class Row:
    def __init__(self, answer, options=None, acceptable=None):
        self.answer = answer
        self.options = options
        self.acceptable = acceptable


opts = json.dumps({"A": "7", "B": "8", "C": "9", "D": "6"})
r = Row("B", opts, json.dumps([]))
check("选择:正确字母", is_correct(r, "B") is True)
check("选择:错误字母", is_correct(r, "A") is False)
check("选择:小写字母", is_correct(r, "b") is True)
check("选择:提交选项内容", is_correct(r, "8") is True)
check("选择:空提交", is_correct(r, "   ") is False)

b = Row("8", json.dumps({}), json.dumps(["8", "八"], ensure_ascii=False))
check("填空:精确匹配", is_correct(b, "8") is True)
check("填空:全角数字", is_correct(b, "８") is True)
check("填空:同义写法", is_correct(b, "八") is True)
check("填空:错误答案", is_correct(b, "9") is False)


# ---------- 3. 学生列表 ----------
students = http.get(BASE + "/students", timeout=10).json()
check("默认双用户可用", len(students) >= 2, [s["name"] for s in students])
check("学生带年级文案", all(s.get("grade_text") for s in students))


# ---------- 4. 出题 ----------
q = http.get(
    BASE + "/question",
    params={"student_id": STUDENT_ID, "subject": "数学", "qtype": "choice"},
    timeout=60,
).json()
check("出题返回 question_id", isinstance(q.get("question_id"), int))
check("选择题返回>=2个选项", len(q.get("options") or {}) >= 2, q.get("options"))
check("答案未下发给前端", "answer" not in q, sorted(q.keys()))
check("返回当前难度", isinstance(q.get("difficulty"), int), q.get("difficulty"))

db = SessionLocal()
row = db.query(Question).filter(Question.id == q["question_id"]).first()
truth = row.answer
db.close()
check("题目已入库且答案非空", bool(truth))


# ---------- 5. 判分 + 落库 + 能力更新 ----------
db = SessionLocal()
before_records = db.query(AnswerRecord).count()
db.close()

good = http.post(
    BASE + "/submit",
    json={"question_id": q["question_id"], "answer": truth, "student_id": STUDENT_ID},
    timeout=20,
).json()
check("答对判为正确", good["correct"] is True)
check("答对回传解析", bool(good["analysis"]))

wrong_letter = [k for k in q["options"] if k != truth][0]
bad = http.post(
    BASE + "/submit",
    json={"question_id": q["question_id"], "answer": wrong_letter, "student_id": STUDENT_ID},
    timeout=20,
).json()
check("答错判为错误", bad["correct"] is False)
check("答错回传正确答案", bad["correct_answer"] == truth, bad["correct_answer"])

db = SessionLocal()
after_records = db.query(AnswerRecord).count()
ability = db.query(Ability).filter(
    Ability.student_id == STUDENT_ID, Ability.subject == "数学"
).first()
db.close()
check("两次作答均已落库", after_records == before_records + 2, (before_records, after_records))
check("能力累计次数已更新", ability.total_count >= 2, ability.total_count if ability else None)


# ---------- 5.5 题单模式：这次作答记到哪一项今日任务头上（V2.8 需求） ----------
def sheet_tasks():
    return http.get(BASE + "/api/tasks/today", params={"student_id": STUDENT_ID},
                    timeout=20).json()["tasks"]


tasks_before = sheet_tasks()
target = next((item for item in tasks_before
               if item.get("status") != "done"
               and int(item.get("target_count") or 0) > int(item.get("complete_count") or 0)),
              None)
check("题单模式：今日任务里有一项还没做完，可以按项记分", target is not None)
if target:
    sheet_q = http.get(
        BASE + "/question",
        params={"student_id": STUDENT_ID, "subject": target["subject"],
                "knowledge": target.get("knowledge") or "", "qtype": "choice"},
        timeout=60,
    ).json()
    db = SessionLocal()
    sheet_row = db.query(Question).filter(Question.id == sheet_q["question_id"]).first()
    sheet_truth = sheet_row.answer
    db.close()

    http.post(
        BASE + "/submit",
        json={"question_id": sheet_q["question_id"], "answer": sheet_truth,
              "student_id": STUDENT_ID, "task_id": target["task_id"]},
        timeout=20,
    )

    tasks_after = sheet_tasks()
    after = next(item for item in tasks_after if item["task_id"] == target["task_id"])
    others_before = sum(int(item.get("complete_count") or 0) for item in tasks_before
                        if item["task_id"] != target["task_id"])
    others_after = sum(int(item.get("complete_count") or 0) for item in tasks_after
                       if item["task_id"] != target["task_id"])
    check("题单模式：带 task_id 的作答只给这一项 +1（别的题型一点没动）",
          int(after.get("complete_count") or 0)
          == min(int(target["target_count"]), int(target.get("complete_count") or 0) + 1)
          and others_before == others_after,
          (after.get("complete_count"), target["target_count"], others_before, others_after))
    check("题单模式：做满 target_count 这一项就收工、没做满就还是进行中",
          (int(after.get("complete_count") or 0) >= int(after.get("target_count") or 1)
           and after.get("status") == "done")
          or (int(after.get("complete_count") or 0) < int(after.get("target_count") or 1)
              and after.get("status") == "doing"),
          (after.get("complete_count"), after.get("target_count"), after.get("status")))


# ---------- 6. 难度自适应闭环 ----------
nxt = http.get(
    BASE + "/question",
    params={"student_id": STUDENT_ID, "subject": "数学", "qtype": "choice"},
    timeout=60,
).json()
# V2.6：无诊断画像时难度 = 能力分与「知识点固有难度」各占一半（main.question）
expected_next = int(round(
    0.5 * float(bad["score"])
    + 0.5 * float(knowledge_tree.difficulty_of("数学", nxt["knowledge"]))))
check(
    "下一题难度 = 能力分与知识点固有难度各占一半",
    nxt["difficulty"] == expected_next,
    {"score": bad["score"], "knowledge": nxt["knowledge"],
     "next_difficulty": nxt["difficulty"], "expected": expected_next},
)


# ---------- 7. 填空模式 ----------
q2 = http.get(
    BASE + "/question",
    params={"student_id": STUDENT_ID, "subject": "数学", "qtype": "blank"},
    timeout=60,
).json()
check("填空题不返回选项", not q2.get("options"), q2.get("options"))

db = SessionLocal()
row2 = db.query(Question).filter(Question.id == q2["question_id"]).first()
truth2 = row2.answer
db.close()

s2 = http.post(
    BASE + "/submit",
    json={"question_id": q2["question_id"], "answer": truth2, "student_id": STUDENT_ID},
    timeout=20,
).json()
check("填空按标准答案判对", s2["correct"] is True, truth2)


# ---------- 8. 跨域与异常 ----------
preflight = http.options(
    BASE + "/submit",
    headers={"Origin": "null", "Access-Control-Request-Method": "POST"},
    timeout=10,
)
check("跨域预检放行", preflight.headers.get("access-control-allow-origin") == "*",
      preflight.headers.get("access-control-allow-origin"))

check(
    "不存在的题目返回404",
    http.post(BASE + "/submit", json={"question_id": 999999, "answer": "A"}, timeout=20).status_code == 404,
)

orig_url = deepseek.API_URL
deepseek.API_URL = "http://127.0.0.1:9/nowhere"
f1 = deepseek.generate_question("数学", "一年级", "20以内加减法", 50, "choice")
f2 = deepseek.generate_question("数学", "一年级", "20以内加减法", 50, "blank")
deepseek.API_URL = orig_url
check("接口异常时选择题兜底可用", f1["source"] == "fallback" and f1["answer"] in f1["options"], f1["source"])
check("接口异常时填空题兜底可用", f2["source"] == "fallback" and bool(f2["answer"]), f2["source"])

# ---------- 9. 出题防雷同（V2.5：同一道经典题不要在一次练习里连出好几遍）----------
import question_dedupe

old_stem = "「床前明月光，疑是地上（  ）。」括号里应该填什么？"
check("防雷同：原题重出被判为重复", question_dedupe.is_duplicate(old_stem, [old_stem + " "]) is True)
check("防雷同：换数字算新题", question_dedupe.is_duplicate("算一算：36 × 24 = ？",
                                                     ["算一算：42 × 18 = ？"]) is False)

_real_post = deepseek.requests.post

def _fake_response(payload):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

    return _Resp()

# 模型第一次故意吐旧题、第二次换新题：本地复核必须识破并重出
_seen_prompts = []


def _dup_then_new(url, headers=None, json=None, timeout=None, **kwargs):
    _seen_prompts.append((json or {}).get("messages", [{}])[0].get("content", ""))
    if len(_seen_prompts) == 1:
        return _fake_response({"question": old_stem, "options": {"A": "霜", "B": "雪", "C": "冰", "D": "水"},
                               "answer": "A", "analysis": "旧题"})
    return _fake_response({"question": "「白日依山尽」的下一句是什么？",
                           "options": {"A": "黄河入海流", "B": "疑是地上霜", "C": "举头望明月", "D": "低头思故乡"},
                           "answer": "A", "analysis": "新题"})


deepseek.API_URL = "http://127.0.0.1:9/not-used"
deepseek.requests.post = _dup_then_new
try:
    fixed = deepseek.generate_question("语文", "一年级", "古诗背诵", 50, "choice", history=[old_stem])
    check("防雷同：命中旧题就重出并返回新题", "白日依山尽" in fixed.get("question", "")
          and not fixed.get("repeated"), fixed.get("question"))
    check("防雷同：历史原题被写进 prompt", "不要重复出" in (_seen_prompts[0] if _seen_prompts else ""))
    check("防雷同：重出时最多 2 次模型调用", len(_seen_prompts) == 2, len(_seen_prompts))
finally:
    deepseek.requests.post = _real_post
    deepseek.API_URL = orig_url

# 模型一直吐旧题：不能把兜底题发给小朋友，要把最后一版发出去并标注雷同
_always_dup_calls = []


def _always_dup(url, headers=None, json=None, timeout=None, **kwargs):
    _always_dup_calls.append(1)
    return _fake_response({"question": old_stem, "options": {"A": "霜", "B": "雪", "C": "冰", "D": "水"},
                           "answer": "A", "analysis": "旧题"})


deepseek.API_URL = "http://127.0.0.1:9/not-used"
deepseek.requests.post = _always_dup
try:
    stubborn = deepseek.generate_question("语文", "一年级", "古诗背诵", 50, "choice", history=[old_stem])
    check("防雷同：持续雷同仍返回模型题而不是兜底题", stubborn.get("source") == "deepseek"
          and "明月" in stubborn.get("question", ""), stubborn.get("source"))
    check("防雷同：持续雷同会被标注 repeated", stubborn.get("repeated") is True)
    check("防雷同：持续雷同时尝试 3 次", len(_always_dup_calls) == deepseek.MAX_GENERATION_ATTEMPTS,
          len(_always_dup_calls))
finally:
    deepseek.requests.post = _real_post
    deepseek.API_URL = orig_url

# 无历史时行为与改动前一致：不多调模型
clean_calls = []


def _clean(url, headers=None, json=None, timeout=None, **kwargs):
    clean_calls.append(1)
    return _fake_response({"question": "算一算：12 + 7 = ？", "options": {"A": "19", "B": "18", "C": "20", "D": "17"},
                           "answer": "A", "analysis": "12 加 7 等于 19。"})


deepseek.API_URL = "http://127.0.0.1:9/not-used"
deepseek.requests.post = _clean
try:
    plain = deepseek.generate_question("数学", "一年级", "20以内加减法", 50, "choice")
    check("无历史时不重复检测、不重试", len(clean_calls) == 1 and plain.get("source") == "deepseek",
          len(clean_calls))
finally:
    deepseek.requests.post = _real_post
    deepseek.API_URL = orig_url


if proc is not None:
    # 自拉后端模式：收进程、放连接、删临时库，避免残留占住端口影响下次运行
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    engine.dispose()

    db_file = os.environ["DATABASE_URL"].replace("sqlite:///", "")
    for suffix in ("", "-journal", "-wal", "-shm"):
        if os.path.exists(db_file + suffix):
            os.remove(db_file + suffix)

print("\nRESULT:", "ALL PASS" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)
