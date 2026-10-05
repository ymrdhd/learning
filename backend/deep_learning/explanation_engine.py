# ==============================================================
# 能力契约｜V2.7 解释引擎（讲给菲比听）：概念覆盖度判定与儿童友好反馈，只看概念对不对，不挑语法（纯函数）
# 入口：EXPLANATION_EVIDENCE / CONCEPT_TABLE / GENERIC_CONCEPTS / REASON_WORDS / MECHANICAL_WORDS /
#       HIGH_VALUE_KNOWLEDGE / ExplanationEngine / DEFAULT_ENGINE / concepts_for / should_ask /
#       prompt_for / evaluate / merge_ai / coverage / child_feedback
# 依赖：deep_learning.explanation_engine 自身无项目依赖；AI 评价经 ai_evaluate 延迟导入 deepseek
# 不负责：AI 直接改掌握度（禁止，需求 §三十六）→ 证据入库后才由 DeepMasteryEngine 更新
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py、deep_learning/routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 解释引擎 —— 儿童版费曼学习「讲给菲比听」（需求 §二十三 ~ §二十五、§三十六）。

菲比问：**「你能告诉我为什么 12÷3=4 吗？」** 孩子用文字（或已有语音输入转成的文字）回答，
系统判断**是否覆盖核心概念**。

三条铁律：

1. **不能因为孩子表达不完整、语法不好就判定理解错误** —— 核心看概念是否正确；
2. **不是每道题都要求解释**（只用于核心知识 / 多次错误知识 / 迁移失败 / 疑似机械记忆 / 重要概念验证）；
3. **AI 不直接修改 mastery**（需求 §三十六）：AI 评价 → ExplanationEngine 校验 → LearningEvidence
   → DeepMasteryEngine 更新状态。
"""

import unicodedata

EXPLANATION_EVIDENCE = "EXPLANATION"

# 核心概念表：知识点 → 必须说到的概念（keywords 用于宽松匹配）
CONCEPT_TABLE = {
    "长方形与正方形的面积": [
        {"concept": "面积 = 长 × 宽", "keywords": ["长", "宽", "乘", "面积"]},
        {"concept": "面积单位是平方单位", "keywords": ["平方", "面积单位"]},
    ],
    "表内除法": [
        {"concept": "平均分", "keywords": ["平均分", "每份", "分成"]},
        {"concept": "除法是乘法的逆运算", "keywords": ["乘", "反过来", "逆", "几倍"]},
    ],
    "分数的意义": [
        {"concept": "把整体平均分成若干份", "keywords": ["平均分", "整体", "份"]},
        {"concept": "取其中的几份", "keywords": ["取", "几份", "其中"]},
    ],
    "两步计算应用题": [
        {"concept": "先求中间量", "keywords": ["先", "中间", "第一步"]},
        {"concept": "再求最终问题", "keywords": ["再", "然后", "最后"]},
    ],
    "圆的周长与面积": [
        {"concept": "周长 = π × 直径", "keywords": ["π", "圆周率", "直径", "周长"]},
        {"concept": "面积 = π × 半径²", "keywords": ["半径", "平方", "面积"]},
    ],
    "乘法口诀": [
        {"concept": "几个相同数相加", "keywords": ["相加", "相同", "几个"]},
        {"concept": "口诀能直接算出结果", "keywords": ["口诀", "得数"]},
    ],
    "比与比例": [
        {"concept": "比表示两个量的倍数关系", "keywords": ["倍数", "关系", "相比"]},
        {"concept": "比例的内项之积等于外项之积", "keywords": ["内项", "外项", "相等"]},
    ],
    "拼音与声调": [
        {"concept": "声母 + 韵母拼成音节", "keywords": ["声母", "韵母", "拼"]},
        {"concept": "声调表示音高的变化", "keywords": ["声调", "第几", "音"]},
    ],
    "修辞手法": [
        {"concept": "把事物当成人来写（拟人）", "keywords": ["当成人", "拟人", "人一样"]},
        {"concept": "用相似的事物打比方（比喻）", "keywords": ["像", "好像", "打比方", "比喻"]},
    ],
    "记叙文阅读理解": [
        {"concept": "从文中找依据", "keywords": ["文中", "原文", "句子", "依据"]},
        {"concept": "概括主要内容", "keywords": ["主要", "概括", "讲了", "内容"]},
    ],
    "一般现在时（第三人称单数）": [
        {"concept": "主语是第三人称单数时动词加 s/es", "keywords": ["第三人称", "加s", "加es", "he", "she"]},
        {"concept": "表示经常发生的动作", "keywords": ["经常", "每天", "习惯"]},
    ],
    "名词单复数": [
        {"concept": "多个要变复数", "keywords": ["复数", "多个", "两"]},
        {"concept": "一般加 s，特殊要记", "keywords": ["加s", "特殊", "不规则"]},
    ],
    "现在进行时": [
        {"concept": "表示正在发生的动作", "keywords": ["正在", "现在", "此刻"]},
        {"concept": "be + 动词 ing", "keywords": ["be", "ing", "动词"]},
    ],
    "单词拼读": [
        {"concept": "按音节拼读", "keywords": ["音节", "拼", "读"]},
        {"concept": "字母组合发音规律", "keywords": ["字母", "组合", "发音"]},
    ],
}

# 表里没有的知识点：用题干 + 知识点本身生成通用概念
GENERIC_CONCEPTS = (
    {"concept": "说清楚知识点本身是什么意思", "keywords": []},
    {"concept": "说清楚为什么这样做", "keywords": ["因为", "所以", "为什么", "意思是", "表示"]},
)

# 算"说清了原因"的词
REASON_WORDS = ("因为", "所以", "意思是", "表示", "也就是", "就等于", "原因", "如果", "那么", "就是")

# 机械记忆信号（需求 §二十三 / §二十五：疑似机械记忆要触发解释练习）
MECHANICAL_WORDS = ("背", "记住", "老师说的", "反正", "不知道", "就是这样", "书上写的", "口诀就是")

# 明确要求做解释的高价值知识点（需求 §二十五）
HIGH_VALUE_KNOWLEDGE = (
    "长方形与正方形的面积", "分数的意义", "圆的周长与面积", "比与比例", "两步计算应用题",
    "修辞手法", "记叙文阅读理解", "一般现在时（第三人称单数）", "现在进行时", "名词单复数",
)

# 解释练习的触发条件（需求 §二十五：不要每道题都要求解释）
TRIGGER_REASONS = {
    "core_knowledge": "这是核心知识，值得确认是不是真的理解",
    "repeated_error": "这个知识点错过好几次了",
    "transfer_failed": "标准题会做、换了样子不会，可能是只记住了模板",
    "mechanical": "回答听起来像在背，而不是在解释",
    "important_check": "重要概念验证",
}

GOOD_FEEDBACK = "你说清楚了最关键的地方，菲比听懂了！"
PARTIAL_FEEDBACK = "你说的方向是对的，还差一点点没说全，菲比帮你想一想。"
MISSING_FEEDBACK = "再想想这个知识点到底在说什么，菲比等你慢慢说。"


def _norm(text):
    value = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    for ch in " \t\r\n，。！？；：、,.!?;:\"'（）()【】[]《》<>~—-…“”‘’":
        value = value.replace(ch, "")
    return value


class ExplanationEngine:
    """解释评价引擎（纯函数，不碰数据库、不调 AI）。"""

    # ---------- 概念 ----------

    def concepts_for(self, subject="", knowledge="", question=""):
        """取得该知识点的期望概念（需求 §二十四 的 ``expected_concepts`` 缺省来源）。"""
        items = CONCEPT_TABLE.get(str(knowledge or "").strip())
        if items:
            return [dict(item) for item in items]

        out = []
        for item in GENERIC_CONCEPTS:
            keywords = list(item["keywords"])
            if keywords and _norm(question):
                keywords = [word for word in keywords if _norm(word) in _norm(question)] or keywords
            out.append({"concept": item["concept"], "keywords": keywords, "generic": True})
        return out

    # ---------- 使用频率（需求 §二十五） ----------

    def should_ask(self, knowledge="", wrong_count=0, transfer_failed=False,
                   deep_level=0, hint_dependency=0.0, recent_explanations=0):
        """只在这些情况下要求"讲给菲比听"，控制认知负担与学习时长。"""
        name = str(knowledge or "").strip()
        reasons = []

        if name in HIGH_VALUE_KNOWLEDGE:
            reasons.append("core_knowledge")
        try:
            if int(wrong_count or 0) >= 2:
                reasons.append("repeated_error")
        except (TypeError, ValueError):
            pass
        if transfer_failed:
            reasons.append("transfer_failed")
        try:
            if float(hint_dependency or 0) >= 0.6:
                reasons.append("mechanical")
        except (TypeError, ValueError):
            pass

        try:
            if int(recent_explanations or 0) >= 1:
                reasons = [item for item in reasons if item == "repeated_error"]
        except (TypeError, ValueError):
            pass

        if not reasons:
            return {"ask": False, "reason": "", "text": ""}

        key = reasons[0]
        return {
            "ask": True,
            "reason": key,
            "reasons": reasons,
            "text": TRIGGER_REASONS.get(key, ""),
            "child": "你能讲给菲比听吗？用自己的话说说就好，说多短都没关系。",
        }

    # ---------- 提问话术 ----------

    def prompt_for(self, knowledge="", question="", subject=""):
        """菲比的提问（需求 §二十三）。"""
        stem = str(question or "").strip()
        if stem:
            return {
                "speaker": "菲比",
                "child": "你能告诉菲比，这道题为什么这样做吗？",
                "question": stem,
                "hint": "可以用自己的话说，说错了也没关系。",
                "placeholders": ["因为……", "也就是说……", "第一步先……"],
            }
        return {
            "speaker": "菲比",
            "child": "你能告诉菲比，%s 是什么意思吗？" % (str(knowledge or "").strip() or "这个知识点"),
            "question": "",
            "hint": "可以用自己的话说，说错了也没关系。",
            "placeholders": ["因为……", "也就是说……"],
        }

    # ---------- 判定 ----------

    def evaluate(self, subject="", grade=3, knowledge="", question="", expected_concepts=None,
                 student_explanation="", transfer_failed=False):
        """判定孩子的解释（需求 §二十四）。

        返回 ``{core_concept_correct, concept_coverage, missing_concepts,
        possible_misconceptions, quality_score, feedback}`` 及其它诊断字段。
        """
        expected = self._expectations(expected_concepts) or self.concepts_for(subject, knowledge, question)
        text = _norm(student_explanation)
        raw = str(student_explanation or "").strip()

        matched, missing = [], []
        for item in expected:
            if self._hit(item, text):
                matched.append(item["concept"])
            else:
                missing.append(item["concept"])

        total = len(expected) or 1
        coverage = len(matched) / float(total)
        core_correct = bool(matched)

        reason_hit = any(word in raw for word in REASON_WORDS)
        mechanical = any(word in raw for word in MECHANICAL_WORDS) and not reason_hit
        long_enough = len(raw) >= 8

        score = coverage * 60.0
        score += 15.0 if reason_hit else 0.0
        score += 15.0 if long_enough else 0.0
        score += 10.0 if mechanical is False else 0.0
        if core_correct:
            score = max(score, 60.0)     # 说到核心概念就不算不理解（需求 §二十四）
        score = int(max(0, min(100, round(score))))

        misconceptions = self._misconceptions(raw, text, coverage, mechanical)

        if core_correct and coverage >= 0.6:
            feedback = GOOD_FEEDBACK
        elif core_correct:
            feedback = PARTIAL_FEEDBACK
        else:
            feedback = MISSING_FEEDBACK

        if missing and core_correct:
            feedback += "还差一点点：" + "、".join(missing[:2])

        return {
            "subject": subject,
            "grade": grade,
            "knowledge": knowledge,
            "core_concept_correct": core_correct,
            "concept_coverage": round(coverage, 3),
            "matched_concepts": matched,
            "missing_concepts": missing,
            "possible_misconceptions": misconceptions,
            "quality_score": score,
            "length": len(raw),
            "reason_words": reason_hit,
            "mechanical": mechanical,
            "transfer_failed": bool(transfer_failed),
            "feedback": feedback,
            "child_feedback": feedback,
            "evidence_type": EXPLANATION_EVIDENCE,
            "source": "rule",
            "note": "只看概念对不对，不因为表达不完整或语法不好扣分。",
        }

    def _expectations(self, expected_concepts):
        if not expected_concepts:
            return []
        out = []
        for item in expected_concepts:
            if isinstance(item, dict):
                concept = str(item.get("concept") or item.get("name") or "").strip()
                keywords = [str(word).strip() for word in (item.get("keywords") or []) if str(word).strip()]
            else:
                concept = str(item or "").strip()
                keywords = []
            if not concept:
                continue
            if not keywords:
                keywords = self._keywords_of(concept)
            out.append({"concept": concept, "keywords": keywords})
        return out

    @staticmethod
    def _keywords_of(concept):
        """从概念句子里切出关键词（≥2 字的中文片段）。"""
        clean = _norm(concept)
        words = []
        for part in [clean[i:i + 2] for i in range(max(0, len(clean) - 1))]:
            if len(part) == 2 and part not in words:
                words.append(part)
        return words[:4]

    @staticmethod
    def _hit(item, text):
        if not text:
            return False
        keywords = [str(word).strip().lower() for word in (item.get("keywords") or []) if str(word).strip()]
        if not keywords:
            return False
        hits = sum(1 for word in keywords if _norm(word) and _norm(word) in text)
        return hits >= max(1, (len(keywords) + 1) // 2)

    @staticmethod
    def _misconceptions(raw, text, coverage, mechanical):
        out = []
        if mechanical:
            out.append("像在背答案，而不是在解释原因")
        if not raw:
            out.append("没有说出解释")
        if coverage <= 0.5 and raw and any(word in raw for word in ("因为他是", "因为是", "反正", "肯定是")):
            out.append("用想当然的理由代替了推理")
        return out

    # ---------- AI 辅助（只建议，不改掌握度） ----------

    def merge_ai(self, rule_result, ai_result):
        """把 AI 评价并入规则评价（需求 §三十六：AI 只提供结构化建议）。"""
        out = dict(rule_result or {})
        if not isinstance(ai_result, dict):
            out["ai"] = None
            return out

        ai_missing = [str(item).strip() for item in (ai_result.get("missing_concepts") or []) if str(item).strip()]
        ai_mis = [str(item).strip() for item in (ai_result.get("possible_misconceptions") or []) if str(item).strip()]

        merged_missing = list(out.get("missing_concepts") or [])
        for item in ai_missing:
            if item not in merged_missing:
                merged_missing.append(item)

        merged_mis = list(out.get("possible_misconceptions") or [])
        for item in ai_mis:
            if item not in merged_mis:
                merged_mis.append(item)

        try:
            ai_score = float(ai_result.get("quality_score"))
        except (TypeError, ValueError):
            ai_score = None

        if ai_score is not None and out.get("source") == "rule":
            # 规则判定说到了核心概念时，AI 不允许把它压到"不理解"（需求 §二十四）
            if out.get("core_concept_correct"):
                ai_score = max(ai_score, 60.0)
            out["quality_score"] = int(max(0, min(100, round((out.get("quality_score", 0) + ai_score) / 2.0))))
            out["source"] = "rule+ai"

        out["missing_concepts"] = merged_missing
        out["possible_misconceptions"] = merged_mis
        if ai_result.get("feedback"):
            out["ai_feedback"] = str(ai_result["feedback"])
        out["ai"] = {
            "core_concept_correct": ai_result.get("core_concept_correct"),
            "concept_coverage": ai_result.get("concept_coverage"),
            "quality_score": ai_score,
        }
        return out

    def ai_evaluate(self, subject="", grade=3, knowledge="", question="", expected_concepts=None,
                    student_explanation=""):
        """调用 DeepSeek 做解释评价辅助；离线/异常返回 None（需求 §三十七）。"""
        try:
            import deepseek
        except Exception:
            return None
        if not getattr(deepseek, "KEY", ""):
            return None
        try:
            return deepseek.evaluate_explanation(
                subject=subject, grade=grade, knowledge=knowledge, question=question,
                expected_concepts=expected_concepts, student_explanation=student_explanation)
        except Exception:
            return None

    def evaluate_with_ai(self, **kwargs):
        """规则评价 + AI 辅助合并；AI 失败时等价于纯规则评价。"""
        use_ai = kwargs.pop("use_ai", True)
        rule = self.evaluate(**kwargs)
        if not use_ai:
            return rule
        ai = self.ai_evaluate(subject=kwargs.get("subject", ""), grade=kwargs.get("grade", 3),
                              knowledge=kwargs.get("knowledge", ""), question=kwargs.get("question", ""),
                              expected_concepts=kwargs.get("expected_concepts"),
                              student_explanation=kwargs.get("student_explanation", ""))
        if ai is None:
            rule["ai"] = None
            return rule
        return self.merge_ai(rule, ai)

    def coverage(self, expected_concepts, student_explanation):
        result = self.evaluate(expected_concepts=expected_concepts,
                               student_explanation=student_explanation)
        return {"concept_coverage": result["concept_coverage"],
                "matched": result["matched_concepts"],
                "missing": result["missing_concepts"]}

    def child_feedback(self, result):
        text = str((result or {}).get("feedback") or "").strip()
        if text:
            return text
        return "谢谢你的解释，菲比听懂了～"


DEFAULT_ENGINE = ExplanationEngine()


def concepts_for(subject="", knowledge="", question=""):
    return DEFAULT_ENGINE.concepts_for(subject, knowledge, question)


def should_ask(knowledge="", wrong_count=0, transfer_failed=False, deep_level=0,
               hint_dependency=0.0, recent_explanations=0):
    return DEFAULT_ENGINE.should_ask(knowledge, wrong_count, transfer_failed, deep_level,
                                     hint_dependency, recent_explanations)


def prompt_for(knowledge="", question="", subject=""):
    return DEFAULT_ENGINE.prompt_for(knowledge, question, subject)


def evaluate(subject="", grade=3, knowledge="", question="", expected_concepts=None,
             student_explanation="", transfer_failed=False):
    return DEFAULT_ENGINE.evaluate(subject, grade, knowledge, question, expected_concepts,
                                   student_explanation, transfer_failed)


def evaluate_with_ai(**kwargs):
    return DEFAULT_ENGINE.evaluate_with_ai(**kwargs)


def merge_ai(rule_result, ai_result):
    return DEFAULT_ENGINE.merge_ai(rule_result, ai_result)
