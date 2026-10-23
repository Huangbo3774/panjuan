"""简单图形符号（★ ● □ △ ＋ － × ( )）的识别与题干重建。

【为什么必须有这一步】
小学数学卷上大量出现「用图形代表数」的题：
    ★＋★＋★＋★＝20        ★＝（   ）      🌙＝（   ）
这些图形在卷面上是【画出来的】——扫描件的像素，不是字符。OCR 只认字，
于是整行只留下"=20 39"这种残渣：题号、分值、配图都在，可题干读不出意思，
家长看到的就是一句看不懂的话（用户原话："你写的东西别人都看不懂是要干啥"）。

【这一模块做什么】
在【已经挖掉 OCR 文字行】的墨迹里，把"一个字符那么大的一坨"挑出来，
按轮廓特征分成 形状（★●□△◆○）和 运算符（＋－×( )），再按 x 顺序和
OCR 读到的碎片拼回这一行。拼不回来就【整行放弃】，绝不半拼：
宁可留"这题请照配图作答"的提示，也不能给孩子一行编出来的算式。

【阈值从哪来】
全部来自真实卷的读数表（E:\\数学卷子\\第三单元练习题.pdf 第 1 页 第 4 题，
27 个小块的实心度/圆度/顶点数/填充率），不是拍脑袋：
    五角星  实心度 0.82–0.85  圆度 0.62–0.65  顶点 7–10/5/5
    弯月    实心度 0.69        圆度 0.41        填充 0.21  径向比 0.00  占空 0.83–0.85
    加号    实心度 0.21–0.28  圆度 0.10–0.13   顶点 8/8/8
    括号    高/宽 1.8          实心度 0.34–0.36
    二维码块 实心度 1.00 填充 0.86（→ 正方形，但那一行没有算式 → 整行拒绝）

【弯月为什么不能只靠实心度】
它和加号都"不凸"，但加号实心度 ≤0.42；和圆、环的区别是【填充率】低（0.21，
圆盘 0.8+）。最稳的一条是【径向外凸】的分布：弯月只有一段弧，开口那侧扫不到墨，
径向比（最近/最远）≈0；圆/星各方向的墨都在。这条同时把"一条斜线/一个破折号"
挡在外面——后者占空只有 0.2 左右，弯月的弧占了 0.83 的圆周。

【花朵的读数来自合成图样，真卷上还没抽到】
判据是"5–8 个胖角"：实心度 0.90、圆度 0.67、填充 0.66、径向比 0.71、占空 0.62。
蘑菇（4 瓣，实心度 0.88）和青蛙（2 瓣，0.90）都是整张配图，不是紧凑符号，
必须留在〔图〕/配图这一侧——它们过不了"5–8 瓣"。
"""
from __future__ import annotations

import os
import re
from typing import Any

# ── 尺寸闸门：符号就是"一个字符那么大"。比这大的是一整张图。 ──
# ⚠️ 下限压得比"一个字"低，是有原因的：真卷上的 ＋ 是 13.7×13.0pt 的【描边】，
# 轮廓面积只有 18pt²；括号是 5.0×15.1pt；等号的两根杠各 4.3×1.4pt。
# 按 6pt/20pt² 卡，这三样全被吃掉，一行算式就只剩星星——行闸门随即整行放弃，
# 真卷那道题一行都没还原出来（实测）。噪声靠的是【行闸门】挡，不是尺寸闸门：
# 一行里必须凑够"形状 + 运算符 + 等号"才允许拼成算式。
SYM_MIN_PT = 4.0
SYM_MAX_PT = 34.0
SYM_MIN_H_PT = 1.0          # 等号/减号是"又扁又宽"的杠，按 6pt 高门槛会被整条丢掉
SYM_MAX_ASPECT = 3.4        # 长宽比再扁/再长就不是一个符号（下划线、破折号、竖线）
SYM_BAR_MAX_ASPECT = 12.0   # 扁杠的上限：真卷的等号杠 10.5:1，超过它的是数轴/横线
SYM_MIN_AREA_PT = 4.0       # 轮廓面积（pt²）下限：等号的一根杠只有 6pt²，再高就吃掉了

# ── 行闸门 ──
MIN_SHAPES_PER_ROW = 2      # 一行里至少这么多个"形状"才值得重建（一个点不算算式）
ROW_MERGE_PT = 5.0          # 相邻两块的水平间隙小于这个值 → 中间不加空格
CJK_IN_ROW_KILLS = True     # 行里带中文说明 → 那是题目文字，图形归图形，不拼进句子

# 形状 → 字符。⚠️ 只用打印字体里【确实有字形】的字符：
# simhei / msyh 有 ★☆●○□△▲◇◆〔〕＝＋×－÷（），但没有 ⭐🌙 这类 emoji，
# 写出 emoji 只会在家长的 PDF 里变成空白方块。
CHARS: dict[str, str] = {
    "star": "★", "circle": "●", "ring": "○", "square": "□",
    "triangle": "△", "diamond": "◆",
    "moon": "〔弯月〕", "flower": "〔花朵〕",
    "plus": "＋", "minus": "－", "times": "×", "equals": "＝",
    "paren_open": "（", "paren_close": "）",
    "shape": "〔图〕",       # 是个紧凑图形，但不认识：诚实标出来，别猜
}
SHAPE_LABELS = ("star", "circle", "ring", "square", "triangle", "diamond",
                "moon", "flower", "shape")


def features(mask, np) -> dict[str, float]:
    """一块墨（0/1 掩码）→ 轮廓特征。cv2 不可用时调用方会整条链路直接放弃。"""
    import cv2
    m = (mask.astype(np.uint8) if hasattr(mask, "astype") else np.asarray(mask)) * 255
    h, w = m.shape
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return {}
    c = max(cnts, key=cv2.contourArea)
    area = float(cv2.contourArea(c))
    per = float(cv2.arcLength(c, True))
    hull = float(cv2.contourArea(cv2.convexHull(c))) or 1.0
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return {}
    on = float(len(xs)) / float(max(1, w * h))
    def _verts(eps: float) -> int:
        return len(cv2.approxPolyDP(c, eps * per, True)) if per > 0 else 0
    # 顶行/中行的"段数"：加号顶行只有中间一竖（1 段），乘号顶行是两条斜臂（2 段）
    def _runs(row: int) -> int:
        line = m[row] > 0
        return int(((line[1:] ^ line[:-1]) & line[1:]).sum()) + (1 if line[0] else 0)

    def _band_x(row: int) -> float:
        """某一行【上下各两像素】这一带的墨的平均 x。"""
        lo, hi = max(0, row - 2), min(h, row + 3)
        sub = m[lo:hi] > 0
        ys2, xs2 = np.nonzero(sub)
        return float(xs2.mean()) if len(xs2) else 0.0
    top = next((i for i in range(h) if (m[i] > 0).any()), 0)
    mid = h // 2
    # 顶边【一小条】里的最大满宽度：扫描图有 1px 抖动，只看一行会误判
    band = range(top, min(h, top + max(1, h // 5)))
    top_w = max((float((m[i] > 0).sum()) / max(1, w)) for i in band)

    # ── 径向外凸计数（"有几个角"）：★ 5 个、□/＋ 4 个、△ 3 个、○ 0 个 ──
    # 为什么非有它不可：五角星有胖有瘦——卷面上圆润的星实心度 0.83，
    # 尖角的星实心度只有 0.55，只靠实心度区间会把尖角星判成"认不出的图形"。
    # "几个角"和胖瘦无关，是星形本身的定义。
    # ⚠️ 必须拿【墨像素】算半径，不能用外轮廓点：fillPoly 画出来的菱形，
    #    轮廓只有 4 个点，按 36 个角度桶取最大半径时 32 个桶是空的，
    #    平滑一次就数出 6 个峰（实测），圆环更被判成五角星。
    px = xs - float(xs.mean())
    py = ys - float(ys.mean())
    ang = np.arctan2(py, px)
    rad = np.hypot(px, py)
    nb = 72
    prof = np.zeros(nb)
    slot = ((ang + 3.14159265358979) / (2 * 3.14159265358979) * nb).astype(int) % nb
    np.maximum.at(prof, slot, rad)
    prof = (prof + np.roll(prof, 1) + np.roll(prof, -1)) / 3.0
    lo, hi = float(prof.min()), float(prof.max())
    lobes = 0
    if hi - lo > 0.10 * max(1.0, hi):
        above = prof > (lo + 0.5 * (hi - lo))
        lobes = int(np.sum(above & ~np.roll(above, 1)))
    return {
        "w": float(w), "h": float(h), "area": area,
        "solidity": area / hull,
        "circularity": (4 * 3.14159265358979 * area / (per * per)) if per > 0 else 0.0,
        "v2": float(_verts(0.02)), "v3": float(_verts(0.03)), "v5": float(_verts(0.05)),
        "fill": on,
        "aspect": float(w) / float(max(1, h)),
        "h_over_w": float(h) / float(max(1, w)),
        # 括号：弯的那一侧鼓出去 → 墨的质心偏离框中心。"（"偏左，"）"偏右
        "cx_off": float(xs.mean() / max(1, w) - 0.5),
        "runs_top": float(_runs(top)), "runs_mid": float(_runs(mid)),
        "lobes": float(lobes),
        # 径向剖面的两个"形状指纹"（都从同一份 prof 来，不另算一遍）：
        #   prof_ratio = 最近/最远。弯月开口那侧没有墨 → ≈0；圆/星/方框都 >0.4。
        #   duty = 半径超过"半高"的角度占比。细尖星 0.38、胖花瓣 0.62、弯月 0.83，
        #          一条斜线只有 0.2（它根本不是环住的形状）。
        "prof_ratio": (lo / hi) if hi > 0 else 0.0,
        "duty": float((prof > (lo + 0.5 * (hi - lo))).mean()) if hi > lo else 0.0,
        # 括号朝哪边开口：弧线【最弯的那一侧】墨最多。用"顶端的 x − 中段的 x"判，
        # 不用质心偏移 —— 质心会被线宽带偏（画粗一点的"）"质心反而偏左，实测翻车）。
        "tip_off": float(_band_x(top) - _band_x(mid)),
        # 正方形【顶边满宽】，菱形【顶边只有一个尖】——这是两者唯一稳定的差别：
        # 空心正方形和菱形的实心度/顶点数完全一样（4 顶点、外轮廓凸）。
        "top_w": top_w,
        "ink_pt": area / 1.0,
    }


def classify(f: dict[str, float]) -> str | None:
    """特征 → 标签；认不出返回 None（调用方据此【放弃整行】，不许猜）。

    判定顺序是有讲究的：先判"又高又窄"的括号，再判运算符，最后才判形状。
    括号和加号的实心度区间是重叠的（0.21 vs 0.34），靠长宽比分开；
    五角星和正方形的圆度区间也重叠（0.62 vs 0.78），靠实心度+填充率分开；
    花朵和星都"有 5–6 个角"，胖花瓣（占空 0.62）排在细尖星（0.38）前面。
    """
    if not f:
        return None
    sol, cir, fill = f["solidity"], f["circularity"], f["fill"]
    asp, how, v3 = f["aspect"], f["h_over_w"], int(f["v3"])
    lobes = int(f["lobes"])
    # ── 先挡"像汉字的墨"：外轮廓是个方方正正的框（实心度≥0.9），
    #    中间一行却被三笔以上横切 → 那是【一个字的笔画】，不是符号。
    #    （OCR 行框和字实际位置常差半行，没挖干净的文字会漏到这里。
    #     为什么要加"实心度"这一半：卷面上的★是【描边】画的，中间一行
    #     正好被左右两条边各切两段 = 4 段，只看段数会把真五角星挡掉——
    #     实测这条把第三单元练习题那道题整个挡死了。汉字的轮廓是满的，
    #     五角星描边的轮廓凹，实心度 0.83 < 0.90，一分就开。）
    if f["runs_mid"] >= 3 and sol >= 0.90:
        return None
    # ── 扁杠：减号（一根）／等号的两根（配对在 _fold_equals 里做） ──
    if asp >= 2.2 and sol >= 0.70 and f["top_w"] >= 0.7:
        return "minus"
    # ── 括号：又高又窄，外轮廓不凸（弧线的实心度天然低） ──
    # 用实心度而不是填充率区分"（"和"1"：弧的实心度 0.36–0.67，
    # 一根竖的实心度 ≥0.9；填充率反而分不开（扫描图上弧线的框很窄，填充率会虚高）。
    if how >= 1.4 and asp <= 0.75 and sol <= 0.80:
        return "paren_open" if f["tip_off"] > 0 else "paren_close"
    # ── 十字 / 叉：极凹（★最凹也有 0.45，弯月 0.69，方框 1.0，只有 ＋/× 会低于 0.42） ──
    if 0.6 <= asp <= 1.6 and sol <= 0.42:
        return "times" if f["runs_top"] >= 2 else "plus"
    # ── 形状 ──
    if 0.6 <= asp <= 1.6:
        if v3 == 3 and sol >= 0.85:
            return "triangle"
        if v3 == 4 and sol >= 0.85:
            # 顶边满宽 → 正方形（空心也算，卷面上的方框就是空心正方形）；
            # 顶边只有一个尖 → 菱形。
            return "square" if f["top_w"] >= 0.7 else "diamond"
        if sol >= 0.88 and cir >= 0.78:
            return "circle" if fill >= 0.66 else "ring"
        # 弯月：一段弧围出大半个圆，开口那侧扫不到墨。
        # 三条一起看才稳：径向比≈0（有开口）、占空≥0.55（是一条长弧，不是一根斜线）、
        # 填充率≤0.40（弧之间是空的，不是圆盘）。五角星 lobes 5–6，被 lobes≤3 挡掉。
        if (sol <= 0.80 and fill <= 0.40 and cir <= 0.55 and lobes <= 3
                and f["top_w"] <= 0.40 and f["prof_ratio"] <= 0.18
                and f["duty"] >= 0.55):
            return "moon"
        # 花朵：5–8 个【胖】角（占空≥0.5，星那种细尖只有 0.38）。
        # 必须排在星前面——胖花瓣的星角数也会落进 5–6，会被星抢走。
        # 蘑菇 4 瓣、青蛙 2 瓣过不了瓣数，仍留在配图/〔图〕。
        if (sol >= 0.85 and cir >= 0.55 and fill >= 0.45
                and 5 <= lobes <= 8 and f["top_w"] <= 0.60
                and f["prof_ratio"] >= 0.55 and f["duty"] >= 0.50):
            return "flower"
        # 五角星：五个/六个角（顶点数或径向峰都算，扫描图上两者会各抽风一次），
        # 且【不凸】——方框/圆盘的实心度 ≥0.88，已经被上面几条挑走了。
        if (lobes in (5, 6) or v3 in (5, 6)) and sol <= 0.88 and cir <= 0.76:
            return "star"
    return "shape" if 0.5 <= asp <= 2.0 and fill >= 0.10 else None


def char_of(label: str) -> str:
    return CHARS.get(label, "")


def _rows(items: list[dict], np) -> list[list[dict]]:
    """按 y 中心把小块墨分成"行"。同一行的符号才可能是一句算式。"""
    if not items:
        return []
    items = sorted(items, key=lambda it: (it["yc"], it["x"]))
    rows: list[list[dict]] = [[items[0]]]
    for it in items[1:]:
        cur = rows[-1]
        span = max(ROW_MERGE_PT, 0.6 * max(e["h"] for e in cur))
        if it["yc"] - cur[-1]["yc"] <= span:
            cur.append(it)
        else:
            rows.append([it])
    return rows


def _line(row: list[dict], texts: list[dict], np) -> str:
    """一行：符号块 + OCR 碎片按 x 排开，水平间隙小于 ROW_MERGE_PT 的不加空格。

    间隙用【真实右边界】算，不用"字符数×某个宽度"估：★ 是 25pt，＋ 是 13pt，
    估出来的间距会把卷面上挨着的东西印成 "★ ＋ ★"。
    """
    items = [(it["x"], it["x"] + it["w"], it["ch"]) for it in row]
    items += [(float(t["x"]), float(t["x"]) + float(t["w"]), str(t.get("text") or "").strip())
              for t in texts if _in_row(t, row)]
    items = [i for i in sorted(items, key=lambda i: i[0]) if i[2]]
    out = ""
    prev_end = None
    for x0, x1, s in items:
        if prev_end is not None and x0 - prev_end > ROW_MERGE_PT:
            out += " "
        out += s
        prev_end = max(prev_end or 0.0, x1)
    return out


def _in_row(t: dict, row: list[dict]) -> bool:
    """OCR 碎片和这一行符号的 y 区间有没有重叠（重叠一半以上才算同一行）。"""
    ty0, ty1 = float(t["y"]), float(t["y"]) + float(t["h"])
    sy0 = min(r["y"] for r in row)
    sy1 = max(r["y"] + r["h"] for r in row)
    ov = min(ty1, sy1) - max(ty0, sy0)
    return ov >= 0.5 * min(ty1 - ty0, sy1 - sy0)


def _fold_equals(items: list[dict]) -> list[dict]:
    """两根上下对齐的扁杠 = 一个等号。

    卷面上的"＝"是两条独立墨（扫描阈值下从不连成一块），连通域只会看到两个"－"。
    不折叠的话，"★＋★＝20" 会印成"★＋★－－20"——那是错的算式，比读不出更糟。
    """
    bars = [it for it in items if it["label"] == "minus"]
    used: set[int] = set()
    out: list[dict] = [it for it in items if it["label"] != "minus"]
    for a in bars:
        if id(a) in used:
            continue
        best = None
        for b in bars:
            if b is a or id(b) in used:
                continue
            dx = abs(a["x"] - b["x"]) + abs(a["w"] - b["w"]) * 0.5
            dy = abs((a["y"] + a["h"] / 2) - (b["y"] + b["h"] / 2))
            if dx <= 3.0 and 1.2 <= dy <= max(9.0, 1.2 * max(a["h"], b["h"])):
                best = b
                break
        if best is None:
            out.append(a)
            used.add(id(a))
            continue
        x0 = min(a["x"], best["x"])
        y0 = min(a["y"], best["y"])
        w0 = max(a["x"] + a["w"], best["x"] + best["w"]) - x0
        h0 = max(a["y"] + a["h"], best["y"] + best["h"]) - y0
        out.append({"x": x0, "y": y0, "w": w0, "h": h0, "yc": y0 + h0 / 2.0,
                    "label": "equals", "ch": char_of("equals")})
        used.add(id(a))
        used.add(id(best))
    return out


def scan_span(src: Any, span: dict, np, cv2) -> dict[str, Any]:
    """一道题的区间 → {lines, n_shapes, n_unknown, rows}；读不出就 lines 为空。

    墨迹、挖字、页脚墙全部复用 figures._scan —— 同一份中间量，
    免得"裁图看到的"和"认符号看到的"是两张不同的图（本项目吃过抄一遍就走样的亏）。
    """
    from .figures import _scan
    from .rules import is_furniture_text
    sc = _scan(src, span, np, cv2)
    if not sc:
        return {"lines": [], "n_shapes": 0, "n_unknown": 0, "rows": []}
    band, k = sc["band"], sc["k"]
    ink = band.astype(np.uint8) * 255
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(ink, connectivity=8)
    items: list[dict] = []
    for i in range(1, n):
        x, y, w, h, _a = [int(v) for v in stats[i]]
        w_pt, h_pt = w / k, h / k
        if not (SYM_MIN_PT <= w_pt <= SYM_MAX_PT and SYM_MIN_H_PT <= h_pt <= SYM_MAX_PT):
            continue
        aspect = max(w_pt, h_pt) / max(1e-6, min(w_pt, h_pt))
        bar = w_pt >= SYM_MIN_PT * 2 and h_pt < SYM_MIN_PT      # 扁杠：等号/减号
        if aspect > (SYM_BAR_MAX_ASPECT if bar else SYM_MAX_ASPECT):
            continue
        f = features(band[y:y + h, x:x + w], np)
        # 面积要换算成 pt² 再比：features 里的 area 是【像素²】，
        # 直接和 pt 阈值比等于把门槛放大 k² 倍（100dpi 下 1.93 倍），
        # 小符号会被静默吃掉——这类单位错正是最难发现的一种。
        if not f or f["area"] / (k * k) < SYM_MIN_AREA_PT:
            continue
        lab = classify(f)
        items.append({"x": (x + sc["cx0"]) / k, "y": (y + sc["y0"]) / k,
                      "w": w_pt, "h": h_pt, "yc": (y + h / 2.0 + sc["y0"]) / k,
                      "label": lab, "ch": char_of(lab) if lab else ""})
    items = _fold_equals(items)
    texts = [t for t in (span.get("text_boxes") or [])
             if str(t.get("text") or "").strip() and not is_furniture_text(str(t.get("text") or ""))]
    lines, n_shapes, n_unknown = [], 0, 0
    for row in _rows(items, np):
        unknown = [it for it in row if not it["label"]]
        shapes = [it for it in row if it["label"] in SHAPE_LABELS]
        ops = [it for it in row if it["label"] and it["label"] not in SHAPE_LABELS]
        near = [t for t in texts if _in_row(t, row)]
        # ── 只重建【像算式】的行，其余一律不碰题干 ──────────────────
        # 四条判据各挡一类真实误伤（读数来自这份真卷 8 页全量跑）：
        #   ① 至少 2 个形状 + 1 个运算符：挡"一个墨点 + 一行说明文字"；
        #   ② 行内必须有等号（图形自己算出来的 ＝，或 OCR 读到的 =/＝）：
        #      挡"数一数"的圆点阵、"连一连"的箭头堆 —— 它们是【图】，不是式子，
        #      图该走配图，不该被拼成一行文字（实测没有这条时，
        #      "◆×◆ ◆ ◆×◆ ◆"这种鬼东西会被印进题干）；
        #   ③ 行里出现中文 → 那是题目说明，图形属于旁边的图，不拼进句子
        #      （没有这条：「□的个数是的5倍，画出□」这种半截话会取代原题干）；
        #   ④ 有一个小块认不出来 → 整行放弃（宁可少一行，不给一行编出来的算式）。
        has_eq = any(it["label"] == "equals" for it in row) or \
            any(("=" in str(t.get("text") or "")) or ("＝" in str(t.get("text") or "")) for t in near)
        has_cjk = any(re.search(r"[\u4e00-\u9fff]", str(t.get("text") or "")) for t in near)
        if len(shapes) < MIN_SHAPES_PER_ROW or not ops or not has_eq:
            continue
        if unknown or (has_cjk and CJK_IN_ROW_KILLS):
            n_unknown += len(unknown)
            continue                                  # 认不全 / 是说明句 → 放弃这一行
        lines.append(_line(row, near, np))
        n_shapes += len(shapes)
    return {"lines": [l for l in lines if l.strip()], "n_shapes": n_shapes,
            "n_unknown": n_unknown, "rows": items}


# ── 大题标题里的作答标记：P6「四、笔算（打▲的要验算）」被 OCR 读成「打的」 ──
# 为什么单独做：这个 ▲ 只有 6.5pt 高，RapidOCR 把整块吞掉（放大 4/8 倍重跑也认不出），
# 只剩「打的」两个字。可它是【全大题的要求】——漏了它，孩子不知道哪些竖式要验算，
# 27 道题都做错方向，属于 P1。只能回到墨迹里认。
#
# 规则的保守口径：只在「打…的」这一处缺口上工作，且必须在这一行里找到
# 【唯一一个字形大小的标记】。找不到 / 找到两个 / 候选位置不在缺口附近 —— 一律
# 原样保留。宁可少补一个符号，也绝不许把「、」的小墨点或某个汉字的偏旁塞进标题。
SEC_MARK_RE = re.compile(r"打[ \t\u3000]{0,2}的")
MARK_LABELS = ("triangle", "star", "square", "diamond", "circle", "ring")


def _mark_char(label: str, fill: float) -> str:
    """标记类别 + 填充率 → 字符。用打印字体里确实有的字形（见 CHARS 的说明）。"""
    if label == "triangle":
        return "▲" if fill >= 0.40 else "△"
    if label == "star":
        return "★" if fill >= 0.45 else "☆"
    if label == "circle":
        return "●" if fill >= 0.60 else "○"
    if label == "square":
        return "■" if fill >= 0.60 else "□"
    if label == "diamond":
        return "◆" if fill >= 0.50 else "◇"
    return ""


def _char_unit(ch: str) -> float:
    """估算一个字符占几个全角字宽（数字/字母/半角空格按半个）。"""
    if ch == "\u3000":
        return 1.0
    if ch.isspace() or ord(ch) < 128:
        return 0.5
    return 1.0


def _norm_line(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _section_mark_from_source(src: Any, a: dict, np, cv2) -> str:
    """标题行 → 被吞掉的标记字符；认不出 / 不唯一就返回空串。

    单独拆出来是给测试用的：合成的标题图能直接喂进来，不必伪造整份任务。
    """
    try:
        from .figures import _scan
        page = int(a.get("page") or 1)
        text = str(a.get("text") or "")
        if not SEC_MARK_RE.search(text):
            return ""
        # 只扫标题这一行：左右各留 6pt、上下各留 1.5pt。
        # text_boxes 必须为空 —— 带着本行文字框进 _scan 会把整行字挖成洞（P6 实测 0 块墨）。
        span = {"q_index": -1, "page": page, "col": int(a.get("col") or 0),
                "x0": max(0.0, float(a["x"]) - 6.0),
                "x1": float(a["x"]) + float(a["w"]) + 6.0,
                "y0": float(a["y"]) - 1.5,
                "y1": float(a["y"]) + float(a["h"]) + 1.5,
                "text_boxes": []}
        sc = _scan(src, span, np, cv2)
        if not sc:
            return ""
        band, k = sc["band"], sc["k"]
        if band.size == 0:
            return ""
        nc, _lab, stats, _cent = cv2.connectedComponentsWithStats(
            band.astype(np.uint8) * 255, connectivity=8)
        comps: list[tuple[float, float, float, float, int]] = []
        heights: list[float] = []
        for i in range(1, nc):
            x, y, w, h, _area = [int(v) for v in stats[i]]
            w_pt, h_pt = w / k, h / k
            if w_pt < 0.8 or h_pt < 1.0:
                continue
            comps.append(((x + sc["cx0"]) / k, (y + sc["y0"]) / k, w_pt, h_pt, i))
            if h_pt >= 2.0:
                heights.append(h_pt)
        if not comps or not heights:
            return ""
        cols = band.any(axis=0)
        nz = np.nonzero(cols)[0]
        if len(nz) == 0:
            return ""
        ix0 = (int(nz[0]) + sc["cx0"]) / k
        ix1 = (int(nz[-1]) + 1 + sc["cx0"]) / k
        row_h = float(np.median(heights))
        # 缺字槽：OCR 行少了这一个字符，所以按「有标记」的字符数算总宽。
        mt = SEC_MARK_RE.search(text)
        if not mt:
            return ""
        cut = mt.start() + 1
        units = [_char_unit(c) for c in text]
        total = sum(units) + 1.0
        u_units = (ix1 - ix0) / max(1e-6, total)
        # 两种尺取平均：按字符数均分（标点/数字宽度会偏）＋ 中文字高（等宽字体
        # 的字宽常等于字高）。P6 实测两种各偏 1pt 以内，平均后落点±0.5 字宽。
        u = 0.5 * (u_units + row_h)
        sx0 = ix0 + sum(units[:cut]) * u
        slot_c = sx0 + 0.5 * u
        # 标记是一个字那么大：比「、」的墨点大得多，比配图小得多。
        min_h = 0.55 * row_h
        min_w = 0.30 * row_h
        cands: list[tuple[float, str]] = []
        for x, y, w_pt, h_pt, i in comps:
            if h_pt < min_h or w_pt < min_w or w_pt > 2.6 * row_h:
                continue
            xc = x + w_pt / 2.0
            if not (ix0 - 2.0 <= xc <= ix1 + 2.0):
                continue
            # ⚠️ 不能要求「整行只有一个标记」：数字 4 的墨块会被判成 star
            #    （P6 实测 fill=0.56），和真的 ▲ 撞车。只认【落在缺口附近】
            #    的那一个 —— 缺口是行内唯一说得通的位置。
            if abs(xc - slot_c) > 1.6 * u:
                continue
            x, y, w, h, _area = [int(v) for v in stats[i]]
            fe = features(band[y:y + h, x:x + w], np)
            lab = classify(fe) if fe else None
            if lab not in MARK_LABELS:
                continue
            ch = _mark_char(lab, float(fe.get("fill") or 0.0))
            if ch:
                cands.append((xc, ch))
        return cands[0][1] if len(cands) == 1 else ""
    except Exception:
        return ""


def repair_section_marks(sections: list[dict], ann: list[dict], r: dict) -> int:
    """补回大题标题里被 OCR 吞掉的作答标记（如「打▲的」读成「打的」）。

    返回补了几个大题。改名时把原 OCR 行文本存进 `sec["ocr_name"]`：
    裁图链路（lines.spans_for_questions）要拿它定位大题标题这堵「硬墙」，
    否则标题一改，span 就找不到锚点、会越过页底漫到下一大题。
    """
    if not sections or not ann or not r:
        return 0
    try:
        import numpy as np
        import cv2
        from . import lines as L
    except Exception:                                  # 缺 OCR/OpenCV 的纯文本入口
        return 0
    fixed = 0
    cursor = 0
    for sec in sections:
        name = str(sec.get("name") or "")
        m = SEC_MARK_RE.search(name)
        if not m:
            continue
        key = _norm_line(sec.get("ocr_name") or name)
        n = -1
        for j in range(cursor, len(ann)):
            if _norm_line(str(ann[j].get("text") or "")) == key:
                n = j
                break
        if n < 0:
            continue
        cursor = n + 1
        a = ann[n]
        try:
            page = int(a.get("page") or 1)
            files = r.get("files") or []
            fi = (r.get("page_sources") or {}).get(page)
            if fi is None or not (0 <= int(fi) < len(files)):
                continue
            f = files[int(fi)]
            kind = str(f.get("kind") or "")
            if not kind:
                kind = os.path.splitext(str(f.get("name") or f.get("path") or ""))[1].lower()
            src = L.open_page_source(kind, "", page, r.get("page_sources") or {}, files)
            if not src:
                continue
            ch = _section_mark_from_source(src, a, np, cv2)
            if not ch:
                continue
            sec["ocr_name"] = str(sec.get("ocr_name") or name)
            # 插在「打」后面；OCR 若在中间留了空格，顺手收掉，别印成「打▲ 的」。
            new_name = (name[:m.start() + 1] + ch
                        + name[m.start() + 1:].lstrip(" \t\u3000"))
            sec["name"] = new_name
            for q in sec.get("questions") or []:
                if q.get("section"):
                    q["section"] = new_name
            fixed += 1
        except Exception:
            continue                                   # 单个标题失败不拖垮整卷
    return fixed
