"""The curation log: each record file's text before an action changes it, and the undo that puts it back."""

from __future__ import annotations

import datetime
import json
from typing import TYPE_CHECKING, Protocol

from core import safe_io

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

CURATION_LOG = ".curation-log"


class Logged(Protocol):
    """What the curation log needs of a record: a file and a handle (a memory or a synthesis)."""

    path: Path
    handle: str


def log_before(memory: Logged, action: str) -> None:
    """Append the file's whole current text to the `.curation-log` beside it, before an action changes the file."""
    entry = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": action,
        "handle": memory.handle,
        "before": memory.path.read_bytes().decode("utf-8"),
    }
    safe_io.append_text(
        memory.path.parent / CURATION_LOG, json.dumps(entry, ensure_ascii=False) + "\n"
    )


def _log_lines(memory: Logged) -> list[str] | None:
    try:
        # split on "\n" only: splitlines() would also cut at U+0085 or U+2028 inside a JSON string
        return (memory.path.parent / CURATION_LOG).read_text(encoding="utf-8").split("\n")
    except OSError:
        return None


def _parsed_log(lines: Sequence[str], handle: str) -> tuple[list[dict | None], int]:
    """The entries of the memory's handle, None for every other line, and the count of unreadable lines."""
    parsed: list[dict | None] = []
    skipped = 0
    for line in lines:
        entry = None
        if line.strip():
            try:
                entry = json.loads(line)
            except ValueError:
                skipped += 1
        parsed.append(entry if isinstance(entry, dict) and entry.get("handle") == handle else None)
    return parsed, skipped


def last_log_entry(memory: Logged) -> dict | None:
    """The newest `.curation-log` entry for the memory's handle that no restore has used yet, or None.

    Undo is a stack over an append-only log: a restore appends a marker naming the entry (by line number) it used.
    The entry returned gains `line` (its number) and `skipped` (the unreadable lines of the log)."""
    lines = _log_lines(memory)
    if lines is None:
        return None
    parsed, skipped = _parsed_log(lines, memory.handle)
    undone = {
        e["undone"]
        for e in parsed
        if e and e.get("action") == "restore" and isinstance(e.get("undone"), int)
    }
    for number in range(len(parsed) - 1, -1, -1):
        entry = parsed[number]
        if entry and isinstance(entry.get("before"), str) and number not in undone:
            return {**entry, "line": number, "skipped": skipped}
    return None


def restore(memory: Logged, entry: dict) -> None:
    """Put back the text a log entry holds, byte for byte, through a temporary file, then log that it was used."""
    safe_io.replace_file(memory.path, entry["before"].encode("utf-8"))
    marker = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": "restore",
        "handle": memory.handle,
        "undone": entry["line"],
    }
    safe_io.append_text(
        memory.path.parent / CURATION_LOG, json.dumps(marker, ensure_ascii=False) + "\n"
    )
