"""The `terms`, `projects`, `init` and `history` handlers (A5, ADR 0028): store and project administration."""

from __future__ import annotations

import contextlib
import datetime
import os
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from core import auto_state, safe_io, store_git
from memories import records
from syntheses import document

from commands import common

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Sequence


_INIT_ALLOWED = {
    "mem-store.yaml",
    "topics.yaml",
    "literature",
    "knowledge",
    "research",
    "memories",
    "templates",
    "syntheses",
    ".git",
    ".gitignore",
    "README.md",
}


def cmd_init(args: argparse.Namespace) -> int:
    if args.folder is None:
        default = records.default_store(os.environ)
        if default is None:
            print(
                "mem: no folder given and neither XDG_DATA_HOME nor HOME is set.", file=sys.stderr
            )
            return 2
        args.folder = str(default)
    code = _init_store(Path(args.folder).expanduser())
    if code == 0:
        # the list is made again by the first global write
        with contextlib.suppress(OSError):
            records.ensure_terms_file(os.environ)
    return code


def _history_store(args: argparse.Namespace) -> Path | None:
    root = common.resolve_root(args.root, os.environ)
    if root is None or not root.is_dir():
        print(
            common.no_store_message(os.environ)
            if root is None
            else f"mem: the store folder does not exist: {root}",
            file=sys.stderr,
        )
        return None
    return root


def _history_init_folder(args: argparse.Namespace) -> Path | None:
    """The store folder `mem history init` turns into a repository; None after a message on stderr."""
    folder = (
        Path(args.folder).expanduser()
        if args.folder
        else common.resolve_root(args.root, os.environ)
    )
    if folder is None:
        print(common.no_store_message(os.environ), file=sys.stderr)
        return None
    if not folder.is_dir():
        print(f"mem: the store folder does not exist: {folder}", file=sys.stderr)
        return None
    if not records.store_is_writable(folder):
        print(
            f'mem: {folder} is read-only: it has no mem-store.yaml (create a store with "mem init").',
            file=sys.stderr,
        )
        return None
    if store_git.is_repo(folder):
        print(f"mem: {folder} is a git repository already", file=sys.stderr)
        return None
    return folder


def _history_init(args: argparse.Namespace) -> int:
    folder = _history_init_folder(args)
    if folder is None:
        return 2
    try:
        print(store_git.init(folder) or "nothing to commit")
    except store_git.GitError as exc:
        print(f"mem: history: {exc}", file=sys.stderr)
        return 1
    return 0


def _history_repo(args: argparse.Namespace, hook: bool) -> Path | None:
    """The store when it is a git repository; None otherwise, with a message unless `hook`."""
    store = _history_store(args) if not hook else common.resolve_root(args.root, os.environ)
    if store is None or not store.is_dir():
        return None
    if not store_git.is_repo(store):
        if not hook:
            print(f'mem: {store} is not a git repository (run "mem history init")', file=sys.stderr)
        return None
    return store


def _history_message(args: argparse.Namespace, hook: bool) -> str | Callable[[int], str]:
    """The commit message: `-m`, or a line stamped with the time of the call."""
    if args.message:
        return args.message
    now = datetime.datetime.now()
    label = "session end" if hook else "manual commit"
    return lambda n: f"{label} {now:%Y-%m-%d %H:%M}: {n} files"


def _history_commit(args: argparse.Namespace, store: Path, hook: bool, started: float) -> int:
    detached = hook and args.detached
    if detached:
        common._log_hook({"hook": "session-end", "phase": "started"})
    if hook and auto_state.run_lock_held(common.data_dir(os.environ), store):
        if detached:
            common._log_hook({
                "hook": "session-end",
                "phase": "done",
                "ms": int((time.monotonic() - started) * 1000),
                "committed": False,
                "failed": False,
            })
        return 0  # an automatic run holds the store: it commits its own work
    message = _history_message(args, hook)
    held: list[str] = []
    commit, failed = common._commit_points(
        store, message, quiet=hook, held=held
    )  # the hook is silent; a failure is in the usage log
    if hook:
        common._log_hook({
            "hook": "session-end",
            **({"phase": "done"} if detached else {}),
            "ms": int((time.monotonic() - started) * 1000),
            "committed": commit is not None,
            "failed": failed,
        })
        return 0
    print(commit or "nothing to commit")
    for path in [] if failed else held:
        print(f"held back: {path}", file=sys.stderr)
    return 1 if failed else 0


def _history_log(args: argparse.Namespace, store: Path) -> int:
    try:
        print("\n".join(store_git.log(store, args.n)))
    except store_git.GitError as exc:
        print(f"mem: history: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    started = time.monotonic()
    hook = args.history_command == "commit" and args.hook
    if args.history_command == "init":
        return _history_init(args)
    store = _history_repo(args, hook)
    if store is None:
        return 0 if hook else 2
    if args.history_command == "commit":
        return _history_commit(args, store, hook, started)
    return _history_log(args, store)


def _init_store_check(folder: Path) -> int | None:
    """The exit code when `folder` cannot become a store, or already is one; None when it can be created."""
    if folder.exists() and not folder.is_dir():
        print(f"mem: {folder} is not a folder", file=sys.stderr)
        return 2
    if folder.is_dir() and any(p.name not in _INIT_ALLOWED for p in folder.iterdir()):
        print(f"mem: {folder} is not empty and is not a store", file=sys.stderr)
        return 2
    if (folder / records.STORE_MARKER).is_file():
        print(folder)
        return 0
    if any((folder / n).exists() for n in ("literature", "knowledge", "research", "topics.yaml")):
        print(
            f"mem: {folder} already holds a store without mem-store.yaml; it stays read-only "
            "(add the file by hand only if you own it and mean to write to it).",
            file=sys.stderr,
        )
        return 2
    return None


def _init_store_create(folder: Path) -> None:
    """Make the folders, the templates and the two files of a new store; what exists stays."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in (
        "literature",
        "knowledge",
        "research",
        records.GLOBAL_DIR,
        document.SYNTHESES_DIR,
    ):
        (folder / name).mkdir(exist_ok=True)
    if not (folder / "templates").exists():
        shutil.copytree(common._TEMPLATES, folder / "templates")
    for name, text in (
        (records.STORE_MARKER, "format: 1\n"),
        ("topics.yaml", "notes: {description: General notes}\n"),
    ):
        if not (folder / name).exists():
            safe_io.replace_file(folder / name, text.encode("utf-8"))


def _init_store(folder: Path) -> int:
    code = _init_store_check(folder)
    if code is not None:
        return code
    try:
        _init_store_create(folder)
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(folder)
    return 0


def _term_class(term: records.Term) -> str:
    return "hard" if not term.soft else f"soft[{term.kind}]" if term.kind else "soft"


def _projects_list(_args: argparse.Namespace, data: Path) -> int:
    today = datetime.date.today()
    for name, entry in sorted(records.read_registry(data).items()):
        path = Path(entry["path"])
        if not path.is_dir():
            print(f"{name}\tmissing\t{path}")
            continue
        live = [
            m
            for m in records.load_memories(records.project_dir(path), "project")
            if records.is_live(m, today)
        ]
        print(f"{name}\t{len(live)} memories\t{path}")
    return 0


def _projects_add(args: argparse.Namespace, data: Path) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        print(f"mem: {path} is not a folder.", file=sys.stderr)
        return 2
    name = records.register_project(data, path, datetime.date.today(), args.name)
    print(f"{name}\t{path}")
    return 0


def _projects_remove(args: argparse.Namespace, data: Path) -> int:
    if not records.forget_project(data, args.name):
        print(f"mem: no project named {args.name} (see mem projects list)", file=sys.stderr)
        return 2
    return 0


_PROJECTS_HANDLERS: dict[str, Callable[[argparse.Namespace, Path], int]] = {
    "list": _projects_list,
    "add": _projects_add,
}  # any other subcommand is `remove`


def cmd_projects(args: argparse.Namespace) -> int:
    data = common.data_dir(os.environ)
    if data is None:
        print(
            "mem: no data folder is set (MEM_DATA, XDG_STATE_HOME or HOME), so there is no registry.",
            file=sys.stderr,
        )
        return 2
    try:
        return _PROJECTS_HANDLERS.get(args.projects_command, _projects_remove)(args, data)
    except (ValueError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2


def _terms_list(_args: argparse.Namespace, _path: Path, terms: Sequence[records.Term]) -> int:
    for t in terms:
        print(f"{_term_class(t)}\t{t.text}")
    return 0


def _terms_add(args: argparse.Namespace, path: Path, terms: Sequence[records.Term]) -> int:
    text = " ".join(args.term.split())
    if args.kind and not args.soft:
        raise common.UsageError("--kind needs --soft")
    if (
        not text
        or text.startswith("#")
        or cast("records.Term", records.parse_term(text)).soft  # not blank, not a comment
    ):
        print("mem: a term cannot be empty, start with # or start with soft:", file=sys.stderr)
        return 2
    line = (
        f"soft[{args.kind}]: {text}"
        if args.soft and args.kind
        else f"soft: {text}"
        if args.soft
        else text
    )
    new = cast("records.Term", records.parse_term(line))  # `line` is neither blank nor a comment
    if any((t.text, t.soft, t.kind) == (new.text, new.soft, new.kind) for t in terms):
        print("already listed")
        return 0
    records.ensure_terms_file(os.environ)
    existing = path.read_text(encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(("" if not existing or existing.endswith("\n") else "\n") + line + "\n")
    print(f"{_term_class(new)}\t{text}")
    return 0


def _terms_remove(args: argparse.Namespace, path: Path, _terms: Sequence[records.Term]) -> int:
    text = " ".join(args.term.split())
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    kept = [ln for ln in lines if (t := records.parse_term(ln)) is None or t.text != text]
    if len(kept) == len(lines):
        print(f"mem: no term {text!r} in the list.", file=sys.stderr)
        return 2
    path.write_text("".join(ln + "\n" for ln in kept), encoding="utf-8")
    print(f"removed {len(lines) - len(kept)}")
    return 0


_TERMS_HANDLERS: dict[str, Callable[[argparse.Namespace, Path, Sequence[records.Term]], int]] = {
    "list": _terms_list,
    "add": _terms_add,
}  # any other subcommand is `remove`


def cmd_terms(args: argparse.Namespace) -> int:
    path = records.forbidden_file(os.environ)
    if path is None:
        print(
            "mem: neither XDG_CONFIG_HOME nor HOME is set: the term list has no place.",
            file=sys.stderr,
        )
        return 2
    try:
        terms = records.read_terms(os.environ)
        return _TERMS_HANDLERS.get(args.terms_command, _terms_remove)(args, path, terms)
    except (records.ForbiddenListError, OSError) as exc:
        print(f"mem: the forbidden-terms list cannot be used ({exc}).", file=sys.stderr)
        return 2
