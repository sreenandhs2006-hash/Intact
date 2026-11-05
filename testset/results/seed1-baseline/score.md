# Detector score - seed 1

Scored 2026-11-05T20:23:29+0530 · tolerance ±200 ms · ffmpeg `ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026 the FFmpeg developers` · PyAV 19.0.2 · Windows-11-10.0.26300-SP0

## Overall

| Expected events | Found | Recall | Detections | False positives | Precision | Validation accuracy | FPs on controls |
|---|---|---|---|---|---|---|---|
| 47 | 45 | 0.9574 | 54 | 15 | 0.7222 | 0.9167 | 0 (of 5 control videos) |

## Per anomaly type

| Type | Expected | Found | Recall | Detections | FPs | Precision | Time err mean / max (ms) | Count exact |
|---|---|---|---|---|---|---|---|---|
| corrupted_frame | 32 | 30 | 0.9375 | 24 | 0 | 1.0 | None / None | None |
| duplicate_timestamp | 0 | 0 | None | 2 | 2 | 0.0 | None / None | None |
| duplicated_frame | 4 | 4 | 1.0 | 5 | 1 | 0.8 | 33.3 / 33.3 | 1.0 |
| irregular_timing | 2 | 2 | 1.0 | 2 | 0 | 1.0 | None / None | None |
| missing_frames | 6 | 6 | 1.0 | 13 | 7 | 0.4615 | 0.0 / 0.0 | 1.0 |
| possible_skipped_frames | 2 | 2 | 1.0 | 6 | 4 | 0.3333 | 0.0 / 0.0 | 0.0 |
| truncation | 1 | 1 | 1.0 | 2 | 1 | 0.5 | 0.0 / 0.0 | 1.0 |

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
| dup_mandelbrot | VALID | VALID | 1/1 | 1 | – |
| dup_noisy | VALID | VALID | 1/1 | 1 | – |
| mixed_dup_gap | VALID | VALID_WITH_ERRORS ✗ | 2/2 | 6 | duplicate_timestamp @4.07s; missing_frames @4.07s; duplicate_timestamp @8.13s; missing_frames @8.20s |
| vfr_jitter | VALID | VALID | 1/1 | 1 | – |
| vfr_burst | VALID | VALID | 1/1 | 1 | – |
| flipped_5 | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 5/5 | 6 | possible_skipped_frames @8.97s |
| flipped_20 | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 20/20 | 21 | possible_skipped_frames @3.97s; possible_skipped_frames @6.60s; duplicated_frame @9.30s |
| zeroed_block | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 5/7 | 7 | missing_frames @5.27s; missing_frames @5.33s; missing_frames @5.40s; missing_frames @5.63s; possible_skipped_frames @5.97s; truncation @9.97s |
| truncated | VALID_WITH_ERRORS | VALID_WITH_ERRORS | 1/1 | 2 | missing_frames @7.80s |
| truncated_moov_end | INVALID | INVALID | 0/0 | 0 | – |
| fake_random | INVALID | INVALID | 0/0 | 0 | – |
| fake_text | INVALID | INVALID | 0/0 | 0 | – |
| fake_image | INVALID | VALID ✗ | 0/0 | 0 | – |

## Missed events

- zeroed_block: `{"type": "corrupted_frame", "time_s": 5.3}`
- zeroed_block: `{"type": "corrupted_frame", "time_s": 5.366667}`
