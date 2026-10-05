# ==============================================================
# 能力契约｜契约卡门禁：校验每张卡片的「入口」符号是否真的存在于对应文件
# 入口：module_files / main / ENTRY_RE / TOKEN_RE
# 依赖：os / re / sys（纯标准库，不 import 任何项目模块）
# 不负责：业务与接口验证 → verify_all.py 及其 12 个套件；卡片批量注入 → backup/tools/apply_module_cards.py
# 验证：python backend/check_cards.py
# 被调用：人工；改动任何契约卡之后（刻意不纳入 verify_all，以免改变其 849 断言基线）
# 索引：docs/MODULE_MAP.md（新增 / 改名模块必须同步该表）
# ==============================================================
"""校验「能力契约」卡片的入口字段：卡片里列的符号是否真的存在于对应文件。

为什么需要它：契约卡是给 AI agent 定位代码用的。卡片里写一个**不存在的符号**，
比不写卡片更糟 —— agent 会按卡 grep 然后扑空，白烧一轮 token。
首轮独立审查抽查 8 个文件就发现 3 处失实（`phoebe.js` 写了不存在的 `celebrateAnswer`），
因此把该检查固化为可重复门禁。

规则：
  * 只校验「入口：」行里形如 ASCII 标识符的 token（`A.B` 取最后一段 B）。
  * 描述性入口（含中文说明、路径、章节号）无法自动校验，单独列出待人工确认。
  * token 判定：该标识符须在对应文件正文中出现（词边界匹配）。

用法：python backend/check_cards.py
退出码：0 = 全部通过；1 = 存在失实符号或前 12 行内缺卡片
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "能力契约｜"
ENTRY_RE = re.compile(r"^(?:#|//)\s*入口：(.+)$", re.M)
TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")

# 非符号噪声（英文通用词 / 文件后缀 / 说明性词）
NOISE = {
    "API", "api", "Router", "router", "python", "Python", "backend", "frontend",
    "None", "and", "or", "the", "True", "False", "py", "js", "html", "css",
    "DEFAULT", "see",
}


def module_files():
    """后端 .py + 前端 .js 的全部模块文件（排除 __pycache__）。"""
    paths = []
    for base in ("backend", "frontend"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, base)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith((".py", ".js")):
                    paths.append(os.path.join(dirpath, name))
    return sorted(paths)


def main():
    bad = []          # (rel, token)
    manual = []       # (rel, entry_text)
    no_card = []
    checked = 0
    for path in module_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        head = "\n".join(text.splitlines()[:12])
        if MARK not in head:
            no_card.append(rel)
            continue
        match = ENTRY_RE.search(head)
        if not match:
            manual.append((rel, "(入口行缺失)"))
            continue
        entry = match.group(1).strip()
        checked += 1
        tokens = []
        for raw in re.split(r"[／/、,，+＋|()（）\[\]【】:：\s]+", entry):
            token = raw.strip("`*　 ")
            if not token or not TOKEN_RE.match(token):
                continue
            leaf = token.split(".")[-1]
            if leaf in NOISE or len(leaf) < 3:
                continue
            tokens.append(leaf)
        if not tokens:
            manual.append((rel, entry[:70]))
            continue
        for leaf in sorted(set(tokens)):
            if not re.search(r"\b" + re.escape(leaf) + r"\b", text):
                bad.append((rel, leaf))
    print(f"校验模块数: {checked}   无卡片: {len(no_card)}   失实符号: {len(bad)}   需人工确认: {len(manual)}")
    if bad:
        print("\n--- 失实符号（必须修）---")
        for rel, token in bad:
            print(f"  {rel}  →  `{token}` 在文件中不存在")
    if manual:
        print("\n--- 描述性入口（无法自动校验，待人工确认）---")
        for rel, entry in manual:
            print(f"  {rel}  →  {entry}")
    if no_card:
        print("\n--- 前 12 行内无契约卡 ---")
        for rel in no_card:
            print(f"  {rel}")
    return 1 if (bad or no_card) else 0


if __name__ == "__main__":
    sys.exit(main())
