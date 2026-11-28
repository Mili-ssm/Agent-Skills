"""Recoverable split groups and their private exact-undo receipts."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from core import jobs, safe_io
from core.file_journal import FileJournal

if TYPE_CHECKING:
    from collections.abc import Callable

    from commands.split_plan import SplitPlan


_ID = re.compile(r"[0-9a-f]{32}\Z")


def _receipt(root: Path, group: str) -> Path:
    if not isinstance(group, str) or not _ID.fullmatch(group):
        raise ValueError("invalid split group")
    path = root / ".split-history" / f"{group}.json"
    safe_io.refuse_symlink_chain(root, path)
    return path


def _member(root: Path, name: str) -> Path:
    p = Path(name)
    parts = p.parts
    allowed = (
        len(parts) == 2  # ruff: ignore[magic-value-comparison]
        and parts[0] == "syntheses"
        and p.suffix == ".md"
    ) or (
        len(parts) == 3  # ruff: ignore[magic-value-comparison]
        and parts[0] == "knowledge"
        and p.suffix == ".md"
        and p.name != "README.md"
    )
    if (
        not allowed
        or p.is_absolute()
        or p.as_posix() != name
        or any(x in {".", ".."} or x.startswith(".") for x in parts)
    ):
        raise ValueError("invalid split member path")
    path = root / p
    safe_io.refuse_symlink_chain(root, path)
    return path


def _encode(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode("ascii")


def _decode(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("invalid split contents")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid split contents") from exc
    if _encode(result) != value:
        raise ValueError("invalid split contents")
    return result


def _read_receipt(  # ruff: ignore[complex-structure]
    root: Path, group: str
) -> tuple[dict, dict[Path, tuple[bytes | None, bytes | None]]]:
    data = json.loads(_receipt(root, group).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("invalid split receipt")
    if (
        data.get("version") != 1
        or data.get("group") != group
        or data.get("state") not in {"applied", "undone"}
        or not isinstance(data.get("entries"), list)
        or not data["entries"]
    ):
        raise ValueError("invalid split receipt")
    changes = {}
    for row in data["entries"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "original", "after", "digest"}
            or not isinstance(row["path"], str)
        ):
            raise ValueError("invalid split receipt entry")
        path = _member(root, row["path"])
        if path in changes:
            raise ValueError("duplicate split member")
        original, after = _decode(row["original"]), _decode(row["after"])
        digest = None if after is None else hashlib.sha256(after).hexdigest()
        if row["digest"] != digest:
            raise ValueError("invalid split digest")
        changes[path] = (original, after)
    return data, changes


def _write(journal: FileJournal, changes: dict[Path, tuple[bytes | None, bytes | None]]) -> None:
    journal.publish(changes)
    try:  # ruff: ignore[too-many-statements-in-try-clause]
        for path, (_, after) in changes.items():
            safe_io.refuse_symlink_chain(journal.root, path)
            if after is None:
                path.unlink()
            else:
                private = path.parent == journal.root / ".split-history"
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o777)
                if private:
                    os.chmod(path.parent, 0o700)
                safe_io.replace_file(path, after, mode=0o600 if private else None)
    except Exception:
        try:
            journal.rollback()
            journal.clear()
        except Exception as exc:
            raise OSError("split recovery pending after rollback failure") from exc
        raise
    journal.clear()


def apply_split(root: Path, prepare: Callable[[], SplitPlan]) -> str:
    journal = FileJournal(root, ".split-recovery")
    with journal.locked():
        if journal.pending():
            raise FileExistsError("split recovery is pending")
        plan = prepare()
        if plan.conflicts:
            raise ValueError("split has conflicts")
        entries = []
        for path, (original, after) in plan.changes.items():
            relative = path.relative_to(root).as_posix()
            if _member(root, relative) != path:
                raise ValueError("invalid split member")
            entries.append({
                "path": relative,
                "original": _encode(original),
                "after": _encode(after),
                "digest": None if after is None else hashlib.sha256(after).hexdigest(),
            })
        if not entries:
            raise ValueError("empty split")
        group = uuid.uuid4().hex
        receipt = _receipt(root, group)
        contents = json.dumps({
            "version": 1,
            "group": group,
            "state": "applied",
            "entries": entries,
        }).encode()
        _write(journal, {**plan.changes, receipt: (None, contents)})
        return group


def undo_split(root: Path, group: str) -> None:
    journal = FileJournal(root, ".split-recovery")
    with journal.locked():
        if journal.pending():
            raise FileExistsError("split recovery is pending")
        receipt = _receipt(root, group)
        old = journal.read_original(receipt)
        data, changes = _read_receipt(root, group)
        if data["state"] != "applied":
            raise ValueError("split already undone")
        data["state"] = "undone"
        new = json.dumps(data).encode()
        _write(
            journal,
            {
                **{path: (after, original) for path, (original, after) in changes.items()},
                receipt: (old, new),
            },
        )


def recover_split(root: Path) -> bool:
    journal = FileJournal(root, ".split-recovery")
    with journal.locked():
        if not journal.pending():
            return False
        journal.rollback()
        journal.clear()
        return True


def split_status(root: Path) -> tuple[bool, list[str]]:  # ruff: ignore[complex-structure]
    journal = FileJournal(root, ".split-recovery")
    lock = journal.folder / jobs.LOCK_NAME
    safe_io.refuse_symlink_chain(root, lock)
    try:
        fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False, []
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BlockingIOError("another file operation or recovery is running") from exc
        if journal.pending():
            return True, []
        folder = root / ".split-history"
        safe_io.refuse_symlink_chain(root, folder)
        groups = []
        if folder.exists():
            for path in sorted(folder.glob("*.json")):
                group = path.stem
                data, _ = _read_receipt(root, group)
                if data["state"] == "applied":
                    groups.append(group)
        return False, groups
    finally:
        os.close(fd)
