"""M4 network test orchestrator (Linux, run as root).

    sudo .venv/bin/python -m nettest.run preflight
    sudo .venv/bin/python -m nettest.run run --reps 5            # all scenarios, ~1-2 h
    sudo .venv/bin/python -m nettest.run run --scenarios stable_20 --reps 5
    .venv/bin/python -m nettest.run summarize

Every run writes raw evidence to nettest/runs/<scenario>/rep<N>/:
  client.jsonl         every client event (chunks, retries, resumes, result)
  client_stdout_*.json final result printed by each client process
  server.log           server stdout/stderr (all restarts appended)
  actions.jsonl        every tc / Toxiproxy action with timestamps and command output
  tc_stats.txt         netem counters (sent/dropped packets) after the run
  server_upload.json   the server's own view: state, hashes, state-change events
  result.json          metrics computed from the above
Runs with an existing result.json are skipped, so an interrupted session can continue.

--no-netem runs everything except tc/netns (server on localhost). That checks the HARNESS
only; its output is labelled as such and is not M4 evidence.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from . import metrics
from .netlab import NS, SRV_IP, NetLab
from .profiles import PROFILES
from .scenarios import SCENARIOS
from .toxi import LISTEN, Toxi

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO = ROOT / "nettest" / "video30s.mp4"
DEFAULT_TOXIPROXY = ROOT / "nettest" / "bin" / ("toxiproxy-server.exe" if os.name == "nt" else "toxiproxy-server")
SERVER_PORT = 8000       # inside the server namespace (Linux)
LOCAL_PORT = 18080       # --no-netem harness check on localhost, away from any dev server on 8000
MAX_CHUNK_KB = 512       # small chunks so faults land mid-transfer even at 100% strength
RUN_TIMEOUT_S = 40 * 60  # a run that takes longer is recorded as failed


# ------------------------------------------------------------------ processes
def popen(cmd, log_file, env):
    kw = {"start_new_session": True} if os.name != "nt" else {}
    return subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env, cwd=ROOT, **kw)


def hard_kill(proc):
    if proc and proc.poll() is None:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)  # the whole group: `ip netns exec` + python
        else:
            proc.kill()
        proc.wait(10)


class Run:
    def __init__(self, args, scenario, rep, lab, toxi):
        self.args, self.name, self.sc = args, scenario, SCENARIOS[scenario]
        self.dir = Path(args.out) / scenario / f"rep{rep}"
        self.lab, self.toxi = lab, toxi
        self.netem = not args.no_netem
        self.server_host = SRV_IP if self.netem else "127.0.0.1"
        self.port = SERVER_PORT if self.netem else LOCAL_PORT
        self.server_url = f"http://{self.server_host}:{self.port}"
        self.client = self.server = None
        self.client_no = 0
        self.lock = threading.Lock()
        self.faults = []  # (action, time) - checked against the client log after the run

    def act(self, event, **f):
        with open(self.dir / "actions.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": round(time.time(), 3), "event": event, **f}) + "\n")

    # -- server / client
    def start_server(self):
        env = {**os.environ, "VI_DATA_DIR": str(self.dir / "server-data"), "VI_STALL_SECONDS": "15"}
        cmd = [sys.executable, "-m", "uvicorn", "server.app:app", "--host", self.server_host,
               "--port", str(self.port), "--log-level", "warning"]
        if self.netem:
            cmd = ["ip", "netns", "exec", NS] + cmd
        self.server = popen(cmd, open(self.dir / "server.log", "a"), env)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                h = httpx.get(f"{self.server_url}/health", timeout=2)
                if h.status_code == 200:
                    # make sure the answer comes from OUR server (a stray server on the same
                    # port once answered for a harness run whose own server failed to bind)
                    if Path(h.json().get("data_dir", "")).resolve() != (self.dir / "server-data").resolve():
                        raise RuntimeError(f"another server answers on port {self.port}: {h.json()}")
                    self.act("server_started", pid=self.server.pid)
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("server did not start")

    def start_client(self):
        self.client_no += 1
        env = {**os.environ, "VI_CLIENT_STATE": str(self.dir / "client-state")}
        cmd = [sys.executable, "-m", "client.uploader", str(self.args.video), "--server", f"http://{LISTEN}",
               "--log", str(self.dir / "client.jsonl"), "--max-chunk-kb", str(MAX_CHUNK_KB)]
        with self.lock:
            self.client = popen(cmd, open(self.dir / f"client_stdout_{self.client_no}.json", "w"), env)
        self.act("client_started", n=self.client_no, pid=self.client.pid)

    # -- scenario actions
    FAULTS = {"profile", "disable", "toxic", "kill_client", "kill_server"}

    def do(self, action):
        kind = action[0]
        if kind in self.FAULTS:
            self.faults.append((kind, time.time()))
        self.act("action", action=list(action))
        if kind == "profile":
            if self.netem:
                self.lab.set_profile(PROFILES[action[1]])
            else:
                self.act("skipped_no_netem", action=list(action))
        elif kind == "wait":
            time.sleep(action[1])
        elif kind == "disable":
            self.toxi.set_enabled(False)
        elif kind == "enable":
            self.toxi.set_enabled(True)
        elif kind == "toxic":
            self.toxi.add(action[1], action[2], timeout=0)
        elif kind == "untoxic":
            self.toxi.remove(action[1])
        elif kind == "kill_client":
            with self.lock:
                hard_kill(self.client)
        elif kind == "start_client":
            self.start_client()
        elif kind == "kill_server":
            hard_kill(self.server)
        elif kind == "start_server":
            self.start_server()
        else:
            raise ValueError(kind)

    def execute(self):
        if (self.dir / "result.json").exists():
            print(f"  skip {self.name}/{self.dir.name} (done)")
            return json.loads((self.dir / "result.json").read_text())
        if self.dir.exists():
            shutil.rmtree(self.dir)  # an interrupted run starts again from scratch
        self.dir.mkdir(parents=True)
        self.lab.action_log = self.dir / "actions.jsonl"
        self.toxi.log = self.act
        self.toxi.reset()
        if self.netem:
            self.lab.set_profile(PROFILES[self.sc["base"]])
        self.start_server()
        t0 = time.time()
        self.start_client()

        # Steps run one after another on a single worker: a step never starts while the
        # previous one's window (e.g. a 2 s reset) is still open.
        fired, queue, self.errors = set(), [], []
        worker = None

        def run_queue():
            while queue:
                i, actions = queue.pop(0)
                for x in actions:
                    try:
                        self.do(x)
                    except Exception as e:  # recorded in the result, never silently lost
                        self.errors.append(f"step {i} {list(x)}: {type(e).__name__}: {e}")
                        self.act("action_error", step=i, action=list(x), error=str(e))

        timed_out = False
        while True:
            p = metrics.progress(metrics.read_log(self.dir / "client.jsonl"))
            for i, (at, actions) in enumerate(self.sc["steps"]):
                if i not in fired and p >= at:
                    fired.add(i)
                    self.act("step_fired", step=i, at=at, progress=round(p, 4))
                    queue.append((i, actions))
            if queue and not (worker and worker.is_alive()):
                worker = threading.Thread(target=run_queue, daemon=True)
                worker.start()
            with self.lock:
                client_done = self.client.poll() is not None
            if client_done and not queue and not (worker and worker.is_alive()):
                with self.lock:
                    if self.client.poll() is not None:
                        break
            if time.time() - t0 > RUN_TIMEOUT_S:
                timed_out = True
                self.act("run_timeout")
                with self.lock:
                    hard_kill(self.client)
                break
            time.sleep(0.25)

        # restore a clean link to collect the server's view, then stop
        self.toxi.reset()
        if self.netem:
            stats = self.lab.show()
            (self.dir / "tc_stats.txt").write_text(
                f"# client side ({self.sc['base']} base)\n{stats['client_side']}\n# server side\n{stats['server_side']}\n")
            self.lab.set_profile(PROFILES["100"])
        events = metrics.read_log(self.dir / "client.jsonl")
        upload_id = next((e["upload_id"] for e in reversed(events) if e.get("upload_id")), None)
        server_info = None
        if upload_id:
            try:
                server_info = httpx.get(f"{self.server_url}/uploads/{upload_id}", timeout=10).json()
                server_info["events"] = httpx.get(f"{self.server_url}/uploads/{upload_id}/events", timeout=10).json()
            except httpx.HTTPError as e:
                server_info = {"error": str(e)}
        (self.dir / "server_upload.json").write_text(json.dumps(server_info, indent=2))
        hard_kill(self.server)

        landed = [metrics.fault_landed(events, t) for _, t in self.faults]
        self.act("faults_checked", faults=[{"action": k, "t": round(t, 3), "landed_mid_transfer": l}
                                           for (k, t), l in zip(self.faults, landed)])
        result = {"scenario": self.name, "rep": self.dir.name, "netem": self.netem,
                  "steps_total": len(self.sc["steps"]), "steps_fired": len(fired), "timed_out": timed_out,
                  "faults_total": len(self.faults), "faults_mid_transfer": sum(landed),
                  "harness_errors": self.errors,
                  **metrics.run_metrics(events, server_info)}
        (self.dir / "result.json").write_text(json.dumps(result, indent=2))
        print(f"  {self.name}/{self.dir.name}: {result['final_state']} hash_ok={result['server_sha256_matches_client']}"
              f" {result['duration_s']}s retries={result['retries']} resumed={result['resumed_bytes']}"
              f" faults mid-transfer {result['faults_mid_transfer']}/{result['faults_total']}"
              + (f" HARNESS ERRORS: {self.errors}" if self.errors else ""))
        return result


# ------------------------------------------------------------------ environment
def sh(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return f"unavailable: {e}"


def environment(args, toxi):
    v = Path(args.video)
    os_release = ""
    if Path("/etc/os-release").exists():
        os_release = next((l.split("=", 1)[1].strip('"') for l in Path("/etc/os-release").read_text().splitlines()
                           if l.startswith("PRETTY_NAME=")), "")
    return {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "netem": not args.no_netem,
        "platform": platform.platform(), "os_release": os_release, "uname": sh(["uname", "-a"]),
        "python": sys.version.split()[0], "tc": sh(["tc", "-V"]), "toxiproxy": toxi.version(),
        "git_commit": sh(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
        "video": {"file": v.name, "size_bytes": v.stat().st_size,
                  "sha256": hashlib.sha256(v.read_bytes()).hexdigest()},
        "max_chunk_kb": MAX_CHUNK_KB,
        "profiles": {k: vars(p) for k, p in PROFILES.items()},
        "scenarios": SCENARIOS,
    }


def make_video(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-t", "30", "-c:v", "libx264", "-b:v", "1M", "-maxrate", "1M", "-bufsize", "2M",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], check=True)


# ------------------------------------------------------------------ commands
def start_toxiproxy(args):
    exe = Path(args.toxiproxy)
    if not exe.exists():
        sys.exit(f"Toxiproxy not found at {exe}: run nettest/setup_linux.sh")
    proc = subprocess.Popen([str(exe), "-host", "127.0.0.1", "-port", "8474"],
                            stdout=open(Path(args.out) / "toxiproxy.log", "a"), stderr=subprocess.STDOUT)
    toxi = Toxi()
    for _ in range(50):
        if toxi.version():
            return proc, toxi
        time.sleep(0.1)
    sys.exit("Toxiproxy did not start")


def cmd_preflight(args):
    """Prove the lab works BEFORE spending an hour: netem delay and rate are measured, not assumed."""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"[{'OK' if cond else 'FAIL'}] {name} {detail}")

    check("running as root", os.name != "nt" and os.geteuid() == 0)
    for tool in ("ip", "tc", "ping", "ffmpeg", "ffprobe"):
        check(f"{tool} installed", shutil.which(tool))
    check("ethtool installed (recommended)", shutil.which("ethtool") or True, "" if shutil.which("ethtool") else "missing")
    check("sch_netem module", subprocess.run(["modprobe", "sch_netem"]).returncode == 0)
    check("toxiproxy binary", Path(args.toxiproxy).exists(), str(args.toxiproxy))
    if not ok:
        sys.exit("preflight failed")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    lab = NetLab(action_log=Path(args.out) / "preflight_actions.jsonl")
    lab.up()
    try:
        for name in ("100", "20"):
            prof = PROFILES[name]
            lab.set_profile(prof)
            out = sh(["ping", "-c", "10", "-i", "0.3", SRV_IP])
            rtt = next((l for l in out.splitlines() if "min/avg" in l), "")
            avg = float(rtt.split("=")[1].split("/")[1]) if rtt else None
            check(f"profile {name}: ping RTT ~{prof.rtt_ms} ms", avg and abs(avg - prof.rtt_ms) < prof.rtt_ms * 0.3 + 5,
                  f"(measured avg {avg} ms)")
        # throughput at 20%: push 256 KB through a TCP connection into the namespace
        lab.set_profile(PROFILES["20"])
        srv = subprocess.Popen(["ip", "netns", "exec", NS, sys.executable, "-c",
                                "import socket;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
                                f"s.bind(('{SRV_IP}',9999));s.listen(1);c,_=s.accept();n=0\n"
                                "while (d:=c.recv(65536)): n+=len(d)\nc.sendall(b'ok')"])
        time.sleep(1)
        import socket
        data = os.urandom(256 * 1024)
        t = time.time()
        with socket.create_connection((SRV_IP, 9999), timeout=60) as s:
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)
            s.recv(2)
        secs = time.time() - t
        kbit = len(data) * 8 / 1000 / secs
        check("profile 20: upload rate <= 500 kbit/s", kbit <= 520, f"(measured {kbit:.0f} kbit/s over {secs:.1f} s)")
        srv.kill()
        print(lab.show()["client_side"])
    finally:
        lab.down()
    print("PREFLIGHT", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


def cmd_run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not args.no_netem and (os.name == "nt" or os.geteuid() != 0):
        sys.exit("run as root (sudo) on Linux, or pass --no-netem for a harness check")
    if not Path(args.video).exists():
        make_video(Path(args.video))
    toxi_proc, toxi = start_toxiproxy(args)
    lab = NetLab(dry_run=args.no_netem)
    try:
        if not args.no_netem:
            lab.up()
        toxi.create_proxy(f"{SRV_IP}:{SERVER_PORT}" if not args.no_netem else f"127.0.0.1:{LOCAL_PORT}")
        (out / "environment.json").write_text(json.dumps(environment(args, toxi), indent=2))
        names = args.scenarios or list(SCENARIOS)
        for rep in range(1, args.reps + 1):  # interleave scenarios so slow drift affects all equally
            for name in names:
                Run(args, name, rep, lab, toxi).execute()
    finally:
        if not args.no_netem:
            lab.down()
        toxi_proc.kill()
    cmd_summarize(args)


def cmd_summarize(args):
    out = Path(args.out)
    results = [json.loads(p.read_text()) for p in sorted(out.glob("*/rep*/result.json"))]
    if not results:
        sys.exit(f"no results in {out}")
    env = json.loads((out / "environment.json").read_text()) if (out / "environment.json").exists() else {}
    table = metrics.summarize(results)
    (out / "summary.json").write_text(json.dumps({"environment": env, "scenarios": table, "runs": results}, indent=2))
    lines = ["# Network test results", ""]
    if not env.get("netem", True) or any(not r["netem"] for r in results):
        lines += ["> **HARNESS CHECK ONLY - netem was disabled. Not M4 evidence.**", ""]
    lines += [f"Recorded {env.get('recorded_at')} on `{env.get('os_release') or env.get('platform')}`, "
              f"`{env.get('uname', '')[:80]}`, tc `{env.get('tc')}`, Toxiproxy `{env.get('toxiproxy')}`, "
              f"commit `{str(env.get('git_commit'))[:10]}`. Video {env.get('video', {}).get('size_bytes')} bytes, "
              f"max chunk {env.get('max_chunk_kb')} KB.", "",
              "Network strength: 100% = 20 Mbit/s, 20 ms RTT, 0% loss · 60% = 5 Mbit/s, 80 ms, 1% · "
              "20% = 500 kbit/s, 400 ms, 5% (loss per direction).", "",
              "| Scenario | Runs | Success | Success rate | Hash verified | Duration median (min-max) s | "
              "Retries mean (max) | Resumed bytes mean | Runs with server STALLED | Faults that hit mid-transfer |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for name in SCENARIOS:
        if name in table:
            t = table[name]
            lines.append(f"| {name} | {t['runs']} | {t['successes']} | {t['success_rate']:.0%} | {t['hash_verified']}/{t['runs']} | "
                         f"{t['duration_s_median']} ({t['duration_s_min']}-{t['duration_s_max']}) | "
                         f"{t['retries_mean']} ({t['retries_max']}) | {t['resumed_bytes_mean']} | "
                         f"{t['server_stalled_runs']} | {t['faults_mid_transfer']}/{t['faults_total']} |")
    lines += ["", "## Scenarios", ""] + [f"- **{n}**: {s['description']}" for n, s in SCENARIOS.items()]
    failed = [r for r in results if not r["success"] or r.get("harness_errors")]
    lines += ["", "## Failed runs or harness errors", ""] + ([f"- {r['scenario']}/{r['rep']}: {r['final_state']}, timed_out={r['timed_out']}, "
                                            f"harness errors={r.get('harness_errors') or 'none'}"
                                            for r in failed] or ["- none"])
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lines))


def main(argv=None):
    p = argparse.ArgumentParser(description="M4 network tests")
    p.add_argument("command", choices=["preflight", "run", "summarize"])
    p.add_argument("--out", default=str(ROOT / "nettest" / "runs"))
    p.add_argument("--video", default=str(DEFAULT_VIDEO))
    p.add_argument("--toxiproxy", default=str(DEFAULT_TOXIPROXY))
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--scenarios", nargs="*", choices=list(SCENARIOS))
    p.add_argument("--no-netem", action="store_true", help="harness check without tc/netns (not evidence)")
    args = p.parse_args(argv)
    {"preflight": cmd_preflight, "run": cmd_run, "summarize": cmd_summarize}[args.command](args)


if __name__ == "__main__":
    main()
