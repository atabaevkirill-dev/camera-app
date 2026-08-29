# -*- coding: utf-8 -*-
"""Vector line icons (reference: lucide-style), drawn with QPainter.

icon(name, color, size) -> QIcon. Crisp at any size — effectively SVG buttons.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen,
                           QPixmap, QGuiApplication)

_PEN = 1.8


def _dpr() -> float:
    scr = QGuiApplication.primaryScreen()
    return max(1.0, scr.devicePixelRatio() if scr is not None else 1.0)


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    dpr = _dpr()
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    c = QColor(color)
    pen = QPen(c, _PEN)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = size
    u = s / 24.0  # 24x24 design grid like lucide

    def path():
        q = QPainterPath()
        return q

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1 * u, y1 * u), QPointF(x2 * u, y2 * u))

    if name == "monitor":
        p.drawRoundedRect(QRectF(3 * u, 4 * u, 18 * u, 12 * u), 2 * u, 2 * u)
        line(12, 16, 12, 20)
        line(8, 20, 16, 20)
    elif name == "folder":
        q = path()
        q.moveTo(3 * u, 7 * u)
        q.lineTo(3 * u, 18 * u)
        q.lineTo(21 * u, 18 * u)
        q.lineTo(21 * u, 9 * u)
        q.lineTo(11 * u, 9 * u)
        q.lineTo(9 * u, 6.5 * u)
        q.lineTo(3 * u, 6.5 * u)
        p.drawPath(q)
    elif name == "scissors":
        p.drawEllipse(QPointF(6 * u, 6 * u), 2.6 * u, 2.6 * u)
        p.drawEllipse(QPointF(6 * u, 18 * u), 2.6 * u, 2.6 * u)
        line(8.2, 7.6, 20, 18)
        line(8.2, 16.4, 20, 6)
    elif name == "settings":
        line(4, 7, 20, 7); line(4, 12, 20, 12); line(4, 17, 20, 17)
        p.setBrush(QColor(color))
        for (x, y) in ((9, 7), (15, 12), (7, 17)):
            p.drawEllipse(QPointF(x * u, y * u), 2 * u, 2 * u)
            p.setBrush(Qt.NoBrush)
    elif name == "refresh":
        q = path()
        q.moveTo(20 * u, 5 * u)
        q.lineTo(20 * u, 10 * u)
        q.lineTo(15 * u, 10 * u)
        p.drawPath(q)
        p.drawArc(QRectF(4 * u, 4 * u, 16 * u, 16 * u), 30 * 16, 300 * 16)
    elif name == "play":
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        q = path()
        q.moveTo(8 * u, 5 * u); q.lineTo(19 * u, 12 * u); q.lineTo(8 * u, 19 * u)
        p.drawPolygon(q) if False else p.drawPath(q)
    elif name == "pause":
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(7 * u, 5 * u, 3.4 * u, 14 * u), 1 * u, 1 * u)
        p.drawRoundedRect(QRectF(13.6 * u, 5 * u, 3.4 * u, 14 * u), 1 * u, 1 * u)
    elif name == "stop":
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(6.5 * u, 6.5 * u, 11 * u, 11 * u), 2 * u, 2 * u)
    elif name == "record":
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(12 * u, 12 * u), 6 * u, 6 * u)
    elif name == "film":
        p.drawRoundedRect(QRectF(3 * u, 4 * u, 18 * u, 16 * u), 2 * u, 2 * u)
        for yy in (7, 12, 17):
            line(7, yy - 1.6, 7, yy + 1.6) if False else None
        for xx in (7, 17):
            line(xx, 4, xx, 8); line(xx, 16, xx, 20)
        line(7, 12, 17, 12)
    elif name == "trash":
        line(4, 7, 20, 7)
        q = path()
        q.moveTo(6 * u, 7 * u); q.lineTo(7.2 * u, 20 * u); q.lineTo(16.8 * u, 20 * u)
        q.lineTo(18 * u, 7 * u)
        p.drawPath(q)
        line(10, 4, 14, 4)
        line(10, 11, 10, 16); line(14, 11, 14, 16)
    elif name == "download":
        line(12, 4, 12, 15)
        q = path(); q.moveTo(7 * u, 11 * u); q.lineTo(12 * u, 16 * u); q.lineTo(17 * u, 11 * u)
        p.drawPath(q)
        line(4, 20, 20, 20)
    elif name == "external":
        p.drawRoundedRect(QRectF(4 * u, 4 * u, 16 * u, 16 * u), 2 * u, 2 * u)
        line(10, 14, 19, 5)
        q = path(); q.moveTo(14 * u, 5 * u); q.lineTo(19 * u, 5 * u); q.lineTo(19 * u, 10 * u)
        p.drawPath(q)
    elif name == "reveal":
        q = path()
        q.moveTo(3 * u, 7 * u); q.lineTo(3 * u, 18 * u); q.lineTo(21 * u, 18 * u)
        q.lineTo(21 * u, 9 * u); q.lineTo(11 * u, 9 * u); q.lineTo(9 * u, 6.5 * u)
        q.lineTo(3 * u, 6.5 * u)
        p.drawPath(q)
        line(14, 13, 19, 13)
        q = path(); q.moveTo(17 * u, 11 * u); q.lineTo(19 * u, 13 * u); q.lineTo(17 * u, 15 * u)
        p.drawPath(q)
    elif name == "search":
        p.drawEllipse(QPointF(10.5 * u, 10.5 * u), 6 * u, 6 * u)
        line(15, 15, 20, 20)
    elif name == "camera":
        q = path()
        q.moveTo(3 * u, 8 * u); q.lineTo(8 * u, 8 * u); q.lineTo(10 * u, 5 * u)
        q.lineTo(14 * u, 5 * u); q.lineTo(16 * u, 8 * u); q.lineTo(21 * u, 8 * u)
        q.lineTo(21 * u, 19 * u); q.lineTo(3 * u, 19 * u)
        p.drawPath(q)
        p.drawEllipse(QPointF(12 * u, 13 * u), 3.2 * u, 3.2 * u)
    elif name == "shield":
        q = path()
        q.moveTo(12 * u, 3 * u); q.lineTo(20 * u, 6 * u); q.lineTo(20 * u, 12 * u)
        q.lineTo(12 * u, 21 * u); q.lineTo(4 * u, 12 * u); q.lineTo(4 * u, 6 * u)
        p.drawPath(q)
    elif name == "clock":
        p.drawEllipse(QPointF(12 * u, 12 * u), 8 * u, 8 * u)
        line(12, 7, 12, 12); line(12, 12, 16, 14)
    elif name == "convert":
        q = path(); q.moveTo(4 * u, 8 * u); q.lineTo(17 * u, 8 * u); q.lineTo(13.5 * u, 4.5 * u)
        p.drawPath(q)
        q = path(); q.moveTo(20 * u, 16 * u); q.lineTo(7 * u, 16 * u); q.lineTo(10.5 * u, 19.5 * u)
        p.drawPath(q)
    elif name == "chevron_down":
        q = path(); q.moveTo(7 * u, 10 * u); q.lineTo(12 * u, 15 * u); q.lineTo(17 * u, 10 * u)
        p.drawPath(q)
    elif name == "chevron_left":
        q = path(); q.moveTo(14 * u, 7 * u); q.lineTo(9 * u, 12 * u); q.lineTo(14 * u, 17 * u)
        p.drawPath(q)
    elif name == "chevron_right":
        q = path(); q.moveTo(10 * u, 7 * u); q.lineTo(15 * u, 12 * u); q.lineTo(10 * u, 17 * u)
        p.drawPath(q)
    elif name == "check":
        q = path(); q.moveTo(5 * u, 12.5 * u); q.lineTo(10 * u, 17.5 * u); q.lineTo(19 * u, 7 * u)
        p.drawPath(q)
    else:  # dot fallback
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(12 * u, 12 * u), 4 * u, 4 * u)
    p.end()
    return pm


def icon(name: str, color: str = "#d4d4d8", size: int = 18) -> QIcon:
    return QIcon(_pixmap(name, color, size))


def set_button_icon(button, name: str, color: str = "#d4d4d8", size: int = 18) -> None:
    button.setIcon(icon(name, color, size))
    button.setIconSize(_pixmap(name, color, size).size())
