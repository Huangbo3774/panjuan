"""把 .ps1 转成 UTF-8 with BOM。

原因：Windows PowerShell 5.1 读 .ps1 时，若文件没有 UTF-8 BOM，会按系统 ANSI（中文机 = GBK）
解码，中文注释/字符串会变成乱码，甚至吃掉引号导致「字符串缺少终止符」「Try 语句缺少 Catch」
这类假语法错误。带 BOM 才会被正确识别为 UTF-8。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOM = b"\xef\xbb\xbf"
try:                       # Windows 控制台默认 GBK，✗ 会抛 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

args = sys.argv[1:]
check_only = "--check" in args
args = [a for a in args if not a.startswith("--")]
# ⚠️ 只在【没给参数】时用默认清单。上一版写成 `sys.argv[1:] or [...]`，
#    于是 `--check` 本身被当成文件列表、过滤后变成空表，
#    闸门扫了 0 个文件却报"0 个缺 BOM"——假绿（计数 0 有两种含义：全过 / 尺坏了）。
DEFAULT_PS1 = ["scripts/setup.ps1", "scripts/go_online.ps1"]
targets = args or [p for p in DEFAULT_PS1 if os.path.exists(os.path.join(ROOT, p))]
if not targets:
    print("✗ 没有任何 .ps1 可检查，闸门拒绝以'通过'收场")
    sys.exit(1)
changed = 0
missing = []
for rel in targets:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        print("跳过（不存在）", rel)
        continue
    with open(p, "rb") as fh:
        b = fh.read()
    if b.startswith(BOM):
        print(f"  已有 BOM  {rel}")
        continue
    if check_only:
        missing.append(rel)
        print(f"  ✗ 缺 BOM  {rel}  （中文 Windows 上会被按 GBK 解码 → 假语法错误）")
        continue
    with open(p, "wb") as fh:
        fh.write(BOM + b)
    changed += 1
    print(f"  已加 BOM  {rel}")
if check_only:
    print(f"\n检查完成：{len(missing)} 个 .ps1 缺 BOM")
    sys.exit(1 if missing else 0)
print(f"共修改 {changed} 个文件")
