"""Read the client's JSON-lines log: live progress during a run, metrics after it.

Metrics come only from what the client logged and what the server reported - no estimates.
"""
import json
import statistics
from pathlib import Path


def read_log(path):
    path = Path(path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # a line cut by SIGKILL mid-write
    return events


def progress(events):
    """Fraction of the file the server has confirmed, according to the client log."""
    size, done = None, 0
    for e in events:
        if e["event"] in ("start", "created"):
            size = e.get("size", size)
        elif e["event"] == "chunk_ok":
            done = max(done, e["offset"] + e["length"])
        elif e["event"] == "resume":
            done = max(done, e["received_bytes"])
    return done / size if size else 0.0


def fault_landed(events, fault_t):
    """A fault tests something only if bytes were still left to upload when it hit
    (progress from events logged before the fault < 100%) and the run ended after it."""
    before = [e for e in events if e["t"] <= fault_t]
    ended_after = any(e["event"] == "result" and e["t"] > fault_t for e in events)
    return progress(before) < 1.0 and ended_after


def run_metrics(events, server_info=None):
    starts = [e for e in events if e["event"] == "start"]
    results = [e for e in events if e["event"] == "result"]
    final = results[-1] if results else None
    duration = (final["t"] - starts[0]["t"]) if final and starts else None
    server_ok = bool(server_info and server_info.get("state") == "COMPLETE" and final
                     and server_info.get("server_sha256") == final.get("client_sha256"))
    return {
        "success": bool(final and final["state"] == "COMPLETE" and final["hash_match"] and server_ok),
        "final_state": final["state"] if final else "NO_RESULT",
        "hash_match": bool(final and final["hash_match"]),
        "server_state": (server_info or {}).get("state"),
        "server_sha256_matches_client": server_ok,
        "duration_s": round(duration, 3) if duration is not None else None,
        "client_invocations": len(starts),
        "retries": sum(e["event"] == "retry" for e in events),
        "resyncs": sum(e["event"] == "resync" for e in events),
        "resumed_bytes": sum(e.get("received_bytes", 0) for e in events if e["event"] == "resume"),
        "chunks_ok": sum(e["event"] == "chunk_ok" for e in events),
        "duplicate_chunks_acked": sum(bool(e.get("duplicate")) for e in events if e["event"] == "chunk_ok"),
        "gave_up": any(e["event"] == "give_up" for e in events),
        "size": starts[0]["size"] if starts else None,
        "upload_id": final["upload_id"] if final else None,
        "client_sha256": starts[0]["sha256"] if starts else None,
        "server_sha256": (server_info or {}).get("server_sha256"),
        "server_events": [e["event"] for e in (server_info or {}).get("events", [])],
    }


def summarize(results):
    """results: list of per-run metric dicts with 'scenario'. Returns per-scenario aggregates."""
    out = {}
    for r in results:
        out.setdefault(r["scenario"], []).append(r)
    table = {}
    for name, runs in out.items():
        ok = [r for r in runs if r["success"]]
        dur = [r["duration_s"] for r in ok if r["duration_s"] is not None]
        table[name] = {
            "runs": len(runs),
            "successes": len(ok),
            "success_rate": round(len(ok) / len(runs), 3),
            "hash_verified": sum(r["server_sha256_matches_client"] for r in runs),
            "duration_s_median": round(statistics.median(dur), 2) if dur else None,
            "duration_s_min": round(min(dur), 2) if dur else None,
            "duration_s_max": round(max(dur), 2) if dur else None,
            "retries_mean": round(statistics.fmean(r["retries"] for r in runs), 2),
            "retries_max": max(r["retries"] for r in runs),
            "resumed_bytes_mean": round(statistics.fmean(r["resumed_bytes"] for r in runs)),
            "server_stalled_runs": sum("STALLED" in r["server_events"] for r in runs),
            "steps_fired_all": all(r.get("steps_fired") == r.get("steps_total") for r in runs),
            # a fault that lands after the upload finished tests nothing - count them explicitly
            "faults_total": sum(r.get("faults_total", 0) for r in runs),
            "faults_mid_transfer": sum(r.get("faults_mid_transfer", 0) for r in runs),
        }
    return table
