"""The curation log read as a stack: the one reader of `.curation-log` for what an integration or its undo left."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from memories.journal import CURATION_LOG

if TYPE_CHECKING:
    from pathlib import Path


def _log_objects(store: Path) -> list[tuple[int, dict[str, Any]]]:
    """(line number, entry) of every log line that is a JSON object with a handle; lines are split on a line feed
    only (`splitlines()` also cuts at U+2028 inside a JSON string) and numbered from 0, the way `mem restore`
    numbers them."""
    try:
        lines = (store / CURATION_LOG).read_text(encoding="utf-8").split("\n")
    except OSError:
        return []
    found = []
    for number, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("handle"), str):
            found.append((number, entry))
    return found


def log_entries(store: Path) -> list[tuple[bool, dict[str, Any]]]:
    """Every log entry with a handle, oldest first (`line` added), each with whether a restore marker has cancelled
    it. A marker `{"action": "restore", "handle": H, "undone": N}` cancels the entry on line N; a marker is itself an
    entry, never cancelled."""
    objects = _log_objects(store)
    cancelled = {
        e["undone"]
        for _, e in objects
        if e.get("action") == "restore" and isinstance(e.get("undone"), int)
    }
    return [(n in cancelled, {**e, "line": n}) for n, e in objects]
