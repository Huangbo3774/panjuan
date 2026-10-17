"""排版选项（PRD §4.4 的打印选项面板对应物）。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

MM = 72.0 / 25.4          # 1mm = 72/25.4 pt
A4_W = 595.28
A4_H = 841.89


@dataclass
class LayoutOptions:
    margin_top: float = 25 * MM          # 默认 25mm
    margin_bottom: float = 25 * MM
    margin_left: float = 20 * MM         # 默认 20mm
    margin_right: float = 20 * MM
    font_size: float = 12.0              # 小四；PRD 允许 10–16
    line_spacing: float = 1.5
    font_scale: float = 1.0              # 80%–150%
    color_mode: str = "gray"             # gray | mono | color
    ink_saver: bool = False              # 省墨模式：强制二值化 + 白底
    two_up: bool = False                 # 2 合 1
    show_header: bool = True             # 班级/姓名/得分 栏
    title: str = ""
    image_gap: float = 8.0

    def clamp(self) -> "LayoutOptions":
        self.font_size = min(max(self.font_size, 8.0), 20.0)
        self.font_scale = min(max(self.font_scale, 0.6), 1.8)
        for name in ("margin_top", "margin_bottom"):
            v = getattr(self, name)
            setattr(self, name, min(max(v, 8 * MM), 45 * MM))
        for name in ("margin_left", "margin_right"):
            v = getattr(self, name)
            setattr(self, name, min(max(v, 8 * MM), 45 * MM))
        return self

    @property
    def content_w(self) -> float:
        return A4_W - self.margin_left - self.margin_right

    @property
    def content_h(self) -> float:
        top = self.margin_top + (52.0 if self.show_header else 0.0)
        bottom = self.margin_bottom + 22.0            # 页脚页码
        return A4_H - top - bottom

    @property
    def effective_font(self) -> float:
        return round(self.font_size * self.font_scale, 2)

    @property
    def leading(self) -> float:
        return round(self.effective_font * self.line_spacing, 2)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "LayoutOptions":
        o = LayoutOptions()
        for k, v in (d or {}).items():
            if hasattr(o, k) and v is not None:
                try:
                    setattr(o, k, type(getattr(o, k))(v))
                except (TypeError, ValueError):
                    pass
        return o.clamp()
