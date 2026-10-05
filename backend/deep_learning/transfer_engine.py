# ==============================================================
# 能力契约｜V2.7 知识迁移系统：迁移等级 T0~T5、变式出题（AI 优先生成本地题库降级）与迁移判定（纯函数）
# 入口：TRANSFER_LEVELS / LEVEL_BY_VALUE / MAX_LEVEL / LOCAL_MAX_LEVEL / TRANSFER_EVIDENCE /
#       CONTEXT_SWAPS / PHRASE_SWAPS / TransferEngine / DEFAULT_ENGINE / levels / level_dict /
#       clamp_level / suggest_level / local_variant / ai_variant / make_question / judge / gap_action
# 依赖：stages、knowledge_tree、diagnostic_bank（本地变式题库）、validator（AI 题必过审）、deepseek（延迟导入）
# 不负责：升降级阶梯状态机 → variant_ladder.py；落库 → deep_learning/engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/variant_ladder.py、deep_learning/engine.py、deep_learning/routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 知识迁移系统（需求 §十三 ~ §十六、§三十四、§三十五、§三十七）。

目标：判断学生是不是**只记住了原题模板**。迁移时保持核心知识目标不变，
逐渐改变：数字 → 表述 → 信息顺序 → 生活情境 → 问题形式 → 题目结构。

迁移等级（需求 §十四）：

| 等级 | 名称 | 变了什么 |
| --- | --- | --- |
| T0 | 原题/近原题 | 不变 |
| T1 | 数字变化 | 只换数字 |
| T2 | 语言表达变化 | 换一种说法 |
| T3 | 情境变化 | 换生活场景 |
| T4 | 结构变化 | 信息顺序 / 问题形式变了 |
| T5 | 综合迁移 | 数字 + 情境 + 结构一起变 |

**绝不能刚学完基础知识就直接大量 T5**（需求 §十四）—— 起始等级由 :func:`suggest_level` 决定，
并且本地题库只覆盖到 T3，T4/T5 交给 AI；AI 不可用时降级到本地 T3 并如实记录**实际达到的等级**
（需求 §三十七：DeepSeek 异常不能阻塞学习）。
"""

import random

TRANSFER_EVIDENCE = "TRANSFER"

TRANSFER_LEVELS = (
    {"level": 0, "key": "T0", "name": "原题/近原题", "change": "和刚才那道一模一样",
     "child": "再做一遍刚才那道题"},
    {"level": 1, "key": "T1", "name": "数字变化", "change": "只换数字，方法一样",
     "child": "换个数字，方法还是一样的"},
    {"level": 2, "key": "T2", "name": "语言表达变化", "change": "换一种说法说同一件事",
     "child": "换个说法，意思没变"},
    {"level": 3, "key": "T3", "name": "情境变化", "change": "换一个生活场景",
     "child": "换到生活里的另一个场景"},
    {"level": 4, "key": "T4", "name": "结构变化", "change": "信息顺序或问题形式变了",
     "child": "条件换了个顺序，要自己找一找"},
    {"level": 5, "key": "T5", "name": "综合迁移", "change": "数字、情境、结构一起变",
     "child": "全都换新了，看看还能不能做"},
)

LEVEL_BY_VALUE = {item["level"]: dict(item) for item in TRANSFER_LEVELS}
MAX_LEVEL = 5
LOCAL_MAX_LEVEL = 3          # 本地题库只能造出这些等级，再高必须靠 AI
DEFAULT_LEVEL = 1

# 情境替换（T3 用）：只在题干文本上做安全替换，不改变数量关系
CONTEXT_SWAPS = {
    "苹果": "铅笔", "铅笔": "苹果", "橘子": "橡皮", "小朋友": "同学", "同学": "小朋友",
    "教室": "操场", "操场": "图书馆", "图书": "画册", "商店": "文具店", "货架": "书架上",
    "小明": "小红", "小红": "小明", "小华": "小刚", "小刚": "小华", "老师": "班长",
    "水果": "文具", "糖": "贴纸", "气球": "风车", "花": "草", "树": "竹子",
    "小明家": "小红家", "学校": "公园", "班": "小组", "动物园": "植物园",
}

# 表达替换（T2 用）：同义词/同义短语，语义等价
PHRASE_SWAPS = {
    "一共": "总共", "总共": "一共", "还剩": "还剩下", "还剩下": "还剩",
    "请问": "", "多少": "几", "几": "多少", "算一算": "计算一下", "计算": "算",
    "下面的": "下列", "下列": "下面的", "正确的是": "对的选项是",
    "填一填": "把答案写出来", "选择": "选出", "求": "算一算",
}

GRADE_RANGE = (1, 6)
STRUCTURE_NOTE = "条件和问题的顺序被打乱了 —— 先自己找出已知和所求（T4/T5 需要 AI 出题）。"


def clamp_level(level):
    try:
        value = int(level)
    except (TypeError, ValueError):
        value = DEFAULT_LEVEL
    return max(0, min(MAX_LEVEL, value))


def level_dict(level):
    return dict(LEVEL_BY_VALUE.get(clamp_level(level), LEVEL_BY_VALUE[DEFAULT_LEVEL]))


def levels():
    return [dict(item) for item in TRANSFER_LEVELS]


def _text(value):
    return str(value or "").strip()


class TransferEngine:
    """迁移引擎（纯函数，不碰数据库）。"""

    # ---------- 起始等级 ----------

    def suggest_level(self, mastery_score=0, deep_level=0, variant_failures=0):
        """根据当前掌握情况决定迁移从哪里开始（绝不一上来就 T5）。"""
        try:
            mastery = float(mastery_score or 0)
        except (TypeError, ValueError):
            mastery = 0.0
        try:
            deep = int(deep_level or 0)
        except (TypeError, ValueError):
            deep = 0
        try:
            failures = int(variant_failures or 0)
        except (TypeError, ValueError):
            failures = 0

        if mastery < 40:
            level = 0
        elif mastery < 60:
            level = 1
        elif deep >= 4:
            level = 3
        else:
            level = 2

        if failures >= 2:
            level = max(0, level - 1)

        info = level_dict(level)
        return {"level": level, "key": info["key"], "name": info["name"],
                "reason": "当前掌握度 %.0f，先从「%s」开始。" % (mastery, info["name"])}

    # ---------- 本地变式 ----------

    def _stage_of(self, subject, knowledge):
        try:
            from knowledge_tree import stage_of_any, stage_of
        except Exception:
            return ""
        for probe in (lambda: stage_of_any(subject, knowledge), lambda: stage_of(subject, knowledge)):
            try:
                key = probe()
            except Exception:
                key = ""
            if key:
                return key
        return ""

    def _bank_question(self, subject, knowledge, stage="", avoid=()):
        try:
            import diagnostic_bank
        except Exception:
            return None
        key = stage or self._stage_of(subject, knowledge)
        if not key:
            return None
        try:
            return diagnostic_bank.build_question(subject, key, avoid=avoid)
        except Exception:
            return None

    def _rewrite(self, text, level):
        """按等级改写题干文本（T2 表达替换 / T3 情境替换）；语义保持不变。"""
        out = _text(text)
        if not out or level <= 1:
            return out
        pairs = []
        if level >= 2:
            pairs.extend(PHRASE_SWAPS.items())
        if level >= 3:
            pairs.extend(CONTEXT_SWAPS.items())
        rng = random.Random(hash((out, level)) & 0xFFFF)
        rng.shuffle(pairs)
        for old, new in pairs:
            if old and old in out:
                out = out.replace(old, new, 1)
        return out

    def local_variant(self, subject, knowledge, level=DEFAULT_LEVEL, base=None,
                      avoid=(), stage=""):
        """本地变式：能用已有题库就不用 AI（需求 §三十七）。

        返回题目 dict（含 ``level`` / ``requested_level`` / ``source`` / ``capped``），
        本地造不出来时返回 ``None``。
        """
        requested = clamp_level(level)
        base = base if isinstance(base, dict) else None

        if requested == 0 and base and _text(base.get("question")):
            item = dict(base)
            item.update({"level": 0, "requested_level": 0, "capped": False,
                         "source": "original", "variant_change": level_dict(0)["change"]})
            return item

        used = min(requested, LOCAL_MAX_LEVEL)
        question = self._bank_question(subject, knowledge, stage=stage, avoid=avoid)
        if question is None and base and _text(base.get("question")):
            question = dict(base)
            question["source"] = "original"
        if question is None:
            return None

        item = dict(question)
        item["question"] = self._rewrite(item.get("question"), used)
        item["level"] = used
        item["requested_level"] = requested
        item["capped"] = requested > used
        item["variant_change"] = level_dict(used)["change"]
        if item["capped"]:
            item["note"] = "本地题库最高只能到 T3，这一题按 T3 出（AI 不可用时的降级）。"
        return item

    # ---------- AI 变式 ----------

    def ai_variant(self, subject, knowledge, level, grade=3, ability=None,
                   deep_mastery=None, base_question="", difficulty=None, avoid=()):
        """请求 AI 出迁移题；必须过 QuestionValidator（需求 §三十五）。离线返回 None。"""
        if str(level) and clamp_level(level) == 0:
            return None

        try:
            import deepseek
            import validator
        except Exception:
            return None

        if not getattr(deepseek, "KEY", ""):
            return None

        target = clamp_level(level)
        try:
            data = deepseek.generate_transfer_question(
                subject, grade, knowledge, difficulty, target,
                ability=ability, deep_mastery=deep_mastery,
                base_question=base_question, avoid=avoid)
        except Exception:
            return None

        if not isinstance(data, dict) or not _text(data.get("question")):
            return None

        report = None
        try:
            report = validator.validate(data, subject=subject, grade=grade,
                                        knowledge=knowledge, difficulty=difficulty,
                                        stage=self._stage_of(subject, knowledge))
        except Exception:
            report = None

        if not isinstance(report, dict) or not report.get("passed"):
            return None

        info = level_dict(target)
        out = dict(data)
        out["level"] = target
        out["requested_level"] = target
        out["capped"] = False
        out["variant_change"] = info["change"]
        out["source"] = "ai"
        out["weakest"] = (report or {}).get("score")
        return out

    # ---------- 主入口 ----------

    def make_question(self, subject, knowledge, level=DEFAULT_LEVEL, grade=3,
                      ability=None, deep_mastery=None, base=None, avoid=(),
                      difficulty=None, use_ai=True):
        """AI 优先 → 本地题库 → 原题兜底；**任何情况都不会抛异常、不会卡住学习**。"""
        requested = clamp_level(level)
        base = base if isinstance(base, dict) else None
        base_text = _text((base or {}).get("question"))
        stage = self._stage_of(subject, knowledge)

        if use_ai and requested >= 1:
            item = self.ai_variant(subject, knowledge, requested, grade=grade, ability=ability,
                                   deep_mastery=deep_mastery, base_question=base_text,
                                   difficulty=difficulty, avoid=avoid)
            if item is not None:
                item["fallback"] = False
                return item

        item = self.local_variant(subject, knowledge, requested, base=base, avoid=avoid,
                                  stage=stage)
        if item is not None:
            item["fallback"] = bool(requested >= 1 and item.get("source") != "ai")
            return item

        if base is not None:
            item = dict(base)
            item.update({"level": 0, "requested_level": requested, "capped": requested > 0,
                         "variant_change": level_dict(0)["change"], "source": "original",
                         "fallback": True,
                         "note": "本地没有可用的变式题，先用原题。"})
            return item
        return None

    # ---------- 判定 ----------

    def judge(self, level, correct, hint_used=0, response_time=0, confidence=""):
        """一次迁移作答 → 证据强度与判定（需求 §十六：迁移失败不等于基础不会）。"""
        used = clamp_level(level)
        try:
            hints = int(hint_used or 0)
        except (TypeError, ValueError):
            hints = 0
        sure = str(confidence or "").strip().lower()

        if correct:
            if hints == 0 and sure != "guess":
                strength = "strong"
                message = "换了个样子你还是会做 —— 说明是真的懂了。"
            else:
                strength = "weak"
                message = "这题做对了，不过用了提示，我们再试试别的样子。"
        else:
            strength = "none"
            message = "这道题换了个样子没做出来 —— 原来的方法你其实会，我们换个角度再看看。"

        return {
            "level": used,
            "level_key": level_dict(used)["key"],
            "level_name": level_dict(used)["name"],
            "correct": bool(correct),
            "hint_used": hints,
            "evidence_type": TRANSFER_EVIDENCE,
            "strength": strength,
            "transfer_gap": (not correct) and used >= 2,
            "base_mastery_penalty": 0 if correct else (0.0 if used >= 2 else 1.0),
            "message": message,
        }

    def gap_action(self, level, correct, mastery_score=0):
        """迁移失败后的推荐下一步（需求 §十六：更多变式 / 关系理解 / 解释练习）。"""
        if correct:
            return {"action": "升级", "reason": "这一级已经通过，可以换更难一点的样子。"}

        used = clamp_level(level)
        try:
            mastery = float(mastery_score or 0)
        except (TypeError, ValueError):
            mastery = 0.0

        if mastery < 55:
            return {"action": "RELATIONSHIP", "name": "关系理解",
                    "reason": "基础题能做、换了样子不会，多半是关系没想清楚，先讲关系。",
                    "child": "我们先一起看清楚题目里的关系，再做变式。"}
        if used >= 3:
            return {"action": "EXPLAIN", "name": "解释练习",
                    "reason": "标准题与常规变式都能做，卡在结构变化 —— 让他讲一遍思路最容易暴露问题。",
                    "child": "你能用自己的话讲一讲这道题是怎么想的吗？"}
        return {"action": "MORE_VARIANTS", "name": "更多变式",
                "reason": "同等级多练两道变式，把模板记忆换成方法记忆。",
                "child": "我们再试两道长得不太一样的题。"}


DEFAULT_ENGINE = TransferEngine()


def suggest_level(mastery_score=0, deep_level=0, variant_failures=0):
    return DEFAULT_ENGINE.suggest_level(mastery_score, deep_level, variant_failures)


def local_variant(subject, knowledge, level=DEFAULT_LEVEL, base=None, avoid=(), stage=""):
    return DEFAULT_ENGINE.local_variant(subject, knowledge, level=level, base=base,
                                        avoid=avoid, stage=stage)


def ai_variant(subject, knowledge, level, **kwargs):
    return DEFAULT_ENGINE.ai_variant(subject, knowledge, level, **kwargs)


def make_question(subject, knowledge, level=DEFAULT_LEVEL, **kwargs):
    return DEFAULT_ENGINE.make_question(subject, knowledge, level=level, **kwargs)


def judge(level, correct, hint_used=0, response_time=0, confidence=""):
    return DEFAULT_ENGINE.judge(level, correct, hint_used, response_time, confidence)


def gap_action(level, correct, mastery_score=0):
    return DEFAULT_ENGINE.gap_action(level, correct, mastery_score)
