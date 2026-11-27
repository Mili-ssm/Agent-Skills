"""mem-corroborate: the state folder, the journal and undo, and the commands that need nothing else (stdlib, `jobs`, `safe_io`; no yaml)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

from core import jobs, safe_io

DEFAULT_BUDGET = 0.25  # USD per session


STAMP_RE = re.compile(r"[A-Za-z0-9._-]+")


# `CURATION_LOG`, repeated so this module needs no yaml: `auto` and `undo` must work when the engine cannot load
CURATION_LOG = ".curation-log"


data_dir = jobs.state_dir


def corroborate_dir(data: Path) -> Path:
    return Path(data) / "corroborate"


def budget_of(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_BUDGET
    return number if math.isfinite(number) and number > 0 else DEFAULT_BUDGET


def save_status(cdir: Path, **changes) -> dict:
    jobs.private_dir(cdir)
    data = {**jobs.read_json(cdir / jobs.STATUS_NAME), **changes}
    for key in [k for k, v in data.items() if k == "failure" and v is None]:
        del data[key]
    jobs.write_json(cdir / jobs.STATUS_NAME, data)
    return data


append_log = jobs.append_log


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)


def digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


FILL_NEWS = (
    "written",
    "refused_code",
    "refused_check",
    "to_triage",
    "stopped",
)  # the counts `status` reports


class Journal:
    """The undo record of one run: `commit` after an action compares each watched file with its text before."""

    def __init__(self, run: Path):
        self.run = run
        self.seen: dict[str, bool] = {}  # file -> created by this run

    @staticmethod
    def before_name(path: Path) -> str:
        return hashlib.sha1(str(path).encode()).hexdigest()[:16]

    @staticmethod
    def watch(paths) -> dict[Path, bytes | None]:
        """The files and the curation log beside each (an action may log the text it replaces)."""
        out = {Path(p): read_bytes(Path(p)) for p in paths}
        for p in list(out):
            log = p.parent / CURATION_LOG
            out.setdefault(log, read_bytes(log))
        return out

    def watch_folder(self, folder: Path) -> dict[Path, bytes | None]:
        found = self.watch(sorted(folder.glob("*.md"))) if folder.is_dir() else {}
        log = folder / CURATION_LOG
        found.setdefault(log, read_bytes(log))
        return found

    def commit(
        self, action: str, before: dict[Path, bytes | None], folder: Path | None = None
    ) -> None:
        """Journal every watched file that changed; with `folder`, files that appeared in it count as created."""
        paths = dict(before)
        if folder is not None and folder.is_dir():
            for p in folder.glob("*.md"):
                paths.setdefault(p, None)
        for path, old in paths.items():
            now = read_bytes(path)
            if now != old:
                self._record(action, path, old, now)

    def _record(self, action: str, path: Path, old: bytes | None, now: bytes | None) -> None:
        """Journal one changed file; the first change to it also saves its text before the run."""
        key = str(path)
        if key not in self.seen:
            self.seen[key] = old is None
            if old is not None:
                folder_b = self.run / "before"
                jobs.private_dir(folder_b)
                write_private_bytes(folder_b / self.before_name(path), old)
        row = {"action": action, "file": key, "created": self.seen[key], "hash": digest(now)}
        fd = os.open(self.run / "journal.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_private_bytes(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(data)


class UndoRefusedError(Exception):
    """An undo that must change nothing; the message says why."""


def _journal_rows(run: Path) -> dict[str, dict]:
    """The last journal row of each file the run changed."""
    journal = run / "journal.jsonl"
    if not journal.is_file():
        raise UndoRefusedError("this run has no journal: nothing to undo")
    last: dict[str, dict] = {}
    for text in journal.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(text)
        except ValueError:
            raise UndoRefusedError("the journal cannot be read: nothing was changed") from None
        if isinstance(row, dict) and isinstance(row.get("file"), str):
            last[row["file"]] = row
    return last


def _to_restore(run: Path, file: str, row: dict) -> tuple[Path, bytes | None] | None:
    """What to put back at `file` (None means remove it), or None when it is restored already."""
    path, now = Path(file), read_bytes(Path(file))
    if row.get("created"):
        saved = None
        if now is None:
            return None
    else:
        saved = read_bytes(run / "before" / Journal.before_name(path))
        if saved is None:
            raise UndoRefusedError(f"the saved copy of {file} is missing: nothing was changed")
        if now == saved:
            return None
    if digest(now) != row.get("hash"):
        raise UndoRefusedError(
            f"{file} changed since the run: nothing was changed. Undo the later change first "
            "(mem restore for a memory), or leave the pass applied"
        )
    return path, saved


def _restore(todo: list[tuple[Path, bytes | None]]) -> str | None:
    """Put the files back; the message of the first failure, None when all are restored."""
    for path, saved in todo:
        try:
            if saved is None:
                path.unlink(missing_ok=True)
            else:
                safe_io.replace_file(path, saved, mode=0o600)
        except OSError as exc:
            return f"cannot restore {path}: {exc.strerror or type(exc).__name__}; run undo again to finish"
    return None


def undo_run(run: Path) -> tuple[bool, str]:
    """(done, message). Changes nothing unless every journaled file that is not restored yet still holds what the run
    left in it; a file already equal to its saved copy (or a created one already gone) counts as restored, so an
    interrupted undo can be run again."""
    if (run / "undone").exists():
        return True, f"run {run.name} was already undone"
    try:
        todo = [
            step
            for file, row in _journal_rows(run).items()
            if (step := _to_restore(run, file, row))
        ]
    except UndoRefusedError as exc:
        return False, str(exc)
    failure = _restore(todo)
    if failure:
        return False, failure
    write_private(run / "undone", "")
    return True, f"undone: {len(todo)} files"


def forget_run(cdir: Path, run: Path) -> None:
    """After an undo: the next run does the work again, so drop the saved fingerprint and the marks this run added."""
    seen = jobs.read_json(cdir / "seen.json")
    if not seen:
        return
    added = jobs.read_json(run / "seen-added.json").get("marked")
    marks = seen.get("refused")
    seen.pop("fingerprint", None)
    seen.pop("retry", None)
    if isinstance(marks, dict) and isinstance(added, list):
        seen["refused"] = {k: v for k, v in marks.items() if k not in added}
    jobs.write_json(cdir / "seen.json", seen)


def cmd_undo(args) -> int:
    if not STAMP_RE.fullmatch(args.stamp) or args.stamp in {".", ".."}:
        print("mem-corroborate: not a run stamp", file=sys.stderr)
        return 2
    cdir = corroborate_dir(data_dir())
    run = cdir / "runs" / args.stamp
    if not run.is_dir():
        print(f"mem-corroborate: no run {args.stamp}", file=sys.stderr)
        return 2
    lock = jobs.take_run_lock(cdir)
    if lock is None:
        print("mem-corroborate: a run is going: try again later", file=sys.stderr)
        return 1
    try:
        if (run / "undone").exists():
            done, message = True, f"run {args.stamp} was already undone"
        else:
            done, message = undo_run(run)
            if (
                done and not (run / "fill").exists()
            ):  # a fill run never touched the pass's `seen.json`
                forget_run(cdir, run)
    finally:
        os.close(lock)
    print(f"mem-corroborate: {message}", file=sys.stdout if done else sys.stderr)
    return 0 if done else 1


def cmd_status() -> int:
    data = jobs.read_json(corroborate_dir(data_dir()) / jobs.STATUS_NAME)
    if not data:
        print("no corroboration run yet")
        return 0
    shown = data.get("state", "?")
    started = data.get("started")
    if (
        shown == "running"
        and isinstance(started, (int, float))
        and time.time() - started > jobs.STALE_RUNNING_SECONDS
    ):
        shown = "failed (a run that did not finish)"
    print(f"last run: state {shown}, cost {float(data.get('cost') or 0):.3f} USD")
    failure = jobs.failure(data, time.time())
    if failure:
        print(f"unacknowledged failure: {failure.get('reason')} (mem-corroborate ack clears it)")
    fill = data.get("fill")
    if isinstance(fill, dict) and any(fill.get(k) for k in FILL_NEWS):
        refused = (fill.get("refused_code") or 0) + (fill.get("refused_check") or 0)
        stopped = f", stopped: {fill['stopped']}" if fill.get("stopped") else ""
        print(
            f"last fill: {fill.get('written') or 0} written, {refused} refused, {fill.get('to_triage') or 0} to triage{stopped}"
        )
    print(f"log: {data.get('log') or '(none)'}")
    return 0


def cmd_ack() -> int:
    cdir = corroborate_dir(data_dir())
    current = jobs.read_json(cdir / jobs.STATUS_NAME)
    if current:
        changes: dict = {"failure": None}
        started = current.get("started")
        if (
            current.get("state") == "running"
            and isinstance(started, (int, float))
            and time.time() - started > jobs.STALE_RUNNING_SECONDS
        ):
            changes["state"] = "failed"
        save_status(cdir, **changes)
    print("acknowledged: the failure line is cleared")
    return 0
