"""Small FFmpeg-generated test videos with known properties (5 s, 320x240, 30 fps unless noted).

M3 builds the full known-fault set with expected results; these are the M2 unit fixtures.
"""
import os
import subprocess

from analysis.tools import binary

SRC = ["-f", "lavfi", "-i", "testsrc2=s=320x240:r=30", "-t", "5"]
ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30", "-movflags", "+faststart"]
FINE_TB = ["-enc_time_base:v", "1/15360", "-video_track_timescale", "15360", "-fps_mode", "passthrough"]

RECIPES = {
    "clean": SRC + ENC,
    # frames 60-64 removed, original timestamps kept -> 200 ms gap at ~2.0 s
    "gap": SRC + ["-vf", "select='not(between(n\\,60\\,64))'", "-fps_mode", "passthrough"] + ENC,
    # frames 60-62 removed and timestamps re-generated -> no gap, only a motion jump at 2.0 s
    "retimed": SRC + ["-vf", "select='not(between(n\\,60\\,62))',setpts=N/30/TB"] + ENC,
    # loop at 90: output frames 90-91 repeat frame 89 -> duplicated frames at 3.0 s
    "dup": SRC + ["-vf", "loop=loop=2:size=1:start=90,setpts=N/30/TB"] + ENC,
    # timestamps jittered by +-20% of a frame -> variable frame rate, no gaps
    "vfr": SRC + ["-vf", "settb=1/15360,setpts='(N+0.2*sin(N*1.7))/30/TB'"] + FINE_TB + ENC,
    # completely static picture -> must NOT be reported as duplicates
    "static": ["-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30", "-t", "5"] + ENC,
    # 25 fps source -> 30 fps timeline needs conversion duplicates (artefacts, not defects)
    "src25": ["-f", "lavfi", "-i", "testsrc2=s=320x240:r=25", "-t", "5"] + ENC,
}


def make(name, out_dir):
    out = out_dir / f"{name}.mp4"
    if out.exists():
        return out
    if name == "truncated":
        clean = make("clean", out_dir)
        data = clean.read_bytes()
        out.write_bytes(data[: len(data) * 6 // 10])
    elif name == "fake":
        out.write_bytes(os.urandom(200_000))
    elif name == "flipped":
        data = bytearray(make("clean", out_dir).read_bytes())
        for i in range(len(data) // 3, 2 * len(data) // 3, 997):  # deterministic byte flips mid-file
            data[i] ^= 0xFF
        out.write_bytes(bytes(data))
    else:
        subprocess.run([binary("ffmpeg"), "-loglevel", "error", "-y", *RECIPES[name], str(out)], check=True)
    return out
