# -*- coding: utf-8 -*-
"""Central logging: rotating file + console. Replaces scattered print()."""

import logging
import os
from logging.handlers import RotatingFileHandler

_CONFIGURED = False
_ROOT = "onvifstation"


def setup_logging(app_dir: str, level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True
    log_dir = os.path.join(app_dir, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        file_handler = None
    root = logging.getLogger(_ROOT)
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                            "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    if file_handler is not None:
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{_ROOT}.{name}")
