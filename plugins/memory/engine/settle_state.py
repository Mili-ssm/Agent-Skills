"""Background settling (`bin/mem-settle`): where its state lives, the lines of the session start text, and the trigger
the write path calls. Standard library plus `settle` and `auto_state`; every function that runs in a write or at
session start swallows its errors, because it must never fail what it rides on."""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, SupportsFloat, SupportsIndex

import jobs
import settle

if TYPE_CHECKING:
    import datetime
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

BIN = Path(__file__).resolve().parents[1] / "bin" / "mem-settle"
DEFAULT_MINUTES = 30.0
# Set by the SessionStart hook for the session's shell commands: without them nothing here starts a run (trials, tests).
ENV_FLAG, ENV_MINUTES, ENV_CLAUDE = "MEM_SETTLE_AUTO", "MEM_SETTLE_MINUTES", "MEM_SETTLE_CLAUDE"


def settle_dir(data: Path, store: Path) -> Path:
    """State of one store's settling runs: lock, status.json and runs/<stamp>/ (mode 0700), apart from mem-auto's."""
    return (
        Path(data) / "settle" / hashlib.sha1(str(Path(store).resolve()).encode()).hexdigest()[:12]
    )


def minutes_of(value: object) -> float:
    if not isinstance(value, SupportsFloat | SupportsIndex | str | bytes | bytearray | memoryview):
        return DEFAULT_MINUTES
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MINUTES
    return number if number >= 0 else DEFAULT_MINUTES


def failure_line(data: Path | None, store: Path | None, now: float) -> str | None:
    if data is None or store is None:
        return None
    return jobs.failure_line(settle_dir(data, store), "settling", "mem-settle", now)


_WORDS = {"merge": "merged", "supersede": "superseded", "distinct": "kept distinct", "left": "left"}


def settled_line(folder: Path | None) -> str | None:
    """One line while settlings the owner has not acknowledged (and not undone) exist. Reads only: it never creates
    the state file, so a store that never settled stays untouched."""
    if folder is None or not (folder / settle.LOG_NAME).is_file():
        return None
    acked = jobs.read_json(folder / settle.STATE_NAME).get("acked", 0)
    fresh = [
        s
        for s in settle.settlings(folder)
        if s["seq"] > (acked if isinstance(acked, int) else 0) and not s["undone"]
    ]
    if not fresh:
        return None
    counts: dict[str, int] = {}
    for s in fresh:
        counts[s.get("decision", "")] = counts.get(s.get("decision", ""), 0) + 1
    parts = [f"{counts[d]} {word}" for d, word in _WORDS.items() if counts.get(d)]
    since = min(str(s.get("date", "")) for s in fresh)
    return (
        f"memory: settled since {since}: {', '.join(parts)}; see `mem settle log`, undo with "
        "`mem settle undo <n>`, hide with `mem settle ack`."
    )


def maybe_start(
    folder: Path, store: Path | None, environ: Mapping[str, str], now: float, today: datetime.date
) -> bool:
    """After a write to the global scope: when the hook enabled settling and a run is due, start `mem-settle run`
    detached. Returns whether it started one. Never raises."""
    try:
        return _start(folder, store, environ, now, today)
    except Exception:
        logger.debug("settle: could not start a run", exc_info=True)
        return False


def _start(
    folder: Path, store: Path | None, environ: Mapping[str, str], now: float, today: datetime.date
) -> bool:
    if environ.get(ENV_FLAG) != "1":
        return False
    minutes = minutes_of(environ.get(ENV_MINUTES))
    if settle.due(folder, minutes, now, today) is None:
        return False
    cmd = [sys.executable, str(BIN), "run", "--minutes", str(minutes)]
    if store is not None:
        cmd += ["--store", str(store)]
    if environ.get(ENV_CLAUDE):
        cmd += ["--claude", environ[ENV_CLAUDE]]
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=dict(environ),
    )
    return True
