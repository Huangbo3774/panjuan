"""生成【公开可分发】的测试样本（不含任何真实学生作业）。

为什么需要：真实材料在 samples/private/，已 gitignore，别人 clone 下来没有它，
验收脚本 F01–F10 就跑不起来。本脚本造一套结构等价的公开样本：
文字版 PDF / 扫描版 PDF / 手机拍照风格的糊图 / docx，够覆盖各条用例的输入形态。

用法: py -3.11 scripts/make_public_samples.py
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

import pymupdf                                                   # noqa: E402
from PIL import Image, ImageDraw, ImageFont                      # noqa: E402

OUT = os.path.join(ROOT, "samples", "public")

LINES = [
    ("第三单元达标练习", 30, True),
    ("一、选择题（每题 3 分，共 15 分）", 17, True),
    ("1. 4×7 读作（  ）", 16, False),
    ("    A. 4乘7    B. 4乘以7    C. 7乘4    D. 四七二十八", 15, False),
    ("2. 一个因数是 6，另一个因数是 8，积是（  ）", 16, False),
    ("    A. 14      B. 48        C. 24      D. 16", 15, False),
    ("3. 3 个 8 相加的正确算式是（  ）", 16, False),
    ("    A. 3+8     B. 3×8       C. 8-3     D. 8÷3", 15, False),
    ("4. 五八（  ）四九（  ）六七（  ）", 16, False),
    ("    A. 四十 三六 四十二     B. 四十 三十六 四十二", 15, False),
    ("    C. 四十五 三十六 四十二  D. 四十 三十六 四十八", 15, False),
    ("5. 7 个 6 相加的和是（  ）", 16, False),
    ("    A. 13      B. 42        C. 36      D. 48", 15, False),
    ("二、填空题（每空 2 分，共 20 分）", 17, True),
    ("6. 一年有＿＿个月，其中大月有＿＿个。", 16, False),
    ("7. 被除数是 56，除数是 8，商是＿＿。", 16, False),
    ("三、解答题（共 25 分）", 17, True),
    ("8. 果园里有 6 行桃树，每行 8 棵，一共有多少棵？", 16, False),
    ("9. 一本书 96 页，每天看 8 页，看了 7 天，还剩多少页？", 16, False),
    ("10. 小明买了 4 支铅笔，每支 6 角，一共要多少钱？", 16, False),
]
# 注意：样本正文【刻意不含"姓名"二字】。表头开关的验收要靠"姓名"判断，
# 若正文里也有"姓名"，关掉表头仍会检测到"姓名"，把正确实现误判成失败（实测踩过）。


def _font(size):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/System/Library/Fonts/PingFang.ttc"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_page(w=1240, h=1754, blur=False, noise=False, gray_bg=False):
    # gray_bg：模拟拍照时纸张发灰/光照不均。省墨模式的判据是"白度上升"，
    # 若样本本来就纯白（76.7%），二值化无处可提，测不出开关有没有生效。
    bg = (206, 204, 199) if gray_bg else "white"
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    y = 70
    for text, size, bold in LINES:
        f = _font(size * (2 if w > 900 else 1))
        d.text((80, y), text, fill=(20, 20, 20) if not bold else (0, 0, 0), font=f)
        y += int(size * 2.3)
    if noise:                                       # 模拟手机拍照：噪点 + 压暗
        import random
        px = img.load()
        for _ in range(w * h // 6):
            x, yy = random.randrange(w), random.randrange(h)
            r, g, b = px[x, yy]
            v = max(0, min(255, int(r * 0.93 + random.uniform(-16, 16))))
            px[x, yy] = (v, v, v)
    if blur:                                        # 轻度模糊（自实现，不依赖滤镜）
        img = img.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(1.2))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    written = []

    # 1) 文字版 PDF（有文本层）
    doc = pymupdf.open()
    for part in range(2):
        pg = doc.new_page(width=595, height=842)
        y = 70
        for text, size, bold in LINES:
            pg.insert_text((50, y), f"{text}（第{part+1}页）", fontsize=size * 0.62,
                           fontname="china-s")
            y += size * 1.5
    p = os.path.join(OUT, "文字版试卷.pdf")
    doc.save(p); doc.close(); written.append(p)

    # 2) 扫描版 PDF（整页一张图，无文本层）
    # 用 JPEG 而非 PNG 内嵌：PNG 无损会让 3 页卷到 6.4MB，进仓库太大
    jpg = os.path.join(OUT, "_scan.jpg")
    draw_page().save(jpg, quality=82)
    doc = pymupdf.open()
    for i in range(3):
        pg = doc.new_page(width=595, height=842)
        pg.insert_image(pymupdf.Rect(0, 0, 595, 842), filename=jpg)
    p = os.path.join(OUT, "扫描版试卷.pdf")
    doc.save(p, deflate=True, garbage=3); doc.close(); os.remove(jpg); written.append(p)

    # 3) 手机拍照风格糊图（灰底，省墨模式才有可提升空间）
    p = os.path.join(OUT, "手机拍作业.jpg")
    draw_page(w=1080, h=1400, blur=True, noise=True, gray_bg=True).save(p, quality=72)
    written.append(p)

    # 4) 清晰电子图
    p = os.path.join(OUT, "清晰试卷图.jpg")
    draw_page(w=1260, h=907).save(p, quality=90)
    written.append(p)

    # 5) docx
    try:
        from docx import Document
        from docx.shared import Pt
        d = Document()
        for text, size, bold in LINES:
            r = d.add_paragraph().add_run(text)
            r.font.size = Pt(size * 0.55)
            r.bold = bold
        p = os.path.join(OUT, "Word试卷.docx")
        d.save(p); written.append(p)
    except Exception as e:
        print("docx 样本跳过：", e)

    print(f"公开样本已生成 {len(written)} 份 → samples/public/")
    for f in written:
        print(f"   {os.path.basename(f):20} {os.path.getsize(f)/1024:8.1f} KB")
    return written


if __name__ == "__main__":
    main()
