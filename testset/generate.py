"""Generate a known-fault video set with FFmpeg and save the expected result for each video.

    python -m testset.generate --out ~/.nihilent-vi/testset/seed1 --seed 1

Ground truth comes from how each video is BUILT, never from the detector:
- frame faults: from the FFmpeg filter parameters (which frame indices were removed,
  repeated or re-timed),
- byte faults (flips, zeroed block, truncation): from ffprobe's packet table of the
  clean source (byte position -> packet -> presentation time).
The seed moves fault positions and sizes, so seed 1 can be used to develop and
seed 2 kept as an untouched held-out set.
"""
import argparse
import json
import os
import random
import subprocess
from pathlib import Path

from analysis.tools import binary

FPS = 30
W, H = 640, 360
SOURCES = {
    "testsrc": f"testsrc2=s={W}x{H}:r={FPS}",         # synthetic, constant motion
    "mandelbrot": f"mandelbrot=s={W}x{H}:r={FPS}",    # smooth zoom, different texture
    "flat": f"color=c=gray:s={W}x{H}:r={FPS}",        # perfectly static
    "noisy": f"color=c=gray:s={W}x{H}:r={FPS}",       # static + temporal noise (like a sensor)
}
BASE_VF = {"noisy": "noise=alls=20:allf=t"}
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", "30", "-pix_fmt", "yuv420p"]
FINE_TB = ["-enc_time_base:v", "1/15360", "-video_track_timescale", "15360"]


def ffmpeg(args):
    subprocess.run([binary("ffmpeg"), "-loglevel", "error", "-y", *args], check=True)


def encode(out, source, duration, vf=None, passthrough=False, fine_tb=False, faststart=True, rate=None):
    lavfi = SOURCES[source] if rate is None else SOURCES[source].replace(f"r={FPS}", f"r={rate}")
    filters = [f for f in (BASE_VF.get(source), vf) if f]
    args = ["-f", "lavfi", "-i", lavfi, "-t", str(duration)]
    if filters:
        args += ["-vf", ",".join(filters)]
    if passthrough:
        args += ["-fps_mode", "passthrough"]
    if fine_tb:
        args += FINE_TB
    args += ENC + (["-movflags", "+faststart"] if faststart else []) + [str(out)]
    ffmpeg(args)


def packets(path):
    out = subprocess.run([binary("ffprobe"), "-v", "error", "-select_streams", "v",
                          "-show_entries", "packet=pts_time,pos,size,flags", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return [{"t": float(p["pts_time"]), "pos": int(p["pos"]), "size": int(p["size"]), "key": "K" in p["flags"]}
            for p in json.loads(out)["packets"]]


def between(ranges):
    """FFmpeg select expression: true for frames inside any (a, b) index range."""
    return "+".join(f"between(n\\,{a}\\,{b})" for a, b in ranges)


# ---------------------------------------------------------------- recipes
# Each returns (description, expected).
# Note: FFmpeg's loop=loop=k:size=1:start=n makes output frames n..n+k-1 identical to
# frame n-1 (verified on raw, unencoded output), so the first duplicate is at n/FPS. Expected anomalies:
#   {"type", "time_s", "count"}            point event, one-to-one matching
#   {"type", "start_s", "end_s"}           range event
#   {"type": "corrupted_frame", "time_s"}  one per damaged packet (many may share a detection)

def clean(out, rng, d, source="testsrc"):
    encode(out, source, d)
    return f"clean {source}, control", {"validation": "VALID", "anomalies": [], "control": True}


def src25(out, rng, d):
    encode(out, "testsrc", d, rate=25)
    return ("25 fps source, control: 30 FPS timeline must show conversion duplicates, not anomalies",
            {"validation": "VALID", "anomalies": [], "control": True})


def gap(out, rng, d, source="testsrc", n_gaps=1):
    # split the video into n_gaps equal segments and put one gap (1-10 frames) in each
    seg = d * FPS // n_gaps
    ranges = []
    for i in range(n_gaps):
        a = rng.randint(i * seg + 30, (i + 1) * seg - 40)
        ranges.append((a, a + rng.randint(0, 9)))
    encode(out, source, d, vf=f"select='not({between(ranges)})'", passthrough=True)
    return (f"{source}: frames {ranges} removed, original timestamps kept (timestamp gap)",
            {"validation": "VALID", "anomalies": [
                {"type": "missing_frames", "time_s": (b + 1) / FPS, "count": b - a + 1} for a, b in ranges]})


def retimed(out, rng, d, source="testsrc"):
    a = rng.randint(60, d * FPS - 90)
    b = a + rng.randint(1, 4)
    encode(out, source, d, vf=f"select='not({between([(a, b)])})',setpts=N/{FPS}/TB")
    return (f"{source}: frames {a}-{b} removed and timestamps re-generated (no gap, content jump only)",
            {"validation": "VALID", "anomalies": [
                {"type": "possible_skipped_frames", "time_s": a / FPS, "count": b - a + 1}]})


def dup(out, rng, d, source="testsrc"):
    n = rng.randint(60, d * FPS - 90)
    k = rng.randint(1, 3)
    encode(out, source, d, vf=f"loop=loop={k}:size=1:start={n},setpts=N/{FPS}/TB")
    return (f"{source}: frame {n} repeated {k} extra time(s) with regular timestamps",
            {"validation": "VALID", "anomalies": [
                {"type": "duplicated_frame", "time_s": n / FPS, "count": k}]})


def mixed(out, rng, d):
    n = rng.randint(45, 90)
    k = rng.randint(1, 2)
    a = rng.randint(n + k + 60, d * FPS - 60)
    b = a + rng.randint(1, 6)
    # Timestamps are written explicitly (a select+passthrough chain after loop produced
    # stray repeated timestamps in FFmpeg 9.0.2, found by the scorer on seed 1).
    shift = b - a + 1
    encode(out, "testsrc", d, passthrough=True, fine_tb=True,
           vf=f"loop=loop={k}:size=1:start={n},settb=1/15360,select='not({between([(a, b)])})',"
              f"setpts='(N+if(gte(N\\,{a})\\,{shift}\\,0))/{FPS}/TB'")
    return (f"testsrc: frame {n} repeated {k}x, then frames {a}-{b} removed keeping timestamps",
            {"validation": "VALID", "anomalies": [
                {"type": "duplicated_frame", "time_s": n / FPS, "count": k},
                {"type": "missing_frames", "time_s": (b + 1) / FPS, "count": b - a + 1}]})


def vfr(out, rng, d):
    amp = round(rng.uniform(0.15, 0.22), 3)  # < 0.25 so no interval reaches the gap threshold
    encode(out, "testsrc", d, vf=f"settb=1/15360,setpts='(N+{amp}*sin(N*1.7))/{FPS}/TB'",
           passthrough=True, fine_tb=True)
    return (f"timestamps jittered by +-{amp} frame throughout (variable frame rate)",
            {"validation": "VALID", "anomalies": [{"type": "irregular_timing", "start_s": 0, "end_s": d}]})


def vfr_burst(out, rng, d):
    s = rng.randint(60, d * FPS - 120)
    e = s + rng.randint(30, 60)
    encode(out, "testsrc", d, passthrough=True, fine_tb=True,
           vf=f"settb=1/15360,setpts='(N+if(between(N\\,{s}\\,{e})\\,0.2*sin(N*1.7)\\,0))/{FPS}/TB'")
    return (f"timestamps jittered only for frames {s}-{e}",
            {"validation": "VALID", "anomalies": [{"type": "irregular_timing", "start_s": s / FPS, "end_s": e / FPS}]})


def _byte_fault(out, rng, d, mutate, description):
    src = out.with_name(out.stem + ".src.mp4")
    encode(src, "testsrc", d)
    pk = packets(src)
    data = bytearray(src.read_bytes())
    damaged = mutate(data, pk, rng)
    out.write_bytes(bytes(data))
    src.unlink()
    times = sorted({p["t"] for p in damaged})
    return description(damaged), {"validation": "VALID_WITH_ERRORS",
                                  "anomalies": [{"type": "corrupted_frame", "time_s": t} for t in times]}


def flipped(out, rng, d, n_packets=5):
    def mutate(data, pk, rng):
        chosen = rng.sample(pk[2:-2], n_packets)
        for p in chosen:
            off = p["pos"] + rng.randint(8, p["size"] - 5)
            for i in range(off, off + 4):  # invert 4 consecutive bytes
                data[i] ^= 0xFF
        return chosen
    return _byte_fault(out, rng, d, mutate, lambda c: f"4 bytes inverted inside {len(c)} video packets")


def zeroed(out, rng, d):
    def mutate(data, pk, rng):
        mid = pk[len(pk) // 3 + rng.randint(0, len(pk) // 3)]
        start, length = mid["pos"], 16384
        data[start:start + length] = bytes(length)
        return [p for p in pk if p["pos"] < start + length and p["pos"] + p["size"] > start]
    return _byte_fault(out, rng, d, mutate, lambda c: f"16 KiB overwritten with zeros across {len(c)} packets")


def truncated(out, rng, d):
    src = out.with_name(out.stem + ".src.mp4")
    encode(src, "testsrc", d)
    pk = packets(src)
    data = src.read_bytes()
    cut = int(len(data) * rng.uniform(0.5, 0.85))
    out.write_bytes(data[:cut])
    src.unlink()
    complete = [p for p in pk if p["pos"] + p["size"] <= cut]
    return (f"file cut to {cut} of {len(data)} bytes (faststart: header intact)",
            {"validation": "VALID_WITH_ERRORS", "anomalies": [
                {"type": "truncation", "time_s": max(p["t"] for p in complete),
                 "count": len(pk) - len(complete)}]})


def truncated_moov_end(out, rng, d):
    src = out.with_name(out.stem + ".src.mp4")
    encode(src, "testsrc", d, faststart=False)
    data = src.read_bytes()
    out.write_bytes(data[: int(len(data) * 0.8)])
    src.unlink()
    return ("file cut to 80%, index (moov) stored at the end so it is lost: unplayable",
            {"validation": "INVALID", "anomalies": []})


def fake_random(out, rng, d):
    out.write_bytes(rng.randbytes(300_000))
    return "random bytes named .mp4", {"validation": "INVALID", "anomalies": []}


def fake_text(out, rng, d):
    out.write_text("This is not a video. " * 2000)
    return "text file named .mp4", {"validation": "INVALID", "anomalies": []}


def fake_image(out, rng, d):
    png = out.with_suffix(".png")
    ffmpeg(["-f", "lavfi", "-i", SOURCES["testsrc"], "-frames:v", "1", str(png)])
    os.replace(png, out)
    return "single PNG image named .mp4", {"validation": "INVALID", "anomalies": []}


SET = [
    ("clean_testsrc", lambda o, r, d: clean(o, r, d, "testsrc")),
    ("clean_mandelbrot", lambda o, r, d: clean(o, r, d, "mandelbrot")),
    ("static_flat", lambda o, r, d: clean(o, r, d, "flat")),
    ("static_noisy", lambda o, r, d: clean(o, r, d, "noisy")),
    ("src25", src25),
    ("gap_testsrc", lambda o, r, d: gap(o, r, d, "testsrc")),
    ("gap_mandelbrot", lambda o, r, d: gap(o, r, d, "mandelbrot")),
    ("gap_multi_noisy", lambda o, r, d: gap(o, r, d, "noisy", n_gaps=3)),
    ("retimed_testsrc", lambda o, r, d: retimed(o, r, d, "testsrc")),
    ("retimed_mandelbrot", lambda o, r, d: retimed(o, r, d, "mandelbrot")),
    ("dup_testsrc", lambda o, r, d: dup(o, r, d, "testsrc")),
    ("dup_mandelbrot", lambda o, r, d: dup(o, r, d, "mandelbrot")),
    ("dup_noisy", lambda o, r, d: dup(o, r, d, "noisy")),
    ("mixed_dup_gap", mixed),
    ("vfr_jitter", vfr),
    ("vfr_burst", vfr_burst),
    ("flipped_5", lambda o, r, d: flipped(o, r, d, 5)),
    ("flipped_20", lambda o, r, d: flipped(o, r, d, 20)),
    ("zeroed_block", zeroed),
    ("truncated", truncated),
    ("truncated_moov_end", truncated_moov_end),
    ("fake_random", fake_random),
    ("fake_text", fake_text),
    ("fake_image", fake_image),
]


def generate(out_dir, seed, duration=10, only=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    # --only regenerates some videos and keeps the other entries
    manifest = [e for e in json.loads(manifest_path.read_text())
                if e["name"] not in only] if only and manifest_path.exists() else []
    for name, recipe in SET:
        if only and name not in only:
            continue
        rng = random.Random(f"{seed}:{name}")  # each video independent of the others
        path = out_dir / f"{name}.mp4"
        description, expected = recipe(path, rng, duration)
        entry = {"name": name, "file": path.name, "seed": seed, "duration_s": duration,
                 "description": description, **expected}
        (out_dir / f"{name}.expected.json").write_text(json.dumps(entry, indent=2))
        manifest.append(entry)
        print(f"{name:20} {description}")
    order = [name for name, _ in SET]
    manifest.sort(key=lambda e: order.index(e["name"]))
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--duration", type=int, default=10)
    p.add_argument("--only", nargs="*")
    args = p.parse_args(argv)
    generate(Path(args.out).expanduser(), args.seed, args.duration, args.only)


if __name__ == "__main__":
    main()
