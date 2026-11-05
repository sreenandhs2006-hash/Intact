"""M4 tests that need no root and no Linux: profiles, lab commands (dry run), scenarios, metrics.

The real network behaviour is verified by `nettest.run preflight` on Linux (measured RTT and
rate) and by the runs themselves; these tests check the harness logic.
"""
import json

import pytest

from nettest import metrics
from nettest.netlab import NetLab
from nettest.profiles import PROFILES
from nettest.scenarios import SCENARIOS

KNOWN_ACTIONS = {"profile", "wait", "disable", "enable", "toxic", "untoxic",
                 "kill_client", "start_client", "kill_server", "start_server"}


# ---------------- profiles = my definition of network strength ----------------

def test_profiles_match_the_stated_definition():
    assert [(p.rate_kbit, p.rtt_ms, p.loss_pct) for p in (PROFILES["100"], PROFILES["60"], PROFILES["20"])] == \
        [(20_000, 20, 0), (5_000, 80, 1), (500, 400, 5)]


def test_netem_arguments_split_rtt_and_limit_upload_rate():
    p = PROFILES["20"]
    up, down = p.netem_upload(), p.netem_download()
    assert up[:6] == ["delay", "200ms", "rate", "500kbit", "loss", "5%"]
    assert down[:4] == ["delay", "200ms", "loss", "5%"] and "rate" not in down


def test_queue_limit_is_about_one_second_of_traffic():
    assert PROFILES["100"].queue_limit() == int(20_000_000 / 8 / 1500 * 1.01)  # ~1683 packets
    assert PROFILES["20"].queue_limit() == 64                                   # floor for slow links


# ---------------- lab commands (dry run) ----------------

def test_lab_builds_namespace_veth_and_netem_on_both_ends():
    lab = NetLab(dry_run=True)
    lab.up()
    lab.set_profile(PROFILES["60"])
    cmds = [" ".join(c) for c in lab.commands]
    assert "ip netns add vi-srv" in cmds
    assert "ip link add vi-cli type veth peer name vi-srv0" in cmds
    assert any(c.startswith("tc qdisc replace dev vi-cli root netem delay 40ms rate 5000kbit loss 1%") for c in cmds)
    assert any(c.startswith("ip netns exec vi-srv tc qdisc replace dev vi-srv0 root netem delay 40ms loss 1%")
               for c in cmds)
    assert any("gso off" in c for c in cmds)  # offloads off, so netem sees real packets


# ---------------- scenarios ----------------

@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenarios_are_well_formed(name):
    sc = SCENARIOS[name]
    assert sc["base"] in PROFILES and sc["description"]
    ats = [at for at, _ in sc["steps"]]
    assert ats == sorted(ats) and all(0 < a < 1 for a in ats)
    for _, actions in sc["steps"]:
        for a in actions:
            assert a[0] in KNOWN_ACTIONS
            if a[0] == "profile":
                assert a[1] in PROFILES


def test_brief_scenarios_are_all_covered():
    assert {"stable_100", "stable_60", "stable_20", "fluctuating", "interruption", "network_switch",
            "resets", "timeouts", "client_restart", "server_restart"} <= set(SCENARIOS)


def test_hang_is_longer_than_client_stall_timeout():
    waits = [a[1] for _, acts in SCENARIOS["timeouts"]["steps"] for a in acts if a[0] == "wait"]
    assert min(waits) > 20  # client default stall timeout


# ---------------- metrics from client logs ----------------

def ev(t, event, **kw):
    return {"t": t, "event": event, **kw}


KILLED_AND_RESUMED = [
    ev(0, "start", size=1000, sha256="abc"), ev(0.1, "created", upload_id="u1", size=1000, sha256="abc"),
    ev(1, "chunk_ok", offset=0, length=300, duplicate=False),
    ev(2, "retry", what="chunk", attempt=1),
    ev(3, "chunk_ok", offset=300, length=200, duplicate=True),
    # client killed here; a new process starts and resumes
    ev(10, "start", size=1000, sha256="abc"), ev(10.5, "resume", upload_id="u1", received_bytes=500, state="UPLOADING"),
    ev(11, "chunk_ok", offset=500, length=500, duplicate=False),
    ev(12, "result", state="COMPLETE", upload_id="u1", hash_match=True, client_sha256="abc"),
]


def test_progress_follows_chunks_and_resume():
    assert metrics.progress(KILLED_AND_RESUMED[:3]) == 0.3
    assert metrics.progress(KILLED_AND_RESUMED[:7]) == 0.5
    assert metrics.progress([]) == 0.0


def test_run_metrics_across_a_client_restart():
    server = {"state": "COMPLETE", "server_sha256": "abc", "events": [{"event": "STALLED"}, {"event": "COMPLETE"}]}
    m = metrics.run_metrics(KILLED_AND_RESUMED, server)
    assert m["success"] and m["duration_s"] == 12 and m["client_invocations"] == 2
    assert m["retries"] == 1 and m["resumed_bytes"] == 500 and m["duplicate_chunks_acked"] == 1
    assert m["server_events"] == ["STALLED", "COMPLETE"]


def test_success_requires_the_server_hash_too():
    m = metrics.run_metrics(KILLED_AND_RESUMED, {"state": "COMPLETE", "server_sha256": "different"})
    assert not m["success"] and not m["server_sha256_matches_client"]
    assert not metrics.run_metrics(KILLED_AND_RESUMED[:4], None)["success"]  # no result = failure


def test_log_with_a_line_cut_by_sigkill_is_still_readable(tmp_path):
    p = tmp_path / "client.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in KILLED_AND_RESUMED[:3]) + '\n{"t": 4, "event": "chu')
    assert len(metrics.read_log(p)) == 3


def test_summary_aggregates_per_scenario():
    base = metrics.run_metrics(KILLED_AND_RESUMED, {"state": "COMPLETE", "server_sha256": "abc", "events": []})
    runs = [{**base, "scenario": "x", "steps_fired": 1, "steps_total": 1, "faults_total": 1, "faults_mid_transfer": 1},
            {**base, "scenario": "x", "success": False, "steps_fired": 1, "steps_total": 1,
             "faults_total": 1, "faults_mid_transfer": 0}]
    t = metrics.summarize(runs)["x"]
    assert t["runs"] == 2 and t["successes"] == 1 and t["success_rate"] == 0.5 and t["steps_fired_all"]
    assert (t["faults_mid_transfer"], t["faults_total"]) == (1, 2)  # late faults are visible, not hidden


def test_fault_counts_only_if_bytes_were_still_left():
    assert metrics.fault_landed(KILLED_AND_RESUMED, 2.5)        # 50% uploaded, result later
    assert not metrics.fault_landed(KILLED_AND_RESUMED, 11.5)   # all bytes already confirmed
    assert not metrics.fault_landed(KILLED_AND_RESUMED, 13)     # after the result
