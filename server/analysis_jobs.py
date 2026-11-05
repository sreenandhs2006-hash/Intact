"""Run integrity analysis in a background thread after an upload is COMPLETE.

The file is obtained ONLY through uploads.verified_file(), which refuses anything
that is not COMPLETE and re-checks the SHA-256 on disk first.
"""
import threading
import traceback

from analysis.analyze import analyze, write_reports

from . import config, uploads

_running: set[str] = set()
_guard = threading.Lock()


def report_dir():
    return config.DATA_DIR / "reports"


def status(upload_id):
    if (report_dir() / f"{upload_id}.json").exists():
        return "done"
    if upload_id in _running:
        return "running"
    if (report_dir() / f"{upload_id}.error.txt").exists():
        return "failed"
    return "none"


def start(upload_id):
    with _guard:
        if upload_id in _running or status(upload_id) == "done":
            return False
        _running.add(upload_id)
    threading.Thread(target=_run, args=(upload_id,), daemon=True).start()
    return True


def _run(upload_id):
    try:
        path = uploads.verified_file(upload_id)  # the gate: raises unless COMPLETE + hash re-verified
        info = uploads.get(upload_id)
        transfer = {k: info[k] for k in ("state", "verified", "sha256", "server_sha256", "size",
                                         "received_bytes", "chunks_received", "duplicate_chunks",
                                         "rejected_chunks", "completed_at", "detail")}
        transfer["events"] = uploads.events(upload_id)
        report = analyze(path, transfer)
        report["input"]["file"] = info["filename"]
        write_reports(report, report_dir(), upload_id)
    except Exception:
        report_dir().mkdir(parents=True, exist_ok=True)
        (report_dir() / f"{upload_id}.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        with _guard:
            _running.discard(upload_id)
