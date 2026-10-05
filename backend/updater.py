# ==============================================================
# 能力契约｜版本对比与自动更新（读 version.json → 比对仓库 → 下载仓库归档 → 覆盖代码文件）
# 入口：local_version / parse_version / is_newer / remote_manifest / download_archive / apply / run
# 依赖：requests（项目已有，deepseek.py 同款；缺失时整套降级为「不更新」）、
#       json / os / io / re / shutil / tarfile / datetime / pathlib
# 不负责：把代码传上仓库 → tools/publish.py；启动流程编排 → backend/update_check.py、start.bat；
#         数据库迁移（新表靠 import 期 Base.metadata.create_all，更新只覆盖代码文件，绝不碰 .db / .env）
# 验证：python backend/update_check.py --self-test（离线：版本比较 / 保护名单 / 临时目录试同步）
# 被调用：backend/update_check.py、start.bat（每次启动）、backend/main.py（只读 local_version()）
# 索引：docs/MODULE_MAP.md（新增/改名模块必须同步该表）
# ==============================================================

"""V2.8 版本对比与自动更新。

口径：
    * ``version.json`` 是版本号唯一真相（本机与仓库是同一份文件）；
    * 每次启动只做「对比 + 有更新就覆盖代码文件」，**绝不碰**数据库 / .env / backup / 日志；
    * 网络不通、仓库不可达、归档坏掉…… 一律吞异常并返回原因，**绝不让启动失败**；
    * 覆盖前把将被改写的文件原样复制到 ``backup/pre-update-<本机版本>/``（项目无 git 时的回退网）。
"""

import io
import json
import os
import re
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

try:  # 出题模块同款依赖；装不上也不影响启动，只是不更新
    import requests
except Exception:  # pragma: no cover - 环境缺依赖时的降级
    requests = None

try:  # hosts 把 github 指向 127.0.0.1 时的 DoH + 直连兜底（没有它只是连不上，不影响启动）
    import net_fallback
except Exception:  # pragma: no cover - 环境缺依赖时的降级
    net_fallback = None
ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "version.json"
LOG_FILE = ROOT / "update.log"
DEFAULT_REPO = "ymrdhd/learning"
DEFAULT_BRANCH = "main"
TIMEOUT = 12

MANIFEST_URLS = (
    "https://raw.githubusercontent.com/{repo}/{branch}/version.json",
    "https://cdn.jsdelivr.net/gh/{repo}@{branch}/version.json",
)
ARCHIVE_URL = "https://codeload.github.com/{repo}/tar.gz/refs/heads/{branch}"

# 只同步这些目录 / 文件；其余（backup / 日志 / 数据库 / .env）一律不动
SYNC_TOP = ("backend", "frontend", "docs", "tools")
SYNC_FILES = ("version.json", "start.bat", "README.md", "PROJECT_CONTEXT.md",
              "AI_RULES.md", "AGENTS.md", "requirements.txt", ".gitignore")
SYNC_SUFFIX = (".py", ".js", ".html", ".css", ".md", ".json", ".bat", ".txt")
SKIP_DIRS = ("__pycache__", ".git", ".dsh-swarm", "dist", ".update-backup",
             "backup", "node_modules", "python-venv")
SKIP_NAMES = ("learning.db", ".env", "update.log", ".github_token")
SKIP_PREFIX = ("_verify_", "out_")
SKIP_SUFFIX = (".db", ".db-journal", ".db-wal", ".db-shm", ".pyc", ".log")


# ---------------- 版本号 ----------------

def local_version() -> str:
    """本机版本号（读 version.json；文件坏了就返回 0.0.0，绝不抛异常）。"""
    try:
        data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        return str(data.get("version") or "0.0.0")
    except Exception:
        return "0.0.0"


def parse_version(text) -> tuple:
    """把「2.8.0」这类文本拆成 (2, 8, 0)，长度不足补 0，方便直接比大小。"""
    nums = [int(n) for n in re.findall(r"\d+", str(text or ""))][:3]
    return tuple(nums + [0] * (3 - len(nums)))


def is_newer(remote, local) -> bool:
    """仓库版本是否比本机新。"""
    return parse_version(remote) > parse_version(local)


# ---------------- 保护名单 ----------------

def _skip(rel: str) -> bool:
    """该相对路径是否禁止被更新覆盖（数据库 / 私密配置 / 备份 / 临时产物）。"""
    parts = rel.replace("\\", "/").split("/")
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    if name in SKIP_NAMES or name.startswith(SKIP_PREFIX):
        return True
    if ".db." in name:  # 数据库派生物（learning.db.v15-backup / learning.db.bak 等）一律不动
        return True
    return name.endswith(SKIP_SUFFIX)


def _wanted(rel: str) -> bool:
    """是否属于本项目的源码范围。"""
    rel = rel.replace("\\", "/")
    head = rel.split("/")[0]
    return head in SYNC_TOP or rel in SYNC_FILES


# ---------------- 取仓库版本 ----------------

def _headers() -> dict:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _repo_branch() -> tuple:
    return (os.getenv("UPDATE_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO,
            os.getenv("UPDATE_BRANCH", DEFAULT_BRANCH).strip() or DEFAULT_BRANCH)


def _http_get(url: str, timeout: int = TIMEOUT):
    """统一网络出口 → (状态码, 字节, how)。正常 DNS 连不上时走 net_fallback 的 DoH + 直连。"""
    if net_fallback is None:
        if requests is None:
            raise RuntimeError("requests 不可用")
        resp = requests.get(url, timeout=timeout, headers=_headers())
        return resp.status_code, resp.content, "dns"
    status, data, how = net_fallback.http_request("GET", url, headers=_headers(), timeout=timeout)
    if how != "dns":
        _log("本机 hosts 拦了更新地址，已改用 DoH 解析 + 直连 IP 访问")
    return status, data, how


def download_archive(timeout: int = TIMEOUT) -> bytes:
    """下载仓库归档（tar.gz）。"""
    repo, branch = _repo_branch()
    status, data, _how = _http_get(ARCHIVE_URL.format(repo=repo, branch=branch), timeout=timeout)
    if status != 200:
        raise RuntimeError(f"归档下载失败（HTTP {status}）")
    return data


def remote_manifest(timeout: int = TIMEOUT):
    """仓库版本清单 → (manifest, 来源, 归档字节或 None)；拿不到就 (None, "", None)。"""
    repo, branch = _repo_branch()
    custom = os.getenv("UPDATE_MANIFEST_URL", "").strip()
    urls = ([custom] if custom else []) + [u.format(repo=repo, branch=branch) for u in MANIFEST_URLS]
    for url in urls:
        if requests is None and net_fallback is None:
            break
        try:
            status, raw, _how = _http_get(url, timeout=timeout)
            if status == 200:
                data = json.loads(raw.decode("utf-8"))
                if data.get("version"):
                    return data, url, None
        except Exception:
            continue
    try:  # 兜底：raw 被拦截时，归档口（codeload）往往还通，顺带把归档留着重用
        blob = download_archive(timeout=timeout)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.count("/") == 1 and member.name.endswith("/version.json"):
                    handle = tar.extractfile(member)
                    if handle is not None:
                        data = json.loads(handle.read().decode("utf-8"))
                        if data.get("version"):
                            return data, "archive", blob
    except Exception:
        pass
    return None, "", None


# ---------------- 覆盖代码文件 ----------------

def _prune(root: Path, remote: set) -> list:
    """删掉仓库里已经不存在的旧源码文件（保护名单与备份目录永不删）。"""
    removed = []
    for top in SYNC_TOP:
        base = root / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in remote or _skip(rel) or not rel.endswith(SYNC_SUFFIX):
                continue
            try:
                path.unlink()
                removed.append(rel)
            except OSError:
                continue
    return removed


def apply(blob: bytes, *, dry_run: bool = False, target_root=None, keep_backup: bool = True) -> dict:
    """把仓库归档覆盖到 target_root（默认项目根）。dry_run=True 只算不写。"""
    root = Path(target_root) if target_root else ROOT
    dest_backup = root / "backup" / f"pre-update-{local_version()}"
    written, skipped, removed, backup = [], [], [], ""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        entries = []
        remote = set()
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
            if not rel or _skip(rel) or not _wanted(rel):
                skipped.append(rel)
                continue
            remote.add(rel)
            entries.append((rel, member))
        entries.sort(key=lambda item: item[0] == "version.json")  # version.json 最后落地
        for rel, member in entries:
            if dry_run:  # 只算不写：把「计划覆盖哪些文件」照样报出来
                written.append(rel)
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            payload = handle.read()
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if keep_backup and target.exists():
                bak = dest_backup / rel
                bak.parent.mkdir(parents=True, exist_ok=True)
                if not bak.exists():
                    shutil.copy2(target, bak)
                backup = str(dest_backup)
            target.write_bytes(payload)
            written.append(rel)
        if not dry_run:
            removed = _prune(root, remote)
    return {"written": written, "skipped": skipped, "removed": removed, "backup": backup}


# ---------------- 对外主流程 ----------------

def _log(line: str, enabled: bool = True) -> None:
    if not enabled:
        return
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line}\n")
    except Exception:
        pass


def run(*, apply_update: bool = False, force: bool = False, log: bool = True) -> dict:
    """启动时调用：对比仓库版本号，需要时覆盖代码文件。永远返回 dict，不抛异常。"""
    local = local_version()
    result = {"ok": True, "local": local, "remote": local, "newer": False, "updated": False,
              "source": "", "written": 0, "removed": 0, "backup": "", "message": ""}
    manifest, source, blob = remote_manifest()
    if not manifest:
        result.update(ok=False, message=f"连不上更新仓库，继续用本机 {local}")
        _log(result["message"], log)
        return result
    remote = str(manifest.get("version") or local)
    result.update(remote=remote, source=source, newer=is_newer(remote, local))
    if not (result["newer"] or force):
        result["message"] = f"已是最新（{local}）"
        _log(result["message"], log)
        return result
    if not apply_update:
        result["message"] = f"发现新版本 {remote}（本机 {local}），加 --apply 才会更新"
        _log(result["message"], log)
        return result
    try:
        info = apply(blob if blob is not None else download_archive())
    except Exception as exc:
        result.update(ok=False, message=f"更新失败（{type(exc).__name__}），继续用本机 {local}")
        _log(result["message"], log)
        return result
    result.update(updated=True, written=len(info["written"]), removed=len(info["removed"]),
                  backup=info["backup"],
                  message=f"已更新到 {remote}（覆盖 {len(info['written'])} 个文件，"
                          f"清理 {len(info['removed'])} 个旧文件）")
    _log(result["message"], log)
    return result
