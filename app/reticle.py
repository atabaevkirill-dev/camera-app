# -*- coding: utf-8 -*-
"""Camera reticle model: sniper styles, geometry builder and painter."""

from dataclasses import dataclass, asdict, fields

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen

STYLE_CROSS = "cross"
STYLE_DUPLEX = "duplex"
STYLE_MIL_DOT = "mil_dot"

STYLE_KEYS = (STYLE_CROSS, STYLE_DUPLEX, STYLE_MIL_DOT)


@dataclass
class ReticleStyle:
    style: str = STYLE_CROSS
    color: str = "#00ff00"
    thickness: int = 2        # line width, px
    length: int = 80          # arm length, px
    gap: int = 14             # center gap, px
    opacity: int = 90         # percent
    outline: bool = True
    center_dot: bool = True
    # duplex
    thick_len: int = 34       # thick outer section length, px
    thick_mult: int = 3       # thickness multiplier for thick section
    # mil-dot
    dots: int = 4
    dot_spacing: int = 16
    dot_radius: int = 2

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ReticleStyle":
        rs = ReticleStyle()
        if not isinstance(data, dict):
            return rs
        names = {f.name for f in fields(ReticleStyle)}
        for k, v in data.items():
            if k in names:
                try:
                    setattr(rs, k, v)
                except Exception:
                    pass
        if rs.style not in STYLE_KEYS:
            rs.style = STYLE_CROSS
        return rs

    def apply(self, other: "ReticleStyle") -> None:
        for f in fields(ReticleStyle):
            setattr(self, f.name, getattr(other, f.name))

    def copy(self) -> "ReticleStyle":
        return ReticleStyle.from_dict(self.to_dict())


def _clamp_int(v, lo, hi, default):
    try:
        v = int(v)
    except Exception:
        return default
    return max(lo, min(hi, v))


def build_geometry(cx: float, cy: float, rs: ReticleStyle):
    """Return (segments, dots). segments: (x1, y1, x2, y2, width). dots: (x, y, r)."""
    t = _clamp_int(rs.thickness, 1, 12, 2)
    L = _clamp_int(rs.length, 10, 600, 80)
    g = _clamp_int(rs.gap, 0, 200, 14)

    segs, dots = [], []
    dirs = ((0, -1), (0, 1), (-1, 0), (1, 0))

    if rs.style == STYLE_DUPLEX:
        thick_w = max(1, int(round(t * _clamp_int(rs.thick_mult, 2, 8, 3))))
        thick_len = _clamp_int(rs.thick_len, 4, 400, 34)
        thin_len = max(0, L - thick_len)
        for dx, dy in dirs:
            x0, y0 = cx + dx * g, cy + dy * g
            x1, y1 = cx + dx * (g + thin_len), cy + dy * (g + thin_len)
            x2, y2 = cx + dx * (g + L), cy + dy * (g + L)
            if thin_len > 0:
                segs.append((x0, y0, x1, y1, t))
            segs.append((x1, y1, x2, y2, thick_w))
    elif rs.style == STYLE_MIL_DOT:
        dots_n = _clamp_int(rs.dots, 0, 10, 4)
        spacing = _clamp_int(rs.dot_spacing, 3, 120, 16)
        radius = _clamp_int(rs.dot_radius, 1, 8, 2)
        for dx, dy in dirs:
            segs.append((cx + dx * g, cy + dy * g, cx + dx * (g + L), cy + dy * (g + L), t))
            for i in range(1, dots_n + 1):
                d = g + i * spacing
                if d > g + L:
                    break
                dots.append((cx + dx * d, cy + dy * d, radius))
    else:  # cross
        for dx, dy in dirs:
            segs.append((cx + dx * g, cy + dy * g, cx + dx * (g + L), cy + dy * (g + L), t))

    if rs.center_dot:
        dots.append((cx, cy, max(1.0, t * 0.8)))

    return segs, dots


def _paint_geometry(painter: QPainter, segs, dots, color: QColor, grow: float) -> None:
    painter.setRenderHint(QPainter.Antialiasing, True)
    for (x1, y1, x2, y2, w) in segs:
        pen = QPen(color, max(1.0, w + grow))
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    for (x, y, r) in dots:
        rr = r + grow * 0.5 if grow else r
        painter.drawEllipse(QPointF(x, y), rr, rr)


def draw_reticle(painter: QPainter, cx: float, cy: float, rs: ReticleStyle) -> None:
    """Draw reticle centered at (cx, cy) in current painter coordinates."""
    segs, dots = build_geometry(cx, cy, rs)
    col = QColor(rs.color)
    if not col.isValid():
        col = QColor("#00ff00")
    alpha = max(0.1, min(1.0, rs.opacity / 100.0))
    col.setAlphaF(alpha)

    if rs.outline:
        ocol = QColor(0, 0, 0)
        ocol.setAlphaF(alpha * 0.9)
        _paint_geometry(painter, segs, dots, ocol, grow=2.0)

    _paint_geometry(painter, segs, dots, col, grow=0.0)
