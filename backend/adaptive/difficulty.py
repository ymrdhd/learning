# ==============================================================
# 能力契约｜难度动态调整（连对 +5 / 连错 −10 / 窗口正确率升降阶段），难度恒在 1~100
# 入口：DifficultyController.adjust / adjust / stage_step / clamp_difficulty / streak_of / window_rate / DEFAULT_CONTROLLER
# 依赖：datetime
# 不负责：难度映射表与阶段阈值 → stages.py
# 验证：python backend/verify_adaptive.py
# 被调用：adaptive/engine.py、adaptive_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎 · 难度动态调整 DifficultyController。

目标：让学生稳定停在**最佳学习区间**（目标正确率 70%~85%）。
太难会挫败，太简单不进步，所以难度必须跟着最近的表现走。

规则（与需求逐条对应）：

| 观察到的表现                 | 调整                                        |
| ---------------------------- | ------------------------------------------- |
| 连续答对 5 题                | 难度 +5（每满 5 题再升一档，单次最多 +10）  |
| 连续答错 3 题                | 难度 −10（每满 3 题再降一档，单次最多 −10） |
| 最近 10 题正确率 ≥ 90%       | 提升阶段（stage_action = "up"）             |
| 最近 10 题正确率 < 50%       | 降低阶段（stage_action = "down"）           |
| 孩子反馈"简单 / 有点难 / 不会" | 微调 +3 / −3 / −6（主观感受也当证据）      |

连对/连错与正确率窗口**不重复计分**：连对（或连错）已经调整了难度，
正确率窗口就只负责"提升/降低阶段"；只有在没有连对/连错时，
正确率窗口才顺手把难度推一点，避免一次跳两级。

约束：
1. 难度恒在 1~100。
2. 单次调整幅度不超过 ±10，避免难度剧烈跳动。
3. 样本太少（不足 5 题）时只看连对/连错，不按正确率调，防止"错一道就降难度"。
"""

from datetime import datetime

MIN_DIFFICULTY = 1
MAX_DIFFICULTY = 100

TARGET_LOW = 0.70          # 最佳学习区间下沿
TARGET_HIGH = 0.85         # 最佳学习区间上沿

WINDOW = 10                # 观察窗口（最近几题）
MIN_WINDOW = 5             # 窗口样本下限，少于它不按正确率调整

UP_STREAK = 5              # 连续答对几题升难度
UP_STEP = 5
DOWN_STREAK = 3            # 连续答错几题降难度
DOWN_STEP = 10

MAX_STEP = 10              # 单次调整上限
UP_RATE = 0.90             # 最近 10 题达到它 → 提升阶段
DOWN_RATE = 0.50           # 最近 10 题低于它 → 降低阶段

# 孩子的主观难度感受 → 难度微调
FEEL_DELTA = {"easy": 3, "normal": 0, "hard": -3, "lost": -6}
FEEL_TEXT = {"easy": "太简单", "normal": "刚刚好", "hard": "有点难", "lost": "不会做"}

STAGE_TEXT = {"up": "提升阶段", "down": "降低阶段", "hold": "保持阶段"}


def clamp_difficulty(value, low=MIN_DIFFICULTY, high=MAX_DIFFICULTY):
    """难度夹到合法区间；非法输入按区间下沿处理。"""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))


def ordered(records):
    """答题记录按时间升序排列；都没有时间时按传入顺序（约定为从旧到新）。"""
    items = [item for item in (records or ()) if item]
    if items and all(isinstance(item.get("time"), datetime) for item in items):
        return sorted(items, key=lambda item: item["time"])
    return list(items)


def streak_of(records):
    """从最新一条往前数，返回 (kind, count)：kind 为 correct / wrong / none。"""
    items = ordered(records)
    if not items:
        return "none", 0

    kind = "correct" if items[-1].get("correct") else "wrong"
    count = 0
    for item in reversed(items):
        if bool(item.get("correct")) != (kind == "correct"):
            break
        count += 1
    return kind, count


def window_rate(records, window=WINDOW):
    """最近 window 题的正确率，返回 (rate, size)。"""
    items = ordered(records)[-max(1, int(window)):]
    if not items:
        return 0.0, 0
    hits = sum(1 for item in items if item.get("correct"))
    return hits / len(items), len(items)


class DifficultyController:
    """难度动态调整器（纯函数，不碰数据库，方便直接单测）。"""

    def adjust(self, base, records=(), feel=None, now=None):
        """算下一题该用什么难度。

        base:    基准难度（能力分与知识点难度的混合值）
        records: [{"correct": bool, "difficulty": int, "time": datetime}, ...]
        feel:    easy / normal / hard / lost（孩子上一次的主观感受，可空）

        返回 dict：difficulty、delta、streak、window_rate、on_target、
        stage_action、reason。
        """
        base = clamp_difficulty(base)
        kind, count = streak_of(records)
        rate, size = window_rate(records)

        delta = 0
        reasons = []
        streak_fired = False

        # 1) 连对升难度 / 连错降难度
        if kind == "correct" and count >= UP_STREAK:
            step = min(UP_STEP * (count // UP_STREAK), MAX_STEP)
            delta += step
            streak_fired = True
            reasons.append(f"连续答对 {count} 题，难度 +{step}")
        elif kind == "wrong" and count >= DOWN_STREAK:
            step = min(DOWN_STEP * (count // DOWN_STREAK), MAX_STEP)
            delta -= step
            streak_fired = True
            reasons.append(f"连续答错 {count} 题，难度 -{step}")

        # 2) 最近 10 题正确率 → 阶段提升 / 降低
        #    连对/连错已经调过难度时，这里只改阶段，不再重复调难度
        stage_action = "hold"
        if size >= MIN_WINDOW:
            if rate >= UP_RATE:
                stage_action = "up"
                if not streak_fired:
                    delta += UP_STEP
                reasons.append(f"最近 {size} 题正确率 {int(round(rate * 100))}%，进入提升阶段")
            elif rate < DOWN_RATE:
                stage_action = "down"
                if not streak_fired:
                    delta -= UP_STEP
                reasons.append(f"最近 {size} 题正确率 {int(round(rate * 100))}%，先降低阶段稳一稳")

        # 3) 主观难度感受微调
        feel_delta = FEEL_DELTA.get(str(feel or "").strip().lower(), 0)
        if feel_delta:
            delta += feel_delta
            reasons.append(f"孩子觉得「{FEEL_TEXT.get(str(feel).lower(), '')}」，难度 {feel_delta:+d}")

        delta = max(-MAX_STEP, min(MAX_STEP, delta))
        target = clamp_difficulty(base + delta)
        # 调整后实际生效的变化（可能被区间夹住）
        real_delta = target - base

        if not reasons:
            reasons.append("表现稳定，难度保持不变")

        return {
            "difficulty": target,
            "base": base,
            "delta": real_delta,
            "focus_delta": delta,
            "streak": {"kind": kind, "count": count},
            "window_rate": round(rate, 3),
            "window_size": size,
            "on_target": bool(size >= 3 and TARGET_LOW <= rate <= TARGET_HIGH),
            "stage_action": stage_action,
            "stage_text": STAGE_TEXT.get(stage_action, "保持阶段"),
            "feel": str(feel or ""),
            "target_range": [int(TARGET_LOW * 100), int(TARGET_HIGH * 100)],
            "reason": "；".join(reasons),
        }


DEFAULT_CONTROLLER = DifficultyController()


def adjust(base, records=(), feel=None, now=None):
    """模块级快捷入口。"""
    return DEFAULT_CONTROLLER.adjust(base, records, feel=feel, now=now)


def stage_step(stage_action, stage_key):
    """阶段变化：up → 下一阶段、down → 上一阶段、hold → 不变。

    依赖 stages 模块，但只在真正需要改阶段时调用，避免所有调用方都被拖进来。
    """
    import stages

    stage_key = stages.normalize_key(stage_key) or stages.START_KEY
    if stage_action == "up":
        return stages.next_key(stage_key)
    if stage_action == "down":
        return stages.prev_key(stage_key)
    return stage_key
