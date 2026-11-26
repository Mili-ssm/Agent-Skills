"""Syntheses: one long Markdown document per subject, built from sections added or edited one at a time.

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
from typing import TYPE_CHECKING, TypedDict

import yaml
from core import safe_io
from core.yaml_load import safe_load
from memories import journal
from memories.matching import STOPWORDS

from syntheses.units import (
    _FENCE,
    _FRONTMATTER_SLOT,
    _GAP,
    _REF_LINK,
    _SUMMARY_SLOT,
    NOTE_FOLDERS,
    _file_part,
    _is_ref,
    _next_fence,
    _note_key,
    _parse,
    _relative,
    first_paragraph,
    units,
    without_references,
    word_count,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Unpack

    from syntheses.units import _Ref

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
MIN_SENTENCE_WORDS = 6
NOTE_DIR_DEPTH = 3  # `<folder>/<dir>/<file>.md`: the folder is the third part from the end
YAML_WIDTH = 10**6  # no line folding
SHRINK_RATIO = 0.8


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


def snapshot(path: Path):
    """A function that puts back the synthesis and its curation log as they are now (for a write that must not
    leave half a change when a later step fails)."""
    log = path.parent / journal.CURATION_LOG
    before = path.read_bytes()
    log_before = log.read_bytes() if log.exists() else None

    def undo() -> None:
        safe_io.replace_file(path, before)
        if log_before is None:
            log.unlink(missing_ok=True)
        else:
            safe_io.replace_file(log, log_before)

    return undo


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").strip("\n")


def _check_body(text: str) -> None:
    _, heads = _scan("---\nx: 1\n---\n" + text)
    if heads:
        raise ValueError(
            f"the text contains a `## {heads[0][1]}` heading: a section is one heading and its text"
        )


def _bump(text: str, today: datetime.date) -> str:
    m = _FRONTMATTER.match(text)
    if not m:
        return text
    head = re.sub(
        r"^updated:[ \t]*.*$",
        f"updated: '{today.isoformat()}'",
        m.group(0),
        count=1,
        flags=re.MULTILINE,
    )
    return head + text[m.end() :]


def bumped(text: str, today: datetime.date) -> str:
    """The file text with `updated:` set to `today`."""
    return _bump(text, today)


def render_new(
    template: str, *, title: str, topics: Sequence[str], summary: str, today: datetime.date
) -> str:
    """The template with `{frontmatter}` and `{summary}` filled in."""
    meta = {
        "title": title,
        "topics": list(topics),
        "created": today.isoformat(),
        "updated": today.isoformat(),
    }
    head = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=None, width=YAML_WIDTH
    )
    return template.replace(_FRONTMATTER_SLOT, head).replace(_SUMMARY_SLOT, _clean(summary))


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


def prepare_add(path: Path, heading: str, text: str, today: datetime.date) -> tuple[str, str, str]:
    """Check an `add` without writing: (section handle, new file text, cleaned section text)."""
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
    return handle, _bump(new, today), text


def add_section(path: Path, heading: str, text: str, today: datetime.date) -> str:
    """Append `## heading` and its text; returns the section handle. Logs the previous file for undo."""
    handle, new, _ = prepare_add(path, heading, text, today)
    journal.log_before(load_one(path), "add")
    _write(path, new)
    return handle


def _target(path: Path, section: str) -> tuple[Synthesis, Section]:
    syn = load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    target = next((s for s in syn.sections if s.handle == section), None)
    if target is None:
        raise ValueError(f"no section {section!r} in s:{syn.handle}")
    if sum(1 for s in syn.sections if s.handle == section) > 1:
        raise ValueError(
            f"the handle {section!r} is repeated in s:{syn.handle}: rename one heading first"
        )
    return syn, target


def _replace(syn: Synthesis, target: Section, text: str, today: datetime.date, action: str) -> None:
    path = syn.path
    old = _read(path)
    lines, heads = _scan(old)
    n = next(k for k, (i, _) in enumerate(heads) if i + 1 == target.line)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    lines[heads[n][0] + 1 : end] = ["", *text.split("\n"), ""]
    journal.log_before(syn, action)
    _write(path, _bump("\n".join(lines), today))


def _sentences(text: str) -> list[str]:
    """Sentences of at least six words, whitespace collapsed and lower-cased; split on `.`, `!`, `?` and line breaks."""
    found = (" ".join(part.split()).lower() for part in re.split(r"[.!?\n]+", text))
    return [s for s in found if len(s.split()) >= MIN_SENTENCE_WORDS]


def _guard_shrink(
    old: str, new: str, *, sentences: bool = True, part: bool = False, drop_references: bool = False
) -> None:
    """Refuse a text that drops over 20% of the words, a link or, when `sentences`, a sentence of the old one
    (a one-sentence field such as a claim is checked without the sentence rule). For a `part`, sentences are
    compared without their references, and `drop_references` lets references go."""
    dropped = max(word_count(old) - word_count(new), 0)
    lost = list(dict.fromkeys(t for t in _links(old) if t not in set(_links(new))))
    if drop_references:
        lost = [t for t in lost if not _is_ref(t)]
    old_s, new_s = (without_references(old), without_references(new)) if part else (old, new)
    kept = set(_sentences(new_s))
    gone = [s for s in dict.fromkeys(_sentences(old_s)) if s not in kept] if sentences else []
    if lost or gone or word_count(new) < SHRINK_RATIO * word_count(old):
        parts = [f"{n} {name}" for n, name in ((dropped, "words"), (len(gone), "sentences")) if n]
        if lost:
            parts.append(f"the links {', '.join(lost)}")
        what = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
        raise ValueError(f"the new text drops {what}; use --shrink if that is meant.")


def _link_on_sources(text: str, base: Path, target: str) -> tuple[str, str] | None:
    """(label, target) as the part's `Sources:` line writes the note `target` names, or None."""
    line = _sources_line(text) or ""
    want = _resolved(base, target)
    for m in _REF_LINK.finditer(line):
        if _relative(m.group(2)) and _resolved(base, m.group(2)) == want:
            return m.group(1), m.group(2)
    return None


class _RefEditor:
    """The state of one `change_references` call: the parsed part and the edits its proposals add up to."""

    def __init__(self, text: str, base: Path) -> None:
        self.text, self.base = text, base
        self.found, self.refs, orphans, _ = _parse(text)
        self.orphan_at = {r.start for r in orphans}
        self.sources = {
            _resolved(base, m.group(2))
            for m in _REF_LINK.finditer(_sources_line(text) or "")
            if _relative(m.group(2))
        }
        self.edits: list[
            tuple[int, int, int, str]
        ] = []  # (position, input order, end, replacement)
        self.removed: dict[
            int, set[int]
        ] = {}  # unit number -> starts of the trailing references to take out
        self.seen: set[tuple[int, str, Path]] = set()

    def judge(self, order: int, proposal: tuple[int, str, str]) -> str | None:
        """Apply one proposal; the reason it was refused, or None."""
        n, op, target = proposal
        resolved = _resolved(self.base, target)
        if not 1 <= n <= len(self.found):
            return f"the part has no unit {n}"
        if resolved not in self.sources:
            return f"{target} is not on the part's Sources line"
        if (n, op, resolved) in self.seen:
            return f"the unit is already changed by an earlier line for {target}"
        own = self._own(n, resolved)
        reason = self._add(order, n, target, own) if op == "add" else self._remove(n, target, own)
        if reason is None:
            self.seen.add((n, op, resolved))
        return reason

    def _own(self, n: int, resolved: Path) -> list[_Ref]:
        unit = self.found[n - 1]
        return [
            r
            for r in self.refs
            if unit.span[0] <= r.start < unit.span[1]
            and r.start not in self.orphan_at
            and _resolved(self.base, r.target) == resolved
        ]

    def _add(self, order: int, n: int, target: str, own: list[_Ref]) -> str | None:
        unit = self.found[n - 1]
        if own:
            return f"unit {n} already carries {target}"
        if unit.text.lstrip().startswith("|"):
            return f"unit {n} is a table row"
        link = _link_on_sources(self.text, self.base, target)
        if link is None:  # not reachable: the target is on the Sources line
            return f"{target} is not on the part's Sources line"
        self.edits.append((unit.span[1], order, unit.span[1], f" [{link[0]}]({link[1]})"))
        return None

    def _remove(self, n: int, target: str, own: list[_Ref]) -> str | None:
        trailing = [r for r in own if r.trailing]
        if not own:
            return f"unit {n} does not carry {target}"
        if not trailing:
            return f"the reference to {target} in unit {n} is inside the sentence: it is part of its words"
        self.removed.setdefault(n, set()).add(trailing[0].start)
        return None

    def _removal(self, n: int, gone: set[int]) -> tuple[int, int, int, str]:
        """Write the unit's run of trailing references again without the removed ones, a space before each: taking
        one out of `[a](x), [b](y)` must not leave its comma behind."""
        unit = self.found[n - 1]
        run = [
            r
            for r in self.refs
            if r.trailing
            and r.start not in self.orphan_at
            and unit.span[0] <= r.start < unit.span[1]
        ]
        start = run[0].start
        while start > unit.span[0] and self.text[start - 1] in _GAP:
            start -= 1
        kept = "".join(" " + self.text[r.start : r.end] for r in run if r.start not in gone)
        return (start, -1, run[-1].end, kept)

    def result(self) -> str:
        edits = self.edits + [self._removal(n, gone) for n, gone in self.removed.items()]
        out = self.text
        for start, _, end, repl in sorted(edits, reverse=True):
            out = out[:start] + repl + out[end:]
        return out


def change_references(
    text: str, base: Path, proposals: Sequence[tuple[int, str, str]]
) -> tuple[str, list[str | None]]:
    """A part's text with references added or removed, and per proposal `(unit number, "add" | "remove", target)`
    the reason it was refused or None when it was applied. Every number refers to `text` as given; no word changes.

    An add writes the label and target of the note's link on the `Sources:` line at the end of the unit, after any
    references already there; a remove takes a reference that follows its sentence's closing punctuation, with the
    white space before it, and never one inside the sentence. `base` is the folder the part's links are relative to."""
    editor = _RefEditor(text, base)
    reasons = [editor.judge(order, proposal) for order, proposal in enumerate(proposals)]
    return editor.result(), reasons


def apply_part_text(path_text: str, section: str, new_text: str) -> str:
    """The file text with the body of `section` replaced by `new_text`; every other byte stays."""
    lines, heads = _scan(path_text)
    n = next(k for k, (_, h) in enumerate(heads) if section_handle(h) == section)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    region = "\n".join(lines[heads[n][0] + 1 : end])
    old = region.strip("\n")
    at = region.find(old)
    lines[heads[n][0] + 1 : end] = (region[:at] + new_text + region[at + len(old) :]).split("\n")
    return "\n".join(lines)


def _guard_references(old: str, new: str) -> None:
    """Refuse a new part that loses a reference of a sentence (or table row) it keeps word for word."""
    kept: dict[str, set[str]] = {}
    for u in units(new)[0]:
        kept.setdefault(" ".join(u.plain.split()), set()).update(u.refs)
    for u in units(old)[0]:
        key = " ".join(u.plain.split())
        if key in kept and (gone := [r for r in dict.fromkeys(u.refs) if r not in kept[key]]):
            raise ValueError(
                f"the new text drops the reference {gone[0]} from a sentence it keeps unchanged "
                f"(unit {u.n}: {key[:60]!r}); use --drop-references if that is meant."
            )


def _guard_shown(old: str, new: str) -> None:
    """Refuse a new part written from the reader's form of the old one (`shown`), where a reference is only a number
    or a label: saving it would lose the link."""
    flat, numbers = " ".join(new.split()), source_numbers(old)
    for u in units(old)[0]:
        if u.refs and re.search(
            re.escape(" ".join(shown(u.text, numbers).split())) + r"(?!\()", flat
        ):
            raise ValueError(
                f"the new text has only the number or label of a reference of the stored part (unit {u.n}: "
                f"{' '.join(u.plain.split())[:60]!r}); start from `mem show <part> --stored`, which "
                "prints the references with their links."
            )


class _EditOptions(TypedDict, total=False):
    shrink: bool
    drop_references: bool


def edit_section(
    path: Path, section: str, text: str, today: datetime.date, **options: Unpack[_EditOptions]
) -> None:
    """Replace the text under one section's heading; every other byte of the file stays. Logs the previous file.

    Refused, unless `shrink`, when the new text has under 80% of the words or lacks a link of the old one.
    Refused, unless `drop_references` (whatever `shrink` says), when a sentence kept unchanged loses a reference."""
    shrink = options.get("shrink", False)
    drop_references = options.get("drop_references", False)
    syn, target = _target(path, section)
    text = _clean(text)
    if not text:
        raise ValueError("the section text is empty")
    _check_body(text)
    _guard_shown(target.text, text)
    if not drop_references:
        _guard_references(target.text, text)
    if not shrink:
        _guard_shrink(target.text, text, part=True, drop_references=drop_references)
    _replace(syn, target, text, today, "edit")


def _without_sources(text: str, src: str | None) -> str:
    if src is None:
        return text.strip("\n")
    lines = text.rstrip("\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines[:-1]).strip("\n")


def _new_source_items(old_src: str | None, new_src: str | None) -> list[str]:
    """The entries of `new_src` that the section's own `Sources:` line does not hold yet."""
    if not new_src:
        return []
    have = old_src or ""
    return [
        i.strip()
        for i in re.split(
            r",\s*(?=\[|experience\b|https?://)", new_src.removeprefix("Sources:").strip()
        )
        if i.strip() and i.strip() not in have
    ]


def _merged_sources(old_src: str | None, items: list[str]) -> str | None:
    if old_src:
        return old_src.rstrip() + "".join(", " + i for i in items)
    return "Sources: " + ", ".join(items) if items else None


def append_section(
    path: Path, section: str, text: str, today: datetime.date, *, store: Path | None = None
) -> None:
    """Add text at the end of a section, before its `Sources:` line; links of a closing `Sources:` line in `text`
    join the section's own line."""
    syn, target = _target(path, section)
    text = _clean(text)
    if not text:
        raise ValueError("the text to append is empty")
    _check_body(text)
    old_src, new_src = _sources_line(target.text), _sources_line(text)
    main, added = _without_sources(target.text, old_src), _without_sources(text, new_src)
    items = _new_source_items(old_src, new_src)
    src = _merged_sources(old_src, items)
    if not added and not items:
        raise ValueError("the text to append adds nothing")
    new = "\n\n".join(p for p in (main, added, src) if p)
    if store is not None and section != SUMMARY and (problems := validate_section(new, store)):
        raise ValueError("; ".join(problems))
    _replace(syn, target, new, today, "append")


def _section_lines(path: Path, section: str) -> tuple[str, list[str], list[tuple[int, str]], int]:
    """(file text, its lines, its headings, index in the headings of `section`) from one read of the file."""
    old = _read(path)
    syn = load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    lines, heads = _scan(old)
    found = [n for n, (_, h) in enumerate(heads) if section_handle(h) == section]
    if not found:
        raise ValueError(f"no section {section!r} in s:{syn.handle}")
    if len(found) > 1:
        raise ValueError(
            f"the handle {section!r} is repeated in s:{syn.handle}: rename one heading by hand"
        )
    if section == SUMMARY:
        raise ValueError("the summary cannot be renamed or removed")
    return old, lines, heads, found[0]


def renamed_section(
    path: Path, section: str, heading: str, today: datetime.date
) -> tuple[str, str, str]:
    """(old file text, new file text, new section handle) with the section's heading replaced; the text stays."""
    old, lines, heads, n = _section_lines(path, section)
    heading = " ".join(heading.split())
    handle = section_handle(heading)
    if not handle:
        raise ValueError("the heading has no letters or digits")
    if handle == SUMMARY or (
        handle != section and any(section_handle(h) == handle for _, h in heads)
    ):
        raise ValueError(f"a section with the handle {handle!r} already exists")
    i = heads[n][0]
    lines[i] = f"## {heading}" + ("\r" if lines[i].endswith("\r") else "")
    return old, _bump("\n".join(lines), today), handle


def without_section(path: Path, section: str, today: datetime.date) -> tuple[str, str]:
    """(old file text, new file text) with the section's heading and text taken out; every other byte stays."""
    old, lines, heads, n = _section_lines(path, section)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    del lines[heads[n][0] : end]
    if n + 1 == len(heads):  # the last one: the file ends with the text before it and one newline
        while len(lines) > 1 and not lines[-1] and not lines[-2]:
            lines.pop()
    return old, _bump("\n".join(lines), today)


def _topics_range(lines: list[str], path: Path) -> tuple[int, int]:
    """(first, end) indexes of the `topics` field in the frontmatter lines."""
    start = next((i for i, ln in enumerate(lines) if ln.startswith(r"topics:")), None)
    if start is None:
        raise ValueError(f"{path.name} has no topics field")
    end = start + 1
    while end < len(lines) and re.match(r"(\s|- )", lines[end]):
        end += 1
    return start, end


def _check_topics(path: Path, new: str, topics: Sequence[str]) -> None:
    head = _FRONTMATTER.match(new)
    meta = safe_load(head.group(1)) if head else None
    got = meta.get("topics") if isinstance(meta, dict) else None
    if got != list(topics):
        raise ValueError(
            f"cannot rewrite the topics of {path.name}: edit its frontmatter by hand ({got!r})"
        )


def with_topics(path: Path, topics: Sequence[str], today: datetime.date) -> tuple[str, str]:
    """(old file text, new file text) with the frontmatter's `topics` replaced; every other byte stays."""
    old = _read(path)
    syn = load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    m = _FRONTMATTER.match(old)
    if m is None:
        raise ValueError(f"{path.name}: no YAML frontmatter")
    if "\r" in m.group(0):
        raise ValueError(f"{path.name} has CRLF line ends: convert it to LF first")
    lines = m.group(1).split("\n")
    start, end = _topics_range(lines, path)
    rendered = yaml.safe_dump(
        list(topics), allow_unicode=True, default_flow_style=True, width=YAML_WIDTH
    ).split("\n")[0]
    lines[start:end] = [f"topics: {rendered}"]
    new = _bump("---\n" + "\n".join(lines) + "\n---\n" + old[m.end() :], today)
    _check_topics(path, new, topics)
    return old, new


def match_sections(
    syntheses: Sequence[Synthesis],
    query_tokens: Sequence[str],
    *,
    tokenize: Callable[[str], list[str]],
    limit: int = 2,
) -> list[tuple[Synthesis, Section]]:
    """Sections holding at least half (rounded up) of the query's non-stop-word terms in heading and first paragraph.

    Best first: most terms in the heading, then most overall, then handle."""
    terms = set(query_tokens) - STOPWORDS
    if not terms:
        return []
    need = (len(terms) + 1) // 2
    scored = []
    for syn in syntheses:
        if syn.error is not None:
            continue
        for sec in syn.sections:
            in_heading = terms & set(tokenize(sec.heading))
            overall = terms & set(tokenize(sec.heading + " " + first_paragraph(sec.text)))
            if len(overall) >= need:
                scored.append((syn, sec, len(in_heading), len(overall)))
    scored.sort(key=lambda t: (-t[2], -t[3], t[0].handle, t[1].line))
    return [(s, sec) for s, sec, _, _ in scored[:limit]]
