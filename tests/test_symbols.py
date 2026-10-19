# -*- coding: utf-8 -*-
"""图形符号识别的尺：每个形状画一遍，认错的、漏认的、误当算式的，全都要红。

为什么必须自己画：真实卷上"画出来的★●□△"只有那一两处，量不到分类器的边界；
而分类器的错误方向很难看——把"3"认成符号、把整张图当成一行算式，
印出来就是给孩子一道题干是瞎话的题。所以每个判据都要有【画出来的正例】
和【长得像的反例】。
"""
from __future__ import annotations

import math
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

from app.extractor import symbols as SY                             # noqa: E402
from app.extractor.figures import PageSource, DPI_PROBE             # noqa: E402

ok_n = bad_n = 0


def t(name, fn):
    global ok_n, bad_n
    try:
        fn()
        ok_n += 1
        print("  PASS " + name)
    except Exception as e:
        bad_n += 1
        print(f"  FAIL {name} → {type(e).__name__}: {e}")


K = DPI_PROBE / 72.0            # px = pt × K


def _blank(w_pt: float, h_pt: float) -> np.ndarray:
    return np.full((int(round(h_pt * K)), int(round(w_pt * K))), 255, dtype=np.uint8)


def _star(g, cx, cy, r):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.42
        pts.append([cx + rr * math.cos(ang), cy + rr * math.sin(ang)])
    cv2.fillPoly(g, [np.array(pts, np.int32)], 0)


def _cross(g, cx, cy, r, deg=0):
    # 臂宽 0.22r：真卷上的 ＋ 是细描边（实心度 0.21–0.28），
    # 画成 0.30r 就成了"胖十字"，实心度 0.46，会掉出运算符判据之外。
    thick = max(2, int(r * 0.22))
    for ang in (deg, deg + 90):
        a = math.radians(ang)
        dx, dy = r * math.cos(a), r * math.sin(a)
        cv2.line(g, (int(cx - dx), int(cy - dy)), (int(cx + dx), int(cy + dy)), 0, thick)


def _bars(g, cx, cy, w, gap, thick=3):
    for dy in (-gap / 2.0, gap / 2.0):
        cv2.line(g, (int(cx - w / 2), int(cy + dy)), (int(cx + w / 2), int(cy + dy)), 0, thick)


def _circle(g, cx, cy, r, hollow=False):
    cv2.circle(g, (int(cx), int(cy)), int(r), 0, -1 if not hollow else max(2, int(r * 0.28)))


def _square(g, cx, cy, r, hollow=False):
    p = int(r)
    cv2.rectangle(g, (cx - p, cy - p), (cx + p, cy + p), 0,
                  -1 if not hollow else max(2, int(p * 0.3)))


def _diamond(g, cx, cy, r):
    cv2.fillPoly(g, [np.array([[cx, cy - r], [cx + r, cy], [cx, cy + r], [cx - r, cy]], np.int32)], 0)


def _triangle(g, cx, cy, r):
    cv2.fillPoly(g, [np.array([[cx, cy - r], [cx + r * 0.9, cy + r * 0.7],
                               [cx - r * 0.9, cy + r * 0.7]], np.int32)], 0)


def _paren(g, cx, cy, r, close=False):
    # cv2 的角度 0 在 +x 方向：画右半边是"）"，画左半边才是"（"
    a0, a1 = (-55, 55) if close else (125, 235)
    cv2.ellipse(g, (int(cx), int(cy)), (int(r * 0.45), int(r)), 0, a0, a1, 0,
                max(2, int(r * 0.22)))


def _blob(g, cx, cy, r):
    """一坨不规则墨：是个图形，但认不出是什么 → 只能标〔图〕，不许标成某个具体形状。"""
    pts = [[cx + r * math.cos(a), cy + r * 0.8 * math.sin(a) + r * 0.35 * math.sin(3 * a)]
           for a in [i * 2 * math.pi / 11 for i in range(11)]]
    cv2.fillPoly(g, [np.array(pts, np.int32)], 0)


def _cjk_like(g, cx, cy, r):
    """长得像【汉字】的墨：一个框里三笔竖。OCR 行框和字实际位置常差半行，
    没挖干净的文字会漏到这一步 —— 它必须被判成"不是符号"，
    否则"国"字会被认成方框、"川"字会被认成三个减号。"""
    cv2.rectangle(g, (int(cx - r), int(cy - r)), (int(cx + r), int(cy + r)), 0,
                  max(2, int(r * 0.18)))
    for k in (-0.45, 0.0, 0.45):
        cv2.line(g, (int(cx + r * k), int(cy - r * 0.6)),
                 (int(cx + r * k), int(cy + r * 0.6)), 0, max(2, int(r * 0.16)))


def _label_of(draw, size_pt=25.0):
    """画一个符号 → 走和线上一样的两步：features → classify。"""
    g = _blank(size_pt + 4, size_pt + 4)
    c = int((size_pt + 4) * K / 2)
    draw(g, c, c, size_pt * K / 2)
    return _label_of_mask(g)


def _label_of_mask(g):
    band = g < 128
    ys, xs = np.nonzero(band)
    if len(xs) == 0:
        return None, {}
    f = SY.features(band[ys.min():ys.max() + 1, xs.min():xs.max() + 1], np)
    return SY.classify(f), f


def classifier_recognises_each_shape():
    drawn = {
        "star": _star,
        "plus": lambda g, x, y, r: _cross(g, x, y, r, 0),
        "times": lambda g, x, y, r: _cross(g, x, y, r, 45),
        "circle": _circle,
        "ring": lambda g, x, y, r: _circle(g, x, y, r, True),
        "square": _square,
        "hollow_square": lambda g, x, y, r: _square(g, x, y, r, True),
        "triangle": _triangle,
        "diamond": _diamond,
        "minus": lambda g, x, y, r: cv2.line(g, (int(x - r), int(y)), (int(x + r), int(y)), 0, 3),
        "paren_open": lambda g, x, y, r: _paren(g, x, y, r, False),
        "paren_close": lambda g, x, y, r: _paren(g, x, y, r, True),
    }
    exp = {"star": "star", "plus": "plus", "times": "times", "circle": "circle",
           "ring": "ring", "square": "square", "hollow_square": "square",
           "triangle": "triangle", "diamond": "diamond", "minus": "minus",
           "paren_open": "paren_open", "paren_close": "paren_close"}
    got = {k: _label_of(v) for k, v in drawn.items()}
    wrong = {k: got[k][0] for k in exp if got[k][0] != exp[k]}
    assert not wrong, "认错形状：" + "; ".join(
        f"{k} 判成 {v!r}（应为 {exp[k]!r}，实心度 {got[k][1].get('solidity'):.2f} "
        f"圆度 {got[k][1].get('circularity'):.2f} 角数 {got[k][1].get('lobes'):.0f} "
        f"顶宽 {got[k][1].get('top_w'):.2f}）" for k, v in wrong.items())
    # 反例：弯月这类"是图形但认不准"的，只许标〔图〕，不许冒充某个具体形状
    moon, _f = _label_of(_blob)
    assert moon == "shape", f"不规则图形被判成 {moon!r}（只许标 〔图〕）"
t("十二种形状各画一遍必须认对；认不准的只标〔图〕不冒充（含反例）",
  classifier_recognises_each_shape)


def unknown_ink_is_not_guessed():
    """长得像【汉字】的墨必须判成"不是符号"。

    OCR 行框和字实际位置常差半行，没挖干净的文字会漏到这里。
    不挡掉的后果：一个"国"字被认成方框、"川"字被认成三个减号，
    拼出来的算式是瞎话，还会被印进孩子的卷子。
    """
    lab, f = _label_of(_cjk_like)
    assert lab is None, f"一个框里三笔竖被判成 {lab!r}（特征 runs_mid={f.get('runs_mid')}）"
    # 又长又扁的横线（数轴、下划线）在尺寸闸门就该被挡掉
    g = _blank(90, 20)
    cv2.line(g, (int(4 * K), int(10 * K)), (int(86 * K), int(10 * K)), 0, 3)
    _lab2, f2 = _label_of_mask(g)
    assert f2["aspect"] > 8.0, f"这条横线的长宽比 {f2['aspect']:.1f}，本该在尺寸闸门就被挡掉"
t("认不出的墨不许猜（汉字笔画 / 超长横线）", unknown_ink_is_not_guessed)


# ────────────────────────── scan_span：行闸门 ──────────────────────────

PLUS = lambda g, x, y, r: _cross(g, x, y, r, 0)
EQ = lambda g, x, y, r: _bars(g, x, y, r * 1.4, r * 0.55)


def _page(w_pt=300.0, h_pt=170.0):
    return _blank(w_pt, h_pt)


def _src(g):
    h, w = g.shape
    return PageSource(1, w / K, h / K, g, lambda rect, out: None)


def _span(text_boxes):
    return {"q_index": 0, "page": 1, "col": 0, "x0": 0.0, "x1": 300.0,
            "y0": 0.0, "y1": 170.0, "text_boxes": text_boxes}


def _equation_page():
    """★ ＋ ★ ＝ 20 —— "20" 是 OCR 读到的文本框（图形是画的，数字是字）。"""
    g = _page()
    for x, kind in ((20, _star), (50, PLUS), (80, _star), (110, EQ)):
        kind(g, int(x * K), int(60 * K), 12.5 * K)
    return g, [{"x": 130.0, "y": 52.0, "w": 24.0, "h": 16.0, "text": "20"}]


def scan_span_rebuilds_an_equation():
    g, boxes = _equation_page()
    got = SY.scan_span(_src(g), _span(boxes), np, cv2)
    assert len(got["lines"]) == 1, f"应重建出一行，实际 {got['lines']}"
    line = got["lines"][0]
    order = [line.find("★"), line.find("＋"), line.find("＝"), line.find("20")]
    assert all(i >= 0 for i in order), f"缺件：{line!r}"
    assert order == sorted(order), f"顺序错了（应按卷面从左到右）：{line!r}"
    assert got["n_shapes"] == 2, f"形状数不对：{got}"
t("scan_span 把 ★＋★＝20 还原成一行（顺序与件数都对）", scan_span_rebuilds_an_equation)


def scan_span_refuses_non_equations():
    g, boxes = _equation_page()
    # 反例①：一排圆点 + 加号，但【没有等号】→ 那是"数一数"的点阵图，
    # 该走配图，不该拼成文字（真卷上"连一连"那题就是这种形状）
    g2 = _page()
    C3 = lambda gg, a, b, r: _circle(gg, a, b, r * 0.64)
    for x, kind in ((20, C3), (48, PLUS), (76, C3), (104, PLUS), (132, C3)):
        kind(g2, int(x * K), int(60 * K), 12.5 * K)
    a = SY.scan_span(_src(g2), _span([]), np, cv2)
    assert a["lines"] == [], f"没有等号的一排圆点被拼成了算式：{a['lines']}"
    # 反例①b：只有一个形状 + 等号 + 数字 → 多半是正文行末尾蹭到一个墨点，不拼
    g5 = _page()
    _star(g5, int(20 * K), int(60 * K), 12.5 * K)
    EQ(g5, int(50 * K), int(60 * K), 12.5 * K)
    e5 = SY.scan_span(_src(g5), _span([{"x": 70.0, "y": 52.0, "w": 20.0, "h": 16.0,
                                        "text": "16"}]), np, cv2)
    assert e5["lines"] == [], f"只有一个形状的行也被拼成算式：{e5['lines']}"
    # 反例②：行里有中文说明 → 图形属于旁边的图，不拼进句子
    b = SY.scan_span(_src(g), _span(boxes + [
        {"x": 160.0, "y": 52.0, "w": 90.0, "h": 16.0, "text": "一共有多少个"}]), np, cv2)
    assert b["lines"] == [], f"带中文的一行被当成算式重建：{b['lines']}"
    # 反例③：有一个小块认不出来 → 整行放弃（绝不半拼）
    g3 = _page()
    _star(g3, int(20 * K), int(60 * K), 12.5 * K)
    _star(g3, int(50 * K), int(60 * K), 12.5 * K)
    EQ(g3, int(80 * K), int(60 * K), 12.5 * K)
    _cjk_like(g3, int(110 * K), int(60 * K), 11 * K)
    c = SY.scan_span(_src(g3), _span([{"x": 130.0, "y": 52.0, "w": 20.0, "h": 16.0,
                                       "text": "?"}]), np, cv2)
    assert c["lines"] == [], f"有认不出的块却照样拼了：{c['lines']}"
    assert c["n_unknown"] >= 1, f"认不出的块没被计数（这条尺看不见自己漏了什么）：{c}"
    # 反例④：扫描 app 的 logo（一个圆 + 两个方块，没有式子）
    g4 = _page()
    _circle(g4, int(220 * K), int(140 * K), 9 * K)
    _square(g4, int(250 * K), int(140 * K), 7 * K)
    _square(g4, int(275 * K), int(140 * K), 7 * K)
    d = SY.scan_span(_src(g4), _span([]), np, cv2)
    assert d["lines"] == [], f"扫描 app 的 logo 被印成一行算式：{d['lines']}"
t("四道反例：没等号 / 带中文 / 有认不出的块 / 扫描 logo 一律不重建",
  scan_span_refuses_non_equations)


def equals_is_one_sign_not_two_minuses():
    """"＝" 在扫描图上是两根独立的杠。不折叠的话，"★＋★＝20" 会印成
    "★＋★－－20"——那是【一道错的算式】，比读不出来更糟。"""
    g, boxes = _equation_page()
    got = SY.scan_span(_src(g), _span(boxes), np, cv2)
    assert "－－" not in got["lines"][0], f"等号没折叠：{got['lines']}"
    # 反例：只有一根杠时不许凭空长出等号
    g2 = _page()
    for x, kind in ((20, _star), (50, PLUS), (80, _star), (110, lambda gg, a, b, r: cv2.line(
            gg, (int(a - r), b), (int(a + r), b), 0, 3))):
        kind(g2, int(x * K), int(60 * K), 12.5 * K)
    got2 = SY.scan_span(_src(g2), _span([{"x": 130.0, "y": 52.0, "w": 24.0, "h": 16.0,
                                          "text": "20"}]), np, cv2)
    assert all("＝" not in l for l in got2["lines"]), f"一根杠被折成了等号：{got2['lines']}"
t("两根杠＝一个等号；一根杠不许长出一个等号（含反例）",
  equals_is_one_sign_not_two_minuses)


print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
