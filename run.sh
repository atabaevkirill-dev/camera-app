#!/usr/bin/env bash
# ONVIF Reticle Station — one-command install & run (Linux / macOS)
set -e
cd "$(dirname "$0")"

PY=python3
if ! command -v $PY >/dev/null 2>&1; then
    echo "[ERROR] python3 not found."
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora:         sudo dnf install python3"
    echo "  macOS:          brew install python3"
    exit 1
fi

# 1) virtual env (auto-created once)
if [ ! -x venv/bin/python ]; then
    echo "[SETUP] Creating virtual environment..."
    $PY -m venv venv
fi

PIP="venv/bin/python -m pip"

# 2) dependencies (fast no-op when already installed)
if ! venv/bin/python -c "import PySide6, cv2, requests, PIL, imageio_ffmpeg" >/dev/null 2>&1; then
    echo "[SETUP] Installing dependencies (first run only)..."
    $PIP install --upgrade pip -q
    $PIP install -r requirements.txt
fi

# 3) run
echo "[START] ONVIF Reticle Station..."
exec venv/bin/python main.py "$@"
