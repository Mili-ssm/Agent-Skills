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


def validate_section(text: str, store: Path) -> list[str]:
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


def fingerprint(text: str) -> str:
    """A short hash of a section's text without its `Sources:` line and surrounding whitespace."""
    lines = text.split("\n")
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    if last is not None and lines[last].startswith("Sources:"):
        lines = lines[:last]
    return hashlib.sha256("\n".join(lines).strip().encode("utf-8")).hexdigest()[:10]


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


def _guard_shrink(old: str, new: str, *, sentences: bool = True) -> None:
    """Refuse a text that drops over 20% of the words, a link or, when `sentences`, a sentence of the old one
    (a one-sentence field such as a claim is checked without the sentence rule)."""
    dropped = max(word_count(old) - word_count(new), 0)
    lost = list(dict.fromkeys(t for t in _links(old) if t not in set(_links(new))))
    kept = set(_sentences(new))
    gone = [s for s in dict.fromkeys(_sentences(old)) if s not in kept] if sentences else []
    if lost or gone or word_count(new) < SHRINK_RATIO * word_count(old):
        parts = [f"{n} {name}" for n, name in ((dropped, "words"), (len(gone), "sentences")) if n]
        if lost:
            parts.append(f"the links {', '.join(lost)}")
        what = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
        raise ValueError(f"the new text drops {what}; use --shrink if that is meant.")


def edit_section(path: Path, section: str, text: str, today: datetime.date, *, shrink: bool = False) -> None:
    """Replace the text under one section's heading; every other byte of the file stays. Logs the previous file.

    Refused, unless `shrink`, when the new text has under 80% of the words or lacks a link of the old one."""
    syn, target = _target(path, section)
    text = _clean(text)
    if not text:
        raise ValueError("the section text is empty")
    _check_body(text)
    if not shrink:
        _guard_shrink(target.text, text)
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
