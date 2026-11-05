"""Upload session logic: create, accept chunks, refresh state, finalize.

Design (offset-based, similar in spirit to the tus resumable-upload protocol):
- The client uploads chunks sequentially. Each chunk is addressed by its byte
  offset, so chunk size can change between requests (adaptive chunking).
- The server only ever extends a contiguous, hash-verified prefix of the file
  (`received_bytes`). Resuming = "ask the server for received_bytes, continue".
- Re-sending a chunk that is already stored is a no-op if its bytes match
  (idempotent retries), and a conflict if they differ.
- COMPLETE is set only after the server re-reads the whole file from disk and
  its SHA-256 equals the hash the client declared when the session was created.
"""
import hashlib
import json
import os
import re
import threading
import time
import uuid

from . import config, db

UPLOADING, STALLED, FAILED, REJECTED, COMPLETE = (
    "UPLOADING", "STALLED", "FAILED", "REJECTED", "COMPLETE")
TERMINAL = {FAILED, REJECTED, COMPLETE}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# One lock per upload serialises a retried request racing its own original.
# (Single server process; a multi-process deployment would need a DB/file lock.)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class UploadError(Exception):
    """An error the API turns into an HTTP response."""

    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _lock(upload_id):
    with _locks_guard:
        return _locks.setdefault(upload_id, threading.Lock())


def part_path(upload_id):
    return config.DATA_DIR / "files" / f"{upload_id}.part"


def final_path(upload_id):
    return config.DATA_DIR / "files" / f"{upload_id}.bin"


def sha256_file(path, start=0, length=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining is None or remaining > 0:
            block = f.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
            if not block:
                break
            h.update(block)
            if remaining is not None:
                remaining -= len(block)
    return h.hexdigest()


def _row(conn, upload_id):
    row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    if row is None:
        raise UploadError(404, "not_found", "Unknown upload id")
    return row


def _refresh_state(conn, row, now):
    """Apply time-based transitions (UPLOADING -> STALLED -> FAILED) and persist them."""
    if row["state"] in TERMINAL:
        return row
    idle = now - row["last_activity_at"]
    new = FAILED if idle >= config.FAIL_SECONDS else STALLED if idle >= config.STALL_SECONDS else UPLOADING
    if new != row["state"]:
        detail = f"no chunk for {idle:.1f}s"
        conn.execute("UPDATE uploads SET state = ?, detail = ? WHERE id = ?", (new, detail, row["id"]))
        db.add_event(conn, row["id"], now, new, detail)
        row = _row(conn, row["id"])
    return row


def to_public(row):
    return {
        "upload_id": row["id"],
        "filename": row["filename"],
        "size": row["size"],
        "sha256": row["sha256"],
        "state": row["state"],
        "received_bytes": row["received_bytes"],
        "progress": round(row["received_bytes"] / row["size"], 4),
        "chunks_received": row["chunks_received"],
        "duplicate_chunks": row["duplicate_chunks"],
        "rejected_chunks": row["rejected_chunks"],
        "created_at": row["created_at"],
        "last_activity_at": row["last_activity_at"],
        "completed_at": row["completed_at"],
        "server_sha256": row["server_sha256"],
        "verified": row["state"] == COMPLETE,
        "detail": row["detail"],
    }


def create(filename, size, sha256):
    sha256 = (sha256 or "").lower()
    if not SHA256_RE.match(sha256):
        raise UploadError(400, "bad_sha256", "sha256 must be 64 hex characters")
    if not (0 < size <= config.MAX_FILE_BYTES):
        raise UploadError(400, "bad_size", f"size must be 1..{config.MAX_FILE_BYTES} bytes")
    upload_id = uuid.uuid4().hex
    now = time.time()
    part = part_path(upload_id)
    part.parent.mkdir(parents=True, exist_ok=True)
    part.touch()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO uploads (id, filename, size, sha256, state, created_at, last_activity_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (upload_id, filename[:255], size, sha256, UPLOADING, now, now),
        )
        db.add_event(conn, upload_id, now, "CREATED", f"size={size}")
        return to_public(_row(conn, upload_id))


def get(upload_id):
    with db.connect() as conn:
        return to_public(_refresh_state(conn, _row(conn, upload_id), time.time()))


def list_all(limit=50):
    now = time.time()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM uploads ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [to_public(_refresh_state(conn, r, now)) for r in rows]


def events(upload_id, limit=200):
    with db.connect() as conn:
        _row(conn, upload_id)
        rows = conn.execute(
            "SELECT ts, event, detail FROM events WHERE upload_id = ? ORDER BY id DESC LIMIT ?",
            (upload_id, limit)).fetchall()
        return [dict(r) for r in rows]


def put_chunk(upload_id, offset, data, chunk_sha256):
    """Store one chunk. Returns (public_state, duplicate: bool)."""
    with _lock(upload_id), db.connect() as conn:
        now = time.time()
        row = _refresh_state(conn, _row(conn, upload_id), now)
        if row["state"] in TERMINAL:
            raise UploadError(409, "terminal_state", f"Upload is {row['state']}", state=row["state"])
        n = len(data)
        if n == 0:
            raise UploadError(400, "empty_chunk", "Chunk is empty")
        if n > config.MAX_CHUNK_BYTES:
            raise UploadError(413, "chunk_too_large", f"Max chunk is {config.MAX_CHUNK_BYTES} bytes")
        if offset < 0 or offset + n > row["size"]:
            raise UploadError(400, "bad_range", "Chunk lies outside the declared file size")

        actual = hashlib.sha256(data).hexdigest()
        if actual != (chunk_sha256 or "").lower():
            # Damaged in transit (or wrong header): reject, store nothing, client re-sends.
            conn.execute("UPDATE uploads SET rejected_chunks = rejected_chunks + 1 WHERE id = ?",
                         (upload_id,))
            db.add_event(conn, upload_id, now, "CHUNK_HASH_MISMATCH", f"offset={offset} len={n}")
            conn.commit()  # keep the counter/event even though we raise
            raise UploadError(422, "chunk_hash_mismatch", "Chunk SHA-256 does not match its bytes")

        received = row["received_bytes"]
        if offset + n <= received:
            # Retry of a chunk we already hold: idempotent only if the bytes are identical.
            if sha256_file(part_path(upload_id), offset, n) == actual:
                conn.execute("UPDATE uploads SET duplicate_chunks = duplicate_chunks + 1 WHERE id = ?",
                             (upload_id,))
                return to_public(_row(conn, upload_id)), True
            raise UploadError(409, "conflict", "Different bytes already stored at this offset",
                              received_bytes=received)
        if offset != received:
            # Gap or partial overlap: tell the client where to continue from.
            raise UploadError(409, "offset_mismatch", f"Expected offset {received}",
                              received_bytes=received)

        # Write at the offset, cut any stale tail left by a crash, force to disk,
        # and only then advance received_bytes in the database.
        with open(part_path(upload_id), "r+b") as f:
            f.seek(offset)
            f.write(data)
            f.truncate(offset + n)
            f.flush()
            os.fsync(f.fileno())
        conn.execute(
            "INSERT OR REPLACE INTO chunks (upload_id, offset, length, sha256, received_at)"
            " VALUES (?, ?, ?, ?, ?)", (upload_id, offset, n, actual, now))
        conn.execute(
            "UPDATE uploads SET received_bytes = ?, chunks_received = chunks_received + 1,"
            " last_activity_at = ?, state = ?, detail = NULL WHERE id = ?",
            (offset + n, now, UPLOADING, upload_id))
        if row["state"] == STALLED:
            db.add_event(conn, upload_id, now, "RESUMED", f"offset={offset}")
        return to_public(_row(conn, upload_id)), False


def finalize(upload_id):
    """Verify the full-file hash. Only a match makes the upload COMPLETE."""
    with _lock(upload_id), db.connect() as conn:
        now = time.time()
        row = _refresh_state(conn, _row(conn, upload_id), now)
        if row["state"] == COMPLETE:
            return to_public(row)  # finalize is idempotent
        if row["state"] in TERMINAL:
            raise UploadError(409, "terminal_state", f"Upload is {row['state']}", state=row["state"])
        if row["received_bytes"] != row["size"]:
            raise UploadError(409, "incomplete", "Not all bytes received",
                              received_bytes=row["received_bytes"], size=row["size"])

        server_hash = sha256_file(part_path(upload_id))
        if server_hash == row["sha256"]:
            os.replace(part_path(upload_id), final_path(upload_id))
            conn.execute(
                "UPDATE uploads SET state = ?, server_sha256 = ?, completed_at = ?,"
                " last_activity_at = ?, detail = ? WHERE id = ?",
                (COMPLETE, server_hash, now, now, "full-file SHA-256 verified", upload_id))
            db.add_event(conn, upload_id, now, COMPLETE, f"sha256={server_hash}")
        else:
            # Every chunk matched its own hash, yet the whole file does not match the
            # declared hash: the source changed during upload or the declaration is wrong.
            detail = f"full-file SHA-256 mismatch: declared {row['sha256']}, got {server_hash}"
            conn.execute(
                "UPDATE uploads SET state = ?, server_sha256 = ?, last_activity_at = ?, detail = ?"
                " WHERE id = ?", (REJECTED, server_hash, now, detail, upload_id))
            db.add_event(conn, upload_id, now, REJECTED, detail)
        return to_public(_row(conn, upload_id))


def verified_file(upload_id):
    """The only way analysis code may obtain a file: it must be COMPLETE (hash-verified)."""
    info = get(upload_id)
    if info["state"] != COMPLETE:
        raise UploadError(409, "not_verified", f"Upload is {info['state']}, not COMPLETE")
    path = final_path(upload_id)
    if sha256_file(path) != info["server_sha256"]:
        raise UploadError(500, "file_changed", "Stored file no longer matches its verified hash")
    return path


# ---------- capture log (M5): per-frame timing written by the browser while recording ----------

MAX_CAPTURE_LOG_BYTES = 5 * 1024 * 1024


def capture_log_path(upload_id):
    return config.DATA_DIR / "capture_logs" / f"{upload_id}.json"


def put_capture_log(upload_id, data, content_sha256):
    """Store the capture log of an upload. It must arrive before finalize, so the analysis that
    finalize starts always sees it, and it must name the video it describes (video_sha256)."""
    with _lock(upload_id), db.connect() as conn:
        now = time.time()
        row = _refresh_state(conn, _row(conn, upload_id), now)
        path = capture_log_path(upload_id)
        if len(data) > MAX_CAPTURE_LOG_BYTES:
            raise UploadError(413, "log_too_large", f"Max capture log is {MAX_CAPTURE_LOG_BYTES} bytes")
        if hashlib.sha256(data).hexdigest() != content_sha256.lower():
            raise UploadError(422, "log_hash_mismatch", "Capture log SHA-256 does not match its bytes")
        if path.exists():
            if path.read_bytes() == data:
                return {"stored": True, "duplicate": True, "sha256": content_sha256.lower()}  # idempotent
            raise UploadError(409, "log_conflict", "A different capture log is already stored")
        if row["state"] in TERMINAL:
            raise UploadError(409, "terminal_state",
                              f"Upload is {row['state']}; the capture log must be sent before finalize",
                              state=row["state"])
        try:
            log = json.loads(data)
        except ValueError:
            raise UploadError(400, "bad_log", "Capture log is not valid JSON")
        if not isinstance(log, dict) or not isinstance(log.get("frames"), list):
            raise UploadError(400, "bad_log", "Capture log must be an object with a 'frames' list")
        if log.get("video_sha256") != row["sha256"]:
            raise UploadError(409, "log_video_mismatch",
                              "Capture log describes a different video (video_sha256 differs)")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        db.add_event(conn, upload_id, now, "CAPTURE_LOG",
                     f"{len(log['frames'])} frame records, sha256={content_sha256.lower()}")
        return {"stored": True, "duplicate": False, "sha256": content_sha256.lower()}


def capture_log(upload_id):
    """The stored capture log (dict) with its SHA-256, or None."""
    path = capture_log_path(upload_id)
    if not path.exists():
        return None
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "log": json.loads(data)}
