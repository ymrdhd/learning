# ==============================================================
# 能力契约｜错题康复子包入口 + 模块分工说明（已含分工表）
# 入口：scheduler / state / strategy（engine 不进导入链）
# 依赖：同包子模块
# 不负责：数据库门面 → recovery/engine.py
# 验证：python backend/verify_recovery.py
# 被调用：recovery_routes.py、main.py（/submit 的康复同步钩子）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 错题康复系统（Wrong Question Recovery：六态状态机 + 分层教学 + 变式练习 + 原题验证）。

模块分工：

| 文件 | 职责 | 回答的问题 |
| --- | --- | --- |
| `state.py` | RecoveryState + transition/apply_result | 这道错题现在处于哪一态、下一步去哪一态？ |
| `strategy.py` | RecoveryStrategy | 下一步干什么、给几级提示、出多难的题？ |
| `scheduler.py` | RecoveryScheduler | 哪些错题该进队列、哪些验证到期了？ |
| `engine.py` | RecoveryEngine | 把上面这些接上 SQLite（唯一碰库的门面） |

对外入口（`engine` 不进本文件的导入链，避免循环依赖）：

```python
from recovery import engine
recovery_engine = engine.DEFAULT_ENGINE
recovery_engine.list_items(db, 1, state="PRACTICING")   # 康复列表
recovery_engine.start(db, 1, 3)                         # 开始教学（NEW → LEARNING）
recovery_engine.next_question(db, 1, 3)                 # 出题（变式题 / 原题）
recovery_engine.answer(db, 1, 3, "B")                   # 判分 + 状态推进
recovery_engine.verify(db, 1, 3, "B")                   # VERIFYING 原题验证
recovery_engine.sync_from_wrong_book(db, 1, row, False) # main.submit 钩子（绝不抛异常）
```

与旧体系的关系：`wrong_questions.stage` 是能力阶段（§2 硬约束 6），本包只读它；
康复状态写在 `wrong_question_recovery.state`，两者互不影响。
"""

from recovery import scheduler, state, strategy  # noqa: F401

__all__ = ["scheduler", "state", "strategy"]
