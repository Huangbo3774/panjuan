"""Word 解析（PRD §4.2）：段落 / 表格 / 内嵌图片 → 统一中间结构。

明确不支持 .doc（PRD §3.3），调用方负责给出「请另存为 .docx」的报错。
"""
from __future__ import annotations

import os
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def parse_docx(path: str, media_dir: str | None = None) -> dict[str, Any]:
    doc = Document(path)
    blocks: list[dict[str, Any]] = []

    # 按文档流顺序遍历段落与表格（python-docx 不保证顺序，需走 body XML）
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
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

    # 内嵌图片：从包里抽出来，落成 ImageBlock
    if media_dir:
        os.makedirs(media_dir, exist_ok=True)
        for i, part in enumerate(doc.part.package.iter_parts()):
            if "image" in (part.content_type or ""):
                fn = os.path.join(media_dir, f"{os.path.basename(path)}_img{i}{os.path.splitext(part.partname)[1]}")
                with open(fn, "wb") as fh:
                    fh.write(part.blob)
                try:
                    from PIL import Image
                    with Image.open(fn) as im:
                        w, h = im.size
                except Exception:
                    w = h = None
                blocks.append({
                    "kind": "image", "path": fn, "width_px": w, "height_px": h,
                    "in_document_flow": False,      # 包内图片拿不到确切位置，标记清楚
                })

    title = ""
    for b in blocks:
        if b["kind"] == "text" and (b.get("bold") or "heading" in (b.get("style") or "").lower() or "title" in (b.get("style") or "").lower()):
            title = b["text"]
            break

    text_chars = sum(len("".join(b["text"].split())) for b in blocks if b["kind"] == "text")
    return {
        "kind": "docx",
        "file": os.path.basename(path),
        "title": title or os.path.splitext(os.path.basename(path))[0],
        "page_count": 1,
        "scan_pages": 0,
        "pages": [{
            "page_no": 1, "is_scan": False, "w_pt": None, "h_pt": None,
            "landscape": False, "text_chars": text_chars, "blocks": blocks,
        }],
    }
