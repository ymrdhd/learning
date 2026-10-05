# API_UPDATE.md — V2.5 新增接口说明（Agent 5 / api-layer）

本次实际新增 5 个路由模块（`recovery_routes.py` / `task_routes.py` / `habit_routes.py` / `active_recall_routes.py` / `daily_routes.py`），并已由 Lead 在 `backend/main.py` 完成注册。

| 文件 | 内容 | 统一前缀 |
|---|---|---|
| `backend/recovery_routes.py` | 错题康复（含兼容 path 接口） | `/api/recovery` |
| `backend/task_routes.py` | 每日任务与五段每日计划 | `/api/tasks` |
| `backend/habit_routes.py` | 学习习惯画像 / 休息保护 / 学习目标 | `/api/habit` |
| `backend/active_recall_routes.py` | 主动回忆（出卡 / 作答 / 当日小结） | `/api/active-recall` |
| `backend/daily_routes.py` | 每日总结与结束页数据 | `/api` |

`main.py` 的 include_router 区已按下列方式接入（顺序为 diagnostic / knowledge / adaptive / review / ability / phoebe / recovery / task / habit / active_recall / daily，路径无冲突），应用标题已升级为 `AI小学学习系统 V2.5`：

```python
from recovery_routes import router as recovery_router      # noqa
from task_routes import router as task_router              # noqa
from habit_routes import router as habit_router            # noqa
from active_recall_routes import router as active_recall_router  # noqa
from daily_routes import router as daily_router            # noqa
app.include_router(recovery_router)
app.include_router(task_router)
app.include_router(habit_router)
app.include_router(active_recall_router)
app.include_router(daily_router)
```

### 兼容 path 接口（V2.5 追加，未新建第二套 API）

按「已有相似接口优先兼容」的约束，在原有 query-string 接口之外补齐 path 形式（内部转发到同一实现）：

| 方法 | 路径 | 对应原接口 |
|---|---|---|
| GET | `/api/recovery/list/{student_id}` | `/api/recovery/list` |
| GET | `/api/recovery/{recovery_id}` | 新增单条详情（越权→空结构） |
| GET | `/api/recovery/next-question` | `POST /api/recovery/question` |
| GET | `/api/tasks/today/{student_id}` | `/api/tasks/today` |
| GET | `/api/tasks/plan/{student_id}` | 新增只读每日计划预览 |
| POST | `/api/tasks/start` | 新增学习启动仪式（落库幂等） |
| POST | `/api/tasks/{task_id}/complete` | `/api/tasks/complete` |
| GET | `/api/habit/profile/{student_id}` | `/api/habit/profile` |
| GET | `/api/habit/rest/{student_id}` | 新增休息保护状态 |
| POST | `/api/habit/rest` | 新增休息保护（每月 2 次） |
| GET | `/api/habit/goal/{student_id}` | 新增当前学习目标（SYSTEM） |
---

## 1. 接口清单

### 1.1 错题康复 `backend/recovery_routes.py`（内部调 `recovery.engine.DEFAULT_ENGINE`）

| 方法 | 路径 | 请求字段 | 响应字段 | 错误码 |
|---|---|---|---|---|
| GET | `/api/recovery/list` | `student_id`(必,≥1)、`subject?`、`state?`、`limit?`(0–500,默认 50) | `student_id,total,stats{new,analyzing,learning,practicing,verifying,mastered,total,mastered_rate},items[{recovery_id,question_id,subject,knowledge,state,state_text,wrong_count,attempts,consecutive_correct,fail_count,max_level_used,question,correct_answer,analysis,error_type,next_verify_time,created_time}]` | 400 subject/state 非法；422 缺/非法 student_id |
| POST | `/api/recovery/start` | `student_id`(必)、`recovery_id?`、`question_id?`（二者其一） | `student_id,recovery_id,question_id,state,state_text,teaching{level,level_text,hint,error_location,steps,full_explanation,source},item{同 list 条目}` | 422 缺 student_id |
| POST | `/api/recovery/question` | `student_id`(必)、`recovery_id`、`hint_level?`(0–4) | `student_id,recovery_id,state,hint_level,question{question_id,question,qtype,options,knowledge,difficulty,source,variant},teaching{...}` | 422 |
| POST | `/api/recovery/answer` | `student_id`(必)、`recovery_id`、`answer`、`question_id?`、`hint_level?`(0–4)、`minutes?`(≥0) | `student_id,correct,correct_answer,analysis,state,state_text,changed,next_action,hint_level,hint,variant,stats{...},review_next` | 422 |
| POST | `/api/recovery/verify` | `student_id`(必)、`recovery_id`、`answer` | 同 answer ＋ `mastered:bool` | 422 |
| POST | `/api/recovery/hint` | `student_id`(必)、`recovery_id`、`level?`(0–4，0=按策略自动) | `student_id,level,level_text,hint,error_location,steps,full_explanation,source` | 422 |

### 1.2 每日任务 `backend/task_routes.py`（内部调 `habit.DEFAULT_ENGINE`）

| 方法 | 路径 | 请求字段 | 响应字段 | 错误码 |
|---|---|---|---|---|
| GET | `/api/tasks/today` | `student_id`(必)、`date?`(YYYY-MM-DD，默认今天) | `student_id,date,generated,tasks[{task_id,task_type,task_type_text,title,subject,knowledge,target_count,complete_count,duration_minutes,target_minutes,status,status_text,priority,goal,reason}],summary{total,done,pending,completion_rate,minutes,mix{new_learning,weakness,review}}`（引擎另附 `mix_tasks`，纯新增字段） | 400 date 非法；422 |
| POST | `/api/tasks/complete` | `student_id`(必)、`task_id`、`minutes?`(0–1440)、`count?`(≥0)、`done?`(默认 true) | `student_id,task_id,status,status_text,complete_count,duration_minutes,summary{...},profile{同 /api/habit/profile}` | 422 |

### 1.3 学习习惯 `backend/habit_routes.py`（内部调 `habit.DEFAULT_ENGINE`）

| 方法 | 路径 | 请求字段 | 响应字段 | 错误码 |
|---|---|---|---|---|
| GET | `/api/habit/profile` | `student_id`(必)、`date?` | `student_id,current_streak,longest_streak,total_days,total_tasks,completed_tasks,completion_rate,total_minutes,today_minutes,level,level_text,badges[{key,name,icon,got}],last_active_date,recent[{date,done,total,minutes,rate}]` | 400 date 非法；422 |
| GET | `/api/habit/stats` | `student_id`(必)、`days?`(1–90，默认 7)、`date?` | `student_id,days,items[{date,done,total,minutes,rate}],avg_rate,total_minutes` | 400 date 非法；422 |

---

## 2. 通用约定

1. **student_id 来源**：GET 走查询串，POST 走请求体（`Pydantic` 模型 `student_id: int = Field(..., ge=1)`）；每个接口的响应体里都带 `student_id`。
2. **空结构而不是 404**：学生不存在 / 没有数据 / `recovery_id`、`task_id` 不属于该学生 → HTTP 200 + 空结构（`total=0` / `items=[]` / `tasks=[]` / 全 0 stats / 徽章 `got=false`），响应体内**不含任何他人的题目、答案、解析、任务标题**。
3. **参数错误**：缺字段 / 类型错 / 越界（`student_id<1`、`hint_level>4`、`minutes>1440`、`days>90`）由 Pydantic 返回 **422**；语义非法（`state`、`subject`、`date` 格式）由路由层返回 **400**。
4. **绝不 500**：每个接口内部业务调用都包在 `_safe(db, call, fallback)` 里，任何内部异常 → 回滚 + 返回该接口的空结构。外部 AI 调用（提示/变式题）全部在 `recovery` 包与 `ai_recovery.py` 内部完成，异常在引擎层已降级（`source` 字段可区分 `ai` / `rule`），不阻塞接口。
5. **无新依赖**：只用了 fastapi / pydantic / sqlalchemy（均已在环境里），未动 `requirements.txt`。

---

## 3. 真实请求与响应样例

自测方式（用后即删的临时件）：`backend/_tmp_api_smoke.py` 把 `DATABASE_URL` 指向临时库
`sqlite:///C:/Users/1/Desktop/ai_learning_system/backend/_tmp_agent.db`，自己建一个只 include 这 3 个 router 的最小 FastAPI app，
用 uvicorn 起在 **127.0.0.1:8920**（空闲端口），再用 `requests` 发真实 HTTP 请求。种子数据：学生 A(id=1)/B(id=2)、
数学题 2 道（`3 × 4 = ?` 答案 B；`2 × 5 = ?` 答案 A）、学生 1 的一条 `wrong_questions` 记录，再经
`RecoveryEngine.sync_from_wrong_book` 进康复队列。命令：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:DATABASE_URL='sqlite:///C:/Users/1/Desktop/ai_learning_system/backend/_tmp_agent.db'
C:\Python313\python.exe backend\_tmp_api_smoke.py
```

### 3.1 康复列表（正常，学生 1）

```
REQ  GET /api/recovery/list?student_id=1
RES  HTTP 200
{"student_id":1,"total":1,"stats":{"new":1,"analyzing":0,"learning":0,"practicing":0,"verifying":0,"mastered":0,"total":1,"mastered_rate":0.0},
 "items":[{"recovery_id":1,"question_id":1,"subject":"数学","knowledge":"表内乘法","state":"NEW","state_text":"刚进康复队列，还没分析",
 "wrong_count":1,"attempts":1,"consecutive_correct":0,"fail_count":1,"max_level_used":0,"question":"3 × 4 = ?","correct_answer":"B",
 "analysis":"三四十二","error_type":"","next_verify_time":"","created_time":"2026-10-04 23:44"}]}
```

### 3.2 开始教学 `POST /api/recovery/start`

```
REQ  POST /api/recovery/start
BODY {"student_id": 1, "recovery_id": 1}
RES  HTTP 200
{"recovery_id":1,"question_id":1,"state":"LEARNING","state_text":"跟着分层提示学",
 "teaching":{"level":1,"level_text":"方向提示","hint":"这道题在考乘法口诀哦，先想想几个相同的数加在一起，看看能不能用口诀一下子说出来～",
             "error_location":"","steps":[],"full_explanation":"","source":"ai"},
 "item":{"recovery_id":1,"question_id":1,"subject":"数学","knowledge":"表内乘法","state":"LEARNING","state_text":"跟着分层提示学",
         "wrong_count":1,"attempts":1,"consecutive_correct":0,"fail_count":1,"max_level_used":1,"question":"3 × 4 = ?",
         "correct_answer":"B","analysis":"三四十二", ...}}
```

### 3.3 出题 `POST /api/recovery/question`（变式题）

```
REQ  POST /api/recovery/question
BODY {"student_id": 1, "recovery_id": 1}
RES  HTTP 200
{"recovery_id":1,"state":"LEARNING","hint_level":2,
 "question":{"question_id":3,"question":"5 × 6 = ?","qtype":"choice","options":{"A":"11","B":"30","C":"25","D":"35"},
             "knowledge":"表内乘法","difficulty":50,"source":"rule","variant":true},
 "teaching":{"level":2,"level_text":"错误定位","hint":"咱们一起看看 5 个 6 加起来是多少，是不是数着数着漏掉了一个 6 呀？",
             "error_location":"错在把 5 个 6 相加时，可能少数了一个 6，或者把 5 和 6 相加当成了乘法。","steps":[],"full_explanation":"","source":"ai"},
 "student_id":1}
```

### 3.4 判分 `POST /api/recovery/answer`（答对 → PRACTICING）

```
REQ  POST /api/recovery/answer
BODY {"student_id": 1, "recovery_id": 1, "answer": "B", "minutes": 3}
RES  HTTP 200
{"correct":true,"correct_answer":"B","analysis":"根据表内乘法口诀“五六三十”，5 × 6 = 30，所以正确答案是 B。",
 "state":"PRACTICING","state_text":"练同知识点的变式题","changed":true,"next_action":"practice","hint_level":2,
 "hint":"别急，咱们一起看看 5 × 6 是几个几相加，数一数就清楚啦。","variant":true,
 "stats":{"new":0,"analyzing":0,"learning":0,"practicing":1,"verifying":0,"mastered":0,"total":1,"mastered_rate":0.0},
 "student_id":1,"review_next":""}
```

答错时（`answer:"D"`）引擎把状态打回 `NEW`、`next_action:"analyze"`，路由层结构与上完全一致：

```
RES  HTTP 200
{"correct":false,"correct_answer":"B","analysis":"...口诀“五六三十”...","state":"NEW","state_text":"刚进康复队列，还没分析",
 "changed":true,"next_action":"analyze","hint_level":3,"hint":"5×6就是5个6加在一起，咱们一步步来数～","variant":true,...}
```

### 3.5 提示 `POST /api/recovery/hint`

```
REQ  POST /api/recovery/hint
BODY {"student_id": 1, "recovery_id": 1, "level": 2}
RES  HTTP 200
{"student_id":1,"level":2,"level_text":"错误定位","hint":"咱们来检查一下，3×4是把3个4加起来，你数对了吗？",
 "error_location":"可能错在把3×4算成了3+4，或者数数的时候漏掉了一组。","steps":[],"full_explanation":"","source":"ai"}
```

### 3.6 进入原题验证（`review_next` 真实有值）

```
REQ  POST /api/recovery/answer
BODY {"student_id": 1, "recovery_id": 1, "answer": "B", "question_id": 1}
RES  HTTP 200
{"correct":true,"correct_answer":"B","analysis":"三四十二","state":"VERIFYING","state_text":"原题验证中","changed":true,
 "next_action":"verify","hint_level":4,"hint":"3乘4就是4个3加在一起，我们一起来数一数吧！","variant":false,
 "stats":{"new":0,"analyzing":0,"learning":0,"practicing":0,"verifying":1,"mastered":0,"total":1,"mastered_rate":0.0},
 "student_id":1,"review_next":"2026-10-05 23:45"}      ← 引擎未返回，由路由层从 detail.next_verify_time 补齐
```

### 3.7 原题验证 `POST /api/recovery/verify`（→ MASTERED）

```
REQ  POST /api/recovery/verify
BODY {"student_id": 1, "recovery_id": 1, "answer": "B"}
RES  HTTP 200
{"correct":true,"correct_answer":"B","analysis":"三四十二","state":"MASTERED","state_text":"已康复","changed":false,
 "next_action":"celebrate","hint_level":1,"hint":"这道题在考乘法口诀，先想一想“几个几相加”是什么意思，再回忆对应的口诀。",
 "variant":false,"stats":{"new":0,"analyzing":0,"learning":0,"practicing":0,"verifying":0,"mastered":1,"total":1,"mastered_rate":1.0},
 "mastered":true,"student_id":1,"review_next":""}
```

随后 `GET /api/recovery/list?student_id=1` 的 `stats.mastered=1, mastered_rate=1.0`，条目 `state:"MASTERED"`。

### 3.8 今日任务 `GET /api/tasks/today`

```
REQ  GET /api/tasks/today?student_id=1
RES  HTTP 200
{"student_id":1,"date":"2026-10-04","generated":true,
 "tasks":[{"task_id":1,"task_type":"new_learning","task_type_text":"新知识","title":"数学 · 新知识","subject":"数学",
           "knowledge":"20以内加减法","target_count":5,"complete_count":0,"duration_minutes":0,"target_minutes":8,
           "status":"pending","status_text":"待完成","priority":1,"goal":"认识新知识「20以内加减法」，做 5 题",
           "reason":"还没有练习记录，先从最基础的知识点开始"}, ... 共 9 条 ...],
 "summary":{"total":9,"done":0,"pending":9,"completion_rate":0.0,"minutes":0,"mix":{"new_learning":20,"weakness":12,"review":8},
            "mix_tasks":{"new_learning":3,"weakness":3,"review":3}}}
```

首次访问 `generated:true` 并落库；同一学生当天再次访问 `generated:false` 且 `task_id` 不变（幂等，已验证 step 18/19）。

### 3.9 上报完成 `POST /api/tasks/complete`

```
REQ  POST /api/tasks/complete
BODY {"student_id": 1, "task_id": 1, "minutes": 10, "count": 5}
RES  HTTP 200
{"student_id":1,"task_id":1,"task_type":"new_learning","status":"done","status_text":"已完成","complete_count":5,"target_count":5,
 "duration_minutes":10,
 "summary":{"total":9,"done":1,"pending":8,"completion_rate":0.1111,"minutes":10,"mix":{"new_learning":20,"weakness":12,"review":8},
            "mix_tasks":{"new_learning":3,"weakness":3,"review":3}},
 "profile":{"student_id":1,"current_streak":1,"longest_streak":1,"total_days":1,"total_tasks":9,"completed_tasks":1,
            "completion_rate":0.1111,"total_minutes":10,"today_minutes":10,"level":1,"level_text":"学习小鲸鱼",
            "badges":[{"key":"first_day","name":"第一次学习","icon":"🐣","got":true},{"key":"streak_3",...,"got":false}, ...],
            "last_active_date":"2026-10-04","recent":[{... 近 7 天 ...}]}}
```

### 3.10 习惯画像 `GET /api/habit/profile`

```
REQ  GET /api/habit/profile?student_id=1
RES  HTTP 200
{"student_id":1,"current_streak":1,"longest_streak":1,"total_days":1,"total_tasks":9,"completed_tasks":1,
 "completion_rate":0.1111,"total_minutes":10,"today_minutes":10,"level":1,"level_text":"学习小鲸鱼",
 "badges":[{"key":"first_day","name":"第一次学习","icon":"🐣","got":true},
           {"key":"streak_3","name":"坚持三天","icon":"🔥","got":false},
           {"key":"streak_7","name":"坚持一周","icon":"⭐","got":false},
           {"key":"streak_30","name":"坚持一月","icon":"👑","got":false},
           {"key":"rate_80","name":"高效完成","icon":"🎯","got":false},
           {"key":"minutes_100","name":"学习百分钟","icon":"⏰","got":false}],
 "last_active_date":"2026-10-04",
 "recent":[{"date":"2026-10-03","done":0,"total":0,"minutes":0,"rate":0.0},
           {"date":"2026-10-04","done":1,"total":9,"minutes":10,"rate":0.1111}]}
```

### 3.11 习惯统计 `GET /api/habit/stats`

```
REQ  GET /api/habit/stats?student_id=1&days=3
RES  HTTP 200
{"student_id":1,"days":3,
 "items":[{"date":"2026-10-02","done":0,"total":0,"minutes":0,"rate":0.0},
          {"date":"2026-10-03","done":0,"total":0,"minutes":0,"rate":0.0},
          {"date":"2026-10-04","done":1,"total":9,"minutes":10,"rate":0.1111}],
 "avg_rate":0.037,"total_minutes":10}
```

### 3.12 错误与空结构样例（全部实测）

| # | 请求 | 结果 |
|---|---|---|
| 2 | `GET /api/recovery/list?student_id=2` | 200 `{"student_id":2,"total":0,"stats":{全部 0},"items":[]}` |
| 3 | `GET /api/recovery/list?student_id=99` | 200 同上（学生不存在 → 空结构，不是 404） |
| 4 | `GET /api/recovery/list?student_id=1&state=BOGUS` | 400 `{"detail":"state 只能是：NEW、ANALYZING、LEARNING、PRACTICING、VERIFYING、MASTERED"}` |
| 5 | `GET /api/recovery/list` | 422 `{"detail":[{"type":"missing","loc":["query","student_id"],"msg":"Field required"}]}` |
| 6 | `GET /api/recovery/list?student_id=0` | 422 `{"type":"greater_than_equal","loc":["query","student_id"],...,"ctx":{"ge":1}}` |
| 14 | `POST /api/recovery/answer`（学生 2 用学生 1 的 recovery_id=1） | 200 空结果：`{"student_id":2,"correct":false,"correct_answer":"","analysis":"","state":"","state_text":"","changed":false,"next_action":"","hint_level":0,"hint":"","variant":false,"stats":{全 0},"review_next":""}` |
| 22 | `GET /api/tasks/today?student_id=1&date=2026-13-99` | 400 `{"detail":"date 必须是 YYYY-MM-DD"}` |
| 26 | `POST /api/tasks/complete` `{"minutes":99999}` | 422 `{"type":"less_than_equal","loc":["body","minutes"],...,"ctx":{"le":1440}}` |
| 29 | `GET /api/habit/profile?student_id=99` | 200 全 0 + 6 枚徽章 `got:false`，`recent` 为近 7 天空档 |
| 30 | `GET /api/habit/profile?student_id=1&date=x` | 400 `{"detail":"date 必须是 YYYY-MM-DD"}` |
| 32 | `GET /api/habit/stats?student_id=1&days=999` | 422 `{"type":"less_than_equal","loc":["query","days"],...,"ctx":{"le":90}}` |
| 33 | `GET /api/habit/stats?student_id=99` | 200 `{"student_id":99,"days":7,"items":[7 个空日],"avg_rate":0.0,"total_minutes":0}` |

自测共 39 步真实 HTTP 请求，**0 个 5xx**（422/400 均为预期失败路径）。

---

## 4. 双学生隔离与越权验证

| 步 | 场景 | 结果 |
|---|---|---|
| 13 | 学生 2 `POST /api/recovery/start {student_id:2, recovery_id:1}`（学生 1 的 id） | 200 `{"student_id":2,"recovery_id":0,"question_id":0,"state":"","state_text":"","teaching":{全空},"item":null}` — 引擎按 (student_id, recovery_id) 查不到 → 空结构 |
| 14 | 学生 2 `answer` 用学生 1 的 recovery_id | 200 空结果，`correct_answer:""`、`analysis:""`，**不泄露学生 1 的答案与解析** |
| 15 | 学生 2 `verify` 用学生 1 的 recovery_id | 200 空结果 + `mastered:false` |
| 16/17 | 学生 2 `question`/`hint` 用学生 1 的 recovery_id | 200 空结构（`question_id:0`、`level:0`） |
| 24 | 学生 2 `POST /api/tasks/complete {student_id:2, task_id:1}`（学生 1 的任务） | 200 空上报结果，且 `summary`/`profile` 都是**学生 2 自己的**当日数据（`total:9,done:0` / `completed_tasks:0`），不含学生 1 的任何字段 |
| 25 | 学生 2 `task_id:0` | 200 空上报结构 |
| 20 | 学生 2 `GET /api/tasks/today` | 200，`task_id` 从 10 起（自己的任务），与学生 1 的 1..9 完全隔离 |
| 28 | 学生 2 `GET /api/habit/profile` | 200，`completed_tasks:0`、`last_active_date:""`，与学生 1 的 1/「2026-10-04」隔离 |
| 35/39 | 学生 2 康复列表复查 | 200 `total:0, items:[]` —— 学生 1 进入 MASTERED 后学生 2 仍看不到任何数据 |

隔离实现方式：全部调用点都把 `student_id` 作为第一个过滤参数传入 `RecoveryEngine`/`HabitEngine`（引擎内部 `WHERE student_id = :sid`），路由层**不做任何跨学生回退查询**；`task_id`/`recovery_id` 由 URL/请求体给出时也只在该学生的范围内解析。

---

## 5. 降级与容错

- **AI 调用与降级**：`/api/recovery/start|question|hint` 的提示与变式题全部经 `recovery` 包 → `ai_recovery.py` → `deepseek.py`（进程环境变量 `DEEPSEEK_API_KEY`，否则读 `backend/.env`）。本次自测环境里 `backend/.env` 配了 key，样例中的 `"source":"ai"` 是真实 AI 返回；变式题组题走本地规则（`"source":"rule"`）。无 key / 调用失败时 `ai_recovery.py` 内部有 `except -> 规则模板` 的降级分支（`source` 会变成 `rule`，字段结构不变），降级路径本身未在本次自测中触发（因 key 可用），但 API 层不感知来源，只会原样透传 `source`。AI 调用不阻塞 `/submit` 与答题主流程。
- **异常兜底**：三个模块各自有一个 `_safe(db, call, fallback)` 包住所有引擎调用，捕获 `Exception` → `db.rollback()` → 返回该接口契约完整、值为空的响应，因此**不会出现 500**。
- **日期校验前置**：非法 `date` 在路由层就被 400 拦下，不进入引擎（引擎内部 `strptime` 会抛 `ValueError`）。
- **幂等**：`/api/tasks/today` 重复访问不重复建任务；`/api/recovery/start {question_id}` 在康复项不存在时调 `sync_from_wrong_book(db, student_id, question, False)` 补建队列行（幂等，且只会为该学生建）。

---

## 6. 与 SPEC 的偏差 / 需要 Lead 注意的事项

1. **`/api/recovery/answer` 与 `/api/recovery/verify` 的 `review_next`**：引擎的 `answer`/`verify` 不返回该字段，SPEC §7.1 要求有。路由层在引擎返回后额外读一次 `detail().next_verify_time` 补上（格式 `YYYY-MM-DD HH:MM`，非 VERIFYING 阶段为空串）。这是**新增字段，不改动引擎**。
2. **`answer` 的 `minutes` 未落库**：`RecoveryEngine.answer()` 签名里没有 `minutes` 参数，路由层按 SPEC 接收该字段但无法透传。任务时长的写入应由 `habit.record_answer`（main.py 的 `/submit` 钩子）负责 —— **这是集成阶段需要 Lead 确认的一处拼接**：若前端在康复作答后不上报 `/api/tasks/complete`，康复练习时长不会计入习惯画像。
3. **`POST /api/recovery/start` 支持 `question_id` 自动入队**：SPEC 只写了「recovery_id 或 question_id 二选一」，未定义 question_id 且队列中无该项时的行为；我实现为**在该学生范围内补建康复行**（复用 `sync_from_wrong_book`，幂等），不存在的 `question_id` 返回空结构。
4. **`summary.mix` 与 `mix_tasks` 并存**：SPEC 只要求 `mix{new_learning,weakness,review}`；引擎实际返回的 `mix` 是**分钟数**并额外附带 `mix_tasks`（任务条数）。两者都是新增字段，未删除 SPEC 要求的键，按 AI_RULES §13.5「已发布接口只允许新增字段」处理；若前端需要「任务条数占比」，直接用 `mix_tasks`。
5. **`/api/habit/stats` 的 `items` 在无数据时仍返回 N 个空日**（`done/total/minutes` 全 0），符合「空结构而不是 404」，前端画曲线时无需特判。
6. **契约卡与门禁**：三个新文件头部都按现有格式写了 `能力契约｜/ 入口：/ 依赖：/ 不负责：/ 验证：/ 被调用：/ 索引：`；
   `C:\Python313\python.exe backend\check_cards.py` → `校验模块数: 88 无卡片: 0 失实符号: 0`（退出码 0；新增的 3 个模块已计入 88）。
   注意其中「验证：」行我写的是 `verify_recovery.py` / `verify_habit.py`（Agent 7 的门禁脚本名）；若 Agent 7 最终用了别的文件名，需要同步这一行，否则会被 check_cards 标记为「失实符号」。
7. **`/api/tasks/*` 的注册**：`task_routes.py` 的 tag 是「每日任务 V2.5」，与 `habit_routes.py`（「每日习惯 V2.5」）是两个独立 router，Lead 记得三个都要 include，否则 `/api/tasks/today` 会 404。

---

## 7. 自测产物处理

临时文件（`backend/_tmp_api_smoke.py`、`backend/_tmp_agent.db`、`backend/_tmp_smoke_out.txt`、`backend/_tmp_smoke_view.txt`）在自测完成后**已删除**；本次未触碰 `backend/learning.db`，未改 `main.py`/`models.py`/`recovery/**`/`habit.py`/`ai_recovery.py`/前端文件，未新增依赖。
