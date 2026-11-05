# M5 evidence – browser capture runs

Three real runs of the browser client (`/capture`) on 2026-11-06, Windows 11, recorded with:

```bash
python -m client.browser_run --source camera --out evidence/m5/fake-camera
python -m client.browser_run --source test --out evidence/m5/test-pattern
python -m client.browser_run --source test --stall --out evidence/m5/test-pattern-stall
```

Browser: HeadlessChrome 156 (user agent in each capture log), MediaRecorder `video/webm;codecs=vp9`.
Each folder holds the server's JSON report (tool versions inside), the HTML report and the raw capture log
exactly as the browser sent it. Every run: upload COMPLETE, server SHA-256 = client SHA-256, capture log
stored before finalize and its SHA-256 recorded in the report's `transfer.capture_log_sha256`.

**What these runs are not:** a real webcam. `fake-camera` is Chrome's built-in fake device
(`--use-fake-device-for-media-stream`): a real getUserMedia track and the real camera code path, but a synthetic
picture. A run with a physical camera needs a person at `/capture` and has not been done yet.

| Run | Time base | Frames logged / in file | Alignment | Key finding |
|---|---|---|---|---|
| fake-camera | `captureTime` | 560 / 559 | 558 of 559 file frames matched (next best offset: 510), mean distance 0.35 ms | 2.0 s gap at 0.45 s (42 frames) is in the file **and** the log: no frame reached the page while MediaRecorder started (2.5 s start-up) → **capture** |
| test-pattern | `presentationTime` | 908 / 875 | 847 of 875 (next best 714), 1.67 ms | 37 frames missing at 0.30–1.49 s; 35 of them reached the page → **encoding** (lost while MediaRecorder started) |
| test-pattern-stall | `presentationTime` | 895 / 860 | 832 of 860 (next best 689), 1.47 ms | the injected 0.5 s source stall at 10 s: file gap 10.046–10.575 s (16 frames), log gap 529.5 ms, 0 logged frames inside → **capture**. Same start-up loss → **encoding** |

What else the runs show, stated as found:

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

- A physical webcam (blocked in the Claude browser pane; needs a person at `/capture`).
- Resume after closing/reloading the page (the recording is kept in IndexedDB for this; the code path exists
  but no test reloads a page mid-upload).
- Firefox and Safari (only Chromium-based browsers were run; Safari records MP4 and may lack `captureTime`).
