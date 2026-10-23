"""V1.1 后半程的离线测试：A3 对开版式 + 题目配图裁剪 + 校对增删题。

这三样都是"看代码以为对、必须真跑一遍才知道对不对"的东西：
  · A3 对开要验证的是【1:1 不缩放】和【页码按 A4 面数】，不是"能出个横版"；
  · 配图要验证裁出来的图【真的有墨】，不是只生成了一个文件；
  · 增删题要验证 uid/题号重排后【标准答案不失联】。
"""
from __future__ import annotations

import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                     # noqa: E402
from app.layout.options import LayoutOptions, MM, A4_W                   # noqa: E402
from app.layout.engine import build_layout                         # noqa: E402
from app.papers.pdf_writer import render_pdf, ensure_fonts         # noqa: E402
from app.papers.answer_writer import render_answers_pdf            # noqa: E402
from app.extractor.lines import annotated_lines_from_pdf, spans_for_questions   # noqa: E402
from app.extractor.figures import find_figures, page_source_from_pdf            # noqa: E402
from app.extractor.rules import extract, flatten_questions         # noqa: E402
from app.storage import db                                         # noqa: E402

ok_n = bad_n = 0
OUT = os.path.join(ROOT, "var", "_formats")
os.makedirs(OUT, exist_ok=True)

LINES = [
    "第三单元 过关练习",
    "一、填空题",
    "1. 看图列式，图中有几个圆点？算式是（  ）",
    "2. 下面哪个数最大？（  ）",
]


def t(name, fn):
    global ok_n, bad_n
    try:
        fn(); ok_n += 1; print("  PASS " + name)
    except AssertionError as e:
        bad_n += 1; print(f"  FAIL {name} → {e}")
    except Exception as e:
        import traceback
        bad_n += 1; print(f"  ERROR {name} → {type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")


def make_paper_with_figure() -> str:
    """造一份【带图形】的试卷：文字行之间画一圈圆点，模拟"看图列式"的图。"""
    path = os.path.join(OUT, "带图卷.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for i, ln in enumerate(LINES):
        page.insert_text((50, y), ln, fontname="china-s", fontsize=12)
        y += 24
        if i == 2:                      # 第 1 题下面画 5 个圆点（图形区域）
            for k in range(5):
                r = pymupdf.Rect(70 + k * 26, y, 86 + k * 26, y + 16)
                page.draw_circle(r.tl + (8, 8), 8, color=(0, 0, 0), width=1.2)
            y += 40
    doc.save(path)
    doc.close()
    first = next(l.strip() for l in pymupdf.open(path)[0].get_text().splitlines() if l.strip())
    assert first.startswith("第三单元"), f"夹具行序不对：{first!r}"
    return path


print("\n[A3 对开版式]")


def a3_spread_mode_a():
    ensure_fonts()
    src = pymupdf.open(make_paper_with_figure())
    pages = [{"page_no": 1, "is_scan": False, "landscape": False,
              "w_pt": 595, "h_pt": 842, "rendered_image": None,
              "blocks": [{"kind": "text", "text": "\n".join(LINES), "x": 0, "y": 0}]}]
    parsed = {"pages": pages, "title": "带图卷"}
    a4 = LayoutOptions(font_size=12, page_format="a4")
    m4 = build_layout(parsed["pages"], a4, title="带图卷")
    r4 = render_pdf(m4, a4, os.path.join(OUT, "a4.pdf"), title="带图卷")
    a3 = LayoutOptions(font_size=12, page_format="a3_spread")
    m3 = build_layout(parsed["pages"], a3, title="带图卷")
    r3 = render_pdf(m3, a3, os.path.join(OUT, "a3.pdf"), title="带图卷")
    d4, d3 = pymupdf.open(r4["path"]), pymupdf.open(r3["path"])
    s4 = {(round(p.rect.width), round(p.rect.height)) for p in d4}
    s3 = {(round(p.rect.width), round(p.rect.height)) for p in d3}
    txt3 = "\n".join(p.get_text() for p in d3)
    n4, n3 = d4.page_count, d3.page_count
    d4.close(); d3.close()
    assert s4 == {(595, 842)}, s4
    assert s3 == {(1191, 842)}, f"A3 横版应是 1191×842pt，实际 {s3}"
    assert n3 == (n4 + 1) // 2, f"页数没减半：A4 {n4} 页 → A3 {n3} 页"
    assert "过关练习" in txt3 and "算式" in txt3, "对开后文字丢了"
    # 对开不能缩字：同一行文字在两种版式里的字号必须一致
    d3 = pymupdf.open(r3["path"])
    sizes = {round(sp["size"], 1) for pg in d3 for blk in pg.get_text("dict")["blocks"]
             if blk.get("type") == 0 for ln in blk["lines"] for sp in ln["spans"]}
    d3.close()
    assert 12.0 in sizes, f"对开把字缩小了？出现的字号 {sizes}"
t("模式 A：A3 横版 = 两个 A4 1:1 并排", a3_spread_mode_a)


def a3_page_numbering():
    """页码必须按 A4 面数：一张 A3 上要有"第1页/共4页"和"第2页/共4页"。"""
    ensure_fonts()
    many = {"pages": [{"page_no": i + 1, "is_scan": False, "landscape": False,
                       "w_pt": 595, "h_pt": 842, "rendered_image": None,
                       "blocks": [{"kind": "text", "x": 0, "y": 0,
                                   "text": "\n".join(f"第 {i+1} 段 题目内容 " * 40)}]}
                      for i in range(6)], "title": "多页"}
    opt = LayoutOptions(font_size=12, page_format="a3_spread")
    model = build_layout(many["pages"], opt, title="多页")
    r = render_pdf(model, opt, os.path.join(OUT, "a3many.pdf"), title="多页")
    d = pymupdf.open(r["path"])
    pages = [p.get_text() for p in d]
    n_a3 = d.page_count
    d.close()
    # 对照：同样的内容按 A4 出几页，对开后页码就必须数到几
    a4opt = LayoutOptions(font_size=12, page_format="a4")
    a4model = build_layout(many["pages"], a4opt, title="多页")
    n_a4 = len(a4model["pages"])
    assert n_a3 == (n_a4 + 1) // 2, (n_a4, n_a3)
    joined = "\n".join(pages)
    labels, totals = [], set()
    for m in re.finditer(r"第 (\d+) 页 / 共 (\d+) 页", joined):
        labels.append(int(m.group(1)))
        totals.add(int(m.group(2)))
    labels = sorted(set(labels))
    assert labels == list(range(1, n_a4 + 1)), f"A4 有 {n_a4} 页，对开页码却是 {labels}"
    assert totals == {n_a4}, f"两张 A3 上标的总页数不一致：{totals}（应为 {n_a4}）"
t("A3 对开的页码按 A4 面数", a3_page_numbering)


def a3_spread_mode_bc():
    """做题/批改导出也要能出 A3（家长打印出来给孩子手写也要同样版式）。"""
    qs = [{"uid": f"q{i}", "q_no": i, "auto_no": i, "section": "一、填空", "qtype": "fill",
           "text": f"第{i}题 算一算（  ）", "options": [], "blanks": 1, "score": 1.0}
          for i in range(1, 9)]
    a4 = LayoutOptions(font_size=12, page_format="a4")
    r4 = render_answers_pdf(qs, a4, os.path.join(OUT, "b_a4.pdf"), title="B版",
                            mode="answered", answers={q["uid"]: "6" for q in qs})
    a3 = LayoutOptions(font_size=12, page_format="a3_spread")
    r3 = render_answers_pdf(qs, a3, os.path.join(OUT, "b_a3.pdf"), title="B版",
                            mode="answered", answers={q["uid"]: "6" for q in qs})
    d4, d3 = pymupdf.open(r4["path"]), pymupdf.open(r3["path"])
    s3 = {(round(p.rect.width), round(p.rect.height)) for p in d3}
    t3 = "\n".join(p.get_text() for p in d3)
    n4, n3 = d4.page_count, d3.page_count
    d4.close(); d3.close()
    assert s3 == {(1191, 842)}, s3
    assert n3 == (n4 + 1) // 2, (n4, n3)
    assert "第8题" in t3.replace("\n", ""), "对开后题目被吃掉"
    assert r3.get("page_format") == "a3_spread"
t("模式 B/C 也支持 A3 对开", a3_spread_mode_bc)


def two_up_still_shrinks():
    """反例：2 合 1 是缩印，不能因为加了 A3 就把两种版式混成一个。"""
    ensure_fonts()
    pages = [{"page_no": 1, "is_scan": False, "landscape": False, "w_pt": 595, "h_pt": 842,
              "rendered_image": None,
              "blocks": [{"kind": "text", "x": 0, "y": 0, "text": "题 " * 400}]}]
    opt = LayoutOptions(font_size=12, page_format="a4_2up")
    assert opt.two_up is True and opt.is_spread is False
    m = build_layout(pages, opt, title="t")
    r = render_pdf(m, opt, os.path.join(OUT, "2up.pdf"), title="t")
    d = pymupdf.open(r["path"])
    s = {(round(p.rect.width), round(p.rect.height)) for p in d}
    d.close()
    assert s == {(595, 842)}, f"2 合 1 应该还是 A4，实际 {s}"
t("2 合 1 与 A3 对开互不串（反例）", two_up_still_shrinks)


print("\n[题目配图]")


def figures_are_cut():
    path = make_paper_with_figure()
    r = annotated_lines_from_pdf(path)
    assert r["lines"], "没读到行"
    res = extract(r["lines"], title="带图卷")
    qs = flatten_questions(res)
    spans = spans_for_questions(r["ann"], qs)
    assert spans, "没算出题目区间"
    sources = {int(s["page"]): page_source_from_pdf(path, int(s["page"])) for s in spans}
    out = os.path.join(OUT, "figs")
    shutil.rmtree(out, ignore_errors=True)
    got = find_figures(sources, spans, out)
    assert got, "一道题的图都没裁出来——看图列式的题会没法做"
    qi, imgs = sorted(got.items())[0]
    im = imgs[0]
    fp = os.path.join(out, im["name"])
    assert os.path.isfile(fp) and os.path.getsize(fp) > 500, f"图太小/不存在：{fp}"
    d = pymupdf.open(fp) if fp.endswith(".pdf") else None
    import numpy as np
    pix = pymupdf.Pixmap(fp)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    dark = int((arr[:, :, 0] < 128).sum())
    assert dark > 200, f"裁出来的图是空白的（墨点 {dark}）"
    assert im["w_pt"] > 40 and im["h_pt"] > 8, im
    print(f"       （第 {qi+1} 题裁出 {im['w_pt']}×{im['h_pt']}pt，暗像素 {dark}）")
t("图形区域被裁成图片挂到题目上", figures_are_cut)


def figures_not_attached_to_text_only():
    """反例：纯文字题不该被配上图（否则每道题下面都挂一张"墨块"，卷面全是废图）。"""
    path = os.path.join(OUT, "纯文字卷.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for ln in ["一、填空", "1. 3+4=（  ）", "2. 5×6=（  ）", "3. 9-2=（  ）"]:
        page.insert_text((50, y), ln, fontname="china-s", fontsize=12)
        y += 26
    doc.save(path); doc.close()
    r = annotated_lines_from_pdf(path)
    qs = flatten_questions(extract(r["lines"], "t"))
    spans = spans_for_questions(r["ann"], qs)
    out = os.path.join(OUT, "figs2")
    shutil.rmtree(out, ignore_errors=True)
    got = find_figures({int(s["page"]): page_source_from_pdf(path, int(s["page"])) for s in spans},
                       spans, out)
    assert not got, f"纯文字卷被裁出了 {sum(len(v) for v in got.values())} 张废图"
t("纯文字题不配图（反例）", figures_not_attached_to_text_only)


print("\n[校对：增 / 删 / 重排]")


def add_and_delete_questions():
    tmp = os.path.join(ROOT, "var", "_t_fmt")
    os.makedirs(tmp, exist_ok=True)
    db.DB_PATH = os.path.join(tmp, "t.db")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(db.DB_PATH + suf):
            os.remove(db.DB_PATH + suf)
    db.init()
    pid = db.create_paper("校对流")
    db.replace_questions(pid, [{"q_no": i, "auto_no": i, "section": "一、填空", "qtype": "fill",
                                "text": f"第{i}题（  ）", "options": [], "blanks": 1, "score": 1.0}
                               for i in range(1, 4)])
    qs = db.get_questions(pid)
    key = {q["uid"]: "6" for q in qs}
    db.save_key(pid, key)
    mid = qs[1]["uid"]
    added = db.add_question(pid, {"section": "一、填空", "qtype": "fill",
                                  "text": "我补的一道题（  ）", "blanks": 1, "score": 2.0}, mid)
    after = db.get_questions(pid)
    assert len(after) == 4, [q["text"] for q in after]
    assert [q["text"][:5] for q in after].index("我补的一道") == 2, "新题没插在指定位置后面"
    assert added["confidence"] == 1.0 and not added["needs_review"], "人工新增的题不该标待校对"
    assert [q["auto_no"] for q in after] == [1, 2, 3, 4], [q["auto_no"] for q in after]
    # 老答案必须还在（uid 不重排）
    assert all(q["uid"] in db.latest_key(pid) for q in qs), "加题后标准答案失联"
    # 删掉中间一题：序号重排，其余 uid 不变
    victim = after[1]["uid"]
    assert db.delete_question(pid, victim) == 1, "删题返回 0，没删掉"
    left = db.get_questions(pid)
    assert [q["auto_no"] for q in left] == [1, 2, 3], [q["auto_no"] for q in left]
    assert victim not in [q["uid"] for q in left]
    # 原有三题的答案必须一条不丢（新补的那题本来就没答案，不能算失联）
    for q in qs:
        assert q["uid"] in db.latest_key(pid), f"加题/删题后标准答案失联：{q['uid']}"
    assert all(q["uid"] in db.latest_key(pid) for q in left if q["uid"] in key)
    # 删不属于本卷的题必须失败，不能误删
    other = db.create_paper("另一卷")
    db.replace_questions(other, [{"q_no": 1, "section": "一", "qtype": "fill", "text": "x", "options": []}])
    ouid = db.get_questions(other)[0]["uid"]
    assert db.delete_question(pid, ouid) == 0, "跨卷误删：别的卷的 uid 在这张卷上删掉了东西"
    assert db.get_questions(other), "跨卷误删：另一张卷的题没了"
    shutil.rmtree(tmp, ignore_errors=True)
t("加题/删题：位置、序号重排、答案不失联", add_and_delete_questions)


def images_roundtrip():
    tmp = os.path.join(ROOT, "var", "_t_fmt")
    os.makedirs(tmp, exist_ok=True)
    db.DB_PATH = os.path.join(tmp, "t2.db")
    db.init()
    pid = db.create_paper("带图卷")
    q = db.replace_questions(pid, [{"q_no": 1, "section": "一", "qtype": "fill",
                                    "text": "看图列式（  ）", "options": [],
                                    "images": [{"name": "p1_q0.png", "page": 1,
                                                "w_pt": 120, "h_pt": 30}]}])[0]
    assert q["images"] and q["images"][0]["name"] == "p1_q0.png", q
    db.set_question_images(pid, q["uid"], [])
    assert db.get_questions(pid)[0]["images"] == [], "移除配图没生效"
    shutil.rmtree(tmp, ignore_errors=True)
t("配图字段读写与移除", images_roundtrip)


def two_up_and_page_format_stay_in_sync():
    """反例：V1.0 的选项里只有 two_up，V1.1 多了 page_format。
    只传 two_up=True 时必须自动等价于 page_format="a4_2up"，
    否则会出现"page_format 说 a4、two_up 说 True"的分裂状态——
    用户看到的就是"我明明选了 A4 单页，印出来还是两页一纸"。"""
    o = LayoutOptions.from_dict({"two_up": True})
    assert o.page_format == "a4_2up" and o.two_up is True and o.is_spread is False
    o2 = LayoutOptions.from_dict({"page_format": "a3_spread"})
    assert o2.is_spread and o2.two_up is False
    o3 = LayoutOptions.from_dict({"page_format": "a4"})
    assert o3.page_format == "a4" and o3.two_up is False
    o4 = LayoutOptions.from_dict({"page_format": "瞎写的值"})
    assert o4.page_format == "a4", o4.page_format
    assert o4.page_w == 595.28 and abs(o4.page_h - 841.89) < 1
    o5 = LayoutOptions.from_dict({"page_format": "a3_spread"})
    assert o5.page_w == 1190.55 and abs(o5.page_h - 841.89) < 1
t("two_up 与 page_format 不分裂（反例）", two_up_and_page_format_stay_in_sync)


def seal_line_stays_in_margin():
    """反例：密封线必须整条落在页边距以内，不能从题干上穿过去。
    第一版竖线画在 21mm、左边距 20mm → 线压在文字上，肉眼一看就知道没校过。"""
    ensure_fonts()
    pages = [{"page_no": 1, "is_scan": False, "landscape": False, "w_pt": 595, "h_pt": 842,
              "rendered_image": None,
              "blocks": [{"kind": "text", "x": 0, "y": 0,
                          "text": "一、填空题\n1. 3+4=（  ）\n2. 5×6=（  ）"}]}]
    opt = LayoutOptions(font_size=12, page_format="a3_spread", seal_line=True)
    r = render_pdf(build_layout(pages, opt, title="密封线"), opt,
                   os.path.join(OUT, "seal.pdf"), title="密封线")
    d = pymupdf.open(r["path"])
    xs = []
    for dr in d[0].get_drawings():
        for it in dr["items"]:
            if it[0] == "l":
                p0, p1 = it[1], it[2]
                if abs(p0.x - p1.x) < 0.5:          # 竖线
                    xs.append(round(p0.x, 1))
    d.close()
    assert xs, f"没画任何竖线（密封线/装订缝都不见了）：{xs}"
    left_margin = opt.margin_left
    seams = [x for x in xs if abs(x - A4_W) < 1]
    seals = [x for x in xs if x < left_margin - 1 or (left_margin - 1 <= x < left_margin + 1)]
    assert seams, f"对开中线没画在 A4 边界（{A4_W}pt）：{xs}"
    bad = [x for x in xs if x > left_margin and abs(x - A4_W) >= 1]
    assert not bad, f"密封线跑到正文区里了（左边距 {round(left_margin,1)}pt，越界的线 {bad}）"
    print(f"       （竖线 x={xs}，左边距 {round(left_margin,1)}pt，中线 {round(A4_W,1)}pt）")
t("密封线落在页边距以内（反例）", seal_line_stays_in_margin)


def sub_questions_print_on_separate_lines():
    """带（1）（2）（3）小问的题，打印时每一问各起一行。

    用户拿真卷问的原话："一个题目里面有三个小题，非得挤在一个框子里，
    怎么分别作答呢？" —— 题号/分值/批改仍按一道题走，但排版必须分开，
    否则孩子看不出哪一空答哪一问。
    """
    from app.extractor.rules import split_subqs

    t = ("看图填一填。 (1)2只2只地数,数了(    )次,一共有(    )只蝴蝶。 "
         "(2)3只3只地数,数了(    )次,一共有(    )只蝴蝶。 "
         "(3)4只4只地数,数了(    )次,一共有(    )只蝴蝶。")
    q = {"uid": "q1", "q_no": 2, "section": "一、填空", "qtype": "fill", "text": t,
         "subqs": split_subqs(t), "blanks": 6, "score": 3, "options": []}

    def lines_of(path):
        d = pymupdf.open(path)
        out = []
        for pg in d:
            for blk in pg.get_text("dict")["blocks"]:
                if blk.get("type") != 0:
                    continue
                for ln in blk["lines"]:
                    out.append("".join(sp["text"] for sp in ln["spans"]).strip())
        d.close()
        return out

    out = os.path.join(OUT, "小问分行.pdf")
    render_answers_pdf([q], LayoutOptions.from_dict({}), out, title="小问分行", mode="blank")
    got = lines_of(out)
    # 行首可能带题号前缀（"2. （1）…"），所以先剥掉 "N. " 再看小问标记
    def head_no(l):
        m = re.match(r"^\s*(?:\d+[.、]\s*)?[（(](\d{1,2})[）)]", l)
        return int(m.group(1)) if m else None
    marks = [head_no(l) for l in got]
    for n, kw in ((1, "2只2只"), (2, "3只3只"), (3, "4只4只")):
        row = [l for l, m in zip(got, marks) if m == n]
        assert len(row) == 1, f"第（{n}）问没独占一行（出现 {len(row)} 次）：{got}"
        assert kw in row[0], f"第（{n}）问的正文没落在本行（{row[0]!r}）——可能被上一行吞了：{got}"
    assert any(l.startswith("2. ") for l in got), f"题号仍要在第一行开头：{got}"
    # 引导语（"看图填一填。"）不是小问，但也不能丢：它得排在（1）之前
    lead_row = [i for i, l in enumerate(got) if "看图填一填" in l]
    assert lead_row, f"引导语整句没了：{got}"
    first_sub = min(i for i, m in enumerate(marks) if m == 1)
    assert lead_row[0] < first_sub, f"引导语跑到小问后面了：{got}"
    assert "（1）" not in got[lead_row[0]], f"引导语还和小问挤在同一行：{got[lead_row[0]]!r}"

    # 反例：没有小问结构的题不许被硬拆（普通填空题一行照排）
    plain = {"uid": "q2", "q_no": 3, "section": "一、填空", "qtype": "fill",
             "text": "一年有（    ）个月，其中大月有（    ）个。", "subqs": [],
             "blanks": 2, "score": 2, "options": []}
    out2 = os.path.join(OUT, "小问分行反例.pdf")
    render_answers_pdf([plain], LayoutOptions.from_dict({}), out2, title="无小问", mode="blank")
    got2 = lines_of(out2)
    assert not any(head_no(l) for l in got2), f"没小问也被加了编号：{got2}"
    assert not any(l.startswith("（1）") for l in got2), f"没小问也被加了编号：{got2}"
    assert any("一年有" in l for l in got2), got2
t("（1）（2）（3）小问在打印版里各起一行（含反例）", sub_questions_print_on_separate_lines)


def subqs_view_is_computed_at_read_time():
    """小问视图必须【接在读库链路上】而且是【读时算】，不是库里存第二份真相。

    两个失败方向都真会发生：
      · 线没接 —— rules.split_subqs 写好了、单测全绿，但 API 读出来的题里没有 subqs，
        打印版和做题页拿到的还是挤成一坨的题干（本项目的老毛病：判据对、线没接）；
      · 存成字段 —— 家长在校对页把"（2）…"改成普通空位后，库里旧的小问还在，
        打印版继续按三问排，跟题干打架。
    """
    tmp = os.path.join(OUT, "_subdb")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    db.DB_PATH = os.path.join(tmp, "t3.db")
    for suf in ("-wal", "-shm"):
        if os.path.exists(db.DB_PATH + suf):
            os.remove(db.DB_PATH + suf)
    db.init()
    pid = db.create_paper("小问卷")
    db.replace_questions(pid, [{"q_no": 1, "auto_no": 1, "section": "一、填空", "qtype": "fill",
                                "text": "看图数一数。(1)2只2只地数。(2)3只3只地数。",
                                "blanks": 2, "options": []},
                               {"q_no": 2, "auto_no": 2, "section": "一、填空", "qtype": "fill",
                                "text": "算式 3×4=（12），5×6=（30）。", "blanks": 2,
                                "options": []},
                               {"q_no": 3, "auto_no": 3, "section": "一、填空", "qtype": "fill",
                                "text": "数了(      )次,一共有(      )只蝴蝶。", "blanks": 0,
                                "options": []},
                               # 一年级数数题：数量本身就写成 1、2、3，没有括号。
                               # 小问号若允许"裸数字"，这题会被劈成三问（打印版各起
                               # 一行、正文只剩"只小鸟，"），孩子根本没法作答。
                               {"q_no": 4, "auto_no": 4, "section": "一、填空", "qtype": "fill",
                                "text": "看图数一数：1只小鸟，2只小兔，3只小鸡。", "blanks": 0,
                                "options": []}])
    got = db.get_questions(pid)
    assert len(got) == 4, f"小问不许拆成两道题（题号/分值仍按一道走）：{len(got)}"
    # 老库里存着"空位数 0"（旧口径只认 1–4 个空格），读出来必须自愈成 2，
    # 否则家长不重新上传一次，做题页永远只给一个输入框。
    assert got[2]["blanks"] == 2, f"空位数没在读时重算（存的快照不会自愈）：{got[2]['blanks']}"
    assert [s["no"] for s in got[0].get("subqs") or []] == [1, 2], \
        f"读库没带出小问视图（线没接）：{got[0].get('subqs')}"
    # 已经填了数的空位不是小问号 —— 库里读出来就必须是空视图
    assert got[1].get("subqs") == [], f"把算式结果当成了小问：{got[1]['subqs']}"
    # 数数题里的"1只…2只…"是数量不是小问编号 —— 小问号必须带括号。
    assert got[3].get("subqs") == [], f"把数量词当成了小问编号：{got[3]['subqs']}"
    assert "看图数一数" in str(got[0]["subqs"][0].get("lead") or ""), \
        f"引导语没随视图读出来：{got[0]['subqs'][0]}"

    db.update_question(pid, got[0]["uid"], text="看图数一数，一共有（    ）只蝴蝶。")
    after = db.get_questions(pid)[0]
    assert after.get("subqs") == [], f"改了题干，旧的小问视图还在（存成字段就会这样）：{after['subqs']}"
    shutil.rmtree(tmp, ignore_errors=True)
t("小问视图接在读库链路上、改题干后跟着变（含反例）", subqs_view_is_computed_at_read_time)


print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
