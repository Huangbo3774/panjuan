# -*- coding: utf-8 -*-
"""诊断：被当成配图裁走的「答题框行」和「栏目横幅」，量清楚它们与真图的差别。

要回答两个问题（用户截图里的两种废图）：
  ① 栏目横幅（"第二步 练变式"的色块）——它的墨有多少落在【家具行带】里？
     家具行带＝OCR 读成文字的家具行（横幅本身），横幅色块比字高，多出来的上下沿
     会被 _merge_boxes 重新并成一个候选。量 wall_share。
  ② 答题框行（`□×□＝□`）——它由几个空心方框＋运算符组成，没有别的图形墨。
     量每个连通块的"空心方框度"：边长、填充率、方度。

用法：
  py -3.11 tests/diag_junk_boxes.py <某份真卷.pdf>
  （不给参数时取 samples/private 里第一份 PDF；真卷不入库，只在 var/ 留诊断图）
输出：每题每个候选项一行；日志只在 stdout，诊断图落 var/（服务启动会清 var/）。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np                                                   # noqa: E402
import cv2                                                           # noqa: E402

from app.extractor import lines as L                                 # noqa: E402
from app.extractor import figures as F                               # noqa: E402
from app.extractor import symbols as SY                              # noqa: E402
from app.extractor.rules import extract, flatten_questions           # noqa: E402


def comp_stats(band, rect, k):
    """候选框里的连通块（不膨胀）→ 每块的尺寸/填充率/顶点数。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    sub = band[y0:y1, x0:x1].astype(np.uint8)
    if not sub.any():
        return []
    n, lab, stats, _c = cv2.connectedComponentsWithStats(sub, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        fill = area / float(w * h)
        cnts, _ = cv2.findContours((lab[y:y + h, x:x + w] == i).astype(np.uint8),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        verts = 0
        if cnts:
            ap = cv2.approxPolyDP(max(cnts, key=cv2.contourArea),
                                  0.06 * cv2.arcLength(max(cnts, key=cv2.contourArea), True), True)
            verts = len(ap)
        out.append({"w_pt": w / k, "h_pt": h / k, "fill": fill, "verts": verts,
                    "area": area,
                    "aspect": max(w, h) / max(1, min(w, h))})
    return out


def box_metrics(band, rect, k):
    """答题框行的候选判据：空心方框几个、方框占全部墨多少、有没有大块非方框。"""
    cs = comp_stats(band, rect, k)
    total = sum(c["area"] for c in cs) or 1
    boxes = [c for c in cs if 12.0 <= min(c["w_pt"], c["h_pt"])
             and max(c["w_pt"], c["h_pt"]) <= 36.0 and c["fill"] <= 0.45
             and c["aspect"] <= 1.4 and c["verts"] in (4, 5)]
    big_nonbox = [c for c in cs if c not in boxes
                  and min(c["w_pt"], c["h_pt"]) >= 16.0]
    return {"n_box": len(boxes), "box_share": sum(c["area"] for c in boxes) / total,
            "big_nonbox": [(round(c["w_pt"]), round(c["h_pt"])) for c in big_nonbox],
            "h_pt": (rect[3] - rect[1]) / k}


def sym_labels(band, rect, k, np):
    """用和题干符号重建【同一个分类器】看候选框里的墨都是什么。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    sub = band[y0:y1, x0:x1]
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(
        sub.astype(np.uint8) * 255, connectivity=8)
    labs, big, squares = {}, [], []
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        wp, hp = w / k, h / k
        if max(wp, hp) > 36.0:
            big.append((round(wp), round(hp)))
            continue
        f = SY.features(sub[y:y + h, x:x + w], np)
        lab = SY.classify(f) if f else None
        labs[lab] = labs.get(lab, 0) + 1
        if lab == "square":
            squares.append((round(wp), round(hp)))
    return labs, big, squares


def box_rule(mask, rect, k, np):
    """拟定的"答题框块"判据：2 个以上真方框 + 方框墨占多数 + 没有大块/形状。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    sub = mask[y0:y1, x0:x1]
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(
        sub.astype(np.uint8) * 255, connectivity=8)
    total = sq_area = 0
    n_sq = n_shape = 0
    big = []
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area < 4:
            continue
        total += area
        wp, hp = w / k, h / k
        f = SY.features(sub[y:y + h, x:x + w], np)
        lab = SY.classify(f) if f else None
        if lab == "square":
            # 真答案框是【大空心方框】，不是文字里 1–3pt 的方块噪点
            if min(wp, hp) >= 12.0:
                n_sq += 1
                sq_area += area
        elif lab in SY.SHAPE_LABELS:
            n_shape += 1
        if max(wp, hp) >= 38.0:
            big.append((round(wp), round(hp)))
    return {"n_sq": n_sq, "share": sq_area / total if total else 0.0,
            "big": big, "n_shape": n_shape}


def wall_share(sgn, rect, raw, pad_pt):
    """裁框内的墨有多少落在（pad 过的）家具行带里。用 raw（挖字前的墨）量。"""
    k = sgn["k"]
    x0, y0, x1, y1 = [int(v) for v in rect]
    sub = raw[y0:y1, x0:x1]
    total = int(sub.sum())
    if not total:
        return 0.0
    wall = sgn["wall"].copy()
    pad = int(round(pad_pt * k))
    if pad > 0:
        wall = cv2.dilate(wall.astype(np.uint8), cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, pad * 2 + 1))) > 0
    inside = int((sub & wall[y0:y1, x0:x1]).sum())
    return inside / total


def _default_material() -> str:
    """不写死本机路径：优先取 samples/private 里第一份 PDF。"""
    d = os.path.join(ROOT, "samples", "private")
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".pdf"):
                return os.path.join(d, name)
    return ""


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else _default_material()
    if not path or not os.path.isfile(path):
        print("请给一份真卷 PDF：py -3.11 tests/diag_junk_boxes.py <path>")
        return 2
    tag = os.path.splitext(os.path.basename(path))[0]
    r = L.annotated_lines_from_pdf(path, work_dir=os.path.join(ROOT, "var", "_diagjunk_ocr", tag))
    res = extract(r["lines"], title=os.path.basename(path))
    qs = flatten_questions(res)
    spans = L.spans_for_questions(r["ann"], qs, pages=r.get("pages"),
                                  sections=res.get("sections"))
    print("=== %s ===" % tag)
    sources = {}
    for s in spans:
        p = int(s["page"])
        if p not in sources:
            sources[p] = F.page_source_from_pdf(path, p)
    fig_dir = os.path.join(ROOT, "var", "_diagjunk_figs", tag)
    rep = []
    got = F.find_figures(sources, spans, fig_dir, report=rep)

    by_q = {int(s["q_index"]): s for s in spans}
    for qi, imgs in sorted(got.items()):
        q = qs[qi] if 0 <= qi < len(qs) else {}
        sp = by_q.get(qi)
        if not sp:
            continue
        sgn = F._scan(sources[int(sp["page"])], sp, np, cv2)
        print("\n第%s题 [%s] q_index=%d 源第%s页  图%d张" % (
            q.get("q_no"), q.get("qtype"), qi, sp["page"], len(imgs)))
        for im in imgs:
            rect = im["rect"]
            x0, y0, x1, y1 = [v * sgn["k"] for v in rect]
            # 裁框允许比探测带外扩 3pt（_extend_to_short_marks 之后才夹回 span），
            # 直接相减会得到负下标，numpy 会静默从另一头切片 → 量出全 0。必须夹。
            hh, ww = sgn["raw"].shape
            px = (max(0, int(x0 - sgn["cx0"])), max(0, int(y0 - sgn["y0"])),
                  min(ww, int(x1 - sgn["cx0"])), min(hh, int(y1 - sgn["y0"])))
            ws = [wall_share(sgn, px, sgn["raw"], p) for p in (0, 2, 6, 10)]
            raw_ink = int(sgn["raw"][int(px[1]):int(px[3]), int(px[0]):int(px[2])].sum())
            band_ink = int(sgn["band"][int(px[1]):int(px[3]), int(px[0]):int(px[2])].sum())
            print("  图 %s×%s 框%s  墨raw=%d band=%d  wall_share pad0/2/6/10=%s" % (
                round(rect[2] - rect[0]), round(rect[3] - rect[1]),
                [round(v) for v in rect], raw_ink, band_ink,
                [round(v, 3) for v in ws]))
            cs = comp_stats(sgn["band"], px, sgn["k"])
            cs.sort(key=lambda c: -c["w_pt"] * c["h_pt"])
            for c in cs[:12]:
                print("     块 %5.1f×%-5.1f fill=%.2f verts=%d asp=%.2f" % (
                    c["w_pt"], c["h_pt"], c["fill"], c["verts"], c["aspect"]))
            bm = box_metrics(sgn["raw"], px, sgn["k"])
            # 候选框与 OCR 行带的竖直重叠：找重叠最多的那一行
            best_ov, best_txt = 0.0, ""
            rh = max(1.0, rect[3] - rect[1])
            for tb in sp.get("text_boxes") or []:
                ov = min(rect[3], tb["y"] + tb["h"]) - max(rect[1], tb["y"])
                if ov / rh > best_ov:
                    best_ov, best_txt = ov / rh, str(tb.get("text") or "")[:18]
            labs, big, squares = sym_labels(sgn["band"], px, sgn["k"], np)
            print("     框行判据 n_box=%d box_share=%.2f 大非方框=%s 行重叠=%.2f「%s」" % (
                bm["n_box"], bm["box_share"], bm["big_nonbox"], best_ov, best_txt))
            print("     符号分类 %s  方框%s 大块%s" % (labs, squares, big))
            br = box_rule(sgn["raw"], px, sgn["k"], np)
            bc = box_rule(sgn["band"], px, sgn["k"], np)
            print("     答题框判据 raw: n_sq=%d share=%.2f 形状=%d 大块=%s | band: n_sq=%d share=%.2f" % (
                br["n_sq"], br["share"], br["n_shape"], br["big"],
                bc["n_sq"], bc["share"]))
            h_pt = rect[3] - rect[1]
            boxy = (h_pt <= 90 and br["n_sq"] >= 2 and br["share"] >= 0.40
                    and br["n_shape"] == 0 and not br["big"])
            # 注：大块用的是 raw 里所有 ≥38pt 的分量；答案框块里不该有
            banner = ws[0] >= 0.60
            if boxy or banner:
                print("     ★RULE boxy=%s banner=%s" % (boxy, banner))
    print("\n被砍候选（非 small）：")
    for d in rep:
        if d.get("kept"):
            continue
        if d.get("why") == "small":
            continue
        print("  q=%s p=%s %s %s" % (d.get("q_index"), d.get("page"), d.get("why"),
                                     [round(v) for v in d["rect"]]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
