# ==============================================================
# 能力契约｜阶段化动态诊断状态机与评分（纯函数）
# 入口：new_state / load_state / dump_state / record_answer / evaluate_stage / progress_of / expected_total / calculate_ability / build_report / confidence_of / mastery_score / knowledge_ranking
# 依赖：json math stages
# 不负责：诊断题库 → diagnostic_bank.py；诊断接口 → diagnostic_routes.py
# 验证：python backend/verify_diagnostic.py
# 被调用：diagnostic_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.0 小学生能力诊断引擎（纯逻辑，不碰数据库，方便直接单测）。

三个概念分清楚：
1. **诊断阶段（stage）**：一组题的难度落在哪个能力阶段，例如 3.2。
2. **能力边界**：连续答对就往上探，答不动就停，最后得到"最后一个达到的阶段"
   和"再往上一级没通过"，即报告里的 3.1～3.2。
3. **能力画像**：`calculate_ability()` 把整场答题折算成能力阶段 + 能力分 + 置信度。

诊断推进规则（每阶段 5 题一组）：

| 正确率     | 判定             | 下一步                                    |
| ---------- | ---------------- | ----------------------------------------- |
| >= 90%     | 掌握优秀（跳级） | 本年级内跳到"进阶"；已在进阶/挑战则进下一学年基础 |
| 85% ~ 90%  | 掌握良好         | 进入下一学年基础                          |
| 60% ~ 85%  | 到了能力边界     | 记为边界候选，再向上探一级确认上沿        |
| < 60%      | 这一级没达到     | 结束，能力落在边界候选（或最后一个通过的阶段） |

关键点：**起点永远是 1.1，不看学生当前年级**；年级只用来生成同年级的题目文案。
"""

import json
import math

import stages

QUESTIONS_PER_STAGE = 5        # 每个阶段抽几道题（5 题全对才算「初步掌握」，避免假短板）
MAX_QUESTIONS = 60             # 一场诊断的题量上限，防止无限出题
EXCELLENT_RATE = 0.90
PASS_RATE = 0.85
BOUNDARY_RATE = 0.60

VERDICT_TEXT = {
    "excellent": "掌握很好，跳级测试",
    "good": "掌握不错，进入下一学年基础",
    "boundary": "到了能力边界，再确认一级",
    "fail": "这一级还没达到",
}


# ---------------- 会话状态 ----------------

def new_state(start_key=stages.START_KEY):
    """一场新诊断的初始状态（会被序列化进 diagnostic_sessions.state）。"""
    start_key = stages.normalize_key(start_key) or stages.START_KEY

    return {
        "stage": start_key,
        "stage_answered": 0,
        "stage_correct": 0,
        "total": 0,
        "correct": 0,
        "history": [],            # 每个阶段一组的判定记录
        "boundary": "",           # 60%~85% 命中的边界候选阶段
        "pass_index": -1,         # 最后一个通过（>=85%）的阶段坐标
        "pending_question_id": None,
        "asked": [],              # 出过的题干，避免同阶段重复出同一道题
        "finished": False,
        "reason": "",
    }


def load_state(raw):
    """从数据库的 JSON 文本恢复状态；损坏时退回全新状态。"""
    if not raw:
        return new_state()

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return new_state()

    if not isinstance(data, dict) or not data.get("stage"):
        return new_state()

    state = new_state()
    state.update(data)
    state["stage"] = stages.normalize_key(state.get("stage")) or stages.START_KEY
    state["boundary"] = stages.normalize_key(state.get("boundary")) or ""
    state["history"] = list(state.get("history") or [])
    state["asked"] = list(state.get("asked") or [])[-40:]
    return state


def dump_state(state):
    return json.dumps(state, ensure_ascii=False)


def progress_of(state):
    """诊断过程页要显示的进度信息。"""
    finished = bool(state["finished"])

    return {
        "stage": state["stage"],
        "stage_label": stages.label(state["stage"]),
        "stage_difficulty": stages.difficulty_of(state["stage"]),
        "stage_question": state["stage_answered"] + 1,
        "stage_total": QUESTIONS_PER_STAGE,
        "answered": state["total"],
        # 结束后分母收成实际题量，进度条正好走满
        "total": state["total"] if finished else expected_total(state),
        "finished": finished,
    }


def expected_total(state):
    """预计总题量：动态测试没有固定题数，这里给小朋友一个稳定的进度条分母。

    起步阶段显示 5+5+5=15 题，答到 15 题后分母变 30，与"15/30"的展示一致。
    """
    remaining = max(0, QUESTIONS_PER_STAGE - state["stage_answered"])
    estimate = state["total"] + remaining + QUESTIONS_PER_STAGE * 2
    return max(QUESTIONS_PER_STAGE * 2, min(MAX_QUESTIONS, estimate))


def record_answer(state, correct):
    """记录一次作答（同一阶段内累计）。"""
    state["stage_answered"] += 1
    state["total"] += 1
    state["pending_question_id"] = None

    if correct:
        state["stage_correct"] += 1
        state["correct"] += 1

    return state


def stage_round_finished(state):
    return state["stage_answered"] >= QUESTIONS_PER_STAGE


def verdict_of(rate):
    if rate >= EXCELLENT_RATE:
        return "excellent"
    if rate >= PASS_RATE:
        return "good"
    if rate >= BOUNDARY_RATE:
        return "boundary"
    return "fail"


def evaluate_stage(state, questions=None):
    """一组题答完后做判定，就地更新状态，返回本组结果。

    questions: 本组题的题干列表，用于解析里展示/去重（可为空）。
    """
    stage = state["stage"]
    index = stages.index_of(stage)
    count = state["stage_answered"]
    correct = state["stage_correct"]
    rate = correct / max(1, count)
    verdict = verdict_of(rate)

    entry = {
        "stage": stage,
        "label": stages.label(stage),
        "count": count,
        "correct": correct,
        "rate": round(rate, 3),
        "verdict": verdict,
        "verdict_text": VERDICT_TEXT[verdict],
        "questions": list(questions or []),
    }
    state["history"].append(entry)

    boundary = stages.normalize_key(state.get("boundary")) or ""
    next_stage = stage
    finished = False
    reason = ""

    # 先按本组正确率记下"通过 / 边界候选"，再判断这场诊断是否该收尾，
    # 这样即使正好撞上题量上限，最后一组的结果也不会丢。
    if verdict in ("excellent", "good"):
        state["pass_index"] = max(state.get("pass_index", -1), index)
        state["boundary"] = ""
    elif verdict == "boundary" and not boundary:
        state["boundary"] = stage

    if state["total"] >= MAX_QUESTIONS:
        finished, reason = True, "题量上限"

    elif verdict in ("excellent", "good"):
        if index >= stages.MAX_INDEX:
            finished, reason = True, "已达到最高阶段"
        else:
            next_stage = stages.advance(stage, rate)

    elif verdict == "boundary":
        if boundary:
            # 探测组也落在边界区间：能力就是候选阶段
            finished, reason = True, "连续两组都在边界区间"
        else:
            next_stage = stages.advance(stage, rate)

    else:  # fail
        finished, reason = True, "未达到当前阶段"

    if finished and not state["finished"]:
        state["finished"] = True
        state["reason"] = reason

    # 一组题结算完，清空本阶段计数并切到下一阶段
    state["stage_answered"] = 0
    state["stage_correct"] = 0
    state["stage"] = next_stage
    entry["next_stage"] = next_stage

    return entry


def final_key(state):
    """最终能力阶段：边界候选优先，其次最后一个通过的阶段，都没有就是 1.1。"""
    boundary = stages.normalize_key(state.get("boundary")) or ""
    if boundary:
        return boundary

    pass_index = int(state.get("pass_index", -1))
    if pass_index >= 0:
        return stages.key_of(pass_index)

    return stages.START_KEY


# ---------------- 能力评分 ----------------

def confidence_of(total):
    """置信度：题量越多越可信。

    10 题 → 0.50，30 题 → 0.85，50 题 → 0.95，之后缓慢逼近 1。
    """
    total = max(0, int(total or 0))

    if total <= 10:
        return round(0.50 * total / 10, 2)
    if total <= 30:
        return round(0.50 + 0.35 * (total - 10) / 20, 2)
    if total <= 50:
        return round(0.85 + 0.10 * (total - 30) / 20, 2)

    return round(min(1.0, 0.95 + 0.05 * (1 - math.exp(-(total - 50) / 50))), 2)


def weighted_rate(records):
    """加权正确率：难题答对更值钱，避免"刷简单题刷出高分"。"""
    weight_sum = 0.0
    hit_sum = 0.0

    for record in records:
        difficulty = float(record.get("difficulty") or 50)
        weight = 1.0 + max(0.0, min(100.0, difficulty)) / 100.0
        weight_sum += weight
        if record.get("correct"):
            hit_sum += weight

    return hit_sum / weight_sum if weight_sum else 0.0


def calculate_ability(records, final_stage, confidence=None):
    """把一场诊断的答题记录折算成能力画像。

    输入：
        records     : [{"stage": "3.2", "difficulty": 55, "correct": True}, ...]
        final_stage : 诊断得到的最终能力阶段
    输出：
        {"stage", "range", "score", "confidence", "stars", "star_text", "rate", "questions"}
    """
    final_stage = stages.normalize_key(final_stage) or stages.START_KEY
    index = stages.index_of(final_stage)
    records = list(records or [])

    rate = weighted_rate(records)
    total = len(records)

    # 阶段基准分：能力阶段越高基准越高（1.1 → 35，6.4 → 约 106，最终夹到 100）
    stage_base = 35.0 + index * 3.1
    score = 0.5 * stage_base + 0.5 * rate * 100.0
    score = round(max(0.0, min(100.0, score)), 1)

    conf = confidence_of(total) if confidence is None else round(float(confidence), 2)
    lower, upper = stages.stage_range(final_stage)

    return {
        "student_id": None,
        "subject": None,
        "stage": final_stage,
        "stage_label": stages.label(final_stage),
        "range": [lower, upper],
        "range_label": lower if lower == upper else f"{lower}～{upper}",
        "score": score,
        "confidence": conf,
        "stars": stages.stars(score),
        "star_text": stages.star_text(score),
        "rate": round(rate, 3),
        "questions": total,
        "correct": sum(1 for record in records if record.get("correct")),
    }


# ---------------- 知识点掌握度 ----------------

def mastery_score(correct, questions):
    """知识点掌握分 = 这个知识点上的正确率（0~100）。

    只用正确率是为了让家长/孩子一眼看懂："做对 8 道题里的几道"。
    题目难度不在这里扣分——它由能力阶段单独表达，否则"一年级全对"
    会被显示成 95 分，报告里白白多出一个"需要提升"的假短板。
    """
    questions = int(questions or 0)
    if questions <= 0:
        return 0

    return int(round(max(0.0, min(100.0, 100.0 * int(correct or 0) / questions))))


def knowledge_ranking(masteries):
    """知识点按掌握度排序，供报告里的"优势 / 需要提升"。"""
    items = [dict(item) for item in (masteries or [])]
    items.sort(key=lambda item: (-float(item.get("mastery_score") or 0), item.get("knowledge") or ""))
    return items


def strengths_and_weaknesses(masteries, top_n=2):
    """返回 (优势知识点, 需要提升的知识点)。

    优势：掌握度 >= 70 的知识点；一个都没有时给出相对最好的那个。
    短板：只认掌握度 < 70 的；全都不错时返回空列表，报告里就写"没有明显短板"。
    """
    ranked = knowledge_ranking(masteries)
    if not ranked:
        return [], []

    strengths = [item for item in ranked if item["mastery_score"] >= 70][:top_n]
    if not strengths:
        strengths = ranked[:1]

    weaknesses = [item for item in reversed(ranked) if item["mastery_score"] < 70][:top_n]

    # 优势与待提升不要重复出现在同一份报告里
    weak_names = {item["knowledge"] for item in weaknesses}
    strengths = [item for item in strengths if item["knowledge"] not in weak_names] or strengths[:1]

    return strengths, weaknesses


def advice_for(subject, final_stage, strengths, weaknesses):
    """根据能力阶段与知识点短板给学习建议（小朋友能读懂的话）。"""
    index = stages.index_of(final_stage)
    grade = stages.grade_of(final_stage)
    tips = []

    if index <= 11:
        tips.append("先把 20 以内、100 以内的加减法练到又快又准，这是后面所有内容的地基。")
    elif index <= 23:
        tips.append("每天用 5 分钟练乘法口诀和口算，再花 5 分钟做两道两步计算的应用题。")
    elif index <= 35:
        tips.append("重点练多位数乘除和分数初步认识，做题前先说说每一步在算什么。")
    elif index <= 47:
        tips.append("把运算定律用熟，遇到计算题先想能不能简便算，再动笔。")
    elif index <= 59:
        tips.append("小数、方程和面积公式要理解着记，每道题都先画一画图或写一写等量关系。")
    else:
        tips.append("分数、比、圆和百分数综合练习，每周做一次小测，把错题重做一遍。")

    if weaknesses:
        names = "、".join(item["knowledge"] for item in weaknesses[:2])
        tips.append(f"需要多练：{names}。每天专门练 10 分钟，做错的题当天再重做一遍。")
    else:
        tips.append("这次没有发现明显的短板，每天坚持练 10 分钟就能一直保持下去。")

    if subject == "语文":
        tips.append("每天大声朗读 10 分钟，把课文和古诗读熟，遇到不认识的字马上查拼音。")
    elif subject == "英语":
        tips.append("每天跟读 10 分钟单词和句子，先听清楚再开口，字母和单词要会拼会写。")
    else:
        tips.append("做题前先说说每一步在算什么，算完检查一遍，正确率比速度更重要。")

    if strengths:
        names = "、".join(item["knowledge"] for item in strengths[:2])
        tips.append(f"继续保持：{names} 已经不错了，可以试着做更难的题挑战自己。")

    if grade >= 5:
        tips.append("每周整理一次错题本，把同一类错误放在一起看，比多做新题更有效。")

    return tips[:3]


def build_report(subject, ability, masteries, history):
    """生成能力报告：能力画像 + 知识点细分 + 优势/待提升 + 建议。"""
    strengths, weaknesses = strengths_and_weaknesses(masteries)

    return {
        "subject": subject,
        "ability": ability,
        "stars": ability["stars"],
        "star_text": ability["star_text"],
        "score": ability["score"],
        "confidence": ability["confidence"],
        "stage": ability["stage"],
        "stage_label": ability["stage_label"],
        "range_label": ability["range_label"],
        "history": list(history or []),
        "knowledge": knowledge_ranking(masteries),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "advice": advice_for(subject, ability["stage"], strengths, weaknesses),
    }
