# ==============================================================
# 能力契约｜/api/knowledge-map/{student_id} 儿童知识地图（真实掌握数据 → 区域/节点/探索进度）
# 入口：router / knowledge_map / REGION_ICON
# 依赖：knowledge_tree（domains_for/subpoints_of/all_names）、stages（科目校验）、kid_status、
#       review.engine（DEFAULT_ENGINE.states_of + review.memory.state_summary）、models、database.get_db
# 不负责：知识点定义 → knowledge_tree.py；掌握度计算 → mastery.py；记忆成熟度 → review/memory.py；
#         学习路径算法 → adaptive/
# 验证：python backend/verify_v26.py（含知识地图用例）
# 被调用：main.py（注册 router）、frontend/knowledge_map.js
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================
"""V2.6 儿童知识地图 API（需求 §23-§25）。

    GET /api/knowledge-map/{student_id}?subject=数学

地图**必须来自真实学习数据**（mastery + 记忆状态），前端不允许写死状态。
区域与节点结构来自 ``knowledge_tree``（单一真相源），本模块只做三件事：
聚合、翻译成儿童语言、算出探索进度。

``is_unlocked`` 只表示"前置知识已经达到可以开始学的程度"，由真实掌握度推导；
**永远不能**因为在线时长 / 金币 / 签到而解锁。

纪律：学生不存在返回 200 空结构；``subject`` 非法返回 400；异常兜住 → 绝不 500。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import kid_status
import knowledge_tree
import stages
from database import get_db
from review import engine as review_engine
from review import memory as review_memory

router = APIRouter(prefix="/api", tags=["知识地图 V2.6"])

REVIEW_ENGINE = review_engine.DEFAULT_ENGINE

SUBJECTS = tuple(stages.SUBJECTS)

# 区域图标（纯展示层，不改动 knowledge_tree 的领域定义）
REGION_ICON = {
    "数与代数": "🏡", "数与计算": "🏡", "计算": "🏡",
    "图形与几何": "🏰", "图形": "🏰",
    "应用题": "⛰", "解决问题的策略": "⛰",
    "统计与概率": "📊", "统计": "📊",
    "乘法": "🌲", "测量": "📏",
    "拼音": "🔤", "汉字": "📖", "识字与写字": "📖", "阅读": "📚", "古诗": "🏮",
    "写作": "✏️", "表达": "✏️",
    "字母": "🔠", "词汇": "🧩", "语法": "🧱", "口语": "🗣", "句型": "💬",
}

GROWN_RANK = 2          # 🌿 及以上算"已经长大"
UNLOCK_LINE = 30        # 前置知识达到"正在学习"就放行下一块
RECOMMEND_LIMIT = 3


def _normalize_subject(subject):
    text = (subject or "").strip()
    if not text:
        return "数学"
    if text not in SUBJECTS:
        raise HTTPException(status_code=400,
                            detail="科目必须是：" + "、".join(SUBJECTS))
    return text



def _state_map(db, student_id, subject):
    """复用 V2.4 记忆状态：{知识点名: {"mastery": 分数, "maturity": 成熟度}}。"""
    mapping = {}
    try:
        rows = REVIEW_ENGINE.states_of(db, student_id, subject)
    except Exception:                          # noqa: BLE001
        return mapping
    for row in rows or []:
        try:
            summary = review_memory.state_summary(row)
        except Exception:                      # noqa: BLE001
            continue
        mapping[summary.get("knowledge_id") or ""] = {
            "mastery": summary.get("mastery_score"),
            "maturity": summary.get("maturity") or "",
        }
    return mapping


def _mastery_rows(db, student_id, subject):
    """知识点 → 掌握度（表里没有的即"还没开始学"）。"""
    from models import StudentKnowledgeMastery
    mapping = {}
    try:
        rows = (db.query(StudentKnowledgeMastery)
                .filter(StudentKnowledgeMastery.student_id == student_id,
                        StudentKnowledgeMastery.subject == subject).all())
    except Exception:                          # noqa: BLE001
        return mapping
    for row in rows:
        mapping[row.knowledge_id or ""] = {
            "mastery": row.mastery_score,
            "total": int(row.total_questions or 0),
            "last": str(row.last_practice_time or ""),
        }
    return mapping


def _node_of(subject, name, region, states, masteries, index, previous):
    """单个知识节点：儿童状态 + 真实数据 + 是否解锁（前置知识够不够）。"""
    state = states.get(name) or {}
    mastery_row = masteries.get(name) or {}
    score = _score_of(masteries, states, name)
    status = kid_status.status_of(score, state.get("maturity") or "")
    practiced = int(mastery_row.get("total") or 0) > 0 or score is not None
    unlocked = index == 0 or _mastery_value(masteries, states, previous) >= UNLOCK_LINE
    children = [{"knowledge_id": child, "name": child,
                 "ui_status": kid_status.status_of(
                     _score_of(masteries, states, child),
                     (states.get(child) or {}).get("maturity") or "")}
                for child in knowledge_tree.subpoints_of(subject, name)]
    return {
        "knowledge_id": name,
        "name": name,
        "region": region,
        "ui_status": status,
        "children": children,
        "is_unlocked": bool(unlocked),
        "recommended": False,
        "practiced": bool(practiced),
        "grade": int(knowledge_tree.grade_of(subject, name) or 1),
        "difficulty": int(knowledge_tree.difficulty_of(subject, name) or 0),
        "mastery_score": score,                       # 算法原始数据：儿童 UI 默认不展示
        "maturity_level": state.get("maturity") or "",
    }


def _score_of(masteries, states, name):
    """掌握度取库内实况，没有记录返回 None（= 还没开始学，不是 0 分）。"""
    row = masteries.get(name) or {}
    if row.get("mastery") is None:
        raw = (states.get(name) or {}).get("mastery")
    else:
        raw = row["mastery"]
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _mastery_value(masteries, states, name):
    """比较用的数值：没有记录按 0 分算（只用于“前置知识够不够”的判断）。"""
    value = _score_of(masteries, states, name)
    return 0.0 if value is None else value


def _empty_map(student_id, subject):
    return {"student_id": student_id, "subject": subject, "regions": [], "knowledge_nodes": [],
            "recommended": [],
            "totals": {"total": 0, "practiced": 0, "grown": 0, "mastered": 0, "long_term": 0},
            "message": "还没有数学知识地图。"}


def knowledge_map(db, student_id, subject="数学"):
    """整张知识地图：区域（领域）+ 知识节点 + 探索进度 + 推荐下一步。"""
    states = _state_map(db, student_id, subject)
    masteries = _mastery_rows(db, student_id, subject)
    nodes = []
    regions = []
    for group in knowledge_tree.domains_for(subject):
        domain = group.get("domain") or ""
        names = [name for name in (group.get("knowledge") or []) if name]
        region_nodes = []
        previous = ""
        for index, name in enumerate(names):
            node = _node_of(subject, name, domain, states, masteries, index, previous)
            node["region_icon"] = REGION_ICON.get(domain, "🌱")
            region_nodes.append(node)
            nodes.append(node)
            previous = name
        grown = sum(1 for node in region_nodes if node["ui_status"]["rank"] >= GROWN_RANK)
        mastered = sum(1 for node in region_nodes if node["ui_status"]["rank"] >= 3)
        regions.append({
            "key": domain,
            "name": domain,
            "title": "{0} {1}".format(REGION_ICON.get(domain, "🌱"), domain),
            "icon": REGION_ICON.get(domain, "🌱"),
            "total": len(region_nodes),
            "grown": grown,
            "mastered": mastered,
            "percent": int(round(100.0 * grown / len(region_nodes))) if region_nodes else 0,
            "progress_text": "{0} / {1} 知识已成长".format(grown, len(region_nodes)),
            "nodes": [node["knowledge_id"] for node in region_nodes],
        })

    recommended = _recommend(nodes)
    for node in nodes:
        node["recommended"] = node["knowledge_id"] in recommended
    return {
        "student_id": student_id,
        "subject": subject,
        "regions": regions,
        "knowledge_nodes": nodes,
        "recommended": recommended,
        "totals": {
            "total": len(nodes),
            "practiced": sum(1 for node in nodes if node["practiced"]),
            "grown": sum(1 for node in nodes if node["ui_status"]["rank"] >= GROWN_RANK),
            "mastered": sum(1 for node in nodes if node["ui_status"]["rank"] >= 3),
            "long_term": sum(1 for node in nodes if node["ui_status"]["rank"] >= 4),
        },
        "message": "点一个区域，看看里面的知识长成什么样啦。",
    }


def _recommend(nodes, limit=RECOMMEND_LIMIT):
    """推荐下一步：已解锁、还没掌握、按年级+难度从易到难（复用知识树真实数据）。"""
    candidates = [node for node in nodes
                  if node["is_unlocked"] and node["ui_status"]["rank"] < 3]
    candidates.sort(key=lambda node: (node["ui_status"]["rank"], node["grade"], node["difficulty"]))
    return [node["knowledge_id"] for node in candidates[:max(1, int(limit or 1))]]


@router.get("/knowledge-map/{student_id}")
def knowledge_map_api(student_id: int, subject: str = "数学", db: Session = Depends(get_db)):
    """儿童知识地图：区域 → 知识节点，状态全部来自真实学习数据。"""
    name = _normalize_subject(subject)
    if student_id < 1:
        return _empty_map(student_id, name)
    try:
        return knowledge_map(db, student_id, name)
    except HTTPException:
        raise
    except Exception:                          # noqa: BLE001 - 兜底，不暴露内部细节
        try:
            db.rollback()
        except Exception:                      # noqa: BLE001
            pass
        return _empty_map(student_id, name)
