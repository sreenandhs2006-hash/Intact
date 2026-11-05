"""Locate FFmpeg tools and record versions of everything that influences a result."""
import os
import platform
import shutil
import subprocess
import sys


def binary(name):
    """ffprobe/ffmpeg from VI_FFPROBE / VI_FFMPEG, else from PATH."""
    path = os.environ.get(f"VI_{name.upper()}") or shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} not found: install FFmpeg or set VI_{name.upper()}")
    return path


def _first_line(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
        return out.splitlines()[0] if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def versions():
    import av
    import cv2
    import numpy
    return {
        "python": sys.version.split()[0],
        "os": platform.platform(),
        "ffmpeg": _first_line([binary("ffmpeg"), "-version"]),
        "ffprobe": _first_line([binary("ffprobe"), "-version"]),
        "pyav": av.__version__,
        # PyAV ships its own FFmpeg libraries, which can differ from the ffmpeg CLI.
        "pyav_libavcodec": ".".join(map(str, av.library_versions.get("libavcodec", ()))),
        "pyav_libavformat": ".".join(map(str, av.library_versions.get("libavformat", ()))),
        "opencv": cv2.__version__,
        "numpy": numpy.__version__,
    }
