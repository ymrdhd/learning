# ==============================================================
# 能力契约｜题干雷同检测（全项目唯一真相：归一化 / 相似度 / 重复判定）
# 入口：normalize_stem / numbers_of / similarity / is_duplicate / DUPLICATE_THRESHOLD
# 依赖：re（纯标准库，无项目内依赖）
# 不负责：出题 → deepseek.py / diagnostic_bank.py；选题 → adaptive/selector.py、review/selector.py
# 验证：python backend/verify_flow.py --self-serve、python backend/verify_memory.py
# 被调用：deepseek.py（主练习防雷同）、review/selector.py（复习不重复原题）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""题干防雷同判定（V2.5 出题密度治理）。

背景：主练习链路原来每道题都独立调用模型，模型在同一个知识点上容易反复吐
同一道经典题（例如语文古诗「床前明月光」），一次练习里连出好几道几乎一样的题。

本模块只做"两道题算不算同一道"这一件事，被两条链路共用：

- `deepseek.generate_question`：出题前把最近原题写进 prompt，出题后再本地复核；
- `review.selector`：间隔复习出题时避开历史原题。

判定规则（与 review 体系原有语义一致）：

1. 归一化后题干完全相同 → 重复；
2. 题干里的数字序列相同、且文字相似度 ≥ `DUPLICATE_THRESHOLD` → 重复；
   数字一变（36×24 → 42×18）就算新题，这是数学变式的核心；
3. 其余情况算新题。
"""

import re

DUPLICATE_THRESHOLD = 0.9

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
PUNCT_RE = re.compile(r"[\s，。、；：？！,.;:?!（）()【】\[\]「」“”\"'=＝+＋\-－×xX*÷/？?]")


def normalize_stem(text):
    """题干归一化：去空白与标点、统一大小写，用于重复检测。"""
    text = str(text or "").strip().lower()
    return PUNCT_RE.sub("", text)


def numbers_of(text):
    """题干里的数字序列（数学题靠它判断"是否只是换了数字"）。"""
    return tuple(NUMBER_RE.findall(str(text or "")))


def similarity(left, right):
    """字符集合 Jaccard 相似度 0~1。"""
    left_set, right_set = set(left or ""), set(right or "")
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / float(len(left_set | right_set))


def is_duplicate(stem, history, threshold=DUPLICATE_THRESHOLD):
    """跟历史原题比对：完全相同，或"数字一样且文字高度相似" → 算重复。"""
    norm = normalize_stem(stem)
    if not norm:
        return False

    norm_numbers = numbers_of(norm)
    for old in history or ():
        old_norm = normalize_stem(old)
        if not old_norm:
            continue
        if norm == old_norm:
            return True
        if numbers_of(old_norm) != norm_numbers:
            continue          # 数字变了 → 是新题（数学变式的核心）
        if similarity(norm, old_norm) >= threshold:
            return True
    return False
