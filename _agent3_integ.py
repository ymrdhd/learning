# -*- coding: utf-8 -*-
"""临时脚本：验证 generate 对 ORM 行对象 + count/difficulty 参数的兼容性（用完删除）。"""
import os
import sys

os.environ["PHOEBE_AI_OFFLINE"] = "1"
os.environ.setdefault("DATABASE_URL", "sqlite:///C:/Users/1/Desktop/ai_learning_system/backend/_tmp_agent3.db")
sys.path.insert(0, "backend")

import ai_recovery as R


class Row:
    """模拟 SQLAlchemy Question 行对象（属性访问 + options 为 dict）。"""

    subject = "英语"
    knowledge = "be动词"
    difficulty = 35
    question = "I ___ a student."
    answer = "am"
    qtype = "choice"
    options = {"A": "am", "B": "is", "C": "are", "D": "be"}
    analysis = ""


row = Row()
hint = R.teach(row, knowledge="be动词", error_type="语法错误", level=2)
print("teach(row) source =", hint["source"], "| hint =", hint["hint"][:40])
for level in (1, 2, 3, 4):
    res = R.teach(row, knowledge="be动词", level=level)
    print(" L%d source=%s answer_leak=%s" % (level, res["source"], "am" in res["hint"]))

items = R.generate_variants(row, count=1, difficulty=40, knowledge="be动词")
print("generate_variants count=1 ->", len(items), "passed:", items[0]["validation"]["passed"])
print(" source:", items[0]["source"], "| q:", items[0]["question"])
print("subject field present:", "subject" in items[0])

items5 = R.generate_variants(row, count=5, difficulty=40, knowledge="be动词")
print("count=5 unique:", len({i["question"] for i in items5}), "all passed:",
      all(i["validation"]["passed"] for i in items5))
print("RESULT: OK")
