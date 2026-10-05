# ==============================================================
# 能力契约｜把项目打包 / 上传到 GitHub 仓库（ymrdhd/learning）
# 入口：main / collect_files / build_zip / api / ensure_repo / push
# 依赖：updater（文件白名单 _skip / _wanted、local_version）、requests、argparse / hashlib / json / os /
#       sys / zipfile / pathlib / base64；令牌取环境变量 GITHUB_TOKEN 或 tools/.github_token（不入库）
# 不负责：启动时对比版本与自动更新 → backend/updater.py、backend/update_check.py；分支保护 / Actions
# 验证：python tools/publish.py --dry-run（离线：只本地打包 dist/learning-<版本>.zip 并列出文件）
# 被调用：人工执行（每次改完要发版时）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.8 打包上传：把项目源码发到 GitHub 仓库 ymrdhd/learning。

用法（项目根目录）：

    python tools/publish.py --dry-run     # 只本地打包（dist/learning-<版本>.zip）+ 列出会传哪些文件
    python tools/publish.py --push        # 真正上传（需要令牌；详见下）

令牌（**绝不写进代码库**）：优先环境变量 ``GITHUB_TOKEN``，其次文件 ``tools/.github_token``（已 gitignore）。
仓库不存在时会自动建（默认私有，``--public`` 可改成公开）。上传走 GitHub Git Data API（免 git 客户端），
只上传与远端不同的文件（本地算 git blob sha1 比对远端 tree）。

注意：本机 hosts 目前把 github.com / api.github.com / raw.githubusercontent.com 指向 127.0.0.1，
上传与自动更新都会连不上；要么先放开这三条 hosts（见交付说明），要么用 ``--dry-run`` 打包后手工上传。
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import updater  # noqa: E402  （文件白名单与版本号唯一真相都在它那里）
import net_fallback  # noqa: E402  （hosts 拦 github 时用 DoH 解析 + 直连 IP）

API = "https://api.github.com"
DIST = ROOT / "dist"
TOKEN_FILE = ROOT / "tools" / ".github_token"


# ---------------- 本地：收集与打包 ----------------

def collect_files() -> list:
    """按 updater 的白名单收集要发布的文件（数据库 / .env / backup / 日志一律排除）。"""
    picked = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if updater._skip(rel) or not updater._wanted(rel):
            continue
        picked.append(rel)
    return sorted(picked)


def build_zip(paths: list) -> Path:
    """把收集到的文件打成 dist/learning-<版本>.zip，返回压缩包路径。"""
    DIST.mkdir(exist_ok=True)
    target = DIST / f"learning-{updater.local_version()}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in paths:
            zf.write(ROOT / rel, arcname=f"learning-{updater.local_version()}/{rel}")
    return target


# ---------------- 远端：Git Data API ----------------

def read_token(explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    if os.getenv("GITHUB_TOKEN", "").strip():
        return os.getenv("GITHUB_TOKEN").strip()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def api(token: str, method: str, url: str, **payload):
    """调一次 GitHub API，返回 (状态码, 解析后的 JSON)。"""
    data = json.dumps(payload).encode("utf-8") if payload else None
    status, body, how = net_fallback.http_request(
        method, url if url.startswith("http") else API + url, body=data, timeout=60,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "ai-learning-system-publisher",
                 "Content-Type": "application/json"},
    )
    if how != "dns":
        print("[提示] 本机 hosts 拦了 api.github.com，已改用 DoH 解析 + 直连 IP 访问")
    try:
        return status, json.loads(body)
    except Exception:
        return status, {"raw": body[:300].decode("utf-8", "replace")}

def blob_sha(data: bytes) -> str:
    """git 的 blob 哈希：sha1("blob <长度>\\0" + 内容)。"""
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def ensure_repo(token: str, repo: str, private: bool) -> tuple:
    """仓库存在就返回 (True, 说明)，不存在就建。返回 (成功?, 说明)。"""
    owner, name = repo.split("/", 1)
    code, info = api(token, "GET", f"/repos/{repo}")
    if code == 200:
        return True, f"仓库已存在：{info.get('full_name')}（{'私有' if info.get('private') else '公开'}）"
    if code not in (404, 403):
        return False, f"查仓库失败 HTTP {code}：{str(info)[:200]}"
    code, info = api(token, "POST", f"/orgs/{owner}/repos",
                     name=name, private=private, auto_init=False, description="AI 小学学习系统（菲比同学）")
    if code not in (201, 404, 403):
        return code == 201, f"建仓库（组织 {owner}）HTTP {code}：{str(info)[:200]}"
    code, info = api(token, "POST", "/user/repos", name=name, private=private, auto_init=False,
                     description="AI 小学学习系统（菲比同学）")
    if code == 201:
        return True, f"已新建仓库：{info.get('full_name')}（{'私有' if private else '公开'}）"
    return False, f"建仓库失败 HTTP {code}：{str(info)[:200]}"


def remote_tree(token: str, repo: str, branch: str) -> dict:
    """远端当前 tree：{相对路径: blob sha}；仓库还空着就返回 {}。"""
    code, info = api(token, "GET", f"/repos/{repo}/git/ref/heads/{branch}")
    if code != 200:
        return {}
    code, tree = api(token, "GET", f"/repos/{repo}/git/trees/{info['object']['sha']}?recursive=1")
    if code != 200:
        return {}
    return {item["path"]: item["sha"] for item in tree.get("tree", []) if item["type"] == "blob"}


def push(token: str, repo: str, branch: str, paths: list, message: str) -> tuple:
    """把文件按 Git Data API 提交到仓库。返回 (成功?, 说明)。"""
    known = remote_tree(token, repo, branch)
    changed, blobs = [], {}
    for rel in paths:
        data = (ROOT / rel).read_bytes()
        digest = blob_sha(data)
        if known.get(rel) == digest:
            continue
        code, info = api(token, "POST", f"/repos/{repo}/git/blobs",
                         content=base64.b64encode(data).decode("ascii"), encoding="base64")
        if code != 201:
            return False, f"上传 {rel} 失败 HTTP {code}：{str(info)[:200]}"
        blobs[rel] = info["sha"]
        changed.append(rel)

    tree_items = [{"path": rel, "mode": "100644", "type": "blob", "sha": sha} for rel, sha in blobs.items()]
    for rel in sorted(known):  # 远端里已经删掉的旧源码文件，随这次提交一起清掉
        if rel not in paths and not updater._skip(rel) and updater._wanted(rel):
            tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": None})
    if not tree_items:
        return True, "远端已经是最新，没有文件需要上传"

    status, parent = api(token, "GET", f"/repos/{repo}/git/ref/heads/{branch}")
    parent_sha = parent["object"]["sha"] if status == 200 else ""
    tree_payload = {"tree": tree_items}
    if parent_sha:
        tree_payload["base_tree"] = parent_sha
    code, tree = api(token, "POST", f"/repos/{repo}/git/trees", **tree_payload)
    if code != 201:
        return False, f"建 tree 失败 HTTP {code}：{str(tree)[:200]}"

    commit_payload = {"message": message, "tree": tree["sha"]}
    if parent_sha:
        commit_payload["parents"] = [parent_sha]
    code, commit = api(token, "POST", f"/repos/{repo}/git/commits", **commit_payload)
    if code != 201:
        return False, f"建 commit 失败 HTTP {code}：{str(commit)[:200]}"

    if commit_payload.get("parents"):
        code, info = api(token, "PATCH", f"/repos/{repo}/git/refs/heads/{branch}", sha=commit["sha"])
    else:
        code, info = api(token, "POST", f"/repos/{repo}/git/refs",
                         ref=f"refs/heads/{branch}", sha=commit["sha"])
    if code not in (200, 201):
        return False, f"更新分支失败 HTTP {code}：{str(info)[:200]}"
    return True, (f"已提交 {len(changed)} 个文件到 {repo}@{branch}"
                  f"（含删除 {sum(1 for i in tree_items if i['sha'] is None)} 个旧文件）：{commit['sha'][:8]}")


# ---------------- 命令行 ----------------

def main(argv=None) -> int:
    repo = os.getenv("UPDATE_REPO", updater.DEFAULT_REPO)
    parser = argparse.ArgumentParser(description="打包 / 上传本项目到 GitHub")
    parser.add_argument("--dry-run", action="store_true", help="只本地打包并列文件，不联网")
    parser.add_argument("--push", action="store_true", help="真正上传到仓库")
    parser.add_argument("--repo", default=repo, help=f"目标仓库（默认 {repo}）")
    parser.add_argument("--branch", default=os.getenv("UPDATE_BRANCH", updater.DEFAULT_BRANCH))
    parser.add_argument("--public", action="store_true", help="仓库不存在时建成公开的（默认私有）")
    parser.add_argument("--token", default="", help="GitHub 令牌（默认读 GITHUB_TOKEN / tools/.github_token）")
    parser.add_argument("--message", default="", help="提交说明（默认带版本号与 version.json 的 notes）")
    args = parser.parse_args(argv)

    version = updater.local_version()
    paths = collect_files()
    archive = build_zip(paths)
    print(f"[打包] 版本 {version} · {len(paths)} 个文件 · {archive.relative_to(ROOT)} "
          f"（{archive.stat().st_size / 1024:.0f} KB）")
    for rel in paths:
        print(f"       + {rel}")
    if not args.push:
        print("[提示] 这是本地打包（未上传）。要上传加 --push；也可以把 dist 里的 zip 拖到 GitHub 网页手工上传。")
        return 0

    token = read_token(args.token)
    if not token:
        print("[失败] 没有令牌：set GITHUB_TOKEN=xxx，或把令牌写进 tools/.github_token（该文件不入库）")
        return 2
    try:
        code, me = api(token, "GET", "/user")
        if code != 200:
            print(f"[失败] 令牌不可用 HTTP {code}：{str(me)[:200]}")
            return 2
        ok, note = ensure_repo(token, args.repo, not args.public)
        print(f"[仓库] {note}")
        if not ok:
            return 2
        message = args.message or f"V{version} {json.loads((ROOT / 'version.json').read_text('utf-8')).get('notes', '')[:60]}"
        ok, note = push(token, args.repo, args.branch, paths, message.strip())
        print(f"[上传] {note}")
        return 0 if ok else 2
    except Exception as exc:
        print(f"[失败] 连不上 GitHub（{type(exc).__name__}: {exc}）")
        print("       本机 hosts 可能把 github.com / api.github.com 指向了 127.0.0.1；"
              "先放开这三条 hosts 再试，或用 --dry-run 打包后手工上传。")
        return 3


if __name__ == "__main__":
    sys.exit(main())
