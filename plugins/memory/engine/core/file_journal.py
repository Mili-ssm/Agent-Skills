"""Private write-ahead rollback journals for interrupted file operations.

Callers hold locked() for the whole operation. Concurrent writers that do not
use the lock and power loss are outside the journal's guarantees.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from core import jobs, safe_io

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping


SPLIT_VERSION = 2


class DivergedError(OSError):
    """A file differs from both its original and replacement contents."""


class FileJournal:
    def __init__(self, root: Path, directory: str, version: int = 2):
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("journal root must be absolute and contained")
        if not directory or directory in {".", ".."} or Path(directory).name != directory:
            raise ValueError("invalid journal directory")
        if version not in {1, 2}:
            raise ValueError("invalid journal version")
        self.root = root
        self.directory = directory
        self.version = version
        self.label = "import recovery" if version == 1 else "file recovery"
        self.folder = root / directory
        self.journal = self.folder / "journal.json"

    def _check_journal(self) -> None:
        safe_io.refuse_symlink_chain(self.root, self.journal)
        safe_io.refuse_symlink_chain(self.root, self.folder / jobs.LOCK_NAME)

    @contextlib.contextmanager
    def locked(self) -> Generator[None, None, None]:
        self._check_journal()
        fd = jobs.take_run_lock(self.folder)
        if fd is None:
            message = (
                "another import or recovery is running"
                if self.version == 1
                else "another file operation or recovery is running"
            )
            raise BlockingIOError(message)
        try:
            yield
        finally:
            os.close(fd)

    def pending(self) -> bool:
        self._check_journal()
        return self.journal.exists()

    def _target(self, path: Path) -> tuple[Path, str]:
        if not path.is_absolute():
            raise ValueError(
                "import path must be absolute"
                if self.version == 1
                else "file path must be absolute"
            )
        relative = path.relative_to(self.root)
        if not relative.parts or ".." in relative.parts or relative.parts[0] == self.directory:
            raise ValueError("invalid import path" if self.version == 1 else "invalid file path")
        target = self.root / relative
        safe_io.refuse_symlink_chain(self.root, target)
        return target, relative.as_posix()

    def read_original(self, path: Path) -> bytes | None:
        target, _ = self._target(path)
        try:
            return target.read_bytes()
        except FileNotFoundError:
            return None

    def publish(self, changes: Mapping[Path, tuple[bytes | None, bytes | None]]) -> None:  # ruff: ignore[complex-structure]
        if self.pending():
            raise FileExistsError(f"an {self.label} journal already exists")
        entries = []
        for path, (original, after) in changes.items():
            target, relative = self._target(path)
            if original is not None and not isinstance(original, bytes):
                raise TypeError("invalid original contents")
            if after is not None and not isinstance(after, bytes):
                raise TypeError("invalid replacement contents")
            if self.version == 1 and after is None:
                raise ValueError("invalid import recovery digest")
            if self.read_original(target) != original:
                raise ValueError(f"file changed before journal publication: {relative}")
            entries.append({
                "path": relative,
                "original": base64.b64encode(original).decode("ascii")
                if original is not None
                else None,
                "after": hashlib.sha256(after).hexdigest() if after is not None else None,
            })
        self._check_journal()
        jobs.write_json(self.journal, {"version": self.version, "entries": entries})

    def rollback(self) -> None:  # ruff: ignore[complex-structure]
        self._check_journal()
        data = json.loads(self.journal.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("version") != self.version
            or not isinstance(data.get("entries"), list)
        ):
            raise ValueError(f"invalid {self.label} journal")
        restore = []
        diverged = []
        seen = set()
        for row in data["entries"]:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise TypeError(f"invalid {self.label} entry")
            target, relative = self._target(self.root / row["path"])
            if self.version == SPLIT_VERSION and ("original" not in row or relative in seen):
                raise ValueError(f"invalid {self.label} entry")
            seen.add(relative)
            original = row.get("original")
            if original is not None:
                original = base64.b64decode(original, validate=True)
            after = row.get("after")
            if not (self.version == SPLIT_VERSION and "after" in row and after is None) and (
                not isinstance(after, str) or len(after) != hashlib.sha256().digest_size * 2
            ):
                raise ValueError(f"invalid {self.label} digest")
            current = self.read_original(target)
            replacement_matches = (
                current is None
                if after is None
                else current is not None and hashlib.sha256(current).hexdigest() == after
            )
            if current != original and not replacement_matches:
                diverged.append(relative)
            restore.append((target, original, current))
        if diverged:
            raise DivergedError(f"{self.label} refused changed files: " + ", ".join(diverged))
        for target, original, current in restore:
            if current == original:
                continue
            safe_io.refuse_symlink_chain(self.root, target)
            if original is None:
                target.unlink()
            else:
                safe_io.replace_file(target, original)

    def clear(self) -> None:
        self._check_journal()
        self.journal.unlink()
