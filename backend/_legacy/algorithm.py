# ==============================================================
# 能力契约｜**已归档死代码**：早期等级推进函数，全项目无引用
# 入口：calculate_next_level / update_level
# 依赖：无
# 不负责：现行阶段推进 → stages.py / ability.py
# 验证：不适用（无测试覆盖，禁止接线）
# 被调用：无（未接线）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

def calculate_next_level(level):
    if level < 50:
        return level+3
    elif level < 80:
        return level+5
    return level+8

def update_level(level,result):
    level += 3 if result else -1
    return max(0,min(100,level))
