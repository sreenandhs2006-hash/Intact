"""Combine several score.json files (e.g. all held-out seeds) into one summary table.

    python -m testset.summary testset/results/seed2-heldout ... --out testset/results/HELDOUT.md
"""
import argparse
import json
import sys
from pathlib import Path


def combine(dirs):
    scores = [json.loads((Path(d) / "score.json").read_text()) for d in dirs]
    per_type, tot = {}, dict(expected=0, found=0, detections=0, fps=0, val_ok=0, videos=0, ctrl_fp=0)
    for s in scores:
        o = s["overall"]
        tot["expected"] += o["expected_events"]
        tot["found"] += o["found"]
        tot["detections"] += o["detections"]
        tot["fps"] += o["false_positives"]
        tot["ctrl_fp"] += o["false_positives_on_controls"]
        tot["videos"] += len(s["videos"])
        tot["val_ok"] += sum(v["validation_ok"] for v in s["videos"])
        for t, b in s["per_type"].items():
            p = per_type.setdefault(t, dict(expected=0, found=0, detections=0, fps=0, terr=[], cexact=[]))
            p["expected"] += b["expected_events"]
            p["found"] += b["found"]
            p["detections"] += b["detections"]
            p["fps"] += b["false_positives"]
        for v in s["videos"]:
            for r in v["events"]:
                p = per_type[r["expected"]["type"]]
                if "time_error_s" in r:
                    p["terr"].append(r["time_error_s"])
                if "count_error" in r:
                    p["cexact"].append(r["count_error"] == 0)
    return scores, per_type, tot


def r(a, b):
    return f"{a / b:.3f}" if b else "–"


def to_markdown(scores, per_type, tot):
    seeds = ", ".join(str(s["seed"]) for s in scores)
    lines = [f"# Held-out detector score (seeds {seeds})", "",
             "Scored with code frozen at the commit that ended seed-1 development; no detector change after.",
             f"Tool versions: ffmpeg `{scores[0]['tool_versions']['ffmpeg']}`, PyAV {scores[0]['tool_versions']['pyav']},"
             f" {scores[0]['tool_versions']['os']}. Match tolerance ±{scores[0]['tolerance_s']*1000:.0f} ms.", "",
             "| Videos | Expected events | Found | Recall | Detections | False positives | Precision | Validation accuracy | FPs on control videos |",
             "|---|---|---|---|---|---|---|---|---|",
             f"| {tot['videos']} | {tot['expected']} | {tot['found']} | {r(tot['found'], tot['expected'])} | {tot['detections']} | "
             f"{tot['fps']} | {r(tot['detections'] - tot['fps'], tot['detections'])} | {r(tot['val_ok'], tot['videos'])} | {tot['ctrl_fp']} |",
             "", "| Type | Expected | Found | Recall | Detections | FPs | Precision | Max time error (ms) | Count exact |",
             "|---|---|---|---|---|---|---|---|---|"]
    for t, p in sorted(per_type.items()):
        terr = f"{max(p['terr'])*1000:.1f}" if p["terr"] else "–"
        lines.append(f"| {t} | {p['expected']} | {p['found']} | {r(p['found'], p['expected'])} | {p['detections']} | "
                     f"{p['fps']} | {r(p['detections'] - p['fps'], p['detections'])} | {terr} | "
                     f"{r(sum(p['cexact']), len(p['cexact']))} |")
    lines += ["", "## Every miss and false positive", ""]
    for s in scores:
        for v in s["videos"]:
            for ev in v["events"]:
                if not ev["found"]:
                    lines.append(f"- seed {s['seed']} · {v['name']} · MISSED `{json.dumps(ev['expected'])}`")
            for fp in v["false_positives"]:
                lines.append(f"- seed {s['seed']} · {v['name']} · FALSE POSITIVE {fp['type']} at {fp['time_s']}: {fp['evidence']}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("dirs", nargs="+")
    p.add_argument("--out")
    a = p.parse_args(argv)
    md = to_markdown(*combine(a.dirs))
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
