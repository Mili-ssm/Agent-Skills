"""State of the background transcript capture (`bin/mem-capture auto`), kept outside the store.

Layout: `<data folder>/capture/` (mode 0700) holds `status.json`, `sessions/<hash>.json` (how far each session was read)
and `runs/<stamp>/` (logs and results). Standard library only, and no import of `records`, `capture` or `yaml`: the
caller loads this module first, so a missing dependency can still be reported through it."""
from __future__ import annotations

import datetime
import hashlib
import shutil
import time
from pathlib import Path

import auto_state

MAX_WINDOWS = 3                  # windows read in one trigger
MAX_NEW_PER_TRIGGER = 5          # new memories one trigger may write
MAX_ATTEMPTS = 2                 # tries of one window before its offset moves on
LOCK_WAIT_SECONDS = 900
PRE_COMPACT_DELAY_SECONDS = 300
KEEP_RUNS = 20
KEEP_RUN_DAYS = 14
OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE"
BUDGET_OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE_BUDGET"


def capture_dir(data: Path) -> Path:
    return Path(data) / "capture"


def session_path(data: Path, session: str) -> Path:
    """The state file of one session; the name is a hash, so no session string becomes a file name."""
    return capture_dir(data) / "sessions" / (hashlib.sha1(session.encode("utf-8", "replace")).hexdigest()[:16] + ".json")


def read_session(data: Path, session: str) -> dict:
    found = auto_state.read_json(session_path(data, session))
    offset, attempts = found.get("offset"), found.get("attempts")
    return {"offset": offset if isinstance(offset, int) and offset >= 0 else 0,
            "attempts": attempts if isinstance(attempts, int) and attempts >= 0 else 0}


def save_session(data: Path, session: str, offset: int, attempts: int) -> None:
    path = session_path(data, session)
    auto_state.private_dir(path.parent)
    auto_state.write_json(path, {"session": session, "offset": offset, "attempts": attempts, "updated": time.time()})


def failure_line(data: Path | None, now: float) -> str | None:
    """The one line `mem session-index` adds after a failed capture; None when there is nothing to show."""
    if data is None:
        return None
    found = auto_state.failure(auto_state.read_json(capture_dir(data) / auto_state.STATUS_NAME), now)
    if found is None:
        return None
    when = datetime.datetime.fromtimestamp(float(found.get("at") or now)).date().isoformat()
    reason = " ".join(str(found["reason"]).split())[:200]
    return (f"Automatic capture failed on {when}: {reason}; log: {found.get('log') or '(none)'} "
            "(mem-capture ack clears this).")


def prune_runs(runs: Path, keep: int, max_age_days: int, now: float) -> None:
    """Delete run folders beyond the newest `keep` and any older than `max_age_days`."""
    try:
        folders = [(p.stat().st_mtime, p) for p in Path(runs).iterdir() if p.is_dir()]
    except OSError:
        return
    folders.sort(key=lambda item: item[0], reverse=True)
    for index, (mtime, folder) in enumerate(folders):
        if index >= keep or now - mtime > max_age_days * 86400:
            shutil.rmtree(folder, ignore_errors=True)
