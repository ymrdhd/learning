# 菲比同学 · AI 小学学习系统（V2.6）

面向小学 1~6 年级的**本地单机**自适应学习系统：两个小朋友各自独立学习数学 / 语文 / 英语，
系统负责能力诊断 → 知识掌握建模 → 错因分析 → **自适应出题与每日任务** → **间隔复习防遗忘** → **错题康复** → **主动回忆** → **每日学习总结与习惯统计**。

- 纯本地运行：SQLite + 本地题库 + 本地规则，没配 DeepSeek Key 也能完整使用（自动用内置兜底题）
- 零构建前端：原生 HTML/CSS/JS，后端直接挂载 `/app`
- 无账号系统：数据按 `student_id` 隔离（默认「小朋友A」「小朋友B」）
- **V2.5**：菲比三视图互动公仔（可拖拽旋转 / 语音 + 字幕 / **6 种表情随点击·答对·答错自动切换**）、答对自动跳题 + 错题解析、
  **能力水平由每日训练与自由练习成绩自动推断**（不再要求额外做一次诊断）、双击 `start.bat` 自动打开网页
- **V2.5 新增三套系统**：①**错题康复**（错误 → 诊断 → 重学 → 变式训练 → 延迟验证 → 真正掌握，严禁答对一次就 MASTERED）；②**每日学习习惯**（孩子只点「开始今天的学习」，系统按年级限时排五段任务，并给「🎉 今天完成啦！」的明确结束点与每月 2 次休息保护）；③**主动回忆**（英语单词 / 语文字词 / 古诗 / 公式 / 概念，**先自己写出来，不给选项**）
- **V2.6 儿童体验重构**：一级导航只留 🏠 **今天** / 🗺 **成长** / ⚔️ **挑战** / 👤 **我的**，打开软件默认进入「今天」（只回答「我今天要做什么」）；
  「开始今天的学习」启动统一 **LearningSession**（微任务连续做、不用回首页重选，**做完即进「🎉 今天完成啦！」结束页，不无限加题、不加练**）；
  新增 **知识地图**（区域探索 + 🌱🌿🌳⭐ 真实掌握度上色，未掌握的知识不能靠签到 / 时长解锁）、**成长中心**（本周学会 / 记住 / 攻克什么 + 成长时间线）、**我的挑战**（错题中心的儿童化包装，底层仍是 V2.5 错题康复）；
  分龄 UI（1-2 年级 JUNIOR / 3-4 MIDDLE / 5-6 SENIOR）+ Design Tokens + 统一 🔊 读题（浏览器原生语音，失败不影响答题）

## 快速开始

```bat
双击 start.bat
```

后端起来后会自动打开**儿童首页「今天」**（<http://127.0.0.1:8000/app/today.html>；成长中心 `/app/growth.html`；
我的挑战 `/app/challenge.html`；知识地图 `/app/knowledge_map.html`；能力水平 `/app/ability.html`；
知识浇水 `/app/review.html`；错题康复 `/app/recovery.html`；主动回忆 `/app/recall.html`；
今日完成 `/app/daily.html`；学习习惯 `/app/habit.html`；自由练习 `/app/index.html`）。

可选：在 `backend/.env` 写入 `DEEPSEEK_API_KEY=sk-xxx` 启用 AI 出题与 AI 错因深化（改动后需重启后端）。
模板见 `backend/.env.example`：密钥只存在环境变量或 `.env` 里（两者都已被 `.gitignore` 忽略），**任何 `.py` 里都不写明文密钥**。

> 从 V2.3 升级：直接启动即可。系统会按已有掌握度自动初始化记忆状态（老数据不删）。

## 页面

| 页面 | 说明 |
| --- | --- |
| `today.html` | **今日学习**：今日目标（新学 / 补强 / 复习）+ 自适应出题 + 菲比互动公仔；答对自动跳下一题，答错出解析 |
| `ability.html` | **我的能力水平**（V2.5）：由每日训练与自由练习成绩自动推断的能力阶段，无需专门做诊断 |
| `review.html` | **知识浇水**（儿童端）：今天有几个知识需要浇水、树的成长状态、复习题作答 |
| `memory_debug.html` | 记忆数据（家长 / 开发）：掌握度 / 记忆强度 / 稳定性 / 遗忘风险 / 下次复习 / 算法日志 |
| `index.html` | 自由练习：**知识点由自适应引擎按当前能力推荐**（提示「为什么练这个」，可手改且改后不再覆盖），语音读题，菲比陪伴，艾宾浩斯复习面板 |
| `diagnostic.html` / `diagnostic_report.html` | 能力诊断（24 个能力阶段）与能力报告（V2.5 起不再出现在主流程入口，页面保留） |
| `knowledge_map.html` | **知识地图**（V2.6）：🌲 乘法森林 / ⛰ 应用题山谷 等区域的探索进度与知识成长（区域数据全部来自真实掌握度） |
| `challenge.html` | **我的挑战**（V2.6）：错题中心的儿童化包装，🔴 等我攻克 / 🟡 正在训练 / 🟢 已经攻克；底层仍是 V2.5 错题康复 |
| `growth.html` | **成长中心**（V2.6）：本周学习天数 / 新掌握知识 / 记得更牢 / 攻克挑战 / 能力阶段变化 + 成长时间线与连续学习 |
| `wrong_book.html` | 错题中心（未掌握 / 巩固中 / 已攻克） |
| `study_advice.html` | 学习建议（复习 / 练习 / 巩固 / 错因提醒） |
| `recovery.html` | **错题康复**（V2.5）：错题生命周期六态、分级提示（1 思考方向 → 4 完整讲解）、变式训练与延迟验证 |
| `recall.html` | **主动回忆**（V2.5）：出卡不给选项，孩子直接写出答案；完全想起增益高，靠提示想起增益低 |
| `daily.html` | **今日完成**（V2.5）：完成全部任务后进入「🎉 今天完成啦！」结束页，逐项上报完成时长 |
| `habit.html` | **学习习惯简报**（V2.5）：本月学习天数 / 当前连续 / 最长连续 / 完成率 / 徽章 / 每月 2 次休息保护 |

## 核心能力

| 能力 | 版本 | 关键模块 |
| --- | --- | --- |
| 练习闭环：出题 → 判分 → 艾宾浩斯复习 → 语音朗读 | V1.5/V2.1 | `main.py`、`srs.py`、`grading.py` |
| 能力诊断：24 个能力阶段（3.2 = 三年级熟练） | V2.1 | `stages.py`、`diagnostic*.py` |
| 知识掌握模型：掌握度 / 置信度 / 下次复习时间 | V2.3 | `mastery.py`、`knowledge_tree.py` |
| 错因分析 + 错题本 + 题目质量审核 | V2.3 | `error_analysis.py`、`wrong_book.py`、`validator.py` |
| **自适应学习引擎**：学什么 / 出多难 / 下一题 / 升降难度 / 今日计划 | V2.3 | `adaptive/`、`adaptive_routes.py` |
| **间隔复习系统**：记忆状态 / 遗忘风险 / 自适应间隔 / 复习队列 / 复习题变式 | V2.4 | `review/`、`review_routes.py` |
| **菲比互动公仔**：三视图拖拽旋转 / **6 情绪表情**（开心·难过·点赞·加油·可爱·鼓励）/ 答对跳跃 / 语音 + 字幕 / 表情包 / **点击即由 DeepSeek 结合学习数据说一句** | V2.5 | `frontend/phoebe3d.js`、`frontend/phoebe.js`、`backend/phoebe_ai.py` |
| **菲比收藏**：知识等级提升时左侧多一只菲比（只收点赞/加油/可爱/鼓励，**不含答对与答错**；不用当前表情；每生上限 12 只，按学生隔离） | V2.6 | `frontend/phoebe3d.js` |
| **训练成绩自动能力诊断**：从每日训练与自由练习成绩推断三科阶段 | V2.5 | `auto_ability.py`、`ability_routes.py`、`frontend/ability.js` |
| **错题康复系统**：六态生命周期 / 错因驱动策略 / 四级提示 / 变式题 / 延迟验证才能 MASTERED / 接入 MemoryState | V2.5 | `recovery/`（`engine.py` `state.py` `strategy.py` `scheduler.py`）、`recovery_routes.py`、`frontend/recovery.js` |
| **每日学习习惯**：孩子只点开始 / 五段动态配比 / 按年级限时 / 明确结束点 / 连续天数与休息保护 | V2.5 | `habit.py`、`task_routes.py`、`habit_routes.py`、`daily_routes.py`、`frontend/today.js` `daily.js` `habit.js` |
| **主动回忆（基础版）**：内置 24 张卡片，主动输入不给选项，直接写 MemoryState 与掌握度 | V2.5 | `active_recall.py`、`active_recall_routes.py`、`frontend/recall.js` |

自适应引擎的四条规则（详见 [V2.3自适应学习引擎说明](docs/V2.3自适应学习引擎说明.md)）：

1. **知识点优先级**：高价值薄弱（<70）→ 影响后续的基础知识 → 近期错误频繁 → 即将遗忘；**不是简单取最低分**
2. **依赖门控**：应用题掌握 60、乘法掌握 50 时，先补乘法（基础不牢，上层练了也白练）
3. **难度动态调整**：连对 5 题 +5、连错 3 题 −10、最近 10 题 ≥90% 提升阶段 / <50% 降低阶段，难度恒在 1~100
4. **下一题推荐**：40% 薄弱度 + 30% 能力匹配 + 20% 遗忘风险 + 10% 随机探索；题源配比 70/20/10，并回避刚练过的知识点

间隔复习的五条规则（详见 [V2.4间隔复习系统说明](docs/V2.4间隔复习系统说明.md)）：

1. **每个学生 × 每科 × 每个知识点**一份记忆状态（记忆强度 / 稳定性 / 个人难度 / 成熟度）
2. **自适应间隔**：阶梯 1→3→7→14→30 天起步，之后按稳定性动态扩大；GOOD ×1.4、EASY ×1.8、HARD ×1.0、答错 ×0.35（1~180 天）
3. **遗忘风险 0~1**：逾期比例 × 稳定性 × 掌握度 × 个人难度 × 历史成功率，≥0.75 高（自动进今日任务）
4. **今日复习队列**：P0 到期 / P1 高风险 / P2 早期巩固 / P3 重要基础；每科 ≤8、每天 ≤15、每个知识点 1~3 题，超出顺延
5. **复习题不重复旧题**：50% 同知识点换数字 / 30% 变式 / 20% 迁移（长期掌握提高迁移比例），生成后做重复检测

每日基础任务按 **50% 新学 / 30% 薄弱补强 / 20% 间隔复习** 配比自动排课（无复习任务时复习降到 5%，高风险多时升到 40%）。

V2.5 的**五段每日计划**在此基础上按 **40% 新学习 / 25% 薄弱补强 / 20% 复习 / 10% 错题康复 / 5% 主动回忆** 起步，**不是固定比例**：错题积压时提高错题康复，复习大量到期时提高复习，没有到期复习就把时间转给新学习与薄弱补强；总时长按年级限制（1-2 年级 10-15 分钟 / 3-4 年级 15-20 / 5-6 年级 20-30），完成即进结束页，不无限推荐。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 版本与功能清单 |
| GET | `/students` | 学生列表 |
| GET | `/question` | 生成一道题（可用 `difficulty` 指定难度，0 = 自动） |
| POST | `/submit` | 判分：更新能力分、掌握度、复习计划、错题本、错因 |
| GET | `/reviews` | 复习计划总览 |
| GET/POST | `/api/diagnostic/*` | 能力诊断（start / question / answer / report） |
| GET | `/api/mastery/{student_id}` | 知识掌握地图 |
| GET | `/api/report/knowledge` | 知识掌握报告与建议 |
| GET | `/api/errors/{student_id}` | 错因统计与明细 |
| POST | `/api/error/analyze` | 分析一次错误（可选 AI 深化） |
| GET | `/api/wrong_questions/{student_id}` | 错题本 |
| GET | `/api/knowledge/tree` | 知识点树 |
| GET | `/api/learning/recommend/{student_id}` | **今日推荐学习内容（含理由）** |
| GET | `/api/learning/plan/{student_id}` | **今日学习计划** |
| POST | `/api/learning/start` | **开始学习任务** |
| GET | `/api/learning/next-question` | **获取下一题（自适应）** |
| POST | `/api/learning/feedback` | **提交学习反馈（对错 / 难度感受 / 是否需要帮助）** |
| GET | `/api/learning/strategy-log/{student_id}` | **策略日志：系统为什么这样安排** |
| GET | `/api/review/today/{student_id}` | **今日复习任务（知识浇水，含儿童文案）** |
| GET | `/api/review/due/{student_id}` | **所有到期 / 高风险知识点** |
| GET | `/api/review/question` | **获取复习题（不重复历史原题）** |
| POST | `/api/review/answer` | **提交复习答案（更新记忆状态与下次复习时间）** |
| GET | `/api/review/memory-map/{student_id}` | **各知识点记忆状态（家长 / 调试）** |
| GET | `/api/review/stats/{student_id}` | **今日复习 / 完成 / 即将遗忘 / 长期掌握** |
| GET | `/api/review/strategy-log/{student_id}` | **复习算法日志：为什么改复习日期** |
| GET | `/api/ability/auto/{student_id}` | **训练成绩自动能力诊断（V2.5，只读）：三科阶段 / 能力分 / 置信度 / 判断依据** |
| POST | `/api/phoebe/chat` | **菲比 AI 陪伴（V2.5，只读）：读学习数据，由 DeepSeek 生成一句给孩子听的话** |
| GET | `/api/recovery/list/{student_id}` | **错题康复列表（V2.5）**：每条错题的 state / recovery_score / 提示使用等级 / 下次验证时间 |
| GET | `/api/recovery/{recovery_id}` | **错题康复详情（V2.5）**：单条错题的策略、历史与统计 |
| POST | `/api/recovery/start` | **开始康复（V2.5）**：NEW → ANALYZING → LEARNING |
| GET | `/api/recovery/next-question` | **取下一题（V2.5）**：变式题 / 延迟验证题（同一知识目标，不复制原题） |
| POST | `/api/recovery/answer` | **提交康复作答（V2.5）**：更新状态机、恢复评分与 MemoryState；答对一次不会直接 MASTERED |
| POST | `/api/recovery/hint` | 取分级提示（V2.5）：1 思考方向 / 2 关键条件 / 3 解决步骤 / 4 完整讲解；用提示后答对掌握度增长更低 |
| GET | `/api/tasks/today/{student_id}` | **今日任务（V2.5）**：系统自动安排的新学 / 补强 / 复习 / 错题康复 / 主动回忆 |
| GET | `/api/tasks/plan/{student_id}` | **今日学习计划预览（V2.5）**：「今天我们用 N 分钟完成 M 个小任务」+ 每段分钟数与安排理由 |
| POST | `/api/tasks/start` | **开始今天的学习（V2.5）**：孩子只点一下，任务落库（幂等） |
| POST | `/api/tasks/{task_id}/complete` | **完成一个任务（V2.5）**：记录实际时长并刷新习惯画像 |
| GET | `/api/habit/profile/{student_id}` | **学习习惯画像（V2.5）**：连续 / 最长连续 / 本月天数 / 平均时长 / 偏好时段 / 徽章 / 休息保护剩余 |
| POST | `/api/habit/rest` | **休息保护（V2.5）**：每月 2 次，不打断连续学习、不归零历史成长（不可购买） |
| GET | `/api/habit/goal/{student_id}` | **当前学习目标（V2.5，基础版）**：来源 SYSTEM（PARENT / STUDENT 预留） |
| POST | `/api/active-recall/start` | **主动回忆出卡（V2.5）**：只给题面与提示，**不给选项** |
| POST | `/api/active-recall/answer` | **提交回忆（V2.5）**：完全想起增益高、靠提示想起增益低；结果写入掌握度与记忆状态 |
| GET | `/api/active-recall/summary` | **今日回忆小结（V2.5）**：对 / 部分 / 错、正确率、记忆增益 |
| GET | `/api/daily-summary/{student_id}` | **今日总结（V2.5）**：任务完成情况 + 儿童版反馈 + 「今天可以休息啦！」结束点 |
| GET | `/api/home/{student_id}` | **儿童首页聚合（V2.6）**：一次返回学生 / 今日计划 / 今日进度 / 待复习数 / 待挑战数 / 成长亮点 / 菲比问候 + 主按钮文案 |
| GET | `/api/knowledge-map/{student_id}` | **知识地图（V2.6）**：区域 + 知识节点（ui_status 用 🌱🌿🌳⭐）+ 解锁与推荐，全部来自真实掌握度 |
| GET | `/api/growth/{student_id}` | **成长中心（V2.6）**：本周学习天数 / 新掌握 / 记得更牢 / 攻克挑战 / 复习成功 / 能力阶段变化 + 成长时间线 |
| GET | `/api/challenge/{student_id}` | **我的挑战（V2.6）**：按 🔴🟡🟢 分组的错题康复项（**不下发答案与解析**） |
| POST | `/api/review/skip` / `/api/review/feedback` | 跳过今天的复习任务 / 孩子主观难度感受（微调间隔） |

## 测试

```powershell
python backend\verify_all.py                    # 全量（23 个套件，串行，各用独立端口与临时库）
python backend\verify_all.py memory memweb      # 只跑间隔复习系统
python backend\verify_memory.py                 # 间隔复习后端（145 项断言，端口 8906）
python backend\verify_adaptive.py               # 自适应引擎后端（110 项断言，端口 8905）
python backend\verify_knowledge.py              # 知识/错因/错题（112 项断言，端口 8904）
python backend\verify_ability.py                # 训练成绩自动能力诊断（端口 8907）
python backend\verify_phoebe_ai.py              # 菲比 AI 台词 / 降级路径（端口 8908，强制离线不联网）
python backend\verify_recovery.py                # V2.5 错题康复（端口 8910）
python backend\verify_habit.py                   # V2.5 每日任务与学习习惯（端口 8911）
python backend\verify_active_recall.py           # V2.5 主动回忆与每日总结（端口 8912）
python backend\verify_v26.py                     # V2.6 儿童体验（首页聚合/知识地图/成长/挑战/隔离，63 项断言，端口 8913）
node frontend\verify_v26_web.js                  # V2.6 儿童端前端（今天/挑战/知识地图/学习会话，65 项断言）
node frontend\verify_memory_web.js              # 知识浇水 + 记忆数据页（60 项断言）
node frontend\verify_adaptive_web.js            # 今日学习页前端（41 项断言）
node frontend\verify_phoebe3d_web.js            # 菲比三视图立牌 + 点击触发 AI（83 项断言）
node frontend\verify_ability_web.js             # 我的能力水平页（29 项断言）
```

> 系统 PATH 里没有 node 时，用 DSH 自带：`C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`。
> 所有验证脚本自带临时数据库与临时后端，不会污染 `backend/learning.db`；端口被占用会直接失败（刻意设计）。

## 文档

| 文档 | 内容 |
| --- | --- |
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | AI 长期上下文：技术栈、目录、核心模块、决策、坑位、验证命令（**改代码前先读**） |
| [AI_RULES.md](AI_RULES.md) | 项目专属开发规则（最小修改、测试策略等） |
| [V2.5功能说明](docs/V2.5功能说明.md) | 菲比三视图互动公仔 / 语音字幕 / 自动跳题与错题解析 / 训练成绩自动能力诊断 / 启动即开网页 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更日志（V1.5 → V2.6，含 V2.6 新增文件与迁移说明） |
| [docs/TODO.md](docs/TODO.md) | 待办与未完成项（未完成不会写成已完成） |
| [V25_RELEASE_REPORT.md](V25_RELEASE_REPORT.md) | V2.5 开发报告：完成情况 / 新增与修改文件 / 迁移 / 算法 / API / 测试结果 / 已知问题 |
| [V26_RELEASE_REPORT.md](V26_RELEASE_REPORT.md) | V2.6 开发报告：17 项——儿童首页 / LearningSession / 知识地图 / 成长中心 / 挑战中心 / 分龄 UI / 健康机制 / 测试与回归结果 |
| [V2.4间隔复习系统说明](docs/V2.4间隔复习系统说明.md) | 记忆状态 / 遗忘风险 / 间隔算法 / 复习队列 / 复习题变式 / 迁移 |
| [V2.3自适应学习引擎说明](docs/V2.3自适应学习引擎说明.md) | 学习策略 / 难度控制 / 选题 / 每日计划 / 数据库 / API |
| [V2.3知识掌握与错因分析说明](docs/V2.3知识掌握与错因分析说明.md) | MasteryEngine、知识点树、错因分析、错题本、题目审核 |
| [V2.2能力诊断说明](docs/V2.2能力诊断说明.md) | 24 个能力阶段与诊断流程 |
| [V2.1功能说明](docs/V2.1功能说明.md) / [V1.5功能说明](docs/V1.5功能说明.md) | 复习闭环、语音朗读、基础练习 |

## 目录结构

```text
ai_learning_system/
├── start.bat              一键启动（起后端 + 自动打开浏览器）
├── backend/               FastAPI + SQLAlchemy + SQLite（learning.db）
│   ├── adaptive/          自适应学习引擎（strategy / difficulty / selector / planner / engine）
│   ├── review/            间隔复习系统（memory / forgetting / interval / scheduler / selector / mix / engine）
│   ├── recovery/          错题康复系统（state / strategy / scheduler / engine）
│   ├── habit.py           每日学习习惯与五段每日计划（V2.5）
│   ├── active_recall.py   主动回忆基础版：24 张卡片 + 记忆增益（V2.5）
│   ├── daily_routes.py    每日总结 GET /api/daily-summary/{student_id}（V2.5）
│   ├── auto_ability.py    训练成绩自动能力诊断（V2.5）
│   ├── main.py            入口 + 自由练习 API + 静态挂载
│   └── verify_*.py        端到端验证脚本
├── frontend/              静态页面（today / recovery / recall / daily / habit / ability / review / memory_debug / index / diagnostic* / knowledge_map / wrong_book / study_advice）
│   ├── phoebe.js          答对庆祝浮层（表情包 + 音效）
│   ├── phoebe3d.js        菲比三视图互动立牌（旋转 / 动作 / 语音字幕 / 6 情绪表情）
│   └── assets/phoebe3d/   表情素材（18 张 {情绪}_{视角}.png + manifest + 源图）
├── data/                  课程 JSON（当前未被代码引用）
└── docs/                  版本功能说明
```
