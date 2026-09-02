# -*- coding: utf-8 -*-
"""JSON profiles: camera settings, reticles, UI state."""

import copy
import json
import os
import re
import time

from .logutil import get_logger
from .onvif_client import strip_userinfo

log = get_logger("profiles")

from .reticle import ReticleStyle

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(APP_DIR, "camera_profiles.json")
# These will be updated by load_profiles if present in cfg
SCREENSHOT_DIR = os.path.join(APP_DIR, "screenshots")
RECORDING_DIR = os.path.join(APP_DIR, "recordings")

# Set by load_profiles when the on-disk config was unreadable and got backed up
corrupt_backup_path = None


def default_camera() -> dict:
    return {
        "autoconnect": False,
        "source_type": "rtsp",  # rtsp | webcam
        "webcam_index": 0,
        "connection": {
            "host": "",
            "port": 80,
            "username": "",
            "password": "",
            "auth": "digest",  # digest | plain
        },
        "rtsp": {
            "url": "",
            "transport": "tcp",     # tcp | udp
            "low_latency": True,
            "record_fps": 25,
        },
        "pelco_d": {
            "enabled": False,
            "ip": "",
            "port": 9761,
            "address": 1,
        },
        "reticle": ReticleStyle().to_dict(),
        "reticle_presets": {},      # "1".."5" -> ReticleStyle dict
        "ptz": {"speed": 50},
    }


def default_profiles() -> dict:
    return {
        "language": "ru",
        "screenshot_dir": SCREENSHOT_DIR,  # Default screenshot dir
        "recording_dir": RECORDING_DIR,    # Default recording dir
        "splitter": [],
        "cameras": {
            "cam1": default_camera(),
            "cam2": default_camera(),
        },
    }


def _deep_merge(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_profiles() -> dict:
    global corrupt_backup_path
    cfg = default_profiles()
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _deep_merge(cfg, data)
    except FileNotFoundError:
        pass
    except Exception as e:
        # Corrupt config: keep a backup so nothing is silently lost (C7)
        backup = f"{PROFILE_PATH}.corrupt-{time.strftime('%Y%m%d_%H%M%S')}"
        try:
            os.replace(PROFILE_PATH, backup)
            corrupt_backup_path = backup
            log.error("Corrupt profiles file moved to %s: %s", backup, e)
        except OSError:
            log.error("Corrupt profiles file could not be backed up: %s", e)
    
    # Update global paths based on loaded config
    global SCREENSHOT_DIR, RECORDING_DIR
    SCREENSHOT_DIR = cfg.get("screenshot_dir", SCREENSHOT_DIR)
    RECORDING_DIR = cfg.get("recording_dir", RECORDING_DIR)

    # sanity
    for key in ("cam1", "cam2"):
        cam = cfg["cameras"].setdefault(key, default_camera())
        for sub, dflt in default_camera().items():
            cam.setdefault(sub, copy.deepcopy(dflt))
        if not isinstance(cam["reticle"], dict):
            cam["reticle"] = ReticleStyle().to_dict()
    return cfg


def _sanitize_credentials(cfg: dict) -> None:
    """Never persist user:pass@ inside RTSP URLs (C6)."""
    for cam in (cfg.get("cameras") or {}).values():
        if not isinstance(cam, dict):
            continue
        rtsp = cam.get("rtsp") or {}
        url = rtsp.get("url") or ""
        clean = strip_userinfo(url)
        if clean != url:
            rtsp["url"] = clean
            log.info("Stripped credentials from stored RTSP URL")


def save_profiles(cfg: dict) -> bool:
    try:
        _sanitize_credentials(cfg)
        tmp = PROFILE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROFILE_PATH)
        return True
    except Exception:
        return False


def reticle_for(cfg: dict, cam_key: str) -> ReticleStyle:
    return ReticleStyle.from_dict(cfg["cameras"][cam_key].get("reticle", {}))


def presets_for(cfg: dict, cam_key: str) -> dict:
    p = cfg["cameras"][cam_key].setdefault("reticle_presets", {})
    if not isinstance(p, dict):
        cfg["cameras"][cam_key]["reticle_presets"] = {}
        p = cfg["cameras"][cam_key]["reticle_presets"]
    return p
