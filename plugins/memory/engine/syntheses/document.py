"""Syntheses: one long Markdown document per subject, built from sections added or edited one at a time.

This module holds the document model, loading, validation and source numbering; `syntheses.units` parses units and
fingerprints, `syntheses.edit` writes sections.

A synthesis is never rewritten whole (a model's rewrite of a whole document drops most of it): `add_section`
appends one section and `edit_section` replaces one section's text, and every other byte of the file stays as it
was. Each part ends with a `Sources:` line linking the notes it rests on, because a synthesis is third-hand.
Imports nothing from mem.py (mem.py imports this module), so matching takes a tokenizer.
"""

from __future__ import annotations

import datetime
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from core import safe_io
from core.yaml_load import safe_load

from syntheses.units import (
    _FENCE,
    _REF_LINK,
    NOTE_FOLDERS,
    _file_part,
    _is_ref,
    _next_fence,
    _note_key,
    _parse,
    _relative,
    units,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


logger = logging.getLogger(__name__)

SYNTHESES_DIR = "syntheses"
SUMMARY = "summary"
_FRONTMATTER = re.compile(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
_H2 = re.compile(r"^## +(\S.*?)\s*$")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_HANDLE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_EXPERIENCE = re.compile(r"\bexperience (\d{4}-\d{2}-\d{2})\b")
_BARE_URL = re.compile(r"https://[^\s,;)\]]+")
LONG_SECTION_WORDS = 800
NOTE_DIR_DEPTH = 3  # `<folder>/<dir>/<file>.md`: the folder is the third part from the end


@dataclass
class Section:
    handle: str
    heading: str
    text: str  # the text under the heading, without surrounding blank lines
    sources: list[
        str
    ]  # the link targets (file part) of its `Sources:` line; empty when it has none
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
    safe_io.replace_file(path, text.encode("utf-8"))


def _scan(text: str) -> tuple[list[str], list[tuple[int, str]]]:
    """The file's lines (split on LF only) and (index, heading) of each `## ` line after the frontmatter, outside code."""
    lines = text.split("\n")
    m = _FRONTMATTER.match(text)
    first = text[: m.end()].count("\n") if m else 0
    found: list[tuple[int, str]] = []
    fence = None
    for i in range(first, len(lines)):
        line = lines[i].rstrip("\r")
        f = _FENCE.match(line)
        if f:
            fence = _next_fence(fence, f.group(1)[0])
            continue
        if fence is None and (h := _H2.match(line)):
            found.append((i, h.group(1)))
    return lines, found


def _links(line: str) -> list[str]:
    return [m.group(1) for m in _LINK.finditer(line)]


def _sources_line(text: str) -> str | None:
    last = next((ln for ln in reversed(text.split("\n")) if ln.strip()), "")
    return last if last.startswith("Sources:") else None


def _meta_of(text: str) -> dict[str, object]:
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError("no YAML frontmatter")
    meta = safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise _invalid("frontmatter is not a mapping")
    return meta


def _invalid(message: str) -> ValueError:
    return ValueError(message)


def _meta_title(meta: dict[str, object]) -> str:
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is missing")
    return title.strip()


def _meta_topics(meta: dict[str, object]) -> list[str]:
    topics = meta.get("topics")
    if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
        raise _invalid("topics must be a list of topic ids")
    return list(topics)


def _meta_date(meta: dict[str, object], key: str) -> str:
    value = meta.get(key)
    if isinstance(value, datetime.datetime) or not isinstance(value, (str, datetime.date)):
        raise _invalid(f"{key} must be an ISO date")
    return value.isoformat() if isinstance(value, datetime.date) else value


def _sections_of(text: str) -> list[Section]:
    lines, heads = _scan(text)
    sections = []
    for n, (i, heading) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = "\n".join(lines[i + 1 : end]).strip("\n")
        src = _sources_line(body)
        sources = [_file_part(t) for t in _links(src) if _relative(t)] if src else []
        sections.append(Section(section_handle(heading), heading, body, sources, i + 1))
    return sections


def _fill(syn: Synthesis, path: Path) -> None:
    """Read the file into `syn`; raises ValueError (or OSError) for a file that is not a synthesis."""
    text = _read(path)
    meta = _meta_of(text)
    title, topics = _meta_title(meta), _meta_topics(meta)
    for key in ("created", "updated"):
        setattr(syn, key, _meta_date(meta, key))
    syn.title, syn.topics = title, topics
    syn.sections.extend(_sections_of(text))
    if not syn.sections or syn.sections[0].handle != SUMMARY:
        raise ValueError("the first section must be `## Summary`")


def load_one(path: Path) -> Synthesis:
    syn = Synthesis(path, path.stem)
    try:
        _fill(syn, path)
    except Exception as e:  # one broken file must not break the rest
        logger.debug("cannot load %s", path, exc_info=True)
        syn.error = f"{type(e).__name__}: {e}".splitlines()[0]
    return syn


def load(folder: Path | None) -> list[Synthesis]:
    """Every synthesis of the folder, sorted by handle; never raises."""
    try:
        if folder is None or not folder.is_dir():
            return []
        return [
            load_one(p) for p in sorted(folder.glob("*.md"), key=lambda p: p.stem) if p.is_file()
        ]
    except OSError:
        return []


_SHOWN_NUMBER = re.compile(r"\[\d+\](?![(\[])")
_CODE_TEXT = re.compile(r"^(?:```|~~~).*?^(?:```|~~~)[^\n]*$|`[^`\n]*`", re.MULTILINE | re.DOTALL)


def _number_problems(text: str) -> list[str]:
    """A bracketed number such as `[3]` in a part: the form in which `mem show` prints a reference (`shown`), so a
    part that holds one was written from that form and lost the link."""
    found = list(dict.fromkeys(_SHOWN_NUMBER.findall(_CODE_TEXT.sub("", text))))
    return [
        f"{n} is how `mem show` prints a reference, not text to store: write the note's link in its place "
        "(`mem show <part> --stored` prints the part with its links)"
        for n in found
    ]


def validate_section(text: str, store: Path) -> list[str]:
    """Problems of a part: a bracketed number left from the form `mem show` prints, then those of
    `_validate_sources`."""
    return _number_problems(text) + _validate_sources(text, store)


def _has_citation(line: str, targets: list[str]) -> bool:
    loose = _LINK.sub("", line)
    experience = [d for d in _EXPERIENCE.findall(loose) if _is_date(d)]
    urls = [t for t in _links(line) if t.startswith("https://")] + _BARE_URL.findall(loose)
    return bool(targets or experience or urls)


def _unlisted_problems(text: str, base: Path, targets: list[str]) -> list[str]:
    sources = {_resolved(base, t) for t in targets}
    return [
        f"reference {target} names a note that is not on the `Sources:` line: add the note "
        "to the `Sources:` line or remove the reference"
        for target in dict.fromkeys(references(text))
        if _resolved(base, target) not in sources
    ]


def _target_problem(target: str, base: Path, root: Path) -> str | None:
    try:
        resolved = (base / _file_part(target)).resolve()
        rel = resolved.relative_to(root)
    except (OSError, ValueError):
        return f"source {target} points outside the store"
    if not (
        rel.parts
        and rel.parts[0] in NOTE_FOLDERS
        and resolved.suffix == ".md"
        and resolved.is_file()
    ):
        return f"source {target} is not an existing note of the store"
    return None


def _validate_sources(text: str, store: Path) -> list[str]:
    """Problems with a part's closing `Sources:` line: missing, citing nothing acceptable, or a note link that does
    not resolve to a note file (literature, knowledge or research) inside the store. A line may cite a note by a
    relative link, an `https` URL (link or bare), or `experience <YYYY-MM-DD>` for knowledge that has no note yet."""
    line = _sources_line(text)
    if line is None:
        return [
            "the part must end with a `Sources:` line citing a note link, an https URL or `experience <date>`"
        ]
    targets = [t for t in _links(line) if _relative(t)]
    if not _has_citation(line, targets):
        return [
            "the `Sources:` line has no relative Markdown link to a note, https URL or `experience <date>`"
        ]
    base, root = (store / SYNTHESES_DIR).resolve(), store.resolve()
    problems = _unlisted_problems(text, base, targets) + _orphan_problems(text)
    checked = (_target_problem(t, base, root) for t in targets)
    return problems + [p for p in checked if p is not None]


def _resolved(base: Path, target: str) -> Path:
    """The file a link names, so that `a/x.md` and `a/./x.md` are the same note."""
    try:
        return (base / _file_part(target)).resolve()
    except OSError:
        return base / _file_part(target)


def _orphan_problems(text: str) -> list[str]:
    return [
        f"reference {t} has no sentence before it on its line: a reference stands after the sentence it supports, on the same line"
        for t in dict.fromkeys(units(text)[1])
    ]


def summary_problems(text: str) -> list[str]:
    """The `## Summary` is no part: it holds no reference, because there is no sentence a reference could support."""
    return [
        f"reference {_file_part(r.target)} stands in the Summary, which is not a part: a reference stands "
        "after the sentence it supports, in a part"
        for r in _parse(text)[1]
    ]


def references(text: str) -> list[str]:
    """The targets (file part) of the references in a part's body, in order."""
    return [_file_part(r.target) for r in _parse(text)[1]]


def source_numbers(text: str) -> dict[str, int]:
    """The place (from 1) of each note on a part's `Sources:` line, by its link target."""
    found: dict[str, int] = {}
    for m in _REF_LINK.finditer(_sources_line(text) or ""):
        if _is_ref(m.group(2)):
            found.setdefault(_note_key(m.group(2)), len(found) + 1)
    return found


def shown(text: str, numbers: Mapping[str, int] | None = None) -> str:
    """`text` as a reader gets it: a reference that follows its sentence becomes `[n]`, the place of its note on the
    part's `Sources:` line (`numbers`, read from `text` when not given); one inside a sentence keeps its label as the
    word it is, followed by `[n]`. A reference to a note that is not on that line keeps only its label (`[note]`
    when it has none). On the `Sources:` line each note link is preceded by its number; everything else stays as
    stored, line breaks included.

    A number costs about 2 tokens where the stored link costs about 29 and its label about 5 to 10."""
    numbers = source_numbers(text) if numbers is None else numbers
    _, every, _, _ = _parse(text)
    line = _sources_line(text)
    if line is not None and numbers:
        # Each note on the `Sources:` line carries its number, so a reader need not count the entries.
        at = text.rindex(line)
        numbered = _REF_LINK.sub(
            lambda m: (
                (f"[{numbers[k]}] " if (k := _note_key(m.group(2))) in numbers else "") + m.group(0)
            ),
            line,
        )
        text = text[:at] + numbered + text[at + len(line) :]
    out, pos = [], 0
    for r in every:
        n = numbers.get(_note_key(r.target))
        if n is None:
            seen = f"[{r.label or 'note'}]"
        else:
            seen = f"[{n}]" if r.trailing else f"{r.label} [{n}]".strip()
        out.append(text[pos : r.start] + seen)
        pos = r.end
    return "".join(out) + text[pos:]


def shown_file(text: str) -> str:
    """`shown` for each part of a whole synthesis file; the frontmatter and the headings stay as stored."""
    lines, heads = _scan(text)
    m = _FRONTMATTER.match(text)
    first = text[: m.end()].count("\n") if m else 0
    bounds = [first] + [i + 1 for i, _ in heads]
    ends = [i for i, _ in heads] + [len(lines)]
    out = lines[:first]
    for n, start in enumerate(bounds):
        out.extend(shown("\n".join(lines[start : ends[n]])).split("\n") if start < ends[n] else [])
        if n < len(heads):
            out.append(lines[heads[n][0]])
    return "\n".join(out)


def _is_date(value: str) -> bool:
    try:
        datetime.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def source_kinds(text: str) -> set[str]:
    """What a part's `Sources:` line cites: the note folders (`literature`, `knowledge`, `research`), `url`,
    `experience`."""
    line = _sources_line(text) or ""
    kinds = {
        parts[-NOTE_DIR_DEPTH]
        for t in _links(line)
        if _relative(t)
        and len(parts := Path(_file_part(t)).parts) >= NOTE_DIR_DEPTH
        and parts[-NOTE_DIR_DEPTH] in NOTE_FOLDERS
    }
    loose = _LINK.sub("", line)
    if any(t.startswith("https://") for t in _links(line)) or _BARE_URL.search(loose):
        kinds.add("url")
    if any(_is_date(d) for d in _EXPERIENCE.findall(loose)):
        kinds.add("experience")
    return kinds
