# ==============================================================
# 能力契约｜临时冒烟脚本（验证后删除，不进入仓库）
# 入口：main
# 依赖：deep_learning.engine、models、database
# 不负责：正式验收 → verify_v27.py
# 验证：python backend/_smoke_v27.py
# 被调用：无
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DB = os.path.join(HERE, "_smoke_v27.db")
if os.path.exists(DB):
    os.remove(DB)
os.environ["PHOEBE_AI_OFFLINE"] = "1"
os.environ["DEEPSEEK_API_KEY"] = ""

os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")

from database import SessionLocal, engine as db_engine, ensure_schema, migrate_data  # noqa: E402
from models import Base  # noqa: E402

Base.metadata.create_all(db_engine)
try:
    ensure_schema(Base)
    migrate_data()
except Exception as exc:  # pragma: no cover
    print("schema note:", exc)
db = SessionLocal()


from deep_learning import engine as deep_engine  # noqa: E402
from deep_learning import deep_mastery, evidence as evidence_module, transfer_engine  # noqa: E402

E = deep_engine.DEFAULT_ENGINE

print("== record STANDARD correct x5 ==")
for i in range(5):
    out = E.record_evidence(db, 1, "数学", "表内除法", evidence_type="STANDARD", result="correct")
    print(" n=%d weight=%s level=%s score=%s" % (i + 1, out["weight"], out["deep"]["level"], out["deep"]["score"]))

print("== recall no-hint ==")
out = E.record_evidence(db, 1, "数学", "表内除法", evidence_type="RECALL", result="correct")
print("recall weight", out["weight"], "level", out["deep"]["level"])

print("== transfer T2 correct ==")
t = E.record_transfer(db, 1, "数学", "表内除法", level=2, correct=True, source="local")
print("transfer weight", t["evidence"]["weight"], "level", t["evidence"]["deep"]["level"])

print("== explanation ==")
ex = E.record_explanation(
    db, 1, "数学", "表内除法",
    question="12÷3=?", student_response="因为 3 个 4 是 12，所以 12 分成 3 份每份是 4",
    use_ai=False)
print("explanation", ex["core_concept_correct"], ex["concept_coverage"], ex["result"])
print("level now", E.detail(db, 1, "数学", "表内除法")["level"])

print("== delayed review ==")
out = E.record_evidence(db, 1, "数学", "表内除法", evidence_type="DELAYED_REVIEW", result="correct")
print("level after delayed", out["deep"]["level"], out["deep"]["level_key"])

print("== status (three layers) ==")
st = E.status(db, 1, "数学", "表内除法")
print("mastery", st["mastery"]["score"], "deep", st["deep_mastery"]["level"], "memory", st["memory"]["maturity_level"])

print("== isolation: student 2 ==")
print("A evidence", len(E.evidence_rows(db, 1)), "B evidence", len(E.evidence_rows(db, 2)))
print("B detail level", E.detail(db, 2, "数学", "表内除法")["level"])

print("== summary/growth/efficiency ==")
print(E.summary(db, 1)["by_level"])
print(E.growth(db, 1)["child_text"])
eff = E.efficiency(db, 1)
print("eff", eff["score"], eff["band"], eff["child_text"])

print("== plan_hint ==")
print(E.plan_hint(db, 1, minutes=15))

print("== ensure_states ==")
print(E.ensure_states(db))

db.close()
db_engine.dispose()
try:
    os.remove(DB)
except OSError:
    pass
print("SMOKE OK")
