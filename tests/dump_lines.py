"""把「行」缓存下来，便于反复看切题结果而不用每次重跑 OCR（OCR 一份 8 页卷要 18s）。

用法:
  py -3.11 tests/dump_lines.py --dump 全部        # 跑 OCR 并写 var/ocr/lines.json
  py -3.11 tests/dump_lines.py --show 扫描卷名   # 读缓存，打印行 + 切题标记（名字取子串即可）
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                   # noqa: E402
from app.extractor import ocr as O                               # noqa: E402
from app.extractor.rules import (extract, flatten_questions,      # noqa: E402
                                 _is_section, _parse_question_no)
from app.parsers.pdf import SCAN_TEXT_THRESHOLD                   # noqa: E402

CACHE = os.path.join(ROOT, "data", "ocr_lines.json")   # 不能放 var/：服务启动会清空 var/
sys.path.insert(0, os.path.join(ROOT, "tests"))
from run_ocr_extract import text_lines_from_pdf                    # noqa: E402


def dump() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "samples", "private", "*.pdf"))):
        name = os.path.basename(p)
        doc = pymupdf.open(p)
        chars = sum(len("".join((pg.get_text("text") or "").split())) for pg in doc)
        doc.close()
        if chars >= SCAN_TEXT_THRESHOLD:
            lines = text_lines_from_pdf(p)
        else:
            r = O.ocr_pdf(p, work_dir=os.path.join(ROOT, "var", "ocr"), dpi=300)
            lines = []
            for pg in r["pages"]:
                lines += O.ordered_lines(pg["items"], pg["width"] or 1)
        out[name] = lines
        print(f"  {name}: {len(lines)} 行")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return out


def show(needle: str) -> None:
    data = json.load(open(CACHE, encoding="utf-8"))
    key = next((k for k in data if needle in k), None)
    if not key:
        print("缓存里没有", needle, "，先 --dump")
        return
    lines = data[key]
    res = extract(lines, title=key)
    qs = flatten_questions(res)
    start: dict[str, str] = {}
    for si, sec in enumerate(res["sections"]):
        for q in sec["questions"]:
            first = (q.get("source_lines") or [""])[0]
            start.setdefault(first, f"题{q['q_no']} [{q['qtype']}] 大{si+1}:{sec['name'][:14]}")
    print(f"== {key}  行 {len(lines)}  大题 {len(res['sections'])}  题 {len(qs)}")
    for si, sec in enumerate(res["sections"]):
        nums = [q["q_no"] for q in sec["questions"] if q["q_no"] is not None]
        print(f"  大题{si+1} 「{sec['name'][:24]}」 题{len(sec['questions'])} "
              f"编号{nums[:14]}{'…' if len(nums) > 14 else ''}")
    print("--- 行 ---")
    for i, l in enumerate(lines):
        tag = start.get(l, "")
        if not tag and _is_section(l)[0]:
            tag = "★大题"
        if not tag and _parse_question_no(l)[0] is not None:
            tag = "☆题号"
        if tag:
            print(f"{i:3d} | {tag:38s} | {l[:52]}")
        elif any(k in l for k in ("第", "天", "课时", "周", "讲")) and len(l) <= 30:
            print(f"{i:3d} | {'（未识别为分段）':34s} | {l[:52]}")


def stats() -> int:
    """只读缓存，快速看切分质量（改规则时用这个，别每次重跑 OCR）。"""
    data = json.load(open(CACHE, encoding="utf-8"))
    bad = 0
    for key, lines in data.items():
        res = extract(lines, title=key)
        qs = flatten_questions(res)
        dup = 0
        for sec in res["sections"]:
            sn = [q["q_no"] for q in sec["questions"] if q["q_no"] is not None]
            dup += len(sn) - len(set(sn))
        nums = [q["q_no"] for q in qs if q["q_no"] is not None]
        if dup or not qs:
            bad += 1
        print(f"【{key}】大题 {len(res['sections'])}  题 {len(qs)}（编号 {len(nums)}）"
              f"重号 {dup}  噪声 {len(res['dropped_noise'])}  栏目 {len(res['stage_markers'])}")
        for si, sec in enumerate(res["sections"]):
            sn = [q["q_no"] for q in sec["questions"] if q["q_no"] is not None]
            flag = "  ✗重号" if len(sn) != len(set(sn)) else ""
            print(f"   {si+1}. 「{sec['name'][:28]}」 题{len(sec['questions'])} {sn[:12]}{flag}")
    return 1 if bad else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--dump" in a:
        dump()
    elif "--stats" in a:
        sys.exit(stats())
    elif "--show" in a:
        show(a[a.index("--show") + 1])
    else:
        print(__doc__)
