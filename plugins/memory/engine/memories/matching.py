"""Matching memories by shared terms: tokens, containment, the related-record lists, and the pairs that may duplicate or refute each other (similarity, the comparison budget, the words that differ)."""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Required, TypedDict, Unpack

from memories.model import is_live

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence

    from memories.model import Memory


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


def similarity(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class Budget:
    """Claim comparisons a caller lets pair searches spend, shared by passing one object to several searches.

    `left` counts down by one per comparison. `exhausted` turns True when a search needed a comparison and `left`
    was 0: `left == 0` alone does not say it, because a budget spent to the last comparison compared everything."""

    left: int
    exhausted: bool = False

    def spend(self) -> bool:
        if self.left <= 0:
            self.exhausted = True
            return False
        self.left -= 1
        return True


def _among_order(
    live: Sequence[Memory], index: Mapping[str, int], among: Sequence[str]
) -> Iterator[tuple[int, int]]:
    """Index pairs with at least one `among` memory, each pair once, in the order of `among`."""
    seen: set[str] = set()
    for h in among:
        i = index.get(h)
        if i is None or h in seen:
            continue
        seen.add(h)
        for j in range(len(live)):
            if j != i and live[j].handle not in seen:
                yield min(i, j), max(i, j)


@dataclass(frozen=True)
class PairSearch:
    """How `pairs` searches: `among` (handles, in the order to search) limits it to pairs with at least one of them,
    each pair once; `budget` spends 1 per comparison and stops the search when spent (the caller reads
    `budget.exhausted`); `floor` is the lowest containment kept, STRONG unless a caller whose pairs a model judges
    lowers it."""

    among: Sequence[str] | None = None
    budget: Budget | None = None
    floor: float = STRONG


def pairs(
    memories: Sequence[Memory],
    today: datetime.date,
    *,
    tokenize: Callable[[str], list[str]],
    among: Sequence[str] | None = None,
    budget: Budget | None = None,
) -> list[tuple[Memory, Memory, float]]:
    """Pairs of live memories whose claims contain each other with at least STRONG, in either direction.

    A claim and its negation score as high as a near-copy: a pair means "same or opposite", never "duplicate".
    `among` and `budget` as in `PairSearch`."""
    return pairs_by(memories, today, tokenize, PairSearch(among=among, budget=budget))


def pairs_by(
    memories: Sequence[Memory],
    today: datetime.date,
    tokenize: Callable[[str], list[str]],
    how: PairSearch,
) -> list[tuple[Memory, Memory, float]]:
    """`pairs` with every choice of `PairSearch`, the floor included."""
    live = sorted((m for m in memories if is_live(m, today)), key=lambda m: m.handle)
    index = {m.handle: i for i, m in enumerate(live)}
    tokens = [set(tokenize(m.claim)) for m in live]
    terms = [_terms(t) for t in tokens]
    if how.among is None:
        order = ((i, j) for i in range(len(live)) for j in range(i + 1, len(live)))
    else:
        order = _among_order(live, index, how.among)
    found = []
    for i, j in order:
        a, b = live[i], live[j]
        if b.handle in a.distinct_from or a.handle in b.distinct_from:
            continue
        if how.budget is not None and not how.budget.spend():
            break
        score = max(
            _containment_of_terms(terms[i], tokens[j]), _containment_of_terms(terms[j], tokens[i])
        )
        if score >= how.floor:
            found.append((a, b, score))
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


def _claim_terms(
    claim: str, tokenize: Callable[[str], list[str]]
) -> tuple[set[str], frozenset[str]]:
    tokens = set(tokenize(claim))
    return tokens, _terms(tokens)


def _may_refute(live: Memory, dead: Memory) -> bool:
    """Whether `live` could refute-contradict `dead`: not recorded as distinct, and written after the refutation."""
    if dead.handle in live.distinct_from or live.handle in dead.distinct_from:
        return False
    since = dead.refuted or dead.created
    return live.created is not None and (since is None or live.created > since)


def _refuted_scores(
    live: Memory,
    dead: Sequence[Memory],
    tokenize: Callable[[str], list[str]],
    dead_seen: dict[str, tuple[set[str], frozenset[str]]],
    budget: Budget | None,
) -> tuple[list[tuple[Memory, Memory, float]], bool]:
    """The pairs of `live` with a refuted memory that reach STRONG, and whether the budget ran out."""
    found = []
    mine: tuple[set[str], frozenset[str]] | None = None
    for r in dead:
        if not _may_refute(live, r):
            continue
        if budget is not None and not budget.spend():
            return found, True
        mine = mine or _claim_terms(live.claim, tokenize)
        if r.handle not in dead_seen:
            dead_seen[r.handle] = _claim_terms(r.claim, tokenize)
        (ta, terms_a), (tr, terms_r) = mine, dead_seen[r.handle]
        score = max(_containment_of_terms(terms_a, tr), _containment_of_terms(terms_r, ta))
        if score >= STRONG:
            found.append((live, r, score))
    return found, False


def refuted_pairs(
    memories: Sequence[Memory],
    today: datetime.date,
    *,
    tokenize: Callable[[str], list[str]],
    among: Sequence[str] | None = None,
    budget: Budget | None = None,
) -> list[tuple[Memory, Memory, float]]:
    """(live, refuted, score): a live memory whose claim and a refuted one's contain each other with at least STRONG,
    unless the two are recorded as distinct or the live one is not strictly newer than the refutation
    (its `refuted` date, else the refuted memory's `created`).

    `among` and `budget` work as in `pairs`; `among` restricts the live memories, in its order."""
    live = sorted((m for m in memories if is_live(m, today)), key=lambda m: m.handle)
    if among is not None:
        by_handle = {m.handle: m for m in live}
        live = [by_handle[h] for h in dict.fromkeys(among) if h in by_handle]
    dead = sorted(
        (m for m in memories if m.error is None and m.status == "refuted"), key=lambda m: m.handle
    )
    dead_seen: dict[str, tuple[set[str], frozenset[str]]] = {}  # tokenized when first compared
    found: list[tuple[Memory, Memory, float]] = []
    for a in live:
        scored, spent = _refuted_scores(a, dead, tokenize, dead_seen, budget)
        found.extend(scored)
        if spent:
            break
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


_WORD = re.compile(r"[a-z0-9]+(?:[.'\u2019][a-z0-9]+)*")
_NEGATIONS = frozenset({"not", "no", "never", "cannot", "without"})


def _claim_words(claim: str) -> set[str]:
    return set(_WORD.findall(claim.casefold()))


def differing_words(a: str, b: str) -> list[str]:
    """The words that occur in only one of the two claims, sorted; stop words are left out except negations,
    digits stay. Empty when nothing is left."""
    return sorted(
        w for w in _claim_words(a) ^ _claim_words(b) if w in _NEGATIONS or w not in STOPWORDS
    )


# Pairs of words that make two claims opposites; either member of a pair may be the one in each claim.
OPPOSITES = [
    "works/fails",
    "work/fail",
    "passes/fails",
    "pass/fail",
    "enable/disable",
    "enabled/disabled",
    "allow/deny",
    "allowed/denied",
    "before/after",
    "always/never",
    "on/off",
    "safe/unsafe",
    "increase/decrease",
    "with/without",
    "can/cannot",
    "must/may",
    "add/remove",
    "start/stop",
    "true/false",
    "required/optional",
    "sync/async",
    "up/down",
]


def _partners() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for pair in OPPOSITES:
        x, y = pair.split("/")
        found.setdefault(x, set()).add(y)
        found.setdefault(y, set()).add(x)
    return found


_PARTNERS = _partners()


def flagged_words(a: str, b: str) -> list[str]:
    """The words that differ between two claims and may mean opposites or different versions: any token with a
    digit, a negation, and a word of OPPOSITES whose partner is among the other claim's differing words."""
    wa, wb = _claim_words(a), _claim_words(b)
    only_a, only_b = wa - wb, wb - wa
    flagged = set()
    for mine, other in ((only_a, only_b), (only_b, only_a)):
        for w in mine:
            if (
                w in _NEGATIONS
                or w.endswith(("n't", "n\u2019t"))
                or any(c.isdigit() for c in w)
                or _PARTNERS.get(w, set()) & other
            ):
                flagged.add(w)
    return sorted(flagged)
