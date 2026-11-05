"""Run the whole integrity analysis and write JSON + HTML reports.

    python -m analysis.analyze VIDEO --out reports/            # local file
Inside the server, analysis runs only on files from uploads.verified_file().
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from . import decode as decode_mod
from . import capture as capture_mod
from . import detect, probe, timeline, tools
from .report_html import render

LIMITATIONS = [
    "A byte-perfect transfer proves only that the backend holds the same bytes the client had. "
    "It cannot prove the original recording has no dropped frames.",
    "Frames dropped before encoding, with timestamps re-generated at a constant rate, leave no "
    "timestamp gap. Only content cues (motion spikes) hint at them, and those are low confidence.",
    "Without a capture log or reference recording, capture drops and encoder drops cannot be told apart; "
    "such anomalies are reported with likely cause 'undetermined'. With a browser capture log, see "
    "capture_evidence.can_prove / cannot_prove for what it settles.",
    "Content checks use fixed thresholds on 160x90 grayscale thumbnails. Static scenes, slow motion, "
    "fades and scene cuts can cause misses or false alarms. Thresholds are measured in the M3 test set.",
    "Only the first video stream is analysed; audio is ignored.",
    "Decoder error messages are mapped to frames via packet timestamps; with B-frames the visibly "
    "damaged frame can differ from the reported one, and damage can propagate until the next keyframe.",
]

CAUSES = {
    # type: (likely cause, other candidates, reasoning)
    "missing_frames": ("undetermined", ["capture", "encoding"],
                       "The file's own timestamps show empty frame slots. The capture pipeline may have "
                       "dropped them or the encoder/editor may have discarded them; a capture log is "
                       "needed to tell which."),
    "irregular_timing": ("capture", ["encoding"],
                         "Irregular intervals are typical of capture pipelines that timestamp frames on "
                         "arrival (phones, browsers). An encoder writing variable timestamps is also possible."),
    "duplicate_timestamp": ("encoding", ["capture"],
                            "Timestamps are written by the encoder/muxer; repeated values usually come from "
                            "there, though a faulty capture clock can cause it too."),
    "non_monotonic_timestamp": ("encoding", ["capture"],
                                "Presentation order going backwards points at muxing/encoding."),
    "missing_timestamp": ("encoding", [], "Frames without timestamps come from the muxer/encoder."),
    "duplicated_frame": ("undetermined", ["capture", "encoding"],
                         "An identical picture inside motion: a repeated capture buffer, or an upstream "
                         "frame-rate conversion that duplicated a frame."),
    "possible_skipped_frames": ("undetermined", ["capture", "encoding"],
                                "A motion jump with regular timestamps: frames removed and re-timed, a capture "
                                "drop hidden by constant-rate timestamps, or simply fast motion / a scene cut."),
    "corrupted_frame": ("undetermined", ["encoding"],
                        "The bitstream itself is damaged (encoder fault or storage damage before upload)."),
    "truncation": ("undetermined", ["capture", "encoding"],
                   "The file ends before its header says it should: recording stopped abruptly or the file "
                   "was cut or not finalised."),
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def attribute(a, transfer_verified):
    likely, candidates, why = CAUSES.get(a["type"], ("undetermined", [], ""))
    candidates = list(candidates)
    if transfer_verified:
        ruled_out = ["transfer"]
        why += " Transfer is ruled out: the backend's SHA-256 matches the client's file."
    else:
        ruled_out = []
        if a["type"] in ("corrupted_frame", "truncation"):
            candidates.append("transfer")
        why += " Transfer was not verified for this file, so it cannot be ruled out."
    a.update(likely_cause=likely, other_candidates=candidates, ruled_out=ruled_out, cause_reasoning=why)
    return a


def analyze(path, transfer=None, capture_log=None):
    path = Path(path)
    started = time.time()
    transfer_verified = bool(transfer and transfer.get("state") == "COMPLETE" and transfer.get("verified"))

    pr = probe.ffprobe(path)
    decoded = decode_mod.decode(path)
    cli = probe.ffmpeg_decode_check(path) if decoded["opened"] else {"returncode": None, "error_lines": 0, "errors": []}
    frames = decoded["frames"]
    header_fps = ((pr.get("video") or {}).get("avg_frame_rate")
                  or (decoded["stream"] or {}).get("average_rate"))

    timing_summary, anomalies = (detect.timing(frames, header_fps, decoded["packet_times"])
                                 if frames else ({}, []))
    anomalies += detect.corruption(frames, decoded, cli)
    # content cues are meaningless on damaged pictures (corrupted frame -> next keyframe)
    damaged = detect.corruption_affected(frames, [a for a in anomalies if a["type"] == "corrupted_frame"])
    content_anoms, content_info = detect.content(frames, anomalies, damaged) if frames else ([], {})
    content_info["frames_skipped_as_damaged"] = len(damaged)
    anomalies += content_anoms
    trunc = detect.truncation(frames, pr, decoded, timing_summary)
    if trunc and decoded["packet_times"]:
        # The last packet of a cut file is usually only partly present. Its decode failure
        # is how the truncation shows, not a separate corruption: fold it in.
        last = decoded["packet_times"][-1]  # last packet in file (demux) order
        for a in [a for a in anomalies if a["type"] == "corrupted_frame" and a["time_start_s"] is not None
                  and a["time_start_s"] - 1e-3 <= last <= (a["time_end_s"] or a["time_start_s"]) + 1e-3]:
            anomalies.remove(a)
            trunc[0]["evidence"] += f"; final packet at {last:.3f}s is incomplete ({a['evidence']})"
            if trunc[0].get("estimated_missing") is not None:
                trunc[0]["estimated_missing"] += 1
    anomalies += trunc
    anomalies.sort(key=lambda a: (a["time_start_s"] is None, a["time_start_s"] or 0))
    for n, a in enumerate(anomalies, 1):
        a["id"] = f"A{n}"
        attribute(a, transfer_verified)
    # M5: the browser's per-frame log is independent capture evidence; it can settle
    # capture-vs-encoding for timing anomalies at moments it covers.
    capture_evidence = (capture_mod.evaluate(capture_log, frames, anomalies) if capture_log
                        else {"present": False, "note": "No capture log: capture and encoding drops cannot "
                                                        "be told apart."})

    nominal = (timing_summary.get("median_interval_ms") or 0) / 1000 or None
    tl = timeline.build(frames, nominal, anomalies)

    decode_errors = [e for e in decoded["errors"] if e["kind"] != "no_video_stream"]
    if len(frames) < 2:
        # zero frames = not decodable; one frame = a still image, not a video
        validation = "INVALID"
        if len(frames) == 1:
            decode_errors.append({"kind": "not_a_video", "message": "only one frame decoded (still image)"})
    elif decode_errors or pr["errors"] or cli["error_lines"] or not pr["ok"]:
        validation = "VALID_WITH_ERRORS"
    else:
        validation = "VALID"

    report = {
        "report_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "analysis_seconds": None,
        "tool_versions": tools.versions(),
        "input": {"file": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)},
        "transfer": transfer or {"state": "NOT_APPLICABLE",
                                 "note": "Local file analysed directly; no transfer took place, so transfer "
                                         "integrity is unknown."},
        "transfer_verified": transfer_verified,
        "validation": {
            "status": validation,
            "ffprobe": pr,
            "decode": {"opened": decoded["opened"], "packets": decoded["packets"],
                       "frames_decoded": len(frames), "corrupt_packets": decoded["corrupt_packets"],
                       "errors": decode_errors[:500], "error_count": len(decode_errors)},
            "ffmpeg_cli_decode": cli,
        },
        "source_timing": {**timing_summary, **content_info,
                          "note": "Computed from original timestamps, before any 30 FPS conversion."},
        "timeline_30fps": tl,
        "capture_evidence": capture_evidence,
        "anomalies": anomalies,
        "summary": None,
        "limitations": LIMITATIONS,
        "frames": [{"index": i, **f} for i, f in enumerate(frames)],
    }
    report["summary"] = summarize(report)
    report["analysis_seconds"] = round(time.time() - started, 2)
    return report


def summarize(r):
    an = r["anomalies"]
    counts = {}
    for a in an:
        counts[a["type"]] = counts.get(a["type"], 0) + 1
    gaps = [a for a in an if a["type"] == "missing_frames"]
    ce = r.get("capture_evidence") or {}
    if r["validation"]["status"] == "INVALID":
        drops = "cannot determine: the file could not be decoded"
    elif ce.get("present") and ce.get("usable"):
        drops = _drops_with_log(gaps, ce)
    elif gaps:
        missing = sum(a.get("estimated_missing", 1) for a in gaps)
        why = (f"the capture log is not usable ({ce.get('reason')})" if ce.get("present")
               else "there is no capture log")
        drops = (f"frames missing from the file timeline: ~{missing} in {len(gaps)} gap(s). Whether they were "
                 f"lost during capture or encoding cannot be determined: {why}.")
    else:
        drops = ("cannot determine: no timestamp gaps were found in the file, but frames dropped before "
                 "encoding with re-generated timestamps would leave no gap. A capture log or reference "
                 "recording is required to prove the recording is complete.")
    return {
        "transfer": "verified (SHA-256 match)" if r["transfer_verified"] else r["transfer"].get("state"),
        "validation": r["validation"]["status"],
        "anomaly_counts": counts,
        "anomalies_total": len(an),
        "dropped_frames_in_original_recording": drops,
        "conversion_artefacts": {k: r["timeline_30fps"].get(k) for k in
                                 ("conversion_duplicates", "conversion_omissions", "gap_fill_slots")},
    }


def _drops_with_log(gaps, ce):
    by = {}
    for a in gaps:
        by[a.get("likely_cause", "undetermined")] = by.get(a.get("likely_cause", "undetermined"), 0) + a.get("estimated_missing", 1)
    log = (f"The capture log covers {ce['coverage']:.0%} of the recording ({ce['time_base']}) and shows "
           f"{len(ce['delivery_gaps'])} delivery gap(s) (~{ce['delivery_gap_frames']} frames).")
    if gaps:
        parts = ", ".join(f"~{n} {cause}" for cause, n in sorted(by.items()))
        return (f"frames missing from the file timeline: ~{sum(by.values())} in {len(gaps)} gap(s); "
                f"by likely cause: {parts}. {log}")
    if ce["coverage"] >= 0.99 and not ce["delivery_gaps"]:
        return (f"no drops found: the file has no timestamp gaps and the capture log shows every frame reached "
                f"the browser without a gap. {log} This cannot exclude drops inside the camera that the "
                f"driver hid by re-timing frames.")
    return (f"no timestamp gaps in the file, but the capture log does not cover the whole recording, so drops "
            f"in the uncovered parts cannot be excluded. {log}")


def write_reports(report, out_dir, stem):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    html_path = out_dir / f"{stem}.html"
    # write to temp files and rename, so a reader never sees a half-written report;
    # JSON last because its existence means "report done"
    for path, text in ((html_path, render(report)), (json_path, json.dumps(report, indent=2))):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    return json_path, html_path


def main(argv=None):
    p = argparse.ArgumentParser(description="Frame integrity analysis of a video file.")
    p.add_argument("video")
    p.add_argument("--out", default="reports")
    p.add_argument("--capture-log", help="browser capture log JSON (M5) for this video")
    args = p.parse_args(argv)
    log = json.loads(Path(args.capture_log).read_text(encoding="utf-8")) if args.capture_log else None
    report = analyze(args.video, capture_log=log)
    j, h = write_reports(report, args.out, Path(args.video).stem)
    print(json.dumps(report["summary"], indent=2))
    print(f"JSON: {j}\nHTML: {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
