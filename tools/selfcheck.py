#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless self-check: theme + shell (top nav) + all views + gallery cards.

Run: venv/bin/python tools/selfcheck.py   (QT_QPA_PLATFORM=offscreen is forced)
Exits 0 and prints SELFCHECK_OK on success.
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ONVIFSTATION_SELFTEST"] = "1"  # no auto-connect, no dialogs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app import profiles
from app.archive_db import ArchiveDB
from app.archive_dialog import ArchiveGallery
from app.logutil import setup_logging
from app.main_window import (MainWindow, VIEW_ARCHIVE, VIEW_EDITOR,
                             VIEW_JOURNAL, VIEW_MONITOR)
from app.theme import apply as apply_theme
from app.i18n import tr


def main() -> int:
    setup_logging(profiles.APP_DIR)
    app = QApplication(sys.argv)
    apply_theme(app)

    cfg = profiles.load_profiles()
    win = MainWindow(cfg)
    win.show()

    assert win.stack.count() == 4, f"expected 4 views, got {win.stack.count()}"
    assert win._record_all_btn is not None and win._record_all_btn.text()
    assert len(win.nav_buttons) == 4 and win.nav_buttons[0].isChecked()
    assert tr("hdr.reticle_on") in win._reticle_toggle_btn.text(), win._reticle_toggle_btn.text()

    win._switch_view(VIEW_ARCHIVE)
    app.processEvents()
    win._switch_view(VIEW_EDITOR)
    app.processEvents()
    win._switch_view(VIEW_JOURNAL)
    app.processEvents()
    win._switch_view(VIEW_MONITOR)
    app.processEvents()

    # gallery card rendering on a temp DB with a real thumbnail
    tmp_dir = tempfile.mkdtemp(prefix="reticle-selfcheck-")
    shots_dir = os.path.join(tmp_dir, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    from PIL import Image
    Image.new("RGB", (320, 180), (40, 200, 120)).save(os.path.join(shots_dir, "cam1_20260101_120000.png"))
    db = ArchiveDB(tmp_dir)
    base = {"screenshot": shots_dir, "recording": os.path.join(tmp_dir, "recs")}
    db.sync_with_directories(base)
    db.backfill_metadata(base)
    gallery = ArchiveGallery(db, base)
    gallery.show()
    gallery._on_loaded(list(db.get_all_items(base)))
    assert len(gallery._cards) == 1, f"expected 1 card, got {len(gallery._cards)}"
    gallery.hide()

    def finish():
        win.close()
        app.quit()

    QTimer.singleShot(700, finish)
    rc = app.exec()
    if rc == 0:
        print("SELFCHECK_OK")
    else:
        print("SELFCHECK_FAILED rc=", rc)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
