"""Where things live: git roots, the project registry, the memories folders and the project key."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from core import config

from memories.model import GLOBAL_DIR, PROJECT_DIR, PROJECT_KEY_LEN
from memories.terms import store_is_writable

if TYPE_CHECKING:
    import datetime
    from collections.abc import Mapping, Sequence

    from memories.model import Memory


def _git_common_dir(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    line = out.stdout.strip()
    if out.returncode != 0 or not line:
        return None
    return Path(line)


def _main_worktree(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            first = Path(line[len("worktree ") :])
            # A submodule lists its git directory (under .git/modules), not its folder: ask for the folder.
            if (first / ".git").exists():
                return first
            return _toplevel(cwd)
    return None


def _toplevel(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    line = out.stdout.strip()
    return Path(line) if out.returncode == 0 and line else None


def project_root(cwd: Path, env: Mapping[str, str]) -> Path | None:
    override = env.get("MEM_PROJECT")
    if override:
        return Path(override).expanduser().resolve()
    return _main_worktree(cwd)


def project_dir(project: Path) -> Path:
    return project / PROJECT_DIR


REGISTRY_FILE = "projects.json"


def read_registry(data: Path | None) -> dict[str, dict[str, str]]:
    """The registry of projects in the data folder: name -> {path, seen}. Empty when there is no file;
    ValueError when the file cannot be read or is not that shape."""
    if data is None:
        return {}
    try:
        text = (data / REGISTRY_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"the registry of projects cannot be read: {exc}") from exc
    try:
        reg = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the registry of projects is not valid JSON: {exc}") from exc
    if not isinstance(reg, dict) or not all(
        isinstance(v, dict) and isinstance(v.get("path"), str) for v in reg.values()
    ):
        raise ValueError("the registry of projects has an unexpected shape")
    return reg


def _registry_name(
    reg: dict[str, dict[str, str]], project: Path, held: str | None, name: str | None
) -> str:
    """The name `project` takes in the registry: `name` when free or its own, else the one it holds, else its folder's."""
    if name is not None:
        if held != name and name in reg:
            raise ValueError(f"the name {name} is taken by {reg[name]['path']}")
        return name
    if held is not None:
        return held
    base = project.resolve().name or "project"
    name, n = base, 2
    while name in reg:
        name, n = f"{base}-{n}", n + 1
    return name


def _write_registry(data: Path, reg: dict[str, dict[str, str]]) -> None:
    tmp = data / f"{REGISTRY_FILE}.{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, data / REGISTRY_FILE)
    finally:
        tmp.unlink(missing_ok=True)


def register_project(
    data: Path | None, project: Path, today: datetime.date, name: str | None = None
) -> str | None:
    """Register `project` (or refresh its `seen` date) in the data folder; its name, None without a data folder.

    The name is the folder's name, with -2, -3 ... when another path holds it; an explicit `name` held by another
    path is a ValueError. The file is replaced whole, so a failure leaves the old one."""
    if data is None:
        return None
    reg = read_registry(data)
    path = str(project.resolve())
    held = next((n for n, v in reg.items() if v["path"] == path), None)
    name = _registry_name(reg, project, held, name)
    if held is not None and held != name:
        del reg[held]
    reg[name] = {"path": path, "seen": today.isoformat()}
    data.mkdir(parents=True, exist_ok=True)
    _write_registry(data, reg)
    return name


def forget_project(data: Path | None, name: str) -> bool:
    """Remove a project from the registry; False when the name is unknown."""
    reg = read_registry(data)
    if data is None or name not in reg:
        return False
    del reg[name]
    _write_registry(data, reg)
    return True


def _configured_memories(env: Mapping[str, str]) -> str:
    """The first non-blank line of agent-memory/memories under the config folder, else an empty string."""
    lines = config.config_lines(env, "memories")
    return next((ln.strip() for ln in lines if ln.strip()), "")


def memories_root(env: Mapping[str, str], store: Path | None) -> Path | None:
    """Folder of global memories: MEM_MEMORIES, else the first line of agent-memory/memories, else the writable store's."""
    named = env.get("MEM_MEMORIES") or _configured_memories(env)
    if named:
        if named == "~" or named.startswith("~/"):
            named = (
                str(Path(env["HOME"]) / named[2:]) if env.get("HOME") else os.path.expanduser(named)
            )
        return Path(named)
    if store is not None and store_is_writable(store):
        return store / GLOBAL_DIR
    return None


def global_memories_root(env: Mapping[str, str]) -> Path | None:
    """The folder of global memories for a command that takes no store argument (the background commands):
    `memories_root` with the store that MEM_STORE names, else the default store. Without this a background run
    that is given only MEM_STORE, as the hooks give it, finds no global memory."""
    store = config.resolve_store(None, env)
    return memories_root(env, store if store is not None and store.is_dir() else None)


def project_key(project: Path) -> str:
    """The first 12 hex characters of the SHA-1 of the resolved path: counts projects without naming them."""
    return hashlib.sha1(str(project.resolve()).encode("utf-8")).hexdigest()[:PROJECT_KEY_LEN]


def under_temp(path: Path) -> bool:
    """True when `path` is under a temporary folder: a trial copy of a project there is not a second project.
    Always false when MEM_COUNT_TEMP_PROJECTS is "1" (the tests, which run under a temporary folder)."""
    if os.environ.get("MEM_COUNT_TEMP_PROJECTS") == "1":
        return False
    resolved = path.resolve()
    roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/var/tmp").resolve(),
    }
    return any(resolved == r or r in resolved.parents for r in roots)


def tracked_memories(project: Path) -> frozenset[str] | None:
    """Handles of the `.memory/*.md` files git tracks in `project`; None when `.memory` holds its own `.git` or is
    listed as a gitlink (every handle counts as tracked); empty when git is missing, fails or times out."""
    folder = project / PROJECT_DIR
    try:
        if (folder / ".git").exists():
            return None
        run = subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "ls-files",
                "-z",
                "--recurse-submodules",
                "--",
                f"{PROJECT_DIR}/",
            ],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if run.returncode != 0:
        return frozenset()
    names = [Path(n.decode("utf-8", "replace")) for n in run.stdout.split(b"\0") if n]
    if any(n.as_posix() == PROJECT_DIR for n in names):  # a gitlink lists as the folder itself
        return None
    return frozenset(
        n.stem for n in names if n.suffix == ".md" and n.parent.as_posix() == PROJECT_DIR
    )


def mark_repository(memories: Sequence[Memory], tracked: frozenset[str] | None) -> list[Memory]:
    """Copies of the tracked memories with `from_repository` set and the owner confirmation in the file dropped: a
    repository's author is not the reader. Sightings still count. `tracked` None marks them all."""
    return [
        replace(m, from_repository=True, owner_confirmed=None)
        if tracked is None or m.handle in tracked
        else m
        for m in memories
    ]


def ensure_excluded(project: Path) -> bool:
    """Add `.memory/` to the repository's .git/info/exclude; raises OSError when the line should be written and cannot."""
    if (project / PROJECT_DIR).exists():
        return False
    common = _git_common_dir(project)
    if common is None:
        return False
    exclude = common / "info" / "exclude"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = {ln.strip() for ln in existing.splitlines()}
    if lines & {".memory/", ".memory", "/.memory/", "/.memory"}:
        return False
    exclude.parent.mkdir(parents=True, exist_ok=True)
    sep = "" if not existing or existing.endswith("\n") else "\n"
    exclude.write_text(f"{existing}{sep}{PROJECT_DIR}/\n", encoding="utf-8")
    return True


def default_store(env: Mapping[str, str]) -> Path | None:
    """The store used when none is named: the path only, `mem init` creates it (see `config.default_store`)."""
    return config.default_store_path(env)
