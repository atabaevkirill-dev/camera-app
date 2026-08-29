#!/usr/bin/env bash
# Install only (no launch): venv + dependencies. Run: ./install.sh
set -e
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then
    echo "[SETUP] Creating virtual environment..."
    python3 -m venv venv
fi
if ! venv/bin/python -c "import PySide6, cv2, requests, PIL, imageio_ffmpeg" >/dev/null 2>&1; then
    echo "[SETUP] Installing dependencies..."
    venv/bin/python -m pip install --upgrade pip -q
    venv/bin/python -m pip install -r requirements.txt
fi
echo "[OK] Installed. Launch with: ./run.sh"
