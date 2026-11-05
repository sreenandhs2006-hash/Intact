"""SQLite storage for upload sessions, accepted chunks and state-change events.

One short-lived connection per operation keeps this safe to use from FastAPI's
thread pool without sharing connection objects between threads.
"""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id               TEXT PRIMARY KEY,
    filename         TEXT NOT NULL,
    size             INTEGER NOT NULL,
    sha256           TEXT NOT NULL,      -- full-file hash declared by the client
    state            TEXT NOT NULL,
    received_bytes   INTEGER NOT NULL DEFAULT 0,  -- contiguous verified prefix on disk
    chunks_received  INTEGER NOT NULL DEFAULT 0,
    duplicate_chunks INTEGER NOT NULL DEFAULT 0,
    rejected_chunks  INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL,
    last_activity_at REAL NOT NULL,
    completed_at     REAL,
    server_sha256    TEXT,               -- hash the server computed at finalize
    detail           TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    upload_id   TEXT NOT NULL,
    offset      INTEGER NOT NULL,
    length      INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    received_at REAL NOT NULL,
    PRIMARY KEY (upload_id, offset)
);
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id TEXT NOT NULL,
    ts        REAL NOT NULL,
    event     TEXT NOT NULL,
    detail    TEXT
);
"""


def db_path():
    return config.DATA_DIR / "uploads.sqlite3"


def init():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")  # a COMMIT survives a power cut / crash
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_event(conn, upload_id, ts, event, detail=None):
    conn.execute(
        "INSERT INTO events (upload_id, ts, event, detail) VALUES (?, ?, ?, ?)",
        (upload_id, ts, event, detail),
    )
