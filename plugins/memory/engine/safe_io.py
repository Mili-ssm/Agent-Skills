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
            os.close(fd)
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
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
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
