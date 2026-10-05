# ==============================================================
# 能力契约｜验证：家长端「备份并重置」（user_routes）
# 入口：脚本自身：python backend/verify_user_reset.py（临时后端 8914 + 临时库）
# 依赖：requests、database、models、user_routes.BACKUP_DIR
# 不负责：前端按钮与二次确认 → frontend/verify_growth_profile_web.js
# 验证：python backend/verify_all.py userreset
# 被调用：verify_all.py（套件 userreset）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""家长端「备份并重置」验证：先备份后清空、备份内容、隔离、幂等、失败路径、重置后可用。

全部通过时退出码为 0。
"""

import json
import os
import socket
import subprocess
import sys
import time

PORT = int(os.getenv("VERIFY_USER_RESET_PORT", "8914"))
HERE = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(HERE, "_verify_user_reset.db")

# 必须在 import database 之前把库指到临时文件（DATABASE_URL 是模块级读取的）
for suffix in ("", "-journal", "-wal", "-shm"):
    leftover = DB_FILE + suffix
    if os.path.exists(leftover):
        os.remove(leftover)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_FILE.replace("\\", "/")

sys.path.insert(0, HERE)

import requests  # noqa: E402

from database import SessionLocal, engine  # noqa: E402
from models import Ability, AnswerRecord, Student, StudentKnowledgeMastery  # noqa: E402

BASE = f"http://127.0.0.1:{PORT}"
http = requests.Session()
ok = True
proc = None
created_backups = []


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


def port_in_use(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def start_server():
    """自拉临时后端；端口被占用直接失败，避免连上别人的服务跑出假通过。"""
    if port_in_use(PORT):
        print(f"FAIL  端口 {PORT} 已被占用，请先关掉占用该端口的进程再跑本测试。")
        sys.exit(1)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    child = subprocess.Popen(
        [sys.executable, "-c",
         f"import uvicorn, main; uvicorn.run(main.app, host='127.0.0.1', port={PORT}, log_level='warning')"],
        cwd=HERE, env=env)

    deadline = time.time() + 60
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


def count_of(model, student_id):
    db = SessionLocal()
    try:
        return db.query(model).filter(model.student_id == student_id).count()
    finally:
        db.close()


def student_name(student_id):
    db = SessionLocal()
    try:
        row = db.query(Student).filter(Student.id == student_id).first()
        return row.name if row else None
    finally:
        db.close()


def seed_real_learning():
    """用真实链路（/question + /submit）给学生 1 造学习数据，再顺手给学生 2 造一条做隔离对照。"""
    question = http.get(BASE + "/question",
                        params={"student_id": 1, "subject": "数学", "qtype": "choice"},
                        timeout=60).json()
    for answer in ("A", "B"):
        http.post(BASE + "/submit",
                  json={"question_id": question["question_id"], "answer": answer, "student_id": 1},
                  timeout=30)
    db = SessionLocal()
    try:
        db.add(Ability(student_id=2, subject="数学", score=42.0, stage=2.0,
                       total_count=3, correct_count=1))
        db.commit()
    finally:
        db.close()
    return question


proc = start_server()

# ---------- 1. 造数据（真实链路） ----------
check("临时后端在 %d 启动" % PORT, proc is not None and proc.poll() is None)
seed_real_learning()
counts = {
    "abilities": count_of(Ability, 1),
    "answer_records": count_of(AnswerRecord, 1),
    "student_knowledge_mastery": count_of(StudentKnowledgeMastery, 1),
}
other_before = count_of(Ability, 2)
check("造出了真实学习数据", counts["answer_records"] >= 2 and counts["abilities"] == 1, counts)

# ---------- 2. 预览（只读） ----------
preview = http.get(BASE + "/api/user/1/reset-preview", timeout=30)
check("预览接口可用", preview.status_code == 200, preview.status_code)
body = preview.json() if preview.status_code == 200 else {}
check("预览带学生名与年级", bool(body.get("name")) and body.get("grade") is not None,
      {k: body.get(k) for k in ("name", "grade")})
check("预览列出会被清空的表与条数",
      body.get("tables", {}).get("abilities") == counts["abilities"]
      and body.get("tables", {}).get("answer_records") == counts["answer_records"],
      body.get("tables"))
check("预览给出总条数", body.get("total") == sum(body.get("tables", {}).values()), body.get("total"))
check("预览是只读的（没动数据）",
      count_of(Ability, 1) == counts["abilities"]
      and count_of(AnswerRecord, 1) == counts["answer_records"],
      (count_of(Ability, 1), count_of(AnswerRecord, 1)))

# ---------- 3. 失败路径 ----------
missing = http.get(BASE + "/api/user/9999/reset-preview", timeout=10)
check("不存在的学生返回 404", missing.status_code == 404, missing.status_code)
missing_reset = http.post(BASE + "/api/user/9999/reset", timeout=10)
check("不存在的学生不能重置（404）", missing_reset.status_code == 404, missing_reset.status_code)
zero = http.post(BASE + "/api/user/0/reset", timeout=10)
check("student_id=0 返回 400", zero.status_code == 400, zero.status_code)

# ---------- 4. 重置：先备份，后清空 ----------
done = http.post(BASE + "/api/user/1/reset", timeout=60)
check("重置接口返回 200", done.status_code == 200, done.status_code)
data = done.json() if done.status_code == 200 else {}
backup_path = data.get("backup_path") or ""
created_backups.append(backup_path)

check("返回备份文件名", bool(data.get("backup_file")), data.get("backup_file"))
check("备份文件真的写出来了", bool(backup_path) and os.path.exists(backup_path), backup_path)
check("备份落在 backup/user_reset 目录里",
      os.path.dirname(backup_path).replace("\\", "/").endswith("backup/user_reset"),
      os.path.dirname(backup_path))

payload = {}
if backup_path and os.path.exists(backup_path):
    with open(backup_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
check("备份是 JSON 且记下学生是谁",
      payload.get("student", {}).get("name") == student_name(1)
      and payload.get("student", {}).get("id") == 1, payload.get("student"))
check("备份保留了清空前的答题记录",
      len(payload.get("tables", {}).get("answer_records", [])) == counts["answer_records"],
      len(payload.get("tables", {}).get("answer_records", [])))
check("备份保留了清空前的知识掌握度",
      len(payload.get("tables", {}).get("student_knowledge_mastery", []))
      == counts["student_knowledge_mastery"],
      len(payload.get("tables", {}).get("student_knowledge_mastery", [])))

check("重置清空了能力分数", count_of(Ability, 1) == 0, count_of(Ability, 1))
check("重置清空了答题记录", count_of(AnswerRecord, 1) == 0, count_of(AnswerRecord, 1))
check("重置清空了知识掌握度", count_of(StudentKnowledgeMastery, 1) == 0,
      count_of(StudentKnowledgeMastery, 1))
check("清空条数写进响应，且与预览一致", data.get("total_cleared") == body.get("total"),
      (data.get("total_cleared"), body.get("total")))
check("孩子本人还在（只是回到零起点）", student_name(1) is not None, student_name(1))
check("另一个小朋友的数据没被动", count_of(Ability, 2) == other_before,
      (other_before, count_of(Ability, 2)))

# ---------- 5. 幂等 ----------
again = http.post(BASE + "/api/user/1/reset", timeout=60)
check("空数据再重置也是 200（幂等）", again.status_code == 200, again.status_code)
if again.status_code == 200:
    created_backups.append(again.json().get("backup_path") or "")
    check("确认清空后，再重置清空 0 条", again.json().get("total_cleared") == 0,
          again.json().get("total_cleared"))

# ---------- 6. 重置后还能继续学 ----------
question = http.get(BASE + "/question",
                    params={"student_id": 1, "subject": "数学", "qtype": "choice"},
                    timeout=60)
check("重置后仍能出题（重新开始）",
      question.status_code == 200 and isinstance(question.json().get("question_id"), int),
      question.status_code)
auto = http.get(BASE + "/api/ability/auto/1", timeout=30)
check("重置后能力评价回到「还没有数据」",
      auto.status_code == 200 and auto.json().get("overall", {}).get("status") == "unknown",
      auto.json().get("overall") if auto.status_code == 200 else auto.status_code)

# ---------- 清理 ----------
if proc is not None:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()

for path in created_backups:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
try:
    engine.dispose()  # 先放掉连接，否则 Windows 上临时库文件删不掉
except Exception:
    pass

for suffix in ("", "-journal", "-wal", "-shm"):
    leftover = DB_FILE + suffix
    if os.path.exists(leftover):
        try:
            os.remove(leftover)
        except OSError:
            pass

print("\nRESULT:", "ALL PASS" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)
