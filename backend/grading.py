# ==============================================================
# 能力契约｜服务端答案归一化与判定（判分的唯一真相）
# 入口：is_correct / normalize / parse_options / parse_acceptable
# 依赖：json re unicodedata
# 不负责：阶段与掌握度判定 → stages.py / mastery.py
# 验证：python backend/verify_flow.py --self-serve
# 被调用：main.py、diagnostic_routes.py、error_analysis.py、review/engine.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

import json
import re
import unicodedata


def normalize(value):
    """归一化答案：全角转半角、去空白、统一小写与常见标点。"""
    if value is None:
        return ""

    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"\s+", "", text)
    text = text.replace("。", ".").replace("，", ",").replace("．", ".")
    text = text.rstrip(".")
    return text


def parse_options(raw):
    """options 列存的是 JSON 字符串，返回 {选项字母: 选项内容}。"""
    if not raw:
        return {}

    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}

    if not isinstance(data, dict):
        return {}

    return {str(k).strip().upper(): str(v).strip() for k, v in data.items() if k}


def parse_acceptable(raw):
    if not raw:
        return []

    if isinstance(raw, (list, tuple)):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []

    if not isinstance(data, (list, tuple)):
        return []

    return [str(item) for item in data if str(item).strip()]


def is_correct(question, submitted):
    """
    question  : models.Question 行对象（答案是服务端保存的，前端拿不到）
    submitted : 学生提交的内容，选择题是选项字母，填空题是文本
    """
    answer = (question.answer or "").strip()
    given = (submitted or "").strip()

    if not given or not answer:
        return False

    # 直接一致（填空题的主要路径，也覆盖选择题提交字母的情况）
    if normalize(given) == normalize(answer):
        return True

    options = parse_options(question.options)

    if options:
        correct_key = answer.upper()
        given_key = given.upper()

        # 提交的是选项字母
        if given_key in options:
            return given_key == correct_key

        # 提交的是选项内容
        correct_text = options.get(correct_key)
        if correct_text and normalize(given) == normalize(correct_text):
            return True

    # 填空题的其他可接受写法
    return any(normalize(given) == normalize(item) for item in parse_acceptable(question.acceptable))
