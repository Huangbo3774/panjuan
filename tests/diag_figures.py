# -*- coding: utf-8 -*-
"""把「现在的配图裁剪到底框住了什么」画出来看。

只在本地跑真实材料（samples/private/ 已被 .gitignore 挡住，产物写进 var/_figdiag/，
都不进仓库）。不改产品代码，只回答三个问题：
  1) 这份材料是不是左右分栏？（横版两栏是用户点名的场景）
  2) 现在的裁图框有没有跨栏 / 有没有把别的题的文字框进来？
  3) 每道题的"下一题"在另一栏时，区间 [y0,y1) 会变成什么？（会倒过来）

输出：var/_figdiag/<名>_p<页>_annotated.png —— 红框=现在的裁图结果，蓝框=题目文字行，
     黄虚线=检测到的分栏缝。人眼看一眼就知道错在哪，比读日志快。
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

import pymupdf                                                      # noqa: E402
from app.extractor import lines as L                                # noqa: E402
from app.extractor import ocr as OC                                 # noqa: E402
from app.extractor.figures import find_figures, page_source_from_pdf  # noqa: E402
from app.extractor.rules import extract, flatten_questions          # noqa: E402

OUT = os.path.join(ROOT, "var", "_figdiag")


def columns_of(ann, page_w):
    """按文字行的 x 起点粗判几栏：把行按 x 排序后找明显的空档。"""
    if not ann:
        return []
    starts = sorted(round(float(a["x"])) for a in ann)
    gaps, prev = [], starts[0]
    for s in starts[1:]:
        if s - prev > page_w * 0.18:
            gaps.append((prev + s) / 2.0)
        prev = max(prev, s)
    edges = [0.0] + gaps + [page_w]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def probe(path: str) -> None:
    name = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1].lower()
    if ext != ".pdf":
        print(f"跳过非 PDF：{name}")
        return
    doc = pymupdf.open(path)
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height
    orient = "横版" if pw > ph else "竖版"
    doc.close()
    print(f"\n{'=' * 74}\n【{name}】首页 {pw:.0f}×{ph:.0f}pt · {orient}")

    ok, why = OC.available()
    r = L.annotated_lines_from_pdf(path, work_dir=os.path.join(ROOT, "var", "_figdiag", "_ocr"))
    ann = r["ann"]
    print(f"  路由：{[(p['page'], p['route']) for p in r['pages']][:6]} · OCR 置信 {r['ocr_conf']} · 行 {len(ann)}")
    if not ann:
        print("  一行都没拿到，跳过")
        return
    res = extract(r["lines"], title="")
    qs = flatten_questions(res)
    secs = [(s["name"], len(s["questions"])) for s in res["sections"]]
    print(f"  切题 {len(qs)} 道 · 大题 {len(secs)} 个：{secs[:8]}")

    spans = L.spans_for_questions(ann, qs)
    print(f"  spans_for_questions 给了 {len(spans)} 条区间")
    bad_order = [s for s in spans if s["y1"] and float(s["y1"]) <= float(s["y0"])]
    print(f"  ⚠️ 区间倒挂（y1<=y0，下一题其实在同一页但更靠上=另一栏）：{len(bad_order)} 条"
          + (f"  例 q{bad_order[0]['q_index']} y0={bad_order[0]['y0']:.0f} y1={bad_order[0]['y1']:.0f}"
             if bad_order else ""))

    # 逐页画框
    for page_no in sorted({int(s["page"]) for s in spans})[:2]:
        src = None
        # 全局页号 → 该文件本地页号（单文件探测时两者一致）
        try:
            src = page_source_from_pdf(path, page_no)
        except Exception as e:
            print(f"  第 {page_no} 页取不到页面源：{e}")
            continue
        if src is None:
            continue
        cols = columns_of([a for a in ann if int(a["page"]) == page_no], src.width_pt)
        print(f"  第 {page_no} 页 宽 {src.width_pt:.0f}pt · 粗判栏数 {len(cols)} → "
              + " / ".join(f"{a:.0f}–{b:.0f}" for a, b in cols))

        rep: list = []
        got = find_figures({page_no: src}, [s for s in spans if int(s["page"]) == page_no],
                           OUT, report=rep)
        n = sum(len(v) for v in got.values())
        cross = 0
        for s in spans:
            if int(s["page"]) != page_no:
                continue
            for im in got.get(int(s["q_index"]), []):
                x0, _y0, x1, _y1 = im["rect"]
                if x0 < s["x0"] - 6 or x1 > s["x1"] + 6:
                    cross += 1
        print(f"  裁出图形 {n} 张，涉及 {len(got)} 道题 · ⚠️ 跨出所属栏的：{cross} 张")
        # 每张被砍掉的候选都要报出【为什么】—— 不然"这题怎么没图"只能靠猜
        from collections import Counter
        print("  砍掉的候选：" + str(dict(Counter(d["why"] for d in rep if not d.get("kept")))))
        for d in rep:
            if d["why"] in ("text-residual", "margin", "furniture", "cap"):
                print(f"    {d['why']:>14} 第 {d['q_index'] + 1} 题 "
                      f"({d['rect'][0]:.0f},{d['rect'][1]:.0f})-"
                      f"({d['rect'][2]:.0f},{d['rect'][3]:.0f})")
        multi = {k + 1: len(v) for k, v in got.items() if len(v) > 1}
        if multi:
            print(f"  ⚠️ 仍被切成多块的题：{multi}（一张图不许切成两块，见 docs §12）")

        d = pymupdf.open(path)
        pg = d[page_no - 1]
        pix = pg.get_pixmap(dpi=110)
        out_png = os.path.join(OUT, f"{name}_p{page_no}_annotated.png")
        # 用 pymupdf 的 Shape 在原页上画框再导出
        k = 1.0                                     # 页面坐标就是 pt
        for s in spans:
            if int(s["page"]) != page_no:
                continue
            y1 = float(s["y1"]) if s["y1"] else src.height_pt
            # 红框 = 这道题现在拥有的区间（应当只占自己那一栏，而不是整页宽）
            pg.draw_rect(pymupdf.Rect(float(s.get("x0") or 0), float(s["y0"]),
                                      float(s.get("x1") or src.width_pt),
                                      max(y1, float(s["y0"]) + 1)),
                         color=(0.9, 0.15, 0.15), width=1.2)
            for b in s["text_boxes"]:
                pg.draw_rect(pymupdf.Rect(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]),
                             color=(0.1, 0.35, 0.95), width=0.5)
        for qi, lst in got.items():
            for im in lst:
                x0, y0, x1, y1 = im["rect"]
                # 绿框 = 实际裁出来的图
                pg.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0.05, 0.7, 0.2), width=1.8)
                pg.insert_text((x0 + 2, y0 + 11), f"q{qi + 1}", fontsize=9, color=(0.05, 0.5, 0.15))
        for a, b in cols[1:]:
            x = a
            pg.draw_line(pymupdf.Point(x, 0), pymupdf.Point(x, src.height_pt),
                         color=(0.95, 0.8, 0.1), width=1.5, dashes="[6 4] 0")
        for qi, lst in got.items():
            for f in lst:
                pass
        pix2 = pg.get_pixmap(dpi=110)
        pix2.save(out_png)
        d.close()
        print(f"  → 画框图已存 {os.path.relpath(out_png, ROOT)}（红=现在的裁图纵向条带·整页宽，"
              f"蓝=题目文字行，黄虚线=分栏缝）")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if not args:
        d = os.path.join(ROOT, "samples", "private")
        args = [os.path.join("samples", "private", f) for f in sorted(os.listdir(d))
                if f.lower().endswith(".pdf")]
    os.makedirs(OUT, exist_ok=True)
    for f in args:
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        if os.path.exists(p):
            try:
                probe(p)
            except Exception as e:
                import traceback
                print(f"  探测失败 {type(e).__name__}: {e}")
                traceback.print_exc(limit=3)
        else:
            print("找不到", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
