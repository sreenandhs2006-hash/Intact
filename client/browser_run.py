"""Scripted run of the M5 browser client in headless Chrome/Edge.

    python -m client.browser_run --server http://127.0.0.1:8000 --source camera
    python -m client.browser_run --source test --stall --out evidence/m5/

--source camera uses Chrome's built-in fake camera (--use-fake-device-for-media-stream): a real
getUserMedia track, so the camera code path runs, but the pictures are synthetic. A real webcam run
needs a person at the page (/capture). The browser gets a fresh temporary profile.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def find_browser(explicit=None):
    for b in ([explicit] if explicit else BROWSERS):
        if b and (Path(b).exists() or shutil.which(b)):
            return b
    raise SystemExit("No Chrome/Edge found; pass --browser PATH")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--source", choices=["camera", "test"], default="camera")
    p.add_argument("--stall", action="store_true", help="test source only: 0.5 s source stall at 10 s")
    p.add_argument("--browser")
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--out", help="folder to save report JSON/HTML and the capture log")
    args = p.parse_args(argv)

    before = {u["upload_id"] for u in httpx.get(f"{args.server}/uploads").json()}
    url = f"{args.server}/capture?autostart={args.source}" + ("&stall=1" if args.stall else "")
    profile = tempfile.mkdtemp(prefix="vi-browser-")
    browser = find_browser(args.browser)
    proc = subprocess.Popen([browser, "--headless=new", "--use-fake-device-for-media-stream",
                             "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
                             "--no-first-run", f"--user-data-dir={profile}", url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"{Path(browser).name} headless -> {url}")
    upload, deadline = None, time.time() + args.timeout
    try:
        while time.time() < deadline:
            try:
                new = [u for u in httpx.get(f"{args.server}/uploads").json() if u["upload_id"] not in before]
            except httpx.HTTPError:  # server down (e.g. a restart test): keep waiting
                time.sleep(1)
                continue
            if new and new[0]["analysis"] in ("done", "failed"):
                upload = new[0]
                break
            if new and new[0]["state"] in ("REJECTED", "FAILED"):
                upload = new[0]
                break
            time.sleep(1)
    finally:
        proc.kill()
        proc.wait(10)
        shutil.rmtree(profile, ignore_errors=True)
    if not upload:
        print("TIMEOUT: no finished upload appeared")
        return 1
    uid = upload["upload_id"]
    print(f"upload {uid}: {upload['state']}, server sha256 {upload['server_sha256']}, analysis {upload['analysis']}")
    if upload["analysis"] != "done":
        return 1
    rep = httpx.get(f"{args.server}/uploads/{uid}/report").json()
    ce = rep["capture_evidence"]
    print(json.dumps(rep["summary"], indent=2))
    print(json.dumps({k: ce.get(k) for k in (
        "present", "usable", "reason", "source", "mime_type", "time_base", "coverage", "measured_fps",
        "records_in_recording", "presented_frames_in_recording", "file_frames", "callbacks_missed",
        "delivery_gaps", "anomaly_verdicts", "recording_duration_s", "log_span_s", "file_span_s",
        "simulated_faults")}, indent=2))
    for a in rep["anomalies"]:
        print(f"{a['id']} {a['type']} {a['time_start_s']}-{a['time_end_s']} cause={a['likely_cause']}"
              f" capture_log={(a.get('capture_evidence') or {}).get('verdict')}")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{uid}.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        (out / f"{uid}.html").write_text(httpx.get(f"{args.server}/uploads/{uid}/report.html").text, encoding="utf-8")
        cl = httpx.get(f"{args.server}/uploads/{uid}/capture-log")
        if cl.status_code == 200:
            (out / f"{uid}.capture-log.json").write_bytes(cl.content)
        print(f"saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
