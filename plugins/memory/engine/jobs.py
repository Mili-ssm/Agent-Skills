"""Generic pieces of the background jobs (`bin/mem-auto`, `bin/mem-settle`, capture, corroborate): the status and lock
file names, the private state folder, the run lock, private JSON files and the failure of the last runs. Standard
library and `safe_io` only (the bin scripts run it without uv)."""

from __future__ import annotations

import fcntl
import json
import os
from typing import TYPE_CHECKING

import safe_io

if TYPE_CHECKING:
    from pathlib import Path

STALE_RUNNING_SECONDS = 3600  # a `running` status older than this is a run that was killed
LOCK_NAME = "run.lock"
STATUS_NAME = "status.json"


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


def lock_held(folder: Path) -> bool:
    """True while a run holds the lock in `folder`. Reads only: no folder is made; any doubt answers False."""
    path = folder / LOCK_NAME
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
    if (
        status.get("state") == "running"
        and isinstance(started, (int, float))
        and now - started > STALE_RUNNING_SECONDS
    ):
        return {"at": started, "reason": "the run did not finish", "log": status.get("log", "")}
    return None
