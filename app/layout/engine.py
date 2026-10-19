"""A4 重排引擎（PRD §4.4）：把解析结果排成一页页可渲染的版面模型。

产物是纯数据（pages → blocks，坐标以内容区左上为原点，y 向下），
渲染交给 app/papers/pdf_writer.py，这样布局可以脱离 PDF 单测。
"""
from __future__ import annotations

import os
from typing import Any, Callable

from .options import LayoutOptions, A4_W, A4_H
from .columns import structure_page

# 文本测量函数由 papers 层注入（要用已注册的字体），默认给一个 CJK 保守估算
_default_metrics: Callable[[str, float], float] = lambda s, fs: fs * sum(
    1.0 if ord(c) > 0x2E80 else 0.55 for c in s)


def set_metrics(fn: Callable[[str, float], float]) -> None:
    global _default_metrics
    _default_metrics = fn


def measure(text: str, font_size: float) -> float:
    return _default_metrics(text, font_size)


def wrap_text(text: str, font_size: float, max_w: float) -> list[str]:
    """按宽度折行。中文无空格，逐字贪心；英文按词，避免把单词劈开。"""
    lines: list[str] = []
    for para in (text or "").split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        cur_w = 0.0
        # 英文按词切，其余按字切
        tokens: list[str] = []
        buf = ""
        for ch in para:
            if ord(ch) < 0x2E80 and ch not in "　，。、；：？！）】》":
                buf += ch
            else:
                if buf:
                    tokens.append(buf); buf = ""
                tokens.append(ch)
        if buf:
            tokens.append(buf)

        for tok in tokens:
            w = measure(tok, font_size)
            if cur and cur_w + w > max_w:
                lines.append(cur.rstrip())
                cur = tok.lstrip() if tok.isspace() else tok
                cur_w = measure(cur, font_size)
            else:
                cur += tok
                cur_w += w
        if cur.strip():
            lines.append(cur.rstrip())
    return lines


def fit_image(img_w: float, img_h: float, box_w: float, box_h: float) -> tuple[float, float]:
    """等比缩放到框内，只缩不放大超过 1 倍（放大只会糊）。"""
    if img_w <= 0 or img_h <= 0:
        return box_w, box_h * 0.6
    s = min(box_w / img_w, box_h / img_h, 1.0)
    if s <= 0:
        s = min(box_w / img_w, box_h / img_h)
    return img_w * s, img_h * s


def _blocks_to_flow(pages: list[dict], title: str = "") -> list[dict]:
    """把解析结果的 blocks 拉平成"内容流"。文字页走分栏归位，图片页整块保留。"""
    norm_title = "".join((title or "").split())
    flow: list[dict] = []
    for pg in pages:
        if pg.get("is_scan"):
            # 扫描页的位图来源有两种：PDF 渲染出的 rendered_image，或图片文件本身的 ImageBlock
            cand = pg.get("rendered_image")
            if not (cand and os.path.exists(cand)):
                cand = next((b.get("path") for b in pg.get("blocks", [])
                             if b.get("kind") == "image" and b.get("path")
                             and os.path.exists(b["path"])), None)
            if cand:
                flow.append({"kind": "image", "path": cand, "page_no": pg["page_no"]})
            continue

        text_blocks = [b for b in pg.get("blocks", []) if b["kind"] == "text"]
        img_blocks = [b for b in pg.get("blocks", []) if b["kind"] == "image"]

        if text_blocks:
            items = []
            for b in text_blocks:
                bb = b.get("bbox")
                if not bb:
                    continue
                items.append({"text": b["text"], "x": bb[0], "y": bb[1],
                              "w": bb[2] - bb[0], "h": max(bb[3] - bb[1], 1),
                              "bold": bool(b.get("bold")), "size": b.get("font_size_hint")})
            if items:
                page_w = max((i["x"] + i["w"] for i in items), default=0) + 1
                st = structure_page(items, page_w)
                for ln in st["lines"]:
                    # 表头已经印了标题，正文里重复出现的同名行丢掉（真实卷常首行就是卷名）
                    if norm_title and "".join(ln["text"].split()) == norm_title:
                        continue
                    flow.append({"kind": "text", "text": ln["text"], "bold": False,
                                 "size": None, "col": ln["col"], "columns": st["columns"],
                                 "page_no": pg["page_no"]})
            else:
                for b in text_blocks:
                    flow.append({"kind": "text", "text": b["text"], "bold": bool(b.get("bold")),
                                 "size": b.get("font_size_hint"), "page_no": pg["page_no"]})

        for b in img_blocks:
            p = b.get("path")
            if p and os.path.exists(p):
                flow.append({"kind": "image", "path": p, "page_no": pg["page_no"],
                             "w_px": b.get("width_px"), "h_px": b.get("height_px")})
    return flow


def build_layout(parsed_pages: list[dict], opt: LayoutOptions, title: str = "") -> dict[str, Any]:
    """核心：内容流 → A4 分页版面模型。

    返回 {pages:[{no, blocks:[{type,x,y,w,h,...}], header, footer}], stats}
    规则（PRD §4.4）：块级流式；不截断行；图片块整体移动不可拆分。
    """
    opt = opt.clamp()
    # 防呆：曾经把整个 parsed 字典传进来（而非 parsed["pages"]），
    # 结果遍历到的是字符串键，静默排出 11 份只有表头的空页。宁可当场抛错。
    if isinstance(parsed_pages, dict):
        raise TypeError("build_layout 需要页列表 parsed['pages']，不是整个 parsed 字典")
    for i, pg in enumerate(parsed_pages):
        if not isinstance(pg, dict):
            raise TypeError(f"parsed_pages[{i}] 不是 dict，而是 {type(pg).__name__}")
    flow = _blocks_to_flow(parsed_pages, title or opt.title)
    fs = opt.effective_font
    lead = opt.leading
    cw = opt.content_w

    pages: list[dict] = []
    cur: list[dict] = []
    y = 0.0

    def new_page():
        nonlocal cur, y
        if cur:
            pages.append({"no": len(pages) + 1, "blocks": cur})
        cur, y = [], 0.0

    for item in flow:
        if item["kind"] == "image":
            from PIL import Image
            try:
                with Image.open(item["path"]) as im:
                    iw, ih = im.size
            except Exception:
                continue
            # 横图塞进竖 A4 只能占 40% 版面（实测横向语文卷就是这样）。
            # 转 90° 后能占 84%，对「整页是图」的扫描卷明显更划算。
            rot = 0
            fit_w, fit_h = fit_image(iw, ih, cw, opt.content_h)
            rot_w, rot_h = fit_image(ih, iw, cw, opt.content_h)
            if iw > ih and rot_w * rot_h > fit_w * fit_h * 1.15:
                rot, iw, ih, fit_w, fit_h = 90, ih, iw, rot_w, rot_h
            if y + fit_h > opt.content_h and cur:
                new_page()
                fit_w, fit_h = fit_image(iw, ih, cw, opt.content_h)
            cur.append({"type": "image", "path": item["path"], "rot": rot,
                        "x": (cw - fit_w) / 2, "y": y, "w": fit_w, "h": fit_h,
                        "src_page": item.get("page_no")})
            y += fit_h + opt.image_gap
            continue

        text = item["text"]
        size = min(max(item.get("size") or fs, 8.0), 20.0) if item.get("size") else fs
        bold = item.get("bold", False)
        # 多栏时把栏号带下去，渲染阶段可据此分栏（V1：按栏插入分隔，避免跨栏串行阅读）
        lines = wrap_text(text, size, cw)
        block_h = len(lines) * (size * opt.line_spacing)
        if y + block_h > opt.content_h and cur:
            new_page()
            lines = wrap_text(text, size, cw)
            block_h = len(lines) * (size * opt.line_spacing)
        cur.append({"type": "text", "lines": lines, "x": 0, "y": y,
                    "w": cw, "h": block_h, "size": size, "bold": bold,
                    "col": item.get("col", 0), "columns": item.get("columns", 1),
                    "src_page": item.get("page_no")})
        y += block_h + lead * 0.35

    if cur:
        pages.append({"no": len(pages) + 1, "blocks": cur})
    if not pages:
        pages = [{"no": 1, "blocks": []}]

    if opt.two_up:
        pages = _merge_two_up(pages, opt)
    elif opt.is_spread:
        pages = _merge_a3_spread(pages, opt)

    return {
        "pages": pages,
        "header": {"title": opt.title, "show": opt.show_header},
        "footer": {"total": len(pages)},
        "stats": {"source_pages": len(parsed_pages), "flow_items": len(flow),
                  "out_pages": len(pages), "two_up": opt.two_up,
                  "page_format": opt.page_format},
    }


def _merge_a3_spread(pages: list[dict], opt: LayoutOptions) -> list[dict]:
    """A3 横版对开 = 两个 A4 竖版【1:1 左右并排】，标准试卷样式。

    和 2 合 1 的区别：2 合 1 是把两页各缩到 √2 塞进一张 A4（字会变小），
    对开不缩放——A3 的长边正好是两个 A4 宽，所以字号、行距、图都和单页一模一样，
    沿中线对折就是一本 A4 卷子。这也是学校印卷子的做法。
    """
    merged: list[dict] = []
    for i in range(0, len(pages), 2):
        pair = pages[i:i + 2]
        blocks: list[dict] = []
        for slot, pg in enumerate(pair):
            ox = slot * A4_W
            for b in pg["blocks"]:
                nb = dict(b)
                nb["x"] = ox + b["x"]
                nb["half"] = slot
                blocks.append(nb)
        merged.append({"no": len(merged) + 1, "blocks": blocks,
                       "spread": True, "halves": len(pair)})
    return merged


def _merge_two_up(pages: list[dict], opt: LayoutOptions) -> list[dict]:
    """2 合 1：两页内容各占左右半版，缩放 √2（PRD §4.4）。"""
    import math
    k = 1.0 / math.sqrt(2.0)
    half_w = opt.content_w / 2 - 8
    merged: list[dict] = []
    for i in range(0, len(pages), 2):
        pair = pages[i:i + 2]
        blocks: list[dict] = []
        for slot, pg in enumerate(pair):
            ox = slot * (opt.content_w / 2)
            for b in pg["blocks"]:
                nb = dict(b)
                nb["x"] = ox + b["x"] * k
                nb["y"] = b["y"] * k
                nb["w"] = b["w"] * k
                nb["h"] = b["h"] * k
                nb["scale"] = k
                if b["type"] == "text":
                    nb["size"] = b["size"] * k
                    nb["lines"] = wrap_text("\n".join(b["lines"]), nb["size"], nb["w"])
                blocks.append(nb)
        merged.append({"no": len(merged) + 1, "blocks": blocks, "two_up": True})
    return merged
