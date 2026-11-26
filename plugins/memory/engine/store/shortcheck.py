"""Code check that a short form is not stronger than the claim it was drawn from.

Pure: imports nothing from the engine. Length and the one-line rule are checked elsewhere.
"""

import re

HEDGES = frozenset([
    "may",
    "might",
    "can",
    "could",
    "sometimes",
    "often",
    "usually",
    "once",
    "untested",
    "provisional",
    "seems",
    "seemed",
    "likely",
    "probably",
    "consider",
    "perhaps",
])
ABSOLUTES = frozenset([
    "always",
    "never",
    "must",
    "every",
    "all",
    "only",
    "none",
    "cannot",
    "can't",
    "guarantees",
    "ensures",
    "proves",
])

_WORD = re.compile(r"[a-z']+")
_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


def _words(text: str) -> list[str]:
    # a typographic apostrophe is the plain one; quoting apostrophes are stripped, an inner one (can't) stays
    found = _WORD.findall(text.lower().replace("\u2019", "'").replace("\u2018", "'"))
    return [w for w in (m.strip("'") for m in found) if w]


def problems(claim: str, short: str) -> list[str]:
    """English reasons the short form is stronger than its claim; [] when it passes."""
    claim_words, short_words = _words(claim), _words(short)
    out = []
    if HEDGES.intersection(claim_words) and not HEDGES.intersection(short_words):
        out.append("the claim is hedged and the short form is not")
    seen = set()
    for w in short_words:
        if w in ABSOLUTES and w not in claim_words and w not in seen:
            seen.add(w)
            out.append(f'the short form says "{w}" and the claim does not')
    if _LINK.search(short):
        out.append("the short form holds a link")
    if any(w in {"owner", "owner's", "owners"} for w in short_words):
        out.append('the short form says "owner": say "the user"')
    return out
