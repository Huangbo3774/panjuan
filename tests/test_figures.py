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
    # 左栏第 2 题的图故意放得比右栏下一题（第 4 题）还低：下界若退回
    # "全局下一题"而不看栏，第 2 题的区间会在第 4 题的行被截断，这张图
    # 就整块失配（详见下方断言）。
    if figures:
        _compass(page, 120, 480, 46)
    # 右栏
    _txt(page, 450, 70, "二、看图计算。")
    _txt(page, 450, 100, "3. 根据右面的平面图，商场在公园的")
    _txt(page, 450, 118, "（   ）面。")
    if figures:
        _grid(page, 470, 150, 640, 270)
    _txt(page, 450, 430, "4. 公园一圈长 120 米，小明走半圈是")
    _txt(page, 450, 448, "（   ）米。")
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
    assert seen >= 3, f"左栏两题各一张、右栏第 3 题一张，却只裁出 {seen} 张：{got}"
    # ⚠️ 只遍历 got 看不出"整道题一张图都没裁到"——必须点名到题。
    # 左栏第 2 题（索引 1）的罗盘图放在右栏第 4 题（索引 3）起手行之下：
    # 区间下界一旦退回"全局下一题、不看栏"，第 2 题的区间会在第 4 题那行
    # 被截断，图整块失踪；只看"每题最多一张"永远发现不了。
    assert {0, 1, 2} <= set(got), (
        "左栏第 2 题的图被别的栏的下一题截掉了：只裁到 " + str(sorted(got)))
    assert 3 not in got, "第 4 题是纯文字，不该裁出图：" + str(got.get(3))
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


def whole_span_question_number_is_not_printed_twice():
    """整题原图已含题号：题干被清空时不许再印一个孤零零的题号。

    P5 Q20 的图裁到页底时，题干为空 → 先印 "20."，图放不下换页 →
    第 5 页底部只剩 "20."，图孤零零地跑到第 6 页。整题图从题号行起裁，
    题号已在图里；题干为空时不再另印。反例：普通配图没有题号，必须照印。
    """
    from app.layout.options import LayoutOptions
    from app.papers.answer_writer import render_answers_pdf

    fig_dir = os.path.join(OUT, "figs_span_qno")
    os.makedirs(fig_dir, exist_ok=True)
    png = os.path.join(fig_dir, "q20.png")
    d = pymupdf.open()
    pg = d.new_page(width=200, height=40)
    pg.draw_rect(pymupdf.Rect(2, 2, 198, 38), color=(0, 0, 0), width=1)
    pg.get_pixmap(dpi=150).save(png)
    d.close()

    qs = [
        {"uid": "四#20", "q_no": 20, "section": "四、解方程", "qtype": "unknown",
         "text": "", "images": [{"name": "q20.png", "page": 1, "w_pt": 200.0,
                                 "h_pt": 40.0, "graphic": True,
                                 "graphic_kind": "calc-span"}]},
        {"uid": "四#21", "q_no": 21, "section": "四、解方程", "qtype": "unknown",
         "text": "", "images": [{"name": "q20.png", "page": 1, "w_pt": 200.0,
                                 "h_pt": 40.0}]},
    ]
    out = os.path.join(OUT, "整题图题号.pdf")
    render_answers_pdf(qs, LayoutOptions.from_dict({"show_header": True}), out,
                       title="整题图题号检查", mode="blank", figures_dir=fig_dir)
    doc = pymupdf.open(out)
    text = "".join(p.get_text() for p in doc).replace(" ", "")
    doc.close()
    assert "20." not in text, f"整题原图已含题号，又印了一遍：{text[:200]}"
    assert "21." in text, f"普通配图丢了题号：{text[:200]}"


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


def crop_bottom_edge_does_not_swallow_the_stem_last_line():
    """裁框下沿把【本题最后一行题干】整行盖住 → 下沿收到这一行上面。

    坐标取自真实卷（第三单元练习题.pdf 第 8 页第 30 题 青蛙跳数轴）：
    数轴在上，"青蛙1次跳4格,兔子1次跳( )个4格。兔子跳1次的距离是青蛙的"
    这一行 y403.3–422.0 整行落进裁框（原始裁框下沿 430.7，行底离下沿 8.7pt），
    印出来图里抄了半句题干，题干又完整留着这一句（审计 含题干 q30）。
    OCR 行框底和裁框之间还留着 8.7pt 的墨（标点/行距），所以下沿的容差
    比上沿的 4pt 宽，是 12pt —— 上沿那条尺子对这里完全瞎。

    ⚠️ 直接喂真实坐标：合成 PDF 里行框和字永远对齐，造不出这种"下沿多探半行"。
    """
    import app.extractor.figures as FG
    rows = [{"x": 59.9, "y": 317.3, "w": 126.1, "h": 16.5, "text": "2.画一画,填一填。"},
            {"x": 248.6, "y": 378.6, "w": 266.8, "h": 20.1,
             "text": "9101112131415161718192021"},
            {"x": 77.1, "y": 403.3, "w": 486.3, "h": 18.7,
             "text": "青蛙1次跳4格,兔子1次跳(      )个4格。兔子跳1次的距离是青蛙的"},
            {"x": 113.9, "y": 429.4, "w": 398.3, "h": 21.0,
             "text": ")倍。画一画,青蛙从0开始跳,跳5次一共跳了（     )格。"}]
    rect = (69.7, 343.3, 513.5, 430.7)
    cut = FG._clip_stem_row_bottom(rect, rows)
    assert cut[3] <= 402.4, f"末行题干还框在图里：y1={cut[3]:.1f}，应收到 402.3"
    assert cut[0] == rect[0] and cut[1] == rect[1] and cut[2] == rect[2], \
        f"只许动下沿，别乱收：{cut}"

    # 正例②：框底压着【三行】阅读材料，只有末行带句号，上面两行是逗号/分号续行。
    # 真实卷（综合实践单元(1) 第 23 题）：旧版只收末行 → 前两行被当"图内重复
    # 文字"删掉，题干留下一个孤零零的 ")"（审计 做不了·括号残缺）。续行要一起收。
    read_rows = [
        {"x": 201.4, "y": 155.8, "w": 160.0, "h": 5.5,
         "text": "2.请为2号无人配送车设计一条行驶路线。画一画。（6分）"},
        {"x": 193.2, "y": 199.7, "w": 150.0, "h": 6.5,
         "text": "附加题。(共10分)"},
        {"x": 214.8, "y": 211.7, "w": 130.0, "h": 6.2,
         "text": "山的南面与水的北面光照更    “贵阳”因位于贵山的（"},
        {"x": 205.9, "y": 222.7, "w": 139.2, "h": 5.5,
         "text": "充足，故称“阳”；山的北面与水的    而得名，“江阴”因位于长江的"},
        {"x": 205.9, "y": 232.3, "w": 112.1, "h": 6.2,
         "text": "南面光照较少，故称“阴”。            )面而得名。"}]
    read_rect = (197.9, 162.3, 363.7, 247.1)
    cut2 = FG._clip_stem_row_bottom(read_rect, read_rows)
    assert cut2[3] <= 198.8, \
        f"三行阅读材料只收了末行：y1={cut2[3]:.1f}，应收到 198.7"
    assert cut2[0] == read_rect[0] and cut2[1] == read_rect[1] \
        and cut2[2] == read_rect[2], f"只许动下沿：{cut2}"

    # 反例①：这一行是被规则⑤当【图注】吸回来的（气泡/标签）→ 不许裁
    assert FG._clip_stem_row_bottom(rect, rows, [2]) == rect, "把吸回来的图注裁掉了"
    # 反例②：横向只盖住 66%（<80%）→ 不是"整行框住"，不许削这一刀
    graze = (69.7, 343.3, 400.0, 430.7)
    assert FG._clip_stem_row_bottom(graze, rows) == graze, "只蹭到一段就裁，阈值等于没写"
    # 反例③：从图中间起句的标注（行首差 179pt）—— 哪怕成句也不许裁
    mid_rows = [rows[0], rows[1],
                {"x": 248.6, "y": 403.3, "w": 180.0, "h": 18.7,
                 "text": "箭头表示向东走3格。"}]
    assert FG._clip_stem_row_bottom(rect, mid_rows) == rect, "把图里的标注句裁掉了"
    # 反例④：图注没有句号/空位（"青蛙跳格路线示意图"）→ 不是题干，不许裁
    cap_rows = [rows[0], rows[1],
                {"x": 77.1, "y": 403.3, "w": 200.0, "h": 18.7,
                 "text": "青蛙跳格路线示意图"}]
    assert FG._clip_stem_row_bottom(rect, cap_rows) == rect, "把题注当题干裁了"
    # 反例⑤：图里的短标注（"北。"）贴着下沿也不收 —— 不足 8 个字。
    #   ⚠️ 必须带句号，否则先被"成句"那条拦下，字数门槛等于没测（第一版就是假绿）。
    tiny_rows = [rows[0], rows[1],
                 {"x": 77.1, "y": 403.3, "w": 30.0, "h": 18.7, "text": "北。"}]
    assert FG._clip_stem_row_bottom(rect, tiny_rows) == rect, "把图里的短标注裁了"
    # 反例⑥：行底离下沿 18pt —— 下面还有别的东西，不是贴着下沿的那一行
    far = (69.7, 343.3, 513.5, 440.0)
    assert FG._clip_stem_row_bottom(far, rows) == far, "离下沿很远也裁，容差等于没写"
    # 反例⑦：整行盖住、但收完下沿就没图了（只剩 3.3pt）→ 宁可重复一行题干
    thin = (69.7, 399.0, 513.5, 430.7)
    assert FG._clip_stem_row_bottom(thin, rows) == thin, "把图裁到 8pt 以下，题就没图做了"
    # 反例⑧：末行上方 35pt 还横着一行图内说明（远超过正常行距）→ 不许顺着往上收
    gap_rows = [rows[0],
                {"x": 77.1, "y": 350.0, "w": 400.0, "h": 18.0,
                 "text": "图里的说明文字，离末行题干很远，不是它的续行。"},
                rows[2]]
    gap_rect = (69.7, 300.0, 513.5, 430.7)
    cut4 = FG._clip_stem_row_bottom(gap_rect, gap_rows)
    assert 390.0 < cut4[3] <= 402.4, \
        f"把 35pt 外的图内说明也当续行收进来了：y1={cut4[3]:.1f}"
    # 反例⑨：OCR 把四个气球的【人名+气泡】并成一行，贴着下沿、带空位、
    #   ≥8 字 —— 三条判据全过，但它是图里的标签，不是末行题干。
    #   真实卷（综合实践单元.pdf 第 1 页第 6 题）：旧版削到 118.0，
    #   下面两个气泡只剩"我没站在东面,我"半句（审计 切边 下+59px）。
    bubble_rows = [
        {"x": 462.6, "y": 33.6, "w": 267.5, "h": 16.2,
         "text": "6．小朋友们分别站在东、南、西、北4个方向做游戏。"},
        {"x": 540.2, "y": 62.5, "w": 191.6, "h": 12.7,
         "text": "我站在北面。            我站在明明的对面"},
        {"x": 500.7, "y": 81.2, "w": 274.8, "h": 13.6,
         "text": "明明            我站在(     )面。           小华"},
        {"x": 539.7, "y": 99.5, "w": 192.5, "h": 12.7,
         "text": "我没站在东面，我           我站在(     )面"},
        {"x": 501.2, "y": 119.0, "w": 275.6, "h": 13.6,
         "text": "兰兰     站在（    )面。            小红"}]
    bubble_rect = (493.8, 52.4, 784.2, 142.0)
    assert FG._clip_stem_row_bottom(bubble_rect, bubble_rows) == bubble_rect, \
        "把气泡里的人名标签行当末行题干削掉了"
    assert FG._clip_stem_row_bottom(rect, []) == rect, "没有文字行时不该改动裁框"


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


def crop_top_edge_cuts_through_the_stem_first_line():
    """裁框上沿从【本题第一行字的中间】切过（cov 0.67）也要收。

    周末作业(1) p2 第 3 题实测：题干行 553.5–573.1，裁框上沿 560.0 正好切在
    字中间，`_covers` 只有 0.67，按 80% 的门槛永远收不掉 —— 图顶留着半行题干
    和题号徽标。这是"贴顶行"判据唯一的例外：只对【本题第一行】降到 0.5。

    ⚠️ 直接喂真实坐标：合成 PDF 里行框和字永远对齐，造不出"从字中间切"。
    """
    import app.extractor.figures as FG
    stem = "3.下面各图中，涂色部分能用分数表示的是（    ）。"
    rows = [{"x": 60.0, "y": 553.5, "w": 300.0, "h": 19.6, "text": stem},
            {"x": 60.0, "y": 600.0, "w": 200.0, "h": 12.0, "text": "图里的标注"}]
    rect = (50.0, 560.0, 400.0, 668.8)
    cut = FG._clip_stem_row(rect, rows)
    assert cut[1] >= 574.1, f"被上沿切开的起手句没收：y0={cut[1]:.1f}，应收到 574.1"
    assert cut[0] == rect[0] and cut[2] == rect[2] and cut[3] == rect[3], \
        f"只许动上沿：{cut}"

    # 反例①：同一个行框，但【不是第一行】（上面还压着一行题干）→ 不许收。
    #   它贴左沿、也成句 —— 唯一拦住它的就是"只认第一行"。
    r2 = [{"x": 60.0, "y": 520.0, "w": 300.0, "h": 16.0, "text": "2.先看左边的图，再填空。"}] + rows
    assert FG._clip_stem_row(rect, r2) == rect, "例外扩散到了第二行"
    # 反例②：切开了、也够长，但没有句末标点/空位 → 像图注，不许收
    r3 = [{"x": 60.0, "y": 553.5, "w": 300.0, "h": 19.6, "text": "涂色部分能用分数表示的是哪一幅图"},
          rows[1]]
    assert FG._clip_stem_row(rect, r3) == rect, "没有成句标点的标签行被当成题干"
    # 反例③：只蹭到行框下沿（cov 0.26 < 0.50）→ 框里没有字，不许削图顶
    graze = (50.0, 568.0, 400.0, 668.8)
    assert FG._clip_stem_row(graze, rows) == graze, "覆盖率下限 0.50 没起作用"
    # 反例④：第一行被切开但不足 8 字（图注"图1"）
    r4 = [{"x": 60.0, "y": 553.5, "w": 30.0, "h": 19.6, "text": "图1。"}, rows[1]]
    assert FG._clip_stem_row(rect, r4) == rect, "短图注被当成起手句"


def crop_top_edge_narrow_tail_of_a_long_stem_row():
    """窄图贴在长题干行的右下角：面积覆盖率只有 0.24，框里却真有字。

    真实卷（综合实践单元(1) p2 第 6 题 2 号配送车）：裁框
    (301.6,154.7,345.8,198.8)，题干行框 155.8–161.3、横向只重叠 34pt。
    `_covers` 算的是面积占比，于是"只蹭到一点"的反例把这一刀挡住了，
    成品图顶带着半行"画一画。（6分）"。

    ⚠️ 必须喂像素：判据是"重叠区里有没有墨"，不是面积。
    """
    import numpy as np
    import app.extractor.figures as FG

    class Src:
        pass
    src = Src()
    src.ink_thr = 128
    src.gray = np.full((420, 560), 255, dtype=np.uint8)
    k = 100 / 72.0
    row = {"x": 201.4, "y": 155.8, "w": 134.6, "h": 5.5,
           "text": "2.请为2号无人配送车设计一条行驶路线。画一画。（6分）"}
    rect = (301.6, 154.7, 345.8, 198.8)
    # 只在题干行与裁框的重叠区里点墨（模拟"画一画。（6分）"这半行）
    y0, y1 = int(156.0 * k), int(161.0 * k)
    x0, x1 = int(303.0 * k), int(335.0 * k)
    src.gray[y0:y1, x0:x1] = 0
    cut = FG._clip_stem_row(rect, [row], src=src, k=k)
    assert cut[1] >= 162.0, f"窄图顶上的半行题干没收：y0={cut[1]:.1f}"

    # 反例①：同样的行/框，但重叠区是白纸 → 框里没有字，不许削图顶
    src2 = Src()
    src2.ink_thr = 128
    src2.gray = np.full((420, 560), 255, dtype=np.uint8)
    assert FG._clip_stem_row(rect, [row], src=src2, k=k) == rect, "白纸上也削了图顶"

    # 反例②：不传像素时保持旧行为（面积覆盖率 0.24 不收）
    assert FG._clip_stem_row(rect, [row]) == rect, "旧调用没有 src 也改了框"

    # 反例③：行框顶已经在裁框顶下方超过 4pt → 是图自己的标注，不收
    inside = {"x": 201.4, "y": 170.0, "w": 134.6, "h": 5.5,
              "text": "2.请为2号无人配送车设计一条行驶路线。画一画。（6分）"}
    assert FG._clip_stem_row(rect, [inside], src=src, k=k) == rect, "图内标注被裁了"

    # 反例④：短标签（"北 东"）即使压到裁框上沿、重叠区真有墨，也不当题干。
    # 这里把上沿抬到 157.9，让面积覆盖率掉到 0.62（低于 0.8 的主判据），
    # 只剩新加的"重叠区有墨"这条分支可能命中 —— 必须被"≥8 字"挡住。
    short = {"x": 301.4, "y": 155.8, "w": 30.0, "h": 5.5, "text": "北 东"}
    short_rect = (301.6, 157.9, 345.8, 198.8)
    assert FG._clip_stem_row(short_rect, [short], src=src, k=k) == short_rect, "短图注被当题干"
    long_row = {"x": 301.4, "y": 155.8, "w": 30.0, "h": 5.5,
                "text": "2.请为2号无人配送车设计一条行驶路线。"}
    assert FG._clip_stem_row(short_rect, [long_row], src=src, k=k)[1] > short_rect[1], \
        "同样的几何、换成题干长句却不收（分支没生效）"

    # 反例⑤：OCR 把题干和图内气泡并成一行（中间夹着一大段空白）。
    # 真实卷（综合实践单元(1) p1 第 4 题）："…背靠背夹    我面向东。"
    # 若拿整行去收图顶，孩子头顶和气泡一起被切掉，题目没法答。
    merged = {"x": 201.4, "y": 155.8, "w": 134.6, "h": 5.5,
              "text": "4.如右图所示，两名同学玩背靠背夹    我面向东。"}
    assert FG._clip_stem_row(rect, [merged], src=src, k=k) == rect, \
        "题干与气泡并成一行时把图顶削了（气泡被切）"
t("窄图的题干行字尾要收（含四个反例）", crop_top_edge_narrow_tail_of_a_long_stem_row)


def text_edge_fragment_is_not_a_figure():
    """只有多行正文右端字尾的窄条不是配图（附例题的 14×38pt 文字残片）。"""
    import app.extractor.figures as FG
    rows = [
        {"x": 214.8, "y": 211.7, "w": 113.8, "h": 6.2,
         "text": "山的南面与水的北面光照更    “贵阳”因位于贵山的（"},
        {"x": 205.9, "y": 222.7, "w": 139.2, "h": 5.5,
         "text": "充足，故称“阳”；山的北面与水的    而得名，“江阴”因位于长江的"},
        {"x": 205.9, "y": 232.3, "w": 112.1, "h": 6.3,
         "text": "南面光照较少，故称“阴”。            )面而得名。"},
    ]
    strip = (331.8, 208.7, 345.8, 246.4)
    assert FG._is_text_edge_fragment(strip, rows), "文字字尾条被当成配图"

    # 反例①：宽 30pt → 已经像一块真图（地图/表格的一列），不砍
    assert not FG._is_text_edge_fragment((331.8, 208.7, 361.8, 246.4), rows), "宽条被砍"
    # 反例②：只压着一行 → 不够证明是多行字尾
    assert not FG._is_text_edge_fragment(strip, rows[:1]), "单行也砍"
    # 反例③：窄条在行框左边远处 → 不是字尾
    assert not FG._is_text_edge_fragment((150.0, 208.7, 164.0, 246.4), rows), "左侧独立窄图被砍"
    # 反例④：行框本身很短（图内标签）→ 不参与证明
    labels = [{"x": 300.0, "y": 211.0, "w": 30.0, "h": 6.0, "text": "北"},
              {"x": 300.0, "y": 222.0, "w": 30.0, "h": 6.0, "text": "东"}]
    assert not FG._is_text_edge_fragment(strip, labels), "短标签凑成了文字残片"
t("正文右端字尾的窄条不是配图（含四个反例）", text_edge_fragment_is_not_a_figure)


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

    # 边框条：表格自己的底边被文字洞切断，只剩宽 113.8pt、高 6pt 的一截，
    # 和表身只压住 0.1pt。这不是"同行小块"，但必须并回来，否则表格缺底边。
    # 真实卷（综合实践单元(1) p1 第 3 题记录单，审计 切边 下+237px）。
    table = (81.2, 372.8, 409.8, 462.8)
    strip = (295.9, 462.7, 409.7, 468.7)
    flags: list[str] = []
    g5 = FG._absorb_row_peers(table, [strip], (0, 0, 500, 500), flags)
    assert abs(g5[3] - 468.7) < 0.01 and flags == ["bottom"], (g5, flags)
    assert g5[:2] == table[:2] and g5[2] == table[2], f"边框条不许改别的沿：{g5}"
    # 顶边同理
    top_strip = (295.9, 366.8, 409.7, 372.9)
    g6 = FG._absorb_row_peers(table, [top_strip], (0, 0, 500, 500))
    assert abs(g6[1] - 366.8) < 0.01, f"表格顶边没并回来：{g6}"
    # 反例①：薄到 1.5pt 的扫描线（不是 3–12pt 的边框条）
    line = (295.9, 462.7, 409.7, 464.2)
    assert FG._absorb_row_peers(table, [line], (0, 0, 500, 500)) == table
    # 反例②：宽度不足图宽 30%（那是一个小图标，不是整条边框）
    short = (250.0, 462.7, 330.0, 468.7)
    assert FG._absorb_row_peers(table, [short], (0, 0, 500, 500)) == table
    # 反例③：离下沿 12pt（>10pt）→ 另一行的一块图，不是这条边框
    far = (295.9, 474.8, 409.7, 480.8)
    assert FG._absorb_row_peers(table, [far], (0, 0, 500, 500)) == table
    # 反例④：伸出图的右沿 60pt → 是邻块的横线，不是表格底边
    overhang = (350.0, 462.7, 470.0, 468.7)
    assert FG._absorb_row_peers(table, [overhang], (0, 0, 500, 500)) == table


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


def answer_blanks_and_merged_squares_are_not_figures():
    """两条新判据的正反例：空白作答行、被扫描连成一块的答题框。

    真实卷缺陷（第三单元练习题 p2）：
      · 第 1 题 181×49 的「读作:( )」：两对括号＋虚线点，墨占 1.6%，不是图；
        它先被切成左右两半，每半只有一对括号，所以判据必须接受一对。
      · 第 4 题 164×38 的 `□×□=□( )`：扫描把两个方框和运算符连成 65.5×25.2pt
        一块，分类器叫它 minus；按内腔数才能数出两个方框。
    反例必须当场量：任何 ≥18pt 的墨块都不许被空白行判据砍；两行方格图不算一行方框。
    """
    import numpy as np
    import cv2
    import app.extractor.figures as FG

    def arc(m, cx, cy, a0, a1):
        img = np.zeros(m.shape, dtype=np.uint8)
        cv2.ellipse(img, (cx, cy), (4, 6), 0, a0, a1, 1, 2)
        m |= img.astype(bool)

    blanks = np.zeros((60, 260), dtype=bool)
    for x in (20, 100):
        arc(blanks, x, 35, 90, 270)          # 左半弧 → paren_open
        arc(blanks, x + 25, 35, -90, 90)     # 右半弧 → paren_close
    for x in (70, 150):
        for y in range(10, 27, 8):
            blanks[y:y + 3, x:x + 3] = True  # 虚线引导点
    assert FG._is_blank_answer_row((0, 0, 260, 60), blanks, 1.0, 0, 0, np), \
        "两对括号＋虚线点组成的空白作答行没被认出来"
    assert not FG._is_blank_answer_row((0, 0, 260, 60), np.zeros_like(blanks), 1.0, 0, 0, np), \
        "全白也当空白作答行（没有括号）"
    no_close = blanks.copy()
    for x in (45, 125):
        no_close[:, x - 1:x + 6] = False
    assert not FG._is_blank_answer_row((0, 0, 260, 60), no_close, 1.0, 0, 0, np), \
        "只有左括号也对"
    big = blanks.copy()
    big[50:58, 200:226] = True                # 26×8 的一块实墨
    assert not FG._is_blank_answer_row((0, 0, 260, 60), big, 1.0, 0, 0, np), \
        "有一块 26pt 的实墨（真图/算式主体）却被当空白行"

    def hollow(m, x, y, s):
        m[y:y + s, x:x + 2] = True
        m[y:y + s, x + s - 2:x + s] = True
        m[y:y + 2, x:x + s] = True
        m[y + s - 2:y + s, x:x + s] = True

    row = np.zeros((40, 100), dtype=bool)
    hollow(row, 5, 5, 20)
    hollow(row, 55, 5, 20)
    row[13:15, 25:55] = True                  # 扫描把两块连成一个连通域
    assert FG._merged_square_units(row[5:25, 5:75], 1.0, cv2, np) == 2, \
        "连成一排的两个空方框没按内腔数出来"
    assert FG._merged_square_units(row[5:25, 5:25], 1.0, cv2, np) == 0, \
        "单个空方框也被当成一排（应交给原来的 square 分类）"
    stacked = np.zeros((60, 40), dtype=bool)
    hollow(stacked, 5, 5, 20)
    hollow(stacked, 5, 35, 20)
    stacked[13:15, 25:35] = True
    assert FG._merged_square_units(stacked, 1.0, cv2, np) == 0, \
        "两行方格图（不是一行空方框）被按内腔数成答题框"

    raw = np.zeros((50, 130), dtype=bool)
    raw[5:25, 5:75] |= row[5:25, 5:75]
    hollow(raw, 90, 8, 20)
    assert FG._is_answer_box_block((0, 0, 130, 50), raw, 1.0, 0, 0, np), \
        "连成一排的两个方框＋旁边一个独立方框没被认成答题框"
    raw_big = raw.copy()
    raw_big[36:44, 8:48] = True                # 40×8 的别的墨
    assert not FG._is_answer_box_block((0, 0, 130, 50), raw_big, 1.0, 0, 0, np), \
        "框里还有一大块别的墨却被当答题框"
    raw_circle = raw.astype(np.uint8)
    cv2.circle(raw_circle, (118, 40), 8, 1, -1)
    marked = raw_circle.astype(bool)
    assert not FG._is_answer_box_block((0, 0, 130, 50), marked, 1.0, 0, 0, np), \
        "方框旁边有圆（图形）却被当答题框"


def text_inside_figures_is_removed_from_stem():
    """图内标注行被 OCR 拼进题干 → 只删【整行落在本题配图框内】的那几条。

    真实卷（第三单元 p2）：第 2 题题干变成"一共有多少个蘑菇? 加法算式: 或 乘法算式: 或"，
    可这四段字本来就在蘑菇图的右侧框里，印出来会重复一遍；第 3 题末尾的
    "CL 长长" 同样是树叶图里的乱码。反例必须覆盖：只压住一半的、框外的、
    删完会变成空题的、以及题干里根本没有这串字的。
    """
    import app.extractor.figures as FG
    qs = [{"text": "一共有多少个蘑菇? 加法算式: 或 乘法算式: 或"},
          {"text": "下面的树叶片数不能用2×4表示的是(  )。(填序号) CL            长长"}]
    spans = [
        {"q_index": 0, "text_boxes": [
            {"x": 100, "y": 10, "w": 40, "h": 12, "text": "加法算式:"},
            {"x": 150, "y": 10, "w": 10, "h": 12, "text": "或"},
            {"x": 100, "y": 30, "w": 40, "h": 12, "text": "乘法算式:"},
            {"x": 150, "y": 30, "w": 10, "h": 12, "text": "或"},
        ]},
        {"q_index": 1, "text_boxes": [
            {"x": 100, "y": 10, "w": 40, "h": 12, "text": "CL 长长"}]},
    ]
    got = {0: [{"rect": [80.0, 0.0, 300.0, 60.0]}],
           1: [{"rect": [80.0, 0.0, 300.0, 60.0]}]}
    n = FG.strip_text_inside_figures(qs, spans, got)
    assert n == 5, f"应删 5 条图内文字，实际 {n}"
    assert qs[0]["text"] == "一共有多少个蘑菇?", qs[0]["text"]
    assert qs[1]["text"].endswith("(填序号)"), qs[1]["text"]

    # 起手句即使被裁框整行盖住也要留：真实卷 p4 第 3 题裁框同时盖住起手句和
    # "问题一/问题二"标签，若按顺序全删就只剩空题干。
    q5 = [{"text": "观察图片,提出两个能用6×2解决的问题。 问题一: 问题二："}]
    sp5 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 10, "w": 200, "h": 14, "text": "观察图片,提出两个能用6×2解决的问题。"},
        {"x": 100, "y": 40, "w": 120, "h": 14, "text": "问题一: 问题二："}]}]
    got5 = {0: [{"rect": [80.0, 0.0, 320.0, 60.0]}]}
    assert FG.strip_text_inside_figures(q5, sp5, got5) == 1
    # 起手句本身是完整的一句（"…解决的问题。"）→ 就算图里也印着，也不再收字。
    # 整题截图只收"看着被截断"的题干，完整句留在上面不算错。
    assert q5[0]["text"] == "观察图片,提出两个能用6×2解决的问题。", q5[0]["text"]
    assert not got5[0][0].get("whole_question")

    # 同名标签：句子里先出现一次、图里又挂一行。必须删【行序对应的后一次】，
    # 不能删句子里的「辰辰」（真实卷综合实践课 p1 第 4 题就是这么被改坏的）。
    q6 = [{"text": "辰辰从( )面走来。 辰辰"}]
    sp6 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 10, "w": 120, "h": 14, "text": "辰辰从( )面走来。"},
        {"x": 100, "y": 40, "w": 20, "h": 14, "text": "辰辰"}]}]
    got6 = {0: [{"rect": [80.0, 30.0, 160.0, 60.0]}]}
    assert FG.strip_text_inside_figures(q6, sp6, got6) == 1
    assert q6[0]["text"] == "辰辰从( )面走来。", q6[0]["text"]

    # 反方向：图内标签「散通道」在前，最后一句正文「紧急疏散通道」在后。
    # 只删行序对应的图内那一次，正文那句一个字节都不许动。
    q7 = [{"text": "下面是教学楼的平面图。 散通道 请画出从广播室到紧急疏散通道的路线。"}]
    sp7 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 10, "w": 150, "h": 14, "text": "下面是教学楼的平面图。"},
        {"x": 100, "y": 30, "w": 30, "h": 14, "text": "散通道"},
        {"x": 100, "y": 55, "w": 200, "h": 14,
         "text": "请画出从广播室到紧急疏散通道的路线。"}]}]
    got7 = {0: [{"rect": [80.0, 25.0, 160.0, 50.0]}]}
    assert FG.strip_text_inside_figures(q7, sp7, got7) == 1
    assert q7[0]["text"] == "下面是教学楼的平面图。 请画出从广播室到紧急疏散通道的路线。", \
        q7[0]["text"]

    # OCR 行框带题号、拼好的题干已剥题号：起手句若认不出，content_seen 翻不过去，
    # 紧跟其后的图注/正文就会被当"第一处"误删。真实卷（综合实践课 p1 第 2 题）
    # 行框是「2.按要求填一填。」，题干是「按要求填一填。 北 请你把指南针 …」。
    q8 = [{"text": "按要求填一填。 北 请你把指南针 上的另外三个 方向补充完整。"}]
    sp8 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 10, "w": 120, "h": 14, "text": "2.按要求填一填。"},
        {"x": 100, "y": 40, "w": 20, "h": 14, "text": "北"},
        {"x": 140, "y": 40, "w": 90, "h": 14, "text": "请你把指南针"},
        {"x": 140, "y": 60, "w": 90, "h": 14, "text": "上的另外三个"},
        {"x": 140, "y": 80, "w": 90, "h": 14, "text": "方向补充完整。"}]}]
    got8 = {0: [{"rect": [80.0, 0.0, 300.0, 100.0]}]}
    assert FG.strip_text_inside_figures(q8, sp8, got8) == 4, "题号前缀挡住了起手句"
    # 起手句 "按要求填一填。" 是完整句，图内其余四行只是说明 → 保留题干，
    # 不套整题截图（题号前缀认不出来时四条标注删不掉，这条守住 box_text_patterns）。
    assert q8[0]["text"] == "按要求填一填。", q8[0]["text"]
    assert not got8[0][0].get("whole_question")

    # 裁框上沿把一整行地图标注削掉 3.3pt（覆盖率 80%）→ 字还印在图里，题干同款行要删。
    # 真实卷（综合实践课 p1 第 3 题）：「教学楼 活动室 北 北」被留在题干。
    q9 = [{"text": "观察校园，并记录下操场的四个方向各有什么。 教学楼 活动室 北 北"}]
    sp9 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 0, "w": 200, "h": 14, "text": "观察校园，并记录下操场的四个方向各有什么。"},
        {"x": 100, "y": 29, "w": 180, "h": 16, "text": "教学楼 活动室 北 北"}]}]
    got9 = {0: [{"rect": [80.0, 32.3, 300.0, 120.0]}]}
    assert FG.strip_text_inside_figures(q9, sp9, got9) == 1, "被削掉 3.3pt 的图内行没删"
    assert q9[0]["text"] == "观察校园，并记录下操场的四个方向各有什么。", q9[0]["text"]

    # 图里的文字标签和右括号是分开的行框：删掉标签后，题干只剩"） ）"。
    # 真实卷（P5 Q12/Q16）：左侧图例写"用分数表示是（ ）"，OCR 把左括号裁进图里，
    # 只把「用分数表示是」几个字留在题干。完整句子由配图原样呈现，残渣必须清掉，
    # 否则家长看到"…占整图的多少， ） ）"，以为题目被弄坏了。
    q11 = [{"text": "观察下图，分别用不同的数表示图中阴影部分占整幅图的多少，"
                    "用分数表示是 ），用百分数表示是 ）"}]
    sp11 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 10, "w": 80, "h": 12, "text": "用分数表示是"},
        {"x": 100, "y": 30, "w": 90, "h": 12, "text": "用百分数表示是"}]}]
    got11 = {0: [{"rect": [80.0, 0.0, 320.0, 60.0]}]}
    assert FG.strip_text_inside_figures(q11, sp11, got11) == 2
    assert q11[0]["text"] == "观察下图，分别用不同的数表示图中阴影部分占整幅图的多少", \
        q11[0]["text"]
    # 反例 5：本题没有配图 → 残缺就是真残缺，尾巴一个字符都不许动（要留给人看）
    q12 = [{"text": "如下图所示，可以拼成近似的长方形。 ）"}]
    assert FG.strip_text_inside_figures(q12, [], {}) == 0
    assert q12[0]["text"] == "如下图所示，可以拼成近似的长方形。 ）", q12[0]["text"]
    # 反例 6：句尾右括号有配对的左括号（是真的括注）→ 不许当成残渣删
    q13 = [{"text": "这扇窗户的面积是（ ）平方米（π取3.14） 图注"}]
    sp13 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 40, "w": 30, "h": 12, "text": "图注"}]}]
    got13 = {0: [{"rect": [80.0, 35.0, 160.0, 60.0]}]}
    assert FG.strip_text_inside_figures(q13, sp13, got13) == 1
    assert q13[0]["text"] == "这扇窗户的面积是（ ）平方米（π取3.14）", q13[0]["text"]

    # 反例 1：只压住一半（横向 50%）→ 那是图上方真正的题干，不许删
    q2 = [{"text": "一共有多少个蘑菇? 加法算式:"}]
    sp2 = [{"q_index": 0, "text_boxes": [
        {"x": 280, "y": 10, "w": 40, "h": 12, "text": "加法算式:"}]}]
    assert FG.strip_text_inside_figures(q2, sp2, {0: [{"rect": [80.0, 0.0, 300.0, 60.0]}]}) == 0
    assert q2[0]["text"] == "一共有多少个蘑菇? 加法算式:"
    # 反例 2：框外文字（本题没图也一样）
    q3 = [{"text": "加法算式:"}]
    assert FG.strip_text_inside_figures(q3, spans[:1], {}) == 0
    assert q3[0]["text"] == "加法算式:"
    # 反例 3：删完就空了 → 宁可留残渣，不交白卷
    q4 = [{"text": "加法算式:"}]
    sp4 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 10, "w": 40, "h": 12, "text": "加法算式:"}]}]
    assert FG.strip_text_inside_figures(q4, sp4, {0: [{"rect": [80.0, 0.0, 300.0, 60.0]}]}) == 0
    assert q4[0]["text"] == "加法算式:"
    # 反例 4：纵向在框外 8pt（面积还有 73%）→ 那是图上方真正的题干行，不许删。
    # 这条守住"削边放宽到 6pt"那一档，防止放宽变成"贴边就删"。
    q10 = [{"text": "观察校园，并记录下操场的四个方向各有什么。 教学楼 活动室 北 北"}]
    sp10 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 0, "w": 200, "h": 14, "text": "观察校园，并记录下操场的四个方向各有什么。"},
        {"x": 100, "y": 24, "w": 180, "h": 30, "text": "教学楼 活动室 北 北"}]}]
    got10 = {0: [{"rect": [80.0, 32.0, 300.0, 120.0]}]}
    assert FG.strip_text_inside_figures(q10, sp10, got10) == 0, "框外 8pt 的题干行被删"
    assert q10[0]["text"].endswith("教学楼 活动室 北 北"), q10[0]["text"]


def stem_line_above_is_joined_into_whole_question_image():
    """题干第一行在图框上方、续行在图里 → 把第一行接进图，按整题原图收掉文字。

    真实卷（P1 Q2/Q5）：扫描页上题干第一行在裁框外，成品上停在"付了50元，找回"，
    下一行图片才接"26元。…"，看着像题干被截断。接框后整道题印一张图，
    导出不再重排 OCR 文字（whole_question）。反例：有 OCR 选项（选项在图外）、
    纯尺寸标注的图形、上面那行不是本题题干。
    """
    import app.extractor.figures as FG

    class _Src:
        width_pt = 363.7
        height_pt = 500.0

        def __init__(self):
            self.calls = []

        def crop(self, rect, out):
            self.calls.append((tuple(rect), out))

    boxes = [
        {"x": 24.1, "y": 216.4, "w": 278.7, "h": 11.1,
         "text": "2.在准备新年联欢会时，王老师买了几袋同一种糖，付了50元，找回"},
        {"x": 35.6, "y": 235.4, "w": 113.4, "h": 9.8,
         "text": "26元。她买的糖不可能是（"},
        {"x": 45.0, "y": 257.8, "w": 242.3, "h": 12.9,
         "text": "每袋3元            每袋4元            每袋5元            每袋6元"},
        {"x": 54.7, "y": 299.9, "w": 217.1, "h": 8.6,
         "text": "A            B            D"},
    ]
    q = [{"text": "在准备新年联欢会时，王老师买了几袋同一种糖，付了50元，找回"}]
    sp = [{"q_index": 0, "text_boxes": boxes}]
    src = _Src()
    got = {0: [{"name": "q2.png", "page": 1,
                "rect": [11.5, 231.0, 300.4, 310.5], "w_pt": 288.9, "h_pt": 79.5}]}
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        FG.strip_text_inside_figures(q, sp, got, sources={1: src}, fig_dir=td)
    im = got[0][0]
    assert src.calls, "题干第一行没接进图框"
    assert im["rect"][1] <= 216.4, f"图框上沿没接到第一行：{im['rect']}"
    assert im["whole_question"] is True and im["graphic"] is True, im
    assert q[0]["text"] == "", f"整题都在图里，题干还留了一遍：{q[0]['text']!r}"

    # 反例 1：OCR 读到了选项（选项在图外）→ 整题图会吞掉选项，不许接。
    # 三例都必须给 name+page+fig_dir：否则 _extend_crop_for_stem 在"没路径"
    # 就提前返回，下面三条判据一条都走不到（变异闸门实测 3 条漏网）。
    q2 = [{"text": "在准备新年联欢会时，王老师买了几袋同一种糖，付了50元，找回",
           "options": ["A.3元", "B.4元"]}]
    src2, got2 = _Src(), {0: [{"name": "q2.png", "page": 1,
                               "rect": [11.5, 231.0, 300.4, 310.5]}]}
    sp2 = [{"q_index": 0, "text_boxes": boxes}]
    with tempfile.TemporaryDirectory() as td2:
        FG.strip_text_inside_figures(q2, sp2, got2, sources={1: src2},
                                     fig_dir=td2)
    assert not src2.calls, "有选项的题被接成整题图（选项会丢）"
    assert got2[0][0]["rect"] == [11.5, 231.0, 300.4, 310.5]
    assert q2[0]["text"], "反例题的文字被清空了"

    # 反例 2：图里只有尺寸标注（8cm），不是题干 → 不许把上面一行吞进图
    q3 = [{"text": "求阴影部分的面积。"}]
    sp3 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 104, "w": 80, "h": 12, "text": "3.求阴影部分的面积。"},
        {"x": 160, "y": 150, "w": 24, "h": 10, "text": "8cm"},
    ]}]
    src3, got3 = _Src(), {0: [{"name": "q3.png", "page": 1,
                               "rect": [90.0, 120.0, 300.0, 220.0]}]}
    with tempfile.TemporaryDirectory() as td3:
        FG.strip_text_inside_figures(q3, sp3, got3, sources={1: src3},
                                     fig_dir=td3)
    assert not src3.calls, "纯图形配图被接成了整题图"
    assert q3[0]["text"] == "求阴影部分的面积。"

    # 反例 3：图框上方那行不是本题题干的开头 → 不接
    q4 = [{"text": "求阴影部分的面积。"}]
    sp4 = [{"q_index": 0, "text_boxes": [
        {"x": 100, "y": 104, "w": 80, "h": 12, "text": "4.上一道题的题干。"},
        {"x": 60, "y": 150, "w": 120, "h": 10, "text": "下面四幅图中，可以表示的是图（ ）"},
    ]}]
    src4, got4 = _Src(), {0: [{"name": "q4.png", "page": 1,
                               "rect": [90.0, 120.0, 300.0, 220.0]}]}
    with tempfile.TemporaryDirectory() as td4:
        FG.strip_text_inside_figures(q4, sp4, got4, sources={1: src4},
                                     fig_dir=td4)
    assert not src4.calls, "把上一题的题干行接进了本题图框"
    assert q4[0]["text"] == "求阴影部分的面积。"


def box_text_patterns_also_tries_without_the_question_number():
    """行框常带题号（"2.按要求填一填。"），拼好的题干已剥题号：两版都要能匹配。

    只留原样一版时，竖排图那块的行框「3」「21」会匹配不上题干，残留在题干末尾
    （真实卷 第三单元 p2 第 1 题）；地图题的行尾图注也会因此认不出来。
    """
    import app.extractor.figures as FG
    pats = FG.box_text_patterns("2.按要求填一填。")
    assert len(pats) == 2, f"只给了一版（去题号那版没了）：{pats}"
    assert any("2" in p for p in pats), f"原样版丢了：{pats}"
    assert any("2" not in p for p in pats), f"去题号版丢了：{pats}"


def residue_cleanup_is_wired_into_the_pipeline():
    """接线检查：出题接口与审计尺都必须真的调用清理，不能只留一个函数。"""
    for rel in (os.path.join("app", "api", "papers.py"),
                os.path.join("tests", "audit_papers.py")):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel)
        src = open(p, encoding="utf-8").read()
        assert "strip_text_inside_figures(qs, spans, got, sources=" in src, \
            rel + " 没接清理"
        assert "fig_dir=" in src, rel + " 没接裁图目录（接题干第一行要用）"


def top_growth_pulls_a_small_icon_above_the_question():
    """本题上沿紧贴的小太阳要随图裁进来；大图标、离得远、OCR 文字、横线都不许长。

    真实卷（综合实践课 p1 第 1 题）：太阳在题干第一行之上，图的上沿从题干第一行
    开始，于是太阳整个落在本题区间之外，裁出来只剩太阳下班 —— 用户说"太阳被裁"。
    这条判据只向上吃 ≤40×40pt 的小图标，四面乱长已实测会挤掉邻题的图，不接。
    """
    import numpy as np
    import cv2
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    def page_with(draw):
        g = np.full((int(200 * k), int(200 * k)), 255, dtype=np.uint8)
        draw(g)
        return FG.PageSource(1, 200.0, 200.0, g, lambda rect, out: None)

    def circle(g, cx, cy, r):
        cv2.circle(g, (int(cx * k), int(cy * k)), max(1, int(r * k)), 30, -1)

    rect0 = (40.0, 60.0, 120.0, 150.0)
    got = FG._grow_up_small_attached(
        rect0, page_with(lambda g: circle(g, 80, 48, 8)), [], 60.0, np, cv2)
    assert (got[0], got[2], got[3]) == (rect0[0], rect0[2], rect0[3]), \
        f"只许向上长，别的边动了：{got}"
    assert got[1] <= 45.0, f"太阳没被吃进来：{got}"

    # 正例 2（真实卷形状）：太阳旁边还有一段 14×1pt 的墨，合起来 46×21pt。
    # 单个墨团都没超 40，合起来超 40 但没超 60 —— 这不是共享地图，仍是"一个图标"。
    def sun_with_dash(g):
        circle(g, 82, 48, 8)
        cv2.line(g, (int(44 * k), int(59 * k)), (int(58 * k), int(59 * k)), 30,
                 max(1, int(1 * k)))
    dash_got = FG._grow_up_small_attached(
        rect0, page_with(sun_with_dash), [], 60.0, np, cv2)
    assert dash_got[1] <= 45.0, f"太阳旁边有一段平线就被挡在框外：{dash_got}"

    # 反例 1：离上沿 17pt（超过 5pt 的紧贴门槛）→ 不许长。
    # ⚠️ 用 6×6 小块，不用 r8 的圆：r8 在 17pt 外总长已超 30pt，会被总长门槛
    #    顺手挡住，量到的就不是"紧贴"这条判据了（变异闸门实测没红）。
    def far_mark(g):
        cv2.rectangle(g, (int(77 * k), int(37 * k)), (int(83 * k), int(43 * k)), 30, -1)
    far = FG._grow_up_small_attached(
        rect0, page_with(far_mark), [], 60.0, np, cv2)
    assert far == rect0, f"离得远的墨也被吃进来：{far}"
    # 反例 2：70×20pt 的大块（不是小图标）→ 不许长
    def big(g):
        cv2.rectangle(g, (int(50 * k), int(36 * k)), (int(120 * k), int(56 * k)), 30, -1)
    big_got = FG._grow_up_small_attached(
        rect0, page_with(big), [], 60.0, np, cv2)
    assert big_got == rect0, f"大块墨被当小图标吃进来：{big_got}"
    # 反例 2b：50×10pt 的横条。合起来没超 60×40，但【单个】就超 40 宽，
    # 是横幅/底边，不是图标 —— 单个墨团的上限必须自己站得住。
    def wide(g):
        cv2.rectangle(g, (int(45 * k), int(48 * k)), (int(95 * k), int(58 * k)), 30, -1)
    wide_got = FG._grow_up_small_attached(
        rect0, page_with(wide), [], 60.0, np, cv2)
    assert wide_got == rect0, f"50×10pt 的横条被当图标吃进来：{wide_got}"
    # 反例 3：那块墨被 OCR 认成文字（"太阳"两个字就是两个小连通域）→ 不许长
    labeled = FG._grow_up_small_attached(
        rect0, page_with(lambda g: circle(g, 80, 48, 8)),
        [{"x": 68, "y": 36, "w": 24, "h": 24, "text": "太阳"}], 60.0, np, cv2)
    assert labeled == rect0, f"OCR 文字框里的墨被当图标吃进来：{labeled}"
    # 反例 4：裁框上沿不在本题区间顶（下方 10pt）→ 不是"贴着题顶"，不许长
    notop = FG._grow_up_small_attached(
        rect0, page_with(lambda g: circle(g, 80, 48, 8)), [], 50.0, np, cv2)
    assert notop == rect0, f"没贴着本题上沿也向上长：{notop}"
    # 反例 5：页眉那种细横线（宽度接近整框）→ 不许长
    def rule(g):
        cv2.line(g, (int(20 * k), int(57 * k)), (int(140 * k), int(57 * k)), 30,
                 max(1, int(2 * k)))
    rule_got = FG._grow_up_small_attached(
        rect0, page_with(rule), [], 60.0, np, cv2)
    assert rule_got == rect0, f"细横线被当图标吃进来：{rule_got}"
    # 反例 6：两团分开的小墨（合起来 65×10）→ 不是"一个图标"，不许长
    def two(g):
        circle(g, 50, 52, 5)
        circle(g, 110, 52, 5)
    two_got = FG._grow_up_small_attached(
        rect0, page_with(two), [], 60.0, np, cv2)
    assert two_got == rect0, f"两团分开的墨被一起当图标吃进来：{two_got}"
    # 反例 7：10×35pt 的高条（离上沿 1pt，但会让总长超过 30pt）→ 不许长
    def tall(g):
        cv2.rectangle(g, (int(75 * k), int(24 * k)), (int(85 * k), int(59 * k)), 30, -1)
    tall_got = FG._grow_up_small_attached(
        rect0, page_with(tall), [], 60.0, np, cv2)
    assert tall_got == rect0, f"总长超过 30pt 的墨条也被吃进来：{tall_got}"
    # 反例 8：上一题底边就在太阳下方（floor_top=45）→ 跨题一律不长
    floor_got = FG._grow_up_small_attached(
        rect0, page_with(lambda g: circle(g, 80, 48, 8)), [], 60.0, np, cv2,
        floor_top=45.0)
    assert floor_got == rect0, f"越过上一题底边向上长：{floor_got}"


def sun_above_the_figure_is_kept_end_to_end():
    """接线检查（真实文字层）：太阳落在本题区间之外时，find_figures 必须自己向上吃。"""
    path = os.path.join(OUT, "太阳上沿.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # 不要大题题头：题头会把区间上沿拉到 y=39，太阳自然落进区间里，夹具就测不到
    # "区间从题干第一行起、太阳在第一行之上"这个真实情形。
    _txt(page, 40, 125, "1. 图中的太阳从哪里升起？")
    page.draw_circle((300, 104.5), 8, color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(pymupdf.Rect(250, 116, 500, 230), color=(0, 0, 0), width=1.2)
    page.draw_rect(pymupdf.Rect(270, 140, 470, 215), color=None, fill=(0.6, 0.6, 0.6))
    page.draw_line((270, 170), (470, 170), color=(0, 0, 0), width=1.0)
    doc.save(path)
    doc.close()
    r = annotated_lines_from_pdf(path)
    res = extract(r["lines"], title="")
    qs = flatten_questions(res)
    spans = spans_for_questions(r["ann"], qs, pages=r["pages"], sections=res["sections"])
    src = page_source_from_pdf(path, 1)
    rep = []
    got = find_figures({1: src}, spans, OUT, report=rep)
    assert got.get(0), f"夹具没裁出第 1 题的图：{[q['text'][:12] for q in qs]}；report={rep}"
    tops = [float(im["rect"][1]) for im in got[0]]
    assert min(tops) < 110.0, f"太阳被裁在框外：{tops}"
    assert any(x.get("why") == "grew-up" for x in rep), f"没走向上吃的判据：{rep}"


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


def stem_bottom_clip_is_wired_into_find_figures():
    """接线检查：下沿裁题干这条必须真的跑在 find_figures 里，不是死函数。

    合成一页：图墨 90–202，外加一根探到 225 的竖笔画（图自己的下探线）；
    题干行框 203–221 印在【白纸】上、整行落在裁框里（扫描卷里数轴图下面
    紧贴题干就是这个样子），±3pt 外扩后裁框下沿 228，行底 221 离下沿 7pt ——
    正是 q30 的 8.7pt 那一档。函数单测证明判据对；这条证明它被接进链路，
    且报告里留下 `stem-bottom-clipped`。

    ⚠️ 文字行不能压在整块实心墨上：那样上下都是满宽墨，`_row_in_border`
       会正确地判成"字印在闭合边框里"（周末作业绿框那条），于是不裁。
       第一版夹具就是实心块盖住文字行，加了这条守卫后当场变红。
    """
    import app.extractor.figures as FG
    from app.extractor.figures import find_figures, PageSource
    import numpy as np
    k = FG.DPI_PROBE / 72.0
    g = np.full((int(300 * k), int(400 * k)), 255, dtype=np.uint8)
    g[int(90 * k):int(202 * k), int(30 * k):int(300 * k)] = 40     # 图墨（实心块）
    g[int(202 * k):int(225 * k), int(275 * k):int(290 * k)] = 40   # 图自己下探的笔画
    src = PageSource(1, 400.0, 300.0, g, lambda rect, out: None)
    spans = [{"q_index": 0, "page": 1, "col": 0,
              "y0": 35.0, "y1": 250.0, "x0": 0.0, "x1": 400.0,
              "text_boxes": [
                  {"x": 20, "y": 40, "w": 180, "h": 18, "text": "2.画一画,填一填。"},
                  {"x": 25, "y": 203, "w": 260, "h": 18,
                   "text": "青蛙1次跳4格,兔子1次跳(      )个4格。"}]}]
    rep = []
    got = find_figures({1: src}, spans, OUT, report=rep)
    assert got.get(0), f"夹具没裁出图：report={rep}"
    bottoms = [float(im["rect"][3]) for im in got[0]]
    assert max(bottoms) <= 202.5, f"末行题干还框在图里：{bottoms}；report={rep}"
    assert any(x.get("why") == "stem-bottom-clipped" for x in rep), \
        f"没走下沿裁切判据：{rep}"


def blank_dashed_answer_areas_are_stripped():
    """大块虚线作答区：只剔框线的短划，框里/框边的真图和圆点必须留下。

    真实卷（第三单元练习题 第 4 页第 3 题）：左右两个「问题一/问题二」虚线框
    被补洞规则和插图连成一张 442×246pt 的巨图；右边那个还把下一题点阵图的
    顶行连走。判据是「框大、墨稀、四边全是 ≤15pt 的短划」，不是「有虚线就剔」。
    """
    import numpy as np
    import cv2
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    def dash_rect(g, x0, y0, x1, y1, dash=5.0, gap=4.0, thick=1.5):
        def h(y):
            x = x0
            while x < x1 - 0.5:
                xa, xb = int(round(x * k)), int(round(min(x1, x + dash) * k))
                ya, yb = int(round(y * k)), int(round((y + thick) * k))
                g[ya:yb, xa:xb] = True
                x += dash + gap

        def v(x):
            y = y0
            while y < y1 - 0.5:
                ya, yb = int(round(y * k)), int(round(min(y1, y + dash) * k))
                xa, xb = int(round(x * k)), int(round((x + thick) * k))
                g[ya:yb, xa:xb] = True
                y += dash + gap
        h(y0)
        h(y1 - thick)
        v(x0)
        v(x1 - thick)

    def disk(g, cx, cy, r):
        yy, xx = np.ogrid[:g.shape[0], :g.shape[1]]
        g[(xx - cx * k) ** 2 + (yy - cy * k) ** 2 <= (r * k) ** 2] = True

    def canvas(w=520.0, h=260.0):
        return np.zeros((int(h * k), int(w * k)), dtype=bool)

    def strip(band):
        return FG._strip_blank_answer_areas(band, np.zeros_like(band), k, np, cv2)

    # 正例：150×85 虚线框 + 紧贴框底的一行 4 个 18pt 圆点 + 远处真插图。
    # 圆点和框底在膨胀半径内会连成同一个连通域 —— 必须按【短划自己的 bbox】
    # 认框，不能按连通域 bbox（真实卷 q17 右框下面就是下一题点阵的顶行）。
    b = canvas()
    dash_rect(b, 40, 40, 190, 125)
    for cx in (60, 100, 140, 180):
        disk(b, cx, 140, 9)
    b[int(50 * k):int(120 * k), int(300 * k):int(380 * k)] = True
    out, wall = strip(b)
    assert not out[int(40 * k):int(125 * k), int(40 * k):int(190 * k)].any(), \
        "虚线框的短划没剔干净"
    for cx in (60, 100, 140, 180):
        assert out[int((140 - 9) * k):int((140 + 9) * k),
                   int((cx - 9) * k):int((cx + 9) * k)].sum() > 0, \
            f"框旁边的圆点被当框线剔掉了（x={cx}）"
    assert out[int(50 * k):int(120 * k), int(300 * k):int(380 * k)].all(), \
        "真插图被虚线框规则误伤"
    assert wall[int(40 * k):int(125 * k), int(40 * k):int(190 * k)].sum() > 20, \
        "剔掉的框线没有记成墙，膨胀仍会跨过去"
    assert not wall[int(50 * k):int(120 * k), int(300 * k):int(380 * k)].any(), \
        "真插图被记成了墙"

    # 反例 1：实线边框（150pt 长横线）不许剔
    b = canvas()
    b[int(40 * k):int(41.5 * k), int(40 * k):int(190 * k)] = True
    b[int(123.5 * k):int(125 * k), int(40 * k):int(190 * k)] = True
    b[int(40 * k):int(125 * k), int(40 * k):int(41.5 * k)] = True
    b[int(40 * k):int(125 * k), int(188.5 * k):int(190 * k)] = True
    out, _ = strip(b)
    assert np.array_equal(out, b), "实线边框被当成虚线框剔了"

    # 反例 2：框里有一大块图（密度 0.34）→ 整块都不许剔
    b = canvas()
    dash_rect(b, 40, 40, 190, 125)
    b[int(55 * k):int(105 * k), int(80 * k):int(160 * k)] = True
    out, _ = strip(b)
    assert np.array_equal(out, b), "框里有图也把框线剔了（圆点阵会被切碎）"

    # 反例 3：点状纹理铺满整块（不是围在框边）→ 不许剔
    b = canvas()
    step = int(6 * k)
    dot = max(1, int(1.3 * k))
    for y in range(int(40 * k), int(125 * k), step):
        for x in range(int(40 * k), int(190 * k), step):
            b[y:y + dot, x:x + dot] = True
    out, _ = strip(b)
    assert np.array_equal(out, b), "铺满整块的点状纹理被当成虚线框剔了"

    # 反例 4：框太小（70×40）→ 不许剔。短划画得细而稀（覆盖率 <6%），
    # 这样每条别的判据都过得去，只剩"尺寸"这一条能挡住它。
    b = canvas()
    dash_rect(b, 40, 40, 110, 80, dash=3.0, gap=6.0, thick=1.0)
    out, _ = strip(b)
    assert np.array_equal(out, b), "小虚线框被剔了（它是作答位置，不是大块空白区）"

    # 反例 5：短划不够 8 个 → 不许剔
    b = canvas()
    dash_rect(b, 40, 40, 190, 125, dash=6, gap=80)
    out, _ = strip(b)
    assert np.array_equal(out, b), "零星几根虚线被当成整框剔了"

    # 反例 6：右边缺一条竖边（顶边探到最右，底边只到 140）→ 不许剔。
    # 右边沿只剩顶边那一根短划（sides[右]=1），"四边都得有"才挡得住；
    # 尺寸/密度/最长横走/贴边占比全过。
    b = canvas()
    for x_end, y in ((189.5, 40), (140, 123.5)):
        x = 40
        while x < x_end:
            b[int(y * k):int((y + 1.5) * k),
              int(x * k):int(min(x_end, x + 5) * k)] = True
            x += 9
    y = 40
    while y < 122:
        b[int(y * k):int(min(123.5, y + 5) * k),
          int(40 * k):int(41.5 * k)] = True
        y += 9
    out, _ = strip(b)
    assert np.array_equal(out, b), "缺一条竖边的虚线被当成完整框剔了"

    # 反例 7：框里横着一根长线（150pt）→ 不是空白作答区，不许剔
    b = canvas()
    dash_rect(b, 40, 40, 190, 125)
    b[int(80 * k):int(81 * k), int(40 * k):int(190 * k)] = True
    out, _ = strip(b)
    assert np.array_equal(out, b), "框里有长横线也剔了（作答横线≠虚线框）"

    # 反例 8：框里挨着上沿有一颗 12pt 小圆点（和框线在同一个连通域）→
    # 只许剔框线，框里的点得留下（圆点阵的第一颗常贴边）。
    b = canvas()
    dash_rect(b, 40, 40, 190, 125)
    disk(b, 100, 50, 6)
    out, _ = strip(b)
    assert out[int(44 * k):int(56 * k), int(94 * k):int(106 * k)].sum() > 0, \
        "框里的小圆点被当成框线剔了"
    assert not out[int(40 * k):int(41.5 * k), int(60 * k):int(70 * k)].any(), \
        "加了圆点以后框线反而不剔了"

    # 反例 9：框里有一根 15×58pt 的实心竖条（贴着底边、同一连通域）→
    # 内容密度 ~7% > 6%，不是空白作答区。横走最长只有 15pt，
    # 所以"长横线"判据挡不住，只剩密度这一条能挡。
    b = canvas()
    dash_rect(b, 40, 40, 190, 125)
    b[int(60 * k):int(118 * k), int(100 * k):int(115 * k)] = True
    out, _ = strip(b)
    assert np.array_equal(out, b), "框里那根实心竖条被当虚线剔了（密度门槛失效）"


def seam_crossing_and_sliver_rules_are_sound():
    """跨题缝合：接缝上必须有贯穿两侧的笔画；同宽薄片是唯一例外。

    真实卷（第三单元练习题 第 4 页）：第 2 题连环画底边 446、第 3 题操场图
    顶边 451.5，本来差 5.5pt；题目区间上下各留 3pt，把两张【各自完好】的图
    在题界上夹出 6pt 重叠 —— 旧判据「接缝上有墨」就把它缝成一张，
    第 3 题的裁图把第 2 题的图整个吞进来（923KB 的巨图）。
    同时，第 4 题的点阵被题界从两行圆点之间切开，接缝上【没有】贯穿笔画，
    但顶行只有 24.7pt 高、与下面同宽，必须靠薄片例外缝回去。
    """
    import numpy as np
    import cv2
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    def source(draw, size=200.0):
        g = np.full((int(size * k), int(size * k)), 255, dtype=np.uint8)
        draw(g)
        return FG.PageSource(1, size, size, g, lambda rect, out: None)

    def cand(src, qi, rect, band):
        return {"q_index": qi, "page": 1, "col": 0, "src": src, "rect": rect,
                "w_pt": rect[2] - rect[0], "h_pt": rect[3] - rect[1],
                "tbs": [], "band": band}

    def block(g, x0, y0, x1, y1):
        cv2.rectangle(g, (int(x0 * k), int(y0 * k)),
                      (int(x1 * k), int(y1 * k)), 40, -1)

    def dots(g, xs, ys, r=9.0):
        for y in ys:
            for x in xs:
                cv2.circle(g, (int(x * k), int(y * k)), int(r * k), 40, -1)

    # 反例 A：两张完整的图（上 51pt、下 104pt），接缝两侧各只有一条 1–2px 的
    # 水平边 —— 有墨，但没有【贯穿】的笔画。旧判据只看"接缝上有墨"就会缝；
    # 新判据要求同一列在上下两半都有 ≥2px 的连续墨 → 必须保持两张。
    src_a = source(lambda g: (block(g, 10, 20, 130, 71),
                              block(g, 10, 76, 130, 180)))
    out_a = FG._stitch_across_questions([
        cand(src_a, 20, (10.0, 10.0, 130.0, 74.0), (0, 0, 200, 74)),
        cand(src_a, 21, (10.0, 74.0, 132.0, 190.0), (0, 74, 200, 200))])
    assert len(out_a) == 2, f"两张完整的图被缝成一张：{[c['rect'] for c in out_a]}"

    # 反例 A2：接缝上确实有贯穿笔画，但只有 3 列 —— 两张图各带 3 根对齐的
    # 竖线时也会"贯穿"。SEAM_CROSS_MIN_COLS=6 就是防这个；门槛退回 0 就会缝。
    src_a2 = source(lambda g: (block(g, 10, 20, 130, 71),
                               block(g, 10, 76, 130, 180),
                               [cv2.line(g, (int(x * k), int(40 * k)),
                                         (int(x * k), int(140 * k)), 40, 1)
                                for x in (30, 60, 90)]))
    out_a2 = FG._stitch_across_questions([
        cand(src_a2, 20, (10.0, 10.0, 130.0, 74.0), (0, 0, 200, 74)),
        cand(src_a2, 21, (10.0, 74.0, 132.0, 190.0), (0, 74, 200, 200))])
    assert len(out_a2) == 2, f"只靠 3 列对齐的竖线就缝了：{[c['rect'] for c in out_a2]}"

    # 正例 B：同宽薄片（30pt 高的顶行圆点）→ 缝回一张，挂给点数更多的题
    src_b = source(lambda g: (dots(g, (30, 70, 110), (30,)),
                              dots(g, (30, 70, 110), (60, 100, 140, 180))))
    out_b = FG._stitch_across_questions([
        cand(src_b, 20, (10.0, 10.0, 130.0, 40.0), (0, 0, 200, 40)),
        cand(src_b, 21, (10.0, 40.0, 132.0, 200.0), (0, 40, 200, 200))])
    assert len(out_b) == 1, f"同宽点阵薄片没缝回一张：{[c['rect'] for c in out_b]}"
    assert out_b[0]["q_index"] == 21, "缝完该挂给点数更多的那道题"
    assert out_b[0]["rect"][3] - out_b[0]["rect"][1] >= 189, out_b[0]["rect"]

    # 反例 C：薄片但宽度差太多（70 vs 100，比值 0.7）→ 不是同一张图，不许缝。
    # 0.7 能过 STITCH_MIN_W_RATIO(0.6)，所以单独检验薄片自己的 0.9 门槛。
    src_c = source(lambda g: (dots(g, (30, 60), (30,)),
                              dots(g, (30, 60, 90), (60, 100, 140, 180))))
    out_c = FG._stitch_across_questions([
        cand(src_c, 20, (10.0, 10.0, 80.0, 40.0), (0, 0, 200, 40)),
        cand(src_c, 21, (10.0, 40.0, 110.0, 200.0), (0, 40, 200, 200))])
    assert len(out_c) == 2, f"宽窄差太多的薄片被缝上了：{[c['rect'] for c in out_c]}"

    # 反例 D：同宽但薄片高 50pt（超过 32pt 上限）→ 已是一整张图，
    # 没有贯穿笔画就必须分开。上限一放宽就会把上下两张并掉。
    # 上块墨止于 57（离接缝 3pt），上下两半各只剩一条 1px 的边。
    src_d = source(lambda g: (block(g, 10, 20, 130, 57),
                              block(g, 10, 60, 130, 180)))
    out_d = FG._stitch_across_questions([
        cand(src_d, 20, (10.0, 10.0, 130.0, 60.0), (0, 0, 200, 60)),
        cand(src_d, 21, (10.0, 60.0, 132.0, 190.0), (0, 60, 200, 200))])
    assert len(out_d) == 2, f"50pt 高的同宽块被当成薄片缝了：{[c['rect'] for c in out_d]}"


def blank_area_strip_is_wired_into_find_figures():
    """接线检查（真实裁图链路）：虚线作答区必须在 _scan 里被剔掉，真图不许误伤。"""
    import app.extractor.figures as FG
    path = os.path.join(OUT, "虚线作答区.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _base(page)
    _txt(page, 40, 90, "1. 观察图片，提出两个能用6×2解决的问题。")
    _txt(page, 60, 155, "问题一：")
    x0, y0, x1, y1 = 55.0, 135.0, 250.0, 225.0

    def h(y):
        x = x0
        while x < x1 - 0.5:
            page.draw_line((x, y), (min(x1, x + 5), y), color=(0, 0, 0), width=1.0)
            x += 9

    def v(x):
        y = y0
        while y < y1 - 0.5:
            page.draw_line((x, y), (x, min(y1, y + 5)), color=(0, 0, 0), width=1.0)
            y += 9
    h(y0)
    h(y1)
    v(x0)
    v(x1)
    _grid(page, 330, 135, 450, 215)
    _txt(page, 40, 320, "2. 第二题的题干文字内容。")
    doc.save(path)
    doc.close()

    real = FG._strip_blank_answer_areas
    calls = []

    def spy(band, wall, k, np, cv2):
        out, w2 = real(band, wall, k, np, cv2)
        calls.append(int(band.sum()) - int(out.sum()))
        return out, w2
    FG._strip_blank_answer_areas = spy
    try:
        _r, _res, qs, spans, got = run(path)
    finally:
        FG._strip_blank_answer_areas = real
    assert calls and max(calls) > 50, f"虚线框没被 _scan 剔掉（calls={calls}）"
    figs = got.get(0) or []
    assert figs, f"真插图也没裁出来（判据剔过头了）：{got}"
    assert all(im["rect"][0] >= 300 for im in figs), \
        f"虚线作答区仍被当配图裁走：{[im['rect'] for im in figs]}"


def blank_answer_rules_are_not_figures():
    """只有作答横线的矮块不是图（真实卷：达标B 第 5 题 320×38pt 两条线）。

    合成一页：两条 240pt 的长横线 + 上方两行会被 OCR 挖掉的文字。
    没有这条判据时，两线框会被尺寸/墨量门槛放行，成品里多一张"空白横线"图。
    """
    import app.extractor.figures as FG
    from app.extractor.figures import find_figures, PageSource
    import numpy as np
    k = FG.DPI_PROBE / 72.0
    g = np.full((int(250 * k), int(300 * k)), 255, dtype=np.uint8)
    g[int(100 * k):int(100 * k) + 2, int(30 * k):int(270 * k)] = 20    # 作答线 1
    g[int(125 * k):int(125 * k) + 2, int(30 * k):int(270 * k)] = 20    # 作答线 2
    # 两条线之间的引导点（真实扫描件上就有）——不让它们先被 thin-horizontal 各自砍掉
    for yy in (108, 116):
        g[int(yy * k):int(yy * k) + 2, int(35 * k):int(35 * k) + 2] = 20
    for yy in (55, 72):                                               # 题干文字（会被挖掉）
        for xx in range(30, 260, 12):
            g[int(yy * k):int(yy * k) + 8, int(xx * k):int(xx * k) + 6] = 20
    src = PageSource(1, 300.0, 250.0, g, lambda rect, out: None)
    spans = [{"q_index": 0, "page": 1, "col": 0,
              "y0": 40.0, "y1": 200.0, "x0": 0.0, "x1": 300.0,
              "text_boxes": [
                  {"x": 20, "y": 52, "w": 260, "h": 12, "text": "在菜园里，方方学到了有关蔬菜的知识。"},
                  {"x": 20, "y": 69, "w": 260, "h": 12, "text": "假如你是方方，你会对爷爷说："}]}]
    rep = []
    got = find_figures({1: src}, spans, OUT, report=rep)
    assert not got.get(0), f"两条作答横线被当成配图：{got.get(0)}；report={rep}"
    assert any(d.get("why") == "answer-rules" for d in rep if not d.get("kept")), \
        f"没走空白横线判据：{rep}"

    # 判据本身的正反例（阈值 12pt 是量出来的，不是拍的）：
    # 正例里那块 10pt 高的引号残角就是达标B q5 的真实读数；
    # 14pt 以上的实墨、表格竖线、只有一条长轴的数轴，都必须否决。
    def band_of(extra=None):
        b = np.zeros((50, 300), dtype=bool)
        b[30:32, 20:280] = True
        b[45:47, 20:280] = True
        if extra is not None:
            x0, y0, x1, y1 = extra
            b[y0:y1, x0:x1] = True
        return b

    rect = (0.0, 0.0, 300.0, 50.0)
    assert FG._is_blank_rule_row(rect, band_of((285, 35, 289, 45)), 1.0, 0, 0, np), \
        "10pt 的引号残角把两条作答横线挡在门外了（真实卷 q5）"
    only_one = np.zeros((50, 300), dtype=bool)
    only_one[30:32, 20:280] = True
    assert not FG._is_blank_rule_row(rect, only_one, 1.0, 0, 0, np), \
        "数轴只有一条长轴，被当成作答横线砍了"
    assert not FG._is_blank_rule_row(rect, band_of((285, 10, 301, 26)), 1.0, 0, 0, np), \
        "16pt 的实墨块被当成碎点，整块仍被砍"
    assert not FG._is_blank_rule_row(rect, band_of((150, 10, 152, 47)), 1.0, 0, 0, np), \
        "表格竖线被当成碎点，整块仍被砍"


def answer_circles_are_not_figures():
    """两个空心圆圈夹着算式碎片 = 比较大小的作答位置，不是图。

    真实卷（L2 中期评估模拟卷 p1 第 2 题）：42.7×65.7pt 的窄条里只有两个
    22pt 空心圈和几块 ≤10.1pt 的算式残角，裁出来就是一张"两个圆圈"的废图。
    正例＋三个反例：一个圈、带大块实墨、实心点，都不许砍。
    """
    import app.extractor.figures as FG
    import cv2
    import numpy as np

    def strip(rings: int = 2, extra=None, filled: bool = False):
        b = np.zeros((70, 50), dtype=np.uint8)
        if filled:
            cv2.circle(b, (14, 18), 11, 1, -1)
            cv2.circle(b, (14, 50), 11, 1, -1)
        else:
            for cy in ([18, 50] if rings == 2 else [18]):
                cv2.circle(b, (14, cy), 11, 1, 2)
        b[10:16, 30:36] = 1                    # 算式残角（×/字的碎笔）
        if extra is not None:
            x0, y0, x1, y1 = extra
            b[y0:y1, x0:x1] = 1
        return b.astype(bool)

    rect = (0.0, 0.0, 50.0, 70.0)
    assert FG._is_answer_circle_row(rect, strip(), 1.0, 0, 0, np), \
        "两个作答圆圈被当成配图了（真实卷 L2 q2）"
    assert not FG._is_answer_circle_row(rect, strip(rings=1), 1.0, 0, 0, np), \
        "只有一个圆圈，不当答题圈砍"
    assert not FG._is_answer_circle_row(rect, strip(extra=(30, 22, 45, 38)), 1.0, 0, 0, np), \
        "带 15pt 实墨的图被当答题圈砍了"
    assert not FG._is_answer_circle_row(rect, strip(filled=True), 1.0, 0, 0, np), \
        "实心圆点被当成空心作答圈了"
    # 接线检查：候选阶段与合并后的复检都要真的调用它，不能只当死函数。
    import inspect
    src = inspect.getsource(FG.find_figures)
    assert "_is_answer_circle_row(" in src, "作答圆圈判据没接进 find_figures"
    assert "_is_answer_circle_row(rect" in inspect.getsource(FG._recheck_merged), \
        "合并后的最终复检没查作答圆圈"


def text_covered_block_is_not_a_figure():
    """小窄块里的墨几乎全在文字行框里 → 文字残影，不是图（含反例）。"""
    import app.extractor.figures as FG
    import numpy as np
    raw = np.zeros((60, 100), dtype=bool)
    raw[5:20, 10:90] = True                       # 第一行“字”
    raw[25:40, 10:90] = True                      # 第二行“字”
    tb = [[8, 3, 92, 22], [8, 23, 92, 42]]
    assert FG._is_text_covered_block([0, 0, 100, 60], raw, tb, 1.0, np), \
        "两行文字残影没被认出来"
    # 反例①：框里有一大块不在任何文字行里的墨（真图主体）
    raw2 = raw.copy()
    raw2[45:58, 10:80] = True
    assert not FG._is_text_covered_block([0, 0, 100, 60], raw2, tb, 1.0, np), \
        "图里的实心主体被当文字抹掉了"
    # 反例②：整题截图那档大框不在判据范围内
    raw3 = np.zeros((120, 300), dtype=bool)
    raw3[5:110, 10:290] = True
    tb3 = [[8, 3, 292, 58], [8, 60, 292, 112]]
    assert not FG._is_text_covered_block([0, 0, 300, 120], raw3, tb3, 1.0, np), \
        "整题截图被当成文字残影砍了"
    # 接线检查：判据必须真的跑在 find_figures 里，不能只当死函数
    import inspect
    from app.extractor import figures as FG2
    src = inspect.getsource(FG2.find_figures)
    assert "_is_text_covered_block(" in src and "_is_blank_rule_row(" in src, \
        "纯文字块/空白横线判据没接进 find_figures"


def merged_text_block_is_rechecked():
    """合并之后长出来的文字块，要按【最终框】再判一次。

    真实卷（第三单元练习题 p7 第 2 题）：选项文字被 OCR 行框盖住 86%，剩下的
    字角散成几块；`_absorb_row_peers` 把它们接成 82×53 的框时，形状已经和候选
    阶段不同了，候选那一眼的判据放过了它。这里直接喂 `_recheck_merged`：
    同一个小窄块 → 必须丢；框里多一块不在文字行里的实墨（真图主体）→ 必须留。
    """
    import app.extractor.figures as FG
    import numpy as np
    k = FG.DPI_PROBE / 72.0

    def page_with(solid=False):
        g = np.full((int(120 * k), int(200 * k)), 255, dtype=np.uint8)
        for yy in (32, 44):                       # 两行“字”，全部落在文字框里
            for xx in range(20, 160, 10):
                g[int(yy * k):int((yy + 8) * k), int(xx * k):int((xx + 6) * k)] = 20
        if solid:                                 # 文字行外的一大块实墨（真图主体）
            g[int(50 * k):int(72 * k), int(30 * k):int(120 * k)] = 20
        return FG.PageSource(1, 200.0, 120.0, g, lambda rect, out: None)

    tbs = [{"x": 18, "y": 30, "w": 138, "h": 13, "text": "第一行文字"},
           {"x": 18, "y": 42, "w": 138, "h": 13, "text": "第二行文字"}]

    def cand(src, rect):
        return {"q_index": 0, "page": 1, "col": 0, "src": src, "rect": rect,
                "band": [0.0, 20.0, 200.0, 100.0], "tbs": tbs,
                "strict": True, "w_pt": 140.0, "h_pt": 25.0}

    rep = []
    got = FG._recheck_merged([cand(page_with(), (20.0, 30.0, 160.0, 55.0))],
                             rep, np, None)
    assert not got, f"row-peer 接出来的文字块没被最终复检砍掉：{got}"
    assert any(e.get("why") == "text-block-final" for e in rep), \
        f"没走最终复检（text-block-final）：{rep}"

    rep2 = []
    got2 = FG._recheck_merged([cand(page_with(solid=True), (20.0, 30.0, 160.0, 78.0))],
                              rep2, np, None)
    assert got2, f"框里有真图主体，却被最终复检砍了：{rep2}"

    # 接线：复检必须接在 _drop_contained 之后（不是死函数）
    import inspect
    src_find = inspect.getsource(FG.find_figures)
    assert "ok = _drop_contained(ok, report)" in src_find
    assert src_find.index("_drop_contained(ok, report)") < src_find.index(
        "ok = _recheck_merged(ok, report, np, cv2)"), \
        "最终复检没接在合并/去重之后"


def _gblock_source(fills=(), rings=(), width=400.0, height=200.0):
    """图形算式判据的合成页：fills＝实心方块，rings＝(x0,y0,x1,y1,线宽) 空心框。"""
    import numpy as np
    from app.extractor.figures import PageSource, DPI_PROBE
    k = DPI_PROBE / 72.0
    g = np.full((int(height * k), int(width * k)), 255, dtype=np.uint8)
    for (x0, y0, x1, y1) in fills:
        g[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] = 30
    for (x0, y0, x1, y1, w) in rings:
        px0, py0 = int(x0 * k), int(y0 * k)
        px1, py1 = int(x1 * k), int(y1 * k)
        t = max(1, int(w * k))
        g[py0:py1, px0:px0 + t] = 30
        g[py0:py1, px1 - t:px1] = 30
        g[py0:py0 + t, px0:px1] = 30
        g[py1 - t:py1, px0:px1] = 30
    return PageSource(1, width, height, g, lambda rect, out: None)


def graphic_equation_block_is_one_original_row():
    """题干行里夹着一排【字符级大图标】→ 整行原样成图，不许按"图"切碎。

    真实卷（第三单元练习题 p7 第 31 题）：OCR 行框把图标行横穿挖空，普通裁图
    只能得到图标的上半截/下半截两块碎片，孩子看到的算式是断的。
    这条判据不猜图标是什么，只回答"这一行该不该整行成图"。
    五个反例分别钉住：空心图形、图标太少、挤在局部、没有长空格缺口、
    没有等号、整行框罩住另一行文字 —— 任何一条松开都会把普通图文行也做成整行图。
    """
    import cv2
    import numpy as np
    import app.extractor.figures as FG
    line = "3. 如果            =16，            =16，那么"
    tb = {"x": 40.0, "y": 80.0, "w": 320.0, "h": 14.0, "text": line}
    span = {"x0": 0.0, "y0": 50.0, "x1": 400.0, "y1": 160.0, "text_boxes": [tb]}
    icons = [(100 + i * 35, 78, 125 + i * 35, 103) for i in range(4)]
    gb = FG._graphic_equation_block(_gblock_source(fills=icons), span, np, cv2)
    assert gb, "图形算式行没认出来（这行还会被切成图标碎片）"
    assert gb["n_icons"] == 4 and gb["n_rows"] == 1, gb
    x0, y0, x1, y1 = gb["rect"]
    assert x0 <= 40.0 and x1 >= 320.0, f"整行框没盖住文字行：{gb['rect']}"
    assert y1 - y0 <= FG.GRAPHIC_EQ_MAX_H_PT, gb["rect"]

    # 反例①：空心框（fill≈0.33）—— 第 11 题那种空心图形不是"字符级图标"。
    #    外框取 40pt：42pt 加像素取整会到 42.5pt，先被尺寸门槛挡住，就测不到 fill 这条。
    rings = [(100 + i * 50, 76, 140 + i * 50, 116, 5) for i in range(4)]
    assert not FG._graphic_equation_block(_gblock_source(rings=rings), span, np, cv2), \
        "空心图形被当成图形算式的图标"
    # 反例②：只有两个图标
    assert not FG._graphic_equation_block(_gblock_source(fills=icons[:2]), span, np, cv2), \
        "两个图标就被当成图形算式"
    # 反例③：三个图标挤在 95pt 以内 —— 不是横贯题干的算式行
    tight = [(100, 78, 125, 103), (135, 78, 160, 103), (170, 78, 195, 103)]
    assert not FG._graphic_equation_block(_gblock_source(fills=tight), span, np, cv2), \
        "图标挤在一小段里也当成图形算式"
    # 反例④：没有长空格缺口 / 没有等号 —— 普通图文行
    tb2 = dict(tb, text="3. 如果=16，=16，那么")
    assert not FG._graphic_equation_block(
        _gblock_source(fills=icons), dict(span, text_boxes=[tb2]), np, cv2), \
        "没有长空格缺口也当成图形算式"
    tb3 = dict(tb, text="3. 如果            ，            ，那么")
    assert not FG._graphic_equation_block(
        _gblock_source(fills=icons), dict(span, text_boxes=[tb3]), np, cv2), \
        "没有等号也当成图形算式"
    # 反例⑤：整行框里罩住了另一行 OCR 文字 —— 那是插图/邻题，不是一行算式
    tb4 = {"x": 120.0, "y": 82.0, "w": 100.0, "h": 12.0, "text": "另一行文字"}
    assert not FG._graphic_equation_block(
        _gblock_source(fills=icons), dict(span, text_boxes=[tb, tb4]), np, cv2), \
        "整行框罩住了另一行文字，仍被当成图形算式"
    # 接线：find_figures 必须真的调用它，图形候选必须绕过"像不像图"的筛子
    import inspect
    src_find = inspect.getsource(FG.find_figures)
    assert "_graphic_equation_block(" in src_find, "判据没接进 find_figures"
    assert 'if c.get("graphic"):' in src_find, "图形算式候选没绕过筛选"


def graphic_equation_is_cropped_as_one_original_row():
    """接线（真 PDF）：整行成一张图、碎片不再单裁、题干加说明（含反例）。"""
    from app.extractor.figures import apply_graphic_notes
    path = os.path.join(OUT, "图形算式.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=400)
    _base(page)
    _txt(page, 40, 100, "1. 看图写出一道乘法算式。")
    page.draw_rect(pymupdf.Rect(60, 115, 260, 175), color=(0, 0, 0), width=1.2)
    _txt(page, 40, 260, "3.如果" + " " * 12 + "=16，" + " " * 12 + "=16，那么")
    # 图标画进两段全角空格里：位置从文本层字符框量出来，夹具不猜排版
    raw = page.get_text("rawdict")
    spaces = [ch["bbox"] for blk in raw["blocks"] for ln in blk.get("lines", [])
              for sp in ln.get("spans", []) for ch in sp.get("chars", [])
              if ch["c"] == " " and ch["bbox"][1] > 200]
    assert len(spaces) == 24, f"夹具的空格数不对：{len(spaces)}"
    for gi, n in ((0, 4), (1, 3)):
        grp = spaces[gi * 12:(gi + 1) * 12]
        for k in range(n):
            bx = grp[int((k + 0.5) * len(grp) / n)]
            page.draw_circle(((bx[0] + bx[2]) / 2, 255), 12.5,
                             color=None, fill=(0.85, 0.2, 0.2), width=0)
    # 行尾一块 50×30 的实墨：它在整行原图范围内，普通裁图也会把它当一张图。
    # 不剔除的话，第 31 题会同时印出"整行原图"和"旁边这一小块"两张（真实 bug）。
    page.draw_rect(pymupdf.Rect(470, 240, 520, 270), color=(0, 0, 0),
                   fill=(0, 0, 0), width=0)
    _txt(page, 40, 330, "4. 下一题的文字内容。")
    doc.save(path)
    doc.close()

    _r, _res, qs, spans, got = run(path)
    gimgs = [im for lst in got.values() for im in lst if im.get("graphic")]
    assert len(gimgs) == 1, f"图形算式应当只出一张整行原图，实际 {len(gimgs)} 张"
    im = gimgs[0]
    eq_tb = max((b for s in spans for b in (s.get("text_boxes") or [])
                 if "=16" in str(b.get("text") or "")),
                key=lambda b: float(b["y"]))
    assert im["rect"][0] <= eq_tb["x"], (
        f"整行原图没盖住行首：图 {im['rect']} 行框 {eq_tb['x']}")
    assert im["rect"][2] >= eq_tb["x"] + eq_tb["w"], (
        f"整行原图没盖住行尾（截断了“=16，那么”）：{im['rect']} "
        f"行框右沿 {eq_tb['x'] + eq_tb['w']:.1f}")
    assert im["rect"][2] >= 524, (
        f"行尾那块实墨没进整行原图：{im['rect']}（应到 524 左右）")
    assert im["h_pt"] <= 45, f"整行原图高度异常：{im['h_pt']}"
    qi = next(k for k, v in got.items() if any(i.get("graphic") for i in v))
    assert len(got[qi]) == 1, (
        f"图形算式题还另外裁了 {len(got[qi]) - 1} 张碎片："
        + str([i["rect"] for i in got[qi]]))
    plain = [im for lst in got.values() for im in lst if not im.get("graphic")]
    assert plain, "第 1 题的真图也没裁出来（接线断了）"

    apply_graphic_notes(qs, got)
    t = qs[qi]["text"]
    assert "（本题算式中的图形见下方原图）" in t, f"题干没加图形说明：{t!r}"
    assert not _re.search(r"\s{2,}", t), f"题干里还留着长空格：{t!r}"
    for j, q in enumerate(qs):
        if j != qi:
            assert "（本题算式中的图形见下方原图）" not in str(q.get("text") or ""), \
                f"第 {j + 1} 题没有图形算式，却被加了说明"


def term_diagram_block_is_one_original_picture():
    """算式各部分名称的竖排图：标签行在、读作行在、中间夹着碎片 → 整块成图。

    真实卷（第三单元练习题 p2 第 1 题）：OCR 只读到「3            21      读作：(
    」「:」「乘数」，×、7、=、省略号和括号全丢。任何文本重建都拼不出原题，
    必须整块裁图并给题干加"各部分名称见下方原图"。
    """
    import app.extractor.figures as FG
    src = _gblock_source()
    stem = {"x": 40.0, "y": 100.0, "w": 330.0, "h": 14.0,
            "text": "1.乘法是求几个相同(      )的和的简便运算。"}
    form = {"x": 74.0, "y": 126.0, "w": 352.0, "h": 16.0,
            "text": "3            21      读作：("}
    dot = {"x": 74.0, "y": 150.0, "w": 6.0, "h": 12.0, "text": ":"}
    label = {"x": 60.0, "y": 168.0, "w": 32.0, "h": 16.0, "text": "乘数"}
    nxt = {"x": 40.0, "y": 198.0, "w": 100.0, "h": 18.0, "text": "第二步 练变式"}
    span = {"x0": 38.0, "y0": 94.0, "x1": 560.0, "y1": 194.0,
            "text_boxes": [stem, form, dot, label, nxt]}
    gb = FG._term_diagram_block(src, span)
    assert gb and gb.get("kind") == "terms", gb
    x0, y0, x1, y1 = gb["rect"]
    assert x0 <= 60.0 and x1 >= 426.0, f"竖排图没盖住标签/读作：{gb['rect']}"
    assert y0 > 114.0, f"裁框上沿盖进题干行（会被图文分离删掉）：{gb['rect']}"
    assert y1 < 198.0, f"裁框下沿吃进下一节标题：{gb['rect']}"

    # 反例①：没有独立术语标签（q28 那种「乘数是（ 读作：…」的表格式排布）
    long_label = {"x": 60.0, "y": 168.0, "w": 260.0, "h": 16.0,
                  "text": "乘数是（            读作：            还可以写成："}
    assert not FG._term_diagram_block(
        src, dict(span, text_boxes=[stem, form, dot, long_label])), \
        "不是独立标签行也当成竖排图"
    # 反例②：没有「读作」行
    no_read = dict(form, text="3            21")
    assert not FG._term_diagram_block(
        src, dict(span, text_boxes=[stem, no_read, dot, label])), "没有读作行也当成竖排图"
    # 反例③：标签离读作太远（>80pt）
    far = dict(label, y=260.0)
    assert not FG._term_diagram_block(
        src, dict(span, text_boxes=[stem, form, dot, far])), "隔了整道题还当竖排图"
    # 反例④：只有标签和读作两行、中间没有碎片 → 更像普通文字行，不裁
    assert not FG._term_diagram_block(
        src, dict(span, text_boxes=[stem, form, label])), "两行也当成竖排图"
    # 反例⑤：裁框会罩住题干行 → 不裁（否则题干被删成白卷）
    overlap = dict(form, y=104.0, h=24.0)
    assert not FG._term_diagram_block(
        src, dict(span, text_boxes=[stem, overlap, dot, label])), \
        "裁框罩住题干行也照裁"


def term_diagram_is_cropped_and_note_is_added():
    """接线：find_figures 真的把竖排图整块裁出来，题干只留第一句并补专用说明。

    这里不造 PDF：文字层版式会把「3 × 7 = 21 读作…」按空格切成三栏，
    造出来的夹具和真实扫描件不是一回事。直接给 find_figures 一份
    【已经从 OCR 读到的】spans（行框与真实卷一致），量的是接线本身。
    """
    import numpy as np
    from PIL import Image
    from app.extractor.figures import (find_figures, page_source_from_image,
                                       apply_graphic_notes, strip_text_inside_figures)
    path = os.path.join(OUT, "算式各部分名称.png")
    Image.fromarray(np.full((300, 700), 255, dtype=np.uint8)).save(path)
    src = page_source_from_image(path, 1)
    stem = {"x": 40.0, "y": 100.0, "w": 330.0, "h": 14.0,
            "text": "1.乘法是求几个相同(      )的和的简便运算。"}
    form = {"x": 74.0, "y": 126.0, "w": 352.0, "h": 16.0,
            "text": "3            21      读作：("}
    dot = {"x": 74.0, "y": 150.0, "w": 6.0, "h": 12.0, "text": ":"}
    label = {"x": 60.0, "y": 168.0, "w": 32.0, "h": 16.0, "text": "乘数"}
    span = {"q_index": 0, "page": 1, "col": 0, "y0": 94.0, "y1": 194.0,
            "x0": 38.0, "x1": 560.0,
            "text_boxes": [stem, form, dot, label]}
    qs = [{"q_no": 1, "qtype": "fill",
           "text": "乘法是求几个相同(      )的和的简便运算。 3            21 "
                   "     读作：( : 乘数"}]
    got = find_figures({1: src}, [span], OUT, questions=qs)
    imgs = got.get(0) or []
    terms = [im for im in imgs if im.get("graphic_kind") == "terms"]
    assert len(terms) == 1, f"竖排图没接上：{[(i.get('name'), i.get('graphic_kind')) for i in imgs]}"
    im = terms[0]
    assert im["w_pt"] >= 300 and im["h_pt"] >= 40, f"竖排图裁得太小：{im['rect']}"
    assert im["rect"][1] >= 118, f"竖排图把题干行裁进去了：{im['rect']}"
    strip_text_inside_figures(qs, [span], got)
    apply_graphic_notes(qs, got)
    t = str(qs[0].get("text") or "")
    assert "乘法是求几个相同" in t, t
    assert "（本题算式的各部分名称见下方原图）" in t, t
    assert "乘数" not in t and "读作" not in t, f"图内碎片还留在题干里：{t!r}"


def match_layout_block_is_one_original_picture():
    """「连一连」：水果图 + 一圈算式 + 连线空间必须整块成图，不许拆成两块图+一行字。

    真实卷（周末作业(1) p1 第 1 题）：按连通域裁只剩上下两小条水果，
    7 个算式条目被并进题干 —— 连线两端分在两处，题没法做。
    """
    import numpy as np
    import app.extractor.figures as FG
    class Src:
        pass
    src = Src()
    src.ink_thr = 128
    src.width_pt = 300.0
    src.height_pt = 300.0
    k = 100 / 72.0
    src.gray = np.full((int(300 * k), int(300 * k)), 255, dtype=np.uint8)
    bands = [(80, 70, 200, 90), (20, 110, 260, 125), (40, 140, 260, 170),
             (40, 260, 260, 275)]        # 最后一条是隔着 90pt 空白的页脚墨带
    for x0, y0, x1, y1 in bands:
        src.gray[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] = 0
    anchor = {"x": 20.0, "y": 40.0, "w": 100.0, "h": 10.0,
              "text": "1.想一想，连一连。"}
    items = {"x": 30.0, "y": 100.0, "w": 120.0, "h": 10.0,
             "text": "6+6   6个2   6X2   2X6"}
    span = {"x0": 10.0, "y0": 35.0, "x1": 290.0, "y1": 290.0,
            "text_boxes": [anchor, items]}
    gb = FG._match_layout_block(src, span)
    assert gb and gb.get("kind") == "match", gb
    x0, y0, x1, y1 = gb["rect"]
    assert y0 <= 52.0 and y1 >= 172.0, f"没盖住整组连线条目：{gb['rect']}"
    assert y1 < 240.0, f"页脚那条断开 90pt 的墨带被裁进来：{gb['rect']}"
    assert x0 <= 20.0 and x1 >= 260.0, f"三行条目没被横向盖全：{gb['rect']}"

    # 反例①：题干里没有「连一连」
    assert not FG._match_layout_block(
        src, dict(span, text_boxes=[dict(anchor, text="1.看图填空。"), items])), \
        "普通题也整块成图"
    # 反例②：题干本身带空位 → 是要作答的题，不是纯连线版式
    assert not FG._match_layout_block(
        src, dict(span, text_boxes=[dict(anchor, text="1.连一连（  ）。"), items])), \
        "带空位的题也整块成图"
    # 反例③：锚点下面还有空位 → 后面的文字不能进图
    assert not FG._match_layout_block(
        src, dict(span, text_boxes=[anchor, items,
                                    {"x": 30.0, "y": 200.0, "w": 80.0, "h": 10.0,
                                     "text": "答案：（    ）"}])), \
        "下面带空位的题也整块成图"
    # 反例③b：空位行就落在第一块墨带里 —— 只有"空位"这一条能挡（反例③
    # 同时被下面"掉出第一块"那条挡住，删掉空位判据它也照样返回 None，尺是空的）
    assert not FG._match_layout_block(
        src, dict(span, text_boxes=[anchor, items,
                                    {"x": 30.0, "y": 130.0, "w": 80.0, "h": 10.0,
                                     "text": "答案：（    ）"}])), \
        "第一块里的空位行也整块成图"
    # 反例④：锚点下面隔着一大段空白还有条目 → 结构不明确，不接管
    assert not FG._match_layout_block(
        src, dict(span, text_boxes=[anchor, items,
                                    {"x": 30.0, "y": 240.0, "w": 120.0, "h": 10.0,
                                     "text": "6+6   6个2   6X2"}])), \
        "中间断开也硬缝成一块"
    # 反例⑤：锚点下面全白（没有图/条目）→ 不裁空白
    blank = Src()
    blank.ink_thr = 128
    blank.width_pt = 300.0
    blank.height_pt = 300.0
    blank.gray = np.full((int(300 * k), int(300 * k)), 255, dtype=np.uint8)
    assert not FG._match_layout_block(
        blank, dict(span, text_boxes=[anchor])), "白纸上也裁了一块"


def match_layout_is_cropped_and_note_is_added():
    """接线：find_figures 真的把连一连整块裁出，题干只留第一句并补专用说明。"""
    import app.extractor.figures as FG
    src = _src_from_bands(400, 300, [(60, 70, 330, 95, 40),
                                     (30, 110, 370, 130, 40),
                                     (40, 150, 360, 190, 40)])
    anchor = {"x": 30.0, "y": 40.0, "w": 150.0, "h": 12.0,
              "text": "1.想一想，连一连。"}
    items = {"x": 40.0, "y": 105.0, "w": 200.0, "h": 12.0,
             "text": "6+6   6个2   6X2   2X6"}
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 380.0,
            "y0": 35.0, "y1": 250.0, "text_boxes": [anchor, items]}
    qs = [{"q_no": 1, "qtype": "fill",
           "text": "想一想，连一连。\n6+6   6个2   6X2   2X6"}]
    got = FG.find_figures({1: src}, [span], OUT, questions=qs)
    imgs = got.get(0) or []
    match = [im for im in imgs if im.get("graphic_kind") == "match"]
    assert len(match) == 1, \
        f"连一连没接上：{[(i.get('name'), i.get('graphic_kind')) for i in imgs]}"
    im = match[0]
    assert im["w_pt"] >= 300.0 and im["h_pt"] >= 100.0, f"整块裁得太小：{im['rect']}"
    assert im["rect"][1] >= 52.0, f"把题干第一句裁进图里：{im['rect']}"
    FG.strip_text_inside_figures(qs, [span], got)
    FG.apply_graphic_notes(qs, got)
    t = str(qs[0].get("text") or "")
    assert "连一连" in t, t
    assert "6+6" not in t, f"图里的条目还留在题干里：{t!r}"
    assert "照着原图连线" in t, t


def echo_full_sentence_needs_a_real_sentence_in_the_stem():
    """整题截图判据：被框住的起手行必须是一句 ≥15 字、题干里原样存在的成句。"""
    import app.extractor.figures as FG
    stem = "下面是真真同学准备分享的故事。拼一拼，写一写。（9分）"
    assert FG._echo_full_sentence("1. 下面是真真同学准备分享的故事。拼一拼，写一写。",
                                  stem), "真成句没认出来（整题截图从此切不开）"
    assert not FG._echo_full_sentence("1. 看图写话。（10分）", "看图写话。（10分）"), \
        "短句被当成成句（会把普通图当整题截图切掉）"
    assert not FG._echo_full_sentence("1. 下面是真真同学准备分享的故事。", "别的题干"), \
        "题干里没有的句子也被当成成句"


def stem_screenshot_trim_keeps_only_the_figure():
    """整题截图 → 切掉题干文字块，只留图；五个反例钉住"图片/地图不许动"。"""
    import app.extractor.figures as FG
    q_text = "下面是真真同学准备分享的故事。拼一拼，写一写。（9分）小马驮着麦子要过河。"
    rows = [{"x": 20, "y": 22, "w": 260, "h": 14,
             "text": "1. 下面是真真同学准备分享的故事。"},
            {"x": 20, "y": 38, "w": 180, "h": 14, "text": "拼一拼，写一写。（9分）"},
            {"x": 20, "y": 54, "w": 200, "h": 14, "text": "小马驮着麦子要过河。"}]
    new, why = FG._stem_echo_edit((20, 20, 300, 220), rows, q_text)
    assert why == "stem-trim" and new is not None, f"整题截图没切掉文字块：{why}"
    assert 68 < new[1] <= 76, f"下沿没贴着文字块下方第一行墨切：{new}"
    assert new[3] == 220, f"不该动下沿：{new}"

    # 反例①：文字块下面没有 ≥60pt 干净区（图就在文字中间）→ 整框不要
    tight, why2 = FG._stem_echo_edit((20, 20, 300, 70), rows, q_text)
    assert tight is None and why2 == "stem-screenshot", \
        f"切完不剩东西，却没整框丢掉：{tight} {why2}"
    # 反例②：只有一行题干被框住 → 不是整题截图，保留原框
    one, why3 = FG._stem_echo_edit(
        (20, 20, 300, 220),
        rows[:1] + [{"x": 20, "y": 300, "w": 200, "h": 14,
                     "text": "小马驮着麦子要过河。"}], q_text)
    assert one == (20, 20, 300, 220) and why3 is None, \
        f"框里只有一行题干也被当成整题截图：{one} {why3}"
    # 反例③：地图标签/子题碎行不是成句 → 不许动（综合实践卷两个公园地图）
    map_q = "竹林 喷泉 游乐场 1.喷泉的西面是（ ）。"
    map_rows = [{"x": 20, "y": 22, "w": 180, "h": 14, "text": "竹林 喷泉 游乐场"},
                {"x": 20, "y": 38, "w": 200, "h": 14, "text": "1.喷泉的西面是（ ）。"},
                {"x": 20, "y": 54, "w": 180, "h": 14, "text": "大门在教学楼的东面。"}]
    keep, why4 = FG._stem_echo_edit((20, 20, 300, 220), map_rows, map_q)
    assert keep == (20, 20, 300, 220) and why4 is None, \
        f"地图标签碎行被当成整题截图切了：{keep} {why4}"
    # 反例④：起手行够长、带括号，但【拼不出一句完整话】（横排地图标签）→ 不许动。
    #    上一反例在"选第一行"那一步就停住了，成句尺坏了也测不出来；
    #    这一条让 first 真被选中、只靠 _echo_full_sentence 拦下来。
    label_q = "竹林 喷泉 游乐场 大门 教学楼 北 北（ ） 1.喷泉的西面是（ ）。"
    label_rows = [{"x": 20, "y": 22, "w": 270, "h": 14,
                   "text": "竹林 喷泉 游乐场 大门 教学楼 北 北（ ）"},
                  {"x": 20, "y": 38, "w": 200, "h": 14, "text": "1.喷泉的西面是（ ）。"},
                  {"x": 20, "y": 54, "w": 180, "h": 14, "text": "大门在教学楼的东面。"}]
    keep2, why6 = FG._stem_echo_edit((20, 20, 300, 220), label_rows, label_q)
    assert keep2 == (20, 20, 300, 220) and why6 is None, \
        f"拼不成句的地图标签行被当成整题截图切了：{keep2} {why6}"
    # 正例（另一种方向）：文字块在下半部、图在上半部 → 收下沿
    low_rows = [{"x": 20, "y": 150, "w": 260, "h": 14,
                 "text": "1. 下面是真真同学准备分享的故事。"},
                {"x": 20, "y": 166, "w": 180, "h": 14, "text": "拼一拼，写一写。（9分）"},
                {"x": 20, "y": 182, "w": 200, "h": 14, "text": "小马驮着麦子要过河。"}]
    top, why5 = FG._stem_echo_edit((20, 20, 300, 220), low_rows, q_text)
    assert why5 == "stem-trim" and top is not None, f"文字块在下半部没切：{why5}"
    assert 140 <= top[3] < 150 and top[1] == 20, f"上沿/下沿切错：{top}"


def short_text_blocks_are_not_whole_question_screenshots():
    """L0 只认高块；气泡/说明框这类矮块不许整框丢（含三档边界）。

    真实卷（综合实践单元 q20/q22/q23）：39–99pt 的文字块右边并排着方格图；
    按"整题截图"丢掉，方格图/地图也一起没了。达标A q1 的整题截图 177pt。
    """
    import app.extractor.figures as FG
    assert FG._is_whole_question_screenshot((16.4, 161.9, 361.6, 339.2)), \
        "达标A 的整题截图没被认成高块"
    assert not FG._is_whole_question_screenshot((204.4, 55.6, 363.7, 94.4)), \
        "39pt 的说明气泡被当成整题截图"
    assert not FG._is_whole_question_screenshot((474.4, 348.4, 818.8, 447.2)), \
        "99pt 的图文同排块被当成整题截图"
    assert not FG._is_whole_question_screenshot((0, 0, 300, 119.9)), \
        "门槛下沿的矮块被当成整题截图"
    assert FG._is_whole_question_screenshot((0, 0, 300, 120.0)), \
        "门槛上沿的高块没被认成整题截图"


def whole_question_screenshot_is_dropped_before_the_stem_row_is_clipped():
    """接线检查：整题截图要在裁掉起手行【之前】判。

    真实卷（达标A 第 1 题）：裁框 [16.4,161.9,…] 把起手行 164.9–181.4 框住；
    `_clip_stem_row` 先把上沿削到 182.4，轮到 `_stem_echo_edit` 时只剩拼音和
    答案格碎片，选不到起手句 → 整题截图留了下来，图里重复一遍故事题干。
    这里合成同一结构：题干四行都印在答案格截图里，上下都没有 60pt 干净区。
    """
    import numpy as np
    import app.extractor.figures as FG
    from app.extractor.figures import find_figures, PageSource
    k = FG.DPI_PROBE / 72.0
    w, h = 300, 330
    g = np.full((int(h * k), int(w * k)), 255, dtype=np.uint8)

    def line(x0, y0, x1, y1):
        g[int(y0 * k):int(y1 * k) + 1, int(x0 * k):int(x1 * k) + 1] = 20

    # 起手行必须【顶在裁框上沿】才会被 `_clip_stem_row` 削掉 —— 真实卷是
    # 框 161.9、行 164.9（差 3pt）；这里让图框上沿（外扩后 23.6）离行顶 3.4pt。
    # 图要够高（≥120pt）才走 L0：达标A 的整题截图实测 177pt，矮块另有处理。
    gx0, gy0, gx1, gy1 = 30, 30, 260, 200
    # 左页边装饰线：真实卷是它在起手行左侧撑住裁框上沿（行框只挖 30–260 的墨）。
    # 起点 30 → 外扩后的框顶 24，离起手行 27 只差 3pt，`_clip_stem_row` 才会削它。
    line(24, 30, 26, gy1)
    line(gx0, gy0, gx1, gy0 + 2)
    line(gx0, gy1 - 2, gx1, gy1)
    line(gx0, gy0, gx0 + 2, gy1)
    line(gx1 - 2, gy0, gx1, gy1)
    for x in range(gx0 + 40, gx1, 40):
        line(x, gy0, x + 2, gy1)
    for y in range(gy0 + 20, gy1, 20):
        line(gx0, y, gx1, y + 2)

    def crop(rect, out):
        with open(out, "wb") as f:
            f.write(b"\0" * 400)
    src = PageSource(1, float(w), float(h), g, crop)
    tb = [{"x": 30, "y": 27, "w": 230, "h": 14,
           "text": "1.下面是真真同学准备分享的故事。"},
          {"x": 30, "y": 58, "w": 230, "h": 14,
           "text": "养了一只可爱的小狗，它的（    ）叫点点。"},
          {"x": 30, "y": 80, "w": 230, "h": 14,
           "text": "好的时候，它会在（    ）的花园里尽情（    ）。"},
          {"x": 30, "y": 102, "w": 230, "h": 14, "text": "玩耍。"},
          {"x": 30, "y": 124, "w": 230, "h": 14,
           "text": "它特别喜欢在（    ）里跑来跑去。"},
          {"x": 30, "y": 146, "w": 230, "h": 14,
           "text": "每次看到（    ）就摇尾巴。"},
          {"x": 30, "y": 168, "w": 230, "h": 14, "text": "我们都很喜欢它。"}]
    q_text = ("下面是真真同学准备分享的故事。养了一只可爱的小狗，它的（    ）叫点点。"
              "好的时候，它会在（    ）的花园里尽情（    ）。玩耍。"
              "它特别喜欢在（    ）里跑来跑去。每次看到（    ）就摇尾巴。"
              "我们都很喜欢它。")
    qs = [{"q_no": 1, "qtype": "fill", "text": q_text}]
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 20.0, "y1": 280.0,
              "x0": 0.0, "x1": 300.0, "text_boxes": tb}]
    rep = []
    got = find_figures({1: src}, spans, OUT, report=rep, questions=qs)
    assert not got.get(0), f"整题截图没在削题干行之前丢掉：{got.get(0)}；report={rep}"
    assert any(d.get("why") == "stem-screenshot" for d in rep if not d.get("kept")), \
        f"没走整题截图判据：{rep}"


def partially_covered_stem_rows_block_the_clean_region():
    """裁框横向切掉一截的题干行也算文字块：干净区从它下沿量（达标A q1）。

    真实卷：起手行 164.9–181.4 覆盖 0.87，故事行 216.7–233.3 只覆盖 0.71
    （行框 177–437，裁框右沿 361.6），末行 277.9–295.9 覆盖 0.74。
    旧版只按 ≥0.80 的行量文字块，把下面 43pt 的同一道练习当"干净区"，
    切一刀留下半截截图；现在 0.71/0.74 的行也占位，上下都没有 60pt → 整框丢。
    """
    import app.extractor.figures as FG
    q_text = ("下面是真真同学准备分享的故事。拼一拼，写一写。（9分）"
              "养了一只可爱的小狗，它的叫点点。好的时候，它会在花园里尽情玩耍。")
    rows = [{"x": 20, "y": 22, "w": 260, "h": 14,
             "text": "下面是真真同学准备分享的故事。"},
            {"x": 20, "y": 38, "w": 260, "h": 14,
             "text": "拼一拼，写一写。（9分）"},
            # 这两行宽 380、裁框只到 300：横向被切掉一截（覆盖 0.74）。
            {"x": 20, "y": 150, "w": 380, "h": 16,
             "text": "养了一只可爱的小狗，它的叫点点。"},
            {"x": 20, "y": 170, "w": 380, "h": 16,
             "text": "好的时候，它会在花园里尽情玩耍。"}]
    got, why = FG._stem_echo_edit((20, 20, 300, 200), rows, q_text)
    assert got is None and why == "stem-screenshot", \
        f"横向切半的题干行没挡住干净区，截图又被留下来了：{got} {why}"
    # 反例：同样的行完整落在框里（文字块在上半部）→ 下方 114pt 干净区仍在，只切文字块
    fit = [rows[0], rows[1],
           dict(rows[2], y=54, w=260), dict(rows[3], y=70, w=260)]
    got2, why2 = FG._stem_echo_edit((20, 20, 300, 200), fit, q_text)
    assert why2 == "stem-trim" and got2 is not None, \
        f"完整落在框里的文字块反而不切了：{got2} {why2}"


def number_line_below_a_stem_row_is_not_a_screenshot():
    """先收下沿的题干行，再判整题截图（第三单元练习题 q29 数轴）。

    真实卷：裁框 [69.7,343.3,513.5,430.7]；数轴刻度行 378.6–398.7 在框里，
    题干指令行 403.3–422.0 整行贴着框底。先由 `_clip_stem_row_bottom` 把
    下沿收到 402.3，`_stem_echo_edit` 就看不到"框底还有一整句"，不会把数轴
    当整题截图丢掉。顺序反了（先判截图、后收下沿）正是这次的回归。
    """
    import app.extractor.figures as FG
    tb = [{"x": 70.0, "y": 340.0, "w": 160.0, "h": 14.0,
           "text": "2.画一画,填一填。"},
          {"x": 248.6, "y": 378.6, "w": 266.8, "h": 20.1,
           "text": "9101112131415161718192021"},
          {"x": 77.1, "y": 403.3, "w": 486.3, "h": 18.7,
           "text": "青蛙1次跳4格,兔子1次跳(      )个4格。兔子跳1次的距离是青蛙的"}]
    q_text = ("画一画,填一填。9101112131415161718192021青蛙1次跳4格,"
              "兔子1次跳(      )个4格。兔子跳1次的距离是青蛙的（ ）倍。")
    rect = (69.7, 343.3, 513.5, 430.7)
    cut = FG._clip_stem_row_bottom(rect, tb, ())
    assert cut[3] < 410.0, f"下沿没收到题干行上面：{cut}"
    kept, why = FG._stem_echo_edit(cut, tb, q_text)
    assert kept == cut and why is None, f"数轴被当成整题截图了：{kept} {why}"
    # 反例：顺序反过来（先判截图）→ 数轴整张丢，正是这次修掉的真卷缺陷
    shot, why2 = FG._stem_echo_edit(rect, tb, q_text)
    assert shot is None and why2 == "stem-screenshot", \
        f"夹具没重现「先判截图会丢数轴」：{shot} {why2}"


def screenshot_fragments_are_dropped_with_the_screenshot():
    """整题截图被丢后，截图里的答题格碎片不许单独出图（达标A q1）。

    真实卷：86×46 的 "míng zi" 答题格纵向 100% 落在截图里、右沿多出 2.9pt；
    截图还在时它由 `_drop_contained` 吃掉，截图先丢后它就成了没头没尾的图。
    """
    import app.extractor.figures as FG
    shot = (16.4, 161.9, 361.6, 339.2)
    cands = [
        {"page": 1, "q_index": 0, "rect": (318.1, 202.9, 403.9, 249.2)},
        {"page": 1, "q_index": 0, "rect": (20.0, 380.0, 200.0, 440.0)},
        {"page": 1, "q_index": 0, "rect": (500.0, 200.0, 600.0, 260.0)},
        {"page": 1, "q_index": 0, "rect": (16.4, 161.9, 361.6, 339.2),
         "graphic": True},
    ]
    rep = []
    got = FG._drop_shot_fragments(cands, {(1, 0): [shot]}, rep)
    rects = [c["rect"] for c in got]
    assert (318.1, 202.9, 403.9, 249.2) not in rects, "截图里的答题格碎片没丢"
    assert len(got) == 3, f"误伤了别的图：{rects}"
    assert any(d.get("why") == "contained" for d in rep), "没留下 contained 记录"


def page_edge_scan_band_is_not_a_figure():
    """贴物理页边、又矮又宽的【空白】灰带＝扫描压痕；页顶的真图不许砍。"""
    import app.extractor.figures as FG
    src = _src_from_bands(440, 653, [(0, 627, 437, 652, 210)])
    assert FG._is_page_edge_band((0, 627, 437, 653), src), "页边压痕没认出来"
    assert not FG._is_page_edge_band((20, 300, 420, 330), src), "页中间的图被当成压痕"
    assert not FG._is_page_edge_band((0, 590, 437, 653), src), "53pt 高的图被当成压痕"
    assert not FG._is_page_edge_band((0, 627, 60, 653), src), "窄条被当成压痕"
    # 反例⑤：贴页顶、又矮又宽，但有实笔画 —— 是地图/表格，不是压痕。
    # 真实卷（综合实践单元(1) p1 第 6 题、p2 第 19 题）就是这样被误砍的。
    real = _src_from_bands(440, 653, [(200, 5, 330, 35, 30)])
    assert not FG._is_page_edge_band((200, 5, 330, 35), real), "页顶的真图被当成压痕"
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 560.0, "y1": 653.0,
              "x0": 0.0, "x1": 437.0,
              "text_boxes": [{"x": 40, "y": 610, "w": 200, "h": 12,
                              "text": "3.看图列式。"}]}]
    rep = []
    got = FG.find_figures({1: src}, spans, OUT, report=rep)
    assert not got.get(0), f"页边压痕被当成配图：{got.get(0)}；report={rep}"
    assert any(d.get("why") == "page-edge" for d in rep if not d.get("kept")), \
        f"没走页边压痕判据：{rep}"


def edge_ink_extension_reconnects_a_cut_border():
    """栏界把图框线切断 → 只接【从框边起连续有墨】的条带；窄条不接。"""
    import numpy as np
    import app.extractor.figures as FG
    from app.extractor.figures import PageSource, DPI_PROBE
    k = DPI_PROBE / 72.0

    def src_with(bands):
        g = np.full((int(120 * k), int(220 * k)), 255, dtype=np.uint8)
        for (x0, y0, x1, y1) in bands:
            g[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] = 30
        return PageSource(1, 220.0, 120.0, g, lambda rect, out: None)

    src = src_with([(60, 40, 135, 60)])
    out = FG._extend_edge_ink((60, 30, 125, 70), src, k, np, "right", 180.0)
    assert 134 <= out[2] <= 137, f"框外的连续墨没接回来：{out}"
    # 反例①：框边先空 5pt 再出现墨 → 不是这张图的延续
    src2 = src_with([(60, 40, 125, 60), (130, 40, 145, 60)])
    out2 = FG._extend_edge_ink((60, 30, 125, 70), src2, k, np, "right", 180.0)
    assert out2 == (60, 30, 125, 70), f"隔着空白也接宽了：{out2}"
    # 反例②：窄条（<60pt）不接 —— 达标A q1 的页边装饰就是这样被放过的
    out3 = FG._extend_edge_ink((60, 30, 90, 70), src, k, np, "right", 180.0)
    assert out3 == (60, 30, 90, 70), f"窄条也被接宽了：{out3}"
    # 正例（左）：墨从框左沿连续往左
    src3 = src_with([(30, 40, 125, 60)])
    out4 = FG._extend_edge_ink((60, 30, 125, 70), src3, k, np, "left", 20.0)
    assert 28 <= out4[0] <= 31, f"左侧连续墨没接回来：{out4}"


def _src_from_bands(w: float, h: float, bands):
    """按 (x0,y0,x1,y1,灰度) 画一张探测图；crop 写一个够大的假文件让裁图保留。"""
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0
    g = np.full((int(h * k), int(w * k)), 255, dtype=np.uint8)
    for x0, y0, x1, y1, v in bands:
        g[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] = v

    def crop(rect, out):
        with open(out, "wb") as f:
            f.write(b"\0" * 400)
    return FG.PageSource(1, float(w), float(h), g, crop)


def map_label_tokens_keep_the_stem_body():
    """地图标签行：只认行首短图注，题干正文（含括号空位）必须原样留下。

    真实卷（综合实践单元(1) p2 第 1 题）OCR 把地图标签和题干拼成一行；
    整行删掉会丢题干，整行留下又和图里的标签重复。
    """
    import app.extractor.figures as FG
    assert FG._leading_label_tokens(
        "莲池      假山            2.莲池在凉亭的（     )面，在") == ["莲池", "假山"]
    assert FG._leading_label_tokens(
        "喷泉      游乐场            是（    )。(4分)") == ["喷泉", "游乐场"]
    # 反例①：纯正文行（无人配送车旁）哪怕有空格也不是图注
    assert FG._leading_label_tokens("画出1号无人配送车的行驶路线。(6分）") == []
    # 反例②：行首长词（>4 字）不是图注
    assert FG._leading_label_tokens("无人配送车      画出路线。(6分）") == []
    # 反例③：标签后面没有正文 → 不摘，免得整行被当图注删光
    assert FG._leading_label_tokens("东北      喷泉      游乐场") == []
    # 反例④：剩下的正文里没有数字/标点 → 更像地图注记，不动
    assert FG._leading_label_tokens(
        "东北      喷泉      游乐场      凉亭      假山风景") == []
    # 反例⑤：只剩一对括号/标点也不够正文（否则整行图注会被删光）
    assert FG._leading_label_tokens("东北      喷泉      （    )") == []


def diagram_label_shape_has_hard_counter_examples():
    """图注形状只认"短、无句读、不是题号"；真题干的反例一条都不许过。"""
    import app.extractor.figures as FG
    assert FG._diagram_label_like("①十里堡站")
    assert FG._diagram_label_like("呼家楼金台路?")
    assert FG._diagram_label_like("教学楼      (  ↑      综合楼   体育馆")
    assert FG._diagram_label_like("★光明小学大门▲祥和小区出口")
    # 反例①：带空作答位的题干
    assert not FG._diagram_label_like("龙龙面向（       )。")
    # 反例②：有逗号的整句
    assert not FG._diagram_label_like("体育课上，同学们一开始面向北站立")
    # 反例③：题号起手
    assert not FG._diagram_label_like("3.下面是北京地铁部分线路示意图。")
    # 反例④：只有数字/方位、没有汉字（8513 这类门牌号是图的一部分，但形状分不清）
    assert not FG._diagram_label_like("85018502 8506 8507 8512")
    # 反例⑤：一整排短标签（总长超过上限）是图例/正文行，不是单个图注
    assert not FG._diagram_label_like(
        "教学楼 综合楼 体育馆 艺术楼 图书馆 实验楼 报告厅 运动场 升旗台"), \
        "超过 24 字的整排图例被当成图注"


def map_labels_in_option_rows_are_trimmed():
    """选项行伸进图框：图里那截地名从选项里摘掉，真选项和带逗号的正文不动。"""
    import app.extractor.figures as FG
    boxes = [
        {"x": 212.0, "y": 122.0, "w": 116.0, "h": 7.0,
         "text": "①十里堡站            呼家楼金台路?"},
        {"x": 212.0, "y": 133.0, "w": 116.0, "h": 7.0,
         "text": "②大望路站            金台夕照○国贸大望路"},
        {"x": 212.0, "y": 143.0, "w": 28.0, "h": 7.0,
         "text": "③呼家楼站"},
        {"x": 212.0, "y": 155.0, "w": 140.0, "h": 7.0,
         "text": "④从公园东门出发，一直向西走到书店"},
        {"x": 180.0, "y": 165.0, "w": 60.0, "h": 7.0,
         "text": "⑤公园"},
    ]
    opts = [b["text"] for b in boxes]
    qs = [{"q_no": 3, "text": "下面是北京地铁部分线路示意图。",
           "options": list(opts)}]
    span = {"q_index": 0, "page": 1, "col": 0, "y0": 110.0, "y1": 175.0,
            "x0": 0.0, "x1": 400.0, "text_boxes": boxes}
    got = {0: [{"rect": [292.0, 120.0, 359.0, 152.0]}]}
    n = FG.strip_text_inside_figures(qs, [span], got)
    assert qs[0]["options"][:3] == ["①十里堡站", "②大望路站", "③呼家楼站"], \
        f"选项里的图注没摘：{qs[0]['options']}"
    # 反例①：选项带完整句子（逗号）→ 一个字都不许少
    assert qs[0]["options"][3] == "④从公园东门出发，一直向西走到书店"
    # 反例②：选项整行在图的左边（没伸进图框）→ 不动
    assert qs[0]["options"][4] == "⑤公园"
    assert n == 2, f"只该改两条选项，实际 {n} 条"


def diagram_row_straddling_the_crop_is_not_stem():
    """裁框上沿切进图注行 64%：这一行在图里也有，不能再当题干。"""
    import app.extractor.figures as FG
    boxes = [
        {"x": 28.8, "y": 139.4, "w": 126.5, "h": 6.3,
         "text": "3.小朋友们在操场上辨认方向，请帮他们补全记录单。"},
        {"x": 55.0, "y": 150.2, "w": 104.1, "h": 7.5,
         "text": "小亮的记录单            小丽的记录单"},
        {"x": 39.1, "y": 167.3, "w": 137.3, "h": 6.9,
         "text": "教学楼      (  ↑      综合楼   体育馆     ↑    艺术楼"},
    ]
    qs = [{"q_no": 3, "text":
           "小朋友们在操场上辨认方向，请帮他们补全记录单。 "
           "小亮的记录单            小丽的记录单\n"
           "教学楼 ( ↑ 综合楼 体育馆 ↑ 艺术楼"}]
    span = {"q_index": 0, "page": 1, "col": 0, "y0": 135.0, "y1": 210.0,
            "x0": 0.0, "x1": 250.0, "text_boxes": boxes}
    got = {0: [{"rect": [33.7, 169.8, 181.6, 207.5]}]}
    n = FG.strip_text_inside_figures(qs, [span], got)
    text = qs[0]["text"]
    assert "教学楼" not in text and "艺术楼" not in text, f"跨框图注还在：{text!r}"
    # 上面的两行只露出图框外，不按图注删（图上并没有完整重复这两行）
    assert "小亮的记录单" in text
    assert "请帮他们补全记录单" in text
    assert n == 1
    # 反例：同样的几何，但那一行是带逗号的题干 → 不许当图注删
    assert not FG._diagram_row_hit(
        (39.1, 167.3, 176.4, 174.2),
        "教学楼里同学们正在上课，请写出他们的方向。",
        (33.7, 169.8, 181.6, 207.5))


def first_stem_line_only_loses_its_map_labels():
    """起手句保护只挡整行删除：行尾那截伸进图里的图注仍要摘掉。"""
    import app.extractor.figures as FG
    boxes = [{"x": 28.8, "y": 204.7, "w": 119.8, "h": 7.2,
              "text": "4.如右图所示，两名同学玩背靠背夹    我面向东。"}]
    qs = [{"q_no": 4, "text": "如右图所示，两名同学玩背靠背夹    我面向东。"}]
    span = {"q_index": 0, "page": 1, "col": 0, "y0": 200.0, "y1": 230.0,
            "x0": 0.0, "x1": 250.0, "text_boxes": boxes}
    got = {0: [{"rect": [118.0, 201.7, 176.5, 226.8]}]}
    FG.strip_text_inside_figures(qs, [span], got)
    text = qs[0]["text"]
    assert "我面向东" not in text, f"行尾图注没摘：{text!r}"
    assert "两名同学玩背靠背夹" in text, f"起手句被删残：{text!r}"
    # 行框带题号、题干已剥题号：替换段必须来自题干，不许把 "4." 抄回来
    assert not text.startswith("4."), f"行框题号被抄进题干：{text!r}"
    # 反例①：图在正文左边（标签不该从右边摘）→ 原样不动
    qs2 = [{"q_no": 4, "text": "如右图所示，两名同学玩背靠背夹    我面向东。"}]
    got2 = {0: [{"rect": [5.0, 201.7, 100.0, 226.8]}]}
    FG.strip_text_inside_figures(qs2, [span], got2)
    assert "我面向东" in qs2[0]["text"], "图在左边也把行尾摘了"
    # 反例②：尾巴是带逗号的正文（不是图注）→ 不摘
    qs3 = [{"q_no": 4, "text": "4.如右图所示，两名同学玩背靠背夹    我面向东，然后转身向东走。"}]
    span3 = dict(span, text_boxes=[dict(boxes[0],
                 text="4.如右图所示，两名同学玩背靠背夹    我面向东，然后转身向东走。")])
    FG.strip_text_inside_figures(qs3, [span3], got)
    assert "然后转身向东走" in qs3[0]["text"], f"带逗号的正文被当图注摘了：{qs3[0]['text']!r}"
    # 反例③：空白缝落在作答括号里（第三单元练习题 p1 第 1 题）→ 不许把 ")个" 摘走
    qs4 = [{"q_no": 1, "text": "1.一共有(       )个"}]
    span4 = {"q_index": 0, "page": 1, "col": 0, "y0": 120.0, "y1": 160.0,
             "x0": 0.0, "x1": 250.0,
             "text_boxes": [{"x": 29.5, "y": 128.5, "w": 131.5, "h": 17.8,
                             "text": "1.一共有(       )个"}]}
    got4 = {0: [{"rect": [133.8, 125.5, 196.7, 155.6]}]}
    FG.strip_text_inside_figures(qs4, [span4], got4)
    assert qs4[0]["text"] == "1.一共有(       )个", \
        f"作答括号里的空白被当成图注缝：{qs4[0]['text']!r}"


def figure_top_grows_over_a_cut_table_row():
    """裁框上沿从表格行中间切过：整行连同表头并进图里（含三个反例）。"""
    import app.extractor.figures as FG
    boxes = [
        {"x": 28.8, "y": 139.4, "w": 126.5, "h": 6.3,
         "text": "3.小朋友们在操场上辨认方向，请帮他们补全记录单。"},
        {"x": 55.0, "y": 150.2, "w": 104.1, "h": 7.5,
         "text": "小亮的记录单            小丽的记录单"},
        {"x": 62.6, "y": 158.9, "w": 88.8, "h": 6.9,
         "text": "体育馆            （东）综合楼"},
        {"x": 39.1, "y": 167.3, "w": 137.3, "h": 6.9,
         "text": "教学楼      (  ↑            综合楼       体育馆            ↑            艺术楼"},
    ]
    got = FG._grow_over_cut_label_rows((33.7, 169.8, 181.6, 207.5), boxes)
    assert abs(got[1] - 150.2) < 0.6, f"表头没并进图框：{got}"
    assert got[0] == 33.7 and got[2] == 181.6 and got[3] == 207.5, f"不该动别的沿：{got}"
    # 反例①：切点那行是带逗号的正文 → 一行都不并
    sent = [dict(boxes[3], text="教学楼，综合楼，体育馆，艺术楼")]
    assert FG._grow_over_cut_label_rows((33.7, 169.8, 181.6, 207.5), sent)[1] == 169.8
    # 反例②：图注行伸出框外（是正文/邻栏）→ 不并
    wide = [dict(boxes[3], w=260.0)]
    assert FG._grow_over_cut_label_rows((33.7, 169.8, 181.6, 207.5), wide)[1] == 169.8
    # 反例③：表头离切点太远（隔着一行正文）→ 只并切点那一行
    far = [dict(boxes[1], y=130.0), dict(boxes[2], y=145.0), boxes[3]]
    assert abs(FG._grow_over_cut_label_rows(
        (33.7, 169.8, 181.6, 207.5), far)[1] - 167.3) < 0.6


def right_edge_label_fused_into_a_stem_line_is_absorbed():
    """题干行右端并着图注（"行驶路线如右图。      古城9"）时，上沿要长过整行。

    真实卷 P1 第 4 页第 13 题：OCR 把地图右上角的"古城"并进了题干第二行，
    图的地图墨迹从 y=38.8 才被认出，裁框上沿正好切在这行（31.0–44.0）中间——
    旧判据只看"整行是不是短图注"，长句带句号一律拒绝，结果裁出的地图
    只剩一条线，目的地标签和端点都留在框外（独立复测 P1-04 同类）。
    反例：同样带长空格的正文行、右端没贴着图右边沿的短尾、以及尾巴带句读的行。
    """
    import app.extractor.figures as FG
    rect = (221.6, 38.8, 301.8, 149.2)
    boxes = [
        {"x": 37.1, "y": 19.1, "w": 240.1, "h": 12.6,
         "text": "13.李叔叔一家开车从幸福镇出发去古城游玩，全程428千米，"},
        {"x": 50.4, "y": 31.0, "w": 253.8, "h": 13.0,
         "text": "行驶路线如右图。            古城9"},
    ]
    got = FG._grow_over_cut_label_rows(rect, boxes)
    assert abs(got[1] - 31.0) < 0.6, f"右端图注没随整行并进图框：{got}"
    assert got[0] == rect[0] and got[2] == rect[2] and got[3] == rect[3]
    # 反例①：正文行带长空格、尾巴短，但右端离图右边沿很远 → 不并
    far = [dict(boxes[1], w=140.0)]
    assert FG._grow_over_cut_label_rows(rect, far)[1] == 38.8
    # 反例②：尾巴带句读（不是图注）→ 不并
    punct = [dict(boxes[1], text="行驶路线如右图。            大致位置。")]
    assert FG._grow_over_cut_label_rows(rect, punct)[1] == 38.8
    # 反例③：整行就是一句正文（没有长空格隔出的短尾）→ 不并
    sent = [dict(boxes[1], text="行驶路线如右图，从幸福镇出发去古城游玩。")]
    assert FG._grow_over_cut_label_rows(rect, sent)[1] == 38.8


def figure_edge_grow_respects_the_question_band():
    """图注生长不许越过本题区间：上沿别吞上一题图注，下沿别吞下一题。

    P5 Q14：社团统计图的区间从 160pt 才开始，上一题窗户的尺寸行 "-2m-→"
    落在 150.2pt —— 不设上界时会被并进 Q14 的图里。
    """
    import app.extractor.figures as FG
    boxes = [
        {"x": 28.8, "y": 139.4, "w": 126.5, "h": 6.3,
         "text": "3.小朋友们在操场上辨认方向，请帮他们补全记录单。"},
        {"x": 55.0, "y": 150.2, "w": 104.1, "h": 7.5,
         "text": "小亮的记录单            小丽的记录单"},
        {"x": 62.6, "y": 158.9, "w": 88.8, "h": 6.9,
         "text": "体育馆            （东）综合楼"},
        {"x": 39.1, "y": 167.3, "w": 137.3, "h": 6.9,
         "text": "教学楼      (  ↑            综合楼       体育馆            ↑            艺术楼"},
    ]
    rect = (33.7, 169.8, 181.6, 207.5)
    assert abs(FG._grow_over_cut_label_rows(rect, boxes)[1] - 150.2) < 0.6
    # 区间从 155 才开始：150.2 那行是上一题的，只能长到 158.9
    got = FG._grow_over_cut_label_rows(rect, boxes, top_limit=155.0)
    assert abs(got[1] - 158.9) < 0.6, f"越过本题区间上沿生长了：{got}"
    # 区间从 160 才开始：158.9 也在上一题，只能长到切点那行 167.3
    got160 = FG._grow_over_cut_label_rows(rect, boxes, top_limit=160.0)
    assert abs(got160[1] - 167.3) < 0.6, f"越过本题区间上沿生长了：{got160}"
    # 切点那行本身也在区间外（是上一题的）→ 一点不长
    assert FG._grow_over_cut_label_rows(rect, boxes, top_limit=168.0)[1] == 169.8

    under = [{"x": 70.0, "y": 150.0, "w": 60.0, "h": 6.0, "text": "24cm"}]
    r2 = (64.0, 70.4, 249.0, 152.8)
    assert abs(FG._grow_under_cut_label_rows(r2, under)[3] - 156.0) < 0.6
    got2 = FG._grow_under_cut_label_rows(r2, under, bottom_limit=151.0)
    assert got2[3] == 152.8, f"越过本题区间下沿生长了：{got2}"


def options_row_below_a_figure_is_not_absorbed():
    """图下紧贴着 A./B./C./D. 选项行：不许裁进图里给孩子看第二遍。

    真实卷 P1 第 7 题：③④ 标签行收进来后，下沿离选项行只有 1.2pt；
    选项行每段 ≤8 字、总长正好 24 字，形状刚好落进 `_diagram_label_like`，
    旧版下沿生长把整行选项裁进图里（选项已经作为文字印过一遍）。
    选项行不是图注。正例是同一位置的 "24cm" 仍要长进来。
    """
    import app.extractor.figures as FG
    rect = (36.6, 309.9, 305.4, 495.6)
    row = {"x": 41.8, "y": 496.8, "w": 250.6, "h": 13.3,
           "text": "A.只有①       B.只有②④      C.只有①③     D.只有①③④"}
    assert FG._looks_like_options_row(row["text"])
    assert not FG._looks_like_options_row("24cm")
    assert not FG._looks_like_options_row("一共有多少个笑脸？            一共需要多少元？")
    assert FG._grow_under_cut_label_rows(rect, [row])[3] == 495.6, \
        "选项行被裁进图里重复了"
    lab = [{"x": 70.0, "y": 496.8, "w": 60.0, "h": 6.0, "text": "24cm"}]
    assert abs(FG._grow_under_cut_label_rows(rect, lab)[3] - 502.8) < 0.6
    # 上沿同理：选项行从框上沿切过时也不许并进来（同位置换成图注则要并）
    over = dict(row, y=506.3, h=13.3)
    assert FG._grow_over_cut_label_rows((36.6, 512.0, 305.4, 600.0), [over])[1] == 512.0
    lab2 = [{"x": 70.0, "y": 506.3, "w": 40.0, "h": 8.0, "text": "古城"}]
    assert abs(FG._grow_over_cut_label_rows((36.6, 512.0, 305.4, 600.0), lab2)[1] - 506.3) < 0.6


def figure_side_grows_over_a_dimension_label():
    """图形右侧/左侧的尺寸标注落在框外：横向长到包住它（含反例）。

    P3 第 2 页第四大题第 2 小题：梯形的 24cm 在框内，右侧的高 8cm 因为和
    图形之间有一小段空白，被连通域漏掉 —— 图里没有高，面积题没法做。
    """
    import app.extractor.figures as FG
    rect = (110.0, 100.0, 140.0, 160.0)
    boxes = [
        {"x": 80.0, "y": 120.0, "w": 22.0, "h": 6.0, "text": "8cm"},
        {"x": 146.0, "y": 120.0, "w": 22.0, "h": 6.0, "text": "10cm"},
        {"x": 175.0, "y": 120.0, "w": 20.0, "h": 6.0, "text": "8cm"},      # 缝 35pt > 24
        {"x": 146.0, "y": 200.0, "w": 40.0, "h": 6.0, "text": "8cm"},      # 纵向在图外
        {"x": 146.0, "y": 120.0, "w": 60.0, "h": 6.0, "text": "8cm，量一量"},  # 正文不是图注
    ]
    got = FG._grow_side_dim_label_rows(rect, boxes)
    assert [round(v, 1) for v in got] == [80.0, 100.0, 168.0, 160.0], got
    # 反例：贴得最近的只有一条 35pt 外的 → 原样不动
    assert FG._grow_side_dim_label_rows(rect, [boxes[2]]) == rect


def side_label_fused_into_a_stem_line_is_absorbed():
    """题干行右端并着图注、图注骑在框的侧沿上：横向让出整段（含反例）。

    真实卷 P1 第 4 页第 13 题：地图左下角"幸福镇"和题干"大致位置。"
    被 OCR 读成同一行（长空格隔开），裁框左沿正好从"幸福镇"中间切过——
    图上只剩"福镇"两个字。旧判据只认整行短图注，整行带句号直接跳过。
    """
    import app.extractor.figures as FG
    rect = (221.6, 32.2, 301.8, 149.2)
    row = [{"x": 60.8, "y": 123.1, "w": 181.1, "h": 13.0,
            "text": "大致位置。            幸福镇"}]
    got = FG._grow_side_dim_label_rows(rect, row)
    assert got[0] < 205.0, f"左沿没让出图注：{got}"
    assert abs(got[0] - (241.9 - 3 * 13.0 * 1.1)) < 1.0, got
    assert got[1] == rect[1] and got[2] == rect[2] and got[3] == rect[3]
    # 反例①：图注整段在框内（左沿没切到它）→ 不动
    inside = [dict(row[0], x=230.0, w=60.0)]
    assert FG._grow_side_dim_label_rows(rect, inside) == rect
    # 反例②：行尾是正文短词、不是图注形状（带句读）→ 不动
    punct = [dict(row[0], text="大致位置。            幸福镇。")]
    assert FG._grow_side_dim_label_rows(rect, punct) == rect


def label_grow_is_wired_into_find_figures():
    """接线检查：向上并整行图注这一步真的跑在 find_figures 里。"""
    import app.extractor.figures as FG
    src = _src_from_bands(200, 200, [(20, 60, 120, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 200.0,
              "text_boxes": [{"x": 20, "y": 55, "w": 130, "h": 6,
                              "text": "1.看图填空。"}]}]
    real = FG._grow_over_cut_label_rows
    calls = []

    def spy(rect, boxes, **kw):
        calls.append(tuple(rect))
        calls[-1] = calls[-1] + (kw.get("top_limit"),)
        return (rect[0], rect[1] - 10.0, rect[2], rect[3])

    FG._grow_over_cut_label_rows = spy
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._grow_over_cut_label_rows = real
    imgs = got.get(0) or []
    assert calls and imgs, f"并整行图注根本没跑：calls={calls}, rep={rep}"
    assert imgs[0]["rect"][1] <= calls[0][1] - 9.0, \
        f"上沿没落进输出框：{imgs[0]['rect']} vs {calls[0]}"
    assert any(x.get("why") == "label-grow" for x in rep), \
        f"报告里没留下 label-grow：{rep}"
    # 上沿不许越过本题区间起点：P5 Q14 曾把上一题窗户的 "-2m-→" 长进自己图里。
    assert calls[0][-1] is not None and abs(calls[0][-1] - 50.0) < 1.0, \
        f"没把本题区间上沿传给图注生长：{calls[0]}"


def leading_map_labels_on_a_continuation_line_are_trimmed():
    """续行行首落在图里、行尾伸到图外：摘行首地名，正文必须留（含两个反例）。"""
    import app.extractor.figures as FG
    boxes = [
        {"x": 53.8, "y": 44.9, "w": 103.9, "h": 6.2,
         "text": "喷泉      游乐场            是（    )。(4分)"},
        {"x": 53.8, "y": 57.1, "w": 123.6, "h": 7.2,
         "text": "莲池      假山            2.莲池在凉亭的（     )面，在"},
        {"x": 53.8, "y": 67.2, "w": 119.5, "h": 5.8,
         "text": "凉亭            假山的（     )面。(4分)"},
    ]
    qs = [{"q_no": 2,
           "text": "莲池在凉亭的（     )面，在 凉亭            假山的（     )面。(4分)"}]
    span = {"q_index": 0, "page": 2, "col": 0, "y0": 40.0, "y1": 80.0,
            "x0": 0.0, "x1": 200.0, "text_boxes": boxes}
    got = {0: [{"rect": [25.1, 30.7, 108.6, 80.9]}]}
    n = FG.strip_text_inside_figures(qs, [span], got)
    text = qs[0]["text"]
    assert "凉亭            假山" not in text, f"行首图注没摘：{text!r}"
    assert text.count("凉亭") == 1, f"正文里的凉亭被删了：{text!r}"
    assert "假山的（     )面" in text, f"正文被删残：{text!r}"
    assert n >= 1
    # 反例①：这一行整体在图左边（行首不在图里）→ 一行都不摘
    qs2 = [{"q_no": 2, "text": "莲池在凉亭的（     )面，在 凉亭            假山的（     )面。(4分)"}]
    got2 = {0: [{"rect": [120.0, 30.7, 190.0, 80.9]}]}
    FG.strip_text_inside_figures(qs2, [span], got2)
    assert "凉亭            假山" in qs2[0]["text"], "图在右边却把行首摘了"
    # 反例②：行首没有 2 个空格的标签（单空格是正常正文）→ 不摘
    qs3 = [{"q_no": 2, "text": "莲池在凉亭的（     )面，在 凉亭 假山的（     )面。(4分)"}]
    span3 = dict(span, text_boxes=[dict(boxes[2], text="凉亭 假山的（     )面。(4分)")])
    FG.strip_text_inside_figures(qs3, [span3], got)
    assert "凉亭 假山" in qs3[0]["text"], "正常正文被当图注摘了"


def cross_question_graze_trims_the_upper_figure():
    """上一题的图底蹭进下一题的图几个点：只收上题底沿（含三个反例）。"""
    import copy
    import app.extractor.figures as FG
    base = [
        {"q_index": 3, "page": 1, "rect": (33.7, 150.2, 181.6, 207.5)},
        {"q_index": 4, "page": 1, "rect": (118.0, 201.7, 176.5, 226.8)},
    ]
    rep = []
    got = FG._trim_cross_question_graze(copy.deepcopy(base), rep)
    assert abs(got[0]["rect"][3] - 201.2) < 0.6, f"上题底沿没收：{got[0]['rect']}"
    assert got[1]["rect"] == (118.0, 201.7, 176.5, 226.8), f"下题不该动：{got[1]['rect']}"
    assert any(x.get("why") == "cross-graze" for x in rep), f"报告没留痕：{rep}"
    # 反例①：重叠 20pt（共享图/大段重叠）→ 不动
    deep = copy.deepcopy(base)
    deep[0]["rect"] = (33.7, 150.2, 181.6, 221.7)
    assert FG._trim_cross_question_graze(deep, None)[0]["rect"][3] == 221.7
    # 反例②：同一题的两块 → 不动
    same = copy.deepcopy(base)
    same[1]["q_index"] = 3
    assert FG._trim_cross_question_graze(same, None)[0]["rect"][3] == 207.5
    # 反例③：横向只擦到一点边 → 不动
    narrow = copy.deepcopy(base)
    narrow[1]["rect"] = (175.0, 201.7, 230.0, 226.8)
    assert FG._trim_cross_question_graze(narrow, None)[0]["rect"][3] == 207.5
    # 反例④：底沿刚并进来的是一条表格边框（border_strip）→ 不是邻题人头，不许削
    strip = copy.deepcopy(base)
    strip[0]["border_strip"] = True
    assert FG._trim_cross_question_graze(strip, None)[0]["rect"][3] == 207.5, \
        "表格底边被当成邻题人头削掉了"


def cross_graze_trim_is_wired_into_find_figures():
    """接线检查：跨题蹭边收回这一步真的跑在 find_figures 里。"""
    import app.extractor.figures as FG
    src = _src_from_bands(200, 200, [(20, 60, 120, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 200.0,
              "text_boxes": [{"x": 20, "y": 55, "w": 130, "h": 6,
                              "text": "1.看图填空。"}]}]
    real = FG._trim_cross_question_graze
    calls = []

    def spy(cands, report):
        calls.append(len(cands))
        for c in cands:
            c["rect"] = (c["rect"][0], c["rect"][1], c["rect"][2], c["rect"][3] - 4.0)
            if report is not None:
                report.append({"q_index": c["q_index"], "page": c["page"],
                               "kept": True, "rect": list(c["rect"]),
                               "why": "cross-graze"})
        return cands

    FG._trim_cross_question_graze = spy
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._trim_cross_question_graze = real
    imgs = got.get(0) or []
    assert imgs, f"跨题蹭边收回后图没了：calls={calls}, rep={rep}"
    # 两次都必须接：第一次在缝合/复检后，第二次在"矮图长回真边"之后。
    # 只断言"跑过"会漏掉第二次被拆线（海淀六上 p4 第 12/13 题的窗户顶
    # 恰恰是长回真边之后才蹭进上一题）。
    assert len(calls) >= 2, (
        f"跨题蹭边收回只跑了 {len(calls)} 次，长回真边后的那一次没接线：rep={rep}")
    assert any(x.get("why") == "cross-graze" for x in rep), \
        f"报告里没留下 cross-graze：{rep}"


def side_text_split_stops_before_the_stem_body():
    """地图在左、题干被 OCR 拼在右：沿图注与正文间最宽空白收右沿。

    含反例：纯正文行（无人配送车旁的解题说明）不许据此切框 ——
    实测会沿着说明文字切掉右侧方格图（q22/q23）。
    """
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0
    g = np.full((int(120 * k), int(250 * k)), 255, dtype=np.uint8)
    g[int(15 * k):int(90 * k), int(10 * k):int(95 * k)] = 60      # 地图
    g[int(20 * k):int(40 * k), int(100 * k):int(118 * k)] = 60    # 指北针
    for yy in (20, 40, 60, 80):
        g[int(yy * k):int((yy + 8) * k), int(130 * k):int(150 * k)] = 30
        g[int(yy * k):int((yy + 8) * k), int(160 * k):int(220 * k)] = 30
    src = FG.PageSource(1, 250.0, 120.0, g, lambda rect, out: None)
    boxes = [
        {"x": 40.0, "y": 20.0, "w": 190.0, "h": 8.0,
         "text": "东北           1.喷泉的西面是（     )，东面"},
        {"x": 40.0, "y": 40.0, "w": 190.0, "h": 8.0,
         "text": "喷泉      游乐场            是（     )。(4分)"},
        {"x": 40.0, "y": 60.0, "w": 190.0, "h": 8.0,
         "text": "莲池      假山            2.莲池在凉亭的（     )面，在"},
        {"x": 40.0, "y": 80.0, "w": 190.0, "h": 8.0,
         "text": "凉亭              假山的（     )面。(4分)"},
    ]
    out = FG._split_side_text_figure((5.0, 10.0, 230.0, 100.0), boxes, src, np, k)
    assert out is not None, "地图＋题干同排没切开"
    # 正文从 129.6 起：右沿必须停在它左边，且不能把指北针/地图削掉
    assert out[2] <= 131.0, f"右沿切进题干正文：{out}"
    assert out[2] >= 118.0, f"右沿切进图里，指北针被削：{out}"
    assert out[0] == 5.0 and out[3] == 100.0, f"不该动左/下沿：{out}"
    # 反例：同样的几何，但 OCR 行是纯正文（没有行首图注）→ 一刀都不许切
    pure = [dict(b, x=92.0, text="画出1号无人配送车的行驶路线。(6分）")
            for b in boxes]
    assert FG._split_side_text_figure(
        (5.0, 10.0, 230.0, 100.0), pure, src, np, k) is None, \
        "纯正文行也据此切框（q22/q23 的方格图就是这样被削掉的）"


def sliver_text_rows_are_trimmed_only_with_a_gap():
    """裁框上下沿只切到一行字的 1–2pt：行外先空出空白才收，贴着图的不动。"""
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0
    g = np.full((int(200 * k), int(200 * k)), 255, dtype=np.uint8)
    g[int(10 * k):int(25.5 * k), int(30 * k):int(170 * k)] = 30   # 上一行字
    g[int(30 * k):int(90 * k), int(30 * k):int(170 * k)] = 60     # 图
    g[int(96.5 * k):int(108 * k), int(30 * k):int(170 * k)] = 30  # 下一行字
    src = FG.PageSource(1, 200.0, 200.0, g, lambda rect, out: None)
    boxes = [{"x": 30.0, "y": 10.0, "w": 140.0, "h": 16.0,
              "text": "1.喷泉的西面是（ )，东面是（ )。"},
             {"x": 30.0, "y": 96.0, "w": 140.0, "h": 16.0,
              "text": "2.莲池在凉亭的（ )面，在假山的（ )面。"}]
    out = FG._trim_sliver_text_rows((20.0, 20.0, 180.0, 100.0), boxes, src, np, k)
    assert abs(out[1] - 26.5) < 0.6, f"上沿没收出半个字：{out}"
    assert abs(out[3] - 95.5) < 0.6, f"下沿没收出半个字：{out}"

    # 反例：图墨一直贴到下一行字（中间没有空白）→ 下沿不许收，否则会削掉图
    g2 = g.copy()
    g2[int(30 * k):int(96.5 * k), int(30 * k):int(170 * k)] = 60
    src2 = FG.PageSource(1, 200.0, 200.0, g2, lambda rect, out: None)
    out2 = FG._trim_sliver_text_rows((20.0, 20.0, 180.0, 100.0), boxes, src2, np, k)
    assert out2[3] == 100.0, f"图墨贴着字也把下沿收了：{out2}"

    # 起于框左沿之外的正文行：切得深一点（50% 行高）也要收
    # 真卷：综合实践单元(1) p1 第 5 题，下一题起手句 x=205.4、图框 x=206.5，
    # 被切 2.7/5.5pt；按 45% 判会漏，图底留一条黑边。
    g3 = g.copy()
    g3[int(30 * k):int(90 * k), int(30 * k):int(170 * k)] = 60
    g3[int(92.5 * k):int(108 * k), int(20 * k):int(190 * k)] = 30  # 行从框左沿外起
    src3 = FG.PageSource(1, 200.0, 200.0, g3, lambda rect, out: None)
    deep = [{"x": 18.0, "y": 92.0, "w": 172.0, "h": 16.0,
             "text": "5.小君想先参观书法馆。根据下面的路线图，他从大门进入后，"}]
    out3 = FG._trim_sliver_text_rows((20.0, 20.0, 180.0, 100.0), deep, src3, np, k)
    assert abs(out3[3] - 91.5) < 0.6, f"从框左沿外伸进来的半行没收：{out3}"

    # 反例：同样切 50%，但这行整行都在框里（图注）→ 仍按 45% 判，不许收
    inside = [{"x": 30.0, "y": 92.0, "w": 140.0, "h": 16.0,
               "text": "5.小君想先参观书法馆。根据下面的路线图，他从大门进入后，"}]
    out4 = FG._trim_sliver_text_rows((20.0, 20.0, 180.0, 100.0), inside, src3, np, k)
    assert out4[3] == 100.0, f"框内 50% 的标注也照收：{out4}"

    # 反例：从框左沿外伸进来，但图墨贴着字 → 不收（不能削图）
    g4 = g3.copy()
    g4[int(30 * k):int(92.5 * k), int(30 * k):int(170 * k)] = 60
    src4 = FG.PageSource(1, 200.0, 200.0, g4, lambda rect, out: None)
    out5 = FG._trim_sliver_text_rows((20.0, 20.0, 180.0, 100.0), deep, src4, np, k)
    assert out5[3] == 100.0, f"贴墨也把外伸行收了：{out5}"


def seal_strip_at_page_edge_is_clipped():
    """页边竖排密封线：同一列 ≥4 个 margin 单字 → 裁框右沿收到这列左边。

    真实卷（综合实践单元(1) p2 第 22/23 题）：裁框为了保住方格图右沿伸到
    363.7，把「…请勿…答」那列竖排字也裁了进来。用已丢弃的 margin 单字框
    反推左缘，比按“离页边多少 pt”硬切稳。
    """
    import app.extractor.figures as FG
    seal = [(392.0, 60.0, 397.0, 65.0), (392.0, 80.0, 397.0, 85.0),
            (392.0, 100.0, 397.0, 105.0), (392.0, 112.0, 397.0, 117.0)]
    out = FG._clip_seal_strip((50.0, 50.0, 400.0, 120.0), seal, 400.0)
    assert out == (50.0, 50.0, 391.0, 120.0), f"密封线没裁掉：{out}"
    # 反例①：只有三个框 → 不够成一列。真实卷 综合实践单元(1) p1 第 5 题：
    # 图右沿的「北 / 东 / 大门」正好三个，按 3 个算就会切掉「大门」的「门」。
    trio = [(392.0, 60.0, 397.0, 65.0), (393.0, 62.0, 398.0, 67.0),
            (392.0, 100.0, 397.0, 105.0)]
    assert FG._clip_seal_strip((50.0, 50.0, 400.0, 120.0), trio, 400.0) == \
        (50.0, 50.0, 400.0, 120.0), "三个图标签也当密封列"
    # 反例②：裁框伸过了字列左缘，但只压住字的 1/5（没真正盖住）→ 不动
    aside = [(385.0, 60.0, 390.0, 65.0), (385.0, 80.0, 390.0, 85.0),
             (385.0, 100.0, 390.0, 105.0), (385.0, 112.0, 390.0, 117.0)]
    assert FG._clip_seal_strip((50.0, 50.0, 386.0, 120.0), aside, 400.0) == \
        (50.0, 50.0, 386.0, 120.0), "没盖住也照切"
    # 反例③：这列小字在页面中间（正文注释）→ 不是页边密封线
    mid = [(200.0, 60.0, 205.0, 65.0), (200.0, 80.0, 205.0, 85.0),
           (200.0, 100.0, 205.0, 105.0), (200.0, 112.0, 205.0, 117.0)]
    assert FG._clip_seal_strip((50.0, 50.0, 400.0, 120.0), mid, 400.0) == \
        (50.0, 50.0, 400.0, 120.0), "正文里的一列小字也照切"
    # 反例④：切完不足 12pt → 宁可留着，不交一条窄条
    assert FG._clip_seal_strip((385.0, 50.0, 400.0, 120.0), seal, 400.0) == \
        (385.0, 50.0, 400.0, 120.0), "切完只剩窄条也照切"


def seal_column_accepts_real_glyph_sizes_and_rejects_scatter():
    """达标B 的密封字实测 6.5–13.7pt 宽：卡 10pt 会把整列滤到只剩 1 个框。
    反例是一列真正散开的图标签（各 3 个，凑不成一条线），以及真实卷
    综合实践单元(1) p1 右侧那串地图标签 —— 它们 x 挤成一列，但纵向最大
    空档 76pt（页高 287 的 26%），不是「密封线」而是散落的图注。"""
    import app.extractor.figures as FG
    wide = [(388.0, 20.0 + i * 18.0, 400.0, 32.0 + i * 18.0) for i in range(6)]
    assert len(FG._seal_column(wide, 400.0, 200.0)) == 6, "12pt 宽的密封字没被认成一列"
    out = FG._clip_seal_strip((50.0, 10.0, 402.0, 140.0), wide, 400.0)
    assert out == (50.0, 10.0, 387.0, 140.0), f"12pt 密封列没裁掉：{out}"
    scatter = ([(392.0, 10.0 + i * 20.0, 400.0, 22.0 + i * 20.0) for i in range(3)]
               + [(200.0, 10.0 + i * 20.0, 208.0, 22.0 + i * 20.0) for i in range(3)])
    assert FG._seal_column(scatter, 400.0) == [], "散开的图标签被凑成一列"
    assert FG._clip_seal_strip((50.0, 10.0, 402.0, 140.0), scatter, 400.0) == \
        (50.0, 10.0, 402.0, 140.0), "散开的图标签也照切"
    # 真密封列（达标B 实测）：8 个字、y 98–528、最大空档 62pt / 页高 634
    real = [(850.0, 98.0 + i * 61.5, 864.0, 110.0 + i * 61.5) for i in range(8)]
    assert len(FG._seal_column(real, 900.0, 634.0)) == 8, "真密封列被纵向判据筛掉"
    # 反例：综合实践单元(1) p1 右侧地图标签（x 327–355，y 37–227，最大空档 76pt）
    labels = [(331.0, 37.0, 342.0, 43.0), (332.0, 54.5, 343.0, 60.0),
              (344.0, 128.2, 354.0, 133.7), (329.0, 138.5, 339.0, 142.6),
              (346.0, 214.8, 351.0, 220.6), (327.0, 217.9, 343.0, 224.9),
              (345.6, 218.9, 355.4, 225.1), (338.0, 226.6, 349.0, 232.8)]
    assert FG._seal_column(labels, 370.0, 287.0) == [], "散落的地图标签被当成密封列"


def seal_dashed_rule_is_found_and_cut():
    """密封字左边那条页顶到页底的竖虚线：按逐像素列认，切在它左边。

    反例：实线框边（覆盖率 100%）、正文栏（行距 30pt 的大空隙）、
    只有一小段的短线 —— 都不许认成密封虚线。
    """
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    def page(draw):
        g = np.full((int(200 * k), int(200 * k)), 255, dtype=np.uint8)
        draw(g)
        return FG.PageSource(1, 200.0, 200.0, g, lambda rect, out: None)

    def dashed(g, x=182, y0=10, y1=190, on=4, off=3):
        xa, xb = int(x * k), int((x + 1.0) * k)
        y = y0
        while y < y1:
            g[int(y * k):int(min(y + on, y1) * k), xa:max(xa + 1, xb)] = 40
            y += on + off

    src = page(dashed)
    rx = FG._seal_rule_x((20.0, 10.0, 200.0, 140.0), src, 186.0, k)
    assert rx is not None and abs(rx - 182.0) < 1.2, f"竖虚线没找到：{rx}"
    seal = [(186.0, 20.0 + i * 18.0, 198.0, 32.0 + i * 18.0) for i in range(6)]
    out = FG._clip_seal_strip((20.0, 10.0, 200.0, 140.0), seal, 200.0, src=src, k=k)
    assert abs(out[2] - 181.0) < 1.2, f"没切在虚线左边：{out}"
    # 压在虚线上、左移 11pt 的密封单字：要整字切掉（达标B 的「线/答」）
    stray = [(170.0, 50.0, 181.0, 62.0)]
    out2 = FG._clip_seal_strip((20.0, 10.0, 200.0, 140.0), seal + stray, 200.0,
                               src=src, k=k)
    assert out2[2] <= 169.5, f"压在虚线左边的密封单字没切掉：{out2}"
    # 反例①：实线（覆盖率 100%）
    src_solid = page(lambda g: g.__setitem__(
        (slice(int(10 * k), int(190 * k)), slice(int(182 * k), int(183 * k))), 40))
    assert FG._seal_rule_x((20.0, 10.0, 200.0, 140.0), src_solid, 186.0, k) is None, \
        "实线框边被当成密封虚线"
    # 反例②：正文栏（一行行字，行距 30pt 的大空隙）
    def body(g):
        for y in (12, 42, 72, 102, 132, 162):
            g[int(y * k):int((y + 12) * k), int(182 * k):int(183 * k)] = 40
    assert FG._seal_rule_x((20.0, 10.0, 200.0, 140.0), page(body), 186.0, k) is None, \
        "正文栏被当成密封虚线"
    # 反例③：只有 20pt 长的一小段虚线
    src_short = page(lambda g: dashed(g, y0=90, y1=110))
    assert FG._seal_rule_x((20.0, 10.0, 200.0, 140.0), src_short, 186.0, k) is None, \
        "短线被当成贯通密封虚线"


def footer_is_never_absorbed_as_a_bottom_label_row():
    """达标B 两页并排的页脚："第 3 页   共 4 页   200" 会被 _looks_like_label_row
    认成三段短标签（真实踩过：裁框往下吃到 623pt）。家具行必须先被挡住；
    反例用真图注 "？个  ?根  ？元  ?根"：它必须仍然被吸进来。"""
    import app.extractor.figures as FG
    rect = (20.0, 20.0, 180.0, 100.0)
    footer = [{"x": 20.0, "y": 96.0, "w": 140.0, "h": 12.0,
               "text": "第 3 页   共 4 页   200"}]
    assert FG._extend_bottom_label_row(rect, footer) == rect, "页脚被当图注吸进裁框"
    label = [{"x": 20.0, "y": 96.0, "w": 140.0, "h": 12.0,
              "text": "？个  ?根  ？元  ?根"}]
    out = FG._extend_bottom_label_row(rect, label)
    assert out[3] == 110.0, f"真图注没被吸进来：{out}"


def two_token_label_row_is_recognised_and_extended():
    """只有两段的标签行（③ ④ 被 OCR 读成 "3    4"）也必须认出来。

    真实卷 P1 第 2 页第 7 题：图下沿 y=489.0 正好切在两个小图的序号行
    （y=483.8–498）中间，裁出来的图底部 ③ ④ 只剩上半截（独立复测 P1-04）。
    旧判据要求 ≥3 段，两段永远过不了；这条只放开"两段且每段都是单个
    序号/字母"的极窄形状，题干的两段行（"4 × 5 =   20"）仍必须拒绝。
    """
    import app.extractor.figures as FG
    rect = (20.0, 20.0, 180.0, 100.0)
    for text in ("3            4", "①      ②", "A      B", "1   2"):
        assert FG._looks_like_label_row(text), f"两段序号行没被认成标签：{text!r}"
        rows = [{"x": 20.0, "y": 96.0, "w": 140.0, "h": 12.0, "text": text}]
        out = FG._extend_bottom_label_row(rect, rows)
        assert out[3] == 110.0, f"两段序号行没把下沿放下去：{text!r} → {out}"
    for text in ("4 × 5 =       20", "大门在        东面", "（1）      （2）"):
        assert not FG._looks_like_label_row(text), f"题干两段行被误认成标签：{text!r}"


def side_split_stem_cleanup_keeps_the_body():
    """图文同排收窄后：题干里只摘行首图注，正文一个字都不许少。"""
    import app.extractor.figures as FG
    boxes = [
        {"x": 40.0, "y": 20.0, "w": 180.0, "h": 8.0,
         "text": "东北           1.喷泉的西面是（     )，东面"},
        {"x": 40.0, "y": 40.0, "w": 180.0, "h": 8.0,
         "text": "喷泉      游乐场            是（     )。(4分)"},
        {"x": 40.0, "y": 60.0, "w": 180.0, "h": 8.0,
         "text": "莲池      假山            2.莲池在凉亭的（     )面，在"},
        {"x": 40.0, "y": 80.0, "w": 180.0, "h": 8.0,
         "text": "凉亭              假山的（     )面。(4分)"},
    ]
    qs = [{"q_no": 1, "text":
           "东北         1.喷泉的西面是（    )，东面是（    )。(4分) "
           "喷泉      游乐场            是（    )。(4分) "
           "莲池      假山            2.莲池在凉亭的（    )面，在 "
           "凉亭              假山的（    )面。(4分)"}]
    span = {"q_index": 0, "page": 1, "col": 0, "y0": 10.0, "y1": 100.0,
            "x0": 0.0, "x1": 260.0, "text_boxes": boxes}
    got = {0: [{"rect": [5.0, 10.0, 129.6, 100.0], "side_split": True}]}
    n = FG.strip_text_inside_figures(qs, [span], got)
    t = str(qs[0]["text"])
    assert n == 4, f"只摘了 {n} 行的图注（应为 4 行）：{t!r}"
    assert "东北" not in t, f"行首图注没摘：{t!r}"
    assert "1.喷泉的西面" in t and "2.莲池在凉亭的" in t and "假山的" in t, \
        f"题干正文被删残：{t!r}"


def side_split_is_wired_into_find_figures():
    """接线检查：find_figures 真的调用图文同排切分、输出 side_split，并跳过接宽。

    图表几何由上一条直接量；这条只验接线 —— 把切分换成记账的壳子，
    看它有没有被叫到、标志有没有传到输出、右侧接宽有没有被跳过。
    """
    import app.extractor.figures as FG
    src = _src_from_bands(200, 200, [(20, 60, 120, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 200.0,
              "text_boxes": [{"x": 20, "y": 55, "w": 130, "h": 6,
                              "text": "1.看图填空。"}]}]
    real_split = FG._split_side_text_figure
    real_ext = FG._extend_edge_ink
    ext_calls = []

    def spy_split(rect, boxes, src_, np_, k_):
        return (rect[0], rect[1], rect[0] + 80.0, rect[3])

    def spy_ext(*a, **kw):
        ext_calls.append(a[0])
        return a[0]

    FG._split_side_text_figure = spy_split
    FG._extend_edge_ink = spy_ext
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._split_side_text_figure = real_split
        FG._extend_edge_ink = real_ext
    imgs = got.get(0) or []
    assert imgs, f"夹具没裁出图，接线测不到：{rep}"
    im = imgs[0]
    assert im.get("side_split"), f"切分标志没传到输出：{im}"
    assert im["rect"][2] < 110.0, f"右沿没用收窄后的框：{im['rect']}"
    assert not ext_calls, f"收窄过后又往右接宽了（题干首字会被裁进来）：{ext_calls}"
    assert any(x.get("why") == "side-text-split" for x in rep), \
        f"报告里没留下 side-text-split：{rep}"


def final_edge_trim_is_wired_into_find_figures():
    """接线检查：最后那刀“上下沿半个字 / 密封线”真的跑在 find_figures 里。"""
    import app.extractor.figures as FG
    src = _src_from_bands(200, 200, [(20, 60, 120, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 200.0,
              "text_boxes": [{"x": 20, "y": 55, "w": 130, "h": 6,
                              "text": "1.看图填空。"}]}]
    real = FG._trim_sliver_text_rows
    calls = []

    def spy(rect, boxes, src_, np_, k_):
        calls.append(tuple(rect))
        return (rect[0], rect[1], rect[2] - 15.0, rect[3] - 5.0)

    FG._trim_sliver_text_rows = spy
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._trim_sliver_text_rows = real
    imgs = got.get(0) or []
    assert calls and imgs, f"最后这刀根本没跑：calls={calls}, rep={rep}"
    assert abs(imgs[0]["rect"][2] - (calls[0][2] - 15.0)) < 1.0, \
        f"修边结果没落到输出框：{imgs[0]['rect']} vs {calls[0]}"
    assert any(x.get("why") == "edge-trim" for x in rep), \
        f"报告里没留下 edge-trim：{rep}"


def text_edge_drop_is_wired_into_find_figures():
    """接线检查：最终形状复检也会丢"窄条字尾"。

    候选阶段框还宽 31.9pt（含页边空白），修边后只剩 14pt，两层判据必须都在；
    这里让候选宽 40pt、修边后宽 10pt，只有最终复检能抓到。
    """
    import app.extractor.figures as FG
    src = _src_from_bands(400, 200, [(150, 60, 190, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 400.0,
              "text_boxes": [{"x": 20, "y": 45, "w": 130, "h": 6,
                              "text": "1.看图填空。"}]}]
    real_trim = FG._trim_sliver_text_rows
    real_edge = FG._is_text_edge_fragment
    seen = []

    def trim(rect, boxes, src_, np_, k_):
        return (rect[0], rect[1], rect[2] - 40.0, rect[3])

    def edge(rect, boxes):
        seen.append(tuple(rect))
        return (rect[2] - rect[0]) < 20.0

    FG._trim_sliver_text_rows = trim
    FG._is_text_edge_fragment = edge
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._trim_sliver_text_rows = real_trim
        FG._is_text_edge_fragment = real_edge
    imgs = got.get(0) or []
    assert seen, f"最终复检根本没跑：rep={rep}"
    assert not imgs, f"修边后才露出的窄条字尾留成了图：{imgs}"
    assert any(x.get("why") == "text-edge" for x in rep), \
        f"报告里没留下 text-edge：{rep}"


def seal_strip_clip_is_wired_into_find_figures():
    """接线检查（真函数）：页边密封字列必须在找到图之后被裁掉。

    候选阶段可能已经切过一次，但后面的修边/缝合会把右沿重新推回密封字上
    （真实卷 q22 就是这样：候选切完，接宽又长回去）。这里让修边把右沿推回
    398（盖住 x 392–397 的密封字），只有【最终那刀】还能把它收回 391 ——
    把最终裁切关掉，右沿会停在 398，测试必须变红。
    """
    import app.extractor.figures as FG
    src = _src_from_bands(400, 200, [(30, 60, 398, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 400.0,
              "text_boxes": [{"x": 20, "y": 45, "w": 180, "h": 6,
                              "text": "1.看图填空。"}]}]
    noise = [{"x": 392.0, "y": y, "w": 5.0, "h": 5.0, "page": 1}
             for y in (30.0, 60.0, 90.0, 120.0, 150.0, 180.0)]
    real_trim = FG._trim_sliver_text_rows

    def widen(rect, boxes, src_, np_, k_):
        return (rect[0], rect[1], min(398.0, rect[2] + 12.0), rect[3])

    FG._trim_sliver_text_rows = widen
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep, noise=noise)
    finally:
        FG._trim_sliver_text_rows = real_trim
    imgs = got.get(0) or []
    assert imgs, f"夹具没裁出图：{rep}"
    assert 380.0 <= imgs[0]["rect"][2] <= 391.5, \
        f"右沿没收在密封字左边：{imgs[0]['rect']}"
    assert any(x.get("why") in ("seal-trim", "edge-trim") for x in rep), \
        f"报告里没留下裁密封线的记录：{rep}"


def _blank_page_source(size_pt=200):
    """纯白页：只量几何，不让"接缝上有没有墨"混进这几条判据。"""
    import numpy as np
    from app.extractor.figures import PageSource, DPI_PROBE
    k = DPI_PROBE / 72.0
    n = int(size_pt * k)
    g = np.full((n, n), 255, dtype=np.uint8)
    return PageSource(1, size_pt, size_pt, g, lambda rect, out: None)


def figure_split_along_the_same_left_edge_is_stitched():
    """题界斜穿共享地图：上下两块同左沿、纵向交叠 → 缝回一张。

    真实卷（综合实践单元(1) p2 第三大题）：84×50 的公园地图被第 1、2 题的分界
    切成 84×39 + 44×17 两块。上半块被 text-cut 当成"切断文字"丢掉，第 1 题
    一张图都没有，第 2 题只剩一小条；常规缝合又因"两半宽窄差一倍"拒绝。
    """
    import app.extractor.figures as FG
    src = _blank_page_source()

    def cand(qi, rect):
        return {"q_index": qi, "page": 1, "col": 0, "src": src, "rect": rect,
                "w_pt": rect[2] - rect[0], "h_pt": rect[3] - rect[1],
                "tbs": [], "band": [0, 0, 200, 200]}

    rep = []
    out = FG._stitch_across_questions(
        [cand(0, (10.0, 10.0, 94.0, 49.0)), cand(1, (10.0, 45.0, 54.0, 62.0))], rep)
    assert len(out) == 1, f"同左沿的上下两块没缝回一张：{[c['rect'] for c in out]}"
    assert out[0]["q_index"] == 0, "缝合后应挂到靠前那道题"
    assert [round(v, 1) for v in out[0]["rect"]] == [10.0, 10.0, 94.0, 62.0], out[0]["rect"]
    assert rep and rep[-1]["why"] == "side-shared", rep

    # 正例②：上块只是上一题区间末尾的一条，绝大部分图身落在下一题区间 ——
    # 缝完必须改挂下一题。真实卷（第三单元练习题 p4 第 4 题）：4×4 圆点阵的
    # 第一行落在上一题区间里，缝完挂在上一题，下一题"在图上圈一圈"却没有图。
    def cand_band(qi, rect, band):
        d = cand(qi, rect)
        d["band"] = band
        return d

    out_band = FG._stitch_across_questions([
        cand_band(0, (10.0, 140.0, 94.0, 155.0), [0, 0, 200, 155]),
        cand_band(1, (10.0, 148.0, 94.0, 250.0), [0, 155, 200, 300]),
    ])
    assert len(out_band) == 1, f"圆点阵没有缝回一张：{out_band}"
    assert out_band[0]["q_index"] == 1, "缝完仍挂在上一题（下一题没图）"
    assert [round(v, 1) for v in out_band[0]["rect"]] == [10.0, 140.0, 94.0, 250.0], \
        out_band[0]["rect"]
    # 反例⑤（改挂）：两半在自己区间里一样多 → 仍挂靠前那道（既有行为）
    out_eq = FG._stitch_across_questions([
        cand_band(0, (10.0, 140.0, 94.0, 155.0), [0, 0, 200, 195]),
        cand_band(1, (10.0, 148.0, 94.0, 250.0), [0, 195, 200, 300]),
    ])
    assert out_eq[0]["q_index"] == 0, "区间一样多时改挂了（与旧行为不一致）"

    # 正例③：上块底沿正好压在自己区间下沿，下块和它隔了 12.4pt（>常规 2pt）——
    # 仍是同一张地图的下半截。真实卷（综合实践单元(1) p2 第 1 题公园地图）。
    out_gap = FG._stitch_across_questions([
        cand_band(0, (64.0, 70.4, 249.0, 152.8), [0, 0, 300, 152.8]),
        cand_band(1, (64.0, 165.2, 149.9, 179.4), [0, 152.8, 300, 300]),
    ])
    assert len(out_gap) == 1, f"地铁图上下的 12.4pt 缝没补：{out_gap}"
    assert [round(v, 1) for v in out_gap[0]["rect"]] == [64.0, 70.4, 249.0, 179.4], \
        out_gap[0]["rect"]

    # 反例⑤b：缝宽 20pt（>15pt）→ 两张图，不缝
    out_gap2 = FG._stitch_across_questions([
        cand_band(0, (64.0, 70.4, 249.0, 152.8), [0, 0, 300, 152.8]),
        cand_band(1, (64.0, 172.8, 149.9, 187.0), [0, 152.8, 300, 300]),
    ])
    assert len(out_gap2) == 2, f"缝宽 20pt 的两张图被缝成一张：{out_gap2}"
    # 反例⑤c：下块高 40pt（>30pt 薄片档）→ 是一张完整的图，不是缺的下半截
    out_gap3 = FG._stitch_across_questions([
        cand_band(0, (64.0, 70.4, 249.0, 152.8), [0, 0, 300, 152.8]),
        cand_band(1, (64.0, 165.2, 149.9, 205.2), [0, 152.8, 300, 300]),
    ])
    assert len(out_gap3) == 2, f"40pt 高的独立图被缝进地图：{out_gap3}"
    # 反例⑤d：上块底沿离自己区间下沿还有 10pt（没被题界切开）→ 不缝
    out_gap4 = FG._stitch_across_questions([
        cand_band(0, (64.0, 70.4, 249.0, 152.8), [0, 0, 300, 162.8]),
        cand_band(1, (64.0, 165.2, 149.9, 179.4), [0, 162.8, 300, 300]),
    ])
    assert len(out_gap4) == 2, f"没贴区间下沿的两块仍被缝：{out_gap4}"

    # 反例①：左沿差 10pt（真·两张图）。常规分支也会因宽窄差一倍拒绝，
    # 只有把"同左沿"这条删掉才会缝 —— 变异闸门要抓的就是这一条。
    out2 = FG._stitch_across_questions(
        [cand(0, (10.0, 10.0, 94.0, 49.0)), cand(1, (20.0, 45.0, 64.0, 80.0))])
    assert len(out2) == 2, f"左沿差 10pt 的两块被缝成一张：{[c['rect'] for c in out2]}"

    # 反例②：纵向只贴 1pt 边、几乎不交叠（两半高度都超过薄片档，不走薄片缝）。
    out3 = FG._stitch_across_questions(
        [cand(0, (10.0, 10.0, 94.0, 49.0)), cand(1, (10.0, 48.0, 94.0, 90.0))])
    assert len(out3) == 2, f"只贴 1pt 边的两张图被缝成一张：{[c['rect'] for c in out3]}"

    # 反例③：同一道题的碎片由补洞合并管，这里不许动。
    out4 = FG._stitch_across_questions(
        [cand(0, (10.0, 10.0, 94.0, 49.0)), cand(0, (10.0, 45.0, 54.0, 62.0))])
    assert len(out4) == 2, "同题碎片被跨题缝合吞了"

    # 反例④：缝合后超过尺寸上限（不是一张图，是整页）。
    out5 = FG._stitch_across_questions(
        [cand(0, (10.0, 10.0, 94.0, 49.0)), cand(1, (10.0, 45.0, 54.0, 280.0))])
    assert len(out5) == 2, "超过尺寸上限的两块仍被缝成一张"

    # 反例⑤：后一块太窄（<前一块 35%），是图注/小图标，不是地图缺的下半块。
    out6 = FG._stitch_across_questions(
        [cand(0, (10.0, 10.0, 94.0, 49.0)), cand(1, (10.0, 45.0, 24.0, 62.0))])
    assert len(out6) == 2, f"过窄的下半块仍被缝进地图：{[c['rect'] for c in out6]}"


def long_text_line_between_overlapping_blocks_blocks_the_stitch():
    """上下只叠几 pt、叠缝里夹着一整行正文 → 不是同一张图，不许缝。

    真实卷（P5 Q13/Q14）：Q13 的窗户 [130.2,113.1,240.6,146.7] 与 Q14 的社团
    统计图 [130.9,141.2,241.3,217.7] 在纵向上叠 5.5pt，叠缝里正是 Q14 的
    题干行（158pt 宽）。缝了以后 Q14 的图里印着上一题的窗户。
    被题界劈开的棋盘中间只有"22."这种短题号，所以判据是"叠缝里有长正文行"。
    """
    import app.extractor.figures as FG
    src = _blank_page_source(300)

    def cand(qi, rect, tbs):
        return {"q_index": qi, "page": 1, "col": 0, "src": src, "rect": rect,
                "w_pt": rect[2] - rect[0], "h_pt": rect[3] - rect[1],
                "tbs": tbs, "band": [0, 0, 300, 300]}

    stem = {"x": 40.0, "y": 140.0, "w": 158.0, "h": 7.0,
            "text": "14.下面是小星调查本班同学最喜欢的社团活动情况。"}
    got = FG._stitch_across_questions([
        cand(0, (130.2, 113.1, 240.6, 146.7), []),
        cand(1, (130.9, 141.2, 241.3, 217.7), [stem])])
    assert len(got) == 2, f"叠缝里夹着题干行的两块被缝成一张：{[c['rect'] for c in got]}"

    # 阳性对照：同样的几何，叠缝里只有短题号 "22." → 仍要缝回一张。
    short = {"x": 150.0, "y": 142.0, "w": 20.0, "h": 6.0, "text": "22."}
    got2 = FG._stitch_across_questions([
        cand(0, (130.2, 113.1, 240.6, 146.7), []),
        cand(1, (130.9, 141.2, 241.3, 217.7), [short])])
    assert len(got2) == 1, f"只有短题号的共享图没缝回一张：{[c['rect'] for c in got2]}"


def side_by_side_questions_share_a_look_at_the_picture_band():
    """左右并排的两问共用一条看图区间：兜底截图要沿中间空白竖缝切开。

    真实卷（P1 Q17/Q18）：Q17 的区间只到题干行，图全落在 Q18 的区间里；
    整段兜底会把 Q18 一起裁进来。判据是"中线附近有通高空白竖缝、两半都有墨"。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG

    assert FG._span_mentions_qno(
        {"text_boxes": [{"text": "17.看图填空。                    18.看图填空。"}]}, 18)
    assert not FG._span_mentions_qno(
        {"text_boxes": [{"text": "18.看图填空。                      17.看图填空。"}]}, 19)
    assert not FG._span_mentions_qno({}, 18)

    p = os.path.join(OUT, "side_split.png")
    im = Image.new("L", (934, 446), 255)
    d = ImageDraw.Draw(im)
    d.rectangle((30, 40, 420, 380), fill=0)        # 左问的树状图
    d.rectangle((500, 40, 900, 380), fill=0)       # 右问的统计图
    im.save(p)
    px = FG._fallback_side_split_px(p)
    assert px is not None and 425 <= px <= 505, f"没找到中线空白竖缝：{px}"

    # 反例①：整张大图（中间没有通高空白）→ 不许切。
    p2 = os.path.join(OUT, "side_whole.png")
    im2 = Image.new("L", (934, 446), 255)
    d2 = ImageDraw.Draw(im2)
    d2.rectangle((30, 40, 900, 380), fill=0)
    im2.save(p2)
    assert FG._fallback_side_split_px(p2) is None, "中间有贯穿墨的大图被切开了"

    # 反例②：一边几乎没有墨（空白页边）→ 不算并排两问。
    p3 = os.path.join(OUT, "side_empty.png")
    im3 = Image.new("L", (934, 446), 255)
    d3 = ImageDraw.Draw(im3)
    d3.rectangle((30, 40, 420, 380), fill=0)
    im3.save(p3)
    assert FG._fallback_side_split_px(p3) is None, "空白页边被当成了另一问"


def side_split_fallback_is_wired_into_attach_span_fallbacks():
    """接线检查：看图大题左右并排时，兜底截图真的按中线切开了。

    只测 _fallback_side_split_px 不够 —— P1 Q17 的毛病是"没走进切分那一步"，
    整段兜底把 Q18 一起印进来。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)
    page = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(page)
    d.rectangle((int(30 * k), int(80 * k), int(240 * k), int(370 * k)), fill=0)
    d.rectangle((int(320 * k), int(80 * k), int(480 * k), int(370 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    sec = "六 看图列式计算"
    spans = [
        {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
         "y0": 100.0, "y1": 133.0,
         "text_boxes": [{"x": 30, "y": 105, "w": 400, "h": 8,
                         "text": "17.松树种了多少棵？        18.科技书有多少本？"}]},
        {"q_index": 1, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
         "y0": 132.0, "y1": 380.0, "text_boxes": []},
    ]
    qs = [{"q_no": 17, "text": "17.看图列式。", "section": sec, "images": []},
          {"q_no": 18, "text": "18.看图列式。", "section": sec,
           "images": [{"name": "x.png"}]}]
    out_dir = os.path.join(OUT, "side_fallback")
    shutil.rmtree(out_dir, ignore_errors=True)
    n = FG.attach_span_fallbacks(qs, {1: src}, spans, out_dir)
    assert n == 1, f"兜底图数量不对：{n}"
    p = os.path.join(out_dir, "p1_q0_span.png")
    im = Image.open(p)
    assert im.width < int(W * 0.75), f"兜底图没按中线切开：{im.size}"
    left = np.asarray(im.convert("L")) < 160
    assert int(left.sum()) > 200, "切完的图里没有墨"
    # 左块右沿在 240pt（裁框从 16pt 起）——再往右必须全是空白，右问的图不许留下
    edge = int((240.0 - 16.0) * k) + 2
    assert int(left[:, edge:].sum()) == 0, "右半还留着下一题的图"


def calc_span_fallback_replaces_fragment_images():
    """算式大题只裁到一小块：整题截图必须替换碎片（含四个反例）。

    P2 Q1 只留下 3/8-2/8、Q2 丢了右列 ③8)6115 / ⑥7)3261；碎片图与读崩的
    数字一起印，孩子做不了。判据：
      · 碎片（远小于区间）→ 整题截图 + 文字清空；
      · 已覆盖大半区间 → 不动（正常裁图不许被整题截图顶掉）；
      · 非算式题带小图 → 不动（不许把普通配图换成含题干的大图）；
      · "哪幅图"题没图 → 整题截图 + 文字清空（P5 Q23 的 1/4 被读成 4）。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)
    page = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(page)
    d.rectangle((int(30 * k), int(100 * k), int(470 * k), int(370 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 100.0, "y1": 380.0, "text_boxes": []}
    calc_sec = "四、计算(30 分)"
    text = "口算(6 分) 2 28X416X7200X 6        + 4      4 99 ÷ 3"

    # ① 碎片图：宽 50pt / 区间 460pt → 必须换成整题截图，文字清空。
    q_frag = {"q_no": 1, "section": calc_sec, "text": text,
              "images": [{"name": "frag.png", "page": 1,
                          "rect": [50.0, 120.0, 100.0, 180.0],
                          "band": [0.0, 0.0, 374.4, 272.9]}]}
    out1 = os.path.join(OUT, "calc_frag")
    shutil.rmtree(out1, ignore_errors=True)
    n1 = FG.attach_span_fallbacks([q_frag], {1: src}, [dict(span)], out1)
    assert n1 == 1, f"碎片图没有触发整题兜底：{n1}"
    imgs = q_frag.get("images") or []
    assert len(imgs) == 1 and imgs[0].get("graphic") is True, f"碎片没有被整题图替换：{imgs}"
    assert imgs[0].get("graphic_kind") == "calc-span", imgs[0].get("graphic_kind")
    assert q_frag["text"] == "", "整题截图已含算式，读崩的文字必须清空"
    p1 = os.path.join(out1, "p1_q0_span.png")
    assert os.path.exists(p1) and os.path.getsize(p1) > 500, "整题截图没落盘"

    # ② 反例：裁块已覆盖大半区间（宽 450/460、高 270/280）→ 原图不动。
    full = {"name": "full.png", "page": 1,
            "rect": [25.0, 105.0, 475.0, 375.0],
            "band": [25.0, 105.0, 475.0, 375.0]}
    q_full = {"q_no": 2, "section": calc_sec, "text": text, "images": [full]}
    out2 = os.path.join(OUT, "calc_full")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks([q_full], {1: src}, [dict(span)], out2)
    assert n2 == 0, f"完整裁图被整题截图顶掉了：{n2}"
    assert q_full["images"] == [full] and q_full["text"] == text, "完整裁图被改动了"
    assert not os.path.exists(os.path.join(out2, "p1_q0_span.png")), "不该生成兜底图"

    # ③ 反例：非算式题带一张小图 → 不换成含题干的大图。
    q_other = {"q_no": 3, "section": "六、解决问题(25 分)",
               "text": "一个长方形花园，长27米，宽比长少4米，篱笆长多少米？",
               "images": [{"name": "small.png", "page": 1,
                           "rect": [50.0, 120.0, 100.0, 180.0],
                           "band": [50.0, 120.0, 100.0, 180.0]}]}
    out3 = os.path.join(OUT, "calc_other")
    shutil.rmtree(out3, ignore_errors=True)
    n3 = FG.attach_span_fallbacks([q_other], {1: src}, [dict(span)], out3)
    assert n3 == 0 and q_other["images"][0]["name"] == "small.png", "普通配图被误换"

    # ④ "哪幅图"题没图：整题截图 + 文字清空（P5 Q23）。
    q_which = {"q_no": 23, "section": "五、解决问题(共5个小题)",
               "text": ("某小学2023年一年级新生有420人，比2022年增加了4 人。"
                        "(1) 下面哪幅图正确表达了题目的意思？在相应的括号里画√。"
                        "1、 2022 年 2022年 2022年 2023年 420人 2023年 420人 C"),
               "images": []}
    out4 = os.path.join(OUT, "calc_which")
    shutil.rmtree(out4, ignore_errors=True)
    n4 = FG.attach_span_fallbacks([q_which], {1: src}, [dict(span)], out4)
    assert n4 == 1, f"哪幅图题没有兜底：{n4}"
    assert q_which.get("images") and q_which["images"][0].get("graphic") is True
    assert q_which["images"][0].get("graphic_kind") == "span-fallback"
    assert q_which["text"] == "", "哪幅图题的零散标签必须清空，不能与正确原图矛盾"


def lost_box_fill_question_gets_whole_span():
    """方框被 OCR 吞掉的比较题：整题原图必须替掉碎片（含三个反例）。

    P2 填空 Q8 源卷「在□里填上“>”“<”或“=”，①23×0□23+0 ②32×2□76…」，
    RapidOCR 把 □ 全吞了（放大 2/3/4 倍同样复现），文字变成
    「在里填上… ①23× 023+0 ②32×276」；成品只裁到 ⑤⑥ 两张小图。
    ② 已读成另一道乘法，学生没有填符号的位置 → P1。
    判据：
      · 题干丢了方框 + 现有图没盖住整题 → 整题截图 + 文字清空；
      · 现有图已覆盖大半区间 → 不动（完整配图不许被大图顶掉）；
      · 原文带 □ 的完整填写题 → 不触发（别把好题换成大图）。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)
    page = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(page)
    d.rectangle((int(30 * k), int(100 * k), int(470 * k), int(370 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 100.0, "y1": 380.0, "text_boxes": []}
    text = ("在里填上“>”、“<”或“=” ①23× 023+0 ②32×276 "
            "③67 厘米口7 分米 ④989克口1千克")
    small = {"name": "p1_q0_1.png", "page": 1,
             "rect": [50.0, 300.0, 100.0, 330.0],
             "band": [50.0, 300.0, 100.0, 330.0]}
    q = {"q_no": 8, "section": "一、填空(20 分，每空 1 分)", "text": text,
         "source_lines": ["8.在里填上“>”、“<”或“=”"], "images": [dict(small)]}
    out = os.path.join(OUT, "lost_box")
    shutil.rmtree(out, ignore_errors=True)
    n = FG.attach_span_fallbacks([q], {1: src}, [dict(span)], out)
    assert n == 1, f"方框被吞的题没有整题兜底：{n}"
    imgs = q.get("images") or []
    assert len(imgs) == 1 and imgs[0].get("graphic") is True, f"碎片没被整题图替换：{imgs}"
    assert imgs[0].get("graphic_kind") == "span-fallback", imgs[0]
    assert imgs[0].get("whole_question") is True, \
        f"单 span 整题图没标 whole_question（导出会重复印残句）：{imgs[0]}"
    assert q["text"] == "", "整题原图已含比较项，读崩的文字必须清空"
    assert os.path.exists(os.path.join(out, "p1_q0_span.png")), "整题截图没落盘"

    # 反例①：现有图已覆盖大半区间 → 不动（正常完整配图不许被大图顶掉）。
    cover = {"name": "cover.png", "page": 1,
             "rect": [20.0, 100.0, 480.0, 380.0],
             "band": [20.0, 100.0, 480.0, 380.0]}
    q2 = {"q_no": 9, "section": "一、填空(20 分，每空 1 分)", "text": text,
          "source_lines": ["在里填上“>”、“<”或“=”"], "images": [cover]}
    out2 = os.path.join(OUT, "lost_box_cover")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks([q2], {1: src}, [dict(span)], out2)
    assert n2 == 0, f"已覆盖整题的配图被误换：{n2}"
    assert q2["text"] == text and q2["images"] == [cover], "完整题被改动了"

    # 反例②：原文带 □（方框没丢）→ 不触发，文字与小图都保留。
    q3 = {"q_no": 10, "section": "一、填空(20 分，每空 1 分)",
          "text": "在□里填上“>”、“<”或“=”，请把答案写在括号里。",
          "source_lines": ["10.在□里填上“>”、“<”或“=”"], "images": [dict(small)]}
    out3 = os.path.join(OUT, "lost_box_intact")
    shutil.rmtree(out3, ignore_errors=True)
    n3 = FG.attach_span_fallbacks([q3], {1: src}, [dict(span)], out3)
    assert n3 == 0, f"方框完整的题被误换成大图：{n3}"
    assert q3["text"].startswith("在□里填上") and q3["images"][0]["name"] == small["name"]


def calc_span_drops_section_heading_and_footer():
    """算式整题截图：切掉重复的大题标题、页脚和半页空白（含一个反例）。

    P5 实测：Q17/Q19 的截图把"三、计算题（共2道小题）"又印了一遍；Q19/Q20
    还把页脚"六年级数学第5页共8页"和半页空白裁进来。页脚在隔壁栏，
    本题 span 的 text_boxes 里没有它 —— 只能按"本题最后一行的下沿"收口。
    反例：看图题的图可能延伸到文字下面，绝不许按文字行收口。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    page = Image.new("L", (int(W_PT * k), int(H_PT * k)), 255)
    d = ImageDraw.Draw(page)
    # 题行要够"花"：只有一条实心横条的 PNG 压缩后 <500 字节，会被落盘闸门
    # （图太小当废图）拦掉，测不到截框逻辑。
    for i in range(10):
        x = 35 + i * 22
        d.rectangle((int(x * k), int(100 * k), int((x + 12) * k), int(116 * k)), fill=0)
        d.rectangle((int((x + 2) * k), int(92 * k), int((x + 10) * k), int(99 * k)), fill=0)
    # 斜线/细线让 PNG 有足够熵（纯白底 + 几个方块压完只有几百字节）
    for i in range(14):
        d.line((int((35 + i * 15) * k), int(98 * k),
                int((80 + i * 12) * k), int(126 * k)), fill=0, width=1)
    d.rectangle((int(35 * k), int(120 * k), int(250 * k), int(126 * k)), outline=0, width=1)
    d.rectangle((int(300 * k), int(370 * k), int(500 * k), int(380 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    boxes = [
        {"x": 30, "y": 80, "w": 200, "h": 10, "text": "四、解方程（共2道小题）"},
        {"x": 30, "y": 98, "w": 200, "h": 10, "text": "19. 15%x=75"},
        {"x": 300, "y": 370, "w": 200, "h": 10, "text": "六年级数学第5页共8页"},
    ]
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 76.0, "y1": 380.0, "text_boxes": list(boxes)}
    q = {"q_no": 19, "section": "四、解方程（共2道小题）",
         "text": "15%x=75", "images": []}
    out1 = os.path.join(OUT, "calc_compact")
    shutil.rmtree(out1, ignore_errors=True)
    n = FG.attach_span_fallbacks([q], {1: src}, [span], out1)
    assert n == 1, f"算式题没有兜底：{n}"
    rect = q["images"][0]["rect"]
    assert rect[1] >= 94.0, f"大题标题还留在截图里：{rect}"
    assert rect[3] <= 140.0, f"页脚/半页空白没收掉：{rect}"
    assert 24.0 <= rect[3] - rect[1] < 80.0, f"裁框高度不对：{rect}"
    assert rect[0] >= 23.0, f"左沿没收掉装订栏虚线/页边：{rect}"

    # 反例：看图题（非算式块）不许按文字行收口 —— 图可能一直延伸到下面。
    q2 = {"q_no": 17, "section": "六、看图列式",
          "text": "17.看图列式。", "images": []}
    span2 = dict(span, q_index=0)
    out2 = os.path.join(OUT, "calc_compact_look")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks([q2], {1: src}, [span2], out2)
    assert n2 == 1, f"看图题没有兜底：{n2}"
    rect2 = q2["images"][0]["rect"]
    assert rect2[3] > 300.0, f"看图题被按文字行切短了：{rect2}"


def table_garbage_gets_whole_span_and_drops_footer():
    """统计表被 OCR 横着串行：整题截图 + 清空串行文字 + 切掉页脚。

    P5 Q24 实测：两个班的成绩表并排印，OCR 把两列数字串成
    "45 44 53 47 39 34 46 47"，右侧等级标准也被插进同一行；只裁到下半截
    表格（补全下表）时，学生看不到上面的原始成绩，整题做不了（P1）。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    page = Image.new("L", (int(W_PT * k), int(H_PT * k)), 255)
    d = ImageDraw.Draw(page)
    for i in range(12):
        x = 30 + i * 30
        d.rectangle((int(x * k), int(90 * k), int((x + 18) * k), int(150 * k)), fill=0)
        d.line((int(x * k), int(90 * k), int((x + 30) * k), int(150 * k)), fill=0)
        d.line((int(x * k), int(150 * k), int((x + 30) * k), int(90 * k)), fill=0)
        for j in range(6):
            d.line((int((x + 2 + j * 3) * k), int((95 + j * 8) * k),
                    int((x + 16) * k), int((100 + j * 9) * k)), fill=255, width=1)
    d.rectangle((int(30 * k), int(160 * k), int(470 * k), int(330 * k)), outline=0, width=2)
    d.line((int(30 * k), int(160 * k), int(470 * k), int(330 * k)), fill=0, width=2)
    d.line((int(470 * k), int(160 * k), int(30 * k), int(330 * k)), fill=0, width=2)
    d.rectangle((int(280 * k), int(372 * k), int(420 * k), int(382 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    boxes = [
        {"x": 30, "y": 60, "w": 300, "h": 10, "text": "24. 张老师是六年级体育老师"},
        {"x": 280, "y": 372, "w": 140, "h": 10,
         "text": "六年级数学第6页共8页"},
    ]
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 56.0, "y1": 390.0, "text_boxes": list(boxes)}
    q = {"q_no": 24, "section": "五、解决问题（共5道小题）",
         "text": ("张老师是六年级体育老师。下面是他记录的2023年某次测试两个班男生"
                  "一分钟仰卧起坐的成绩情况。\n（1）按成绩段整理数据，补全下表。\n"
                  "（2）回答下面的问题。"),
         "source_lines": [
             "45 44 53 47 39 34 46 47",
             "52 49 50 16 40 50 49 48",
             "45 36 49 15 45 47 51 29",
             "（1）按成绩段整理数据，补全下表。",
             "（2）回答下面的问题。",
         ],
         "images": [{"name": "frag.png", "page": 1,
                     "rect": [50.0, 200.0, 300.0, 330.0],
                     "band": [50.0, 200.0, 300.0, 330.0]}]}
    # 只让「统计表横串」这一条触发：小问号没丢，否则 lost_subq 也会兜底，
    # 把 table_garbage 打坏后测试仍然绿（2026-10-22 变异闸门实测漏抓）。
    assert FG._has_interleaved_table(q) and not FG._lost_subq_numbers(q), \
        "夹具没有隔离统计表横串这一条判据"
    out = os.path.join(OUT, "table_garbage")
    shutil.rmtree(out, ignore_errors=True)
    n = FG.attach_span_fallbacks([q], {1: src}, [span], out)
    assert n == 1, f"统计表横串没有触发整题兜底：{n}"
    imgs = q["images"]
    assert len(imgs) == 1 and imgs[0].get("graphic_kind") == "span-fallback", imgs
    assert imgs[0].get("whole_question") is True, \
        f"单 span 的整题原图没标 whole_question（导出会重复印 OCR 题干）：{imgs[0]}"
    assert q["text"] == "", "串行的成绩表文字必须清空（否则与正确原图矛盾）"
    rect = imgs[0]["rect"]
    assert rect[1] <= 60.0, f"成绩表上半截没进图：{rect}"
    assert rect[3] <= 370.0, f"页脚没切掉：{rect}"
    assert os.path.exists(os.path.join(out, imgs[0]["name"]))

    # 新口径（用户：复杂题不许被不合理裁切丢内容）：同一题同页多段时，
    # 合并成一张整块截图，从第一段上沿到最后一段下沿；两段都覆盖到了才
    # 标整题原图。旧口径只截第一段、留文字，仍会丢第二段的原貌。
    q2 = dict(q)
    q2["images"] = []
    span_hi = dict(span, y0=56.0, y1=150.0)
    span_low = dict(span, y0=180.0, y1=250.0)
    out2 = os.path.join(OUT, "table_garbage_two_spans")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks([q2], {1: src}, [span_hi, span_low], out2)
    assert n2 == 1 and len(q2["images"]) == 1, \
        f"同页多段没合并成一张：{q2['images']}"
    im2 = q2["images"][0]
    assert im2["rect"][1] <= 56.0 and im2["rect"][3] >= 250.0, \
        f"合并后的截图没覆盖第二段：{im2['rect']}"
    assert im2.get("whole_question") is True, \
        f"两段都覆盖了却没标整题原图：{im2}"

    # 反例：另一段在没载入源页的第 2 页 → 只覆盖了一段，不能标整题原图，
    # 否则导出会把另一段的 OCR 文字也藏掉（宁重不许丢）。
    q3 = dict(q)
    q3["images"] = []
    span_p2 = dict(span, page=2, y0=56.0, y1=150.0)
    out3 = os.path.join(OUT, "table_garbage_missing_page")
    shutil.rmtree(out3, ignore_errors=True)
    n3 = FG.attach_span_fallbacks([q3], {1: src}, [span_hi, span_p2], out3)
    assert n3 == 1 and not q3["images"][0].get("whole_question"), \
        f"跨页题只截到一页却标成整题原图：{q3['images']}"


def page_bottom_whole_span_gets_next_page_continuation():
    """整题截图在页底截断：下一页的坐标纸和小问要补进来（含三个反例）。

    P4 六 Q4 实测：第 3 页的统计表整题截图到页底为止，第 4 页的空白条形图
    坐标纸和 (1)(2)(3) 没有任何 span 认领，导出时整页丢失（P1）。判据：
      · 单 span 的整题截图 + 本页页底 + 下一页没有别的题的 span → 补一张续图；
      · 下一页已有别的题 → 不补（那是下一题的地盘）；
      · 下一页是空白页 → 不补（没有墨迹）；
      · 根本没有下一页 → 不补。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)

    p1 = Image.new("L", (W, H), 255)
    d1 = ImageDraw.Draw(p1)
    for i in range(10):
        d1.rectangle((int(30 * k), int((50 + i * 30) * k),
                      int(560 * k), int((60 + i * 30) * k)), fill=0)
    p2 = Image.new("L", (W, H), 255)
    d2 = ImageDraw.Draw(p2)
    for i in range(6):
        d2.line((int(80 * k), int((90 + i * 18) * k),
                 int(500 * k), int((90 + i * 18) * k)), fill=0, width=2)
    for i in range(7):
        d2.line((int((80 + i * 70) * k), int(90 * k),
                 int((80 + i * 70) * k), int(180 * k)), fill=0, width=2)
    for i in range(3):
        d2.rectangle((int(30 * k), int((240 + i * 50) * k),
                      int(460 * k), int((252 + i * 50) * k)), fill=0)
    blank = Image.new("L", (W, H), 255)

    def crop_of(page):
        def crop(rect, out):
            page.crop((int(rect[0] * k), int(rect[1] * k),
                       int(rect[2] * k), int(rect[3] * k))).save(out)
        return crop

    src1 = FG.PageSource(1, W_PT, H_PT, np.asarray(p1), crop_of(p1))
    src2 = FG.PageSource(2, W_PT, H_PT, np.asarray(p2), crop_of(p2))
    srcb = FG.PageSource(2, W_PT, H_PT, np.asarray(blank), crop_of(blank))
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 580.0,
            "y0": 44.0, "y1": 400.0,
            "text_boxes": [{"x": 30, "y": 46, "w": 500, "h": 10,
                            "text": "27.下面是四年级同学喜欢的运动项目统计表。"}]}
    q = {"q_no": 27, "section": "六、解决问题", "text": "", "images": []}
    out = os.path.join(OUT, "span_continuation")
    shutil.rmtree(out, ignore_errors=True)
    n = FG.attach_span_fallbacks([q], {1: src1, 2: src2}, [span], out)
    assert n == 1, f"页底整题截图没有生成：{n}"
    imgs = q["images"]
    assert len(imgs) == 2, f"页底整题截图没有补续页：{imgs}"
    assert imgs[0].get("whole_question") is True, imgs[0]
    assert imgs[1].get("graphic_kind") == "span-continuation", imgs[1]
    assert imgs[1].get("page") == 2 and not imgs[1].get("whole_question"), imgs[1]
    cout = os.path.join(out, imgs[1]["name"])
    assert os.path.exists(cout) and os.path.getsize(cout) > 500, "续图没落盘"
    assert imgs[1]["rect"][1] <= 92.0 and imgs[1]["rect"][3] >= 350.0, \
        f"续图没盖住坐标纸和小问：{imgs[1]['rect']}"

    # 反例①：下一页已经开始另一道题 → 不补。
    q2 = {"q_no": 28, "section": "六、解决问题", "text": "", "images": []}
    span2 = dict(span)
    other = {"q_index": 1, "page": 2, "col": 0, "x0": 20.0, "x1": 580.0,
             "y0": 40.0, "y1": 380.0, "text_boxes": []}
    out2 = os.path.join(OUT, "span_continuation_other")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks(
        [q2, {"q_no": 29, "section": "六、解决问题", "text": "29.下一题。",
              "images": []}], {1: src1, 2: src2}, [span2, other], out2)
    assert n2 == 1 and len(q2["images"]) == 1, \
        f"下一页有别的题，仍然补了续图：{n2} {q2['images']}"

    # 反例②：下一页空白 → 不补。反例③：没有下一页 → 不补。
    q3 = {"q_no": 30, "section": "六、解决问题", "text": "", "images": []}
    q4 = {"q_no": 31, "section": "六、解决问题", "text": "", "images": []}
    out3 = os.path.join(OUT, "span_continuation_blank")
    out4 = os.path.join(OUT, "span_continuation_none")
    shutil.rmtree(out3, ignore_errors=True)
    shutil.rmtree(out4, ignore_errors=True)
    FG.attach_span_fallbacks([q3], {1: src1, 2: srcb}, [dict(span)], out3)
    FG.attach_span_fallbacks([q4], {1: src1}, [dict(span)], out4)
    assert len(q3["images"]) == 1 and len(q4["images"]) == 1, \
        "空白页/无下一页被当成了续图"


def cross_page_title_line_joins_the_whole_span():
    """跨页题：上一页页底的「4、估算」要跟下一页的算式挂到同一题（含三个反例）。

    P2 四、计算 4 实测：OCR 把页底「4、估算」与页首「901×8=…」并成一条
    source_line，span 却只从下一页页首算起 —— 整题截图里只剩算式行，题号与
    「估算」要求全丢，学生无法按题号对号（P1，违反 4.1 兜底一）。判据：
      · 本题最早 span 贴新页页首 + 上一页同栏最后一条正文是「本题题号+标题」
        且标题在本題 source_lines 里 → 先补一张标题小图，再排下一页正文；
      · 题号对不上 → 不补；
      · 标题不在本题 source_lines 里（别人的标题） → 不补；
      · 那行底下还有正文（不是页底最后一条） → 不补。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    import random
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)
    rnd = random.Random(11)

    def speckle(draw):
        # 扫描页有底噪；纯黑条+白底的合成图 PNG 只有一两百字节，
        # 会被"小于 500 字节＝空白/坏图"的门槛误杀（真卷不会）。
        for _ in range(2400):
            draw.point((rnd.randrange(W), rnd.randrange(H)), fill=0)

    p1 = Image.new("L", (W, H), 255)
    d1 = ImageDraw.Draw(p1)
    for i in range(6):
        d1.rectangle((int(30 * k), int((60 + i * 40) * k),
                      int(560 * k), int((70 + i * 40) * k)), fill=0)
    # 页底那条题号+标题（本题唯一的「4、估算」）
    d1.rectangle((int(34 * k), int(360 * k), int(120 * k), int(372 * k)), fill=0)
    speckle(d1)
    p2 = Image.new("L", (W, H), 255)
    d2 = ImageDraw.Draw(p2)
    d2.rectangle((int(30 * k), int(10 * k), int(560 * k), int(22 * k)), fill=0)
    speckle(d2)

    def crop_of(page):
        def crop(rect, out):
            page.crop((int(rect[0] * k), int(rect[1] * k),
                       int(rect[2] * k), int(rect[3] * k))).save(out)
        return crop

    def src(page, num):
        return FG.PageSource(num, W_PT, H_PT, np.asarray(page), crop_of(page))

    src1, src2 = src(p1, 1), src(p2, 2)
    title_box = {"x": 34, "y": 360, "w": 86, "h": 12, "text": "4、估算"}
    span1 = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 580.0,
             "y0": 56.0, "y1": 400.0,
             "text_boxes": [{"x": 30, "y": 60, "w": 500, "h": 10,
                             "text": "3.用递等式计算(12分)"}, title_box]}
    span2 = {"q_index": 1, "page": 2, "col": 0, "x0": 20.0, "x1": 580.0,
             "y0": 8.0, "y1": 40.0,
             "text_boxes": [{"x": 30, "y": 10, "w": 500, "h": 10,
                             "text": "901×8= 98÷5≈ 50÷7≈ 989+605"}]}
    q_prev = {"q_no": 3, "section": "四、计算(30 分)", "text": "用递等式计算(12分)",
              "source_lines": ["用递等式计算(12分)", "①34×6 ②659÷8"],
              "images": [{"name": "prev.png", "page": 1, "rect": [20, 50, 580, 320],
                          "graphic": True}]}

    def make_q(n=4, src_lines=None):
        merged = "估算 901×8=       98÷5≈   50÷7≈       989+605"
        return {"q_no": n, "section": "四、计算(30 分)", "text": merged,
                "source_lines": (src_lines if src_lines is not None else [merged]),
                "images": []}

    out = os.path.join(OUT, "span_carry_title")
    shutil.rmtree(out, ignore_errors=True)
    q = make_q()
    n = FG.attach_span_fallbacks([q_prev, q], {1: src1, 2: src2},
                                 [span1, span2], out)
    assert n == 1, f"跨页算式题没有生成整题图：{n}"
    imgs = q["images"]
    assert len(imgs) == 2, f"上一页的「4、估算」没补进来：{imgs}"
    assert imgs[0]["page"] == 1 and imgs[0]["graphic_kind"] == "calc-span", imgs[0]
    assert imgs[0]["rect"][1] <= 361.0 and imgs[0]["rect"][3] >= 370.0, \
        f"标题小图没盖住「4、估算」：{imgs[0]['rect']}"
    assert imgs[1]["page"] == 2, f"下一页算式图被挤掉了：{imgs}"
    assert imgs[0].get("whole_question") is True, \
        f"两段都覆盖了却没标整题原图（导出会重复印文字）：{imgs[0]}"
    cout = os.path.join(out, imgs[0]["name"])
    assert os.path.exists(cout) and os.path.getsize(cout) > 500, "标题小图没落盘"

    # 反例①：页底标题的题号不是本题 → 不补。
    out1 = os.path.join(OUT, "span_carry_title_other_no")
    shutil.rmtree(out1, ignore_errors=True)
    q1 = make_q(n=5)
    FG.attach_span_fallbacks([q_prev, q1], {1: src1, 2: src2},
                             [dict(span1), dict(span2)], out1)
    assert len(q1["images"]) == 1, f"别的题号的标题被补进来了：{q1['images']}"

    # 反例②：标题不在本题 source_lines（OCR 没把它并进来） → 不补。
    out2 = os.path.join(OUT, "span_carry_title_not_in_src")
    shutil.rmtree(out2, ignore_errors=True)
    q2 = make_q(src_lines=["901×8=       98÷5≈   50÷7≈       989+605"])
    FG.attach_span_fallbacks([q_prev, q2], {1: src1, 2: src2},
                             [dict(span1), dict(span2)], out2)
    assert len(q2["images"]) == 1, f"标题不在题干里的行被补进来了：{q2['images']}"

    # 反例③：标题下面还有正文（不是页底最后一条） → 不补。
    out3 = os.path.join(OUT, "span_carry_title_not_last")
    shutil.rmtree(out3, ignore_errors=True)
    span1b = dict(span1, text_boxes=list(span1["text_boxes"]) + [
        {"x": 34, "y": 384, "w": 300, "h": 12, "text": "五、解决问题"}])
    q3 = make_q()
    FG.attach_span_fallbacks([q_prev, q3], {1: src1, 2: src2},
                             [span1b, dict(span2)], out3)
    assert len(q3["images"]) == 1, f"页底正文下面的标题行被补进来了：{q3['images']}"


def chart_drawing_question_gets_whole_region_and_continuation():
    """要求"画统计图"的题：只裁到数据表也必须换整块截图（含一个反例）。

    P4 六 Q4 实测：题干里只剩数据表的零散数字，"请根据以上数据制成复式条形
    统计图"被 OCR 挤丢，第 4 页整张空白坐标纸和 (1)(2)(3) 没有任何 span
    认领 —— 只给孩子一张数据表，他没法作图（P1）。判据：
      · 原文要求"制成/绘制/画出…统计图"，现有图没盖住整题 → 整题截图，
        跨页补续图，横向整页宽（纵轴刻度/图例贴着页边），文字与小问清空；
      · 只是问"用哪种统计图"、图已盖住区间的选择题 → 原样不动。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)

    p1 = Image.new("L", (W, H), 255)
    d1 = ImageDraw.Draw(p1)
    for i in range(4):                     # 数据表：几条横线 + 竖线
        d1.rectangle((int(80 * k), int((60 + i * 12) * k),
                      int(400 * k), int((62 + i * 12) * k)), fill=0)
    for i in range(6):
        d1.rectangle((int((80 + i * 64) * k), int(60 * k),
                      int((81 + i * 64) * k), int(96 * k)), fill=0)
    d1.rectangle((int(30 * k), int(390 * k), int(560 * k), int(396 * k)), fill=0)
    p2 = Image.new("L", (W, H), 255)
    d2 = ImageDraw.Draw(p2)
    for i in range(6):                     # 空白坐标纸
        d2.line((int(80 * k), int((120 + i * 18) * k),
                 int(500 * k), int((120 + i * 18) * k)), fill=0, width=2)
    for i in range(7):
        d2.line((int((80 + i * 70) * k), int(120 * k),
                 int((80 + i * 70) * k), int(210 * k)), fill=0, width=2)
    d2.rectangle((int(510 * k), int(130 * k), int(590 * k), int(160 * k)),
                 outline=0, width=1)       # 图例在坐标纸右侧贴边
    for i in range(3):                     # (1)(2)(3)
        d2.rectangle((int(30 * k), int((260 + i * 40) * k),
                      int(460 * k), int((270 + i * 40) * k)), fill=0)

    def crop_of(page):
        def crop(rect, out):
            page.crop((int(rect[0] * k), int(rect[1] * k),
                       int(rect[2] * k), int(rect[3] * k))).save(out)
        return crop

    src1 = FG.PageSource(1, W_PT, H_PT, np.asarray(p1), crop_of(p1))
    src2 = FG.PageSource(2, W_PT, H_PT, np.asarray(p2), crop_of(p2))
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 580.0,
            "y0": 44.0, "y1": 400.0,
            "text_boxes": [{"x": 30, "y": 46, "w": 500, "h": 10,
                            "text": "4.四年级同学喜欢的运动项目如下表。（10分）"}]}
    table = {"name": "table.png", "page": 1,
             "rect": [80.0, 58.0, 400.0, 98.0],
             "band": [80.0, 58.0, 400.0, 98.0]}
    q = {"q_no": 4, "section": "六、解决问题", "qtype": "essay",
         "text": "四年级同学喜欢的运动项目如下表。（1）男生哪个项目最多？（2）"
                 "哪个项目人最多？（3）你还能提出什么数学问题？",
         "source_lines": ["四年级同学喜欢的运动项目如下表。（10分）",
                          "请根据以上数据制成复式条形统计图"],
         "subqs": [{"no": 1, "text": "男生哪个项目最多？"},
                   {"no": 2, "text": "哪个项目人最多？"},
                   {"no": 3, "text": "你还能提出什么数学问题？"}],
         "images": [dict(table)]}
    out = os.path.join(OUT, "chart_whole")
    shutil.rmtree(out, ignore_errors=True)
    n = FG.attach_span_fallbacks([q], {1: src1, 2: src2}, [span], out)
    assert n == 1, f"统计图题没有换整块截图：{n}"
    imgs = q["images"]
    assert len(imgs) == 2, f"跨页空白坐标纸没补进来：{imgs}"
    assert imgs[0].get("whole_question") is True, imgs[0]
    assert imgs[1].get("graphic_kind") == "span-continuation", imgs[1]
    for im in imgs:
        assert im["rect"][0] <= 0.5 and im["rect"][2] >= W_PT - 0.5, \
            f"统计图截图没取整页宽（纵轴/图例会被切）：{im['rect']}"
    assert imgs[1]["rect"][1] <= 122.0 and imgs[1]["rect"][3] >= 340.0, \
        f"续图没盖住坐标纸和三问：{imgs[1]['rect']}"
    assert q["text"] == "" and not q.get("subqs"), \
        "统计图原图已含说明与小问，OCR 文字/小问必须清空，避免网页重复"

    # 反例：只是问"用哪种统计图"，图已覆盖区间 → 原样不动。
    q2 = {"q_no": 5, "section": "一、选择", "qtype": "choice",
          "text": "要表示男女生人数的对比，下面哪种统计图比较合适？",
          "source_lines": ["要表示男女生人数的对比，下面哪种统计图比较合适？"],
          "images": [{"name": "full.png", "page": 1,
                      "rect": [22.0, 46.0, 578.0, 398.0],
                      "band": [22.0, 46.0, 578.0, 398.0]}]}
    out2 = os.path.join(OUT, "chart_choice_kept")
    shutil.rmtree(out2, ignore_errors=True)
    span2 = dict(span, q_index=1)
    n2 = FG.attach_span_fallbacks([q2], {1: src1}, [span2], out2)
    assert n2 == 0 and q2["images"][0]["name"] == "full.png", "选择题的完整图被误换"


def complex_question_gets_one_region_per_column_and_page():
    """复杂题跨栏/跨页：每个（页,栏）只裁一张，覆盖本题该栏首行到末行。

    用户口径：图片处理不好时宁可把整个题目区域截成一张，也不许多张碎片或
    不合理裁切丢内容。同一题的三段 span（p1 左栏两段、p1 右栏一段、p2 左栏
    一段）必须并成三张整栏图，且全部覆盖才算 whole_question。
    反例：某一栏的页源缺失 → 已有的图照出，但 whole_question 必须为 False
    （导出仍保留 OCR 文字，宁重不许丢）。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0

    def make_page(bands):
        page = Image.new("L", (int(W_PT * k), int(H_PT * k)), 255)
        d = ImageDraw.Draw(page)
        rng = np.random.default_rng(7)
        for (bx0, by0, bx1, by1) in bands:
            for i in range(6):
                y = by0 + i * max(1.0, (by1 - by0 - 6) / 6.0)
                d.rectangle((int(bx0 * k), int(y * k),
                             int(bx1 * k), int((y + 5) * k)), fill=0)
            # 撒一层固定种子的细点：让 PNG 不至于压到 500 字节门槛以下
            # （产出门槛本身要测，不能为了过门槛把内容画成纯色块）。
            x0p, y0p = int(bx0 * k), int(by0 * k)
            x1p, y1p = int(bx1 * k), int(by1 * k)
            noise = (rng.random((y1p - y0p, x1p - x0p)) < 0.08)
            arr = np.asarray(page).copy()
            arr[y0p:y1p, x0p:x1p][noise] = 0
            page = Image.fromarray(arr)
            d = ImageDraw.Draw(page)
        return page

    p1 = make_page([(24.0, 50.0, 276.0, 100.0),
                    (24.0, 110.0, 276.0, 150.0),
                    (324.0, 60.0, 576.0, 170.0)])
    p2 = make_page([(24.0, 70.0, 276.0, 180.0)])

    def crop_of(page):
        def crop(rect, out):
            page.crop((int(rect[0] * k), int(rect[1] * k),
                       int(rect[2] * k), int(rect[3] * k))).save(out)
        return crop

    src1 = FG.PageSource(1, W_PT, H_PT, np.asarray(p1), crop_of(p1))
    src2 = FG.PageSource(2, W_PT, H_PT, np.asarray(p2), crop_of(p2))
    spans = [
        {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 280.0,
         "y0": 50.0, "y1": 100.0, "text_boxes": []},
        {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 280.0,
         "y0": 110.0, "y1": 150.0, "text_boxes": []},
        {"q_index": 0, "page": 1, "col": 1, "x0": 320.0, "x1": 580.0,
         "y0": 60.0, "y1": 170.0, "text_boxes": []},
        {"q_index": 0, "page": 2, "col": 0, "x0": 20.0, "x1": 280.0,
         "y0": 70.0, "y1": 180.0, "text_boxes": []},
    ]
    q = {"q_no": 24, "section": "六、解决问题", "text": "", "images": []}
    out = os.path.join(OUT, "span_multi_region")
    shutil.rmtree(out, ignore_errors=True)
    n = FG.attach_span_fallbacks([q], {1: src1, 2: src2}, spans, out)
    assert n == 1, f"跨栏跨页题没有整题兜底：{n}"
    imgs = q["images"]
    assert len(imgs) == 3, f"每个（页,栏）应只出一张：{[im['name'] for im in imgs]}"
    names = [im["name"] for im in imgs]
    assert names == ["p1_q0_c0_span.png", "p1_q0_c1_span.png",
                     "p2_q0_c0_span.png"], names
    assert imgs[0].get("whole_question") is True, imgs[0]
    assert not imgs[1].get("whole_question") and not imgs[2].get("whole_question")
    # 左栏两段必须并进同一张：上沿到第一段、下沿到第二段。
    assert imgs[0]["rect"][1] <= 50.0 and imgs[0]["rect"][3] >= 150.0, imgs[0]["rect"]
    # 右栏独立一张，不许混进左栏的 x 范围。
    assert imgs[1]["rect"][0] >= 300.0 and imgs[1]["rect"][3] >= 170.0, imgs[1]["rect"]
    assert imgs[2]["page"] == 2 and imgs[2]["rect"][3] >= 180.0, imgs[2]["rect"]
    for im in imgs:
        fp = os.path.join(out, im["name"])
        assert os.path.exists(fp) and os.path.getsize(fp) > 500, f"没落盘：{fp}"

    # 反例：第二页页源缺失 → 已裁到的两张照出，但不算整题原图。
    q2 = {"q_no": 25, "section": "六、解决问题", "text": "", "images": []}
    out2 = os.path.join(OUT, "span_multi_region_missing")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks([q2], {1: src1}, spans, out2)
    assert n2 == 1 and len(q2["images"]) == 2, \
        f"缺页时其余栏没照出：{n2} {[im['name'] for im in q2['images']]}"
    assert not any(im.get("whole_question") for im in q2["images"]), \
        "少覆盖一栏却当成了整题原图"


def lost_subq_numbers_use_whole_span():
    """原文有（1）（2）（3），拼出来的题干一个都没剩 → 整题截图，文字清空。

    P5 Q25 实测：图形把每问的后半句吞掉，题干只剩三段残句，小问号全丢；
    导出的图还被挤到下一页，孩子得翻页才能看到（1）（2）的任务。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    page = Image.new("L", (int(W_PT * k), int(H_PT * k)), 255)
    d = ImageDraw.Draw(page)
    for i in range(14):
        x = 30 + i * 28
        d.rectangle((int(x * k), int(80 * k), int((x + 16) * k), int(160 * k)), fill=0)
        d.line((int(x * k), int(80 * k), int((x + 24) * k), int(160 * k)), fill=0)
        d.line((int(x * k), int(160 * k), int((x + 24) * k), int(80 * k)), fill=0)
    d.rectangle((int(30 * k), int(170 * k), int(470 * k), int(340 * k)), outline=0, width=2)
    d.line((int(30 * k), int(170 * k), int(470 * k), int(340 * k)), fill=0, width=2)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 40.0, "y1": 390.0, "text_boxes": []}
    q = {"q_no": 25, "section": "五、解决问题（共5道小题）",
         "text": "学习完圆的周长后，同学们设计了一些新图形。他们正在研究这些新图形的周长。",
         "source_lines": [
             "（1）笑笑设计出了一个新图形，如下图所示。",
             "你同意笑笑的说法吗？写一写，算一算，说明你的理由。",
             "（2）同学们还设计出了以下三个新图形，请你判断。",
             "（3）结合以上研究，请你表示出你的发现。",
         ],
         "images": [{"name": "fig.png", "page": 1,
                     "rect": [60.0, 120.0, 240.0, 260.0],
                     "band": [60.0, 120.0, 240.0, 260.0]}]}
    out = os.path.join(OUT, "lost_subq")
    shutil.rmtree(out, ignore_errors=True)
    n = FG.attach_span_fallbacks([q], {1: src}, [span], out)
    assert n == 1, f"小问号全丢的题没有整题兜底：{n}"
    assert q["images"][0].get("graphic_kind") == "span-fallback", q["images"]
    assert q["text"] == "", "整题原图已含每一问，残句文字必须清空"
    assert q["images"][0]["rect"][1] <= 42.0, f"题头没进图：{q['images'][0]['rect']}"


def partially_lost_subq_number_uses_whole_span():
    """原文（1）（2）（3），题干只剩（1）（3）→ 整题截图（含两个反例）。

    P5 Q25 实测：图把（2）整段吞进裁图，留着的（3）排在图前面，
    孩子读到的顺序是 1→3→图里的 2。整题原图里三问都在原位。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    page = Image.new("L", (int(W_PT * k), int(H_PT * k)), 255)
    d = ImageDraw.Draw(page)
    d.rectangle((int(60 * k), int(120 * k), int(240 * k), int(260 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 40.0, "y1": 390.0, "text_boxes": []}
    src_lines = ["（1）笑笑设计出了一个新图形。",
                 "（2）同学们还设计出了以下三个新图形，请你判断。",
                 "（3）结合以上研究，请表示出你的发现。"]
    partial = ("学习完圆的周长后，同学们设计了一些新图形。"
               "（1）笑笑设计出了一个新图形。"
               "（3）结合以上研究，请表示出你的发现。")

    def make(text, subqs=None):
        return {"q_no": 25, "section": "五、解决问题（共5道小题）",
                "text": text, "source_lines": list(src_lines),
                "subqs": subqs or [],
                "images": [{"name": "fig.png", "page": 1,
                            "rect": [60.0, 120.0, 240.0, 260.0],
                            "band": [60.0, 120.0, 240.0, 260.0]}]}

    out = os.path.join(OUT, "part_lost_subq")
    shutil.rmtree(out, ignore_errors=True)
    q = make(partial)
    n = FG.attach_span_fallbacks([q], {1: src}, [span], out)
    assert n == 1, f"缺第（2）问没有整题兜底：{n}"
    assert q["images"][0].get("graphic_kind") == "span-fallback", q["images"]
    assert q["text"] == "", "整题原图已含三问，残留的（1）（3）必须清空"

    # 反例①：三问都在题干里 → 不许换成整题截图。
    q2 = make("学习完圆的周长后。（1）笑笑设计出了一个新图形。"
              "（2）同学们还设计出了以下三个新图形。"
              "（3）结合以上研究，请表示出你的发现。")
    n2 = FG.attach_span_fallbacks([q2], {1: src}, [span], out)
    assert n2 == 0 and not q2["images"][0].get("graphic"), \
        f"三问齐全却换了整题图：{n2} {q2['images']}"

    # 反例②：题干没写（2），但已拆进 subqs → 不算丢。
    q3 = make(partial, [{"no": 2, "text": "同学们还设计出了以下三个新图形"}])
    n3 = FG.attach_span_fallbacks([q3], {1: src}, [span], out)
    assert n3 == 0 and not q3["images"][0].get("graphic"), \
        f"小问已拆出来却当成丢失：{n3} {q3['images']}"


def flattened_fraction_gets_whole_span():
    """分数被 OCR 拍平成 310/410：整题截图（含三个反例）。

    P6 五 Q1 实测：3/10、4/10 的分数线读不出来，题干成了
    "第一天看了全书的310" —— 条件直接错。原图里分数线清清楚楚。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    page = Image.new("L", (int(W_PT * k), int(H_PT * k)), 255)
    d = ImageDraw.Draw(page)
    for i in range(4):
        y = 70 + i * 50
        d.rectangle((int(30 * k), int(y * k), int(520 * k), int((y + 14) * k)),
                    fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 540.0,
            "y0": 40.0, "y1": 390.0, "text_boxes": []}
    out = os.path.join(OUT, "flat_fraction")
    shutil.rmtree(out, ignore_errors=True)

    def run(text):
        q = {"q_no": 1, "section": "五、解决问题。（25%）", "text": text,
             "source_lines": [text], "subqs": [], "images": []}
        return q, FG.attach_span_fallbacks([q], {1: src}, [span], out)

    q, n = run("小华有一本书，第一天看了全书的310，第二天看了全书的410，"
               "两天一共看了全书的几分之几?")
    assert n == 1, f"拍平分数没有整题兜底：{n}"
    assert q["images"] and q["images"][0].get("whole_question"), q["images"]
    assert q["text"] == "", "整题原图已含分数线，310/410 必须清掉"

    # 反例①：310 后面有单位"页" → 是正常数量，不许换成整题图。
    q2, n2 = run("一本书有310页，第一天看了全书的3/10，"
                 "两天一共看了全书的几分之几?")
    assert n2 == 0 and not q2["images"], f"带单位的 310 被误判：{n2} {q2['images']}"

    # 反例②："百分之几"不是分数题（P5 Q22 路灯题）。
    q3, n3 = run("幸福村今年的路灯数量比去年增加了百分之几？总数310")
    assert n3 == 0 and not q3["images"], f"百分之几被误判：{n3} {q3['images']}"

    # 反例③：2023 年是年份，不许当成分数拍平。
    q4, n4 = run("2023年学校组织读书，第一天看了全书的3/10，"
                 "两天一共看了全书的几分之几?")
    assert n4 == 0 and not q4["images"], f"年份被误判：{n4} {q4['images']}"


def garbled_formula_gets_whole_span():
    """算式被 OCR 拍平成数字+空格：整题截图替换碎片（含三个反例）。

    P5 Q14 原文 "48×2/3×3/4" 读成 "48            213"，分数线/乘号全丢，
    孩子根本不知道要用哪个算式解题（P1）。碎片图里没有算式，只有整题原图能救。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)
    page = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(page)
    d.rectangle((int(30 * k), int(100 * k), int(470 * k), int(370 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 100.0, "y1": 380.0, "text_boxes": []}
    text = "根据右图，乐乐列出了算式48            213 她想用这个算式解决的问题是："
    frags = [
        {"name": "fig.png", "page": 1, "rect": [130.0, 147.0, 241.0, 218.0],
         "band": [130.0, 147.0, 241.0, 218.0]},
        {"name": "blank.png", "page": 1, "rect": [31.0, 167.0, 161.0, 200.0],
         "band": [31.0, 167.0, 161.0, 200.0]},
    ]
    q = {"q_no": 14, "section": "二、填空题(共6道小题)", "text": text,
         "images": [dict(x) for x in frags]}
    out1 = os.path.join(OUT, "garbled_formula")
    shutil.rmtree(out1, ignore_errors=True)
    n1 = FG.attach_span_fallbacks([q], {1: src}, [dict(span)], out1)
    assert n1 == 1, f"拍平的算式没有触发整题兜底：{n1}"
    assert len(q["images"]) == 1 and q["images"][0].get("graphic") is True, q["images"]
    assert q["images"][0].get("graphic_kind") == "span-fallback"
    assert q["text"] == "", "整题截图已含算式，读崩的文字必须清空"
    assert q["images"][0]["rect"][2] >= 245.0, \
        f"整题截图没包住碎片右沿：{q['images'][0]['rect']}"
    p1 = os.path.join(out1, "p1_q0_span.png")
    assert os.path.exists(p1) and os.path.getsize(p1) > 500, "整题截图没落盘"

    # 反例一：算式带运算符（ORC 读对了）→ 不许换成整题大图
    q_ok = {"q_no": 14, "section": "二、填空题(共6道小题)",
            "text": "根据右图，乐乐列出了算式48×2/3×3/4，她想用这个算式解决的问题是：",
            "images": [dict(x) for x in frags]}
    out2 = os.path.join(OUT, "formula_ok")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks([q_ok], {1: src}, [dict(span)], out2)
    assert n2 == 0 and len(q_ok["images"]) == 2, "正确算式被误换成整题截图"
    assert q_ok["text"].startswith("根据右图"), "正确算式的文字被清空"

    # 反例二：碎片已经覆盖大半区间 → 原图不动
    q_full = {"q_no": 14, "section": "二、填空题(共6道小题)", "text": text,
              "images": [{"name": "full.png", "page": 1,
                          "rect": [25.0, 105.0, 475.0, 375.0],
                          "band": [25.0, 105.0, 475.0, 375.0]}]}
    out3 = os.path.join(OUT, "formula_full")
    shutil.rmtree(out3, ignore_errors=True)
    n3 = FG.attach_span_fallbacks([q_full], {1: src}, [dict(span)], out3)
    assert n3 == 0 and q_full["text"] == text, "已覆盖区间的图被整题截图顶掉"

    # 正例三：没有碎片图，但算式被拍平 → 仍给整题截图
    q_noimg = {"q_no": 14, "section": "二、填空题(共6道小题)",
               "text": text, "images": []}
    out4 = os.path.join(OUT, "formula_noimg")
    shutil.rmtree(out4, ignore_errors=True)
    n4 = FG.attach_span_fallbacks([q_noimg], {1: src}, [dict(span)], out4)
    assert n4 == 1 and q_noimg["text"] == "" and q_noimg["images"], \
        f"没图时拍平算式没有兜底：{n4}"


def inline_gap_and_lost_fraction_get_whole_span():
    """OCR 把行内卡片/分数整段吞掉：整题截图，残句清空（含两个反例）。

    P3 判断 Q3 的卡片 [2][3][4][5] 读成 "从卡片            意抽取"；
    P2 判断 Q5 的 1/10 读成第二行 "101            ）"。
    两者都让关键条件消失，只靠修字补不回来，整题原图是唯一可信来源。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    import app.extractor.figures as FG
    W_PT, H_PT = 600.0, 400.0
    k = FG.DPI_PROBE / 72.0
    W, H = int(W_PT * k), int(H_PT * k)
    page = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(page)
    d.rectangle((int(30 * k), int(100 * k), int(470 * k), int(370 * k)), fill=0)
    arr = np.asarray(page)

    def crop(rect, out):
        page.crop((int(rect[0] * k), int(rect[1] * k),
                   int(rect[2] * k), int(rect[3] * k))).save(out)

    src = FG.PageSource(1, W_PT, H_PT, arr, crop)
    span = {"q_index": 0, "page": 1, "col": 0, "x0": 20.0, "x1": 480.0,
            "y0": 100.0, "y1": 380.0, "text_boxes": []}

    # 正例一：行内 4 个以上空格，前后都是汉字 → 卡片图被吞
    q_gap = {"q_no": 3, "section": "二、判断", "qtype": "judge",
             "text": "从卡片            意抽取两张，抽到和是双数的我赢。",
             "images": [], "source_lines": ["从卡片            意抽取两张。"]}
    out1 = os.path.join(OUT, "inline_gap")
    shutil.rmtree(out1, ignore_errors=True)
    n1 = FG.attach_span_fallbacks([q_gap], {1: src}, [dict(span)], out1)
    assert n1 == 1 and q_gap["images"], f"行内缺口没有整题兜底：{n1}"
    assert q_gap["text"] == "", "残句与整题原图并排印会自相矛盾"
    assert q_gap["images"][0].get("whole_question") is True, q_gap["images"]
    p1 = os.path.join(out1, "p1_q0_span.png")
    assert os.path.exists(p1) and os.path.getsize(p1) > 500, "整题截图没落盘"

    # 反例一：已经有图（卡片可能已经裁到）→ 不许换成整题截图
    q_img = {"q_no": 3, "section": "二、判断", "qtype": "judge",
             "text": "从卡片            意抽取两张。",
             "images": [{"name": "cards.png", "page": 1,
                         "rect": [100.0, 100.0, 300.0, 140.0],
                         "band": [100.0, 100.0, 300.0, 140.0]}]}
    out2 = os.path.join(OUT, "inline_gap_has_img")
    shutil.rmtree(out2, ignore_errors=True)
    n2 = FG.attach_span_fallbacks([q_img], {1: src}, [dict(span)], out2)
    assert n2 == 0 and q_img["text"].startswith("从卡片"), "已有图的题被整题截图顶掉"

    # 正例二：分数拍平成一行数字 "101 )" → 整题截图
    q_frac = {"q_no": 5, "section": "二、判断", "qtype": "judge",
              "text": "把10块糖平均分给5个小朋友，每个小朋友分了这些糖 101",
              "images": [], "source_lines": [
                  "把10块糖平均分给5个小朋友，每个小朋友分了这些糖",
                  "101            ）"]}
    out3 = os.path.join(OUT, "lost_fraction")
    shutil.rmtree(out3, ignore_errors=True)
    n3 = FG.attach_span_fallbacks([q_frac], {1: src}, [dict(span)], out3)
    assert n3 == 1 and q_frac["images"], f"拍平分数没有整题兜底：{n3}"
    assert q_frac["text"] == "", "拍平分数的残句必须清空"
    assert q_frac["images"][0].get("whole_question") is True, q_frac["images"]

    # 反例二：普通作答括号行（没有孤立数字）不许触发
    q_ok = {"q_no": 6, "section": "二、判断", "qtype": "judge",
            "text": "还剩下（    ）米。", "images": [],
            "source_lines": ["还剩下（    ）米。"]}
    out4 = os.path.join(OUT, "lost_fraction_ok")
    shutil.rmtree(out4, ignore_errors=True)
    n4 = FG.attach_span_fallbacks([q_ok], {1: src}, [dict(span)], out4)
    assert n4 == 0 and q_ok["text"] == "还剩下（    ）米。", "空白括号被误当拍平分数"

    # 正例三：比较算式被读成字母（P4 Q9：×→X、○→O、÷→+）→ 整题截图
    q_ops = {"q_no": 9, "section": "一、填空", "qtype": "fill",
             "text": "在O里填上“<”“>”或“=” 230X20O23X200  96+3O69+3",
             "images": [], "source_lines": ["在O里填上“<”“>”或“=”",
                                            "230X20O23X200  96+3O69+3"]}
    out5 = os.path.join(OUT, "op_garble")
    shutil.rmtree(out5, ignore_errors=True)
    n5 = FG.attach_span_fallbacks([q_ops], {1: src}, [dict(span)], out5)
    assert n5 == 1 and q_ops["images"], f"符号读成字母没有整题兜底：{n5}"
    assert q_ops["text"] == "", "错符号的残句必须清空"

    # 反例三：只有一处 X（P2 "0÷17=0×18"）→ 不许触发
    q_one = {"q_no": 1, "section": "二、判断", "qtype": "judge",
             "text": "0÷17=0X18", "images": [],
             "source_lines": ["0÷17=0X18"]}
    out6 = os.path.join(OUT, "op_garble_one")
    shutil.rmtree(out6, ignore_errors=True)
    n6 = FG.attach_span_fallbacks([q_one], {1: src}, [dict(span)], out6)
    assert n6 == 0 and q_one["text"] == "0÷17=0X18", "单处乘法 X 被误当符号丢失"


def side_pairs_and_gutter_find_the_real_split():
    """并排两小题：认出一对区间 + 在两张图之间找到贯通空白竖缝（含六个反例）。"""
    import numpy as np
    import app.extractor.figures as FG

    spans = [
        {"q_index": 0, "page": 1, "col": 0, "section": "四", "y0": 100.0, "y1": 200.0},
        {"q_index": 1, "page": 1, "col": 0, "section": "四", "y0": 101.0, "y1": 201.0},
        {"q_index": 2, "page": 1, "col": 0, "section": "四", "y0": 400.0, "y1": 500.0},
    ]
    assert FG._side_pairs(spans) == [(0, 1)], FG._side_pairs(spans)
    # 反例：不同大题 / 不同栏 / 不同页 / y0 差太多 → 都不配成对
    for i, patch in enumerate((
            {"section": "五"}, {"col": 1}, {"page": 2}, {"y0": 110.0})):
        bad = [dict(s) for s in spans]
        bad[1].update(patch)
        assert FG._side_pairs(bad) == [], f"第 {i} 个反例被配成对：{FG._side_pairs(bad)}"
    # 反例：题号不连续（0 与 2 同高同段）也不配
    nonseq = [dict(spans[0]), {**spans[2], "q_index": 2, "y0": 100.0, "y1": 200.0}]
    assert FG._side_pairs(nonseq) == [], "不连续的题号被当并排两问"

    def src_with(left, right):
        gray = np.full((600, 800), 255, dtype=np.uint8)
        gray[60:520, left[0]:left[1]] = 0
        gray[60:520, right[0]:right[1]] = 0
        return FG.PageSource(1, 576.0, 432.0, gray, lambda r, o: None)

    rect = (20.0, 40.0, 520.0, 380.0)
    gx = FG._side_gutter(rect, src_with((40, 300), (420, 720)), np)
    assert gx is not None and 240.0 < gx < 280.0, f"没找到真竖缝：{gx}"

    # 反例①：整张实心大图（没有贯穿空白）→ 不许切
    solid = FG.PageSource(1, 576.0, 432.0,
                          np.pad(np.zeros((460, 680), dtype=np.uint8), ((60, 80), (40, 80)),
                                 constant_values=255), lambda r, o: None)
    assert FG._side_gutter(rect, solid, np) is None, "实心大图被当成两幅并排图"

    # 反例②：只有细轮廓的平行四边形（顶/底边每列都有 2 个墨点）→ 内部不是缝
    outline = np.full((600, 800), 255, dtype=np.uint8)
    outline[60:64, 40:720] = 0
    outline[516:520, 40:720] = 0
    outline[60:520, 40:44] = 0
    outline[60:520, 716:720] = 0
    hollow = FG.PageSource(1, 576.0, 432.0, outline, lambda r, o: None)
    assert FG._side_gutter(rect, hollow, np) is None, "细轮廓图内部被当缝切开"

    # 反例③：缝太窄（8.6pt < 12pt）→ 不切
    assert FG._side_gutter(rect, src_with((40, 360), (372, 720)), np) is None, \
        "窄缝也被当成两图的间隔"
    # 反例④：左边只有 28.8pt 宽的墨（<40pt 的一半）→ 不是成块的两幅图
    assert FG._side_gutter(rect, src_with((40, 80), (420, 720)), np) is None, \
        "一边太窄仍被切开"
    # 反例⑤：两幅实图之间是一条"每列都有零星墨点"的虚线带 —— 每列墨量只有
    # 1–3 点，只看墨量会当空白；非零列占比 >30% 必须拒绝（否则从虚线中间切一刀）。
    gd = np.full((600, 800), 255, dtype=np.uint8)
    gd[60:520, 40:300] = 0
    gd[60:520, 420:720] = 0
    for x in range(304, 416, 4):
        gd[280:283, x:x + 2] = 0
    dotted_mid = FG.PageSource(1, 576.0, 432.0, gd, lambda r, o: None)
    assert FG._side_gutter(rect, dotted_mid, np) is None, \
        "稀疏虚线带被当贯通空白缝"


def side_pair_split_absorbs_cut_label_and_clamps_edges():
    """并排图的拆框、被上沿切穿的图注回吸、最终修边夹回竖缝（含三个反例）。"""
    import numpy as np
    import app.extractor.figures as FG

    gray = np.full((600, 800), 255, dtype=np.uint8)
    gray[60:520, 40:300] = 0
    gray[60:520, 420:720] = 0
    src = FG.PageSource(1, 576.0, 432.0, gray, lambda r, o: None)
    label = {"x": 60.0, "y": 56.5, "w": 380.0, "h": 10.8,
             "text": "一共种了800棵树            30本"}

    # 先单独验回吸：行被框上沿切穿（56.5–67.3，框从 62.5 起）也要并进来
    rect = (28.8, 62.5, 518.4, 380.0)
    grown = FG._absorb_pair_top(rect, [label])
    assert abs(grown[1] - 55.5) < 0.6, f"被上沿切穿的图注没吸回：{grown}"
    # 反例：行完全在框上方（by1 < y0-0.5）→ 不动
    assert FG._absorb_pair_top(rect, [{"x": 60, "y": 40, "w": 200, "h": 10,
                                       "text": "30本"}]) == rect
    # 反例：题干（题号起手 + 空位）→ 不动
    assert FG._absorb_pair_top(rect, [{"x": 40, "y": 56, "w": 260, "h": 12,
                                       "text": "17.松树种了多少棵？（ ）"}]) == rect
    # 反例：行高 >16pt（正文行）→ 不动
    assert FG._absorb_pair_top(rect, [{"x": 60, "y": 50, "w": 200, "h": 20,
                                       "text": "一共种了800棵树"}]) == rect

    sec = "四、看图列式计算"
    spans = [
        {"q_index": 0, "page": 1, "col": 0, "x0": 10.0, "x1": 520.0,
         "section": sec, "y0": 50.0, "y1": 400.0, "text_boxes": [label]},
        {"q_index": 1, "page": 1, "col": 0, "x0": 10.0, "x1": 520.0,
         "section": sec, "y0": 51.0, "y1": 401.0, "text_boxes": []},
    ]
    base = {"q_index": 0, "page": 1, "graphic": None, "rect": rect,
            "w_pt": 489.6, "h_pt": 317.5, "src": src}
    out = FG._split_side_by_side_figures([dict(base)], spans)
    got = {int(c["q_index"]): c for c in out}
    assert set(got) == {0, 1}, f"没拆成左右两张：{[c['q_index'] for c in out]}"
    lsp, rsp = got[0], got[1]
    meta = lsp.get("side_pair") or {}
    assert meta.get("qs") == [0, 1] and meta.get("split_x") is not None, meta
    assert lsp["rect"][2] == meta["split_x"] - 0.5, f"左图没夹在竖缝左边：{lsp['rect']}"
    assert rsp["rect"][0] == meta["split_x"] + 0.5, f"右图没夹在竖缝右边：{rsp['rect']}"
    assert abs(lsp["rect"][1] - 55.5) < 0.6 and abs(rsp["rect"][1] - 55.5) < 0.6, \
        f"拆完没继承回吸过的上沿：{lsp['rect']} {rsp['rect']}"
    assert lsp["w_pt"] > 40 and rsp["w_pt"] > 40

    # 最终修边顺着横跨两图的长图注长回去：左图右沿 / 右图左沿必须夹回 split_x
    sx = float(meta["split_x"])
    grew = (rect[0], 55.5, sx + 30.0, 380.0)
    clamped = FG._clamp_side_pair(grew, lsp)
    assert clamped[2] == sx - 0.5, f"左图长过竖缝没夹回：{clamped}"
    grew_r = (sx - 30.0, 55.5, rect[2], 380.0)
    clamped_r = FG._clamp_side_pair(grew_r, rsp)
    assert clamped_r[0] == sx + 0.5, f"右图长过竖缝没夹回：{clamped_r}"
    # 反例：不是并排拆出来的图 / 题号不在这一对里 → 原样返回
    assert FG._clamp_side_pair(grew, {"q_index": 0, "rect": rect}) == grew
    assert FG._clamp_side_pair(grew, {**lsp, "q_index": 9}) == grew

    # 反例：不同大题的两题即使同高也不拆
    bad = [dict(spans[0]), {**spans[1], "section": "五"}]
    assert FG._split_side_by_side_figures([dict(base)], bad) == [base], \
        "不同大题的同高两题被拆成了并排图"


def margin_rule_cols_masks_dotted_margin():
    """页边点线/虚线装饰要整列掏掉（含五个反例）；表格竖线不许误伤。"""
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    def dotted(x0, x1):
        g = np.full((800, 1000), 255, dtype=np.uint8)
        for y in range(50, 750, 8):
            g[y:y + 3, x0:x1] = 0
        return g

    got = FG._margin_rule_cols(dotted(30, 34), k, np, 0, 1000)
    assert got and got[0][0] <= 30 and got[0][1] >= 34, f"页边点线没认出来：{got}"
    # 右页边同样要认
    gr = FG._margin_rule_cols(dotted(966, 970), k, np, 0, 1000)
    assert gr and gr[0][0] <= 966 and gr[0][1] >= 970, f"右页边点线没认出来：{gr}"

    # 反例①：内侧 6pt 内就有别的真墨（表格线贴着字/图）→ 不是孤立装饰
    g2 = dotted(30, 34)
    g2[50:750, 38:40] = 0
    assert FG._margin_rule_cols(g2, k, np, 0, 1000) == [], "贴字的表格竖线被当页边装饰"
    # 反例②：线宽 10pt（>6pt）→ 不是细点线
    assert FG._margin_rule_cols(dotted(30, 44), k, np, 0, 1000) == [], "宽线被当点线"
    # 反例③：外侧（更靠页边）还有真墨 → 不是页边装饰
    g3 = dotted(30, 34)
    g3[50:750, 20:22] = 0
    assert FG._margin_rule_cols(g3, k, np, 0, 1000) == [], "外侧有墨仍被当页边线"
    # 反例④：只有零星几个点（占高 <8%）→ 不是贯通装饰线
    g4 = np.full((800, 1000), 255, dtype=np.uint8)
    g4[50:59, 30:34] = 0
    assert FG._margin_rule_cols(g4, k, np, 0, 1000) == [], "零星墨点被当页边线"
    # 反例⑤：探测带不贴物理页边（cx0>0）→ 不看左页边
    assert FG._margin_rule_cols(dotted(30, 34), k, np, 50, 1000) == [], \
        "页内表格线被当页边装饰"


def strip_dimension_label_may_leave_stem_empty():
    """图框里只剩一个尺寸标注时，题干可以清空；汉字残句仍要留（含三个反例）。"""
    import app.extractor.figures as FG

    def run(text, bx=250.0, bt="24cm"):
        qs = [{"text": text}]
        spans = [{"q_index": 0, "page": 1,
                  "text_boxes": [{"x": bx, "y": 450.0, "w": 26.0, "h": 9.0,
                                  "text": bt}]}]
        got = {0: [{"rect": [210.0, 437.0, 380.0, 527.0]}]}
        return FG.strip_text_inside_figures(qs, spans, got), qs[0]["text"]

    n, txt = run("24cm")
    assert n == 1 and txt == "", f"最后一条尺寸标注没清掉：{n} {txt!r}"
    # 反例①：汉字残句（≥6 字）是题干，不许清空
    n2, txt2 = run("求阴影部分的面积", bt="求阴影部分的面积")
    assert txt2 == "求阴影部分的面积", f"短题干被当图注清空：{txt2!r}"
    # 反例②：光秃秃的汉字短标签（不是尺寸标注）仍按"留残渣"
    n3, txt3 = run("求面积", bt="求面积")
    assert txt3 == "求面积", f"汉字短标签被清空：{txt3!r}"
    # 反例③：标注框伸出图框外（不是整行在图里）→ 不许删
    n4, txt4 = run("24cm", bx=400.0)
    assert txt4 == "24cm", f"图框外的尺寸标注被删：{txt4!r}"


def post_crop_text_cleanup_marks_what_it_cannot_fix():
    """清字后的三件收尾：光题号、半边括号、粘来的下一题号（含反例）。"""
    import app.extractor.figures as FG
    from app.extractor.rules import trim_trailing_next_qno

    # 1) 题干只剩 "2、" 且有图 → 清空；没图 / 还有正文 → 不动
    qs = [{"text": "2、", "images": [{"name": "a.png"}]},
          {"text": "3、", "images": []},
          {"text": "4、看图列式", "images": [{"name": "b.png"}]}]
    assert FG.strip_number_only_stems(qs) == 1
    assert qs[0]["text"] == "" and qs[1]["text"] == "3、" \
        and qs[2]["text"].endswith("列式")

    # 2) 半边括号 → 标待校对；配对的不动；已有说明不覆盖
    qs2 = [{"text": "5.用分数表示是 ）", "needs_review": False},
           {"text": "6.用分数表示是（ ）"},
           {"text": "7.读作（ ）", "needs_review": True, "review_note": "别的原因"}]
    assert FG.mark_unbalanced_brackets(qs2) == 1
    assert qs2[0]["needs_review"] and "括号" in qs2[0]["review_note"]
    assert not qs2[1].get("needs_review")
    assert qs2[2]["review_note"] == "别的原因"

    # 3) 末尾粘着下一题题号 → 摘掉；同大题没有该题号 / 只有一个空格 → 不动
    qs3 = [{"section": "一", "q_no": 1, "text": "1.8÷4 读作（    3."},
           {"section": "一", "q_no": 2, "text": "2.下一题"},
           {"section": "一", "q_no": 3, "text": "3.再下一题"},
           {"section": "二", "q_no": 4, "text": "4.答：    3."},
           {"section": "二", "q_no": 5, "text": "5.答： 3."}]
    assert trim_trailing_next_qno(qs3) == 1
    assert qs3[0]["text"] == "1.8÷4 读作（"
    assert qs3[3]["text"] == "4.答：    3.", "同大题没有 3 号也被摘了"
    assert qs3[4]["text"] == "5.答： 3.", "正常句尾的 3. 被摘了"


def text_frame_with_two_full_rows_is_not_a_figure():
    """带花边的文字框（整行正文 + 细边框 + 小装饰）不是配图。

    真实卷（综合实践单元(1) p2 第 3 题）："路线一…/路线二…"两行填空指示印在
    圆角蓝框里，OCR 行框装不住边框，覆盖率 80.9% 够不着 text-block 的 85%，
    整块被裁成图从题干里删掉。反例：框里还有一栋实心楼、表格内线、只有一行字、
    一框小图标、尺寸不像文字框 —— 都必须是真图。
    """
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0

    ROUTE_TXT = ["路线一：从学校出发，先向东走到书店。",
                 "路线二：先向南走到公园，再向西到学校。"]

    def build(rows=2, with_frame=True, extra=None, box_px=None,
              sz=(200, 200), texts=None):
        g = np.full((int(sz[1] * k), int(sz[0] * k)), 255, dtype=np.uint8)
        bx0, by0, bx1, by1 = box_px or (10, 10, 170, 110)
        if with_frame:
            g[by0:by0 + 2, bx0:bx1] = 40
            g[by1 - 2:by1, bx0:bx1] = 40
            g[by0:by1, bx0:bx0 + 2] = 40
            g[by0:by1, bx1 - 2:bx1] = 40
        tb = []
        tb_txt = list(texts) if texts is not None else ROUTE_TXT[:rows]
        for i in range(rows):
            y0 = by0 + 20 + i * 35
            # 只有一行字时把这一行画高一点，让"框外墨占比"这条先放行，
            # 才能单独量"≥2 行"这条判据（否则挡住它的是占比，不是行数）。
            ink_h, box_h = (30, 34) if rows == 1 else (16, 22)
            g[y0 + 2:y0 + 2 + ink_h, bx0 + 24:bx0 + 140] = 40
            tb.append([bx0 + 20, y0, bx0 + 144, y0 + box_h])
        if rows >= 2:
            tb.append([bx0 + 20, by0 + 88, bx0 + 30, by0 + 98])   # 右下角小花
            tb_txt.append("")                    # OCR 也会给小花一行，文本对齐不能错位
            g[by0 + 88:by0 + 98, bx0 + 20:bx0 + 30] = 40
        if extra == "building":
            g[by0 + 52:by0 + 60, bx0 + 20:bx0 + 90] = 40
        elif extra == "table":
            g[by0 + 47:by0 + 48, bx0 + 30:bx0 + 130] = 40
        elif extra == "icons":
            for j in range(8):
                g[by0 + 14:by0 + 27, bx0 + 120 + j * 6:bx0 + 126 + j * 6] = 40
                g[by0 + 86:by0 + 99, bx0 + 40 + j * 6:bx0 + 46 + j * 6] = 40
        return g, tb, tb_txt, (bx0, by0, bx1, by1)

    g, tb, tx, box = build()
    assert FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "两行正文+细框被当成图"

    # 记录表：两行都是长标签但【没有句读】，哪怕字够多、框也够，也必须是图。
    # 真实卷（综合实践单元(1) p1 第 3 题）整张记录表曾被这条规则删掉。
    g, tb, tx, box = build(rows=2, texts=["一操场- (东) ( 操场一一",
                                          "艺术楼- (南) ( 艺术楼一一"])
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "记录表的标签行被当成整句正文"

    # 有句读但太短（不到 12 字）→ 也证不出是整句正文，保留成图。
    g, tb, tx, box = build(rows=2, texts=["路线一：向东。", "路线二：向南。"])
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "短句也被当成整句正文"

    # 两行里只有一行是整句 → 证不出是文字框，保留成图。
    g, tb, tx, box = build(rows=2, texts=[ROUTE_TXT[0], "艺术楼     教学楼"])
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "只有一行整句也判文字框"

    # 调用方没给 OCR 原文 → 证不出是文字框，保留成图（绝不拿几何硬猜）。
    g, tb, _, box = build()
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np), \
        "没有 OCR 原文也判文字框"

    g, tb, tx, box = build(extra="building")
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "框里还有实心楼却仍判文字框"

    g, tb, tx, box = build(extra="table")
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "表格内线被当成边框"

    g, tb, tx, box = build(rows=1)
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "只有一行字也判文字框"

    g, tb, tx, box = build(extra="icons")
    assert not FG._is_text_frame_block(list(box), g < 128, tb, k, np, tb_txt=tx), \
        "一框小图标被当成文字框"

    # 尺寸：302pt 宽已经超过文字框上限（60–260pt），哪怕形状全对也不是文字框。
    # 文字画满整个框，确保挡住它的是尺寸而不是"框外墨占比"。
    g = np.full((int(200 * k), int(400 * k)), 255, dtype=np.uint8)
    bx0, by0, bx1, by1 = 10, 10, 430, 110
    g[by0:by0 + 2, bx0:bx1] = 40
    g[by1 - 2:by1, bx0:bx1] = 40
    g[by0:by1, bx0:bx0 + 2] = 40
    g[by0:by1, bx1 - 2:bx1] = 40
    tb = []
    for i in range(2):
        y0 = by0 + 20 + i * 35
        g[y0 + 2:y0 + 18, 34:390] = 40
        tb.append([30, y0, 400, y0 + 22])
    assert not FG._is_text_frame_block([bx0, by0, bx1, by1], g < 128, tb, k, np,
                                       tb_txt=ROUTE_TXT), "超宽框仍判文字框"


def figure_preamble_questions_are_folded_into_the_next_question():
    """图前面的无题号伪题要折进真题：图并给真题、图例并进题干、伪题消失。

    真实卷（综合实践单元(1) p2）第四节/第五节：地图标注和 ①②③④ 图例被切成
    两道 q_no=None 的伪题，前端自动编成"第 1 题"，真正的第 1 题又在下面 ——
    同一大题两道 1。反例：有空的真题、正文引导语、没有图的、下一题也没题号的、
    跨大题的，一律不许折。
    """
    import app.extractor.figures as FG

    Q16 = "85018502 8506 8507 8512 8513 肉 东北"
    Q20 = "①春风小区 ②人民广场 ③长风商城 ④体育馆"
    IMG_A = [{"rect": [28.7, 132.0, 180.1, 176.5], "page": 2}]
    IMG_B = [{"rect": [246.8, 24.4, 345.8, 57.7], "page": 2}]

    qs = [
        {"q_no": None, "section": "四、应急", "text": Q16, "images": list(IMG_A)},
        {"q_no": 1, "section": "四、应急", "text": "1.酒店5层有（ ）个安全出口。", "images": []},
        {"q_no": None, "section": "五、小玉", "text": Q20, "images": list(IMG_B)},
        {"q_no": 1, "section": "五、小玉", "text": "1.根据描述，把序号填在上图。", "images": []},
        {"q_no": 2, "section": "五、小玉", "text": "2.在上图中画出路线。"},
    ]
    got = {0: qs[0]["images"], 2: qs[2]["images"]}
    spans = [{"q_index": i} for i in range(5)]
    n = FG.fold_figure_preamble_questions(qs, got, spans)
    assert n == 2, n
    assert len(qs) == 3, [q.get("q_no") for q in qs]
    assert qs[0]["text"].startswith("1.酒店5层"), qs[0]["text"]
    assert [im["rect"] for im in qs[0]["images"]] == [IMG_A[0]["rect"]]
    assert qs[0]["text"].strip() == "1.酒店5层有（ ）个安全出口。", "数字图注必须丢"
    assert qs[1]["text"].startswith(Q20), qs[1]["text"]
    assert qs[1]["text"].endswith("1.根据描述，把序号填在上图。"), "图例后面要接真题"
    assert [im["rect"] for im in qs[1]["images"]] == [IMG_B[0]["rect"]]
    assert sorted(got) == [0, 1], got
    assert [int(s["q_index"]) for s in spans] == [0, 1, 2], spans

    def fold_one(entries, g=None, sp=None):
        return FG.fold_figure_preamble_questions(entries, g, sp)

    def pair(text, q1=1, imgs=None, sec0="四", sec1="四", nxt_imgs=None):
        return [{"q_no": None, "section": sec0, "text": text,
                 "images": list(IMG_A if imgs is None else imgs)},
                {"q_no": q1, "section": sec1, "text": "1.真题。",
                 "images": list(nxt_imgs or [])}]

    # 反例①：正文引导语（不是图注）→ 保留成独立题。
    a = pair("观察下面的地图，回答问题：")
    assert fold_one(a) == 0 and len(a) == 2, "正文引导语被折进下一题"

    # 反例②：下一题也没有题号 → 可能是同组小问，不能折。
    a = pair(Q16, q1=None)
    assert fold_one(a) == 0 and len(a) == 2, "下一题没题号也折"

    # 反例③：这道伪题没有图 → 不折（可能是正常的无编号题）。
    a = pair(Q16, imgs=[])
    assert fold_one(a) == 0 and len(a) == 2, "没有图也折"

    # 反例④：带空位 → 可能是真题，不折。
    a = pair("8501 8502 8506 （ ）（ ）")
    assert fold_one(a) == 0 and len(a) == 2, "带空位的题被折"

    # 反例⑤：跨大题 → 图不能借给下一大题。
    a = pair(Q16, sec0="四", sec1="五")
    assert fold_one(a) == 0 and len(a) == 2, "跨大题也折"

    # 反例⑥：只有一个圈号（正文里的①）→ 不是图例。
    a = pair("①春风小区在学校的东面。")
    assert fold_one(a) == 0 and len(a) == 2, "正文里的单个圈号被当图例"

    # 只有 q 上挂图、没传 got/spans 也要能折（重映射是可选参数）。
    a = pair(Q16)
    assert fold_one(a) == 1 and len(a) == 1, "不带 got/spans 时折不动"


def shared_figure_trims_the_next_questions_leading_labels():
    """共享图只挂第一题：第二题自己没有图，续行行首照样压在同一张图上。

    真实卷（综合实践单元(1) p2 第三大题）：第 2 题的续行 OCR 成
    "凉亭            假山的（ )面。(4分)"，行首"凉亭"是地图标签，
    正文是"假山的（ )面"。只摘行首标签，正文一个字不许动。
    """
    import app.extractor.figures as FG
    qs = [
        {"text": "喷泉的西面是（      )，东面\n是（    )。(4分)"},
        {"text": "莲池在凉亭的（     )面，在 凉亭            假山的（     )面。(4分)"},
    ]
    spans = [
        {"q_index": 0, "page": 2, "col": 0, "text_boxes": [
            {"x": 87.1, "y": 33.8, "w": 89.8, "h": 6.3,
             "text": "东北           1.喷泉的西面是（      )，东面"},
            {"x": 53.8, "y": 44.9, "w": 103.9, "h": 6.2,
             "text": "喷泉      游乐场            是（    )。(4分)"},
            {"x": 53.8, "y": 57.1, "w": 123.6, "h": 7.2,
             "text": "莲池      假山            2.莲池在凉亭的（     )面，在"},
        ]},
        {"q_index": 1, "page": 2, "col": 0, "text_boxes": [
            {"x": 53.8, "y": 67.2, "w": 119.5, "h": 5.8,
             "text": "凉亭            假山的（     )面。(4分)"},
        ]},
    ]
    got = {0: [{"rect": [25.1, 30.7, 109.3, 80.9]}]}
    n = FG.strip_text_inside_figures(qs, spans, got)
    assert n >= 1, "第二题续行的行首地名没被摘掉"
    assert qs[1]["text"] == "莲池在凉亭的（     )面，在 假山的（     )面。(4分)", qs[1]["text"]

    # 反例①：图在另一页 —— 不能借来当"行首压在图里"的几何证据。
    qs2 = [{"text": "莲池在凉亭的（     )面，在 凉亭            假山的（     )面。(4分)"}]
    spans2 = [{"q_index": 0, "page": 3, "col": 0, "text_boxes": [
        {"x": 53.8, "y": 67.2, "w": 119.5, "h": 5.8,
         "text": "凉亭            假山的（     )面。(4分)"}]}]
    got2 = {9: [{"rect": [25.1, 30.7, 109.3, 80.9]}]}      # 图挂在第 2 页
    assert FG.strip_text_inside_figures(qs2, spans2, got2) == 0, "另一页的图被借来删字"
    assert qs2[0]["text"].startswith("莲池在凉亭的"), qs2[0]["text"]

    # 反例②：行首和后文只隔一个空格 —— 那是正文里的词，不是图注。
    qs3 = [{"text": "莲池在凉亭的（     )面，在 凉亭 假山的（     )面。(4分)"}]
    spans3 = [{"q_index": 0, "page": 2, "col": 0, "text_boxes": [
        {"x": 53.8, "y": 67.2, "w": 119.5, "h": 5.8,
         "text": "凉亭 假山的（     )面。(4分)"}]}]
    assert FG.strip_text_inside_figures(qs3, spans3, got) == 0, "单空格的行首正文被删"
    assert qs3[0]["text"] == "莲池在凉亭的（     )面，在 凉亭 假山的（     )面。(4分)", qs3[0]["text"]

    # 反例③：整行都落在邻图里，但没有"行尾伸出图外"的证据 —— 邻图只借几何给
    # "行首压在图里"这一条，不许拿它整行删字（宁可留重复，不许把题干改残）。
    qs4 = [{"text": "莲池在凉亭的（     )面。 凉亭"}]
    spans4 = [
        {"q_index": 0, "page": 2, "col": 0, "text_boxes": [
            {"x": 53.8, "y": 67.2, "w": 10.0, "h": 6.0, "text": "凉亭"}]},
        {"q_index": 9, "page": 2, "col": 0, "text_boxes": []},
    ]
    got4 = {9: [{"rect": [25.1, 30.7, 109.3, 80.9]}]}
    assert FG.strip_text_inside_figures(qs4, spans4, got4) == 0, "邻图把整行标签删了"
    assert qs4[0]["text"].endswith("凉亭"), qs4[0]["text"]


def cut_glyph_at_the_crop_edge_is_completed():
    """裁框从字中间切过：框外这一笔要接完；空白外沿、长横线一律不接。

    真实卷（综合实践单元(1) p1 第 4 题）：OCR 把图内标签"乐乐 龙龙"当正文行
    擦掉大半，候选框右沿停在 176.5pt，第二个"龙"只剩左边一竖；打印出来标签
    缺字，孩子分不出谁是谁。窄图够不到 60pt 的整栏接图门槛，需要单独这一条。
    """
    import numpy as np
    import app.extractor.figures as FG
    k = FG.DPI_PROBE / 72.0
    g = np.full((int(260 * k), int(260 * k)), 255, dtype=np.uint8)
    # 图内标签的第二笔：x 175.1–179.3，字高 6pt；框右沿 176.5 正落在中间
    g[int(216.7 * k):int(223.0 * k), int(175.1 * k):int(179.3 * k)] = 40
    src = FG.PageSource(1, 260.0, 260.0, g, lambda rect, out: None)
    rect = (118.0, 201.7, 176.5, 226.8)
    out = FG._extend_cut_glyph(rect, src, k, np, "right", 240.0)
    assert 179.2 <= out[2] <= 179.6, f"半个字没接完：{out}"
    assert out[:2] == rect[:2] and out[3] == rect[3], f"不该动其它边：{out}"
    # 反例①：框外先是空白（正常外沿）→ 一刀都不许接
    blank = (118.0, 201.7, 186.0, 226.8)
    assert FG._extend_cut_glyph(blank, src, k, np, "right", 240.0) == blank, \
        "空白外沿被当成切字"
    # 反例②：切到的是一根 1pt 高的框线（高度不像字）→ 不接
    g2 = np.full_like(g, 255)
    g2[int(210.0 * k):int(210.9 * k), int(175.5 * k):int(179.0 * k)] = 40
    src2 = FG.PageSource(1, 260.0, 260.0, g2, lambda rect, out: None)
    line = (118.0, 205.0, 176.5, 215.0)
    assert FG._extend_cut_glyph(line, src2, k, np, "right", 240.0) == line, \
        "框线被接成图"
    # 反例③：墨一直连到 6pt 上限（长横线/整行字）→ 不接
    g3 = np.full_like(g, 255)
    g3[int(208.0 * k):int(214.0 * k), int(175.0 * k):int(190.0 * k)] = 40
    src3 = FG.PageSource(1, 260.0, 260.0, g3, lambda rect, out: None)
    long_run = (118.0, 205.0, 176.5, 215.0)
    assert FG._extend_cut_glyph(long_run, src3, k, np, "right", 240.0) == long_run, \
        "连到上限的长墨被接进图里"
    # 反例④：右侧栏界就在 178pt，接完会越栏 → 放弃
    assert FG._extend_cut_glyph(rect, src, k, np, "right", 178.0) == rect, \
        "越栏界接宽"


def glyph_extension_is_wired_into_find_figures():
    """接线检查：候选阶段真的调用切字接边，且结果落到最终输出框。

    直接测 `_extend_cut_glyph` 只证明函数本身对；把调用删掉（`glyph = rect`）
    它照样全绿。这里用 spy 把右沿 +12pt，输出必须真的跟着变宽。
    """
    import app.extractor.figures as FG
    src = _src_from_bands(400, 200, [(30, 60, 380, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 400.0,
              "text_boxes": [{"x": 20, "y": 45, "w": 180, "h": 6,
                              "text": "1.看图填空。"}]}]
    real = FG._extend_cut_glyph
    calls = []

    def spy(rect, src_, k_, np_, side, limit):
        calls.append(tuple(rect))
        return (rect[0], rect[1], rect[2] + 12.0, rect[3])

    FG._extend_cut_glyph = spy
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._extend_cut_glyph = real
    imgs = got.get(0) or []
    assert calls and imgs, f"切字接边根本没跑：calls={calls}, rep={rep}"
    assert imgs[0]["rect"][2] >= 390.0, \
        f"切字接边的结果没落到输出框：{imgs[0]['rect']} vs {calls[0]}"
    assert any(x.get("why") == "glyph-extended" for x in rep), \
        f"报告里没留下 glyph-extended：{rep}"


def _window_bands(fig_x0=140, fig_x1=220, fig_y0=30, fig_y1=110):
    return [(fig_x0, fig_y0, fig_x0 + 2, fig_y1, 40),
            (fig_x1 - 2, fig_y0, fig_x1, fig_y1, 40),
            (fig_x0, fig_y0, fig_x1, fig_y0 + 2, 40),
            (fig_x0, fig_y1 - 2, fig_x1, fig_y1, 40)]


def left_text_tail_is_trimmed_only_between_text_and_figure():
    """裁框左沿从长题干行中间切过：收到文字与图之间的竖缝（含四个反例）。

    真实卷（海淀六上 2024 p4 第 13 题）：题干第二行横穿裁框，图里印着
    半句题干。只认"长正文行 + 全高空白竖缝 + 缝右真有图"。
    """
    import app.extractor.figures as FG
    bands = _window_bands() + [(20, 60, 132, 72, 40)]
    src = _src_from_bands(240, 140, bands)
    boxes = [{"x": 20, "y": 60, "w": 115, "h": 12,
              "text": "下面是长方形，这扇窗户的面积是（    ）平方米。"}]
    got = FG._trim_left_text_tail((20.0, 50.0, 230.0, 120.0), boxes,
                                  src, None, FG.DPI_PROBE / 72.0)
    assert abs(got[0] - 132.5) < 1.0, f"左沿没收在文字与图之间：{got}"
    assert got[1:] == (50.0, 230.0, 120.0), f"只许动左沿：{got}"
    # 反例①：左段有一根贯穿全高的表格竖线 → 是表格左栏，不是文字尾巴
    table = _src_from_bands(240, 140, bands + [(70, 30, 72, 110, 40)])
    got = FG._trim_left_text_tail((20.0, 50.0, 230.0, 120.0), boxes,
                                  table, None, FG.DPI_PROBE / 72.0)
    assert got == (20.0, 50.0, 230.0, 120.0), f"表格左栏被当文字尾巴切了：{got}"
    # 反例②：缝右只剩 25pt 宽 → 切了就是把图裁没
    got = FG._trim_left_text_tail((20.0, 50.0, 165.0, 120.0), boxes,
                                  src, None, FG.DPI_PROBE / 72.0)
    assert got == (20.0, 50.0, 165.0, 120.0), f"窄图被切：{got}"
    # 反例③：缝右什么都没有（纯页边空白）→ 不动
    blank_right = _src_from_bands(240, 140, [(20, 60, 132, 72, 40),
                                             (200, 30, 202, 110, 40)])
    got = FG._trim_left_text_tail((20.0, 50.0, 230.0, 120.0), boxes,
                                  blank_right, None, FG.DPI_PROBE / 72.0)
    assert got == (20.0, 50.0, 230.0, 120.0), f"右侧没图也切：{got}"
    # 反例④：短标签行（<12 字）不算横穿题干
    short = [{"x": 20, "y": 60, "w": 115, "h": 12, "text": "面积是（ ）平方米。"}]
    got = FG._trim_left_text_tail((20.0, 50.0, 230.0, 120.0), short,
                                  src, None, FG.DPI_PROBE / 72.0)
    assert got == (20.0, 50.0, 230.0, 120.0), f"短标签被当正文切：{got}"


def small_figure_grows_over_a_cut_band_only_into_ink():
    """矮块图的上下沿切在图形中间：沿连续墨迹长回真边（含四个反例）。"""
    import app.extractor.figures as FG
    sides = [(120, 30, 122, 130, 40), (180, 30, 182, 130, 40),
             (120, 48, 182, 50, 40)]
    src = _src_from_bands(240, 160, sides)
    k = FG.DPI_PROBE / 72.0
    got = FG._grow_small_figure_over_band((118.0, 60.0, 184.0, 118.0),
                                          src, [], None, k)
    assert abs(got[1] - 29.5) < 1.0, f"上沿没长回图形顶：{got}"
    assert abs(got[3] - 130.5) < 1.0, f"下沿没长回图形底：{got}"
    # 反例①：长出去的带子里有长正文行 → 不许吞上一题题干
    boxes = [{"x": 20, "y": 25, "w": 162, "h": 12,
              "text": "1.下面图形中，不是轴对称图形的是（        ）"}]
    got = FG._grow_small_figure_over_band((118.0, 40.0, 184.0, 68.0),
                                          src, boxes, None, k)
    assert got[1] == 40.0, f"长进了上一题题干：{got}"
    # 反例②：高图（>60pt）不试 —— 高图试验吞过上一题，整体回滚过
    tall = _src_from_bands(240, 220, sides)
    got = FG._grow_small_figure_over_band((118.0, 20.0, 184.0, 118.0),
                                          tall, [], None, k)
    assert got == (118.0, 20.0, 184.0, 118.0), f"高图也长了：{got}"
    # 反例③：框沿这一行没有墨（图在框内，没被切）→ 上沿不长
    got = FG._grow_small_figure_over_band((118.0, 25.0, 184.0, 78.0),
                                          src, [], None, k)
    assert got[1] == 25.0, f"没被切也长上沿：{got}"
    assert got[3] > 78.0, f"下沿切到了却没长：{got}"


def cross_graze_content_floor_keeps_the_upper_figures_border():
    """收上题底沿时按上题自己的墨停：方格图底框线不许被削（含两个反例）。"""
    import app.extractor.figures as FG
    src = _src_from_bands(240, 170, [
        (30, 96, 110, 98, 40),          # 上题方格图的底框线（到 97.5）
        (165, 98, 167, 140, 40),        # 下题窗户左竖线（从 98 起）
        (200, 98, 202, 140, 40),        # 下题窗户右竖线
    ])
    a = {"q_index": 0, "page": 1, "rect": (20.0, 60.0, 210.0, 108.0), "src": src}
    b = {"q_index": 1, "page": 1, "rect": (165.0, 98.0, 210.0, 140.0)}
    got = FG._trim_cross_question_graze([a, b], None)
    assert got[0]["rect"][3] >= 98.0, \
        f"上题底框线被削掉了（应收在下题顶沿之上、但留出自己的框线）：{got[0]['rect']}"
    assert got[0]["rect"][3] <= 99.0, f"没收：{got[0]['rect']}"
    # 反例①：上题自己的墨一直到底沿 → 收不动，保持原样
    full = _src_from_bands(240, 170, [(30, 100, 110, 108, 40),
                                      (165, 98, 167, 140, 40)])
    a2 = {"q_index": 0, "page": 1, "rect": (20.0, 60.0, 210.0, 108.0), "src": full}
    b2 = {"q_index": 1, "page": 1, "rect": (165.0, 98.0, 210.0, 140.0)}
    got = FG._trim_cross_question_graze([a2, b2], None)
    assert got[0]["rect"][3] == 108.0, f"上题自己的内容被削：{got[0]['rect']}"
    # 反例②：没有像素（旧夹具）→ 退回"下题顶沿 -0.5"的旧行为
    a3 = {"q_index": 0, "page": 1, "rect": (33.7, 150.2, 181.6, 207.5)}
    b3 = {"q_index": 1, "page": 1, "rect": (118.0, 201.7, 176.5, 226.8)}
    got = FG._trim_cross_question_graze([a3, b3], None)
    assert abs(got[0]["rect"][3] - 201.2) < 0.6, f"旧行为被改了：{got[0]['rect']}"


def left_tail_trim_is_wired_into_find_figures():
    """接线检查：左沿文字尾巴这一刀真的跑在 find_figures 里。"""
    import app.extractor.figures as FG
    src = _src_from_bands(200, 200, [(20, 60, 120, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 200.0,
              "text_boxes": [{"x": 20, "y": 55, "w": 130, "h": 6,
                              "text": "1.看图填空。"}]}]
    real = FG._trim_left_text_tail
    calls = []

    def spy(rect, boxes, src_, np_, k_):
        calls.append(tuple(rect))
        return (rect[0] + 30.0, rect[1], rect[2], rect[3])

    FG._trim_left_text_tail = spy
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._trim_left_text_tail = real
    imgs = got.get(0) or []
    assert calls and imgs, f"左沿那刀根本没跑：calls={calls}, rep={rep}"
    assert imgs[0]["rect"][0] >= calls[0][0] + 29.0, \
        f"修边结果没落到输出框：{imgs[0]['rect']} vs {calls[0]}"
    assert any(x.get("why") == "left-tail-trim" for x in rep), \
        f"报告里没留下 left-tail-trim：{rep}"


def band_grow_is_wired_into_find_figures():
    """接线检查：矮块图长回真边这一刀真的跑在 find_figures 里。"""
    import app.extractor.figures as FG
    src = _src_from_bands(200, 200, [(20, 60, 120, 140, 40)])
    spans = [{"q_index": 0, "page": 1, "col": 0, "y0": 50.0, "y1": 160.0,
              "x0": 0.0, "x1": 200.0,
              "text_boxes": [{"x": 20, "y": 55, "w": 130, "h": 6,
                              "text": "1.看图填空。"}]}]
    real = FG._grow_small_figure_over_band
    calls = []

    def spy(rect, src_, boxes, np_, k_):
        calls.append(tuple(rect))
        return (rect[0], rect[1] - 10.0, rect[2], rect[3])

    FG._grow_small_figure_over_band = spy
    rep = []
    try:
        got = FG.find_figures({1: src}, spans, OUT, report=rep)
    finally:
        FG._grow_small_figure_over_band = real
    imgs = got.get(0) or []
    assert calls and imgs, f"长回真边根本没跑：calls={calls}, rep={rep}"
    assert imgs[0]["rect"][1] <= calls[0][1] - 9.0, \
        f"长回的结果没落到输出框：{imgs[0]['rect']} vs {calls[0]}"
    assert any(x.get("why") == "band-grow" for x in rep), \
        f"报告里没留下 band-grow：{rep}"


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
    ("整题原图已含题号：不许再印孤立的题号", whole_span_question_number_is_not_printed_twice),
    ("统计表横串：整题截图 + 清空串行 + 切页脚", table_garbage_gets_whole_span_and_drops_footer),
    ("小问号全丢：整题截图代替三段残句", lost_subq_numbers_use_whole_span),
    ("缺一个小问号：整题截图（含三个反例）", partially_lost_subq_number_uses_whole_span),
    ("分数被拍平 310/410：整题截图（含三个反例）", flattened_fraction_gets_whole_span),
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
    ("裁框下沿不许吞掉本题末行题干（含九个反例）", crop_bottom_edge_does_not_swallow_the_stem_last_line),
    ("下沿裁题干接线检查（真实裁图链路）", stem_bottom_clip_is_wired_into_find_figures),
    ("裁框上沿不许吞掉题干第二行（含三个反例）", crop_top_edge_does_not_swallow_the_stem_second_line),
    ("裁框上沿从起手句中间切过也要收（含四个反例）",
     crop_top_edge_cuts_through_the_stem_first_line),
    ("窄图的题干行字尾要收（含四个反例）", crop_top_edge_narrow_tail_of_a_long_stem_row),
    ("正文右端字尾的窄条不是配图（含四个反例）", text_edge_fragment_is_not_a_figure),
    ("裁框上沿不许吞掉图内标注（非第一行须贴左沿）", crop_top_edge_skips_figure_labels_inside_the_picture),
    ("栏目横幅与答题框行不许当配图", banner_and_answer_boxes_are_not_figures),
    ("家具行占比/答题框判据的反例（真图不许砍）", junk_crop_measures_keep_real_figures),
    ("空白作答行与连成一块的答题框（含反例）", answer_blanks_and_merged_squares_are_not_figures),
    ("空白作答横线不许当配图", blank_answer_rules_are_not_figures),
    ("两个作答圆圈不许当配图（含反例与接线）", answer_circles_are_not_figures),
    ("多行文字残影不许当配图（含反例与接线）", text_covered_block_is_not_a_figure),
    ("合并后长出来的文字块要按最终框复检（含反例）", merged_text_block_is_rechecked),
    ("图内重复文字要从题干里删掉（含反例）", text_inside_figures_is_removed_from_stem),
    ("题干第一行接进整题原图（含三个反例）", stem_line_above_is_joined_into_whole_question_image),
    ("行框题号归一化：带题号与去题号两版都试",
     box_text_patterns_also_tries_without_the_question_number),
    ("题干残渣清理接线检查", residue_cleanup_is_wired_into_the_pipeline),
    ("题顶紧贴的小太阳要随图裁进来（含九个反例）", top_growth_pulls_a_small_icon_above_the_question),
    ("太阳上沿接线检查（真实文字层）", sun_above_the_figure_is_kept_end_to_end),
    ("虚线作答区只剔框线，不剔框边的圆点和真图（含九个反例）", blank_dashed_answer_areas_are_stripped),
    ("跨题缝合：接缝要有贯穿笔画，同宽薄片例外（含四个反例）", seam_crossing_and_sliver_rules_are_sound),
    ("虚线作答区剔除接线检查（真实裁图链路）", blank_area_strip_is_wired_into_find_figures),
    ("家具行判据接线检查（含丢弃原因）", banner_rule_is_wired_into_find_figures),
    ("栏目横幅接线（真实文字层）", banner_rule_wiring_end_to_end),
    ("图形算式整行原图：一排字符级图标不许被切成碎片（含五个反例）",
     graphic_equation_block_is_one_original_row),
    ("图形算式接线：真 PDF 上整行成图、题干加说明（含反例）",
     graphic_equation_is_cropped_as_one_original_row),
    ("算式各部分名称的竖排图要整块成图（含五个反例）", term_diagram_block_is_one_original_picture),
    ("竖排图接线：整块裁图并补专用说明", term_diagram_is_cropped_and_note_is_added),
    ("连一连的匹配版式要整块成图（含五个反例）", match_layout_block_is_one_original_picture),
    ("匹配版式接线：整块裁图并补专用说明", match_layout_is_cropped_and_note_is_added),
    ("整题截图的成句判据（含反例）", echo_full_sentence_needs_a_real_sentence_in_the_stem),
    ("整题截图只留图：切掉题干文字块（含五个反例）", stem_screenshot_trim_keeps_only_the_figure),
    ("整题截图只认高块，气泡/说明框不许整框丢（含三档边界）",
     short_text_blocks_are_not_whole_question_screenshots),
    ("整题截图要在削题干行之前丢（接线检查）",
     whole_question_screenshot_is_dropped_before_the_stem_row_is_clipped),
    ("横向切半的题干行也占干净区（整题截图不许留半截）",
     partially_covered_stem_rows_block_the_clean_region),
    ("数轴图：先收下沿题干行再判截图（含顺序反例）",
     number_line_below_a_stem_row_is_not_a_screenshot),
    ("整题截图的答题格碎片要跟着丢（含三个反例）",
     screenshot_fragments_are_dropped_with_the_screenshot),
    ("页边扫描压痕不许当配图（含四条反例）", page_edge_scan_band_is_not_a_figure),
    ("栏界切断的框线要接回来（含三个反例）", edge_ink_extension_reconnects_a_cut_border),
    ("地图短标签只摘行首图注，题干正文不动（含四个反例）", map_label_tokens_keep_the_stem_body),
    ("图文同排切分停在正文之前（含纯正文反例）", side_text_split_stops_before_the_stem_body),
    ("裁框只切到半个字：上下沿要收（含贴墨反例）", sliver_text_rows_are_trimmed_only_with_a_gap),
    ("页边竖排密封线要裁掉（含四个反例）", seal_strip_at_page_edge_is_clipped),
    ("密封字按真实字号认列，散落地图标签不许当列", seal_column_accepts_real_glyph_sizes_and_rejects_scatter),
    ("密封字左边那条竖虚线要找到并切在它左边（含四个反例）", seal_dashed_rule_is_found_and_cut),
    ("页脚不许被当成图注吸进裁框（含真图注反例）", footer_is_never_absorbed_as_a_bottom_label_row),
    ("题干行右端并着的图注要随整行并进图框（含三个反例）",
     right_edge_label_fused_into_a_stem_line_is_absorbed),
    ("骑在侧沿上的行尾图注要横向让出来（含两个反例）",
     side_label_fused_into_a_stem_line_is_absorbed),
    ("两段序号标签行也要把下沿放下去（含题干反例）",
     two_token_label_row_is_recognised_and_extended),
    ("图文同排收窄后题干只摘图注（正文必须留）", side_split_stem_cleanup_keeps_the_body),
    ("图文同排切分接线检查（含跳过接宽）", side_split_is_wired_into_find_figures),
    ("最后修边接线检查（edge-trim）", final_edge_trim_is_wired_into_find_figures),
    ("密封线裁切接线检查（edge-trim）", seal_strip_clip_is_wired_into_find_figures),
    ("窄条字尾复检接线检查（text-edge）", text_edge_drop_is_wired_into_find_figures),
    ("图注形状判据（含正反样例）", diagram_label_shape_has_hard_counter_examples),
    ("选项行伸进图框：图里的短标签要摘掉（含四个反例）", map_labels_in_option_rows_are_trimmed),
    ("整行跨在图框里的图注不算题干（含反例）", diagram_row_straddling_the_crop_is_not_stem),
    ("题干首行只丢图注、正文必须留（含三个反例）", first_stem_line_only_loses_its_map_labels),
    ("裁框从表格行中间切过：整行连表头并进图（含三个反例）", figure_top_grows_over_a_cut_table_row),
    ("图注生长不许越过本题区间（含正反例）", figure_edge_grow_respects_the_question_band),
    ("图下的选项行不裁进图里重复（含正反例）", options_row_below_a_figure_is_not_absorbed),
    ("图形侧边的尺寸标注要横向长进图（含四个反例）", figure_side_grows_over_a_dimension_label),
    ("并整行图注接线检查（label-grow）", label_grow_is_wired_into_find_figures),
    ("跨题图只蹭进几个点：收上题底沿（含三个反例）", cross_question_graze_trims_the_upper_figure),
    ("跨题蹭边收回接线检查（cross-graze）", cross_graze_trim_is_wired_into_find_figures),
    ("裁框左沿切进题干长行：收到文字与图之间（含四个反例）",
     left_text_tail_is_trimmed_only_between_text_and_figure),
    ("矮图上下沿切在图形中间：沿连续墨迹长回真边（含四个反例）",
     small_figure_grows_over_a_cut_band_only_into_ink),
    ("收上题底沿按上题自己的墨停（含两个反例）",
     cross_graze_content_floor_keeps_the_upper_figures_border),
    ("左沿文字尾巴接线检查（left-tail-trim）",
     left_tail_trim_is_wired_into_find_figures),
    ("矮图长回真边接线检查（band-grow）", band_grow_is_wired_into_find_figures),
    ("续行行首落在图里：只摘地名、正文要留（含两个反例）",
     leading_map_labels_on_a_continuation_line_are_trimmed),
    ("共享图被题界切成两块：同左沿要缝回一张（含五个反例）",
     figure_split_along_the_same_left_edge_is_stitched),
    ("叠缝里夹着题干行：两块不许缝（含短题号正例）",
     long_text_line_between_overlapping_blocks_blocks_the_stitch),
    ("并排两问共用看图区间：兜底按中线空白竖缝切开（含两个反例）",
     side_by_side_questions_share_a_look_at_the_picture_band),
    ("看图兜底的中线切分接线检查（side-split）",
     side_split_fallback_is_wired_into_attach_span_fallbacks),
    ("算式大题碎片图换整题截图（含四个反例）",
     calc_span_fallback_replaces_fragment_images),
    ("方框被 OCR 吞掉的比较题换整题截图（含三个反例）",
     lost_box_fill_question_gets_whole_span),
    ("OCR 拍平的算式换整题截图（含三个反例）",
     garbled_formula_gets_whole_span),
    ("行内卡片被吞/分数被拍平：换整题截图（含两个反例）",
     inline_gap_and_lost_fraction_get_whole_span),
    ("算式整题截图切掉大题标题/页脚/空白（含看图题反例）",
     calc_span_drops_section_heading_and_footer),
    ("页底整题截图要补下一页续图（含三个反例）",
     page_bottom_whole_span_gets_next_page_continuation),
    ("跨页题号题标题落在上一页页底：要并进整题图（含三个反例）",
     cross_page_title_line_joins_the_whole_span),
    ("画统计图：数据表+空白坐标纸整块截图（含反例）",
     chart_drawing_question_gets_whole_region_and_continuation),
    ("复杂题跨栏跨页：每栏一张完整图（含缺页反例）",
     complex_question_gets_one_region_per_column_and_page),
    ("并排两小题：配对与贯通空白竖缝（含六个反例）",
     side_pairs_and_gutter_find_the_real_split),
    ("并排图拆框：切穿图注回吸 + 最终修边夹回竖缝（含三个反例）",
     side_pair_split_absorbs_cut_label_and_clamps_edges),
    ("页边点线装饰整列掏掉（含五个反例）", margin_rule_cols_masks_dotted_margin),
    ("图里只剩尺寸标注：题干可清空（含三个反例）",
     strip_dimension_label_may_leave_stem_empty),
    ("清字收尾：光题号/半边括号/粘来的下一题号（含反例）",
     post_crop_text_cleanup_marks_what_it_cannot_fix),
    ("带花边的文字框不是配图（含九个反例）", text_frame_with_two_full_rows_is_not_a_figure),
    ("图前伪题折进下一题（含六个反例）",
     figure_preamble_questions_are_folded_into_the_next_question),
    ("共享图后一题没有自己的图：续行行首地名也要摘（含三个反例）",
     shared_figure_trims_the_next_questions_leading_labels),
    ("裁框从字中间切过：框外这一笔要接完（含四个反例）",
     cut_glyph_at_the_crop_edge_is_completed),
    ("切字接边接线检查（glyph-extend）", glyph_extension_is_wired_into_find_figures),
]
for name, fn in CASES:
    t(name, fn)

shutil.rmtree(OUT, ignore_errors=True)
print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
