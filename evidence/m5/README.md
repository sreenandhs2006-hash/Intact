# M5 evidence – browser capture runs

Five real runs of the browser client (`/capture`). One with the user's physical webcam in desktop Chrome 156
(`webcam/`, 2026-11-06, recorded by hand at http://127.0.0.1:8000/capture); one on an iPhone in Safari
(`iphone-safari/`, 2026-11-08, recorded by hand, see below); three scripted in headless Chrome (2026-11-06):

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

**iPhone setup:** the laptop joined the iPhone's own hotspot (private network) and the server ran on HTTPS on
that address only (`uvicorn --host 172.20.10.8 --port 8443 --ssl-keyfile/--ssl-certfile`). The certificate came
from a throwaway test CA (OpenSSL, valid 7 days), installed and trusted on the phone for this test, then removed.
HTTPS is required because the camera API and `crypto.subtle` only work in a secure context. The server's tool
versions in the report are the laptop's; the browser is the phone's (user agent in the capture log).

`fake-camera` is Chrome's built-in fake device (`--use-fake-device-for-media-stream`): a real getUserMedia
track and the real camera code path, but a synthetic picture.

| Run | Time base | Frames logged / in file | Alignment | Key finding |
|---|---|---|---|---|
| **webcam** (1280x720, 30 fps requested and reported) | `captureTime` | 788 records + 12 frames without callback = 800 presented / 797 | 785 of 797 (next best 696), 0.72 ms | 3.3 s gap at 0.30–3.60 s (102 frames) in file **and** log → **capture**. 32 single-frame gaps about every 0.8 s, in file and log → **capture** (the camera delivered ~29 fps, not 30). 2 single frames (0.16 s, 8.77 s) were presented in the page (counted by `presentedFrames`, no callback) but are missing from the file → **encoding** |
| fake-camera | `captureTime` | 560 / 559 | 558 of 559 file frames matched (next best offset: 510), mean distance 0.35 ms | 2.0 s gap at 0.45 s (42 frames) is in the file **and** the log: no frame reached the page while MediaRecorder started (2.5 s start-up) → **capture** |
| test-pattern | `presentationTime` | 908 / 875 | 847 of 875 (next best 714), 1.67 ms | 37 frames missing at 0.30–1.49 s; 35 of them reached the page → **encoding** (lost while MediaRecorder started) |
| **iphone-safari** (front camera, 720x1280 portrait, 30 fps reported) | `captureTime` | 900 / 899 | 899 of 899 (next best 892), 0.25 ms | **No drops**: 0 delivery gaps in the log, no timestamp gaps in the file. MediaRecorder started **3 ms** after `start()` (Chrome: 1.5–3.8 s), so no start-up loss. 9 irregular-timing segments (single 42–45 ms intervals): 8 also irregular in the log → **capture**, 1 regular in the log → **encoding**. 36 `possible_skipped_frames` (picture jumps with regular timestamps) stay undetermined: the log shows regular delivery there |
| test-pattern-stall | `presentationTime` | 895 / 860 | 832 of 860 (next best 689), 1.47 ms | the injected 0.5 s source stall at 10 s: file gap 10.046–10.575 s (16 frames), log gap 529.5 ms, 0 logged frames inside → **capture**. Same start-up loss → **encoding** |

What else the runs show, stated as found:

- **Start-up loss in every run.** MediaRecorder took 1.5–3.8 s from `start()` to its `start` event (webcam: 3.8 s).
  In that window the webcam and fake camera delivered no frames to the page (log: capture), while the canvas
  source kept delivering and the recorder dropped them (log: encoding). The log is right about *where* the frames
  were lost; *why* the camera track paused exactly while the encoder started is not provable from this log. The
  timing points at the browser's capture/encoder start-up rather than the camera sensor (hypothesis, untested).
- **iPhone Safari is the exception.** Same page, real phone camera (iOS Safari 26.5, user agent in the log): the
  recorder started in 3 ms and every presented frame is in the file. Safari also recorded `video/webm;codecs=vp9`
  (the page prefers WebM; this Safari supports it) and provides `captureTime`, so the earlier guess "Safari records
  MP4 and may lack captureTime" did not hold for this version. One run, one phone: no statistics.
- The iPhone run has 900 presented frames and 899 in the file, but no gap in the file. The one-frame difference
  is not located (most likely at the very end of the recording, where the file span is 34 ms shorter than the log).
- **Alignment rule tightened (2026-11-08).** A later headless test-pattern run came out perfectly regular: the file
  matched the log 810 frames at the right offset and 809 one frame later, and the recorder start time was 121 ms off.
  The old rule then fell back to the start time, which in all five runs above was 29–64 ms (1–2 frames) off, so it
  could not be trusted. Now only the data may pin the offset: the frame pattern (margin ≥ 3 frames, as in all five runs
  above) or a long gap shared by file and log whose edges line up within a quarter frame (here the 0.5 s stall:
  offset 581.5 ms, the same as computed by hand from the stall edges). Otherwise the alignment is unreliable and
  the log judges nothing. The five runs above are unaffected (all decided by frame pattern). That run's timestamps
  are kept as a regression test (`tests/data/headless-stall-regular.json`).
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
- Firefox (not run). Safari only once, on one iPhone (iOS Safari 26.5); Safari's MP4 path was not exercised
  because this version chose WebM.
- Upload from the phone over a bad network: the iPhone run went over the phone's own hotspot (a short, good link),
  so it tests the browser and camera, not the network. Network faults are covered by M4 and the pytest above.
