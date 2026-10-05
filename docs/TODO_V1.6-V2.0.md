# V1.6-V2.0开发任务列表

## 已完成

[x] 本地双用户模型
[x] 默认创建两个学生
[x] 学生数据隔离
[x] 年级选择框架
[x] 语数英科目框架
[x] 答题记录模型
[x] 能力评分模型
[x] 自适应难度算法基础
[x] 艾宾浩斯记忆曲线复习计划（V2.1）
[x] 语音朗读题目与解析（V2.1）

## V2.2 已完成（能力诊断系统）

[x] 24 个能力阶段模型（1.1 ~ 6.4）
[x] 阶段化动态诊断算法（每阶段 5 题，按正确率跳级/停留/回退）
[x] 能力画像 ability_profile（能力阶段 + 能力分 + 置信度 + 能力区间）
[x] 知识点掌握度 student_knowledge_mastery
[x] 诊断记录 diagnostic_sessions / diagnostic_records
[x] 诊断 API：start / question / answer / report
[x] 出题 prompt 带上能力上下文（当前能力、目标阶段、掌握度）
[x] 前端：诊断入口页 / 诊断过程页 / 能力报告页
[x] 诊断测试套件 verify_diagnostic.py + verify_diagnostic_web.js
[ ] 能力雷达图（当前用知识点条形图代替）

详见 docs/V2.2能力诊断说明.md

## V2.3 已完成（知识掌握 + 错因分析 + 题目审核）

[x] 知识点体系 knowledge_points（树结构：科目→章节→知识点→子知识点，139 个节点）
[x] 掌握模型 MasteryEngine（掌握度 / 置信度 / 等级 / 复习计划）
[x] 错因分析 answer_error_analysis（数学/语文/英语规则 + AI 深化）
[x] 错题本 wrong_questions（NEW 未掌握 → LEARNING 巩固中 → MASTERED 已攻克）
[x] AI 题目质量审核 QuestionValidator（格式 / 算式自检 / 难度 / 知识点 / 歧义）
[x] 出题 Prompt 升级（带掌握度与错误历史）
[x] 数据库迁移 V2.2 → V2.3（补表补列 + 幂等回填，旧数据零丢失）
[x] 前端：知识掌握地图 / 错题中心 / 学习建议页
[x] 测试套件 verify_knowledge.py + verify_knowledge_web.js
[ ] 错因趋势图（按周看某类错误是否在减少）
[ ] 掌握度历史曲线

详见 docs/V2.3知识掌握与错因分析说明.md

---

# V1.6 待完成

[ ] 完整知识点数据库（当前每科 24 个阶段知识点）
[ ] 一年级-六年级教材结构
[ ] 用户切换页面优化
[ ] 学习记录页面
[ ] 错题本

---

# V1.8 待完成

[x] 初始能力测评流程
[x] CAT动态测试
[x] 阶段判断算法优化
[ ] 能力雷达图
[x] 学科能力报告

---

# V2.0 待完成

[x] 自动推荐下一知识点（V2.3 自适应引擎：QuestionSelector + LearningStrategy）
[x] 根据能力生成Prompt
[x] AI题目难度控制
[x] 错题原因分析
[x] 每日学习计划（V2.3 自适应引擎：DailyLearningPlanner + 今日学习页）

---

# V2.4 间隔复习系统（已完成）

[x] 记忆状态模型 knowledge_memory_state（掌握度 / 记忆强度 / 稳定性 / 个人难度 / 成熟度）
[x] 遗忘风险模型 ForgettingRiskEngine（0~1，高 / 中 / 低分级）
[x] 自适应间隔 calculate_next_interval（阶梯 1/3/7/14/30 → 稳定性驱动，1~180 天）
[x] 今日复习队列 ReviewScheduler（P0~P3、每科 ≤8、每天 ≤15、每个 1~3 题、超出顺延）
[x] 复习题不重复旧题 ReviewQuestionSelector（50/30/20 模式 + 重复检测 + 变式生成）
[x] 每日内容配比 calculate_daily_mix（新学 50% / 补强 30% / 复习 20%，可动态调整）
[x] 复习失败 → 错题康复 / 连续失败 → RELEARN 重新学
[x] 儿童端知识浇水页 + 家长端记忆数据页
[x] V2.3 → V2.4 数据迁移（按掌握度分档初始化，不删旧数据）
[x] 自动化测试 verify_memory.py（145 项）+ verify_memory_web.js（60 项）

---

# 后续V2.5

[ ] XP等级
[ ] 宠物系统
[ ] 成就
[ ] 每日任务

---

# 后续V2.6（知识森林）

[ ] 知识森林可视化（后端已输出 forest / forest_icon 字段）
[ ] 复习日历与记忆衰减曲线（数据已齐：review_records + knowledge_memory_state）
[ ] 能力雷达图（V2.2 遗留）
