#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ONVIF Reticle Station
Desktop application for two IP cameras (industrial zoom camera + thermal imager).
ONVIF / RTSP, reticle overlays, PTZ control, auto discovery.
"""

import os
import sys


def main() -> int:
    selftest = "--selftest" in sys.argv
    if selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ["ONVIFSTATION_SELFTEST"] = "1"

    from PySide6.QtWidgets import QApplication, QMessageBox

    from app import profiles
    from app.i18n import set_lang, tr
    from app.logutil import setup_logging, get_logger
    from app.main_window import MainWindow
    from app.theme import apply as apply_theme

    setup_logging(profiles.APP_DIR)
    log = get_logger("main")
    log.info("Starting ONVIF Reticle Station%s", " (selftest)" if selftest else "")

    cfg = profiles.load_profiles()
    set_lang(cfg.get("language", "ru"))

    app = QApplication(sys.argv)
    app.setApplicationName("ONVIF Reticle Station")
    apply_theme(app)  # SENTINEL NVR theme (palette + global QSS)

    # Corrupt config was backed up: tell the user once (C7)
    if profiles.corrupt_backup_path and not selftest:
        QMessageBox.warning(
            None, "ONVIF Reticle Station",
            tr("msg.config_corrupt", path=profiles.corrupt_backup_path))

    win = MainWindow(cfg)
    win.show()

    if selftest:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, app.quit)
        rc = app.exec()
        print("SELFTEST_OK")
        return rc

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
