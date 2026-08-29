# -*- coding: utf-8 -*-
"""Archive dialog: widget-card gallery, filters, internal player, conversion.

Reference: Sentinel NVR ArchiveView (glass filter bar, thumbnail cards with
badges, player dialog with metadata grid, incremental pagination).
"""

import os
import subprocess
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal, QPointF
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QImage,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSlider,
                               QVBoxLayout, QWidget)

from .i18n import tr
from .icons import icon, set_button_icon
from .logutil import get_logger
from .media_convert import transcode_to_h264, probe_codec, is_playable
from . import theme
from .theme import ACCENT, TEXT, TEXT2, TEXT_MUTED, TEXT_SOFT

log = get_logger("archive_dialog")

try:
    import cv2
    CV2_OK = True
except Exception:
    CV2_OK = False

PAGE_SIZE = 24
CARD_W = 320
THUMB_H = 180
INFO_H = 70
CARD_H = THUMB_H + INFO_H


def fmt_size(num_bytes) -> str:
    try:
        b = float(num_bytes or 0)
    except (TypeError, ValueError):
        b = 0.0
    for unit, factor in (("ГБ", 1024 ** 3), ("МБ", 1024 ** 2), ("КБ", 1024.0)):
        if b >= factor:
            return f"{b / factor:.1f} {unit}"
    return f"{int(b)} Б"


def fmt_duration(sec) -> str:
    try:
        s = int(float(sec or 0))
    except (TypeError, ValueError):
        return "—"
    h, rem = divmod(s, 3600)
    m, s2 = divmod(rem, 60)
    return f"{h}:{m:02d}:{s2:02d}" if h else f"{m}:{s2:02d}"


def mono_font() -> QFont:
    return QFontDatabase.systemFont(QFontDatabase.FixedFont)


class ArchiveLoader(QThread):
    finished = Signal(list)

    def __init__(self, db, base_dirs: dict, search_params: dict, parent=None):
        super().__init__(parent)
        self.db = db
        self.base_dirs = base_dirs
        self.search_params = search_params

    def run(self):
        try:
            items = self.db.search_items(self.base_dirs, **self.search_params)
            self.finished.emit(items)
        except Exception as e:
            log.error("Archive load failed: %s", e)
            self.finished.emit([])


# ----------------------------------------------------------------- card UI

class ThumbLabel(QWidget):
    """16:9 thumbnail with reference-style badges and hover play overlay."""

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.hovered = False
        self.setFixedSize(CARD_W - 2, THUMB_H)
        self._pixmap = QPixmap(item.get("thumbnail_path") or "")
        self._mono = mono_font()

    def set_item(self, item: dict):
        self.item = item
        self._pixmap = QPixmap(item.get("thumbnail_path") or "")
        self.update()

    def enterEvent(self, _):
        self.hovered = True
        self.update()

    def leaveEvent(self, _):
        self.hovered = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0b0e0c"))
        p.drawRoundedRect(0, 0, w, h, 9, 9)

        clip = QPainterPath()
        clip.addRoundedRect(0, 0, w, h, 9, 9)
        p.setClipPath(clip)
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(w, h, Qt.KeepAspectRatioByExpanding,
                                         Qt.SmoothTransformation)
            p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
        else:
            # film placeholder: play triangle on dark plate
            p.setBrush(QColor(255, 255, 255, 24))
            r = 26.0
            tri = QPolygonF([QPointF(w / 2 - r / 2, h / 2 - r * 0.8),
                             QPointF(w / 2 - r / 2, h / 2 + r * 0.8),
                             QPointF(w / 2 + r * 0.87, h / 2)])
            p.drawPolygon(tri)

        # hover play overlay (reference style)
        if self.hovered:
            p.setBrush(QColor(0, 0, 0, 150))
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawEllipse(QPointF(w / 2, h / 2), 24, 24)
            p.setBrush(QColor(255, 255, 255, 230))
            p.setPen(Qt.NoPen)
            r = 14.0
            tri = QPolygonF([QPointF(w / 2 - r / 2 + 3, h / 2 - r * 0.75),
                             QPointF(w / 2 - r / 2 + 3, h / 2 + r * 0.75),
                             QPointF(w / 2 + r * 0.87 + 3, h / 2)])
            p.drawPolygon(tri)
        p.setClipping(False)

        # badges
        fm = QFontMetrics(self._mono)
        is_rec = self.item.get("item_type") == "recording"
        badge = fmt_duration(self.item.get("duration_sec")) if is_rec else \
            (os.path.splitext(self.item.get("rel_path", ""))[1].lstrip(".").upper() or "PNG")
        bw = max(26, fm.horizontalAdvance(badge) + 12)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 178))
        p.drawRoundedRect(w - bw - 8, h - 25, bw, 17, 4, 4)
        p.setPen(QColor("#e4e4e7"))
        p.setFont(self._mono)
        p.drawText(w - bw - 2, h - 25, bw, 17, Qt.AlignVCenter | Qt.AlignLeft, badge)

        chip = tr("arch.recording").upper() if is_rec else tr("arch.screenshot").upper()
        cw = fm.horizontalAdvance(chip) + 12
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(52, 211, 153, 46) if is_rec else QColor(255, 255, 255, 36))
        p.drawRoundedRect(8, 8, cw, 17, 4, 4)
        p.setPen(QColor("#a7f3d0") if is_rec else QColor("#d4d4d8"))
        p.drawText(14, 8, cw, 17, Qt.AlignVCenter | Qt.AlignLeft, chip)
        p.end()


class ArchiveCard(QFrame):
    """Gallery card: thumbnail + name + date/camera + type/size meta."""

    def __init__(self, item: dict, dialog: "ArchiveDialog", parent=None):
        super().__init__(parent)
        self.setObjectName("archCard")
        self.dialog = dialog
        self.item = item
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.thumb = ThumbLabel(item)
        lay.addWidget(self.thumb)

        info = QWidget()
        info_lay = QVBoxLayout(info)
        info_lay.setContentsMargins(10, 7, 10, 8)
        info_lay.setSpacing(2)

        name = os.path.basename(item.get("full_path") or item.get("rel_path") or "?")
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px; border: none; background: transparent;")
        when = datetime.fromtimestamp(item.get("timestamp") or 0).strftime("%d.%m.%Y %H:%M:%S")
        cam_n = item.get("camera_index")
        cam = tr("arch.cam1") if cam_n == 0 else tr("arch.cam2") if cam_n == 1 else \
              tr("arch.cam_both") if cam_n == 2 else tr("arch.cam")
        date_lbl = QLabel(f"{when} · {cam}")
        date_lbl.setFont(mono_font())
        date_lbl.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 10px; border: none; background: transparent;")
        is_rec = item.get("item_type") == "recording"
        itype = tr("arch.recording") if is_rec else tr("arch.screenshot")
        meta_lbl = QLabel(f"{itype} · {fmt_size(item.get('size_bytes'))}")
        meta_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none; background: transparent;")
        info_lay.addWidget(name_lbl)
        info_lay.addWidget(date_lbl)
        info_lay.addWidget(meta_lbl)
        lay.addWidget(info)

    def set_item(self, item: dict):
        self.item = item
        self.thumb.set_item(item)
        self._refresh_selected()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dialog.select_card(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dialog._open_player(self.item)
        super().mouseDoubleClickEvent(event)

    def _refresh_selected(self):
        selected = self.item.get("id") == self.dialog._selected_id
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


# ------------------------------------------------------------------ dialog

class ArchiveGallery(QWidget):
    openAppSettings = Signal()
    openEditorRequested = Signal(str)  # recording path

    def __init__(self, db, base_dirs: dict, parent=None):
        super().__init__(parent)
        self.db = db
        self.base_dirs = base_dirs
        self._items = []
        self._visible_count = PAGE_SIZE
        self._cards = {}
        self._selected_id = None
        self.loader_thread = None
        self._mono = mono_font()

        self._init_ui()
        self._load_archive()

    def refresh(self):
        """Reload when the view becomes visible."""
        self._load_archive()

    # ------------------------------------------------------------------- UI

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- filters card (glass)
        filter_card = QFrame()
        filter_card.setObjectName("glassCard")
        frow = QHBoxLayout(filter_card)
        frow.setContentsMargins(12, 10, 12, 10)
        frow.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("arch.filter_ph"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._perform_search)
        frow.addWidget(self.search_input, 2)

        self.filter_type_combo = QComboBox()
        self.filter_type_combo.addItem(tr("arch.all_types"))
        self.filter_type_combo.addItem(tr("arch.only_screenshots"))
        self.filter_type_combo.addItem(tr("arch.only_recordings"))
        self.filter_type_combo.currentIndexChanged.connect(self._perform_search)
        frow.addWidget(self.filter_type_combo)

        self.filter_cam_combo = QComboBox()
        self.filter_cam_combo.addItem(tr("arch.all_cams"))
        self.filter_cam_combo.addItem(tr("arch.cam1"))
        self.filter_cam_combo.addItem(tr("arch.cam2"))
        self.filter_cam_combo.currentIndexChanged.connect(self._perform_search)
        frow.addWidget(self.filter_cam_combo)

        self.counter_label = QLabel("")
        self.counter_label.setObjectName("hudMeta")
        self.counter_label.setFont(self._mono)
        frow.addStretch(1)
        frow.addWidget(self.counter_label)
        layout.addWidget(filter_card)

        # ---- gallery: scroll area + grid of cards
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("rootSurface")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        layout.addWidget(self.scroll, 1)

        # ---- show more + empty state
        more_row = QHBoxLayout()
        more_row.addStretch(1)
        self.more_btn = QPushButton()
        self.more_btn.clicked.connect(self._show_more)
        more_row.addWidget(self.more_btn)
        more_row.addStretch(1)
        layout.addLayout(more_row)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("glassCard")
        empty_lay = QVBoxLayout(self.empty_card)
        empty_lay.setContentsMargins(24, 40, 24, 40)
        empty_lay.setSpacing(8)
        empty_title = QLabel(tr("arch.empty_title"))
        empty_title.setAlignment(Qt.AlignCenter)
        empty_title.setStyleSheet(f"color: {TEXT2}; font-weight: 600; font-size: 14px;")
        self.empty_hint = QLabel(tr("arch.empty_hint"))
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
        empty_btn = QPushButton(tr("arch.open_app_settings"))
        empty_btn.clicked.connect(self.openAppSettings.emit)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(empty_btn)
        btn_row.addStretch(1)
        empty_lay.addWidget(empty_title)
        empty_lay.addWidget(self.empty_hint)
        empty_lay.addLayout(btn_row)
        layout.addWidget(self.empty_card)

        # ---- bottom buttons
        button_layout = QHBoxLayout()
        self.refresh_btn = QPushButton(tr("arch.refresh"))
        self.open_btn = QPushButton(tr("arch.open"))
        self.delete_btn = QPushButton(tr("arch.delete"))
        self.refresh_btn.clicked.connect(self._load_archive)
        self.open_btn.clicked.connect(self._open_selected)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.delete_btn.setProperty("buttonRole", "danger")
        set_button_icon(self.refresh_btn, "refresh", theme.TEXT2, 16)
        set_button_icon(self.open_btn, "external", theme.TEXT2, 16)
        set_button_icon(self.delete_btn, "trash", "#f87171", 16)
        button_layout.addStretch(1)
        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.open_btn)
        button_layout.addWidget(self.delete_btn)
        layout.addLayout(button_layout)

    # --------------------------------------------------------------- helpers

    def _get_search_params(self) -> dict:
        type_filter = self.filter_type_combo.currentIndex()
        cam_filter = self.filter_cam_combo.currentIndex()
        item_types = None
        if type_filter == 1:
            item_types = ["screenshot"]
        elif type_filter == 2:
            item_types = ["recording"]
        camera_indices = None
        if cam_filter == 1:
            camera_indices = [0]
        elif cam_filter == 2:
            camera_indices = [1]
        return {
            "search_term": self.search_input.text().strip(),
            "item_types": item_types,
            "camera_indices": camera_indices,
        }

    def _columns(self) -> int:
        viewport_w = max(360, self.scroll.viewport().width())
        return max(2, viewport_w // (CARD_W + 14))

    def select_card(self, card: ArchiveCard):
        self._selected_id = card.item.get("id")
        for c in self._cards.values():
            c._refresh_selected()

    # --------------------------------------------------------------- loading

    def _on_search_changed(self):
        self._search_timer.start()

    def _load_archive(self):
        self._load_with_params(self._get_search_params())

    def _perform_search(self):
        self._load_with_params(self._get_search_params())

    def _load_with_params(self, params: dict):
        if self.loader_thread is not None and self.loader_thread.isRunning():
            self.loader_thread.wait(1500)
        self.loader_thread = ArchiveLoader(self.db, self.base_dirs, params, self)
        self.loader_thread.finished.connect(self._on_loaded)
        self.loader_thread.start()

    def _on_loaded(self, items: list):
        self._items = items or []
        self._visible_count = PAGE_SIZE
        self._populate()

    def _show_more(self):
        self._visible_count += PAGE_SIZE
        self._populate()

    def _populate(self):
        # clear grid
        self._cards = {}
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        cols = self._columns()
        visible = self._items[:self._visible_count]
        for i, item in enumerate(visible):
            card = ArchiveCard(item, self)
            self._cards[item.get("id")] = card
            self.grid.addWidget(card, i // cols, i % cols)
        self._selected_id = None

        has_more = len(self._items) > len(visible)
        self.more_btn.setVisible(has_more)
        if has_more:
            self.more_btn.setText(tr("arch.show_more", n=len(self._items) - len(visible)))
        empty = not self._items
        self.empty_card.setVisible(empty)
        self.scroll.setVisible(not empty)
        self.more_btn.setVisible(has_more and not empty)
        total_bytes = sum(i.get("size_bytes") or 0 for i in self._items)
        self.counter_label.setText(tr("arch.count", n=len(self._items),
                                      size=fmt_size(total_bytes)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._cards and self.isVisible():
            cols = self._columns()
            if self.grid.columnCount() != cols:
                self._populate()

    # ------------------------------------------------------------- actions

    def _selected_item(self):
        if self._selected_id is None:
            return None
        return next((i for i in self._items if i.get("id") == self._selected_id), None)

    def _open_selected(self):
        item = self._selected_item()
        if item:
            self._open_player(item)

    def _show_context_menu(self, position):
        pass  # cards handle their own interaction; kept for API compatibility

    def _open_player(self, item: dict):
        dlg = _PlayerDialog(item, self)
        dlg.exec()
        if getattr(dlg, "open_in_editor", False):
            self.openEditorRequested.emit(item.get("full_path", ""))

    def _delete_selected(self):
        item = self._selected_item()
        if item:
            self._delete_item(item.get("id"))

    def _delete_item(self, item_id):
        if item_id is None:
            return
        if self._confirm_delete():
            self.db.remove_item(item_id, self.base_dirs)
            self._load_archive()

    def _confirm_delete(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(tr("arch.delete_confirm_title"))
        box.setText(tr("arch.delete_confirm", name="…"))
        yes = box.addButton(tr("arch.delete"), QMessageBox.YesRole)
        no = box.addButton(tr("btn.cancel"), QMessageBox.NoRole)
        box.exec()
        return box.clickedButton() is yes

    def hideEvent(self, event):
        if self.loader_thread is not None and self.loader_thread.isRunning():
            self.loader_thread.wait(1000)
        event.accept()


# ------------------------------------------------------------------ player

def _reveal_in_folder(path: str):
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif os.uname().sysname == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or path])
    except Exception as e:
        log.error("Reveal failed: %s", e)


def _open_in_system(path: str):
    try:
        if os.name == "nt":
            os.startfile(path)
        elif os.uname().sysname == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        log.error("Open failed: %s", e)


class _VideoCanvas(QWidget):
    """Black canvas drawing the current BGR frame, letterboxed like the tile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img = None  # QImage
        self.setMinimumSize(560, 315)
        self.setStyleSheet("background: #000000; border: 1px solid rgba(255,255,255,0.10); border-radius: 8px;")

    def set_frame_bgr(self, frame) -> bool:
        if frame is None:
            return False
        h, w = frame.shape[:2]
        img = QImage(frame.data, w, h, w * 3, QImage.Format_BGR888)
        self._img = img.copy()
        self.update()
        return True

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._img is not None:
            scaled = self._img.scaled(self.size(), Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawImage(x, y, scaled)
        p.end()


class _PlayerDialog(QDialog):
    """Reference-style viewer: cv2-frame playback (no codec quirks, no black
    screen), metadata grid, actions. Plays H.264 MP4 and MJPG AVI alike.
    """

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.open_in_editor = False
        self.full_path = item.get("full_path", "")
        self.is_rec = item.get("item_type") == "recording"
        self._cap = None
        self._timer = None
        self._pos = 0
        self._fps = 25.0
        self._frame_count = 0
        self._playing = False
        self._converting = False
        name = os.path.basename(self.full_path) or "?"
        self.setWindowTitle(f"{tr('arch.player_title')} — {name}")
        self.resize(880, 660)
        self._build_ui()
        if self.is_rec:
            self._open_video()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        if self.layout() is not None:
            QWidget().setLayout(self.layout())
        root = QVBoxLayout(self)
        root.setSpacing(10)

        if self.is_rec:
            self.canvas = _VideoCanvas(self)
            root.addWidget(self.canvas, 1)

            controls = QHBoxLayout()
            self.play_btn = QPushButton()
            self.play_btn.setFixedWidth(40)
            set_button_icon(self.play_btn, "play", theme.TEXT2, 16)
            self.play_btn.clicked.connect(self._toggle_play)
            self.step_back_btn = QPushButton()
            self.step_back_btn.setFixedWidth(34)
            set_button_icon(self.step_back_btn, "chevron_left", theme.TEXT_MUTED, 15)
            self.step_back_btn.clicked.connect(lambda: self._step(-1))
            self.step_fwd_btn = QPushButton()
            self.step_fwd_btn.setFixedWidth(34)
            set_button_icon(self.step_fwd_btn, "chevron_down", theme.TEXT_MUTED, 15)
            self.step_fwd_btn.clicked.connect(lambda: self._step(1))
            self.speed_combo = QComboBox()
            for s in (0.5, 1.0, 2.0, 4.0):
                self.speed_combo.addItem(f"×{s}", s)
            self.speed_combo.setCurrentIndex(1)
            self.speed_combo.setFixedWidth(86)
            self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
            self.pos_slider = QSlider(Qt.Horizontal)
            self.pos_slider.setRange(0, 0)
            self.pos_slider.sliderMoved.connect(self._seek)
            self.time_label = QLabel("0:00 / 0:00")
            self.time_label.setObjectName("hudMeta")
            self.time_label.setFont(mono_font())
            controls.addWidget(self.play_btn)
            controls.addWidget(self.step_back_btn)
            controls.addWidget(self.pos_slider, 1)
            controls.addWidget(self.step_fwd_btn)
            controls.addWidget(self.speed_combo)
            controls.addWidget(self.time_label)
            root.addLayout(controls)
            self._speed = 1.0
            self.setFocusPolicy(Qt.StrongFocus)
        else:
            media = QLabel()
            media.setAlignment(Qt.AlignCenter)
            media.setMinimumSize(560, 315)
            pm = QPixmap(self.full_path)
            if not pm.isNull():
                media.setPixmap(pm.scaled(820, 460, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
            else:
                media.setText("…")
            root.addWidget(media, 1)

        # ---- metadata grid
        meta_card = QFrame()
        meta_card.setObjectName("glassCard")
        grid = QGridLayout(meta_card)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)

        when = datetime.fromtimestamp(self.item.get("timestamp") or 0).strftime("%d.%m.%Y %H:%M:%S")
        size = fmt_size(self.item.get("size_bytes"))
        dur = fmt_duration(self.item.get("duration_sec")) if self.is_rec else "—"
        res, codec = "—", "—"
        if self.is_rec:
            res, codec = self._probe_video()
        cam_n = self.item.get("camera_index")
        cam = tr("arch.cam1") if cam_n == 0 else tr("arch.cam2") if cam_n == 1 else tr("arch.cam")
        itype = tr("arch.screenshot") if not self.is_rec else tr("arch.recording")

        cells = [
            (tr("arch.meta.date"), when),
            (tr("arch.meta.duration"), dur),
            (tr("arch.meta.size"), size),
            (tr("arch.meta.res"), res),
            (tr("arch.meta.codec"), codec),
            (tr("arch.meta.camera"), cam),
            (tr("arch.meta.type"), itype),
            (tr("arch.meta.file"), os.path.basename(self.full_path)),
        ]
        for i, (label, value) in enumerate(cells):
            r, c = divmod(i, 3)
            cell = QVBoxLayout()
            lab = QLabel(str(label).upper())
            lab.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 9px; border: none; background: transparent;")
            val = QLabel(str(value))
            val.setFont(mono_font())
            val.setStyleSheet(f"color: {TEXT2}; font-size: 11px; border: none; background: transparent;")
            cell.addWidget(lab)
            cell.addWidget(val)
            grid.addLayout(cell, r, c)
        root.addWidget(meta_card)

        # ---- actions
        btns = QHBoxLayout()
        open_sys = QPushButton(tr("arch.open_sys"))
        set_button_icon(open_sys, "external", theme.TEXT2, 15)
        open_sys.clicked.connect(lambda: _open_in_system(self.full_path))
        reveal = QPushButton(tr("arch.show_folder"))
        set_button_icon(reveal, "reveal", theme.TEXT2, 15)
        reveal.clicked.connect(lambda: _reveal_in_folder(self.full_path))
        btns.addWidget(open_sys)
        btns.addWidget(reveal)
        if hasattr(self.parent(), "openEditorRequested"):
            edit_btn = QPushButton(tr("menu.editor"))
            set_button_icon(edit_btn, "scissors", theme.TEXT2, 15)
            edit_btn.clicked.connect(lambda: self._goto_editor())
            btns.addWidget(edit_btn)
        codec_now = probe_codec(self.full_path)
        ext_ok = self.full_path.lower().endswith(".mp4")
        if self.is_rec and CV2_OK and not (ext_ok and codec_now in ("h264", "hevc")):
            self.convert_btn = QPushButton(tr("arch.convert_h264"))
            set_button_icon(self.convert_btn, "convert", "#08110d", 15)
            self.convert_btn.setProperty("buttonRole", "accent")
            self.convert_btn.clicked.connect(self._convert)
            btns.addWidget(self.convert_btn)
        btns.addStretch(1)
        delete = QPushButton(tr("arch.delete"))
        delete.setProperty("buttonRole", "danger")
        set_button_icon(delete, "trash", "#f87171", 15)
        delete.clicked.connect(self._delete)
        close = QPushButton(tr("btn.cancel"))
        close.clicked.connect(self.reject)
        btns.addWidget(delete)
        btns.addWidget(close)
        root.addLayout(btns)

    # ------------------------------------------------------------- playback

    def _step(self, delta: int):
        if self._cap is None:
            return
        self._stop_playback()
        target = int(max(0, min(self._frame_count - 1, self._pos * self._fps + delta)))
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = self._cap.read()
        self._pos = target / max(1.0, self._fps)
        if ok:
            self.canvas.set_frame_bgr(frame)
        self.pos_slider.blockSignals(True)
        self.pos_slider.setValue(target)
        self.pos_slider.blockSignals(False)
        self._update_time()

    def _on_speed_changed(self):
        self._speed = float(self.speed_combo.currentData() or 1.0)
        if self._timer is not None and self._playing:
            self._timer.setInterval(max(8, int(33 / self._speed)))

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space:
            self._toggle_play(); event.accept(); return
        if key == Qt.Key_Left:
            self._step(-1); event.accept(); return
        if key == Qt.Key_Right:
            self._step(1); event.accept(); return
        super().keyPressEvent(event)

    def _probe_video(self):
        if not CV2_OK or not os.path.exists(self.full_path):
            return "—", "—"
        try:
            cap = cv2.VideoCapture(self.full_path)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            return (f"{w}×{h}" if w and h else "—"), (probe_codec(self.full_path) or "—")
        except Exception:
            return "—", "—"

    def _open_video(self):
        """(Re)open the video: first frame on canvas + timer running."""
        self._stop_playback()
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        if not CV2_OK or not os.path.exists(self.full_path):
            return
        self._cap = cv2.VideoCapture(self.full_path)
        ok, frame = self._cap.read()
        if not ok:
            self._cap = None
            return
        self.canvas.set_frame_bgr(frame)
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._fps = float(fps) if fps and 1 < fps < 121 else 25.0
        self._frame_count = max(1, int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        self._pos = 0
        self.pos_slider.blockSignals(True)
        self.pos_slider.setRange(0, self._frame_count - 1)
        self.pos_slider.setValue(0)
        self.pos_slider.blockSignals(False)
        self._update_time()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
        self._timer.setInterval(max(16, int(1000 / self._fps)))
        self._playing = True
        set_button_icon(self.play_btn, "pause", theme.TEXT2, 16)
        self._timer.start()

    def _tick(self):
        if self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok:
            self._stop_playback()
            self._pos = self._frame_count
            self._update_time()
            return
        self._pos += 1
        self.canvas.set_frame_bgr(frame)
        self.pos_slider.blockSignals(True)
        self.pos_slider.setValue(min(self._pos, self._frame_count - 1))
        self.pos_slider.blockSignals(False)
        self._update_time()
        if self._speed > 1.0 and self._pos < self._frame_count - 1:
            skip = int(self._speed) - 1
            for _ in range(skip):
                ok2, frame2 = self._cap.read()
                if not ok2:
                    break
                self._pos += 1

    def _toggle_play(self):
        if self._cap is None:
            return
        if self._playing:
            self._stop_playback()
        else:
            if self._pos >= self._frame_count - 1:
                self._open_video()  # replay from start
                return
            self._playing = True
            set_button_icon(self.play_btn, "pause", theme.TEXT2, 16)
            self._timer.start()

    def _stop_playback(self):
        self._playing = False
        if self._timer is not None:
            self._timer.stop()
        if getattr(self, "play_btn", None) is not None:
            set_button_icon(self.play_btn, "play", theme.TEXT2, 16)

    def _seek(self, value: int):
        if self._cap is None:
            return
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, int(value))
        ok, frame = self._cap.read()
        self._pos = int(value)
        if ok:
            self.canvas.set_frame_bgr(frame)
        self._update_time()

    def _update_time(self):
        cur = fmt_duration(self._pos / self._fps)
        total = fmt_duration(self._frame_count / self._fps)
        self.time_label.setText(f"{cur} / {total}")

    # ----------------------------------------------------------- conversion

    def _convert(self):
        """Re-encode to H.264 in place (smaller file), then reopen."""
        if self._converting or not CV2_OK:
            return
        self._converting = True
        src = self.full_path
        self._stop_playback()
        self.convert_btn.setEnabled(False)
        self.convert_btn.setText(tr("arch.converting"))
        result = {"ok": False}

        def work():
            result["ok"] = transcode_to_h264(src, log_ctx="player convert")

        def after():
            self._converting = False
            self._build_ui()
            if result["ok"]:
                self._open_video()
                db = self.parent().db if hasattr(self.parent(), "db") else None
                base_dirs = self.parent().base_dirs if hasattr(self.parent(), "base_dirs") else {}
                if db is not None:
                    try:
                        db.backfill_metadata(base_dirs)
                    except Exception as e:
                        log.error("post-convert backfill failed: %s", e)
                QMessageBox.information(self, tr("arch.player_title"), tr("arch.convert_done"))
            else:
                QMessageBox.warning(self, tr("arch.player_title"), tr("arch.convert_fail"))

        self._conv_thread = QThread()
        # inline worker: conversion is a single subprocess call, run in QThread via helper
        from concurrent.futures import ThreadPoolExecutor

        def run_and_emit():
            work()
            QTimer.singleShot(0, after)

        self._conv_pool = ThreadPoolExecutor(max_workers=1)
        self._conv_pool.submit(run_and_emit)

    def _goto_editor(self):
        self.open_in_editor = True
        self.reject()

    def _delete(self):
        parent = self.parent()
        self.reject()
        if hasattr(parent, "_delete_item"):
            parent._delete_item(self.item.get("id"))

    def closeEvent(self, event):
        self._stop_playback()
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        event.accept()


class ArchiveDialog(QDialog):
    """Modal wrapper kept for compatibility; the app embeds ArchiveGallery."""

    def __init__(self, db, base_dirs: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("arch.dlg_title"))
        self.resize(1100, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.gallery = ArchiveGallery(db, base_dirs, self)
        lay.addWidget(self.gallery)
