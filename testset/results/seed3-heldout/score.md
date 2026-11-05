# Detector score - seed 3

Scored 2026-11-05T20:28:41+0530 · tolerance ±200 ms · ffmpeg `ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026 the FFmpeg developers` · PyAV 19.0.2 · Windows-11-10.0.26300-SP0

## Overall

| Expected events | Found | Recall | Detections | False positives | Precision | Validation accuracy | FPs on controls |
|---|---|---|---|---|---|---|---|
| 46 | 41 | 0.8913 | 38 | 0 | 1.0 | 1.0 | 0 (of 5 control videos) |

## Per anomaly type

| Type | Expected | Found | Recall | Detections | FPs | Precision | Time err mean / max (ms) | Count exact |
|---|---|---|---|---|---|---|---|---|
| corrupted_frame | 31 | 27 | 0.871 | 24 | 0 | 1.0 | None / None | None |
| duplicated_frame | 4 | 3 | 0.75 | 3 | 0 | 1.0 | 0.0 / 0.0 | 1.0 |
| irregular_timing | 2 | 2 | 1.0 | 2 | 0 | 1.0 | None / None | None |
| missing_frames | 6 | 6 | 1.0 | 6 | 0 | 1.0 | 0.0 / 0.0 | 1.0 |
| possible_skipped_frames | 2 | 2 | 1.0 | 2 | 0 | 1.0 | 0.0 / 0.0 | 0.0 |
| truncation | 1 | 1 | 1.0 | 1 | 0 | 1.0 | 0.0 / 0.0 | 0.0 |

## Per video

| Video | Expected validation | Got | Events found | Detections | False positives |
|---|---|---|---|---|---|
| clean_testsrc | VALID | VALID | 0/0 | 0 | – |
| clean_mandelbrot | VALID | VALID | 0/0 | 0 | – |
| static_flat | VALID | VALID | 0/0 | 0 | – |
| static_noisy | VALID | VALID | 0/0 | 0 | – |
| src25 | VALID | VALID | 0/0 | 0 | – |
| gap_testsrc | VALID | VALID | 1/1 | 1 | – |
| gap_mandelbrot | VALID | VALID | 1/1 | 1 | – |
| gap_multi_noisy | VALID | VALID | 3/3 | 3 | – |
| retimed_testsrc | VALID | VALID | 1/1 | 1 | – |
| retimed_mandelbrot | VALID | VALID | 1/1 | 1 | – |
| dup_testsrc | VALID | VALID | 1/1 | 1 | – |
| dup_mandelbrot | VALID | VALID | 0/1 | 0 | – |
| dup_noisy | VALID | VALID | 1/1 | 1 | – |
| mixed_dup_gap | VALID | VALID | 2/2 | 2 | – |
| vfr_jitter | VALID | VALID | 1/1 | 1 | – |
| vfr_burst | VALID | VALID | 1/1 | 1 | – |
| flipped_5 | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 3/5 | 3 | – |
| flipped_20 | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 18/20 | 16 | – |
| zeroed_block | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 6/6 | 5 | – |
| truncated | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 1/1 | 1 | – |
| truncated_moov_end | INVALID | INVALID | 0/0 | 0 | – |
| fake_random | INVALID | INVALID | 0/0 | 0 | – |
| fake_text | INVALID | INVALID | 0/0 | 0 | – |
| fake_image | INVALID | INVALID | 0/0 | 0 | – |

## Missed events

- dup_mandelbrot: `{"type": "duplicated_frame", "time_s": 7.0, "count": 1}`
- flipped_5: `{"type": "corrupted_frame", "time_s": 7.9}`
- flipped_5: `{"type": "corrupted_frame", "time_s": 9.366667}`
- flipped_20: `{"type": "corrupted_frame", "time_s": 0.933333}`
- flipped_20: `{"type": "corrupted_frame", "time_s": 1.866667}`
