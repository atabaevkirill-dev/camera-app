# -*- coding: utf-8 -*-
"""Video panel: frame display, reticle overlay, digital zoom, screenshots."""

import os
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import profiles
from .reticle import ReticleStyle, draw_reticle
from .stream_worker import (CV2_OK, STATUS_CONNECTING, STATUS_ERROR,
                            STATUS_OFFLINE, STATUS_ONLINE, StreamWorker)

REFRESH_MS = 33
TEXT_UI = "#f4f4f5"

# SENTINEL NVR status colors
_STATUS_COLOR = {
    STATUS_ONLINE: "#34d399",
    STATUS_CONNECTING: "#fbbf24",
    STATUS_ERROR: "#ef4444",
    STATUS_OFFLINE: "#71717a",
}


class VideoPanel(QWidget):
    message = Signal(str)                 # diagnostics for status bar
    recordingChanged = Signal(bool)
    frameOnline = Signal(bool)            # went online/offline

    def __init__(self, reticle: ReticleStyle, cam_index: int, parent=None):
        super().__init__(parent)
        self.cam_index = cam_index            # 0 or 1
        self.reticle = reticle
        self.setMinimumSize(240, 180)
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.StrongFocus)

        self.worker = None
        self._status = STATUS_OFFLINE
        self._qimg = None
        self._qbuf = None
        self._last_seq = -1
        self._fw = 0
        self._fh = 0
        self._frame_rect = QRectF()

        # digital zoom
        self._zoom = 1.0
        self._zoom_cx = 0.5
        self._zoom_cy = 0.5

        # reticle offset (normalized to displayed frame rect)
        self._ret_dx = 0.0
        self._ret_dy = 0.0

        # interaction state
        self._dragging_reticle = False
        self._grab_dx = 0.0
        self._grab_dy = 0.0
        self._selecting = False
        self._sel_rect = QRect()

        self._rec_state = False
        self._painted_status = None

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------- worker link

    def set_worker(self, worker) -> None:
        old = self.worker
        if old is not None:
            try:
                old.statusChanged.disconnect(self._on_status)
                old.message.disconnect(self.message)
            except Exception:
                pass
        self.worker = worker
        self._status = STATUS_OFFLINE
        self._qimg = None
        self._last_seq = -1
        self._zoom = 1.0
        self._zoom_cx = self._zoom_cy = 0.5
        if worker is not None:
            worker.statusChanged.connect(self._on_status)
            worker.message.connect(self.message)
        self.update()

    def _on_status(self, status: str) -> None:
        was_online = self._status == STATUS_ONLINE
        self._status = status
        if (status == STATUS_ONLINE) != was_online:
            self.frameOnline.emit(status == STATUS_ONLINE)
        self.update()

    def _tick(self) -> None:
        w = self.worker
        if w is None or not CV2_OK:
            return
        seq, frame = w.get_frame()
        new_frame = frame is not None and seq != self._last_seq
        if new_frame:
            self._last_seq = seq
            self._qbuf = frame
            h, wd = frame.shape[:2]
            self._qimg = QImage(frame.data, wd, h, wd * 3, QImage.Format_BGR888)
            self._fw, self._fh = wd, h
        # recording state watch
        rec = bool(w.is_recording())
        rec_changed = rec != self._rec_state
        if rec_changed:
            self._rec_state = rec
            self.recordingChanged.emit(rec)
        # Repaint only on change (no 30 fps busy redraw while idle)
        if new_frame or rec_changed or self._painted_status != self._status:
            self._painted_status = self._status
            self.update()
        elif self._rec_state:
            # keep the REC badge dot pulsing while recording
            self.update()

    # ------------------------------------------------------------------ helpers

    def _status_text(self) -> str:
        from .i18n import tr
        if self.worker is None:
            cfg_url = ""
            return tr("status.no_url") if not self._has_url_hint() else tr("status.offline")
        if not CV2_OK:
            return tr("status.nocv")
        return {
            STATUS_CONNECTING: tr("status.connecting"),
            STATUS_ONLINE: tr("status.online"),
            STATUS_ERROR: tr("status.offline"),
        }.get(self._status, tr("status.reconnect"))

    def _has_url_hint(self) -> bool:
        return False

    def is_online(self) -> bool:
        return self.worker is not None and self._status == STATUS_ONLINE

    def is_recording(self) -> bool:
        return self._rec_state

    def center_reticle(self) -> None:
        self._ret_dx = 0.0
        self._ret_dy = 0.0
        self.update()

    def set_reticle_offset_norm(self, dx: float, dy: float) -> None:
        self._ret_dx = max(-1.0, min(1.0, dx))
        self._ret_dy = max(-1.0, min(1.0, dy))
        self.update()

    def get_reticle_offset_norm(self):
        return self._ret_dx, self._ret_dy

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self._zoom_cx = self._zoom_cy = 0.5
        self.update()

    # --------------------------------------------------------------- mapping

    def _widget_to_frame_norm(self, x: float, y: float):
        r = self._frame_rect
        if r.width() <= 0 or r.height() <= 0:
            return 0.5, 0.5
        fx = (x - r.left()) / r.width()
        fy = (y - r.top()) / r.height()
        return max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy))

    def _reticle_widget_pos(self) -> QPointF:
        r = self._frame_rect
        if r.width() <= 0 or r.height() <= 0:
            return QPointF(self.width() / 2.0 + self._ret_dx * self.width(),
                           self.height() / 2.0 + self._ret_dy * self.height())
        return QPointF(r.center().x() + self._ret_dx * r.width(),
                       r.center().y() + self._ret_dy * r.height())

    def _crop_rect_f(self) -> QRectF:
        fw = max(1.0, float(self._fw))
        fh = max(1.0, float(self._fh))
        z = max(1.0, self._zoom)
        zw = fw / z
        zh = fh / z
        x0 = self._zoom_cx * fw - zw / 2.0
        y0 = self._zoom_cy * fh - zh / 2.0
        x0 = max(0.0, min(fw - zw, x0))
        y0 = max(0.0, min(fh - zh, y0))
        return QRectF(x0, y0, zw, zh)

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            self._paint_content(painter, self.width(), self.height(), include_hud=True)
        finally:
            painter.end()

    def _paint_content(self, painter: QPainter, W: int, H: int, include_hud: bool) -> None:
        painter.fillRect(0, 0, W, H, QColor(8, 9, 11))

        if self._qimg is None:
            # SENTINEL NVR surveillance grid + emerald glow (empty state)
            painter.save()
            glow = QRadialGradient(W / 2.0, -H * 0.25, H * 1.1)
            glow.setColorAt(0.0, QColor(52, 211, 153, 18))
            glow.setColorAt(1.0, QColor(52, 211, 153, 0))
            painter.fillRect(0, 0, W, H, glow)
            painter.setPen(QColor(255, 255, 255, 6))
            for gx in range(0, W, 44):
                painter.drawLine(gx, 0, gx, H)
            for gy in range(0, H, 44):
                painter.drawLine(0, gy, W, gy)
            painter.restore()
            painter.setPen(QColor(150, 155, 162))
            painter.setFont(QFont(self.font().family(), 10))
            if include_hud:
                painter.drawText(QRect(0, 0, W, H), Qt.AlignCenter, self._status_text())
            # reticle is visible even without a stream (at widget center)
            pos = self._reticle_widget_pos()
            draw_reticle(painter, pos.x(), pos.y(), self.reticle)
            if include_hud:
                self._paint_hud(painter, W, H)
            if self._selecting and not self._sel_rect.isNull():
                pen = QPen(QColor(52, 211, 153), 1, Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(self._sel_rect)
            self._frame_rect = QRectF()
            return

        fw = float(self._qimg.width())
        fh = float(self._qimg.height())
        scale = min(W / fw, H / fh)
        dw, dh = fw * scale, fh * scale
        dx, dy = (W - dw) / 2.0, (H - dh) / 2.0
        self._frame_rect = QRectF(dx, dy, dw, dh)

        crop = self._crop_rect_f()
        painter.drawImage(self._frame_rect, self._qimg, crop)

        # reticle (drawn in display space, independent of zoom)
        pos = self._reticle_widget_pos()
        draw_reticle(painter, pos.x(), pos.y(), self.reticle)

        if include_hud:
            self._paint_hud(painter, W, H)

        if self._selecting and not self._sel_rect.isNull():
            pen = QPen(QColor(52, 211, 153), 1, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._sel_rect)

    def _paint_hud(self, painter: QPainter, W: int, H: int) -> None:
        import math
        text = self._status_text()
        if self.worker is not None and self._status == STATUS_ONLINE and self._src_fps() > 0:
            text += f"  {self._src_fps():.0f} fps"
        painter.setFont(QFont(self.font().family(), 9, QFont.Bold))
        fm = painter.fontMetrics()

        # status chip: dark rounded plate + colored dot (SENTINEL style)
        dot_color = QColor(_STATUS_COLOR.get(self._status, "#71717a"))
        text_w = fm.horizontalAdvance(text)
        chip_w = text_w + 34
        chip_h = fm.height() + 10
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawRoundedRect(QRectF(6, 6, chip_w, chip_h), 6, 6)
        painter.setBrush(dot_color)
        painter.drawEllipse(QPointF(18, 6 + chip_h / 2.0), 4, 4)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QColor(TEXT_UI))
        painter.drawText(QRect(28, 9, text_w + 6, fm.height() + 4),
                         Qt.AlignLeft | Qt.AlignVCenter, text)

        right_x = W - 8
        if self._rec_state:
            # REC badge: red-tinted plate + pulsing dot
            pulse = 120 + int(110 * abs(math.sin(time.time() * 3.0)))
            painter.setRenderHint(QPainter.Antialiasing, True)
            elapsed = 0.0
            if self.worker is not None:
                try:
                    elapsed = self.worker.rec_elapsed()
                except Exception:
                    elapsed = 0.0
            rec_text = f"REC {int(elapsed // 60):d}:{int(elapsed % 60):02d}"
            rfm_w = fm.horizontalAdvance(rec_text)
            rec_w = rfm_w + 40
            painter.setPen(QColor(239, 68, 68, 100))
            painter.setBrush(QColor(239, 68, 68, 38))
            painter.drawRoundedRect(QRectF(right_x - rec_w, 6, rec_w, chip_h), 6, 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(239, 68, 68, pulse))
            painter.drawEllipse(QPointF(right_x - rec_w + 14, 6 + chip_h / 2.0), 4, 4)
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setPen(QColor("#fca5a5"))
            painter.drawText(QRect(right_x - rfm_w - 14, 9, rfm_w + 6, fm.height() + 4),
                             Qt.AlignRight | Qt.AlignVCenter, rec_text)
            right_x -= rec_w + 8

        if self._zoom > 1.01:
            painter.setPen(QColor(110, 231, 183))
            ztext = f"x{self._zoom:.1f}"
            zw = fm.horizontalAdvance(ztext) + 10
            painter.drawText(QRect(right_x - zw, 9, zw, fm.height() + 2),
                             Qt.AlignRight | Qt.AlignVCenter, ztext)

    def _src_fps(self) -> float:
        if self.worker is not None:
            try:
                return float(self.worker.get_source_fps())
            except Exception:
                return 0.0
        return 0.0

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                self._selecting = True
                self._sel_rect = QRect(int(pos.x()), int(pos.y()), 0, 0)
            else:
                rpos = self._reticle_widget_pos()
                reach = max(34.0, self.reticle.length * 0.6)
                if (QPointF(pos) - rpos).manhattanLength() <= reach:
                    self._dragging_reticle = True
                    self._grab_dx = pos.x() - rpos.x()
                    self._grab_dy = pos.y() - rpos.y()
                    self.setFocus()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._dragging_reticle:
            r = self._frame_rect
            if r.width() > 0:
                cx = pos.x() - self._grab_dx - r.center().x()
                cy = pos.y() - self._grab_dy - r.center().y()
                self._ret_dx = max(-1.0, min(1.0, cx / r.width()))
                self._ret_dy = max(-1.0, min(1.0, cy / r.height()))
                self.update()
        elif self._selecting:
            self._sel_rect.setWidth(int(pos.x()) - self._sel_rect.x())
            self._sel_rect.setHeight(int(pos.y()) - self._sel_rect.y())
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._dragging_reticle:
            self._dragging_reticle = False
            self.update()
        elif event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            self._apply_selection_zoom()
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.reset_zoom()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        pos = event.position()
        fx, fy = self._widget_to_frame_norm(pos.x(), pos.y())
        factor = 1.25 if delta > 0 else 0.8
        new_zoom = max(1.0, min(12.0, self._zoom * factor))
        if new_zoom <= 1.01:
            self._zoom = 1.0
            self._zoom_cx = self._zoom_cy = 0.5
        else:
            self._zoom = new_zoom
            if delta > 0:
                self._zoom_cx, self._zoom_cy = fx, fy
        self.update()

    def _apply_selection_zoom(self) -> None:
        if self._qimg is None or self._frame_rect.width() <= 0:
            return
        r = self._sel_rect.normalized()
        fr = self._frame_rect
        r = r.intersected(QRect(int(fr.left()), int(fr.top()),
                                int(fr.width()), int(fr.height())))
        if r.width() < 12 or r.height() < 12:
            return
        fw, fh = float(self._fw), float(self._fh)
        x0 = (r.left() - fr.left()) / fr.width() * fw
        y0 = (r.top() - fr.top()) / fr.height() * fh
        cw = r.width() / fr.width() * fw
        ch = r.height() / fr.height() * fh
        zoom = max(1.0, min(12.0, fw / max(8.0, cw)))
        if ch * zoom > fh:
            zoom = min(zoom, fh / max(8.0, ch))
        self._zoom = zoom
        self._zoom_cx = max(0.0, min(1.0, (x0 + cw / 2.0) / fw))
        self._zoom_cy = max(0.0, min(1.0, (y0 + ch / 2.0) / fh))

    # ---------------------------------------------------------------- keyboard

    def keyPressEvent(self, event) -> None:
        step = 10 if (event.modifiers() & Qt.ShiftModifier) else 1
        key = event.key()
        if key == Qt.Key_Left:
            self._ret_dx = max(-1.0, self._ret_dx - step * 0.002)
        elif key == Qt.Key_Right:
            self._ret_dx = min(1.0, self._ret_dx + step * 0.002)
        elif key == Qt.Key_Up:
            self._ret_dy = max(-1.0, self._ret_dy - step * 0.002)
        elif key == Qt.Key_Down:
            self._ret_dy = min(1.0, self._ret_dy + step * 0.002)
        elif key == Qt.Key_Home:
            self.center_reticle()
            event.accept()
            return
        else:
            super().keyPressEvent(event)
            return
        self.update()
        event.accept()

    # -------------------------------------------------------------- screenshot

    def screenshot(self, cfg: dict) -> str: # Accept cfg as argument
        """Save current view (frame + reticle) as PNG. Returns path or ''."""
        if self._qimg is None:
            self.message.emit("No frame")
            return ""
        # Use screenshot_dir from cfg
        screenshot_dir = cfg.get("screenshot_dir", profiles.SCREENSHOT_DIR)
        os.makedirs(screenshot_dir, exist_ok=True)
        fname = f"cam{self.cam_index + 1}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(screenshot_dir, fname)
        W, H = self.width(), self.height()
        img = QImage(W, H, QImage.Format_ARGB32)
        painter = QPainter(img)
        try:
            self._paint_content(painter, W, H, include_hud=False)
        finally:
            painter.end()
        ok = img.save(path, "PNG")
        return path if ok else ""
