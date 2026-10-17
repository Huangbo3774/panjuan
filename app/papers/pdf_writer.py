"""试卷 PDF 生成（PRD §4.5）：ReportLab 画版面模型 → A4 PDF。

字体策略（PRD §7.2）：优先系统中文 TTF/TTC 并子集嵌入；拿不到时回退
UnicodeCIDFont('STSong-Light')（不嵌文件，靠阅读器字体，任何 PDF 阅读器都能显示）。
"""
from __future__ import annotations

import os
from typing import Any

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import black, HexColor
from reportlab.pdfgen import canvas as rl_canvas

from ..layout.options import LayoutOptions, A4_W, A4_H

_FONT_CANDIDATES = [
    ("PaperForge-Reg", "C:/Windows/Fonts/msyh.ttc"),
    ("PaperForge-Reg", "C:/Windows/Fonts/msyh.ttf"),
    ("PaperForge-Reg", "C:/Windows/Fonts/simhei.ttf"),
    ("PaperForge-Reg", "C:/Windows/Fonts/simsun.ttc"),
    ("PaperForge-Reg", "C:/Windows/Fonts/simfang.ttf"),
    # Linux / macOS 常见中文字体，开源分发时也能跑
    ("PaperForge-Reg", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("PaperForge-Reg", "/System/Library/Fonts/PingFang.ttc"),
]
_FONT_BOLD_CANDIDATES = [
    ("PaperForge-Bold", "C:/Windows/Fonts/msyhbd.ttc"),
    ("PaperForge-Bold", "C:/Windows/Fonts/simhei.ttf"),
    ("PaperForge-Bold", "C:/Windows/Fonts/simbdi.ttf"),
    ("PaperForge-Bold", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
]

REGULAR = "PaperForge-Reg"
BOLD = "PaperForge-Bold"
_state: dict[str, Any] = {"registered": False, "family": None, "note": ""}


def ensure_fonts() -> dict[str, Any]:
    """注册中文字体。幂等；返回 {family, bold, note}。"""
    if _state["registered"]:
        return _state
    got_reg = got_bold = False
    for name, path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                got_reg = True
                _state["family"] = name
                _state["note"] = f"嵌入 {os.path.basename(path)}"
                break
            except Exception:
                continue
    if not got_reg:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _state["family"] = "STSong-Light"
        _state["note"] = "未找到系统中文字体，回退 CID STSong-Light（不嵌文件）"
        BOLD_NAME = "STSong-Light"
    else:
        for name, path in _FONT_BOLD_CANDIDATES:
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    got_bold = True
                    BOLD_NAME = name
                    break
                except Exception:
                    continue
        BOLD_NAME = _state["family"] if not got_bold else BOLD_NAME
    globals()["BOLD"] = BOLD_NAME
    try:
        registerFontFamily(_state["family"], normal=_state["family"], bold=BOLD_NAME,
                           italic=_state["family"], boldItalic=BOLD_NAME)
    except Exception:
        pass
    _state["registered"] = True
    _state["bold"] = BOLD_NAME
    return _state


def _measure(text: str, font_size: float) -> float:
    ensure_fonts()
    try:
        return pdfmetrics.stringWidth(text, _state["family"], font_size)
    except Exception:
        return font_size * sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in text)


def bind_metrics() -> None:
    """把精确测量函数注入布局引擎（布局必须在注册字体后跑才准）。"""
    from ..layout import engine
    engine.set_metrics(_measure)


def _draw_header(c: rl_canvas.Canvas, opt: LayoutOptions, title: str) -> None:
    if not opt.show_header:
        return
    top = A4_H - opt.margin_top
    c.setFont(_state["family"], 16)
    c.drawString(opt.margin_left, top - 14, (title or "")[:40])
    c.setFont(_state["family"], opt.effective_font)
    line_y = top - 36
    label = "班级 ____________    姓名 ____________    得分 ____________"
    c.drawString(opt.margin_left, line_y, label)
    c.setStrokeColor(HexColor("#888888"))
    c.setLineWidth(0.6)
    c.line(opt.margin_left, line_y - 7, A4_W - opt.margin_right, line_y - 7)


def _draw_footer(c: rl_canvas.Canvas, opt: LayoutOptions, no: int, total: int) -> None:
    c.setFont(_state["family"], 9)
    c.setFillColor(HexColor("#555555"))
    txt = f"第 {no} 页 / 共 {total} 页"
    c.drawCentredString(A4_W / 2, opt.margin_bottom - 12, txt)
    c.drawRightString(A4_W - opt.margin_right, opt.margin_bottom - 12, "磐卷 PaperForge")
    c.setFillColor(black)


def _as_jpeg(path: str, cache_dir: str, quality: int = 82) -> str:
    """清洗产物是 PNG（无损），8 页扫描卷内嵌后会到 12 MB，微信传不动也打不开。
    灰度文档图转 JPEG q82 视觉无损且体积小一个数量级。带缓存，不重复转。
    """
    os.makedirs(cache_dir, exist_ok=True)
    key = os.path.splitext(os.path.basename(path))[0] + f"_q{quality}.jpg"
    out = os.path.join(cache_dir, key)
    if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(path):
        return out
    try:
        from PIL import Image
        with Image.open(path) as im:
            if im.mode not in ("L", "RGB"):
                im = im.convert("RGB")
            im.save(out, "JPEG", quality=quality, optimize=True)
        return out
    except Exception:
        return path


def render_pdf(model: dict[str, Any], opt: LayoutOptions, out_path: str,
               title: str = "", image_cache_dir: str | None = None,
               gray: bool = True) -> dict[str, Any]:
    """把版面模型画成 PDF。返回 {path, bytes, pages, font}。"""
    st = ensure_fonts()
    fam, bold = st["family"], _state.get("bold", st["family"])
    cache = image_cache_dir or (os.path.dirname(out_path) + "/_jpg")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    # 先写 .tmp 再原子改名：否则「改选项 → 后台重排」期间客户端能读到半截 PDF
    # （验收 F05/F06 实测报 IncompleteRead: 0 bytes read, 510465 more expected）
    tmp = out_path + ".tmp.pdf"
    c = rl_canvas.Canvas(tmp, pagesize=(A4_W, A4_H))
    c.setTitle(title or opt.title or "磐卷试卷")
    c.setAuthor("磐卷 PaperForge")
    total = len(model["pages"])

    for pg in model["pages"]:
        base_y = A4_H - opt.margin_top - (52.0 if opt.show_header else 0.0)
        _draw_header(c, opt, title or opt.title)
        for b in pg["blocks"]:
            if b["type"] == "image":
                try:
                    jp = _as_jpeg(b["path"], cache)
                    if b.get("rot") == 90:
                        # 绕图中心逆时针转 90°：先平移坐标系，再按旋转后的框画
                        cx, cy = opt.margin_left + b["x"] + b["w"] / 2, base_y - b["y"] - b["h"] / 2
                        c.saveState()
                        c.translate(cx, cy)
                        c.rotate(90)
                        c.drawImage(jp, -b["h"] / 2, -b["w"] / 2, width=b["h"], height=b["w"],
                                    preserveAspectRatio=True, mask="auto")
                        c.restoreState()
                    else:
                        c.drawImage(jp, opt.margin_left + b["x"], base_y - b["y"] - b["h"],
                                    width=b["w"], height=b["h"], preserveAspectRatio=True, mask="auto")
                except Exception as e:
                    c.setFont(fam, 9)
                    c.drawString(opt.margin_left, base_y - b["y"], f"[图片无法嵌入: {e}]")
                continue
            size = b.get("size") or opt.effective_font
            c.setFont(bold if b.get("bold") else fam, size)
            leading = size * opt.line_spacing
            yy = base_y - b["y"]
            for ln in b["lines"]:
                c.drawString(opt.margin_left + b["x"], yy, ln)
                yy -= leading
        _draw_footer(c, opt, pg["no"], total)
        c.showPage()
    c.save()
    os.replace(tmp, out_path)          # 原子替换，读者只会看到完整文件

    size = os.path.getsize(out_path)
    return {"path": out_path, "bytes": size, "pages": total, "font": st.get("note")}
