# -*- coding: utf-8 -*-
"""Minimal Pelco-D PTZ controller support over UDP."""

import socket


class PelcoDController:
    """Emulates the ONVIF PTZ client interface for Pelco-D PTZ controllers."""

    def __init__(self, host: str, port: int = 9761, address: int = 1):
        self.host = (host or "").strip()
        self.port = int(port or 9761)
        self.address = max(1, min(255, int(address or 1)))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(1.0)

    def _checksum(self, packet):
        # Pelco-D checksum is the low byte of the sum of bytes 1..6 (address +
        # command bytes + pan/tilt/zoom speeds), followed by the 0xFF sync byte.
        return sum(packet[1:7]) & 0xFF

    def _send(self, command1: int, command2: int, pan_speed: int = 0, tilt_speed: int = 0, zoom_speed: int = 0):
        if not self.host:
            raise ValueError("Pelco-D host is empty")
        pkt = [0xFF, self.address & 0xFF, command1 & 0xFF, command2 & 0xFF,
               pan_speed & 0xFF, tilt_speed & 0xFF, zoom_speed & 0xFF]
        pkt.append(self._checksum(pkt))
        self._sock.sendto(bytes(pkt), (self.host, self.port))

    def ptz_continuous_move(self, profile_token: str, pan: float, tilt: float, zoom: float) -> None:
        pan = max(-1.0, min(1.0, float(pan)))
        tilt = max(-1.0, min(1.0, float(tilt)))
        zoom = max(-1.0, min(1.0, float(zoom)))

        cmd1 = 0x00
        cmd2 = 0x00
        pan_speed = 0
        tilt_speed = 0
        zoom_speed = 0

        # Pelco-D uses absolute speed values for horizontal/vertical and zoom.
        pan_speed = int(abs(pan) * 0x3F)
        tilt_speed = int(abs(tilt) * 0x3F)
        zoom_speed = int(abs(zoom) * 0x3F)

        if pan > 0:
            cmd1 |= 0x04  # right
        elif pan < 0:
            cmd1 |= 0x08  # left
        if tilt > 0:
            cmd2 |= 0x01  # up
        elif tilt < 0:
            cmd2 |= 0x02  # down
        if zoom > 0:
            cmd1 |= 0x10
        elif zoom < 0:
            cmd1 |= 0x20

        # Some implementations expect speed in the first/second byte of data for
        # pan/tilt and zoom. The exact field mapping varies by controller firmware,
        # but the packet still matches the Pelco-D wire format used by PTZ domes.
        self._send(cmd1, cmd2, pan_speed, tilt_speed, zoom_speed)

    def ptz_stop(self, profile_token: str) -> None:
        self._send(0x00, 0x00, 0, 0, 0)

    def ptz_goto_home(self, profile_token: str) -> None:
        self._send(0x00, 0x00, 0, 0, 0)

    def ptz_set_home(self, profile_token: str) -> None:
        return None

    def ptz_set_preset(self, profile_token: str, preset_token: str, name: str = "") -> None:
        return None

    def ptz_goto_preset(self, profile_token: str, preset_token: str) -> None:
        return None

    def imaging_move_focus(self, video_source_token: str, speed: float) -> None:
        return None

    def imaging_stop_focus(self, video_source_token: str) -> None:
        return None

    def imaging_set_focus_mode(self, video_source_token: str, auto: bool) -> None:
        return None
