# -*- coding: utf-8 -*-
"""Application settings dialog: screenshot and recording paths."""

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout)

from .i18n import tr


class AppSettingsDialog(QDialog):
    """Edits application config dict in place."""

    def __init__(self, app_cfg: dict, parent=None):
        super().__init__(parent)
        self.app_cfg = app_cfg
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(tr("app_dlg.title"))
        self.setMinimumWidth(500)

        root = QVBoxLayout(self)

        # --- Paths Group ---
        paths_group = QGroupBox(tr("paths.group"))
        paths_form = QFormLayout(paths_group)

        # Screenshot Path
        self.ss_path_edit = QLineEdit(self.app_cfg.get("screenshot_dir", ""))
        ss_browse_btn = QPushButton(tr("paths.browse"))
        ss_browse_btn.clicked.connect(lambda: self._browse_directory(self.ss_path_edit))
        ss_row = QHBoxLayout()
        ss_row.addWidget(self.ss_path_edit)
        ss_row.addWidget(ss_browse_btn)
        paths_form.addRow(tr("paths.screenshot"), ss_row)

        # Recording Path
        self.rec_path_edit = QLineEdit(self.app_cfg.get("recording_dir", ""))
        rec_browse_btn = QPushButton(tr("paths.browse"))
        rec_browse_btn.clicked.connect(lambda: self._browse_directory(self.rec_path_edit))
        rec_row = QHBoxLayout()
        rec_row.addWidget(self.rec_path_edit)
        rec_row.addWidget(rec_browse_btn)
        paths_form.addRow(tr("paths.recording"), rec_row)

        root.addWidget(paths_group)

        # --- Buttons ---
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_directory(self, line_edit: QLineEdit):
        current_path = line_edit.text() or os.path.expanduser("~")
        directory = QFileDialog.getExistingDirectory(
            self, tr("paths.select_dir"), current_path, QFileDialog.ShowDirsOnly
        )
        if directory:
            line_edit.setText(directory)

    def accept(self):
        # Validate and update config
        ss_path = self.ss_path_edit.text().strip()
        rec_path = self.rec_path_edit.text().strip()

        if not ss_path or not rec_path:
            # Handle error or show warning
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("paths.warn_title"), tr("paths.warn_empty"))
            return

        self.app_cfg["screenshot_dir"] = ss_path
        self.app_cfg["recording_dir"] = rec_path
        super().accept()