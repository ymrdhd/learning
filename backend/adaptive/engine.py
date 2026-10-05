# ==============================================================
# 能力契约｜自适应门面：组装画像 → 决策 → 计划 → 推荐 → 会话 → 日志（唯一碰数据库的自适应模块）
# 入口：AdaptiveLearningEngine（ability_of/profile/profiles/difficulty_state/decision_for/next_spec/plan/recommend/start/feedback/log/strategy_logs/feedback_history）/ DEFAULT_ENGINE
# 依赖：adaptive 各纯函数模块、knowledge_routes._mastery_items、mastery、error_analysis、stages、knowledge_tree、models
# 不负责：算法细节 → adaptive/strategy|difficulty|selector|planner；出题 → main.question
# 验证：python backend/verify_adaptive.py
# 被调用：adaptive_routes.py、review/engine.py（RELEARN 回流）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎 · AdaptiveLearningEngine。

把 V2.1 的能力诊断、V2.2 的知识掌握模型与错因分析、V2.3 的学习策略
串成一个闭环：

```text
学生
 ↓
能力模型   （AbilityProfile + MasteryEngine + 错因分析）
 ↓
学习策略   （LearningStrategy：学什么、为什么）
 ↓
难度决策   （DifficultyController：出多难）
 ↓
任务生成   （DailyLearningPlanner + QuestionSelector：今天做什么、下一题是什么）
 ↓
答题
 ↓
更新能力   （/submit 重算掌握度与能力分）
 ↓
下一轮调整 （feedback + recommend 再决策）
```

这一层只做两件事：**从数据库组装画像**、**把决策落库**。
算法本身都在 strategy / difficulty / selector / planner 四个纯函数模块里，
方便单测，也方便以后换成别的算法而不动 API。
"""

from datetime import datetime, timedelta

import error_analysis
import knowledge_tree
import mastery
import stages
from adaptive import difficulty, planner, selector, strategy
import review.engine as review_engine_module
from models import (
    Ability,
    AbilityProfile,
    AnswerErrorAnalysis,
    AnswerRecord,
    LearningFeedback,
    LearningPlan,
    LearningStrategyLog,
    Question,
    Student,
)
# 复用知识掌握视图：知识点树 + 掌握度合并好的 24 项明细
from knowledge_routes import _mastery_items

# 主观感受的生效时间窗：孩子刚反馈的"太难"才影响下一题，
# 避免几天前的一次"有点难"反复拉低难度
FEEL_WINDOW_HOURS = 2
DEFAULT_QUESTION_TYPE = "choice"


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
    return None


def _fmt(moment):
    return moment.strftime("%Y-%m-%d %H:%M") if moment else ""


class AdaptiveLearningEngine:
    """自适应学习引擎门面：画像 → 决策 → 任务 → 反馈 → 再决策。"""

    # ---------------- 画像 ----------------

    def ability_of(self, db, student_id, subject):
        """能力阶段与能力分：优先用 V2.1 诊断画像，没有就退回日常练习模型。"""
        row = db.query(AbilityProfile).filter(
            AbilityProfile.student_id == student_id,
            AbilityProfile.subject == subject,
        ).first()

        if row is not None and stages.is_valid(row.ability_stage):
            return {
                "stage": row.ability_stage,
                "label": stages.label(row.ability_stage),
                "score": float(row.ability_score or 50),
                "confidence": float(row.confidence or 0),
                "source": row.source or "diagnostic",
            }

        fallback = db.query(Ability).filter(
            Ability.student_id == student_id,
            Ability.subject == subject,
        ).first()

        if fallback is None:
            return {}

        score = float(fallback.score or 50)
        key = stages.key_of_difficulty(score)
        return {
            "stage": key,
            "label": stages.label(key),
            "score": score,
            "confidence": mastery.DEFAULT_ENGINE.confidence_of(fallback.total_count or 0),
            "source": "practice",
        }

    def error_counts(self, db, student_id, subject):
        """知识点 → 错因记录条数（错误频率的证据）。"""
        rows = db.query(AnswerErrorAnalysis).filter(
            AnswerErrorAnalysis.student_id == student_id,
            AnswerErrorAnalysis.subject == subject,
        ).all()

        counts = {}
        for row in rows:
            if not row.knowledge_id:
                continue
            counts[row.knowledge_id] = counts.get(row.knowledge_id, 0) + 1
        return counts

    def recent_records(self, db, student_id, subject=None, knowledge=None, limit=20):
        """最近答题记录（从旧到新），供难度控制器使用。"""
        query = db.query(AnswerRecord).filter(AnswerRecord.student_id == student_id)
        if subject:
            query = query.filter(AnswerRecord.subject == subject)
        if knowledge:
            query = query.filter(AnswerRecord.knowledge == knowledge)

        rows = query.order_by(AnswerRecord.id.desc()).limit(max(1, int(limit))).all()

        return [
            {"correct": bool(row.correct),
             "difficulty": int(row.difficulty or 50),
             "knowledge": row.knowledge,
             "time": row.created_at}
            for row in reversed(rows)
        ]

    def recent_knowledge(self, db, student_id, subject, limit=3):
        """最近几题练过的知识点（出下一题时回避重复）。"""
        return [item["knowledge"] for item in
                self.recent_records(db, student_id, subject, limit=limit)]

    def last_feel(self, db, student_id, subject, now=None):
        """最近一次主观难度感受（只认时间窗内的）。"""
        now = now or datetime.now()
        row = db.query(LearningFeedback).filter(
            LearningFeedback.student_id == student_id,
            LearningFeedback.subject == subject,
        ).order_by(LearningFeedback.id.desc()).first()

        if row is None or not row.feel:
            return ""
        created = row.created_time or now
        if now - created > timedelta(hours=FEEL_WINDOW_HOURS):
            return ""
        return row.feel

    def memory_rows(self, db, student_id, subject=None):
        """V2.4 记忆状态（按 科目+知识点 索引），用于把遗忘风险并进画像。"""
        from models import KnowledgeMemoryState

        query = db.query(KnowledgeMemoryState).filter(
            KnowledgeMemoryState.student_id == student_id)
        if subject:
            query = query.filter(KnowledgeMemoryState.subject == subject)

        return {(row.subject, row.knowledge_id): row for row in query.all()}

    def profile(self, db, student_id, subject):
        """组装一个科目的完整学习画像。"""
        items = _mastery_items(db, student_id, subject)
        memory_map = self.memory_rows(db, student_id, subject)

        for item in items:
            item["last_practice_time"] = _parse_dt(item.get("last_practice_time"))
            item["next_review_time"] = _parse_dt(item.get("next_review_time"))

            # V2.4：把真实的记忆状态并进画像，学习策略就能用"遗忘风险"做判断
            memory_row = memory_map.get((subject, item.get("knowledge_id")))
            if memory_row is not None:
                item["forgetting_risk"] = float(memory_row.forgetting_risk or 0)
                item["memory_stability"] = float(memory_row.stability or 0)
                item["maturity_level"] = memory_row.maturity_level or ""
                item["needs_relearn"] = bool(memory_row.needs_relearn)
                item["next_review_memory_at"] = memory_row.next_review_at

        practiced = [item for item in items if int(item.get("total_questions") or 0) > 0]
        average = mastery.aggregate(practiced) if practiced else 0
        student = db.query(Student).filter(Student.id == student_id).first()

        return {
            "student_id": student_id,
            "student_name": student.name if student else f"小朋友{student_id}",
            "grade": student.grade if student else 1,
            "subject": subject,
            "ability": self.ability_of(db, student_id, subject),
            "knowledge": items,
            "error_counts": self.error_counts(db, student_id, subject),
            "recent": self.recent_records(db, student_id, subject, limit=20),
            "summary": {
                "knowledge_count": len(items),
                "practiced": len(practiced),
                "weak": sum(1 for item in practiced
                            if int(item.get("mastery_score") or 0) < strategy.WEAK_LINE),
                "average_mastery": average,
                "stars": stages.stars(average),
                "star_text": stages.star_text(average),
            },
            "now": datetime.now(),
        }

    def profiles(self, db, student_id, subjects=None):
        """多个科目的画像（默认三科）。"""
        return [self.profile(db, student_id, name)
                for name in (subjects or stages.SUBJECTS)]

    # ---------------- 难度决策 ----------------

    def difficulty_state(self, db, student_id, subject, knowledge, profile=None,
                         feel=None):
        """当前该用什么难度：能力分与知识点难度混合 → 难度控制器调整。"""
        profile = profile or self.profile(db, student_id, subject)
        ability = profile.get("ability") or {}
        ability_score = float(ability.get("score") or 50)
        knowledge_difficulty = knowledge_tree.difficulty_of(subject, knowledge)

        base = 0.5 * ability_score + 0.5 * float(knowledge_difficulty)
        if feel is None:
            feel = self.last_feel(db, student_id, subject)

        state = difficulty.DEFAULT_CONTROLLER.adjust(
            base,
            self.recent_records(db, student_id, subject, limit=20),
            feel=feel,
        )
        state["knowledge"] = knowledge
        state["knowledge_difficulty"] = knowledge_difficulty
        state["ability_score"] = round(ability_score, 1)
        state["ability_stage"] = ability.get("stage") or ""
        state["ability_label"] = ability.get("label") or ""
        return state

    # ---------------- 学习决策 ----------------

    def decision_for(self, db, student_id, subject, knowledge=None, profile=None):
        """这一科下一步学什么（含难度与理由）。"""
        profile = profile or self.profile(db, student_id, subject)
        ranked = strategy.DEFAULT_STRATEGY.rank(profile)

        if not ranked:
            return strategy.DEFAULT_STRATEGY.choose(profile)

        top = ranked[0]
        if knowledge:
            top = next((entry for entry in ranked if entry["knowledge"] == knowledge), top)

        state = self.difficulty_state(db, student_id, subject, top["knowledge"],
                                      profile=profile)
        decision = strategy.DEFAULT_STRATEGY.choose(
            profile, difficulty_hint=state["difficulty"], knowledge=knowledge or None)
        decision["difficulty_state"] = state
        decision["student_id"] = student_id
        decision["student_name"] = profile.get("student_name")
        return decision

    def next_spec(self, db, student_id, subject, knowledge=None, rng=None,
                  avoid_knowledge=()):
        """下一题的出题规格：知识点 + 难度 + 题源类型（不真正出题）。

        knowledge：前端/计划指定的知识点。
        avoid_knowledge：最近刚练过的知识点（通常就是这几道题），这些知识点不锁定，
            交给选择器在其它候选里挑，避免同一种题连着出。
        """
        decision = self.decision_for(db, student_id, subject, knowledge=knowledge)
        picked = selector.DEFAULT_SELECTOR.select_from_decision(
            decision, rng=rng,
            recent_knowledge=self.recent_knowledge(db, student_id, subject, limit=5))

        # 明确指定知识点时不再让选择器改知识点；但这个知识点刚练过就不锁定
        avoided = {str(item).strip() for item in (avoid_knowledge or ()) if str(item).strip()}
        if knowledge and str(knowledge).strip() not in avoided:
            picked["knowledge"] = knowledge
            picked["avoided"] = False
        elif knowledge:
            picked["avoided"] = True          # 刚练过 → 已换成别的知识点
            picked["avoided_knowledge"] = str(knowledge).strip()

        picked.update({
            "student_id": student_id,
            "subject": subject,
            "difficulty_state": decision.get("difficulty_state") or {},
            "decision": {
                "action": decision.get("action"),
                "reason": decision.get("reason"),
                "priority_score": decision.get("priority_score"),
                "tier": decision.get("tier"),
                "evidence": decision.get("evidence"),
                "candidates": decision.get("candidates"),
                "dependency_chain": decision.get("dependency_chain"),
            },
        })
        return picked

    # ---------------- 今日计划 / 推荐 ----------------

    def plan(self, db, student_id, plan_date=None, refresh=False, profiles=None,
             review_items=None, relearn_items=None, total_minutes=None):
        """确认并返回今日计划（幂等）。

        V2.4：计划里会插入 `ReviewScheduler` 排出来的间隔复习任务，
        并按 `calculate_daily_mix()` 的新学 / 补强 / 复习比例分配题量。
        """
        from review import engine as review_engine_module

        review_engine = review_engine_module.DEFAULT_ENGINE

        if review_items is None or relearn_items is None:
            review_today = review_engine.today(db, student_id, refresh=refresh)
            review_items = review_today["items"] if review_items is None else review_items
            relearn_items = review_today["relearn"] if relearn_items is None else relearn_items

        if profiles is None:
            profiles = []
            for name in stages.SUBJECTS:
                profile = self.profile(db, student_id, name)
                profile["decision"] = self.decision_for(db, student_id, name,
                                                        profile=profile)
                profiles.append(profile)

        if refresh:
            day = planner.date_text(plan_date)
            rows = db.query(LearningPlan).filter(
                LearningPlan.student_id == student_id,
                LearningPlan.date == day,
                LearningPlan.status != planner.STATUS_DONE,
            ).all()
            for row in rows:
                row.status = planner.STATUS_EXPIRED
            db.commit()

        return planner.DEFAULT_PLANNER.ensure(db, student_id, profiles=profiles,
                                              plan_date=plan_date,
                                              total_minutes=total_minutes,
                                              review_items=review_items,
                                              relearn_items=relearn_items)

    def recommend(self, db, student_id, subject=None, log=True):
        """今日推荐：学哪一科、学什么知识点、什么难度、为什么。"""
        subject = str(subject or "").strip() or None
        if subject and subject not in stages.SUBJECTS:
            subject = None

        subjects = [subject] if subject else list(stages.SUBJECTS)

        profiles = []
        decisions = []
        for name in subjects:
            profile = self.profile(db, student_id, name)
            decision = self.decision_for(db, student_id, name, profile=profile)
            profile["decision"] = decision
            profiles.append(profile)
            decisions.append(decision)

        primary = max(decisions, key=lambda item: (
            item.get("priority_score") or 0,
            1 if item.get("action") != "diagnostic" else 0,
        )) if decisions else {}

        # V2.4：先看有没有到期复习任务 —— 有就先复习，再学新内容
        review_engine = review_engine_module.DEFAULT_ENGINE
        review_today = review_engine.today(db, student_id)
        review_action = self._review_action(review_today, subject)
        if review_action is not None and primary is not None:
            primary = dict(primary)
            primary.update({
                "action": "review",
                "action_text": "间隔复习",
                "subject": review_action["subject"],
                "knowledge": review_action["knowledge"],
                "difficulty": review_action["difficulty"],
                "reason": review_action["reason"],
                "priority_score": 1.0,
            })

        plan = self.plan(db, student_id, profiles=profiles,
                         review_items=review_today["items"],
                         relearn_items=review_today["relearn"])
        mix_result = review_engine.mix_for(db, student_id)
        log_id = self.log(db, student_id, primary, source="recommend") if log else None

        student = db.query(Student).filter(Student.id == student_id).first()

        return {
            "student_id": student_id,
            "student": {
                "id": student_id,
                "name": student.name if student else f"小朋友{student_id}",
                "grade": student.grade if student else 1,
            },
            "date": plan["date"],
            "subject": subject or "",
            "primary": primary,
            "next_action": {
                "action": primary.get("action"),
                "action_text": primary.get("action_text"),
                "subject": primary.get("subject"),
                "knowledge": primary.get("knowledge"),
                "difficulty": primary.get("difficulty"),
                "reason": primary.get("reason"),
            },
            "subjects": [
                {
                    "subject": profile["subject"],
                    "ability": profile.get("ability") or {},
                    "summary": profile.get("summary") or {},
                    "decision": decision,
                    "difficulty_state": decision.get("difficulty_state") or {},
                }
                for profile, decision in zip(profiles, decisions)
            ],
            "plan": plan,
            # V2.4 间隔复习：今天该浇水的知识 + 新学/补强/复习配比
            "review": {
                "date": review_today.get("date"),
                "total": review_today.get("total"),
                "completed": review_today.get("completed"),
                "remaining": review_today.get("remaining"),
                "planned_questions": review_today.get("planned_questions"),
                "child_title": review_today.get("child_title"),
                "child_message": review_today.get("child_message"),
                "by_priority": review_today.get("by_priority"),
                "relearn": review_today.get("relearn"),
                "items": review_today.get("items", [])[:10],
            },
            "review_first": bool(review_action),
            "daily_mix": mix_result,
            "strategy_log_id": log_id,
            "message": self._message_of(primary, plan),
            "generated_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    @staticmethod
    def _review_action(review_today, subject=None):
        """今天有 P0（已经到期）的复习任务时，优先返回复习动作。"""
        items = [item for item in (review_today or {}).get("items") or []
                 if item.get("priority") == "P0"]
        if subject:
            items = [item for item in items if str(item.get("subject")) == subject]
        if not items:
            return None

        top = max(items, key=lambda item: float(item.get("forgetting_risk") or 0))
        mastery = int(top.get("mastery_score") or 0)
        return {
            "subject": top.get("subject"),
            "knowledge": top.get("knowledge_id"),
            "difficulty": int(max(20, min(90, mastery + 5))),
            "risk": float(top.get("forgetting_risk") or 0),
            "reason": (f"{top.get('knowledge_id')}已经到期该复习了"
                       f"（遗忘风险 {float(top.get('forgetting_risk') or 0):.0%}）"),
        }

    @staticmethod
    def _message_of(decision, plan):
        if not decision:
            return "今天还没有可安排的内容，先做一次能力诊断吧～"
        knowledge = decision.get("knowledge") or ""
        reason = decision.get("reason") or ""
        remain = 0
        for item in (plan or {}).get("items") or []:
            if item["subject"] == decision.get("subject") and item["knowledge_id"] == knowledge:
                remain = item["remain_count"]
                break
        tail = f"，今天还剩 {remain} 题" if remain else ""
        return f"今天先练「{knowledge}」：{reason}{tail}"

    # ---------------- 开始学习 / 反馈 ----------------

    def start(self, db, student_id, subject, knowledge=None, plan_id=None):
        """开始一次学习任务：锁定知识点与难度，并把计划标成进行中。"""
        spec = self.next_spec(db, student_id, subject, knowledge=knowledge)
        day = planner.date_text()

        # V2.4：没指定知识点、且该科有到期复习任务时，提示"先复习再学新的"
        review_action = None
        if not knowledge:
            review_today = review_engine_module.DEFAULT_ENGINE.today(db, student_id)
            review_action = self._review_action(review_today, subject)

        query = db.query(LearningPlan).filter(
            LearningPlan.student_id == student_id,
            LearningPlan.date == day,
            LearningPlan.subject == subject,
            LearningPlan.status != planner.STATUS_EXPIRED,
        )
        if plan_id:
            query = query.filter(LearningPlan.id == plan_id)

        rows = query.order_by(LearningPlan.priority.asc(), LearningPlan.id.asc()).all()
        target_row = None
        for row in rows:
            if row.knowledge_id == spec["knowledge"]:
                target_row = row
                break
        target_row = target_row or (rows[0] if rows else None)

        if target_row is not None and (target_row.status or "") == planner.STATUS_PENDING:
            target_row.status = planner.STATUS_DOING
            target_row.updated_time = datetime.now()

        db.commit()
        log_id = self.log(db, student_id, dict(spec, action=spec.get("action"),
                                              reason=spec.get("reason")),
                          source="start")

        return {
            "student_id": student_id,
            "subject": subject,
            "knowledge": spec["knowledge"],
            "difficulty": spec["difficulty"],
            "mode": spec.get("mode"),
            "reason": spec.get("reason"),
            "target_count": int(target_row.target_count or 0) if target_row else 0,
            "completed_count": int(target_row.completed_count or 0) if target_row else 0,
            "plan_id": target_row.id if target_row else 0,
            "plan": planner.DEFAULT_PLANNER.summary(db, student_id, day),
            "difficulty_state": spec.get("difficulty_state") or {},
            # V2.4：该科是否存在到期复习任务（前端可提示"先复习"）
            "review_first": bool(review_action),
            "review": review_action,
            "strategy_log_id": log_id,
        }

    def feedback(self, db, student_id, payload):
        """记录学习反馈（对错 / 难度感受 / 是否需要帮助），并给出下一次难度建议。"""
        payload = payload or {}
        question = None
        question_id = int(payload.get("question_id") or 0)
        if question_id:
            question = db.query(Question).filter(Question.id == question_id).first()

        subject = str(payload.get("subject") or (question.subject if question else "")
                      or stages.DEFAULT_SUBJECT)
        knowledge = str(payload.get("knowledge") or (question.knowledge if question else "") or "")
        difficulty_value = int(payload.get("difficulty")
                               or (question.difficulty if question else 50) or 50)
        correct = payload.get("correct")
        correct = bool(correct) if correct is not None else None
        feel = str(payload.get("feel") or "").strip().lower()
        need_help = bool(payload.get("need_help"))

        row = LearningFeedback(
            student_id=student_id,
            subject=subject,
            knowledge_id=knowledge,
            question_id=question_id or None,
            difficulty=difficulty_value,
            correct=correct,
            feel=feel,
            need_help=need_help,
            note=str(payload.get("note") or "")[:500],
            created_time=datetime.now(),
        )
        db.add(row)
        db.flush()

        plan_row = self._advance_plan(db, student_id, subject, knowledge)
        db.commit()

        state = self.difficulty_state(db, student_id, subject, knowledge, feel=feel or None)
        message = self._feedback_message(feel, need_help, state)

        return {
            "saved": True,
            "id": row.id,
            "student_id": student_id,
            "subject": subject,
            "knowledge": knowledge,
            "feel": feel,
            "feel_text": difficulty.FEEL_TEXT.get(feel, ""),
            "need_help": need_help,
            "next_difficulty": state["difficulty"],
            "difficulty_delta": state["delta"],
            "difficulty_reason": state["reason"],
            "stage_action": state["stage_action"],
            "on_target": state["on_target"],
            "message": message,
            "plan": {
                "id": plan_row.id if plan_row else 0,
                "completed_count": int(plan_row.completed_count or 0) if plan_row else 0,
                "target_count": int(plan_row.target_count or 0) if plan_row else 0,
                "status": plan_row.status if plan_row else "",
            },
        }

    @staticmethod
    def _feedback_message(feel, need_help, state):
        if need_help:
            return "收到，这道题我们慢慢来：先看一遍解析，下一题难度会降一点，把信心找回来。"
        if feel == "easy":
            return "很棒！下一题会稍微难一点，继续加油。"
        if feel in ("hard", "lost"):
            return "没关系，觉得难说明正在进步：下一题难度会降一点，先把基础打牢。"
        return "收到你的感受，系统会继续按你的节奏调整难度。"

    def _advance_plan(self, db, student_id, subject, knowledge):
        """今天这个科目的计划完成数 +1（找不到计划就不计数）。"""
        day = planner.date_text()
        rows = db.query(LearningPlan).filter(
            LearningPlan.student_id == student_id,
            LearningPlan.date == day,
            LearningPlan.subject == subject,
            LearningPlan.status != planner.STATUS_EXPIRED,
        ).order_by(LearningPlan.priority.asc(), LearningPlan.id.asc()).all()

        row = next((item for item in rows if item.knowledge_id == knowledge), None)
        row = row or (rows[0] if rows else None)
        if row is None:
            return None

        row.completed_count = int(row.completed_count or 0) + 1
        row.status = (planner.STATUS_DONE
                      if row.completed_count >= int(row.target_count or 0)
                      else planner.STATUS_DOING)
        row.updated_time = datetime.now()
        return row

    # ---------------- 日志 ----------------

    def log(self, db, student_id, decision, source="recommend"):
        """记录"为什么推荐这个学习"（learning_strategy_log）。"""
        decision = decision or {}
        row = LearningStrategyLog(
            student_id=student_id,
            action=decision.get("action") or "",
            reason=decision.get("reason") or "",
            subject=decision.get("subject") or "",
            knowledge_id=decision.get("knowledge") or decision.get("knowledge_id") or "",
            difficulty=int(decision.get("difficulty") or 0),
            mode=decision.get("mode") or "",
            priority_score=float(decision.get("priority_score") or 0),
            source=source,
            created_time=datetime.now(),
        )
        db.add(row)
        db.commit()
        return row.id

    def strategy_logs(self, db, student_id, limit=20):
        """最近的策略日志（给家长/老师看"系统为什么这么安排"）。"""
        rows = db.query(LearningStrategyLog).filter(
            LearningStrategyLog.student_id == student_id,
        ).order_by(LearningStrategyLog.id.desc()).limit(max(1, int(limit))).all()

        return [
            {
                "id": row.id,
                "action": row.action,
                "reason": row.reason,
                "subject": row.subject,
                "knowledge": row.knowledge_id,
                "difficulty": row.difficulty,
                "mode": row.mode,
                "priority_score": row.priority_score,
                "source": row.source,
                "created_time": _fmt(row.created_time),
            }
            for row in rows
        ]

    def feedback_history(self, db, student_id, subject=None, limit=20):
        """最近的学习反馈（主观感受统计，看看难度是不是合适）。"""
        query = db.query(LearningFeedback).filter(LearningFeedback.student_id == student_id)
        if subject:
            query = query.filter(LearningFeedback.subject == subject)

        rows = query.order_by(LearningFeedback.id.desc()).limit(max(1, int(limit))).all()
        counter = {}
        for row in rows:
            key = row.feel or "none"
            counter[key] = counter.get(key, 0) + 1

        return {
            "total": len(rows),
            "by_feel": counter,
            "need_help": sum(1 for row in rows if row.need_help),
            "items": [
                {
                    "id": row.id,
                    "subject": row.subject,
                    "knowledge": row.knowledge_id,
                    "difficulty": row.difficulty,
                    "correct": row.correct,
                    "feel": row.feel,
                    "feel_text": difficulty.FEEL_TEXT.get(row.feel or "", ""),
                    "need_help": bool(row.need_help),
                    "created_time": _fmt(row.created_time),
                }
                for row in rows
            ],
        }


DEFAULT_ENGINE = AdaptiveLearningEngine()
