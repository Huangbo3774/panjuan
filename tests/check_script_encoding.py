"""脚本编码门禁：.ps1 必须带 UTF-8 BOM，.bat 必须是纯 ASCII（并统一 CRLF 行尾）。

为什么 .bat 要禁中文：Windows 的 cmd 用**系统 ANSI 代码页**（简体中文=GBK，欧美=CP1252）
读 .bat，而不是 UTF-8。UTF-8 存的中文在 cmd 里会被解成乱码字节，那些乱码里只要出现
`&`/空格/引号，整行命令就被切碎——实测本项目的 scripts/check.bat 变成
`'t.py' 不是内部或外部命令`，一个中文 Windows 用户双击就跑不起来。
.ps1 反过来：PowerShell 5.1 只认 BOM 来判 UTF-8，所以必须带 BOM。

关于行尾（口径写清楚，别把约定说成实测缺陷）：
  · .ps1 纯 LF + BOM + 中文注释 → 本机 PowerShell 5.1 实测 rc=0、两条 Write-Host 都执行，
    所以这里【不】卡 .ps1 行尾。
  · .bat 纯 LF + 顶层 `goto :fail` → 本机 cmd 实测也能跑，所以卡 CRLF 是「Windows 脚本惯例」
    而不是已复现的故障；保留是因为 cmd 在括号块/标签上的行尾行为历来不稳，而成本为零。
"""
from __future__ import annotations

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _ctrl(raw: bytes) -> list[int]:
    """除 \\t \\r \\n 之外的控制字符。

    真实事故：用 heredoc 往 check.bat 里插一行 `py -3.11 tests\\break_webgate.py`，
    跨 shell 传递时 `\\b` 被解释成退格符 0x08，落盘变成 `tests<BS>reak_webgate.py`。
    0x08 是 ASCII，"纯 ASCII"那条检查照样放行，直到 cmd 找不到文件才暴露。
    """
    return [i for i, b in enumerate(raw) if b < 32 and b not in (9, 10, 13)]


_CTRL_NAMES = {8: "BS(退格)", 0: "NUL", 7: "BEL", 12: "FF", 27: "ESC"}


def _ctrl_name(raw: bytes, pos: int) -> str:
    """_ctrl 返回的是【位置】，名字要拿那个位置上的字节去查 —— 直接拿位置查表会印出 0x617 这种没意义的东西。"""
    b = raw[pos]
    return f"{_CTRL_NAMES.get(b, hex(b))}@{pos}"


def check() -> list[str]:
    bad: list[str] = []
    for p in sorted(glob.glob(os.path.join(ROOT, "scripts", "*.ps1"))):
        raw = open(p, "rb").read()
        if not raw.startswith(b"\xef\xbb\xbf"):
            bad.append(f"{os.path.basename(p)}: .ps1 缺 UTF-8 BOM（PS5.1 会按 GBK 解码→语法错误）")
        # 行尾不要求 CRLF：PowerShell 5.1 跑「带 BOM 的 UTF-8 + 纯 LF + 中文注释」脚本
        # 实测 rc=0 且两条 Write-Host 都执行（本机 PS 5.1.19041），所以只卡 BOM 这一条。
        # 只有 .bat 才同时卡行尾：cmd 的标签/goto 在 LF 下会出问题。
    # .bat 不止在 scripts/ 下：根目录的 start.bat / stop.bat 才是用户真正双击的那个，
    # 只扫 scripts/ 等于给最关键的入口留了缺口。
    bat_globs = [os.path.join(ROOT, "scripts", "*.bat"), os.path.join(ROOT, "*.bat")]
    for g in bat_globs:
        for p in sorted(glob.glob(g)):
            raw = open(p, "rb").read()
            rel = os.path.relpath(p, ROOT)
            nonascii = [i for i, b in enumerate(raw) if b > 0x7F]
            if nonascii:
                sample = raw[max(0, nonascii[0] - 30):nonascii[0] + 10]
                bad.append(f"{rel}: .bat 含 {len(nonascii)} 个非 ASCII 字节"
                           f"（cmd 按 GBK 解码会把命令行切碎）偏移 {nonascii[:5]} 附近={sample!r}")
            if b"\r\n" not in raw[:400]:
                bad.append(f"{rel}: .bat 不是 CRLF 行尾")
            c = _ctrl(raw)
            if c:
                bad.append(f"{rel}: .bat 含 {len(c)} 个控制字符 {[_ctrl_name(raw, i) for i in c[:5]]}"
                           f"（位置 {c[:5]}），cmd 会把路径/命令切坏")
    # .vbs 与 .bat 同理：WSH 用系统 ANSI 代码页读 .vbs，所以只允许纯 ASCII。
    # start_hidden.vbs 是 panjuan:// 协议真正执行的那一条，它挂了就等于按钮失灵。
    for p in sorted(glob.glob(os.path.join(ROOT, "scripts", "*.vbs"))):
        raw = open(p, "rb").read()
        rel = os.path.relpath(p, ROOT)
        nonascii = [i for i, b in enumerate(raw) if b > 0x7F]
        if nonascii:
            bad.append(f"{rel}: .vbs 含 {len(nonascii)} 个非 ASCII 字节"
                       "（WSH 按 GBK 解码，注释里的中文会变乱码字节）")
        if b"\r\n" not in raw[:400]:
            bad.append(f"{rel}: .vbs 不是 CRLF 行尾")
        c = _ctrl(raw)
        if c:
            bad.append(f"{rel}: .vbs 含 {len(c)} 个控制字符 {[_ctrl_name(raw, i) for i in c[:5]]}"
                       f"（位置 {c[:5]}）")
    # .ps1 也一样：PowerShell 对 NUL/退格这类字节的容忍度取决于版本与宿主控制台，
    # 而且它们几乎只可能来自"跨 shell 写文件时把转义序列坐实了"这一种错误。
    for p in sorted(glob.glob(os.path.join(ROOT, "scripts", "*.ps1"))):
        raw = open(p, "rb").read()
        c = _ctrl(raw)
        if c:
            bad.append(f"{os.path.basename(p)}: .ps1 含 {len(c)} 个控制字符"
                       f" {[_ctrl_name(raw, i) for i in c[:5]]}（位置 {c[:5]}）")
    return bad


def main() -> int:
    bad = check()
    n_ps1 = len(glob.glob(os.path.join(ROOT, "scripts", "*.ps1")))
    n_bat = sum(len(glob.glob(g)) for g in (os.path.join(ROOT, "scripts", "*.bat"), os.path.join(ROOT, "*.bat")))
    n_vbs = len(glob.glob(os.path.join(ROOT, "scripts", "*.vbs")))
    if bad:
        for b in bad:
            print("  ✗", b)
        print(f"\n{n_ps1} 个 .ps1 / {n_bat} 个 .bat / {n_vbs} 个 .vbs 检查完毕，{len(bad)} 项不合规")
        return 1
    print(f"  ✓ {n_ps1} 个 .ps1 带 BOM，{n_bat} 个 .bat + {n_vbs} 个 .vbs 纯 ASCII，行尾均为 CRLF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
