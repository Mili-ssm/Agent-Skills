"""A store that is a git repository: `mem` commits every change it makes (plan 2026-11-17-memory-store-git).

A git failure never fails a command: `commit_if_changed` reports one line and returns None.
"""
from __future__ import annotations

import fcntl
import fnmatch
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

# Same values as mem.py (_LOCAL_DIRS, MAX_FILE_BYTES); mem.py cannot be imported from here (it runs as __main__)
# and a test keeps both copies equal.
LOCAL_DIRS = frozenset({"__pycache__", ".venv", "target", "node_modules", ".pytest_cache", ".sources",
                        ".playwright-mcp"})
MAX_FILE_BYTES = 5 * 1024 * 1024
IGNORED_FILES = ("research/*/data/", ".*.tmp", ".curation-log")  # logs: git holds every earlier state already

TIMEOUT = 10
LOCK_WAIT = 10
STALE_LOCK_SECONDS = 60
LOCK_NAME = "mem-commit.lock"
_GIT_FLAGS = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath="]  # a user's signing or hooks cannot hang a commit


class GitError(Exception):
    pass


def _git(store: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(store), *_GIT_FLAGS, *args], capture_output=True, text=True,
                              check=False, timeout=TIMEOUT, env=os.environ.copy())
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git {args[0]}: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise GitError(f"git {args[0]} failed" + (f": {detail[-1]}" if detail else ""))
    return done.stdout


def is_repo(store: Path) -> bool:
    return (Path(store) / ".git").exists()


def _oversized(store: Path) -> list[str]:
    """Files over MAX_FILE_BYTES outside the ignored folders; they are never staged."""
    found = []
    for dirpath, dirnames, filenames in os.walk(store):
        in_research = Path(dirpath).parent == store / "research"
        dirnames[:] = [d for d in dirnames if d != ".git" and d not in LOCAL_DIRS and not (in_research and d == "data")]
        for name in filenames:
            if name == ".curation-log" or fnmatch.fnmatch(name, ".*.tmp"):
                continue  # ignored already; git add fails when an exclude pathspec names an ignored file
            path = Path(dirpath) / name
            try:
                if path.lstat().st_size > MAX_FILE_BYTES:
                    found.append(path.relative_to(store).as_posix())
            except OSError:
                continue
    return found


def _lock(store: Path):
    fd = os.open(store / ".git" / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise GitError("the commit lock stayed busy for 10 s")
            time.sleep(0.05)


def _drop_stale_index_lock(store: Path) -> None:
    lock = store / ".git" / "index.lock"
    try:
        if time.time() - lock.stat().st_mtime > STALE_LOCK_SECONDS:
            lock.unlink()
    except OSError:
        pass


def _commit(store: Path, message: str) -> str | None:
    try:
        fd = _lock(store)
    except OSError as exc:
        raise GitError(f"lock: {exc}") from exc
    try:
        _drop_stale_index_lock(store)
        _git(store, "add", "-A", "--", ".", *(f":(exclude,literal){rel}" for rel in _oversized(store)))
        staged = subprocess.run(["git", "-C", str(store), *_GIT_FLAGS, "diff", "--cached", "--quiet"],
                                capture_output=True, text=True, check=False, timeout=TIMEOUT)
        if staged.returncode == 0:
            return None
        if staged.returncode != 1:
            raise GitError("git diff failed: " + (staged.stderr.strip() or f"exit {staged.returncode}"))
        _git(store, "commit", "-q", "-m", message)
        return _git(store, "rev-parse", "--short", "HEAD").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(str(exc)) from exc
    finally:
        os.close(fd)  # closing releases the flock


def _print_reason(reason: str) -> None:
    print(f"mem: history: {reason}", file=sys.stderr)


def commit_if_changed(store: Path, message: str, *, report: Callable[[str], None] = _print_reason) -> str | None:
    """Stage everything and commit; the short commit id, or None when nothing changed or git failed (reported)."""
    try:
        return _commit(Path(store), message)
    except GitError as exc:
        report(str(exc))
        return None


def init(store: Path) -> None:
    """Make the store a repository: local identity, .gitignore, a first commit of everything present."""
    store = Path(store)
    _git(store, "init", "-q")
    _git(store, "config", "user.name", "mem")
    _git(store, "config", "user.email", "mem@localhost")
    lines = [f"{name}/" for name in sorted(LOCAL_DIRS)] + list(IGNORED_FILES)
    (store / ".gitignore").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _commit(store, "mem history init")
