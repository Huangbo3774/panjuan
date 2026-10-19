"""把已排好的 A4 竖版 PDF 两两并到 A3 横版上（标准试卷对开）。

为什么用"事后拼页"而不是在排版引擎里直接画两栏：
  · 排版引擎按 A4 宽度折行、分页，拼页时【不需要重新折行】，
    所以模式 A/B/C 三条链路共用同一份 A4 版面，不会出现"打印版和做题版行宽不一致"。
  · A3 横版长边 = 2×A4 宽，1:1 放置，不缩放，字号和单页完全一样。
    （2 合 1 是 √2 缩印，那是省纸，不是标准试卷样式——两件事不能混。）
"""
from __future__ import annotations

import os

A4_W, A4_H = 595.28, 841.89
A3_W, A3_H = 1190.55, 841.89


def a4_to_a3_spread(src_pdf: str, out_pdf: str) -> dict:
    """返回 {pages_a4, pages_a3, path}。奇数页时右半留空（对折后背面空白，符合习惯）。"""
    import pymupdf

    src = pymupdf.open(src_pdf)
    n = src.page_count
    out = pymupdf.open()
    for i in range(0, n, 2):
        page = out.new_page(width=A3_W, height=A3_H)
        page.show_pdf_page(pymupdf.Rect(0, 0, A4_W, A4_H), src, i)
        if i + 1 < n:
            page.show_pdf_page(pymupdf.Rect(A4_W, 0, A3_W, A4_H), src, i + 1)
    tmp = out_pdf + ".tmp.pdf"
    out.save(tmp)
    out.close()
    src.close()
    os.replace(tmp, out_pdf)
    return {"pages_a4": n, "pages_a3": (n + 1) // 2, "path": out_pdf}
