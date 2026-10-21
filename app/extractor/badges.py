"""彩色题号徽标：白字压在红/粉色圆角方块上（教辅活页最常见）。

为什么需要单独找：RapidOCR 的检测网络会整块漏掉这种「白字＋彩色底」的小方块
（实测周末作业(1).pdf 第 1 页 1/2/4 题、第 2 页 1/3/4 题都没有检出），题号一丢，
整页就被并成一道没有题号的题——用户看到的正是「连线条目被并段」。

做法分两步，各管一件事：
  1. 按颜色/形状找徽标（位置、大小、填充率）；
  2. 把徽标里的白字单独抠出来（只留最大的 1~2 个白色连通块，去掉圆角高光），
     走 RapidOCR 的【只识别】通道。整张图送检测反而读不出来，只识别是 0.99。
"""
from __future__ import annotations

import re
from typing import Any, Callable

# 尺寸都按【页宽的百分比】给，300dpi / 100dpi / 手机照片同一套阈值。
BADGE_W_FRAC = (0.010, 0.050)
BADGE_ASPECT = (0.70, 1.45)
BADGE_FILL_MIN = 0.45

# 白字：高度占徽标的 30%~90%，面积至少 2%（防止把圆角高光当成字）。
DIGIT_H_FRAC = (0.30, 0.90)
DIGIT_W_FRAC = (0.06, 0.80)
DIGIT_AREA_FRAC = 0.02
DIGIT_CONF_MIN = 0.50
DIGIT_RE = re.compile(r"^\d{1,2}$")

# 题号只会在左/上页面边缘那一列；正文里的红色小图标离文字更远。
BADGE_TEXT_GAP_FRAC = 0.10
CJK_LEAD = re.compile(r"^[\u4e00-\u9fff（(]")


def _overlap_frac(badge: tuple[int, int, int, int],
                  item: dict[str, Any]) -> float:
    """OCR 框和徽标的重叠面积占徽标面积的比例。"""
    bx, by, bw, bh = badge
    ix = float(item.get("x") or 0)
    iy = float(item.get("y") or 0)
    iw = float(item.get("w") or 0)
    ih = float(item.get("h") or 0)
    x0, y0 = max(bx, ix), max(by, iy)
    x1, y1 = min(bx + bw, ix + iw), min(by + bh, iy + ih)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return ((x1 - x0) * (y1 - y0)) / max(1.0, float(bw * bh))


def _has_text_on_right(box: tuple[int, int, int, int],
                       items: list[dict[str, Any]], page_w: float) -> bool:
    """徽标右边必须紧跟着一行题干文字，否则它只是装饰图标。"""
    x, y, w, h = box
    x1 = x + w
    for it in items:
        t = str(it.get("text") or "").strip()
        if not t or not CJK_LEAD.match(t):
            continue
        ix = float(it.get("x") or 0)
        iy = float(it.get("y") or 0)
        iw = float(it.get("w") or 0)
        ih = float(it.get("h") or 0)
        if ix < x1 - 2.0 or ix - x1 > page_w * BADGE_TEXT_GAP_FRAC:
            continue
        cy = iy + ih / 2.0
        if y - h * 0.25 <= cy <= y + h * 1.25:
            return True
    return False


def _after_ordinal_marker(box: tuple[int, int, int, int],
                          items: list[dict[str, Any]]) -> bool:
    """徽标左边紧挨着「第」→ 这是课时/章节序号，不是题号。

    OCR 常把「第⑤课时」拆成「第」「5」「课时」三个框，那个 5 会压满徽标。
    不拦的话 cover 分支会把它改成「5.」，成品印成「第 5. 课时」。
    """
    x, y, w, h = box
    for it in items:
        if not str(it.get("text") or "").strip().endswith("第"):
            continue
        ix = float(it.get("x") or 0)
        iy = float(it.get("y") or 0)
        iw = float(it.get("w") or 0)
        ih = float(it.get("h") or 0)
        right = ix + iw
        if right > x + 2.0 or x - right > w * 1.2:
            continue
        cy = iy + ih / 2.0
        if y - h * 0.5 <= cy <= y + h * 1.5:
            return True
    return False


def _digit_mask(sub_bgr, sub_hsv):
    """徽标内部的白字连通块 → (mask, bbox, area)；不成立返回 None。"""
    import cv2
    import numpy as np

    h, w = sub_bgr.shape[:2]
    sat, val = sub_hsv[:, :, 1], sub_hsv[:, :, 2]
    white = (((sat <= 60) & (val >= 195))).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    cands: list[tuple[int, int, int, int, int, int]] = []
    for i in range(1, n):
        x, y, cw, ch, area = (int(stats[i, cv2.CC_STAT_LEFT]),
                              int(stats[i, cv2.CC_STAT_TOP]),
                              int(stats[i, cv2.CC_STAT_WIDTH]),
                              int(stats[i, cv2.CC_STAT_HEIGHT]),
                              int(stats[i, cv2.CC_STAT_AREA]))
        if ch < h * DIGIT_H_FRAC[0] or ch > h * DIGIT_H_FRAC[1]:
            continue
        if cw < w * DIGIT_W_FRAC[0] or cw > w * DIGIT_W_FRAC[1]:
            continue
        if area < w * h * DIGIT_AREA_FRAC:
            continue
        # 圆角方块的高光/描边贴着徽标边，真正的数字缩在中间
        if x <= 1 or y <= 1 or x + cw >= w - 1 or y + ch >= h - 1:
            continue
        cands.append((x, y, cw, ch, area, i))
    if not cands:
        return None
    cands.sort(key=lambda c: c[4], reverse=True)
    best = cands[0]
    group = [best]
    for c in cands[1:]:
        if c[3] < best[3] * 0.70:
            continue
        # 同一行、横向相邻 → 两位数（10、12…）的两个数字
        if c[1] + c[3] < best[1] or best[1] + best[3] < c[1]:
            continue
        gap = max(best[0], c[0]) - min(best[0] + best[2], c[0] + c[2])
        if gap <= w * 0.35:
            group.append(c)
    xs = [c[0] for c in group]
    ys = [c[1] for c in group]
    x2 = [c[0] + c[2] for c in group]
    y2 = [c[1] + c[3] for c in group]
    x0, y0, x1, y1 = min(xs), min(ys), max(x2), max(y2)
    keep = np.zeros_like(white)
    for c in group:
        keep[lab == c[5]] = 1
    return keep[y0:y1, x0:x1], (x0, y0, x1 - x0, y1 - y0), int(keep.sum())


def find_badges(bgr, items: list[dict[str, Any]],
                recognize: Callable[[Any], tuple[str, float]] | None = None
                ) -> list[dict[str, Any]]:
    """图里所有「彩色方块 + 白字 + 右边紧跟题干」的题号，返回 OCR 条目。

    recognize 收到一张黑字白底的数字小图，返回 (文本, 置信度)。单测可以传假函数，
    正式链路传 RapidOCR 的只识别通道。没有 recognize 时只做检测、不猜数字。
    """
    if bgr is None or not getattr(bgr, "size", 0) or recognize is None:
        return []
    import cv2
    import numpy as np

    H, W = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    pink = ((((hue <= 8) | (hue >= 160)) & (sat >= 80) & (val >= 110))
            .astype(np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(pink, 8)
    out: list[dict[str, Any]] = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, cv2.CC_STAT_LEFT]),
                            int(stats[i, cv2.CC_STAT_TOP]),
                            int(stats[i, cv2.CC_STAT_WIDTH]),
                            int(stats[i, cv2.CC_STAT_HEIGHT]),
                            int(stats[i, cv2.CC_STAT_AREA]))
        if w < W * BADGE_W_FRAC[0] or w > W * BADGE_W_FRAC[1]:
            continue
        if h < W * BADGE_W_FRAC[0] or h > W * BADGE_W_FRAC[1]:
            continue
        aspect = w / max(1.0, float(h))
        if not (BADGE_ASPECT[0] <= aspect <= BADGE_ASPECT[1]):
            continue
        if area < w * h * BADGE_FILL_MIN:
            continue
        box = (x, y, w, h)
        # 页眉的「第⑤课时」：数字是课时序号，不是题号（OCR 常拆成三个框）
        if _after_ordinal_marker(box, items):
            continue
        # ① OCR 已经在这块徽标里读到东西 → 不重复注入。但要把题号和题干【切开】：
        #    OCR 常把「2看一看」「5(1)×7」连成一个条目，不插分隔符的话
        #    rules.py 的题号正则（要求 1. / 1、 / （1））永远认不出来。
        #    页眉那个「第4课时」即使 OCR 读成一整条也不会进这里（不以数字开头）；
        #    被拆成「第」「5」「课时」三框的由上面的课时序号判据挡住。
        cover = [it for it in items if _overlap_frac(box, it) >= 0.20]
        if cover:
            for it in cover:
                t = str(it.get("text") or "").strip()
                m = re.match(r"^(\d{1,2})(?![\d.、．])", t)
                if not m:
                    continue
                tail = t[m.end():]
                if not tail or re.match(r"^[\u4e00-\u9fff（(]", tail):
                    it["text"] = m.group(1) + "." + tail
                    it["badge"] = True
            continue
        # ② 右边必须紧跟题干，孤零零的红色图标不算
        if not _has_text_on_right(box, items, float(W)):
            continue
        sub_bgr = bgr[y:y + h, x:x + w]
        sub_hsv = hsv[y:y + h, x:x + w]
        got = _digit_mask(sub_bgr, sub_hsv)
        if not got:
            continue
        mask, _db, _da = got
        pad = max(8, mask.shape[0] // 4)
        img = np.where(mask > 0, 0, 255).astype(np.uint8)     # 黑字白底
        img = np.pad(img, pad, constant_values=255)
        scale = max(2.0, 96.0 / max(1, mask.shape[0]))
        img = cv2.resize(img, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)
        try:
            text, conf = recognize(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
        except Exception:
            continue
        text = str(text or "").strip()
        if not DIGIT_RE.match(text) or text == "0" or float(conf) < DIGIT_CONF_MIN:
            continue
        # 句点只用来让 rules.py 认出"这是题号"，题干里不会再显示它（q_no 单独排）
        out.append({"text": text + ".", "x": float(x), "y": float(y),
                    "w": float(w), "h": float(h), "conf": round(float(conf), 3),
                    "badge": True})
    return out
