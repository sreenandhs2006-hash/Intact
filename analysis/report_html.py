"""Render the analysis report dict as a single self-contained HTML page."""
import html
import json

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1b;--muted:#6b6b66;--line:#e3e3de;
--ok:#1f7a3d;--warn:#a86400;--bad:#b3261e;--info:#1f5fa8;--art:#8a8a84}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#201f1d;--text:#ecebe6;--muted:#a3a29b;
--line:#34332f;--ok:#5cc47f;--warn:#e0a446;--bad:#f07b72;--info:#7fb0ec;--art:#77766f}}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.k{font-size:12px;color:var(--muted)}.v{font-size:18px;font-weight:600}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}code{font-size:12px;word-break:break-all}
svg text{fill:var(--muted);font-size:10px}
li{margin:4px 0}
"""

STATUS_CLASS = {"VALID": "ok", "VALID_WITH_ERRORS": "warn", "INVALID": "bad"}
CONF_CLASS = {"high": "bad", "medium": "warn", "low": "muted"}


def e(x):
    return html.escape("" if x is None else str(x))


def fmt_t(t):
    return "–" if t is None else f"{t:.3f}s"


def interval_chart(frames, anomalies, nominal_ms):
    pts = [(f["index"], f["pts_s"]) for f in frames if f["pts_s"] is not None]
    if len(pts) < 3 or not nominal_ms:
        return "<p class='muted'>Not enough timestamps to chart.</p>"
    W, H, pad = 960, 170, 30
    ymax = nominal_ms * 3
    n = pts[-1][0] or 1
    x = lambda i: pad + (W - 2 * pad) * i / n
    y = lambda ms: H - pad - (H - 2 * pad) * min(ms, ymax) / ymax
    path = " ".join(f"{'M' if k == 0 else 'L'}{x(b[0]):.1f},{y((b[1]-a[1])*1000):.1f}"
                    for k, (a, b) in enumerate(zip(pts, pts[1:])))
    marks = "".join(
        f"<line x1='{x(a['frame_index_start']):.1f}' x2='{x(a['frame_index_start']):.1f}' y1='{pad-8}' y2='{H-pad}'"
        f" stroke='var(--bad)' stroke-opacity='.35'><title>{e(a['id'])} {e(a['type'])}</title></line>"
        for a in anomalies if a.get("frame_index_start") is not None)
    return (f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' aria-label='frame interval chart'>"
            f"<line x1='{pad}' x2='{W-pad}' y1='{y(nominal_ms):.1f}' y2='{y(nominal_ms):.1f}' stroke='var(--ok)' stroke-dasharray='4 3'/>"
            f"<text x='{pad}' y='{y(nominal_ms)-4:.1f}'>nominal {nominal_ms:.2f} ms</text>"
            f"<text x='{pad}' y='{pad-12}'>{ymax:.0f} ms (clipped)</text><text x='{pad}' y='{H-8}'>frame 0</text>"
            f"<text x='{W-pad-60}' y='{H-8}'>frame {n}</text>{marks}"
            f"<path d='{path}' fill='none' stroke='var(--info)' stroke-width='1.2'/></svg>")


def timeline_strip(tl):
    slots = tl.get("slots") or []
    if not slots:
        return ""
    W = 960
    w = W / len(slots)
    colour = {"original": "var(--ok)", "conversion_duplicate": "var(--art)", "gap_fill": "var(--bad)"}
    rects = "".join(f"<rect x='{s['index']*w:.2f}' y='0' width='{max(w,0.6):.2f}' height='18' fill='{colour[s['kind']]}'/>"
                    for s in slots if s["kind"] != "original")
    return (f"<svg viewBox='0 0 {W} 18' width='100%' height='18' preserveAspectRatio='none'>"
            f"<rect width='{W}' height='18' fill='var(--ok)' fill-opacity='.25'/>{rects}</svg>"
            "<p class='k'>green: original source frame · grey: conversion duplicate (artefact) · "
            "red: slot filling a source timestamp gap</p>")


def capture_section(ce):
    if not ce or not ce.get("present"):
        return f"<div class='card muted'>{e((ce or {}).get('note', 'No capture log.'))}</div>"
    if not ce.get("usable"):
        return f"<div class='card warn'>Capture log present but not usable: {e(ce.get('reason'))}</div>"
    gaps = "".join(f"<li>{g['t0_ms']:.1f}–{g['t1_ms']:.1f} ms (page clock): {g['interval_ms']} ms, ~{g['estimated_missing']} frame(s)</li>"
                   for g in ce["delivery_gaps"][:50]) or "<li class='muted'>none</li>"
    faults = "".join(f"<li>{e(f)}</li>" for f in ce.get("simulated_faults") or [])
    return f"""<div class="card">
 <div class="grid">
  <div><div class="k">Source</div><div class="v">{e(ce.get('source'))}</div><div class="k">{e(ce.get('mime_type'))}</div></div>
  <div><div class="k">Time base</div><div class="v">{e(ce['time_base'])}</div></div>
  <div><div class="k">Coverage of recording</div><div class="v">{ce['coverage']:.1%}</div></div>
  <div><div class="k">Logged FPS (median)</div><div class="v">{e(ce['measured_fps'])}</div></div>
  <div><div class="k">Frames presented / in file</div><div class="v">{e(ce['presented_frames_in_recording'])} / {e(ce.get('file_frames'))}</div></div>
  <div><div class="k">Missed callbacks</div><div class="v">{e(ce['callbacks_missed'])}</div></div>
 </div>
 <p>Recording ran {e(ce.get('recording_duration_s'))} s; log spans {e(ce.get('log_span_s'))} s; file spans {e(ce.get('file_span_s'))} s.
 Verdicts per anomaly: {e(', '.join(f'{k}: {n}' for k, n in (ce.get('anomaly_verdicts') or {}).items()) or 'none')}.</p>
 <p class="k">Delivery gaps (no new frame reached the page)</p><ul>{gaps}</ul>
 {f"<p class='k warn'>Simulated faults injected by the test-pattern source (test aid, not a real camera):</p><ul>{faults}</ul>" if faults else ""}
 <p class="k">What this log can prove</p><ul>{''.join(f'<li>{e(x)}</li>' for x in ce['can_prove'])}</ul>
 <p class="k">What it cannot prove</p><ul>{''.join(f'<li>{e(x)}</li>' for x in ce['cannot_prove'])}</ul>
</div>"""


def render(r):
    s = r["summary"]
    v = r["validation"]
    st = r["source_timing"]
    tl = r["timeline_30fps"]
    tv = r["tool_versions"]
    rows = "".join(
        f"<tr><td>{e(a['id'])}</td><td>{e(a['type'])}</td><td>{fmt_t(a['time_start_s'])} – {fmt_t(a['time_end_s'])}"
        f"<div class='k'>frames {e(a['frame_index_start'])}–{e(a['frame_index_end'])}</div></td>"
        f"<td>{e(a['evidence'])}</td><td class='{CONF_CLASS.get(a['confidence'],'')}'>{e(a['confidence'])}</td>"
        f"<td><b>{e(a['likely_cause'])}</b><div class='k'>candidates: {e(', '.join(a['other_candidates']) or '–')};"
        f" ruled out: {e(', '.join(a['ruled_out']) or '–')}</div><div class='k'>{e(a['cause_reasoning'])}</div>"
        + (f"<div class='k'>capture log: <b>{e(a['capture_evidence']['verdict'])}</b></div>" if a.get('capture_evidence') else "")
        + "</td></tr>"
        for a in r["anomalies"]) or "<tr><td colspan='6' class='muted'>No anomalies detected.</td></tr>"
    errs = "".join(f"<li><code>{e(x.get('packet_time_s'))}</code> {e(x['kind'])}: {e(x['message'])}</li>"
                   for x in v["decode"]["errors"][:50])
    cli = "".join(f"<li><code>{e(x)}</code></li>" for x in v["ffmpeg_cli_decode"]["errors"][:30])
    probe_errs = "".join(f"<li><code>{e(x)}</code></li>" for x in v["ffprobe"]["errors"][:30])
    vid = v["ffprobe"].get("video") or {}
    tr = r["transfer"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Integrity Report</title><style>{CSS}</style></head>
<body><main>
<h1>Video integrity report</h1>
<div class="muted">{e(r['input']['file'])} · {r['input']['size_bytes']:,} bytes · generated {e(r['generated_at'])}</div>

<div class="grid" style="margin-top:14px">
 <div class="card"><div class="k">Transfer</div><div class="v {'ok' if r['transfer_verified'] else 'warn'}">{e(s['transfer'])}</div></div>
 <div class="card"><div class="k">Validation</div><div class="v {STATUS_CLASS.get(v['status'],'')}">{e(v['status'])}</div></div>
 <div class="card"><div class="k">Anomalies</div><div class="v">{s['anomalies_total']}</div>
   <div class="k">{e(', '.join(f'{k}: {n}' for k, n in s['anomaly_counts'].items()) or 'none')}</div></div>
 <div class="card"><div class="k">Frames decoded</div><div class="v">{v['decode']['frames_decoded']}</div>
   <div class="k">packets {v['decode']['packets']} · decode errors {v['decode']['error_count']}</div></div>
</div>

<div class="card"><b>Dropped frames in the original recording:</b> {e(s['dropped_frames_in_original_recording'])}</div>

<h2>Anomalies</h2>
<div class="card scroll"><table><tr><th>ID</th><th>Type</th><th>Location</th><th>Evidence</th><th>Confidence</th><th>Likely cause</th></tr>{rows}</table></div>

<h2>Capture evidence (browser frame log)</h2>
{capture_section(r.get('capture_evidence'))}

<h2>Source timestamps (before 30 FPS conversion)</h2>
<div class="card">
 <div class="grid">
  <div><div class="k">Header FPS</div><div class="v">{e(st.get('header_fps'))}</div></div>
  <div><div class="k">Measured FPS (median interval)</div><div class="v">{e(st.get('measured_fps'))}</div></div>
  <div><div class="k">Interval min / max</div><div class="v">{e(st.get('interval_min_ms'))} / {e(st.get('interval_max_ms'))} ms</div></div>
  <div><div class="k">Interval CV</div><div class="v">{e(st.get('interval_cv'))}</div></div>
 </div>
 <p class="k">Interval between consecutive frames, per frame. Red lines mark anomalies.</p>
 {interval_chart(r['frames'], r['anomalies'], st.get('median_interval_ms'))}
</div>

<h2>30 FPS timeline</h2>
<div class="card">
 <p>{tl.get('slot_count')} slots · rule: {e(tl.get('rule'))}</p>
 {timeline_strip(tl)}
 <p>Conversion duplicates: <b>{tl.get('conversion_duplicates')}</b> · conversion omissions: <b>{tl.get('conversion_omissions')}</b>
 · gap-fill slots: <b>{tl.get('gap_fill_slots')}</b>. Conversion duplicates and omissions are artefacts of resampling, not defects of the source.</p>
</div>

<h2>Validation evidence</h2>
<div class="card">
 <p>Container <code>{e((v['ffprobe'].get('format') or {}).get('format_name'))}</code> · codec <code>{e(vid.get('codec'))}</code>
 {e(vid.get('width'))}×{e(vid.get('height'))} · declared frames {e(vid.get('declared_frames'))} · declared duration {e(vid.get('declared_duration_s'))}s</p>
 <p class="k">ffprobe errors</p><ul>{probe_errs or '<li class="muted">none</li>'}</ul>
 <p class="k">PyAV decoder errors (first 50 of {v['decode']['error_count']})</p><ul>{errs or '<li class="muted">none</li>'}</ul>
 <p class="k">Independent ffmpeg CLI decode ({v['ffmpeg_cli_decode']['error_lines']} error lines)</p><ul>{cli or '<li class="muted">none</li>'}</ul>
</div>

<h2>Transfer</h2>
<div class="card scroll"><pre>{e(json.dumps(tr, indent=2))}</pre></div>

<h2>Limitations</h2>
<div class="card"><ul>{''.join(f'<li>{e(x)}</li>' for x in r['limitations'])}</ul></div>

<h2>Tool versions</h2>
<div class="card scroll"><table>{''.join(f'<tr><td>{e(k)}</td><td><code>{e(val)}</code></td></tr>' for k, val in tv.items())}</table>
<p class="k">Analysis took {e(r['analysis_seconds'])}s.</p></div>
</main></body></html>"""
