"""Helpers shared by the `mem` command handlers and the dispatch (A5, ADR 0028): store resolution, the usage and hook logs, note resolution, the secret and term checks, read-only guards, field and file swaps, history commit points and the project-synthesis context."""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from core import config, safe_io, store_git
from memories import records
from notes import check as check_rules
from notes import note as note_files
from syntheses import project as project_syntheses

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence


class UsageError(Exception):
    """The options of a command contradict each other: the dispatch prints the message as the parser's error (exit 2)."""


def _env_value(env: Mapping[str, str], key: str) -> str:
    return env.get(key) or ""


NO_STORE = (
    'mem: no store is set. Run "mem init" to create the default store, or set the plugin\'s "store" option, '
    "or pass --root <folder>, or set MEM_STORE."
)


def no_store_message(env: Mapping[str, str]) -> str:
    """NO_STORE, plus a line when the default folder exists without its marker (it is not used, and why)."""
    folder = config.default_store_path(env)
    if folder is None or not folder.is_dir() or (folder / config.STORE_MARKER).is_file():
        return NO_STORE
    return (
        f"{NO_STORE}\nmem: {folder} has no {config.STORE_MARKER}, so it is not used; "
        "add the file by hand only if you own that folder and mean to write to it."
    )


def resolve_root(cli_root: str | None, env: Mapping[str, str]) -> Path | None:
    """The store folder by precedence --root, MEM_STORE, config file, default store; not checked for existence."""
    return config.resolve_store(cli_root, env)


def data_dir(env: Mapping[str, str]) -> Path | None:
    """Folder for the usage log and other state, outside the store; None when no variable locates it."""
    if _env_value(env, "MEM_DATA"):
        return Path(env["MEM_DATA"])
    state = _env_value(env, "XDG_STATE_HOME")
    if state:
        return Path(state) / "agent-memory"
    home = _env_value(env, "HOME")
    return Path(home) / ".local" / "state" / "agent-memory" if home else None


def resolve_note(root: Path, arg: str, *, prefix: bool = True) -> Path | list[str] | None:
    """The `.md` file `arg` names inside the hub, as a resolved absolute Path.

    `arg` is a path (hub-relative or absolute), else a handle (`_handle`, with or without `.md`), else (when
    `prefix`, and `arg` does not end in `.md`) a unique prefix of a handle or of a hub-relative path; an exact
    handle or path wins over prefixes. Several matches return their hub-relative paths, sorted; no match
    returns None. Handles come from file names alone: no note is parsed."""
    root = root.resolve()
    path = Path(arg)
    path = (path if path.is_absolute() else root / path).resolve()
    if path.suffix == ".md" and path.is_file() and path.is_relative_to(root):
        return path
    name = arg.removesuffix(".md")
    if not name:
        return None
    rels = sorted(p.relative_to(root).as_posix() for _, p in note_files._note_files(root))
    for found in (
        [r for r in rels if note_files._handle(r) == name or r.removesuffix(".md") == name],
        [r for r in rels if note_files._handle(r).startswith(name) or r.startswith(name)]
        if prefix and name == arg
        else [],
    ):
        if found:
            return root / found[0] if len(found) == 1 else found
    return None


def _ambiguous(arg: str, found: list[str]) -> None:
    print(f"ambiguous: {arg} matches {len(found)} notes:", *found[:10], sep="\n", file=sys.stderr)


def _split_frontmatter_block(text: str) -> re.Match | None:
    return re.match(r"---\n(.*?)\n---[ \t]*(?:\n|$)", text, re.DOTALL)


def _set_field(text: str, key: str, value: Any) -> str:
    """`text` with the frontmatter field `key` set (in place when present, else last) or, for None, removed;
    every other byte stays."""
    m = _split_frontmatter_block(text)
    if m is None:
        raise ValueError("the note has no frontmatter")
    lines = m.group(1).split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(key)}:", ln)), None)
    end = start
    if start is not None:
        end = start + 1
        while end < len(lines) and re.match(r"(\s|- )", lines[end]):
            end += 1
    rendered = (
        ""
        if value is None
        else yaml.safe_dump(
            value, allow_unicode=True, default_flow_style=True, width=float("inf")
        ).split("\n")[0]
    )
    new = [] if value is None else [f"{key}: {rendered}"]
    new_lines = lines[:start] + new + lines[end:] if start is not None else lines + new
    return "---\n" + "\n".join(new_lines) + "\n---\n" + text[m.end() :]


def _usage_log(env: Mapping[str, str]) -> Path | None:
    data = data_dir(env)
    return None if data is None else data / "usage" / "log.jsonl"


def _is_outside(root: Path, cwd: Path | None) -> bool:
    try:
        here = (cwd if cwd is not None else Path.cwd()).resolve()
        return not here.is_relative_to(root.resolve())
    except OSError:
        return True


def _append_usage(
    root: Path | None, entry: dict[str, Any], env: Mapping[str, str], cwd: Path | None
) -> None:
    """Write one usage entry as a line of the log file, unless the log would sit inside the store."""
    log_path = _usage_log(env)
    if root is not None:
        entry["outside"] = _is_outside(root, cwd)
        # the store is never written by the log
        if log_path is not None and log_path.resolve().is_relative_to(root.resolve()):
            return
    if log_path is None:
        return
    # ASCII escapes keep one entry on one line and survive argv that is not valid UTF-8
    line = (json.dumps(entry) + "\n").encode("ascii")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)  # one write: parallel processes cannot interleave lines
    finally:
        os.close(fd)


def log_usage(
    root: Path | None,
    entry: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> None:
    """Append one JSON line to the usage log in the data folder; never raises, never changes output."""
    env = os.environ if env is None else env
    if env.get("MEM_USAGE_LOG") == "0":
        return
    entry = {"t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    with contextlib.suppress(OSError, ValueError, TypeError):
        _append_usage(root, entry, env, cwd)


def _project_synthesis_context() -> tuple[Path, Path, Path] | None:
    """(memory folder, working tree, project root) of the project the session is in; None after saying so."""
    root = records.project_root(Path.cwd(), os.environ)
    if root is None:
        print("mem: not inside a project", file=sys.stderr)
        return None
    return records.project_dir(root), project_syntheses.worktree(Path.cwd(), root, os.environ), root


def _split_part_ref(ref: str) -> tuple[str, str | None]:
    name, sep, handle = ref.removeprefix("p:").partition("#")
    if sep and not handle:
        raise project_syntheses.ProjectSynthesisError(f"{ref!r} has an empty part handle after `#`")
    return name, handle or None


def _existing_parts(found: dict[str, list[project_syntheses.Part]]) -> str:
    return "; ".join(f"p:{n}#{p.handle}" for n, parts in found.items() for p in parts) or "none yet"


def _part_line(name: str, part: project_syntheses.Part, tree: Path) -> str:
    return (
        f"p:{name}#{part.handle}\t{project_syntheses.freshness(tree, part.stamp)}\t{part.heading}"
    )


def _load_project_syntheses(
    memory_dir: Path, name: str | None = None
) -> dict[str, list[project_syntheses.Part]]:
    """The files that load; a broken one does not hide the others, but asking for it by name raises its error."""
    found, broken = project_syntheses.load_each(memory_dir)
    for path, error in broken:
        if name is not None and path == f"{project_syntheses.folder(Path()).as_posix()}/{name}.md":
            raise project_syntheses.Unavailable(f"{path} cannot be read: {error}")
    return found


def _optional_store(args: argparse.Namespace) -> Path | None:
    return args.root if isinstance(args.root, Path) and args.root.is_dir() else None


_READ_ONLY_PROJECT = (
    "mem: this project is the store, which is read-only: it has no mem-store.yaml; "
    "a memory cannot be written here."
)


_READ_ONLY_MEMORIES = (
    "mem: the memories folder is inside the store, which is read-only: it has no mem-store.yaml."
)


def _read_only_store(store: Path | None, path: Path) -> bool:
    return (
        store is not None and not records.store_is_writable(store) and records.inside(path, store)
    )


def _append_hook_log(entry: dict[str, Any]) -> None:
    folder = data_dir(os.environ)
    if folder is None:
        return
    log_path = folder / "hooks" / "log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(entry) + "\n").encode("ascii"))
    finally:
        os.close(fd)


def _log_hook(entry: dict[str, Any]) -> None:
    """Append one line to the hook log in the data folder; never raises. Holds no text and no path."""
    entry = {"t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    with contextlib.suppress(OSError, ValueError, TypeError):
        _append_hook_log(entry)


def _check_terms(texts: Sequence[str], kind: str, approved: bool) -> int:
    """0 when a write to the global scope may go on, else its exit code after a message on stderr: 4 for a hard
    term, 5 for a soft one the owner has not approved, 2 when the list cannot be read, created or located (no HOME and
    no XDG_CONFIG_HOME). A missing list is created, so it never blocks."""
    if records.forbidden_file(os.environ) is None:
        print(
            "mem: the forbidden-terms list has no place: neither XDG_CONFIG_HOME nor HOME is set; nothing was written.",
            file=sys.stderr,
        )
        return 2
    try:
        records.ensure_terms_file(os.environ)
        hits = records.term_hits(texts, os.environ, kind)
    except records.ForbiddenListError as exc:
        print(
            f"mem: the forbidden-terms list cannot be read ({exc}); nothing was written.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(
            f"mem: the forbidden-terms list cannot be created ({exc}); nothing was written.",
            file=sys.stderr,
        )
        return 2
    hard = next((t for t in hits if not t.soft), None)
    if hard is not None:
        print(
            f"mem: the text contains a forbidden term (line {hard.line} of the forbidden-terms list); "
            "nothing was written.",
            file=sys.stderr,
        )
        return 4
    soft = next((t for t in hits), None)
    if soft is not None and not approved:
        print(
            f'mem: the text mentions "{soft.text}" (a soft term): ask the owner whether this may be written to the '
            "global scope; if they agree, repeat with --owner-approved.",
            file=sys.stderr,
        )
        return 5
    return 0


def _refuse_secret(texts: Sequence[str]) -> bool:
    """Say so on stderr and return True when a text looks like it holds a secret."""
    name = records.secret_in(texts)
    if name is None:
        return False
    print(
        f"mem: the text looks like it contains a secret ({name}); nothing was written.",
        file=sys.stderr,
    )
    return True


_TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _commit_points(
    store: Path,
    message: str | Callable[[int], str],
    *,
    quiet: bool = False,
    held: list[str] | None = None,
) -> tuple[str | None, bool]:
    """Commit the store; (commit id or None, whether git failed). The failure is reported and logged.

    `held` receives the paths this run held back, so a caller never reads an older run's list."""
    failed: list[str] = []

    def report(reason: str) -> None:
        failed.append(reason)
        if not quiet:
            print(f"mem: history: {reason}", file=sys.stderr)
        log_usage(store, {"cmd": "history", "error": reason})

    def warn(
        reason: str,
    ) -> None:  # not a git failure: it must not make `mem history commit` exit 1
        if not quiet:
            print(f"mem: history: {reason}", file=sys.stderr)
        log_usage(store, {"cmd": "history", "warning": reason})

    commit = store_git.commit_if_changed(
        store,
        message,
        report=report,
        warn=warn,
        validate=check_rules.invalid_changed(store),
        on_held=lambda paths: held.extend(paths) if held is not None else None,
    )
    return commit, bool(failed)


def _swap_file(path: Path, data: bytes) -> None:
    safe_io.replace_file(path, data)
