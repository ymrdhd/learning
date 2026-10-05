# ==============================================================
# 能力契约｜验证：V2.1 艾宾浩斯复习闭环（srs.py + /reviews + 面板字段），端口 8899
# 入口：脚本自身：python backend/verify_review.py
# 依赖：srs、main、models、database
# 不负责：V2.4 记忆体系 → verify_memory.py
# 验证：python backend/verify_review.py
# 被调用：verify_all.py（套件 review）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.1 艾宾浩斯复习闭环测试。

覆盖：复习表结构 → 间隔阶梯纯函数 → 新知识点自动建计划 → 到期优先复习
      → 答错打回第一级 → 连续答对 3 次升级 → 升级后不再到期 → /reviews 总览

测试自己拉起一个临时后端（独立端口 + 独立临时库，不污染 backend/learning.db），
用临时库也能顺带验证"新库自动建表"。

用法：python backend/verify_review.py
全部通过时退出码为 0。
"""

import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from sqlalchemy import create_engine, text

import srs

PORT = int(os.getenv("VERIFY_REVIEW_PORT", "8899"))
BASE = f"http://127.0.0.1:{PORT}"
STUDENT_ID = 1
DEFAULT_KNOWLEDGE = "20以内加减法"
NEW_KNOWLEDGE = "100以内进位加法"
ok = True

# 复用连接：出题请求要走一遍兜底题库，是整个测试里最贵的一步
session = requests.Session()


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


# ---------- 1. 间隔阶梯纯函数 ----------
check("间隔阶梯递增", all(a < b for a, b in zip(srs.INTERVALS, srs.INTERVALS[1:])), srs.INTERVALS)
check("间隔文案可读", srs.format_interval(300) == "5分钟后", srs.format_interval(300))
check("小时级文案", srs.format_interval(12 * 3600) == "12小时后", srs.format_interval(43200))

fresh = srs.normalize(None)
check("新知识点立即到期", srs.is_due(fresh) is True, fresh)
check("新知识点默认第一级间隔", fresh["interval"] == srs.INTERVALS[0], fresh["interval"])

r1 = srs.review(fresh, True)
check("答对首次仍是第0阶段", r1["stage"] == 0 and r1["streak"] == 1, r1)
check("答对后按第一级间隔安排", r1["interval"] == srs.INTERVALS[0], r1["interval"])
check("答对后不再到期", srs.is_due(r1) is False, r1)

r_bad = srs.review({"stage": 4, "streak": 2, "interval": srs.INTERVALS[4], "due_at": 0}, False)
check("答错阶段打回 0", r_bad["stage"] == 0 and r_bad["streak"] == 0, r_bad)
check("答错按 5 分钟后再练", r_bad["interval"] == srs.INTERVALS[0], r_bad["interval"])
check("答错有提醒文案", "巩固" in r_bad["message"], r_bad["message"])

r3 = srs.review(fresh, True)
r3 = srs.review(r3, True)
r3 = srs.review(r3, True)
check("连续答对3次升到第1阶段", r3["stage"] == 1 and r3["streak"] == 0, r3)
check("升级后间隔变为第2级", r3["interval"] == srs.INTERVALS[1], r3["interval"])
check("升级掌握度提升", srs.mastery(r3) > srs.mastery(fresh), (srs.mastery(fresh), srs.mastery(r3)))

full = srs.review({"stage": srs.MASTERED_STAGE, "streak": 0, "interval": srs.INTERVALS[-1], "due_at": 0}, True)
check("掌握后不再进复习队列", srs.is_due(full) is False and full["mastered"] is True, full)

# 知识点选择：填了就按填的走，没填才用复习队列
past = srs.now_ts() - 600
learned = {"knowledge": "乘法口诀", "due_at": past, "stage": 1, "interval": 300,
           "mastered": False, "review_count": 4}
fresh_row = {"knowledge": "除法", "due_at": past, "stage": 0, "interval": 300,
             "mastered": False, "review_count": 0}
check("填了知识点就按它出题",
      srs.select_knowledge([fresh_row], [learned], "除法") == {"knowledge": "除法", "is_review": False})
check("做过又到期的算复习",
      srs.select_knowledge([learned], [learned], "乘法口诀") == {"knowledge": "乘法口诀", "is_review": True})
check("没做过的即使到期也不算复习",
      srs.select_knowledge([fresh_row], [fresh_row], "除法") == {"knowledge": "除法", "is_review": False})
check("没填知识点走复习队列",
      srs.select_knowledge([], [learned], "") == {"knowledge": "乘法口诀", "is_review": True})


# ---------- 启动临时后端 ----------
# 临时库放在 backend/ 下：DSH 沙箱只允许在会话工作区写文件，系统 Temp 目录里
# SQLite 打不开，放这里既跑得通又看得见，跑完删除。
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_review.db")
for leftover in (DB_FILE, DB_FILE + "-journal", DB_FILE + "-wal", DB_FILE + "-shm"):
    if os.path.exists(leftover):
        os.remove(leftover)

# 端口被占用时必须直接报错：否则可能连上别人起的服务，跑出"假通过"的结果，
# 上一轮开发就因为残留进程踩过一次，白白耗了 3 分钟。
# 注意不能用 requests 探测：别人绑在 0.0.0.0 上时本地连接能建立却收不到 HTTP 响应。
def port_in_use():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
            return True
    return False


if port_in_use():
    print(f"FAIL  端口 {PORT} 已被占用。请先关掉占用该端口的进程再跑本测试。")
    sys.exit(1)

env = dict(os.environ)
env["DATABASE_URL"] = "sqlite:///" + DB_FILE.replace("\\", "/")
env["DEEPSEEK_API_KEY"] = ""          # 强制走内置兜底题，测试不依赖外网
env["PYTHONIOENCODING"] = "utf-8"

proc = subprocess.Popen(
    [sys.executable, "-c",
     "import uvicorn, main; uvicorn.run(main.app, host='127.0.0.1', port=%d, log_level='warning')" % PORT],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env,
)
engine = None


def wait_ready(proc, timeout=40):
    """等到临时后端可访问；起不来就返回 False（由调用方在 finally 里收干净）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            return session.get(BASE + "/", timeout=2).status_code == 200
        except requests.RequestException:
            time.sleep(0.2)
    return False


try:
    if not wait_ready(proc):
        print(f"FAIL  临时后端启动失败（端口 {PORT}）")
        sys.exit(1)

    # ---------- 2. 新库自动建复习表 ----------
    import sqlite3
    conn = sqlite3.connect(DB_FILE)
    tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    conn.close()
    check("新库自动建出 reviews 表", "reviews" in tables, sorted(tables))
    check("reviews 含调度所需列",
          {"student_id", "subject", "knowledge", "stage", "interval", "streak",
           "next_review_at", "review_count", "correct_count"} <= cols, sorted(cols))

    rev0 = session.get(BASE + "/reviews", params={"student_id": STUDENT_ID}, timeout=10).json()
    check("初始复习清单为空", rev0["total"] == 0 and rev0["due_count"] == 0, rev0)

    engine = create_engine(env["DATABASE_URL"])

    def truth(qid):
        """从库里读标准答案，保证提交的是正确答案。"""
        with engine.connect() as conn:
            return conn.execute(
                text("select answer from questions where id = :i"), {"i": qid}
            ).scalar()

    def force_due(knowledge=None):
        """把复习时间拨回过去，模拟“到点该复习了”。"""
        sql = "UPDATE reviews SET next_review_at = '2000-01-01 00:00:00'"
        params = {}
        if knowledge:
            sql += " WHERE knowledge = :k"
            params["k"] = knowledge
        with engine.begin() as conn:
            conn.execute(text(sql), params)

    # ---------- 3. 新知识点自动建计划 ----------
    q1 = session.get(BASE + "/question",
                      params={"student_id": STUDENT_ID, "subject": "数学", "knowledge": NEW_KNOWLEDGE},
                      timeout=20).json()
    check("出题沿用填写的知识点", q1["knowledge"] == NEW_KNOWLEDGE, q1["knowledge"])
    check("返回复习状态", isinstance(q1.get("review"), dict) and "mastery" in q1["review"], q1.get("review"))
    check("首次不是复习题", q1["is_review"] is False, q1.get("is_review"))
    check("本题新知识点算到期", q1["review"]["due"] is True, q1["review"])

    s1 = session.post(BASE + "/submit",
                       json={"question_id": q1["question_id"], "answer": "肯定不对", "student_id": STUDENT_ID},
                       timeout=20).json()
    check("答错后安排 5 分钟后复习", s1["review"]["interval"] == 300, s1["review"])
    check("答错有复习提示文案", "巩固" in s1["review"]["message"], s1["review"]["message"])
    check("判分仍然正确", s1["correct"] is False)

    # ---------- 4. 到期优先复习 ----------
    q2 = session.get(BASE + "/question",
                      params={"student_id": STUDENT_ID, "subject": "数学", "knowledge": NEW_KNOWLEDGE},
                      timeout=20).json()
    check("做过又到期的知识点标为复习", q2["is_review"] is True, q2.get("is_review"))

    # 把复习时间拨到过去，模拟"到点该复习了"
    force_due(NEW_KNOWLEDGE)

    q3 = session.get(BASE + "/question",
                      params={"student_id": STUDENT_ID, "subject": "数学", "knowledge": DEFAULT_KNOWLEDGE},
                      timeout=20).json()
    check("切到别处时提示有到期复习", q3["due_count"] >= 1, q3["due_count"])
    check("复习面板列出到期的旧知识点",
          any(item["knowledge"] == NEW_KNOWLEDGE for item in q3["due_reviews"]), q3["due_reviews"])

    # ---------- 5. 连续答对 3 次升级 ----------
    # 只需要一道题：这里考的是"同一知识点连续答对"，重复提交同一题即可，
    # 不必为每次提交重新出题（出题是整套测试里最贵的一步，约 1.3s）
    q5 = session.get(BASE + "/question",
                     params={"student_id": STUDENT_ID, "subject": "数学", "knowledge": NEW_KNOWLEDGE},
                     timeout=20).json()
    answer5 = truth(q5["question_id"])

    stages = []
    for _ in range(3):
        s = session.post(BASE + "/submit",
                         json={"question_id": q5["question_id"], "answer": answer5,
                               "student_id": STUDENT_ID},
                         timeout=20).json()
        stages.append(s["review"]["stage"])
        force_due(NEW_KNOWLEDGE)

    check("连续答对 3 次升到第 1 阶段", stages == [0, 0, 1], stages)

    rev = session.get(BASE + "/reviews", params={"student_id": STUDENT_ID}, timeout=10).json()
    item = next(i for i in rev["items"] if i["knowledge"] == NEW_KNOWLEDGE)
    check("间隔拉长为第 2 级", item["interval_text"] == "30分钟后", item["interval_text"])
    check("掌握度随阶段上升", item["mastery"] == 9, item["mastery"])
    check("统计次数已累计", item["review_count"] == 4 and item["correct_count"] == 3, item)

    # 时间没到就不该再塞复习题
    with engine.begin() as conn:
        conn.execute(text("UPDATE reviews SET next_review_at = '2099-01-01 00:00:00'"))
    rev2 = session.get(BASE + "/reviews", params={"student_id": STUDENT_ID}, timeout=10).json()
    check("未到期时不进复习队列", rev2["due_count"] == 0, rev2["due_count"])
    check("总数仍包含全部知识点", rev2["total"] == 2, rev2["total"])

    # ---------- 6. 掌握度到 100 ----------
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reviews WHERE knowledge != :k"), {"k": NEW_KNOWLEDGE})
        conn.execute(text("UPDATE reviews SET stage = :s, streak = 0, next_review_at = '2000-01-01 00:00:00'"),
                     {"s": srs.MASTERED_STAGE - 1})

    # 同样是一道题连续提交 3 次，凑满 3 次连续答对
    for _ in range(3):
        s = session.post(BASE + "/submit",
                         json={"question_id": q5["question_id"], "answer": answer5,
                               "student_id": STUDENT_ID},
                         timeout=20).json()
        force_due(NEW_KNOWLEDGE)

    check("满级后标记已掌握", s["review"]["mastered"] is True and s["review"]["mastery"] == 100, s["review"])
    check("已掌握给出鼓励文案", "掌握" in s["review"]["message"], s["review"]["message"])

    rev3 = session.get(BASE + "/reviews", params={"student_id": STUDENT_ID}, timeout=10).json()
    check("已掌握不再提示复习", rev3["due_count"] == 0 and rev3["mastered_count"] == 1, rev3)

    # ---------- 7. 不破坏原有接口 ----------
    legacy = session.get(BASE + "/question",
                          params={"student_id": STUDENT_ID, "subject": "语文", "qtype": "choice"},
                          timeout=20).json()
    check("原有出题字段仍在", {"question_id", "qtype", "options", "difficulty", "stage"} <= set(legacy), sorted(legacy))
    check("语文默认知识点生效", legacy["knowledge"] == "拼音与组词", legacy["knowledge"])

finally:
    # 无论前面怎么退出都要收干净，否则残留进程会占住端口、污染下一次运行
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    if engine is not None:
        engine.dispose()          # 不释放连接池，Windows 上删不掉库文件
    for leftover in (DB_FILE, DB_FILE + "-journal", DB_FILE + "-wal", DB_FILE + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)

print("\nRESULT:", "ALL PASS" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)
