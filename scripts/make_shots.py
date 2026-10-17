"""生成 README 用的「原始 → 干净 A4」对比图。

⚠️ 面向陌生人发布时，默认只用【公开合成样本】，不用真实学生作业。
   要包含真实材料必须显式加 --include-private，且自己确认过愿意公开。
"""
from __future__ import annotations

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                   # noqa: E402
from PIL import Image, ImageDraw, ImageFont                      # noqa: E402

OUT = os.path.join(ROOT, "shots")
GAP, PAD, LABEL = 26, 28, 46


def font(size=26):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
              "C:/Windows/Fonts/simhei.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def pdf_page_png(pdf_path: str, dpi: int = 130) -> Image.Image:
    d = pymupdf.open(pdf_path)
    pm = d[0].get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
    d.close()
    return img


def load_any(path: str) -> Image.Image:
    """左栏既可能是图片，也可能是 PDF（比如"老师发的扫描版 PDF"本身）。"""
    if path.lower().endswith(".pdf"):
        return pdf_page_png(path, dpi=110)
    return Image.open(path).convert("RGB")


def build(before_path: str, after_pdf: str, title_left: str, title_right: str, out_name: str):
    a = load_any(before_path)
    b = pdf_page_png(after_pdf)
    H = 900
    a = a.resize((int(a.width * H / a.height), H))
    b = b.resize((int(b.width * H / b.height), H))
    W = a.width + b.width + GAP + PAD * 2
    canvas = Image.new("RGB", (W, H + LABEL + PAD * 2), (247, 247, 245))
    canvas.paste(a, (PAD, PAD + LABEL))
    canvas.paste(b, (PAD + a.width + GAP, PAD + LABEL))
    d = ImageDraw.Draw(canvas)
    f = font(27)
    d.text((PAD, PAD + 6), title_left, fill=(150, 60, 30), font=f)
    d.text((PAD + a.width + GAP, PAD + 6), title_right, fill=(35, 95, 65), font=f)
    d.rectangle([PAD - 6, PAD + LABEL - 6, PAD + a.width + 6, PAD + LABEL + H + 6],
                outline=(220, 214, 208), width=2)
    d.rectangle([PAD + a.width + GAP - 6, PAD + LABEL - 6,
                 PAD + a.width + GAP + b.width + 6, PAD + LABEL + H + 6],
                outline=(190, 205, 196), width=2)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, out_name)
    canvas.save(p, optimize=True)
    print(f"  {p}  {canvas.width}x{canvas.height}  {os.path.getsize(p)/1024:.0f}KB")
    return p


def main():
    made = []
    pub = os.path.join(ROOT, "samples", "public")
    # 1) 手机拍照 → 干净 A4（公开合成样本，可安全对外）
    scan = os.path.join(pub, "扫描版试卷.pdf")
    shot = os.path.join(pub, "手机拍作业.jpg")
    if os.path.exists(shot) and os.path.exists(scan):
        made.append(build(shot, scan, "手机拍的作业照片", "磐卷输出：标准 A4 试卷",
                          "compare-photo-to-a4.png"))
    # 2) 扫描版 PDF → A4
    if os.path.exists(scan):
        made.append(build(scan if os.path.exists(scan) else shot, scan,
                          "老师发的扫描版 PDF", "磐卷输出：统一页边距 + 表头 + 页码",
                          "compare-scan-to-a4.png"))
    if "--include-private" in sys.argv:
        pv = os.path.join(ROOT, "samples", "private", "数学作业.jpeg")
        gen = os.path.join(ROOT, "var", "e2e", "数学作业_磐卷A4.pdf")
        if os.path.exists(pv) and os.path.exists(gen):
            made.append(build(pv, gen, "原始照片（真实材料）", "磐卷输出",
                              "compare-private.png"))
            print("  ⚠️ 这张含真实学生作业，对外发布前请自己确认愿意公开")
    print(f"\n共 {len(made)} 张 → shots/")


if __name__ == "__main__":
    main()
