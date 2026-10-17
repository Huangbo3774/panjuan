"""语法自检：抽出 web/*.html 里的内联 JS，交给 node --check 验。

为什么需要：我用 Python 通用换行模式改过一次 HTML，JS 源码里的 '\\n' 转义序列
被当成真实换行写回，导致 `join('⏎')` 这种跨行字符串 —— 整段 <script> 静默不执行，
页面看起来"功能没了"但没有任何提示。语法检查能在 1 秒内抓到它。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def extract(html_path: str) -> list[str]:
    # newline='' 是关键：否则读进来的 \n 转义序列会被换行转换毁掉
    with open(html_path, encoding="utf-8", newline="") as fh:
        s = fh.read()
    out = []
    i = 0
    while True:
        a = s.find("<script>", i)
        if a < 0:
            break
        b = s.find("</script>", a)
        if b < 0:
            break
        out.append(s[a + len("<script>"):b])
        i = b + 9
    return out


def main() -> int:
    bad = 0
    total = 0
    for name in sorted(os.listdir(WEB)):
        if not name.endswith(".html"):
            continue
        p = os.path.join(WEB, name)
        raw = open(p, encoding="utf-8", newline="").read()
        # 结构检查：JS 源码里不该出现「真实换行夹在引号中间」的坏字面量
        # （Python 通用换行模式改写 HTML 时会把 '\\n' 变成真换行，制造语法错误）
        if "('\\r\\n')" in raw or "('\\n\\r')" in raw:
            print(f"  FAIL {name} 含可疑的真实换行字面量")
            bad += 1
        for i, js in enumerate(extract(p)):
            total += 1
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8", newline="") as tf:
                tf.write(js)
                tmp = tf.name
            try:
                r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
                if r.returncode == 0:
                    print(f"  OK   {name} <script>#{i}")
                else:
                    bad += 1
                    print(f"  FAIL {name} <script>#{i}\n{r.stderr[:600]}")
            except FileNotFoundError:
                print("  SKIP 没装 node，无法做语法检查")
                return 0
            finally:
                os.unlink(tmp)
        # 语义检查：不许再有把对象数组直接 join 的写法（会渲染成 [object Object]）
        n_bad = raw.count("||[]).join(")
        if n_bad:
            print(f"  FAIL {name} 有 {n_bad} 处 `(x||[]).join(...)`，对象数组会被渲染成 [object Object]")
            bad += n_bad
    print(f"\n{total - bad}/{total} 段内联 JS 语法通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
