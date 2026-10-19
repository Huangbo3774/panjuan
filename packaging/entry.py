# -*- coding: utf-8 -*-
"""打包态入口：双击 exe = 起本机服务 + 自动开浏览器。

三条口径（和 scripts/start.ps1 完全一致，不能各说一套）：
  1) 已经在跑就不再起第二个 —— 重复启动会端口冲突、uvicorn 静默绑定失败，
     于是"你点的是新版、跑的是旧版"，这个坑在验收里踩过；
  2) 健康检查真的通了才开浏览器，不是"睡两秒就打开"那种假等待；
  3) 关掉这个黑框 = 停止服务（对家长来说这是唯一听得懂的"怎么关掉它"）。

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
    ap.add_argument("--status", action="store_true", help="只查在不在跑：RUNNING / STOPPED")
    a = ap.parse_args(argv)

    if a.status:
        h = who_is_on(a.port)
        print(f"RUNNING pid={h.get('pid')} frozen={h.get('frozen')}" if h else "STOPPED")
        return 0 if h else 2

    other = who_is_on(a.port) if port_busy(a.host, a.port) else None
    if other:
        # 幂等：再双击一次不该冒出第二个服务，也不该报错
        banner(a.port, "磐卷已经在跑了，不再起第二个")
        print(f"  正在跑的那个：pid={other.get('pid')} · "
              f"{'免安装版' if other.get('frozen') else '源码版'} · 数据目录 {other.get('home')}")
        print("  直接用它就行；要换成这一份，请先关掉另一个的窗口。")
        if not a.no_browser:
            webbrowser.open(f"http://127.0.0.1:{a.port}/")
        time.sleep(3.0)
        return 0

    if port_busy(a.host, a.port):
        print(f"\n✗ 端口 {a.port} 被【别的程序】占着（它不是磐卷，我们没敢把浏览器开过去）。")
        print("  换一个端口双击就行：  PaperForge.exe --port 8123")
        print("  或者找出那个程序关掉它：netstat -ano | findstr :8000")
        sys.stdout.flush()
        time.sleep(12.0)          # 别一闪而过，得让人看清这行字
        return 1

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
