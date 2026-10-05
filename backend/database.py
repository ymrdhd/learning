# ==============================================================
# 能力契约｜SQLAlchemy engine/Session、补列（ensure_schema）、数据迁移（migrate_data）、每请求会话
# 入口：engine / SessionLocal / get_db / ensure_schema / migrate_data
# 依赖：sqlalchemy、os（DATABASE_URL）
# 不负责：表定义 → models.py；业务读写 → 各业务模块
# V2.5：新增表（wrong_question_recovery / daily_learning_task / learning_habit_profile）
#       由 models.Base.metadata.create_all 建表，ensure_schema 只负责给旧表补列；MIGRATIONS 无需新增
# 验证：python backend/verify_knowledge.py
# 被调用：main.py（import 期）；各 verify_*.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 用绝对路径，避免从不同工作目录启动时读写到两个不同的库文件
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(BASE_DIR, "learning.db").replace("\\", "/"),
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


def ensure_schema(base):
    """
    按模型定义给已存在的 SQLite 库补齐缺失的列。

    create_all 只会建新表，不会修改已有表结构；缺少这一步时，
    老库上新增的字段会让查询直接抛 "no such column"。
    """
    with engine.begin() as conn:
        for table in base.metadata.sorted_tables:
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")
            }
            if not existing:
                continue

            for column in table.columns:
                if column.name in existing:
                    continue

                ddl = column.type.compile(engine.dialect)
                conn.exec_driver_sql(
                    f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl}'
                )


# V2.3 迁移：V2.2 的知识点掌握度只有"总题量/答对数"两列，
# 这里把老数据搬到新的掌握模型列上，老列保持不动，随时可以回退。
MIGRATIONS = (
    # 题量：questions → total_questions
    """
    UPDATE student_knowledge_mastery
       SET total_questions = questions
     WHERE (total_questions IS NULL OR total_questions = 0)
       AND questions > 0
    """,
    # 答对数：correct → correct_questions
    """
    UPDATE student_knowledge_mastery
       SET correct_questions = correct
     WHERE (correct_questions IS NULL OR correct_questions = 0)
       AND correct > 0
    """,
    # 答错数 = 总题量 - 答对数
    """
    UPDATE student_knowledge_mastery
       SET wrong_questions = max(total_questions - correct_questions, 0)
     WHERE (wrong_questions IS NULL OR wrong_questions = 0)
       AND total_questions > 0
    """,
    # 置信度按题量补算：n / (n + 7.5)
    """
    UPDATE student_knowledge_mastery
       SET confidence = round(total_questions * 1.0 / (total_questions + 7.5), 2)
     WHERE (confidence IS NULL OR confidence = 0)
       AND total_questions > 0
    """,
    # 最近练习时间沿用原来的更新时间
    """
    UPDATE student_knowledge_mastery
       SET last_practice_time = updated_time
     WHERE last_practice_time IS NULL
       AND updated_time IS NOT NULL
    """,
)


def migrate_data():
    """执行 V2.3 数据迁移（幂等，重复启动不会重复搬数据）。"""
    applied = []
    with engine.begin() as conn:
        tables = {
            row[0] for row in conn.exec_driver_sql(
                "select name from sqlite_master where type='table'"
            )
        }
        if "student_knowledge_mastery" not in tables:
            return applied

        for statement in MIGRATIONS:
            try:
                result = conn.exec_driver_sql(statement)
                applied.append(getattr(result, "rowcount", 0) or 0)
            except Exception:              # 老库结构异常时不阻塞启动
                applied.append(0)

    return applied


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
