# ==============================================================
# 能力契约｜**已归档死代码**：早期 DeepSeek 出题函数（无审核、无兜底），全项目无引用
# 入口：create_question
# 依赖：requests
# 不负责：现行出题 → deepseek.py + validator.py
# 验证：不适用（无测试覆盖，禁止接线）
# 被调用：无（未接线）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

import requests

DEEPSEEK_KEY="YOUR_DEEPSEEK_KEY"

def create_question(grade,knowledge,difficulty):
    prompt=f'''
你是长沙小学数学老师。
学生：{grade}
知识点：{knowledge}
难度：{difficulty}/100

生成一道题，并返回JSON：
题目、答案、解析
'''

    response=requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization":f"Bearer {DEEPSEEK_KEY}"},
        json={
            "model":"deepseek-chat",
            "messages":[{"role":"user","content":prompt}]
        }
    )

    return response.json()
