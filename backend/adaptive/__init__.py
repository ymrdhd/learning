# ==============================================================
# 能力契约｜自适应子包入口 + 模块分工说明（已含分工表）
# 入口：difficulty / planner / selector / strategy（engine 不进导入链，避免循环依赖）
# 依赖：同包子模块
# 不负责：数据库门面 → adaptive/engine.py
# 验证：python backend/verify_adaptive.py
# 被调用：main.py、adaptive_routes.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.3 自适应学习引擎（Adaptive Learning Engine）。

模块分工：

| 文件 | 职责 | 回答的问题 |
| --- | --- | --- |
| `strategy.py` | LearningStrategy + 知识依赖关系 | 学什么知识点？为什么？ |
| `difficulty.py` | DifficultyController | 出什么难度？什么时候升降？ |
| `selector.py` | QuestionSelector | 下一题是什么？ |
| `planner.py` | DailyLearningPlanner | 今天怎么安排？ |
| `engine.py` | AdaptiveLearningEngine | 从数据库组装画像并把决策落库（闭环） |

对外入口：

```python
from adaptive import engine
engine.DEFAULT_ENGINE.recommend(db, student_id)       # 今日推荐
engine.DEFAULT_ENGINE.next_spec(db, student_id, "数学")  # 下一题规格
engine.DEFAULT_ENGINE.plan(db, student_id)            # 今日计划
engine.DEFAULT_ENGINE.feedback(db, student_id, payload)  # 学习反馈
```
"""

from adaptive import difficulty, planner, selector, strategy  # noqa: F401

__all__ = ["difficulty", "planner", "selector", "strategy"]
