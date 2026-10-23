"""把图形符号分类器的每条判据改回"没有它"的样子，要求 tests/test_symbols.py 变红。

分类器的错误方向是【把 ★ 认成 □】——印出来就是一道题干被写错的题，
比"认不出"糟得多。所以每条阈值都要现场拆一次，看尺会不会响。
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

SYM = os.path.join(ROOT, "app", "extractor", "symbols.py")
PAPERS = os.path.join(ROOT, "app", "api", "papers.py")
TEST = os.path.join(ROOT, "tests", "test_symbols.py")

SHAPE = "十四种形状各画一遍必须认对"
UNKNOWN = "认不出的墨不许猜"
LINE = "scan_span 把 ★＋★＝20 还原成一行"
REFUSE = "四道反例：没等号 / 带中文 / 有认不出的块 / 扫描 logo 一律不重建"
EQ = "两根杠＝一个等号"
NAME = "scan_span 把弯月/花朵印成名字"
NEG = "真卷配图（蘑菇/青蛙）"
TITLE = "标题「打▲的」的实心三角能从墨迹补回"
TITLE_NEG = "标题补标记的三个反例"

M = [
    Mutation("过·汉字笔画不再挡（一个「国」字会被认成方框）", SYM,
             '    if f["runs_mid"] >= 3 and sol >= 0.90:\n        return None',
             "    if False:\n        return None",
             UNKNOWN),
    Mutation("反·括号开口方向判反", SYM,
             '        return "paren_open" if f["tip_off"] > 0 else "paren_close"',
             '        return "paren_close" if f["tip_off"] > 0 else "paren_open"',
             SHAPE),
    Mutation("钝·乘号不再看顶行段数（× 全被判成 ＋）", SYM,
             '        return "times" if f["runs_top"] >= 2 else "plus"',
             '        return "plus"',
             SHAPE),
    Mutation("钝·正方形/菱形改用填充率区分（空心方框被判成菱形）", SYM,
             '            return "square" if f["top_w"] >= 0.7 else "diamond"',
             '            return "square" if fill >= 0.7 else "diamond"',
             SHAPE),
    Mutation("钝·实心圆与圆环不分（○ 全被判成 ●）", SYM,
             '            return "circle" if fill >= 0.66 else "ring"',
             '            return "circle"',
             SHAPE),
    Mutation("关·五角星判据摘掉（星只能落到 〔图〕）", SYM,
             '        if (lobes in (5, 6) or v3 in (5, 6)) and sol <= 0.88 and cir <= 0.76:\n'
             '            return "star"',
             '        if False:\n            return "star"',
             SHAPE),
    Mutation("关·弯月判据摘掉（弯月只能落到 〔图〕）", SYM,
             '        if (sol <= 0.80 and fill <= 0.40 and cir <= 0.55 and lobes <= 3\n'
             '                and f["top_w"] <= 0.40 and f["prof_ratio"] <= 0.18\n'
             '                and f["duty"] >= 0.55):\n'
             '            return "moon"',
             '        if False:\n            return "moon"',
             SHAPE),
    Mutation("关·花朵判据摘掉（花朵只能落到 〔图〕）", SYM,
             '        if (sol >= 0.85 and cir >= 0.55 and fill >= 0.45\n'
             '                and 5 <= lobes <= 8 and f["top_w"] <= 0.60\n'
             '                and f["prof_ratio"] >= 0.55 and f["duty"] >= 0.50):\n'
             '            return "flower"',
             '        if False:\n            return "flower"',
             SHAPE),
    Mutation("关·名字没带出行（分类对、印出来还是〔图〕）", SYM,
             '    "moon": "〔弯月〕", "flower": "〔花朵〕",',
             '    "moon": "〔图〕", "flower": "〔图〕",',
             NAME),
    Mutation("过·花朵判据放宽到 2 瓣（青蛙/蘑菇被当花）", SYM,
             '        if (sol >= 0.85 and cir >= 0.55 and fill >= 0.45\n'
             '                and 5 <= lobes <= 8 and f["top_w"] <= 0.60\n'
             '                and f["prof_ratio"] >= 0.55 and f["duty"] >= 0.50):',
             '        if (sol >= 0.85 and cir >= 0.55 and fill >= 0.45\n'
             '                and 2 <= lobes <= 8 and f["top_w"] <= 0.70\n'
             '                and f["prof_ratio"] >= 0.40 and f["duty"] >= 0.50):',
             NEG),
    Mutation("过·弯月三门槛同时放宽（5pt 墨点被当弯月）", SYM,
             '        if (sol <= 0.80 and fill <= 0.40 and cir <= 0.55 and lobes <= 3\n'
             '                and f["top_w"] <= 0.40 and f["prof_ratio"] <= 0.18\n'
             '                and f["duty"] >= 0.55):',
             '        if (sol <= 0.80 and fill <= 0.45 and cir <= 0.55 and lobes <= 3\n'
             '                and f["top_w"] <= 0.60 and f["prof_ratio"] <= 0.18\n'
             '                and f["duty"] >= 0.10):',
             NEG),
    Mutation("过·行闸门不再要求等号（一排圆点也被拼成算式）", SYM,
             "        if len(shapes) < MIN_SHAPES_PER_ROW or not ops or not has_eq:",
             "        if len(shapes) < MIN_SHAPES_PER_ROW or not ops:",
             REFUSE),
    Mutation("过·行闸门不再拒绝带中文的行（把说明句拼成算式）", SYM,
             "        if unknown or (has_cjk and CJK_IN_ROW_KILLS):",
             "        if False:",
             REFUSE),
    Mutation("过·行闸门不再拒绝认不出的块（半拼一行算式）", SYM,
             "        if unknown or (has_cjk and CJK_IN_ROW_KILLS):",
             "        if has_cjk and CJK_IN_ROW_KILLS:",
             REFUSE),
    Mutation("钝·扫描 logo 那类无文本行不再被行闸门挡（形状数够就拼）", SYM,
             "MIN_SHAPES_PER_ROW = 2      ", "MIN_SHAPES_PER_ROW = 1      ",
             REFUSE),
    Mutation("关·两根杠不折叠成等号（＝ 印成 －－）", SYM,
             '                    "label": "equals", "ch": char_of("equals")})',
             '                    "label": "minus", "ch": char_of("minus")})',
             EQ),
    Mutation("关·符号识别整条链路不接（还原不出任何一行）", SYM,
             "    lines, n_shapes, n_unknown = [], 0, 0",
             "    return {\"lines\": [], \"n_shapes\": 0, \"n_unknown\": 0, \"rows\": []}\n"
             "    lines, n_shapes, n_unknown = [], 0, 0",
             LINE),
    # ── 本轮（P6 大题标题「打▲的」被 OCR 读成「打的」）新增判据 ──
    Mutation("关·缺口位置筛（缺口外的三角也补进标题）", SYM,
             "            if abs(xc - slot_c) > 1.6 * u:\n                continue",
             "            if False:\n                continue",
             TITLE_NEG),
    Mutation("反·实心三角判成空心（▲ 印成 △）", SYM,
             '        return "▲" if fill >= 0.40 else "△"',
             '        return "△" if fill >= 0.40 else "▲"',
             TITLE),
    # ── 本轮实测事故：api_parse 里再导入一次 SY，模块级别名被遮蔽，
    #    前半段的补标题抛 UnboundLocalError 又被 except 吞掉（单测全绿、真卷没补） ──
    Mutation("关·api_parse 局部再导入 SY（补标题静默失效）", PAPERS,
             "    qs = flatten_questions(res)",
             "    from ..extractor import symbols as SY  # noqa: F811\n"
             "    qs = flatten_questions(res)",
             "api_parse 不许在函数内再导入 SY"),
]

if __name__ == "__main__":
    sys.exit(run(M, TEST))
