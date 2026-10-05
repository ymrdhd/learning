# ==============================================================
# 能力契约｜下一题推荐（40% 薄弱 + 30% 匹配 + 20% 遗忘 + 10% 探索）
# 入口：QuestionSelector.select / select_from_decision / breakdown / match_score / DEFAULT_SELECTOR
# 依赖：random
# 不负责：复习题选择 → review/selector.py
# 验证：python backend/verify_adaptive.py
# 被调用：adaptive/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎 · 下一题推荐 QuestionSelector。

挑选"下一题出在哪个知识点上"，四项证据加权：

| 权重 | 证据       | 说明 |
| --- | --- | --- |
| 40% | 知识薄弱度 | 掌握度越低越该练 |
| 30% | 当前能力匹配 | 知识点难度与目标难度的贴合度 |
| 20% | 遗忘风险   | 到期没复习 / 很久没练的先安排 |
| 10% | 随机探索   | 保留一点新鲜感，避免路径完全固定 |

再加两条防呆规则：

1. **题源配比 70 / 20 / 10**：70% 当前薄弱知识、20% 复习旧知识、10% 挑战知识。
2. **同知识点回避**：最近 3 题练过的知识点降权，避免"一直做同一种题"。
"""

import random

WEIGHTS = {"weakness": 0.40, "match": 0.30, "forgetting": 0.20, "random": 0.10}

# 题源配比：薄弱 70% / 复习 20% / 挑战 10%
MODE_WEIGHTS = (("practice", 0.70), ("review", 0.20), ("challenge", 0.10))
MODE_TEXT = {"practice": "当前薄弱知识", "review": "复习旧知识", "challenge": "挑战知识"}

# 同知识点软避让：最近练过的知识点降权，但最近第几题扣得多、隔几题扣得少。
# 不硬禁——同一种题隔几道还能再练；罚分保持在 weakness 权重（0.40）之下，
# 让"薄弱程度"仍然是主要驱动力，避免把软避让变成事实上的硬禁。
REPEAT_PENALTY = 0.12              # 兼容旧值 / 展示用基准（距上次已隔几题）
REPEAT_PENALTY_NEAREST = 0.35      # 上一题就是这个知识点（仍是最大的单项扣分）
REPEAT_PENALTY_RECENT = 0.22       # 再往前一道（最近 2 题内）
REPEAT_WINDOW = 5                  # 备注：实际窗口由 engine.next_spec 传进来的 limit=5 决定
CHALLENGE_LINE = 85
WEAK_LINE = 70

def repeat_penalty_of(knowledge, recent_knowledge=()):
    """同知识点软避让惩罚：越近的扣得越多，隔几道题只扣基准值。

    不硬禁重复（可以反复练习），只是让 "每一道都同一个知识点" 不再必然发生。
    """
    name = str(knowledge or "").strip()
    if not name:
        return 0.0

    recent = [str(item).strip() for item in (recent_knowledge or ())]
    if name not in recent:
        return 0.0

    distance = len(recent) - 1 - recent[::-1].index(name)   # 0 = 上一题刚练过
    if distance == 0:
        return REPEAT_PENALTY_NEAREST
    if distance == 1:
        return REPEAT_PENALTY_RECENT
    return REPEAT_PENALTY


def match_score(knowledge_difficulty, target_difficulty):
    """能力匹配度 0~1：知识点难度离目标难度越近越高。"""
    try:
        gap = abs(float(knowledge_difficulty or 50) - float(target_difficulty or 50))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, 1.0 - gap / 100.0))


class QuestionSelector:
    """下一题知识点选择器（纯函数，随机源可注入，方便直接单测）。"""

    def choose_mode(self, rng=None, weights=MODE_WEIGHTS):
        """按 70/20/10 抽题源类型。"""
        rng = rng or random.Random()
        roll = rng.random()
        cumulative = 0.0

        for mode, weight in weights:
            cumulative += float(weight)
            if roll < cumulative:
                return mode

        return weights[-1][0]

    def pool_for(self, mode, candidates):
        """按题源类型筛候选；筛空了就退回全量，保证永远有题可出。"""
        items = [item for item in (candidates or ()) if item]

        if mode == "review":
            pool = [item for item in items if item.get("practiced")]
        elif mode == "challenge":
            pool = [item for item in items if int(item.get("mastery") or 0) >= WEAK_LINE]
        else:
            pool = [item for item in items if int(item.get("mastery") or 0) < CHALLENGE_LINE]

        return pool or items

    def breakdown(self, item, target_difficulty=50, rng=None, recent_knowledge=()):
        """单个候选的四项打分。"""
        rng = rng or random.Random()
        weakness = float(item.get("weakness") or 0)
        match = match_score(item.get("difficulty"), target_difficulty)
        forgetting = float(item.get("forgetting") or 0)
        explore = rng.random()

        score = (WEIGHTS["weakness"] * weakness
                 + WEIGHTS["match"] * match
                 + WEIGHTS["forgetting"] * forgetting
                 + WEIGHTS["random"] * explore)

        penalty = repeat_penalty_of(item.get("knowledge"), recent_knowledge)
        if penalty:
            score -= penalty

        return {
            "weakness": round(weakness, 3),
            "match": round(match, 3),
            "forgetting": round(forgetting, 3),
            "random": round(explore, 3),
            "repeat_penalty": -penalty,
            "score": round(score, 4),
        }

    def select(self, candidates, target_difficulty=50, mode=None, rng=None,
               recent_knowledge=()):
        """选出下一题的知识点与难度。

        candidates: strategy.rank() 的输出（含 knowledge / mastery / difficulty /
                    weakness / forgetting / practiced）。
        """
        rng = rng or random.Random()
        items = [item for item in (candidates or ()) if item]
        if not items:
            return {
                "knowledge": "",
                "difficulty": target_difficulty,
                "mode": mode or "practice",
                "score": 0.0,
                "breakdown": {},
                "reason": "没有可选知识点",
                "alternatives": [],
            }

        mode = mode or self.choose_mode(rng)
        pool = self.pool_for(mode, items)

        scored = []
        for item in pool:
            breakdown = self.breakdown(item, target_difficulty, rng, recent_knowledge)
            scored.append({
                "knowledge": item.get("knowledge"),
                "mastery": int(item.get("mastery") or 0),
                "difficulty": int(item.get("difficulty") or target_difficulty),
                "breakdown": breakdown,
                "score": breakdown["score"],
            })

        scored.sort(key=lambda entry: (-entry["score"], str(entry["knowledge"])))
        best = scored[0]

        if best["breakdown"]["weakness"] >= 0.45:
            reason = f"薄弱知识优先：{best['knowledge']}（掌握度 {best['mastery']}）"
        elif best["breakdown"]["forgetting"] >= 0.6:
            reason = f"快忘了，先复习：{best['knowledge']}（掌握度 {best['mastery']}）"
        else:
            reason = f"{MODE_TEXT.get(mode, '当前薄弱知识')}：{best['knowledge']}（掌握度 {best['mastery']}）"

        return {
            "knowledge": best["knowledge"],
            "difficulty": int(target_difficulty),
            "mode": mode,
            "mode_text": MODE_TEXT.get(mode, ""),
            "score": best["score"],
            "breakdown": best["breakdown"],
            "reason": reason,
            "alternatives": [
                {"knowledge": entry["knowledge"], "score": entry["score"],
                 "mastery": entry["mastery"]}
                for entry in scored[1:4]
            ],
            "strategy": "QuestionSelector",
        }

    def select_from_decision(self, decision, rng=None, recent_knowledge=()):
        """便捷入口：直接吃 strategy.choose() 的结果。"""
        candidates = decision.get("ranked") or []
        picked = self.select(candidates,
                             target_difficulty=decision.get("difficulty") or 50,
                             mode=decision.get("mode"),
                             rng=rng,
                             recent_knowledge=recent_knowledge)
        picked["action"] = decision.get("action")
        picked["action_text"] = decision.get("action_text")
        picked["reason"] = picked["reason"] or decision.get("reason")
        return picked


DEFAULT_SELECTOR = QuestionSelector()
