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
import shutil
import tempfile
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


def _recognize_digit(eng, img) -> tuple[str, float]:
    """只识别、不检测：白字抠出来后是孤立的一个数字，检测网络找不到它。"""
    res, _ = eng(img, use_det=False, use_cls=False, use_rec=True)
    if not res:
        return "", 0.0
    row = res[0]
    if isinstance(row, (list, tuple)) and row:
        return str(row[0]), float(row[1]) if len(row) > 1 else 0.0
    return "", 0.0


def _add_badges(eng, path: str, out: list[dict[str, Any]]) -> None:
    """彩色题号徽标补检。失败绝不能让整页 OCR 挂掉。"""
    try:
        import cv2
        import numpy as np

        from .badges import find_badges
        # cv2.imread 在 Windows 上读不了中文路径；np.fromfile + imdecode 可以
        bgr = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return
        out.extend(find_badges(
            bgr, out, recognize=lambda im: _recognize_digit(eng, im)))
    except Exception:
        return


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
    # 教辅活页的 1/2/4 这类白字彩色题号检测不到 → 整页并成一道无号题
    _add_badges(eng, path, out)
    return out


def ocr_image_auto(path: str, min_long_side: int = 1600,
                   factor: float = 2.0) -> list[dict[str, Any]]:
    """单张扫描页 → 文本条目；短边太小时先放大 2 倍再 OCR。

    为什么需要：DOCX/图片路线按原始像素进 OCR，真实材料只有 455–611px 宽
    （相当于 60–80dpi 的 A4 扫描），RapidOCR 会漏掉页边独立题号、把密集行
    粘成一行。实测 P2 第 1 页放大后补回了左边距的"7."（1 倍时整块没检出），
    P3 判断第 3 题补回了中间被吞掉的一截题干。
    PDF 路线在 300dpi 渲染，长边远超阈值，这里不会二次放大。
    返回坐标统一换算回【原图像素】，调用方不需要知道放大倍数。
    """
    up_path = None
    tmp_dir = None
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            if max(w, h) < min_long_side and factor > 1.0:
                tmp_dir = tempfile.mkdtemp(prefix="pf_ocr_")
                up_path = os.path.join(tmp_dir, "page.png")
                im.convert("RGB").resize(
                    (max(1, round(w * factor)), max(1, round(h * factor))),
                    Image.LANCZOS).save(up_path)
    except Exception:
        up_path = None
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir = None
    try:
        if up_path:
            out = ocr_image(up_path)
            for it in out:
                for k in ("x", "y", "w", "h"):
                    it[k] = round(float(it[k]) / factor, 1)
            return out
        return ocr_image(path)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


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
