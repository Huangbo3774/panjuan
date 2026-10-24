# -*- coding: utf-8 -*-
"""磐远试卷打印助手 · Qt 桌面壳（V1.4）——真桌面程序形态。

用户口径：双击 exe = 应用窗口。没有"启动服务"这一步（后端在同进程后台线程里，
端口随机、用完即弃），没有浏览器标签页，没有黑框；关窗 = 整体退出。

为什么是 Qt 壳 + 自带 Chromium（QWebEngineView）而不是 v1.3 的 pywebview/WebView2：
  · 拖拽：QWebEngineView 是原生控件，dropEvent 由我们截获 —— 文件从资源管理器
    拖进窗口真的能用（WebView2 出于安全不把文件对象给页面，做不到）；
  · 零依赖：Chromium 随包自带，不再要求系统装 WebView2 运行时（方法论铁律 4）；
  · PDF：QtWebEngine 内置 PDF 查看器，「打开并打印」在应用内新窗口完成。

大文件不走 base64：注册 pjfile:// 协议（白名单 token 制，只回放本次拖入的文件），
页面 fetch 成 Blob → File → 现成的 add()。50MB 的扫描件也不卡，
且页面拿不到任何本地路径读取能力（token 随进程退出失效）。

铁律 3（出错必被看见）：sys.excepthook + 页面 alert/confirm 全桥到原生框，
错误同时追加 exe 同目录 errors.log。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import urllib.request

APP_NAME = "磐远试卷打印助手"
APP_TITLE = APP_NAME + " · 老师发什么，磐远印什么"
ALLOWED = {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}

QT_OK = True
_QT_IMPORT_ERR = None
try:
    from PySide6.QtCore import Qt, QBuffer, QIODevice, QUrl, QByteArray
    from PySide6.QtGui import QIcon, QPixmap, QDesktopServices
    from PySide6.QtWidgets import (QApplication, QMainWindow, QMessageBox,
                                   QSplashScreen, QFileDialog)
    from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                         QWebEngineScript,
                                         QWebEngineUrlScheme,
                                         QWebEngineUrlSchemeHandler)
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception as e:                                # 缺 Qt 时由 entry 退回 pywebview/浏览器
    QT_OK = False
    _QT_IMPORT_ERR = repr(e)


def asset_dir() -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        for cand in (os.path.join(base, "packaging", "assets"),
                     os.path.join(base, "assets")):
            if os.path.isdir(cand):
                return cand
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "packaging", "assets")


def _home_for_log() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log_error(exc_type=None, exc=None, tb=None) -> None:
    try:
        text = ("".join(traceback.format_exception(exc_type, exc, tb))
                if exc is not None else "unknown")
        with open(os.path.join(_home_for_log(), "errors.log"), "a",
                  encoding="utf-8") as fh:
            fh.write(f"\n==== {time.strftime('%F %T')} ====\n{text}")
    except Exception:
        pass


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _ensure_std_streams() -> None:
    """冻结无控制台态 sys.stdout/stderr 可能是 None 或没有 isatty 的 NullWriter，
    uvicorn 的日志格式器一碰就炸（v1.4 首建实测）。桌面态日志本就没地方看：
    换上能 isatty() 的 devnull，服务线程先保住。"""
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is None or not hasattr(s, "isatty"):
            try:
                setattr(sys, name, open(os.devnull, "w"))
            except Exception:
                pass


def _mime(p: str) -> str:
    ext = os.path.splitext(p)[1].lower()
    return {".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument"
                     ".wordprocessingml.document",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".bmp": "image/bmp"}.get(
                ext, "application/octet-stream")


if QT_OK:

    class DropSchemeHandler(QWebEngineUrlSchemeHandler):
        """pjfile://drop/<token> → 只回放本次拖入白名单里的文件字节。"""

        def __init__(self, app_ref):
            super().__init__()
            self.app_ref = app_ref

        def requestStarted(self, request):
            token = request.requestUrl().path().rstrip("/").rsplit("/", 1)[-1]
            info = self.app_ref.drop_tokens.get(token)
            if not info:
                request.abort(404)
                return
            try:
                with open(info["path"], "rb") as fh:
                    data = fh.read()
            except Exception as e:
                log_error(type(e), e, e.__traceback__)
                request.abort(400)
                return
            buf = QBuffer()
            buf.setData(QByteArray(data))
            buf.open(QIODevice.ReadOnly)
            request.reply(200, QByteArray(b"OK"),
                          {b"Access-Control-Allow-Origin": b"*",
                           b"Content-Type": info["mime"].encode()},
                          buf)

    class Page(QWebEnginePage):
        app_ref = None

        def javaScriptAlert(self, sec_origin, msg):
            QMessageBox.warning(self.view_widget(), APP_TITLE, msg)

        def javaScriptConfirm(self, sec_origin, msg):
            box = QMessageBox(self.view_widget())
            box.setWindowTitle(APP_TITLE)
            box.setText(msg)
            yes = box.addButton("确定", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            return box.clickedButton() is yes

        def view_widget(self):
            w = self.parent()
            return w if isinstance(w, QWebEngineView) else None

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            # 外部链接交给系统浏览器；壳内只跑本机应用
            s = url.toString()
            if url.scheme() in ("http", "https") and f":{self.app_ref.port}" not in s:
                QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def createWindow(self, wtype):
            # window.open('_blank') → 应用内新窗口（「打开 PDF 并打印」走这里）
            return self.app_ref.make_popup()

    class View(QWebEngineView):
        def __init__(self, app_ref, popup=False):
            super().__init__()
            self.app_ref = app_ref
            self.popup = popup
            self.setAcceptDrops(True)
            page = Page(self)
            page.app_ref = app_ref
            self.setPage(page)

        def dragEnterEvent(self, ev):
            if ev.mimeData().hasUrls():
                ev.acceptProposedAction()

        def dragMoveEvent(self, ev):
            if ev.mimeData().hasUrls():
                ev.acceptProposedAction()

        def dropEvent(self, ev):
            if not ev.mimeData().hasUrls():
                return
            ev.acceptProposedAction()
            self.app_ref.handle_drop([u.toLocalFile()
                                      for u in ev.mimeData().urls()])

    class Shell(QMainWindow):
        def __init__(self, app_ref):
            super().__init__()
            self.app_ref = app_ref
            self.setWindowTitle(APP_TITLE)
            icon = os.path.join(asset_dir(), "icon_128.png")
            if os.path.isfile(icon):
                self.setWindowIcon(QIcon(icon))
            self.resize(1240, 860)
            self.view = View(app_ref)
            self.setCentralWidget(self.view)
            app_ref.main_view = self.view
            self.view.loadFinished.connect(app_ref.on_loaded)
            self.view.load(QUrl(app_ref.url))


class App:
    def __init__(self, port: int):
        self.port = port
        self.url = f"http://127.0.0.1:{port}/"
        self.drop_tokens = {}
        self._token_seq = 0
        self.main_view = None
        self.popups = []
        self.profile = None

    # ── 拖放桥 ─────────────────────────────────────────────
    def handle_drop(self, paths):
        files = [p for p in paths
                 if os.path.isfile(p)
                 and os.path.splitext(p)[1].lower() in ALLOWED]
        skipped = len(paths) - len(files)
        if not files:
            self.notify(f"这些文件不收（支持 PDF/图片/Word，跳过 {skipped} 个）")
            return
        if skipped:
            self.notify(f"跳过 {skipped} 个不支持的文件")
        js = []
        for p in files:
            self._token_seq += 1
            tok = f"t{self._token_seq}"
            mime = _mime(p)
            self.drop_tokens[tok] = {"path": p, "mime": mime}
            name = os.path.basename(p).replace("\\", "\\\\").replace("'", "\\'")
            js.append(
                "fetch('pjfile://drop/%s').then(r=>r.blob()).then(b=>window.add("
                "[new File([b],'%s',{type:'%s'})]))" % (tok, name, mime))
        code = ("typeof window.add==='function' && (" + ";".join(js) + ")")

        def cb(val):
            if val is False:
                self.notify("文件请拖到第 1 步「上传」页（这一页没有投放区）")
        self.run_js(code, cb)

    def notify(self, text):
        safe = text.replace("\\", "\\\\").replace("'", "\\'")
        self.run_js(f"window.__pjToast ? window.__pjToast('{safe}') : false",
                    lambda r: None if r is not False
                    else QMessageBox.information(None, APP_TITLE, text))

    def run_js(self, code, cb=None):
        v = self.main_view
        if v is None:
            return
        if cb is None:
            v.page().runJavaScript(code)
        else:
            v.page().runJavaScript(code, cb)

    def make_popup(self):
        dlg = View(self, popup=True)
        dlg.setWindowTitle(APP_NAME + " · PDF")
        dlg.resize(1000, 800)
        self.popups.append(dlg)
        dlg.show()
        return dlg.page()

    def on_loaded(self, ok):
        pass

    # ── 服务 ───────────────────────────────────────────────
    def _start_server(self):
        try:
            _ensure_std_streams()
            import uvicorn
            from app.main import app
            # log_config=None：冻结无控制台态 sys.stderr 可能是 None，
            # uvicorn 默认日志格式器会 sys.stderr.isatty() 直接炸服务线程
            #（v1.4 首建实测：health 永不应答，errors.log 抓到现形）。
            cfg = uvicorn.Config(app, host="127.0.0.1",
                                 port=self.port, log_level="warning",
                                 log_config=None)
            uvicorn.Server(cfg).run()
        except BaseException as e:                    # 线程里的死也要被看见（铁律 3）
            log_error(type(e), e, e.__traceback__)
            raise

    # ── 主流程 ─────────────────────────────────────────────
    def run(self) -> int:
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName(APP_NAME)

        def hook(t, e, tb):
            log_error(t, e, tb)
            if threading.current_thread() is threading.main_thread():
                try:
                    QMessageBox.critical(None, APP_TITLE,
                                         f"出了点问题，详情已写入 errors.log：\n\n{e}")
                except Exception:
                    pass
        sys.excepthook = hook

        # pjfile:// 白名单协议（拖放大文件通道）
        # ⚠️ 枚举名按 PySide6 6.12 实测：Syntax 没有 HostAndPath（那是文档旧图），
        #    Flag 里放行 fetch 的叫 FetchApiAllowed，没有 SupportFetch。写错＝启动即崩，
        #    第一次冒烟就是被 errors.log 抓到才定位到的（铁律 3 生效实录）。
        scheme = QWebEngineUrlScheme(b"pjfile")
        scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
        flags = QWebEngineUrlScheme.Flag.SecureScheme
        for extra in ("FetchApiAllowed", "CorsEnabled"):
            f = getattr(QWebEngineUrlScheme.Flag, extra, None)
            if f is not None:
                flags |= f
        scheme.setFlags(flags)
        QWebEngineUrlScheme.registerScheme(scheme)

        self.profile = QWebEngineProfile.defaultProfile()
        self.profile.setHttpUserAgent("PanJuanDesktop/1.4 local-first")
        self.profile.installUrlSchemeHandler(b"pjfile", DropSchemeHandler(self))

        # 桌面标记：desktop.js 靠 __PANJUAN_QT__ 调整文案（先插脚本再建窗口）
        # ⚠️ PySide6 6.12 实测 API：setSourceCode（不是 setSourceString）、
        #    setWorldId(ScriptWorldId.MainWorld)（不是 setWorld(...ScriptWorld.MainWorld)）
        mark = QWebEngineScript()
        mark.setName("panjuan-desktop")
        mark.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        mark.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        mark.setSourceCode("window.__PANJUAN_QT__=true;")
        self.profile.scripts().insert(mark)

        # 下载 → 系统「另存为」
        # ⚠️ PySide6 6.12：QWebEngineDownloadItem 改名 QWebEngineDownloadRequest，
        #    setPath 拆成 setDownloadDirectory + setDownloadFileName。
        def on_download(item):
            suggested = os.path.basename(item.suggestedFileName()
                                         or "panjuan.pdf")
            default = os.path.join(os.path.expanduser("~"), "Downloads", suggested)
            path, _ = QFileDialog.getSaveFileName(
                self.main_view, "保存文件", default, "所有文件 (*.*)")
            if path:
                item.setDownloadDirectory(os.path.dirname(path))
                item.setDownloadFileName(os.path.basename(path))
                item.accept()
            else:
                item.cancel()
        self.profile.downloadRequested.connect(on_download)

        # 启动画面：服务与 OCR 模型加载期间有交代（UX 军规）
        splash = None
        sp = os.path.join(asset_dir(), "splash_1440x1080.png")
        if os.path.isfile(sp):
            pm = QPixmap(sp).scaledToWidth(560, Qt.SmoothTransformation)
            splash = QSplashScreen(pm, Qt.WindowStaysOnTopHint)
            splash.show()
            splash.showMessage("正在启动本机服务与 OCR 引擎…",
                               Qt.AlignBottom | Qt.AlignHCenter)
            app.processEvents()

        threading.Thread(target=self._start_server, daemon=True).start()
        deadline = time.time() + 180
        up = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.url + "api/health", timeout=1) as r:
                    if r.status == 200:
                        up = True
                        break
            except Exception:
                time.sleep(0.4)
            app.processEvents()
        if not up:
            QMessageBox.critical(None, APP_TITLE,
                                 "本机服务 3 分钟没起来，请重启一次；\n详情见 errors.log。")
            return 1

        win = Shell(self)
        win.show()
        if splash is not None:
            splash.finish(win)

        app.exec()
        os._exit(0)      # 关窗 = 全退：daemon 服务线程一并带走，不留占端口的孤儿


def run(port: int | None = None) -> int:
    """入口：port=None 用随机端口（用户永远看不见）。Qt 不可用时返回 3 由调用方降级。"""
    if not QT_OK:
        print(f"⚠ Qt 桌面壳不可用（{_QT_IMPORT_ERR}），退回其它模式")
        return 3
    return App(port or free_port()).run()
