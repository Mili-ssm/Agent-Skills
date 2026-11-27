"""What `mem-integrate` remembers between and within runs: the done list and the record of each run.

Both live in a state folder: `done.json` (`{note handle: digest}`) and `<run id>/record.json`. A file that is
missing or unreadable reads as empty, so a damaged state costs a repeated check, never a failed run.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from core import safe_io

if TYPE_CHECKING:
    from pathlib import Path

type Done = dict[str, str]

DONE_FILE = "done.json"
RECORD_FILE = "record.json"


@dataclass
class GroupRecord:
    """One group a command wrote: the files it changed (`s:<handle>` for a synthesis, a note handle for a note)."""

    handles: list[str]
    group_id: str
    kind: str  # `integrate` today
    undone: bool = False


@dataclass
class RunRecord:
    run_id: str
    started: str
    groups: list[GroupRecord] = field(default_factory=list)
    cost: float = 0.0
    failures: list[str] = field(default_factory=list)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(path, json.dumps(data, indent=2).encode("utf-8"))


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_done(folder: Path) -> Done:
    data = _read_json(folder / DONE_FILE)
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def write_done(folder: Path, done: Done) -> None:
    _write_json(folder / DONE_FILE, done)


def is_done(done: Done, handle: str, digest: str) -> bool:
    """True when the note was handled at exactly this digest; an edited note is offered again."""
    return done.get(handle) == digest


def mark_done(folder: Path, handle: str, digest: str) -> None:
    done = read_done(folder)
    done[handle] = digest
    write_done(folder, done)


def write_record(folder: Path, record: RunRecord) -> None:
    """Rewrite the run's record; the runner calls it after every applied command."""
    _write_json(folder / record.run_id / RECORD_FILE, asdict(record))


def read_record(folder: Path, run_id: str) -> RunRecord | None:
    data = _read_json(folder / run_id / RECORD_FILE)
    if not isinstance(data, dict):
        return None
    try:
        groups = [GroupRecord(**g) for g in data.pop("groups", [])]
        return RunRecord(**data, groups=groups)
    except (TypeError, AttributeError):
        return None
