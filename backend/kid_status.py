# ==============================================================
# 能力契约｜儿童知识状态 UI 适配器：算法层数值 → 🌱🌿🌳⭐ 儿童语言（只做显示映射）
# 入口：LEVELS / LEVEL_BY_KEY / UNKNOWN / CHALLENGE_STATUS / status_of / status_label / rank_of / is_upgrade / upgrade_text / forgetting_text / no_review_text / no_wrong_text / challenge_status
# 依赖：review.memory（MATURITY_LEVELS，只读复用成熟度键名，不重算任何数值）
# 不负责：掌握度计算 → mastery.py；记忆成熟度计算 → review/memory.py；前端同名字典 → frontend/kid-lang.js
# 验证：python backend/verify_v26.py
# 被调用：home_routes.py、growth_routes.py、knowledge_map_routes.py、challenge_routes.py
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================
"""V2.6 儿童知识状态适配器（UI Adapter）。

最高原则 §22：全产品只有四种儿童说法，算法数值不允许出现在儿童端。

    🌱 刚开始    🌿 正在学习（基本会了）    🌳 已经掌握    ⭐ 记得很牢

后端只做"数值 → 结构化儿童状态"的映射，不改动任何底层算法：
掌握度仍由 ``mastery.py`` 计算，记忆成熟度仍由 ``review/memory.py`` 计算，
本模块只把两者的结果翻译成儿童语言，供聚合接口统一输出。

前端同名字典在 ``frontend/kid-lang.js``（阈值 90/75/55/30 必须与本文件保持一致）。
"""

from review.memory import MATURITY_LEVELS

# 按把握程度从高到低；min 为掌握度下限（None = 兜底档）
LEVELS = (
    {"key": "solid", "icon": "⭐", "label": "记得很牢", "rank": 4, "min": 90},
    {"key": "mastered", "icon": "🌳", "label": "已经掌握", "rank": 3, "min": 75},
    {"key": "basic", "icon": "🍀", "label": "基本会了", "rank": 2, "min": 55},
    {"key": "learning", "icon": "🌿", "label": "正在学习", "rank": 1, "min": 30},
    {"key": "sprout", "icon": "🌱", "label": "刚开始", "rank": 0, "min": None},
)

LEVEL_BY_KEY = {item["key"]: item for item in LEVELS}
LEVEL_KEYS = tuple(item["key"] for item in LEVELS)

# 从未练习过（mastery 为 None / 空 / NaN）
UNKNOWN = {"key": "sprout", "icon": "🌱", "label": "还没开始学", "rank": 0}

# 记忆成熟度 → 儿童状态下限（只会把档位抬高，不会压低掌握度得出的档位）
MATURITY_FLOOR = {
    "NEW": "sprout",
    "LEARNING": "sprout",
    "SHORT_TERM": "learning",
    "CONSOLIDATING": "basic",
    "STABLE": "mastered",
    "LONG_TERM": "solid",
}

# 挑战中心三色（真实状态仍来自 recovery/state.py 的六态，这里只做视觉映射）
CHALLENGE_STATUS = {
    "red": {"key": "red", "icon": "🔴", "label": "等我攻克"},
    "yellow": {"key": "yellow", "icon": "🟡", "label": "正在训练"},
    "green": {"key": "green", "icon": "🟢", "label": "已经攻克"},
}

# recovery/state.py 六态 → 三色
RECOVERY_TONE = {
    "NEW": "red",
    "ANALYZING": "red",
    "LEARNING": "yellow",
    "PRACTICING": "yellow",
    "VERIFYING": "yellow",
    "MASTERED": "green",
}


def _number(value):
    """容错取数：None / "" / NaN / 非数字 → None（表示"还没开始学"）。"""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:                       # NaN
        return None
    return number


def _level_of_key(key):
    return LEVEL_BY_KEY.get(key) or LEVELS[-1]


def status_of(mastery_score, maturity=""):
    """掌握度（0~100）+ 记忆成熟度 → 儿童状态 ``{key, icon, label, rank}``。

    没练过 → 🌱 还没开始学；成熟度只作为下限抬高档位（长期掌握直接 ⭐）。
    """
    score = _number(mastery_score)
    if score is None:
        return dict(UNKNOWN)
    level = LEVELS[-1]
    for item in LEVELS:
        if item["min"] is not None and score >= item["min"]:
            level = item
            break
    floor_key = MATURITY_FLOOR.get(str(maturity or "").strip().upper(), "")
    if floor_key and _level_of_key(floor_key)["rank"] > level["rank"]:
        level = _level_of_key(floor_key)
    return {"key": level["key"], "icon": level["icon"], "label": level["label"],
            "rank": level["rank"]}


def status_label(mastery_score, maturity=""):
    """只要一句儿童话：🌱 刚开始 / 🌿 正在学习 / 🌳 已经掌握 / ⭐ 记得很牢。"""
    return status_of(mastery_score, maturity)["label"]


def rank_of(mastery_score, maturity=""):
    """档位序号 0~4，用于判断"是不是真的变强了"。"""
    return status_of(mastery_score, maturity)["rank"]


def _key_of(value):
    if isinstance(value, dict):
        return str(value.get("key") or "")
    return str(value or "")


def is_upgrade(previous, current):
    """两次状态（字典或 key）相比是否真的升档。没有旧状态 → False（不算成长）。"""
    before, after = _key_of(previous), _key_of(current)
    if not before or not after or before not in LEVEL_BY_KEY or after not in LEVEL_BY_KEY:
        return False
    return LEVEL_BY_KEY[after]["rank"] > LEVEL_BY_KEY[before]["rank"]


def upgrade_text(previous, current, name=""):
    """成长文案：``🌿 → 🌳　「两位数乘法」这个知识记得更牢啦！``"""
    before, after = _key_of(previous), _key_of(current)
    left = _level_of_key(before) if before in LEVEL_BY_KEY else LEVELS[-1]
    right = _level_of_key(after) if after in LEVEL_BY_KEY else LEVELS[-1]
    head = "{0} → {1}".format(left["icon"], right["icon"])
    if name:
        return "{0}　「{1}」这个知识记得更牢啦！".format(head, name)
    return "{0}　这个知识记得更牢啦！".format(head)


def forgetting_text(count):
    """需要照顾的知识点数（间隔复习 + 主动回忆的儿童说法）。"""
    return "🌱 今天有 {0} 个知识需要照顾。".format(max(0, int(count or 0)))


def no_review_text():
    return "🌳 今天没有知识需要复习。"


def no_wrong_text():
    return "🎉 暂时没有需要攻克的错题！"


def challenge_status(state):
    """康复六态 → 挑战中心三色状态 ``{key, icon, label}``。未知状态当作"等我攻克"。"""
    tone = RECOVERY_TONE.get(str(state or "").strip().upper(), "red")
    return dict(CHALLENGE_STATUS[tone])


def maturity_keys():
    """成熟度合法键名（供门禁套件校验 MATURITY_FLOOR 无遗漏）。"""
    return tuple(MATURITY_LEVELS)
