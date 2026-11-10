# Limitations

What the system cannot do, and what was not tested. Each point is stated as found in real runs.

## What the analysis cannot prove

- **A byte-perfect transfer does not prove a clean recording.** The hash proves the backend has the same bytes the
  client had, nothing about what happened before encoding.
- **Frames dropped before encoding with re-generated timestamps leave no gap.** Only content cues (a motion jump)
  hint at them, reported as `possible_skipped_frames` with low confidence. Held-out recall for this type is 0.60.
- **Without a capture log, capture and encoding drops cannot be told apart.** Such anomalies get likely cause
  `undetermined`, and the summary says "cannot determine" instead of "no drops".
- **The capture log is written by the client.** The server checks its integrity (SHA-256, tied to the video's
  hash) but cannot check its authenticity. It covers delivery to the page, not what MediaRecorder encoded.
- **The capture log can fail to settle a case.** It judges nothing when:
  - the page was hidden;
  - a gap is shorter than the log's time resolution (`presentationTime` is rounded to ~17 ms);
  - the alignment is ambiguous (a perfectly regular source with no shared gap);
  - the page displays frames late because the browser is busy. Without camera timestamps the log holds display
    times, which then lag behind capture. Seen once in an embedded browser view: the analysis judged the log
    unreliable (mean distance 9.1 ms) and left the stall undetermined.

## Detector limits (measured on 120 held-out videos)

- **Low-motion content:** duplicated or skipped frames are not detected when the picture barely changes; the
  detector abstains below a motion threshold.
- **Small timing irregularity:** variable frame rate jitter just under the 25% threshold is missed (recall 0.80).
- **Silent byte damage:** flipped bytes that decode without any error message cannot be seen in the pictures
  (corrupted-frame recall 0.96). Only a hash catches those, and on upload it does.
- Content checks use fixed thresholds on 160×90 grayscale thumbnails. Static scenes, fades and scene cuts can cause
  misses or false alarms.
- Only the first video stream is analysed; audio is ignored.
- With B-frames, decoder errors map to the packet's frame. The visibly damaged frame can differ, and damage can
  carry on until the next keyframe.

## Transfer behaviour worth knowing

- **STALLED means "no completed chunk for a while"** (30 s by default, 15 s in the network tests). It is not proof
  of a fault: on the 20% link one slow first chunk took 16.9 s and was marked STALLED. The state is computed when it
  is read, so its timestamp is the first status read after the threshold.
- **The 20% link delivers about 140–200 kbit/s, not 500.** With 5% loss and 400 ms delay, TCP cannot fill it. A
  3.76 MB video took 152–217 s.
- When a connection is cut while a chunk is arriving, the server discards the partial chunk correctly but logs a
  `ClientDisconnect` traceback (2 of 50 runs). Only cosmetic.
- Uploads are sequential: one chunk in flight. That is simple and robust, but slower than parallel chunks on fast links.

## Not tested

- A real mobile network or a real Wi-Fi → mobile handover. Network switching was emulated, and the client's IP
  address did not change. This work was done alone and overlapped with end-semester exams, so real-device testing
  was cut to the single iPhone run above. The planned tests, in order of value:
  1. **Real connection switch.** Server on a second computer, both on one router; the client laptop switches between
     the router's 2.4 GHz and 5 GHz networks (or Wi-Fi and cable) halfway through an upload. Its address changes and
     the server sees the new one. Pass: `COMPLETE`, hashes match, re-sent bytes at most one chunk.
  2. **Phone on mobile data.** The iPhone, Wi-Fi off, records on `/capture` over HTTPS and uploads to a server
     reachable from the internet.

  A tunnel (for example a Cloudflare quick tunnel) was considered for test 1 and rejected: through the tunnel the
  server sees every request coming from the tunnel process on the same laptop, so the address change it is meant
  to show is invisible, and switching networks also cuts the tunnel itself.
- The browser client under netem (it was tested against Toxiproxy resets and a server crash).
- Firefox. Safari was tested once (iPhone, iOS Safari 26.5); its MP4 recording path was not exercised because that
  version chose WebM.
- Resuming a browser upload after a page reload (the IndexedDB path exists; no test reloads a page mid-upload).
- More than one webcam run, and more than one machine for the network tests.
- Files larger than one 30 s recording over the 20% link. No security hardening: no authentication, plain HTTP on
  localhost, size limits only.

## Test suite

- The browser tests drive a real headless Chrome and are timing-sensitive. On a throttled laptop (battery saver)
  the canvas test source cannot hold 30 fps and the stall test fails; run the suite on mains power.
- On 2026-11-09 one full run (81 tests, mains power) had a single failure that passed on immediate re-run; which
  test it was was not recorded. The next full run passed 81/81, and the suspected test (browser upload through
  Toxiproxy with a server crash) passed 3 of 3 on its own.
- On 2026-11-09 a later full run (82 tests) failed that same test once: the upload did not finish within the 300 s
  limit. It passed on its own (90 s) and in the next five full runs (82/82 each). Treat it as flaky under load.
- On 2026-11-10, a full run made while Chrome was busy rendering the PDF failed two browser tests (the simulated
  stall, and resets plus server crash): "no finished upload appeared" within the limit. Both passed when run on their
  own (200 s), and the next full run passed 82/82. A later full run that day failed the resets-plus-crash test once
  more (81/82, same timeout) and it passed on its own (91 s). The browser tests depend on machine load; run them on an
  idle laptop.
- The page's animations stop while recording and uploading, so they do not compete with the frame log (measured
  for the light-rays background: no WebGL draw calls while busy; for the other animations this is by code only). Their graphics cost on a slow laptop or a phone was not measured.
