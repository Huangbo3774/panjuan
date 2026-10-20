# -*- coding: utf-8 -*-
"""配图裁剪的回归测试：横版两栏、大题边界、纯文字反例。

为什么单独一个文件（test_print_formats 里已经有一条配图测试）：
那条是单栏卷，测的是"能不能裁出图"；用户报的 bug 是"裁错了地方"——
横版两张 A4 并排的语文/综合实践卷，右半页的图被框进了左半页的题目里。
单栏夹具对这类错误【天然免疫】，所以必须造两栏夹具。

夹具全部是脚本现画的合成内容（不含任何真实作业），跑完产物落在 var/_figtest/。
"""
from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                      # noqa: E402
from app.extractor.figures import find_figures, page_source_from_pdf  # noqa: E402
from app.extractor.lines import (annotated_lines_from_pdf,           # noqa: E402
                                 spans_for_questions)
from app.extractor.rules import extract, flatten_questions          # noqa: E402

OUT = os.path.join(ROOT, "var", "_figtest")
os.makedirs(OUT, exist_ok=True)
import re as _re                                                       # noqa: E402
ok_n = bad_n = 0

GUTTER = 420.0                       # 两栏的分缝（页面中心）


def t(name, fn):
    global ok_n, bad_n
    try:
        fn()
        ok_n += 1
        print("  PASS " + name)
    except AssertionError as e:
        bad_n += 1
        print(f"  FAIL {name} → {e}")
    except Exception as e:
        import traceback
        bad_n += 1
        print(f"  ERROR {name} → {type(e).__name__}: {e}\n{traceback.print_exc(limit=3)}")


def _txt(page, x, y, s, size=11):
    page.insert_text((x, y), s, fontsize=size, fontname="china-s")


def _compass(page, cx, cy, r):
    """画一个"罗盘"：圆 + 十字 + 斜线，纯图形无文字（图里带字的情况另有测试）。"""
    page.draw_circle((cx, cy), r, color=(0, 0, 0), width=1.2)
    page.draw_line((cx - r, cy), (cx + r, cy), color=(0, 0, 0), width=1.0)
    page.draw_line((cx, cy - r), (cx, cy + r), color=(0, 0, 0), width=1.0)
    page.draw_line((cx - r * .6, cy - r * .6), (cx + r * .6, cy + r * .6),
                   color=(0, 0, 0), width=0.8)
    page.draw_polyline([(cx, cy - r * .55), (cx + r * .18, cy), (cx, cy + r * .55),
                        (cx - r * .18, cy), (cx, cy - r * .55)],
                       color=(0, 0, 0), width=0.9, fill=(0.75, 0.75, 0.75))


def _grid(page, x0, y0, x1, y1):
    """画一个"平面图"：外框 + 内部几条路。"""
    page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=1.2)
    for i in range(1, 4):
        page.draw_line((x0 + (x1 - x0) * i / 4, y0), (x0 + (x1 - x0) * i / 4, y1),
                       color=(0, 0, 0), width=0.7)
    for j in range(1, 3):
        page.draw_line((x0, y0 + (y1 - y0) * j / 3), (x1, y0 + (y1 - y0) * j / 3),
                       color=(0, 0, 0), width=0.7)


def make_two_column(figures=True) -> str:
    """横版两栏：左栏第一大题（带罗盘图），右栏第二大题（带平面图）。"""
    path = os.path.join(OUT, "两栏卷.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=840, height=600)
    _txt(page, 300, 36, "综合实践达标练习", size=15)
    # 左栏
    _txt(page, 30, 70, "一、看图填方向。")
    _txt(page, 30, 100, "1. 小明站在操场中央，他的前面是北，")
    _txt(page, 30, 118, "后面是（   ）。")
    if figures:
        _compass(page, 120, 200, 46)
    _txt(page, 30, 300, "2. 图书馆在医院的东面，医院的南面")
    _txt(page, 30, 318, "是（   ）。")
    # 右栏
    _txt(page, 450, 70, "二、看图计算。")
    _txt(page, 450, 100, "3. 根据右面的平面图，商场在公园的")
    _txt(page, 450, 118, "（   ）面。")
    if figures:
        _grid(page, 470, 150, 640, 270)
    _txt(page, 450, 300, "4. 公园一圈长 120 米，小明走半圈是")
    _txt(page, 450, 318, "（   ）米。")
    doc.save(path)
    doc.close()
    return path


def run(path: str):
    r = annotated_lines_from_pdf(path)
    res = extract(r["lines"], title="")
    qs = flatten_questions(res)
    spans = spans_for_questions(r["ann"], qs, pages=r["pages"], sections=res["sections"])
    src = page_source_from_pdf(path, 1)
    got = find_figures({1: src}, spans, OUT)
    return r, res, qs, spans, got


def two_column_crops_stay_in_their_own_column():
    """核心回归：左栏的题绝不能框到右栏的图。"""
    r, res, qs, spans, got = run(make_two_column())
    assert len(qs) >= 4, f"夹具没切成 4 道题：{[q['text'][:12] for q in qs]}"
    # 每题的 span 必须带栏边界，且不能是整页宽
    for s in spans:
        w = s["x1"] - s["x0"]
        assert w < 840 * 0.75, f"q{s['q_index']} 的栏宽 {w:.0f}pt ≈ 整页宽，等于没分栏"
        assert s["y1"] > s["y0"], f"q{s['q_index']} 区间倒挂 y0={s['y0']:.0f} y1={s['y1']:.0f}"
    left = [s for s in spans if s["col"] == 0]
    right = [s for s in spans if s["col"] == 1]
    assert left and right, f"两栏没分开：col 分布 {[s['col'] for s in spans]}"
    # 裁出来的每张图都必须整个落在自己那一栏里
    seen = 0
    for qi, lst in got.items():
        sp = next((s for s in spans if s["q_index"] == qi), None)
        assert sp, f"q{qi} 有图但没有 span？"
        for im in lst:
            seen += 1
            x0, _y0, x1, _y1 = im["rect"]
            assert x0 >= sp["x0"] - 6 and x1 <= sp["x1"] + 6, (
                f"第 {qi + 1} 题的配图跨出了所属栏：图 [{x0:.0f},{x1:.0f}] "
                f"栏 [{sp['x0']:.0f},{sp['x1']:.0f}]")
    assert seen >= 2, f"两栏各有一张图，却只裁出 {seen} 张：{got}"
    # 每栏这道题【只有】一张图：探测带一旦退回整页宽，隔壁栏的图会被当成
    # "本题的第二张图"裁进来（栏边界裁剪只会把它切窄，不会让它消失），
    # 所以只断言"没跨栏"抓不到它，必须连张数一起钉。
    for qi, lst in got.items():
        assert len(lst) == 1, (f"第 {qi + 1} 题裁出 {len(lst)} 张，本夹具每题只该有 1 张："
                               + str([i["rect"] for i in lst]))
    # 左栏题的图必须整体在分缝左边，右栏题的图必须整体在分缝右边
    for qi, lst in got.items():
        sp = next(s for s in spans if s["q_index"] == qi)
        for im in lst:
            if sp["col"] == 0:
                assert im["rect"][2] < GUTTER + 30, f"左栏第 {qi + 1} 题的图伸到了右栏：{im['rect']}"
            else:
                assert im["rect"][0] > GUTTER - 30, f"右栏第 {qi + 1} 题的图伸到了左栏：{im['rect']}"


def pure_text_two_column_crops_nothing():
    """反例：两栏纯文字卷一张图都不许裁出来。
    没有这条，"把文字行当图"的退化会被上面那条测试一起放过。"""
    path = os.path.join(OUT, "两栏纯文字.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=840, height=600)
    _txt(page, 30, 70, "一、填空。")
    for i in range(4):
        _txt(page, 30, 100 + i * 22, f"{i + 1}. 这是第 {i + 1} 道题的文字，没有图形。")
    _txt(page, 450, 70, "二、判断。")
    for i in range(4):
        _txt(page, 450, 100 + i * 22, f"{i + 5}. 这也是纯文字题目 {i + 5}。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    assert len(qs) >= 8, f"纯文字夹具题数不对：{len(qs)}"
    assert not got, f"纯文字卷裁出了 {sum(len(v) for v in got.values())} 张废图：" + \
        str({k: [(i['rect'], i['w_pt'], i['h_pt']) for i in v] for k, v in got.items()})


def section_header_is_a_wall():
    """大题题头是硬墙：上一题的图不能伸到下一个大题里，
    共享图挂在它下面第一道小题上（用户："一定要先识别大题号，把一个大题的图截在一起"）。"""
    path = os.path.join(OUT, "大题墙.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _txt(page, 40, 50, "单栏卷")
    _txt(page, 40, 80, "一、填空。")
    _txt(page, 40, 110, "1. 第一小题的题干文字。")
    _compass(page, 120, 175, 40)                      # 属于第 1 题
    _txt(page, 40, 260, "二、看图计算。")
    _grid(page, 60, 285, 220, 385)                    # 属于第二大题
    _txt(page, 40, 420, "2. 第二小题的题干文字。")
    doc.save(path)
    doc.close()
    r = annotated_lines_from_pdf(path)
    res = extract(r["lines"], title="")
    qs = flatten_questions(res)
    spans = spans_for_questions(r["ann"], qs, pages=r["pages"], sections=res["sections"])
    src = page_source_from_pdf(path, 1)
    got = find_figures({1: src}, spans, OUT)
    assert len(qs) >= 2, f"没切出题：{[q['text'][:10] for q in qs]}"
    # 第 1 题 = q_index 0：它的区间必须停在"二、"题头之前（题头是墙）
    sp0 = next(s for s in spans if s["q_index"] == 0)
    assert sp0["y1"] <= 262, f"第 1 题的区间越过了大题题头（y1={sp0['y1']:.0f} > 260）"
    for im in got.get(0, []):
        assert im["rect"][3] <= 262, f"第 1 题裁到了下一个大题里：{im['rect']}"
    # 第二大题的共享图必须挂在它下面第一道小题（第 2 题 = q_index 1）上
    boxes = [im["rect"] for im in got.get(1, [])]
    assert any(b[1] > 270 and b[3] < 400 for b in boxes), \
        f"第二大题的共享图没挂到它的第一道小题上：q2 拿到 {boxes}"
    # 反向：这张共享图绝不能同时挂在第 1 题上（一个大题的图只截一次）
    for im in got.get(0, []):
        assert not (im["rect"][1] > 270), f"共享图被上一题也裁走了一份：{im['rect']}"


def figure_with_labels_inside_is_kept():
    """图里带字（"北""东"这类标注）时不能因为"有文字"就把整张图判掉。"""
    path = os.path.join(OUT, "图里带字.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _txt(page, 40, 50, "一、看图填方向。")
    _txt(page, 40, 80, "1. 根据图上的方向填一填。")
    _compass(page, 150, 200, 55)
    _txt(page, 145, 140, "北")                        # 标注字压在图形里
    _txt(page, 145, 268, "南")
    doc.save(path)
    doc.close()
    r = annotated_lines_from_pdf(path)
    res = extract(r["lines"], title="")
    qs = flatten_questions(res)
    spans = spans_for_questions(r["ann"], qs, pages=r["pages"], sections=res["sections"])
    src = page_source_from_pdf(path, 1)
    got = find_figures({1: src}, spans, OUT)
    n = sum(len(v) for v in got.values())
    assert n >= 1, f"图里带标注字就把图判没了：{got}"
    big = [im for lst in got.values() for im in lst if im["w_pt"] > 60 and im["h_pt"] > 60]
    assert big, f"裁出来的不是那张罗盘（尺寸都对不上）：{[i['rect'] for l in got.values() for i in l]}"


def two_figures_in_one_question_stay_two():
    """一道题里有两张分开的图（两个钟面 / 两面旗）时必须出【两张】。
    旧实现是"剩余墨的总外接盒"，会把两张图连中间一大片空白并成一个巨框 ——
    用户看到的就是一张横跨半页的怪图。这条测试专门盯它。"""
    path = os.path.join(OUT, "一题两图.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _txt(page, 40, 50, "一、看图填空。")
    _txt(page, 40, 80, "1. 下面两个钟面，各是几时？")
    _compass(page, 110, 170, 42)                     # 左图
    _compass(page, 430, 170, 42)                     # 右图，和左图隔 220pt
    _txt(page, 40, 280, "2. 第二题的题干。")
    doc.save(path)
    doc.close()
    r = annotated_lines_from_pdf(path)
    res = extract(r["lines"], title="")
    qs = flatten_questions(res)
    spans = spans_for_questions(r["ann"], qs, pages=r["pages"], sections=res["sections"])
    src = page_source_from_pdf(path, 1)
    got = find_figures({1: src}, spans, OUT)
    imgs = got.get(0, [])
    assert len(imgs) == 2, f"两张分开的图应该出两张，实际出了 {len(imgs)} 张：{[i['rect'] for i in imgs]}"
    for im in imgs:
        w = im["rect"][2] - im["rect"][0]
        assert w < 140, f"单张图宽 {w:.0f}pt，明显是把两张图连中间空白并成了一个大框：{im['rect']}"
    xs = sorted(im["rect"][0] for im in imgs)
    assert xs[1] - xs[0] > 200, f"两张图没分开落在各自位置上：{xs}"


def figures_actually_land_in_the_pdf():
    """配图必须【真的印进 PDF】——三态各查一遍。

    这条是被用户逼出来的：库里存的是 `name`，而渲染只读 `path`，
    于是屏幕上看得见配图、打印出来一张都没有，而且一声不吭。
    以前的测试只查"裁出来有没有墨"，从没查"PDF 里有没有这张图"。
    """
    from app.layout.options import LayoutOptions
    from app.papers.answer_writer import render_answers_pdf

    fig_dir = os.path.join(OUT, "figs")
    os.makedirs(fig_dir, exist_ok=True)
    png = os.path.join(fig_dir, "p1_q0_1.png")
    d = pymupdf.open()
    pg = d.new_page(width=160, height=90)
    pg.draw_circle((80, 45), 34, color=(0, 0, 0), width=1.5, fill=(0.85, 0.85, 0.85))
    pg.draw_line((46, 45), (114, 45), color=(0, 0, 0), width=1.2)
    # 必须走 pixmap 才是真 PNG：Document.save("x.png") 存的是 PDF 字节，
    # reportlab 读不了，测试会以"图片缺失"失败（我自己先踩了一次）
    pg.get_pixmap(dpi=150).save(png)
    d.close()
    assert open(png, "rb").read(4) == b"\x89PNG", "夹具生成的不是真 PNG"

    qs = [{"uid": "一#1", "q_no": 1, "section": "一、看图填空。", "qtype": "fill",
           "text": "1. 看图填空，钟面上是（  ）时。", "options": [], "score": 2,
           "blanks": 1, "images": [{"name": "p1_q0_1.png", "page": 1,
                                    "w_pt": 160.0, "h_pt": 90.0}]}]
    for mode in ("answered", "graded"):
        out = os.path.join(OUT, f"印图_{mode}.pdf")
        r = render_answers_pdf(qs, LayoutOptions.from_dict({"show_header": True}), out,
                               title="印图检查卷", mode=mode,
                               answers={"一#1": "3"}, key={"一#1": "3"},
                               grade_result={"score": 2, "total": 2,
                                             "counts": {"correct": 1, "wrong": 0, "pending": 0},
                                             "results": [{"uid": "一#1", "verdict": "correct"}]}
                               if mode == "graded" else None,
                               figures_dir=fig_dir)
        doc = pymupdf.open(out)
        n = sum(len(p.get_images(full=True)) for p in doc)
        doc.close()
        assert n >= 1, f"{mode} 版 PDF 里内嵌图片 0 张——配图没印上去（用户报的就是这个）"
        assert r.get("figures_drawn", 0) >= 1, f"{mode} 版没记到画了图：{r}"
        assert r.get("figures_missing", 0) == 0, f"{mode} 版有图被跳过：{r}"

    # 反例：图片文件不存在时，必须【报出来】而不是悄悄少印
    r2 = render_answers_pdf(qs, LayoutOptions.from_dict({}), os.path.join(OUT, "印图_缺文件.pdf"),
                            title="印图检查卷", mode="answered", answers={}, key={},
                            figures_dir=os.path.join(OUT, "没有这个目录"))
    assert r2.get("figures_missing") == 1 and r2.get("figures_drawn") == 0, \
        f"图丢了却没报数：{r2}"


def footer_page_total_matches_when_figures_take_space():
    """页脚"共 N 页"必须等于真实页数 —— 配图占版面，第一趟数页数时也要带上图。

    真实事故：九份卷全部出现"共 4 页"的页脚而 PDF 实际有 5 页。
    根因是数页数那一趟没传 fig_dir，配图被跳过 → 版面偏短 → 页数少算一页。
    """
    from app.layout.options import LayoutOptions
    from app.papers.answer_writer import render_answers_pdf

    fig_dir = os.path.join(OUT, "figs2")
    os.makedirs(fig_dir, exist_ok=True)
    png = os.path.join(fig_dir, "p1_q0_1.png")
    d = pymupdf.open()
    pg = d.new_page(width=300, height=260)
    pg.draw_rect(pymupdf.Rect(10, 10, 290, 250), color=(0, 0, 0), width=1.5)
    pg.get_pixmap(dpi=150).save(png)
    d.close()
    qs = [{"uid": f"一#{i}", "q_no": i, "section": "一、看图填空。", "qtype": "fill",
           "text": f"{i}. 看图列式，结果是（  ）。" + "这是一段用来占行的题干文字。" * 3,
           "options": [], "score": 2, "blanks": 1,
           "images": [{"name": "p1_q0_1.png", "page": 1, "w_pt": 300.0, "h_pt": 260.0}]}
          for i in range(1, 9)]
    out = os.path.join(OUT, "页脚总页数.pdf")
    render_answers_pdf(qs, LayoutOptions.from_dict({"show_header": True}), out,
                       title="页脚检查卷", mode="blank", figures_dir=fig_dir)
    doc = pymupdf.open(out)
    real = doc.page_count
    assert real >= 2, f"夹具没铺到两页以上，测不到跨页：{real} 页"
    bad = []
    for i, p in enumerate(doc, start=1):
        t = p.get_text().replace(" ", "")
        m = _re.search(r"共(\d+)页", t)
        if not m or int(m.group(1)) != real:
            bad.append((i, m.group(1) if m else None))
    doc.close()
    assert not bad, (f"页脚写的「共 N 页」和真实页数 {real} 不一致"
                     f"（第几页, 页脚写的）：{bad}")


def fake_gutter_from_figure_is_rejected():
    """图形自己占的地方没有文字框，只看文本投影会把它当成"栏缝"。

    真实事故：综合实践单元.pdf 第 1 页只有一条真缝（403–462pt），
    但文本投影切出了 4 栏 → 一张图被劈开、左侧竖排装订栏自成一栏，
    裁出 55 张碎片把 2 页卷子撑成 11 页。现在栏界要用页面墨迹复核。
    """
    path = os.path.join(OUT, "假栏缝.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=840, height=600)
    _txt(page, 30, 60, "一、看图填空。")
    _txt(page, 30, 90, "1. 第一题的题干。")
    _compass(page, 200, 200, 60)                     # 左栏一张大图：它占的地方没有文字
    _txt(page, 30, 320, "2. 第二题的题干。")
    _txt(page, 450, 60, "二、计算。")
    _txt(page, 450, 90, "3. 第三题的题干。")
    _txt(page, 450, 120, "4. 第四题的题干。")
    _txt(page, 450, 150, "5. 第五题的题干。")
    doc.save(path)
    doc.close()
    r = annotated_lines_from_pdf(path)
    bands = r["pages"][0]["bands"]
    assert len(bands) == 2, (f"应当是左右两栏，实际判成 {len(bands)} 栏："
                             f"{[(round(b['x0']), round(b['x1'])) for b in bands]}"
                             "（图形占位被当成了栏缝）")
    seam = bands[1]["x0"]
    # 断言"真正要紧的性质"而不是某个具体坐标：缝不许穿过任何文字框，
    # 也不许把那张罗盘图劈成两半（写死数值会因夹具行宽而假失败，踩过）
    crossing = [a for a in r["ann"] if int(a["page"]) == 1
                and float(a["x"]) < seam - 2 and float(a["x"] + a["w"]) > seam + 2]
    assert not crossing, f"栏缝 {seam:.0f}pt 穿过了 {len(crossing)} 个文字框：{[c['text'][:14] for c in crossing[:3]]}"
    assert 260 < seam < 450, f"栏缝落在内容里了：{seam:.0f}（左栏内容止于 ~260，右栏起于 450）"
    res = extract(r["lines"], title="")
    spans = spans_for_questions(r["ann"], flatten_questions(res), pages=r["pages"],
                                sections=res["sections"])
    src = page_source_from_pdf(path, 1)
    got = find_figures({1: src}, spans, OUT)
    for qi, lst in got.items():
        for im in lst:
            assert im["w_pt"] < 420, f"q{qi + 1} 的图宽 {im['w_pt']:.0f}pt 超过半页，疑似跨栏大框"
            x0, x1 = im["rect"][0], im["rect"][2]
            assert not (x0 < seam - 4 < x1), f"q{qi + 1} 的图被栏缝劈开：[{x0:.0f},{x1:.0f}] 缝 {seam:.0f}"


def _base(page, x=40, y=50, s="一、看图回答问题。"):
    _txt(page, x, y, s)


def _labelled_grid(page, ox=60, oy=120, cols=3, rows=3, bw=60, bh=25,
                   gx=12, gy=20) -> tuple[float, float, float, float]:
    """画一张"格子 + 格子里的字 + 格子间的连线"的平面图，返回它的外接框。

    这就是用户截图那张 实践基地平面示意图 的结构：每个格子里都有字，
    格子之间用短线连起来。字会被 OCR 读成整行 → 被挖掉 → 连线跟着断 →
    一张图就裂成左右两半（用户原话"你把应该一页的弄成多页了"）。

    ⚠️ 列间距 gx 故意只留 12pt：格子拉开到 20pt 以上时，字与字之间的空白会被
       分栏检测当成一条"栏缝"（真实卷上靠图框线压住），图会被从中间劈成两栏 ——
       那是分栏那条规则的事，别混进这条测试。
    """
    names = ["西瓜基地", "葡萄基地", "草莓基地", "梨园", "蔬菜基地", "苹果基地",
             "樱桃基地", "蜜桃基地", "大门"]
    n = 0
    for r in range(rows):
        for c in range(cols):
            x0, y0 = ox + c * (bw + gx), oy + r * (bh + gy)
            page.draw_rect(pymupdf.Rect(x0, y0, x0 + bw, y0 + bh), color=(0, 0, 0), width=1.0)
            _txt(page, x0 + 8, y0 + bh - 8, names[n % len(names)])
            n += 1
            if c + 1 < cols:                      # 横向连线（会被上面那行字挖断）
                page.draw_line((x0 + bw, y0 + bh / 2), (x0 + bw + gx, y0 + bh / 2),
                               color=(0, 0, 0), width=1.0)
        if r + 1 < rows:                          # 纵向连线
            page.draw_line((ox + bw / 2, oy + r * (bh + gy) + bh),
                           (ox + bw / 2, oy + (r + 1) * (bh + gy)), color=(0, 0, 0), width=1.0)
    return (ox, oy, ox + cols * bw + (cols - 1) * gx, oy + rows * bh + (rows - 1) * gy)


def one_diagram_is_not_cut_into_pieces():
    """核心回归（用户截图）：一张带格子字的平面图必须裁成【一张】，而且整张都在。"""
    path = os.path.join(OUT, "格子平面图.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 下面是开心小学实践基地的平面示意图，看图回答问题。")
    box = _labelled_grid(page)
    _txt(page, 40, 300, "2. 大门在蔬菜基地的（   ）面。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    imgs = [im for lst in got.values() for im in lst]
    assert len(imgs) == 1, (f"一张平面图被切成了 {len(imgs)} 块（用户报的就是这个）："
                            + str([i["rect"] for i in imgs]))
    x0, y0, x1, y1 = imgs[0]["rect"]
    assert x0 <= box[0] + 4 and x1 >= box[2] - 4, f"图没盖满整张：{imgs[0]['rect']} vs 实际 {box}"
    assert y0 <= box[1] + 4 and y1 >= box[3] - 4, f"图缺了上下几行：{imgs[0]['rect']} vs 实际 {box}"


def one_diagram_cut_by_its_own_label_row():
    """一张图被它自己那行标签切成上下两块 —— 必须补回一张。

    这是用户截图那张平面示意图的成因最小复现：格子里的字会被 OCR 读成整行，
    裁图前要把文字行从墨迹里挖掉，于是这一行字【横穿图框】，把一张图切成上下两条。
    补洞合并（_bridge）的判据是"这道缝是我们自己挖的"，缝里全是挖掉的文字 → 并回去。

    ⚠️ 夹具要点：字要压在图框【中间】（不是格子里），上下两截的间距 15pt
       必须大于近邻合并半径 MERGE_GAP_PT=14pt，否则这条测试会被邻近合并顺手做掉，
       补洞规则关掉也照样全绿（我就先写错过一版这样的假测试）。
    """
    path = os.path.join(OUT, "被自己标签行切开的图.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 下面是实践基地的平面示意图，看图回答问题。")
    page.draw_rect(pymupdf.Rect(60, 150, 240, 230), color=(0, 0, 0), width=1.2)
    page.draw_line((60, 190), (240, 190), color=(0, 0, 0), width=0.8)     # 图里的一条路
    # 字要【横跨图框左右两条边】、而且行高要把上下两截的间距拉开到 14pt（近邻合并半径）以上：
    #   · 从 x=56 起笔，挖掉的行框才盖得住 x=60 那条左边线（从 70 起笔时左边线没断，
    #     整张图还是一个连通块，把补洞规则整条关掉测试照样绿 —— 第一版就假在这里）；
    #   · 20pt 字号 → 行框 ≈27pt 高，上下两截差 27pt > 14pt，只能靠补洞合并并回去。
    _txt(page, 56, 196, "西瓜基地        葡萄基地        草莓基地", size=20)
    _txt(page, 40, 300, "2. 大门在蔬菜基地的（   ）面。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    imgs = [im for lst in got.values() for im in lst]
    assert len(imgs) == 1, (f"一张图被切成 {len(imgs)} 块（用户原话：应该一页的弄成多页）："
                            + str([i["rect"] for i in imgs]))
    x0, y0, x1, y1 = imgs[0]["rect"]
    assert y0 <= 153 and y1 >= 227, f"补回来的图不完整：{imgs[0]['rect']}"
    assert x0 <= 63 and x1 >= 237, f"补回来的图缺左右：{imgs[0]['rect']}"


def clipped_top_label_row_is_absorbed():
    """图顶那行被挖掉的标签必须吸回来，否则裁出来的图缺第一行。

    坐标全部取自真实卷实测（综合实践课.pdf 第 3 页 第 3 题"实践基地平面示意图"，
    就是用户截图那张）：区间顶 y=386 是题干行，图剩下的墨从 y=427 才开始，
    而第一行标签"西瓜基地—葡萄基地—草莓基地"印在 412–428 —— 不吸回来，
    裁出来的图就把这一行切成半截。

    ⚠️ 这条做成"直接喂坐标的判定单测"而不是端到端夹具：合成 PDF 的字宽和扫描卷
       不是一回事（试过画格子图，结果格子被分栏检测从中间劈开，测的已经不是这条规则）。
    """
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    def px(x0, y0, x1, y1):        # pt → 探测像素，原点 = 区间左上角（y=386）
        return [x0 * k, (y0 - 386) * k, x1 * k, (y1 - 386) * k]

    box = px(165, 427, 398, 490)                      # 补洞之后剩下的墨
    rows = [px(30, 386, 388, 402),                    # 区间第一行＝题干 → 永不吸
            px(169, 412, 400, 428),                   # 图自己的第一行标签 → 该吸
            px(315, 431, 438, 447)]                   # 第二行右侧的标签：伸到图外 → 不吸
    got = FG._absorb_label_rows(list(box), rows, k)
    assert abs(got[1] / k + 386 - 412) < 1.5, (
        f"顶行标签没吸回来（图会缺第一行）：吸完 y0={got[1] / k + 386:.1f}，应为 412")
    assert got[0] / k + 386 > 380, "把题干行也吸进来了（图里会混进题目文字）"
    assert got[3] / k + 386 < 495, f"往下乱长：{got}"

    # 反例：只有题干行贴着图顶时，一行都不许吸
    only_stem = FG._absorb_label_rows(list(px(165, 427, 398, 490)), [rows[0]], k)
    assert only_stem == list(box), f"题干行被吸进图里了：{only_stem}"

    # 单独钉"区间第一行永不吸"这一条：把题干行画成【和图同宽、正好贴着图顶】，
    # 这时贴边/宽度/范围三条全都拦不住它，只有这一条拦得住（少了它，题干会进图）。
    tight = px(165, 406, 398, 470)
    first_row = px(165, 386, 398, 402)
    got2 = FG._absorb_label_rows(list(tight), [first_row], k)
    assert abs(got2[1] - tight[1]) < 1e-6, f"区间第一行（题干）被吸进图里：{got2}"


def page_margin_strip_is_not_a_figure():
    """左侧竖排装订栏（学校/班级/姓名/学号）不许当配图。"""
    path = os.path.join(OUT, "装订栏.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 看图填方向。")
    _compass(page, 300, 200, 52)                      # 真图
    page.draw_rect(pymupdf.Rect(8, 120, 40, 330), color=(0, 0, 0), width=1.0)
    for i, s in enumerate("学校班级姓名学号"):        # 竖排，每字一行
        _txt(page, 16, 140 + i * 21, s)
    # 第二形状：齐着【物理页边】的一小坨（真实卷上是装订线被 ±3pt 外扩后顶到 x=0）。
    # 它 42×34，长宽比 0.8 —— "窄长条"那条判据（要求高 ≥1.5 倍宽）挡不住它，
    # 必须靠"齐页边的窄框"这一条。缺了这块夹具，那条判据就是空转的。
    _blob(page, 3.0, 400.0, 45.0, 434.0)
    _txt(page, 40, 400, "2. 第二题的题干文字。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    imgs = [im for lst in got.values() for im in lst]
    assert imgs, "装订栏卷上一张图都没裁出来，说明夹具或探测坏了"
    bad = [im for im in imgs if im["rect"][2] < 60]
    assert not bad, f"装订栏被当成配图裁了：{[i['rect'] for i in bad]}"
    assert any(i["rect"][0] > 200 for i in imgs), f"真图反而没裁到：{[i['rect'] for i in imgs]}"


def flush_edge_sidebar_composite_is_not_a_figure():
    """贴物理页边的复合块（侧栏色块 + 栏目横幅 + 题干碎字）不是图。

    坐标取自真实卷（第三单元练习题.pdf 第 2 页第 1 题）：蓝色"第三单元"侧栏
    被 ±3pt 外扩顶到 x=0，又和橙色"第二步 练变式"横幅、题干碎字连成
    88×125 的一坨。宽 88 > MARGIN_MAX_W_PT(60)，长宽比 125/88=1.42 < 1.5，
    两条旧判据都【差一点】放它过去，用户截图里就是这块 88×125 的左栏残片。

    ⚠️ 直接喂坐标：合成卷里画不出"侧栏贴边 + 横幅 + OCR 碎字连成一块"的
       真实复合几何，端到端夹具只会造出自证的假绿。
    """
    import app.extractor.figures as FG
    page_w = 595.0
    assert FG._is_margin_strip((0.0, 142.4, 88.0, 267.2), page_w), \
        "88×125 左栏残片又会被当成配图裁出来"
    assert FG._is_margin_strip((507.0, 142.4, 595.0, 267.2), page_w), \
        "右页边对称的一块（横版卷的右半页）也得挡住"

    # 反例①：同样 88×125，但离页边 20pt —— 不是装订栏/侧栏，得按真图对待
    assert not FG._is_margin_strip((20.0, 142.4, 108.0, 267.2), page_w), \
        "把离页边 20pt 的中等块误砍了（真图会丢）"
    # 反例②：贴页边但太宽 —— 100pt 是"窄条"上限，不是"贴边就砍"
    assert not FG._is_margin_strip((0.0, 142.4, 150.0, 300.0), page_w), \
        "贴页边的真图被宽度闸误砍：150×158"


def run_multi(path: str):
    """多页版：`run()` 只喂了第 1 页，跨页判据（页上家具）在它里面【永远测不到】。"""
    r = annotated_lines_from_pdf(path)
    res = extract(r["lines"], title="")
    qs = flatten_questions(res)
    spans = spans_for_questions(r["ann"], qs, pages=r["pages"], sections=res["sections"])
    d = pymupdf.open(path)
    n = d.page_count
    d.close()
    srcs = {i: page_source_from_pdf(path, i) for i in range(1, n + 1)}
    got = find_figures({k: v for k, v in srcs.items() if v}, spans, OUT)
    return r, res, qs, spans, got


def repeated_page_furniture_is_not_a_figure():
    """每页同一位置都印一遍的东西（页脚 logo / 二维码）是页上家具，不是题图。"""
    path = os.path.join(OUT, "页脚logo.pdf")
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        _base(page)
        # ⚠️ 每页都得有一道"像样的题"：只写一句"第 N 页的题干文字"会被切题阶段
        #    当成标题/噪声丢掉 → 那一页没有 span → 那张页的图根本不会被考虑 →
        #    "logo 没被裁出来"就以【空转】的方式报绿（这次正对照抓到的就是它）。
        _txt(page, 40, 90, f"{i + 1}. 看图填一填，把方向填在括号里，这一页共有两道题。")
        for r in range(6):                            # 一块密排小方格＝二维码
            for c in range(6):
                page.draw_rect(pymupdf.Rect(490 + c * 9, 780 + r * 9,
                                            490 + c * 9 + 8, 780 + r * 9 + 8),
                               color=(0, 0, 0), width=1.0, fill=(0.2, 0.2, 0.2))
        # 两页结构必须【完全对称】：页脚再多一行文字，两页的题目锚点就会不一样，
        # 同一块 logo 在两页被切出不同高度 → "跨页重复"对不上 → 测试假失败。
        _compass(page, 300 if i == 0 else 150, 300 if i == 0 else 520, 52)
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run_multi(path)
    all_imgs = [im for lst in got.values() for im in lst]
    # 正对照：夹具上那张真图（第 1 页的罗盘）必须裁得出来。
    # 没有这一条，"题被识别成 0 道 → 一张图都没有 → 断言空转"也会报绿（这次就撞上了）。
    assert any(im["rect"][0] < 400 and im["rect"][1] < 400 for im in all_imgs), \
        f"夹具里的真图没裁出来，这条测试是空转：{[i['rect'] for i in all_imgs]}"
    near = [im for im in all_imgs
            if abs(im["rect"][0] - 490) < 20 and abs(im["rect"][1] - 780) < 20]
    assert not near, f"每页都印的页脚 logo 被当成配图：{[i['rect'] for i in near]}"


def number_line_survives_text_residual_rule():
    """数轴＝"又长又扁、正好压在文字行上"的东西，必须活着。
    它是"文字残影"那条规则的天然反例：规则只看位置就会把数轴一起砍掉。"""
    path = os.path.join(OUT, "数轴.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 在数轴上标出下面的数。")
    page.draw_line((60, 200), (500, 200), color=(0, 0, 0), width=1.4)
    for i in range(10):
        x = 60 + i * 48.9
        page.draw_line((x, 194), (x, 206), color=(0, 0, 0), width=1.2)
        _txt(page, x - 6, 188, str(i * 2))
    _txt(page, 40, 300, "2. 第二题的题干文字。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    wide = [im for lst in got.values() for im in lst if im["w_pt"] > 300]
    assert wide, f"数轴被当噪声砍了（本模块最早踩过的坑）：{got}"


def cap_keeps_the_biggest_not_the_topmost():
    """一题图数超上限时，必须【先挑大的再排阅读顺序】。
    按 y 截断的真实后果：第三单元练习题 第 5 题的 453×109 大图被三个小方块挤掉。"""
    import app.extractor.figures as FG
    path = os.path.join(OUT, "限量挑大的.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 看图列式。")
    for i in range(3):                                # 三个小图，靠上
        # 间隔 170pt：实测钟面墨宽约 74pt，缝隙约 96pt > 横向缝合的 80pt 上限，
        # 三张才会保持分开。间距一旦收到 80pt 以内，横向缝合会把它们并成一张
        # 374×74 的长条 —— 限量那条判据就没有"多个候选抢上限"的场景可测了
        # （第一版就是 120pt 间距被并了，导致"按 y 截断"的破坏测不出来）。
        _compass(page, 90 + i * 170, 165, 30)
    _grid(page, 60, 260, 510, 370)                    # 一张大图，靠下
    _txt(page, 40, 430, "2. 第二题的题干文字。")
    doc.save(path)
    doc.close()
    old = FG.MAX_PER_QUESTION
    FG.MAX_PER_QUESTION = 2                           # 故意收紧上限，逼限量逻辑表态
    try:
        _r, _res, qs, spans, got = run(path)
    finally:
        FG.MAX_PER_QUESTION = old
    imgs = [im for lst in got.values() for im in lst]
    assert imgs, "限量之后一张都不剩，说明挑错了"
    biggest = max(imgs, key=lambda i: i["w_pt"] * i["h_pt"])
    assert biggest["w_pt"] > 300, (
        f"大图被小图挤掉了（限量按 y 截断的老毛病）：{[(i['w_pt'], i['h_pt']) for i in imgs]}")


def text_line_residual_is_not_a_figure():
    """没挖干净的一行字不许当配图 —— 但"又长又扁"的真图（数轴）必须活着。

    坐标取自真实卷（综合实践课.pdf 第 3 页 第 4 题）：那行
    "再向东走到家；欢欢先向西走，再" 的 OCR 框在 y 623–640，字实际印在 638–652，
    差整整一行高 → 笔画留在原地被膨胀半径连成 242×14 的"图"，一题凭空多两张废图。
    反例是数轴：同样扁、同样正好压在文字行上，靠"框内有没有一根长横线"分开。
    """
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    def px(x0, y0, x1, y1):
        return [x0 * k, y0 * k, x1 * k, y1 * k]

    rows = [px(208, 623, 535, 640), px(299, 660, 534, 676)]
    band = np.zeros((int(700 * k), int(600 * k)), dtype=bool)
    for y in range(int(638 * k), int(652 * k)):            # 一截一截的笔画，没有长横线
        for x in range(int(296 * k), int(538 * k), 4):
            band[y, x] = True
    assert FG._is_text_residual(px(296, 638, 538, 652), rows, band, k, np), \
        "文字残影没被认出来：一题会多出两张只有字的废图"

    # 反例：数轴（440pt 一根连续横线）
    rows2 = [px(60, 190, 500, 210)]
    band2 = np.zeros_like(band)
    band2[int(200 * k):int(202 * k), int(60 * k):int(500 * k)] = True
    assert not FG._is_text_residual(px(60, 194, 500, 206), rows2, band2, k, np), \
        "数轴被当噪声砍了——本模块最早踩过的坑，别再来一次"

    # 反例：记录单格子（27pt 高，比一行字高）
    band3 = np.zeros_like(band)
    band3[int(384 * k):int(411 * k), int(132 * k):int(188 * k)] = True
    assert not FG._is_text_residual(px(132, 384, 188, 411), rows, band3, k, np), \
        "比一行字高的东西不该被当成文字残影"


def light_coloured_diagram_is_still_found():
    """淡蓝框线的图必须裁得出来：固定"灰度<160 才算墨"一直在系统性漏墨。

    真实卷：5·3 天天练的地铁线路示意图、书法馆路线图、无人配送车方格图，
    框线是淡蓝的（灰度 180–210），旧门限下整张图只剩几行字 → 题做不了。
    现在每页按 Otsu 自适应（并把墨占比压在 12% 以内），这类图才看得见。
    """
    path = os.path.join(OUT, "淡蓝图.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 下面是某地铁部分线路示意图，填一填。")
    light = (0.76, 0.76, 0.76)                 # 灰度≈194：旧门限 160 完全看不见
    for i in range(4):
        x = 70 + i * 90
        page.draw_line((x, 170), (x + 90, 170), color=light, width=2.2)
        page.draw_circle((x, 170), 9, color=light, width=2.0, fill=(1, 1, 1))
    _txt(page, 40, 260, "2. 第二题的题干文字。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    wide = [im for lst in got.values() for im in lst if im["w_pt"] > 200]
    assert wide, f"淡蓝框线的线路图没被认出来（题就没法做）：{got}"


def trailing_bracket_of_an_equation_is_inside_the_crop():
    """算式图右边的"（ ）"不能被切掉：括号是文字框，但少了半个括号孩子就看不出那是个空。

    真实卷：第三单元练习题 思维探究题"⭐+⭐+⭐+⭐=20 … 🌙=（ ）"，
    裁图停在括号之前，印出来是"🌙=("。
    """
    from app.extractor.figures import _extend_to_short_marks
    boxes = [{"x": 300, "y": 100, "w": 12, "h": 12},        # 图右边的"）"
             {"x": 320, "y": 100, "w": 200, "h": 14}]       # 隔壁整句题干
    out = _extend_to_short_marks((60, 90, 296, 130), boxes)
    assert out[2] >= 312, f"没把紧贴图边的括号圈进来：{out}"
    assert out[2] < 330, f"把隔壁整句题干也圈进来了：{out}"


def _board_source(gaps=(), size_pt=200):
    """造一页"围棋盘"：每 10pt 一根横竖线；gaps 里的 y 区间【不画线】（模拟真空缝）。"""
    import numpy as np
    from app.extractor.figures import PageSource, DPI_PROBE
    k = DPI_PROBE / 72.0
    g = np.full((int(size_pt * k), int(size_pt * k)), 255, dtype=np.uint8)
    n = int(size_pt * k)
    for i in range(10, n, int(10 * k)):
        g[max(0, i - 1):i + 1, :] = 40
        g[:, max(0, i - 1):i + 1] = 40
    for lo, hi in gaps:            # 缝里【横竖线都断掉】：只断横线的话竖线自己就把缝跨过去了
        g[int(lo * k):int(hi * k), :] = 255
    return PageSource(1, size_pt, size_pt, g, lambda rect, out: None)


def figure_split_by_a_question_boundary_is_stitched():
    """题号边界正好穿过一张图：上下两半必须缝成一张（真实卷：第三单元 第 5 页的围棋盘，
    棋盘被切成"上半挂第 21 题、下半挂第 22 题"，两边都只能看半个棋盘）。"""
    import app.extractor.figures as FG
    src = _board_source()
    def cand(qi, rect):
        return {"q_index": qi, "page": 1, "col": 0, "src": src, "rect": rect,
                "w_pt": rect[2] - rect[0], "h_pt": rect[3] - rect[1],
                "tbs": [], "band": [0, 0, 200, 200]}
    out = FG._stitch_across_questions([cand(20, (10.0, 10.0, 130.0, 102.0)),
                                       cand(21, (10.0, 98.0, 132.0, 190.0))])
    assert len(out) == 1, f"接缝上有棋盘线却没缝回一张：{[c['rect'] for c in out]}"
    assert out[0]["q_index"] == 20, "缝合后应挂到靠前那道题"
    assert out[0]["rect"][3] >= 189 and out[0]["rect"][1] <= 11, out[0]["rect"]

    # 反例：两张本来就该分开的图（中间是真空白，没有墨跨过去）不许缝
    def cand2(qi, rect):
        return {"q_index": qi, "page": 1, "col": 0, "src": src2, "rect": rect,
                "w_pt": rect[2] - rect[0], "h_pt": rect[3] - rect[1],
                "tbs": [], "band": [0, 0, 200, 200]}
    # ⚠️ 缝必须【紧贴】（间隙 ≤ STITCH_GAP_PT），否则挡下它的是"间隙太大"这条，
    #    而不是"接缝上没有墨"这条 —— 变异闸门就是要区分这两条。
    src2 = _board_source(gaps=((88, 99),))
    out2 = FG._stitch_across_questions([cand2(20, (10.0, 10.0, 130.0, 92.0)),
                                        cand2(21, (10.0, 93.0, 132.0, 190.0))])
    assert len(out2) == 2, f"两张分开的图被缝成一张了：{[c['rect'] for c in out2]}"

    # 反例②：两半【宽窄差一倍】＝上下两张不相干的图，不是一张被劈开。
    #   真实卷（综合实践单元(1).pdf 第 1 页）：第 3 题的记录单 148pt 宽，
    #   第 4 题那两个背靠背小孩 59pt 宽，正好压在记录单右半边下面，
    #   两边各自 ±3pt 外扩后互相重叠 6pt —— 只看"横向重叠"就会缝成一张 148×76 的怪图，
    #   第 4 题从此没图。正例（上面那个棋盘）两半是 120 和 122，比值 0.98。
    out3 = FG._stitch_across_questions([cand(2, (10.0, 10.0, 158.0, 63.0)),
                                        cand(4, (100.0, 63.0, 159.0, 91.0))])
    assert len(out3) == 2, (f"宽窄差一倍的上下两张图被缝成一张（第 4 题会因此没图）："
                            + str([c["rect"] for c in out3]))

    # 反例③：缝合之后【挂给谁】。真实卷（综合实践单元.pdf 第 1 页）第 4 题
    # "背靠背夹球"那张图从 441 画到 515，而第 3、4 题的分界在 466 ——
    # 图有 48pt 落在第 4 题区间、只有 25pt 落在第 3 题区间。
    # 无脑"挂靠前那道"＝第 4 题题干明明写着"如右图所示"却一张图都没有。
    def cand_b(qi, rect, band):
        d = cand(qi, rect)
        d["band"] = band
        return d
    out4 = FG._stitch_across_questions([
        cand_b(3, (10.0, 40.0, 130.0, 66.0), (0.0, 0.0, 200.0, 63.0)),
        cand_b(4, (10.0, 65.0, 132.0, 115.0), (0.0, 63.0, 200.0, 120.0))])
    assert len(out4) == 1, f"夹具本身没缝上，测不到归属：{[c['rect'] for c in out4]}"
    assert out4[0]["q_index"] == 4, (
        f"整张图落在第 4 题区间里的更多，却挂给了第 3 题（q4 会没图）：{out4[0]['q_index']}")


def dirty_background_does_not_become_one_giant_figure():
    """纸面发灰（拍照/扫描底）时，门限不许一路顶到"整页都是墨"。

    墨门限取"最黑 12% 的分位"，但必须【夹在 225 以内】：
    纯白页那个分位是 255，不夹的话背景上任何一点灰都被当墨，
    整页会糊成一张"图"。这条用一张灰底页正面量它。
    """
    path = os.path.join(OUT, "灰底页.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(pymupdf.Rect(0, 0, 595, 842), color=(0.92, 0.92, 0.92),
                   fill=(0.92, 0.92, 0.92))                 # 灰底 ≈235
    _base(page)
    _txt(page, 40, 90, "1. 第一题的题干文字内容。")
    _txt(page, 40, 300, "2. 第二题的题干文字内容。")
    doc.save(path)
    doc.close()
    from app.extractor.figures import page_source_from_pdf
    src = page_source_from_pdf(path, 1)
    assert src.ink_thr <= 225 + 1, f"门限没夹住上限：{src.ink_thr}"
    _r, _res, qs, spans, got = run(path)
    giant = [im for lst in got.values() for im in lst
             if im["w_pt"] > 480 and im["h_pt"] > 600]
    assert not giant, f"灰底整页被当成一张图：{[(i['w_pt'], i['h_pt']) for i in giant]}"


def equation_bracket_wiring_end_to_end():
    """接线检查：小标点框圈进来这条，必须真的在 find_figures 的链路上。
    （单元测试直接调函数是测不出"没人调用它"的——这一轮被变异闸门抓到过两次。）"""
    path = os.path.join(OUT, "算式带括号.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 看图列式，把得数填在括号里。")
    # 图本体：一个画了格子的长条（真墨，不会被文字掩膜挖掉）
    page.draw_rect(pymupdf.Rect(60, 120, 250, 180), color=(0, 0, 0), width=1.2)
    for i in range(1, 4):
        page.draw_line((60 + i * 47.5, 120), (60 + i * 47.5, 180), color=(0, 0, 0), width=0.8)
    _txt(page, 258, 158, "（", size=14)       # 紧贴图右边的一对括号＝要填的空
    _txt(page, 300, 158, "）", size=14)
    _txt(page, 40, 260, "2. 第二题的题干文字。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    imgs = [im for lst in got.values() for im in lst]
    assert imgs, "这道题一张图都没有"
    right = max(im["rect"][2] for im in imgs)
    assert right >= 314, f"括号没被圈进裁图（印出来会少半个括号）：最右只到 {right:.0f}"


def straddling_figure_wiring_end_to_end():
    """接线检查：跨题缝合必须真的接在 find_figures 上（同上，防"函数对、线没接"）。

    夹具照真实卷那张围棋盘的形状造：一张高图横跨两道题的分界行，
    上半天属于第 1 题的区间、下半属于第 2 题 → 不缝就是"两题各看半个棋盘"。
    """
    path = os.path.join(OUT, "跨题的图.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 数一数，黑棋有多少枚？")
    # 分界行【必须自己带题号】，否则它不会成为区间边界，图也就没被劈开（第一版假在这）
    _txt(page, 330, 200, "2. 白棋有（   ）枚。")
    _txt(page, 40, 320, "3. 一共有多少枚？")
    for i in range(11):                              # 棋盘格：y 120–300，横跨两题区间
        y = 120 + i * 18
        page.draw_line((60, y), (300, y), color=(0, 0, 0), width=0.8)
        page.draw_line((60 + i * 24, 120), (60 + i * 24, 300), color=(0, 0, 0), width=0.8)
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    tall = [im for lst in got.values() for im in lst if im["h_pt"] > 120]
    assert tall, ("没有一张横跨分界的完整图，说明缝合没接上："
                  + str({k + 1: [i["rect"] for i in v] for k, v in got.items()}))
    im = tall[0]
    assert im["rect"][1] <= 126 and im["rect"][3] >= 294, f"缝合后仍不完整：{im['rect']}"


def merged_label_row_absorbs_only_the_fragment():
    """OCR 把"题干 + 图里的标注"并成一行时，只许吸【贴着图的那一小片】。

    真实卷：综合实践单元(1).pdf 第 1 页 第 4 题（背靠背夹球）——
    "4.如右图所示，两名同学玩背靠背夹" 和气泡里的"我面向东。"被读成同一行。
    整行挖掉＝气泡从图里消失（孩子不知道谁面向东，这道题做不了）；
    整行吸回＝题干进图（用户骂过的"图片和题目不对应"）。两头都错，
    所以先按行内空白把这一行切成碎片，只吸贴着图边、宽度 ≤ FRAG_MAX_W_PT 的那片。
    """
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0
    W, H = int(200 * k), int(40 * k)

    def source(patches):
        raw = np.zeros((H, W), dtype=bool)
        for (x0, y0, x1, y1) in patches:
            raw[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] = True
        return raw

    # 正例：题干那截 30–110，气泡 121–149（中间空 11pt），小孩的墨 145–174
    raw = source([(30, 8, 110, 15), (121, 8, 149, 16), (145, 5, 174, 28)])
    box = [145 * k, 5 * k, 174 * k, 28 * k]
    row = [30 * k, 6 * k, 149 * k, 17 * k]
    got = FG._absorb_label_rows(list(box), [row], k, raw, np)
    assert got[0] / k <= 122, (f"图注气泡没吸回来，裁出的图缺「我面向东」：x0={got[0] / k:.1f}")
    assert got[0] / k > 110, f"把题干也一起吸进图里了：x0={got[0] / k:.1f}"
    assert got[2] / k >= 173, f"右边被吸乱了：{[v / k for v in got]}"

    # 反例：贴着图的那一片有 50pt 宽（> FRAG_MAX_W_PT=45）＝半句正文，一行都不许吸
    raw2 = source([(30, 8, 60, 15), (95, 8, 145, 15), (145, 5, 174, 28)])
    got2 = FG._absorb_label_rows(list(box), [[30 * k, 6 * k, 145 * k, 17 * k]], k, raw2, np)
    assert got2 == list(box), f"把 50pt 宽的正文碎片吸进图里了：{[v / k for v in got2]}"

    # 反例：没有 raw 时退回老行为（整行判定），不许凭空长框
    got3 = FG._absorb_label_rows(list(box), [row], k)
    assert got3 == list(box), f"没有墨迹图时乱长：{[v / k for v in got3]}"

    # 反例②：贴着图边的碎片只有【一个字宽】（10pt < FRAG_MIN_W_PT）—— 那是正文里的
    #         一个字，不是图注。没有这条下限，页脚那行字的单字碎片会被一路吸进图里。
    raw4 = source([(30, 8, 110, 15), (138, 8, 148, 15), (145, 5, 174, 28)])
    got4 = FG._absorb_label_rows(list(box), [[30 * k, 6 * k, 148 * k, 17 * k]], k, raw4, np)
    assert got4 == list(box), f"一个字宽的碎片被当图注吸进图里：{[v / k for v in got4]}"

    # 反例③：碎片贴在图的【正上方】—— 那是正文行的尾巴，不是图注。
    #   真实卷（第三单元练习题 第 2 页第 3 题）：题干第二行被切成三片，最左 44.6pt
    #   那片距叶子图只有 5.8pt，吸进来后裁框顶 457.1→439.9，整行题干又进了图。
    #   （行内得有两坨墨才会走"碎片"分支；最左那坨 15pt < 下限，天然不收）
    raw5 = source([(0, 8, 15, 15), (32, 8, 72, 15)])
    fig5 = [30 * k, 20 * k, 120 * k, 50 * k]
    got5 = FG._absorb_label_rows(list(fig5), [[0, 4 * k, 75 * k, 17 * k]], k, raw5, np)
    assert got5 == list(fig5), f"图正上方的正文碎片被当图注吸进来了：{[v / k for v in got5]}"


def _blob(page, x0, y0, x1, y1):
    """一块看得出是图的墨：外框 + 两根内线（不是空心单线框）。"""
    page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=1.2)
    page.draw_line((x0 + 3, (y0 + y1) / 2), (x1 - 3, (y0 + y1) / 2),
                   color=(0, 0, 0), width=1.0)
    page.draw_line(((x0 + x1) / 2, y0 + 3), ((x0 + x1) / 2, y1 - 3),
                   color=(0, 0, 0), width=1.0)


def small_page_gate_scales_with_the_column():
    """小版面（5·3 那种 64% 缩放的页面）上的小图不许被"太小"这条砍没。

    真实卷：综合实践单元(1).pdf 页面只有 370×287pt、一栏 192pt，同一张插图缩到
    53×22pt；按 A4 栏（≈280pt）量的绝对门槛 1200pt² 判它不值得裁 → 这道题没图做不了。
    所以门槛跟着【栏有多宽】缩，但只放宽不收紧。

    ⚠️ 做成直接喂尺寸的判定单测：合成 PDF 里造不出"窄页两栏"（两栏之间的缝够不到
       分栏检测的最小缝宽，会被并成一栏 → scale=1 → 测试假失败，第一版就栽在这里）。
    """
    import app.extractor.figures as FG
    # 正对照：A4 栏上量出来的绝对门槛本身还在（100×30 在宽栏上照样合格）
    assert FG._size_gate(100.0, 30.0, 280.0) == (True, True), "宽栏的判据被改坏了"
    # 小版面上唯一的 50×20 图：绝对门槛不过，缩放后的门槛要过
    ok, strict = FG._size_gate(50.0, 20.0, 192.5)
    assert ok and not strict, f"窄栏的小图还是被砍（或没算出它是放宽档）：{(ok, strict)}"
    # 反例①：门槛只放宽不收紧 —— 宽栏上"太小"的图不能因为这条混进来
    assert FG._size_gate(50.0, 20.0, 595.0) == (False, False),         "宽栏也放宽了：小版面那条判据等于没闸"
    # 反例②：再窄也不能无限放宽（下限 0.5 倍）
    assert FG._gate_scale(20.0) == 0.5, f"缩放没有下限：{FG._gate_scale(20.0)}"
    assert FG._gate_scale(0) == 1.0, "拿不到栏宽时应退回原判据"

    # 放宽那一档：这道题有严格合格的图时，只留严格的
    def c(qi, w, h, strict):
        return {"page": 1, "q_index": qi, "rect": (0.0, 0.0, w, h), "strict": strict}
    big, small = c(2, 75, 60, True), c(2, 50, 20, False)
    only_small = c(1, 50, 20, False)
    kept = FG._prefer_strict([big, small, only_small])
    assert kept == [big, only_small], f"放宽档没受控：{[(k['q_index'], k['rect']) for k in kept]}"


def page_footer_is_a_wall_not_a_seam():
    """页脚那行印刷字是【墙】：不许让近邻合并把上面的图和下面的东西接成一张。

    真实卷：综合实践单元(1).pdf 第 2 页最后一道题（书法馆路线图）——它是本栏最后一题，
    区间一直延伸到页底，图和页脚"第2页(共4页)"之间只隔一行字。那行字被挖掉之后，
    膨胀半径 7pt + 近邻半径 14pt 正好把"图 → 页脚 → 页底 logo"接成一块，
    成品图上就印着"夸克扫描王"和它的二维码。
    """
    path = os.path.join(OUT, "页脚缝进图里.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 660, "1. 看图填方向，把答案写在括号里。")
    _compass(page, 120, 735, 45)                         # 图：x 75–165、y 690–780
    _txt(page, 40, 795, "综合实践(一)达标练习 第 1 页（共 2 页）")   # 页脚＝墙
    for r in range(4):                                   # 页底 logo（图下面 22pt）
        for c in range(4):
            page.draw_rect(pymupdf.Rect(78 + c * 22, 802 + r * 10,
                                        98 + c * 22, 811 + r * 10),
                           color=(0, 0, 0), width=1.0, fill=(0.3, 0.3, 0.3))
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    imgs = [im for lst in got.values() for im in lst]
    assert imgs, "夹具上一张图都没裁出来，等于空转"
    merged = [im for im in imgs if im["rect"][1] < 700 and im["rect"][3] > 790]
    assert not merged, (f"图和页脚下面的东西被接成一张（成品会带着扫描 app 的广告）："
                        + str([i["rect"] for i in merged]))
    assert any(im["rect"][1] < 700 and im["rect"][3] < 790 for im in imgs),         f"那张罗盘本身没裁到：{[i['rect'] for i in imgs]}"
    # 图也不许【向右长】进页脚那行字：单个汉字的碎片（10pt）不算"图注"
    wide = [im for im in imgs if im["rect"][1] < 700 and im["rect"][2] > 176]
    assert not wide, f"图往右长进了页脚那行字里：{[i['rect'] for i in wide]}"

    # 直接钉住 _absorb_label_rows 里的墙判据。上面的成品几何在"碎片只收左右两侧"
    # 之后已经碰不到页脚（页脚在图正下方），单靠成品图测不到这条墙：
    # 把函数打坏也照样全绿（变异闸门当场报"没抓到"）。
    # 反例必须成立：不带墙标记的右侧图注要真的吸进来，否则这条尺是空转。
    import app.extractor.figures as FG
    real_frag = FG._row_fragments
    FG._row_fragments = lambda raw, t, k, np: [[303.0, 120.0, 330.0, 140.0]]
    try:
        box = [100.0, 100.0, 300.0, 200.0]
        row = [303.0, 120.0, 330.0, 140.0]
        walled = FG._absorb_label_rows(box, [row], 1.0, wall_flags=[True])
        assert walled == box, f"页脚行被当图注吸进图：{walled}"
        free = FG._absorb_label_rows(box, [row], 1.0, wall_flags=[False])
        assert free[2] >= 330.0, f"带墙标记的没吸、不带墙的也没吸，这条测不到墙：{free}"
    finally:
        FG._row_fragments = real_frag


def crop_top_edge_does_not_swallow_the_stem_first_line():
    """裁框盖住"本题第一行"时把上沿收到这一行下面 —— 图里不许再抄一遍题目。

    坐标取自真实卷（综合实践单元(1).pdf 第 2 页 第 24 题）：题干行框是
    y 155.8–161.3，可 OCR 的行框和真正的字差了半行，字的墨落在 157.7，
    ±3pt 外扩后裁框顶到 154.7 → 整行"2. 请为2号无人配送车设计一条行驶路线。"
    被框进图里，印出来就是图下面又抄了一遍题目。九份卷这种有 9 处。

    ⚠️ 做成直接喂坐标的判定单测：合成 PDF 里字的位置和行框【永远是对齐的】，
       复现不了"行框和字错位半行"这个成因（第一版造夹具就是这么假的绿）。
    """
    import app.extractor.figures as FG
    rows = [{"x": 201.4, "y": 155.8, "w": 134.6, "h": 5.5, "text": "2.请为2号无人配送车设计一条行驶路线。"},
            {"x": 235.7, "y": 168.7, "w": 86.2, "h": 6.5, "text": "从标★的快递点出发"}]
    rect = (197.9, 154.7, 363.7, 247.1)
    cut = FG._clip_stem_row(rect, rows)
    assert cut[1] >= 162.3, f"题干首行还框在图里：y0={cut[1]:.1f}，应收到 162.3"
    assert cut[3] == rect[3] and cut[0] == rect[0], f"只许动上沿，别乱收：{cut}"

    # 反例①：这一行是被规则⑤当【图注】吸回来的（气泡"我面向东。"）→ 一行都不许裁
    assert FG._clip_stem_row(rect, rows, [0]) == rect, "把图注也裁掉了（图会缺气泡）"
    # 反例②：只蹭到题干行【下沿一点点】（盖住 24% < 80%）→ 不许削这一刀。
    #   ⚠️ 不能拿"图整个在题干下面"当反例：那种裁框 max() 之后原样返回，
    #      把阈值判据整条关掉也不会红（第一版就是这么假绿过去的）。
    graze = (197.9, 160.0, 363.7, 247.1)
    assert FG._clip_stem_row(graze, rows) == graze, "只蹭到一点就裁，阈值判据等于没写"
    # 反例③：整行盖住、但收完上沿就没图了 → 宁可留着重复的那行题干，也不能让题没图
    thin = (200.0, 155.0, 340.0, 165.0)
    assert FG._clip_stem_row(thin, rows) == thin, "把图裁到 8pt 以下，题就没图做了"
    assert FG._clip_stem_row(rect, []) == rect, "没有文字行时不该改动裁框"


def crop_top_edge_does_not_swallow_the_stem_second_line():
    """题干第二行也不许进图 —— 旧版只盯"区间第一行"，第二行正好被裁框盖住时放过。

    真实卷（第三单元练习题.pdf 第 2 页第 3 题 树叶片数）：叶子图的裁框是
    (53.2, 436.9, 558.1, 522.1)，题干第二行"不能用2×4表示的是( ).(填序号)"
    的行框是 y436.7–455.0、横向 100% 落在裁框里 —— 旧版 `_clip_stem_row`
    只看区间最上面那行（L00，在裁框上方 10pt 外），于是整行题干被裁进图里。

    ⚠️ 直接喂真实坐标：行框和字的半行错位在合成 PDF 里复现不出来。
    """
    import app.extractor.figures as FG
    rows = [{"x": 41.3, "y": 407.0, "w": 519.9, "h": 20.1,
             "text": "3.[自然科普］落叶腐(f)烂后会化作养分,促进植物生长。下面的树叶片数"},
            {"x": 58.1, "y": 436.7, "w": 276.7, "h": 18.3,
             "text": "不能用2×4表示的是(       )。(填序号)"},
            {"x": 63.5, "y": 482.9, "w": 444.1, "h": 18.7, "text": "CL            长长"}]
    rect = (53.2, 436.9, 558.1, 522.1)
    cut = FG._clip_stem_row(rect, rows)
    assert cut[1] >= 456.0, f"题干第二行还框在图里：y0={cut[1]:.1f}，应收到 456"
    assert cut[0] == rect[0] and cut[2] == rect[2] and cut[3] == rect[3], \
        f"只许动上沿：{cut}"

    # 反例①：图自己内部的标注行（叶子图里的"CL 长长"）离裁框顶 46pt ——
    #   它不在"贴着上沿"那一档，一行都不许裁。
    inside = (53.2, 436.9, 558.1, 522.1)
    assert FG._clip_stem_row(inside, [rows[2]]) == inside, "把图自己的标注行裁掉了"
    # 反例②：同一行若已被规则⑤当图注吸回来（气泡/标签），不许裁
    assert FG._clip_stem_row(rect, rows, [1]) == rect, "把吸回来的图注裁掉了"
    # 反例③：收完上沿就不到 8pt 图 —— 宁可留这一行题干
    tiny = (53.2, 436.9, 558.1, 446.0)
    assert FG._clip_stem_row(tiny, rows) == tiny, "把图裁没了"


def crop_top_edge_skips_figure_labels_inside_the_picture():
    """放宽到"任意贴顶行"之后，图里的标注也被裁掉了 —— 非第一行必须贴左沿。

    旧版只看区间第一行；放宽后这三处的标注行都满足"贴顶 + 被盖住 80%"：
      · 第三单元练习题 第 2 页 "一共有多少个蘑菇?"：`加法算式:` 与顶层蘑菇同高，
        裁框上沿 290.8 被它收到 311.9 → 第一排蘑菇全切掉（审计 切边 上+1911px）；
      · 第三单元练习题 第 1 页 "数一数…"：`+2+2…` 是数轴图自己的刻度标签，
        裁框 541.3 → 560.2，青蛙和弧线全没了（审计 切边 上+304px）；
      · 综合实践课 第 2 页公交路线图：右上角 "开心公园   北" 是图注，
        裁框 267.7 → 301.5，地图上部被削掉。

    共同点：它们都从图【中间】起句（行首离裁框左沿 49 / 205 / 327pt），
    而真正的题干行从正文左边界起排（正的实测：达标B 第 1 题读文行差 11.6pt）。
    """
    import app.extractor.figures as FG
    # 正例：非第一行、贴左沿 → 该裁（第三单元达标练习题B 第 1 题读文行）
    b_rows = [{"x": 90.0, "y": 40.0, "w": 300.0, "h": 18.0, "text": "六、一起来为童年纪念册添故事吧！"},
              {"x": 90.7, "y": 67.7, "w": 334.1, "h": 26.6,
               "text": "我最喜欢读关于航天的书籍！从火箭升空的原理，到空间站运"}]
    b_rect = (79.1, 67.6, 432.1, 264.4)
    cut = FG._clip_stem_row(b_rect, b_rows)
    assert cut[1] >= 95.3, f"贴左沿的读文行没裁：y0={cut[1]:.1f}，应收到 95.3"

    # 反例①：第三单元 蘑菇题里的 `加法算式:`（行首差 205pt）
    m_rows = [{"x": 41.7, "y": 264.7, "w": 158.8, "h": 18.8, "text": "2.一共有多少个蘑菇?"},
              {"x": 289.9, "y": 292.7, "w": 76.7, "h": 18.2, "text": "加法算式:"}]
    m_rect = (84.8, 290.8, 538.7, 400.4)
    assert FG._clip_stem_row(m_rect, m_rows) == m_rect, "把顶层蘑菇连着 `加法算式:` 一起切了"

    # 反例②：数轴图的 `+2+2…`（行首差 49pt）
    n_rows = [{"x": 30.8, "y": 477.8, "w": 260.9, "h": 17.4, "text": "3.数一数，用加法算式记录数的结果。"},
              {"x": 91.6, "y": 544.6, "w": 210.1, "h": 14.6, "text": "+2+2+2+2+2+2+2+2"}]
    n_rect = (42.4, 541.3, 324.1, 591.2)
    assert FG._clip_stem_row(n_rect, n_rows) == n_rect, "把青蛙和数轴弧线切掉了"

    # 反例③：公交路线图右上角的 "开心公园   北"（行首差 327pt）
    g_rows = [{"x": 96.0, "y": 240.0, "w": 300.0, "h": 18.0, "text": "2.某市新开通了一条公交专线。"},
              {"x": 423.3, "y": 264.9, "w": 85.7, "h": 16.4, "text": "开心公园   北"}]
    g_rect = (96.4, 267.7, 509.9, 405.5)
    assert FG._clip_stem_row(g_rect, g_rows) == g_rect, "把路线图右上角削掉了"

    # 第一行不受左沿限制：达标A 第 1 题的"时间/评价"栏（行首差 37.5pt 也照裁）
    a_rows = [{"x": 109.4, "y": 117.4, "w": 197.3, "h": 14.4, "text": "③时间：40分钟            评价"}]
    a_rect = (71.9, 114.4, 396.1, 311.2)
    cut = FG._clip_stem_row(a_rect, a_rows)
    assert cut[1] >= 132.8, f"第一行的表格栏没裁：y0={cut[1]:.1f}，应收到 132.8"


def short_mark_extension_skips_wordy_boxes():
    """圈"小标点"不许把换行正文一路串进图里（小版面 86pt 宽的正文照样过宽度关）。"""
    import app.extractor.figures as FG
    rect = (0.0, 224.0, 31.0, 262.0)                    # 装订栏那条碎墨外扩后的框
    boxes = [{"x": 36.5, "y": 237.4, "w": 86.6, "h": 5.8, "text": "的口令后，同学们将面向（   ）站立。"},
             {"x": 20.9, "y": 249.1, "w": 86.2, "h": 4.8, "text": "157 综合实践(一)达标练习 第1页(共4页）"},
             {"x": 34.0, "y": 240.0, "w": 10.0, "h": 6.0, "text": "）"}]
    got = FG._extend_to_short_marks(rect, boxes)
    assert got[2] < 50, f"整句正文被当「小标点」串进裁图：{got}"
    assert got[2] >= 44, f"真的括号也没圈进来（算式会少半个括号）：{got}"


def row_peers_join_the_crop():
    """同一行被"太小"闸门砍掉的括号/运算符，要并回这张图。

    真实卷（第三单元练习题.pdf 第 1 页第 4 题「★＋★＋★＋★＝20」）：
    星星加号连成 366×107pt 的图，式子末尾的"（   ）"只有 11×22pt，
    被单独砍掉 → 裁图右边缘正好切在"＝（"上，孩子看不见括号里要填什么。
    审计器的"切边"看不见这一类：它只看框外 6px 的贴边墨，这里中间还隔着 26pt 空白。
    """
    import app.extractor.figures as FG
    rect = (41.6, 686.0, 407.6, 792.8)                 # 真的那张图
    box = (0.0, 664.8, 595.2, 907.0)                   # 本题的栏区间
    paren = (434.2, 765.4, 445.0, 787.0)               # 被 small 砍掉的那半个括号
    got = FG._absorb_row_peers(rect, [paren], box)
    assert got[2] >= 445.0, f"同行的小括号没并进来，算式仍被截断：{got}"
    assert got[0] == rect[0] and got[1] == rect[1] and got[3] == rect[3], \
        f"只许横向长，别乱动别的边：{got}"

    # 反例①：只压到图框【下沿 8pt】的一条小块（下一行的东西，而且更宽）
    #   —— 竖直重叠 7.8/15 = 52% < 60% → 不算同行。
    #   ⚠️ 这块必须【比图框宽】：放在框内的话，"重叠阈值调到 0.05"这种破坏
    #      并进来也不会改变坐标，测试照样绿（第一版就是这么假绿过去的）。
    below = (41.6, 785.0, 460.0, 800.0)
    assert FG._absorb_row_peers(rect, [below], box) == rect, "把下一行的东西并进来了"
    # 反例②：同一行但隔得太远（那是栏里另一道式子）
    far = (520.0, 765.4, 530.0, 787.0)
    assert FG._absorb_row_peers(rect, [far], box) == rect, "把 100pt 外的另一道式子并来了"
    # 反例③：不许越过本题的栏区间（越栏＝把邻题的图截过来，用户骂过的老 bug）
    over = (600.0, 765.4, 640.0, 787.0)
    g3 = FG._absorb_row_peers((41.6, 686.0, 560.0, 792.8), [over], box)
    assert g3[2] <= box[2] + 3.0, f"裁框越过栏区间：{g3}"
    # 反例④：同行、但【往上探出 36pt】的小块 —— 竖直重叠够格（80/80），
    # 也只许把 x 拉宽，不许把上沿顶回 650（那是规则 L 刚裁掉的题干首行）
    above = (10.0, 660.0, 50.0, 780.0)
    g4 = FG._absorb_row_peers(rect, [above], box)
    assert g4[1] == rect[1], f"上沿被同行小块顶回去了（题干首行会重新框进图）：{g4}"
    assert g4[0] == 10.0, f"这条本该横向并进来却没并：{g4}"


def side_by_side_pieces_join_one_figure():
    """同一道题、同一行、被【文字行挖断】的几块，其实是一张图。

    真实卷（第三单元练习题.pdf 第 2 页）的标注算式/括号列被 OCR 行框横穿，
    横向切开后各自成块，每块只剩半个式子——用户指着说"图片中的字不全"。
    这里用【等高、同题、间隙 10/63pt】的三块把缝合判据钉住；三块各自都过
    尺寸门槛，所以问题不在门槛，在【横向没有缝合】
    （上下方向早就有 _stitch_across_questions 治棋盘）。

    ⚠️ 直接喂候选框：合成卷里"OCR 行框正好横穿图"的几何造不出来，硬造是假绿。
    """
    import app.extractor.figures as FG

    def cand(qi, rect, page=2, col=0):
        return {"q_index": qi, "page": page, "col": col, "rect": list(rect),
                "band": [0.0, 127.6, 595.2, 264.7], "strict": True, "src": None,
                "tbs": [], "w_pt": rect[2] - rect[0], "h_pt": rect[3] - rect[1]}

    left = cand(4, [60.0, 172.7, 173.6, 219.7])        # 三块等高（47.0/47.1/47.0）
    mid = cand(4, [183.5, 174.8, 242.0, 221.9])
    right = cand(4, [305.2, 172.7, 364.4, 219.7])
    got = FG._stitch_side_by_side([left, mid, right])
    assert len(got) == 1, f"一张标注图被题内切成 {len(got)} 块：{[g['rect'] for g in got]}"
    r = got[0]["rect"]
    assert r[0] <= 61.0 and r[2] >= 363.0, f"合并后的框没盖住整张图：{r}"
    assert got[0]["q_index"] == 4, f"合并后挂错题：{got[0]['q_index']}"

    # 反例①：两个并排钟面（间隙 236pt）必须还是两张
    a = cand(0, [68.0, 128.0, 152.0, 212.0], page=1)
    b = cand(0, [388.0, 128.0, 472.0, 212.0], page=1)
    g2 = FG._stitch_side_by_side([a, b])
    assert len(g2) == 2, f"两张并排的图被并成一张横跨半页的怪图：{[x['rect'] for x in g2]}"
    # 反例②：同一行、挨得很近，但【属于两道题】→ 不许把邻题的图吞过来
    c = cand(7, [183.5, 174.8, 242.0, 221.9])
    g3 = FG._stitch_side_by_side([mid, c])
    assert len(g3) == 2, f"跨题并图：邻题的图被并进来了 {[x['rect'] for x in g3]}"
    # 反例③：同一题、水平也挨着，但【上下分开】（竖直只重叠 25%）→ 那是两张图。
    #   ⚠️ 两块必须【等高】：让"重叠"这一条单独负责拦它。否则高度比 1.91 也会拦，
    #      "把重叠阈值从 0.5 调到 0.05"这种破坏改不了结果（第一版拿"上下分离 80pt"
    #      当反例，闸门当场报没抓到）。
    d = cand(4, [183.5, 210.0, 242.0, 257.1])
    g4 = FG._stitch_side_by_side([mid, d])
    assert len(g4) == 2, f"上下两张图被并成一张：{[x['rect'] for x in g4]}"

    # 反例④：真实卷 Q4（胡萝卜货架）—— 答题框行外扩后 37.7pt 高、货架 74.4pt 高，
    #   横向间隙 50.3pt、竖直重叠 50.7%（刚过 50% 的重叠关），高度比 1.97。
    #   并起来就是用户截图那张"真图蹭到题干字"的 459×74 怪框。
    row = cand(7, [103.6, 542.0, 267.1, 579.7])
    shelf = cand(7, [317.4, 516.1, 562.4, 590.5])
    g5 = FG._stitch_side_by_side([row, shelf])
    assert len(g5) == 2, f"答题框行和货架被并成一张：{[x['rect'] for x in g5]}"
    # 反例⑤：老用例里那块 174×125 的"左半张"，其实是左栏残片（侧栏+横幅+碎字），
    #   高度是右侧 47pt 的两倍多 —— 只许左右并排、不许"矮的贴高的"。
    junk_l = cand(4, [0.0, 142.4, 173.6, 267.2])
    g6 = FG._stitch_side_by_side([junk_l, mid])
    assert len(g6) == 2, f"左栏残片被当成图的一半并进来了：{[x['rect'] for x in g6]}"


def contained_duplicate_crop_is_dropped():
    """同一题里小框整块落在大框里＝同一张图裁了两遍，只留大框。

    真实卷（第三单元练习题.pdf 第 2 页第 5 题）：蘑菇图把顶部那行补回来后
    453.9×109.6，右侧答题框 190.5×67.1 有 **95.7%** 落在里面。两块高度比
    1.63 > SIDE_STITCH_MAX_H_RATIO=1.5，横向缝合按规矩不并（那条判据保护的是
    "答题框行 + 胡萝卜货架"），于是同一张图出了两张，第二张只剩答题框那半截
    （用户截图 p2_q5_9.png）。这条钉住"罩住就去重"。
    """
    import app.extractor.figures as FG

    def cand(qi, rect, page=2):
        return {"q_index": qi, "page": page, "col": 0, "rect": list(rect),
                "band": [0.0, 127.6, 595.2, 418.0], "strict": True, "src": None,
                "tbs": [], "w_pt": rect[2] - rect[0], "h_pt": rect[3] - rect[1]}

    shelf = cand(5, [84.8, 290.8, 538.7, 400.4])
    answer = cand(5, [347.5, 336.2, 538.0, 403.3])
    got = FG._drop_contained([answer, shelf])          # 故意把小框放前面
    assert len(got) == 1, \
        f"同一张图裁了两遍，还留着 {len(got)} 张：{[g['rect'] for g in got]}"
    assert got[0]["rect"] == shelf["rect"], \
        f"留下的不是能把图盖全的那张：{got[0]['rect']}"

    # 反例①：跨题不许去重 —— 邻题的图落在本题大图的坐标范围里也还是邻题的
    other_q = cand(6, [347.5, 336.2, 538.0, 403.3])
    assert len(FG._drop_contained([shelf, other_q])) == 2, "跨题去重：邻题的图被吃掉了"
    # 反例②：只罩住 76% (<90%) —— 两块各自有边，不是同一张图裁重（右沿多出 47pt）
    off = cand(5, [347.5, 336.2, 585.5, 403.3])
    assert len(FG._drop_contained([shelf, off])) == 2, "罩住不到 90% 也被当成重复裁图"
    # 反例③：两块几乎一样大（面积比 1.13 < 1.3）→ 宁可留两张也不许互吃
    near = cand(5, [90.0, 295.0, 530.0, 395.0])
    assert len(FG._drop_contained([shelf, near])) == 2, "两张几乎同大的真图被互相吃掉了"


def side_stitch_is_wired_into_find_figures():
    """判据对、线没接 = 没有判据。这条只验"find_figures 真的调了横向缝合"。

    合成卷要造出"一张标注算式被文字行横切"的几何很挑，硬造容易造出自证的假绿；
    所以这里不验几何（几何由上一条验），只验接线：
    把函数换成一个会记账的壳子，跑一遍真流程，看它有没有被叫到。
    """
    import app.extractor.figures as FG
    path = os.path.join(OUT, "接线_横向缝合.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 看图列式。")
    _grid(page, 60, 140, 300, 240)
    _txt(page, 40, 300, "2. 第二题的题干文字。")
    doc.save(path)
    doc.close()
    calls = []
    drop_calls = []
    real = FG._stitch_side_by_side
    real_drop = FG._drop_contained

    def spy(cands, report=None):
        calls.append(len(cands))
        return real(cands, report)

    def spy_drop(cands, report=None):
        drop_calls.append(len(cands))
        return real_drop(cands, report)

    FG._stitch_side_by_side = spy
    FG._drop_contained = spy_drop
    try:
        run(path)
    finally:
        FG._stitch_side_by_side = real
        FG._drop_contained = real_drop
    assert calls, "find_figures 根本没调用横向缝合（判据成了死代码）"
    assert sum(calls) >= 1, f"接线了但一道候选都没拿到：{calls}"
    assert drop_calls, "find_figures 没调用罩住去重（同一张图会裁两遍）"


def banner_and_answer_boxes_are_not_figures():
    """用户截图里的两种废图：栏目横幅色块、答题框行（□×□＝□）。

    横幅：色块比 OCR 读到的那行字高，上下沿逃过 wall，膨胀后才连成"图"；
    答题框行：一排空心方框＋运算符，和"图形代表数"的题图同形。
    这两种都必须一张都不裁出来（真正看图作答的题另有两栏卷等正面用例）。
    """
    path = os.path.join(OUT, "横幅与答题框.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 第一题的题干文字内容。")
    # 栏目横幅：橙底色块 + 反白字。字号大，让 OCR 行框盖住色块的大部分（真卷 89%）
    page.draw_rect(pymupdf.Rect(40, 155, 230, 193), color=None,
                   fill=(0.88, 0.46, 0.12))
    _txt(page, 46, 184, "第二步 练变式", size=26)
    _txt(page, 40, 260, "2. 第二题的题干文字内容。")
    # 答题框行：四个空心方框＋加号/等号，没有任何图的主体
    for i, x in enumerate((60, 100, 140, 190)):
        page.draw_rect(pymupdf.Rect(x, 320, x + 16, 336), color=(0, 0, 0), width=1.2)
        if i < 3:
            page.draw_line((x + 18, 328), (x + 38, 328), color=(0, 0, 0), width=1.2)
    page.draw_line((166, 326), (182, 326), color=(0, 0, 0), width=1.2)
    page.draw_line((166, 330), (182, 330), color=(0, 0, 0), width=1.2)
    _txt(page, 40, 390, "3. 第三题的题干文字内容。")
    _txt(page, 40, 470, "4. 第四题的题干文字内容。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    bad = {qi: [im for im in lst] for qi, lst in got.items()
           if qi in (0, 1)}
    assert not bad, f"横幅/答题框被当成配图裁出来了：{bad}"
    assert not any(lst for lst in got.values()), f"整页都是文字和符号，却裁出图：{got}"
    # 正例必须真的落在题目区间里，否则"没裁出来"只是因为裁图根本没看这块地方
    assert any("第二步" in str(t.get("text") or "")
               for t in spans[0].get("text_boxes") or []), \
        f"夹具没把横幅放进第 1 题区间（这条测试就白测了）：{spans[0].get('text_boxes')}"
    assert any(float(s["y0"]) <= 320 < float(s["y1"]) for s in spans), \
        f"答题框没落在任何题目区间里（测试白测）：{[(s['q_index'], s['y0'], s['y1']) for s in spans]}"


def junk_crop_measures_keep_real_figures():
    """两条新判据的【反例】必须当场量给自己看：

    · 家具行占比 30% 的真图不许砍（阈值 0.60，两边各留 30 点）；
    · 一个方框 / 方框旁有圆（花）的图不许被当答题框。
    """
    import numpy as np
    import app.extractor.figures as FG

    # 墙占比：80×80 的墨，底部 20 行落在 wall 里 = 25%
    raw = np.zeros((120, 120), dtype=bool)
    raw[10:90, 10:90] = True
    wall = np.zeros_like(raw)
    wall[70:90, 10:90] = True
    share = FG._wall_ink_share((10, 10, 90, 90), raw, wall, 1.0, 0, 0)
    assert abs(share - 0.25) < 0.02, f"墙占比量错：{share}"
    assert share < FG.WALL_INK_SHARE_MAX, "25% 的真图被当成横幅（阈值太松）"
    wall[10:80, 10:90] = True
    share2 = FG._wall_ink_share((10, 10, 90, 90), raw, wall, 1.0, 0, 0)
    assert share2 >= FG.WALL_INK_SHARE_MAX, f"70% 的墨在墙里却没到阈值：{share2}"

    # 答题框：四个空心方框 → 是；只有一个方框 → 不是
    def squares(n, big=False, size=20, step=30):
        m = np.zeros((140, 300), dtype=bool)
        for i in range(n):
            x, y = 10 + i * step, 10
            m[y:y + size, x:x + 2] = True
            m[y:y + size, x + size - 2:x + size] = True
            m[y:y + 2, x:x + size] = True
            m[y + size - 2:y + size, x:x + size] = True
        if big:
            # 40×8 的「图的主体」：够宽（≥38pt）但很矮，方框仍占 49% 的墨。
            # 这样它只能被"有大块别的墨"那一条挡住；去掉那一条，函数就会误判成答题框。
            m[45:53, 95:135] = True
        return m
    four = squares(4)
    assert FG._is_answer_box_block((5, 5, 130, 40), four, 1.0, 0, 0, np), \
        "四个空心方框组成的答题框没被认出来"
    assert not FG._is_answer_box_block((5, 5, 130, 40), squares(1), 1.0, 0, 0, np), \
        "只有一个方框也当成答题框（误砍题图）"
    assert not FG._is_answer_box_block((5, 5, 145, 70), squares(4, big=True),
                                       1.0, 0, 0, np), \
        "框里还有一大块别的墨（真图的主体）却被当答题框"
    # 高 95pt（超过 90pt 上限）：真图里的几个方框不许把整张图判成答题框
    assert not FG._is_answer_box_block((5, 5, 130, 100), four, 1.0, 0, 0, np), \
        "95pt 高的图里有方框却被当答题框（高度上限失效）"
    # 两个方框（每个 144px 墨）+ 两根 37×6 的横杠（各 222px，运算符不是方框）：
    # 方框只占 39% 墨。占比门槛必须挡在这里 —— 否则"有 ≥2 个方框"就够，
    # 真图里带两个方框就被砍。37pt 也贴着"大块墨"上限 38 的内侧。
    sparse = squares(2)
    sparse[35:41, 10:47] = True
    sparse[35:41, 50:87] = True
    assert not FG._is_answer_box_block((5, 5, 130, 45), sparse, 1.0, 0, 0, np), \
        "方框只占四成墨的图被当答题框（占比门槛形同虚设）"
    # 四个方框 + 两朵实心圆花：方框占墨 65%（超过 40% 门槛），
    # 所以只有"圆形是图形"这一条能挡住它 —— 专测那条，不测占比。
    yy, xx = np.ogrid[:140, :300]
    mixed = squares(4, size=30, step=40)
    for cx in (200, 230):
        mixed |= ((xx - cx) ** 2 + (yy - 25) ** 2) <= 9 ** 2
    assert not FG._is_answer_box_block((5, 5, 250, 50), mixed, 1.0, 0, 0, np), \
        "方框旁边有圆（花）却被当答题框砍掉"


def banner_rule_is_wired_into_find_figures():
    """接线检查：家具行占比这条必须跑在 find_figures 里，不是只存在于函数里。"""
    import app.extractor.figures as FG
    from app.extractor.figures import find_figures, PageSource
    import numpy as np
    k = FG.DPI_PROBE / 72.0

    # 一页 200×200：第 1 题在 y=60，横幅色块在 y=100–152，第 2 题在 y=180。
    # 家具行只盖住色块的左 120pt（真卷的 OCR 行框也比色块窄一点）：
    # 右边 10pt 竖边把上下两条边连成【一个】候选，框里有 72% 的墨落在墙里。
    # ⚠️ 不能让上下两条边各自独立：它们只有 6pt 高，会先被 thin-horizontal 砍掉，
    #    那样测到的就不是家具行占比这条判据了（第一版夹具实测正是这样）。
    g = np.full((int(200 * k), int(200 * k)), 255, dtype=np.uint8)
    g[int(100 * k):int(152 * k), int(20 * k):int(150 * k)] = 100   # 横幅色块
    g[int(60 * k):int(64 * k), int(20 * k):int(150 * k)] = 30      # 第 1 题文字墨
    g[int(180 * k):int(184 * k), int(20 * k):int(150 * k)] = 30    # 第 2 题文字墨
    src = PageSource(1, 200.0, 200.0, g, lambda rect, out: None)
    spans = [
        {"q_index": 0, "page": 1, "col": 0, "y0": 55.0, "y1": 175.0, "x0": 0.0, "x1": 200.0,
         "text_boxes": [{"x": 20, "y": 60, "w": 130, "h": 4},
                        {"x": 20, "y": 106, "w": 120, "h": 40, "text": "第二步 练变式"}]},
        {"q_index": 1, "page": 1, "col": 0, "y0": 175.0, "y1": 200.0, "x0": 0.0, "x1": 200.0,
         "text_boxes": [{"x": 20, "y": 180, "w": 130, "h": 4}]},
    ]
    rep = []
    got = find_figures({1: src}, spans, OUT, report=rep)
    dropped = [d for d in rep if not d.get("kept") and d.get("why") == "furniture-row"]
    assert dropped, f"横幅没被家具行判据砍掉：{rep}"
    assert not got.get(0), f"横幅仍挂在第 1 题上：{got.get(0)}"


def banner_rule_wiring_end_to_end():
    """接线检查（走真实文字层）：栏目横幅必须由 find_figures 自己砍掉。"""
    path = os.path.join(OUT, "横幅接线.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 第一题的题干文字内容。")
    page.draw_rect(pymupdf.Rect(40, 155, 230, 193), color=None,
                   fill=(0.88, 0.46, 0.12))
    _txt(page, 46, 184, "第二步 练变式", size=26)
    _txt(page, 40, 260, "2. 第二题的题干文字内容。")
    doc.save(path)
    doc.close()
    _r, _res, qs, spans, got = run(path)
    assert len(qs) >= 2, f"夹具没切成 2 题：{[q['text'][:10] for q in qs]}"
    assert not got.get(0), f"横幅没砍掉，仍挂在第 1 题：{got.get(0)}"
    assert any("第二步" in str(t.get("text") or "")
               for t in spans[0].get("text_boxes") or []), \
        f"夹具没把横幅放进第 1 题区间（这条测试就白测了）：{spans[0].get('text_boxes')}"


CASES = [
    ("同一行被文字行切断的图要并回一张（第2页标注图）", side_by_side_pieces_join_one_figure),
    ("同一张图被裁两遍：罩住的小框要丢掉", contained_duplicate_crop_is_dropped),
    ("横向缝合真的接在裁图链路上（接线检查）", side_stitch_is_wired_into_find_figures),
    ("同行被砍的小括号要并回图框（算式不许被截断）", row_peers_join_the_crop),
    ("横版两栏：裁图不许跨栏", two_column_crops_stay_in_their_own_column),
    ("两栏纯文字：一张废图都不裁（反例）", pure_text_two_column_crops_nothing),
    ("大题题头是硬墙：共享图挂本大题第一小题", section_header_is_a_wall),
    ("图里带标注字：图不能被判没", figure_with_labels_inside_is_kept),
    ("一题两张图：必须出两张，不许并成巨框", two_figures_in_one_question_stay_two),
    ("配图必须真的印进 PDF（含缺文件要报数）", figures_actually_land_in_the_pdf),
    ("页脚「共 N 页」必须等于真实页数（配图占版面）", footer_page_total_matches_when_figures_take_space),
    ("图形占位不算栏缝：两栏不能被切成四栏", fake_gutter_from_figure_is_rejected),
    ("一张格子平面图不许切成两块（用户截图）", one_diagram_is_not_cut_into_pieces),
    ("一张图不许被自己那行标签切成上下两块", one_diagram_cut_by_its_own_label_row),
    ("图顶那行标签不许缺（被挖掉的行要吸回来）", clipped_top_label_row_is_absorbed),
    ("页边装订栏不许当配图", page_margin_strip_is_not_a_figure),
    ("贴页边的侧栏复合块不许当配图（88×125）", flush_edge_sidebar_composite_is_not_a_figure),
    ("每页都印的页脚 logo 不许当配图", repeated_page_furniture_is_not_a_figure),
    ("数轴不许被文字残影规则砍掉（反例）", number_line_survives_text_residual_rule),
    ("文字残影：一行字不许当配图，数轴例外", text_line_residual_is_not_a_figure),
    ("一题限量必须挑大的，不许按 y 截断", cap_keeps_the_biggest_not_the_topmost),
    ("淡蓝框线的图也要裁得出来（自适应墨门限）", light_coloured_diagram_is_still_found),
    ("算式图右边的括号不许被切掉", trailing_bracket_of_an_equation_is_inside_the_crop),
    ("题界穿过一张图：上下两半要缝回一张（含反例）", figure_split_by_a_question_boundary_is_stitched),
    ("灰底页不许整页当一张图", dirty_background_does_not_become_one_giant_figure),
    ("括号圈进裁图：接线检查", equation_bracket_wiring_end_to_end),
    ("跨题缝合：接线检查", straddling_figure_wiring_end_to_end),
    ("题干和图注并成一行：只吸图注那片", merged_label_row_absorbs_only_the_fragment),
    ("小版面门槛按栏宽缩放（含只放宽不收紧）", small_page_gate_scales_with_the_column),
    ("圈小标点不许把换行正文串进图里", short_mark_extension_skips_wordy_boxes),
    ("页脚与扫描 app logo 是墙，不许缝进题图", page_footer_is_a_wall_not_a_seam),
    ("裁框上沿不许吞掉本题起手句（含三个反例）", crop_top_edge_does_not_swallow_the_stem_first_line),
    ("裁框上沿不许吞掉题干第二行（含三个反例）", crop_top_edge_does_not_swallow_the_stem_second_line),
    ("裁框上沿不许吞掉图内标注（非第一行须贴左沿）", crop_top_edge_skips_figure_labels_inside_the_picture),
    ("栏目横幅与答题框行不许当配图", banner_and_answer_boxes_are_not_figures),
    ("家具行占比/答题框判据的反例（真图不许砍）", junk_crop_measures_keep_real_figures),
    ("家具行判据接线检查（含丢弃原因）", banner_rule_is_wired_into_find_figures),
    ("栏目横幅接线（真实文字层）", banner_rule_wiring_end_to_end),
]
for name, fn in CASES:
    t(name, fn)

shutil.rmtree(OUT, ignore_errors=True)
print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
