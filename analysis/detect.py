"""Anomaly detection on the SOURCE frames (original timestamps, before 30 FPS conversion).

Two independent kinds of evidence:
1. Timestamps  - gaps, repeats, reversals, irregular intervals. Strong evidence:
                 the file itself says a frame slot is empty.
2. Content     - thumbnail differences between consecutive frames. Weaker
                 evidence: an identical frame inside motion suggests a duplicate,
                 a motion spike suggests frames were removed and re-timed.
Thresholds are named constants so M3 can measure them; they are not tuned per video.
"""
import statistics

GAP_FACTOR = 1.5          # interval > 1.5x nominal  => at least one frame slot is empty
IRREGULAR_TOLERANCE = 0.25  # |interval - nominal| > 25% of nominal => irregular timing
IRREGULAR_MERGE = 15      # irregular intervals <= 15 intervals apart are one segment
DUP_MAX_DIFF = 0.5        # mean abs thumbnail diff (0-255) at or below this = "same picture"
MOTION_MIN = 2.0          # local motion needed before content checks are meaningful
SKIP_RATIO = 1.8          # diff > 1.8x local median motion => possible removed frames
SCENE_CUT_RATIO = 6.0     # far larger jumps look like scene cuts rather than drops
MAX_DUP_RUN = 15          # longer identical runs (0.5 s @30fps) are treated as static scenes
WINDOW = 5                # frames each side for the local motion median


def _anomaly(kind, frames, i0, i1, evidence, confidence, **extra):
    t0 = frames[i0]["pts_s"] if 0 <= i0 < len(frames) else None
    t1 = frames[i1]["pts_s"] if 0 <= i1 < len(frames) else None
    return {"type": kind, "frame_index_start": i0, "frame_index_end": i1,
            "time_start_s": t0, "time_end_s": t1, "evidence": evidence,
            "confidence": confidence, **extra}


def nominal_interval(times, header_fps):
    deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
    median = statistics.median(deltas) if deltas else None
    header = 1 / header_fps if header_fps else None
    return median, header


def timing(frames, header_fps):
    """Return (summary, anomalies) from presentation timestamps."""
    anomalies = []
    missing_pts = [i for i, f in enumerate(frames) if f["pts_s"] is None]
    if missing_pts:
        anomalies.append(_anomaly("missing_timestamp", frames, missing_pts[0], missing_pts[-1],
                                  f"{len(missing_pts)} decoded frames carry no timestamp", "high"))
    idx = [i for i, f in enumerate(frames) if f["pts_s"] is not None]
    times = [frames[i]["pts_s"] for i in idx]
    if len(times) < 2:
        return {"frames_with_timestamps": len(times)}, anomalies

    median, header = nominal_interval(times, header_fps)
    nominal = median or header
    eps = nominal * 0.01
    deltas = [b - a for a, b in zip(times, times[1:])]
    irregular_run = []

    def flush_irregular():
        if irregular_run:
            a, b = irregular_run[0], irregular_run[-1]
            vals = [deltas[k] * 1000 for k in irregular_run]
            anomalies.append(_anomaly(
                "irregular_timing", frames, idx[a], idx[b + 1],
                f"{len(irregular_run)} of {b - a + 1} intervals in this segment off nominal"
                f" {nominal*1000:.2f} ms by >{IRREGULAR_TOLERANCE:.0%}: {min(vals):.2f}-{max(vals):.2f} ms", "high",
                intervals_ms=[round(v, 3) for v in vals[:50]]))
            irregular_run.clear()

    for k, d in enumerate(deltas):
        i, j = idx[k], idx[k + 1]
        if abs(d) <= eps:
            flush_irregular()
            anomalies.append(_anomaly("duplicate_timestamp", frames, i, j,
                                      f"frames {i} and {j} share timestamp {times[k]:.4f}s", "high"))
        elif d < 0:
            flush_irregular()
            anomalies.append(_anomaly("non_monotonic_timestamp", frames, i, j,
                                      f"timestamp goes backwards by {-d*1000:.2f} ms", "high"))
        elif d > GAP_FACTOR * nominal:
            flush_irregular()
            missing = round(d / nominal) - 1
            anomalies.append(_anomaly(
                "missing_frames", frames, i, j,
                f"interval {d*1000:.2f} ms = {d/nominal:.2f}x nominal {nominal*1000:.2f} ms;"
                f" ~{missing} frame slot(s) empty between {times[k]:.4f}s and {times[k+1]:.4f}s",
                "high", estimated_missing=max(missing, 1)))
        elif abs(d - nominal) > IRREGULAR_TOLERANCE * nominal:
            irregular_run.append(k)
        elif irregular_run and k - irregular_run[-1] > IRREGULAR_MERGE:
            flush_irregular()  # irregular intervals close together form one segment
    flush_irregular()

    positive = [d for d in deltas if d > 0]
    mean = statistics.fmean(positive)
    std = statistics.pstdev(positive)
    summary = {
        "frames_with_timestamps": len(times),
        "first_pts_s": times[0],
        "last_pts_s": times[-1],
        "span_s": times[-1] - times[0] + nominal,
        "header_fps": header_fps,
        "median_interval_ms": round(median * 1000, 4) if median else None,
        "measured_fps": round(1 / median, 4) if median else None,
        "interval_min_ms": round(min(positive) * 1000, 4),
        "interval_max_ms": round(max(positive) * 1000, 4),
        "interval_mean_ms": round(mean * 1000, 4),
        "interval_std_ms": round(std * 1000, 4),
        "interval_cv": round(std / mean, 5),
        "variable_frame_rate": any(a["type"] == "irregular_timing" for a in anomalies),
    }
    return summary, anomalies


def content(frames, timing_anomalies):
    """Duplicate and skipped frames from picture content. Returns (anomalies, info)."""
    diffs = [f["diff_prev"] for f in frames]
    n = len(frames)
    gap_starts = {a["frame_index_end"] for a in timing_anomalies if a["type"] == "missing_frames"}
    ts_dups = {a["frame_index_end"] for a in timing_anomalies if a["type"] == "duplicate_timestamp"}

    def local_motion(i):
        around = [diffs[k] for k in range(max(1, i - WINDOW), min(n, i + WINDOW + 1))
                  if k != i and diffs[k] is not None and diffs[k] > DUP_MAX_DIFF]
        return statistics.median(around) if len(around) >= 3 else 0.0

    anomalies, static_frames, corroborated = [], 0, []
    i = 1
    while i < n:
        d = diffs[i]
        if d is None:
            i += 1
            continue
        if d <= DUP_MAX_DIFF:
            j = i
            while j + 1 < n and diffs[j + 1] is not None and diffs[j + 1] <= DUP_MAX_DIFF:
                j += 1
            run = j - i + 1
            motion = local_motion(i)
            if run <= MAX_DUP_RUN and motion >= MOTION_MIN:
                if i in ts_dups:
                    corroborated.append(i)
                anomalies.append(_anomaly(
                    "duplicated_frame", frames, i, j,
                    f"{run} frame(s) identical to frame {i-1} (diff <= {DUP_MAX_DIFF}) while local motion"
                    f" is {motion:.2f}", "medium", count=run))
            else:
                static_frames += run
            i = j + 1
            continue
        motion = local_motion(i)
        if motion >= MOTION_MIN and d > SKIP_RATIO * motion:
            ratio = d / motion
            if i in gap_starts:
                corroborated.append(i)  # the timestamp gap already explains this jump
            else:
                note = " (very large: may be a scene cut)" if ratio > SCENE_CUT_RATIO else ""
                anomalies.append(_anomaly(
                    "possible_skipped_frames", frames, i - 1, i,
                    f"picture change {d:.2f} is {ratio:.2f}x local motion {motion:.2f} while timestamps"
                    f" stay regular{note}", "low", estimated_missing=max(1, round(ratio) - 1)))
        i += 1
    return anomalies, {"static_frames": static_frames, "content_corroborates_frames": corroborated}


def corruption(frames, decoded, ffmpeg_check):
    """Corrupted frames from decoder messages, corrupt flags and decode exceptions."""
    anomalies = []
    by_time = {}
    for e in decoded["errors"]:
        t = e.get("packet_time_s")
        if t is not None:
            by_time.setdefault(round(t, 6), []).append(e["message"])
    flagged = []
    for i, f in enumerate(frames):
        msgs = by_time.get(round(f["pts_s"], 6), []) if f["pts_s"] is not None else []
        if msgs or f["corrupt"]:
            flagged.append((i, msgs, f["corrupt"]))
    # group consecutive flagged frames into one anomaly each
    groups, cur = [], []
    for item in flagged:
        if cur and item[0] != cur[-1][0] + 1:
            groups.append(cur)
            cur = []
        cur.append(item)
    if cur:
        groups.append(cur)
    cli_confirms = ffmpeg_check["error_lines"] > 0
    for g in groups:
        msgs = [m for _, ms, _ in g for m in ms]
        keys_after = [k for k in range(g[-1][0] + 1, len(frames)) if frames[k]["key"]]
        heal = frames[keys_after[0]]["pts_s"] if keys_after else None
        anomalies.append(_anomaly(
            "corrupted_frame", frames, g[0][0], g[-1][0],
            f"{len(g)} frame(s) with decoder errors/corrupt flag; e.g. '{msgs[0] if msgs else 'corrupt flag'}'."
            f" ffmpeg CLI {'also reports' if cli_confirms else 'does not report'} errors."
            + (f" Damage may propagate until next keyframe at {heal:.3f}s." if heal is not None else ""),
            "high" if cli_confirms else "medium",
            messages=msgs[:10]))
    unplaced = [e for e in decoded["errors"] if e.get("packet_time_s") is None
                and e["kind"] in ("decoder_message", "decode_exception")]
    if unplaced:
        anomalies.append({"type": "corrupted_frame", "frame_index_start": None, "frame_index_end": None,
                          "time_start_s": None, "time_end_s": None, "confidence": "medium",
                          "evidence": f"{len(unplaced)} decoder error(s) without a timestamp",
                          "messages": [e["message"] for e in unplaced[:10]]})
    return anomalies


def truncation(frames, probe, decoded, timing_summary):
    """File shorter than its own header claims, or the demuxer hit a damaged end."""
    anomalies = []
    v = (probe or {}).get("video") or {}
    declared_frames = v.get("declared_frames")
    n = len(frames)
    demux_errors = [e for e in decoded["errors"] if e["kind"] == "demux_error"]
    reasons = []
    if declared_frames and n < declared_frames:
        reasons.append(f"header declares {declared_frames} frames, {n} decoded")
    declared = v.get("declared_duration_s") or ((probe or {}).get("format") or {}).get("duration_s")
    span = timing_summary.get("span_s")
    if declared and span and declared - span > 2 * (1 / (v.get("avg_frame_rate") or 30)):
        reasons.append(f"header duration {declared:.3f}s, decoded frames span {span:.3f}s")
    if demux_errors:
        reasons.append(f"demuxer error: {demux_errors[0]['message']}")
    if reasons:
        last = n - 1
        anomalies.append({"type": "truncation", "frame_index_start": last if n else None,
                          "frame_index_end": None,
                          "time_start_s": frames[last]["pts_s"] if n else None,
                          "time_end_s": declared, "confidence": "high" if len(reasons) > 1 or demux_errors else "medium",
                          "evidence": "; ".join(reasons),
                          "estimated_missing": (declared_frames - n) if declared_frames and n < declared_frames else None})
    return anomalies
