# -*- coding: utf-8 -*-
"""发布名闸门：README 里承诺的下载文件名，GitHub 必须真能给出来。

为什么需要：2026-10-19 发 v1.1.0 时，README 写的是「磐卷-Windows-免安装.zip」，
`gh release create` 上传后附件被 GitHub 折成 `-Windows-.zip`——
**Release 的资产名（进 URL 的那个）不吃非 ASCII 字符**，中文只能放在 label 里。
README 承诺的名字和用户点开的链接不是同一个东西，属于"文档骗人"那一类。

两条判据：
  ① 离线（check.bat 跑这条）：README 里出现的下载文件名必须是纯 ASCII，
     且中英两份 README 说的是同一个名字；
  ② 在线（`--online`，手动跑）：最新 Release 上真的挂着这个名字、大小和本地包一致。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

README = {"README.md": "英文", "README.zh-CN.md": "中文"}
ZIP_RE = re.compile(r"`([^`\n]*?\.zip)`")


def advertised() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f, _label in README.items():
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p):
            out[f] = set()
            continue
        with open(p, encoding="utf-8") as fh:
            out[f] = set(ZIP_RE.findall(fh.read()))
    return out


def main() -> int:
    bad: list[str] = []
    adv = advertised()
    for f, names in adv.items():
        if not names:
            bad.append(f"{f} 里一个 .zip 文件名都没提到，闸门测不到东西（不是通过）")
            continue
        for n in sorted(names):
            if not n.isascii():
                bad.append(f"{f} 承诺的下载名 {n!r} 含非 ASCII 字符 —— "
                           f"GitHub 会把它折成别的名字，README 的链接就是骗人的")
    allnames = set().union(*adv.values()) if adv else set()
    if len(allnames) > 1:
        bad.append(f"中英 README 的下载名不一致：{sorted(allnames)}")
    print("  README 承诺的下载名：" + ", ".join(sorted(allnames)) if allnames else "  （无）")

    if "--online" in sys.argv:
        try:
            r = subprocess.run(["gh", "release", "view", "--json",
                                "tagName,assets", "-q",
                                '{"tag":.tagName,"assets":[.assets[]|{name,size}]}'],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", cwd=ROOT, timeout=180)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or "").strip()[:300]
                                   or f"gh 退出码 {r.returncode}")
            info = json.loads(r.stdout)
        except Exception as e:
            bad.append(f"--online 取最新 Release 失败：{type(e).__name__}: {e}")
            info = None
        if info:
            assets = info.get("assets", [])
            got = {a["name"] for a in assets}
            sizes = {a["name"]: a.get("size") for a in assets}
            print(f"  最新 Release {info.get('tag')} 的附件：{sorted(got)}")
            for n in allnames:
                if n not in got:
                    bad.append(f"README 承诺 {n!r}，但 Release 上没有这个附件（实有 {sorted(got)}）")
                    continue
                local = os.path.join(ROOT, "dist", n)
                if os.path.isfile(local):
                    want = os.path.getsize(local)
                    if sizes.get(n) != want:
                        bad.append(f"附件 {n!r} 线上 {sizes.get(n)} 字节，本地包 {want} 字节")
                    else:
                        print(f"  {n} 大小一致：{want} 字节")
            if not got:
                bad.append("最新 Release 一个附件都没有，README 却在让人下载")
    else:
        print("  （没加 --online：只查了名字合不合法，没去线上核对附件真的在不在）")

    for m in bad:
        print("  ✗ " + m)
    print("\n" + ("发布名闸门 FAIL" if bad else "发布名闸门 PASS"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
