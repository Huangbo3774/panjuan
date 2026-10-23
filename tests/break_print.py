"""打印链路（answer_writer + 读库视图 + 小问判据）的变异闸门。

为什么要单独一个闸门：test_print_formats.py 是【端到端】的尺 —— 它量的是
"PDF 里真的排成三行了吗"，而这条链上有三处任何一个断了都会让家长看到挤成一坨的题干：
  · rules.split_subqs 的判据（切不切得出来）
  · db.get_questions 读时挂视图（线接没接）
  · answer_writer 重排题干（排版落没落地）
break_extractor 只跑 test_extractor.py，量不到后两段，所以这里用
test_print_formats.py 当被照的尺，逐段各打坏一次。
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

RULES = os.path.join(ROOT, "app", "extractor", "rules.py")
DB = os.path.join(ROOT, "app", "storage", "db.py")
WRITER = os.path.join(ROOT, "app", "papers", "answer_writer.py")
TEST = os.path.join(ROOT, "tests", "test_print_formats.py")

EXPECT_LINE = "小问在打印版里各起一行"
EXPECT_VIEW = "小问视图接在读库链路上"
TEST_EXPORT = os.path.join(ROOT, "tests", "test_answer_export.py")
EXPECT_SAME_PAGE = "选择题整题同页"
EXPECT_WHOLE_FIG = "整题截图放大到页宽"
EXPECT_WHOLE_Q = "整题原图不许再印一遍"
EXPECT_FIG_FIRST = "配图紧跟题干"

# 导出分页 / 整题截图尺寸（被照的尺是 test_answer_export.py）
M_EXPORT = [
    Mutation("旧·题目不整题搬页（D 选项单独落在下一页）", WRITER,
             "        if est <= usable:\n            fl.need(est)",
             "        if False:\n            fl.need(est)",
             EXPECT_SAME_PAGE),
    Mutation("旧·整题截图按 1:1 印（半栏宽，字只有 5–6pt）", WRITER,
             "    if whole and w_pt:",
             "    if False and w_pt:",
             EXPECT_WHOLE_FIG),
    Mutation("旧·半页扫描件的普通配图不放大（P4 角图只有 53pt）", WRITER,
             "    pscale = _page_scale(im)",
             "    pscale = 1.0",
             EXPECT_WHOLE_FIG),
    Mutation("旧·整题原图又印一遍 OCR 文字（同题出现两次）", WRITER,
             '        whole_q = any(bool(im.get("whole_question")) for im in (q.get("images") or []))',
             "        whole_q = False",
             EXPECT_WHOLE_Q),
    Mutation("旧·整题原图的作答不印（孩子的答案在导出里看不见）", WRITER,
             '                fl.text("作答：" + body, fs, indent=indent + 6, gap_after=0)',
             "                pass",
             EXPECT_WHOLE_Q),
    Mutation("旧·整题没作答印两次「未作答」（批改版叠成两行）", WRITER,
             '                fl.text("作答：" + body, fs, indent=indent + 6, gap_after=0)\n'
             "            elif not graded:",
             '                fl.text("作答：" + body, fs, indent=indent + 6, gap_after=0)\n'
             "            elif graded:\n"
             '                fl.text("（未作答）", fs - 1, indent=indent + 8, gap_after=0)\n'
             "            elif not graded:",
             EXPECT_WHOLE_Q),
    Mutation("关·整题图下不给作答行（孩子没处下笔）", WRITER,
             "            elif not graded:",
             "            elif False:",
             EXPECT_WHOLE_Q),
    Mutation("关·原卷自带答框还补作答行（P5 Q24/Q25 多翻一页）", WRITER,
             '                if (not re.search(r"答\\s*[:：]|我的理由|解\\s*[:：]", src_lines)',
             "                if (True",
             EXPECT_WHOLE_Q),
    Mutation("旧·普通配图留到作答横线之后才画（孩子先看到空行，P2 Q8/P3 面积题）", WRITER,
             '            if q.get("images"):\n'
             "                _draw_figures(c, q, opt, fl, indent, fig_dir=fig_dir, stats=stats)\n"
             "                figures_done = True\n"
             '            body = " ".join(alist).strip()',
             '            body = " ".join(alist).strip()',
             EXPECT_FIG_FIRST),
]

M = [
    Mutation("关·打印版根本不看小问视图（三问仍挤一段）", WRITER,
             "        subs = q.get(\"subqs\") or []",
             "        subs = []",
             EXPECT_LINE),
    Mutation("关·小问各起一行（判据对、换行没落进题干）", WRITER,
             '            body = "\\n".join(f"（{s.get(\'no\')}）{s.get(\'text\')}" for s in subs)',
             '            body = " ".join(f"（{s.get(\'no\')}）{s.get(\'text\')}" for s in subs)',
             EXPECT_LINE),
    Mutation("关·引导语那一行不印（小问前正文整句消失）", WRITER,
             '            stem = f"{head}\\n{body}" if head else body',
             "            stem = body",
             EXPECT_LINE),
    Mutation("关·读库时不挂小问视图（API 拿不到 subqs）", DB,
             '            d["subqs"] = split_subqs(d.get("text") or "")',
             '            d["subqs"] = []',
             EXPECT_VIEW),
    Mutation("过·小问号不必成对括号（算式结果被当编号）", RULES,
             r'SUBQ_MARK_RE = re.compile(r"[（(]\s*(\d{1,2})\s*[）)]")',
             r'SUBQ_MARK_RE = re.compile(r"(?:[（(]\s*)?(\d{1,2})(?:\s*[）)])?")',
             EXPECT_VIEW),
    Mutation("关·读库时不重算空位数（老库的 0 永远自愈不了）", DB,
             '            d["blanks"] = len(BLANK_RE.findall(d.get("text") or ""))',
             '            d["blanks"] = int(d.get("blanks") or 0)',
             EXPECT_VIEW),
]

if __name__ == "__main__":
    rc1 = run(M, TEST)
    rc2 = run(M_EXPORT, TEST_EXPORT)
    sys.exit(1 if (rc1 or rc2) else 0)
