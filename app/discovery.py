# -*- coding: utf-8 -*-
"""ONVIF WS-Discovery auto search (UDP multicast 239.255.255.250:3702)."""

import socket
import time
import uuid
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Signal

MULTICAST_ADDR = "239.255.255.250"
MULTICAST_PORT = 3702

_PROBE_TMPL = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
    'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    "<e:Header>"
    "<d:MessageID>uuid:{uid}</d:MessageID>"
    "<d:To e:mustUnderstand=\"1\">urn:schemas-xmlsoap-org:ws:2005:04:discovery</d:To>"
    "<d:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</d:Action>"
    "</e:Header>"
    "<e:Body>"
    "<d:Probe>{types}</d:Probe>"
    "</e:Body>"
    "</e:Envelope>"
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_matches(data: bytes):
    """Return list of (xaddrs, scopes) from a ProbeMatch response."""
    import xml.etree.ElementTree as ET
    out = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return out
    for pm in [e for e in root.iter() if _local(e.tag) == "ProbeMatch"]:
        xaddrs = ""
        scopes = ""
        for child in pm:
            name = _local(child.tag)
            if name == "XAddrs":
                xaddrs = (child.text or "").strip()
            elif name == "Scopes":
                scopes = (child.text or "").strip()
        out.append((xaddrs, scopes))
    return out


def wsdiscovery_once(timeout: float, include_types: bool) -> dict:
    """One probe round. Returns {ip: {"ip", "xaddrs", "scopes"}}."""
    results = {}
    types = "<d:Types>dn:NetworkVideoTransmitter</d:Types>" if include_types else ""
    probe = _PROBE_TMPL.format(uid=f"{uuid.uuid4()}", types=types)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.5)
    try:
        sock.sendto(probe.encode("utf-8"), (MULTICAST_ADDR, MULTICAST_PORT))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            for xaddrs, scopes in _parse_matches(data):
                for xaddr in xaddrs.split():
                    try:
                        p = urlparse(xaddr)
                        ip = p.hostname or ""
                        port = p.port or 80
                    except Exception:
                        continue
                    if not ip:
                        continue
                    entry = results.get(ip)
                    if entry is None:
                        results[ip] = {"ip": ip, "port": port,
                                       "xaddrs": xaddr, "scopes": scopes}
                    else:
                        if xaddr not in entry["xaddrs"]:
                            entry["xaddrs"] += "  " + xaddr
                        if not entry.get("scopes") and scopes:
                            entry["scopes"] = scopes
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return results


def wsdiscovery(total_timeout: float = 4.0) -> list:
    """Two passes: ONVIF NetworkVideoTransmitter types, then generic."""
    merged = {}
    t1 = max(1.0, total_timeout * 0.6)
    t2 = max(1.0, total_timeout * 0.4)
    merged.update(wsdiscovery_once(t1, include_types=True))
    merged.update(wsdiscovery_once(t2, include_types=False))
    return list(merged.values())


class DiscoveryWorker(QThread):
    """Background discovery thread (does not block UI)."""

    finished = Signal(list)   # list of dicts {ip, port, xaddrs, scopes}

    def __init__(self, timeout: float = 4.0, parent=None):
        super().__init__(parent)
        self._timeout = float(timeout)

    def run(self):
        try:
            results = wsdiscovery(self._timeout)
        except Exception:
            results = []
        self.finished.emit(results)
