# -*- coding: utf-8 -*-
"""成品审计：不问"裁了几张图"，只问"这份卷子的每道题还能不能正常做"。

【做不了】级（必须清零，每条都给题号和证据）
  断号     一个大题里 1、2、4 少了 3 → 有题整道丢了
  空题干   题文为空或只剩标点
  缺图     题干明写"看图/示意图/下面"，可这道题（含上一题共享）一张图都没有
  括号残缺 填空缺半边括号，孩子不知道往哪儿写（补不回来的必须已标待校对）
  题型不符 选择题没选项 / 填空题没空位
【做得别扭】级（尽量清零）
  切边     裁图框外紧贴一片【不是文字的墨】→ 图被切掉一块
  串题     这道题的裁框盖住了【同一页另一道题】的文字行 → 图片和题目不对应
  含题干   裁框把整句题干框进去 → 图里混着题目文字

用法：
  py -3.11 tests/audit_papers.py                    不给参数＝跑 samples/private 全部
  py -3.11 tests/audit_papers.py "D:/我的试卷"      给目录就跑整个目录
  py -3.11 tests/audit_papers.py --no-render        只算不渲染
产物：var/_audit/<卷名>_出卷_p<n>.png —— 逐页成品图，人眼逐页复核用
退出码：还有【做不了】级问题 = 1（可当门禁），否则 0。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np                                               # noqa: E402
import pymupdf                                                   # noqa: E402

from app.extractor import lines as L                             # noqa: E402
from app.extractor.figures import (find_figures, page_source_from_pdf,   # noqa: E402
                                   page_source_from_image)
from app.extractor.rules import extract, flatten_questions       # noqa: E402
from app.layout.options import LayoutOptions                     # noqa: E402
from app.papers.answer_writer import render_answers_pdf          # noqa: E402

OUT = os.path.join(ROOT, "var", "_audit")
K = 100 / 72.0
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

FIG_CUE = re.compile(
    r"如图|看图|右图|左图|下图|上图|上面的图|下面的图|示意图|钟面|数轴|方格|格子图|"
    r"连一连|涂一涂|标一标|在图上|图上的|画一画|照样子|下面各图|这排|这列|观察图片|图片中|"
    r"结合图片|图片上")
# ⚠️ "路线图 / 平面图 / 统计图"这三个词【可能是题目在讲的知识点】，不是"看着那张图作答"：
#    "路线图通常是按照上北下南…绘制的""路线图中不需要有（）"——这类题压根没有配图，
#    把它们报成"缺图"，尺就一直在喊狼来了（实测两份综合实践卷各误报 1—2 条）。
#    所以它们只有再配上"下面/这幅/该图"这种指示词时才算缺图。
FIG_TOPIC = re.compile(r"路线图|平面图|统计图|线路图")
FIG_DEICTIC = re.compile(r"下面|上面|这幅|这张|该图|图中的|图上的|右边的|左边的")
STEMISH = re.compile(r"[。；]|（\s*）|\(\s*\)|^\d+[、.．]|^[（(]\d+[）)]")
ONLY_PUNCT = re.compile(r"^[\s（）()。、，,.．:：;；—…·\d]*$")


def load(path: str) -> dict:
    """一份材料 → 行 + 可裁的页面源。PDF 逐页路由；照片走 OCR。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        r = L.annotated_lines_from_pdf(path, work_dir=os.path.join(OUT, "_ocr"))
        n = pymupdf.open(path).page_count
        srcs = {i: page_source_from_pdf(path, i) for i in range(1, n + 1)}
    elif ext in IMG_EXT:
        r = L.lines_from_image(path)
        srcs = {1: page_source_from_image(path, 1)}
        n = 1
    else:
        return {}
    r["sources"] = {k: v for k, v in srcs.items() if v}
    r["n_pages"] = n
    return r


def _run_len(mask_row) -> int:
    best = run = 0
    for v in mask_row:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def clipped_sides(src, rect, page_boxes, pad_pt=6.0, min_px=45, min_run=18,
                  other_crops=()):
    """裁图框四条边【外侧】贴着多少非文字墨。返回 [(边, 墨px)]。

    ⚠️ 必须先把【别的题已经裁走的图】从这条外边带里挖掉：两张图上下紧挨着时
       （真实卷：周末作业 第 1、2 题的两幅格子图、综合实践单元(1) 第 3、4 题），
       下一张图的墨会贴在上一张裁框外面，尺就报"切边"—— 报的是邻题的图，
       不是被切掉的半张图。九条"切边"里七条是这么来的。
    """
    x0, y0, x1, y1 = [v * K for v in rect]
    p = pad_pt * K
    H, W = src.gray.shape
    out = []
    for side, (bx0, by0, bx1, by1) in {
        "上": (x0, y0 - p, x1, y0 - 1), "下": (x0, y1 + 1, x1, y1 + p),
        "左": (x0 - p, y0, x0 - 1, y1), "右": (x1 + 1, y0, x1 + p, y1),
    }.items():
        bx0, by0 = max(0, int(bx0)), max(0, int(by0))
        bx1, by1 = min(W, int(bx1)), min(H, int(by1))
        if bx1 - bx0 < 2 or by1 - by0 < 2:
            continue
        ink = src.gray[by0:by1, bx0:bx1] < src.ink_thr
        if not ink.any():
            continue
        for (tx0, ty0, tx1, ty1, _t) in page_boxes:
            a, b = max(int(tx0 * K) - bx0, 0), min(int(tx1 * K) - bx0, ink.shape[1])
            c, d = max(int(ty0 * K) - by0, 0), min(int(ty1 * K) - by0, ink.shape[0])
            if b > a and d > c:
                ink[c:d, a:b] = False
        for (ox0, oy0, ox1, oy1) in other_crops:
            a, b = max(int(ox0 * K) - bx0, 0), min(int(ox1 * K) - bx0, ink.shape[1])
            c, d = max(int(oy0 * K) - by0, 0), min(int(oy1 * K) - by0, ink.shape[0])
            if b > a and d > c:
                ink[c:d, a:b] = False
        n = int(ink.sum())
        if n < min_px or max((_run_len(row) for row in ink), default=0) < min_run:
            continue
        out.append((side, n))
    return out


def overlap(a, b) -> float:
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    area = (b[2] - b[0]) * (b[3] - b[1])
    return (ix * iy) / area if area else 0.0


def answerability(qs) -> list[tuple]:
    """【做不了】级检查：逐题问"拿着这张纸能不能作答"。"""
    bad: list[tuple] = []
    sec_no: dict[str, list[int]] = {}
    for q in qs:
        sec_no.setdefault(str(q.get("section") or ""), []).append(int(q.get("q_no") or 0))
    for sec, nos in sec_no.items():
        have = sorted({n for n in nos if n})
        if not have:
            continue
        for miss in range(have[0], have[-1] + 1):
            if miss not in have:
                bad.append(("断号", 0, f"大题「{sec[:14]}」缺第 {miss} 题（实有 {have}）"))
    for i, q in enumerate(qs):
        t = str(q.get("text") or "").strip()
        no = int(q.get("q_no") or i + 1)
        if not t or ONLY_PUNCT.match(t):
            bad.append(("空题干", no, t[:20]))
            continue
        if (t.count("（") + t.count("(")) != (t.count("）") + t.count(")")) \
                and not q.get("needs_review"):
            bad.append(("括号残缺", no, f"没补也没标待校对：…{t[-22:]}"))
        qt = q.get("qtype")
        if qt == "choice" and len(q.get("options") or []) < 2:
            bad.append(("选择没选项", no, t[:24]))
        if qt == "fill" and not int(q.get("blanks") or 0):
            bad.append(("填空没空位", no, t[:24]))
        if not q.get("images") and wants_figure(t, qt):
            prev = qs[i - 1] if i else {}
            shared = bool(prev.get("images")) and re.search(r"上图|上面|如图|图上的", t)
            if not shared:
                bad.append(("缺图", no, t[:26]))
    return bad


def wants_figure(t: str, qt: str = "") -> bool:
    """这道题是不是【必须看着一张图】才能做。"""
    if FIG_CUE.search(t):
        return True
    return bool(FIG_TOPIC.search(t) and FIG_DEICTIC.search(t))


def duplicates(qs) -> list[tuple]:
    """同一大题里同一个题号出现两次 = 卷面上多出一道"假题"。

    典型成因（实测：综合实践单元(1).pdf 第四大题）：题号"1"和它的题干之间隔着整张
    平面图，OCR 把图上的房间号读成一行行文字插在中间，于是"1"被前一段文字带走，
    真正的题干又开了一道"1"。孩子卷面上会看到两道第 1 题，其中一道是乱码。
    """
    seen: dict[tuple, int] = {}
    for i, q in enumerate(qs):
        key = (str(q.get("section") or ""), int(q.get("q_no") or 0))
        if not key[1]:
            continue
        seen[key] = seen.get(key, 0) + 1
    return [(sec, no, n) for (sec, no), n in seen.items() if n > 1]


def selftest() -> list[str]:
    """尺自己要先证明"它会 FAIL"——不然"做不了 0"只说明我把判据写松了。

    每条都是这一轮真实遇到的：正例＝真缺陷必须报，反例＝误报必须不报。
    返回没过的条目（空＝尺还在工作）。
    """
    def q(text, **kw):
        return {"text": text, "q_no": kw.pop("no", 1), "qtype": kw.pop("qt", "essay"),
                "options": kw.pop("opts", []), "blanks": kw.pop("blanks", 0),
                "section": kw.get("sec", "一、填空"), "images": kw.get("imgs") or [],
                "needs_review": kw.get("review", False)}

    def kinds(qs):
        return [k for k, _n, _w in answerability(qs)]

    fails: list[str] = []

    def chk(name, got, want):
        if want is None:
            if got:
                fails.append(f"{name}：尺误报了（got={got}）")
        elif want not in got:
            fails.append(f"{name}：尺没报出【{want}】（got={got}）")

    chk("右图题没图→缺图",
        kinds([q("如右图所示，两名同学玩背靠背夹球跑的游戏。龙龙面向（ ）。")]), "缺图")
    chk("下面…平面图没图→缺图",
        kinds([q("下面是开心小学教学楼2层的平面图，看图回答问题。")]), "缺图")
    chk("路线图是知识点→不该报",
        kinds([q("路线图通常是按照“上北、下（  ）左（  ）右（  ）”来绘制的。",
                 qt="fill", blanks=3)]), None)
    chk("路线图中不需要有什么（选择）→不该报",
        kinds([q("在设计校园路线图时，路线图中不需要有（  ）。", qt="choice",
                 opts=["①路线", "②方向", "③时间"])]), None)
    chk("断号（缺第3题）→要报",
        kinds([q("第一题的题干内容。", no=1), q("第二题的题干内容。", no=2),
               q("第四题的题干内容。", no=4)]), "断号")
    chk("题号连续→不该报",
        kinds([q("第一题的题干内容。", no=1), q("第二题的题干内容。", no=2),
               q("第三题的题干内容。", no=3)]), None)
    chk("括号残缺又没标待校对→要报",
        kinds([q("他的前面是（       )，后面是（", qt="fill", blanks=2)]), "括号残缺")
    chk("选择题没选项→要报",
        kinds([q("下面哪个是对的？（  ）", qt="choice")]), "选择没选项")
    chk("填空题没空位→要报",
        kinds([q("这是一道被误判成填空题的解答题。", qt="fill")]), "填空没空位")

    # 重号尺：同一大题里同一个题号出现两次＝卷面上多出一道假题
    d1 = duplicates([q("第一题的题干内容。", no=1), q("乱码行。", no=1),
                     q("第二题的题干内容。", no=2)])
    if not d1:
        fails.append("重号尺：两道第 1 题却没报（这条尺坏了）")
    d2 = duplicates([q("第一题的题干内容。", no=1), q("第二题的题干内容。", no=2),
                     q("第三题的题干内容。", no=3)])
    if d2:
        fails.append(f"重号尺：题号不重复却报了（误报）：{d2}")

    # 切边尺：紧贴裁框下面的墨如果是【邻题已经裁走的图】，不算"这道题被切掉一块"
    from app.extractor.figures import PageSource
    g = np.full((int(200 * K), int(200 * K)), 255, dtype=np.uint8)
    g[int(100 * K):int(140 * K), int(20 * K):int(120 * K)] = 40      # 这道题的图
    g[int(141 * K):int(150 * K), int(20 * K):int(120 * K)] = 40      # 下面那块墨
    src = PageSource(1, 200.0, 200.0, g, lambda rect, out: None)
    mine = (20.0, 100.0, 120.0, 140.0)
    if not clipped_sides(src, mine, []):
        fails.append("切边尺：框外明明有墨却没报（这条尺坏了，报 0 不算通过）")
    if clipped_sides(src, mine, [], other_crops=[(20.0, 141.0, 120.0, 150.0)]):
        fails.append("切边尺：邻题的图被算成了这道题的「切边」（误报）")
    return fails


def audit(path: str, render=True) -> dict:
    name = os.path.splitext(os.path.basename(path))[0]
    r = load(path)
    if not r or not r.get("lines"):
        print(f"\n【{name}】没读到任何文本行（跳过）")
        return {}
    res = extract(r["lines"], title=name)
    qs = flatten_questions(res)
    spans = L.spans_for_questions(r["ann"], qs, pages=r.get("pages"),
                                  sections=res.get("sections"))
    fig_dir = os.path.join(OUT, "figs", name)
    rep: list = []
    got = find_figures(r["sources"], spans, fig_dir, report=rep, noise=r.get("noise"))
    for qi, imgs in got.items():
        if 0 <= qi < len(qs):
            qs[qi]["images"] = imgs

    by_page: dict[int, list] = {}
    for a in r["ann"]:
        by_page.setdefault(int(a.get("page", 1)), []).append(a)
    boxes = {pg: [(float(a["x"]), float(a["y"]), float(a["x"]) + float(a["w"]),
                   float(a["y"]) + float(a["h"]), str(a.get("text") or ""))
                  for a in items] for pg, items in by_page.items()}
    span_by_q = {int(s["q_index"]): s for s in spans}

    clip, bleed, stem_in = [], [], []
    crops_by_page: dict[int, list] = {}
    for q in qs:
        for im in q.get("images") or []:
            crops_by_page.setdefault(int(im["page"]), []).append(tuple(im["rect"]))
    for qi, q in enumerate(qs):
        for im in q.get("images") or []:
            rect = im["rect"]
            page = int(im["page"])
            if page not in r["sources"]:
                continue
            others = [c for c in crops_by_page.get(page, []) if tuple(c) != tuple(rect)]
            c = clipped_sides(r["sources"][page], rect, boxes.get(page, []),
                              other_crops=others)
            if c:
                clip.append((qi + 1, [f"{s}+{n}px" for s, n in c], [round(v) for v in rect]))
            for qj, sj in span_by_q.items():
                if qj == qi or int(sj.get("page", -1)) != page:
                    continue
                for b in sj.get("text_boxes", []):
                    bb = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
                    if overlap(rect, bb) >= 0.6 and (bb[2] - bb[0]) > 20:
                        bleed.append((qi + 1, qj + 1, str(b.get("text", ""))[:16]))
                        break
            own = span_by_q.get(qi, {}).get("text_boxes") or []
            for bi, b in enumerate(own):
                t = str(b.get("text") or "")
                bb = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
                if len(t) >= 8 and STEMISH.search(t) and overlap(rect, bb) >= 0.8:
                    # 第一行＝题干的起手句，被图整行框住＝印出来重复一行题目；
                    # 后面几行多半是【图自己的标注】（"我站在北面。"），那是图的一部分。
                    stem_in.append((qi + 1, t[:20], "题干首行" if bi == 0 else f"第{bi + 1}行"))
                    break

    bad = answerability(qs)
    dup = duplicates(qs)
    pages_out = 0
    if render:
        os.makedirs(OUT, exist_ok=True)
        pdf = os.path.join(OUT, f"{name}_blank.pdf")
        render_answers_pdf(qs, LayoutOptions.from_dict({"show_header": True}), pdf,
                           title=name, mode="blank", figures_dir=fig_dir)
        d = pymupdf.open(pdf)
        pages_out = d.page_count
        for i, pg in enumerate(d):
            pg.get_pixmap(dpi=110).save(os.path.join(OUT, f"{name}_出卷_p{i + 1}.png"))
        d.close()

    n_img = sum(len(v) for v in got.values())
    cut = [d for d in rep if not d.get("kept")]
    from collections import Counter
    print(f"\n【{name}】源{r['n_pages']}页 · 题{len(qs)} · 配图{n_img}张（带图题{len(got)}）"
          f"· 出卷{pages_out}页 · 待校对{sum(1 for q in qs if q.get('needs_review'))}")
    print(f"  做不了 {len(bad)}　·　做得别扭：切边 {len(clip)} · 串题 {len(bleed)} "
          f"· 含题干 {len(stem_in)} · 重号 {len(dup)}")
    for kind, no, why in bad:
        print(f"    ✗ {kind:6} 第 {no} 题 {why}")
    for sec, no, n in dup:
        print(f"    · 重号   大题「{sec[:14]}」第 {no} 题出现 {n} 次（其中一道多半是乱码假题）")
    for t, c, rr in clip:
        print(f"    · 切边   第 {t} 题 {c} 框{rr}")
    for t, o, s in bleed:
        print(f"    · 串题   第 {t} 题的图盖住第 {o} 题「{s}」")
    for t, s, w in stem_in:
        print(f"    · 含题干 第 {t} 题的图框住「{s}」  {w}")
    print(f"    砍掉的候选：{dict(Counter(d['why'] for d in cut))}")
    return {"name": name, "bad": bad, "clip": clip, "bleed": bleed, "stem": stem_in,
            "dup": dup,
            "pages": pages_out, "questions": len(qs)}


def collect(args: list[str]) -> list[str]:
    out = []
    for a in args:
        p = a if os.path.isabs(a) else os.path.join(ROOT, a)
        if os.path.isdir(p):
            out += [os.path.join(p, f) for f in sorted(os.listdir(p))
                    if f.lower().endswith((".pdf",) + IMG_EXT)]
        elif os.path.isfile(p):
            out.append(p)
        else:
            print("找不到", p)
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    render = "--no-render" not in sys.argv
    os.makedirs(OUT, exist_ok=True)
    bad_ruler = selftest()
    if bad_ruler:
        print("✗ 审计尺本身坏了（这份报告一个字都别信）：")
        for m in bad_ruler:
            print("   ", m)
        return 2
    print("✓ 审计尺自检通过（11 条正/反对照）")
    files = collect(args) or collect([os.path.join(ROOT, "samples", "private")])
    tot = {"bad": 0, "clip": 0, "bleed": 0, "stem": 0, "dup": 0}
    for f in files:
        try:
            a = audit(f, render=render)
        except Exception as e:
            import traceback
            print(f"  审计失败 {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)
            tot["bad"] += 1
            continue
        if not a:
            continue
        tot["bad"] += len(a["bad"])
        for k in ("clip", "bleed", "stem", "dup"):
            tot[k] += len(a[k])
    print(f"\n===== 合计：做不了 {tot['bad']} · 切边 {tot['clip']} · 串题 {tot['bleed']} "
          f"· 含题干 {tot['stem']} · 重号 {tot['dup']} =====")
    print(f"逐页成品图在 {OUT}")
    return 1 if tot["bad"] else 0


if __name__ == "__main__":
    sys.exit(main())
