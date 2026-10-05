# -*- coding: utf-8 -*-
# ==============================================================
# 能力契约｜英语分阶段诊断题库数据（每阶段 6 题，硬编码）
# 入口：题库数据结构（由 diagnostic_bank 取用）
# 依赖：无
# 不负责：数学题库 → diagnostic_bank.py；语文题库 → bank_chinese.py
# 验证：python backend/verify_diagnostic.py
# 被调用：diagnostic_bank.py
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

# AI 小学学习系统 V2.0 能力诊断系统 —— 英语题库数据文件
#
# 用途：
#   为「能力诊断」模块提供小学 1-6 年级英语选择题题库。题库按旧 24 个大知识点组织（细分阶段由 diagnostic_bank 用 legacy_key 兜底），
#   键为阶段编号字符串（年级 1-6，每年级 4 个等级：1 基础、2 熟练、3 进阶、4 挑战）：
#
#     1.1 26 个字母              1.2 问候语与自我介绍      1.3 数字 1-10            1.4 颜色
#     2.1 常见动物单词           2.2 家庭成员              2.3 学习用品与教室       2.4 简单祈使句
#     3.1 食物与饮料             3.2 一般现在时(三单)      3.3 时间表达与日常作息   3.4 方位介词
#     4.1 现在进行时             4.2 天气与季节            4.3 一般过去时(规则动词) 4.4 情态动词 can/must
#     5.1 一般将来时             5.2 形容词比较级          5.3 频度副词与一般现在时 5.4 名词单复数与不可数名词
#     6.1 现在完成时初步         6.2 一般过去时(不规则)    6.3 宾语从句与间接引语   6.4 阅读理解与完形填空
#
# 数据结构：
#   QUESTION_BANK: dict[str, list[tuple[str, str, list[str], str]]]
#   每个阶段的值为题目列表，每阶段 6 题；每题是一个 4 元组：
#       (题干, 正确答案文本, 错误选项列表(恰好 3 个), 中文解析)
#
# 约定（调用方须知）：
#   1. 这里只提供选择题的原始素材，不含选项字母；调用方负责把 1 个正确项与 3 个错误项
#      打乱顺序后分配 A/B/C/D。
#   2. 错误选项都是小学生常见错误（拼写混淆、时态误用、词义混淆等），互不相同、
#      不等于正确答案，且不使用「以上都对」「都不对」这类选项。
#   3. 题干中不出现选项字母，也不包含正确答案文本。
#   4. 本文件只使用 Python 标准库，不导入项目内其他模块，也没有任何副作用代码。

QUESTION_BANK = {

    # ==========================================================
    # 1.1 26 个英文字母
    # ==========================================================
    "1.1": [
        ("大写字母 A 的小写形式是哪一个？", "a", ["e", "o", "d"],
         "大写 A 对应的小写字母是 a，写的时候占中间一格。"),
        ("大写字母 B 的小写形式是哪一个？", "b", ["d", "p", "q"],
         "大写 B 对应的小写字母是 b，注意不要和 d、p、q 看混。"),
        ("英语字母表里，紧跟在字母 G 后面的字母是哪一个？", "H", ["F", "J", "I"],
         "字母表顺序是 ...F、G、H、I...，所以 G 的后面是 H。"),
        ("英语字母表里，排在字母 E 前面的字母是哪一个？", "D", ["C", "F", "G"],
         "字母表顺序是 ...C、D、E...，所以 E 的前面是 D。"),
        ("英语字母表一共有多少个字母？", "26", ["24", "25", "28"],
         "英语一共有 26 个字母，从 A 一直排到 Z。"),
        ("英语字母表里排在最后的一个字母是哪一个？", "Z", ["Y", "X", "W"],
         "字母表从 A 开始，到 Z 结束，最后一个字母是 Z。"),
    ],

    # ==========================================================
    # 1.2 问候语与自我介绍
    # ==========================================================
    "1.2": [
        ("早上八点在学校见到老师，用英语问好最合适的是哪一句？", "Good morning!",
         ["Good night!", "Good evening!", "Good afternoon!"],
         "morning 是早上，所以早上问好用 Good morning!。Good night! 是晚上睡前道别说的。"),
        ("下午三点见到同学，用英语问好应该说哪一句？", "Good afternoon!",
         ["Good morning!", "Good night!", "Good evening!"],
         "afternoon 是下午，所以下午问好用 Good afternoon!。"),
        ("晚上睡觉前和家人道别，应该说哪一句？", "Good night!",
         ["Good morning!", "Good afternoon!", "Good evening!"],
         "Good night! 是晚上睡觉前或道别时说的；Good evening! 是晚上刚见面时问好用的。"),
        ("别人问你 How are you? 时，下面哪个回答最合适？", "I'm fine, thank you.",
         ["I'm nine, thank you.", "Yes, I am.", "You are welcome."],
         "How are you? 是问「你好吗」，回答 I'm fine, thank you.（我很好，谢谢）。I'm nine 是在说自己九岁。"),
        ("你想知道新同学的名字，问完 What's your name? 之后，他应该怎么回答？", "My name is Tom.",
         ["I'm fine.", "He is my brother.", "Nice to meet you, too."],
         "What's your name? 问的是名字，回答要用 My name is ... 或者 I'm ...。"),
        ("第一次见面时说 Nice to meet you. 对方通常回答哪一句？", "Nice to meet you, too.",
         ["I'm sorry.", "Thank you very much.", "Goodbye."],
         "Nice to meet you. 是「很高兴认识你」，回答时加上 too，表示「我也很高兴认识你」。"),
    ],

    # ==========================================================
    # 1.3 数字 1-10
    # ==========================================================
    "1.3": [
        ("数字 3 用英语怎么写？", "three", ["tree", "thirteen", "free"],
         "3 是 three；tree 是「树」，thirteen 是 13，读音相近但意思不同。"),
        ("数字 8 用英语怎么写？", "eight", ["eigth", "ate", "eightteen"],
         "8 是 eight，正确拼写是 e-i-g-h-t；eigth 把字母顺序写错了，ate 是 eat 的过去式。"),
        ("英语单词 five 表示的数字是几？", "5", ["4", "9", "15"],
         "five 是 5；four 是 4，nine 是 9，fifteen 是 15。"),
        ("按照 1 到 10 的顺序，数字 7 前面的那个数字是几？", "6", ["8", "9", "5"],
         "顺序是 ...5、6、7、8...，所以 7 前面的数字是 6。"),
        ("数字 10 用英语怎么写？", "ten", ["teen", "tan", "tenth"],
         "10 是 ten；tenth 是「第十」，teen 只出现在 thirteen、fourteen 这样的词里，单独用不对。"),
        ("表示数量「两个」的英语单词是哪一个？", "two", ["to", "too", "twelve"],
         "「两个」是 two；to 和 too 与 two 读音相同，但 to 表示「到」，too 表示「也、太」。"),
    ],

    # ==========================================================
    # 1.4 颜色
    # ==========================================================
    "1.4": [
        ("「红色」用英语怎么说？", "red", ["read", "ride", "rad"],
         "红色是 red；read 是「读」，ride 是「骑」，拼写相近但意思完全不同。"),
        ("「蓝色」用英语怎么说？", "blue", ["bule", "blew", "blur"],
         "蓝色是 blue，正确拼写是 b-l-u-e；bule 把字母顺序写错了。"),
        ("英语单词 green 表示的是什么颜色？", "绿色", ["灰色", "蓝色", "棕色"],
         "green 是绿色，草和树叶的颜色就是 green。"),
        ("「黄色」用英语怎么说？", "yellow", ["yelow", "yello", "red"],
         "黄色是 yellow，中间有两个 l；red 是红色，不是黄色。"),
        ("The grass is ___ . 草地在正常情况下是什么颜色？空白处应填哪个单词？", "green",
         ["red", "blue", "black"],
         "草是绿色的，所以填 green；red 是红色，blue 是蓝色，black 是黑色。"),
        ("「黑色」用英语怎么说？", "black", ["back", "block", "blank"],
         "黑色是 black；back 是「后面」，block 是「街区、积木」，拼写相近但意思不同。"),
    ],

    # ==========================================================
    # 2.1 常见动物单词
    # ==========================================================
    "2.1": [
        ("「猫」用英语怎么说？", "cat", ["cap", "car", "cut"],
         "猫是 cat；cap 是「帽子」，car 是「小汽车」，cut 是「切」，只差一个字母。"),
        ("「狗」用英语怎么说？", "dog", ["dot", "bog", "dig"],
         "狗是 dog；dot 是「点」，dig 是「挖」，注意中间的字母是 o。"),
        ("英语单词 elephant 指的是哪种动物？", "大象", ["老虎", "猴子", "熊猫"],
         "elephant 是大象；tiger 是老虎，monkey 是猴子，panda 是熊猫。"),
        ("「熊猫」用英语怎么说？", "panda", ["penda", "pony", "panther"],
         "熊猫是 panda；pony 是「小马」，panther 是「豹」，拼写有点像但意思不同。"),
        ("「兔子」用英语怎么说？", "rabbit", ["rabit", "robot", "ribbon"],
         "兔子是 rabbit，中间有两个 b；robot 是「机器人」，ribbon 是「丝带」。"),
        ("「鸟」用英语怎么说？", "bird", ["brid", "bread", "beard"],
         "鸟是 bird，字母顺序是 b-i-r-d，不要写成 brid；bread 是「面包」。"),
    ],

    # ==========================================================
    # 2.2 家庭成员
    # ==========================================================
    "2.2": [
        ("「妈妈」用英语怎么说？", "mother", ["father", "brother", "mather"],
         "妈妈是 mother；father 是爸爸，brother 是兄弟，注意拼写是 m-o-t-h-e-r。"),
        ("「爸爸」用英语怎么说？", "father", ["farther", "brother", "mother"],
         "爸爸是 father；farther 是 far 的比较级，表示「更远」，拼写很像但不是家人称呼。"),
        ("英语单词 sister 指的是家里的谁？", "姐妹", ["兄弟", "爷爷", "叔叔"],
         "sister 是姐妹；brother 是兄弟，grandfather 是爷爷，uncle 是叔叔。"),
        ("「爷爷」用英语怎么说？", "grandfather", ["grandmother", "grandson", "granddaughter"],
         "爷爷是 grandfather；grandmother 是奶奶，grandson 是孙子，granddaughter 是孙女。"),
        ("「哥哥或弟弟（一个人）」用英语怎么说？", "brother", ["bother", "sister", "borther"],
         "兄弟是 brother，拼写是 b-r-o-t-h-e-r；bother 是「打扰」，意思完全不同。"),
        ("This is my father's father. 这句话里的人是我的谁？", "爷爷", ["爸爸", "叔叔", "哥哥"],
         "father's father 是「爸爸的爸爸」，那是爷爷。"),
    ],

    # ==========================================================
    # 2.3 学习用品与教室
    # ==========================================================
    "2.3": [
        ("「书」用英语怎么说？", "book", ["look", "cook", "buk"],
         "书是 book，中间是两个 o；look 是「看」，cook 是「做饭」。"),
        ("「铅笔」用英语怎么说？", "pencil", ["pen", "pencel", "pencile"],
         "铅笔是 pencil，拼写是 p-e-n-c-i-l；pen 是「钢笔」，不是铅笔。"),
        ("「尺子」用英语怎么说？", "ruler", ["rule", "rubber", "ruller"],
         "尺子是 ruler；rule 是「规则」，rubber 是「橡皮」，ruler 里只有一个 l。"),
        ("英语单词 eraser 指的是什么？", "橡皮", ["铅笔", "尺子", "书包"],
         "eraser 是橡皮；pencil 是铅笔，ruler 是尺子，schoolbag 是书包。"),
        ("「书包」用英语怎么说？", "schoolbag", ["school", "bag", "schoolbug"],
         "书包是 schoolbag，由 school 和 bag 合成；只说 school 是「学校」，只说 bag 是「包」。"),
        ("老师上课写字用的「黑板」用英语怎么说？", "blackboard", ["blackbird", "blackbord", "board"],
         "黑板是 blackboard，由 black 和 board 组成；blackbird 是「乌鸦」，拼写像但不是黑板。"),
    ],

    # ==========================================================
    # 2.4 简单祈使句
    # ==========================================================
    "2.4": [
        ("老师说「起立」，同学们应该说：___ up! 空白处应填哪个单词？", "Stand",
         ["Sit", "Standing", "Stands"],
         "祈使句用动词原形开头，所以是 Stand up!；加 -ing 或 -s 都不是祈使句，Sit up 意思也不对。"),
        ("想让同学把门关上，应该说哪一句？", "Close the door.",
         ["Open the door.", "Close the window.", "Closes the door."],
         "祈使句用动词原形开头：Close the door.（关上门）。Open the door 是「打开门」，Closes 加了 s 不对。"),
        ("提醒同学「不要迟到」，应该说哪一句？", "Don't be late.",
         ["Don't late.", "Not be late.", "Doesn't be late."],
         "祈使句的否定形式是 Don't + 动词原形，be late 是「迟到」，所以是 Don't be late.。"),
        ("请别人打开书，用英语应该说哪一句？", "Open your book, please.",
         ["Opens your book, please.", "Opening your book, please.", "Open you book, please."],
         "祈使句用动词原形 Open 开头，your 是「你的」，所以是 Open your book, please.。"),
        ("下面哪一句是表示请求或命令的祈使句？", "Come in, please.",
         ["I come in.", "He comes in.", "She is coming."],
         "祈使句没有主语、用动词原形开头，Come in, please. 就是祈使句；其他三句都有主语。"),
        ("让同学们「安静一点」，应该说哪一句？", "Be quiet, please.",
         ["Are quiet, please.", "You are quiet, please.", "Be quietly, please."],
         "祈使句用动词原形 Be 开头，quiet 是形容词，所以是 Be quiet, please.。"),
    ],

    # ==========================================================
    # 3.1 食物与饮料
    # ==========================================================
    "3.1": [
        ("「苹果」用英语怎么说？", "apple", ["aple", "appel", "banana"],
         "苹果是 apple，中间有两个 p；aple 少写了一个 p，banana 是香蕉。"),
        ("「面包」用英语怎么说？", "bread", ["bred", "beard", "bird"],
         "面包是 bread，字母顺序是 b-r-e-a-d；beard 是「胡子」，bird 是「鸟」。"),
        ("英语单词 milk 指的是什么？", "牛奶", ["果汁", "水", "茶"],
         "milk 是牛奶；juice 是果汁，water 是水，tea 是茶。"),
        ("「米饭」用英语怎么说？", "rice", ["rise", "race", "rices"],
         "米饭是 rice，字母顺序是 r-i-c-e；rise 是「上升」，race 是「比赛」。"),
        ("别人问 What would you like to drink? 下面哪个回答最合适？", "I'd like some water, please.",
         ["I'd like some bread, please.", "Yes, I do.", "Here you are."],
         "drink 问的是喝的东西，water 是饮料；bread 是面包，属于吃的，不能用来回答 drink 的问题。"),
        ("I'm hungry. I want some ___ . 空白处应填哪个单词？", "noodles",
         ["water", "milk", "juice"],
         "hungry 是「饿」，想吃的应该是食物，noodles 是面条；water、milk、juice 都是喝的。"),
    ],

    # ==========================================================
    # 3.2 一般现在时（第三人称单数）
    # ==========================================================
    "3.2": [
        ("He ___ to school every day. 空白处应填哪个单词？", "goes", ["go", "going", "went"],
         "every day 表示经常发生，用一般现在时；主语 He 是第三人称单数，动词要加 es。"),
        ("My mother ___ TV in the evening. 空白处应填哪个单词？", "watches",
         ["watch", "watching", "watched"],
         "主语 My mother 是第三人称单数，动词 watch 以 ch 结尾，要加 es 变成 watches。"),
        ("The boy ___ football on Sundays. 空白处应填哪个单词？", "plays",
         ["play", "playing", "plaies"],
         "主语 The boy 是第三人称单数，动词 play 直接加 s 变成 plays，不能写成 plaies。"),
        ("Lily ___ her homework after school. 空白处应填哪个单词？", "does",
         ["do", "doing", "dos"],
         "主语 Lily 是第三人称单数，动词 do 要变成 does。"),
        ("Tom ___ like apples. 空白处应填哪个单词？", "doesn't",
         ["don't", "isn't", "aren't"],
         "主语 Tom 是第三人称单数，否定要用 doesn't + 动词原形。"),
        ("___ your father go to work by bus? 空白处应填哪个单词？", "Does",
         ["Do", "Is", "Are"],
         "主语 your father 是第三人称单数，一般现在时的一般疑问句要用 Does 开头，后面动词用原形。"),
    ],

    # ==========================================================
    # 3.3 时间表达与日常作息
    # ==========================================================
    "3.3": [
        ("钟表上正好是 8 点整，用英语回答 What time is it? 应该说哪一句？", "It's eight o'clock.",
         ["It's eight clock.", "It's eight hour.", "It's at eight."],
         "整点的说法是「数字 + o'clock」，8 点是 eight o'clock，前面还要加 It's。"),
        ("钟表上是 7 点 30 分，用英语怎么读？", "It's seven thirty.",
         ["It's seven thirteen.", "It's thirty seven.", "It's seven and thirty."],
         "英语读时间是「先小时后分钟」，7:30 是 seven thirty；thirty seven 是 37，顺序反了。"),
        ("「我早上六点起床」用英语怎么说？", "I get up at six in the morning.",
         ["I get up at six in the evening.", "I get up on six in the morning.", "I get up at six on the morning."],
         "具体时刻前面用 at，早上用 in the morning，所以是 at six in the morning。"),
        ("I go to school ___ 7:30. 空白处应填哪个介词？", "at", ["in", "on", "for"],
         "具体几点几分前面用介词 at，所以是 at 7:30。"),
        ("别人问你 When do you have lunch? 下面哪个回答最合适？", "At twelve o'clock.",
         ["In twelve o'clock.", "On twelve o'clock.", "It's twelve o'clock."],
         "When 问的是「什么时候」，回答用 At + 时间；It's twelve o'clock. 回答的是 What time is it?。"),
        ("I do my homework ___ the afternoon. 空白处应填哪个介词？", "in", ["at", "on", "for"],
         "in the morning、in the afternoon、in the evening 是固定说法，中间用介词 in。"),
    ],

    # ==========================================================
    # 3.4 方位介词
    # ==========================================================
    "3.4": [
        ("The cat is ___ the box. 猫在盒子里面，空白处应填哪个单词？", "in",
         ["on", "under", "behind"],
         "in 表示「在……里面」；on 是在上面，under 是在下面，behind 是在后面。"),
        ("The book is ___ the desk. 书在桌子上面，空白处应填哪个单词？", "on",
         ["in", "under", "behind"],
         "on 表示「在……上面（和表面接触）」；in 表示「在……里面」，意思不同。"),
        ("The ball is ___ the chair. 球在椅子下面，空白处应填哪个单词？", "under",
         ["on", "in", "beside"],
         "under 表示「在……下面」；beside 是「在……旁边」，位置不一样。"),
        ("The tree is ___ the house. 树在房子后面，空白处应填哪个单词？", "behind",
         ["in front of", "between", "in"],
         "behind 表示「在……后面」；in front of 意思正好相反，是「在……前面」。"),
        ("The shop is ___ the school and the park. 商店在学校和公园之间，空白处应填哪个单词？", "between",
         ["behind", "under", "in"],
         "between ... and ... 表示「在……和……之间」，所以用 between。"),
        ("There is a picture ___ the wall. 画挂在墙上，空白处应填哪个单词？", "on",
         ["in", "at", "under"],
         "挂在墙面上的东西用 on the wall；in the wall 是「嵌在墙体里面」，意思不同。"),
    ],

    # ==========================================================
    # 4.1 现在进行时
    # ==========================================================
    "4.1": [
        ("Look! The boys ___ football now. 空白处应填哪个单词？", "are playing",
         ["play", "plays", "played"],
         "now 表示此刻正在踢球，用现在进行时 be + 动词的 -ing 形式；主语 The boys 是复数，所以用 are playing。"),
        ("My mother ___ dinner in the kitchen now. 空白处应填哪个单词？", "is cooking",
         ["cook", "cooks", "cooked"],
         "now 表示正在做，用现在进行时；主语 My mother 是第三人称单数，所以用 is cooking。"),
        ("What ___ you doing? 空白处应填哪个单词？", "are", ["is", "do", "does"],
         "现在进行时的结构是 be + 动词的 -ing 形式，主语 you 要用 are，所以是 What are you doing?。"),
        ("Listen! Someone ___ in the next room. 空白处应填哪个单词？", "is singing",
         ["sings", "sang", "sing"],
         "Listen! 提示动作正在发生，用现在进行时；someone 看作单数，所以用 is singing。"),
        ("I ___ my homework now. Don't trouble me. 空白处应填哪个单词？", "am doing",
         ["do", "does", "did"],
         "now 表示此刻正在做作业，用现在进行时；主语 I 用 am，所以是 am doing。"),
        ("现在进行时的结构是下面哪一个？", "be + 动词的 -ing 形式",
         ["do + 动词原形", "have + 过去分词", "will + 动词原形"],
         "现在进行时表示正在做，结构是 be（am / is / are）+ 动词的 -ing 形式。"),
    ],

    # ==========================================================
    # 4.2 天气与季节
    # ==========================================================
    "4.2": [
        ("It's ___ today. 今天下雨，空白处应填哪个单词？", "rainy",
         ["rain", "rains", "rained"],
         "be 动词后面要用形容词，rainy 是「下雨的」；rain 是名词或动词，不能直接放在 is 后面。"),
        ("There are four ___ in a year. 空白处应填哪个单词？", "seasons",
         ["season", "days", "months"],
         "four 后面要接复数名词，four seasons 是「四个季节」；一年有四季，不是四个月。"),
        ("「冬天」用英语怎么说？", "winter", ["winner", "winder", "summer"],
         "冬天是 winter；winner 是「获胜者」，summer 是夏天，拼写和意思都不一样。"),
        ("It's very hot. It's ___ now. 空白处应填哪个单词？", "summer",
         ["winter", "autumn", "spring"],
         "hot 表示很热，对应夏天 summer；winter 是寒冷的冬天。"),
        ("Spring comes after ___ . 春天在哪个季节之后到来？空白处应填哪个单词？", "winter",
         ["summer", "autumn", "spring"],
         "季节顺序是 spring、summer、autumn、winter，冬天 winter 之后又是春天。"),
        ("In winter, it often ___ in the north of China. 空白处应填哪个单词？", "snows",
         ["snow", "snowing", "snowed"],
         "often 表示经常发生，用一般现在时；主语 it 是第三人称单数，动词 snow 要加 s。"),
    ],

    # ==========================================================
    # 4.3 一般过去时（规则动词）
    # ==========================================================
    "4.3": [
        ("I ___ my homework yesterday. 空白处应填哪个单词？", "finished",
         ["finish", "finishes", "finishing"],
         "yesterday 表示过去，用一般过去时；规则动词 finish 的过去式是 finished。"),
        ("They ___ TV last night. 空白处应填哪个单词？", "watched",
         ["watch", "watches", "watching"],
         "last night 是过去时间，用一般过去时；规则动词 watch 的过去式是 watched。"),
        ("She ___ to the park last Sunday. 空白处应填哪个单词？", "walked",
         ["walk", "walks", "walking"],
         "last Sunday 是过去时间，用一般过去时；规则动词 walk 的过去式是 walked。"),
        ("We ___ football two days ago. 空白处应填哪个单词？", "played",
         ["play", "plays", "playing"],
         "two days ago 是过去时间，用一般过去时；规则动词 play 的过去式是 played。"),
        ("英语里规则动词的过去式一般是怎么构成的？", "在动词后面加 -ed",
         ["在动词后面加 -ing", "在动词前面加 did", "在动词后面加 -s"],
         "规则动词的过去式一般在词尾加 -ed，例如 play → played；加 -ing 是现在进行时，加 -s 是一般现在时第三人称单数。"),
        ("___ you visit your grandma last week? 空白处应填哪个单词？", "Did",
         ["Do", "Does", "Are"],
         "last week 是过去时间，一般过去时的一般疑问句要用 Did 开头，后面的动词用原形。"),
    ],

    # ==========================================================
    # 4.4 情态动词 can / must
    # ==========================================================
    "4.4": [
        ("I ___ swim very well. 空白处应填哪个单词？", "can",
         ["cans", "can to", "am can"],
         "情态动词 can 没有人称变化，后面直接跟动词原形，也不能和 am 一起用。"),
        ("You ___ be careful when you cross the road. 空白处应填哪个单词？", "must",
         ["musts", "must to", "are must"],
         "must 表示「必须」，是情态动词，没有人称变化，后面接动词原形 be。"),
        ("Can you swim? — No, I ___ . 空白处应填哪个单词？", "can't",
         ["don't", "am not", "won't"],
         "用 Can 提问就要用 can 来回答，否定回答是 No, I can't.。"),
        ("Students ___ listen to the teacher in class.（学生在课堂上应当认真听老师讲课）", "must",
         ["mustn't", "can't", "needn't"],
         "must 表示「必须」；mustn't 表示「禁止」，can't 和 needn't 也都不能表达「必须」。"),
        ("We ___ run in the classroom. It's dangerous. 空白处应填哪个单词？", "mustn't",
         ["must", "can", "may"],
         "mustn't 表示「禁止、不许」；在教室里跑很危险，所以是不许跑。"),
        ("I can ___ the guitar. 空白处应填哪个单词？", "play",
         ["plays", "playing", "played"],
         "情态动词 can 后面要用动词原形，所以是 can play。"),
    ],

    # ==========================================================
    # 5.1 一般将来时
    # ==========================================================
    "5.1": [
        ("I ___ visit my grandpa tomorrow. 空白处应填哪个单词？", "will",
         ["am", "do", "did"],
         "tomorrow 是将来时间，一般将来时用 will + 动词原形。"),
        ("She ___ going to be a doctor. 空白处应填哪个单词？", "is",
         ["are", "am", "be"],
         "be going to 结构中，主语 She 是第三人称单数，be 动词要用 is。"),
        ("They ___ have a party next Sunday. 空白处应填哪个单词？", "will",
         ["are", "were", "did"],
         "next Sunday 是将来时间，用 will + 动词原形；were 和 did 都表示过去。"),
        ("Look at the black clouds. It ___ rain soon. 空白处应填哪个单词？", "is going to",
         ["was going to", "is going", "goes to"],
         "有乌云说明马上要下雨，用 be going to 表示根据迹象作出的推测；主语 It 用 is going to。"),
        ("What ___ you do this weekend? 空白处应填哪个单词？", "will",
         ["are", "did", "does"],
         "this weekend 指将来的时间，问将来的打算用 will + 动词原形；does 是第三人称单数，不能和 you 连用。"),
        ("We ___ going to visit the museum next week. 空白处应填哪个单词？", "are",
         ["is", "am", "will"],
         "be going to 结构中，主语 We 是复数，be 动词要用 are。"),
    ],

    # ==========================================================
    # 5.2 形容词比较级
    # ==========================================================
    "5.2": [
        ("Tom is ___ than Mike. 空白处应填哪个单词？", "taller",
         ["tall", "tallest", "more tall"],
         "than 前面要用比较级，tall 的比较级是 taller；tallest 是最高级，more tall 的形式错误。"),
        ("This book is ___ than that one. 空白处应填哪个单词？", "more interesting",
         ["interesting", "most interesting", "interestinger"],
         "多音节形容词的比较级在前面加 more，所以是 more interesting；most interesting 是最高级。"),
        ("My sister is ___ than me. 空白处应填哪个单词？", "younger",
         ["young", "youngest", "more young"],
         "than 前面要用比较级，young 的比较级是 younger；youngest 是最高级。"),
        ("Which is ___ , the sun or the earth? 空白处应填哪个单词？", "bigger",
         ["big", "biggest", "more big"],
         "两者比较用比较级；big 是重读闭音节，要双写 g 再加 er，变成 bigger。"),
        ("The weather today is ___ than yesterday. 空白处应填哪个单词？", "better",
         ["good", "gooder", "best"],
         "good 的比较级是不规则形式 better，不能说 gooder；best 是最高级。"),
        ("Lily is the ___ girl in our class. 空白处应填哪个单词？", "tallest",
         ["taller", "tall", "more tall"],
         "in our class 表示在全班所有人中比较，三者以上用最高级，前面还有 the，所以用 tallest。"),
    ],

    # ==========================================================
    # 5.3 频度副词与一般现在时综合
    # ==========================================================
    "5.3": [
        ("I ___ get up at six. 我总是六点起床。空白处应填哪个单词？", "always",
         ["never", "sometimes", "often"],
         "「总是」用 always，表示每次都这样；never 是「从不」，意思正好相反。"),
        ("She is ___ late for school. 她上学从来不迟到。空白处应填哪个单词？", "never",
         ["always", "often", "usually"],
         "「从来不」用 never，表示一次也没有；always 是「总是」，意思正好相反。"),
        ("下面哪一个频度副词表示「有时」？", "sometimes",
         ["always", "never", "usually"],
         "sometimes 是「有时」；always 是「总是」，usually 是「通常」，never 是「从不」。"),
        ("___ do you go to the library? — Twice a week. 空白处应填哪个词组？", "How often",
         ["How many", "How long", "How much"],
         "Twice a week 回答的是频率，问频率用 How often；How many 问数量，How long 问时长。"),
        ("My father usually ___ to work by car. 空白处应填哪个单词？", "goes",
         ["go", "going", "went"],
         "usually 表示经常，用一般现在时；主语 My father 是第三人称单数，动词 go 要加 es。"),
        ("Kate ___ her teeth twice a day. 空白处应填哪个单词？", "brushes",
         ["brush", "brushing", "brushed"],
         "twice a day 表示经常的习惯，用一般现在时；主语 Kate 是第三人称单数，brush 要加 es 变成 brushes。"),
    ],

    # ==========================================================
    # 5.4 名词单复数与不可数名词
    # ==========================================================
    "5.4": [
        ("There are three ___ on the desk. 空白处应填哪个单词？", "books",
         ["book", "bookes", "bookies"],
         "three 后面要接复数名词，book 的复数是 books；以 k 结尾直接加 s，不用加 es。"),
        ("There ___ some water in the glass. 空白处应填哪个单词？", "is",
         ["are", "be", "have"],
         "water 是不可数名词，看作单数，所以 be 动词用 is。"),
        ("How many ___ are there in your class? 空白处应填哪个单词？", "students",
         ["student", "studentes", "student's"],
         "How many 后面要接复数名词，student 的复数是 students。"),
        ("There are five ___ in the box. 空白处应填哪个单词？", "tomatoes",
         ["tomato", "tomatos", "tomato's"],
         "five 后面要接复数名词；tomato 以 o 结尾，复数要加 es，变成 tomatoes。"),
        ("下面哪一个单词是不可数名词？", "water",
         ["apple", "book", "pen"],
         "water（水）不可数，不能说成 waters；apple、book、pen 都是可数名词，可以有复数形式。"),
        ("These ___ are mine. 空白处应填哪个单词？", "boxes",
         ["box", "boxs", "boxies"],
         "These 后面要用复数名词；box 以 x 结尾，复数要加 es，变成 boxes。"),
    ],

    # ==========================================================
    # 6.1 现在完成时初步
    # ==========================================================
    "6.1": [
        ("I have already ___ my homework. 空白处应填哪个单词？", "finished",
         ["finish", "finishes", "finishing"],
         "现在完成时的结构是 have / has + 过去分词，finish 的过去分词是 finished。"),
        ("She ___ just cleaned the room. 空白处应填哪个单词？", "has",
         ["have", "is", "does"],
         "主语 She 是第三人称单数，现在完成时要用 has + 过去分词。"),
        ("They ___ lived here for ten years. 空白处应填哪个单词？", "have",
         ["has", "are", "were"],
         "for ten years 表示从过去持续到现在，用现在完成时；主语 They 是复数，用 have + 过去分词。"),
        ("___ you ever been to Beijing? 空白处应填哪个单词？", "Have",
         ["Has", "Are", "Did"],
         "主语 you 要用 have；ever 常和现在完成时连用，所以是 Have you ever been to Beijing?。"),
        ("He has ___ his lunch. 他已经吃过午饭了。空白处应填哪个单词？", "eaten",
         ["ate", "eat", "eating"],
         "has 后面要接过去分词，eat 的过去分词是 eaten；ate 是过去式，不能和 has 连用。"),
        ("I have ___ this book twice. 空白处应填哪个单词？", "read",
         ["readed", "reading", "reads"],
         "read 的过去分词还是 read，只是读音变成 /red/，不能写成 readed。"),
    ],

    # ==========================================================
    # 6.2 一般过去时（不规则动词）
    # ==========================================================
    "6.2": [
        ("I ___ to the zoo last Sunday. 空白处应填哪个单词？", "went",
         ["goed", "go", "going"],
         "go 是不规则动词，过去式是 went，不能加 -ed 写成 goed。"),
        ("She ___ a beautiful song yesterday. 空白处应填哪个单词？", "sang",
         ["singed", "sing", "singing"],
         "sing 是不规则动词，过去式是 sang，不是 singed。"),
        ("They ___ a lot of photos last week. 空白处应填哪个单词？", "took",
         ["taked", "take", "taking"],
         "take 是不规则动词，过去式是 took，不能写成 taked。"),
        ("He ___ his leg last month.（他上个月摔断了腿）空白处应填哪个单词？", "broke",
         ["breaked", "break", "breaking"],
         "break 是不规则动词，过去式是 broke，不能写成 breaked。"),
        ("We ___ a good time at the party. 空白处应填哪个单词？", "had",
         ["haved", "have", "having"],
         "have 是不规则动词，过去式是 had，不能写成 haved。"),
        ("The boy ___ his homework at home yesterday. 空白处应填哪个单词？", "did",
         ["doed", "do", "doing"],
         "do 是不规则动词，过去式是 did，不能写成 doed。"),
    ],

    # ==========================================================
    # 6.3 宾语从句与间接引语初步
    # ==========================================================
    "6.3": [
        ("Do you know where he ___ ? 空白处应填哪个单词？", "lives",
         ["does he live", "lives he", "live"],
         "宾语从句要用陈述语序（主语 + 谓语），主语 he 是第三人称单数，所以是 where he lives。"),
        ("Can you tell me ___ ? 空白处应填哪个词组？", "what time it is",
         ["what time is it", "what time does it", "what is time it"],
         "宾语从句要用陈述语序；what time is it 是疑问语序，只能用在直接问句里。"),
        ("She asked me ___ I liked English. 空白处应填哪个单词？", "if",
         ["that", "what", "which"],
         "把一般疑问句变成间接引语时，用 if 或 whether 表示「是否」。"),
        ("Tom said that he ___ busy that day. 空白处应填哪个单词？", "was",
         ["is", "were", "be"],
         "主句 said 是过去时，宾语从句的时态要往后推，is 要变成 was。"),
        ("She said, 「I like music.」变成间接引语：She said that she ___ music. 空白处应填哪个单词？", "liked",
         ["like", "likes", "liking"],
         "主句是过去时 said，从句时态要相应后推，like 要变成 liked。"),
        ("I want to know ___ . 空白处应填哪个句子？", "where she is",
         ["where is she", "where she be", "where does she"],
         "宾语从句要用陈述语序，所以是 where she is，不能写成疑问语序 where is she。"),
    ],

    # ==========================================================
    # 6.4 阅读理解与完形填空
    # ==========================================================
    "6.4": [
        ("阅读：Tom is a pupil. He gets up at six thirty. He goes to school at seven. "
         "He has four classes in the morning. 问：What time does Tom get up?",
         "At half past six.",
         ["At half past seven.", "At six o'clock.", "At seven thirty."],
         "短文里说他六点三十分起床，six thirty 就是 half past six（六点半）。"),
        ("阅读：Tom is a pupil. He gets up at six thirty. He goes to school at seven. "
         "He has four classes in the morning. 问：How many classes does Tom have in the morning?",
         "4.",
         ["3.", "5.", "6."],
         "短文里说 He has four classes in the morning，也就是上午有四节课。"),
        ("阅读：Lily has a cat. Its name is Mimi. Its fur is the same color as snow. "
         "Lily plays with Mimi when her classes are over. 问：What color is Mimi's fur?",
         "White.",
         ["Black.", "Yellow.", "Brown."],
         "短文说它的毛和雪是一样的颜色，雪是白色的，所以是 white。"),
        ("阅读：Lily has a cat. Its name is Mimi. Its fur is the same color as snow. "
         "Lily plays with Mimi when her classes are over. 问：When does Lily play with Mimi?",
         "After school.",
         ["Before school.", "In class.", "At midnight."],
         "when her classes are over 意思是「她的课结束以后」，也就是放学后 after school。"),
        ("完形：I am Amy. I am ten years old. I have a brother. He ___ eight. 空白处应填哪个单词？",
         "is",
         ["am", "are", "be"],
         "主语 He 是第三人称单数，be 动词要用 is；am 只能和 I 连用。"),
        ("完形：Last Sunday, Jack ___ to the park with his father. They played football there. "
         "空白处应填哪个单词？",
         "went",
         ["go", "goes", "going"],
         "Last Sunday 是过去时间，用一般过去时，go 的过去式是 went。"),
    ],
}
