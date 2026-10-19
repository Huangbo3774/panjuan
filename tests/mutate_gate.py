"""变异闸门通用跑法：把源码逐条「故意打坏」，确认对应测试会变红。

单测全绿只证明「实现满足断言」，不证明「断言能发现问题」。
本项目已经吃过三次假绿：BOM 闸门把 --check 当文件名扫了 0 个文件、
F05 的前后对比下载写进同一个文件、答案计数 0 分不清「全过」和「尺坏了」。
所以每条新规则出厂时都要配一次「打坏看它红不红」。

用法：各模块的 break_*.py 只需给出变异表，跑法在这里。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import NamedTuple


class Mutation(NamedTuple):
    name: str          # 这条变异对应哪个历史缺陷
    file: str          # 被打坏的源文件（绝对路径）
    needle: str        # 现状片段（必须唯一命中）
    broken: str        # 打坏后的片段
    expect: str        # 期望变红的测试名关键字


def run(mutations: list[Mutation], test_file: str, python=None) -> int:
    py = python or sys.executable
    sources = {m.file: open(m.file, encoding="utf-8", newline="").read() for m in mutations}
    backups = {}
    for f, src in sources.items():
        backups[f] = f + ".bak_mutgate"
        shutil.copyfile(f, backups[f])
    # ⚠️ 先把这些模块的 __pycache__ 清掉，并且子进程一律 -B（不写字节码）：
    #    默认的 pyc 失效判定是【源文件 mtime(秒) + 大小】。改坏→还原常常落在同一秒内，
    #    大小又可能刚好相同 → 子进程拿到上一次那份 .pyc，跑的是【没被改坏】的代码，
    #    于是"打坏了却没测到红"，而且时好时坏（实测这条闸门两次跑出两种结果）。
    for f in sources:
        d = os.path.join(os.path.dirname(f), "__pycache__")
        if os.path.isdir(d):
            stem = os.path.splitext(os.path.basename(f))[0]
            for name in os.listdir(d):
                if name.startswith(stem + "."):
                    os.remove(os.path.join(d, name))
    bad: list[str] = []
    try:
        base = _fails(py, test_file)
        print(f"基线：{len(base)} 条失败（应为 0）")
        if base:
            print("  基线就是红的，先修测试再谈变异：", base)
            return 1
        for m in mutations:
            src = sources[m.file]
            if src.count(m.needle) != 1:
                print(f"  SKIP 锚点命中 {src.count(m.needle)} 次（规则被改写过或片段不唯一）：{m.name}")
                bad.append(f"{m.name}（锚点失效）")
                continue
            open(m.file, "w", encoding="utf-8", newline="").write(src.replace(m.needle, m.broken, 1))
            fails = _fails(py, test_file)
            # ⚠️ 匹配对象必须是【整行】，不能是"→ 之前截断的名字"。
            #    第一版在这里截断过，凡是期望串里带了「→ 」的变异（比如「无标准答案 → 待确认」）
            #    永远匹配不上，被判成「这条缺陷没有尺在量」——尺本身出错时把产品喊成有病，
            #    比产品出错更难发现，所以这条教训单独留着。
            hit = [x for x in fails if m.expect in x]
            if hit:
                print(f"  ✓ 打坏「{m.name}」→ 抓到 {len(fails)} 条：{hit[0].split('→')[0].strip()}")
            else:
                print(f"  ✗ 打坏「{m.name}」→ 仍全绿！没有任何尺在量它（期望红：{m.expect}）")
                bad.append(m.name)
            open(m.file, "w", encoding="utf-8", newline="").write(src)
    finally:
        for f, bk in backups.items():
            shutil.move(bk, f)
            restored = open(f, encoding="utf-8", newline="").read() == sources[f]
            print(f"已还原 {f.rsplit(chr(92), 1)[-1]}（校验：{'一致' if restored else '被改动！'}）")
            if not restored:
                bad.append(f"{f} 未还原")
    print(f"\n{len(mutations) - len(bad)}/{len(mutations)} 条变异被测试抓到")
    for b in bad:
        print("   未通过：", b)
    return 1 if bad else 0


def _fails(py: str, test_file: str) -> list[str]:
    """返回【完整】的失败行（含 → 后面的原因），匹配用整行，显示时再截断。"""
    p = subprocess.run([py, "-B", test_file], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    return [ln.strip() for ln in out.splitlines()
            if ln.strip().startswith(("FAIL", "ERROR"))]
