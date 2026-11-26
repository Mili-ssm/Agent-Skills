"""Matching a text against memories by shared terms: tokens, containment and the related-record lists."""

from __future__ import annotations

import datetime
import re
import unicodedata
from typing import TYPE_CHECKING, NamedTuple, Required, TypedDict, Unpack

from store.memory_model import is_live

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Sequence

    from store.memory_model import Memory


def _terms(tokens: Iterable[str]) -> frozenset[str]:
    """The distinct terms `containment` counts: no all-digit token, no stop word."""
    return frozenset(t for t in tokens if not t.isdigit()) - STOPWORDS


def _containment_of_terms(terms: frozenset[str], other_tokens: Collection[str]) -> float:
    """`containment` over precomputed terms."""
    if len(terms) < MIN_TERMS:
        return 0.0
    return len(terms.intersection(other_tokens)) / len(terms)


STOPWORDS = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "nor",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "from",
    "by",
    "with",
    "about",
    "as",
    "into",
    "over",
    "under",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "am",
    "do",
    "does",
    "did",
    "has",
    "have",
    "had",
    "will",
    "would",
    "can",
    "could",
    "should",
    "may",
    "might",
    "must",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "his",
    "its",
    "our",
    "their",
    "this",
    "that",
    "these",
    "those",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "why",
    "how",
    "not",
    "no",
    "if",
    "then",
    "than",
    "so",
    "there",
    "here",
])


class MatchOptions(TypedDict, total=False):
    """The keyword options of `match_memories`."""

    tokenize: Required[Callable[[str], list[str]]]
    limit: int  # 3
    include_dead: bool  # False


def match_memories(
    memories: Sequence[Memory],
    query_tokens: Sequence[str],
    today: datetime.date,
    **options: Unpack[MatchOptions],
) -> list[Memory]:
    """Memories holding at least half (rounded up) of the query's non-stop-word terms, best first."""
    tokenize, limit = options["tokenize"], options.get("limit", 3)
    include_dead = options.get("include_dead", False)
    terms = set(query_tokens) - STOPWORDS
    if not terms:
        return []
    need = (len(terms) + 1) // 2
    scored = []
    for m in memories:
        if m.error is not None or not (include_dead or is_live(m, today)):
            continue
        in_claim = terms & set(tokenize(m.claim))
        overall = terms & set(tokenize(" ".join([m.claim, m.context or "", m.body])))
        if len(overall) >= need:
            scored.append((m, len(in_claim), len(overall)))
    scored.sort(
        key=lambda t: (
            -t[1],
            -t[2],
            -t[0].observed,
            -(t[0].created or datetime.date.min).toordinal(),
            t[0].handle,
        )
    )
    return [m for m, _, _ in scored[:limit]]


STRONG = 0.6  # chosen on evals/signal/set.json by the rule in the stage 6 plan
POSSIBLE = 0.5  # counted only, never named
MIN_TERMS = 2


_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase [a-z0-9]+ tokens after NFKD with combining marks removed (García -> garcia)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return _TOKEN.findall("".join(c for c in decomposed if not unicodedata.combining(c)).lower())


def containment(claim_tokens: Iterable[str], text_tokens: Collection[str]) -> float:
    """Share of the claim's distinct non-stop-word terms found in the text; 0.0 under MIN_TERMS terms.

    Measured from the claim's side: a brief has hundreds of words and a claim about ten. A token of only digits
    (a year, a count) is not a term: it matches unrelated briefs."""
    return _containment_of_terms(_terms(claim_tokens), set(text_tokens))


class Related(NamedTuple):
    handle: str
    kind: str  # "m" memory, "n" note
    score: float


def related_records(
    memories: Sequence[Memory],
    note_stems: Sequence[str],
    text: str,
    today: datetime.date,
    *,
    tokenize: Callable[[str], list[str]],
) -> tuple[list[Related], list[Related]]:
    """Records whose claim (a note: its file stem) is largely contained in the text: (strong, possible).

    A record whose handle occurs in the text as a whole token, with or without "m:", is left out: the text already
    names it."""
    text_tokens = set(tokenize(text))
    found: list[Related] = []
    candidates = [(m.handle, "m", m.claim) for m in memories if is_live(m, today)]
    candidates += [(stem, "n", stem.replace("-", " ")) for stem in note_stems]
    for handle, kind, claim in candidates:
        if re.search(rf"(?<![\w-]){re.escape(handle)}(?![\w-])", text):
            continue
        score = containment(tokenize(claim), text_tokens)
        if score >= POSSIBLE:
            found.append(Related(handle, kind, score))
    found.sort(key=lambda r: (-r.score, r.kind != "m", r.handle))
    return ([r for r in found if r.score >= STRONG], [r for r in found if r.score < STRONG])
