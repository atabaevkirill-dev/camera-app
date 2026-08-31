# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all data files from the 'app' directory excluding Python source files
app_data_files = []
for root, dirs, files in os.walk('app'):
    for file in files:
        if not file.endswith('.py') and not file.endswith('.pyc') and not file.endswith('.pyo'):
            app_data_files.append((os.path.join(root, file), root))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=app_data_files,  # Include collected data files
    hiddenimports=[
        'app.main_window', 'app.ptz_pad', 'app.onvif_client', 'app.video_panel', 'app.icons', 'app.i18n', 'app.logutil', 'app.theme', 'app.profiles', 'app.settings_dialog', 'app.app_settings_dialog', 'app.discover_dialog', 'app.archive_dialog', 'app.editor_dialog', 'app.journal', 'app.reticle', 'app.split_recorder', 'app.archive_db', 'app.stream_worker'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CameraApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False, # Set to True for debugging if needed to see console output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)