# ==============================================================
# 能力契约｜首次启动写入默认学生（朵朵 / 童童），并把旧默认名改过来
# 入口：init_default_users
# 依赖：models
# 不负责：学生列表 API → main.students
# 验证：python backend/verify_flow.py --self-serve
# 被调用：main.py（import 期调用）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

from models import Student

# 默认学生：id 固定 1 <=>「朵朵」，2 <=>「童童」（avatar 沿用老库的设定，不因改名而变）
DEFAULT_STUDENTS = (
    {"id": 1, "name": "朵朵", "grade": 1, "avatar": "boy"},
    {"id": 2, "name": "童童", "grade": 1, "avatar": "girl"},
)

# 老版本自动写进去的默认名（「小朋友A」「小朋友B」「小朋友1」…）。
# 只认这个前缀：已经改过名的库不会再匹配，手动改成别的名字的库也不会被覆盖。
LEGACY_NAME_PREFIX = "小朋友"


def init_default_users(db):
    """保证 id=1/2 的默认学生存在；还是旧默认名（小朋友…）时一并改成新名字。

    幂等：重复启动不会重复插入，也不会覆盖已经手动改过的姓名。
    """
    for spec in DEFAULT_STUDENTS:
        student = db.query(Student).filter(Student.id == spec["id"]).first()

        if student is None:
            db.add(Student(
                id=spec["id"],
                name=spec["name"],
                grade=spec["grade"],
                avatar=spec["avatar"],
            ))
            continue

        name = student.name or ""
        if name.startswith(LEGACY_NAME_PREFIX):
            student.name = spec["name"]

    db.commit()
