"""Syntheses: one long Markdown document per subject, built from sections added or edited one at a time.

A synthesis is never rewritten whole (a model's rewrite of a whole document drops most of it): `add_section`
appends one section and `edit_section` replaces one section's text, and every other byte of the file stays as it
was. Each part ends with a `Sources:` line linking the notes it rests on, because a synthesis is third-hand.
Imports nothing from mem.py (mem.py imports this module), so matching takes a tokenizer.
"""
from __future__ import annotations

import datetime
import os
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import yaml

import records

SYNTHESES_DIR = "syntheses"
SUMMARY = "summary"
NOTE_FOLDERS = ("literature", "knowledge", "research")  # where a Sources link may point
_FRONTMATTER = re.compile(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)
_H2 = re.compile(r"^## +(\S.*?)\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
_HANDLE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass
class Section:
    handle: str
    heading: str
    text: str  # the text under the heading, without surrounding blank lines
    sources: list[str]  # the link targets (file part) of its `Sources:` line; empty when it has none
    line: int  # 1-based line of the heading in the file


@dataclass
class Synthesis:
    path: Path
    handle: str
    title: str = ""
    topics: list[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    sections: list[Section] = field(default_factory=list)
    error: str | None = None

    @property
    def parts(self) -> list[Section]:
        return [s for s in self.sections if s.handle != SUMMARY]


def section_handle(heading: str) -> str:
    """The heading in lower case, accents dropped, runs of other characters as one hyphen."""
    ascii_text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def split_ref(ref: str) -> tuple[str, str | None]:
    """`s:<h>` or `s:<h>#<section handle>` as (synthesis handle, section handle or None)."""
    name = ref.removeprefix("s:")
    handle, _, section = name.partition("#")
    return handle, (section or None) if "#" in name else None


def path_of(folder: Path, handle: str) -> Path | None:
    return folder / f"{handle}.md" if _HANDLE.fullmatch(handle) else None


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def _scan(text: str) -> tuple[list[str], list[tuple[int, str]]]:
    """The file's lines (split on LF only) and (index, heading) of each `## ` line after the frontmatter, outside code."""
    lines = text.split("\n")
    m = _FRONTMATTER.match(text)
    first = text[:m.end()].count("\n") if m else 0
    found: list[tuple[int, str]] = []
    fence = None
    for i in range(first, len(lines)):
        line = lines[i].rstrip("\r")
        f = _FENCE.match(line)
        if f:
            fence = None if fence and f.group(1)[0] == fence else (fence or f.group(1)[0])
            continue
        if fence is None and (h := _H2.match(line)):
            found.append((i, h.group(1)))
    return lines, found


def _links(line: str) -> list[str]:
    return [m.group(1) for m in _LINK.finditer(line)]


def _relative(target: str) -> bool:
    return not target.startswith(("#", "mailto:")) and not _SCHEME.match(target)


def _file_part(target: str) -> str:
    return urllib.parse.unquote(target.split("#", 1)[0])


def _sources_line(text: str) -> str | None:
    last = next((ln for ln in reversed(text.split("\n")) if ln.strip()), "")
    return last if last.startswith("Sources:") else None


def load_one(path: Path) -> Synthesis:
    syn = Synthesis(path, path.stem)
    try:
        text = _read(path)
        m = _FRONTMATTER.match(text)
        if not m:
            raise ValueError("no YAML frontmatter")
        meta = yaml.safe_load(m.group(1))
        if not isinstance(meta, dict):
            raise ValueError("frontmatter is not a mapping")
        title = meta.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is missing")
        topics = meta.get("topics")
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            raise ValueError("topics must be a list of topic ids")
        for key in ("created", "updated"):
            value = meta.get(key)
            if isinstance(value, datetime.datetime) or not isinstance(value, (str, datetime.date)):
                raise ValueError(f"{key} must be an ISO date")
            setattr(syn, key, value.isoformat() if isinstance(value, datetime.date) else value)
        syn.title, syn.topics = title.strip(), list(topics)
        lines, heads = _scan(text)
        for n, (i, heading) in enumerate(heads):
            end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
            body = "\n".join(lines[i + 1:end]).strip("\n")
            src = _sources_line(body)
            syn.sections.append(Section(section_handle(heading), heading, body,
                                        [_file_part(t) for t in _links(src) if _relative(t)] if src else [], i + 1))
        if not syn.sections or syn.sections[0].handle != SUMMARY:
            raise ValueError("the first section must be `## Summary`")
    except Exception as e:  # one broken file must not break the rest
        syn.error = f"{type(e).__name__}: {e}".splitlines()[0]
    return syn


def load(folder: Path | None) -> list[Synthesis]:
    """Every synthesis of the folder, sorted by handle; never raises."""
    try:
        if folder is None or not folder.is_dir():
            return []
        return [load_one(p) for p in sorted(folder.glob("*.md"), key=lambda p: p.stem) if p.is_file()]
    except OSError:
        return []


def validate_section(text: str, store: Path) -> list[str]:
    """Problems with a part's closing `Sources:` line: missing, without a relative link, or a link that does not
    resolve to a note file (literature, knowledge or research) inside the store."""
    line = _sources_line(text)
    if line is None:
        return ["the part must end with a `Sources:` line linking the notes it rests on"]
    targets = [t for t in _links(line) if _relative(t)]
    if not targets:
        return ["the `Sources:` line has no relative Markdown link to a note"]
    base, root = (store / SYNTHESES_DIR).resolve(), store.resolve()
    problems = []
    for target in targets:
        try:
            resolved = (base / _file_part(target)).resolve()
            rel = resolved.relative_to(root)
        except (OSError, ValueError):
            problems.append(f"source {target} points outside the store")
            continue
        if not (rel.parts and rel.parts[0] in NOTE_FOLDERS and resolved.suffix == ".md" and resolved.is_file()):
            problems.append(f"source {target} is not an existing note of the store")
    return problems


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").strip("\n")


def _check_body(text: str) -> None:
    lines, heads = _scan("---\nx: 1\n---\n" + text)
    if heads:
        raise ValueError(f"the text contains a `## {heads[0][1]}` heading: a section is one heading and its text")


def _bump(text: str, today: datetime.date) -> str:
    m = _FRONTMATTER.match(text)
    if not m:
        return text
    head = re.sub(r"^updated:[ \t]*.*$", f"updated: '{today.isoformat()}'", m.group(0), count=1, flags=re.M)
    return head + text[m.end():]


def render_new(template: str, *, title: str, topics: Sequence[str], summary: str, today: datetime.date) -> str:
    """The template with `{frontmatter}` and `{summary}` filled in."""
    meta = {"title": title, "topics": list(topics), "created": today.isoformat(), "updated": today.isoformat()}
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=None, width=10**6)
    return template.replace("{frontmatter}", head).replace("{summary}", _clean(summary))


def create(folder: Path, slug: str, text: str) -> Path:
    """Write a new synthesis file, never over an existing one."""
    if not _HANDLE.fullmatch(slug):
        raise ValueError(f"invalid slug {slug!r}: use lowercase letters, digits and hyphens")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.md"
    try:
        with path.open("x", encoding="utf-8", newline="") as f:
            f.write(text if text.endswith("\n") else text + "\n")
    except FileExistsError:
        raise ValueError(f"syntheses/{slug}.md already exists") from None
    return path


def add_section(path: Path, heading: str, text: str, today: datetime.date) -> str:
    """Append `## heading` and its text; returns the section handle. Logs the previous file for undo."""
    syn = load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    heading = " ".join(heading.split())
    handle = section_handle(heading)
    if not handle:
        raise ValueError("the heading has no letters or digits")
    if any(s.handle == handle for s in syn.sections):
        raise ValueError(f"a section with the handle {handle!r} already exists")
    text = _clean(text)
    if not text:
        raise ValueError("the section text is empty")
    _check_body(text)
    old = _read(path)
    base = old if old.endswith("\n") else old + "\n"
    new = base + ("" if base.endswith("\n\n") else "\n") + f"## {heading}\n\n{text}\n"
    records.log_before(syn, "add")
    _write(path, _bump(new, today))
    return handle


def edit_section(path: Path, section: str, text: str, today: datetime.date) -> None:
    """Replace the text under one section's heading; every other byte of the file stays. Logs the previous file."""
    syn = load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    target = next((s for s in syn.sections if s.handle == section), None)
    if target is None:
        raise ValueError(f"no section {section!r} in s:{syn.handle}")
    if sum(1 for s in syn.sections if s.handle == section) > 1:
        raise ValueError(f"the handle {section!r} is repeated in s:{syn.handle}: rename one heading first")
    text = _clean(text)
    if not text:
        raise ValueError("the section text is empty")
    _check_body(text)
    old = _read(path)
    lines, heads = _scan(old)
    n = next(k for k, (i, _) in enumerate(heads) if i + 1 == target.line)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    lines[heads[n][0] + 1:end] = ["", *text.split("\n"), ""]
    records.log_before(syn, "edit")
    _write(path, _bump("\n".join(lines), today))


def match_sections(syntheses: Sequence[Synthesis], query_tokens: Sequence[str], *,
                   tokenize: Callable[[str], list[str]], limit: int = 2) -> list[tuple[Synthesis, Section]]:
    """Sections holding at least half (rounded up) of the query's non-stop-word terms in heading and text.

    Best first: most terms in the heading, then most overall, then handle."""
    terms = set(query_tokens) - records.STOPWORDS
    if not terms:
        return []
    need = (len(terms) + 1) // 2
    scored = []
    for syn in syntheses:
        if syn.error is not None:
            continue
        for sec in syn.sections:
            in_heading = terms & set(tokenize(sec.heading))
            overall = terms & set(tokenize(sec.heading + " " + sec.text))
            if len(overall) >= need:
                scored.append((syn, sec, len(in_heading), len(overall)))
    scored.sort(key=lambda t: (-t[2], -t[3], t[0].handle, t[1].line))
    return [(s, sec) for s, sec, _, _ in scored[:limit]]
