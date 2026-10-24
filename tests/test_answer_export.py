"""模式 B/C 导出（PRD §5.4 / 验收 F15）的离线测试。

重点不是"能不能生成 PDF"，而是【标记真的印在纸上】：
矢量画的 √ × △ 如果坐标算错、被裁到页边外、或者颜色是白的，
文本抽取照样"看得到内容"，只有把页面栅格化再数墨点才会暴露。
所以这里每条断言都用 pymupdf 的真实读数。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pymupdf                                                     # noqa: E402
from app.layout.options import LayoutOptions, MM                   # noqa: E402
from app.grading.engine import grade, make_uid                     # noqa: E402
from app.papers.answer_writer import render_answers_pdf, _fill_blank    # noqa: E402

ok_n = bad_n = 0
OUT = os.path.join(ROOT, "var", "_answer_export")
os.makedirs(OUT, exist_ok=True)

QS = [
    {"uid": "q1", "q_no": 1, "auto_no": 1, "section": "一、填空", "qtype": "fill",
     "text": "太阳从（  ）边升起", "options": [], "blanks": 1, "score": 2.0},
    {"uid": "q2", "q_no": 1, "auto_no": 1, "section": "二、选择", "qtype": "choice",
     "text": "4×7 读作（  ）", "options": ["A. 四七二十八", "B. 4乘7", "C. 7乘4"],
     "blanks": 1, "score": 2.0},
    {"uid": "q3", "q_no": 1, "auto_no": 1, "section": "三、判断", "qtype": "judge",
     "text": "6×3 和 3×6 的积相等", "options": [], "blanks": 0, "score": 1.0},
    {"uid": "q4", "q_no": 1, "auto_no": 1, "section": "四、解答", "qtype": "essay",
     "text": "说一说你是怎么想的，为什么。", "options": [], "blanks": 0, "score": 3.0},
]
KEY = {"q1": "东", "q2": "A", "q3": "√", "q4": "先找关键词再作答"}
ANS = {"q1": "东", "q2": "四七二十八", "q3": "×", "q4": "我是这样想的：先看数字"}


def _grade():
    return grade(QS, KEY, ANS, scores={make_uid(q): float(q["score"]) for q in QS})


def facts(path: str) -> dict:
    doc = pymupdf.open(path)
    txt = "\n".join(p.get_text() for p in doc)
    sizes = {(round(p.rect.width), round(p.rect.height)) for p in doc}
    # 左侧页边留白区（题号标记画在这里）的墨点数：证明符号是"印出来了"而不是"调用过了"
    ink_left = 0
    drawings = 0
    colors: set[tuple] = set()
    for p in doc:
        drawings += len(p.get_drawings())
        for d in p.get_drawings():
            col = d.get("color")
            if col:
                colors.add(tuple(round(float(x), 2) for x in col))
        pix = p.get_pixmap(dpi=100, clip=pymupdf.Rect(0, 0, 18 * MM * 100 / 25.4, p.rect.height))
        for i in range(0, len(pix.samples), pix.n):
            if pix.samples[i] < 128:
                ink_left += 1
    pages = doc.page_count
    doc.close()
    return {"text": txt, "sizes": sizes, "pages": pages, "ink_left": ink_left,
            "drawings": drawings, "colors": colors}


def t(name, fn):
    global ok_n, bad_n
    try:
        fn(); ok_n += 1; print("  PASS " + name)
    except AssertionError as e:
        bad_n += 1; print(f"  FAIL {name} → {e}")
    except Exception as e:
        import traceback
        bad_n += 1; print(f"  ERROR {name} → {type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")


print("\n[模式 B/C 导出]")

_res = _grade()
opt = LayoutOptions(font_size=12, show_header=True, branding=True)
B = render_answers_pdf(QS, opt, os.path.join(OUT, "b.pdf"), title="第三单元练习",
                       mode="answered", answers=ANS, key=KEY)
C = render_answers_pdf(QS, opt, os.path.join(OUT, "c.pdf"), title="第三单元练习",
                       mode="graded", answers=ANS, key=KEY, grade_result=_res,
                       class_name="二(1)班", student_name="小明")
fb, fc = facts(B["path"]), facts(C["path"])


def basics():
    assert B["pages"] >= 1 and C["pages"] >= 1, (B, C)
    assert fb["sizes"] == {(595, 842)}, f"不是 A4：{fb['sizes']}"
    assert fc["sizes"] == {(595, 842)}, fc["sizes"]
    assert os.path.getsize(B["path"]) > 1000 and os.path.getsize(C["path"]) > 1000
    assert not os.path.exists(B["path"] + ".tmp.pdf"), "临时文件残留（原子写没做完）"
t("两版都能出、尺寸 A4、无临时残留", basics)


def answered_has_content():
    assert "太阳从（东）边升起" in fb["text"].replace("\n", ""), fb["text"][:400]
    assert "四七二十八" in fb["text"], "选择题的勾选依据（作答正文）没印出来"
    assert "说一说你是怎么想的" in fb["text"].replace("\n", "")
    assert "我是这样想的" in fb["text"].replace("\n", ""), "问答题的学生作答没印出来"
    assert "班级" in fb["text"] and "姓名" in fb["text"], "表头缺班级/姓名"
t("B 版：题干+学生答案都落纸", answered_has_content)


def wide_blanks_fill_in_order():
    """扫描件里的宽空位（8–14 空格）必须和识别端一样算一个空位。

    独立复测 report_A P3-01/02/03：识别端数出 3 个空，导出端只认前 2 个，
    第 1 空空着、答案右移一格、最后一个答案掉进"其余作答"，批改还打 √。
    """
    stem = ("6. 把9.5463保留两位小数约是（{' ' * 12}），"
            "保留一位小数约是（{' ' * 12}），保留整数约是（{' ' * 12}）。")
    stem = stem.replace("{' ' * 12}", " " * 12)
    filled, extra = _fill_blank(stem, ["9.55", "9.5", "10"])
    assert not extra, f"宽空位没被认出来，答案被丢到题后：{extra} → {filled}"
    assert "（9.55）" in filled and "（9.5）" in filled and "（10）" in filled, filled
    # 半角/全角混配的一对括号（OCR 常见）也算空位
    mixed = "5个1角，就是5个（" + " " * 8 + ")元，是（" + " " * 8 + "）元。"
    filled2, extra2 = _fill_blank(mixed, ["0.1", "0.5"])
    assert not extra2 and "（0.1）" in filled2 and "（0.5）" in filled2, (filled2, extra2)
    # 已经填了内容的括号不是空位，不许覆盖
    assert _fill_blank("3×4=（12），5×6=（30）", ["1"]) == ("3×4=（12），5×6=（30）", ["1"])
    # 下划线空位照旧
    f3, e3 = _fill_blank("答案：________ ＝ ________", ["8", "9"])
    assert not e3 and "（8）" in f3 and "（9）" in f3, (f3, e3)
t("B 版：宽空位/混配括号逐空回填，不产生“其余作答”", wide_blanks_fill_in_order)


def marks_are_printed():
    """C 版必须有可见的对错标记（数页边墨点，不看调用）。"""
    assert fc["ink_left"] > 0, "批改标记一个像素都没画出来（题号左侧整页全白）"
    assert fb["ink_left"] <= fc["ink_left"], (fb["ink_left"], fc["ink_left"])
    assert fc["drawings"] >= 3, f"矢量标记数 {fc['drawings']}，太少"
    # 黑白可打印：不允许出现彩色（PRD 要求用符号而非颜色）
    chroma = [col for col in fc["colors"] if len(col) == 3 and max(col) - min(col) > 0.05]
    assert not chroma, f"出现彩色笔画，黑白打印会丢信息：{chroma}"
t("C 版：对错符号真印出来且非彩色", marks_are_printed)


def graded_summary_and_score():
    txt = fc["text"].replace("\n", "")
    assert "得分" in txt and "满分" in txt, txt[:300]
    assert f"{_res['score']}/{_res['total']}" in txt.replace(" ", "") or "得分 5.0/8.0" in txt, txt[:300]
    assert "待确认" in txt or _res["counts"]["pending"] == 0
    assert "第 1 页" in fc["text"], "缺页码"
    assert "磐远试卷打印助手" in fc["text"], "缺出处署名（P3 口碑链路）"
    # B 版不该出现得分汇总
    assert "满分" not in fb["text"], "已作答版不该带批改汇总"
t("C 版：得分汇总 + 页码 + 署名", graded_summary_and_score)


def summary_labels_every_pending_question():
    """批改汇总必须【一个不少】且能映射到大题：整题图没有 q_no 也不能漏。

    独立复测 report_A/B 实测：汇总写"待确认 19 题"，清单只有 17 个号；
    两个整题图题（一、口算 / 四、笔算）因为 q_no=None 被漏掉，
    各小题的 1/2/3 又按大题重复，老师无法对应到具体题目。
    """
    qs2 = [
        {"uid": "w1", "q_no": None, "auto_no": 1, "section": "一、直接写出得数（12%）",
         "qtype": "essay", "text": "", "options": [], "blanks": 0, "score": 1.0},
        {"uid": "w2", "q_no": 1, "auto_no": 2, "section": "二、填空（29%）",
         "qtype": "fill", "text": "甲（ ）", "options": [], "blanks": 1, "score": 1.0},
        {"uid": "w3", "q_no": 1, "auto_no": 3, "section": "三、判断（10%）",
         "qtype": "judge", "text": "乙", "options": [], "blanks": 0, "score": 1.0},
    ]
    g = grade(qs2, {}, {})                      # 没有标准答案 → 三题全待确认
    r = render_answers_pdf(qs2, opt, os.path.join(OUT, "summary.pdf"), title="汇总",
                           mode="graded", answers={}, key={}, grade_result=g)
    txt = facts(r["path"])["text"].replace("\n", "")
    assert "待确认 3 题" in txt, txt
    for lab in ("一·整题", "二·1", "三·1"):
        assert lab in txt, f"汇总漏了 {lab}：{txt}"
    assert "待确认：一·整题、二·1、三·1" in txt.replace(" ", ""), txt
t("C 版：待确认清单覆盖整题图且带大题号", summary_labels_every_pending_question)


def long_paper_paginates():
    """200 题必须自动分页，不许把内容挤出纸外。"""
    many = []
    for i in range(1, 201):
        many.append({"uid": f"z{i}", "q_no": i, "auto_no": i, "section": "一、填空",
                     "qtype": "fill", "text": f"第{i}题 计算 {i}+1=（  ）的结果并写出想法",
                     "options": [], "blanks": 1, "score": 1.0})
    key = {q["uid"]: str(int(q["q_no"]) + 1) for q in many}
    ans = {q["uid"]: key[q["uid"]] for q in many[::2]}
    g = grade(many, key, ans)
    r = render_answers_pdf(many, opt, os.path.join(OUT, "many.pdf"), title="长卷",
                           mode="graded", answers=ans, key=key, grade_result=g)
    f = facts(r["path"])
    assert f["pages"] >= 3, f"200 题只出了 {f['pages']} 页"
    body = f["text"].replace("\n", "")
    missing = [i for i in (1, 50, 120, 200) if f"第{i}题" not in body]
    assert not missing, f"分页后题目丢失：{missing}"
    assert "200" in body and f"{g['score']}" in body, "汇总分没落在最后一页"
t("200 题自动分页不丢题", long_paper_paginates)


def empty_answers_ok():
    """反例：一题没写也不能崩，B 版留空、C 版标 ×。"""
    g = grade(QS, KEY, {})
    r = render_answers_pdf(QS, opt, os.path.join(OUT, "empty.pdf"), title="空白",
                           mode="graded", answers={}, key=KEY, grade_result=g)
    f = facts(r["path"])
    assert r["pages"] >= 1 and f["ink_left"] > 0
    assert "未作答" in f["text"], "未作答的题没任何提示"
t("全未作答不崩且标记得画（反例）", empty_answers_ok)


def whole_span_figure_is_enlarged_to_page_width():
    """整题截图原尺寸只有半栏宽（P5 Q24 285.6pt），1:1 印出来字只有 5–6pt。

    判据：整题图要放大到接近页宽；普通配图仍按原尺寸（只缩不放）。
    """
    from PIL import Image, ImageDraw
    fp = os.path.join(OUT, "span_whole.png")
    im = Image.new("RGB", (794, 959), "white")
    dr = ImageDraw.Draw(im)
    for yy in range(20, 940, 40):
        dr.line((20, yy, 760, yy), fill=(0, 0, 0), width=2)
    im.save(fp)

    def width_of(graphic: bool, tag: str, w_pt: float = 285.6,
                 h_pt: float = 345.2, page_w: float | None = None) -> float:
        im = {"name": f"span_{tag}.png", "path": fp,
              "w_pt": w_pt, "h_pt": h_pt, "graphic": graphic}
        if page_w:
            im["page_w_pt"] = page_w
        q = {"uid": "q1", "q_no": 1, "auto_no": 1, "section": "", "qtype": "essay",
             "text": "", "options": [], "blanks": 0, "score": 1.0,
             "images": [im]}
        r = render_answers_pdf([q], LayoutOptions(), os.path.join(OUT, f"span_{tag}.pdf"),
                               title="整题图", mode="answered")
        doc = pymupdf.open(r["path"])
        # 整题图有半页多高，跟着它的作答横线一起挪到第 2 页是正确行为；
        # 这里只量图的宽度，所以按页找，不假定一定落在第 1 页。
        infos, page = [], None
        for pg in doc:
            infos = pg.get_images(full=True)
            if infos:
                page = pg
                break
        assert infos, f"[{tag}] 图没画到纸上"
        return page.get_image_bbox(infos[0]).width

    w_whole = width_of(True, "whole")
    w_normal = width_of(False, "normal")
    assert w_whole > 450, f"整题图没放大（{w_whole:.1f}pt），印出来仍只有半栏宽"
    assert w_whole <= LayoutOptions().content_w + 1, f"整题图溢出内容区：{w_whole:.1f}"
    assert abs(w_normal - 285.6) < 3, f"普通小图被误放大：{w_normal:.1f}（应约 285.6）"
    # 半张 A4 的扫描页（P4 285.6×404pt）：普通配图按 A4/源页比例放大回真实大小。
    # 53.5pt 的角图原样印出来只有 4–5pt 字高，孩子看不清。
    # h_pt 与测试 PNG 的 794×959 同比例（53.5×64.7），否则 drawImage 会按
    # 图片真实比例收窄，量到的不是 _figure_size 算出的宽度。
    w_half = width_of(False, "half", w_pt=53.5, h_pt=64.7, page_w=285.6)
    assert 100 < w_half < 130, f"半页源的普通配图没放大：{w_half:.1f}（应约 111）"
    # 反例：同一尺寸的图来自 A4 页 → 仍只按原尺寸印，不许一律放大。
    w_a4 = width_of(False, "a4", w_pt=53.5, h_pt=64.7, page_w=595.3)
    assert abs(w_a4 - 53.5) < 3, f"A4 页上的小图被误放大：{w_a4:.1f}"
t("整题截图放大到页宽（普通配图不放大；反例）", whole_span_figure_is_enlarged_to_page_width)

def whole_question_image_replaces_ocr_text():
    """整题原图（含题号/选项）已在图里：不许把 OCR 题干和选项再排一遍。

    P5 Q4/Q8 实测：图是完整的原题，上面又印了一遍 OCR 文字，同一道题
    出现两次；Q4 还带着 "B D" 残渣。判据：
      · 空白卷：只印图，OCR 文字一个都不出现；
      · 作答卷：图下必须有一行「作答：…」，否则孩子的答案在导出里看不见；
      · 普通片段图（没有 whole_question）仍印题干（反例）。
    """
    from PIL import Image, ImageDraw
    fp = os.path.join(OUT, "wq.png")
    im = Image.new("RGB", (794, 500), "white")
    ImageDraw.Draw(im).rectangle((10, 10, 780, 480), outline=(0, 0, 0), width=3)
    im.save(fp)
    OCR = "这段话只属于OCR残渣绝不该再印一遍"

    def make(whole: bool) -> dict:
        return {"uid": "wq", "q_no": 8, "auto_no": 8, "section": "一、选择",
                "qtype": "choice", "text": OCR,
                "options": ["A.甲选项", "B.乙选项"], "blanks": 1, "score": 1.0,
                "images": [{"name": "wq.png", "path": fp, "w_pt": 285.6,
                            "h_pt": 180.0, "graphic": True,
                            "graphic_kind": "span-fallback",
                            "whole_question": whole}]}

    blank = render_answers_pdf([make(True)], LayoutOptions(),
                               os.path.join(OUT, "wq_blank.pdf"),
                               title="整题图", mode="answered")
    doc = pymupdf.open(blank["path"])
    txt = "\n".join(p.get_text() for p in doc)
    assert OCR not in txt and "A.甲选项" not in txt, f"OCR 文字又印了一遍：{txt!r}"
    # 空白卷也必须留下笔位置：P1 Q1/Q2/Q5 的整题图下面原本直接接下一题，
    # 孩子只能在扫描图的选项上圈一下，没有可写答案的行。
    assert "作答" in txt, f"整题图的空白卷没有作答行：{txt!r}"
    assert doc[0].get_images(full=True), "整题图没画出来"
    doc.close()

    ans = render_answers_pdf([make(True)], LayoutOptions(),
                             os.path.join(OUT, "wq_ans.pdf"),
                             title="整题图", mode="answered", answers={"wq": "B"})
    atxt = "\n".join(p.get_text() for p in pymupdf.open(ans["path"]))
    assert "作答" in atxt and "B.乙选项" in atxt, f"作答内容没印在图下：{atxt!r}"

    # 批改卷：没作答的整题只许印一次「未作答」。整题分支和末尾兜底各印一次，
    # 会把「未作答」叠成两行（P1 批改版实测）。
    graded = render_answers_pdf([make(True)], LayoutOptions(),
                                os.path.join(OUT, "wq_graded.pdf"),
                                title="整题图", mode="graded")
    gtxt = "\n".join(p.get_text() for p in pymupdf.open(graded["path"]))
    assert gtxt.count("未作答") == 1, f"「未作答」印了 {gtxt.count('未作答')} 次：{gtxt!r}"

    # 原卷自带「答：/我的理由：」框的整题图（P5 Q24/Q25）不再补作答行：
    # 多补两行只会把下一题顶到新页。反例是没有这个提示的整题图（上面已断言有）。
    cued = make(True)
    cued["source_lines"] = ["答：我认为六（1）班男生的成绩好一些。", "我的理由："]
    cu = render_answers_pdf([cued], LayoutOptions(),
                            os.path.join(OUT, "wq_cued.pdf"),
                            title="整题图", mode="answered")
    ctxt = "\n".join(p.get_text() for p in pymupdf.open(cu["path"]))
    assert "作答" not in ctxt, f"原卷已有作答框却又补了一行：{ctxt!r}"

    normal = render_answers_pdf([make(False)], LayoutOptions(),
                                os.path.join(OUT, "wq_normal.pdf"),
                                title="普通图", mode="answered")
    ntxt = "\n".join(p.get_text() for p in pymupdf.open(normal["path"]))
    assert OCR in ntxt, "反例：普通片段图的题干被误藏"
t("整题原图不许再印一遍 OCR 文字（作答要单独印；反例）", whole_question_image_replaces_ocr_text)

def figure_is_drawn_before_the_answer_area():
    """配图必须紧跟题干、排在作答区之前（P2 Q8 / P3 面积题实测）。

    旧版只给 graphic=True 的图形算式开"图先于横线"的口子，普通配图留到
    函数末尾才画：纸上先出现"1."和两条作答横线，图却在横线下面。孩子得
    先越过答题区才看到题目问的是什么。判据：
      · 空白卷：图底在两条灰色作答横线之上；
      · 有作答：图底在「答：」那行之上；
      · 反例：没有配图的题仍要有两条作答横线。
    """
    from PIL import Image, ImageDraw
    fp = os.path.join(OUT, "before_answer.png")
    im = Image.new("RGB", (600, 300), "white")
    ImageDraw.Draw(im).rectangle((5, 5, 595, 295), outline=(0, 0, 0), width=4)
    im.save(fp)

    def make(uid: str, with_fig: bool = True) -> dict:
        q = {"uid": uid, "q_no": 1, "auto_no": 1, "section": "四、面积",
             "qtype": "essay", "text": "看图算出下面图形的面积。",
             "options": [], "blanks": 0, "score": 4.0}
        if with_fig:
            q["images"] = [{"name": "before_answer.png", "path": fp,
                            "w_pt": 200.0, "h_pt": 100.0, "graphic": False}]
        return q

    def gray_lines(page):
        out = []
        for d in page.get_drawings():
            col = d.get("color") or ()
            rect = d["rect"]
            if (len(col) == 3 and all(abs(float(c) - 0.733) < 0.02 for c in col)
                    and rect.width > 300 and rect.height < 3):
                out.append(rect)
        return out

    def image_box(page):
        infos = page.get_images(full=True)
        assert infos, "配图没画到纸上"
        return page.get_image_bbox(infos[0])

    blank = render_answers_pdf([make("blankfig")], LayoutOptions(),
                               os.path.join(OUT, "fig_before_blank.pdf"),
                               title="图先于作答", mode="answered")
    p1 = pymupdf.open(blank["path"])[0]
    box1, lines1 = image_box(p1), gray_lines(p1)
    assert len(lines1) >= 2, f"空白卷没有作答横线：{len(lines1)}"
    assert box1.y1 < min(r.y0 for r in lines1), \
        f"图排在作答横线之后：图底 {box1.y1:.1f}，横线顶 {min(r.y0 for r in lines1):.1f}"

    ans = render_answers_pdf([make("ansfig")], LayoutOptions(),
                             os.path.join(OUT, "fig_before_ans.pdf"),
                             title="图先于作答", mode="answered",
                             answers={"ansfig": "24 平方厘米"})
    p2 = pymupdf.open(ans["path"])[0]
    box2, hits = image_box(p2), p2.search_for("答：")
    assert hits, "作答正文没印出来"
    assert box2.y1 < min(h.y0 for h in hits), \
        f"图排在「答：」之后：图底 {box2.y1:.1f}，答行顶 {min(h.y0 for h in hits):.1f}"

    plain = render_answers_pdf([make("plain", with_fig=False)], LayoutOptions(),
                               os.path.join(OUT, "fig_before_none.pdf"),
                               title="无图", mode="answered")
    p3 = pymupdf.open(plain["path"])[0]
    assert len(gray_lines(p3)) >= 2, "反例：没有配图的题丢了作答横线"
t("配图紧跟题干、排在作答区之前（含无图反例）", figure_is_drawn_before_the_answer_area)

def choice_question_is_not_split_across_pages():
    """P5 第 7 题真机导出：D 选项单独落在下一页顶部，前面没有题干。

    判据：选择题的题干与它的全部选项必须在同一页（整题能放下时）。
    """
    qs = [{"uid": f"f{i}", "q_no": i, "auto_no": i, "section": "一、填空",
           "qtype": "fill", "text": f"第{i}题 填一填（  ）。",
           "options": [], "blanks": 1, "score": 1.0} for i in range(1, 22)]
    opts = [f"{chr(65+i)}.选项{'甲乙丙丁戊己庚辛壬癸'[i]}的说法的确就是这样" for i in range(10)]
    qs.append({"uid": "q22", "q_no": 22, "auto_no": 22, "section": "二、选择",
               "qtype": "choice",
               "text": "下面这一段话很长，用来把这道选择题推到页底附近，"
                       "看它的选项会不会被拆到下一页去。请选出正确的一项（ ）。",
               "options": opts, "blanks": 1, "score": 1.0})
    r = render_answers_pdf(qs, opt, os.path.join(OUT, "no_split.pdf"),
                           title="分页", mode="answered")
    doc = pymupdf.open(r["path"])
    pages_of: dict[str, int] = {}
    for pi, page in enumerate(doc):
        body = page.get_text()
        for i, o in enumerate(opts):
            if o in body:
                pages_of[o] = pi
        if "正确的一项" in body:
            pages_of["stem"] = pi
    assert "stem" in pages_of, "题干没印出来"
    assert len(pages_of) == len(opts) + 1, f"有选项没印出来：{len(pages_of)}/{len(opts)+1}"
    assert len(set(pages_of.values())) == 1, \
        f"选择题被拆到多页：{ {k[:6]: v + 1 for k, v in pages_of.items()} }"
t("选择题整题同页（选项 D 不许单独甩到下一页）", choice_question_is_not_split_across_pages)

print(f"\n{ok_n} passed, {bad_n} failed")
print("产物：", OUT)
sys.exit(1 if bad_n else 0)
