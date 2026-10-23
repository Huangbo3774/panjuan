"""任务表（内存）。单用户本机工具，重启即清空 —— 与 PRD「本地优先、不留存」一致。"""
from __future__ import annotations

import os
import shutil
import threading
import time
from typing import Any

from ..layout.options import LayoutOptions

# 任务工作目录根：pipeline / papers 路由 / 存储都从这里取，
# 免得三处各自拼一遍「上三层 + var」——打包成 exe 时那种拼法会一起算错。
# 唯一来源是 app/paths.py。
from ..paths import APP_HOME as ROOT, VAR


class Task:
    def __init__(self, tid: str, files: list[dict]):
        self.id = tid
        self.files = files
        self.status = "queued"                 # queued|running|done|partial|failed
        self.stage = "排队中"
        self.progress = 0.0
        self.error: str | None = None
        self.created = time.time()
        self.parsed: list[dict] = []
        self.previews: list[dict] = []
        self.export_path: str | None = None
        self.options = LayoutOptions().to_dict()
        self.logs: list[dict] = []
        self.lock = threading.Lock()

    @property
    def work(self) -> str:
        return os.path.join(VAR, self.id)

    def log(self, msg: str) -> None:
        with self.lock:
            self.logs.append({"t": round(time.time() - self.created, 2), "msg": msg})

    def public(self) -> dict[str, Any]:
        return {
            "task_id": self.id, "status": self.status, "stage": self.stage,
            "progress": round(self.progress, 3), "error": self.error,
            "files": [{"name": f["name"], "ok": f["ok"], "error": f.get("error"),
                       "bytes": f.get("bytes")} for f in self.files],
            # 页数是【解析出来的实际页数】，不是上传文件数：Word 里贴 6 张扫描页
            # 曾被报成 pages:1（测试员据此判"预览 6 页与接口 1 页自相矛盾"）。
            "pages": (sum(len(p.get("pages") or []) for p in self.parsed)
                      if self.parsed else 0),
            "previews": self.previews,
            "export_ready": bool(self.export_path and os.path.isfile(self.export_path or "")),
            "options": self.options, "logs": self.logs[-40:],
        }

    def preview_pages(self) -> list[dict]:
        return self.previews

    def set_options(self, d: dict) -> None:
        self.options = LayoutOptions.from_dict({**self.options, **(d or {})}).to_dict()

    def export_pdf(self) -> str | None:
        return self.export_path


class Store:
    def __init__(self) -> None:
        self._d: dict[str, Task] = {}
        self._lock = threading.Lock()

    def create(self, tid: str, files: list[dict]) -> Task:
        t = Task(tid, files)
        with self._lock:
            self._d[tid] = t
        return t

    def get(self, tid: str) -> Task | None:
        with self._lock:
            return self._d.get(tid)

    def restart_layout(self, tid: str) -> None:
        t = self.get(tid)
        if not t or not t.parsed:
            return
        from .pipeline import relayout
        threading.Thread(target=relayout, args=(t,), daemon=True).start()

    def delete(self, tid: str) -> None:
        with self._lock:
            t = self._d.pop(tid, None)
        if t:
            shutil.rmtree(os.path.join(VAR, tid), ignore_errors=True)

    def __len__(self) -> int:
        return len(self._d)


STORE = Store()
