# ==============================================================
# 能力契约｜验证：套件端口守卫（确保端口空闲，避免连上别人的服务造成假通过）
# 入口：脚本自身：python backend/verify_port_guard.py
# 依赖：socket os subprocess
# 不负责：业务断言 → 各 verify_*.py
# 验证：python backend/verify_port_guard.py（与全量互斥）
# 被调用：人工：全量测试前检查
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""验证 verify_review.py 的端口占用保护：

1. 先占住 8899 端口，此时 verify_review.py 必须立刻报错退出（不能连上别人的服务跑出假通过）
2. 释放端口后再跑一次，必须全部通过且不残留进程

用法：python backend/verify_port_guard.py
"""
import os
import socket
import subprocess
import sys
import time

BACKEND = os.path.dirname(os.path.abspath(__file__))
PORT = 8899
ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        ok = False


def port_open():
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def run_review():
    return subprocess.run(
        [sys.executable, os.path.join(BACKEND, "verify_review.py")],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", timeout=180,
    )


# 用一个假服务占住端口（只需能被 TCP 连上）
blocker = socket.socket()
blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
blocker.bind(("127.0.0.1", PORT))
blocker.listen(5)
check("测试前端口被占住", port_open())

try:
    busy = run_review()
    check("端口被占用时立即失败", busy.returncode != 0, busy.returncode)
    check("给出明确的占用提示", "已被占用" in busy.stdout, busy.stdout.strip()[:80])
    check("不会连上别人的服务跑测试", "RESULT:" not in busy.stdout, busy.stdout.strip()[-60:])
finally:
    blocker.close()

time.sleep(0.5)
check("释放端口后端口关闭", not port_open())

good = run_review()
check("端口空闲时全部通过", good.returncode == 0, good.returncode)
check("输出 ALL PASS", "ALL PASS" in good.stdout, good.stdout.strip().splitlines()[-1:])

time.sleep(0.5)
check("跑完不残留进程（端口已释放）", not port_open())
check("跑完删除临时库", not os.path.exists(os.path.join(BACKEND, "_verify_review.db")))

print("\nRESULT:", "ALL PASS" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)
