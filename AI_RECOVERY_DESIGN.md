# AI 错题康复教学层设计说明（Agent 3 / 任务 ai-recovery）

> 对应 SPEC.md §5.1（AIRecoveryTeacher / VariantQuestionGenerator / ai_enabled / fallback_hint）、§5.2（可选只读路由）、§2 硬约束第 4/6 条。
> 实现文件：`backend/ai_recovery.py`（806 行）。本文件只描述设计与验证事实，不改动任何接口契约。

## 1. 模块定位

| 项 | 内容 |
| --- | --- |
| 唯一实现文件 | `backend/ai_recovery.py` |
| 上游调用方 | `backend/recovery/engine.py:435` `_teach()`、`backend/recovery/engine.py:480` `_generate()`（函数内延迟 import + `try/except`） |
| 唯一真相源依赖 | `backend/validator.py` 的 `QuestionValidator.validate`（题目质量）、`backend/deepseek.py`（唯一外部 AI 出口） |
| 不负责 | 康复状态机与落库（→ `backend/recovery/state.py` / `engine.py`）、判分（→ `backend/grading.py`）、HTTP 路由（→ `backend/main.py`） |
| 路由交付 | **本次不交付 `backend/ai_recovery_routes.py`**。SPEC §5.2 标注为可选；只读路由需要 `air_recovery` 记录落库与 `recovery/engine.py` 的既有表结构（并行 Agent 2 负责），本 agent 不与其它 agent 的写入范围交叉，故留待集成方按 §5.2 自行挂载。模块级函数已就绪，挂载成本为一次 `GET /api/recovery/hint/{recovery_id}?level=n` → `ai_recovery.teach(...)`。 |

## 2. 四级分层提示设计表

等级归一：`level` 经 `_coerce_level()` 处理，非整数或越界一律归一到 `1`（`level=0 / 'abc' / 9` → 1）。`level_name(level)` 返回纯名字 `"方向提示" / "错误定位" / "步骤引导" / "完整讲解"`（**不含序号前缀**）；SPEC.md:210 描述的 `1 方向提示 / 2 错误定位 / 3 步骤引导 / 4 完整讲解` 是四级映射表本身，序号由调用方拼接。此约定与并行 Agent 2 的 `backend/recovery/engine.py:55` `LEVEL_TEXTS = {1: "方向提示", 2: "错误定位", 3: "步骤引导", 4: "完整讲解"}` 完全一致——`teach()` 返回的 `level_text` 与 engine 的离线兜底文案同字面，前端可无条件信任该字段。

| 级别 | `level_name` | 给什么（`gives`） | 不给什么（`withhold`） | 返回字段填充 |
| --- | --- | --- | --- | --- |
| L1 | 方向提示 | 这道题考的知识点、从哪儿入手（读题 / 圈已知条件 / 判断运算方向 / 判断考读音还是字形） | 任何数、任何答案、任何步骤 | 仅 `hint` |
| L2 | 错误定位 | 指出错在哪一步（由 `error_location()` 依 `error_type` 与学科生成）+ 安抚式引导 | 正确答案、完整步骤 | `hint` + `error_location` |
| L3 | 步骤引导 | 完整解题步骤（`_hint_steps()`），**最后一步答案位置用 `□` 占位**，让孩子自己填 | 最终答案 | `hint` + `steps` |
| L4 | 完整讲解 | 完整讲解 + 明确的正确答案 + 为什么是这个答案（`build_full_explanation()`） | —— | `hint` + `steps` + `full_explanation` |

### 2.1 返回结构

`teach(question_row, *, knowledge=None, error_type="", level=1, student=None, use_ai=True)` 返回：

```python
{"level": int,            # 1..4，已归一
 "level_text": str,       # level_name(level)
 "hint": str,             # 本级的提示正文（非空）
 "source": str,           # 见 §4 降级表
 "error_location": str,   # 仅 L2 非空
 "steps": [str, ...],     # 仅 L3 / L4 非空
 "full_explanation": str} # 仅 L4 非空
```

另有静态元数据接口：`levels()` → `[{"level":1,"name":"方向提示","text":"...","level_text":"方向提示","gives":[...],"withhold":[...]}, ...]`（`name`/`text` 满足 SPEC §5.1，`level_text` 满足任务书，互为同义字段，共 4 项）；`AIRecoveryTeacher.levels()` / `.level_name()` / `.teach()` / `.explain()`（`explain()` = 固定 `level=4` 的便捷入口）。

### 2.2 答案不泄漏的硬保障

四级语义不是靠提示词自律，而是代码校验：`_level_pure(result, level, question_row)` 检查 L1~L3 的 `hint`/`steps` 文本是否出现正确答案。若 AI 在 L1~L3 里漏了答案，整条结果被丢弃、退回规则文案，并把 `source` 置为 `"fallback_answer_leak"`。因此**任何 source 的 L1~L3 都不会含答案**。

## 3. 变式题生成与过审流水线

`VariantQuestionGenerator.generate(question_row, *, count=1, difficulty=None, knowledge=None, use_ai=True) -> list[dict]`，每题字段：

```python
{"question": str, "answer": str, "options": {...}, "qtype": str,
 "knowledge": str, "difficulty": int, "analysis": str,
 "source": "ai" | "rule", "validation": {...}}
```

流水线（`backend/ai_recovery.py:686` 起）：

```text
generate(count)
  ├─ count<=0 → 返回 []
  ├─ seed = _row_dict(题目行)        # 兼容 ORM 行对象 / dict / None
  ├─ subject/knowledge/difficulty 归一（缺 subject 时兜底 "数学"）
  ├─ 【AI 支路】use_ai 且 ai_enabled()
  │     └─ _ai_variants() → 逐题 _finalize()
  │           └─ validate_variant() → QuestionValidator.validate()
  │                 ├─ passed=True  → 入列（题干去重）
  │                 └─ passed=False → 丢弃（返回 None，不入列）
  ├─ 【规则支路】AI 不可用 / AI 题不够 count
  │     └─ while attempt < max(48, count*6):
  │           variant = _pick(pool, attempt)          # pool = list(range(6))
  │           candidate = _rule_template(seed, difficulty, variant)
  │           → _finalize() 过审；None 或题干重复 → continue
  ├─ 【补足】仍不足 count 时按序轮转复用已有题（dict 拷贝，不共享引用）
  └─ return items[:count]      # 长度恒等于 count
```

要点：

- **过审唯一真相**：`validate_variant(data, *, subject, knowledge, difficulty)` 直接调用 `QuestionValidator.validate(payload, subject=..., knowledge=..., difficulty=...)`，不自建第二套校验。
- **丢弃语义**：`validation["passed"] is False` 的题一律不产出，绝不放宽标准凑数。
- **选题多样性**：`_pick(items, variant)` 按 `variant % len(items)` 确定性取池中项，同一批 `generate` 内每个 `variant` 只取一次 → `count=5` 时 5 道题题干互不相同（已对 17 个知识点 × 30 轮实测，最少唯一题干 5/5）。
- **规则模板覆盖**：数学（两位数加法/减法/乘法/除法、长方形周长、长方形面积，运算符由 `_math_operators()` 按知识点与题干关键词识别）、语文（反义词 8 组、近义词 7、量词 7、笔画 7、拼音 7、比喻修辞 6 组 × 6 种问法）、英语（名词复数、过去式、现在进行时、颜色、动物、数字、be 动词，每池 ≥6 项）。
- **选择题答案格式**：`answer` 必须是选项字母（`"A"`/`"B"`…），否则 `QuestionValidator` 报 `FORMAT_ANSWER_NOT_IN_OPTIONS` 并拦下——这是本次自测踩到过的坑，已在设计文档中固化。

## 4. 降级策略（任何异常都不抛）

`ai_enabled()`：`PHOEBE_AI_OFFLINE` 命中离线值（`1/true/yes/on`）返回 `False`；否则看 `deepseek.KEY` 是否非空。无 key 或离线时 `False`。

`teach()` 的 source 取值表：

| source | 触发条件 | 文案来源 |
| --- | --- | --- |
| `"ai"` | DeepSeek 正常返回且过了 `_level_pure` 校验 | 模型 |
| `"rule"` | 兜底文案就绪但未走到 AI 分支（内部保留值） | 规则 |
| `"fallback_offline"` | `PHOEBE_AI_OFFLINE=1` | `fallback_hint()` |
| `"fallback_no_key"` | 未配 `DEEPSEEK_API_KEY` / `backend/.env` | `fallback_hint()` |
| `"fallback_disabled"` | 调用方传 `use_ai=False` | `fallback_hint()` |
| `"fallback_error"` | 网络异常/超时（12s）/HTTP 非 200/JSON 解析失败（`_ai_teach` 返回 `(None, "error:...")`） | `fallback_hint()` |
| `"fallback_answer_leak"` | AI 在 L1~L3 泄漏了答案，被 `_level_pure` 拦下 | `fallback_hint()` |

`fallback_hint(question_row, level, error_type="")` 是**纯函数**：不联网、不读数据库、不抛异常，`question_row=None` 也返回结构完整的 dict。`generate()` 侧同理：AI 支路失败即静默转规则模板，规则模板也不可用时仍保证返回 `count` 道题（最后按序轮转复用）。

## 5. 密钥读取方式

- 唯一入口：`backend/deepseek.py`（本模块 `import deepseek`，直接复用 `deepseek.KEY` / `deepseek.API_URL` / `deepseek._extract_json`，**不自建 requests 请求头、不读任何其它密钥来源**）。
- 优先级：环境变量 `DEEPSEEK_API_KEY` → 同目录私密文件 `backend/.env`。
- 本模块不做密钥校验以外的任何持久化，日志不打印密钥。

## 6. 验证命令与实测输出

环境：`C:\Python313\python.exe`（3.13，fastapi/sqlalchemy/requests 已装）。

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PHOEBE_AI_OFFLINE='1'                       # 强制离线，验证降级路径
C:\Python313\python.exe _agent3_selftest.py      # 四级提示 + generate(count=5)
C:\Python313\python.exe _agent3_pool.py          # 17 知识点 × 30 轮 唯一题干/过审
C:\Python313\python.exe backend\check_cards.py   # 模块契约卡
```

### 6.1 四级提示与变式题自测（离线）

`_agent3_selftest.py` 输出（节选）：每科（数学/语文/英语）L1~L4 各 6 项断言全 PASS，其中关键语义断言：

```text
PASS 数学 L1 **不含最终答案**
PASS 数学 L2 **不含最终答案**
PASS 数学 L3 **不含最终答案**
PASS 数学 L4 **含最终答案**
PASS 数学 L3 含步骤
PASS 数学 L2 有 error_location 且 L1 无
（语文、英语同样全 PASS）
=== 异常/边界降级（不抛）===
PASS None 题不抛
PASS use_ai=False 不联网
PASS level=0 归一到 1
PASS level='abc' 归一到 1
PASS level=9 归一到 1
PASS fallback_hint(None, 4) 不抛
=== 变式题生成 generate(count=5) ===
PASS 数学 恰好 5 题 / 5 题题干互不相同 / 每题 validation.passed / source 合法（ai/rule）
（语文、英语同样全 PASS）
==== 结果 ====
FAILED: 无
RESULT: ALL PASS
```

退出码 `0`。

### 6.2 知识点池覆盖（17 知识点 × 30 轮 × 5 题）

```text
OK  数学/两位数加法: 30 轮 × 5 题，最少唯一题干 5/5
OK  数学/表内乘法: 30 轮 × 5 题，最少唯一题干 5/5
OK  数学/长方形周长: 30 轮 × 5 题，最少唯一题干 5/5
OK  数学/长方形面积: 30 轮 × 5 题，最少唯一题干 5/5
OK  语文/反义词（近义词、量词、笔画、比喻修辞、拼音同样 OK）
OK  英语/名词复数（过去式、现在进行时、颜色、动物、数字、be动词同样 OK）

RESULT: ALL PASS
```

退出码 `0`。

### 6.3 与 `recovery/engine.py` 的调用兼容（ORM 行对象 + 数据库参数）

`_agent3_integ.py`（`DATABASE_URL` 指向临时库 `backend/_tmp_agent3.db`，模拟 `Question` 行对象属性访问）：

```text
teach(row) source = fallback_offline | hint = 错在语法这一步：词形（时态、单复数）和句子对不上。
 L1 source=fallback_offline answer_leak=False
 L2 source=fallback_offline answer_leak=False
 L3 source=fallback_offline answer_leak=False
 L4 source=fallback_offline answer_leak=True
generate_variants count=1 -> 1 passed: True   source: rule
count=5 unique: 5 all passed: True
RESULT: OK
```

即 `engine._teach()`（`teach(question, knowledge=..., error_type=..., level=...)`）与 `engine._generate()`（`generate_variants(original, count=1, difficulty=..., knowledge=...)`）两条既有调用路径均可用。

### 6.4 模块契约卡

`backend/check_cards.py` 运行结果为「校验模块数: 85 / 无卡片: 1 / 失实符号: 0」，其中唯一缺卡文件是 `backend/_lead_migrate_check.py`（Lead 名下临时文件，不在本 agent 写入范围，未改动）。`backend/ai_recovery.py` 自身 8 行契约卡完整、失实符号 0（基线模块数由 76 变为 85 系并行 agent 新增模块所致）。

## 7. 已知边界与遗留

1. **未交付只读路由**：见 §1，`backend/ai_recovery_routes.py` 按 SPEC §5.2 的可选口径未实现，避免与并行 agent 的 `air_recovery` 落库/表结构交叉；模块级 `teach()` 已可直接被路由调用。
2. **`source` 语义**：返回给前端/落库的 `source` 只会是 `"ai"` 或 `fallback_*`（`"rule"` 是 `teach()` 内部中间态）；`generate()` 的 `source` 只会是 `"ai"` 或 `"rule"`（符合 SPEC 枚举）。
3. **规则模板的多样性上限**：同一知识点的题干变体来自模板池 × 池起点旋转，`count` 很大（远超池容量）时最后会按序轮转复用题干；`validation.passed` 仍逐题保证，但题干会重复。康复流程实际只取 `count=1`（`engine._generate`）。
4. **AI 支路未经真实密钥联网验证**：本次全部验证在 `PHOEBE_AI_OFFLINE=1` 下完成；AI 支路的代码路径（`_ai_teach` → `_merge_ai` → `_level_pure`）只做了静态审查与解析函数的离线容错（返回 `(None, "error:...")`）验证，未用真实 key 端到端跑通。
5. **难度回显**：`difficulty` 参数优先于题目行自身的 `difficulty`；传 `None` 时取题目行值，再兜底 50。
