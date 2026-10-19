# -*- mode: python ; coding: utf-8 -*-
"""磐卷 PaperForge · PyInstaller 打包配置（onedir）

为什么 onedir 不用 onefile：onefile 每次启动都要把整个归档解到 %TEMP%（我们这套
含 OpenCV + onnxruntime + OCR 模型，解压要几十秒，而且解出来的目录会被杀软盯上），
onedir 是"解压一次、以后直接跑"，双击秒开。代价是产物是一个文件夹而不是单个 exe
—— 反正我们发的是 zip，用户本来就是解压使用。

三个必须显式处理的地方，漏一个就是"能启动但功能静默坏掉"：
  1) web/ 前端目录：作为数据打进去（app/paths.py 在冻结态从 sys._MEIPASS 读它）；
  2) rapidocr_onnxruntime 的模型文件：collect_all 才会把 .onnx / 配置一起收走，
     漏了不报错，只是扫描版试卷【一道题都认不出来】——最难查的那种坏法；
  3) uvicorn 的 loops/protocols 是字符串动态导入的，不写 hiddenimports 就会
     在打包后第一次接受请求时 ImportError。
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

# SPECPATH 由 PyInstaller 注入 = 本文件所在目录（packaging/）
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "web"), "web")]
binaries = []
hiddenimports = [
    # uvicorn 内部按字符串挑实现，静态分析看不见
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.auto", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    # 我们代码里是函数内 import，静态分析同样容易漏
    "pymupdf", "fitz", "docx", "reportlab", "reportlab.pdfbase.ttfonts",
    "reportlab.pdfbase.cidfonts", "reportlab.lib.utils",
    "fastapi", "starlette", "multipart", "python_multipart",
    "sqlite3", "numpy", "cv2", "PIL", "onnxruntime",
    "anyio", "anyio._backends._asyncio", "h11", "sniffio", "idna",
]

# OCR：模型与配置都在包里，必须整包收走（漏了不报错，只是扫描卷认不出题）
for pkg in ("rapidocr_onnxruntime",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 原生 DLL：pymupdf(mupdf) / onnxruntime 的加载在部分环境里靠钩子不够，显式收一遍
for pkg in ("pymupdf", "onnxruntime", "cv2"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception as e:
        print(f"[spec] collect_dynamic_libs({pkg}) 跳过：{e}")

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # 这台机的全局 Python 里躺着 1.8GB 无关包（polars/playwright/gradio/streamlit…），
    # 就算在干净 venv 里构建，也把这些显式排除，防止哪天被间接拽进来把包撑爆。
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2", "PySide6", "IPython",
              "notebook", "streamlit", "gradio", "pandas", "scipy", "sklearn",
              "playwright", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir：DLL 与数据放 _internal，不塞进 exe
    name="PaperForge",
    debug=False,
    strip=False,
    upx=False,                      # UPX 压过的 exe 是杀软误报的头号来源，公开下载别用
    console=True,                   # 留一个窗口：那就是服务本身，关掉=停止
    # icon=os.path.join(ROOT, "packaging", "paperforge.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PaperForge",
)
