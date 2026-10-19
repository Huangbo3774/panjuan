# -*- coding: utf-8 -*-
"""故意打坏「前端/脚本编码」这四把尺，验证它们真的会报 FAIL。

为什么要有这个文件：闸门只跑一次"全绿"不说明它会响。前端的这几把尺
（gate.js 挂载、注释闭合、.ps1 BOM、.vbs ASCII）都是"缺一处就整页失灵"的类型，
而 check_web_js.py 自己就曾经漏掉过一次——我注入 gate.js 时忘了写注释结尾的
`-->`，注释把 <script> 连同 <body> 一起吞了，页面空掉，当时所有闸门一路绿灯。

用法：py -3.11 tests/break_webgate.py
每处破坏跑完立刻按内存里的原字节还原，还原后还会核对字节一致（绝不留坏文件）。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PY = sys.executable

# (说明, 文件, 旧串, 新串, 由哪个闸门负责抓)
CASES = [
    ("页面没挂 gate.js", "web/proofread.html",
     '<script src="js/gate.js"></script>', "", "tests/check_web_js.py"),
    ("gate.js 语法写坏", "web/js/gate.js",
     "function mk(tag, cls, text) {", "function mk(tag, cls, text) {(",
     "tests/check_web_js.py"),
    ("gate.js 用 innerHTML 拼文案", "web/js/gate.js",
     "if (text != null) n.textContent = text;", "if (text != null) n.innerHTML = text;",
     "tests/check_web_js.py"),
    ("旧 #guard 容器复活", "web/paper.html",
     '<main class="wrap">', '<main class="wrap">\n  <div id="guard"></div>',
     "tests/check_web_js.py"),
    ("注释没闭合吃掉 script 标签", "web/index.html",
     "协议让 Windows 去拉起服务。-->", "协议让 Windows 去拉起服务。",
     "tests/check_web_js.py"),
    ("样式改成绝对路径", "web/print.html",
     'href="css/app.css"', 'href="/css/app.css"', "tests/check_web_js.py"),
    # 流程顺序（用户明确指定的口径）：这四把尺各自守一条，缺一条就会漂回去
    ("步骤条顺序被改回旧版", "web/js/app.js",
     "{ key: 'proofread', label: '校对题目',    href: 'proofread.html' },\n"
     "    { key: 'answer',    label: '在线做题',    href: 'paper.html' },",
     "{ key: 'answer',    label: '在线做题',    href: 'paper.html' },\n"
     "    { key: 'proofread', label: '校对题目',    href: 'proofread.html' },",
     "tests/check_web_js.py"),
    ("页面又自己抄了一份步骤数组", "web/print.html",
     "const $=s=>document.querySelector(s);",
     "const items=[['index.html','上传','1'],['#','打印版','2']];\n"
     "const $=s=>document.querySelector(s);", "tests/check_web_js.py"),
    ("页面不声明自己在第几步", "web/paper.html",
     '<body data-step="answer">', "<body>", "tests/check_web_js.py"),
    ("首页四步文案顺序写错", "web/index.html",
     "<div><b><i>2</i>校对题目</b>", "<div><b><i>2</i>打印版</b>", "tests/check_web_js.py"),
    # ---- 小问（1）（2）（3）视图：判据搬进 js/subqs.js 后，这两把尺各守一段 ----
    ("做题页用了 PJSubs 却没挂 js/subqs.js", "web/paper.html",
     '<script src="js/subqs.js"></script>', "", "tests/check_web_js.py"),
    ("subqs.js 的挂载标签掉进没闭合的注释里", "web/paper.html",
     "页面不自己写一遍 -->", "页面不自己写一遍", "tests/check_web_js.py"),
    ("小问标签少给一个输入框（批改下标会错位）", "web/js/subqs.js",
     "    return out.slice(0, n);", "    return out;", "tests/test_subqs_js.py"),
    ("引导语那行不再单独印（小问前的正文消失）", "web/js/subqs.js",
     "    if (head) out.push(head);", "    if (false) out.push(head);",
     "tests/test_subqs_js.py"),
    ("只有一问也被加编号（普通题被当成小问拆）", "web/js/subqs.js",
     "    return s.length >= 2 ? s.length : 0;", "    return s.length;",
     "tests/test_subqs_js.py"),
    ("前端空位口径退回「只认 1–4 个空格」（和后端漂开）", "web/js/subqs.js",
     "/_{2,}|＿{2,}|[（(]\\s*[）)]/g",
     "/_{2,}|＿{2,}|[（(]\\s{0,4}[）)]/g",
     "tests/test_subqs_js.py"),
    ("前端空位口径退回「括号必须成对」（漏掉混配的（   )）", "web/js/subqs.js",
     "/_{2,}|＿{2,}|[（(]\\s*[）)]/g",
     "/_{2,}|＿{2,}|（\\s*）|\\(\\s*\\)/g",
     "tests/test_subqs_js.py"),
    ("符号插入不替换选区（选中×点÷变成 ×÷）", "web/js/subqs.js",
     "    var b = Math.max(a, Math.min(v.length, end == null ? a : end));",
     "    var b = a;",
     "tests/test_subqs_js.py"),
    ("符号插入的光标不夹回合法区间（越界点到看不见的地方）", "web/js/subqs.js",
     "    var a = Math.max(0, Math.min(v.length, start == null ? v.length : start));",
     "    var a = Math.max(0, start == null ? v.length : start);",
     "tests/test_subqs_js.py"),
    ("符号面板里塞进打印字体没有的 emoji（印出来是空白方块）", "web/js/subqs.js",
     "['★', '☆', '●', '○'", "['⭐', '☆', '●', '○'",
     "tests/test_subqs_js.py"),
    (".ps1 丢了 BOM", "scripts/install_startup.ps1", None, "STRIP_BOM",
     "tests/check_script_encoding.py"),    (".vbs 混进中文", "scripts/start_hidden.vbs",
     "PaperForge - windowless", "磐卷 PaperForge windowless",
     "tests/check_script_encoding.py"),
    # 真实事故：跨 shell 写 check.bat 时 `tests\break...` 里的 \b 被坐实成退格符 0x08，
    # 文件仍是"纯 ASCII"，只有这条控制字符检查能看见它。
    # 这里故意写 \x08 而不是 \b —— 后者在本文件里就会真的变成退格符，读代码的人会以为打错了。
    ("check.bat 混进退格符", "scripts/check.bat",
     "py -3.11 tests\\check_web_js.py", "py -3.11 tests\x08reak_webgate.py",
     "tests/check_script_encoding.py"),
]


def run_gate(gate: str) -> tuple[int, str]:
    r = subprocess.run([PY, os.path.join(ROOT, gate)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    missed = []
    for name, rel, old, new, gate in CASES:
        p = os.path.join(ROOT, rel)
        raw = open(p, "rb").read()
        if new == "STRIP_BOM":
            assert raw.startswith(b"\xef\xbb\xbf"), rel + " 本来就没 BOM，这一刀切不下去"
            mutated = raw[3:]
        else:
            enc = old.encode("utf-8")
            assert raw.count(enc) >= 1, "锚点找不到：%s / %r（脚本该跟着更新了）" % (rel, old)
            mutated = raw.replace(enc, new.encode("utf-8"), 1)
        assert mutated != raw, "破坏没生效：" + name

        open(p, "wb").write(mutated)
        try:
            rc, out = run_gate(gate)
        finally:
            open(p, "wb").write(raw)
            assert open(p, "rb").read() == raw, "还原后字节不一致：" + rel

        caught = rc != 0
        why = [l.strip() for l in out.splitlines() if "FAIL" in l or "✗" in l]
        print("  %-24s → %s  %s" % (name, "被抓" if caught else "★没抓到★",
                                    (why[0][:96] if why else out.strip()[:96])))
        if not caught:
            missed.append(name)

    print("\n%d/%d 处破坏被闸门抓到" % (len(CASES) - len(missed), len(CASES)))
    if missed:
        print("没抓到的：" + "、".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
