# ==============================================================
# 能力契约｜**已归档死代码**：早期激励机制，引用了 Student 上不存在的列，接线即 AttributeError
# 入口：give_reward
# 依赖：无
# 不负责：现行激励 → 无（激励机制尚未接线，见 PROJECT_CONTEXT §7 Pending）
# 验证：不适用（无测试覆盖，禁止接线）
# 被调用：无（未接线）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

def give_reward(student,correct):

    if correct:
        student.experience += 10
        student.coins += 5
        student.streak += 1

        if student.streak % 7 == 0:
            student.coins += 50
            student.pet_level += 1

    else:
        student.streak = 0

    return {
        "xp":student.experience,
        "coins":student.coins,
        "pet_level":student.pet_level,
        "streak":student.streak
    }
