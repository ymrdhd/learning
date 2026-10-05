# ==============================================================
# 能力契约｜全量验证编排：串行跑全部套件（review/flow/web/diagnostic/.../recovery/habit/recall），各自独立端口与临时库，只输出 RESULT 与退出码
# 入口：main / SUITES / node_exe
# 依赖：subprocess socket（绝对路径自解析）
# 不负责：单个套件的断言内容 → 各 verify_*.py
# 验证：python backend/verify_all.py
# 被调用：人工与 CI 入口
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""一键跑完全部验证（V2.3 统一入口）。

每个套件各用独立端口，串行执行，互不抢端口/数据库：

    python backend/verify_all.py

- 复习闭环：自带临时后端 + 临时库
- 学习闭环回归：自带临时后端 + 临时库（与上面端口不同）
- 能力诊断引擎：自带临时后端 + 临时库（端口 8902）
- 知识掌握与错因分析：自带临时后端 + 临时库（端口 8904）
- 自适应学习引擎：自带临时后端 + 临时库（端口 8905）
- 间隔复习系统：自带临时后端 + 临时库（端口 8906）
- 训练数据自动能力诊断：自带临时后端 + 临时库（端口 8907）
- 菲比 AI 陪伴对话：自带临时后端 + 临时库（端口 8908，**强制离线开关，不联网**）
- 前端语音/复习逻辑：node + DOM 打桩，无端口
- 前端诊断页面逻辑：node + DOM 打桩，无端口
- 前端知识地图/错题本逻辑：node + DOM 打桩，无端口
- 前端今日学习/学习反馈逻辑：node + DOM 打桩，无端口
- 前端知识浇水/记忆数据逻辑：node + DOM 打桩，无端口
- 前端菲比庆祝模块：node + DOM 打桩，无端口
- 前端菲比三视图立牌：node + DOM 打桩，无端口
- 前端能力水平页逻辑：node + DOM 打桩，无端口

只跑其中几个：

    python backend/verify_all.py knowledge knowweb phoebe3dweb
"""

import os
import socket
import subprocess
import sys
import time

BACKEND = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(os.path.dirname(BACKEND), "frontend")
PY = sys.executable


def node_exe():
    """优先用捆绑的 node，其次 PATH 里的 node。"""
    bundled = os.path.join(
        os.environ.get("USERPROFILE", ""),
        ".dsh", "dsh-runtimes", "dsh-primary-runtime", "dependencies", "node", "bin", "node.exe",
    )
    return bundled if os.path.exists(bundled) else "node"


SUITES = {
    "review": {
        "title": "艾宾浩斯复习闭环",
        "port": 8899,
        "cmd": [PY, os.path.join(BACKEND, "verify_review.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_REVIEW_PORT": "8899"},
    },
    "flow": {
        "title": "学习闭环回归",
        "port": 8900,
        "cmd": [PY, os.path.join(BACKEND, "verify_flow.py"), "--self-serve"],
        "cwd": BACKEND,
        "env": {"VERIFY_FLOW_PORT": "8900", "VERIFY_BASE": ""},
    },
    "web": {
        "title": "前端语音/复习逻辑",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "diagnostic": {
        "title": "能力诊断引擎",
        "port": 8902,
        "cmd": [PY, os.path.join(BACKEND, "verify_diagnostic.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_DIAG_PORT": "8902"},
    },
    "diagweb": {
        "title": "前端诊断页面逻辑",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_diagnostic_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "knowledge": {
        "title": "知识掌握与错因分析",
        "port": 8904,
        "cmd": [PY, os.path.join(BACKEND, "verify_knowledge.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_KNOWLEDGE_PORT": "8904"},
    },
    "knowweb": {
        "title": "前端知识地图/错题本逻辑",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_knowledge_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "adaptive": {
        "title": "自适应学习引擎",
        "port": 8905,
        "cmd": [PY, os.path.join(BACKEND, "verify_adaptive.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_ADAPTIVE_PORT": "8905"},
    },
    "adaptweb": {
        "title": "前端今日学习/反馈逻辑",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_adaptive_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "memory": {
        "title": "间隔复习系统",
        "port": 8906,
        "cmd": [PY, os.path.join(BACKEND, "verify_memory.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_MEMORY_PORT": "8906"},
    },
    "memweb": {
        "title": "前端知识浇水/记忆数据逻辑",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_memory_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "phoebeweb": {
        "title": "前端菲比庆祝模块",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_phoebe_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "phoebe3dweb": {
        "title": "前端菲比三视图立牌",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_phoebe3d_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "uishell": {
        "title": "前端共享UI层",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_ui_shell.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "growthweb": {
        "title": "前端成长/我的页",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_growth_profile_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "ability": {
        "title": "训练数据自动能力诊断",
        "port": 8907,
        "cmd": [PY, os.path.join(BACKEND, "verify_ability.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_ABILITY_PORT": "8907"},
    },
    "abilityweb": {
        "title": "前端能力水平页逻辑",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_ability_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "phoebeai": {
        "title": "菲比 AI 陪伴对话",
        "port": 8908,
        "cmd": [PY, os.path.join(BACKEND, "verify_phoebe_ai.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_PHOEBE_PORT": "8908", "PHOEBE_AI_OFFLINE": "1"},
    },
    "recovery": {
        "title": "错题康复系统",
        "port": 8910,
        "cmd": [PY, os.path.join(BACKEND, "verify_recovery.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_RECOVERY_PORT": "8910"},
    },
    "habit": {
        "title": "每日学习习惯系统",
        "port": 8911,
        "cmd": [PY, os.path.join(BACKEND, "verify_habit.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_HABIT_PORT": "8911"},
    },
    "recall": {
        "title": "主动回忆与每日总结",
        "port": 8912,
        "cmd": [PY, os.path.join(BACKEND, "verify_active_recall.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_RECALL_PORT": "8912"},
    },
    "v26": {
        "title": "V2.6 儿童体验（首页聚合/知识地图/成长中心/挑战中心/隔离）",
        "port": 8913,
        "cmd": [PY, os.path.join(BACKEND, "verify_v26.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_V26_PORT": "8913"},
    },
    "v26web": {
        "title": "V2.6 儿童端前端（今天/挑战/知识地图/学习会话）",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_v26_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
    "userreset": {
        "title": "家长端备份并重置",
        "port": 8914,
        "cmd": [PY, os.path.join(BACKEND, "verify_user_reset.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_USER_RESET_PORT": "8914"},
    },
    "points": {
        "title": "积分系统（答对 / 打卡 / 计划做完后继续练 / 任务收工）",
        "port": 8915,
        "cmd": [PY, os.path.join(BACKEND, "verify_points.py")],
        "cwd": BACKEND,
        "env": {"VERIFY_POINTS_PORT": "8915"},
    },
    "shopweb": {
        "title": "积分商城页（商品 + 积分明细）",
        "port": None,
        "cmd": [node_exe(), os.path.join(FRONTEND, "verify_shop_web.js")],
        "cwd": FRONTEND,
        "env": {},
    },
}


def port_in_use(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def use_utf8_stdout():
    """子套件的输出里带 emoji，Windows 控制台默认 GBK 会直接把汇总打印打断。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv):
    use_utf8_stdout()

    names = [a for a in argv[1:] if a in SUITES] or list(SUITES)
    unknown = [a for a in argv[1:] if a not in SUITES]
    if unknown:
        print(f"未知的套件: {', '.join(unknown)}；可选: {', '.join(SUITES)}")
        return 2

    env_base = dict(os.environ)
    env_base["PYTHONIOENCODING"] = "utf-8"
    env_base["PYTHONUTF8"] = "1"

    results = []
    for name in names:
        suite = SUITES[name]
        print(f"\n{'=' * 60}\n[{name}] {suite['title']}\n{'=' * 60}")

        if suite["port"] and port_in_use(suite["port"]):
            print(f"FAIL  端口 {suite['port']} 已被占用，先关掉占用进程再跑")
            results.append((name, False, 0.0))
            continue

        env = dict(env_base, **suite["env"])
        started = time.time()
        proc = subprocess.run(suite["cmd"], cwd=suite["cwd"], env=env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        elapsed = time.time() - started

        output = (proc.stdout or "") + (proc.stderr or "")
        for line in output.splitlines():
            if line.startswith(("PASS", "FAIL")) or "RESULT" in line or "Error" in line:
                print("  " + line)

        passed = proc.returncode == 0
        results.append((name, passed, elapsed))
        print(f"→ {suite['title']}: {'通过' if passed else '失败'}（{elapsed:.1f}s）")

    print(f"\n{'=' * 60}\n汇总\n{'=' * 60}")
    for name, passed, elapsed in results:
        print(f"  {'✅' if passed else '❌'} {SUITES[name]['title']:<16} {elapsed:6.1f}s")
    all_ok = all(passed for _, passed, _ in results)
    print(f"\nRESULT: {'ALL PASS' if all_ok else 'HAS FAILURES'}（合计 {sum(e for _, _, e in results):.1f}s）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
