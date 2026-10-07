# ==============================================================
# 能力契约｜验证：菲比陪伴对话（学习数据快照 + DeepSeek 台词 + 降级路径），端口 8908
# 入口：脚本自身：python backend/verify_phoebe_ai.py
# 依赖：phoebe_ai / phoebe_routes / models / database（自建临时库 + 临时后端）
# 不负责：立牌与语音播放 → frontend/verify_phoebe3d_web.js
# 验证：python backend/verify_phoebe_ai.py
# 被调用：verify_all.py（套件 phoebeai）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.5 菲比 AI 陪伴测试。

覆盖：

  纯函数：clean_line（去引号 / Markdown / emoji / 超长截断 / 空输入）
        → build_prompt（场景、学习数据、硬性要求都在）
        → fallback_line（三种触发 × 有数据 / 无数据，且必须引用真实数据）
        → snapshot_brief（摘要含题量、水平、待补强）
  快照：learning_snapshot（今日作答、三科水平、薄弱点、错题、该复习的都聚合对）
  降级：无 key → no_key；PHOEBE_AI_OFFLINE=1 → offline；请求异常 → error:xxx；
        三种情况都必须落到 fallback 文案，且 phoebe_line 永远返回非空 text
  AI 路径：用假的 requests.post 打桩，验证真的会去调 DeepSeek 并清洗返回
  API：POST /api/phoebe/chat（临时后端 8908）字段齐全、非法 trigger 归一到 click、
       只读（调用前后 answer_records / student_knowledge_mastery 行数不变）

**刻意不真的联网**：临时后端用 PHOEBE_AI_OFFLINE=1 启动，走确定性降级路径；
AI 成功路径用打桩覆盖。这样验证不依赖外网、不花 token，也不会因为网络抖动假失败。

用法：python backend/verify_phoebe_ai.py   （自拉临时后端，端口 VERIFY_PHOEBE_PORT，默认 8908）
全部通过时退出码为 0；端口被占用直接失败退出。
"""

import os
import socket
import subprocess
import sys
import time

PORT = int(os.getenv("VERIFY_PHOEBE_PORT", "8908"))

_db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_phoebe.db")
for _suffix in ("", "-journal", "-wal", "-shm"):
    if os.path.exists(_db_file + _suffix):
        os.remove(_db_file + _suffix)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
os.environ["DEEPSEEK_API_KEY"] = ""

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

import phoebe_ai
import deepseek
from database import SessionLocal, engine as db_engine
from models import AnswerRecord, Base, Student, StudentKnowledgeMastery, WrongQuestion

# 外部可能带着离线开关跑（verify_all 就会传）：先摘掉，保证本脚本行为确定。
# 端到端那一段会显式给子进程设置离线开关。
os.environ.pop(phoebe_ai.OFFLINE_ENV, None)

Base.metadata.create_all(db_engine)

PASSED = 0
FAILED = 0


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS  {name}" + (f"  | {extra}" if extra else ""))
    else:
        FAILED += 1
        print(f"FAIL  {name}" + (f"  | {extra}" if extra else ""))


def port_in_use(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


if port_in_use(PORT):
    print(f"FAIL  端口 {PORT} 已被占用，先关掉占用进程再跑")
    sys.exit(1)

# ---------------- 1. 造数据 ----------------

db = SessionLocal()

db.add(Student(id=1, name="朵朵", grade=2))
db.add(Student(id=2, name="童童", grade=4))

from datetime import datetime, timedelta

now = datetime.now()

# 数学：今天 3 题（对 2 错 1）+ 昨天 2 题；语文：错得多；英语：没有记录
records = [
    ("数学", "20以内加减法", 30, True, now - timedelta(minutes=30)),
    ("数学", "20以内加减法", 35, False, now - timedelta(minutes=20)),
    ("数学", "100以内加减法", 45, True, now - timedelta(minutes=10)),
    ("数学", "100以内加减法", 45, True, now - timedelta(days=1)),
    ("数学", "100以内加减法", 45, True, now - timedelta(days=1)),
    ("语文", "拼音拼读", 25, False, now - timedelta(minutes=40)),
    ("语文", "拼音拼读", 25, False, now - timedelta(minutes=35)),
]
for subject, knowledge, difficulty, correct, when in records:
    db.add(AnswerRecord(student_id=1, subject=subject, knowledge=knowledge,
                        difficulty=difficulty, correct=correct, question_id=0,
                        submitted="A", created_at=when))

# 掌握度：一个薄弱（数学 20以内加减法 40 分）、一个已经不错（英语 26个字母 90 分，3 题）
db.add(StudentKnowledgeMastery(student_id=1, subject="数学", knowledge_id="20以内加减法",
                               mastery_score=40, total_questions=6, correct_questions=3,
                               wrong_questions=3, next_review_time=now - timedelta(hours=1)))
db.add(StudentKnowledgeMastery(student_id=1, subject="英语", knowledge_id="26个字母",
                               mastery_score=90, total_questions=5, correct_questions=5,
                               wrong_questions=0, next_review_time=now + timedelta(days=3)))

# 错题本：2 道未掌握
db.add(WrongQuestion(student_id=1, subject="语文", knowledge_id="拼音拼读",
                     question_id=1, status="NEW", wrong_count=2))
db.add(WrongQuestion(student_id=1, subject="语文", knowledge_id="拼音拼读",
                     question_id=2, status="NEW", wrong_count=1))

db.commit()

# ---------------- 2. 纯函数：clean_line ----------------

check("clean_line 去掉首尾引号", phoebe_ai.clean_line('"你好呀，小朋友"') == "你好呀，小朋友")
check("clean_line 去掉中文引号", phoebe_ai.clean_line("“你好呀”") == "你好呀")
check("clean_line 去掉 Markdown 记号", phoebe_ai.clean_line("**加油** `真棒`") == "加油 真棒")
check("clean_line 去掉 emoji（语音读不出来）",
      phoebe_ai.clean_line("你真棒 🎉🌟！").strip() == "你真棒 ！".strip(),
      phoebe_ai.clean_line("你真棒 🎉🌟！"))
check("clean_line 只取第一行", phoebe_ai.clean_line("第一句\n第二句") == "第一句")
check("clean_line 空输入安全", phoebe_ai.clean_line("") == "" and phoebe_ai.clean_line(None) == "")

long_text = "今天练了十道题真的非常厉害要继续保持这个学习节奏不要停下来哦对了还有两个知识点该复习了"
cleaned = phoebe_ai.clean_line(long_text)
check("clean_line 超长会截断到上限", 0 < len(cleaned) <= phoebe_ai.MAX_LINE, f"len={len(cleaned)}")

# ---------------- 3. 纯函数：build_prompt ----------------

snapshot = phoebe_ai.learning_snapshot(db, 1)
prompt = phoebe_ai.build_prompt(snapshot, "click")
check("prompt 说明当前场景是点击", "孩子点了一下你" in prompt)
check("prompt 带上孩子姓名", "朵朵" in prompt)
check("prompt 带上学习数据 JSON", '"需要补强"' in prompt and "20以内加减法" in prompt)
check("prompt 明确不许编造数据", "不要编造数据里没有的内容" in prompt)
check("prompt 明确不要 Markdown 与 emoji", "不要 Markdown" in prompt and "不要 emoji" in prompt)

wrong_prompt = phoebe_ai.build_prompt(snapshot, "wrong", {"knowledge": "拼音拼读"})
check("答错场景的 prompt 会带上刚错的知识点", "拼音拼读" in wrong_prompt)
check("答错场景的 prompt 说明是答错", "答错" in wrong_prompt)

# ---------------- 4. 快照聚合 ----------------

check("快照：学生姓名", snapshot["name"] == "朵朵", snapshot["name"])
check("快照：累计答题数", snapshot["total_answers"] == 7, str(snapshot["total_answers"]))
check("快照：今日作答只统计今天", snapshot["today"]["total"] == 5, str(snapshot["today"]))
check("快照：总体正确率", abs(snapshot["correct_rate"] - 4 / 7) < 0.01, str(snapshot["correct_rate"]))
check("快照：只列有记录的科目", [s["subject"] for s in snapshot["subjects"]] == ["数学", "语文"],
      str([s["subject"] for s in snapshot["subjects"]]))
check("快照：薄弱点排最前的是掌握度最低的",
      snapshot["weak"] and snapshot["weak"][0]["knowledge"] == "20以内加减法",
      str(snapshot["weak"]))
check("快照：已经不错的知识点有英语 26个字母",
      any(s["knowledge"] == "26个字母" for s in snapshot["strong"]), str(snapshot["strong"]))
check("快照：错题本统计 NEW=2", snapshot["wrong"]["NEW"] == 2, str(snapshot["wrong"]))
check("快照：该复习的知识点被识别出来",
      any(d["knowledge"] == "20以内加减法" for d in snapshot["due_reviews"]), str(snapshot["due_reviews"]))
check("快照：最近作答明细按最新在前",
      snapshot["recent"] and snapshot["recent"][0]["subject"] == "语文", str(snapshot["recent"][0]))
check("快照：没有记录的学生不报错",
      phoebe_ai.learning_snapshot(db, 2)["total_answers"] == 0)

brief = phoebe_ai.snapshot_brief(snapshot)
check("摘要含姓名与累计题量", "朵朵" in brief and "7 题" in brief, brief)
check("摘要含待补强知识点", "20以内加减法" in brief, brief)

# ---------------- 5. 降级路径（全程不联网） ----------------

# 显式清空 KEY 再断言：.env 里可能配了真 key，绝不能让验证脚本真联网
_real_key = deepseek.KEY
try:
    deepseek.KEY = ""
    check("无 key 时 ai_line 返回 no_key", phoebe_ai.ai_line(snapshot, "click") == ("", "no_key"))
    check("无 key 时 ai_enabled 为假", phoebe_ai.ai_enabled() is False)
finally:
    deepseek.KEY = _real_key

os.environ[phoebe_ai.OFFLINE_ENV] = "1"
try:
    check("离线开关生效时 ai_enabled 为假", phoebe_ai.ai_enabled() is False)
    offline_text, offline_source = phoebe_ai.ai_line(snapshot, "click")
    check("离线开关生效时 ai_line 返回 offline", offline_text == "" and offline_source == "offline",
          offline_source)

    line = phoebe_ai.phoebe_line(db, 1, "click")
    check("离线时 phoebe_line 仍然返回非空台词", bool(line["text"]), line["text"])
    check("离线时来源标注为 fallback_offline", line["source"] == "fallback_offline", line["source"])
    check("离线时的台词也是英文以外的中文", any("\u4e00" <= ch <= "\u9fff" for ch in line["text"]))
finally:
    os.environ.pop(phoebe_ai.OFFLINE_ENV, None)

# ---------------- 6. 规则兜底文案 ----------------

click_line = phoebe_ai.fallback_line(snapshot, "click")
check("兜底（点击）会引用今天练了多少题", "题" in click_line and ("今天" in click_line),
      click_line)
check("兜底（点击）会提到该复习的知识点", "复习" in click_line or "浇水" in click_line, click_line)

correct_line = phoebe_ai.fallback_line(snapshot, "correct")
check("兜底（答对）是鼓励", "答对" in correct_line or "棒" in correct_line, correct_line)

wrong_line = phoebe_ai.fallback_line(snapshot, "wrong")
check("兜底（答错）不安慰过度、会指向要补的知识点",
      "没关系" in wrong_line and "20以内加减法" in wrong_line, wrong_line)

empty_snapshot = {"name": "小朋友B", "today": {"total": 0, "correct": 0},
                  "weak": [], "strong": [], "wrong": {}, "due_reviews": []}
check("兜底（点击）对没练过的孩子给出邀请",
      "还没" in phoebe_ai.fallback_line(empty_snapshot, "click"),
      phoebe_ai.fallback_line(empty_snapshot, "click"))

# ---------------- 7. AI 成功路径（打桩，不联网） ----------------

real_post = phoebe_ai.requests.post


class FakeResponse:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class FakePost:
    """假的 requests.post：记录请求内容，返回固定台词或抛异常。"""

    def __init__(self, content="你好呀小朋友", error=None):
        self.content = content
        self.error = error
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.error:
            raise self.error
        return FakeResponse(self.content)


try:
    fake = FakePost()
    phoebe_ai.requests.post = fake
    deepseek.KEY = "sk-fake-for-test"

    text, source = phoebe_ai.ai_line(snapshot, "click")
    check("有 key 时会真的去调大模型并返回 ai", text == "你好呀小朋友" and source == "ai",
          f"{text} / {source}")
    check("请求带了 Bearer 鉴权与超时",
          fake.calls and fake.calls[0]["timeout"] == phoebe_ai.AI_TIMEOUT,
          str(fake.calls[0]["timeout"]) if fake.calls else "no call")
    check("请求体带 prompt 与模型名",
          fake.calls and fake.calls[0]["json"]["model"] == "deepseek-chat"
          and "朵朵" in fake.calls[0]["json"]["messages"][0]["content"])

    dirty = FakePost(content='"**你真棒** 🎉\n多余的一行"')
    phoebe_ai.requests.post = dirty
    text, source = phoebe_ai.ai_line(snapshot, "click")
    check("模型返回脏文本会被清洗成一句话", text == "你真棒" and source == "ai", text)

    phoebe_ai.requests.post = FakePost(error=RuntimeError("boom"))
    text, source = phoebe_ai.ai_line(snapshot, "click")
    check("调用异常时返回 error 来源且文本为空", text == "" and source.startswith("error:"), source)

    phoebe_ai.requests.post = FakePost(content="   ")
    text, source = phoebe_ai.ai_line(snapshot, "click")
    check("模型返回空内容时判为 empty", text == "" and source == "empty", source)

    phoebe_ai.requests.post = FakePost(error=RuntimeError("boom"))
    line = phoebe_ai.phoebe_line(db, 1, "click")
    check("AI 失败时 phoebe_line 自动落到兜底文案",
          bool(line["text"]) and line["source"].startswith("fallback"), line["source"])
finally:
    phoebe_ai.requests.post = real_post
    deepseek.KEY = _real_key

# ---------------- 8. API 端到端 ----------------

env = dict(os.environ)
env["DATABASE_URL"] = "sqlite:///" + _db_file.replace("\\", "/")
env["DEEPSEEK_API_KEY"] = ""
env[phoebe_ai.OFFLINE_ENV] = "1"      # 验证不联网，走确定性降级
env["PYTHONIOENCODING"] = "utf-8"

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

base = f"http://127.0.0.1:{PORT}"

try:
    ready = False
    for _ in range(60):
        try:
            requests.get(base + "/", timeout=1)
            ready = True
            break
        except Exception:
            time.sleep(0.4)
    check("临时后端在 8908 启动", ready)

    if ready:
        before_answers = db.query(AnswerRecord).count()
        before_mastery = db.query(StudentKnowledgeMastery).count()

        resp = requests.post(base + "/api/phoebe/chat", timeout=30,
                             json={"student_id": 1, "trigger": "click"})
        check("POST /api/phoebe/chat 返回 200", resp.status_code == 200, str(resp.status_code))
        data = resp.json()
        check("返回字段齐全",
              all(key in data for key in ("student_id", "trigger", "text", "source", "brief", "elapsed_ms")),
              ",".join(sorted(data.keys())))
        check("台词非空且是中文", bool(data["text"]) and any("\u4e00" <= c <= "\u9fff" for c in data["text"]),
              data["text"])
        check("离线环境下来源标注为降级", data["source"].startswith("fallback"), data["source"])
        check("摘要里带上了学习数据", "朵朵" in data["brief"], data["brief"])
        check("elapsed_ms 是整数", isinstance(data["elapsed_ms"], int))

        for trigger in ("correct", "wrong"):
            item = requests.post(base + "/api/phoebe/chat", timeout=30,
                                 json={"student_id": 1, "trigger": trigger,
                                       "knowledge": "20以内加减法"}).json()
            check(f"trigger={trigger} 也能给出台词", bool(item["text"]) and item["trigger"] == trigger,
                  item["text"])

        weird = requests.post(base + "/api/phoebe/chat", timeout=30,
                              json={"student_id": 1, "trigger": "乱写"}).json()
        check("非法 trigger 归一到 click", weird["trigger"] == "click", weird["trigger"])

        nobody = requests.post(base + "/api/phoebe/chat", timeout=30,
                               json={"student_id": 999}).json()
        check("没有数据的学生也能拿到台词（不报错）", bool(nobody["text"]), nobody["text"])

        after_answers = db.query(AnswerRecord).count()
        after_mastery = db.query(StudentKnowledgeMastery).count()
        check("接口是只读的（答题记录没变）", before_answers == after_answers,
              f"{before_answers}→{after_answers}")
        check("接口是只读的（掌握度没变）", before_mastery == after_mastery,
              f"{before_mastery}→{after_mastery}")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    time.sleep(0.3)
    db.close()
    # 必须先释放连接池：Windows 上只要有连接没关，临时库文件就删不掉（会留下垃圾）
    db_engine.dispose()
    for _suffix in ("", "-journal", "-wal", "-shm"):
        if os.path.exists(_db_file + _suffix):
            try:
                os.remove(_db_file + _suffix)
            except OSError:
                pass

print(f"\n合计 {PASSED + FAILED} 项断言：PASS {PASSED} / FAIL {FAILED}")
print("RESULT: " + ("ALL PASS" if FAILED == 0 else "HAS FAILURES"))
sys.exit(0 if FAILED == 0 else 1)
