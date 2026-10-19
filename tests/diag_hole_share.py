"""量一下：真卷第 2 页那张标注图，三块之间的缝里有多少是"我们挖的文字洞"。
（决定横向缝合要不要加"缝必须是洞"这条判据 —— 不量就不能写进注释。）"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np                                                  # noqa: E402
import cv2                                                          # noqa: E402
from audit_papers import load                                       # noqa: E402
from app.extractor import lines as L                                # noqa: E402
from app.extractor.rules import extract, flatten_questions          # noqa: E402
from app.extractor import figures as F                              # noqa: E402

P = r"E:\数学卷子\第三单元练习题.pdf"
r = load(P)
res = extract(r["lines"], title="第三单元练习题")
qs = flatten_questions(res)
spans = L.spans_for_questions(r["ann"], qs, pages=r.get("pages"), sections=res.get("sections"))
tgt = next(i for i, q in enumerate(qs) if "乘法是求几个相同" in (q.get("text") or ""))
sp = next(s for s in spans if int(s["q_index"]) == tgt)
src = r["sources"][int(sp["page"])]
sc = F._scan(src, sp, np, cv2)
hole, k, ox, oy = sc["hole"], sc["k"], sc["cx0"], sc["y0"]

pairs = [("左↔中", (0.0, 142.4, 173.6, 267.2), (183.5, 174.8, 242.0, 221.9)),
         ("中↔右", (183.5, 174.8, 242.0, 221.9), (305.2, 172.7, 364.4, 219.7))]
out = []
for name, a, b in pairs:
    gx0, gx1 = a[2], b[0]
    gy0, gy1 = max(a[1], b[1]), min(a[3], b[3])
    px0, px1 = int(gx0 * k - ox), int(gx1 * k - ox)
    py0, py1 = int(gy0 * k - oy), int(gy1 * k - oy)
    band = hole[max(0, py0):py1, max(0, px0):px1]
    out.append("%s 缝 x=%.1f..%.1f y=%.1f..%.1f → 洞占比 %.1f%%（像素 %s）"
               % (name, gx0, gx1, gy0, gy1, 100.0 * float(band.mean()), band.shape))
txt = "\n".join(out)
open(os.path.join(ROOT, "var", "_hole_share.txt"), "w", encoding="utf-8").write(txt + "\n")
print(txt)
