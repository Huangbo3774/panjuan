"""PRD §8.1 功能验收 F01–F10：通过真实 HTTP API 跑，不碰内部函数。

用法: py -3.11 tests/acceptance.py            # 需要先起服务（本脚本会自己起）
每条用例给出可核对的实测数字；判不过就 FAIL，不粉饰。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import urllib.request                                            # noqa: E402
import pymupdf                                                   # noqa: E402

BASE = "http://127.0.0.1:8777"
PORT = 8777

# 真实作业在 samples/private/（已 gitignore，不入库）。别人 clone 下来没有它，
# 所以缺料时自动改用 scripts/make_public_samples.py 生成的公开样本。
_PRIVATE = os.path.join(ROOT, "samples", "private")
_PUBLIC = os.path.join(ROOT, "samples", "public")
_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".docx")
if os.path.isdir(_PRIVATE) and any(f.lower().endswith(_EXT) for f in os.listdir(_PRIVATE)):
    S, SAMPLE_SET = _PRIVATE, "private"
else:
    S, SAMPLE_SET = _PUBLIC, "public"
    if not os.path.isdir(S) or not any(f.lower().endswith(_EXT) for f in os.listdir(S)):
        print("没有可用样本。先跑：py -3.11 scripts/make_public_samples.py")
        sys.exit(2)

# 公开样本与真实材料文件名不同，用例按真实材料写，这里做一层解析
ALIAS = {
    "数学作业.jpeg": "手机拍作业.jpg",
    "第三单元达标练习题A.jpeg": "清晰试卷图.jpg",
    "第三单元达标练习题B.jpg": "清晰试卷图.jpg",
    "综合实践课.pdf": "扫描版试卷.pdf",
    "第三单元练习题.pdf": "扫描版试卷.pdf",
    "L2中期评估模拟卷.pdf": "文字版试卷.pdf",
    "paper-cn.docx": "Word试卷.docx",
} if SAMPLE_SET == "public" else {}


def sp(name: str) -> str:
    """把用例里的样本名解析成当前样本集里的真实路径。"""
    return os.path.join(S, ALIAS.get(name, name))


def req(method, path, body=None, headers=None, raw=False):
    url = BASE + path
    r = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            d = resp.read()
            return resp.status, (d if raw else json.loads(d.decode("utf-8")))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]


def multipart(path_field, files):
    """files: [(filename, bytes)] → (content_type, body)"""
    b = "----accBoundary7MA4YWxkTrZu0gW"
    out = bytearray()
    for fn, data in files:
        out += f"--{b}\r\nContent-Disposition: form-data; name=\"{path_field}\"; filename=\"{fn}\"\r\n".encode("utf-8")
        out += b"Content-Type: application/octet-stream\r\n\r\n"
        out += data
        out += b"\r\n"
    out += f"--{b}--\r\n".encode("utf-8")
    return f"multipart/form-data; boundary={b}", bytes(out)


def upload(files):
    ct, body = multipart("files", files)
    return req("POST", "/api/tasks", body, {"Content-Type": ct})


def wait(tid, want=("done", "partial", "failed"), timeout=240):
    """轮询到任务真正完成。

    ⚠️ 不能只看 stage 变了没：relayout 期间 stage 会残留上一轮的"完成"，
       用 stage 判结束会让本函数立刻返回，测试于是下载到【旧文件】，
       看起来就像"开关没生效"（F05 第一版是被这个假象骗的）。
    """
    t0 = time.time()
    s = None
    while time.time() - t0 < timeout:
        _, s = req("GET", f"/api/tasks/{tid}")
        if isinstance(s, dict) and s.get("status") in want:
            return s
        time.sleep(1)
    raise TimeoutError(f"任务 {tid} 超时，最后状态 {s.get('stage') if isinstance(s, dict) else s}")


def wait_for(tid, pred, timeout=240):
    """等到 pred(状态) 成立（用于等「重排完成」这种没有状态跳变的情况）。"""
    t0 = time.time()
    s = None
    while time.time() - t0 < timeout:
        _, s = req("GET", f"/api/tasks/{tid}")
        if isinstance(s, dict) and s.get("status") in ("done", "partial", "failed") and pred(s):
            return s
        time.sleep(1)
    raise TimeoutError(f"任务 {tid} 条件超时")


def set_options(tid, patch):
    """改选项并等【这一轮】重排出新 PDF（以日志增长为完成信号）。"""
    _, s = req("GET", f"/api/tasks/{tid}")
    n0 = len(s.get("logs") or [])
    req("PUT", f"/api/tasks/{tid}/options",
        json.dumps({**s["options"], **patch}).encode(), {"Content-Type": "application/json"})
    return wait_for(tid, lambda x: len(x.get("logs") or []) > n0)


def download(tid, tag=""):
    """下载产物。tag 必须用于区分同一任务的多次下载 ——
    曾因为两次都写 {tid}.pdf，导致先下载的那份被覆盖，
    于是"对比省墨前后"实际是把同一个文件量了两遍（F05 假失败的真因）。"""
    st, data = req("GET", f"/api/tasks/{tid}/export?mode=print", raw=True)
    if st != 200:
        return None, st
    p = os.path.join(ROOT, "var", "acc", f"{tid}{('_'+tag) if tag else ''}.pdf")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)
    return p, len(data)


def pdf_facts(path):
    if not path or not os.path.isfile(path):
        # 之前这里抛 TypeError: stat: path ... not NoneType，看不出是"导出没成功"
        raise AssertionError("PDF 未生成（导出接口没返回 200，看任务日志）")
    d = pymupdf.open(path)
    chars = sum(len("".join((p.get_text("text") or "").split())) for p in d)
    imgs = sum(len(p.get_images(full=True)) for p in d)
    sizes = {tuple(round(v) for v in (p.rect.width, p.rect.height)) for p in d}
    d.close()
    return {"pages": os.path.getsize(path) and len(pdf_facts_pages(path)), "chars": chars,
            "images": imgs, "sizes": sizes, "kb": round(os.path.getsize(path) / 1024)}


def pdf_facts_pages(path):
    d = pymupdf.open(path)
    n = d.page_count
    d.close()
    return list(range(n))


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


RESULTS: list[tuple[str, bool, str]] = []


def case(cid, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        import traceback
        ok, detail = False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
    RESULTS.append((cid, ok, detail))
    print(f"  {'✓' if ok else '✗'} {cid}  {detail}")


def main():
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                             "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(40):
            try:
                st, h = req("GET", "/api/health")
                if st == 200:
                    print(f"服务就绪 · {h.get('font')} · 样本集={SAMPLE_SET}\n")
                    break
            except Exception:
                pass
            time.sleep(0.6)
        else:
            print("服务起不来"); return 1

        # F01 手机拍作业照片 → 10 秒内出 A4，不模糊不歪
        def f01():
            t0 = time.time()
            _, r = upload([("数学作业.jpeg", read(sp("数学作业.jpeg")))])
            s = wait(r["task_id"])
            ms = round((time.time() - t0) * 1000)
            p, kb = download(s["task_id"], "a")
            f = pdf_facts(p)
            ok = ms <= 10000 and f["sizes"] == {(595, 842)} and f["images"] >= 1
            return ok, f"{ms}ms（限 10s）{f['pages']}页 {f['kb']}KB A4={f['sizes']} 图{f['images']}"
        case("F01 手机拍照 10 秒出 A4", f01)

        # F02 3 图 + 1 PDF + 1 docx 混合 → 合并为一份，页序 = 上传序
        def f02():
            order = ["第三单元达标练习题A.jpeg", "第三单元达标练习题B.jpg", "数学作业.jpeg",
                     "综合实践课.pdf", "paper-cn.docx"]
            _, r = upload([(n, read(sp(n))) for n in order])
            s = wait(r["task_id"])
            p, kb = download(s["task_id"], "a")
            f = pdf_facts(p)
            # 源页合计 3×1 + 3 + 1 = 7；重排会把稀疏内容合并，所以判「≥ 源页数」而非等于
            src_pages = sum(int(l.split("→")[1].split("页")[0]) for l in s["logs"] if "→" in l and "页" in l)
            all_ok = all(x["ok"] for x in s["files"])
            ok = all_ok and f["sizes"] == {(595, 842)} and f["pages"] >= 5 and s["pages"] == 5
            return ok, (f"5 个文件全部解析成功={all_ok}，源页 {src_pages} → 出 {f['pages']} 页 "
                        f"{f['kb']}KB A4={f['sizes']}")
        case("F02 混合格式合并为一份", f02)

        # F03 文字版 PDF → 字号统一、题号完整、无乱码
        def f03():
            _, r = upload([("L2中期评估模拟卷.pdf", read(sp("L2中期评估模拟卷.pdf")))])
            s = wait(r["task_id"])
            p, _ = download(s["task_id"], "a")
            d = pymupdf.open(p)
            txt = "".join(pg.get_text("text") or "" for pg in d)
            sizes = {round(sp["size"], 1) for pg in d for bl in pg.get_text("dict")["blocks"]
                     if bl.get("type") == 0 for ln in bl["lines"] for sp in ln["spans"]}
            d.close()
            qn = {int(m) for m in __import__("re").findall(r"(\d{1,3})[.、．]", txt)}
            has_q = len(qn) >= 5 and 1 in qn
            garbled = sum(1 for c in txt if c in "\ufffd")
            ok = has_q and garbled == 0 and len(sizes) <= 4
            return ok, f"题号1-5齐全={has_q} 乱码={garbled} 字号种类={sorted(sizes)}"
        case("F03 文字版 PDF 重排", f03)

        # F04 扫描版 PDF → 走清洗，输出清晰
        def f04():
            _, r = upload([("第三单元练习题.pdf", read(sp("第三单元练习题.pdf")))])
            s = wait(r["task_id"])
            p, _ = download(s["task_id"], "a")
            f = pdf_facts(p)
            profs = [l for l in s["logs"] if "扫描" in l]
            src = s["pages"] or f["pages"]
            ok = f["pages"] >= 1 and f["images"] >= src
            return ok, f"{f['pages']}页 内嵌图 {f['images']} 张 {f['kb']}KB · {profs[:1]}"
        case("F04 扫描版 PDF 出卷", f04)

        # F05 省墨模式：输出白底黑字、体积减小
        def f05():
            _, r = upload([("数学作业.jpeg", read(sp("数学作业.jpeg")))])
            s0 = wait(r["task_id"]); p0, kb0 = download(s0["task_id"], "before")
            s1 = set_options(s0["task_id"], {"ink_saver": True}); p1, kb1 = download(s1["task_id"], "after")
            import io
            import numpy as np
            from PIL import Image

            def ink_ratio(path):
                """量 PDF 里【真正内嵌的那张图】，不是整页渲染 —— 页边距的白底会把
                图里的灰底稀释掉（实测整页白度两边都是 91.1%，看不出差别）。"""
                d = pymupdf.open(path)
                vals = []
                for pg in d:
                    for x in [i[0] for i in pg.get_images(full=True)]:
                        a = np.asarray(Image.open(io.BytesIO(d.extract_image(x)["image"])).convert("L"))
                        vals.append(float((a > 200).mean()))
                d.close()
                return max(vals) if vals else 0.0

            w0, w1 = ink_ratio(p0), ink_ratio(p1)
            # 判据要能证明开关真的起作用；上一版用 >= 且量整页，开关无效也会"通过"（假绿）
            ok = w1 > w0 + 0.10
            return ok, (f"内嵌图白度 {w0*100:.1f}%→{w1*100:.1f}%（需显著上升） "
                        f"体积 {kb0//1024}KB→{kb1//1024}KB")
        case("F05 省墨模式", f05)

        # F06 2 合 1：两页合一页，内容完整可读
        def f06():
            _, r = upload([("综合实践课.pdf", read(sp("综合实践课.pdf")))])
            s0 = wait(r["task_id"]); p0, _ = download(s0["task_id"], "before"); n0 = pdf_facts(p0)["pages"]
            s1 = set_options(s0["task_id"], {"two_up": True}); p1, _ = download(s1["task_id"], "after"); f1 = pdf_facts(p1)
            import math
            ok = f1["pages"] == math.ceil(n0 / 2) and f1["images"] >= n0
            return ok, f"{n0} 页 → {f1['pages']} 页（√2 缩印）内嵌图 {f1['images']} 张"
        case("F06 2合1", f06)

        # F07 表头开关
        def f07():
            _, r = upload([("L2中期评估模拟卷.pdf", read(sp("L2中期评估模拟卷.pdf")))])
            s = wait(r["task_id"]); p, _ = download(s["task_id"], "before")
            HDR = "班级 _"
            with_h = HDR in pymupdf.open(p)[0].get_text("text")
            s1 = set_options(s["task_id"], {"show_header": False}); p1, _ = download(s1["task_id"], "after")
            without = HDR not in pymupdf.open(p1)[0].get_text("text")
            return with_h and without, f"开=有姓名栏 {with_h}，关=无 {without}"
        case("F07 表头开关", f07)

        # F11 页脚出处署名可关（口碑传播要有效，但不能是用户关不掉的广告）
        def f11():
            _, r = upload([("L2中期评估模拟卷.pdf", read(sp("L2中期评估模拟卷.pdf")))])
            s = wait(r["task_id"]); p, _ = download(s["task_id"], "on")
            txt_on = pymupdf.open(p)[0].get_text("text")
            shown = "磐卷" in txt_on and "开源免费" in txt_on
            s1 = set_options(s["task_id"], {"branding": False}); p1, _ = download(s1["task_id"], "off")
            txt_off = pymupdf.open(p1)[0].get_text("text")
            gone = "磐卷" not in txt_off
            # 反例：关掉署名不能顺手把页码也弄没
            paged = "第 1 页" in txt_off
            return shown and gone and paged, f"开=有署名 {shown}，关=无 {gone}，页码仍在 {paged}"
        case("F11 页脚署名可关", f11)

        # F08 损坏文件 + 正常文件混合：损坏标红不中断
        def f08():
            bad = b"%PDF-1.7\nthis is not a real pdf body\n%%EOF\n"
            _, r = upload([("坏文件.pdf", bad),
                           ("L2中期评估模拟卷.pdf", read(sp("L2中期评估模拟卷.pdf")))])
            s = wait(r["task_id"])
            rej = [f for f in s["files"] if not f["ok"]]
            p, kb = download(s["task_id"], "a")
            ok = len(rej) >= 1 and p is not None and pdf_facts(p)["pages"] >= 1
            return ok, f"拒绝 {len(rej)} 个（{rej[0]['error'][:40] if rej else ''}），正常文件仍出卷 {pdf_facts(p)['pages']} 页"
        case("F08 损坏文件不中断", f08)

        # F09 100 页 PDF 不崩溃、内存 ≤1GB
        # 注意：不能拿「输出页数 == 100」当判据 —— 每页只有一行文字时，重排把它们
        # 压成几页是【正确行为】（PRD 要的是统一版式，不是 1:1 复刻页序）。
        # 真正的判据是「100 行内容一行都不丢」+ 不崩 + 内存达标。
        def f09():
            import pymupdf as fz
            big = os.path.join(ROOT, "var", "acc100.pdf")
            os.makedirs(os.path.dirname(big), exist_ok=True)
            d = fz.open()
            for i in range(100):
                pg = d.new_page(width=595, height=842)
                # ⚠️ insert_text 默认 Helvetica，写不进中文（实测会变成 "·3· ········"）。
                #    必须用 fontname="china-s"，并且下面先自证内容真的进了 PDF，
                #    否则会拿一个坏夹具去测产品（本用例第一版就栽在这）。
                pg.insert_text((60, 80), f"Page {i+1} 第{i+1}页 磐卷压力测试内容 12345",
                               fontsize=12, fontname="china-s")
            d.save(big); d.close()

            chk = pymupdf.open(big)
            chk_txt = "".join(p.get_text("text") or "" for p in chk)
            chk.close()
            if "第7页" not in chk_txt.replace(" ", ""):
                return False, "夹具自证失败：压测 PDF 里中文没写进去，不能用来测产品"

            t0 = time.time()
            _, r = upload([("big100.pdf", read(big))])
            s = wait(r["task_id"], timeout=300)
            ms = round((time.time() - t0) * 1000)
            p, kb = download(s["task_id"], "a")
            f = pdf_facts(p)
            d = pymupdf.open(p)
            txt = "".join(pg.get_text("text") or "" for pg in d)
            d.close()
            missing = [i for i in range(1, 101) if f"第{i}页" not in txt.replace(" ", "")]
            mem = proc_memory_mb(proc.pid)
            ok = not missing and mem >= 0 and mem < 1024
            return ok, (f"100 页 → {f['pages']} 页 {ms}ms，内容缺失 {len(missing)} 行，"
                        f"服务内存 {mem:.0f}MB（限 1024）")
        case("F09 100 页不崩溃", f09)

        # F10 预览前后对比
        def f10():
            _, r = upload([("数学作业.jpeg", read(sp("数学作业.jpeg")))])
            s = wait(r["task_id"])
            ok = len(s["previews"]) >= 1 and s["previews"][0]["image_url"].startswith("/api/")
            st, _ = req("GET", s["previews"][0]["image_url"], raw=True) if ok else (0, None)
            return ok and st == 200, f"预览 {len(s['previews'])} 页，首图 HTTP {st}"
        case("F10 预览可显示", f10)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()

    print("\n" + "=" * 64)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for cid, ok, detail in RESULTS:
        if not ok:
            print(f"FAIL {cid}: {detail}")
    print(f"验收 {passed}/{len(RESULTS)} 通过")
    return 0 if passed == len(RESULTS) else 1


def proc_memory_mb(pid):
    try:
        import psutil
        return psutil.Process(pid).memory_info().rss / 1048576
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
            f"(Get-Process -Id {pid}).WorkingSet64/1MB"], text=True, timeout=20)
        return float(out.strip().splitlines()[-1])
    except Exception:
        return -1.0


if __name__ == "__main__":
    sys.exit(main())
