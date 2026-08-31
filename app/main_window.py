# -*- coding: utf-8 -*-
"""Main window: splitter with two camera columns, menus, PTZ, profiles."""

import os
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QPushButton, QSplitter,
                               QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from . import profiles
from .archive_db import ArchiveDB
from .archive_dialog import ArchiveGallery, mono_font
from .app_settings_dialog import AppSettingsDialog
from .discover_dialog import DiscoverDialog
from .i18n import get_lang, set_lang, tr
from .icons import icon, set_button_icon
from .journal import JournalView, log_event
from .logutil import get_logger
from .onvif_client import OnvifClient, OnvifError, ensure_credentials, strip_userinfo
from .ptz_pad import PTZPad
from .split_recorder import SplitRecorder
from .editor_dialog import EditorWidget
from .reticle import ReticleStyle
from .settings_dialog import SettingsDialog
from . import theme
from .stream_worker import StreamWorker
from .video_panel import VideoPanel


log = get_logger("main_window")

CAM_KEYS = ("cam1", "cam2")
VIEW_MONITOR, VIEW_ARCHIVE, VIEW_EDITOR, VIEW_JOURNAL = 0, 1, 2, 3
SELFTEST = os.environ.get("ONVIFSTATION_SELFTEST") == "1"


class CameraConnector(QThread):
    """Resolves ONVIF capabilities/profiles/stream URI off the GUI thread (C2)."""

    resolved = Signal(int, bool, str, str, str, str)  # idx, ok, url(creds), profile, vstoken, error

    def __init__(self, idx: int, conn: dict, rtsp: dict, parent=None):
        super().__init__(parent)
        self._idx = idx
        self._conn = conn
        self._rtsp = rtsp

    ATTEMPTS = 3

    def run(self):
        last_err = ""
        for attempt in range(1, self.ATTEMPTS + 1):
            if self.isInterruptionRequested():
                return
            try:
                client = OnvifClient(self._conn.get("host", ""), self._conn.get("port", 80),
                                     self._conn.get("username", ""), self._conn.get("password", ""),
                                     self._conn.get("auth", "digest"))
                client.get_capabilities()
                profile = ""
                profs = client.get_profiles()
                if profs:
                    profile = profs[0]["token"]
                url = (self._rtsp.get("url") or "").strip()
                if not url:
                    if not profile:
                        raise OnvifError("No media profiles")
                    url = client.get_stream_uri(profile)
                url = client.inject_credentials(url)
                vstoken = ""
                try:
                    vsc = client.get_video_source_configurations()
                    if vsc:
                        vstoken = vsc[0]["token"]
                except Exception:
                    pass
                self.resolved.emit(self._idx, True, url, profile, vstoken, "")
                return
            except Exception as e:
                last_err = str(e)
                log.warning("ONVIF resolve attempt %d/%d failed for cam%d: %s",
                            attempt, self.ATTEMPTS, self._idx + 1, e)
                time.sleep(1.2 * attempt)
        self.resolved.emit(self._idx, False, "", "", "", last_err)


class PTZProbe(QThread):
    """PTZ capability probe off the GUI thread (C2)."""

    probed = Signal(int, bool, str, str)  # idx, supported, profile, vstoken

    def __init__(self, idx: int, client: OnvifClient, parent=None):
        super().__init__(parent)
        self._idx = idx
        self._client = client

    def run(self):
        supported = False
        profile = ""
        vstoken = ""
        try:
            caps = self._client.get_capabilities()
            # Only treat PTZ as supported when the device actually exposes a usable
            # PTZ-capable profile. Imaging-only devices still expose AF/focus, but
            # PTZ pan/tilt/zoom commands require a PTZ-enabled profile token.
            if caps.get("ptz"):
                try:
                    profile = self._client.get_ptz_profile_token()
                    supported = bool(profile)
                except Exception as e:
                    log.warning("Could not resolve PTZ profile for cam%d: %s", self._idx + 1, e)
                    supported = False
            elif caps.get("imaging"):
                # Focus-only device: allow imaging commands without claiming pan/tilt
                # support. Keep the profile empty so PTZ commands are blocked.
                supported = True
                try:
                    profs = self._client.get_profiles()
                    if profs:
                        profile = profs[0]["token"]
                except Exception:
                    profile = ""

            if supported:
                try:
                    vsc = self._client.get_video_source_configurations()
                    if vsc:
                        vstoken = vsc[0]["token"]
                except Exception as e:
                    log.warning("Could not get VideoSourceToken for cam%d: %s", self._idx + 1, e)
        except Exception as e:
            log.warning("PTZ probe failed for cam%d: %s", self._idx + 1, e)
        self.probed.emit(self._idx, supported, profile, vstoken)


class ArchiveSyncer(QThread):
    """Background archive sync: directory scan, thumbnails, DB cleanup (C8)."""

    done = Signal()

    def __init__(self, db: ArchiveDB, base_dirs: dict, parent=None):
        super().__init__(parent)
        self._db = db
        self._base_dirs = base_dirs

    def run(self):
        try:
            self._db.sync_with_directories(self._base_dirs)
            self._db.backfill_metadata(self._base_dirs)
            self._db.cleanup_missing(self._base_dirs)
        except Exception as e:
            log.warning("Archive sync failed: %s", e)
        self.done.emit()


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.archive_db = ArchiveDB(os.path.dirname(profiles.PROFILE_PATH))
        self.panels = []
        self.workers = [None, None]
        self._zombies = []            # workers still finishing; kept referenced (C3)
        self._onvif = [None, None]
        self._ptz_profile = ["", ""]
        self._vstoken = ["", ""]
        self.record_buttons = []
        self._pads = []
        self._titles = []
        self._buttons = []
        self._connector = None
        self._record_all_btn = None
        self._rec_timer = None
        self._cam_chips = []
        self._split_recorder = None
        self._reticle_in_rec = True
        self._reticle_toggle_btn = None
        self._editor_btn = None
        self._connect_gen = [0, 0]    # invalidates stale connect results
        self._probes = [None, None]
        self._syncer = None
        self._sync_pending = False
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="main-onvif")

        self.setWindowTitle(tr("app.title"))
        self.resize(1500, 860)

        central = QWidget()
        central.setObjectName("rootSurface")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)

        self._build_shell(root)

        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Horizontal)
        page_lay.addWidget(self.splitter, 1)
        for idx in range(2):
            col = self._build_camera_column(idx)
            self.splitter.addWidget(col)
        self.stack.addWidget(page)  # VIEW_MONITOR

        self.archive_view = ArchiveGallery(self.archive_db, self._base_dirs())
        self.archive_view.openAppSettings.connect(self._open_app_settings)
        self.archive_view.openEditorRequested.connect(self._open_editor_with)
        self.stack.addWidget(self.archive_view)  # VIEW_ARCHIVE

        self.editor_view = EditorWidget(self.archive_db, self._base_dirs())
        self.editor_view.exported.connect(self._schedule_archive_sync)
        self.stack.addWidget(self.editor_view)  # VIEW_EDITOR

        from .journal import JournalView
        self.journal_view = JournalView()
        self.stack.addWidget(self.journal_view)  # VIEW_JOURNAL

        sizes = self.cfg.get("splitter") or []
        if len(sizes) == 2 and all(isinstance(v, int) and v > 0 for v in sizes):
            total = sum(sizes)
            if total > 200:
                self.splitter.setSizes(sizes)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        self.statusBar().showMessage("")
        self._sys_label = QLabel()
        self._sys_label.setObjectName("sysActive")
        self.statusBar().addPermanentWidget(self._sys_label)

        self._build_menus()
        self._build_shortcuts()
        self.retranslate()

        if not SELFTEST:
            self._schedule_archive_sync()
            QTimer.singleShot(150, self._auto_connect)

    # ------------------------------------------------------------ UI build

    def _build_camera_column(self, idx: int) -> QWidget:
        cam_key = CAM_KEYS[idx]
        cam_cfg = self.cfg["cameras"][cam_key]
        reticle = ReticleStyle.from_dict(cam_cfg.get("reticle", {}))
        cam_cfg["reticle"] = reticle.to_dict()

        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(2, 0, 2, 0)

        title = QLabel()
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        panel = VideoPanel(reticle, idx)
        panel.message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        lay.addWidget(panel, 1)
        self.panels.append(panel)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        shot_btn = QPushButton()
        rec_btn = QPushButton()
        center_btn = QPushButton()
        zoom_btn = QPushButton()
        set_btn = QPushButton()
        shot_btn.clicked.connect(lambda: self._screenshot(idx))
        rec_btn.clicked.connect(lambda: self._toggle_record(idx))
        center_btn.clicked.connect(lambda: self._center_reticle(idx))
        zoom_btn.clicked.connect(lambda: self._reset_zoom(idx))
        set_btn.clicked.connect(lambda: self._open_settings(idx))
        for b in (shot_btn, rec_btn, center_btn, zoom_btn, set_btn):
            btn_row.addWidget(b)
        self.record_buttons.append(rec_btn)
        lay.addLayout(btn_row)
        panel.recordingChanged.connect(lambda rec, i=idx: self._update_rec_button(i))

        pad = PTZPad()
        pad.errorOccurred.connect(lambda m: self.statusBar().showMessage(
            f"PTZ: {m}", 5000))
        pad.set_backend(
            get_client=lambda i=idx: self._onvif_for_ptz(i),
            get_profile=lambda i=idx: self._ptz_profile[i],
            get_vstoken=lambda i=idx: self._vstoken[i],
        )
        lay.addWidget(pad)
        self._pads.append(pad)
        self._titles.append(title)
        self._buttons.append((shot_btn, rec_btn, center_btn, zoom_btn, set_btn))
        return col

    # ------------------------------------------------------------ top nav

    def _build_shell(self, root_layout):
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(58)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 9, 12, 9)
        h.setSpacing(10)

        brand = QLabel()
        brand.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #34d399, stop:1 #059669);"
            "border-radius: 9px; color: #08110d; font-weight: 800; font-size: 15px;"
            "qproperty-alignment: AlignCenter;")
        brand.setFixedSize(34, 34)
        brand.setText("R")
        h.addWidget(brand)

        titles = QLabel()
        titles.setText(f'<span style="color:{theme.TEXT}; font-weight:700; font-size:13px;">'
                       f'RETICLE STATION</span><br>'
                       f'<span style="color:{theme.TEXT_FAINT}; font-size:9px; letter-spacing:2px;">'
                       f'SENTINEL NVR EDITION</span>')
        h.addWidget(titles)
        h.addSpacing(6)

        # ---- navigation tabs (top only)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        nav_defs = [("nav.live", "monitor"), ("nav.archive", "folder"),
                    ("nav.editor", "scissors"), ("nav.journal", "clock")]
        for i, (key, ic) in enumerate(nav_defs):
            b = QPushButton(tr(key))
            b.setProperty("nav", "true")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(icon(ic, "#a1a1aa", 17))
            b.clicked.connect(lambda _=False, v=i: self._switch_view(v))
            self.nav_group.addButton(b, i)
            h.addWidget(b)
            self.nav_buttons.append(b)
        self.nav_buttons[VIEW_MONITOR].setChecked(True)

        h.addStretch(1)

        self._cam_chips = []
        for idx in range(2):
            chip = QLabel()
            chip.setObjectName("hudMeta")
            h.addWidget(chip)
            self._cam_chips.append(chip)
        h.addSpacing(4)

        self._reticle_in_rec = bool(self.cfg.get("reticle_in_recording", True))
        self._reticle_toggle_btn = QPushButton()
        self._reticle_toggle_btn.setCheckable(True)
        self._reticle_toggle_btn.setChecked(self._reticle_in_rec)
        self._reticle_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._reticle_toggle_btn.toggled.connect(self._on_reticle_toggle)
        self._apply_reticle_toggle(initial=True)
        h.addWidget(self._reticle_toggle_btn)

        self._record_all_btn = QPushButton()
        self._record_all_btn.setProperty("buttonRole", "danger")
        self._record_all_btn.setMinimumWidth(200)
        self._record_all_btn.clicked.connect(self._toggle_record_all)
        h.addWidget(self._record_all_btn)

        self._clock_label = QLabel()
        self._clock_label.setObjectName("hudMeta")
        self._clock_label.setFont(mono_font())
        self._clock_label.setText('<span style="color:#ef4444;">●</span> --:--:--')
        h.addWidget(self._clock_label)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        set_btn = QPushButton()
        set_btn.setFixedSize(34, 30)
        set_btn.setToolTip(tr("menu.app_settings"))
        from .icons import set_button_icon
        set_button_icon(set_btn, "settings", theme.TEXT_MUTED, 17)
        set_btn.clicked.connect(self._open_app_settings)
        h.addWidget(set_btn)

        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(1000)
        self._rec_timer.timeout.connect(self._update_record_all_button)

        self.stack = QStackedWidget()
        root_layout.addWidget(bar)
        root_layout.addWidget(self.stack, 1)

    def _update_clock(self):
        self._clock_label.setText(
            f'<span style="color:#ef4444;">●</span> {time.strftime("%H:%M:%S")}')

    def _switch_view(self, view: int):
        self.stack.setCurrentIndex(view)
        if view == VIEW_ARCHIVE:
            self.archive_view.refresh()
        elif view == VIEW_EDITOR:
            self.editor_view.refresh()

    def _apply_reticle_toggle(self, initial: bool = False):
        btn = self._reticle_toggle_btn
        on = self._reticle_in_rec
        btn.setText(tr("hdr.reticle_on") if on else tr("hdr.reticle_off"))
        btn.setProperty("ptzHome", "true" if on else None)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        if not initial:
            msg = tr("msg.rec_with_reticle") if on else tr("msg.rec_no_reticle")
            self.statusBar().showMessage(msg, 5000)
            log_event("INFO", msg)

    def _on_reticle_toggle(self, checked: bool):
        self._reticle_in_rec = bool(checked)
        self.cfg["reticle_in_recording"] = self._reticle_in_rec
        profiles.save_profiles(self.cfg)
        self._apply_reticle_toggle()

    def _reticle_for(self, idx: int):
        panel = self.panels[idx]
        dx, dy = panel.get_reticle_offset_norm()
        return dict(panel.reticle.to_dict()), (dx, dy)

    def _open_editor(self):
        self._switch_view(VIEW_EDITOR)

    def _open_editor_with(self, path: str):
        self._switch_view(VIEW_EDITOR)
        if path:
            self.editor_view.load_file(path)

    def _toggle_record_all(self):
        # Split recording takes priority: one combined file with both cameras.
        if self._split_recorder is not None and self._split_recorder.isRunning():
            self._split_recorder.stop()
            self.statusBar().showMessage(tr("msg.rec_stopped"), 5000)
            return
        # stop any per-camera recordings first
        for idx in range(2):
            w = self.workers[idx]
            if w is not None and w.is_recording():
                w.set_recording(None)
        online = [i for i in range(2) if self.panels[i].is_online()]
        if not online:
            self.statusBar().showMessage(tr("msg.need_url"), 5000)
            return
        recording_dir = self.cfg.get("recording_dir", profiles.RECORDING_DIR)
        os.makedirs(recording_dir, exist_ok=True)
        fname = f"split_{time.strftime('%Y%m%d_%H%M%S')}.avi"
        workers = [self.workers[i] for i in range(2)]
        styles = [self._reticle_for(i)[0] for i in range(2)]
        self._split_recorder = SplitRecorder(
            workers, styles, self._reticle_in_rec,
            os.path.join(recording_dir, fname),
            fps=int(self.cfg["cameras"]["cam1"]["rtsp"].get("record_fps", 25) or 25),
            parent=self)
        self._split_recorder.stopped.connect(lambda _p: self._on_split_stopped())
        self._split_recorder.failed.connect(lambda m: self._worker_message(0, m))
        self._split_recorder.start()
        self.statusBar().showMessage(
            tr("msg.rec_started", path=f"split ({len(online)}/2)"), 6000)
        self._update_record_all_button()

    def _on_split_stopped(self):
        log_event("SUCCESS", tr("msg.split_saved"))
        self._schedule_archive_sync()
        self._update_record_all_button()

    def _update_record_all_button(self):
        btn = self._record_all_btn
        if btn is None:
            return
        split_running = self._split_recorder is not None and self._split_recorder.isRunning()
        any_recording = split_running or any(self._is_recording(i) for i in range(2))
        if split_running:
            btn.setText(f"{tr('hdr.stop_all')}  SPLIT")
            if not self._rec_timer.isActive():
                self._rec_timer.start()
        elif any_recording:
            elapsed = max((self.workers[i].rec_elapsed() for i in range(2)
                           if self.workers[i] is not None), default=0.0)
            btn.setText(f"{tr('hdr.stop_all')}  {int(elapsed // 60):d}:{int(elapsed % 60):02d}")
            if not self._rec_timer.isActive():
                self._rec_timer.start()
        else:
            online = sum(1 for i in range(2) if self.panels[i].is_online())
            btn.setText(f"{tr('hdr.record_all')} ({online}/2)")
            self._rec_timer.stop()
        btn.setProperty("buttonRole", "danger" if any_recording else "accent")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _update_cam_chips(self):
        name0 = tr("app.cam1_name")
        name1 = tr("app.cam2_name")
        for idx, chip in enumerate(self._cam_chips):
            online = self.panels[idx].is_online()
            color = theme.ACCENT if online else theme.DANGER
            name = name0 if idx == 0 else name1
            chip.setText(f'<span style="color:{color};">●</span>'
                         f'<span style="color:{theme.TEXT_MUTED};"> {name}</span>')

    def _build_menus(self):
        bar = self.menuBar()

        self.m_file = bar.addMenu("File")
        self.act_save = QAction(self)
        self.act_save.triggered.connect(self._save_profiles_action)
        self.m_file.addAction(self.act_save)
        self.m_file.addSeparator()
        self.act_exit = QAction(self)
        self.act_exit.triggered.connect(self.close)
        self.m_file.addAction(self.act_exit)

        self.cam_menus = []
        self._cam_actions = []
        for idx in range(2):
            m_cam = bar.addMenu("Cam")
            act_set = QAction(self)
            act_set.triggered.connect(lambda _=False, i=idx: self._open_settings(i))
            act_conn = QAction(self)
            act_conn.triggered.connect(lambda _=False, i=idx: self.connect_camera(i))
            act_disc = QAction(self)
            act_disc.triggered.connect(lambda _=False, i=idx: self.disconnect_camera(i))
            m_cam.addAction(act_set)
            m_cam.addSeparator()
            m_cam.addAction(act_conn)
            m_cam.addAction(act_disc)
            self.cam_menus.append((m_cam, act_set, act_conn, act_disc))
            self._cam_actions.append((act_conn, act_disc))

        self.m_service = bar.addMenu("Service")
        self.act_discover = QAction(self)
        self.act_discover.triggered.connect(self._open_discover)
        self.act_app_settings = QAction(self)
        self.act_app_settings.triggered.connect(self._open_app_settings)
        self.act_archive = QAction(self)
        self.act_archive.triggered.connect(self._open_archive)
        self.m_service.addAction(self.act_discover)
        self.m_service.addAction(self.act_app_settings)
        self.m_service.addAction(self.act_archive)
        self.m_service.addSeparator()
        self.lang_menu = self.m_service.addMenu("Lang")
        self.act_ru = QAction("Русский", self)
        self.act_en = QAction("English", self)
        self.act_ru.setCheckable(True)
        self.act_en.setCheckable(True)
        group = QActionGroup(self)
        group.addAction(self.act_ru)
        group.addAction(self.act_en)
        self.act_ru.triggered.connect(lambda: self._switch_lang("ru"))
        self.act_en.triggered.connect(lambda: self._switch_lang("en"))
        self.lang_menu.addAction(self.act_ru)
        self.lang_menu.addAction(self.act_en)
        self._sync_lang_actions()

    def _build_shortcuts(self):
        s1 = QShortcut(QKeySequence("F1"), self)
        s1.activated.connect(lambda: self._screenshot(0))
        s2 = QShortcut(QKeySequence("F2"), self)
        s2.activated.connect(lambda: self._screenshot(1))
        s3 = QShortcut(QKeySequence("F3"), self)
        s3.activated.connect(lambda: self._center_reticle(0))
        s4 = QShortcut(QKeySequence("F4"), self)
        s4.activated.connect(lambda: self._center_reticle(1))

    # ------------------------------------------------------------- language

    def _sync_lang_actions(self):
        lang = get_lang()
        self.act_ru.setChecked(lang == "ru")
        self.act_en.setChecked(lang == "en")

    def _switch_lang(self, lang: str):
        set_lang(lang)
        self.cfg["language"] = lang
        profiles.save_profiles(self.cfg)
        self._sync_lang_actions()
        self.retranslate()

    def retranslate(self):
        self.setWindowTitle(tr("app.title"))
        self.m_file.setTitle(tr("menu.file"))
        self.m_service.setTitle(tr("menu.service"))
        self.lang_menu.setTitle(tr("menu.lang"))
        self.act_save.setText(tr("menu.save"))
        self.act_exit.setText(tr("menu.exit"))
        self.act_discover.setText(tr("menu.discover"))
        self.act_app_settings.setText(tr("menu.app_settings"))
        self.act_archive.setText(tr("menu.archive"))
        for idx, (menu, act_set, act_conn, act_disc) in enumerate(self.cam_menus):
            name = tr("app.cam1_name") if idx == 0 else tr("app.cam2_name")
            menu.setTitle(tr("menu.cam", n=idx + 1))
            act_set.setText(tr("menu.settings"))
            act_conn.setText(tr("menu.connect"))
            act_disc.setText(tr("menu.disconnect"))
            self._titles[idx].setText(tr("app.cam_title", n=idx + 1, name=name))
        for idx, btns in enumerate(self._buttons):
            shot, rec, center, zoom, sett = btns
            shot.setText(tr("btn.screenshot"))
            rec.setText(tr("btn.stop_rec") if self._is_recording(idx) else tr("btn.record"))
            center.setText(tr("btn.reticle_center"))
            zoom.setText(tr("btn.zoom_reset"))
            sett.setText(tr("btn.settings"))
        for pad in self._pads:
            pad.retranslate()
        for i, b in enumerate(getattr(self, "nav_buttons", [])):
            b.setText(tr(("nav.live", "nav.archive", "nav.editor", "nav.journal")[i]))
        self._update_cam_chips()
        self._update_record_all_button()
        self._sys_label.setText(
            f'<span style="color:{theme.ACCENT};">●</span>'
            f'&nbsp;<span style="color:{theme.TEXT_FAINT};">{tr("status.system_active")}</span>')

    # ------------------------------------------------------------ profiles

    def _save_profiles_action(self):
        self._persist()
        self.statusBar().showMessage(tr("msg.saved", path=profiles.PROFILE_PATH), 6000)

    def _persist(self):
        self.cfg["splitter"] = list(self.splitter.sizes())
        profiles.save_profiles(self.cfg)

    # ------------------------------------------------------------- archive

    def _base_dirs(self) -> dict:
        return {
            "screenshot": self.cfg.get("screenshot_dir", profiles.SCREENSHOT_DIR),
            "recording": self.cfg.get("recording_dir", profiles.RECORDING_DIR),
        }

    def _schedule_archive_sync(self):
        """Run archive sync in background; coalesce overlapping requests (C8)."""
        if SELFTEST:
            return
        if self._syncer is not None and self._syncer.isRunning():
            self._sync_pending = True
            return
        self._syncer = ArchiveSyncer(self.archive_db, self._base_dirs())
        self._syncer.done.connect(self._on_sync_done)
        self._syncer.start()
        log.info("Archive sync scheduled")

    def _on_sync_done(self):
        if self._sync_pending:
            self._sync_pending = False
            QTimer.singleShot(0, self._schedule_archive_sync)

    # ------------------------------------------------------------- connect

    def _auto_connect(self):
        for idx in range(2):
            if self.cfg["cameras"][CAM_KEYS[idx]].get("autoconnect"):
                self.connect_camera(idx, silent=True)

    def _onvif_client(self, idx) -> OnvifClient:
        client = self._onvif[idx]
        if client is not None:
            return client
        cam = self.cfg["cameras"][CAM_KEYS[idx]]
        conn = cam["connection"]
        client = OnvifClient(conn.get("host", ""), conn.get("port", 80),
                             conn.get("username", ""), conn.get("password", ""),
                             conn.get("auth", "digest"))
        self._onvif[idx] = client
        return client

    def _onvif_for_ptz(self, idx):
        try:
            return self._onvif_client(idx)
        except Exception:
            return None

    def _invalidate_onvif(self, idx):
        self._onvif[idx] = None
        self._ptz_profile[idx] = ""
        self._vstoken[idx] = ""

    def connect_camera(self, idx: int, silent: bool = False,
                       force_resolve: bool = False) -> None:
        """Connect camera. ONVIF resolution runs in background with retries."""
        cam = self.cfg["cameras"][CAM_KEYS[idx]]
        conn = cam["connection"]
        rtsp = cam["rtsp"]
        source_type = cam.get("source_type", "rtsp")
        webcam_index = cam.get("webcam_index", 0)
        self._connect_gen[idx] += 1

        if source_type == "webcam":
            self._start_worker(idx, "", silent, source_type, webcam_index)
            return

        url = (rtsp.get("url") or "").strip()
        if url and not force_resolve:
            url = ensure_credentials(url, conn.get("username", ""),
                                     conn.get("password", ""))
            self._start_worker(idx, url, silent, "rtsp", webcam_index)
            return

        # No RTSP URL yet: resolve via ONVIF in background
        if not (conn.get("host") or "").strip():
            if not silent:
                self.statusBar().showMessage(tr("msg.need_url"), 6000)
            return
        self._set_connecting(idx, True)
        self.statusBar().showMessage(tr("status.connecting"), 0)
        gen = self._connect_gen[idx]
        self._connector = CameraConnector(idx, conn, rtsp, self)
        self._connector.resolved.connect(
            lambda i, ok, u, p, v, err, g=gen, s=silent: self._on_resolved(i, ok, u, p, v, err, g, s))
        self._connector.start()

    def _set_connecting(self, idx: int, busy: bool) -> None:
        if idx < len(self._cam_actions):
            for act in self._cam_actions[idx]:
                act.setEnabled(not busy)

    def _on_resolved(self, idx: int, ok: bool, url: str, profile: str,
                     vstoken: str, error: str, gen: int, silent: bool) -> None:
        if gen != self._connect_gen[idx]:
            return  # stale result (user reconnected meanwhile)
        self._set_connecting(idx, False)
        if ok:
            log_event("SUCCESS", tr("msg.cam_connected", n=idx + 1))
        if not ok:
            if not silent:
                self.statusBar().showMessage(tr("msg.onvif_fail", err=error), 7000)
            else:
                self.statusBar().showMessage(
                    f"[{tr('app.cam1_name') if idx == 0 else tr('app.cam2_name')}] {error}", 4000)
            return
        self._ptz_profile[idx] = profile
        self._vstoken[idx] = vstoken
        rtsp = self.cfg["cameras"][CAM_KEYS[idx]]["rtsp"]
        rtsp["url"] = strip_userinfo(url)  # never persist creds (C6)
        self._start_worker(idx, url, silent, "rtsp", 0)

    def _start_worker(self, idx: int, url: str, silent: bool,
                      source_type: str, webcam_index: int) -> None:
        cam = self.cfg["cameras"][CAM_KEYS[idx]]
        rtsp = cam["rtsp"]
        self.disconnect_camera(idx)
        worker = StreamWorker(
            url, rtsp.get("transport", "tcp"), rtsp.get("low_latency", True),
            rtsp.get("record_fps", 25), source_type, webcam_index,
            on_recording_start_callback=self._schedule_archive_sync,
            on_recording_stop_callback=self._schedule_archive_sync)
        worker.message.connect(lambda m, i=idx: self._worker_message(i, m))
        try:
            worker.streamLost.disconnect()
        except Exception:
            pass
        worker.streamLost.connect(lambda rounds, i=idx: self._on_stream_lost(i, rounds))
        self.workers[idx] = worker
        self.panels[idx].set_worker(worker)
        try:
            self.panels[idx].frameOnline.disconnect()
        except Exception:
            pass
        self.panels[idx].frameOnline.connect(
            lambda online, i=idx: self._on_online(i, online))
        worker.start()
        self._persist()

    def _worker_message(self, idx: int, msg: str):
        name = tr("app.cam1_name") if idx == 0 else tr("app.cam2_name")
        self.statusBar().showMessage(f"[{name}] {msg}", 6000)

    def _on_stream_lost(self, idx: int, rounds: int):
        name = tr("app.cam1_name") if idx == 0 else tr("app.cam2_name")
        log_event("WARN", tr("msg.cam_offline", n=idx + 1))
        if rounds >= 2:
            # repeated drops: the stream URI may be stale — re-resolve via ONVIF
            log_event("INFO", tr("msg.cam_reresolve", n=idx + 1))
            self._invalidate_onvif(idx)
            QTimer.singleShot(1200, lambda i=idx: self.connect_camera(i, silent=True,
                                                                     force_resolve=True))
            return
        # first drop: quick silent reconnect with the same URL
        QTimer.singleShot(800, lambda i=idx: self.connect_camera(i, silent=True))

    def _on_online(self, idx: int, online: bool):
        self._update_cam_chips()
        self._update_record_all_button()
        if not online:
            return
        client = self._onvif[idx]
        if client is None:
            self._pads[idx].set_enabled_state(False)
            return
        # PTZ probe off the GUI thread (C2)
        old = self._probes[idx]
        if old is not None and old.isRunning():
            return
        probe = PTZProbe(idx, client, self)
        self._probes[idx] = probe
        probe.probed.connect(self._on_ptz_probed)
        probe.start()

    def _on_ptz_probed(self, idx: int, supported: bool, profile: str, vstoken: str):
        """Handles the result of the PTZ capability probe."""
        log.debug(f"PTZ probe result for cam{idx+1}: supported={supported}, profile='{profile}', vstoken='{vstoken}'")
        if profile:
            self._ptz_profile[idx] = profile
        if vstoken:
            self._vstoken[idx] = vstoken
        self._pads[idx].set_enabled_state(supported)

    def _open_app_settings(self):
        """Opens the application settings dialog."""
        from .app_settings_dialog import AppSettingsDialog  # Import here to avoid circular dependencies if any
        dlg = AppSettingsDialog(self.cfg, parent=self)
        dlg.configChanged.connect(self._on_config_changed)
        dlg.exec()

    def _on_config_changed(self, new_config: dict):
        """Handles updates from the AppSettingsDialog."""
        self.cfg.update(new_config)
        profiles.save_profiles(self.cfg)  # Persist changes
        self.retranslate()  # Update UI strings if language changed
        # Add any other necessary UI updates here based on changed settings

    def disconnect_camera(self, idx: int) -> None:
        self._connect_gen[idx] += 1
        self._set_connecting(idx, False)
        w = self.workers[idx]
        if w is not None:
            w.stop()
            if not w.wait(8000):
                # Stream read may block on a stalled connection: keep the
                # QThread referenced until it actually finishes (C3).
                log.warning("Worker cam%d did not stop in 8s; parking it", idx + 1)
                self._zombies.append(w)
                w.finished.connect(lambda z=w: self._reap_worker(z))
            self.workers[idx] = None
        self.panels[idx].set_worker(None)
        self._update_rec_button(idx)

    def _reap_worker(self, w):
        try:
            self._zombies.remove(w)
        except ValueError:
            pass
        w.deleteLater()

    # ------------------------------------------------------------ settings

    def _open_settings(self, idx: int) -> None:
        cam_key = CAM_KEYS[idx]
        cam_cfg = self.cfg["cameras"][cam_key]
        panel = self.panels[idx]
        presets = profiles.presets_for(self.cfg, cam_key)
        worker_to_pass = self.workers[idx] if idx < len(self.workers) else None
        dlg = SettingsDialog(idx, cam_cfg, panel.reticle, presets,
                             live_cb=panel.update, worker=worker_to_pass, parent=self)
        if dlg.exec():
            self._invalidate_onvif(idx)
            self._persist()
            if cam_cfg.get("autoconnect") or self.workers[idx] is not None:
                self.connect_camera(idx)
        self.retranslate()

    def _open_discover(self) -> None:
        dlg = DiscoverDialog(self)
        if dlg.exec() and dlg.selected:
            sel = dlg.selected
            target = int(sel.get("target", 0))
            cam = self.cfg["cameras"][CAM_KEYS[target]]
            cam["connection"]["host"] = sel.get("ip", "")
            port = sel.get("port") or 80
            cam["connection"]["port"] = int(port)
            self.statusBar().showMessage(
                tr("msg.transferred", n=target + 1), 6000)
            self._persist()
            self._open_settings(target)

    def _open_archive(self):
        self._switch_view(VIEW_ARCHIVE)

    # ------------------------------------------------------------- actions

    def _screenshot(self, idx: int) -> None:
        path = self.panels[idx].screenshot(self.cfg)
        if path:
            self._schedule_archive_sync()
            self.statusBar().showMessage(tr("msg.shot_saved", path=path), 6000)

    def _toggle_record(self, idx: int) -> None:
        w = self.workers[idx]
        if w is None:
            self.statusBar().showMessage(tr("msg.need_url"), 5000)
            return
        if w.is_recording():
            w.set_recording(None)
            self.statusBar().showMessage(tr("msg.rec_stopped"), 5000)
        else:
            recording_dir = self.cfg.get("recording_dir", profiles.RECORDING_DIR)
            os.makedirs(recording_dir, exist_ok=True)
            fname = f"cam{idx + 1}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            path = os.path.join(recording_dir, fname)
            style, offset = self._reticle_for(idx)
            w.set_reticle_overlay(self._reticle_in_rec, style, offset)
            if w.set_recording(path):
                log_event("SUCCESS", tr("msg.rec_started", path=os.path.basename(path)))
                self.statusBar().showMessage(tr("msg.rec_started", path=path), 6000)
            else:
                self.statusBar().showMessage(tr("msg.rec_fail"), 5000)
        self._update_rec_button(idx)

    def _update_rec_button(self, idx: int) -> None:
        self._update_record_all_button()
        btn = self.record_buttons[idx]
        btn.setText(tr("btn.stop_rec") if self._is_recording(idx) else tr("btn.record"))
        btn.setStyleSheet(
            "QPushButton { color: #ff6b6b; font-weight: 600; }"
            if self._is_recording(idx) else "")

    def _is_recording(self, idx: int) -> bool:
        w = self.workers[idx]
        return bool(w is not None and w.is_recording())

    def _center_reticle(self, idx: int) -> None:
        self.panels[idx].center_reticle()

    def _reset_zoom(self, idx: int) -> None:
        self.panels[idx].reset_zoom()

    # --------------------------------------------------------------- close

    def closeEvent(self, event) -> None:
        self._persist()
        for idx in range(2):
            self.disconnect_camera(idx)
        for pad in self._pads:
            pad.shutdown()
        if self._split_recorder is not None and self._split_recorder.isRunning():
            self._split_recorder.stop()
            self._split_recorder.wait(5000)
        if self._syncer is not None and self._syncer.isRunning():
            self._syncer.wait(3000)
        self._pool.shutdown(wait=False)
        event.accept()
