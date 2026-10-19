"""测 OCR → 分栏归位 → 切题 这条链（真实扫描卷）。

用法: py -3.11 tests/run_ocr_extract.py [文件...]
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                   # noqa: E402
from app.extractor import ocr as O                               # noqa: E402
from app.extractor.rules import extract, flatten_questions       # noqa: E402
from app.parsers.pdf import SCAN_TEXT_THRESHOLD                  # noqa: E402


def text_lines_from_pdf(path: str) -> list[str]:
    doc = pymupdf.open(path)
    out: list[str] = []
    for page in doc:
        items = []
        for blk in page.get_text("dict").get("blocks", []):
            if blk.get("type") != 0:
                continue
            for ln in blk.get("lines", []):
                t = "".join(s.get("text", "") for s in ln.get("spans", []))
                if t.strip():
                    bb = ln["bbox"]
                    items.append({"text": t.strip(), "x": bb[0], "y": bb[1],
                                  "w": bb[2] - bb[0], "h": max(bb[3] - bb[1], 1)})
        if items:
            w = max(i["x"] + i["w"] for i in items) + 1
            out += O.ordered_lines(items, w)
    doc.close()
    return out


def main(paths: list[str]):
    ok, why = O.available()
    print(f"OCR 引擎: {'可用 ' + why if ok else '不可用 ' + why}\n")
    if not ok:
        return 2
    report = []
    for p in paths:
        name = os.path.basename(p)
        doc = pymupdf.open(p)
        chars = sum(len("".join((pg.get_text("text") or "").split())) for pg in doc)
        n = doc.page_count
        doc.close()
        route = "文本层" if chars >= SCAN_TEXT_THRESHOLD else "OCR"
        t0 = time.time()
        if route == "OCR":
            r = O.ocr_pdf(p, work_dir=os.path.join(ROOT, "var", "ocr"), dpi=300)
            items = [dict(i, page=pg["page_no"]) for pg in r["pages"] for i in pg["items"]]
            lines = []
            for pg in r["pages"]:
                lines += O.ordered_lines(pg["items"], pg["width"] or 1)
            conf = round(sum(i["conf"] for i in items) / len(items), 3) if items else 0
        else:
            lines = text_lines_from_pdf(p)
            conf = 1.0
        ms = round((time.time() - t0) * 1000)
        res = extract(lines, title=name)
        qs = flatten_questions(res)
        nums = [q["q_no"] for q in qs if q["q_no"] is not None]
        # 重号只在大题内部算（中文卷每大题都从 1 重新编号）
        dup = 0
        for sec in res["sections"]:
            sn = [q["q_no"] for q in sec["questions"] if q["q_no"] is not None]
            dup += len(sn) - len(set(sn))
        types: dict[str, int] = {}
        for q in qs:
            types[q["qtype"]] = types.get(q["qtype"], 0) + 1
        rec = {"file": name, "route": route, "pages": n, "lines": len(lines),
               "questions": len(qs), "numbered": len(nums),
               "dup": dup, "conf": conf, "ms": ms, "types": types}
        report.append(rec)
        print(f"【{name}】走 {route}  {n} 页 {ms}ms  行 {len(lines)} → 题 {len(qs)}"
              f"（编号 {len(nums)}，重号 {rec['dup']}）OCR置信 {conf}")
        print(f"   题型 {types}")
        for q in qs[:6]:
            print(f"     {q['q_no']}. [{q['qtype']}] {q['text'][:46]}"
                  f"{' | ' + '/'.join(o[:12] for o in q['options'][:4]) if q['options'] else ''}")

    with open(os.path.join(ROOT, "tests", "ocr-extract-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    zero = [r for r in report if r["questions"] == 0]
    print(f"\n共 {len(report)} 份；0 产出 {len(zero)} 份")
    for r in zero:
        print("   ✗", r["file"], r["route"])
    return 1 if zero else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        args = sorted(glob.glob(os.path.join(ROOT, "samples", "private", "*.pdf")))
    sys.exit(main(args))
