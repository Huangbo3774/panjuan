# -*- coding: utf-8 -*-
"""打包态入口：双击 exe = 起本机服务 + 开原生桌面窗口（V1.3 起）。

形态口径（v1.3 变更）：
  · 打包态默认【桌面窗口】：pywebview + 系统 WebView2，关窗即退出（run_window）；
  · `--browser` 回到 v1.2 老行为（起服务 + 开系统浏览器，含横幅控制台逻辑）；
  · 源码态默认仍是浏览器 —— 开发要的就是浏览器里的真页面，`--window` 可显式开窗口。

三条不变的服务口径（和 scripts/start.ps1 完全一致，不能各说一套）：
  1) 已经在跑就不再起第二个 —— 重复启动会端口冲突、uvicorn 静默绑定失败，
     于是"你点的是新版、跑的是旧版"，这个坑在验收里踩过；
  2) 健康检查真的通了才开窗口/浏览器，不是"睡两秒就打开"那种假等待；
  3) 窗口版关窗 = 停止服务；浏览器版关掉黑框 = 停止服务。

冻结态不能用 `uvicorn.run("app.main:app")` 那个导入字符串：exe 里没有可以被
字符串路径 import 的 app.main（源码在 PyInstaller 归档里），必须把模块对象传进去。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

# 横幅里有 ✗ ✓ · 这类字符。Python 只有在"stdout 真的连着控制台"时才自动走 UTF-8；
# 一旦输出被重定向（管道、>> 日志、被别的脚本调起），它就退回系统 ANSI 代码页（中文机=cp936），
# 于是 print('✗') 直接 UnicodeEncodeError 把启动流程砸断 —— 实测就是这样崩的。
# 这里显式钉成 UTF-8 + 兜底替换：宁可显示成 ? 也不能让启动信息打不出来。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 从源码直接跑这个文件时（py -3.11 packaging/entry.py），sys.path[0] 是 packaging/，
# import app.* 会找不到 —— 冻结态由 PyInstaller 解决，开发态得自己补上仓库根。
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def port_busy(host: str, port: int) -> bool:
    """端口上有没有人在听 —— 有就说明服务已经在跑（可能就是我们自己上一次的窗口）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def wait_health(port: int, timeout: float = 120.0) -> dict | None:
    """轮询 /api/health 直到通；返回解析后的 json，超时给 None。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
                if r.status == 200:
                    return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(0.4)
    return None


def open_when_ready(port: int) -> None:
    h = wait_health(port)
    if h:
        webbrowser.open(f"http://127.0.0.1:{port}/")


def alert(title: str, msg: str) -> None:
    """给用户看的一行字：有控制台就 print，窗口版（无控制台）弹系统消息框。"""
    print(f"{title}\n{msg}")
    try:
        sys.stdout.flush()
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, title, 0x10)  # MB_ICONSTOP
        except Exception:
            pass


def start_server_thread(app, host: str, port: int):
    """后台线程里跑 uvicorn（桌面窗口模式用：主线程必须留给 GUI 消息循环）。

    返回 Server 对象：调用方想干净停服可以用 .should_exit=True，
    但窗口模式下我们直接随进程退出（线程是 daemon），关窗 = 关程序。"""
    import uvicorn
    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    return srv


def run_window(port: int, host: str, url: str, own_server: bool = True) -> int:
    """桌面窗口模式：原生窗口内嵌本机页面（Windows 用系统 WebView2，Win11 自带）。

    与浏览器模式的三条差异（口径写进使用说明）：
      1) 关窗口 = 退出程序（不再有"黑框 = 服务"的心智负担）；
      2) 导出 PDF 走系统"另存为"对话框（pywebview 默认取消一切下载，必须显式放行）；
      3) 从资源管理器往页面里拖文件在 WebView2 下拿不到文件对象，用「选择文件」按钮。
    WebView2 初始化失败（老 Win10 缺运行时）时退回系统浏览器，服务照常可用。"""
    try:
        import webview
    except Exception as e:
        alert("磐卷 PaperForge 打不开",
              f"桌面窗口模式需要 pywebview，导入失败：{e!r}\n\n"
              f"先用浏览器模式顶上：  PaperForge.exe --browser")
        return 3
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True   # 放行导出下载（见上）
    except Exception:
        pass

    if own_server:
        from app.main import app
        start_server_thread(app, host, port)
    if not wait_health(port):
        alert("磐卷 PaperForge 打不开", "服务超时没起来，窗口不开。重启电脑后再试一次。")
        return 1
    win = webview.create_window(
        "磐卷 PaperForge · 老师发什么，磐卷印什么",
        url, width=1240, height=860, min_size=(920, 620), text_select=True)
    try:
        webview.start(gui="edgechromium", debug=False)   # 阻塞到窗口关闭
    except Exception as e:
        print(f"⚠ 原生窗口起不来（{e!r}），退回系统浏览器，服务照常")
        webbrowser.open(url)
        threading.Event().wait()                          # 保持服务活着
    os._exit(0)   # 窗口关了就直接退：daemon 服务线程跟着走，不留孤儿进程占端口


def banner(port: int, first_line: str = "磐卷 PaperForge 正在启动") -> None:
    from app.paths import APP_HOME, DATA, FROZEN, HOME_NOTE, VAR
    print("")
    print("  " + "=" * 62)
    print(f"  {first_line}")
    print("  " + "=" * 62)
    print(f"  页面地址   http://127.0.0.1:{port}/   （浏览器马上会自动打开）")
    print(f"  程序位置   {os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))}")
    print(f"  数据存放   {DATA}      ← 试卷、题目、标准答案、作答记录")
    print(f"  临时文件   {VAR}       ← 每次启动清空，不含孩子的作业")
    print(f"  位置说明   {HOME_NOTE}")
    print("")
    print("  这个窗口就是服务本身：【关掉它 = 停止磐卷】，不影响已经存好的试卷。")
    print("  全程只在本机运行，不连外网；代码开源在 GitHub，欢迎审查。")
    print("")
    sys.stdout.flush()


def who_is_on(port: int) -> dict | None:
    """端口上那个进程【自报】是不是磐卷；不是（或答不上来）返回 None。

    为什么必须问一句而不是只看端口通不通：家长机器上 8000 端口很可能被
    打印机驱动、NAS 控制台、别的开发服务占着。只看"端口有人听"就说"磐卷已经在跑"
    并把浏览器开过去，用户看到的是别人的页面，只会以为我们的程序坏了。
    """
    try:
        # 3 秒：本机健康检查正常是毫秒级，但别因为一次卡顿就把磐卷自己误判成"陌生程序"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3.0) as r:
            j = json.loads(r.read().decode("utf-8"))
        return j if j.get("service") == "paper-forge" else None
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="PaperForge", description="磐卷 PaperForge 本机服务")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PJ_PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true", help="只起服务，不开浏览器")
    ap.add_argument("--window", action="store_true", help="桌面窗口模式（打包 exe 的默认行为）")
    ap.add_argument("--browser", action="store_true", help="强制浏览器模式（v1.2 之前的老行为）")
    ap.add_argument("--status", action="store_true", help="只查在不在跑：RUNNING / STOPPED")
    a = ap.parse_args(argv)

    if a.status:
        h = who_is_on(a.port)
        print(f"RUNNING pid={h.get('pid')} frozen={h.get('frozen')}" if h else "STOPPED")
        return 0 if h else 2

    # 打包 exe 默认走原生窗口（双击=开程序，关窗=退出）；源码态默认浏览器，
    # 因为开发时大家就是想看浏览器里的真页面。--browser / --window 显式覆盖。
    use_window = (a.window or getattr(sys, "frozen", False)) and not a.browser
    url = f"http://127.0.0.1:{a.port}/"

    other = who_is_on(a.port) if port_busy(a.host, a.port) else None
    if other:
        # 幂等：再双击一次不该冒出第二个服务，也不该报错
        if use_window:
            # 已有服务在跑：开一个窗口直接指过去，不再起第二个
            return run_window(a.port, a.host, url, own_server=False)
        banner(a.port, "磐卷已经在跑了，不再起第二个")
        print(f"  正在跑的那个：pid={other.get('pid')} · "
              f"{'免安装版' if other.get('frozen') else '源码版'} · 数据目录 {other.get('home')}")
        print("  直接用它就行；要换成这一份，请先关掉另一个的窗口。")
        if not a.no_browser:
            webbrowser.open(f"http://127.0.0.1:{a.port}/")
        time.sleep(3.0)
        return 0

    if port_busy(a.host, a.port):
        msg = (f"端口 {a.port} 被【别的程序】占着（它不是磐卷）。\n\n"
               f"换一个端口双击即可：  PaperForge.exe --port 8123\n"
               f"或找出占端口的程序关掉：  netstat -ano | findstr :{a.port}")
        if use_window:
            alert("磐卷 PaperForge 打不开", msg)   # 窗口版没有黑框，print 没人看得见
            return 1
        print(f"\n✗ 端口 {a.port} 被【别的程序】占着（它不是磐卷，我们没敢把浏览器开过去）。")
        print("  换一个端口双击就行：  PaperForge.exe --port 8123")
        print("  或者找出那个程序关掉它：netstat -ano | findstr :8000")
        sys.stdout.flush()
        time.sleep(12.0)          # 别一闪而过，得让人看清这行字
        return 1

    if use_window:
        return run_window(a.port, a.host, url)

    banner(a.port)
    from app.main import app                      # 放在横幅之后：导入要装字体、建库，慢半拍
    from app.paths import DATA
    import uvicorn

    if not a.no_browser:
        threading.Thread(target=open_when_ready, args=(a.port,), daemon=True).start()
    try:
        # 传对象而不是 "app.main:app" 字符串：冻结态没有可字符串导入的模块
        uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    except KeyboardInterrupt:
        pass
    print(f"\n  已停止。数据都还在：{os.path.join(DATA, 'papers.db')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
