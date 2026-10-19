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
    sys.exit(run(M, TEST))
