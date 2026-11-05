"""M1 tests: reliable, verified, resumable transfer. All run against a real server process."""
import hashlib
import json
import random
import threading
import time

import httpx
import pytest

from client.uploader import KB, Uploader, sha256_file


def h(b):
    return hashlib.sha256(b).hexdigest()


def stored_file(tmp_path, upload_id):
    return tmp_path / "server-data" / "files" / f"{upload_id}.bin"


def make_uploader(server, tmp_path, **kw):
    kw.setdefault("sleep", lambda s: time.sleep(min(s, 0.05)))  # keep tests fast, keep behaviour
    return Uploader(server.url, state_dir=tmp_path / "client-state",
                    log_path=tmp_path / "client.jsonl", **kw)


def create(server, data, sha=None):
    r = httpx.post(f"{server.url}/uploads", json={"filename": "x.bin", "size": len(data),
                                                   "sha256": sha or h(data)})
    assert r.status_code == 201
    return r.json()["upload_id"]


def put(server, uid, offset, data, sha=None):
    return httpx.put(f"{server.url}/uploads/{uid}/chunks", params={"offset": offset},
                     content=data, headers={"X-Chunk-SHA256": sha or h(data)})


# ---------------- happy path ----------------

def test_upload_completes_and_bytes_match(server, sample_file, tmp_path):
    result = make_uploader(server, tmp_path).upload(sample_file)
    assert result["state"] == "COMPLETE"
    assert result["hash_match"] is True
    assert result["server_sha256"] == sha256_file(sample_file)
    assert stored_file(tmp_path, result["upload_id"]).read_bytes() == sample_file.read_bytes()


def test_chunk_size_adapts_upwards_on_good_link(server, sample_file, tmp_path):
    make_uploader(server, tmp_path, initial_chunk=64 * KB).upload(sample_file)
    sizes = [e["length"] for e in map(json.loads, open(tmp_path / "client.jsonl"))
             if e["event"] == "chunk_ok"]
    assert sizes[0] == 64 * KB and max(sizes) > sizes[0]


# ---------------- server-side protocol rules ----------------

def test_damaged_chunk_is_rejected_and_not_stored(server):
    data = b"a" * 1000
    uid = create(server, data)
    r = put(server, uid, 0, data, sha=h(b"something else"))
    assert r.status_code == 422
    s = httpx.get(f"{server.url}/uploads/{uid}").json()
    assert s["received_bytes"] == 0 and s["rejected_chunks"] == 1


def test_duplicate_chunk_is_idempotent(server):
    data = b"abc" * 1000
    uid = create(server, data)
    first, second = put(server, uid, 0, data[:1000]), put(server, uid, 0, data[:1000])
    assert first.json()["duplicate"] is False
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert second.json()["received_bytes"] == 1000


def test_different_bytes_at_stored_offset_conflict(server):
    data = b"abc" * 1000
    uid = create(server, data)
    put(server, uid, 0, data[:1000])
    r = put(server, uid, 0, b"z" * 1000)
    assert r.status_code == 409 and r.json()["error"] == "conflict"


def test_gap_returns_expected_offset(server):
    data = b"abc" * 1000
    uid = create(server, data)
    r = put(server, uid, 500, data[500:1000])
    assert r.status_code == 409 and r.json()["received_bytes"] == 0


def test_finalize_refuses_incomplete_upload(server):
    data = b"abc" * 1000
    uid = create(server, data)
    put(server, uid, 0, data[:1000])
    r = httpx.post(f"{server.url}/uploads/{uid}/finalize")
    assert r.status_code == 409 and r.json()["error"] == "incomplete"
    assert httpx.get(f"{server.url}/uploads/{uid}").json()["state"] == "UPLOADING"


def test_wrong_full_hash_is_rejected_never_complete(server):
    data = b"abc" * 1000
    uid = create(server, data, sha=h(b"not this file"))
    assert put(server, uid, 0, data).status_code == 200
    r = httpx.post(f"{server.url}/uploads/{uid}/finalize").json()
    assert r["state"] == "REJECTED" and r["verified"] is False
    assert put(server, uid, 0, data).status_code == 409  # terminal: no more chunks


def test_file_altered_during_upload_is_rejected(server, sample_file, tmp_path):
    def alter(received, size):
        if received < size:  # flip one byte later in the file, after hashing started
            with open(sample_file, "r+b") as f:
                f.seek(size - 10)
                b = f.read(1)
                f.seek(size - 10)
                f.write(bytes([b[0] ^ 0xFF]))
    up = make_uploader(server, tmp_path, initial_chunk=256 * KB, max_chunk=256 * KB)
    called = {"n": 0}

    def once(received, size):
        if called["n"] == 0:
            alter(received, size)
        called["n"] += 1
    up.on_chunk = once
    result = up.upload(sample_file)
    assert result["state"] == "REJECTED" and result["hash_match"] is False


# ---------------- states ----------------

def test_stalled_then_resumed_then_failed(make_server):
    server = make_server(VI_STALL_SECONDS=1, VI_FAIL_SECONDS=3)
    data = b"abc" * 1000
    uid = create(server, data)
    put(server, uid, 0, data[:1000])
    time.sleep(1.3)
    assert httpx.get(f"{server.url}/uploads/{uid}").json()["state"] == "STALLED"
    assert put(server, uid, 1000, data[1000:2000]).json()["state"] == "UPLOADING"
    events = [e["event"] for e in httpx.get(f"{server.url}/uploads/{uid}/events").json()]
    assert "STALLED" in events and "RESUMED" in events
    time.sleep(3.3)
    assert httpx.get(f"{server.url}/uploads/{uid}").json()["state"] == "FAILED"
    assert put(server, uid, 2000, data[2000:]).status_code == 409


# ---------------- resume and restarts ----------------

class Crash(Exception):
    pass


def test_resume_after_client_crash(server, sample_file, tmp_path):
    def crash_after_1mb(received, size):
        if received >= 1024 * KB:
            raise Crash()
    first = make_uploader(server, tmp_path, max_chunk=256 * KB, on_chunk=crash_after_1mb)
    with pytest.raises(Crash):
        first.upload(sample_file)

    second = make_uploader(server, tmp_path, max_chunk=256 * KB)  # fresh process state
    result = second.upload(sample_file)
    assert result["state"] == "COMPLETE" and result["hash_match"]
    assert result["resumed_bytes"] >= 1024 * KB
    assert result["bytes_sent"] <= sample_file.stat().st_size - result["resumed_bytes"]


def test_server_crash_and_restart_mid_upload(server, sample_file, tmp_path):
    fired = {"done": False}
    restart = threading.Timer(1.5, server.start)              # back after 1.5 s

    def crash_server(received, size):
        if not fired["done"] and received >= 512 * KB:
            fired["done"] = True
            server.stop()                                     # hard kill
            restart.start()

    up = make_uploader(server, tmp_path, max_chunk=256 * KB, on_chunk=crash_server,
                       sleep=time.sleep, backoff_base=0.2, backoff_cap=1.0)
    result = up.upload(sample_file)
    restart.join()
    assert fired["done"]
    assert result["state"] == "COMPLETE" and result["hash_match"]
    assert result["retries"] > 0


class FlakyTransport(httpx.BaseTransport):
    """Fails some requests before sending (connection error) and some after the
    server processed them (response lost) - the case idempotency exists for."""

    def __init__(self, seed, before=0.2, after=0.15):
        self.inner = httpx.HTTPTransport()
        self.rng = random.Random(seed)
        self.before, self.after = before, after

    def handle_request(self, request):
        r = self.rng.random()
        if r < self.before:
            raise httpx.ConnectError("injected: connection failed", request=request)
        response = self.inner.handle_request(request)
        if r < self.before + self.after:
            response.read()
            response.close()
            raise httpx.ReadTimeout("injected: response lost", request=request)
        return response


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_flaky_network_still_completes_with_correct_hash(server, sample_file, tmp_path, seed):
    up = make_uploader(server, tmp_path, http=httpx.Client(transport=FlakyTransport(seed)),
                       max_chunk=256 * KB, max_consecutive_failures=30)
    result = up.upload(sample_file)
    assert result["state"] == "COMPLETE" and result["hash_match"]
    assert result["retries"] > 0
    assert stored_file(tmp_path, result["upload_id"]).read_bytes() == sample_file.read_bytes()


def test_client_gives_up_when_server_never_returns(tmp_path, sample_file):
    up = Uploader("http://127.0.0.1:9", state_dir=tmp_path / "cs", max_consecutive_failures=3,
                  sleep=lambda s: None, connect_timeout=1)
    result = up.upload(sample_file)
    assert result["state"] == "FAILED" and "consecutive failures" in result["detail"]
    assert up.retries == 4


# ---------------- the analysis gate ----------------

def test_only_verified_files_can_be_opened_for_analysis(monkeypatch, tmp_path):
    from server import config, db, uploads
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "inproc")
    db.init()
    data = b"video bytes" * 100
    uid = uploads.create("v.mp4", len(data), h(data))["upload_id"]
    uploads.put_chunk(uid, 0, data, h(data))
    with pytest.raises(uploads.UploadError, match="not COMPLETE"):
        uploads.verified_file(uid)                      # all bytes there, but not verified yet
    assert uploads.finalize(uid)["state"] == "COMPLETE"
    path = uploads.verified_file(uid)
    assert path.read_bytes() == data
    path.write_bytes(b"tampered" + data[8:])            # changed on disk after verification
    with pytest.raises(uploads.UploadError, match="no longer matches"):
        uploads.verified_file(uid)


# ---------------- retry policy (unit level) ----------------

def test_backoff_is_exponential_capped_and_jittered(monkeypatch, tmp_path):
    bounds = []
    monkeypatch.setattr("client.uploader.random.uniform", lambda a, b: bounds.append(b) or 0)
    up = Uploader("http://x", state_dir=tmp_path, backoff_base=0.5, backoff_cap=4,
                  max_consecutive_failures=10, sleep=lambda s: None, initial_chunk=1024 * KB)
    for _ in range(6):
        up._failed("test", RuntimeError("x"))
    assert bounds == [0.5, 1, 2, 4, 4, 4]
    assert up.chunk == 64 * KB  # halved each failure, floored at min_chunk
