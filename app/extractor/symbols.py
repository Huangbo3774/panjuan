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
    弯月    实心度 0.69        圆度 0.41        顶点 11/8–10/5–7
    加号    实心度 0.21–0.28  圆度 0.10–0.13   顶点 8/8/8
    括号    高/宽 1.8          实心度 0.34–0.36
    二维码块 实心度 1.00 填充 0.86（→ 正方形，但那一行没有算式 → 整行拒绝）
"""
from __future__ import annotations

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
    "plus": "＋", "minus": "－", "times": "×", "equals": "＝",
    "paren_open": "（", "paren_close": "）",
    "shape": "〔图〕",       # 是个紧凑图形，但不认识：诚实标出来，别猜
}
SHAPE_LABELS = ("star", "circle", "ring", "square", "triangle", "diamond", "shape")


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
    五角星和正方形的圆度区间也重叠（0.62 vs 0.78），靠实心度+填充率分开。
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
