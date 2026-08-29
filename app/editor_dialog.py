# -*- coding: utf-8 -*-
"""Video editor (reference: Sentinel NVR EditorView): trim timeline, speed,
resolution, quality, format, B&W / contrast filters, export with progress.
"""

import os
import subprocess

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from .archive_dialog import _VideoCanvas, fmt_duration, fmt_size, mono_font
from .i18n import tr
from .icons import set_button_icon
from . import theme
from .logutil import get_logger
from .media_convert import _find_ffmpeg
from .theme import ACCENT, TEXT2, TEXT_SOFT

try:
    import cv2
    CV2_OK = True
except Exception:
    cv2 = None
    CV2_OK = False

log = get_logger("editor")

QUALITY = [("ed.q_low", 30), ("ed.q_medium", 26), ("ed.q_high", 23), ("ed.q_max", 20)]
SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0]
RESOLUTIONS = [("ed.res_orig", None), ("ed.res_1080", 1080), ("ed.res_720", 720), ("ed.res_480", 480)]


class ExportWorker(QThread):
    progress = Signal(int)
    done = Signal(bool, str)  # ok, output path / error

    def __init__(self, cmd, total_sec: float, out_path: str, parent=None):
        super().__init__(parent)
        self._cmd = cmd
        self._total = max(0.001, total_sec)
        self._out = out_path

    def run(self):
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            self.done.emit(False, "ffmpeg unavailable")
            return
        try:
            proc = subprocess.Popen(
                [ffmpeg, "-hide_banner", "-loglevel", "error",
                 "-progress", "pipe:1", "-nostats"] + self._cmd[1:],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    try:
                        us = float(line.split("=", 1)[1])
                        pct = min(99, int(us / 1_000_000 / self._total * 100))
                        self.progress.emit(pct)
                    except ValueError:
                        pass
            rc = proc.wait()
            if rc == 0 and os.path.exists(self._out) and os.path.getsize(self._out) > 1024:
                self.progress.emit(100)
                self.done.emit(True, self._out)
            else:
                err = proc.stderr.read()[-300:] if proc.stderr else ""
                log.error("export failed rc=%s %s", rc, err)
                try:
                    if os.path.exists(self._out):
                        os.remove(self._out)
                except OSError:
                    pass
                self.done.emit(False, err or f"rc={rc}")
        except Exception as e:
            log.exception("export error")
            self.done.emit(False, str(e))


class EditorWidget(QWidget):
    exported = Signal()

    def __init__(self, db, base_dirs: dict, parent=None):
        super().__init__(parent)
        self.db = db
        self.base_dirs = base_dirs
        self._items = []
        self._cap = None
        self._pos = 0.0        # seconds
        self._fps = 25.0
        self._frame_count = 0
        self._duration = 0.0
        self._trim = [0.0, 0.0]
        self._playing = False
        self._exporting = False
        self._worker = None

        self._build_ui()
        self._reload_files()

    def refresh(self):
        """Reload recordings when the view becomes visible."""
        self._reload_files()

    def load_file(self, path: str):
        """Select a specific recording in the combo."""
        self._reload_files()
        for i in range(self.file_combo.count()):
            if os.path.normpath(self.file_combo.itemData(i) or "") == os.path.normpath(path or ""):
                self.file_combo.setCurrentIndex(i)
                break

    # ------------------------------------------------------------------- UI

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setSpacing(12)

        # ---- left: preview
        left = QVBoxLayout()
        self.canvas = _VideoCanvas(self)
        self.canvas.setMinimumSize(620, 360)
        left.addWidget(self.canvas, 1)

        play_row = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(44)
        self.play_btn.clicked.connect(self._toggle_play)
        self.pos_slider = QSlider(Qt.Horizontal)
        self.pos_slider.setRange(0, 0)
        self.pos_slider.sliderMoved.connect(self._on_playhead)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("hudMeta")
        self.time_label.setFont(mono_font())
        play_row.addWidget(self.play_btn)
        play_row.addWidget(self.pos_slider, 1)
        play_row.addWidget(self.time_label)
        left.addLayout(play_row)
        root.addLayout(left, 3)

        # ---- right: controls
        right = QVBoxLayout()
        right.setSpacing(8)

        file_row = QHBoxLayout()
        self.file_combo = QComboBox()
        self.file_combo.currentIndexChanged.connect(self._on_file_changed)
        file_row.addWidget(self.file_combo, 1)
        right.addLayout(file_row)

        # trim
        trim_card = QFrame(); trim_card.setObjectName("glassCard")
        trim_lay = QGridLayout(trim_card)
        trim_lay.setContentsMargins(12, 10, 12, 10)
        self.trim_start = QSlider(Qt.Horizontal); self.trim_start.setRange(0, 1000)
        self.trim_end = QSlider(Qt.Horizontal); self.trim_end.setRange(0, 1000)
        self.trim_end.setValue(1000)
        self.trim_start.sliderReleased.connect(self._on_trim_changed)
        self.trim_end.sliderReleased.connect(self._on_trim_changed)
        self.set_start_btn = QPushButton(tr("ed.set_start"))
        self.set_end_btn = QPushButton(tr("ed.set_end"))
        self.set_start_btn.clicked.connect(lambda: self._mark(True))
        self.set_end_btn.clicked.connect(lambda: self._mark(False))
        self.trim_label = QLabel(tr("ed.selected", a="0.0", b="0.0"))
        self.trim_label.setObjectName("hudMeta")
        self.trim_label.setFont(mono_font())
        trim_lay.addWidget(QLabel(tr("ed.trim_start")), 0, 0)
        trim_lay.addWidget(self.trim_start, 0, 1)
        trim_lay.addWidget(self.set_start_btn, 0, 2)
        trim_lay.addWidget(QLabel(tr("ed.trim_end")), 1, 0)
        trim_lay.addWidget(self.trim_end, 1, 1)
        trim_lay.addWidget(self.set_end_btn, 1, 2)
        trim_lay.addWidget(self.trim_label, 2, 0, 1, 3)
        right.addWidget(trim_card)

        # params card
        par_card = QFrame(); par_card.setObjectName("glassCard")
        par = QGridLayout(par_card)
        par.setContentsMargins(12, 10, 12, 10)
        par.setVerticalSpacing(6)

        par.addWidget(QLabel(tr("ed.speed")), 0, 0)
        self.speed_combo = QComboBox()
        for s in SPEEDS:
            self.speed_combo.addItem(f"×{s}", s)
        self.speed_combo.setCurrentIndex(2)
        par.addWidget(self.speed_combo, 0, 1)

        par.addWidget(QLabel(tr("ed.resolution")), 1, 0)
        self.res_combo = QComboBox()
        for key, _h in RESOLUTIONS:
            self.res_combo.addItem(tr(key), _h)
        par.addWidget(self.res_combo, 1, 1)

        par.addWidget(QLabel(tr("ed.quality")), 2, 0)
        self.quality_combo = QComboBox()
        for key, crf in QUALITY:
            self.quality_combo.addItem(tr(key), crf)
        self.quality_combo.setCurrentIndex(2)
        par.addWidget(self.quality_combo, 2, 1)

        par.addWidget(QLabel(tr("ed.format")), 3, 0)
        self.format_combo = QComboBox()
        for ext in ("mp4", "avi", "mkv"):
            self.format_combo.addItem(ext.upper(), ext)
        par.addWidget(self.format_combo, 3, 1)

        self.bw_check = QCheckBox(tr("ed.filter_bw"))
        self.contrast_check = QCheckBox(tr("ed.filter_contrast"))
        par.addWidget(self.bw_check, 4, 0, 1, 2)
        par.addWidget(self.contrast_check, 5, 0, 1, 2)
        right.addWidget(par_card)

        # export
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        right.addWidget(self.progress)

        self.export_btn = QPushButton(tr("ed.export"))
        self.export_btn.setProperty("buttonRole", "accent")
        set_button_icon(self.export_btn, "download", "#08110d", 16)
        self.export_btn.clicked.connect(self._export)
        right.addWidget(self.export_btn)

        self.status_label = QLabel("")
        self.status_label.setObjectName("hudMeta")
        self.status_label.setWordWrap(True)
        right.addWidget(self.status_label)
        right.addStretch(1)

        holder = QWidget()
        holder.setLayout(right)
        holder.setFixedWidth(360)
        root.addWidget(holder)

    # ------------------------------------------------------------- data

    def _reload_files(self):
        items = self.db.search_items(self.base_dirs, item_types=["recording"])
        self._items = items
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        for it in items:
            self.file_combo.addItem(
                f"{os.path.basename(it['full_path'])} · {fmt_size(it.get('size_bytes'))}",
                it.get("full_path"))
        self.file_combo.blockSignals(False)
        if items:
            self.file_combo.setCurrentIndex(0)
            self._on_file_changed()
        else:
            self.status_label.setText(tr("ed.no_file"))

    def _current_path(self) -> str:
        return self.file_combo.currentData() or ""

    def _on_file_changed(self):
        self._close_cap()
        path = self._current_path()
        if not path or not os.path.exists(path) or not CV2_OK:
            return
        self._cap = cv2.VideoCapture(path)
        ok, frame = self._cap.read()
        if not ok:
            self._cap = None
            return
        self.canvas.set_frame_bgr(frame)
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._fps = float(fps) if fps and 1 < fps < 121 else 25.0
        n = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self._frame_count = max(1, int(n))
        self._duration = self._frame_count / self._fps
        self._trim = [0.0, self._duration]
        self.pos_slider.blockSignals(True)
        self.pos_slider.setRange(0, self._frame_count - 1)
        self.pos_slider.setValue(0)
        self.pos_slider.blockSignals(False)
        self._pos = 0.0
        self._update_time()
        self._update_trim_label()

    def _close_cap(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._stop_playback()

    # ---------------------------------------------------------- playback

    def _toggle_play(self):
        if self._cap is None:
            return
        if self._playing:
            self._stop_playback()
        else:
            if self._pos >= self._duration - 0.05:
                self._seek_to(0.0)
            self._playing = True
            self.play_btn.setText("⏸")
            if self._timer is None:
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._tick)
            self._timer.setInterval(33)
            self._timer.start()

    def _stop_playback(self):
        self._playing = False
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()
        self.play_btn.setText("▶")

    def _tick(self):
        if self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok or self._pos >= self._duration - 0.02:
            self._stop_playback()
            return
        self._pos += 1.0 / self._fps
        self.canvas.set_frame_bgr(frame)
        self.pos_slider.blockSignals(True)
        self.pos_slider.setValue(int(self._pos * self._fps))
        self.pos_slider.blockSignals(False)
        self._update_time()

    def _on_playhead(self, frame_idx: int):
        self._seek_to(frame_idx / max(1.0, self._fps))

    def _seek_to(self, sec: float):
        if self._cap is None:
            return
        self._pos = max(0.0, min(self._duration, sec))
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, int(self._pos * self._fps))
        ok, frame = self._cap.read()
        if ok:
            self.canvas.set_frame_bgr(frame)
        self._update_time()

    def _update_time(self):
        self.time_label.setText(f"{fmt_duration(self._pos)} / {fmt_duration(self._duration)}")

    # ------------------------------------------------------------- trim

    def _mark(self, is_start: bool):
        if is_start:
            self._trim[0] = min(self._pos, self._trim[1] - 0.1)
        else:
            self._trim[1] = max(self._pos, self._trim[0] + 0.1)
        self._sync_trim_sliders()
        self._update_trim_label()

    def _on_trim_changed(self):
        a = self.trim_start.value() / 1000.0 * self._duration
        b = self.trim_end.value() / 1000.0 * self._duration
        if b - a < 0.1:
            b = min(self._duration, a + 0.1)
        self._trim = [a, b]
        self._update_trim_label()

    def _sync_trim_sliders(self):
        self.trim_start.blockSignals(True)
        self.trim_end.blockSignals(True)
        if self._duration > 0:
            self.trim_start.setValue(int(self._trim[0] / self._duration * 1000))
            self.trim_end.setValue(int(self._trim[1] / self._duration * 1000))
        self.trim_start.blockSignals(False)
        self.trim_end.blockSignals(False)

    def _update_trim_label(self):
        self.trim_label.setText(tr("ed.selected",
                                   a=f"{self._trim[1] - self._trim[0]:.1f}",
                                   b=f"{(self._trim[1] - self._trim[0]) / self._speed():.1f}"))

    def _speed(self) -> float:
        return float(self.speed_combo.currentData() or 1.0)

    # ------------------------------------------------------------- export

    def _export(self):
        if self._exporting or not self._items:
            return
        src = self._current_path()
        if not src or not os.path.exists(src) or not _find_ffmpeg():
            self.status_label.setText(tr("ed.fail"))
            return
        self._exporting = True
        self._stop_playback()
        self.export_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)

        start, end = self._trim
        speed = self._speed()
        crf = int(self.quality_combo.currentData() or 23)
        target_h = self.res_combo.currentData()
        ext = self.format_combo.currentData() or "mp4"

        stem = os.path.splitext(os.path.basename(src))[0]
        rec_dir = self.base_dirs.get("recording", "")
        out = os.path.join(rec_dir, f"edit_{stem}.{ext}")
        i = 1
        while os.path.exists(out):
            out = os.path.join(rec_dir, f"edit_{stem}_{i}.{ext}")
            i += 1

        vf = []
        if target_h:
            vf.append(f"scale=-2:{target_h}")
        if self.bw_check.isChecked():
            vf.append("hue=s=0")
        if self.contrast_check.isChecked():
            vf.append("eq=contrast=1.18:saturation=1.08")
        if speed != 1.0:
            vf.append(f"setpts=PTS/{speed}")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        content_sec = max(0.1, (end - start) / speed)
        if ext == "avi":
            cmd += ["-c:v", "mjpeg", "-q:v", "4"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
            if ext == "mp4":
                cmd += ["-movflags", "+faststart"]
        cmd += ["-an", out]

        content_sec_out = content_sec
        self._worker = ExportWorker(cmd, content_sec_out, out, self)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.done.connect(self._on_export_done)
        self.status_label.setText(tr("ed.exporting"))
        self._worker.start()

    def _on_export_done(self, ok: bool, info: str):
        self._exporting = False
        self.export_btn.setEnabled(True)
        self.progress.setVisible(False)
        if ok:
            self.status_label.setText(tr("ed.done"))
            self.exported.emit()
        else:
            self.status_label.setText(tr("ed.fail") + f"\n{info[:200]}")

    def hideEvent(self, event):
        self._close_cap()
        event.accept()


class EditorDialog(QDialog):
    """Modal wrapper kept for compatibility; the app embeds EditorWidget."""

    def __init__(self, db, base_dirs: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ed.title"))
        self.resize(1120, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.editor = EditorWidget(db, base_dirs, self)
        lay.addWidget(self.editor)
