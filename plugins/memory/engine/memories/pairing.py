"""Pairs of memories: similarity, the comparison budget, the pairs that may duplicate or refute each other and the words that differ between them."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memories.matching import (
    STOPWORDS,
    STRONG,
    _containment_of_terms,
    _terms,
)
from memories.model import is_live

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

    from memories.model import Memory


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

    With `among` (handles, in the order to search) only pairs with at least one of them are compared, each pair
    once, searching `among` in its order. With `budget` each comparison spends 1 and the search stops when it is
    spent, returning what it found; the caller reads `budget.exhausted` (a comparison was needed with none left)."""
    live = sorted((m for m in memories if is_live(m, today)), key=lambda m: m.handle)
    index = {m.handle: i for i, m in enumerate(live)}
    tokens = [set(tokenize(m.claim)) for m in live]
    terms = [_terms(t) for t in tokens]
    if among is None:
        order = ((i, j) for i in range(len(live)) for j in range(i + 1, len(live)))
    else:
        order = _among_order(live, index, among)
    found = []
    for i, j in order:
        a, b = live[i], live[j]
        if b.handle in a.distinct_from or a.handle in b.distinct_from:
            continue
        if budget is not None and not budget.spend():
            break
        score = max(
            _containment_of_terms(terms[i], tokens[j]), _containment_of_terms(terms[j], tokens[i])
        )
        if score >= STRONG:
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
