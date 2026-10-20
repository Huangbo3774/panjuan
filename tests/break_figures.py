# -*- coding: utf-8 -*-
"""故意把配图裁剪的五条判据改回旧行为，要求 tests/test_figures.py 必须变红。

为什么需要它：test_figures.py 4/4 全绿只说明"代码满足了断言"，
不说明"断言抓得住东西"。本项目已经被"假绿的尺"骗过四次，
这次用户报的正是同一类问题（裁图裁错地方），所以每条新判据都要现场打坏一次。

用法：py -3.11 tests/break_figures.py
每处破坏跑完立刻按原字节还原，并核对还原后字节一致（绝不留坏文件）。
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
FIG = os.path.join(ROOT, "app", "extractor", "figures.py")
LNS = os.path.join(ROOT, "app", "extractor", "lines.py")
AWR = os.path.join(ROOT, "app", "papers", "answer_writer.py")

# (说明, 文件, 旧串, 新串, 期望哪条测试变红)
CASES = [
    ("探测带退回整页宽（旧 bug 本体：这道栏边界墙拆掉）", FIG,
     '    return (float(s.get("x0") or 0), float(s["y0"]),\n'
     '            float(s.get("x1") or src.width_pt), float(s.get("y1") or src.height_pt))',
     '    return (0.0, float(s["y0"]), src.width_pt,\n'
     '            float(s.get("y1") or src.height_pt))',
     "横版两栏：裁图不许跨栏"),
    ("区间下界退回【全局】下一题（不看栏）", LNS,
     '            if o is rec or o["page"] != page or o["col"] != col:',
     '            if o is rec or o["page"] != page:',
     "横版两栏：裁图不许跨栏"),
    ("连通域退回单个大外接盒", FIG,
     "    comps = _merge_boxes(_components(band, k, np, cv2, wall), MERGE_GAP_PT * k)",
     "    import numpy as _np\n"
     "    _ys, _xs = _np.nonzero(band)\n"
     "    comps = [] if len(_xs) == 0 else [[int(_xs.min()), int(_ys.min()), "
     "int(_xs.max()) + 1, int(_ys.max()) + 1]]",
     "一题两张图：必须出两张，不许并成巨框"),
    ("不认大题题头（墙拆了）", LNS,
     "    for sec in sections or []:",
     "    for sec in []:",
     "大题题头是硬墙：共享图挂本大题第一小题"),
    ("共享图不向上够到题头（没人接那段区间）", LNS,
     '        if up:\n            y0 = up["y"]',
     '        if up and False:\n            y0 = up["y"]',
     "大题题头是硬墙：共享图挂本大题第一小题"),
    # ── 打印链路：库里存 name、渲染只认 path 的话，图会静默消失（用户报的第三条）──
    # ── 打印链路：库里存的是 name，渲染只认 path 的话图会静默消失（用户报的第三条）──
    ("配图渲染退回只读 path（打印没图）", AWR,
     '    p = im.get("path") or ""' + "\n" +
     '    if not p and fig_dir and im.get("name"):' + "\n" +
     '        p = os.path.join(fig_dir, os.path.basename(str(im["name"])))',
     '    p = im.get("path") or ""',
     "配图必须真的印进 PDF（含缺文件要报数）"),
    ("图丢了却不报数（静默少印，用户无从发现）", AWR,
     '        if not p:' + "\n" +
     '            if stats is not None:' + "\n" +
     '                stats["missing"] += 1' + "\n" +
     '            continue',
     '        if not p:' + "\n" + '            continue',
     "配图必须真的印进 PDF（含缺文件要报数）"),
    # ── 本轮（用户："你把应该一页的弄成多页了"）新增的判据，逐条打坏 ──
    ("补洞合并关掉（一张图被文字行切成两块）", FIG,
     '    near = (m["gap_pt"] <= BRIDGE_MAX_GAP_PT * (DPI_PROBE / 72.0)\n'
     '            or m["gap_ratio"] <= BRIDGE_MAX_GAP_RATIO)',
     "    near = False",
     "一张图不许被自己那行标签切成上下两块"),
    ("文字残影规则关掉（一题多出几张只有字的废图）", FIG,
     "    bx0, by0, bx1, by1 = [int(v) for v in box]",
     "    return False\n    bx0, by0, bx1, by1 = [int(v) for v in box]",
     "文字残影：一行字不许当配图，数轴例外"),
    ("数轴保护（长横线判据）关掉（真图被当噪声砍）", FIG,
     "    return _max_h_run(band[by0:by1, bx0:bx1], k, np) < TEXT_MIN_RUN_PT",
     "    return True",
     "文字残影：一行字不许当配图，数轴例外"),
    # ⚠️ 多行锚点里的换行写成「反斜杠+n」两个字符：直接写转义会被某些 shell 的
    #    heredoc 变成真换行，整个文件语法就废了（这次踩到了）。
    ("装订栏判据整条关掉（页边窄长条当配图）", FIG,
     "    w = rect[2] - rect[0]\n    h = rect[3] - rect[1]\n" + "    if w <= MARGIN_FLUSH_W_PT and (rect[0] <= 2.0",
     "    return False\n    w = rect[2] - rect[0]\n    h = rect[3] - rect[1]\n" + "    if w <= MARGIN_FLUSH_W_PT and (rect[0] <= 2.0",
     "页边装订栏不许当配图"),
    ("齐页边那条窄框判据关掉（42×34 的装订线残块当配图）", FIG,
     "    if w <= MARGIN_FLUSH_W_PT and (rect[0] <= 2.0 or rect[2] >= page_w - 2.0):",
     "    if False:",
     "页边装订栏不许当配图"),
    ("门槛不按栏宽缩放（小版面的 50×20 图被「太小」砍没）", FIG,
     "    return max(0.5, min(1.0, col_w / GATE_REF_COL_PT))",
     "    return 1.0",
     "小版面门槛按栏宽缩放（含只放宽不收紧）"),
    ("缩放没有上限（宽栏也一律放宽，碎墨混进配图）", FIG,
     "    return max(0.5, min(1.0, col_w / GATE_REF_COL_PT))",
     "    return 0.5",
     "小版面门槛按栏宽缩放（含只放宽不收紧）"),
    ("放宽档不受控（有严格合格大图时还往里塞小碎墨）", FIG,
     "        out += hard if hard else g",
     "        out += g",
     "小版面门槛按栏宽缩放（含只放宽不收紧）"),
    ("题干和图注并成一行时的碎片吸收关掉（图注被挖没→题做不了）", FIG,
     "            frags = _row_fragments(raw, t, k, np)",
     "            frags = []",
     "题干和图注并成一行：只吸图注那片"),
    ("碎片长度关关掉（半句正文被吸进图里）", FIG,
     "                    if (u[2] - u[0]) > FRAG_MAX_W_PT * k:",
     "                    if False:",
     "题干和图注并成一行：只吸图注那片"),
    ("缝合不看两半宽窄（上下两张图缝成一张，下面那题没图）", FIG,
     "                    if narrow / wide < STITCH_MIN_W_RATIO:",
     "                    if False:",
     "题界穿过一张图：上下两半要缝回一张（含反例）"),
    ("圈小标点不看内容（换行正文被一路串进裁图）", FIG,
     "            if len(txt) > 2 and not SHORT_MARK_TEXT_RE.match(txt):",
     "            if False:",
     "圈小标点不许把换行正文串进图里"),
    # ── 页脚/页码那行＝墙（连通域、近邻合并、补洞、吸收标签行都不许跨它）──
    ("页脚那行不再当墙（连通域跨过页脚接到 logo 上）", FIG,
     "    if wall is not None:\n        dil[wall] = 0",
     "    if False:\n        dil[wall] = 0",
     "页脚与扫描 app logo 是墙，不许缝进题图"),
    ("页脚那行还算成「我们自己挖的洞」（补洞会把它缝回来）", FIG,
     "        if furniture:\n            wall[ty0:ty1, tx0:tx1] = True\n        else:\n            hole[ty0:ty1, tx0:tx1] = True",
     "        hole[ty0:ty1, tx0:tx1] = True",
     "页脚与扫描 app logo 是墙，不许缝进题图"),
    ("页脚判据整条关掉（页脚/logo 那几行又当成图注和洞）", FIG,
     '        furniture = is_furniture_text(str(tb.get("text") or ""))',
     "        furniture = False",
     "页脚与扫描 app logo 是墙，不许缝进题图"),
    ("吸收标签行时不看页脚这堵墙（页脚被当图注吸进图）", FIG,
     "            if wall_flags is not None and idx < len(wall_flags) and wall_flags[idx]:",
     "            if False:",
     "页脚与扫描 app logo 是墙，不许缝进题图"),
    ("碎片长度下限关掉（一个汉字也算图注）", FIG,
     "                    if (u[2] - u[0]) < FRAG_MIN_W_PT * k:",
     "                    if False:",
     "题干和图注并成一行：只吸图注那片"),
    ("缝合后仍无脑挂靠前那道题（图落在谁区间多就不管了）", FIG,
     "                    if _band_share(u, g[j].get(\"band\") or b) > _band_share(u, own_band):",
     "                    if False:",
     "题界穿过一张图：上下两半要缝回一张（含反例）"),
    ("数页数那一趟不带 fig_dir（页脚「共 N 页」少算一页）", AWR,
     "               graded, answers, key, grade_result, class_name, student_name, total=None,\n               fig_dir=figures_dir)",
     "               graded, answers, key, grade_result, class_name, student_name, total=None)",
     "页脚「共 N 页」必须等于真实页数（配图占版面）"),
    ('关·裁框上沿收到题干行下面（图里再抄一遍题目）', FIG,
     '        if not hits:\n            break\n        bottom = max(r[3] for r in hits)',
     '        if True:\n            break\n        bottom = max(r[3] for r in hits)',
     '裁框上沿不许吞掉本题起手句（含三个反例）'),
    ('关·只处理列表第一行（题干第二行整行进图）', FIG,
     '        for i, tb in enumerate(text_boxes):\n            if i in skip:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[1] > cut[1] + STEM_TOP_TOL_PT:',
     '        for i, tb in enumerate(text_boxes[:1]):\n            if i in skip:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[1] > cut[1] + STEM_TOP_TOL_PT:',
     '裁框上沿不许吞掉题干第二行（含三个反例）'),
    ('过·不看盖住多少就照收（没盖住题干的图被白削一刀）', FIG,
     '            if row[1] > cut[1] + STEM_TOP_TOL_PT:\n                continue                              # 行框顶在图里面：是图自己的标注\n            if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:\n                continue                              # 从图中间起句：图自己的标注\n            if _covers(cut, row) < STEM_IN_FIG_COVER:',
     '            if row[1] > cut[1] + STEM_TOP_TOL_PT:\n                continue                              # 行框顶在图里面：是图自己的标注\n            if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:\n                continue                              # 从图中间起句：图自己的标注\n            if False:',
     '裁框上沿不许吞掉本题起手句（含三个反例）'),
    ('过·被当图注吸回来的那行也照裁（图会缺气泡）', FIG,
     '            if i in skip:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[1] > cut[1] + STEM_TOP_TOL_PT:',
     '            if False:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[1] > cut[1] + STEM_TOP_TOL_PT:',
     '裁框上沿不许吞掉本题起手句（含三个反例）'),
    ('过·收完上沿不管图还剩多高（题直接没图）', FIG,
     '        cut = (cut[0], new_top, cut[2], cut[3])\n        if cut[3] - cut[1] < 8 or cut[2] - cut[0] < 8:',
     '        cut = (cut[0], new_top, cut[2], cut[3])\n        if False:',
     '裁框上沿不许吞掉本题起手句（含三个反例）'),
    # ---- 下沿：图在上、题干紧贴着图（第三单元练习题 第 30 题）----
    ('关·下沿不裁（图里再抄半句题干）', FIG,
     '        if not hits:\n            break\n        top = min(r[1] for r in hits)',
     '        if True:\n            break\n        top = min(r[1] for r in hits)',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('关·下沿只处理列表第一行（末行题干整行进图）', FIG,
     '        for i, tb in enumerate(text_boxes):\n            if i in skip:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[3] < cut[3] - STEM_BOTTOM_TOL_PT:',
     '        for i, tb in enumerate(text_boxes[:1]):\n            if i in skip:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[3] < cut[3] - STEM_BOTTOM_TOL_PT:',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('过·下沿不看盖住多少（只蹭到一段也照削）', FIG,
     '            if not re.search(r"[。？?]|[（(]\\s*[）)]", t):\n                continue                              # 成句/带空位，不是"图1"这种题注\n            if _covers(cut, row) < STEM_IN_FIG_COVER:',
     '            if not re.search(r"[。？?]|[（(]\\s*[）)]", t):\n                continue                              # 成句/带空位，不是"图1"这种题注\n            if False:',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('过·下沿把吸回来的图注也裁（图缺最后一口气泡）', FIG,
     '            if i in skip:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[3] < cut[3] - STEM_BOTTOM_TOL_PT:',
     '            if False:\n                continue\n            row = (float(tb["x"]), float(tb["y"]),\n                   float(tb["x"]) + float(tb.get("w") or 0),\n                   float(tb["y"]) + float(tb.get("h") or 0))\n            if row[3] < cut[3] - STEM_BOTTOM_TOL_PT:',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('过·下沿不看左沿（图中间的标注句被削掉）', FIG,
     '            if row[3] < cut[3] - STEM_BOTTOM_TOL_PT:\n                continue                              # 行底不在下沿：图内的字\n            if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:\n                continue                              # 从图中间起句：图自己的标注',
     '            if row[3] < cut[3] - STEM_BOTTOM_TOL_PT:\n                continue                              # 行底不在下沿：图内的字\n            if False:\n                continue',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('过·下沿不看句号/空位（图注当题干削掉）', FIG,
     '            if not re.search(r"[。？?]|[（(]\\s*[）)]", t):',
     '            if False:',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('过·下沿不看字数（图里的"北"也当题干）', FIG,
     '            if len(re.sub(r"\\s+", "", t)) < 8:',
     '            if False:',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('过·下沿容差放到 1000（图内部的行也收）', FIG,
     'STEM_BOTTOM_TOL_PT = 12.0', 'STEM_BOTTOM_TOL_PT = 1000.0',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('过·收完下沿不管图还剩多高（题直接没图）', FIG,
     '        cut = (cut[0], cut[1], cut[2], new_bottom)\n        if cut[3] - cut[1] < 8 or cut[2] - cut[0] < 8:',
     '        cut = (cut[0], cut[1], cut[2], new_bottom)\n        if False:',
     '裁框下沿不许吞掉本题末行题干（含九个反例）'),
    ('关·下沿裁切没接进 find_figures（函数对、线没接）', FIG,
     '            cut = _clip_stem_row_bottom(rect, s.get("text_boxes") or [], ate_rows)\n            if cut != rect:',
     '            cut = rect\n            if cut != rect:',
     '下沿裁题干接线检查（真实裁图链路）'),
    # ---- 第十轮（用户截图：88×125 左栏残片 / 真图蹭到半行题干字）----
    ('过·贴边窄条上限放回 60（88×125 残片又当配图）', FIG,
     'MARGIN_FLUSH_W_PT = 100.0', 'MARGIN_FLUSH_W_PT = 60.0',
     '贴页边的侧栏复合块不许当配图（88×125）'),
    ('过·贴边判据不看宽度（贴边的真图也被砍）', FIG,
     '    if w <= MARGIN_FLUSH_W_PT and (rect[0] <= 2.0 or rect[2] >= page_w - 2.0):',
     '    if (rect[0] <= 2.0 or rect[2] >= page_w - 2.0):',
     '贴页边的侧栏复合块不许当配图（88×125）'),
    ('过·图正上方的正文碎片也当图注吸（整行题干又进图）', FIG,
     '                    if side not in ("left", "right"):\n                        continue',
     '                    if False:\n                        continue',
     '题干和图注并成一行：只吸图注那片'),
    ('过·图内标注行也照裁（非第一行不看左沿）', FIG,
     '            if row[1] > cut[1] + STEM_TOP_TOL_PT:\n                continue                              # 行框顶在图里面：是图自己的标注\n            if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:\n                continue                              # 从图中间起句：图自己的标注',
     '            if row[1] > cut[1] + STEM_TOP_TOL_PT:\n                continue                              # 行框顶在图里面：是图自己的标注\n            if False:\n                continue',
     '裁框上沿不许吞掉图内标注（非第一行须贴左沿）'),
    ('过·左沿门槛放到 1000（蘑菇/数轴/地图的上部全切）', FIG,
     'STEM_LEFT_TOL_PT = 24.0', 'STEM_LEFT_TOL_PT = 1000.0',
     '裁框上沿不许吞掉图内标注（非第一行须贴左沿）'),
    ('过·第一行也套左沿门槛（时间/评价栏留在图里）', FIG,
     '            if row[1] > cut[1] + STEM_TOP_TOL_PT:\n                continue                              # 行框顶在图里面：是图自己的标注\n            if i != first_i and row[0] > cut[0] + STEM_LEFT_TOL_PT:',
     '            if row[1] > cut[1] + STEM_TOP_TOL_PT:\n                continue                              # 行框顶在图里面：是图自己的标注\n            if row[0] > cut[0] + STEM_LEFT_TOL_PT:',
     '裁框上沿不许吞掉图内标注（非第一行须贴左沿）'),
    ('过·横向缝合高度比不管（答题框行并进货架图）', FIG,
     'SIDE_STITCH_MAX_H_RATIO = 1.5', 'SIDE_STITCH_MAX_H_RATIO = 1000.0',
     '同一行被文字行切断的图要并回一张'),
    ('过·罩住的小框也照留（答题框半截图又出一张）', FIG,
     '                if iw * ih >= area * CONTAIN_COVER_MIN:\n                    swallowed = True',
     '                if False:\n                    swallowed = True',
     '同一张图被裁两遍：罩住的小框要丢掉'),
    ('过·面积比门槛关掉（两张几乎同大的真图互吃）', FIG,
     '                if area <= 0 or karea < area * CONTAIN_AREA_RATIO:',
     '                if False:',
     '同一张图被裁两遍：罩住的小框要丢掉'),
    ('过·去重不分题（邻题落进大图范围的真图被吃）', FIG,
     '    for c in cands:\n        by.setdefault((int(c["page"]), int(c["q_index"])), []).append(c)\n    out: list[dict[str, Any]] = []\n    for _key, g in sorted(by.items()):\n        keep: list[dict[str, Any]] = []',
     '    for c in cands:\n        by.setdefault((int(c["page"]),), []).append(c)\n    out: list[dict[str, Any]] = []\n    for _key, g in sorted(by.items()):\n        keep: list[dict[str, Any]] = []',
     '同一张图被裁两遍：罩住的小框要丢掉'),
    ("跨页重复判据关掉（每页的 logo/二维码都当配图）", FIG,
     "    w = rect[2] - rect[0]\n    h = rect[3] - rect[1]\n    touches_edge = (",
     "    return False\n    w = rect[2] - rect[0]\n    h = rect[3] - rect[1]\n    touches_edge = (",
     "每页都印的页脚 logo 不许当配图"),
    ("一题限量退回按 y 截断（大图被小图挤掉）", FIG,
     '        big = sorted(g, key=lambda x: -((x["rect"][2] - x["rect"][0]) * (x["rect"][3] - x["rect"][1])))',
     '        big = sorted(g, key=lambda x: (x["rect"][1], x["rect"][0]))',
     "一题限量必须挑大的，不许按 y 截断"),
    ("整条补标签行规则关掉（裁出的图缺最后一行）", FIG,
     "    b = list(box)\n    slack = GROW_TOUCH_PT * k",
     "    return list(box)\n    b = list(box)\n    slack = GROW_TOUCH_PT * k",
     "图顶那行标签不许缺（被挖掉的行要吸回来）"),
    ("区间第一行保护关掉（题干被吸进图里）", FIG,
     "            if t[1] < GROW_MIN_BELOW_TOP_LINES * line_h:",
     "            if False:",
     "图顶那行标签不许缺（被挖掉的行要吸回来）"),
    # ── 第八轮（审计器：淡蓝图裁不出 / 括号被切 / 题界劈开一张图）──
    ("旧·固定墨门限 160（淡蓝框线的图全裁不到）", FIG,
     "        t = float(np.percentile(gray, INK_FRAC_MAX * 100.0))",
     "        t = float(INK_THR_FIXED)",
     "淡蓝框线的图也要裁得出来（自适应墨门限）"),
    ("过·墨门限不看上限（拍照页整页当墨）", FIG,
     "        return int(min(INK_THR_MAX, max(INK_THR_MIN, t)))",
     "        return int(max(INK_THR_MIN, t))",
     "灰底页不许整页当一张图"),
    ("关·跨题缝合（题界把一张图劈成上下两半）", FIG,
     "    cands = _stitch_across_questions(cands)",
     "    pass",
     "跨题缝合：接线检查"),
    ("过·缝合不看接缝上有没有墨（两张图缝成一张）", FIG,
     "                    if not sliver and not _seam_has_ink(a[\"src\"], tuple(r), tuple(b),",
     "                    if False and not _seam_has_ink(a[\"src\"], tuple(r), tuple(b),",
     "题界穿过一张图：上下两半要缝回一张（含反例）"),
    ("关·小标点框圈进来（算式少半个括号）", FIG,
     "            rect = _extend_to_short_marks(rect, s.get(\"text_boxes\") or [])",
     "            pass",
     "括号圈进裁图：接线检查"),
    # ---- 同行小块并回图框（治"算式被从中间截断"）：四条约束各拆一条 ----
    ("关·同行小块并回来（间隙阈值归零）", FIG,
     "ROW_PEER_MAX_GAP_PT = 40.0", "ROW_PEER_MAX_GAP_PT = 0.0",
     "同行被砍的小括号要并回图框"),
    ("过·同行判定形同虚设（重叠阈值 0.05，上下行都并）", FIG,
     "ROW_PEER_MIN_OVERLAP = 0.6", "ROW_PEER_MIN_OVERLAP = 0.05",
     "同行被砍的小括号要并回图框"),
    ("关·并回来时不夹回栏区间（越栏截邻题的图）", FIG,
     "            n = (max(n[0], box[0] - 3), max(n[1], box[1] - 3),\n"
     "                 min(n[2], box[2] + 3), min(n[3], box[3] + 3))",
     "            n = (n[0], box[1] - 3, n[2], box[3] + 3)",
     "同行被砍的小括号要并回图框"),
    ("过·并回来时连上下沿一起动（规则 L 白做）", FIG,
     "            n = (min(r[0], p[0]), r[1], max(r[2], p[2]), r[3])",
     "            n = (min(r[0], p[0]), min(r[1], p[1]), max(r[2], p[2]), max(r[3], p[3]))",
     "同行被砍的小括号要并回图框"),
    # ---- 横向缝合（同一行被文字行挖断的一张图并回一张）----
    ("关·横向缝合整条不接（判据对、线没接）", FIG,
     "    ok = _stitch_side_by_side(ok, report)",
     "    pass",
     "横向缝合真的接在裁图链路上"),
    ("过·横向缝合并不管竖直重叠（上下两张并成巨框）", FIG,
     "    if ov < SIDE_STITCH_MIN_Y_SHARE * tall:",
     "    if ov < 0.0 * tall:",
     "同一行被文字行切断的图要并回一张"),
    ("过·横向缝合不看水平间隙（两个并排钟面并成一张）", FIG,
     "    return max(r1[0] - r2[2], r2[0] - r1[2]) <= SIDE_STITCH_MAX_GAP_PT",
     "    return True",
     "同一行被文字行切断的图要并回一张"),
    ("过·横向缝合跨题并图（邻题的图被吞掉）", FIG,
     '    for c in cands:\n        by.setdefault((int(c["page"]), int(c["q_index"])), []).append(c)\n    out: list[dict[str, Any]] = []\n    for _key, g in sorted(by.items()):\n        g = list(g)',
     '    for c in cands:\n        by.setdefault((int(c["page"]), 0), []).append(c)\n    out: list[dict[str, Any]] = []\n    for _key, g in sorted(by.items()):\n        g = list(g)',
     "同一行被文字行切断的图要并回一张"),
    # ---- 第九轮（用户截图：栏目横幅 / 答题框行被当成配图）----
    ("关·家具行占比判据整条不接（栏目横幅当配图）", FIG,
     '            if _wall_ink_share(rect, sgn.get("raw"), sgn.get("wall"),\n'
     '                               k, cx0, y0) >= WALL_INK_SHARE_MAX:',
     "            if False:",
     "家具行判据接线检查（含丢弃原因）"),
    ("过·家具行阈值放到 101%（横幅永远砍不掉）", FIG,
     "WALL_INK_SHARE_MAX = 0.60", "WALL_INK_SHARE_MAX = 1.01",
     "栏目横幅接线（真实文字层）"),
    ("关·答题框判据整条不接（□×□＝□ 当配图）", FIG,
     '            if _is_answer_box_block(rect, sgn.get("raw"), k, cx0, y0, np):',
     "            if False:",
     "栏目横幅与答题框行不许当配图"),
    ("过·答题框占比门槛降到 0（单个方框也砍）", FIG,
     "ANSWER_BOX_MIN_SHARE = 0.40", "ANSWER_BOX_MIN_SHARE = 0.0",
     "家具行占比/答题框判据的反例（真图不许砍）"),
    ("过·只数到一个方框也当答题框", FIG,
     "ANSWER_BOX_MIN_SQUARES = 2", "ANSWER_BOX_MIN_SQUARES = 1",
     "家具行占比/答题框判据的反例（真图不许砍）"),
    ("过·答题框高度上限取消（整张图带方框也被砍）", FIG,
     "ANSWER_BOX_MAX_H_PT = 90.0", "ANSWER_BOX_MAX_H_PT = 100000.0",
     "家具行占比/答题框判据的反例（真图不许砍）"),
    ("过·答题框不看「框里有大块别的墨」（真图被砍）", FIG,
     "        if max(w_pt, h_pt) >= ANSWER_BOX_MAX_OTHER_PT:",
     "        if False:",
     "家具行占比/答题框判据的反例（真图不许砍）"),
    ("过·答题框不看别的形状（花/星被砍）", FIG,
     '        if lab in SY.SHAPE_LABELS and lab != "square":',
     "        if False:",
     "家具行占比/答题框判据的反例（真图不许砍）"),
    # ── 本轮（用户："读作:( ) 空白块、□×□=□ 答题框块"）新增的判据 ──
    ("关·空白作答行判据整条不接（读作:( ) 当配图）", FIG,
     "    if total / float(sub.size) > BLANK_ROW_MAX_DENSITY:\n"
     "        return False",
     "    if True:\n        return False",
     "空白作答行与连成一块的答题框（含反例）"),
    ("关·连成一块的方框不按内腔数（□×□ 当减号放过）", FIG,
     "        if merged >= MERGED_SQUARE_MIN_HOLES:",
     "        if False:",
     "空白作答行与连成一块的答题框（含反例）"),
    ("过·内腔不分方圆（线路图圆站点被当方框砍）", FIG,
     '        if SY.classify(SY.features(hole, np)) != "square":',
     "        if False:",
     "淡蓝框线的图也要裁得出来（自适应墨门限）"),
    ("过·括号配对门槛降到 0（没有右括号也算作答行）", FIG,
     "    return min(n_open, n_close) >= BLANK_ROW_MIN_PAREN_PAIRS",
     "    return min(n_open, n_close) >= 0",
     "空白作答行与连成一块的答题框（含反例）"),
    # ── 题干残渣清理（图内标注被 OCR 拼进题干 → 同一句话印两遍）──
    ("关·图内重复文字整条不清理（题干印两遍）", FIG,
     '    by_q = {int(s.get("q_index", -1)): s for s in spans}',
     "    return 0\n" + '    by_q = {int(s.get("q_index", -1)): s for s in spans}',
     "图内重复文字要从题干里删掉（含反例）"),
    ("过·压住一半也算图内文字（题干被削掉半句）", FIG,
     "RESIDUE_COVER_MIN = 0.90", "RESIDUE_COVER_MIN = 0.0",
     "图内重复文字要从题干里删掉（含反例）"),
    ("过·起手句也照删（整题变成空题干）", FIG,
     "            if not content_seen and len(re.sub(r\"\\s+\", \"\", t)) >= RESIDUE_KEEP_FIRST_CHARS:",
     "            if False:",
     "图内重复文字要从题干里删掉（含反例）"),
    ("过·不看行序只删第一处（句子里的同名标签被删、图注留下）", FIG,
     "                m = re.compile(p).search(text, cursor)",
     "                m = re.compile(p).search(text, 0)",
     "图内重复文字要从题干里删掉（含反例）"),
    ("过·不剥行框里的题号（起手句认不出，后面的正文被当图注删掉）", FIG,
     "    bare = re.sub(r\"^\\s*\\d+\\s*[、.．]\\s*\", \"\", t).strip()",
     "    bare = t.strip()",
     "图内重复文字要从题干里删掉（含反例）"),
    ("关·裁框削掉一条边就不算图内文字（地图顶行留在题干）", FIG,
     "RESIDUE_EDGE_MIN = 0.70", "RESIDUE_EDGE_MIN = 1.01",
     "图内重复文字要从题干里删掉（含反例）"),
    ("过·削边放宽到不封顶（图上方 8pt 外的题干行也被删）", FIG,
     "RESIDUE_EDGE_SLACK_PT = 6.0", "RESIDUE_EDGE_SLACK_PT = 100.0",
     "图内重复文字要从题干里删掉（含反例）"),
    # ── 太阳/月亮紧贴题顶：只向上吃小图标（"太阳被裁在题干上面"）──
    ("关·向上吃小图标整条不接（太阳仍被裁在框外）", FIG,
     "            if rect[1] <= lby0 + 1.0:",
     "            if False:",
     "太阳上沿接线检查（真实文字层）"),
    ("过·不限离图距离（离图 17pt 的墨也被吃）", FIG,
     "TOP_GROW_GAP_PT = 5.0", "TOP_GROW_GAP_PT = 500.0",
     "题顶紧贴的小太阳要随图裁进来（含九个反例）"),
    ("过·不限图标尺寸（大块邻图被吃）", FIG,
     "            if (cx1 - cx0) > TOP_GROW_MAX_W_PT or (cy1 - cy0) > TOP_GROW_MAX_H_PT:",
     "            if False:",
     "题顶紧贴的小太阳要随图裁进来（含九个反例）"),
    ("过·不避 OCR 文字框（把别人的字吃进图）", FIG,
     "            if any(_covers(box, t) >= 0.20 for t in tbs):",
     "            if False:",
     "题顶紧贴的小太阳要随图裁进来（含九个反例）"),
    ("过·不要求贴题顶（图中间也向上长）", FIG,
     "    if rect[1] > float(span_y0) + 1.0:",
     "    if False:",
     "题顶紧贴的小太阳要随图裁进来（含九个反例）"),
    ("过·不限总长（一轮拉 98pt 把上一题吃穿）", FIG,
     "TOP_GROW_TOTAL_PT = 30.0", "TOP_GROW_TOTAL_PT = 500.0",
     "题顶紧贴的小太阳要随图裁进来（含九个反例）"),
    ("过·不看整团墨的大小（共享地图被一路拉上来）", FIG,
     "        if (ux1 - ux0) > TOP_GROW_CLUSTER_W_PT or (uy1 - uy0) > TOP_GROW_CLUSTER_H_PT:",
     "        if False:",
     "题顶紧贴的小太阳要随图裁进来（含九个反例）"),
    ("过·不夹上一题底边（跨题也长）", FIG,
     "        if new_top < limit - 0.001:",
     "        if False:",
     "题顶紧贴的小太阳要随图裁进来（含九个反例）"),
    # ── 虚线作答区（"读作:( )"空白块）与跨题接缝的贯穿笔画 ──
    ("关·虚线作答区整条不接（读作:( ) 仍当配图）", FIG,
     "    band, wall = _strip_blank_answer_areas(band, wall, k, np, cv2)",
     "    pass",
     "虚线作答区剔除接线检查（真实裁图链路）"),
    ("过·框里有真图也剔（内容密度门槛失效）", FIG,
     "BLANK_AREA_MAX_DENSITY = 0.06", "BLANK_AREA_MAX_DENSITY = 1.0",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("过·框里长横线也剔", FIG,
     "BLANK_AREA_MAX_RUN_PT = 20.0", "BLANK_AREA_MAX_RUN_PT = 999.0",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("过·小框也剔（尺寸门槛失效）", FIG,
     "BLANK_AREA_MIN_W_PT = 100.0\nBLANK_AREA_MIN_H_PT = 50.0",
     "BLANK_AREA_MIN_W_PT = 0.0\nBLANK_AREA_MIN_H_PT = 0.0",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("过·点状纹理也剔（贴边占比门槛失效）", FIG,
     "        if on_edge / float(len(dashes)) < 0.80:",
     "        if False:",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("过·缺一条竖边也剔（四边门槛失效）", FIG,
     "        if min(sides) < 2:",
     "        if False:",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("过·按连通域 bbox 认框（圆点算进框高，框反而不剔）", FIG,
     "        dx0 = min(s[0] for s in small)\n"
     "        dy0 = min(s[1] for s in small)\n"
     "        dx1 = max(s[0] + s[2] for s in small)\n"
     "        dy1 = max(s[1] + s[3] for s in small)",
     "        dx0, dy0, dx1, dy1 = 0, 0, w, h",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("过·框内小点全剔（只该剔贴边短划）", FIG,
     "        for sx, sy, sw, sh, near in dashes:\n"
     "            if not near:\n                continue",
     "        for sx, sy, sw, sh, near in dashes:\n"
     "            if False:\n                continue",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("关·剔掉的框线不记墙（碎片又缝回来）", FIG,
     "            walls[y + sy:y + sy + sh, x + sx:x + sx + sw] = True",
     "            pass",
     "虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）"),
    ("关·接缝贯穿判据退回旧规则（有墨就缝）", FIG,
     "    need = max(SEAM_CROSS_MIN_COLS, int(round(SEAM_CROSS_WIDTH_SHARE * sub.shape[1])))\n"
     "    return cols >= need",
     "    return True",
     "跨题缝合：接缝要有贯穿笔画，同宽薄片例外（含四个反例）"),
    ("过·贯穿列门槛降到 0（3 列对齐竖线就缝）", FIG,
     "SEAM_CROSS_MIN_COLS = 6", "SEAM_CROSS_MIN_COLS = 0",
     "跨题缝合：接缝要有贯穿笔画，同宽薄片例外（含四个反例）"),
    ("过·贯穿笔画只要求 1px（两条边就缝）", FIG,
     "SEAM_CROSS_MIN_RUN_PX = 2", "SEAM_CROSS_MIN_RUN_PX = 1",
     "跨题缝合：接缝要有贯穿笔画，同宽薄片例外（含四个反例）"),
    ("关·薄片例外关掉（圆点阵顶行分家）", FIG,
     "                    sliver = (min(r[3] - r[1], b[3] - b[1]) <= STITCH_SLIVER_MAX_PT\n"
     "                              and narrow / wide >= STITCH_SLIVER_MIN_W_RATIO)",
     "                    sliver = False",
     "跨题缝合：接缝要有贯穿笔画，同宽薄片例外（含四个反例）"),
    ("过·薄片高度上限取消（50pt 整块当薄片）", FIG,
     "STITCH_SLIVER_MAX_PT = 32.0", "STITCH_SLIVER_MAX_PT = 1000.0",
     "跨题缝合：接缝要有贯穿笔画，同宽薄片例外（含四个反例）"),
    ("过·薄片宽度比取消（70 vs 100 也缝）", FIG,
     "STITCH_SLIVER_MIN_W_RATIO = 0.9", "STITCH_SLIVER_MIN_W_RATIO = 0.0",
     "跨题缝合：接缝要有贯穿笔画，同宽薄片例外（含四个反例）"),
    # ---- 第十二轮（综合实践单元(1) 第 2 题：三行材料只收末行，题干剩一个 ")"）----
    ("关·框底多行题干只收末行（续行仍被当图内文字删掉）", FIG,
     "STEM_BOTTOM_JOIN_PT = 6.0", "STEM_BOTTOM_JOIN_PT = -1.0",
     "裁框下沿不许吞掉本题末行题干（含九个反例）"),
    ("过·不限续行距离（35pt 外的图内说明也被收）", FIG,
     "STEM_BOTTOM_JOIN_PT = 6.0", "STEM_BOTTOM_JOIN_PT = 1000.0",
     "裁框下沿不许吞掉本题末行题干（含九个反例）"),
    # ---- 第十二轮·续（综合实践单元 第 1 页第 6 题：气泡人名行被当末行题干）----
    ("关·人名/气泡标签并成一行也当末行题干裁（气泡只剩半句）", FIG,
     "            if _looks_like_label_row(t):\n                continue                              # 人名/气泡/表头并成一行，不是题干",
     "            if False:\n                continue",
     "裁框下沿不许吞掉本题末行题干（含九个反例）"),
    ("过·所有行都当标签行（q30/q23 的题干全裁不动）", FIG,
     '    parts = [p for p in re.split(r"\\s{2,}", (text or "").strip()) if p.strip()]\n'
     '    if len(parts) < 3:\n'
     '        return False\n'
     '    short = [p for p in parts\n'
     '             if len(re.sub(r"\\s+", "", p)) <= 3\n'
     '             and not re.search(r"[（(）)□×＋+－=＝]", p)]\n'
     '    return len(short) >= 2',
     "    return True",
     "裁框下沿不许吞掉本题末行题干（含九个反例）"),
    # ---- 第十三轮（p7 第 2 题选项文字残影 / 达标B 第 5 题两条作答横线）----
    ("关·小窄块文字覆盖率判据（残影一律放行）", FIG,
     "    return int((sub & inside).sum()) / float(total) >= TEXT_BLOCK_COVER_MIN",
     "    return False",
     "多行文字残影不许当配图（含反例与接线）"),
    ("关·空白作答横线判据（两三条线当图裁）", FIG,
     "    return (BLANK_RULE_MIN_LINES <= n_lines <= BLANK_RULE_MAX_LINES\n"
     "            and longest >= w_pt * BLANK_RULE_LONG_SHARE)",
     "    return False",
     "空白作答横线不许当配图"),
    ("过·碎点门槛放到 100pt（16pt 实墨/表格竖线也放行）", FIG,
     "BLANK_RULE_MAX_OTHER_PT = 12.0", "BLANK_RULE_MAX_OTHER_PT = 100.0",
     "空白作答横线不许当配图"),
    ("关·合并后的最终复检（row-peer 长出的文字块又留下）", FIG,
     "    ok = _recheck_merged(ok, report, np, cv2)",
     "    ok = ok",
     "合并后长出来的文字块要按最终框复检（含反例）"),
    # ---- 第十四轮（L2 第 2 题 `50-55 ○ 3×9` 的两个作答圆圈）----
    ("关·作答圆圈判据（两个空心圈当图裁）", FIG,
     "    return ring_area / float(total) >= ANSWER_CIRCLE_MIN_SHARE",
     "    return False",
     "两个作答圆圈不许当配图（含反例与接线）"),
]


def run_tests() -> tuple[int, str]:
    r = subprocess.run([PY, os.path.join(ROOT, "tests", "test_figures.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    # 可选过滤：只跑名字里含某个关键词的变异（改一条判据时不必等整轮 20 分钟）。
    # 不带参数＝跑全部，check.bat 走的就是这条。
    only = [a for a in sys.argv[1:] if a.strip()]
    cases = [c for c in CASES if not only or any(o in c[0] for o in only)]
    if only and not cases:
        print("没有名字匹配的变异：" + "、".join(only))
        return 1
    orig = {p: open(p, "rb").read() for p in (FIG, LNS, AWR)}
    # 锚点预检：每条变异都要跑一遍 52 个测试，跑到第 N 条才发现某个旧串
    # 已经过期（源码在上一轮被改过）＝白等好几分钟。先把 119 条全查完再开跑。
    stale = [(name, orig[path].count(old.encode("utf-8")))
             for name, path, old, new, want in cases]
    stale = [(n, c) for n, c in stale if c != 1]
    if stale:
        for n, c in stale:
            print("★锚点过期：%s（%d 处）" % (n, c))
        print("\n0/%d：锚点没过预检，一条测试都没跑" % len(cases))
        return 1
    missed = []
    for name, path, old, new, want in cases:
        raw = orig[path]
        enc = old.encode("utf-8")
        assert raw.count(enc) == 1, "锚点不唯一或已变：%s（%d 处）" % (name, raw.count(enc))
        open(path, "wb").write(raw.replace(enc, new.encode("utf-8"), 1))
        try:
            rc, out = run_tests()
        finally:
            open(path, "wb").write(raw)
            assert open(path, "rb").read() == raw, "还原后字节不一致：" + path
        red = rc != 0
        named = any(w in out for w in ("FAIL " + want, "ERROR " + want))
        lines = [l.strip() for l in out.splitlines() if l.strip().startswith(("FAIL", "ERROR", "PASS"))]
        print("  %-34s → %s  %s" % (name, "测试变红" if red else "★仍然全绿★",
                                    "｜".join(l[:34] for l in lines[:3])))
        if not (red and named):
            tag = "（没红）" if not red else "（红了，但不是预期那条）"
            missed.append(name + tag)

    print("\n%d/%d 处退回旧行为被抓到" % (len(cases) - len(missed), len(cases)))
    if missed:
        print("没抓到：" + "、".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
