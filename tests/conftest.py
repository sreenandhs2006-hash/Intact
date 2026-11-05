"""Shared fixtures: a real uvicorn server process we can kill and restart."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerProcess:
    """Runs `uvicorn server.app:app` in a subprocess. stop() is a hard kill (simulated crash)."""

    def __init__(self, data_dir, env_extra=None):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = {**os.environ, "VI_DATA_DIR": str(data_dir), **(env_extra or {})}
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=ROOT, env=self.env)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                h = httpx.get(f"{self.url}/health", timeout=1)
                if h.status_code == 200:
                    if Path(h.json()["data_dir"]).resolve() != Path(self.env["VI_DATA_DIR"]).resolve():
                        raise RuntimeError(f"another server answers on port {self.port}")
                    return self
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)


@pytest.fixture
def make_server(tmp_path):
    servers = []

    def _make(**env):
        s = ServerProcess(tmp_path / "server-data", {k: str(v) for k, v in env.items()})
        servers.append(s)
        return s.start()

    yield _make
    for s in servers:
        s.stop()


@pytest.fixture
def server(make_server):
    return make_server()


@pytest.fixture
def sample_file(tmp_path):
    """3 MB of random bytes. M1 is about bytes, not video, so content does not matter here."""
    p = tmp_path / "sample.bin"
    p.write_bytes(os.urandom(3 * 1024 * 1024))
    return p
