# ==============================================================
# 能力契约｜菲比陪伴对话：把学生的学习数据交给 DeepSeek，生成一句口语化反馈
# 入口：learning_snapshot / build_prompt / clean_line / fallback_line / ai_line / ai_enabled / phoebe_line / TRIGGERS
# 依赖：deepseek（KEY / API_URL）、auto_ability、models、sqlalchemy、requests
# 不负责：3D 立牌与语音播放 → frontend/phoebe3d.js；出题 → deepseek.generate_question
# 验证：python backend/verify_phoebe_ai.py
# 被调用：phoebe_routes.py（POST /api/phoebe/chat）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 菲比的"会说话"能力（只读）。

用户需求：菲比不再是写死的几句台词，而是**每次点击都触发一次反馈**，
由 DeepSeek 读取这个孩子的真实学习数据（练了多少、哪科什么水平、哪个知识点不稳、
错题多少、有什么该复习了）分析之后再说出来。

设计要点：

1. **只读**：本模块只 SELECT，不写任何表；出问题也不影响做题。
2. **轻量**：每科最多取最近 40 条答题记录（SQL 层 LIMIT），其余都是聚合查询。
3. **可降级**：没有 DEEPSEEK_API_KEY、网络超时、模型说胡话时，一律退回
   `fallback_line`——它同样会读学习数据（"你'两位数除法'还不太稳"），
   只是不用大模型，所以功能永远不会因为外网不可用而消失。
4. **给小孩子听**：台词限制在几十个字、去掉 Markdown 与 emoji，
   避免语音朗读念出奇怪的东西。
"""

import json
import os
import re
import time
from datetime import datetime

import requests
from sqlalchemy import func

import deepseek
from models import AnswerRecord, StudentKnowledgeMastery, Student, WrongQuestion

# 触发场景：点击立牌 / 答对 / 答错
TRIGGERS = ("click", "correct", "wrong")

MAX_LINE = 48          # 台词长度上限（字幕 + 朗读都吃这个长度）
AI_TIMEOUT = 8         # 单次 DeepSeek 调用的超时（秒），孩子等不了更久
RECENT_LIMIT = 40      # 每科取多少条最近答题记录参与能力判断
RECENT_SHOW = 5        # 快照里带几条最近作答明细

# 离线开关：设 PHOEBE_AI_OFFLINE=1 时完全不联网，直接走规则文案（验证脚本与不想联网的家长都用它）
OFFLINE_ENV = "PHOEBE_AI_OFFLINE"
OFFLINE_VALUES = ("1", "true", "yes", "on")

TRIGGER_TEXT = {
    "click": "孩子点了一下你（想听你说点什么）",
    "correct": "孩子刚刚答对了一道题",
    "wrong": "孩子刚刚答错了一道题",
}

# 清洗用：Markdown 记号与 emoji（朗读时会念出奇怪的东西）
MARK_RE = re.compile(r"[*_`#>•·]+")
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d\u2190-\u21FF]"
)
SPACE_RE = re.compile(r"\s+")
CUT_MARKS = "。！？；，"


# ---------------- 学习数据快照（只读） ----------------


def _today_start():
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _subject_rows(db, student_id, subject, limit=RECENT_LIMIT):
    """某一科最近的答题记录（SQL 层倒序截断，长期上万行也不会整表进内存）。"""
    rows = (db.query(AnswerRecord)
            .filter(AnswerRecord.student_id == student_id, AnswerRecord.subject == subject)
            .order_by(AnswerRecord.id.desc())
            .limit(limit)
            .all())
    return list(reversed(rows))


def _weak_points(db, student_id, limit=3):
    """最该补的知识点：做过题、题量够、掌握度最低。"""
    rows = (db.query(StudentKnowledgeMastery)
            .filter(StudentKnowledgeMastery.student_id == student_id,
                    StudentKnowledgeMastery.total_questions > 0)
            .order_by(StudentKnowledgeMastery.mastery_score.asc(),
                      StudentKnowledgeMastery.total_questions.desc())
            .limit(limit)
            .all())
    return [{"subject": r.subject, "knowledge": r.knowledge_id,
             "mastery": int(r.mastery_score or 0)} for r in rows]


def _strong_points(db, student_id, limit=2):
    """已经比较稳的知识点（用来夸孩子）。"""
    rows = (db.query(StudentKnowledgeMastery)
            .filter(StudentKnowledgeMastery.student_id == student_id,
                    StudentKnowledgeMastery.total_questions >= 3,
                    StudentKnowledgeMastery.mastery_score >= 80)
            .order_by(StudentKnowledgeMastery.mastery_score.desc())
            .limit(limit)
            .all())
    return [{"subject": r.subject, "knowledge": r.knowledge_id,
             "mastery": int(r.mastery_score or 0)} for r in rows]


def _wrong_stats(db, student_id):
    rows = (db.query(WrongQuestion.status, func.count(WrongQuestion.id))
            .filter(WrongQuestion.student_id == student_id)
            .group_by(WrongQuestion.status)
            .all())
    stats = {"NEW": 0, "LEARNING": 0, "MASTERED": 0}
    for status, count in rows:
        stats[str(status or "NEW").upper()] = int(count or 0)
    return stats


def _due_reviews(db, student_id, limit=3):
    """该复习了的知识点（按掌握度模型的下次复习时间判断，不依赖复习子包）。"""
    rows = (db.query(StudentKnowledgeMastery)
            .filter(StudentKnowledgeMastery.student_id == student_id,
                    StudentKnowledgeMastery.next_review_time.isnot(None),
                    StudentKnowledgeMastery.next_review_time <= datetime.now())
            .order_by(StudentKnowledgeMastery.next_review_time.asc())
            .limit(limit)
            .all())
    return [{"subject": r.subject, "knowledge": r.knowledge_id} for r in rows]


def learning_snapshot(db, student_id):
    """把"这个孩子现在学得怎么样"整理成一个精简字典（全部只读）。"""
    student = db.query(Student).filter(Student.id == student_id).first()
    name = (student.name if student else "") or f"小朋友{student_id}"

    snapshot = {
        "name": name,
        "student_id": student_id,
        "total_answers": 0,
        "correct_rate": 0.0,
        "today": {"total": 0, "correct": 0},
        "subjects": [],
        "weak": [],
        "strong": [],
        "wrong": {"NEW": 0, "LEARNING": 0, "MASTERED": 0},
        "due_reviews": [],
        "recent": [],
    }

    # 总体与今日作答
    total = db.query(func.count(AnswerRecord.id)).filter(
        AnswerRecord.student_id == student_id).scalar() or 0
    correct = db.query(func.count(AnswerRecord.id)).filter(
        AnswerRecord.student_id == student_id, AnswerRecord.correct.is_(True)).scalar() or 0
    snapshot["total_answers"] = int(total)
    snapshot["correct_rate"] = round(correct / total, 3) if total else 0.0

    today_total = db.query(func.count(AnswerRecord.id)).filter(
        AnswerRecord.student_id == student_id,
        AnswerRecord.created_at >= _today_start()).scalar() or 0
    today_correct = db.query(func.count(AnswerRecord.id)).filter(
        AnswerRecord.student_id == student_id,
        AnswerRecord.created_at >= _today_start(),
        AnswerRecord.correct.is_(True)).scalar() or 0
    snapshot["today"] = {"total": int(today_total), "correct": int(today_correct)}

    # 三科水平：复用 V2.5 的自动能力诊断（同样是只读轻量）
    try:
        import auto_ability
        profile = auto_ability.profile_for(db, student_id)
        snapshot["subjects"] = [
            {"subject": item["subject"], "stage_label": item.get("stage_label", ""),
             "score": item.get("score", 0), "status": item.get("status", ""),
             "answer_count": item.get("answer_count", 0),
             "correct_rate": item.get("correct_rate", 0)}
            for item in profile.get("subjects", [])
            if item.get("status") != "unknown"
        ]
    except Exception:
        snapshot["subjects"] = []

    snapshot["weak"] = _weak_points(db, student_id)
    snapshot["strong"] = _strong_points(db, student_id)
    snapshot["wrong"] = _wrong_stats(db, student_id)
    snapshot["due_reviews"] = _due_reviews(db, student_id)

    # 最近几次作答（最新的排在前面）
    recent_rows = (db.query(AnswerRecord)
                   .filter(AnswerRecord.student_id == student_id)
                   .order_by(AnswerRecord.id.desc())
                   .limit(RECENT_SHOW)
                   .all())
    snapshot["recent"] = [
        {"subject": r.subject, "knowledge": r.knowledge, "correct": bool(r.correct)}
        for r in recent_rows
    ]

    return snapshot


def snapshot_brief(snapshot):
    """给人看的一句话摘要（接口返回，方便家长/开发确认 AI 依据了什么）。"""
    info = snapshot or {}
    today = info.get("today") or {}
    parts = [f"{info.get('name', '小朋友')}：累计 {info.get('total_answers', 0)} 题"]

    if today.get("total"):
        parts.append(f"今天 {today['total']} 题对 {today['correct']} 题")
    else:
        parts.append("今天还没练")

    levels = [f"{s['subject']}{s.get('stage_label') or s.get('score')}"
              for s in (info.get("subjects") or [])]
    if levels:
        parts.append("水平 " + "／".join(levels))

    weak = info.get("weak") or []
    if weak:
        parts.append("待补强 " + "、".join(w["knowledge"] for w in weak[:2]))

    wrong = info.get("wrong") or {}
    if wrong.get("NEW") or wrong.get("LEARNING"):
        parts.append(f"错题 {wrong.get('NEW', 0) + wrong.get('LEARNING', 0)} 道")

    due = info.get("due_reviews") or []
    if due:
        parts.append(f"{len(due)} 个知识点该复习")

    return "；".join(parts)


# ---------------- 生成台词 ----------------


def build_prompt(snapshot, trigger="click", context=None):
    """拼出让 DeepSeek 说人话的提示词。"""
    trigger = trigger if trigger in TRIGGERS else "click"
    scene = TRIGGER_TEXT[trigger]

    extra = ""
    context = context or {}
    if trigger == "wrong" and context.get("knowledge"):
        extra = f"\n（刚答错的知识点是：{context['knowledge']}）"
    elif trigger == "correct" and context.get("knowledge"):
        extra = f"\n（刚答对的知识点是：{context['knowledge']}）"

    data = {
        "姓名": snapshot.get("name", ""),
        "累计答题": snapshot.get("total_answers", 0),
        "总体正确率": snapshot.get("correct_rate", 0),
        "今天": snapshot.get("today", {}),
        "各科水平": snapshot.get("subjects", []),
        "需要补强": snapshot.get("weak", []),
        "已经不错": snapshot.get("strong", []),
        "错题本": snapshot.get("wrong", {}),
        "该复习了": snapshot.get("due_reviews", []),
        "最近几次作答": snapshot.get("recent", []),
    }

    return f"""你是小学学习软件里的毛绒玩偶"菲比"，是孩子的学习伙伴。

现在的场景：{scene}{extra}

孩子的学习数据：
{json.dumps(data, ensure_ascii=False)}

请说一句中文给孩子听。硬性要求：
1. 只输出这一句话，不要引号、不要 Markdown、不要换行、不要 emoji。
2. 长度 15~45 个字，用小学生能听懂的口语，像玩偶在说话。
3. 要结合上面的数据说具体的东西（比如今天练了几题、哪个知识点还不稳、有几道错题该看看），但别生硬地念数字，也**不要编造数据里没有的内容**。
4. 语气温暖、有陪伴感：做到了就夸具体的点，没做到就温柔提醒，不要说教。
"""


def clean_line(text, limit=MAX_LINE):
    """把模型输出清洗成一句适合"字幕 + 朗读"的话。"""
    value = str(text or "").strip()
    if not value:
        return ""

    value = value.splitlines()[0]
    value = value.strip().strip('"').strip("'").strip("“”‘’")
    value = MARK_RE.sub("", value)
    value = EMOJI_RE.sub("", value)
    value = SPACE_RE.sub(" ", value).strip().strip("：:，,、")

    if len(value) > limit:
        cut = max(value.rfind(mark, 0, limit) for mark in CUT_MARKS)
        value = value[:cut + 1] if cut >= limit // 2 else value[:limit]

    return value.strip()


def fallback_line(snapshot, trigger="click", context=None):
    """没有大模型时也要说人话：规则化，但同样读学习数据。"""
    info = snapshot or {}
    name = info.get("name") or "小朋友"
    today = info.get("today") or {}
    weak = (info.get("weak") or [{}])[0]
    strong = (info.get("strong") or [{}])[0]
    wrong = info.get("wrong") or {}
    due = info.get("due_reviews") or []

    if trigger == "correct":
        return f"答对啦，{name}真棒！继续保持这个节奏。"

    if trigger == "wrong":
        if weak.get("knowledge"):
            return f"没关系，这道错了不要紧，「{weak['knowledge']}」我们再练两道就稳了。"
        return "没关系，错了才知道哪里要补，看完解析再来一道。"

    # click：日常问候 + 学习数据
    if not today.get("total"):
        if due:
            return f"{name}，今天还没开始练呢，有 {len(due)} 个知识点该复习啦，先浇浇水吧。"
        return f"{name}，今天还没开始练哦，要不要先做两道题热热身？"

    if due:
        return f"今天练了 {today['total']} 题啦，还有 {len(due)} 个知识点该复习，别忘了浇水～"

    if weak.get("knowledge"):
        return (f"今天已经练了 {today['total']} 题，{name}很努力！"
                f"「{weak['knowledge']}」还有点不稳，等下多练两道吧。")

    if strong.get("knowledge"):
        return f"{name}今天练了 {today['total']} 题，「{strong['knowledge']}」已经很稳啦，真厉害！"

    unresolved = int(wrong.get("NEW", 0)) + int(wrong.get("LEARNING", 0))
    if unresolved:
        return f"今天练了 {today['total']} 题，错题本里还有 {unresolved} 道等着我们一起攻克。"

    return f"{name}今天已经练了 {today['total']} 题，做得不错，继续保持！"


def ai_enabled():
    """能不能用大模型：配了 key 且没有打开离线开关。"""
    if os.getenv(OFFLINE_ENV, "").strip().lower() in OFFLINE_VALUES:
        return False
    return bool(getattr(deepseek, "KEY", ""))


def ai_line(snapshot, trigger="click", context=None, timeout=AI_TIMEOUT):
    """调 DeepSeek 生成台词。返回 (文本, 来源)；任何失败都返回 ("", 原因)。"""
    if os.getenv(OFFLINE_ENV, "").strip().lower() in OFFLINE_VALUES:
        return "", "offline"

    key = getattr(deepseek, "KEY", "")
    if not key:
        return "", "no_key"

    prompt = build_prompt(snapshot, trigger, context)

    try:
        response = requests.post(
            deepseek.API_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 120,
                "temperature": 1.1,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return "", f"error:{type(exc).__name__}"

    text = clean_line(content)
    if not text:
        return "", "empty"

    return text, "ai"


def phoebe_line(db, student_id, trigger="click", context=None):
    """总入口：抓学习数据 → 让 AI 说一句 → 不行就用规则兜底。"""
    started = time.time()
    trigger = trigger if trigger in TRIGGERS else "click"

    snapshot = learning_snapshot(db, student_id)
    text, source = ai_line(snapshot, trigger, context)

    if not text:
        text = fallback_line(snapshot, trigger, context)
        if source == "no_key":
            source = "fallback_no_key"
        elif source == "offline":
            source = "fallback_offline"
        else:
            source = "fallback_" + source.split(":")[0]

    return {
        "student_id": student_id,
        "trigger": trigger,
        "text": text,
        "source": source,
        "brief": snapshot_brief(snapshot),
        "elapsed_ms": int((time.time() - started) * 1000),
    }
