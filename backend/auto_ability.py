# ==============================================================
# 能力契约｜训练数据自动能力诊断（AutoAbility）：只读答题记录推断每科能力阶段，**不写库**
# 入口：subject_profile / overall_profile / profile_for / recent_records / confidence_text
# 依赖：stages（能力阶段与知识点唯一来源）、knowledge_tree（知识点固有难度）、models.AnswerRecord（只读查询）
# 不负责：HTTP 接口 → ability_routes.py；专门诊断流程 → diagnostic.py / diagnostic_routes.py
# 验证：python backend/verify_ability.py
# 被调用：ability_routes.py（/api/ability/auto/{student_id}）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 训练数据自动能力诊断（AutoAbility）。

需求：**不额外进行能力诊断**，通过用户每日训练（今日学习页 /api/learning/*）
和自由训练（练习页 /question + /submit）的成绩系统自动诊断能力水平。
也就是说：不再依赖专门的能力诊断流程，改为从 answer_records 自动推断每科能力阶段。

算法契约（纯函数部分可直接单测，见 verify_ability.py）：

1. 样本窗口：某一科的答题记录按 id 升序排列，取**最近 WINDOW_SIZE = 40 条**。
2. 能力分 score（0~100，保留 1 位）= 加权平均难度：
   答对权重 1.0，答错权重 0.35，``score = Σ(difficulty × w) / Σ(w)``。
   V2.6：每条记录的 difficulty 先与「该知识点固有难度」取小（知识树查得到才取），
   避免旧的虚高难度分（曾按能力分顶到 100）把能力评价抬成假的高年级。
3. 阶段 stage = ``stages.key_of_difficulty(score)``；stage_label = ``stages.label(stage)``；
   range = ``stages.stage_range(stage)``。
4. 稳定性 consistency：答对题 difficulty 的标准差 s → ``max(0.0, 1 - s / 40)``；
   答对题少于 2 条时记 0.5（样本太少，不给满也不给零）。
5. 题量因子 volume = ``min(1.0, n / 20)``；
   confidence = ``round(0.6 × volume + 0.4 × consistency, 2)``。
6. confidence_text：>= 0.75 → "高"，>= 0.45 → "中"，否则 "低"。
7. status：n == 0 → "unknown"（还没数据）；n < 5 → "warming"（数据积累中）；否则 "ready"。

本模块只读不写：不新增/修改任何表或列，不产生副作用。
"""

from datetime import datetime

from sqlalchemy import func

import knowledge_tree
import stages
from models import AnswerRecord

# 样本窗口：每科只看最近多少条记录
WINDOW_SIZE = 40

# 加权平均难度的权重：答对算满，答错降权（错题也反映水平，但不能和对题等权）
CORRECT_WEIGHT = 1.0
WRONG_WEIGHT = 0.35

# 题量因子满值：一科练够 20 题，题量维度就满分
VOLUME_FULL = 20

# 答对题难度的标准差达到 40 分时，稳定性因子归零
CONSISTENCY_SPAN = 40.0

# 置信度文案分界
CONFIDENCE_HIGH = 0.75
CONFIDENCE_MID = 0.45

# 至少 5 题才算"可以下结论"
READY_MIN_ANSWERS = 5

STATUS_UNKNOWN = "unknown"
STATUS_WARMING = "warming"
STATUS_READY = "ready"

# 下一步建议（三种状态各一句，前后端共用的中文文案）
NEXT_STEP_TEXT = {
    STATUS_UNKNOWN: "先做几道这一科的题，系统就能看出你的水平",
    STATUS_WARMING: "再多练几题，判断会更准",
    STATUS_READY: "可以试试更难一点的题目",
}


def confidence_text(confidence):
    """置信度 0~1 → "高" / "中" / "低"（给小朋友看的说法）。"""
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "低"

    if value >= CONFIDENCE_HIGH:
        return "高"
    if value >= CONFIDENCE_MID:
        return "中"
    return "低"


def _value(record, key, default=None):
    """答题记录既可能是 ORM 行对象，也可能是 dict（单测直接喂数据）。"""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _difficulty_of(record, subject=""):
    """取题目难度；脏数据退化成最低难度，保证算法永远能算出一个数。

    V2.6：题目难度分可能是虚高的（旧数据曾按能力分一路顶到 100），因此再与
    「这个知识点固有的难度」取小 —— 能力评价只认真实练的是什么知识点。
    知识树里查不到的知识点（如单测直接喂的 dict）不参与取小，保持向后兼容。
    """
    try:
        difficulty = float(_value(record, "difficulty", stages.MIN_DIFFICULTY))
    except (TypeError, ValueError):
        difficulty = float(stages.MIN_DIFFICULTY)

    knowledge = str(_value(record, "knowledge", "") or "").strip()
    if subject and knowledge and knowledge_tree.stage_of(subject, knowledge):
        return min(difficulty, float(knowledge_tree.difficulty_of(subject, knowledge)))
    return difficulty


def _is_correct(record):
    return bool(_value(record, "correct", False))


def _std(values):
    """总体标准差（除以个数）；样本不足 2 条时返回 None。"""
    if len(values) < 2:
        return None

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5


def _empty_profile():
    """一条记录都没有时的画像：字段齐全，前端可以直接渲染。"""
    return {
        "status": STATUS_UNKNOWN,
        "score": 0,
        "stage": "",
        "stage_label": "",
        "range": ["", ""],
        "stars": 0,
        "star_text": stages.star_text(0),
        "confidence": 0,
        "confidence_text": "低",
        "answer_count": 0,
        "correct_count": 0,
        "correct_rate": 0.0,
        "knowledge_focus": "",
        "reason": "最近还没有这一科的答题记录，先去练几道题，系统就能推断你的水平",
        "next_step": NEXT_STEP_TEXT[STATUS_UNKNOWN],
    }


def subject_profile(records, subject=""):
    """纯函数：把**某一科**的答题记录（id 升序）推断成能力画像。

    records 按 id 升序传入（旧 → 新），内部取最近 WINDOW_SIZE 条作为样本窗口。
    返回 dict：status / score / stage / stage_label / range / stars / star_text /
    confidence / confidence_text / answer_count / correct_count / correct_rate /
    knowledge_focus / reason / next_step。
    """
    window = list(records or [])[-WINDOW_SIZE:]
    count = len(window)

    if count == 0:
        return _empty_profile()

    weighted = 0.0
    total_weight = 0.0
    correct_difficulties = []

    for record in window:
        difficulty = _difficulty_of(record, subject)
        if _is_correct(record):
            weight = CORRECT_WEIGHT
            correct_difficulties.append(difficulty)
        else:
            weight = WRONG_WEIGHT

        weighted += difficulty * weight
        total_weight += weight

    score = round(weighted / total_weight, 1) if total_weight else 0.0
    stage = stages.key_of_difficulty(score)
    stage_label = stages.label(stage)
    correct_count = len(correct_difficulties)
    correct_rate = round(correct_count / count, 2)

    std = _std(correct_difficulties)
    consistency = 0.5 if std is None else max(0.0, 1 - std / CONSISTENCY_SPAN)
    volume = min(1.0, count / VOLUME_FULL)
    confidence = round(0.6 * volume + 0.4 * consistency, 2)

    status = STATUS_READY if count >= READY_MIN_ANSWERS else STATUS_WARMING
    percent = int(round(correct_count / count * 100))

    if correct_count:
        stable = int(round(sum(correct_difficulties) / correct_count))
        reason = (f"最近 {count} 题答对 {correct_count} 题（{percent}%），"
                  f"稳定答对难度约 {stable} 的题，推断为{stage_label}")
    else:
        reason = (f"最近 {count} 题答对 0 题（{percent}%），"
                  f"还没有答对的题目，只能按当前难度估计，推断为{stage_label}")

    return {
        "status": status,
        "score": score,
        "stage": stage,
        "stage_label": stage_label,
        "range": list(stages.stage_range(stage)),
        "stars": stages.stars(score),
        "star_text": stages.star_text(score),
        "confidence": confidence,
        "confidence_text": confidence_text(confidence),
        "answer_count": count,
        "correct_count": correct_count,
        "correct_rate": correct_rate,
        "knowledge_focus": stages.knowledge_of(subject, stage) if subject else "",
        "reason": reason,
        "next_step": NEXT_STEP_TEXT[status],
    }


def overall_profile(subjects):
    """三科画像 → 总体画像：有数据的科目取 score 平均（保留 1 位）。"""
    scored = [item for item in subjects if item.get("status") != STATUS_UNKNOWN]

    if not scored:
        return {"stage": "", "stage_label": "", "score": 0, "status": STATUS_UNKNOWN}

    score = round(sum(item["score"] for item in scored) / len(scored), 1)
    stage = stages.key_of_difficulty(score)
    status = STATUS_READY if any(item["status"] == STATUS_READY for item in scored) else STATUS_WARMING

    return {
        "stage": stage,
        "stage_label": stages.label(stage),
        "score": score,
        "status": status,
    }


def recent_records(db, student_id, subject, limit=WINDOW_SIZE):
    """只读查询：某学生某科最近的答题记录，返回**id 升序**（旧 → 新）。

    在 SQL 层就限制条数，长期使用（题库累计上万条）也不会把整表读进内存。
    """
    rows = (db.query(AnswerRecord)
              .filter(AnswerRecord.student_id == student_id, AnswerRecord.subject == subject)
              .order_by(AnswerRecord.id.desc())
              .limit(limit)
              .all())
    rows.reverse()
    return rows


def profile_for(db, student_id):
    """只读查询：某学生的三科自动能力画像 + 总体画像 + 累计题量 + 生成时间。

    - 三科顺序与 ``stages.SUBJECTS`` 一致（数学 / 语文 / 英语）。
    - 学生不存在或没有任何记录时**不报错**，三科统一返回 status="unknown"。
    - 本函数不写库：只做 SELECT。
    """
    total_answers = (db.query(func.count(AnswerRecord.id))
                       .filter(AnswerRecord.student_id == student_id)
                       .scalar()) or 0

    subjects = []
    for subject in stages.SUBJECTS:
        item = subject_profile(recent_records(db, student_id, subject), subject)
        item["subject"] = subject
        subjects.append(item)

    return {
        "student_id": student_id,
        "source": "training",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_answers": int(total_answers),
        "overall": overall_profile(subjects),
        "subjects": subjects,
    }
