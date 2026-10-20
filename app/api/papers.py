"""在线作答相关的接口（PRD §7.4 的 /api/papers/* 那一组 + V1.1 校对发布流）。

{id} 允许两种写法，前端不用关心：
  · 纯数字 = papers.id（已经建过试卷）
  · 任务号 = tasks 的 tid（第一次点「校对题目」时惰性建档，并记住 source_task）

工作流口径（用户明确要求）：
  上传 → 识别 → 【校对模式：改 / 增 / 删 / 发布】→ 发布 → 做题 → 批改 → 导出
校对是上传者的活，做题的人不该在作答过程里改题，所以 paper.html 上没有任何编辑入口；
而且没发布的卷子直接拒制作答（409），避免拿着一份识别错的卷子做半天。
"""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse

from .store import STORE
from ..paths import VAR, DATA
from ..extractor import lines as L
from ..extractor import ocr as OC
from ..extractor.figures import find_figures, strip_text_inside_figures
from ..extractor.rules import extract, flatten_questions
from ..grading.engine import grade, make_uid
from ..storage import db

router = APIRouter(prefix="/api/papers")

# 配图必须放 data/：var/ 在服务启动时会被整目录清空（PRD §4.7 临时目录）
# 两个目录都来自 app/paths.py，不在这里二次拼。


def _is_pid(s: str) -> bool:
    return str(s).isdigit()


def resolve(id_str: str) -> dict:
    """拿到试卷记录；传任务号且尚未建档时，先用任务信息建一张空壳试卷。"""
    if _is_pid(id_str):
        p = db.get_paper(int(id_str))
        if not p:
            raise HTTPException(404, f"没有试卷 {id_str}")
        return p
    t = STORE.get(id_str)
    if not t:
        raise HTTPException(404, f"任务 {id_str} 不存在（内存任务表，服务重启后请用试卷号）")
    p = db.find_paper_by_task(t.id)
    if p:
        return p
    title = (t.options.get("title") or "").strip() or (
        t.parsed[0].get("title") if t.parsed else "") or t.files[0]["name"]
    pid = db.create_paper(title=title, options=t.options, status="draft", source_task=t.id)
    return db.get_paper(pid) or {"id": pid, "title": title}


def figures_dir(pid: int) -> str:
    return os.path.join(DATA, "figures", str(pid))


@router.get("")
def api_list_papers(limit: int = Query(50, ge=1, le=200)) -> dict:
    return {"papers": db.list_papers(limit)}


@router.post("/{id_str}/parse")
def api_parse(id_str: str) -> dict:
    """题型识别（PRD F11）+ 题目配图裁剪。扫描页走 OCR，文字页走文本层，逐页路由。"""
    paper = resolve(id_str)
    pid = int(paper["id"])
    t = STORE.get(paper.get("source_task") or "")
    if not t:
        raise HTTPException(409, "原任务已不在内存（服务重启）。请重新上传后再识别。")
    ok, why = OC.available()
    r = L.lines_from_task(t)
    if not ok and not r["ann"]:
        raise HTTPException(422, f"这份材料需要 OCR 才能出题，但引擎不可用：{why}")

    res = extract(r["lines"], title=paper.get("title", ""))
    qs = flatten_questions(res)

    fig_note = ""
    try:
        spans = L.spans_for_questions(r["ann"], qs, pages=r.get("pages"),
                                      sections=res.get("sections"))
        sources = {}
        for gp in sorted({int(s["page"]) for s in spans}):
            kind = next((f["kind"] for f in r["files"]
                         if f["first_page"] <= gp < f["first_page"] + max(1, len(f["pages"]))), ".pdf")
            src = L.open_page_source(kind, "", gp, r["page_sources"], r["files"])
            if src:
                sources[gp] = src
        got = find_figures(sources, spans, figures_dir(pid), noise=r.get("noise")) \
            if sources else {}
        for qi, imgs in got.items():
            if 0 <= qi < len(qs):
                qs[qi]["images"] = imgs
        # 图里的标注行先被 OCR 拼进题干、又被裁进图里 → 同一句话印两遍
        # （判据与真实反例见 docs 14.12-F）。
        n_res = strip_text_inside_figures(qs, spans, got)
        fig_note = f"，裁出配图 {sum(len(v) for v in got.values())} 张"
        if n_res:
            fig_note += f"，清掉图内重复文字 {n_res} 行"
        # ── 卷面上【画出来】的图形符号（★＋★＝20 这种）：OCR 只认字，整行会读成
        #    "=20 39" 的残渣。这里按轮廓把算式还原出来，单独存 symbols 一列 ——
        #    不并进题干：家长必须能分清哪半句是卷面上读到的、哪半句是系统还原的。
        n_sym = 0
        try:
            import numpy as np2
            import cv2 as cv2m
            from ..extractor import symbols as SY
            for s in spans:
                qi = int(s.get("q_index", -1))
                src = sources.get(int(s["page"]))
                if not (0 <= qi < len(qs)) or not src:
                    continue
                g = SY.scan_span(src, s, np2, cv2m)
                if g.get("lines"):
                    qs[qi]["symbols"] = g["lines"]
                    n_sym += len(g["lines"])
            if n_sym:
                fig_note += f"，还原图形算式 {n_sym} 行"
        except Exception as e:                             # 认符号失败同样不许拖垮识别
            fig_note += f"，图形算式还原失败（{type(e).__name__}: {e}）"
    except Exception as e:                                 # 配图失败不能拖垮整卷识别
        fig_note = f"，配图裁剪失败（{type(e).__name__}: {e}）"

    saved = db.replace_questions(pid, qs)
    db.update_paper(pid, status="proofreading")
    return {
        "paper_id": pid, "title": res.get("title") or paper.get("title"),
        "status": "proofreading",
        "questions": saved,
        "sections": [{"name": s["name"], "count": len(s["questions"])} for s in res["sections"]],
        "dropped_noise": len(res["dropped_noise"]),
        "stage_markers": len(res["stage_markers"]),
        "answer_key_lines": res["answer_key_lines"][:5],
        "ocr": {"engine": why if ok else "不可用", "conf": r["ocr_conf"],
                "files": [{"file": f["file"], "lines": f["lines"]} for f in r["files"]],
                "errors": r["errors"]},
        "figures_note": fig_note,
        "needs_review": sum(1 for q in saved if q["needs_review"]),
    }


@router.get("/{id_str}/questions")
def api_questions(id_str: str, require_published: bool = False) -> dict:
    paper = resolve(id_str)
    pid = int(paper["id"])
    if require_published and paper.get("status") != "published":
        raise HTTPException(409, "这份试卷还没发布，请先去校对")
    qs = db.get_questions(pid)
    return {"paper_id": pid, "title": paper.get("title"), "status": paper.get("status"),
            "questions": qs, "key": db.latest_key(pid),
            "options": paper.get("options") or {},
            "needs_review": sum(1 for q in qs if q["needs_review"])}


@router.put("/{id_str}/questions")
def api_save_questions(id_str: str, payload: dict = Body(...)) -> dict:
    """保存校对结果：整批替换，或带 uid 的单题修改。"""
    paper = resolve(id_str)
    pid = int(paper["id"])
    if isinstance(payload.get("question"), dict):
        q = payload["question"]
        fields = {k: v for k, v in q.items()
                  if k in ("q_no", "section", "qtype", "text", "options", "blanks",
                           "score", "needs_review", "images")}
        db.update_question(pid, str(q.get("uid") or ""), **fields)
        return {"paper_id": pid, "updated": q.get("uid"), "questions": db.get_questions(pid)}
    items = payload.get("questions")
    if not isinstance(items, list):
        raise HTTPException(422, "需要 {questions:[...]} 或 {question:{...}}")
    saved = db.replace_questions(pid, items)
    return {"paper_id": pid, "count": len(saved), "questions": saved}


@router.post("/{id_str}/questions")
def api_add_question(id_str: str, payload: dict = Body(...)) -> dict:
    """校对页「加一道题」。after_uid 指定插在哪一题后面。"""
    paper = resolve(id_str)
    pid = int(paper["id"])
    q = payload.get("question")
    if not isinstance(q, dict):
        raise HTTPException(422, "需要 {question:{...}, after_uid?}")
    added = db.add_question(pid, q, payload.get("after_uid"))
    return {"paper_id": pid, "question": added, "questions": db.get_questions(pid)}


@router.delete("/{id_str}/questions/{uid}")
def api_delete_question(id_str: str, uid: str) -> dict:
    paper = resolve(id_str)
    pid = int(paper["id"])
    if not db.delete_question(pid, uid):
        raise HTTPException(404, f"没有删除任何题：{uid} 不属于试卷 {pid}")
    return {"paper_id": pid, "deleted": uid, "questions": db.get_questions(pid)}


@router.get("/{pid}/figures/{fname}")
def api_figure(pid: int, fname: str) -> FileResponse:
    """配图是【本机文件】，浏览器读不到，必须走这条路由。
    文件名先消毒：只允许基名 + .png，防 /figures/../../etc/passwd 这类越界。"""
    safe = os.path.basename(fname)
    if not re.fullmatch(r"[\w.\-]+\.png", safe):
        raise HTTPException(400, "文件名不合法")
    fp = os.path.join(figures_dir(int(pid)), safe)
    if not os.path.isfile(fp):
        raise HTTPException(404, "没有这张图")
    return FileResponse(fp, media_type="image/png")


@router.post("/{id_str}/publish")
def api_publish(id_str: str, payload: dict = Body(default={})) -> dict:
    """发布 = 校对收尾。校验过了才允许做题，标题/版式选项一起定稿。"""
    paper = resolve(id_str)
    pid = int(paper["id"])
    qs = db.get_questions(pid)
    if not qs:
        raise HTTPException(409, "一份题目都没有，不能发布")
    empty = [q["uid"] for q in qs
             if not (q.get("text") or "").strip() and not (q.get("images") or [])]
    if empty:
        raise HTTPException(409,
                            f"有 {len(empty)} 道题既没有题干也没有配图，先补上或删掉再发布")
    if payload.get("title"):
        db.update_paper(pid, title=str(payload["title"])[:80])
    if isinstance(payload.get("options"), dict):
        db.update_paper(pid, options={**(paper.get("options") or {}), **payload["options"]})
    db.update_paper(pid, status="published", published_at=db._now())
    p = db.get_paper(pid)
    return {"paper_id": pid, "status": p["status"], "published_at": p.get("published_at"),
            "questions": len(qs), "title": p.get("title")}


@router.post("/{id_str}/unpublish")
def api_unpublish(id_str: str) -> dict:
    """发布后还能改：撤回校对状态（已提交的作答不受影响）。"""
    paper = resolve(id_str)
    pid = int(paper["id"])
    db.update_paper(pid, status="proofreading")
    return {"paper_id": pid, "status": "proofreading"}


@router.post("/{id_str}/key")
def api_save_key(id_str: str, payload: dict = Body(...)) -> dict:
    """保存标准答案：逐题填 {answers:{uid:…}}，或把某次提交另存为标准答案。"""
    paper = resolve(id_str)
    pid = int(paper["id"])
    answers = payload.get("answers")
    if not isinstance(answers, dict) and payload.get("submission_id"):
        sub = db.get_submission(int(payload["submission_id"]))
        if not sub or int(sub["paper_id"]) != pid:
            raise HTTPException(404, "找不到那次提交，无法另存为标准答案")
        answers = {k: v for k, v in sub["answers"].items() if not str(k).startswith("_")}
    if not isinstance(answers, dict):
        raise HTTPException(422, "需要 {answers:{uid:…}} 或 {submission_id:N}")
    kid = db.save_key(pid, answers)
    return {"paper_id": pid, "key_id": kid, "answers": answers}


@router.post("/{id_str}/submissions")
def api_submit(id_str: str, payload: dict = Body(...)) -> dict:
    """提交学生作答并即时批改。"""
    paper = resolve(id_str)
    pid = int(paper["id"])
    if paper.get("status") != "published":
        raise HTTPException(409, "这份试卷还没发布，请先在校对页点「发布」")
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict):
        raise HTTPException(422, "answers 必须是 {uid: 作答} 字典")
    clean = {k: v for k, v in answers.items() if not str(k).startswith("_")}
    man = answers.get("_manual") if isinstance(answers.get("_manual"), dict) else {}
    manual = {str(k): v for k, v in man.items() if v in ("correct", "wrong", "pending")}
    qs = db.get_questions(pid)
    res = grade(qs, db.latest_key(pid), clean,
                scores={make_uid(q): float(q.get("score") or 1.0) for q in qs},
                manual=manual)
    sid = db.add_submission(pid, str(payload.get("class_name") or ""),
                            str(payload.get("student_name") or ""),
                            {**clean, **({"_manual": manual} if manual else {})}, res)
    return {"paper_id": pid, "submission_id": sid, **res}


@router.get("/{id_str}/grade")
def api_grade(id_str: str, submission_id: int | None = Query(None)) -> dict:
    paper = resolve(id_str)
    pid = int(paper["id"])
    subs = db.list_submissions(pid)
    sub = (db.get_submission(submission_id) if submission_id is not None
           else (subs[-1] if subs else None))
    if sub is not None and sub.get("paper_id") is not None and int(sub["paper_id"]) != pid:
        raise HTTPException(404, "那次作答不属于这份试卷")
    if not sub:
        raise HTTPException(404, "这份试卷还没有作答记录")
    return {"paper_id": pid, "submission_id": sub["id"],
            "class_name": sub.get("class_name"), "student_name": sub.get("student_name"),
            "graded_at": sub.get("graded_at"), **sub.get("results", {})}


@router.get("/{id_str}/submissions")
def api_submissions(id_str: str) -> dict:
    paper = resolve(id_str)
    pid = int(paper["id"])
    rows = db.list_submissions(pid)
    return {"paper_id": pid,
            "submissions": [{"id": r["id"], "class_name": r["class_name"],
                             "student_name": r["student_name"], "score": r["score"],
                             "total": r["total"], "graded_at": r["graded_at"],
                             "wrong": len((r.get("results") or {}).get("wrong_uids", []))}
                            for r in rows]}


@router.get("/{id_str}/printable")
def api_printable(id_str: str) -> dict:
    """第 4 步要按状态决定三种内容能不能选，而且要说清【为什么不能】。

    前端的三个单选不能靠"点了再说"：没作答却让人点「我的答案」，
    拿到的是一句 404，用户会以为程序坏了。所以这里一次性把状态和原因给出去。
    """
    paper = resolve(id_str)
    pid = int(paper["id"])
    qs = db.get_questions(pid)
    subs = db.list_submissions(pid)
    last = subs[-1] if subs else None
    has_key = bool(db.latest_key(pid))
    graded_ok = bool(last and (last.get("results") or {}).get("results"))
    return {
        "paper_id": pid,
        "title": paper.get("title"),
        "status": paper.get("status"),
        "published": paper.get("status") == "published",
        "questions": len(qs),
        "submissions": [{"id": s["id"], "student_name": s["student_name"],
                         "score": s["score"], "total": s["total"],
                         "graded_at": s["graded_at"]} for s in subs],
        "has_key": has_key,
        "can_blank": len(qs) > 0,
        "can_answered": bool(last),
        "can_graded": bool(last and has_key and graded_ok),
        "reasons": {
            "blank": "" if qs else "还没识别到题目（先在第 2 步校对并发布）",
            "answered": "" if last else "这份卷子还没人作答过：先去第 3 步做题，或改选「空白卷」",
            "graded": ("" if (last and has_key and graded_ok) else
                       ("这份卷子还没人作答过：先去第 3 步做题" if not last else
                        ("还没录标准答案：在做题页点「把我的作答存为标准答案」" if not has_key
                         else "这次作答没有批改结果，回第 3 步重新提交一次即可"))),
        },
    }


def _render_mode(mode: str) -> str:
    """proofread 是 V1.1 早期给「校对稿」用的名字，语义就是空白卷，保留别名。"""
    return "blank" if mode == "proofread" else mode


def _paper_pdf(pid: int, mode: str, submission_id: int | None) -> dict[str, Any]:
    """按内容模式渲染成 PDF。导出与预览共用这一条路，避免"预览一个样、下载另一个样"。"""
    from ..layout.options import LayoutOptions
    from ..papers.answer_writer import render_answers_pdf

    paper = db.get_paper(pid)
    if not paper:
        raise HTTPException(404, f"没有试卷 {pid}")
    qs = db.get_questions(pid)
    if not qs:
        raise HTTPException(409, "这份试卷还没识别题目，先调 /parse")
    mode = _render_mode(mode)
    answers: dict = {}
    grade_result: dict | None = None
    class_name = student_name = ""
    sub_id: int | None = None
    if mode in ("answered", "graded"):
        subs = db.list_submissions(pid)
        sub = db.get_submission(submission_id) if submission_id else (subs[-1] if subs else None)
        if not sub or (sub.get("paper_id") and int(sub["paper_id"]) != pid):
            raise HTTPException(404, "这份试卷还没有作答记录")
        sub_id = int(sub["id"])
        answers = sub["answers"]
        grade_result = sub.get("results") or {}
        class_name = sub.get("class_name") or ""
        student_name = sub.get("student_name") or ""
        if mode == "graded" and not grade_result.get("results"):
            raise HTTPException(409, "作答记录里没有批改结果，无法出批改版")

    opt = LayoutOptions.from_dict(paper.get("options") or {})
    out_dir = os.path.join(VAR, f"paper{pid}")
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", (paper.get("title") or "试卷"))[:60]
    label = {"blank": "空白卷", "answered": "我的答案", "graded": "答案加批改"}[mode]
    out = os.path.join(out_dir, f"{safe}_{label}.pdf")
    r = render_answers_pdf(qs, opt, out, title=paper.get("title") or "",
                           mode="graded" if mode == "graded" else "answered",
                           answers=answers, key=db.latest_key(pid),
                           grade_result=grade_result,
                           class_name=class_name, student_name=student_name,
                           figures_dir=figures_dir(pid))
    return {**r, "mode": mode, "label": label, "submission_id": sub_id,
            "options": opt.to_dict(), "paper_title": paper.get("title") or ""}


def _content_revision(pid: int, mode: str, sub_id: int | None, opt: dict, title: str) -> str:
    """决定"这一张预览图到底是什么内容"的全部输入 → 短哈希。

    为什么不用自增计数：题目改动、作答提交、标准答案录入、撤回发布……任何一处忘了
    bump，浏览器就会拿旧图继续显示，而 URL 一模一样 —— 用户看到的就是
    "我明明切了，左边怎么没变"。把影响像素的东西全哈希进来，忘了也变不了。
    """
    import hashlib
    import json as _j
    payload = _j.dumps({
        "mode": mode, "sub": sub_id, "opt": opt, "title": title,
        "qs": [{k: q.get(k) for k in ("uid", "q_no", "section", "qtype", "text",
                                      "options", "score", "images")}
               for q in db.get_questions(pid)],
        "key": db.latest_key(pid),
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


@router.get("/{id_str}/preview")
def api_preview(id_str: str, mode: str = Query("blank", pattern="^(blank|answered|graded|proofread)$"),
                submission_id: int | None = Query(None), dpi: int = Query(110, ge=60, le=200)) -> dict:
    """把第 4 步要打印的那份 PDF 逐页转成 PNG 给前端看。

    图片文件名里带内容哈希：preview_<rev>_1.png。所以每次内容真的变了，URL 必然变，
    浏览器不可能拿缓存 —— 上一版就是栽在"同名文件 + 没有 Cache-Control"上。
    """
    paper = resolve(id_str)
    pid = int(paper["id"])
    r = _paper_pdf(pid, mode, submission_id)
    rev = _content_revision(pid, r["mode"], r["submission_id"], r["options"], r["paper_title"])
    out_dir = os.path.join(VAR, f"paper{pid}", "preview")
    os.makedirs(out_dir, exist_ok=True)
    pages: list[dict[str, Any]] = []
    note = ""
    try:
        import pymupdf
        doc = pymupdf.open(r["path"])
        for fn in os.listdir(out_dir):
            if fn.startswith("preview_") and fn.endswith(".png"):
                try:
                    os.unlink(os.path.join(out_dir, fn))      # 旧版本号的图留着只会占地方
                except OSError:
                    pass
        for i, page in enumerate(doc):
            fn = f"preview_{rev}_{i + 1}.png"
            page.get_pixmap(dpi=dpi).save(os.path.join(out_dir, fn))
            pages.append({"page_no": i + 1,
                          "image_url": f"/api/papers/{pid}/preview/{fn}",
                          "w": page.rect.width, "h": page.rect.height})
        doc.close()
    except Exception as e:
        note = f"预览图生成失败（不影响下载 PDF）：{type(e).__name__}: {e}"
    return {"paper_id": pid, "mode": r["mode"], "revision": rev, "pages": pages,
            "pdf_pages": r["pages"], "pdf_bytes": r["bytes"], "note": note,
            "figures_drawn": r.get("figures_drawn", 0),
            "figures_missing": r.get("figures_missing", 0),
            "options": r["options"], "submission_id": r["submission_id"]}


@router.get("/{pid}/preview/{fname}")
def api_preview_file(pid: int, fname: str) -> FileResponse:
    base = os.path.realpath(os.path.join(VAR, f"paper{pid}", "preview"))
    target = os.path.realpath(os.path.join(base, os.path.basename(fname)))
    if not target.startswith(base + os.sep) or not re.fullmatch(r"preview_[\w.\-]+\.png",
                                                                os.path.basename(fname)) \
            or not os.path.isfile(target):
        raise HTTPException(404, "预览图不存在")
    return FileResponse(target, headers={"Cache-Control": "no-store"})


@router.put("/{id_str}/options")
def api_save_options(id_str: str, payload: dict = Body(...)) -> dict:
    """第 4 步的版式选项存到试卷上（不是任务上）：任务在内存里，重启就没了。"""
    from ..layout.options import LayoutOptions
    paper = resolve(id_str)
    pid = int(paper["id"])
    merged = {**(paper.get("options") or {}), **(payload or {})}
    opt = LayoutOptions.from_dict(merged)          # 过一遍：顺手把 two_up 与 page_format 对齐
    db.update_paper(pid, options=opt.to_dict())
    return {"paper_id": pid, "options": opt.to_dict()}


@router.get("/{id_str}/export")
def api_export(id_str: str,
               mode: str = Query("graded", pattern="^(answered|graded|proofread|blank)$"),
               submission_id: int | None = Query(None)) -> Any:
    """导出 PDF：blank 空白卷 / answered 我的答案 / graded 答案加批改。"""
    paper = resolve(id_str)
    r = _paper_pdf(int(paper["id"]), mode, submission_id)
    if r.get("figures_missing"):
        # 配图画不上＝这道题没法做，必须说出来，不能悄悄少印几张图
        r = {**r, "note": f"有 {r['figures_missing']} 张配图没能画上（图片文件缺失），请重新识别或补图"}
    return FileResponse(r["path"], filename=os.path.basename(r["path"]),
                        media_type="application/pdf")
