# HABIT_DESIGN.md — 每日学习习惯系统设计说明（Agent 4 / habit-engine）

对应实现：`backend/habit.py`（`HabitEngine` + 模块级 `DEFAULT_ENGINE`）
对应规格：`SPEC.md` §6（HabitEngine）、§7.2（任务/画像字段）
数据表：`daily_learning_task`、`learning_habit_profile`（`backend/models.py`，Agent 1 已建，本任务只读不改）

---

## 1. 公开契约

```python
HabitEngine.MIX       = {"new_learning": 0.5, "weakness": 0.3, "review": 0.2}
HabitEngine.MIX_TEXT  = {"new_learning": "新知识", "weakness": "薄弱训练", "review": "复习恢复"}
HabitEngine.SUBJECTS  = ("数学", "语文", "英语")
HabitEngine.TYPE_ORDER = ("new_learning", "weakness", "review")
DEFAULT_ENGINE = HabitEngine()

generate_daily_tasks(db, student_id, *, date=None, minutes=None, force=False) -> list[DailyLearningTask]
today(db, student_id, *, date=None) -> dict
complete_task(db, student_id, task_id, *, minutes=0, count=None, done=True) -> dict
record_answer(db, student_id, *, subject, knowledge, correct, minutes=0, date=None) -> dict
profile(db, student_id, *, date=None) -> dict
stats(db, student_id, *, days=7, date=None) -> dict
refresh(db, student_id, *, date=None) -> dict
```

辅助函数（模块级，供测试或其他模块直接复用）：

```python
split_by_mix(total) -> {"new_learning": int, "weakness": int, "review": int}
```

`backend/habit.py` 不依赖 DeepSeek、不依赖 FastAPI：纯 SQLAlchemy + `backend/review/knowledge_tree.py` 的
知识点名兜底。AI 出题/讲解一律由调用方（题路由 / deepseek.py）负责，`HabitEngine` 只做任务编排与统计。

---

## 2. 每日任务生成

### 2.1 一天生成 9 行

每天为三科各生成三个任务类型的一条任务行（3 科 × 3 类 = 9 行）：

| task_type | MIX_TEXT | 每科题量来源 |
| --- | --- | --- |
| `new_learning` | 新知识 | `round(科题量 × 0.5)` |
| `weakness` | 薄弱训练 | `round(科题量 × 0.3)` |
| `review` | 复习恢复 | 科题量 − 前两者 |

每科的「科题量」= `backend/adaptive/planner.py::target_count_of(subject, subject_minutes)`：

- `minutes=None`（默认）时按 `planner.DEFAULT_MINUTES` 配比 35 分钟：数学 15 / 语文 10 / 英语 10
  → 数学 10 题、语文 10 题、英语 20 题，合计 40 题。
- 传入 `minutes=` 时按同一比例缩放（同样按 `DEFAULT_MINUTES` 的比例切分，每科下限 `MIN_MINUTES = 5`）。

实测（学生 1，默认分钟数）：

| 学科 | 科题量 | new_learning | weakness | review |
| --- | --- | --- | --- | --- |
| 数学 | 10 | 5 | 3 | 2 |
| 语文 | 10 | 5 | 3 | 2 |
| 英语 | 20 | 10 | 6 | 4 |
| **合计** | **40** | **20 (50%)** | **12 (30%)** | **8 (20%)** |

### 2.2 取整规则与边界（`split_by_mix`）

1. `total = max(3, int(total))`：三类任务每类至少 1 题，因此总题量下限是 3。
2. `new_learning = round(total × 0.5)`（Python 内置 `round`，**银行家舍入**：`.5` 时向偶数取整）。
3. `weakness = round(total × 0.3)`。
4. `review = total − new_learning − weakness`（用减法兜底，保证三类之和恒等于 `total`）。
5. **边界修补循环**：若某类为 0，则从「数量最大」的类借 1 题给「数量最小」的类，循环直到三类均 ≥ 1。
   借题只改变分布，不改变 `total`。

实测边界值：

| total | new_learning | weakness | review | 说明 |
| --- | --- | --- | --- | --- |
| 3 | 1 | 1 | 1 | 下限，三类各 1 |
| 4 | 2 | 1 | 1 | 零类回填（原始 2/1/1 已合法，边界规则兜底） |
| 5 | 2 | 2 | 1 | 0.5 银行家舍入（round(2.5)=2） |
| 9 | 4 | 3 | 2 | round(4.5)=4 |
| 10 | 5 | 3 | 2 | 默认数学/语文 |
| 15 | 8 | 4 | 3 | round(7.5)=8 |
| 20 | 10 | 6 | 4 | 默认英语 |
| 40 | 20 | 12 | 8 | 默认全天 |

不变量（自测逐条断言）：`sum(三类) == total` 且 `min(三类) >= 1`。

> 说明：`backend/review/mix.py::split_counts(total, mix)` 需要 `{key}_ratio` 形式的字典且**不保证每类 ≥1**，
> 所以这里自行实现 `split_by_mix`，算术差异只体现在边界回填上。

### 2.3 知识点选择（降级路径）

优先级：**当天 learning_plan > student_knowledge_mastery 薄弱点 > knowledge_tree 知识点名兜底**。

1. 读当天 `learning_plan`（`student_id` + `date` 过滤，`status != "expired"`），按 `(item_type, subject)` 建索引；
   命中时该行直接取自计划：`source="plan"`、`plan_id`、`knowledge_id` 全部来自计划行，`target_count` 取计划值。
2. 未命中时读该生 `student_knowledge_mastery`，按 `knowledge_id` 聚合平均 `mastery_score` 后**升序**排序：
   - `weakness` → 最薄弱一条（升序第一）
   - `review` → 掌握最好一条（升序最后）
   - `new_learning` → 从未练过的知识点（`total_questions <= 0`）优先，否则升序第二
   - 全部来源 `source="habit"`
3. 该生该科完全没有掌握记录时，用 `backend/review/knowledge_tree.py::all_names(subject)` 的第一个知识点名兜底，
   保证**数学/语文/英语三科在任何数据状态下都能生成任务**（自测用例⑦）。
4. 全程零外部依赖：不调用 DeepSeek，也不阻塞答题主流程。

### 2.4 幂等策略

- 唯一约束来自 Agent 1：`ix_daily_task_unique(student_id, date, task_type, subject, knowledge_id)`。
- `generate_daily_tasks` 先查当天已有行：
  - 已有行且 `force=False` → **直接返回已有行，一行不新增**（自测用例①：同一天调用两次都是 9 行）。
  - `force=True` → 按 `(task_type, subject)` 作为业务键 **upsert**：存在则更新字段，不存在才插入。
- 保护已完成的进度：若某行 `complete_count > 0` 且知识点未变化，则不全量覆盖，避免抹掉学生白天的做题记录。
- 知识点升级（例如弱点集合变化）时会更新 `knowledge_id` / `title` / `reason`，但保留 `complete_count` 与 `duration_minutes`。

---

## 3. 连续天数状态转移表（`refresh` / `_profile_dict`）

「今天学了」的判定（`today_active`）：该日期存在任一任务 `status == "done"` **或** `complete_count > 0`。

设 `stored = last_active_date` 落库的 `current_streak`，`day` = 本次统计的日期：

| 今天是否学习 | last_active_date 相对 day | current_streak 结果 |
| --- | --- | --- |
| 是 | 等于 day（今天） | `max(stored, 1)`（不变，防重复加） |
| 是 | 等于 day − 1（昨天） | `stored + 1` |
| 是 | 更早 / 为空 | `1`（重置并重新计） |
| 否 | 等于今天或昨天 | `stored`（保持，今天还没结束） |
| 否 | 早于昨天 / 为空 | `0`（中断归零） |

- `longest_streak = max(已落库 longest_streak, current_streak)`，历史最长永不回退。
- 同一次写入同时落库：`last_active_date`（有学习才更新）、`total_days`（有学习的日期数）、
  `total_tasks`（全部任务行数）、`completed_tasks`（`status == "done"` 行数）、
  `total_minutes`、`today_minutes`、`completion_rate = round(done / total, 4)`、`badges`、`level`。
- 实测：连续 day1→day2→day3 学习后 `current_streak == 3`；跳到 day5（中断一天）后 `current_streak == 0`
  而 `longest_streak` 仍为 3。

---

## 4. 徽章触发条件（`BADGE_CATALOG`，只增不减、去重合并）

| key | 名称 | 触发条件 |
| --- | --- | --- |
| `first_day` | 初次见面 | `total_days >= 1`（第一次有学习记录） |
| `streak_3` | 三日不辍 | `longest_streak >= 3` |
| `streak_7` | 一周坚持 | `longest_streak >= 7` |
| `streak_30` | 月度习惯 | `longest_streak >= 30` |
| `rate_80` | 高效完成 | `total_tasks >= 5` 且 `completion_rate >= 0.8` |
| `minutes_100` | 时长破百 | `total_minutes >= 100` |

- 判定一律基于 `longest_streak`（而非 `current_streak`），所以中断后已得徽章不会掉。
- 合并规则：`badges = 已落库 key 列表 ∪ 本次命中的 key 列表`，按 `BADGE_CATALOG` 顺序去重输出；
  落库为 JSON 数组（`learning_habit_profile.badges`），例如 `["first_day", "streak_3"]`。
- `profile()` 返回的 `badges` 是**全量清单**（每个 key 都带 `got: true/false` + 名称 + 图标），便于前端直接渲染。
- 等级：`level = min(10, 1 + min(6, current_streak // 3) + (1 if rate_80 else 0))`，配 `LEVEL_TEXT` 文案。

---

## 5. 验证命令与实测输出

### 5.1 契约卡校验（必须 0 缺卡 / 0 失真）

```
C:\Python313\python.exe backend\check_cards.py
```

实测输出（节选）：`校验模块数: 80  无卡片: 1  失实符号: 0`。
唯一缺卡文件是 Lead 自己的 `backend/_lead_migrate_check.py`（不在本任务写范围）；`backend/habit.py` 无失实符号。

### 5.2 临时库自测（34 项断言，全 PASS）

自测脚本使用临时库，不触碰 `backend/learning.db`：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:DATABASE_URL='sqlite:///C:/Users/1/Desktop/ai_learning_system/backend/_tmp_habit_agent4.db'
# 脚本内：Base.metadata.create_all(engine) → 逐项断言 → 删除临时库
```

实测结果（`RESULT: ALL PASS`，exit 0）：

```
PASS split_by_mix(3)   {'new_learning': 1, 'weakness': 1, 'review': 1}
PASS split_by_mix(4)   {'new_learning': 2, 'weakness': 1, 'review': 1}
PASS split_by_mix(5)   {'new_learning': 2, 'weakness': 2, 'review': 1}
PASS split_by_mix(9)   {'new_learning': 4, 'weakness': 3, 'review': 2}
PASS split_by_mix(10)  {'new_learning': 5, 'weakness': 3, 'review': 2}
PASS split_by_mix(15)  {'new_learning': 8, 'weakness': 4, 'review': 3}
PASS split_by_mix(20)  {'new_learning': 10, 'weakness': 6, 'review': 4}
PASS split_by_mix(40)  {'new_learning': 20, 'weakness': 12, 'review': 8}
PASS no learning_plan in db
PASS three subjects generated  ['数学', '英语', '语文']
PASS all source=habit fallback
PASS idempotent rows  (9, 9)                      ← 用例①
PASS mix 50/30/20 by target_count  {'new_learning': 20, 'weakness': 12, 'review': 8}
PASS mix sums to per-subject target_count_of  40  ← 用例②
PASS complete_task done  ('done', 5, 6)
PASS summary done=1 rate=1/9                      ← 用例③
PASS partial -> doing  ('doing', 1)
PASS other student cannot complete  {}
PASS 3-day streak  3                              ← 用例④
PASS badges first_day+streak_3
PASS level >= 2  2
PASS gap -> streak 0, longest 3  (0, 3)           ← 用例⑤
PASS badges monotonic
   stored badges: ["first_day", "streak_3"]
PASS student isolation  (9, 9, 27)                ← 用例⑥（学生 2 首日 9 行 / 只统计自己 / 学生 1 仍 27 行）
PASS plan wins for matching task  ('plan', '分数初步认识', 1)
PASS others stay habit
PASS record_answer matches task  (True, 4, 1, 'doing')
PASS record_answer adds minutes  18
PASS record_answer falls back to same subject  (2, 'weakness')
PASS record_answer auto-generates when empty  (52, '2026-01-20')
PASS stats 7 days ending day3  (7, {'date': '2026-01-07', ...}, 0.0476)
PASS today reuses rows, generated False
PASS today summary mix by target_count  {'new_learning': 20, 'weakness': 12, 'review': 8}
PASS today task fields complete  （15 个字段与 §7.2 一致）
RESULT: ALL PASS
```

用例覆盖对照：①幂等 ②配比 ③complete_task 汇总 ④三日连续 + `streak_3` ⑤中断归零 ⑥学生 1/2 隔离
⑦无 learning_plan 三科生成（+ learning_plan 命中优先级、record_answer 钩子、stats/today 结构）。

### 5.3 注意事项

- 只允许用 `DATABASE_URL` 指向临时库跑库相关验证；本任务的自测库 `backend/_tmp_habit_agent4.db` 已在同一条命令内删除。
- 本任务未运行 `backend/verify_all.py`（由 Lead 统一执行，端口独占）。
