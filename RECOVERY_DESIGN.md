# RECOVERY_DESIGN.md — V2.5 错题康复系统（Agent 2 / backend/recovery/）

> 本文是 `backend/recovery/` 子包的设计说明：状态机、计数规则、签名对照、降级策略与实测验证。
> 冻结契约以 `SPEC.md` §4 / §4.1 为准，本文只记录实现与实测，不修改契约。
> 生成时间：V2.5 开发期（Agent 2 交付物之一）。

## 1. 子包分工

| 文件 | 职责 | 是否碰库 |
| --- | --- | --- |
| `backend/recovery/state.py` | 纯状态机：六态常量、事件、`transition/apply_result/next_action/is_active` | 否（不 import 任何数据库模块） |
| `backend/recovery/strategy.py` | 纯策略：下一步动作、提示层级 1~4、难度、题型、题量 | 否 |
| `backend/recovery/scheduler.py` | 队列与到期：`enqueue`（幂等入队）、`due_verify`、`apply_overdue`、`summarize` | 读 `wrong_questions` / `wrong_question_recovery` |
| `backend/recovery/engine.py` | **唯一门面**：教学、出题、判分、验证、统计、`main.submit` 钩子 | 是（只有它能写 `wrong_question_recovery`） |
| `backend/recovery/__init__.py` | 子包契约卡 + 分工表 + `__all__`（不 import engine，避免循环依赖） | 否 |

依赖方向单向：`state ← strategy ← scheduler ← engine`。路由层（Agent 5 的 `recovery_routes.py`）只允许调用 `engine`。

## 2. 状态机图（文字版）

```text
        ┌──────────────────────── 再次答错原题（relearn）───────────────────────┐
        │                                                                      ▼
  NEW ──analyze──▶ ANALYZING ──hint──▶ LEARNING                        ┌──▶ NEW ◀──┐
                                       │ 答对（教学完成）                 │           │
                                       ▼                                 │ fail%2==0 │
                                   PRACTICING ──变式题连对 2 次──▶ VERIFYING ──原题答对──▶ MASTERED
                                       ▲    │                          │   ▲            │
                                       │    └──答错：cc=0, fail+=1 ─────┘   │            │
                                       │        （fail%2==0 → NEW）          │            │
                                       └──────── 验证未过 / 超时（verify_timeout）────────┘
                                       ▲                                  再次答错原题 → NEW
                                       └────────── MASTERED 再次答错原题（relearn）────────┘
```

事件常量（`recovery/state.py`）：`analyze` / `hint` / `practice` / `correct` / `wrong` /
`verify_pass` / `verify_fail` / `verify_timeout` / `relearn`。

## 3. 每个状态的进入 / 退出条件

| 状态 | 中文（`RecoveryState.TEXT`） | 进入条件 | 退出条件（事件 → 目标态） |
| --- | --- | --- | --- |
| `NEW` | 刚进康复队列，还没分析 | 错题入队（`scheduler.enqueue` / `engine.sync_from_wrong_book`）；PRACTICING 偶数次答错；VERIFYING 未过且 `relearn` | `analyze` → ANALYZING |
| `ANALYZING` | 正在找错因，准备讲解 | `NEW` + `analyze`（`engine.start()` 第一步） | `hint` → LEARNING（`practice` 也可直接进 PRACTICING） |
| `LEARNING` | 跟着分层提示学 | `NEW`/`ANALYZING` + `hint`（`engine.start()` 第二步，Level 1 提示） | 答对 → PRACTICING（`cc=1`）；答错 → NEW |
| `PRACTICING` | 练同知识点的变式题 | 教学阶段答对；VERIFYING 答错/超时 | 连对 2 次 → VERIFYING（写 `next_verify_time = now+1天`）；答错 `fail_count%2==0` → NEW，否则留在 PRACTICING |
| `VERIFYING` | 原题验证中 | PRACTICING 连对 2 次 | 原题答对 → MASTERED（写 `mastered_time`）；答错 / 超时 → PRACTICING；再答错原题（`relearn`）→ NEW |
| `MASTERED` | 已康复 | VERIFYING 原题答对 | 再次答错原题 → NEW（`state_before=MASTERED`） |

`is_active(state)`：`NEW/ANALYZING/LEARNING/PRACTICING/VERIFYING` → `True`，`MASTERED` → `False`。

## 4. 计数规则表

| 场景 | `consecutive_correct` | `fail_count` | 状态变化 | 备注 |
| --- | --- | --- | --- | --- |
| 教学阶段（NEW/ANALYZING/LEARNING）答对 | `min(cc+1, 1)` = 1 | 不变 | → PRACTICING | 教学完成即开始练习 |
| 教学阶段答错 | 0 | +1 | → NEW | 留在回炉起点 |
| PRACTICING 答对（未满 2 次） | +1 | 不变 | 不变 | |
| PRACTICING 连对 2 次 | 2 | 不变 | → VERIFYING | `next_verify_time = now + 1 天`（`VERIFY_DAYS=1`） |
| PRACTICING 答错 | 0 | +1 | `fail_count % 2 == 0` → NEW，否则不变 | `RELEARN_FAIL_STEP=2` |
| VERIFYING 答对 | 不变 | 不变 | → MASTERED | `mastered_time = now`，`next_verify_time` 清空 |
| VERIFYING 答错 | 0 | +1 | → PRACTICING | `next_verify_time` 清空 |
| VERIFYING 超时（`next_verify_time <= now`） | 不变 | 不变 | → PRACTICING | `scheduler.apply_overdue` 在门面读行前自动执行 |
| 任意状态再次答错**原题**（`relearn`） | 0 | +1 | → NEW | `state_before` 记原状态 |
| MASTERED 答对 | 不变 | 不变 | 不变 | |

补充实现约定（与 SPEC 不冲突，供 Agent 5/7 对齐）：

1. `transition()` 返回的 `state` 与 `next_state` 同义，均为**迁移后**的状态；`changed` 表示状态是否变化，
   `state_before` 记录迁移前状态（未变化时为空串）。
2. `engine.verify()` 的答错走 `wrong` 事件（→ PRACTICING，SPEC 明文）；`engine.answer()` 在非
   `VERIFYING` 状态下答错原题走 `relearn`（→ NEW，SPEC 明文）。两者互不覆盖。
3. 变式题会作为新的 `questions` 行落库（`db.begin_nested()` 保存点，失败即降级，不留脏数据）；
   `engine.answer()` 未传 `question_id` 时，先取本次会话记住的「最近发出的题」，再退回原题。

## 5. 与 SPEC §4.1 的签名对照表

### 5.1 `backend/recovery/state.py`

| SPEC §4.1 | 实现位置 | 状态 |
| --- | --- | --- |
| `RecoveryState.NEW/ANALYZING/LEARNING/PRACTICING/VERIFYING/MASTERED` | `state.py` 常量 | ✅ 一致（值即字面名） |
| `RecoveryState.ALL` / `ORDER` / `TEXT` | `state.py` | ✅ `ALL == ORDER`，`TEXT` 覆盖六态 |
| `transition(state, event, *, consecutive_correct=0, fail_count=0) -> dict` | `state.py` | ✅ 返回 `state/next_state/state_before/changed/reason/consecutive_correct/fail_count/mastered/enter_verifying/verify_delay_days/next_action` |
| `apply_result(state, correct, *, consecutive_correct=0, fail_count=0) -> dict` | `state.py` | ✅ 字段同 `transition`，另加 `correct` |
| `next_action(state) -> str` | `state.py` | ✅ `analyze/hint/hint/practice/verify/celebrate` |
| `is_active(state) -> bool` | `state.py` | ✅ |
| 额外导出（供其他模块复用，非契约） | `normalize / state_text / EVENTS / VERIFY_STREAK / RELEARN_FAIL_STEP / VERIFY_DAYS / EVENT_*` | ➕ |

### 5.2 `backend/recovery/strategy.py`

| SPEC §4.1 | 实现 | 状态 |
| --- | --- | --- |
| `RecoveryStrategy.plan(item, *, mastery=None, hint_level=0) -> dict` | `strategy.py` | ✅ 返回 `action/hint_level/difficulty/question_type/target_count/reason` |
| `RecoveryStrategy.hint_level_for(attempts, max_level_used, fail_count) -> int` | `strategy.py` | ✅ 1~4，且不低于 `max_level_used`（只升不降） |
| `RecoveryStrategy.should_vary(state, attempts=0) -> bool` | `strategy.py` | ✅ VERIFYING/MASTERED 出原题，LEARNING/PRACTICING 出变式题 |
| `DEFAULT_STRATEGY` | `strategy.py` | ✅ |

### 5.3 `backend/recovery/scheduler.py`

| SPEC §4.1 | 实现 | 状态 |
| --- | --- | --- |
| `RecoveryScheduler.enqueue(db, student_id, limit=20) -> list` | `scheduler.py` | ✅ 只取 `wrong_questions.status in (NEW, LEARNING)` 且未入队的题；靠 `ix_recovery_unique(student_id, question_id)` 幂等 |
| `RecoveryScheduler.due_verify(db, student_id, now=None) -> list` | `scheduler.py` | ✅ `state == VERIFYING` 且 `next_verify_time` 为空或 `<= now` |
| `RecoveryScheduler.summarize(rows) -> dict` | `scheduler.py` | ✅ `{new, analyzing, learning, practicing, verifying, mastered, total, mastered_rate}`（与 §7.1 `stats` 同名） |
| `DEFAULT_SCHEDULER` | `scheduler.py` | ✅ |
| 额外导出 | `apply_overdue(db, student_id, now=None)` | ➕ 超时未验证自动回落 PRACTICING |

### 5.4 `backend/recovery/engine.py`

| SPEC §4.1 | 实现 | 状态 |
| --- | --- | --- |
| `list_items(db, student_id, subject=None, state=None, limit=50)` | `engine.py` | ✅ 返回 `{student_id, total, stats, items}` |
| `start(db, student_id, recovery_id)` | `engine.py` | ✅ NEW→ANALYZING→LEARNING，返回 `{recovery_id, question_id, state, state_text, teaching, item}` |
| `next_question(db, student_id, recovery_id, hint_level=None)` | `engine.py` | ✅ 返回 `{recovery_id, state, hint_level, question{...}, teaching}` |
| `answer(db, student_id, recovery_id, answer, *, question_id=None, hint_level=None)` | `engine.py` | ✅ 字段集合精确等于 `{correct, correct_answer, analysis, state, state_text, changed, next_action, hint_level, hint, variant, stats}` |
| `verify(db, student_id, recovery_id, answer, *, question_id=None)` | `engine.py` | ✅ 同上 11 字段 + `mastered` |
| `sync_from_wrong_book(db, student_id, question_row, correct)` | `engine.py` | ✅ 幂等、内部 `try/except` + `rollback`、**绝不抛异常** |
| `stats(db, student_id)` | `engine.py` | ✅ 字段名同 §7.1 |
| `detail(db, student_id, recovery_id)` | `engine.py` | ✅ item + `state_before/active/plan/history`，跨学生返回 `None` |
| `DEFAULT_ENGINE` | `engine.py` | ✅ |
| 额外导出 | `hint(db, student_id, recovery_id, level=None)`（§5.2 可选接口 `/api/recovery/hint` 用，不推进状态）、`STATE_TEXT`、`FALLBACK_HINTS` | ➕ |

## 6. 降级策略（离线 / Agent 3 未就绪时的行为）

| 能力 | 首选 | 降级链 | 保证 |
| --- | --- | --- | --- |
| 分层提示 | `ai_recovery.teach()` | 异常 / 无 key / 返回缺 `hint` → `FALLBACK_HINTS` 四级本地文案（`source="fallback"`） | 永不抛异常，`hint` 恒非空 |
| 变式题 | `ai_recovery.generate_variants()`（`validation.passed is False` 的题直接丢弃） | 无结果 / 异常 / 落库失败 → 同 `subject + knowledge` 且难度最接近的既有题目（`source="existing"`）；知识点无题再放宽到同科 | 必有题可出，最坏退回原题（`source="original"`） |
| 到期验证 | `scheduler.apply_overdue()` | 读行前执行；自身异常则 `rollback` 并跳过 | 到期处理失败不影响 `/answer` |
| `/submit` 钩子 | `sync_from_wrong_book()` | 内部全量 `try/except` + `rollback`，失败返回 `None` | 判分主流程优先，绝不被康复逻辑拖垮 |

所有 AI 调用都在**函数内延迟 import + try/except**，`import ai_recovery` 失败（Agent 3 未就绪）时直接走降级，
`/submit` 与答题主流程不阻塞。

## 7. 验证命令与实测输出

```powershell
# 1. 模块契约卡（新增/修改 .py 前 8 行必须合规）
C:\Python313\python.exe backend\check_cards.py
# → 校验模块数: 85   无卡片: 1   失实符号: 0   需人工确认: 9
#   唯一「无卡片」是 Lead 的临时脚本 backend/_lead_migrate_check.py（非本任务文件）；
#   recovery/ 五个文件均通过，失实符号 0。

# 2. 状态机 + 六态全流程 + 三条回炉路径 + A/B 隔离（临时库，禁止用 learning.db）
$env:DATABASE_URL='sqlite:///C:/Users/1/Desktop/ai_learning_system/backend/_tmp_agent2.db'
C:\Python313\python.exe <自测脚本>
# → 60 项检查全部 PASS，RESULT: ALL PASS (0 failures)，退出码 0；测完删除临时库。
```

实测覆盖（自测脚本逐项核对，全部 PASS）：

- 纯状态机：六态常量 / `ALL==ORDER` / `TEXT` 覆盖 / `next_action` 映射 / `is_active`；
  `analyze`、`hint`、教学答对、PRACTICING 答对 1 次与连对 2 次、VERIFYING 答对→MASTERED、
  VERIFYING 答错→PRACTICING、超时→PRACTICING、`fail_count` 奇数留 PRACTICING / 偶数回 NEW、
  `relearn` 记 `state_before`、MASTERED 再错→NEW。
- 策略：`plan()` 六字段、`hint_level_for` 只升不降、`should_vary` 取舍。
- 编排：`enqueue` 幂等（第二次返回 `[]`，表内仍 1 行）；`start()` NEW→LEARNING 且带 Level 1 提示；
  `hint(level=3)`；变式题落 `questions` 表；`answer()` 字段集合与 SPEC §4.1 **完全一致**；
  PRACTICING 连对 2 次 → VERIFYING 且 `next_verify_time ≈ now+1天`；`due_verify` 到期为空、
  2 天后命中；VERIFYING 答错 → PRACTICING 且 `next_verify_time` 清空；`verify()` = 11 字段 + `mastered`；
  VERIFYING 答对 → MASTERED 且写 `mastered_time`；`stats()` / `list_items()` 字段名与 §7.1 一致；
  `detail()` 含 `plan/history/active`；`state=`/`subject=` 过滤。
- 钩子与隔离：`sync_from_wrong_book` 幂等、`None` 入参安全、答对且未入队不建行、走同一状态机；
  A/B 隔离（学生 2 列出/详情/作答均看不到学生 1 的康复项）；判分同源 `grading.is_correct`；
  `state.py` 不 import 数据库模块。

## 8. 已知偏差 / 遗留

1. `backend/recovery/engine.py` 491 行，超过「单文件尽量 ≤250 行」的软约束。原因是本次写入范围被限定为
   5 个文件 + 本文档，无法再拆出 `recovery/store.py`；门面九方法 + 变式题落库 + 降级链都集中在门面里。
   如需拆分，建议由 Agent 5 或后续任务把 `_teach/_variant/_fallback_question` 迁到 `recovery/ai_bridge.py`。
2. `main.py` 的 `/submit` 钩子接线由 Agent 5/Lead 负责，本任务只提供 `DEFAULT_ENGINE.sync_from_wrong_book`。
3. `engine.hint()` 与 `scheduler.apply_overdue()` 是契约外的增量导出（SPEC §5.2 可选接口需要），
   签名与语义已在 §5 标注，不影响 SPEC §4.1 的冻结签名。
