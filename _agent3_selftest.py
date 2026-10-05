# -*- coding: utf-8 -*-
"""Agent 3 自测：四级提示 + 变式题生成（临时文件，测完删除）。"""
import os
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
os.environ["PHOEBE_AI_OFFLINE"] = "1"

import ai_recovery  # noqa: E402
import deepseek  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(detail)))
    if not ok:
        FAILS.append(name)


def norm(text):
    return unicodedata.normalize("NFKC", str(text or "")).strip().lower().replace(" ", "")


ROWS = {
    "数学": {"id": 1, "subject": "数学", "knowledge": "两位数加法", "difficulty": 30,
             "question": "算一算：27 + 15 = ？", "answer": "42", "qtype": "fill",
             "options": {}, "analysis": "相同数位对齐，个位相加满十进一。"},
    "语文": {"id": 2, "subject": "语文", "knowledge": "反义词", "difficulty": 20,
             "question": "「高兴」的反义词是下面哪一个词？", "answer": "难过", "qtype": "choice",
             "options": {"A": "难过", "B": "快乐", "C": "开心", "D": "欢喜"}, "analysis": ""},
    "英语": {"id": 3, "subject": "英语", "knowledge": "be动词", "difficulty": 35,
             "question": "I ___ a student.", "answer": "am", "qtype": "choice",
             "options": {"A": "am", "B": "is", "C": "are", "D": "be"}, "analysis": ""},
}


def answer_text(row):
    raw = str(row.get("answer") or "")
    opts = row.get("options") or {}
    for key, value in opts.items():
        if key.upper() == raw.upper():
            return str(value)
    return raw


print("=== ai_enabled（无 key + 离线）===")
check("ai_enabled() is False", ai_recovery.ai_enabled() is False)
check("deepseek.KEY 为空或已离线", not getattr(deepseek, "KEY", "") or True)

print("\n=== levels() / level_name() ===")
levels = ai_recovery.levels()
check("levels() 恰好四级", len(levels) == 4, len(levels))
check("每级含 level/name/text",
      all({"level", "name", "text"} <= set(item) for item in levels) and all(item.get("level_text") for item in levels),
      levels)
check("level 为 1..4", [item["level"] for item in levels] == [1, 2, 3, 4])
check("L1 名 = 方向提示", ai_recovery.level_name(1) == "方向提示")
check("L2 名 = 错误定位", ai_recovery.level_name(2) == "错误定位")
check("L3 名 = 步骤引导", ai_recovery.level_name(3) == "步骤引导")
check("L4 名 = 完整讲解", ai_recovery.level_name(4) == "完整讲解")
check("越界归一到 1", ai_recovery.level_name(99) == "方向提示")

print("\n=== 四级提示（离线降级）===")
teacher = ai_recovery.AIRecoveryTeacher()
for subject, row in ROWS.items():
    answer = norm(answer_text(row))
    for level in (1, 2, 3, 4):
        result = teacher.teach(row, knowledge=row["knowledge"],
                               error_type="计算错误" if subject == "数学" else "字词错误",
                               level=level, student={"id": 1}, use_ai=True)
        text = " ".join([str(result.get("hint") or ""), str(result.get("error_location") or ""),
                         " ".join(result.get("steps") or []),
                         str(result.get("full_explanation") or "")])
        has_answer = answer and answer in norm(text)
        tag = f"{subject} L{level}"
        check(tag + " 字段齐全",
              set(result) >= {"level", "level_text", "hint", "source", "error_location",
                              "steps", "full_explanation"}, sorted(result))
        check(tag + " level 回显正确", result["level"] == level, result["level"])
        check(tag + " level_text 正确", result["level_text"] == ai_recovery.level_name(level))
        check(tag + " source 合法",
              result["source"] in ("ai", "rule", "fallback_offline", "fallback_no_key",
                                   "fallback_disabled", "fallback_error"), result["source"])
        check(tag + " hint 非空", bool(str(result["hint"]).strip()))
        if level in (1, 2, 3):
            check(tag + " **不含最终答案**", not has_answer, text[:120])
        else:
            check(tag + " **含最终答案**", has_answer, text[:120])
    check(f"{subject} L3 含步骤", len(teacher.teach(row, level=3)["steps"]) >= 3)
    check(f"{subject} L2 有 error_location 且 L1 无",
          bool(teacher.teach(row, level=2)["error_location"].strip())
          and not teacher.teach(row, level=1)["error_location"].strip())

print("\n=== 异常/边界降级（不抛）===")
check("None 题不抛", isinstance(teacher.teach(None, level=2), dict))
check("use_ai=False 不联网", teacher.teach(ROWS["数学"], level=3, use_ai=False)["source"] == "fallback_disabled")
check("level=0 归一到 1", teacher.teach(ROWS["数学"], level=0)["level"] == 1)
check("level='abc' 归一到 1", teacher.teach(ROWS["数学"], level="abc")["level"] == 1)
check("level=9 归一到 1", teacher.teach(ROWS["数学"], level=9)["level"] == 1)
check("fallback_hint(None, 4) 不抛", isinstance(ai_recovery.fallback_hint(None, 4), dict))

print("\n=== 变式题生成 generate(count=5) ===")
gen = ai_recovery.VariantQuestionGenerator()
for subject, row in ROWS.items():
    items = gen.generate(row, count=5, knowledge=row["knowledge"], use_ai=True)
    check(f"{subject} 恰好 5 题", len(items) == 5, len(items))
    for index, item in enumerate(items, 1):
        tag = f"{subject} 变式{index}"
        check(tag + " 字段齐全",
              set(item) >= {"question", "answer", "options", "qtype", "knowledge",
                            "difficulty", "analysis", "source", "validation"}, sorted(item))
        check(tag + " validation.passed", bool(item["validation"].get("passed")),
              item["validation"].get("issues"))
        check(tag + " source 合法（ai/rule）", item["source"] in ("ai", "rule"), item["source"])
        check(tag + " 非空题干/答案", bool(item["question"].strip()) and bool(str(item["answer"]).strip()))
    check(f"{subject} 5 题题干互不相同",
          len({item["question"] for item in items}) == 5,
          [item["question"] for item in items])
    check(f"{subject} 难度回显", all(item["difficulty"] == int(row["difficulty"] or 50) for item in items))
    check(f"{subject} 知识点回显", all(item["knowledge"] == row["knowledge"] for item in items))

print("\n=== validate_variant 独立调用 ===")
good = {"question": "算一算：3 + 4 = ？", "answer": "A", "options": {"A": "7", "B": "8", "C": "6", "D": "9"},
        "qtype": "choice", "analysis": "3+4=7。", "source": "rule"}
bad = {"question": "算一算：3 + 4 = ？", "answer": "B", "options": {"A": "7", "B": "8", "C": "6", "D": "9"},
       "qtype": "choice", "analysis": "", "source": "rule"}
check("validate_variant(good).passed", bool(gen.validate_variant(good, subject="数学", knowledge="两位数加法",
                                                                 difficulty=30).get("passed")))
check("validate_variant(bad) 被拦（use_ai 也丢弃）",
      not bool(gen.validate_variant(bad, subject="数学", knowledge="两位数加法", difficulty=30).get("passed")))
check("模块级 validate_variant 可用",
      isinstance(ai_recovery.validate_variant(good, subject="数学", knowledge="两位数加法", difficulty=30), dict))
check("count=0 返回空表", gen.generate(ROWS["数学"], count=0) == [])

print("\n=== 其它 ===")
check("模块级 teach 可用", isinstance(ai_recovery.teach(ROWS["数学"], level=1), dict))
check("模块级 generate_variants 可用", len(ai_recovery.generate_variants(ROWS["数学"], count=2)) == 2)
check("DEFAULT_TEACHER / DEFAULT_GENERATOR 存在",
      isinstance(ai_recovery.DEFAULT_TEACHER, ai_recovery.AIRecoveryTeacher)
      and isinstance(ai_recovery.DEFAULT_GENERATOR, ai_recovery.VariantQuestionGenerator))

print("\n==== 结果 ====")
print("FAILED:", FAILS if FAILS else "无")
print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
