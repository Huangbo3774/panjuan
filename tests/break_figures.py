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
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 变异期间源码是"坏的"。进程被强杀/死机时 finally 不会执行，源码会停在坏态。
# 所以开跑前把四个文件的原字节落盘；正常结束删掉；异常退出后由
# tests/recover_mutations.py 还原（本文件检测到备份还在会拒绝再跑，防止叠加）。
BACKUP = os.path.join(ROOT, "var", "_mut_backup")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PY = sys.executable
FIG = os.path.join(ROOT, "app", "extractor", "figures.py")
LNS = os.path.join(ROOT, "app", "extractor", "lines.py")
RUL = os.path.join(ROOT, "app", "extractor", "rules.py")
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
     '            cov = _covers(cut, row)\n            if cov < STEM_IN_FIG_COVER:',
     '            cov = _covers(cut, row)\n            if False:',
     '裁框上沿不许吞掉本题起手句（含三个反例）'),
    ('关·从字中间切过的起手句不收（图顶留半行题干）', FIG,
     '                if not first_cut:\n                    continue\n            hits.append(row)',
     '                if True:\n                    continue\n            hits.append(row)',
     '裁框上沿从起手句中间切过也要收（含四个反例）'),
    ('过·起手句例外扩散到所有行（第二行被切开也削图顶）', FIG,
     '                first_cut = (i == first_i and row[1] < cut[1]',
     '                first_cut = (i >= 0 and row[1] < cut[1]',
     '裁框上沿从起手句中间切过也要收（含四个反例）'),
    ('过·起手句例外不卡覆盖率下限（只蹭 0.24 也削图顶）', FIG,
     '                             and cov >= 0.50',
     '                             and cov >= 0.00',
     '裁框上沿从起手句中间切过也要收（含四个反例）'),
    ('过·起手句例外不看字数（"图1。"也当题干）', FIG,
     '                             and len(re.sub(r"\\s+", "", t)) >= 8\n                             and bool(re.search(r"[。？?]|[（(]\\s*[）)]", t)))',
     '                             and bool(re.search(r"[。？?]|[（(]\\s*[）)]", t)))',
     '裁框上沿从起手句中间切过也要收（含四个反例）'),
    ('过·起手句例外不看句末标点/空位（图注当题干）', FIG,
     '                             and len(re.sub(r"\\s+", "", t)) >= 8\n                             and bool(re.search(r"[。？?]|[（(]\\s*[）)]", t)))',
     '                             and len(re.sub(r"\\s+", "", t)) >= 8)',
     '裁框上沿从起手句中间切过也要收（含四个反例）'),
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
     '            if not re.search(r"[。？?]|[（(]\\s*[）)]", t):\n                continue                              # 成句/带空位，不是"图1"这种题注\n            if (src is not None and k and np is not None\n                    and _row_in_border(src, row, k, np)):\n                continue                              # 印在闭合边框里：图的说明行\n            if _covers(cut, row) < STEM_IN_FIG_COVER:',
     '            if not re.search(r"[。？?]|[（(]\\s*[）)]", t):\n                continue                              # 成句/带空位，不是"图1"这种题注\n            if (src is not None and k and np is not None\n                    and _row_in_border(src, row, k, np)):\n                continue                              # 印在闭合边框里：图的说明行\n            if False:',
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
     '            cut = _clip_stem_row_bottom(rect, s.get("text_boxes") or [], ate_rows,\n                                        src=src, k=k, np=np)\n            if cut != rect:',
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
     "    cands = _stitch_across_questions(cands, report)",
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
    ("过·家具行占比阈值放到 101%（这条判据失去约束）", FIG,
     "WALL_INK_SHARE_MAX = 0.60", "WALL_INK_SHARE_MAX = 1.01",
     "家具行判据接线检查（含丢弃原因）"),
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
    # ── 题干第一行被截在图外 → 接进整题原图 ──
    ("关·题干第一行不接进图框（成品停在半句）", FIG,
     '        if sources is not None and len(imgs) == 1 and imgs[0].get("rect"):',
     "        if False:",
     "题干第一行接进整题原图（含三个反例）"),
    ("关·整题都在图里也不清题干（同一句印两遍）", FIG,
     "        if first_covered and not outside and len(imgs) == 1 \\\n"
     '                and not q.get("options") and not q.get("subqs"):',
     "        if False:",
     "题干第一行接进整题原图（含三个反例）"),
    ("过·完整句也收成整题图（完整题干被清空）", FIG,
     "                    and not _stem_looks_complete(flat)",
     "                    and True",
     "图内重复文字要从题干里删掉（含反例）"),
    ("过·单个图注也当整题截图（题干只剩小图）", FIG,
     '                    and (imgs[0].get("stem_extended") or n_inside >= 2)):',
     "                    and True):",
     "图里只剩尺寸标注：题干可清空（含三个反例）"),
    ("过·有选项也接成整题图（选项被导出吞掉）", FIG,
     '    if q.get("options") or q.get("subqs"):\n        return False',
     "    if False:\n        return False",
     "题干第一行接进整题原图（含三个反例）"),
    ("过·图里只有尺寸标注也接（普通配图吞掉题干行）", FIG,
     "    if not inside_sentence:\n        return False",
     "    if False:\n        return False",
     "题干第一行接进整题原图（含三个反例）"),
    ("过·图框上方那行不核对是不是本题题干（上一题被吞）", FIG,
     "        if not body or not qflat.startswith(body):\n            continue",
     "        if not body:\n            continue",
     "题干第一行接进整题原图（含三个反例）"),
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
    ("过·不剥行框里的题号（竖排图的 3/21 残留在题干）", FIG,
     "    bare = re.sub(r\"^\\s*\\d+\\s*[、.．]\\s*\", \"\", t).strip()",
     "    bare = t.strip()",
     "行框题号归一化：带题号与去题号两版都试"),
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
     '    if len(parts) < 2:\n'
     '        return False\n'
     '    if len(parts) == 2:\n'
     '        # 两段的行只认「纯序号标签」：③ ④ 被 OCR 读成 "3    4"，\n'
     '        # 单段全是括号/运算符的题干行（q30 算式空行）不能算。\n'
     '        toks = [re.sub(r"\\s+", "", p) for p in parts]\n'
     '        return all(re.fullmatch(r"[①-⑳A-Ha-h1-9]", t) for t in toks)\n'
     '    short = [p for p in parts\n'
     '             if len(re.sub(r"\\s+", "", p)) <= 3\n'
     '             and not re.search(r"[（(）)□×＋+－=＝]", p)]\n'
     '    return len(short) >= 2',
     "    return True",
     "裁框下沿不许吞掉本题末行题干（含九个反例）"),
    ("关·两段序号标签行退回「≥3 段」（③④ 只剩上半截）", FIG,
     "    if len(parts) == 2:\n"
     "        # 两段的行只认「纯序号标签」：③ ④ 被 OCR 读成 \"3    4\"，\n"
     "        # 单段全是括号/运算符的题干行（q30 算式空行）不能算。\n"
     "        toks = [re.sub(r\"\\s+\", \"\", p) for p in parts]\n"
     "        return all(re.fullmatch(r\"[①-⑳A-Ha-h1-9]\", t) for t in toks)",
     "    if len(parts) == 2:\n        return False",
     "两段序号标签行也要把下沿放下去（含题干反例）"),
    ("关·图下的选项行又被当图注裁进图里（P1 Q7 重复选项）", FIG,
     "        if _looks_like_options_row(t):\n"
     "            continue                       # 选项行已按文字印过，不再裁进图里重复\n"
     "        if not _figure_edge_label_like(t):",
     "        if not _figure_edge_label_like(t):",
     "图下的选项行不裁进图里重复（含正反例）"),
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
    # ---- 第十五轮（图形算式整行原图 / 整题截图图文分离 / 栏界接墨）----
    ("关·图形算式整行判据（图标行又被切成碎片）", FIG,
     "                gb = _graphic_equation_block(src, s, np, cv2)",
     "                gb = None",
     "图形算式接线：真 PDF 上整行成图、题干加说明（含反例）"),
    ("过·图形算式图标的实心门槛（空心图形也算图标）", FIG,
     '            and c["fill"] >= GRAPHIC_ICON_FILL_MIN)',
     "            and True)",
     "图形算式整行原图：一排字符级图标不许被切成碎片（含五个反例）"),
    ("过·图形算式不挡其他文字行（整块罩住邻题也成图）", FIG,
     "        if other is tb:\n"
     "            continue\n"
     "        ox0, oy0 = float(other[\"x\"]), float(other[\"y\"])\n"
     "        ox1 = ox0 + float(other.get(\"w\") or 0)\n"
     "        oy1 = oy0 + float(other.get(\"h\") or 0)\n"
     "        iw = min(x1, ox1) - max(x0, ox0)\n"
     "        ih = min(y1, oy1) - max(y0, oy0)\n"
     "        if iw > 0 and ih > 0 and iw * ih >= 0.5 * max(1.0, (ox1 - ox0) * (oy1 - oy0)):\n"
     "            return None",
     "        if other is tb:\n"
     "            continue\n"
     "        ox0, oy0 = float(other[\"x\"]), float(other[\"y\"])\n"
     "        ox1 = ox0 + float(other.get(\"w\") or 0)\n"
     "        oy1 = oy0 + float(other.get(\"h\") or 0)\n"
     "        iw = min(x1, ox1) - max(x0, ox0)\n"
     "        ih = min(y1, oy1) - max(y0, oy0)\n"
     "        if False:\n"
     "            return None",
     "图形算式整行原图：一排字符级图标不许被切成碎片（含五个反例）"),
    ("关·图形算式的碎片剔除（整行图旁边再裁一条）", FIG,
     "            if grect is not None and _covers(grect, rect) >= 0.5:",
     "            if False:",
     "图形算式接线：真 PDF 上整行成图、题干加说明（含反例）"),
    ("关·图形算式说明不落到题干（留长空格装没事）", FIG,
     '        if not (0 <= qi < len(qs)) or not any(im.get("graphic") for im in imgs):\n'
     "            continue",
     "        if True:\n            continue",
     "图形算式接线：真 PDF 上整行成图、题干加说明（含反例）"),
    # ---- 第十六轮（算式各部分名称的竖排图：OCR 读丢结构，只能整块成图）----
    ("关·竖排图判据（乘数/读作碎片又留在题干）", FIG,
     "                gb = _term_diagram_block(src, s)",
     "                gb = None",
     "竖排图接线：整块裁图并补专用说明"),
    ("过·术语标签按前缀匹配（表格式长行也算标签）", FIG,
     'TERM_LABEL_RE = re.compile(r"^(?:乘数|因数|被乘数|加数|和|积)$")',
     'TERM_LABEL_RE = re.compile(r"^(?:乘数|因数|被乘数|加数|和|积)")',
     "算式各部分名称的竖排图要整块成图（含五个反例）"),
    ("过·标签与读作不限距离（隔整道题也成一块）", FIG,
     "            if gap < 0 or gap > TERM_FORM_MAX_GAP_PT:",
     "            if gap < 0:",
     "算式各部分名称的竖排图要整块成图（含五个反例）"),
    ("过·两行也成图（标签+读作没有中缀碎片）", FIG,
     "    if len(members) < 3:\n        return None",
     "    if False:\n        return None",
     "算式各部分名称的竖排图要整块成图（含五个反例）"),
    ("过·竖排图罩住题干行也照裁（图文分离删成白卷）", FIG,
     '        if float(tb["y"]) < float(rd["y"]) < float(tb["y"]) + float(tb.get("h") or 0) - 1.0:\n'
     "            return None",
     "        if False:\n            return None",
     "算式各部分名称的竖排图要整块成图（含五个反例）"),
    ("关·竖排图专用说明（家长看不懂图里是什么）", FIG,
     '                note = "（本题算式的各部分名称见下方原图）"',
     '                note = "（本题算式中的图形见下方原图）"',
     "竖排图接线：整块裁图并补专用说明"),
    # ---- 第二十轮：连一连的匹配版式 ----
    ("关·66 连一连不看题面（普通题也整块成图）", FIG,
     "            anchor = tb\n            break\n    if anchor is None:\n        return None",
     "            anchor = tb\n            break\n    if False:\n        return None",
     "连一连的匹配版式要整块成图（含五个反例）"),
    ("关·66 连一连不看题干空位（带空位的题也整块成图）", FIG,
     "    ta = re.sub(r\"\\s+\", \"\", str(anchor.get(\"text\") or \"\"))\n"
     "    if re.search(r\"[（(]\\s*[）)]|[（(]\\s*\\d+\\s*分\", ta):",
     "    ta = re.sub(r\"\\s+\", \"\", str(anchor.get(\"text\") or \"\"))\n"
     "    if False:",
     "连一连的匹配版式要整块成图（含五个反例）"),
    ("关·66 连一连下面有空位也接管（答题行进图）", FIG,
     "        if re.search(r\"[（(]\\s*[）)]|[（(]\\s*\\d+\\s*分\", t):\n"
     "            return None",
     "        if False:\n            return None",
     "连一连的匹配版式要整块成图（含五个反例）"),
    ("关·66 连一连中间断开也硬缝（页脚墨带并进图）", FIG,
     "        if merged and (a - merged[-1][1]) / k <= MATCH_ROW_GAP_PT:",
     "        if merged:",
     "连一连的匹配版式要整块成图（含五个反例）"),
    ("关·66 连一连不管断开处的文字（页脚广告并进题干）", FIG,
     "        if ty >= top - 0.5 and ty > first_end_pt + 0.5:\n            return None",
     "        if False:\n            return None",
     "连一连的匹配版式要整块成图（含五个反例）"),
    ("关·66 连一连裁图没接线（条目仍并段）", FIG,
     "                gb = _match_layout_block(src, s)",
     "                gb = None",
     "匹配版式接线：整块裁图并补专用说明"),
    ("关·66 连一连专用说明丢掉（家长不知道怎么作答）", FIG,
     '            if "match" in kinds:\n'
     '                note = "（连一连的题目见下方原图，请照着原图连线）"',
     '            if False:\n'
     '                note = "（连一连的题目见下方原图，请照着原图连线）"',
     "匹配版式接线：整块裁图并补专用说明"),
    ("关·整题截图的成句门槛（地图标签也被切）", FIG,
     "    if not _echo_full_sentence(first_raw, stem):\n        return rect, None",
     "    if False:\n        return rect, None",
     "整题截图只留图：切掉题干文字块（含五个反例）"),
    ("关·整题截图的干净区门槛（切完不剩也动手）", FIG,
     '    if not regions:\n        return None, "stem-screenshot"',
     '    if False:\n        return None, "stem-screenshot"',
     "整题截图只留图：切掉题干文字块（含五个反例）"),
    ("关·栏界接墨的连续性门槛（隔着空白也接宽）", FIG,
     "                if c > EDGE_EXTEND_GAP_PX + 1:\n"
     "                    return rect                 # 框边先是空白：不是这张图的延续",
     "                if False:\n"
     "                    return rect                 # 框边先是空白：不是这张图的延续",
     "栏界切断的框线要接回来（含三个反例）"),
    # ---- 第十七轮（地图短标签去重、半个字修边、页边密封线）----
    ("关·64 长词也算图注（行首长词被摘）", FIG,
     "len(tok) > SIDE_LABEL_MAX_CHARS",
     "len(tok) > 99",
     "地图短标签只摘行首图注，题干正文不动（含四个反例）"),
    ("关·64 图注后没正文也摘（整行图注被删光）", FIG,
     "    if len(body) < SIDE_BODY_MIN_CHARS:",
     "    if False:",
     "地图短标签只摘行首图注，题干正文不动（含四个反例）"),
    ("关·64 正文起点取最右空白（切进括号）", FIG,
     "    _, _a, b = max(cand)",
     "    _, _a, b = cand[-1]",
     "图文同排切分停在正文之前（含纯正文反例）"),
    ("关·64 切分越过正文起点（题干被裁进图）", FIG,
     "        if split > body_min + 0.5:",
     "        if False:",
     "图文同排切分停在正文之前（含纯正文反例）"),
    ("关·64 切点取第一条缝（指北针被削）", FIG,
     "        best = split                       # 候选缝里取最靠右的那条",
     "        best = best or split",
     "图文同排切分停在正文之前（含纯正文反例）"),
    ("关·64 上沿半个字不收", FIG,
     "                top = max(top, by1 + 0.5)",
     "                top = top",
     "裁框只切到半个字：上下沿要收（含贴墨反例）"),
    ("关·64 下沿半个字不收", FIG,
     "                bottom = min(bottom, by0 - 0.5)",
     "                bottom = bottom",
     "裁框只切到半个字：上下沿要收（含贴墨反例）"),
    ("关·64 行外没有空白也收（削掉贴边图）", FIG,
     "            if prev is None or (iy - 1 - prev) / k >= SIDE_SPLIT_GAP_PT:",
     "            if True:",
     "裁框只切到半个字：上下沿要收（含贴墨反例）"),
    ("关·64 外伸行仍按 45% 判（图底留黑边）", FIG,
     "        limit = (SLIVER_ROW_CROSS_LEFT_FRAC if bx0 < x0 + 2.0\n"
     "                 else SLIVER_ROW_FRAC)",
     "        limit = SLIVER_ROW_FRAC",
     "裁框只切到半个字：上下沿要收（含贴墨反例）"),
    ("关·64 所有行都按 60% 判（图注被削）", FIG,
     "        limit = (SLIVER_ROW_CROSS_LEFT_FRAC if bx0 < x0 + 2.0\n"
     "                 else SLIVER_ROW_FRAC)",
     "        limit = SLIVER_ROW_CROSS_LEFT_FRAC",
     "裁框只切到半个字：上下沿要收（含贴墨反例）"),
    ("关·64 下沿分支仍用 45% 判（外伸行漏收）", FIG,
     "        elif by0 >= y1 - limit * h:",
     "        elif by0 >= y1 - SLIVER_ROW_FRAC * h:",
     "裁框只切到半个字：上下沿要收（含贴墨反例）"),
    ("关·64 三个图标签也算一列（切掉图里的门）", FIG,
     "    if len(col) < 4:",
     "    if False:",
     "页边竖排密封线要裁掉（含四个反例）"),
    ("关·64 没盖住密封字也切", FIG,
     "    if not any(_covers(rect, b) >= 0.5 for b in col):",
     "    if False:",
     "页边竖排密封线要裁掉（含四个反例）"),
    ("关·64 正文中间的小字也当密封线", FIG,
     "             and b[0] >= page_w - 80.0]",
     "             and b[0] >= 0.0]",
     "页边竖排密封线要裁掉（含四个反例）"),
    ("关·64 密封线切完只剩窄条也切", FIG,
     "    if cut - rect[0] < 12.0:",
     "    if False:",
     "页边竖排密封线要裁掉（含四个反例）"),
    ("关·64 最后修边没接线", FIG,
     '        trimmed = _trim_sliver_text_rows(rect, page_boxes.get(c["page"], []),\n'
     '                                         c["src"], np, DPI_PROBE / 72.0)',
     "        trimmed = rect",
     "最后修边接线检查（edge-trim）"),
    ("关·64 密封线裁切没接线", FIG,
     "        clipped = _clip_seal_strip(\n"
     '            regrown, noise_by_page.get(c["page"], []), c["src"].width_pt,\n'
     '            src=c["src"], k=DPI_PROBE / 72.0)',
     "        clipped = regrown",
     "密封线裁切接线检查（edge-trim）"),
    ("关·64 密封列不看纵向空档（散落地图标签被裁掉）", FIG,
     "        return max(gaps) <= 0.16 * page_h",
     "        return True",
     "密封字按真实字号认列，散落地图标签不许当列"),
    ("关·64 密封虚线不看最大空隙（正文栏被当虚线）", FIG,
     "        if int((rows[1:] - rows[:-1]).max()) > 6.0 * k:",
     "        if False:",
     "密封字左边那条竖虚线要找到并切在它左边（含四个反例）"),
    ("关·64 页脚也被当图注吸进裁框", FIG,
     "        if is_furniture_text(text):\n            continue",
     "        if False:\n            continue",
     "页脚不许被当成图注吸进裁框（含真图注反例）"),
    ("关·64 side_split 标志不输出", FIG,
     '"side_split": bool(c.get("side_split")),',
     '"side_split": False,',
     "图文同排切分接线检查（含跳过接宽）"),
    ("关·64 同排收窄后不跳过接宽", FIG,
     'grown = rect if side_split else _extend_edge_ink(rect, src, k, np, "right", wr)',
     'grown = _extend_edge_ink(rect, src, k, np, "right", wr)',
     "图文同排切分接线检查（含跳过接宽）"),
    ("关·64 同排切分不摘图注（整行留下）", FIG,
     "            if side:",
     "            if False:",
     "图文同排收窄后题干只摘图注（正文必须留）"),
    ("关·65 整题截图不在削题干行前判（图里重复故事题干）", FIG,
     "            if q_text:\n"
     "                edited0, ewhy0 = _stem_echo_edit(rect, s.get(\"text_boxes\") or [], q_text,\n"
     "                                                 src=src, k=k)\n",
     "            if False:\n"
     "                edited0, ewhy0 = _stem_echo_edit(rect, s.get(\"text_boxes\") or [], q_text,\n"
     "                                                 src=src, k=k)\n",
     "整题截图要在削题干行之前丢（接线检查）"),
    ("关·65 页边压痕判据没接线（压痕成图）", FIG,
     "            if _is_page_edge_band(raw, src):",
     "            if False:",
     "页边扫描压痕不许当配图（含四条反例）"),
    ("关·65 页边压痕不限高度（53pt 高图被砍）", FIG,
     "    if y1 - y0 > 40.0 or x1 - x0 < 80.0:",
     "    if x1 - x0 < 80.0:",
     "页边扫描压痕不许当配图（含四条反例）"),
    ("关·65 页边压痕不看墨量（页顶真图被砍）", FIG,
     "    return float((sub < 170).mean()) <= 0.005",
     "    return True",
     "页边扫描压痕不许当配图（含四条反例）"),
    ("关·65 矮块也按整题截图丢（方格图陪葬）", FIG,
     "STEM_SCREENSHOT_MIN_H_PT = 120.0",
     "STEM_SCREENSHOT_MIN_H_PT = 0.0",
     "整题截图只认高块，气泡/说明框不许整框丢（含三档边界）"),
    ("关·65 横向切半的题干行不占干净区（截图留半截）", FIG,
     "ECHO_ROW_EDGE_MIN = 0.50",
     "ECHO_ROW_EDGE_MIN = 0.80",
     "横向切半的题干行也占干净区（整题截图不许留半截）"),
    ("关·65 下沿题干行不收（数轴被截图判据吞掉）", FIG,
     "STEM_BOTTOM_TOL_PT = 12.0",
     "STEM_BOTTOM_TOL_PT = 0.0",
     "数轴图：先收下沿题干行再判截图（含顺序反例）"),
    ("关·65 截图碎片没跟着截图一起丢（空格子单独出图）", FIG,
     "    if not shot_rects:\n        return cands",
     "    if True:\n        return cands  # mutation: 不丢截图碎片",
     "整题截图的答题格碎片要跟着丢（含三个反例）"),
    # ---- 第十八轮（地图短标签：选项行、跨框整行、题干首行；图注形状）----
    ("关·66 长句也当图注", FIG,
     "    if not t or len(t) > DIAGRAM_LABEL_MAX_CHARS:",
     "    if not t:",
     "图注形状判据（含正反样例）"),
    ("关·66 带标记的连写图注不认（祥和小区出口被漏）", FIG,
     '    if re.search(r"[★☆▲△◆◇○●◎]", t):\n        return True',
     "    if False:\n        return True",
     "图注形状判据（含正反样例）"),
    ("关·66 选项行伸进图框的图注不摘", FIG,
     "        n += _strip_side_labels_from_options(",
     "        n += 0 * _strip_side_labels_from_options(",
     "选项行伸进图框：图里的短标签要摘掉（含四个反例）"),
    ("关·66 整行跨在图框里的图注不删", FIG,
     "            if any(_diagram_row_hit(bb, t, r) for r in rects):",
     "            if False:",
     "整行跨在图框里的图注不算题干（含反例）"),
    ("关·66 题干行伸进图框的图注也不摘（首行重复）", FIG,
     "                    cut = _side_label_cut(t, bb, r, option=False)",
     "                    cut = None",
     "题干首行只丢图注、正文必须留（含三个反例）"),
    ("关·66 作答括号里的空白当图注缝（题干括号残缺）", FIG,
     '        if prefix.endswith(("(", "（")) or suffix[:1] in (")", "）"):\n'
     "            continue\n",
     "",
     "题干首行只丢图注、正文必须留（含三个反例）"),
    # ---- 第十八轮续：裁框从表格行中间切过 / 跨题图蹭边 ----
    ("关·66 并整行图注没接线（表头仍留在框外）", FIG,
     "        grown = _grow_over_cut_label_rows(rect, page_boxes.get(c[\"page\"], []),\n"
     "                                          top_limit=(c.get(\"band\") or [0, 0, 0, 0])[1])",
     "        grown = rect",
     "并整行图注接线检查（label-grow）"),
    ("关·66 带逗号的正文也并进图（题干被吞）", FIG,
     "        if _looks_like_options_row(t):\n"
     "            continue                       # 选项行已按文字印过，不再裁进图里重复\n"
     "        if not (_figure_edge_label_like(t) or edge_tail):\n"
     "            continue\n"
     "        rows.append((by0, by1))\n"
     "    if top_limit is not None:",
     "        if _looks_like_options_row(t):\n"
     "            continue                       # 选项行已按文字印过，不再裁进图里重复\n"
     "        if False:\n"
     "            continue\n"
     "        rows.append((by0, by1))\n"
     "    if top_limit is not None:",
     "裁框从表格行中间切过：整行连表头并进图（含三个反例）"),
    ("关·66 伸出框外的正文行也并进图", FIG,
     "        if (bx0 < x0 - 2.0 or bx1 > x1 + 2.0) and not edge_tail:\n"
     "            continue                       # 行伸出框外：不是图注，是正文\n"
     "        if _looks_like_options_row(t):\n"
     "            continue                       # 选项行已按文字印过，不再裁进图里重复\n"
     "        if not (_figure_edge_label_like(t) or edge_tail):\n"
     "            continue\n"
     "        rows.append((by0, by1))\n"
     "    if top_limit is not None:",
     "        if False:\n"
     "            continue                       # 行伸出框外：不是图注，是正文\n"
     "        if _looks_like_options_row(t):\n"
     "            continue                       # 选项行已按文字印过，不再裁进图里重复\n"
     "        if not (_figure_edge_label_like(t) or edge_tail):\n"
     "            continue\n"
     "        rows.append((by0, by1))\n"
     "    if top_limit is not None:",
     "裁框从表格行中间切过：整行连表头并进图（含三个反例）"),
    ("关·66 跨题蹭边收回没接线（邻题人头留在上题）", FIG,
     "    ok = _recheck_merged(ok, report, np, cv2)\n"
     "\n"
     "    # 上一题的图底只蹭进下一题的图几个点（缝合把邻题的人头并进来了）→ 收回底沿\n"
     "    ok = _trim_cross_question_graze(ok, report)",
     "    ok = _recheck_merged(ok, report, np, cv2)\n"
     "\n"
     "    # 上一题的图底只蹭进下一题的图几个点（缝合把邻题的人头并进来了）→ 收回底沿\n"
     "    ok = ok",
     "跨题蹭边收回接线检查（cross-graze）"),
    ("关·66 表格底边被当成邻题人头削掉", FIG,
     "                if a.get(\"border_strip\"):\n"
     "                    # 底沿是刚并进来的表格边框，不是邻题的人头；削了就把框线切断\n"
     "                    continue",
     "                if False:\n                    continue",
     "跨题图只蹭进几个点：收上题底沿（含三个反例）"),
    ("关·66 表格边框条不并回图（表格缺底边）", FIG,
     "            if (BORDER_STRIP_MIN_H_PT <= ph <= BORDER_STRIP_MAX_H_PT",
     "            if (False and BORDER_STRIP_MIN_H_PT <= ph <= BORDER_STRIP_MAX_H_PT",
     "同行被砍的小括号要并回图框（算式不许被截断）"),
    ("关·66 边框条不看宽度（小图标也并进表格）", FIG,
     "                    and pw >= (r[2] - r[0]) * BORDER_STRIP_MIN_W_SHARE",
     "                    and True",
     "同行被砍的小括号要并回图框（算式不许被截断）"),
    ("关·66 边框条隔着 12pt 也并（两行外的图被拉进来）", FIG,
     "                if -2.0 <= vgap <= BORDER_STRIP_MAX_GAP_PT:",
     "                if True:",
     "同行被砍的小括号要并回图框（算式不许被截断）"),
    ("关·66 缝合后不看区间（圆点阵挂回上一题）", FIG,
     "                            if (_band_share(u, g[j].get(\"band\") or b)\n"
     "                                    > _band_share(u, own_band)):",
     "                            if False:",
     "共享图被题界切成两块：同左沿要缝回一张（含五个反例）"),
    ("关·66 同左沿不补 12.4pt 的缝（地图缺下半张）", FIG,
     "                    if gap > STITCH_GAP_PT and not strip_below:",
     "                    if gap > STITCH_GAP_PT:",
     "共享图被题界切成两块：同左沿要缝回一张（含五个反例）"),
    ("关·66 大段重叠也收（共享图被削）", FIG,
     "                if ih > CROSS_GRAZE_MAX_PT or ih > min(ah, bh) * CROSS_GRAZE_MAX_FRAC:\n"
     "                    continue",
     "                if False:\n                    continue",
     "跨题图只蹭进几个点：收上题底沿（含三个反例）"),
    ("关·66 同题两块也互收", FIG,
     "                if int(a[\"q_index\"]) == int(b[\"q_index\"]):\n                    continue",
     "                if False:\n                    continue",
     "跨题图只蹭进几个点：收上题底沿（含三个反例）"),
    ("关·66 摘图注时拿行框前缀替换（卷面印成「4. 4如右图」）", FIG,
     "                    body = seg[:keep].rstrip()\n"
     "                    if (keep > 0 and len(re.sub(r\"\\s+\", \"\", body)) >= 4",
     "                    body = t[:cut].rstrip()\n"
     "                    if (keep > 0 and len(re.sub(r\"\\s+\", \"\", body)) >= 4",
     "题干首行只丢图注、正文必须留（含三个反例）"),
    ("关·66 续行行首图注不摘（同一地名印两遍）", FIG,
     "                if (vshare >= 0.5 and bb[0] >= r[0] - 2.0",
     "                if (False and bb[0] >= r[0] - 2.0",
     "续行行首落在图里：只摘地名、正文要留（含两个反例）"),
    # ---- 第十八轮续：共享地图跨题缝合 / 带花边的文字框 / 邻图借几何 ----
    ("关·66 同左沿的共享图不缝（地图被劈成两半）", FIG,
     "                    if same_left and (b[1] < r[3] - 2.0 or strip_below):",
     "                    if False:",
     "共享图被题界切成两块：同左沿要缝回一张（含五个反例）"),
    ("关·66 不同左沿的两张图也缝（并成一张怪图）", FIG,
     "                    same_left = (abs(r[0] - b[0]) <= 2.0",
     "                    same_left = (True",
     "共享图被题界切成两块：同左沿要缝回一张（含五个反例）"),
    ("关·66 文字框的外圈细框不认（路线指示框仍成图）", FIG,
     "        if fill <= 0.25 and thin_frame == 0:",
     "        if False:",
     "带花边的文字框不是配图（含九个反例）"),
    ("关·66 文字框不看整句（记录表标签也删）", FIG,
     "    if prose < 2:",
     "    if False:",
     "带花边的文字框不是配图（含九个反例）"),
    ("关·66 文字框只看字数不看句读（记录表标签算整句）", FIG,
     "    return len(t) >= 12 and bool(PROSE_PUNCT_RE.search(t))",
     "    return len(t) >= 12",
     "带花边的文字框不是配图（含九个反例）"),
    ("关·66 文字框只看句读不看字数（短句也算整句）", FIG,
     "    return len(t) >= 12 and bool(PROSE_PUNCT_RE.search(t))",
     "    return bool(PROSE_PUNCT_RE.search(t))",
     "带花边的文字框不是配图（含九个反例）"),
    ("关·66 文字框不看 OCR 原文（没有文本也硬判）", FIG,
     "    if not tb_txt or len(tb_txt) != len(tb_px):\n        return False",
     "    if False:\n        return False",
     "带花边的文字框不是配图（含九个反例）"),
    ("关·66 文字框不看框外墨占比（一框小图标被吞）", FIG,
     "    if int(out.sum()) / float(total) > 0.30:",
     "    if False:",
     "带花边的文字框不是配图（含九个反例）"),
    ("关·66 文字框不看尺寸上限（整题截图被当文字框）", FIG,
     "    if not (60.0 <= w_pt <= 260.0 and 15.0 <= h_pt <= 90.0):",
     "    if not (60.0 <= w_pt <= 2600.0 and 15.0 <= h_pt <= 90.0):",
     "带花边的文字框不是配图（含九个反例）"),
    ("关·66 共享图后一题不进扫描范围（续行地名留着）", FIG,
     "    for qi, pc in page_col.items():\n        if neigh.get(pc):\n            scope.add(int(qi))",
     "    for qi, pc in page_col.items():\n        if False:\n            scope.add(int(qi))",
     "共享图后一题没有自己的图：续行行首地名也要摘（含三个反例）"),
    ("关·66 邻图不参与行首几何（续行地名留着）", FIG,
     "        for r_ in neigh.get(page_col.get(qi, (-1, -1)), []):",
     "        for r_ in []:",
     "共享图后一题没有自己的图：续行行首地名也要摘（含三个反例）"),
    ("过·邻图整行删字（题干里的同名标签被删）", FIG,
     '        rects = [tuple(im["rect"]) for im in imgs if im.get("rect")]',
     '        rects = [tuple(im["rect"]) for im in imgs if im.get("rect")]'
     ' + list(neigh.get(page_col.get(qi, (-1, -1)), []))',
     "共享图后一题没有自己的图：续行行首地名也要摘（含三个反例）"),
    # ---- 第十九轮（附加题分段 / 窄图顶上的题干字尾 / 正文右端字尾条）----
    ("关·76 窄图顶上的题干字尾不收（「画一画。（6分）」留在图里）", FIG,
     "                if not first_cut and src is not None and k:\n",
     "                if False:\n",
     "窄图的题干行字尾要收（含四个反例）"),
    ("关·76 重叠区墨量永远算 0（窄图顶上的题干字尾不收）", FIG,
     "    return int((src.gray[by0:by1, bx0:bx1] < src.ink_thr).sum())\n",
     "    return 0\n",
     "窄图的题干行字尾要收（含四个反例）"),
    ("关·76 题干与气泡并成一行也削图顶（气泡被切）", FIG,
     "                                and not re.search(r\"\\S[ \\t\\u3000]{3,}\\S\", t)",
     "                                and True",
     "窄图的题干行字尾要收（含四个反例）"),
    ("关·76 字尾条宽度不封顶（宽 30pt 的真图被砍）", FIG,
     "    if w > TEXT_EDGE_MAX_W_PT or h < 16.0:\n",
     "    if h < 16.0:\n",
     "正文右端字尾的窄条不是配图（含四个反例）"),
    ("关·76 一个字尾就够（单行也被当残片砍）", FIG,
     "            if hits >= TEXT_EDGE_MIN_ROWS:\n",
     "            if hits >= 1:\n",
     "正文右端字尾的窄条不是配图（含四个反例）"),
    ("关·76 不短到 6 字也算证据（图内「北 东」凑成残片）", FIG,
     "        if len(text) < TEXT_EDGE_MIN_CHARS:\n",
     "        if False:\n",
     "正文右端字尾的窄条不是配图（含四个反例）"),
    ("关·76 修边后的窄条字尾不复检（14pt 文字残片成图）", FIG,
     '        if not c.get("graphic") and _is_text_edge_fragment(\n',
     '        if False and _is_text_edge_fragment(\n',
     "窄条字尾复检接线检查（text-edge）"),
    # ---- 第十九轮续：图前伪题折进下一题的四条护栏 ----
    ("关·76 带空位的伪题也折（真题被吞）", FIG,
     '        if re.search(r"[（(]\\s*[）)]", flat) or re.search(r"[（(]\\s*\\d+\\s*分", flat):\n',
     "        if False:\n",
     "图前伪题折进下一题（含六个反例）"),
    ("关·76 跨大题也折（图借给下一大题）", FIG,
     '                or q.get("section") != nxt.get("section")):\n',
     "                or False):\n",
     "图前伪题折进下一题（含六个反例）"),
    ("关·76 伪题没有图也折（正常无编号题被吞）", FIG,
     '        if not imgs:\n            i += 1\n            continue\n'
     '        t = str(q.get("text") or "")\n',
     '        if False:\n            i += 1\n            continue\n'
     '        t = str(q.get("text") or "")\n',
     "图前伪题折进下一题（含六个反例）"),
    ("关·76 图例不并进题干（①②③ 图成了看图猜谜）", FIG,
     '        if re.search(r"[①-⑳]", flat):        # 图例是答题必需的信息，并进题干开头\n',
     "        if False:\n",
     "图前伪题折进下一题（含六个反例）"),
    ("关·76 折题不改 got（后面的图全错位）", FIG,
     "        if got is not None:\n",
     "        if False:\n",
     "图前伪题折进下一题（含六个反例）"),
    ("关·76 一个圈号也算图例（正文里的①被折）", FIG,
     '    if len(set(re.findall(r"[①-⑳]", t))) >= 2:\n',
     '    if len(set(re.findall(r"[①-⑳]", t))) >= 1:\n',
     "图前伪题折进下一题（含六个反例）"),
    # ---- 第二十轮：切边补字（图内标签只剩半个字）----
    ("关·切字接边没接线（图内标签只剩半个字）", FIG,
     '                glyph = _extend_cut_glyph(rect, src, k, np, "right", wr)\n',
     "                glyph = rect\n",
     "切字接边接线检查（glyph-extend）"),
    # ---- 第二十一轮：图注生长不许越区间 / 叠缝题干行 / 看图兜底中线切 ----
    ("关·图注向上长越过本题区间（上一题图注被吞）", FIG,
     "    if top_limit is not None:\n",
     "    if False:\n",
     "图注生长不许越过本题区间（含正反例）"),
    ("关·图注向下长越过本题区间（下一题正文被吞）", FIG,
     "    if bottom_limit is not None:\n",
     "    if False:\n",
     "图注生长不许越过本题区间（含正反例）"),
    ("关·叠缝里夹着题干行也缝（上一题的图混进下一题）", FIG,
     "                    if bridged:\n",
     "                    if False:\n",
     "叠缝里夹着题干行：两块不许缝（含短题号正例）"),
    ("关·兜底截图不看中线空白缝（左右两问混成一张）", FIG,
     "    if best is None:\n        return None\n    return (best[0] + best[1]) // 2",
     "    return None",
     "看图兜底的中线切分接线检查（side-split）"),
    ("关·兜底截图不接线（Q17 整段截图混进 Q18）", FIG,
     "        if side_later:\n",
     "        if False:\n",
     "看图兜底的中线切分接线检查（side-split）"),
    ("关·共用题号行不算并排证据（Q17 图里混进 Q18）", FIG,
     "                                and (cur_h <= 24.0 or _span_mentions_qno(\n",
     "                                and (cur_h <= 24.0 or False and _span_mentions_qno(\n",
     "看图兜底的中线切分接线检查（side-split）"),
    ("关·侧边尺寸标注不算图注（8cm 漏在图外）", FIG,
     "        if not (_figure_edge_label_like(t) or edge_tail):\n"
     "            continue\n"
     "        by0 = float(tb[\"y\"])\n"
     "        by1 = by0 + float(tb.get(\"h\") or 0)\n"
     "        if by1 - by0 <= 0.5 or by1 - by0 > 14.0:\n"
     "            continue\n"
     "        if by1 < y0 + 0.5 or by0 > y1 - 0.5:",
     "        if False:\n"
     "            continue\n"
     "        by0 = float(tb[\"y\"])\n"
     "        by1 = by0 + float(tb.get(\"h\") or 0)\n"
     "        if by1 - by0 <= 0.5 or by1 - by0 > 14.0:\n"
     "            continue\n"
     "        if by1 < y0 + 0.5 or by0 > y1 - 0.5:",
     "图形侧边的尺寸标注要横向长进图（含四个反例）"),
    ("关·侧边标注隔 240pt 也长（把邻栏正文拉进图）", FIG,
     "DIAGRAM_SIDE_GAP_PT = 24.0", "DIAGRAM_SIDE_GAP_PT = 240.0",
     "图形侧边的尺寸标注要横向长进图（含四个反例）"),
    ("关·侧边标注不看纵向（别的行的尺寸也拉进来）", FIG,
     "        if by1 < y0 + 0.5 or by0 > y1 - 0.5:\n",
     "        if False:\n",
     "图形侧边的尺寸标注要横向长进图（含四个反例）"),
    # ---- 第二十一轮续：清字后的三件收尾 ----
    ("关·光题号没有图也清（可能清掉仅有的内容）", FIG,
     "        if not q.get(\"images\"):\n            continue",
     "        if False:\n            continue",
     "清字收尾：光题号/半边括号/粘来的下一题号（含反例）"),
    ("关·清字后不剥句尾半边括号（P5 题干留「） ）」）", FIG,
     "            if imgs:\n"
     "                text = strip_dangling_tail(text)\n",
     "            if False:\n"
     "                text = strip_dangling_tail(text)\n",
     "图内重复文字要从题干里删掉（含反例）"),
    ("关·括号配对判断写反（半边不标、配对反标）", FIG,
     '        if (t.count("（") + t.count("(")) != (t.count("）") + t.count(")")):',
     '        if (t.count("（") + t.count("(")) == (t.count("）") + t.count(")")):',
     "清字收尾：光题号/半边括号/粘来的下一题号（含反例）"),
    ("关·粘来的题号不看同大题有没有该题（正常句尾也摘）", RUL,
     "        if not any(x.get(\"section\") == sec and x.get(\"q_no\") == no\n"
     "                   for x in qs[i + 1:]):\n"
     "            continue",
     "        if False:\n            continue",
     "清字收尾：光题号/半边括号/粘来的下一题号（含反例）"),
    # ---- 第二十二轮：左沿题干尾巴 / 矮块图长回真边 / 收底沿看自己的墨 ----
    ("关·77 左沿题干尾巴不看字数（短标签也被当正文切）", FIG,
     "LEFT_TAIL_MIN_CHARS = 12",
     "LEFT_TAIL_MIN_CHARS = 0",
     "裁框左沿切进题干长行：收到文字与图之间（含四个反例）"),
    ("关·77 左段贯穿全高也切（表格左栏被当文字尾巴）", FIG,
     "LEFT_TAIL_MAX_LEFT_ROWS = 0.60",
     "LEFT_TAIL_MAX_LEFT_ROWS = 1.01",
     "裁框左沿切进题干长行：收到文字与图之间（含四个反例）"),
    ("关·77 缝右没有图也切（把图裁没）", FIG,
     "        if right_cols < LEFT_TAIL_MIN_RIGHT_COLS or right_rows < LEFT_TAIL_MIN_RIGHT_ROWS:",
     "        if False:",
     "裁框左沿切进题干长行：收到文字与图之间（含四个反例）"),
    ("关·77 左沿修边没接线", FIG,
     '        tailed = _trim_left_text_tail(trimmed, page_boxes.get(c["page"], []),\n'
     '                                      c["src"], np, DPI_PROBE / 72.0)',
     "        tailed = trimmed",
     "左沿文字尾巴接线检查（left-tail-trim）"),
    ("关·77 矮块图长进上一题题干", FIG,
     "        if len(t) >= 15 or (bx1 - bx0 >= 80.0 and by1 - by0 >= 10.0):\n"
     "            return True",
     "        if False:\n"
     "            return True",
     "矮图上下沿切在图形中间：沿连续墨迹长回真边（含四个反例）"),
    ("关·77 高图也长回真边（吞掉上一题）", FIG,
     "BAND_GROW_MAX_H_PT = 60.0",
     "BAND_GROW_MAX_H_PT = 1000.0",
     "矮图上下沿切在图形中间：沿连续墨迹长回真边（含四个反例）"),
    ("关·77 长回真边没接线", FIG,
     '        regrown = _grow_small_figure_over_band(tailed, c["src"],\n'
     '                                               page_boxes.get(c["page"], []),\n'
     '                                               np, DPI_PROBE / 72.0)',
     "        regrown = tailed",
     "矮图长回真边接线检查（band-grow）"),
    ("关·77 收底沿不看上题自己的墨（底框线被削）", FIG,
     "                floor = _content_bottom_outside(a, b)",
     "                floor = None",
     "收上题底沿按上题自己的墨停（含两个反例）"),
    ("关·77 上题墨不避开重叠区（下题图算上题内容）", FIG,
     "            ink[:, c0 - px0:c1 - px0] = False",
     "            pass",
     "收上题底沿按上题自己的墨停（含两个反例）"),
    # ---- 第二十三轮：并排两小题的竖缝/拆框/回吸，页边点线，尺寸标注 ----
    ("关·页边点线不掏（装饰线与图连成一片）", FIG,
     "    h, w = gray.shape\n    out: list[tuple[int, int]] = []\n"
     "    sides: list[tuple[str, int, int]] = []",
     "    return []\n    h, w = gray.shape\n    out: list[tuple[int, int]] = []\n"
     "    sides: list[tuple[str, int, int]] = []",
     "页边点线装饰整列掏掉（含五个反例）"),
    ("旧·内侧只扫 30pt（贴边的表格线看不见，装饰线被误掏）", FIG,
     "    scan = int(EDGE_DECOR_BAND_PT * 2.0 * k)",
     "    scan = int(EDGE_DECOR_BAND_PT * k)",
     "整题截图要在削题干行之前丢"),
    ("松·页边线内侧有墨也算孤立", FIG,
     "and gap_pt >= MARGIN_RULE_GAP_PT ",
     "and True ",
     "页边点线装饰整列掏掉（含五个反例）"),
    ("松·页边线外侧有墨也算装饰", FIG,
     "if (int(outer.max()) < need if outer.size else True) ",
     "if (True) ",
     "页边点线装饰整列掏掉（含五个反例）"),
    ("松·页边线不限宽（宽表格线也掏）", FIG,
     "            if width_pt <= MARGIN_RULE_MAX_PT and on_edge:",
     "            if width_pt <= 1000.0 and on_edge:",
     "页边点线装饰整列掏掉（含五个反例）"),
    ("旧·被上沿切穿的图注不吸回（只剩半截字）", FIG,
     "        if by1 < y0 - 0.5:\n            continue",
     "        if by1 < y0 - 0.5 or by1 > y0 + 0.5:\n            continue",
     "并排图拆框：切穿图注回吸 + 最终修边夹回竖缝（含三个反例）"),
    ("松·只看每列墨量（稀疏虚线带被当贯通缝）", FIG,
     "        if frac > 0.30 or float(cs[a:b].mean()) > tol * 0.5:\n"
     "            continue",
     "        if False:\n            continue",
     "并排两小题：配对与贯通空白竖缝（含六个反例）"),
    ("松·缝一边太窄也拆（图边留白当缝）", FIG,
     "        if half.shape[1] / k < SIDE_PAIR_HALF_MIN_PT:\n            return None",
     "        if False:\n            return None",
     "并排两小题：配对与贯通空白竖缝（含六个反例）"),
    ("松·不同大题同高也配成并排", FIG,
     "        if not sa or sa != sb:\n            continue",
     "        if not sa:\n            continue",
     "并排两小题：配对与贯通空白竖缝（含六个反例）"),
    ("关·并排图不拆（两幅图并成一张给别人）", FIG,
     "    pairs = _side_pairs(spans)\n    if not pairs:\n        return cands",
     "    pairs = []\n    if not pairs:\n        return cands",
     "并排图拆框：切穿图注回吸 + 最终修边夹回竖缝（含三个反例）"),
    ("关·拆完的图不夹回竖缝（左图长进右题）", FIG,
     '    sp = cand.get("side_pair") or {}',
     "    return rect\n" + '    sp = cand.get("side_pair") or {}',
     "并排图拆框：切穿图注回吸 + 最终修边夹回竖缝（含三个反例）"),
    ("关·右图不夹回竖缝（只夹左边）", FIG,
     "    if qi == qb:\n        return (max(rect[0], sx + 0.5), rect[1],"
     " rect[2], rect[3])",
     "    if qi == qb:\n        return rect",
     "并排图拆框：切穿图注回吸 + 最终修边夹回竖缝（含三个反例）"),
    ("关·只含尺寸标注的题干不清（页面上留 24cm 残渣）", FIG,
     '                if _DIM_LABEL_RE.match(str(t or "")):',
     "                if False:",
     "图里只剩尺寸标注：题干可清空（含三个反例）"),
    # ── 本轮 P5 实测：算式整题截图又带上了大题标题/页脚/半页空白；
    #    题干清空后还硬印一个 "20."，版面一挤就变成页底孤儿题号 ──
    ("关·算式整题截图收紧（标题/页脚/空白全回来）", FIG,
     "        if calc_block:",
     "        if False:",
     "算式整题截图切掉大题标题/页脚/空白（含看图题反例）"),
    ("旧·整题原图仍印题号（页底孤儿 + 重复）", AWR,
     "        if (whole_span and not stem) or whole_q:",
     "        if False:",
     "整题原图已含题号：不许再印孤立的题号"),
    # ── P5 Q24 实测：两个班的成绩表被 OCR 横着串成一行行数字，只裁到下半截
    #    表格时学生看不到原始成绩；页脚也被扫进整题截图 ──
    ("关·统计表横串兜底（留下串行文字 + 半截表）", FIG,
     "        table_garbage = _has_interleaved_table(q)",
     "        table_garbage = False",
     "统计表横串：整题截图 + 清空串行 + 切页脚"),
    ("旧·跨段兜底也当整题原图（另一段文字被藏）", FIG,
     '        made_imgs[0]["whole_question"] = covered_all',
     '        made_imgs[0]["whole_question"] = True',
     "统计表横串：整题截图 + 清空串行 + 切页脚"),
    ("关·整题截图切页脚（六年级数学第6页共8页进图）", FIG,
     "            x0, y0, x1, y1 = _trim_page_footer(\n"
     '                (x0, y0, x1, y1), boxes_g, float(gsrc.height_pt))',
     "            pass",
     "统计表横串：整题截图 + 清空串行 + 切页脚"),
    # P5 Q25 实测：小问号（1）（2）（3）全被图吞掉，只剩三段残句 + 图跑到下一页。
    ("关·小问号全丢仍用残句（图与题干分家）", FIG,
     "        lost_subq = _lost_subq_numbers(q)",
     "        lost_subq = False",
     "小问号全丢：整题截图代替三段残句"),
    # P5 Q25 实测：只剩（1）（3）两问，旧的"少于 2 个"判据放过，图里的（2）
    # 让题干顺序变成 1→3→2。缺任意一问都必须整题截图。
    ("旧·只数小问号个数（缺第2问仍放过）", FIG,
     "    return bool(src_nums - have)",
     "    return len(have) < 2",
     "缺一个小问号：整题截图（含三个反例）"),
    # P6 五 Q1 实测：3/10、4/10 被读成 "310""410"，题干条件直接错（P1）。
    ("关·拍平分数不兜底（310/410 仍当条件）", FIG,
     "            or lost_subq or flat_fraction or inline_gap or lost_fraction \\",
     "            or lost_subq or False or inline_gap or lost_fraction \\",
     "分数被拍平 310/410：整题截图（含三个反例）"),
    # P3 判断 Q3 卡片被吞 / P2 判断 Q5 分数拍平成 "101"：
    # 没有图的题要把整题截图当题干，已有图的题不许被顶掉。
    ("关·行内长空格不兜底（卡片被吞仍当正文）", FIG,
     "        inline_gap = bool(no_img and _INLINE_GAP_RE.search(text))",
     "        inline_gap = False",
     "行内卡片被吞/分数被拍平：换整题截图（含两个反例）"),
    ("关·拍平分数不兜底（1/10 仍读成 101）", FIG,
     "        lost_fraction = bool(no_img and _LOST_FRACTION_RE.search(\n"
     "            \"\\n\".join(str(x) for x in (q.get(\"source_lines\") or []))))",
     "        lost_fraction = False",
     "行内卡片被吞/分数被拍平：换整题截图（含两个反例）"),
    ("关·算式符号被读成字母不兜底（X/O 仍当正文）", FIG,
     "        op_garble = bool(no_img\n"
     "                         and len(_OPERATOR_GARBLE_RE.findall(text)) >= 2)",
     "        op_garble = False",
     "行内卡片被吞/分数被拍平：换整题截图（含两个反例）"),
    ("一处 X 也当符号错（正常乘法写法被整题截图顶掉）", FIG,
     "        op_garble = bool(no_img\n"
     "                         and len(_OPERATOR_GARBLE_RE.findall(text)) >= 2)",
     "        op_garble = bool(no_img\n"
     "                         and len(_OPERATOR_GARBLE_RE.findall(text)) >= 1)",
     "行内卡片被吞/分数被拍平：换整题截图（含两个反例）"),
    ("关·行内缺口不清字（残句和原图并排印）", FIG,
     "                or flat_fraction or inline_gap or lost_fraction or op_garble \\\n"
     "                or lost_box:",
     "                or flat_fraction or False or lost_fraction or op_garble \\\n"
     "                or lost_box:",
     "行内卡片被吞/分数被拍平：换整题截图（含两个反例）"),
    # ── P4 六 Q4 实测：整题截图在第 3 页页底截断，第 4 页的坐标纸和
    #    (1)(2)(3) 没有 span 认领，导出时整页丢失 ──
    ("关·页底整题截图不补续页（统计图下半页丢了）", FIG,
     "        if covered_all and last_src is not None \\\n"
     '                and last_y1 >= float(last_src.height_pt) - 2.0:',
     "        if False:",
     "页底整题截图要补下一页续图（含三个反例）"),
    ("过·下一页有别的题也补续图（下一题被吞）", FIG,
     "            if next_src is not None and not other_q and not q_next:",
     "            if next_src is not None:",
     "页底整题截图要补下一页续图（含三个反例）"),
    # ── 用户口径：复杂题跨栏/跨页时宁可整块原卷，也不许多张碎图丢内容 ──
    ("关·复杂题只裁第一段（跨栏题后半段丢失）", FIG,
     "        for (gp, gcol), grp in sorted(groups.items()):",
     "        for (gp, gcol), grp in sorted(groups.items())[:1]:",
     "复杂题跨栏跨页：每栏一张完整图（含缺页反例）"),
    ("松·缺一栏也算整题原图（残段文字被清空）", FIG,
     "        covered_all = (not missing_group) and len(made_imgs) == len(groups)",
     "        covered_all = bool(made_imgs)",
     "复杂题跨栏跨页：每栏一张完整图（含缺页反例）"),
    ("过·跨栏整题图串成一栏（右栏并进左图）", FIG,
     '            groups.setdefault((int(o.get("page") or 0),\n'
     '                               int(o.get("col") or 0)), []).append(o)',
     '            groups.setdefault((int(o.get("page") or 0), 0), []).append(o)',
     "复杂题跨栏跨页：每栏一张完整图（含缺页反例）"),
    # ── 统计图题（P4 六 Q4）：数据表 + 下一页空白坐标纸必须整块给 ──
    ("关·统计图不换整块截图（只剩数据表，空白坐标纸丢失）", FIG,
     "        chart_gap = draw_chart and any(",
     "        chart_gap = False and any(",
     "画统计图：数据表+空白坐标纸整块截图（含反例）"),
    ("关·统计图截图退回文字区宽（纵轴刻度/图例被切）", FIG,
     "            if draw_chart:\n",
     "            if False:\n",
     "画统计图：数据表+空白坐标纸整块截图（含反例）"),
    ("关·统计图不清 OCR 文字/小问（网页与原图重复一遍）", FIG,
     "        if draw_chart and covered_all:",
     "        if False and covered_all:",
     "画统计图：数据表+空白坐标纸整块截图（含反例）"),
    # ── 方框被 OCR 吞掉的比较题（P2 填空 Q8）：碎片图必须换整题原图 ──
    ("关·方框丢失的填写题不兜底（②读成另一道乘法）", FIG,
     '            lost_box_gap = lost_box and not _images_cover_span(q["images"], s)',
     "            lost_box_gap = False",
     "方框被 OCR 吞掉的比较题换整题截图（含三个反例）"),
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
    if os.path.isdir(BACKUP):
        print("★发现上次异常退出留下的变异备份（源码可能还是坏的）。先运行：\n"
              "    py -3.11 tests/recover_mutations.py\n"
              "再重跑本门禁。为防叠加，本次不执行。")
        return 1
    orig = {p: open(p, "rb").read() for p in (FIG, LNS, RUL, AWR)}
    # 锚点预检：每条变异都要跑一遍 115 个测试，跑到第 N 条才发现某个旧串
    # 已经过期（源码在上一轮被改过）＝白等好几分钟。先把 256 条全查完再开跑。
    stale = [(name, orig[path].count(old.encode("utf-8")))
             for name, path, old, new, want in cases]
    stale = [(n, c) for n, c in stale if c != 1]
    # 插入型变异（new = old + 插入行）在替换后 old 仍然存在，光数 old 查不出
    # "上次强杀留下的 return False"。干净源码里 new 整串必须一次都不出现。
    for name, path, old, new, want in cases:
        if old in new and orig[path].count(new.encode("utf-8")):
            stale.append((name, -orig[path].count(new.encode("utf-8"))))
    if stale:
        for n, c in stale:
            print("★锚点过期/已残留：%s（%d）" % (n, c))
        print("\n0/%d：锚点没过预检，一条测试都没跑" % len(cases))
        return 1
    os.makedirs(BACKUP, exist_ok=True)
    for p in orig:
        open(os.path.join(BACKUP, os.path.basename(p)), "wb").write(orig[p])
    missed = []
    try:
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
    finally:
        # 正常/异常退出一律还原；被强杀时这段不执行，备份留到下次恢复。
        for p, raw in orig.items():
            open(p, "wb").write(raw)
        shutil.rmtree(BACKUP, ignore_errors=True)

    print("\n%d/%d 处退回旧行为被抓到" % (len(cases) - len(missed), len(cases)))
    if missed:
        print("没抓到：" + "、".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
