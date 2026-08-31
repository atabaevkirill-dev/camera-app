# -*- coding: utf-8 -*-
"""
Lightweight ONVIF client (SOAP over HTTP) without heavy dependencies.

Covers: device info, capabilities, media profiles, stream URI,
PTZ (continuous move, stop, home, presets) and Imaging (focus move, AF mode).
Auth: WS-UsernameToken (digest or plain).
"""

import base64
import hashlib
import os
import time
from urllib.parse import quote, urlparse, urlunparse

import requests
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


class OnvifError(Exception):
    pass


NS_DEVICE = "http://www.onvif.org/ver10/device/wsdl"
NS_MEDIA = "http://www.onvif.org/ver10/media/wsdl"
NS_MEDIA2 = "http://www.onvif.org/ver20/media/wsdl"
NS_PTZ = "http://www.onvif.org/ver20/ptz/wsdl"
NS_IMAGING = "http://www.onvif.org/ver20/imaging/wsdl"
NS_SCHEMA = "http://www.onvif.org/ver10/schema"

DEFAULT_TIMEOUT = (4, 6)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def find_first(elem: ET.Element, name: str):
    for child in elem.iter():
        if _local(child.tag) == name:
            return child
    return None


def find_all(elem: ET.Element, name: str):
    return [child for child in elem.iter() if _local(child.tag) == name]


def text_of(elem) -> str:
    if elem is None:
        return ""
    return (elem.text or "").strip()


def strip_userinfo(uri: str) -> str:
    """Remove user:pass@ from a URI (safe for storing in config)."""
    if not uri or "@" not in uri:
        return uri
    try:
        p = urlparse(uri)
        if "@" not in p.netloc:
            return uri
        hostport = p.netloc.rsplit("@", 1)[-1]
        return urlunparse((p.scheme, hostport, p.path, p.params, p.query, p.fragment))
    except Exception:
        return uri


def ensure_credentials(uri: str, username: str, password: str) -> str:
    """Add user:pass@ into a URI for the live stream (not persisted)."""
    username = username or ""
    if not username or not uri:
        return uri
    try:
        p = urlparse(uri)
        if "@" in p.netloc:
            return uri
        userinfo = quote(username, safe="") + ":" + quote(password or "", safe="")
        return urlunparse((p.scheme, f"{userinfo}@{p.netloc}", p.path,
                           p.params, p.query, p.fragment))
    except Exception:
        return uri


class OnvifClient:
    """ONVIF device client. All methods may raise OnvifError / requests exceptions."""

    def __init__(self, host: str, port: int = 80, username: str = "",
                 password: str = "", auth: str = "digest", scheme: str = "http",
                 timeout=DEFAULT_TIMEOUT):
        host = (host or "").strip()
        if not host:
            raise OnvifError("Empty host")
        if "://" in host:  # allow full host like http://1.2.3.4
            p = urlparse(host)
            scheme = p.scheme or "http"
            host = p.hostname or ""
            if p.port:
                port = p.port
        self.host = host
        self.port = int(port or 80)
        self.username = username or ""
        self.password = password or ""
        self.auth_mode = "plain" if auth == "plain" else "digest"
        self.scheme = scheme
        self.timeout = timeout
        self.device_url = f"{self.scheme}://{self.host}:{self.port}/onvif/device_service"
        self.media_url = None
        self.ptz_url = None
        self.imaging_url = None
        self._session = requests.Session()
        self._session.trust_env = False

    # ------------------------------------------------------------------ SOAP

    def _security_header(self) -> str:
        if not self.username:
            return ""
        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        nonce = os.urandom(18)
        nonce_b64 = base64.b64encode(nonce).decode("ascii")
        if self.auth_mode == "digest":
            digest = hashlib.sha1(nonce + created.encode("utf-8") + self.password.encode("utf-8")).digest()
            pwd = base64.b64encode(digest).decode("ascii")
            pwd_type = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
                        "username-token-profile-1.0#PasswordDigest")
        else:
            pwd = escape(self.password)
            pwd_type = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
                        "username-token-profile-1.0#PasswordText")
        return (
            '<s:Security s:mustUnderstand="1" '
            'xmlns:s="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
            "<s:UsernameToken>"
            f"<s:Username>{escape(self.username)}</s:Username>"
            f'<s:Password Type="{pwd_type}">{pwd}</s:Password>'
            f"<s:Nonce>{nonce_b64}</s:Nonce>"
            f"<Created xmlns=\"http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
            f"wssecurity-utility-1.0.xsd\">{created}</Created>"
            "</s:UsernameToken>"
            "</s:Security>"
        )

    def _envelope(self, service_url: str, action: str, body: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:a="http://www.w3.org/2005/08/addressing">'
            "<s:Header>"
            + self._security_header() +
            f"<a:Action>{escape(action)}</a:Action>"
            f"<a:To>{escape(service_url)}</a:To>"
            "</s:Header>"
            f"<s:Body>{body}</s:Body>"
            "</s:Envelope>"
        )

    def _call(self, service: str, action_op: str, body: str, namespace: str) -> ET.Element:
        if service == "device" or not service:
            url = self.device_url
        elif service == "media":
            url = self.media_url or f"{self.scheme}://{self.host}:{self.port}/onvif/media_service"
        elif service == "ptz":
            url = self.ptz_url or f"{self.scheme}://{self.host}:{self.port}/onvif/ptz_service"
        elif service == "imaging":
            url = self.imaging_url or f"{self.scheme}://{self.host}:{self.port}/onvif/imaging_service"
        else:
            url = self.device_url

        # ONVIF SOAP action headers are namespaced action names, not a raw
        # namespace prefix concatenated with the method name. Many cameras reject
        # the malformed variant that omitted the trailing slash.
        action = f"{namespace.rstrip('/')}/{action_op}"
        envelope = self._envelope(url, action, body)
        headers = {
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
        }
        try:
            resp = self._session.post(url, data=envelope.encode("utf-8"),
                                      headers=headers, timeout=self.timeout, verify=False)
        except requests.exceptions.Timeout:
            raise OnvifError("Timeout")
        except requests.exceptions.ConnectionError as e:
            raise OnvifError(f"Connection error: {e}")
        if resp.status_code in (401, 403):
            raise OnvifError("Authentication failed (401/403)")
        if resp.status_code >= 400:
            raise OnvifError(f"HTTP {resp.status_code}")
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            raise OnvifError(f"Bad XML response: {e}")

        fault = find_first(root, "Fault")
        if fault is not None:
            msg = text_of(find_first(fault, "faultstring"))
            if not msg:
                sub = find_first(fault, "Text")
                msg = text_of(sub) or "SOAP fault"
            raise OnvifError(msg)
        return root

    # ---------------------------------------------------------------- device

    def get_capabilities(self) -> dict:
        body = f'<GetCapabilities xmlns="{NS_DEVICE}"><Category>All</Category></GetCapabilities>'
        root = self._call("device", "GetCapabilities", body, NS_DEVICE)
        caps = {"media": False, "ptz": False, "imaging": False}
        cap_node = find_first(root, "Capabilities")
        if cap_node is None:
            return caps
        for svc, key in (("Media", "media"), ("PTZ", "ptz"), ("Imaging", "imaging")):
            node = find_first(cap_node, svc)
            if node is not None:
                caps[key] = True
                xaddr = node.attrib.get("XAddr") or ""
                if not xaddr:
                    xel = find_first(node, "XAddr")
                    xaddr = text_of(xel)
                if xaddr:
                    if key == "media":
                        self.media_url = xaddr
                    elif key == "ptz":
                        self.ptz_url = xaddr
                    else:
                        self.imaging_url = xaddr
        return caps

    def get_device_information(self) -> dict:
        body = f'<GetDeviceInformation xmlns="{NS_DEVICE}"/>'
        root = self._call("device", "GetDeviceInformation", body, NS_DEVICE)
        info = {}
        for key in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber", "HardwareId"):
            el = find_first(root, key)
            info[key] = text_of(el)
        return info

    def system_reboot(self) -> str:
        body = f'<SystemReboot xmlns="{NS_DEVICE}"/>'
        root = self._call("device", "SystemReboot", body, NS_DEVICE)
        return text_of(find_first(root, "Message"))

    # ----------------------------------------------------------------- media

    def get_profiles(self):
        last_err = None
        for ns in (NS_MEDIA, NS_MEDIA2):
            body = f'<GetProfiles xmlns="{ns}"/>'
            try:
                root = self._call("media", "GetProfiles", body, ns)
            except OnvifError as e:
                last_err = e
                continue
            profiles = []
            candidates = find_all(root, "Profiles") + find_all(root, "Profile")
            for prof in candidates:
                token = prof.attrib.get("token") or ""
                if not token:
                    continue
                name = text_of(find_first(prof, "Name"))
                profiles.append({"token": token, "name": name or token})
            if profiles:
                return profiles
        if last_err:
            raise last_err
        return []

    def get_ptz_profile_token(self) -> str:
        """Find a PTZ-capable media profile. Some cameras expose a single
        profile node named Profiles instead of Profile, and some PTZ devices only
        advertise PTZConfiguration in a subset of profiles."""
        for ns in (NS_MEDIA, NS_MEDIA2):
            body = f'<GetProfiles xmlns="{ns}"/>'
            try:
                root = self._call("media", "GetProfiles", body, ns)
            except OnvifError:
                continue
            candidates = find_all(root, "Profiles") + find_all(root, "Profile")
            for prof in candidates:
                token = prof.attrib.get("token") or ""
                if not token:
                    continue
                if find_first(prof, "PTZConfiguration") is not None:
                    return token
            for prof in candidates:
                token = prof.attrib.get("token") or ""
                if token:
                    return token
        profiles = self.get_profiles()
        if profiles:
            return profiles[0]["token"]
        raise OnvifError("No PTZ profile found")

    def get_video_source_configurations(self):
        body = f'<GetVideoSourceConfigurations xmlns="{NS_MEDIA}"/>'
        root = self._call("media", "GetVideoSourceConfigurations", body, NS_MEDIA)
        out = []
        candidates = (find_all(root, "VideoSourceConfiguration") +
                      find_all(root, "Configuration") +
                      find_all(root, "Configurations"))
        for conf in candidates:
            token = conf.attrib.get("token") or ""
            if not token:
                continue
            name = text_of(find_first(conf, "Name"))
            out.append({"token": token, "name": name or token})
        return out

    def get_stream_uri(self, profile_token: str, protocol: str = "RTSP") -> str:
        body = (
            f'<GetStreamUri xmlns="{NS_MEDIA}">'
            f'<StreamSetup xmlns="{NS_SCHEMA}">'
            f"<Stream xmlns=\"{NS_SCHEMA}\">RTP-Unicast</Stream>"
            f'<Transport xmlns="{NS_SCHEMA}">'
            f'<Protocol xmlns="{NS_SCHEMA}">RTSP</Protocol>'
            "</Transport>"
            "</StreamSetup>"
            f"<ProfileToken>{escape(profile_token)}</ProfileToken>"
            "</GetStreamUri>"
        )
        root = self._call("media", "GetStreamUri", body, NS_MEDIA)
        uri = text_of(find_first(root, "Uri"))
        if not uri:
            raise OnvifError("Empty stream URI")
        return self.inject_credentials(uri)

    def inject_credentials(self, uri: str) -> str:
        if not self.username or "@" in uri:
            return uri
        try:
            p = urlparse(uri)
            netloc = p.netloc
            if "@" in netloc:
                return uri
            hostport = netloc
            userinfo = quote(self.username, safe="") + ":" + quote(self.password, safe="")
            return urlunparse((p.scheme, f"{userinfo}@{hostport}", p.path,
                               p.params, p.query, p.fragment))
        except Exception:
            return uri

    # ------------------------------------------------------------------- PTZ

    def ptz_continuous_move(self, profile_token: str, pan: float, tilt: float, zoom: float) -> None:
        pan = max(-1.0, min(1.0, pan))
        tilt = max(-1.0, min(1.0, tilt))
        zoom = max(-1.0, min(1.0, zoom))
        body = (
            f'<ContinuousMove xmlns="{NS_PTZ}">'
            f"<ProfileToken>{escape(profile_token)}</ProfileToken>"
            f'<Velocity xmlns="{NS_SCHEMA}">'
            f'<PanTilt x="{pan:.4f}" y="{tilt:.4f}"/>'
            f'<Zoom x="{zoom:.4f}"/>'
            "</Velocity>"
            "</ContinuousMove>"
        )
        self._call("ptz", "ContinuousMove", body, NS_PTZ)

    def ptz_stop(self, profile_token: str) -> None:
        body = (
            f'<Stop xmlns="{NS_PTZ}">'
            f"<ProfileToken>{escape(profile_token)}</ProfileToken>"
            "<PanTilt>true</PanTilt><Zoom>true</Zoom>"
            "</Stop>"
        )
        self._call("ptz", "Stop", body, NS_PTZ)

    def ptz_goto_home(self, profile_token: str) -> None:
        body = f'<GotoHomePosition xmlns="{NS_PTZ}"><ProfileToken>{escape(profile_token)}</ProfileToken></GotoHomePosition>'
        self._call("ptz", "GotoHomePosition", body, NS_PTZ)

    def ptz_set_home(self, profile_token: str) -> None:
        body = f'<SetHomePosition xmlns="{NS_PTZ}"><ProfileToken>{escape(profile_token)}</ProfileToken></SetHomePosition>'
        self._call("ptz", "SetHomePosition", body, NS_PTZ)

    def ptz_set_preset(self, profile_token: str, preset_token: str, name: str = "") -> None:
        base = (
            f'<SetPreset xmlns="{NS_PTZ}">'
            f"<ProfileToken>{escape(profile_token)}</ProfileToken>"
            f"<PresetToken>{escape(preset_token)}</PresetToken>"
        )
        try:
            body = base + (f"<PresetName>{escape(name)}</PresetName>" if name else "") + "</SetPreset>"
            self._call("ptz", "SetPreset", body, NS_PTZ)
        except OnvifError:
            # Some cameras reject PresetName
            body = base + "</SetPreset>"
            self._call("ptz", "SetPreset", body, NS_PTZ)

    def ptz_goto_preset(self, profile_token: str, preset_token: str) -> None:
        body = (
            f'<GotoPreset xmlns="{NS_PTZ}">'
            f"<ProfileToken>{escape(profile_token)}</ProfileToken>"
            f"<PresetToken>{escape(preset_token)}</PresetToken>"
            "</GotoPreset>"
        )
        self._call("ptz", "GotoPreset", body, NS_PTZ)

    # --------------------------------------------------------------- imaging

    def imaging_move_focus(self, video_source_token: str, speed: float) -> None:
        speed = max(-1.0, min(1.0, speed))
        body = (
            f'<MoveFocus xmlns="{NS_IMAGING}">'
            f"<VideoSourceToken>{escape(video_source_token)}</VideoSourceToken>"
            f'<Focus xmlns="{NS_SCHEMA}">'
            f"<Continuous><Speed>{speed:.4f}</Speed></Continuous>"
            "</Focus>"
            "</MoveFocus>"
        )
        self._call("imaging", "MoveFocus", body, NS_IMAGING)

    def imaging_stop_focus(self, video_source_token: str) -> None:
        self.imaging_move_focus(video_source_token, 0.0)

    def imaging_set_focus_mode(self, video_source_token: str, auto: bool) -> None:
        mode = "AUTO" if auto else "MANUAL"
        body = (
            f'<SetImagingSettings xmlns="{NS_IMAGING}">'
            f"<VideoSourceToken>{escape(video_source_token)}</VideoSourceToken>"
            f'<ImagingSettings xmlns="{NS_SCHEMA}">'
            f"<Focus><Auto><Mode>{mode}</Mode></Auto></Focus>"
            "</ImagingSettings>"
            "</SetImagingSettings>"
        )
        self._call("imaging", "SetImagingSettings", body, NS_IMAGING)
