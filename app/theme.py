# -*- coding: utf-8 -*-
"""SENTINEL NVR theme: unified dark green "surveillance" styling for the app.

Single source of design tokens. apply(app) installs the QPalette and the
global stylesheet; all widgets pick the theme up automatically.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------- tokens
BG = "#0a0d0b"            # window background (deep green-black)
PANEL = "#121614"         # cards / panels
DIALOG = "#0e1210"        # dialogs / popovers / menus

ACCENT = "#34d399"        # emerald primary
ACCENT_HOVER = "#3edba1"
ACCENT_PRESSED = "#2bb98a"
ACCENT_DIM = "rgba(52, 211, 153, 0.15)"
ACCENT_GLOW = "rgba(52, 211, 153, 0.07)"

TEXT = "#f4f4f5"          # primary text (zinc-100)
TEXT2 = "#d4d4d8"         # secondary text (zinc-300)
TEXT_MUTED = "#a1a1aa"    # muted (zinc-400)
TEXT_SOFT = "#71717a"     # soft (zinc-500)
TEXT_FAINT = "#52525b"    # faint (zinc-600)

DANGER = "#ef4444"
DANGER_HOVER = "#f87171"
DANGER_DIM = "rgba(239, 68, 68, 0.10)"
AMBER = "#fbbf24"

BORDER = "rgba(255, 255, 255, 0.08)"
BORDER_STRONG = "rgba(255, 255, 255, 0.12)"
INPUT_BG = "rgba(255, 255, 255, 0.04)"
INPUT_FOCUS = ACCENT
HOVER_BG = "rgba(255, 255, 255, 0.10)"
PRESSED_BG = "rgba(255, 255, 255, 0.16)"
BTN_BG = "rgba(255, 255, 255, 0.05)"

RADIUS_CARD = 12
RADIUS_CTL = 8

ON_ACCENT = "#08110d"     # text on emerald buttons


def button_role(button, role: str) -> None:
    """Assign a visual role to a QPushButton: accent | danger | secondary."""
    button.setProperty("buttonRole", role or None)
    button.style().unpolish(button)
    button.style().polish(button)


_BASE_QSS = f"""
* {{
    outline: none;
}}

QMainWindow, QWidget#rootSurface {{
    background: {BG};
}}

QDialog {{
    background: {DIALOG};
}}

/* ------------------------------------------------------------ buttons */
QPushButton {{
    background: {BTN_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CTL}px;
    padding: 5px 14px;
    min-height: 18px;
    color: {TEXT2};
    font-weight: 500;
}}
QPushButton:hover {{
    background: {HOVER_BG};
    border-color: rgba(255, 255, 255, 0.18);
    color: {TEXT};
}}
QPushButton:pressed {{
    background: {PRESSED_BG};
}}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    background: rgba(255, 255, 255, 0.03);
    border-color: {BORDER};
}}
QPushButton[buttonRole="accent"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton[buttonRole="accent"]:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[buttonRole="accent"]:pressed {{
    background: {ACCENT_PRESSED};
}}
QPushButton[buttonRole="accent"]:disabled {{
    background: rgba(52, 211, 153, 0.35);
    border-color: transparent;
    color: rgba(8, 17, 13, 0.7);
}}
QPushButton[buttonRole="danger"] {{
    background: transparent;
    border: 1px solid rgba(239, 68, 68, 0.35);
    color: {DANGER_HOVER};
}}
QPushButton[buttonRole="danger"]:hover {{
    background: {DANGER_DIM};
    border-color: rgba(239, 68, 68, 0.55);
    color: {DANGER_HOVER};
}}
QPushButton[buttonRole="danger"]:pressed {{
    background: rgba(239, 68, 68, 0.22);
}}

/* ------------------------------------------------------------ inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {INPUT_BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_CTL}px;
    padding: 4px 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {INPUT_FOCUS};
}}
QLineEdit:disabled, QSpinBox:disabled {{
    color: {TEXT_FAINT};
    background: rgba(255, 255, 255, 0.02);
}}
QLineEdit[placeholderText=""] {{ /* no-op, keeps selectors valid */ }}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 16px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {TEXT_SOFT};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {TEXT_SOFT};
}}

/* ------------------------------------------------------------ combo */
QComboBox {{
    background: {INPUT_BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_CTL}px;
    padding: 4px 26px 4px 8px;
    color: {TEXT};
    min-height: 18px;
}}
QComboBox:hover {{
    border-color: rgba(255, 255, 255, 0.2);
}}
QComboBox:focus {{
    border: 1px solid {INPUT_FOCUS};
}}
QComboBox:disabled {{
    color: {TEXT_FAINT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_SOFT};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {DIALOG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT2};
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
    outline: none;
    padding: 4px;
}}

/* ------------------------------------------------------------ group / glass */
QGroupBox {{
    font-weight: 600;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
    margin-top: 12px;
    padding: 8px 6px 6px 6px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.045),
        stop:1 rgba(255, 255, 255, 0.018));
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT_MUTED};
}}

/* ------------------------------------------------------------ menus */
QMenuBar {{
    background: {BG};
    color: {TEXT2};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item {{
    padding: 4px 10px;
    border-radius: 6px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background: {HOVER_BG};
    color: {TEXT};
}}
QMenu {{
    background: {DIALOG};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{
    padding: 5px 24px 5px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {ACCENT_DIM};
    color: {TEXT};
}}
QMenu::item:disabled {{
    color: {TEXT_FAINT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}

/* ------------------------------------------------------------ tooltip */
QToolTip {{
    background: {DIALOG};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
}}

/* ------------------------------------------------------------ status bar */
QStatusBar {{
    background: {BG};
    color: {TEXT_SOFT};
    border-top: 1px solid {BORDER};
}}
QStatusBar QLabel {{
    color: {TEXT_SOFT};
}}

/* ------------------------------------------------------------ lists / tables */
QListWidget, QTableWidget, QListView {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
    color: {TEXT2};
    padding: 4px;
}}
QListWidget::item {{
    color: {TEXT2};
    border-radius: 8px;
    padding: 4px;
    margin: 2px;
}}
QListWidget::item:hover {{
    background: rgba(255, 255, 255, 0.04);
}}
QListWidget::item:selected {{
    background: {ACCENT_DIM};
    color: {TEXT};
}}
QTableWidget {{
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {PANEL};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 5px 8px;
}}

/* ------------------------------------------------------------ scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.12);
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(52, 211, 153, 0.35);
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 0.12);
    border-radius: 3px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(52, 211, 153, 0.35);
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ------------------------------------------------------------ sliders */
QSlider::groove:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.10);
}}
QSlider::sub-page:horizontal {{
    background: rgba(52, 211, 153, 0.45);
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT_HOVER};
}}

/* ------------------------------------------------------------ checks */
QCheckBox, QRadioButton {{
    color: {TEXT2};
    spacing: 7px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER_STRONG};
    background: {INPUT_BG};
}}
QCheckBox::indicator {{
    border-radius: 4px;
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: rgba(255, 255, 255, 0.25);
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
        stop:0 {ACCENT}, stop:0.55 {ACCENT}, stop:0.7 {INPUT_BG}, stop:1 {INPUT_BG});
    border-color: {ACCENT};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {BORDER};
    background: rgba(255, 255, 255, 0.02);
}}

/* ------------------------------------------------------------ misc */
QSplitter::handle {{
    background: {BG};
}}
QSplitter::handle:horizontal {{
    width: 3px;
}}
QSplitter::handle:hover {{
    background: rgba(52, 211, 153, 0.35);
}}

QLabel#sysActive {{
    color: {TEXT_FAINT};
    font-size: 11px;
}}
QLabel#hudMeta {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QLabel#cardTitle {{
    color: {TEXT};
    font-weight: 600;
}}
QFrame#glassCard {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.045),
        stop:1 rgba(255, 255, 255, 0.018));
}}
/* ------------------------------------------------------------ archive cards */
QFrame#archCard {{
    border: 1px solid {{BORDER}};
    border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.04),
        stop:1 rgba(255, 255, 255, 0.015));
}}
QFrame#archCard:hover {{
    border: 1px solid rgba(255, 255, 255, 0.20);
}}
QFrame#archCard[selected="true"] {{
    border: 1px solid rgba(52, 211, 153, 0.55);
    background: rgba(52, 211, 153, 0.06);
}}

/* ------------------------------------------------------------ top nav */
QPushButton[nav="true"] {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 7px 14px;
    color: #a1a1aa;
    font-weight: 500;
}}
QPushButton[nav="true"]:hover {{
    background: rgba(255, 255, 255, 0.05);
    color: #f4f4f5;
}}
QPushButton[nav="true"]:checked {{
    background: rgba(52, 211, 153, 0.12);
    color: #6ee7b7;
    font-weight: 600;
}}
QFrame#topBar {{
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.045),
        stop:1 rgba(255, 255, 255, 0.018));
}}

/* ------------------------------------------------------------ PTZ pad */
QPushButton[ptz="true"] {{
    padding: 0;
    min-height: 0;
    font-size: 15px;
    font-weight: 600;
    color: {{TEXT2}};
}}
QPushButton[ptz="true"]:hover {{
    border: 1px solid rgba(52, 211, 153, 0.55);
    color: {{ACCENT_HOVER}};
    background: rgba(52, 211, 153, 0.08);
}}
QPushButton[ptz="true"]:pressed {{
    background: rgba(52, 211, 153, 0.22);
    color: {{ACCENT}};
}}
QPushButton[ptzHome="true"] {{
    background: {{ACCENT_DIM}};
    border: 1px solid rgba(52, 211, 153, 0.40);
    color: {{ACCENT}};
    font-weight: 700;
    padding: 0;
    min-height: 0;
}}
QPushButton[ptzHome="true"]:hover {{
    background: rgba(52, 211, 153, 0.28);
}}
QPushButton[ptzHome="true"]:pressed {{
    background: rgba(52, 211, 153, 0.45);
}}
"""


def build_palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(PANEL))
    pal.setColor(QPalette.AlternateBase, QColor("#161a18"))
    pal.setColor(QPalette.ToolTipBase, QColor(DIALOG))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT2))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(BG))
    pal.setColor(QPalette.ButtonText, QColor(TEXT2))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(ON_ACCENT))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_SOFT))
    disabled = QColor("#4a4f4c")
    for group in (QPalette.Disabled,):
        pal.setColor(group, QPalette.Text, disabled)
        pal.setColor(group, QPalette.ButtonText, disabled)
        pal.setColor(group, QPalette.WindowText, disabled)
        pal.setColor(group, QPalette.Base, QColor("#0d100e"))
    return pal


def apply(app: QApplication) -> None:
    """Install the SENTINEL NVR palette + global stylesheet."""
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setStyleSheet(_BASE_QSS)
