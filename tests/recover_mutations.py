# -*- coding: utf-8 -*-
"""还原 break_figures / mutate_gate 被强杀后留在源码里的变异。

为什么需要它：变异门禁是"改源码 → 跑测试 → 还原"。机器死机、进程被强杀时
还原那一步不会执行，源码会停在坏态；而插入型变异（new = old + 一行）
光看旧串还在不在查不出来。break_figures 开跑前把四个文件的原字节写进
var/_mut_backup；本脚本把它们原样写回并逐字节核对，然后删掉备份。

用法：py -3.11 tests/recover_mutations.py
"""
from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP = os.path.join(ROOT, "var", "_mut_backup")
TARGETS = {
    "figures.py": os.path.join(ROOT, "app", "extractor", "figures.py"),
    "lines.py": os.path.join(ROOT, "app", "extractor", "lines.py"),
    "rules.py": os.path.join(ROOT, "app", "extractor", "rules.py"),
    "answer_writer.py": os.path.join(ROOT, "app", "papers", "answer_writer.py"),
}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.path.isdir(BACKUP):
        print("没有待还原的备份：" + BACKUP)
        return 0
    restored = 0
    for name, dst in TARGETS.items():
        src = os.path.join(BACKUP, name)
        if not os.path.isfile(src):
            print("★备份缺文件：%s（不动源码）" % src)
            return 1
        raw = open(src, "rb").read()
        cur = open(dst, "rb").read() if os.path.isfile(dst) else b""
        if cur != raw:
            open(dst, "wb").write(raw)
            restored += 1
            print("还原 %s（%d 字节）" % (dst, len(raw)))
        else:
            print("未变 %s" % dst)
        assert open(dst, "rb").read() == raw, "还原后字节不一致：" + dst
    shutil.rmtree(BACKUP, ignore_errors=True)
    print("完成：还原 %d 个文件，备份已删除。" % restored)
    print("接着跑 py -3.11 tests/test_figures.py 确认基线全绿，再重跑门禁。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
