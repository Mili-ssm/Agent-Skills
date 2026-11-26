"""State of the automatic curation run (`bin/mem-auto`), shared with `mem`: where it lives, the store-wide run lock
and the failure line of the session text. Standard library only (mem-auto runs it without uv).

Layout, per store: `<data folder>/auto/<id>/` (mode 0700) holds `run.lock`, `status.json` and `runs/<stamp>/` (logs and
transcripts, kept 30 days)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import jobs


def auto_dir(data: Path, store: Path) -> Path:
    return Path(data) / "auto" / hashlib.sha1(str(Path(store).resolve()).encode()).hexdigest()[:12]


def run_lock_held(data: Path | None, store: Path) -> bool:
    """True while a run holds the lock. Reads only: no folder is made; any doubt answers False."""
    if data is None:
        return False
    return jobs.lock_held(auto_dir(data, store))


def failure_line(data: Path | None, store: Path | None, now: float) -> str | None:
    """The one line `mem session-index` adds after a failed run; None when there is nothing to show."""
    if data is None or store is None:
        return None
    return jobs.failure_line(auto_dir(data, store), "curation", "mem-auto", now)
