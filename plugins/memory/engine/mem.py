#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.15"  # an upper bound: a newer Python may have no prebuilt pyyaml yet
# dependencies = ["pyyaml"]
# ///
"""Memory engine: parsing primitives and the mem commands."""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import datetime
import hashlib
import html.parser
import http.client
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

import auto_state
import capture_state
import check as check_rules
import corroborate
import digest
import handoff
import index as index_files
import notes as note_files
import project_syntheses
import records
import research_checks
import rules
import safe_io
import session_notices
import settle
import settle_state
import shortcheck
import store_git
import syntheses
import yaml
from check import (
    LEVELS,
    MAX_KNOWLEDGE_NAME,
    NAME_PATTERNS,
    OPTIONAL_FIELDS,
    SCHEMAS,
    Problem,
    check,
    due_requirements,
    due_rereads,
    due_retests,
    instruction_word,
    invalid_changed,
    orphan_notes,
)
from index import (
    INDEX_FOLDERS,
    apply_index,
    index_targets,
)
from notes import (
    FrontmatterError,
    ancestors,
    descendants,
    discover_notes,
    load_topics,
    load_yaml,
    root_of,
    root_topics,
    slugify,
    split_frontmatter,
)
from records import tokenize

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

    from notes import (
        Note,
    )

# Names that live in check, notes and index; callers may still read them from `mem`.
_MOVED = frozenset({
    "BASELINE_HEADING",
    "EXPERIMENT_DIRS",
    "HubLoader",
    "INDEX_END",
    "INDEX_START",
    "IndexTarget",
    "MAX_FILE_BYTES",
    "MODEL_SPECIFIC_ROOT",
    "Note",
    "REQUIRED_HEADINGS",
    "REREAD_DAYS",
    "RESERVED_TOPIC",
    "RETEST_DAYS",
    "RULES",
    "Validator",
    "_BACKTICKS",
    "_BaseLoader",
    "_CODE_SPAN",
    "_CONCRETE_ID",
    "_DATE",
    "_DISPUTE_KEYS",
    "_DOMAIN_PURPOSE",
    "_DROPPED_TAGS",
    "_FENCE",
    "_IMPERATIVES",
    "_INDEX_COLUMNS",
    "_INSTRUCTION_FIX",
    "_INTENT_ID",
    "_LINK",
    "_LOCAL_DIRS",
    "_LONG_NAME_FIX",
    "_MONTH",
    "_NAME_FIX",
    "_PART_OF",
    "_REFDEF",
    "_REQUIREMENTS",
    "_SCHEME",
    "_TOPIC_ID",
    "_UNTRACKED_DIRS",
    "_authors",
    "_blank",
    "_cell",
    "_date",
    "_disputed",
    "_domain_notes",
    "_enum",
    "_handle",
    "_handle_list",
    "_handle_value",
    "_has_committable_file",
    "_heading_problems",
    "_in_fence",
    "_index_cells",
    "_index_row",
    "_indexable",
    "_is_hidden",
    "_is_index_readme",
    "_iso_date",
    "_markdown_files",
    "_month",
    "_no_duplicate_keys",
    "_nonempty_dir",
    "_note_files",
    "_parent",
    "_part_hash",
    "_part_of",
    "_read_note",
    "_read_text",
    "_relative_links",
    "_requirement_rows",
    "_rows_table",
    "_split_cells",
    "_starts_with_author",
    "_string",
    "_strip_code",
    "_subtopics",
    "_target_spans",
    "_topic_line",
    "_topics",
    "_url",
    "_visible",
    "_with_index",
    "_yaml_problem",
    "_year",
    "key_line",
    "leaf_topics",
    "render_domain_index",
    "render_index",
    "rule_consistency",
    "rule_domain",
    "rule_file_size",
    "rule_flat",
    "rule_handles",
    "rule_index_fresh",
    "rule_links",
    "rule_names",
    "rule_placeholders",
    "rule_requirements",
    "rule_schema",
    "rule_supersession",
    "rule_syntheses",
    "rule_topics_file",
    "rule_topics_used",
    "safe_load",
})


def __getattr__(name: str) -> object:
    if name in _MOVED:
        for module in (check_rules, note_files, index_files):
            if hasattr(module, name):
                return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


logger = logging.getLogger(__name__)

_KEY_VALUE_CELLS = 2  # a two-cell table row: name and value
_MIN_TITLE_WORDS = 4  # a title shorter than this is too generic to match as a phrase
_SECTION_LEVEL = 2  # the heading level of a `## ` section
_NOTE_PATH_PARTS = 3  # `<folder>/<domain>/<file>.md`
_CLAIM_PREVIEW_CHARS = 160  # a claim longer than this is cut in a listing
_CURATE_LINE_WORDS = 3  # `merge m:<keep> m:<drop>` and `attach <note> s:<h>#<section>`
_SETTLE_LOG_CELLS = 3  # `<section> | <unit> | add|remove <target>`
_SETTLE_ACTION_WORDS = 2  # `add|remove <target>`
_SPARSE_HITS = 3  # fewer hits than this makes a search look for more


_WRITE_COMMANDS = ("new", "note", "rename", "unify", "index", "fetch-sources", "import")
_SYNTHESIS_WRITES = (
    "new",
    "add",
    "edit",
    "append",
    "attach",
    "rename",
    "remove",
    "detach",
    "topics",
    "refs",
)
_NO_STORE_NEEDED = (
    "remember",
    "observe",
    "confirm",
    "refute",
    "supersede",
    "merge",
    "forget",
    "promote",
    "distinct",
    "restore",
    "triage",
    "memory",
    "memories",
    "curate",
    "settle",
    "session-index",
    "rules",
    "compact-log",
    "signal",
    "projects",
    "project-synthesis",
)


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


NO_STORE = (
    'mem: no store is set. Run "mem init" to create the default store, or set the plugin\'s "store" option, '
    "or pass --root <folder>, or set MEM_STORE."
)


def _default_store(env: Mapping[str, str]) -> Path | None:
    """The default store when its folder exists."""
    path = records.default_store(env)
    return path if path is not None and path.is_dir() else None


def store_source(cli_root: str | None, env: Mapping[str, str]) -> str | None:
    """Where the store path comes from: --root, MEM_STORE, the config file or the default store."""
    if cli_root:
        return "--root"
    if _env_value(env, "MEM_STORE"):
        return "MEM_STORE"
    if _config_store(env):
        return "config file"
    if _default_store(env) is not None:
        return "default"
    return None


def resolve_root(cli_root: str | None, env: Mapping[str, str]) -> Path | None:
    """The store folder by precedence --root, MEM_STORE, config file, default store; not checked for existence."""
    source = store_source(cli_root, env)
    if source is None:
        return None
    if source == "default":
        return _default_store(env)
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


# --- find and new --------------------------------------------------------------


_FIND_ONLY_TYPE = {"kind": "literature", "status": "research", "confidence": "knowledge"}
_FIND_TYPES = {"level": ("literature", "knowledge")}


def _unknown_topic_message(topic: str, known: dict) -> str:
    """Say what to try instead: ids sharing a word with the guess, and free-text search."""
    words = set(topic.lower().split("-"))
    close = sorted(t for t in known if words & set(t.split("-")) or topic.lower() in t)
    hint = f"close ids: {', '.join(close)}; " if close else ""
    return f'unknown topic {topic}: {hint}for free text use: mem search "{topic.replace("-", " ")}" (ids: topics.yaml)'


class NoteFilters(TypedDict, total=False):
    """The keyword filters of `_matching_notes`, for the functions that pass them on."""

    type: str | None
    topic: str | None
    kind: str | None
    status: str | None
    confidence: str | None
    level: str | None
    superseded: bool


def _search_types(wanted: dict[str, str | None], type_filter: str | None) -> set[str]:
    """The note types left after the type filter and the type each other filter implies."""
    types: set[str] = {type_filter} if type_filter else set(INDEX_FOLDERS)
    for key, value in wanted.items():
        if value is not None:
            types &= set(_FIND_TYPES[key]) if key in _FIND_TYPES else {_FIND_ONLY_TYPE[key]}
    return types


def _search_in_scope(meta: dict, scope: set[str] | None) -> bool:
    """Whether a note lists a topic of `scope`; every note is in scope when there is none."""
    if scope is None:
        return True
    listed = meta.get("topics")
    return isinstance(listed, list) and bool(
        scope.intersection(t for t in listed if isinstance(t, str))
    )


def _search_matches(
    note: Note,
    types: set[str],
    wanted: dict[str, str | None],
    scope: set[str] | None,
    superseded: bool,
) -> bool:
    """Whether a parsed note passes the type, superseded, field and topic filters."""
    meta = note.meta
    if note.type not in types:
        return False
    if not superseded and meta.get("superseded_by") is not None:
        return False
    if any(v is not None and meta.get(k) != v for k, v in wanted.items()):
        return False
    return _search_in_scope(meta, scope)


def _matching_notes(root: Path, **filters: Unpack[NoteFilters]) -> list[Note]:
    """Parsable typed notes matching every filter; unparsable ones are skipped with a warning.

    A note with `superseded_by` is left out unless `superseded`."""
    wanted = {
        "kind": filters.get("kind"),
        "status": filters.get("status"),
        "confidence": filters.get("confidence"),
        "level": filters.get("level"),
    }
    types = _search_types(wanted, filters.get("type"))
    topic = filters.get("topic")
    known = load_topics(root)
    if topic and topic not in known:
        raise FrontmatterError(_unknown_topic_message(topic, known))
    scope = descendants(known, topic) if topic else None
    superseded = filters.get("superseded") or False
    result = []
    for note in discover_notes(root):
        if note.error is not None or not isinstance(note.meta, dict):
            print(
                f"mem: skipping {note.rel}: {note.error or 'frontmatter is not a mapping'}",
                file=sys.stderr,
            )
            continue
        if _search_matches(note, types, wanted, scope, superseded):
            result.append(note)
    return result


def _title(note: Note) -> str:
    return str(note.meta.get("claim" if note.type == "knowledge" else "title", ""))


def find(root: Path, **filters: Unpack[NoteFilters]) -> list[tuple[str, str]]:
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


def _fields(note: Note) -> dict[str, str]:
    """Searchable text per field: the title (`claim` for knowledge notes), and the body with topics and authors."""
    meta = note.meta
    extra = [
        " ".join(str(v) for v in meta[f])
        for f in ("topics", "authors")
        if isinstance(meta.get(f), list)
    ]
    return {"title": _title(note), "body": "\n".join([*extra, note.body])}


@dataclass(frozen=True)
class Corpus:
    """Notes with per-field term counts and lengths, so many queries can be ranked without re-reading notes."""

    notes: list[Note]
    counts: list[dict[str, collections.Counter]]
    lengths: list[dict[str, int]]
    average: dict[str, float]


def build_corpus(root: Path, **filters: Unpack[NoteFilters]) -> Corpus:
    """Read and tokenize the notes matching `filters` once."""
    notes = _matching_notes(root, **filters)
    counts = [
        {f: collections.Counter(tokenize(text)) for f, text in _fields(n).items()} for n in notes
    ]
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
    for note, fields, length in zip(corpus.notes, corpus.counts, corpus.lengths, strict=False):
        score = 0.0
        for term in terms:
            tf = sum(
                FIELD_WEIGHTS[f]
                * fields[f][term]
                / (1 - FIELD_B[f] + FIELD_B[f] * length[f] / corpus.average[f])
                for f in FIELD_WEIGHTS
                if fields[f].get(term) and corpus.average[f]
            )
            if tf:
                score += idf[term] * tf * (BM25_K1 + 1) / (tf + BM25_K1)
        if score > 0:
            scored.append((note, score))
    scored.sort(key=lambda r: (-r[1], r[0].rel))
    return scored[:limit]


def search(
    root: Path, query: str, *, limit: int = 10, **filters: Unpack[NoteFilters]
) -> list[tuple[str, float, str]]:
    """(rel, score, title) of the best BM25F matches, best first; notes scoring 0 are omitted."""
    return [
        (n.rel, score, _title(n))
        for n, score in rank(build_corpus(root, **filters), query, limit=limit)
    ]


LINK_SEEDS = LINK_EXTRA = 10


def linked_notes(
    root: Path, corpus: Corpus, ranked: list[tuple[Note, float]], shown: int
) -> list[tuple[Note, float]]:
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
    for note, score in ranked[
        : min(shown, LINK_SEEDS)
    ]:  # seeds are printed results, so "above" holds
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
        if (
            not in_table
            or len(cells) != _KEY_VALUE_CELLS
            or not cells[0]
            or set(cells[0]) <= set("-: ")
        ):
            continue
        wanted = [
            os.path.normpath(f"docs/{m.split('#')[0]}").replace(os.sep, "/")
            for m in _MD_LINK.findall(cells[1])
        ]
        rows.append((number, cells[0].strip("`"), wanted))
    return rows


RELATIONS = ("links-to", "linked-from", "similar")


def _link_targets(root: Path, note: Note) -> set[str]:
    """Hub-relative paths the note links to (a folder link means its README.md), as `orphan_notes` resolves them."""
    targets = set()
    for _, _, file_part in check_rules._relative_links(note.body, refs=True):
        target = os.path.normpath(root / Path(note.rel).parent / file_part)
        if Path(target).is_dir():
            target = os.path.join(target, "README.md")
        targets.add(Path(os.path.relpath(target, root)).as_posix())
    return targets


def related(
    root: Path, rel: str, *, limit: int = 5, corpus: Corpus | None = None
) -> dict[str, list[Note]]:
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
    similar = [
        n for n, _ in rank(corpus, _title(note), limit=limit + len(seen)) if n.rel not in seen
    ]
    return {
        "links-to": sorted(links_to, key=lambda n: n.rel),
        "linked-from": sorted(linked_from, key=lambda n: n.rel),
        "similar": similar[:limit],
    }


def _mention_pattern(note: Note) -> re.Pattern[str] | None:
    """Regex for text that names `note` without linking it: its title as a phrase (4+ words), and for a
    literature note also `Surname ... YEAR` (first author's last word, case-sensitive, within 40 characters)."""
    words = re.findall(r"\w+", _title(note))
    parts = (
        [r"(?i:\b" + r"\W+".join(map(re.escape, words)) + r"\b)"]
        if len(words) >= _MIN_TITLE_WORDS
        else []
    )
    authors = note.meta.get("authors")
    if (
        note.type == "literature"
        and isinstance(authors, list)
        and authors
        and str(authors[0]).split()
    ):
        surname = str(authors[0]).split()[-1]
        parts.append(
            rf"\b{re.escape(surname)}\b.{{0,40}}\b{re.escape(str(note.meta.get('year')))}\b"
        )
    return re.compile("|".join(parts), re.DOTALL) if parts else None


def unlinked_mentions(root: Path, rel: str, corpus: Corpus) -> list[Note]:
    """Typed notes whose body names `rel`'s note (see `_mention_pattern`) without linking to it, by path.

    Markdown links are removed before looking, so the label of a link to another note is not a mention."""
    note = next((n for n in corpus.notes if n.rel == rel), None)
    if note is None:
        raise ValueError(f"not a note: {rel}")
    pattern = _mention_pattern(note)
    if pattern is None:
        return []
    return sorted(
        (
            n
            for n in corpus.notes
            if n.rel != rel
            and pattern.search(check_rules._LINK.sub("", n.body))
            and rel not in _link_targets(root, n)
        ),
        key=lambda n: n.rel,
    )


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


class NoteFormatError(ValueError):
    """A note file that a command cannot edit as it is."""


_HEADING = re.compile(r"^(#{1,4})[ \t]+\S")


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(0-based index, level, text) of each Markdown heading outside fenced code."""
    return [
        (i, len(h.group(1)), line)
        for i, (line, fenced) in enumerate(zip(lines, check_rules._in_fence(lines), strict=False))
        if not fenced and (h := _HEADING.match(line))
    ]


def _sections(lines: list[str], wanted: list[str]) -> list[str]:
    """Requested `## ` sections in the note's order, then a message per absent one."""
    h2 = [
        (i, line[2:].strip().casefold())
        for i, level, line in _headings(lines)
        if level == _SECTION_LEVEL
    ]
    keys = {w.strip().casefold() for w in wanted}
    out: list[str] = []
    seen: set[str] = set()
    for n, (start, key) in enumerate(h2):
        if key in keys:
            seen.add(key)
            end = h2[n + 1][0] if n + 1 < len(h2) else len(lines)
            out.extend(lines[start:end])
    out.extend(f'(no section "{w}")' for w in wanted if w.strip().casefold() not in seen)
    return out


_KEY_FACTS = {
    "knowledge": ("confidence", "updated", "level"),
    "literature": ("year", "kind", "url", "level"),
    "research": ("status", "started"),
}


def _key_facts(note_type: str, meta: Any) -> str | None:
    """One line of the fields an agent needs to judge a note; missing fields are left out."""
    if not isinstance(meta, dict) or note_type not in _KEY_FACTS:
        return None
    flag = " [disputed]" if note_type == "knowledge" and meta.get("disputed") else ""
    return (
        " \u00b7 ".join(
            f"{k}: {meta[k]}{flag if k == 'confidence' else ''}"
            for k in _KEY_FACTS[note_type]
            if meta.get(k) is not None
        )
        or None
    )


DETAILS = ("paths", "titles", "facts", "snippet", "summary")
_LEAD_SECTION = {"knowledge": "Claim", "literature": "TL;DR"}


def snippet(
    note: Note,
    terms: Sequence[str] = (),
    *,
    weights: Mapping[str, float] | None = None,
    width: int = 200,
) -> str:
    """The body line (not blank, heading, table separator or inside a fenced code block) with the highest
    total weight of its distinct `terms` (`weights`, else 1 each), earliest on ties; else the first such line.
    Whitespace is collapsed and text over `width` is cut with an ellipsis."""
    body = note.body.splitlines()
    fenced = check_rules._in_fence(body)
    lines = [
        line
        for line, inside in zip(body, fenced, strict=False)
        if not inside
        and line.strip()
        and not line.lstrip().startswith("#")
        and not set(line.strip()) <= set("|-: ")
    ]
    if not lines:
        return ""
    wanted = set(terms)
    weight = lambda line: sum(
        1.0 if weights is None else weights.get(t, 0.0) for t in wanted & set(tokenize(line))
    )
    best = max(lines, key=weight)  # max keeps the earliest tie
    text = " ".join(best.split())
    return text if len(text) <= width else text[: width - 1] + "\u2026"


class HitOptions(TypedDict, total=False):
    """The keyword options of `format_hit`."""

    score: float | None
    terms: Sequence[str]
    weights: Mapping[str, float] | None
    name: str | None


def _hit_summary(note: Note) -> list[str]:
    """The lead section of a note, indented, for the `summary` detail."""
    body = note.body.splitlines()
    lead = _LEAD_SECTION.get(note.type) or next(
        (line[2:].strip() for _, level, line in _headings(body) if level == _SECTION_LEVEL),
        None,
    )
    if lead is None:
        return []
    return ["  " + line for line in _sections(body, [lead])[1:] if line.strip()]


def _hit_disputed(note: Note) -> bool:
    return (
        note.type == "knowledge" and isinstance(note.meta, dict) and bool(note.meta.get("disputed"))
    )


def _hit_body_lines(note: Note, detail: str, options: HitOptions) -> list[str]:
    """The lines under a hit for the `snippet` and `summary` details; none for the others."""
    if detail == "summary":
        return _hit_summary(note)
    if detail == "snippet" and (
        text := snippet(note, options.get("terms", ()), weights=options.get("weights"))
    ):
        return ["  " + text]
    return []


def format_hit(note: Note, detail: str, **options: Unpack[HitOptions]) -> list[str]:
    """Output lines for one note at a `DETAILS` level; `score` is omitted from the line when None and
    `name` (a short handle) replaces the path."""
    name = options.get("name")
    score = options.get("score")
    if detail == "paths":
        return [name or note.rel]
    lines = [(name or note.rel) + ("" if score is None else f"\t{score:.2f}") + f"\t{_title(note)}"]
    if detail == "titles":
        if _hit_disputed(note):
            lines[0] += "  [disputed]"
        return lines
    if (facts := _key_facts(note.type, note.meta)) is not None:
        lines.append("  " + facts)
    lines.extend(_hit_body_lines(note, detail, options))
    return lines


def short_handles(root: Path) -> dict[str, str]:
    """Path -> the shortest prefix of its handle, cut at a hyphen and at least two words long, that no other
    handle starts with (the whole handle when none is); `resolve_note` turns it back into the note."""
    handles = {
        rel: note_files._handle(rel)
        for rel in (p.relative_to(root).as_posix() for _, p in note_files._note_files(root))
    }
    out = {}
    for rel, handle in handles.items():
        words = handle.split("-")
        out[rel] = next(
            (
                pre
                for k in range(2, len(words))
                if sum(h.startswith(pre := "-".join(words[:k])) for h in handles.values()) == 1
            ),
            handle,
        )
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
    rels = sorted(p.relative_to(root).as_posix() for _, p in note_files._note_files(root))
    for found in (
        [r for r in rels if note_files._handle(r) == name or r.removesuffix(".md") == name],
        [r for r in rels if note_files._handle(r).startswith(name) or r.startswith(name)]
        if prefix and name == arg
        else [],
    ):
        if found:
            return root / found[0] if len(found) == 1 else found
    return None


def _ambiguous(arg: str, found: list[str]) -> None:
    print(f"ambiguous: {arg} matches {len(found)} notes:", *found[:10], sep="\n", file=sys.stderr)


_CONCLUSION = {
    "knowledge": ("Claim", "Does not apply when"),
    "literature": ("TL;DR",),
    "research": ("Question",),
}


def _expand_conclusion(note_type: str, lines: list[str], sections: list[str]) -> list[str]:
    """Replace `conclusion` by the note type's lead sections that exist; other kinds get their first `## `."""
    present = [line[2:].strip() for _, level, line in _headings(lines) if level == _SECTION_LEVEL]
    lead = [
        n
        for n in _CONCLUSION.get(note_type, present[:1])
        if n.casefold() in {p.casefold() for p in present}
    ]
    return [
        x for s in sections for x in (lead or [s] if s.strip().casefold() == "conclusion" else [s])
    ]


def _outline_ranges(lines: list[str], body_line: int) -> list[str]:
    """`<start>-<end><TAB><words>w<TAB><heading>` per heading; a section ends before the next heading of its level or higher."""
    while lines and not lines[-1]:
        lines = lines[:-1]
    heads = _headings(lines)
    rows = []
    for n, (i, level, line) in enumerate(heads):
        stop = next((j for j, lv, _ in heads[n + 1 :] if lv <= level), len(lines))
        words = sum(len(x.split()) for x in lines[i:stop])
        rows.append(f"{body_line + i}-{body_line + stop - 1}\t{words}w\t{line}")
    return rows


@dataclass(frozen=True)
class _ShowMode:
    """How `show` renders a body: whole, as an outline (with line ranges) or as chosen sections."""

    sections: list[str] | None
    outline: bool
    ranges: bool


def _show_unresolved(arg: str, found: list[str] | None) -> str:
    """The block for an argument that names no single note; prints the ambiguity to stderr."""
    if found is None:
        return f"== {arg}\n(not found)"
    _ambiguous(arg, found)
    return f"== {arg}\n(ambiguous: {len(found)} notes match)"


def _show_header(note_type: str, meta: Any) -> list[str]:
    """The lines before the body: what supersedes the note, its key facts and its synthesis."""
    out = []
    if isinstance(meta, dict) and isinstance(meta.get("superseded_by"), str):
        out.append(f"superseded by: {meta['superseded_by']}")
    if facts := _key_facts(note_type, meta):
        out.append(facts)
    if isinstance(meta, dict) and isinstance(meta.get("part_of"), str):
        ref = "s:" + meta["part_of"]
        out.append(f"part of: {ref} (extended version: mem show {ref})")
    return out


def _show_body(note_type: str, body: str, body_line: int, mode: _ShowMode) -> list[str]:
    lines = body.split("\n")
    if mode.outline and mode.ranges:
        return _outline_ranges(lines, body_line)
    if mode.outline:
        return [f"{body_line + i}: {line}" for i, _, line in _headings(lines)]
    if mode.sections:
        return _sections(lines, _expand_conclusion(note_type, lines, mode.sections))
    return lines


def _show_note(path: Path, rel: str, mode: _ShowMode) -> tuple[str, bool]:
    """The output block of one note and whether its file could be read."""
    note_type = rel.split("/", 1)[0]
    try:
        text = note_files._read_text(path)
    except FrontmatterError as exc:
        return f"== {rel}\n({exc})", False
    try:
        meta, body, body_line = split_frontmatter(text)
    except FrontmatterError:
        meta, body, body_line = None, text, 1
    out = [
        f"== {rel}",
        *_show_header(note_type, meta),
        *_show_body(note_type, body, body_line, mode),
    ]
    return "\n".join(out).rstrip("\n"), True


def show(
    root: Path,
    paths: list[str],
    *,
    sections: list[str] | None = None,
    outline: bool = False,
    ranges: bool = False,
) -> tuple[list[str], list[str], bool]:
    """Blocks of output, one per path; the resolved paths shown; whether every path was found."""
    mode = _ShowMode(sections, outline, ranges)
    blocks: list[str] = []
    shown: list[str] = []
    ok = True
    for arg in paths:
        path = resolve_note(root, arg)
        if not isinstance(path, Path):
            blocks.append(_show_unresolved(arg, path))
            ok = False
            continue
        rel = path.relative_to(root.resolve()).as_posix()
        shown.append(rel)
        block, readable = _show_note(path, rel, mode)
        blocks.append(block)
        ok = ok and readable
    return blocks, shown, ok


def _dump_frontmatter(data: dict) -> str:
    dumped = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=float("inf")
    )
    return f"---\n{dumped}---\n"


def _knowledge_name_problem(stem: str) -> str | None:
    if word := instruction_word(stem):
        return (
            f'knowledge name reads as an instruction ("{word}-..."): {check_rules._INSTRUCTION_FIX}'
        )
    if len(stem) > MAX_KNOWLEDGE_NAME:
        return f"knowledge name too long ({len(stem)} characters): {check_rules._LONG_NAME_FIX}"
    return None


def _note_template_and_topics(root: Path, note_type: str) -> tuple[str, dict]:
    """The template body of a note type and the known topics, from the hub."""
    template = root / "templates" / f"{note_type}.md"
    try:
        _, template_body, _ = split_frontmatter(note_files._read_text(template))
        known = load_topics(root)
    except FrontmatterError as exc:
        raise NewNoteError(f"cannot read template or topics: {exc}") from exc
    return template_body, known


def _note_domain_and_topics(known: dict, topics: list[str]) -> tuple[str, list[str]]:
    """The root topic (the folder) of the first topic, and every topic with its ancestors."""
    if not topics:
        raise NewNoteError("at least one topic is required")
    for t in topics:
        if t not in known:
            raise NewNoteError(f"unknown topic '{t}': use an id from topics.yaml or add it there")
    domain = root_of(known, topics[0])
    if domain not in root_topics(known):
        raise NewNoteError(
            f"topic '{topics[0]}' has no root topic (its parent chain ends at "
            f"'{domain}'): fix its parent in topics.yaml"
        )
    all_topics = list(topics)
    for t in topics:
        all_topics += [a for a in ancestors(known, t) if a not in all_topics]
    return domain, all_topics


def _note_literature_target(
    root: Path, domain: str, slug: str, meta: dict[str, Any], today: datetime.date
) -> tuple[Path, str]:
    """Fill the literature fields of `meta`; return the target path and the name to check."""
    author = meta.pop("author", "")
    names = [a.strip() for a in author.split(",") if a.strip()] if isinstance(author, str) else []
    meta["authors"] = names
    first = slugify(names[0]) if names else ""
    if not first:
        raise NewNoteError(
            "author must contain at least one ASCII letter or digit to form the filename"
        )
    if check_rules._starts_with_author(slug.split("-"), first):
        raise NewNoteError(
            f"slug '{slug}' repeats the first author '{first}', which the "
            f"filename already holds: drop '{first}-' from --slug"
        )
    if slug.split("-", maxsplit=1)[0] == str(meta.get("year")):
        raise NewNoteError(
            f"slug '{slug}' repeats the year; `new` adds '<year>-<author>-' "
            "itself: pass only the descriptive part as --slug"
        )
    name = f"{meta.get('year')}-{first}-{slug}.md"
    meta["added"] = today.isoformat()
    return root / "literature" / domain / name, name


def _note_knowledge_target(
    root: Path, domain: str, slug: str, meta: dict[str, Any], today: datetime.date
) -> tuple[Path, str]:
    """Fill the knowledge fields of `meta`; return the target path and the name to check."""
    if problem := _knowledge_name_problem(slug):
        raise NewNoteError(problem)
    meta["updated"] = today.isoformat()
    pattern_name = f"{slug}.md"
    return root / "knowledge" / domain / pattern_name, pattern_name


def _note_research_target(
    root: Path, domain: str, slug: str, meta: dict[str, Any], today: datetime.date
) -> tuple[Path, str]:
    """Fill the research fields of `meta`; return the target path and the name to check."""
    meta.update(status="idea", started=f"{today:%Y-%m}")
    pattern_name = f"{today:%Y-%m}-{slug}"
    return root / "research" / pattern_name / "README.md", pattern_name


_NOTE_TARGETS = {
    "literature": _note_literature_target,
    "knowledge": _note_knowledge_target,
}


def _note_ordered_fields(note_type: str, meta: dict[str, Any]) -> dict[str, Any]:
    """`meta` in schema order, every value validated; raises on a missing, invalid or extra field."""
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
    return ordered


def _note_refuse_existing(root: Path, note_type: str, target: Path) -> None:
    if note_type == "research" and target.parent.exists():
        raise NewNoteError(
            f"folder {target.parent.relative_to(root).as_posix()} already exists: "
            "choose another slug"
        )
    if target.exists():
        raise NewNoteError(f"{target.relative_to(root).as_posix()} already exists")


def new_note(
    root: Path,
    note_type: str,
    *,
    slug: str,
    topics: list[str],
    today: datetime.date,
    **fields: Any,
) -> Path:
    """Create a note from its template (or with the `body` field in place of the template body),
    refusing bad slugs, unknown topics and existing paths."""
    if note_type not in SCHEMAS:
        raise NewNoteError(f"unknown note type '{note_type}'")
    body = fields.pop("body", None)
    template_body, known = _note_template_and_topics(root, note_type)
    domain, all_topics = _note_domain_and_topics(known, topics)

    meta: dict[str, Any] = dict(fields)
    plan_target = _NOTE_TARGETS.get(note_type, _note_research_target)
    target, pattern_name = plan_target(root, domain, slug, meta, today)
    meta["topics"] = all_topics

    if not NAME_PATTERNS[note_type].fullmatch(pattern_name):
        raise NewNoteError(f"invalid name '{pattern_name}': {check_rules._NAME_FIX[note_type]}")
    ordered = _note_ordered_fields(note_type, meta)
    _note_refuse_existing(root, note_type, target)

    target.parent.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(
        target,
        (_dump_frontmatter(ordered) + (template_body if body is None else body)).encode("utf-8"),
    )
    try:
        apply_index(root)
    except FrontmatterError as exc:
        raise NewNoteError(
            f"{target.relative_to(root).as_posix()} was created but the index "
            f"was not updated ({exc}): fix it, then run mem index"
        ) from exc
    return target


# --- rename --------------------------------------------------------------------


def _link_points_at(base: Path, target: str, raw: str, old: Path) -> bool:
    """Whether the link `target` (`raw` is its path part) in the file `base` points at the file `old`."""
    if target.startswith(("#", "mailto:")) or check_rules._SCHEME.match(target) or not raw:
        return False
    try:
        return (base.parent / urllib.parse.unquote(raw)).resolve() == old
    except (OSError, ValueError):
        return False


def _link_edits(
    text: str, base: Path, old: Path, new_name: str, new_path: Path | None = None
) -> tuple[str, int]:
    """`text` of the file `base` with each relative link to `old` pointing at `new_name`, and their count.

    Links are found as `_relative_links` finds them (code is masked in place, so offsets stay valid);
    only the file name of the path part changes: prefix, `#anchor` and link text are kept. With `new_path`
    (resolved, like `old` and `base`) the whole path part is recomputed from `base`'s folder instead, because
    the note may sit in another folder.
    """
    lines = text.split("\n")
    masked = check_rules._CODE_SPAN.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        "\n".join(
            " " * len(l) if f else l
            for l, f in zip(lines, check_rules._in_fence(lines), strict=False)
        ),
    )
    count = 0
    for i, line in enumerate(masked.split("\n")):
        for start, end in reversed(check_rules._target_spans(line, True)):
            target = line[start:end]
            raw = target.split("#", 1)[0]
            hit = _link_points_at(base, target, raw, old)
            if hit and new_path is not None:
                lines[i] = (
                    lines[i][:start]
                    + Path(os.path.relpath(new_path, base.parent)).as_posix()
                    + lines[i][start + len(raw) :]
                )
                count += 1
            elif hit:
                cut = start + len(raw) - len(raw.rsplit("/", 1)[-1])
                lines[i] = lines[i][:cut] + new_name + lines[i][start + len(raw) :]
                count += 1
    return "\n".join(lines), count


def _split_frontmatter_block(text: str) -> re.Match | None:
    return re.match(r"---\n(.*?)\n---[ \t]*(?:\n|$)", text, re.DOTALL)


def _set_field(text: str, key: str, value: Any) -> str:
    """`text` with the frontmatter field `key` set (in place when present, else last) or, for None, removed;
    every other byte stays."""
    m = _split_frontmatter_block(text)
    if m is None:
        raise ValueError("the note has no frontmatter")
    lines = m.group(1).split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(key)}:", ln)), None)
    end = start
    if start is not None:
        end = start + 1
        while end < len(lines) and re.match(r"(\s|- )", lines[end]):
            end += 1
    rendered = (
        ""
        if value is None
        else yaml.safe_dump(
            value, allow_unicode=True, default_flow_style=True, width=float("inf")
        ).split("\n")[0]
    )
    new = [] if value is None else [f"{key}: {rendered}"]
    new_lines = lines[:start] + new + lines[end:] if start is not None else lines + new
    return "---\n" + "\n".join(new_lines) + "\n---\n" + text[m.end() :]


def _rename_handle_fields(text: str, old: str, new: str) -> tuple[str, int]:
    """`text` with `superseded_by` and `distinct_from` values that name the note `old` naming `new`, and their count."""
    # `part_of` is not renamed here: it names a synthesis, and `rename` takes only literature and knowledge notes.
    try:
        meta, _, _ = split_frontmatter(text)
    except FrontmatterError:
        return text, 0
    count = 0
    if isinstance(meta, dict):
        if meta.get("superseded_by") == old:
            text, count = _set_field(text, "superseded_by", new), count + 1
        names = meta.get("distinct_from")
        if isinstance(names, list) and old in names:
            text, count = (
                _set_field(text, "distinct_from", sorted(new if h == old else h for h in names)),
                count + 1,
            )
    return text, count


def _rename_source(root: Path, arg: str) -> Path:
    """The literature or knowledge note `arg` names exactly, else a refusal."""
    old = resolve_note(root, arg, prefix=False)
    if isinstance(old, list):
        raise NewNoteError(f"ambiguous: {arg} matches {len(old)} notes: {', '.join(old[:10])}")
    parts = old.relative_to(root).parts if old else ()
    if (
        old is None
        or len(parts) != _NOTE_PATH_PARTS
        or parts[0] not in {"literature", "knowledge"}
        or old.name == "README.md"
        or note_files._is_hidden(old, root)
    ):
        raise NewNoteError(
            f"{arg} is not a literature or knowledge note: give its path or exact handle "
            "(no prefix; investigations are not renamed)"
        )
    return old


def _rename_keep_literature_prefix(root: Path, old: Path, stem: str) -> None:
    """Refuse a new literature name that drops the `<year>-<author>-` prefix or repeats it after it."""
    meta = note_files._read_note("literature", old, root).meta
    authors = meta.get("authors") if isinstance(meta, dict) else None
    year, *tokens = old.stem.split("-")
    slug = (
        slugify(cast("list[str]", authors)[0])  # `_authors` found a valid list
        if check_rules._authors(authors) is None
        else tokens[0]
    )  # as rule_consistency: may span tokens
    n = next((k for k in range(1, len(tokens)) if "".join(tokens[:k]) == slug), 1)
    new_year, *new_tokens = stem.split("-")
    if new_year != year or tokens[:n] != new_tokens[:n]:
        raise NewNoteError(f"the name must keep the prefix {'-'.join([year, *tokens[:n]])}-")
    if (rest := new_tokens[n:]) and (
        check_rules._starts_with_author(rest, slug) or rest[0] == year
    ):
        raise NewNoteError("the name repeats the author or the year after the prefix")


def _rename_check_name(root: Path, old: Path, kind: str, stem: str) -> None:
    """Refuse a new name that breaks the naming rules of the kind or is taken by another note."""
    name = f"{stem}.md"
    if not NAME_PATTERNS[kind].fullmatch(name):
        raise NewNoteError(f"invalid name '{name}': {check_rules._NAME_FIX[kind]}")
    if kind == "knowledge" and (problem := _knowledge_name_problem(stem)):
        raise NewNoteError(problem)
    if kind == "literature":
        _rename_keep_literature_prefix(root, old, stem)
    if old.with_name(name).exists() or any(
        note_files._handle(p.relative_to(root).as_posix()) == stem
        for _, p in note_files._note_files(root)
    ):
        raise NewNoteError(f"a note named '{stem}' already exists")


def _rename_link_edits(root: Path, old: Path, stem: str) -> tuple[dict[Path, str], int]:
    """The new text of every markdown file that links to, or names the handle or copy of, `old`; and the count."""
    edits: dict[Path, str] = {}
    links = 0
    copy = f"{SOURCES_DIR}/{old.stem}/"
    for path in check_rules._markdown_files(root):
        try:
            text = note_files._read_text(path)
        except FrontmatterError as exc:
            raise NewNoteError(
                f"cannot read {path.relative_to(root).as_posix()} to rewrite its links ({exc}): "
                "fix it, then rename"
            ) from exc
        edited, count = _link_edits(text, path, old, f"{stem}.md")
        count += edited.count(copy)  # a note's text naming its local copy
        edited, named = _rename_handle_fields(edited, old.stem, stem)
        count += named
        if count:
            edits[path], links = edited.replace(copy, f"{SOURCES_DIR}/{stem}/"), links + count
    return edits, links


def _rename_refuse_locked(root: Path, paths: list[Path]) -> None:
    locked = [p for p in paths if not os.access(p, os.W_OK)]
    if locked:
        raise NewNoteError(
            f"not writable: {', '.join(p.relative_to(root).as_posix() for p in locked)}"
        )


def rename_note(root: Path, arg: str, new_stem: str) -> tuple[Path, int, int]:
    """Rename a literature or knowledge note in its folder; return (new path, links rewritten, files changed).

    Every edit is computed before anything is written, so a refusal leaves the hub untouched.
    """
    root = root.resolve()
    old = _rename_source(root, arg)
    stem = new_stem.removesuffix(".md")
    new = old.with_name(f"{stem}.md")
    _rename_check_name(root, old, old.relative_to(root).parts[0], stem)
    sources, new_sources = root / SOURCES_DIR / old.stem, root / SOURCES_DIR / stem
    if new_sources.exists():
        raise NewNoteError(f"{SOURCES_DIR}/{stem} already exists")
    edits, links = _rename_link_edits(root, old, stem)
    _rename_refuse_locked(
        root, [*edits, old, old.parent, *((sources, sources.parent) if sources.is_dir() else ())]
    )
    originals = {(new if p == old else p): p.read_bytes() for p in (*edits, old)}
    listings = _index_files(root)
    for path, text in edits.items():
        safe_io.replace_file(path, text.encode("utf-8"))
    old.rename(new)
    if sources.is_dir():
        sources.rename(new_sources)
    try:
        apply_index(root)
    except FrontmatterError as exc:
        raise NewNoteError(
            f"{new.relative_to(root).as_posix()} was renamed but the index was not "
            f"updated ({exc}): fix it, then run mem index"
        ) from exc
    _log_group(root, _with_changed_listings(originals, listings), "rename", {new: old})
    return new, links, len(edits)


# --- unify ---------------------------------------------------------------------

_CONFIDENCE_ORDER = ("low", "medium", "high")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _index_files(root: Path) -> dict[Path, bytes]:
    """The README listing files that `apply_index` may rewrite, with their bytes now (those that exist)."""
    try:
        targets = index_targets(root, discover_notes(root), load_topics(root))
    except FrontmatterError:
        return {}
    return {t.path: t.path.read_bytes() for t in targets if t.path.is_file()}


def _with_changed_listings(
    originals: dict[Path, bytes], listings: Mapping[Path, bytes]
) -> dict[Path, bytes]:
    """`originals` plus each listing file in `listings` whose bytes are not what they were."""
    return {**{p: b for p, b in listings.items() if p.read_bytes() != b}, **originals}


def _log_group(
    root: Path,
    originals: Mapping[Path, bytes],
    action: str,
    moved: Mapping[Path, Path] | None = None,
    group: str | None = None,
) -> None:
    """One `.curation-log` entry per changed file, sharing a `group` id and holding the file's text before the action
    and a digest of its text after it, so `mem restore` can undo them together and refuse when one changed since.
    `moved` names, for a file that was renamed, the path it had before (`from`, hub-relative)."""
    group = group or uuid.uuid4().hex
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for path, before in originals.items():
        entry = {
            "t": stamp,
            "action": action,
            "handle": path.relative_to(root).as_posix(),
            "group": group,
            "before": before.decode("utf-8"),
            "after": _sha(path.read_bytes()),
        }
        if moved and path in moved:
            entry["from"] = moved[path].relative_to(root).as_posix()
        out.append(json.dumps(entry, ensure_ascii=False) + "\n")
    safe_io.append_text(root / records.CURATION_LOG, "".join(out))


def _resolve_notes(root: Path, args: Sequence[str]) -> list[Path]:
    typed = {p.resolve() for _, p in note_files._note_files(root)}
    found = []
    for arg in args:
        path = resolve_note(root, arg)
        if isinstance(path, list):
            raise NewNoteError(
                f"ambiguous: {arg} matches {len(path)} notes: {', '.join(path[:10])}"
            )
        if path is None or path not in typed:
            raise NewNoteError(f"no note {arg}")
        found.append(path)
    return found


@dataclass(frozen=True)
class UnifyRequest:
    """What the owner asked `unify_notes` to write: the unified text, whether dropped links are meant, the date."""

    body: str
    drop: bool
    today: datetime.date


def _unify_readable_notes(root: Path, paths: list[Path]) -> list[Note]:
    """The parsed notes of `paths`, refusing the same note twice, an unreadable one and mixed types."""
    if len(set(paths)) != len(paths):
        raise NewNoteError("the same note is named twice: unify needs different notes")
    notes = [note_files._read_note(p.relative_to(root).parts[0], p, root) for p in paths]
    for note in notes:
        if note.error is not None or not isinstance(note.meta, dict):
            raise NewNoteError(
                f"{note.rel} cannot be read ({note.error or 'frontmatter is not a mapping'})"
            )
    if len({n.type for n in notes}) > 1:
        raise NewNoteError("the notes are of different types: unify joins notes of one type")
    return notes


def _unify_refuse_superseded(root: Path, notes: list[Note]) -> None:
    """Refuse a note already superseded, and any note in the store that a note to unify supersedes."""
    for note in notes:
        if note.meta.get("superseded_by") is not None:
            raise NewNoteError(f"{note.rel} is already superseded by {note.meta['superseded_by']}")
    handles = {note_files._handle(n.rel) for n in notes}
    for note in discover_notes(root):
        if isinstance(note.meta, dict) and note.meta.get("superseded_by") in handles:
            raise NewNoteError(
                f"{note.rel} is already superseded by {note.meta['superseded_by']}: unify into the "
                "note that replaced it, or leave it"
            )


def _unify_refuse_lost_links(root: Path, notes: list[Note], body: str, drop: bool) -> None:
    """Refuse a unified text that drops links of the notes, unless the owner passed `--drop`."""
    unified = {n.rel for n in notes}
    had = set().union(*(_link_targets(root, n) for n in notes))
    lost = sorted(had - _link_targets(root, dataclasses.replace(notes[0], body=body)) - unified)
    if lost and not drop:
        raise NewNoteError(
            f"the unified text drops the links {', '.join(lost)}; use --drop if that is meant."
        )


def _unify_keep_text(notes: list[Note], request: UnifyRequest) -> str:
    """The text of the kept note: the new body, the union of the topics, the lowest confidence."""
    keep, others = notes[0], notes[1:]
    keep_text = note_files._read_text(keep.path)
    m = _split_frontmatter_block(keep_text)
    if m is None:
        raise NewNoteError(f"{keep.rel} has no frontmatter")
    union = list(keep.meta.get("topics") or [])
    union += [t for o in others for t in (o.meta.get("topics") or []) if t not in union]
    new_text = _set_field(keep_text[: m.end()] + request.body, "topics", union)
    if "confidence" in SCHEMAS[keep.type]:
        ranks = [
            _CONFIDENCE_ORDER.index(n.meta["confidence"])
            for n in notes
            if n.meta.get("confidence") in _CONFIDENCE_ORDER
        ]
        if ranks:
            new_text = _set_field(new_text, "confidence", _CONFIDENCE_ORDER[min(ranks)])
    if keep.type == "knowledge":
        new_text = _set_field(new_text, "updated", request.today.isoformat())
    return new_text


def _unify_current_text(root: Path, path: Path, edits: dict[Path, str]) -> str:
    """The text of a file as it stands with the edits so far."""
    original = edits.get(path.resolve())
    if original is not None:
        return original
    try:
        return note_files._read_text(path)
    except FrontmatterError as exc:
        raise NewNoteError(
            f"cannot read {path.relative_to(root).as_posix()} to rewrite its links ({exc}): "
            "fix it, then unify"
        ) from exc


def _unify_rewrite_links(
    root: Path, edits: dict[Path, str], others: list[Note], keep_path: Path
) -> int:
    """Point every link to an other note at the kept note, adding the files to `edits`; the count."""
    links = 0
    skip = {o.path for o in others}
    for path in check_rules._markdown_files(root):
        rel = path.relative_to(root).as_posix()
        if path.resolve() in skip or check_rules._is_index_readme(rel):
            continue
        resolved = path.resolve()
        original = _unify_current_text(root, path, edits)
        text = original
        for o in others:
            text, count = _link_edits(text, resolved, o.path, "", keep_path)
            links += count
        if text != original:
            edits[resolved] = text
    return links


def _unify_write(root: Path, edits: dict[Path, str]) -> None:
    for path in edits:  # a note resolved outside the store raises ValueError here, before any write
        path.relative_to(root)
    for path, text in edits.items():
        safe_io.replace_file(path, text.encode("utf-8"))


def _unify_new_problems(
    root: Path, keep_rel: str, before: collections.Counter[tuple[str, str]]
) -> list[Problem]:
    """The `check` problems the edits introduced; an index that cannot be updated is one."""
    try:
        apply_index(root)
        after = check(root)
        more = (
            collections.Counter((p.path, p.message) for p in after) - before
        )  # counted: a second copy is new
        return [p for p in after if (p.path, p.message) in more]
    except FrontmatterError as exc:
        return [Problem(keep_rel, 1, f"the index was not updated ({exc})")]


def _unify_undo_on_problems(
    root: Path, originals: dict[Path, bytes], problems: list[Problem]
) -> None:
    """With problems, put every file back and raise them; with none, do nothing."""
    if not problems:
        return
    for path, data in originals.items():
        safe_io.replace_file(path, data)
    with contextlib.suppress(FrontmatterError, OSError):
        apply_index(root)
    raise NewNoteError(
        f"the unified notes have {len(problems)} problems, so nothing was written:\n"
        + "\n".join(str(p) for p in problems)
    )


def unify_notes(
    root: Path, keep_arg: str, other_args: Sequence[str], request: UnifyRequest
) -> tuple[Path, int, int]:
    """Make `keep_arg` the unified note of itself and `other_args`; return (keep path, notes unified, links rewritten).

    The kept note takes the request's body, the union of the topics and the lowest confidence; each other note
    gets `superseded_by` and stays as a file; every link to an other note in the store points at the kept note.
    The result must pass `check`, else every file is put back and the problems are raised."""
    root = root.resolve()
    notes = _unify_readable_notes(root, _resolve_notes(root, [keep_arg, *other_args]))
    keep, others = notes[0], notes[1:]
    _unify_refuse_superseded(root, notes)
    _unify_refuse_lost_links(root, notes, request.body, request.drop)

    edits: dict[Path, str] = {keep.path: _unify_keep_text(notes, request)}
    for o in others:
        edits[o.path] = _set_field(
            note_files._read_text(o.path), "superseded_by", note_files._handle(keep.rel)
        )
    links = _unify_rewrite_links(root, edits, others, keep.path)
    _rename_refuse_locked(root, list(edits))

    # Line numbers move with the edit, so a problem is known by its file and message: the store may hold
    # problems older than this change (an imported note that links a document left behind), and they do not block it.
    before = collections.Counter((p.path, p.message) for p in check(root))
    originals = {p: p.read_bytes() for p in edits}
    listings = _index_files(root)
    _unify_write(root, edits)
    _unify_undo_on_problems(root, originals, _unify_new_problems(root, keep.rel, before))
    _log_group(root, _with_changed_listings(originals, listings), "unify")
    return keep.path, len(notes), links


# --- fetch-sources -------------------------------------------------------------

SOURCES_DIR = ".sources"
FETCH_TIMEOUT = 30  # seconds per socket operation: slow source servers answer late
FETCH_DEADLINE = 120  # seconds for one download, all redirects together
FETCH_PAUSE = 1.0
FETCH_MAX_BYTES = 50 * 1024 * 1024  # larger sources stay online only (C-14)
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
_CONTENT_EXT = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "txt",
}
_SUFFIX_EXT = {".pdf": "pdf", ".html": "html", ".htm": "html", ".txt": "txt"}


def _download(url: str) -> tuple[bytes, str]:
    """(body, Content-Type) of a URL, redirects followed. Goes through the address-checked transport of
    `research_checks`: a host that resolves to a non-public address, at any hop, is refused."""
    try:
        return research_checks.fetch_raw(
            url,
            lambda _: FETCH_MAX_BYTES,
            over="fail",
            headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
            deadline=FETCH_DEADLINE,
            max_redirects=10,
            timeout=FETCH_TIMEOUT,
        )
    except research_checks.FetchError as exc:
        raise ValueError(str(exc)) from exc


def _source_extension(url: str, content_type: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in _CONTENT_EXT:
        return _CONTENT_EXT[mime]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return _SUFFIX_EXT.get(suffix, "html")


_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "svg",
    "title",
    "select",
    "button",
    "option",
}
_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "section",
    "article",
    "blockquote",
    "pre",
}
_CHARSET = re.compile(rb"""charset\s*=\s*["']?([\w.:-]+)""", re.IGNORECASE)
MIN_TEXT_WORDS = (
    200  # a shorter conversion is a shell page (script-rendered, paywalled), not a source text
)


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip: list[str] = []
        self.main = 0  # open article/main elements: a header inside one is part of the text

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.main += tag in {"article", "main"}
        if tag in _SKIP_TAGS and not (tag == "header" and self.main):
            self.skip.append(tag)
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        self.main = max(0, self.main - (tag in {"article", "main"}))
        if tag in self.skip:
            del self.skip[len(self.skip) - 1 - self.skip[::-1].index(tag) :]
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(
                re.sub(r"\s+", " ", data)
            )  # a newline inside the markup is not a line break


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
    return (
        [by_rel[p] for p in paths if p in by_rel],
        [f"failed {p}: not a literature note" for p in paths if p not in by_rel],
    )


def _txt_files(folder: Path) -> list[Path]:
    """Every `.txt` entry of a source folder (any case, symlinks too): the hub never writes `source.txt` beside one."""
    return [p for p in folder.iterdir() if p.suffix.lower() == ".txt"]


def _largest_copy(folder: Path, *patterns: str) -> Path | None:
    """The largest regular file of the folder matching a pattern (ties by name), symlinks left out."""
    found = [p for pat in patterns for p in folder.glob(pat) if p.is_file() and not p.is_symlink()]
    return max(found, key=lambda p: (p.stat().st_size, p.name), default=None)


def _text_from_page(folder: Path, page: Path) -> str | None:
    """Write `source.txt` from an HTML copy: None when written, else the reason it is too short."""
    text = html_to_text(page.read_bytes())
    if len(text.split()) >= MIN_TEXT_WORDS:
        safe_io.replace_file(folder / "source.txt", text.encode("utf-8"))
        return None
    return f"page has under {MIN_TEXT_WORDS} words of text"


def _text_from_pdf(folder: Path, pdf: Path) -> str | None:
    """Write `source.txt` from a PDF copy with `pdftotext`: None when written, else the reason."""
    if not shutil.which("pdftotext"):
        return "pdftotext is not installed"
    try:
        done = subprocess.run(
            ["pdftotext", str(pdf), str(folder / "source.txt")],
            check=False,
            timeout=60,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"pdftotext failed: {exc}"
    if done.returncode == 0:
        return None
    (folder / "source.txt").unlink(missing_ok=True)
    return f"pdftotext failed with exit {done.returncode}"


def _write_text_copy(folder: Path) -> str | None:
    """Write `source.txt` from the folder's largest HTML copy, else its largest PDF; None when written, else the reason."""
    if _txt_files(folder):
        return "the folder already holds a .txt"
    reason = "no HTML or PDF copy"
    if (page := _largest_copy(folder, "*.html", "*.htm")) is not None:
        reason = _text_from_page(folder, page)
        if reason is None:
            return None
    if (pdf := _largest_copy(folder, "*.pdf")) is None:
        return reason
    return _text_from_pdf(folder, pdf)


def _folder_text_status(folder: Path) -> tuple[str | None, int] | None:
    """(reason it has no text, words of its text) for a source folder after trying to build `source.txt`;
    None when the folder already held a `.txt`."""
    if folder.is_symlink():
        return f"{SOURCES_DIR}/{folder.name} is a symlink", 0
    if _txt_files(folder):
        return None
    reason = _write_text_copy(folder)
    if reason is not None:
        return reason, 0
    return None, len((folder / "source.txt").read_text(encoding="utf-8").split())


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
        try:
            status = _folder_text_status(folder)
        except OSError as exc:
            status = (str(exc), 0)
        if status is None:
            had += 1
            continue
        reason, words = status
        if reason is None:
            lines.append(f"text {note.rel} ({words} words)")
            written += 1
        else:
            lines.append(f"no text {note.rel}: {reason}")
            without += 1
    lines.append(f"text written {written}, without text {without}, already had text {had}")
    return lines, not bad


@dataclass(frozen=True)
class _FetchOutcome:
    """What `fetch_sources` did with one note: the counter to bump, the output line, whether it hit the network."""

    counter: str
    line: str
    requested: bool


def _fetch_refusal(note: Note, folder: Path, force: bool) -> tuple[str, str] | None:
    """(counter, output line) when a note's folder rules out a download: a symlink or a cached copy."""
    if folder.is_symlink():
        return "failed", f"failed {note.rel}: {SOURCES_DIR}/{folder.name} is a symlink"
    if not force and folder.is_dir() and any(not p.is_symlink() for p in folder.iterdir()):
        return "skipped", f"skipped {note.rel} (already cached)"
    return None


def _http_url(note: Note) -> str | None:
    """The note's `url` when it is a string starting with http:// or https://."""
    url = note.meta.get("url") if isinstance(note.meta, dict) else None
    if isinstance(url, str) and urllib.parse.urlparse(url).scheme in {"http", "https"}:
        return url
    return None


def _download_source(folder: Path, url: str) -> str:
    """Download `url` into `folder` as `source.<ext>`, dropping other copies of `source.*`; the extension."""
    data, content_type = _download(url)
    ext = _source_extension(url, content_type)
    folder.mkdir(parents=True, exist_ok=True)
    if ext == "txt" and any(p.name != "source.txt" for p in _txt_files(folder)):
        raise ValueError("the folder already holds a .txt")
    for old in folder.glob("source.*"):  # --force: drop copies of another type or a stale text
        old.unlink()
    safe_io.replace_file(folder / f"source.{ext}", data)
    return ext


def _fetched_line(note: Note, folder: Path, ext: str) -> str:
    """The output line of a fetched note; an HTML copy is converted to text, and a failure noted."""
    if ext == "pdf" and shutil.which("pdftotext") and not _txt_files(folder):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["pdftotext", str(folder / "source.pdf"), str(folder / "source.txt")],
                check=False,
                timeout=60,
                capture_output=True,
            )
    line = f"fetched {note.rel}"
    if ext != "html":
        return line
    try:
        reason = _write_text_copy(folder)
    except OSError as exc:
        reason = str(exc)
    return line if reason is None else f"{line} (no text: {reason})"


def _fetch_one(note: Note, folder: Path, force: bool, pause: bool) -> _FetchOutcome:
    """Download one note's source, sleeping first when `pause` (a request went out before)."""
    if (refusal := _fetch_refusal(note, folder, force)) is not None:
        return _FetchOutcome(*refusal, requested=False)
    url = _http_url(note)
    if url is None:
        line = f"failed {note.rel}: url must start with http:// or https://"
        return _FetchOutcome("failed", line, requested=False)
    if pause:
        time.sleep(FETCH_PAUSE)
    try:
        ext = _download_source(folder, url)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return _FetchOutcome("failed", f"failed {note.rel}: {exc}", requested=True)
    return _FetchOutcome("fetched", _fetched_line(note, folder, ext), requested=True)


def fetch_sources(
    root: Path, paths: list[str] | None = None, *, force: bool = False
) -> tuple[list[str], bool]:
    """Download each literature note's `url` into .sources/<note-stem>/; returns (output lines, all ok)."""
    notes, lines = _literature_notes(root, paths)
    counts = {"fetched": 0, "skipped": 0, "failed": len(lines)}
    requested = False
    for note in notes:
        outcome = _fetch_one(note, root / SOURCES_DIR / note.path.stem, force, requested)
        lines.append(outcome.line)
        counts[outcome.counter] += 1
        requested = requested or outcome.requested
    lines.append(
        f"fetched {counts['fetched']}, skipped {counts['skipped']}, failed {counts['failed']}"
    )
    return lines, counts["failed"] == 0


def source_text(root: Path, rel: str) -> Path | None:
    """The largest `.txt` (ties by name) of a literature note's `.sources/<note-stem>/` folder, else its largest `.md`."""
    folder = root / SOURCES_DIR / Path(rel).stem
    texts: list[Path] = []
    for pattern in ("*.txt", "*.md"):
        texts = (
            [p for p in folder.glob(pattern) if p.is_file() and not p.is_symlink()]
            if folder.is_dir()
            else []
        )
        if texts:
            break
    return min(texts, key=lambda p: (-p.stat().st_size, p.name), default=None)


def passages(
    text: str, query: str, *, count: int = 5, words: int = 500
) -> tuple[int, list[tuple[int, int, str]]]:
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
    wins = [" ".join(tokens[s : s + words]) for s in starts]
    counts = [collections.Counter(tokenize(w)) for w in wins]
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / len(wins)
    idf = {}
    for term in dict.fromkeys(tokenize(query)):
        n = sum(1 for c in counts if term in c)
        idf[term] = math.log(1 + (len(wins) - n + 0.5) / (n + 0.5))
    scored = []
    for i, (c, length) in enumerate(zip(counts, lengths, strict=False)):
        score = sum(
            idf[t] * c[t] * 2.2 / (c[t] + 1.2 * (1 - 0.75 + 0.75 * length / average))
            for t in idf
            if c.get(t) and average
        )
        if score > 0:
            scored.append((-score, i))
    best = sorted(i for _, i in sorted(scored)[:count])
    return len(tokens), [
        (starts[i] + 1, min(starts[i] + words, len(tokens)), wins[i]) for i in best
    ]


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
    return not scopes or any(s in {".", rel} or rel.startswith(s + "/") for s in scopes)


def _page_footer(offset: int, shown: int, total: int) -> None:
    if shown and offset + shown < total:
        print(
            f"-- {offset + 1}-{offset + shown} of {total}; next: --offset {offset + shown} --",
            file=sys.stderr,
        )
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
        notes = _matching_notes(
            args.root,
            type=args.type,
            topic=args.topic,
            kind=args.kind,
            status=args.status,
            confidence=args.confidence,
            level=args.level,
            superseded=args.superseded,
        )
    except (FrontmatterError, OSError) as exc:
        print(f"mem: cannot find: {exc}", file=sys.stderr)
        return 1
    page = sorted(notes, key=lambda n: n.rel)[args.offset : args.offset + args.limit]
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
        direct = (
            {t for t in listed if isinstance(t, str) and t in known}
            if isinstance(listed, list)
            else set()
        )
        counts.update(direct.union(*(ancestors(known, t) for t in direct)))
    rows: list[tuple[int, str, int]] = []

    def walk(tid: str, depth: int) -> None:
        rows.append((depth, tid, counts[tid]))
        for child in sorted(
            t
            for t in known
            if note_files._parent(known, t) == tid and t not in {r[1] for r in rows}
        ):
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


def _append_usage(
    root: Path | None, entry: dict[str, Any], env: Mapping[str, str], cwd: Path | None
) -> None:
    """Write one usage entry as a line of the log file, unless the log would sit inside the store."""
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


def log_usage(
    root: Path | None,
    entry: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> None:
    """Append one JSON line to the usage log in the data folder; never raises, never changes output."""
    env = os.environ if env is None else env
    if env.get("MEM_USAGE_LOG") == "0":
        return
    entry = {"t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
    with contextlib.suppress(OSError, ValueError, TypeError):
        _append_usage(root, entry, env, cwd)


def _memory_folders(args: argparse.Namespace) -> list[tuple[str, Path | None]]:
    try:
        project = records.project_root(Path.cwd(), os.environ)
    except OSError:
        project = None
    return [
        ("project", records.project_dir(project) if project else None),
        ("global", records.memories_root(os.environ, _optional_store(args))),
    ]


def _register_project(project: Path | None) -> None:
    """Record the project in the local registry; never fails or prints, the command it follows has succeeded."""
    if project is None:
        return
    try:
        records.register_project(data_dir(os.environ), project, datetime.date.today())
    except Exception:
        logger.debug("registering the project failed", exc_info=True)


def _named_folder(name: str) -> Path | None:
    """The memory folder of a registered project; None when the name is unknown or the registry unreadable."""
    try:
        entry = records.read_registry(data_dir(os.environ)).get(name)
    except ValueError:
        return None
    return records.project_dir(Path(entry["path"])) if entry else None


def _other_projects(names: Sequence[str], every: bool) -> list[tuple[str, Path]] | None:
    """The folders of the projects asked for, without the current one; None after a message on stderr."""
    try:
        reg = records.read_registry(data_dir(os.environ))
    except ValueError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return None
    for name in names:
        if name not in reg:
            print(f"mem: no project named {name} (see mem projects list)", file=sys.stderr)
            return None
    try:
        current = records.project_root(Path.cwd(), os.environ)
        current = current.resolve() if current else None
    except OSError:
        current = None
    chosen = list(dict.fromkeys([*(reg if every else ()), *names]))
    return [
        (n, records.project_dir(Path(reg[n]["path"])))
        for n in chosen
        if current is None or Path(reg[n]["path"]) != current
    ]


def _memory_status(m: records.Memory, today: datetime.date) -> str | None:
    if m.status != "active":
        return m.status
    return "expired" if m.valid_until is not None and m.valid_until < today else None


def _unconfirmed(m: records.Memory) -> str:
    """A web finding is unchecked until a second source confirms it; a transcript memory until another session shows it."""
    if m.origin == "transcript":
        return (
            ", from transcript, unconfirmed"
            if records.standing(m) == "unconfirmed"
            else ", from transcript"
        )
    return ", web, unconfirmed" if m.origin == "web" else ""


def _memory_line(m: records.Memory, today: datetime.date) -> str:
    dead = _memory_status(m, today)
    created = m.created.isoformat() if m.created else "undated"
    claim = " ".join(m.claim.split())  # a hand-edited tab or newline must not add a column
    return (
        f"m:{m.handle}\t[memory: {m.kind}, observed {m.observed}, {created}{_unconfirmed(m)}"
        f"{', ' + dead if dead else ''}]\t{claim}"
    )


def _tally_line(tally: records.Tally, until: datetime.date) -> str:
    """The `mem show` line of one version; `until` is the date of the next version, or today for the last."""
    days = (until - tally.since).days
    return (
        f"version {tally.number} since {tally.since.isoformat()} ({days} day{'' if days == 1 else 's'}): "
        f"worked {tally.worked}, failed {tally.failed}: {tally.text}"
    )


def _memory_facts(m: records.Memory) -> str:
    facts = f"kind: {m.kind} \u00b7 observed {m.observed} \u00b7 status {m.status} \u00b7 created {m.created.isoformat() if m.created else 'undated'}"
    if m.valid_until:
        facts += f" \u00b7 valid until {m.valid_until.isoformat()}"
    if m.context:
        facts += f" \u00b7 context: {m.context}"
    return facts


def _memory_source_lines(m: records.Memory) -> list[str]:
    out = []
    if m.sources:
        out.append(f"sources: {', '.join(m.sources)}")
    if m.short:
        out.append(f"short: {m.short}")
    return out


def _memory_tail_lines(m: records.Memory) -> list[str]:
    """The optional fields after the versions: what shortened it, why triage held it, its topic and load."""
    fields = (
        ("short_by", m.short_by),
        ("held at triage", m.triage_reason),
        ("topic", m.topic),
        ("load", m.load),
    )
    return [f"{label}: {value}" for label, value in fields if value]


def _memory_claim_lines(m: records.Memory, sections: list[str] | None) -> list[str]:
    """The claim, and the body unless the sections asked for are only the conclusion."""
    out = ["", "## Claim", " ".join(m.claim.split())]
    if (
        not (sections and any(s.strip().casefold() == "conclusion" for s in sections))
        and m.body.strip()
    ):
        out += ["", m.body.rstrip("\n")]
    return out


def _memory_block(m: records.Memory, sections: list[str] | None) -> str:
    out = [f"== m:{m.handle} ({m.scope})", _memory_facts(m), *_memory_source_lines(m)]
    found = records.tallies(m)
    ends = [t.since for t in found[1:]] + [datetime.date.today()]
    out += [_tally_line(t, end) for t, end in zip(found, ends, strict=False)]
    out += _memory_tail_lines(m)
    out += _memory_claim_lines(m, sections)
    return "\n".join(out)


def _is_memory_arg(args: argparse.Namespace, arg: str) -> bool:
    """`m:<handle>`, or a bare handle that names no note and does name a memory."""
    if arg.startswith("m:"):
        return True
    if "/" in arg or arg.endswith(".md"):
        return False
    root = _optional_store(args)
    if root is not None and resolve_note(root, arg) is not None:
        return False
    return _find_memory(args, arg) is not None


def _synthesis_section_block(
    syn: syntheses.Synthesis, handle: str, section: str, lines: list[str]
) -> str | None:
    """The text of one section of a synthesis; None after a message when it has no such section."""
    found = [s for s in syn.sections if s.handle == section]
    if not found:
        print(f"mem: no section {section} in s:{handle}", file=sys.stderr)
        return None
    start = found[0].line - 1
    stop = next((x.line - 1 for x in syn.sections if x.line > found[0].line), len(lines))
    return "\n".join([f"== s:{handle}#{section}", *lines[start:stop]]).rstrip("\n")


def _synthesis_body_lines(args: argparse.Namespace, text: str, lines: list[str]) -> list[str]:
    """The lines of a whole synthesis `mem show` prints: its outline, the chosen sections or the file."""
    frontmatter = cast(
        "re.Match[str]", syntheses._FRONTMATTER.match(text)
    )  # `syn` parsed this text
    first = text[: frontmatter.end()].count("\n")
    body = lines[first:]
    if args.outline and not args.ranges:
        return [f"{first + 1 + i}: {line}" for i, _, line in _headings(body)]
    if args.section and not args.outline:
        return _sections(body, args.section)
    if args.all and not args.outline:
        return lines
    # a synthesis is long: the outline with ranges is the default, `--all` prints the file
    return _outline_ranges(body, first + 1)


def _synthesis_block(args: argparse.Namespace, ref: str) -> str | None:
    """`s:<h>` the whole file (or its outline or `--section`s), `s:<h>#<section handle>` one section; None after a message."""
    handle, section = syntheses.split_ref(ref)
    path = syntheses.path_of(args.root / syntheses.SYNTHESES_DIR, handle)
    if path is None or not path.is_file():
        print(f"mem: no synthesis {ref}", file=sys.stderr)
        return None
    syn = syntheses.load_one(path)
    if syn.error:
        print(f"mem: {path}: {syn.error}", file=sys.stderr)
        return None
    text = path.read_bytes().decode("utf-8", "replace")
    if not args.stored:  # a reader gets `[n]`, the note's place on the `Sources:` line, not the 29-token reference; line numbers stay
        text = syntheses.shown_file(text)
    lines = text.split("\n")
    if section is not None:
        return _synthesis_section_block(syn, handle, section, lines)
    out = [f"== s:{handle}", *_synthesis_body_lines(args, text, lines)]
    return "\n".join(out).rstrip("\n")


def _project_synthesis_context() -> tuple[Path, Path, Path] | None:
    """(memory folder, working tree, project root) of the project the session is in; None after saying so."""
    root = records.project_root(Path.cwd(), os.environ)
    if root is None:
        print("mem: not inside a project", file=sys.stderr)
        return None
    return records.project_dir(root), project_syntheses.worktree(Path.cwd(), root, os.environ), root


def _split_part_ref(ref: str) -> tuple[str, str | None]:
    name, sep, handle = ref.removeprefix("p:").partition("#")
    if sep and not handle:
        raise project_syntheses.ProjectSynthesisError(f"{ref!r} has an empty part handle after `#`")
    return name, handle or None


def _existing_parts(found: dict[str, list[project_syntheses.Part]]) -> str:
    return "; ".join(f"p:{n}#{p.handle}" for n, parts in found.items() for p in parts) or "none yet"


def _part_line(name: str, part: project_syntheses.Part, tree: Path) -> str:
    return (
        f"p:{name}#{part.handle}\t{project_syntheses.freshness(tree, part.stamp)}\t{part.heading}"
    )


def _load_project_syntheses(
    memory_dir: Path, name: str | None = None
) -> dict[str, list[project_syntheses.Part]]:
    """The files that load; a broken one does not hide the others, but asking for it by name raises its error."""
    found, broken = project_syntheses.load_each(memory_dir)
    for path, error in broken:
        if name is not None and path == f"{project_syntheses.folder(Path()).as_posix()}/{name}.md":
            raise project_syntheses.Unavailable(f"{path} cannot be read: {error}")
    return found


def _project_synthesis_block(ref: str, memory_dir: Path, tree: Path) -> str:
    """The outline of `p:NAME` or the text of `p:NAME#HANDLE`; ProjectSynthesisError when it does not exist."""
    name, handle = _split_part_ref(ref)
    found = _load_project_syntheses(memory_dir, name)
    parts = found.get(name)
    if parts is None:
        raise project_syntheses.Unavailable(
            f"no project synthesis {name!r}; parts that exist: {_existing_parts(found)}"
        )
    if handle is None:
        return "\n".join(_part_line(name, p, tree) for p in parts)
    part = next((p for p in parts if p.handle == handle), None)
    if part is None:
        raise project_syntheses.Unavailable(
            f"no part {handle!r} in {name}; parts that exist: {_existing_parts(found)}"
        )
    state = project_syntheses.describe(project_syntheses.freshness(tree, part.stamp))
    s = part.stamp
    stamp = project_syntheses._render_stamp(s.paths, s.date, s.commit)
    return f"== p:{name}#{part.handle} ({state})\n{part.heading}\n\n{part.body}\n{stamp}"


def _warn_uncommitted(ref: str) -> None:
    print(
        f"mem: {ref} covers files with uncommitted changes; "
        "it will read possibly stale until you confirm it after committing.",
        file=sys.stderr,
    )


def _ps_list(args: argparse.Namespace, memory_dir: Path, tree: Path) -> int:
    found, broken = project_syntheses.load_each(memory_dir)
    for name, parts in found.items():
        for part in parts:
            print(_part_line(name, part, tree))
    for path, error in broken:
        print(f"mem: skipped {path}: {error}", file=sys.stderr)
    return 1 if broken else 0


def _ps_check_name(name: str) -> None:
    if name not in project_syntheses.NAMES:
        raise project_syntheses.ProjectSynthesisError(
            f"unknown project synthesis {name!r}; use one of: {', '.join(project_syntheses.NAMES)}"
        )


def _ps_add(args: argparse.Namespace, memory_dir: Path, tree: Path) -> int:
    try:
        body = _memory_body(args.body_file)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mem: cannot read the body: {exc}", file=sys.stderr)
        return 2
    _ps_check_name(args.name)
    paths = [p for p in (item.strip() for item in args.paths.split(",")) if p]
    project_syntheses._check_paths(
        tree, paths
    )  # before the secret scan, so a bad path is not reported as a secret
    if _refuse_secret([args.heading, body]):
        return 4
    handle = project_syntheses.write_part(
        memory_dir, tree, args.name, args.heading, body, paths, datetime.date.today()
    )
    ref = f"p:{args.name}#{handle}"
    print(ref)
    if project_syntheses.covers_uncommitted(tree, paths):
        _warn_uncommitted(ref)
    return 0


def _ps_confirm(args: argparse.Namespace, memory_dir: Path, tree: Path) -> int:
    name, handle = _split_part_ref(args.part)
    found = _load_project_syntheses(memory_dir, name)
    if handle is None or name not in found or handle not in [p.handle for p in found[name]]:
        raise project_syntheses.Unavailable(
            f"no part {args.part!r}; parts that exist: {_existing_parts(found)}"
        )
    project_syntheses.confirm_part(memory_dir, tree, name, handle, datetime.date.today())
    print(
        f"p:{name}#{handle}\tconfirmed at {project_syntheses.head_commit(tree) or project_syntheses.NO_COMMIT}"
    )
    part = next(p for p in found[name] if p.handle == handle)
    if project_syntheses.covers_uncommitted(tree, part.stamp.paths):
        _warn_uncommitted(f"p:{name}#{handle}")
    return 0


_PS_HANDLERS = {"list": _ps_list, "add": _ps_add}


def cmd_project_synthesis(args: argparse.Namespace) -> int:
    context = _project_synthesis_context()
    if context is None:
        return 2
    memory_dir, tree, _ = context
    try:
        return _PS_HANDLERS.get(args.ps_command, _ps_confirm)(args, memory_dir, tree)
    except project_syntheses.ProjectSynthesisError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1 if isinstance(exc, project_syntheses.Unavailable) else 2


def cmd_show(args: argparse.Namespace) -> int:
    if args.ranges and not args.outline:
        build_parser().error("--ranges needs --outline")
    if args.outline and args.section:
        print("mem: --outline and --section cannot be used together", file=sys.stderr)
        return 2
    if args.project and _other_projects([args.project], False) is None:
        return 2
    if any(a.startswith(("s:", "p:")) or _is_memory_arg(args, a) for a in args.paths):
        blocks, shown, ok, refused = [], [], True, False
        for arg in args.paths:
            if arg.startswith("p:"):
                if (
                    args.project or args.section
                ):  # refused per handle, so other handles in the call are still shown
                    print(
                        f"mem: --project and --section do not apply to `p:` handles ({arg})",
                        file=sys.stderr,
                    )
                    blocks.append(f"== {arg}\n(not found)")
                    ok, refused = False, True
                    continue
                context = _project_synthesis_context()
                if context is None:
                    return 2
                try:
                    blocks.append(_project_synthesis_block(arg, context[0], context[1]))
                except project_syntheses.ProjectSynthesisError as exc:
                    print(f"mem: {exc}", file=sys.stderr)
                    blocks.append(f"== {arg}\n(not found)")
                    ok = False
                    refused = refused or not isinstance(exc, project_syntheses.Unavailable)
                continue
            if arg.startswith("s:"):
                block = _synthesis_block(args, arg)
                blocks.append(block or f"== {arg}\n(not found)")
                ok = ok and block is not None
                continue
            if _is_memory_arg(args, arg):
                found = _find_memory(args, arg.removeprefix("m:"))
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
            b, sh, o = show(
                args.root, [arg], sections=args.section, outline=args.outline, ranges=args.ranges
            )
            blocks += b
            shown += sh
            ok = ok and o
    else:
        blocks, shown, ok, refused = (
            *show(
                args.root,
                args.paths,
                sections=args.section,
                outline=args.outline,
                ranges=args.ranges,
            ),
            False,
        )
    print("\n\n".join(blocks))
    if ok:
        log_usage(
            args.root,
            {
                "cmd": "show",
                "paths": list(dict.fromkeys(shown)),
                "sections": args.section or [],
                "outline": bool(args.outline),
            },
        )
    return 2 if refused else 0 if ok else 1


_INIT_ALLOWED = {
    "mem-store.yaml",
    "topics.yaml",
    "literature",
    "knowledge",
    "research",
    "memories",
    "templates",
    "syntheses",
    ".git",
    ".gitignore",
    "README.md",
}


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
    named = getattr(args, "project", None)
    if named:  # an explicit, read-only look at another project
        return next(
            (
                m
                for m in records.load_memories(_named_folder(named), "project")
                if m.handle == handle
            ),
            None,
        )
    project = records.project_root(Path.cwd(), os.environ)
    folders = [
        ("project", records.project_dir(project) if project else None),
        ("global", records.memories_root(os.environ, _optional_store(args))),
    ]
    for scope, folder in folders:
        for m in records.load_memories(folder, scope):
            if m.handle == handle:
                return m
    return None


_READ_ONLY_PROJECT = (
    "mem: this project is the store, which is read-only: it has no mem-store.yaml; "
    "a memory cannot be written here."
)
_READ_ONLY_MEMORIES = (
    "mem: the memories folder is inside the store, which is read-only: it has no mem-store.yaml."
)


def _read_only_store(store: Path | None, path: Path) -> bool:
    return (
        store is not None and not records.store_is_writable(store) and records.inside(path, store)
    )


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
# Only a project with a live state memory has written state for the status checker to read (ADR 0030).
_STATUS_LINE = (
    "- Resuming earlier work, or asked where things stand: dispatch memory:memory-status-checker "
    "before reading plans or the backlog yourself."
)
_INDEX_LIMIT = 1500
_CLAIM_LIMIT = 100


_SUPERSEDED_LINE = re.compile(r"^superseded_by:", re.MULTILINE)


def _is_superseded_file(path: Path) -> bool:
    """Whether the frontmatter at the top of the file has `superseded_by`; only the first 16 KB is read."""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            head = f.read(16384)
    except OSError:
        return False
    m = re.match(r"---\r?\n(.*?)\r?\n---", head, re.DOTALL)
    return m is not None and _SUPERSEDED_LINE.search(m.group(1)) is not None


def _count_notes(store: Path) -> int:
    """Notes by file name only: the index runs at every session start and must not read them."""
    try:
        files = [
            p
            for kind in ("literature", "knowledge")
            for p in store.glob(f"{kind}/*/*.md")
            if p.name != "README.md"
        ]
        files += list(store.glob("research/*/README.md"))
        return sum(1 for f in files if not _is_superseded_file(f))
    except OSError:
        return 0


def _readable(memories: Sequence[records.Memory], today: datetime.date) -> list[records.Memory]:
    """What a reader may be shown: live, and not a global lesson still in quarantine. The tools that corroborate or
    look a record up (the identical-claim check, handles, curate, the capture list) load unfiltered. `cmd_search`,
    `cmd_memories` and `cmd_signal` filter `records.quarantined` directly: the first two because `--all-memories` and
    `--dead` still show dead records, the third because it reads the folders itself and shows no liveness."""
    return [m for m in memories if records.is_live(m, today) and not records.quarantined(m)]


def session_index(
    store: Path | None,
    project: Path | None,
    memories: Path | None,
    today: datetime.date,
    *,
    limit: int = 0,
    passes: Mapping[str, datetime.date] | None = None,
    notice: str | None = None,
    stats: dict[str, int] | None = None,
    marks: Mapping[str, frozenset[str]] | None = None,
    tracked: frozenset[str] | None = frozenset(),
) -> str:
    """Text for the start of a session: three generic lines with counts; the project's newest memories when limit > 0.

    `passes` (date of the last curation pass per resolved folder) turns on the "Curation due" count; None leaves it out.
    `marks` holds the decision keys each pass recorded (C100); the count is the keys of `_decisions` not in them.
    `notice` is one more line after the rules (the failure of the automatic curation run).
    The lessons that load as rules follow the notice; `stats`, when given, receives their numbers (rules, rules_left,
    rules_chars). `limit` and `_INDEX_LIMIT` apply to the text without them."""
    try:
        has_store = store is not None and store.is_dir()
        has_memories = memories is not None and memories.is_dir()
    except OSError:
        has_store = has_memories = False
    head = [_INDEX_HEAD]
    due: dict[str, int] = {}
    complete = True
    budget = records.Budget(PAIR_WORK)  # one for both folders, the project's first (C101)
    loaded_global: list[records.Memory] = []

    def due_in(folder: Path, loaded: list[records.Memory], root: Path | None) -> None:
        nonlocal complete
        try:
            key = str(folder.resolve())
            found = _decisions(
                loaded,
                today,
                since=(passes or {}).get(key),
                budget=budget,
                attempts=_fill_attempts(os.environ),
                root=root,
                tracked=tracked,
            )
            known = (marks or {}).get(key, frozenset())
            for k, label in found.keys().items():
                if k not in known:
                    due[label] = due.get(label, 0) + 1
            complete = complete and found.pairs_checked
        except Exception:
            logger.debug("counting a store folder failed", exc_info=True)
            complete = False  # this folder stays out of the count, so the line says "at least"; the rest prints

    if store is not None and has_store:
        head.append(f"Store: {_count_notes(store)} notes.")
    if memories is not None and has_memories:
        loaded_global = records.load_memories(memories, "global")
        live = len(_readable(loaded_global, today))
        head.append(f"Global memories: {live}.")
    loaded_project = records.mark_repository(records.load_memories(project, "project"), tracked)
    if passes is not None and project is not None:
        due_in(project, loaded_project, project.parent)
    if passes is not None and memories is not None and has_memories:
        due_in(memories, loaded_global, None)
    mine = [m for m in loaded_project if records.is_live(m, today)]
    if mine:
        mine.sort(key=lambda m: m.handle)  # stable sorts, least significant key first
        mine.sort(key=lambda m: m.created or datetime.date.min, reverse=True)
        mine.sort(key=lambda m: m.observed, reverse=True)
        mine.sort(key=lambda m: m.kind != "state")  # the project's current situation first
        head.append(f"This project: {len(mine)} memories.")
    total = sum(due.values())
    if total:
        parts = ", ".join(
            f"{due[label]} {label}" for label in _DECISION_LABELS.values() if label in due
        )
        head.append(
            f"Curation due: {'' if complete else 'at least '}{total} {'item' if total == 1 else 'items'} "
            f"({parts}) (after the current task: dispatch memory:memory-curator)."
        )
    if has_memories:
        waiting = sum(
            1 for m in loaded_global if m.triage == "pending" and records.is_live(m, today)
        )
        if waiting:
            head.append(
                f"Triage: {waiting} general lesson{' awaits' if waiting == 1 else 's await'} triage "
                "(mem curate --global)."
            )
    rules_off = _rules_off()
    choice: rules.Choice | None = None
    if not rules_off:
        try:
            choice = rules.choose(loaded_project, loaded_global, today)
        except Exception:
            logger.debug("loading the rules failed", exc_info=True)
            choice = None
    if (
        choice is not None
    ):  # nothing loads when the rules are off, so nothing "got worse after loading"
        try:
            worse = sum(
                1
                for _, loaded in _got_worse(loaded_project, loaded_global, today, choice)
                if loaded
            )
            if worse:
                head.append(
                    f"Got worse: {worse} loaded lesson{' needs' if worse == 1 else 's need'} a decision "
                    "(mem curate)."
                )
        except Exception:
            logger.debug("the session start usage tally failed", exc_info=True)
    lines = [" ".join(head), *_INDEX_RULES.split("\n")[1:]]
    if any(m.kind == "state" for m in mine):
        lines.append(_STATUS_LINE)
    if notice:
        lines.append(notice)
    if store is not None and has_store:
        lines += session_notices.store_due_lines(store, today, data_dir(os.environ))
    extra: list[str] = []
    if rules_off:
        if stats is not None:
            stats.update(rules=0, rules_left=0, rules_chars=0)
    elif choice is not None:
        try:
            layout = _rules_layout()
            digest, topics = _rules_digest(loaded_global, today)
            try:
                extra = rules.block(choice, layout, digest=digest, topics=topics)
                extra += rules.index_lines(choice, digest=digest, topics=topics)
            except Exception:  # a failure in the digest leaves the block without it
                logger.debug("the rules digest failed", exc_info=True)
                extra = rules.block(choice, "grouped" if layout == "digest" else layout)
                more = rules.more_line(choice)
                if more:
                    extra.append(more)
            if stats is not None:
                stats.update(
                    rules=len(choice.loaded),
                    rules_left=len(rules.not_fitted(choice)),
                    rules_chars=len("\n".join(extra)),
                )
        except Exception:
            logger.debug("the rules block failed", exc_info=True)
            extra = []
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
            tail = (
                [f'  … and {len(rows) - shown} more: mem search "<words>" --scope memories']
                if shown < len(rows)
                else []
            )
            text = "\n".join(lines + rows[:shown] + tail)
            if len(text) <= _INDEX_LIMIT or shown == 0:
                return "\n".join(lines + extra + rows[:shown] + tail)
            shown -= 1
    return "\n".join(lines + extra)


def _got_worse(
    project: Sequence[records.Memory],
    global_: Sequence[records.Memory],
    today: datetime.date,
    choice: rules.Choice | None = None,
) -> list[tuple[records.Memory, bool]]:
    """The lessons whose present version got worse (records.got_worse) and that the rules block loads or leaves out
    over the cap; the flag says "loaded". `choose` gets both scopes so that the cap is the one of session start."""
    choice = choice if choice is not None else rules.choose(project, global_, today)
    found = [(m, True) for m in choice.loaded] + [
        (m, False) for m, why in choice.left if why == rules.OVER
    ]
    return [(m, loaded) for m, loaded in found if records.got_worse(m)]


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
    entry = {"t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
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


def _corroborate_failure_line(data: Path | None, now: float) -> str | None:
    """The line `mem session-index` adds after a failed corroboration pass (`mem-corroborate ack` clears it)."""
    if data is None:
        return None
    found = auto_state.failure(
        auto_state.read_json(data / "corroborate" / auto_state.STATUS_NAME), now
    )
    if found is None:
        return None
    reason = " ".join(str(found["reason"]).split())[:200]
    return (
        f"memory: the last corroboration pass failed ({reason}): see mem-corroborate status, "
        "then mem-corroborate ack."
    )


def cmd_session_index(args: argparse.Namespace) -> int:
    """Never fails: the rules matter most when nothing is configured yet. Writes only the hook log, with --hook,
    and the day's due-note count (session_notices.DUE_CACHE_NAME)."""
    started = time.monotonic()
    data = _hook_input() if args.hook else {}
    stats: dict[str, int] = {}
    try:
        store = args.root if isinstance(args.root, Path) else None
        cwd = Path(data["cwd"]) if isinstance(data.get("cwd"), str) and data["cwd"] else Path.cwd()
        if not cwd.is_dir():
            cwd = Path.cwd()
        try:
            project = records.project_root(cwd, os.environ)
        except OSError:
            project = None
        memories = records.memories_root(
            os.environ, store if store is not None and store.is_dir() else None
        )
        notices = []
        for make in (
            lambda: auto_state.failure_line(data_dir(os.environ), store, time.time()),
            lambda: settle_state.failure_line(data_dir(os.environ), store, time.time()),
            lambda: capture_state.failure_line(data_dir(os.environ), time.time()),
            lambda: _corroborate_failure_line(data_dir(os.environ), time.time()),
            lambda: settle_state.settled_line(memories),
        ):
            try:
                found = make()
            except Exception:
                logger.debug("a session start notice failed", exc_info=True)
                found = None
            if found:
                notices.append(found)
        notice = "\n".join(notices) or None
        text = session_index(
            store,
            records.project_dir(project) if project else None,
            memories,
            datetime.date.today(),
            limit=max(args.list, 0),
            passes=read_passes(os.environ),
            notice=notice,
            stats=stats,
            marks=read_marks(os.environ),
            tracked=records.tracked_memories(project) if project else frozenset(),
        )
    except Exception:
        logger.debug("building the session start text failed", exc_info=True)
        text = _INDEX_RULES
        stats.clear()
    print(text)
    if args.hook:
        source = data.get("source")
        _log_hook({
            "hook": "session-index",
            "source": source if isinstance(source, str) else None,
            "ms": int((time.monotonic() - started) * 1000),
            "chars": len(text),
            "rules": stats.get("rules", 0),
            "rules_left": stats.get("rules_left", 0),
            "rules_chars": stats.get("rules_chars", 0),
        })
    return 0


_COMPACT_PARSE_LIMIT = 1_000_000
_COMPACT_OUT_LIMIT = 300
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def cmd_compact_log(args: argparse.Namespace) -> int:
    """Never fails and prints nothing on bad input. Prints the handoff mismatch lines and logs counts only."""
    started = time.monotonic()
    try:
        data = _hook_input() if args.hook else {}
        summary = data.get("compact_summary")
        if not isinstance(summary, str):
            return 0
        text = summary[:_COMPACT_PARSE_LIMIT]
        cwd = Path(data["cwd"]) if isinstance(data.get("cwd"), str) and data["cwd"] else Path.cwd()
        if not cwd.is_dir():
            cwd = Path.cwd()
        found = handoff.parse(text)
        lines = handoff.mismatches(found, cwd)
        trigger, session = data.get("trigger"), data.get("session_id")
        if lines:
            print("\n".join(lines)[:_COMPACT_OUT_LIMIT])
        if args.hook:
            _log_hook({
                "hook": "post-compact",
                "trigger": trigger
                if isinstance(trigger, str) and trigger in {"manual", "auto"}
                else None,
                "session": session
                if isinstance(session, str) and _SESSION_ID.fullmatch(session)
                else None,
                "chars": len(summary),
                "marker": handoff.has_marker(text),
                "handoff": [f for f in handoff.FIELDS if f in found],
                "plan_named": handoff.names_plan(found.get("plan", "")),
                "unrecorded": handoff.unrecorded(text),
                "mismatches": len(lines),
                "ms": int((time.monotonic() - started) * 1000),
            })
    except Exception:
        logger.debug("logging the compact summary failed", exc_info=True)
    return 0


_SIGNAL_LIMIT = 400
_SIGNAL_HANDLES = 3


def signal_text(strong: Sequence[records.Related], possible: Sequence[records.Related]) -> str:
    """The block appended to a subagent's brief: handles and counts only, at most _SIGNAL_LIMIT characters."""
    if not strong:
        return ""
    shown = [
        f"{r.kind}:{r.handle}" for r in strong[:_SIGNAL_HANDLES]
    ]  # only strong matches are named

    def render(items: list[str]) -> str:
        return "\n".join([
            f"[memory] For information: memories related to this task exist (not read yet): {' '.join(items)}",
            (
                f"{len(strong)} strong, {len(possible)} possibly related. Read one with: mem show m:<handle> "
                "(they are files in .memory/)."
            ),
            (
                "They are experience, not fact: where one conflicts with this brief, the brief wins and you report "
                "the conflict."
            ),
        ])

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
        tool_input: Any = None
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
        memories = records.memories_root(
            os.environ, store if store is not None and store.is_dir() else None
        )
        today = datetime.date.today()
        found = records.load_memories(
            records.project_dir(project) if project else None, "project"
        ) + [m for m in records.load_memories(memories, "global") if not records.quarantined(m)]
        strong, possible = records.related_records(
            found, [], brief, today, tokenize=tokenize
        )  # memories only
        text = signal_text(strong, possible)
        if args.hook:
            _log_hook({
                "hook": "signal",
                "ms": int((time.monotonic() - started) * 1000),
                "strong": len(strong),
                "possible": len(possible),
                "subagent_type": subagent_type if isinstance(subagent_type, str) else None,
                "words": len(brief.split()),
            })
        if not text:
            return 0
        if args.hook:
            updated = {**tool_input, "prompt": f"{brief}\n\n{text}"}
            print(
                json.dumps({
                    "hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}
                })
            )
        else:
            print(text)
    except Exception:
        logger.debug("the signal hook failed", exc_info=True)
    return 0


def _check_terms(texts: Sequence[str], kind: str, approved: bool) -> int:
    """0 when a write to the global scope may go on, else its exit code after a message on stderr: 4 for a hard
    term, 5 for a soft one the owner has not approved, 2 when the list cannot be read, created or located (no HOME and
    no XDG_CONFIG_HOME). A missing list is created, so it never blocks."""
    if records.forbidden_file(os.environ) is None:
        print(
            "mem: the forbidden-terms list has no place: neither XDG_CONFIG_HOME nor HOME is set; nothing was written.",
            file=sys.stderr,
        )
        return 2
    try:
        records.ensure_terms_file(os.environ)
        hits = records.term_hits(texts, os.environ, kind)
    except records.ForbiddenListError as exc:
        print(
            f"mem: the forbidden-terms list cannot be read ({exc}); nothing was written.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(
            f"mem: the forbidden-terms list cannot be created ({exc}); nothing was written.",
            file=sys.stderr,
        )
        return 2
    hard = next((t for t in hits if not t.soft), None)
    if hard is not None:
        print(
            f"mem: the text contains a forbidden term (line {hard.line} of the forbidden-terms list); "
            "nothing was written.",
            file=sys.stderr,
        )
        return 4
    soft = next((t for t in hits), None)
    if soft is not None and not approved:
        print(
            f'mem: the text mentions "{soft.text}" (a soft term): ask the owner whether this may be written to the '
            "global scope; if they agree, repeat with --owner-approved.",
            file=sys.stderr,
        )
        return 5
    return 0


def _approval(args: argparse.Namespace) -> dict[str, bool]:
    return {"owner_approved": True} if getattr(args, "owner_approved", False) else {}


def _refuse_secret(texts: Sequence[str]) -> bool:
    """Say so on stderr and return True when a text looks like it holds a secret."""
    name = records.secret_in(texts)
    if name is None:
        return False
    print(
        f"mem: the text looks like it contains a secret ({name}); nothing was written.",
        file=sys.stderr,
    )
    return True


def _add_sightings(
    same: Sequence[records.Memory],
    args: argparse.Namespace,
    today: datetime.date,
    folder: Path,
    project: Path | None,
) -> bool:
    """An identical claim from another session: when both the existing record and this call come from a transcript,
    the session goes onto the existing record. True when the call was handled (the caller still exits 3)."""
    keys = [records.sighting_entry(*f) for f in map(records.sighting, args.source) if f]
    target = next((m for m in same if m.origin == "transcript"), None)
    if target is None or getattr(args, "origin", None) != "transcript" or not keys:
        return False
    added = cased = False
    for key in keys:
        if records.counted(target, key):
            print(f"mem: {key} is already counted for m:{target.handle}.", file=sys.stderr)
            explicit = getattr(args, "outcome", None)
            sid = records.session_key(key)
            if explicit and sid and not records.has_case(target, sid, explicit):
                records.log_before(target, "confirm")
                target, _ = records.add_case(
                    target, key, getattr(args, "seen_on", None) or today, explicit, today
                )
                cased = True
                print(f"mem: case {explicit} added to m:{target.handle}.", file=sys.stderr)
            continue
        records.log_before(target, "confirm")
        target, _ = records.add_sighting(
            target,
            key,
            today,
            outcome=getattr(args, "outcome", None) or "seen",
            on=getattr(args, "seen_on", None),
        )
        added = True
        print(f"mem: {key} added to m:{target.handle}.", file=sys.stderr)
    print(f"m:{target.handle}\t{'sighting' if added else 'case' if cased else 'already counted'}")
    return True


def _check_short_topic(args: argparse.Namespace) -> int | None:
    """Collapse the whitespace of `args.short`, then 2 after a message when it or `args.topic` is not valid
    (empty is allowed: it means none), else None."""
    if args.short and len(args.short.splitlines()) > 1:
        print("mem: the short form must be one line: it has a line break.", file=sys.stderr)
        return 2
    if args.short is not None:
        args.short = " ".join(args.short.split())
    if args.short and not records.valid_short(args.short):
        print(
            f"mem: the short form must be one line of at most {records.SHORT_LIMIT} characters.",
            file=sys.stderr,
        )
        return 2
    if args.topic and not records.valid_topic(args.topic):
        print(
            f"mem: the topic must be one or two lowercase words, at most {records.TOPIC_LIMIT} characters, "
            f'not "other".',
            file=sys.stderr,
        )
        return 2
    return None


def _check_short_claim(args: argparse.Namespace, claim: str) -> int | None:
    """2 after a message when `--user-read` has no `--short`, or a short form the owner did not read is stronger
    than the claim it will sit on; else None."""
    user_read = getattr(args, "user_read", False)
    if user_read and args.short is None:
        print(
            "mem: --user-read goes with --short: it says the owner read that text.", file=sys.stderr
        )
        return 2
    if args.short and not user_read and (reasons := shortcheck.problems(claim, args.short)):
        print(
            "mem: the short form is refused: "
            + "; ".join(reasons)
            + ". Reword it, or pass --user-read if the "
            "owner read this text.",
            file=sys.stderr,
        )
        return 2
    return None


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
    if (refused := _check_short_topic(args)) is not None:
        return refused
    if (refused := _check_short_claim(args, args.claim)) is not None:
        return refused
    if args.is_global:
        folder = records.memories_root(os.environ, store)
        if folder is None:
            print(
                'mem: no folder for global memories: set the plugin\'s "memories" option, '
                'or MEM_MEMORIES, or use a store made with "mem init".',
                file=sys.stderr,
            )
            return 2
        if _read_only_store(store, folder.resolve()):
            print(_READ_ONLY_MEMORIES, file=sys.stderr)
            return 2
        project = None
    else:
        project = records.project_root(Path.cwd(), os.environ)
        if project is None:
            print(
                "mem: not inside a git repository: pass --global, or set MEM_PROJECT to the project folder.",
                file=sys.stderr,
            )
            return 2
        folder = records.project_dir(project)
        if _read_only_store(store, project) or _read_only_store(store, folder.resolve()):
            print(_READ_ONLY_PROJECT, file=sys.stderr)
            return 2
    if not args.source and (getattr(args, "outcome", None) or getattr(args, "seen_on", None)):
        print("mem: --outcome and --seen-on need --source.", file=sys.stderr)
        return 2
    if getattr(args, "seen_on", None) is not None and args.seen_on > today:
        print("mem: --seen-on cannot be later than today.", file=sys.stderr)
        return 2
    scope = "global" if args.is_global else "project"
    if args.kind in {"finding", "document"} and not args.source:
        print(f"mem: a {args.kind} needs at least one --source.", file=sys.stderr)
        return 2
    try:
        body = _memory_body(args.body_file)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mem: cannot read the body: {exc}", file=sys.stderr)
        return 2
    if _refuse_secret([args.claim, args.context or "", body, *args.source, args.short or ""]):
        return 4
    if args.is_global:
        refused = _check_terms(
            [
                args.claim,
                args.context or "",
                body,
                *args.source,
                records.slug_of(args.claim),
                args.short or "",
            ],
            args.kind,
            args.owner_approved,
        )
        if refused:
            return refused
    if getattr(args, "origin", None) == "transcript":
        for source in args.source:
            if (
                " ".join(source.split()).lower().startswith(records.SESSION_PREFIX)
                and records.sighting(source) is None
            ):
                print(
                    f"mem: --source {source!r} is not a session entry: write 'session <id>' or "
                    f"'session <id> project <{records.PROJECT_KEY_LEN} hex characters>'.",
                    file=sys.stderr,
                )
                return 2
    from_session = getattr(args, "origin", None) == "transcript" and any(
        map(records.session_key, args.source)
    )
    if getattr(args, "origin", None) == "transcript" and args.valid_until is not None:
        draft = records.Memory(
            scope,
            folder,
            "",
            args.kind,
            args.claim,
            today,
            1,
            "active",
            None,
            None,
            records.normalized_sources(args.source),
            "",
            None,
            origin="transcript",
            weight=getattr(args, "weight", None),
        )
        if records.standing(draft) != "established":
            print(
                f"mem: --valid-until is refused: the life of a record from a transcript is "
                f"{records.UNCONFIRMED_DAYS} days from the last session that showed it.",
                file=sys.stderr,
            )
            return 2
    claim_tokens = tokenize(args.claim)
    existing = records.load_memories(folder, scope)
    live = [m for m in existing if records.is_live(m, today)]
    if not args.force:
        lapsed = [
            m
            for m in existing
            if from_session
            and m.error is None
            and m.status == "active"
            and m.origin == "transcript"
            and m not in live
        ]
        same = [m for m in live + lapsed if _same_claim(m.claim, args.claim)]
        if same:
            seen = _add_sightings(same, args, today, folder, project)
            if seen:
                return 3
            for m in same:
                print(f"m:{m.handle}\t{m.claim}", file=sys.stderr)
            print(
                f'mem: a memory with the same claim exists; run "mem observe m:{same[0].handle}" if it is the same, '
                "or repeat with --force to write a new one.",
                file=sys.stderr,
            )
            return 3
    related = records.match_memories(_readable(live, today), claim_tokens, today, tokenize=tokenize)
    exclude_failed = False
    if project is not None:
        try:
            records.ensure_excluded(project)
        except OSError:
            exclude_failed = True
    try:
        m = records.write_memory(
            folder,
            scope,
            kind=args.kind,
            claim=args.claim,
            body=body,
            today=today,
            context=args.context,
            valid_until=args.valid_until,
            sources=args.source,
            origin=getattr(args, "origin", None),
            reach=getattr(args, "reach", None),
            weight=getattr(args, "weight", None),
            short=args.short or None,
            topic=args.topic or None,
            short_by="model" if args.short and not getattr(args, "user_read", False) else None,
            outcome=getattr(args, "outcome", None),
            on=getattr(args, "seen_on", None),
        )
    except (ValueError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    _register_project(project)
    rel = m.path.relative_to(project if project is not None else folder).as_posix()
    print(f"m:{m.handle}\t{rel}")
    if exclude_failed:
        print(
            "mem: could not add .memory/ to .git/info/exclude; the folder may appear in git status.",
            file=sys.stderr,
        )
    if related:
        print(
            'related memories (if one is the same, run "mem observe m:<handle>"; if one says the opposite, keep both):',
            file=sys.stderr,
        )
        for r in related:
            print(
                f"m:{r.handle}\t[{r.kind}, observed {r.observed}, {r.created.isoformat() if r.created else '?'}]\t{r.claim}",
                file=sys.stderr,
            )
    log_usage(store, {"cmd": "remember", "scope": scope, **_approval(args)})
    if (
        scope == "global"
        and getattr(args, "origin", None) != "pipeline"
        and not records.quarantined(m)
    ):
        settle_state.maybe_start(folder, store, os.environ, time.time(), today)
    return 0


def _memory_of(args: argparse.Namespace, handles: Sequence[str]) -> list[records.Memory] | None:
    """The named memories, all in one scope: the project's unless --global; None after a message on stderr.

    A handle found in both scopes means the project one, as for any lookup; with several handles the scope is
    one that holds all of them, and handles that exist only in different scopes are refused."""
    project = records.project_root(Path.cwd(), os.environ)
    folders = {
        "project": records.project_dir(project) if project else None,
        "global": records.memories_root(os.environ, _optional_store(args)),
    }
    loaded = {
        scope: {m.handle: m for m in records.load_memories(folder, scope)}
        for scope, folder in folders.items()
    }
    order = ("global",) if args.is_global else ("project", "global")
    names = [h.removeprefix("m:") for h in handles]
    for name, raw in zip(names, handles, strict=False):
        if not any(name in loaded[scope] for scope in order):
            print(f"mem: no memory named {raw}", file=sys.stderr)
            return None
    for scope in order:
        if all(name in loaded[scope] for name in names):
            found = [loaded[scope][name] for name in names]
            break
    else:
        print(
            f"mem: {' and '.join('m:' + n for n in names)} are in different scopes: both must be in the same one.",
            file=sys.stderr,
        )
        return None
    store = _optional_store(args)
    for m in found:
        if m.error is not None:
            print(f"mem: {m.path}: {m.error}", file=sys.stderr)
            return None
        if _read_only_store(store, m.path.resolve()):
            print(
                _READ_ONLY_PROJECT if m.scope == "project" else _READ_ONLY_MEMORIES, file=sys.stderr
            )
            return None
    return found


def _with_note(body: str, heading: str, text: str) -> str:
    """The body with a heading line and the text under it added at the end."""
    head = body.rstrip("\n")
    return (
        f"{head}\n\n{heading}\n{text.strip()}\n" if head.strip() else f"{heading}\n{text.strip()}\n"
    )


def _reason_allowed(memory: records.Memory, because: str | None, approved: bool) -> int:
    """0 when the reason may be written: it goes through the secret patterns; one written into a global memory also
    through the term list, failing closed. Else the exit code, after a message."""
    if not because:
        return 0
    if _refuse_secret([because]):
        return 4
    if memory.scope != "global":
        return 0
    return _check_terms([because], memory.kind, approved)


def _act(
    args: argparse.Namespace,
    handles: Sequence[str],
    apply: Callable[[list[records.Memory], datetime.date], list[str]],
    name: str,
    because: str | None = None,
) -> int:
    found = _memory_of(args, handles)
    if found is None:
        return 2
    refused = _reason_allowed(found[0], because, getattr(args, "owner_approved", False))
    if refused:
        return refused
    try:
        lines = apply(found, datetime.date.today())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if found[0].scope == "project":
        _register_project(records.project_root(Path.cwd(), os.environ))
    print("\n".join(lines))
    log_usage(_optional_store(args), {"cmd": name, "scope": found[0].scope, **_approval(args)})
    return 0


def _add_plain_source(
    memory: records.Memory, source: str, today: datetime.date, note: str | None
) -> records.Memory:
    """A source (URL, path or session) appended once to a memory that is not from a transcript, with the note."""
    changes: dict = {}
    if source not in memory.sources:
        changes["sources"] = [*memory.sources, source]
    if note and note.strip():
        head = memory.body if memory.body.endswith("\n") or not memory.body else memory.body + "\n"
        changes["body"] = f"{head}{' '.join(note.split())}\n"
    return records.update(memory, today, **changes) if changes else memory


def cmd_confirm(args: argparse.Namespace) -> int:
    repeated: list[bool] = []

    def apply(found, today):
        until = getattr(args, "until", None)
        if until is not None:
            try:
                until = datetime.date.fromisoformat(until)
            except ValueError:
                raise ValueError(f"--until needs a date as YYYY-MM-DD, not {until!r}") from None
        source = getattr(args, "source", None)
        if source is None and getattr(args, "note", None):
            raise ValueError("--note needs --source")
        if source is None and (getattr(args, "outcome", None) or getattr(args, "seen_on", None)):
            raise ValueError("--outcome and --seen-on need --source")
        if getattr(args, "seen_on", None) is not None and args.seen_on > today:
            raise ValueError("--seen-on cannot be later than today")
        from_transcript = found[0].origin == "transcript"
        key = records.session_key(source) if source is not None else None
        if getattr(args, "by_owner", False):
            if source is not None or until is not None:
                raise ValueError("--by-owner stands alone: it takes no --source or --until")
            m = found[0]
            if m.origin != "transcript":
                raise ValueError(
                    f"m:{m.handle} is not from a transcript: the owner's confirmation applies to a "
                    "lesson captured from one"
                )
            if m.status != "active":
                raise ValueError(
                    f"m:{m.handle} is {m.status}: the owner confirms only an active memory"
                )
            if m.owner_confirmed:
                repeated.append(True)
                return [f"m:{m.handle}\talready confirmed by the owner: nothing changed"]
            records.log_before(m, "confirm")
            after = dataclasses.replace(m, owner_confirmed=today)
            records.update(
                m, today, owner_confirmed=today, **records.standing_changes(m, after, today)
            )
            return [f"m:{m.handle}\tconfirmed by the owner"]
        if source is not None and not source.strip():
            raise ValueError("--source is empty")
        if source is not None and from_transcript and key is None:
            raise ValueError(f"--source takes a session ('session <id>'), not {source!r}")
        if until is not None and records.standing(found[0]) == "unconfirmed":
            raise ValueError(
                "a record from a transcript is confirmed only by another session showing it: "
                "use --source 'session <id>', not --until"
            )
        if source is not None and found[0].status != "active":
            raise ValueError(
                f"m:{found[0].handle} is {found[0].status}: a source is added only to an active memory"
            )
        seen = {records.session_key(s) or s.strip() for s in found[0].sources}
        already = (
            records.counted(found[0], source)
            if from_transcript and source is not None
            else (source is not None and (key or source.strip()) in seen)
        )
        outcome = (
            getattr(args, "outcome", None) or "seen"
        )  # `seen` is the default, resolved here so that
        seen_on = getattr(args, "seen_on", None)  # a counted session gets a case only on request
        if already:
            repeated.append(True)
            if (
                from_transcript
                and key
                and source is not None  # a session key comes only from a source
                and getattr(args, "outcome", None)
                and not records.has_case(found[0], key, outcome)
            ):
                records.log_before(found[0], "confirm")
                found[0], _ = records.add_case(found[0], source, seen_on or today, outcome, today)
                repeated.pop()  # a case was written: the call changed something
                if until is None:
                    return [f"m:{found[0].handle}\tcase {outcome} added"]
                records.update(found[0], today, valid_until=until)
                return [
                    f"m:{found[0].handle}\tcase {outcome} added; valid until {until.isoformat()}"
                ]
            if until is None:
                return [f"m:{found[0].handle}\t{source} is already a source: nothing changed"]
            records.log_before(
                found[0], "confirm"
            )  # the source is not counted again; the date is still set
            records.update(found[0], today, valid_until=until)
            return [
                f"m:{found[0].handle}\t{source} is already a source; valid until {until.isoformat()}"
            ]
        records.log_before(found[0], "confirm")
        if source is not None and from_transcript:
            updated, _ = records.add_sighting(
                found[0], source, today, args.note, outcome=outcome, on=seen_on
            )
        else:
            updated = records.observe(found[0], today)
            if source is not None:
                updated = _add_plain_source(updated, source.strip(), today, args.note)
        if until is not None:
            updated = records.update(updated, today, valid_until=until)
        return [f"m:{updated.handle}\tobserved {updated.observed}"]

    code = _act(args, [args.handle], apply, args.command, because=getattr(args, "note", None))
    return 3 if code == 0 and repeated else code


def _text_change(
    found: list[records.Memory],
    key: str,
    heading: str,
    because: str | None,
    today: datetime.date,
    **extra,
) -> records.Memory:
    m = found[0]
    records.log_before(m, {"refuted": "refute", "forgotten": "forget"}[key])
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
        _text_change(
            found, "forgotten", "Forgotten", args.because, today, triage=None, triage_reason=None
        )
        return [f"m:{found[0].handle}\tforgotten"]

    return _act(args, [args.handle], apply, "forget", args.because)


def _linked_project_records(handle: str) -> list[records.Memory]:
    """Step 1 of a reject: every project record, in every counted project, whose `general` names `handle`.
    ValueError, with nothing changed yet, when a registry, a folder or a file that may name it cannot be read."""
    named = re.compile(rf"^general:\s*['\"]?{re.escape(handle)}['\"]?\s*$", re.MULTILINE)
    found = []
    try:
        projects = corroborate.counted_projects(records.read_registry(data_dir(os.environ)))
        for n, project in enumerate(projects, 1):
            folder = records.project_dir(project)
            try:  # os.listdir raises on a folder that cannot be read; Path.glob would return nothing
                files = [folder / name for name in os.listdir(folder) if name.endswith(".md")]
            except OSError as exc:
                raise ValueError(
                    f"project memory folder {n} of {len(projects)} cannot be read ({exc})"
                ) from exc
            for m in records.load_memories(folder, "project"):
                if m.error is None:
                    if m.general == handle:
                        found.append(m)
                elif m.path in files and named.search(
                    m.path.read_text(encoding="utf-8", errors="replace")
                ):
                    raise ValueError(
                        f"project record m:{m.handle} names it in `general` but cannot be parsed "
                        f"({m.error})"
                    )
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"reject stopped while looking for the project records that name it: {exc}; "
            "no change was made"
        ) from exc
    return found


def _reject(found: list[records.Memory], today: datetime.date) -> list[str]:
    m = found[0]
    linked = _linked_project_records(
        m.handle
    )  # before any change: a refusal leaves everything as it was
    done: list[str] = []
    try:
        for record in linked:
            records.log_before(record, "triage")
            records.update(record, today, promote="no", general=None)
            done.append(f"m:{record.handle}")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(
            f"reject failed while unlinking the project records ({exc}); unlinked so far: "
            f"{', '.join(done) or 'none'}; the global record is still active"
        ) from exc
    try:
        _text_change(found, "forgotten", "Forgotten", None, today, triage=None, triage_reason=None)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(
            f"reject failed while retiring m:{m.handle} ({exc}); the project records were already "
            f"unlinked: {', '.join(done) or 'none'}; the global record is still active"
        ) from exc
    return [
        f"m:{m.handle}\trejected",
        f"unlinked {len(done)} project record{'' if len(done) == 1 else 's'}",
        *(f"{h}\tunlinked" for h in done),
    ]


def cmd_triage(args: argparse.Namespace) -> int:
    """Accept or reject a general lesson that left quarantine, on the global scope; accept also keeps the wording
    of a lesson that got worse, and with --project-scope that lesson may be a project one."""
    args.is_global = not getattr(args, "project_scope", False)
    because = None
    if args.triage_command == "hold":
        because = " ".join((args.because or "").split())
        if not because or not records.valid_triage_reason(because):
            print(
                f"mem: hold needs --because, one line of at most {records.TRIAGE_REASON_LIMIT} characters.",
                file=sys.stderr,
            )
            return 2

    def apply(found, today):
        m = found[0]
        if (
            getattr(args, "project_scope", False) and m.scope != "project"
        ):  # the lookup falls back to the global scope
            raise ValueError(f"no memory named m:{m.handle}")
        if args.triage_command == "hold":
            if m.status != "active":
                raise ValueError(f"m:{m.handle} is {m.status}: only an active lesson can be held")
            if records.quarantined(m):
                raise ValueError(
                    f"m:{m.handle} is in quarantine: it is not shown anyway until corroborated"
                )
            records.log_before(m, "triage")
            records.update(m, today, triage="pending", triage_reason=because)
            return [f"m:{m.handle}\theld"]
        if m.status != "active":
            raise ValueError(
                f"m:{m.handle} is {m.status}: only an active general lesson awaits triage"
            )
        if args.triage_command == "accept" and m.triage != "pending" and records.got_worse(m):
            records.log_before(m, "triage")
            records.update(m, today, reviewed=today)
            return [f"m:{m.handle}\tkept as worded"]
        if m.triage != "pending":
            if records.quarantined(m):
                raise ValueError(
                    f"m:{m.handle} is still in quarantine: it leaves quarantine when seen in a second "
                    "project or confirmed with mem confirm --by-owner"
                )
            raise ValueError(f"m:{m.handle} was already accepted or never awaited triage")
        if args.triage_command == "accept":
            records.log_before(m, "triage")
            records.update(m, today, triage=None, triage_reason=None)
            return [f"m:{m.handle}\taccepted"]
        return _reject(found, today)

    return _act(args, [args.handle], apply, f"triage-{args.triage_command}", because)


def _two(args: argparse.Namespace, first: str, second: str, name: str, apply) -> int:
    if first.removeprefix("m:") == second.removeprefix("m:"):
        print(f"mem: {name} needs two different memories.", file=sys.stderr)
        return 2
    return _act(args, [first, second], apply, name)


def _supersede_pair(old: records.Memory, new: records.Memory, today: datetime.date) -> list[str]:
    records.log_before(old, "supersede")
    records.update(old, today, status="superseded", superseded_by=new.handle)
    return [f"m:{old.handle}\tsuperseded by m:{new.handle}"]


def cmd_supersede(args: argparse.Namespace) -> int:
    def apply(found: list[records.Memory], today: datetime.date) -> list[str]:
        return _supersede_pair(found[0], found[1], today)

    return _two(args, args.old, args.new, "supersede", apply)


def _reword_failed(args: argparse.Namespace) -> int:
    """`mem memory edit <h> --reword-failed`: note the version the automatic rewording gave up on; nothing else changes."""
    others = (args.claim, args.context, args.body_file, args.short, args.topic)
    if (
        any(o is not None for o in others)
        or args.no_load
        or args.load
        or args.index_only
        or args.reworded
        or args.user_read
    ):
        print(
            "mem: --reword-failed stands alone: it changes no other part of the lesson.",
            file=sys.stderr,
        )
        return 2
    found = _memory_of(args, [args.handle])
    if found is None:
        return 2
    m = found[0]
    versions = records.version_list(m)
    if not versions:
        print(f"mem: m:{m.handle} has no short form version to give up on.", file=sys.stderr)
        return 2
    log = m.path.parent / records.CURATION_LOG
    log_before = log.read_bytes() if log.exists() else None
    original = m.path.read_bytes()
    updating = False
    try:
        records.log_before(m, "edit")
        updating = True
        records.update(m, datetime.date.today(), reword_failed=versions[-1][0])
    except (
        OSError,
        ValueError,
        yaml.YAMLError,
    ) as exc:  # any failure leaves the memory and its log as they were
        if updating and m.path.read_bytes() != original:
            _swap_file(m.path, original)
        if log_before is None:
            log.unlink(missing_ok=True)
        else:
            safe_io.replace_file(log, log_before)
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"m:{m.handle}\tedited reword failed")
    log_usage(
        _optional_store(args),
        {"cmd": "memory", "action": "edit", "scope": m.scope, **_approval(args)},
    )
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    """`mem memory edit`: the claim, context or body of a memory, through the guard, with undo."""
    if args.reword_failed:
        return _reword_failed(args)
    if args.reworded and (not args.short or args.user_read):
        print(
            "mem: --reworded goes with a non-empty --short and without --user-read: it marks a model's rewording.",
            file=sys.stderr,
        )
        return 2
    if (
        args.claim is None
        and args.context is None
        and args.body_file is None
        and args.short is None
        and args.topic is None
        and not args.no_load
        and not args.load
        and not args.index_only
    ):
        build_parser().error(
            "memory edit needs --claim, --context, --body-file, --short, --topic, --no-load, --index-only or --load"
        )
    claim = " ".join(args.claim.split()) if args.claim is not None else None
    context = " ".join(args.context.split()) if args.context is not None else None
    try:
        body = _read_body(args.body_file) if args.body_file else None
    except NewNoteError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if claim is not None and not claim:
        print("mem: the claim is empty.", file=sys.stderr)
        return 2
    if (refused := _check_short_topic(args)) is not None:
        return refused
    texts = [t for t in (claim, context, body, args.short) if t]
    if _refuse_secret(texts):
        return 4
    found = _memory_of(args, [args.handle])
    if found is None:
        return 2
    m = found[0]
    if m.status != "active":
        print(
            f"mem: m:{m.handle} is {m.status}: run mem restore m:{m.handle} to bring it back before editing it.",
            file=sys.stderr,
        )
        return 2
    if (refused := _check_short_claim(args, claim if claim is not None else m.claim)) is not None:
        return refused
    if (
        m.scope == "global"
        and texts
        and (refused := _check_terms(texts, m.kind, getattr(args, "owner_approved", False)))
    ):
        return refused
    log = m.path.parent / records.CURATION_LOG
    log_before = log.read_bytes() if log.exists() else None
    try:
        original = m.path.read_bytes()
        what = []
        short_removed = False
        changes: dict[str, Any] = {}
        if claim is not None:
            if not args.shrink:
                syntheses._guard_shrink(m.claim, claim, sentences=False)
            changes["claim"] = claim
            what.append("claim")
        if context is not None:
            changes["context"] = context or None
            what.append("context")
        if body is not None:
            if not args.shrink:
                syntheses._guard_shrink(m.body.strip("\n"), body.strip("\n"))
            changes["body"] = body
            what.append("body")
        if args.short is not None:
            changes["short"] = args.short or None
            changes["short_by"] = "model" if args.short and not args.user_read else None
            if args.reworded:
                changes["reworded"] = datetime.date.today()
            what.append("short")
        elif claim is not None and claim != m.claim and (m.short or m.short_by):
            changes["short"] = None  # a short form never outlives the claim it was drawn from
            changes["short_by"] = None
            if m.short:
                what.append("short removed")
                short_removed = True
        if args.topic is not None:
            changes["topic"] = args.topic or None
            what.append("topic")
        if args.no_load:
            changes["load"] = "no"
            what.append("load")
        elif args.index_only:
            changes["load"] = "index"
            what.append("load")
        elif args.load:
            changes["load"] = None
            what.append("load")
        updating = False
        try:
            records.log_before(m, "edit")
            if m.path.read_bytes() != original:
                raise ValueError(
                    f"{m.path.name} changed since it was read, so nothing was written: run the command again"
                )
            updating = True
            records.update(m, datetime.date.today(), **changes)
        except BaseException:  # any failure leaves the memory and its log as they were
            if updating and m.path.read_bytes() != original:
                _swap_file(m.path, original)
            if log_before is None:
                log.unlink(missing_ok=True)
            else:
                safe_io.replace_file(log, log_before)
            raise
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if m.scope == "project":
        _register_project(records.project_root(Path.cwd(), os.environ))
    if short_removed:
        print(
            "mem: the short form was removed with the old claim: write a new one with --short",
            file=sys.stderr,
        )
    print(f"m:{m.handle}\tedited {', '.join(what)}")
    log_usage(
        _optional_store(args),
        {"cmd": "memory", "action": "edit", "scope": m.scope, **_approval(args)},
    )
    if m.scope == "global" and m.origin != "pipeline":
        settle_state.maybe_start(
            m.path.parent, _optional_store(args), os.environ, time.time(), datetime.date.today()
        )
    return 0


def _merge_pair(keep: records.Memory, drop: records.Memory, today: datetime.date) -> list[str]:
    records.log_before(keep, "merge")
    records.log_before(drop, "merge")
    records.update(drop, today, status="superseded", superseded_by=keep.handle)
    changes: dict[str, Any] = {"observed": keep.observed + drop.observed}
    if drop.body.strip():
        changes["body"] = _with_note(
            keep.body, f"Merged from m:{drop.handle} on {today.isoformat()}:", drop.body
        )
    if "transcript" in {
        keep.origin,
        drop.origin,
    }:  # a session must survive the merge, whichever record holds it
        sources = records.normalized_sources([*keep.sources, *drop.sources])
        changes["sources"] = sources
        if keep.origin == "transcript":
            after = dataclasses.replace(keep, sources=sources)
            standing_changes = records.standing_changes(keep, after, today)
            if records.standing(after) == "established" or len(records.sessions(after)) > len(
                records.sessions(keep)
            ):
                changes.update(
                    standing_changes
                )  # enough evidence now, or a new session renews the 30 days
    log = records.merged_log(keep, drop)
    if log != keep.log:
        changes["log"] = log
    versions = records.merged_versions(keep, drop, today)
    if versions and versions != keep.versions:
        changes["versions"] = versions
    updated = records.update(keep, today, **changes)
    return [f"m:{updated.handle}\tobserved {updated.observed}, merged m:{drop.handle}"]


def cmd_merge(args: argparse.Namespace) -> int:
    def apply(found, today):
        keep, drop = found
        flagged = records.flagged_words(keep.claim, drop.claim)
        if flagged and not args.force:
            raise ValueError(
                f"these claims differ in {', '.join(flagged)}: they may be opposites or different "
                "versions; use --force to merge anyway."
            )
        return _merge_pair(keep, drop, today)

    return _two(args, args.keep, args.drop, "merge", apply)


def _distinct_notes(args: argparse.Namespace, store: Path) -> int | None:
    """`mem distinct` for two notes of the store; None when the arguments are not both notes."""
    if args.a.startswith("m:") or args.b.startswith("m:"):
        return None
    first, second = resolve_note(store, args.a), resolve_note(store, args.b)
    if not isinstance(first, Path) or not isinstance(second, Path):
        return None
    root = _writable_store(args, "distinct")
    if root is None:
        return 2
    root = root.resolve()
    if first == second:
        print("mem: distinct needs two different notes.", file=sys.stderr)
        return 2
    try:
        names = {p: note_files._handle(p.relative_to(root).as_posix()) for p in (first, second)}
        originals, edits = {}, {}
        for path, other in ((first, second), (second, first)):
            text = note_files._read_text(path)
            meta, _, _ = split_frontmatter(text)
            listed = meta.get("distinct_from") if isinstance(meta, dict) else None
            known = [h for h in listed if isinstance(h, str)] if isinstance(listed, list) else []
            originals[path], edits[path] = (
                path.read_bytes(),
                _set_field(text, "distinct_from", sorted({*known, names[other]})),
            )
        for path, text in edits.items():
            safe_io.replace_file(path, text.encode("utf-8"))
        _log_group(root, originals, "distinct")
    except (OSError, ValueError, FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"{names[first]}\tkept apart from {names[second]}")
    log_usage(root, {"cmd": "distinct", "scope": "note"})
    return 0


def _distinct_pair(a: records.Memory, b: records.Memory, today: datetime.date) -> list[str]:
    for m in (a, b):
        records.log_before(m, "distinct")
    for m, other in ((a, b), (b, a)):
        records.update(m, today, distinct_from=sorted({*m.distinct_from, other.handle}))
    return [f"m:{a.handle}\tkept apart from m:{b.handle}"]


def cmd_distinct(args: argparse.Namespace) -> int:
    store = _optional_store(args)
    if store is not None and store.is_dir() and (done := _distinct_notes(args, store)) is not None:
        return done

    def apply(found: list[records.Memory], today: datetime.date) -> list[str]:
        return _distinct_pair(found[0], found[1], today)

    return _two(args, args.a, args.b, "distinct", apply)


def _writable_store(args: argparse.Namespace, command: str) -> Path | None:
    root = args.root
    if not isinstance(root, Path) or not root.is_dir():
        print(NO_STORE, file=sys.stderr)
        return None
    if not records.store_is_writable(root):
        print(
            f"mem: {command} writes to the store, which is read-only: it has no mem-store.yaml "
            '(create a store with "mem init").',
            file=sys.stderr,
        )
        return None
    return root


def _restore_synthesis(args: argparse.Namespace) -> int:
    root = _writable_store(args, "restore")
    if root is None:
        return 2
    handle, section = syntheses.split_ref(args.handle)
    path = syntheses.path_of(root / syntheses.SYNTHESES_DIR, handle)
    if section is not None or path is None or not path.is_file():
        print(f"mem: no synthesis named {args.handle}", file=sys.stderr)
        return 2
    syn = syntheses.Synthesis(path, handle)
    entry = records.last_log_entry(syn)
    rel = f"{syntheses.SYNTHESES_DIR}/{path.name}"
    group = records.last_log_entry(
        _StoreLog(root / "note", rel)
    )  # a rename or remove logs its files as a group
    if (
        group is not None
        and group.get("group")
        and (entry is None or _sha(path.read_bytes()) == group.get("after"))
    ):
        # the file is as the group's action left it (or has no own entry): the group is the newest change; when
        # the file differs, a change came after the group and its own entry is the one to undo
        return _restore_group(root, rel, group, f"s:{handle}")
    if entry is None:
        print(f"mem: no logged text for s:{handle}: nothing to restore", file=sys.stderr)
        return 2
    if entry["skipped"]:
        print(
            f"mem: skipped {entry['skipped']} unreadable lines in the curation log", file=sys.stderr
        )
    try:
        records.restore(syn, entry)
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"s:{handle}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]}")
    log_usage(root, {"cmd": "restore", "scope": "synthesis"})
    return 0


@dataclass
class _StoreLog:
    """A note's entry in the store-level `.curation-log` (the log sits beside `path`, the store's root)."""

    path: Path
    handle: str


def _restore_group(root: Path, rel: str, entry: dict, label: str | None = None) -> int:
    """Undo every file of the unify, rename or distinct that logged `entry`, or none: refused when any changed since.

    A README listing that changed since is left alone (not a refusal) and rebuilt by `apply_index`; one that is
    as the action left it gets its exact previous bytes back."""
    lines = (root / records.CURATION_LOG).read_text(encoding="utf-8").split("\n")
    members: list[tuple[int, dict]] = []
    undone: set[int] = set()
    for number, line in enumerate(lines):
        try:
            logged = json.loads(line)
        except ValueError:
            continue
        if not isinstance(logged, dict):
            continue
        if logged.get("action") == "restore" and isinstance(logged.get("undone"), int):
            undone.add(logged["undone"])
        elif logged.get("group") == entry["group"] and isinstance(logged.get("before"), str):
            members.append((number, logged))
    members = [(n, e) for n, e in members if n not in undone]

    def current(e: dict) -> bool:
        return (root / e["handle"]).is_file() and _sha((root / e["handle"]).read_bytes()) == e.get(
            "after"
        )

    listing = {n: check_rules._is_index_readme(e["handle"]) for n, e in members}
    moved = [e["handle"] for n, e in members if not listing[n] and not current(e)]
    if moved:
        print(
            f"mem: {', '.join(moved)} changed since {entry.get('action')}, so nothing was restored: "
            "restore or edit those files by hand",
            file=sys.stderr,
        )
        return 2
    kept = [(n, e) for n, e in members if not listing[n] or current(e)]
    rebuild = not any(listing.values()) or len(kept) < len(members)
    members = kept
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        for number, e in members:
            target = root / e.get("from", e["handle"])
            safe_io.replace_file(target, e["before"].encode("utf-8"))
            if "from" in e:
                (root / e["handle"]).unlink()
                sources, was = (
                    root / SOURCES_DIR / Path(e["handle"]).stem,
                    root / SOURCES_DIR / Path(e["from"]).stem,
                )
                if sources.is_dir() and not was.exists():
                    sources.rename(was)
            marker = {"t": stamp, "action": "restore", "handle": e["handle"], "undone": number}
            safe_io.append_text(
                root / records.CURATION_LOG, json.dumps(marker, ensure_ascii=False) + "\n"
            )
        if rebuild:
            apply_index(root)
    except (OSError, FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(
        f"{label or note_files._handle(rel)}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]} "
        f"({len(members)} files)"
    )
    log_usage(root, {"cmd": "restore", "scope": "note"})
    return 0


def _restore_note(args: argparse.Namespace, root: Path, note: Path) -> int:
    rel = note.relative_to(root.resolve()).as_posix()
    log = _StoreLog(root / "note", rel)
    entry = records.last_log_entry(log)
    if entry is None:
        print(
            f"mem: no logged text for {note_files._handle(rel)}: nothing to restore",
            file=sys.stderr,
        )
        return 2
    if entry.get("group"):
        return _restore_group(root, rel, entry)
    try:
        safe_io.replace_file(note, entry["before"].encode("utf-8"))
        marker = {
            "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "action": "restore",
            "handle": rel,
            "undone": entry["line"],
        }
        safe_io.append_text(
            root / records.CURATION_LOG, json.dumps(marker, ensure_ascii=False) + "\n"
        )
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(
        f"{note_files._handle(rel)}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]}"
    )
    log_usage(root, {"cmd": "restore", "scope": "note"})
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    if args.handle.startswith("s:"):
        return _restore_synthesis(args)
    if not args.handle.startswith("m:"):
        store = _optional_store(args)
        if store is not None and isinstance(found := resolve_note(store, args.handle), Path):
            root = _writable_store(args, "restore")
            return 2 if root is None else _restore_note(args, root, found)

    def apply(found, today):
        m = found[0]
        entry = records.last_log_entry(m)
        if entry is None:
            raise ValueError(f"no logged text for m:{m.handle}: nothing to restore")
        if entry["skipped"]:
            print(
                f"mem: skipped {entry['skipped']} unreadable lines in the curation log",
                file=sys.stderr,
            )
        records.restore(m, entry)
        return [
            f"m:{m.handle}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]}"
        ]

    return _act(args, [args.handle], apply, "restore")


def cmd_promote(args: argparse.Namespace) -> int:
    args.is_global = False
    if args.to and not args.done:
        print("mem: --to goes with --done.", file=sys.stderr)
        return 2
    target = None
    if args.to:
        target = args.to.removeprefix("m:")
        if not any(
            m.handle == target and m.error is None
            for m in records.load_memories(
                records.memories_root(os.environ, _optional_store(args)), "global"
            )
        ):
            print(f"mem: --to names no global memory: {args.to}", file=sys.stderr)
            return 2
    if args.no or args.done:
        value, text = ("no", "not to be promoted") if args.no else ("done", "promoted")
        extra = {"general": target} if target else {}

        def apply(found, today):
            records.log_before(found[0], "promote")
            records.update(found[0], today, promote=value, **extra)
            return [f"m:{found[0].handle}\t{text}"]

        for handle in args.handles:
            if _act(args, [handle], apply, "promote") != 0:
                return 2
        return 0
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
    print(
        "Rewrite the claim in general terms, with no name of a project, system, client or person, "
        "before you run it; then run: mem promote --done <h>"
    )
    return 0


def _loaded(
    folders: Sequence[tuple[str, Path | None]],
) -> list[tuple[str, Path | None, list[records.Memory]]]:
    out = []
    for scope, folder in folders:
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
    if args.project:
        named = _other_projects([args.project], False)
        if named is None:
            return 2
        folder = _named_folder(args.project)
        if folder is not None and not folder.is_dir():
            print(
                f"mem: the memory folder of project {args.project} was not found: {folder} (moved or deleted?)",
                file=sys.stderr,
            )
            return 2
        folders = [("project", folder)]
    else:
        folders = _memory_folders(args)
        if not args.all:
            folders = [f for f in folders if (f[0] == "global") == args.is_global]
    shown = [
        m
        for _, _, loaded in _loaded(folders)
        for m in loaded
        if m.error is None
        and (args.kind is None or m.kind == args.kind)
        and (
            args.dead or records.is_live(m, today) or (args.quarantine and m.status == "active")
        )  # a lapsed lesson in quarantine is still listed
        and records.quarantined(m) == args.quarantine
    ]
    shown.sort(
        key=lambda m: (m.kind != "state", -(m.created or datetime.date.min).toordinal(), m.handle)
    )
    for m in shown:
        dead = _memory_status(m, today)
        created = m.created.isoformat() if m.created else "undated"
        print(
            f"m:{m.handle}\t[{m.kind}, observed {m.observed}, {created}{_unconfirmed(m)}"
            f"{', quarantine' if args.quarantine else ''}"
            f"{', ' + dead if dead else ''}]\t{_flat(m.claim)}"
        )
    return 0


RULES_OFF_NOTICE = "Loaded rules are switched off (plugin option loaded_rules): nothing below loads at session start."


def _rules_layout(arg: str | None = None) -> str:
    """`--layout` wins, then MEM_RULES_LAYOUT (set by the hooks from the option rules_layout); only `grouped` and `digest` switch."""
    env = os.environ.get("MEM_RULES_LAYOUT")
    return arg or (env if env in {"grouped", "digest"} else "flat")


def _rules_digest(
    global_lessons: list[records.Memory], today: datetime.date
) -> tuple[dict | None, dict | None]:
    """The digest file and the topics it may speak for, (None, None) when either cannot be read: callers then print without it."""
    try:
        data = digest.read(data_dir(os.environ))
        return (data, digest.topics_of(global_lessons, today)) if data["topics"] else (None, None)
    except Exception:
        logger.debug("reading the rules digest failed", exc_info=True)
        return None, None


def _rules_off() -> bool:
    return os.environ.get("MEM_LOADED_RULES") == "off"


def _rules_unread(args: argparse.Namespace, today: datetime.date) -> int:
    """`--unread` lists the short forms a model wrote that nobody read; `--read` marks them read."""
    if args.unread and args.read:
        print("mem: --unread and --read cannot be used together.", file=sys.stderr)
        return 2
    scopes = _loaded(_memory_folders(args))
    pool = [
        m
        for _, _, loaded in scopes
        for m in loaded
        if m.error is None and records.is_live(m, today)
    ]
    unread = [m for m in pool if m.short_by == "model" and m.short]
    if args.unread:
        for m in unread:
            print(f"m:{m.handle}\t{m.scope}\t{m.short}\n\tclaim: {_flat(m.claim)}")
        if not unread:
            print("No short form is waiting to be read.")
        return 0
    if args.read == ["all"]:
        targets = unread
    else:
        targets = []
        for raw in args.read:
            name = raw.removeprefix("m:")
            hit = next(
                (m for m in pool if m.handle == name), None
            )  # project first: the order of the scopes
            if hit is None:
                print(f"mem: no live memory named {raw}", file=sys.stderr)
                return 2
            targets.append(hit)
    store = _optional_store(args)
    for m in targets:
        if _read_only_store(store, m.path.resolve()):
            print(
                _READ_ONLY_PROJECT if m.scope == "project" else _READ_ONLY_MEMORIES, file=sys.stderr
            )
            return 2
    for m in targets:
        if m.short_by:
            records.log_before(m, "edit")
            records.update(m, today, short_by=None)
        print(f"m:{m.handle}\tread")
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    """Print the rules block and the line after it exactly as session start does; --more lists what was left out."""
    today = datetime.date.today()
    if args.unread or args.read:
        return _rules_unread(args, today)
    (_, _, project), (_, _, global_) = _loaded(_memory_folders(args))
    try:
        root = records.project_root(Path.cwd(), os.environ)
    except OSError:
        root = None
    project = records.mark_repository(
        project, records.tracked_memories(root) if root else frozenset()
    )
    choice = rules.choose(project, global_, today)
    if _rules_off():
        print(RULES_OFF_NOTICE)
    unready = f"{choice.unready} established lesson{' has' if choice.unready == 1 else 's have'} no short form yet"
    # the pass skips the fill while the loaded rules are off (`cmd_auto` of mem-corroborate)
    attempts = _fill_attempts(os.environ)
    stuck = (
        0
        if _rules_off()
        else sum(
            1
            for m in choice.unready_lessons
            if (root is not None or m.scope != "project")
            and corroborate.fill_wont_write(
                m, root if m.scope == "project" else None, attempts, today
            )
        )
    )
    if _rules_off():
        unready += "."
    elif stuck == choice.unready:
        unready += (
            ": the automatic fill will not write "
            f"{'it, so it needs' if stuck == 1 else 'them, so they need'} curation (mem curate)."
        )
    elif stuck:
        unready += (
            f": {stuck} need{'s' if stuck == 1 else ''} curation (mem curate), the background pass writes the "
            f"{'other' if choice.unready - stuck == 1 else 'others'} when auto_capture is on (mem-corroborate status shows the last one)."
        )
    else:
        unready += ": the background pass writes them when auto_capture is on (mem-corroborate status shows the last one)."
    if args.more is not None:
        topic = None if args.more is True else args.more
        shown = [
            (m, why)
            for m, why in choice.left
            if topic is None or (m.topic or "other") == topic or (topic == "other" and not m.topic)
        ]
        order = [t for t, _ in rules.topic_counts(choice)] + [None]
        for group in order:
            for m, why in (x for x in shown if x[0].topic == group):
                claim = _flat(m.claim)
                claim = (
                    claim
                    if len(claim) <= _CLAIM_PREVIEW_CHARS
                    else claim[: _CLAIM_PREVIEW_CHARS - 1] + "\u2026"
                )
                print(
                    f"m:{m.handle}\t{m.scope}\t{why}\t{rules.standing_words(m)}\t{m.topic or '-'}\t{claim}\t{records.mark_words(m) or '-'}"
                )
        if shown:
            print("mem show m:<handle> prints a whole lesson.")
        else:
            print("No lessons left out" + (f" under {topic}." if topic else "."))
        if choice.unready:
            print(unready)
        return 0
    digest, topics = _rules_digest(global_, today)
    lines = rules.block(choice, _rules_layout(args.layout), digest=digest, topics=topics)
    print("\n".join(lines) if lines else "No rules loaded.")
    index = rules.index_lines(choice, digest=digest, topics=topics)
    if index:  # also alone: index-only lessons are reachable when no rule loads
        print("\n".join(index))
    if not lines and choice.unready:
        print(unready)
    failed = [
        (m, words)
        for m in [*choice.loaded, *(m for m, why in choice.left if why == rules.OVER)]
        if (words := records.mark_words(m))
    ]
    if failed:
        print("Failed after it loaded:")
        for m, words in failed:
            print(f"m:{m.handle}\t{words}")
    return 0


_STALE_DAYS = 90
_FREQUENT = 3
_STANDING_KINDS = (
    "constraint",
    "decision",
    "state",
)  # no date makes them stale: only a refutation retires them


def _passes_file(env: Mapping[str, str]) -> Path | None:
    folder = data_dir(env)
    return folder / "curated.json" if folder is not None else None


def read_passes(env: Mapping[str, str]) -> dict[str, datetime.date]:
    """Date of the last pass per memory folder (resolved path), from the data folder; {} when unknown."""
    path = _passes_file(env)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path is not None else {}
        return {k: datetime.date.fromisoformat(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _write_passes(env: Mapping[str, str], covered: Sequence[Path], today: datetime.date) -> None:
    path = _passes_file(env)
    if path is None:
        raise OSError("no data folder: set MEM_DATA or HOME")
    known = {k: v.isoformat() for k, v in read_passes(env).items()}
    known.update({str(f.resolve()): today.isoformat() for f in covered})
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(path, (json.dumps(known, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _marks_file(env: Mapping[str, str]) -> Path | None:
    folder = data_dir(env)
    return folder / "curated-items.json" if folder is not None else None


def _parse_marks(text: str) -> dict[str, frozenset[str]]:
    try:
        return {
            k: frozenset(v)
            for k, v in json.loads(text).items()
            if isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
        }
    except (ValueError, AttributeError, TypeError):
        return {}


def read_marks(env: Mapping[str, str]) -> dict[str, frozenset[str]]:
    """Decision keys recorded by the last pass per memory folder (resolved path); anything unreadable reads as none."""
    path = _marks_file(env)
    try:
        return _parse_marks(path.read_text(encoding="utf-8")) if path is not None else {}
    except (OSError, ValueError):  # ValueError: not UTF-8
        return {}


def _write_marks(env: Mapping[str, str], covered: Mapping[Path, Collection[str]]) -> None:
    """Replace the keys of the covered folders only; `curated.json` is not touched (C100)."""
    path = _marks_file(env)
    if path is None:
        raise OSError("no data folder: set MEM_DATA or HOME")
    # a missing or malformed file starts empty; one that exists but cannot be read raises, so no key is dropped
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except UnicodeDecodeError:  # malformed, not unreadable
        text = ""
    known = {k: sorted(v) for k, v in _parse_marks(text).items()}
    known.update({str(f.resolve()): sorted(keys) for f, keys in covered.items()})
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(path, (json.dumps(known, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _tagged(m: records.Memory, extra: str = "") -> str:
    created = m.created.isoformat() if m.created else "undated"
    return f"  m:{m.handle}  [{m.kind}, {created}{extra}]  {_flat(m.claim)}"


def _differ_in(a: str, b: str) -> str:
    words = records.differing_words(a, b)
    return f"differ in: {', '.join(words)}" if words else "differ in: wording only"


PAIR_WORK = 150_000  # claim comparisons the session start line may spend on pair searches, both folders together
_DECISION_LABELS = {
    "refuted": "refuted again",
    "pair": "same or opposite",
    "state": "newer state",
    "expired": "expired",
    "seen": "seen often",
    "stale": f"not confirmed in {_STALE_DAYS} days",
    "nofill": "no short form",
}


@dataclass(frozen=True)
class Decisions:
    """The decision items of one folder's curation queue (C98): `mem curate` prints them, the count counts them."""

    refuted: list[tuple[records.Memory, records.Memory]]  # (live, refuted)
    same: list[tuple[records.Memory, records.Memory]]
    state: list[tuple[records.Memory, records.Memory]]  # (old, new)
    expired: list[records.Memory]
    seen: list[records.Memory]
    stale: list[records.Memory]
    nofill: list[
        records.Memory
    ]  # established lessons the automatic short-form fill will not write (`fill_wont_write`)
    pairs_checked: bool

    def keys(self) -> dict[str, str]:
        """Each item's key (C100) with the label of its part."""
        found: dict[str, str] = {}
        for a, r in self.refuted:
            found[f"refuted:{a.handle}|{r.handle}"] = _DECISION_LABELS["refuted"]
        for a, b in self.same:
            found[f"pair:{'|'.join(sorted((a.handle, b.handle)))}"] = _DECISION_LABELS["pair"]
        for old, new in self.state:
            found[f"state:{old.handle}|{new.handle}"] = _DECISION_LABELS["state"]
        for name, items in (
            ("expired", self.expired),
            ("seen", self.seen),
            ("stale", self.stale),
            ("nofill", self.nofill),
        ):
            for m in items:
                found[f"{name}:{m.handle}"] = _DECISION_LABELS[name]
        return found


def _unconfirmed_handles(memories: Sequence[records.Memory]) -> set[str]:
    """Handles of the unconfirmed memories: they have their own category, so the other blocks skip them."""
    return {m.handle for m in memories if records.standing(m) == "unconfirmed"}


def _changed_since(live: Sequence[records.Memory], since: datetime.date) -> list[str]:
    """Handles of the memories changed on or after `since`, newest change first: created then, or its file written
    then (local time), or no `created`, or the file cannot be read."""
    found = []
    for m in live:
        try:
            written: datetime.date | None = datetime.date.fromtimestamp(m.path.stat().st_mtime)
        except OSError:
            written = None
        if m.created is not None and written is not None and m.created < since and written < since:
            continue
        found.append((
            max(m.created, written)
            if m.created is not None and written is not None
            else datetime.date.max,
            m.handle,
        ))
    found.sort(key=lambda t: (-t[0].toordinal(), t[1]))
    return [h for _, h in found]


def _fill_attempts(env: Mapping[str, str]) -> dict:
    """The automatic short-form fill's attempts (`fill_key` -> entry), read defensively: a missing, unreadable or
    malformed state reads as no attempts, so curation never fails on it."""
    data = data_dir(env)
    lessons = (
        auto_state.read_json(data / "corroborate" / "fill-attempts.json").get("lessons")
        if data
        else None
    )
    return lessons if isinstance(lessons, dict) else {}


def _decisions(
    loaded: Sequence[records.Memory],
    today: datetime.date,
    *,
    since: datetime.date | None = None,
    budget: records.Budget | None = None,
    attempts: dict | None = None,
    root: Path | None = None,
    tracked: frozenset[str] | None = frozenset(),
) -> Decisions:
    """The decision items of one folder from what `records.load_memories` returned: superseded memories and
    unreadable files are left out. With `since` the pair kinds compare only pairs with a memory changed since then;
    `budget` is spent by those comparisons. `attempts` (`_fill_attempts`) turns on the "no short form" kind; `root` is
    the project root of a project folder, None for the global one, and `tracked` its `records.tracked_memories`."""
    kept = [m for m in loaded if m.error is None and m.superseded_by is None]
    live = [m for m in kept if records.is_live(m, today)]
    among = _changed_since(live, since) if since is not None else None
    again = [
        (a, r)
        for a, r, _ in records.refuted_pairs(
            kept, today, tokenize=tokenize, among=among, budget=budget
        )
    ]
    same: list[tuple[records.Memory, records.Memory]] = []
    state: list[tuple[records.Memory, records.Memory]] = []
    for a, b, _ in records.pairs(kept, today, tokenize=tokenize, among=among, budget=budget):
        if (
            a.kind == "state" and b.kind == "state" and a.scope == b.scope == "project"
        ):  # C103: a project matter
            old, new = sorted((a, b), key=lambda m: (m.created or datetime.date.min, m.handle))
            state.append((old, new))
        else:
            same.append((a, b))
    unconfirmed = _unconfirmed_handles(kept)
    expired = [
        m
        for m in kept
        if m.status == "active"
        and m.valid_until is not None
        and m.valid_until < today
        and m.handle not in unconfirmed
    ]
    seen = [
        m for m in live if m.scope == "project" and m.observed >= _FREQUENT and not m.promote
    ]  # a global one cannot be promoted
    cutoff = today - datetime.timedelta(days=_STALE_DAYS)
    stale = [
        m
        for m in live
        if m.kind not in _STANDING_KINDS
        and m.created is not None
        and m.handle not in unconfirmed
        and max(m.created, m.last_observed or m.created) <= cutoff
    ]
    nofill = [
        m
        for m in (records.mark_repository(kept, tracked) if root else kept)
        if attempts is not None and corroborate.fill_wont_write(m, root, attempts, today)
    ]
    return Decisions(
        again, same, state, expired, seen, stale, nofill, budget is None or not budget.exhausted
    )


def _grouped_pairs(pairs: Sequence[tuple[records.Memory, records.Memory]]) -> list[str]:
    """C102: the memory in the most remaining pairs first (ties by handle) with its line, then one indented line per
    partner (its tag and claim, two spaces deeper) with its `differ in` below; each pair once."""
    left = list(pairs)
    out: list[str] = []
    while left:
        count: collections.Counter = collections.Counter()
        for a, b in left:
            count.update([(a.scope, a.handle), (b.scope, b.handle)])
        top = min(count, key=lambda k: (-count[k], k[1], k[0]))
        rest = []
        head = left[0][0]  # overwritten: `top` is a member of some pair
        lines = []
        for a, b in left:
            if (a.scope, a.handle) == top:
                head, other = a, b
            elif (b.scope, b.handle) == top:
                head, other = b, a
            else:
                rest.append((a, b))
                continue
            lines.append((
                other.handle,
                f"  {_tagged(other)}",
                f"      {_differ_in(head.claim, other.claim)}",
            ))
        out.append(_tagged(head))
        for _, line, differ in sorted(lines):
            out += [line, differ]
        left = rest
    return out


TOPIC_CROWD = 8
TOPIC_LOOSE = 5  # of them, knowledge notes not yet part of any synthesis


def _note_line(note: Note) -> str:
    return (
        f"  {note_files._handle(note.rel)}  [{note.meta.get('confidence', '')}, {note.meta.get('updated', '')}]  "
        f"{_flat(str(note.meta.get('claim', '')))}"
    )


def _note_pairs(notes: Sequence[Note]) -> list[tuple[Note, Note]]:
    """Pairs of notes that share a topic and whose claims contain each other with at least `records.STRONG`,
    unless one names the other in `distinct_from`; the closest pair first."""
    notes = sorted(notes, key=lambda n: note_files._handle(n.rel))
    tokens = [set(tokenize(str(n.meta.get("claim", "")))) for n in notes]
    found = []
    for i, a in enumerate(notes):
        for j in range(i + 1, len(notes)):
            b = notes[j]
            if not set(a.meta.get("topics") or []) & set(b.meta.get("topics") or []):
                continue
            if note_files._handle(b.rel) in (
                a.meta.get("distinct_from") or []
            ) or note_files._handle(a.rel) in (b.meta.get("distinct_from") or []):
                continue
            score = max(
                records.containment(tokens[i], tokens[j]), records.containment(tokens[j], tokens[i])
            )
            if score >= records.STRONG:
                found.append((score, a, b))
    found.sort(key=lambda t: (-t[0], note_files._handle(t[1].rel), note_files._handle(t[2].rel)))
    return [(a, b) for _, a, b in found]


def _curate_notes(args: argparse.Namespace) -> int:
    root = args.root
    if root is None:
        print("mem: curate --notes needs a store", file=sys.stderr)
        return 2
    synths = [x for x in syntheses.load(root / syntheses.SYNTHESES_DIR) if x.error is None]
    try:
        known = load_topics(root)
    except FrontmatterError:
        known = {}
    unattached, stale, disputed = [], [], []
    for note in discover_notes(root):
        if note.type != "knowledge" or note.error is not None or not isinstance(note.meta, dict):
            continue
        if check_rules._disputed(note.meta.get("disputed")) is None:
            disputed.append(
                f"  {note_files._handle(note.rel)}  {_flat(str(note.meta.get('claim', '')))}  "
                f"(source: {note.meta['disputed'][0]['source']})"
            )
        part = note.meta.get("part_of")
        name = note_files._handle(note.rel)
        if not isinstance(part, str):
            topics = [t for t in note.meta.get("topics", []) if isinstance(t, str)]
            own = set(_own_topics(known, topics))
            covering = [x for x in synths if own & set(x.topics)]
            if covering:
                unattached.append(
                    f"  {name}  \u2192  {', '.join('s:' + x.handle for x in covering)}  "
                    f"{_flat(str(note.meta.get('claim', '')))}"
                )
            continue
        handle, _, section = part.partition("#")
        syn = next((x for x in synths if x.handle == handle), None)
        sec = next((x for x in syn.sections if x.handle == section), None) if syn else None
        if sec is not None and not syntheses.is_current(
            note.meta.get("part_of_hash"), sec.text, _note_target(note.rel)
        ):
            stale.append(f"  {name}  s:{handle}#{section}")
    out = []
    if disputed:
        out.append(
            "notes disputed by a source (decide: correct the note with mem note edit, "
            "or mem note dispute <note> --clear)"
        )
        out += disputed
    if unattached:
        out.append(
            "notes on a topic that has a synthesis, not yet part of it (add what the note says to a part with "
            "mem synthesis append or add, then: mem synthesis attach <note> s:<h>#<section>)"
        )
        out += unattached
    if stale:
        out.append(
            "notes older than their section (rewrite the note from the section: mem show s:<h>#<section>)"
        )
        out += stale
    live = [
        n
        for n in discover_notes(root)
        if n.error is None and isinstance(n.meta, dict) and n.meta.get("superseded_by") is None
    ]
    same = _note_pairs([n for n in live if n.type == "knowledge"])
    if same:
        out.append(
            "notes that say the same or the opposite? (decide: mem unify <keep> <other> --body-file \u2026, "
            "mem distinct <a> <b>, or leave)"
        )
        for a, b in same:
            out += [
                _note_line(a),
                _note_line(b),
                f"  {_differ_in(str(a.meta.get('claim', '')), str(b.meta.get('claim', '')))}",
            ]
    covered = {t for x in synths for t in x.topics}
    counts: collections.Counter = collections.Counter()
    loose: collections.Counter = (
        collections.Counter()
    )  # knowledge notes that are part of no synthesis
    for n in live:
        if n.type in {"knowledge", "literature"}:
            own = _own_topics(known, [t for t in n.meta.get("topics", []) if isinstance(t, str)])
            counts.update(own)
            if n.type == "knowledge" and not n.meta.get("part_of"):
                loose.update(own)
    # A topic whose notes already sit in other syntheses is not worth a document of its own.
    crowded = sorted(
        (
            (t, c)
            for t, c in counts.items()
            if c >= TOPIC_CROWD and t not in covered and loose[t] >= TOPIC_LOOSE
        ),
        key=lambda tc: (-tc[1], tc[0]),
    )
    if crowded:
        out.append(f"topics with {TOPIC_CROWD} notes or more and no synthesis (mem synthesis new)")
        out += [f"  {t}  {c} notes" for t, c in crowded]
    if out:
        print("\n".join(out))
    return 0


_PROJECT_SYNTHESIS_MIN_MEMORIES = 5


def _curate_project_syntheses(
    scopes: Sequence[tuple[str, Path | None, list[records.Memory]]], today: datetime.date
) -> list[str]:
    """The two project synthesis blocks of `mem curate`: parts possibly stale, and none written yet."""
    context = _project_synthesis_context_quiet()
    if context is None:
        return []
    memory_dir, tree = context
    found, broken = project_syntheses.load_each(memory_dir)
    out: list[str] = []
    if broken:
        out.append("-- project syntheses: unreadable --")
        out += [f"{path}\t{error}" for path, error in broken]
    states = [
        (name, part, project_syntheses.freshness(tree, part.stamp))
        for name, parts in found.items()
        for part in parts
    ]
    stale = [
        (name, part, state) for name, part, state in states if state != project_syntheses.FRESH
    ]
    if stale:
        out.append("-- project syntheses: possibly stale --")
        out += [
            f"p:{name}#{part.handle}\t{project_syntheses.describe(state)}"
            for name, part, state in stale
        ]
    active = sum(
        1
        for scope, _, loaded in scopes
        if scope == "project"
        for m in loaded
        if m.error is None and records.is_live(m, today)
    )
    if not found and not broken and active >= _PROJECT_SYNTHESIS_MIN_MEMORIES:
        out += [
            "-- project syntheses: none yet --",
            f"{active} active memories and no project synthesis: organize them (see the memory-curation skill).",
        ]
    return out


def _project_synthesis_context_quiet() -> tuple[Path, Path] | None:
    """(memory folder, working tree) of the project the session is in; None outside a project, silently."""
    try:
        root = records.project_root(Path.cwd(), os.environ)
    except OSError:
        return None
    if root is None:
        return None
    return records.project_dir(root), project_syntheses.worktree(Path.cwd(), root, os.environ)


def _claim_key(claim: str) -> str:
    """A claim for the safe-merge test: case, whitespace and trailing punctuation do not count."""
    return " ".join(claim.lower().split()).rstrip(" .,;:!?")


def _parse_actions(text: str) -> list[tuple[str, list[str]]]:
    """(raw line, words) of each action line; blank lines and `#` comments dropped. ValueError on a known verb
    with the wrong number of arguments, so a malformed file applies nothing."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        words = line.split()
        if words[0] == "merge" and len(words) != _CURATE_LINE_WORDS:
            raise ValueError(f"malformed line (merge m:<keep> m:<drop>): {line}")
        if words[0] == "attach" and len(words) != _CURATE_LINE_WORDS:
            raise ValueError(f"malformed line (attach <note> s:<h>#<section>): {line}")
        out.append((" ".join(words), words))
    return out


def _last_error(buf: io.StringIO, default: str) -> str:
    lines = [ln.removeprefix("mem: ").strip() for ln in buf.getvalue().splitlines() if ln.strip()]
    return lines[-1] if lines else default


def _curate_merge_refusal(a: records.Memory, b: records.Memory) -> str | None:
    """Why two memories must not be merged automatically; None when they are the same claim, both active, in one
    scope."""
    if a.handle == b.handle:
        return "the same memory twice"
    if a.scope != b.scope:
        return "different scopes"
    for m in (a, b):
        if m.status != "active" or m.superseded_by is not None:
            return f"m:{m.handle} is {m.status}"
    if _claim_key(a.claim) != _claim_key(b.claim):
        return "the claims are not equal"
    return None


def _safe_merge(args: argparse.Namespace, keep: str, drop: str) -> str | None:
    """None after the merge ran; else why it was left. Only equal claims, both active, in one scope; never --force."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        found = _memory_of(args, [keep, drop])
    if found is None:
        return _last_error(err, "memories not found")
    refusal = _curate_merge_refusal(*found)
    if refusal is not None:
        return refusal
    ns = argparse.Namespace(**{**vars(args), "keep": keep, "drop": drop, "force": False})
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cmd_merge(ns)
    return None if code == 0 else _last_error(err, "the merge was refused")


def _curate_attach_refusal(root: Path, found: Path, target: str) -> str | None:
    """Why the note must not be attached automatically to `target`; None when the part's `Sources:` line links it and
    it is not part of a synthesis yet."""
    try:
        syn, sec = _section_ref(root, target)
        part = split_frontmatter(note_files._read_text(found))[0].get("part_of")
    except (ValueError, OSError, FrontmatterError) as exc:
        return str(exc)
    if part:
        return f"the note is already part of s:{part}"
    cited = {(syn.path.parent / s).resolve() for s in sec.sources}
    if found.resolve() not in cited:
        return "the part's Sources line does not link the note"
    return None


def _safe_attach(args: argparse.Namespace, note: str, target: str) -> str | None:
    """None after the attach ran; else why it was left. Only when the part's `Sources:` line links the note and the
    note is not part of a synthesis yet."""
    root = args.root
    if not isinstance(root, Path) or not root.is_dir() or not records.store_is_writable(root):
        return "no writable store"
    found = resolve_note(root, note)
    if isinstance(found, list):
        return "the note name is ambiguous"
    if found is None:
        return "no such note"
    refusal = _curate_attach_refusal(root, found, target)
    if refusal is not None:
        return refusal
    ns = argparse.Namespace(root=root, note=note, target=target)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = _attach(ns)
    return None if code == 0 else _last_error(err, "the attach was refused")


def _curate_run_action(args: argparse.Namespace, words: list[str]) -> str | None:
    """None after the action ran; else why it was left."""
    if words[0] == "merge":
        return _safe_merge(args, words[1], words[2])
    if words[0] == "attach":
        return _safe_attach(args, words[1], words[2])
    return f"not a safe action ({words[0]})"


def _curate_apply(args: argparse.Namespace) -> int:
    """`mem curate apply --safe`: action lines from a file or stdin; only what the code can prove safe runs."""
    if not args.safe:
        print("mem: curate apply runs only with --safe: there is no unsafe mode.", file=sys.stderr)
        return 2
    try:
        text = (
            sys.stdin.read()
            if args.from_file in {None, "-"}
            else Path(args.from_file).read_text(encoding="utf-8")
        )
        actions = _parse_actions(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    applied = left = 0
    for line, words in actions:
        why = _curate_run_action(args, words)
        if why is None:
            applied += 1
            print(f"applied\t{line}")
        else:
            left += 1
            print(f"left\t{line}\t{why}")
    print(f"applied {applied}, left {left}")
    return 0


def _curate_new_since(args: argparse.Namespace) -> int:
    """Print how many global memories and notes of the store were written after `--new-since` (epoch seconds) and
    after the last curation pass of the global memories (its day counts as passed). File times: an edit counts as new.
    The trigger of `mem-auto`."""
    store = args.root
    cutoff = float(args.new_since)
    memories = records.memories_root(
        os.environ, store if store is not None and store.is_dir() else None
    )
    paths: list[Path] = []
    if memories is not None and memories.is_dir():
        last = read_passes(os.environ).get(str(memories.resolve()))
        if last is not None:
            cutoff = max(
                cutoff,
                datetime.datetime.combine(
                    last + datetime.timedelta(days=1), datetime.time.min
                ).timestamp(),
            )
        today = datetime.date.today()
        paths += [
            m.path
            for m in records.load_memories(memories, "global")
            if m.error is None and records.is_live(m, today) and m.origin is None
        ]  # a pipeline's own writes must not start the next run
    if store is not None and store.is_dir():
        paths += [store / n.rel for n in discover_notes(store) if n.error is None]
    count = 0
    for path in paths:
        try:
            count += path.stat().st_mtime > cutoff
        except OSError:
            continue
    print(count)
    return 0


type _CurateScopes = Sequence[tuple[str, Path | None, list[records.Memory]]]


@dataclass(frozen=True)
class _CuratePass:
    """The folders a `mem curate done` pass covers, with the decision keys and the scope label of each."""

    covered: list[Path]
    keys: dict[Path, set[str]]
    labels: dict[Path, str]


def _curate_pass_keys(folder: Path, scope: str, attempts: dict, today: datetime.date) -> set[str]:
    """The decision keys of one folder's queue, as `mem curate done` records them."""
    root = folder.parent if scope == "project" else None
    return set(
        _decisions(
            records.load_memories(folder, scope),
            today,
            attempts=attempts,
            root=root,
            tracked=records.tracked_memories(root) if root else frozenset(),
        ).keys()
    )


def _curate_pass_of(
    store: Path | None, scopes: _CurateScopes, attempts: dict, today: datetime.date
) -> _CuratePass | None:
    """The folders a pass covers; None after a message on stderr when one of them is read-only."""
    covered = []
    keys: dict[Path, set[str]] = {}
    labels: dict[Path, str] = {}
    for scope, folder, _ in scopes:
        if folder is None or not folder.is_dir():
            continue
        if _read_only_store(store, folder.resolve()):
            print(
                _READ_ONLY_PROJECT if scope == "project" else _READ_ONLY_MEMORIES,
                file=sys.stderr,
            )
            return None
        covered.append(folder)
        keys[folder] = _curate_pass_keys(folder, scope, attempts, today)
        labels[folder] = scope
    return _CuratePass(covered, keys, labels)


def _curate_record_pass(passed: _CuratePass, today: datetime.date) -> int:
    """Write the marks and the pass dates of the covered folders and say how many items each held; 2 when the write
    fails."""
    if not passed.covered:
        return 0
    try:
        _write_marks(
            os.environ, passed.keys
        )  # first: a failed write leaves the pass date where it was
        _write_passes(os.environ, passed.covered, today)
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    for folder in sorted(passed.covered, key=lambda f: passed.labels[f] != "global"):
        n = len(passed.keys[folder])
        print(f"recorded {n} {'item' if n == 1 else 'items'} ({passed.labels[folder]})")
    return 0


def _curate_commit_pass(store: Path | None, today: datetime.date) -> None:
    """Commit the store after a pass and trim its logs."""
    if store is not None and store_git.is_repo(store):
        _, failed = _commit_points(store, lambda n: f"curation pass {today.isoformat()}: {n} files")
        # git holds the older states now: the logs keep 30 days. Not while an automatic run may be appending
        # to them, and under the commit lock so a commit never sees a half-written log.
        if not failed and not auto_state.run_lock_held(data_dir(os.environ), store):
            store_git.trim_logs_locked(store)


def _curate_done(
    args: argparse.Namespace, scopes: _CurateScopes, attempts: dict, today: datetime.date
) -> int:
    """`mem curate --done`: record the pass over the folders loaded."""
    store = _optional_store(args)
    passed = _curate_pass_of(store, scopes, attempts, today)
    if passed is None:
        return 2
    code = _curate_record_pass(passed, today)
    if code != 0:
        return code
    _curate_commit_pass(store, today)
    return 0


def _curate_decisions(
    scopes: _CurateScopes, attempts: dict, today: datetime.date
) -> list[Decisions]:
    """The decision items of each scope, in order."""
    roots = [
        folder.parent if scope == "project" and folder else None for scope, folder, _ in scopes
    ]
    return [
        _decisions(
            loaded,
            today,
            attempts=attempts,
            root=root,
            tracked=records.tracked_memories(root) if root else frozenset(),
        )
        for root, (_, _, loaded) in zip(roots, scopes, strict=False)
    ]


def _curate_refuted_lines(found: Sequence[Decisions]) -> list[str]:
    again = [pair for d in found for pair in d.refuted]
    if not again:
        return []
    out = [
        (
            "written again after being refuted (decide: mem refute <h>, or mem distinct <a> <b> if it is a "
            "different claim)"
        )
    ]
    for a, r in again:
        out += [_tagged(a), _tagged(r, ", refuted")]
    return out


def _curate_same_lines(found: Sequence[Decisions]) -> list[str]:
    same = [pair for d in found for pair in d.same]
    if not same:
        return []
    header = (
        "same or opposite? (decide: mem merge <keep> <drop>, or keep both and say so in the body)"
    )
    return [header, *_grouped_pairs(same)]


def _curate_state_lines(found: Sequence[Decisions]) -> list[str]:
    state = [pair for d in found for pair in d.state]
    if not state:
        return []
    out = [
        "newer state of the same project? (decide: mem supersede <old> <new>, or mem distinct <a> <b>)"
    ]
    for old, new in state:
        out += [_tagged(old), f"    -> {_tagged(new).lstrip()}"]
    return out


def _curate_expired_lines(found: Sequence[Decisions]) -> list[str]:
    expired = [m for d in found for m in d.expired]
    if not expired:
        return []
    out = ["expired (decide: mem forget <h>, or mem confirm <h> --until <date> if it still holds)"]
    out += [
        f"  m:{m.handle}  valid until {m.valid_until.isoformat()}  {_flat(m.claim)}"
        for m in expired
        if m.valid_until is not None
    ]
    return out


def _curate_seen_lines(found: Sequence[Decisions]) -> list[str]:
    frequent = [m for d in found for m in d.seen]
    if not frequent:
        return []
    out = [f"seen {_FREQUENT} times or more: general enough for a global lesson? (mem promote <h>)"]
    out += [f"  m:{m.handle}  observed {m.observed}  {_flat(m.claim)}" for m in frequent]
    return out


def _curate_stale_lines(found: Sequence[Decisions]) -> list[str]:
    stale = [m for d in found for m in d.stale]
    if not stale:
        return []
    out = [f"not confirmed in {_STALE_DAYS} days (decide: mem confirm <h> or mem forget <h>)"]
    out += [
        f"  m:{m.handle}  {m.created.isoformat()}  {_flat(m.claim)}"
        for m in stale
        if m.created is not None
    ]
    return out


def _curate_awaiting_lines(live: Sequence[records.Memory]) -> list[str]:
    awaiting = [m for m in live if m.triage == "pending"]
    if not awaiting:
        return []
    out = [
        (
            "general lesson, out of quarantine, awaiting triage (decide: mem triage accept <h>, mem triage "
            "reject <h>, or reword it with mem memory edit <h> --global and then accept)"
        )
    ]
    for m in awaiting:
        n, p = len(records.sessions(m)), len(records.projects(m))
        out.append(
            f"  m:{m.handle}  {n} session{'' if n == 1 else 's'}, {p} project{'' if p == 1 else 's'}  "
            f"{_flat(m.claim)}"
        )
        if m.triage_reason:
            out.append(f"    held: {m.triage_reason}")
    return out


def _curate_worse_lines(
    args: argparse.Namespace,
    raw: dict[str, list[records.Memory]],
    scopes: _CurateScopes,
    today: datetime.date,
) -> list[str]:
    """The lessons whose balance got worse after loading; `raw` gets the scope not asked for, loaded quietly."""
    asked = {scope for scope, _, _ in scopes}
    for scope, folder in _memory_folders(
        args
    ):  # the scope not asked for still counts toward the cap; loaded quietly
        if scope not in raw:
            raw[scope] = records.load_memories(folder, scope)
    worse = [
        (m, loaded)
        for m, loaded in _got_worse(raw.get("project", []), raw.get("global", []), today)
        if m.scope in asked and m.superseded_by is None
    ]
    if not worse:
        return []
    out = [
        (
            "balance got worse after loading (decide: reword it or go back with mem memory edit <h> --short, "
            "drop it with mem forget <h>, or keep the wording with mem triage accept <h>)"
        )
    ]
    for m, loaded in worse:
        state = "rules off" if _rules_off() else "loaded" if loaded else "left out by the cap"
        note = records.reword_note(m)
        out.append(f"  m:{m.handle}  {state}{'; ' + note if note else ''}  {_flat(m.claim)}")
        found = records.tallies(m)[-2:]
        ends = [t.since for t in found[1:]] + [today]
        out += [f"    {_tally_line(t, end)}" for t, end in zip(found, ends, strict=False)]
    return out


def _curate_quarantine_lines(every: Sequence[records.Memory]) -> list[str]:
    held = sum(
        1 for m in every if m.status == "active" and records.quarantined(m)
    )  # a lapsed one is still stored
    if not held:
        return []
    return [
        (
            f"in quarantine: {held} general lesson{'' if held == 1 else 's'}, not shown to a reader until corroborated "
            "(mem memories --global --quarantine)"
        )
    ]


def _curate_unconfirmed_lines(live: Sequence[records.Memory], unconfirmed: set[str]) -> list[str]:
    waiting = [m for m in live if m.handle in unconfirmed and not records.quarantined(m)]
    if not waiting:
        return []
    out = [
        (
            "from a transcript, not confirmed yet (decide: mem forget <h>, or leave it; it is confirmed only "
            "when another session shows it)"
        )
    ]
    for m in waiting:
        n = len(records.sessions(m))
        out.append(
            f"  m:{m.handle}  {m.weight or 'medium'}, {n} session{'' if n == 1 else 's'}  {_flat(m.claim)}"
        )
    return out


def _curate_unread_lines(live: Sequence[records.Memory]) -> list[str]:
    unread = [m for m in live if m.short_by == "model" and m.short]
    return [f"short forms nobody read: {len(unread)} (mem rules --unread)"] if unread else []


def _curate_nofill_lines(found: Sequence[Decisions]) -> list[str]:
    nofill = [m for d in found for m in d.nofill]
    if not nofill:
        return []
    out = [
        (
            "established, but the automatic fill will not write its short form (it gave up, or never "
            f"tries a repository-tracked or strong unconfirmed project lesson); write one of at most "
            f"{records.SHORT_LIMIT} characters and pick a topic: mem memory edit m:<h> --short '<text>' "
            "--topic <t>, with --global for a global lesson; add --user-read only when the owner wrote or read the text)"
        )
    ]
    out += [f"  m:{m.handle}  {_flat(m.claim)}" for m in nofill]
    return out


def _curate_report(
    args: argparse.Namespace,
    scopes: _CurateScopes,
    attempts: dict,
    today: datetime.date,
) -> int:
    """Print the curation queue: every decision the owner or the pipeline has to take."""
    raw = {scope: loaded for scope, _, loaded in scopes}
    scopes = [(s, f, [m for m in loaded if m.superseded_by is None]) for s, f, loaded in scopes]
    every = [m for _, _, loaded in scopes for m in loaded if m.error is None]
    live = [m for m in every if records.is_live(m, today)]
    found = _curate_decisions(scopes, attempts, today)
    unconfirmed = _unconfirmed_handles(every)  # their own category below
    out = [
        *_curate_refuted_lines(found),
        *_curate_same_lines(found),
        *_curate_state_lines(found),
        *_curate_expired_lines(found),
        *_curate_seen_lines(found),
        *_curate_stale_lines(found),
        *_curate_awaiting_lines(live),
        *_curate_worse_lines(args, raw, scopes, today),
        *_curate_quarantine_lines(every),
        *_curate_unconfirmed_lines(live, unconfirmed),
        *_curate_unread_lines(live),
        *_curate_nofill_lines(found),
    ]
    if not args.is_global:
        out += _curate_project_syntheses(scopes, today)
    if out:
        print("\n".join(out))
    return 0


def cmd_curate(args: argparse.Namespace) -> int:
    if args.action == "apply":
        return _curate_apply(args)
    if args.new_since is not None:
        return _curate_new_since(args)
    if args.notes:
        return _curate_notes(args)
    today = datetime.date.today()
    folders = _memory_folders(args)
    if args.is_project or args.is_global:
        folders = [f for f in folders if (f[0] == "global") == args.is_global]
    scopes = _loaded(folders)
    attempts = _fill_attempts(os.environ)
    if args.done:
        return _curate_done(args, scopes, attempts, today)
    return _curate_report(args, scopes, attempts, today)


def _settle_actions() -> settle.Actions:
    return settle.Actions(_merge_pair, _supersede_pair, _distinct_pair)


def _settle_reason_ok(reason: str) -> bool:
    return not _refuse_secret([reason]) and _check_terms([reason], "lesson", False) == 0


def _settle_missing_folder(command: str) -> int:
    """The exit code of a settle subcommand when there is no global memories folder."""
    if command == "due":
        return 1
    if command in {"pending", "log"}:
        return 0
    print("mem: there is no global memories folder.", file=sys.stderr)
    return 2


def _settle_due(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    count = settle.due(folder, args.minutes, time.time(), today)
    if count is None:
        return 1
    print(count)
    return 0


def _settle_pending(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    with settle.locked(folder):
        state = settle.load_state(folder)
        found = settle.pending(
            records.load_memories(folder, "global"), state, today, tokenize=tokenize
        )
        settle.offer(folder, state, found, time.time())
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
    else:
        for p in found:
            flagged = f"  flagged: {', '.join(p['flagged_words'])}" if p["flagged_words"] else ""
            print(
                f"pair {p['pair']}  newer: m:{p['newer']}{flagged}\n  m:{p['a']}\t{p['claim_a']}\n  "
                f"m:{p['b']}\t{p['claim_b']}"
            )
    return 0


def _settle_apply(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    try:
        rows = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"mem: cannot read the verdicts: {exc}", file=sys.stderr)
        return 2
    try:
        with settle.locked(folder):
            lines = settle.apply_verdicts(
                folder,
                records.load_memories(folder, "global"),
                rows,
                today,
                time.time(),
                actions=_settle_actions(),
                reason_ok=_settle_reason_ok,
                tokenize=tokenize,
            )
    except settle.NoListing as exc:
        print("\n".join(exc.lines))
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


def _settle_log(args: argparse.Namespace, folder: Path, _today: datetime.date) -> int:
    out = settle.listing(folder, args.all)
    if out:
        print("\n".join(out))
    return 0


def _settle_ack(_args: argparse.Namespace, folder: Path, _today: datetime.date) -> int:
    print(f"acknowledged {settle.ack(folder)}")
    return 0


def _settle_undo(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    try:
        with settle.locked(folder):
            print("\n".join(settle.undo(folder, args.number, today)))
    except settle.NothingToUndo as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    return 0


_SETTLE_HANDLERS: dict[str, Callable[[argparse.Namespace, Path, datetime.date], int]] = {
    "due": _settle_due,
    "pending": _settle_pending,
    "apply": _settle_apply,
    "log": _settle_log,
    "ack": _settle_ack,
}  # any other subcommand is `undo`


def cmd_settle(args: argparse.Namespace) -> int:
    """`mem settle`: the engine side of settling new global memories (see settle.py)."""
    store = _optional_store(args)
    folder = records.memories_root(os.environ, store)
    command = args.settle_command
    if folder is None or not folder.is_dir():
        return _settle_missing_folder(command)
    if _read_only_store(store, folder.resolve()):
        print(_READ_ONLY_MEMORIES, file=sys.stderr)
        return 2
    today = datetime.date.today()
    try:
        return _SETTLE_HANDLERS.get(command, _settle_undo)(args, folder, today)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2


_TEMPLATES = Path(__file__).resolve().parent / "templates"


def cmd_init(args: argparse.Namespace) -> int:
    if args.folder is None:
        default = records.default_store(os.environ)
        if default is None:
            print(
                "mem: no folder given and neither XDG_DATA_HOME nor HOME is set.", file=sys.stderr
            )
            return 2
        args.folder = str(default)
    code = _init_store(Path(args.folder).expanduser())
    if code == 0:
        # the list is made again by the first global write
        with contextlib.suppress(OSError):
            records.ensure_terms_file(os.environ)
    return code


def _history_store(args: argparse.Namespace) -> Path | None:
    root = resolve_root(args.root, os.environ)
    if root is None or not root.is_dir():
        print(
            NO_STORE if root is None else f"mem: the store folder does not exist: {root}",
            file=sys.stderr,
        )
        return None
    return root


def _commit_points(
    store: Path,
    message: str | Callable[[int], str],
    *,
    quiet: bool = False,
    held: list[str] | None = None,
) -> tuple[str | None, bool]:
    """Commit the store; (commit id or None, whether git failed). The failure is reported and logged.

    `held` receives the paths this run held back, so a caller never reads an older run's list."""
    failed: list[str] = []

    def report(reason: str) -> None:
        failed.append(reason)
        if not quiet:
            print(f"mem: history: {reason}", file=sys.stderr)
        log_usage(store, {"cmd": "history", "error": reason})

    def warn(
        reason: str,
    ) -> None:  # not a git failure: it must not make `mem history commit` exit 1
        if not quiet:
            print(f"mem: history: {reason}", file=sys.stderr)
        log_usage(store, {"cmd": "history", "warning": reason})

    commit = store_git.commit_if_changed(
        store,
        message,
        report=report,
        warn=warn,
        validate=invalid_changed(store),
        on_held=lambda paths: held.extend(paths) if held is not None else None,
    )
    return commit, bool(failed)


def _history_init_folder(args: argparse.Namespace) -> Path | None:
    """The store folder `mem history init` turns into a repository; None after a message on stderr."""
    folder = Path(args.folder).expanduser() if args.folder else resolve_root(args.root, os.environ)
    if folder is None:
        print(NO_STORE, file=sys.stderr)
        return None
    if not folder.is_dir():
        print(f"mem: the store folder does not exist: {folder}", file=sys.stderr)
        return None
    if not records.store_is_writable(folder):
        print(
            f'mem: {folder} is read-only: it has no mem-store.yaml (create a store with "mem init").',
            file=sys.stderr,
        )
        return None
    if store_git.is_repo(folder):
        print(f"mem: {folder} is a git repository already", file=sys.stderr)
        return None
    return folder


def _history_init(args: argparse.Namespace) -> int:
    folder = _history_init_folder(args)
    if folder is None:
        return 2
    try:
        print(store_git.init(folder) or "nothing to commit")
    except store_git.GitError as exc:
        print(f"mem: history: {exc}", file=sys.stderr)
        return 1
    return 0


def _history_repo(args: argparse.Namespace, hook: bool) -> Path | None:
    """The store when it is a git repository; None otherwise, with a message unless `hook`."""
    store = _history_store(args) if not hook else resolve_root(args.root, os.environ)
    if store is None or not store.is_dir():
        return None
    if not store_git.is_repo(store):
        if not hook:
            print(f'mem: {store} is not a git repository (run "mem history init")', file=sys.stderr)
        return None
    return store


def _history_message(args: argparse.Namespace, hook: bool) -> str | Callable[[int], str]:
    """The commit message: `-m`, or a line stamped with the time of the call."""
    if args.message:
        return args.message
    now = datetime.datetime.now()
    label = "session end" if hook else "manual commit"
    return lambda n: f"{label} {now:%Y-%m-%d %H:%M}: {n} files"


def _history_commit(args: argparse.Namespace, store: Path, hook: bool, started: float) -> int:
    detached = hook and args.detached
    if detached:
        _log_hook({"hook": "session-end", "phase": "started"})
    if hook and auto_state.run_lock_held(data_dir(os.environ), store):
        if detached:
            _log_hook({
                "hook": "session-end",
                "phase": "done",
                "ms": int((time.monotonic() - started) * 1000),
                "committed": False,
                "failed": False,
            })
        return 0  # an automatic run holds the store: it commits its own work
    message = _history_message(args, hook)
    held: list[str] = []
    commit, failed = _commit_points(
        store, message, quiet=hook, held=held
    )  # the hook is silent; a failure is in the usage log
    if hook:
        _log_hook({
            "hook": "session-end",
            **({"phase": "done"} if detached else {}),
            "ms": int((time.monotonic() - started) * 1000),
            "committed": commit is not None,
            "failed": failed,
        })
        return 0
    print(commit or "nothing to commit")
    for path in [] if failed else held:
        print(f"held back: {path}", file=sys.stderr)
    return 1 if failed else 0


def _history_log(args: argparse.Namespace, store: Path) -> int:
    try:
        print("\n".join(store_git.log(store, args.n)))
    except store_git.GitError as exc:
        print(f"mem: history: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    started = time.monotonic()
    hook = args.history_command == "commit" and args.hook
    if args.history_command == "init":
        return _history_init(args)
    store = _history_repo(args, hook)
    if store is None:
        return 0 if hook else 2
    if args.history_command == "commit":
        return _history_commit(args, store, hook, started)
    return _history_log(args, store)


def _init_store_check(folder: Path) -> int | None:
    """The exit code when `folder` cannot become a store, or already is one; None when it can be created."""
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
        print(
            f"mem: {folder} already holds a store without mem-store.yaml; it stays read-only "
            "(add the file by hand only if you own it and mean to write to it).",
            file=sys.stderr,
        )
        return 2
    return None


def _init_store_create(folder: Path) -> None:
    """Make the folders, the templates and the two files of a new store; what exists stays."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in (
        "literature",
        "knowledge",
        "research",
        records.GLOBAL_DIR,
        syntheses.SYNTHESES_DIR,
    ):
        (folder / name).mkdir(exist_ok=True)
    if not (folder / "templates").exists():
        shutil.copytree(_TEMPLATES, folder / "templates")
    for name, text in (
        (records.STORE_MARKER, "format: 1\n"),
        ("topics.yaml", "notes: {description: General notes}\n"),
    ):
        if not (folder / name).exists():
            safe_io.replace_file(folder / name, text.encode("utf-8"))


def _init_store(folder: Path) -> int:
    code = _init_store_check(folder)
    if code is not None:
        return code
    try:
        _init_store_create(folder)
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(folder)
    return 0


def _term_class(term: records.Term) -> str:
    return "hard" if not term.soft else f"soft[{term.kind}]" if term.kind else "soft"


def _projects_list(_args: argparse.Namespace, data: Path) -> int:
    today = datetime.date.today()
    for name, entry in sorted(records.read_registry(data).items()):
        path = Path(entry["path"])
        if not path.is_dir():
            print(f"{name}\tmissing\t{path}")
            continue
        live = [
            m
            for m in records.load_memories(records.project_dir(path), "project")
            if records.is_live(m, today)
        ]
        print(f"{name}\t{len(live)} memories\t{path}")
    return 0


def _projects_add(args: argparse.Namespace, data: Path) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        print(f"mem: {path} is not a folder.", file=sys.stderr)
        return 2
    name = records.register_project(data, path, datetime.date.today(), args.name)
    print(f"{name}\t{path}")
    return 0


def _projects_remove(args: argparse.Namespace, data: Path) -> int:
    if not records.forget_project(data, args.name):
        print(f"mem: no project named {args.name} (see mem projects list)", file=sys.stderr)
        return 2
    return 0


_PROJECTS_HANDLERS: dict[str, Callable[[argparse.Namespace, Path], int]] = {
    "list": _projects_list,
    "add": _projects_add,
}  # any other subcommand is `remove`


def cmd_projects(args: argparse.Namespace) -> int:
    data = data_dir(os.environ)
    if data is None:
        print(
            "mem: no data folder is set (MEM_DATA, XDG_STATE_HOME or HOME), so there is no registry.",
            file=sys.stderr,
        )
        return 2
    try:
        return _PROJECTS_HANDLERS.get(args.projects_command, _projects_remove)(args, data)
    except (ValueError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2


def _terms_list(_args: argparse.Namespace, _path: Path, terms: Sequence[records.Term]) -> int:
    for t in terms:
        print(f"{_term_class(t)}\t{t.text}")
    return 0


def _terms_add(args: argparse.Namespace, path: Path, terms: Sequence[records.Term]) -> int:
    text = " ".join(args.term.split())
    if args.kind and not args.soft:
        build_parser().error("--kind needs --soft")
    if (
        not text
        or text.startswith("#")
        or cast("records.Term", records.parse_term(text)).soft  # not blank, not a comment
    ):
        print("mem: a term cannot be empty, start with # or start with soft:", file=sys.stderr)
        return 2
    line = (
        f"soft[{args.kind}]: {text}"
        if args.soft and args.kind
        else f"soft: {text}"
        if args.soft
        else text
    )
    new = cast("records.Term", records.parse_term(line))  # `line` is neither blank nor a comment
    if any((t.text, t.soft, t.kind) == (new.text, new.soft, new.kind) for t in terms):
        print("already listed")
        return 0
    records.ensure_terms_file(os.environ)
    existing = path.read_text(encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(("" if not existing or existing.endswith("\n") else "\n") + line + "\n")
    print(f"{_term_class(new)}\t{text}")
    return 0


def _terms_remove(args: argparse.Namespace, path: Path, _terms: Sequence[records.Term]) -> int:
    text = " ".join(args.term.split())
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    kept = [ln for ln in lines if (t := records.parse_term(ln)) is None or t.text != text]
    if len(kept) == len(lines):
        print(f"mem: no term {text!r} in the list.", file=sys.stderr)
        return 2
    path.write_text("".join(ln + "\n" for ln in kept), encoding="utf-8")
    print(f"removed {len(lines) - len(kept)}")
    return 0


_TERMS_HANDLERS: dict[str, Callable[[argparse.Namespace, Path, Sequence[records.Term]], int]] = {
    "list": _terms_list,
    "add": _terms_add,
}  # any other subcommand is `remove`


def cmd_terms(args: argparse.Namespace) -> int:
    path = records.forbidden_file(os.environ)
    if path is None:
        print(
            "mem: neither XDG_CONFIG_HOME nor HOME is set: the term list has no place.",
            file=sys.stderr,
        )
        return 2
    try:
        terms = records.read_terms(os.environ)
        return _TERMS_HANDLERS.get(args.terms_command, _terms_remove)(args, path, terms)
    except (records.ForbiddenListError, OSError) as exc:
        print(f"mem: the forbidden-terms list cannot be used ({exc}).", file=sys.stderr)
        return 2


SIMILAR_LIMIT = 3


def _read_body_text(source: str) -> str:
    """The text of the file, or of standard input for `-`, before any check of its content."""
    if source == "-":
        if sys.stdin.isatty():
            raise NewNoteError("--body-file - needs the body on standard input, not a terminal")
        return sys.stdin.read().removeprefix("\ufeff").replace("\r\n", "\n")
    return note_files._read_text(Path(source))


def _read_body(source: str) -> str:
    """The text of a `--body-file` (`-` is standard input); NewNoteError when it cannot be a body."""
    try:
        body = _read_body_text(source)
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        raise NewNoteError(f"cannot read the body: {exc}") from exc
    if not body.strip():
        raise NewNoteError("the body is empty")
    if body.split("\n", 1)[0].strip() == "---":
        raise NewNoteError(
            "the body starts with a frontmatter fence: pass the text after the frontmatter"
        )
    return body if body.endswith("\n") else body + "\n"


def _synthesis_text(source: str | None) -> str | None:
    try:
        return _read_body(source) if source else ""
    except NewNoteError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return None


def _long_note(handle: str, path: Path, section: str) -> None:
    sec = next((x for x in syntheses.load_one(path).sections if x.handle == section), None)
    if sec is not None and (n := syntheses.word_count(sec.text)) > syntheses.LONG_SECTION_WORDS:
        print(
            f"mem: s:{handle}#{section} has {n} words: consider splitting it into two parts "
            "(mem synthesis add).",
            file=sys.stderr,
        )


def _own_topics(known: dict, topics: Sequence[str]) -> list[str]:
    """The topics a note was filed under: those that are not the ancestor of another listed topic."""
    return [t for t in topics if not any(t in ancestors(known, o) for o in topics if o != t)]


def _covering(root: Path, topics: Sequence[str]) -> list[syntheses.Synthesis]:
    """Syntheses that list one of `topics` by its exact id (no ancestors, no descendants)."""
    try:
        known = load_topics(root)
    except FrontmatterError:
        known = {}
    own = set(_own_topics(known, topics))
    return [
        x
        for x in syntheses.load(root / syntheses.SYNTHESES_DIR)
        if x.error is None and own & set(x.topics)
    ]


def _section_ref(root: Path, ref: str) -> tuple[syntheses.Synthesis, syntheses.Section]:
    """`s:<h>#<section>` as the synthesis and section it names; ValueError when either is missing."""
    handle, section = syntheses.split_ref(ref)
    path = syntheses.path_of(root / syntheses.SYNTHESES_DIR, handle)
    if section is None or path is None or not path.is_file():
        raise ValueError(
            f"{ref} must name an existing synthesis section: s:<handle>#<section handle>"
        )
    syn = syntheses.load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    found = next((x for x in syn.sections if x.handle == section), None)
    if found is None:
        raise ValueError(f"no section {section} in s:{handle}")
    return syn, found


def _log_note(root: Path, path: Path, rel: str, action: str) -> None:
    """The note's current text, appended to the store's `.curation-log` before a curation action changes it."""
    entry = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": action,
        "handle": rel,
        "before": path.read_bytes().decode("utf-8"),
    }
    safe_io.append_text(root / records.CURATION_LOG, json.dumps(entry, ensure_ascii=False) + "\n")


def _note_target(rel: str) -> str:
    """How a synthesis part refers to the note stored at `rel` (a store-relative path)."""
    return "../" + rel


def _set_part_of(text: str, part_of: str, digest: str) -> str:
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if m is None:
        raise ValueError("the note has no frontmatter")
    kept = [ln for ln in m.group(1).split("\n") if not re.match(r"part_of(_hash)?:", ln)]
    head = (
        "---\n"
        + "\n".join([
            *kept,
            f"part_of: {json.dumps(part_of)}",
            f"part_of_hash: {json.dumps(digest)}",
        ])
        + "\n---\n"
    )
    return head + text[m.end() :]


def _attach(args: argparse.Namespace) -> int:
    root = args.root
    found = resolve_note(root, args.note)
    if isinstance(found, list):
        _ambiguous(args.note, found)
        return 2
    if found is None:
        print(f"mem: no note {args.note}", file=sys.stderr)
        return 2
    rel = found.relative_to(root.resolve()).as_posix()
    if not rel.startswith("knowledge/"):
        print(
            f"mem: {rel} is not a knowledge note: only knowledge notes are part of a synthesis",
            file=sys.stderr,
        )
        return 2
    try:
        syn, sec = _section_ref(root, args.target)
        text = note_files._read_text(found)
        _log_note(root, found, rel, "attach")
        safe_io.replace_file(
            found,
            _set_part_of(
                text,
                f"{syn.handle}#{sec.handle}",
                syntheses.note_fingerprint(sec.text, _note_target(rel)),
            ).encode("utf-8"),
        )
    except (ValueError, OSError, FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"{note_files._handle(rel)}\tpart of s:{syn.handle}#{sec.handle}")
    log_usage(root, {"cmd": "synthesis", "action": "attach"})
    return 0


def _part_of_notes(root: Path, ref: str) -> list[tuple[Path, str]]:
    """(path, text) of each note whose `part_of` is `ref` (`<synthesis>#<section>`), sorted by path."""
    found = []
    for _, path in note_files._note_files(root):
        try:
            text = path.read_bytes().decode("utf-8")
            meta = split_frontmatter(text)[0]
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if isinstance(meta, dict) and meta.get("part_of") == ref:
            found.append((path, text))
    return sorted(found)


def _log_group_ahead(root: Path, changes: Mapping[Path, tuple[bytes, bytes]], action: str) -> None:
    """The group entries `_log_group` writes, but before the files change: each holds the digest of the new bytes."""
    group = uuid.uuid4().hex
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_io.append_text(
        root / records.CURATION_LOG,
        "".join(
            json.dumps(
                {
                    "t": stamp,
                    "action": action,
                    "handle": path.relative_to(root).as_posix(),
                    "group": group,
                    "before": old.decode("utf-8"),
                    "after": _sha(new),
                },
                ensure_ascii=False,
            )
            + "\n"
            for path, (old, new) in changes.items()
        ),
    )


def _logged_changes_unchanged(changes: Mapping[Path, tuple[bytes, bytes]]) -> None:
    """ValueError when a file is not as it was read."""
    for path, (old, _) in changes.items():
        if path.read_bytes() != old:
            raise ValueError(
                f"{path.name} changed since it was read, so nothing was written: run the command again"
            )


def _write_logged_changes(
    changes: Mapping[Path, tuple[bytes, bytes]], log: Path, write_log: Callable[[], None]
) -> None:
    """Log the undo with `write_log`, then swap each file from its old bytes to its new ones; a file that is not as
    it was read, or any failure, puts every file and `log` back as they were."""
    log_before = log.read_bytes() if log.exists() else None
    write_log()
    swapped: list[Path] = []
    try:
        _logged_changes_unchanged(changes)
        for path, (_, new) in changes.items():
            _swap_file(path, new)
            swapped.append(path)
    except BaseException:
        for path in swapped:
            _swap_file(path, changes[path][0])
        if log_before is None:
            log.unlink(missing_ok=True)
        else:
            safe_io.replace_file(log, log_before)
        raise


def _synthesis_require_writable(changes: Mapping[Path, tuple[bytes, bytes]]) -> None:
    """ValueError naming the files of `changes` that cannot be written."""
    locked = [
        p.name for p in changes if not os.access(p, os.W_OK) or not os.access(p.parent, os.W_OK)
    ]
    if locked:
        raise ValueError(f"not writable: {', '.join(locked)}")


@dataclass(frozen=True)
class _StructurePlan:
    """What a `mem synthesis` structure command will write: the files with their old and new bytes, the output
    lines, the curation log and the function that logs the undo."""

    changes: dict[Path, tuple[bytes, bytes]]
    lines: list[str]
    log: Path
    write_log: Callable[[], None]


@dataclass(frozen=True)
class _StructureTarget:
    """The synthesis (and section, when given) a structure command acts on."""

    root: Path
    handle: str
    section: str | None
    path: Path
    today: datetime.date


@dataclass(frozen=True)
class _SectionEdit:
    """The new text of a synthesis after a section changed, the output lines, and how each member note changes."""

    old: str
    new: str
    lines: list[str]
    edit_note: Callable[[str, str], str]


def _structure_detach_plan(root: Path, note: str) -> _StructurePlan | None:
    """The plan to detach a note from its synthesis; None after an ambiguity message on stderr."""
    found = resolve_note(root, note)
    if isinstance(found, list):
        _ambiguous(note, found)
        return None
    if found is None or found not in {p.resolve() for _, p in note_files._note_files(root)}:
        raise ValueError(f"no note {note}")
    rel = found.relative_to(root).as_posix()
    original = found.read_bytes()
    text = original.decode("utf-8")
    meta = split_frontmatter(text)[0]
    part = meta.get("part_of") if isinstance(meta, dict) else None
    if not isinstance(part, str):
        raise ValueError(f"{note_files._handle(rel)} is not part of a synthesis")
    return _StructurePlan(
        {found: (original, _detached(text, rel).encode("utf-8"))},
        [f"{note_files._handle(rel)}\tdetached from s:{part}"],
        root / records.CURATION_LOG,
        lambda: _log_note(root, found, rel, "detach"),
    )


def _structure_topic_ids(args: argparse.Namespace, root: Path) -> list[str]:
    """The topic ids of `mem synthesis topics`, each one known; ValueError otherwise."""
    topics = list(dict.fromkeys(t.strip() for t in args.topic_ids.split(",") if t.strip()))
    known = load_topics(root)
    if not topics:
        raise ValueError("at least one topic is required")
    for t in topics:
        if t not in known:
            raise ValueError(f"unknown topic '{t}': use an id from topics.yaml or add it there")
    return topics


def _structure_topic_clash(root: Path, handle: str, topics: Sequence[str]) -> None:
    """ValueError when another synthesis already covers one of `topics`."""
    for other in syntheses.load(root / syntheses.SYNTHESES_DIR):
        if (
            other.error is None
            and other.handle != handle
            and (clash := [t for t in topics if t in other.topics])
        ):
            raise ValueError(f"s:{other.handle} already covers the topic {clash[0]}")


def _structure_topics_plan(args: argparse.Namespace, target: _StructureTarget) -> _StructurePlan:
    if target.section is not None:
        raise ValueError("topics takes s:<handle>")
    topics = _structure_topic_ids(args, target.root)
    _structure_topic_clash(target.root, target.handle, topics)
    old, new = syntheses.with_topics(target.path, topics, target.today)
    return _StructurePlan(
        {target.path: (old.encode("utf-8"), new.encode("utf-8"))},
        [f"s:{target.handle}\ttopics {', '.join(topics)}"],
        target.root / syntheses.SYNTHESES_DIR / records.CURATION_LOG,
        lambda: records.log_before(syntheses.Synthesis(target.path, target.handle), "topics"),
    )


def _structure_rename_edit(
    args: argparse.Namespace, target: _StructureTarget, members: Sequence[tuple[Path, str]]
) -> _SectionEdit:
    section = cast("str", target.section)
    old, new, new_section = syntheses.renamed_section(
        target.path, section, args.heading, target.today
    )
    return _SectionEdit(
        old,
        new,
        [
            f"s:{target.handle}#{new_section}\trenamed from {section}",
            *[
                f"{note_files._handle(p.relative_to(target.root).as_posix())}\tpart of s:{target.handle}#{new_section}"
                for p, _ in members
            ],
        ],
        lambda text, rel: _renamed_part_of(text, rel, f"{target.handle}#{new_section}"),
    )


def _structure_remove_edit(
    target: _StructureTarget, members: Sequence[tuple[Path, str]]
) -> _SectionEdit:
    section = cast("str", target.section)
    old, new = syntheses.without_section(target.path, section, target.today)
    ref = f"{target.handle}#{section}"
    return _SectionEdit(
        old,
        new,
        [
            f"s:{ref}\tremoved",
            *[
                f"{note_files._handle(p.relative_to(target.root).as_posix())}\tdetached from s:{ref}"
                for p, _ in members
            ],
        ],
        _detached,
    )


def _structure_section_plan(
    args: argparse.Namespace, target: _StructureTarget, action: str
) -> _StructurePlan:
    """The plan to rename or remove one section, with the member notes that follow it."""
    if target.section is None:
        raise ValueError(f"{action} takes s:<handle>#<section handle>")
    root = target.root
    members = _part_of_notes(root, f"{target.handle}#{target.section}")
    edit = (
        _structure_rename_edit(args, target, members)
        if action == "rename"
        else _structure_remove_edit(target, members)
    )
    changes = {target.path: (edit.old.encode("utf-8"), edit.new.encode("utf-8"))}
    for note, text in members:
        changes[note] = (
            text.encode("utf-8"),
            edit.edit_note(text, note.relative_to(root).as_posix()).encode("utf-8"),
        )
    return _StructurePlan(
        changes,
        edit.lines,
        root / records.CURATION_LOG,
        lambda: _log_group_ahead(root, changes, action),
    )


def _structure_plan(
    args: argparse.Namespace, root: Path, action: str, today: datetime.date
) -> _StructurePlan | None:
    """The plan of a structure command; None after a message on stderr."""
    if action == "detach":
        return _structure_detach_plan(root, args.note)
    handle, section = syntheses.split_ref(args.target)
    path = syntheses.path_of(root / syntheses.SYNTHESES_DIR, handle)
    if path is None or not path.is_file():
        raise ValueError(f"no synthesis named {args.target}")
    target = _StructureTarget(root, handle, section, path, today)
    if action == "topics":
        return _structure_topics_plan(args, target)
    return _structure_section_plan(args, target, action)


def _structure_heading_refused(args: argparse.Namespace) -> int:
    """0 when the new heading may be written, else the exit code after a message on stderr."""
    if _refuse_secret([args.heading]):
        return 4
    return _check_terms([args.heading], "synthesis", getattr(args, "owner_approved", False))


def _structure_run(
    args: argparse.Namespace, root: Path, action: str, today: datetime.date
) -> tuple[int, list[str]]:
    """(exit code, output lines) after the files of the command were written; the lines only when the code is 0."""
    if action == "rename":
        refused = _structure_heading_refused(args)
        if refused:
            return refused, []
    plan = _structure_plan(args, root, action, today)
    if plan is None:
        return 2, []
    _synthesis_require_writable(plan.changes)
    _write_logged_changes(plan.changes, plan.log, plan.write_log)
    return 0, plan.lines


def _structure(args: argparse.Namespace) -> int:
    """`mem synthesis rename | remove | detach | topics`: one line per changed record, errors on stderr with exit 2."""
    root = args.root.resolve()
    action = args.synthesis_command
    try:
        code, lines = _structure_run(args, root, action, datetime.date.today())
    except (NewNoteError, OSError, ValueError, FrontmatterError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if code != 0:
        return code
    print("\n".join(lines))
    log_usage(root, {"cmd": "synthesis", "action": action})
    return 0


@dataclass(frozen=True)
class _RefsPart:
    """One part of a synthesis with the reference changes proposed for it, each (line, unit, op, target)."""

    part: syntheses.Section
    items: list[tuple[str, int, str, str]]
    folder: Path
    root: Path


@dataclass(frozen=True)
class _RefsPartOutcome:
    """What the proposals for one part came to: refused lines, the summary line (None when the part was refused as
    a whole), the units added and removed, and (old, new) text of the part when it changed."""

    refused: list[str]
    count_line: str | None
    added: int
    removed: int
    change: tuple[str, str] | None


@dataclass(frozen=True)
class _RefsOutcome:
    """What the proposals came to over the whole synthesis: its new text, the member notes to rewrite, one summary
    line per part, the refused lines and the totals."""

    new_file: str
    notes: dict[Path, tuple[bytes, bytes]]
    counts: list[str]
    refused: list[str]
    added: int
    removed: int


@dataclass(frozen=True)
class _RefsRun:
    """The result of `mem synthesis refs` before it prints: exit code, output lines, whether a file changed."""

    code: int
    lines: list[str]
    changed: bool


def _refs_target(target: str, folder: Path) -> tuple[str, Path] | None:
    """(handle, path) of the synthesis named; None after a message on stderr when there is none."""
    handle, section = syntheses.split_ref(target)
    path = syntheses.path_of(folder, handle)
    if path is None or not path.is_file():
        print(f"mem: no synthesis named {target}", file=sys.stderr)
        return None
    if section is not None:
        raise ValueError("refs takes s:<handle>")
    return handle, path


def _refs_read_file(file: str) -> str | None:
    """The proposal file; None after a message on stderr when it cannot be read."""
    try:
        return Path(file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mem: cannot read the file: {exc}", file=sys.stderr)
        return None


def _refs_parse_line(line: str) -> tuple[str, tuple[str, int, str, str]] | None:
    """(section handle, (line, unit, op, target)) of a proposal line; None when it is not one."""
    cells = [c.strip() for c in line.split("|", 2)]
    action = cells[2].split(None, 1) if len(cells) == _SETTLE_LOG_CELLS else []
    if not (
        len(cells) == _SETTLE_LOG_CELLS
        and cells[1].isdigit()
        and len(action) == _SETTLE_ACTION_WORDS
        and action[0] in {"add", "remove"}
    ):
        return None
    return cells[0], (line.strip(), int(cells[1]), action[0], action[1].strip())


def _refs_proposals(
    raw: str,
) -> tuple[dict[str, list[tuple[str, int, str, str]]], list[str]]:
    """The proposals of the file by section handle, and a refused line for each one that is malformed."""
    refused: list[str] = []
    by_part: dict[str, list[tuple[str, int, str, str]]] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parsed = _refs_parse_line(line)
        if parsed is None:
            refused.append(
                f"refused: {line.strip()}: not `<section> | <unit> | add|remove <target>`"
            )
            continue
        by_part.setdefault(parsed[0], []).append(parsed[1])
    return by_part, refused


def _refs_refusal(
    sections: Sequence[syntheses.Section], name: str, part: syntheses.Section | None
) -> str | None:
    """Why no reference may change in the part `name`; None when it may."""
    if name == syntheses.SUMMARY:
        return "the Summary takes no references"
    if part is None:
        return f"no section {name!r}"
    if sum(1 for x in sections if x.handle == name) > 1:
        return f"the handle {name!r} is repeated: rename one heading first"
    return None


def _refs_attempt(unit: _RefsPart, picked: list[int]) -> tuple[str, list[str | None], str | None]:
    """The part's text with the picked proposals applied, the reason each was refused, and a problem with the
    result as a whole (None when it is sound)."""
    part = unit.part
    text, why_not = syntheses.change_references(
        part.text,
        unit.folder,
        [(unit.items[i][1], unit.items[i][2], unit.items[i][3]) for i in picked],
    )
    if text == part.text:
        return text, why_not, None
    if syntheses.without_references(text) != syntheses.without_references(part.text):
        return (
            text,
            why_not,
            "the command would change a word of the part (a bug: nothing of it was written)",
        )
    if found := syntheses.validate_section(text, unit.root):
        return text, why_not, "the part would fail its checks: " + "; ".join(found)
    return text, why_not, None


def _refs_resolve(unit: _RefsPart) -> tuple[str, list[str | None]]:
    """The part's new text and the reason each proposal was refused (None when applied)."""
    everyone = list(range(len(unit.items)))
    new, reasons, problem = _refs_attempt(unit, everyone)
    if problem:
        # One line that breaks the part is refused alone; the others are applied unit by unit.
        reasons, kept = list(reasons), []
        for i in everyone:
            if reasons[i] is not None:
                continue
            if (trial := _refs_attempt(unit, [*kept, i]))[2]:
                reasons[i] = trial[2]
            else:
                kept.append(i)
        new = _refs_attempt(unit, kept)[0]
    return new, reasons


def _refs_count(
    items: Sequence[tuple[str, int, str, str]], reasons: Sequence[str | None], op: str
) -> int:
    """How many proposals of kind `op` were applied."""
    return sum(1 for (_, _, o, _), r in zip(items, reasons, strict=False) if r is None and o == op)


def _refs_part_outcome(
    sections: Sequence[syntheses.Section],
    handle: str,
    root: Path,
    name: str,
    items: list[tuple[str, int, str, str]],
) -> _RefsPartOutcome:
    part = {s.handle: s for s in sections}.get(name)
    why = _refs_refusal(sections, name, part)
    if why or part is None:  # `part` is None only when `why` is set
        return _RefsPartOutcome([f"refused: {line}: {why}" for line, *_ in items], None, 0, 0, None)
    new, reasons = _refs_resolve(_RefsPart(part, items, root / syntheses.SYNTHESES_DIR, root))
    failed = [
        f"refused: {line}: {r}"
        for (line, *_), r in zip(items, reasons, strict=False)
        if r is not None
    ]
    added = _refs_count(items, reasons, "add")
    removed = _refs_count(items, reasons, "remove")
    return _RefsPartOutcome(
        failed,
        f"s:{handle}#{name}: added {added}, removed {removed}, refused {len(failed)}",
        added,
        removed,
        (part.text, new) if new != part.text else None,
    )


def _refs_note_edits(
    root: Path, handle: str, name: str, change: tuple[str, str]
) -> dict[Path, tuple[bytes, bytes]]:
    """The member notes of a changed part that were current and get the new `part_of_hash`."""
    old, new = change
    notes: dict[Path, tuple[bytes, bytes]] = {}
    for note, text in _part_of_notes(root, f"{handle}#{name}"):
        stored = (split_frontmatter(text)[0] or {}).get("part_of_hash")
        rel = note.relative_to(root).as_posix()
        new_fp = syntheses.note_fingerprint(new, _note_target(rel))
        if syntheses.is_current(stored, old, _note_target(rel)) and stored != new_fp:
            notes[note] = (
                text.encode("utf-8"),
                _set_field(_lf(text, rel), "part_of_hash", new_fp).encode("utf-8"),
            )
    return notes


def _refs_collect(
    syn: syntheses.Synthesis,
    handle: str,
    root: Path,
    by_part: dict[str, list[tuple[str, int, str, str]]],
    file_text: str,
) -> _RefsOutcome:
    """Apply the proposals part by part, in order, to the text of the synthesis."""
    outcomes = []
    new_file = file_text
    notes: dict[Path, tuple[bytes, bytes]] = {}
    for name, items in by_part.items():
        outcome = _refs_part_outcome(syn.sections, handle, root, name, items)
        outcomes.append(outcome)
        if outcome.change is not None:
            new_file = syntheses.apply_part_text(new_file, name, outcome.change[1])
            notes.update(_refs_note_edits(root, handle, name, outcome.change))
    return _RefsOutcome(
        new_file,
        notes,
        [o.count_line for o in outcomes if o.count_line is not None],
        [line for o in outcomes for line in o.refused],
        sum(o.added for o in outcomes),
        sum(o.removed for o in outcomes),
    )


def _refs_write(
    path: Path, original: bytes, outcome: _RefsOutcome, root: Path, today: datetime.date
) -> None:
    """Write the synthesis and the member notes as one logged group."""
    changes = {
        path: (original, syntheses.bumped(outcome.new_file, today).encode("utf-8")),
        **outcome.notes,
    }
    _synthesis_require_writable(changes)
    _write_logged_changes(
        changes, root / records.CURATION_LOG, lambda: _log_group_ahead(root, changes, "refs")
    )


def _refs_run(args: argparse.Namespace, root: Path, today: datetime.date) -> _RefsRun:
    """Read the proposals, apply them and write the files; the lines are printed by the caller."""
    target = _refs_target(args.target, root / syntheses.SYNTHESES_DIR)
    if target is None:
        return _RefsRun(1, [], False)
    handle, path = target
    raw = _refs_read_file(args.file)
    if raw is None:
        return _RefsRun(1, [], False)
    syn = syntheses.load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    original = path.read_bytes()
    file_text = original.decode("utf-8")
    _lf(file_text, path.name)
    by_part, malformed = _refs_proposals(raw)
    if not (by_part or malformed):
        print("mem: the file holds no proposal", file=sys.stderr)
        return _RefsRun(1, [], False)
    outcome = _refs_collect(syn, handle, root, by_part, file_text)
    changed = bool(outcome.added or outcome.removed)
    if changed:
        _refs_write(path, original, outcome, root, today)
    refused = [*malformed, *outcome.refused]
    summary = (
        f"s:{handle}: added {outcome.added}, removed {outcome.removed}, refused {len(refused)}"
    )
    return _RefsRun(0, [*outcome.counts, *refused, summary], changed)


def _refs(args: argparse.Namespace) -> int:
    """`mem synthesis refs s:<handle> --file F`: add or remove references by unit number and source target, never
    by text. Every changed part, and each member note that stays current, is written as one logged group."""
    root = args.root.resolve()
    try:
        run = _refs_run(args, root, datetime.date.today())
    except (NewNoteError, OSError, ValueError, FrontmatterError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if run.code != 0:
        return run.code
    print("\n".join(run.lines))
    if run.changed:
        log_usage(root, {"cmd": "synthesis", "action": "refs"})
    return 0


def _detached(text: str, rel: str) -> str:
    """The note's text without `part_of` and `part_of_hash`."""
    return _set_field(_set_field(_lf(text, rel), "part_of", None), "part_of_hash", None)


def _renamed_part_of(text: str, rel: str, part_of: str) -> str:
    """The note's text with `part_of` set to `part_of`; `part_of_hash` stays, so a stale note stays listed."""
    return _set_field(_lf(text, rel), "part_of", part_of)


def _lf(text: str, rel: str) -> str:
    if "\r" in text:
        raise ValueError(f"{rel} has CRLF line ends: convert it to LF first")
    return text


def _add_with_note(
    args: argparse.Namespace, root: Path, path: Path, handle: str, body: str, today: datetime.date
) -> str:
    """The section and the knowledge note that summarizes it, both or neither; returns the note's path."""
    syn = syntheses.load_one(path)
    note_body = _read_body(args.note_body_file)
    section_handle, _, cleaned = syntheses.prepare_add(path, args.section, body, today)
    kinds = syntheses.source_kinds(cleaned)
    origin = args.origin or (
        "literature"
        if kinds & {"literature", "url"}
        else "research"
        if "research" in kinds
        else "experience"
        if "experience" in kinds
        else "literature"
    )
    undo = syntheses.snapshot(path)
    syntheses.add_section(path, args.section, body, today)
    target = None
    created = False
    try:
        known = load_topics(root)
        domain = root_of(known, syn.topics[0]) if syn.topics and syn.topics[0] in known else None
        created = not (root / "knowledge" / str(domain)).exists()
        target = new_note(
            root,
            "knowledge",
            slug=args.note_slug,
            topics=list(syn.topics),
            today=today,
            body=note_body,
            claim=args.note_claim,
            confidence=args.confidence,
            level=args.level,
            origin=origin,
            part_of=f"{handle}#{section_handle}",
            part_of_hash=syntheses.fingerprint(cleaned),
        )
        rel = target.relative_to(root).as_posix()
        if (
            stamp := syntheses.note_fingerprint(cleaned, _note_target(rel))
        ) != syntheses.fingerprint(cleaned):
            safe_io.replace_file(
                target,
                _set_field(note_files._read_text(target), "part_of_hash", stamp).encode("utf-8"),
            )
        if found := [p for p in check(root) if p.path == rel]:
            raise NewNoteError(
                f"the note has {len(found)} problems, so nothing was written: "
                + "; ".join(str(p) for p in found)
            )
    except Exception:
        if target is not None:
            target.unlink(missing_ok=True)
            if created:
                shutil.rmtree(target.parent, ignore_errors=True)
            with contextlib.suppress(FrontmatterError, OSError):
                apply_index(root)
        undo()
        raise
    return rel


def cmd_synthesis(args: argparse.Namespace) -> int:
    root = args.root
    folder = root / syntheses.SYNTHESES_DIR
    today = datetime.date.today()
    action = args.synthesis_command
    approved = getattr(args, "owner_approved", False)
    if action == "list":
        listed = syntheses.load(folder)
        try:
            known = load_topics(root)
        except FrontmatterError:
            known = {}
        wanted = {args.topic, *descendants(known, args.topic)} if args.topic else None
        for syn in listed:
            if syn.error:
                print(f"mem: skipped {syn.path}: {syn.error}", file=sys.stderr)
            elif wanted is None or wanted & set(syn.topics):
                print(f"s:{syn.handle}\t{len(syn.parts)} parts, updated {syn.updated}\t{syn.title}")
        return 0
    if action == "attach":
        return _attach(args)
    if action in {"rename", "remove", "detach", "topics"}:
        return _structure(args)
    if action == "refs":
        return _refs(args)
    note_group = (
        [args.note_slug, args.note_claim, args.note_body_file, args.confidence, args.level]
        if action == "add"
        else []
    )
    one_call = any(note_group)
    if one_call and not all(note_group):
        build_parser().error(
            "--note-slug, --note-claim, --note-body-file, --confidence and --level go together"
        )
    try:
        if action == "new":
            topics = [t.strip() for t in args.topics.split(",") if t.strip()]
            known = load_topics(root)
            if not topics:
                raise ValueError("at least one topic is required")
            for t in topics:
                if t not in known:
                    raise ValueError(
                        f"unknown topic '{t}': use an id from topics.yaml or add it there"
                    )
            for other in syntheses.load(folder):
                if other.error is None and (clash := [t for t in topics if t in other.topics]):
                    raise ValueError(
                        f"s:{other.handle} already covers the topic {clash[0]}; add a part to it."
                    )
            summary = _synthesis_text(args.summary_file)
            if summary is None:
                return 1
            if _refuse_secret([args.title, summary]):
                return 4
            if refused := _check_terms([args.title, args.slug, summary], "synthesis", approved):
                return refused
            text = syntheses.render_new(
                (_TEMPLATES / "synthesis.md").read_text(encoding="utf-8"),
                title=args.title,
                topics=topics,
                summary=summary,
                today=today,
            )
            path = syntheses.create(folder, args.slug, text)
            print(f"s:{path.stem}\t{path.relative_to(root).as_posix()}")
        else:
            ref = args.target
            handle, section = syntheses.split_ref(ref)
            path = syntheses.path_of(folder, handle)
            if path is None or not path.is_file():
                raise ValueError(f"no synthesis named {ref}")
            body = _synthesis_text(args.body_file)
            if body is None:
                return 1
            note_texts = []
            if one_call:
                note_texts = [args.note_claim, _synthesis_text(args.note_body_file)]
                if note_texts[1] is None:
                    return 1
            if _refuse_secret([getattr(args, "section", None) or "", body, *note_texts]):
                return 4
            if refused := _check_terms(
                [getattr(args, "section", None) or "", body], "synthesis", approved
            ):
                return refused
            if note_texts and (
                refused := _check_terms([*note_texts, args.note_slug], "note", approved)
            ):
                return refused
            if action == "add":
                if section is not None:
                    raise ValueError("add takes s:<handle>, not a section")
                problems = syntheses.validate_section(body, root) if body.strip() else []
                if problems:
                    raise ValueError("; ".join(problems))
                note_rel = ""
                if one_call:
                    note_rel = _add_with_note(args, root, path, handle, body, today)
                    new_handle = syntheses.section_handle(args.section)
                else:
                    new_handle = syntheses.add_section(path, args.section, body, today)
                print(f"s:{handle}#{new_handle}\tadded")
                shown = new_handle
                if one_call:
                    print(note_rel)
            else:
                if section is None:
                    raise ValueError(f"{action} takes s:<handle>#<section handle>")
                shown = section
                if action == "append":
                    syntheses.append_section(path, section, body, today, store=root)
                    print(f"s:{handle}#{section}\tappended")
                else:
                    problems = (
                        syntheses.validate_section(body, root)
                        if section != syntheses.SUMMARY and body.strip()
                        else []
                    )
                    if problems:
                        raise ValueError("; ".join(problems))
                    syntheses.edit_section(
                        path,
                        section,
                        body,
                        today,
                        shrink=args.shrink,
                        drop_references=args.drop_references,
                    )
                    print(f"s:{handle}#{section}\tedited")
            _long_note(handle, path, shown)
    except (ValueError, OSError, FrontmatterError, yaml.YAMLError, NewNoteError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    log_usage(root, {"cmd": "synthesis", "action": action})
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    fields = {k: getattr(args, k) for k in _NEW_FIELDS[args.type]}
    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    part_text: str | None = None  # the text of the section `--part-of` names
    try:
        body = _read_body(args.body_file) if args.body_file else None
        if _refuse_secret([*(v for v in fields.values() if isinstance(v, str)), body or ""]):
            return 4
        texts = [
            str(fields[k])
            for k in ("title", "claim", "url", "question", "author", "slug")
            if k in fields
        ]
        if refused := _check_terms(
            [*texts, args.slug, body or ""], "note", getattr(args, "owner_approved", False)
        ):
            return refused
        if getattr(args, "part_of", None):
            syn, sec = _section_ref(args.root, args.part_of)
            fields["part_of"] = f"{syn.handle}#{sec.handle}"
            fields["part_of_hash"] = syntheses.fingerprint(sec.text)
            part_text = sec.text
        path = new_note(
            args.root,
            args.type,
            slug=args.slug,
            topics=topics,
            today=datetime.date.today(),
            body=body,
            **fields,
        )
        if part_text is not None:
            stamp = syntheses.note_fingerprint(
                part_text, _note_target(path.relative_to(args.root).as_posix())
            )
            if stamp != fields["part_of_hash"]:
                safe_io.replace_file(
                    path,
                    _set_field(note_files._read_text(path), "part_of_hash", stamp).encode("utf-8"),
                )
    except (NewNoteError, OSError, ValueError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    rel = path.relative_to(args.root).as_posix()
    print(rel)
    if args.type == "knowledge" and "part_of" not in fields:
        for syn in _covering(args.root, topics):
            print(
                f"mem: s:{syn.handle} ({syn.title}) covers this topic; a curation pass can attach this note to it "
                "(mem curate --notes).",
                file=sys.stderr,
            )
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
            print(
                "Similar notes exist: link them, or edit the existing note if it states the same claim.",
                file=sys.stderr,
            )
            for other, score, title in similar[:SIMILAR_LIMIT]:
                print(f"similar: {other}\t{score:.2f}\t{title}", file=sys.stderr)
    if args.type == "research":
        branch = f"research/{Path(rel).parent.name}"
        print(
            f"An investigation with its own material lives on a branch (ADR 0006): before committing, "
            f"git switch -c {branch} (uncommitted files move with you); add literature and knowledge "
            "notes on main, then merge main into it.",
            file=sys.stderr,
        )
    return 0


def cmd_unify(args: argparse.Namespace) -> int:
    try:
        body = _read_body(args.body_file)
        if _refuse_secret([body]):
            return 4
        if refused := _check_terms([body], "note", getattr(args, "owner_approved", False)):
            return refused
        keep, count, links = unify_notes(
            args.root,
            args.keep,
            args.others,
            UnifyRequest(body, args.drop, datetime.date.today()),
        )
    except (NewNoteError, OSError, ValueError, FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    print(
        f"{note_files._handle(keep.relative_to(args.root.resolve()).as_posix())}\tunified from {count} notes, {links} links rewritten"
    )
    log_usage(args.root, {"cmd": "unify", "notes": count, "links": links, "drop": args.drop})
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


# --- note edit -----------------------------------------------------------------


def _section_span(text: str, heading: str) -> tuple[list[str], int, int]:
    """The note's lines and the index of the `## heading` line and of the line that ends its text."""
    lines, heads = syntheses._scan(text)
    want = " ".join(heading.removeprefix("## ").split())
    hits = [k for k, (_, h) in enumerate(heads) if " ".join(h.split()) == want]
    if not hits:
        raise ValueError(f"no section '## {want}' in the note")
    if len(hits) > 1:
        raise ValueError(f"the heading '## {want}' is repeated in the note: edit it by hand")
    k = hits[0]
    return lines, heads[k][0], heads[k + 1][0] if k + 1 < len(heads) else len(lines)


def _edited_note_text(
    text: str,
    path: Path,
    meta: dict,
    known: dict,
    *,
    section: str | None,
    body: str | None,
    claim: str | None,
    topics: list[str] | None,
    shrink: bool,
    today: datetime.date,
) -> tuple[str, list[str]]:
    """The note's text with the section text, the claim and the topics replaced (every other byte stays), and what
    changed; ValueError when a change is refused."""
    what = []
    if section is not None:
        lines, head, end = _section_span(text, section)
        new = syntheses._clean(body or "")
        if not new:
            raise ValueError("the section text is empty")
        syntheses._check_body(new)
        if not shrink:
            syntheses._guard_shrink("\n".join(lines[head + 1 : end]).strip("\n"), new)
        lines[head + 1 : end] = ["", *new.split("\n"), ""]
        text = "\n".join(lines)
        what.append("section " + " ".join(section.removeprefix("## ").split()))
    if claim is not None:
        if not isinstance(meta.get("claim"), str):
            raise ValueError("the note has no claim: only a knowledge note does")
        if not claim:
            raise ValueError("the claim is empty")
        if not shrink:
            syntheses._guard_shrink(meta["claim"], claim, sentences=False)
        text = _set_field(text, "claim", claim)
        what.append("claim")
    if topics is not None:
        if not topics:
            raise ValueError("at least one topic is required")
        for t in topics:
            if t not in known:
                raise ValueError(f"unknown topic '{t}': use an id from topics.yaml")
            domain = path.parent.name
            if (
                path.parent.parent.name in {"literature", "knowledge"}
                and root_of(known, t) != domain
            ):
                raise ValueError(
                    f"topic '{t}' belongs to the domain {root_of(known, t)}, not to {domain}, "
                    "where the note lives"
                )
            if missing := [a for a in ancestors(known, t) if a not in topics]:
                raise ValueError(f"topic '{t}' needs its ancestor '{missing[0]}' in the list too")
        text = _set_field(text, "topics", topics)
        what.append("topics")
    if "updated" in meta:
        text = _set_field(text, "updated", today.isoformat())
    return text, what


def _swap_file(path: Path, data: bytes) -> None:
    safe_io.replace_file(path, data)


def _commit_note_edit(
    root: Path, found: Path, rel: str, original: bytes, text: str, new: str
) -> None:
    """Write `new` over the note through the undo log; any failure leaves the note, the listings and the log as
    they were (`mem restore` undoes it)."""
    group = uuid.uuid4().hex
    listings = _index_files(root)
    log = root / records.CURATION_LOG
    log_before = log.read_bytes() if log.exists() else None
    entry = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": "note-edit",
        "handle": rel,
        "group": group,
        "before": text,
        "after": _sha(new.encode("utf-8")),
    }
    safe_io.append_text(log, json.dumps(entry, ensure_ascii=False) + "\n")
    swapped = False
    try:
        if found.read_bytes() != original:
            raise ValueError(
                f"{rel} changed since it was read, so nothing was written: run the command again"
            )
        _swap_file(found, new.encode("utf-8"))
        swapped = True
        apply_index(root)
    except BaseException:  # any failure leaves the note, the listings and the log as they were
        if swapped:
            _swap_file(found, original)
            for path, data in listings.items():
                if path.read_bytes() != data:
                    _swap_file(path, data)
        if log_before is None:
            log.unlink(missing_ok=True)
        else:
            safe_io.replace_file(log, log_before)
        raise
    _log_group(root, _with_changed_listings({}, listings), "note-edit", group=group)


def cmd_note(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    if args.section is None and args.claim is None and args.topics is None:
        build_parser().error("note edit needs --section, --claim or --topics")
    if (args.section is None) != (args.body_file is None):
        build_parser().error("--section and --body-file go together")
    claim = " ".join(args.claim.split()) if args.claim is not None else None
    topics = (
        list(dict.fromkeys(t.strip() for t in args.topics.split(",") if t.strip()))
        if args.topics is not None
        else None
    )
    try:
        body = _read_body(args.body_file) if args.body_file else None
        texts = [args.section or "", body or "", claim or "", *(topics or [])]
        if _refuse_secret(texts):
            return 4
        if refused := _check_terms(texts, "note", getattr(args, "owner_approved", False)):
            return refused
        found = resolve_note(root, args.note)
        if isinstance(found, list):
            _ambiguous(args.note, found)
            return 2
        if found is None or found not in {p.resolve() for _, p in note_files._note_files(root)}:
            raise ValueError(f"no note {args.note}")
        rel = found.relative_to(root).as_posix()
        original = found.read_bytes()
        text = original.decode("utf-8")
        if "\r" in text:
            raise ValueError(f"{rel} has CRLF line ends: convert it to LF first")
        meta = split_frontmatter(text)[0]
        if not isinstance(meta, dict):
            raise NoteFormatError(f"{rel} has no frontmatter mapping")
        today = datetime.date.today()
        new, what = _edited_note_text(
            text,
            found,
            meta,
            load_topics(root),
            section=args.section,
            body=body,
            claim=claim,
            topics=topics,
            shrink=args.shrink,
            today=today,
        )
        _commit_note_edit(root, found, rel, original, text, new)
    except (NewNoteError, OSError, ValueError, FrontmatterError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"{note_files._handle(rel)}\tedited {', '.join(what)}")
    log_usage(root, {"cmd": "note", "action": "edit"})
    return 0


def _source_mark(fact: str, source: str, quote: str) -> tuple[str, str, str]:
    """The texts of a confirm or dispute, whitespace collapsed; ValueError when one is empty or the source is no URL."""
    fact, quote, source = (" ".join(t.split()) for t in (fact, quote, source))
    if not fact or not quote:
        raise ValueError("the fact and the quote must not be empty")
    parts = urllib.parse.urlsplit(source)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or check_rules._url(source) is not None
    ):
        raise ValueError("the source must be an http(s) URL")
    return fact, source, quote


def _evidence_line(text: str, line: str) -> str:
    """`text` with `line` appended to its `## Evidence` section (added at the end when the note has none)."""
    if not re.search(r"^## Evidence[ \t]*$", text, re.MULTILINE):
        return text.rstrip("\n") + f"\n\n## Evidence\n\n{line}\n"
    lines, head, end = _section_span(text, "Evidence")
    last = max((i for i in range(head + 1, end) if lines[i].strip()), default=head)
    lines.insert(last + 1, line)
    if last == head:
        lines.insert(last + 1, "")
    return "\n".join(lines)


def cmd_note_mark(args: argparse.Namespace) -> int:
    """`mem note confirm|dispute`: a source's verdict on a knowledge note, through the `note edit` write path."""
    root = args.root.resolve()
    action = args.note_command
    clear = action == "dispute" and args.clear
    given = [args.fact, args.source, args.quote]
    if clear and any(v is not None for v in given):
        build_parser().error("--clear goes alone")
    if not clear and any(v is None for v in given):
        build_parser().error(
            f"note {action} needs --fact, --source and --quote"
            + (" (or --clear)" if action == "dispute" else "")
        )
    fact = source = quote = ""  # set below unless `--clear`, which does not read them
    try:
        if not clear:
            fact, source, quote = _source_mark(*given)
            if _refuse_secret([fact, source, quote]):
                return 4
            if refused := _check_terms([fact, source, quote], "note", args.owner_approved):
                return refused
        found = resolve_note(root, args.note)
        if isinstance(found, list):
            _ambiguous(args.note, found)
            return 2
        if found is None or found not in {p.resolve() for _, p in note_files._note_files(root)}:
            raise ValueError(f"no note {args.note}")
        rel = found.relative_to(root).as_posix()
        if not rel.startswith("knowledge/"):
            raise ValueError(
                f"{rel} is not a knowledge note: only a knowledge note carries evidence and can be disputed"
            )
        original = found.read_bytes()
        text = original.decode("utf-8")
        if "\r" in text:
            raise ValueError(f"{rel} has CRLF line ends: convert it to LF first")
        meta = split_frontmatter(text)[0]
        if not isinstance(meta, dict):
            raise NoteFormatError(f"{rel} has no frontmatter mapping")
        today = datetime.date.today().isoformat()
        if action == "confirm":
            host = urllib.parse.urlsplit(source).netloc
            new = _evidence_line(
                text, f'- {today} confirmed: {fact} "{quote}" ([{host}]({source}))'
            )
        elif clear:
            if not meta.get("disputed"):
                raise ValueError(f"{rel} is not disputed")
            new = _set_field(text, "disputed", None)
        else:
            entry = {"date": today, "fact": fact, "source": source, "quote": quote}
            disputed = meta.get("disputed")
            new = _set_field(
                text, "disputed", [*(disputed if isinstance(disputed, list) else []), entry]
            )
        if "updated" in meta:
            new = _set_field(new, "updated", today)
        _commit_note_edit(root, found, rel, original, text, new)
    except (NewNoteError, OSError, ValueError, FrontmatterError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(
        f"{note_files._handle(rel)}\t{'cleared the dispute' if clear else action + ('ed' if action == 'confirm' else 'd')}"
    )
    log_usage(root, {"cmd": "note", "action": action})
    return 0


_IMPORT_FOLDERS = ("literature", "knowledge", "research")
# what an investigation's documents are made of: the text and the figures it embeds
_IMPORT_DOCUMENTS = {".md", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}


def _import_files(
    src: Path, with_sources: bool, research_data: bool = False, skipped: list[str] | None = None
) -> list[str]:
    """Source-relative paths to import, sorted. The source is only listed and read, never written.
    A symlink, or anything under one, is never listed: its source-relative path goes to `skipped`."""
    skipped = skipped if skipped is not None else []

    def refused(path: Path) -> bool:
        try:
            safe_io.refuse_symlink_chain(src, path)
        except safe_io.UnsafePath:
            skipped.append(path.relative_to(src).as_posix())
            return True
        return False

    found: list[str] = []
    roots = [*_IMPORT_FOLDERS, *([".sources"] if with_sources else [])]
    for top in roots:
        base = src / top
        if base.is_symlink():
            refused(base)
            continue
        for here, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d == d.lstrip(".") or top == ".sources")
            dirs[:] = [d for d in dirs if d != "__pycache__" and not refused(Path(here) / d)]
            for name in names:
                if refused(Path(here) / name):
                    continue
                rel = (Path(here) / name).relative_to(src)
                if top != ".sources" and name.startswith("."):
                    continue
                # An investigation's data and code stay where the experiments live; its documents are the memory.
                if (
                    top == "research"
                    and not research_data
                    and Path(name).suffix.lower() not in _IMPORT_DOCUMENTS
                ):
                    continue
                # the generated listings: folder/README.md and, for literature and knowledge, folder/topic/README.md
                if (
                    name == "README.md"
                    and top != ".sources"
                    and len(rel.parts) in ((2,) if top == "research" else (2, 3))
                ):
                    continue
                found.append(rel.as_posix())
    return sorted(found)


def _note_kind(rel: str) -> str | None:
    parts = rel.split("/")
    if (
        parts[0] in {"literature", "knowledge"}
        and len(parts) == _NOTE_PATH_PARTS
        and parts[2].endswith(".md")
        and parts[2] != "README.md"
    ):
        return parts[0]
    if parts[0] == "research" and len(parts) == _NOTE_PATH_PARTS and parts[2] == "README.md":
        return "research"
    return None


def _flag_import(src: Path, files: Sequence[str]) -> list[str]:
    """Imported text files whose text matches a secret pattern or a hard term (a file with a NUL byte is binary: skipped)."""
    try:
        terms = [t for t in records.read_terms(os.environ) if not t.soft]
    except records.ForbiddenListError:
        terms = []
    flagged = []
    for rel in files:
        try:
            raw = (src / rel).read_bytes()
        except OSError:
            continue
        if raw[:2] in {b"\xff\xfe", b"\xfe\xff"}:  # a BOM-marked UTF-16 file holds NULs but is text
            text = raw.decode("utf-16", errors="ignore")
        elif b"\x00" in raw:
            continue
        else:
            text = raw.decode("utf-8", errors="ignore")
        if records.secret_in([text]) is not None or (
            terms and any(not t.soft for t in records.term_hits([text], os.environ))
        ):
            flagged.append(rel)
    return flagged


def _union_topics(src: Path, dest: Path) -> tuple[list[str], list[str], str]:
    """(ids added, ids kept as they were, text to append to the destination's topics.yaml)."""
    path = src / "topics.yaml"
    if path.is_symlink() or not path.is_file():
        return [], [], ""
    try:
        theirs = load_yaml(note_files._read_text(path))
    except (yaml.YAMLError, FrontmatterError) as exc:
        raise FrontmatterError(f"the source's topics.yaml is unusable ({exc})") from exc
    if theirs is None:
        theirs = {}
    if not isinstance(theirs, dict):
        raise FrontmatterError("the source's topics.yaml must be a mapping of topic ids")
    mine = load_topics(dest)
    added = [t for t in theirs if t not in mine]
    kept = [t for t in theirs if t in mine and theirs[t] != mine[t]]
    # one `id: {flow entry}` line each: the flow dump of {id: entry} without its outer braces
    lines = "".join(
        yaml.safe_dump(
            {t: theirs[t]}, default_flow_style=True, width=10**6, allow_unicode=True
        ).strip()[1:-1]
        + "\n"
        for t in added
    )
    return [str(t) for t in added], [str(t) for t in kept], lines


def cmd_import(args: argparse.Namespace) -> int:
    dest = args.root.resolve()
    src = Path(args.source).expanduser()
    if not src.is_dir():
        print(f"mem: the source is not a folder: {src}", file=sys.stderr)
        return 2
    src = src.resolve()
    if records.inside(src, dest) or records.inside(dest, src):
        print(
            "mem: the source and the store must be separate folders, neither inside the other.",
            file=sys.stderr,
        )
        return 2
    try:
        added, kept, topic_text = _union_topics(src, dest)
    except FrontmatterError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    skipped: list[str] = []
    if (src / "topics.yaml").is_symlink():
        skipped.append("topics.yaml")
    files = _import_files(src, args.with_sources, args.research_data, skipped)
    kinds = collections.Counter(k for k in map(_note_kind, files) if k)
    todo: list[str] = []
    same, conflicts = 0, []
    for rel in files:
        target = dest / rel
        try:
            safe_io.refuse_symlink_chain(dest, target)
        except safe_io.UnsafePath:
            skipped.append(rel)
            continue
        data = (src / rel).read_bytes()
        if target.is_file():
            if target.read_bytes() == data:
                same += 1
                continue
            if not args.overwrite:
                conflicts.append(rel)
                continue
        todo.append(rel)
    flagged = _flag_import(src, files)

    def apply(root: Path, log: bool) -> None:
        originals: dict[Path, bytes] = {}
        for rel in todo:
            if rel.startswith(".sources/") and root is not dest:
                continue
            target = root / rel
            if log and target.is_file():
                try:
                    target.read_bytes().decode("utf-8")
                    originals[target] = target.read_bytes()
                except UnicodeDecodeError:
                    pass  # not text: the log keeps text only
            target.parent.mkdir(parents=True, exist_ok=True)
            with (src / rel).open("rb") as f:
                safe_io.replace_file(target, f.read())
        if topic_text:
            current = (root / "topics.yaml").read_text(encoding="utf-8")
            safe_io.replace_file(
                root / "topics.yaml",
                (
                    current + ("" if current.endswith("\n") or not current else "\n") + topic_text
                ).encode("utf-8"),
            )
        if originals:
            _log_group(root, originals, "import")
        apply_index(root)

    try:
        if args.dry_run:
            with tempfile.TemporaryDirectory() as tmp:
                scratch = Path(tmp) / "store"
                shutil.copytree(dest, scratch, ignore=shutil.ignore_patterns(".*"))
                apply(scratch, False)
                problems = check(scratch)
        else:
            apply(dest, True)
            problems = check(dest)
    except (FrontmatterError, OSError) as exc:
        print(f"mem: import failed: {exc}", file=sys.stderr)
        return 2
    print(f"source: {src}")
    print(f"destination: {dest}")
    print(
        f"notes: {kinds['literature']} literature, {kinds['knowledge']} knowledge, {kinds['research']} research"
    )
    print(f"files: {len(todo)} copied, {same} identical, {len(conflicts)} conflicts")
    print(f"topics: {len(added)} added, {len(kept)} kept as they were")
    print(f"check: {len(problems)} problems")
    print(f"flagged: {len(flagged)} files")
    for header, items in (
        ("skipped symlinks:", sorted(skipped)),
        ("conflicts:", conflicts),
        ("topics kept:", kept),
        ("check problems (first 20):", [str(p) for p in problems[:20]]),
        ("flagged:", flagged),
    ):
        if items:
            print(header)
            for item in items:
                print(f"  {item}")
    log_usage(dest, {"cmd": "import", "copied": len(todo), "conflicts": len(conflicts)})
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
    synths = [s for s in syntheses.load(root / syntheses.SYNTHESES_DIR) if s.error is None]
    if synths:
        lines.insert(
            len(INDEX_FOLDERS) + 1,
            f"syntheses: {len(synths)} ({sum(len(s.parts) for s in synths)} parts)",
        )
    today = datetime.date.today()
    counts = [records.load_memories(folder, scope) for scope, folder in _memory_folders(args)]
    if any(counts):
        counts = [[m for m in group if not records.quarantined(m)] for group in counts]
        live = sum(records.is_live(m, today) for group in counts for m in group)
        lines.insert(
            1, f"memories: {len(counts[0])} project, {len(counts[1])} global ({live} live)"
        )
    script = Path(__file__).resolve().read_text(encoding="utf-8")
    lines.append(f"orphans: {len(orphan_notes(root))}")
    lines += [
        f"topics: {topic_count}",
        f"characters: {chars}",
        f"tokens: {chars // 4}",
        f"mem.py lines: {len(script.splitlines())}",
    ]
    log_path = _usage_log(os.environ)
    try:
        entries = 0 if log_path is None else log_path.read_bytes().count(b"\n")
    except OSError:
        entries = 0
    lines.append(f"usage log entries: {entries}")
    print("\n".join(lines))
    return 0


def _deeper_hit(args: argparse.Namespace, query: str, printed: int) -> bool:
    """True when a --deep search would print more note lines than the default one did (`printed`)."""
    try:
        full = build_corpus(
            args.root,
            topic=args.topic,
            kind=args.kind,
            status=args.status,
            confidence=args.confidence,
            level=args.level,
            superseded=args.superseded,
        )
        return (
            len(rank(full, query, limit=len(full.notes))[args.offset : args.offset + args.limit])
            > printed
        )
    except (FrontmatterError, OSError):
        return False


def cmd_search(args: argparse.Namespace) -> int:
    queries = [args.query, *args.also]
    if not all(tokenize(q) for q in queries):
        build_parser().error("query has no searchable words: use letters or digits")
    if args.links and args.offset:
        build_parser().error("--offset cannot be used with --links")
    others = (
        _other_projects(args.project, args.all_projects)
        if args.project or args.all_projects
        else []
    )
    if others is None:
        return 2
    with_notes = args.scope != "memories"
    filters = {
        k: getattr(args, k)
        for k in ("type", "topic", "kind", "status", "confidence", "level")
        if getattr(args, k) is not None
    }
    corpus = None
    default_type = None if args.deep or args.type else "knowledge"
    if with_notes:
        try:
            corpus = build_corpus(
                args.root,
                type=args.type or default_type,
                topic=args.topic,
                kind=args.kind,
                status=args.status,
                confidence=args.confidence,
                level=args.level,
                superseded=args.superseded,
            )
            ranks = [rank(corpus, q, limit=len(corpus.notes)) for q in queries]
            linkeds = [
                linked_notes(args.root, corpus, r, args.limit) if args.links else [] for r in ranks
            ]
        except (FrontmatterError, OSError) as exc:
            print(f"mem: cannot search: {exc}", file=sys.stderr)
            return 1
    else:
        ranks, linkeds = [[] for _ in queries], [[] for _ in queries]
    names = short_handles(args.root) if args.handles and with_notes else {}
    # memories stay out of any narrowed, paged or path-only note listing, unless they are all that was asked for
    memories: list[tuple[str, list[records.Memory]]] = []
    other_memories: list[tuple[str, list[records.Memory]]] = []
    today = datetime.date.today()
    if (
        args.scope != "notes"
        and not args.offset
        and not filters
        and (args.detail != "paths" or not with_notes)
    ):
        for scope, folder in [*_memory_folders(args), *((f"project: {n}", f) for n, f in others)]:
            loaded = records.load_memories(folder, scope.split(":")[0])
            for m in loaded:
                if m.error is not None:
                    print(f"mem: skipped {m.path}: {m.error}", file=sys.stderr)
            loaded = [m for m in loaded if not records.quarantined(m)]
            (other_memories if ":" in scope else memories).append((scope, loaded))
    # like memories, syntheses stay out of any narrowed, paged or path-only listing; they follow the notes
    all_syntheses = (
        syntheses.load(args.root / syntheses.SYNTHESES_DIR)
        if args.deep
        and args.scope == "all"
        and args.root is not None
        and not args.offset
        and not filters
        and args.detail != "paths"
        else []
    )
    more = False
    for query, ranked, linked in zip(queries, ranks, linkeds, strict=False):
        result = ranked[args.offset : args.offset + args.limit]
        if args.also:
            print(f"== {query} ==")
        printed: list[str] = []
        from_others = False
        for scope, loaded in [*memories, *other_memories]:
            hits = records.match_memories(
                loaded,
                tokenize(query),
                today,
                tokenize=tokenize,
                limit=3,
                include_dead=args.all_memories,
            )
            if not hits:
                continue
            if args.detail == "paths":
                print("\n".join(f"m:{m.handle}" for m in hits))
            else:
                print(f"-- memories ({scope}) --")
                print("\n".join(_memory_line(m, today) for m in hits))
            if ":" in scope:
                from_others = True
            else:
                printed += [f"m:{m.handle}" for m in hits]
        if with_notes and (printed or from_others) and result:
            print("-- notes --")
        if not result and not printed and not from_others and not args.offset:
            print("no matches", file=sys.stderr)
        terms = tokenize(query)
        weights = term_idf(corpus, terms) if corpus is not None else {}
        for note, score in result:
            print(
                "\n".join(
                    format_hit(
                        note,
                        args.detail,
                        score=score,
                        terms=terms,
                        weights=weights,
                        name=names.get(note.rel),
                    )
                )
            )
        if linked and args.detail != "paths":
            print("-- linked to the results above --")
        for note, score in linked:
            print(
                "\n".join(
                    format_hit(
                        note,
                        args.detail,
                        score=score,
                        terms=terms,
                        weights=weights,
                        name=names.get(note.rel),
                    )
                )
            )
        sections = syntheses.match_sections(all_syntheses, tokenize(query), tokenize=tokenize)
        if sections:
            print("-- syntheses (extended versions) --")
            for syn, sec in sections:
                print(f"s:{syn.handle}#{sec.handle}\t{syn.title}: {sec.heading}")
        if default_type and with_notes and len(result) < _SPARSE_HITS and not more:
            more = _deeper_hit(args, query, len(result))
        if (
            not args.also and with_notes
        ):  # a footer names --offset, which applies to every query at once
            _page_footer(args.offset, len(result), len(ranked))
        extra = {"links": True, "linked": [note.rel for note, _ in linked]} if args.links else {}
        if printed:
            extra["memories"] = printed
        if args.project or args.all_projects:
            extra["projects"] = len(other_memories)
        if sections:
            extra["syntheses"] = [f"s:{syn.handle}#{sec.handle}" for syn, sec in sections]
        if args.deep:
            extra["deep"] = True
        log_usage(
            args.root,
            {
                "cmd": "search",
                "query": query,
                "limit": args.limit,
                "detail": args.detail,
                "filters": filters,
                "results": [note.rel for note, _ in result],
                **extra,
            },
        )
    if more:
        print("mem: more in sources and syntheses: repeat with --deep.", file=sys.stderr)
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
        print(
            f"mem: no source text for {args.path}: looked for a .txt in "
            f"{SOURCES_DIR}/{Path(rel).stem}/ (needs a literature note path); `mem fetch-sources {args.path}` "
            "downloads the source when it has a url, and writes a .txt only for a plain-text response "
            "or a PDF with pdftotext installed",
            file=sys.stderr,
        )
        return 1
    total, found = passages(
        source.read_text(encoding="utf-8", errors="replace"),
        args.query,
        count=args.count,
        words=args.words,
    )
    if not found:
        print(
            f"no matching passage in {source.relative_to(args.root).as_posix()} ({total} words)",
            file=sys.stderr,
        )
    else:
        print(f"source: {source.relative_to(args.root).as_posix()} ({total} words)")
        print("\n\n".join(f"== words {a}-{b} of {total} ==\n{t}" for a, b, t in found))
    log_usage(
        args.root,
        {
            "cmd": "passages",
            "path": rel,
            "query": args.query,
            "count": args.count,
            "words": args.words,
            "hits": len(found),
        },
    )
    return 0


def cmd_related(args: argparse.Namespace) -> int:
    path = resolve_note(args.root, args.path)
    if isinstance(path, list):
        _ambiguous(args.path, path)
        return 1
    rel = path.relative_to(args.root.resolve()).as_posix() if path else None
    try:
        corpus = build_corpus(args.root, superseded=args.superseded)
        if rel is None:
            raise ValueError(f"not a note: {rel}")  # what `related` raises for it
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
    print(
        " · ".join(f"{relation}: {len(notes)}" for relation, notes in groups.items()),
        file=sys.stderr,
    )
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
        print(
            f"search-eval: below the revisit trigger (recall@10 {RECALL_TRIGGER:.2f}, MRR@10 {MRR_TRIGGER:.3f}): "
            "see C-6 in docs/requirements.md",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    today = args.today or datetime.date.today()
    for line in (
        due_requirements(args.root, today)
        + due_retests(args.root, today)
        + due_rereads(args.root, today)
    ):
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
    if (date := check_rules._iso_date(value)) is None:
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


_OWNER_APPROVED = "the owner agreed to a write that mentions a soft term: never add it on your own"


_USER_READ = (
    "with --short: the owner read this text, so it skips the code check and carries no mark; "
    "without it the short form is checked against the claim and marked as written by a model"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mem", description="Memory engine: search and read a store of notes."
    )
    parser.add_argument(
        "--root", default=None, help="store folder (default: $MEM_STORE, then the config file)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="validate the hub rules")
    check_parser.add_argument(
        "paths", nargs="*", metavar="PATH", help="print only problems in these notes or folders"
    )
    check_parser.set_defaults(func=cmd_check)
    index_parser = sub.add_parser("index", help="regenerate the index blocks in the folder READMEs")
    index_parser.set_defaults(func=cmd_index)
    find_parser = sub.add_parser("find", help="list notes matching all filters")
    search_parser = sub.add_parser("search", help="rank notes by BM25 relevance to a query")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=_limit, default=10)
    search_parser.add_argument(
        "--offset", type=_offset, default=0, help="skip the first N results (default: 0)"
    )
    search_parser.add_argument(
        "--also",
        action="append",
        default=[],
        metavar="QUERY",
        help="another query over the same corpus (repeatable); each list is headed `== <query> ==`",
    )
    search_parser.add_argument(
        "--links",
        action="store_true",
        help="also list up to 10 notes linked to or from the first 10 printed results",
    )
    search_parser.add_argument(
        "--scope",
        choices=("all", "notes", "memories"),
        default="all",
        help="what to search: notes and memories (default), only notes, only memories",
    )
    search_parser.add_argument(
        "--deep",
        action="store_true",
        help="also rank source notes and investigations, and list syntheses "
        "(default: knowledge notes and memories)",
    )
    search_parser.add_argument(
        "--all-memories",
        action="store_true",
        help="also match refuted, superseded and expired memories",
    )
    search_parser.add_argument(
        "--project",
        action="append",
        default=[],
        metavar="NAME",
        help="also search this registered project's memories (repeatable; see mem projects list)",
    )
    search_parser.add_argument(
        "--all-projects",
        action="store_true",
        help="also search the memories of every registered project but the current one",
    )
    search_parser.set_defaults(func=cmd_search)
    for filtered in (find_parser, search_parser):
        filtered.add_argument("--type", choices=INDEX_FOLDERS)
        filtered.add_argument("--topic")
        filtered.add_argument("--kind", choices=_KINDS)
        filtered.add_argument("--status", choices=("idea", "active", "paused", "done", "abandoned"))
        filtered.add_argument("--confidence", choices=_CONFIDENCE)
        filtered.add_argument("--level", choices=LEVELS)
        filtered.add_argument(
            "--superseded", action="store_true", help="also list notes that a unified note replaced"
        )
        filtered.add_argument(
            "--handles",
            action="store_true",
            help="print a short handle in place of each path (accepted wherever a note is named)",
        )
        filtered.add_argument(
            "--detail",
            choices=DETAILS,
            default="titles",
            help="per result: path only, title, key facts, a matching line, or the lead section",
        )
    find_parser.add_argument(
        "--limit", type=_limit, default=50, help="print at most N notes (default: 50)"
    )
    find_parser.add_argument(
        "--offset", type=_offset, default=0, help="skip the first N notes (default: 0)"
    )
    find_parser.set_defaults(func=cmd_find)
    passages_parser = sub.add_parser(
        "passages", help="print the passages of a note's local source that best match"
    )
    passages_parser.add_argument("path", metavar="PATH")
    passages_parser.add_argument("query")
    passages_parser.add_argument(
        "--count", type=_limit, default=5, help="passages to print (default: 5)"
    )
    passages_parser.add_argument(
        "--words", type=_limit, default=500, help="words per passage (default: 500)"
    )
    passages_parser.set_defaults(func=cmd_passages)
    related_parser = sub.add_parser(
        "related", help="list a note's links, backlinks and most similar notes"
    )
    related_parser.add_argument("path", metavar="PATH")
    related_parser.add_argument(
        "--limit", type=_limit, default=5, help="print at most N similar notes (default: 5)"
    )
    related_parser.add_argument(
        "--detail",
        choices=DETAILS,
        default="titles",
        help="per result: path only, title, key facts, a matching line, or the lead section",
    )
    related_parser.add_argument(
        "--superseded", action="store_true", help="also list notes that a unified note replaced"
    )
    related_parser.add_argument(
        "--unlinked-mentions",
        action="store_true",
        help="print only the notes that name this one in their text without linking to it",
    )
    related_parser.set_defaults(func=cmd_related)
    show_parser = sub.add_parser("show", aliases=["read"], help="print chosen sections of notes")
    show_parser.add_argument("paths", nargs="+", metavar="PATH")
    show_parser.add_argument(
        "--section", action="append", help="a `## ` section to print (repeatable)"
    )
    show_parser.add_argument(
        "--outline", action="store_true", help="list headings with line numbers"
    )
    show_parser.add_argument(
        "--ranges",
        action="store_true",
        help="with --outline: print start-end lines and word count per heading",
    )
    show_parser.add_argument(
        "--all", action="store_true", help="a synthesis: print the whole file, not its outline"
    )
    show_parser.add_argument(
        "--project", metavar="NAME", help="read a memory of this registered project"
    )
    show_parser.add_argument(
        "--stored",
        action="store_true",
        help="a synthesis: print each reference as stored, not as `[n]`, the place of its note on the `Sources:` line",
    )
    show_parser.set_defaults(func=cmd_show)
    topics_parser = sub.add_parser("topics", help="print the topic tree with note counts")
    topics_parser.add_argument(
        "topic", nargs="?", metavar="ID", help="print only this topic's subtree"
    )
    topics_parser.set_defaults(func=cmd_topics)
    stats_parser = sub.add_parser("stats", help="print note, topic and size counts")
    stats_parser.add_argument(
        "--orphans", action="store_true", help="list notes no other file links to"
    )
    stats_parser.add_argument(
        "paths", nargs="*", metavar="PATH", help="with --orphans: only these notes or folders"
    )
    stats_parser.set_defaults(func=cmd_stats)
    review_parser = sub.add_parser(
        "review",
        help="list concrete requirements due for review and notes due for re-testing or re-reading",
    )
    review_parser.add_argument(
        "--today", type=_today, default=None, help="YYYY-MM-DD (default: today)"
    )
    review_parser.set_defaults(func=cmd_review)
    fetch_parser = sub.add_parser(
        "fetch-sources", help="download literature note urls into .sources/"
    )
    fetch_parser.add_argument("paths", nargs="*", metavar="PATH")
    fetch_parser.add_argument("--force", action="store_true", help="refetch notes already cached")
    fetch_parser.add_argument(
        "--text-only",
        action="store_true",
        help="no download: write source.txt in cached folders that hold no .txt",
    )
    fetch_parser.set_defaults(func=cmd_fetch_sources)
    eval_parser = sub.add_parser("search-eval", help="measure search recall on docs/search-eval.md")
    eval_parser.add_argument(
        "--min",
        type=float,
        help="exit 1 when recall@10 is below this (replaces the default revisit triggers)",
    )
    eval_parser.set_defaults(func=cmd_search_eval)
    rename_parser = sub.add_parser(
        "rename", help="rename a note in its folder and rewrite the links to it"
    )
    rename_parser.add_argument("note", metavar="NOTE")
    rename_parser.add_argument("new_stem", metavar="NEW-STEM", help="the new file name without .md")
    rename_parser.set_defaults(func=cmd_rename)
    note_parser = sub.add_parser(
        "note", help="change a note through mem, never by editing its file"
    )
    note_sub = note_parser.add_subparsers(dest="note_command", required=True)
    note_edit = note_sub.add_parser(
        "edit", help="replace the text of one section, the claim or the topics of a note"
    )
    note_edit.add_argument("note", metavar="NOTE", help="a path or a handle, as in mem show")
    note_edit.add_argument(
        "--section", metavar="HEADING", help="the `## ` heading whose text is replaced"
    )
    note_edit.add_argument(
        "--body-file", metavar="PATH", help="the new section text; - reads standard input"
    )
    note_edit.add_argument(
        "--claim", metavar="TEXT", help="the new frontmatter claim (one sentence)"
    )
    note_edit.add_argument(
        "--topics", metavar="A,B", help="the new topic ids: in topics.yaml, in the note's domain"
    )
    note_edit.add_argument(
        "--shrink",
        action="store_true",
        help="accept a text that drops over 20%% of the words, a sentence or a link",
    )
    note_edit.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    note_parser.set_defaults(func=cmd_note)
    for verb, what in (
        ("confirm", "append a source-confirmed line to the note's Evidence section"),
        ("dispute", "mark the note as contradicted by a source (the claim stays as it is)"),
    ):
        marked = note_sub.add_parser(verb, help=what)
        marked.add_argument(
            "note", metavar="NOTE", help="a path or a handle of a knowledge note, as in mem show"
        )
        marked.add_argument("--fact", metavar="TEXT", help="what the source says about the claim")
        marked.add_argument("--source", metavar="URL", help="the http(s) URL of the page")
        marked.add_argument("--quote", metavar="TEXT", help="the words of the page that show it")
        if verb == "dispute":
            marked.add_argument(
                "--clear", action="store_true", help="remove the mark: the owner settled it"
            )
        marked.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
        marked.set_defaults(func=cmd_note_mark)
    import_parser = sub.add_parser(
        "import",
        help="copy the notes of another folder of notes into the store; the source is never changed",
    )
    import_parser.add_argument(
        "source",
        metavar="SOURCE",
        help="the folder to read (literature/, knowledge/, research/, topics.yaml)",
    )
    import_parser.add_argument(
        "--dry-run", action="store_true", help="change nothing; print the report a real run would"
    )
    import_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace files that differ (the old text goes to the curation log)",
    )
    import_parser.add_argument(
        "--with-sources", action="store_true", help="also copy the source's .sources/ folder"
    )
    import_parser.add_argument(
        "--research-data",
        action="store_true",
        help="also copy the data and code under research/ (by default only its Markdown files)",
    )
    import_parser.set_defaults(func=cmd_import)
    unify_parser = sub.add_parser(
        "unify",
        help="replace several notes of one type with one, keeping the others as "
        "superseded files and pointing their links at it",
    )
    unify_parser.add_argument("keep", metavar="KEEP", help="the note that takes the unified text")
    unify_parser.add_argument("others", nargs="+", metavar="OTHER", help="notes that KEEP replaces")
    unify_parser.add_argument(
        "--body-file",
        required=True,
        metavar="PATH",
        help="the unified body (after the frontmatter); - reads standard input",
    )
    unify_parser.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    unify_parser.add_argument(
        "--drop", action="store_true", help="accept a unified text that lacks a link the notes had"
    )
    unify_parser.set_defaults(func=cmd_unify)
    new_parser = sub.add_parser("new", help="create a note from its template")
    new_sub = new_parser.add_subparsers(dest="type", required=True)
    for note_type, flags in {
        "literature": {
            "title": {},
            "author": {},
            "year": {"type": int},
            "kind": {"choices": _KINDS},
            "level": {"choices": LEVELS},
            "url": {},
            "topics": {},
            "slug": {},
        },
        "knowledge": {
            "slug": {},
            "claim": {},
            "topics": {},
            "confidence": {"choices": _CONFIDENCE},
            "level": {"choices": LEVELS},
            "origin": {"choices": _ORIGINS},
        },
        "research": {"slug": {}, "title": {}, "question": {}, "topics": {}},
    }.items():
        type_parser = new_sub.add_parser(note_type)
        type_parser.add_argument(
            "--body-file",
            metavar="PATH",
            help="text (or - for standard input) that replaces the template body",
        )
        for flag, opts in flags.items():
            type_parser.add_argument(f"--{flag}", required=True, **opts)
        if note_type == "knowledge":
            type_parser.add_argument(
                "--part-of",
                metavar="s:HANDLE#SECTION",
                help="the synthesis section this note summarizes",
            )
        type_parser.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
        type_parser.set_defaults(func=cmd_new)
    remember_parser = sub.add_parser(
        "remember", help="write a memory in the project or, with --global, in the global folder"
    )
    remember_parser.add_argument("--kind", required=True, choices=records.KINDS)
    remember_parser.add_argument("--claim", required=True)
    remember_parser.add_argument(
        "--body-file", metavar="PATH", help="text (or - for standard input); may be empty"
    )
    remember_parser.add_argument("--context")
    remember_parser.add_argument(
        "--short",
        metavar="TEXT",
        help="the claim as one line of at most 120 characters, loaded at session start",
    )
    remember_parser.add_argument("--user-read", action="store_true", help=_USER_READ)
    remember_parser.add_argument(
        "--topic", metavar="TEXT", help="one or two lowercase words that group rules"
    )
    remember_parser.add_argument("--valid-until", type=_today, default=None, metavar="YYYY-MM-DD")
    remember_parser.add_argument("--source", action="append", default=[], metavar="URL_OR_PATH")
    remember_parser.add_argument(
        "--origin",
        choices=records.ORIGINS,
        help="where the claim came from when not a session: web (a finding), pipeline (a pipeline's write) "
        "or transcript (a lesson captured from a session transcript)",
    )
    remember_parser.add_argument(
        "--reach", choices=records.REACHES, help="how far the lesson reaches"
    )
    remember_parser.add_argument(
        "--weight",
        choices=records.WEIGHTS,
        help="how much it weighs: light needs 1 session to be established, medium 2, strong 3",
    )
    remember_parser.add_argument(
        "--outcome",
        choices=records.OUTCOMES,
        help="what the session showed about the lesson; recorded as a case of its log",
    )
    remember_parser.add_argument(
        "--seen-on",
        type=_today,
        default=None,
        metavar="YYYY-MM-DD",
        help="the day of the session, when it is not today",
    )
    remember_parser.add_argument("--global", dest="is_global", action="store_true")
    remember_parser.add_argument(
        "--force", action="store_true", help="write even when a memory has the same claim"
    )
    remember_parser.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    remember_parser.set_defaults(func=cmd_remember)
    index_cmd = sub.add_parser(
        "session-index", help="print the text that opens a session: usage rules and counts"
    )
    index_cmd.add_argument(
        "--hook",
        action="store_true",
        help="read the hook's JSON from standard input (its cwd locates the project) and log the call",
    )
    index_cmd.add_argument(
        "--list",
        type=int,
        default=0,
        metavar="N",
        help="also list up to N of the project's newest memories",
    )
    index_cmd.set_defaults(func=cmd_session_index)
    compact_cmd = sub.add_parser(
        "compact-log", help="check the handoff block of a compaction summary and log counts"
    )
    compact_cmd.add_argument(
        "--hook", action="store_true", help="read the hook's JSON from standard input"
    )
    compact_cmd.set_defaults(func=cmd_compact_log)
    signal_cmd = sub.add_parser(
        "signal", help="print the records related to a brief read from standard input"
    )
    signal_cmd.add_argument(
        "--hook",
        action="store_true",
        help="read a PreToolUse hook's JSON from standard input and print the brief with the signal appended",
    )
    signal_cmd.set_defaults(func=cmd_signal)

    def memory_command(name: str, help_text: str, *handles: str, because: bool = False):
        cmd = sub.add_parser(name, help=help_text)
        for h in handles:
            cmd.add_argument(h, metavar="m:HANDLE")
        if because:
            cmd.add_argument(
                "--because", metavar="TEXT", help="the reason, appended to the memory's body"
            )
            cmd.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
        cmd.add_argument(
            "--global",
            dest="is_global",
            action="store_true",
            help="act on the global memory when the handle exists in both scopes",
        )
        return cmd

    for name, text in (
        ("confirm", "count one more observation of a memory"),
        ("observe", "alias of confirm"),
    ):
        confirm_parser = memory_command(name, text, "handle")
        confirm_parser.add_argument(
            "--until", metavar="YYYY-MM-DD", help="also set valid_until to this date"
        )
        confirm_parser.add_argument(
            "--source",
            metavar="'session ID'",
            help="another session shows it: add it as a source (exit 3 when already one)",
        )
        confirm_parser.add_argument(
            "--note", metavar="TEXT", help="with --source: a line added to the body"
        )
        confirm_parser.add_argument(
            "--outcome",
            choices=records.OUTCOMES,
            help="with --source: what that session showed about the lesson (default seen)",
        )
        confirm_parser.add_argument(
            "--seen-on",
            type=_today,
            default=None,
            metavar="YYYY-MM-DD",
            help="with --source: the day of that session (default today)",
        )
        confirm_parser.add_argument(
            "--by-owner",
            action="store_true",
            help="the owner vouches for a transcript lesson: it is established (exit 3 when already)",
        )
        confirm_parser.set_defaults(func=cmd_confirm)
    memory_command("refute", "mark a memory refuted", "handle", because=True).set_defaults(
        func=cmd_refute
    )
    memory_command("forget", "mark a memory forgotten", "handle", because=True).set_defaults(
        func=cmd_forget
    )
    triage_parser = sub.add_parser(
        "triage",
        help="decide what a corroborated general lesson becomes",
        description="Triage is deciding what a corroborated general lesson becomes: one seen in two projects leaves "
        "quarantine and waits here (mem curate --global lists it).",
    )
    triage_sub = triage_parser.add_subparsers(dest="triage_command", required=True)
    triage_hold = triage_sub.add_parser(
        "hold",
        help="keep a general lesson out of the rules until the owner decides",
        description="Hold: a global lesson is set to await triage, with the reason, and stops loading as a rule.",
    )
    triage_hold.add_argument("handle", metavar="m:HANDLE")
    triage_hold.add_argument(
        "--because", metavar="TEXT", help="why it is held (one line, at most 200 characters)"
    )
    for verb, text in (
        (
            "accept",
            "a general lesson that awaits triage stays a general lesson every project may read",
        ),
        (
            "reject",
            (
                "a general lesson that awaits triage is retired (mem restore brings it back), and "
                "its project records are marked so they are not promoted again"
            ),
        ),
    ):
        triage_verb = triage_sub.add_parser(
            verb, help=text, description=f"{verb.capitalize()}: {text}."
        )
        triage_verb.add_argument("handle", metavar="m:HANDLE")
        if verb == "accept":
            triage_verb.add_argument(
                "--project-scope",
                dest="project_scope",
                action="store_true",
                help="keep the wording of a project lesson that got worse",
            )
    triage_parser.set_defaults(func=cmd_triage)
    memory_command("supersede", "mark OLD as superseded by NEW", "old", "new").set_defaults(
        func=cmd_supersede
    )
    merge_parser = memory_command(
        "merge", "add DROP's count and body to KEEP and supersede DROP", "keep", "drop"
    )
    merge_parser.add_argument(
        "--force",
        action="store_true",
        help="merge although the claims differ by a negation or a number",
    )
    merge_parser.set_defaults(func=cmd_merge)
    memory_command(
        "distinct",
        "record that two memories are different claims: the queue stops pairing them",
        "a",
        "b",
    ).set_defaults(func=cmd_distinct)
    memory_command(
        "restore", "put back the text a memory had before its last curation action", "handle"
    ).set_defaults(func=cmd_restore)
    promote_parser = sub.add_parser(
        "promote", help="print a draft of a global memory from project memories"
    )
    promote_parser.add_argument(
        "--no", action="store_true", help="record that the memory is not for a global note"
    )
    promote_parser.add_argument(
        "--done", action="store_true", help="record that the memory was promoted"
    )
    promote_parser.add_argument(
        "--to", metavar="m:HANDLE", help="with --done: the global memory it was promoted to"
    )
    promote_parser.add_argument("handles", nargs="+", metavar="m:HANDLE")
    promote_parser.set_defaults(func=cmd_promote)
    memories_parser = sub.add_parser("memories", help="list memories, newest first")
    curate_parser = sub.add_parser(
        "curate", help="list what needs a decision: pairs, expired, frequent, unconfirmed"
    )
    scope_group = memories_parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--global", dest="is_global", action="store_true", help="the global memories only"
    )
    scope_group.add_argument("--all", action="store_true", help="project and global memories")
    scope_group.add_argument(
        "--project", metavar="NAME", help="the memories of this registered project"
    )
    curate_scope = curate_parser.add_mutually_exclusive_group()
    curate_scope.add_argument(
        "--project", dest="is_project", action="store_true", help="the project's memories only"
    )
    curate_scope.add_argument(
        "--global", dest="is_global", action="store_true", help="the global memories only"
    )
    memories_parser.add_argument("--kind", choices=records.KINDS)
    memories_parser.add_argument(
        "--quarantine",
        action="store_true",
        help="only the global lessons in quarantine (not shown anywhere else until corroborated)",
    )
    memories_parser.add_argument(
        "--dead", action="store_true", help="also list refuted, superseded, forgotten and expired"
    )
    memories_parser.set_defaults(func=cmd_memories)
    rules_parser = sub.add_parser(
        "rules", help="print the rules that load at session start; --more lists the rest"
    )
    rules_parser.add_argument(
        "--more",
        nargs="?",
        const=True,
        default=None,
        metavar="TOPIC",
        help="the lessons left out, grouped by topic; with TOPIC only that group (other: no topic)",
    )
    rules_parser.add_argument(
        "--layout",
        choices=rules.LAYOUTS,
        help="print the lessons flat or under a heading per topic (default: MEM_RULES_LAYOUT, else flat)",
    )
    rules_parser.add_argument(
        "--unread",
        action="store_true",
        help="list the short forms a model wrote that nobody read, with their claims",
    )
    rules_parser.add_argument(
        "--read",
        nargs="+",
        metavar="HANDLE",
        help="mark short forms as read: the handles, or all of those --unread lists",
    )
    rules_parser.set_defaults(func=cmd_rules)
    curate_parser.add_argument(
        "--notes",
        action="store_true",
        help="list notes to attach to a synthesis part, and notes older than their part",
    )
    curate_parser.add_argument(
        "--done",
        action="store_true",
        help="record today as the date of the last pass over the scopes covered",
    )
    curate_parser.add_argument(
        "--new-since",
        type=float,
        metavar="EPOCH",
        help="print the number of global memories and notes written since EPOCH seconds (and since the last pass)",
    )
    curate_parser.add_argument(
        "action",
        nargs="?",
        choices=["apply"],
        help="apply: carry out the safe actions read from --from FILE or stdin (needs --safe)",
    )
    curate_parser.add_argument(
        "--safe",
        action="store_true",
        help="with apply: only merges of equal claims and attaches the part's Sources line backs",
    )
    curate_parser.add_argument(
        "--from",
        dest="from_file",
        metavar="FILE",
        help="with apply: the action lines (default or -: stdin)",
    )
    curate_parser.set_defaults(func=cmd_curate)
    settle_parser = sub.add_parser(
        "settle", help="settle new global memories against their look-alikes (verdicts from a file)"
    )
    settle_sub = settle_parser.add_subparsers(dest="settle_command", required=True)
    settle_pending = settle_sub.add_parser(
        "pending", help="list the look-alike pairs with a not yet judged side"
    )
    settle_pending.add_argument(
        "--json",
        action="store_true",
        help="a JSON list: pair, a, b, claim_a, claim_b, newer, flagged_words",
    )
    settle_apply = settle_sub.add_parser(
        "apply", help="carry out the verdicts the rules allow; refused rows are printed"
    )
    settle_apply.add_argument(
        "--verdicts",
        required=True,
        metavar="FILE",
        help='JSON list of {"a", "b", "decision": merge|supersede|distinct|nothing, "reason"}',
    )
    settle_log = settle_sub.add_parser("log", help="list the settlings not yet acknowledged")
    settle_log.add_argument(
        "--all", action="store_true", help="every settling, acknowledged and undone ones too"
    )
    settle_sub.add_parser("ack", help="mark every settling acknowledged")
    settle_undo = settle_sub.add_parser(
        "undo", help="undo settling N: both records back as they were"
    )
    settle_undo.add_argument("number", type=int, metavar="N")
    settle_due = settle_sub.add_parser(
        "due",
        help="exit 0 and print the count when new memories wait and the last apply is older than M minutes",
    )
    settle_due.add_argument("--minutes", type=float, required=True, metavar="M")
    settle_parser.set_defaults(func=cmd_settle)
    ps_parser = sub.add_parser(
        "project-synthesis",
        help="write, confirm and list the stamped parts of a project's syntheses",
    )
    ps_sub = ps_parser.add_subparsers(dest="ps_command", required=True)
    ps_add = ps_sub.add_parser(
        "add", help="write a part, or replace the one with the same heading; prints p:NAME#HANDLE"
    )
    ps_add.add_argument(
        "name", metavar="NAME", help="one of: " + ", ".join(project_syntheses.NAMES)
    )
    ps_add.add_argument("heading")
    ps_add.add_argument(
        "--paths", required=True, metavar="A,B", help="the project files or folders the part covers"
    )
    ps_add.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    ps_confirm = ps_sub.add_parser("confirm", help="stamp a part as checked today, text unchanged")
    ps_confirm.add_argument("part", metavar="p:NAME#HANDLE")
    ps_sub.add_parser("list", help="one line per part: handle, freshness, heading")
    ps_parser.set_defaults(func=cmd_project_synthesis)
    synthesis_parser = sub.add_parser(
        "synthesis", help="create and extend syntheses, the long documents behind notes"
    )
    synthesis_sub = synthesis_parser.add_subparsers(dest="synthesis_command", required=True)
    syn_new = synthesis_sub.add_parser("new", help="create syntheses/<slug>.md with its summary")
    syn_new.add_argument("--title", required=True)
    syn_new.add_argument("--topics", required=True, help="comma-separated topic ids")
    syn_new.add_argument("--slug", required=True)
    syn_new.add_argument(
        "--summary-file", metavar="PATH", help="the summary (or - for standard input)"
    )
    syn_add = synthesis_sub.add_parser(
        "add", help="append one section; its text must end with a `Sources:` line"
    )
    syn_add.add_argument("target", metavar="s:HANDLE")
    syn_add.add_argument("--section", required=True, metavar="HEADING")
    syn_add.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    syn_add.add_argument(
        "--note-slug",
        metavar="SLUG",
        help="also write a knowledge note that summarizes the section",
    )
    syn_add.add_argument("--note-claim", metavar="TEXT")
    syn_add.add_argument(
        "--note-body-file", metavar="PATH", help="the note's body (or - for standard input)"
    )
    syn_add.add_argument("--confidence", choices=_CONFIDENCE)
    syn_add.add_argument("--level", choices=LEVELS)
    syn_add.add_argument(
        "--origin", choices=_ORIGINS, help="default: taken from the section's Sources line"
    )
    syn_edit = synthesis_sub.add_parser(
        "edit", help="replace the text of one section; the rest of the file stays"
    )
    syn_edit.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_edit.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    syn_edit.add_argument(
        "--shrink", action="store_true", help="allow a text with fewer words or links than before"
    )
    syn_edit.add_argument(
        "--drop-references",
        action="store_true",
        help="allow a sentence kept unchanged to lose a reference (a note link in its body)",
    )
    syn_append = synthesis_sub.add_parser(
        "append", help="add text at the end of a section, before its Sources line"
    )
    syn_append.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_append.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    syn_attach = synthesis_sub.add_parser(
        "attach", help="make a knowledge note the short recall of a section"
    )
    syn_attach.add_argument("note", metavar="NOTE")
    syn_attach.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_rename = synthesis_sub.add_parser(
        "rename", help="rename a section's heading; its notes follow"
    )
    syn_rename.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_rename.add_argument("heading", metavar="NEW_HEADING")
    syn_remove = synthesis_sub.add_parser(
        "remove", help="take a section out; its notes lose part_of"
    )
    syn_remove.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_detach = synthesis_sub.add_parser("detach", help="remove a note's part_of")
    syn_detach.add_argument("note", metavar="NOTE")
    syn_refs = synthesis_sub.add_parser(
        "refs", help="add or remove inline note references from a file of proposals"
    )
    syn_refs.add_argument("target", metavar="s:HANDLE")
    syn_refs.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="one proposal per line: SECTION | UNIT | add TARGET  or  SECTION | UNIT | remove TARGET",
    )
    syn_topics = synthesis_sub.add_parser("topics", help="replace a synthesis's topics")
    syn_topics.add_argument("target", metavar="s:HANDLE")
    syn_topics.add_argument("topic_ids", metavar="TOPICS", help="comma-separated topic ids")
    for syn_cmd in (syn_new, syn_add, syn_edit, syn_append, syn_rename):
        syn_cmd.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    syn_list = synthesis_sub.add_parser("list", help="one line per synthesis")
    syn_list.add_argument("--topic")
    synthesis_parser.set_defaults(func=cmd_synthesis)
    terms_parser = sub.add_parser(
        "terms", help="manage the terms that must not reach the global scope"
    )
    terms_sub = terms_parser.add_subparsers(dest="terms_command", required=True)
    terms_sub.add_parser("list", help="print hard<TAB>term and soft<TAB>term lines")
    terms_add = terms_sub.add_parser("add", help="add a term to the list")
    terms_add.add_argument("term")
    terms_add.add_argument(
        "--soft",
        action="store_true",
        help="a soft term: the owner must approve a write that holds it",
    )
    terms_add.add_argument(
        "--kind",
        choices=records.TERM_KINDS,
        help="with --soft: only for this kind of memory, or note or synthesis",
    )
    terms_remove = terms_sub.add_parser(
        "remove", help="remove every line that holds exactly this term"
    )
    terms_remove.add_argument("term")
    terms_parser.set_defaults(func=cmd_terms)
    projects_parser = sub.add_parser(
        "projects", help="the local registry of projects whose memories can be searched"
    )
    projects_sub = projects_parser.add_subparsers(dest="projects_command", required=True)
    projects_sub.add_parser("list", help="one line per project: name, live memories, path")
    projects_add = projects_sub.add_parser("add", help="register a project by hand")
    projects_add.add_argument("path")
    projects_add.add_argument("--name")
    projects_remove = projects_sub.add_parser(
        "remove", help="forget a project; its files are not touched"
    )
    projects_remove.add_argument("name")
    projects_parser.set_defaults(func=cmd_projects)
    init_parser = sub.add_parser(
        "init", help="make a folder a writable store (default: the default store)"
    )
    init_parser.add_argument("folder", metavar="FOLDER", nargs="?")
    init_parser.set_defaults(func=cmd_init)
    history_parser = sub.add_parser("history", help="the store's git history: list, init, commit")
    history_parser.add_argument(
        "-n", type=int, default=10, metavar="N", help="how many commits to list"
    )
    history_sub = history_parser.add_subparsers(dest="history_command")
    history_init = history_sub.add_parser("init", help="make a writable store a git repository")
    history_init.add_argument("folder", metavar="STORE", nargs="?")
    history_commit = history_sub.add_parser("commit", help="commit what changed in the store")
    history_commit.add_argument("-m", dest="message", metavar="TEXT", help="the commit message")
    history_commit.add_argument(
        "--hook",
        action="store_true",
        help="the SessionEnd hook: a `session end` message, silent, always exit 0, log the call",
    )
    history_commit.add_argument(
        "--detached",
        action="store_true",
        help="with --hook: also log a `started` record before and a `done` one after, so a killed run shows",
    )
    history_parser.set_defaults(func=cmd_history)
    memory_parser = sub.add_parser(
        "memory", help="change a memory through mem, never by editing its file"
    )
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_edit = memory_sub.add_parser(
        "edit", help="replace the claim, the context or the body of a memory"
    )
    memory_edit.add_argument("handle", metavar="m:HANDLE")
    memory_edit.add_argument("--claim", metavar="TEXT", help="the new claim (one sentence)")
    memory_edit.add_argument(
        "--context", metavar="TEXT", help="the new context; an empty text removes it"
    )
    memory_edit.add_argument(
        "--body-file", metavar="PATH", help="the new body; - reads standard input"
    )
    memory_edit.add_argument(
        "--short",
        metavar="TEXT",
        help="the one-line rule loaded at session start; an empty text removes it",
    )
    memory_edit.add_argument("--user-read", action="store_true", help=_USER_READ)
    memory_edit.add_argument(
        "--reworded",
        action="store_true",
        help="with --short: the automatic step wrote this text; marks the lesson as reworded",
    )
    memory_edit.add_argument(
        "--reword-failed",
        action="store_true",
        help="alone: note that the automatic rewording gave up on the last version",
    )
    memory_edit.add_argument(
        "--topic", metavar="TEXT", help="one or two lowercase words; an empty text removes it"
    )
    load_switch = memory_edit.add_mutually_exclusive_group()
    load_switch.add_argument(
        "--no-load", action="store_true", help="never load this lesson as a rule"
    )
    load_switch.add_argument(
        "--index-only",
        action="store_true",
        help="never load this lesson as a rule, but count it in the index line by topic",
    )
    load_switch.add_argument(
        "--load", action="store_true", help="remove --no-load and --index-only"
    )
    memory_edit.add_argument(
        "--shrink",
        action="store_true",
        help="accept a text that drops over 20%% of the words, a sentence or a link",
    )
    memory_edit.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    memory_edit.add_argument(
        "--global",
        dest="is_global",
        action="store_true",
        help="edit the global memory when the handle exists in both scopes",
    )
    memory_parser.set_defaults(func=cmd_memory)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return _dispatch(argv)
    except safe_io.UnsafePath as exc:  # a symlink where a command refuses one
        print(f"mem: refused: {exc}", file=sys.stderr)
        return 2


def _dispatch(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "read":
        args.command = "show"
    if refusal := safe_io.sandbox_refusal(args.command, vars(args)):
        print(f"mem: {refusal}", file=sys.stderr)
        return 2
    if args.command in {
        "init",
        "terms",
        "history",
    }:  # history finds its own store: `history init` may name one
        return args.func(args)
    if (
        args.command in _NO_STORE_NEEDED
    ):  # a project memory needs no store; a missing one is an error only where used
        root = resolve_root(args.root, os.environ)
        args.root = root
        return args.func(args)
    root = resolve_root(args.root, os.environ)
    if (
        args.command == "search"
        and args.scope == "memories"
        and (root is None or not root.is_dir())
    ):
        args.root = None  # memories need no store; only a project or a global folder
        return args.func(args)
    if (
        args.command == "show"
        and all(a.startswith(("m:", "p:")) or _find_memory(args, a) for a in args.paths)
        and (root is None or not root.is_dir())
    ):
        args.root = None
        return args.func(args)
    if root is None:
        print(NO_STORE, file=sys.stderr)
        return 2
    if root.exists() and not root.is_dir():
        print(f"mem: the store is not a folder: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"mem: the store folder does not exist: {root}", file=sys.stderr)
        return 2
    writes = args.command in _WRITE_COMMANDS or (
        args.command == "synthesis" and args.synthesis_command in _SYNTHESIS_WRITES
    )
    if writes and not records.store_is_writable(root):
        print(
            f"mem: {args.command} writes to the store, which is read-only: it has no mem-store.yaml "
            '(create a store with "mem init").',
            file=sys.stderr,
        )
        return 2
    args.root_source = store_source(args.root, os.environ)
    args.root = root
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
