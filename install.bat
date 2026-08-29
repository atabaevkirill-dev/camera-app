@echo off
rem Install only (no launch). Run: install.bat
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
)
"venv\Scripts\python.exe" -c "import PySide6, cv2, requests, PIL, imageio_ffmpeg" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing dependencies...
    "venv\Scripts\python.exe" -m pip install --upgrade pip -q
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
)
echo [OK] Installed. Launch with: run.bat
pause
