# ==============================================================
# 能力契约｜**已归档死代码**：早期难度调整函数，全项目无引用（与 adaptive/ 子包无关）
# 入口：adjust_difficulty
# 依赖：无
# 不负责：现行难度调整 → adaptive/difficulty.py
# 验证：不适用（无测试覆盖，禁止接线）
# 被调用：无（未接线）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

def adjust_difficulty(level,correct_rate):

    if correct_rate>0.9:
        return min(level+10,100)

    if correct_rate>0.7:
        return min(level+5,100)

    if correct_rate<0.5:
        return max(level-5,10)

    return level
