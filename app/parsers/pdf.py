"""PDF 解析（PRD §4.2）：文字/扫描判定 + 文本块 + 内嵌图片。

判定口径来自真实材料实测（docs/P0-真实样本.md §1）：
    9 份材料 6 份 PDF，其中 5 份是完全无文本层的扫描件（文本字符数恰好为 0），
    唯一带文本层的那份每页约 206 字。
    ⇒ PRD 原稿的「每页 < 50 字判扫描」在本数据集上与 < 5 字结论相同，
      但 50 这个数离真实分布太远（真实值是 0 和 206），一旦遇到
      「只有页眉页脚的扫描卷」就会误判成文字页。故阈值收紧为 20，并叠加字体证据。
"""
from __future__ import annotations

import os
from typing import Any

import pymupdf  # PyMuPDF ≥1.24 推荐名；旧名 fitz 仍可用但已弃用

# 每页文本字符数低于此值 ⇒ 判为扫描页
SCAN_TEXT_THRESHOLD = 20


def parse_pdf(path: str, render_dir: str | None = None, dpi: int = 300) -> dict[str, Any]:
    """把 PDF 解析成 PRD §4.2 的中间结构。

    返回 {title, page_count, scan_pages, pages:[{page_no, is_scan, w_pt, h_pt,
          landscape, text_chars, blocks:[TextBlock|ImageBlock], rendered_image?}]}
    """
    doc = pymupdf.open(path)
    try:
        pages: list[dict[str, Any]] = []
        scan_pages = 0
        for i, page in enumerate(doc):
            # 只数真正的文字项，排除图片占位
            raw = page.get_text("text") or ""
            chars = len("".join(raw.split()))
            fonts = page.get_fonts(full=False)
            # 字体证据：有 Type0/TrueType 且带 ToUnicode 的嵌入字体，才可能是真文字页
            has_font_evidence = any(f[3] not in ("n/a", "") for f in fonts) if fonts else False
            is_scan = chars < SCAN_TEXT_THRESHOLD and not has_font_evidence

            blocks: list[dict[str, Any]] = []
            # ⚠️ 不能用 get_text("blocks")：它按版面块切，会把表格的【列】切成独立块
            #    （实测 L2 模拟卷：块4 = 左列 4 行，块5 = 右列 4 行），
            #    于是"30 厘米 1 米"这种同列内容被念到一起，横向阅读顺序整个丢掉。
            #    get_text("dict") 给的是真实行，同一行内的多列在同一 line 序列里。
            d = page.get_text("dict")
            lines: list[dict[str, Any]] = []
            for blk in d.get("blocks", []):
                if blk.get("type") != 0:
                    continue
                for ln in blk.get("lines", []):
                    spans = ln.get("spans") or []
                    text = "".join(s.get("text", "") for s in spans)
                    if not text.strip():
                        continue
                    bb = ln.get("bbox") or [0, 0, 0, 0]
                    sizes = [s.get("size") for s in spans if s.get("size")]
                    bold = any((s.get("font") or "").lower().find("bold") >= 0
                               or (s.get("flags", 0) & 16) for s in spans)
                    lines.append({
                        "kind": "text", "text": text.strip(),
                        "bbox": [round(bb[0], 1), round(bb[1], 1), round(bb[2], 1), round(bb[3], 1)],
                        "font_size_hint": round(max(sizes), 1) if sizes else None,
                        "bold": bool(bold),
                    })
            blocks.extend(lines)

            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                blocks.append({
                    "kind": "image",
                    "path": None,                       # 需要时再落盘，避免解析阶段写一堆文件
                    "xref": xref,
                    "ext": info.get("ext"),
                    "width_px": info.get("width"),
                    "height_px": info.get("height"),
                })

            rect = page.rect
            w_pt, h_pt = float(rect.width), float(rect.height)
            entry: dict[str, Any] = {
                "page_no": i + 1,
                "is_scan": is_scan,
                # PDF 里的一页已经是扫描/排版后的成品，不是手机拍的照片。
                # 再做去噪/CLAHE/放大只会把低清字糊掉（实测 P2 60 行 → 27 行），
                # 所以默认跳过清洗；省墨模式仍会单独二值化（见 api/pipeline.py）。
                "no_clean": True,
                "w_pt": round(w_pt, 1),
                "h_pt": round(h_pt, 1),
                "landscape": w_pt > h_pt,
                "text_chars": chars,
                "font_evidence": has_font_evidence,
                "blocks": blocks,
            }
            # 扫描页渲染成 300dpi 位图，交给清洗管线（PRD §4.3）
            if is_scan and render_dir:
                os.makedirs(render_dir, exist_ok=True)
                pix = page.get_pixmap(dpi=dpi)
                out = os.path.join(render_dir, f"{os.path.basename(path)}_p{i+1}.png")
                pix.save(out)
                entry["rendered_image"] = out
                entry["rendered_px"] = [pix.width, pix.height]
            if is_scan:
                scan_pages += 1
            pages.append(entry)

        meta_title = (doc.metadata or {}).get("title") or ""
        return {
            "kind": "pdf",
            "file": os.path.basename(path),
            "title": meta_title.strip() or os.path.splitext(os.path.basename(path))[0],
            "page_count": len(pages),
            "scan_pages": scan_pages,
            "pages": pages,
        }
    finally:
        doc.close()
