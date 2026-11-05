"""M2 tests: validation, decoding, source-timestamp analysis, 30 FPS timeline, reports."""
import json
import time

import httpx
import pytest

from analysis.analyze import analyze, write_reports
from client.uploader import Uploader
from tests import videos


@pytest.fixture(scope="session")
def video_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("videos")


_cache = {}


@pytest.fixture
def report(video_dir):
    def _get(name):
        if name not in _cache:
            _cache[name] = analyze(videos.make(name, video_dir))
        return _cache[name]
    return _get


def types(r):
    return [a["type"] for a in r["anomalies"]]


def near(t, target, tol=0.1):
    return t is not None and abs(t - target) <= tol


# ---------------- clean and false-positive controls ----------------

def test_clean_video_is_valid_with_no_anomalies(report):
    r = report("clean")
    assert r["validation"]["status"] == "VALID"
    assert r["anomalies"] == []
    assert r["validation"]["decode"]["frames_decoded"] == 150
    assert r["source_timing"]["measured_fps"] == pytest.approx(30, abs=0.01)
    tl = r["timeline_30fps"]
    assert tl["slot_count"] == 150 and tl["conversion_duplicates"] == 0 and tl["conversion_omissions"] == 0


def test_static_scene_is_not_reported_as_duplicates(report):
    r = report("static")
    assert r["anomalies"] == []
    assert r["source_timing"]["static_frames"] >= 140


def test_byte_perfect_clean_file_still_says_cannot_determine(report):
    drops = report("clean")["summary"]["dropped_frames_in_original_recording"]
    assert drops.startswith("cannot determine")


# ---------------- source defects ----------------

def test_timestamp_gap_is_located_and_counted(report):
    r = report("gap")
    gaps = [a for a in r["anomalies"] if a["type"] == "missing_frames"]
    assert len(gaps) == 1
    g = gaps[0]
    assert g["estimated_missing"] == 5 and g["confidence"] == "high"
    assert near(g["time_start_s"], 60 / 30 - 1 / 30) and near(g["time_end_s"], 65 / 30)
    assert g["likely_cause"] == "undetermined" and set(g["other_candidates"]) == {"capture", "encoding"}
    # the 30 FPS timeline fills the gap and labels those slots, not as plain conversion duplicates
    assert r["timeline_30fps"]["gap_fill_slots"] == 5
    assert r["timeline_30fps"]["conversion_duplicates"] == 0
    assert "possible_skipped_frames" not in types(r)  # content jump explained by the gap


def test_frames_removed_and_retimed_are_found_by_content_only(report):
    r = report("retimed")
    skips = [a for a in r["anomalies"] if a["type"] == "possible_skipped_frames"]
    assert len(skips) == 1 and near(skips[0]["time_end_s"], 2.0)
    assert skips[0]["confidence"] == "low"
    assert "missing_frames" not in types(r)  # timestamps are regular, as constructed


def test_duplicated_frames_are_located(report):
    r = report("dup")
    dups = [a for a in r["anomalies"] if a["type"] == "duplicated_frame"]
    # loop=...:start=90 makes frames 90 and 91 copies of frame 89 (checked on raw FFmpeg output)
    assert len(dups) == 1 and dups[0]["count"] == 2 and near(dups[0]["time_start_s"], 90 / 30, tol=0.001)


def test_variable_frame_rate_is_timing_irregularity_and_conversion_artefacts(report):
    r = report("vfr")
    assert r["source_timing"]["variable_frame_rate"] is True
    assert set(types(r)) == {"irregular_timing"}
    tl = r["timeline_30fps"]
    assert tl["conversion_duplicates"] > 0 and tl["conversion_omissions"] > 0
    assert tl["gap_fill_slots"] == 0


def test_25fps_source_conversion_duplicates_are_not_anomalies(report):
    r = report("src25")
    assert r["anomalies"] == []
    assert r["timeline_30fps"]["conversion_duplicates"] == 25  # 125 frames -> 150 slots


def test_truncated_file_is_detected(report):
    r = report("truncated")
    assert r["validation"]["status"] == "VALID_WITH_ERRORS"
    t = [a for a in r["anomalies"] if a["type"] == "truncation"]
    assert len(t) == 1 and t[0]["estimated_missing"] > 0
    assert "transfer" in t[0]["other_candidates"]  # local file: transfer not ruled out


def test_flipped_bytes_give_located_corrupted_frames(report):
    r = report("flipped")
    assert r["validation"]["status"] == "VALID_WITH_ERRORS"
    corrupt = [a for a in r["anomalies"] if a["type"] == "corrupted_frame"]
    assert corrupt and all(a["time_start_s"] is not None for a in corrupt)
    assert r["validation"]["ffmpeg_cli_decode"]["error_lines"] > 0


def test_fake_video_is_invalid(report):
    r = report("fake")
    assert r["validation"]["status"] == "INVALID"
    assert r["validation"]["decode"]["frames_decoded"] == 0
    assert r["summary"]["dropped_frames_in_original_recording"].startswith("cannot determine")


# ---------------- report contents ----------------

def test_report_has_required_sections_and_tool_versions(report, tmp_path):
    r = report("gap")
    for key in ("transfer", "validation", "source_timing", "timeline_30fps", "anomalies",
                "summary", "limitations", "tool_versions"):
        assert key in r
    for key in ("python", "os", "ffmpeg", "ffprobe", "pyav", "opencv"):
        assert r["tool_versions"][key]
    for a in r["anomalies"]:
        for key in ("evidence", "confidence", "likely_cause", "cause_reasoning", "time_start_s"):
            assert key in a
    j, h = write_reports(r, tmp_path, "gap")
    assert json.loads(j.read_text())["summary"] == r["summary"]
    assert "missing_frames" in h.read_text(encoding="utf-8")


# ---------------- server integration: analysis only after verified transfer ----------------

def test_upload_then_report_rules_out_transfer(server, video_dir, tmp_path):
    video = videos.make("gap", video_dir)
    result = Uploader(server.url, state_dir=tmp_path / "cs").upload(video)
    assert result["state"] == "COMPLETE"
    uid = result["upload_id"]
    deadline = time.time() + 60
    while (r := httpx.get(f"{server.url}/uploads/{uid}/report")).status_code == 202 and time.time() < deadline:
        time.sleep(0.3)
    assert r.status_code == 200
    rep = r.json()
    assert rep["transfer_verified"] is True and rep["transfer"]["server_sha256"] == result["client_sha256"]
    gap = next(a for a in rep["anomalies"] if a["type"] == "missing_frames")
    assert gap["ruled_out"] == ["transfer"]
    assert httpx.get(f"{server.url}/uploads/{uid}/report.html").status_code == 200


def test_analysis_refused_for_unverified_upload(server):
    data = b"x" * 1000
    import hashlib
    uid = httpx.post(f"{server.url}/uploads", json={"filename": "v.mp4", "size": 1000,
                                                     "sha256": hashlib.sha256(data).hexdigest()}).json()["upload_id"]
    assert httpx.post(f"{server.url}/uploads/{uid}/analyze").status_code == 409
    assert httpx.get(f"{server.url}/uploads/{uid}/report").status_code == 404
