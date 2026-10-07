# ==============================================================
# 能力契约｜284 节点知识点树（硬编码 DOMAINS/SUBPOINTS）+ 启动灌库 + 与掌握度关联
# 入口：seed / ensure_seeded / link_mastery / node_rows / domains_for / path_of / subpoints_of
# 依赖：stages
# 不负责：阶段与知识点定义 → stages.py
# 验证：python backend/verify_knowledge.py
# 被调用：main.py（import 期）、knowledge_routes.py、adaptive/strategy.py、adaptive/engine.py、review/engine.py、review/selector.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 知识点体系：科目 → 章节领域 → 知识点 → 子知识点的树结构。

设计要点：
1. `stages.KNOWLEDGE` 仍然是"每个能力阶段练哪个知识点"的唯一来源，
   本模块的领域划分必须与它逐字对齐（seed 时会校验，缺一个就报错）。
2. 知识点按 `parent_id` 自关联成树，深度最多 4 层：
      数学 → 计算 → 表内乘法 → 2~5的乘法口诀
3. 年级/学期/难度从知识点所属的能力阶段推导，不手写，避免和阶段模型打架。
"""

import stages

# 章节领域 → 该领域下的知识点名称（名称必须与 stages.KNOWLEDGE 完全一致）
DOMAINS = {
    "数学": {
        "计算": [
            "20以内加减法", "100以内加减法", "连加连减与加减混合", "表内乘法", "表内除法",
            "多位数乘一位数", "两位数除法", "大数认识与四则运算", "运算定律与简便计算",
            "小数乘除法", "因数与倍数", "分数乘除法",
            "10以内加减法", "20以内进位加法", "100以内进位与退位加减法", "连加连减",
            "加减混合运算", "认识几分之几", "同分母分数加减法", "乘法的初步认识",
            "2~6的乘法口诀", "除法的初步认识", "用乘法口诀求商", "口算乘法", "笔算乘法",
            "口算除法", "笔算除法与验算", "四则运算的顺序", "加法运算定律", "乘法运算定律",
            "小数乘法", "小数除法", "因数和倍数", "质数与合数", "分数乘法", "分数除法",
            "百分数的意义和计算",
        ],
        "数与代数": [
            "分数初步认识", "小数的意义与加减法", "简易方程", "比与比例", "百分数与统计",
            "100以内数的认识", "亿以内数的认识", "小数的意义和性质", "小数的加法和减法",
            "用字母表示数量关系", "等式的性质与解方程", "比的意义和基本性质", "比例和比例尺",
        ],
        "图形与几何": [
            "认识图形与简单应用", "长度单位与测量", "长方形与正方形的周长",
            "平行四边形与梯形面积", "多边形面积与组合图形", "圆的周长与面积",
            "认识平面图形", "认识立体图形", "认识厘米和米", "线段与角的初步认识",
            "四边形的认识", "长方形和正方形的周长", "平行与垂直", "平行四边形和梯形的面积",
            "三角形的面积", "组合图形的面积", "圆的认识", "圆的周长和面积",
        ],
        "应用题": [
            "两步计算应用题", "先乘后加减的两步计算", "先除后加减的两步计算",
        ],
        "统计与概率": ["统计与可能性"],
    },
    "语文": {
        "拼音与识字": [
            "拼音拼读", "笔画与笔顺", "多音字与词语积累",
            "声母", "韵母与声调", "认识笔画", "写好笔顺",
        ],
        "词语积累": [
            "组词与量词", "反义词与简单句子", "近义词与词语搭配", "成语积累",
            "组词", "量词", "反义词", "多音字", "词语积累", "近义词", "词语搭配",
            "成语的理解", "成语的运用",
        ],
        "句子与标点": [
            "句子排序与标点符号", "句子补充与看图写话", "关联词与复句",
            "修辞手法初步", "病句修改",
            "简单句子", "句子排序", "标点符号", "句子补充", "比喻句", "拟人句",
            "关联词", "复句", "修改搭配不当的病句", "修改成分残缺的病句",
        ],
        "阅读理解": [
            "段落大意概括", "记叙文阅读理解", "概括主要内容", "说明文阅读",
            "把握文章主要内容",
            "文章结构与详略", "综合阅读与主旨", "写作手法鉴赏",
            "找中心句", "概括段意", "记叙文的人物与事件", "体会人物的心情",
            "抓关键语句", "说明方法", "提取信息", "文章结构", "详写与略写",
            "概括主旨", "体会表达方法", "描写方法", "修辞与表达效果",
            "文言文断句与翻译", "文言文内容理解",
        ],
        "古诗文": [
            "古诗名句", "文言文字词初步", "古诗词鉴赏", "文言文阅读",
            "古诗名句填空", "理解诗句意思", "文言实词", "文言虚词", "诗句赏析", "思想感情",
        ],
        "表达与综合": [
            "综合性学习与语言表达", "看图写话", "口语交际", "综合性学习",
        ],
    },
    "英语": {
        "字母与语音": ["26个字母", "字母 A~M", "字母 N~Z"],
        "词汇": [
            "数字1-10", "颜色", "常见动物单词", "家庭成员", "学习用品与教室",
            "食物与饮料", "天气与季节",
            "问候语", "自我介绍", "数字 1-5", "数字 6-10", "基本颜色词", "颜色与物品",
            "农场动物", "野生动物", "家庭称呼", "介绍家人", "学习用品", "教室与方位",
            "食物", "饮料", "整点时间", "日常作息", "天气", "季节",
        ],
        "句型与交际": [
            "问候语与自我介绍", "简单祈使句", "时间表达与日常作息", "方位介词",
            "课堂指令", "日常祈使句", "in / on / under", "方位问答",
            "can 的用法", "must 的用法",
        ],
        "语法": [
            "一般现在时（第三人称单数）", "现在进行时", "一般过去时（规则动词）",
            "情态动词 can / must", "一般将来时", "形容词比较级", "频度副词与一般现在时",
            "名词单复数与不可数名词", "现在完成时初步", "一般过去时（不规则动词）",
            "宾语从句与间接引语",
            "动词的第三人称单数形式", "含 does 的疑问句", "be 动词 + 现在分词",
            "现在分词的构成", "动词过去式的 -ed 形式", "过去时间状语（yesterday 等）",
            "will 的用法", "be going to 的用法", "比较级 -er 形式", "比较级 more 形式",
            "频度副词", "一般现在时的用法", "名词复数的规则变化", "名词复数的不规则变化",
            "have / has + 过去分词", "现在完成时的用法", "不规则动词的过去式", "过去时综合",
            "宾语从句", "间接引语",
        ],
        "阅读": ["阅读理解与完形填空", "阅读理解", "完形填空"],
    },
}

# 第四层：知识点 → 子知识点（更细的能力追踪，答题挂在子知识点上时会向上聚合）
SUBPOINTS = {
    "数学": {
        "表内乘法": ["2~5的乘法口诀", "6~9的乘法口诀"],
        "多位数乘一位数": ["两位数乘一位数", "三位数乘一位数"],
        "两位数除法": ["除数是整十数的除法", "试商与调商"],
        "长方形与正方形的周长": ["长方形周长", "正方形周长"],
        "运算定律与简便计算": ["乘法交换律与结合律", "乘法分配律"],
        "分数初步认识": ["认识几分之一", "同分母分数加减"],
        "小数乘除法": ["小数乘整数", "小数除以整数"],
        "简易方程": ["用字母表示数", "解简易方程"],
        "圆的周长与面积": ["圆的周长", "圆的面积"],
        "两步计算应用题": ["先乘后加", "先减后除"],
    },
    "语文": {
        "拼音拼读": ["声母与韵母", "四声辨别"],
        "笔画与笔顺": ["基本笔画", "笔顺规则"],
        "成语积累": ["成语意思", "成语填空"],
        "修辞手法初步": ["比喻", "拟人"],
        "病句修改": ["搭配不当", "成分残缺"],
        "古诗名句": ["诗句填空", "诗句意思"],
        "记叙文阅读理解": ["找出人物和事件", "体会人物心情"],
        "文言文字词初步": ["常见实词", "常见虚词"],
    },
    "英语": {
        "26个字母": ["大写字母", "小写字母"],
        "一般现在时（第三人称单数）": ["动词加 s", "does 的用法"],
        "现在进行时": ["be + doing", "现在分词的变化"],
        "一般过去时（规则动词）": ["动词加 ed", "过去时间状语"],
        "形容词比较级": ["er 形式", "more 形式"],
        "名词单复数与不可数名词": ["规则复数", "不规则复数"],
        "一般过去时（不规则动词）": ["常见不规则动词"],
    },
}


def _stage_of(subject, name):
    """知识点名称 → 它所属的能力阶段（如 "表内乘法" → "2.1"）。"""
    for key, value in (stages.KNOWLEDGE.get(subject) or {}).items():
        if value == name:
            return key
    return ""


def all_names(subject):
    """该科目下的全部知识点名称（不含领域与子知识点）。"""
    names = []
    for group in (DOMAINS.get(subject) or {}).values():
        names.extend(group)
    return names


def domain_of(subject, name):
    """知识点属于哪个章节领域；找不到时返回 "其它"。"""
    for domain, names in (DOMAINS.get(subject) or {}).items():
        if name in names:
            return domain
    return "其它"


def subject_of_knowledge(name):
    """反查这个知识点属于哪一科（跨科目查询时用）。"""
    for subject in DOMAINS:
        if name in all_names(subject):
            return subject
    return ""


def stage_of(subject, name):
    return _stage_of(subject, name)


def stage_of_any(subject, name):
    """知识点的能力阶段：子知识点自己不在阶段表里，就继承父知识点的阶段。"""
    key = _stage_of(subject, name)
    if key:
        return key

    parent = subpoint_parent(subject, name)
    return _stage_of(subject, parent) if parent else ""


def grade_of(subject, name):
    """知识点所在年级；推导不出来时默认一年级。"""
    key = _stage_of(subject, name)
    return stages.grade_of(key) if key else 1


def semester_of(subject, name):
    """知识点所在学期：每年级前 6 块算上册，后 6 块算下册。"""
    key = _stage_of(subject, name)
    if not key:
        return "上册"
    return "上册" if stages.level_of(key) <= stages.LEVELS_PER_GRADE // 2 else "下册"


def difficulty_of(subject, name):
    key = _stage_of(subject, name)
    return stages.difficulty_of(key) if key else 50


def path_of(subject, name):
    """知识点的完整路径，例如 "数学 / 计算 / 表内乘法"。"""
    return f"{subject} / {domain_of(subject, name)} / {name}"


def subpoints_of(subject, name):
    return list((SUBPOINTS.get(subject) or {}).get(name) or [])


def domains_for(subject):
    """[{"domain": 名称, "knowledge": [知识点名称, ...]}, ...]"""
    return [{"domain": domain, "knowledge": list(names)}
            for domain, names in (DOMAINS.get(subject) or {}).items()]


def subpoint_parent(subject, name):
    """子知识点 → 它的父知识点；不是子知识点时返回 ""。"""
    for parent, children in (SUBPOINTS.get(subject) or {}).items():
        if name in children:
            return parent
    return ""


def parent_name(subject, name):
    """知识点的父节点名称：子知识点 → 知识点，知识点 → 领域名。"""
    parent = subpoint_parent(subject, name)
    if parent:
        return parent
    if name in all_names(subject):
        return f"{subject} / {domain_of(subject, name)}"
    return ""


def node_rows(subject):
    """按"先父后子"的顺序，把整棵树展开成可直接入库的行。

    每行：{subject, grade, semester, chapter, knowledge_name, parent_name, difficulty}
    parent_name 为空表示根节点（科目节点）。
    """
    rows = []

    for domain, names in (DOMAINS.get(subject) or {}).items():
        rows.append({
            "subject": subject, "grade": 1, "semester": "全册", "chapter": domain,
            "knowledge_name": f"{subject} / {domain}", "parent_name": subject,
            "difficulty": 0, "is_leaf": False,
        })

        for name in names:
            key = _stage_of(subject, name)
            if not key:
                raise ValueError(f"{subject} 的知识点「{name}」没有对应的能力阶段")

            rows.append({
                "subject": subject,
                "grade": stages.grade_of(key),
                "semester": semester_of(subject, name),
                "chapter": domain,
                "knowledge_name": name,
                "parent_name": f"{subject} / {domain}",
                "difficulty": stages.difficulty_of(key),
                "is_leaf": True,
            })

            for child in subpoints_of(subject, name):
                rows.append({
                    "subject": subject,
                    "grade": stages.grade_of(key),
                    "semester": semester_of(subject, name),
                    "chapter": domain,
                    "knowledge_name": child,
                    "parent_name": name,
                    "difficulty": stages.difficulty_of(key),
                    "is_leaf": True,
                })

    rows.insert(0, {
        "subject": subject, "grade": 1, "semester": "全册", "chapter": subject,
        "knowledge_name": subject, "parent_name": "", "difficulty": 0, "is_leaf": False,
    })

    return rows


def seed(session, force=False):
    """把知识点树写进 knowledge_points 表（幂等，按科目+名称去重）。

    返回 (新增数, 跳过数)。
    """
    from models import KnowledgePoint

    existing = {
        (row.subject, row.knowledge_name): row
        for row in session.query(KnowledgePoint).all()
    }

    created = 0
    skipped = 0

    for subject in stages.SUBJECTS:
        rows = node_rows(subject)
        for row in rows:
            key = (row["subject"], row["knowledge_name"])
            if key in existing:
                skipped += 1
                continue

            node = KnowledgePoint(
                subject=row["subject"],
                grade=row["grade"],
                semester=row["semester"],
                chapter=row["chapter"],
                knowledge_name=row["knowledge_name"],
                difficulty=row["difficulty"],
                is_leaf=row["is_leaf"],
                path=path_of(subject, row["knowledge_name"]) if row["is_leaf"]
                else f"{row['subject']} / {row['chapter']}",
            )
            session.add(node)
            session.flush()
            existing[key] = node

            parent_name = row["parent_name"]
            if parent_name:
                parent = existing.get((row["subject"], parent_name))
                if parent is not None:
                    node.parent_id = parent.id

            created += 1

    session.commit()
    return created, skipped


def ensure_seeded(session):
    """启动时调用：把缺的知识点补进表里（seed 幂等，已有节点跳过）。

    早期只在表为空时灌库；知识树扩到 284 节点后，旧库也必须能补齐
    新增的知识点，所以这里改成每次都跑一遍 seed。
    """
    return seed(session)


def link_mastery(session):
    """把已有的知识点掌握度挂到树上（回填 knowledge_point_id 与 grade）。

    V2.2 的掌握度行只有知识点名称，没有指向知识树的 id；这里补上，
    之后就能按章节/年级聚合了。
    """
    from models import KnowledgePoint, StudentKnowledgeMastery

    points = {
        (row.subject, row.knowledge_name): row
        for row in session.query(KnowledgePoint).all()
    }

    updated = 0
    for row in session.query(StudentKnowledgeMastery).all():
        node = points.get((row.subject, row.knowledge_id))
        if node is None:
            continue

        changed = False
        if row.knowledge_point_id != node.id:
            row.knowledge_point_id = node.id
            changed = True
        if not row.grade or row.grade != node.grade:
            row.grade = node.grade
            changed = True

        if changed:
            updated += 1

    session.commit()
    return updated
