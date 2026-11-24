"""Writes into memory folders that never follow a symlink.

A cloned repository can ship a `.memory/` folder with planted symlinks; a write that follows one would
overwrite a file elsewhere. Files are replaced through an unpredictable temporary name (`os.replace` swaps a
symlink at the target itself, never what it points to) and logs are appended with `O_NOFOLLOW`."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


class UnsafePath(OSError):
    """A path that is, or sits under, a symlink where the caller refuses one."""


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def replace_file(path: Path, data: bytes, mode: int | None = None) -> None:
    """Write `data` to a fresh temporary file beside `path`, then move it over `path`.

    The mode is `mode` when given, else the one `path` has when it is a regular file, else `0o666 & ~umask`."""
    if mode is None:
        try:
            st = os.lstat(path)
            mode = stat.S_IMODE(st.st_mode) if stat.S_ISREG(st.st_mode) else 0o666 & ~_umask()
        except FileNotFoundError:
            mode = 0o666 & ~_umask()
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        try:
            f = os.fdopen(fd, "wb")
        except BaseException:
            try:
                os.close(fd)
            except OSError:  # fdopen may already have closed it; keep the original error
                pass
            raise
        with f:
            f.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def append_text(path: Path, text: str) -> None:
    """Append `text` to `path`, creating it; a symlink at `path` raises OSError."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        f = os.fdopen(fd, "w", encoding="utf-8", newline="")
    except BaseException:
        try:
            os.close(fd)
        except OSError:  # fdopen may already have closed it; keep the original error
            pass
        raise
    with f:
        f.write(text)


def refuse_symlink_chain(root: Path, path: Path) -> None:
    """Raise UnsafePath when `root` or any component of `path` below `root` is a symlink."""
    if root.is_symlink():
        raise UnsafePath(f"{root} is a symlink")
    current = root
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise UnsafePath(f"{path} is not under {root}") from None
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise UnsafePath(f"{current} is a symlink")


# Sandbox of the background sessions (`mem-auto`, `mem-synthesize`): their text may come from injected notes, so a
# session started with MEM_SANDBOX=1 reaches no network and reads body files only under MEM_SANDBOX_ROOTS and its
# working folder.
SANDBOX = "MEM_SANDBOX"
SANDBOX_ROOTS = "MEM_SANDBOX_ROOTS"
_SANDBOX_COMMANDS = ("import", "fetch-sources")


def sandbox_active(env: "os._Environ[str] | dict[str, str] | None" = None) -> bool:
    return (os.environ if env is None else env).get(SANDBOX) == "1"


def body_file_allowed(source: str) -> bool:
    """`-` (standard input) and any file under MEM_SANDBOX_ROOTS or the working directory; symlinks resolved."""
    if source == "-":
        return True
    roots = [Path.cwd(), *(Path(r) for r in os.environ.get(SANDBOX_ROOTS, "").split(os.pathsep) if r)]
    target = Path(os.path.realpath(source))
    return any(target.is_relative_to(os.path.realpath(r)) for r in roots)


def sandbox_refusal(command: str, args: dict) -> str | None:
    """Why a `mem` call is refused in a sandboxed session, else None. `args` holds the parsed options."""
    if not sandbox_active():
        return None
    if command in _SANDBOX_COMMANDS:
        return f"{command} is off in this session"
    if command == "new" and args.get("url"):
        return "--url is off in this session"
    for key, value in args.items():
        if key.endswith("body_file") and isinstance(value, str) and not body_file_allowed(value):
            return f"--{key.replace('_', '-')} is outside the folders this session may read: {value}"
    return None
