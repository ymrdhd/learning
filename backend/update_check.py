# ==============================================================
# 能力契约｜自动更新的命令行入口（启动时对比仓库版本号；有更新就覆盖代码文件）
# 入口：main / self_test / print_result
# 依赖：updater（版本比较 / 下载 / 覆盖）、argparse、json、os、sys、shutil、io、tarfile、pathlib
# 不负责：版本比较与覆盖细节 → updater.py；把项目传上仓库 → tools/publish.py
# 验证：python backend/update_check.py --self-test（离线自检：版本比较 / 保护名单 / 临时目录试同步）
# 被调用：start.bat（每次启动跑 `python update_check.py --apply`）、人工排查
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.8 启动时自动更新。

用法（在 backend 目录下，或写全路径）：

    python backend/update_check.py              # 只对比版本号，不下载
    python backend/update_check.py --apply      # 有新版本就覆盖代码文件（start.bat 用这个）
    python backend/update_check.py --force      # 不管版本号，强制按仓库覆盖一次
    python backend/update_check.py --self-test  # 离线自检（不联网：版本比较 / 保护名单 / 临时目录试同步）

纪律：**永远不影响启动**。连不上仓库、归档坏掉、覆盖失败…… 都只在屏幕上说一句，退出码非 0 也不会中断 start.bat。
"""

import argparse
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import updater  # noqa: E402  （必须先把 backend 放进 sys.path）

BACKEND = Path(__file__).resolve().parent
ROOT = BACKEND.parent


def print_result(result: dict) -> None:
    """把 updater.run 的结果印成一行中文。"""
    print(f"[更新] {result.get('message', '')}")


# ---------------- 离线自检 ----------------

def self_test() -> int:
    """不联网：版本比较 / 保护名单 / 临时目录试同步 / 启动接线 的断言。"""
    total = passed = 0

    def check(title, ok):
        nonlocal total, passed
        total += 1
        passed += 1 if ok else 0
        print(f"{'PASS' if ok else 'FAIL'}  {title}")

    check("版本号解析：2.8.1 > 2.8.0", updater.is_newer("2.8.1", "2.8.0"))
    check("版本号解析：v2.10 > 2.9.9（不是字符串比较）", updater.is_newer("v2.10", "2.9.9"))
    check("版本号解析：2.8 与 2.8.0 视为同一版", not updater.is_newer("2.8", "2.8.0"))
    check("版本号解析：相同版本不算新", not updater.is_newer("2.8.0", "2.8.0"))
    check("版本号解析：空 / 垃圾文本不会抛异常", updater.parse_version(None) == (0, 0, 0))
    check("本机版本号读的是 version.json", updater.local_version() == json.loads(
        (ROOT / "version.json").read_text(encoding="utf-8"))["version"])
    check("保护名单：数据库不覆盖", updater._skip("backend/learning.db"))
    check("保护名单：.env 不覆盖", updater._skip("backend/.env"))
    check("保护名单：backup/ 不覆盖", updater._skip("backup/snapshots/prism.js"))
    check("保护名单：__pycache__ 不覆盖", updater._skip("backend/__pycache__/x.pyc"))
    check("保护名单：update.log / 临时库 / 日志不覆盖",
          all(updater._skip(n) for n in ("update.log", "backend/_verify_points.db", "out_verify_all.txt")))
    check("保护名单：数据库备份 *.db.* 不覆盖",
          all(updater._skip(n) for n in ("backend/learning.db.v15-backup", "backend/learning.db.bak")))
    check("保护名单：源码要覆盖", not updater._skip("backend/points.py") and not updater._skip("frontend/today.js"))

    # 造一个假仓库归档，试跑一次真覆盖
    version_new = "9.9.9"
    payload = {f"learning-main/{rel}": body for rel, body in {
        "version.json": json.dumps({"version": version_new}, ensure_ascii=False),
        "backend/demo_mod.py": "# 新版\n",
        "frontend/demo.js": "// 新版\n",
        "backend/learning.db": "别动我\n",
        "backend/.env": "KEY=别动\n",
        "backup/pre-update-2.8.0/backend/demo_mod.py": "别动\n",
    }.items()}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, body in payload.items():
            data = body.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    blob = buffer.getvalue()

    # 临时目录放在项目内 dist/ 下（已 gitignore）：系统 %TEMP% 与 mkdtemp 建的目录在本机建不了子目录
    tmp_root = ROOT / "dist" / "_selftest"
    shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        root = tmp_root / "a"
        (root / "backend").mkdir(parents=True)
        (root / "frontend").mkdir()
        (root / "backend" / "demo_mod.py").write_text("# 老版\n", encoding="utf-8")
        (root / "backend" / "learning.db").write_text("本地数据\n", encoding="utf-8")
        (root / "backend" / "stale_mod.py").write_text("# 仓库里已经没有这个文件\n", encoding="utf-8")

        updater.apply(blob, target_root=root)
        check("覆盖：新文件落地", (root / "backend" / "demo_mod.py").read_text(encoding="utf-8") == "# 新版\n")
        check("覆盖：数据库一个字节没动", (root / "backend" / "learning.db").read_text(encoding="utf-8") == "本地数据\n")
        check("覆盖：.env 不落地", not (root / "backend" / ".env").exists())
        check("覆盖：仓库里没有的旧源码被清理", not (root / "backend" / "stale_mod.py").exists())
        check("覆盖：改前文件有备份", (root / "backup" / f"pre-update-{updater.local_version()}" /
                                 "backend" / "demo_mod.py").read_text(encoding="utf-8") == "# 老版\n")
        check("覆盖：version.json 跟着仓库走", json.loads(
            (root / "version.json").read_text(encoding="utf-8"))["version"] == version_new)
        check("dry_run：只算不写（计划里有文件）",
              len(updater.apply(blob, dry_run=True, target_root=root)["written"]) > 0)

        root2 = tmp_root / "b"
        (root2 / "backend").mkdir(parents=True)
        (root2 / "backend" / "demo_mod.py").write_text("# 老版\n", encoding="utf-8")
        updater.apply(blob, dry_run=True, target_root=root2)
        check("dry_run：一个文件都没写",
              (root2 / "backend" / "demo_mod.py").read_text(encoding="utf-8") == "# 老版\n"
              and not (root2 / "version.json").exists())
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    # 连不上仓库 / 有新版本但不带 --apply：都必须只说不写
    real_manifest = updater.remote_manifest
    try:
        updater.remote_manifest = lambda *a, **k: (None, "", None)
        offline = updater.run(apply_update=True, log=False)
        check("连不上仓库时不抛异常、只给一句提示",
              offline["ok"] is False and "连不上更新仓库" in offline["message"])
        updater.remote_manifest = lambda *a, **k: ({"version": "99.0.0"}, "stub", None)
        peek = updater.run(apply_update=False, log=False)
        check("有新版本但不带 --apply：只报告、不动文件",
              peek["newer"] is True and peek["updated"] is False and "加 --apply" in peek["message"])
    finally:
        updater.remote_manifest = real_manifest

    check("main.py 的根接口版本号来自 version.json", "updater.local_version()" in
          (BACKEND / "main.py").read_text(encoding="utf-8", errors="ignore"))
    check("start.bat 每次启动都会对比仓库版本", "update_check.py --apply" in
          (ROOT / "start.bat").read_text(encoding="utf-8", errors="ignore"))
    check("hosts 拦 github 时能直连：net_fallback 在位且被 updater / publish 用上",
          (BACKEND / "net_fallback.py").exists()
          and "net_fallback" in (BACKEND / "updater.py").read_text(encoding="utf-8", errors="ignore")
          and "net_fallback" in (ROOT / "tools" / "publish.py").read_text(encoding="utf-8", errors="ignore"))

    print(f"合计 {total} 项断言：PASS {passed} / FAIL {total - passed}")
    print(f"RESULT: {'ALL PASS' if passed == total else 'FAILED'}")
    return 0 if passed == total else 1


# ---------------- 命令行 ----------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="对比 GitHub 仓库版本号，必要时自动更新代码文件")
    parser.add_argument("--apply", action="store_true", help="有新版本就覆盖代码文件")
    parser.add_argument("--force", action="store_true", help="不管版本号，强制按仓库覆盖一次")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--self-test", action="store_true", help="离线自检（不联网）")
    parser.add_argument("--version", action="store_true",
                        help="只打印本机版本号（start.bat 读它填 TARGET_VERSION，不接受额外输出）")
    args = parser.parse_args(argv)

    if args.version:
        print(updater.local_version())
        return 0

    if args.self_test:
        return self_test()

    result = updater.run(apply_update=args.apply, force=args.force)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print_result(result)
    if not result.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
