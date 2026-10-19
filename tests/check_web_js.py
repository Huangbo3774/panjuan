"""语法自检：抽出 web/*.html 里的内联 JS，交给 node --check 验。

为什么需要：我用 Python 通用换行模式改过一次 HTML，JS 源码里的 '\\n' 转义序列
被当成真实换行写回，导致 `join('⏎')` 这种跨行字符串 —— 整段 <script> 静默不执行，
页面看起来"功能没了"但没有任何提示。语法检查能在 1 秒内抓到它。
"""
from __future__ import annotations

import glob
import os
import re
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


def check_relative_paths(html_path: str) -> list[str]:
    """样式与接口一律用相对路径。

    绝对路径 /css/app.css 在 http:// 下没事，但用户【双击 HTML】用 file:// 打开时
    会去磁盘根 C:/css/app.css 找 → 找不到 → 整页裸 HTML。
    这个坑真实发生过（用户看到的就是"黑不溜秋的什么玩意"），所以钉成门禁。
    """
    raw = open(html_path, encoding="utf-8", newline="").read()
    bad = []
    for pat, why in (('href="/css/', '样式绝对路径'), ('src="/', '资源绝对路径'),
                     ('fetch(`/api/', '接口绝对路径'), ("fetch('/api/", '接口绝对路径'),
                     ('fetch(`api/', None), ('api(`/api/', '接口绝对路径')):
        if why is None:
            continue
        n = raw.count(pat)
        if n:
            bad.append(f"{why} ×{n}（file:// 下会 404）")
    return bad


def node_check(path: str, label: str, snippet: str) -> int:
    """把一段 JS 交给 node --check；返回 0 通过 / 1 失败 / -1 没装 node。"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8", newline="") as tf:
        tf.write(snippet)
        tmp = tf.name
    try:
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"  OK   {label}")
            return 0
        print(f"  FAIL {label}\n{r.stderr[:600]}")
        return 1
    except FileNotFoundError:
        print("  SKIP 没装 node，无法做语法检查")
        return -1
    finally:
        os.unlink(tmp)


def comment_ranges(raw: str):
    """返回所有 <!-- … --> 覆盖的字符区间。"""
    out, i = [], 0
    while True:
        a = raw.find("<!--", i)
        if a < 0:
            return out
        b = raw.find("-->", a + 4)
        if b < 0:                       # 没有闭合 —— 调用方会当成错误报，这里先记到文件尾
            out.append((a, len(raw)))
            return out
        out.append((a, b + 3))
        i = b + 3


def in_comment(ranges, pos: int) -> bool:
    return any(a <= pos < b for a, b in ranges)


def check_structure(raw: str) -> list[str]:
    """HTML 结构最低保证：注释必须成对，关键标签必须在注释之外。

    真实事故：我给四个页面注入 gate.js 时，写了两行注释却没写结尾的 `-->`。
    未闭合的注释会把后面的内容一直吞到 </head>，于是 <script src=js/gate.js>
    连同 <body> 开标签一起变成注释文本 —— 浏览器不报错，页面直接空掉，
    而当时的闸门只 grep 字符串，照样绿灯。这条规则就是为了堵这个口子。
    """
    bad = []
    n_open, n_close = raw.count("<!--"), raw.count("-->")
    if n_open != n_close:
        bad.append(f"注释不成对：<!-- ×{n_open}，--> ×{n_close}（未闭合的注释会吞掉后面的标签）")
    ranges = comment_ranges(raw)
    for pat, why in (('<script src="js/gate.js">', 'gate.js 的 script 标签'),
                     ('<link rel="stylesheet" href="css/app.css">', '样式表 link'),
                     ('<body>', '<body> 开标签')):
        pos = raw.find(pat)
        if pos < 0:
            continue                    # 缺失由别的检查负责，这里只判"被注释吃掉"
        if in_comment(ranges, pos):
            bad.append(f"{why} 落在未闭合的注释里（浏览器不会执行它）")
    return bad


CANON_STEPS = ["上传", "校对题目", "在线做题", "打印成 PDF"]
STEP_KEYS = {"proofread.html": "proofread", "paper.html": "answer", "print.html": "print"}


def check_flow(html_path: str, raw: str) -> list[str]:
    """流程顺序的门禁。

    用户原话："你这个顺序是错误的 —— 上传、校对、做题、打印。"
    上一版四页各抄一份 items 数组，preview.html 那份把「打印版」排在第 2 步，
    抄一遍就漂一次。现在顺序只在 web/js/app.js 里有一份，于是这里查三件事：
      1) 那份唯一定义的顺序 = 口径（见 check_canon_steps）；
      2) 页面里不许再出现自己抄的步骤数组；
      3) 每个流程页必须挂 app.js 并声明自己是第几步；首页那段"四步"文案也要同序。
    """
    bad = []
    name = os.path.basename(html_path)
    if "const items=[" in raw or "items=[['index.html'" in raw:
        bad.append("页面里又抄了一份步骤数组 —— 顺序必须只住在 js/app.js")
    if "'打印版'" in raw or '"打印版"' in raw:
        # 只禁这个【标签字面量】；「打印版式」是正常的字段名，不能一起误伤
        bad.append("出现了旧叫法「打印版」（第 4 步叫「打印成 PDF」）")
    if name in STEP_KEYS:
        if "js/app.js" not in raw:
            bad.append("没挂 js/app.js（步骤条顺序的唯一来源）")
        want = 'data-step="%s"' % STEP_KEYS[name]
        if want not in raw:
            bad.append(f"缺 {want}：页面没声明自己在第几步")
    if name == "index.html":
        seg = raw[raw.find('class="flow"'):]
        seg = seg[:seg.find("</section>")]
        labels = re.findall(r"<i>\d</i>([^<]+)<", seg)
        if [l.strip() for l in labels] != CANON_STEPS:
            bad.append(f"首页「四步」文案顺序是 {labels}，口径是 {CANON_STEPS}")
    return bad


def check_canon_steps() -> list[str]:
    p = os.path.join(WEB, "js", "app.js")
    if not os.path.exists(p):
        return ["缺 web/js/app.js"]
    src = open(p, encoding="utf-8", newline="").read()
    found = re.findall(r"label:\s*'([^']+)'", src)
    bad = []
    if found != CANON_STEPS:
        bad.append(f"js/app.js 里的步骤顺序是 {found}，口径是 {CANON_STEPS}")
    return bad


def check_gate(html_path: str, raw: str) -> list[str]:
    """四个页面都必须挂上门闸（js/gate.js）。

    网页自己起不了本地进程，所以「启动服务」按钮是用户唯一的自救入口。
    某次改版把这个 script 标签删掉，页面就退化成"点什么都报错、又没人解释"，
    而这正是用户当初开火的那个场景 —— 所以钉成门禁，不靠我记得。
    """
    bad = []
    if 'src="js/gate.js"' not in raw:
        bad.append("没挂 js/gate.js（服务没起来时页面不会提示，也不给启动入口）")
    else:
        # 光看字符串不够：上面那个事故里标签"在文件里"，但躺在未闭合的注释里，等于没有
        ranges = comment_ranges(raw)
        pos = raw.find('src="js/gate.js"')
        if in_comment(ranges, pos):
            bad.append("js/gate.js 的 script 标签在未闭合的注释里，浏览器不会加载它")
    if 'id="guard"' in raw:
        bad.append("还留着旧的 #guard 容器（提示语已经统一到 gate.js，两处会互相矛盾）")
    return bad


def check_external_js() -> tuple[int, int]:
    """外链 JS 文件也要过 node --check，并且不许用 innerHTML 拼页面数据。

    内联 <script> 有语法检查，以前 js/*.js 是盲区：gate.js 里一个括号写错，
    四个页面的「启动服务」按钮集体失灵，而 check.bat 一路绿灯。
    """
    bad = 0
    total = 0
    jsdir = os.path.join(WEB, "js")
    for name in sorted(glob.glob(os.path.join(jsdir, "*.js"))):
        total += 1
        src = open(name, encoding="utf-8", newline="").read()
        rel = "web/js/" + os.path.basename(name)
        r = node_check(name, rel, src)
        if r == 1:
            bad += 1
        elif r < 0:
            return -1, total
        # gate.js 里出现 .innerHTML＝"静态文案"的口子一旦开，下一个改动就会把
        # 题目原文塞进去（题目是用户上传的内容）。结构上禁止比口头承诺可靠。
        if ".innerHTML" in src or ".outerHTML" in src or "document.write" in src:
            print(f"  FAIL {rel} 用了 innerHTML/outerHTML/document.write —— 改用 createElement + textContent")
            bad += 1
    return bad, total


def main() -> int:
    bad = 0
    total = 0
    js_bad = 0        # 只数语法检查的失败，别让"路径不合规"混进分母（否则汇总会假绿）
    for msg in check_canon_steps():
        print("  FAIL", msg)
        bad += 1
    for name in sorted(os.listdir(WEB)):
        if not name.endswith(".html"):
            continue
        p = os.path.join(WEB, name)
        for msg in check_relative_paths(p):
            print(f"  FAIL {name} {msg}")
            bad += 1
        raw = open(p, encoding="utf-8", newline="").read()
        for msg in check_structure(raw):
            print(f"  FAIL {name} {msg}")
            bad += 1
        for msg in check_flow(p, raw):
            print(f"  FAIL {name} {msg}")
            bad += 1
        for msg in check_gate(p, raw):
            print(f"  FAIL {name} {msg}")
            bad += 1
        # 结构检查：JS 源码里不该出现「真实换行夹在引号中间」的坏字面量
        # （Python 通用换行模式改写 HTML 时会把 '\\n' 变成真换行，制造语法错误）
        if "('\\r\\n')" in raw or "('\\n\\r')" in raw:
            print(f"  FAIL {name} 含可疑的真实换行字面量")
            bad += 1
        for i, js in enumerate(extract(p)):
            total += 1
            r = node_check(p, f"{name} <script>#{i}", js)
            if r == 1:
                bad += 1
                js_bad += 1
            elif r < 0:
                print("  SKIP 没装 node，无法做语法检查")
                return 0 if not bad else 1
        # 语义检查：不许再有把对象数组直接 join 的写法（会渲染成 [object Object]）
        n_bad = raw.count("||[]).join(")
        if n_bad:
            print(f"  FAIL {name} 有 {n_bad} 处 `(x||[]).join(...)`，对象数组会被渲染成 [object Object]")
            bad += n_bad
    e_bad, e_total = check_external_js()
    skip_node = e_bad < 0
    if skip_node:
        e_bad, e_total = 0, e_total
    bad += e_bad
    print(f"\n内联 JS 语法 {total - js_bad}/{total}；外链 JS 语法+innerHTML "
          f"{e_total - e_bad}/{e_total}；其它不合规 {bad - js_bad - e_bad} 项"
          + ("（没装 node，语法检查已跳过）" if skip_node else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
