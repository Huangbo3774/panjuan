# -*- coding: utf-8 -*-
"""成品审计：不问"裁了几张图"，只问"这份卷子的每道题还能不能正常做"。

【做不了】级（必须清零，每条都给题号和证据）
  断号     一个大题里 1、2、4 少了 3 → 有题整道丢了
  空题干   题文为空或只剩标点
  缺图     题干明写"看图/示意图/下面"，可这道题（含上一题共享）一张图都没有
  括号残缺 填空缺半边括号，孩子不知道往哪儿写（补不回来的必须已标待校对）
  题型不符 选择题没选项 / 填空题没空位
【做得别扭】级（尽量清零）
  切边     裁图框外紧贴一片【不是文字的墨】→ 图被切掉一块
  串题     这道题的裁框盖住了【同一页另一道题】的文字行 → 图片和题目不对应
  含题干   裁框把整句题干框进去 → 图里混着题目文字
  题型可疑 题干明写"填序号/选一选/选出"，题型却不是 choice（选项多半是图片，
            OCR 读不到 A/B/C/D）。仍可作答，但校对页要看一眼。

用法：
  py -3.11 tests/audit_papers.py                    不给参数＝跑 samples/private 全部
  py -3.11 tests/audit_papers.py "D:/我的试卷"      给目录就跑整个目录
  py -3.11 tests/audit_papers.py --no-render        只算不渲染
产物：var/_audit/<卷名>_出卷_p<n>.png —— 逐页成品图，人眼逐页复核用
退出码：还有【做不了】级问题 = 1（可当门禁），否则 0。
"""
from __future__ import annotations

import inspect
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import cv2                                                       # noqa: E402
import numpy as np                                               # noqa: E402
import pymupdf                                                   # noqa: E402

from app.extractor import lines as L                             # noqa: E402
from app.extractor.figures import (find_figures, page_source_from_pdf,   # noqa: E402
                                   page_source_from_image,
                                   strip_text_inside_figures, apply_graphic_notes,
                                   fold_figure_preamble_questions,
                                   residue_covered, box_text_patterns,
                                   RESIDUE_KEEP_FIRST_CHARS)
from app.extractor.rules import (extract, flatten_questions, mark_image_options,
                                 CHOICE_CUE, is_furniture_text)  # noqa: E402
from app.layout.options import LayoutOptions                     # noqa: E402
from app.papers.answer_writer import render_answers_pdf          # noqa: E402

OUT = os.path.join(ROOT, "var", "_audit")
K = 100 / 72.0
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

FIG_CUE = re.compile(
    r"如图|看图|右图|左图|下图|上图|上面的图|下面的图|示意图|钟面|数轴|方格|格子图|"
    r"连一连|涂一涂|标一标|在图上|图上的|画一画|照样子|下面各图|这排|这列|观察图片|图片中|"
    r"结合图片|图片上")
# ── 材料类型（人工分类）──────────────────────────────────────────────
# 配图这几把尺（切边/漏块/含题干/残渣）回答的是"印刷卷上的图形有没有裁全"。
# 手写作业照片上，笔画本身就是大面积墨迹，这几把尺没有适用对象：
#   数学作业.jpeg 是一页红笔手写练习（人眼核对 2026-10-20），5 张"配图"全是
#   笔迹块，3 条"漏块"是同一行笔迹在框外——不是漏图。
# 审计照旧把证据列出来，但记在"不适用"里、不计入缺陷：既不静默吞掉警告，
# 也不把一张手写照片冤枉成裁图缺陷。新加材料默认按印刷卷审，人眼确认手写后再登记。
MATERIAL_CLASSES = {
    "数学作业.jpeg": {
        "kind": "handwritten",
        "note": "红笔手写练习本照片；配图/切边/漏块类判据不适用（人眼核对 2026-10-20）",
    },
}


def apply_material_class(kind: str, clip, leak, bleed, stem_in, residue):
    """手写材料 → 配图类证据转"不适用"，不计缺陷；印刷卷原样返回。

    返回 (clip, leak, bleed, stem_in, residue, na)。na 只装证据、不装判决：
    报告里照样逐条列出，读者能自己判断，也不会被算进"做不了"。
    """
    if kind != "handwritten":
        return clip, leak, bleed, stem_in, residue, {}
    na = {"切边": clip, "漏块": leak, "串题": bleed,
          "含题干": stem_in, "题干残渣": residue}
    return [], [], [], [], [], na


def material_kind(path: str) -> str:
    """文件名 → 材料类型；未登记的按印刷卷审（默认不许放行）。"""
    return (MATERIAL_CLASSES.get(os.path.basename(path)) or {}).get("kind") or "print"


def reclassify_material(path: str, clip, leak, bleed, stem_in, residue):
    """audit() 用的一个口子：按文件名判材料类型，再决定证据怎么记。"""
    return apply_material_class(material_kind(path), clip, leak, bleed,
                                stem_in, residue)


def clear_stale_pages(out_dir: str, name: str) -> int:
    """渲染前清掉这份材料上一次的逐页图，只认 `<name>_出卷_p<数字>.png`。

    不清会怎样（本轮实测）：达标B 当前只出 2 页，目录里还躺着上一版的 p3；
    人眼复核把旧 p3 当成本版成品，差点把已经修好的图文分离判成没修。
    只删本材料的同名页：别的材料的成品、同名的 .jpg/.pdf 都不动。
    """
    pat = re.compile(r"^" + re.escape(name) + r"_出卷_p\d+\.png$")
    n = 0
    for f in os.listdir(out_dir):
        if pat.match(f):
            os.remove(os.path.join(out_dir, f))
            n += 1
    return n
# ⚠️ "路线图 / 平面图 / 统计图"这三个词【可能是题目在讲的知识点】，不是"看着那张图作答"：
#    "路线图通常是按照上北下南…绘制的""路线图中不需要有（）"——这类题压根没有配图，
#    把它们报成"缺图"，尺就一直在喊狼来了（实测两份综合实践卷各误报 1—2 条）。
#    所以它们只有再配上"下面/这幅/该图"这种指示词时才算缺图。
FIG_TOPIC = re.compile(r"路线图|平面图|统计图|线路图")
FIG_DEICTIC = re.compile(r"下面|上面|这幅|这张|该图|图中的|图上的|右边的|左边的")
STEMISH = re.compile(r"[。；]|（\s*）|\(\s*\)|^\d+[、.．]|^[（(]\d+[）)]")
ONLY_PUNCT = re.compile(r"^[\s（）()。、，,.．:：;；—…·\d]*$")


def load(path: str) -> dict:
    """一份材料 → 行 + 可裁的页面源。PDF 逐页路由；照片走 OCR。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        r = L.annotated_lines_from_pdf(path, work_dir=os.path.join(OUT, "_ocr"))
        n = pymupdf.open(path).page_count
        srcs = {i: page_source_from_pdf(path, i) for i in range(1, n + 1)}
    elif ext in IMG_EXT:
        r = L.lines_from_image(path)
        srcs = {1: page_source_from_image(path, 1)}
        n = 1
    else:
        return {}
    r["sources"] = {k: v for k, v in srcs.items() if v}
    r["n_pages"] = n
    return r


def _run_len(mask_row) -> int:
    best = run = 0
    for v in mask_row:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def clipped_sides(src, rect, page_boxes, pad_pt=6.0, min_px=45, min_run=18,
                  other_crops=()):
    """裁图框四条边【外侧】贴着多少非文字墨。返回 [(边, 墨px)]。

    ⚠️ 必须先把【别的题已经裁走的图】从这条外边带里挖掉：两张图上下紧挨着时
       （真实卷：周末作业 第 1、2 题的两幅格子图、综合实践单元(1) 第 3、4 题），
       下一张图的墨会贴在上一张裁框外面，尺就报"切边"—— 报的是邻题的图，
       不是被切掉的半张图。九条"切边"里七条是这么来的。
    """
    x0, y0, x1, y1 = [v * K for v in rect]
    p = pad_pt * K
    H, W = src.gray.shape
    out = []
    for side, (bx0, by0, bx1, by1) in {
        "上": (x0, y0 - p, x1, y0 - 1), "下": (x0, y1 + 1, x1, y1 + p),
        "左": (x0 - p, y0, x0 - 1, y1), "右": (x1 + 1, y0, x1 + p, y1),
    }.items():
        bx0, by0 = max(0, int(bx0)), max(0, int(by0))
        bx1, by1 = min(W, int(bx1)), min(H, int(by1))
        if bx1 - bx0 < 2 or by1 - by0 < 2:
            continue
        ink = src.gray[by0:by1, bx0:bx1] < src.ink_thr
        if not ink.any():
            continue
        _mask_text_boxes(ink, bx0, by0, page_boxes)
        for (ox0, oy0, ox1, oy1) in other_crops:
            a, b = max(int(ox0 * K) - bx0, 0), min(int(ox1 * K) - bx0, ink.shape[1])
            c, d = max(int(oy0 * K) - by0, 0), min(int(oy1 * K) - by0, ink.shape[0])
            if b > a and d > c:
                ink[c:d, a:b] = False
        n = int(ink.sum())
        if n < min_px or max((_run_len(row) for row in ink), default=0) < min_run:
            continue
        out.append((side, n))
    return out


EDGE_DEAD_PT = 24.0       # 页面最外侧这条带里的是页边花纹/装订线/密封线，不是题目内容
FURNITURE_BLOCK_PAD_PT = 12.0  # 家具行色块与字框的上下允许距离（见 _mask_text_boxes）
NEAR_BAND_PT = 6.0        # 裁框内侧多宽算"框内的墨"
NEAR_RATIO_MIN = 0.5      # 框外的墨至少有一半行要跟框内边缘的墨对齐，才算被切断的延续
RULE_MIN_W_PT = 40.0      # 1px 高、40pt 以上的横条是印刷横线/答题线，不是图形
LEAK_MIN_COMP_PX = 40     # 单个连通域小于这个数＝句号/竖弯钩的碎墨，不是被切掉的图形


def _mask_text_boxes(ink, bx0: int, by0: int, page_boxes) -> None:
    """把边带里的【文字行】挖掉；家具行的彩色底整块挖掉。

    为什么家具行要单独处理：周末作业(1) p1 第 4 题 / p2 第 3 题裁框下面
    紧贴"智慧加油站"绿色横幅 —— OCR 只读到反白的那 5 个字，绿色圆角底比字框
    上下左右各大 4–6pt。只按字框挖，剩下那圈底色就被当成"图被切掉一块"，
    实测两条切边全是这块横幅（var/_probe_edge.py 取证：带内 956/994px 墨
    全部落在一个连通域里，横向 70.6–164.9 / 33.8–129.6，正是横幅的圆角底）。

    ⚠️ 试过"家具字框统一外扩 12pt 再挖"：那会把紧贴横幅的真图残墨一起盖住，
       等于给切边尺开了个 12pt 的盲区。现在只挖【横向 ≥50% 落在该家具字框里】
       的那一个连通域 —— 彩色底正好是这个形状；旁边的图块横向大部分在字框外，
       仍然照报（自检里有正反例）。
    普通文字行不放宽：那是题面文字，只按原框挖。
    """
    furn: list[tuple[float, float, float, float]] = []
    for tb in page_boxes:
        tx0, ty0, tx1, ty1 = [float(v) for v in tb[:4]]
        if is_furniture_text(str(tb[4] if len(tb) > 4 else "")):
            furn.append((tx0, ty0, tx1, ty1))
        a = max(int(tx0 * K) - bx0, 0)
        b = min(int(tx1 * K) - bx0, ink.shape[1])
        c = max(int(ty0 * K) - by0, 0)
        d = min(int(ty1 * K) - by0, ink.shape[0])
        if b > a and d > c:
            ink[c:d, a:b] = False
    if not furn or not ink.any():
        return
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    for i in range(1, n):
        x, y, w, h, _area = [int(v) for v in stats[i]]
        if w <= 0 or h <= 0:
            continue
        cx0, cx1 = (bx0 + x) / K, (bx0 + x + w) / K
        cy0, cy1 = (by0 + y) / K, (by0 + y + h) / K
        for (tx0, ty0, tx1, ty1) in furn:
            if cy1 < ty0 - FURNITURE_BLOCK_PAD_PT or cy0 > ty1 + FURNITURE_BLOCK_PAD_PT:
                continue
            ov = min(cx1, tx1) - max(cx0, tx0)
            # 宽度也卡死：色块只会比字宽出圆角那一圈；连接域被右侧图块拉长后
            # 横向占比仍可能过 50%，只靠占比会把旁边的真图一起吞掉。
            if (ov >= 0.5 * (cx1 - cx0)
                    and (cx1 - cx0) <= (tx1 - tx0) + 2 * FURNITURE_BLOCK_PAD_PT):
                ink[y:y + h, x:x + w] = False
                break


def row_leaks(src, rect, page_boxes, other_crops=(), furniture=(), reach_pt=70.0,
              min_px=45, min_run=3):
    """图框【左右两侧的同一行上】还剩多少非文字墨 —— 中间隔着空白也算漏。

    和 `clipped_sides` 的分工：那条尺只看框外 6px 的【贴边】墨，
    看不见"式子被从中间截断"这种 —— 真实卷（第三单元练习题 第 1 页第 4 题
    「★＋★＋★＋★＝20」）裁框停在 x=407.6，式子末尾的"（   ）"在 x=434，
    中间隔着 26pt 空白 → 切边报 0，可孩子看到的算式少了括号和得数。

    三条护栏，一条都不能少（少一条就是把邻题的图报成自己的漏块）：
      · 只看【同一行】：横条带就是裁框自己的 y 区间，不往上往下扩；
      · 挖掉 OCR 文字行：那一行本来就是字，不是被切掉的图；
      · 挖掉【别的题已经裁走的图】：邻题的图不该算在这道题头上。
    ⚠️ 门槛是量出来的，不是猜的：被切掉的那半个括号，条带里实测 48px 墨。
      所以 min_px 只能取 45（第一版照抄切边尺的 60px → 对它要治的那个缺陷【完全瞎】，
      把修复关掉也报不出第 4 题；min_run 也只能到 3px，竖弧没有长横画）。
    """
    x0, y0, x1, y1 = [v * K for v in rect]
    reach = reach_pt * K
    H, W = src.gray.shape
    out = []
    for side, (bx0, bx1) in (("左", (max(0, int(x0 - reach)), int(x0) - 1)),
                             ("右", (int(x1) + 1, min(W, int(x1 + reach))))):
        by0, by1 = max(0, int(y0)), min(H, int(y1))
        if bx1 - bx0 < 3 or by1 - by0 < 3:
            continue
        ink = src.gray[by0:by1, bx0:bx1] < src.ink_thr
        if not ink.any():
            continue
        _mask_text_boxes(ink, bx0, by0, page_boxes)
        # furniture = 被丢弃的页边 margin 单字（密封线/装订栏）：不是图的墨。
        for (ox0, oy0, ox1, oy1) in list(other_crops) + list(furniture):
            a, b = max(int(ox0 * K) - bx0, 0), min(int(ox1 * K) - bx0, ink.shape[1])
            c, d = max(int(oy0 * K) - by0, 0), min(int(oy1 * K) - by0, ink.shape[0])
            if b > a and d > c:
                ink[c:d, a:b] = False
        # 裁框内侧边缘条：判断框外的墨是不是和框内的墨在同一行上接得上。
        # 三条护栏都来自 26 条真卷警告的逐条取证（var/_leaks_all_v124c.txt）：
        #  · 页边 32pt 内的墨 = 花纹边/装订线/密封线（周末作业 4 条、第三单元 4 条）；
        #  · 离框 >10pt 且与框内边缘对不上行的墨 = 邻栏文字/答题横线（q8/q26/q29）；
        #  · 1px 高、40pt 以上的横条 = 印刷横线，不是被切掉的图形。
        # 保留的是对得上行的真漏块（q31 的 "=16," 段，ratio 0.56）。
        ew = max(2, int(NEAR_BAND_PT * K))
        ex0, ex1 = ((int(x0), int(x0) + ew) if side == "左"
                    else (int(x1) - ew, int(x1)))
        ex0, ex1 = max(0, ex0), min(W, ex1)
        edge_rows = set()
        if ex1 > ex0:
            edge_ink = src.gray[by0:by1, ex0:ex1] < src.ink_thr
            edge_rows = set(np.where(edge_ink.any(axis=1))[0].tolist())
        n_lab, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
        keep = np.zeros_like(ink)
        for i in range(1, n_lab):
            cx, cy, cw, ch, area = [int(v) for v in stats[i]]
            # 综合实践单元 第24题右侧 116px 全是这种 11×4/12×4 的碎墨：
            # 「南面光照较少，故称“阴”。」的句号和竖弯钩比 OCR 行框低 2px，
            # 是文字不是图。真漏块（第三单元 q31 的 "=16," 段）是 27×9/145px。
            if area < LEAK_MIN_COMP_PX:
                continue
            gx0, gx1 = cx + bx0, cx + bx0 + cw
            gap = (int(x0) - gx1) if side == "左" else (gx0 - int(x1))
            # 只看【这一侧】的纸边：左带里的墨从左边缘开始，右带里的墨碰到右边缘。
            if ((side == "左" and gx0 < EDGE_DEAD_PT * K)
                    or (side == "右" and gx1 > W - EDGE_DEAD_PT * K)):
                continue
            if ch <= 1 and cw >= RULE_MIN_W_PT * K:
                continue
            # 竖排密封线/虚线：断成一截截的印刷线，不是被切掉的图。
            # 达标B q8 实测：写作格右框线 820pt 已收进框，右侧 21pt 处 843pt
            # 的密封虚线被框内竖框线带着"行对齐"判据，13 截共 424px 全留下。
            # 真图边界是一条贯穿整框的长线（ch 远大于 60pt），不会被这条误伤。
            # ⚠️ 不能再要求"离框 >10pt"：裁剪收窄到密封字左边之后，
            #    虚线离框只有 4pt（达标B q8 实测），带 gap 条件等于放它进来。
            #    真图边界是贯穿整框的长线（ch 远大于 60pt），不在这一档。
            #    furniture 还会把密封单字整块挖掉（那是被丢弃的 margin 字）。
            if cw <= 3 * K and 6 <= ch <= 60 * K:
                continue
            if gap > 10 * K and ch:
                hit = sum(1 for yy in range(ch) if (cy + yy) in edge_rows)
                if hit / ch < NEAR_RATIO_MIN:
                    continue
            keep |= (lab == i)
        n = int(keep.sum())
        if n < min_px or max((_run_len(row) for row in keep), default=0) < min_run:
            continue
        out.append((side, n))
    return out


def overlap(a, b) -> float:
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    area = (b[2] - b[0]) * (b[3] - b[1])
    return (ix * iy) / area if area else 0.0


def answerability(qs) -> list[tuple]:
    """【做不了】级检查：逐题问"拿着这张纸能不能作答"。"""
    bad: list[tuple] = []
    sec_no: dict[str, list[int]] = {}
    for q in qs:
        sec_no.setdefault(str(q.get("section") or ""), []).append(int(q.get("q_no") or 0))
    for sec, nos in sec_no.items():
        have = sorted({n for n in nos if n})
        if not have:
            continue
        for miss in range(have[0], have[-1] + 1):
            if miss not in have:
                bad.append(("断号", 0, f"大题「{sec[:14]}」缺第 {miss} 题（实有 {have}）"))
    for i, q in enumerate(qs):
        t = str(q.get("text") or "").strip()
        no = int(q.get("q_no") or i + 1)
        if not t or ONLY_PUNCT.match(t):
            bad.append(("空题干", no, t[:20]))
            continue
        if (t.count("（") + t.count("(")) != (t.count("）") + t.count(")")) \
                and not q.get("needs_review"):
            bad.append(("括号残缺", no, f"没补也没标待校对：…{t[-22:]}"))
        qt = q.get("qtype")
        if qt == "choice" and len(q.get("options") or []) < 2:
            bad.append(("选择没选项", no, t[:24]))
        if qt == "fill" and not int(q.get("blanks") or 0):
            bad.append(("填空没空位", no, t[:24]))
        if not q.get("images") and wants_figure(t, qt):
            # 共享图不一定挂在【紧挨着】上一题：大题头下的选项行会被切成一道
            # 无题号的伪题，图挂在那道伪题上（综合实践单元(1) 第五大题实测），
            # 真正的第 2 题往上隔两道才是图。同大题内往回看最多 3 道。
            shared = False
            for prev in reversed(qs[max(0, i - 3):i]):
                if prev.get("section") != q.get("section"):
                    break
                if prev.get("images"):
                    shared = True
                    break
            if shared:
                shared = bool(re.search(r"上图|上面|如图|图上的", t))
            if not shared:
                bad.append(("缺图", no, t[:26]))
    return bad


def wants_figure(t: str, qt: str = "") -> bool:
    """这道题是不是【必须看着一张图】才能做。"""
    if FIG_CUE.search(t):
        return True
    return bool(FIG_TOPIC.search(t) and FIG_DEICTIC.search(t))


def type_suspects(qs) -> list[tuple[int, int, str, str]]:
    """题型可疑：题干/大题名在要求"挑一个"，题型却不是 choice。

    为什么需要这把尺：第三单元练习题 第 3 题（自然科普·树叶）四片叶子是【图片选项】，
    OCR 读不到 A/B/C/D，题目被当时的 JUDGE_HINT 里那个光秃秃的「×」判成判断题
    （因为题干算式里有 2×4）—— 做题页只给"对/错"两个单选，孩子没有地方写序号。
    老审计只看"选择题没选项"，对这种"判成了别的题型"完全瞎。

    为什么只列为【做得别扭】而不是硬门禁：这种题现在会保留成 fill/essay，
    孩子还能在空里写序号，题是能做的；把它卡成"做不了"会让整套真实材料永远红灯，
    反而没人再信这盏灯。校对页会挂"待校对"提醒家长补选项/改题型。

    返回 [(题序, 题号, 当前题型, 命中的信号)]。
    """
    out: list[tuple[int, int, str, str]] = []
    for i, q in enumerate(qs):
        qt = str(q.get("qtype") or "")
        if qt == "choice" or q.get("image_options"):
            # 选项图已经挂在题下（mark_image_options 判过有图）→ 不是"选项丢了"。
            continue
        t = str(q.get("text") or "")
        sec = str(q.get("section") or "")
        m = CHOICE_CUE.search(t) or CHOICE_CUE.search(sec)
        if m:
            out.append((i + 1, int(q.get("q_no") or i + 1), qt, m.group(0)))
    return out


def duplicates(qs) -> list[tuple]:
    """同一大题里同一个题号出现两次 = 卷面上多出一道"假题"。

    典型成因（实测：综合实践单元(1).pdf 第四大题）：题号"1"和它的题干之间隔着整张
    平面图，OCR 把图上的房间号读成一行行文字插在中间，于是"1"被前一段文字带走，
    真正的题干又开了一道"1"。孩子卷面上会看到两道第 1 题，其中一道是乱码。
    """
    seen: dict[tuple, int] = {}
    for i, q in enumerate(qs):
        key = (str(q.get("section") or ""), int(q.get("q_no") or 0))
        if not key[1]:
            continue
        seen[key] = seen.get(key, 0) + 1
    return [(sec, no, n) for (sec, no), n in seen.items() if n > 1]


def text_residues(qs, got, span_by_q) -> list[tuple]:
    """题干里还有【整行落在本题配图框内】的字 → 同一句话会印两遍。

    正常流水线会先调 `strip_text_inside_figures` 删掉；这里是独立的第二把尺：
    如果删漏了、或者以后有人把清理那一步关掉，审计必须自己喊出来。

    只按"图内文字出现在题干里"报会误伤同名正文：句子里本来就有「辰辰」，
    地图上的「散通道」又是「紧急疏散通道」的一部分。所以按出现次数算：
    题干里该词的出现次数，必须超过所有【框外行】加起来能解释的次数，才算残渣。
    """
    out: list[tuple] = []
    for qi, imgs in got.items():
        if not (0 <= qi < len(qs)) or not imgs:
            continue
        text = str(qs[qi].get("text") or "")
        rects = [tuple(im["rect"]) for im in imgs if im.get("rect")]
        content_seen = False
        boxes: list[tuple[str, bool]] = []          # (文字, 是否图内候选)
        for b in span_by_q.get(qi, {}).get("text_boxes") or []:
            t = str(b.get("text") or "").strip()
            if not t:
                continue
            bb = (float(b["x"]), float(b["y"]),
                  float(b["x"]) + float(b.get("w") or 0),
                  float(b["y"]) + float(b.get("h") or 0))
            pats = box_text_patterns(t)
            # 起手句按设计保留（见 figures.strip_text_inside_figures），不算残渣；
            # 但它被裁框整行盖住照样由「含题干」那把尺报，不能在这里重复报。
            # ⚠️ 必须是【真的出现在题干里】的那一行才算起手句。大题题头/栏目名
            # 也在 text_boxes 里、且不在题干里；若它抢走豁免，真正的第一句
            # （常被裁框整行盖住）就会被误报成残渣（达标B 第 8 题）。
            if (not content_seen
                    and len(re.sub(r"\s+", "", t)) >= RESIDUE_KEEP_FIRST_CHARS
                    and any(re.search(p, text) for p in pats)):
                content_seen = True
                boxes.append((t, False))
                continue
            boxes.append((t, any(residue_covered(r, bb) for r in rects)))
        # 同一个词可能本来就出现在【没被图盖住】的正文行里：
        # 「辰辰从( )面走来」里的「辰辰」、『紧急疏散通道』里的『散通道』。
        # 只有出现次数超过正文行能解释的那几次，才算真正的图内残渣。
        legit = "\n".join(t for t, cand in boxes if not cand)
        for t, cand in boxes:
            if not cand:
                continue
            pats = box_text_patterns(t)
            hit = max(len(re.findall(p, text)) for p in pats)
            if hit and hit > max(len(re.findall(p, legit)) for p in pats):
                out.append((qi + 1, t[:20]))
                break
    return out


def stem_in_figures(qs, got, span_by_q) -> list[tuple]:
    """裁框把【题干里还在的整句】框进去 → 图里混着题目文字。

    图内标注（对话气泡、地图标签）同样落在框里，但清理那一步已经把
    它们从题干删掉了 —— 题干里没有这行字，就不算"含题干"。
    第 1 行（起手句）按设计保留在题干里，所以被框住时照报。
    """
    out: list[tuple] = []
    for qi, imgs in got.items():
        if not (0 <= qi < len(qs)) or not imgs:
            continue
        # 图形算式的整行原图【必须】含题干文字：图标只有原图能表达，题干里的
        # "如果  =16"本来就是残缺的。这类图由 extractor 用"≥3 个大图标 + = +
        # ≥4 空格缺口"判出来并打上 graphic，不能拿普通配图的含题干尺量它。
        # 其它图照旧——整题截图没有这些特征，不会被这条豁免放走。
        rects = [tuple(im["rect"]) for im in imgs
                 if im.get("rect") and not im.get("graphic")]
        text = str(qs[qi].get("text") or "")
        for bi, b in enumerate(span_by_q.get(qi, {}).get("text_boxes") or []):
            t = str(b.get("text") or "")
            if len(t) < 8 or not STEMISH.search(t):
                continue
            bb = (float(b["x"]), float(b["y"]),
                  float(b["x"]) + float(b.get("w") or 0),
                  float(b["y"]) + float(b.get("h") or 0))
            if not any(overlap(r, bb) >= 0.8 for r in rects):
                continue
            if not any(re.search(p, text) for p in box_text_patterns(t)):
                continue
            out.append((qi + 1, t[:20], "题干首行" if bi == 0 else f"第{bi + 1}行"))
            break
    return out


def selftest() -> list[str]:
    """尺自己要先证明"它会 FAIL"——不然"做不了 0"只说明我把判据写松了。

    每条都是这一轮真实遇到的：正例＝真缺陷必须报，反例＝误报必须不报。
    返回没过的条目（空＝尺还在工作）。
    """
    def q(text, **kw):
        return {"text": text, "q_no": kw.pop("no", 1), "qtype": kw.pop("qt", "essay"),
                "options": kw.pop("opts", []), "blanks": kw.pop("blanks", 0),
                "section": kw.get("sec", "一、填空"), "images": kw.get("imgs") or [],
                "needs_review": kw.get("review", False)}

    def kinds(qs):
        return [k for k, _n, _w in answerability(qs)]

    fails: list[str] = []

    def chk(name, got, want):
        if want is None:
            if got:
                fails.append(f"{name}：尺误报了（got={got}）")
        elif want not in got:
            fails.append(f"{name}：尺没报出【{want}】（got={got}）")

    chk("右图题没图→缺图",
        kinds([q("如右图所示，两名同学玩背靠背夹球跑的游戏。龙龙面向（ ）。")]), "缺图")
    chk("下面…平面图没图→缺图",
        kinds([q("下面是开心小学教学楼2层的平面图，看图回答问题。")]), "缺图")
    chk("路线图是知识点→不该报",
        kinds([q("路线图通常是按照“上北、下（  ）左（  ）右（  ）”来绘制的。",
                 qt="fill", blanks=3)]), None)
    chk("路线图中不需要有什么（选择）→不该报",
        kinds([q("在设计校园路线图时，路线图中不需要有（  ）。", qt="choice",
                 opts=["①路线", "②方向", "③时间"])]), None)
    chk("共享图挂在两道之前的伪题上，题干说上图→不该报",
        kinds([q("①春风小区 ②学校 ③公园 ④医院", no=0, sec="五、解决问题",
                 imgs=[{"rect": [10, 10, 200, 160]}]),
               q("小玉从家出发去学校，描述在图上面。", no=1, sec="五、解决问题"),
               q("在上图中画出小玉上学可能行走的路线。（6分）", no=2,
                 sec="五、解决问题")]), None)
    chk("共享图在两道之前但题干没说上图→仍要报",
        kinds([q("①春风小区 ②学校 ③公园 ④医院", no=0, sec="五、解决问题",
                 imgs=[{"rect": [10, 10, 200, 160]}]),
               q("小玉从家出发去学校。", no=1, sec="五、解决问题"),
               q("请观察图片，画出小玉上学可能行走的路线。（6分）", no=2,
                 sec="五、解决问题")]), "缺图")
    chk("图在上一大题里→不在共享范围，要报",
        kinds([q("上一大题的配图题。", no=1, sec="四、操作",
                 imgs=[{"rect": [10, 10, 200, 160]}]),
               q("在上图中画出小玉上学可能行走的路线。", no=1,
                 sec="五、解决问题")]), "缺图")
    chk("断号（缺第3题）→要报",
        kinds([q("第一题的题干内容。", no=1), q("第二题的题干内容。", no=2),
               q("第四题的题干内容。", no=4)]), "断号")
    chk("题号连续→不该报",
        kinds([q("第一题的题干内容。", no=1), q("第二题的题干内容。", no=2),
               q("第三题的题干内容。", no=3)]), None)
    chk("括号残缺又没标待校对→要报",
        kinds([q("他的前面是（       )，后面是（", qt="fill", blanks=2)]), "括号残缺")
    chk("选择题没选项→要报",
        kinds([q("下面哪个是对的？（  ）", qt="choice")]), "选择没选项")
    chk("填空题没空位→要报",
        kinds([q("这是一道被误判成填空题的解答题。", qt="fill")]), "填空没空位")

    # 重号尺：同一大题里同一个题号出现两次＝卷面上多出一道假题
    d1 = duplicates([q("第一题的题干内容。", no=1), q("乱码行。", no=1),
                     q("第二题的题干内容。", no=2)])
    if not d1:
        fails.append("重号尺：两道第 1 题却没报（这条尺坏了）")
    d2 = duplicates([q("第一题的题干内容。", no=1), q("第二题的题干内容。", no=2),
                     q("第三题的题干内容。", no=3)])
    if d2:
        fails.append(f"重号尺：题号不重复却报了（误报）：{d2}")

    # 切边尺：紧贴裁框下面的墨如果是【邻题已经裁走的图】，不算"这道题被切掉一块"
    from app.extractor.figures import PageSource
    g = np.full((int(200 * K), int(200 * K)), 255, dtype=np.uint8)
    g[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40      # 这道题的图
    g[int(141 * K):int(150 * K), int(20 * K):int(120 * K)] = 40      # 下面那块墨
    src = PageSource(1, 200.0, 200.0, g, lambda rect, out: None)
    mine = (20.0, 100.0, 120.0, 140.0)
    if not clipped_sides(src, mine, []):
        fails.append("切边尺：框外明明有墨却没报（这条尺坏了，报 0 不算通过）")
    if clipped_sides(src, mine, [], other_crops=[(20.0, 141.0, 120.0, 150.0)]):
        fails.append("切边尺：邻题的图被算成了这道题的「切边」（误报）")
    # 栏目横幅：OCR 只读到反白字，彩色圆角底比字框大一圈。这圈底色不是被切掉的图。
    # 正例：家具行字框 + 色块 → 不许报；反例：同一块墨配普通文字行 → 必须报
    # （证明放宽只挂在家具行上，不是把整条切边尺放哑了）。
    g_banner = np.full((int(200 * K), int(200 * K)), 255, dtype=np.uint8)
    g_banner[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40   # 这道题的图
    g_banner[int(141 * K):int(146 * K), int(30 * K):int(112 * K)] = 40   # 横幅色块
    src_b = PageSource(1, 200.0, 200.0, g_banner, lambda rect, out: None)
    banner_box = [(40.0, 143.0, 100.0, 148.0, "智慧加油站")]
    if clipped_sides(src_b, mine, banner_box):
        fails.append("切边尺：栏目横幅的彩色底被算成被切掉的图（误报）")
    plain_box = [(40.0, 143.0, 100.0, 148.0, "下面各题作答")]
    if not clipped_sides(src_b, mine, plain_box):
        fails.append("切边尺：横幅色块套到了普通文字上（真正被切的图不报了）")
    # 横幅旁边连着一块图：不许因为"附近有家具行"就把整块连通域一起盖掉。
    # 这里图块与横幅在带里相连，连通域横向被拉到字宽的 1.5 倍 —— 只卡 50% 占比
    # 会把它整个吞掉（实测：去掉宽度上限这条自检就红）。
    g_frag = g_banner.copy()
    g_frag[int(141 * K):int(146 * K), int(100 * K):int(120 * K)] = 40
    if not clipped_sides(PageSource(1, 200.0, 200.0, g_frag, lambda rect, out: None),
                         mine, banner_box):
        fails.append("切边尺：横幅旁边连着的图块被一起盖掉了（尺变瞎）")

    # 漏块尺：同一行、但【隔着 30pt 空白】的那块墨，切边尺看不见（它只看贴边 6px），
    # 真实卷上这就是"★＋★＝20 被裁成 ★＋★＝"。这条尺必须自己会响。
    g2 = np.full((int(200 * K), int(200 * K)), 255, dtype=np.uint8)
    g2[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40     # 裁下来的图
    g2[int(110 * K):int(130 * K), int(150 * K):int(170 * K)] = 40    # 式子末尾的括号
    src2 = PageSource(1, 200.0, 200.0, g2, lambda rect, out: None)
    if not row_leaks(src2, mine, []):
        fails.append("漏块尺：同一行框外 30pt 的墨没报（这条尺坏了，报 0 不算通过）")
    if clipped_sides(src2, mine, []):
        fails.append("漏块尺的反证失败：贴边 6px 内本来就没墨，切边尺不该跟着响")
    box_cover = [(150.0, 110.0, 170.0, 130.0, "（   ）")]
    if row_leaks(src2, mine, box_cover):
        fails.append("漏块尺：OCR 已经读到、本来就当文字挖掉的行被算成漏块（误报）")
    if row_leaks(src2, mine, [], other_crops=[(150.0, 110.0, 170.0, 130.0)]):
        fails.append("漏块尺：邻题已经裁走的图被算成这道题的漏块（误报）")
    # 页边花纹/装订线：贴着纸边的墨再长也不是这道题被切掉的内容。
    g3 = np.full_like(g2, 255)
    g3[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40
    g3[int(110 * K):int(130 * K), 0:int(8 * K)] = 40
    if row_leaks(PageSource(1, 200.0, 200.0, g3, lambda rect, out: None), mine, []):
        fails.append("漏块尺：纸边花纹被算成漏块（误报）")
    # 与框内边缘对不上行：框外的字是邻栏的，不是框里那块图的延续。
    g4 = np.full_like(g2, 255)
    g4[int(100 * K):int(112 * K), int(20 * K):int(120 * K)] = 40
    g4[int(124 * K):int(136 * K), int(150 * K):int(170 * K)] = 40
    if row_leaks(PageSource(1, 200.0, 200.0, g4, lambda rect, out: None), mine, []):
        fails.append("漏块尺：框外邻栏文字与框内边缘对不上行，仍被报（误报）")
    # 1px 印刷横线：框外的答题横线不是被切掉的图形。
    g5 = np.full_like(g2, 255)
    g5[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40
    g5[int(130 * K):int(130 * K) + 1, int(150 * K):int(200 * K)] = 40
    if row_leaks(PageSource(1, 200.0, 200.0, g5, lambda rect, out: None), mine, []):
        fails.append("漏块尺：框外 1px 印刷横线被算成漏块（误报）")
    # 单个连通域 <40px 的碎墨（句号/竖弯钩）不许凑成漏块：六个 5×5px 的点
    # 合计 150px，已经超过 min_px=45，全靠 LEAK_MIN_COMP_PX 挡住。
    # 同一位置换成一块 12×12px 的实墨必须报 —— 证明上一句不是"尺坏了"（阴性对照有效）。
    g6 = np.full_like(g2, 255)
    g6[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40
    for j in range(6):
        x0 = int(121.0 * K)
        y0 = int((105 + j * 5) * K)
        g6[y0:y0 + 5, x0:x0 + 5] = 40
    if row_leaks(PageSource(1, 200.0, 200.0, g6, lambda rect, out: None), mine, []):
        fails.append("漏块尺：六个句号大的碎墨被算成漏块（误报）")
    g7 = np.full_like(g2, 255)
    g7[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40
    g7[int(115 * K):int(115 * K) + 12, int(121.0 * K):int(121.0 * K) + 12] = 40
    if not row_leaks(PageSource(1, 200.0, 200.0, g7, lambda rect, out: None), mine, []):
        fails.append("漏块尺：12×12px 的实墨块没报（面积下限把真漏块也挡住了）")

    # 页边密封线：被丢弃的 margin 单字（furniture）不是这道题漏的图；
    # 细竖虚线（≤3pt 宽、6–60pt 高）也不是。阴性对照＝同一块墨不给 furniture
    # 时必须报，证明"不报"是因为 furniture 生效，不是尺变瞎。
    g8 = np.full_like(g2, 255)
    g8[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40
    g8[int(105 * K):int(120 * K), int(132 * K):int(142 * K)] = 40     # 密封单字
    src8 = PageSource(1, 200.0, 200.0, g8, lambda rect, out: None)
    if not row_leaks(src8, mine, []):
        fails.append("漏块尺：框外 12pt 的实墨块没报（密封字阴性对照失效）")
    if row_leaks(src8, mine, [], furniture=[(132.0, 105.0, 142.0, 120.0)]):
        fails.append("漏块尺：已丢弃的页边密封字被算成漏块（误报）")
    g9 = np.full_like(g2, 255)
    g9[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40
    g9[int(95 * K):int(145 * K), int(126 * K):int(129 * K)] = 40      # 离框 6pt 的细竖虚线
    if row_leaks(PageSource(1, 200.0, 200.0, g9, lambda rect, out: None), mine, []):
        fails.append("漏块尺：框外 6pt 的细竖虚线被算成漏块（误报）")

    # 题型可疑尺：选项是图片时 OCR 读不到 A/B/C/D，题型会被判成 fill/essay/judge。
    # 正例＝题干明写"填序号"却非 choice；反例＝乘法算式、判断题、真选择题、普通解答。
    ts = type_suspects([q("下面的树叶片数不能用2×4表示的是（  ）。(填序号)",
                          qt="fill", blanks=1)])
    if not ts:
        fails.append("题型可疑尺：题干要求填序号却判成 fill，没报（这条尺坏了）")
    ts = type_suspects([q("2×3=（  ）", qt="fill", blanks=1)])
    if ts:
        fails.append(f"题型可疑尺：乘法算式被当成选择题信号（误报）：{ts}")
    ts = type_suspects([q("对的打√，错的打×。", qt="judge")])
    if ts:
        fails.append(f"题型可疑尺：判断题被报成题型可疑（误报）：{ts}")
    # 反例必须【带着选择题信号而且是 choice】：没有信号的 choice 不报，只说明
    # "这段文字里没有可选信号"，证明不了"choice 会被放行"（变异闸门实测放过一次）。
    ts = type_suspects([q("选出正确的答案（ ）。", qt="choice",
                          opts=["A. 对", "B. 错"])])
    if ts:
        fails.append(f"题型可疑尺：真正的选择题被报（误报）：{ts}")
    ts = type_suspects([q("选择合适的方法计算下面各题。", qt="essay")])
    if ts:
        fails.append(f"题型可疑尺：光有「选择」二字的解答题被报（误报）：{ts}")
    ts = type_suspects([q("根据下图写算式。", qt="essay", sec="二、选一选。")])
    if not ts:
        fails.append("题型可疑尺：大题名是「选一选」却没报（这条尺坏了）")
    # 选项图：有配图时 mark_image_options 要把题标成 image_options，尺不再报"可疑"；
    # 没配图时必须照报 —— 后者才是"选项真的丢了"。
    iq = q("下面树叶中不能用2×4表示的是（  ）。(填序号)", qt="fill", blanks=1,
           imgs=[{"rect": [0.0, 50.0, 200.0, 120.0]}])
    if mark_image_options([iq]) != 1 or not iq.get("image_options"):
        fails.append("图片选项：题干要填序号且有配图，却没标成 image_options（这条尺坏了）")
    if type_suspects([iq]):
        fails.append("图片选项：已标明选项在配图里，题型可疑尺还在报（误报）")
    iq2 = q("下面树叶中不能用2×4表示的是（  ）。(填序号)", qt="fill", blanks=1)
    if mark_image_options([iq2]) or not type_suspects([iq2]):
        fails.append("图片选项：没有配图也放行 —— 真丢选项的题被藏起来了")

    # 题干残渣尺：整行落在【本题】配图框内的字必须报；框外、只压住一半的不许报。
    rq = q("CL            长长", imgs=[{"rect": [0.0, 0.0, 300.0, 200.0]}])
    rg = {0: rq["images"]}
    if not text_residues([rq], rg, {0: {"text_boxes": [
            {"x": 100, "y": 50, "w": 40, "h": 12, "text": "CL 长长"}]}}):
        fails.append("题干残渣尺：整行落在配图框里却没报（这条尺坏了）")
    if text_residues([rq], rg, {0: {"text_boxes": [
            {"x": 500, "y": 50, "w": 40, "h": 12, "text": "CL 长长"}]}}):
        fails.append("题干残渣尺：框外的题干被报成残渣（误报）")
    if text_residues([rq], rg, {0: {"text_boxes": [
            {"x": 280, "y": 50, "w": 40, "h": 12, "text": "CL 长长"}]}}):
        fails.append("题干残渣尺：只压住一半的题干被报成残渣（误报）")
    rq2 = q("观察图片,提出两个能用6×2解决的问题。",
            imgs=[{"rect": [0.0, 0.0, 300.0, 200.0]}])
    if text_residues([rq2], {0: rq2["images"]}, {0: {"text_boxes": [
            {"x": 100, "y": 50, "w": 200, "h": 12,
             "text": "观察图片,提出两个能用6×2解决的问题。"}]}}):
        fails.append("题干残渣尺：按设计保留的起手句被报成残渣（误报）")
    # 裁框上沿削掉一整行地图标注 3.3pt（覆盖率 80%）仍是图内文字 → 必须报；
    # 上沿超出 8pt（只有下半截在图里）→ 是图上方真正的题干行，不许报。
    rq3 = q("观察校园，并记录下操场的四个方向各有什么。 教学楼 活动室 北 北",
            imgs=[{"rect": [0.0, 32.3, 300.0, 200.0]}])
    rg3 = {0: rq3["images"]}
    if not text_residues([rq3], rg3, {0: {"text_boxes": [
            {"x": 20, "y": 0, "w": 200, "h": 14,
             "text": "观察校园，并记录下操场的四个方向各有什么。"},
            {"x": 100, "y": 29, "w": 180, "h": 16,
             "text": "教学楼 活动室 北 北"}]}}):
        fails.append("题干残渣尺：被裁框削掉 3pt 的图内标注行没报（这条尺坏了）")
    if text_residues([rq3], rg3, {0: {"text_boxes": [
            {"x": 20, "y": 0, "w": 200, "h": 14,
             "text": "观察校园，并记录下操场的四个方向各有什么。"},
            {"x": 100, "y": 24, "w": 180, "h": 16,
             "text": "教学楼 活动室 北 北"}]}}):
        fails.append("题干残渣尺：框外半行题干被报成残渣（误报）")
    # 同名正文不能误伤：「辰辰从…」里的「辰辰」是句子自己的；只有多出一份才报。
    rq4 = q("辰辰从( )面走来。", imgs=[{"rect": [0.0, 40.0, 300.0, 200.0]}])
    rg4 = {0: rq4["images"]}
    if text_residues([rq4], rg4, {0: {"text_boxes": [
            {"x": 20, "y": 10, "w": 200, "h": 14, "text": "辰辰从( )面走来。"},
            {"x": 100, "y": 60, "w": 30, "h": 14, "text": "辰辰"}]}}):
        fails.append("题干残渣尺：句子里的同名正文被报成残渣（误报）")
    rq4b = q("辰辰从( )面走来。 辰辰", imgs=[{"rect": [0.0, 40.0, 300.0, 200.0]}])
    if not text_residues([rq4b], {0: rq4b["images"]}, {0: {"text_boxes": [
            {"x": 20, "y": 10, "w": 200, "h": 14, "text": "辰辰从( )面走来。"},
            {"x": 100, "y": 60, "w": 30, "h": 14, "text": "辰辰"}]}}):
        fails.append("题干残渣尺：多出一份的同名图注没报（这条尺坏了）")
    # 大题题头也在 text_boxes 里但不在题干里，不能抢走起手句豁免
    # （达标B 第 8 题：真正的第一句被裁框整行盖住，却被误报成残渣）。
    rq5 = q("每个人都在童年时做过一些有意思的事情。",
            imgs=[{"rect": [0.0, 40.0, 300.0, 200.0]}])
    if text_residues([rq5], {0: rq5["images"]}, {0: {"text_boxes": [
            {"x": 20, "y": 0, "w": 250, "h": 14,
             "text": "六、一起来为童年纪念册添故事吧！按要求写话。（15分）"},
            {"x": 20, "y": 50, "w": 250, "h": 14,
             "text": "每个人都在童年时做过一些有意思的事情。"}]}}):
        fails.append("题干残渣尺：大题题头抢走起手句豁免（第一句被误报）")

    # 含题干尺：图内标注从题干删掉后不许再报；题干里还在的整句被框住必须报。
    s1 = q("小明和小红在玩游戏。", imgs=[{"rect": [0.0, 50.0, 300.0, 120.0]}])
    sb = [{"x": 20, "y": 10, "w": 200, "h": 14, "text": "小明和小红在玩游戏。"},
          {"x": 20, "y": 60, "w": 200, "h": 14, "text": "我站在北面，明明站在南面。"}]
    if stem_in_figures([s1], {0: s1["images"]}, {0: {"text_boxes": sb}}):
        fails.append("含题干尺：图内标签被删后还报（误报）")
    s2 = q("小明和小红在玩游戏。 我站在北面，明明站在南面。",
           imgs=[{"rect": [0.0, 50.0, 300.0, 120.0]}])
    if not stem_in_figures([s2], {0: s2["images"]}, {0: {"text_boxes": sb}}):
        fails.append("含题干尺：题干里还在的整句被图框住却没报（这条尺坏了）")
    # 图形算式的整行原图【必须】含题干（图标只有原图能表达）→ 打 graphic 的那张豁免；
    # 豁免按【图】算，不按题算：同一题里再罩住题干的普通图照报。
    gl = "3. 如果            =16，            =16，那么"
    gt = "如果            =16，            =16，那么            =( )。"
    gb = [{"x": 20, "y": 60, "w": 280, "h": 14, "text": gl}]
    gq = q(gt, imgs=[{"rect": [0.0, 50.0, 300.0, 120.0], "graphic": True}])
    if stem_in_figures([gq], {0: gq["images"]}, {0: {"text_boxes": gb}}):
        fails.append("含题干尺：图形算式整行原图被报成含题干（误报）")
    gq0 = q(gt, imgs=[{"rect": [0.0, 50.0, 300.0, 120.0]}])
    if not stem_in_figures([gq0], {0: gq0["images"]}, {0: {"text_boxes": gb}}):
        fails.append("含题干尺：同一行没打 graphic 时不报（这条尺坏了）")
    gq2 = q(gt, imgs=[{"rect": [0.0, 200.0, 300.0, 260.0], "graphic": True},
                      {"rect": [0.0, 50.0, 300.0, 120.0]}])
    if not stem_in_figures([gq2], {0: gq2["images"]}, {0: {"text_boxes": gb}}):
        fails.append("含题干尺：普通图罩住题干，却因同题有图形算式图被一起豁免（漏报）")
    # 手写材料：配图类证据转"不适用"、不计缺陷；印刷卷一律照算。映射丢了也要报。
    if MATERIAL_CLASSES.get("数学作业.jpeg", {}).get("kind") != "handwritten":
        fails.append("手写材料：数学作业.jpeg 的分类丢了（红笔笔迹会被算成漏块）")
    c0, l0, b0, st0, re0, na0 = reclassify_material(
        os.path.join("samples", "private", "数学作业.jpeg"),
        [("切",)], [("漏",)], [("串",)], [("含",)], [("渣",)])
    if (c0 or l0 or b0 or st0 or re0) or na0.get("漏块") != [("漏",)]:
        fails.append("手写材料：配图类警告没转成不适用证据（会被算进缺陷总数）")
    c1, l1, b1, st1, re1, na1 = reclassify_material(
        os.path.join("samples", "private", "别的卷.pdf"),
        [("切",)], [("漏",)], [], [], [])
    if c1 != [("切",)] or l1 != [("漏",)] or b1 or st1 or re1 or na1:
        fails.append("手写材料：印刷卷也被转成不适用（真缺陷被藏起来）")
    # 直接测 helpers 还不够：audit() 不接这个口子，上面两条照样全绿。查调用点。
    if "reclassify_material(" not in inspect.getsource(audit):
        fails.append("手写材料：audit() 没接 reclassify_material（分类只在自检里成立）")
    # 旧逐页图清理：只删本材料的 p<数字>.png；别的材料、别的扩展名都不动。
    probe = os.path.join(ROOT, "var", "_selftest_stale")
    os.makedirs(probe, exist_ok=True)
    for f in ("甲_出卷_p1.png", "甲_出卷_p10.png", "甲_出卷_p1.jpg",
              "乙_出卷_p1.png", "甲_blank.pdf"):
        open(os.path.join(probe, f), "wb").close()
    n = clear_stale_pages(probe, "甲")
    left = set(os.listdir(probe))
    if n != 2 or left != {"乙_出卷_p1.png", "甲_出卷_p1.jpg", "甲_blank.pdf"}:
        fails.append(f"旧逐页图清理：删了 {n} 个，剩下 {sorted(left)}"
                     f"（应只删本材料的 p<数字>.png）")
    for f in left:
        os.remove(os.path.join(probe, f))
    os.rmdir(probe)
    if "clear_stale_pages(" not in inspect.getsource(audit):
        fails.append("旧逐页图清理：audit() 没接 clear_stale_pages（旧页仍会混进复核目录）")
    return fails


def audit(path: str, render=True) -> dict:
    name = os.path.splitext(os.path.basename(path))[0]
    mat = MATERIAL_CLASSES.get(os.path.basename(path)) or {}
    handwritten = material_kind(path) == "handwritten"
    r = load(path)
    if not r or not r.get("lines"):
        print(f"\n【{name}】没读到任何文本行（跳过）")
        return {}
    res = extract(r["lines"], title=name)
    qs = flatten_questions(res)
    spans = L.spans_for_questions(r["ann"], qs, pages=r.get("pages"),
                                  sections=res.get("sections"))
    fig_dir = os.path.join(OUT, "figs", name)
    # 裁剪件也按"题号+序号"命名，上一版的图会留在同名目录里（实测 q6 有三份，
    # 只有 21:13 那份是本版）。复核时无法凭文件名分辨，渲染前整目录清掉。
    shutil.rmtree(fig_dir, ignore_errors=True)
    rep: list = []
    got = find_figures(r["sources"], spans, fig_dir, report=rep, noise=r.get("noise"),
                       questions=qs)
    for qi, imgs in got.items():
        if 0 <= qi < len(qs):
            qs[qi]["images"] = imgs
    n_res = strip_text_inside_figures(qs, spans, got)
    n_fold = fold_figure_preamble_questions(qs, got, spans)
    apply_graphic_notes(qs, got)
    n_imgopt = mark_image_options(qs)

    by_page: dict[int, list] = {}
    for a in r["ann"]:
        by_page.setdefault(int(a.get("page", 1)), []).append(a)
    boxes = {pg: [(float(a["x"]), float(a["y"]), float(a["x"]) + float(a["w"]),
                   float(a["y"]) + float(a["h"]), str(a.get("text") or ""))
                  for a in items] for pg, items in by_page.items()}
    span_by_q = {int(s["q_index"]): s for s in spans}
    residue = text_residues(qs, got, span_by_q)

    clip, bleed, stem_in, leak = [], [], [], []
    crops_by_page: dict[int, list] = {}
    for q in qs:
        for im in q.get("images") or []:
            crops_by_page.setdefault(int(im["page"]), []).append(tuple(im["rect"]))
    for qi, q in enumerate(qs):
        for im in q.get("images") or []:
            rect = im["rect"]
            page = int(im["page"])
            if page not in r["sources"]:
                continue
            others = [c for c in crops_by_page.get(page, []) if tuple(c) != tuple(rect)]
            c = clipped_sides(r["sources"][page], rect, boxes.get(page, []),
                              other_crops=others)
            if c:
                clip.append((qi + 1, [f"{s}+{n}px" for s, n in c], [round(v) for v in rect]))
            furn = [(float(m["x"]), float(m["y"]),
                     float(m["x"]) + float(m.get("w") or 0),
                     float(m["y"]) + float(m.get("h") or 0))
                    for m in (r.get("noise") or [])
                    if int(m.get("page", 1)) == page]
            lk = row_leaks(r["sources"][page], rect, boxes.get(page, []),
                           other_crops=others, furniture=furn)
            if lk:
                leak.append((qi + 1, [f"{s}+{n}px" for s, n in lk], [round(v) for v in rect]))
            for qj, sj in span_by_q.items():
                if qj == qi or int(sj.get("page", -1)) != page:
                    continue
                for b in sj.get("text_boxes", []):
                    bb = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
                    if overlap(rect, bb) >= 0.6 and (bb[2] - bb[0]) > 20:
                        bleed.append((qi + 1, qj + 1, str(b.get("text", ""))[:16]))
                        break
    # 图内标注已由清理步骤从题干删掉，不能再算"含题干"；只报题干里还在的整句。
    stem_in = stem_in_figures(qs, got, span_by_q)

    # 手写材料：配图类判据没有适用对象。证据照列，但不计入缺陷（见 MATERIAL_CLASSES）。
    clip, leak, bleed, stem_in, residue, na = reclassify_material(
        path, clip, leak, bleed, stem_in, residue)

    bad = answerability(qs)
    dup = duplicates(qs)
    type_bad = type_suspects(qs)
    pages_out = 0
    if render:
        os.makedirs(OUT, exist_ok=True)
        # ⚠️ 先清掉这份材料上一次留下的逐页图。渲染目录是共用的，题少了/页数缩短时
        #    旧 PNG 不会被覆盖，人眼复核会把【上一版】的第 3 页当成本版成品
        #    （本轮实测：达标B 当前出 2 页，目录里还躺着上一版的 p3，整题截图看起来
        #    "文字还在图里"，差点把已经修好的图文分离判成没修）。
        clear_stale_pages(OUT, name)
        pdf = os.path.join(OUT, f"{name}_blank.pdf")
        render_answers_pdf(qs, LayoutOptions.from_dict({"show_header": True}), pdf,
                           title=name, mode="blank", figures_dir=fig_dir)
        d = pymupdf.open(pdf)
        pages_out = d.page_count
        for i, pg in enumerate(d):
            pg.get_pixmap(dpi=110).save(os.path.join(OUT, f"{name}_出卷_p{i + 1}.png"))
        d.close()

    n_img = sum(len(v) for v in got.values())
    n_graphic = sum(1 for v in got.values() for im in v if im.get("graphic"))
    cut = [d for d in rep if not d.get("kept")]
    from collections import Counter
    print(f"\n【{name}】源{r['n_pages']}页 · 题{len(qs)} · 配图{n_img}张（带图题{len(got)}）"
          f"· 出卷{pages_out}页 · 待校对{sum(1 for q in qs if q.get('needs_review'))}")
    print(f"  做不了 {len(bad)}　·　做得别扭：切边 {len(clip)} · 漏块 {len(leak)} · 串题 {len(bleed)} "
          f"· 含题干 {len(stem_in)} · 题干残渣 {len(residue)} · 重号 {len(dup)} "
          f"· 题型可疑 {len(type_bad)} · 图片选项 {n_imgopt}"
          f" · 图形算式图 {n_graphic}（整行原图，不计入含题干）")
    if n_res:
        print(f"    （已清掉图内重复文字 {n_res} 行）")
    if n_fold:
        print(f"    （已折掉图前伪题 {n_fold} 道：图并给真题，图例并进题干）")
    if handwritten:
        n_na = sum(len(v) for v in na.values())
        print(f"    材料类型：手写作业（人工分类）—— {mat.get('note')}；"
              f"不适用证据 {n_na} 条，不计入缺陷")
        for t, c, rr in na.get("漏块") or []:
            print(f"    · 不适用·漏块 第 {t} 题 框{rr} 框外 {c}（是笔迹，不是漏图）")
        for label, rows in na.items():
            if label != "漏块" and rows:
                print(f"    · 不适用·{label} {len(rows)} 条（手写材料，不逐条展开）")
    for kind, no, why in bad:
        print(f"    ✗ {kind:6} 第 {no} 题 {why}")
    for sec, no, n in dup:
        print(f"    · 重号   大题「{sec[:14]}」第 {no} 题出现 {n} 次（其中一道多半是乱码假题）")
    for i, no, qt, cue in type_bad:
        print(f"    · 题型可疑 第 {no} 题判成 {qt}，题干却在要求「{cue}」"
              f"（选项多半是图片，请在校对页确认题型/补选项）")
    for t, c, rr in clip:
        print(f"    · 切边   第 {t} 题 {c} 框{rr}")
    for t, c, rr in leak:
        print(f"    · 漏块   第 {t} 题 同一行框外还有墨 {c} 框{rr}（式子被从中间截断）")
    for t, o, s in bleed:
        print(f"    · 串题   第 {t} 题的图盖住第 {o} 题「{s}」")
    for t, s, w in stem_in:
        print(f"    · 含题干 第 {t} 题的图框住「{s}」  {w}")
    for t, s in residue:
        print(f"    · 残渣   第 {t} 题的题干里还有图内文字「{s}」")
    print(f"    砍掉的候选：{dict(Counter(d['why'] for d in cut))}")
    return {"name": name, "bad": bad, "clip": clip, "leak": leak, "bleed": bleed,
            "stem": stem_in, "res": residue, "dup": dup, "type": type_bad,
            "imgopt": n_imgopt, "graphic": n_graphic, "pages": pages_out,
            "questions": len(qs), "kind": ("handwritten" if handwritten else "print"),
            "na": na}


def collect(args: list[str]) -> list[str]:
    out = []
    for a in args:
        p = a if os.path.isabs(a) else os.path.join(ROOT, a)
        if os.path.isdir(p):
            out += [os.path.join(p, f) for f in sorted(os.listdir(p))
                    if f.lower().endswith((".pdf",) + IMG_EXT)]
        elif os.path.isfile(p):
            out.append(p)
        else:
            print("找不到", p)
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    render = "--no-render" not in sys.argv
    os.makedirs(OUT, exist_ok=True)
    bad_ruler = selftest()
    if bad_ruler:
        print("✗ 审计尺本身坏了（这份报告一个字都别信）：")
        for m in bad_ruler:
            # 前缀写成 FAIL：变异闸门 tests/break_audit.py 靠这一行判"打坏了会不会红"。
            print("FAIL 审计尺自检：" + m)
        return 2
    # 括号里的条数只是【标签】，判决只看 selftest() 返回的 fails ——
    # 加检查时忘了改这个数字，不会让一把坏尺装成好的。
    print("✓ 审计尺自检通过（53 条正/反对照）")
    if "--selftest" in sys.argv:        # 只验尺、不看真实材料（变异闸门用）
        return 0
    files = collect(args) or collect([os.path.join(ROOT, "samples", "private")])
    tot = {"bad": 0, "clip": 0, "leak": 0, "bleed": 0, "stem": 0, "res": 0,
           "dup": 0, "type": 0, "imgopt": 0, "graphic": 0, "na": 0}
    for f in files:
        try:
            a = audit(f, render=render)
        except Exception as e:
            import traceback
            print(f"  审计失败 {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)
            tot["bad"] += 1
            continue
        if not a:
            continue
        tot["bad"] += len(a["bad"])
        for k in ("clip", "leak", "bleed", "stem", "res", "dup", "type"):
            tot[k] += len(a[k])
        tot["imgopt"] += int(a.get("imgopt") or 0)
        tot["graphic"] += int(a.get("graphic") or 0)
        tot["na"] += sum(len(v) for v in (a.get("na") or {}).values())
    print(f"\n===== 合计：做不了 {tot['bad']} · 切边 {tot['clip']} · 漏块 {tot['leak']} "
          f"· 串题 {tot['bleed']} · 含题干 {tot['stem']} · 题干残渣 {tot['res']} "
          f"· 重号 {tot['dup']} · 题型可疑 {tot['type']} "
          f"· 图片选项 {tot['imgopt']}（选项在配图里，可按图作答）"
          f" · 图形算式图 {tot['graphic']}（整行原图，不计入含题干）"
          f" · 手写·不适用 {tot['na']}（仅备查）=====")
    print(f"逐页成品图在 {OUT}")
    return 1 if tot["bad"] else 0


if __name__ == "__main__":
    sys.exit(main())
