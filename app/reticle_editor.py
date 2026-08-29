# -*- coding: utf-8 -*-
"""Reticle editor widget: style, geometry, color, presets (5 slots)."""

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from .reticle import (STYLE_CROSS, STYLE_DUPLEX, STYLE_KEYS, STYLE_MIL_DOT,
                      ReticleStyle, draw_reticle)
from .i18n import tr

STYLE_I18N = {STYLE_CROSS: "ret.cross", STYLE_DUPLEX: "ret.duplex",
              STYLE_MIL_DOT: "ret.mil_dot"}


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color if QColor(color).isValid() else "#00ff00"
        self.setFixedSize(56, 24)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self):
        self.setStyleSheet(
            f"QPushButton {{ background: {self._color}; border: 1px solid #666; border-radius: 4px; }}")

    def set_color(self, color: str):
        if QColor(color).isValid():
            self._color = color
            self._refresh()

    def _pick(self):
        col = QColorDialog.getColor(QColor(self._color), self, tr("ret.color"))
        if col.isValid():
            self._color = col.name()
            self._refresh()
            self.colorChanged.emit(self._color)


class ReticleEditor(QWidget):
    """Edits a shared ReticleStyle instance in place; emits changed()."""

    changed = Signal()

    def __init__(self, style: ReticleStyle, presets: dict, parent=None):
        super().__init__(parent)
        self.rs = style
        self.presets = presets if isinstance(presets, dict) else {}
        self._build()
        self._load_from_style()
        self._update_group_visibility()
        self.retranslate()

    # ------------------------------------------------------------------ UI

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.style_label = QLabel()
        self.style_combo = QComboBox()
        for key in STYLE_KEYS:
            self.style_combo.addItem(tr(STYLE_I18N[key]), key)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        top.addWidget(self.style_label)
        top.addWidget(self.style_combo, 1)
        self.color_label = QLabel()
        self.color_btn = ColorButton(self.rs.color)
        self.color_btn.colorChanged.connect(self._set_color)
        top.addWidget(self.color_label)
        top.addWidget(self.color_btn)
        root.addLayout(top)

        # preview
        self.preview = QLabel()
        self.preview.setMinimumHeight(120)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: #101216; border: 1px solid #33373e;")
        root.addWidget(self.preview)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self._sliders = {}
        self._spins = {}
        rows = [
            ("thickness", "ret.thickness", 1, 12),
            ("length", "ret.length", 10, 600),
            ("gap", "ret.gap", 0, 200),
            ("opacity", "ret.opacity", 10, 100),
        ]
        for i, (key, trkey, lo, hi) in enumerate(rows):
            label = QLabel()
            slider = QSlider(Qt.Horizontal)
            slider.setRange(lo, hi)
            spin = QSpinBox()
            spin.setRange(lo, hi)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            spin.valueChanged.connect(self._on_param)
            grid.addWidget(label, i, 0)
            grid.addWidget(slider, i, 1)
            grid.addWidget(spin, i, 2)
            self._sliders[key] = (label, trkey)
            self._spins[key] = (slider, spin)

        r = len(rows)
        self.outline_check = QCheckBox()
        self.outline_check.toggled.connect(self._on_flag)
        grid.addWidget(self.outline_check, r, 0, 1, 3)
        self.center_check = QCheckBox()
        self.center_check.toggled.connect(self._on_flag)
        grid.addWidget(self.center_check, r + 1, 0, 1, 3)
        root.addLayout(grid)

        # duplex group
        self.duplex_group = QGroupBox()
        dg = QGridLayout(self.duplex_group)
        self.thick_len_label = QLabel()
        self.thick_len_spin = QSpinBox()
        self.thick_len_spin.setRange(4, 400)
        self.thick_len_spin.valueChanged.connect(self._on_param)
        dg.addWidget(self.thick_len_label, 0, 0)
        dg.addWidget(self.thick_len_spin, 0, 1)
        self.thick_mult_label = QLabel()
        self.thick_mult_spin = QSpinBox()
        self.thick_mult_spin.setRange(2, 8)
        self.thick_mult_spin.valueChanged.connect(self._on_param)
        dg.addWidget(self.thick_mult_label, 1, 0)
        dg.addWidget(self.thick_mult_spin, 1, 1)
        root.addWidget(self.duplex_group)

        # mil-dot group
        self.mil_group = QGroupBox()
        mg = QGridLayout(self.mil_group)
        self.dots_label = QLabel()
        self.dots_spin = QSpinBox()
        self.dots_spin.setRange(0, 10)
        self.dots_spin.valueChanged.connect(self._on_param)
        mg.addWidget(self.dots_label, 0, 0)
        mg.addWidget(self.dots_spin, 0, 1)
        self.spacing_label = QLabel()
        self.spacing_spin = QSpinBox()
        self.spacing_spin.setRange(3, 120)
        self.spacing_spin.valueChanged.connect(self._on_param)
        mg.addWidget(self.spacing_label, 1, 0)
        mg.addWidget(self.spacing_spin, 1, 1)
        self.radius_label = QLabel()
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(1, 8)
        self.radius_spin.valueChanged.connect(self._on_param)
        mg.addWidget(self.radius_label, 2, 0)
        mg.addWidget(self.radius_spin, 2, 1)
        root.addWidget(self.mil_group)

        # presets
        pres = QHBoxLayout()
        self.presets_label = QLabel()
        self.preset_combo = QComboBox()
        for i in range(1, 6):
            self.preset_combo.addItem(f"P{i}", i)
        self.preset_save_btn = QPushButton()
        self.preset_load_btn = QPushButton()
        self.preset_save_btn.clicked.connect(self._preset_save)
        self.preset_load_btn.clicked.connect(self._preset_load)
        pres.addWidget(self.presets_label)
        pres.addWidget(self.preset_combo)
        pres.addWidget(self.preset_save_btn)
        pres.addWidget(self.preset_load_btn)
        pres.addStretch(1)
        root.addLayout(pres)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #8a9099; font-size: 11px;")
        root.addWidget(self.hint_label)

    # --------------------------------------------------------------- helpers

    def _retranslate_labels(self):
        self.style_label.setText(tr("ret.style"))
        self.color_label.setText(tr("ret.color"))
        for key, (label, trkey) in self._sliders.items():
            label.setText(tr(trkey))
        self.outline_check.setText(tr("ret.outline"))
        self.center_check.setText(tr("ret.center_dot"))
        self.duplex_group.setTitle(tr("ret.duplex_g"))
        self.mil_group.setTitle(tr("ret.mil_g"))
        self.thick_len_label.setText(tr("ret.thick_len"))
        self.thick_mult_label.setText(tr("ret.thick_mult"))
        self.dots_label.setText(tr("ret.dots"))
        self.spacing_label.setText(tr("ret.dot_spacing"))
        self.radius_label.setText(tr("ret.dot_radius"))
        self.presets_label.setText(tr("ret.presets"))
        self.preset_save_btn.setText(tr("ret.preset_save"))
        self.preset_load_btn.setText(tr("ret.preset_load"))
        self.hint_label.setText(tr("ret.hint"))
        for i, key in enumerate(STYLE_KEYS):
            self.style_combo.setItemText(i, tr(STYLE_I18N[key]))

    def retranslate(self):
        self._retranslate_labels()

    def _load_from_style(self):
        rs = self.rs
        idx = list(STYLE_KEYS).index(rs.style) if rs.style in STYLE_KEYS else 0
        self.style_combo.blockSignals(True)
        self.style_combo.setCurrentIndex(idx)
        self.style_combo.blockSignals(False)
        for key in ("thickness", "length", "gap", "opacity"):
            slider, spin = self._spins[key]
            val = int(getattr(rs, key))
            slider.blockSignals(True)
            spin.blockSignals(True)
            slider.setValue(val)
            spin.setValue(val)
            slider.blockSignals(False)
            spin.blockSignals(False)
        self.outline_check.blockSignals(True)
        self.outline_check.setChecked(rs.outline)
        self.outline_check.blockSignals(False)
        self.center_check.blockSignals(True)
        self.center_check.setChecked(rs.center_dot)
        self.center_check.blockSignals(False)
        self.thick_len_spin.blockSignals(True)
        self.thick_len_spin.setValue(rs.thick_len)
        self.thick_len_spin.blockSignals(False)
        self.thick_mult_spin.blockSignals(True)
        self.thick_mult_spin.setValue(rs.thick_mult)
        self.thick_mult_spin.blockSignals(False)
        self.dots_spin.blockSignals(True)
        self.dots_spin.setValue(rs.dots)
        self.dots_spin.blockSignals(False)
        self.spacing_spin.blockSignals(True)
        self.spacing_spin.setValue(rs.dot_spacing)
        self.spacing_spin.blockSignals(False)
        self.radius_spin.blockSignals(True)
        self.radius_spin.setValue(rs.dot_radius)
        self.radius_spin.blockSignals(False)
        self.color_btn.set_color(rs.color)
        self._update_group_visibility()
        self._draw_preview()

    def _update_group_visibility(self):
        self.duplex_group.setVisible(self.rs.style == STYLE_DUPLEX)
        self.mil_group.setVisible(self.rs.style == STYLE_MIL_DOT)

    def _draw_preview(self):
        pm = QPixmap(self.preview.width() or 320, 120)
        pm.fill(QColor(16, 18, 22))
        p = QPainter(pm)
        try:
            p.setPen(QColor(40, 46, 54))
            for x in range(0, pm.width(), 24):
                p.drawLine(x, 0, x, pm.height())
            for y in range(0, pm.height(), 24):
                p.drawLine(0, y, pm.width(), y)
            draw_reticle(p, pm.width() / 2.0, pm.height() / 2.0, self.rs)
        finally:
            p.end()
        self.preview.setPixmap(pm)

    def refresh_preview(self):
        self._draw_preview()

    # ---------------------------------------------------------------- slots

    def _on_style_changed(self):
        key = self.style_combo.currentData()
        if key in STYLE_KEYS:
            self.rs.style = key
            self._update_group_visibility()
            self._emit_changed()

    def _set_color(self, color):
        self.rs.color = color
        self._emit_changed()

    def _on_param(self, value):
        sender = self.sender()
        rs = self.rs
        if sender in (self._spins["thickness"][0], self._spins["thickness"][1]):
            rs.thickness = value
        elif sender in (self._spins["length"][0], self._spins["length"][1]):
            rs.length = value
        elif sender in (self._spins["gap"][0], self._spins["gap"][1]):
            rs.gap = value
        elif sender in (self._spins["opacity"][0], self._spins["opacity"][1]):
            rs.opacity = value
        elif sender is self.thick_len_spin:
            rs.thick_len = value
        elif sender is self.thick_mult_spin:
            rs.thick_mult = value
        elif sender is self.dots_spin:
            rs.dots = value
        elif sender is self.spacing_spin:
            rs.dot_spacing = value
        elif sender is self.radius_spin:
            rs.dot_radius = value
        else:
            return
        self._emit_changed()

    def _on_flag(self, checked):
        rs = self.rs
        if self.sender() is self.outline_check:
            rs.outline = bool(checked)
        elif self.sender() is self.center_check:
            rs.center_dot = bool(checked)
        self._emit_changed()

    def _emit_changed(self):
        self._draw_preview()
        self.changed.emit()

    def set_style_object(self, style: ReticleStyle):
        self.rs = style
        self._load_from_style()

    # -------------------------------------------------------------- presets

    def _preset_save(self):
        slot = str(self.preset_combo.currentData())
        self.presets[slot] = copy.deepcopy(self.rs.to_dict())

    def _preset_load(self):
        slot = str(self.preset_combo.currentData())
        data = self.presets.get(slot)
        if isinstance(data, dict):
            self.rs.apply(ReticleStyle.from_dict(data))
            self._load_from_style()
            self._emit_changed()
