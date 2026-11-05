"""Resumable upload client.

Reliability features (each one is deliberately simple so it can be explained):
- SHA-256 per chunk (server rejects damaged chunks) and for the whole file
  (server refuses COMPLETE unless the full hash matches).
- Retries with exponential backoff and *full jitter*:
  delay = uniform(0, min(cap, base * 2**attempt)). Jitter stops many clients
  retrying in lock-step after an outage.
- Stall detection: httpx read/write timeouts fire when *no bytes move* for
  `stall_timeout` seconds. A slow-but-progressing link is not punished.
- Adaptive chunk size: aim for ~`target_chunk_seconds` per chunk based on the
  measured rate (grow at most 2x per step); halve after a failure. Small chunks
  on weak links mean less is lost when a request dies.
- Resume: the upload id is saved in a small state file keyed by the file's
  SHA-256. After a client or server restart the client asks the server for
  `received_bytes` and continues from there. After every failure it re-syncs
  the offset too, because the server may have stored a chunk whose response
  was lost.
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx

KB, MB = 1024, 1024 * 1024
DEFAULT_STATE_DIR = Path(os.environ.get("VI_CLIENT_STATE", Path.home() / ".nihilent-vi" / "client-state"))


class GiveUp(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(MB), b""):
            h.update(block)
    return h.hexdigest()


class Uploader:
    def __init__(self, base_url, *, http=None, state_dir=DEFAULT_STATE_DIR, log_path=None,
                 initial_chunk=256 * KB, min_chunk=64 * KB, max_chunk=8 * MB,
                 target_chunk_seconds=2.0, stall_timeout=20.0, connect_timeout=10.0,
                 max_consecutive_failures=15, backoff_base=0.5, backoff_cap=30.0,
                 on_chunk=None, sleep=time.sleep):
        self.base = base_url.rstrip("/")
        timeout = httpx.Timeout(connect=connect_timeout, read=stall_timeout,
                                write=stall_timeout, pool=connect_timeout)
        self.http = http or httpx.Client(timeout=timeout)
        self.state_dir = Path(state_dir)
        self.log_path = Path(log_path) if log_path else None
        self.chunk = initial_chunk
        self.min_chunk, self.max_chunk = min_chunk, max_chunk
        self.target_s = target_chunk_seconds
        self.max_failures = max_consecutive_failures
        self.backoff_base, self.backoff_cap = backoff_base, backoff_cap
        self.on_chunk = on_chunk
        self.sleep = sleep
        self.failures = 0      # consecutive, reset on any success
        self.retries = 0       # total over the whole upload
        self.bytes_sent = 0    # includes re-sent bytes

    # ---------- logging ----------
    def log(self, event, **fields):
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(time.time(), 3), "event": event, **fields}) + "\n")

    # ---------- retry helpers ----------
    def _failed(self, what, err):
        self.failures += 1
        self.retries += 1
        if self.failures > self.max_failures:
            self.log("give_up", what=what, error=str(err))
            raise GiveUp(f"{what}: {self.failures - 1} consecutive failures, last: {err}")
        delay = random.uniform(0, min(self.backoff_cap, self.backoff_base * 2 ** (self.failures - 1)))
        self.chunk = max(self.min_chunk, self.chunk // 2)
        self.log("retry", what=what, error=f"{type(err).__name__}: {err}", attempt=self.failures,
                 delay_s=round(delay, 3), next_chunk=self.chunk)
        self.sleep(delay)

    def _request(self, what, method, url, **kw):
        """Send until we get a response that is not a transient error. Returns httpx.Response."""
        while True:
            try:
                r = self.http.request(method, url, **kw)
            except httpx.HTTPError as e:  # connect errors, resets, timeouts (= stalls)
                self._failed(what, e)
                continue
            if r.status_code >= 500 or r.status_code == 429:
                self._failed(what, RuntimeError(f"HTTP {r.status_code}"))
                continue
            return r

    # ---------- session handling ----------
    def _state_file(self, file_sha):
        return self.state_dir / f"{file_sha}.json"

    def _resume_or_create(self, path, size, file_sha):
        sf = self._state_file(file_sha)
        if sf.exists():
            saved = json.loads(sf.read_text())
            if saved.get("base_url") == self.base:
                r = self._request("status", "GET", f"{self.base}/uploads/{saved['upload_id']}")
                if r.status_code == 200 and r.json()["state"] in ("UPLOADING", "STALLED", "COMPLETE"):
                    info = r.json()
                    self.log("resume", upload_id=info["upload_id"], received_bytes=info["received_bytes"],
                             state=info["state"])
                    return info, info["received_bytes"]
        r = self._request("create", "POST", f"{self.base}/uploads",
                          json={"filename": Path(path).name, "size": size, "sha256": file_sha})
        r.raise_for_status()
        info = r.json()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps({"upload_id": info["upload_id"], "base_url": self.base,
                                  "path": str(path)}))
        self.log("created", upload_id=info["upload_id"], size=size, sha256=file_sha)
        return info, 0

    def _sync(self, upload_id):
        r = self._request("status", "GET", f"{self.base}/uploads/{upload_id}")
        r.raise_for_status()
        return r.json()

    # ---------- main entry ----------
    def upload(self, path):
        path = Path(path)
        t0 = time.time()
        size = path.stat().st_size
        file_sha = sha256_file(path)
        self.log("start", path=str(path), size=size, sha256=file_sha)
        info, resumed_bytes, upload_id, received = {}, 0, None, 0
        result_state, detail = "FAILED", None

        try:
            info, resumed_bytes = self._resume_or_create(path, size, file_sha)
            upload_id = info["upload_id"]
            received = info["received_bytes"]
            result_state = info["state"]
            with open(path, "rb") as f:
                while received < size and result_state != "COMPLETE":
                    f.seek(received)
                    data = f.read(min(self.chunk, size - received))
                    chunk_sha = hashlib.sha256(data).hexdigest()
                    t = time.time()
                    try:
                        r = self.http.put(f"{self.base}/uploads/{upload_id}/chunks",
                                          params={"offset": received}, content=data,
                                          headers={"X-Chunk-SHA256": chunk_sha,
                                                   "Content-Type": "application/octet-stream"})
                    except httpx.HTTPError as e:
                        self.bytes_sent += len(data)
                        self._failed("chunk", e)
                        received = self._sync(upload_id)["received_bytes"]
                        continue
                    self.bytes_sent += len(data)
                    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

                    if r.status_code == 200:
                        elapsed = max(time.time() - t, 1e-3)
                        self.failures = 0
                        received = body["received_bytes"]
                        rate = len(data) / elapsed
                        self.chunk = int(min(self.max_chunk, self.chunk * 2,
                                             max(self.min_chunk, rate * self.target_s)))
                        self.log("chunk_ok", offset=received - len(data), length=len(data),
                                 secs=round(elapsed, 3), rate_Bps=int(rate), duplicate=body.get("duplicate"),
                                 next_chunk=self.chunk)
                        if self.on_chunk:
                            self.on_chunk(received, size)
                    elif r.status_code == 409 and "received_bytes" in body:
                        received = body["received_bytes"]  # server tells us where to continue
                        self.log("resync", received_bytes=received, reason=body.get("error"))
                    elif r.status_code == 409:
                        result_state, detail = body.get("state", "FAILED"), body.get("message")
                        break
                    elif r.status_code == 422 or r.status_code >= 500 or r.status_code == 429:
                        self._failed("chunk", RuntimeError(f"HTTP {r.status_code} {body.get('error', '')}"))
                        received = self._sync(upload_id)["received_bytes"]
                    else:
                        raise GiveUp(f"Unexpected HTTP {r.status_code}: {r.text[:200]}")

            if received >= size and result_state != "COMPLETE":
                r = self._request("finalize", "POST", f"{self.base}/uploads/{upload_id}/finalize")
                body = r.json()
                result_state = body.get("state", "FAILED")
                detail = body.get("detail") or body.get("message")
                info = body if r.status_code == 200 else info
        except GiveUp as e:
            result_state, detail = "FAILED", str(e)

        if result_state in ("COMPLETE", "REJECTED", "FAILED"):
            self._state_file(file_sha).unlink(missing_ok=True)

        result = {
            "state": result_state,
            "upload_id": upload_id,
            "size": size,
            "client_sha256": file_sha,
            "server_sha256": info.get("server_sha256"),
            "hash_match": result_state == "COMPLETE" and info.get("server_sha256") == file_sha,
            "duration_s": round(time.time() - t0, 3),
            "retries": self.retries,
            "resumed_bytes": resumed_bytes,
            "bytes_sent": self.bytes_sent,
            "detail": detail,
        }
        self.log("result", **result)
        return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Upload a file with resume and verification.")
    p.add_argument("file")
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--log", help="append JSON-lines events here")
    p.add_argument("--stall-timeout", type=float, default=20.0)
    p.add_argument("--max-failures", type=int, default=15)
    p.add_argument("--max-chunk-kb", type=int, default=8 * 1024)
    args = p.parse_args(argv)
    up = Uploader(args.server, log_path=args.log, stall_timeout=args.stall_timeout,
                  max_consecutive_failures=args.max_failures,
                  max_chunk=args.max_chunk_kb * KB, initial_chunk=min(256 * KB, args.max_chunk_kb * KB))
    result = up.upload(args.file)
    print(json.dumps(result, indent=2))
    return 0 if result["state"] == "COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
