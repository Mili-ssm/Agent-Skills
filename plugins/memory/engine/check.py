"""The check rules, `check()`, `orphan_notes` and the due-retest and re-read queries. Imports notes and index, never mem."""

from __future__ import annotations

import collections
import datetime
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple

import syntheses
from index import INDEX_FOLDERS, INDEX_START, _with_index, index_targets
from notes import (FrontmatterError, Note, _handle, _is_hidden, _parent, _read_text, ancestors, descendants,
                   discover_notes, key_line, load_topics, root_of, root_topics, slugify)


class Problem(NamedTuple):
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


NAME_PATTERNS: dict[str, re.Pattern] = {
    "literature": re.compile(r"[0-9]{4}-[a-z0-9]+-[a-z0-9]+(-[a-z0-9]+)*\.md"),
    "knowledge": re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*\.md"),
    "research": re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])-[a-z0-9]+(-[a-z0-9]+)*"),
}
RESERVED_TOPIC = "general"
_TOPIC_ID = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")
_NAME_FIX = {
    "literature": "rename to year-firstauthor-slug.md",
    "knowledge": "rename to lowercase-words-with-hyphens.md, starting with a letter",
    "research": "rename the folder to YYYY-MM-slug",
}

# Rule 11. Noun/verb homographs (check, test, cache, index, scale, prompt, query, start, stop,
# move, pin, separate, split, run, read, write, log, record, set, limit, measure, document,
# store) are left out on purpose, so a real claim is not rejected. Known limitation: a claim
# that starts with one of these words (use-after-free-...) is rejected too.
_IMPERATIVES = frozenset(
    "add always apply ask avoid choose compare consider curate define do dont ensure fix give "
    "include isolate keep make never prefer put remove replace require show tell treat try use "
    "validate verify wrap".split())
_INSTRUCTION_FIX = ('rename to a declarative claim such as "x-is-y" and update links')


def instruction_word(stem: str) -> str | None:
    """The imperative that makes a knowledge file stem read as an instruction, else None.

    Looked at: the first token and the token right after a "so" or "then" token.
    """
    tokens = stem.split("-")
    positions = [0] + [i + 1 for i, t in enumerate(tokens[:-1]) if t in ("so", "then")]
    return next((tokens[i] for i in positions if tokens[i] in _IMPERATIVES), None)


Validator = Callable[[Any], "str | None"]


def _string(v: Any) -> str | None:
    return None if isinstance(v, str) and v.strip() else "set a non-empty string"


def _enum(*allowed: str) -> Validator:
    def check_enum(v: Any) -> str | None:
        return None if v in allowed else f"use one of {', '.join(allowed)}"
    return check_enum


def _year(v: Any) -> str | None:
    return None if isinstance(v, int) and not isinstance(v, bool) else "set an integer year"


def _url(v: Any) -> str | None:
    ok = isinstance(v, str) and v.startswith(("http://", "https://"))
    return None if ok else "start the url with http:// or https://"


def _date(v: Any) -> str | None:
    if isinstance(v, str) and _DATE.fullmatch(v):
        try:
            datetime.date.fromisoformat(v)
            return None
        except ValueError:
            pass
    return "use a real date as a YYYY-MM-DD string"


def _month(v: Any) -> str | None:
    return None if isinstance(v, str) and _MONTH.fullmatch(v) else 'use a "YYYY-MM" string'


def _authors(v: Any) -> str | None:
    ok = isinstance(v, list) and v and all(isinstance(a, str) and a.strip() for a in v)
    return None if ok else "set a list of one or more non-empty strings"


def _topics(v: Any) -> str | None:
    ok = isinstance(v, list) and all(isinstance(t, str) for t in v)
    return None if ok else "set a list of topic ids from topics.yaml"


_PART_OF = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*#[a-z0-9]+(?:-[a-z0-9]+)*")


def _part_of(v: Any) -> str | None:
    return None if isinstance(v, str) and _PART_OF.fullmatch(v) else "use <synthesis handle>#<section handle>"


def _part_hash(v: Any) -> str | None:
    return None if isinstance(v, str) and re.fullmatch(r"(?:u:)?[0-9a-f]{10}", v) else "set the 10-hex fingerprint of the section (`u:` first for a per-note one)"


def _handle_value(v: Any) -> str | None:
    return None if isinstance(v, str) and v.strip() else "use the handle of a note"


def _handle_list(v: Any) -> str | None:
    ok = isinstance(v, list) and all(isinstance(h, str) and h.strip() for h in v)
    return None if ok else "set a list of note handles"


_DISPUTE_KEYS = ("date", "fact", "source", "quote")


def _disputed(v: Any) -> str | None:
    hint = "set a non-empty list of {date, fact, source, quote} entries (mem note dispute writes them)"
    if not isinstance(v, list) or not v:
        return hint
    for entry in v:
        if not isinstance(entry, dict) or set(entry) != set(_DISPUTE_KEYS):
            return hint
        if _date(entry["date"]) is not None or any(not isinstance(entry[k], str) or not entry[k].strip()
                                                    for k in _DISPUTE_KEYS[1:]) or _url(entry["source"]) is not None:
            return hint
    return None


LEVELS = ("basic", "beginner", "intermediate", "advanced", "expert", "niche")
# Fields a note may omit. Empty since 2026-11-07: `level` became required once every note had one (ADR 0004).
OPTIONAL_FIELDS: frozenset[str] = frozenset({"part_of", "part_of_hash", "superseded_by", "distinct_from", "disputed"})

# Field order follows the spec tables; `new` writes fields in this order.
SCHEMAS: dict[str, dict[str, Validator]] = {
    "literature": {
        "title": _string,
        "authors": _authors,
        "year": _year,
        "kind": _enum("paper", "book", "article", "web", "talk", "repo", "dataset"),
        "level": _enum(*LEVELS),
        "url": _url,
        "topics": _topics,
        "added": _date,
        "superseded_by": _handle_value,
        "distinct_from": _handle_list,
    },
    "knowledge": {
        "claim": _string,
        "topics": _topics,
        "confidence": _enum("high", "medium", "low"),
        "level": _enum(*LEVELS),
        "origin": _enum("literature", "research", "experience"),
        "updated": _date,
        "part_of": _part_of,
        "part_of_hash": _part_hash,
        "superseded_by": _handle_value,
        "distinct_from": _handle_list,
        "disputed": _disputed,
    },
    "research": {
        "title": _string,
        "question": _string,
        "status": _enum("idea", "active", "paused", "done", "abandoned"),
        "started": _month,
        "topics": _topics,
        "superseded_by": _handle_value,
        "distinct_from": _handle_list,
    },
}

REQUIRED_HEADINGS: dict[str, list[str]] = {
    "literature": ["TL;DR", "What the source says", "Our interpretation", "Relevance"],
    "knowledge": ["Claim", "Evidence", "Applies when", "Does not apply when"],
    "research": ["Question", "Status", "Findings", "Contents"],
}
# An investigation with its own experiments (spec 5.5, ADR 0008) also states what it improves on.
BASELINE_HEADING = "Baseline and contribution"
EXPERIMENT_DIRS = ("code", "results")


def _visible(directory: Path, root: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if not _is_hidden(p, root))


def _has_committable_file(folder: Path) -> bool:
    """Whether git would store anything from an investigation folder.

    Its `data/` and the folders `.gitignore` names stay local, so a folder holding only those (left
    behind when its branch was checked out here) is not an investigation on this branch."""
    for dirpath, dirnames, filenames in os.walk(folder):
        local = _LOCAL_DIRS | ({"data"} if Path(dirpath) == folder else set())
        dirnames[:] = [d for d in dirnames if d not in local]
        if filenames:
            return True
    return False


# Longest knowledge filename stem (characters); longer claims belong in `claim`, not the name (C-10).
MAX_KNOWLEDGE_NAME = 80
_LONG_NAME_FIX = (f"shorten the filename to at most {MAX_KNOWLEDGE_NAME} characters (keep the full sentence "
                  "in `claim`) and update links")


def rule_names(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 1: filenames and research folder names; research/ holds only README.md and <id>/."""
    problems = []
    for kind in ("literature", "knowledge"):
        for domain in _visible(root / kind, root):
            for p in _visible(domain, root) if domain.is_dir() else []:
                if p.is_file() and p.suffix == ".md" and p.name != "README.md":
                    if not NAME_PATTERNS[kind].fullmatch(p.name):
                        problems.append(Problem(p.relative_to(root).as_posix(), 1,
                                                f"invalid name: {_NAME_FIX[kind]}"))
                    elif kind == "knowledge" and (word := instruction_word(p.stem)):
                        problems.append(Problem(p.relative_to(root).as_posix(), 1,
                                                f'knowledge name reads as an instruction ("{word}-..."): '
                                                f"{_INSTRUCTION_FIX}"))
                    elif kind == "knowledge" and len(p.stem) > MAX_KNOWLEDGE_NAME:
                        problems.append(Problem(p.relative_to(root).as_posix(), 1,
                                                f"knowledge name too long ({len(p.stem)} characters): "
                                                f"{_LONG_NAME_FIX}"))
    for p in _visible(root / "research", root):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            if not NAME_PATTERNS["research"].fullmatch(p.name):
                problems.append(Problem(rel, 1, f"invalid name: {_NAME_FIX['research']}"))
            if not (p / "README.md").is_file() and _has_committable_file(p):
                problems.append(Problem(rel, 1, f"missing readme: create {rel}/README.md "
                                                "by copying templates/research.md and filling it"))
        elif p.name != "README.md":
            problems.append(Problem(rel, 1, "not allowed here: research/ holds only README.md and "
                                            "<id>/ folders; move the file into a research folder"))
    return problems


def rule_flat(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 7: literature/ and knowledge/ hold README.md and domain folders; those hold only .md files."""
    problems = []
    domains = set(root_topics(topics)) if topics is not None else None
    for kind in ("literature", "knowledge"):
        for p in _visible(root / kind, root):
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                if domains is not None and p.name not in domains:
                    problems.append(Problem(rel, 1, f"not allowed here: {kind}/ holds only README.md "
                                                    "and folders named after root topics of "
                                                    "topics.yaml; rename or remove it"))
                for q in _visible(p, root):
                    if q.is_dir() or q.suffix != ".md":
                        problems.append(Problem(q.relative_to(root).as_posix(), 1,
                                                f"not allowed here: {kind}/{p.name}/ holds only .md "
                                                "notes; move or remove it"))
            elif p.name != "README.md":
                problems.append(Problem(rel, 1, f"not allowed here: {kind}/ holds only README.md and "
                                                f"domain folders; move the file into {kind}/<domain>/"))
    return problems


def rule_domain(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 8: a literature or knowledge note lives under the root of at least one of its topics."""
    if topics is None:
        return []
    problems = []
    for note in notes:
        listed = note.meta.get("topics") if isinstance(note.meta, dict) else None
        if note.type == "research" or not isinstance(listed, list):
            continue
        domains = set(root_topics(topics))
        roots = list(dict.fromkeys(root_of(topics, t) for t in listed if isinstance(t, str) and t in topics))
        roots = [r for r in roots if r in domains]
        if roots and note.path.parent.name not in roots:
            fix = " or ".join(f"{note.type}/{r}/" for r in roots)
            problems.append(Problem(note.rel, key_line(note.text, "topics"), f"wrong domain: move to {fix}"))
    return problems


def _nonempty_dir(path: Path) -> bool:
    """An empty folder does not count: git does not store it, so the staged snapshot would not see it."""
    return path.is_dir() and any(path.iterdir())


def _heading_problems(note: Note) -> list[Problem]:
    lines = [ln.rstrip() for ln in note.body.split("\n")]
    pos = 0
    problems = []
    for heading in REQUIRED_HEADINGS[note.type]:
        try:
            pos = lines.index(f"## {heading}", pos) + 1
        except ValueError:
            problems.append(Problem(note.rel, note.body_line,
                                    f"missing heading '## {heading}': add it in the order of the template"))
    if (note.type == "research" and f"## {BASELINE_HEADING}" not in lines
            and any(_nonempty_dir(note.path.parent / d) for d in EXPERIMENT_DIRS)):
        problems.append(Problem(note.rel, note.body_line,
                                f"missing heading '## {BASELINE_HEADING}' (required once code/ or results/ exists, "
                                "spec 5.5): add it, naming the strongest published method that fits our constraints, "
                                "the change tested against it and the result"))
    return problems


def rule_schema(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 2: frontmatter present, closed schema, typed values, required headings."""
    problems = []
    for note in notes:
        if note.error is not None:
            problems.append(Problem(note.rel, note.error_line, f"invalid frontmatter ({note.error}): "
                                                 "fix the block at the top of the file"))
            continue
        if not isinstance(note.meta, dict):
            problems.append(Problem(note.rel, 1, "invalid frontmatter (it must be a mapping of "
                                                 "fields): rewrite it as key: value lines"))
            continue
        schema = SCHEMAS[note.type]
        for field in schema:
            if field not in note.meta and field not in OPTIONAL_FIELDS:
                problems.append(Problem(note.rel, 1, f"missing field '{field}': add it to the frontmatter"))
        for field, value in note.meta.items():
            line = key_line(note.text, str(field))
            if field not in schema:
                problems.append(Problem(note.rel, line, f"unknown field '{field}': remove it "
                                                        "(the schema is closed)"))
            elif (fix := schema[field](value)) is not None:
                problems.append(Problem(note.rel, line, f"invalid value for '{field}': {fix}"))
        problems += _heading_problems(note)
    return problems


def _starts_with_author(tokens: list[str], first: str) -> bool:
    """True when the slug's first tokens spell the author again ("ethereum-org" for "ethereumorg")."""
    return any("".join(tokens[:k]) == first for k in range(1, len(tokens) + 1))


def rule_consistency(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 3: literature year/author and research started match the file name."""
    problems = []
    for note in notes:
        if not isinstance(note.meta, dict) or note.error is not None:
            continue
        if note.type == "literature":
            name = note.path.name
            if NAME_PATTERNS["literature"].fullmatch(name):
                _, first, *rest = name.removesuffix(".md").split("-")
                if rest and _starts_with_author(rest, first):
                    problems.append(Problem(note.rel, 1, "author repeated in filename: "
                                                         f"rename to {name[:4]}-{first}-<rest>.md"))
                elif rest and rest[0] == name[:4]:
                    problems.append(Problem(note.rel, 1, "year repeated in filename: "
                                                         f"rename to {name[:4]}-{first}-<rest>.md"))
                year = note.meta.get("year")
                if isinstance(year, int) and str(year) != name[:4]:
                    problems.append(Problem(note.rel, key_line(note.text, "year"),
                                            f"year mismatch: set year to {name[:4]} or rename the file"))
                authors = note.meta.get("authors")
                if _authors(authors) is None and slugify(authors[0]) != first:
                    problems.append(Problem(note.rel, key_line(note.text, "authors"),
                                            f"author mismatch: first author must slugify to '{first}'; "
                                            "fix authors or rename the file"))
        elif note.type == "research":
            folder = note.path.parent.name
            started = note.meta.get("started")
            if NAME_PATTERNS["research"].fullmatch(folder) and isinstance(started, str) \
                    and started != folder[:7]:
                problems.append(Problem(note.rel, key_line(note.text, "started"),
                                        f'started mismatch: set started to "{folder[:7]}" or rename the folder'))
    return problems


def rule_topics_used(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 4: topics exist, are listed with every ancestor, and are not empty."""
    if topics is None:
        return []
    problems = []
    for note in notes:
        listed = note.meta.get("topics") if isinstance(note.meta, dict) else None
        if not isinstance(listed, list):
            continue
        line = key_line(note.text, "topics")
        if not listed:
            problems.append(Problem(note.rel, line, "at least one topic is required: "
                                                    "list a topic id from topics.yaml"))
        names = [t for t in listed if isinstance(t, str)]
        for t in names:
            if t not in topics:
                problems.append(Problem(note.rel, line, f"unknown topic '{t}': use an id from "
                                                        "topics.yaml or add it there"))
                continue
            for a in ancestors(topics, t):
                if a not in names:
                    problems.append(Problem(note.rel, line, f"missing ancestor '{a}' of '{t}': "
                                                            f"add '{a}' to topics"))
    return problems


def _topic_line(text: str, tid: object) -> int:
    for i, ln in enumerate(text.split("\n"), 1):
        if re.match(rf"{re.escape(str(tid))}[ \t]*:", ln):
            return i
    return 1


def rule_topics_file(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 5: topics.yaml follows 5.6."""
    if topics is None:
        return []
    text = _read_text(root / "topics.yaml")
    problems = []

    def bad(tid: object, why: str, fix: str, kind: str = "topics file entry") -> None:
        problems.append(Problem("topics.yaml", _topic_line(text, tid), f"invalid {kind} '{tid}' ({why}): {fix}"))

    for tid, entry in topics.items():
        if not isinstance(tid, str) or not _TOPIC_ID.fullmatch(tid):
            bad(tid, "not a valid id", "use lowercase words with hyphens, starting with a letter")
            continue
        if tid == RESERVED_TOPIC:
            problems.append(Problem("topics.yaml", _topic_line(text, tid),
                                    f"topic id '{tid}' is reserved (it is the fallback heading of "
                                    "domain indexes): rename it"))
            continue
        if not isinstance(entry, dict):
            bad(tid, "not a mapping", "write it as {parent: ..., description: ...} or {}")
            continue
        for key in entry:
            if key not in ("parent", "description"):
                bad(tid, f"unknown field '{key}'", "keep only parent and description")
        if "description" in entry and not isinstance(entry["description"], str):
            bad(tid, "description is not a string", "write a one-line description")
        parent = entry.get("parent")
        if "parent" in entry and not isinstance(parent, str):
            bad(tid, "parent is not a string", "set parent to an existing topic id")
        elif isinstance(parent, str) and parent not in topics:
            problems.append(Problem("topics.yaml", _topic_line(text, tid),
                                    f"unknown parent '{parent}' of '{tid}': add '{parent}' "
                                    "or point parent at an existing topic"))
    for tid in topics:
        seen, current = set(), _parent(topics, tid) if isinstance(tid, str) else None
        while isinstance(current, str) and current not in seen:
            if current == tid:
                problems.append(Problem("topics.yaml", _topic_line(text, tid),
                                        f"cycle through '{tid}': break the parent chain"))
                break
            seen.add(current)
            current = _parent(topics, current)
    return problems


def rule_placeholders(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 10: no TODO(hub): lines left in typed notes."""
    return [
        Problem(note.rel, i, "placeholder left from the template: replace the TODO(hub): text")
        for note in notes
        for i, line in enumerate(note.text.split("\n"), 1)
        if line.startswith("TODO(hub):")
    ]


def rule_index_fresh(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 9: generated index blocks are current."""
    if topics is None:
        return []
    problems = []
    for path, block, default in index_targets(root, notes, topics):
        rel = path.relative_to(root).as_posix()
        if not path.is_file():
            if default is not None:
                problems.append(Problem(rel, 1, "missing readme: run mem index"))
            continue
        try:
            text = _read_text(path)
        except FrontmatterError as exc:
            problems.append(Problem(rel, 1, f"unreadable index README ({exc}): save it as UTF-8 text"))
            continue
        try:
            current = _with_index(text, block) == text
        except FrontmatterError as exc:
            start = text.find(INDEX_START)
            problems.append(Problem(rel, text.count("\n", 0, start) + 1 if start >= 0 else 1, str(exc)))
            continue
        if not current:
            start = text.find(INDEX_START)
            line = text.count("\n", 0, start) + 1 if start >= 0 else 1
            problems.append(Problem(rel, line, "index stale: run mem index"))
    return problems


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
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and line.strip() == m.group(1):
                fence = None
            flags.append(True)
    return flags


def _strip_code(text: str) -> str:
    """Blank out fenced blocks and inline code spans, keeping line numbers."""
    lines = text.split("\n")
    kept = ["" if fenced else line for line, fenced in zip(lines, _in_fence(lines))]
    return _CODE_SPAN.sub(_blank, "\n".join(kept))


def _markdown_files(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).parts
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".")
            and not (len(rel) == 2 and rel[0] == "research" and d == "code")
            and not (rel == ("tools", "tests") and d == "fixtures")
        )
        found += [Path(dirpath) / f for f in sorted(filenames)
                  if f.endswith(".md") and not f.startswith(".")]
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
            text = _read_text(path)
        except FrontmatterError:
            continue
        rel = path.relative_to(root).as_posix()
        for lineno, target, file_part in _relative_links(text):
            try:
                exists = (path.parent / file_part).exists()
            except (OSError, ValueError):
                exists = False
            if not exists:
                problems.append(Problem(rel, lineno, f"broken link {target}: "
                                                     "fix the path or remove the link"))
    return problems


def _is_index_readme(rel: str) -> bool:
    parts = rel.split("/")
    return parts[-1] == "README.md" and (
        (len(parts) == 2 and parts[0] in INDEX_FOLDERS)
        or (len(parts) == 3 and parts[0] in ("literature", "knowledge")))


def orphan_notes(root: Path) -> list[str]:
    """Typed notes no other Markdown file links to, not counting the generated index READMEs; sorted."""
    linked: set[tuple[str, ...]] = set()
    for path in _markdown_files(root):
        rel = path.relative_to(root).as_posix()
        if _is_index_readme(rel):
            continue
        try:
            text = _read_text(path)
        except FrontmatterError:
            continue
        for _, _, file_part in _relative_links(text):
            target = os.path.normpath(path.parent / file_part)
            if Path(target).is_dir():
                target = os.path.join(target, "README.md")
            if target != os.path.normpath(path):
                linked.add(target)
    return sorted(n.rel for n in discover_notes(root) if os.path.normpath(root / n.rel) not in linked)


# --- requirements --------------------------------------------------------------

_REQUIREMENTS = "docs/requirements.md"
_INTENT_ID = re.compile(r"I-[0-9]+")
_CONCRETE_ID = re.compile(r"C-[0-9]+")
_BACKTICKS = re.compile(r"`+")


def _split_cells(line: str) -> list[str]:
    """Cells of a table row, split on '|' outside inline code spans (a literal '|' in a cell is unsupported)."""
    line = line.strip().removeprefix("|").removesuffix("|")
    cells, start, i = [], 0, 0
    while i < len(line):
        if line[i] == "`":
            run = _BACKTICKS.match(line, i).group()
            close = line.find(run, i + len(run))
            i = close + len(run) if close != -1 else i + len(run)
        elif line[i] == "|":
            cells.append(line[start:i].strip())
            start = i = i + 1
        else:
            i += 1
    cells.append(line[start:].strip())
    return cells


def _requirement_rows(root: Path) -> list[tuple[int, list[str]]] | None:
    """(line, cells) of the table rows whose first cell is an I-n or C-n id; None when the file is absent."""
    path = root / _REQUIREMENTS
    if not path.is_file():
        return None
    try:
        text = _read_text(path)
    except FrontmatterError:
        return None
    rows = []
    for number, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("|"):
            cells = _split_cells(line)
            if _INTENT_ID.fullmatch(cells[0]) or _CONCRETE_ID.fullmatch(cells[0]):
                rows.append((number, cells))
    return rows


def _iso_date(value: str) -> datetime.date | None:
    if not _DATE.fullmatch(value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def rule_requirements(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 12: docs/requirements.md rows are well formed (checked only when the file exists)."""
    rows = _requirement_rows(root)
    if not rows:
        return []
    problems = []
    seen: set[str] = set()
    intents = {cells[0] for _, cells in rows if _INTENT_ID.fullmatch(cells[0])}
    for number, cells in rows:
        ident = cells[0]
        if ident in seen:
            problems.append(Problem(_REQUIREMENTS, number, f"duplicate id {ident}: give each requirement a unique id"))
        seen.add(ident)
        if not _CONCRETE_ID.fullmatch(ident):
            continue
        if len(cells) != 6:
            problems.append(Problem(_REQUIREMENTS, number, f"{ident} has {len(cells)} cells: use exactly 6 "
                                    "(ID, Requirement, Serves, Rests on, Revisit when, Review by)"))
            continue
        if _iso_date(cells[5]) is None:
            problems.append(Problem(_REQUIREMENTS, number, f"{ident} has an invalid 'Review by' date "
                                    f"'{cells[5]}': use a real date as YYYY-MM-DD"))
        served = [c.strip() for c in cells[2].split(",")]
        unknown = [c for c in served if c not in intents]
        if unknown:
            problems.append(Problem(_REQUIREMENTS, number, f"{ident} serves unknown intent "
                                    f"{', '.join(repr(u) for u in unknown)}: list existing I-ids, comma-separated"))
    return problems


# Model-specific advice ages; see docs/requirements.md C-13.
MODEL_SPECIFIC_ROOT = "llm"
# Days after `updated` before such a note is listed for re-testing; see docs/requirements.md C-13.
RETEST_DAYS = 365
# Days after `added` (the date the source was last read) before a vendor web page is listed for re-reading;
# see docs/requirements.md C-15.
REREAD_DAYS = 182


def due_retests(root: Path, today: datetime.date) -> list[str]:
    """Lines for knowledge notes on llm topics not updated within RETEST_DAYS, sorted by path."""
    try:
        topics = load_topics(root)
    except FrontmatterError:  # `check` reports an unusable topics.yaml
        return []
    if MODEL_SPECIFIC_ROOT not in topics:
        return []
    scope = descendants(topics, MODEL_SPECIFIC_ROOT)
    # Only notes homed in llm's domain: a math note tagged llm-evaluation states statistics, not model behaviour.
    home = f"knowledge/{root_of(topics, MODEL_SPECIFIC_ROOT)}/"
    lines = []
    for note in discover_notes(root):
        if (note.type != "knowledge" or note.error is not None or not isinstance(note.meta, dict)
                or not note.rel.startswith(home)):
            continue
        listed = note.meta.get("topics")
        updated = _iso_date(note.meta["updated"]) if isinstance(note.meta.get("updated"), str) else None
        if (updated is None or not isinstance(listed, list)
                or not scope.intersection(t for t in listed if isinstance(t, str))):
            continue
        if (today - updated).days > RETEST_DAYS:
            lines.append(f"{note.rel}:1: re-test: updated {updated}; "
                         "advice that depends on model behaviour ages (spec 5.4)")
    return lines


def due_rereads(root: Path, today: datetime.date) -> list[str]:
    """Lines for llm web literature notes whose `added` is over REREAD_DAYS old, sorted by path."""
    try:
        topics = load_topics(root)
    except FrontmatterError:  # `check` reports an unusable topics.yaml
        return []
    if MODEL_SPECIFIC_ROOT not in topics:
        return []
    scope = descendants(topics, MODEL_SPECIFIC_ROOT)
    home = f"literature/{root_of(topics, MODEL_SPECIFIC_ROOT)}/"
    lines = []
    for note in discover_notes(root):
        if (note.type != "literature" or note.error is not None or not isinstance(note.meta, dict)
                or not note.rel.startswith(home) or note.meta.get("kind") != "web"):
            continue
        listed = note.meta.get("topics")
        added = _iso_date(note.meta["added"]) if isinstance(note.meta.get("added"), str) else None
        if (added is None or not isinstance(listed, list)
                or not scope.intersection(t for t in listed if isinstance(t, str))):
            continue
        if (today - added).days > REREAD_DAYS:
            lines.append(f"{note.rel}:1: re-read: added {added}; vendor documentation changes (spec 5.3)")
    return lines


def due_requirements(root: Path, today: datetime.date) -> list[str]:
    """One line per concrete requirement whose 'Review by' date is today or earlier, in file order."""
    lines = []
    for number, cells in _requirement_rows(root) or []:
        if _CONCRETE_ID.fullmatch(cells[0]) and len(cells) == 6 and (due := _iso_date(cells[5])) and due <= today:
            lines.append(f"{_REQUIREMENTS}:{number}: {cells[0]} due for review since {due}: {cells[1]}")
    return lines


MAX_FILE_BYTES = 5 * 1024 * 1024
_UNTRACKED_DIRS = frozenset({"__pycache__", ".venv", "target", "node_modules"})  # .gitignore entries; hidden ones (.sources/) are skipped as hidden
_LOCAL_DIRS = _UNTRACKED_DIRS | {".pytest_cache", ".sources", ".playwright-mcp"}  # every folder name .gitignore keeps out of git


def rule_file_size(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 13: no file over 5 MB (sizes only; contents are never read)."""
    problems = []
    for dirpath, dirnames, filenames in os.walk(root):
        local_data = {"data"} if Path(dirpath).parent == root / "research" else set()  # research/*/data/ never reaches git
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in _UNTRACKED_DIRS and d not in local_data)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name.startswith("."):
                continue
            try:  # lstat: git stores a symlink, not its target; a broken or vanished file is not an error
                size = path.lstat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                problems.append(Problem(path.relative_to(root).as_posix(), 1,
                                        "file over 5 MB: keep it out of git and link it by https:// URL (spec 5.1)"))
    return problems


def rule_handles(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 14: no two typed notes share a handle (`_handle`), so a handle names one note."""
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for note in notes:
        groups[_handle(note.rel)].append(note.rel)
    return [Problem(rel, 1, f'handle "{h}" is also used by {", ".join(r for r in rels if r != rel)}: '
                            "rename one so a handle names one note")
            for h, rels in groups.items() if len(rels) > 1 for rel in rels]


def rule_syntheses(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 15: each synthesis parses, repeats no section handle, uses known topics and ends every part with a
    valid `Sources:` line; a reference names a source and has a sentence before it, and no reference or source
    names a superseded note."""
    problems = []
    loaded = syntheses.load(root / syntheses.SYNTHESES_DIR)
    superseded = {(root / n.rel).resolve(): n.meta["superseded_by"] for n in notes
                  if n.error is None and isinstance(n.meta, dict) and isinstance(n.meta.get("superseded_by"), str)}
    for note in notes:
        part = note.meta.get("part_of") if note.error is None and isinstance(note.meta, dict) else None
        if isinstance(part, str) and _PART_OF.fullmatch(part):
            handle, _, section = part.partition("#")
            syn = next((x for x in loaded if x.handle == handle and x.error is None), None)
            if syn is None:
                problems.append(Problem(note.rel, key_line(note.text, "part_of"),
                                        f"part_of names s:{handle}, which does not exist: fix or remove part_of"))
            elif not any(sec.handle == section for sec in syn.sections):
                problems.append(Problem(note.rel, key_line(note.text, "part_of"),
                                        f"part_of names the section {section} of s:{handle}, which does not exist: "
                                        "fix or remove part_of"))
    for syn in loaded:
        rel = syn.path.relative_to(root).as_posix()
        if syn.error:
            problems.append(Problem(rel, 1, f"synthesis cannot be parsed ({syn.error}): fix the frontmatter "
                                            "and start the body with `## Summary`"))
            continue
        for t in syn.topics:
            if topics is not None and t not in topics:
                problems.append(Problem(rel, 1, f"unknown topic '{t}': use an id from topics.yaml or add it there"))
        seen: set[str] = set()
        for sec in syn.sections:
            if sec.handle in seen:
                problems.append(Problem(rel, sec.line, f'repeated section handle "{sec.handle}": '
                                                       "rename one heading"))
            seen.add(sec.handle)
            if sec.handle != syntheses.SUMMARY:
                msgs = syntheses.validate_section(sec.text, root)
                base = (root / syntheses.SYNTHESES_DIR).resolve()
                cited = [("reference", t) for t in dict.fromkeys(syntheses.references(sec.text))]
                cited += [("source", t) for t in sec.sources]
                for kind, target in cited:
                    successor = superseded.get(syntheses._resolved(base, target))
                    if successor:
                        msgs.append(f"{kind} {target} is superseded by {successor}: point to it")
            else:
                msgs = syntheses.summary_problems(sec.text)
            for msg in msgs:
                problems.append(Problem(rel, sec.line, f'section "{sec.heading}": {msg}'))
    return problems


def rule_supersession(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 16: `superseded_by` and `distinct_from` name notes that exist."""
    handles = {_handle(n.rel) for n in notes}
    problems = []
    for note in notes:
        if note.error is not None or not isinstance(note.meta, dict):
            continue
        named = [("superseded_by", note.meta.get("superseded_by"))]
        named += [("distinct_from", h) for h in (note.meta.get("distinct_from") or []) if isinstance(h, str)] \
            if isinstance(note.meta.get("distinct_from"), list) else []
        for field, value in named:
            if isinstance(value, str) and value not in handles:
                problems.append(Problem(note.rel, key_line(note.text, field),
                                        f"{field} names {value}, which is not a note: fix or remove {field}"))
    return problems


RULES = [rule_names, rule_flat, rule_domain, rule_schema, rule_consistency, rule_topics_used,
         rule_topics_file, rule_links, rule_index_fresh, rule_placeholders, rule_requirements, rule_file_size, rule_handles,
         rule_syntheses, rule_supersession]


def check(root: Path) -> list[Problem]:
    problems: list[Problem] = []
    try:
        topics: dict | None = load_topics(root)
    except FrontmatterError as exc:
        topics = None
        problems.append(Problem("topics.yaml", exc.line, f"topics file unusable ({exc}): "
                                                  "restore topics.yaml as a mapping of topic ids"))
    notes = discover_notes(root)
    for rule in RULES:
        problems += rule(root, notes, topics)
    return sorted(set(problems))


def invalid_changed(store: Path) -> Callable[[list[str]], list[str]]:
    """A validator for `store_git.commit_if_changed`: runs `check` once, on the working tree, and returns the given
    paths that have a problem. The working tree is checked, not the committed snapshot: a committed note may link to a
    held-back one."""
    def validate(paths: list[str]) -> list[str]:
        bad = {p.path for p in check(store)}
        return [p for p in paths if p in bad]
    return validate
