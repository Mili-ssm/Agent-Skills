"""Write-ahead rollback for imports; callers hold locked() during imports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.file_journal import DivergedError, FileJournal

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["DivergedError"]

DIRECTORY = ".import-recovery"
JOURNAL = "journal.json"


def _journal(root: Path) -> FileJournal:
    return FileJournal(root, DIRECTORY, version=1)


def locked(root: Path):
    return _journal(root).locked()


def pending(root: Path) -> bool:
    return _journal(root).pending()


def publish(root: Path, intended: Mapping[Path, bytes]) -> None:
    journal = _journal(root)
    if journal.pending():
        raise FileExistsError("an import recovery journal already exists")
    journal.publish({
        path: (journal.read_original(path), after) for path, after in intended.items()
    })


def rollback(root: Path) -> None:
    _journal(root).rollback()


def clear(root: Path) -> None:
    _journal(root).clear()
