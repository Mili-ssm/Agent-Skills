"""Write-ahead rollback for imports.

Importers must hold locked() while using this module. Other store writers do not take
this lock and concurrent writes by them during an import or rollback are unsupported.
The journal protects against process interruption, not power loss.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from pathlib import Path

from core import jobs, safe_io

DIRECTORY = ".import-recovery"
JOURNAL = "journal.json"


class DivergedError(OSError):
    """A file differs from both its original and imported contents."""


@contextlib.contextmanager
def locked(root: Path) -> Generator[None, None, None]:
    folder = root / DIRECTORY
    safe_io.refuse_symlink_chain(root, folder / JOURNAL)
    safe_io.refuse_symlink_chain(root, folder / jobs.LOCK_NAME)
    fd = jobs.take_run_lock(folder)
    if fd is None:
        raise BlockingIOError("another import or recovery is running")
    try:
        yield
    finally:
        os.close(fd)


def pending(root: Path) -> bool:
    return (root / DIRECTORY / JOURNAL).exists()


def _target(root: Path, path: Path) -> tuple[Path, str]:
    if not path.is_absolute():
        raise ValueError("import path must be absolute")
    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts or relative.parts[0] == DIRECTORY:
        raise ValueError("invalid import path")
    target = root / relative
    safe_io.refuse_symlink_chain(root, target)
    return target, relative.as_posix()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish(root: Path, intended: Mapping[Path, bytes]) -> None:
    journal = root / DIRECTORY / JOURNAL
    if pending(root):
        raise FileExistsError("an import recovery journal already exists")
    entries = []
    for path, after in intended.items():
        target, relative = _target(root, path)
        try:
            original = target.read_bytes()
        except FileNotFoundError:
            original = None
        entries.append({
            "path": relative,
            "original": base64.b64encode(original).decode("ascii")
            if original is not None
            else None,
            "after": _digest(after),
        })
    jobs.write_json(journal, {"version": 1, "entries": entries})


def rollback(root: Path) -> None:  # ruff: ignore[complex-structure]
    journal = root / DIRECTORY / JOURNAL
    data = json.loads(journal.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("entries"), list)
    ):
        raise ValueError("invalid import recovery journal")
    restore = []
    diverged = []
    for row in data["entries"]:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise TypeError("invalid import recovery entry")
        target, relative = _target(root, root / row["path"])
        original = row.get("original")
        if original is not None:
            original = base64.b64decode(original, validate=True)
        after = row.get("after")
        if not isinstance(after, str) or len(after) != hashlib.sha256().digest_size * 2:
            raise ValueError("invalid import recovery digest")
        try:
            current = target.read_bytes()
        except FileNotFoundError:
            current = None
        if current != original and (current is None or _digest(current) != after):
            diverged.append(relative)
        restore.append((target, original, current))
    if diverged:
        raise DivergedError("import recovery refused changed files: " + ", ".join(diverged))
    for target, original, current in restore:
        if current == original:
            continue
        safe_io.refuse_symlink_chain(root, target)
        if original is None:
            target.unlink()
        else:
            safe_io.replace_file(target, original)


def clear(root: Path) -> None:
    (root / DIRECTORY / JOURNAL).unlink()
