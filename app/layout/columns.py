"""版面结构化（P3a）：分栏检测 → 栏内合并行 → 阅读顺序。

Python 版，移植自 ../shijuan-maker/src/layout.mjs（该实现已在真实双栏卷上验证：
16 条单测全绿，含 4 条反例）。四条来自真实数据的教训全部保留在注释里。
"""
from __future__ import annotations

from typing import Any, Iterable


def _join_with_gaps(parts: list[dict]) -> str:
    """按水平间距补空格，保住表格列与选项间距。
    直接 "".join 会把「30 厘米  1 米」粘成「30 厘米1米」（实测踩过）。"""
    if not parts:
        return ""
    out = parts[0]["text"]
    unit = max(1.0, min(p.get("h", 10) or 10 for p in parts) * 0.28)
    for prev, cur in zip(parts, parts[1:]):
        gap = cur["x"] - (prev["x"] + prev.get("w", 0))
        if gap > unit:
            out += " " * min(12, max(1, int(round(gap / unit))))
        out += cur["text"]
    return out


def group_lines(items: list[dict], y_tol: float = 10.0) -> list[dict]:
    """把同一水平线上的碎片合成一行，并按 x 排序（间距转成空格）。"""
    ordered = sorted(items, key=lambda i: (i["y"], i["x"]))
    lines: list[dict] = []
    for it in ordered:
        last = lines[-1] if lines else None
        if last and abs(it["y"] - last["y"]) <= max(y_tol, last["h"] * 0.6):
            last["parts"].append(it)
            last["h"] = max(last["h"], it["h"])
            last["x"] = min(last["x"], it["x"])
            last["right"] = max(last["right"], it["x"] + it["w"])
            if it.get("conf") is not None:
                last["confs"].append(it["conf"])
        else:
            lines.append({
                "y": it["y"], "x": it["x"], "right": it["x"] + it["w"], "h": it["h"],
                "parts": [it], "confs": [it["conf"]] if it.get("conf") is not None else [],
            })
    out = []
    for ln in lines:
        ln["parts"].sort(key=lambda p: p["x"])
        text = _join_with_gaps(ln["parts"]).rstrip()
        if not text.strip():
            continue
        conf = round(sum(ln["confs"]) / len(ln["confs"]), 3) if ln["confs"] else None
        out.append({"text": text, "x": ln["x"], "y": ln["y"],
                    "w": ln["right"] - ln["x"], "h": ln["h"], "conf": conf})
    return out


def _bands_from_histogram(items: list[dict], page_w: float, key: str,
                          min_gap_ratio: float, occupancy: float,
                          bucket: float | None, min_band_share: float) -> list[dict]:
    """通用空带检测。key='bbox' 用外接框投影（适合 OCR 碎片），
    key='left' 用左边缘起笔分布（适合 PDF 文本块 —— 它们常横跨栏宽，外接框投影会没有间隙）。"""
    if not items or not page_w:
        return [{"x0": 0.0, "x1": float(page_w or 0)}]

    if key == "left":
        widths = [1.0 for _ in items]
    else:
        widths = sorted(max(i.get("w", 1), 1) for i in items)
    med = sorted(widths)[len(widths) // 2] if widths else 20
    bw = bucket or max(6.0, min(med, page_w / 24))
    n = max(12, int(page_w / bw))
    bin_w = page_w / n

    hist = [0] * n
    for it in items:
        if key == "left":
            a = b = min(n - 1, max(0, int(it["x"] / bin_w)))
        else:
            a = max(0, int(it["x"] / bin_w))
            b = min(n - 1, int((it["x"] + max(it.get("w", 1), 1)) / bin_w))
        for i in range(a, b + 1):
            hist[i] += 1

    thr = max(1.0, len(items) * occupancy)
    gaps: list[dict] = []
    run = None
    for i, c in enumerate(hist):
        empty = c <= thr
        if empty and run is None:
            run = {"from": i, "to": i}
        elif empty:
            run["to"] = i
        elif run is not None:
            gaps.append(run); run = None
    if run is not None:
        gaps.append(run)

    usable = sorted(
        ({"center": (g["from"] + g["to"] + 1) / 2 * bin_w, "width": (g["to"] - g["from"] + 1) * bin_w}
         for g in gaps if (g["to"] - g["from"] + 1) * bin_w >= page_w * min_gap_ratio),
        key=lambda x: -x["width"])
    if not usable:
        return [{"x0": 0.0, "x1": page_w}]

    chosen: list[float] = []
    for g in usable:
        near = max(g["width"], page_w * 0.02)
        if any(abs(c - g["center"]) < near for c in chosen):
            continue
        left_has = any(i["x"] < g["center"] - 1 for i in items)
        right_has = any(i["x"] >= g["center"] for i in items)
        if left_has and right_has:
            chosen.append(g["center"])
    if not chosen:
        return [{"x0": 0.0, "x1": page_w}]
    chosen.sort()
    bounds = [0.0] + chosen + [page_w]
    bands = [{"x0": bounds[i], "x1": bounds[i + 1]} for i in range(len(bounds) - 1)]

    def count_in(b):
        return sum(1 for i in items if b["x0"] <= i["x"] < b["x1"])

    # ⚠️ 只合并【真正为空】的边栏。曾用「占比 < min_band_share 就删」，
    #    在每页只有一行的压力测试样本上删掉了非空栏 → 100 行内容丢了 96 行（验收 F09 抓到）。
    #    稀疏但真实存在的栏（如左侧竖排装订栏）宁可留着，也不能吞内容。
    i = 0
    while i < len(bands) and len(bands) > 1:
        if count_in(bands[i]) == 0:
            if i == 0:
                bands[1]["x0"] = bands[0]["x0"]; bands.pop(0)
            elif i == len(bands) - 1:
                bands[i - 1]["x1"] = bands[i]["x1"]; bands.pop()
            else:
                bands[i + 1]["x0"] = bands[i]["x0"]; bands.pop(i)
            i = -1
        i += 1
    return bands


def detect_columns(items: list[dict], page_w: float, min_gap_ratio: float = 0.03,
                   occupancy: float = 0.12, bucket: float | None = None,
                   min_band_share: float = 0.10) -> list[dict]:
    """在【原始碎片框】上找栏界。

    ⚠️ 教训 1（真实数据打穿的）：绝不能先 group_lines 再检测。双栏卷左右两栏在同一
       水平线上，合并后变成横跨全页的"行"，间隙消失，必然漏检。
    ⚠️ 教训 2：直方图桶宽不能写死（曾用 20px 把三栏的 50px 间隙量化没了）。
    ⚠️ 教训 3：试卷左侧竖排「学校/班级/姓名/学号」只有两三个框，会把整页误判成三栏。
    ⚠️ 教训 4（L2 模拟卷实测）：PDF 文本块的外接框常横跨栏宽，bbox 投影会"没有间隙"，
       于是双栏被读成逐行交替的乱序。故 bbox 找不到栏时，再用【左边缘起笔分布】试一次。
    """
    bands = _bands_from_histogram(items, page_w, "bbox", min_gap_ratio, occupancy,
                                  bucket, min_band_share)
    if len(bands) > 1:
        return bands
    left = _bands_from_histogram(items, page_w, "left", 0.06, 0.10,
                                 bucket or max(6.0, page_w / 60), min_band_share)
    # 左边缘法要求两栏都够肥，否则宁可保持单栏（避免把缩进误判成分栏）
    if len(left) > 1:
        counts = [sum(1 for i in items if b["x0"] <= i["x"] < b["x1"]) for b in left]
        if min(counts) >= max(3, len(items) * 0.15):
            return left
    return bands


def structure_page(items: list[dict], page_w: float, y_tol: float = 10.0) -> dict[str, Any]:
    """原始条目 → 分栏 → 栏内合并行 → 阅读顺序。P3a 主入口，顺序不可调换。"""
    bands = detect_columns(items, page_w)

    def assign(it):
        mid = it["x"] + max(it.get("w", 1), 1) / 2
        for bi, b in enumerate(bands):
            if b["x0"] <= mid < b["x1"]:
                return bi
        return 0 if mid < bands[0]["x1"] else len(bands) - 1

    # 通栏判定（保守）：跨过第一条栏界 + 跨过页面中线 + 自身 ≥40% 页宽。
    # ⚠️ 教训 4：判太松会把普通长行当成通栏抽离正文（真实数据上把「六、大作文」错排到首行）。
    wide: set[int] = set()
    if len(bands) > 1:
        b0 = bands[0]["x1"]
        mid_page = page_w / 2
        for idx, it in enumerate(items):
            if it["x"] < b0 - 4 and it["x"] + it.get("w", 0) > mid_page and it.get("w", 0) >= page_w * 0.4:
                wide.add(idx)

    per_col: list[list[dict]] = [[] for _ in bands]
    for idx, it in enumerate(items):
        if idx in wide:
            continue
        per_col[assign(it)].append(it)

    out: list[dict] = []
    for ci, col in enumerate(per_col):
        for ln in group_lines(sorted(col, key=lambda i: (i["y"], i["x"])), y_tol):
            out.append({**ln, "col": ci})

    if wide:
        arr = [items[i] for i in sorted(wide)]
        body_top = min((i["y"] for k, i in enumerate(items) if k not in wide), default=0)
        hoist = [i for i in arr if i["y"] < body_top]          # 页眉/大标题 → 前置
        inline = [i for i in arr if not i["y"] < body_top]      # 跨栏题头 → 留在所在栏
        for it in inline:
            per_col[assign(it)].append(it)
        if inline:
            out = []
            for ci, col in enumerate(per_col):
                for ln in group_lines(sorted(col, key=lambda i: (i["y"], i["x"])), y_tol):
                    out.append({**ln, "col": ci})
        for ln in group_lines(sorted(hoist, key=lambda i: (i["y"], i["x"])), y_tol):
            out.append({**ln, "col": -1})

    out.sort(key=lambda l: (0 if l["col"] < 0 else 1, l["col"], l["y"]))
    return {"lines": [dict(l, order=i) for i, l in enumerate(out)],
            "columns": len(bands), "bands": bands}
