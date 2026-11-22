"""Count of sessions started per project, and how often each reminder was shown.

State lives in `<data>/sessions.json`, outside the store. Writers take an exclusive, non-blocking `flock` on
`<data>/sessions.lock` (retried for at most LOCK_WAIT seconds): a session start never waits longer. Counts hold no
text and no path: projects are named by `records.project_key`.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any, Sequence

COUNT_NAME = "sessions.json"
LOCK_NAME = "sessions.lock"
COUNTED_SOURCES = ("startup", "clear", "compact")
LOCK_WAIT = 0.5
_RETRY = 0.02


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _clean(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    projects = raw.get("projects") if isinstance(raw.get("projects"), dict) else {}
    shown = raw.get("shown") if isinstance(raw.get("shown"), dict) else {}
    kept: dict[str, dict[str, Any]] = {}
    for name, entry in shown.items():
        entry = entry if isinstance(entry, dict) else {}
        last = entry.get("last")
        kept[str(name)] = {"n": _count(entry.get("n")), "last": last if isinstance(last, str) else None}
    return {"total": _count(raw.get("total")), "projects": {str(k): _count(v) for k, v in projects.items()},
            "shown": kept}


def read(data: Path | None) -> dict[str, Any]:
    """The state; zeros and empty maps when the file is missing or unreadable."""
    try:
        raw = json.loads((data / COUNT_NAME).read_text(encoding="utf-8")) if data is not None else None
    except (OSError, ValueError):
        raw = None
    return _clean(raw)


def showings(state: dict[str, Any], name: str, session: str | None = None) -> int:
    """Showings of a reminder, plus one when `session` is given and differs from the last one counted."""
    entry = state.get("shown", {}).get(name) or {}
    n = _count(entry.get("n"))
    return n + 1 if session is not None and session != entry.get("last") else n


def count_for(state: dict[str, Any], key: str | None) -> int:
    """The project's count for a key, the total for None."""
    return _count(state.get("total")) if key is None else _count(state.get("projects", {}).get(key))


def _write(data: Path, state: dict[str, Any]) -> None:
    tmp = data / f"{COUNT_NAME}.{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(tmp, data / COUNT_NAME)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _locked(data: Path | None, change) -> Any:
    """Run `change(state)` on the stored state under the lock and write it; None when nothing was written."""
    if data is None:
        return None
    fd = None
    try:
        data.mkdir(parents=True, exist_ok=True)
        fd = os.open(data / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return None
                time.sleep(_RETRY)
        path = data / COUNT_NAME
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))  # a file that does not parse is left as it is
            if not isinstance(raw, dict):
                return None
            state = _clean(raw)
        else:
            state = _clean(None)
        result = change(state)
        _write(data, state)
        return result
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)  # closing releases the lock
            except OSError:
                pass


def bump(data: Path | None, key: str | None, shown: Sequence[str] = (), session: str | None = None) -> dict[str, Any] | None:
    """Count one session start: the total, the project when `key` is given, each named showing (once per session).
    Returns the new state, or None when nothing was written. Never raises."""
    def change(state: dict[str, Any]) -> dict[str, Any]:
        state["total"] += 1
        if key is not None:
            state["projects"][key] = state["projects"].get(key, 0) + 1
        for name in shown:
            entry = state["shown"].setdefault(name, {"n": 0, "last": None})
            if session is None or session != entry["last"]:
                entry["n"] += 1
            if session is not None:
                entry["last"] = session
        return state
    try:
        return _locked(data, change)
    except Exception:
        return None


def forget_shown(data: Path | None, name: str) -> int | None:
    """Remove a reminder's showings and return how many there were (0 when absent); None when not written."""
    def change(state: dict[str, Any]) -> int:
        return _count((state["shown"].pop(name, None) or {}).get("n"))
    try:
        return _locked(data, change)
    except Exception:
        return None
