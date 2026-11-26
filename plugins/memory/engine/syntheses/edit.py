"""The writes of a synthesis: one section is added, replaced, renamed or removed at a time, and every other byte stays.

`edit_section` and its siblings return the new text and the log line; the guards refuse a rewrite that drops too much
or changes the sources. Imports nothing from mem.py.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypedDict

import yaml
from core import safe_io
from core.yaml_load import safe_load
from memories import journal
from memories.matching import STOPWORDS

from syntheses.document import (
    _FRONTMATTER,
    _HANDLE,
    SUMMARY,
    _links,
    _read,
    _resolved,
    _scan,
    _sources_line,
    _write,
    load_one,
    section_handle,
    shown,
    source_numbers,
    validate_section,
)
from syntheses.units import (
    _FRONTMATTER_SLOT,
    _GAP,
    _REF_LINK,
    _SUMMARY_SLOT,
    _is_ref,
    _parse,
    _relative,
    first_paragraph,
    units,
    without_references,
    word_count,
)

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable, Sequence
    from pathlib import Path
    from typing import Unpack

    from syntheses.document import Section, Synthesis
    from syntheses.units import _Ref

MIN_SENTENCE_WORDS = 6
YAML_WIDTH = 10**6  # no line folding
SHRINK_RATIO = 0.8


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


def append_text(
    section_text: str, text: str, *, store: Path | None = None, is_summary: bool = False
) -> str:
    """The section text after `text` is added at its end, before its `Sources:` line; links of a closing `Sources:`
    line in `text` join the section's own line. Pure: nothing is read or written."""
    text = _clean(text)
    if not text:
        raise ValueError("the text to append is empty")
    _check_body(text)
    old_src, new_src = _sources_line(section_text), _sources_line(text)
    main, added = _without_sources(section_text, old_src), _without_sources(text, new_src)
    items = _new_source_items(old_src, new_src)
    src = _merged_sources(old_src, items)
    if not added and not items:
        raise ValueError("the text to append adds nothing")
    new = "\n\n".join(p for p in (main, added, src) if p)
    if store is not None and not is_summary and (problems := validate_section(new, store)):
        raise ValueError("; ".join(problems))
    return new


def append_section(
    path: Path, section: str, text: str, today: datetime.date, *, store: Path | None = None
) -> None:
    """Add text at the end of a section, before its `Sources:` line; links of a closing `Sources:` line in `text`
    join the section's own line."""
    syn, target = _target(path, section)
    new = append_text(target.text, text, store=store, is_summary=section == SUMMARY)
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
