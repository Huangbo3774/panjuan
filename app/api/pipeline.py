"""任务流水线：解析 → 清洗 → 排版 → 出 PDF → 预览图（PRD §4.2–4.5）。"""
from __future__ import annotations

import os
import time
import traceback

from ..parsers.pdf import parse_pdf
from ..parsers.docx import parse_docx
from ..parsers.image import parse_image
from ..cleaners.pipeline import clean
from ..layout.options import LayoutOptions
from ..layout.engine import build_layout
from ..papers.pdf_writer import render_pdf, ensure_fonts, bind_metrics


def _parse(path: str, work: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return parse_pdf(path, render_dir=os.path.join(work, "render"), dpi=300)
    if ext == ".docx":
        return parse_docx(path, media_dir=os.path.join(work, "media"))
    return parse_image(path)


def _clean_scans(parsed: dict, work: str, ink_saver: bool = False) -> dict:
    for pg in parsed["pages"]:
        p = pg.get("rendered_image")
        if not pg.get("is_scan"):
            continue
        if not p or not os.path.exists(p):
            cand = next((b.get("path") for b in pg.get("blocks", [])
                         if b.get("kind") == "image" and b.get("path")
                         and os.path.exists(b["path"])), None)
            p = cand
        if not p:
            continue
        out = os.path.join(work, "clean",
                           f"p{pg['page_no']}_clean{'_ink' if ink_saver else ''}.png")
        # 省墨模式必须真的落到像素上：显式传 options 会走 explicit 档（不自动分档），
        # 否则开关拨了、产物一模一样（验收 F05 第一版就是这样假通过的）
        opts = {"binarize": True} if ink_saver else None
        try:
            r = clean(p, out, options=opts, exif_orientation=1)
            pg["rendered_image"] = out
            pg["clean_profile"] = r["profile"]
            pg["ink_saver"] = ink_saver
        except Exception as e:
            pg["clean_error"] = str(e)
    return parsed


def run_task(store, tid: str) -> None:
    t = store.get(tid)
    if not t:
        return
    work = t.work
    os.makedirs(os.path.join(work, "clean"), exist_ok=True)
    os.makedirs(os.path.join(work, "preview"), exist_ok=True)
    t.status, t.stage = "running", "解析中"
    ensure_fonts()
    bind_metrics()

    ok_files = [f for f in t.files if f["ok"]]
    total = len(ok_files) or 1
    try:
        for i, f in enumerate(ok_files, 1):
            t.stage = f"解析中 {i}/{total}"
            t.progress = 0.1 + 0.5 * (i - 1) / total
            try:
                parsed = _parse(f["path"], work)
                parsed = _clean_scans(parsed, work, bool(t.options.get("ink_saver")))
                # 把解析结果挂回文件条目：在线作答（/api/papers/*/parse）要按文件取文本，
                # 只靠 t.parsed 的追加顺序对齐文件，一旦有解析失败就会错位。
                f["parsed"] = parsed
                t.parsed.append(parsed)
                t.log(f"{f['name']} → {parsed['page_count']} 页，"
                      f"扫描 {parsed['scan_pages']} 页，标题「{parsed['title']}」")
            except Exception as e:
                t.log(f"{f['name']} 解析失败：{type(e).__name__}: {e}")
                f["ok"] = False
                f["error"] = f"{type(e).__name__}: {e}"

        relayout(t, work)
        t.progress = 1.0
        bad = [f for f in t.files if not f["ok"]]
        t.status = "partial" if bad and t.parsed else ("failed" if bad else "done")
        t.stage = "完成" if not bad else f"完成（{len(bad)} 个文件失败）"
    except Exception as e:
        t.status = "failed"
        t.error = f"{type(e).__name__}: {e}"
        t.log(traceback.format_exc(limit=6))


def relayout(t, work: str | None = None) -> None:
    """按当前选项重排版并出 PDF（选项变更时复用已解析结果，不重新解析）。

    状态必须置回 running：否则客户端 PUT 选项后立刻轮询会拿到上一轮的 done
    就去下载，撞上正在重写的文件。
    """
    work = work or t.work
    t.status, t.progress = "running", 0.9
    if not t.parsed:
        t.status, t.stage = "failed", "没有可排版的内容"
        return
    t.stage = "排版中"
    # 省墨开关变了要重新清洗（清洗产物是排版输入）
    want_ink = bool(t.options.get("ink_saver"))
    if any(bool(pg.get("ink_saver")) != want_ink for parsed in t.parsed for pg in parsed["pages"]
           if pg.get("is_scan")):
        t.stage = "清洗中（省墨）" if want_ink else "清洗中"
        for parsed in t.parsed:
            _clean_scans(parsed, work, want_ink)
            for pg in parsed["pages"]:
                if pg.get("is_scan"):
                    pg["ink_saver"] = want_ink
    opt = LayoutOptions.from_dict(t.options)
    # 先算出标题，再回填给前端（顺序不能反：这里曾因引用未赋值的 title 抛 UnboundLocalError，
    # 把全部验收用例打成 0/10）
    title = (opt.title or "").strip() or t.parsed[0].get("title") or "试卷"
    # 用户没填标题时回填解析出来的卷名，否则前端标题框空白却已经在用文件名当表头
    if not (opt.title or "").strip():
        opt.title = title
        t.options = opt.to_dict()
    try:
        pages = [pg for parsed in t.parsed for pg in parsed["pages"]]
        model = build_layout(pages, opt, title=title)
        t.stage = "生成 PDF"
        out = os.path.join(work, "export", f"{title}_磐卷A4.pdf")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        r = render_pdf(model, opt, out, title=title,
                       image_cache_dir=os.path.join(work, "_jpg"))
        t.export_path = r["path"]
        t.log(f"出卷 {r['pages']} 页 {(r['bytes']/1024):.0f}KB（{r['font']}）")
        t.previews = _make_previews(t, r["path"], work)
        t.status, t.stage, t.progress = "done", "完成", 1.0
    except Exception as e:
        t.log(f"排版失败：{type(e).__name__}: {e}")
        t.error = str(e)
        t.status = "failed"


def _make_previews(t, pdf_path: str, work: str) -> list[dict]:
    """把输出 PDF 逐页转 PNG 供预览。失败不影响出卷。"""
    out: list[dict] = []
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        for i, page in enumerate(doc):
            fn = f"preview_{i+1}.png"
            page.get_pixmap(dpi=110).save(os.path.join(work, "preview", fn))
            out.append({"page_no": i + 1, "image_url": f"/api/files/{t.id}/preview/{fn}"})
        doc.close()
    except Exception as e:
        t.log(f"预览图生成失败（不影响下载）：{e}")
    return out
