"""Syntheses: one long Markdown document per subject, built from sections added or edited one at a time.

A synthesis is never rewritten whole (a model's rewrite of a whole document drops most of it): `add_section`
appends one section and `edit_section` replaces one section's text, and every other byte of the file stays as it
was. Each part ends with a `Sources:` line linking the notes it rests on, because a synthesis is third-hand.
Imports nothing from mem.py (mem.py imports this module), so matching takes a tokenizer.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import posixpath
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

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
_EXPERIENCE = re.compile(r"\bexperience (\d{4}-\d{2}-\d{2})\b")
_BARE_URL = re.compile(r"https://[^\s,;)\]]+")
LONG_SECTION_WORDS = 800
SHRINK_RATIO = 0.8


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


_SHOWN_NUMBER = re.compile(r"\[\d+\](?![(\[])")
_CODE_TEXT = re.compile(r"^(?:```|~~~).*?^(?:```|~~~)[^\n]*$|`[^`\n]*`", re.M | re.S)


def _number_problems(text: str) -> list[str]:
    """A bracketed number such as `[3]` in a part: the form in which `mem show` prints a reference (`shown`), so a
    part that holds one was written from that form and lost the link."""
    found = list(dict.fromkeys(_SHOWN_NUMBER.findall(_CODE_TEXT.sub("", text))))
    return [f"{n} is how `mem show` prints a reference, not text to store: write the note's link in its place "
            "(`mem show <part> --stored` prints the part with its links)" for n in found]


def validate_section(text: str, store: Path) -> list[str]:
    """Problems of a part: a bracketed number left from the form `mem show` prints, then those of
    `_validate_sources`."""
    return _number_problems(text) + _validate_sources(text, store)


def _validate_sources(text: str, store: Path) -> list[str]:
    """Problems with a part's closing `Sources:` line: missing, citing nothing acceptable, or a note link that does
    not resolve to a note file (literature, knowledge or research) inside the store. A line may cite a note by a
    relative link, an `https` URL (link or bare), or `experience <YYYY-MM-DD>` for knowledge that has no note yet."""
    line = _sources_line(text)
    if line is None:
        return ["the part must end with a `Sources:` line citing a note link, an https URL or `experience <date>`"]
    targets = [t for t in _links(line) if _relative(t)]
    loose = _LINK.sub("", line)
    experience = [d for d in _EXPERIENCE.findall(loose) if _is_date(d)]
    urls = [t for t in _links(line) if t.startswith("https://")] + _BARE_URL.findall(loose)
    if not (targets or experience or urls):
        return ["the `Sources:` line has no relative Markdown link to a note, https URL or `experience <date>`"]
    base, root = (store / SYNTHESES_DIR).resolve(), store.resolve()
    problems = []
    sources = {_resolved(base, t) for t in targets}
    for target in dict.fromkeys(references(text)):
        if _resolved(base, target) not in sources:
            problems.append(f"reference {target} names a note that is not on the `Sources:` line: add the note "
                            "to the `Sources:` line or remove the reference")
    problems += _orphan_problems(text)
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


def _resolved(base: Path, target: str) -> Path:
    """The file a link names, so that `a/x.md` and `a/./x.md` are the same note."""
    try:
        return (base / _file_part(target)).resolve()
    except OSError:
        return base / _file_part(target)


def _orphan_problems(text: str) -> list[str]:
    return [f"reference {t} has no sentence before it on its line: a reference stands after the sentence it supports, on the same line"
            for t in dict.fromkeys(units(text)[1])]


def summary_problems(text: str) -> list[str]:
    """The `## Summary` is no part: it holds no reference, because there is no sentence a reference could support."""
    return [f"reference {_file_part(r.target)} stands in the Summary, which is not a part: a reference stands "
            "after the sentence it supports, in a part" for r in _parse(text)[1]]


def references(text: str) -> list[str]:
    """The targets (file part) of the references in a part's body, in order."""
    return [_file_part(r.target) for r in _parse(text)[1]]


def _note_key(target: str) -> str:
    return posixpath.normpath(urllib.parse.unquote(_file_part(target)))


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
    _, every, _, body_end = _parse(text)
    line = _sources_line(text)
    if line is not None and numbers:
        # Each note on the `Sources:` line carries its number, so a reader need not count the entries.
        at = text.rindex(line)
        numbered = _REF_LINK.sub(lambda m: (f"[{numbers[k]}] " if (k := _note_key(m.group(2))) in numbers else "")
                                 + m.group(0), line)
        text = text[:at] + numbered + text[at + len(line):]
    out, pos = [], 0
    for r in every:
        n = numbers.get(_note_key(r.target))
        if n is None:
            seen = f"[{r.label or 'note'}]"
        else:
            seen = f"[{n}]" if r.trailing else f"{r.label} [{n}]".strip()
        out.append(text[pos:r.start] + seen)
        pos = r.end
    return "".join(out) + text[pos:]


def shown_file(text: str) -> str:
    """`shown` for each part of a whole synthesis file; the frontmatter and the headings stay as stored."""
    lines, heads = _scan(text)
    m = _FRONTMATTER.match(text)
    first = text[:m.end()].count("\n") if m else 0
    bounds = [first] + [i + 1 for i, _ in heads]
    ends = [i for i, _ in heads] + [len(lines)]
    out = lines[:first]
    for n, start in enumerate(bounds):
        out.extend(shown("\n".join(lines[start:ends[n]])).split("\n") if start < ends[n] else [])
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
    kinds = {parts[-3] for t in _links(line) if _relative(t) and len(parts := Path(_file_part(t)).parts) >= 3
             and parts[-3] in NOTE_FOLDERS}
    loose = _LINK.sub("", line)
    if any(t.startswith("https://") for t in _links(line)) or _BARE_URL.search(loose):
        kinds.add("url")
    if any(_is_date(d) for d in _EXPERIENCE.findall(loose)):
        kinds.add("experience")
    return kinds


_REF_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_LIST_MARK = re.compile(r"(?:>\s*)*(?:(?:[-*+]|\d+[.)])[ \t]+|#{1,6}[ \t]+)?")
_BOLD_LABEL = re.compile(r"\*\*[^*\n]*[.!?:]\*\*(?=\s|$)")
_TABLE_SEP = re.compile(r"\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*")
_ABBREVIATION = re.compile(r"(?:^|[\s(\[])(?:e\.g|i\.e|et al|vs|cf)$", re.I)
_CLOSERS = "\"'\u201d\u2019)]\u00bb"
_GAP = " \t,;"


@dataclass(frozen=True)
class Unit:
    """One sentence or table row of a part's body."""
    n: int  # 1-based
    text: str  # as stored, including the references that follow the sentence
    plain: str  # without references: trailing ones dropped, inline ones reduced to their label
    refs: list[str]  # targets (file part), in order
    span: tuple[int, int]  # character offsets in the part text, [start, end)


@dataclass(frozen=True)
class _Ref:
    start: int
    end: int
    label: str
    target: str
    trailing: bool  # follows the closing punctuation of its sentence: dropped, not reduced to its label


def _is_ref(target: str) -> bool:
    """A relative link into a note folder (the folders may be reached through leading `..`)."""
    if not _relative(target) or target.startswith("/"):
        return False
    parts = [p for p in posixpath.normpath(_file_part(target)).split("/") if p not in ("", ".")]
    while parts and parts[0] == "..":
        parts.pop(0)
    return len(parts) >= 2 and parts[0] in NOTE_FOLDERS and parts[-1].endswith(".md")


def _inline(raw: str) -> list[tuple[int, int, str, re.Match | None]]:
    """Code spans and links of a line, as (start, end, kind, match); nothing inside them splits or links."""
    found, i = [], 0
    while i < len(raw):
        if raw[i] == "`":
            n = len(raw[i:]) - len(raw[i:].lstrip("`"))
            j = i + n
            while (j := raw.find("`" * n, j)) != -1 and raw[j:j + n + 1] == "`" * (n + 1):
                j += len(raw[j:]) - len(raw[j:].lstrip("`"))
            if j != -1:
                found.append((i, j + n, "code", None))
                i = j + n
                continue
            i += n
        elif raw[i] == "[" and (m := _REF_LINK.match(raw, i)):
            found.append((i, m.end(), "link", m))
            i = m.end()
        else:
            i += 1
    return found


def _remove(text: str, lo: int, hi: int, refs: Sequence[_Ref]) -> str:
    out, pos = [], lo
    for r in refs:
        if r.trailing:
            s = r.start
            while s > pos and text[s - 1] in _GAP:
                s -= 1
            out.append(text[pos:s])
        else:
            out.append(text[pos:r.start] + r.label)
        pos = r.end
    return "".join(out) + text[pos:hi]


def _parse(text: str) -> tuple[list[Unit], list[_Ref], list[_Ref], int]:
    """(units, every reference of the body in order, the references without an owner, end of the body)."""
    lines = text.split("\n")
    offsets, o = [], 0
    for ln in lines:
        offsets.append(o)
        o += len(ln) + 1
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    count, body_end = len(lines), len(text)
    if last is not None and lines[last].startswith("Sources:"):
        count, body_end = last, offsets[last]
    found: list[tuple[int, int, list[_Ref]]] = []
    orphans: list[_Ref] = []
    fence, prev_blank = None, True

    def ref_of(m: re.Match, base: int, trailing: bool) -> _Ref:
        return _Ref(base + m.start(), base + m.end(), m.group(1), m.group(2), trailing)

    for i in range(count):
        raw, base = lines[i].rstrip("\r"), offsets[i]
        f = _FENCE.match(raw)
        if f:
            fence = None if fence and f.group(1)[0] == fence else (fence or f.group(1)[0])
            prev_blank = False
            continue
        if fence:
            continue
        if not raw.strip():
            prev_blank = True
            continue
        was_blank, prev_blank = prev_blank, False
        spans = _inline(raw)
        links = {s: (e, m) for s, e, kind, m in spans if kind == "link" and _is_ref(m.group(2))}
        starts = {s: e for s, e, _, _ in spans}
        ce = len(raw.rstrip())
        if raw.lstrip().startswith("|"):
            if _TABLE_SEP.fullmatch(raw) and "-" in raw:
                continue
            cs = len(raw) - len(raw.lstrip())
            refs = []
            for s, (e, m) in links.items():
                k = s
                while k > cs and raw[k - 1] in _GAP:
                    k -= 1
                refs.append(ref_of(m, base, k > cs and raw[k - 1] in ".!?" + _CLOSERS))
            found.append((base + cs, base + ce, refs))
            continue
        cs = _LIST_MARK.match(raw).end()
        if was_blank or cs > 0:
            if m := _BOLD_LABEL.match(raw, cs, ce):
                # A reference inside a label supports no sentence: it has no owner.
                orphans.extend(ref_of(lm, base, False) for s, (_, lm) in links.items() if cs <= s < m.end())
                cs = m.end()
        pos = cs

        def skip_gap(p: int, chars: str = " \t") -> int:
            while p < ce and raw[p] in chars:
                p += 1
            return p
        pos = skip_gap(pos)
        while pos in links:  # a reference with no sentence before it
            end, m = links[pos]
            orphans.append(ref_of(m, base, False))
            pos = skip_gap(end, _GAP)
        ustart, k = pos, pos
        while k < ce:
            if k in starts:
                k = starts[k]
                continue
            if raw[k] not in ".!?":
                k += 1
                continue
            j = k + 1
            while j < ce and raw[j] in ".!?":
                j += 1
            t = j
            while t < ce and raw[t] in _CLOSERS:
                t += 1
            if not (t >= ce or raw[t].isspace() or t in links) or (
                    raw[k] == "." and j == k + 1 and _ABBREVIATION.search(raw[ustart:k])):
                k = j
                continue
            if not re.search(r"\w", raw[ustart:k]):
                k = ustart = skip_gap(t)
                continue
            end = t
            while True:  # references that follow the closing punctuation
                p = skip_gap(end, _GAP)
                if p not in links:
                    break
                end = links[p][0]
            refs = [ref_of(m, base, s >= t) for s, (e, m) in links.items() if ustart <= s < end]
            found.append((base + ustart, base + end, refs))
            k = ustart = skip_gap(end)
        if ustart < ce and re.search(r"\w", raw[ustart:ce]):
            refs = [ref_of(m, base, False) for s, (e, m) in links.items() if ustart <= s < ce]
            found.append((base + ustart, base + ce, refs))
    units = [Unit(n, text[a:b], _remove(text, a, b, refs), [_file_part(r.target) for r in refs], (a, b))
             for n, (a, b, refs) in enumerate(found, 1)]
    every = sorted([r for _, _, refs in found for r in refs] + orphans, key=lambda r: r.start)
    return units, every, orphans, body_end


def units(text: str) -> tuple[list[Unit], list[str]]:
    """A part's body (everything but the closing `Sources:` line) as numbered units, and the targets of the
    references that have no owner.

    A unit is a sentence or a table row. A reference is a relative link into a note folder; one that follows a
    sentence's closing punctuation (white space, `,` or `;` between) belongs to that sentence, and so does one
    inside it. A bold label that opens a paragraph or list item (`**What it is.**`) belongs to no unit."""
    found, _, orphans, _ = _parse(text)
    return found, [_file_part(r.target) for r in orphans]


def _body_without_references(text: str) -> tuple[str, int]:
    _, every, _, body_end = _parse(text)
    return _remove(text, 0, body_end, every), body_end


def without_references(text: str) -> str:
    """The part's text with the references of its body removed (the `Sources:` line stays as it is)."""
    body, body_end = _body_without_references(text)
    return body + text[body_end:]


def fingerprint(text: str) -> str:
    """A short hash of a section's text without its `Sources:` line, its references and surrounding whitespace."""
    return _hash(_body_without_references(text)[0])


def _hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:10]


def fingerprint_legacy(text: str) -> str:
    """The fingerprint before references existed: stored by notes stamped earlier, still accepted."""
    lines = text.split("\n")
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    if last is not None and lines[last].startswith("Sources:"):
        lines = lines[:last]
    return _hash("\n".join(lines))


def is_current(stored: object, text: str) -> bool:
    """Whether a note's `part_of_hash` matches the part's text, by the current or the legacy fingerprint."""
    return stored in (fingerprint(text), fingerprint_legacy(text))


def word_count(text: str) -> int:
    return len(text.split())


def first_paragraph(text: str) -> str:
    """The text up to the first blank line; empty when that paragraph is the `Sources:` line."""
    para = re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]
    return "" if para.startswith("Sources:") else para


def snapshot(path: Path):
    """A function that puts back the synthesis and its curation log as they are now (for a write that must not
    leave half a change when a later step fails)."""
    log = path.parent / records.CURATION_LOG
    before = path.read_bytes()
    log_before = log.read_bytes() if log.exists() else None

    def undo() -> None:
        path.write_bytes(before)
        if log_before is None:
            log.unlink(missing_ok=True)
        else:
            log.write_bytes(log_before)
    return undo


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


def bumped(text: str, today: datetime.date) -> str:
    """The file text with `updated:` set to `today`."""
    return _bump(text, today)


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
    records.log_before(load_one(path), "add")
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
        raise ValueError(f"the handle {section!r} is repeated in s:{syn.handle}: rename one heading first")
    return syn, target


def _replace(path: Path, syn: Synthesis, target: Section, text: str, today: datetime.date, action: str) -> None:
    old = _read(path)
    lines, heads = _scan(old)
    n = next(k for k, (i, _) in enumerate(heads) if i + 1 == target.line)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    lines[heads[n][0] + 1:end] = ["", *text.split("\n"), ""]
    records.log_before(syn, action)
    _write(path, _bump("\n".join(lines), today))


def _sentences(text: str) -> list[str]:
    """Sentences of at least six words, whitespace collapsed and lower-cased; split on `.`, `!`, `?` and line breaks."""
    found = (" ".join(part.split()).lower() for part in re.split(r"[.!?\n]+", text))
    return [s for s in found if len(s.split()) >= 6]


def _guard_shrink(old: str, new: str, *, sentences: bool = True, part: bool = False,
                  drop_references: bool = False) -> None:
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


def change_references(text: str, base: Path, proposals: Sequence[tuple[int, str, str]]) -> tuple[str, list[str | None]]:
    """A part's text with references added or removed, and per proposal `(unit number, "add" | "remove", target)`
    the reason it was refused or None when it was applied. Every number refers to `text` as given; no word changes.

    An add writes the label and target of the note's link on the `Sources:` line at the end of the unit, after any
    references already there; a remove takes a reference that follows its sentence's closing punctuation, with the
    white space before it, and never one inside the sentence. `base` is the folder the part's links are relative to."""
    found, refs, orphans, _ = _parse(text)
    sources = {_resolved(base, m.group(2)) for m in _REF_LINK.finditer(_sources_line(text) or "") if _relative(m.group(2))}
    orphan_at = {r.start for r in orphans}
    reasons: list[str | None] = []
    edits: list[tuple[int, int, int, str]] = []  # (position, input order, end, replacement)
    removed: dict[int, set[int]] = {}  # unit number -> starts of the trailing references to take out
    seen: set[tuple[int, str, Path]] = set()
    for order, (n, op, target) in enumerate(proposals):
        resolved = _resolved(base, target)
        if not 1 <= n <= len(found):
            reasons.append(f"the part has no unit {n}")
            continue
        unit = found[n - 1]
        if resolved not in sources:
            reasons.append(f"{target} is not on the part's Sources line")
            continue
        own = [r for r in refs if unit.span[0] <= r.start < unit.span[1] and r.start not in orphan_at
               and _resolved(base, r.target) == resolved]
        if (n, op, resolved) in seen:
            reasons.append(f"the unit is already changed by an earlier line for {target}")
            continue
        if op == "add":
            if own:
                reasons.append(f"unit {n} already carries {target}")
            elif unit.text.lstrip().startswith("|"):
                reasons.append(f"unit {n} is a table row")
            else:
                label, written = _link_on_sources(text, base, target)
                edits.append((unit.span[1], order, unit.span[1], f" [{label}]({written})"))
                seen.add((n, op, resolved))
                reasons.append(None)
            continue
        trailing = [r for r in own if r.trailing]
        if not own:
            reasons.append(f"unit {n} does not carry {target}")
        elif not trailing:
            reasons.append(f"the reference to {target} in unit {n} is inside the sentence: it is part of its words")
        else:
            removed.setdefault(n, set()).add(trailing[0].start)
            seen.add((n, op, resolved))
            reasons.append(None)
    for n, gone in removed.items():
        # Write the unit's run of trailing references again without the removed ones, a space before each: taking
        # one out of `[a](x), [b](y)` must not leave its comma behind.
        unit = found[n - 1]
        run = [r for r in refs if r.trailing and r.start not in orphan_at and unit.span[0] <= r.start < unit.span[1]]
        start = run[0].start
        while start > unit.span[0] and text[start - 1] in _GAP:
            start -= 1
        kept = "".join(" " + text[r.start:r.end] for r in run if r.start not in gone)
        edits.append((start, -1, run[-1].end, kept))
    out = text
    for start, _, end, repl in sorted(edits, reverse=True):
        out = out[:start] + repl + out[end:]
    return out, reasons


def apply_part_text(path_text: str, section: str, new_text: str) -> str:
    """The file text with the body of `section` replaced by `new_text`; every other byte stays."""
    lines, heads = _scan(path_text)
    n = next(k for k, (_, h) in enumerate(heads) if section_handle(h) == section)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    region = "\n".join(lines[heads[n][0] + 1:end])
    old = region.strip("\n")
    at = region.find(old)
    lines[heads[n][0] + 1:end] = (region[:at] + new_text + region[at + len(old):]).split("\n")
    return "\n".join(lines)


def _guard_references(old: str, new: str) -> None:
    """Refuse a new part that loses a reference of a sentence (or table row) it keeps word for word."""
    kept: dict[str, set[str]] = {}
    for u in units(new)[0]:
        kept.setdefault(" ".join(u.plain.split()), set()).update(u.refs)
    for u in units(old)[0]:
        key = " ".join(u.plain.split())
        if key in kept and (gone := [r for r in dict.fromkeys(u.refs) if r not in kept[key]]):
            raise ValueError(f"the new text drops the reference {gone[0]} from a sentence it keeps unchanged "
                             f"(unit {u.n}: {key[:60]!r}); use --drop-references if that is meant.")


def _guard_shown(old: str, new: str) -> None:
    """Refuse a new part written from the reader's form of the old one (`shown`), where a reference is only a number
    or a label: saving it would lose the link."""
    flat, numbers = " ".join(new.split()), source_numbers(old)
    for u in units(old)[0]:
        if u.refs and re.search(re.escape(" ".join(shown(u.text, numbers).split())) + r"(?!\()", flat):
            raise ValueError(f"the new text has only the number or label of a reference of the stored part (unit {u.n}: "
                             f"{' '.join(u.plain.split())[:60]!r}); start from `mem show <part> --stored`, which "
                             "prints the references with their links.")


def edit_section(path: Path, section: str, text: str, today: datetime.date, *, shrink: bool = False,
                 drop_references: bool = False) -> None:
    """Replace the text under one section's heading; every other byte of the file stays. Logs the previous file.

    Refused, unless `shrink`, when the new text has under 80% of the words or lacks a link of the old one.
    Refused, unless `drop_references` (whatever `shrink` says), when a sentence kept unchanged loses a reference."""
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
    _replace(path, syn, target, text, today, "edit")


def append_section(path: Path, section: str, text: str, today: datetime.date, *, store: Path | None = None) -> None:
    """Add text at the end of a section, before its `Sources:` line; links of a closing `Sources:` line in `text`
    join the section's own line."""
    syn, target = _target(path, section)
    text = _clean(text)
    if not text:
        raise ValueError("the text to append is empty")
    _check_body(text)
    old_src, new_src = _sources_line(target.text), _sources_line(text)

    def without_sources(t: str, src: str | None) -> str:
        if src is None:
            return t.strip("\n")
        lines = t.rstrip("\n").split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines[:-1]).strip("\n")

    main, added = without_sources(target.text, old_src), without_sources(text, new_src)
    items = []
    if new_src:
        have = old_src or ""
        items = [i.strip() for i in re.split(r",\s*(?=\[|experience\b|https?://)", new_src.removeprefix("Sources:").strip())
                 if i.strip() and i.strip() not in have]
    if old_src:
        src = old_src.rstrip() + "".join(", " + i for i in items)
    else:
        src = "Sources: " + ", ".join(items) if items else None
    if not added and not items:
        raise ValueError("the text to append adds nothing")
    new = "\n\n".join(p for p in (main, added, src) if p)
    if store is not None and section != SUMMARY and (problems := validate_section(new, store)):
        raise ValueError("; ".join(problems))
    _replace(path, syn, target, new, today, "append")


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
        raise ValueError(f"the handle {section!r} is repeated in s:{syn.handle}: rename one heading by hand")
    if section == SUMMARY:
        raise ValueError("the summary cannot be renamed or removed")
    return old, lines, heads, found[0]


def renamed_section(path: Path, section: str, heading: str, today: datetime.date) -> tuple[str, str, str]:
    """(old file text, new file text, new section handle) with the section's heading replaced; the text stays."""
    old, lines, heads, n = _section_lines(path, section)
    heading = " ".join(heading.split())
    handle = section_handle(heading)
    if not handle:
        raise ValueError("the heading has no letters or digits")
    if handle == SUMMARY or (handle != section and any(section_handle(h) == handle for _, h in heads)):
        raise ValueError(f"a section with the handle {handle!r} already exists")
    i = heads[n][0]
    lines[i] = f"## {heading}" + ("\r" if lines[i].endswith("\r") else "")
    return old, _bump("\n".join(lines), today), handle


def without_section(path: Path, section: str, today: datetime.date) -> tuple[str, str]:
    """(old file text, new file text) with the section's heading and text taken out; every other byte stays."""
    old, lines, heads, n = _section_lines(path, section)
    end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
    del lines[heads[n][0]:end]
    if n + 1 == len(heads):  # the last one: the file ends with the text before it and one newline
        while len(lines) > 1 and lines[-1] == "" and lines[-2] == "":
            lines.pop()
    return old, _bump("\n".join(lines), today)


def with_topics(path: Path, topics: Sequence[str], today: datetime.date) -> tuple[str, str]:
    """(old file text, new file text) with the frontmatter's `topics` replaced; every other byte stays."""
    old = _read(path)
    syn = load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    m = _FRONTMATTER.match(old)
    if "\r" in m.group(0):
        raise ValueError(f"{path.name} has CRLF line ends: convert it to LF first")
    lines = m.group(1).split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(r"topics:", ln)), None)
    if start is None:
        raise ValueError(f"{path.name} has no topics field")
    end = start + 1
    while end < len(lines) and re.match(r"(\s|- )", lines[end]):
        end += 1
    rendered = yaml.safe_dump(list(topics), allow_unicode=True, default_flow_style=True, width=10**6).split("\n")[0]
    lines[start:end] = [f"topics: {rendered}"]
    new = _bump("---\n" + "\n".join(lines) + "\n---\n" + old[m.end():], today)
    if (meta := yaml.safe_load(_FRONTMATTER.match(new).group(1))).get("topics") != list(topics):
        raise ValueError(f"cannot rewrite the topics of {path.name}: edit its frontmatter by hand ({meta.get('topics')!r})")
    return old, new


def match_sections(syntheses: Sequence[Synthesis], query_tokens: Sequence[str], *,
                   tokenize: Callable[[str], list[str]], limit: int = 2) -> list[tuple[Synthesis, Section]]:
    """Sections holding at least half (rounded up) of the query's non-stop-word terms in heading and first paragraph.

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
            overall = terms & set(tokenize(sec.heading + " " + first_paragraph(sec.text)))
            if len(overall) >= need:
                scored.append((syn, sec, len(in_heading), len(overall)))
    scored.sort(key=lambda t: (-t[2], -t[3], t[0].handle, t[1].line))
    return [(s, sec) for s, sec, _, _ in scored[:limit]]
