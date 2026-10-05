# ==============================================================
# 能力契约｜V2.7 前置知识追踪与最小回补：沿依赖链找出「最小缺失能力」（只读数据库）
# 入口：PrerequisiteTracer / DEFAULT_TRACER / trace / minimal_repair / should_defer / chain / summarize
# 依赖：adaptive.strategy（DEPENDENCIES / prerequisites / dependency_chain，纯函数）+ models（只读）
# 不负责：掌握度写入 → knowledge_routes.update_mastery；任务落库 → habit.py / engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py（根因分析 / 前置回补任务）、daily_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 前置知识追踪与**最小回补**（需求 §十一 / §十二）。

依赖关系不另建表：直接复用 ``adaptive/strategy.py`` 的 ``DEPENDENCIES``（三科共 69 条边）
与 ``dependency_chain``。本模块只做两件事：

1. ``trace``：把前置链上每个知识的真实掌握情况列出来（练过没有、多少分、算不算薄弱）。
2. ``minimal_repair``：**不让孩子重学整个低年级章节**，而是从离当前知识最近的
   前置开始，找出**第一个练过却薄弱**的知识 —— 那就是"最小缺失能力"。

回补流程（需求 §十二）：

    当前知识暂缓 → 插入短前置知识任务 → 快速验证 → 恢复原知识学习
"""

from adaptive import strategy as strategy_module

# 判定阈值与策略层保持一致（strategy.WEAK_LINE / READY_LINE）
READY_LINE = getattr(strategy_module, "READY_LINE", 70)
WEAK_LINE = getattr(strategy_module, "WEAK_LINE", 70)

REPAIR_MINUTES = 5          # 回补任务时长（短，不侵占原计划）
REPAIR_QUESTIONS = 2        # 快速验证题量
MAX_TRACE_DEPTH = 3         # 依赖链最大追踪深度
MAX_TRACE_ITEMS = 6

STATE_GAP = "gap"           # 练过但薄弱
STATE_READY = "ready"       # 练过且达标
STATE_UNKNOWN = "unknown"   # 从未练过（不算缺口，但要标出来）


class PrerequisiteTracer:
    """前置知识追踪器（只读，不写任何表）。"""

    # ---------- 依赖链 ----------

    def chain(self, subject, knowledge, depth=MAX_TRACE_DEPTH):
        """返回 [自身, 最近前置, 更前置, …]（依赖缺失时至少返回 [自身]）。"""
        try:
            return list(strategy_module.dependency_chain(subject, knowledge, depth=depth) or [])
        except Exception:
            return [knowledge] if knowledge else []

    def prerequisites(self, subject, knowledge):
        """直接前置（不做递归）。"""
        try:
            return list(strategy_module.prerequisites(subject, knowledge) or [])
        except Exception:
            return []

    # ---------- 追踪 ----------

    def trace(self, db, student_id, subject, knowledge, depth=MAX_TRACE_DEPTH):
        """把前置链上每个知识的真实状态列出来（只读）。

        返回 ``[{"knowledge", "mastery_score", "total", "correct", "distance",
        "state", "weak", "practiced"}]``；第 0 项是当前知识自身。
        """
        names = self.chain(subject, knowledge, depth=depth)
        if not names:
            return []

        rows = self._rows(db, student_id, subject, names)
        out = []
        for index, name in enumerate(names[: MAX_TRACE_ITEMS + 1]):
            if not name:
                continue
            row = rows.get(name)
            mastery = int(getattr(row, "mastery_score", 0) or 0) if row else 0
            total = int(getattr(row, "total_questions", 0) or 0) if row else 0
            correct = int(getattr(row, "correct_questions", 0) or 0) if row else 0

            if total <= 0:
                state = STATE_UNKNOWN
            elif mastery < WEAK_LINE:
                state = STATE_GAP
            else:
                state = STATE_READY

            out.append({
                "knowledge": name,
                "mastery_score": mastery,
                "total": total,
                "correct": correct,
                "distance": index,
                "state": state,
                "weak": state == STATE_GAP,
                "practiced": total > 0,
            })
        return out

    def summarize(self, db, student_id, subject, knowledge):
        """追踪结果的汇总视图（给接口与调试看）。"""
        items = self.trace(db, student_id, subject, knowledge)
        weak = [item for item in items[1:] if item["weak"]]
        return {
            "knowledge": knowledge,
            "items": items,
            "weak": weak,
            "ready_line": READY_LINE,
            "has_gap": bool(weak),
        }

    # ---------- 最小回补 ----------

    def minimal_repair(self, db, student_id, subject, knowledge, depth=MAX_TRACE_DEPTH):
        """找**最小缺失能力**并给出回补方案；没有缺口时返回 ``None``。

        从离当前知识最近的前置开始逐级往外找，找到的第一个"练过却薄弱"的知识
        就是最小缺失能力 —— 它离当前知识最近，补它的代价最小。
        """
        items = self.trace(db, student_id, subject, knowledge, depth=depth)
        if len(items) < 2:
            return None

        target = None
        for item in items[1:]:
            if item["weak"]:
                target = item
                break

        if target is None:
            return None

        path = [entry["knowledge"] for entry in items[: target["distance"] + 1]]
        return {
            "needed": True,
            "defer_knowledge": knowledge,
            "insert_knowledge": target["knowledge"],
            "insert_mastery": target["mastery_score"],
            "distance": target["distance"],
            "path": path,
            "minutes": REPAIR_MINUTES,
            "verify_count": REPAIR_QUESTIONS,
            "verify_evidence": "PREREQUISITE_CHECK",
            "reason": "《%s》要先补《%s》这一小步，补完就回来继续。" % (knowledge, target["knowledge"]),
            "resume_hint": "补完这 %d 题，我们就回到《%s》。" % (REPAIR_QUESTIONS, knowledge),
            "mode": "MINIMAL_REPAIR",
        }

    def should_defer(self, db, student_id, subject, knowledge):
        """当前知识是否应该暂缓（有最小回补方案 → True）。"""
        return self.minimal_repair(db, student_id, subject, knowledge) is not None

    # ---------- 内部 ----------

    @staticmethod
    def _rows(db, student_id, subject, names):
        """一次性把依赖链上的掌握度查出来（只读；失败时返回空表而不是抛异常）。"""
        try:
            from models import StudentKnowledgeMastery
        except Exception:
            return {}

        try:
            query = db.query(StudentKnowledgeMastery).filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.subject == subject,
                StudentKnowledgeMastery.knowledge_id.in_(list(names)),
            )
            return {row.knowledge_id: row for row in query.all()}
        except Exception:
            return {}


DEFAULT_TRACER = PrerequisiteTracer()


def chain(subject, knowledge, depth=MAX_TRACE_DEPTH):
    return DEFAULT_TRACER.chain(subject, knowledge, depth=depth)


def trace(db, student_id, subject, knowledge, depth=MAX_TRACE_DEPTH):
    return DEFAULT_TRACER.trace(db, student_id, subject, knowledge, depth=depth)


def minimal_repair(db, student_id, subject, knowledge, depth=MAX_TRACE_DEPTH):
    return DEFAULT_TRACER.minimal_repair(db, student_id, subject, knowledge, depth=depth)


def should_defer(db, student_id, subject, knowledge):
    return DEFAULT_TRACER.should_defer(db, student_id, subject, knowledge)


def summarize(db, student_id, subject, knowledge):
    return DEFAULT_TRACER.summarize(db, student_id, subject, knowledge)
