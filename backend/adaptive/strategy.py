# ==============================================================
# 能力契约｜学什么知识点：优先级 + 依赖门控 + 知识依赖表（69 条边）
# 入口：LearningStrategy.rank / choose / prerequisites / dependents / foundation_weight / dependency_chain / tier_of / weakness_of / forgetting_risk / error_pressure / suggest_difficulty / DEPENDENCIES
# 依赖：stages knowledge_tree datetime
# 不负责：难度数值调整 → difficulty.py；下一题选择 → selector.py
# 验证：python backend/verify_adaptive.py
# 被调用：adaptive/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎 · 学习策略 LearningStrategy。

回答一个问题：**下一步学什么？**

输入（profile，由 `engine.profile()` 组装，也可以手工喂给纯函数做单测）：

```python
{
  "student_id": 1, "subject": "数学",
  "ability": {"stage": "3.2", "label": "三年级熟练", "score": 72, "confidence": 0.6},
  "knowledge": [{"knowledge_id": "两步计算应用题", "mastery_score": 60,
                 "total_questions": 8, "correct_questions": 5, "wrong_questions": 3,
                 "consecutive_wrong": 1, "stage": "2.3", "chapter": "应用题",
                 "last_practice_time": datetime, "next_review_time": datetime}, ...],
  "error_counts": {"两步计算应用题": 3},
  "recent": [{"correct": False, "difficulty": 58, "knowledge": "两步计算应用题",
              "time": datetime}, ...],
  "now": datetime,
}
```

输出 `next_action`：

```python
{"action": "practice", "knowledge": "两步计算应用题", "difficulty": 72,
 "reason": "掌握度62，需要强化", "priority_score": 0.68, "candidates": [...]}
```

知识点选择的优先级（**不是简单取最低分**）：

| 优先级 | 规则 |
| --- | --- |
| 1 | 高价值薄弱知识点：`mastery_score < 70` |
| 2 | 影响后续知识的基础知识：被依赖度高的先补 |
| 3 | 近期错误频繁的知识点 |
| 4 | 即将遗忘的知识点（到期没复习 / 很久没练） |

关键设计是 **依赖门控（block_bonus）**：应用题掌握 60、乘法掌握 50，
而应用题依赖乘法时，先把乘法提上来，而不是去练分数更低的那一个 ——
基础不牢，上面那层练了也白练。门控只在"前置**练过**且确实没达标"时生效，
避免把从没练过、只是没记录的前置误判成拦路虎。
"""

from datetime import datetime, timedelta

import knowledge_tree
import stages

# ---------- 阈值 ----------

WEAK_LINE = 70             # 低于它算薄弱知识点（需求给的第一优先级）
READY_LINE = 70            # 前置知识点达到它才算"基础打好了"
FOUNDATION_LINE = 0.34     # 被依赖度达到它才算"影响后续知识的基础"
ERROR_LINE = 0.34          # 近期错误压力达到它才算"错误频繁"
CHALLENGE_LINE = 85        # 达到它就该做挑战题
DECAY_DAYS = 10            # 超过这么多天没练，开始算"即将遗忘"
MAX_IDLE_DAYS = 30
# V2.6：练够题量、掌握度也稳在 60 以上，却始终到不了 READY_LINE 的知识点，
# 不再按最高优先级反复刷（继续单刷的边际收益很低），也不再当拦路虎挡住后续知识
SATURATION_TOTAL = 12      # 练过这么多题
SATURATION_MASTERY = 60    # 且掌握度已经不算差

# 四项证据的权重（合计 1.0）
WEIGHTS = {"weakness": 0.35, "foundation": 0.25, "error": 0.20, "forgetting": 0.20}

# 优先级档位加成：保证第 1 档真的排在后面几档前面
TIER_BONUS = {1: 0.30, 2: 0.18, 3: 0.10, 4: 0.04, 5: 0.00}
BLOCK_BONUS = 0.55         # 前置知识卡住后续知识时的加成
STAGE_BONUS = 0.12         # 命中当前能力阶段（学新知识时用）
CHALLENGE_PENALTY = 0.25   # 已经熟练掌握的，不再反复练

# 没练过的知识点按「离当前能力阶段有多远」加分：近的先学、超前的压后。
# 没有这条时，零记录学生只能靠 foundation_weight 排序，会永远从 1.1「20以内加减法」开始。
STAGE_LEVEL_BONUS = {0: 0.22, 1: 0.20, 2: 0.16, 3: 0.10}
# 从未练过、又比当前能力阶段高出 2 级以上的，大概率还学不动
STAGE_LEVEL_AHEAD_PENALTY = 0.08
# 坐标差超过它就不再给阶段加成
STAGE_LEVEL_SPAN = 3
ACTION_TEXT = {
    "practice": "强化练习",
    "review": "复习巩固",
    "challenge": "挑战提升",
    "diagnostic": "能力诊断",
}

# ---------- 知识依赖关系 ----------
#
# A → B → C：学 B 之前要先把 A 弄明白。这里写的是"主要依赖"，
# 不和 stages 的阶段顺序打架（阶段顺序只影响出题难度，不影响先补哪块基础）。
DEPENDENCIES = {
    "数学": {
        "100以内加减法": ["20以内加减法"],
        "连加连减与加减混合": ["100以内加减法"],
        "表内乘法": ["20以内加减法"],
        "表内除法": ["表内乘法"],
        "两步计算应用题": ["表内乘法", "100以内加减法"],
        "长度单位与测量": ["100以内加减法"],
        "认识图形与简单应用": ["20以内加减法"],
        "多位数乘一位数": ["表内乘法", "100以内加减法"],
        "两位数除法": ["表内除法"],
        "分数初步认识": ["100以内加减法"],
        "长方形与正方形的周长": ["长度单位与测量", "100以内加减法"],
        "大数认识与四则运算": ["100以内加减法"],
        "运算定律与简便计算": ["多位数乘一位数"],
        "小数的意义与加减法": ["分数初步认识", "100以内加减法"],
        "平行四边形与梯形面积": ["长方形与正方形的周长", "表内乘法"],
        "小数乘除法": ["小数的意义与加减法", "两位数除法"],
        "简易方程": ["100以内加减法", "表内乘法"],
        "因数与倍数": ["表内除法"],
        "多边形面积与组合图形": ["平行四边形与梯形面积"],
        "分数乘除法": ["分数初步认识", "表内乘法"],
        "比与比例": ["分数初步认识", "小数乘除法"],
        "圆的周长与面积": ["小数乘除法", "多边形面积与组合图形"],
        "百分数与统计": ["小数乘除法", "比与比例"],
    },
    "语文": {
        "笔画与笔顺": ["拼音与声调"],
        "组词与量词": ["笔画与笔顺"],
        "反义词与简单句子": ["组词与量词"],
        "多音字与词语积累": ["组词与量词"],
        "近义词与词语搭配": ["反义词与简单句子"],
        "句子排序与标点符号": ["反义词与简单句子"],
        "句子补充与看图写话": ["句子排序与标点符号"],
        "成语积累": ["多音字与词语积累"],
        "修辞手法初步": ["近义词与词语搭配"],
        "关联词与复句": ["句子排序与标点符号"],
        "段落大意概括": ["句子补充与看图写话"],
        "古诗名句": ["成语积累"],
        "病句修改": ["关联词与复句"],
        "记叙文阅读理解": ["段落大意概括"],
        "概括主要内容": ["记叙文阅读理解"],
        "说明文阅读": ["概括主要内容"],
        "文言文字词初步": ["古诗名句"],
        "文章结构与详略": ["说明文阅读"],
        "古诗词鉴赏": ["文言文字词初步"],
        "综合阅读与主旨": ["文章结构与详略"],
        "写作手法鉴赏": ["古诗词鉴赏"],
        "文言文阅读": ["文言文字词初步"],
        "综合性学习与语言表达": ["写作手法鉴赏"],
    },
    "英语": {
        "问候语与自我介绍": ["26个字母"],
        "数字1-10": ["26个字母"],
        "颜色": ["数字1-10"],
        "常见动物单词": ["颜色"],
        "家庭成员": ["常见动物单词"],
        "学习用品与教室": ["家庭成员"],
        "简单祈使句": ["学习用品与教室"],
        "食物与饮料": ["学习用品与教室"],
        "一般现在时（第三人称单数）": ["简单祈使句"],
        "时间表达与日常作息": ["数字1-10"],
        "方位介词": ["简单祈使句"],
        "现在进行时": ["一般现在时（第三人称单数）"],
        "天气与季节": ["食物与饮料"],
        "一般过去时（规则动词）": ["现在进行时"],
        "情态动词 can / must": ["简单祈使句"],
        "一般将来时": ["现在进行时"],
        "形容词比较级": ["一般将来时"],
        "频度副词与一般现在时": ["一般现在时（第三人称单数）"],
        "名词单复数与不可数名词": ["食物与饮料"],
        "现在完成时初步": ["一般过去时（规则动词）"],
        "一般过去时（不规则动词）": ["一般过去时（规则动词）"],
        "宾语从句与间接引语": ["现在完成时初步"],
        "阅读理解与完形填空": ["宾语从句与间接引语"],
    },
}


# ---------- 依赖关系工具 ----------

def prerequisites(subject, knowledge):
    """这个知识点的前置知识点（子知识点继承父知识点的前置）。"""
    table = DEPENDENCIES.get(subject) or {}
    direct = list(table.get(knowledge) or [])

    parent = knowledge_tree.subpoint_parent(subject, knowledge)
    if parent:
        for name in table.get(parent) or []:
            if name not in direct:
                direct.append(name)
    if not direct:
        # 新细分出来的知识块没有单独写依赖时，按教材顺序依赖上一块
        key = knowledge_tree.stage_of(subject, knowledge)
        if key and key != stages.START_KEY:
            previous = stages.knowledge_of(subject, stages.prev_key(key))
            if previous and previous != knowledge:
                direct.append(previous)

    return direct


def dependents(subject, knowledge):
    """哪些知识点依赖它（被依赖越多，越是"基础"）。"""
    table = DEPENDENCIES.get(subject) or {}

    result = [name for name, prereqs in table.items() if knowledge in prereqs]
    for child in knowledge_tree.subpoints_of(subject, knowledge):
        if child not in result:
            result.append(child)

    return result


def foundation_weight(subject, knowledge):
    """基础权重 0~1：被 3 个以上知识点依赖就算满分。"""
    return round(min(1.0, len(dependents(subject, knowledge)) / 3.0), 3)


def dependency_chain(subject, knowledge, depth=3):
    """一条可读的依赖链，例如 两步计算应用题 → 表内乘法 → 20以内加减法。"""
    chain = [knowledge]
    current = knowledge

    for _ in range(max(1, int(depth))):
        prereqs = prerequisites(subject, current)
        if not prereqs:
            break
        # 只沿最基础的那条往下走，避免依赖图分叉后变成一大片
        current = sorted(prereqs, key=lambda name: stages.index_of(
            knowledge_tree.stage_of(subject, name) or stages.START_KEY))[0]
        if current in chain:
            break
        chain.append(current)

    return chain


# ---------- 特征计算 ----------

def _as_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
    return None


def _clamp01(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def weakness_of(mastery_score):
    """薄弱度 0~1：掌握度越低越高。从没练过（0 分且无题量）由调用方另行处理。"""
    return _clamp01((100.0 - float(mastery_score or 0)) / 100.0)


def forgetting_risk(item, now=None):
    """遗忘风险 0~1。

    V2.4 起优先用记忆状态（`MemoryState.forgetting_risk`）的实测风险；
    没有记忆状态时退回"到期没复习直接 1.0 / 按多久没练线性上升"的估算。
    """
    now = now or datetime.now()
    total = int(item.get("total_questions") or 0)
    if total <= 0:
        return 0.0

    measured = item.get("forgetting_risk")
    if measured is not None:
        return _clamp01(measured)

    next_review = _as_dt(item.get("next_review_time"))
    if next_review is not None and next_review <= now:
        return 1.0

    last = _as_dt(item.get("last_practice_time"))
    if last is None:
        return 0.0

    idle_days = max(0.0, (now - last).total_seconds() / 86400.0)
    if idle_days <= 0:
        return 0.0
    return _clamp01(idle_days / DECAY_DAYS)


def error_pressure(item, error_counts=None):
    """错误压力 0~1：历史错误率 + 最近错因次数 + 连续答错。"""
    error_counts = error_counts or {}
    knowledge = str(item.get("knowledge_id") or "")

    total = int(item.get("total_questions") or 0)
    wrong = int(item.get("wrong_questions") or 0)
    rate = (wrong / total) if total else 0.0

    recent = int(error_counts.get(knowledge) or 0)
    score = 0.6 * rate + 0.4 * min(1.0, recent / 3.0)

    if int(item.get("consecutive_wrong") or 0) >= 2:
        score += 0.2

    return round(_clamp01(score), 3)


def due_now(item, now=None):
    """这个知识点是不是已经到了该复习的时间。"""
    now = now or datetime.now()
    next_review = _as_dt(item.get("next_review_time"))
    return bool(next_review is not None and next_review <= now)


def tier_of(item, foundation, error, forgetting, now=None):
    """优先级档位 1~5（数字越小越优先）。"""
    total = int(item.get("total_questions") or 0)
    mastery = int(item.get("mastery_score") or 0)

    if total <= 0:
        return 5                                    # 没练过：按能力阶段学新知识
    if mastery < WEAK_LINE:
        return 1                                    # 1. 高价值薄弱
    if foundation >= FOUNDATION_LINE and mastery < CHALLENGE_LINE:
        return 2                                    # 2. 影响后续知识的基础
    if error >= ERROR_LINE:
        return 3                                    # 3. 近期错误频繁
    if forgetting >= 0.5 or due_now(item, now):
        return 4                                    # 4. 即将遗忘
    return 5


def suggest_difficulty(subject, knowledge, ability_score=50, mastery_score=None,
                       hint=None):
    """出题难度：能力分与知识点难度各占一半；有控制器结果时直接采用。"""
    from adaptive.difficulty import clamp_difficulty

    if hint is not None:
        return clamp_difficulty(hint)

    knowledge_difficulty = knowledge_tree.difficulty_of(subject, knowledge)
    base = 0.5 * float(ability_score or 50) + 0.5 * float(knowledge_difficulty)

    mastery = int(mastery_score or 0)
    if mastery <= 0:
        offset = 0
    elif mastery < 50:
        offset = -5          # 太薄弱：先降一点，把信心和正确率稳住
    elif mastery < WEAK_LINE:
        offset = 3           # 需要强化：略高于当前水平，努力一下能做对
    elif mastery >= CHALLENGE_LINE:
        offset = 5           # 已熟练：加难度挑战
    else:
        offset = 0

    return clamp_difficulty(round(base + offset))


# ---------- 策略主体 ----------

class LearningStrategy:
    """学习策略：把学生画像翻译成"下一步做什么"。"""

    def rank(self, profile, now=None, difficulty_hint=None):
        """给所有知识点打分排序（分数越高越该学）。

        返回列表，元素含 knowledge / score / tier / 各项证据 / difficulty / reason。
        """
        subject = str(profile.get("subject") or stages.DEFAULT_SUBJECT)
        now = now or profile.get("now") or datetime.now()
        ability = profile.get("ability") or {}
        ability_score = float(ability.get("score") or 50)
        stage_key = stages.normalize_key(ability.get("stage")) or ""
        error_counts = profile.get("error_counts") or {}
        # 目标阶段：优先能力阶段；还没有任何能力信号时，退回学生年级的「基础」级
        stage_index = None
        if stage_key:
            stage_index = stages.index_of(stage_key)
        elif profile.get("grade"):
            grade = max(1, min(stages.GRADE_COUNT, int(profile.get("grade") or 1)))
            stage_index = (grade - 1) * stages.LEVELS_PER_GRADE

        items = list(profile.get("knowledge") or [])
        if not items:
            return []

        # 先把每个知识点的静态特征算出来，后面算门控要用
        facts = {}
        for item in items:
            knowledge = str(item.get("knowledge_id") or "")
            if not knowledge:
                continue

            foundation = foundation_weight(subject, knowledge)
            error = error_pressure(item, error_counts)
            forgetting = forgetting_risk(item, now)
            facts[knowledge] = {
                "item": item,
                "foundation": foundation,
                "error": error,
                "forgetting": forgetting,
                "tier": tier_of(item, foundation, error, forgetting, now),
            }

        # 依赖门控：前置"练过但没达标"，就把前置顶上来
        blocking = {}
        for knowledge, fact in facts.items():
            item = fact["item"]
            mastery = int(item.get("mastery_score") or 0)
            if int(item.get("total_questions") or 0) <= 0:
                continue

            for prereq in prerequisites(subject, knowledge):
                pre = facts.get(prereq)
                if pre is None:
                    continue
                pre_item = pre["item"]
                pre_total = int(pre_item.get("total_questions") or 0)
                pre_mastery = int(pre_item.get("mastery_score") or 0)
                if pre_total <= 0 or pre_mastery >= READY_LINE:
                    continue
                # V2.6：前置已经练够题量、掌握度也不算差，只是没到 70 线 ——
                # 不再无限期挡住后续知识（否则会永远卡在最基础的一块）
                if (pre_total >= SATURATION_TOTAL
                        and pre_mastery >= SATURATION_MASTERY):
                    continue
                if pre_mastery >= mastery:
                    continue          # 前置并不比它更薄弱，不构成"拦路虎"
                blocking.setdefault(prereq, []).append(knowledge)

        # V2.6：阶段适配度按「这个知识点有没有练过」逐个判断（见下面的 stage_level），
        # 不再要求整科零练习 —— 否则练过几道的科目会被最基础的一块永久锁住

        ranked = []
        for knowledge, fact in facts.items():
            item = fact["item"]
            mastery = int(item.get("mastery_score") or 0)
            total = int(item.get("total_questions") or 0)

            weakness = weakness_of(mastery) if total > 0 else 0.35

            item_stage = stages.normalize_key(item.get("stage") or
                                              knowledge_tree.stage_of(subject, knowledge))
            # 阶段适配度：给「还没练过的知识点」按离当前能力阶段的距离排序
            # （能力阶段已覆盖的先补/承接，超前的压后）
            stage_level = 0.0
            if stage_index is not None and item_stage and total <= 0:
                item_index = stages.index_of(item_stage)
                distance = item_index - stage_index
                if 0 <= distance <= STAGE_LEVEL_SPAN:
                    stage_level = STAGE_LEVEL_BONUS.get(distance, 0.0)
                elif distance < 0:
                    # 能力阶段已经覆盖、却还没练过：按「落后档」加分，优先补齐
                    stage_level = STAGE_LEVEL_BONUS[STAGE_LEVEL_SPAN]
                else:
                    stage_level = -STAGE_LEVEL_AHEAD_PENALTY

            # V2.6：饱和平滑 —— 练了 SATURATION_TOTAL 题以上、掌握度也不差，
            # 却始终到不了 70 线的知识点，不再占「高价值薄弱」的最高档加成
            tier = fact["tier"]
            if (tier == 1 and total >= SATURATION_TOTAL
                    and mastery >= SATURATION_MASTERY):
                tier = 5

            score = (
                TIER_BONUS.get(tier, 0.0)
                + WEIGHTS["weakness"] * weakness
                + WEIGHTS["foundation"] * fact["foundation"]
                + WEIGHTS["error"] * fact["error"]
                + WEIGHTS["forgetting"] * fact["forgetting"]
                + stage_level
            )

            if stage_key and item_stage == stage_key and total <= 0:
                score += STAGE_BONUS
            if mastery >= CHALLENGE_LINE and total > 0:
                score -= CHALLENGE_PENALTY

            blocked_by = blocking.get(knowledge) or []
            if blocked_by:
                score += BLOCK_BONUS

            difficulty = suggest_difficulty(subject, knowledge, ability_score, mastery,
                                            hint=difficulty_hint)

            ranked.append({
                "subject": subject,
                "knowledge": knowledge,
                "knowledge_id": knowledge,
                "mastery": mastery,
                "total": total,
                "confidence": float(item.get("confidence") or 0),
                "weakness": round(weakness, 3),
                "foundation": fact["foundation"],
                "error": fact["error"],
                "forgetting": fact["forgetting"],
                "tier": tier,
                "score": round(score, 4),
                "blocking": blocked_by,
                "blocked_by": "",
                "due": due_now(item, now),
                "practiced": total > 0,
                "difficulty": difficulty,
                "stage": item_stage or knowledge_tree.stage_of(subject, knowledge),
                "stage_level": round(stage_level, 3),
                "chapter": item.get("chapter") or knowledge_tree.domain_of(subject, knowledge),
                "last_practice_time": item.get("last_practice_time"),
                "next_review_time": item.get("next_review_time"),
                "consecutive_wrong": int(item.get("consecutive_wrong") or 0),
            })

        # 被推荐项如果自己被更基础的前置卡住，标出来给理由文案用
        for entry in ranked:
            for prereq in prerequisites(subject, entry["knowledge"]):
                pre = facts.get(prereq)
                if not pre:
                    continue
                pre_item = pre["item"]
                pre_total = int(pre_item.get("total_questions") or 0)
                pre_mastery = int(pre_item.get("mastery_score") or 0)
                if (pre_total > 0 and pre_mastery < READY_LINE
                        and pre_mastery < entry["mastery"]
                        and entry["total"] > 0):
                    entry["blocked_by"] = prereq
                    entry["blocked_mastery"] = pre_mastery
                    break

        ranked.sort(key=lambda entry: (-entry["score"], entry["knowledge"]))
        return ranked

    def choose(self, profile, now=None, difficulty_hint=None, knowledge=None):
        """选出下一步该学什么，返回 next_action。"""
        subject = str(profile.get("subject") or stages.DEFAULT_SUBJECT)
        now = now or profile.get("now") or datetime.now()
        ranked = self.rank(profile, now=now, difficulty_hint=difficulty_hint)

        if not ranked:
            return {
                "student_id": profile.get("student_id"),
                "subject": subject,
                "action": "diagnostic",
                "mode": "diagnostic",
                "knowledge": knowledge_tree.stage_of_any(subject, "") or "",
                "difficulty": 40,
                "reason": "还没有可以练习的知识点，先做一次能力诊断～",
                "priority_score": 0.0,
                "candidates": [],
                "evidence": {},
                "strategy": "LearningStrategy",
            }

        picked = None
        if knowledge:
            picked = next((entry for entry in ranked
                           if entry["knowledge"] == knowledge), None)
        picked = picked or ranked[0]

        ability = profile.get("ability") or {}
        practiced_count = sum(1 for entry in ranked if entry["practiced"])
        ability_stage = stages.normalize_key(ability.get("stage")) or ""

        if practiced_count == 0 and not ability_stage:
            action = "diagnostic"
        elif picked["mastery"] >= CHALLENGE_LINE and picked["practiced"]:
            action = "challenge"
        elif picked["due"] and picked["mastery"] >= READY_LINE:
            action = "review"
        else:
            action = "practice"

        reason = self._reason_of(picked, action, subject, ability)
        entry_difficulty = picked["difficulty"]
        if action == "challenge":
            entry_difficulty = min(100, entry_difficulty + 3)
        elif action == "diagnostic":
            entry_difficulty = 40

        return {
            "student_id": profile.get("student_id"),
            "subject": subject,
            "action": action,
            "mode": action,
            "action_text": ACTION_TEXT.get(action, "强化练习"),
            "knowledge": picked["knowledge"],
            "difficulty": int(entry_difficulty),
            "reason": reason,
            "priority_score": picked["score"],
            "tier": picked["tier"],
            "evidence": {
                "mastery": picked["mastery"],
                "total_questions": picked["total"],
                "weakness": picked["weakness"],
                "foundation": picked["foundation"],
                "error": picked["error"],
                "forgetting": picked["forgetting"],
                "due": picked["due"],
                "blocking": picked["blocking"],
            },
            "stage": picked["stage"],
            "dependency_chain": dependency_chain(subject, picked["knowledge"]),
            "candidates": [
                {"knowledge": entry["knowledge"], "score": entry["score"],
                 "tier": entry["tier"], "mastery": entry["mastery"],
                 "difficulty": entry["difficulty"], "reason": self._reason_of(
                     entry, "challenge" if entry["mastery"] >= CHALLENGE_LINE else "practice",
                     subject, ability),
                 "blocking": entry["blocking"]}
                for entry in ranked[:3]
            ],
            "ranked": ranked,
            "strategy": "LearningStrategy",
        }

    @staticmethod
    def _reason_of(entry, action, subject, ability):
        """一句话说清"为什么推荐这个学习"。"""
        knowledge = entry["knowledge"]
        mastery = entry["mastery"]

        if action == "diagnostic":
            return "还没有练习记录，先做一次能力诊断或练几道基础题"
        if action == "challenge":
            return f"掌握度{mastery}，已经很熟练，做几道更难的题挑战一下"
        if action == "review":
            return f"掌握度{mastery}，已经到复习时间，趁热复习一遍"
        if entry["blocking"]:
            blocked = "、".join(entry["blocking"][:2])
            return f"{knowledge}是{blocked}的基础，掌握度{mastery}，先把这块补牢"
        if entry["total"] <= 0:
            stage_label = stages.label(entry["stage"]) if entry["stage"] else ""
            tail = f"（{stage_label}）" if stage_label else ""
            return f"{knowledge}还没练过，是当前能力阶段的重点{tail}"
        if entry.get("blocked_by"):
            return (f"{knowledge}掌握度{mastery}，但它依赖"
                    f"{entry['blocked_by']}（{entry.get('blocked_mastery', 0)}分），先练基础更划算")
        return f"掌握度{mastery}，需要强化"


DEFAULT_STRATEGY = LearningStrategy()
