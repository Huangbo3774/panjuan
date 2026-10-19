"""把任务里的原始材料变成「已按阅读顺序排好的文本行」，供 extractor 切题（PRD §5.1）。

路由口径与打印链路一致但判据不同：
  · 打印（模式 A）不需要文字，图片直接排版；
  · 在线作答（模式 B/C）必须有文本，所以扫描页只能走 OCR。
    真实材料 6 份 PDF 里 5 份完全没有文本层 ⇒ 不接 OCR 的话，在线作答覆盖不到六分之一。

⚠️ 两条硬性顺序要求（都实测踩过）：
  1. 逐页路由，不能整份文档一刀切：混合卷（前几页文字层、后几页扫描）很常见。
  2. 文本条目必须先过 layout.columns.structure_page 归位再拼行：
     OCR/文本层返回的都是引擎自己的顺序，双栏卷会跨栏穿插。
"""
from __future__ import annotations

import os
import re
from typing import Any

import pymupdf

from . import ocr as O
from ..layout.columns import detect_columns, structure_page
from ..parsers.pdf import SCAN_TEXT_THRESHOLD


# ── 装订栏（竖排"学校/班级/姓名/学号"、"密封线内不要答题"）─────────────
# 它必须【在合并成行之前】就被丢掉：这些竖排单字和正文同一水平线，
# 一旦进了 group_lines 就会变成「1. 学号： 线 小朋友们，准备好…」
# 「…后面是（ 封」这种题干（真实卷：综合实践单元.pdf 841×653 横版两张 A4，
# 左右各有一条装订栏），用户说的"排版变形严重"根子就在这。
MARGIN_ZONE_PT = 45.0
MARGIN_BOILER = re.compile(r"学校|班级|姓名|学号|密封|内线|不要答题|不许答题|弥\s*封|封\s*线")
MARGIN_MAX_CHARS = 2       # 贴边且只有一两个字（弥/封/线/号…）＝装订栏的竖排字
# 贴页边、≤6 个字、又不含任何数字/标点/括号的，是【侧边栏色块】上的科目名
# （真实卷："综合实践·画校园路线图"、"第三单元 数与乘法"、"拍照秒批"、"视频讲解"）。
# 正文行几乎必然带数字或括号填空，所以这条不误杀；它们会混进正文行末尾：
# "左边是( ),右边是( 综合实践" —— 用户说的"排版变形"就是这个样子。
MARGIN_TAB_CHARS = 6


def _is_margin_tab(t: str) -> bool:
    if len(t) > MARGIN_TAB_CHARS:
        return False
    return not re.search(r"[0-9０-９（）()。、，,.．!！?？:：;；—…]", t)


def drop_margin_items(items: list[dict[str, Any]], page_w: float
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把整条落在页边装订带里、且是装订栏/侧边栏字样的条目挑出来。

    两个条件同时成立才丢，防误杀：
      ① 【整个框】都在物理页边 45pt 以内。⚠️ 必须是"框右边也 ≤45"而不是"框左边 ≤45"：
         横版两张 A4 的卷子左半正文就从 x≈45 起笔，用左边判会把题干里
         短到两三个字的行尾（"）。"、"）,"）当成装订栏吃掉 ——
         实测第一版就这么把"…一端指（ ），一端指（ ）。"咬成了"…一端指("，
         用户看到的是"题目读不通"，比混进装订栏更糟。
      ② 文字是装订栏套话 / 短到 ≤2 个字（竖排每字一个框）
        / ≤6 个字的纯词（侧边栏科目名，不含任何数字与标点）。
    """
    keep: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for it in items:
        t = str(it.get("text") or "").strip()
        x0, x1 = float(it["x"]), float(it["x"]) + float(it.get("w") or 0)
        in_edge = x1 <= MARGIN_ZONE_PT or x0 >= page_w - MARGIN_ZONE_PT
        if in_edge and t and (len(t) <= MARGIN_MAX_CHARS or MARGIN_BOILER.search(t)
                              or _is_margin_tab(t)):
            dropped.append(it)
            continue
        keep.append(it)
    return keep, dropped


def _items_from_page(page) -> list[dict[str, Any]]:
    """文本层 → 带坐标的条目。必须用 get_text("dict") 拿行级坐标，
    用 blocks 会把表格的列切成整块，横向阅读顺序就丢了。"""
    items: list[dict[str, Any]] = []
    for blk in page.get_text("dict").get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            t = "".join(s.get("text", "") for s in ln.get("spans", []))
            if not t.strip():
                continue
            bb = ln["bbox"]
            items.append({"text": t.strip(), "x": bb[0], "y": bb[1],
                          "w": max(bb[2] - bb[0], 1), "h": max(bb[3] - bb[1], 1)})
    return items


def ordered_lines(items: list[dict[str, Any]], page_w: float) -> list[str]:
    """条目 → 阅读顺序文本行（先分栏归位，再栏内合并）。"""
    if not items:
        return []
    st = structure_page(items, page_w, y_tol=max(8, min(20, page_w / 60)))
    return [l["text"] for l in st["lines"]]


def lines_from_pdf(path: str, work_dir: str | None = None, dpi: int = 300,
                   progress=None) -> dict[str, Any]:
    """只要文本行时用这个（内部走 annotated_lines_from_pdf）。"""
    r = annotated_lines_from_pdf(path, work_dir=work_dir, dpi=dpi, progress=progress)
    return {k: r[k] for k in ("lines", "pages", "ocr_conf", "needs_review", "errors")}


def annotated_lines_from_pdf(path: str, work_dir: str | None = None, dpi: int = 300,
                             progress=None) -> dict[str, Any]:
    """逐页路由 + 保留坐标。

    返回 {"lines":[文本行…], "ann":[{text,page,x,y,w,h}（单位 pt）],
          "pages":[{page,route,lines,width_pt,height_pt}], "ocr_conf", "errors"}

    ⚠️ 坐标必须统一到 pt：文本层本来就是 pt，OCR 拿到的是渲染图的 px，
       不换算的话裁图会按 300/72 的倍率偏出去（裁到页面外，图直接是空的）。
    """
    doc = pymupdf.open(path)
    lines: list[str] = []
    ann: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    confs: list[float] = []
    errors: list[str] = []
    margin_dropped = 0
    noise: list[dict[str, Any]] = []
    try:
        for i, page in enumerate(doc):
            page_no = i + 1
            width_pt = page.rect.width or 1
            items = _items_from_page(page)
            chars = len("".join((page.get_text("text") or "").split()))
            route = "text"
            if chars < SCAN_TEXT_THRESHOLD or not items:
                ok, why = O.available()
                if not ok:
                    errors.append(f"第 {page_no} 页需要 OCR，但引擎不可用：{why}")
                    pages.append({"page": page_no, "route": "ocr-missing", "lines": 0,
                                  "width_pt": width_pt, "height_pt": page.rect.height})
                    continue
                if progress:
                    progress(page_no, doc.page_count, os.path.basename(path))
                pix = page.get_pixmap(dpi=dpi)
                tmp = work_dir or os.path.join(os.path.dirname(os.path.abspath(path)), "_ocr")
                os.makedirs(tmp, exist_ok=True)
                fp = os.path.join(tmp, f"lines_p{page_no}.png")
                pix.save(fp)
                try:
                    raw = O.ocr_image(fp)
                finally:
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
                # px → pt：渲染时是 dpi/72 倍放大，所以 1pt = dpi/72 px。
                sc = 72.0 / dpi
                items = [{**it, "x": it["x"] * sc, "y": it["y"] * sc,
                          "w": it["w"] * sc, "h": max(it["h"] * sc, 1)} for it in raw]
                confs += [it["conf"] for it in raw]
                width_pt = pix.width * sc or width_pt
                route = "ocr"
            # 装订栏必须在【合并成行之前】摘掉，否则竖排单字会混进题干
            items, margin = drop_margin_items(items, width_pt)
            margin_dropped += len(margin)
            noise += [{"x": m["x"], "y": m["y"], "w": m.get("w", 0), "h": m.get("h", 0),
                       "page": page_no} for m in margin]
            # 栏界先用墨迹复核一遍再决定（只看文本框投影会把图形占的地方当成栏缝）
            cand = detect_columns(items, width_pt)
            if len(cand) > 1:
                cand = verify_bands_with_ink(page, cand, width_pt)
            got, bands = _ordered_items(items, width_pt, bands=cand)
            for g in got:
                g["page"] = page_no
                ann.append(g)
                lines.append(g["text"])
            pages.append({"page": page_no, "route": route, "lines": len(got),
                          "width_pt": width_pt, "height_pt": page.rect.height,
                          "columns": len(bands), "bands": bands,
                          "margin_dropped": len(margin)})
    finally:
        doc.close()
    return {"lines": lines, "ann": ann, "pages": pages, "noise": noise,
            "ocr_conf": round(sum(confs) / len(confs), 3) if confs else 1.0,
            "needs_review": any(p["route"] == "ocr-missing" for p in pages),
            "errors": errors}


def verify_bands_with_ink(page, bands: list[dict[str, float]], page_w: float,
                          dpi: int = 72) -> list[dict[str, float]]:
    """用页面**墨迹**复核栏界。文字框投影稀疏不等于栏缝 —— 那里往往正是图形占的位置。

    实测：综合实践单元.pdf 第 1 页（841×653pt，两张 A4 并排）真实墨迹只有
    一条缝（403–462pt，带内墨占比 0.11%），但只看文本框投影会切出 **4 栏**，
    多出的两条假缝导致：① 一张图被从中间劈开；② 左侧竖排"学校/班级/姓名/学号"
    自成一栏，裁图时冒出一堆 36×150 的细长条垃圾。

    真栏缝的判据：这条竖带（±1% 页宽）在正文高度范围内基本【没有墨】。
    太窄的栏带（<8% 页宽）一律并进邻居 —— 装订线、侧栏不该成为一道墙。
    """
    if len(bands) <= 1:
        return bands
    import numpy as np
    try:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        g = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    except Exception:
        return bands
    ink = g < 160
    H, W = ink.shape
    rows = np.flatnonzero(ink.any(axis=1))
    if len(rows) < 12:
        return bands
    top, bot = int(rows[0]), int(rows[-1])
    # 正文高度范围内"每一列有多少行是黑的"→ 找出真正的竖直空白带
    frac = ink[top:bot + 1, :].mean(axis=0)
    runs: list[tuple[int, int]] = []
    start = None
    min_w = max(3, int(W * 0.012))
    for x in range(W):
        empty = frac[x] <= 0.02
        if empty and start is None:
            start = x
        elif not empty and start is not None:
            if x - start >= min_w:
                runs.append((start, x))
            start = None
    if start is not None and W - start >= min_w:
        runs.append((start, W))
    if not runs:
        return [bands[0]] if len(bands) == 1 else bands
    centers = [((a + b) / 2.0) / W * page_w for a, b in runs]      # px → pt

    keep: list[float] = []
    for b in bands[1:]:
        x_pt = float(b["x0"])
        # 文本检测只能给个大概位置：真实空白带常在它旁边几十 pt（实测 403 vs 406–466）。
        # 所以在候选附近 ±10% 页宽内找一条真空白带，吸附到它的中心；找不到就判假缝。
        near = [c for c in centers if abs(c - x_pt) <= page_w * 0.10]
        if not near:
            continue
        snap = min(near, key=lambda c: abs(c - x_pt))
        if any(abs(snap - k) < page_w * 0.06 for k in keep):       # 两条候选吸到同一条缝 → 只留一份
            continue
        keep.append(snap)
    keep.sort()
    edges = [0.0] + keep + [float(page_w)]
    out = [{"x0": edges[i], "x1": edges[i + 1]} for i in range(len(edges) - 1)]
    i = 0
    while i < len(out) and len(out) > 1:
        if (out[i]["x1"] - out[i]["x0"]) / max(1.0, page_w) < 0.08:
            if i == 0:
                out[1]["x0"] = out[0]["x0"]
                out.pop(0)
            else:
                out[i - 1]["x1"] = out[i]["x1"]
                out.pop(i)
            i = max(0, i - 1)
        else:
            i += 1
    return out


def _ordered_items(items: list[dict[str, Any]], page_w: float,
                   bands: list[dict[str, float]] | None = None
                   ) -> tuple[list[dict[str, Any]], list[dict[str, float]]]:
    """条目 → 阅读顺序的【带坐标 + 带栏号】行。

    ⚠️ `col` 必须带出去：裁图阶段要知道每行属于哪一栏，否则只能按"整页宽的纵向条带"
       去圈图形 —— 横版两张 A4 并排的卷（真实材料：综合实践单元.pdf 841×653pt）
       就会把隔壁半页的图一起框进来，用户原话"你截图都把右边跟他没有关系的截过来了"。
       以前 structure_page 算好了栏、这里却把 col 丢了，等于手里有尺不用。
    """
    if not items:
        return [], [{"x0": 0.0, "x1": float(page_w or 0)}]
    st = structure_page(items, page_w, y_tol=max(8, min(20, page_w / 60)), bands=bands)
    out = [{"text": l["text"], "x": l.get("x", 0), "y": l.get("y", 0),
            "w": l.get("w", 0), "h": l.get("h", 1), "col": int(l.get("col", 0))}
           for l in st["lines"]]
    return out, [{"x0": float(b["x0"]), "x1": float(b["x1"])} for b in st.get("bands") or []]


SECTION_RE = re.compile(r"^[一二三四五六七八九十百]+\s*[、.．,，]")


def spans_for_questions(ann: list[dict[str, Any]], questions: list[dict[str, Any]],
                        pages: list[dict[str, Any]] | None = None,
                        sections: list[dict[str, Any]] | None = None
                        ) -> list[dict[str, Any]]:
    """每道题在源页上的【所属栏内】区间 + 该区间内的文字行框（裁图要用）。

    两条必须按真实卷立的规矩（都是被用户指着说"问题百出"的那两处）：

    1) **区间下界只能看同一页、同一栏的下一个锚点。**
       原来取"全局下一题的首行"，而横版两张 A4 并排的卷（真实材料
       综合实践单元.pdf 841×653pt）左栏第 5 题的"下一题"其实在右栏顶部，
       实测区间变成 y0=514 → y1=34 —— 直接倒挂，裁出来的东西和题目毫无关系。
    2) **大题题头（一、二、三…）是硬墙。** 图形不能跨过它；
       落在"题头与它第一道小题之间"的共享图（阅读材料、总平面图）
       挂到该大题的第一题上 —— 也就是用户要的"按标号来、一个大题的图截在一起"。

    每条 span 因此带上 col 与该栏的 x 边界 x0/x1：裁图必须被限制在这一段里，
    否则就是整页宽的一条，隔壁栏的图必然被捞进来。
    """
    idx: dict[str, int] = {}
    # ⚠️ 不能用"整行相等"去找题目对应的源行：extract() 会把题号从题干里剥掉
    #    （源行 "1. 看图列式…" → source_lines 只剩 "看图列式…"），
    #    直接比对永远找不到，区间为空 → 一道图都裁不出来（实测命中）。
    NUM_RE = re.compile(r"^\s*(?:\d{1,3}\s*[、．.]|[（(]\d{1,3}[）)][、.]?|[①-⑳])\s*")

    def norm(s: str) -> str:
        return NUM_RE.sub("", str(s or "").strip()).strip()

    for n, a in enumerate(ann):
        idx.setdefault(norm(a["text"]), n)

    def locate(q: dict[str, Any], start: int) -> int:
        for s in q.get("source_lines") or []:
            t = norm(s)
            if not t:
                continue
            if t in idx and idx[t] >= start:
                return idx[t]
            for n in range(start, len(ann)):       # 被拆行/合并过的，退化成前缀匹配
                if len(t) >= 4 and norm(ann[n]["text"]).startswith(t[:10]):
                    return n
        return -1

    BARE = re.compile(r"^(\d{1,2})\s*[.、．]?$")

    def anchor_row(q: dict[str, Any], n: int) -> int:
        """题目在源页上的【起点行】。

        "题号印在图顶上、题干印在图底下"的卷（教辅书常见）：locate 只能找到题干那行
        （y=570），而题号"3"单独成行在 y=450，中间隔着整张图。用题干行当区间起点，
        整张图就落在【上一题】的区间里 → 这道题没图，上一题还多出一张不相干的图。
        所以：起点行的上一行如果正好是【这个数字】、同页同栏、且在它上面 → 用它当起点。
        ⚠️ 必须"数字 == 本题题号"才抬，不然只是把区间往上扩着玩。
        """
        if n <= 0 or q.get("q_no") is None:
            return n
        p = ann[n - 1]
        if int(p.get("page") or 0) != int(ann[n].get("page") or 0) \
                or int(p.get("col", 0)) != int(ann[n].get("col", 0)):
            return n
        m = BARE.match(str(p.get("text") or "").strip())
        if not m or float(p["y"]) >= float(ann[n]["y"]):
            return n
        return n - 1 if int(m.group(1)) == int(q["q_no"]) else n

    def locate_text(needle: str, start: int = 0) -> int:
        t = norm(needle)
        if not t:
            return -1
        for n in range(start, len(ann)):
            s = norm(ann[n]["text"])
            if s == t or (len(t) >= 4 and s.startswith(t[:10])):
                return n
        return -1

    # 页面几何：优先用调用方给的 pages，退化成从 ann 里估
    geo: dict[int, dict[str, Any]] = {}
    for p in pages or []:
        try:
            pg = int(p["page"])
        except (KeyError, TypeError, ValueError):
            continue
        bands = p.get("bands") or []
        geo[pg] = {"w": float(p.get("width_pt") or 0), "h": float(p.get("height_pt") or 0),
                   "bands": bands}
    for a in ann:                                   # 没给 pages 时也要能算出边界
        pg = int(a.get("page") or 1)
        g = geo.setdefault(pg, {"w": 0.0, "h": 0.0, "bands": []})
        g["w"] = max(g["w"], float(a["x"]) + float(a["w"]))
        g["h"] = max(g["h"], float(a["y"]) + float(a["h"]))

    def col_bounds(pg: int, x_mid: float) -> tuple[float, float]:
        g = geo.get(pg) or {}
        for b in (g.get("bands") or []):
            if float(b["x0"]) <= x_mid < float(b["x1"]):
                return float(b["x0"]), float(b["x1"])
        return 0.0, float((g.get("w") or 0) or (x_mid + 1))

    # 锚点：题目 + 大题题头。同一 (page, col) 内按 y 排序，题与题之间就是"能裁的带"。
    anchors: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    cursor = 0
    for qi, q in enumerate(questions):
        n = locate(q, cursor)
        if n < 0:
            placed.append({})
            continue
        n = anchor_row(q, n)
        cursor = n + 1
        a = ann[n]
        rec = {"qi": qi, "n": n, "page": int(a["page"]), "col": int(a.get("col", 0)),
               "y": float(a["y"]), "kind": "q"}
        placed.append(rec)
        anchors.append(rec)
    for sec in sections or []:
        name = sec.get("name") or ""
        if not SECTION_RE.match(name.strip()):
            continue                                 # 卷名/关卡名不当墙，只有一、二、三这种才算
        n = locate_text(name)
        if n < 0:
            continue
        a = ann[n]
        anchors.append({"qi": None, "n": n, "page": int(a["page"]), "col": int(a.get("col", 0)),
                        "y": float(a["y"]), "kind": "sec"})
    anchors.sort(key=lambda r: (r["page"], r["col"], r["y"]))

    spans: list[dict[str, Any]] = []
    for rec in placed:
        if not rec:
            continue
        page, col, y0 = rec["page"], rec["col"], rec["y"]
        g = geo.get(page) or {"w": 0.0, "h": 0.0}
        # ── 向上够到本大题的题头 ──────────────────────────────
        # 大题题头与它第一道小题之间常放着共享的东西（阅读材料、总平面图、
        # "根据下面的路线图"那张图）。这段区间不属于任何小题，
        # 谁都不接就等于把图丢了 —— 所以把它划给本大题的第一道小题，
        # 也就是用户要的"先认大题号，一个大题的图截在一起"。
        # 条件很紧：中间不能夹着别的小题，否则就不是"本大题的第一题"。
        up = None
        for o in anchors:
            if o["kind"] != "sec" or o["page"] != page or o["col"] != col:
                continue
            if o["y"] >= y0 - 1:
                continue
            between = [q for q in anchors
                       if q["kind"] == "q" and q["page"] == page and q["col"] == col
                       and o["y"] < q["y"] < y0]
            if not between and (up is None or o["y"] > up["y"]):
                up = o
        if up:
            y0 = up["y"]
        # 同栏内、严格在它下面的最近锚点（下一题或下一个大题题头）= 区间下界
        y1 = float(g["h"] or 1e9)
        for o in anchors:
            if o is rec or o["page"] != page or o["col"] != col:
                continue
            if o["y"] > y0 + 1 and o["y"] < y1:
                y1 = o["y"]
        if col < 0:                                   # 通栏行（页眉/大标题）：整幅宽
            x0, x1 = 0.0, float(g["w"] or y1)
        else:
            a = ann[rec["n"]]
            x0, x1 = col_bounds(page, float(a["x"]) + float(a["w"]) / 2)
        boxes = [b for b in ann
                 if int(b["page"]) == page and int(b.get("col", 0)) == col
                 and y0 <= float(b["y"]) < y1]
        spans.append({"q_index": rec["qi"], "page": page, "col": col,
                      "y0": y0, "y1": y1, "x0": x0, "x1": x1,
                      "section": (questions[rec["qi"]].get("section") or ""),
                      # text 一起带上：审计/诊断报"哪一行被图盖住了"时必须能说出内容，
                      # 只报坐标的话，人还得回去翻页面，等于尺不准。
                      "text_boxes": [{"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"],
                                      "text": b.get("text", "")}
                                     for b in boxes]})
    return spans


def lines_from_image(path: str, dpi_probe: int = 100) -> dict[str, Any]:
    """单张作业照片 → 文本行（带 pt 坐标，和 figures 的虚拟页面口径一致）。"""
    ok, why = O.available()
    if not ok:
        return {"lines": [], "ann": [], "pages": [], "ocr_conf": 0,
                "needs_review": True, "error": why}
    items = O.ocr_image(path)
    sc = 72.0 / dpi_probe                      # 照片按"1px = 1px@dpi_probe"当页面，换成 pt
    items = [{**it, "x": it["x"] * sc, "y": it["y"] * sc,
              "w": it["w"] * sc, "h": it["h"] * sc} for it in items]
    w = max((it["x"] + it["w"] for it in items), default=1) + 1
    ann, bands = _ordered_items(items, w)
    for a in ann:
        a["page"] = 1
    return {"lines": [a["text"] for a in ann], "ann": ann,
            "pages": [{"page": 1, "route": "ocr", "lines": len(ann),
                       "width_pt": w, "height_pt": max((a["y"] + a["h"] for a in ann), default=1),
                       "columns": len(bands), "bands": bands}],
            "ocr_conf": round(sum(i["conf"] for i in items) / len(items), 3) if items else 0,
            "needs_review": False, "errors": []}


def lines_from_task(task) -> dict[str, Any]:
    """一个任务（可能多个文件）合并成一份可作答文本。页序 = 上传顺序。

    页面号是【全局】的：ann 里的 page 会被改写成跨文件唯一编号，
    figures 用同一套编号找 PageSource，否则第二个文件的第 1 页会和第一个文件的第 1 页撞车。
    """
    lines: list[str] = []
    ann: list[dict[str, Any]] = []
    per: list[dict[str, Any]] = []
    pages_out: list[dict[str, Any]] = []      # 全局页号 → 该页几何与【栏带】，裁图要靠它
    noise_out: list[dict[str, Any]] = []      # 装订栏/侧边栏被丢掉的框，裁图要避开
    sources: dict[int, int] = {}               # 全局页号 → sources 列表下标
    confs: list[float] = []
    err: list[str] = []
    page_base = 0
    for f in [x for x in task.files if x.get("ok")]:
        ext = os.path.splitext(f["path"])[1].lower()
        if ext == ".pdf":
            r = annotated_lines_from_pdf(
                f["path"], work_dir=os.path.join(task.work, "ocr"),
                progress=lambda a, b, n=None: task.log(f"OCR {n} {a}/{b} 页"))
        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            r = lines_from_image(f["path"])
        else:
            r = _from_parsed_docx(f)
        for a in r.get("ann", []):
            a = {**a, "page": page_base + int(a["page"])}
            ann.append(a)
            lines.append(a["text"])
        for p in r.get("pages", []):
            gp = page_base + int(p["page"])
            sources[gp] = len(per)
            pages_out.append({**p, "page": gp})
        # 装订栏/侧边栏被丢掉的框：裁图阶段要用它挡"把装订栏当配图裁下来"
        for m in r.get("noise", []):
            noise_out.append({**m, "page": page_base + int(m.get("page", 1))})
        per.append({"file": f["name"], "path": f["path"], "kind": ext,
                    "first_page": page_base + 1, "pages": r.get("pages", []),
                    "lines": len(r.get("ann", []))})
        confs.append(r.get("ocr_conf") or 0)
        err += [f"{f['name']}：{e}" for e in (r.get("errors") or [])]
        if r.get("error"):
            err.append(f"{f['name']}：{r['error']}")
        page_base += max(1, len(r.get("pages", []) or [1]))
    # ⚠️ pages 必须带出去：papers.py 的裁图要用每页的 bands（栏带）来限制裁剪范围。
    #    以前这里只回 files/page_sources，pages 被丢掉了，于是
    #    spans_for_questions 拿不到栏带、col_bounds 退回整页宽 ——
    #    离线单测（直接调 annotated_lines_from_pdf）看着是对的，
    #    走 API 却仍然跨栏：真实卷上 51 张碎片把 2 页卷撑成 11 页。
    return {"lines": lines, "ann": ann, "files": per, "pages": pages_out,
            "noise": noise_out, "page_sources": sources,
            "ocr_conf": round(max(confs), 3) if confs else 0, "errors": err}


def open_page_source(kind: str, path: str, global_page: int,
                     page_sources: dict[int, int], files: list[dict[str, Any]]):
    """按全局页号拿到可裁剪的页面源。"""
    from .figures import page_source_from_image, page_source_from_pdf
    fi = page_sources.get(int(global_page))
    if fi is None or fi >= len(files):
        return None
    f = files[fi]
    local = int(global_page) - int(f.get("first_page", 1)) + 1
    if kind == ".pdf":
        return page_source_from_pdf(f["path"], local)
    if kind in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        return page_source_from_image(f["path"], local)
    return None


def _from_parsed_docx(f: dict) -> dict[str, Any]:
    """docx：解析阶段已经把段落取成文本块，直接按顺序拼。"""
    parsed = f.get("parsed") or {}
    out: list[str] = []
    for pg in parsed.get("pages", []):
        for b in pg.get("blocks", []):
            if b.get("kind") == "text" and (b.get("text") or "").strip():
                out.append(b["text"].strip())
    return {"lines": out, "pages": [{"page": 1, "route": "docx", "lines": len(out)}],
            "ocr_conf": 1.0, "needs_review": False}
