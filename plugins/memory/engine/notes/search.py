"""Search over the typed notes: filters, BM25F ranking, links, mentions and the search-eval table (A5, ADR 0028). Pure means no subprocess, no `os.environ` and no file writes; it only reads, and prints a skip warning on stderr for a note it cannot read. The `mem` commands print what it returns."""

from __future__ import annotations

import collections
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack

from memories import records

from notes import index as index_files
from notes import links as link_rules
from notes import note as note_files

if TYPE_CHECKING:
    from collections.abc import Iterable


_KEY_VALUE_CELLS = 2  # a two-cell table row: name and value


_MIN_TITLE_WORDS = 4  # a title shorter than this is too generic to match as a phrase


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
    types: set[str] = {type_filter} if type_filter else set(index_files.INDEX_FOLDERS)
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
    note: note_files.Note,
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


def _matching_notes(root: Path, **filters: Unpack[NoteFilters]) -> list[note_files.Note]:
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
    known = note_files.load_topics(root)
    if topic and topic not in known:
        raise note_files.FrontmatterError(_unknown_topic_message(topic, known))
    scope = note_files.descendants(known, topic) if topic else None
    superseded = filters.get("superseded") or False
    result = []
    for note in note_files.discover_notes(root):
        if note.error is not None or not isinstance(note.meta, dict):
            print(
                f"mem: skipping {note.rel}: {note.error or 'frontmatter is not a mapping'}",
                file=sys.stderr,
            )
            continue
        if _search_matches(note, types, wanted, scope, superseded):
            result.append(note)
    return result


def _title(note: note_files.Note) -> str:
    return str(note.meta.get("claim" if note.type == "knowledge" else "title", ""))


def find(root: Path, **filters: Unpack[NoteFilters]) -> list[tuple[str, str]]:
    """(rel, title) of notes matching every filter; claim is the title of knowledge notes."""
    return sorted((n.rel, _title(n)) for n in _matching_notes(root, **filters))


# BM25F (Robertson, Zaragoza and Taylor 2004): each field is length-normalized on its own, the weighted
# term frequencies are summed, and saturation is applied once. Parameters were tuned on docs/search-eval.md
# and held on both held-out halves of it (ADR 0007); retune only the same way.
BM25_K1 = 2.0


FIELD_WEIGHTS = {"title": 8.0, "body": 1.0}


FIELD_B = {"title": 0.3, "body": 0.75}


def _fields(note: note_files.Note) -> dict[str, str]:
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

    notes: list[note_files.Note]
    counts: list[dict[str, collections.Counter]]
    lengths: list[dict[str, int]]
    average: dict[str, float]


def build_corpus(root: Path, **filters: Unpack[NoteFilters]) -> Corpus:
    """Read and tokenize the notes matching `filters` once."""
    notes = _matching_notes(root, **filters)
    counts = [
        {f: collections.Counter(records.tokenize(text)) for f, text in _fields(n).items()}
        for n in notes
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


def rank(corpus: Corpus, query: str, *, limit: int = 10) -> list[tuple[note_files.Note, float]]:
    """(note, score) of the best BM25F matches, best first, ties by `note.rel`; notes scoring 0 are omitted."""
    terms = list(dict.fromkeys(records.tokenize(query)))
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
    root: Path, corpus: Corpus, ranked: list[tuple[note_files.Note, float]], shown: int
) -> list[tuple[note_files.Note, float]]:
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


def _link_targets(root: Path, note: note_files.Note) -> set[str]:
    """Hub-relative paths the note links to (a folder link means its README.md), as `orphan_notes` resolves them."""
    targets = set()
    for _, _, file_part in link_rules._relative_links(note.body, refs=True):
        target = os.path.normpath(root / Path(note.rel).parent / file_part)
        if Path(target).is_dir():
            target = os.path.join(target, "README.md")
        targets.add(Path(os.path.relpath(target, root)).as_posix())
    return targets


def related(
    root: Path, rel: str, *, limit: int = 5, corpus: Corpus | None = None
) -> dict[str, list[note_files.Note]]:
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


def _mention_pattern(note: note_files.Note) -> re.Pattern[str] | None:
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


def unlinked_mentions(root: Path, rel: str, corpus: Corpus) -> list[note_files.Note]:
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
            and pattern.search(link_rules._LINK.sub("", n.body))
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
        top = (
            [n.rel for n, _ in rank(corpus, query, limit=limit)] if records.tokenize(query) else []
        )
        for rel in wanted:
            expected += 1
            if rel in top:
                found += 1
                reciprocal += 1 / (top.index(rel) + 1)
            else:
                misses.append(f'{_EVAL_FILE}:{number}: missed {rel} for "{query}"')
    return misses, found, expected, reciprocal
