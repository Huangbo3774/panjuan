# -*- coding: utf-8 -*-
"""自己对照：把【源卷上那一块】和【系统做出来的东西】并排拼成表，逐张人眼看。

为什么需要它：审计尺量的是能形式化的东西（缺括号、缺图、断号、重号），
"这道题拿到手上到底能不能做、图挂没挂对题"要人眼对照源卷才知道。
用户第三次开火那句"你能不能自己对照一下，这题都对不上"就是尺报 0 而题是错的。

用法：
  py -3.11 tests/diag_compare.py                      # 默认 samples/private 全部
  py -3.11 tests/diag_compare.py "E:/数学卷子/第三单元练习题.pdf"
产物：var/_compare/对照_NN.png ＋ 台账.txt（每题题干字数/空数/几张图/图多大）
⚠️ var/ 在服务启动时会被清空（这是产品设计），所以对照表看完就要留存或重跑。
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

import numpy as np                                                  # noqa: E402
import cv2                                                          # noqa: E402
import pymupdf                                                      # noqa: E402
from PIL import Image, ImageDraw, ImageFont                         # noqa: E402

from app.extractor import lines as L                                # noqa: E402
from app.extractor import symbols as SY                             # noqa: E402
from app.extractor.rules import extract, flatten_questions          # noqa: E402
from app.extractor.figures import find_figures, page_source_from_pdf     # noqa: E402

OUT = os.path.join(ROOT, "var", "_compare")
ZOOM = 2.2
FONT = "C:/Windows/Fonts/msyh.ttc"
PER = 2                      # 每页两道题：源块和成品并排，够大才看得清


def collect(path: str):
    """一份材料 → (题目, 区间, 配图, 页面位图缓存)。走的是和 API 完全同一条链路。"""
    os.makedirs(OUT, exist_ok=True)
    r = L.annotated_lines_from_pdf(path, work_dir=os.path.join(OUT, "_ocr"))
    res = extract(r["lines"], title=os.path.basename(path))
    qs = flatten_questions(res)
    spans = L.spans_for_questions(r["ann"], qs, pages=r.get("pages"),
                                  sections=res.get("sections"))
    sources = {}
    for pno in sorted({int(s["page"]) for s in spans}):
        src = page_source_from_pdf(path, pno)
        if src:
            sources[pno] = src
    got = find_figures(sources, spans, os.path.join(OUT, "_figs"))
    for s in spans:
        qi = int(s["q_index"])
        src = sources.get(int(s["page"]))
        if not (0 <= qi < len(qs)) or src is None:
            continue
        g = SY.scan_span(src, s, np, cv2)
        if g["lines"]:
            qs[qi]["symbols"] = g["lines"]
    return r, qs, spans, got


def ledger(qs, spans, got) -> str:
    by_q = {int(s["q_index"]): s for s in spans}
    lines = []
    for qi, q in enumerate(qs):
        sp = by_q.get(qi)
        crops = got.get(qi) or []
        lines.append("第%s题 [%s] 源第%s页 题干%d字 空%d 图%d %s%s" % (
            q.get("q_no"), q.get("qtype"), int(sp["page"]) if sp else "?",
            len((q.get("text") or "").strip()), q.get("blanks") or 0, len(crops),
            [(round(i["rect"][2] - i["rect"][0]), round(i["rect"][3] - i["rect"][1]))
             for i in crops],
            " | 还原%d行" % len(q.get("symbols") or []) if q.get("symbols") else ""))
    return "\n".join(lines)


def sheets(path: str) -> list[str]:
    r, qs, spans, got = collect(path)
    by_q = {int(s["q_index"]): s for s in spans}
    doc = pymupdf.open(path)
    f_title = ImageFont.truetype(FONT, 22)
    f_body = ImageFont.truetype(FONT, 17)
    pages, cache = [], {}
    cards = []
    for qi, q in enumerate(qs):
        sp = by_q.get(qi)
        if not sp:
            continue
        pg = int(sp["page"])
        if pg not in cache:
            pix = doc[pg - 1].get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM))
            cache[pg] = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        box = (max(0, int(sp["x0"] * ZOOM)), max(0, int(sp["y0"] * ZOOM)),
               min(cache[pg].width, int(sp["x1"] * ZOOM)),
               min(cache[pg].height, int(sp["y1"] * ZOOM)))
        cards.append((qi, q, cache[pg].crop(box)))
    for start in range(0, len(cards), PER):
        batch = cards[start:start + PER]
        W = 1500
        hs = [max(c[2].height, 420) for c in batch]
        sheet = Image.new("RGB", (W, sum(hs) + 40 * len(batch) + 20), (250, 250, 250))
        d = ImageDraw.Draw(sheet)
        y = 10
        for (qi, q, src_im), h in zip(batch, hs):
            sp = by_q[qi]
            d.text((12, y), "第 %s 题 [%s]  源第%d页  成品配图 %d 张" %
                   (q.get("q_no"), q.get("qtype"), int(sp["page"]), len(got.get(qi) or [])),
                   font=f_title, fill=(120, 20, 20))
            d.rectangle([12, y + 30, 12 + 700, y + h + 20], outline=(200, 200, 200))
            sw = min(690, src_im.width)
            sh = int(src_im.height * sw / src_im.width)
            sheet.paste(src_im.resize((sw, min(sh, h))), (16, y + 32))
            x, ty = 740, y + 58
            d.text((x, y + 32), "系统读到的题干：", font=f_body, fill=(0, 60, 140))
            txt = (q.get("text") or "").strip() or "（空）"
            while txt:
                d.text((x, ty), txt[:34], font=f_body, fill=(20, 20, 20))
                ty += 22
                txt = txt[34:]
            for sl in (q.get("symbols") or []):
                d.text((x, ty), "还原算式：" + sl, font=f_body, fill=(150, 90, 0))
                ty += 22
            fy = max(ty + 6, y + 32)
            for im in (got.get(qi) or []):
                p = os.path.join(OUT, "_figs", im["name"])
                if not os.path.exists(p):
                    continue
                c = Image.open(p)
                cw = min(740, c.width)
                ch = int(c.height * cw / max(1, c.width))
                room = (y + h + 20) - fy
                if room < 24:
                    d.text((x, fy), "（图太多画不下，尺寸见台账）",
                           font=f_body, fill=(180, 0, 0))
                    break
                if ch > room:
                    ch = room
                    cw = int(c.width * ch / max(1, c.height))
                d.rectangle([x - 2, fy - 2, x + cw + 2, fy + ch + 2], outline=(0, 150, 0))
                sheet.paste(c.resize((max(1, cw), max(1, ch))), (x, fy))
                fy += ch + 6
            y += h + 40
        out = os.path.join(OUT, "对照_%02d.png" % (start // PER + 1))
        sheet.save(out)
        pages.append(out)
    open(os.path.join(OUT, "台账.txt"), "w", encoding="utf-8").write(
        ledger(qs, spans, got) + "\n")
    return pages


def main() -> int:
    args = [a for a in sys.argv[1:]] or [os.path.join(ROOT, "samples", "private")]
    files = []
    for a in args:
        p = a if os.path.isabs(a) else os.path.join(ROOT, a)
        if os.path.isdir(p):
            files += [os.path.join(p, f) for f in sorted(os.listdir(p))
                      if f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png"))]
        else:
            files.append(p)
    for f in files:
        if not f.lower().endswith(".pdf"):
            print("跳过（只支持 PDF 逐页定位）：", f)
            continue
        try:
            got = sheets(f)
        except Exception as e:
            print("对照失败 %s：%s: %s" % (f, type(e).__name__, e))
            continue
        print("%s → %d 张对照表 + 台账.txt" % (os.path.basename(f), len(got)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
