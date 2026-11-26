"""Where the note store is: one resolution for every entry point.

Precedence, highest first: `--root`/`--store`, `MEM_STORE` (empty counts as unset), the first line of
`agent-memory/store` under the config folder (stripped), then the default store. Owner rulings 2026-11-26:
the config file is honoured by every entry point, and the default store counts only when it holds
`mem-store.yaml`; with neither `HOME` nor `XDG_DATA_HOME` there is no default store.

Pure: every function takes the environment as a mapping and imports no engine module. The one exception is
`~` in a configured path, expanded with `Path.expanduser()` (it reads the process `HOME`) as `mem` always did.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

STORE_MARKER = "mem-store.yaml"
APP_DIR = "agent-memory"

StoreSource = Literal["--root", "MEM_STORE", "config file", "default"]


def config_dir(env: Mapping[str, str]) -> Path | None:
    """`agent-memory` under XDG_CONFIG_HOME, else under ~/.config; None without either variable."""
    if env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"]) / APP_DIR
    if env.get("HOME"):
        return Path(env["HOME"]) / ".config" / APP_DIR
    return None


def config_lines(env: Mapping[str, str], name: str) -> list[str]:
    """The lines of the config file `name`; empty when it is missing or unreadable."""
    base = config_dir(env)
    if base is None:
        return []
    try:
        return (base / name).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def default_store_path(env: Mapping[str, str]) -> Path | None:
    """Where the default store lives (`mem init` creates it there), whether or not it exists."""
    if env.get("XDG_DATA_HOME"):
        return Path(env["XDG_DATA_HOME"]) / APP_DIR / "store"
    if env.get("HOME"):
        return Path(env["HOME"]) / ".local" / "share" / APP_DIR / "store"
    return None


def default_store(env: Mapping[str, str]) -> Path | None:
    """The default store when it holds the marker; a folder without it is not ours to write to."""
    path = default_store_path(env)
    return path if path is not None and (path / STORE_MARKER).is_file() else None


def _config_store(env: Mapping[str, str]) -> str:
    lines = config_lines(env, "store")
    return lines[0].strip() if lines else ""


def store_source(arg: str | None, env: Mapping[str, str]) -> StoreSource | None:
    """Which rung of the precedence names the store; None when none does."""
    if arg:
        return "--root"
    if env.get("MEM_STORE"):
        return "MEM_STORE"
    if _config_store(env):
        return "config file"
    if default_store(env) is not None:
        return "default"
    return None


def resolve_store(arg: str | None, env: Mapping[str, str]) -> Path | None:
    """The store folder by the precedence above; a named folder is not checked for existence."""
    source = store_source(arg, env)
    if source is None:
        return None
    if source == "default":
        return default_store(env)
    raw = {"--root": arg, "MEM_STORE": env.get("MEM_STORE")}.get(source) or _config_store(env)
    return Path(raw).expanduser()
