"""图片解析（PRD §4.2）：读取 + EXIF 方向 + 尺寸事实。

⚠️ 真实数据教训（docs/P0-真实样本.md §3.2）：**分辨率不是清晰度的可靠代理**。
   两张 1260×907 的语文卷（相对 A4@300DPI 只有 13%）是电子屏摄图，OCR 置信度 0.93；
   而按像素数判会得出"偏低，必须预处理"的错结论。
   ⇒ 这里只报客观事实（像素、EXIF 方向），**清晰度判定交给 cleaners 的拉普拉斯方差**。
"""
from __future__ import annotations

import os
from typing import Any

from PIL import Image, ImageOps, ImageStat

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# A4@300DPI 的像素数，仅作参照量，不作为判定阈值
A4_300DPI_PX = 2480 * 3508


def cv_imread(path: str):
    """Windows 中文路径下 cv2.imread 会直接返回 None（实测：本仓库三个中文文件名全失败）。
    统一走 numpy 读字节 + imdecode，所有需要 OpenCV 读图的地方都必须用这个，不要再用 imread。
    """
    import cv2
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def sharpness(path: str) -> float:
    """拉普拉斯方差：值越大越锐。经验分界 <100 模糊，>200 清晰（本仓库会重新标定）。
    返回 -1 表示【测量失败】，不是"很模糊"——调用方必须区分这两者。
    """
    import cv2

    img = cv_imread(path)
    if img is None:
        return -1.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if max(h, w) > 2000:                      # 统一缩到 2000 长边再比，否则不同尺寸不可比
        s = 2000 / max(h, w)
        gray = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def parse_image(path: str) -> dict[str, Any]:
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        raise ValueError(f"不支持的图片格式：{ext}（支持 {', '.join(sorted(SUPPORTED))}）")

    with Image.open(path) as im:
        w, h = im.size
        exif = im.getexif()
        orientation = exif.get(274, 1)
        mode = im.mode
        # 灰度均值：判断是不是白底文档图（文档图通常 >200）
        gray = ImageOps.exif_transpose(im).convert("L")
        mean = float(ImageStat.Stat(gray).mean[0])

    return {
        "kind": "image",
        "file": os.path.basename(path),
        "title": os.path.splitext(os.path.basename(path))[0],
        "page_count": 1,
        "scan_pages": 1,
        "pages": [{
            "page_no": 1,
            "is_scan": True,                    # 图片一律进清洗管线
            "w_pt": None,
            "h_pt": None,
            "landscape": w > h,
            "text_chars": 0,
            "blocks": [{
                "kind": "image",
                "path": path,
                "width_px": w,
                "height_px": h,
                "megapixels": round(w * h / 1e6, 2),
                "a4_300dpi_ratio": round(w * h / A4_300DPI_PX, 2),
                "mode": mode,
                "exif_orientation": orientation,
                "mean_luma": round(mean, 1),
                "sharpness_lapVar": round(sharpness(path), 1),
            }],
        }],
    }
