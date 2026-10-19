"""跑 web/js/subqs.js 的行为断言 + 和 Python 侧做【同口径】交叉核对。

为什么要包一层 Python：check.bat 里所有尺都必须是"跑不动 = 红"，不是"跳过 = 绿"。
node 不在场时，浏览器那套小问/空位标签就【没有任何尺在量】—— 本项目已经吃过
「闸门自己漏检却一路绿灯」三次，所以这里把 SKIP 判成 FAIL。

交叉核对针对的是另一类事故：校对页保存时用 JS 重算 q.blanks，
后端用 BLANK_RE 算同一个数。两处实现一漂，家长点一次保存，
做题页的输入框数量就跳一格（少一格＝批改下标错位）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.extractor.rules import BLANK_RE                            # noqa: E402

ASSERT_JS = os.path.join(ROOT, "tests", "subqs_assert.js")
CROSS_JS = os.path.join(ROOT, "tests", "cross_blanks.js")
SUBJS = os.path.join(ROOT, "web", "js", "subqs.js")
N_CASES = 13        # 断言条数：改断言必须同时改这里，否则"删掉一半断言"也能绿灯

# 清单只有这一份（Python 侧），JS 侧拿同一份跑 —— 两边各抄一份清单，
# 漂了都不知道比的是不是同一批字符串。
BATTERY = [
    "数了(      )次,一共有(      )只蝴蝶。",
    "数了（      )次,一共有(      ）只蝴蝶。",      # OCR 常读成半/全角混配的一对
    "一年有（        ）个月，大月有（  ）个。",
    "算式：____________ ＝ ____________",
    "3×4=（12），5×6=（30）",
    "（ 见上图 ）不对，应该是（   ）",
    "a_b",
    "在（\u3000\u3000\u3000）里填“>”“<”或“=”",
    "读作：(         )，写作：（\u00a0\u00a0）",
    "",
    "（）",
    "() x",
    "______ ______ 两条下划线",
    "（1）第一问（2）第二问",
]


def _node(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([shutil.which("node"), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    if not shutil.which("node"):
        print("  FAIL 找不到 node —— 小问/空位标签此刻【没有尺在量】，不许算通过")
        return 1
    for f in (SUBJS, ASSERT_JS, CROSS_JS):
        if not os.path.exists(f):
            print(f"  FAIL 文件不在：{f}")
            return 1

    bad = 0
    r = _node([ASSERT_JS])
    out = (r.stdout or "") + (r.stderr or "")
    print("\n".join(l for l in out.splitlines() if l.strip().startswith(("PASS", "FAIL"))))
    if r.returncode != 0 or f"{N_CASES} passed" not in out:
        print(f"  FAIL 小问视图断言没过 / 条数不是 {N_CASES} 条（断言文件被删减或没跑起来）")
        bad += 1
    else:
        print(f"  OK   作答页小问视图（node 断言 {N_CASES}/{N_CASES}）")

    # ── 交叉核对 ──
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8", newline="") as tf:
        json.dump(BATTERY, tf, ensure_ascii=False)
        tmp = tf.name
    try:
        c = _node([CROSS_JS, tmp])
    finally:
        os.unlink(tmp)
    try:
        js_counts = json.loads((c.stdout or "").strip() or "[]")
    except json.JSONDecodeError:
        js_counts = []
    py_counts = [len(BLANK_RE.findall(s)) for s in BATTERY]
    if not c.stdout or js_counts != py_counts:
        print(f"  FAIL 前后端口径漂了：python={py_counts}")
        print(f"                          js    ={js_counts}  {c.stderr[:200]}")
        for i, (a, b) in enumerate(zip(py_counts, js_counts)):
            if a != b:
                print(f"        第 {i + 1} 条不一致：{BATTERY[i]!r} → python {a} / js {b}")
        bad += 1
    else:
        print(f"  OK   空位数前后端同口径（{len(BATTERY)} 条字符串，"
              f"合计 {sum(py_counts)} 个空位）")
        # 反证：清单里必须真的有空位，否则"两边都数出 0"也是假绿
        if sum(py_counts) == 0:
            print("  FAIL 清单数出来全是 0 —— 这条尺在比空气")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
