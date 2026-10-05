# -*- coding: utf-8 -*-
"""变式题池抽查：每个知识点重复 30 次 generate(count=5)，统计唯一题干数。"""
import os
import sys
import collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
os.environ["PHOEBE_AI_OFFLINE"] = "1"
import ai_recovery  # noqa: E402

SEEDS = [
    ("数学", "两位数加法", "算一算：27 + 15 = ？", "42", 30),
    ("数学", "表内乘法", "算一算：6 × 7 = ？", "42", 30),
    ("数学", "长方形周长", "一个长方形的长是 5 厘米，宽是 3 厘米，它的周长是多少厘米？", "16厘米", 40),
    ("数学", "长方形面积", "一个长方形的长是 5 米，宽是 3 米，它的面积是多少平方米？", "15平方米", 40),
    ("语文", "反义词", "「高兴」的反义词是？", "难过", 20),
    ("语文", "近义词", "「美丽」的近义词是？", "漂亮", 20),
    ("语文", "量词", "一（  ）小鸟", "只", 20),
    ("语文", "笔画", "「口」一共有几画？", "3画", 20),
    ("语文", "比喻修辞", "下面哪一句用了比喻的手法？", "弯弯的月亮像一只小船。", 20),
    ("语文", "拼音", "「大」的拼音是？", "dà", 20),
    ("英语", "名词复数", "「book」的复数形式是？", "books", 30),
    ("英语", "过去式", "「play」的过去式是？", "played", 30),
    ("英语", "现在进行时", "「run」的现在分词是？", "running", 30),
    ("英语", "颜色", "「红色」用英语怎么说？", "red", 30),
    ("英语", "动物", "「猫」用英语怎么说？", "cat", 30),
    ("英语", "数字", "「三」用英语怎么写？", "three", 30),
    ("英语", "be动词", "I ___ a student.", "am", 30),
]

gen = ai_recovery.VariantQuestionGenerator()
bad = []
for subject, knowledge, question, answer, difficulty in SEEDS:
    seed = {"subject": subject, "knowledge": knowledge, "question": question,
            "answer": answer, "qtype": "choice",
            "options": {"A": answer, "B": "x", "C": "y", "D": "z"}, "difficulty": difficulty}
    worst = 99
    for _ in range(30):
        items = gen.generate(seed, count=5, knowledge=knowledge)
        assert len(items) == 5, (knowledge, len(items))
        unique = len({item["question"] for item in items})
        worst = min(worst, unique)
        for item in items:
            assert item["validation"].get("passed"), (knowledge, item["question"], item["validation"]["issues"])
            assert item["source"] in ("ai", "rule"), item["source"]
    flag = "OK  " if worst == 5 else "BAD "
    print(f"{flag}{subject}/{knowledge}: 30 轮 × 5 题，最少唯一题干 {worst}/5")
    if worst < 5:
        bad.append((subject, knowledge, worst))

print("\nRESULT:", "ALL PASS" if not bad else f"BAD: {bad}")
sys.exit(1 if bad else 0)
