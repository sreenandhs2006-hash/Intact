"""Build the judges' PDF: docs/Intact-nSEPIA-Sreenandh-S.pdf.

    python docs/submission/build.py [--repo https://github.com/...]

Reads the numbers from the evidence files (network runs, held-out detector scores, the test suite itself), draws
the charts as SVG, writes docs/submission/submission.html and prints it to PDF with headless Chrome. The few numbers
that come from reading raw logs by hand (lost acknowledgements, bytes re-sent, browser-run findings) are constants
below, each with the file it comes from.
"""
import argparse
import html
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_HTML = ROOT / "docs" / "submission" / "submission.html"
OUT_PDF = ROOT / "docs" / "Intact-nSEPIA-Sreenandh-S.pdf"
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", "google-chrome", "chromium"]

AUTHOR = "Sreenandh Sudheesh Puthalath"

# From reading the raw logs (nettest/EVIDENCE.md, section 3) and the browser runs (evidence/m5/README.md).
LOST_ACKS = 13                 # runs where an acknowledgement was lost; each time the client skipped ahead <= 1 chunk
MAX_RESENT_AFTER_CRASH = 524_288   # bytes re-sent after a server SIGKILL (server_restart, 5 runs)
REAL_RATE_AT_20 = "140–200"    # kbit/s of useful data on the 20% link (500 kbit/s nominal, 5% loss, 400 ms RTT)
PING_100, PING_20 = 22.2, 401.7     # ms, measured before the runs
REJECT_TESTS = 16              # tests/test_m1_transfer.py: damaged, partial or altered uploads never accepted

NICE = {
    "stable_100": "Stable 100%", "stable_60": "Stable 60%", "stable_20": "Stable 20%",
    "fluctuating": "Fluctuating 100↔20%", "interruption": "10 s outage", "network_switch": "Network switch",
    "resets": "TCP resets ×3", "timeouts": "30 s hangs ×2", "client_restart": "Client killed",
    "server_restart": "Server killed",
}
TYPE_NICE = {
    "missing_frames": "Missing frames", "truncation": "Truncation", "corrupted_frame": "Corrupted frame",
    "duplicated_frame": "Duplicated frame", "irregular_timing": "Irregular timing",
    "possible_skipped_frames": "Possibly skipped",
}
e = html.escape


def load_network():
    d = json.loads((ROOT / "nettest/runs/summary.json").read_text(encoding="utf-8"))
    runs = d["runs"]
    return {
        "scen": d["scenarios"],
        "defs": d["environment"]["scenarios"],
        "profiles": d["environment"]["profiles"],
        "video_bytes": d["environment"]["video"]["size_bytes"],
        "chunk_kb": d["environment"]["max_chunk_kb"],
        "runs": len(runs),
        "ok": sum(r["success"] and r["final_state"] == "COMPLETE" for r in runs),
        "hash": sum(bool(r["server_sha256_matches_client"]) for r in runs),
        "faults": sum(r["faults_mid_transfer"] for r in runs),
        "retries": sum(r["retries"] for r in runs),
    }


def load_detector():
    per, tot = {}, {"expected_events": 0, "found": 0, "detections": 0, "false_positives": 0,
                    "videos": 0, "valid_ok": 0.0, "controls": 0, "fp_controls": 0}
    for seed in range(2, 7):
        d = json.loads((ROOT / f"testset/results/seed{seed}-heldout/score.json").read_text(encoding="utf-8"))
        o, n = d["overall"], len(d["videos"])
        for k in ("expected_events", "found", "detections", "false_positives"):
            tot[k] += o[k]
        tot["videos"] += n
        tot["valid_ok"] += o["validation_accuracy"] * n
        tot["controls"] += o["control_videos"]
        tot["fp_controls"] += o["false_positives_on_controls"]
        for t, v in d["per_type"].items():
            p = per.setdefault(t, {"expected": 0, "found": 0, "detections": 0, "fp": 0})
            p["expected"] += v["expected_events"]; p["found"] += v["found"]
            p["detections"] += v["detections"]; p["fp"] += v["false_positives"]
    tot["recall"] = tot["found"] / tot["expected_events"]
    tot["precision"] = (tot["detections"] - tot["false_positives"]) / tot["detections"]
    for p in per.values():
        p["recall"] = p["found"] / p["expected"]
        p["precision"] = (p["detections"] - p["fp"]) / p["detections"] if p["detections"] else 1.0
    return per, tot


def count_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True)
    for ln in reversed(r.stdout.splitlines()):
        if " test" in ln and ("collected" in ln or ln.split()[0].isdigit()):
            return int(ln.split()[0])
    raise SystemExit(f"could not count tests: {r.stdout[-300:]}")


# ---------------------------------------------------------------- charts (inline SVG)

def chart_network(net):
    order = ["stable_100", "stable_60", "stable_20", "fluctuating", "interruption", "network_switch",
             "resets", "timeouts", "client_restart", "server_restart"]
    W, row, left, right = 640, 29, 150, 92
    H = row * len(order) + 34
    lo, hi = math.log10(1), math.log10(300)
    x = lambda s: left + (math.log10(s) - lo) / (hi - lo) * (W - left - right)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart">']
    for t in (1, 3, 10, 30, 100, 300):
        out.append(f'<line x1="{x(t):.1f}" y1="4" x2="{x(t):.1f}" y2="{H-24}" class="grid"/>'
                   f'<text x="{x(t):.1f}" y="{H-8}" class="ax" text-anchor="middle">{t} s</text>')
    for i, k in enumerate(order):
        s, y = net["scen"][k], 8 + i * row
        mid = y + 10
        out.append(f'<text x="{left-10}" y="{mid+4}" class="lab" text-anchor="end">{e(NICE[k])}</text>')
        out.append(f'<rect x="{left}" y="{y+2}" width="{x(s["duration_s_median"])-left:.1f}" height="16" rx="3" class="bar"/>')
        out.append(f'<line x1="{x(s["duration_s_min"]):.1f}" y1="{mid}" x2="{x(s["duration_s_max"]):.1f}" y2="{mid}" class="whisk"/>'
                   f'<line x1="{x(s["duration_s_min"]):.1f}" y1="{mid-4}" x2="{x(s["duration_s_min"]):.1f}" y2="{mid+4}" class="whisk"/>'
                   f'<line x1="{x(s["duration_s_max"]):.1f}" y1="{mid-4}" x2="{x(s["duration_s_max"]):.1f}" y2="{mid+4}" class="whisk"/>')
        med = s["duration_s_median"]
        out.append(f'<text x="{x(s["duration_s_max"])+6:.1f}" y="{mid+4}" class="val">{med:.3g} s</text>')
        out.append(f'<text x="{W-4}" y="{mid+4}" class="pass" text-anchor="end">{s["hash_verified"]}/{s["runs"]} ✓</text>')
    out.append("</svg>")
    return "".join(out)


def chart_detector(per):
    order = sorted(per, key=lambda t: -per[t]["recall"])
    W, row, left = 640, 38, 150
    H = row * len(order) + 30
    span = W - left - 150
    x = lambda v: left + v * span
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        out.append(f'<line x1="{x(t):.1f}" y1="4" x2="{x(t):.1f}" y2="{H-22}" class="grid"/>'
                   f'<text x="{x(t):.1f}" y="{H-6}" class="ax" text-anchor="middle">{t:g}</text>')
    for i, t in enumerate(order):
        p, y = per[t], 8 + i * row
        mid = y + 10
        out.append(f'<text x="{left-10}" y="{mid+4}" class="lab" text-anchor="end">{e(TYPE_NICE.get(t, t))}</text>')
        out.append(f'<rect x="{left}" y="{y+2}" width="{span:.1f}" height="16" rx="3" class="track"/>'
                   f'<rect x="{left}" y="{y+2}" width="{x(p["recall"])-left:.1f}" height="16" rx="3" class="bar"/>')
        out.append(f'<text x="{x(1)+10:.1f}" y="{mid+4}" class="val"><tspan class="big">{p["recall"]:.2f}</tspan>'
                   f'  {p["found"]}/{p["expected"]} found</text>')
    out.append("</svg>")
    return "".join(out)


def diagram_pipeline():
    boxes = [("Client", "Python uploader or browser page"), ("Chunks", "each with its own SHA-256"),
             ("Server", "keeps only a verified prefix, fsync first"), ("Gate", "whole-file SHA-256 must match"),
             ("Analysis", "validate · decode · detect · 30 FPS"), ("Report", "JSON + HTML, cause per anomaly")]
    W, bw, gap, y, h = 690, 98, 18, 10, 70
    out = [f'<svg viewBox="0 0 {W} 96" class="chart">',
           '<defs><marker id="ar" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M0,0 L8,4 L0,8 z" class="arrowhead"/></marker></defs>']
    for i, (t, s) in enumerate(boxes):
        x0 = 4 + i * (bw + gap)
        cls = "box gate" if t == "Gate" else "box"
        out.append(f'<rect x="{x0}" y="{y}" width="{bw}" height="{h}" rx="8" class="{cls}"/>'
                   f'<text x="{x0+bw/2}" y="{y+24}" class="bt" text-anchor="middle">{t}</text>')
        words, lines, cur = s.split(), [], ""
        for w in words:
            if len(cur + " " + w) > 17 and cur:
                lines.append(cur); cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        for j, ln in enumerate(lines[:3]):
            out.append(f'<text x="{x0+bw/2}" y="{y+41+j*11}" class="bs" text-anchor="middle">{e(ln)}</text>')
        if i < len(boxes) - 1:
            out.append(f'<line x1="{x0+bw+2}" y1="{y+h/2}" x2="{x0+bw+gap-2}" y2="{y+h/2}" class="arrow" marker-end="url(#ar)"/>')
    out.append(f'<text x="{4+3*(bw+gap)+bw/2}" y="{y+h+14}" class="no" text-anchor="middle">no match → REJECTED</text>')
    out.append("</svg>")
    return "".join(out)


def diagram_lanes():
    """File timeline vs browser frame log: a gap in both = capture, a gap only in the file = encoding."""
    W, x0, x1 = 640, 120, 620
    n = 60
    step = (x1 - x0) / n
    cap = range(14, 22)       # missing in file and log
    enc = range(40, 43)       # missing in file only
    out = [f'<svg viewBox="0 0 {W} 128" class="chart">']
    for lane, (label, y) in enumerate((("Video file", 26), ("Browser log", 66))):
        out.append(f'<text x="{x0-12}" y="{y+5}" class="lab" text-anchor="end">{label}</text>')
        for i in range(n):
            gone = i in cap or (lane == 0 and i in enc)
            if not gone:
                out.append(f'<rect x="{x0+i*step:.1f}" y="{y-8}" width="{step*0.62:.1f}" height="16" rx="1.5" class="tick"/>')
    cx0, cx1 = x0 + 14 * step - 2, x0 + 22 * step - 2
    ex0, ex1 = x0 + 40 * step - 2, x0 + 43 * step - 2
    out.append(f'<rect x="{cx0:.1f}" y="10" width="{cx1-cx0:.1f}" height="74" rx="5" class="hl-cap"/>'
               f'<text x="{(cx0+cx1)/2:.1f}" y="104" class="tag cap" text-anchor="middle">gap in both → CAPTURE</text>'
               f'<text x="{(cx0+cx1)/2:.1f}" y="118" class="ax" text-anchor="middle">frames never reached the page</text>')
    out.append(f'<rect x="{ex0:.1f}" y="10" width="{ex1-ex0:.1f}" height="34" rx="5" class="hl-enc"/>'
               f'<text x="{(ex0+ex1)/2:.1f}" y="104" class="tag enc" text-anchor="middle">gap in file only → ENCODING</text>'
               f'<text x="{(ex0+ex1)/2:.1f}" y="118" class="ax" text-anchor="middle">reached the page, not recorded</text>')
    out.append("</svg>")
    return "".join(out)


SHORT = {   # condensed from the scenario descriptions in nettest/runs/summary.json
    "fluctuating": "100 → 60 → 20 → 60 → 20 → 100% at 15, 30, 50, 65, 80% of the file",
    "interruption": "60% link; at 30% every connection is cut and refused for 10 s",
    "network_switch": "100% link drops for 3 s at 40% and returns as a 20% link (client address unchanged)",
    "resets": "60% link; every connection reset (TCP RST) for 2 s at 25, 50, 75%",
    "timeouts": "60% link; data silently dropped for 30 s at 30% and 60%, longer than the 20 s stall timeout",
    "client_restart": "client process SIGKILLed at 40%, restarted 2 s later",
    "server_restart": "server process SIGKILLed at 40%, restarted 3 s later",
}


def scenario_legend(net):
    assert set(SHORT) <= set(net["defs"]), "scenario list changed"
    rows = "".join(f'<li><b>{e(NICE[k])}</b> {e(v)}</li>' for k, v in SHORT.items())
    return f'<ul class="legend">{rows}</ul>'


def sample_finding():
    r = json.loads((ROOT / "docs/samples/mixed_dup_gap.json").read_text(encoding="utf-8"))
    a = next(x for x in r["anomalies"] if x["type"] == "missing_frames")
    return f"""<div class="finding">
      <div class="fh"><span class="ft">{e(a["type"])}</span><span class="chipc">{a["time_start_s"]:.3f} – {a["time_end_s"]:.3f} s</span>
        <span class="chipc">frames {a["frame_index_start"]}–{a["frame_index_end"]}</span><span class="chipc hi">confidence: {e(a["confidence"])}</span></div>
      <div class="fe">“{e(a["evidence"])}”</div>
      <div class="fc">likely cause <b>{e(a["likely_cause"])}</b> · candidates {e(", ".join(a["other_candidates"]))} · ruled out
        <b class="ok-t">{e(", ".join(a["ruled_out"]))}</b> (the hash matched)</div></div>"""


# ---------------------------------------------------------------- page

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
/* One accent (blue) for results; red and amber only where they carry meaning (capture, encoding, failure). */
:root { --ink:#111418; --mut:#4a5160; --soft:#7b8290; --rule:#d9dde3; --faint:#f3f4f6;
        --acc:#1d4ed8; --acc2:#eef2fd; --amb:#b54708; --red:#b42318; --blue:#1d4ed8; }
html, body { margin:0; padding:0; }
body { color:var(--ink); font:9.6pt/1.45 "Segoe UI Variable Text","Segoe UI",Inter,Roboto,sans-serif;
       font-variant-numeric:tabular-nums; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
.page { width:210mm; height:297mm; padding:15mm 15mm 13mm; position:relative; overflow:hidden; break-after:page; }
.page:last-child { break-after:auto; }
.top { display:flex; justify-content:space-between; font-size:7.6pt; color:var(--soft); letter-spacing:.06em;
       text-transform:uppercase; border-bottom:1px solid var(--rule); padding-bottom:5px; margin-bottom:16px; }
.foot { position:absolute; left:15mm; right:15mm; bottom:8mm; display:flex; justify-content:space-between;
        font-size:7.4pt; color:var(--soft); }
h1 { font:750 46pt/1 "Segoe UI Variable Display","Segoe UI",sans-serif; letter-spacing:-.025em; margin:6px 0 10px; }
h2 { font:700 17pt/1.15 "Segoe UI Variable Display","Segoe UI",sans-serif; letter-spacing:-.02em; margin:0 0 4px; }
h2 em { font-style:normal; color:var(--acc); }
h3 { font:650 10pt/1.3 "Segoe UI",sans-serif; margin:18px 0 6px; }
p { margin:0 0 7px; }
.sub { color:var(--mut); font-size:9.8pt; margin:0 0 14px; max-width:165mm; }
.tag { font:600 15pt/1.3 "Segoe UI Variable Display","Segoe UI",sans-serif; letter-spacing:-.01em; margin:0 0 10px; text-wrap:balance; max-width:150mm; }
.who { font-size:9.5pt; font-weight:600; margin:2px 0 18px; }
code, .mono { font-family:"Cascadia Mono",Consolas,"JetBrains Mono",monospace; font-size:8.4pt; }
code { background:var(--faint); border-radius:3px; padding:0 4px; white-space:nowrap; }

/* Key figures: a ruled ledger, not cards. */
.tiles { display:grid; grid-template-columns:repeat(4,1fr); border-top:2px solid var(--ink); margin:10px 0 0; }
.tile { padding:10px 14px 12px; border-left:1px solid var(--rule); }
.tile:first-child { border-left:0; padding-left:0; }
.tile .n { font:700 27pt/1 "Segoe UI Variable Display","Segoe UI",sans-serif; letter-spacing:-.03em; }
.tile .n small { font-size:13pt; color:var(--soft); font-weight:600; margin-left:2px; }
.tile.hero .n { color:var(--acc); }
.tile .l { font-size:8.2pt; color:var(--mut); margin-top:6px; line-height:1.35; }
.minis { display:grid; grid-template-columns:repeat(4,1fr); border-top:1px solid var(--rule); border-bottom:1px solid var(--rule);
         margin-bottom:6px; }
.mini { padding:7px 14px 8px; border-left:1px solid var(--rule); font-size:8.2pt; color:var(--mut); line-height:1.35; }
.mini:first-child { border-left:0; padding-left:0; }
.mini b { font:700 11pt/1 "Segoe UI Variable Display","Segoe UI",sans-serif; color:var(--ink); margin-right:4px; }

.promise { display:grid; grid-template-columns:repeat(3,1fr); gap:18px; margin:6px 0 4px; }
.promise div { border-top:1px solid var(--ink); padding-top:7px; }
.promise div b { display:block; font:700 10.2pt/1.25 "Segoe UI",sans-serif; margin-bottom:3px; }
.promise div span { font-size:8.4pt; color:var(--mut); }
.chart { width:100%; display:block; font-family:"Segoe UI",sans-serif; }
.chart .grid { stroke:#eceef1; stroke-width:1; } .chart .ax { fill:#868d98; font-size:9px; }
.chart .lab { fill:var(--ink); font-size:10.5px; } .chart .val { fill:var(--mut); font-size:10px; }
.chart .big { font-weight:700; font-size:12px; fill:var(--ink); }
.chart .bar { fill:#a9bcf2; } .chart .track { fill:#eef0f3; }
.chart .whisk { stroke:#2b3240; stroke-width:1.2; } .chart .pass { fill:var(--acc); font-weight:700; font-size:10.5px; }
.chart .box { fill:#fff; stroke:var(--ink); stroke-width:1.1; } .chart .gate { fill:var(--acc2); stroke:var(--acc); stroke-width:1.4; }
.chart .bt { font-weight:700; font-size:11.5px; fill:var(--ink); } .chart .bs { font-size:8.6px; fill:var(--mut); }
.chart .arrow { stroke:#8f96a1; stroke-width:1.3; } .chart .arrowhead { fill:#8f96a1; }
.chart .no { fill:var(--red); font-size:9px; font-weight:600; }
.chart .tick { fill:#9aa3b2; } .chart .hl-cap { fill:rgba(180,35,24,.06); stroke:var(--red); stroke-width:1.1; stroke-dasharray:3 2; }
.chart .hl-enc { fill:rgba(181,71,8,.07); stroke:var(--amb); stroke-width:1.1; stroke-dasharray:3 2; }
.chart .tag { font-weight:700; font-size:10px; } .chart .cap { fill:var(--red); } .chart .enc { fill:var(--amb); }
.two { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
.three { display:grid; grid-template-columns:repeat(3,1fr); gap:18px; }
.call { border-top:1px solid var(--rule); padding-top:8px; font-size:8.6pt; color:var(--mut); }
.call b { display:block; font:700 17pt/1.05 "Segoe UI Variable Display","Segoe UI",sans-serif; color:var(--acc); margin-bottom:4px; letter-spacing:-.02em; }
.prof { border-top:2px solid var(--ink); padding-top:7px; }
.prof .s { font:700 18pt/1 "Segoe UI Variable Display","Segoe UI",sans-serif; }
.prof .d { font-size:8.3pt; color:var(--mut); margin-top:4px; }
.steps { counter-reset:s; list-style:none; padding:0; margin:4px 0 0; }
.steps li { counter-increment:s; position:relative; padding:0 0 8px 20px; font-size:9pt; color:var(--ink); }
.steps li::before { content:counter(s); position:absolute; left:0; top:0; color:var(--acc); font:700 9pt/1.45 "Segoe UI",sans-serif; }
.chips { margin:4px 0 0; border-top:1px solid var(--rule); }
.chip { display:block; border-bottom:1px solid var(--rule); padding:4px 0; font-size:8.6pt; color:var(--mut); }
.chip b { color:var(--ink); font-weight:700; }
.rule { font:600 10.2pt/1.4 "Cascadia Mono",Consolas,monospace; border-top:1px solid var(--ink); border-bottom:1px solid var(--ink);
        padding:10px 14px; margin:14px 0 4px; text-align:center; }
table { border-collapse:collapse; width:100%; font-size:8.6pt; }
td, th { text-align:left; padding:5px 6px; border-bottom:1px solid var(--rule); vertical-align:top; }
th { font-size:7.6pt; color:var(--soft); text-transform:uppercase; letter-spacing:.06em; font-weight:600; }
td.v { font-weight:700; white-space:nowrap; } .cap-t { color:var(--red); font-weight:700; } .enc-t { color:var(--amb); font-weight:700; }
.ok-t { color:var(--acc); font-weight:700; }
figure { margin:6px 0 4px; } figure img { width:100%; display:block; border-radius:3px; border:1px solid var(--rule); }
figcaption { font-size:7.8pt; color:var(--soft); margin-top:4px; }
.lim { columns:2; column-gap:18px; font-size:8.4pt; color:var(--mut); padding-left:14px; margin:4px 0 0; }
.lim li { margin:0 0 5px; break-inside:avoid; } .lim b { color:var(--ink); }
.box2 { border-top:1px solid var(--rule); padding-top:7px; }
.cmd { font:8.3pt/1.7 "Cascadia Mono",Consolas,monospace; background:var(--faint); color:var(--ink); border-radius:3px; padding:9px 12px; }
.cmd span { color:var(--soft); }
table.check { border-top:1px solid var(--rule); }
table.check td { font-size:8.7pt; padding:6px 6px; } table.check td:nth-child(2) { font-weight:600; color:var(--ink); }
table.check td:nth-child(3) { color:var(--mut); } .ck { color:var(--acc); font-weight:800; width:14px; }
.pg { color:var(--soft); white-space:nowrap; text-align:right; }
.seq { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
.legend { columns:2; column-gap:18px; padding:0; margin:2px 0 0; list-style:none; font-size:8.2pt; color:var(--mut); }
.legend li { break-inside:avoid; margin:0 0 5px; } .legend b { color:var(--ink); display:block; font-size:8.6pt; }
.finding { border:1px solid var(--rule); border-radius:4px; padding:11px 13px; }
.fh { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:7px; }
.ft { font:700 10.5pt "Cascadia Mono",Consolas,monospace; margin-right:4px; }
.chipc { font:600 8.2pt "Cascadia Mono",Consolas,monospace; background:var(--faint); border-radius:3px; padding:2px 7px; }
.chipc.hi { background:var(--acc2); color:var(--acc); }
.fe { font:9pt/1.45 "Cascadia Mono",Consolas,monospace; color:var(--ink); margin-bottom:6px; }
.fc { font-size:8.5pt; color:var(--mut); }
.seq div { border-top:2px solid var(--rule); padding-top:7px; font-size:8.5pt; color:var(--mut); }
.seq div.ok { border-top-color:var(--acc); }
.seq b { display:block; color:var(--ink); font-size:10.5pt; margin:1px 0 3px; }
.seq span { font:700 8pt/1 "Segoe UI",sans-serif; color:var(--acc); }
"""


def build(repo):
    net = load_network()
    per, det = load_detector()
    tests = count_tests()
    assert net["ok"] == net["runs"] == net["hash"], "network summary changed"
    prof = net["profiles"]
    repo_html = f'<a href="{e(repo)}" style="color:var(--blue);text-decoration:none">{e(repo.removeprefix("https://"))}</a>' if repo \
        else "repository: link in the submission email"
    top = lambda left: f'<div class="top"><span>{left}</span><span>nSEPIA technical challenge · Confluentia 2026</span></div>'
    foot = lambda n: f'<div class="foot"><span>Intact · {e(AUTHOR)}</span><span>{n} / 6</span></div>'
    s20 = net["scen"]["stable_20"]
    valid_pct = round(100 * det["valid_ok"] / det["videos"])

    p1 = f"""
<section class="page">
  {top("Reliable video upload &amp; frame integrity detection")}
  <h1>Intact</h1>
  <p class="tag">A 30 s video over a 20–100% network, accepted only when every byte matches.</p>
  <div class="who">{e(AUTHOR)}</div>
  <p class="sub">The backend checks the whole-file SHA-256 before it touches the video, then decodes every frame, finds
  missing, duplicated and damaged frames at 30 FPS, and says whether the evidence points to transfer, capture or
  encoding.</p>

  <div class="tiles">
    <div class="tile hero"><div class="n">{net["ok"]}<small>/{net["runs"]}</small></div><div class="l">uploads finished intact under 10 bad-network scenarios, SHA-256 matched every time</div></div>
    <div class="tile ok"><div class="n">{det["recall"]:.3f}</div><div class="l">recall: share of {det["expected_events"]} known faults found in {det["videos"]} held-out videos</div></div>
    <div class="tile ok"><div class="n">{det["precision"]:.3f}</div><div class="l">precision: {det["false_positives"]} false alarm in {det["detections"]} detections</div></div>
    <div class="tile"><div class="n">{tests}</div><div class="l">automated tests, one command: <code>pytest -q</code></div></div>
  </div>
  <div class="minis">
    <div class="mini"><b>{net["faults"]}</b>faults injected mid-transfer</div>
    <div class="mini"><b>0</b>damaged or partial files accepted ({REJECT_TESTS} tests)</div>
    <div class="mini"><b>{det["fp_controls"]}</b>false alarms on {det["controls"]} clean videos</div>
    <div class="mini"><b>5</b>real browser recordings, incl. iPhone</div>
  </div>

  <h3>Three rules the system never breaks</h3>
  <div class="promise">
    <div><b>Accept only intact files</b><span>COMPLETE only when the server's SHA-256 of the whole file equals the client's</span></div>
    <div><b>Analyse only accepted files</b><span>the analysis can open a file only through a check that refuses anything else</span></div>
    <div><b>Never guess the cause</b><span>no evidence → "cannot determine", never "no drops"</span></div>
  </div>

  <h3>What is in the repository</h3>
  <div class="three">
    <div class="box2"><b>Code</b><br><span style="color:var(--mut);font-size:8.4pt">Python uploader, browser recording page, FastAPI backend, analysis pipeline</span></div>
    <div class="box2"><b>Evidence</b><br><span style="color:var(--mut);font-size:8.4pt">raw logs of all {net["runs"]} network runs, 120 scored videos, 5 browser runs</span></div>
    <div class="box2"><b>Reports</b><br><span style="color:var(--mut);font-size:8.4pt">sample integrity reports (HTML + JSON), design notes, limitations, demo script</span></div>
  </div>
  <h3>Evidence the brief asks for, and where it is</h3>
  <table class="check">
    <tr><td class="ck">✓</td><td>Stable connection and variable signal (20%–100%)</td><td>15 stable + 5 fluctuating runs, all verified</td><td class="pg">p. 3</td></tr>
    <tr><td class="ck">✓</td><td>Temporary interruption, timeout and reconnection</td><td>outage, resets, hangs, client and server kills: 25 runs, all verified</td><td class="pg">p. 3</td></tr>
    <tr><td class="ck">✓</td><td>Connection switching or fluctuating speeds</td><td>5 switch + 5 fluctuating runs (emulated; see limits)</td><td class="pg">p. 3, 6</td></tr>
    <tr><td class="ck">✓</td><td>Altered, truncated or invalid video</td><td>120 held-out videos scored, 3 samples end to end</td><td class="pg">p. 4, 6</td></tr>
    <tr><td class="ck">✓</td><td>Architecture, README and run instructions</td><td>pipeline, states, commands; README in the repository</td><td class="pg">p. 2, 6</td></tr>
    <tr><td class="ck">✓</td><td>Sample integrity report and limitations</td><td>HTML + JSON reports; limits stated plainly</td><td class="pg">p. 6</td></tr>
  </table>
  <p style="margin-top:10px;font-size:8.6pt;color:var(--mut)">{repo_html}. Every number in this document is read from a file there.</p>
  {foot(1)}
</section>"""

    p2 = f"""
<section class="page">
  {top("1 · How it works")}
  <h2>One recovery rule: <em>ask the server, continue from there</em></h2>
  <p class="sub">The upload is cut into chunks. The server keeps only a contiguous, verified prefix of the file, so after any
  failure the right place to continue is simply the number of bytes it holds.</p>
  {diagram_pipeline()}
  <div class="two" style="margin-top:12px">
    <div>
      <h3>An upload, step by step</h3>
      <ol class="steps">
        <li><b>Open a session.</b> The client declares the file size and its SHA-256.</li>
        <li><b>Send chunks.</b> Each goes to a byte offset with its own SHA-256. A damaged chunk is refused; an identical re-sent chunk changes nothing.</li>
        <li><b>Store safely.</b> The server writes the chunk, calls fsync, and only then records the new offset in SQLite, so the recorded offset is never ahead of the disk.</li>
        <li><b>Recover.</b> Lost network, timeout, client crash or server crash: the client asks for the offset and continues.</li>
        <li><b>Finalize.</b> The server re-reads and re-hashes the whole file. Only a match gives COMPLETE; analysis starts automatically.</li>
      </ol>
    </div>
    <div>
      <h3>Behaviour on a bad link</h3>
      <div class="chips">
        <span class="chip">chunk size <b>64 KB – 8 MB</b>, doubles after a success, halves after a failure</span>
        <span class="chip">retry: exponential backoff, full jitter, cap <b>30 s</b></span>
        <span class="chip">no progress for <b>20 s</b> → drop the connection, retry</span>
        <span class="chip">up to <b>15</b> failures in a row before giving up</span>
      </div>
      <h3>Server states</h3>
      <table>
        <tr><td class="v">UPLOADING</td><td>chunks arriving</td></tr>
        <tr><td class="v" style="color:var(--amb)">STALLED</td><td>no completed chunk for 30 s: a timer, not a verdict</td></tr>
        <tr><td class="v" style="color:var(--red)">FAILED</td><td>no chunk for 24 h: session closed</td></tr>
        <tr><td class="v ok-t">COMPLETE</td><td>whole-file SHA-256 matches</td></tr>
        <tr><td class="v" style="color:var(--red)">REJECTED</td><td>assembled file does not match: never analysed</td></tr>
      </table>
    </div>
  </div>
  <div class="rule">COMPLETE ⇔ SHA-256(file on server disk) = SHA-256(file the client declared)</div>
  <h3>A real recovery, from the raw log (interruption scenario, run 1)</h3>
  <div class="seq">
    <div><span>1</span><b>Send</b>chunk at byte <code>1,310,720</code> (512 KB)</div>
    <div><span>2</span><b>Cut</b>the server stores it; the connection drops before the reply</div>
    <div><span>3</span><b>Ask</b>client retries: "how many bytes?" → <code>1,835,008</code></div>
    <div class="ok"><span>4</span><b>Continue</b>from <code>1,835,008</code>. Nothing sent twice</div>
  </div>
  {foot(2)}
</section>"""

    def pcard(k):
        p = prof[k]
        rate = f'{p["rate_kbit"]/1000:g} Mbit/s' if p["rate_kbit"] >= 1000 else f'{p["rate_kbit"]} kbit/s'
        return f'<div class="prof"><div class="s">{k}%</div><div class="d">{rate} · {p["rtt_ms"]} ms RTT · {p["loss_pct"]}% loss</div></div>'

    p3 = f"""
<section class="page">
  {top("2 · Transfer under bad networks")}
  <h2><em>{net["ok"]} of {net["runs"]}</em> uploads arrived byte-perfect</h2>
  <p class="sub">Run on a separate Linux laptop: netem shapes a private virtual link in both directions, Toxiproxy cuts,
  resets and hangs connections. Each fault fires when the client's own log shows a set fraction of the file sent, so it
  always lands mid-transfer. Test video {net["video_bytes"]:,} bytes, chunks up to {net["chunk_kb"]} KB.</p>
  <div class="three" style="margin-bottom:6px">{pcard("100")}{pcard("60")}{pcard("20")}</div>
  <p style="font-size:8.2pt;color:var(--soft)">Measured before the runs: ping {PING_100} ms at 100%, {PING_20} ms at 20%.</p>
  <h3>Upload time per scenario: median of 5 runs, whiskers min–max (log scale)</h3>
  {chart_network(net)}
  <div class="three" style="margin-top:12px">
    <div class="call"><b>{LOST_ACKS}</b>times a chunk arrived but its acknowledgement was lost. The client asked, skipped ahead, and never sent that chunk twice.</div>
    <div class="call"><b>≤ {MAX_RESENT_AFTER_CRASH//1024} KB</b>re-sent after the server was killed (SIGKILL) mid-upload and restarted, over 5 runs.</div>
    <div class="call"><b>{REAL_RATE_AT_20} kbit/s</b>is what the 20% link really carries (5% loss, 400 ms). Every upload still completed, in {s20["duration_s_min"]:.0f}–{s20["duration_s_max"]:.0f}&nbsp;s.</div>
  </div>
  <p style="margin-top:10px;font-size:8.6pt;color:var(--mut)">Checked separately from the harness: in every run the acknowledged chunks plus the server's resume
  offsets cover exactly bytes 0 to {net["video_bytes"]:,}. {net["retries"]} retries in total, 0 harness errors.</p>
  <h3>What the fault scenarios do</h3>
  {scenario_legend(net)}
  {foot(3)}
</section>"""

    p4 = f"""
<section class="page">
  {top("3 · Frame integrity analysis")}
  <h2>Found <em>{det["found"]} of {det["expected_events"]}</em> known faults; <em>{det["false_positives"]}</em> false alarm</h2>
  <p class="sub">24 kinds of faulty 30 s video with known ground truth. Thresholds were tuned on seed 1, the code frozen,
  then seeds 2–6 ({det["videos"]} new videos) scored once. Every miss is listed in the repository.</p>
  <div class="tiles">
    <div class="tile hero"><div class="n">{det["recall"]:.3f}</div><div class="l">recall</div></div>
    <div class="tile hero"><div class="n">{det["precision"]:.3f}</div><div class="l">precision</div></div>
    <div class="tile ok"><div class="n">{valid_pct}<small>%</small></div><div class="l">of videos judged valid / invalid correctly</div></div>
    <div class="tile ok"><div class="n">{det["fp_controls"]}</div><div class="l">false alarms on {det["controls"]} clean control videos</div></div>
  </div>
  <h3>Recall by anomaly type</h3>
  {chart_detector(per)}
  <div class="two" style="margin-top:10px">
    <div>
      <h3>How a file is checked</h3>
      <ol class="steps">
        <li><b>Validate:</b> ffprobe reads the container and streams.</li>
        <li><b>Decode everything:</b> PyAV decodes every frame and records every decoder message; the ffmpeg CLI decodes again as an independent check.</li>
        <li><b>Detect on real timestamps:</b> gaps, repeats, jitter, damage, truncation; each with time, frame indices, evidence, confidence.</li>
        <li><b>Then 30 FPS:</b> map each slot to a source frame; repeats made by that conversion are labelled artefacts, not defects.</li>
      </ol>
    </div>
    <div>
      <h3>What it misses, and why</h3>
      <table>
        <tr><td class="v">6</td><td>byte flips that decode without any error and leave no visible trace (damage in transit is caught by the hash)</td></tr>
        <tr><td class="v">4</td><td>frames dropped with re-generated timestamps: no gap left, only a motion jump</td></tr>
        <tr><td class="v">3</td><td>duplicates in near-still scenes, where a repeat looks like no motion</td></tr>
        <tr><td class="v">2</td><td>timing jitter just under the 25% threshold</td></tr>
      </table>
    </div>
  </div>
  <h3>What one finding looks like (from the sample report)</h3>
  {sample_finding()}
  {foot(4)}
</section>"""

    p5 = f"""
<section class="page">
  {top("4 · Transfer, capture or encoding")}
  <h2>A matching hash rules out the network. <em>The frame log tells capture from encoding.</em></h2>
  <p class="sub">The browser page logs every frame that reaches it (<code>requestVideoFrameCallback</code>) and uploads the log
  with its own hash. The log is aligned to the file by a time search, and used only when the frame pattern or a shared gap
  pins the offset down; otherwise the report says the alignment is ambiguous.</p>
  {diagram_lanes()}
  <h3>Found in real recordings</h3>
  <table>
    <tr><th>Run</th><th>Evidence</th><th>Verdict</th></tr>
    <tr><td>Webcam, desktop Chrome</td><td><b>3.3 s</b> gap (102 frames) at 0.30–3.60 s, in the file <b>and</b> the log</td><td class="cap-t">capture</td></tr>
    <tr><td>Webcam, desktop Chrome</td><td><b>2</b> frames shown in the page but missing from the file</td><td class="enc-t">encoding</td></tr>
    <tr><td>Injected 0.5 s source stall</td><td>file gap 10.046–10.575 s; log gap <b>529.5 ms</b> with no frames inside</td><td class="cap-t">capture</td></tr>
    <tr><td>iPhone, Safari</td><td><b>899/899</b> frames aligned, <b>0</b> delivery gaps; recorder started in <b>3 ms</b> (Chrome: 1.5–3.8 s)</td><td class="ok-t">no drops</td></tr>
  </table>
  <h3 style="margin-top:14px">The recording page</h3>
  <figure><img src="capture-page.png" alt="Capture page">
  <figcaption>Record 30 s, watch it upload in verified pieces, read the verdict. Animations stop while recording and
  uploading so they never compete with the frame log.</figcaption></figure>
  {foot(5)}
</section>"""

    p6 = f"""
<section class="page">
  {top("5 · Sample report and limits")}
  <h2>Both planted faults found, <em>at the right frames</em></h2>
  <p class="sub">A 30 s video with frame 47 repeated twice and frames 356–361 removed, uploaded through the system. No
  capture log exists for this file, so the cause stays <i>undetermined</i> rather than guessed.</p>
  <figure><img src="sample-report.png" alt="Sample integrity report">
  <figcaption>docs/samples/mixed_dup_gap.html. Also in the samples: a file cut to about half (VALID_WITH_ERRORS,
  truncation located at 15.33 s) and a text file named .mp4 (INVALID).</figcaption></figure>
  <h3>Limits, stated plainly</h3>
  <ul class="lim">
    <li><b>A perfect transfer does not prove a clean recording.</b> Frames dropped before encoding with new timestamps leave no gap.</li>
    <li><b>The frame log is written by the client:</b> its integrity is checked, its authenticity cannot be. Resolution about 17 ms.</li>
    <li><b>Detector thresholds are fixed;</b> near-still scenes and silent byte flips are its known misses.</li>
    <li><b>Network conditions were emulated.</b> I did this alone during end-semester exams, which left no time for a real
    mobile-network or real connection-switch test. Next test: server on a second computer, both on one router, the laptop
    switching between its 2.4 and 5 GHz networks mid-upload so its address really changes. Pass: COMPLETE, hashes match,
    at most one chunk re-sent.</li>
    <li>Not tested: Firefox, the browser client under netem, resuming after a page reload. No authentication.</li>
  </ul>
  <h3>Run it</h3>
  <div class="cmd"><span>$</span> pip install -r requirements.txt &nbsp;&nbsp;<span># Python 3.12/3.13, FFmpeg on PATH</span><br>
  <span>$</span> python -m pytest -q &nbsp;&nbsp;<span># {tests} tests</span><br>
  <span>$</span> uvicorn server.app:app --port 8000 &nbsp;&nbsp;<span># then open http://127.0.0.1:8000/capture</span><br>
  <span>$</span> python -m client.uploader video.mp4 --server http://127.0.0.1:8000</div>
  <p style="margin-top:8px;font-size:7.8pt;color:var(--soft)">Two WebGL effects on the recording page are ports of React Bits
  components (MIT + Commons Clause; licence file in server/static/).</p>
  {foot(6)}
</section>"""

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Intact – {e(AUTHOR)}</title>
<!-- Generated by docs/submission/build.py; edit that file, not this one. -->
<style>{CSS}</style></head>
<body>{p1}{p2}{p3}{p4}{p5}{p6}</body></html>"""
    OUT_HTML.write_text(doc, encoding="utf-8", newline="\n")
    chrome = next((c for c in CHROME if Path(c).exists() or subprocess.run(["where" if sys.platform == "win32" else "which", c], capture_output=True).returncode == 0), None)
    if not chrome:
        raise SystemExit("Chrome not found")
    subprocess.run([chrome, "--headless=new", "--no-pdf-header-footer", f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
                   check=True, capture_output=True)
    print(f"wrote {OUT_HTML.relative_to(ROOT)} and {OUT_PDF.relative_to(ROOT)} ({tests} tests, "
          f"{net['ok']}/{net['runs']} runs, recall {det['recall']:.3f}, precision {det['precision']:.3f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="", help="repository URL to print on the cover")
    build(ap.parse_args().repo)
