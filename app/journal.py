# -*- coding: utf-8 -*-
"""Journal view: in-app event feed (reference: Sentinel NVR JournalView)."""

from datetime import datetime

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .i18n import tr

MAX_ROWS = 500

LEVELS = {
    "INFO": ("#38bdf8", "Инфо"),
    "SUCCESS": ("#34d399", "Успех"),
    "WARN": ("#fbbf24", "Внимание"),
    "ERROR": ("#ef4444", "Ошибка"),
}


class EventBus(QObject):
    """Tiny global event bus: any module emits, JournalView listens."""
    event = Signal(str, str)  # level, message


bus = EventBus()


def log_event(level: str, message: str) -> None:
    bus.event.emit(level, message)


class JournalView(QWidget):
    """Structured, compact event feed with level badges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("glassCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(10, 10, 10, 10)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("j.level"), tr("j.time"), tr("j.event")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setShowGrid(False)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 110)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet("QTableWidget { border: none; }")
        card_lay.addWidget(self.table)
        lay.addWidget(card)

        self._empty_hint = QLabel(tr("j.empty"))
        self._empty_hint.setObjectName("hudMeta")
        self._empty_hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._empty_hint)
        self._empty_hint.setVisible(True)

        bus.event.connect(self._on_event)

    def _on_event(self, level: str, message: str):
        color, label = LEVELS.get(level, LEVELS["INFO"])
        row = self.table.rowCount()
        self.table.insertRow(row)

        lvl_item = QTableWidgetItem(f"●  {label}")
        lvl_item.setForeground(QColor(color))
        time_item = QTableWidgetItem(datetime.now().strftime("%H:%M:%S"))
        time_item.setForeground(QColor("#a1a1aa"))
        msg_item = QTableWidgetItem(message)
        msg_item.setForeground(QColor("#e4e4e7"))

        self.table.setItem(row, 0, lvl_item)
        self.table.setItem(row, 1, time_item)
        self.table.setItem(row, 2, msg_item)
        if row >= MAX_ROWS:
            self.table.removeRow(0)
        self._empty_hint.setVisible(False)
        self.table.scrollToBottom()
