"""模式 B（已作答）/ 模式 C（批改）PDF 导出（PRD §5.4，验收 F15）。

与模式 A 的区别：A 排的是"原卷版面"，B/C 排的是"题目数据 + 作答"，
所以这个文件自己管分页，不走 layout.engine 的分页模型。

四条硬性口径：
  · 对错用【矢量画的符号】（√ / × / △），不用颜色、也不用字体里的符号字形。
    黑白打印要能分辨（PRD 明确要求）；而且 ✓(U+2713)/✗(U+2717) 在很多中文字体里
    根本没有字形，ReportLab 会静默画成空白——"以为画了"和"印得出来"是两件事，画线不会骗人。
  · 学生没作答的题，B 版留空、C 版标 ×，绝不代填标准答案。
  · 待确认（△）必须有：问答题和不确定的填空不能印成"错"，那是误伤孩子。
  · 页码与署名走【两趟渲染】：Canvas 不能回头改已写的页，
    所以先空跑一趟数页数，再带 total 画第二趟。
"""
from __future__ import annotations

import io
import os
import re
from typing import Any

from reportlab.lib.colors import black, HexColor
from reportlab.pdfgen import canvas as rl_canvas

from ..layout.options import LayoutOptions
from ..layout.engine import wrap_text
from .pdf_writer import ensure_fonts, _state, _measure, _draw_footer

A4_W, A4_H = 595.28, 841.89
BLANK_RE = re.compile(r"(_{2,}|[＿]{2,}|（\s{0,6}）|\(\s{0,6}\))")
FIG_BORDER = HexColor("#c9ccc9")


def _fill_blank(stem: str, answers: list[str]) -> tuple[str, list[str]]:
    """把学生答案填回题干的空位（（）/＿＿/下划线）。返回 (成品文本, 没地方放的答案)。"""
    rest = [a for a in answers if str(a).strip()]
    if not rest:
        return stem, []
    out, used, pos = [], 0, 0
    for m in BLANK_RE.finditer(stem):
        out.append(stem[pos:m.start()])
        if used < len(rest):
            out.append(f"（{rest[used]}）")
            used += 1
        else:
            out.append(m.group(0))
        pos = m.end()
    out.append(stem[pos:])
    return "".join(out), rest[used:]


class Flow:
    """A4 上的流式排版：写不下自动翻页；知道总页数时每页盖页脚。"""

    def __init__(self, c: rl_canvas.Canvas, opt: LayoutOptions, total: int | None = None):
        self.c, self.opt, self.total = c, opt, total
        self.y = A4_H - opt.margin_top
        self.pno = 1
        self.pages = 1

    def _break(self) -> None:
        if self.total:
            _draw_footer(self.c, self.opt, self.pno, self.total)
        self.c.showPage()
        self.pno += 1
        self.pages += 1
        self.y = A4_H - self.opt.margin_top

    def need(self, h: float) -> None:
        while self.y - h < self.opt.margin_bottom + 18:
            self._break()

    def text(self, s: str, size: float, indent: float = 0, gap_after: float = 0) -> None:
        w = self.opt.content_w - indent
        for line in wrap_text(s, size, w) or [""]:
            self.need(self.opt.leading)
            self.c.setFont(_state["family"], size)
            self.c.drawString(self.opt.margin_left + indent, self.y - size, line)
            self.y -= self.opt.leading
        self.y -= gap_after

    def space(self, h: float) -> None:
        self.need(h)
        self.y -= h


def _poly(c: rl_canvas.Canvas, pts: list[tuple[float, float]]) -> None:
    """按点列画折线。⚠️ 不能用 canvas.lines()：它要 [(x1,y1,x2,y2), ...] 线段元组，
    传点列会当场 ValueError（第一版就是这么炸的，好在是响亮地炸而不是静默画歪）。"""
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        c.line(x1, y1, x2, y2)


def _draw_mark(c: rl_canvas.Canvas, kind: str, x: float, y: float, size: float) -> None:
    """矢量画 √ / × / △（三态：对 / 错 / 待人工确认）。"""
    c.setStrokeColor(black)
    c.setLineWidth(max(1.0, size / 9))
    if kind == "correct":
        _poly(c, [(x, y - size * 0.45), (x + size * 0.32, y - size * 0.8), (x + size, y)])
    elif kind == "wrong":
        _poly(c, [(x, y), (x + size * 0.8, y - size * 0.8)])
        _poly(c, [(x + size * 0.8, y), (x, y - size * 0.8)])
    else:
        p = c.beginPath()
        p.moveTo(x + size * 0.45, y)
        p.lineTo(x, y - size * 0.8)
        p.lineTo(x + size * 0.9, y - size * 0.8)
        p.close()
        c.drawPath(p, stroke=1, fill=0)


def _option_box(c: rl_canvas.Canvas, x: float, y: float, size: float, checked: bool) -> None:
    c.setStrokeColor(black)
    c.setLineWidth(0.8)
    c.rect(x, y - size, size, size, stroke=1, fill=0)
    if checked:
        c.setLineWidth(max(1.1, size / 7))
        _poly(c, [(x + size * 0.18, y - size * 0.5), (x + size * 0.42, y - size * 0.82),
                  (x + size * 0.85, y - size * 0.1)])


def _resolve_fig(im: dict, fig_dir: str | None) -> str:
    """配图落盘路径。库里存的字段是 `name`（校对页/做题页拿它拼 URL），
    以前这里只读 `path` —— 于是 PDF 里一张图都不画，而且一声不吭。"""
    p = im.get("path") or ""
    if not p and fig_dir and im.get("name"):
        p = os.path.join(fig_dir, os.path.basename(str(im["name"])))
    return p if p and os.path.exists(p) else ""


def _draw_figures(c: rl_canvas.Canvas, q: dict, opt: LayoutOptions, fl: "Flow",
                  indent: float = 0, fig_dir: str | None = None,
                  stats: dict | None = None) -> None:
    """把题目配图画在题干下面。图没了这道题就没法做，所以宁可占半页也要留。"""
    imgs = q.get("images") or []
    for im in imgs:
        p = _resolve_fig(im, fig_dir)
        if not p:
            if stats is not None:
                stats["missing"] += 1
            continue
        w_pt = float(im.get("w_pt") or 0) or opt.content_w * 0.6
        h_pt = float(im.get("h_pt") or 0) or w_pt * 0.6
        max_w = opt.content_w - indent - 8
        scale = min(1.0, max_w / w_pt) if w_pt else 1.0
        # 高度上限：一张图最多吃掉半页，超了就缩（否则平面图会把整页占满）
        max_h = (A4_H - opt.margin_top - opt.margin_bottom) * 0.5
        if h_pt * scale > max_h:
            scale = max_h / h_pt
        w, h = w_pt * scale, h_pt * scale
        fl.need(h + 8)
        fl.y -= 4
        c.saveState()
        c.setStrokeColor(FIG_BORDER)
        c.setLineWidth(0.5)
        try:
            c.drawImage(p, opt.margin_left + indent + 8, fl.y - h, width=w, height=h,
                        preserveAspectRatio=True, mask="auto")
        except Exception:                       # 图坏了也不能整卷出不来，但要记账
            c.restoreState()
            if stats is not None:
                stats["missing"] += 1
            continue
        c.rect(opt.margin_left + indent + 8, fl.y - h, w, h, stroke=1, fill=0)
        c.restoreState()
        fl.y -= h + 6
        if stats is not None:
            stats["drawn"] += 1


def _chosen(alist: list[str], options: list[str]) -> int | None:
    """把学生作答映射到选项下标（字母 / 圆圈 / 抄正文三种写法都认）。
    判定函数全部复用 grading 里那一份：两处各写一套的话，批改判对、导出画错勾
    这种不一致迟早出现。"""
    from ..grading.engine import _marker, _option_body, _eq
    if not alist:
        return None
    g = str(alist[0]).strip()
    m = _marker(g)
    for i, o in enumerate(options):
        if m:
            om = _marker(str(o))
            if om and om == m:
                return i
            head = re.match(r"^\s*([A-H])", str(o), re.I)
            if m[0] == "L" and head and head.group(1).upper() == m[1]:
                return i
            if m[0] == "N" and int(m[1]) == i + 1:
                return i
        if _eq(str(o), g) or _eq(_option_body(str(o)), g):
            return i
    return None


def _paint(c: rl_canvas.Canvas, questions: list[dict], opt: LayoutOptions, title: str,
           graded: bool, answers: dict, key: dict, grade_result: dict | None,
           class_name: str, student_name: str, total: int | None,
           fig_dir: str | None = None, stats: dict | None = None) -> int:
    ensure_fonts()
    fs = opt.effective_font
    by_uid = {r["uid"]: r for r in (grade_result or {}).get("results", [])}
    c.setTitle(title or "磐卷 PaperForge")
    c.setAuthor("磐卷 PaperForge")
    fl = Flow(c, opt, total=total)

    if opt.show_header:
        c.setFont(_state["family"], 16)
        c.drawString(opt.margin_left, fl.y - 14, (title or "")[:40])
        fl.y -= 30
        if graded and grade_result:
            line = (f"班级 {class_name or '____________'}    "
                    f"姓名 {student_name or '____________'}    "
                    f"得分 {grade_result.get('score', 0)}/{grade_result.get('total', 0)}")
        elif class_name or student_name:
            line = (f"班级 {class_name or '____________'}    "
                    f"姓名 {student_name or '____________'}    得分 ____________")
        else:
            line = "班级 ____________    姓名 ____________    得分 ____________"
        c.setFont(_state["family"], fs)
        c.drawString(opt.margin_left, fl.y - fs, line)
        fl.y -= fl.opt.leading
        c.setStrokeColor(HexColor("#888888"))
        c.setLineWidth(0.6)
        c.line(opt.margin_left, fl.y - 6, A4_W - opt.margin_right, fl.y - 6)
        fl.y -= 14

    last_section = None
    for q in questions:
        uid = str(q.get("uid") or "")
        sec = (q.get("section") or "").strip()
        if sec and sec != last_section:
            fl.space(4)
            fl.text(sec, fs + 1, gap_after=2)
            last_section = sec

        res = by_uid.get(uid, {})
        mark = res.get("verdict") if graded else None
        indent = 16 if mark else 0
        no = q.get("q_no") if q.get("q_no") is not None else q.get("auto_no")
        prefix = f"{no}. " if no is not None else ""
        stem = (q.get("text") or "").strip()
        raw = answers.get(uid)
        alist = raw if isinstance(raw, (list, tuple)) else ([raw] if raw not in (None, "") else [])
        alist = [str(a) for a in alist]
        qtype = (q.get("qtype") or "unknown").lower()
        y0 = fl.y

        if qtype == "choice" and q.get("options"):
            fl.text(f"{prefix}{stem}", fs, indent=indent, gap_after=1)
            pick = _chosen(alist, q["options"])
            for i, o in enumerate(q["options"]):
                fl.need(fl.opt.leading + 2)
                x = opt.margin_left + indent + 8
                y = fl.y - 1
                _option_box(c, x, y, fs * 0.85, checked=(pick == i))
                c.setFont(_state["family"], fs)
                c.drawString(x + fs * 1.2, y - fs * 0.85, str(o))
                fl.y -= fl.opt.leading + 1
        elif qtype == "judge":
            fl.text(f"{prefix}{stem}", fs, indent=indent, gap_after=1)
            fl.need(fl.opt.leading)
            c.setFont(_state["family"], fs)
            x = opt.margin_left + indent + 8
            c.drawString(x, fl.y - fs, "判断：（    ）")
            from ..grading.normalizer import judge_symbol
            s = judge_symbol(alist[0]) if alist else None
            if s:
                _draw_mark(c, "correct" if s == "T" else "wrong",
                           x + _measure("判断：（", fs) + fs * 0.25, fl.y - fs * 0.2, fs * 0.62)
            fl.y -= fl.opt.leading
        elif qtype == "fill":
            filled, extra = _fill_blank(stem, alist)
            text = f"{prefix}{filled}"
            if extra:
                text += "  其余作答：" + "；".join(extra)
            fl.text(text, fs, indent=indent, gap_after=1)
        else:
            fl.text(f"{prefix}{stem}", fs, indent=indent, gap_after=1)
            body = " ".join(alist).strip()
            if body:
                fl.text("答：" + body, fs, indent=indent + 6, gap_after=1)
            else:
                for _ in range(2):
                    fl.need(fl.opt.leading + 6)
                    c.setStrokeColor(HexColor("#BBBBBB"))
                    c.setLineWidth(0.5)
                    c.line(opt.margin_left + indent + 6, fl.y - fs,
                           A4_W - opt.margin_right, fl.y - fs)
                    fl.y -= fl.opt.leading + 6

        _draw_figures(c, q, opt, fl, indent, fig_dir=fig_dir, stats=stats)
        if graded and not alist:
            # 没写的题要显式印「未作答」：否则家长分不清"孩子没写"和"系统漏印了"
            fl.text("（未作答）", fs - 1, indent=indent + 8, gap_after=0)
        if mark:
            _draw_mark(c, mark, opt.margin_left + 1, y0 - 1, fs)
        fl.space(5)

    if graded and grade_result:
        r = grade_result
        wrong = [str(x.get("q_no")) for x in r.get("results", [])
                 if x["verdict"] == "wrong" and x.get("q_no") is not None]
        pend = [str(x.get("q_no")) for x in r.get("results", [])
                if x["verdict"] == "pending" and x.get("q_no") is not None]
        rows = [f"得分 {r.get('score', 0)} ／ 满分 {r.get('total', 0)}"
                f"（另有 {r.get('pending_max', 0)} 分待人工确认）",
                f"判对 {r['counts']['correct']} 题 · 判错 {r['counts']['wrong']} 题"
                f" · 待确认 {r['counts']['pending']} 题",
                f"错题：{'、'.join(wrong) or '无'}　待确认：{'、'.join(pend) or '无'}"]
        fl.space(6)
        h = fl.opt.leading * 3 + 12
        fl.need(h)
        c.setStrokeColor(black)
        c.setLineWidth(0.8)
        c.rect(opt.margin_left, fl.y - h, opt.content_w, h, stroke=1, fill=0)
        c.setFont(_state["family"], fs)
        for i, s in enumerate(rows):
            c.drawString(opt.margin_left + 6, fl.y - fl.opt.leading * i - fs - 4, s[:120])
        fl.y -= h

    if total:
        _draw_footer(c, opt, fl.pno, total)
    c.showPage()
    return fl.pages


def render_answers_pdf(questions: list[dict], opt: LayoutOptions, out_path: str,
                       title: str = "", mode: str = "answered",
                       answers: dict | None = None, key: dict | None = None,
                       grade_result: dict | None = None,
                       class_name: str = "", student_name: str = "",
                       figures_dir: str | None = None) -> dict[str, Any]:
    """mode: answered（模式 B，已作答）| graded（模式 C，批改回传）。

    figures_dir：题目配图所在目录（data/figures/<试卷号>）。库里只存文件名，
    所以必须由调用方给目录，否则图会被静默跳过 —— 这个坑真实发生过，
    现象就是"屏幕上能看到配图，打印出来什么都没有"。"""
    ensure_fonts()
    answers = answers or {}
    key = key or {}
    graded = mode == "graded"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    # 第一趟：数页数（Canvas 不能回头补页码，所以必须先知道 total）
    # ⚠️ 这一趟【必须和第三趟一样带 fig_dir】：配图是往版面里占高度的，
    #    第一趟不画图 → 数出来的页数偏小 → 页脚印成"共 4 页"而实际有 5 页
    #    （真实材料九份卷全部命中，家长一眼就能看出来的那种错）。
    buf = io.BytesIO()
    n = _paint(rl_canvas.Canvas(buf, pagesize=(A4_W, A4_H)), questions, opt, title,
               graded, answers, key, grade_result, class_name, student_name, total=None,
               fig_dir=figures_dir)

    # 第二趟：带页码写到临时文件，再原子改名——客户端只会读到完整文件
    tmp = out_path + ".tmp.pdf"
    c = rl_canvas.Canvas(tmp, pagesize=(A4_W, A4_H))
    stats = {"drawn": 0, "missing": 0}
    pages = _paint(c, questions, opt, title, graded, answers, key, grade_result,
                   class_name, student_name, total=n, fig_dir=figures_dir, stats=stats)
    c.save()
    os.replace(tmp, out_path)

    if getattr(opt, "is_spread", False):
        # 先按 A4 出，再两两并到 A3 横版：模式 A/B/C 共用同一份 A4 版面，
        # 不会出现"打印版和做题版行宽不一样"
        from .spread import a4_to_a3_spread
        r = a4_to_a3_spread(out_path, out_path)
        pages = r["pages_a3"]
    return {"path": out_path, "pages": pages, "mode": mode,
            "figures_drawn": stats["drawn"], "figures_missing": stats["missing"],
            "bytes": os.path.getsize(out_path), "font": _state.get("family"),
            "page_format": getattr(opt, "page_format", "a4")}
