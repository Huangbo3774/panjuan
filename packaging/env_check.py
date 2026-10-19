# -*- coding: utf-8 -*-
"""打包前的环境体检：解释器、依赖是否齐、PyInstaller 在不在、各包多大。"""
import importlib.util as u
import os
import sys

MODS = ["fastapi", "uvicorn", "fitz", "pymupdf", "docx", "cv2", "numpy", "reportlab",
        "onnxruntime", "rapidocr_onnxruntime", "pyinstaller", "PIL", "sqlite3"]
print("exe:", sys.executable, "ver:", sys.version.split()[0])
for m in MODS:
    try:
        s = u.find_spec(m)
    except Exception as e:
        s = None
        print(f"  {m:22s} 探测异常 {type(e).__name__}: {e}")
        continue
    if not s:
        print(f"  {m:22s} MISSING")
    else:
        where = (s.origin or "(内置)")
        print(f"  {m:22s} OK   {where[-70:]}")

SP = os.path.dirname(os.path.dirname(sys.executable)) if hasattr(sys, "frozen") else \
    os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages")
if os.path.isdir(SP):
    tot = 0
    rows = []
    for name in sorted(os.listdir(SP)):
        p = os.path.join(SP, name)
        if not os.path.isdir(p) or name.endswith((".dist-info", ".egg-info")):
            continue
        n = 0
        for root, _, files in os.walk(p):
            for f in files:
                try:
                    n += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        if n > 3_000_000:
            rows.append((n, name))
    for n, name in sorted(rows, reverse=True):
        print(f"  {name:28s} {n / 1048576:6.1f} MB")
        tot += n
    print(f"  {'合计(>3MB 的包)':28s} {tot / 1048576:6.1f} MB")
