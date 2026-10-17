"""对真实材料跑一遍解析器，输出体检表。
用法: py -3.11 tests/run_parsers.py [目录]
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.parsers.pdf import parse_pdf          # noqa: E402
from app.parsers.docx import parse_docx        # noqa: E402
from app.parsers.image import parse_image      # noqa: E402

SUPPORTED = {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def main(d):
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith("_"):
            continue
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext not in SUPPORTED:
            print(f"跳过 {fn}（格式 {ext} 不在 PRD 支持范围）")
            continue
        t0 = time.time()
        try:
            if ext == ".pdf":
                r = parse_pdf(p)
            elif ext == ".docx":
                r = parse_docx(p)
            else:
                r = parse_image(p)
        except Exception as e:
            print(f"【{fn}】!! 解析失败 {type(e).__name__}: {e}")
            out.append({"file": fn, "error": f"{type(e).__name__}: {e}"})
            continue
        ms = round((time.time() - t0) * 1000)
        rec = {
            "file": fn, "kind": r["kind"], "pages": r["page_count"],
            "scan_pages": r["scan_pages"], "ms": ms, "bytes": os.path.getsize(p),
            "title": r["title"],
        }
        if r["kind"] == "pdf":
            rec["per_page"] = [
                {"p": pg["page_no"], "chars": pg["text_chars"], "scan": pg["is_scan"],
                 "font": pg["font_evidence"], "pt": f'{pg["w_pt"]}x{pg["h_pt"]}',
                 "landscape": pg["landscape"],
                 "text_blocks": sum(1 for b in pg["blocks"] if b["kind"] == "text"),
                 "img_blocks": sum(1 for b in pg["blocks"] if b["kind"] == "image")}
                for pg in r["pages"]
            ]
        elif r["kind"] == "image":
            b = r["pages"][0]["blocks"][0]
            rec["img"] = {k: b[k] for k in ("width_px", "height_px", "megapixels",
                                            "a4_300dpi_ratio", "sharpness_lapVar", "mean_luma")}
        else:
            rec["text_blocks"] = sum(1 for pg in r["pages"] for b in pg["blocks"] if b["kind"] == "text")
            rec["tables"] = sum(1 for pg in r["pages"] for b in pg["blocks"] if b.get("is_table"))
            rec["chars"] = r["pages"][0]["text_chars"]
        out.append(rec)

        # 控制台报告
        if r["kind"] == "pdf":
            print(f"【{fn}】{r['page_count']} 页，扫描页 {r['scan_pages']}，{ms}ms")
            for pg in rec["per_page"]:
                print(f"    p{pg['p']}: {pg['chars']}字 字体证据={pg['font']} → "
                      f"{'扫描件' if pg['scan'] else '文字页'}  {pg['pt']}pt"
                      f"{' 横向' if pg['landscape'] else ''}  文本块{pg['text_blocks']} 图块{pg['img_blocks']}")
        elif r["kind"] == "image":
            i = rec["img"]
            print(f"【{fn}】{i['width_px']}x{i['height_px']}  {i['megapixels']}MP  "
                  f"清晰度(拉普拉斯方差)={i['sharpness_lapVar']}  亮度={i['mean_luma']}  {ms}ms")
        else:
            print(f"【{fn}】段落 {rec['text_blocks']} 块，表格 {rec['tables']} 个，共 {rec['chars']} 字，{ms}ms")

    with open(os.path.join(ROOT, "tests", "parsers-report.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\n明细已存 tests/parsers-report.json（{len(out)} 份）")


if __name__ == "__main__":
    # 注意：sys.argv[1] 在缺省时是 IndexError，不是 falsy
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg or os.path.join(ROOT, "samples", "private"))
