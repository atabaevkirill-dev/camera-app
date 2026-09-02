# -*- coding: utf-8 -*-
"""RTSP stream worker: OpenCV capture thread with reconnect + MP4 recording."""

import os
import threading
import time

from PySide6.QtCore import QThread, Signal, QTimer

from .logutil import get_logger
from .split_recorder import draw_reticle_on_frame

try:
    import cv2
    CV2_OK = True
except Exception:
    cv2 = None
    CV2_OK = False


log = get_logger("stream_worker")

STATUS_CONNECTING = "connecting"
STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_ERROR = "error"

# Serializes (env var + VideoCapture construction): OPENCV_FFMPEG_CAPTURE_OPTIONS
# is a process-global read at capture creation, so two workers reconnecting in
# parallel could otherwise apply each other's transport options (C5).
_CAPTURE_LOCK = threading.Lock()


class StreamWorker(QThread):
    """Grabs RTSP frames in background thread or webcam frames.

    Panel pulls latest frame via get_frame() on its own timer (no queue buildup).
    Recording happens inside the worker thread directly from captured frames;
    the VideoWriter is only ever created/released in this thread (C4).
    Recording lifecycle callbacks are zero-argument callables (C1).
    """

    statusChanged = Signal(str)   # STATUS_*
    message = Signal(str)         # human readable diagnostics
    streamLost = Signal(int)      # emitted when a healthy stream dropped

    def __init__(self, rtsp_url: str, transport: str = "tcp",
                 low_latency: bool = True, record_fps: int = 25,
                 source_type: str = "rtsp", webcam_index: int = 0,
                 on_recording_start_callback=None, on_recording_stop_callback=None,
                 parent=None):
        super().__init__(parent)
        self._url = rtsp_url
        self._transport = "udp" if transport == "udp" else "tcp"
        self._low_latency = bool(low_latency)
        self._record_fps = int(record_fps) if record_fps and record_fps > 0 else 25
        self._source_type = source_type
        self._webcam_index = webcam_index
        self._stop_flag = False
        self._lock = threading.Lock()
        self._frame = None          # latest BGR numpy frame
        self._seq = 0               # increments on each new frame
        self._recording = False
        self._rec_path = None
        self._writer = None
        self._rec_started_at = None
        self._overlay = None  # (style_dict, (dx, dy)) or None
        self._src_fps = 0.0
        self._cap = None
        self._on_rec_start_cb = on_recording_start_callback
        self._on_rec_stop_cb = on_recording_stop_callback
        # Timer-related attributes
        self._rec_duration_secs = 0
        self._timer = QTimer()
        self._timer.timeout.connect(self._stop_recording_by_timer)
    # ------------------------------------------------------------- interface

    def set_url(self, url: str, transport: str, low_latency: bool,
                source_type: str = "rtsp", webcam_index: int = 0) -> None:
        with self._lock:
            self._url = url
            self._transport = "udp" if transport == "udp" else "tcp"
            self._low_latency = bool(low_latency)
            self._source_type = source_type
            self._webcam_index = webcam_index

    def set_record_fps(self, fps: int) -> None:
        with self._lock:
            self._record_fps = int(fps) if fps and fps > 0 else 25

    def get_frame(self):
        """Return (seq, frame_copy) — frame is BGR numpy array or None."""
        with self._lock:
            if self._frame is None:
                return self._seq, None
            return self._seq, self._frame.copy()

    def get_source_fps(self) -> float:
        return self._src_fps

    def set_reticle_overlay(self, enabled: bool, style_dict: dict = None,
                            offset=(0.0, 0.0)) -> None:
        """Include (or not) the reticle in recorded frames."""
        with self._lock:
            self._overlay = (style_dict, (offset[0], offset[1])) if enabled else None

    def rec_elapsed(self) -> float:
        """Seconds since the writer actually opened (0 if not recording)."""
        with self._lock:
            if self._recording and self._rec_started_at:
                return time.time() - self._rec_started_at
        return 0.0

    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def set_recording(self, path, duration_secs=0) -> bool:
        """Start recording to path for duration_secs (0 means manual stop). Returns success.

        Callbacks receive no arguments (C1). The writer is released only
        inside the worker loop (C4) — here we just flip the flag.
        """
        if path is None:
            with self._lock:
                was_recording = self._recording
                self._recording = False
                self._rec_path = None
            if was_recording:
                self._timer.stop() # Остановить таймер при ручной остановке
                if self._on_rec_stop_cb is not None:
                    self._safe_cb(self._on_rec_stop_cb, "stop")
            return True
        with self._lock:
            self._rec_path = path
            self._recording = True
            self._rec_duration_secs = duration_secs # Сохраняем длительность
        if self._on_rec_start_cb is not None:
            self._safe_cb(self._on_rec_start_cb, "start")
        
        # --- Логика запуска таймера ---
        if self._rec_duration_secs > 0:
            self._timer.start(self._rec_duration_secs * 1000) # Таймер в миллисекундах
            log.info("Recording timer started for %d seconds", self._rec_duration_secs)
        else:
            self._timer.stop() # Убедиться, что таймер остановлен
        # --- /Логика запуска таймера ---
        return True

    def stop(self) -> None:
        """Stop the worker thread and clean up resources."""
        self._timer.stop()  # Stop timer when thread is stopping
        self._stop_flag = True
        cap = self._cap
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
            self._cap = None

    def _stop_recording_by_timer(self):
        """Internal slot called by QTimer to stop recording automatically."""
        log.info("Timer triggered - stopping recording")
        self.set_recording(None)  # Use main method to stop recording

    def _safe_cb(self, cb, tag: str) -> None:
        try:
            cb()
        except Exception as e:  # never let a callback kill the worker/GUI
            log.exception("recording %s callback failed", tag)
            try:
                self.message.emit(f"Archive sync error: {e}")
            except Exception:
                pass

    # ------------------------------------------------------------- internals

    def _capture_options(self) -> str:
        if self._low_latency:
            return (
                f"rtsp_transport;{self._transport}"
                "|buffer_size;512000|max_delay;400000"
                "|fflags;nobuffer|flags;low_delay"
                # stimeout is used by older FFmpeg, timeout by newer (C3)
                "|stimeout;5000000|timeout;5000000"
                "|reorder_queue_size;0"
            )
        return f"rtsp_transport;{self._transport}|stimeout;10000000|timeout;10000000"

    def _open_capture(self):
        """Create VideoCapture with per-worker FFMPEG options applied atomically."""
        with _CAPTURE_LOCK:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = self._capture_options()
            if self._source_type == "webcam":
                cap = cv2.VideoCapture(int(self._webcam_index))
            elif not self._url:
                cap = None
            else:
                cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            self._cap = cap
            return cap

    def _close_writer(self) -> None:
        """Closes the video writer safely. Worker thread only (C4)."""
        with self._lock:
            writer = self._writer
            self._writer = None
            self._rec_started_at = None
        if writer is not None:
            try:
                writer.release()
                log.info("VideoWriter released")
            except Exception as e:
                log.warning("Error releasing VideoWriter: %s", e)
                self.message.emit(f"Error closing VideoWriter: {e}")

    # cv2 in this build cannot encode H264 (avc1 silently degrades to raw
    # BGR3) — record MJPG/AVI here; the background syncer converts to
    # H.264 MP4 via ffmpeg (see app/media_convert.py).
    CODEC_CANDIDATES = [
        ("MJPG", ".avi"),
        ("XVID", ".avi"),
    ]

    def _create_writer(self, frame, path: str):
        """Try codec fallbacks; returns (writer, actual_path) or (None, path)."""
        h, w = frame.shape[:2]
        root, ext = os.path.splitext(path or "")
        for fourcc_tag, ext_needed in self.CODEC_CANDIDATES:
            target = path if ext.lower() == ext_needed else (root + ext_needed)
            try:
                writer = cv2.VideoWriter(
                    target, cv2.VideoWriter_fourcc(*fourcc_tag),
                    float(self._record_fps), (int(w), int(h)))
            except Exception as e:
                log.warning("VideoWriter(%s) raised: %s", fourcc_tag, e)
                writer = None
            if writer is not None and writer.isOpened():
                log.info("VideoWriter opened with %s -> %s", fourcc_tag, target)
                self.message.emit(f"VideoWriter: {fourcc_tag} -> {os.path.basename(target)}")
                return writer, target
            if writer is not None:
                try:
                    writer.release()
                except Exception:
                    pass
        return None, path

    def _write_frame(self, frame) -> None:
        with self._lock:
            if not self._recording:
                return
            writer = self._writer
            path = self._rec_path
            overlay = self._overlay
        if overlay:
            try:
                draw_reticle_on_frame(frame, overlay[0], overlay[1][0], overlay[1][1])
            except Exception as e:
                log.warning("reticle overlay failed: %s", e)
        if writer is None:
            writer, actual = self._create_writer(frame, path or "")
            with self._lock:
                self._writer = writer
                self._rec_path = actual
            if writer is None:
                with self._lock:
                    self._recording = False
                log.error("All VideoWriter attempts failed for %s", path)
                self.message.emit("All VideoWriter attempts failed. Recording stopped.")
                return
            with self._lock:
                self._rec_started_at = time.time()
            self.message.emit(f"Recording started: {os.path.basename(actual)}")
        try:
            writer.write(frame)
        except Exception as e:
            log.warning("Write frame error: %s", e)
            self.message.emit(f"Write frame error: {e}")

    # ------------------------------------------------------------------ run

    def run(self):
        if not CV2_OK:
            self.statusChanged.emit(STATUS_ERROR)
            self.message.emit("OpenCV (opencv-python) is not installed")
            return
        backoff = 1.0
        while not self._stop_flag:
            with self._lock:
                source_type = self._source_type
                webcam_idx = self._webcam_index
                url = self._url

            if source_type != "webcam" and not url:
                self.statusChanged.emit(STATUS_OFFLINE)
                self._sleep_ms(2000)
                continue

            self.statusChanged.emit(STATUS_CONNECTING)
            cap = self._open_capture()

            opened = False
            try:
                opened = cap is not None and cap.isOpened()
            except Exception:
                opened = False
            if not opened:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                self._cap = None
                self.statusChanged.emit(STATUS_OFFLINE)
                if source_type == "webcam":
                    self.message.emit(f"Cannot open webcam at index {webcam_idx}")
                else:
                    self.message.emit("Cannot open RTSP stream")
                self._sleep_ms(int(backoff * 1000))
                backoff = min(backoff * 1.5, 5.0)
                continue

            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            try:
                fps = cap.get(cv2.CAP_PROP_FPS)
                self._src_fps = float(fps) if 1.0 < fps < 120.0 else 0.0
            except Exception:
                self._src_fps = 0.0

            log.info("Capture online (%s)", "webcam" if source_type == "webcam" else "rtsp")
            self.statusChanged.emit(STATUS_ONLINE)
            backoff = 1.0
            rounds = 0
            fails = 0
            last_t = time.time()
            while not self._stop_flag:
                try:
                    ok, frame = cap.read()
                except Exception as e:
                    log.warning("Frame read failed: %s", e)
                    fails += 1
                    if fails > 3:
                        rounds += 1
                        self.streamLost.emit(rounds)
                        self.message.emit("Stream read error, reconnecting…")
                        break
                    self._sleep_ms(150)
                    continue
                if not ok or frame is None:
                    fails += 1
                    if fails > 25:
                        rounds += 1
                        self.streamLost.emit(rounds)
                        self.message.emit("Stream lost, reconnecting…")
                        break
                    time.sleep(0.05)
                    continue
                fails = 0
                now = time.time()
                dt = now - last_t
                last_t = now
                if dt > 0 and self._src_fps <= 0.0:
                    self._src_fps = max(1.0, min(60.0, 1.0 / dt))
                with self._lock:
                    self._frame = frame
                    self._seq += 1
                self._write_frame(frame)
                # Recording stop is honored here: the writer is released in
                # this thread only (C4).
                with self._lock:
                    idle_rec = self._recording
                    has_writer = self._writer is not None
                if not idle_rec and has_writer:
                    self._close_writer()

            self._close_writer()
            with self._lock:
                self._recording = False
            try:
                cap.release()
            except Exception:
                pass
            self._cap = None
            if not self._stop_flag:
                self.statusChanged.emit(STATUS_OFFLINE)
                self._sleep_ms(int(backoff * 1000))

        self._close_writer()
        self._cap = None

    def _sleep_ms(self, ms: int) -> None:
        end = time.time() + ms / 1000.0
        while time.time() < end and not self._stop_flag:
            time.sleep(0.05)
