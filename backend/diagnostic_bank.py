# ==============================================================
# 能力契约｜数学诊断题库（程序化生成）+ 语文/英语取题库入口
# 入口：build_question / bank_size
# 依赖：random math stages bank_chinese bank_english
# 不负责：日常练习出题 → deepseek.py / main.question
# 验证：python backend/verify_diagnostic.py
# 被调用：diagnostic_routes.py、review/selector.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.0 诊断题库：按能力阶段出题（数学参数化生成 + 语文/英语固定题库）。

为什么诊断用本地题库而不是直接问 DeepSeek：
诊断要求每一组题**严格落在被测阶段**，否则"答对/答错"就无法解释成能力信号。
本地题库能做到难度可控、离线可跑、结果可复现；DeepSeek 仍然保留在常规练习
和可选的高阶出题路径上（见 deepseek.build_prompt 的能力上下文）。

对外只暴露 build_question()：
    build_question("数学", "3.2") -> {
        "question": "...", "options": {"A": ...}, "answer": "B",
        "acceptable": [], "analysis": "...",
        "knowledge": "两位数除法", "stage": "3.2", "source": "bank",
    }
"""

import random
from math import gcd

import stages

# 语文 / 英语题库由独立数据文件提供；缺失或损坏时不影响系统启动
try:
    from bank_chinese import QUESTION_BANK as CHINESE_BANK
except Exception:                                  # pragma: no cover - 数据文件缺失时的兜底
    CHINESE_BANK = {}

try:
    from bank_english import QUESTION_BANK as ENGLISH_BANK
except Exception:                                  # pragma: no cover
    ENGLISH_BANK = {}

BANKS = {"语文": CHINESE_BANK, "英语": ENGLISH_BANK}

LETTERS = ("A", "B", "C", "D")


# ---------------- 选项组装 ----------------

def _same_value(left, right):
    """数值等价的选项算重复：1.0 与 1.00、8 与 8.0 对小学生就是同一个答案。"""
    if left == right:
        return True
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _clean_options(answer, wrongs):
    """把正确答案 + 干扰项整理成互不相同的 4 个文本选项；凑不齐返回 None。"""
    answer = str(answer)
    options = [answer]

    for value in wrongs or ():
        text = str(value)
        if not text or any(_same_value(text, item) for item in options):
            continue
        options.append(text)
        if len(options) == 4:
            return options

    return options if len(options) == 4 else None


def _pack(stage, subject, stem, answer, wrongs, analysis):
    """(题干, 正确答案, 干扰项, 解析) → 可直接下发的题目 dict。"""
    options = _clean_options(answer, wrongs)
    if options is None:
        return None

    shuffled = options[:]
    random.shuffle(shuffled)

    letters = {}
    correct_letter = "A"
    for letter, text in zip(LETTERS, shuffled):
        letters[letter] = text
        if text == str(answer):
            correct_letter = letter

    return {
        "qtype": "choice",
        "question": stem,
        "options": letters,
        "answer": correct_letter,
        "answer_text": str(answer),
        "acceptable": [],
        "analysis": analysis,
        "knowledge": stages.knowledge_of(subject, stage),
        "stage": stage,
        "difficulty": stages.difficulty_of(stage),
        "source": "bank",
    }


# ---------------- 数学：旧 24 个大知识点的题目生成器（细分阶段用 legacy_key 兜底） ----------------

def _frac(num, den):
    """分数约分后的可读写法；能整除时返回整数。"""
    if den < 0:
        num, den = -num, -den
    g = gcd(abs(num), abs(den)) or 1
    num, den = num // g, den // g
    return str(num) if den == 1 else f"{num}/{den}"


def _m_1_1():
    """20以内加减法。"""
    if random.random() < 0.5:
        a = random.randint(2, 15)
        b = random.randint(1, 20 - a)
        ans = a + b
        return (f"算一算：{a} + {b} = ？", ans, [ans + 1, ans - 1, ans + 10],
                f"{a} 和 {b} 合起来是 {ans}。")
    a = random.randint(6, 20)
    b = random.randint(1, a - 1)
    ans = a - b
    return (f"算一算：{a} - {b} = ？", ans, [ans + 1, ans - 1, a + b],
            f"{a} 去掉 {b}，还剩 {ans}。")


def _m_1_2():
    """100以内加减法。"""
    if random.random() < 0.5:
        a = random.randint(20, 60)
        b = random.randint(10, 99 - a)
        ans = a + b
        return (f"算一算：{a} + {b} = ？", ans, [ans + 10, ans - 1, ans + 1],
                f"个位加个位、十位加十位：{a} + {b} = {ans}。")
    a = random.randint(35, 99)
    b = random.randint(10, a - 10)
    ans = a - b
    return (f"算一算：{a} - {b} = ？", ans, [ans + 10, ans - 10, ans + 1],
            f"{a} 减 {b} 等于 {ans}，注意退位。")


def _m_1_3():
    """连加连减与加减混合。"""
    a = random.randint(5, 30)
    b = random.randint(3, 20)
    c = random.randint(2, a + b - 1)
    ans = a + b - c
    return (f"算一算：{a} + {b} - {c} = ？", ans, [ans + 2, ans - 2, a + b + c],
            f"先算 {a} + {b} = {a + b}，再算 {a + b} - {c} = {ans}。")


_1_4_APPS = (
    ("小明有 {a} 个苹果，妈妈又给了他 {b} 个，现在一共有多少个苹果？", "个"),
    ("树上有 {a} 只小鸟，飞走了 {b} 只，树上还剩多少只小鸟？", "只"),
    ("小红做了 {a} 朵花，小兰做了 {b} 朵花，两人一共做了多少朵花？", "朵"),
)


def _m_1_4():
    """认识图形与简单应用。"""
    if random.random() < 0.35:
        shape, sides = random.choice((("三角形", 3), ("正方形", 4), ("长方形", 4), ("五边形", 5)))
        return (f"一个{shape}有几条边？", sides, [sides + 1, sides - 1, sides + 2],
                f"{shape}有 {sides} 条边。")

    template, unit = random.choice(_1_4_APPS)
    a = random.randint(3, 18)
    b = random.randint(2, 9)
    if "飞走" in template and b >= a:
        b = a - 1

    if "飞走" in template:
        ans = a - b
        wrongs = [ans + 1, ans - 1, a + b]
    else:
        ans = a + b
        wrongs = [ans + 1, ans - 1, ans + 2]

    stem = template.format(a=a, b=b)
    return (stem, ans, wrongs, f"列式：{a} {'-' if '飞走' in template else '+'} {b} = {ans}（{unit}）。")


def _m_2_1():
    """表内乘法。"""
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    ans = a * b
    return (f"算一算：{a} × {b} = ？", ans, [ans + a, ans - b, ans + b],
            f"用乘法口诀：{min(a, b)} 乘 {max(a, b)} 得 {ans}。")


def _m_2_2():
    """表内除法。"""
    b = random.randint(2, 9)
    ans = random.randint(2, 9)
    total = b * ans
    return (f"算一算：{total} ÷ {b} = ？", ans, [ans + 1, ans - 1, ans + 2],
            f"因为 {b} × {ans} = {total}，所以 {total} ÷ {b} = {ans}。")


def _m_2_3():
    """两步计算应用题。"""
    a = random.randint(3, 9)
    b = random.randint(2, 9)
    c = random.randint(2, 5)
    kind = random.random()
    if kind < 0.5:
        ans = a * b + c
        stem = f"每盒有 {a} 个乒乓球，买了 {b} 盒，又另外买了 {c} 个，一共有多少个乒乓球？"
        analysis = f"先算 {a} × {b} = {a * b}，再加 {c} 得 {ans}。"
        wrongs = [a * b, (a + b) * c, ans - 1]
    else:
        ans = a * b - c
        stem = f"每盒有 {a} 个鸡蛋，一共 {b} 盒，吃掉 {c} 个后还剩多少个鸡蛋？"
        analysis = f"先算 {a} × {b} = {a * b}，再减 {c} 得 {ans}。"
        wrongs = [a * b, a * b + c, ans + 1]
    return (stem, ans, wrongs, analysis)


_2_4_UNITS = (
    ("1米 = 多少厘米？", 100, [10, 1000, 50]),
    ("1千米 = 多少米？", 1000, [100, 10000, 500]),
    ("1分米 = 多少厘米？", 10, [100, 1000, 20]),
    ("1厘米 = 多少毫米？", 10, [100, 1000, 5]),
)


def _m_2_4():
    """长度单位与测量。"""
    if random.random() < 0.5:
        stem, ans, wrongs = random.choice(_2_4_UNITS)
        return (stem, ans, wrongs, "相邻常用长度单位之间是 10 倍关系，米和厘米之间是 100 倍。")

    a = random.randint(2, 9)
    b = random.randint(2, 9)
    ans = (a + b) * 10
    return (f"一根绳子长 {a} 分米，另一根长 {b} 分米，两根接起来一共长多少厘米？", ans,
            [a + b, ans + 10, ans - 10],
            f"先算 {a} + {b} = {a + b} 分米，1分米=10厘米，所以是 {ans} 厘米。")


def _m_3_1():
    """多位数乘一位数。"""
    a = random.randint(12, 89)
    b = random.randint(2, 9)
    ans = a * b
    return (f"算一算：{a} × {b} = ？", ans, [ans + 10, ans - b, ans + a],
            f"先算 {a // 10 * 10} × {b} = {a // 10 * 10 * b}，再算 {a % 10} × {b} = {a % 10 * b}，合起来是 {ans}。")


def _m_3_2():
    """两位数除法。"""
    b = random.randint(2, 9)
    ans = random.randint(3, 9)
    total = b * ans
    return (f"算一算：{total} ÷ {b} = ？", ans, [ans + 1, ans - 1, ans + 10],
            f"{b} × {ans} = {total}，所以 {total} ÷ {b} = {ans}。")


def _m_3_3():
    """分数初步认识。"""
    den = random.randint(4, 9)
    a = random.randint(1, den - 2)
    b = random.randint(1, den - a)
    ans = _frac(a + b, den)
    return (f"算一算：{a}/{den} + {b}/{den} = ？", ans,
            [_frac(a + b, den * 2), _frac(a * b, den), _frac(a + b + 1, den)],
            f"同分母分数相加，分母不变、分子相加：{a}+{b}={a + b}，所以是 {a + b}/{den}。")


def _m_3_4():
    """长方形与正方形的周长。"""
    if random.random() < 0.5:
        a = random.randint(3, 15)
        ans = 4 * a
        return (f"一个正方形的边长是 {a} 厘米，它的周长是多少厘米？", f"{ans}厘米",
                [f"{a * a}厘米", f"{2 * a}厘米", f"{ans + 4}厘米"],
                f"正方形周长 = 边长 × 4 = {a} × 4 = {ans} 厘米。")
    a = random.randint(3, 15)
    b = random.randint(2, a - 1)
    ans = 2 * (a + b)
    return (f"一个长方形的长是 {a} 厘米，宽是 {b} 厘米，它的周长是多少厘米？", f"{ans}厘米",
            [f"{a * b}厘米", f"{a + b}厘米", f"{ans + 2}厘米"],
            f"长方形周长 = (长 + 宽) × 2 = ({a} + {b}) × 2 = {ans} 厘米。")


def _m_4_1():
    """大数认识与四则运算。"""
    if random.random() < 0.5:
        a = random.randint(100, 999)
        b = random.randint(11, 99)
        ans = a * b
        return (f"算一算：{a} × {b} = ？", ans, [ans // 10, ans + a, ans - b],
                f"把 {b} 拆成 {b // 10 * 10} 和 {b % 10} 分别去乘 {a}，再把结果相加得 {ans}。")
    number = random.randint(10000, 99999)
    digits = str(number)
    return (f"{number} 这个数中，万位上的数字是几？", digits[0],
            [digits[1], digits[2], digits[4]],
            f"从右往左依次是个、十、百、千、万位，万位上是 {digits[0]}。")


def _m_4_2():
    """运算定律与简便计算。"""
    a = random.randint(2, 9)
    ans = 25 * 4 * a
    return (f"用简便方法算一算：25 × {a} × 4 = ？", ans, [100 * a + 100, ans // 4, ans + 25],
            f"先算 25 × 4 = 100，再算 100 × {a} = {ans}。")


def _m_4_3():
    """小数的意义与加减法。"""
    a = round(random.uniform(1, 20), 2)
    b = round(random.uniform(0.5, 9), 2)
    ans = round(a + b, 2)
    text = f"{ans:.2f}"
    return (f"算一算：{a:.2f} + {b:.2f} = ？", text,
            [f"{ans + 0.1:.2f}", f"{ans - 0.1:.2f}", f"{a * b:.2f}"],
            f"小数点对齐，相同数位相加：{a:.2f} + {b:.2f} = {text}。")


def _m_4_4():
    """平行四边形与梯形面积。"""
    if random.random() < 0.5:
        base = random.randint(4, 15)
        height = random.randint(3, 12)
        ans = base * height
        return (f"一个平行四边形的底是 {base} 厘米，高是 {height} 厘米，面积是多少平方厘米？",
                f"{ans}平方厘米", [f"{base + height}平方厘米", f"{ans // 2}平方厘米", f"{ans + base}平方厘米"],
                f"平行四边形面积 = 底 × 高 = {base} × {height} = {ans} 平方厘米。")
    a = random.randint(3, 10)
    b = random.randint(3, 10)
    height = random.randint(2, 8)
    if (a + b) % 2:                       # 保证"×高÷2"是整数，避免面积出现小数
        height = height * 2 if height * 2 <= 16 else height + 1
    ans = (a + b) * height // 2
    return (f"一个梯形的上底是 {a} 厘米，下底是 {b} 厘米，高是 {height} 厘米，面积是多少平方厘米？",
            f"{ans}平方厘米", [f"{(a + b) * height}平方厘米", f"{(a + b) * height // 2 + a}平方厘米", f"{a * b}平方厘米"],
            f"梯形面积 = (上底 + 下底) × 高 ÷ 2 = ({a} + {b}) × {height} ÷ 2 = {ans} 平方厘米。")


def _m_5_1():
    """小数乘除法。"""
    a = round(random.uniform(1, 9), 1)
    b = random.randint(2, 9)
    if random.random() < 0.5:
        ans = round(a * b, 2)
        return (f"算一算：{a} × {b} = ？", f"{ans:g}",
                [f"{ans * 10:g}", f"{ans / 10:g}", f"{a + b:g}"],
                f"先按整数乘法算 {int(a * 10)} × {b} = {int(a * 10) * b}，再点上小数点得 {ans:g}。")
    ans = round(a / b, 2)
    return (f"算一算：{a} ÷ {b} = ？（除不尽时保留两位小数）", f"{ans:.2f}",
            [f"{ans * 10:.2f}", f"{a * b:.2f}", f"{round(a / b, 1):.1f}"],
            f"{a} ÷ {b} ≈ {ans:.2f}。")


def _m_5_2():
    """简易方程。"""
    a = random.randint(2, 9)
    x = random.randint(2, 12)
    b = random.randint(1, 20)
    c = a * x + b
    return (f"解方程：{a}x + {b} = {c}，x 等于多少？", x,
            [x + 1, c - b, (c - b) // (a + 1) or 1],
            f"两边先减去 {b} 得 {a}x = {c - b}，再除以 {a} 得 x = {x}。")


def _m_5_3():
    """因数与倍数。"""
    if random.random() < 0.5:
        a = random.randint(4, 24)
        b = random.randint(4, 24)
        ans = gcd(a, b)
        return (f"{a} 和 {b} 的最大公因数是多少？", ans, [ans * 2, ans + 1, a * b, ans + 3],
                f"{a} 和 {b} 都能被 {ans} 整除，且没有更大的公因数。")

    # 重抽到"互不整除且不相等"为止：否则最小公倍数正好等于较大的那个数，
    # 干扰项会和正确答案撞成同一个值，凑不出 4 个选项
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    while a == b or max(a, b) % min(a, b) == 0:
        a = random.randint(2, 9)
        b = random.randint(2, 9)

    ans = a * b // gcd(a, b)
    return (f"{a} 和 {b} 的最小公倍数是多少？", ans, [max(a, b), a * b + 1, ans + a, ans * 2],
            f"{a} 和 {b} 的最小公倍数是 {ans}。")


def _m_5_4():
    """多边形面积与组合图形。"""
    if random.random() < 0.5:
        base = random.randint(4, 16)
        height = random.randint(2, 12)
        area = base * height
        ans = area // 2 if area % 2 == 0 else f"{area / 2:g}"
        return (f"一个三角形的底是 {base} 厘米，高是 {height} 厘米，面积是多少平方厘米？",
                f"{ans}平方厘米", [f"{area}平方厘米", f"{base + height}平方厘米", f"{ans}平方分米"],
                f"三角形面积 = 底 × 高 ÷ 2 = {base} × {height} ÷ 2 = {ans} 平方厘米。")
    r = random.randint(2, 9)
    ans = r * r
    return (f"一个正方形的边长是 {r} 厘米，它的面积是多少平方厘米？", f"{ans}平方厘米",
            [f"{4 * r}平方厘米", f"{2 * r}平方厘米", f"{ans + r}平方厘米"],
            f"正方形面积 = 边长 × 边长 = {r} × {r} = {ans} 平方厘米。")


def _m_6_1():
    """分数乘除法。"""
    a, b = random.randint(1, 5), random.randint(2, 6)
    c, d = random.randint(1, 5), random.randint(2, 6)
    if a >= b:
        a = b - 1
    if c >= d:
        c = d - 1
    if random.random() < 0.5:
        ans = _frac(a * c, b * d)
        return (f"算一算：{a}/{b} × {c}/{d} = ？", ans,
                [_frac(a + c, b + d), _frac(a * d, b * c), _frac(a * c + 1, b * d)],
                f"分数相乘：分子乘分子、分母乘分母，得 {a * c}/{b * d}，约分后是 {ans}。")
    ans = _frac(a * d, b * c)
    return (f"算一算：{a}/{b} ÷ {c}/{d} = ？", ans,
            [_frac(a * c, b * d), _frac(b * c, a * d), _frac(a * d + 1, b * c)],
            f"除以一个分数等于乘它的倒数：{a}/{b} × {d}/{c} = {ans}。")


def _m_6_2():
    """比与比例。"""
    if random.random() < 0.5:
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        while b == a:                     # a:b 与 b:a 相同会让干扰项变成答案
            b = random.randint(2, 9)

        g = gcd(a, b)
        ans = f"{a // g}:{b // g}"
        return (f"把比 {a}:{b} 化成最简整数比是多少？", ans,
                [f"{a}:{b}", f"{b // g}:{a // g}", f"{a * 2 // g}:{b * 2 // g}", f"{a + 1}:{b + 1}"],
                f"{a} 和 {b} 的最大公因数是 {g}，前后项同时除以 {g} 得 {ans}。")

    x = random.randint(2, 12)
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    while b == a:                         # a = b 时 a×x 会等于正确答案
        b = random.randint(2, 9)

    return (f"解比例：{a}:{b} = {a * x}:？，？处应填多少？", b * x,
            [b + x, a * x, b * x + b, b * x - b],
            f"内项之积等于外项之积：{a} × ? = {b} × {a * x}，所以 ? = {b * x}。")


def _m_6_3():
    """圆的周长与面积。"""
    r = random.randint(2, 10)
    if random.random() < 0.5:
        ans = round(2 * 3.14 * r, 2)
        return (f"一个圆的半径是 {r} 厘米，它的周长是多少厘米？（π 取 3.14）", f"{ans:g}厘米",
                [f"{round(3.14 * r * r, 2):g}厘米", f"{round(3.14 * r, 2):g}厘米", f"{round(3.14 * r * 3, 2):g}厘米"],
                f"圆的周长 = 2πr = 2 × 3.14 × {r} = {ans:g} 厘米。")
    ans = round(3.14 * r * r, 2)
    return (f"一个圆的半径是 {r} 厘米，它的面积是多少平方厘米？（π 取 3.14）", f"{ans:g}平方厘米",
            [f"{round(2 * 3.14 * r, 2):g}平方厘米", f"{round(3.14 * r, 2):g}平方厘米", f"{round(3.14 * r * r * 2, 2):g}平方厘米"],
            f"圆的面积 = πr² = 3.14 × {r} × {r} = {ans:g} 平方厘米。")


def _m_6_4():
    """百分数与统计。"""
    kind = random.random()
    if kind < 0.5:
        price = random.choice([40, 50, 80, 120, 200])
        rate = random.choice([10, 20, 25, 50])
        ans = price * (100 - rate) / 100
        return (f"一件商品原价 {price} 元，现在按原价的 {100 - rate}% 出售，价格是多少元？",
                f"{ans:g}元", [f"{price * rate / 100:g}元", f"{price - rate:g}元", f"{ans + 10:g}元"],
                f"求一个数的百分之几用乘法：{price} × {100 - rate}% = {ans:g} 元。")
    values = [random.randint(60, 100) for _ in range(4)]
    total = sum(values)
    ans = round(total / len(values), 1)
    return (f"小明四次数学成绩分别是 {'、'.join(str(v) for v in values)} 分，平均分是多少？",
            f"{ans:g}分", [f"{total:g}分", f"{ans + 1:g}分", f"{ans - 2:g}分"],
            f"平均数 = 总数 ÷ 个数 = {total} ÷ 4 = {ans:g} 分。")


MATH_MAKERS = {
    "1.1": _m_1_1, "1.2": _m_1_2, "1.3": _m_1_3, "1.4": _m_1_4,
    "2.1": _m_2_1, "2.2": _m_2_2, "2.3": _m_2_3, "2.4": _m_2_4,
    "3.1": _m_3_1, "3.2": _m_3_2, "3.3": _m_3_3, "3.4": _m_3_4,
    "4.1": _m_4_1, "4.2": _m_4_2, "4.3": _m_4_3, "4.4": _m_4_4,
    "5.1": _m_5_1, "5.2": _m_5_2, "5.3": _m_5_3, "5.4": _m_5_4,
    "6.1": _m_6_1, "6.2": _m_6_2, "6.3": _m_6_3, "6.4": _m_6_4,
}


# ---------------- 统一出题入口 ----------------

def _math_maker(key):
    """数学阶段 → 生成器；细分阶段还没有自己的生成器时，用旧键（大知识点）的。"""
    maker = MATH_MAKERS.get(key)
    if maker is None:
        maker = MATH_MAKERS.get(stages.legacy_key(key))
    return maker


def _bank_pool(subject, key):
    """科目题库池；细分阶段还没有自己的题时，用大知识点的题库兜底。"""
    bank = BANKS.get(subject) or {}
    pool = bank.get(key) or []
    if not pool:
        # 细分阶段（如 1.2「声母」）还没有自己的题时，用旧键（1.1「拼音拼读」）兜底
        pool = bank.get(stages.legacy_key(key)) or []
    return pool


def bank_size(subject, stage):
    """题库里该科目该阶段有多少道现成题目（数学是生成器，返回一个足够大的数）。"""
    key = stages.normalize_key(stage)
    if not key:
        return 0
    if subject == "数学":
        return 999 if _math_maker(key) else 0
    return len(_bank_pool(subject, key))


def build_question(subject, stage, avoid=()):
    """按科目与能力阶段出一道选择题；题库缺失时返回 None 交给上层兜底。"""
    key = stages.normalize_key(stage) or stages.START_KEY
    avoid = set(avoid or ())

    if subject == "数学":
        maker = _math_maker(key)
        if maker is None:
            return None

        for _ in range(6):
            question = _pack(key, subject, *maker())
            if question and question["question"] not in avoid:
                return question
        return None

    pool = _bank_pool(subject, key)
    if not pool:
        return None

    candidates = [item for item in pool if item[0] not in avoid] or list(pool)
    random.shuffle(candidates)
    for stem, answer, wrongs, analysis in candidates:
        question = _pack(key, subject, stem, answer, wrongs, analysis)
        if question:
            return question

    return None
