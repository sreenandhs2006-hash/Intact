"""Score the detector against a generated known-fault set.

    python -m testset.score --set ~/.nihilent-vi/testset/seed1 --out testset/results/seed1

Matching rules (fixed before looking at results):
- A detection matches an expected event only if the TYPE is identical.
- Point events (missing_frames, possible_skipped_frames, duplicated_frame, truncation):
  one-to-one, nearest first, within TOLERANCE_S of the detection's event time.
- Range events (irregular_timing): any overlap counts.
- corrupted_frame: one expected event per damaged packet; it is found if it lies inside a
  detected corrupted range (+-TOLERANCE_S). One detection may cover several damaged packets,
  because damage spreads to following frames until the next keyframe.
- Any detection that matches nothing is a false positive.
Metrics: precision, recall, timestamp error of matched point events, count error, false
positives (overall and on control videos), validation-status accuracy.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from analysis.analyze import analyze
from analysis.tools import versions

TOLERANCE_S = 0.2
POINT_TYPES = {"missing_frames", "possible_skipped_frames", "duplicated_frame", "truncation"}


def event_time(det):
    """The single time a detection points at, comparable with the generator's ground truth."""
    if det["type"] in ("missing_frames", "possible_skipped_frames"):
        return det["time_end_s"]       # first frame after the missing ones
    return det["time_start_s"]         # first duplicate / last decoded frame before truncation


def det_count(det):
    return det.get("estimated_missing") if "estimated_missing" in det else det.get("count")


def match_video(expected, detections):
    """Return (per-event results, per-detection matched flags)."""
    used = [False] * len(detections)
    results = []
    for ev in expected:
        r = {"expected": ev, "found": False}
        cands = [i for i, d in enumerate(detections) if d["type"] == ev["type"]]
        if ev["type"] in POINT_TYPES:
            best = None
            for i in cands:
                t = event_time(detections[i])
                if not used[i] and t is not None and abs(t - ev["time_s"]) <= TOLERANCE_S:
                    if best is None or abs(t - ev["time_s"]) < abs(event_time(detections[best]) - ev["time_s"]):
                        best = i
            if best is not None:
                used[best] = True
                d = detections[best]
                r.update(found=True, detection=d["id"], time_error_s=round(abs(event_time(d) - ev["time_s"]), 4))
                if ev.get("count") is not None and det_count(d) is not None:
                    r["count_error"] = abs(det_count(d) - ev["count"])
        elif ev["type"] == "irregular_timing":
            for i in cands:
                d = detections[i]
                if d["time_start_s"] <= ev["end_s"] and (d["time_end_s"] or 0) >= ev["start_s"]:
                    used[i] = True
                    r.update(found=True, detection=d["id"])
        elif ev["type"] == "corrupted_frame":
            for i in cands:
                d = detections[i]
                if d["time_start_s"] is None:
                    continue
                if d["time_start_s"] - TOLERANCE_S <= ev["time_s"] <= (d["time_end_s"] or d["time_start_s"]) + TOLERANCE_S:
                    used[i] = True
                    r.update(found=True, detection=d["id"])
        results.append(r)
    return results, used


def ratio(a, b):
    return round(a / b, 4) if b else None


def score(set_dir):
    set_dir = Path(set_dir)
    manifest = json.loads((set_dir / "manifest.json").read_text())
    videos, per_type = [], {}

    def bucket(t):
        return per_type.setdefault(t, {"tp_events": 0, "fn_events": 0, "tp_detections": 0, "fp_detections": 0,
                                       "time_errors": [], "count_errors": []})

    for entry in manifest:
        t0 = time.time()
        report = analyze(set_dir / entry["file"])
        dets = report["anomalies"]
        results, used = match_video(entry["anomalies"], dets)
        for r in results:
            b = bucket(r["expected"]["type"])
            b["tp_events" if r["found"] else "fn_events"] += 1
            if "time_error_s" in r:
                b["time_errors"].append(r["time_error_s"])
            if "count_error" in r:
                b["count_errors"].append(r["count_error"])
        fps = []
        for d, u in zip(dets, used):
            bucket(d["type"])["tp_detections" if u else "fp_detections"] += 1
            if not u:
                fps.append({"id": d["id"], "type": d["type"], "time_s": d["time_start_s"],
                            "confidence": d["confidence"], "evidence": d["evidence"]})
        videos.append({
            "name": entry["name"], "description": entry["description"], "control": entry.get("control", False),
            "expected_validation": entry["validation"], "validation": report["validation"]["status"],
            "validation_ok": entry["validation"] == report["validation"]["status"],
            "expected_events": len(entry["anomalies"]), "found_events": sum(r["found"] for r in results),
            "detections": len(dets), "false_positives": fps, "events": results,
            "conversion_duplicates": report["timeline_30fps"]["conversion_duplicates"],
            "analysis_s": round(time.time() - t0, 2),
        })

    types_out, tot = {}, {"tp_events": 0, "fn_events": 0, "tp_detections": 0, "fp_detections": 0}
    for t, b in sorted(per_type.items()):
        for k in tot:
            tot[k] += b[k]
        te, ce = b["time_errors"], b["count_errors"]
        types_out[t] = {
            "expected_events": b["tp_events"] + b["fn_events"], "found": b["tp_events"], "missed": b["fn_events"],
            "detections": b["tp_detections"] + b["fp_detections"], "false_positives": b["fp_detections"],
            "recall": ratio(b["tp_events"], b["tp_events"] + b["fn_events"]),
            "precision": ratio(b["tp_detections"], b["tp_detections"] + b["fp_detections"]),
            "time_error_mean_ms": round(statistics.fmean(te) * 1000, 2) if te else None,
            "time_error_max_ms": round(max(te) * 1000, 2) if te else None,
            "count_exact": ratio(sum(c == 0 for c in ce), len(ce)) if ce else None,
            "count_error_mean": round(statistics.fmean(ce), 3) if ce else None,
        }
    controls = [v for v in videos if v["control"]]
    return {
        "set": str(set_dir), "seed": manifest[0]["seed"] if manifest else None,
        "scored_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool_versions": versions(),
        "tolerance_s": TOLERANCE_S,
        "overall": {
            "expected_events": tot["tp_events"] + tot["fn_events"], "found": tot["tp_events"],
            "detections": tot["tp_detections"] + tot["fp_detections"], "false_positives": tot["fp_detections"],
            "recall": ratio(tot["tp_events"], tot["tp_events"] + tot["fn_events"]),
            "precision": ratio(tot["tp_detections"], tot["tp_detections"] + tot["fp_detections"]),
            "validation_accuracy": ratio(sum(v["validation_ok"] for v in videos), len(videos)),
            "false_positives_on_controls": sum(len(v["false_positives"]) for v in controls),
            "control_videos": len(controls),
        },
        "per_type": types_out,
        "videos": videos,
    }


def to_markdown(s):
    o = s["overall"]
    lines = [f"# Detector score - seed {s['seed']}", "",
             f"Scored {s['scored_at']} · tolerance ±{s['tolerance_s']*1000:.0f} ms · "
             f"ffmpeg `{s['tool_versions']['ffmpeg']}` · PyAV {s['tool_versions']['pyav']} · {s['tool_versions']['os']}", "",
             "## Overall", "",
             "| Expected events | Found | Recall | Detections | False positives | Precision | Validation accuracy | FPs on controls |",
             "|---|---|---|---|---|---|---|---|",
             f"| {o['expected_events']} | {o['found']} | {o['recall']} | {o['detections']} | {o['false_positives']} | "
             f"{o['precision']} | {o['validation_accuracy']} | {o['false_positives_on_controls']} (of {o['control_videos']} control videos) |",
             "", "## Per anomaly type", "",
             "| Type | Expected | Found | Recall | Detections | FPs | Precision | Time err mean / max (ms) | Count exact |",
             "|---|---|---|---|---|---|---|---|---|"]
    for t, b in s["per_type"].items():
        lines.append(f"| {t} | {b['expected_events']} | {b['found']} | {b['recall']} | {b['detections']} | "
                     f"{b['false_positives']} | {b['precision']} | {b['time_error_mean_ms']} / {b['time_error_max_ms']} | "
                     f"{b['count_exact']} |")
    lines += ["", "## Per video", "",
              "| Video | Expected validation | Got | Events found | Detections | False positives |",
              "|---|---|---|---|---|---|"]
    for v in s["videos"]:
        fp = "; ".join(f"{f['type']} @{f['time_s']:.2f}s" if f["time_s"] is not None else f["type"]
                       for f in v["false_positives"]) or "–"
        mark = "" if v["validation_ok"] else " ✗"
        lines.append(f"| {v['name']} | {v['expected_validation']} | {v['validation']}{mark} | "
                     f"{v['found_events']}/{v['expected_events']} | {v['detections']} | {fp} |")
    lines += ["", "## Missed events", ""]
    missed = [(v["name"], r["expected"]) for v in s["videos"] for r in v["events"] if not r["found"]]
    lines += [f"- {n}: `{json.dumps(e)}`" for n, e in missed] or ["- none"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description="Score the detector on a known-fault set.")
    p.add_argument("--set", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    s = score(Path(args.set).expanduser())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "score.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    (out / "score.md").write_text(to_markdown(s), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    print(to_markdown(s))


if __name__ == "__main__":
    main()
