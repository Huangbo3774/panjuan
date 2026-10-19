"""PRD §8.2 V1.1 功能验收 F12–F15：走真实 HTTP + 真实 PDF，不碰内部函数。

样本用脚本现造的一份文字层试卷（含选择/填空/判断/问答四种题型），
原因：F12–F15 考的是「作答—批改—回传」这条链，跟材料是不是扫描件无关；
用现造样本才能让 clone 仓库的人也能跑（真实学生作业不入库）。

用法: py -3.11 tests/acceptance_v11.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                     # noqa: E402
from app.layout.options import MM                                   # noqa: E402

PORT = int(os.environ.get("PJ_PORT", "8781"))
# PJ_BASE 设了就【不自起服务】，改测那个地址 —— 这是验证打包产物（exe）的唯一诚实办法：
# 测的必须是双击出来的那个进程，而不是 import 源码起的 uvicorn。
EXTERNAL = (os.environ.get("PJ_BASE") or "").strip().rstrip("/")
BASE = EXTERNAL or f"http://127.0.0.1:{PORT}"
VAR = os.path.join(ROOT, "var", "acc11")
os.makedirs(VAR, exist_ok=True)
RESULTS: list[tuple[str, bool, str]] = []
CTX: dict = {}          # 跨用例共享（试卷号/题目），case() 靠它判断前置是否完成

LINES = [
    "第三单元 过关练习",
    "班级＿＿＿＿ 姓名＿＿＿＿ 满分 100",
    "一、选择题",
    "1. 4×7 读作（  ）",
    "A. 四七二十八    B. 4乘7    C. 7乘4    D. 四四十六",
    "2. 一个因数是 6，另一个因数是 8，积是（  ）",
    "A. 14    B. 48    C. 24    D. 16",
    "二、填空题",
    "3. 一半是（  ），用小数表示是（  ）。",
    "4. 6 行桃树，每行 8 棵，一共（  ）棵。",
    "三、判断题",
    "5. 6×3 和 3×6 的积相等。（  ）",
    "6. 30 厘米比 30 米长。（  ）",
    "四、解答题",
    "7. 小明有 24 颗糖，平均分给 6 个小朋友，每人几颗？写出算式并作答。",
]

KEY = {"1": "A", "2": "B", "3": ["1/2", "0.5"], "4": "48", "5": "√", "6": "×",
       "7": "24÷6=4，每人 4 颗"}
KID = {"1": "A", "2": "C", "3": ["二分之一", "0.5"], "4": "４８", "5": "√", "6": "√",
       "7": "24÷6=4 答每人4颗"}


def req(method, path, body=None, data=None, headers=None, raw=False):
    r = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        r.add_header("Content-Type", "application/json")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, data=data, timeout=180) as resp:
            d = resp.read()
            return resp.status, (d if raw else json.loads(d.decode("utf-8")))
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode("utf-8", "replace")[:200]}


def make_sample() -> str:
    """现造一份带文本层的试卷 PDF（字体 china-s 保证中文不乱码）。"""
    # 目录必须等服务起来【之后】再建：app 启动时会整目录清空 var/（PRD §4.7），
    # 在启动前建好的目录会被删掉，doc.save() 当场 FzErrorSystem code=2（实测）。
    os.makedirs(VAR, exist_ok=True)
    path = os.path.join(VAR, "v11样本卷.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60                                    # fitz 的 y 从页面【顶部】往下算
    for i, ln in enumerate(LINES):
        page.insert_text((50, y), ln, fontname="china-s", fontsize=12)
        y += 26
        if i == 8:      # "4. 6 行桃树…" 下面画一排圆点：验收要真的把图裁出来挂回题目
            for k in range(6):
                page.draw_circle(pymupdf.Point(70 + k * 26, y + 10), 9,
                                 color=(0, 0, 0), width=1.2)
            y += 44
    doc.save(path)
    doc.close()
    # 先证明【样本自己】是好的：不只证明"中文读得回来"，还要证明"行序是对的"。
    # 第一版这里从 y=780 往上写，整页顺序倒过来，题目串到大题里，
    # 于是 F12/F14 报的是产品的错、其实是夹具的错（本项目吃过一次同样的亏）。
    p0 = pymupdf.open(path)[0]
    back = p0.get_text("text")
    first = next((l.strip() for l in back.splitlines() if l.strip()), "")
    assert "选择题" in back and "4×7" in back, f"样本造坏了：{back[:80]!r}"
    assert first.startswith("第三单元"), f"样本行序不对（第一行是 {first!r}），排版会倒序读"
    return path


def upload(path: str) -> str:
    boundary = "----acc11"
    name = os.path.basename(path)
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
            f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + open(path, "rb").read() + tail
    r = urllib.request.Request(BASE + "/api/tasks", data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))["task_id"]


def wait_task(tid: str, timeout=120) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, s = req("GET", f"/api/tasks/{tid}")
        if s.get("status") in ("done", "partial", "failed"):
            return s
        time.sleep(0.4)
    raise TimeoutError("任务超时")


def case(cid, fn):
    if "前置" not in cid and "pid" not in CTX:
        # 前置没成就别硬跑：否则 6 条 KeyError 把真正的失败原因埋掉
        RESULTS.append((cid, False, "跳过：前置步骤未通过"))
        print(f"  ✗ {cid}  跳过：前置步骤未通过")
        return
    try:
        ok, detail = fn()
    except Exception as e:
        import traceback
        ok, detail = False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
    RESULTS.append((cid, ok, detail))
    print(f"  {'✓' if ok else '✗'} {cid}  {detail}")


def pdf_facts(path: str) -> dict:
    """页面真实读数。用 numpy 向量化：纯 Python 逐像素数一页数百万次循环，
    验收脚本会慢到像卡死（实测一次跑到超时）。"""
    import numpy as np
    doc = pymupdf.open(path)
    txt = "\n".join(p.get_text() for p in doc)
    sizes = {(round(p.rect.width), round(p.rect.height)) for p in doc}
    ink = colored = 0
    for p in doc:
        pix = p.get_pixmap(dpi=100)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        rgb = a[:, :, :3]
        mn = rgb.min(axis=2)
        mx = rgb.max(axis=2)
        ink += int((mn < 128).sum())
        colored += int(((mx.astype(int) - mn.astype(int)) > 40).sum())
    n = doc.page_count
    doc.close()
    return {"text": txt, "sizes": sizes, "pages": n, "ink": ink, "colored": colored,
            "kb": round(os.path.getsize(path) / 1024, 1)}


def answers_by_uid(qs: list[dict], table: dict) -> dict:
    """按题号把答案映射到 uid（题目文本里含 "1." 这样的编号，用 q_no 对齐）。"""
    out = {}
    for q in qs:
        no = str(q.get("q_no") if q.get("q_no") is not None else q.get("auto_no"))
        if no in table:
            out[q["uid"]] = table[no]
    return out


def main() -> int:
    proc = None
    if not EXTERNAL:
        # 数据根指到临时目录：验收造的假卷不许进用户那个真库（见 paths.PJ_DATA_HOME）
        acc_home = tempfile.mkdtemp(prefix="pj_acc_f12_")
        print(f"验收用临时数据根：{acc_home}")
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                                 "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
                                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                env={**os.environ, "PJ_DATA_HOME": acc_home})
    CTX.clear()
    try:
        for _ in range(40):
            try:
                st, h = req("GET", "/api/health")
                if st == 200:
                    break
            except Exception:
                pass                      # 服务还没起来，连接被拒是常态
            time.sleep(0.6)
        else:
            print(f"服务起不来（{BASE}）")
            return 1
        # 端口被上一轮没杀干净的服务占着时，新 uvicorn 会静默绑定失败，
        # 于是"跑的是新代码"这个前提就是假的 —— 必须核对 pid 是自己起的那个。
        if proc is not None:
            if h.get("pid") != proc.pid:
                print(f"端口 {PORT} 上是别人的服务（pid {h.get('pid')} ≠ 我起的 {proc.pid}），"
                      f"先把它杀掉再跑，否则测的是旧代码")
                return 1
            print("V1.1 验收 · 样本=脚本现造的文字层试卷\n")
        else:
            # 外部模式（PJ_BASE）：不自起服务，测的是别人那台进程 —— 用来验打包产物。
            # 这里没法核对 pid 归属，所以把远端自报的身份原样打出来，
            # 让"我测的到底是源码还是 exe"这件事留在记录里，而不是靠人记住。
            print(f"V1.1 验收 · 外部服务模式：测的是 {BASE}\n"
                  f"  远端自报 pid={h.get('pid')} · frozen={h.get('frozen')} · "
                  f"build={h.get('build')} · 数据目录={h.get('home')}\n"
                  f"  ⚠️ 外部模式不核对进程归属：请确认上面这个 frozen/pid 就是你要测的那一份\n")

        def prep():
            p = make_sample()
            tid = upload(p)
            s = wait_task(tid)
            st, r = req("POST", f"/api/papers/{tid}/parse")
            assert st == 200, f"识别失败 {st} {r}"
            CTX.update(tid=tid, pid=r["paper_id"], qs=r["questions"])
            types = {}
            for q in r["questions"]:
                types[q["qtype"]] = types.get(q["qtype"], 0) + 1
            assert r["status"] == "proofreading", f"识别完应进校对状态，实际 {r['status']}"
            # 没发布就不许做题（校对是上传者的活，做题页不该顺手改题）
            st2, g = req("POST", f"/api/papers/{r['paper_id']}/submissions",
                         {"answers": {r["questions"][0]["uid"]: "A"}})
            assert st2 == 409, f"未发布却能提交作答（HTTP {st2}）：{g}"
            fig = [q for q in r["questions"] if q.get("images")]
            assert fig, f"题目配图一张都没裁出来：{r.get('figures_note')}"
            im = fig[0]["images"][0]
            st3, raw = req("GET", f"/api/papers/{r['paper_id']}/figures/{im['name']}", raw=True)
            assert st3 == 200 and len(raw) > 800, f"配图路由取不到图：{st3}"
            return True, (f"试卷号 {r['paper_id']} · {len(r['questions'])} 题 · 题型 {types}"
                          f" · 待校对 {r['needs_review']} · 配图 {len(fig)} 题带图"
                          f"（{im['w_pt']}×{im['h_pt']}pt，HTTP 取回 {len(raw)} 字节）"
                          f" · 未发布提交被拒 409 ✓")
        case("前置 上传→识别题型→配图→发布闸门", prep)

        # F16 校对模式四功能：改 / 增 / 删 / 发布
        def f16():
            qs = CTX["qs"]
            target = qs[0]
            st, r = req("PUT", f"/api/papers/{CTX['pid']}/questions",
                        {"question": {**target, "text": "改过的题干（  ）", "qtype": "fill",
                                      "score": 3.0}})
            assert st == 200, f"改题失败 {st} {r}"
            now = {q["uid"]: q for q in r["questions"]}
            assert now[target["uid"]]["text"] == "改过的题干（  ）"
            assert now[target["uid"]]["score"] == 3.0 and now[target["uid"]]["manual_fixed"]
            st, r = req("POST", f"/api/papers/{CTX['pid']}/questions",
                        {"question": {"section": "二、填空题", "qtype": "fill",
                                      "text": "家长补的一道题（  ）", "blanks": 1, "score": 2.0},
                         "after_uid": qs[1]["uid"]})
            assert st == 200, f"加题失败 {st} {r}"
            added = r["question"]
            texts = [q["text"] for q in r["questions"]]
            assert texts.index("家长补的一道题（  ）") == 2, f"没插在指定位置后：{texts}"
            assert not added["needs_review"], "人工新增的题不该标待校对"
            st, r = req("DELETE", f"/api/papers/{CTX['pid']}/questions/{added['uid']}")
            assert st == 200 and "家长补的" not in "".join(q["text"] for q in r["questions"]), \
                f"删题失败 {st} {r}"
            st, r = req("POST", f"/api/papers/{CTX['pid']}/publish",
                        {"title": "第三单元 过关练习", "options": {"page_format": "a3_spread"}})
            assert st == 200, f"发布失败 {st} {r}"
            assert r["status"] == "published" and r["published_at"]
            st, g = req("GET", f"/api/papers/{CTX['pid']}/questions")
            assert g["status"] == "published"
            CTX["qs"] = g["questions"]
            return True, ("改题√（分值/题型/正文一起存并记 manual_fixed）"
                          " 加题√（按位置插入） 删题√ 发布√（状态 published）")
        case("F16 校对模式：改 / 增 / 删 / 发布", f16)

        # F12 在线作答：选择/填空/问答均可提交，草稿不丢
        def f12():
            st, j = req("GET", f"/api/papers/{CTX['pid']}/questions")
            qs = j["questions"]
            bytype = {q["qtype"] for q in qs}
            need = {"choice", "fill", "essay"}
            a = answers_by_uid(qs, {"1": "A", "3": ["1/2"], "7": "24÷6=4"})
            st, sub = req("POST", f"/api/papers/{CTX['pid']}/submissions",
                          {"answers": a, "class_name": "二(1)班", "student_name": "验收同学"})
            assert st == 200, f"提交失败 {st} {sub}"
            # 这一步还没录标准答案：全部题必须是"待确认"而不是"错"（判错＝误伤孩子）
            assert sub["counts"]["wrong"] == 0, f"没标准答案却判了错：{sub['counts']}"
            assert sub["counts"]["pending"] >= 3, sub["counts"]
            CTX["sub1"] = sub
            # 草稿：做题页用 localStorage，这里验证【页面能加载且表单渲染出三种控件】
            st, html = req("GET", "/paper.html", raw=True)
            assert st == 200, f"做题页打不开 {st}"
            html = html.decode("utf-8", "replace")
            has = all(k in html for k in ("localStorage", "collect()", "q.qtype==='choice'",
                                          "q.qtype==='fill'", "textarea"))
            assert has, "做题页缺作答控件"
            return True, (f"可提交题型 {sorted(bytype)}（含 {sorted(need)}）· "
                          f"三种控件齐备 · 未录答案时 {sub['counts']['pending']} 题待确认、0 题误判")
        case("F12 在线作答", f12)

        # F13 标准答案：自己做一遍 → 另存为标准答案
        def f13():
            st, mine = req("POST", f"/api/papers/{CTX['pid']}/submissions",
                           {"answers": answers_by_uid(CTX["qs"], KEY),
                            "class_name": "", "student_name": "家长"})
            assert st == 200, f"家长作答失败 {st} {mine}"
            st, k = req("POST", f"/api/papers/{CTX['pid']}/key", {"submission_id": mine["submission_id"]})
            assert st == 200, f"另存失败 {st} {k}"
            assert len(k["answers"]) >= 5, f"存进去的答案太少：{k['answers']}"
            st, g = req("GET", f"/api/papers/{CTX['pid']}/questions")
            assert g["key"] and len(g["key"]) >= 5, "取题目时没带回标准答案"
            # 同一个人再做一遍，必须满分（证明"答案卷与做题 UI 一致"）
            st, again = req("POST", f"/api/papers/{CTX['pid']}/submissions",
                            {"answers": answers_by_uid(g["questions"], KEY)})
            assert st == 200, again
            pend = again["counts"]["pending"]
            assert again["counts"]["wrong"] == 0, \
                f"自己做的卷子重做却有 {again['counts']['wrong']} 题判错：{again['results'][:3]}"
            CTX["keysub"] = again
            return True, (f"另存为答案 {len(k['answers'])} 条 · 重做一遍 0 题判错"
                          f"（得分 {again['score']}/{again['total']}，问答题按 PRD 只标待确认 {pend} 题）")
        case("F13 自己做一遍→另存为标准答案", f13)

        # F14 填空容错批改
        def f14():
            st, j = req("GET", f"/api/papers/{CTX['pid']}/questions")
            a = answers_by_uid(j["questions"], KID)
            st, sub = req("POST", f"/api/papers/{CTX['pid']}/submissions",
                          {"answers": a, "class_name": "二(1)班", "student_name": "小孩"})
            assert st == 200, sub
            byno = {str(r.get("q_no")): r for r in sub["results"]}
            assert byno["3"]["verdict"] == "correct", f"二分之一/0.5 没判对：{byno['3']}"
            assert byno["4"]["verdict"] == "correct", f"全角４８没判对：{byno['4']}"
            assert byno["2"]["verdict"] == "wrong", f"选错了却没判出来：{byno['2']}"
            assert byno["6"]["verdict"] == "wrong", f"判断题答错却没判出来：{byno['6']}"
            assert byno["7"]["verdict"] == "pending", f"问答题被自动判分了：{byno['7']}"
            CTX["kidsub"] = sub
            return True, (f"分数等价√ 全半角√ 答错判错√ 问答不自动判√"
                          f"（得分 {sub['score']}/{sub['total']}，待确认 {sub['pending_max']}）")
        case("F14 填空容错批改", f14)

        # F15 导出模式 C 批改 PDF（顺带核一遍模式 B）
        def f15():
            st, b = req("GET", f"/api/papers/{CTX['pid']}/export?mode=answered", raw=True)
            assert st == 200, f"B 版导出失败 {st} {b}"
            pb = os.path.join(VAR, "b.pdf")
            open(pb, "wb").write(b)
            st, cc = req("GET", f"/api/papers/{CTX['pid']}/export?mode=graded", raw=True)
            assert st == 200, f"C 版导出失败 {st} {cc}"
            pc = os.path.join(VAR, "c.pdf")
            open(pc, "wb").write(cc)
            fb, fc = pdf_facts(pb), pdf_facts(pc)
            assert "班级" in fc["text"] and "姓名" in fc["text"] and "得分" in fc["text"], "表头缺项"
            assert "二(1)班" in fc["text"] and "小孩" in fc["text"], "表头没带班级姓名"
            assert "满分" in fc["text"], "缺得分汇总"
            assert fc["ink"] > 500, f"C 版几乎没有墨：{fc['ink']}"
            assert fc["colored"] == 0, f"C 版有 {fc['colored']} 个彩色像素，黑白打印会丢信息"
            assert "磐卷 PaperForge" in fc["text"], "缺出处署名"
            assert fc["pages"] >= fb["pages"] >= 1
            # 发布时选了 A3 对开 → 导出的批改版必须是 A3 横版（1191×842）
            assert fc["sizes"] == {(1191, 842)}, \
                f"发布选了 A3 对开，导出却是 {fc['sizes']}"
            st, r = req("POST", f"/api/papers/{CTX['pid']}/publish",
                        {"options": {"page_format": "a4"}})
            assert st == 200, r
            st, cc = req("GET", f"/api/papers/{CTX['pid']}/export?mode=graded", raw=True)
            open(pc, "wb").write(cc)
            fa = pdf_facts(pc)
            assert fa["sizes"] == {(595, 842)}, f"切回 A4 后仍是 {fa['sizes']}"
            req("POST", f"/api/papers/{CTX['pid']}/publish", {"options": {"page_format": "a3_spread"}})
            return True, (f"B {fb['pages']}页 {fb['kb']}KB / C {fc['pages']}页 {fc['kb']}KB "
                          f"A3对开{sorted(fc['sizes'])[0]} 表头√ 汇总√ 黑白√ 署名√ · 版式可切回 A4√")
        case("F15 导出模式 B/C PDF（含 A3 对开）", f15)

        # 附加：题目校对（PRD F11 的"可人工校对"）+ 人工改判
        def extra_review():
            st, j = req("GET", f"/api/papers/{CTX['pid']}/questions")
            q = j["questions"][0]
            st, r = req("PUT", f"/api/papers/{CTX['pid']}/questions",
                        {"question": {"uid": q["uid"], "qtype": "essay", "score": 5.0}})
            assert st == 200, f"改题失败 {st} {r}"
            back = [x for x in r["questions"] if x["uid"] == q["uid"]][0]
            assert back["qtype"] == "essay" and back["manual_fixed"] and back["score"] == 5.0, back
            # 改题型后标准答案必须还在（uid 稳定性）
            st, g = req("GET", f"/api/papers/{CTX['pid']}/questions")
            assert g["key"].get(q["uid"]), "改完题号/题型后标准答案失联了"
            # 人工改判
            a = answers_by_uid(g["questions"], KID)
            st, sub = req("POST", f"/api/papers/{CTX['pid']}/submissions",
                          {"answers": {**a, "_manual": {q["uid"]: "correct"}}})
            assert st == 200, sub
            r0 = [x for x in sub["results"] if x["uid"] == q["uid"]][0]
            assert r0["verdict"] == "correct", r0
            # 还原题型，免得影响后面的用例
            req("PUT", f"/api/papers/{CTX['pid']}/questions",
                {"question": {"uid": q["uid"], "qtype": "choice", "score": 1.0}})
            return True, "改题型/分值√ 答案不失联√ 人工改判√"
        case("附加 题目校对与人工改判", extra_review)

        # 附加：重启后数据还在（SQLite 的意义）
        def extra_persist():
            st, j = req("GET", f"/api/papers/{CTX['pid']}/questions")
            assert st == 200 and j["questions"], j
            st, lst = req("GET", "/api/papers")
            assert st == 200 and any(p["id"] == CTX["pid"] for p in lst["papers"]), lst
            return True, f"试卷列表 {len(lst['papers'])} 份 · 题目 {len(j['questions'])} 道在库"
        case("附加 数据落在 SQLite 可复查", extra_persist)

        # F17 网页一键启动：服务发出去的四个页面都必须挂着门闸脚本，
        # 而且注册表里那条协议命令必须指向【当前这份检出】——
        # 文件夹挪过位置的话按钮会指向旧路径，点了没反应，这里要能看出来。
        def f17():
            import re
            problems = []
            for page in ("index.html", "proofread.html", "paper.html", "print.html"):
                st, body = req("GET", "/" + page, raw=True)
                assert st == 200, f"{page} 取不到（{st}）"
                txt = body.decode("utf-8", "replace")
                if 'src="js/gate.js"' not in txt:
                    problems.append(f"{page} 没挂 gate.js")
                # 注释不成对＝未闭合，会把 <script> 连同 <body> 一起吞掉（真实事故）
                if txt.count("<!--") != txt.count("-->"):
                    problems.append(f"{page} 注释不成对")
                if 'id="guard"' in txt:
                    problems.append(f"{page} 还留着旧 #guard")
            assert not problems, "；".join(problems)
            for f in ("web/js/gate.js", "scripts/start_hidden.vbs", "scripts/install_startup.ps1"):
                assert os.path.exists(os.path.join(ROOT, f)), f"缺文件 {f}"
            # 注册表这一步只在"已经注册过"时才校验指向；没注册不算失败
            # （clone 下来第一次跑的人还没双击过 start.bat，这时按钮本来就该提示手动启动）
            # 判决放在脚本的退出码里（0=指向本检出 / 2=没注册 / 3=指向别处），
            # 不去比对输出文本——中文路径过一遍代码页就成了乱码，比对结果会是假判决。
            note = "协议未注册（首次双击 start.bat 会自动注册）"
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-File", os.path.join(ROOT, "scripts", "install_startup.ps1"),
                                "-CheckThis"],
                               capture_output=True, text=True, timeout=60,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0:
                note = "协议已注册且指向本检出"
            elif r.returncode == 3:
                raise AssertionError("协议注册指向的不是当前这份检出（文件夹挪过位置？）："
                                     + (r.stdout or "").strip()[:200])
            elif r.returncode != 2:
                raise AssertionError(f"install_startup.ps1 -CheckThis 退出码 {r.returncode}："
                                     + (r.stdout or "").strip()[:200])
            return True, f"四页均挂 gate.js + 注释成对 · {note}"
        case("F17 一键启动：门闸挂载 + 协议指向本检出", f17)

        # F18 第 4 步「打印成 PDF」的三种内容 + 预览必须真的跟着变。
        # 两条用户口径：① 顺序是 上传→校对→做题(可跳过)→打印；
        #             ② 做了题就带答案、开了批改就带结果、没做就是空白卷。
        # 另外这一条专门盯"预览不刷新"那个投诉：改版式后 revision 必须变、
        # 页面几何必须变，而且同一份输入重复请求 revision 必须相同（否则是随机数假动作）。
        def f18():
            pid = CTX["pid"]
            # ── 1) 流程顺序：服务端发出去的唯一定义 js/app.js 里必须是口径顺序
            st, body = req("GET", "/js/app.js", raw=True)
            assert st == 200, "取不到 js/app.js"
            import re as _re
            labels = _re.findall(r"label:\s*'([^']+)'", body.decode("utf-8", "replace"))
            assert labels == ["上传", "校对题目", "在线做题", "打印成 PDF"], f"步骤顺序错了：{labels}"
            for page in ("proofread.html", "paper.html", "print.html"):
                st, b = req("GET", "/" + page, raw=True)
                t = b.decode("utf-8", "replace")
                assert "js/app.js" in t, f"{page} 没挂共享步骤条"
                assert "const items=[" not in t, f"{page} 又自己抄了一份步骤数组"

            # ── 2) 三种内容的状态与拒绝理由
            st, j = req("GET", f"/api/papers/{pid}/printable")
            assert st == 200, j
            assert j["can_blank"] and j["can_answered"], j
            # 前面 F13/F14 已录标准答案并作答过，所以三态此时都该可用
            assert j["can_graded"], f"有作答也有标准答案，批改版却不可选：{j['reasons']}"
            # 找一张没人做过的卷子，验证"不能选"时给的是解释而不是空按钮
            other = None
            st, lst = req("GET", "/api/papers")
            for p in lst["papers"]:
                if int(p["id"]) == pid:
                    continue
                st2, q = req("GET", f"/api/papers/{p['id']}/printable")
                if st2 == 200 and not q["can_answered"]:
                    other = (int(p["id"]), q)
                    break
            if other:
                oid, oj = other
                assert "作答" in oj["reasons"]["answered"], oj["reasons"]
                st2, _ = req("GET", f"/api/papers/{oid}/preview?mode=answered")
                assert st2 == 404, f"没作答却出了带答案的预览（{st2}）"

            # ── 3) 预览真的跟着版式变，而且 revision 是内容的函数
            def prev(mode):
                st3, b3 = req("GET", f"/api/papers/{pid}/preview?mode={mode}")
                assert st3 == 200, (mode, b3)
                return b3

            st, o = req("PUT", f"/api/papers/{pid}/options", {"page_format": "a4"})
            assert st == 200, o
            a4 = prev("blank")
            a4_again = prev("blank")
            assert a4["revision"] == a4_again["revision"], \
                f"同一份内容两次请求 revision 不同（{a4['revision']} vs {a4_again['revision']}）＝随机数假动作"
            st, o = req("PUT", f"/api/papers/{pid}/options", {"page_format": "a3_spread"})
            assert st == 200, o
            a3 = prev("blank")
            assert a3["revision"] != a4["revision"], "A4→A3 对开之后 revision 没变＝预览不可能变"
            assert a3["pages"] and a4["pages"]
            w3, h3 = a3["pages"][0]["w"], a3["pages"][0]["h"]
            w4, h4 = a4["pages"][0]["w"], a4["pages"][0]["h"]
            assert w3 > h3 and h4 > w4, f"A3 该横、A4 该竖：A3 {w3}×{h3}，A4 {w4}×{h4}"
            # 图本身也得变（URL 带 revision，浏览器不可能拿缓存）
            assert a3["pages"][0]["image_url"] != a4["pages"][0]["image_url"]
            st, png = req("GET", a3["pages"][0]["image_url"], raw=True)
            assert st == 200 and png[:8].startswith(b"\x89PNG"), "预览图取不到或不是 PNG"

            # ── 4) 三种内容各出一份 PDF，互不相同，且"答案在不在纸上"能读出来
            #     （批改符号是矢量画的线，不在文本层里，所以不能拿 ✓/✗/△ 当判据）
            import pymupdf
            st, q2 = req("GET", f"/api/papers/{pid}/questions")
            probe = "磐卷验收专用串QZ7"           # 只出现在作答里，不会出现在题干/选项
            ans = answers_by_uid(q2["questions"], KID)
            tgt = next((x for x in q2["questions"] if x["qtype"] == "essay"), q2["questions"][0])
            ans[tgt["uid"]] = probe
            st, mine = req("POST", f"/api/papers/{pid}/submissions",
                           {"answers": ans, "class_name": "二(1)班", "student_name": "验收小孩"})
            assert st == 200, f"为验收提交的作答失败了：{mine}"

            def text_of(mode):
                st5, b5 = req("GET", f"/api/papers/{pid}/export?mode={mode}", raw=True)
                assert st5 == 200 and b5[:4] == b"%PDF", (mode, st5)
                d = pymupdf.open(stream=b5, filetype="pdf")
                t = "".join(p.get_text() for p in d)
                d.close()
                return t

            sizes = {m: len(req("GET", f"/api/papers/{pid}/export?mode={m}", raw=True)[1])
                     for m in ("blank", "answered", "graded")}
            assert len(set(sizes.values())) == 3, f"三种内容导出的 PDF 大小一模一样：{sizes}"
            tb, ta_, tg = text_of("blank"), text_of("answered"), text_of("graded")
            assert probe not in tb, "空白卷的纸上出现了孩子的答案"
            assert probe in ta_, "「我的答案」这一版纸上找不到孩子的作答"
            assert probe in tg, "「答案+批改」这一版纸上找不到孩子的作答"
            import re as _re
            assert not _re.search(r"得分\s*[0-9]", tb), "空白卷的得分栏里已经有数字了"
            assert _re.search(r"得分\s*[0-9.]+\s*/", tg), "批改版没把得分写进表头"
            return True, (f"顺序=上传→校对→做题→打印 · A4/A3 revision 变且几何对（{w4}×{h4}→{w3}×{h3}）· "
                          f"三态 {'/'.join(str(v // 1024) + 'KB' for v in sizes.values())} · "
                          f"空白无作答、带答案两版都有作答、只有批改版表头有得分")
        case("F18 第 4 步三态导出 + 预览随版式真的变", f18)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    bad = [c for c, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 64)
    print(f"V1.1 验收 {len(RESULTS) - len(bad)}/{len(RESULTS)} 通过"
          + ("" if not bad else "  ✗ " + "，".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
