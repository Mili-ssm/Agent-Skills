"""`mem install-command` (ADR 0036): put `mem` (and `mem-research`, `mem-synthesize`) on PATH for every tool, and the plugin-root record it follows.

The plugin lives in a versioned cache folder that moves with every update, so the launcher does not embed one path:
it reads `<state dir>/plugin-root`, which each session start refreshes (`record_root`), and falls back to the root
that ran `install-command`."""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core import jobs, safe_io

if TYPE_CHECKING:
    import argparse

MARKER = "# agent-memory launcher (mem install-command)"
RECORD_NAME = "plugin-root"
_EXEC_MODE = 0o755
# Commands the Codex roles and skills call by name; each launcher runs the plugin's `bin/<name>`.
LAUNCHERS = ("mem", "mem-research", "mem-synthesize")

# Bash twin of `jobs.state_dir()`: MEM_DATA, else $XDG_STATE_HOME/agent-memory (default ~/.local/state); empty is unset.
_LAUNCHER = """#!/usr/bin/env bash
{marker}
if [ -n "${{MEM_DATA:-}}" ]; then d="$MEM_DATA"; else d="${{XDG_STATE_HOME:-$HOME/.local/state}}/agent-memory"; fi
rec=""
[ -r "$d/{record}" ] && IFS= read -r rec < "$d/{record}"
rec="${{rec%$'\\r'}}"
emb={embedded}
marker={marker_q}
for cand in "$rec" "$emb"; do
  [ -n "$cand" ] && [ -x "$cand/bin/{name}" ] || continue
  [ "$cand/bin/{name}" -ef "$0" ] && continue
  line=""
  {{ IFS= read -r line; IFS= read -r line; }} < "$cand/bin/{name}" 2>/dev/null
  [ "$line" = "$marker" ] && continue
  exec "$cand/bin/{name}" "$@"
done
printf '{name}: no plugin copy found; start a Claude Code or Codex session once, or reinstall with %s/bin/mem install-command\n' "$emb" >&2
exit 127
"""


def plugin_root() -> Path:
    """The folder that holds `engine/` and `bin/`: this copy of the plugin."""
    return Path(__file__).resolve().parents[2]


def default_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def launcher_missing() -> bool:
    """True when no `mem` resolves on PATH (the rule of hooks/subagent-start.sh: `command -v mem`)."""
    return shutil.which("mem") is None


def _write_record() -> None:
    state = jobs.state_dir()
    target = state / RECORD_NAME
    data = str(plugin_root()).encode()
    safe_io.refuse_symlink_chain(state, target)  # raises UnsafePathError: record_root suppresses it
    with contextlib.suppress(OSError):
        if target.read_bytes() == data:
            return
    jobs.private_dir(target.parent)
    safe_io.replace_file(target, data, 0o600)


def record_root() -> None:
    """Record this copy's root for the launcher; writes only when it differs, never raises or prints."""
    with contextlib.suppress(OSError, RuntimeError):  # a failing hook disturbs every session
        _write_record()


def launcher_text(root: Path, name: str = "mem") -> str:
    return _LAUNCHER.format(
        name=name,
        marker=MARKER,
        marker_q=shlex.quote(MARKER),
        record=RECORD_NAME,
        embedded=shlex.quote(str(root)),
    )


def _is_ours(path: Path) -> bool:
    try:
        if path.is_symlink():
            return False
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    return len(lines) > 1 and lines[1] == MARKER


def _one(bin_dir: Path, name: str, remove: bool) -> int:
    """Install or remove the launcher `name`; a file that is not ours stays untouched (returns 1)."""
    target = bin_dir / name
    exists = target.exists() or target.is_symlink()
    if exists and not _is_ours(target):
        print(
            f"mem: {target} exists and is not an agent-memory launcher; left untouched",
            file=sys.stderr,
        )
        return 1
    if remove:
        if exists:
            target.unlink()
        print(f"removed {target}" if exists else f"nothing to remove at {target}")
        return 0
    bin_dir.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(target, launcher_text(plugin_root(), name).encode(), _EXEC_MODE)
    print(f"installed {target}")
    return 0


def _warn_off_path(bin_dir: Path) -> None:
    on_path = str(bin_dir.resolve()) in {
        str(Path(p).resolve()) for p in os.environ.get("PATH", "").split(os.pathsep) if p
    }
    if not on_path:
        print(f"warning: {bin_dir} is not on PATH; add it so `mem` resolves", file=sys.stderr)


def cmd_install_command(args: argparse.Namespace) -> int:
    bin_dir = Path(args.bin_dir).expanduser() if args.bin_dir else default_bin_dir()
    failed = sum(_one(bin_dir, name, args.remove) for name in LAUNCHERS)
    if not args.remove:
        _warn_off_path(bin_dir)
    return 1 if failed else 0


def add_parser(sub: Any) -> None:
    cmd = sub.add_parser(
        "install-command",
        help="install `mem`, `mem-research` and `mem-synthesize` as commands on PATH (launchers that follow the plugin)",
    )
    cmd.add_argument(
        "--remove", action="store_true", help="delete the launchers this command wrote"
    )
    cmd.add_argument("--bin-dir", metavar="DIR", help="where to put it (default: ~/.local/bin)")
    cmd.set_defaults(func=cmd_install_command)
