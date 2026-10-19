# -*- coding: utf-8 -*-
"""故意打坏「第 4 步三态 + 预览刷新」这条链，看 F18 会不会红。

为什么单独一个文件、且不进 check.bat：它要跑三遍完整验收（每遍起一次服务、
跑真实 OCR 与 PDF 读回），一次约 2–3 分钟；check.bat 里其余的变异闸门都是
秒级的单元测试。改到 papers.py / answer_writer.py 的导出与预览逻辑时手动跑它。

用法：py -3.11 tests/break_flowgate.py
每处破坏跑完立刻按原字节还原，还原后核对字节一致（绝不留坏文件）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PY = sys.executable
TARGET = os.path.join(ROOT, "app", "api", "papers.py")

# (说明, 旧串, 新串, 期望 F18 报出的关键词)
CASES = [
    ("revision 改成随机数：预览看着每次都变，其实内容没变",
     '    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]',
     '    import os as _o\n    return _o.urandom(6).hex()',
     "随机数假动作"),
    ("空白卷偷偷带上最近一次作答：三态其实没分开",
     '    mode = _render_mode(mode)\n    answers: dict = {}',
     '    mode = _render_mode(mode)\n    mode = "answered" if mode == "blank" else mode\n    answers: dict = {}',
     "空白卷的纸上出现了孩子的答案"),
    ("版式存了但渲染时不读：改了预览不可能变",
     '    opt = LayoutOptions.from_dict(paper.get("options") or {})',
     '    opt = LayoutOptions.from_dict({})',
     "revision 没变"),
]


def run_acceptance() -> tuple[int, str]:
    r = subprocess.run([PY, os.path.join(ROOT, "tests", "acceptance_v11.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, timeout=1800)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def f18_line(out: str) -> str:
    for l in out.splitlines():
        if "F18" in l:
            return l.strip()
    return "(输出里没找到 F18 那一行)"


def main() -> int:
    raw = open(TARGET, "rb").read()
    missed = []
    for name, old, new, want in CASES:
        enc = old.encode("utf-8")
        assert raw.count(enc) == 1, "锚点不是唯一一处：%s（%d）" % (name, raw.count(enc))
        open(TARGET, "wb").write(raw.replace(enc, new.encode("utf-8"), 1))
        try:
            rc, out = run_acceptance()
        finally:
            open(TARGET, "wb").write(raw)
            assert open(TARGET, "rb").read() == raw, "还原后字节不一致"
        line = f18_line(out)
        caught = rc != 0 and "F18" in line and "✗" in line
        named = want in line or want in out
        print("  %-42s → %s%s\n      %s" % (
            name, "F18 变红" if caught else "★F18 仍然绿★",
            "" if not caught or named else "（但报的不是预期那条）",
            line[:170]))
        if not (caught and named):
            missed.append(name)

    print("\n%d/%d 处破坏让 F18 变红" % (len(CASES) - len(missed), len(CASES)))
    if missed:
        print("没抓到：" + "、".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
