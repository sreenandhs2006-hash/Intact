"""M5 tests: capture-log storage rules, log analysis, attribution with a real FFmpeg video, and
(if Chrome/Edge is installed) the browser client end to end in headless mode.

The capture logs below are written by the tests to match the known videos; they test the analysis
logic. Real browser logs are exercised by test_browser_end_to_end_with_simulated_stall.
"""
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

from analysis import capture
from analysis.analyze import analyze
from client import browser_run
from client.uploader import Uploader
from tests import videos

FPS_MS = 1000 / 30


def jitter_ms(k):
    """Every 7th frame arrives 10 ms late, in the log and in the file alike. Real cameras are never
    perfectly periodic; a perfectly periodic log matches the file equally well one frame later, so the
    analysis (rightly) refuses to align it."""
    return 10 if k % 7 == 5 else 0


def make_log(n_frames=150, drop=(), start_ms=1000.0, base="capture_time", hidden=None, skip_callbacks=(),
             video_sha="0" * 64):
    """Capture log for a 30 fps source: frame k captured at start + k/30 s (+ jitter). `drop` = frames
    never delivered to the page; `skip_callbacks` = frames presented without a callback."""
    frames, presented = [], 0
    for k in range(n_frames):
        if k in drop:
            continue
        presented += 1
        if k in skip_callbacks:
            continue
        t = start_ms + k * FPS_MS + jitter_ms(k)
        rec = {"now": t + 5, "presented_frames": presented, "capture_time": None,
               "presentation_time": t + 4}
        if base == "capture_time":
            rec["capture_time"] = t
        frames.append(rec)
    vis = [{"t_ms": 0, "state": "visible"}] + (hidden or [])
    return {"log_version": 1, "video_sha256": video_sha, "source": "test", "frames": frames, "visibility": vis,
            "recorder": {"start_called_ms": start_ms - 1, "stop_called_ms": start_ms + n_frames * FPS_MS + 50}}


def file_frames(n=150, drop=()):
    return [{"pts_s": pts(k)} for k in range(n) if k not in drop]


def pts(k):
    return (k * FPS_MS + jitter_ms(k)) / 1000


def gap_anomaly(first_missing, last_missing):
    return {"type": "missing_frames", "time_start_s": pts(first_missing - 1), "time_end_s": pts(last_missing + 1),
            "estimated_missing": last_missing - first_missing + 1, "ruled_out": ["transfer"], "cause_reasoning": ""}


# ---------------- log analysis ----------------

def test_alignment_finds_the_offset_even_when_the_file_lost_frames():
    log = make_log(drop=range(40, 45))
    file_pts = [f["pts_s"] for f in file_frames(drop=range(60, 90))]   # file lost 30 other frames
    _, idx = capture.summarize_log(log)
    a = capture.align(file_pts, [t for t, _ in idx["pts"]], guess_ms=900, nominal_ms=idx["nominal"])
    assert a["reliable"] and abs(a["offset_ms"] - 1000) < 1


def test_alignment_regular_timing_is_pinned_only_by_a_shared_gap():
    # Perfectly regular 30 fps (like the canvas test source): the log runs 0.5 s past the file on both
    # sides, so one frame later matches just as well. The start-time guess is 120 ms off, as in a real
    # headless run. Without a shared gap this must stay unreliable - never decided by the guess ...
    def regular(frames, drop=()):
        return [k * FPS_MS for k in range(frames) if k not in drop]
    log_ms = [1000 + t for t in regular(330)]                      # log frames 0..329
    file_pts = [t / 1000 for t in regular(300)]                    # file = log frames 15..314
    true_offset = 1000 + 15 * FPS_MS
    a = capture.align(file_pts, log_ms, guess_ms=true_offset + 120, nominal_ms=FPS_MS)
    assert not a["reliable"] and a["gap_anchors"] == 0


def test_alignment_real_regular_run_is_pinned_by_the_shared_stall():
    # Real headless run (tests/data): frame pattern ambiguous (810 vs 809), start-time guess 121 ms off.
    # The 0.5 s stall is in both file (10.127-10.655 s) and log (10709-11239 ms): offset ~582 ms.
    fx = json.loads((Path(__file__).parent / "data" / "headless-stall-regular.json").read_text(encoding="utf-8"))
    a = capture.align(fx["file_pts_s"], fx["log_ms"], fx["guess_ms"], fx["nominal_ms"])
    assert a["frames_matched"] - a["frames_matched_next_best"] < 3          # pattern alone cannot decide
    assert a["reliable"] and a["decided_by"] == "gap edges" and a["gap_anchors"] == 1
    assert abs(a["offset_ms"] - 582) < 3


def test_alignment_real_run_with_late_file_clock_and_rounded_gap_edges():
    # Second real run: the file clock starts near the recorder's 'start' event (1.9 s after start()), and
    # presentationTime rounds the stall's edges to the display refresh, so they sit ~10 ms off the best fit.
    # The stall must still pick the frame; the fit gives the exact offset (gap edges imply 2406-2409 ms).
    fx = json.loads((Path(__file__).parent / "data" / "headless-stall-regular-2.json").read_text(encoding="utf-8"))
    rec = {"start_called_ms": fx["start_called_ms"], "started_ms": fx["started_ms"]}
    guess, center, half = capture.search_window(rec, fx["file_pts_s"], fx["log_ms"][0])
    assert center - half <= guess - 3000 and center + half >= guess + (fx["started_ms"] - fx["start_called_ms"]) + 3000
    a = capture.align(fx["file_pts_s"], fx["log_ms"], center, fx["nominal_ms"], search_ms=half)
    assert a["reliable"] and a["decided_by"] == "gap edges" and a["gap_anchors"] == 1
    assert abs(a["offset_ms"] - 2407) < fx["nominal_ms"] / 2 and a["mean_distance_ms"] < 2


def test_gap_in_file_and_log_is_capture():
    anomalies = [gap_anomaly(60, 64)]
    ce = capture.evaluate(make_log(drop=range(60, 65)), file_frames(drop=range(60, 65)), anomalies)
    a = anomalies[0]
    assert a["capture_evidence"]["verdict"] == "delivery_gap" and a["likely_cause"] == "capture"
    assert ce["delivery_gaps"][0]["estimated_missing"] == 5


def test_gap_only_in_file_is_encoding_and_rules_out_capture():
    anomalies = [gap_anomaly(60, 64)]
    capture.evaluate(make_log(), file_frames(drop=range(60, 65)), anomalies)
    a = anomalies[0]
    assert a["capture_evidence"]["verdict"] == "regular_delivery"
    assert a["capture_evidence"]["log_frames_inside_gap"] == 5
    assert a["likely_cause"] == "encoding" and "capture" in a["ruled_out"] and "transfer" in a["ruled_out"]


def test_some_frames_delivered_is_partial():
    anomalies = [gap_anomaly(60, 64)]
    capture.evaluate(make_log(drop=range(62, 65)), file_frames(drop=range(60, 65)), anomalies)
    assert anomalies[0]["capture_evidence"]["verdict"] == "partial_delivery"
    assert anomalies[0]["likely_cause"] == "encoding" and "capture" in anomalies[0]["other_candidates"]


def test_frames_presented_without_callback_are_not_a_delivery_gap():
    ce = capture.evaluate(make_log(skip_callbacks={70}), file_frames(), [])
    assert ce["callbacks_missed"] == 1 and ce["delivery_gaps"] == []


def test_hidden_page_is_not_covered():
    anomalies = [gap_anomaly(60, 64)]
    hidden = [{"t_ms": 2900, "state": "hidden"}, {"t_ms": 3300, "state": "visible"}]
    capture.evaluate(make_log(drop=range(60, 65), hidden=hidden), file_frames(drop=range(60, 65)), anomalies)
    assert anomalies[0]["capture_evidence"]["verdict"] == "not_covered"
    assert anomalies[0].get("cause_basis") is None


def test_single_frame_gap_is_too_short_for_presentation_times():
    anomalies = [gap_anomaly(59, 59)]       # neighbours 58 and 60 are on time (no late frame widens the gap)
    capture.evaluate(make_log(base="presentation_time"), file_frames(drop={59}), anomalies)
    ev = anomalies[0]["capture_evidence"]
    assert ev["verdict"] == "not_covered" and "resolution" in ev["reason"]


def test_presentation_times_cannot_judge_small_timing_irregularity():
    anomalies = [{"type": "irregular_timing", "time_start_s": 2.0, "time_end_s": 2.5, "cause_reasoning": ""}]
    capture.evaluate(make_log(base="presentation_time"), file_frames(), anomalies)
    assert anomalies[0]["capture_evidence"]["verdict"] == "not_covered"


def test_log_with_too_few_frames_is_reported_unusable():
    log = make_log(n_frames=2)
    ce = capture.evaluate(log, file_frames(), [])
    assert ce["present"] and not ce["usable"] and ce["can_prove"] and ce["cannot_prove"]


# ---------------- with a real FFmpeg video (frames 60-64 removed, 200 ms gap at 2.0 s) ----------------

@pytest.fixture(scope="module")
def gap_video(tmp_path_factory):
    return videos.make("gap", tmp_path_factory.mktemp("m5videos"))


def test_analyze_with_capture_log_attributes_the_real_gap(gap_video):
    gap = lambda r: next(a for a in r["anomalies"] if a["type"] == "missing_frames")
    without = analyze(gap_video)
    assert gap(without)["likely_cause"] == "undetermined" and not without["capture_evidence"]["present"]
    # the FFmpeg video is perfectly regular, so the log for it must be too (no late frames)
    regular_log = lambda drop=(): {**make_log(drop=drop), "frames": [
        {**f, "capture_time": 1000 + k * FPS_MS, "presentation_time": 1004 + k * FPS_MS}
        for k, f in zip([k for k in range(150) if k not in drop], make_log(drop=drop)["frames"])]}
    with_cap_gap = analyze(gap_video, capture_log=regular_log(range(60, 65)))
    assert gap(with_cap_gap)["likely_cause"] == "capture"                  # the shared gap pins the alignment
    assert with_cap_gap["capture_evidence"]["alignment"]["gap_anchors"] == 1
    assert "capture" in with_cap_gap["summary"]["dropped_frames_in_original_recording"]
    # perfectly regular log, gap only in the file: one frame later fits as well -> no verdict, not a guess
    with_regular = analyze(gap_video, capture_log=regular_log())
    assert not with_regular["capture_evidence"]["alignment"]["reliable"]
    assert gap(with_regular)["likely_cause"] == "undetermined"


# ---------------- server: capture-log endpoint ----------------

def put_log(server, uid, body, sha=None):
    return httpx.post(f"{server.url}/uploads/{uid}/capture-log", content=body,
                      headers={"X-Content-SHA256": sha or hashlib.sha256(body).hexdigest()})


def new_upload(server, data):
    sha = hashlib.sha256(data).hexdigest()
    r = httpx.post(f"{server.url}/uploads", json={"filename": "v.webm", "size": len(data), "sha256": sha})
    return r.json()["upload_id"], sha


def test_capture_log_rules(server):
    data = b"x" * 1000
    uid, sha = new_upload(server, data)
    good = json.dumps(make_log(video_sha=sha)).encode()
    assert put_log(server, uid, good, sha="0" * 64).status_code == 422                     # hash mismatch
    assert put_log(server, uid, json.dumps(make_log(video_sha="1" * 64)).encode()).status_code == 409  # other video
    assert put_log(server, uid, b"not json").status_code == 400
    r = put_log(server, uid, good)
    assert r.status_code == 201 and r.json()["duplicate"] is False
    assert put_log(server, uid, good).json()["duplicate"] is True                          # idempotent retry
    other = json.dumps({**make_log(video_sha=sha), "source": "camera"}).encode()
    assert put_log(server, uid, other).status_code == 409                                  # cannot be replaced
    events = [e["event"] for e in httpx.get(f"{server.url}/uploads/{uid}/events").json()]
    assert "CAPTURE_LOG" in events


def test_capture_log_after_finalize_is_refused(server, tmp_path):
    p = tmp_path / "v.bin"
    p.write_bytes(b"y" * 5000)
    res = Uploader(server.url, state_dir=tmp_path / "cs").upload(p)
    assert res["state"] == "COMPLETE"
    body = json.dumps(make_log(video_sha=res["client_sha256"])).encode()
    r = put_log(server, res["upload_id"], body)
    assert r.status_code == 409 and r.json()["error"] == "terminal_state"


def test_report_uses_the_stored_log(server, gap_video):
    data = gap_video.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    body = json.dumps(make_log(drop=range(60, 65), video_sha=sha)).encode()
    # same flow as the browser: chunks, then the log, then finalize
    r = httpx.post(f"{server.url}/uploads", json={"filename": "gap.mp4", "size": len(data), "sha256": sha})
    uid = r.json()["upload_id"]
    httpx.put(f"{server.url}/uploads/{uid}/chunks", params={"offset": 0}, content=data,
              headers={"X-Chunk-SHA256": sha})
    assert put_log(server, uid, body).status_code == 201
    assert httpx.post(f"{server.url}/uploads/{uid}/finalize").json()["state"] == "COMPLETE"
    deadline = time.time() + 60
    while (r := httpx.get(f"{server.url}/uploads/{uid}/report")).status_code == 202 and time.time() < deadline:
        time.sleep(0.3)
    rep = r.json()
    assert rep["capture_evidence"]["usable"]
    assert rep["transfer"]["capture_log_sha256"] == hashlib.sha256(body).hexdigest()
    assert next(a for a in rep["anomalies"] if a["type"] == "missing_frames")["likely_cause"] == "capture"


def test_capture_page_and_scripts_are_served(server):
    assert "requestVideoFrameCallback" in httpx.get(f"{server.url}/capture").text
    assert "X-Chunk-SHA256" in httpx.get(f"{server.url}/static/uploader.js").text


# ---------------- real browser (headless Chrome/Edge), skipped if none is installed ----------------

def _browser():
    try:
        return browser_run.find_browser()
    except SystemExit:
        return None


@pytest.mark.skipif(_browser() is None, reason="Chrome/Edge not installed")
def test_browser_end_to_end_with_simulated_stall(server, capsys):
    """Real MediaRecorder + requestVideoFrameCallback + JS uploader: the 0.5 s source stall at 10 s
    must be in the file and attributed to capture by the browser's own log."""
    assert browser_run.main(["--server", server.url, "--source", "test", "--stall", "--timeout", "150"]) == 0
    uid = httpx.get(f"{server.url}/uploads").json()[0]["upload_id"]
    rep = httpx.get(f"{server.url}/uploads/{uid}/report").json()
    ce = rep["capture_evidence"]
    assert rep["transfer_verified"] and ce["usable"] and ce["alignment"]["reliable"]
    # The page stops drawing at page time start() + 10 s for 0.5 s. Where that lands in the FILE depends on
    # where Chrome starts the file clock (near start() or near the recorder's 'start' event, ~2 s later), so
    # find the stall in the log and map it through the analysis's own offset.
    log = httpx.get(f"{server.url}/uploads/{uid}/capture-log").json()
    injected = log["recorder"]["start_called_ms"] + 10000
    gap = next(g for g in ce["delivery_gaps"] if abs(g["t0_ms"] - injected) < 150 and g["interval_ms"] >= 400)
    t0 = (gap["t0_ms"] - ce["alignment"]["offset_ms"]) / 1000
    near = [a for a in rep["anomalies"] if a["type"] == "missing_frames" and abs(a["time_start_s"] - t0) < 0.1]
    stall = max(near, key=lambda a: a["estimated_missing"])  # small 1-frame gaps can sit nearby
    assert stall["estimated_missing"] >= 12
    assert stall["likely_cause"] == "capture" and stall["capture_evidence"]["verdict"] == "delivery_gap"


# ---------------- real browser under faults: connection resets and a server crash mid-upload ----------------

TOXIPROXY = Path(__file__).resolve().parents[1] / "nettest" / "bin" / (
    "toxiproxy-server.exe" if os.name == "nt" else "toxiproxy-server")


@pytest.mark.skipif(_browser() is None or not TOXIPROXY.exists(), reason="needs Chrome/Edge and nettest/bin/toxiproxy")
def test_browser_upload_survives_resets_and_server_crash(make_server, tmp_path):
    """The JS uploader through Toxiproxy: upload throttled to ~250 KB/s, connections reset at ~25%,
    server killed at ~50% and restarted 5 s later. It must end COMPLETE with matching hashes."""
    from nettest.toxi import LISTEN, Toxi

    server = make_server()
    toxi_proc = subprocess.Popen([str(TOXIPROXY), "-host", "127.0.0.1", "-port", "8474"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        toxi = Toxi()
        deadline = time.time() + 10
        while toxi.version() is None and time.time() < deadline:
            time.sleep(0.2)
        toxi.create_proxy(server.url.removeprefix("http://"))
        toxi.add("slow", "bandwidth", stream="upstream", rate=250)  # KB/s, upload direction only

        result = {}
        t = threading.Thread(target=lambda: result.setdefault("rc", browser_run.main(
            ["--server", f"http://{LISTEN}", "--source", "test", "--timeout", "300"])))
        t.start()

        def wait_progress(p, timeout=120):
            end = time.time() + timeout
            while time.time() < end:
                try:
                    ups = httpx.get(f"{server.url}/uploads", timeout=2).json()
                    if ups and ups[0]["size"] and ups[0]["received_bytes"] / ups[0]["size"] >= p:
                        return ups[0]
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            raise AssertionError(f"upload never reached {p:.0%}")

        at_reset = wait_progress(0.25)
        toxi.add("rst", "reset_peer", stream="upstream", timeout=0)
        time.sleep(3)
        toxi.remove("rst")
        at_kill = wait_progress(0.5)
        server.stop()            # hard kill: simulated server crash
        time.sleep(5)
        server.start()
        t.join(320)
        assert result.get("rc") == 0
        final = httpx.get(f"{server.url}/uploads/{at_kill['upload_id']}").json()
        assert final["state"] == "COMPLETE" and final["server_sha256"] == final["sha256"]
        assert at_reset["received_bytes"] < final["size"] and at_kill["received_bytes"] < final["size"]
        events = [e["event"] for e in httpx.get(f"{server.url}/uploads/{final['upload_id']}/events").json()]
        assert "CAPTURE_LOG" in events and events[0] == "COMPLETE"  # newest first
        print(f"faults at {at_reset['received_bytes']}/{final['size']} and {at_kill['received_bytes']}/{final['size']}"
              f" bytes; duplicates {final['duplicate_chunks']}, rejected {final['rejected_chunks']}")
    finally:
        toxi_proc.kill()
        toxi_proc.wait(10)
