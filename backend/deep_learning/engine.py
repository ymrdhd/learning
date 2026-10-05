# ==============================================================
# 能力契约｜V2.7 Deep Mastery 引擎：学习证据 / 深度掌握状态 / 根因 / 迁移 / 解释 / 效率的唯一碰库门面
# 入口：DeepMasteryEngine / DEFAULT_ENGINE / record_evidence / refresh / detail / status / summary / map_levels / growth / efficiency / plan_hint / focus_knowledge / analyze_root_cause / root_cause_detail / record_root_cause / record_transfer / transfer_plan / record_explanation / explain_should_ask / explain_prompt / misconception / confidence_options / confidence_plan / guess_check / evidence_rows / ensure_states
# 依赖：models.py（deep_mastery_state / learning_evidence / root_cause_record / transfer_attempt / explanation_attempt）、database.py、deep_learning 各纯函数子模块、deepseek.py（可选，失败即降级）
# 不负责：出题与判分（main.py / grading.py）、掌握度写入（knowledge_routes.update_mastery）、记忆状态（review/）、HTTP 接口（deep_learning_routes.py）
# 验证：python backend/verify_v27.py
# 被调用：deep_learning_routes.py、main.py（启动重建）、main.py 的 POST /submit 与 recall/transfer 挂钩
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""Deep Mastery 引擎（V2.7）。

一句话：**把所有深度学习子模块的计算结果落到数据库，并且只在这里碰库。**

三条铁律：

1. **AI 永远不能直接改 mastery / deep mastery。** AI 只能产出候选，最终一律经
   `record_evidence` → `refresh`（规则重放）写入（需求 §三十四 / §三十六）。
2. **单题证据不可能顶满。** 状态由 `LearningEvidence` 全量重放（`replay`）得出，
   幂等、可重建，升级同时受分数门槛 + 证据条数 + 来源多样性约束（需求 §二十七）。
3. **严格按 student_id 隔离。** 所有查询都带 `student_id` 条件（需求 §四十）。
"""

import datetime
import json

from deep_learning import (
    confidence_engine,
    deep_mastery,
    evidence as evidence_module,
    explanation_engine,
    learning_efficiency,
    misconception_engine,
    prerequisite_tracer,
    root_cause as root_cause_module,
    transfer_engine,
    variant_ladder,
)
from models import (
    DailyLearningTask,
    DeepMasteryState,
    ExplanationAttempt,
    KnowledgeMemoryState,
    LearningEvidence,
    RootCauseRecord,
    StudentKnowledgeMastery,
    TransferAttempt,
    AnswerRecord,
)

# 迁移/重建时一次最多处理多少个知识点，避免启动期长事务
REBUILD_LIMIT = 2000

# 每种新增任务在每日计划里的时长预算（分钟）——深度学习不扩张 Session 时长（需求 §三十一）
PLAN_TASK_MINUTES = {
    "PREREQUISITE_REPAIR": 5,
    "TRANSFER": 4,
    "ACTIVE_RECALL": 3,
    "EXPLAIN": 3,
}
PLAN_TASK_ORDER = ("PREREQUISITE_REPAIR", "ACTIVE_RECALL", "TRANSFER", "EXPLAIN")
PLAN_MAX_EXTRA_TASKS = 2          # 每天最多额外加 2 个小任务，绝不全部强制出现（需求 §三十）
PLAN_TIME_BUDGET_RATIO = 0.4      # 额外任务最多吃掉计划总时长的 40%


def _now():
    return datetime.datetime.now()


def _text(value, default=""):
    if value is None:
        return default
    return str(value)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"


def _loads(text, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _growth_text(apply_count, star_count):
    """成长中心「深度成长」儿童文案：只讲事实，不出现内部指标（需求 §三十三）。"""
    parts = []
    if apply_count > 0:
        parts.append("这周有 %d 个知识从「会做」升级成「会应用」" % apply_count)
    if star_count > 0:
        parts.append("%d 个知识达到了 ⭐ 长期记住" % star_count)
    if not parts:
        return "这一周你在稳稳地打基础，菲比都记下来了～"
    return "；".join(parts) + "！"


class DeepMasteryEngine:
    """Deep Mastery 唯一碰库门面（需求 §四 / §二十六 / §二十七 / §三十八）。"""

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def state_row(self, db, student_id, subject, knowledge, create=True):
        """取（或按需创建）一个知识点的深度状态行。"""
        if db is None or not knowledge:
            return None
        row = (
            db.query(DeepMasteryState)
            .filter(
                DeepMasteryState.student_id == student_id,
                DeepMasteryState.subject == subject,
                DeepMasteryState.knowledge_id == knowledge,
            )
            .first()
        )
        if row is None and create:
            row = DeepMasteryState(
                student_id=student_id,
                subject=subject,
                knowledge_id=knowledge,
                current_level=0,
                level_key="UNKNOWN",
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(row)
            db.flush()
        return row

    def evidence_rows(self, db, student_id, subject=None, knowledge=None, evidence_type=None,
                      since=None, before=None, desc=False, limit=None):
        """按学生隔离读取学习证据（默认时间正序，`desc=True` 取最近优先）。"""
        if db is None:
            return []
        query = db.query(LearningEvidence).filter(LearningEvidence.student_id == student_id)
        if subject:
            query = query.filter(LearningEvidence.subject == subject)
        if knowledge:
            query = query.filter(LearningEvidence.knowledge_id == knowledge)
        if evidence_type:
            query = query.filter(LearningEvidence.evidence_type == evidence_type)
        if since is not None:
            query = query.filter(LearningEvidence.created_at >= since)
        if before is not None:
            query = query.filter(LearningEvidence.created_at < before)
        query = query.order_by(LearningEvidence.id.desc() if desc else LearningEvidence.id.asc())
        rows = query.all()
        if limit:
            rows = rows[: max(0, _int(limit, 0))]
        return rows

    def counts_of(self, db, student_id, subject, knowledge):
        """按证据类型计数：{STANDARD: 3, RECALL: 1, ...}。"""
        rows = (
            db.query(LearningEvidence.evidence_type)
            .filter(
                LearningEvidence.student_id == student_id,
                LearningEvidence.subject == subject,
                LearningEvidence.knowledge_id == knowledge,
            )
            .all()
        )
        counts = {}
        for (kind,) in rows:
            key = evidence_module.normalize_type(kind)
            counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _counts_of_rows(rows):
        counts = {}
        for row in rows or ():
            key = evidence_module.normalize_type(row.evidence_type)
            counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _state_of(row):
        """ORM 行 → 六维状态 dict（喂给 DeepMasteryModel 的纯函数）。"""
        return {
            "recognition": _float(getattr(row, "recognition_score", 0)),
            "understanding": _float(getattr(row, "understanding_score", 0)),
            "application": _float(getattr(row, "application_score", 0)),
            "transfer": _float(getattr(row, "transfer_score", 0)),
            "explanation": _float(getattr(row, "explanation_score", 0)),
            "retention": _float(getattr(row, "retention_score", 0)),
            "evidence_count": _int(getattr(row, "evidence_count", 0)),
            "hint_dependency": _float(getattr(row, "hint_dependency", 0.0)),
            "guess_count": _int(getattr(row, "guess_count", 0)),
        }

    @staticmethod
    def _items_of(rows):
        return [
            {
                "evidence_type": row.evidence_type,
                "result": row.result,
                "hint_level": row.hint_level,
                "confidence": row.confidence,
                "weight": row.weight,
            }
            for row in rows or ()
        ]

    def detail(self, db, student_id, subject, knowledge):
        """一个知识点的深度画像（含六维、等级、四项能力、升级缺口）。"""
        model = deep_mastery.DEFAULT_MODEL
        row = self.state_row(db, student_id, subject, knowledge, create=False)
        counts = self.counts_of(db, student_id, subject, knowledge)
        total = sum(counts.values())
        state = self._state_of(row) if row is not None else model.blank()
        if row is not None and total <= 0:
            total = _int(getattr(row, "evidence_count", 0), 0)
        level = model.level_of(state, counts, total)
        keys = deep_mastery.LEVEL_KEYS
        return {
            "student_id": student_id,
            "subject": subject,
            "knowledge": knowledge,
            "knowledge_id": knowledge,
            "level": level,
            "level_info": deep_mastery.level_dict(level),
            "level_key": keys[level] if 0 <= level < len(keys) else "UNKNOWN",
            "child_stage": model.child_stage(level),
            "abilities": model.abilities(state, counts),
            "dimensions": model.dimension_scores(state),
            "dimension_text": dict(deep_mastery.DIMENSION_TEXT),
            # score 是内部值：儿童端禁止直接展示（需求 §二十六）
            "score": model.score_of(state),
            "evidence_count": total,
            "counts": dict(counts),
            "hint_dependency": _float(state.get("hint_dependency"), 0.0),
            "guess_count": _int(state.get("guess_count"), 0),
            "misconception_flag": bool(getattr(row, "misconception_flag", False))
            if row is not None
            else False,
            "upgrade": model.upgrade_gap(state, counts, total),
            "updated_at": getattr(row, "updated_at", None) if row is not None else None,
        }

    def status(self, db, student_id, subject, knowledge):
        """**三层并列**返回：会不会做 / 是不是真懂 / 还记不记得（需求 §三，绝不合并）。"""
        mastery = (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.subject == subject,
                StudentKnowledgeMastery.knowledge_id == knowledge,
            )
            .first()
        )
        memory = (
            db.query(KnowledgeMemoryState)
            .filter(
                KnowledgeMemoryState.student_id == student_id,
                KnowledgeMemoryState.subject == subject,
                KnowledgeMemoryState.knowledge_id == knowledge,
            )
            .first()
        )
        return {
            "student_id": student_id,
            "subject": subject,
            "knowledge": knowledge,
            "mastery": {
                "score": _int(getattr(mastery, "mastery_score", 0)),
                "total": _int(getattr(mastery, "total_questions", 0)),
                "correct": _int(getattr(mastery, "correct_questions", 0)),
                "wrong": _int(getattr(mastery, "wrong_questions", 0)),
                "consecutive_wrong": _int(getattr(mastery, "consecutive_wrong", 0)),
                "answered": "这个知识会不会做",
            },
            "deep_mastery": self.detail(db, student_id, subject, knowledge),
            "memory": {
                "strength": _int(getattr(memory, "memory_strength", 0)),
                "maturity_level": _text(getattr(memory, "maturity_level", "NEW"), "NEW"),
                "forgetting_risk": _float(getattr(memory, "forgetting_risk", 0.0)),
                "stability": _float(getattr(memory, "stability", 1.0)),
                "needs_relearn": bool(getattr(memory, "needs_relearn", False)),
                "answered": "过一段时间还记不记得",
            },
            "separate": True,
            "note": "三层独立：掌握度=会不会做；深度=是不是真懂、能不能迁移与解释；记忆=延迟后还记不记得",
        }

    def summary(self, db, student_id, subject=None):
        """整生（或单科）深度分布，供成长中心 / 首页聚合使用。"""
        query = db.query(DeepMasteryState).filter(DeepMasteryState.student_id == student_id)
        if subject:
            query = query.filter(DeepMasteryState.subject == subject)
        rows = query.all()
        by_level = {}
        items = []
        for row in rows:
            level = _int(row.current_level, 0)
            by_level[level] = by_level.get(level, 0) + 1
            items.append(
                {
                    "subject": row.subject,
                    "knowledge": row.knowledge_id,
                    "level": level,
                    "level_key": row.level_key or "UNKNOWN",
                    "deep_mastery_score": _int(row.deep_mastery_score, 0),
                    "evidence_count": _int(row.evidence_count, 0),
                    "misconception_flag": bool(row.misconception_flag),
                }
            )
        items.sort(key=lambda item: (-item["level"], -item["deep_mastery_score"]))
        return {
            "student_id": student_id,
            "subject": subject,
            "total": len(items),
            "by_level": {str(key): value for key, value in sorted(by_level.items())},
            "levels": [deep_mastery.level_dict(i) for i in range(0, deep_mastery.MAX_LEVEL + 1)],
            "stars": [item for item in items if item["level"] >= 6],
            "applying": [item for item in items if item["level"] >= 4],
            "items": items,
        }

    def map_levels(self, db, student_id, subject=None):
        """知识地图用的深度状态：{知识点: {level, stage_key, icon, text, ...}}。"""
        query = db.query(DeepMasteryState).filter(DeepMasteryState.student_id == student_id)
        if subject:
            query = query.filter(DeepMasteryState.subject == subject)
        out = {}
        for row in query.all():
            level = _int(row.current_level, 0)
            stage = deep_mastery.DEFAULT_MODEL.child_stage(level)
            out[row.knowledge_id] = {
                "level": level,
                "level_key": row.level_key or "UNKNOWN",
                "stage_key": stage.get("key", ""),
                "icon": stage.get("icon", ""),
                "text": stage.get("text", ""),
                "desc": stage.get("desc", ""),
                "evidence_count": _int(row.evidence_count, 0),
                "misconception_flag": bool(row.misconception_flag),
            }
        return out

    def growth(self, db, student_id, days=7):
        """成长中心「深度成长」（需求 §三十三）：只给事实与儿童文案。"""
        days = max(1, _int(days, 7))
        start = _now() - datetime.timedelta(days=days)
        rows = db.query(DeepMasteryState).filter(DeepMasteryState.student_id == student_id).all()
        recent = [
            row
            for row in rows
            if getattr(row, "last_evidence_at", None) is not None and row.last_evidence_at >= start
        ]
        recent_apply = [row for row in recent if _int(row.current_level, 0) >= 4]
        stars = [row for row in rows if _int(row.current_level, 0) >= 6]
        recent_stars = [row for row in stars if row in recent]
        return {
            "student_id": student_id,
            "days": days,
            "active_count": len(recent),
            "apply_count": len(recent_apply),
            "apply_total": len([row for row in rows if _int(row.current_level, 0) >= 4]),
            "star_count": len(stars),
            "new_star_count": len(recent_stars),
            "items": [
                {
                    "subject": row.subject,
                    "knowledge": row.knowledge_id,
                    "level": _int(row.current_level, 0),
                    "level_key": row.level_key or "UNKNOWN",
                }
                for row in recent_apply
            ],
            "stars": [
                {"subject": row.subject, "knowledge": row.knowledge_id}
                for row in stars
            ],
            "child_text": _growth_text(len(recent_apply), len(recent_stars)),
        }

    # ------------------------------------------------------------------
    # 写入：证据与状态
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_result(value):
        if value is True:
            return "correct"
        if value is False:
            return "wrong"
        text = _text(value, "").strip().lower()
        if text in ("correct", "right", "true", "1", "对", "正确", "答对"):
            return "correct"
        if text in ("partial", "half", "0.5", "部分", "一半", "差不多"):
            return "partial"
        return "wrong"

    def record_evidence(self, db, student_id, subject, knowledge, *, evidence_type="STANDARD",
                        result="correct", question_id=0, difficulty=50, hint_level=0,
                        confidence="", response_time=0.0, source="submit", detail="",
                        when=None, commit=True):
        """写一条学习证据并立即刷新深度状态（唯一写入路径，需求 §六）。"""
        kind = evidence_module.normalize_type(evidence_type)
        normalized = self._normalize_result(result)
        weight = evidence_module.weight_of(kind, normalized, hint_level, confidence)
        dims = evidence_module.dimensions_of(kind)
        stamp = when or _now()
        row = LearningEvidence(
            student_id=student_id,
            subject=subject,
            knowledge_id=knowledge,
            evidence_type=kind,
            question_id=_int(question_id, 0),
            result=normalized,
            correct=(normalized == "correct"),
            difficulty=_int(difficulty, 50),
            hint_level=_int(hint_level, 0),
            confidence=_text(confidence),
            response_time=_float(response_time, 0.0),
            weight=weight,
            dimensions=_json(sorted(dims.keys())),
            source=_text(source, "submit"),
            detail=_text(detail),
            created_at=stamp,
        )
        db.add(row)
        db.flush()
        deep = self.refresh(db, student_id, subject, knowledge, commit=False)
        if commit:
            db.commit()
        return {
            "evidence_id": row.id,
            "evidence_type": kind,
            "result": normalized,
            "weight": weight,
            "strong": evidence_module.is_strong(weight),
            "dimensions": sorted(dims.keys()),
            "deep": deep,
        }

    def refresh(self, db, student_id, subject, knowledge, commit=True):
        """由证据全量重放 → 深度状态（幂等，可随时重建，需求 §二十七）。"""
        model = deep_mastery.DEFAULT_MODEL
        rows = self.evidence_rows(db, student_id, subject, knowledge)
        state = model.replay(self._items_of(rows))
        counts = self._counts_of_rows(rows)
        total = len(rows)
        level = model.level_of(state, counts, total)
        dims = model.dimension_scores(state)

        row = self.state_row(db, student_id, subject, knowledge, create=True)
        if row is not None:
            row.deep_mastery_score = model.score_of(state)
            row.recognition_score = dims["recognition"]
            row.understanding_score = dims["understanding"]
            row.application_score = dims["application"]
            row.transfer_score = dims["transfer"]
            row.explanation_score = dims["explanation"]
            row.retention_score = dims["retention"]
            row.current_level = level
            row.level_key = deep_mastery.LEVEL_KEYS[level]
            row.evidence_count = total
            row.standard_count = counts.get("STANDARD", 0)
            row.recall_count = counts.get("RECALL", 0)
            row.transfer_count = counts.get("TRANSFER", 0)
            row.explanation_count = counts.get("EXPLANATION", 0)
            row.delayed_count = counts.get("DELAYED_REVIEW", 0)
            row.recovery_count = counts.get("RECOVERY", 0)
            row.prerequisite_count = counts.get("PREREQUISITE_CHECK", 0)
            row.hint_dependency = _float(state.get("hint_dependency"), 0.0)
            row.guess_count = _int(state.get("guess_count"), 0)
            if rows:
                row.last_evidence_at = rows[-1].created_at or row.last_evidence_at
            row.updated_at = _now()
        if commit:
            db.commit()
        return self.detail(db, student_id, subject, knowledge)

    def ensure_states(self, db, student_id=None, commit=True):
        """从证据表重建全部深度状态（启动期 / 迁移后调用，幂等）。"""
        query = db.query(
            LearningEvidence.student_id,
            LearningEvidence.subject,
            LearningEvidence.knowledge_id,
        ).distinct()
        if student_id is not None:
            query = query.filter(LearningEvidence.student_id == student_id)
        pairs = query.limit(REBUILD_LIMIT).all()
        rebuilt = 0
        for sid, subject, knowledge in pairs:
            try:
                self.refresh(db, sid, subject, knowledge, commit=False)
                rebuilt += 1
            except Exception:
                db.rollback()
        if commit:
            db.commit()
        return {"rebuilt": rebuilt}

    # ------------------------------------------------------------------
    # 薄弱根因
    # ------------------------------------------------------------------

    def recent_history(self, db, student_id, subject, knowledge, limit=6):
        """最近若干次作答（新→旧），根因分析的历史证据。"""
        rows = (
            db.query(AnswerRecord)
            .filter(
                AnswerRecord.student_id == student_id,
                AnswerRecord.subject == subject,
                AnswerRecord.knowledge == knowledge,
            )
            .order_by(AnswerRecord.id.desc())
            .limit(max(1, _int(limit, 6)))
            .all()
        )
        return [
            {
                "correct": bool(row.correct),
                "result": "correct" if row.correct else "wrong",
                "difficulty": _int(row.difficulty, 50),
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def prerequisite_state(self, db, student_id, subject, knowledge):
        """前置知识状态（PrerequisiteTracer，失败返回空结构）。"""
        try:
            return prerequisite_tracer.DEFAULT_TRACER.summarize(db, student_id, subject, knowledge)
        except Exception:
            return {"knowledge": knowledge, "items": [], "weak": [], "has_gap": False}

    def analyze_root_cause(self, db, student_id, subject, knowledge, *, question="",
                           student_answer="", correct_answer="", error_type="",
                           response_time=0, hint_usage=0, confidence="", variant=False,
                           answer_record_id=0, question_id=0, use_ai=False, commit=True):
        """规则优先 + AI 辅助的根因分析（需求 §七 / §三十四 / §三十六）。"""
        mastery = (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.subject == subject,
                StudentKnowledgeMastery.knowledge_id == knowledge,
            )
            .first()
        )
        memory = (
            db.query(KnowledgeMemoryState)
            .filter(
                KnowledgeMemoryState.student_id == student_id,
                KnowledgeMemoryState.subject == subject,
                KnowledgeMemoryState.knowledge_id == knowledge,
            )
            .first()
        )
        prerequisite = self.prerequisite_state(db, student_id, subject, knowledge)
        analysis = root_cause_module.DEFAULT_ANALYZER.analyze(
            subject=subject,
            knowledge_id=knowledge,
            question=question,
            student_answer=student_answer,
            correct_answer=correct_answer,
            error_type=error_type,
            recent_history=self.recent_history(db, student_id, subject, knowledge),
            mastery_state=mastery,
            memory_state=memory,
            prerequisite_state=prerequisite,
            response_time=response_time,
            hint_usage=hint_usage,
            confidence=confidence,
            variant=variant,
            result="wrong",
        )
        if use_ai:
            ai = self._ai_root_cause(
                subject=subject,
                knowledge=knowledge,
                question=question,
                student_answer=student_answer,
                correct_answer=correct_answer,
                error_type=error_type,
                mastery_state=mastery,
                memory_state=memory,
                prerequisite_state=prerequisite,
                response_time=response_time,
                hint_usage=hint_usage,
                confidence=confidence,
            )
            if ai:
                analysis = self._merge_ai_cause(analysis, ai)
        record = self.record_root_cause(
            db,
            student_id,
            subject,
            knowledge,
            analysis,
            answer_record_id=answer_record_id,
            question_id=question_id,
            source=_text(analysis.get("source"), "rule"),
            commit=False,
        )
        if commit:
            db.commit()
        return {"analysis": analysis, "record": record, "prerequisite": prerequisite}

    @staticmethod
    def _ai_root_cause(**kwargs):
        """AI 辅助根因（失败/离线一律返回 None，绝不阻塞学习，需求 §三十七）。"""
        try:
            from deepseek import analyze_root_cause as ai_analyze

            memory = kwargs.get("memory_state")
            memory_text = ""
            if memory is not None:
                memory_text = "成熟度 %s / 遗忘风险 %.2f" % (
                    _text(getattr(memory, "maturity_level", ""), ""),
                    _float(getattr(memory, "forgetting_risk", 0.0)),
                )
            return ai_analyze(
                subject=kwargs.get("subject", "数学"),
                knowledge=kwargs.get("knowledge", ""),
                question=kwargs.get("question", ""),
                student_answer=kwargs.get("student_answer", ""),
                correct_answer=kwargs.get("correct_answer", ""),
                error_type=kwargs.get("error_type", ""),
                mastery_score=_int(getattr(kwargs.get("mastery_state"), "mastery_score", 0)),
                memory_state=memory_text,
                prerequisite_state=kwargs.get("prerequisite_state"),
                response_time=kwargs.get("response_time", 0),
                hint_usage=kwargs.get("hint_usage", 0),
                confidence=kwargs.get("confidence", ""),
                candidates=root_cause_module.causes_for(kwargs.get("subject", "数学")),
            )
        except Exception:
            return None

    @staticmethod
    def _merge_ai_cause(rule, ai):
        """AI 只能补充，不能覆盖规则判定的主因（需求 §三十四 / §三十六）。"""
        allowed = root_cause_module.causes_for(rule.get("subject", "数学"))
        merged = dict(rule)
        ai_cause = _text((ai or {}).get("root_cause_type"), "")
        if ai_cause in allowed and ai_cause != merged.get("root_cause_type"):
            merged["ai_suggestion"] = ai_cause
            merged["ai_confidence"] = _float((ai or {}).get("root_cause_confidence"), 0.0)
        if (ai or {}).get("analysis"):
            merged["ai_analysis"] = _text(ai.get("analysis"))
        merged["source"] = "rule+ai"
        return merged

    def record_root_cause(self, db, student_id, subject, knowledge, payload,
                          answer_record_id=0, question_id=0, source="rule", commit=True):
        """落一条根因记录（需求 §三十八 root_cause_record）。"""
        data = payload or {}
        row = RootCauseRecord(
            student_id=student_id,
            subject=subject,
            knowledge_id=knowledge,
            answer_record_id=_int(answer_record_id, 0),
            question_id=_int(question_id, 0),
            root_cause_type=_text(data.get("root_cause_type"), "CONCEPT_GAP"),
            root_cause_confidence=_float(data.get("root_cause_confidence"), 0.0),
            related_knowledge_ids=_json(data.get("related_knowledge_ids") or []),
            recommended_action=_text(data.get("recommended_action")),
            analysis=_text(data.get("analysis") or data.get("root_cause_text")),
            source=_text(source, "rule"),
            created_at=_now(),
        )
        db.add(row)
        db.flush()
        if commit:
            db.commit()
        return {
            "id": row.id,
            "root_cause_type": row.root_cause_type,
            "root_cause_confidence": row.root_cause_confidence,
            "root_cause_text": root_cause_module.cause_text(row.root_cause_type, subject),
            "recommended_action": row.recommended_action,
            "related_knowledge_ids": _loads(row.related_knowledge_ids, []),
            "analysis": row.analysis,
            "source": row.source,
            "created_at": row.created_at,
        }

    def root_cause_detail(self, db, student_id, knowledge=None, subject=None, limit=5):
        """根因历史 + 前置回补建议（供 GET /api/root-cause/{student_id}/{knowledge_id}）。"""
        query = db.query(RootCauseRecord).filter(RootCauseRecord.student_id == student_id)
        if knowledge:
            query = query.filter(RootCauseRecord.knowledge_id == knowledge)
        if subject:
            query = query.filter(RootCauseRecord.subject == subject)
        rows = query.order_by(RootCauseRecord.id.desc()).limit(max(1, _int(limit, 5))).all()
        items = [
            {
                "id": row.id,
                "subject": row.subject,
                "knowledge": row.knowledge_id,
                "root_cause_type": row.root_cause_type,
                "root_cause_confidence": _float(row.root_cause_confidence, 0.0),
                "root_cause_text": root_cause_module.cause_text(row.root_cause_type, row.subject),
                "recommended_action": row.recommended_action,
                "related_knowledge_ids": _loads(row.related_knowledge_ids, []),
                "analysis": row.analysis,
                "source": row.source,
                "created_at": row.created_at,
            }
            for row in rows
        ]
        latest = items[0] if items else None
        repair = None
        if latest:
            try:
                repair = prerequisite_tracer.DEFAULT_TRACER.minimal_repair(
                    db, student_id, latest["subject"], latest["knowledge"]
                )
            except Exception:
                repair = None
        detection = None
        if latest:
            try:
                detection = self.misconception(db, student_id, latest["subject"], latest["knowledge"])
            except Exception:
                detection = None
        return {
            "student_id": student_id,
            "knowledge": knowledge,
            "subject": subject,
            "latest": latest,
            "items": items,
            "repair": repair,
            "misconception": detection,
        }

    # ------------------------------------------------------------------
    # 前置知识 / 最小回补
    # ------------------------------------------------------------------

    def prerequisite_trace(self, db, student_id, subject, knowledge):
        """前置知识链追踪（需求 §十一）。"""
        try:
            return prerequisite_tracer.DEFAULT_TRACER.trace(db, student_id, subject, knowledge)
        except Exception:
            return {"knowledge": knowledge, "items": [], "weak": [], "has_gap": False}

    def minimal_repair(self, db, student_id, subject, knowledge):
        """最小回补方案（需求 §十二）：不重学整个低年级章节。"""
        try:
            return prerequisite_tracer.DEFAULT_TRACER.minimal_repair(db, student_id, subject, knowledge)
        except Exception:
            return None

    def should_defer(self, db, student_id, subject, knowledge):
        try:
            return bool(prerequisite_tracer.DEFAULT_TRACER.should_defer(db, student_id, subject, knowledge))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 知识迁移
    # ------------------------------------------------------------------

    def transfer_plan(self, db, student_id, subject, knowledge, minutes=None, base=None,
                      use_ai=True, grade=None):
        """一轮变式阶梯计划（需求 §十三~§十五）。"""
        deep = self.detail(db, student_id, subject, knowledge)
        mastery = self._mastery_of(db, student_id, subject, knowledge)
        failures = self._variant_failures(db, student_id, subject, knowledge)
        start_level = transfer_engine.DEFAULT_ENGINE.suggest_level(
            mastery_score=mastery, deep_level=_int(deep.get("level"), 0), variant_failures=failures
        )
        plan = variant_ladder.DEFAULT_ENGINE.plan(
            level=start_level,
            minutes=minutes or variant_ladder.ROUND_MINUTES,
            mastery_score=mastery,
            deep_level=_int(deep.get("level"), 0),
            variant_failures=failures,
        )
        first = None
        try:
            first = transfer_engine.DEFAULT_ENGINE.make_question(
                subject,
                knowledge,
                plan.get("start_level", start_level),
                grade=_int(grade, 0) or self._grade_of(db, student_id) or 3,
                base=base,
                use_ai=use_ai,
            )
        except Exception:
            first = None
        plan.update(
            {
                "student_id": student_id,
                "subject": subject,
                "knowledge": knowledge,
                "mastery_score": mastery,
                "deep_level": _int(deep.get("level"), 0),
                "question": first,
                "levels": transfer_engine.levels(),
            }
        )
        return plan

    def _variant_failures(self, db, student_id, subject, knowledge, limit=6):
        rows = (
            db.query(TransferAttempt)
            .filter(
                TransferAttempt.student_id == student_id,
                TransferAttempt.subject == subject,
                TransferAttempt.knowledge_id == knowledge,
            )
            .order_by(TransferAttempt.id.desc())
            .limit(max(1, _int(limit, 6)))
            .all()
        )
        return sum(1 for row in rows if not row.correct)

    def record_transfer(self, db, student_id, subject, knowledge, *, level=0, correct=False,
                        question_id=0, hint_used=0, response_time=0, source="local",
                        child_message="", confidence="", commit=True):
        """记录一次迁移作答（需求 §三十八 transfer_attempt）。"""
        level = transfer_engine.clamp_level(level)
        judgment = transfer_engine.DEFAULT_ENGINE.judge(
            level, correct, hint_used, response_time, confidence
        )
        row = TransferAttempt(
            student_id=student_id,
            subject=subject,
            knowledge_id=knowledge,
            transfer_level=level,
            question_id=_int(question_id, 0),
            correct=bool(correct),
            hint_used=_int(hint_used, 0),
            response_time=_float(response_time, 0.0),
            source=_text(source, "local"),
            child_message=_text(child_message),
            created_at=_now(),
        )
        db.add(row)
        db.flush()
        evidence = self.record_evidence(
            db,
            student_id,
            subject,
            knowledge,
            evidence_type="TRANSFER",
            result="correct" if correct else "wrong",
            question_id=question_id,
            hint_level=hint_used,
            confidence=confidence,
            response_time=response_time,
            source="transfer",
            detail="T%d" % level,
            commit=False,
        )
        if commit:
            db.commit()
        return {
            "id": row.id,
            "transfer_level": level,
            "level_info": transfer_engine.level_dict(level),
            "correct": bool(correct),
            "judgment": judgment,
            "next_action": transfer_engine.DEFAULT_ENGINE.gap_action(
                level, correct, self._mastery_of(db, student_id, subject, knowledge)
            ),
            "evidence": evidence,
        }

    def transfer_history(self, db, student_id, subject=None, knowledge=None, limit=10):
        query = db.query(TransferAttempt).filter(TransferAttempt.student_id == student_id)
        if subject:
            query = query.filter(TransferAttempt.subject == subject)
        if knowledge:
            query = query.filter(TransferAttempt.knowledge_id == knowledge)
        rows = query.order_by(TransferAttempt.id.desc()).limit(max(1, _int(limit, 10))).all()
        return [
            {
                "id": row.id,
                "subject": row.subject,
                "knowledge": row.knowledge_id,
                "transfer_level": _int(row.transfer_level, 0),
                "level_info": transfer_engine.level_dict(_int(row.transfer_level, 0)),
                "correct": bool(row.correct),
                "hint_used": _int(row.hint_used, 0),
                "source": row.source,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 解释（讲给菲比听）
    # ------------------------------------------------------------------

    def explain_should_ask(self, db, student_id, subject, knowledge, transfer_failed=False):
        """是否值得要求解释（需求 §二十五：不是每道题都问）。"""
        mastery = (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.subject == subject,
                StudentKnowledgeMastery.knowledge_id == knowledge,
            )
            .first()
        )
        wrong_count = _int(getattr(mastery, "wrong_questions", 0))
        deep = self.detail(db, student_id, subject, knowledge)
        asked = (
            db.query(ExplanationAttempt)
            .filter(
                ExplanationAttempt.student_id == student_id,
                ExplanationAttempt.subject == subject,
                ExplanationAttempt.knowledge_id == knowledge,
            )
            .count()
        )
        result = explanation_engine.DEFAULT_ENGINE.should_ask(
            knowledge,
            wrong_count=wrong_count,
            transfer_failed=transfer_failed,
            deep_level=_int(deep.get("level"), 0),
            hint_dependency=_float(deep.get("hint_dependency"), 0.0),
            recent_explanations=asked,
        )
        result.update({"student_id": student_id, "subject": subject, "knowledge": knowledge,
                       "asked_before": asked})
        return result

    def explain_prompt(self, subject, knowledge, question=""):
        return explanation_engine.DEFAULT_ENGINE.prompt_for(**{"knowledge": knowledge,
                                                               "question": question,
                                                               "subject": subject})

    def evaluate_explanation(self, subject="", grade=3, knowledge="", question="",
                             expected_concepts=None, student_explanation="",
                             transfer_failed=False, use_ai=True):
        """规则评价（+ 可选 AI 辅助合并），AI 只补充不覆盖（需求 §二十四 / §三十六）。"""
        rule = explanation_engine.DEFAULT_ENGINE.evaluate(
            subject=subject,
            grade=grade,
            knowledge=knowledge,
            question=question,
            expected_concepts=expected_concepts,
            student_explanation=student_explanation,
            transfer_failed=transfer_failed,
        )
        if not use_ai:
            return rule
        try:
            ai = explanation_engine.DEFAULT_ENGINE.ai_evaluate(
                subject=subject,
                grade=grade,
                knowledge=knowledge,
                question=question,
                expected_concepts=expected_concepts,
                student_explanation=student_explanation,
            )
        except Exception:
            ai = None
        if not ai:
            return rule
        try:
            return explanation_engine.DEFAULT_ENGINE.merge_ai(rule, ai)
        except Exception:
            return rule

    def record_explanation(self, db, student_id, subject, knowledge, *, question="",
                           student_response="", evaluation=None, grade=3,
                           expected_concepts=None, transfer_failed=False, use_ai=True,
                           commit=True):
        """记录一次解释尝试并生成 EXPLANATION 证据（需求 §二十三 / §三十八）。"""
        if evaluation is None:
            evaluation = self.evaluate_explanation(
                subject=subject,
                grade=grade,
                knowledge=knowledge,
                question=question,
                expected_concepts=expected_concepts,
                student_explanation=student_response,
                transfer_failed=transfer_failed,
                use_ai=use_ai,
            )
        coverage = _float(evaluation.get("concept_coverage"), 0.0)
        correct = bool(evaluation.get("core_concept_correct"))
        if correct:
            result = "correct"
        elif coverage >= 0.4:
            result = "partial"
        else:
            result = "wrong"
        row = ExplanationAttempt(
            student_id=student_id,
            subject=subject,
            knowledge_id=knowledge,
            question=_text(question),
            student_response=_text(student_response),
            concept_coverage=coverage,
            quality_score=_int(evaluation.get("quality_score"), 0),
            core_concept_correct=correct,
            missing_concepts=_json(evaluation.get("missing_concepts") or []),
            possible_misconceptions=_json(evaluation.get("possible_misconceptions") or []),
            feedback=_text(evaluation.get("feedback") or evaluation.get("child_feedback")),
            source=_text(evaluation.get("source"), "rule"),
            created_at=_now(),
        )
        db.add(row)
        db.flush()
        evidence = self.record_evidence(
            db,
            student_id,
            subject,
            knowledge,
            evidence_type="EXPLANATION",
            result=result,
            source="explain",
            detail="coverage=%.2f" % coverage,
            commit=False,
        )
        if commit:
            db.commit()
        return {
            "id": row.id,
            "evaluation": evaluation,
            "result": result,
            "core_concept_correct": correct,
            "concept_coverage": coverage,
            "quality_score": row.quality_score,
            "child_feedback": explanation_engine.DEFAULT_ENGINE.child_feedback(
                {"core_concept_correct": correct, "concept_coverage": coverage}
            ),
            "evidence": evidence,
        }

    def explanation_history(self, db, student_id, subject=None, knowledge=None, limit=10):
        query = db.query(ExplanationAttempt).filter(ExplanationAttempt.student_id == student_id)
        if subject:
            query = query.filter(ExplanationAttempt.subject == subject)
        if knowledge:
            query = query.filter(ExplanationAttempt.knowledge_id == knowledge)
        rows = query.order_by(ExplanationAttempt.id.desc()).limit(max(1, _int(limit, 10))).all()
        return [
            {
                "id": row.id,
                "subject": row.subject,
                "knowledge": row.knowledge_id,
                "concept_coverage": _float(row.concept_coverage, 0.0),
                "quality_score": _int(row.quality_score, 0),
                "core_concept_correct": bool(row.core_concept_correct),
                "feedback": row.feedback,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 自信度 / 猜测 / 误解
    # ------------------------------------------------------------------

    def confidence_options(self):
        """儿童端自信度选项（只有图标与文案，没有数字，需求 §十九）。"""
        return [dict(item) for item in confidence_engine.CONFIDENCE_OPTIONS]

    def confidence_should_ask(self, scene="", difficulty=50, hint_level=0, correct=None,
                              response_time=0, mastery_score=None):
        return confidence_engine.DEFAULT_ENGINE.should_ask(
            scene, difficulty, hint_level, correct, response_time, mastery_score
        )

    def confidence_plan(self, correct=None, confidence_key="", mastery_score=None,
                        response_time=0, expected=None):
        """正确性 × 自信度矩阵 + 猜测验证计划（需求 §二十 / §二十一）。"""
        kwargs = {
            "correct": correct,
            "confidence_key": confidence_key,
            "mastery_score": mastery_score,
            "response_time": response_time,
        }
        if expected:
            kwargs["expected"] = expected
        matrix = confidence_engine.DEFAULT_ENGINE.matrix(correct, confidence_key)
        plan = confidence_engine.DEFAULT_ENGINE.verify_plan(**kwargs)
        return {"matrix": matrix, "verify": plan, "confidence_key": confidence_key}

    def guess_check(self, db, student_id, subject, knowledge, *, correct=False,
                    confidence_key="", response_time=0, expected=None):
        """猜对检测（需求 §二十一）：猜对不大幅加掌握度，安排一题快速验证。"""
        mastery = self._mastery_of(db, student_id, subject, knowledge)
        plan = self.confidence_plan(
            correct=correct,
            confidence_key=confidence_key,
            mastery_score=mastery,
            response_time=response_time,
            expected=expected,
        )
        return plan

    def misconception(self, db, student_id, subject, knowledge, window=None):
        """疑似概念性误解检测（需求 §二十二）。"""
        window = max(2, _int(window, misconception_engine.DETECT_WINDOW))
        evidence = self.evidence_rows(
            db, student_id, subject, knowledge, desc=True, limit=window
        )
        wrongs = [row for row in evidence if not row.correct]
        causes = (
            db.query(RootCauseRecord)
            .filter(
                RootCauseRecord.student_id == student_id,
                RootCauseRecord.subject == subject,
                RootCauseRecord.knowledge_id == knowledge,
            )
            .order_by(RootCauseRecord.id.desc())
            .limit(window)
            .all()
        )
        cause_by_question = {}
        cause_flat = []
        for row in causes:
            cause_flat.append(
                {
                    "root_cause_type": row.root_cause_type,
                    "correct": False,
                    "confidence": "",
                    "created_at": row.created_at,
                }
            )
            if row.question_id:
                cause_by_question[_int(row.question_id, 0)] = row.root_cause_type
        records = [
            {
                "root_cause_type": cause_by_question.get(_int(row.question_id, 0), ""),
                "correct": bool(row.correct),
                "confidence": _text(row.confidence),
                "created_at": row.created_at,
            }
            for row in wrongs
        ]
        result = misconception_engine.DEFAULT_ENGINE.detect(records or cause_flat, window=window)
        if not result.get("possible_misconception") and cause_flat:
            result = misconception_engine.DEFAULT_ENGINE.detect(cause_flat, window=window)
        if result.get("possible_misconception"):
            row = self.state_row(db, student_id, subject, knowledge, create=False)
            if row is not None and not row.misconception_flag:
                row.misconception_flag = True
                db.flush()
            result["remediation"] = misconception_engine.DEFAULT_ENGINE.remediation(
                knowledge, result.get("root_cause_type", "")
            )
        result.update({"student_id": student_id, "subject": subject, "knowledge": knowledge})
        return result

    # ------------------------------------------------------------------
    # 学习效率
    # ------------------------------------------------------------------

    def _minutes_of(self, db, student_id, days=7):
        try:
            start = (_now() - datetime.timedelta(days=max(1, _int(days, 7)))).date().isoformat()
            rows = (
                db.query(DailyLearningTask.duration_minutes)
                .filter(
                    DailyLearningTask.student_id == student_id,
                    DailyLearningTask.date >= start,
                )
                .all()
            )
            return sum(_int(value, 0) for (value,) in rows)
        except Exception:
            return 0

    def efficiency(self, db, student_id, days=7):
        """学习效率（需求 §二十八 / §二十九）：真实收益，不用做题速度。"""
        days = max(1, _int(days, 7))
        start = _now() - datetime.timedelta(days=days)
        window = self.evidence_rows(db, student_id, since=start)
        touched = []
        seen = set()
        for row in window:
            key = (row.subject, row.knowledge_id)
            if key not in seen:
                seen.add(key)
                touched.append(key)

        model = deep_mastery.DEFAULT_MODEL
        minutes = self._minutes_of(db, student_id, days)
        if minutes <= 0:
            minutes = len(window)
        share = int(round(float(minutes) / len(touched))) if touched else 0

        rows = []
        for subject, knowledge in touched:
            all_rows = self.evidence_rows(db, student_id, subject, knowledge)
            past = [row for row in all_rows if row.created_at is not None and row.created_at < start]
            window_rows = [
                row for row in all_rows if row.created_at is not None and row.created_at >= start
            ]
            state_now = model.replay(self._items_of(all_rows))
            state_past = model.replay(self._items_of(past))
            deep_gain = max(0.0, float(model.score_of(state_now) - model.score_of(state_past)))

            mastery_gain = 0.0
            if past:
                baseline = 100.0 * (
                    sum(evidence_module.result_value(row.result) for row in past) / len(past)
                )
                mastery_gain = max(0.0, self._mastery_of(db, student_id, subject, knowledge) - baseline)

            memory_rows = [
                row
                for row in window_rows
                if evidence_module.normalize_type(row.evidence_type)
                in ("RECALL", "DELAYED_REVIEW", "RECOVERY")
            ]
            memory_gain = (
                100.0 * (sum(_float(row.weight) for row in memory_rows) / len(memory_rows))
                if memory_rows
                else 0.0
            )
            recovery_rows = [
                row
                for row in window_rows
                if evidence_module.normalize_type(row.evidence_type) == "RECOVERY"
            ]
            recovery_gain = (
                100.0 * (sum(1 for row in recovery_rows if row.correct) / len(recovery_rows))
                if recovery_rows
                else 0.0
            )
            hint_avg = (
                sum(_int(row.hint_level, 0) for row in window_rows) / len(window_rows)
                if window_rows
                else 0
            )
            counts = self._counts_of_rows(all_rows)
            level = model.level_of(state_now, counts, len(all_rows))
            rows.append(
                {
                    "subject": subject,
                    "knowledge": knowledge,
                    "minutes": share,
                    "mastery_gain": mastery_gain,
                    "deep_mastery_gain": deep_gain,
                    "memory_gain": memory_gain,
                    "recovery_gain": recovery_gain,
                    "hint_level": hint_avg,
                    "correct": window_rows[-1].correct if window_rows else None,
                    "learned": 1 if level >= 3 else 0,
                    "level": level,
                }
            )

        result = learning_efficiency.DEFAULT_ENGINE.aggregate(rows, days=days)
        result.update(
            {
                "student_id": student_id,
                "days": days,
                "touched": len(touched),
                "details": rows,
            }
        )
        return result

    # ------------------------------------------------------------------
    # 每日计划整合（需求 §三十 / §三十一）
    # ------------------------------------------------------------------

    def focus_knowledge(self, db, student_id, subject=None):
        """挑一个今天最该练的知识点（练过但最薄弱者优先）。"""
        query = db.query(StudentKnowledgeMastery).filter(
            StudentKnowledgeMastery.student_id == student_id,
            StudentKnowledgeMastery.total_questions > 0,
        )
        if subject:
            query = query.filter(StudentKnowledgeMastery.subject == subject)
        rows = query.all()
        if not rows:
            return None
        rows.sort(key=lambda row: (_int(row.mastery_score, 0), -_int(row.total_questions, 0)))
        row = rows[0]
        return {
            "subject": row.subject,
            "knowledge": row.knowledge_id,
            "mastery_score": _int(row.mastery_score, 0),
        }

    def plan_hint(self, db, student_id, subject=None, minutes=None):
        """每日计划的深度学习增量建议（**最多 2 个**，且在时长预算内，需求 §三十 / §三十一）。"""
        budget = _int(minutes, 0)
        if budget <= 0:
            budget = 15
        hard_limit = int(budget * PLAN_TIME_BUDGET_RATIO)
        hint = {
            "student_id": student_id,
            "subject": subject,
            "minutes": budget,
            "extra_minutes": 0,
            "tasks": [],
            "reasons": [],
            "focus": None,
            "note": "深度学习任务不扩张今日总时长：只在原预算内重新分配（需求 §三十一）",
        }
        focus = self.focus_knowledge(db, student_id, subject)
        if not focus:
            return hint
        hint["focus"] = focus
        candidates = []

        repair = self.minimal_repair(db, student_id, focus["subject"], focus["knowledge"])
        if repair:
            candidates.append(
                (
                    "PREREQUISITE_REPAIR",
                    "前置知识「%s」有点松，先花 5 分钟补一补再回来"
                    % _text(repair.get("insert_knowledge")),
                    repair,
                )
            )

        deep = self.detail(db, student_id, focus["subject"], focus["knowledge"])
        level = _int(deep.get("level"), 0)
        if level <= 2:
            candidates.append(
                ("ACTIVE_RECALL", "先自己回忆一遍「%s」，回忆过再做题更牢" % focus["knowledge"], None)
            )
        elif level == 3:
            candidates.append(
                ("TRANSFER", "「%s」标准题会做了，试试换一种问法" % focus["knowledge"], None)
            )
        elif level == 4:
            candidates.append(
                ("EXPLAIN", "「%s」已经会用了，讲给菲比听一次" % focus["knowledge"], None)
            )

        for task_type, reason, payload in candidates:
            if len(hint["tasks"]) >= PLAN_MAX_EXTRA_TASKS:
                break
            cost = PLAN_TASK_MINUTES.get(task_type, 3)
            if hint["extra_minutes"] + cost > hard_limit:
                continue
            hint["extra_minutes"] += cost
            hint["tasks"].append(
                {"task_type": task_type, "minutes": cost, "reason": reason, "payload": payload}
            )
            hint["reasons"].append(reason)
        return hint

    # ------------------------------------------------------------------
    # 内部小工具
    # ------------------------------------------------------------------

    def _mastery_of(self, db, student_id, subject, knowledge):
        row = (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.subject == subject,
                StudentKnowledgeMastery.knowledge_id == knowledge,
            )
            .first()
        )
        return _int(getattr(row, "mastery_score", 0))

    def _grade_of(self, db, student_id):
        try:
            from models import Student

            row = db.query(Student).filter(Student.id == student_id).first()
            return _int(getattr(row, "grade", 0), 0)
        except Exception:
            return 0



DEFAULT_ENGINE = DeepMasteryEngine()


# ----------------------------------------------------------------------
# 模块级薄封装（接口层统一从这里调用，保证「唯一碰库门面」）
# ----------------------------------------------------------------------


def record_evidence(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.record_evidence(db, student_id, subject, knowledge, **kwargs)


def refresh(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.refresh(db, student_id, subject, knowledge, **kwargs)


def detail(db, student_id, subject, knowledge):
    return DEFAULT_ENGINE.detail(db, student_id, subject, knowledge)


def status(db, student_id, subject, knowledge):
    return DEFAULT_ENGINE.status(db, student_id, subject, knowledge)


def summary(db, student_id, subject=None):
    return DEFAULT_ENGINE.summary(db, student_id, subject)


def map_levels(db, student_id, subject=None):
    return DEFAULT_ENGINE.map_levels(db, student_id, subject)


def growth(db, student_id, days=7):
    return DEFAULT_ENGINE.growth(db, student_id, days)


def efficiency(db, student_id, days=7):
    return DEFAULT_ENGINE.efficiency(db, student_id, days)


def plan_hint(db, student_id, subject=None, minutes=None):
    return DEFAULT_ENGINE.plan_hint(db, student_id, subject, minutes)


def focus_knowledge(db, student_id, subject=None):
    return DEFAULT_ENGINE.focus_knowledge(db, student_id, subject)


def analyze_root_cause(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.analyze_root_cause(db, student_id, subject, knowledge, **kwargs)


def root_cause_detail(db, student_id, knowledge=None, subject=None, limit=5):
    return DEFAULT_ENGINE.root_cause_detail(db, student_id, knowledge, subject, limit)


def record_root_cause(db, student_id, subject, knowledge, payload, **kwargs):
    return DEFAULT_ENGINE.record_root_cause(db, student_id, subject, knowledge, payload, **kwargs)


def record_transfer(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.record_transfer(db, student_id, subject, knowledge, **kwargs)


def transfer_plan(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.transfer_plan(db, student_id, subject, knowledge, **kwargs)


def record_explanation(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.record_explanation(db, student_id, subject, knowledge, **kwargs)


def explain_should_ask(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.explain_should_ask(db, student_id, subject, knowledge, **kwargs)


def explain_prompt(subject, knowledge, question=""):
    return DEFAULT_ENGINE.explain_prompt(subject, knowledge, question)


def misconception(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.misconception(db, student_id, subject, knowledge, **kwargs)


def confidence_options():
    return DEFAULT_ENGINE.confidence_options()


def confidence_plan(**kwargs):
    return DEFAULT_ENGINE.confidence_plan(**kwargs)


def guess_check(db, student_id, subject, knowledge, **kwargs):
    return DEFAULT_ENGINE.guess_check(db, student_id, subject, knowledge, **kwargs)


def evidence_rows(db, student_id, **kwargs):
    return DEFAULT_ENGINE.evidence_rows(db, student_id, **kwargs)


def ensure_states(db, student_id=None, **kwargs):
    return DEFAULT_ENGINE.ensure_states(db, student_id, **kwargs)
