# ==============================================================
# 能力契约｜验证：训练数据自动能力诊断（AutoAbility 算法 + /api/ability/auto 接口），端口 8907
# 入口：脚本自身：python backend/verify_ability.py
# 依赖：auto_ability / ability_routes / stages / models / database（自建临时库 + 临时后端）
# 不负责：专门能力诊断 → verify_diagnostic.py；自适应学习引擎 → verify_adaptive.py
# 验证：python backend/verify_ability.py
# 被调用：verify_all.py（套件 ability）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 训练数据自动能力诊断（AutoAbility）测试。

覆盖：

  纯函数 subject_profile（加权平均难度、答错降权 0.35、40 条样本窗口、
      n<5 → warming、n==0 → unknown、confidence 题量×稳定性、
      confidence_text 高/中/低边界、难度单调 → 阶段单调、
      reason 含题量/百分比/阶段名、knowledge_focus 命中知识点）
  → 纯函数 overall_profile（三科都无数据 → 空总体画像）
  → API /api/ability/auto/{student_id}（字段齐全、三科顺序、unknown 学生不报 404、
      窗口裁剪、overall 平均分、正确率 2 位小数、接口只读不写库）
  → 真实训练闭环（练习页 /question + /submit 产生的记录直接被自动诊断消费）

用法：python backend/verify_ability.py   （自拉临时后端，端口 VERIFY_ABILITY_PORT，默认 8907）
全部通过时退出码为 0；端口被占用直接失败退出。
"""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime

PORT = int(os.getenv("VERIFY_ABILITY_PORT", "8907"))

_db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_ability.db")
for _suffix in ("", "-journal", "-wal", "-shm"):
    if os.path.exists(_db_file + _suffix):
        os.remove(_db_file + _suffix)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
os.environ["DEEPSEEK_API_KEY"] = ""      # 全程本地规则，不依赖外网

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK，打印中文/符号可能抛 UnicodeEncodeError，
# 这里统一切到 UTF-8（无法改编码时退化为替换字符，不影响断言结果）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

import auto_ability
import stages
from database import SessionLocal, engine as db_engine
from models import AnswerRecord, Base, Question

# 测试进程也要先建表：临时库是空的
Base.metadata.create_all(db_engine)

BASE = f"http://127.0.0.1:{PORT}"
http = requests.Session()

PASSED = 0
FAILED = 0


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
    else:
        FAILED += 1
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))


def rec(difficulty, correct):
    """单测直接喂给算法的记录（模仿 answer_records 的三个关键列）。"""
    return {"difficulty": difficulty, "correct": correct}


# ================= 1. 空窗口与样本窗口 =================

empty = auto_ability.subject_profile([], "数学")
check("n==0 → status=unknown", empty["status"] == "unknown", empty["status"])
check("n==0 → score=0 / stage 空 / confidence=0",
      empty["score"] == 0 and empty["stage"] == "" and empty["confidence"] == 0,
      (empty["score"], empty["stage"], empty["confidence"]))
check("n==0 → stage_label 与 knowledge_focus 为空串",
      empty["stage_label"] == "" and empty["knowledge_focus"] == "",
      (empty["stage_label"], empty["knowledge_focus"]))
check("n==0 → 星级为空星（前端仍可渲染）",
      empty["stars"] == 0 and empty["star_text"] == "☆☆☆☆☆", empty["star_text"])
check("n==0 → 建议先做几道题", "先做几道" in empty["next_step"], empty["next_step"])

window = auto_ability.subject_profile([rec(95, True)] * 5 + [rec(20, False)] * 40, "数学")
check("样本窗口只取最近 40 条", window["answer_count"] == 40, window["answer_count"])
check("窗口外的旧记录不参与计算（全错难度 20 → 20.0）", window["score"] == 20.0, window["score"])


# ================= 2. 能力分：加权平均难度 =================

even = auto_ability.subject_profile([rec(60, True)] * 7 + [rec(60, False)] * 3, "数学")
check("同一难度 7 对 3 错 → 能力分等于该难度（60.0）", even["score"] == 60.0, even["score"])

balanced = auto_ability.subject_profile([rec(90, True), rec(30, True)], "数学")
check("加权平均难度：90 对 + 30 对 → 60.0", balanced["score"] == 60.0, balanced["score"])

penalised = auto_ability.subject_profile([rec(90, False), rec(30, True)], "数学")
check("答错降权：90 错(×0.35) + 30 对(×1.0) → 45.6", penalised["score"] == 45.6, penalised["score"])
check("同一条题由答对改为答错 → 能力分下降", penalised["score"] < balanced["score"],
      (balanced["score"], penalised["score"]))
check("全错时加权平均仍是平均难度（80.0）",
      auto_ability.subject_profile([rec(80, False)] * 3, "数学")["score"] == 80.0)
check("脏数据（difficulty 为空）不崩，按最低难度算",
      auto_ability.subject_profile([{"difficulty": None, "correct": True}] * 5, "数学")["score"]
      == float(stages.MIN_DIFFICULTY))


# ================= 3. status：unknown / warming / ready =================

check("4 题 → warming（数据积累中）",
      auto_ability.subject_profile([rec(50, True)] * 4, "数学")["status"] == "warming")
check("5 题 → ready（可以下结论）",
      auto_ability.subject_profile([rec(50, True)] * 5, "数学")["status"] == "ready")
check("warming → 建议再多练几题",
      auto_ability.subject_profile([rec(50, True)] * 4, "数学")["next_step"] == "再多练几题，判断会更准")
check("ready → 建议试试更难一点的题目",
      auto_ability.subject_profile([rec(50, True)] * 5, "数学")["next_step"] == "可以试试更难一点的题目")


# ================= 4. confidence：题量 × 稳定性 =================

five = auto_ability.subject_profile([rec(50, True)] * 5, "数学")
check("5 题全对同难度 → confidence = 0.6×0.25 + 0.4×1.0 = 0.55", five["confidence"] == 0.55, five["confidence"])
check("confidence 0.55 → 文案「中」", five["confidence_text"] == "中", five["confidence_text"])

twenty = auto_ability.subject_profile([rec(50, True)] * 20, "数学")
check("20 题全对同难度 → confidence = 1.0", twenty["confidence"] == 1.0, twenty["confidence"])
check("confidence 1.0 → 文案「高」", twenty["confidence_text"] == "高", twenty["confidence_text"])
check("40 题（窗口上限）→ confidence 仍夹在 1.0",
      auto_ability.subject_profile([rec(50, True)] * 40, "数学")["confidence"] == 1.0)

single = auto_ability.subject_profile([rec(50, True)], "数学")
check("答对题少于 2 条 → consistency 记 0.5（confidence = 0.03 + 0.2 = 0.23）",
      single["confidence"] == 0.23, single["confidence"])
check("confidence 0.23 → 文案「低」", single["confidence_text"] == "低", single["confidence_text"])
check("一条都没答对 → consistency 也记 0.5（confidence = 0.6 + 0.2 = 0.8）",
      auto_ability.subject_profile([rec(50, False)] * 20, "数学")["confidence"] == 0.8)

spread = auto_ability.subject_profile([rec(20, True), rec(60, True)] * 10, "数学")
check("答对题难度标准差 20 → consistency 0.5（confidence = 0.6 + 0.2 = 0.8）",
      spread["confidence"] == 0.8, spread["confidence"])
check("答对题难度标准差 > 40 → consistency 夹到 0（confidence = 0.06）",
      auto_ability.subject_profile([rec(1, True), rec(100, True)], "数学")["confidence"] == 0.06)

check("confidence_text 边界：0.44 低 / 0.45 中 / 0.74 中 / 0.75 高",
      auto_ability.confidence_text(0.44) == "低" and auto_ability.confidence_text(0.45) == "中"
      and auto_ability.confidence_text(0.74) == "中" and auto_ability.confidence_text(0.75) == "高")


# ================= 5. 阶段、理由与知识点 =================

stage_by_difficulty = [auto_ability.subject_profile([rec(value, True)] * 5, "数学")["stage"]
                       for value in (20, 40, 60, 80)]
stage_indexes = [stages.index_of(key) for key in stage_by_difficulty]
check("难度越高 → 推断阶段单调不降", stage_indexes == sorted(stage_indexes),
      list(zip(stage_by_difficulty, stage_indexes)))
check("难度 20 与 80 推断出不同阶段", stage_indexes[0] < stage_indexes[-1], stage_indexes)
check("stage 由 stages.key_of_difficulty 反查",
      auto_ability.subject_profile([rec(60, True)] * 5, "数学")["stage"] == stages.key_of_difficulty(60.0))

profile = auto_ability.subject_profile([rec(60, True)] * 9 + [rec(60, False)] * 3, "数学")
check("reason 含题量与答对数", "最近 12 题答对 9 题" in profile["reason"], profile["reason"])
check("reason 含百分比整数", "（75%）" in profile["reason"], profile["reason"])
check("reason 含推断出的阶段名", stages.label(profile["stage"]) in profile["reason"], profile["reason"])
check("reason 含稳定答对难度", "稳定答对难度约 60" in profile["reason"], profile["reason"])
check("全错时 reason 也含题量、百分比与阶段名",
      "答对 0 题" in window["reason"] and "（0%）" in window["reason"]
      and stages.label(window["stage"]) in window["reason"], window["reason"])
check("correct_rate 保留 2 位小数",
      auto_ability.subject_profile([rec(60, True)] + [rec(60, False)] * 2, "数学")["correct_rate"] == 0.33)
check("knowledge_focus 取该科该阶段知识点",
      profile["knowledge_focus"] == stages.knowledge_of("数学", profile["stage"]),
      profile["knowledge_focus"])
check("stars / star_text 与 stages 一致",
      profile["stars"] == stages.stars(profile["score"])
      and profile["star_text"] == stages.star_text(profile["score"]),
      (profile["stars"], profile["star_text"]))
check("range = [本阶段, 下一阶段]",
      profile["range"] == list(stages.stage_range(profile["stage"])), profile["range"])

blank = [auto_ability.subject_profile([], subject) for subject in stages.SUBJECTS]
check("三科都无数据 → overall.score=0 且 stage 为空",
      auto_ability.overall_profile(blank)["score"] == 0
      and auto_ability.overall_profile(blank)["stage"] == ""
      and auto_ability.overall_profile(blank)["status"] == "unknown")


# ================= 6. 启动临时后端 =================

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


# ================= 7. 灌入日常训练答题记录（直接写库，模拟 /submit） =================

def seed(student_id, subject, count, difficulty, correct, knowledge="综合练习"):
    """直接写 answer_records，模拟今日学习页与练习页产生的训练记录。"""
    session = SessionLocal()
    for _ in range(count):
        session.add(AnswerRecord(student_id=student_id, subject=subject, knowledge=knowledge,
                                 difficulty=difficulty, correct=correct,
                                 question_id=0, submitted=""))
    session.commit()
    session.close()


def is_time_text(text):
    try:
        datetime.strptime(text, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return False
    return True


def auto(student_id):
    return http.get(f"{BASE}/api/ability/auto/{student_id}", timeout=20)


seed(1, "数学", 9, 60, True)      # 学生 1：数学 12 题（9 对 3 错，难度 60）→ ready
seed(1, "数学", 3, 60, False)
seed(1, "语文", 3, 20, True)      # 学生 1：语文只有 3 题 → warming
seed(3, "数学", 5, 95, True)      # 学生 3：前 5 条是高难度旧记录（应被窗口丢弃）
seed(3, "数学", 40, 20, False)    # 学生 3：最近 40 条全错（难度 20）


# ================= 8. 接口契约 =================

response = auto(1)
check("接口返回 200（不是 404）", response.status_code == 200, response.status_code)
body = response.json() if response.status_code == 200 else {}

check("student_id 原样返回", body.get("student_id") == 1, body.get("student_id"))
check("source=training（结论来自日常训练数据）", body.get("source") == "training", body.get("source"))
check("total_answers 等于该学生记录总数", body.get("total_answers") == 15, body.get("total_answers"))
check("generated_at 形如 2026-10-04 21:00", is_time_text(body.get("generated_at", "")),
      body.get("generated_at"))
check("三科顺序与 stages.SUBJECTS 一致",
      [item["subject"] for item in body.get("subjects", [])] == list(stages.SUBJECTS),
      [item["subject"] for item in body.get("subjects", [])])

EXPECTED_FIELDS = {"subject", "status", "score", "stage", "stage_label", "range", "stars",
                   "star_text", "confidence", "confidence_text", "answer_count",
                   "correct_count", "correct_rate", "knowledge_focus", "reason", "next_step"}
check("每科字段齐全（前后端契约字段名不变）",
      all(EXPECTED_FIELDS <= set(item) for item in body.get("subjects", [])))
check("overall 字段齐全", {"stage", "stage_label", "score", "status"} <= set(body.get("overall", {})))

math_item, chinese_item, english_item = body.get("subjects", [{}, {}, {}])

check("数学：题量与答对数取自窗口",
      math_item.get("answer_count") == 12 and math_item.get("correct_count") == 9, math_item)
check("数学：正确率 0.75（2 位小数）", math_item.get("correct_rate") == 0.75, math_item.get("correct_rate"))
check("数学：12 题 → status=ready", math_item.get("status") == "ready", math_item.get("status"))
check("数学：能力分 60.0", math_item.get("score") == 60.0, math_item.get("score"))
check("数学：阶段 4.5 / 四年级上册五",
      math_item.get("stage") == "4.5" and math_item.get("stage_label") == "四年级上册五", math_item.get("stage"))
check("数学：能力区间 [4.5, 4.6]", math_item.get("range") == ["4.5", "4.6"], math_item.get("range"))
check("数学：4 颗星", math_item.get("stars") == 4 and math_item.get("star_text") == "★★★★☆",
      math_item.get("star_text"))
check("数学：confidence 0.76 → 文案「高」",
      math_item.get("confidence") == 0.76 and math_item.get("confidence_text") == "高", math_item.get("confidence"))
check("数学：knowledge_focus 命中该阶段知识点",
      math_item.get("knowledge_focus") == stages.knowledge_of("数学", math_item.get("stage")),
      math_item.get("knowledge_focus"))
check("数学：reason 含 75% 与阶段名",
      "（75%）" in math_item.get("reason", "") and "四年级上册五" in math_item.get("reason", ""),
      math_item.get("reason"))
check("数学：next_step 建议试试更难的题",
      math_item.get("next_step") == "可以试试更难一点的题目", math_item.get("next_step"))

check("语文：3 题 → warming", chinese_item.get("status") == "warming"
      and chinese_item.get("answer_count") == 3, chinese_item.get("status"))
check("语文：warming 时照样给出分数与阶段",
      chinese_item.get("score") == 20.0 and chinese_item.get("stage") == "1.5", chinese_item)
check("语文：next_step 建议再多练几题",
      chinese_item.get("next_step") == "再多练几题，判断会更准", chinese_item.get("next_step"))

check("英语：无记录 → unknown", english_item.get("status") == "unknown"
      and english_item.get("answer_count") == 0, english_item.get("status"))
check("英语：unknown → score 0 / stage 空 / knowledge_focus 空",
      english_item.get("score") == 0 and english_item.get("stage") == ""
      and english_item.get("knowledge_focus") == "", english_item)
check("英语：unknown 也能渲染空星", english_item.get("stars") == 0
      and english_item.get("star_text") == "☆☆☆☆☆", english_item.get("star_text"))
check("英语：unknown 的 range 是空占位", english_item.get("range") == ["", ""], english_item.get("range"))
check("英语：next_step 引导先做题", "先做几道" in english_item.get("next_step", ""), english_item.get("next_step"))

overall = body.get("overall", {})
check("overall 取有数据科目的平均分（(60.0+20.0)/2 = 40.0）", overall.get("score") == 40.0, overall)
check("overall 阶段由平均分反查",
      overall.get("stage") == stages.key_of_difficulty(40.0)
      and overall.get("stage_label") == stages.label(stages.key_of_difficulty(40.0)), overall)
check("overall：只要有 ready 的科目就算 ready", overall.get("status") == "ready", overall.get("status"))


# ================= 9. 无记录学生 / 不存在的学生 / 窗口裁剪 =================

response = auto(2)
body2 = response.json()
check("无记录学生：接口仍是 200", response.status_code == 200, response.status_code)
check("无记录学生：三科都是 unknown",
      len(body2["subjects"]) == 3 and all(item["status"] == "unknown" for item in body2["subjects"]))
check("无记录学生：total_answers=0", body2["total_answers"] == 0, body2["total_answers"])
check("无记录学生：overall 为空画像",
      body2["overall"]["score"] == 0 and body2["overall"]["stage"] == ""
      and body2["overall"]["status"] == "unknown", body2["overall"])
check("无记录学生：三科都给中文下一步建议",
      all(item["next_step"] for item in body2["subjects"]))

response = auto(999999)
body3 = response.json()
check("不存在的学生也返回 200（前端可直接渲染）", response.status_code == 200, response.status_code)
check("不存在的学生：三科 unknown / 累计 0",
      len(body3["subjects"]) == 3 and body3["total_answers"] == 0
      and all(item["status"] == "unknown" for item in body3["subjects"]), body3["total_answers"])

response = auto(3)
body4 = response.json()
math3 = body4["subjects"][0]
check("45 条记录只取最近 40 条做窗口", math3["answer_count"] == 40, math3["answer_count"])
check("窗口外的高难度旧记录不影响结论（20.0）", math3["score"] == 20.0, math3["score"])
check("窗口全错 → 答对 0 题 / 正确率 0.0",
      math3["correct_count"] == 0 and math3["correct_rate"] == 0.0, math3)
check("窗口全错 → 答对题不足 2 条时 consistency 记 0.5（confidence 0.8）",
      math3["confidence"] == 0.8, math3["confidence"])
check("窗口全错 → reason 说明还没答对过", "答对 0 题" in math3["reason"], math3["reason"])
check("total_answers 统计该学生全部记录（不受窗口限制）", body4["total_answers"] == 45,
      body4["total_answers"])

session = SessionLocal()
before = session.query(AnswerRecord).count()
session.close()
auto(1)
auto(3)
auto(2)
session = SessionLocal()
after = session.query(AnswerRecord).count()
session.close()
check("接口只读：多次请求前后 answer_records 行数不变", before == after, (before, after))


# ================= 10. 真实训练闭环：/question + /submit → 自动诊断 =================

def truth_of(question_id):
    session = SessionLocal()
    row = session.query(Question).filter(Question.id == question_id).first()
    answer = row.answer if row else ""
    session.close()
    return answer


submit_total = 6
submit_correct = 0
for index in range(submit_total):
    picked = http.get(BASE + "/question",
                      params={"student_id": 4, "subject": "数学", "qtype": "choice"},
                      timeout=60).json()
    truth = truth_of(picked["question_id"])
    if index < submit_total - 1:
        given = truth                      # 前 5 题答对
    else:
        options = list((picked.get("options") or {}).keys())
        given = next((key for key in options if key != truth), "Z")   # 最后一题故意答错

    result = http.post(BASE + "/submit",
                       json={"question_id": picked["question_id"], "answer": given,
                             "student_id": 4}, timeout=30).json()
    if result.get("correct"):
        submit_correct += 1

body5 = auto(4).json()
math4 = body5["subjects"][0]
check("真实训练闭环：/submit 的记录被自动诊断消费", math4["answer_count"] == submit_total,
      math4["answer_count"])
check("真实训练闭环：答对数与 /submit 判分一致",
      math4["correct_count"] == submit_correct, (math4["correct_count"], submit_correct))
check("真实训练闭环：正确率保留 2 位小数",
      math4["correct_rate"] == round(submit_correct / submit_total, 2), math4["correct_rate"])
check("真实训练闭环：无需专门诊断即给出 ready 结论",
      math4["status"] == "ready" and bool(math4["reason"]), (math4["status"], math4["reason"]))
check("真实训练闭环：total_answers 统计该学生全部训练记录",
      body5["total_answers"] == submit_total, body5["total_answers"])


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

print(f"\n合计 {PASSED + FAILED} 项断言：PASS {PASSED} / FAIL {FAILED}")
print("RESULT:", "ALL PASS" if FAILED == 0 else "HAS FAILURES")
sys.exit(0 if FAILED == 0 else 1)
