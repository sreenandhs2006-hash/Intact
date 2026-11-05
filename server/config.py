"""Server settings, read from environment variables so tests and demos can override them."""
import os
from pathlib import Path

# Uploaded data lives outside the repo (and outside OneDrive) by default.
DATA_DIR = Path(os.environ.get("VI_DATA_DIR", Path.home() / ".nihilent-vi" / "data"))

# A session with no new chunk for this long is shown as STALLED (it can still resume).
STALL_SECONDS = float(os.environ.get("VI_STALL_SECONDS", "30"))

# A session with no activity for this long is FAILED (terminal; the client must start over).
FAIL_SECONDS = float(os.environ.get("VI_FAIL_SECONDS", str(24 * 3600)))

# Upper bounds that protect the server from bad or hostile clients.
MAX_FILE_BYTES = int(os.environ.get("VI_MAX_FILE_BYTES", str(2 * 1024**3)))
MAX_CHUNK_BYTES = int(os.environ.get("VI_MAX_CHUNK_BYTES", str(8 * 1024**2)))
