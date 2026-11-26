"""The store lines of the session index: notes held back from history commits and notes due for re-reading.

Keeps the day's due count in the data folder. Imports check and store_git, never mem."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import check
import store_git

if TYPE_CHECKING:
    import datetime

logger = logging.getLogger(__name__)

DUE_CACHE_NAME = "due-counts.json"


def _cached(cache: Path, key: str, today: str) -> tuple[int, int] | None:
    try:
        hit = json.loads(cache.read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        return None
    if (
        isinstance(hit, dict)
        and hit.get("date") == today
        and all(type(hit.get(k)) is int for k in ("retests", "rereads"))
    ):
        return hit["retests"], hit["rereads"]
    return None


def _store(cache: Path, key: str, today: str, counts: tuple[int, int]) -> None:
    """Keep only today's entries; a unique temp name in the folder lets two session starts write at once."""
    try:
        known = json.loads(cache.read_text(encoding="utf-8"))
        known = {k: v for k, v in known.items() if isinstance(v, dict) and v.get("date") == today}
    except (OSError, ValueError, AttributeError):
        known = {}
    known[key] = {"date": today, "retests": counts[0], "rereads": counts[1]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=cache.parent,
        prefix=cache.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp = handle.name
    try:
        Path(tmp).write_text(json.dumps(known, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, cache)
    except OSError:
        Path(tmp).unlink(missing_ok=True)  # a failed write leaves no temp file behind
        raise


def cached_due_counts(
    root: Path, today: datetime.date, cache_dir: Path | None = None
) -> tuple[int, int]:
    """`check.due_counts`, kept per store and day in `cache_dir` when given.

    The count refreshes once a day: a note edited or re-read later the same day shows from the next day."""
    if cache_dir is None:
        return check.due_counts(root, today)
    cache = cache_dir / DUE_CACHE_NAME
    key, day = str(root.resolve()), today.isoformat()
    counts = _cached(cache, key, day)
    if counts is None:
        counts = check.due_counts(root, today)
        with contextlib.suppress(OSError):
            _store(cache, key, day, counts)
    return counts


def store_due_lines(store: Path, today: datetime.date, cache_dir: Path | None) -> list[str]:
    """Lines for notes held back from the last history commit and for notes past their review date; none at zero.

    Never raises: a failing count leaves its line out so the session start goes on."""
    lines = []
    # Broad on purpose: one unreadable note or file must cost only its line, never the whole session index.
    try:
        held = len(store_git.held_back(store))
    except Exception:
        logger.debug("held-back count failed", exc_info=True)
        held = 0
    if held:
        lines.append(
            f"History: {held} changed {'note' if held == 1 else 'notes'} held back from the last "
            "commit: run mem check."
        )
    try:
        retests, rereads = cached_due_counts(store, today, cache_dir)
    except Exception:
        logger.debug("due count failed", exc_info=True)
        return lines
    n = retests + rereads
    if n:
        lines.append(
            f"Re-read due: {n} {'note is' if n == 1 else 'notes are'} past "
            f"{'its' if n == 1 else 'their'} review date: mem review."
        )
    return lines
