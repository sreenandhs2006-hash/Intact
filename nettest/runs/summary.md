# Network test results

Recorded 2026-11-08T00:55:04+0530 on `Ubuntu 24.04.5 LTS`, `Linux pai 7.0.0-42-generic #42~24.04.1-Ubuntu SMP PREEMPT_DYNAMIC Mon Oct 19 14:`, tc `tc utility, iproute2-6.1.0, libbpf 1.3.0`, Toxiproxy `{"version": "2.9.0"}`, commit `7c50be86ef`. Video 3756860 bytes, max chunk 512 KB.

Network strength: 100% = 20 Mbit/s, 20 ms RTT, 0% loss · 60% = 5 Mbit/s, 80 ms, 1% · 20% = 500 kbit/s, 400 ms, 5% (loss per direction).

| Scenario | Runs | Success | Success rate | Hash verified | Duration median (min-max) s | Retries mean (max) | Resumed bytes mean | Runs with server STALLED | Faults that hit mid-transfer |
|---|---|---|---|---|---|---|---|---|---|
| stable_100 | 5 | 5 | 100% | 5/5 | 1.92 (1.91-1.92) | 0.0 (0) | 0 | 0 | 0/0 |
| stable_60 | 5 | 5 | 100% | 5/5 | 10.2 (7.92-18.52) | 0.0 (0) | 0 | 0 | 0/0 |
| stable_20 | 5 | 5 | 100% | 5/5 | 181.47 (151.84-217.38) | 0.0 (0) | 0 | 1 | 0/0 |
| fluctuating | 5 | 5 | 100% | 5/5 | 32.22 (25.55-45.66) | 0.4 (1) | 0 | 3 | 25/25 |
| interruption | 5 | 5 | 100% | 5/5 | 26.64 (20.44-44.31) | 6.2 (7) | 0 | 4 | 5/5 |
| network_switch | 5 | 5 | 100% | 5/5 | 66.04 (62.77-89.83) | 4.6 (6) | 0 | 1 | 10/10 |
| resets | 5 | 5 | 100% | 5/5 | 16.95 (13.79-23.67) | 8.8 (9) | 0 | 0 | 15/15 |
| timeouts | 5 | 5 | 100% | 5/5 | 70.16 (68.61-77.7) | 5.8 (6) | 0 | 5 | 10/10 |
| client_restart | 5 | 5 | 100% | 5/5 | 10.56 (9.08-10.82) | 0.0 (0) | 2149581 | 0 | 5/5 |
| server_restart | 5 | 5 | 100% | 5/5 | 17.19 (12.57-19.39) | 4.4 (5) | 0 | 0 | 5/5 |

## Scenarios

- **stable_100**: 100% strength throughout
- **stable_60**: 60% strength throughout
- **stable_20**: 20% strength throughout
- **fluctuating**: strength changes mid-transfer 100 -> 60 -> 20 -> 60 -> 20 -> 100
- **interruption**: 60% link; at 30% the connection is cut for 10 s (all sockets closed, new ones refused)
- **network_switch**: Wi-Fi-like 100% link; at 40% all connections drop for 3 s and the link comes back as a cellular-like 20% link (approximation: the client IP does not change)
- **resets**: 60% link; at 25%, 50%, 75% every connection is reset (TCP RST) for 2 s
- **timeouts**: 60% link; at 30% and 60% data is silently dropped for 30 s (hung connection, longer than the client's 20 s stall timeout)
- **client_restart**: 60% link; at 40% the client process is killed (SIGKILL) and restarted 2 s later
- **server_restart**: 60% link; at 40% the server process is killed (SIGKILL) and restarted 3 s later

## Failed runs or harness errors

- none
