"""Capture evidence from the browser's per-frame log (M5).

The browser client calls requestVideoFrameCallback (rVFC) on the live preview <video> while
MediaRecorder records the same camera track. Each callback logs when a frame reached the page
(captureTime when the browser provides it, else presentationTime) and the presentedFrames counter.

What this log is: an independent record of the frames the camera track delivered to the page.
What it is not: a record of what MediaRecorder encoded (the preview and the recorder are two
separate consumers of the track). The analysis therefore uses it only to answer one question
per file anomaly: "did frames reach the browser at this moment?"
  - the file lacks frames AND the log shows no frame reached the page  -> capture (source) side
  - the file lacks frames BUT the log shows regular delivery            -> recording/encoding side
  - the log does not cover that moment (hidden tab, no reliable alignment) -> undetermined
"""
import statistics

from .detect import GAP_FACTOR, IRREGULAR_TOLERANCE

MATCH_TOLERANCE_S = 0.15   # upper bound for matching file anomalies to log moments
VSYNC_SLACK_MS = 17        # presentationTime is quantised to display refresh (~60 Hz)
MIN_CAPTURE_TIME_SHARE = 0.9

CAN_PROVE = [
    "When each frame of the camera track reached the page during recording (captureTime, when the "
    "browser provides it), and the number of frames presented (presentedFrames).",
    "Delivery gaps: periods in which no new frame reached the page. If the file has a gap at the same "
    "moment, the frames were most likely never delivered by the camera/OS, so they could not be recorded.",
    "Regular delivery: if frames reached the page at a steady rate while the file has a gap, the frames "
    "were lost after capture, in the recording pipeline (MediaRecorder / encoder / muxer).",
    "Whether the page was hidden (requestVideoFrameCallback pauses then) and how long recording ran.",
]

CANNOT_PROVE = [
    "What MediaRecorder actually encoded: the preview and the recorder are separate consumers of the "
    "track, so a frame shown in the preview may still be missing from the file (that is exactly the "
    "case the log helps to identify).",
    "Why the camera did not deliver a frame (driver, USB bandwidth, exposure time, OS load): a delivery "
    "gap shows only that no frame arrived.",
    "A frame that arrived but was replaced before display (page overloaded) looks the same as a delivery "
    "gap; it is told apart only if the file still contains that frame.",
    "Exact times of frames presented without a callback (main thread busy): presentedFrames counts them, "
    "so they are known to have been delivered, but a short gap hidden among them could be missed.",
    "Picture content: a camera that repeats or freezes a picture still delivers frames on time, so "
    "duplicated pictures cannot be attributed with this log.",
    "Alignment: page clock and file timestamps are aligned by searching the offset at which file frames "
    "and logged frames coincide. With perfectly regular timing this is ambiguous by whole frames; the "
    "report gives the residual, anomalies are matched with a 0.15 s tolerance, and nothing is "
    "re-attributed if the alignment is not reliable.",
    "Authenticity: the log is written by the client. Its SHA-256 and its link to the video's hash are "
    "verified, but a modified client could write any log.",
]


def _times(log):
    """Choose the time base and return [(t_ms, presented_frames)] inside the recording window."""
    rec = log.get("recorder") or {}
    start = rec.get("start_called_ms")
    stop = rec.get("stop_called_ms")
    recs = [f for f in log.get("frames", [])
            if (start is None or f.get("now", 0) >= start) and (stop is None or f.get("now", 0) <= stop)]
    with_ct = [f for f in recs if f.get("capture_time") is not None]
    if recs and len(with_ct) >= MIN_CAPTURE_TIME_SHARE * len(recs):
        base, recs = "capture_time", with_ct
    else:
        base = "presentation_time"
        recs = [f for f in recs if f.get("presentation_time") is not None]
    pts = sorted((f[base], f.get("presented_frames")) for f in recs)
    return base, pts, start, stop


def _hidden(log, start, stop):
    """Intervals [t0, t1] (page ms) in which the page was hidden."""
    out, hidden_since = [], None
    for v in sorted(log.get("visibility", []), key=lambda v: v["t_ms"]):
        if v["state"] == "hidden" and hidden_since is None:
            hidden_since = v["t_ms"]
        elif v["state"] == "visible" and hidden_since is not None:
            out.append((hidden_since, v["t_ms"]))
            hidden_since = None
    if hidden_since is not None:
        out.append((hidden_since, stop if stop is not None else float("inf")))
    return out


def summarize_log(log):
    base, pts, start, stop = _times(log)
    summary = {
        "present": True, "time_base": base, "records_in_recording": len(pts),
        "source": log.get("source"), "user_agent": log.get("user_agent"), "mime_type": log.get("mime_type"),
        "track_settings": log.get("track_settings"), "rvfc_supported": log.get("rvfc_supported"),
        "recording_duration_s": round((stop - start) / 1000, 3) if start is not None and stop is not None else None,
        "simulated_faults": log.get("simulated_faults") or [],
    }
    hidden = _hidden(log, start, stop)
    summary["hidden_intervals_ms"] = [[round(a, 1), round(b, 1)] for a, b in hidden]
    if len(pts) < 3:
        summary["usable"] = False
        summary["reason"] = "fewer than 3 frame records inside the recording window"
        return summary, None

    deltas = [(pts[k][0], pts[k + 1][0], pts[k + 1][0] - pts[k][0],
               (pts[k + 1][1] - pts[k][1]) if pts[k][1] is not None and pts[k + 1][1] is not None else None)
              for k in range(len(pts) - 1)]
    nominal = statistics.median(d for _, _, d, _ in deltas if d > 0)
    slack = VSYNC_SLACK_MS if base == "presentation_time" else 0
    gaps, missed, irregular = [], [], []
    for t0, t1, d, dpf in deltas:
        # n frames were presented in this interval (n > 1: some without a callback). presentedFrames
        # still counts them, so they were delivered - only their exact times are unknown.
        n = dpf if dpf is not None and dpf > 1 else 1
        if n > 1:
            missed.append({"t0_ms": t0, "t1_ms": t1, "frames_without_callback": n - 1})
        if d > GAP_FACTOR * nominal * n + slack:
            gaps.append({"t0_ms": t0, "t1_ms": t1, "interval_ms": round(d, 2),
                         "estimated_missing": max(round(d / nominal) - n, 1)})
        elif n == 1 and base == "capture_time" and abs(d - nominal) > IRREGULAR_TOLERANCE * nominal:
            irregular.append((t0, t1))

    pf = [p for _, p in pts if p is not None]
    summary.update({
        "usable": True,
        "nominal_interval_ms": round(nominal, 3),
        "measured_fps": round(1000 / nominal, 3),
        "first_record_ms": pts[0][0], "last_record_ms": pts[-1][0],
        "presented_frames_in_recording": (pf[-1] - pf[0] + 1) if pf else None,
        "callbacks_missed": sum(m["frames_without_callback"] for m in missed),
        "missed_callback_spans": len(missed),
        "delivery_gaps": gaps,
        "delivery_gap_frames": sum(g["estimated_missing"] for g in gaps),
        "irregular_intervals": len(irregular),
    })
    covered = pts[-1][0] - pts[0][0]
    for a, b in hidden:
        covered -= max(0.0, min(b, pts[-1][0]) - max(a, pts[0][0]))
    span = pts[-1][0] - pts[0][0]
    summary["coverage"] = round(max(covered, 0) / span, 4) if span > 0 else 0.0
    # a logged frame counts as "inside" a file gap only if it is clearly away from the gap's edge frames
    edge_ms = 3 if base == "capture_time" else VSYNC_SLACK_MS
    return summary, {"pts": pts, "gaps": gaps, "missed": missed, "irregular": irregular, "hidden": hidden,
                     "nominal": nominal, "base": base, "edge_ms": edge_ms}


def align(file_pts, log_ms, guess_ms, nominal_ms, search_ms=3000):
    """Find the offset (ms) that maps file time to page time: log_ms ~= file_s * 1000 + offset.

    The recorder timestamps each frame from its capture time, so file frames and logged frames
    should line up in time - except where one side lost frames. Search offsets around the guess
    (first file frame = first frame after MediaRecorder.start()) and keep the one where file frames
    sit closest to logged frames (each distance capped at one frame interval, so frames missing on
    one side cost the same at every offset). Ties go to the offset nearest the guess. Matching by
    time rather than by frame index keeps working when one side has dropped frames.
    """
    import bisect
    cap = nominal_ms

    def cost(o):
        total = 0.0
        for f in file_pts:
            t = f * 1000 + o
            j = bisect.bisect_left(log_ms, t)
            d = min((abs(log_ms[i] - t) for i in (j - 1, j) if 0 <= i < len(log_ms)), default=cap)
            total += min(d, cap)
        return total / len(file_pts)

    coarse = {o: cost(o) for o in range(int(guess_ms - search_ms), int(guess_ms + search_ms) + 1, 2)}
    best_c = min(coarse.values())
    # refine every coarse candidate within one grid step of the best, then prefer the guess on ties
    fine = {}
    for o0 in (o for o, c in coarse.items() if c <= best_c + 1.0):
        for d in range(-20, 21):
            o = round(o0 + d / 10, 1)
            if o not in fine:
                fine[o] = cost(o)
    best_f = min(fine.values())
    offset = min((o for o, c in fine.items() if c <= best_f + 0.05), key=lambda o: abs(o - guess_ms))
    # how unique is it: best cost at least half a frame away from this offset
    # Reliable = close fit, and clearly better than the best offset at least half a frame away
    # (perfectly regular timing matches equally well one frame later: then it is ambiguous).
    rival_o = min((o for o in coarse if abs(o - offset) > nominal_ms / 2), key=coarse.get, default=None)

    def matched(o):
        return sum(1 for f in file_pts
                   if min((abs(log_ms[i] - (f * 1000 + o)) for i in (bisect.bisect_left(log_ms, f * 1000 + o) - 1,
                                                                    bisect.bisect_left(log_ms, f * 1000 + o))
                           if 0 <= i < len(log_ms)), default=cap) <= nominal_ms / 4)
    m_best = matched(offset)
    m_rival = matched(rival_o) if rival_o is not None else 0
    return {"method": "time_search", "offset_ms": round(offset, 1), "guess_ms": round(guess_ms, 1),
            "mean_distance_ms": round(fine[offset], 2), "frames_matched": m_best, "file_frames": len(file_pts),
            "frames_matched_next_best": m_rival,
            # the data pins the offset, or (regular timing) the start-time guess agrees with the best fit
            "reliable": fine[offset] < nominal_ms / 4 and (m_best - m_rival >= 3 or abs(offset - guess_ms) < nominal_ms / 2),
            "decided_by": "frame pattern" if m_best - m_rival >= 3 else "start time"}


def _overlaps(a0, a1, b0, b1):
    return a0 <= b1 and b0 <= a1


def assess(anomaly, idx, to_log_ms, tol_s):
    """What the log says about the moment of one file anomaly.

    missing_frames: the file has no frame between its two neighbour frames, so count the logged
    frames that fall strictly inside that interval. None -> nothing reached the browser either
    (delivery gap); some -> frames reached the browser but not the file.
    Other types: look for a logged delivery gap or irregularity overlapping the anomaly.
    """
    t0 = anomaly.get("time_start_s")
    if t0 is None:
        return {"verdict": "not_covered", "reason": "anomaly has no timestamp"}
    t1 = anomaly.get("time_end_s") or t0
    w0, w1 = to_log_ms(t0 - tol_s), to_log_ms(t1 + tol_s)
    first, last = idx["pts"][0][0], idx["pts"][-1][0]
    if w0 < first or w1 > last:
        return {"verdict": "not_covered", "reason": "moment lies at or beyond the edge of the logged recording"}
    if any(_overlaps(w0, w1, a, b) for a, b in idx["hidden"]):
        return {"verdict": "not_covered", "reason": "the page was hidden (callbacks pause)"}

    if anomaly["type"] == "missing_frames":
        lo, hi = to_log_ms(t0) + idx["edge_ms"], to_log_ms(t1) - idx["edge_ms"]
        if hi - lo < idx["nominal"]:
            # a delivered frame would not have to land inside so narrow a window: cannot judge
            return {"verdict": "not_covered",
                    "reason": f"the {(t1 - t0) * 1000:.0f} ms file gap is too short for the log's time resolution "
                              f"({idx['base']}, +-{idx['edge_ms']} ms)"}
        inside = [t for t, _ in idx["pts"] if lo < t < hi]
        presented = None
        before = [p for t, p in idx["pts"] if t <= lo and p is not None]
        after = [p for t, p in idx["pts"] if t >= hi and p is not None]
        if before and after:
            presented = after[0] - before[-1] - 1  # frames presented strictly between (incl. callback-less)
        delivered = max(len(inside), presented or 0)
        expected = anomaly.get("estimated_missing", 1)
        base = {"log_frames_inside_gap": len(inside), "presented_inside_gap": presented,
                "file_missing": expected, "log_window_ms": [round(lo, 1), round(hi, 1)]}
        if delivered == 0:
            gaps = [g for g in idx["gaps"] if _overlaps(lo, hi, g["t0_ms"], g["t1_ms"])]
            return {**base, "verdict": "delivery_gap", "log_gaps_ms": [[g["t0_ms"], g["t1_ms"]] for g in gaps],
                    "reason": f"no frame reached the page during the {(t1 - t0) * 1000:.0f} ms file gap either"}
        if delivered >= expected:
            return {**base, "verdict": "regular_delivery",
                    "reason": f"{delivered} frame(s) reached the page during this file gap"}
        return {**base, "verdict": "partial_delivery",
                "reason": f"{delivered} of ~{expected} missing frame(s) reached the page during this file gap"}

    gaps = [g for g in idx["gaps"] if _overlaps(w0, w1, g["t0_ms"], g["t1_ms"])]
    if gaps:
        g = max(gaps, key=lambda g: g["interval_ms"])
        return {"verdict": "delivery_gap", "log_interval_ms": g["interval_ms"],
                "log_gaps_ms": [[x["t0_ms"], x["t1_ms"]] for x in gaps],
                "reason": f"no new frame reached the page for {g['interval_ms']:.1f} ms here"}
    if anomaly["type"] == "irregular_timing" and idx["base"] != "capture_time":
        return {"verdict": "not_covered",
                "reason": "the log has only presentation times (rounded to the display refresh), too coarse to "
                          "judge timing irregularities this small"}
    if any(_overlaps(w0, w1, a, b) for a, b in idx["irregular"]):
        return {"verdict": "irregular_delivery", "reason": "frames reached the page at irregular intervals here"}
    return {"verdict": "regular_delivery",
            "reason": f"frames reached the page every ~{idx['nominal']:.1f} ms with no gap here"}


# (anomaly type, verdict) -> (likely cause, other candidates, extra ruled-out, reasoning)
REATTRIBUTE = {
    ("missing_frames", "delivery_gap"): (
        "capture", [], [],
        "The capture log shows no frame reached the browser at this moment either, so the frames were "
        "most likely never delivered by the camera/OS and could not be recorded."),
    ("missing_frames", "regular_delivery"): (
        "encoding", [], ["capture"],
        "The capture log shows frames reached the browser regularly at this moment, yet they are missing "
        "from the file: they were lost in the recording pipeline (MediaRecorder/encoder/muxer)."),
    ("missing_frames", "partial_delivery"): (
        "encoding", ["capture"], [],
        "Some of the missing frames reached the browser, so at least those were lost in the recording "
        "pipeline; the rest may not have been delivered."),
    ("irregular_timing", "delivery_gap"): (
        "capture", [], [], "The capture log shows irregular delivery (a gap) at the same moment."),
    ("irregular_timing", "irregular_delivery"): (
        "capture", [], [], "The capture log shows frames reached the browser at the same irregular intervals."),
    ("irregular_timing", "regular_delivery"): (
        "encoding", [], ["capture"],
        "Frames reached the browser regularly, so the irregular file timestamps were written later "
        "(recorder/muxer timestamping)."),
    ("possible_skipped_frames", "delivery_gap"): (
        "capture", [], [], "The capture log shows a delivery gap at this motion jump."),
    ("possible_skipped_frames", "regular_delivery"): (
        "undetermined", ["encoding"], ["capture"],
        "Frames reached the browser regularly here, so nothing was lost before the browser; the motion "
        "jump may be real fast motion or a recording-side drop."),
    ("duplicated_frame", "regular_delivery"): (
        "undetermined", ["capture", "encoding"], [],
        "Frames reached the browser on time here; the log cannot see picture content, so a camera that "
        "repeated a picture cannot be told apart from an encoder duplicate."),
}


def evaluate(log, frames, anomalies):
    """Return the report's capture_evidence section; re-attribute anomalies the log speaks to."""
    summary, idx = summarize_log(log)
    summary["can_prove"], summary["cannot_prove"] = CAN_PROVE, CANNOT_PROVE
    if idx is None:
        return summary
    file_pts = [f["pts_s"] for f in frames if f.get("pts_s") is not None]
    if not file_pts:
        summary["usable"], summary["reason"] = False, "file has no frame timestamps to align with"
        return summary
    rec = log.get("recorder") or {}
    guess = (rec.get("start_called_ms") or idx["pts"][0][0]) - min(file_pts) * 1000
    alignment = align(sorted(file_pts), [t for t, _ in idx["pts"]], guess, idx["nominal"])
    offset = alignment["offset_ms"]
    to_log_ms = lambda t: t * 1000 + offset
    # with a reliable alignment, match within about one frame; otherwise nothing is matched anyway
    tol_s = min(MATCH_TOLERANCE_S, max(idx["nominal"], 3 * alignment["mean_distance_ms"]) / 1000)
    summary["alignment"] = {**alignment, "tolerance_s": round(tol_s, 4)}
    file_span = max(file_pts) - min(file_pts)
    log_span = (idx["pts"][-1][0] - idx["pts"][0][0]) / 1000
    summary["file_frames"] = len(file_pts)
    summary["file_span_s"] = round(file_span, 3)
    summary["log_span_s"] = round(log_span, 3)
    # rough: the recorder may start/stop a frame earlier or later than the preview log
    summary["frames_presented_minus_file_frames"] = (
        (summary["presented_frames_in_recording"] or summary["records_in_recording"]) - len(file_pts))

    counts = {}
    for a in anomalies:
        ev = (assess(a, idx, to_log_ms, tol_s) if alignment["reliable"] else
              {"verdict": "not_covered", "reason": "file and log could not be aligned reliably"})
        a["capture_evidence"] = ev
        counts[ev["verdict"]] = counts.get(ev["verdict"], 0) + 1
        rule = REATTRIBUTE.get((a["type"], ev["verdict"]))
        if rule:
            likely, others, extra_ruled_out, why = rule
            a["likely_cause"] = likely
            a["other_candidates"] = others
            a["ruled_out"] = sorted(set(a.get("ruled_out", [])) | set(extra_ruled_out))
            # the log replaces the generic reasoning; keep only the transfer verdict sentence
            prior = a.get("cause_reasoning", "")
            transfer = prior[prior.find("Transfer "):] if "Transfer " in prior else ""
            a["cause_reasoning"] = f"{why} ({ev['reason']}.) {transfer}".strip()
            a["cause_basis"] = "capture_log"
        elif ev["verdict"] == "not_covered" and a["type"] in {t for t, _ in REATTRIBUTE}:
            a["cause_reasoning"] = (f"The capture log does not cover this moment ({ev['reason']}), so the "
                                    "cause stays as stated. ") + a.get("cause_reasoning", "")
    summary["anomaly_verdicts"] = counts

    # Delivery gaps the file does not show: only the preview missed frames (page busy) - no file impact.
    matched = {tuple(g) for a in anomalies for g in a["capture_evidence"].get("log_gaps_ms", [])}
    summary["delivery_gaps_without_file_anomaly"] = [g for g in idx["gaps"] if (g["t0_ms"], g["t1_ms"]) not in matched]
    return summary
