"""端到端：真实材料 → 解析 → 清洗 → A4 排版 → 试卷 PDF → 回读验证。

用法: py -3.11 tests/run_e2e.py [--only 关键词]
回读判据（不是"文件存在"就算过）：
  ① 页数 > 0；② 文件大小合理；③ 文字版 PDF 重排后仍能抽到中文字（字体嵌入正确）；
  ④ 扫描页在输出 PDF 里确实以图像形式存在（不是空白页）。
"""
from __future__ import annotations

import os
import sys
import time
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                    # noqa: E402
from app.parsers.pdf import parse_pdf                             # noqa: E402
from app.parsers.docx import parse_docx                           # noqa: E402
from app.parsers.image import parse_image                         # noqa: E402
from app.cleaners.pipeline import clean                           # noqa: E402
from app.layout.options import LayoutOptions                      # noqa: E402
from app.layout.engine import build_layout                        # noqa: E402
from app.papers.pdf_writer import render_pdf, ensure_fonts, bind_metrics   # noqa: E402

SAMPLES = os.path.join(ROOT, "samples", "private")
WORK = os.path.join(ROOT, "var", "e2e")


def parse_one(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return parse_pdf(path, render_dir=os.path.join(WORK, "render"))
    if ext == ".docx":
        return parse_docx(path, media_dir=os.path.join(WORK, "media"))
    return parse_image(path)


def clean_scans(parsed: dict, src: str) -> dict:
    """对扫描页跑清洗（含 PDF 渲染出的整页图）。"""
    for pg in parsed["pages"]:
        p = pg.get("rendered_image")
        if pg.get("is_scan") and p and os.path.exists(p):
            out = p.replace(".png", "_clean.png")
            r = clean(p, out, exif_orientation=1)
            pg["rendered_image"] = out
            pg["profile"] = r["profile"]
    return parsed


def verify(out_pdf: str, parsed: dict) -> dict:
    doc = pymupdf.open(out_pdf)
    pages = doc.page_count
    chars = sum(len("".join((p.get_text("text") or "").split())) for p in doc)
    imgs = sum(len(p.get_images(full=True)) for p in doc)
    sizes = {tuple(round(v) for v in (p.rect.width, p.rect.height)) for p in doc}
    sample = ""
    for p in doc:
        t = (p.get_text("text") or "").strip()
        if t:
            sample = t.replace("\n", " ")[:60]
            break
    doc.close()
    src_text_chars = sum(pg["text_chars"] for pg in parsed["pages"])
    src_scans = sum(1 for pg in parsed["pages"] if pg.get("is_scan"))
    problems = []
    if pages == 0:
        problems.append("0 页")
    if sizes and sizes != {(595, 842)}:
        problems.append(f"页面尺寸非 A4: {sizes}")
    if src_text_chars > 100 and chars < src_text_chars * 0.5:
        problems.append(f"文字大量丢失 {src_text_chars}→{chars}")
    if src_scans and imgs == 0:
        problems.append("扫描页没有以图像形式进入 PDF")
    mb = os.path.getsize(out_pdf) / 1048576
    if mb > 8:
        problems.append(f"体积 {mb:.1f}MB 过大（微信/邮件传不动）")
    return {"pages": pages, "out_chars": chars, "src_text_chars": src_text_chars,
            "images": imgs, "page_sizes": list(sizes), "sample": sample,
            "mb": round(mb, 2), "problems": problems}


def main(only: str | None):
    os.makedirs(WORK, exist_ok=True)
    ensure_fonts()
    bind_metrics()
    st = ensure_fonts()
    print(f"字体: {st['note']}  regular={st['family']} bold={st.get('bold')}\n")

    files = sorted(glob.glob(os.path.join(SAMPLES, "*")))
    if only:
        files = [f for f in files if only in os.path.basename(f)]
    results = []
    for f in files:
        name = os.path.basename(f)
        t0 = time.time()
        try:
            parsed = clean_scans(parse_one(f), f)
            opt = LayoutOptions(title=parsed["title"])
            # build_layout 吃的是【页列表】，不是整个 parsed 字典 —— 传错会静默排出空页
            model = build_layout(parsed["pages"], opt, title=parsed["title"])
            out = os.path.join(WORK, f"{os.path.splitext(name)[0]}_磐卷A4.pdf")
            r = render_pdf(model, opt, out, title=parsed["title"])
            v = verify(out, parsed)
            ms = round((time.time() - t0) * 1000)
            ok = not v["problems"]
            print(f"【{name}】{ms}ms → {r['pages']} 页 {(r['bytes']/1024):.0f}KB  "
                  f"抽出 {v['out_chars']} 字  图 {v['images']} 张  {'✓' if ok else '✗ ' + '; '.join(v['problems'])}")
            if v["sample"]:
                print(f"    回读文本: {v['sample']}")
            results.append({"file": name, "ms": ms, "ok": ok, **v,
                            "out": os.path.relpath(r["path"], ROOT),
                            "flow": model["stats"]})
        except Exception as e:
            import traceback
            print(f"【{name}】!! 失败 {type(e).__name__}: {e}")
            traceback.print_exc(limit=4)
            results.append({"file": name, "ok": False, "error": f"{type(e).__name__}: {e}"})

    import json
    with open(os.path.join(ROOT, "tests", "e2e-report.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    bad = [r for r in results if not r.get("ok")]
    print(f"\n{'='*60}\n{len(results)} 份，失败 {len(bad)}")
    for b in bad:
        print("  ✗", b["file"], b.get("error") or "; ".join(b.get("problems", [])))
    print("明细 → tests/e2e-report.json   产物 → var/e2e/")
    return 1 if bad else 0


if __name__ == "__main__":
    arg = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--only" else None
    sys.exit(main(arg))
