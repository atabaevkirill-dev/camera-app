# -*- coding: utf-8 -*-
"""Per-camera settings dialog: ONVIF connection, RTSP stream, reticle editor."""

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget, QTabWidget)

from .i18n import tr
from .onvif_client import OnvifClient, OnvifError, strip_userinfo
from .reticle import ReticleStyle
from .reticle_editor import ReticleEditor


class SettingsDialog(QDialog):
    """Edits camera config dict in place; reticle edited via shared object."""

    def __init__(self, cam_index: int, cam_cfg: dict, reticle: ReticleStyle,
                 presets: dict, live_cb=None, worker=None, parent=None): # Added worker
        super().__init__(parent)
        self.cam_index = cam_index
        self.cfg = cam_cfg
        self.rs = reticle
        self.live_cb = live_cb
        self.worker = worker # Store worker reference
        self._backup = copy.deepcopy(reticle.to_dict())
        self._client = None
        self._profiles = []

        conn = cam_cfg.setdefault("connection", {})
        rtsp = cam_cfg.setdefault("rtsp", {})
        pelco = cam_cfg.setdefault("pelco_d", {"enabled": False, "ip": "", "port": 9761, "address": 1})
        source_type = cam_cfg.setdefault("source_type", "rtsp")
        webcam_index = cam_cfg.setdefault("webcam_index", 0)

        self.setWindowTitle(tr("dlg.title", n=cam_index + 1))
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)

        # Create tab widget
        tab_widget = QTabWidget()
        self.tab_widget = tab_widget # Store reference for retranslate

        # --- Connection Tab ---
        conn_tab = QWidget()
        conn_layout = QVBoxLayout(conn_tab)

        # Source type selection
        source_row = QHBoxLayout()
        self.source_type_label = QLabel(tr("source.type"))
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItem(tr("source.rtsp"), "rtsp")
        self.source_type_combo.addItem(tr("source.webcam"), "webcam")
        source_cur = str(source_type)
        self.source_type_combo.setCurrentIndex(1 if source_cur == "webcam" else 0)
        self.source_type_combo.currentTextChanged.connect(self._on_source_type_changed)
        source_row.addWidget(self.source_type_label)
        source_row.addWidget(self.source_type_combo)
        source_row.addStretch(1)
        conn_layout.addLayout(source_row)

        # Webcam index (initially hidden)
        self.webcam_group = QGroupBox(tr("webcam.group"))
        self.webcam_group.setVisible(source_type == "webcam")
        wform = QFormLayout(self.webcam_group)
        self.webcam_index_spin = QSpinBox()
        self.webcam_index_spin.setRange(0, 10) # Adjust range as needed
        self.webcam_index_spin.setValue(int(webcam_index))
        wform.addRow(tr("webcam.index"), self.webcam_index_spin)
        conn_layout.addWidget(self.webcam_group)

        # ONVIF connection group
        conn_group = QGroupBox(tr("conn.group"))
        # Make it initially visible only if source is rtsp
        conn_group.setVisible(source_type == "rtsp")
        self.conn_group = conn_group
        form = QFormLayout(conn_group)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.host_edit = QLineEdit(str(conn.get("host", "")))
        self.host_edit.setPlaceholderText("192.168.1.10")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(conn.get("port", 80) or 80))
        self.user_edit = QLineEdit(str(conn.get("username", "")))
        self.pass_edit = QLineEdit(str(conn.get("password", "")))
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.auth_combo = QComboBox()
        self.auth_combo.addItem(tr("conn.digest"), "digest")
        self.auth_combo.addItem(tr("conn.plain"), "plain")
        auth_cur = str(conn.get("auth", "digest"))
        self.auth_combo.setCurrentIndex(1 if auth_cur == "plain" else 0)

        form.addRow(tr("conn.host"), self.host_edit)
        form.addRow(tr("conn.port"), self.port_spin)
        form.addRow(tr("conn.user"), self.user_edit)
        form.addRow(tr("conn.pass"), self.pass_edit)
        form.addRow(tr("conn.auth"), self.auth_combo)

        self.pelco_group = QGroupBox(tr("pelco.group"))
        self.pelco_group.setCheckable(True)
        self.pelco_group.setChecked(bool(pelco.get("enabled", False)))
        pform = QFormLayout(self.pelco_group)
        self.pelco_ip_edit = QLineEdit(str(pelco.get("ip", "")))
        self.pelco_ip_edit.setPlaceholderText("192.168.1.115")
        self.pelco_port_spin = QSpinBox()
        self.pelco_port_spin.setRange(1, 65535)
        self.pelco_port_spin.setValue(int(pelco.get("port", 9761) or 9761))
        self.pelco_addr_spin = QSpinBox()
        self.pelco_addr_spin.setRange(1, 255)
        self.pelco_addr_spin.setValue(int(pelco.get("address", 1) or 1))
        pform.addRow(tr("pelco.ip"), self.pelco_ip_edit)
        pform.addRow(tr("pelco.port"), self.pelco_port_spin)
        pform.addRow(tr("pelco.address"), self.pelco_addr_spin)
        self.pelco_group.toggled.connect(self._sync_pelco_edit_state)
        self._sync_pelco_edit_state(self.pelco_group.isChecked())
        conn_layout.addWidget(self.pelco_group)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton(tr("conn.test"))
        self.test_btn.clicked.connect(self._test_connection)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        form.addRow(test_row)
        conn_layout.addWidget(conn_group)

        tab_widget.addTab(conn_tab, tr("tab.connection")) # Assuming translation key for "Connection"

        # --- RTSP Tab ---
        rtsp_tab = QWidget()
        rtsp_layout = QVBoxLayout(rtsp_tab)

        # RTSP group
        rtsp_group = QGroupBox(tr("rtsp.group"))
        self.rtsp_group = rtsp_group
        rform = QFormLayout(rtsp_group)
        rform.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.url_edit = QLineEdit(strip_userinfo(str(rtsp.get("url", ""))))
        self.url_edit.setPlaceholderText(tr("rtsp.url_ph"))
        rform.addRow(tr("rtsp.url"), self.url_edit)

        get_row = QHBoxLayout()
        self.get_uri_btn = QPushButton(tr("rtsp.get"))
        self.get_uri_btn.clicked.connect(self._get_uri_from_onvif)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(140)
        get_row.addWidget(self.get_uri_btn)
        get_row.addWidget(self.profile_combo, 1)
        rform.addRow("", get_row)

        self.transport_combo = QComboBox()
        self.transport_combo.addItem("TCP", "tcp")
        self.transport_combo.addItem("UDP", "udp")
        tr_cur = str(rtsp.get("transport", "tcp"))
        self.transport_combo.setCurrentIndex(1 if tr_cur == "udp" else 0)
        rform.addRow(tr("rtsp.transport"), self.transport_combo)

        self.lowlat_check = QCheckBox(tr("rtsp.lowlat"))
        self.lowlat_check.setChecked(bool(rtsp.get("low_latency", True)))
        rform.addRow("", self.lowlat_check)

        self.recfps_spin = QSpinBox()
        self.recfps_spin.setRange(1, 60)
        self.recfps_spin.setValue(int(rtsp.get("record_fps", 25) or 25))
        rform.addRow(tr("rtsp.recfps"), self.recfps_spin)
        rtsp_layout.addWidget(rtsp_group)

        tab_widget.addTab(rtsp_tab, tr("tab.rtsp")) # Assuming translation key for "RTSP"

        # --- Reticle Tab ---
        ret_tab = QWidget()
        ret_layout = QVBoxLayout(ret_tab)

        # Reticle group
        ret_group = QGroupBox(tr("ret.group"))
        self.ret_group = ret_group
        rlay = QVBoxLayout(ret_group)
        self.ret_editor = ReticleEditor(self.rs, presets)
        self.ret_editor.changed.connect(self._reticle_changed)
        rlay.addWidget(self.ret_editor)
        ret_layout.addWidget(ret_group)

        self.auto_check = QCheckBox(tr("conn.auto"))
        self.auto_check.setChecked(bool(cam_cfg.get("autoconnect", False)))
        ret_layout.addWidget(self.auto_check)

        tab_widget.addTab(ret_tab, tr("tab.reticle")) # Assuming translation key for "Reticle"

        # Add tabs to main layout
        root.addWidget(tab_widget)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setText(tr("btn.ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("btn.cancel"))
        self._btn_ok = buttons.button(QDialogButtonBox.Ok)
        self._btn_cancel = buttons.button(QDialogButtonBox.Cancel)
        root.addWidget(buttons)

        self._retranslate()
        self._collect_back()

    # ------------------------------------------------------------ retranslate

    def _retranslate(self):
        self.conn_group.setTitle(tr("conn.group"))
        self.pelco_group.setTitle(tr("pelco.group"))
        self.rtsp_group.setTitle(tr("rtsp.group"))
        self.ret_group.setTitle(tr("ret.group"))
        self.webcam_group.setTitle(tr("webcam.group")) # Add translation key
        self.source_type_label.setText(tr("source.type")) # Add translation key
        self._btn_ok.setText(tr("btn.ok"))
        self._btn_cancel.setText(tr("btn.cancel"))
        # Update tab titles
        self.tab_widget.setTabText(0, tr("tab.connection"))
        self.tab_widget.setTabText(1, tr("tab.rtsp"))
        self.tab_widget.setTabText(2, tr("tab.reticle"))

    def _reticle_changed(self):
        if self.live_cb:
            try:
                self.live_cb()
            except Exception:
                pass

    def _sync_pelco_edit_state(self, checked: bool):
        # Keep Pelco-D fields editable even while the group is unchecked; the
        # checkbox still controls whether Pelco-D is used as the PTZ backend.
        self.pelco_ip_edit.setEnabled(True)
        self.pelco_port_spin.setEnabled(True)
        self.pelco_addr_spin.setEnabled(True)

    # ------------------------------------------------------------- internals

    def _collect_back(self) -> None:
        """Push widget values into cfg (without saving profiles)."""
        conn = self.cfg["connection"]
        conn["host"] = self.host_edit.text().strip()
        conn["port"] = self.port_spin.value()
        conn["username"] = self.user_edit.text().strip()
        conn["password"] = self.pass_edit.text()
        conn["auth"] = self.auth_combo.currentData()
        pelco = self.cfg.setdefault("pelco_d", {"enabled": False, "ip": "", "port": 9761, "address": 1})
        pelco["enabled"] = self.pelco_group.isChecked()
        pelco["ip"] = self.pelco_ip_edit.text().strip()
        pelco["port"] = self.pelco_port_spin.value()
        pelco["address"] = self.pelco_addr_spin.value()
        rtsp = self.cfg["rtsp"]
        rtsp["url"] = strip_userinfo(self.url_edit.text().strip())
        rtsp["transport"] = self.transport_combo.currentData()
        rtsp["low_latency"] = self.lowlat_check.isChecked()
        rtsp["record_fps"] = self.recfps_spin.value()
        self.cfg["autoconnect"] = self.auto_check.isChecked()
        # Add source type and webcam index
        self.cfg["source_type"] = self.source_type_combo.currentData()
        self.cfg["webcam_index"] = self.webcam_index_spin.value()

    def _make_client(self) -> OnvifClient:
        self._collect_back()
        conn = self.cfg["connection"]
        return OnvifClient(conn.get("host", ""), conn.get("port", 80),
                           conn.get("username", ""), conn.get("password", ""),
                           conn.get("auth", "digest"))

    def _test_connection(self):
        try:
            self.test_btn.setEnabled(False)
            client = self._make_client()
            info = client.get_device_information()
            self._client = client
            self.test_result.setStyleSheet("color: #79c779;")
            self.test_result.setText(tr("conn.test_ok",
                                        mfr=info.get("Manufacturer", "?"),
                                        model=info.get("Model", "?"),
                                        fw=info.get("FirmwareVersion", "?")))
        except Exception as e:
            self.test_result.setStyleSheet("color: #e07a7a;")
            self.test_result.setText(tr("conn.test_fail", err=str(e)))
        finally:
            self.test_btn.setEnabled(True)

    def _get_uri_from_onvif(self):
        try:
            client = self._client or self._make_client()
            try:
                client.get_capabilities()
            except OnvifError:
                pass
            profiles = client.get_profiles()
            if not profiles:
                raise OnvifError("No media profiles")
            self._client = client
            self._profiles = profiles
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            for i, p in enumerate(profiles):
                self.profile_combo.addItem(p.get("name") or p["token"], i)
            self.profile_combo.blockSignals(False)
            self.profile_combo.currentIndexChanged.connect(self._fill_uri)
            self._fill_uri()
        except Exception as e:
            self.test_result.setStyleSheet("color: #e07a7a;")
            self.test_result.setText(tr("conn.test_fail", err=str(e)))

    def _fill_uri(self):
        if not self._client or not self._profiles:
            return
        idx = self.profile_combo.currentIndex()
        if idx < 0 or idx >= len(self._profiles):
            idx = 0
        try:
            token = self._profiles[idx]["token"]
            uri = self._client.get_stream_uri(token)
            self.url_edit.setText(uri)
        except Exception as e:
            self.test_result.setStyleSheet("color: #e07a7a;")
            self.test_result.setText(tr("conn.test_fail", err=str(e)))

    def _on_source_type_changed(self, text):
        is_webcam = self.source_type_combo.currentData() == "webcam"
        self.conn_group.setVisible(not is_webcam)
        self.rtsp_group.setVisible(not is_webcam)
        self.webcam_group.setVisible(is_webcam)

    # ---------------------------------------------------------------- result

    def accept(self):
        self._collect_back()
        # Update worker parameters if available
        if self.worker:
            rtsp = self.cfg["rtsp"]
            source_type = self.cfg.get("source_type", "rtsp")
            webcam_index = self.cfg.get("webcam_index", 0)
            self.worker.set_url(rtsp.get("url", ""), rtsp.get("transport", "tcp"), rtsp.get("low_latency", True), source_type, webcam_index)
            self.worker.set_record_fps(rtsp.get("record_fps", 25))

        super().accept()

    def reject(self):
        # restore reticle edits
        self.rs.apply(ReticleStyle.from_dict(self._backup))
        if self.live_cb:
            try:
                self.live_cb()
            except Exception:
                pass
        super().reject()