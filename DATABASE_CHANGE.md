# DATABASE_CHANGE.md — V2.5 数据库变更说明

> 任务：swarm run「《菲比同学》V2.5 — 错题康复系统 + 每日学习习惯系统」/ task `db-schema`（Agent 1 · Database Architect）
> 规格来源：`SPEC.md` §2、§3、§3.4、§11（冻结契约）。本文档只描述**数据库结构变更**。

## 0. 变更总览

| 项 | 变更前（V2.4） | 变更后（V2.5） |
| --- | --- | --- |
| 表数量 | 19 | **22**（新增 3 张） |
| 索引数量（元数据口径） | 22 | **28**（新增 6 个，无删除、无重命名） |
| 既有表结构 | — | **零改动**：不删列、不改名、不改类型、不清表 |
| 迁移类型 | — | 纯**新增表**（`CREATE TABLE`）；无数据回填需求，`MIGRATIONS` 未追加 |

改动文件（唯一写入范围）：

| 文件 | 改动 |
| --- | --- |
| `backend/models.py` | 文件末尾追加 3 个模型类（`WrongQuestionRecovery` / `DailyLearningTask` / `LearningHabitProfile`）；仅更新文件头部契约卡。既有 19 张表定义**一字未动** |
| `backend/database.py` | **代码本体零改动**；仅更新文件头部契约卡（说明 V2.5 新表由 `create_all` 建立、`MIGRATIONS` 无需新增） |
| `DATABASE_CHANGE.md` | 本文件 |

---

## 1. 新增表清单与字段表

约定（与 `backend/models.py` 现有 19 张表完全一致的风格）：

- 主键为 `id = Column(Integer, primary_key=True)`；其余列**全部 nullable**（SQLAlchemy 默认，不加 `nullable=False`）。
- 默认值写在 Python 侧 `Column(..., default=...)`，**不是** `server_default`，因此原生 SQL 直插不会触发默认值（业务代码走 ORM Session 即可）。
- `created_time` / `updated_time` 用 `default=datetime.now` / `default=datetime.now, onupdate=datetime.now`。
- 无 `ForeignKey`（与既有 19 张表一致，隔离靠 `student_id` 逻辑过滤）。

### 1.1 `wrong_question_recovery` → `WrongQuestionRecovery`

一道错题在康复队列里的一行（状态机 `NEW → ANALYZING → LEARNING → PRACTICING → VERIFYING → MASTERED`）。
`state` 是**康复状态**，与 `wrong_questions.stage`（能力阶段）互不影响 —— 后者含义未被本次变更触及。

| 列名 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer | PK | 自增主键 |
| `student_id` | Integer | — | 隔离键 |
| `subject` | String | — | 学科 |
| `knowledge_id` | String | — | 知识点名称 |
| `question_id` | Integer | — | 原错题 `questions.id` |
| `wrong_question_id` | Integer | `0` | 对应 `wrong_questions.id`（无则 0） |
| `state` | String | `"NEW"` | 康复状态 |
| `state_before` | String | `""` | 上一次状态（审计） |
| `attempts` | Integer | `0` | 累计尝试次数 |
| `correct_count` | Integer | `0` | 累计答对次数 |
| `consecutive_correct` | Integer | `0` | 连对计数（晋级判据） |
| `fail_count` | Integer | `0` | 累计答错次数 |
| `max_level_used` | Integer | `0` | 已用到的最高提示层级 0~4 |
| `variant_count` | Integer | `0` | 已生成的变式题数量 |
| `last_state_change` | DateTime | — | 最近一次状态变更时间 |
| `next_verify_time` | DateTime | — | `VERIFYING` 到期复验时间 |
| `mastered_time` | DateTime | — | 掌握时间 |
| `source` | String | `"wrong_book"` | `wrong_book` / `manual` |
| `created_time` | DateTime | `now` | 创建时间 |
| `updated_time` | DateTime | `now`，`onupdate=now` | 更新时间 |

### 1.2 `daily_learning_task` → `DailyLearningTask`

一个学生 + 一天 + 一类任务一行（50/30/20 三类：`new_learning` / `weakness` / `review`）。

| 列名 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer | PK | 自增主键 |
| `student_id` | Integer | — | 隔离键 |
| `date` | String | — | `YYYY-MM-DD` |
| `task_type` | String | `"new_learning"` | `new_learning` / `weakness` / `review` |
| `title` | String | — | 儿童文案标题 |
| `subject` | String | — | 学科 |
| `knowledge_id` | String | — | 知识点 |
| `target_count` | Integer | `0` | 目标题量 |
| `complete_count` | Integer | `0` | 已完成题量 |
| `duration_minutes` | Integer | `0` | 该任务累计学习时长（分钟） |
| `target_minutes` | Integer | `0` | 目标时长（分钟） |
| `status` | String | `"pending"` | `pending` / `doing` / `done` |
| `priority` | Integer | `1` | 数字越小越先做 |
| `source` | String | `"plan"` | `plan` / `review_queue` / `habit` |
| `plan_id` | Integer | `0` | 关联学习计划 id |
| `knowledge_ids` | Text | `"[]"` | JSON 数组 |
| `goal` | String | `""` | 任务目标文案 |
| `reason` | String | `""` | 推荐理由 |
| `completed_time` | DateTime | — | 完成时间 |
| `created_time` | DateTime | `now` | 创建时间 |
| `updated_time` | DateTime | `now`，`onupdate=now` | 更新时间 |

### 1.3 `learning_habit_profile` → `LearningHabitProfile`

一个学生一行（连续天数 / 完成率 / 时长 / 徽章 / 等级）。

| 列名 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `id` | Integer | PK | 自增主键 |
| `student_id` | Integer | — | 隔离键，一个学生一行 |
| `current_streak` | Integer | `0` | 当前连续学习天数 |
| `longest_streak` | Integer | `0` | 最长连续学习天数 |
| `total_days` | Integer | `0` | 累计学习天数 |
| `total_tasks` | Integer | `0` | 累计任务数 |
| `completed_tasks` | Integer | `0` | 累计完成任务数 |
| `total_minutes` | Integer | `0` | 累计学习时长（分钟） |
| `today_minutes` | Integer | `0` | 今日学习时长（跨天自动归零重算） |
| `completion_rate` | Float | `0.0` | 完成数 / 任务数 |
| `last_active_date` | String | `""` | `YYYY-MM-DD` |
| `badges` | Text | `"[]"` | JSON 数组 |
| `level` | Integer | `1` | 等级 |
| `created_time` | DateTime | `now` | 创建时间 |
| `updated_time` | DateTime | `now`，`onupdate=now` | 更新时间 |

---

## 2. 索引与唯一约束

全部用 `Index("<SPEC 名字>", ...)` **显式命名**，名字与 SPEC §3 逐字一致，写在 `__table_args__` 元组里。共 **6** 个新索引：

| 索引名 | 所属表 | 列 | 唯一 |
| --- | --- | --- | --- |
| `ix_recovery_student_state` | `wrong_question_recovery` | `student_id`, `state` | 否 |
| `ix_recovery_unique` | `wrong_question_recovery` | `student_id`, `question_id` | **是** |
| `ix_recovery_verify_due` | `wrong_question_recovery` | `student_id`, `next_verify_time` | 否 |
| `ix_daily_task_student_date` | `daily_learning_task` | `student_id`, `date` | 否 |
| `ix_daily_task_unique` | `daily_learning_task` | `student_id`, `date`, `task_type`, `subject`, `knowledge_id` | **是** |
| `ix_habit_profile_student` | `learning_habit_profile` | `student_id` | **是** |

语义：

- `ix_recovery_unique`：同一学生同 `question_id` 只能有一行康复记录（幂等 upsert 的兜底）。
- `ix_daily_task_unique`：同一学生同一天、同一类任务、同一学科同一知识点只生成一行，重复生成计划不会产生脏行。
- `ix_habit_profile_student`：习惯画像一人一行。
- 三个 "学生 + 状态/日期/到期" 索引分别服务康复队列查询、每日任务列表、复验到期扫描，均以 `student_id` 打头，天然满足 SPEC §2「所有查询按 `student_id` 过滤」。

---

## 3. 迁移策略与幂等论证

### 3.1 迁移机制（复用既有代码，无新增）

`backend/main.py:50-53` 在 import 期已执行三步（本次**未改动** `main.py`）：

```python
Base.metadata.create_all(engine)   # 建缺失的表（含 3 张新表）
ensure_schema(Base)                # 逐表 PRAGMA table_info 比对，给旧表补缺列（ALTER TABLE ... ADD COLUMN）
migrate_data()                     # 逐条执行 database.MIGRATIONS 里的回填 SQL
```

- **3 张新表**：裸表，不存在于老库 → `create_all` 直接 `CREATE TABLE`（含 6 个索引）。
- **旧表补列**：本次没有给任何旧表加列，`ensure_schema` 的补列分支对新旧库都不会触发新动作（保持原行为）。
- **数据迁移**：`MIGRATIONS` 现仍是 5 条 V2.2→V2.3 回填（都作用 `student_knowledge_mastery`）。**本次未追加 MIGRATIONS**：三张新表都是空表起步，没有任何历史数据需要回填；SPEC §3.4 只说"如需数据迁移"，此处不需要。这是刻意的 Minimal Diff —— 少一条 SQL 就少一份将来出错的概率。

### 3.2 幂等论证

| 动作 | 重复执行的行为 | 幂等性来源 |
| --- | --- | --- |
| `create_all` | 先 `inspect(engine).has_table()`，已存在则跳过 | SQLAlchemy 内部存在性检查 |
| `ensure_schema` | 已存在的列不再 `ALTER` | `PRAGMA table_info` 后的差集比对 |
| `migrate_data` | 5 条回填 SQL 均为"按状态重算"的 `UPDATE`（如 `wrong_questions = max(total_questions - correct_questions, 0)`），第二次起 rowcount 为 0 | 回填写成绝对赋值而非增量累加；逐条 `try/except` 不中断 |
| 新表 + 6 索引 | `CREATE TABLE` / `CREATE INDEX` 只在首次执行 | 表/索引不存在才创建 |

实测：`migrate_data()` 在同一库上连跑两次，rowcount 均为 `[0, 0, 0, 0, 0]`，无异常（见 §6 测试 A）。

### 3.3 回滚方法

本次变更**只增表**，回滚 = 删掉新表与新索引，既有 19 张表不在回滚范围内、也无需备份（未被触碰）。

```sql
-- 回滚（仅当确认要放弃 V2.5 新功能；会丢弃康复/每日任务/习惯三类数据）
DROP TABLE IF EXISTS wrong_question_recovery;
DROP TABLE IF EXISTS daily_learning_task;
DROP TABLE IF EXISTS learning_habit_profile;
-- 索引随表一起消失；若曾单独创建则：
-- DROP INDEX IF EXISTS ix_recovery_student_state;
-- DROP INDEX IF EXISTS ix_recovery_unique;
-- DROP INDEX IF EXISTS ix_recovery_verify_due;
-- DROP INDEX IF EXISTS ix_daily_task_student_date;
-- DROP INDEX IF EXISTS ix_daily_task_unique;
-- DROP INDEX IF EXISTS ix_habit_profile_student;
```

代码侧回滚：还原 `backend/models.py`（删除文件末尾 3 个类 + 还原契约卡）与 `backend/database.py` 契约卡即可；`database.py` 逻辑零改动，因此**不需要**回滚任何迁移逻辑。
注意：若已升级过，回滚前保留 `learning.db` 备份；因为新表数据无法从旧表重建。

---

## 4. V2.4 兼容性论证（旧表只增不改）

1. **未触碰既有表定义**：`backend/models.py` 的改动是纯追加（文件末尾新增 3 个类），19 张既有表的 `__tablename__` / 列名 / 类型 / 默认值 / `onupdate` / 索引一字未改；`database.py` 代码本体零改动（`MIGRATIONS` 元组长度仍为 5）。
2. **无删列 / 改名 / 改类型 / 清表**：本次唯一的 DDL 是新建 3 张空表，不产生任何 `ALTER TABLE ... DROP`/`RENAME`，符合 SPEC §2 与 AI_RULES §13.2。
3. **行数不变**：迁移不写任何既有表（`MIGRATIONS` 未变，且新表回填为空），因此 SPEC §1 中 17 张有数据表的行数逐张不变 —— 实测断言逐张比对通过（测试 A、测试 B 都覆盖）。
4. **V2.2 遗留列保留**：`student_knowledge_mastery.questions` / `.correct` 等旧列仍存在（`migrate_data` 的 5 条回填依赖它们），未做任何清理。
5. **`wrong_questions.stage` 语义未变**：新增的 `wrong_question_recovery.state` 是独立列、独立表，两者互不影响。
6. **旧库升级路径实测**：用 `Table.to_metadata()` 构造的 V2.4 库（仅 19 张旧表 + 样例数据）跑一遍三步迁移，结果为 22 张表、19 张旧表**行数与列结构（列名与顺序）完全不变**、旧索引全部保留、新增 6 个索引已建立（见 §6 测试 B）。

---

## 5. 验证命令

```powershell
# 契约卡检查（必须 0 缺卡 0 失真）
C:\Python313\python.exe backend\check_cards.py

# 结构自测（临时库，不用真实 learning.db）
$env:PYTHONIOENCODING='utf-8'
C:\Python313\python.exe "<自测脚本>"   # 见 §6，脚本位于仓库外临时目录，跑完自动删除临时库
```

自测脚本要点（`DATABASE_URL` 指向临时库后才 `import database`）：

- 测试 A（全新库）：`Base.metadata.create_all(engine)` + `ensure_schema(Base)` + `migrate_data()` → 断言 22 张表、6 个新索引名一致、`migrate_data` 连跑两次幂等、19 张旧表行数与列结构不变、唯一索引真的拒绝重复、三张新表 ORM 插入的 Python 侧默认值与 SPEC 一致。
- 测试 B（V2.4 老库升级）：只建 19 张旧表 + 塞样例数据 → 三步迁移 → 断言升级后 22 张表、旧表行数与列结构（名称+顺序）完全不变、旧索引保留、新索引已建。

---

## 6. 实测输出

### 6.1 契约卡

```
C:\Python313\python.exe backend\check_cards.py
校验模块数: 78   无卡片: 0   失实符号: 0   人工确认: 9
EXIT=0
```

（基线为 76 个模块；模块数上涨来自并行任务的其它文件，本任务保证的是 **无卡片 0 / 失实符号 0** 且退出码 0。）

### 6.2 结构 + 幂等 + V2.4 兼容自测

```
=== 测试 A：全新临时库（22 张表 + 幂等） ===
  PASS  三张新表已建立：['daily_learning_task', 'learning_habit_profile', 'wrong_question_recovery']
  PASS  19 张旧表全部存在（共 19 张）
  PASS  表总数 = 22（实测 22）
  PASS  6 个新索引名与 SPEC 完全一致：缺失 []
  PASS  migrate_data 连续再跑两次未抛异常（rowcount=[0, 0, 0, 0, 0] / [0, 0, 0, 0, 0]）
  PASS  重复迁移后旧表行数逐张不变：{'abilities': 0, 'ability_profile': 0, 'answer_error_analysis': 0,
        'answer_records': 3, 'diagnostic_records': 0, 'diagnostic_sessions': 0, 'knowledge_memory_state': 0,
        'knowledge_points': 2, 'learning_feedback': 0, 'learning_plan': 0, 'learning_strategy_log': 0,
        'questions': 2, 'review_queue': 0, 'review_records': 0, 'review_strategy_log': 0, 'reviews': 1,
        'student_knowledge_mastery': 1, 'students': 2, 'wrong_questions': 2}
  PASS  重复迁移后旧表列结构不变
  PASS  ix_recovery_unique 生效（同学生同 question_id 拒绝重复）
  PASS  WrongQuestionRecovery 默认值 = ('NEW', '', 'wrong_book', 0, 0, 0)
  PASS  DailyLearningTask 默认值 = ('new_learning', 'pending', 1, 'plan', 0, '[]', 0, 0)
  PASS  LearningHabitProfile 默认值 = (0, 0.0, '', '[]', 1)
  PASS  临时库文件已删除

=== 测试 B：V2.4 老库升级（只增不改） ===
  PASS  V2.4 旧表数量 = 19（实测 19）
  PASS  V2.4 库仅有 19 张旧表（实测 19）
  PASS  升级后表总数 = 22（实测 22）
  PASS  三张新表已在老库上创建
  PASS  19 张旧表行数逐张不变（样例：students=2 questions=2 wrong_questions=2）
  PASS  19 张旧表列结构（名称与顺序）完全不变
  PASS  旧索引全部保留（新增 6 个索引）
  PASS  新索引已建立
  PASS  临时库文件已删除

断言总数: 21，失败: 0
RESULT: ALL PASS
```

### 6.3 元数据索引集合对照

```
C:\Python313\python.exe -c "<对比 V2.4 元数据副本与 V2.5 完整元数据的索引集合>"
old idx 22
new idx 28
added   ['ix_daily_task_student_date', 'ix_daily_task_unique', 'ix_habit_profile_student',
         'ix_recovery_student_state', 'ix_recovery_unique', 'ix_recovery_verify_due']
removed []
```

### 6.4 真实库未被写入

自测全程使用 `DATABASE_URL` 指向临时库文件，跑完即删；`backend/learning.db` 的 `LastWriteTime` 保持为 `2026/10/4 23:19:02`（本次任务期间未被改动）。

---

## 7. 与 SPEC 的偏差与遗留

**偏差：无。** 表名、列名、类型、默认值、索引名（6 个）均与 SPEC §3 逐条一致；未新增依赖；未改 `MIGRATIONS`。

遗留 / 给下游 Agent 的注意事项：

1. 新表默认值是 Python 侧 `default=`，**用原生 SQL 直插不会触发**；业务代码请走 ORM Session（或显式赋值）。这与既有 19 张表的风格一致。
2. 三张新表都**没有 `ForeignKey`**，行级隔离靠业务层强制 `WHERE student_id = ?`，请勿省略该过滤条件。
3. `MIGRATIONS` 未追加任何条目是**有意为之**（新表无历史数据可回填）。若后续 Agent 需要回填，请遵守 AI_RULES §13.2：只能 `ALTER TABLE ... ADD COLUMN` 与幂等 `UPDATE`，禁止删表 / 重建 / 改名。
4. 新增列全部 nullable，写业务代码时请自行防御 `None`（例如 `row.completion_rate or 0.0`）。
