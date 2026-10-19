"""在真实/公开材料上实测题型识别准确率（PRD F11 的 ≥80% 判据）。

判据不用"看着差不多"：
  · 题号是否 1..N 连续且无重复（漏切/重切一目了然）
  · 内容零丢失：原卷每一行文字，去掉空白后必须能在题目文本+选项里找到
  · 人工核对表：把切出来的题打印出来，供人逐条判对错

用法: py -3.11 tests/run_extractor.py [文件...]
"""
from __future__ import annotations

import glob
import json
import os
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                   # noqa: E402
from app.layout.columns import structure_page                    # noqa: E402
from app.layout.engine import wrap_text                          # noqa: E402
from app.parsers.pdf import parse_pdf                            # noqa: E402
from app.extractor.rules import extract, flatten_questions       # noqa: E402


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return "".join(ch for ch in s if not ch.isspace())


def lines_from_pdf(path: str) -> tuple[list[str], list[str]]:
    """返回（按阅读顺序的文本行, 原始行）。原始行用于算内容零丢失。"""
    doc = pymupdf.open(path)
    ordered: list[str] = []
    raw: list[str] = []
    for page in doc:
        items = []
        for blk in page.get_text("dict").get("blocks", []):
            if blk.get("type") != 0:
                continue
            for ln in blk.get("lines", []):
                text = "".join(s.get("text", "") for s in ln.get("spans", []))
                if not text.strip():
                    continue
                bb = ln["bbox"]
                it = {"text": text.strip(), "x": bb[0], "y": bb[1],
                      "w": bb[2] - bb[0], "h": max(bb[3] - bb[1], 1)}
                items.append(it)
                raw.append(it["text"])
        if not items:
            continue
        page_w = max(i["x"] + i["w"] for i in items) + 1
        st = structure_page(items, page_w, y_tol=10)
        ordered += [l["text"] for l in st["lines"]]
    doc.close()
    return ordered, raw


def check(path: str) -> dict:
    ordered, raw = lines_from_pdf(path)
    res = extract(ordered, title=os.path.basename(path))
    qs = flatten_questions(res)
    nums = [q["q_no"] for q in qs if q["q_no"] is not None]
    # 重号/缺号必须【在大题内部】算：中文卷每个大题都从 1 重新编号，
    # 全文档查重会把正常结构误判成异常（实测扫出 8 个假重号）。
    dup = 0
    missing: list[int] = []
    for sec in res["sections"]:
        sn = [q["q_no"] for q in sec["questions"] if q["q_no"] is not None]
        dup += len(sn) - len(set(sn))
        if sn:
            missing += [n for n in range(min(sn), max(sn) + 1) if n not in sn]
    # 内容零丢失：每个原始行（≥4 字）必须能在切出的题目里找到，
    # 或在被有意跳过的表头行里。
    # ⚠️ 必须先剥掉题号前缀再比：提取器把 "1、" 挪进了 q_no 字段，
    #    整行原文自然匹配不上 —— 上一版把 15 行"正常剥号"误报成了丢内容。
    hay = norm(" ".join(q["text"] + " " + " ".join(q["options"]) for q in qs))
    hay += norm(" ".join(res["skipped_header_lines"]))
    prefix_re = __import__("re").compile(r"^(?:\d{1,3}[、.．]|（\d{1,3}）|[①-⑳])\s*")

    def probe(line: str) -> str:
        prev = None
        s = line
        while prev != s:                       # 可能有多层前缀（"3. 五八（）" 里也有数字）
            prev = s
            s = prefix_re.sub("", s.strip(), count=1)
        return norm(s)[:14]

    lost = []
    for l in raw:
        key = probe(l)
        if len(key) >= 4 and key not in hay:
            lost.append(l)
    types: dict[str, int] = {}
    for q in qs:
        types[q["qtype"]] = types.get(q["qtype"], 0) + 1
    review = sum(1 for q in qs if q.get("needs_review"))
    return {"file": os.path.basename(path), "lines": len(ordered), "questions": len(qs),
            "numbered": len(nums), "dup_no": dup, "missing_no": missing,
            "types": types, "needs_review": review,
            "lost_lines": len(lost), "lost_sample": lost[:3],
            "questions_detail": [{k: q[k] for k in ("q_no", "qtype", "section", "text",
                                                    "options", "confidence")} for q in qs]}


def main():
    args = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "samples", "private", "*.pdf")))
    out = []
    for p in args:
        try:
            r = check(p)
        except Exception as e:
            print(f"【{os.path.basename(p)}】!! {type(e).__name__}: {e}")
            continue
        out.append(r)
        # ⚠️ 0 题不是"无异常"，是"什么都没测"。上一版只查重号/缺号/丢行，
        #    于是 5 份扫描版 PDF 各产出 0 题也被打了 ✓ —— 零计数有两种含义：全过 / 尺坏了。
        zero = r["questions"] == 0
        bad_struct = r["dup_no"] > 0 or bool(r["missing_no"]) or r["lost_lines"] > 0
        flag = "✗ 0 题（未接 OCR 或无文本层）" if zero else ("⚠ 结构异常" if bad_struct else "✓")
        print(f"\n【{r['file']}】{flag} 行 {r['lines']} → 题 {r['questions']}"
              f"（有编号 {r['numbered']}，重号 {r['dup_no']}，缺号 {r['missing_no']}）")
        if zero:
            r["zero_output"] = True
        print(f"   题型分布 {r['types']}  待校对 {r['needs_review']}  内容丢失行 {r['lost_lines']}")
        for l in r["lost_sample"]:
            print(f"     丢: {l[:60]}")
        for q in r["questions_detail"][:8]:
            print(f"     {q['q_no']}. [{q['qtype']}] {q['text'][:44]}"
                  f"{' | ' + '/'.join(o[:14] for o in q['options'][:4]) if q['options'] else ''}")

    with open(os.path.join(ROOT, "tests", "extractor-report.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    tot_q = sum(r["questions"] for r in out)
    zero = [r for r in out if r.get("zero_output")]
    bad = [r for r in out if r["dup_no"] or r["missing_no"] or r["lost_lines"]]
    print(f"\n共 {len(out)} 份 / {tot_q} 题；0 产出 {len(zero)} 份；结构异常 {len(bad)} 份")
    if zero:
        print(f"   ⚠️ 这些需要先接 OCR：{', '.join(r['file'] for r in zero)}")
    print("明细 → tests/extractor-report.json（含每题切分结果，供人工逐条核对）")


if __name__ == "__main__":
    main()
