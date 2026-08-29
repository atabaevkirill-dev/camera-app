# -*- coding: utf-8 -*-
"""PTZ control pad: pan/tilt D-pad, zoom, focus, home, presets (hold-to-move)."""

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

from .i18n import tr
from .logutil import get_logger

log = get_logger("ptz_pad")


class PTZPad(QWidget):
    """Sends ONVIF PTZ/Imaging commands via provided callables in background pool."""

    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.get_client = None       # callable -> OnvifClient | None
        self.get_profile = None      # callable -> profile token str | ""
        self.get_vstoken = None      # callable -> video source token str | ""
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ptz")
        self._stop_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ptz-stop")
        self._af_mode = None         # None = unknown
        self._expanded = False
        self._build()
        self.retranslate()
        self._apply_curtain(animate=False)  # collapsed by default

    # ------------------------------------------------------------------ UI

    def _build(self):
        root_outer = QVBoxLayout(self)
        root_outer.setContentsMargins(0, 0, 0, 0)
        root_outer.setSpacing(2)

        # ---- curtain header
        header = QHBoxLayout()
        self._title = QLabel()
        self._title.setStyleSheet("font-weight: 600;")
        self._chevron = QPushButton("▸")
        self._chevron.setObjectName("ptzHome")
        self._chevron.setProperty("ptzHome", "true")
        self._chevron.setFixedSize(26, 22)
        self._chevron.setCursor(Qt.PointingHandCursor)
        self._chevron.clicked.connect(self.toggle_curtain)
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._chevron)
        root_outer.addLayout(header)

        # ---- collapsible body
        self._body = QWidget()
        self._body.setMaximumHeight(0)
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        self.group = QGroupBox()
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(4, 4, 4, 4)

        # speed
        speed_row = QHBoxLayout()
        self.speed_label = QLabel()
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(5, 100)
        self.speed.setValue(50)
        self.speed.setPageStep(10)
        speed_row.addWidget(self.speed_label)
        speed_row.addWidget(self.speed, 1)
        root.addLayout(speed_row)

        # main row: d-pad + zoom/focus column
        main = QHBoxLayout()

        pad = QGridLayout()
        pad.setSpacing(4)
        dirs = [
            ("nw", 0, 0, chr(0x2196)), ("up", 0, 1, chr(0x2191)), ("ne", 0, 2, chr(0x2197)),
            ("left", 1, 0, chr(0x2190)), ("home", 1, 1, None), ("right", 1, 2, chr(0x2192)),
            ("sw", 2, 0, chr(0x2199)), ("down", 2, 1, chr(0x2193)), ("se", 2, 2, chr(0x2198)),
        ]
        self._move_buttons = {}
        self._all_buttons = []
        for key, row, col, ch in dirs:
            if key == "home":
                btn = QPushButton()
                btn.setProperty("ptzHome", "true")
                btn.setFixedSize(40, 34)  # Установка фиксированного размера
                btn.clicked.connect(self._go_home)
                pad.addWidget(btn, row, col)
                self.home_btn = btn
                self._all_buttons.append(btn)
                continue
            btn = QPushButton(ch)
            btn.setProperty("ptz", "true")
            btn.setFixedSize(40, 34)
            btn.pressed.connect(lambda k=key: self._move_start(k))
            btn.released.connect(self._move_stop)
            pad.addWidget(btn, row, col)
            self._move_buttons[key] = btn
            self._all_buttons.append(btn)
        main.addLayout(pad, 1)

        # zoom + focus column
        zf = QVBoxLayout()
        self.zoom_title = QLabel()
        zrow = QHBoxLayout()
        self.zoom_out_btn = QPushButton()
        self.zoom_out_btn.setMinimumWidth(64)
        self.zoom_in_btn = QPushButton()
        self.zoom_in_btn.setMinimumWidth(64)
        # (roles applied below in retranslate-independent setup)
        self.zoom_out_btn.pressed.connect(lambda: self._zoom_start(-1))
        self.zoom_out_btn.released.connect(self._zoom_stop)
        self.zoom_in_btn.pressed.connect(lambda: self._zoom_start(1))
        self.zoom_in_btn.released.connect(self._zoom_stop)
        self.zoom_out_btn.setProperty("ptz", "true")
        self.zoom_in_btn.setProperty("ptz", "true")
        self._all_buttons += [self.zoom_out_btn, self.zoom_in_btn]
        zrow.addWidget(self.zoom_out_btn)
        zrow.addWidget(self.zoom_in_btn)
        zf.addWidget(self.zoom_title)
        zf.addLayout(zrow)

        self.focus_title = QLabel()
        frow = QHBoxLayout()
        self.focus_near_btn = QPushButton()
        self.focus_far_btn = QPushButton()
        self.focus_near_btn.setMinimumWidth(64)
        self.focus_far_btn.setMinimumWidth(64)
        self.focus_near_btn.pressed.connect(lambda: self._focus_start(-1))
        self.focus_near_btn.released.connect(self._focus_stop)
        self.focus_far_btn.pressed.connect(lambda: self._focus_start(1))
        self.focus_far_btn.released.connect(self._focus_stop)
        self.focus_near_btn.setProperty("ptz", "true")
        self.focus_far_btn.setProperty("ptz", "true")
        self._all_buttons += [self.focus_near_btn, self.focus_far_btn]
        frow.addWidget(self.focus_near_btn)
        frow.addWidget(self.focus_far_btn)
        zf.addWidget(self.focus_title)
        zf.addLayout(frow)

        self.af_btn = QPushButton()
        self.af_btn.clicked.connect(self._toggle_af)
        zf.addWidget(self.af_btn)
        self.af_btn.setProperty("ptz", "true")
        self._all_buttons.append(self.af_btn)
        main.addLayout(zf, 1)
        root.addLayout(main)

        # home + presets
        bottom = QHBoxLayout()
        self.home_set_btn = QPushButton()
        self.home_set_btn.clicked.connect(self._set_home)
        self.preset_label = QLabel()
        self.preset_spin = QSpinBox()
        self.preset_spin.setRange(1, 10)
        self.preset_save_btn = QPushButton()
        self.preset_go_btn = QPushButton()
        self.preset_save_btn.clicked.connect(self._preset_save)
        self.preset_go_btn.clicked.connect(self._preset_go)
        self.home_set_btn.setProperty("ptz", "true")
        self.preset_save_btn.setProperty("ptz", "true")
        self.preset_go_btn.setProperty("ptz", "true")
        self._all_buttons += [self.home_set_btn, self.preset_save_btn, self.preset_go_btn]
        bottom.addWidget(self.home_set_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.preset_label)
        bottom.addWidget(self.preset_spin)
        bottom.addWidget(self.preset_save_btn)
        bottom.addWidget(self.preset_go_btn)
        root.addLayout(bottom)

        group_lay = QVBoxLayout(self.group)
        group_lay.setContentsMargins(2, 8, 2, 2)
        group_lay.addWidget(inner)
        body_lay.addWidget(self.group)
        root_outer.addWidget(self._body)
        self._inner = inner
        self._anim = QPropertyAnimation(self._body, b"maximumHeight", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def retranslate(self):
        self._title.setText(tr("ptz.group"))
        self.group.setTitle(tr("ptz.group"))
        self.speed_label.setText(tr("ptz.speed"))
        self.zoom_title.setText(tr("ptz.zoom"))
        self.focus_title.setText(tr("ptz.focus"))
        self.zoom_in_btn.setText("+")
        self.zoom_out_btn.setText(chr(0x2212))
        self.focus_near_btn.setText(tr("ptz.near"))
        self.focus_far_btn.setText(tr("ptz.far"))
        self._update_af_text()
        self.home_btn.setText(tr("ptz.home_go"))
        self.home_set_btn.setText(tr("ptz.home_set"))
        self.preset_label.setText(tr("ptz.preset"))
        self.preset_save_btn.setText(tr("ptz.preset_set"))
        self.preset_go_btn.setText(tr("ptz.preset_go"))

    def toggle_curtain(self):
        self._expanded = not self._expanded
        self._apply_curtain(animate=True)

    def _apply_curtain(self, animate: bool = True):
        target = self._body.sizeHint().height() if self._expanded else 0
        self._chevron.setText("▾" if self._expanded else "▸")
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._body.maximumHeight())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._body.setMaximumHeight(target)

    def set_backend(self, get_client, get_profile, get_vstoken):
        self.get_client = get_client
        self.get_profile = get_profile
        self.get_vstoken = get_vstoken

    def set_enabled_state(self, ptz_supported: bool):
        self.setEnabled(True)
        self._ptz_ok = ptz_supported
        for b in self._all_buttons:
            b.setEnabled(ptz_supported)
        if not ptz_supported:
            self.setToolTip(tr("ptz.unavailable"))
        else:
            self.setToolTip("")

    # ------------------------------------------------------------ execution

    def _run(self, fn):
        def safe():
            try:
                fn()
            except Exception as e:
                self.errorOccurred.emit(str(e))
        try:
            self._pool.submit(safe)
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def _run_stop(self, fn):
        """Stops must never queue behind a hung move (C11)."""
        def safe():
            try:
                fn()
            except Exception as e:
                self.errorOccurred.emit(str(e))
        try:
            self._stop_pool.submit(safe)
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def _context(self):
        if self.get_client is None:
            return None
        client = self.get_client()
        if client is None:
            self.errorOccurred.emit(tr("ptz.need_conn"))
            return None
        profile = (self.get_profile() or "") if self.get_profile else ""
        if not profile:
            self.errorOccurred.emit(tr("ptz.need_conn"))
            return None
        return client, profile

    # ----------------------------------------------------------------- move

    _VEC = {
        "up": (0.0, 1.0), "down": (0.0, -1.0),
        "left": (-1.0, 0.0), "right": (1.0, 0.0),
        "nw": (-0.7071, 0.7071), "ne": (0.7071, 0.7071),
        "sw": (-0.7071, -0.7071), "se": (0.7071, -0.7071),
    }

    def _move_start(self, key):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        vx, vy = self._VEC[key]
        s = self.speed.value() / 100.0
        self._run(lambda: client.ptz_continuous_move(profile, vx * s, vy * s, 0.0))
        self._safe_stop_later()

    def _move_stop(self):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        self._run_stop(lambda: client.ptz_stop(profile))

    def _safe_stop_later(self):
        # safety: auto stop after 15 s in case release event is lost
        QTimer.singleShot(15000, self._auto_stop_check)

    def _auto_stop_check(self):
        if any(b.isDown() for b in self._move_buttons.values()):
            return
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        self._run(lambda: client.ptz_stop(profile))

    # ----------------------------------------------------------------- zoom

    def _zoom_start(self, direction):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        s = 0.5 * self.speed.value() / 100.0
        self._run(lambda: client.ptz_continuous_move(profile, 0.0, 0.0, direction * s))

    def _zoom_stop(self):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        self._run_stop(lambda: client.ptz_stop(profile))

    # ---------------------------------------------------------------- focus

    def _focus_start(self, direction):
        ctx = self._context()
        if ctx is None:
            return
        client = ctx[0]
        vst = (self.get_vstoken() or "") if self.get_vstoken else ""
        if not vst:
            self.errorOccurred.emit(tr("ptz.need_conn"))
            return
        s = max(0.1, 1.0 * self.speed.value() / 100.0) * direction
        self._run(lambda: client.imaging_move_focus(vst, s))

    def _focus_stop(self):
        ctx = self._context()
        if ctx is None:
            return
        client = ctx[0]
        vst = (self.get_vstoken() or "") if self.get_vstoken else ""
        if not vst:
            return
        self._run_stop(lambda: client.imaging_stop_focus(vst))

    def _toggle_af(self):
        ctx = self._context()
        if ctx is None:
            return
        client = ctx[0]
        vst = (self.get_vstoken() or "") if self.get_vstoken else ""
        if not vst:
            self.errorOccurred.emit(tr("ptz.need_conn"))
            return
        new_mode = not self._af_mode if self._af_mode is not None else False
        self._af_mode = new_mode
        self._update_af_text()
        self._run(lambda: client.imaging_set_focus_mode(vst, new_mode))

    def _update_af_text(self):
        if self._af_mode is True:
            self.af_btn.setText(tr("ptz.af"))
            self.af_btn.setProperty("ptzHome", "true")
        elif self._af_mode is False:
            self.af_btn.setText(tr("ptz.mf"))
            self.af_btn.setProperty("ptzHome", None)
        else:
            self.af_btn.setText(tr("ptz.mf") + " / " + tr("ptz.af"))
            self.af_btn.setProperty("ptzHome", None)
        self.af_btn.style().unpolish(self.af_btn)
        self.af_btn.style().polish(self.af_btn)

    # ----------------------------------------------------------------- home

    def _go_home(self):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        self._run(lambda: client.ptz_goto_home(profile))

    def _set_home(self):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        self._run(lambda: client.ptz_set_home(profile))

    # -------------------------------------------------------------- presets

    def _preset_save(self):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        token = str(self.preset_spin.value())
        self._run(lambda: client.ptz_set_preset(profile, token, f"App{token}"))

    def _preset_go(self):
        ctx = self._context()
        if ctx is None:
            return
        client, profile = ctx
        token = str(self.preset_spin.value())
        self._run(lambda: client.ptz_goto_preset(profile, token))

    def shutdown(self):
        for pool in (self._pool, self._stop_pool):
            try:
                pool.shutdown(wait=False)
            except Exception:
                pass
