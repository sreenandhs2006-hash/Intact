# Demo script (about 7 minutes)

For a live demo or a screen recording on the Windows laptop. Everything shown is real. The netem network runs need
Linux, so they are shown from their recorded evidence, not re-run live.

**Before you start:**
- Open a terminal in the project folder with the virtual environment active and FFmpeg on PATH.
- Have Chrome or Edge open.
- Close other uploads.
- Use a fresh data folder so the status page starts empty:

```bash
VI_DATA_DIR=~/.nihilent-vi/demo uvicorn server.app:app --port 8000
```

---

## 1. The problem (30 s)

> "The brief asks for two things: deliver a 30-second video intact over a network that swings between 20% and 100%,
> and then check its frames at 30 FPS. The hard part is the distinction the brief highlights: a perfect upload
> does not prove a perfect recording. My system keeps those questions apart and says what evidence settles each
> one."

Show the architecture diagram in `README.md`.

## 2. Record and upload in the browser (90 s)

1. Open http://127.0.0.1:8000/capture **in Chrome or Edge** (a normal browser window, not an embedded preview: an
   embedded, busy view displays frames late and the log can then not be aligned).
2. Choose **Test pattern (no camera needed)**, tick **simulate a 0.5 s source stall at 10 s**, then press
   **Record 30 s and upload**.
3. While it records, point at the status line (*Starting the recorder…* → *Recording… 23 s left*) and explain:
   > "The page records with MediaRecorder and logs every frame that reaches the browser. The 30 seconds count from
   > the moment the recorder really starts. Then it uploads in pieces: each has its own SHA-256, and the server
   > re-hashes the whole file before accepting it."
4. When the result appears, read the three lines:
   - **Upload:** verified, byte-identical (SHA-256 match);
   - **Video:** valid;
   - **Frames:** about 15 missing frames where the stall was, attributed to **capture**, because the log shows no
     frame reached the page then. The stall is 10 s after recording was *requested*, so in the file it sits at
     8–10 s, depending on when Chrome started the file clock. If the line says *undetermined* instead, the log
     could not be aligned reliably, and the report says so rather than guessing: a good moment to show that rule.
5. Open the full report. Show **Where in the video** (click a marker, and the table jumps to that anomaly). Then
   scroll to **Capture evidence (browser frame log)** → *What this log can prove* / *What it cannot prove*.
   > "The report says exactly what this log can and cannot prove. For example, it is written by the client, so its
   > authenticity cannot be verified."

(Optional, with a webcam: choose **Camera** instead. On this laptop the webcam run showed a 3.3 s gap at the start
attributed to capture.)

## 3. Faults in the upload itself (90 s)

This runs a real browser upload through Toxiproxy: connection resets at about 25%, a hard server kill at about 50%,
and a restart 5 s later.

```bash
python -m pytest -q tests/test_m5_capture.py -k survives
```

> "Same page, but the upload is throttled to 250 KB/s, every connection is reset for 3 seconds, and then I kill the
> server. The client waits, asks the server how many bytes it safely holds, and continues from exactly there."

It prints `1 passed`. The test checks COMPLETE, a matching hash and zero duplicate chunks.

Then open [nettest/EVIDENCE.md](../nettest/EVIDENCE.md) and show the table:
> "On a Linux laptop with netem I ran 10 network scenarios, 5 times each: 20%, 60% and 100% strength, fluctuating,
> a 10-second outage, a network switch, resets, 30-second hangs, client crash, server crash. 50 out of 50
> completed with a verified hash. I checked the raw logs too: every byte is accounted for."

## 4. Damaged, truncated and invalid videos (90 s)

Upload the three samples from `docs/samples/`, or open their saved reports:

```bash
python -m client.uploader samples-videos/mixed_dup_gap.mp4
python -m client.uploader samples-videos/truncated.mp4
python -m client.uploader samples-videos/fake_text.mp4
```

(Make them first with `python -m testset.generate --out samples-videos --seed 6 --duration 30 --only mixed_dup_gap truncated fake_text`.)

- **mixed_dup_gap:** a duplicated frame at 1.57 s, and 6 missing frames at 11.83–12.07 s. The 30 FPS timeline marks
  the filled slots as *gap-fill*, not as duplicates.
- **truncated:** `VALID_WITH_ERRORS`, truncation from 15.33 s ("header declares 900 frames, file contains 462 packets").
- **fake_text:** `INVALID`, "Invalid data found when processing input".

> "All three arrived byte-perfect, so transfer is ruled out. Without a capture log the cause stays
> `undetermined`. I don't guess."

Then show [testset/results/HELDOUT.md](../testset/results/HELDOUT.md):
> "I built 24 kinds of faulty videos with known ground truth, tuned on one seed, froze the code, and scored 120
> new videos once: recall 0.93, precision 0.995, no false alarms on clean videos. Every miss is listed."

## 5. Limitations and close (60 s)

Open [docs/LIMITATIONS.md](LIMITATIONS.md):
> "Frames dropped before encoding with new timestamps leave no gap, so without a capture log I say *cannot
> determine*. Low-motion duplicates and silent byte flips are the detector's known misses. The network tests were
> emulated, not a real phone network."

Finish with the tests:
```bash
python -m pytest -q        # 81 passed
```

---

## Questions you may get

| Question | Short answer |
|---|---|
| Why not zip the video? | Video is already compressed by its codec; ZIP saves almost nothing. The upload sends the exact bytes and the hash proves it, so quality never changes |
| What if a chunk arrives corrupted? | Its SHA-256 does not match, so the server rejects it and the client re-sends it. The whole-file hash at the end catches anything else |
| What if the server crashes mid-upload? | Bytes are fsync'd before being recorded, so the recorded offset is never ahead of the disk. After restart the client asks for the offset and continues (tested: SIGKILL, 5/5 runs) |
| How do you tell capture from encoding drops? | From the browser's per-frame log: no frame reached the page during a file gap → capture; frames reached the page but are not in the file → encoding |
| Why not just resample to 30 FPS and look for repeats? | Resampling creates repeats by design. Detection runs on the original timestamps, and only then is the 30 FPS timeline built, with its artefacts labelled |
| How do you know the detector works? | Held-out known-fault set with ground truth from the FFmpeg recipe, scored once after freezing the code |
| What would you add next? | A real phone-network test, parallel chunks for fast links, a quiet log line instead of the `ClientDisconnect` traceback, and capture logs from native apps |
