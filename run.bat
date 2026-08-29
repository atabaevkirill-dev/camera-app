@echo off
rem ONVIF Reticle Station - one-command install & run (Windows)
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    echo Be sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

rem 1) virtual env (auto-created once)
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
)

rem 2) dependencies (fast no-op when already installed)
"venv\Scripts\python.exe" -c "import PySide6, cv2, requests, PIL, imageio_ffmpeg" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing dependencies (first run only, may take a few minutes)...
    "venv\Scripts\python.exe" -m pip install --upgrade pip -q
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
)

rem 3) run
echo [START] ONVIF Reticle Station...
"venv\Scripts\python.exe" main.py
pause
