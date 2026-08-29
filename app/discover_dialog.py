# -*- coding: utf-8 -*-
"""ONVIF camera auto-discovery dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .discovery import DiscoveryWorker
from .i18n import tr


class DiscoverDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("disc.title"))
        self.setMinimumSize(640, 420)
        self._worker = None
        self.selected = None  # dict or None

        root = QVBoxLayout(self)
        self.hint = QLabel(tr("disc.hint"))
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("disc.col_ip"), tr("disc.col_xaddr")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 160)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.scan_btn = QPushButton(tr("disc.scan"))
        self.scan_btn.clicked.connect(self._scan)
        self.to1_btn = QPushButton(tr("disc.to1"))
        self.to1_btn.clicked.connect(lambda: self._transfer(0))
        self.to2_btn = QPushButton(tr("disc.to2"))
        self.to2_btn.clicked.connect(lambda: self._transfer(1))
        btns.addWidget(self.scan_btn)
        btns.addWidget(self.to1_btn)
        btns.addWidget(self.to2_btn)
        btns.addStretch(1)
        root.addLayout(btns)

        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.reject)
        close_box.clicked.connect(lambda *_: self.reject())
        root.addWidget(close_box)

        self._scan()

    def _scan(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(tr("disc.scanning"))
        self._worker = DiscoveryWorker(4.5, self)
        self._worker.finished.connect(self._on_results)
        self._worker.start()

    def _on_results(self, results: list):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(tr("disc.scan"))
        self.table.setRowCount(0)
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            ip_item = QTableWidgetItem(r.get("ip", ""))
            ip_item.setData(Qt.UserRole, r)
            self.table.setItem(row, 0, ip_item)
            self.table.setItem(row, 1, QTableWidgetItem(r.get("xaddrs", "")))
        if not results:
            self.hint.setText(tr("disc.none"))

    def _transfer(self, cam_index: int):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        self.selected = item.data(Qt.UserRole)
        self.selected["target"] = cam_index
        self.accept()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.wait(200)
            except Exception:
                pass
        event.accept()
