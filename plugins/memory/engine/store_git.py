"""A store that is a git repository: `mem` commits at the end of a curation pass, at session end and by hand
(plan 2026-11-17-memory-store-git); no other command runs git.

A git failure never fails a command: `commit_if_changed` reports one line and returns None.
"""
from __future__ import annotations

import datetime
import fcntl
import fnmatch
import json
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
SETTLE_FILES = (".settle-log", ".settle-state.json", ".settle-lock")
IGNORED_FILES = ("research/*/data/", ".*.tmp", ".curation-log", *SETTLE_FILES)  # logs: git holds every earlier state already; settle state is per machine

TIMEOUT = 10
LOCK_WAIT = 10
STALE_LOCK_SECONDS = 600  # mem's own git calls time out at 10 s: a lock this old is left over
LOCK_NAME = "mem-commit.lock"
_GIT_FLAGS = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath="]  # a user's signing or hooks cannot hang a commit


class GitError(Exception):
    pass


def _env() -> dict[str, str]:
    """The environment without any GIT_* variable that could redirect the repository, index or work tree."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for keep in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):  # the user's config choice, as the plan keeps it
        if keep in os.environ:
            env[keep] = os.environ[keep]
    return env


def _git(store: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(store), *_GIT_FLAGS, *args], capture_output=True, text=True,
                              check=False, timeout=TIMEOUT, env=_env())
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


def _commit(store: Path, message: str | Callable[[int], str]) -> str | None:
    try:
        fd = _lock(store)
    except OSError as exc:
        raise GitError(f"lock: {exc}") from exc
    try:
        _drop_stale_index_lock(store)
        _git(store, "add", "-A", "--", ".", *(f":(exclude,literal){rel}" for rel in _oversized(store)))
        staged = subprocess.run(["git", "-C", str(store), *_GIT_FLAGS, "diff", "--cached", "--quiet"],
                                capture_output=True, text=True, check=False, timeout=TIMEOUT, env=_env())
        if staged.returncode == 0:
            return None
        if staged.returncode != 1:
            raise GitError("git diff failed: " + (staged.stderr.strip() or f"exit {staged.returncode}"))
        if callable(message):
            message = message(len(_git(store, "diff", "--cached", "--name-only").splitlines()))
        _git(store, "commit", "-q", "-m", message)
        return _git(store, "rev-parse", "--short", "HEAD").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(str(exc)) from exc
    finally:
        os.close(fd)  # closing releases the flock


def _print_reason(reason: str) -> None:
    print(f"mem: history: {reason}", file=sys.stderr)


def commit_if_changed(store: Path, message: str | Callable[[int], str], *, report: Callable[[str], None] = _print_reason) -> str | None:
    """Stage everything and commit; the short commit id, or None when nothing changed or git failed (reported).

    `message` may be a function of the number of files the commit holds."""
    try:
        return _commit(Path(store), message)
    except GitError as exc:
        report(str(exc))
        return None


def _ignore_lines(store: Path, lines: list[str]) -> None:
    ignore = store / ".gitignore"
    have = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    missing = [ln for ln in lines if ln not in have]
    if missing or not ignore.exists():
        prefix = "\n" if have and not ignore.read_text(encoding="utf-8").endswith("\n") else ""
        with ignore.open("a", encoding="utf-8") as fh:
            fh.write(prefix + "".join(ln + "\n" for ln in missing))


def ensure_ignored(store: Path) -> None:
    """Add the settle files to the .gitignore of a store that is a repository already (`init` writes them for new ones)."""
    if is_repo(store):
        _ignore_lines(Path(store), list(SETTLE_FILES))


def init(store: Path) -> str | None:
    """Make the store a repository: local identity, .gitignore, a first commit of everything present."""
    store = Path(store)
    _git(store, "init", "-q")
    _git(store, "config", "user.name", "mem")
    _git(store, "config", "user.email", "mem@localhost")
    _ignore_lines(store, [f"{name}/" for name in sorted(LOCAL_DIRS)] + list(IGNORED_FILES))
    return _commit(store, "mem history init")


def log(store: Path, count: int) -> list[str]:
    """The last `count` commits, one line each: `<id> <date> <message>`."""
    out = _git(Path(store), "log", f"-n{max(count, 1)}", "--date=short", "--format=%h %ad %s")
    return out.splitlines()


TRIM_DAYS = 30
_LOG_FOLDERS = ("", "syntheses", "memories")  # the store's own curation logs; a project's .memory/ is never one of them


def trim_logs(store: Path, now: datetime.datetime | None = None) -> int:
    """Blank the `.curation-log` entries older than TRIM_DAYS; the number of entries removed.

    A removed entry becomes an empty line, not a missing one: `mem restore` marks an undone entry by its line number.
    Call it only for a store whose git history is intact."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=TRIM_DAYS)
    removed = 0
    for folder in _LOG_FOLDERS:
        path = Path(store) / folder / ".curation-log"
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        changed = 0
        for number, line in enumerate(lines):
            try:
                entry = json.loads(line) if line.strip() else None
                when = datetime.datetime.strptime(entry["t"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=datetime.timezone.utc)
            except (ValueError, TypeError, KeyError):
                continue  # unreadable or undated lines stay
            if when < cutoff:
                lines[number] = ""
                changed += 1
        if changed:
            tmp = path.with_name(".curation-log.tmp")
            try:
                tmp.write_text("\n".join(lines), encoding="utf-8", newline="")
                os.replace(tmp, path)
            except OSError:
                continue
            removed += changed
    return removed


def trim_logs_locked(store: Path) -> int:
    """`trim_logs` under the commit lock; 0 when the lock stays busy (the next pass trims)."""
    try:
        fd = _lock(Path(store))
    except (OSError, GitError):
        return 0
    try:
        return trim_logs(store)
    finally:
        os.close(fd)
