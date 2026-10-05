"""一次性工具：把 frontend/*.html 的 <script src> 统一成
phoebe.js -> phoebe3d.js -> ui-shell.js -> kid-lang.js -> ui-components.js -> 业务 js
共享层必须先于业务 js 加载（业务 js 在文件末尾会立刻调用 init()，要用到共享层）。
UTF-8 安全；执行后自检。"""
import pathlib
import re

PREF = ["phoebe.js", "phoebe3d.js", "ui-shell.js", "kid-lang.js", "ui-components.js"]
ROOT = pathlib.Path(__file__).resolve().parent.parent / "frontend"
PAT = re.compile(r'^[ \t]*<script src="([^"]+)"></script>[ \t]*\r?\n', re.M)

for path in sorted(ROOT.glob("*.html")):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    srcs = [m.group(1) for m in PAT.finditer(text)]
    if not srcs:
        continue
    uniq = []
    for s in srcs:
        if s not in uniq:
            uniq.append(s)
    ordered = [s for s in PREF if s in uniq] + [s for s in uniq if s not in PREF]
    block = "".join('<script src="%s"></script>\n' % s for s in ordered)

    state = {"done": False}

    def repl(_m, _block=block, _state=state):
        if _state["done"]:
            return ""
        _state["done"] = True
        return _block

    text = PAT.sub(repl, text)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print("%-24s %s" % (path.name, " -> ".join(ordered)))
