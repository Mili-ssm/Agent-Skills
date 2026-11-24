"""State of the automatic curation run (`bin/mem-auto`), shared with `mem`: where it lives, the store-wide run lock
and the failure line of the session text. Standard library only (mem-auto runs it without uv).

Layout, per store: `<data folder>/auto/<id>/` (mode 0700) holds `run.lock`, `status.json` and `runs/<stamp>/` (logs and
transcripts, kept 30 days)."""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path

import safe_io

STALE_RUNNING_SECONDS = 3600   # a `running` status older than this is a run that was killed
LOCK_NAME = "run.lock"
STATUS_NAME = "status.json"


def auto_dir(data: Path, store: Path) -> Path:
    return Path(data) / "auto" / hashlib.sha1(str(Path(store).resolve()).encode()).hexdigest()[:12]


def private_dir(path: Path) -> None:
    """Create `path` with every missing parent at mode 0700 (the umask would give 0755)."""
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for folder in reversed(missing):
        try:
            folder.mkdir(mode=0o700)
        except FileExistsError:
            continue
        os.chmod(folder, 0o700)


def take_run_lock(adir: Path) -> int | None:
    """The store-wide run lock as an open descriptor (closing it releases it), or None when a run holds it."""
    private_dir(adir)
    fd = os.open(adir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def run_lock_held(data: Path | None, store: Path) -> bool:
    """True while a run holds the lock. Reads only: no folder is made; any doubt answers False."""
    if data is None:
        return False
    path = auto_dir(data, store) / LOCK_NAME
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(fd)
    return False


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    safe_io.replace_file(path, json.dumps(data).encode("utf-8"), mode=0o600)


def failure(status: dict, now: float) -> dict | None:
    """The unacknowledged failure of the last runs: `{at, reason, log}`, or None."""
    found = status.get("failure")
    if isinstance(found, dict) and found.get("reason"):
        return found
    started = status.get("started")
    if status.get("state") == "running" and isinstance(started, (int, float)) and now - started > STALE_RUNNING_SECONDS:
        return {"at": started, "reason": "the run did not finish", "log": status.get("log", "")}
    return None


def failure_line(data: Path | None, store: Path | None, now: float) -> str | None:
    """The one line `mem session-index` adds after a failed run; None when there is nothing to show."""
    if data is None or store is None:
        return None
    found = failure(read_json(auto_dir(data, store) / STATUS_NAME), now)
    if found is None:
        return None
    when = datetime.datetime.fromtimestamp(float(found.get("at") or now)).date().isoformat()
    reason = " ".join(str(found["reason"]).split())[:200]
    return (f"Automatic curation failed on {when}: {reason}; log: {found.get('log') or '(none)'} "
            "(mem-auto ack clears this).")
