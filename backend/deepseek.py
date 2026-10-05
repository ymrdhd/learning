# ==============================================================
# 能力契约｜DeepSeek 出题 / 错因分析 + 内置兜底题（FALLBACK）
# 入口：generate_question / generate_review_question / analyze_error / ability_block / CHOICE / FALLBACK / KEY
# 防雷同：generate_question 可传 history（最近原题），prompt 回避 + 本地重复检测重试
# 依赖：requests re json pathlib（密钥只读 DEEPSEEK_API_KEY / backend/.env）
# 依赖：requests re json pathlib（密钥只读 DEEPSEEK_API_KEY / backend/.env）+ question_dedupe（题干雷同检测）
# 验证：python backend/verify_flow.py --self-serve
# 被调用：main.py、diagnostic_routes.py、error_analysis.py、review/selector.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

import json
import os
import re
from pathlib import Path
import requests

import question_dedupe

# 不负责：题目审核 → validator.py；判分 → grading.py

CHOICE = "choice"
BLANK = "blank"

API_URL = "https://api.deepseek.com/chat/completions"
TIMEOUT = 30

# 出题防雷同：一次练习里同一个知识点容易连出同一道经典题（例如「床前明月光」），
# 这里最多尝试 3 次，命中历史原题就换一道；仍然雷同也只发最后一版，绝不发兜底题顶替正常出题。
MAX_GENERATION_ATTEMPTS = 3
AVOID_HISTORY_LIMIT = 6


def _load_key():
    """优先读环境变量，其次读同目录下的 .env（本地私密文件，不纳入版本控制）。"""
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key

    env_file = Path(__file__).with_name(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "DEEPSEEK_API_KEY":
                return value.strip().strip('"').strip("'")

    return ""


KEY = _load_key()

# 出题失败时的本地兜底题库，保证学习流程不会因为接口异常而中断
FALLBACK = {
    CHOICE: {
        "question": "算一算：5 + 3 = ？",
        "options": {"A": "7", "B": "8", "C": "9", "D": "6"},
        "answer": "B",
        "acceptable": [],
        "analysis": "5 和 3 合起来是 8，所以选 B。",
    },
    BLANK: {
        "question": "算一算，把答案填在横线上：5 + 3 = ____",
        "options": {},
        "answer": "8",
        "acceptable": ["8", "八"],
        "analysis": "5 和 3 合起来是 8。",
    },
}

CHOICE_PROMPT = """
只返回JSON，不要额外文字，格式：
{{"question":"题目","options":{{"A":"选项A内容","B":"选项B内容","C":"选项C内容","D":"选项D内容"}},"answer":"正确选项字母","analysis":"解析","needs_image":false}}

硬性要求：
1. 必须给出4个互不相同的选项，用 A、B、C、D 作为键。
2. answer 只能是 A、B、C、D 中的一个字母，且必须是正确答案。
3. 错误选项要像小学生的常见错误，不要出现"以上都对"这类选项。
4. analysis 用小学生能听懂的话讲清为什么。
5. **系统不会给题目配任何图片**：题目必须只靠题干文字就能作答。不要写"看图 / 图中 / 如图 / 下图 / 上图 / 图片 / 插图 / 图案 / 这幅图"这类要孩子看一张没给出的图才能回答的话；也不要让孩子比较形状、写法、位置（例如"哪一朵花上的字母写得又对、又没有写错"），除非题干里已经用文字把图上的内容说清楚。
6. needs_image 如实填写：纯文字就能答就填 false；确实非看图不可才填 true（我们会丢掉这一版重出）。
"""

BLANK_PROMPT = """
只返回JSON，不要额外文字，格式：
{{"question":"题目","answer":"标准答案","acceptable_answers":["其他同样正确的写法"],"analysis":"解析","needs_image":false}}

硬性要求：
1. 题目必须能在横线上填一个很短的答案（一个数、一个符号或一个词）。
2. answer 是最标准、最简洁的写法。
3. acceptable_answers 列出其他同样正确的写法，没有就给空数组。
4. analysis 用小学生能听懂的话讲清为什么。
5. **系统不会给题目配任何图片**：题目必须只靠题干文字就能作答，不要写"看图 / 图中 / 如图 / 下图 / 上图 / 图片 / 插图 / 图案"这类要孩子看一张没给出的图才能回答的话。
6. needs_image 如实填写：纯文字就能答就填 false；确实非看图不可才填 true（我们会丢掉这一版重出）。
"""


def _extract_json(text):
    """从模型输出里取 JSON，兼容 ```json 代码块与前后说明文字。"""
    if not text:
        return None

    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    return None


def _clean_options(raw):
    if not isinstance(raw, dict):
        return {}

    options = {}
    for key, value in raw.items():
        letter = str(key).strip().upper().replace("选项", "")
        text = str(value).strip()
        if letter and text:
            options[letter] = text

    return options


def ability_block(subject, ability):
    """V2.0/V2.3：把"学生能力画像 + 错误历史"写进 prompt，出题不再只看年级。

    ability 结构（由诊断与知识掌握系统提供，缺项会跳过）：
        {"grade": "四年级", "stage": "3.2", "stage_label": "三年级熟练",
         "target_stage": "3.3", "target_label": "三年级进阶",
         "knowledge": "两步应用题", "mastery": 62,
         "error_focus": "审题错误", "goal": "生成一道略高于当前能力的训练题"}
    """
    if not ability:
        return ""

    lines = []
    grade = ability.get("grade") or ""
    name = ability.get("student") or ""
    if name or grade:
        who = name or "小朋友"
        lines.append(f"学生：{who}" + (f"（{grade}）" if grade else ""))

    stage = ability.get("stage")
    if stage:
        label = ability.get("stage_label") or ""
        lines.append(f"当前能力：{subject}{stage}阶段" + (f"（{label}）" if label else ""))

    target = ability.get("target_stage")
    if target:
        label = ability.get("target_label") or ""
        lines.append(f"目标阶段：{target}" + (f"（{label}）" if label else ""))

    knowledge = ability.get("knowledge")
    if knowledge:
        lines.append(f"知识点：{knowledge}")

    mastery = ability.get("mastery")
    if mastery is not None:
        goal_mastery = ability.get("mastery_goal")
        line = f"掌握度：{mastery}"
        if goal_mastery:
            line += f"，这次练习的目标是提升到 {goal_mastery} 以上"
        lines.append(line)

    focus = ability.get("error_focus")
    if focus:
        lines.append(f"错误历史：{focus}较多，出题时针对这个薄弱点设计")

    goal = ability.get("goal") or "生成一道略高于当前能力的训练题。"
    lines.append(f"目标：{goal}")
    lines.append("出题要求：让孩子努力一下能做对，不要超出目标阶段太多。")
    return "\n".join(lines)


def avoid_repeat_block(history):
    """出题防雷同：把最近原题写进 prompt，明确要求换数字 / 换情境。

    history 为空时返回空串，prompt 与改动前完全一致（不改变老行为）。
    只取最近 AVOID_HISTORY_LIMIT 条，控制 token 增量。
    """
    stems = [str(item).strip() for item in (history or ()) if str(item).strip()]
    stems = stems[:AVOID_HISTORY_LIMIT]
    if not stems:
        return ""

    lines = [
        "避免雷同（重要）：下面这些题最近刚练过，不要重复出，也不要只改一两个字；",
        "请换数字、换例子或换一个问法，但知识点保持不变。",
    ]
    lines += [f"- {stem}" for stem in stems]
    return "\n".join(lines)


def generate_question(subject, grade, knowledge, difficulty, qtype=CHOICE, ability=None,
                      history=()):
    """生成一道练习题。

    history：这个学生最近做过的题干（可选）。传了就会写进 prompt 做防雷同，
    生成后还会本地复核；命中重复就重新出，最多 MAX_GENERATION_ATTEMPTS 次。
    """
    qtype = BLANK if str(qtype).lower() == BLANK else CHOICE
    history = [str(item).strip() for item in (history or ()) if str(item).strip()]
    repeated = False
    data = None

    repeated = False
    need_image = False

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        data = _generate_once(subject, grade, knowledge, difficulty, qtype, ability,
                              history, attempt)
        if data.get("source") != "deepseek":
            repeated = False           # 兜底题不算雷同，不能把雷同文案挂在兜底题上
            break
        if data.get("needs_image"):
            need_image = True          # 系统不给题目配图：这一版换掉重出
            continue
        need_image = False
        if not history or not question_dedupe.is_duplicate(data.get("question"), history):
            repeated = False
            break
        repeated = True

    if data is None:
        data = dict(FALLBACK[qtype])
        data.update(source="fallback", error="出题失败，已使用内置练习题")
        return data

    if need_image:
        data = dict(FALLBACK[qtype])
        data.update(source="fallback", needs_image=False,
                    error="生成的题目需要配图才能作答，已换成内置的纯文字练习题")
        return data

    if repeated:
        data["repeated"] = True
        data["error"] = "生成的题目与最近练习过的原题雷同，已尽量更换但仍有相似"
    return data


def _generate_once(subject, grade, knowledge, difficulty, qtype, ability, history, attempt):
    """单次出题（第 attempt 次尝试，越往后越强调必须换题）。"""
    result = {
        "subject": subject,
        "grade": grade,
        "knowledge": knowledge,
        "difficulty": difficulty,
        "qtype": qtype,
        "source": "deepseek",
        "needs_image": False,
    }

    if not KEY:
        result.update(FALLBACK[qtype])
        result["source"] = "fallback"
        result["error"] = "未配置 DEEPSEEK_API_KEY，已使用内置兜底题"
        return result

    ability_text = ability_block(subject, ability)
    avoid_text = avoid_repeat_block(history)
    if attempt:
        avoid_text = (avoid_text + "\n" if avoid_text else "") + (
            "上一版题目和家长反馈的旧题太像了，这一版必须换一个数字、例子或问法。")
    prompt = f'''你是小学老师。

科目:{subject}
年级:{grade}
知识点:{knowledge}
难度:{difficulty}/100
{ability_text}
{avoid_text}

生成一道适合该学生的练习题。
{CHOICE_PROMPT if qtype == CHOICE else BLANK_PROMPT}
'''


    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(content)

        if not parsed or not parsed.get("question"):
            raise ValueError(f"模型返回无法解析: {content[:200]}")

        question_text = str(parsed["question"]).strip()
        needs_image = bool(parsed.get("needs_image"))
        answer = str(parsed.get("answer", "")).strip()
        analysis = str(parsed.get("analysis", "")).strip()

        if qtype == CHOICE:
            options = _clean_options(parsed.get("options"))

            # 模型偶尔把答案写成选项内容，这里反查回字母
            if answer.upper() not in options:
                matched = next((k for k, v in options.items() if v.strip() == answer), None)
                if matched:
                    answer = matched

            if len(options) < 2 or answer.upper() not in options:
                raise ValueError(f"选项或答案不合法: options={options} answer={answer}")

            result.update(
                question=question_text,
                options=options,
                answer=answer.upper(),
                acceptable=[],
                analysis=analysis,
                needs_image=needs_image,
            )
        else:
            if not answer:
                raise ValueError("填空题缺少答案")

            acceptable = parsed.get("acceptable_answers") or []
            if not isinstance(acceptable, (list, tuple)):
                acceptable = []

            result.update(
                question=question_text,
                options={},
                answer=answer,
                acceptable=[str(item).strip() for item in acceptable if str(item).strip()],
                analysis=analysis,
                needs_image=needs_image,
            )

        return result

    except Exception as exc:
        result.update(FALLBACK[qtype])
        result["qtype"] = qtype
        result["source"] = "fallback"
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return result



# ---------------- V2.3 AI 错因分析 ----------------

ERROR_ANALYSIS_PROMPT = """
只返回JSON，不要额外文字，格式：
{{"error_type":"错误类型","analysis":"为什么错","suggestion":"下一步该练什么"}}

硬性要求：
1. error_type 必须从这些里面选一个：{error_types}
2. analysis 要点出具体原因（例如"把减少理解成了增加"），不要只说"算错了"，也不要直接报答案
3. 用小学生能听懂的话说，一句话说清楚
4. suggestion 是给孩子的具体动作，一句话，20 字以内
"""


def analyze_error(payload):
    """V2.3：让模型分析孩子为什么错。

    返回 {"error_type", "analysis", "suggestion", "source"}；
    没配 key、网络异常、返回不合法时返回 None，由调用方回退到本地规则分析。
    """
    if not KEY:
        return None

    payload = payload or {}
    error_types = [str(item) for item in (payload.get("error_types") or [])]

    prompt = f'''你是小学{payload.get("subject", "")}老师，正在帮孩子分析错题。

题目：{payload.get("question", "")}
正确答案：{payload.get("correct_answer", "")}
孩子的答案：{payload.get("submitted", "")}
知识点：{payload.get("knowledge", "")}
难度：{payload.get("difficulty", 50)}/100
本地规则初判：{payload.get("rule_guess") or "不确定"}

请分析孩子为什么做错。
{ERROR_ANALYSIS_PROMPT.format(error_types="、".join(error_types) or "通用")}
'''

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(content)

        if not parsed:
            return None

        analysis = str(parsed.get("analysis", "")).strip()
        if not analysis:
            return None

        error_type = str(parsed.get("error_type", "")).strip()
        if error_types and error_type not in error_types:
            error_type = str(payload.get("rule_guess") or error_types[0])

        return {
            "error_type": error_type,
            "analysis": analysis,
            "suggestion": str(parsed.get("suggestion", "")).strip(),
            "source": "ai",
        }

    except Exception:
        return None


# ---------------- V2.4 间隔复习题 ----------------

REVIEW_PROMPT = """
只返回JSON，不要额外文字，格式：
{{"question":"题目","options":{{"A":"选项A内容","B":"选项B内容","C":"选项C内容","D":"选项D内容"}},"answer":"正确选项字母","analysis":"解析"}}

硬性要求：
1. **不要重复历史原题**：必须更换数字、情境或表达方式（例如 36×24 → 42×18，
   或者把算式变成一个生活中的问题）。
2. 保持同一个知识核心，知识点不变。
3. 难度接近学生当前水平，不要明显超纲。
4. 不要在题目里提示答案，也不要说"和上次那道题一样"。
5. 4 个选项互不相同，answer 只能是 A/B/C/D。
"""

REVIEW_MODE_TEXT = {
    "same": "换一道同知识点的题（换数字）",
    "variant": "变式题（换表达方式或情境）",
    "transfer": "迁移题（结合前后知识点，换一个新情境）",
}


def generate_review_question(subject, grade, knowledge, difficulty, mastery=None,
                             maturity_level="", days_since_review=0, error_history="",
                             history=(), mode="variant", qtype=CHOICE):
    """V2.4：生成一道**间隔复习题**（不重复历史原题，考迁移不考背答案）。

    没配 Key、网络异常或返回不合法时返回 None，由调用方回退到本地题库/变式题。
    """
    if not KEY:
        return None

    qtype = BLANK if str(qtype).lower() == BLANK else CHOICE
    history = list(history or [])[:5]
    history_text = "\n".join(f"- {str(item).strip()}" for item in history if str(item).strip())
    if not history_text:
        history_text = "（这个知识点还没有历史题目）"

    prompt = f'''你是小学{subject}老师，正在给孩子出**复习题**。

间隔复习的目的是"确认还记得、能迁移"，不是"记住原来那道题的答案"。

学生：{grade}
科目：{subject}
知识点：{knowledge}
掌握度：{mastery if mastery is not None else "未知"}
成熟阶段：{maturity_level or "未知"}
距离上次复习：{days_since_review} 天
历史错误：{error_history or "暂无记录"}
本次目标：检测是否仍然掌握
题型要求：{REVIEW_MODE_TEXT.get(str(mode), REVIEW_MODE_TEXT["variant"])}
难度：{difficulty}/100

历史原题（**不要重复、不要只改一两个字**）：
{history_text}

{CHOICE_PROMPT if qtype == CHOICE else BLANK_PROMPT}
{REVIEW_PROMPT}
'''

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(content)

        if not parsed or not parsed.get("question"):
            return None

        question_text = str(parsed["question"]).strip()
        answer = str(parsed.get("answer", "")).strip()
        analysis = str(parsed.get("analysis", "")).strip()

        if parsed.get("needs_image"):
            return None                # 需要配图的题不要：调用方会退回本地题库

        if qtype == CHOICE:
            options = _clean_options(parsed.get("options"))
            if answer.upper() not in options:
                matched = next((k for k, v in options.items() if v.strip() == answer), None)
                if matched:
                    answer = matched
            if len(options) < 2 or answer.upper() not in options:
                return None

            return {
                "qtype": CHOICE,
                "question": question_text,
                "options": options,
                "answer": answer.upper(),
                "acceptable": [],
                "analysis": analysis,
                "source": "deepseek_review",
                "mode": mode,
            }

        if not answer:
            return None

        acceptable = parsed.get("acceptable_answers") or []
        if not isinstance(acceptable, (list, tuple)):
            acceptable = []

        return {
            "qtype": BLANK,
            "question": question_text,
            "options": {},
            "answer": answer,
            "acceptable": [str(item).strip() for item in acceptable if str(item).strip()],
            "analysis": analysis,
            "source": "deepseek_review",
            "mode": mode,
        }

    except Exception:
        return None


# ==============================================================
# V2.7 迁移题生成（深度学习层）
# ==============================================================

TRANSFER_LEVEL_TEXT = {
    0: "原题/近原题（和刚学的那道完全一样）",
    1: "数字变化（只换数字，方法不变）",
    2: "语言表达变化（换一种说法，意思不变）",
    3: "情境变化（换一个生活场景）",
    4: "结构变化（信息顺序或问题形式变了）",
    5: "综合迁移（数字、情境、结构一起变）",
}

TRANSFER_PROMPT = """
只返回JSON，不要额外文字，格式：
{{"question":"题目","options":{{"A":"选项A内容","B":"选项B内容","C":"选项C内容","D":"选项D内容"}},"answer":"正确选项字母","analysis":"解析"}}

迁移题的硬性要求：
1. **知识目标绝对不能变**：考的还是同一个知识点，不能变成别的知识点。
2. **必须与给出的原题有真实变化**，变化方式必须严格对应要求的目标迁移等级。
3. **不许超纲**：只能用该年级该知识点范围内的方法和数字。
4. 题目必须**自洽且只有一个正确答案**，答案能由题目条件唯一推出。
5. 不要在题目里出现"和刚才那道一样""换个数字"之类的话。
6. 4 个选项互不相同，answer 只能是 A/B/C/D；错误选项必须是常见错误，不能是乱写的数。
7. 解析用小学生能听懂的话说明为什么。
"""


def generate_transfer_question(subject, grade, knowledge, difficulty, target_level,
                               ability=None, deep_mastery=None, base_question="",
                               avoid=(), qtype=CHOICE):
    """V2.7：生成一道**迁移题**（需求 §三十五）。

    输入：grade / subject / knowledge / ability_stage / deep_mastery / target_transfer_level。
    要求：不超纲、知识目标不变、与原题有真实变化。

    未配置 Key、网络异常、返回不合法时返回 None —— 由 transfer_engine 降级到本地题库，
    **绝不能因为 AI 失败而阻塞学习**（需求 §三十七）。
    """
    if not KEY:
        return None

    try:
        target = int(target_level)
    except (TypeError, ValueError):
        target = 1
    target = max(0, min(5, target))

    qtype = BLANK if str(qtype).lower() == BLANK else CHOICE
    avoid = [str(item).strip() for item in (avoid or ()) if str(item).strip()][:5]
    avoid_text = "\n".join(f"- {item}" for item in avoid) or "（没有需要避开的历史题目）"

    if not deep_mastery:
        try:
            from deep_learning import deep_mastery as deep_mastery_module
            deep_mastery = deep_mastery_module.LEVEL_BY_KEY.get(
                str(deep_mastery or "").upper(), {}).get("desc", "")
        except Exception:
            deep_mastery = ""

    prompt = f'''你是小学{subject}老师，正在给孩子出一道**迁移题**，用来判断他是"真会了"还是"只记住了原题"。

年级：{grade}
科目：{subject}
知识点（**必须保持不变**）：{knowledge}
学生当前能力阶段：{ability or "未知"}
深度学习程度：{deep_mastery or "未知"}
难度：{difficulty}/100
本次目标迁移等级：T{target} —— {TRANSFER_LEVEL_TEXT.get(target, "")}

原题（**不能照抄，必须按上面的迁移等级做真实变化**）：
{base_question or "（没有原题，请按知识点自己出一道标准难度题）"}

最近做过的题目（**不要与它们雷同**）：
{avoid_text}

{CHOICE_PROMPT if qtype == CHOICE else BLANK_PROMPT}
{TRANSFER_PROMPT}
'''

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(content)

        if not parsed or not parsed.get("question"):
            return None

        question_text = str(parsed["question"]).strip()
        answer = str(parsed.get("answer", "")).strip()
        analysis = str(parsed.get("analysis", "")).strip()

        if parsed.get("needs_image"):
            return None                # 需要配图的题不要，免得孩子看到一道无图可看的题

        if question_text in set(avoid):
            return None

        if qtype == CHOICE:
            options = _clean_options(parsed.get("options"))
            if answer.upper() not in options:
                matched = next((k for k, v in options.items() if v.strip() == answer), None)
                if matched:
                    answer = matched
            if len(options) < 2 or answer.upper() not in options:
                return None

            return {
                "qtype": CHOICE,
                "subject": subject,
                "grade": grade,
                "knowledge": knowledge,
                "difficulty": difficulty,
                "question": question_text,
                "options": options,
                "answer": answer.upper(),
                "acceptable": [],
                "analysis": analysis,
                "source": "deepseek_transfer",
                "transfer_level": target,
            }

        if not answer:
            return None

        acceptable = parsed.get("acceptable_answers") or []
        if not isinstance(acceptable, (list, tuple)):
            acceptable = []

        return {
            "qtype": BLANK,
            "subject": subject,
            "grade": grade,
            "knowledge": knowledge,
            "difficulty": difficulty,
            "question": question_text,
            "options": {},
            "answer": answer,
            "acceptable": [str(item).strip() for item in acceptable if str(item).strip()],
            "analysis": analysis,
            "source": "deepseek_transfer",
            "transfer_level": target,
        }

    except Exception:
        return None


# ==============================================================
# V2.7 解释评价辅助（需求 §三十六）
# ==============================================================

EXPLANATION_PROMPT = """
只返回JSON，不要额外文字，格式：
{{"core_concept_correct":true,"concept_coverage":0.5,"missing_concepts":["缺少的概念"],"possible_misconceptions":["可能的错误理解"],"quality_score":70,"feedback":"鼓励孩子的一句话"}}

评价铁律（必须遵守）：
1. **只看概念对不对**，绝对不要因为孩子表达不完整、语法不好、说话颠三倒四就判定理解错误。
2. concept_coverage 是 0~1 的小数，表示说到的核心概念占比。
3. missing_concepts 只列出**孩子没说到的核心概念**，不要列表达问题。
4. 只有在孩子**明确说出了错误的理解**时才填 possible_misconceptions，否则给空数组。
5. feedback 是给小学生看的，温暖、短、具体，不批评，不出现分数和等级。
"""


def evaluate_explanation(subject, grade, knowledge, question="", expected_concepts=None,
                         student_explanation=""):
    """V2.7：AI 解释评价辅助（需求 §三十六）。

    **AI 不得直接修改 mastery**：本函数只返回结构化评价，由 ExplanationEngine 校验后
    形成 LearningEvidence，再由 DeepMasteryEngine 更新状态。

    未配置 Key / 异常 / 返回不合法时一律返回 None（需求 §三十七：解释可以暂不评分）。
    """
    if not KEY:
        return None

    text = str(student_explanation or "").strip()
    if not text:
        return {"core_concept_correct": False, "concept_coverage": 0.0,
                "missing_concepts": [], "possible_misconceptions": ["没有说出解释"],
                "quality_score": 0, "feedback": "没关系，想到什么就说什么，菲比等你。"}

    concepts = []
    for item in (expected_concepts or ()):
        if isinstance(item, dict):
            concepts.append(str(item.get("concept") or item.get("name") or "").strip())
        else:
            concepts.append(str(item or "").strip())
    concepts = [item for item in concepts if item]
    concept_text = "、".join(concepts) or "（没有给定，请你自己根据知识点判断核心概念）"

    prompt = f'''你是小学{subject}老师，正在看{grade}年级孩子对一道题的**口头解释**。

知识点：{knowledge}
题目：{question or "（没有具体题目，请按知识点判断）"}
核心概念（孩子应该说到这些）：{concept_text}

孩子说的话：
"""
{text}
"""

{EXPLANATION_PROMPT}
'''

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        parsed = _extract_json(response.json()["choices"][0]["message"]["content"])
        if not parsed:
            return None

        def _list_of(key):
            raw = parsed.get(key) or []
            if isinstance(raw, str):
                raw = [raw]
            if not isinstance(raw, (list, tuple)):
                return []
            return [str(item).strip() for item in raw if str(item).strip()]

        try:
            coverage = float(parsed.get("concept_coverage"))
        except (TypeError, ValueError):
            coverage = 1.0 if parsed.get("core_concept_correct") else 0.0
        try:
            score = int(round(float(parsed.get("quality_score"))))
        except (TypeError, ValueError):
            score = int(round(max(0.0, min(1.0, coverage)) * 100))

        return {
            "core_concept_correct": bool(parsed.get("core_concept_correct")),
            "concept_coverage": round(max(0.0, min(1.0, coverage)), 3),
            "missing_concepts": _list_of("missing_concepts"),
            "possible_misconceptions": _list_of("possible_misconceptions"),
            "quality_score": int(max(0, min(100, score))),
            "feedback": str(parsed.get("feedback") or "").strip(),
            "source": "deepseek_explanation",
        }

    except Exception:
        return None


# ==============================================================
# V2.7 错误根因辅助（需求 §三十四）
# ==============================================================

ROOT_CAUSE_PROMPT = """
只返回JSON，不要额外文字，格式：
{{"root_cause_type":"CONCEPT_GAP","root_cause_confidence":0.6,"analysis":"一句话说明","related_knowledge_ids":["相关知识点名"],"recommended_action":"下一步怎么做"}}

判断要求：
1. root_cause_type 只能从给定候选里选一个。
2. root_cause_confidence 是 0~1 的小数，不确定就给低分，不要硬猜。
3. analysis 用家长能看懂的一句话说明**为什么错**，不要重复"做错了"。
4. recommended_action 要具体、可在 5 分钟内完成，不要写"多练习"这种空话。
5. 只依据给定证据判断，不要编造孩子没说过的表现。
"""


def analyze_root_cause(subject="数学", knowledge="", question="", student_answer="",
                       correct_answer="", error_type="", recent_history="",
                       mastery_score=None, memory_state=None, prerequisite_state=None,
                       response_time=0, hint_usage=0, confidence="", candidates=()):
    """V2.7：AI 错误根因**辅助**（需求 §三十四 / §三十七）。

    核心判断不能完全依赖 AI：规则、历史数据、知识图谱优先，本函数只作为补充。
    未配置 Key / 异常时返回 None。
    """
    if not KEY:
        return None

    candidate_text = "、".join(str(item) for item in (candidates or ())) or "（不限，请按学科常识判断）"
    memory_text = memory_state if isinstance(memory_state, str) else (
        str(memory_state) if memory_state else "未知")
    prerequisite_text = prerequisite_state if isinstance(prerequisite_state, str) else (
        str(prerequisite_state) if prerequisite_state else "未知")

    prompt = f'''你是小学{subject}老师，正在分析一个孩子**为什么错**。

知识点：{knowledge}
题目：{question}
孩子的答案：{student_answer}
正确答案：{correct_answer}
系统初步错因标签：{error_type or "无"}
近期答题记录：{recent_history or "无"}
掌握度：{mastery_score if mastery_score is not None else "未知"}
记忆状态：{memory_text}
前置知识情况：{prerequisite_text}
答题用时（秒）：{response_time}
提示使用次数：{hint_usage}
孩子的自信度：{confidence or "未采集"}

可选根因类型（只能选一个）：{candidate_text}

{ROOT_CAUSE_PROMPT}
'''

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        parsed = _extract_json(response.json()["choices"][0]["message"]["content"])
        if not parsed or not parsed.get("root_cause_type"):
            return None

        related = parsed.get("related_knowledge_ids") or []
        if isinstance(related, str):
            related = [related]
        if not isinstance(related, (list, tuple)):
            related = []

        try:
            conf = float(parsed.get("root_cause_confidence"))
        except (TypeError, ValueError):
            conf = 0.5

        return {
            "root_cause_type": str(parsed["root_cause_type"]).strip(),
            "root_cause_confidence": round(max(0.0, min(1.0, conf)), 2),
            "analysis": str(parsed.get("analysis") or "").strip(),
            "related_knowledge_ids": [str(item).strip() for item in related if str(item).strip()],
            "recommended_action": str(parsed.get("recommended_action") or "").strip(),
            "source": "deepseek_root_cause",
        }

    except Exception:
        return None
