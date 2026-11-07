# Network test results

Recorded 2026-11-08T00:50:12+0530 on `Ubuntu 24.04.5 LTS`, `Linux pai 7.0.0-42-generic #42~24.04.1-Ubuntu SMP PREEMPT_DYNAMIC Mon Oct 19 14:`, tc `tc utility, iproute2-6.1.0, libbpf 1.3.0`, Toxiproxy `{"version": "2.9.0"}`, commit `7c50be86ef`. Video 3756860 bytes, max chunk 512 KB.

Network strength: 100% = 20 Mbit/s, 20 ms RTT, 0% loss · 60% = 5 Mbit/s, 80 ms, 1% · 20% = 500 kbit/s, 400 ms, 5% (loss per direction).

| Scenario | Runs | Success | Success rate | Hash verified | Duration median (min-max) s | Retries mean (max) | Resumed bytes mean | Runs with server STALLED | Faults that hit mid-transfer |
|---|---|---|---|---|---|---|---|---|---|
| stable_100 | 1 | 1 | 100% | 1/1 | 1.91 (1.91-1.91) | 0.0 (0) | 0 | 0 | 0/0 |
| client_restart | 1 | 1 | 100% | 1/1 | 9.07 (9.07-9.07) | 0.0 (0) | 2359296 | 0 | 1/1 |
| server_restart | 1 | 1 | 100% | 1/1 | 18.9 (18.9-18.9) | 4.0 (4) | 0 | 0 | 1/1 |

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
