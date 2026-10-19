# -*- coding: utf-8 -*-
"""路径的唯一来源（开发态与打包态都走这里）。

为什么要有这个文件：原来 main.py / api/store.py / storage/db.py 各自写了一遍
`dirname(dirname(abspath(__file__)))`「往上三层找仓库根」，四份同义重复。
打包成 exe 之后 `__file__` 会指到 PyInstaller 的解包目录（只读、每次启动换地方、
而且随版本被替换），那四行会一起算错 —— 孩子的作答库会莫名其妙出现在临时目录里。
所以路径只在这里算一次，其余模块引用它。

三种目录，职责不同，别混：
  * BUNDLE  只读资源（web/ 前端、随包的模型）——打包态在 sys._MEIPASS 下
  * APP_HOME 数据根（data/ 试卷库与配图、var/ 临时工作目录）——必须在【可写】位置，
            且升级程序时不能被覆盖
  * 两者在开发态都等于仓库根，所以现有测试与脚本的行为逐字不变
"""
from __future__ import annotations

import os
import sys
import tempfile

FROZEN = bool(getattr(sys, "frozen", False))

# 只读资源根：打包态 = PyInstaller 解出来的临时目录；开发态 = app/ 的上一层（仓库根）
BUNDLE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exe_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.executable))


def _writable(d: str) -> bool:
    """能不能在这儿建目录、写文件、删掉它（一次实测，不猜）。"""
    probe = os.path.join(d, ".pj_write_probe")
    try:
        os.makedirs(d, exist_ok=True)
        with open(probe, "wb") as fh:
            fh.write(b"x")
        os.unlink(probe)
        return True
    except OSError:
        return False


def _resolve_home() -> tuple[str, str]:
    """数据根目录 + 一句话说明（这句话会打进启动横幅，不能省）。

    打包态下按这个顺序挑，第一个能写的就用：
      1) exe 所在目录            —— 正常情况：解压到桌面/D 盘，数据就在旁边，看得见摸得着
      2) 用户目录下的 PaperForge —— Program Files 等只读位置，或权限受限
      3) %LOCALAPPDATA%\\PaperForge —— 最后的兜底
    另外单独处理一个真实坑：用户【在压缩包里直接双击 exe】时，Windows 会把它
    解到 %TEMP% 下运行 —— 那样写出来的试卷库在临时目录里，重启电脑就没了。
    这种情况不硬拦（拦不住），但要把数据改放到稳定位置并在横幅里说清楚。
    """
    if not FROZEN:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return root, "开发态：仓库根"

    exe = _exe_dir()
    tmp = os.path.normcase(tempfile.gettempdir())
    if not os.path.normcase(exe).startswith(tmp):
        if _writable(exe):
            return exe, "数据放在程序旁边"
    else:
        # 从压缩包里直接双击：exe 在 %TEMP%，别把孩子的作业写进临时目录
        pass

    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    for cand, why in ((os.path.join(local, "PaperForge"), "程序目录不可写或在压缩包里直接运行，"
                                                      "数据改放用户目录"),
                      (os.path.join(os.path.expanduser("~"), "PaperForge"), "用户目录兜底")):
        if _writable(cand):
            return cand, why
    return exe, "找不到可写位置，仍用程序目录（保存数据会失败）"


APP_HOME, HOME_NOTE = _resolve_home()

# 数据根可以单独挪走（只挪 var/ 与 data/，web/ 仍然跟着代码走）。
# 为什么要有它：验收测试以前直接写进用户的真库 data/papers.db，
# 每跑一次就多留几份假卷（实测库里 57 份、其中 46 份是测试垃圾，首页被挤满）。
# 测试跑之前设 PJ_DATA_HOME=一个临时目录即可，产品行为不受任何影响。
DATA_HOME = os.environ.get("PJ_DATA_HOME") or APP_HOME

WEB = os.path.join(BUNDLE, "web") if FROZEN else os.path.join(APP_HOME, "web")
VAR = os.path.join(DATA_HOME, "var")          # 临时工作目录：服务启动即清空
DATA = os.path.join(DATA_HOME, "data")        # 试卷库 / 题目配图：跟着版本走，绝不清空
DB_PATH = os.path.join(DATA, "papers.db")

# 代码指纹：/api/health 会报，用来确认"答我的是哪一版代码"。
# 冻结态源码不在盘上 → 取 exe 的 mtime；开发态取 app/ 下最新的 .py 修改时间。
# （以前只取 main.py 自己，于是改了 lines.py/figures.py 而 build 数字不动，
#   排查时误以为"跑的是旧进程"，白绕了一圈。）
def _build_stamp() -> float:
    if FROZEN:
        return os.path.getmtime(sys.executable)
    newest = os.path.getmtime(os.path.abspath(__file__))
    base = os.path.dirname(os.path.abspath(__file__))
    for root, _dirs, files in os.walk(base):
        for fn in files:
            if fn.endswith(".py"):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, fn)))
                except OSError:
                    pass
    return newest


BUILD_STAMP = _build_stamp()

__all__ = ["FROZEN", "BUNDLE", "APP_HOME", "HOME_NOTE", "WEB", "VAR", "DATA",
           "DB_PATH", "BUILD_STAMP"]
