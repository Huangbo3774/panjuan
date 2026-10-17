"""把中文版 README 落成 README.zh-CN.md，并在两份文件顶部维护语言切换条。
用二进制读写：文本模式会做换行转换，上次就是它把 JS 里的 '\\n' 转义序列毁掉的。
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWITCH_EN = "[English](README.md) · **[中文](README.zh-CN.md)**"
SWITCH_ZH = "**[中文](README.zh-CN.md)** · [English](README.md)"


def read(p: str) -> str:
    with open(p, "rb") as fh:
        return fh.read().decode("utf-8").replace("\r\n", "\n")


def write(p: str, s: str) -> None:
    with open(p, "wb") as fh:
        fh.write(s.replace("\n", "\r\n").encode("utf-8"))


def main() -> int:
    en = read(os.path.join(ROOT, "README.md"))
    zh_src = os.path.join(ROOT, "README.zh-CN.md")
    old_zh = read(zh_src) if os.path.exists(zh_src) else None
    if old_zh is None:
        print("README.zh-CN.md 不存在；请先手工创建中文版正文")
        return 1

    # 去掉旧的切换条行（若存在），重新插入
    def with_switch(text: str, bar: str) -> str:
        lines = [l for l in text.split("\n")
                 if "README.zh-CN.md" not in l and not l.startswith("[English]")
                 and "](README.md)**" not in l]
        text = "\n".join(lines)
        i = text.find("\n")
        return text[: i + 1] + bar + "\n\n" + text[i + 1 :] if i > 0 else bar + "\n\n" + text

    write(zh_src, with_switch(old_zh, SWITCH_ZH))
    write(os.path.join(ROOT, "README.md"), with_switch(en, SWITCH_EN))
    for f in ("README.md", "README.zh-CN.md"):
        head = read(os.path.join(ROOT, f)).split("\n")[:5]
        print(f"--- {f} ---")
        print("\n".join(x for x in head if x.strip()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
