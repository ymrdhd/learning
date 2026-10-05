# ==============================================================
# 能力契约｜/api/phoebe/* 菲比陪伴对话接口
# 入口：router / phoebe_chat
# 依赖：phoebe_ai（学习数据快照 + DeepSeek 台词生成）/ database.get_db
# 不负责：学习数据聚合与台词生成 → phoebe_ai.py；立牌与语音 → frontend/phoebe3d.js
# 验证：python backend/verify_phoebe_ai.py
# 被调用：main.py（注册 router）、frontend/phoebe3d.js（点击立牌时调用）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 菲比"会说人话"接口。

    POST /api/phoebe/chat   读这个孩子的学习数据，让 DeepSeek 说一句给孩子听

只读接口：不写任何表；DeepSeek 不可用时自动退回规则文案（仍然带学习数据），
所以前端永远能拿到一句话，不会因为外网问题卡住。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

import phoebe_ai
from database import get_db

router = APIRouter(prefix="/api/phoebe", tags=["phoebe"])


class ChatIn(BaseModel):
    student_id: int = 1
    trigger: str = "click"          # click / correct / wrong
    knowledge: str = ""             # 当前题目或刚答对答错的知识点（可选）
    correct: Optional[bool] = None  # 刚答对还是答错（可选）


@router.post("/chat")
def phoebe_chat(payload: ChatIn, db: Session = Depends(get_db)):
    """菲比说一句话：结合这个孩子的真实学习数据。

    返回 text（给孩子看/听的话）、source（ai / fallback*，方便排查是不是真走了大模型）、
    brief（这次参考了哪些数据）、elapsed_ms（花多久）。
    """
    context = {
        "knowledge": str(payload.knowledge or "").strip(),
        "correct": payload.correct,
    }

    return phoebe_ai.phoebe_line(
        db, payload.student_id,
        trigger=str(payload.trigger or "click").strip().lower(),
        context=context,
    )
