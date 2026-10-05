# ==============================================================
# 能力契约｜/api/ability/* 训练数据自动能力诊断接口
# 入口：router / ability_auto
# 依赖：auto_ability（算法与只读统计）/ database.get_db / stages
# 不负责：能力推断算法 → auto_ability.py；专门诊断流程 → diagnostic_routes.py
# 验证：python backend/verify_ability.py
# 被调用：main.py（注册 router）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 自动能力诊断 API。

    GET /api/ability/auto/{student_id}   由日常训练与自由练习成绩自动推断三科能力阶段

说明：数据全部来自 answer_records（今日学习页 /api/learning/* 与练习页 /question + /submit
都会写入），不需要学生额外做一次能力诊断；接口只读不写库。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import auto_ability
from database import get_db

router = APIRouter(prefix="/api/ability", tags=["ability"])


@router.get("/auto/{student_id}")
def ability_auto(student_id: int, db: Session = Depends(get_db)):
    """自动能力画像：三科各自的能力阶段 / 能力分 / 星数 / 置信度 / 依据与下一步建议。

    学生不存在或还没有任何答题记录时**不返回 404**：三科都给出 status="unknown"
    的正常结构，前端可以直接渲染成"先去练几道题"。
    """
    return auto_ability.profile_for(db, student_id)
