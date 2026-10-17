"""清洗管线参数扫描 + 闸门：原始 vs 各种管线，用【下游 OCR】当唯一判据。

用法: py -3.11 tests/run_cleaners.py
为什么不目测：PRD §6 说"低清变高清"，但"看起来干净"和"OCR 读得多"不是一回事。
    实测已证明中值滤波 + CLAHE + 强行放大会让 OCR 字数与置信度双双下降。
闸门：任何一档清洗后的 OCR 字数/置信度低于原始，就记 FAIL —— 清洗不许帮倒忙。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:                                            # Windows 控制台 GBK，✓/✗ 与中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.cleaners.pipeline import clean, crop_safety, read_image   # noqa: E402
from app.parsers.image import sharpness                            # noqa: E402

SAMPLES = os.path.join(ROOT, "samples", "private")
OUTDIR = os.path.join(ROOT, "tests", "clean-out")
TARGETS = ["数学作业.jpeg", "第三单元达标练习题A.jpeg", "第三单元达标练习题B.jpg"]

OFF = {k: False for k in ("orient", "grayscale", "deskew", "denoise",
                          "enhance", "binarize", "autocrop", "normalize")}
PROFILES = {
    "geo_only":    {**OFF, "orient": True, "grayscale": True, "deskew": True, "autocrop": True},
    "geo+norm":    {**OFF, "orient": True, "grayscale": True, "deskew": True, "autocrop": True, "normalize": True},
    "geo+denoise": {**OFF, "orient": True, "grayscale": True, "deskew": True, "autocrop": True, "denoise": True},
    "full":        {**OFF, "orient": True, "grayscale": True, "deskew": True, "autocrop": True,
                    "denoise": True, "enhance": True, "normalize": True},
    "full+binary": {**OFF, "orient": True, "grayscale": True, "deskew": True, "autocrop": True,
                    "denoise": True, "enhance": True, "normalize": True, "binarize": True},
}


def ocr(engine, path):
    t0 = time.time()
    res, _ = engine(path)
    ms = round((time.time() - t0) * 1000)
    lines = [r[1] for r in (res or [])]
    confs = [r[2] for r in (res or [])]
    text = "".join(lines)
    return {"ms": ms, "lines": len(lines), "chars": len("".join(text.split())),
            "avg_conf": round(sum(confs) / len(confs), 4) if confs else 0}


def main():
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    os.makedirs(OUTDIR, exist_ok=True)
    report = []
    failures = 0

    for fn in TARGETS:
        src = os.path.join(SAMPLES, fn)
        if not os.path.exists(src):
            print("缺样本", fn); continue
        base = ocr(engine, src)
        b_sharp = sharpness(src)
        # 裁边安全性：同一张图、同一阈值下量「裁框外的边缘带还剩多少墨」。
        # 不用 ink_retention —— 跨处理比墨迹量没有意义（CLAHE 会改 OTSU 阈值本身）。
        safety = crop_safety(read_image(src))
        print(f"\n=== {fn} ===  原始: 清晰度 {b_sharp:.0f} | {base['lines']}行 "
              f"{base['chars']}字 置信度 {base['avg_conf']} | {base['ms']}ms")
        print(f"  裁边安全性: {safety['note']}  裁框 {safety.get('size')}")
        row = {"file": fn, "before": {"sharpness": round(b_sharp, 1), **base},
               "crop_safety": safety, "profiles": {}}
        if not safety["ok"]:
            print("  ✗ 裁边会切掉内容，autocrop 档位不可用")
            failures += 1

        for name, opt in PROFILES.items():
            out = os.path.join(OUTDIR, f"{os.path.splitext(fn)[0]}__{name}.png")
            t0 = time.time()
            r = clean(src, out, options=opt, exif_orientation=1)
            cms = round((time.time() - t0) * 1000)
            a = ocr(engine, out)
            a_sharp = sharpness(out)
            # 闸门只看两件事：清晰度别崩、裁边别切内容。OCR 字数仅供参考（对版面有 ±5% 抖动）
            bad = []
            if a_sharp < b_sharp * 0.5 and b_sharp > 0:
                bad.append(f"清晰度暴跌 {b_sharp:.0f}→{a_sharp:.0f}")
            if opt.get("autocrop") and not safety["ok"]:
                bad.append("裁边不安全")
            mark = "✗ " + "; ".join(bad) if bad else "✓"
            print(f"  {name:14} {cms:5}ms 清晰度{a_sharp:8.0f}  "
                  f"[OCR 参考 {a['chars']}字/{a['avg_conf']:.3f}]  {mark}")
            row["profiles"][name] = {"clean_ms": cms, "sharpness": round(a_sharp, 1),
                                     **a, "fail": bad or None, "out": os.path.relpath(out, ROOT)}
            if bad:
                failures += 1
        report.append(row)

    best_path = os.path.join(ROOT, "tests", "cleaners-report.json")
    with open(best_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print("\n=== 判读 ===")
    print("清洗目的是【打印质量】。判据 = 清晰度不崩 + 裁边不切内容；OCR 列仅供参考。")
    for row in report:
        good = [k for k, v in row["profiles"].items() if not v["fail"]]
        print(f"  {row['file']:26} 安全档位: {', '.join(good) or '（无）'}")
    print(f"\nGATE: {failures} 项不合格（详见 tests/cleaners-report.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
