# ==============================================================
# 能力契约｜规则优先的错因判定（离线瞬时）+ 可选 AI 深化 + 统计与历史回填
# 入口：analyze / rule_analyze / ai_analyze / summary / dominant_error / backfill / SUGGESTIONS
# 依赖：deepseek、grading.parse_options、models
# 不负责：错题本状态推进 → wrong_book.py
# 验证：python backend/verify_knowledge.py
# 被调用：main.py、diagnostic_routes.py、knowledge_routes.py、adaptive/engine.py、review/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 错因分析系统：规则分析 + AI 深化。

孩子答错以后，系统不急着丢一个答案过去，而是先回答"**为什么错**"：

    学生错误 → 规则分析（本地、瞬时） → AI 分析（可选、更细） → 错误原因 + 下一步建议

规则部分按科目各有一套判据（都在本地算，不依赖网络）：

* **数学**：用错运算符（减法做成加法）→ 概念错误；只差一点点 → 计算错误；
  题干长、有应用题关键词且错得离谱 → 审题错误；多步题 → 步骤错误；单位丢了 → 单位错误。
* **语文**：和正确选项有共同字 → 字词错误；带短文的题 → 阅读理解 / 信息定位错误；
  仿写造句类 → 表达错误。
* **英语**：拼写只差一两个字母 → 拼写错误；多了 s/ed/ing → 语法错误；
  带短文的题 → 阅读错误；否则算单词错误。
"""

import json
import re
import unicodedata
from datetime import datetime

import deepseek
from grading import parse_options

# 每个科目允许的错误类型（前端下拉、统计都用它）
ERROR_TYPES = {
    "数学": ["概念错误", "计算错误", "审题错误", "步骤错误", "单位错误"],
    "语文": ["字词错误", "阅读理解错误", "信息定位错误", "表达错误"],
    "英语": ["单词错误", "拼写错误", "语法错误", "阅读错误"],
}

SUGGESTIONS = {
    "概念错误": "重新练习：{knowledge} 的含义。先用自己的话说一遍，再做 3 道同类题。",
    "计算错误": "再做 5 道同类型计算题，做完回头检查一遍（先算的再验算一次）。",
    "审题错误": "读题时圈出关键词（一共、还剩、平均、比……多），先说说题目在问什么再动笔。",
    "步骤错误": "把过程写出来：先算什么、再算什么，一步一步写清楚再计算。",
    "单位错误": "答案要带上单位，做完检查单位对不对（长度、面积、质量别混）。",
    "字词错误": "把容易混淆的字词抄写 3 遍，再各写一个词语。",
    "阅读理解错误": "回到短文里找出答案在哪一句，用笔划出来再作答。",
    "信息定位错误": "先读题目问什么，再带着问题去短文里找关键词。",
    "表达错误": "先口头说一遍再写下来，写完自己读一遍，看通不通顺。",
    "单词错误": "把这些单词做成单词卡，每天读 3 遍、写 3 遍。",
    "拼写错误": "按音节读出来再拼写，拼完对照原词检查一遍。",
    "语法错误": "记住这条语法规则，再造 3 个句子练一练。",
    "阅读错误": "先读问题再读短文，把关键词所在的句子划出来。",
}

OPERATORS = {"+": "+", "-": "-", "×": "*", "x": "*", "X": "*", "*": "*", "÷": "/", "/": "/"}
OPERATOR_NAMES = {"+": "加", "-": "减", "*": "乘", "/": "除"}
EXPR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([+\-×xX*÷/])\s*(\d+(?:\.\d+)?)")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

UNITS = ("平方厘米", "平方分米", "平方米", "厘米", "分米", "毫米", "千米", "米",
         "元", "角", "分", "个", "只", "朵", "本", "支", "人", "岁", "千克", "克", "吨", "升", "毫升")

APPLICATION_WORDS = ("一共", "还剩", "剩下", "平均", "每", "倍", "多多少", "少多少", "总共")
# 真正的"阅读类"信号：光有"下面哪个"不算，必须出现短文/段落这类字眼
READING_HINT = ("短文", "这段话", "文中", "阅读", "故事", "文章", "自然段")
EXPRESSION_HINT = ("仿写", "造句", "改为", "写一写", "补充句子", "扩写")


def _normalize(text):
    return unicodedata.normalize("NFKC", str(text or "")).strip().lower().replace(" ", "")


def _to_number(text):
    value = str(text or "").strip()
    for unit in UNITS:
        value = value.replace(unit, "")

    try:
        return float(value.strip())
    except ValueError:
        return None


def _distance(left, right):
    """编辑距离（拼写错误判定用）。"""
    left, right = str(left), str(right)
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, start=1):
        current = [i]
        for j, char_right in enumerate(right, start=1):
            cost = 0 if char_left == char_right else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def answer_text_of(question_row, submitted):
    """学生提交的可能是选项字母，这里换成看得懂的文本。"""
    given = str(submitted or "").strip()
    options = parse_options(question_row.options)

    if options and given.upper() in options:
        return options[given.upper()]

    return given


def _letter_text(question_row, letter):
    options = parse_options(question_row.options)
    return options.get(str(letter or "").upper(), str(letter or ""))


# ---------------- 数学 ----------------

def _math_reason(question, correct_text, given, difficulty, knowledge):
    want = _to_number(correct_text)
    got = _to_number(given)
    matches = EXPR_RE.findall(question)

    # 1) 用错运算符：把减法做成加法，这类是概念没建立起来
    if matches and want is not None and got is not None and len(matches) == 1:
        left, symbol, right = matches[0]
        operator = OPERATORS.get(symbol)
        a, b = float(left), float(right)
        wrong_ways = {
            "+": ("减法", a - b), "-": ("加法", a + b),
            "*": ("加法", a + b), "/": ("乘法", a * b),
        }
        name, value = wrong_ways.get(operator, ("", None))
        if value is not None and abs(got - value) < 0.001 and abs(want - value) > 0.001:
            return ("概念错误",
                    f"把「{symbol}」算成了{name}：{left} 和 {right} 应该用"
                    f"{OPERATOR_NAMES.get(operator, '')}法，结果应当是 {correct_text}。")

    # 2) 文字应用题：题干里正好两个数，孩子把"减少"当成了"增加"（反之亦然）
    numbers = [float(item) for item in NUMBER_RE.findall(question)]
    if len(numbers) == 2 and want is not None and got is not None:
        first, second = numbers
        if abs(got - (first + second)) < 0.001 and abs(want - (first - second)) < 0.001:
            return ("概念错误",
                    f"把「吃掉 / 减少」理解成了「增加」：{first:g} 和 {second:g} 应该相减，"
                    f"结果是 {correct_text}。")
        if abs(got - (first - second)) < 0.001 and abs(want - (first + second)) < 0.001:
            return ("概念错误",
                    f"「一共」要把 {first:g} 和 {second:g} 合起来（相加），结果是 {correct_text}。")

    # 3) 单位丢了但数字对
    if want is not None and got is not None and abs(got - want) < 0.001:
        return "单位错误", f"数字算对了，但单位没写对（正确答案要写成 {correct_text}）。"

    # 4) 差一点点：算错
    if want is not None and got is not None:
        tolerance = max(1.0, abs(want) * 0.05)
        if abs(got - want) <= tolerance:
            return "计算错误", f"思路是对的，但算错了：{given} 应该是 {correct_text}。"

    # 5) 审题错误：题干长、出现应用题关键词，答案离得很远
    long_story = len(question) >= 20 and any(word in question for word in APPLICATION_WORDS)
    if long_story:
        return "审题错误", f"没有看清题目问的是什么（题目在问「{knowledge}」），答案和题目对不上。"

    # 6) 步骤错误：多步计算
    if len(matches) >= 2 or float(difficulty or 0) >= 55:
        return "步骤错误", f"多步计算中间算错了，正确答案是 {correct_text}。"

    return "计算错误", f"答案算错了，正确答案是 {correct_text}。"


# ---------------- 语文 ----------------

def _chinese_reason(question, correct_text, given, knowledge):
    correct_norm = _normalize(correct_text)
    given_norm = _normalize(given)

    # 先看是不是阅读类题目：短文类题目的选项往往长得很像，不能当成字词混淆
    reading = len(question) >= 40 or any(word in question for word in READING_HINT)

    if reading:
        if len(given_norm) >= 2 and set(given_norm) & set(correct_norm):
            return "阅读理解错误", f"读懂了大概意思，但没有抓住短文里的关键信息（答案：{correct_text}）。"
        return "信息定位错误", f"没有在短文里找到对应信息，答案应该来自「{correct_text}」所在的那一句。"

    if any(word in question for word in EXPRESSION_HINT):
        return "表达错误", f"表达得不够准确，参考答案是「{correct_text}」。"

    if len(given_norm) >= 2 and len(given_norm) == len(correct_norm):
        shared = set(given_norm) & set(correct_norm)
        if shared:
            return "字词错误", f"和正确答案「{correct_text}」有字混了，说明这个字词还没记牢。"

    return "字词错误", f"这个知识点是「{knowledge}」，正确答案是「{correct_text}」，先把它记牢。"


# ---------------- 英语 ----------------

def _english_reason(question, correct_text, given, knowledge):
    correct_norm = _normalize(correct_text)
    given_norm = _normalize(given)

    if len(question) >= 40 or any(word in question for word in READING_HINT):
        return "阅读错误", f"短文里的信息没找对，正确答案是「{correct_text}」。"

    if correct_norm.isalpha() and given_norm.isalpha():
        # 先看词形变化（go / goes / going 这类是语法问题，不是拼写问题）
        for suffix in ("es", "s", "ed", "ing", "d"):
            if given_norm == correct_norm + suffix or correct_norm == given_norm + suffix:
                return "语法错误", f"词形不对：这里应该用「{correct_text}」，不是「{given}」。"

        distance = _distance(correct_norm, given_norm)
        if distance <= 2 and len(correct_norm) >= 3:
            return "拼写错误", f"「{given}」拼错了，正确拼写是「{correct_text}」。"

    return "单词错误", f"这个单词还没记住（{knowledge}），正确答案是「{correct_text}」。"


# ---------------- 对外接口 ----------------

def rule_analyze(subject, question_row, submitted):
    """规则分析：本地即时给出错误类型 + 原因 + 建议。"""
    subject = subject if subject in ERROR_TYPES else "数学"
    question = str(getattr(question_row, "question", "") or "")
    knowledge = str(getattr(question_row, "knowledge", "") or "")
    difficulty = getattr(question_row, "difficulty", 50)
    correct_text = _letter_text(question_row, getattr(question_row, "answer", ""))
    given = answer_text_of(question_row, submitted)

    if subject == "语文":
        error_type, analysis = _chinese_reason(question, correct_text, given, knowledge)
    elif subject == "英语":
        error_type, analysis = _english_reason(question, correct_text, given, knowledge)
    else:
        error_type, analysis = _math_reason(question, correct_text, given, difficulty, knowledge)

    return {
        "subject": subject,
        "knowledge": knowledge,
        "error_type": error_type,
        "analysis": analysis,
        "suggestion": SUGGESTIONS.get(error_type, "把这道题重新做一遍，说说每一步为什么这样做。")
                      .replace("{knowledge}", knowledge or "这个知识点"),
        "source": "rule",
        "correct_answer": correct_text,
        "submitted": given,
    }


def ai_analyze(subject, question_row, submitted, rule_result=None):
    """AI 深化分析；没配 key 或调用失败时返回 None（由调用方回退规则结果）。"""
    payload = {
        "subject": subject,
        "question": str(getattr(question_row, "question", "") or ""),
        "correct_answer": _letter_text(question_row, getattr(question_row, "answer", "")),
        "submitted": answer_text_of(question_row, submitted),
        "knowledge": str(getattr(question_row, "knowledge", "") or ""),
        "difficulty": getattr(question_row, "difficulty", 50),
        "error_types": ERROR_TYPES.get(subject, ERROR_TYPES["数学"]),
        "rule_guess": (rule_result or {}).get("error_type", ""),
    }
    return deepseek.analyze_error(payload)


def analyze(db, student_id, question_row, submitted, answer_record_id=None, use_ai=False):
    """完整分析流程（规则 → AI）并落库，返回分析结果 dict。"""
    from models import AnswerErrorAnalysis

    subject = str(getattr(question_row, "subject", "") or "数学")
    result = rule_analyze(subject, question_row, submitted)

    if use_ai:
        smarter = ai_analyze(subject, question_row, submitted, result)
        if smarter:
            result.update({
                "error_type": smarter.get("error_type") or result["error_type"],
                "analysis": smarter.get("analysis") or result["analysis"],
                "suggestion": smarter.get("suggestion") or result["suggestion"],
                "source": "ai",
            })

    row = AnswerErrorAnalysis(
        answer_record_id=answer_record_id,
        student_id=student_id,
        subject=subject,
        knowledge_id=result["knowledge"],
        question_id=getattr(question_row, "id", None),
        error_type=result["error_type"],
        analysis=result["analysis"],
        suggestion=result["suggestion"],
        source=result["source"],
        created_time=datetime.now(),
    )
    db.add(row)
    db.flush()

    result["id"] = row.id
    result["answer_record_id"] = answer_record_id
    result["question_id"] = getattr(question_row, "id", None)
    result["created_time"] = row.created_time.strftime("%Y-%m-%d %H:%M")
    result["error_types"] = ERROR_TYPES.get(subject, ERROR_TYPES["数学"])
    result["saved"] = True
    return result


def summary(db, student_id, subject=None, limit=20):
    """错因统计：按类型、按科目汇总 + 最近明细。"""
    from models import AnswerErrorAnalysis, Question

    query = db.query(AnswerErrorAnalysis).filter(AnswerErrorAnalysis.student_id == student_id)
    if subject:
        query = query.filter(AnswerErrorAnalysis.subject == subject)

    rows = query.order_by(AnswerErrorAnalysis.id.desc()).all()

    by_type = {}
    by_subject = {}
    for row in rows:
        by_type[row.error_type] = by_type.get(row.error_type, 0) + 1
        by_subject[row.subject] = by_subject.get(row.subject, 0) + 1

    total = len(rows)
    type_items = [
        {"error_type": name, "count": count,
         "percent": int(round(100 * count / total)) if total else 0}
        for name, count in sorted(by_type.items(), key=lambda item: -item[1])
    ]

    items = []
    for row in rows[:max(1, int(limit or 20))]:
        question = db.query(Question).filter(Question.id == row.question_id).first()
        items.append({
            "id": row.id,
            "answer_record_id": row.answer_record_id,
            "subject": row.subject,
            "knowledge": row.knowledge_id,
            "error_type": row.error_type,
            "analysis": row.analysis,
            "suggestion": row.suggestion,
            "source": row.source,
            "created_time": row.created_time.strftime("%Y-%m-%d %H:%M") if row.created_time else "",
            "question": question.question if question else "",
            "correct_answer": _letter_text(question, question.answer) if question else "",
        })

    return {
        "student_id": student_id,
        "subject": subject or "",
        "total": total,
        "by_type": type_items,
        "by_subject": [{"subject": name, "count": count}
                       for name, count in sorted(by_subject.items(), key=lambda item: -item[1])],
        "items": items,
    }


def dominant_error(db, student_id, knowledge=None, subject=None, top=1):
    """该学生（可指定知识点）最常犯的错误类型，供出题 prompt 使用。"""
    from models import AnswerErrorAnalysis

    query = db.query(AnswerErrorAnalysis).filter(AnswerErrorAnalysis.student_id == student_id)
    if knowledge:
        query = query.filter(AnswerErrorAnalysis.knowledge_id == knowledge)
    if subject:
        query = query.filter(AnswerErrorAnalysis.subject == subject)

    counter = {}
    for row in query.all():
        counter[row.error_type] = counter.get(row.error_type, 0) + 1

    ranked = sorted(counter.items(), key=lambda item: -item[1])
    return [name for name, _count in ranked[:max(1, top)]]


def backfill(db, limit=200):
    """给历史错题补错因分析（V2.2 时期的作答记录当时还没有错因表）。

    只在启动时跑一次，纯本地规则分析，最多 `limit` 条，不影响启动速度。
    """
    from models import AnswerErrorAnalysis, AnswerRecord, Question

    analyzed = {
        row[0] for row in db.query(AnswerErrorAnalysis.answer_record_id)
        .filter(AnswerErrorAnalysis.answer_record_id.isnot(None)).all()
    }

    records = (
        db.query(AnswerRecord)
        .filter(AnswerRecord.correct.is_(False))
        .order_by(AnswerRecord.id.desc())
        .limit(max(1, int(limit)) * 2)
        .all()
    )

    created = 0
    for record in records:
        if record.id in analyzed:
            continue

        question = db.query(Question).filter(Question.id == record.question_id).first()
        if question is None:
            continue

        analyze(db, record.student_id, question, record.submitted,
                answer_record_id=record.id, use_ai=False)
        created += 1

        if created >= limit:
            break

    if created:
        db.commit()

    return created
