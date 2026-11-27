"""Undoing a `mem-integrate` run: a group is undone only while it is still the newest change of every file it wrote.

`mem restore <handle>` undoes the newest logged change of a file, not a named group, so `undo` first proves from the
curation log that the group is that newest change everywhere (`newest_is_group`) and only then calls it; with a later
change anywhere, nothing is restored. Groups go newest first; the first refusal stops the undo.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from memories.journal import CURATION_LOG

from integrate import state as run_state

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from subprocess import CompletedProcess

    from integrate.state import GroupRecord

type Mem = Callable[..., CompletedProcess[str]]


@dataclass
class UndoResult:
    """What an undo did: groups undone now, groups still to undo, and why it stopped (None when it did not)."""

    undone: int = 0
    remaining: int = 0
    refusal: str | None = None


def _log_entries(store: Path) -> list[dict[str, Any]]:
    try:
        lines = (store / CURATION_LOG).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("handle"), str):
            found.append(entry)
    return found


def newest_is_group(store: Path, group: GroupRecord) -> str | None:
    """None when every file the group wrote (found in the log by its id) has that group's entry as its newest log
    entry and is still the text that entry left; otherwise the refusal, naming the file."""
    entries = _log_entries(store)
    newest = {
        e["handle"]: e for e in entries
    }  # the log is append-only: the last entry of a file wins
    written = [e for e in entries if e.get("group") == group.group_id]
    if not written:
        return f"the curation log has no entry of group {group.group_id}"
    for entry in written:
        handle = entry["handle"]
        if newest[handle].get("group") != group.group_id:
            return f"{handle} has a newer logged change than group {group.group_id}"
        try:
            current = hashlib.sha256((store / handle).read_bytes()).hexdigest()
        except OSError:
            return f"{handle} is missing, so group {group.group_id} cannot be undone"
        if current != entry.get("after"):
            return f"{handle} changed since group {group.group_id}"
    return None


def _restore(group: GroupRecord, mem: Mem) -> str | None:
    """One `mem restore` per handle of the group; the refusal text when one fails."""
    for handle in group.handles:
        done = mem("restore", handle)
        if done.returncode:
            return f"mem restore {handle} failed: {(done.stderr or done.stdout).strip()}"
    return None


def undo(store: Path, folder: Path, run_id: str, mem: Mem) -> UndoResult:
    """Undoes the run's groups newest first, marking each in the record; a second call continues with the rest."""
    record = run_state.read_record(folder, run_id)
    if record is None:
        return UndoResult(refusal=f"no record of run {run_id}")
    todo = [g for g in reversed(record.groups) if not g.undone]
    result = UndoResult(remaining=len(todo))
    for group in todo:
        refusal = newest_is_group(store, group) or _restore(group, mem)
        if refusal:
            result.refusal = refusal
            return result
        group.undone = True
        run_state.write_record(folder, record)
        result.undone += 1
        result.remaining -= 1
    return result
