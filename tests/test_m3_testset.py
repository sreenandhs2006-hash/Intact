"""M3 tests: the scorer's matching rules, and generator + scorer end to end on a small subset."""
import json

import pytest

from testset import generate, score


def det(id_, type_, t0, t1=None, **kw):
    return {"id": id_, "type": type_, "time_start_s": t0, "time_end_s": t1 if t1 is not None else t0, **kw}


# ---------------- matching rules (pure logic, no video) ----------------

def test_point_event_matches_within_tolerance_and_records_errors():
    expected = [{"type": "missing_frames", "time_s": 2.0, "count": 5}]
    results, used = score.match_video(expected, [det("A1", "missing_frames", 1.8, 2.1, estimated_missing=4)])
    assert results[0]["found"] and used == [True]
    assert results[0]["time_error_s"] == pytest.approx(0.1) and results[0]["count_error"] == 1


def test_wrong_type_or_too_far_is_not_a_match():
    expected = [{"type": "missing_frames", "time_s": 2.0, "count": 1}]
    dets = [det("A1", "possible_skipped_frames", 1.97, 2.0), det("A2", "missing_frames", 2.5, 2.6)]
    results, used = score.match_video(expected, dets)
    assert not results[0]["found"] and used == [False, False]


def test_point_matching_is_one_to_one():
    expected = [{"type": "duplicated_frame", "time_s": 3.0, "count": 1},
                {"type": "duplicated_frame", "time_s": 3.1, "count": 1}]
    results, used = score.match_video(expected, [det("A1", "duplicated_frame", 3.05)])
    assert sum(r["found"] for r in results) == 1 and used == [True]


def test_one_corruption_range_may_cover_several_damaged_packets():
    expected = [{"type": "corrupted_frame", "time_s": t} for t in (5.0, 5.1, 7.0)]
    results, used = score.match_video(expected, [det("A1", "corrupted_frame", 4.95, 5.4)])
    assert [r["found"] for r in results] == [True, True, False] and used == [True]


def test_range_event_matches_on_overlap():
    expected = [{"type": "irregular_timing", "start_s": 4.0, "end_s": 6.0}]
    results, used = score.match_video(expected, [det("A1", "irregular_timing", 5.5, 7.0)])
    assert results[0]["found"]


# ---------------- generator + scorer on a real subset ----------------

SUBSET = ["clean_testsrc", "static_noisy", "gap_testsrc", "dup_testsrc", "flipped_5", "fake_image"]


@pytest.fixture(scope="module")
def scored(tmp_path_factory):
    d = tmp_path_factory.mktemp("set")
    generate.generate(d, seed=11, duration=6, only=SUBSET)
    return d, score.score(d)


def test_generator_writes_expected_result_per_video(scored):
    d, _ = scored
    for name in SUBSET:
        exp = json.loads((d / f"{name}.expected.json").read_text())
        assert exp["name"] == name and "validation" in exp and "anomalies" in exp
        assert (d / exp["file"]).exists()
    assert len(json.loads((d / "manifest.json").read_text())) == len(SUBSET)


def test_byte_fault_ground_truth_comes_from_packet_table(scored):
    d, _ = scored
    exp = json.loads((d / "flipped_5.expected.json").read_text())
    assert len(exp["anomalies"]) == 5 and all(a["type"] == "corrupted_frame" for a in exp["anomalies"])


def test_subset_scores_and_controls_stay_clean(scored):
    _, s = scored
    o = s["overall"]
    assert o["validation_accuracy"] == 1.0
    assert o["false_positives_on_controls"] == 0
    assert o["recall"] >= 0.9 and o["precision"] >= 0.9
    assert s["tool_versions"]["ffmpeg"]
    md = score.to_markdown(s)
    assert "| missing_frames |" in md and "Per video" in md
