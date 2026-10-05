# ==============================================================
# 能力契约｜复习子包入口 + 模块分工说明（已含分工表）
# 入口：forgetting / interval / memory / mix / scheduler / selector（engine 不进导入链）
# 依赖：同包子模块
# 不负责：数据库门面 → review/engine.py
# 验证：python backend/verify_memory.py
# 被调用：自适应 planner.py、review_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.4 间隔复习系统（Spaced Repetition & Forgetting Risk Engine）。

模块分工：

| 文件 | 职责 | 回答的问题 |
| --- | --- | --- |
| `memory.py` | MemoryState + 成熟度 | 还记不记得？记忆有多强？ |
| `forgetting.py` | ForgettingRiskEngine | 现在有多大概率忘了？ |
| `interval.py` | calculate_next_interval() | 下次什么时候复习？ |
| `scheduler.py` | ReviewScheduler | 今天复习哪些知识点、各出几题？ |
| `selector.py` | ReviewQuestionSelector | 复习题出什么（且不重复旧题）？ |
| `mix.py` | calculate_daily_mix() | 今天新学/补强/复习各占多少？ |
| `engine.py` | ReviewEngine | 把上面这些接上 SQLite（闭环） |

对外入口（`engine` 不进本文件的导入链，避免与自适应引擎循环依赖）：

```python
from review import engine
review_engine = engine.DEFAULT_ENGINE
review_engine.today(db, student_id)              # 今日复习队列
review_engine.review_question(db, 1, "数学", "表内乘法")   # 复习题
review_engine.submit_review(db, 1, payload)      # 提交并更新记忆状态
review_engine.memory_map(db, 1)                  # 记忆地图（家长端）
```
"""

from review import forgetting, interval, memory, mix, scheduler, selector  # noqa: F401

__all__ = ["forgetting", "interval", "memory", "mix", "scheduler", "selector"]
