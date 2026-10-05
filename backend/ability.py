# ==============================================================
# 能力契约｜能力阶段推进与下一题难度的轻量纯函数（V2.1 遗留，仍在用）
# 入口：calculate_stage / next_difficulty
# 依赖：无
# 不负责：自适应难度调整 → adaptive/difficulty.py；诊断评分 → diagnostic.py
# 验证：python backend/verify_flow.py --self-serve
# 被调用：main.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

def calculate_stage(total, correct, difficulty):
    if total == 0:
        return 1.0, 50

    rate = correct / total

    if rate >= 0.9:
        stage = min(6.0, difficulty/20)
        score = min(100, 70 + rate*30)

    elif rate >= 0.75:
        stage = difficulty/25
        score = 70 + rate*20

    elif rate >= 0.6:
        stage = difficulty/30
        score = 60

    else:
        stage = max(1, difficulty/35)
        score = 50

    return round(stage,1), round(score,1)


def next_difficulty(correct_rate, current):
    if correct_rate >= 0.9:
        return min(100,current+10)

    if correct_rate >= 0.75:
        return min(100,current+5)

    if correct_rate < 0.5:
        return max(10,current-10)

    return current
