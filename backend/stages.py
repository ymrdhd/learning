# ==============================================================
# 能力契约｜能力阶段与知识点的**唯一来源**：72 阶段（1.1~6.12）、难度映射、三科×72 知识点、升降阈值
# 入口：all_keys / normalize_key / key_of / label / difficulty_of / knowledge_of / next_key / prev_key / advance / stars / parent_key / legacy_key / SUBJECTS / KNOWLEDGE
# 依赖：无（纯标准库）
# 不负责：知识点树结构 → knowledge_tree.py；难度动态调整 → adaptive/difficulty.py
# 验证：python backend/verify_diagnostic.py（+ 全套）
# 被调用：几乎全部后端模块（改动影响面最大）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.0 能力阶段模型：72 个能力阶段（纯函数，方便直接单测）。

设计要点：
1. 能力阶段不是"学生所在年级"，而是"学生真实答出来的水平"，
   用 "年级.等级" 表示，例如 3.2 = 三年级熟练阶段。
2. 全部阶段排成一条 0~23 的线性坐标（index），
   所有推进/回退都在 index 上做，再换回 "3.2" 这样的可读字符串。
3. 阶段到难度的映射是单调递增的，供出题难度、知识点权重使用。
"""

# 每个学年 12 个能力等级：上册 6 块 + 下册 6 块，对应人教版教材一学期的单元块
LEVELS = ("上册一", "上册二", "上册三", "上册四", "上册五", "上册六",
          "下册一", "下册二", "下册三", "下册四", "下册五", "下册六")
GRADE_NAMES = ("一", "二", "三", "四", "五", "六")

GRADE_COUNT = 6
LEVELS_PER_GRADE = len(LEVELS)
MAX_INDEX = GRADE_COUNT * LEVELS_PER_GRADE - 1     # 71

# 一年级基础 ~ 六年级挑战 对应的难度区间（0~100）
MIN_DIFFICULTY = 15
MAX_DIFFICULTY = 95

# 各科目在每个阶段主要考察的知识点，出题与知识点画像都按它来
KNOWLEDGE = {
    # 每科 72 个知识块：每年级 12 块（上册 6 + 下册 6）。
    # 每个「原 4 等级」大知识点拆成 3 块，大知识点本身固定落在第 1/4/7/10 块，
    # 保证旧库里的知识点名称仍然有效；第 2/3、5/6、8/9、11/12 块是更细的教材内容。
    "数学": {
        # 一年级上册
        "1.1": "20以内加减法", "1.2": "10以内加减法", "1.3": "20以内进位加法",
        # 一年级下册
        "1.4": "100以内加减法", "1.5": "100以内数的认识", "1.6": "100以内进位与退位加减法",
        "1.7": "连加连减与加减混合", "1.8": "连加连减", "1.9": "加减混合运算",
        "1.10": "认识图形与简单应用", "1.11": "认识平面图形", "1.12": "认识立体图形",
        # 二年级上册
        "2.1": "表内乘法", "2.2": "乘法的初步认识", "2.3": "2~6的乘法口诀",
        "2.4": "表内除法", "2.5": "除法的初步认识", "2.6": "用乘法口诀求商",
        "2.7": "两步计算应用题", "2.8": "先乘后加减的两步计算", "2.9": "先除后加减的两步计算",
        "2.10": "长度单位与测量", "2.11": "认识厘米和米", "2.12": "线段与角的初步认识",
        # 三年级上册
        "3.1": "多位数乘一位数", "3.2": "口算乘法", "3.3": "笔算乘法",
        "3.4": "两位数除法", "3.5": "口算除法", "3.6": "笔算除法与验算",
        "3.7": "分数初步认识", "3.8": "认识几分之几", "3.9": "同分母分数加减法",
        "3.10": "长方形与正方形的周长", "3.11": "四边形的认识", "3.12": "长方形和正方形的周长",
        # 四年级上册
        "4.1": "大数认识与四则运算", "4.2": "亿以内数的认识", "4.3": "四则运算的顺序",
        "4.4": "运算定律与简便计算", "4.5": "加法运算定律", "4.6": "乘法运算定律",
        "4.7": "小数的意义与加减法", "4.8": "小数的意义和性质", "4.9": "小数的加法和减法",
        "4.10": "平行四边形与梯形面积", "4.11": "平行与垂直", "4.12": "平行四边形和梯形的面积",
        # 五年级上册
        "5.1": "小数乘除法", "5.2": "小数乘法", "5.3": "小数除法",
        "5.4": "简易方程", "5.5": "用字母表示数量关系", "5.6": "等式的性质与解方程",
        "5.7": "因数与倍数", "5.8": "因数和倍数", "5.9": "质数与合数",
        "5.10": "多边形面积与组合图形", "5.11": "三角形的面积", "5.12": "组合图形的面积",
        # 六年级上册
        "6.1": "分数乘除法", "6.2": "分数乘法", "6.3": "分数除法",
        "6.4": "比与比例", "6.5": "比的意义和基本性质", "6.6": "比例和比例尺",
        "6.7": "圆的周长与面积", "6.8": "圆的认识", "6.9": "圆的周长和面积",
        "6.10": "百分数与统计", "6.11": "百分数的意义和计算", "6.12": "统计与可能性",
    },
    "语文": {
        # 一年级上册
        "1.1": "拼音与声调", "1.2": "声母", "1.3": "韵母与声调",
        # 一年级下册
        "1.4": "笔画与笔顺", "1.5": "认识笔画", "1.6": "写好笔顺",
        "1.7": "组词与量词", "1.8": "组词", "1.9": "量词",
        "1.10": "反义词与简单句子", "1.11": "反义词", "1.12": "简单句子",
        # 二年级上册
        "2.1": "多音字与词语积累", "2.2": "多音字", "2.3": "词语积累",
        "2.4": "近义词与词语搭配", "2.5": "近义词", "2.6": "词语搭配",
        "2.7": "句子排序与标点符号", "2.8": "句子排序", "2.9": "标点符号",
        "2.10": "句子补充与看图写话", "2.11": "句子补充", "2.12": "看图写话",
        # 三年级上册
        "3.1": "成语积累", "3.2": "成语的理解", "3.3": "成语的运用",
        "3.4": "修辞手法初步", "3.5": "比喻句", "3.6": "拟人句",
        "3.7": "关联词与复句", "3.8": "关联词", "3.9": "复句",
        "3.10": "段落大意概括", "3.11": "找中心句", "3.12": "概括段意",
        # 四年级上册
        "4.1": "古诗名句", "4.2": "古诗名句填空", "4.3": "理解诗句意思",
        "4.4": "病句修改", "4.5": "修改搭配不当的病句", "4.6": "修改成分残缺的病句",
        "4.7": "记叙文阅读理解", "4.8": "记叙文的人物与事件", "4.9": "体会人物的心情",
        "4.10": "概括主要内容", "4.11": "抓关键语句", "4.12": "把握文章主要内容",
        # 五年级上册
        "5.1": "说明文阅读", "5.2": "说明方法", "5.3": "提取信息",
        "5.4": "文言文字词初步", "5.5": "文言实词", "5.6": "文言虚词",
        "5.7": "文章结构与详略", "5.8": "文章结构", "5.9": "详写与略写",
        "5.10": "古诗词鉴赏", "5.11": "诗句赏析", "5.12": "思想感情",
        # 六年级上册
        "6.1": "综合阅读与主旨", "6.2": "概括主旨", "6.3": "体会表达方法",
        "6.4": "写作手法鉴赏", "6.5": "描写方法", "6.6": "修辞与表达效果",
        "6.7": "文言文阅读", "6.8": "文言文断句与翻译", "6.9": "文言文内容理解",
        "6.10": "综合性学习与语言表达", "6.11": "口语交际", "6.12": "综合性学习",
    },
    "英语": {
        # 一年级上册
        "1.1": "26个字母", "1.2": "字母 A~M", "1.3": "字母 N~Z",
        # 一年级下册
        "1.4": "问候语与自我介绍", "1.5": "问候语", "1.6": "自我介绍",
        "1.7": "数字1-10", "1.8": "数字 1-5", "1.9": "数字 6-10",
        "1.10": "颜色", "1.11": "基本颜色词", "1.12": "颜色与物品",
        # 二年级上册
        "2.1": "常见动物单词", "2.2": "农场动物", "2.3": "野生动物",
        "2.4": "家庭成员", "2.5": "家庭称呼", "2.6": "介绍家人",
        "2.7": "学习用品与教室", "2.8": "学习用品", "2.9": "教室与方位",
        "2.10": "简单祈使句", "2.11": "课堂指令", "2.12": "日常祈使句",
        # 三年级上册
        "3.1": "食物与饮料", "3.2": "食物", "3.3": "饮料",
        "3.4": "一般现在时（第三人称单数）", "3.5": "动词的第三人称单数形式", "3.6": "含 does 的疑问句",
        "3.7": "时间表达与日常作息", "3.8": "整点时间", "3.9": "日常作息",
        "3.10": "方位介词", "3.11": "in / on / under", "3.12": "方位问答",
        # 四年级上册
        "4.1": "现在进行时", "4.2": "be 动词 + 现在分词", "4.3": "现在分词的构成",
        "4.4": "天气与季节", "4.5": "天气", "4.6": "季节",
        "4.7": "一般过去时（规则动词）", "4.8": "动词过去式的 -ed 形式", "4.9": "过去时间状语（yesterday 等）",
        "4.10": "情态动词 can / must", "4.11": "can 的用法", "4.12": "must 的用法",
        # 五年级上册
        "5.1": "一般将来时", "5.2": "will 的用法", "5.3": "be going to 的用法",
        "5.4": "形容词比较级", "5.5": "比较级 -er 形式", "5.6": "比较级 more 形式",
        "5.7": "频度副词与一般现在时", "5.8": "频度副词", "5.9": "一般现在时的用法",
        "5.10": "名词单复数与不可数名词", "5.11": "名词复数的规则变化", "5.12": "名词复数的不规则变化",
        # 六年级上册
        "6.1": "现在完成时初步", "6.2": "have / has + 过去分词", "6.3": "现在完成时的用法",
        "6.4": "一般过去时（不规则动词）", "6.5": "不规则动词的过去式", "6.6": "过去时综合",
        "6.7": "宾语从句与间接引语", "6.8": "宾语从句", "6.9": "间接引语",
        "6.10": "阅读理解与完形填空", "6.11": "阅读理解", "6.12": "完形填空",
    },
}

SUBJECTS = tuple(KNOWLEDGE.keys())
DEFAULT_SUBJECT = "数学"
START_KEY = "1.1"          # 所有诊断都从上册第一块开始，不看学生当前年级
BLOCKS_PER_TOPIC = 3       # 每个年级 12 块 = 4 个大知识点 × 3 块（第 1/4/7/10 块是大知识点本身）


def parent_key(key):
    """这个阶段所属「大知识点」的阶段键（1.2 → 1.1、3.11 → 3.10）。

    细分阶段还没有自己的题库时，用大知识点的题库兜底（见 diagnostic_bank）。
    """
    normalized = normalize_key(key)
    if not normalized:
        return ""
    index = index_of(normalized)
    level_index = index % LEVELS_PER_GRADE
    return key_of(index - level_index % BLOCKS_PER_TOPIC)


def legacy_key(key):
    """旧题库的键（旧 4 等级/年级 ↔ 新 12 块/年级的第 1/4/7/10 块）。

    新 1.1/1.2/1.3 → 旧 1.1，1.4/1.5/1.6 → 旧 1.2，…… 旧题库还用这个键，
    细分阶段取不到自己的题时用它兜底（见 diagnostic_bank）。
    """
    normalized = normalize_key(key)
    if not normalized:
        return ""
    grade, level = (int(part) for part in normalized.split("."))
    return f"{grade}.{(level - 1) // BLOCKS_PER_TOPIC + 1}"


def all_keys():
    """按从低到高返回全部 72 个阶段，例如 ["1.1", ..., "6.12"]。"""
    return [key_of(index) for index in range(MAX_INDEX + 1)]


def normalize_key(value):
    """把各种写法统一成 "3.2"：支持 "3.2" / "3-2" / 3.2 / "三年级熟练"。

    无法识别时返回 ""（调用方据此判断非法输入）。
    """
    if value is None:
        return ""

    if isinstance(value, bool):
        return ""

    if isinstance(value, (int, float)):
        grade = int(value)
        level = int(round((float(value) - grade) * 10))
        return key_of_index(grade - 1, level - 1)

    text = str(value).strip()
    if not text:
        return ""

    # 中文写法必须带「年级」二字：「三年级上册二」；否则「上册二」里的「二」
    # 会被误当成年级（GRADE_NAMES 里也有「二」）。
    for name_index, name in enumerate(GRADE_NAMES):
        if f"{name}年级" in text:
            for level, level_name in enumerate(LEVELS, start=1):
                if level_name in text:
                    return key_of_index(name_index, level - 1)
            return ""

    text = text.replace(" ", "").replace("阶段", "").replace("年级", ".")
    for sep in ("-", "_", "/", "，"):
        text = text.replace(sep, ".")

    parts = [part for part in text.split(".") if part != ""]
    if len(parts) != 2:
        return ""

    try:
        grade, level = int(parts[0]), int(parts[1])
    except ValueError:
        return ""

    return key_of_index(grade - 1, level - 1)


def key_of_index(grade_index, level_index):
    """年级下标 0~5 + 等级下标 0~3 → "3.2"；越界返回 ""。"""
    if not (0 <= grade_index < GRADE_COUNT and 0 <= level_index < LEVELS_PER_GRADE):
        return ""
    return f"{grade_index + 1}.{level_index + 1}"


def key_of(index):
    """线性坐标 → 阶段字符串；越界时夹到两端，保证永远返回合法阶段。"""
    index = max(0, min(MAX_INDEX, int(index)))
    return key_of_index(index // LEVELS_PER_GRADE, index % LEVELS_PER_GRADE)


def index_of(key):
    """阶段字符串 → 线性坐标；无法识别时抛 ValueError，避免静默算错。"""
    normalized = normalize_key(key)
    if not normalized:
        raise ValueError(f"无法识别的能力阶段: {key!r}")

    grade, level = normalized.split(".")
    return (int(grade) - 1) * LEVELS_PER_GRADE + (int(level) - 1)


def grade_of(key):
    return int(normalize_key(key).split(".")[0])


def level_of(key):
    return int(normalize_key(key).split(".")[1])


def level_name(key):
    return LEVELS[level_of(key) - 1]


def label(key):
    """给小朋友看的阶段名，例如 3.2 → "三年级熟练"。"""
    return f"{GRADE_NAMES[grade_of(key) - 1]}年级{level_name(key)}"


def full_label(key):
    """3.2 → "三年级熟练（3.2）"。"""
    return f"{label(key)}（{key}）"


def grade_text(key):
    """3.2 → "三年级"，用于出题 prompt 里描述题目所属年级。"""
    return f"{GRADE_NAMES[grade_of(key) - 1]}年级"


def difficulty_of(key):
    """阶段 → 出题难度 0~100（单调递增）。"""
    span = MAX_DIFFICULTY - MIN_DIFFICULTY
    return int(round(MIN_DIFFICULTY + span * index_of(key) / MAX_INDEX))


def knowledge_of(subject, key):
    """该科目在该阶段主要考察的知识点。"""
    table = KNOWLEDGE.get(subject) or {}
    return table.get(normalize_key(key), "综合练习")


def next_key(key):
    """高一个阶段；已是 6.4 时返回自己。"""
    index = index_of(key)
    return key_of(index + 1) if index < MAX_INDEX else key_of(MAX_INDEX)


def key_of_difficulty(difficulty):
    """难度 0~100 → 最接近的能力阶段（把日常练习的题目映射回能力阶段）。"""
    try:
        value = float(difficulty)
    except (TypeError, ValueError):
        value = MIN_DIFFICULTY

    span = MAX_DIFFICULTY - MIN_DIFFICULTY
    ratio = (value - MIN_DIFFICULTY) / span
    return key_of(round(max(0.0, min(1.0, ratio)) * MAX_INDEX))


def prev_key(key):
    """低一个阶段；已是 1.1 时返回自己。"""
    index = index_of(key)
    return key_of(index - 1) if index > 0 else key_of(0)


def is_valid(key):
    return bool(normalize_key(key))


def stage_range(final_key):
    """能力区间：能力落在 [final, 下一阶段] 之间，例如 3.1 → ("3.1", "3.2")。

    这是诊断报告里"数学能力：3.1～3.2 阶段"的来源：final 是最后一个确认
    达到的阶段，再往上一级还没通过，所以真实水平落在这两级之间。
    """
    final_key = normalize_key(final_key) or START_KEY
    return final_key, next_key(final_key)


def advance(key, rate):
    """按一组题的正确率决定下一个要测的阶段（诊断推进规则）。

    | 正确率      | 含义             | 下一步                        |
    | >= 90%      | 掌握优秀         | 跳过一个大知识点的剩余两块（+3） |
    | 85% ~ 90%   | 掌握良好         | 进入下一块（+1）              |
    | 60% ~ 85%   | 到了能力边界     | 向上再探一块（+1），确认上沿  |
    | < 60%       | 没达到这一级     | 由调用方结束测试并回退        |
    """
    index = index_of(key)
    rate = float(rate or 0)

    nxt = index + (BLOCKS_PER_TOPIC if rate >= 0.90 else 1)
    return key_of(min(nxt, MAX_INDEX))


def stars(score):
    """能力分 → 1~5 颗星（报告页用）。"""
    try:
        score = float(score)
    except (TypeError, ValueError):
        return 0

    score = max(0.0, min(100.0, score))
    if score <= 0:
        return 0
    return max(1, min(5, int(score // 20) + 1))


def star_text(score):
    """76 → "★★★★☆"。"""
    count = stars(score)
    return "★" * count + "☆" * (5 - count)
