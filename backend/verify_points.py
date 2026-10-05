# ==============================================================
# 能力契约｜积分套件：规则分值 / 答对与打卡幂等 / 计划做完后继续练 / 任务收工 / 接口 / 学生隔离
# 入口：check / schema_case / rule_case / reward_case / answer_case / free_case / task_case / checkin_case /
#       login_case /
#       http_case / isolation_case / wiring_case / failure_case / start_server / finish / main
# 依赖：os sys time json socket sqlite3 subprocess、requests、points、points_rewards、points_routes、database、models
# 不负责：修 bug（只记录缺陷）→ Lead；积分规则与商城占位数据 → points.py；其它套件 → verify_all.py
# 验证：python backend/verify_points.py（端口 8915 · 临时库 _verify_points.db）
# 被调用：人工 / verify_all.py（套件 key = points）
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================

"""V2.8 积分系统门禁套件（SPEC m00845 · key=points · port=8915）。

覆盖：student_point / point_record 两张新表与索引建出 / 规则分值（答对 2 · 打卡 10 · 继续练 3 · 收工 5）/
答对一题自动记分并顺带当日打卡（第二次不再重复）/ 答错不加分 / 当天任务全 done 后继续答对额外 +3 /
任务收工按 task_id 幂等（status 不是 done 不给分）/ 打卡必须先答对过一题 / 接口真实 HTTP 断言与 404 /
A·B 学生隔离 / 静态接线（main.py 注册路由 + /submit 钩子、task_routes 两个完成端点挂钩）/
第一版奖励行为表（积分明细 14 条 · 区间分值 · 星级 · 三态）/ 每日首次登录与「任务全部收工自动打卡」/
失败路径（未知学生 404、非法学生号 422）。

纪律：临时库 _verify_points.db（跑完删除）· 绝不写 learning.db · 端口被占用故意失败（不换端口）。
"""

import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

BACKEND = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BACKEND, "_verify_points.db")
PORT = int(os.getenv("VERIFY_POINTS_PORT", "8915"))
BASE = "http://127.0.0.1:%d" % PORT
NEW_TABLES = ("student_point", "point_record")
STUDENT_A, STUDENT_B, STUDENT_C, STUDENT_D, STUDENT_E = 1, 2, 3, 4, 5
STUDENT_F = 6

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

import points  # noqa: E402
import points_rewards  # noqa: E402
from database import SessionLocal, engine as db_engine, ensure_schema  # noqa: E402
from models import Base, DailyLearningTask, PointRecord, Student, StudentPoint  # noqa: E402

PASSED = 0
FAILED = 0


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


def q(text):
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(text).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def index_names(table):
    return {row[1]: row[2] for row in q('PRAGMA index_list("%s")' % table)}


# ---------------------------------------------------------------- 建库与种子

def setup_db():
    Base.metadata.create_all(db_engine)
    ensure_schema(Base)
    db = SessionLocal()
    try:
        if not db.query(Student).filter(Student.id == STUDENT_A).first():
            for sid, name in ((STUDENT_A, "朵朵"), (STUDENT_B, "童童")):
                db.add(Student(id=sid, name=name, avatar="girl", grade=1,
                               created_at=datetime.now()))
        db.commit()
    finally:
        db.close()


def schema_case():
    names = {row[0] for row in q("select name from sqlite_master where type='table'")}
    check("积分：student_point / point_record 两张新表由 create_all 建出",
          all(item in names for item in NEW_TABLES),
          sorted(item for item in NEW_TABLES if item not in names) or "两张都在")
    accounts = index_names("student_point")
    records = index_names("point_record")
    check("积分：一个学生只有一个积分账户（student_id 唯一索引）",
          accounts.get("ix_point_account_student") == 1, accounts)
    check("积分：流水按学生+日期建索引、once_key 唯一（重复事件只记一次）",
          "ix_point_record_student_date" in records
          and records.get("ix_point_record_once") == 1, records)


def rule_case():
    rules = {item["event"]: item for item in points.RULES}
    check("积分：五条规则分值 = 答对 2 / 打卡 10 / 登录 10 / 继续练 3 / 收工 5",
          (rules.get("answer_correct", {}).get("points") == 2
           and rules.get("daily_checkin", {}).get("points") == 10
           and rules.get("daily_login", {}).get("points") == 10
           and rules.get("free_practice", {}).get("points") == 3
           and rules.get("task_done", {}).get("points") == 5
           and len(points.RULES) == 5),
          {key: value.get("points") for key, value in rules.items()})
    items = points.SHOP_ITEMS
    check("积分：商城占位五件道具（iPad 时间 / 玩具 20·50·100 / 蛋仔充值）",
          len(items) == 5 and [item["key"] for item in items] ==
          ["ipad_time", "toy_20", "toy_50", "toy_100", "eggy_recharge"],
          [item["key"] for item in items])
    check("积分：兑换比例先占位（SHOP_ENABLED=False，不给兑换按钮）",
          points.SHOP_ENABLED is False and "占位" in points.SHOP_NOTE, points.SHOP_NOTE)


def reward_case():
    """第一版奖励行为表（积分明细）：只描述规则、自己不判定，分值口径必须与需求一致。"""
    rows = points_rewards.reward_table()
    check("积分明细：第一版共 14 条奖励行为", len(rows) == 14, len(rows))
    check("积分明细：第一条是最核心的「首次真正掌握一个知识点 +100 ★★★★★」",
          rows[0]["label"] == "首次真正掌握一个知识点"
          and (rows[0]["points_min"], rows[0]["points_max"]) == (100, 100)
          and rows[0]["stars"] == 5 and rows[0]["note"] == "最核心学习成果", rows[0])
    spans = {row["key"]: (row["points_min"], row["points_max"]) for row in rows}
    check("积分明细：区间分值保持原样（迁移题 60~80 / 前置修复 40~60 / 复习 20~40 / 提示后 10~20 / 适龄题 2~5）",
          spans.get("transfer_question") == (60, 80)
          and spans.get("prerequisite_fix") == (40, 60)
          and spans.get("review_success") == (20, 40)
          and spans.get("hint_then_solo") == (10, 20)
          and spans.get("answer_correct") == (2, 5)
          and spans.get("mastered_repeat") == (0, 1), spans)
    check("积分明细：单点分值保持原样（100 / 80 / 80 / 70 / 50 / 40 / 30）",
          [spans.get(key) for key in ("first_mastery", "deep_mastery_upgrade", "wrong_recovery_done",
                                      "memory_after_days", "teach_phoebe", "recall_without_hint",
                                      "daily_plan_done")]
          == [(100, 100), (80, 80), (80, 80), (70, 70), (50, 50), (40, 40), (30, 30)])
    stars = {row["key"]: row["stars"] for row in rows}
    check("积分明细：星级按重要程度（5★ 核心成果 / 2★ 即时反馈 / 1★ 防刷分 / 0★ 屏幕时间）",
          stars.get("first_mastery") == 5 and stars.get("answer_correct") == 2
          and stars.get("mastered_repeat") == 1 and stars.get("screen_time") == 0, stars)
    check("积分明细：登录 / 停留 / 点击永远 0 分（标成 never）",
          spans.get("screen_time") == (0, 0)
          and [row["state"] for row in rows if row["key"] == "screen_time"] == ["never"])
    check("积分明细：只有「普通适龄题独立答对」已经在自动记分，事件与 points.RULES 对得上",
          len(points_rewards.rewards_of("live")) == 1
          and points_rewards.rewards_of("live")[0]["event"] == "answer_correct"
          and points.RULE_POINTS.get("answer_correct") == 2,
          points_rewards.rewards_of("live"))
    check("积分明细：还没接判定的 12 条标成 planned（不虚报分数）",
          len(points_rewards.rewards_of("planned")) == 12,
          len(points_rewards.rewards_of("planned")))
    check("积分明细：分值文案（单点 / 区间 / 零分）",
          [points_rewards.points_text(row) for row in rows][:2] == ["+100", "+80"]
          and points_rewards.points_text(rows[-1]) == "0 分")
    check("积分明细：三态文案齐全且都是中文",
          set(points_rewards.REWARD_STATES) == {"live", "planned", "never"}
          and all(points_rewards.REWARD_STATES.values()))


def answer_case():
    db = SessionLocal()
    try:
        first = points.award_after_answer(db, STUDENT_A, correct=True,
                                          subject="数学", knowledge="两位数乘法")
        second = points.award_after_answer(db, STUDENT_A, correct=True,
                                           subject="数学", knowledge="两位数乘法")
        wrong = points.award_after_answer(db, STUDENT_A, correct=False,
                                          subject="数学", knowledge="两位数乘法")
        balance = points.balance_of(db, STUDENT_A)
        info = points.summary(db, STUDENT_A)
    finally:
        db.close()
    check("积分：第一次答对 = +2（打卡不再由「答对一题」触发）",
          first.get("gained") == 2
          and [item["event"] for item in first.get("events") or []] == ["answer_correct"], first)
    check("积分：当天第二次答对还是 +2",
          second.get("gained") == 2
          and [item["event"] for item in second.get("events") or []] == ["answer_correct"], second)
    check("积分：答错一题不加分", wrong.get("gained") == 0, wrong)
    check("积分：余额 = 2 + 2 = 4，今天还没打卡（小任务没做完）",
          balance == 4 and info.get("checked_in") is False and info.get("streak") == 0,
          "balance=%s checked_in=%s streak=%s" % (balance, info.get("checked_in"),
                                                  info.get("streak")))
    check("积分：流水与今日合计对得上（今日 4 分 · 2 条流水）",
          info.get("today_points") == 4 and info.get("today_count") == 2,
          "today=%s count=%s" % (info.get("today_points"), info.get("today_count")))


def free_case():
    """「超时自由学习」：当天任务全部收工后继续答对，额外 +3。"""
    with SessionLocal() as db:
        before = points.award_after_answer(db, STUDENT_C, correct=True)
    with SessionLocal() as db:
        db.add(DailyLearningTask(student_id=STUDENT_C, date=points.today_text(),
                                 task_type="new_learning", title="数学 · 新知识", subject="数学",
                                 knowledge_id="两位数乘法", target_count=2, complete_count=2,
                                 duration_minutes=10, target_minutes=10, status="done",
                                 priority=1, source="plan", created_time=datetime.now()))
        db.commit()
    with SessionLocal() as db:
        after = points.award_after_answer(db, STUDENT_C, correct=True)
        finished = points.plan_finished(db, STUDENT_C, points.today_text())
    check("积分：当天任务全 done 后继续答对 = 答对 2 + 打卡 10 + 继续练 3",
          before.get("gained") == 2 and after.get("gained") == 15
          and sorted(item["event"] for item in after.get("events") or [])
          == ["answer_correct", "daily_checkin", "free_practice"]
          and finished is True,
          "%s → %s" % (before.get("gained"), after.get("gained")))
    with SessionLocal() as db:
        untouched = points.plan_finished(db, STUDENT_B, points.today_text())
    check("积分：当天没有任务时不算「继续练」（别的学生互不影响）",
          untouched is False, untouched)


def task_case():
    with SessionLocal() as db:
        pending = points.award_task_done(db, STUDENT_D, 71, status="doing")
        done = points.award_task_done(db, STUDENT_D, 71, status="done")
        again = points.award_task_done(db, STUDENT_D, 71, status="done")
        balance = points.balance_of(db, STUDENT_D)
    check("积分：任务没做完（status=doing）不给收工分",
          pending.get("awarded") is False and pending.get("reason") == "not_done", pending)
    check("积分：一项任务收工 +5，同一项重复调用不再加（幂等）",
          done.get("points") == 5 and again.get("awarded") is False
          and again.get("reason") == "already" and balance == 5,
          "done=%s again=%s balance=%s" % (done.get("points"), again.get("reason"), balance))
    # 当天小任务全部收工那一刻：收工分 + 每日打卡一起到（打卡由系统记，不需要孩子点按钮）
    with SessionLocal() as db:
        db.add(DailyLearningTask(student_id=STUDENT_D, date=points.today_text(),
                                 task_type="review", title="语文 · 复习恢复", subject="语文",
                                 knowledge_id="拼音与声调", target_count=1, complete_count=1,
                                 duration_minutes=5, target_minutes=5, status="done",
                                 priority=2, source="plan", created_time=datetime.now()))
        db.commit()
    with SessionLocal() as db:
        finished = points.plan_finished(db, STUDENT_D, points.today_text())
        last = points.award_task_done(db, STUDENT_D, 72, status="done")
        balance = points.balance_of(db, STUDENT_D)
    check("积分：当天小任务全部收工后自动记「每日打卡」（孩子不用点按钮）",
          finished is True and last.get("points") == 5
          and (last.get("checkin") or {}).get("awarded") is True
          and (last.get("checkin") or {}).get("points") == 10 and balance == 20,
          "balance=%s checkin=%s" % (balance, last.get("checkin")))


def checkin_case():
    """每日打卡：小任务全部收工后自动记一次；没做完只提示，不给分。"""
    with SessionLocal() as db:
        unfinished = points.checkin(db, STUDENT_E)
    check("积分：小任务没做完就打卡 → 提示先做完、不给分",
          unfinished.get("awarded") is False and unfinished.get("reason") == "need_finish"
          and "小任务做完" in str(unfinished.get("message") or ""), unfinished.get("message"))
    with SessionLocal() as db:
        db.add(DailyLearningTask(student_id=STUDENT_E, date=points.today_text(),
                                 task_type="new_learning", title="数学 · 新知识", subject="数学",
                                 knowledge_id="两位数乘法", target_count=2, complete_count=2,
                                 duration_minutes=10, target_minutes=10, status="done",
                                 priority=1, source="plan", created_time=datetime.now()))
        db.commit()
    with SessionLocal() as db:
        first = points.checkin(db, STUDENT_E)
        second = points.checkin(db, STUDENT_E)
        balance = points.balance_of(db, STUDENT_E)
    check("积分：任务全做完后自动打卡 +10（打卡成功！）",
          first.get("awarded") is True and first.get("points") == 10
          and first.get("message") == "打卡成功！", first.get("message"))
    check("积分：同一天再打卡提示今天已打过（幂等，不加分）",
          second.get("awarded") is False and second.get("message") == "今天已经打过卡啦",
          second.get("message"))
    check("积分：打卡分只记一次（学生 E 余额 = 10）", balance == 10, balance)


def login_case():
    """每日首次登录奖励：一天只记一次（幂等）。"""
    with SessionLocal() as db:
        first = points.login(db, STUDENT_F)
        second = points.login(db, STUDENT_F)
        balance = points.balance_of(db, STUDENT_F)
    check("积分：每日首次登录 +10",
          first.get("awarded") is True and first.get("points") == 10
          and "+10" in str(first.get("message") or ""), first.get("message"))
    check("积分：同一天再登录不再加（幂等，提示今天已经领过）",
          second.get("awarded") is False and second.get("reason") == "already"
          and "已经领过" in str(second.get("message") or ""), second.get("message"))
    check("积分：登录奖励只记一次（学生 F 余额 = 10）", balance == 10, balance)


def isolation_case():
    with SessionLocal() as db:
        a = points.balance_of(db, STUDENT_A)
        b = points.balance_of(db, STUDENT_B)
        e = points.balance_of(db, STUDENT_E)
    check("积分：A·B·E 学生互不串味（B 没做过题余额还是 0）",
          a == 4 and b == 0 and e == 10, "A=%s B=%s E=%s" % (a, b, e))


def http_case():
    data = requests.get(BASE + "/api/points/%d" % STUDENT_A, timeout=5).json()
    fields = {"student_id", "date", "balance", "total_earned", "today_points", "today_count",
              "checked_in", "streak", "rules", "shop", "records",
              "rewards", "reward_version", "reward_states"}
    check("接口：GET /api/points/{id} 字段齐全（余额 / 今日 / 打卡 / 规则 / 商城 / 流水）",
          fields <= set(data) and data.get("balance") == 4, sorted(fields - set(data)) or "齐全")
    detail = data.get("rewards") or []
    check("接口：积分总览带第一版奖励行为明细（14 条 · 规则版本 · 三态文案）",
          len(detail) == 14 and data.get("reward_version") == "第一版"
          and set(data.get("reward_states") or {}) == {"live", "planned", "never"},
          "%s 条 / %s" % (len(detail), data.get("reward_version")))
    shop = data.get("shop") or {}
    check("接口：首页商城是占位（enabled=False · 五件道具都买不了）",
          shop.get("enabled") is False and len(shop.get("items") or []) == 5
          and all(item.get("affordable") is False for item in shop.get("items") or []),
          [item.get("label") for item in (shop.get("items") or [])])
    check("接口：流水带上「何时 + 哪类 + 多少分」",
          bool(data.get("records")) and
          set(data["records"][0]) >= {"date", "event", "label", "points", "time"},
          data.get("records", [])[:1])
    one_shop = requests.get(BASE + "/api/points/%d/shop" % STUDENT_A, timeout=5).json()
    check("接口：GET /api/points/{id}/shop 只给占位道具与说明",
          len(one_shop.get("items") or []) == 5 and "占位" in str(one_shop.get("note") or ""),
          one_shop.get("note"))
    again = requests.post(BASE + "/api/points/%d/checkin" % STUDENT_A, timeout=5).json()
    check("接口：小任务没做完时打卡 → 提示「先把今天的小任务做完」（need_finish）",
          again.get("awarded") is False and again.get("reason") == "need_finish"
          and "小任务做完" in str(again.get("message") or ""), again.get("message"))
    first_login = requests.post(BASE + "/api/points/%d/login" % STUDENT_B, timeout=5).json()
    second_login = requests.post(BASE + "/api/points/%d/login" % STUDENT_B, timeout=5).json()
    check("接口：POST /api/points/{id}/login 首次 +10、第二次幂等（已经领过）",
          first_login.get("awarded") is True and first_login.get("points") == 10
          and second_login.get("awarded") is False
          and "已经领过" in str(second_login.get("message") or ""),
          "%s / %s" % (first_login.get("message"), second_login.get("message")))


def wiring_case():
    with open(os.path.join(BACKEND, "main.py"), "r", encoding="utf-8") as handle:
        main_src = handle.read()
    with open(os.path.join(BACKEND, "task_routes.py"), "r", encoding="utf-8") as handle:
        task_src = handle.read()
    check("接线：main.py 注册积分路由（points_router）",
          "from points_routes import router as points_router" in main_src
          and "app.include_router(points_router)" in main_src)
    check("接线：/submit 判分后给答对的孩子记分（积分出错不影响判分）",
          "points.award_after_answer" in main_src
          and "积分出问题绝不影响判分返回" in main_src)
    check("接线：两个任务完成端点都挂上「收工加分」",
          task_src.count("_award_task_points(") >= 3
          and "points.award_task_done" in task_src
          and "积分出问题绝不影响任务接口返回" in task_src,
          task_src.count("_award_task_points("))


def failure_case():
    unknown = requests.get(BASE + "/api/points/999", timeout=5)
    check("失败路径：查不存在的学生 → 404 且给出中文提示",
          unknown.status_code == 404, unknown.status_code)
    raw = requests.get(BASE + "/api/points/abc", timeout=5)
    check("失败路径：学生号不是数字 → 422（不 500）",
          raw.status_code == 422, raw.status_code)


# ---------------------------------------------------------------- 临时后端

def port_in_use():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        return sock.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        sock.close()


def start_server():
    """起一个只带积分路由的临时后端（不依赖 main.py 里其它模块是否可离线）。"""
    if port_in_use():
        check("端口未占用（%d 被占用则故意失败，不自动换端口）" % PORT, False, "端口已被占用")
        finish(None)
    code = (
        "import uvicorn\n"
        "from fastapi import FastAPI\n"
        "import points_routes\n"
        "app = FastAPI(title='verify-points')\n"
        "app.include_router(points_routes.router)\n"
        "@app.get('/')\n"
        "def _root():\n"
        "    return {'ok': True, 'suite': 'points'}\n"
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
                check("临时后端启动（端口 %d，只带 /api/points 路由）" % PORT, True)
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
    setup_db()
    schema_case()
    rule_case()
    reward_case()
    answer_case()
    free_case()
    task_case()
    checkin_case()
    login_case()
    isolation_case()
    proc = start_server()
    try:
        http_case()
        failure_case()
        wiring_case()
    finally:
        print("耗时 %.1fs" % (time.time() - start))
        finish(proc)


if __name__ == "__main__":
    main()
