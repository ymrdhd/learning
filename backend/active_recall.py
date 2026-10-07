# ==============================================================
# 能力契约｜主动回忆基础系统（闪卡式回忆检测：内置卡片库 + 判分 + 记忆增益）
# 入口：DEFAULT_ENGINE / ActiveRecallEngine / card_bank / card_dict / judge / child_level / hint_for / hint_ladder / hint_level_text / recall_evidence / start / answer / hint
# 依赖：models（ActiveRecallRecord / AnswerRecord / KnowledgeMemoryState）、knowledge_routes.update_mastery、
#       review.engine（DEFAULT_ENGINE.record_learning / state_row / refresh_risks）、review.memory、knowledge_tree
# 不负责：题目生成与审核 → recovery/variant_generator.py + validator.py；错题康复 → recovery/；每日任务 → habit.py
# 验证：python backend/verify_active_recall.py
# 被调用：active_recall_routes.py、daily_routes.py、main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 主动回忆基础系统（需求 §21-§22）。

主动回忆 = 只给提示语（``prompt``），让学生**自己输入**答案，**不给任何选择项**。
适合：英语单词 / 语文字词 / 古诗基础 / 公式 / 概念 / 数学基础知识。

链路（沿用既有唯一写入口，不另建第二套）：

    start()  → 按薄弱与到期程度选卡（排除最近做过的卡）
    answer() → judge 判分 → 写 active_recall_record
             → 写 answer_records → knowledge_routes.update_mastery（掌握度唯一写入口）
             → review.engine.record_learning（记忆状态唯一写入口）
             → 记忆稳定性增益：完全独立回忆成功增益高，依赖提示后成功增益低

纪律：一切按 ``student_id`` 隔离；主动回忆**不写 wrong_questions**（答错不等于错题本错题，
不进错题康复流水线）；DeepSeek 不参与，离线可用；内部异常由接口层兜住，绝不 500。
"""

import re
import unicodedata
from datetime import datetime, timedelta

import knowledge_routes
from models import ActiveRecallRecord, AnswerRecord, KnowledgeMemoryState
from review import memory
from review.engine import DEFAULT_ENGINE as REVIEW_ENGINE

# --------------------------------------------------------------
# 文案与阈值
# --------------------------------------------------------------

RESULT_TEXT = {
    "correct": "想起来啦！",
    "partial": "有点像了，再想完整一点",
    "wrong": "这个还没记牢，我们再看一次",
}

KIND_TEXT = {
    "word": "单词",
    "phrase": "字词",
    "poem": "古诗",
    "formula": "公式",
    "concept": "概念",
    "basic": "数学基础",
}

SUBJECTS = ("数学", "语文", "英语")

BASE_GAIN = 3.0                 # 完全独立回忆成功 → 稳定性 +3 天
# V2.7 主动回忆 2.0：Recall Hint Ladder（需求 §十八）
# 证据强度：无提示成功最强；越依赖高级提示，证据越弱。这里的 weight 同时用于
# ①记忆稳定性增益 ②写 learning_evidence 时传给 deep_learning.evidence 的提示折减。
EVIDENCE_TYPE = "RECALL"
MAX_HINT_LEVEL = 4
HINT_LADDER = [
    {"level": 0, "key": "none", "name": "无提示", "child": "自己想，不看提示",
     "weight": 1.00, "note": "无提示主动回忆成功 → 最强证据"},
    {"level": 1, "key": "keyword", "name": "关键词", "child": "给你一个关键词",
     "weight": 0.60, "note": "关键词提示后成功 → 中等证据"},
    {"level": 2, "key": "structure", "name": "部分结构", "child": "给你答案的开头",
     "weight": 0.45, "note": "部分结构后成功 → 偏弱证据"},
    {"level": 3, "key": "choice", "name": "选择提示", "child": "从几个答案里选一个",
     "weight": 0.30, "note": "选择提示后成功 → 弱证据（接近再认）"},
    {"level": 4, "key": "answer", "name": "完整答案", "child": "直接看答案",
     "weight": 0.20, "note": "看答案后成功 → 最弱证据，只能算再学习"},
]
HINT_LADDER_BY_LEVEL = {step["level"]: step for step in HINT_LADDER}
HINT_FACTOR = {step["level"]: step["weight"] for step in HINT_LADDER}
PARTIAL_FACTOR = 0.5            # 部分回忆 → 增益减半
WRONG_FACTOR = 0.7              # 回忆失败 → 稳定性打折
STABILITY_FLOOR = 0.5
WEAK_LINE = 60                  # 记忆强度低于该值视为薄弱，优先出卡
DEFAULT_COUNT = 3
MAX_COUNT = 10
CONFIDENCE = {"correct": 0.9, "partial": 0.45, "wrong": 0.2}
HINT_LINE = {"correct": 0.6, "partial": 0.4, "wrong": 0.2}

_NORM_DROP = re.compile(r"[\s，。、；：！？“”‘’（）()《》〈〉·,.;:!?\"'`]")

# --------------------------------------------------------------
# 内置卡片库（离线可用；knowledge 与知识点树名称一致才能接进掌握度与记忆状态）
# --------------------------------------------------------------

CARD_BANK = [
    # ---- 数学：公式 / 概念 / 基础 ----
    {"id": "m_area_circle", "subject": "数学", "knowledge": "圆的周长与面积", "kind": "formula",
     "prompt": "圆的面积公式是什么？", "answers": ["S=πr²", "πr²", "圆周率×半径×半径", "π×半径×半径"],
     "hint": "圆的面积和半径的平方有关。"},
    {"id": "m_area_parallelogram", "subject": "数学", "knowledge": "平行四边形与梯形面积", "kind": "formula",
     "prompt": "平行四边形的面积公式是什么？", "answers": ["底×高", "S=ah", "ah", "底乘高"],
     "hint": "把平行四边形转化成长方形想一想。"},
    {"id": "m_distributive", "subject": "数学", "knowledge": "运算定律与简便计算", "kind": "formula",
     "prompt": "乘法分配律用字母怎么表示？", "answers": ["(a+b)×c=a×c+b×c", "a×c+b×c"],
     "hint": "括号里的两个数分别和外面的数相乘，再相加。"},
    {"id": "m_commutative_add", "subject": "数学", "knowledge": "加法运算定律", "kind": "concept",
     "prompt": "加法交换律说的是什么？", "answers": ["a+b=b+a", "交换两个加数的位置，和不变"],
     "hint": "只交换位置，和不变。"},
    {"id": "m_perimeter_rect", "subject": "数学", "knowledge": "长方形与正方形的周长", "kind": "formula",
     "prompt": "长方形的周长怎么算？", "answers": ["(长+宽)×2", "长×2+宽×2"],
     "hint": "沿着长方形走一圈，是两条长加两条宽。"},
    {"id": "m_fraction_denominator", "subject": "数学", "knowledge": "分数初步认识", "kind": "concept",
     "prompt": "分数里的分母表示什么？", "answers": ["平均分成的份数", "把整体平均分成几份", "分的份数"],
     "hint": "分母是把一个整体平均分成几份。"},
    {"id": "m_decimal_tenth", "subject": "数学", "knowledge": "小数的意义与性质", "kind": "concept",
     "prompt": "0.1 表示几分之几？", "answers": ["十分之一", "1/10"],
     "hint": "小数点后面第一位是十分位。"},
    {"id": "m_equation_property", "subject": "数学", "knowledge": "简易方程", "kind": "concept",
     "prompt": "等式的基本性质是什么？", "answers": ["等式两边同时加上或减去同一个数，等式仍然成立", "两边同时加或减同一个数等式不变"],
     "hint": "像天平一样，两边做同样的处理才保持平衡。"},
    # ---- 语文：字词 / 古诗 / 概念 ----
    {"id": "c_poem_jingyesi", "subject": "语文", "knowledge": "古诗名句", "kind": "poem",
     "prompt": "《静夜思》里“举头望明月”的下一句是什么？", "answers": ["低头思故乡"],
     "hint": "诗人在思念自己的家乡。"},
    {"id": "c_poem_chunxiao", "subject": "语文", "knowledge": "古诗名句", "kind": "poem",
     "prompt": "《春晓》的第一句是什么？", "answers": ["春眠不觉晓"],
     "hint": "说的是春天睡觉，不知不觉天就亮了。"},
    {"id": "c_antonym_gao", "subject": "语文", "knowledge": "反义词", "kind": "phrase",
     "prompt": "“高”的反义词是什么？", "answers": ["矮", "低"],
     "hint": "和“高”意思相反。"},
    {"id": "c_idiom_shouzhu", "subject": "语文", "knowledge": "成语积累", "kind": "concept",
     "prompt": "“守株待兔”告诉我们什么道理？", "answers": ["不能靠运气", "不能不劳而获", "不要心存侥幸", "不能死守经验"],
     "hint": "那个农夫一直守在树桩旁边等兔子。"},
    {"id": "c_punct_question", "subject": "语文", "knowledge": "标点符号", "kind": "concept",
     "prompt": "表示疑问的标点符号是什么？", "answers": ["问号", "？", "?"],
     "hint": "读这种句子时语气会往上扬。"},
    {"id": "c_pinyin_blend", "subject": "语文", "knowledge": "拼音拼读", "kind": "phrase",
     "prompt": "“妈”的声母是什么？", "answers": ["m", "M"],
     "hint": "读「妈」时，嘴唇先闭一下再张开。"},
    {"id": "c_synonym_meili", "subject": "语文", "knowledge": "近义词", "kind": "phrase",
     "prompt": "“美丽”的近义词是什么？", "answers": ["漂亮", "好看", "优美"],
     "hint": "意思相近的形容词。"},
    {"id": "c_stroke_shi", "subject": "语文", "knowledge": "笔画与笔顺", "kind": "concept",
     "prompt": "写“十”字的笔顺是先写什么，再写什么？", "answers": ["先横后竖"],
     "hint": "先写上面那一横。"},
    # ---- 英语：单词 / 句型 / 语法 ----
    {"id": "e_apple", "subject": "英语", "knowledge": "食物", "kind": "word",
     "prompt": "apple 是什么意思？", "answers": ["苹果"],
     "hint": "一种常见的水果。"},
    {"id": "e_three", "subject": "英语", "knowledge": "数字 1-5", "kind": "word",
     "prompt": "three 是什么意思？", "answers": ["三", "3"],
     "hint": "比 two 多一。"},
    {"id": "e_mother", "subject": "英语", "knowledge": "家庭称呼", "kind": "word",
     "prompt": "mother 是什么意思？", "answers": ["妈妈", "母亲"],
     "hint": "家里最亲近的女性长辈。"},
    {"id": "e_good_morning", "subject": "英语", "knowledge": "问候语与自我介绍", "kind": "phrase",
     "prompt": "“早上好”用英语怎么说？", "answers": ["Good morning"],
     "hint": "一天开始时的问候语。"},
    {"id": "e_cat", "subject": "英语", "knowledge": "常见动物单词", "kind": "word",
     "prompt": "cat 是什么意思？", "answers": ["猫"],
     "hint": "会喵喵叫的小动物。"},
    {"id": "e_book", "subject": "英语", "knowledge": "学习用品", "kind": "word",
     "prompt": "book 是什么意思？", "answers": ["书", "书本"],
     "hint": "可以读的东西。"},
    {"id": "e_go_third", "subject": "英语", "knowledge": "一般现在时（第三人称单数）", "kind": "basic",
     "prompt": "He ___ to school every day.（用 go 的正确形式填空）", "answers": ["goes"],
     "hint": "主语是 he，动词要变化。"},
    {"id": "e_child_plural", "subject": "英语", "knowledge": "名词单复数与不可数名词", "kind": "word",
     "prompt": "child 的复数形式是什么？", "answers": ["children"],
     "hint": "这是一个不规则复数。"},
    # ---- V2.7 主动回忆 2.0 扩充：公式 / 古诗 / 字词 / 单词 / 语法规则 ----
    {"id": "m_area_triangle", "subject": "数学", "knowledge": "三角形的面积", "kind": "formula",
     "prompt": "三角形的面积公式是什么？", "answers": ["底×高÷2", "S=ah÷2", "ah÷2"],
     "hint": "想一想两个完全一样的三角形可以拼成什么图形。"},
    {"id": "m_circle_radius", "subject": "数学", "knowledge": "圆的认识", "kind": "concept",
     "prompt": "在同一个圆里，直径和半径是什么关系？", "answers": ["直径是半径的2倍", "d=2r", "直径=2×半径"],
     "hint": "直径穿过圆心，半径只到圆心。"},
    {"id": "m_associative_mul", "subject": "数学", "knowledge": "乘法运算定律", "kind": "formula",
     "prompt": "乘法结合律用字母怎么表示？", "answers": ["（a×b）×c=a×（b×c）", "(a×b)×c=a×(b×c)", "a×b×c"],
     "hint": "先乘前两个数和先乘后两个数，积不变。"},
    {"id": "m_equation_balance", "subject": "数学", "knowledge": "等式的性质与解方程", "kind": "concept",
     "prompt": "解方程 x+5=12，两边要同时做什么？", "answers": ["同时减去5", "两边同时减5", "减去5"],
     "hint": "要让左边的 +5 消失，两边做同样的运算。"},
    {"id": "c_poem_yonge", "subject": "语文", "knowledge": "古诗名句", "kind": "poem",
     "prompt": "《咏鹅》的第一句是什么？", "answers": ["鹅鹅鹅"],
     "hint": "开头连着叫了三声。"},
    {"id": "c_poem_lushan", "subject": "语文", "knowledge": "古诗名句", "kind": "poem",
     "prompt": "《望庐山瀑布》里“飞流直下三千尺”的下一句是什么？", "answers": ["疑是银河落九天"],
     "hint": "诗人把瀑布想象成天上的银河。"},
    {"id": "c_duoyin_chang", "subject": "语文", "knowledge": "多音字", "kind": "phrase",
     "prompt": "“长大”里的“长”读什么？", "answers": ["zhǎng", "zhang"],
     "hint": "表示“生长”的意思时读第三声。"},
    {"id": "c_rhetoric_simile", "subject": "语文", "knowledge": "修辞手法初步", "kind": "concept",
     "prompt": "“弯弯的月亮像小船”用了什么修辞手法？", "answers": ["比喻", "比喻句"],
     "hint": "把一样东西比作另一样东西。"},
    {"id": "c_idiom_huashe", "subject": "语文", "knowledge": "成语积累", "kind": "concept",
     "prompt": "“画蛇添足”告诉我们什么道理？", "answers": ["多做反而坏事", "不要多此一举", "做多余的事反而不好"],
     "hint": "给蛇画上脚，是多做的事情。"},
    {"id": "e_red", "subject": "英语", "knowledge": "颜色", "kind": "word",
     "prompt": "red 是什么意思？", "answers": ["红色", "红"],
     "hint": "苹果和国旗的颜色。"},
    {"id": "e_rainy", "subject": "英语", "knowledge": "天气", "kind": "word",
     "prompt": "rainy 是什么意思？", "answers": ["下雨的", "多雨的", "雨天"],
     "hint": "它和 rain 有关。"},
    {"id": "e_pencil", "subject": "英语", "knowledge": "学习用品与教室", "kind": "word",
     "prompt": "pencil 是什么意思？", "answers": ["铅笔"],
     "hint": "用来写字的东西。"},
    {"id": "e_play_past", "subject": "英语", "knowledge": "一般过去时（规则动词）", "kind": "basic",
     "prompt": "He ___ (play) football yesterday.（用 play 的正确形式填空）", "answers": ["played"],
     "hint": "这是一般过去时，规则动词要加 -ed。"},
    {"id": "e_read_ing", "subject": "英语", "knowledge": "现在进行时", "kind": "basic",
     "prompt": "She is ___ (read) a book now.（用 read 的正确形式填空）", "answers": ["reading"],
     "hint": "be 动词后面要用现在分词。"},
]

CARD_BY_ID = {card["id"]: card for card in CARD_BANK}


def hint_ladder():
    """Recall Hint Ladder 全貌（只含儿童可读文案，不含任何答案）。"""
    return [{"level": step["level"], "key": step["key"],
             "name": step["name"], "text": step["child"], "note": step["note"]}
            for step in HINT_LADDER]


def hint_level_text(level):
    """某一级提示的儿童文案。"""
    value = _clamp_level(level)
    step = HINT_LADDER_BY_LEVEL[value]
    return step["child"] if value else "自己想的"


def _clamp_level(level):
    value = int(level or 0)
    return 0 if value < 0 else (MAX_HINT_LEVEL if value > MAX_HINT_LEVEL else value)


def _mask(answer):
    """部分结构：保留首字，其余用 ○ 遮住。"""
    text = str(answer or "")
    if not text:
        return "○"
    if len(text) <= 1:
        return text + "○"
    return text[0] + "○" * (len(text) - 1)


def _choice_options(card, count=3):
    """选择提示（level 3）：正确答案 + 同科目其它卡片答案作为干扰项，顺序确定性打乱。"""
    answers = [str(item) for item in (card.get("answers") or []) if str(item).strip()]
    correct = answers[0] if answers else ""
    pool = []
    for other in CARD_BANK:
        if other.get("id") == card.get("id") or other.get("subject") != card.get("subject"):
            continue
        value = str((other.get("answers") or [""])[0])
        if value and value != correct and value not in pool:
            pool.append(value)
    seed = sum(ord(ch) for ch in str(card.get("id") or "")) or 1
    picked = []
    guard = 0
    while len(picked) < max(0, count - 1) and pool and guard < len(pool) * 4:
        seed = (seed * 7 + 3) % len(pool)
        value = pool[seed]
        if value not in picked:
            picked.append(value)
        guard += 1
    options = [correct] + picked if correct else list(picked)
    if len(options) > 1:
        shift = seed % len(options)
        options = options[shift:] + options[:shift]
    return options


def hint_for(card, level=0):
    """取某一级回忆提示（Recall Hint Ladder，需求 §十八）。

    给前端的只有提示文本：level 0 无提示 / 1 关键词 / 2 部分结构 / 3 选择提示 /
    4 完整答案。除 level 4 外任何一级都不会下发完整答案。
    """
    card = card or {}
    value = _clamp_level(level)
    step = HINT_LADDER_BY_LEVEL[value]
    answers = [str(item) for item in (card.get("answers") or []) if str(item).strip()]
    main = answers[0] if answers else ""
    payload = {}
    if value == 1:
        text = str(card.get("hint") or "先想一想，它属于哪个知识。")
    elif value == 2:
        payload["structure"] = _mask(main)
        payload["length"] = len(main)
        text = "答案一共 %d 个字，开头是「%s」：%s" % (len(main), main[:1], _mask(main))
    elif value == 3:
        options = _choice_options(card)
        payload["options"] = options
        text = "从下面几个答案里选出正确的那个：" + "／".join(options)
    elif value >= MAX_HINT_LEVEL:
        payload["answer"] = main
        text = "完整答案是：%s" % (" / ".join(answers) if answers else "（暂无）")
    else:
        text = "自己想一想，先不要看提示。"
    return {
        "card_id": card.get("id", ""),
        "level": value,
        "level_key": step["key"],
        "level_name": step["name"],
        "level_text": step["child"],
        "text": text,
        "kind": card.get("kind", ""),
        "reveal_answer": value >= MAX_HINT_LEVEL,
        "weight": step["weight"],
        "note": step["note"],
        "payload": payload,
        "ladder": hint_ladder(),
    }


def recall_evidence(result, hint_level=0, confidence_feedback=""):
    """把一次回忆结果翻译成 Learning Evidence 参数（写库由 deep_learning.engine 负责）。"""
    value = _clamp_level(hint_level)
    return {
        "evidence_type": EVIDENCE_TYPE,
        "result": result if result in ("correct", "partial", "wrong") else "wrong",
        "hint_level": value,
        "confidence": str(confidence_feedback or ""),
        "weight_hint": HINT_FACTOR.get(value, HINT_FACTOR[MAX_HINT_LEVEL]),
        "hint_text": hint_level_text(value),
    }

def card_bank(subject=None):
    """按科目取卡片（不传科目 → 全部）。"""
    if not subject:
        return list(CARD_BANK)
    return [card for card in CARD_BANK if card["subject"] == subject]


def card_dict(card):
    """给前端的题面：**只给提示语，不给答案与选项**。"""
    return {
        "card_id": card["id"],
        "subject": card["subject"],
        "knowledge": card["knowledge"],
        "kind": card["kind"],
        "kind_text": KIND_TEXT.get(card["kind"], card["kind"]),
        "prompt": card["prompt"],
        "hint": card.get("hint", ""),
    }


def _norm(text):
    value = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    return _NORM_DROP.sub("", value)


def judge(card, answer):
    """判分：``correct`` / ``partial`` / ``wrong``（只看标准答案集合，不需要选择题）。"""
    text = _norm(answer)
    if not text or not card:
        return "wrong"

    targets = [_norm(item) for item in (card.get("answers") or []) if _norm(item)]
    for target in targets:
        if text == target or (len(target) >= 2 and target in text):
            return "correct"

    best = 0.0
    for target in targets:
        overlap = len(set(text) & set(target))
        if target:
            best = max(best, overlap / float(len(set(target))))
    return "partial" if best >= 0.6 else "wrong"


def child_level(mastery_score, stability=0.0):
    """把真实数值翻译成儿童能懂的四档成长反馈（调试/家长接口仍返回真实数据）。"""
    mastery = float(mastery_score or 0)
    value = float(stability or 0)
    if value >= memory.LONG_TERM_STABILITY:
        return {"key": "long_term", "icon": "⭐", "text": "记得很牢"}
    if mastery >= memory.STABLE_LINE:
        return {"key": "mastered", "icon": "🌳", "text": "已经掌握"}
    if mastery >= memory.RELEARN_LINE:
        return {"key": "basic", "icon": "🌿", "text": "基本会了"}
    return {"key": "learning", "icon": "🌱", "text": "正在学习"}


def _mastery_of(outcome):
    if outcome is None:
        return None
    value = outcome.get("mastery_score") if isinstance(outcome, dict) else getattr(outcome, "mastery_score", None)
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _day_bounds(day=None):
    if not day:
        moment = datetime.now()
    elif isinstance(day, datetime):
        moment = day
    else:
        moment = datetime.strptime(str(day)[:10], "%Y-%m-%d")
    start = datetime(moment.year, moment.month, moment.day)
    return start, start + timedelta(days=1)


class ActiveRecallEngine:
    """主动回忆门面（SPEC §7.3）。"""

    # ---------------- 选卡 ----------------

    def weak_knowledge(self, db, student_id, now=None):
        """薄弱或已到复习期的知识点名称集合（失败时退化为空集，不影响出卡）。"""
        now = now or datetime.now()
        names = set()
        try:
            rows = db.query(KnowledgeMemoryState).filter(
                KnowledgeMemoryState.student_id == student_id).all()
            for row in rows:
                due = isinstance(row.next_review_at, datetime) and row.next_review_at <= now
                if row.needs_relearn or int(row.memory_strength or 0) < WEAK_LINE or due:
                    if row.knowledge_id:
                        names.add(str(row.knowledge_id))
        except Exception:                          # noqa: BLE001 - 选卡降级，不阻塞
            return names
        return names

    def recent_ids(self, db, student_id, limit=12):
        ids = []
        try:
            rows = (db.query(ActiveRecallRecord)
                    .filter(ActiveRecallRecord.student_id == student_id)
                    .order_by(ActiveRecallRecord.id.desc())
                    .limit(limit).all())
            ids = [row.card_id for row in rows if row.card_id]
        except Exception:                          # noqa: BLE001
            return []
        return ids

    def pick(self, db, student_id, subject=None, count=DEFAULT_COUNT, date=None):
        pool = card_bank(subject) or list(CARD_BANK)
        recent = set(self.recent_ids(db, student_id))
        weak = self.weak_knowledge(db, student_id)
        fresh = [card for card in pool if card["id"] not in recent]
        candidates = fresh or pool
        ranked = sorted(candidates, key=lambda card: (0 if card["knowledge"] in weak else 1, card["id"]))
        total = max(1, min(MAX_COUNT, int(count or DEFAULT_COUNT)))
        return ranked[:total]

    # ---------------- 开始 ----------------

    def start(self, db, student_id, *, subject=None, count=DEFAULT_COUNT, date=None):
        cards = self.pick(db, student_id, subject=subject, count=count, date=date)
        minutes = max(1, len(cards))
        return {
            "student_id": student_id,
            "subject": subject or "综合",
            "count": len(cards),
            "minutes": minutes,
            "mode": "ACTIVE_RECALL",
            "message": "先自己想一想，再直接把答案写出来～想不起来可以要提示，菲比会一级一级帮你。",
            "hint_ladder": hint_ladder(),
            "cards": [card_dict(card) for card in cards],
        }

    # ---------------- 回忆提示阶梯（V2.7 §十八） ----------------

    def hint(self, card_id, level=0):
        """取某一级提示；找不到卡片返回 None（接口层会退化为空结构）。"""
        card = CARD_BY_ID.get(str(card_id or "").strip())
        if card is None:
            return None
        data = hint_for(card, level)
        data["subject"] = card.get("subject", "")
        data["knowledge"] = card.get("knowledge", "")
        data["prompt"] = card.get("prompt", "")
        return data

    def ladder(self):
        return hint_ladder()

    # ---------------- 作答 ----------------

    def _gain(self, result, level):
        factor = HINT_FACTOR.get(int(level or 0), HINT_FACTOR[4])
        if result == "correct":
            return BASE_GAIN * factor
        if result == "partial":
            return BASE_GAIN * factor * PARTIAL_FACTOR
        return 0.0

    def _apply_gain(self, db, student_id, subject, knowledge, gain, result, now=None):
        """把回忆结果落到记忆状态：成功加稳定性，失败打折。返回 (实际增益, 稳定性)。"""
        state = REVIEW_ENGINE.state_row(db, student_id, subject, knowledge)
        if state is None:
            return 0.0, 0.0
        old = float(state.stability or 0.0)
        if result == "wrong":
            new = max(STABILITY_FLOOR, old * WRONG_FACTOR)
        else:
            new = min(memory.STABILITY_MAX, old + float(gain or 0.0))
        state.stability = round(new, 2)
        try:
            REVIEW_ENGINE.refresh_risks(db, student_id, rows=[state], now=now, force=True)
        except Exception:                          # noqa: BLE001
            pass
        return round(new - old, 2), round(new, 2)

    def answer(self, db, student_id, card_id, answer, *, response_time=0, hint_level=0,
               confidence_feedback="", when=None):
        """提交一次主动回忆；返回判分、期望答案、记忆增益与儿童反馈（找不到卡片返回 None）。"""
        card = CARD_BY_ID.get(str(card_id or "").strip())
        if card is None:
            return None

        now = when or datetime.now()
        level = int(hint_level or 0)
        level = 0 if level < 0 else (4 if level > 4 else level)
        result = judge(card, answer)
        correct = result == "correct"
        gain = self._gain(result, level)

        row = ActiveRecallRecord(
            student_id=student_id,
            subject=card["subject"],
            knowledge=card["knowledge"],
            card_id=card["id"],
            kind=card["kind"],
            prompt=card["prompt"],
            answer=str(answer or ""),
            expected=" / ".join(card["answers"]),
            result=result,
            hint_level=level,
            response_time=int(response_time or 0),
            confidence_feedback=str(confidence_feedback or ""),
            memory_gain=round(gain, 2),
            created_at=now,
        )
        db.add(row)

        db.add(AnswerRecord(
            student_id=student_id,
            subject=card["subject"],
            knowledge=card["knowledge"],
            difficulty=1,
            correct=correct,
            question_id=None,
            submitted=str(answer or ""),
            created_at=now,
        ))
        db.flush()

        mastery = None
        try:
            mastery = _mastery_of(knowledge_routes.update_mastery(
                db, student_id, card["subject"], card["knowledge"]))
        except Exception:                          # noqa: BLE001 - 掌握度失败不影响回忆记录
            mastery = None

        confidence = HINT_LINE.get(result, 0.2) if level else CONFIDENCE.get(result, 0.2)
        try:
            REVIEW_ENGINE.record_learning(
                db, student_id, card["subject"], card["knowledge"],
                mastery_score=mastery, confidence=confidence, correct=correct, when=now)
        except Exception:                          # noqa: BLE001 - 记忆状态失败不影响判分
            pass

        applied, stability = 0.0, 0.0
        try:
            applied, stability = self._apply_gain(
                db, student_id, card["subject"], card["knowledge"], gain, result, now=now)
        except Exception:                          # noqa: BLE001
            applied, stability = 0.0, 0.0

        try:
            db.commit()
        except Exception:                          # noqa: BLE001
            db.rollback()

        return {
            "student_id": student_id,
            "card_id": card["id"],
            "subject": card["subject"],
            "knowledge": card["knowledge"],
            "kind": card["kind"],
            "kind_text": KIND_TEXT.get(card["kind"], card["kind"]),
            "prompt": card["prompt"],
            "answer": str(answer or ""),
            "expected": list(card["answers"]),
            "result": result,
            "result_text": RESULT_TEXT.get(result, ""),
            "correct": correct,
            "hint_level": level,
            "response_time": int(response_time or 0),
            "memory_gain": round(applied, 2),
            "stability": stability,
            "mastery_score": mastery,
            "child": child_level(mastery, stability),
            "hint": "" if correct else card.get("hint", ""),
            "hint_level_text": hint_level_text(level),
            # V2.7：这次回忆属于哪一类学习证据、证据强度如何（接口层据此写 learning_evidence）
            "evidence": recall_evidence(result, level, confidence_feedback),
            "used_hint": level > 0,
        }

    # ---------------- 汇总 ----------------

    def history(self, db, student_id, day=None, limit=50):
        start, end = _day_bounds(day)
        try:
            rows = (db.query(ActiveRecallRecord)
                    .filter(ActiveRecallRecord.student_id == student_id,
                            ActiveRecallRecord.created_at >= start,
                            ActiveRecallRecord.created_at < end)
                    .order_by(ActiveRecallRecord.id.desc())
                    .limit(limit).all())
        except Exception:                          # noqa: BLE001
            return []
        return [{"card_id": row.card_id, "subject": row.subject, "knowledge": row.knowledge,
                 "prompt": row.prompt, "result": row.result, "hint_level": row.hint_level,
                 "response_time": row.response_time, "memory_gain": float(row.memory_gain or 0.0),
                 "created_at": row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else ""}
                for row in rows]

    def summary(self, db, student_id, day=None):
        """当天主动回忆小结（供每日完成页与 daily-summary 使用）。"""
        start, _end = _day_bounds(day)
        items = self.history(db, student_id, day=day)
        correct = sum(1 for item in items if item["result"] == "correct")
        partial = sum(1 for item in items if item["result"] == "partial")
        wrong = sum(1 for item in items if item["result"] == "wrong")
        seconds = sum(int(item["response_time"] or 0) for item in items)
        minutes = int(round(seconds / 60.0)) if seconds else len(items)
        total = len(items)
        return {
            "student_id": student_id,
            "date": start.strftime("%Y-%m-%d"),
            "total": total,
            "correct": correct,
            "partial": partial,
            "wrong": wrong,
            "accuracy": round(correct / float(total), 4) if total else 0.0,
            "minutes": minutes,
            "items": items,
        }


DEFAULT_ENGINE = ActiveRecallEngine()
