#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Memory engine: parsing primitives and the mem commands."""

from __future__ import annotations

import argparse
import collections
import datetime
import html.parser
import http.client
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, NamedTuple, Sequence

import yaml

import records

_WRITE_COMMANDS = ("new", "rename", "index", "fetch-sources")
_NO_STORE_NEEDED = ("remember", "observe", "confirm", "refute", "supersede", "merge", "forget", "promote",
                    "memories", "curate", "session-index", "signal")


def _env_value(env: Mapping[str, str], key: str) -> str:
    return env.get(key) or ""


def _config_file(env: Mapping[str, str]) -> Path | None:
    base = _env_value(env, "XDG_CONFIG_HOME")
    if not base:
        home = _env_value(env, "HOME")
        if not home:
            return None
        base = str(Path(home) / ".config")
    return Path(base) / "agent-memory" / "store"


def _config_store(env: Mapping[str, str]) -> str:
    path = _config_file(env)
    if path is None:
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    return lines[0].strip() if lines else ""


def store_source(cli_root: str | None, env: Mapping[str, str]) -> str | None:
    """Where the store path comes from: --root, MEM_STORE or the config file."""
    if cli_root:
        return "--root"
    if _env_value(env, "MEM_STORE"):
        return "MEM_STORE"
    if _config_store(env):
        return "config file"
    return None


def resolve_root(cli_root: str | None, env: Mapping[str, str]) -> Path | None:
    """The store folder by precedence --root, MEM_STORE, config file; not checked for existence."""
    source = store_source(cli_root, env)
    if source is None:
        return None
    raw = {"--root": cli_root, "MEM_STORE": env.get("MEM_STORE")}.get(source) or _config_store(env)
    return Path(raw).expanduser()


def data_dir(env: Mapping[str, str]) -> Path | None:
    """Folder for the usage log and other state, outside the store; None when no variable locates it."""
    if _env_value(env, "MEM_DATA"):
        return Path(env["MEM_DATA"])
    state = _env_value(env, "XDG_STATE_HOME")
    if state:
        return Path(state) / "agent-memory"
    home = _env_value(env, "HOME")
    return Path(home) / ".local" / "state" / "agent-memory" if home else None

_DROPPED_TAGS = {"tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool"}


# The C parser is several times faster; searching reads every note.
_BaseLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class HubLoader(_BaseLoader):
    """SafeLoader that keeps dates and on/off/yes/no as strings."""


# Copy, never mutate: SafeLoader's table is shared with every other user of PyYAML.
HubLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag not in _DROPPED_TAGS]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _no_duplicate_keys(loader: HubLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in seen
            seen.add(key)
        except TypeError:  # unhashable key: the default constructor reports it
            continue
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark)
    return yaml.constructor.SafeConstructor.construct_mapping(loader, node, deep=deep)


HubLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=HubLoader)


class FrontmatterError(Exception):
    def __init__(self, message: str, line: int = 1) -> None:
        super().__init__(message)
        self.line = line


def _yaml_problem(exc: yaml.YAMLError, first_line: int) -> tuple[str, int]:
    """One-line description and file line of a YAML error; first_line is where the YAML text starts."""
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    return problem, (mark.line + first_line if mark is not None else first_line)


def _read_text(path: Path) -> str:
    """UTF-8 text without BOM and with LF newlines; FrontmatterError when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise FrontmatterError("file is not valid UTF-8") from exc
    except OSError as exc:
        raise FrontmatterError(f"file cannot be read ({exc.strerror or exc})") from exc
    return text.removeprefix("\ufeff").replace("\r\n", "\n")


def split_frontmatter(text: str) -> tuple[Any, str, int]:
    """Return (data, body, 1-based line where the body starts)."""
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise FrontmatterError("missing frontmatter block (file must start with '---')")
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i] == "---":
            try:
                data = load_yaml("\n".join(lines[1:i]))
            except yaml.YAMLError as exc:
                problem, line = _yaml_problem(exc, 2)
                raise FrontmatterError(f"invalid YAML in frontmatter: {problem}", line) from exc
            return data, "\n".join(lines[i + 1 :]), i + 2
    raise FrontmatterError("frontmatter block is not closed with '---'")


@dataclass
class Note:
    type: str
    path: Path
    rel: str
    meta: Any
    body: str
    body_line: int
    text: str
    error: str | None
    error_line: int = 1


def _is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _read_note(note_type: str, path: Path, root: Path) -> Note:
    rel = path.relative_to(root).as_posix()
    try:
        text = _read_text(path)
    except FrontmatterError as exc:
        return Note(note_type, path, rel, None, "", 1, "", str(exc))
    try:
        meta, body, body_line = split_frontmatter(text)
        return Note(note_type, path, rel, meta, body, body_line, text, None)
    except FrontmatterError as exc:
        return Note(note_type, path, rel, None, text, 1, text, str(exc), exc.line)


def _note_files(root: Path) -> list[tuple[str, Path]]:
    """(type, path) of the typed notes: literature/*/*.md and knowledge/*/*.md (not README.md), research/*/README.md."""
    found = [(kind, path) for kind in ("literature", "knowledge") for path in (root / kind).glob("*/*.md")
             if path.name != "README.md"]
    found += [("research", path) for path in (root / "research").glob("*/README.md")]
    return [(kind, path) for kind, path in found if path.is_file() and not _is_hidden(path, root)]


def discover_notes(root: Path) -> list[Note]:
    """Typed notes (see `_note_files`), sorted by path."""
    return sorted((_read_note(kind, path, root) for kind, path in _note_files(root)), key=lambda n: n.rel)


def load_topics(root: Path) -> dict[str, dict]:
    path = root / "topics.yaml"
    if not path.is_file():
        raise FrontmatterError("topics.yaml is missing")
    try:
        data = load_yaml(_read_text(path))
    except yaml.YAMLError as exc:
        problem, line = _yaml_problem(exc, 1)
        raise FrontmatterError(f"invalid YAML in topics.yaml: {problem}", line) from exc
    if not isinstance(data, dict):
        raise FrontmatterError("topics.yaml must be a mapping of topic ids")
    return data


def _parent(topics: dict, tid: str) -> str | None:
    entry = topics.get(tid)
    parent = entry.get("parent") if isinstance(entry, dict) else None
    return parent if isinstance(parent, str) else None


def ancestors(topics: dict, tid: str) -> list[str]:
    """Known parents of tid, nearest first; an unknown or non-string parent and a cycle end the walk and are not included."""
    result: list[str] = []
    seen = {tid}
    current = _parent(topics, tid)
    while current is not None and current in topics and current not in seen:
        result.append(current)
        seen.add(current)
        current = _parent(topics, current)
    return result


def descendants(topics: dict, tid: str) -> set[str]:
    """tid plus every topic that has it as an ancestor."""
    return {tid} | {t for t in topics if tid in ancestors(topics, t)}


def root_topics(topics: dict) -> list[str]:
    """Topic ids with no parent: the domains."""
    return [t for t, e in topics.items() if isinstance(t, str) and isinstance(e, dict) and "parent" not in e]


def root_of(topics: dict, tid: str) -> str:
    """The domain of a known topic: its last ancestor, or itself when it has no parent."""
    return (ancestors(topics, tid) or [tid])[-1]


def leaf_topics(topics: dict, listed: list[str]) -> list[str]:
    return [
        t for t in listed
        if not any(o != t and t in ancestors(topics, o) for o in listed)
    ]


def slugify(s: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def key_line(text: str, key: str) -> int:
    """1-based line of a top-level `key:` inside the frontmatter, else 1."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return 1
    for i in range(1, len(lines)):
        if lines[i] == "---":
            break
        if re.match(rf"{re.escape(key)}[ \t]*:", lines[i]):
            return i + 1
    return 1


# --- index -------------------------------------------------------------------


INDEX_START = "<!-- hub:index:start -->"
INDEX_END = "<!-- hub:index:end -->"
INDEX_FOLDERS = ("literature", "knowledge", "research")

_INDEX_COLUMNS = {
    "literature": ("Year", "Title", "Kind", "Level", "Topics"),
    "knowledge": ("Claim", "Confidence", "Level", "Topics"),
    "research": ("Started", "Title", "Status", "Topics"),
}


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _index_row(note: Note, topics: dict) -> tuple[tuple, list[str]]:
    meta = note.meta
    listed = meta.get("topics")
    leaves = leaf_topics(topics, [t for t in listed if isinstance(t, str)]) \
        if isinstance(listed, list) else []
    topic_cell = _cell(", ".join(sorted(leaves)))
    if note.type == "literature":
        name = note.path.name
        link = f"[{_cell(meta.get('title', name))}]({name})"
        year = meta.get("year")
        key = (-year if isinstance(year, int) else 0, name)
        return key, [_cell(year if year is not None else ""), link, _cell(meta.get("kind", "")),
                          _cell(meta.get("level", "")), topic_cell]
    if note.type == "knowledge":
        name = note.path.name
        link = f"[{_cell(meta.get('claim', name))}]({name})"
        return (name,), [link, _cell(meta.get("confidence", "")), _cell(meta.get("level", "")), topic_cell]
    folder = note.path.parent.name
    link = f"[{_cell(meta.get('title', folder))}]({folder}/README.md)"
    started = str(meta.get("started", ""))
    return (started, folder), [_cell(started), link, _cell(meta.get("status", "")), topic_cell]


def _rows_table(folder: str, rows: list[tuple[tuple, list[str]]]) -> list[str]:
    if folder == "research":
        # started descending, then id ascending
        rows.sort(key=lambda r: r[0][1])
        rows.sort(key=lambda r: r[0][0], reverse=True)
    else:
        rows.sort(key=lambda r: r[0])
    cols = _INDEX_COLUMNS[folder]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    return lines + ["| " + " | ".join(cells) + " |" for _, cells in rows]


def _indexable(notes: list[Note], folder: str) -> list[Note]:
    return [n for n in notes if n.type == folder and n.error is None and isinstance(n.meta, dict)]


def _domain_notes(notes: list[Note], folder: str, domain: str) -> list[Note]:
    return [n for n in _indexable(notes, folder) if n.path.parent.name == domain]


def _subtopics(note: Note, domain: str, topics: dict) -> list[str]:
    """Headings of a note in its domain README: each most-specific topic under the domain, else `general`."""
    listed = note.meta.get("topics")
    leaves = leaf_topics(topics, [t for t in listed if isinstance(t, str) and t in topics]) \
        if isinstance(listed, list) else []
    found = sorted(t for t in leaves if t != domain and root_of(topics, t) == domain)
    return found or ["general"]


def render_index(root: Path, folder: str, notes: list[Note], topics: dict) -> str:
    """Block content between the markers of research/ or of a top-level literature/knowledge README."""
    if folder == "research":
        rows = [_index_row(n, topics) for n in _indexable(notes, folder)]
        return "\n" + "\n".join(_rows_table(folder, rows)) + "\n" if rows else "\n_No entries yet._\n"
    counts = {d: len(_domain_notes(notes, folder, d)) for d in sorted(root_topics(topics))}
    counts = {d: c for d, c in counts.items() if c}
    if not counts:
        return "\n_No entries yet._\n"
    lines = ["| Domain | Notes |", "| --- | --- |"]
    lines += [f"| [{d}]({d}/README.md) | {c} |" for d, c in counts.items()]
    return "\n" + "\n".join(lines) + "\n"


def render_domain_index(folder: str, domain: str, notes: list[Note], topics: dict) -> str:
    """Block content of <folder>/<domain>/README.md: one table per subtopic, `general` last."""
    groups: dict[str, list[tuple[tuple, list[str]]]] = {}
    for n in _domain_notes(notes, folder, domain):
        for heading in _subtopics(n, domain, topics):
            groups.setdefault(heading, []).append(_index_row(n, topics))
    if not groups:
        return "\n_No entries yet._\n"
    out: list[str] = []
    for name in sorted(groups, key=lambda g: (g == "general", g)):
        out += ["", f"### {name}", ""] + _rows_table(folder, groups[name])
    return "\n".join(out) + "\n"


def _with_index(text: str, block: str) -> str:
    """Replace the block between the markers, or append one when there are no markers at all."""
    starts, ends = text.count(INDEX_START), text.count(INDEX_END)
    start, end = text.find(INDEX_START), text.find(INDEX_END)
    if (starts, ends) != (0, 0) and not (starts == ends == 1 and start < end):
        raise FrontmatterError("index markers must be exactly one start marker followed by one "
                               "end marker: remove the stray or duplicated markers")
    if starts:
        return text[: start + len(INDEX_START)] + block + text[end:]
    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + INDEX_START + block + INDEX_END + "\n"


_DOMAIN_PURPOSE = {
    "literature": "Our readings of external sources about {domain}.",
    "knowledge": "Reusable conclusions about {domain}.",
}


class IndexTarget(NamedTuple):
    path: Path
    block: str
    default: str | None  # initial text when the README is missing; None: do not create it


def index_targets(root: Path, notes: list[Note], topics: dict) -> list[IndexTarget]:
    """Every README that carries a generated block."""
    targets = []
    for folder in INDEX_FOLDERS:
        targets.append(IndexTarget(root / folder / "README.md",
                                   render_index(root, folder, notes, topics), None))
        if folder == "research":
            continue
        for domain in sorted(root_topics(topics)):
            readme = root / folder / domain / "README.md"
            if readme.is_file() and not _domain_notes(notes, folder, domain):
                targets.append(IndexTarget(readme, render_domain_index(folder, domain, notes, topics), None))
            elif _domain_notes(notes, folder, domain):
                default = f"# {folder.capitalize()}: {domain}\n\n" \
                          f"{_DOMAIN_PURPOSE[folder].format(domain=domain)}\n"
                targets.append(IndexTarget(root / folder / domain / "README.md",
                                           render_domain_index(folder, domain, notes, topics), default))
    return targets


def apply_index(root: Path) -> list[str]:
    """Rewrite every index block; return the hub-relative paths that changed."""
    topics = load_topics(root)
    notes = discover_notes(root)
    pending: list[tuple[Path, str]] = []
    for path, block, default in index_targets(root, notes, topics):
        if not path.is_file():
            if default is None:
                continue
            text = default
            new = _with_index(text, block)
            pending.append((path, new))
            continue
        try:
            text = _read_text(path)
            new = _with_index(text, block)
        except FrontmatterError as exc:
            raise FrontmatterError(f"{path.relative_to(root).as_posix()}: {exc}") from exc
        if new != text:
            pending.append((path, new))
    for path, new in pending:  # write only after every README was accepted
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return [path.relative_to(root).as_posix() for path, _ in pending]


# --- check -------------------------------------------------------------------


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


LEVELS = ("basic", "beginner", "intermediate", "advanced", "expert", "niche")
# Fields a note may omit. Empty since 2026-11-07: `level` became required once every note had one (ADR 0004).
OPTIONAL_FIELDS: frozenset[str] = frozenset()

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
    },
    "knowledge": {
        "claim": _string,
        "topics": _topics,
        "confidence": _enum("high", "medium", "low"),
        "level": _enum(*LEVELS),
        "origin": _enum("literature", "research", "experience"),
        "updated": _date,
    },
    "research": {
        "title": _string,
        "question": _string,
        "status": _enum("idea", "active", "paused", "done", "abandoned"),
        "started": _month,
        "topics": _topics,
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
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")


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


def _relative_links(text: str) -> Iterator[tuple[int, str, str]]:
    """(line, target, decoded file part) of each relative link outside code; anchors and URLs are skipped."""
    for lineno, line in enumerate(_strip_code(text).split("\n"), 1):
        for m in _LINK.finditer(line):
            target = m.group(1) if m.group(1) is not None else m.group(2)
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


RULES = [rule_names, rule_flat, rule_domain, rule_schema, rule_consistency, rule_topics_used,
         rule_topics_file, rule_links, rule_index_fresh, rule_placeholders, rule_requirements, rule_file_size, rule_handles]


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


# --- find and new --------------------------------------------------------------


_FIND_ONLY_TYPE = {"kind": "literature", "status": "research", "confidence": "knowledge"}
_FIND_TYPES = {"level": ("literature", "knowledge")}


def _unknown_topic_message(topic: str, known: dict) -> str:
    """Say what to try instead: ids sharing a word with the guess, and free-text search."""
    words = set(topic.lower().split("-"))
    close = sorted(t for t in known if words & set(t.split("-")) or topic.lower() in t)
    hint = f"close ids: {', '.join(close)}; " if close else ""
    return f"unknown topic {topic}: {hint}for free text use: mem search \"{topic.replace('-', ' ')}\" (ids: topics.yaml)"


def _matching_notes(root: Path, *, type: str | None = None, topic: str | None = None,
                    kind: str | None = None, status: str | None = None,
                    confidence: str | None = None, level: str | None = None) -> list[Note]:
    """Parsable typed notes matching every filter; unparsable ones are skipped with a warning."""
    wanted = {"kind": kind, "status": status, "confidence": confidence, "level": level}
    types = {type} if type else set(INDEX_FOLDERS)
    for key, value in wanted.items():
        if value is not None:
            types &= set(_FIND_TYPES[key]) if key in _FIND_TYPES else {_FIND_ONLY_TYPE[key]}
    known = load_topics(root)
    if topic and topic not in known:
        raise FrontmatterError(_unknown_topic_message(topic, known))
    scope = descendants(known, topic) if topic else None
    result = []
    for note in discover_notes(root):
        if note.error is not None or not isinstance(note.meta, dict):
            print(f"mem: skipping {note.rel}: {note.error or 'frontmatter is not a mapping'}",
                  file=sys.stderr)
            continue
        meta = note.meta
        if note.type not in types:
            continue
        if any(v is not None and meta.get(k) != v for k, v in wanted.items()):
            continue
        if scope is not None:
            listed = meta.get("topics")
            if not isinstance(listed, list) or not scope.intersection(t for t in listed if isinstance(t, str)):
                continue
        result.append(note)
    return result


def _title(note: Note) -> str:
    return str(note.meta.get("claim" if note.type == "knowledge" else "title", ""))


def find(root: Path, **filters: str | None) -> list[tuple[str, str]]:
    """(rel, title) of notes matching every filter; claim is the title of knowledge notes."""
    return sorted((n.rel, _title(n)) for n in _matching_notes(root, **filters))


# --- search --------------------------------------------------------------------

# BM25F (Robertson, Zaragoza and Taylor 2004): each field is length-normalized on its own, the weighted
# term frequencies are summed, and saturation is applied once. Parameters were tuned on docs/search-eval.md
# and held on both held-out halves of it (ADR 0007); retune only the same way.
BM25_K1 = 2.0
RECALL_TRIGGER = 0.8  # below these, revisit the search design (C-6 in docs/requirements.md)
MRR_TRIGGER = 0.6
FIELD_WEIGHTS = {"title": 8.0, "body": 1.0}
FIELD_B = {"title": 0.3, "body": 0.75}
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase [a-z0-9]+ tokens after NFKD with combining marks removed (García -> garcia)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return _TOKEN.findall("".join(c for c in decomposed if not unicodedata.combining(c)).lower())


def _fields(note: Note) -> dict[str, str]:
    """Searchable text per field: the title (`claim` for knowledge notes), and the body with topics and authors."""
    meta = note.meta
    extra = [" ".join(str(v) for v in meta[f]) for f in ("topics", "authors") if isinstance(meta.get(f), list)]
    return {"title": _title(note), "body": "\n".join(extra + [note.body])}


@dataclass(frozen=True)
class Corpus:
    """Notes with per-field term counts and lengths, so many queries can be ranked without re-reading notes."""
    notes: list[Note]
    counts: list[dict[str, collections.Counter]]
    lengths: list[dict[str, int]]
    average: dict[str, float]


def build_corpus(root: Path, **filters: str | None) -> Corpus:
    """Read and tokenize the notes matching `filters` once."""
    notes = _matching_notes(root, **filters)
    counts = [{f: collections.Counter(tokenize(text)) for f, text in _fields(n).items()} for n in notes]
    lengths = [{f: sum(c.values()) for f, c in fields.items()} for fields in counts]
    total = len(notes)
    average = {f: sum(l[f] for l in lengths) / total if total else 0.0 for f in FIELD_WEIGHTS}
    return Corpus(notes, counts, lengths, average)


def term_idf(corpus: Corpus, terms: Iterable[str]) -> dict[str, float]:
    """BM25 IDF of each term, where a note counts when the term is in any of its fields."""
    total = len(corpus.notes)
    idf = {}
    for term in terms:
        n = sum(1 for fields in corpus.counts if any(term in c for c in fields.values()))
        idf[term] = math.log(1 + (total - n + 0.5) / (n + 0.5))
    return idf


def rank(corpus: Corpus, query: str, *, limit: int = 10) -> list[tuple[Note, float]]:
    """(note, score) of the best BM25F matches, best first, ties by `note.rel`; notes scoring 0 are omitted."""
    terms = list(dict.fromkeys(tokenize(query)))
    idf = term_idf(corpus, terms)
    scored = []
    for note, fields, length in zip(corpus.notes, corpus.counts, corpus.lengths):
        score = 0.0
        for term in terms:
            tf = sum(FIELD_WEIGHTS[f] * fields[f][term] / (1 - FIELD_B[f] + FIELD_B[f] * length[f] / corpus.average[f])
                     for f in FIELD_WEIGHTS if fields[f].get(term) and corpus.average[f])
            if tf:
                score += idf[term] * tf * (BM25_K1 + 1) / (tf + BM25_K1)
        if score > 0:
            scored.append((note, score))
    scored.sort(key=lambda r: (-r[1], r[0].rel))
    return scored[:limit]


def search(root: Path, query: str, *, limit: int = 10, **filters: str | None) -> list[tuple[str, float, str]]:
    """(rel, score, title) of the best BM25F matches, best first; notes scoring 0 are omitted."""
    return [(n.rel, score, _title(n)) for n, score in rank(build_corpus(root, **filters), query, limit=limit)]


LINK_SEEDS = LINK_EXTRA = 10


def linked_notes(root: Path, corpus: Corpus, ranked: list[tuple[Note, float]],
                 shown: int) -> list[tuple[Note, float]]:
    """Up to `LINK_EXTRA` notes of `corpus` linked to or from the first `LINK_SEEDS` printed results of `ranked` (the full
    ranking), not among its first `shown`, as (note, own score; 0 when it does not match the query).

    Order, as measured (tools/README.md): the scores of the seeds a note is linked with, summed, plus its own
    score, ties by path. Links are those `related` reads between typed notes."""
    in_corpus = {n.rel for n in corpus.notes}
    graph: dict[str, set[str]] = {rel: set() for rel in in_corpus}
    for note in corpus.notes:
        for target in _link_targets(root, note):
            if target in in_corpus and target != note.rel:
                graph[note.rel].add(target)
                graph[target].add(note.rel)
    own = {n.rel: score for n, score in ranked}
    printed = {n.rel for n, _ in ranked[:shown]}
    support: dict[str, float] = {}
    for note, score in ranked[:min(shown, LINK_SEEDS)]:  # seeds are printed results, so "above" holds
        for rel in graph[note.rel] - printed:
            support[rel] = support.get(rel, 0.0) + score
    best = sorted(support, key=lambda rel: (-(support[rel] + own.get(rel, 0.0)), rel))[:LINK_EXTRA]
    by_rel = {n.rel: n for n in corpus.notes}
    return [(by_rel[rel], own.get(rel, 0.0)) for rel in best]


_EVAL_FILE = "docs/search-eval.md"
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def eval_rows(root: Path) -> list[tuple[int, str, list[str]]] | None:
    """(line number, query, expected note paths) per row of docs/search-eval.md's query table; None when absent."""
    path = root / _EVAL_FILE
    if not path.is_file():
        return None
    rows = []
    in_table = False  # only the table whose header is "| Query | Expected notes |" holds queries
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.lstrip().startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:1] == ["Query"]:
            in_table = True
            continue
        if not in_table or len(cells) != 2 or not cells[0] or set(cells[0]) <= set("-: "):
            continue
        wanted = [os.path.normpath(f"docs/{m.split('#')[0]}").replace(os.sep, "/")
                  for m in _MD_LINK.findall(cells[1])]
        rows.append((number, cells[0].strip("`"), wanted))
    return rows


RELATIONS = ("links-to", "linked-from", "similar")


def _link_targets(root: Path, note: Note) -> set[str]:
    """Hub-relative paths the note links to (a folder link means its README.md), as `orphan_notes` resolves them."""
    targets = set()
    for _, _, file_part in _relative_links(note.body):
        target = os.path.normpath(root / Path(note.rel).parent / file_part)
        if Path(target).is_dir():
            target = os.path.join(target, "README.md")
        targets.add(Path(os.path.relpath(target, root)).as_posix())
    return targets


def related(root: Path, rel: str, *, limit: int = 5, corpus: Corpus | None = None) -> dict[str, list[Note]]:
    """Notes `rel` links to, notes linking to it (typed notes only, by path) and its `limit` most similar notes.

    Raises ValueError when `rel` is not a typed note; pass `corpus` (of all notes) to reuse one already built."""
    corpus = corpus or build_corpus(root)
    note = next((n for n in corpus.notes if n.rel == rel), None)
    if note is None:
        raise ValueError(f"not a note: {rel}")
    outgoing = _link_targets(root, note)
    links_to = [n for n in corpus.notes if n.rel in outgoing and n.rel != rel]
    linked_from = [n for n in corpus.notes if n.rel != rel and rel in _link_targets(root, n)]
    seen = {rel, *(n.rel for n in links_to + linked_from)}
    similar = [n for n, _ in rank(corpus, _title(note), limit=limit + len(seen)) if n.rel not in seen]
    return {"links-to": sorted(links_to, key=lambda n: n.rel), "linked-from": sorted(linked_from, key=lambda n: n.rel),
            "similar": similar[:limit]}


def _mention_pattern(note: Note) -> re.Pattern[str] | None:
    """Regex for text that names `note` without linking it: its title as a phrase (4+ words), and for a
    literature note also `Surname ... YEAR` (first author's last word, case-sensitive, within 40 characters)."""
    words = re.findall(r"\w+", _title(note))
    parts = [r"(?i:\b" + r"\W+".join(map(re.escape, words)) + r"\b)"] if len(words) >= 4 else []
    authors = note.meta.get("authors")
    if note.type == "literature" and isinstance(authors, list) and authors and str(authors[0]).split():
        surname = str(authors[0]).split()[-1]
        parts.append(rf"\b{re.escape(surname)}\b.{{0,40}}\b{re.escape(str(note.meta.get('year')))}\b")
    return re.compile("|".join(parts), re.S) if parts else None


def unlinked_mentions(root: Path, rel: str, corpus: Corpus) -> list[Note]:
    """Typed notes whose body names `rel`'s note (see `_mention_pattern`) without linking to it, by path.

    Markdown links are removed before looking, so the label of a link to another note is not a mention."""
    note = next((n for n in corpus.notes if n.rel == rel), None)
    if note is None:
        raise ValueError(f"not a note: {rel}")
    pattern = _mention_pattern(note)
    if pattern is None:
        return []
    return sorted((n for n in corpus.notes
                   if n.rel != rel and pattern.search(_LINK.sub("", n.body)) and rel not in _link_targets(root, n)),
                  key=lambda n: n.rel)


def search_eval(root: Path, *, limit: int = 10) -> tuple[list[str], int, int, float] | None:
    """(misses, found, expected, reciprocal-rank sum) for docs/search-eval.md; None when it is absent.

    The reciprocal-rank sum divided by `expected` is MRR@limit: it moves when a note climbs or falls
    inside the top `limit`, which recall alone does not show (used to tune BM25; see ADR 0003)."""
    rows = eval_rows(root)
    if rows is None:
        return None
    corpus = build_corpus(root)
    misses, found, expected, reciprocal = [], 0, 0, 0.0
    for number, query, wanted in rows:
        top = [n.rel for n, _ in rank(corpus, query, limit=limit)] if tokenize(query) else []
        for rel in wanted:
            expected += 1
            if rel in top:
                found += 1
                reciprocal += 1 / (top.index(rel) + 1)
            else:
                misses.append(f'{_EVAL_FILE}:{number}: missed {rel} for "{query}"')
    return misses, found, expected, reciprocal


class NewNoteError(Exception):
    pass


_HEADING = re.compile(r"^(#{1,4})[ \t]+\S")


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(0-based index, level, text) of each Markdown heading outside fenced code."""
    return [(i, len(h.group(1)), line) for i, (line, fenced) in enumerate(zip(lines, _in_fence(lines)))
            if not fenced and (h := _HEADING.match(line))]


def _sections(lines: list[str], wanted: list[str]) -> list[str]:
    """Requested `## ` sections in the note's order, then a message per absent one."""
    h2 = [(i, line[2:].strip().casefold()) for i, level, line in _headings(lines) if level == 2]
    keys = {w.strip().casefold() for w in wanted}
    out: list[str] = []
    seen: set[str] = set()
    for n, (start, key) in enumerate(h2):
        if key in keys:
            seen.add(key)
            end = h2[n + 1][0] if n + 1 < len(h2) else len(lines)
            out.extend(lines[start:end])
    for w in wanted:
        if w.strip().casefold() not in seen:
            out.append(f'(no section "{w}")')
    return out


_KEY_FACTS = {"knowledge": ("confidence", "updated", "level"), "literature": ("year", "kind", "url", "level"),
              "research": ("status", "started")}


def _key_facts(note_type: str, meta: Any) -> str | None:
    """One line of the fields an agent needs to judge a note; missing fields are left out."""
    if not isinstance(meta, dict) or note_type not in _KEY_FACTS:
        return None
    return " \u00b7 ".join(f"{k}: {meta[k]}" for k in _KEY_FACTS[note_type] if meta.get(k) is not None) or None


DETAILS = ("paths", "titles", "facts", "snippet", "summary")
_LEAD_SECTION = {"knowledge": "Claim", "literature": "TL;DR"}


def snippet(note: Note, terms: Sequence[str] = (), *, weights: Mapping[str, float] | None = None,
            width: int = 200) -> str:
    """The body line (not blank, heading, table separator or inside a fenced code block) with the highest
    total weight of its distinct `terms` (`weights`, else 1 each), earliest on ties; else the first such line.
    Whitespace is collapsed and text over `width` is cut with an ellipsis."""
    body = note.body.splitlines()
    fenced = _in_fence(body)
    lines = [line for line, inside in zip(body, fenced)
             if not inside and line.strip() and not line.lstrip().startswith("#") and not set(line.strip()) <= set("|-: ")]
    if not lines:
        return ""
    wanted = set(terms)
    weight = lambda line: sum(1.0 if weights is None else weights.get(t, 0.0) for t in wanted & set(tokenize(line)))
    best = max(lines, key=weight)  # max keeps the earliest tie
    text = " ".join(best.split())
    return text if len(text) <= width else text[:width - 1] + "\u2026"


def format_hit(note: Note, detail: str, *, score: float | None = None,
               terms: Sequence[str] = (), weights: Mapping[str, float] | None = None,
               name: str | None = None) -> list[str]:
    """Output lines for one note at a `DETAILS` level; `score` is omitted from the line when None and
    `name` (a short handle) replaces the path."""
    if detail == "paths":
        return [name or note.rel]
    lines = [(name or note.rel) + ("" if score is None else f"\t{score:.2f}") + f"\t{_title(note)}"]
    if detail == "titles":
        return lines
    if (facts := _key_facts(note.type, note.meta)) is not None:
        lines.append("  " + facts)
    if detail == "snippet" and (text := snippet(note, terms, weights=weights)):
        lines.append("  " + text)
    if detail == "summary":
        body = note.body.splitlines()
        lead = _LEAD_SECTION.get(note.type) or next((line[2:].strip() for _, level, line in _headings(body)
                                                     if level == 2), None)
        if lead is not None:
            lines.extend("  " + line for line in _sections(body, [lead])[1:] if line.strip())
    return lines


def _handle(rel: str) -> str:
    """What names a note: the file stem of a literature or knowledge note, the folder id of an investigation."""
    p = Path(rel)
    return p.parent.name if rel.startswith("research/") else p.stem


def short_handles(root: Path) -> dict[str, str]:
    """Path -> the shortest prefix of its handle, cut at a hyphen and at least two words long, that no other
    handle starts with (the whole handle when none is); `resolve_note` turns it back into the note."""
    handles = {rel: _handle(rel) for rel in (p.relative_to(root).as_posix() for _, p in _note_files(root))}
    out = {}
    for rel, handle in handles.items():
        words = handle.split("-")
        out[rel] = next((pre for k in range(2, len(words)) if sum(h.startswith(pre := "-".join(words[:k]))
                                                                  for h in handles.values()) == 1), handle)
    return out


def resolve_note(root: Path, arg: str, *, prefix: bool = True) -> Path | list[str] | None:
    """The `.md` file `arg` names inside the hub, as a resolved absolute Path.

    `arg` is a path (hub-relative or absolute), else a handle (`_handle`, with or without `.md`), else (when
    `prefix`, and `arg` does not end in `.md`) a unique prefix of a handle or of a hub-relative path; an exact
    handle or path wins over prefixes. Several matches return their hub-relative paths, sorted; no match
    returns None. Handles come from file names alone: no note is parsed."""
    root = root.resolve()
    path = Path(arg)
    path = (path if path.is_absolute() else root / path).resolve()
    if path.suffix == ".md" and path.is_file() and path.is_relative_to(root):
        return path
    name = arg.removesuffix(".md")
    if not name:
        return None
    rels = sorted(p.relative_to(root).as_posix() for _, p in _note_files(root))
    for found in ([r for r in rels if _handle(r) == name or r.removesuffix(".md") == name],
                  [r for r in rels if _handle(r).startswith(name) or r.startswith(name)]
                  if prefix and name == arg else []):
        if found:
            return root / found[0] if len(found) == 1 else found
    return None


def _ambiguous(arg: str, found: list[str]) -> None:
    print(f"ambiguous: {arg} matches {len(found)} notes:", *found[:10], sep="\n", file=sys.stderr)


_CONCLUSION = {"knowledge": ("Claim", "Does not apply when"), "literature": ("TL;DR",), "research": ("Question",)}


def _expand_conclusion(note_type: str, lines: list[str], sections: list[str]) -> list[str]:
    """Replace `conclusion` by the note type's lead sections that exist; other kinds get their first `## `."""
    present = [line[2:].strip() for _, level, line in _headings(lines) if level == 2]
    lead = [n for n in _CONCLUSION.get(note_type, present[:1]) if n.casefold() in {p.casefold() for p in present}]
    return [x for s in sections for x in (lead or [s] if s.strip().casefold() == "conclusion" else [s])]


def _outline_ranges(lines: list[str], body_line: int) -> list[str]:
    """`<start>-<end><TAB><words>w<TAB><heading>` per heading; a section ends before the next heading of its level or higher."""
    while lines and not lines[-1]:
        lines = lines[:-1]
    heads = _headings(lines)
    rows = []
    for n, (i, level, line) in enumerate(heads):
        stop = next((j for j, lv, _ in heads[n + 1:] if lv <= level), len(lines))
        words = sum(len(x.split()) for x in lines[i:stop])
        rows.append(f"{body_line + i}-{body_line + stop - 1}\t{words}w\t{line}")
    return rows


def show(root: Path, paths: list[str], *, sections: list[str] | None = None,
         outline: bool = False, ranges: bool = False) -> tuple[list[str], list[str], bool]:
    """Blocks of output, one per path; the resolved paths shown; whether every path was found."""
    blocks: list[str] = []
    shown: list[str] = []
    ok = True
    for arg in paths:
        path = resolve_note(root, arg)
        if isinstance(path, list):
            _ambiguous(arg, path)
            blocks.append(f"== {arg}\n(ambiguous: {len(path)} notes match)")
            ok = False
            continue
        if path is None:
            blocks.append(f"== {arg}\n(not found)")
            ok = False
            continue
        rel = path.relative_to(root.resolve()).as_posix()
        shown.append(rel)
        out = [f"== {rel}"]
        note_type = rel.split("/", 1)[0]
        try:
            text = _read_text(path)
        except FrontmatterError as exc:
            blocks.append(f"== {rel}\n({exc})")
            ok = False
            continue
        try:
            meta, body, body_line = split_frontmatter(text)
        except FrontmatterError:
            meta, body, body_line = None, text, 1
        if facts := _key_facts(note_type, meta):
            out.append(facts)
        lines = body.split("\n")
        if outline and ranges:
            out.extend(_outline_ranges(lines, body_line))
        elif outline:
            out.extend(f"{body_line + i}: {line}" for i, _, line in _headings(lines))
        elif sections:
            out.extend(_sections(lines, _expand_conclusion(note_type, lines, sections)))
        else:
            out.extend(lines)
        blocks.append("\n".join(out).rstrip("\n"))
    return blocks, shown, ok


def _dump_frontmatter(data: dict) -> str:
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=None,
                            width=float("inf"))
    return f"---\n{dumped}---\n"


def _knowledge_name_problem(stem: str) -> str | None:
    if word := instruction_word(stem):
        return f'knowledge name reads as an instruction ("{word}-..."): {_INSTRUCTION_FIX}'
    if len(stem) > MAX_KNOWLEDGE_NAME:
        return f"knowledge name too long ({len(stem)} characters): {_LONG_NAME_FIX}"
    return None


def new_note(root: Path, note_type: str, *, slug: str, topics: list[str], today: datetime.date,
             body: str | None = None, **fields: Any) -> Path:
    """Create a note from its template (or with `body` in place of the template body), refusing
    bad slugs, unknown topics and existing paths."""
    if note_type not in SCHEMAS:
        raise NewNoteError(f"unknown note type '{note_type}'")
    template = root / "templates" / f"{note_type}.md"
    try:
        _, template_body, _ = split_frontmatter(_read_text(template))
        known = load_topics(root)
    except FrontmatterError as exc:
        raise NewNoteError(f"cannot read template or topics: {exc}") from exc
    if not topics:
        raise NewNoteError("at least one topic is required")
    for t in topics:
        if t not in known:
            raise NewNoteError(f"unknown topic '{t}': use an id from topics.yaml or add it there")
    domain = root_of(known, topics[0])
    if domain not in root_topics(known):
        raise NewNoteError(f"topic '{topics[0]}' has no root topic (its parent chain ends at "
                           f"'{domain}'): fix its parent in topics.yaml")
    all_topics = list(topics)
    for t in topics:
        all_topics += [a for a in ancestors(known, t) if a not in all_topics]

    meta: dict[str, Any] = dict(fields)
    if note_type == "literature":
        author = meta.pop("author", "")
        names = [a.strip() for a in author.split(",") if a.strip()] if isinstance(author, str) else []
        meta["authors"] = names
        first = slugify(names[0]) if names else ""
        if not first:
            raise NewNoteError("author must contain at least one ASCII letter or digit "
                               "to form the filename")
        if _starts_with_author(slug.split("-"), first):
            raise NewNoteError(f"slug '{slug}' repeats the first author '{first}', which the "
                               f"filename already holds: drop '{first}-' from --slug")
        if slug.split("-")[0] == str(meta.get("year")):
            raise NewNoteError(f"slug '{slug}' repeats the year; `new` adds '<year>-<author>-' "
                               "itself: pass only the descriptive part as --slug")
        name = f"{meta.get('year')}-{first}-{slug}.md"
        meta["added"] = today.isoformat()
        target = root / "literature" / domain / name
        pattern_name = name
    elif note_type == "knowledge":
        if problem := _knowledge_name_problem(slug):
            raise NewNoteError(problem)
        meta["updated"] = today.isoformat()
        pattern_name = f"{slug}.md"
        target = root / "knowledge" / domain / pattern_name
    else:
        meta.update(status="idea", started=f"{today:%Y-%m}")
        pattern_name = f"{today:%Y-%m}-{slug}"
        target = root / "research" / pattern_name / "README.md"
    meta["topics"] = all_topics

    if not NAME_PATTERNS[note_type].fullmatch(pattern_name):
        raise NewNoteError(f"invalid name '{pattern_name}': {_NAME_FIX[note_type]}")
    ordered = {}
    for field, validator in SCHEMAS[note_type].items():
        if field not in meta and field in OPTIONAL_FIELDS:
            continue
        if field not in meta:
            raise NewNoteError(f"missing value for '{field}'")
        if (fix := validator(meta[field])) is not None:
            raise NewNoteError(f"invalid value for '{field}': {fix}")
        ordered[field] = meta[field]
    extra = set(meta) - set(ordered)
    if extra:
        raise NewNoteError(f"unexpected fields for {note_type}: {', '.join(sorted(extra))}")
    if note_type == "research" and target.parent.exists():
        raise NewNoteError(f"folder {target.parent.relative_to(root).as_posix()} already exists: "
                           "choose another slug")
    if target.exists():
        raise NewNoteError(f"{target.relative_to(root).as_posix()} already exists")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_dump_frontmatter(ordered) + (template_body if body is None else body),
                      encoding="utf-8")
    try:
        apply_index(root)
    except FrontmatterError as exc:
        raise NewNoteError(f"{target.relative_to(root).as_posix()} was created but the index "
                           f"was not updated ({exc}): fix it, then run mem index") from exc
    return target


# --- rename --------------------------------------------------------------------

def _link_edits(text: str, base: Path, old: Path, new_name: str) -> tuple[str, int]:
    """`text` of the file `base` with each relative link to `old` pointing at `new_name`, and their count.

    Links are found as `_relative_links` finds them (code is masked in place, so offsets stay valid);
    only the file name of the path part changes: prefix, `#anchor` and link text are kept.
    """
    lines = text.split("\n")
    masked = _CODE_SPAN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                            "\n".join(" " * len(l) if f else l for l, f in zip(lines, _in_fence(lines))))
    count = 0
    for i, line in enumerate(masked.split("\n")):
        for m in reversed(list(_LINK.finditer(line))):
            start, end = m.span(1 if m.group(1) is not None else 2)
            target = line[start:end]
            raw = target.split("#", 1)[0]
            if target.startswith(("#", "mailto:")) or _SCHEME.match(target) or not raw:
                continue
            try:
                hit = (base.parent / urllib.parse.unquote(raw)).resolve() == old
            except (OSError, ValueError):
                continue
            if hit:
                cut = start + len(raw) - len(raw.rsplit("/", 1)[-1])
                lines[i] = lines[i][:cut] + new_name + lines[i][start + len(raw):]
                count += 1
    return "\n".join(lines), count


def rename_note(root: Path, arg: str, new_stem: str) -> tuple[Path, int, int]:
    """Rename a literature or knowledge note in its folder; return (new path, links rewritten, files changed).

    Every edit is computed before anything is written, so a refusal leaves the hub untouched.
    """
    root = root.resolve()
    old = resolve_note(root, arg, prefix=False)
    if isinstance(old, list):
        raise NewNoteError(f"ambiguous: {arg} matches {len(old)} notes: {', '.join(old[:10])}")
    parts = old.relative_to(root).parts if old else ()
    if len(parts) != 3 or parts[0] not in ("literature", "knowledge") or old.name == "README.md" or _is_hidden(old, root):
        raise NewNoteError(f"{arg} is not a literature or knowledge note: give its path or exact handle "
                           "(no prefix; investigations are not renamed)")
    kind, stem = parts[0], new_stem.removesuffix(".md")
    name, new = f"{stem}.md", old.with_name(f"{stem}.md")
    if not NAME_PATTERNS[kind].fullmatch(name):
        raise NewNoteError(f"invalid name '{name}': {_NAME_FIX[kind]}")
    if kind == "knowledge" and (problem := _knowledge_name_problem(stem)):
        raise NewNoteError(problem)
    if kind == "literature":
        meta = _read_note(kind, old, root).meta
        authors = meta.get("authors") if isinstance(meta, dict) else None
        year, *tokens = old.stem.split("-")
        slug = slugify(authors[0]) if _authors(authors) is None else tokens[0]  # as rule_consistency: may span tokens
        n = next((k for k in range(1, len(tokens)) if "".join(tokens[:k]) == slug), 1)
        new_year, *new_tokens = stem.split("-")
        if new_year != year or tokens[:n] != new_tokens[:n]:
            raise NewNoteError(f"the name must keep the prefix {'-'.join([year, *tokens[:n]])}-")
        if (rest := new_tokens[n:]) and (_starts_with_author(rest, slug) or rest[0] == year):
            raise NewNoteError("the name repeats the author or the year after the prefix")
    if new.exists() or any(_handle(p.relative_to(root).as_posix()) == stem for _, p in _note_files(root)):
        raise NewNoteError(f"a note named '{stem}' already exists")
    sources, new_sources = root / SOURCES_DIR / old.stem, root / SOURCES_DIR / stem
    if new_sources.exists():
        raise NewNoteError(f"{SOURCES_DIR}/{stem} already exists")
    edits: dict[Path, str] = {}
    links = 0
    copy = f"{SOURCES_DIR}/{old.stem}/"
    for path in _markdown_files(root):
        try:
            text = _read_text(path)
        except FrontmatterError as exc:
            raise NewNoteError(f"cannot read {path.relative_to(root).as_posix()} to rewrite its links ({exc}): "
                               "fix it, then rename") from exc
        edited, count = _link_edits(text, path, old, name)
        count += edited.count(copy)  # a note's text naming its local copy
        if count:
            edits[path], links = edited.replace(copy, f"{SOURCES_DIR}/{stem}/"), links + count
    locked = [p for p in (*edits, old, old.parent, *((sources, sources.parent) if sources.is_dir() else ()))
              if not os.access(p, os.W_OK)]
    if locked:
        raise NewNoteError(f"not writable: {', '.join(p.relative_to(root).as_posix() for p in locked)}")
    for path, text in edits.items():
        path.write_text(text, encoding="utf-8")
    old.rename(new)
    if sources.is_dir():
        sources.rename(new_sources)
    try:
        apply_index(root)
    except FrontmatterError as exc:
        raise NewNoteError(f"{new.relative_to(root).as_posix()} was renamed but the index was not "
                           f"updated ({exc}): fix it, then run mem index") from exc
    return new, links, len(edits)


# --- fetch-sources -------------------------------------------------------------

SOURCES_DIR = ".sources"
FETCH_TIMEOUT = 30
FETCH_PAUSE = 1.0
FETCH_MAX_BYTES = 50 * 1024 * 1024  # larger sources stay online only (C-14)
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
_CONTENT_EXT = {"application/pdf": "pdf", "text/html": "html", "application/xhtml+xml": "html",
                "text/plain": "txt"}
_SUFFIX_EXT = {".pdf": "pdf", ".html": "html", ".htm": "html", ".txt": "txt"}


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s); urllib's default also follows ftp."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 (stdlib signature)
        if urllib.parse.urlparse(newurl).scheme not in ("http", "https"):
            raise ValueError(f"redirected to a non-http URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str) -> tuple[bytes, str]:
    """(body, Content-Type) of a URL, redirects followed. The only network access of the hub tools."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    opener = urllib.request.build_opener(_HttpOnlyRedirects)
    with opener.open(request, timeout=FETCH_TIMEOUT) as response:
        if urllib.parse.urlparse(response.geturl()).scheme not in ("http", "https"):
            raise ValueError(f"redirected to a non-http URL: {response.geturl()}")
        data = response.read(FETCH_MAX_BYTES + 1)
        if len(data) > FETCH_MAX_BYTES:
            raise ValueError(f"response larger than {FETCH_MAX_BYTES // (1024 * 1024)} MB")
        return data, response.headers.get("Content-Type", "")


def _source_extension(url: str, content_type: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in _CONTENT_EXT:
        return _CONTENT_EXT[mime]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return _SUFFIX_EXT.get(suffix, "html")


_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "svg", "title", "select", "button",
              "option"}
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article",
               "blockquote", "pre"}
_CHARSET = re.compile(rb"""charset\s*=\s*["']?([\w.:-]+)""", re.I)
MIN_TEXT_WORDS = 200  # a shorter conversion is a shell page (script-rendered, paywalled), not a source text


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip: list[str] = []
        self.main = 0  # open article/main elements: a header inside one is part of the text

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.main += tag in ("article", "main")
        if tag in _SKIP_TAGS and not (tag == "header" and self.main):
            self.skip.append(tag)
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        self.main = max(0, self.main - (tag in ("article", "main")))
        if tag in self.skip:
            del self.skip[len(self.skip) - 1 - self.skip[::-1].index(tag):]
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))  # a newline inside the markup is not a line break


def html_to_text(data: bytes) -> str:
    """Plain text of an HTML document: no script, style or page chrome; one line per block, spaces collapsed.

    Charset from a `<meta>` in the first 4,096 bytes, else UTF-8, latin-1 when that fails to decode."""
    match = _CHARSET.search(data[:4096])
    try:
        text = data.decode(match.group(1).decode("ascii") if match else "utf-8")
    except (UnicodeDecodeError, LookupError):
        text = data.decode("latin-1")
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.out).split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def _literature_notes(root: Path, paths: list[str] | None) -> tuple[list[Note], list[str]]:
    """The literature notes to work on (all, or the given paths) and a `failed` line per path that is not one."""
    notes = [n for n in discover_notes(root) if n.type == "literature"]
    if not paths:
        return notes, []
    by_rel = {n.rel: n for n in notes}
    return ([by_rel[p] for p in paths if p in by_rel],
            [f"failed {p}: not a literature note" for p in paths if p not in by_rel])


def _txt_files(folder: Path) -> list[Path]:
    """Every `.txt` entry of a source folder (any case, symlinks too): the hub never writes `source.txt` beside one."""
    return [p for p in folder.iterdir() if p.suffix.lower() == ".txt"]


def _write_text_copy(folder: Path) -> str | None:
    """Write `source.txt` from the folder's largest HTML copy, else its largest PDF; None when written, else the reason."""
    def largest(*patterns: str) -> Path | None:
        found = [p for pat in patterns for p in folder.glob(pat) if p.is_file() and not p.is_symlink()]
        return max(found, key=lambda p: (p.stat().st_size, p.name), default=None)

    if _txt_files(folder):
        return "the folder already holds a .txt"
    reason = "no HTML or PDF copy"
    if (page := largest("*.html", "*.htm")) is not None:
        text = html_to_text(page.read_bytes())
        if len(text.split()) >= MIN_TEXT_WORDS:
            (folder / "source.txt").write_text(text, encoding="utf-8")
            return None
        reason = f"page has under {MIN_TEXT_WORDS} words of text"
    if (pdf := largest("*.pdf")) is None:
        return reason
    if not shutil.which("pdftotext"):
        return "pdftotext is not installed"
    try:
        done = subprocess.run(["pdftotext", str(pdf), str(folder / "source.txt")], check=False, timeout=60,
                              capture_output=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"pdftotext failed: {exc}"
    if done.returncode == 0:
        return None
    (folder / "source.txt").unlink(missing_ok=True)
    return f"pdftotext failed with exit {done.returncode}"


def build_missing_texts(root: Path, paths: list[str] | None = None) -> tuple[list[str], bool]:
    """`fetch-sources --text-only`: write `source.txt` in each `.sources/<stem>/` folder that holds no `.txt`.

    Never downloads, never touches a folder with any `.txt` (hand-made texts win in `passages`) and skips a
    folder that is a symlink. Returns (output lines, False when a PATH is not a literature note)."""
    notes, lines = _literature_notes(root, paths)
    bad = bool(lines)
    written = without = had = 0
    for note in notes:
        folder = root / SOURCES_DIR / note.path.stem
        if not folder.is_dir():
            continue
        words = 0
        try:
            if folder.is_symlink():
                reason = f"{SOURCES_DIR}/{folder.name} is a symlink"
            elif _txt_files(folder):
                had += 1
                continue
            elif (reason := _write_text_copy(folder)) is None:
                words = len((folder / "source.txt").read_text(encoding="utf-8").split())
        except OSError as exc:
            reason = str(exc)
        if reason is None:
            lines.append(f"text {note.rel} ({words} words)")
            written += 1
        else:
            lines.append(f"no text {note.rel}: {reason}")
            without += 1
    lines.append(f"text written {written}, without text {without}, already had text {had}")
    return lines, not bad


def fetch_sources(root: Path, paths: list[str] | None = None, *,
                  force: bool = False) -> tuple[list[str], bool]:
    """Download each literature note's `url` into .sources/<note-stem>/; returns (output lines, all ok)."""
    notes, lines = _literature_notes(root, paths)
    counts = {"fetched": 0, "skipped": 0, "failed": len(lines)}
    requested = False
    for note in notes:
        folder = root / SOURCES_DIR / note.path.stem
        url = note.meta.get("url") if isinstance(note.meta, dict) else None
        if folder.is_symlink():
            lines.append(f"failed {note.rel}: {SOURCES_DIR}/{folder.name} is a symlink")
            counts["failed"] += 1
            continue
        if not force and folder.is_dir() and any(not p.is_symlink() for p in folder.iterdir()):
            lines.append(f"skipped {note.rel} (already cached)")
            counts["skipped"] += 1
            continue
        if not isinstance(url, str) or urllib.parse.urlparse(url).scheme not in ("http", "https"):
            lines.append(f"failed {note.rel}: url must start with http:// or https://")
            counts["failed"] += 1
            continue
        if requested:
            time.sleep(FETCH_PAUSE)
        requested = True
        try:
            data, content_type = _download(url)
            ext = _source_extension(url, content_type)
            folder.mkdir(parents=True, exist_ok=True)
            if ext == "txt" and any(p.name != "source.txt" for p in _txt_files(folder)):
                raise ValueError("the folder already holds a .txt")
            for old in folder.glob("source.*"):  # --force: drop copies of another type or a stale text
                old.unlink()
            (folder / f"source.{ext}").write_bytes(data)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            lines.append(f"failed {note.rel}: {exc}")
            counts["failed"] += 1
            continue
        if ext == "pdf" and shutil.which("pdftotext") and not _txt_files(folder):
            try:
                subprocess.run(["pdftotext", str(folder / "source.pdf"), str(folder / "source.txt")],
                               check=False, timeout=60, capture_output=True)
            except (OSError, subprocess.SubprocessError):
                pass
        note_line = f"fetched {note.rel}"
        if ext == "html":
            try:
                reason = _write_text_copy(folder)
            except OSError as exc:
                reason = str(exc)
            if reason is not None:
                note_line += f" (no text: {reason})"
        lines.append(note_line)
        counts["fetched"] += 1
    lines.append(f"fetched {counts['fetched']}, skipped {counts['skipped']}, failed {counts['failed']}")
    return lines, counts["failed"] == 0


def source_text(root: Path, rel: str) -> Path | None:
    """The largest `.txt` (ties by name) of a literature note's `.sources/<note-stem>/` folder, else its largest `.md`."""
    folder = root / SOURCES_DIR / Path(rel).stem
    texts: list[Path] = []
    for pattern in ("*.txt", "*.md"):
        texts = [p for p in folder.glob(pattern) if p.is_file() and not p.is_symlink()] if folder.is_dir() else []
        if texts:
            break
    return min(texts, key=lambda p: (-p.stat().st_size, p.name), default=None)


def passages(text: str, query: str, *, count: int = 5, words: int = 500) -> tuple[int, list[tuple[int, int, str]]]:
    """(word count, [(first, last, text)] of the `count` best windows by BM25 over this text, in document order).

    Windows of `words` words start half a window apart (BM25 k1 1.2, b 0.75); the last ends at the text's end;
    word numbers start at 1."""
    tokens = text.split()
    step = max(1, words // 2)
    starts = []
    for start in range(0, max(len(tokens), 1), step):
        starts.append(start)
        if start + words >= len(tokens):
            break
    wins = [" ".join(tokens[s:s + words]) for s in starts]
    counts = [collections.Counter(tokenize(w)) for w in wins]
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / len(wins)
    idf = {}
    for term in dict.fromkeys(tokenize(query)):
        n = sum(1 for c in counts if term in c)
        idf[term] = math.log(1 + (len(wins) - n + 0.5) / (n + 0.5))
    scored = []
    for i, (c, length) in enumerate(zip(counts, lengths)):
        score = sum(idf[t] * c[t] * 2.2 / (c[t] + 1.2 * (1 - 0.75 + 0.75 * length / average))
                    for t in idf if c.get(t) and average)
        if score > 0:
            scored.append((-score, i))
    best = sorted(i for _, i in sorted(scored)[:count])
    return len(tokens), [(starts[i] + 1, min(starts[i] + words, len(tokens)), wins[i]) for i in best]


# --- CLI ---------------------------------------------------------------------


def _scopes(root: Path, paths: list[str]) -> list[str]:
    """Hub-relative form of existing files or folders inside the hub; ValueError names the first that is not."""
    out = []
    for arg in paths:
        path = (Path(arg) if Path(arg).is_absolute() else root / arg).resolve()
        if not path.exists() or not path.is_relative_to(root.resolve()):
            raise ValueError(f"no such file or folder in the hub: {arg}")
        out.append(path.relative_to(root.resolve()).as_posix())
    return out


def _in_scopes(rel: str, scopes: list[str]) -> bool:
    return not scopes or any(s == "." or rel == s or rel.startswith(s + "/") for s in scopes)


def _page_footer(offset: int, shown: int, total: int) -> None:
    if shown and offset + shown < total:
        print(f"-- {offset + 1}-{offset + shown} of {total}; next: --offset {offset + shown} --", file=sys.stderr)
    elif not shown and offset:
        print(f"-- offset {offset} is past the {total} matches --", file=sys.stderr)


def cmd_check(args: argparse.Namespace) -> int:
    try:
        scopes = _scopes(args.root, args.paths)
    except ValueError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    problems = [p for p in check(args.root) if _in_scopes(p.path, scopes)]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def cmd_index(args: argparse.Namespace) -> int:
    try:
        changed = apply_index(args.root)
    except (FrontmatterError, OSError) as exc:
        print(f"mem: cannot build the index: {exc}", file=sys.stderr)
        return 1
    for rel in changed:
        print(f"updated {rel}")
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    try:
        notes = _matching_notes(args.root, type=args.type, topic=args.topic, kind=args.kind,
                                status=args.status, confidence=args.confidence, level=args.level)
    except (FrontmatterError, OSError) as exc:
        print(f"mem: cannot find: {exc}", file=sys.stderr)
        return 1
    page = sorted(notes, key=lambda n: n.rel)[args.offset:args.offset + args.limit]
    names = short_handles(args.root) if args.handles else {}
    for note in page:
        print("\n".join(format_hit(note, args.detail, name=names.get(note.rel))))
    _page_footer(args.offset, len(page), len(notes))
    return 0


def topic_tree(root: Path, topic: str | None = None) -> list[tuple[int, str, int]]:
    """(depth, id, notes) in tree order; notes counts what `find --topic <id>` returns, descendants included."""
    known = load_topics(root)
    if topic and topic not in known:
        raise FrontmatterError(_unknown_topic_message(topic, known))
    counts: collections.Counter = collections.Counter()
    for note in _matching_notes(root):
        listed = note.meta.get("topics")
        direct = {t for t in listed if isinstance(t, str) and t in known} if isinstance(listed, list) else set()
        counts.update(direct.union(*(ancestors(known, t) for t in direct)))
    rows: list[tuple[int, str, int]] = []

    def walk(tid: str, depth: int) -> None:
        rows.append((depth, tid, counts[tid]))
        for child in sorted(t for t in known if _parent(known, t) == tid and t not in {r[1] for r in rows}):
            walk(child, depth + 1)

    for tid in [topic] if topic else sorted(root_topics(known)):
        walk(tid, 0)
    return rows


def cmd_topics(args: argparse.Namespace) -> int:
    try:
        rows = topic_tree(args.root, args.topic)
    except (FrontmatterError, OSError) as exc:
        print(f"mem: cannot find: {exc}", file=sys.stderr)
        return 1
    for depth, tid, count in rows:
        print(f"{'  ' * depth}{tid}\t{count}")
    return 0


def _usage_log(env: Mapping[str, str]) -> Path | None:
    data = data_dir(env)
    return None if data is None else data / "usage" / "log.jsonl"


def _is_outside(root: Path, cwd: Path | None) -> bool:
    try:
        here = (cwd if cwd is not None else Path.cwd()).resolve()
        return not here.is_relative_to(root.resolve())
    except OSError:
        return True


def log_usage(root: Path | None, entry: dict[str, Any], *, env: Mapping[str, str] | None = None,
              cwd: Path | None = None) -> None:
    """Append one JSON line to the usage log in the data folder; never raises, never changes output."""
    env = os.environ if env is None else env
    if env.get("MEM_USAGE_LOG") == "0":
        return
    entry = {"t": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    try:
        log_path = _usage_log(env)
        if root is not None:
            entry["outside"] = _is_outside(root, cwd)
            # the store is never written by the log
            if log_path is not None and log_path.resolve().is_relative_to(root.resolve()):
                return
        if log_path is None:
            return
        # ASCII escapes keep one entry on one line and survive argv that is not valid UTF-8
        line = (json.dumps(entry) + "\n").encode("ascii")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)  # one write: parallel processes cannot interleave lines
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError):
        pass


def _memory_folders(args: argparse.Namespace) -> list[tuple[str, Path | None]]:
    try:
        project = records.project_root(Path.cwd(), os.environ)
    except OSError:
        project = None
    return [("project", records.project_dir(project) if project else None),
            ("global", records.memories_root(os.environ, _optional_store(args)))]


def _memory_status(m: records.Memory, today: datetime.date) -> str | None:
    if m.status != "active":
        return m.status
    return "expired" if m.valid_until is not None and m.valid_until < today else None


def _memory_line(m: records.Memory, today: datetime.date) -> str:
    dead = _memory_status(m, today)
    created = m.created.isoformat() if m.created else "undated"
    claim = " ".join(m.claim.split())  # a hand-edited tab or newline must not add a column
    return f"m:{m.handle}\t[memory: {m.kind}, observed {m.observed}, {created}{', ' + dead if dead else ''}]\t{claim}"


def _memory_block(m: records.Memory, sections: list[str] | None) -> str:
    facts = f"kind: {m.kind} \u00b7 observed {m.observed} \u00b7 status {m.status} \u00b7 created {m.created.isoformat() if m.created else 'undated'}"
    if m.valid_until:
        facts += f" \u00b7 valid until {m.valid_until.isoformat()}"
    if m.context:
        facts += f" \u00b7 context: {m.context}"
    out = [f"== m:{m.handle} ({m.scope})", facts]
    if m.sources:
        out.append(f"sources: {', '.join(m.sources)}")
    out += ["", "## Claim", " ".join(m.claim.split())]
    if not (sections and any(s.strip().casefold() == "conclusion" for s in sections)) and m.body.strip():
        out += ["", m.body.rstrip("\n")]
    return "\n".join(out)


def cmd_show(args: argparse.Namespace) -> int:
    if args.ranges and not args.outline:
        build_parser().error("--ranges needs --outline")
    if args.outline and args.section:
        print("mem: --outline and --section cannot be used together", file=sys.stderr)
        return 2
    if any(a.startswith("m:") for a in args.paths):
        blocks, shown, ok = [], [], True
        for arg in args.paths:
            if arg.startswith("m:"):
                found = _find_memory(args, arg[2:])
                if found is None:
                    print(f"mem: no memory {arg}", file=sys.stderr)
                    blocks.append(f"== {arg}\n(not found)")
                    ok = False
                elif found.error is not None:
                    print(f"mem: skipped {found.path}: {found.error}", file=sys.stderr)
                    ok = False
                else:
                    blocks.append(_memory_block(found, args.section))
                continue
            b, sh, o = show(args.root, [arg], sections=args.section, outline=args.outline, ranges=args.ranges)
            blocks += b
            shown += sh
            ok = ok and o
    else:
        blocks, shown, ok = show(args.root, args.paths, sections=args.section, outline=args.outline,
                                 ranges=args.ranges)
    print("\n\n".join(blocks))
    if ok:
        log_usage(args.root, {"cmd": "show", "paths": list(dict.fromkeys(shown)), "sections": args.section or [],
                              "outline": bool(args.outline)})
    return 0 if ok else 1


_INIT_ALLOWED = {"mem-store.yaml", "topics.yaml", "literature", "knowledge", "research", "memories", "templates",
                 ".git", ".gitignore", "README.md"}


def _memory_body(source: str | None) -> str:
    """The text of `--body-file` (`-` is standard input); absent or empty gives an empty body."""
    if not source:
        return ""
    if source == "-":
        if sys.stdin.isatty():
            raise OSError("--body-file - needs the body on standard input, not a terminal")
        return sys.stdin.read().removeprefix("\ufeff").replace("\r\n", "\n")
    return Path(source).read_text(encoding="utf-8").replace("\r\n", "\n")


def _optional_store(args: argparse.Namespace) -> Path | None:
    return args.root if isinstance(args.root, Path) and args.root.is_dir() else None


def _find_memory(args: argparse.Namespace, handle: str) -> records.Memory | None:
    """An exact handle: the project scope wins over the global one."""
    project = records.project_root(Path.cwd(), os.environ)
    folders = [("project", records.project_dir(project) if project else None),
               ("global", records.memories_root(os.environ, _optional_store(args)))]
    for scope, folder in folders:
        for m in records.load_memories(folder, scope):
            if m.handle == handle:
                return m
    return None


_READ_ONLY_PROJECT = ("mem: this project is the store, which is read-only: it has no mem-store.yaml; "
                      "a memory cannot be written here.")
_READ_ONLY_MEMORIES = "mem: the memories folder is inside the store, which is read-only: it has no mem-store.yaml."


def _read_only_store(store: Path | None, path: Path) -> bool:
    return store is not None and not records.store_is_writable(store) and records.inside(path, store)


def _same_claim(a: str, b: str) -> bool:
    """Exact duplicate by word sequence in any script; claims with no word characters compare as stripped text."""
    wa, wb = re.findall(r"\w+", a.casefold()), re.findall(r"\w+", b.casefold())
    return wa == wb if wa or wb else a.strip() == b.strip()


_INDEX_HEAD = "memory: the mem command searches notes and memories (skill: memory)."
_INDEX_RULES = (
    _INDEX_HEAD + "\n"
    '- Before you act on this project, change something or research a topic: mem search "<topic in English>". '
    "It returns decisions, constraints and pitfalls recorded earlier that the files do not show.\n"
    "- To remember: preferences and personal matters -> auto memory; what a later session would need (a decision, "
    "constraint, pitfall or finding) -> mem remember, in English, with --global if it holds in any project and names "
    "no business; the project's current situation -> both."
)
_INDEX_LIMIT = 1500
_CLAIM_LIMIT = 100


def _count_notes(store: Path) -> int:
    """Notes by file name only: the index runs at every session start and must not read them."""
    try:
        files = [p for kind in ("literature", "knowledge") for p in store.glob(f"{kind}/*/*.md")
                 if p.name != "README.md"]
        files += list(store.glob("research/*/README.md"))
        return len(files)
    except OSError:
        return 0


def session_index(store: Path | None, project: Path | None, memories: Path | None, today: datetime.date,
                  *, limit: int = 0) -> str:
    """Text for the start of a session: three generic lines with counts; the project's newest memories when limit > 0."""
    try:
        has_store = store is not None and store.is_dir()
        has_memories = memories is not None and memories.is_dir()
    except OSError:
        has_store = has_memories = False
    head = [_INDEX_HEAD]
    if has_store:
        head.append(f"Store: {_count_notes(store)} notes.")
    if has_memories:
        live = sum(1 for m in records.load_memories(memories, "global") if records.is_live(m, today))
        head.append(f"Global memories: {live}.")
    mine = [m for m in records.load_memories(project, "project") if records.is_live(m, today)]
    if mine:
        mine.sort(key=lambda m: m.handle)  # stable sorts, least significant key first
        mine.sort(key=lambda m: m.created or datetime.date.min, reverse=True)
        mine.sort(key=lambda m: m.observed, reverse=True)
        mine.sort(key=lambda m: m.kind != "state")  # the project's current situation first
        head.append(f"This project: {len(mine)} memories.")
    lines = [" ".join(head)] + _INDEX_RULES.split("\n")[1:]
    if mine and limit > 0:
        rows = []
        for m in mine:
            claim = " ".join(m.claim.split())
            if len(claim) > _CLAIM_LIMIT:
                claim = claim[:_CLAIM_LIMIT] + "…"
            created = m.created.isoformat() if m.created else "undated"
            rows.append(f"  m:{m.handle} [{m.kind}, {created}] {claim}")
        shown = min(limit, len(rows))
        while True:
            tail = [f'  … and {len(rows) - shown} more: mem search "<words>" --scope memories'] if shown < len(rows) else []
            text = "\n".join(lines + rows[:shown] + tail)
            if len(text) <= _INDEX_LIMIT or shown == 0:
                return text
            shown -= 1
    return "\n".join(lines)


def _hook_input() -> dict[str, Any]:
    """The hook's JSON from standard input; {} when it is missing or not an object."""
    try:
        if sys.stdin is None or sys.stdin.isatty():  # nothing piped: never wait for a terminal
            return {}
        data = json.load(sys.stdin)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _log_hook(entry: dict[str, Any]) -> None:
    """Append one line to the hook log in the data folder; never raises. Holds no text and no path."""
    entry = {"t": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    try:
        folder = data_dir(os.environ)
        if folder is None:
            return
        log_path = folder / "hooks" / "log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(entry) + "\n").encode("ascii"))
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError):
        pass


def cmd_session_index(args: argparse.Namespace) -> int:
    """Never fails: the rules matter most when nothing is configured yet. Writes only the hook log, with --hook."""
    started = time.monotonic()
    data = _hook_input() if args.hook else {}
    try:
        store = args.root if isinstance(args.root, Path) else None
        cwd = Path(data["cwd"]) if isinstance(data.get("cwd"), str) and data["cwd"] else Path.cwd()
        if not cwd.is_dir():
            cwd = Path.cwd()
        try:
            project = records.project_root(cwd, os.environ)
        except OSError:
            project = None
        memories = records.memories_root(os.environ, store if store is not None and store.is_dir() else None)
        text = session_index(store, records.project_dir(project) if project else None, memories,
                             datetime.date.today(), limit=max(args.list, 0))
    except Exception:
        text = _INDEX_RULES
    print(text)
    if args.hook:
        source = data.get("source")
        _log_hook({"hook": "session-index", "source": source if isinstance(source, str) else None,
                   "ms": int((time.monotonic() - started) * 1000), "chars": len(text)})
    return 0


_SIGNAL_LIMIT = 400
_SIGNAL_HANDLES = 3


def signal_text(strong: Sequence[records.Related], possible: Sequence[records.Related]) -> str:
    """The block appended to a subagent's brief: handles and counts only, at most _SIGNAL_LIMIT characters."""
    if not strong:
        return ""
    shown = [f"{r.kind}:{r.handle}" for r in strong[:_SIGNAL_HANDLES]]  # only strong matches are named

    def render(items: list[str]) -> str:
        return "\n".join([
            f"[memory] For information: memories related to this task exist (not read yet): {' '.join(items)}",
            f"{len(strong)} strong, {len(possible)} possibly related. Read one with: mem show m:<handle> "
            "(they are files in .memory/).",
            "They are experience, not fact: where one conflicts with this brief, the brief wins and you report "
            "the conflict."])

    text = render(shown)
    while len(text) > _SIGNAL_LIMIT and len(shown) > 1:  # very long note names
        shown.pop()
        text = render(shown)
    return text


def cmd_signal(args: argparse.Namespace) -> int:
    """Never fails. Without --hook: the brief on standard input, the signal text out. With --hook: the hook's JSON in,
    the brief with the signal appended out (updatedInput, never a permission decision), one line in the hook log."""
    started = time.monotonic()
    try:
        data: dict[str, Any] = {}
        if args.hook:
            data = _hook_input()
            tool_input = data.get("tool_input")
            if data.get("tool_name") != "Agent" or not isinstance(tool_input, dict):
                return 0
            brief = tool_input.get("prompt")
        else:
            brief = None if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
        if not isinstance(brief, str) or not brief.strip():
            return 0
        subagent_type = tool_input.get("subagent_type") if args.hook else None
        store = args.root if isinstance(args.root, Path) else None
        cwd = Path(data["cwd"]) if isinstance(data.get("cwd"), str) and data["cwd"] else Path.cwd()
        if not cwd.is_dir():
            cwd = Path.cwd()
        project = records.project_root(cwd, os.environ)
        memories = records.memories_root(os.environ, store if store is not None and store.is_dir() else None)
        today = datetime.date.today()
        found = (records.load_memories(records.project_dir(project) if project else None, "project")
                 + records.load_memories(memories, "global"))
        strong, possible = records.related_records(found, [], brief, today, tokenize=tokenize)  # memories only
        text = signal_text(strong, possible)
        if args.hook:
            _log_hook({"hook": "signal", "ms": int((time.monotonic() - started) * 1000),
                       "strong": len(strong), "possible": len(possible),
                       "subagent_type": subagent_type if isinstance(subagent_type, str) else None,
                       "words": len(brief.split())})
        if not text:
            return 0
        if args.hook:
            updated = {**tool_input, "prompt": f"{brief}\n\n{text}"}
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}}))
        else:
            print(text)
    except Exception:
        pass
    return 0


def cmd_remember(args: argparse.Namespace) -> int:
    today = datetime.date.today()
    store = _optional_store(args)
    args.claim = " ".join(args.claim.split())
    if args.context is not None:
        args.context = " ".join(args.context.split()) or None
    if not args.claim:
        print("mem: the claim is empty.", file=sys.stderr)
        return 2
    if args.kind not in records.KINDS:
        print(f"mem: unknown kind {args.kind!r}.", file=sys.stderr)
        return 2
    if args.is_global:
        folder = records.memories_root(os.environ, store)
        if folder is None:
            print('mem: no folder for global memories: set the plugin\'s "memories" option, '
                  'or MEM_MEMORIES, or use a store made with "mem init".', file=sys.stderr)
            return 2
        if _read_only_store(store, folder.resolve()):
            print(_READ_ONLY_MEMORIES, file=sys.stderr)
            return 2
        forbidden = records.forbidden_file(os.environ)
        if forbidden is None or not forbidden.is_file():
            print(f"mem: global memories need the file {forbidden} (one forbidden term per line; it may be empty), "
                  "so that a business name is not written by mistake.", file=sys.stderr)
            return 2
        project = None
    else:
        project = records.project_root(Path.cwd(), os.environ)
        if project is None:
            print("mem: not inside a git repository: pass --global, or set MEM_PROJECT to the project folder.",
                  file=sys.stderr)
            return 2
        folder = records.project_dir(project)
        if _read_only_store(store, project) or _read_only_store(store, folder.resolve()):
            print(_READ_ONLY_PROJECT, file=sys.stderr)
            return 2
    scope = "global" if args.is_global else "project"
    if args.kind in ("finding", "document") and not args.source:
        print(f"mem: a {args.kind} needs at least one --source.", file=sys.stderr)
        return 2
    try:
        body = _memory_body(args.body_file)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mem: cannot read the body: {exc}", file=sys.stderr)
        return 2
    if args.is_global:
        try:
            hit = records.forbidden_line([args.claim, args.context or "", body, *args.source,
                                          records.slug_of(args.claim)], os.environ)
        except records.ForbiddenListError as exc:
            print(f"mem: the forbidden-terms list cannot be read ({exc}); nothing was written.", file=sys.stderr)
            return 2
        if hit is not None:
            print(f"mem: the text contains a forbidden term (line {hit} of the forbidden-terms list); "
                  "nothing was written.", file=sys.stderr)
            return 4
    claim_tokens = tokenize(args.claim)
    existing = records.load_memories(folder, scope)
    live = [m for m in existing if records.is_live(m, today)]
    if not args.force:
        same = [m for m in live if _same_claim(m.claim, args.claim)]
        if same:
            for m in same:
                print(f"m:{m.handle}\t{m.claim}", file=sys.stderr)
            print(f'mem: a memory with the same claim exists; run "mem observe m:{same[0].handle}" if it is the same, '
                  "or repeat with --force to write a new one.", file=sys.stderr)
            return 3
    related = records.match_memories(live, claim_tokens, today, tokenize=tokenize)
    exclude_failed = False
    if project is not None:
        try:
            records.ensure_excluded(project)
        except OSError:
            exclude_failed = True
    try:
        m = records.write_memory(folder, scope, kind=args.kind, claim=args.claim, body=body, today=today,
                                 context=args.context, valid_until=args.valid_until, sources=args.source)
    except (ValueError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    rel = m.path.relative_to(project if project is not None else folder).as_posix()
    print(f"m:{m.handle}\t{rel}")
    if exclude_failed:
        print("mem: could not add .memory/ to .git/info/exclude; the folder may appear in git status.", file=sys.stderr)
    if related:
        print('related memories (if one is the same, run "mem observe m:<handle>"; if one says the opposite, keep both):',
              file=sys.stderr)
        for r in related:
            print(f"m:{r.handle}\t[{r.kind}, observed {r.observed}, {r.created.isoformat() if r.created else '?'}]\t{r.claim}",
                  file=sys.stderr)
    log_usage(store, {"cmd": "remember", "scope": scope})
    return 0


def _memory_of(args: argparse.Namespace, handles: Sequence[str]) -> list[records.Memory] | None:
    """The named memories, all in one scope: the project's unless --global; None after a message on stderr.

    A handle found in both scopes means the project one, as for any lookup; with several handles the scope is
    one that holds all of them, and handles that exist only in different scopes are refused."""
    project = records.project_root(Path.cwd(), os.environ)
    folders = {"project": records.project_dir(project) if project else None,
               "global": records.memories_root(os.environ, _optional_store(args))}
    loaded = {scope: {m.handle: m for m in records.load_memories(folder, scope)} for scope, folder in folders.items()}
    order = ("global",) if args.is_global else ("project", "global")
    names = [h.removeprefix("m:") for h in handles]
    for name, raw in zip(names, handles):
        if not any(name in loaded[scope] for scope in order):
            print(f"mem: no memory named {raw}", file=sys.stderr)
            return None
    for scope in order:
        if all(name in loaded[scope] for name in names):
            found = [loaded[scope][name] for name in names]
            break
    else:
        print(f"mem: {' and '.join('m:' + n for n in names)} are in different scopes: both must be in the same one.",
              file=sys.stderr)
        return None
    store = _optional_store(args)
    for m in found:
        if m.error is not None:
            print(f"mem: {m.path}: {m.error}", file=sys.stderr)
            return None
        if _read_only_store(store, m.path.resolve()):
            print(_READ_ONLY_PROJECT if m.scope == "project" else _READ_ONLY_MEMORIES, file=sys.stderr)
            return None
    return found


def _with_note(body: str, heading: str, text: str) -> str:
    """The body with a heading line and the text under it added at the end."""
    head = body.rstrip("\n")
    return f"{head}\n\n{heading}\n{text.strip()}\n" if head.strip() else f"{heading}\n{text.strip()}\n"


def _reason_allowed(memory: records.Memory, because: str | None) -> bool:
    """A reason written into a global memory goes through the forbidden-terms list, failing closed."""
    if not because or memory.scope != "global":
        return True
    try:
        hit = records.forbidden_line([because], os.environ)
    except records.ForbiddenListError as exc:
        print(f"mem: the forbidden-terms list cannot be read ({exc}); nothing was written.", file=sys.stderr)
        return False
    if hit is not None:
        print(f"mem: the text contains a forbidden term (line {hit} of the forbidden-terms list); "
              "nothing was written.", file=sys.stderr)
        return False
    return True


def _act(args: argparse.Namespace, handles: Sequence[str], apply: Callable[[list[records.Memory], datetime.date], list[str]],
         name: str, because: str | None = None) -> int:
    found = _memory_of(args, handles)
    if found is None:
        return 2
    if not _reason_allowed(found[0], because):
        return 4
    try:
        lines = apply(found, datetime.date.today())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    log_usage(_optional_store(args), {"cmd": name, "scope": found[0].scope})
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    def apply(found, today):
        updated = records.observe(found[0], today)
        return [f"m:{updated.handle}\tobserved {updated.observed}"]
    return _act(args, [args.handle], apply, args.command)


def _text_change(found: list[records.Memory], key: str, heading: str, because: str | None, today: datetime.date,
                 **extra) -> records.Memory:
    m = found[0]
    changes = {"status": key, key: today, **extra}
    if because and because.strip():
        changes["body"] = _with_note(m.body, f"{heading} {today.isoformat()}:", because)
    return records.update(m, today, **changes)


def cmd_refute(args: argparse.Namespace) -> int:
    def apply(found, today):
        _text_change(found, "refuted", "Refuted", args.because, today)
        return [f"m:{found[0].handle}\trefuted"]
    return _act(args, [args.handle], apply, "refute", args.because)


def cmd_forget(args: argparse.Namespace) -> int:
    def apply(found, today):
        _text_change(found, "forgotten", "Forgotten", args.because, today)
        return [f"m:{found[0].handle}\tforgotten"]
    return _act(args, [args.handle], apply, "forget", args.because)


def _two(args: argparse.Namespace, first: str, second: str, name: str, apply) -> int:
    if first.removeprefix("m:") == second.removeprefix("m:"):
        print(f"mem: {name} needs two different memories.", file=sys.stderr)
        return 2
    return _act(args, [first, second], apply, name)


def cmd_supersede(args: argparse.Namespace) -> int:
    def apply(found, today):
        old, new = found
        records.update(old, today, status="superseded", superseded_by=new.handle)
        return [f"m:{old.handle}\tsuperseded by m:{new.handle}"]
    return _two(args, args.old, args.new, "supersede", apply)


def cmd_merge(args: argparse.Namespace) -> int:
    def apply(found, today):
        keep, drop = found
        records.update(drop, today, status="superseded", superseded_by=keep.handle)
        changes: dict[str, Any] = {"observed": keep.observed + drop.observed}
        if drop.body.strip():
            changes["body"] = _with_note(keep.body, f"Merged from m:{drop.handle} on {today.isoformat()}:", drop.body)
        updated = records.update(keep, today, **changes)
        return [f"m:{updated.handle}\tobserved {updated.observed}, merged m:{drop.handle}"]
    return _two(args, args.keep, args.drop, "merge", apply)


def cmd_promote(args: argparse.Namespace) -> int:
    args.is_global = False
    found = []
    for handle in args.handles:
        got = _memory_of(args, [handle])
        if got is None:
            return 2
        found.append(got[0])
    print('Draft for: mem remember --global --kind lesson --claim "\u2026"')
    for m in found:
        print(f"m:{m.handle}\t{' '.join(m.claim.split())}")
        if m.context:
            print(f"  context: {' '.join(m.context.split())}")
    print("Rewrite the claim in general terms, with no name of a project, system, client or person, "
          "before you run it.")
    return 0


def _curation_folders(args: argparse.Namespace) -> list[tuple[str, Path | None]]:
    folders = _memory_folders(args)
    if args.all:
        return folders
    return [f for f in folders if (f[0] == "global") == args.is_global]


def _loaded(args: argparse.Namespace) -> list[tuple[str, Path | None, list[records.Memory]]]:
    out = []
    for scope, folder in _curation_folders(args):
        loaded = records.load_memories(folder, scope)
        for m in loaded:
            if m.error is not None:
                print(f"mem: skipped {m.path}: {m.error}", file=sys.stderr)
        out.append((scope, folder, loaded))
    return out


def _flat(text: str) -> str:
    return " ".join(text.split())  # a hand-edited tab or newline must not add a column


def cmd_memories(args: argparse.Namespace) -> int:
    today = datetime.date.today()
    shown = [m for _, _, loaded in _loaded(args) for m in loaded
             if m.error is None and (args.kind is None or m.kind == args.kind)
             and (args.dead or records.is_live(m, today))]
    shown.sort(key=lambda m: (m.kind != "state", -(m.created or datetime.date.min).toordinal(), m.handle))
    for m in shown:
        dead = _memory_status(m, today)
        created = m.created.isoformat() if m.created else "undated"
        print(f"m:{m.handle}\t[{m.kind}, observed {m.observed}, {created}{', ' + dead if dead else ''}]\t{_flat(m.claim)}")
    return 0


_STALE_DAYS = 90
_FREQUENT = 3
CURATED = ".curated"


def cmd_curate(args: argparse.Namespace) -> int:
    today = datetime.date.today()
    scopes = _loaded(args)
    if args.done:
        store = _optional_store(args)
        for scope, folder, _ in scopes:
            if folder is None or not folder.is_dir():
                continue
            if _read_only_store(store, folder.resolve()):
                print(_READ_ONLY_PROJECT if scope == "project" else _READ_ONLY_MEMORIES, file=sys.stderr)
                return 2
            try:
                (folder / CURATED).write_text(today.isoformat() + "\n", encoding="utf-8")
            except OSError as exc:
                print(f"mem: {exc}", file=sys.stderr)
                return 2
        return 0
    every = [m for _, _, loaded in scopes for m in loaded if m.error is None]
    live = [m for m in every if records.is_live(m, today)]
    cutoff = today - datetime.timedelta(days=_STALE_DAYS)
    out: list[str] = []
    same = [pair for _, _, loaded in scopes for pair in records.pairs(loaded, today, tokenize=tokenize)]
    same.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    if same:
        out.append("same or opposite? (decide: mem merge <keep> <drop>, or keep both and say so in the body)")
        for a, b, _ in same:
            out += [f"  m:{a.handle}  {_flat(a.claim)}", f"  m:{b.handle}  {_flat(b.claim)}"]
    expired = [m for m in every if m.status == "active" and m.valid_until is not None and m.valid_until < today]
    if expired:
        out.append("expired (decide: mem forget <h>, or mem remember again with a new date)")
        out += [f"  m:{m.handle}  valid until {m.valid_until.isoformat()}  {_flat(m.claim)}" for m in expired]
    frequent = [m for m in live if m.observed >= _FREQUENT]
    if frequent:
        out.append(f"seen {_FREQUENT} times or more: general enough for a note? (mem promote <h>)")
        out += [f"  m:{m.handle}  observed {m.observed}  {_flat(m.claim)}" for m in frequent]
    stale = [m for m in live if m.kind != "state" and m.created is not None and m.created <= cutoff
             and m.observed == 1 and m.last_observed is None]
    if stale:
        out.append(f"not confirmed in {_STALE_DAYS} days (decide: mem confirm <h> or mem forget <h>)")
        out += [f"  m:{m.handle}  {m.created.isoformat()}  {_flat(m.claim)}" for m in stale]
    if out:
        print("\n".join(out))
    return 0


_TEMPLATES = Path(__file__).resolve().parent / "templates"


def cmd_init(args: argparse.Namespace) -> int:
    folder = Path(args.folder).expanduser()
    if folder.exists() and not folder.is_dir():
        print(f"mem: {folder} is not a folder", file=sys.stderr)
        return 2
    if folder.is_dir() and any(p.name not in _INIT_ALLOWED for p in folder.iterdir()):
        print(f"mem: {folder} is not empty and is not a store", file=sys.stderr)
        return 2
    if (folder / records.STORE_MARKER).is_file():
        print(folder)
        return 0
    if any((folder / n).exists() for n in ("literature", "knowledge", "research", "topics.yaml")):
        print(f"mem: {folder} already holds a store without mem-store.yaml; it stays read-only "
              "(add the file by hand only if you own it and mean to write to it).", file=sys.stderr)
        return 2
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("literature", "knowledge", "research", records.GLOBAL_DIR):
            (folder / name).mkdir(exist_ok=True)
        if not (folder / "templates").exists():
            shutil.copytree(_TEMPLATES, folder / "templates")
        for name, text in ((records.STORE_MARKER, "format: 1\n"),
                           ("topics.yaml", "notes: {description: General notes}\n")):
            if not (folder / name).exists():
                (folder / name).write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(folder)
    return 0


SIMILAR_LIMIT = 3


def _read_body(source: str) -> str:
    """The text of a `--body-file` (`-` is standard input); NewNoteError when it cannot be a body."""
    try:
        if source == "-":
            if sys.stdin.isatty():
                raise NewNoteError("--body-file - needs the body on standard input, not a terminal")
            body = sys.stdin.read().removeprefix("\ufeff").replace("\r\n", "\n")
        else:
            body = _read_text(Path(source))
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        raise NewNoteError(f"cannot read the body: {exc}") from exc
    if not body.strip():
        raise NewNoteError("the body is empty")
    if body.split("\n", 1)[0].strip() == "---":
        raise NewNoteError("the body starts with a frontmatter fence: pass the text after the frontmatter")
    return body if body.endswith("\n") else body + "\n"


def cmd_new(args: argparse.Namespace) -> int:
    fields = {k: getattr(args, k) for k in _NEW_FIELDS[args.type]}
    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    try:
        body = _read_body(args.body_file) if args.body_file else None
        path = new_note(args.root, args.type, slug=args.slug, topics=topics,
                        today=datetime.date.today(), body=body, **fields)
    except (NewNoteError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    rel = path.relative_to(args.root).as_posix()
    print(rel)
    if body is not None and (found := [p for p in check(args.root) if p.path == rel]):
        print(f"check: {len(found)} problems in {rel}:", file=sys.stderr)
        for problem in found:
            print(problem, file=sys.stderr)
    query = fields.get("claim") or fields.get("title") if args.type != "research" else None
    if query and tokenize(query):
        try:
            similar = [r for r in search(args.root, query, limit=SIMILAR_LIMIT + 1) if r[0] != rel]
        except (FrontmatterError, OSError):  # the note exists; the hint is optional
            similar = []
        if similar:
            print("Similar notes exist: link them, or edit the existing note if it states the same claim.",
                  file=sys.stderr)
            for other, score, title in similar[:SIMILAR_LIMIT]:
                print(f"similar: {other}\t{score:.2f}\t{title}", file=sys.stderr)
    if args.type == "research":
        branch = f"research/{Path(rel).parent.name}"
        print(f"An investigation with its own material lives on a branch (ADR 0006): before committing, "
              f"git switch -c {branch} (uncommitted files move with you); add literature and knowledge "
              "notes on main, then merge main into it.", file=sys.stderr)
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    try:
        path, links, files = rename_note(args.root, args.note, args.new_stem)
    except (NewNoteError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    print(path.relative_to(args.root.resolve()).as_posix())
    print(f"rewrote {links} links in {files} files", file=sys.stderr)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    root = args.root
    if args.paths and not args.orphans:
        build_parser().error("PATH needs --orphans")
    if args.orphans:
        try:
            scopes = _scopes(root, args.paths)
        except ValueError as exc:
            print(f"mem: {exc}", file=sys.stderr)
            return 2
        for path in orphan_notes(root):
            if _in_scopes(path, scopes):
                print(path)
        return 0
    notes = discover_notes(root)
    try:
        topic_count = len(load_topics(root))
    except FrontmatterError:
        topic_count = 0
    chars = 0
    for note in notes:
        chars += len(note.text)
    lines = [f"store: {root} (from {getattr(args, 'root_source', None) or 'unknown'})"]
    lines += [f"{kind}: {sum(1 for n in notes if n.type == kind)}" for kind in INDEX_FOLDERS]
    for kind in ("literature", "knowledge"):
        domains = collections.Counter(n.path.parent.name for n in notes if n.type == kind)
        lines += [f"{kind}/{domain}: {domains[domain]}" for domain in sorted(domains)]
    today = datetime.date.today()
    counts = [records.load_memories(folder, scope) for scope, folder in _memory_folders(args)]
    if any(counts):
        live = sum(records.is_live(m, today) for group in counts for m in group)
        lines.insert(1, f"memories: {len(counts[0])} project, {len(counts[1])} global ({live} live)")
    script = Path(__file__).resolve().read_text(encoding="utf-8")
    lines.append(f"orphans: {len(orphan_notes(root))}")
    lines += [f"topics: {topic_count}", f"characters: {chars}", f"tokens: {chars // 4}",
              f"mem.py lines: {len(script.splitlines())}"]
    log_path = _usage_log(os.environ)
    try:
        entries = 0 if log_path is None else log_path.read_bytes().count(b"\n")
    except OSError:
        entries = 0
    lines.append(f"usage log entries: {entries}")
    print("\n".join(lines))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    queries = [args.query, *args.also]
    if not all(tokenize(q) for q in queries):
        build_parser().error("query has no searchable words: use letters or digits")
    if args.links and args.offset:
        build_parser().error("--offset cannot be used with --links")
    with_notes = args.scope != "memories"
    filters = {k: getattr(args, k) for k in ("type", "topic", "kind", "status", "confidence", "level")
               if getattr(args, k) is not None}
    corpus = None
    if with_notes:
        try:
            corpus = build_corpus(args.root, type=args.type, topic=args.topic, kind=args.kind,
                                  status=args.status, confidence=args.confidence, level=args.level)
            ranks = [rank(corpus, q, limit=len(corpus.notes)) for q in queries]
            linkeds = [linked_notes(args.root, corpus, r, args.limit) if args.links else [] for r in ranks]
        except (FrontmatterError, OSError) as exc:
            print(f"mem: cannot search: {exc}", file=sys.stderr)
            return 1
    else:
        ranks, linkeds = [[] for _ in queries], [[] for _ in queries]
    names = short_handles(args.root) if args.handles and with_notes else {}
    # memories stay out of any narrowed, paged or path-only note listing, unless they are all that was asked for
    memories: list[tuple[str, list[records.Memory]]] = []
    if args.scope != "notes" and not args.offset and not filters and (args.detail != "paths" or not with_notes):
        today = datetime.date.today()
        for scope, folder in _memory_folders(args):
            loaded = records.load_memories(folder, scope)
            for m in loaded:
                if m.error is not None:
                    print(f"mem: skipped {m.path}: {m.error}", file=sys.stderr)
            memories.append((scope, loaded))
    for query, ranked, linked in zip(queries, ranks, linkeds):
        result = ranked[args.offset:args.offset + args.limit]
        if args.also:
            print(f"== {query} ==")
        printed: list[str] = []
        for scope, loaded in memories:
            hits = records.match_memories(loaded, tokenize(query), today, tokenize=tokenize, limit=3,
                                          include_dead=args.all_memories)
            if not hits:
                continue
            if args.detail == "paths":
                print("\n".join(f"m:{m.handle}" for m in hits))
            else:
                print(f"-- memories ({scope}) --")
                print("\n".join(_memory_line(m, today) for m in hits))
            printed += [f"m:{m.handle}" for m in hits]
        if with_notes and printed and result:
            print("-- notes --")
        if not result and not printed and not args.offset:
            print("no matches", file=sys.stderr)
        terms = tokenize(query)
        weights = term_idf(corpus, terms) if corpus is not None else {}
        for note, score in result:
            print("\n".join(format_hit(note, args.detail, score=score, terms=terms, weights=weights,
                                            name=names.get(note.rel))))
        if linked and args.detail != "paths":
            print("-- linked to the results above --")
        for note, score in linked:
            print("\n".join(format_hit(note, args.detail, score=score, terms=terms, weights=weights,
                                            name=names.get(note.rel))))
        if not args.also and with_notes:  # a footer names --offset, which applies to every query at once
            _page_footer(args.offset, len(result), len(ranked))
        extra = {"links": True, "linked": [note.rel for note, _ in linked]} if args.links else {}
        if printed:
            extra["memories"] = printed
        log_usage(args.root, {"cmd": "search", "query": query, "limit": args.limit,
                              "detail": args.detail, "filters": filters,
                              "results": [note.rel for note, _ in result], **extra})
    return 0


def cmd_passages(args: argparse.Namespace) -> int:
    if not tokenize(args.query):
        build_parser().error("query has no searchable words: use letters or digits")
    try:
        notes = {n.rel for n in discover_notes(args.root) if n.type == "literature"}
    except (FrontmatterError, OSError) as exc:
        print(f"mem: cannot read passages: {exc}", file=sys.stderr)
        return 1
    path = resolve_note(args.root, args.path)  # a path or handle, like `show`
    if isinstance(path, list):
        _ambiguous(args.path, path)
        return 1
    rel = path.relative_to(args.root.resolve()).as_posix() if path else args.path
    source = source_text(args.root, rel) if rel in notes else None
    if source is None:
        print(f"mem: no source text for {args.path}: looked for a .txt in "
              f"{SOURCES_DIR}/{Path(rel).stem}/ (needs a literature note path); `mem fetch-sources {args.path}` "
              "downloads the source when it has a url, and writes a .txt only for a plain-text response "
              "or a PDF with pdftotext installed", file=sys.stderr)
        return 1
    total, found = passages(source.read_text(encoding="utf-8", errors="replace"), args.query,
                            count=args.count, words=args.words)
    if not found:
        print(f"no matching passage in {source.relative_to(args.root).as_posix()} ({total} words)", file=sys.stderr)
    else:
        print(f"source: {source.relative_to(args.root).as_posix()} ({total} words)")
        print("\n\n".join(f"== words {a}-{b} of {total} ==\n{t}" for a, b, t in found))
    log_usage(args.root, {"cmd": "passages", "path": rel, "query": args.query, "count": args.count,
                          "words": args.words, "hits": len(found)})
    return 0


def cmd_related(args: argparse.Namespace) -> int:
    path = resolve_note(args.root, args.path)
    if isinstance(path, list):
        _ambiguous(args.path, path)
        return 1
    rel = path.relative_to(args.root.resolve()).as_posix() if path else None
    try:
        corpus = build_corpus(args.root)
        groups = related(args.root, rel, limit=args.limit, corpus=corpus)
    except ValueError:
        print(f"mem: not a note: {args.path}", file=sys.stderr)
        return 1
    except (FrontmatterError, OSError) as exc:
        print(f"mem: cannot relate: {exc}", file=sys.stderr)
        return 1
    terms = tokenize(_title(next(n for n in corpus.notes if n.rel == rel)))
    weights = term_idf(corpus, terms)
    if args.unlinked_mentions:
        groups = {"mentions": unlinked_mentions(args.root, rel, corpus)}
    for relation, notes in groups.items():
        for other in notes:
            first, *rest = format_hit(other, args.detail, terms=terms, weights=weights)
            print("\n".join([f"{relation}\t{first}", *rest]))
    print(" · ".join(f"{relation}: {len(notes)}" for relation, notes in groups.items()), file=sys.stderr)
    return 0


def cmd_search_eval(args: argparse.Namespace) -> int:
    try:
        outcome = search_eval(args.root)
    except (FrontmatterError, OSError) as exc:
        print(f"mem: cannot evaluate search: {exc}", file=sys.stderr)
        return 1
    if outcome is None:
        print(f"mem: {_EVAL_FILE} not found", file=sys.stderr)
        return 0
    misses, found, expected, reciprocal = outcome
    for miss in misses:
        print(miss)
    recall = found / expected if expected else 1.0
    print(f"recall@10: {recall:.2f} ({found}/{expected})")
    mrr = reciprocal / expected if expected else 1.0
    print(f"MRR@10: {mrr:.3f}")
    if args.min is not None:
        return 1 if recall < args.min else 0
    if recall < RECALL_TRIGGER or mrr < MRR_TRIGGER:
        print(f"search-eval: below the revisit trigger (recall@10 {RECALL_TRIGGER:.2f}, MRR@10 {MRR_TRIGGER:.3f}): "
              "see C-6 in docs/requirements.md", file=sys.stderr)
        return 1
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    today = args.today or datetime.date.today()
    for line in due_requirements(args.root, today) + due_retests(args.root, today) + due_rereads(args.root, today):
        print(line)
    return 0


def cmd_fetch_sources(args: argparse.Namespace) -> int:
    if args.text_only:
        lines, ok = build_missing_texts(args.root, args.paths)
    else:
        lines, ok = fetch_sources(args.root, args.paths, force=args.force)
    print("\n".join(lines))
    return 0 if ok else 1


def _today(value: str) -> datetime.date:
    if (date := _iso_date(value)) is None:
        raise argparse.ArgumentTypeError("use a real date as YYYY-MM-DD")
    return date


def _offset(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return n


def _limit(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


_KINDS = ("paper", "book", "article", "web", "talk", "repo", "dataset")
_CONFIDENCE = ("high", "medium", "low")
_ORIGINS = ("literature", "research", "experience")
_NEW_FIELDS = {
    "literature": ("title", "author", "year", "kind", "level", "url"),
    "knowledge": ("claim", "confidence", "level", "origin"),
    "research": ("title", "question"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mem", description="Memory engine: search and read a store of notes.")
    parser.add_argument("--root", default=None, help="store folder (default: $MEM_STORE, then the config file)")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="validate the hub rules")
    check_parser.add_argument("paths", nargs="*", metavar="PATH", help="print only problems in these notes or folders")
    check_parser.set_defaults(func=cmd_check)
    index_parser = sub.add_parser("index", help="regenerate the index blocks in the folder READMEs")
    index_parser.set_defaults(func=cmd_index)
    find_parser = sub.add_parser("find", help="list notes matching all filters")
    search_parser = sub.add_parser("search", help="rank notes by BM25 relevance to a query")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=_limit, default=10)
    search_parser.add_argument("--offset", type=_offset, default=0, help="skip the first N results (default: 0)")
    search_parser.add_argument("--also", action="append", default=[], metavar="QUERY",
                               help="another query over the same corpus (repeatable); each list is headed `== <query> ==`")
    search_parser.add_argument("--links", action="store_true",
                               help="also list up to 10 notes linked to or from the first 10 printed results")
    search_parser.add_argument("--scope", choices=("all", "notes", "memories"), default="all",
                               help="what to search: notes and memories (default), only notes, only memories")
    search_parser.add_argument("--all-memories", action="store_true",
                               help="also match refuted, superseded and expired memories")
    search_parser.set_defaults(func=cmd_search)
    for filtered in (find_parser, search_parser):
        filtered.add_argument("--type", choices=INDEX_FOLDERS)
        filtered.add_argument("--topic")
        filtered.add_argument("--kind", choices=_KINDS)
        filtered.add_argument("--status", choices=("idea", "active", "paused", "done", "abandoned"))
        filtered.add_argument("--confidence", choices=_CONFIDENCE)
        filtered.add_argument("--level", choices=LEVELS)
        filtered.add_argument("--handles", action="store_true",
                              help="print a short handle in place of each path (accepted wherever a note is named)")
        filtered.add_argument("--detail", choices=DETAILS, default="titles",
                              help="per result: path only, title, key facts, a matching line, or the lead section")
    find_parser.add_argument("--limit", type=_limit, default=50, help="print at most N notes (default: 50)")
    find_parser.add_argument("--offset", type=_offset, default=0, help="skip the first N notes (default: 0)")
    find_parser.set_defaults(func=cmd_find)
    passages_parser = sub.add_parser("passages", help="print the passages of a note's local source that best match")
    passages_parser.add_argument("path", metavar="PATH")
    passages_parser.add_argument("query")
    passages_parser.add_argument("--count", type=_limit, default=5, help="passages to print (default: 5)")
    passages_parser.add_argument("--words", type=_limit, default=500, help="words per passage (default: 500)")
    passages_parser.set_defaults(func=cmd_passages)
    related_parser = sub.add_parser("related", help="list a note's links, backlinks and most similar notes")
    related_parser.add_argument("path", metavar="PATH")
    related_parser.add_argument("--limit", type=_limit, default=5, help="print at most N similar notes (default: 5)")
    related_parser.add_argument("--detail", choices=DETAILS, default="titles",
                                help="per result: path only, title, key facts, a matching line, or the lead section")
    related_parser.add_argument("--unlinked-mentions", action="store_true",
                                help="print only the notes that name this one in their text without linking to it")
    related_parser.set_defaults(func=cmd_related)
    show_parser = sub.add_parser("show", aliases=["read"], help="print chosen sections of notes")
    show_parser.add_argument("paths", nargs="+", metavar="PATH")
    show_parser.add_argument("--section", action="append", help="a `## ` section to print (repeatable)")
    show_parser.add_argument("--outline", action="store_true", help="list headings with line numbers")
    show_parser.add_argument("--ranges", action="store_true",
                             help="with --outline: print start-end lines and word count per heading")
    show_parser.set_defaults(func=cmd_show)
    topics_parser = sub.add_parser("topics", help="print the topic tree with note counts")
    topics_parser.add_argument("topic", nargs="?", metavar="ID", help="print only this topic's subtree")
    topics_parser.set_defaults(func=cmd_topics)
    stats_parser = sub.add_parser("stats", help="print note, topic and size counts")
    stats_parser.add_argument("--orphans", action="store_true", help="list notes no other file links to")
    stats_parser.add_argument("paths", nargs="*", metavar="PATH", help="with --orphans: only these notes or folders")
    stats_parser.set_defaults(func=cmd_stats)
    review_parser = sub.add_parser("review", help="list concrete requirements due for review")
    review_parser.add_argument("--today", type=_today, default=None, help="YYYY-MM-DD (default: today)")
    review_parser.set_defaults(func=cmd_review)
    fetch_parser = sub.add_parser("fetch-sources", help="download literature note urls into .sources/")
    fetch_parser.add_argument("paths", nargs="*", metavar="PATH")
    fetch_parser.add_argument("--force", action="store_true", help="refetch notes already cached")
    fetch_parser.add_argument("--text-only", action="store_true",
                              help="no download: write source.txt in cached folders that hold no .txt")
    fetch_parser.set_defaults(func=cmd_fetch_sources)
    eval_parser = sub.add_parser("search-eval", help="measure search recall on docs/search-eval.md")
    eval_parser.add_argument("--min", type=float, help="exit 1 when recall@10 is below this (replaces the default revisit triggers)")
    eval_parser.set_defaults(func=cmd_search_eval)
    rename_parser = sub.add_parser("rename", help="rename a note in its folder and rewrite the links to it")
    rename_parser.add_argument("note", metavar="NOTE")
    rename_parser.add_argument("new_stem", metavar="NEW-STEM", help="the new file name without .md")
    rename_parser.set_defaults(func=cmd_rename)
    new_parser = sub.add_parser("new", help="create a note from its template")
    new_sub = new_parser.add_subparsers(dest="type", required=True)
    for note_type, flags in {
        "literature": {"title": {}, "author": {}, "year": {"type": int}, "kind": {"choices": _KINDS},
                       "level": {"choices": LEVELS},
                       "url": {}, "topics": {}, "slug": {}},
        "knowledge": {"slug": {}, "claim": {}, "topics": {}, "confidence": {"choices": _CONFIDENCE},
                      "level": {"choices": LEVELS},
                      "origin": {"choices": _ORIGINS}},
        "research": {"slug": {}, "title": {}, "question": {}, "topics": {}},
    }.items():
        type_parser = new_sub.add_parser(note_type)
        type_parser.add_argument("--body-file", metavar="PATH",
                                 help="text (or - for standard input) that replaces the template body")
        for flag, opts in flags.items():
            type_parser.add_argument(f"--{flag}", required=True, **opts)
        type_parser.set_defaults(func=cmd_new)
    remember_parser = sub.add_parser("remember", help="write a memory in the project or, with --global, in the global folder")
    remember_parser.add_argument("--kind", required=True, choices=records.KINDS)
    remember_parser.add_argument("--claim", required=True)
    remember_parser.add_argument("--body-file", metavar="PATH", help="text (or - for standard input); may be empty")
    remember_parser.add_argument("--context")
    remember_parser.add_argument("--valid-until", type=_today, default=None, metavar="YYYY-MM-DD")
    remember_parser.add_argument("--source", action="append", default=[], metavar="URL_OR_PATH")
    remember_parser.add_argument("--global", dest="is_global", action="store_true")
    remember_parser.add_argument("--force", action="store_true", help="write even when a memory has the same claim")
    remember_parser.set_defaults(func=cmd_remember)
    index_cmd = sub.add_parser("session-index", help="print the text that opens a session: usage rules and counts")
    index_cmd.add_argument("--hook", action="store_true",
                           help="read the hook's JSON from standard input (its cwd locates the project) and log the call")
    index_cmd.add_argument("--list", type=int, default=0, metavar="N",
                           help="also list up to N of the project's newest memories")
    index_cmd.set_defaults(func=cmd_session_index)
    signal_cmd = sub.add_parser("signal", help="print the records related to a brief read from standard input")
    signal_cmd.add_argument("--hook", action="store_true",
                            help="read a PreToolUse hook's JSON from standard input and print the brief with the signal appended")
    signal_cmd.set_defaults(func=cmd_signal)
    def memory_command(name: str, help_text: str, *handles: str, because: bool = False):
        cmd = sub.add_parser(name, help=help_text)
        for h in handles:
            cmd.add_argument(h, metavar="m:HANDLE")
        if because:
            cmd.add_argument("--because", metavar="TEXT", help="the reason, appended to the memory's body")
        cmd.add_argument("--global", dest="is_global", action="store_true",
                         help="act on the global memory when the handle exists in both scopes")
        return cmd

    for name, text in (("confirm", "count one more observation of a memory"),
                       ("observe", "alias of confirm")):
        memory_command(name, text, "handle").set_defaults(func=cmd_confirm)
    memory_command("refute", "mark a memory refuted", "handle", because=True).set_defaults(func=cmd_refute)
    memory_command("forget", "mark a memory forgotten", "handle", because=True).set_defaults(func=cmd_forget)
    memory_command("supersede", "mark OLD as superseded by NEW", "old", "new").set_defaults(func=cmd_supersede)
    memory_command("merge", "add DROP's count and body to KEEP and supersede DROP", "keep", "drop").set_defaults(func=cmd_merge)
    promote_parser = sub.add_parser("promote", help="print a draft of a global memory from project memories")
    promote_parser.add_argument("handles", nargs="+", metavar="m:HANDLE")
    promote_parser.set_defaults(func=cmd_promote)
    memories_parser = sub.add_parser("memories", help="list memories, newest first")
    curate_parser = sub.add_parser("curate", help="list what needs a decision: pairs, expired, frequent, unconfirmed")
    for lister in (memories_parser, curate_parser):
        scope_group = lister.add_mutually_exclusive_group()
        scope_group.add_argument("--global", dest="is_global", action="store_true", help="the global memories only")
        scope_group.add_argument("--all", action="store_true", help="project and global memories")
    memories_parser.add_argument("--kind", choices=records.KINDS)
    memories_parser.add_argument("--dead", action="store_true", help="also list refuted, superseded, forgotten and expired")
    memories_parser.set_defaults(func=cmd_memories)
    curate_parser.add_argument("--done", action="store_true", help="record today's date as the last pass")
    curate_parser.set_defaults(func=cmd_curate)
    init_parser = sub.add_parser("init", help="make a folder a writable store")
    init_parser.add_argument("folder", metavar="FOLDER")
    init_parser.set_defaults(func=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "read":
        args.command = "show"
    if args.command == "init":
        return args.func(args)
    if args.command in _NO_STORE_NEEDED:  # a project memory needs no store; a missing one is an error only where used
        root = resolve_root(args.root, os.environ)
        args.root = root
        return args.func(args)
    root = resolve_root(args.root, os.environ)
    if args.command == "search" and args.scope == "memories" and (root is None or not root.is_dir()):
        args.root = None  # memories need no store; only a project or a global folder
        return args.func(args)
    if args.command == "show" and all(a.startswith("m:") for a in args.paths) and (root is None or not root.is_dir()):
        args.root = None
        return args.func(args)
    if root is None:
        print('mem: no store is set. Enable the memory plugin and set its "store" option, '
              "or pass --root <folder>, or set MEM_STORE.", file=sys.stderr)
        return 2
    if root.exists() and not root.is_dir():
        print(f"mem: the store is not a folder: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"mem: the store folder does not exist: {root}", file=sys.stderr)
        return 2
    if args.command in _WRITE_COMMANDS and not records.store_is_writable(root):
        print(f"mem: {args.command} writes to the store, which is read-only: it has no mem-store.yaml "
              '(create a store with "mem init").', file=sys.stderr)
        return 2
    args.root_source = store_source(args.root, os.environ)
    args.root = root
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
