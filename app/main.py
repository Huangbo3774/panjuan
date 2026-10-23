"""磐卷 PaperForge · FastAPI 入口（PRD §7.4）

本机/局域网单用户工具，不做鉴权（PRD §6 安全项已注明风险）。
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.pipeline import run_task                     # 任务流水线
from app.api.store import STORE                           # 任务表
from app.api.papers import router as papers_router        # V1.1 在线作答
from app.storage import db                                # V1.1 SQLite
from app.paths import WEB, VAR, BUILD_STAMP, FROZEN, HOME_NOTE, APP_HOME

# 路径不再在这里算：main.py / store.py / db.py 原来各写了一遍「往上三层找仓库根」，
# 打包成 exe 后 __file__ 指向只读的解包目录，那三处会一起算错（孩子的作答库
# 会跑到 %TEMP% 里）。统一收在 app/paths.py，见那个文件的注释。
ROOT = APP_HOME       # 旧名字留着：main.py 里多处用 ROOT

MAX_FILES = 50
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
ALLOWED = {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}

app = FastAPI(title="磐卷 PaperForge", version="1.2.6")
app.include_router(papers_router)


@app.on_event("startup")
def _cleanup_stale() -> None:
    """服务启动清空临时目录（PRD §4.7），但建好 V1.1 的数据库。
    ⚠️ 清理只碰 var/：试卷、题目、标准答案、作答记录在 data/papers.db，
       跟着 var/ 一起删等于每次重启把孩子的作业删掉。"""
    if os.path.isdir(VAR):
        shutil.rmtree(VAR, ignore_errors=True)
    os.makedirs(VAR, exist_ok=True)
    db.init()


def sanitize(name: str) -> str:
    """文件名消毒：去路径分隔符与 Windows 非法字符，但保留中文。
    （JS 版曾因把字段名当文件名而静默丢文件，这里显式只清危险字符。）"""
    base = os.path.basename(name or "file").replace("\\", "/").split("/")[-1]
    base = re.sub(r'[:*?"<>|]', "_", base)
    base = re.sub(r"\s+", " ", base).strip() or "file"
    return base[:120]


@app.get("/api/health")
def health() -> dict[str, Any]:
    from app.papers.pdf_writer import ensure_fonts
    st = ensure_fonts()
    # pid + 代码指纹：验收脚本必须确认"回答我的是我刚起的那个服务"。
    # 实测踩过：上一轮测试的服务没被杀掉、还占着端口，新起的 uvicorn 静默绑定失败，
    # 于是"新代码的验收"其实跑在旧代码上，全绿也是假绿。
    # OCR 引擎状态也报出去：网页上"识别题型失败"那句提示必须能分清
    # "这台机器没装 OCR"和"服务端自己出错了"，不能一律怪引擎（实测就误判过一次：
    # 真因是临时图撞名导致 500，提示却写"常见于纯扫描又缺 OCR 引擎"）。
    from app.extractor import ocr as _O
    ocr_ok, ocr_why = _O.available()
    return {"ok": True, "service": "paper-forge", "font": st.get("note"),
            "ocr": {"ok": bool(ocr_ok), "why": ocr_why},
            "tasks": len(STORE), "pid": os.getpid(),
            "frozen": FROZEN, "home": APP_HOME, "home_note": HOME_NOTE,
            # 冻结态源码不在盘上，取 exe 的 mtime 才是"这份程序什么时候构建的"
            "build": int(BUILD_STAMP)}


@app.post("/api/tasks")
async def create_task(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if not files:
        raise HTTPException(400, "没有收到文件")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"一次最多 {MAX_FILES} 个文件")

    task_id = uuid.uuid4().hex[:12]
    work = os.path.join(VAR, task_id, "upload")
    os.makedirs(work, exist_ok=True)

    saved: list[dict[str, Any]] = []
    total = 0
    for f in files:
        name = sanitize(f.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED:
            saved.append({"name": name, "ok": False,
                          "error": f"不支持的格式 {ext or '(无扩展名)'}；.doc 请先另存为 .docx"})
            continue
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            saved.append({"name": name, "ok": False, "error": "单文件超过 50MB"})
            continue
        if total + len(data) > MAX_TOTAL_BYTES:
            saved.append({"name": name, "ok": False, "error": "总量超过 200MB"})
            continue
        if len(data) == 0:
            saved.append({"name": name, "ok": False, "error": "空文件"})
            continue
        total += len(data)
        # 防重名覆盖：同名加序号
        target = os.path.join(work, name)
        i = 1
        while os.path.exists(target):
            stem, e = os.path.splitext(name)
            target = os.path.join(work, f"{stem}_{i}{e}")
            i += 1
        with open(target, "wb") as fh:
            fh.write(data)
        saved.append({"name": os.path.basename(target), "ok": True, "bytes": len(data),
                      "path": target})

    rec = STORE.create(task_id, saved)
    threading.Thread(target=run_task, args=(STORE, task_id), daemon=True).start()
    return {"task_id": task_id,
            "accepted": [s["name"] for s in saved if s["ok"]],
            "rejected": [{"name": s["name"], "error": s["error"]} for s in saved if not s["ok"]]}


@app.get("/api/tasks/{tid}")
def get_task(tid: str) -> dict[str, Any]:
    rec = STORE.get(tid)
    if not rec:
        raise HTTPException(404, "任务不存在")
    return rec.public()


@app.get("/api/tasks/{tid}/pages")
def task_pages(tid: str) -> dict[str, Any]:
    rec = STORE.get(tid)
    if not rec:
        raise HTTPException(404, "任务不存在")
    return {"pages": rec.preview_pages()}


@app.get("/api/files/{tid}/{kind}/{fname}")
def get_file(tid: str, kind: str, fname: str) -> FileResponse:
    """只允许读该任务工作区内的图片，路径严格约束在 var/<tid>/ 下。"""
    rec = STORE.get(tid)
    if not rec:
        raise HTTPException(404, "任务不存在")
    if kind not in ("preview", "export"):
        raise HTTPException(400, "kind 只支持 preview/export")
    base = os.path.realpath(os.path.join(VAR, tid, kind))
    target = os.path.realpath(os.path.join(base, sanitize(fname)))
    if not target.startswith(base + os.sep) or not os.path.isfile(target):
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


@app.put("/api/tasks/{tid}/options")
async def put_options(tid: str, body: dict) -> JSONResponse:
    rec = STORE.get(tid)
    if not rec:
        raise HTTPException(404, "任务不存在")
    rec.set_options(body or {})
    STORE.restart_layout(tid)
    return JSONResponse({"ok": True, "options": rec.options})


@app.get("/api/tasks/{tid}/export")
def export(tid: str, mode: str = "print") -> FileResponse:
    rec = STORE.get(tid)
    if not rec:
        raise HTTPException(404, "任务不存在")
    if mode != "print":
        raise HTTPException(400, "V1.0 只支持 mode=print（在线作答与批改在 V1.1）")
    p = rec.export_pdf()
    if not p or not os.path.isfile(p):
        raise HTTPException(409, "试卷尚未生成完成或已失败，请查看任务状态")
    return FileResponse(p, media_type="application/pdf", filename=os.path.basename(p))


@app.delete("/api/tasks/{tid}")
def delete(tid: str) -> dict[str, Any]:
    rec = STORE.get(tid)
    if not rec:
        raise HTTPException(404, "任务不存在")
    STORE.delete(tid)
    return {"ok": True}


class NoCacheStatic(StaticFiles):
    """本机工具：改了代码刷新就该看到。曾因为浏览器缓存旧 HTML，
    修好的日志渲染在页面上看起来"没生效"。"""

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        resp.headers.setdefault("Cache-Control", "no-cache")
        return resp


app.mount("/", NoCacheStatic(directory=WEB, html=True), name="web")
