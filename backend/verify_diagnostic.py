# ==============================================================
# 能力契约｜验证：72 阶段能力诊断（阶段推进/置信度/报告/接口 400 与 404），端口 8902
# 入口：脚本自身：python backend/verify_diagnostic.py
# 依赖：diagnostic diagnostic_bank stages models database
# 不负责：日常练习 → verify_flow.py
# 验证：python backend/verify_diagnostic.py
# 被调用：verify_all.py（套件 diagnostic）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.0 能力诊断引擎测试。

覆盖：
  阶段模型（72 阶段/推进规则/星级）→ 评分算法（能力分、置信度、能力区间）
  → 引擎状态机（连续答对升级、连续答错停在基础）→ 题库（三科 72 阶段）
  → API 全流程（start/question/answer/report）→ 学生数据隔离 → 不污染原有功能

用法：
    python backend/verify_diagnostic.py            # 自拉临时后端（端口 VERIFY_DIAG_PORT，默认 8902）

临时库 + 临时端口，不写 backend/learning.db；全部通过时退出码为 0。
"""

import os
import socket
import subprocess
import sys
import time

PORT = int(os.getenv("VERIFY_DIAG_PORT", "8902"))

_db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_diag.db")
for _suffix in ("", "-journal", "-wal", "-shm"):
    if os.path.exists(_db_file + _suffix):
        os.remove(_db_file + _suffix)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
os.environ["DEEPSEEK_API_KEY"] = ""      # 全程走本地题库，不依赖外网

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import diagnostic
import diagnostic_bank
import stages
from database import SessionLocal, engine
from models import Ability, AbilityProfile, AnswerRecord, DiagnosticRecord, Question

BASE = f"http://127.0.0.1:{PORT}"
ok = True
proc = None
http = requests.Session()


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


# ================= 1. 阶段模型 =================

keys = stages.all_keys()
check("72 个能力阶段", len(keys) == 72 and keys[0] == "1.1" and keys[-1] == "6.12", keys[:3])
check("阶段与坐标互转", stages.index_of("3.2") == 25 and stages.key_of(25) == "3.2")
check("阶段名可读", stages.label("3.2") == "三年级上册二", stages.label("3.2"))
check("阶段全名", stages.full_label("3.2") == "三年级上册二（3.2）", stages.full_label("3.2"))
check("阶段容错解析", stages.normalize_key(3.2) == "3.2" and stages.normalize_key("三年级上册二") == "3.2")

difficulties = [stages.difficulty_of(key) for key in keys]
check("阶段难度单调递增", all(a < b for a, b in zip(difficulties, difficulties[1:])), difficulties[:3])
check("难度可回推阶段", stages.key_of_difficulty(stages.difficulty_of("3.2")) == "3.2")

check("满分跳过一个大知识点的剩余两块", stages.advance("1.1", 1.0) == "1.4", stages.advance("1.1", 1.0))
check("满分跨过学年边界", stages.advance("1.11", 1.0) == "2.2", stages.advance("1.11", 1.0))
check("熟练满分跳下一大块", stages.advance("2.1", 0.9) == "2.4", stages.advance("2.1", 0.9))
check("85% 进下一块", stages.advance("2.1", 0.87) == "2.2", stages.advance("2.1", 0.87))
check("边界率向上探一级", stages.advance("3.1", 0.7) == "3.2", stages.advance("3.1", 0.7))
check("最高阶段封顶", stages.advance("6.12", 1.0) == "6.12")
check("星级文案", stages.star_text(76) == "★★★★☆", stages.star_text(76))
check("能力区间", stages.stage_range("3.1") == ("3.1", "3.2"), stages.stage_range("3.1"))
check("三科都有 72 个知识点", all(len(stages.KNOWLEDGE[s]) == 72 for s in stages.SUBJECTS))


# ================= 2. 评分算法 =================

check("置信度 10 题 = 0.5", diagnostic.confidence_of(10) == 0.5, diagnostic.confidence_of(10))
check("置信度 30 题 = 0.85", diagnostic.confidence_of(30) == 0.85, diagnostic.confidence_of(30))
check("置信度 50 题 = 0.95", diagnostic.confidence_of(50) == 0.95, diagnostic.confidence_of(50))
check("置信度 0 题为 0", diagnostic.confidence_of(0) == 0)
check(
    "置信度随题量单调不减",
    all(a <= b for a, b in zip(
        [diagnostic.confidence_of(n) for n in range(0, 80)],
        [diagnostic.confidence_of(n) for n in range(1, 81)],
    )),
)

records = [
    {"stage": "3.2", "difficulty": 55, "correct": True},
    {"stage": "3.2", "difficulty": 55, "correct": True},
    {"stage": "3.2", "difficulty": 55, "correct": False},
    {"stage": "3.1", "difficulty": 48, "correct": True},
]
ability = diagnostic.calculate_ability(records, "3.2")
check("能力画像字段齐全",
      {"stage", "score", "confidence", "range", "stars", "star_text"} <= set(ability), sorted(ability))
check("能力分在 0~100 之间", 0 <= ability["score"] <= 100, ability["score"])
check("能力区间正确", ability["range"] == ["3.2", "3.3"], ability["range"])
check("能力分随阶段单调",
      diagnostic.calculate_ability([], "5.2")["score"] > diagnostic.calculate_ability([], "1.2")["score"])
check("难题答对更值钱",
      diagnostic.weighted_rate([{"difficulty": 90, "correct": True}, {"difficulty": 30, "correct": False}])
      > 0.5)
check("知识点掌握分", diagnostic.mastery_score(8, 10) == 80, diagnostic.mastery_score(8, 10))
check("全对知识点满分", diagnostic.mastery_score(5, 5) == 100)
check("没做过题掌握分为 0", diagnostic.mastery_score(0, 0) == 0)


# ================= 3. 引擎状态机 =================

def simulate(rate_for_stage):
    """按"每个阶段答对几成"跑完一场诊断，返回最终阶段与状态。"""
    state = diagnostic.new_state()
    guard = 0

    while not state["finished"] and guard < 40:
        guard += 1
        rate = rate_for_stage(state["stage"])
        hits = int(round(rate * diagnostic.QUESTIONS_PER_STAGE))
        for index in range(diagnostic.QUESTIONS_PER_STAGE):
            diagnostic.record_answer(state, index < hits)
        diagnostic.evaluate_stage(state)

    return diagnostic.final_key(state), state


final_all_right, state_right = simulate(lambda stage: 1.0)
check("全部答对 → 能力持续前进", stages.index_of(final_all_right) >= stages.index_of("3.1"), final_all_right)
check("全部答对触及题量上限", state_right["total"] == diagnostic.MAX_QUESTIONS, state_right["total"])
check("全部答对的置信度很高", diagnostic.confidence_of(state_right["total"]) >= 0.95)

final_all_wrong, state_wrong = simulate(lambda stage: 0.0)
check("全部答错 → 停留在一年级基础", final_all_wrong == "1.1", final_all_wrong)
check("全部答错只测一组题", state_wrong["total"] == diagnostic.QUESTIONS_PER_STAGE, state_wrong["total"])
check("全部答错的置信度较低", diagnostic.confidence_of(state_wrong["total"]) < 0.5)

# 模拟用户示例：低阶段满分 → 一路爬升；到 3.1 掉到边界率、再降一级后收尾
boundary_index = stages.index_of("3.1")


def sample_rate(stage):
    index = stages.index_of(stage)
    if index < boundary_index:
        return 1.0
    return 0.7 if index == boundary_index else 0.5


final_sample, state_sample = simulate(sample_rate)
check("阶梯式作答停在能力边界",
      stages.index_of("3.1") <= stages.index_of(final_sample) <= stages.index_of("3.4"),
      final_sample)
check("阶梯式作答记录了每个阶段", len(state_sample["history"]) >= 3, len(state_sample["history"]))
check("边界阶段被记录为候选", state_sample["boundary"] == final_sample, state_sample["boundary"])


# ================= 4. 题库 =================

for subject in stages.SUBJECTS:
    missing = []
    for key in keys:
        question = diagnostic_bank.build_question(subject, key)
        if not question:
            missing.append(key)
            continue
        options = question["options"]
        values = list(options.values())
        if len(options) != 4 or len(set(values)) != 4 or options.get(question["answer"]) is None:
            missing.append(key)
    check(f"{subject} 72 个阶段都能出题且选项合法", not missing, missing)

math_target = stages.knowledge_of("数学", "3.2")
check("数学出题带知识点", diagnostic_bank.build_question("数学", "3.2")["knowledge"] == math_target)

# 数学生成器带随机参数，多跑几轮确认不会偶尔凑不出 4 个合法选项
bad = []
for key in keys:
    for _ in range(40):
        question = diagnostic_bank.build_question("数学", key)
        if not question:
            bad.append(key)
            break
check("数学生成器 72 阶段 × 40 次全部合法", not bad, bad)

sizes = {subject: min(diagnostic_bank.bank_size(subject, key) for key in keys)
         for subject in ("语文", "英语")}
check("语文/英语每阶段至少 5 道题", all(size >= 5 for size in sizes.values()), sizes)


# ================= 5. 启动临时后端 =================

def port_in_use():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
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


def answer_of(question_id):
    """测试脚本可以直接查库拿答案（前端拿不到）。"""
    db = SessionLocal()
    row = db.query(Question).filter(Question.id == question_id).first()
    letter = row.answer if row else ""
    db.close()
    return letter


def start_diagnostic(student_id, subject="数学"):
    response = http.post(BASE + "/api/diagnostic/start",
                         json={"student_id": student_id, "subject": subject}, timeout=20)
    return response.json()


def play(student_id, subject="数学", always_correct=True, max_questions=80):
    """把一场诊断玩完，返回 (最终结果, 作答明细)。"""
    started = start_diagnostic(student_id, subject)
    session_id = started["session_id"]
    detail = []
    final = None

    for _ in range(max_questions):
        question = http.get(BASE + "/api/diagnostic/question",
                            params={"session_id": session_id}, timeout=30).json()
        if question.get("finished"):
            final = question
            break

        truth = answer_of(question["question_id"])
        if always_correct:
            given = truth
        else:
            options = question.get("options") or {}
            given = next((key for key in options if key != truth), "Z")

        result = http.post(BASE + "/api/diagnostic/answer",
                           json={"session_id": session_id, "question_id": question["question_id"],
                                 "answer": given}, timeout=20).json()
        result["_question"] = question
        result["_truth"] = truth
        detail.append(result)

        if result.get("finished"):
            final = result
            break

    return started, final, detail


# ================= 6. API 契约 =================

root = http.get(BASE + "/", timeout=10).json()


def version_tuple(text):
    try:
        return tuple(int(part) for part in str(text).split("."))
    except ValueError:
        return (0,)


check("版本不低于 2.2（能力诊断已上线）", version_tuple(root["version"]) >= (2, 2), root["version"])
check("首页列出能力诊断", any("诊断" in item for item in root["features"]))

stage_dict = http.get(BASE + "/api/diagnostic/stages", timeout=10).json()
check("阶段字典返回 72 个阶段", stage_dict["total"] == 72)

no_report = http.get(BASE + "/api/diagnostic/report",
                     params={"student_id": 2, "subject": "语文"}, timeout=10).json()
check("没做过诊断时报告提示未诊断", no_report["available"] is False, no_report)

bad_subject = http.post(BASE + "/api/diagnostic/start",
                        json={"student_id": 1, "subject": "科学"}, timeout=10)
check("非法科目返回 400", bad_subject.status_code == 400, bad_subject.status_code)

started = start_diagnostic(1, "数学")
check("开始诊断返回 session_id", isinstance(started.get("session_id"), int), started)
check("起点是一年级基础", started["stage"] == "1.1", started["stage"])

first = http.get(BASE + "/api/diagnostic/question",
                 params={"session_id": started["session_id"]}, timeout=30).json()
check("诊断题不下发答案", "answer" not in first and "analysis" not in first, sorted(first))
check("诊断题给出 4 个选项", len(first.get("options") or {}) == 4, first.get("options"))
check("诊断题带阶段与知识点", bool(first.get("stage")) and bool(first.get("knowledge")))
check("进度带当前阶段与题量", first["progress"]["stage"] == "1.1" and first["progress"]["total"] >= 10,
      first["progress"])

again = http.get(BASE + "/api/diagnostic/question",
                 params={"session_id": started["session_id"]}, timeout=30).json()
check("未作答时重复取题返回同一道", again["question_id"] == first["question_id"])

mismatch = http.post(BASE + "/api/diagnostic/answer",
                     json={"session_id": started["session_id"], "question_id": 999999, "answer": "A"},
                     timeout=20)
check("乱提交题目返回 400", mismatch.status_code == 400, mismatch.status_code)

missing = http.get(BASE + "/api/diagnostic/question", params={"session_id": 999999}, timeout=10)
check("不存在的会话返回 404", missing.status_code == 404, missing.status_code)


# ================= 7. 学生 A：连续答对 → 自动升级 =================

db = SessionLocal()
answers_before = db.query(AnswerRecord).count()
ability_before = db.query(Ability).count()
db.close()

started_a, final_a, detail_a = play(1, "数学", always_correct=True)
check("学生 A 诊断结束", bool(final_a) and final_a.get("finished"), final_a)
check("学生 A 答对越多阶段越高", bool(detail_a) and detail_a[0]["stage"] != detail_a[-1]["stage"],
      (detail_a[0]["stage"], detail_a[-1]["stage"]) if detail_a else None)
check("学生 A 阶段一路上升", stages.index_of(final_a["final_stage"]) >= stages.index_of("3.1"),
      final_a.get("final_stage"))
check("学生 A 能力分合理", 0 < final_a["final_score"] <= 100, final_a.get("final_score"))
check("学生 A 有星级与区间", bool(final_a["star_text"]) and bool(final_a["range_label"]), final_a)
check("学生 A 中途题目不带答案",
      all("answer" not in item["_question"] for item in detail_a))

report_a = http.get(BASE + "/api/diagnostic/report",
                    params={"student_id": 1, "subject": "数学"}, timeout=20).json()
check("学生 A 报告可用", report_a["available"] is True, report_a.get("message"))
check("报告含能力阶段与区间", bool(report_a["stage"]) and bool(report_a["range_label"]), report_a.get("stage"))
check("报告含知识点细分", len(report_a["knowledge"]) >= 1, report_a.get("knowledge"))
check("报告含优势知识点", bool(report_a["strengths"]))
check("全对时没有假短板", report_a["weaknesses"] == [], report_a.get("weaknesses"))
check("报告含学习建议", bool(report_a["advice"]), report_a.get("advice"))
check("报告含测试过程", len(report_a["history"]) >= 2, len(report_a.get("history") or []))


# ================= 8. 学生 B：连续答错 → 停在基础 + 数据隔离 =================

started_b, final_b, detail_b = play(2, "数学", always_correct=False)
check("学生 B 诊断结束", bool(final_b) and final_b.get("finished"), final_b)
check("学生 B 停留在一年级基础", final_b["final_stage"] == "1.1", final_b.get("final_stage"))
check("学生 B 只测一组题", len(detail_b) == diagnostic.QUESTIONS_PER_STAGE, len(detail_b))
check("学生 B 置信度低于学生 A", final_b["confidence"] < final_a["confidence"],
      (final_b["confidence"], final_a["confidence"]))
check("结束后进度条走满", final_b["progress"]["answered"] == final_b["progress"]["total"],
      final_b["progress"])

report_b = http.get(BASE + "/api/diagnostic/report",
                    params={"student_id": 2, "subject": "数学"}, timeout=20).json()
check("学生 B 也生成自己的画像", report_b["available"] is True, report_b.get("message"))
check("全错时有明确的待提升知识点", bool(report_b["weaknesses"]), report_b.get("weaknesses"))
check("两个学生能力阶段不同（数据隔离）", report_a["stage"] != report_b["stage"],
      (report_a["stage"], report_b["stage"]))
check("两个学生画像各自独立", report_a["student_id"] == 1 and report_b["student_id"] == 2)

db = SessionLocal()
records_a = db.query(DiagnosticRecord).filter(DiagnosticRecord.student_id == 1).count()
records_b = db.query(DiagnosticRecord).filter(DiagnosticRecord.student_id == 2).count()
sessions_a = [row.session_id for row in db.query(DiagnosticRecord)
              .filter(DiagnosticRecord.student_id == 1).all()]
sessions_b = [row.session_id for row in db.query(DiagnosticRecord)
              .filter(DiagnosticRecord.student_id == 2).all()]
profile_a = db.query(AbilityProfile).filter(AbilityProfile.student_id == 1,
                                            AbilityProfile.subject == "数学").first()
profile_b = db.query(AbilityProfile).filter(AbilityProfile.student_id == 2,
                                            AbilityProfile.subject == "数学").first()
mastery_a = db.query(AbilityProfile).filter(AbilityProfile.student_id == 1).count()
answers_after = db.query(AnswerRecord).count()
ability_after = db.query(Ability).count()
db.close()

check("学生 A 的答题记录数与题量一致", records_a == len(detail_a), (records_a, len(detail_a)))
check("学生 B 的答题记录数与题量一致", records_b == len(detail_b), (records_b, len(detail_b)))
check("两场诊断的记录互不混用", set(sessions_a).isdisjoint(set(sessions_b)),
      (set(sessions_a), set(sessions_b)))
check("能力画像分别落库", profile_a is not None and profile_b is not None)
check("画像阶段与报告一致",
      profile_a.ability_stage == report_a["stage"] and profile_b.ability_stage == report_b["stage"])
check("学生 A 只有数学画像", mastery_a == 1, mastery_a)
check("诊断不写常规答题记录", answers_after == answers_before, (answers_before, answers_after))
check("诊断不改动日常能力分", ability_after == ability_before, (ability_before, ability_after))


# ================= 9. 会话收尾与异常路径 =================

after_finish = http.get(BASE + "/api/diagnostic/question",
                        params={"session_id": started_b["session_id"]}, timeout=20).json()
check("结束后取题返回 finished", after_finish.get("finished") is True, after_finish)
check("结束后给出报告地址", "report" in (after_finish.get("report_url") or ""), after_finish.get("report_url"))

late_answer = http.post(BASE + "/api/diagnostic/answer",
                        json={"session_id": started_b["session_id"],
                              "question_id": detail_b[-1]["_question"]["question_id"], "answer": "A"},
                        timeout=20)
check("结束后再作答返回 400", late_answer.status_code == 400, late_answer.status_code)

session_detail = http.get(BASE + "/api/diagnostic/session",
                          params={"session_id": started_b["session_id"]}, timeout=10).json()
check("会话详情可查", session_detail["status"] == "finished" and session_detail["history"],
      session_detail.get("status"))

profiles = http.get(BASE + "/api/diagnostic/profiles", params={"student_id": 1}, timeout=10).json()
check("画像列表按科目返回", len(profiles["profiles"]) == 1, profiles)

# 前端页面由后端静态挂载（/app/...），确认小朋友真的打得开
for page in ("diagnostic.html", "diagnostic_test.html", "diagnostic_report.html"):
    response = http.get(f"{BASE}/app/{page}", timeout=10)
    check(f"诊断页面可访问 {page}",
          response.status_code == 200 and "<html" in response.text.lower(), response.status_code)

for asset in ("diagnostic.js", "diagnostic_test.js", "diagnostic_report.js", "style.css"):
    response = http.get(f"{BASE}/app/{asset}", timeout=10)
    check(f"诊断资源可访问 {asset}", response.status_code == 200 and len(response.text) > 200,
          response.status_code)

english_report = http.get(BASE + "/api/diagnostic/report",
                          params={"student_id": 1, "subject": "英语"}, timeout=10).json()
check("未测科目不串数据", english_report["available"] is False)

# 诊断画像生效后，常规出题难度应围绕"下一个能力阶段"
practice = http.get(BASE + "/question",
                    params={"student_id": 1, "subject": "数学", "qtype": "choice"}, timeout=60).json()
check("诊断后常规出题带能力上下文", isinstance(practice.get("ability"), dict), practice.get("ability"))
check("常规出题难度跟随能力画像",
      abs(practice["difficulty"] - int(round(0.5 * practice["ability"]["score"]
                                             + 0.5 * stages.difficulty_of(practice["ability"]["target_stage"])))) <= 1,
      {"difficulty": practice["difficulty"], "ability": practice["ability"]})
check("常规出题仍然不下发答案", "answer" not in practice)


# ================= 收尾 =================

if proc is not None:
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
