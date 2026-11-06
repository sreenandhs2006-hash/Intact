# M5 evidence – browser capture runs

Four real runs of the browser client (`/capture`) on 2026-11-06, Windows 11. One with the user's physical
webcam in desktop Chrome 156 (`webcam/`, recorded by hand at http://127.0.0.1:8000/capture); three scripted in
headless Chrome:

```bash
python -m client.browser_run --source camera --out evidence/m5/fake-camera
python -m client.browser_run --source test --out evidence/m5/test-pattern
python -m client.browser_run --source test --stall --out evidence/m5/test-pattern-stall
```

Browser: Chrome 156 (user agent in each capture log), MediaRecorder `video/webm;codecs=vp9`. The webcam video
itself is not committed (it shows a person); its SHA-256 is in the report.
Each folder holds the server's JSON report (tool versions inside), the HTML report and the raw capture log
exactly as the browser sent it. Every run: upload COMPLETE, server SHA-256 = client SHA-256, capture log
stored before finalize and its SHA-256 recorded in the report's `transfer.capture_log_sha256`.

`fake-camera` is Chrome's built-in fake device (`--use-fake-device-for-media-stream`): a real getUserMedia
track and the real camera code path, but a synthetic picture.

| Run | Time base | Frames logged / in file | Alignment | Key finding |
|---|---|---|---|---|
| **webcam** (1280x720, 30 fps requested and reported) | `captureTime` | 788 records + 12 frames without callback = 800 presented / 797 | 785 of 797 (next best 696), 0.72 ms | 3.3 s gap at 0.30–3.60 s (102 frames) in file **and** log → **capture**. 32 single-frame gaps about every 0.8 s, in file and log → **capture** (the camera delivered ~29 fps, not 30). 2 single frames (0.16 s, 8.77 s) were presented in the page (counted by `presentedFrames`, no callback) but are missing from the file → **encoding** |
| fake-camera | `captureTime` | 560 / 559 | 558 of 559 file frames matched (next best offset: 510), mean distance 0.35 ms | 2.0 s gap at 0.45 s (42 frames) is in the file **and** the log: no frame reached the page while MediaRecorder started (2.5 s start-up) → **capture** |
| test-pattern | `presentationTime` | 908 / 875 | 847 of 875 (next best 714), 1.67 ms | 37 frames missing at 0.30–1.49 s; 35 of them reached the page → **encoding** (lost while MediaRecorder started) |
| test-pattern-stall | `presentationTime` | 895 / 860 | 832 of 860 (next best 689), 1.47 ms | the injected 0.5 s source stall at 10 s: file gap 10.046–10.575 s (16 frames), log gap 529.5 ms, 0 logged frames inside → **capture**. Same start-up loss → **encoding** |

What else the runs show, stated as found:

- **Start-up loss in every run.** MediaRecorder took 1.5–3.8 s from `start()` to its `start` event (webcam: 3.8 s).
  In that window the webcam and fake camera delivered no frames to the page (log: capture), while the canvas
  source kept delivering and the recorder dropped them (log: encoding). The log is right about *where* the frames
  were lost; *why* the camera track paused exactly while the encoder started is not provable from this log. The
  timing points at the browser's capture/encoder start-up rather than the camera sensor (hypothesis, untested).
- The two webcam "encoding" frames rest on the `presentedFrames` counter alone (callback missed, exact time
  unknown); the report shows `log_frames_inside_gap: 0, presented_inside_gap: 1` for both.

- The test pattern's one-frame gaps (~47–50 ms) stay **undetermined**: `presentationTime` is rounded to the
  display refresh (~17 ms), too coarse to judge a gap that short. The report says so per anomaly.
- The canvas test source gives no `captureTime`; the fake camera does. Chrome's fake camera ran at 20 fps
  (`track_settings.frameRate`), not the 30 fps requested.
- 45 `possible_skipped_frames` on the fake camera's synthetic picture stay **undetermined** (frames reached the
  page irregularly but without gaps). Not investigated further; likely the fake device's animation, not drops.
- One run in a hidden Browser pane (not kept) produced only 2 frame callbacks: frame callbacks and painting stop
  when the page is not rendered. The analysis reported that log as "not usable" instead of guessing.

## Browser upload under faults (pytest, not stored here)

`tests/test_m5_capture.py::test_browser_upload_survives_resets_and_server_crash` runs the same page in headless
Chrome through Toxiproxy (upload throttled to 250 KB/s), resets every connection for 3 s at ~25 % and hard-kills
the server at ~50 %, restarting it 5 s later. Run on 2026-11-06: faults landed at 2,026,197 and 3,398,833 of
6,514,961 bytes; the upload finished COMPLETE with matching SHA-256, 0 duplicate and 0 rejected chunks
(the client resumed exactly from the server's verified offset).

## Not verified

- More than one webcam run (one run on one camera; no repeat statistics).
- Resume after closing/reloading the page (the recording is kept in IndexedDB for this; the code path exists
  but no test reloads a page mid-upload).
- Firefox and Safari (only Chromium-based browsers were run; Safari records MP4 and may lack `captureTime`).
