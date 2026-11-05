# Reliable Video Upload & Frame Integrity Detection

Confluentia 2026 (IIT BHU) · nSEPIA technical challenge. Full README arrives in M6; this covers what is built so far.

## Status

| Milestone | State |
|---|---|
| M1 Reliable transfer | done |
| M2 Integrity analysis | done |
| M3 Known-fault test set | done: held-out recall 0.933, precision 0.995 ([results](testset/results/HELDOUT.md)) |
| M4 Network tests | – |
| M5 Browser capture | – |
| M6 Submission | – |

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows (Git Bash); on Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn server.app:app --port 8000          # status page: http://127.0.0.1:8000/
python -m client.uploader path/to/video.mp4 --log upload.jsonl
python -m analysis.analyze path/to/video.mp4 --out reports/   # analyse a local file
```

After an upload reaches COMPLETE the server analyses it automatically; the status page links the
HTML/JSON report (`/uploads/{id}/report.html`). FFmpeg/ffprobe must be on PATH.

Server data goes to `~/.nihilent-vi/data` (override with `VI_DATA_DIR`).

## Test everything

```bash
python -m pytest -q
```

## Known-fault test set and detector score

```bash
python -m testset.generate --out ~/.nihilent-vi/testset/seed2 --seed 2     # 24 videos + expected results
python -m testset.score --set ~/.nihilent-vi/testset/seed2 --out testset/results/seed2-heldout
python -m testset.summary testset/results/seed*-heldout --out testset/results/HELDOUT.md
```

## M1 design in one paragraph

The client creates a session declaring the file's size and SHA-256, then sends chunks
sequentially, each addressed by byte offset and carrying its own SHA-256. The server
rejects damaged chunks, treats a re-sent identical chunk as a no-op, and only extends a
contiguous verified prefix (`received_bytes`), fsyncing the bytes before recording them
in SQLite. Resuming after any crash is "ask the server for `received_bytes` and continue".
`finalize` re-reads the whole file from disk; only a matching SHA-256 yields `COMPLETE`,
anything else is `REJECTED`. Idle sessions become `STALLED` (resumable) and later `FAILED`
(terminal). Analysis code can only open a file through `uploads.verified_file()`, which
refuses anything that is not `COMPLETE`.

## M2 design in one paragraph

ffprobe validates the container and stream; PyAV decodes every frame single-threaded, capturing every
FFmpeg message per packet; the ffmpeg CLI decodes again as an independent check. Detection runs on the
ORIGINAL timestamps first: gaps (interval > 1.5x the median interval), repeated or backwards timestamps,
irregular intervals (VFR). Content checks on 160x90 grayscale thumbnails add duplicated frames (identical
picture inside motion) and possible skipped frames (motion jump with regular timestamps, low confidence).
Only then is a 30 FPS timeline built ("slot k shows the latest frame with pts <= k/30"); slots that repeat
a frame are labelled conversion duplicates, or gap-fill when they cover a source gap - artefacts, not defects.
Each anomaly has evidence, confidence, a likely cause with candidates and what is ruled out (transfer is
ruled out only when the SHA-256 was verified). Regular timestamps never produce "no drops": the report
says "cannot determine" without a capture log.

## M3 design in one paragraph

`testset/generate.py` builds 24 videos per seed: controls (clean synthetic, clean Mandelbrot zoom, flat static,
noisy static, 25 fps source), removed frames with and without re-timing, duplicated frames, mixed faults,
whole-file and burst VFR, flipped bytes, a zeroed block, truncation with and without a usable index, and three
fake files. Ground truth comes from the FFmpeg recipe (frame indices) or from ffprobe's packet table of the clean
source (byte position -> packet -> time), never from the detector; each video gets a `.expected.json`.
`testset/score.py` matches detections to expected events by identical type within ±200 ms and reports precision,
recall, timestamp error, count error, false positives (also on control videos only) and validation accuracy.
Seed 1 was the development set: its untouched baseline is in `testset/results/seed1-baseline` (recall 0.957,
precision 0.722). Fixes were rules, not threshold changes, and two generator ground-truth errors were found and
verified on raw FFmpeg output. The code was then frozen and seeds 2-6 (seed 6 at 30 s) scored once:
recall 0.933, precision 0.995, 0 false positives on controls, validation 100%. Every miss is listed in
`testset/results/HELDOUT.md`; the classes are low-motion content (detector abstains below `MOTION_MIN`), VFR jitter
just under the 25% threshold, and byte flips that decode silently (only a hash can catch those).
