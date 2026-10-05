# ==============================================================
# 能力契约｜复习出题：不重复历史原题，50/30/20 模式配比
# 入口：ReviewQuestionSelector.build / is_duplicate / choose_mode / similarity / normalize_stem
# 依赖：random re diagnostic_bank knowledge_tree stages question_dedupe（题干雷同判定唯一真相）
# 不负责：自适应选题 → adaptive/selector.py
# 验证：python backend/verify_memory.py
# 被调用：review/engine.py、review_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统 · 复习题选择 ReviewQuestionSelector。

**复习题不能简单重复原题**：间隔复习考的是"知识迁移"，不是"记住那道题的答案"。
所以原题 `36 × 24` 复习时应该换成 `42 × 18`，或者换情境
（"一盒彩笔 18 支，学校买了 42 盒，一共有多少支？"）。

题源结构（按成熟度动态调整迁移题比例）：

| 模式 | 普通知识点 | 长期掌握 | 说明 |
| --- | --- | --- | --- |
| `same` | 50% | 20% | 同知识点、换数字/换题目 |
| `variant` | 30% | 40% | 同知识点变式（换表达、换情境） |
| `transfer` | 20% | 40% | 迁移题（结合前后知识点、略高一个阶段） |

出题优先级：

1. **AI**（配了 DeepSeek Key 时）：prompt 里带上历史原题与"不要重复"的硬约束
2. **本地题库/生成器**（`diagnostic_bank`）：数学按阶段随机生成新数字，
   语文/英语从题库里轮换没出过的题
3. **兜底变式**：内置题做数字替换 + 答案重算

每次出题后都会做一次**重复检测**：题干完全相同，或"数字序列相同且文字高度相似"
就判为重复，换一道再来（最多 3 轮）。
"""

import random

import diagnostic_bank
import knowledge_tree
import question_dedupe
import stages

MODES = ("same", "variant", "transfer")
MODE_TEXT = {"same": "同知识点新题", "variant": "变式题", "transfer": "迁移题"}

MODE_WEIGHTS = {"same": 0.50, "variant": 0.30, "transfer": 0.20}
LONG_TERM_WEIGHTS = {"same": 0.20, "variant": 0.40, "transfer": 0.40}
MATURE_LEVELS = ("STABLE", "LONG_TERM")

DUPLICATE_THRESHOLD = question_dedupe.DUPLICATE_THRESHOLD
HISTORY_LIMIT = 5
MAX_ATTEMPTS = 3

# 题干归一化 / 数字序列 / 相似度 / 重复判定统一由 question_dedupe 提供，
# 保证"日常练习"与"间隔复习"用的是同一套雷同判定规则。
normalize_stem = question_dedupe.normalize_stem
numbers_of = question_dedupe.numbers_of
similarity = question_dedupe.similarity
is_duplicate = question_dedupe.is_duplicate

# 兜底题的期望作答时间（秒），复习记录里用来判断 HARD / EASY
EXPECTED_SECONDS = 45.0


def choose_mode(maturity_level="LEARNING", rng=None):
    """按成熟度抽题源模式；长期掌握的知识多考迁移。"""
    rng = rng or random.Random()
    weights = (LONG_TERM_WEIGHTS if str(maturity_level or "").upper() in MATURE_LEVELS
               else MODE_WEIGHTS)
    roll = rng.random()
    cumulative = 0.0
    for mode in MODES:
        cumulative += float(weights[mode])
        if roll < cumulative:
            return mode
    return MODES[-1]


class ReviewQuestionSelector:
    """复习题选择器（重复检测与模式配比可独立单测）。"""

    # ---------------- 历史原题 ----------------

    def history(self, db, student_id, subject, knowledge, limit=HISTORY_LIMIT):
        """这个知识点最近做过的题干（复习出题时要避开它们）。"""
        from models import AnswerRecord, Question

        rows = (
            db.query(Question)
            .join(AnswerRecord, AnswerRecord.question_id == Question.id)
            .filter(AnswerRecord.student_id == student_id,
                    AnswerRecord.subject == subject,
                    AnswerRecord.knowledge == knowledge)
            .order_by(AnswerRecord.id.desc())
            .limit(max(1, int(limit)))
            .all()
        )

        stems = [row.question for row in rows if row.question]
        if stems:
            return stems

        # 没有答题记录时退回"这个知识点出过的题"
        rows = (
            db.query(Question)
            .filter(Question.subject == subject, Question.knowledge == knowledge)
            .order_by(Question.id.desc())
            .limit(max(1, int(limit)))
            .all()
        )
        return [row.question for row in rows if row.question]

    # ---------------- 出题 ----------------

    def build(self, db, student_id, subject, knowledge, difficulty=50,
              maturity_level="", rng=None, use_ai=False, grade="三年级"):
        """生成一道复习题（保证与历史原题不同）。

        返回 dict：question / options / answer / qtype / analysis / knowledge /
        difficulty / source / mode / repeated。
        """
        rng = rng or random.Random()
        knowledge = str(knowledge or "").strip()
        difficulty = int(max(1, min(100, int(difficulty or 50))))

        history = self.history(db, student_id, subject, knowledge)
        mode = choose_mode(maturity_level, rng)

        stage_key = (knowledge_tree.stage_of_any(subject, knowledge)
                     or stages.key_of_difficulty(difficulty))
        target_stage = stages.next_key(stage_key) if mode == "transfer" else stage_key

        # 1) AI 生成（配了 Key 时）
        if use_ai:
            data = self._from_ai(subject, grade, knowledge, difficulty, mode, history)
            if data is not None and not is_duplicate(data.get("question"), history):
                return self._pack(data, subject, knowledge, difficulty, mode, target_stage)

        # 2) 本地题库 / 生成器
        avoid = list(history)
        for _ in range(MAX_ATTEMPTS):
            data = diagnostic_bank.build_question(subject, target_stage, avoid=avoid)
            if not data:
                break
            if not is_duplicate(data.get("question"), history):
                return self._pack(data, subject, knowledge, difficulty, mode, target_stage)
            avoid.append(data.get("question"))

        # 3) 兜底变式（把内置题换数字，答案重算）
        data = self.fallback_variant(rng)
        return self._pack(data, subject, knowledge, difficulty, mode, target_stage,
                          repeated=True)

    @staticmethod
    def _from_ai(subject, grade, knowledge, difficulty, mode, history):
        import deepseek

        if not deepseek.KEY:
            return None

        return deepseek.generate_review_question(
            subject, grade, knowledge, difficulty,
            history=history, mode=mode)

    @staticmethod
    def fallback_variant(rng=None):
        """内置兜底题的数字变式（纯本地、答案可重算）。"""
        rng = rng or random.Random()
        left = rng.randint(3, 19)
        right = rng.randint(2, 9)
        answer = left + right

        wrongs = {answer + 1, answer - 1, left * right if left * right != answer else answer + 2,
                  answer + 10}
        wrongs.discard(answer)
        wrong_texts = [str(value) for value in sorted(wrongs)][:3]

        options = [str(answer)] + wrong_texts
        rng.shuffle(options)
        letters = {}
        correct_letter = "A"
        for letter, text in zip(("A", "B", "C", "D"), options):
            letters[letter] = text
            if text == str(answer):
                correct_letter = letter

        return {
            "qtype": "choice",
            "question": f"算一算：{left} + {right} = ？",
            "options": letters,
            "answer": correct_letter,
            "answer_text": str(answer),
            "acceptable": [],
            "analysis": f"{left} 和 {right} 合起来是 {answer}。",
            "source": "fallback_variant",
        }

    @staticmethod
    def _pack(data, subject, knowledge, difficulty, mode, stage_key, repeated=False):
        """统一成出题结构，并把知识点锁定成复习的那个知识点。"""
        return {
            "qtype": data.get("qtype") or "choice",
            "question": data.get("question") or "",
            "options": data.get("options") or {},
            "answer": data.get("answer") or "",
            "acceptable": data.get("acceptable") or [],
            "analysis": data.get("analysis") or "",
            "knowledge": knowledge,
            "subject": subject,
            "stage": stage_key,
            "difficulty": difficulty,
            "source": "review_" + str(data.get("source") or "bank"),
            "mode": mode,
            "mode_text": MODE_TEXT.get(mode, ""),
            "repeated": bool(repeated),
            "expected_seconds": EXPECTED_SECONDS,
        }


DEFAULT_SELECTOR = ReviewQuestionSelector()
