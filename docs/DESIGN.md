# Design notes

Why the system is built the way it is, one section per part. Each choice lists the alternative that was rejected.

## 1. Reliable transfer (client/uploader.py, server/uploads.py)

The client creates a session declaring the file's size and SHA-256, then sends chunks one after another. Each chunk
is addressed by byte offset and carries its own SHA-256. The server rejects damaged chunks, treats a re-sent
identical chunk as a no-op (409 if different bytes arrive for a stored offset), and only extends a contiguous
verified prefix (`received_bytes`). It fsyncs the bytes before recording them in SQLite, so the database never
claims bytes the disk does not have. Resuming after any failure is the same operation: ask the server for
`received_bytes` and continue. `finalize` re-reads the whole file from disk; only a matching SHA-256 yields
`COMPLETE`, anything else is `REJECTED`. Idle sessions become `STALLED` (resumable) and later `FAILED` (terminal).
Analysis code can open a file only through `uploads.verified_file()`, which refuses anything that is not
`COMPLETE` with a matching hash.

| Choice | Why | Rejected alternative |
|---|---|---|
| Offset-addressed chunks, contiguous prefix | One rule covers every failure: the server's offset is the truth | Out-of-order parallel chunks: faster on good links, but bookkeeping for holes and no gain at 500 kbit/s |
| SHA-256 per chunk **and** for the whole file | Per chunk: a damaged chunk is re-sent at once, not discovered at the end. Whole file: proves the assembled result, including bugs in assembly | TCP checksum only: 16-bit, misses corruption by proxies, disks or software bugs |
| fsync before recording the chunk in SQLite | After a server crash (tested: SIGKILL) the recorded offset is never ahead of the data on disk | Write-back caching: a crash can lose bytes the database says are stored |
| Retry with exponential backoff, capped at 30 s, full jitter | Recovers quickly from short drops and does not hammer a recovering server; jitter stops many clients retrying in sync | Fixed retry interval |
| 20 s read/write timeout as stall detection | A hung connection (data silently dropped) is detected and replaced; tested with 30 s hangs | No timeout: the upload hangs forever on a dead connection |
| Chunk size adapts toward about 2 s per chunk (64 KB–8 MB, at most doubling after a success, halved after a failure) | At 20% strength a chunk still finishes before the stall timeout; at 100% the per-request overhead is small | Fixed chunk size: either too big for bad links or too slow on good ones |
| Plain HTTP + JSON, no tus/websockets | Easy to reason about and port (the browser client is a direct port) | tus protocol: similar ideas, more machinery to explain |

## 2. Integrity analysis (analysis/)

ffprobe validates the container and stream. PyAV decodes every frame single-threaded, capturing every FFmpeg
message per packet; the ffmpeg CLI decodes again as an independent check. Detection runs on the **original**
timestamps first:
- gaps: an interval more than 1.5× the median interval;
- repeated or backwards timestamps;
- irregular intervals (variable frame rate).

Content checks on 160×90 grayscale thumbnails add duplicated frames (an identical picture in the middle of motion)
and possible skipped frames (a motion jump with regular timestamps, low confidence).

Only then is a 30 FPS timeline built: slot k shows the latest frame with pts ≤ k/30. Slots that repeat a frame are
labelled *conversion duplicates*, or *gap-fill* when they cover a source gap. These are artefacts of the
conversion, not defects. Each anomaly carries:
- evidence;
- confidence;
- a likely cause, plus other candidates;
- what is ruled out (transfer is ruled out only when the SHA-256 was verified).

Regular timestamps never produce "no drops": without a capture log the report says "cannot determine".

| Choice | Why | Rejected alternative |
|---|---|---|
| Detect on source timestamps, convert to 30 FPS afterwards | The brief warns that 30 FPS conversion duplicates and omits frames by design; detecting after conversion would report those as defects | Resample first, then compare neighbouring frames |
| Two decoders (PyAV + ffmpeg CLI) | An error seen by both is solid; one seen by only one is reported with that caveat | Single decoder |
| Thumbnails for content checks | Fast, and robust to compression noise | Full-resolution pixel diffs: slow and noisy |
| "Cannot determine" as a first-class answer | A clean file cannot prove a clean recording (the brief's key distinction) | Reporting "no drops" whenever timestamps are regular |

## 3. Known-fault test set (testset/)

`testset/generate.py` builds 24 videos per seed:
- controls: clean synthetic, clean Mandelbrot zoom, flat static, noisy static, 25 fps source;
- removed frames, with and without re-timing; duplicated frames; mixed faults;
- variable frame rate, whole-file and in bursts;
- flipped bytes; a zeroed block; truncation with and without a usable index;
- three fake files.

Ground truth comes from the FFmpeg recipe (frame indices) or from ffprobe's packet table of the clean source (byte
position → packet → time), never from the detector. `testset/score.py` matches detections to expected events of
the same type within ±200 ms.

Seed 1 was the development set: its untouched baseline is kept (recall 0.957, precision 0.722). Fixes were rules,
not threshold tuning. The code was then frozen and seeds 2–6 were scored once: recall 0.933, precision 0.995,
0 false positives on clean videos, validation 100%. Every miss is listed in `testset/results/HELDOUT.md`.

**Why held out:** scoring on the data used for tuning would overstate accuracy.

## 4. Network tests (nettest/)

A private virtual cable (veth pair, server in its own network namespace) carries all traffic.
- **netem** shapes both directions: 100% = 20 Mbit/s, 20 ms, 0% loss; 60% = 5 Mbit/s, 80 ms, 1%;
  20% = 500 kbit/s, 400 ms, 5%.
- **Toxiproxy** in front of the server cuts, resets or hangs connections.
- **Process kills** (SIGKILL) test crashes of the client and the server.

Faults fire when the client's own log shows a given fraction uploaded, so they always land mid-transfer whatever
the speed. Scenarios are interleaved across repetitions, so slow drift affects all of them equally. Preflight
measures the lab (ping RTT, upload rate) before any test.

**Why emulation:** a real phone network cannot be repeated, and its conditions cannot be stated precisely.

## 5. Browser capture (server/static/, analysis/capture.py)

`/capture` records 30 s with MediaRecorder. Meanwhile `requestVideoFrameCallback` on the live preview logs every
frame that reaches the page: `captureTime` when the browser provides it, else `presentationTime`, plus the
`presentedFrames` counter and page visibility. The recording is kept in IndexedDB until the upload is COMPLETE, so
a reload or crash can resume. `static/uploader.js` is a port of the Python client (same protocol). Before finalize
it posts the log; the server accepts it only if its SHA-256 matches and it names the video's SHA-256.

`analysis/capture.py` aligns the page clock with the file timestamps. It searches for the offset at which file
frames and logged frames coincide; this is robust to frames lost on one side. The offset counts as reliable only
if the data pins it:
- **frame pattern:** at least 3 more frames match than one frame later (camera jitter makes the pattern unique); or
- **gap edges:** a long gap present in both file and log lines up at both edges within a quarter frame.

A perfectly regular source with no shared gap is ambiguous, and then the log is not used. The recorder's start
time is not trusted for this: in five real runs it was 29–64 ms (1–2 frames) off.

Then, for each file anomaly, it asks: did frames reach the browser at that moment?
- No logged frame inside a file gap → **capture**.
- Frames reached the page but are missing from the file → **encoding** (the recording pipeline).
- The log cannot judge (hidden page, gap shorter than the log's time resolution, unreliable alignment) →
  **undetermined**.

Every report lists exactly what the log can and cannot prove.

**Why a frame log and not a second recording:** it is cheap, it covers every frame, and it answers exactly the
brief's question (capture vs encoding). Its limit is stated plainly: the client writes it, so its integrity can be
checked but its authenticity cannot.
