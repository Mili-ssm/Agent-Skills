"""The link rules: relative links resolve, and `orphan_notes`. Pure."""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

from notes import note as notes_mod
from notes.fields import Problem
from notes.index import INDEX_FOLDERS
from notes.note import FrontmatterError, discover_notes

if TYPE_CHECKING:
    from collections.abc import Iterator

    from notes.note import Note


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# A code span never crosses a blank line (paragraph boundary).
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.DOTALL)
# Target: <...> (spaces allowed) or bare with one level of balanced parentheses; optional title.
_LINK = re.compile(
    r"\[[^\]]*\]\(\s*(?:<([^<>\n]*)>|((?:[^()\s]|\([^()\s]*\))+))"
    r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)"""
)
# A reference definition, `[label]: target "title"`: a link to its target for `[text][label]` uses.
_REFDEF = re.compile(
    r"""^ {0,3}\[[^\]]+\]:[ \t]*(?:<([^<>\n]*)>|(\S+))(?:[ \t]+(?:"[^"]*"|'[^']*'|\([^)]*\)))?[ \t]*$"""
)
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")


def _target_spans(line: str, refs: bool) -> list[tuple[int, int]]:
    """(start, end) of the target of each inline link in `line`, and of its reference definition when `refs`."""
    found = [m.span(1 if m.group(1) is not None else 2) for m in _LINK.finditer(line)]
    if refs and (m := _REFDEF.match(line)):
        found.append(m.span(1 if m.group(1) is not None else 2))
    return found


def _blank(match: re.Match) -> str:
    return "\n" * match.group(0).count("\n")


def _in_fence(lines: list[str]) -> list[bool]:
    """Per line: True when it is a fence line or inside a fenced code block."""
    flags: list[bool] = []
    fence: str | None = None
    for line in lines:
        m = _FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
            flags.append(fence is not None)
        else:
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)
                and line.strip() == m.group(1)
            ):
                fence = None
            flags.append(True)
    return flags


def _strip_code(text: str) -> str:
    """Blank out fenced blocks and inline code spans, keeping line numbers."""
    lines = text.split("\n")
    kept = ["" if fenced else line for line, fenced in zip(lines, _in_fence(lines), strict=True)]
    return _CODE_SPAN.sub(_blank, "\n".join(kept))


# Path parts of a research/<id> folder (the depth at which its `code/` is skipped).
_RESEARCH_FOLDER_DEPTH = 2
# Path parts of an index README: <folder>/README.md and <literature|knowledge>/<domain>/README.md.
_FOLDER_README_PARTS = 2
_DOMAIN_README_PARTS = 3


def _markdown_files(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).parts
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".")
            and not (len(rel) == _RESEARCH_FOLDER_DEPTH and rel[0] == "research" and d == "code")
            and not (rel == ("tools", "tests") and d == "fixtures")
        )
        found += [
            Path(dirpath) / f
            for f in sorted(filenames)
            if f.endswith(".md") and not f.startswith(".")
        ]
    return found


def _relative_links(text: str, refs: bool = False) -> Iterator[tuple[int, str, str]]:
    """(line, target, decoded file part) of each relative link outside code; anchors and URLs are skipped.

    Reference definitions count as links only with `refs` (`check` keeps its own scan)."""
    for lineno, line in enumerate(_strip_code(text).split("\n"), 1):
        for start, end in _target_spans(line, refs):
            target = line[start:end]
            if target.startswith(("#", "mailto:")) or _SCHEME.match(target):
                continue
            file_part = urllib.parse.unquote(target.split("#", 1)[0])
            if file_part:
                yield lineno, target, file_part


def rule_links(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 6: relative links resolve to existing files."""
    problems = []
    for path in _markdown_files(root):
        try:
            text = notes_mod._read_text(path)
        except FrontmatterError:
            continue
        rel = path.relative_to(root).as_posix()
        for lineno, target, file_part in _relative_links(text):
            try:
                exists = (path.parent / file_part).exists()
            except (OSError, ValueError):
                exists = False
            if not exists:
                problems.append(
                    Problem(rel, lineno, f"broken link {target}: fix the path or remove the link")
                )
    return problems


def _is_index_readme(rel: str) -> bool:
    parts = rel.split("/")
    return parts[-1] == "README.md" and (
        (len(parts) == _FOLDER_README_PARTS and parts[0] in INDEX_FOLDERS)
        or (len(parts) == _DOMAIN_README_PARTS and parts[0] in {"literature", "knowledge"})
    )


def _link_targets(path: Path, text: str) -> Iterator[str]:
    """Normalized files that `path` links to, a folder standing for its README.md; self links are skipped."""
    for _, _, file_part in _relative_links(text):
        target = os.path.normpath(path.parent / file_part)
        if Path(target).is_dir():
            target = os.path.join(target, "README.md")
        if target != os.path.normpath(path):
            yield target


def orphan_notes(root: Path) -> list[str]:
    """Typed notes no other Markdown file links to, not counting the generated index READMEs; sorted."""
    linked: set[str] = set()
    for path in _markdown_files(root):
        if _is_index_readme(path.relative_to(root).as_posix()):
            continue
        try:
            text = notes_mod._read_text(path)
        except FrontmatterError:
            continue
        linked.update(_link_targets(path, text))
    return sorted(
        n.rel for n in discover_notes(root) if os.path.normpath(root / n.rel) not in linked
    )
