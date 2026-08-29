# -*- coding: utf-8 -*-
"""H.264 conversion via real FFmpeg (OpenCV here cannot encode H264).

Priority: system ffmpeg -> imageio-ffmpeg bundled binary. All conversions
are verified (readable + avc1 tag) before the original is replaced.
"""

import os
import shutil
import subprocess

from .logutil import get_logger

log = get_logger("media_convert")

_FFMPEG = None


def _find_ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG is not None:
        return _FFMPEG
    _FFMPEG = ""
    exe = shutil.which("ffmpeg")
    if exe:
        _FFMPEG = exe
        return _FFMPEG
    try:
        import imageio_ffmpeg
        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return _FFMPEG


def ffmpeg_available() -> bool:
    return bool(_find_ffmpeg())


PLAYABLE = {"h264", "hevc"}


def probe_codec(path: str) -> str:
    """True container codec via `ffmpeg -i` stderr parsing.

    cv2's CAP_PROP_FOURCC lies in this build (reports BGR3 for everything);
    ffprobe is not bundled with imageio-ffmpeg, so parse ffmpeg itself.
    Returns lowercase codec name ('h264', 'mjpeg', ...) or ''.
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg or not os.path.exists(path):
        return ""
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                              capture_output=True, text=True, timeout=30)
        for line in proc.stderr.splitlines():
            if "Video:" in line:
                seg = line.split("Video:", 1)[1].strip()
                return seg.split(",")[0].strip().split(" ")[0].lower()
    except Exception as e:
        log.error("probe failed: %s", e)
    return ""


def is_playable(path_or_codec: str) -> bool:
    """H264/HEVC plays natively in Qt Multimedia (AVFoundation/MF)."""
    codec = probe_codec(path_or_codec) if os.path.exists(path_or_codec) else path_or_codec
    return codec in PLAYABLE


def transcode_to_h264(src_path: str, log_ctx: str = ""):
    """Re-encode to H.264 MP4 with a proper extension (verified replace).

    Returns (True, path) on success, (False, src_path) otherwise. If the
    source extension differs from .mp4 (e.g. MJPG .avi), the converted file
    is renamed to .mp4 and the original is removed.
    """
    if not os.path.exists(src_path):
        return False, src_path
    if probe_codec(src_path) in PLAYABLE:
        # already H264; only fix a misleading extension (cv2 picks the demuxer
        # by extension and fails on mp4-content-named-.avi)
        root, ext = os.path.splitext(src_path)
        if ext.lower() != ".mp4":
            dst_path = root + ".mp4"
            if os.path.exists(dst_path):
                i = 1
                while os.path.exists(f"{root}_{i}.mp4"):
                    i += 1
                dst_path = f"{root}_{i}.mp4"
            os.replace(src_path, dst_path)
            log.info("Renamed playable recording: %s -> %s",
                     os.path.basename(src_path), os.path.basename(dst_path))
            return True, dst_path
        return True, src_path
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        log.warning("ffmpeg not available; cannot convert %s", src_path)
        return False, src_path
    root, ext = os.path.splitext(src_path)
    dst_path = src_path if ext.lower() == ".mp4" else root + ".mp4"
    tmp = dst_path + ".h264tmp.mp4"
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", src_path,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        tmp,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            log.error("ffmpeg failed (%s): %s", log_ctx, proc.stderr[-400:])
            _cleanup(tmp)
            return False, src_path
    except Exception as e:
        log.error("ffmpeg error (%s): %s", log_ctx, e)
        _cleanup(tmp)
        return False, src_path
    if not os.path.exists(tmp) or os.path.getsize(tmp) < 1024:
        _cleanup(tmp)
        return False, src_path
    if probe_codec(tmp) not in PLAYABLE:
        log.error("ffmpeg produced non-H264 output (%s)", log_ctx)
        _cleanup(tmp)
        return False, src_path
    if dst_path != src_path and os.path.exists(dst_path):
        # never clobber an existing target: pick a unique name
        i = 1
        while os.path.exists(f"{root}_{i}.mp4"):
            i += 1
        dst_path = f"{root}_{i}.mp4"
        os.replace(tmp, dst_path)
    else:
        os.replace(tmp, dst_path)
    if dst_path != src_path:
        try:
            os.remove(src_path)
        except OSError:
            pass
        log.info("Converted + renamed: %s -> %s", os.path.basename(src_path),
                 os.path.basename(dst_path))
    else:
        log.info("Converted to H264: %s %s", os.path.basename(src_path), log_ctx)
    return True, dst_path


def _cleanup(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
