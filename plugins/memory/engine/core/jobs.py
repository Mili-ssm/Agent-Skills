"""Generic pieces of the background jobs (`bin/mem-auto`, `bin/mem-settle`, capture, corroborate): the status and lock
file names, the private state folder, the run lock, private JSON files and the failure of the last runs. Standard
library and `safe_io` only (the bin scripts run it without uv)."""

from __future__ import annotations

import datetime
import fcntl
import json
import os
import shutil
from pathlib import Path

from core import safe_io

STALE_RUNNING_SECONDS = 3600  # a `running` status older than this is a run that was killed
LOCK_NAME = "run.lock"
STATUS_NAME = "status.json"


def state_dir() -> Path:
    """The data folder: MEM_DATA, else `$XDG_STATE_HOME/agent-memory` (default `~/.local/state`); empty values count as unset."""
    if os.environ.get("MEM_DATA"):
        return Path(os.environ["MEM_DATA"])
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "agent-memory"


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


def append_log(cdir: Path, line: dict) -> None:
    """Append `line` as one JSON line to `cdir/log.jsonl` (private folder, file mode 0600)."""
    private_dir(cdir)
    fd = os.open(cdir / "log.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def prune_runs_older(runs: Path, now: float, keep_seconds: float) -> None:
    """Remove the entries of `runs` last modified more than `keep_seconds` before `now`; no folder is made."""
    if not runs.is_dir():
        return
    for folder in runs.iterdir():
        try:
            if now - folder.stat().st_mtime > keep_seconds:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def failure_line(folder: Path, kind: str, ack: str, now: float) -> str | None:
    """The one line `mem session-index` adds after a failed `kind` run of the job whose status is in `folder`."""
    found = failure(read_json(folder / STATUS_NAME), now)
    if found is None:
        return None
    when = datetime.datetime.fromtimestamp(float(found.get("at") or now)).date().isoformat()
    reason = " ".join(str(found["reason"]).split())[:200]
    return (
        f"Automatic {kind} failed on {when}: {reason}; log: {found.get('log') or '(none)'} "
        f"({ack} ack clears this)."
    )
