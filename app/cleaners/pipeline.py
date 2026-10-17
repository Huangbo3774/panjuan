"""图像清洗管线（PRD §4.3）：8 步，每步可开关，默认全开。

真实数据依据（docs/P0-真实样本.md §3.2 + 本仓库实测）：
    语文卷 A/B（电子屏摄图）清晰度 7382 / 9660，数学作业（手机拍照）142 —— 相差 52 倍。
    ⇒ 步骤的触发条件按【清晰度】分档，不按像素数。像素数低不代表要清洗。

⚠️ Windows 中文路径下 cv2.imread 返回 None（本仓库真实踩过），一律用 cv_imread。
"""
from __future__ import annotations

import os
from typing import Any

import cv2
import numpy as np

from ..parsers.image import cv_imread          # 统一的中文路径读图


def write_image(path: str, img: np.ndarray) -> None:
    """cv2.imwrite 同样不支持中文路径，走 imencode + 字节写。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError(f"编码失败: {path}")
    buf.tofile(path)


def read_image(path: str) -> np.ndarray:
    img = cv_imread(path)
    if img is None:
        raise ValueError(f"无法读取图片（文件损坏或格式不支持）: {path}")
    return img


# ---------------------------------------------------------------- 各步骤

def step_orient(img, *, exif_orientation: int = 1):
    """1. 方向矫正：EXIF 方向（90° 步进）。"""
    if exif_orientation in (None, 1):
        return img, "EXIF 方向正常"
    table = {
        3: cv2.rotate,   # 180°
        6: lambda i: cv2.rotate(i, cv2.ROTATE_90_COUNTERCLOCKWISE),
        8: lambda i: cv2.rotate(i, cv2.ROTATE_90_CLOCKWISE),
    }
    if exif_orientation == 3:
        return cv2.rotate(img, cv2.ROTATE_180), "EXIF 180°"
    if exif_orientation in (6, 8):
        return table[exif_orientation](img), f"EXIF {exif_orientation}"
    return img, f"EXIF {exif_orientation} 未处理"


def step_grayscale(img):
    """2. 灰度化。"""
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), "BGR→GRAY"


def estimate_skew(gray: np.ndarray) -> float:
    """投影法估倾斜角：把二值图按多个候选角旋转，取行投影方差最大者（行最分明）。"""
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    h, w = binary.shape
    scale = 800 / max(h, w)
    if scale < 1:
        binary = cv2.resize(binary, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    best, best_score = 0.0, -1.0
    for deg in np.arange(-8.0, 8.01, 0.25):
        M = cv2.getRotationMatrix2D((binary.shape[1] / 2, binary.shape[0] / 2), deg, 1.0)
        rot = cv2.warpAffine(binary, M, (binary.shape[1], binary.shape[0]), flags=cv2.INTER_NEAREST)
        score = float(np.var(np.sum(rot, axis=1)))
        if score > best_score:
            best, best_score = float(deg), score
    return round(best, 2)


def step_deskew(img, gray=None, angle: float | None = None):
    """3. 倾斜矫正。angle=None 时自动估计；|angle|<0.3° 视为已正，不动图像。"""
    src = gray if gray is not None else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    a = estimate_skew(src) if angle is None else angle
    if abs(a) < 0.3:
        return img, a, "倾斜可忽略，未旋转"
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    border = (255, 255, 255) if img.ndim == 3 else 255
    out = cv2.warpAffine(img, M, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=border)
    return out, a, f"旋转 {a}°"


def step_denoise(gray):
    """4. 去噪：中值滤波 3×3（对椒盐噪点有效，且不糊化文字边缘）。"""
    return cv2.medianBlur(gray, 3), "中值 3×3"


def step_enhance(gray):
    """5. 对比度增强：CLAHE 自适应直方图均衡。"""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray), "CLAHE"


def step_binarize(gray):
    """6. 二值化（省墨模式）：OTSU 全局阈值。"""
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], "OTSU"


def step_autocrop(img, pad: int = 12):
    """7. 自动裁边：按内容外接框裁掉四周白边，留 pad 像素。"""
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # 去掉零星噪点再找外接框，否则一个脏点就能让裁边失效
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    rows = np.where(ink.sum(axis=1) > 0)[0]
    cols = np.where(ink.sum(axis=0) > 0)[0]
    if len(rows) == 0 or len(cols) == 0:
        return img, "未检出内容，跳过裁边"
    h, w = img.shape[:2]
    y0 = max(0, int(rows[0]) - pad)
    y1 = min(h, int(rows[-1]) + pad)
    x0 = max(0, int(cols[0]) - pad)
    x1 = min(w, int(cols[-1]) + pad)
    return img[y0:y1, x0:x1], f"裁边 → {x1 - x0}x{y1 - y0}"


def step_normalize(img, long_side: int = 3508):
    """8. 尺寸归一：长边对齐 A4@300DPI（3508px），只缩不放超过 2 倍。"""
    h, w = img.shape[:2]
    cur = max(h, w)
    s = long_side / cur
    s = min(max(s, 0.5), 2.0)                # 放大超 2 倍只会糊，不裁到小于一半
    if abs(s - 1) < 0.02:
        return img, "尺寸已合适"
    out = cv2.resize(img, (int(w * s), int(h * s)),
                     interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)
    return out, f"缩放 ×{s:.2f} → {out.shape[1]}x{out.shape[0]}"


# ---------------------------------------------------------------- 编排

DEFAULTS = {
    "orient": True, "grayscale": True, "deskew": True, "denoise": True,
    "enhance": True, "binarize": False, "autocrop": True, "normalize": True,
}

# 清晰度分档阈值（本仓库真实样本标定，2026-10-17）：
#   电子屏摄图 拉普拉斯方差 7382 / 9660      手机拍照 142
#   ⇒ 相差 52 倍，阈值取 1500 居中，两侧行为必须不同。
SHARP_DIGITAL_MIN = 1500.0

# 数字图档：只做几何类操作。中值滤波会抹掉锐利笔画、CLAHE 会把白底拉灰、
# 强行放大是插值假细节 —— 实测这三件事合起来让 OCR 置信度 0.930→0.825、字数 842→836，
# 即"全量清洗"对清晰图是净伤害（tests/cleaners-report.json 留有退化记录）。
DIGITAL_PROFILE = {
    "orient": True, "grayscale": True, "deskew": True, "denoise": False,
    "enhance": False, "binarize": False, "autocrop": True, "normalize": False,
}


def resolve_profile(sharpness_value: float, options: dict | None) -> tuple[dict, str]:
    """未显式指定步骤时按清晰度自动选档。

    ⚠️ 关键：options 里含 binarize=True（省墨模式）时，**不能**整档换成 DEFAULTS，
       否则会顺带打开 normalize（放大 2 倍）—— 实测那样白度纹丝不动、体积反而涨 142KB，
       等于"开关拨了但没生效"（验收 F05 抓到）。正确做法：在自动档基础上只加二值化。
    """
    base, name = ({**DEFAULTS, **DIGITAL_PROFILE}, "digital") if sharpness_value >= SHARP_DIGITAL_MIN \
        else (dict(DEFAULTS), "photo")
    opts = options or {}
    changed = {k: v for k, v in opts.items() if k in DEFAULTS}
    if not changed:
        return base, name
    # 用户只动了个别开关 → 尊重自动档，覆盖他明确指定的那几项
    if set(changed) <= {"binarize"}:
        return {**base, **changed}, f"{name}+ink" if changed.get("binarize") else name
    return {**DEFAULTS, **opts}, "explicit"


def ink_density(img) -> float:
    """墨迹像素 / 总面积。⚠️ 只可用于【同一张图的两块区域】之间比较。
    不能跨清洗步骤比：CLAHE/二值化会改变 OTSU 阈值本身，导致"墨迹量"漂移
    （实测同一张图处理后密度涨到 120~143%，那是阈值变了不是内容多了）。"""
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    return float((t > 0).sum()) / t.size


def crop_safety(img, pad: int = 12) -> dict[str, Any]:
    """直接量「裁边会不会切掉内容」：用全图阈值算裁框，再看框外边缘带还剩多少墨。
    这是同图同阈值下的比较，尺度无关、处理无关，比 ink_retention 可靠。
    """
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    t = cv2.morphologyEx(t, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    rows = np.where(t.sum(axis=1) > 0)[0]
    cols = np.where(t.sum(axis=0) > 0)[0]
    if len(rows) == 0 or len(cols) == 0:
        return {"ok": True, "margin_ink": 0, "note": "无内容"}
    h, w = t.shape
    y0 = max(0, int(rows[0]) - pad); y1 = min(h, int(rows[-1]) + pad)
    x0 = max(0, int(cols[0]) - pad); x1 = min(w, int(cols[-1]) + pad)
    total = int((t > 0).sum())
    band = t.copy()
    band[y0:y1, x0:x1] = 0                      # 只留裁框之外的边缘带
    margin = int((band > 0).sum())
    frac = margin / total if total else 0
    return {"ok": frac <= 0.01, "margin_ink": margin, "total_ink": total,
            "margin_frac": round(frac, 4),
            "box": [x0, y0, x1, y1], "size": [x1 - x0, y1 - y0],
            "note": f"边缘带残留 {frac*100:.2f}% 墨迹（阈值 1%）"}


def clean(path: str, out_path: str | None = None, options: dict | None = None,
          exif_orientation: int = 1) -> dict[str, Any]:
    """跑清洗管线。返回 {out, profile, steps, sharpness_before/after, ink_retention}。

    profile=digital 跳过所有像素级增强（清晰图会被洗坏）；
    profile=photo   跑 PRD §4.3 的完整 8 步。
    binarize 默认关：普通模式保留灰度，PRD §4.4 的"省墨模式"再打开。
    options=None 时按清晰度自动分档；显式传 options 时尊重用户每一项设置。

    ⚠️ 判据教训（2026-10-17 实测）：清洗是为【打印】服务的，不能用 OCR 字数验收。
       实测各档清洗后 OCR 字数都掉 0~5%，但墨迹保留率 99.71% —— 掉的是 OCR 自身的
       版面抖动，不是内容被裁没。用 OCR 当尺会把正常的裁边误判成 bug。
    """
    from ..parsers.image import sharpness      # 局部导入避免循环

    before = sharpness(path)
    opt, profile = resolve_profile(before, options)
    log: list[dict[str, str]] = [{"step": "分档", "note": f"{profile}（清晰度 {before:.0f}）"}]

    img = read_image(path)
    ink0 = ink_density(img)

    if opt["orient"]:
        img, note = step_orient(img, exif_orientation=exif_orientation); log.append({"step": "方向", "note": note})
    if opt["grayscale"]:
        img, note = step_grayscale(img); log.append({"step": "灰度", "note": note})

    if opt["deskew"]:
        g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img, angle, note = step_deskew(img, gray=g); log.append({"step": "倾斜", "note": f"{note}（估角 {angle}°）"})

    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if opt["denoise"]:
        img, note = step_denoise(img); log.append({"step": "去噪", "note": note})
    if opt["enhance"]:
        img, note = step_enhance(img); log.append({"step": "增强", "note": note})
    if opt["binarize"]:
        img, note = step_binarize(img); log.append({"step": "二值化", "note": note})
    if opt["autocrop"]:
        img, note = step_autocrop(img); log.append({"step": "裁边", "note": note})
    if opt["normalize"]:
        img, note = step_normalize(img); log.append({"step": "归一", "note": note})

    out = out_path or (os.path.splitext(path)[0] + "_clean.png")
    write_image(out, img)
    ink1 = ink_density(img)
    retention = round(ink1 / ink0, 4) if ink0 else 1.0
    return {"out": out, "profile": profile, "steps": log,
            "sharpness_before": before, "sharpness_after": sharpness(out),
            "ink_density_before": round(ink0, 5), "ink_density_after": round(ink1, 5),
            "ink_retention": retention}
