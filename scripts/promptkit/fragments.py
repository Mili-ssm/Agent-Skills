"""Render shared text from shared/fragments/<id>.md into marked blocks of Markdown files.

Run from scripts/: python3 -m promptkit.fragments [--check] [--root PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FRAGMENTS_DIR = Path("shared") / "fragments"
VERBATIM = "verbatim-in:"
OPEN = re.compile(r'^ {0,3}<!-- shared:([\w-]+)((?:\s+[\w-]+="[^"]*")*)\s*-->\s*$')
CLOSE = re.compile(r"^ {0,3}<!-- /shared:([\w-]+) -->\s*$")
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
PLACEHOLDER = re.compile(r"\{\{([\w-]+)\}\}")


class FragmentError(ValueError):
    """A marker or fragment is malformed."""


@dataclass
class Block:
    id: str
    attrs: dict[str, str]
    start: int  # line index of the opening marker
    end: int  # line index of the closing marker


def _read_fragment(path: Path) -> tuple[str, str | None]:
    """Fragment text without its trailing newline, and the `verbatim-in:` target if declared."""
    text = path.read_text(encoding="utf-8")
    target = None
    first, _, rest = text.partition("\n")
    if first.startswith(VERBATIM):
        target, text = first[len(VERBATIM):].strip(), rest
    return text.rstrip("\n"), target


def _fragment_files(folder: Path) -> list[Path]:
    """Fragment files of the folder; its README.md documents the folder and is no fragment."""
    if not folder.is_dir():
        return []
    return [p for p in sorted(folder.glob("*.md")) if p.name != "README.md"]


def load_fragments(folder: Path) -> dict[str, str]:
    fragments = {p.stem: _read_fragment(p)[0] for p in _fragment_files(folder)}
    for fid, text in fragments.items():
        if _fence_flags(text.split("\n"))[1] >= 0:  # a rendered block would hide every later marker
            raise FragmentError(f"fragment '{fid}' leaves a code fence open")
    return fragments


def verbatim_targets(folder: Path) -> dict[str, str]:
    """Fragment id -> repo-relative file whose text must contain the fragment verbatim."""
    pairs = {p.stem: _read_fragment(p)[1] for p in _fragment_files(folder)}
    return {k: v for k, v in pairs.items() if v}


def _fence_flags(lines: list[str]) -> tuple[list[bool], int]:
    """Per line: is it a fence line or inside a fence (CommonMark closing rule)? Plus the line index
    where a fence left open at the end of the file started (-1 when none)."""
    flags: list[bool] = []
    fence = ""
    opened_at = -1
    for i, line in enumerate(lines):
        if not fence:
            m = FENCE.match(line)
            fence = m.group(1) if m else ""
            opened_at = i if m else -1
            flags.append(bool(m))
        else:
            flags.append(True)
            m = FENCE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip().strip(fence[0]):
                fence = ""
                opened_at = -1
    return flags, opened_at


def _blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    current: Block | None = None
    flags, unclosed_at = _fence_flags(lines)
    if unclosed_at >= 0 and any(OPEN.match(line) or CLOSE.match(line) for line in lines[unclosed_at:]):
        raise FragmentError("unclosed code fence opened before a shared marker")
    for i, (line, fenced) in enumerate(zip(lines, flags)):
        if fenced:
            continue
        opened, closed = OPEN.match(line), CLOSE.match(line)
        if not (opened or closed) and line.lstrip().startswith(("<!-- shared:", "<!-- /shared:")):
            raise FragmentError(f"line {i + 1}: unrecognized shared marker (malformed, or indented 4+ spaces)")
        if opened:
            if current:
                raise FragmentError(f"line {i + 1}: marker '{opened.group(1)}' opens inside unclosed '{current.id}'")
            current = Block(opened.group(1), dict(ATTR.findall(opened.group(2))), i, -1)
        elif closed:
            if not current or current.id != closed.group(1):
                raise FragmentError(f"line {i + 1}: closing marker '{closed.group(1)}' mismatch")
            current.end = i
            blocks.append(current)
            current = None
    if current:
        raise FragmentError(f"line {current.start + 1}: unclosed marker '{current.id}'")
    return blocks


def _expand(block: Block, fragments: dict[str, str]) -> str:
    if block.id not in fragments:
        raise FragmentError(f"unknown fragment id '{block.id}'")
    text = fragments[block.id]
    needed = set(PLACEHOLDER.findall(text))
    for key in sorted(needed - block.attrs.keys()):
        raise FragmentError(f"block '{block.id}' misses parameter '{key}'")
    for key in sorted(block.attrs.keys() - needed):
        raise FragmentError(f"block '{block.id}' has unused parameter '{key}'")
    return PLACEHOLDER.sub(lambda m: block.attrs[m.group(1)], text)


def render(text: str, fragments: dict[str, str]) -> str:
    """Fill every block; a CRLF file stays CRLF; a mixed file keeps its lines outside blocks as they are."""
    crlf = "\r\n" in text and "\n" not in text.replace("\r\n", "")
    if crlf:
        text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    for block in reversed(_blocks(lines)):
        lines[block.start + 1 : block.end] = _expand(block, fragments).split("\n")
    out = "\n".join(lines)
    return out.replace("\n", "\r\n") if crlf else out


def strip_markers(text: str) -> str:
    lines = text.split("\n")
    for block in reversed(_blocks(lines)):
        del lines[block.end]
        del lines[block.start]
    return "\n".join(lines)


def drifted(text: str, fragments: dict[str, str]) -> list[str]:
    """Ids of blocks whose content differs from their fragment."""
    lines = text.split("\n")
    return [b.id for b in _blocks(lines) if lines[b.start + 1 : b.end] != _expand(b, fragments).split("\n")]


def find_unmarked(text: str, fragments: dict[str, str]) -> list[str]:
    """Ids of parameterless fragments whose full text occupies whole lines outside any block."""
    lines = text.split("\n")
    outside = list(lines)
    for block in reversed(_blocks(lines)):
        del outside[block.start : block.end + 1]
    rest = "\n" + "\n".join(outside) + "\n"
    return [k for k, v in fragments.items() if v and not PLACEHOLDER.search(v) and f"\n{v}\n" in rest]


def scan_files(root: Path) -> list[Path]:
    found: set[Path] = set()
    for plugin in sorted((root / "plugins").glob("*/")):
        found.update(plugin.glob("agents/*.md"))
        found.update(plugin.glob("commands/*.md"))
        found.update(plugin.glob("skills/**/*.md"))
    return sorted(found)


def check(root: Path) -> list[str]:
    """Drift, unmarked copies and `verbatim-in:` mismatches under `root`, one message each."""
    folder = root / FRAGMENTS_DIR
    fragments = load_fragments(folder)
    problems: list[str] = []
    for path in scan_files(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            problems += [f"{rel}: block '{i}' differs from {FRAGMENTS_DIR.as_posix()}/{i}.md" for i in drifted(text, fragments)]
            problems += [f"{rel}: text of '{i}' outside a block" for i in find_unmarked(text, fragments)]
        except FragmentError as err:
            problems.append(f"{rel}: {err}")
    for frag_id, target in verbatim_targets(folder).items():
        file = root / target
        if not file.is_file() or fragments[frag_id] not in file.read_text(encoding="utf-8"):
            problems.append(f"{target}: text of '{frag_id}' is not verbatim in it (shared/fragments/{frag_id}.md)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render shared fragments into marked blocks.")
    parser.add_argument("--check", action="store_true", help="report drift and unmarked copies; change nothing")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent.parent)
    args = parser.parse_args(argv)
    root: Path = args.root
    if args.check:
        problems = check(root)
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    fragments = load_fragments(root / FRAGMENTS_DIR)
    status = 0
    for path in scan_files(root):
        with path.open(encoding="utf-8", newline="") as f:
            text = f.read()
        try:
            new = render(text, fragments)
        except FragmentError as err:
            print(f"{path.relative_to(root).as_posix()}: {err}")
            status = 1
            continue
        if new != text:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(new)
            print(f"updated {path.relative_to(root).as_posix()}")
    return status


if __name__ == "__main__":
    sys.exit(main())
