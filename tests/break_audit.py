"""审计尺的变异闸门：把每条审计尺分别打坏，要求自检必须变红。

为什么单独一把：用户截图里的第 3 题（树叶选项是图片）被判成判断题，
老审计只看"选择题没选项"，对这种错题型完全瞎。题干残渣尺同理 ——
如果尺本身坏了，报告里的"题型可疑 0 / 残渣 0"就等于没说，所以逐条打坏一次。

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
    # ── 题干残渣尺（图内标注被 OCR 拼进题干）──
    Mutation("关·不要求文字落在配图框内（框外题干也报）", AU,
             "            boxes.append((t, any(residue_covered(r, bb) for r in rects)))",
             "            boxes.append((t, True))",
             "题干残渣尺"),
    Mutation("关·不匹配题干（残渣留着也不报）", AU,
             "            if hit and hit > max(len(re.findall(p, legit)) for p in pats):",
             "            if False:",
             "题干残渣尺"),
    Mutation("过·按设计保留的起手句也报（误报）", AU,
             "            if (not content_seen",
             "            if (False",
             "题干残渣尺"),
    Mutation("过·题头抢走起手句豁免（真正的第一句被误报）", AU,
             "                    and any(re.search(p, text) for p in pats)):",
             "                    and True):",
             "题干残渣尺"),
    Mutation("过·不按出现次数算（句子里的同名正文被误报）", AU,
             "            if hit and hit > max(len(re.findall(p, legit)) for p in pats):",
             "            if hit:",
             "题干残渣尺"),
    # ── 含题干尺（裁框把还在题干里的整句框进去）──
    Mutation("过·不检查题干里还在不在（图内标签全被报）", AU,
             "            if not any(re.search(p, text) for p in box_text_patterns(t)):\n"
             "                continue",
             "            if False:\n                continue",
             "含题干尺"),
    Mutation("过·不看框（没被框住的整句也报）", AU,
             "            if not any(overlap(r, bb) >= 0.8 for r in rects):\n                continue",
             "            if False:\n                continue",
             "含题干尺"),
    Mutation("关·整条尺不产出（题干被框住也不报）", AU,
             '            out.append((qi + 1, t[:20], "题干首行" if bi == 0 else f"第{bi + 1}行"))',
             "            pass",
             "含题干尺"),
]

if __name__ == "__main__":
    sys.exit(run(M, AU, test_args=("--selftest",)))
