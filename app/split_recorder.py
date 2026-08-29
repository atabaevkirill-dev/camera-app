# -*- coding: utf-8 -*-
"""Split-screen recorder: both cameras side-by-side into one video file,
with optional reticle overlay drawn directly on frames (cv2).
"""

import time

import numpy as np

from PySide6.QtCore import QThread, Signal

from .logutil import get_logger
from .reticle import (STYLE_CROSS, STYLE_DUPLEX, STYLE_MIL_DOT, ReticleStyle)

try:
    import cv2
    CV2_OK = True
except Exception:
    cv2 = None
    CV2_OK = False

log = get_logger("split_recorder")


def _clamp(v, lo, hi, default):
    try:
        v = int(v)
    except Exception:
        return default
    return max(lo, min(hi, v))


def draw_reticle_on_frame(frame, style_dict: dict, dx: float = 0.0, dy: float = 0.0):
    """Draw the reticle (SENTINEL cross/duplex/mil-dot) onto a BGR frame."""
    if not CV2_OK or frame is None:
        return
    rs = ReticleStyle.from_dict(style_dict or {})
    h, w = frame.shape[:2]
    cx = w / 2.0 + max(-1.0, min(1.0, dx)) * w
    cy = h / 2.0 + max(-1.0, min(1.0, dy)) * h

    hex_color = (rs.color or "#00ff00").lstrip("#")
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        bgr = (b, g, r)
    except Exception:
        bgr = (0, 255, 0)

    t = _clamp(rs.thickness, 1, 12, 2)
    L = _clamp(rs.length, 10, 600, 80)
    g = _clamp(rs.gap, 0, 200, 14)
    dirs = ((0, -1), (0, 1), (-1, 0), (1, 0))

    segs, dots = [], []
    if rs.style == STYLE_DUPLEX:
        thick_w = max(1, int(round(t * _clamp(rs.thick_mult, 2, 8, 3))))
        thick_len = _clamp(rs.thick_len, 4, 400, 34)
        thin_len = max(0, L - thick_len)
        for ddx, ddy in dirs:
            x0, y0 = cx + ddx * g, cy + ddy * g
            x1, y1 = cx + ddx * (g + thin_len), cy + ddy * (g + thin_len)
            x2, y2 = cx + ddx * (g + L), cy + ddy * (g + L)
            if thin_len > 0:
                segs.append(((int(x0), int(y0)), (int(x1), int(y1)), t))
            segs.append(((int(x1), int(y1)), (int(x2), int(y2)), thick_w))
    elif rs.style == STYLE_MIL_DOT:
        dots_n = _clamp(rs.dots, 0, 10, 4)
        spacing = _clamp(rs.dot_spacing, 3, 120, 16)
        radius = _clamp(rs.dot_radius, 1, 8, 2)
        for ddx, ddy in dirs:
            segs.append(((int(cx + ddx * g), int(cy + ddy * g)),
                         (int(cx + ddx * (g + L)), int(cy + ddy * (g + L))), t))
            for i in range(1, dots_n + 1):
                d = g + i * spacing
                if d > g + L:
                    break
                dots.append((int(cx + ddx * d), int(cy + ddy * d), radius))
    else:  # cross
        for ddx, ddy in dirs:
            segs.append(((int(cx + ddx * g), int(cy + ddy * g)),
                         (int(cx + ddx * (g + L)), int(cy + ddy * (g + L))), t))

    alpha = max(0.1, min(1.0, rs.opacity / 100.0))
    overlay = frame.copy()
    if rs.outline:
        for p1, p2, wt in segs:
            cv2.line(overlay, p1, p2, (0, 0, 0), wt + 4, cv2.LINE_AA)
        for (x, y, r) in dots:
            cv2.circle(overlay, (x, y), r + 2, (0, 0, 0), -1, cv2.LINE_AA)
    for p1, p2, wt in segs:
        cv2.line(overlay, p1, p2, bgr, wt, cv2.LINE_AA)
    for (x, y, r) in dots:
        cv2.circle(overlay, (x, y), r, bgr, -1, cv2.LINE_AA)
    if rs.center_dot:
        cv2.circle(overlay, (int(cx), int(cy)), max(1, int(t * 0.8)), bgr, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


class SplitRecorder(QThread):
    """Composes both camera frames side-by-side (with separator), optional
    reticle per half, 'NO SIGNAL' placeholder for offline cameras, writes
    MJPG AVI (the sync pipeline converts it to H.264 MP4 afterwards).
    """

    stopped = Signal(str)   # output path
    failed = Signal(str)

    def __init__(self, workers: list, reticle_styles: list,
                 include_reticle: bool, out_path: str, fps: int = 25,
                 parent=None):
        super().__init__(parent)
        self._workers = workers
        self._styles = reticle_styles
        self._include_reticle = bool(include_reticle)
        self._out_path = out_path
        self._fps = int(fps) if fps and fps > 0 else 25
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def _placeholder(self, h: int, text: str = "NO SIGNAL"):
        part = np.zeros((h, int(h * 16 / 9), 3), np.uint8)
        part[:] = (16, 18, 20)
        cv2.putText(part, text, (part.shape[1] // 2 - 90, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (110, 116, 122), 2, cv2.LINE_AA)
        return part

    def run(self):
        if not CV2_OK:
            self.failed.emit("OpenCV unavailable")
            return
        writer = None
        frame_interval = 1.0 / self._fps
        next_t = time.time()
        try:
            while not self._stop_flag:
                frames = []
                for w in self._workers:
                    try:
                        frames.append(w.get_frame()[1] if w is not None else None)
                    except Exception:
                        frames.append(None)
                live = [f for f in frames if f is not None]
                if not live:
                    time.sleep(0.05)
                    continue
                h = min(f.shape[0] for f in live)
                parts = []
                for i, f in enumerate(frames):
                    if f is None:
                        part = self._placeholder(h)
                    else:
                        scale = h / f.shape[0]
                        part = cv2.resize(f, (max(2, int(f.shape[1] * scale)), h))
                    if self._include_reticle and i < len(self._styles):
                        draw_reticle_on_frame(part, self._styles[i])
                    parts.append(part)
                sep = 4
                total_w = sum(p.shape[1] for p in parts) + sep * (len(parts) - 1)
                canvas = np.zeros((h, total_w, 3), np.uint8)
                canvas[:] = (10, 12, 11)
                x = 0
                for p in parts:
                    canvas[:, x:x + p.shape[1]] = p
                    x += p.shape[1] + sep
                if writer is None:
                    writer = cv2.VideoWriter(
                        self._out_path, cv2.VideoWriter_fourcc(*"MJPG"),
                        float(self._fps), (total_w, h))
                    if not writer.isOpened():
                        log.error("Split VideoWriter failed for %s", self._out_path)
                        self.failed.emit(self._out_path)
                        return
                    log.info("Split recording started: %s", self._out_path)
                writer.write(canvas)
                # Real-time timeline: the writer fps is fixed, so keep the
                # frames-per-wallclock-second exact. If compositing ran late,
                # duplicate the frame to catch up instead of letting the clip
                # play back faster than reality.
                next_t += frame_interval
                late = time.time() - next_t
                dup = 0
                while late >= frame_interval and dup < 8:
                    writer.write(canvas)
                    next_t += frame_interval
                    late = time.time() - next_t
                    dup += 1
                if late > 1.0:  # hopelessly behind: resync the schedule
                    next_t = time.time()
                time.sleep(max(0.0, next_t - time.time()))
        except Exception as e:
            log.exception("Split recorder error: %s", e)
            self.failed.emit(str(e))
        finally:
            if writer is not None:
                try:
                    writer.release()
                except Exception:
                    pass
        log.info("Split recording stopped: %s", self._out_path)
        self.stopped.emit(self._out_path)
