# ==============================================================
# 能力契约｜V2.7 深度学习子包入口 + 模块分工说明
# 入口：evidence / deep_mastery / root_cause / prerequisite_tracer / transfer_engine / variant_ladder / confidence_engine / misconception_engine / explanation_engine / learning_efficiency（engine 不进导入链，避免循环依赖）
# 依赖：同包子模块（全部纯函数，可离线单测）
# 不负责：数据库门面 → deep_learning/engine.py
# 验证：python backend/verify_v27.py
# 被调用：deep_learning/engine.py、deep_learning_routes.py、main.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.7 深度学习层（Deep Learning Layer）。

回答的问题与 Mastery / Memory **并列且互不替代**：

| 概念 | 回答的问题 | 归属 |
| --- | --- | --- |
| `mastery_score` | 这个知识会不会做？ | mastery.py / knowledge_routes.py |
| `deep_mastery` | 是不是真正理解，并且能灵活使用？ | 本子包 |
| `memory_state` | 过一段时间以后还能不能记住？ | review/ 子包 |

模块分工：

| 文件 | 职责 | 回答的问题 |
| --- | --- | --- |
| `evidence.py` | Learning Evidence 统一证据与权重 | 这条证据有多可信？ |
| `deep_mastery.py` | Deep Mastery 六维模型与 0~6 等级 | 深度到哪一级了？ |
| `root_cause.py` | RootCauseAnalyzer 规则版根因 | 为什么错？ |
| `prerequisite_tracer.py` | PrerequisiteTracer 前置追踪与最小回补 | 是不是前置知识松了？ |
| `transfer_engine.py` | TransferEngine 迁移题生成与判定（T0~T5） | 换一种题还会不会？ |
| `variant_ladder.py` | VariantLadder 变式阶梯升降级 | 下一步升还是退？ |
| `confidence_engine.py` | Confidence Feedback / Guess Detection | 是真会还是猜的？ |
| `misconception_engine.py` | Misconception Detection | 是不是形成了错误逻辑？ |
| `explanation_engine.py` | ExplanationEngine「讲给菲比听」 | 能不能自己讲清楚？ |
| `learning_efficiency.py` | LearningEfficiencyEngine 学习效率 | 投入有没有真实收益？ |
| `engine.py` | DeepMasteryEngine：唯一碰库门面 | 以上一切怎么落库？ |

对外入口：

```python
from deep_learning import engine
engine.DEFAULT_ENGINE.record_evidence(db, student_id, "数学", "分数的意义",
                                      evidence_type="RECALL", result="correct")
engine.DEFAULT_ENGINE.detail(db, student_id, "数学", "分数的意义")
engine.DEFAULT_ENGINE.status(db, student_id, "数学", "分数的意义")   # 三层并列
```
"""

from deep_learning import (  # noqa: F401
    confidence_engine,
    deep_mastery,
    evidence,
    explanation_engine,
    learning_efficiency,
    misconception_engine,
    prerequisite_tracer,
    root_cause,
    transfer_engine,
    variant_ladder,
)

__all__ = [
    "confidence_engine",
    "deep_mastery",
    "evidence",
    "explanation_engine",
    "learning_efficiency",
    "misconception_engine",
    "prerequisite_tracer",
    "root_cause",
    "transfer_engine",
    "variant_ladder",
]
