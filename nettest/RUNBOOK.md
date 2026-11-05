# M4 runbook – network tests on a Linux laptop

Total time: ~15 min setup + ~1.5–2 h unattended runs. Keep the laptop on power with sleep disabled.

**Safe for the laptop:** the tests create a private virtual cable (`vi-cli` ⇄ `vi-srv0`) and a network
namespace (`vi-srv`). netem and Toxiproxy act only on that cable. The laptop's Wi-Fi/Ethernet and its
internet connection are not touched. Everything is removed at the end of a run.

## 0. Take the code to the laptop (on your PC)

```bash
git bundle create ../nihilent.bundle --all
```
Copy `nihilent.bundle` to the laptop (USB / cloud drive).

## 1. Get the code and set up (laptop, Debian/Ubuntu)

```bash
git clone nihilent.bundle nihilent && cd nihilent && git checkout m4-network-tests
bash nettest/setup_linux.sh
```
Installs ffmpeg, iproute2, ethtool, a Python venv with the pinned packages, and Toxiproxy (v2.9.0 binary
from GitHub). Ends by running the M4 unit tests.

## 2. Preflight – must say `PREFLIGHT PASSED`

```bash
sudo .venv/bin/python -m nettest.run preflight
```
It builds the lab and **measures** it: ping RTT at 100% (~20 ms) and 20% (~400 ms), and the upload rate at
20% (≤ 500 kbit/s). If anything says FAIL, stop and bring the full output back – do not run the tests.

## 3. Short smoke run (~2 min)

```bash
sudo .venv/bin/python -m nettest.run run --reps 1 --scenarios stable_100 client_restart server_restart --out nettest/smoke
```
Each line should end with `COMPLETE hash_ok=True`. If not, stop and bring `nettest/smoke` back.

## 4. Full run (5 repetitions of 10 scenarios)

```bash
sudo .venv/bin/python -m nettest.run run --reps 5 2>&1 | tee nettest/runs-console.log
```
Interrupted (lid closed, Ctrl+C)? Run the same command again: finished runs are skipped.

## 5. Bring the evidence back

```bash
sudo chown -R "$USER" nettest/runs nettest/smoke nettest/runs-console.log
git add nettest/runs nettest/smoke nettest/runs-console.log
git commit -m "M4: network test evidence from Linux laptop"
git bundle create ../m4-results.bundle m4-network-tests
```
Copy `m4-results.bundle` back. On your PC: `git pull ../m4-results.bundle m4-network-tests`.
(Large files – uploaded videos, server databases – are git-ignored and stay on the laptop.)

## If a run crashed and left the lab behind

```bash
sudo ip link del vi-cli; sudo ip netns del vi-srv; sudo pkill -f toxiproxy-server
```

## What is recorded per run (`nettest/runs/<scenario>/rep<N>/`)

| File | Content |
|---|---|
| `client.jsonl` | every client event: chunks, retries with errors, resumes, final result |
| `client_stdout_N.json` | result printed by each client process |
| `server.log` | server output, all restarts |
| `actions.jsonl` | every tc / Toxiproxy / kill action, with timestamps and command output |
| `tc_stats.txt` | netem counters: packets sent, dropped, queued |
| `server_upload.json` | server's own state, hashes and state-change events (UPLOADING/STALLED/COMPLETE) |
| `result.json` | metrics computed from the above |

`nettest/runs/summary.md` and `summary.json` aggregate success rate, duration, retries, resumed bytes and
hash verification per scenario, plus `environment.json` (kernel, tc and Toxiproxy versions, git commit,
video hash, profile and scenario definitions).
