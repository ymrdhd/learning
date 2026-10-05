# ==============================================================
# 能力契约｜V2.7 自信度系统 + 猜测识别：正确性 × 自信度矩阵与快速验证安排（纯函数）
# 入口：CONFIDENCE_OPTIONS / CONFIDENCE_KEYS / VALUE_BY_KEY / HIGH_VALUE_SCENES / COMPLEX_DIFFICULTY /
#       ConfidenceEngine / DEFAULT_ENGINE / options / should_ask / matrix / guess_suspected /
#       verify_plan / normalize / option_of / label_of
# 依赖：deep_learning.evidence（自信度系数单一出口，避免两套权重）
# 不负责：界面采集 → frontend/learning-session.js；落库 → deep_learning/engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py、deep_learning/misconception_engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 自信度系统与猜测识别（需求 §十九 / §二十 / §二十一）。

**只在高价值场景采集**（诊断 / 迁移 / 主动回忆 / 复杂题 / 疑似猜测题），
不每道题都问，避免打断心流、拉长 Session（需求 §十九 / §三十一）。

四种儿童端选项（**不显示数字**）：

    🙂 很确定      🤔 有点确定      🎲 我猜的      😵 不会

正确性 × 自信度矩阵是本模块的核心（需求 §二十）：

| | 很确定 | 有点确定 | 猜的 / 不会 |
| --- | --- | --- | --- |
| **正确** | 强证据 | 普通证据 | 弱证据 + 触发一题快速验证 |
| **错误** | possible_misconception | 普通学习缺口 | 普通学习缺口 |
"""

from deep_learning import evidence as evidence_module

# --------------------------------------------------------------
# 儿童端选项（不下发任何数字，需求 §十九）
# --------------------------------------------------------------

CONFIDENCE_OPTIONS = (
    {"key": "sure", "icon": "🙂", "label": "很确定", "value": 1.0, "child": "我很有把握"},
    {"key": "maybe", "icon": "🤔", "label": "有点确定", "value": 0.6, "child": "我觉得差不多"},
    {"key": "guess", "icon": "🎲", "label": "我猜的", "value": 0.2, "child": "我是猜的"},
    {"key": "unknown", "icon": "😵", "label": "不会", "value": 0.0, "child": "我还不会"},
)

CONFIDENCE_KEYS = tuple(item["key"] for item in CONFIDENCE_OPTIONS)
OPTION_BY_KEY = {item["key"]: item for item in CONFIDENCE_OPTIONS}
VALUE_BY_KEY = {item["key"]: item["value"] for item in CONFIDENCE_OPTIONS}
LABEL_BY_KEY = {item["key"]: item["label"] for item in CONFIDENCE_OPTIONS}

# 高价值场景（需求 §十九）；不在其中的普通题不采集自信度
HIGH_VALUE_SCENES = ("diagnostic", "transfer", "recall", "complex", "suspected_guess", "explanation")

COMPLEX_DIFFICULTY = 60          # 难度达到它就算"复杂题"
GUESS_MASTERY_LINE = 60          # 掌握度低于它时"异常快且正确"要多想一步
FAST_RATIO = 0.35                # 用时 < 期望用时的 35% 视为异常快
EXPECTED_SECONDS = 40            # 单题期望用时（秒），没有题型信息时的默认值
EXPECTED_BY_KIND = {"choice": 30, "blank": 45, "short": 60, "reading": 120}
VERIFY_QUESTIONS = 1             # 猜对后安排的快速验证题量（需求 §二十一）

STRENGTH_TEXT = {
    "strong": "做对了而且很确定 —— 这是很扎实的证据",
    "normal": "记录下来了，我们继续",
    "weak": "先记下来，稍后我们再验证一次",
}


def normalize(key):
    """任意输入 → 合法自信度键（未知返回空串，表示"没有采集"）。"""
    value = str(key or "").strip().lower()
    return value if value in OPTION_BY_KEY else ""


def option_of(key):
    return dict(OPTION_BY_KEY.get(normalize(key), OPTION_BY_KEY["maybe"]))


def label_of(key):
    return LABEL_BY_KEY.get(normalize(key), "")


def options():
    """儿童端四选项（原样可直接下发给前端）。"""
    return [dict(item) for item in CONFIDENCE_OPTIONS]


def expected_seconds(kind=""):
    return float(EXPECTED_BY_KIND.get(str(kind or "").strip().lower(), EXPECTED_SECONDS))


class ConfidenceEngine:
    """自信度引擎（纯函数）。"""

    # ---------- 什么时候问 ----------

    def should_ask(self, scene="", difficulty=50, hint_level=0, correct=None,
                   response_time=0, mastery_score=None):
        """只在高价值场景采集（需求 §十九 / §二十五：控制认知负担与学习时长）。"""
        name = str(scene or "").strip().lower()
        if name in HIGH_VALUE_SCENES:
            return True

        try:
            if float(difficulty or 0) >= COMPLEX_DIFFICULTY:
                return True
        except (TypeError, ValueError):
            pass

        if int(hint_level or 0) >= 2:
            return False

        return self.guess_suspected(correct=correct, mastery_score=mastery_score,
                                    response_time=response_time)

    # ---------- 正确性 × 自信度矩阵 ----------

    def matrix(self, correct, confidence_key=""):
        """正确性 × 自信度 → {strength, factor, flags, text}（需求 §二十）。"""
        key = normalize(confidence_key)
        if not key:
            key = "maybe"

        if correct:
            if key == "sure":
                return self._out("strong", evidence_module.SURE_FACTOR, [],
                                 "做对了而且很确定，这个知识你掌握得挺扎实。")
            if key == "guess":
                return self._out("weak", evidence_module.GUESS_FACTOR, ["guess"],
                                 "做对了但你说在猜，我们再验证一题好不好？")
            if key == "unknown":
                return self._out("weak", 0.50, ["lucky"],
                                 "你觉得不会却做对了，我们再试一道确认一下。")
            return self._out("normal", 1.0, [], "做对了，记录下来了。")

        if key == "sure":
            return self._out("normal", 1.0, ["possible_misconception"],
                             "做错了但是你很确定 —— 可能有一个小地方理解偏了，我们一起看看。")
        if key == "guess":
            return self._out("weak", evidence_module.GUESS_FACTOR, ["guess"],
                             "没关系，这题本来就是没把握的，我们换个方式学。")
        if key == "unknown":
            return self._out("weak", evidence_module.UNSURE_FACTOR, ["known_gap"],
                             "这个还没学会，我们从最简单的一步开始。")
        return self._out("normal", 1.0, [], "没关系，我们再来一次。")

    @staticmethod
    def _out(strength, factor, flags, text):
        return {"strength": strength, "factor": round(float(factor), 4),
                "flags": list(flags), "text": text}

    # ---------- 猜测识别 ----------

    def guess_suspected(self, *, correct=None, confidence_key="", mastery_score=None,
                        response_time=0, expected=EXPECTED_SECONDS):
        """疑似猜测（需求 §二十一）：掌握度低 + 答题异常快 + 结果正确 + 学生说"猜的"。"""
        if str(confidence_key or "").strip().lower() == "guess":
            return True
        if correct is not True:
            return False

        try:
            mastery = float(mastery_score) if mastery_score is not None else 100.0
        except (TypeError, ValueError):
            mastery = 100.0
        if mastery >= GUESS_MASTERY_LINE:
            return False

        try:
            used = float(response_time or 0)
        except (TypeError, ValueError):
            used = 0.0
        if used <= 0:
            return False

        try:
            limit = float(expected or EXPECTED_SECONDS) * FAST_RATIO
        except (TypeError, ValueError):
            limit = EXPECTED_SECONDS * FAST_RATIO
        return used <= limit

    def verify_plan(self, *, correct=None, confidence_key="", mastery_score=None,
                    response_time=0, expected=EXPECTED_SECONDS):
        """猜对之后不要大幅提高掌握度，而是安排一题快速验证（需求 §二十一）。"""
        key = normalize(confidence_key)
        suspected = self.guess_suspected(correct=correct, confidence_key=key,
                                         mastery_score=mastery_score,
                                         response_time=response_time, expected=expected)
        if not suspected:
            return {"needed": False, "questions": 0, "reason": ""}

        if key == "guess":
            reason = "你说这题是猜的 —— 再做一题就知道是不是真的会了。"
        else:
            reason = "这题做得特别快又对了 —— 再做一题确认一下。"

        return {
            "needed": True,
            "questions": VERIFY_QUESTIONS,
            "reason": reason,
            "child_message": "再试一题就好，不用紧张～",
            "after": "第二次也做对，才会把它当成真的会了。",
        }


DEFAULT_ENGINE = ConfidenceEngine()


def should_ask(scene="", difficulty=50, hint_level=0, correct=None,
               response_time=0, mastery_score=None):
    return DEFAULT_ENGINE.should_ask(scene, difficulty, hint_level, correct,
                                     response_time, mastery_score)


def matrix(correct, confidence_key=""):
    return DEFAULT_ENGINE.matrix(correct, confidence_key)


def guess_suspected(**kwargs):
    return DEFAULT_ENGINE.guess_suspected(**kwargs)


def verify_plan(**kwargs):
    return DEFAULT_ENGINE.verify_plan(**kwargs)
