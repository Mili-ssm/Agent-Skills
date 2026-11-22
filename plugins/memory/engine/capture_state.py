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
SWEEP_IDLE_SECONDS = 6 * 3600    # a session this recently changed may still be open and live
SWEEP_MAX_AGE_DAYS = 7
SWEEP_MAX_SESSIONS = 2           # runs that start a model session at one start
SWEEP_MAX_EXAMINED = 10          # candidate files one start may examine, newest first
SWEEP_LOCK_WAIT_SECONDS = 30     # a sweep gives up on a held capture lock sooner than a hook does
SWEEP_MAX_PER_DAY = 4            # sessions swept per UTC day for one data folder
SWEEP_DAY_NAME = "sweep-day.json"
OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE"
BUDGET_OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE_BUDGET"


def capture_dir(data: Path) -> Path:
    return Path(data) / "capture"


def session_path(data: Path, session: str) -> Path:
    """The state file of one session; the name is a hash, so no session string becomes a file name."""
    return capture_dir(data) / "sessions" / (hashlib.sha1(session.encode("utf-8", "replace")).hexdigest()[:16] + ".json")


def _count(value) -> int:
    """A stored counter: a non-negative int (a JSON boolean is not one), else 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def read_session(data: Path, session: str) -> dict:
    found = auto_state.read_json(session_path(data, session))
    offset, attempts = found.get("offset"), found.get("attempts")
    return {"offset": _count(offset), "attempts": _count(attempts)}


def swept_size(data: Path, session: str) -> int | None:
    """The file's size at its last sweep, None when it was never swept."""
    found = auto_state.read_json(session_path(data, session)).get("swept_size")
    return _count(found) if found is not None else None


def save_session(data: Path, session: str, offset: int, attempts: int) -> None:
    path = session_path(data, session)
    auto_state.private_dir(path.parent)
    state = {"session": session, "offset": offset, "attempts": attempts, "updated": time.time()}
    swept = swept_size(data, session)
    if swept is not None:
        state["swept_size"] = swept   # a capture keeps what the last sweep saw
    auto_state.write_json(path, state)


def save_swept_size(data: Path, session: str, size: int) -> None:
    """Remember the file's size at its sweep, next to the offset, so an unchanged file is not swept again."""
    path = session_path(data, session)
    auto_state.private_dir(path.parent)
    found = read_session(data, session)
    auto_state.write_json(path, {"session": session, "offset": found["offset"], "attempts": found["attempts"],
                                 "swept_size": size, "updated": time.time()})


def _utc_day(now: float) -> str:
    return datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date().isoformat()


def sweeps_today(data: Path, now: float) -> int:
    found = auto_state.read_json(capture_dir(data) / SWEEP_DAY_NAME)
    return _count(found.get("count")) if found.get("day") == _utc_day(now) else 0


def note_sweep(data: Path, now: float) -> None:
    """Count one swept session against today's cap."""
    auto_state.private_dir(capture_dir(data))
    auto_state.write_json(capture_dir(data) / SWEEP_DAY_NAME, {"day": _utc_day(now), "count": sweeps_today(data, now) + 1})


def failure_line(data: Path | None, now: float) -> str | None:
    """The one line `mem session-index` adds after a failed capture; None when there is nothing to show."""
    if data is None:
        return None
    found = auto_state.failure(auto_state.read_json(capture_dir(data) / auto_state.STATUS_NAME), now)
    if found is None:
        return None
    try:
        when = datetime.datetime.fromtimestamp(float(found.get("at") or now)).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        when = datetime.datetime.fromtimestamp(now).date().isoformat()
    reason = " ".join(str(found["reason"]).split())[:200]
    return (f"Automatic capture failed on {when}: {reason}; log: {found.get('log') or '(none)'} "
            "(mem-capture ack clears this).")


def prune_runs(runs: Path, keep: int, max_age_days: int, now: float) -> None:
    """Delete run folders beyond the newest `keep` and any older than `max_age_days`."""
    try:
        folders = [(p.stat().st_mtime, p) for p in Path(runs).iterdir() if p.is_dir() and not p.is_symlink()]
    except OSError:
        return
    folders.sort(key=lambda item: item[0], reverse=True)
    for index, (mtime, folder) in enumerate(folders):
        if index >= keep or now - mtime > max_age_days * 86400:
            shutil.rmtree(folder, ignore_errors=True)
