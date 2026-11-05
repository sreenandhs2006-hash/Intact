# Held-out detector score (seeds 2, 3, 4, 5, 6)

Scored with code frozen at the commit that ended seed-1 development; no detector change after.
Tool versions: ffmpeg `ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026 the FFmpeg developers`, PyAV 19.0.2, Windows-11-10.0.26300-SP0. Match tolerance ±200 ms.

| Videos | Expected events | Found | Recall | Detections | False positives | Precision | Validation accuracy | FPs on control videos |
|---|---|---|---|---|---|---|---|---|
| 120 | 223 | 208 | 0.933 | 194 | 1 | 0.995 | 1.000 | 0 |

| Type | Expected | Found | Recall | Detections | FPs | Precision | Max time error (ms) | Count exact |
|---|---|---|---|---|---|---|---|---|
| corrupted_frame | 148 | 142 | 0.959 | 127 | 0 | 1.000 | – | – |
| duplicated_frame | 20 | 17 | 0.850 | 17 | 0 | 1.000 | 0.0 | 1.000 |
| irregular_timing | 10 | 8 | 0.800 | 8 | 0 | 1.000 | – | – |
| missing_frames | 30 | 30 | 1.000 | 31 | 1 | 0.968 | 0.0 | 1.000 |
| possible_skipped_frames | 10 | 6 | 0.600 | 6 | 0 | 1.000 | 0.0 | 0.167 |
| truncation | 5 | 5 | 1.000 | 5 | 0 | 1.000 | 0.0 | 0.200 |

## Every miss and false positive

- seed 2 · retimed_mandelbrot · MISSED `{"type": "possible_skipped_frames", "time_s": 5.2, "count": 2}`
- seed 2 · dup_mandelbrot · MISSED `{"type": "duplicated_frame", "time_s": 5.533333333333333, "count": 1}`
- seed 2 · vfr_jitter · MISSED `{"type": "irregular_timing", "start_s": 0, "end_s": 10}`
- seed 2 · flipped_20 · MISSED `{"type": "corrupted_frame", "time_s": 6.466667}`
- seed 3 · dup_mandelbrot · MISSED `{"type": "duplicated_frame", "time_s": 7.0, "count": 1}`
- seed 3 · flipped_5 · MISSED `{"type": "corrupted_frame", "time_s": 7.9}`
- seed 3 · flipped_5 · MISSED `{"type": "corrupted_frame", "time_s": 9.366667}`
- seed 3 · flipped_20 · MISSED `{"type": "corrupted_frame", "time_s": 0.933333}`
- seed 3 · flipped_20 · MISSED `{"type": "corrupted_frame", "time_s": 1.866667}`
- seed 4 · retimed_mandelbrot · MISSED `{"type": "possible_skipped_frames", "time_s": 5.266666666666667, "count": 3}`
- seed 4 · flipped_5 · MISSED `{"type": "corrupted_frame", "time_s": 4.7}`
- seed 5 · retimed_mandelbrot · MISSED `{"type": "possible_skipped_frames", "time_s": 6.6, "count": 5}`
- seed 5 · vfr_jitter · MISSED `{"type": "irregular_timing", "start_s": 0, "end_s": 10}`
- seed 5 · truncated · FALSE POSITIVE missing_frames at 6.766666666666667: interval 133.33 ms = 4.00x nominal 33.33 ms; ~2 frame slot(s) empty between 6.7667s and 6.9000s with no packet in the container
- seed 6 · retimed_mandelbrot · MISSED `{"type": "possible_skipped_frames", "time_s": 12.966666666666667, "count": 2}`
- seed 6 · dup_mandelbrot · MISSED `{"type": "duplicated_frame", "time_s": 16.1, "count": 2}`
