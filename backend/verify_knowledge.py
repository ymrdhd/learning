# ==============================================================
# 能力契约｜验证：知识掌握/错因/错题本 + 掌握度写入口 + 题目审核（含图片依赖拦截） + V2.2→V2.3 迁移回填，端口 8904
# 入口：脚本自身：python backend/verify_knowledge.py
# 依赖：mastery error_analysis knowledge_tree wrong_book validator deepseek stages models database
# 不负责：复习/自适应 → verify_memory.py / verify_adaptive.py
# 验证：python backend/verify_knowledge.py
# 被调用：verify_all.py（套件 knowledge）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 知识掌握模型 + 错因分析 + 错题本 + 题目审核 测试。

覆盖：
  掌握度算法（题量收缩、连续错误降档、复习加成、时间衰减、置信度）
  → 知识点树（72 阶段全覆盖、领域/年级/学期推导）
  → 题目质量审核（格式、算式自检、歧义、超纲、要配图的题拦下）
  → 错因规则（数学/语文/英语）
  → V2.2 → V2.3 数据迁移回填
  → API 全流程（mastery / report / errors / error.analyze / wrong_questions）
  → 学生 A 应用题连续错误（掌握度下降 + 错因记录 + 训练建议）
  → 学生 B 大量正确（掌握度提升到熟练） → 两人数据隔离

用法：python backend/verify_knowledge.py     （自拉临时后端，端口 VERIFY_KNOWLEDGE_PORT，默认 8904）
全部通过时退出码为 0。
"""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta

PORT = int(os.getenv("VERIFY_KNOWLEDGE_PORT", "8904"))

_db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_knowledge.db")
for _suffix in ("", "-journal", "-wal", "-shm"):
    if os.path.exists(_db_file + _suffix):
        os.remove(_db_file + _suffix)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
os.environ["DEEPSEEK_API_KEY"] = ""      # 全程本地规则 + 内置兜底题，不依赖外网

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import error_analysis
import knowledge_tree
import mastery
import stages
import validator
import wrong_book
from database import SessionLocal, engine, migrate_data
from models import (
    AnswerErrorAnalysis,
    Base,
    Question,
    StudentKnowledgeMastery,
    WrongQuestion,
)

# 测试进程也要自己建表：临时库是空的，migrate_data() 需要表已经存在
Base.metadata.create_all(engine)

BASE = f"http://127.0.0.1:{PORT}"
KNOWLEDGE = "两步计算应用题"
ok = True
proc = None
http = requests.Session()


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


class Row:
    """模拟 models.Question 行对象，供纯函数测试使用。"""

    def __init__(self, subject, question, answer, options=None, knowledge="两步计算应用题",
                 difficulty=50, qid=1):
        self.id = qid
        self.subject = subject
        self.question = question
        self.answer = answer
        self.options = options
        self.knowledge = knowledge
        self.difficulty = difficulty


# ================= 1. MasteryEngine =================

engine_ = mastery.DEFAULT_ENGINE

five_right = [{"correct": True, "difficulty": 50, "time": datetime(2026, 1, 1, 9, 0)} for _ in range(5)]
result_five = engine_.calculate_mastery(five_right, now=datetime(2026, 1, 1, 10, 0))
check("5 题全对 → 掌握度约 70（题量少不给满分）", 65 <= result_five["mastery_score"] <= 72,
      result_five["mastery_score"])
check("5 题全对 → 置信度 0.4", result_five["confidence"] == 0.4, result_five["confidence"])
check("掌握等级分档", result_five["level"] == "初步掌握", result_five["level"])

many_right = [{"correct": True, "difficulty": 50, "time": datetime(2026, 1, 1, 9, 0)} for _ in range(50)]
result_many = engine_.calculate_mastery(many_right, now=datetime(2026, 1, 1, 10, 0))
check("50 题全对 → 掌握度 90 以上", result_many["mastery_score"] >= 90, result_many["mastery_score"])
check("50 题全对 → 置信度 0.85 以上", result_many["confidence"] >= 0.85, result_many["confidence"])
check("题量越多掌握度越高", result_many["mastery_score"] > result_five["mastery_score"])
check("等级随分数上升", result_many["level"] == "熟练", result_many["level"])

mixed = ([{"correct": True, "difficulty": 50, "time": datetime(2026, 1, 1, 9, 0)} for _ in range(40)] +
         [{"correct": False, "difficulty": 50, "time": datetime(2026, 1, 1, 10, 0)} for _ in range(3)])
result_mixed = engine_.calculate_mastery(mixed, now=datetime(2026, 1, 1, 11, 0))
check("连续答错会降档", result_mixed["mastery_score"] < result_many["mastery_score"] - 10,
      (result_mixed["mastery_score"], result_many["mastery_score"]))
check("记录连续错误次数", result_mixed["consecutive_wrong"] == 3, result_mixed["consecutive_wrong"])

review_days = [{"correct": True, "difficulty": 50, "time": datetime(2026, 1, day, 9, 0)}
               for day in (1, 2, 3, 4)]
same_day = [{"correct": True, "difficulty": 50, "time": datetime(2026, 1, 1, hour, 0)}
            for hour in (9, 10, 11, 12)]
check("跨天复习有加成",
      engine_.calculate_mastery(review_days, now=datetime(2026, 1, 4, 12, 0))["mastery_score"]
      > engine_.calculate_mastery(same_day, now=datetime(2026, 1, 1, 13, 0))["mastery_score"])

idle = [{"correct": True, "difficulty": 50, "time": datetime(2026, 1, 1, 9, 0)} for _ in range(20)]
check("久不练习会衰减",
      engine_.calculate_mastery(idle, now=datetime(2026, 4, 1, 9, 0))["mastery_score"]
      < engine_.calculate_mastery(idle, now=datetime(2026, 1, 2, 9, 0))["mastery_score"])

empty = engine_.calculate_mastery([])
check("没有记录时掌握度为 0", empty["mastery_score"] == 0 and empty["level"] == "未练习")
check("置信度随题量单调", all(
    engine_.confidence_of(n) <= engine_.confidence_of(n + 1) for n in range(0, 60)))
check("掌握度始终在 0~100", all(
    0 <= engine_.calculate_mastery(
        [{"correct": index % 2 == 0, "difficulty": 90,
          "time": datetime(2026, 1, 1) + timedelta(hours=index)} for index in range(n)],
        now=datetime(2026, 1, 1))["mastery_score"] <= 100
    for n in range(0, 30)))
check("领域聚合按题量加权", mastery.aggregate([
    {"mastery_score": 100, "total_questions": 1},
    {"mastery_score": 0, "total_questions": 9},
]) == 10)
check("没有练习数据时聚合为 0", mastery.aggregate([]) == 0)


# ================= 2. 知识点树 =================

counts = {subject: len(knowledge_tree.all_names(subject)) for subject in stages.SUBJECTS}
check("三科知识点数量与阶段数一致",
      all(value == stages.LEVELS_PER_GRADE * stages.GRADE_COUNT for value in counts.values()), counts)

missing = []
for subject in stages.SUBJECTS:
    for key, name in stages.KNOWLEDGE[subject].items():
        if knowledge_tree.stage_of(subject, name) != key:
            missing.append((subject, name))
check("每个阶段的知识点都能在树里找到", not missing, missing[:3])

check("领域划分覆盖全部知识点", all(
    sum(len(group["knowledge"]) for group in knowledge_tree.domains_for(subject))
    == stages.LEVELS_PER_GRADE * stages.GRADE_COUNT
    for subject in stages.SUBJECTS))
check("知识点路径可读",
      knowledge_tree.path_of("数学", "表内乘法") == "数学 / 计算 / 表内乘法",
      knowledge_tree.path_of("数学", "表内乘法"))
check("年级与学期可推导",
      knowledge_tree.grade_of("数学", "表内乘法") == 2
      and knowledge_tree.semester_of("数学", "表内乘法") == "上册",
      (knowledge_tree.grade_of("数学", "表内乘法"), knowledge_tree.semester_of("数学", "表内乘法")))
check("支持子知识点", knowledge_tree.subpoints_of("数学", "表内乘法") == ["2~5的乘法口诀", "6~9的乘法口诀"])
check("子知识点能反查父节点", knowledge_tree.subpoint_parent("数学", "2~5的乘法口诀") == "表内乘法")
check("整棵树节点数合理", len(knowledge_tree.node_rows("数学")) > 30,
      len(knowledge_tree.node_rows("数学")))

bad_rows = []
for subject in stages.SUBJECTS:
    for row in knowledge_tree.node_rows(subject):
        if row["is_leaf"] and not knowledge_tree.stage_of_any(subject, row["knowledge_name"]):
            bad_rows.append(row["knowledge_name"])
check("叶子节点都能对应到能力阶段（子知识点继承父节点）", not bad_rows, bad_rows[:3])
check("子知识点的阶段继承父节点",
      knowledge_tree.stage_of_any("数学", "2~5的乘法口诀") == "2.1",
      knowledge_tree.stage_of_any("数学", "2~5的乘法口诀"))


# ================= 3. QuestionValidator =================

good = {"qtype": "choice", "question": "算一算：6 + 7 = ？",
        "options": {"A": "12", "B": "13", "C": "14", "D": "15"}, "answer": "B", "source": "bank"}
report_good = validator.validate(good, subject="数学", knowledge="20以内加减法", difficulty=15)
check("合法题目通过审核", report_good["passed"] is True, report_good["issues"])

wrong_answer = dict(good, answer="A")
check("答案与算式不符会被拦下",
      validator.validate(wrong_answer, subject="数学")["passed"] is False)

empty_question = dict(good, question="")
check("空题干会被拦下", validator.validate(empty_question)["passed"] is False)

missing_answer = dict(good, answer="")
check("缺答案会被拦下", validator.validate(missing_answer)["passed"] is False)

dup_options = dict(good, options={"A": "13", "B": "13", "C": "14", "D": "15"})
check("重复选项会被拦下", validator.validate(dup_options)["passed"] is False)

answer_out = dict(good, answer="Z")
check("答案不在选项里会被拦下", validator.validate(answer_out)["passed"] is False)

ambiguous = dict(good, options={"A": "12", "B": "13", "C": "14", "D": "以上都不对"})
check("歧义选项会被拦下", validator.validate(ambiguous)["passed"] is False)

leak = {"qtype": "choice", "question": "下面哪个是「苹果」的英文？apple 是正确写法吗？",
        "options": {"A": "apple", "B": "banana", "C": "pear", "D": "grape"},
        "answer": "A", "source": "bank"}
check("题干泄漏答案会给提示",
      any(item["code"] == "FORMAT_QUESTION_LEAKS_ANSWER"
          for item in validator.validate(leak, subject="英语")["issues"]))

hard_for_low = {"qtype": "choice", "question": "算一算：980 + 750 = ？",
                "options": {"A": "1730", "B": "1700", "C": "1630", "D": "1830"},
                "answer": "A", "source": "bank"}
check("低阶段出现大数会给提示",
      any(item["code"] == "DIFFICULTY_SCALE"
          for item in validator.validate(hard_for_low, subject="数学", difficulty=20)["issues"]))

out_of_scope = {"qtype": "choice", "question": "下面哪个分数最大？",
                "options": {"A": "1/2", "B": "1/3", "C": "1/4", "D": "1/5"},
                "answer": "A", "source": "deepseek"}
check("可能超纲会给提示",
      any(item["code"] == "DIFFICULTY_SCOPE"
          for item in validator.validate(out_of_scope, subject="数学", difficulty=20)["issues"]))

divide_zero = {"qtype": "choice", "question": "算一算：8 ÷ 0 = ？",
               "options": {"A": "0", "B": "8", "C": "1", "D": "10"},
               "answer": "A", "source": "bank"}
check("除以 0 会被拦下", validator.validate(divide_zero, subject="数学")["passed"] is False)

retained = validator.validate(good, subject="数学")["checks"]
check("审核结果带检查项", {"format", "answer", "difficulty", "knowledge"} <= set(retained), sorted(retained))

# ---- V2.8：系统不出带图的题（孩子看不到图就没法作答） ----
image_dependent = {"qtype": "choice", "question": "看图选出正确的答案：下面哪幅图画的是小猫？",
                   "options": {"A": "小猫", "B": "小狗", "C": "小兔", "D": "小马"},
                   "answer": "A", "source": "deepseek"}
image_codes = [item["code"] for item in validator.validate(image_dependent, subject="语文")["issues"]]
check("要孩子看图的题会被拦下", "IMAGE_DEPENDENT" in image_codes, image_codes)

letter_shape = {"qtype": "choice", "question": "哪一朵花上的字母写得又对、又没有写错？",
                "options": {"A": "b", "B": "d", "C": "p", "D": "q"},
                "answer": "A", "source": "deepseek"}
shape_codes = [item["code"] for item in validator.validate(letter_shape, subject="英语")["issues"]]
check("没有配图却要比字母写法的题会被拦下", "IMAGE_DEPENDENT" in shape_codes, shape_codes)

graphic_talk = {"qtype": "choice", "question": "下面这个图形有几条边？",
                "options": {"A": "3", "B": "4", "C": "5", "D": "6"},
                "answer": "B", "source": "deepseek"}
graphic_codes = [item["code"] for item in validator.validate(graphic_talk, subject="数学")["issues"]]
check("指向「下面这个图形」的题会被拦下", "IMAGE_DEPENDENT" in graphic_codes, graphic_codes)

needs_image_flag = dict(good, source="deepseek", needs_image=True)
check("模型自报需要配图的题会被拦下",
      validator.validate(needs_image_flag, subject="数学")["passed"] is False)

self_described = {"qtype": "choice",
                  "question": "看图写话时，图上画着一只小猫在树下睡觉，写哪句话最合适？",
                  "options": {"A": "一只小猫在树下安静地睡觉。", "B": "一只小狗在树上捉老鼠。",
                              "C": "一只小猫在河里游泳。", "D": "一只小猫在天上飞。"},
                  "answer": "A", "source": "deepseek"}
self_report = validator.validate(self_described, subject="语文")
check("用文字把图上内容写清楚的题仍然能过", self_report["passed"] is True, self_report["issues"])

bank_view = dict(self_described, source="bank")
bank_report = validator.validate(bank_view, subject="语文")
check("本地题库的看图写话题不受影响", bank_report["passed"] is True, bank_report["issues"])

import deepseek  # noqa: E402  （只读提示词常量，不联网）

check("出题提示词（选择题）要求不出需要配图的题",
      "needs_image" in deepseek.CHOICE_PROMPT and "配任何图片" in deepseek.CHOICE_PROMPT)
check("出题提示词（填空题）要求不出需要配图的题",
      "needs_image" in deepseek.BLANK_PROMPT and "配任何图片" in deepseek.BLANK_PROMPT)


# ================= 4. 错因规则 =================

math_row = Row("数学", "小明有 12 个苹果，吃掉 3 个，还剩多少个？", "A",
               options='{"A": "9", "B": "15", "C": "10", "D": "12"}', difficulty=45)
math_rule = error_analysis.rule_analyze("数学", math_row, "B")
check("数学：减法做成加法 → 概念错误", math_rule["error_type"] == "概念错误", math_rule["error_type"])
check("概念错误给出下一步建议", bool(math_rule["suggestion"]), math_rule["suggestion"])

calc_row = Row("数学", "算一算：47 + 25 = ？", "A", options='{"A": "72", "B": "71", "C": "62", "D": "73"}',
               knowledge="100以内加减法", difficulty=25)
check("数学：只差一点 → 计算错误",
      error_analysis.rule_analyze("数学", calc_row, "B")["error_type"] == "计算错误")

unit_row = Row("数学", "一个正方形的边长是 6 厘米，它的周长是多少厘米？", "A",
               options='{"A": "24厘米", "B": "24平方厘米", "C": "12厘米", "D": "36厘米"}',
               knowledge="长方形与正方形的周长", difficulty=50)
check("数学：数字对但单位错 → 单位错误",
      error_analysis.rule_analyze("数学", unit_row, "24")["error_type"] == "单位错误")

chinese_row = Row("语文", "下面哪个字是「木」字旁？", "A",
                  options='{"A": "树", "B": "水", "C": "火", "D": "土"}',
                  knowledge="笔画与笔顺", difficulty=18)
chinese_rule = error_analysis.rule_analyze("语文", chinese_row, "B")
check("语文：给出字词类错因", chinese_rule["error_type"] in error_analysis.ERROR_TYPES["语文"],
      chinese_rule["error_type"])

plain_choice = Row("语文", "下面哪个字的读音是 dà？", "A",
                   options='{"A": "大", "B": "太", "C": "天", "D": "犬"}',
                   knowledge="拼音与声调", difficulty=15)
check("语文：普通选择题不会被误判成阅读类错因",
      error_analysis.rule_analyze("语文", plain_choice, "B")["error_type"] == "字词错误",
      error_analysis.rule_analyze("语文", plain_choice, "B")["error_type"])

short_story = Row("语文", "阅读短文《春天来了》：小草绿了，花儿开了。这段话主要写了什么？", "A",
                  options='{"A": "春天的景色", "B": "冬天的景色", "C": "秋天的景色", "D": "夏天的景色"}',
                  knowledge="段落大意概括", difficulty=45)
check("语文：带短文的题会判成阅读理解类",
      error_analysis.rule_analyze("语文", short_story, "B")["error_type"]
      in ("阅读理解错误", "信息定位错误"),
      error_analysis.rule_analyze("语文", short_story, "B")["error_type"])

english_row = Row("英语", "Which word is correct?", "A",
                  options='{"A": "apple", "B": "appel", "C": "banana", "D": "pear"}',
                  knowledge="常见动物单词", difficulty=30)
english_rule = error_analysis.rule_analyze("英语", english_row, "B")
check("英语：拼写相近 → 拼写错误", english_rule["error_type"] == "拼写错误",
      english_rule["error_type"])

grammar_row = Row("英语", "He ____ to school every day.", "A",
                  options='{"A": "goes", "B": "go", "C": "going", "D": "went"}',
                  knowledge="一般现在时（第三人称单数）", difficulty=55)
check("英语：词形变化 → 语法错误",
      error_analysis.rule_analyze("英语", grammar_row, "B")["error_type"] == "语法错误")

check("三科错因类型齐全",
      all(len(error_analysis.ERROR_TYPES[subject]) >= 4 for subject in stages.SUBJECTS),
      {subject: len(types) for subject, types in error_analysis.ERROR_TYPES.items()})


# ================= 5. V2.2 → V2.3 数据迁移 =================

db = SessionLocal()
db.add(StudentKnowledgeMastery(
    student_id=9, subject="数学", knowledge_id="表内乘法",
    questions=10, correct=8, total_questions=0, correct_questions=0,
    wrong_questions=0, confidence=0, mastery_score=80,
))
db.commit()
db.close()

migrate_data()

db = SessionLocal()
legacy = db.query(StudentKnowledgeMastery).filter(StudentKnowledgeMastery.student_id == 9).first()
check("迁移：总题量已回填", legacy.total_questions == 10, legacy.total_questions)
check("迁移：答对数已回填", legacy.correct_questions == 8, legacy.correct_questions)
check("迁移：答错数已算出", legacy.wrong_questions == 2, legacy.wrong_questions)
check("迁移：置信度已补算", legacy.confidence and legacy.confidence > 0, legacy.confidence)
check("迁移：旧列保持不变", legacy.questions == 10 and legacy.correct == 8)
check("迁移：幂等（再跑一次不重复搬运）", sum(migrate_data()) == 0)
db.close()


# ================= 6. 启动临时后端 =================

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


def ask(student_id, knowledge, subject="数学"):
    return http.get(BASE + "/question",
                    params={"student_id": student_id, "subject": subject,
                            "knowledge": knowledge, "qtype": "choice"}, timeout=60).json()


def submit(student_id, question, answer):
    return http.post(BASE + "/submit",
                     json={"question_id": question["question_id"], "answer": answer,
                           "student_id": student_id}, timeout=30).json()


# ================= 7. 学生 A：应用题连续错误 =================

scores = []
reason_types = []

for _ in range(3):
    question = ask(1, KNOWLEDGE)
    result = submit(1, question, wrong_of(question))
    scores.append(result["mastery"]["mastery_score"])
    reason_types.append(result["error_analysis"]["error_type"])

check("答错后给出错因分析", all(item in error_analysis.ERROR_TYPES["数学"] for item in reason_types),
      reason_types)
check("答错后附掌握度", all(isinstance(item, int) for item in scores), scores)
check("连续答错掌握度下降", scores[-1] < scores[0], scores)
check("掌握度置信度随题量上升", result["mastery"]["confidence"] > 0, result["mastery"]["confidence"])
check("答错返回错题本概览", result["wrong_book"]["NEW"] >= 1, result["wrong_book"])

db = SessionLocal()
stored = db.query(AnswerErrorAnalysis).filter(AnswerErrorAnalysis.student_id == 1).count()
wrong_rows = db.query(WrongQuestion).filter(WrongQuestion.student_id == 1).count()
mastery_row = db.query(StudentKnowledgeMastery).filter(
    StudentKnowledgeMastery.student_id == 1,
    StudentKnowledgeMastery.knowledge_id == KNOWLEDGE,
).first()
db.close()

check("错因分析已落库", stored >= 3, stored)
check("错题已进入错题本", wrong_rows >= 3, wrong_rows)
check("掌握度行已写入 V2.3 字段",
      mastery_row is not None and mastery_row.total_questions >= 3
      and mastery_row.wrong_questions >= 3 and mastery_row.mastery_score < 50,
      (mastery_row.mastery_score, mastery_row.total_questions, mastery_row.wrong_questions))


# ================= 8. 学生 A：错题本状态流转 =================

flow_stats = http.get(f"{BASE}/api/wrong_questions/1", params={"subject": "数学"}, timeout=20).json()
check("错题本返回三档统计", {"NEW", "LEARNING", "MASTERED", "total"} <= set(flow_stats["stats"]),
      flow_stats["stats"])
check("新错题状态是未掌握", flow_stats["stats"]["NEW"] >= 3, flow_stats["stats"])
check("错题条目带题干与状态文案",
      all(item["question"] and item["status_text"] for item in flow_stats["items"][:3]))

for _ in range(2):
    question = ask(1, KNOWLEDGE)
    submit(1, question, truth_of(question["question_id"]))

after = http.get(f"{BASE}/api/wrong_questions/1", params={"subject": "数学"}, timeout=20).json()
check("练相似题后错题进入巩固中/已攻克",
      after["stats"]["MASTERED"] >= 3 or after["stats"]["LEARNING"] >= 3, after["stats"])
check("已攻克的和未掌握的不再混在一起",
      after["stats"]["NEW"] + after["stats"]["LEARNING"] + after["stats"]["MASTERED"]
      == after["stats"]["total"])

filtered = http.get(f"{BASE}/api/wrong_questions/1",
                    params={"subject": "数学", "status": "MASTERED"}, timeout=20).json()
check("按状态筛选错题", all(item["status"] == "MASTERED" for item in filtered["items"]),
      [item["status"] for item in filtered["items"]])
check("非法状态返回 400",
      http.get(f"{BASE}/api/wrong_questions/1", params={"status": "XX"}, timeout=20).status_code == 400)


# ================= 9. 学生 B：大量正确 → 掌握度提升到熟练 =================

last = None
all_correct = True
for index in range(20):
    question = ask(2, "表内乘法")
    last = submit(2, question, truth_of(question["question_id"]))
    if not last["correct"]:
        all_correct = False
        check(f"第 {index + 1} 题判对", False, last)
        break

check("连续 20 题全部判对", all_correct, last and last["correct"])

check("答对时错因分析为空", last["error_analysis"] is None, last["error_analysis"])
check("连续答对掌握度提升", last["mastery"]["mastery_score"] >= 85, last["mastery"])
check("进入熟练状态", last["mastery"]["level"] == "熟练", last["mastery"]["level"])
check("掌握了就不再出现错题", last["wrong_book"]["total"] == 0, last["wrong_book"])


# ================= 10. 数据隔离 =================

report_a = http.get(f"{BASE}/api/report/knowledge",
                    params={"student_id": 1, "subject": "数学"}, timeout=20).json()
report_b = http.get(f"{BASE}/api/report/knowledge",
                    params={"student_id": 2, "subject": "数学"}, timeout=20).json()

check("两个学生的知识报告各自独立",
      report_a["student_id"] == 1 and report_b["student_id"] == 2, "ok")
check("学生 A 报告里薄弱的是应用题",
      any(item["knowledge"] == KNOWLEDGE for item in report_a["weak"]), report_a["weak"][:2])
check("学生 B 报告里掌握的是乘法",
      any(item["knowledge"] == "表内乘法" for item in report_b["mastered"]), report_b["mastered"][:2])
check("两人平均掌握度不同", report_a["average_mastery"] != report_b["average_mastery"],
      (report_a["average_mastery"], report_b["average_mastery"]))

db = SessionLocal()
shared = db.query(StudentKnowledgeMastery).filter(
    StudentKnowledgeMastery.student_id == 1,
    StudentKnowledgeMastery.knowledge_id == "表内乘法",
).count()
answers_b = db.query(WrongQuestion).filter(WrongQuestion.student_id == 2).count()
db.close()
check("学生 B 的练习不会写进学生 A 的记录", shared == 0, shared)
check("学生 B 没有错题记录", answers_b == 0, answers_b)


# ================= 11. API 契约 =================

root = http.get(BASE + "/", timeout=10).json()
check("版本已升级到 2.6（V2.3 能力保留）", root["version"] == "2.6", root["version"])
check("首页列出错因分析与题目审核",
      any("错因" in item for item in root["features"]) and any("审核" in item for item in root["features"]))

mastery_api = http.get(f"{BASE}/api/mastery/1", params={"subject": "数学"}, timeout=20).json()
check("知识地图返回领域与知识点",
      len(mastery_api["domains"]) >= 3
      and len(mastery_api["knowledge"]) == stages.LEVELS_PER_GRADE * stages.GRADE_COUNT,
      (len(mastery_api["domains"]), len(mastery_api["knowledge"])))
check("知识地图领域带星级",
      all({"domain", "star_text", "children"} <= set(item) for item in mastery_api["domains"]))
check("知识地图带汇总统计",
      {"knowledge_count", "mastered", "learning", "weak", "average_mastery"} <= set(mastery_api["summary"]),
      mastery_api["summary"])
check("知识点带掌握度与置信度",
      all({"mastery_score", "confidence", "level", "path"} <= set(item)
          for item in mastery_api["knowledge"]))
check("三科汇总都在", len(mastery_api["subjects_summary"]) == 3)
check("非法科目返回 400",
      http.get(f"{BASE}/api/mastery/1", params={"subject": "科学"}, timeout=10).status_code == 400)

report = http.get(f"{BASE}/api/report/knowledge",
                  params={"student_id": 1, "subject": "数学"}, timeout=20).json()
check("知识报告可用", report["available"] is True)
check("知识报告含领域汇总", len(report["domain_summary"]) >= 3)
check("知识报告含建议", bool(report["advice"]), report["advice"][:2])
check("知识报告建议里提到短板知识点",
      any(KNOWLEDGE in item for item in report["advice"]), report["advice"])
check("知识报告含错因汇总", isinstance(report["error_summary"], list))
check("没练过的科目报告为不可用",
      http.get(f"{BASE}/api/report/knowledge",
               params={"student_id": 1, "subject": "英语"}, timeout=10).json()["available"] is False)

errors = http.get(f"{BASE}/api/errors/1", timeout=20).json()
check("错因统计有数据", errors["total"] >= 3, errors["total"])
check("错因按类型汇总带百分比",
      all({"error_type", "count", "percent"} <= set(item) for item in errors["by_type"]),
      errors["by_type"])
check("错因明细带题干与建议",
      all({"question", "analysis", "suggestion", "knowledge"} <= set(item) for item in errors["items"]))
check("错因按科目筛选",
      http.get(f"{BASE}/api/errors/1", params={"subject": "语文"}, timeout=10).json()["total"] == 0)

analyze_question = ask(1, KNOWLEDGE)
analyze = http.post(BASE + "/api/error/analyze",
                    json={"student_id": 1, "question_id": analyze_question["question_id"],
                          "answer": wrong_of(analyze_question), "use_ai": False}, timeout=20).json()
check("错因分析接口返回原因与建议", bool(analyze["analysis"]) and bool(analyze["suggestion"]), analyze)
check("错因分析接口给出候选类型", len(analyze["error_types"]) >= 4, analyze["error_types"])
check("错因分析已落库", analyze["saved"] is True and analyze["id"] > 0)
check("分析不存在的题目返回 404",
      http.post(BASE + "/api/error/analyze",
                json={"student_id": 1, "question_id": 999999, "answer": "A"}, timeout=10).status_code == 404)

tree_api = http.get(f"{BASE}/api/knowledge/tree", params={"subject": "语文"}, timeout=10).json()
check("知识点树接口可用", len(tree_api["domains"]) >= 4 and len(tree_api["domains"][0]["children"]) >= 1)

audit = ask(2, "表内乘法")
check("出题返回质量审核结果", audit.get("audit", {}).get("passed") is True, audit.get("audit"))


# ================= 12. 诊断也接入错因与掌握度 =================

started = http.post(BASE + "/api/diagnostic/start",
                    json={"student_id": 2, "subject": "语文"}, timeout=20).json()
before = http.get(f"{BASE}/api/errors/2", params={"subject": "语文"}, timeout=10).json()["total"]

for _ in range(5):
    question = http.get(BASE + "/api/diagnostic/question",
                        params={"session_id": started["session_id"]}, timeout=30).json()
    if question.get("finished"):
        break
    http.post(BASE + "/api/diagnostic/answer",
              json={"session_id": started["session_id"], "question_id": question["question_id"],
                    "answer": wrong_of(question)}, timeout=20)

after_errors = http.get(f"{BASE}/api/errors/2", params={"subject": "语文"}, timeout=10).json()
check("诊断答错也会记录错因", after_errors["total"] >= before + 3, (before, after_errors["total"]))

db = SessionLocal()
chinese_mastery = db.query(StudentKnowledgeMastery).filter(
    StudentKnowledgeMastery.student_id == 2,
    StudentKnowledgeMastery.subject == "语文",
).count()
db.close()
check("诊断也更新了语文掌握度", chinese_mastery >= 1, chinese_mastery)


# ================= 13. 前端页面可访问 =================

for page in ("knowledge_map.html", "wrong_book.html", "study_advice.html"):
    response = http.get(f"{BASE}/app/{page}", timeout=10)
    check(f"新页面可访问 {page}",
          response.status_code == 200 and "<html" in response.text.lower(), response.status_code)

for asset in ("knowledge_map.js", "wrong_book.js", "study_advice.js"):
    response = http.get(f"{BASE}/app/{asset}", timeout=10)
    check(f"新页面脚本可访问 {asset}", response.status_code == 200 and len(response.text) > 200,
          response.status_code)


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
