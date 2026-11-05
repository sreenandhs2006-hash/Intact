"""Map source frames onto a constant 30 FPS timeline.

Rule ("sample and hold", what a player shows): output slot k at time
t_k = start + k/30 shows the latest source frame whose timestamp is <= t_k.

Consequences, labelled as CONVERSION ARTEFACTS, never as source defects:
- a source frame shown in 2+ slots  -> conversion_duplicate (source slower than 30 fps,
  or a source gap being filled - then tagged gap_fill with the gap's anomaly id)
- a source frame shown in 0 slots   -> conversion_omission (source faster than 30 fps)
"""
import bisect

TARGET_FPS = 30
EPS = 1e-4  # 0.1 ms tolerance for float timestamp rounding


def build(frames, nominal_interval, anomalies, target_fps=TARGET_FPS):
    timed = [(f["pts_s"], i) for i, f in enumerate(frames) if f["pts_s"] is not None]
    timed.sort()
    if not timed:
        return {"target_fps": target_fps, "slots": [], "slot_count": 0,
                "conversion_duplicates": 0, "conversion_omissions": 0, "gap_fill_slots": 0,
                "omitted_source_frames": []}
    times = [t for t, _ in timed]
    start = times[0]
    end = times[-1] + (nominal_interval or 1 / target_fps)
    count = round((end - start) * target_fps)

    # source frame index -> anomaly id of the timestamp gap that FOLLOWS it
    gap_after = {a["frame_index_start"]: a["id"] for a in anomalies if a["type"] == "missing_frames"}

    slots, used = [], {}
    for k in range(count):
        t = start + k / target_fps
        pos = bisect.bisect_right(times, t + EPS) - 1
        src = timed[max(pos, 0)][1]
        used[src] = used.get(src, 0) + 1
        if slots and slots[-1]["source_frame"] == src:
            kind = "gap_fill" if src in gap_after else "conversion_duplicate"
        else:
            kind = "original"
        slot = {"index": k, "time_s": round(t, 6), "source_frame": src,
                "source_pts_s": frames[src]["pts_s"], "kind": kind}
        if kind == "gap_fill":
            slot["gap_anomaly"] = gap_after[src]
        slots.append(slot)

    omitted = [{"source_frame": i, "source_pts_s": t} for t, i in timed if i not in used]
    return {
        "target_fps": target_fps,
        "rule": "slot k shows the latest source frame with pts <= start + k/30",
        "start_s": start,
        "slot_count": count,
        "conversion_duplicates": sum(s["kind"] == "conversion_duplicate" for s in slots),
        "gap_fill_slots": sum(s["kind"] == "gap_fill" for s in slots),
        "conversion_omissions": len(omitted),
        "omitted_source_frames": omitted,
        "slots": slots,
    }
