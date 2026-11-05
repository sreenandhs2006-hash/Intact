"""Container/stream validation with ffprobe, plus an independent full decode with the ffmpeg CLI.

Two different decoders (ffmpeg CLI here, PyAV in decode.py) give corroborating evidence:
an error both report is stronger than an error only one reports.
"""
import json
import subprocess
from fractions import Fraction

from .tools import binary


def _rate(s):
    try:
        r = Fraction(s)
        return float(r) if r > 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def _num(v, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def ffprobe(path):
    """Return {ok, errors, format, video} describing the container and first video stream."""
    proc = subprocess.run(
        [binary("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=120)
    errors = [line for line in proc.stderr.splitlines() if line.strip()]
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    out = {
        "ok": proc.returncode == 0 and bool(videos),
        "returncode": proc.returncode,
        "errors": errors,
        "format": {
            "format_name": fmt.get("format_name"),
            "duration_s": _num(fmt.get("duration")),
            "size_bytes": _num(fmt.get("size"), int),
            "bit_rate": _num(fmt.get("bit_rate"), int),
            "nb_streams": fmt.get("nb_streams"),
        } if fmt else None,
        "stream_types": [s.get("codec_type") for s in streams],
        "video": None,
    }
    if videos:
        v = videos[0]
        out["video"] = {
            "index": v.get("index"),
            "codec": v.get("codec_name"),
            "profile": v.get("profile"),
            "width": v.get("width"),
            "height": v.get("height"),
            "pix_fmt": v.get("pix_fmt"),
            "time_base": v.get("time_base"),
            "r_frame_rate": _rate(v.get("r_frame_rate")),
            "avg_frame_rate": _rate(v.get("avg_frame_rate")),
            "declared_frames": _num(v.get("nb_frames"), int),
            "declared_duration_s": _num(v.get("duration")),
            "start_time_s": _num(v.get("start_time")),
            "has_b_frames": v.get("has_b_frames"),
        }
    elif proc.returncode == 0:
        out["errors"].append("no video stream found")
    return out


def ffmpeg_decode_check(path, max_lines=200):
    """Decode every video frame with the ffmpeg CLI and return its error output."""
    proc = subprocess.run(
        [binary("ffmpeg"), "-v", "error", "-nostdin", "-i", str(path),
         "-map", "0:v:0", "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    lines = [l for l in proc.stderr.splitlines() if l.strip()]
    return {"returncode": proc.returncode, "error_lines": len(lines), "errors": lines[:max_lines]}
