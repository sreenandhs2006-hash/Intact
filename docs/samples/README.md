# Sample integrity reports

Three 30-second videos with known faults, made with `testset/generate.py` (seed 6). Each was uploaded with the
Python client to a running server on 2026-11-09 and analysed by the server automatically. Nothing here is edited by
hand. Each sample has three files:
- `*.html`: the report as a person reads it (open it in a browser);
- `*.json`: the full report, including tool versions and every frame;
- `*.expected.json`: what the generator put in the video, written before analysis.

Reproduce:
```bash
python -m testset.generate --out samples-videos --seed 6 --duration 30 --only mixed_dup_gap truncated fake_text
uvicorn server.app:app --port 8000
python -m client.uploader samples-videos/mixed_dup_gap.mp4      # then open the report from http://127.0.0.1:8000/
```

| Sample | What was done to the video | Transfer | Validation | What the report found |
|---|---|---|---|---|
| [mixed_dup_gap](mixed_dup_gap.html) | frame 47 repeated 2×; frames 356–361 removed, timestamps kept | COMPLETE, SHA-256 match | VALID | **duplicated_frame** at 1.567 s: "2 frame(s) identical to frame 46 … while local motion is 2.00". **missing_frames** at 11.833–12.067 s: "interval 233.33 ms = 7.00× nominal; ~6 frame slots empty … no packet in the container". The 30 FPS timeline marks those 6 slots as gap-fill, not as duplicates |
| [truncated](truncated.html) | file cut to 1,513,688 of 2,936,429 bytes (header intact) | COMPLETE, SHA-256 match | VALID_WITH_ERRORS | **truncation** from 15.33 s: "header declares 900 frames, file contains 462 packets; header duration 30.000 s, decoded frames span 15.500 s". It counts 438 missing frames; the generator says 439. The location is exact, the count is off by one (truncation counts were exact in only 1 of 5 held-out videos; cause not investigated) |
| [fake_text](fake_text.html) | a text file named `.mp4` | COMPLETE, SHA-256 match | INVALID | ffprobe: "Invalid data found when processing input"; the decoder cannot open it. No frame analysis is attempted |

## What these samples show

- **Transfer and content are separate questions.** All three files arrived byte-perfect (hash match), and yet one
  is damaged and one is not a video. The report states both results separately. Because the hash matched, it rules
  out transfer as the cause of every anomaly.
- **Causes are not guessed.** These are FFmpeg files without a capture log, so the likely cause of the missing and
  duplicated frames is `undetermined`, with capture and encoding as candidates. With a browser capture log the same
  question can be settled; see `evidence/m5/`. In the webcam run there, a 3.3 s gap is attributed to capture because
  no frame reached the page during it.
- **Conversion artefacts are labelled.** Converting to 30 FPS fills the 6 empty slots by repeating the last frame;
  the report counts them as `gap_fill_slots`, not as duplicated frames.

A damaged *upload* never gets this far: a corrupted chunk is rejected, an incomplete file cannot be finalized, and
a file whose hash does not match becomes `REJECTED` and is never analysed (`tests/test_m1_transfer.py`).
