# -*- coding: utf-8 -*-
"""一次性工具：把儿童端可见的错误提示统一成儿童化文案，真实技术错误只进 console。

用法：C:\\Python313\\python.exe tools\\clean_error_text.py
（只改 frontend/*.js 的指定行；每个替换都先校验原行内容，不匹配就整批不写。）
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# (文件, 起始行号(1基), 结束行号(1基), 原行必须包含的子串, 新行列表)
EDITS = [
    ("ability.js", 148, 149, "err.message",
     ['            console.error("[ability] 连接后端失败", err);',
      '            $("status").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;']),
    ("ability.js", 172, 172, "err.message",
     ['            console.error("[ability] 能力水平读取失败", err);',
      '            $("status").innerHTML = `<p class="diag-intro">菲比刚刚没拿到能力水平，我们再试一次。</p>`;']),
    ("diagnostic.js", 92, 92, "err.message",
     ['            console.error("[diagnostic] 连接后端失败", err);',
      '            $("hint").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;']),
    ("diagnostic.js", 128, 128, "err.message",
     ['            console.error("[diagnostic] 开始诊断失败", err);',
      '            $("hint").innerHTML = `<p class="diag-intro">菲比刚刚没能开始，我们再试一次。</p>`;']),
    ("diagnostic_report.js", 151, 151, "err.message",
     ['            console.error("[diagnostic_report] 报告读取失败", err);',
      '            $("report").innerHTML = `<p class="diag-intro">菲比刚刚没拿到报告，我们再试一次。</p>`;']),
    ("diagnostic_report.js", 169, 169, "err.message",
     ['            console.error("[diagnostic_report] 连接后端失败", err);',
      '            $("report").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;']),
    ("diagnostic_test.js", 158, 158, "err.message",
     ['            console.error("[diagnostic_test] 出题失败", err);',
      '            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没拿到题目，我们再试一次。</p>`;']),
    ("diagnostic_test.js", 206, 206, "err.message",
     ['            console.error("[diagnostic_test] 提交失败", err);',
      '            $("feedback").innerHTML = `<p class="diag-intro">菲比刚刚没收到你的答案，我们再试一次。</p>`;']),
    ("diagnostic_test.js", 239, 239, "err.message",
     ['            console.error("[diagnostic_test] 诊断记录读取失败", err);',
      '            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没拿到题目，我们再试一次。</p>`;']),
    ("habit.js", 87, 87, "err.message",
     ['        console.error("[habit] 连接后端失败", err);',
      '        $("habit-streak").textContent = "菲比现在连不上，请先双击 start.bat。";']),
    ("habit.js", 103, 103, "err.message",
     ['        console.error("[habit] 学习记录读取失败", err);',
      '        $("habit-streak").textContent = "菲比刚刚没拿到学习记录，我们再试一次。";']),
    ("habit.js", 158, 158, "err.message",
     ['        console.error("[habit] 休息保护失败", err);',
      '        $("habit-rest-result").textContent = "菲比刚刚没处理好，我们再试一次。";']),
    ("memory_debug.js", 181, 181, "err.message",
     ['            console.error("[memory_debug] 连接后端失败", err);',
      '            $("status").innerHTML = `<p class="diag-intro">连不上后端，请先双击 start.bat。</p>`;']),
    ("memory_debug.js", 215, 215, "err.message",
     ['            console.error("[memory_debug] 读取失败", err);',
      '            $("status").innerHTML = `<p class="diag-intro">记忆数据刚刚没读到，请再试一次。</p>`;']),
    ("recovery.js", 267, 267, "err.message",
     ['            console.error("[recovery] 错题加载失败", err);',
      '            $("status").innerHTML = `<p class="diag-intro">菲比刚刚没拿到错题，我们再试一次。</p>`;']),
    ("recovery.js", 299, 299, "err.message",
     ['            console.error("[recovery] 开始康复失败", err);',
      '            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没能开始，我们再试一次。</p>`;']),
    ("recovery.js", 318, 318, "err.message",
     ['            console.error("[recovery] 出题失败", err);',
      '            $("question").innerHTML = `<p class="diag-intro">菲比刚刚没拿到题目，我们再试一次。</p>`;']),
    ("recovery.js", 391, 391, "err.message",
     ['            console.error("[recovery] 提交失败", err);',
      '            $("result").innerHTML = `<p class="recovery-result-meta">😕 菲比刚刚没收到你的答案，再试一次吧。</p>`;']),
    ("recovery.js", 432, 433, "err.message",
     ['            console.error("[recovery] 连接后端失败", err);',
      '            $("status").innerHTML = `<p class="diag-intro">菲比现在连不上，请先双击 start.bat。</p>`;']),
    ("today.js", 994, 995, "err.message",
     ['            console.error("[today] 感受提交失败", err);',
      '            $("feel-box").innerHTML = `<p class="meta">😕 菲比刚刚没记下你的感受，不过没关系，继续加油～</p>',
      '                <button class="mode-btn" onclick="nextQuestion()">下一题 ➡️</button>`;']),
]

# 先按文件分组、从后往前替换，避免行号漂移
by_file = {}
for name, start, end, needle, new_lines in EDITS:
    by_file.setdefault(name, []).append((start, end, needle, new_lines))

for name, items in by_file.items():
    path = FRONTEND / name
    lines = path.read_text(encoding="utf-8").splitlines(keepends=False)
    for start, end, needle, new_lines in sorted(items, key=lambda x: -x[0]):
        block = "\n".join(lines[start - 1:end])
        if needle not in block:
            print("MISMATCH", name, start, repr(block[:100]))
            sys.exit(1)
        lines[start - 1:end] = new_lines
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    print("OK", name)

print("done")
