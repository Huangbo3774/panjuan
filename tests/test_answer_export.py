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
from app.papers.answer_writer import render_answers_pdf             # noqa: E402

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
    assert "磐卷 PaperForge" in fc["text"], "缺出处署名（P3 口碑链路）"
    # B 版不该出现得分汇总
    assert "满分" not in fb["text"], "已作答版不该带批改汇总"
t("C 版：得分汇总 + 页码 + 署名", graded_summary_and_score)


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


print(f"\n{ok_n} passed, {bad_n} failed")
print("产物：", OUT)
sys.exit(1 if bad_n else 0)
