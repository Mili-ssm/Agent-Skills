"""Project syntheses: long-lived documents in a project's `.memory/syntheses/`, each part stamped with the commit it
was written at, so a reader learns whether the files it covers changed since.

A project synthesis is a file named after one of `NAMES`; a part is a `## ` section whose last line is its stamp:
`Covers: <path>[, <path>...] | updated <YYYY-MM-DD> at <12 hex digits or no-commit>`. The tool writes the stamp.
`load` reads files only and never runs git; `freshness` is the only function that compares a stamp with the files.
Two roots: `.memory/` sits at the project root (the main worktree), git and the path checks use `worktree()`.
"""

from __future__ import annotations

import datetime
import os
import posixpath
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import yaml
from core import safe_io

from store import syntheses
from store.memory_model import PROJECT_DIR
from store.notes import safe_load

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

NAMES: tuple[str, ...] = ("organization", "plans", "pending", "conventions")
FRESH, CHANGED, UNKNOWN = "fresh", "changed", "unknown"
NO_COMMIT = "no-commit"
GIT_TIMEOUT = 2
MIN_STATUS_ENTRY = 3  # `XY ` status prefix plus at least one character of path
_STAMP = re.compile(
    r"Covers: (?P<paths>[^|]+?) \| updated (?P<date>\d{4}-\d{2}-\d{2}) at (?P<commit>[0-9a-f]{12}|no-commit)"
)
_DESCRIPTIONS = {
    FRESH: "fresh: its files are as they were when it was written",
    CHANGED: "possibly stale: its files changed since it was written; check them before relying on it",
    UNKNOWN: "unknown: not a git project or its commit is gone; check the files",
}


class Stamp(NamedTuple):
    paths: tuple[str, ...]
    date: datetime.date
    commit: str | None


class Part(NamedTuple):
    handle: str
    heading: str
    body: str
    stamp: Stamp
    line: int


class NewPart(NamedTuple):
    """What `write_part` writes: the synthesis `name`, the part's heading and text, and the paths it covers."""

    name: str
    heading: str
    body: str
    paths: Sequence[str]


class ProjectSynthesisError(ValueError):
    pass


class UnavailableError(ProjectSynthesisError):
    """A well-formed request for a name or part that does not exist or cannot be read (exit 1, like `show s:`)."""


Unavailable = UnavailableError  # the name mem.py uses


def folder(memory_dir: Path) -> Path:
    return memory_dir / syntheses.SYNTHESES_DIR


def _render_stamp(paths: Sequence[str], date: datetime.date, commit: str | None) -> str:
    return f"Covers: {', '.join(paths)} | updated {date.isoformat()} at {commit or NO_COMMIT}"


def _parse_stamp(line: str) -> Stamp | None:
    m = _STAMP.fullmatch(line)
    if not m:
        return None
    try:
        date = datetime.date.fromisoformat(m["date"])
    except ValueError:
        return None
    commit = None if m["commit"] == NO_COMMIT else m["commit"]
    return Stamp(tuple(m["paths"].split(", ")), date, commit)


def _check_frontmatter(path: Path) -> None:
    def fail(why: str) -> ProjectSynthesisError:
        return ProjectSynthesisError(f"{path.name}: {why}")

    try:
        text = syntheses._read(path)
    except (OSError, UnicodeDecodeError) as e:
        raise fail(f"cannot be read ({type(e).__name__})") from None
    m = syntheses._FRONTMATTER.match(text)
    try:
        meta = safe_load(m.group(1)) if m else None
    except yaml.YAMLError:
        meta = None
    if not isinstance(meta, dict) or not isinstance(meta.get("title"), str):
        raise fail("no valid frontmatter with a title")


def _parse_part(
    name: str, lines: list[str], span: tuple[int, int], heading: str, seen: list[Part]
) -> Part:
    def fail(why: str) -> ProjectSynthesisError:
        return ProjectSynthesisError(f"{name}: {why}")

    i, end = span
    content = [ln.rstrip("\r") for ln in lines[i + 1 : end]]
    while content and not content[-1].strip():
        content.pop()
    stamp = _parse_stamp(content[-1]) if content else None
    if stamp is None:
        raise fail(f"the part `{heading}` (line {i + 1}) does not end with a stamp")
    handle = syntheses.section_handle(heading)
    if not handle or any(p.handle == handle for p in seen):
        raise fail(f"the heading `{heading}` (line {i + 1}) has an empty or repeated handle")
    return Part(handle, heading, "\n".join(content[:-1]).strip("\n"), stamp, i + 1)


def _parse(path: Path) -> list[Part]:
    _check_frontmatter(path)
    lines, heads = syntheses._scan(syntheses._read(path))
    parts: list[Part] = []
    for n, (i, heading) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        parts.append(_parse_part(path.name, lines, (i, end), heading, parts))
    return parts


def load(memory_dir: Path) -> dict[str, list[Part]]:
    """Name -> parts of every project synthesis that exists; the first broken file raises ProjectSynthesisError."""
    found, broken = load_each(memory_dir)
    if broken:
        raise ProjectSynthesisError(broken[0][1])
    return found


def load_each(memory_dir: Path) -> tuple[dict[str, list[Part]], list[tuple[str, str]]]:
    """Name -> parts, but a broken file does not stop the rest: (name -> parts of the files that load,
    [(path under memory_dir, error message)] of the ones that do not). No git."""
    found: dict[str, list[Part]] = {}
    broken: list[tuple[str, str]] = []
    if folder(memory_dir).is_symlink():
        return found, broken
    for name in NAMES:
        path = folder(memory_dir) / f"{name}.md"
        if path.is_file() and not path.is_symlink():
            try:
                found[name] = _parse(path)
            except ProjectSynthesisError as exc:
                broken.append((path.relative_to(memory_dir).as_posix(), str(exc)))
    return found, broken


def worktree(cwd: Path, project_root: Path, env: Mapping[str, str]) -> Path:
    """The working tree the session is in: the project root when MEM_PROJECT names the project, else the
    repository's top level at `cwd` (a linked worktree is its own), else the project root."""
    if env.get("MEM_PROJECT"):
        return project_root
    out = _git(cwd, "rev-parse", "--show-toplevel")
    top = out.stdout.strip() if out else ""
    return Path(top) if top else project_root


def _git(tree: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=tree,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT,
            env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"},
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return out if out.returncode == 0 else None


def head_commit(tree: Path) -> str | None:
    out = _git(tree, "rev-parse", "HEAD")
    sha = out.stdout.strip()[:12] if out else ""
    return sha if re.fullmatch(r"[0-9a-f]{12}", sha) else None


def _bad_path(p: str) -> bool:
    if not p or p != p.strip() or p.startswith("/") or "//" in p or ".." in p.split("/"):
        return True
    if any(c in p for c in (",", "|", "\\", "\n")):
        return True
    norm = posixpath.normpath(p)
    return norm in {"..", PROJECT_DIR} or norm.startswith((
        "../",
        PROJECT_DIR + "/",
    ))


def _check_paths(tree: Path, paths: Sequence[str]) -> list[str]:
    if not paths:
        raise ProjectSynthesisError("a part must cover at least one path")
    clean = []
    for p in paths:
        if _bad_path(p):
            raise ProjectSynthesisError(
                f"invalid path {p!r}: relative, `/`-separated, no `,` or `|`, not in .memory/"
            )
        if not (tree / p).exists():
            raise ProjectSynthesisError(f"the path {p!r} does not exist in {tree.name}")
        clean.append(p)
    return list(dict.fromkeys(clean))


def _frontmatter(name: str, today: datetime.date) -> str:
    meta = {"title": name.capitalize(), "created": today.isoformat(), "updated": today.isoformat()}
    return (
        "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=10**6) + "---\n"
    )


def _file(memory_dir: Path, name: str) -> Path:
    if name not in NAMES:
        raise ProjectSynthesisError(
            f"unknown project synthesis {name!r}; use one of: {', '.join(NAMES)}"
        )
    return folder(memory_dir) / f"{name}.md"


def _clean_part(heading: str, body: str) -> tuple[str, str, str]:
    """(heading, handle, body) of a part to write, or ProjectSynthesisError."""
    heading = " ".join(heading.split())
    if heading.startswith("#"):
        raise ProjectSynthesisError(
            "the heading must not start with `#`: the tool writes the `## `"
        )
    handle = syntheses.section_handle(heading)
    if not handle:
        raise ProjectSynthesisError("the heading has no letters or digits")
    return heading, handle, _check_body(syntheses._clean(body))


def _check_body(body: str) -> str:
    if not body:
        raise ProjectSynthesisError("the text is empty")
    if syntheses._scan("---\nx: 1\n---\n" + body)[1]:
        raise ProjectSynthesisError(
            "the text contains a `## ` heading: a part is one heading and its text"
        )
    probe = syntheses._scan("---\nx: 1\n---\n" + body + "\n## probe")[1]
    if not probe or probe[-1][1] != "probe":
        raise ProjectSynthesisError("the text leaves a code fence open: close it")
    if any(_parse_stamp(ln.rstrip()) for ln in body.split("\n")):
        raise ProjectSynthesisError("the text contains a stamp line: the tool writes the stamp")
    return body


def _merged(path: Path, handle: str, block: list[str], today: datetime.date) -> str:
    """The file's text with `block` replacing the part of `handle`, or appended when there is none."""
    old = _parse(path)
    lines, heads = syntheses._scan(syntheses._read(path))
    same = next((p for p in old if p.handle == handle), None)
    if same:
        n = next(k for k, (i, _) in enumerate(heads) if i + 1 == same.line)
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        lines[heads[n][0] : end] = [*block, ""]
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", *block, ""]
    return syntheses._bump("\n".join(lines), today)


def write_part(memory_dir: Path, worktree: Path, part: NewPart, today: datetime.date) -> str:
    """Create the file or add a part to it; a heading whose handle exists replaces that part in place."""
    path = _file(memory_dir, part.name)
    safe_io.refuse_symlink_chain(memory_dir, path)
    heading, handle, body = _clean_part(part.heading, part.body)
    covered = _check_paths(worktree, part.paths)
    block = [
        f"## {heading}",
        "",
        *body.split("\n"),
        "",
        _render_stamp(covered, today, head_commit(worktree)),
    ]
    if path.is_file():
        new = _merged(path, handle, block, today)
    else:
        folder(memory_dir).mkdir(parents=True, exist_ok=True)
        new = _frontmatter(part.name, today) + "\n" + "\n".join(block) + "\n"
    syntheses._write(path, new)
    return handle


def confirm_part(
    memory_dir: Path, worktree: Path, name: str, handle: str, today: datetime.date
) -> None:
    """Give a part a new stamp (today, the current commit) and leave its text as it was."""
    path = _file(memory_dir, name)
    safe_io.refuse_symlink_chain(memory_dir, path)
    if not path.is_file():
        raise ProjectSynthesisError(f"there is no project synthesis {name!r}")
    part = next((p for p in _parse(path) if p.handle == handle), None)
    if part is None:
        raise ProjectSynthesisError(f"no part {handle!r} in {name}")
    try:
        _check_paths(worktree, part.stamp.paths)
    except ProjectSynthesisError as e:
        raise ProjectSynthesisError(
            f"{e}; confirming would stamp a false fresh: write the part again with new paths"
        ) from None
    lines, heads = syntheses._scan(syntheses._read(path))
    n = next(k for k, (i, _) in enumerate(heads) if i + 1 == part.line)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    last = max(k for k in range(heads[n][0] + 1, end) if lines[k].strip())
    lines[last] = _render_stamp(part.stamp.paths, today, head_commit(worktree))
    syntheses._write(path, syntheses._bump("\n".join(lines), today))


def _names(out: subprocess.CompletedProcess, status: bool) -> list[str]:
    entries = out.stdout.split("\0")
    if not status:
        return [e for e in entries if e]
    names, skip = [], False
    for e in entries:
        if skip:
            skip = False
        elif len(e) > MIN_STATUS_ENTRY:
            names.append(e[3:])
            skip = e[0] in "RC" or e[1] in "RC"
    return names


def freshness(worktree: Path, stamp: Stamp) -> str:
    if (
        stamp.commit is None
        or _git(worktree, "cat-file", "-e", f"{stamp.commit}^{{commit}}") is None
    ):
        return UNKNOWN
    # --no-relative: names relative to the toplevel, like status, even when the user sets diff.relative
    diff = _git(
        worktree, "diff", "--no-relative", "--name-only", "-z", stamp.commit, "--", *stamp.paths
    )
    status = _git(
        worktree, "status", "--porcelain", "-z", "--untracked-files=all", "--", *stamp.paths
    )
    if diff is None or status is None:
        return UNKNOWN
    prefix = _git(worktree, "rev-parse", "--show-prefix")
    if prefix is None:
        return UNKNOWN
    own = prefix.stdout.strip() + PROJECT_DIR + "/"
    touched = [n for n in _names(diff, False) + _names(status, True) if not n.startswith(own)]
    if touched or any(not (worktree / p).exists() for p in stamp.paths):
        return CHANGED
    return FRESH


def covers_uncommitted(worktree: Path, paths: Sequence[str]) -> bool:
    """True when a covered path differs from HEAD in the working tree; False when git is unavailable."""
    head = head_commit(worktree)
    return (
        head is not None
        and freshness(worktree, Stamp(tuple(paths), datetime.date.today(), head)) == CHANGED
    )


def describe(state: str) -> str:
    return _DESCRIPTIONS[state]
