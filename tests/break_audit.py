"""审计尺的变异闸门：把「题型可疑」这条尺打坏，要求它的自检必须变红。

为什么单独一把：用户截图里的第 3 题（树叶选项是图片）被判成判断题，
老审计只看"选择题没选项"，对这种错题型完全瞎。新尺装在审计器里，
如果尺本身坏了，报告里的"题型可疑 0"就等于没说 —— 所以先把它打坏一次。

跑法：py -3.11 -B tests/break_audit.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from mutate_gate import Mutation, run                    # noqa: E402

AU = os.path.join(ROOT, "tests", "audit_papers.py")

M = [
    Mutation("关·不为 choice 才算可疑（真选择题也被报）", AU,
             '        if qt == "choice":\n            continue\n',
             "        if False:\n            continue\n",
             "题型可疑尺"),
    Mutation("关·只看题干、不看大题名（二、选一选 漏报）", AU,
             '        m = CHOICE_CUE.search(t) or CHOICE_CUE.search(sec)',
             "        m = CHOICE_CUE.search(t)",
             "题型可疑尺"),
    Mutation("关·整条尺不产出（填序号却判成 fill 也不报）", AU,
             '        if m:\n            out.append((i + 1, int(q.get("q_no") or i + 1), qt, m.group(0)))',
             '        if False:\n            out.append((i + 1, int(q.get("q_no") or i + 1), qt, m.group(0)))',
             "题型可疑尺"),
]

if __name__ == "__main__":
    sys.exit(run(M, AU, test_args=("--selftest",)))
