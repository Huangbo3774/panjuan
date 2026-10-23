"""布局算法单测（Python 版，对应 JS 版 tests/layout.test.mjs 的 16 条）。

规矩：每个正例都配一条能证明这把尺会 FAIL 的反例。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.layout.columns import (detect_columns, group_lines, structure_page,   # noqa: E402
                                _exact_gap_split)
from app.layout.engine import build_layout, wrap_text, _QNO_LINE_RE           # noqa: E402
from app.layout.options import LayoutOptions, MM                              # noqa: E402

ok_n = bad_n = 0


def t(name, fn):
    global ok_n, bad_n
    try:
        fn(); ok_n += 1; print("  PASS " + name)
    except AssertionError as e:
        bad_n += 1; print(f"  FAIL {name} → {e}")
    except Exception as e:
        bad_n += 1; print(f"  ERROR {name} → {type(e).__name__}: {e}")


def I(x, y, w, text, h=20):
    return {"x": x, "y": y, "w": w, "h": h, "text": text}


def two_col():
    a = []
    for i in range(6):
        a += [I(50, 100 + i * 30, 90, f"左{i}"), I(160, 100 + i * 30, 90, f"左b{i}"),
              I(380, 100 + i * 30, 90, f"右{i}"), I(490, 100 + i * 30, 90, f"右b{i}")]
    return a


print("\n[分栏检测]")
def two_col_detected():
    b = detect_columns(two_col(), 600)
    assert len(b) == 2, f"实际 {len(b)} 栏: {b}"
t("双栏判 2 栏", two_col_detected)

def single_col_not_split():
    # 真实单栏的样子：每行左对齐、长度不一，行与行之间横向连续无空带
    items = [I(50, 100 + i * 30, 60 + (i % 4) * 110, "字" * 8) for i in range(8)]
    b = detect_columns(items, 600)
    assert len(b) == 1, f"单栏被误判为 {len(b)} 栏: {b}"
t("单栏不误判", single_col_not_split)
t("只有右边有内容不算双栏", lambda: (_ for _ in ()).throw(AssertionError("单边误判"))
  if len(detect_columns([I(380, 100 + i * 30, 90, "r") for i in range(6)], 600)) != 1 else None)
t("三栏", lambda: (_ for _ in ()).throw(AssertionError("三栏漏检"))
  if len(detect_columns([I(c, 100 + i * 30, 60, "z") for i in range(6)
                         for c in (30, 100, 230, 300, 430, 500)], 600)) != 3 else None)
t("回归：先合行再分栏必然漏检", lambda: (_ for _ in ()).throw(
    AssertionError("合并后仍留空隙，本用例需重写"))
  if len(detect_columns(group_lines(two_col(), 10), 600)) != 1 else None)

print("\n[双页照片：中缝兜底]")
def exact_gap_split_picks_the_widest_central_gap():
    """达标B：两页并排拍成一张 900pt 宽的图。左页里还夹着一条 25pt 的栏内空带，
    它比中缝更靠前、也够 18pt/30% 的门槛；只许切中缝（37pt、444.5）。"""
    items = []
    for i in range(5):
        y = 80 + i * 40
        items += [I(30, y, 90, "a"), I(140, y, 120, "b"),
                  I(280, y, 70, "c"), I(375, y, 51, "d"),
                  I(463, y, 80, "e"), I(560, y, 110, "f")]
    cut = _exact_gap_split(items, 900)
    assert cut == 444.5, f"没切中缝（被左页 25pt 空带抢走了）：{cut}"
    # 接线：直方图和左边缘法都判不出栏时，detect_columns 必须走这条兜底。
    # 稀疏夹具会让直方图自己切出六栏，所以这里把两条旧判据固定成"没找到"。
    import app.layout.columns as C
    orig = C._bands_from_histogram
    C._bands_from_histogram = lambda *a, **kw: [{"x0": 0.0, "x1": 900.0}]
    try:
        bands = detect_columns(items, 900)
    finally:
        C._bands_from_histogram = orig
    assert len(bands) == 2 and abs(bands[0]["x1"] - 444.5) < 0.6, \
        f"detect_columns 没走兜底：{bands}"
t("中缝要找最宽的合格缝（页内空带不许抢）", exact_gap_split_picks_the_widest_central_gap)

def exact_gap_split_rejects_bad_shapes():
    # 反例①：单栏参差行 —— 外接框互相接上，只有一整段墨 → 不切
    ragged = [I(40 + (i % 3) * 20, 80 + i * 30, 480 - (i % 3) * 40, "x")
              for i in range(8)]
    assert _exact_gap_split(ragged, 900) is None, "参差单栏被劈成两栏"
    # 反例②：只有左边有内容 → 右边没有第二段墨
    one_side = [I(40 + i * 20, 80 + i * 30, 120, "x") for i in range(6)]
    assert _exact_gap_split(one_side, 900) is None, "单边内容也切"
    # 反例③：缝在页面左边 27%（页面宽 1200）→ 不是中缝
    edge = [I(20, 80, 80, "a"), I(120, 80, 80, "b"), I(220, 80, 80, "c"),
            I(360, 80, 60, "d"), I(440, 80, 60, "e"), I(520, 80, 60, "f")]
    assert _exact_gap_split(edge, 1200) is None, "页边大缝被当中缝"
    # 反例④：缝在页面右侧 84% → 同样不算中缝
    edge2 = [I(500, 80, 60, "a"), I(580, 80, 60, "b"), I(660, 80, 60, "c"),
             I(800, 80, 20, "d"), I(830, 80, 20, "e"), I(860, 80, 20, "f")]
    assert _exact_gap_split(edge2, 900) is None, "右侧页边缝被当中缝"
    # 反例⑤：缝只有 10pt（<18pt）
    short = [I(40, 80, 360, "a"), I(40, 120, 360, "b"), I(40, 160, 360, "c"),
             I(410, 80, 120, "d"), I(410, 120, 120, "e"), I(410, 160, 120, "f")]
    assert _exact_gap_split(short, 900) is None, "10pt 小缝也切"
    # 反例⑥：左边只有 2 个框（<3）→ 不能成栏
    few = [I(40, 80, 120, "a"), I(40, 120, 120, "b"),
           I(500, 80, 120, "c"), I(500, 120, 120, "d"),
           I(500, 160, 120, "e"), I(500, 200, 120, "f")]
    assert _exact_gap_split(few, 900) is None, "左边 2 个框也切"
t("中缝兜底的六条反例", exact_gap_split_rejects_bad_shapes)

print("\n[内容守恒 —— 压力测试抓到的真 bug]")
def no_content_loss():
    """稀疏页（每页一行）一行都不许丢。曾用「占比<10% 的栏删掉」吞掉了 96/100 行。"""
    pages = [{"is_scan": False, "page_no": i + 1, "text_chars": 20,
              "blocks": [{"kind": "text", "text": f"第{i+1}页 内容", "bbox": [60, 80, 300, 96]}]}
             for i in range(100)]
    model = build_layout(pages, LayoutOptions(), title="压测")
    txt = "".join(ln for b in model["pages"] for x in b["blocks"] if x["type"] == "text"
                  for ln in x["lines"])
    missing = [i for i in range(1, 101) if f"第{i}页" not in txt.replace(" ", "")]
    assert not missing, f"丢了 {len(missing)} 行内容"
t("100 页稀疏内容重排后一行不丢", no_content_loss)

def sparse_column_kept():
    """稀疏但真实的栏（左侧竖排装订栏）不能被删掉。"""
    items = two_col() + [I(8, 200, 30, "学校"), I(8, 400, 30, "班级"), I(8, 600, 30, "姓名")]
    bands = detect_columns(items, 600)
    kept = sum(1 for b in bands if any(b["x0"] <= i["x"] < b["x1"] for i in items))
    assert kept == len(bands), f"有 {len(bands)-kept} 个栏是空的却被保留/或内容被吞"
    st = structure_page(items, 600)
    for tag in ("学校", "班级", "姓名"):
        assert any(tag in l["text"] for l in st["lines"]), f"{tag} 被吞了"
t("左侧装订栏内容不被吞", sparse_column_kept)

print("\n[阅读顺序]")
def reading_order():
    st = structure_page(two_col(), 600)
    seq = [l["text"] for l in st["lines"]]
    assert all(s.startswith("左") for s in seq[:6]), f"前 6 行应全左栏: {seq[:6]}"
    assert all(s.startswith("右") for s in seq[6:]), f"后 6 行应全右栏: {seq[6:]}"
t("双栏：左栏全部先于右栏", reading_order)

def two_up_page():
    """计算练习页：同一大题的 (1)(3) 排左、(2)(4) 排右，必须逐行读。

    真实新卷（P5 第 5 页）：按栏优先会把 (2) 接到下一题，Q17 只剩 (1)、Q20 只剩题号。
    """
    return [
        I(46, 40, 100, "三、计算题（共2道小题）"),
        I(46, 62, 70, "17.化简。"),
        I(46, 80, 70, "(1) 2.8:0.7"),
        I(150, 78, 70, "(2) 3.5:12"),
        I(46, 120, 80, "18.计算下面各题。"),
        I(46, 140, 70, "(1) 4×3/18"),
        I(150, 142, 70, "(2) 27/9×4/9"),
        I(46, 180, 70, "(3) 7/25×1/35"),
        I(150, 178, 70, "(4) 7/25×65"),
        I(46, 240, 70, "19. 15%x=75"),
        I(150, 241, 90, "20. 4/7x-1/2x=3"),
    ]


def two_up_reads_row_major():
    st = structure_page(two_up_page(), 285.6)
    seq = [l["text"] for l in st["lines"]]
    want = ["(1) 2.8:0.7", "(2) 3.5:12", "(1) 4×3/18", "(2) 27/9×4/9",
            "(3) 7/25×1/35", "(4) 7/25×65"]
    pos = [seq.index(w) for w in want]
    assert pos == sorted(pos), f"2-up 没逐行读：{seq}"
    assert seq.index("17.化简。") < seq.index("(1) 2.8:0.7") < seq.index("18.计算下面各题。"), \
        f"题头与小题目顺序错：{seq}"
    assert seq.index("19. 15%x=75") < seq.index("20. 4/7x-1/2x=3"), \
        f"并排两题丢了右题：{seq}"
t("2-up 练习页逐行读（(1)左/(2)右成对）", two_up_reads_row_major)


def two_up_needs_two_pairs():
    """只有一对 (1)/(2) 同高 → 可能是巧合，保持栏优先。

    反例必须能改变结论：把第二对挪远后，顺序必须回到左栏先读。
    """
    items = two_up_page()
    for it in items:
        if it["text"].startswith("(2) 27/9") or it["text"].startswith("(4)"):
            it["y"] += 60
    st = structure_page(items, 285.6)
    seq = [l["text"] for l in st["lines"]]
    assert seq.index("(1) 4×3/18") < seq.index("(2) 3.5:12"), \
        f"仅一对也翻成逐行读了：{seq}"
t("2-up 判据：两对才翻，一对保持栏优先", two_up_needs_two_pairs)


def true_two_col_with_subitems_stays_column_first():
    """真两栏：左右各有完整的 (1)(2)(3)(4)，但同号不同高 —— 仍先读完整左栏。"""
    items = []
    for i in range(4):
        items += [I(50, 100 + i * 30, 90, f"({i+1}) 左小题{i+1}"),
                  I(380, 100 + i * 30, 90, f"({i+1}) 右小题{i+1}")]
    st = structure_page(items, 600)
    seq = [l["text"] for l in st["lines"]]
    assert all("左小题" in s for s in seq[:4]), f"真两栏被逐行读了：{seq}"
    assert all("右小题" in s for s in seq[4:]), f"真两栏被逐行读了：{seq}"
t("真两栏带小题号仍先读完左栏", true_two_col_with_subitems_stays_column_first)


def wide_title():
    items = [I(180, 30, 240, "第三单元达标练习（通栏大标题）")] + two_col()
    st = structure_page(items, 600)
    assert st["lines"][0]["col"] == -1, f"首行应为通栏，实际 col={st['lines'][0]['col']}"
    assert "通栏大标题" in st["lines"][0]["text"]
t("真通栏标题前置", wide_title)

def inline_wide_stays():
    """嵌在正文中间的跨栏元素不该被抽到全文最前（真实数据上把「六、」错排到首行）。"""
    items = two_col() + [I(50, 260, 520, "六、大作文题头")]
    st = structure_page(items, 600)
    first = st["lines"][0]
    assert "六、" not in first["text"], f"跨栏题头被错抽到首行: {first['text']}"
t("正文中间的跨栏元素不前置", inline_wide_stays)

print("\n[行合并与间距]")
def gaps_preserved():
    """表格列/选项间距必须保住，否则「30 厘米  1 米」会粘成「30 厘米1米」。"""
    items = [I(90, 376, 60, "30 厘米"), I(167, 376, 45, "30 米"),
             I(226, 376, 60, "100-55"), I(297, 376, 60, "100-65")]
    ln = group_lines(items, 10)
    assert len(ln) == 1, f"应合成 1 行，实际 {len(ln)}"
    assert "30 厘米  30 米" in ln[0]["text"] or "  " in ln[0]["text"], f"间距丢了: {ln[0]['text']}"
t("同水平线多列合并时保留间距", gaps_preserved)

def no_empty_lines():
    assert group_lines([I(10, 10, 5, "   ")], 8) == [], "空文本不该产生行"
t("空文本不产生空行", no_empty_lines)

print("\n[折行与选项]")
def wrap_cjk():
    lines = wrap_text("磐卷" * 60, 12, 200)
    assert len(lines) > 1 and all(len(x) > 0 for x in lines)
    from app.layout.engine import measure
    assert all(measure(x, 12) <= 200 + 12 for x in lines), "有行超出宽度"
t("中文按宽度折行不溢出", wrap_cjk)

def clamp():
    o = LayoutOptions.from_dict({"font_size": 999, "margin_left": -50, "font_scale": 9})
    assert o.font_size <= 20 and o.margin_left >= 8 * MM and o.font_scale <= 1.8
t("非法选项被夹到合法区间", clamp)

def a4_geometry():
    o = LayoutOptions()
    assert 0 < o.content_w < 595.28 and 0 < o.content_h < 841.89
    assert o.content_w == round(595.28 - o.margin_left - o.margin_right, 6) or abs(
        o.content_w - (595.28 - o.margin_left - o.margin_right)) < 1e-6
t("A4 内容区尺寸自洽", a4_geometry)

def two_up_halves():
    pages = [{"is_scan": False, "page_no": i + 1, "text_chars": 40,
              "blocks": [{"kind": "text", "text": f"第{i+1}页 " + "内容" * 200,
                          "bbox": [60, 80, 500, 700]}]} for i in range(4)]
    a = build_layout(pages, LayoutOptions(), title="x")
    b = build_layout(pages, LayoutOptions(two_up=True), title="x")
    assert len(b["pages"]) == (len(a["pages"]) + 1) // 2, f"{len(a['pages'])}→{len(b['pages'])}"
t("2合1 页数减半", two_up_halves)

print("\n[分页：一道题的选项不许被甩到下一页]")
def option_letter_stays_with_its_stem():
    """P5 第 7 题真机导出：A–C 在页底，D 单独出现在下一页顶部。

    修复判据不是"页数不变"，而是【同一题号组的所有行必须落在同一页】。
    """
    lines = ["1. 第一题。"] + [f"条件{i}。" for i in range(22)]
    lines += ["7. 淘气正在参加套圈游戏，下面说法正确的是（ ）。",
              "①目前套中了8次。", "②没套中的次数占60%。",
              "③再接20次命中率也是40%。", "A.只有②", "B.只有①②",
              "C.只有①③", "D.只有②③"]
    blocks = [{"kind": "text", "text": t, "bbox": [60, 80 + i * 24, 520, 100 + i * 24]}
              for i, t in enumerate(lines)]
    m = build_layout([{"is_scan": False, "page_no": 1, "blocks": blocks}],
                     LayoutOptions(), title="t")
    p7 = {"7. 淘气正在参加套圈游戏，下面说法正确的是（ ）。",
          "①目前套中了8次。", "②没套中的次数占60%。",
          "③再接20次命中率也是40%。", "A.只有②", "B.只有①②",
          "C.只有①③", "D.只有②③"}
    where = {}
    for pi, pg in enumerate(m["pages"]):
        for b in pg["blocks"]:
            for ln in b.get("lines", []):
                if ln in p7:
                    where.setdefault(ln, set()).add(pi)
    assert len(where) == len(p7), f"有行丢了：{p7 - set(where)}"
    pages_for_q7 = set().union(*where.values())
    assert len(pages_for_q7) == 1, \
        f"第 7 题被拆到 {len(pages_for_q7)} 页：{ {k: sorted(v) for k, v in where.items()} }"
    # 反例保险：题号识别不能把小数当题号（否则 3.14 行会另起一组）
    assert not _QNO_LINE_RE.match("3.14 是圆周率"), "小数被当成题号行"
    assert not _QNO_LINE_RE.match("第5课时 练习"), "课时序号被当成题号行"
t("选项 D 不许被甩到下一页", option_letter_stays_with_its_stem)

print(f"\n{ok_n} passed, {bad_n} failed")
sys.exit(1 if bad_n else 0)
