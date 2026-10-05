# backend/_legacy/ · 归档死代码

这些文件在架构重构 **P1 阶段**（见 `docs/架构重构_Mixin方案.md`）从 `backend/` 根目录移至此处。

## 归档依据

- `AI_RULES.md` §13.9：未接线死代码，**未经确认不要接线或删除**。
- 归档前已用全项目 grep 确认零引用（`import algorithm` / `import ai_question` / `import reward` 均无匹配）。
- `adaptive.py` 与 `adaptive/` 子包**同名不同物**，留在根目录会让 agent 定位代码时误读（增加 token 消耗与误改风险），故一并归档。

## 文件清单

| 文件 | 原用途 | 现状 | 应改去哪里 |
|---|---|---|---|
| `adaptive.py` | 早期难度调整 `adjust_difficulty` | 未接线死代码 | `adaptive/difficulty.py` |
| `algorithm.py` | 早期等级推进 `calculate_next_level` / `update_level` | 未接线死代码 | `stages.py` / `ability.py` |
| `ai_question.py` | 早期 DeepSeek 出题（无审核、无兜底） | 未接线死代码 | `deepseek.py` + `validator.py` |
| `reward.py` | 早期激励机制（引用了 `Student` 上不存在的列） | 未接线死代码，接线即 `AttributeError` | 不存在（激励机制尚未接线，见 `PROJECT_CONTEXT.md` §7 Pending） |

## 硬约束

1. **禁止接线**：不得从任何新代码 `import _legacy.*`。
2. **禁止删除**：删除需先取得用户明确确认，并同步更新 `AI_RULES.md` §13.9 与本文件。
3. **禁止复制**：不要把这里的实现拷回 `backend/` 根目录或新模块。
4. 本目录不参与运行时、不被 `verify_all.py` 覆盖；其中的文件**没有测试**。

## 为什么归档而不是删除

项目当时**不是 git 仓库**（本机也未安装 git），删除不可回退。归档保留可追溯性，同时让 `backend/` 根目录的模块清单保持"每个文件都是活的"这一性质，便于 agent 与人工定位。
