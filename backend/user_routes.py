# ==============================================================
# 能力契约｜用户数据备份与重置（家长端：把某个小朋友清零，回到刚建号的样子）
# 入口：router（GET /api/user/{student_id}/reset-preview、POST /api/user/{student_id}/reset）
# 依赖：database.get_db、models.Base（表清单唯一真相）、models.Student
# 不负责：账号体系 → local_users.py；学习数据的写入 → 各业务模块
# 验证：python backend/verify_user_reset.py
# 被调用：main.py include_router
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""家长端「备份并重置」。

规则（与产品约定一致）：
1. **先备份、后清空**：备份文件写成功才动数据库；写失败直接 500，数据原样保留。
2. 备份是 JSON，落在 ``backup/user_reset/<名字>_<id>_<时间戳>.json``（``backup/`` 已被 .gitignore 排除）。
3. 只清空含 ``student_id`` 列的表；``students`` 行本身**保留** —— 孩子还在，只是回到零起点。
   ``questions`` / ``knowledge_points`` 是全局数据，不动。
4. 只读写数据库，不碰前端与算法模块。
"""

import json
import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from models import Base, Student

router = APIRouter(prefix="/api/user", tags=["user"])

# 备份目录：项目根 / backup / user_reset（backup 已被 .gitignore 排除）
BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backup", "user_reset")

# 要备份并清空的表：全部含 student_id 列的表（表清单以 models.Base 为唯一真相）
RESET_TABLES = [table for table in Base.metadata.sorted_tables
                if "student_id" in table.c]


def _student_or_404(db: Session, student_id: int) -> Student:
    if student_id <= 0:
        raise HTTPException(status_code=400, detail="student_id 必须是正整数")
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    return student


def _count_rows(db: Session, table, student_id: int) -> int:
    stmt = select(func.count()).select_from(table).where(table.c.student_id == student_id)
    return int(db.execute(stmt).scalar() or 0)


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")
    return value


def _dump_rows(db: Session, table, student_id: int):
    stmt = select(table).where(table.c.student_id == student_id)
    if "id" in table.c:
        stmt = stmt.order_by(table.c.id)
    return [{key: _jsonable(value) for key, value in row._mapping.items()}
            for row in db.execute(stmt)]


def _safe_name(name) -> str:
    """文件名里只留字母数字与 -_，避免把名字里的怪字符写进路径。"""
    text = "".join(ch for ch in str(name or "") if ch.isalnum() or ch in "-_")
    return text or "student"


@router.get("/{student_id}/reset-preview")
def reset_preview(student_id: int, db: Session = Depends(get_db)):
    """重置前的预览（只读）：会备份并清空哪些数据、一共多少条。"""
    student = _student_or_404(db, student_id)

    tables = {}
    for table in RESET_TABLES:
        count = _count_rows(db, table, student_id)
        if count:
            tables[table.name] = count

    return {
        "student_id": student_id,
        "name": student.name,
        "grade": student.grade,
        "tables": tables,
        "total": sum(tables.values()),
        "backup_dir": BACKUP_DIR,
    }


@router.post("/{student_id}/reset")
def reset_student(student_id: int, db: Session = Depends(get_db)):
    """备份这个小朋友的全部学习数据，然后清空；任何一步失败都不清空。"""
    student = _student_or_404(db, student_id)

    payload = {
        "student": {"id": student.id, "name": student.name,
                    "grade": student.grade, "avatar": student.avatar},
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tables": {},
    }
    for table in RESET_TABLES:
        rows = _dump_rows(db, table, student_id)
        if rows:
            payload["tables"][table.name] = rows

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{_safe_name(student.name)}_{student_id}_{stamp}.json"
    backup_path = os.path.join(BACKUP_DIR, filename)
    try:
        with open(backup_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"备份失败，未清空任何数据：{exc}")

    cleared = {}
    for table in RESET_TABLES:
        result = db.execute(table.delete().where(table.c.student_id == student_id))
        if result.rowcount:
            cleared[table.name] = int(result.rowcount)
    db.commit()

    return {
        "student_id": student_id,
        "name": student.name,
        "backup_file": filename,
        "backup_path": backup_path,
        "backup_rows": sum(len(rows) for rows in payload["tables"].values()),
        "cleared": cleared,
        "total_cleared": sum(cleared.values()),
    }
