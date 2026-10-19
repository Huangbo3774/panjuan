"""OCR 接入（V1.1）：RapidOCR（ONNX，Apache-2.0）→ 带坐标的文本条目。

为什么用 RapidOCR 而不是 PRD 原稿的 PaddleOCR：
  · 本机已装好并实测可用；PaddleOCR 首次运行要联网下模型，与 PRD §6「无任何外部网络请求」冲突。
  · 真实扫描卷实测：RapidOCR 置信度 0.93–0.98，正卷字符准确率 97.6%（docs/P0-真实样本.md）。
为什么 OCR 不是"可选"：真实材料 6 份 PDF 里 5 份没有文本层，按 PRD 原稿把 OCR 列为可选，
  在线作答能力覆盖不到六分之一。

⚠️ 关键：OCR 返回的行序是引擎自己的阅读序，双栏卷会跨栏穿插。
   拿到的条目必须先过 layout.columns.structure_page 归位，再交给 extractor。
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Any

_engine = None
_lock = threading.Lock()
MISSING = "RapidOCR 未安装：pip install rapidocr-onnxruntime（需 Python 3.11+）"


def available() -> tuple[bool, str]:
    try:
        import rapidocr_onnxruntime                      # noqa: F401
        return True, "rapidocr-onnxruntime"
    except Exception as e:                                # noqa: BLE001
        return False, MISSING + f"（{e.__class__.__name__}）"


def _get_engine():
    """懒加载 + 单例：模型首次加载要几秒，别每张图都初始化一遍。"""
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
    return _engine


def ocr_image(path: str) -> list[dict[str, Any]]:
    """单张图 → [{text,x,y,w,h,conf}]，坐标是像素、左上原点。"""
    eng = _get_engine()
    res, _ = eng(path)
    out: list[dict[str, Any]] = []
    for item in (res or []):
        box, text, conf = item[0], item[1], float(item[2])
        if not str(text).strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append({
            "text": str(text).strip(),
            "x": round(min(xs), 1), "y": round(min(ys), 1),
            "w": round(max(xs) - min(xs), 1), "h": max(round(max(ys) - min(ys), 1), 1),
            "conf": round(conf, 3),
        })
    return out


def ocr_pdf(path: str, work_dir: str | None = None, dpi: int = 300,
            progress=None) -> dict[str, Any]:
    """扫描版 PDF → 逐页 OCR。返回 {pages:[{page_no,items,width,height}], error?}"""
    import pymupdf

    ok, why = available()
    if not ok:
        return {"error": why, "pages": []}

    doc = pymupdf.open(path)
    pages = []
    try:
        tmp = work_dir or os.path.join(os.path.dirname(os.path.abspath(path)), "_ocr")
        os.makedirs(tmp, exist_ok=True)
        for i, page in enumerate(doc):
            if progress:
                progress(i + 1, doc.page_count)
            pix = page.get_pixmap(dpi=dpi)
            # 同 lines.py：唯一名 + 用 Python 覆盖写。固定名撞上"上一次还留着的文件"时，
            # MuPDF 的 save 会先删再写，Windows 删不掉被占用的文件 → 整份卷报错。
            fp = os.path.join(tmp, f"ocr_p{i + 1}_{os.getpid()}_{uuid.uuid4().hex[:8]}.png")
            with open(fp, "wb") as fh:
                fh.write(pix.tobytes("png"))
            items = ocr_image(fp)
            pages.append({
                "page_no": i + 1,
                "width": pix.width, "height": pix.height,
                "items": items,
                "chars": sum(len("".join(x["text"].split())) for x in items),
            })
            try:
                os.remove(fp)
            except OSError:
                pass
    finally:
        doc.close()
    return {"pages": pages, "engine": "rapidocr-onnxruntime", "dpi": dpi}


def ordered_lines(items: list[dict], page_w: float) -> list[str]:
    """OCR 条目 → 按阅读顺序的文本行（先分栏归位，再栏内合并行）。"""
    from ..layout.columns import structure_page
    st = structure_page(items, page_w, y_tol=max(8, min(20, page_w / 60)))
    return [l["text"] for l in st["lines"]]
