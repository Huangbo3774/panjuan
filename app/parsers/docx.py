"""Word 解析（PRD §4.2）：段落 / 表格 / 内嵌图片 → 统一中间结构。

明确不支持 .doc（PRD §3.3），调用方负责给出「请另存为 .docx」的报错。
"""
from __future__ import annotations

import os
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def _image_rids(el) -> list[str]:
    """段落/表格里按出现顺序收集图片关系 id（DrawingML 的 blip、VML 的 imagedata）。"""
    out: list[str] = []
    for node in el.iter():
        tag = node.tag.split("}")[-1]
        if tag == "blip":
            rid = node.get(qn("r:embed")) or node.get(qn("r:link"))
        elif tag == "imagedata":
            rid = node.get(qn("r:id"))
        else:
            continue
        if rid and rid not in out:
            out.append(rid)
    return out


def _save_image_part(part, media_dir: str, base: str, idx: int) -> dict[str, Any]:
    ext = os.path.splitext(str(part.partname))[1].lower() or ".png"
    fn = os.path.join(media_dir, f"{base}_img{idx}{ext}")
    with open(fn, "wb") as fh:
        fh.write(part.blob)
    try:
        from PIL import Image
        with Image.open(fn) as im:
            w, h = im.size
    except Exception:
        w = h = None
    return {"kind": "image", "path": fn, "width_px": w, "height_px": h}


def _page_like(w, h) -> bool:
    """像一整页的图（扫描页），不是 logo/小图标。"""
    if not w or not h:
        return False
    short, long = sorted((int(w), int(h)))
    return short >= 280 and long >= 380


def parse_docx(path: str, media_dir: str | None = None) -> dict[str, Any]:
    doc = Document(path)
    blocks: list[dict[str, Any]] = []
    image_rids: list[str] = []

    # 按文档流顺序遍历段落与表格（python-docx 不保证顺序，需走 body XML）
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag in ("p", "tbl"):
            for rid in _image_rids(child):
                if rid not in image_rids:
                    image_rids.append(rid)
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style else ""
            bold = any(r.bold for r in p.runs if r.bold is not None) if p.runs else False
            size = None
            for r in p.runs:
                if r.font and r.font.size:
                    size = r.font.size.pt
                    break
            blocks.append({
                "kind": "text",
                "text": text,
                "font_size_hint": size,
                "bold": bold or "heading" in style or "title" in style,
                "style": p.style.name if p.style else None,
            })
        elif tag == "tbl":
            t = Table(child, doc)
            rows = []
            for row in t.rows:
                rows.append("\t".join(c.text.strip() for c in row.cells))
            blocks.append({
                "kind": "text",
                "text": "\n".join(rows),
                "is_table": True,
                "rows": len(t.rows),
                "cols": len(t.columns),
                "font_size_hint": None,
                "bold": False,
            })

    # 内嵌图片：按【文档流顺序】抽出来。扫描页贴进 Word 的卷子（新下载的 P1/P2/P3
    # 都是这样）几乎没有任何文字，只能把每张整页图当成扫描页去 OCR —— 旧版把图片
    # 只当配图挂在 page_count=1 的文字页上，识别结果是 0 行、0 题。
    images: list[dict[str, Any]] = []
    if media_dir:
        os.makedirs(media_dir, exist_ok=True)
        base = os.path.basename(path)
        seen: set[str] = set()
        for rid in image_rids:
            part = doc.part.related_parts.get(rid)
            if part is None or "image" not in (part.content_type or ""):
                continue
            seen.add(str(part.partname))
            images.append({**_save_image_part(part, media_dir, base, len(images) + 1),
                           "in_document_flow": True})
        if not images:
            # 关系表里拿不到时退回包内顺序（页眉 logo 之类也会混进来；
            # 下面只把"像一整页"的图当扫描页）。
            for part in doc.part.package.iter_parts():
                if "image" not in (part.content_type or ""):
                    continue
                if str(part.partname) in seen:
                    continue
                images.append({**_save_image_part(part, media_dir, base, len(images) + 1),
                               "in_document_flow": False})

    title = ""
    for b in blocks:
        if b["kind"] == "text" and (b.get("bold") or "heading" in (b.get("style") or "").lower() or "title" in (b.get("style") or "").lower()):
            title = b["text"]
            break

    text_chars = sum(len("".join(b["text"].split())) for b in blocks if b["kind"] == "text")
    scan_imgs = [b for b in images
                 if _page_like(b.get("width_px"), b.get("height_px"))]
    # 只有"几乎没有文字 + 有整页图"才当扫描页；带文字的 Word 仍按文字排，
    # 免得把带插图的通知/试卷错当扫描件。
    scan_only = text_chars < 40 and bool(scan_imgs)
    if scan_only:
        pages: list[dict[str, Any]] = []
        for i, b in enumerate(scan_imgs, 1):
            w, h = b.get("width_px"), b.get("height_px")
            pages.append({
                "page_no": i, "is_scan": True,
                # Word 里贴的是扫描页本身，不是手机照片；清洗会把低清字糊掉
                # （实测 P2 60 行 → 27 行、28 题 → 9 题），默认跳过。
                "no_clean": True,
                "w_pt": (float(w) * 72.0 / 100.0) if w else None,
                "h_pt": (float(h) * 72.0 / 100.0) if h else None,
                "landscape": bool(w and h and w > h),
                "text_chars": 0, "blocks": [b],
                "rendered_image": b["path"],
            })
        page_count, scan_pages = len(pages), len(pages)
    else:
        blocks.extend(images)
        pages = [{
            "page_no": 1, "is_scan": False, "w_pt": None, "h_pt": None,
            "landscape": False, "text_chars": text_chars, "blocks": blocks,
        }]
        page_count, scan_pages = 1, 0

    return {
        "kind": "docx",
        "file": os.path.basename(path),
        "title": title or os.path.splitext(os.path.basename(path))[0],
        "page_count": page_count,
        "scan_pages": scan_pages,
        "pages": pages,
    }
