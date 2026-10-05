# ==============================================================
# 能力契约｜/api 知识域接口：掌握度明细与报告、错因统计与 AI 深化、错题本查询、知识树与重灌
# 入口：router / update_mastery（掌握度唯一写入口）/ mastery_detail / knowledge_report / errors / analyze_error / wrong_questions / knowledge_tree_api / knowledge_sync
# 依赖：mastery wrong_book error_analysis knowledge_tree stages models database
# 不负责：自适应 /api/learning/* → adaptive_routes.py；复习 /api/review/* → review_routes.py；诊断 → diagnostic_routes.py
# 验证：python backend/verify_knowledge.py
# 被调用：main.py（/submit 复用 update_mastery）、diagnostic_routes.py、adaptive/engine.py（_mastery_items）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 知识掌握 / 错因分析 / 错题本 / 知识掌握报告 API。

    GET  /api/mastery/{student_id}      知识掌握情况（含领域星级与知识点明细）
    GET  /api/report/knowledge          知识掌握报告（汇总 + 建议）
    GET  /api/errors/{student_id}       错因分析统计与明细
    POST /api/error/analyze             分析一次错误的错因（规则 + AI）
    GET  /api/wrong_questions/{student_id}  错题本（NEW / LEARNING / MASTERED）
    GET  /api/knowledge/tree            知识点树
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import error_analysis
import knowledge_tree
import mastery
import stages
import wrong_book
from database import get_db
from models import (
    AnswerErrorAnalysis,
    AnswerRecord,
    DiagnosticRecord,
    KnowledgePoint,
    Question,
    StudentKnowledgeMastery,
)

router = APIRouter(prefix="/api", tags=["知识掌握"])

# 错因 → 一句话提醒（学习建议页用）
ERROR_TIPS = {
    "概念错误": "先把概念说清楚：这个知识点到底在问什么。",
    "计算错误": "算完回头验算一遍，正确率比速度重要。",
    "审题错误": "读题时圈出关键词（一共、还剩、平均），说清题目在问什么再动笔。",
    "步骤错误": "把过程一步一步写出来，别跳步。",
    "单位错误": "答案记得带单位，写完检查单位对不对。",
    "字词错误": "容易混淆的字词每天抄写 3 遍。",
    "阅读理解错误": "回到短文里把答案所在的那一句划出来。",
    "信息定位错误": "先读问题，再带着问题读短文。",
    "表达错误": "先口头说一遍，再写下来读一读。",
    "单词错误": "单词卡每天读 3 遍、写 3 遍。",
    "拼写错误": "按音节读出来再拼写，拼完对照检查。",
    "语法错误": "记住这条语法规则，再造 3 个句子。",
    "阅读错误": "先读问题再读短文，找关键词所在句。",
}


class AnalyzeIn(BaseModel):
    student_id: int = 1
    question_id: int = 0
    answer: str = ""
    answer_record_id: int = 0
    use_ai: bool = True


def _fmt(moment):
    return moment.strftime("%Y-%m-%d %H:%M") if moment else ""


# ---------------- 掌握度持久化（日常练习与诊断都走这里） ----------------

def collect_records(db: Session, student_id: int, subject: str, knowledge: str):
    """汇总一个知识点上的全部答题记录：日常练习 + 诊断，并补上错因类型。"""
    db.flush()

    error_map = {}
    for row in db.query(AnswerErrorAnalysis).filter(
        AnswerErrorAnalysis.student_id == student_id,
        AnswerErrorAnalysis.knowledge_id == knowledge,
    ).all():
        if row.question_id:
            error_map[row.question_id] = row.error_type

    records = []
    for row in db.query(AnswerRecord).filter(
        AnswerRecord.student_id == student_id,
        AnswerRecord.subject == subject,
        AnswerRecord.knowledge == knowledge,
    ).all():
        records.append({
            "correct": bool(row.correct),
            "difficulty": row.difficulty or 50,
            "error_type": error_map.get(row.question_id),
            "time": row.created_at,
        })

    for row in db.query(DiagnosticRecord).filter(
        DiagnosticRecord.student_id == student_id,
        DiagnosticRecord.subject == subject,
        DiagnosticRecord.knowledge_point == knowledge,
    ).all():
        records.append({
            "correct": bool(row.correct),
            "difficulty": row.difficulty or 50,
            "error_type": error_map.get(row.question_id),
            "time": row.answer_time,
        })

    return records


def update_mastery(db: Session, student_id: int, subject: str, knowledge: str,
                   stage: str = None, when=None):
    """按历史答题记录重算掌握度并落库（MasteryEngine）。

    每次作答后重算，而不是简单累加，这样"连续错误降档、久不练习衰减、
    多次复习加成"才会真正生效。
    """
    if not knowledge:
        return None

    records = collect_records(db, student_id, subject, knowledge)
    result = mastery.DEFAULT_ENGINE.calculate_mastery(records, now=when)

    row = db.query(StudentKnowledgeMastery).filter(
        StudentKnowledgeMastery.student_id == student_id,
        StudentKnowledgeMastery.subject == subject,
        StudentKnowledgeMastery.knowledge_id == knowledge,
    ).first()

    if row is None:
        row = StudentKnowledgeMastery(
            student_id=student_id, subject=subject, knowledge_id=knowledge,
            questions=0, correct=0, difficulty_sum=0,
        )
        db.add(row)
        db.flush()

    node = db.query(KnowledgePoint).filter(
        KnowledgePoint.subject == subject,
        KnowledgePoint.knowledge_name == knowledge,
    ).first()
    if node is not None:
        row.knowledge_point_id = node.id
        row.grade = node.grade

    if stage and stages.is_valid(stage):
        row.stage = stage
    elif not row.stage:
        row.stage = knowledge_tree.stage_of(subject, knowledge) or stages.START_KEY

    row.mastery_score = result["mastery_score"]
    row.confidence = result["confidence"]
    row.total_questions = result["total_questions"]
    row.correct_questions = result["correct_questions"]
    row.wrong_questions = result["wrong_questions"]
    row.consecutive_wrong = result["consecutive_wrong"]
    # V2.2 的旧列同步写一份，保证老接口读到的数据一致
    row.questions = result["total_questions"]
    row.correct = result["correct_questions"]
    row.difficulty_sum = float(sum(float(item.get("difficulty") or 0) for item in records))
    row.last_practice_time = result["last_practice_time"]
    row.next_review_time = result["next_review_time"]
    row.updated_time = datetime.now()
    return row


def _normalize_subject(subject):
    text = str(subject or "").strip()
    if text not in stages.SUBJECTS:
        raise HTTPException(status_code=400, detail=f"科目必须是：{'、'.join(stages.SUBJECTS)}")
    return text


def _points_of(db: Session, subject: str):
    return {
        row.knowledge_name: row
        for row in db.query(KnowledgePoint).filter(KnowledgePoint.subject == subject).all()
    }


def _mastery_items(db: Session, student_id: int, subject: str):
    """把知识点树与掌握度记录合起来：没练过的知识点也要出现在地图上（未练习）。"""
    rows = {
        row.knowledge_id: row
        for row in db.query(StudentKnowledgeMastery).filter(
            StudentKnowledgeMastery.student_id == student_id,
            StudentKnowledgeMastery.subject == subject,
        ).all()
    }
    points = _points_of(db, subject)

    items = []
    for name in knowledge_tree.all_names(subject):
        row = rows.get(name)
        node = points.get(name)

        total = int((row.total_questions if row else 0) or (row.questions if row else 0) or 0)
        correct = int((row.correct_questions if row else 0) or (row.correct if row else 0) or 0)
        score = int((row.mastery_score if row else 0) or 0)
        confidence = float((row.confidence if row else 0) or 0)

        items.append({
            "knowledge_id": name,
            "knowledge_point_id": (row.knowledge_point_id if row and row.knowledge_point_id
                                   else (node.id if node else 0)),
            "grade": node.grade if node else knowledge_tree.grade_of(subject, name),
            "semester": node.semester if node else knowledge_tree.semester_of(subject, name),
            "chapter": node.chapter if node else knowledge_tree.domain_of(subject, name),
            "path": (node.path if node and node.path else knowledge_tree.path_of(subject, name)),
            "stage": row.stage if row else knowledge_tree.stage_of(subject, name),
            "mastery_score": score,
            "confidence": confidence,
            "level": mastery.DEFAULT_ENGINE.level_of(score) if total else "未练习",
            "total_questions": total,
            "correct_questions": correct,
            "wrong_questions": int((row.wrong_questions if row else 0) or max(total - correct, 0)),
            "consecutive_wrong": int((row.consecutive_wrong if row else 0) or 0),
            "last_practice_time": _fmt(row.last_practice_time if row else None),
            "next_review_time": _fmt(row.next_review_time if row else None),
        })

    items.sort(key=lambda item: (-item["mastery_score"], item["knowledge_id"]))
    return items


def _domains(subject: str, items):
    by_name = {item["knowledge_id"]: item for item in items}
    domains = []

    for group in knowledge_tree.domains_for(subject):
        children = [by_name[name] for name in group["knowledge"] if name in by_name]
        practiced = [child for child in children if child["total_questions"] > 0]
        average = mastery.aggregate(practiced) if practiced else 0

        domains.append({
            "domain": group["domain"],
            "mastery_score": average,
            "stars": stages.stars(average),
            "star_text": stages.star_text(average),
            "knowledge_count": len(children),
            "practiced_count": len(practiced),
            "children": children,
        })

    return domains


def _summary(items):
    practiced = [item for item in items if item["total_questions"] > 0]
    mastered = [item for item in practiced if item["mastery_score"] >= 85]
    learning = [item for item in practiced if 50 <= item["mastery_score"] < 85]
    weak = [item for item in practiced if item["mastery_score"] < 50]

    return {
        "knowledge_count": len(items),
        "practiced": len(practiced),
        "mastered": len(mastered),
        "learning": len(learning),
        "weak": len(weak),
        "average_mastery": mastery.aggregate(practiced),
    }


def _parse_time(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def _build_advice(items, error_types, now=None):
    """今天该干什么：先复习、再练薄弱、最后巩固，末尾提醒最常犯的错因。"""
    now = now or datetime.now()
    practiced = [item for item in items if item["total_questions"] > 0]
    tips = []

    if not practiced:
        return ["先做一次能力诊断或练几道题，系统才知道从哪里开始帮你。"]

    due = []
    for item in practiced:
        if item["mastery_score"] >= 85:
            continue
        moment = _parse_time(item["next_review_time"])
        if moment is not None and moment <= now + timedelta(days=1):
            due.append(item)
    due.sort(key=lambda item: item["mastery_score"])

    if due:
        top = due[0]
        tips.append(f"复习：{top['knowledge_id']}（掌握度 {top['mastery_score']}，已经该复习啦）")

    weak = sorted(practiced, key=lambda item: item["mastery_score"])
    for item in weak[:2]:
        if item["mastery_score"] < 70:
            tips.append(f"练习：{item['knowledge_id']}（掌握度 {item['mastery_score']}，"
                        f"错 {item['wrong_questions']} 题，每天练 10 分钟）")

    strong = [item for item in practiced if item["mastery_score"] >= 70]
    strong.sort(key=lambda item: item["mastery_score"])
    if strong:
        item = strong[0]
        tips.append(f"巩固：{item['knowledge_id']}（掌握度 {item['mastery_score']}，"
                    f"做几道稍难的题保持手感）")

    if error_types:
        top = error_types[0]
        tips.append(f"注意{top['error_type']}：{ERROR_TIPS.get(top['error_type'], '做题时多留意这一步。')}"
                    f"（最近出现 {top['count']} 次）")

    return tips[:4]


@router.get("/mastery/{student_id}")
def mastery_detail(student_id: int, subject: str = stages.DEFAULT_SUBJECT,
                   db: Session = Depends(get_db)):
    """知识掌握地图：领域星级 + 每个知识点的掌握度明细。"""
    subject = _normalize_subject(subject)
    items = _mastery_items(db, student_id, subject)

    summaries = []
    for name in stages.SUBJECTS:
        rows = db.query(StudentKnowledgeMastery).filter(
            StudentKnowledgeMastery.student_id == student_id,
            StudentKnowledgeMastery.subject == name,
            StudentKnowledgeMastery.total_questions > 0,
        ).all()
        summaries.append({
            "subject": name,
            "average_mastery": mastery.aggregate([
                {"mastery_score": row.mastery_score, "total_questions": row.total_questions}
                for row in rows
            ]),
            "practiced": len(rows),
        })

    return {
        "student_id": student_id,
        "subject": subject,
        "subjects": list(stages.SUBJECTS),
        "subjects_summary": summaries,
        "summary": _summary(items),
        "domains": _domains(subject, items),
        "knowledge": items,
    }


@router.get("/report/knowledge")
def knowledge_report(student_id: int = 1, subject: str = stages.DEFAULT_SUBJECT,
                     db: Session = Depends(get_db)):
    """知识掌握报告：整体掌握度 + 已掌握 / 需要提升 + 今天的学习建议。"""
    subject = _normalize_subject(subject)
    items = _mastery_items(db, student_id, subject)
    practiced = [item for item in items if item["total_questions"] > 0]

    if not practiced:
        return {
            "available": False,
            "student_id": student_id,
            "subject": subject,
            "message": "这一科还没有练习记录，先做一次能力诊断或练几道题吧～",
        }

    average = mastery.aggregate(practiced)
    errors = error_analysis.summary(db, student_id, subject=subject, limit=1)

    mastered = sorted([item for item in practiced if item["mastery_score"] >= 85],
                      key=lambda item: -item["mastery_score"])
    weak = sorted([item for item in practiced if item["mastery_score"] < 70],
                  key=lambda item: item["mastery_score"])

    def brief(item):
        return {
            "knowledge": item["knowledge_id"],
            "mastery_score": item["mastery_score"],
            "confidence": item["confidence"],
            "level": item["level"],
            "total_questions": item["total_questions"],
            "correct_questions": item["correct_questions"],
            "wrong_questions": item["wrong_questions"],
            "next_review_time": item["next_review_time"],
        }

    return {
        "available": True,
        "student_id": student_id,
        "subject": subject,
        "average_mastery": average,
        "stars": stages.stars(average),
        "star_text": stages.star_text(average),
        "summary": _summary(items),
        "domain_summary": [
            {"domain": domain["domain"], "mastery_score": domain["mastery_score"],
             "stars": domain["stars"], "star_text": domain["star_text"],
             "knowledge_count": domain["knowledge_count"]}
            for domain in _domains(subject, items)
        ],
        "mastered": [brief(item) for item in mastered[:10]],
        "weak": [brief(item) for item in weak[:10]],
        "error_summary": errors["by_type"][:5],
        "advice": _build_advice(items, errors["by_type"]),
        "generated_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


@router.get("/errors/{student_id}")
def errors(student_id: int, subject: str = "", limit: int = 20,
           db: Session = Depends(get_db)):
    """错因分析：按类型 / 科目汇总，外加最近错题的原因与建议。"""
    if subject:
        subject = _normalize_subject(subject)

    return error_analysis.summary(db, student_id, subject=subject or None, limit=limit)


@router.post("/error/analyze")
def analyze_error(payload: AnalyzeIn, db: Session = Depends(get_db)):
    """分析一次错误：规则分析 +（可选）AI 深化，结果落库。"""
    question = None

    if payload.answer_record_id:
        from models import AnswerRecord

        record = db.query(AnswerRecord).filter(AnswerRecord.id == payload.answer_record_id).first()
        if record is None:
            raise HTTPException(status_code=404, detail="答题记录不存在")

        question = db.query(Question).filter(Question.id == record.question_id).first()
        submitted = record.submitted
    else:
        question = db.query(Question).filter(Question.id == payload.question_id).first()
        submitted = payload.answer

    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在，请先生成题目")

    result = error_analysis.analyze(
        db, payload.student_id, question, submitted,
        answer_record_id=payload.answer_record_id or None,
        use_ai=bool(payload.use_ai),
    )
    db.commit()

    result["student_id"] = payload.student_id
    return result


@router.get("/wrong_questions/{student_id}")
def wrong_questions(student_id: int, subject: str = "", status: str = "", limit: int = 50,
                    db: Session = Depends(get_db)):
    """错题本：未掌握 / 巩固中 / 已攻克。"""
    if subject:
        subject = _normalize_subject(subject)

    status = str(status or "").strip().upper()
    if status and status not in wrong_book.STATUS_ORDER:
        raise HTTPException(status_code=400, detail="状态只能是 NEW / LEARNING / MASTERED")

    return {
        "student_id": student_id,
        "subject": subject,
        "status": status,
        "stats": wrong_book.stats_for(db, student_id, subject=subject or None),
        "status_text": wrong_book.STATUS_TEXT,
        "items": wrong_book.items_for(db, student_id, subject=subject or None,
                                      status=status or None, limit=limit),
    }


@router.get("/knowledge/tree")
def knowledge_tree_api(subject: str = stages.DEFAULT_SUBJECT, db: Session = Depends(get_db)):
    """知识点树：科目 → 章节领域 → 知识点（带年级、学期、难度）。"""
    subject = _normalize_subject(subject)
    points = _points_of(db, subject)

    domains = []
    for group in knowledge_tree.domains_for(subject):
        children = []
        for name in group["knowledge"]:
            node = points.get(name)
            children.append({
                "knowledge_id": name,
                "knowledge_point_id": node.id if node else 0,
                "grade": node.grade if node else knowledge_tree.grade_of(subject, name),
                "semester": node.semester if node else knowledge_tree.semester_of(subject, name),
                "difficulty": node.difficulty if node else knowledge_tree.difficulty_of(subject, name),
                "stage": knowledge_tree.stage_of(subject, name),
                "path": node.path if node else knowledge_tree.path_of(subject, name),
                "children": [
                    {"knowledge_id": child, "parent": name}
                    for child in knowledge_tree.subpoints_of(subject, name)
                ],
            })
        domains.append({"domain": group["domain"], "children": children})

    return {"subject": subject, "domains": domains}


@router.post("/knowledge/sync")
def knowledge_sync(db: Session = Depends(get_db)):
    """重新同步知识点树（升级题库后手动触发）。"""
    created, skipped = knowledge_tree.seed(db)
    linked = knowledge_tree.link_mastery(db)
    return {"created": created, "skipped": skipped, "linked_mastery": linked}
