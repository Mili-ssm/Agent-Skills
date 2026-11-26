"""Field rules of a note's frontmatter: the `Problem` record, the per-field validators and the type schemas. Pure."""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from typing import Any, NamedTuple


class Problem(NamedTuple):
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")

# Rule 11. Noun/verb homographs (check, test, cache, index, scale, prompt, query, start, stop,
# move, pin, separate, split, run, read, write, log, record, set, limit, measure, document,
# store) are left out on purpose, so a real claim is not rejected. Known limitation: a claim
# that starts with one of these words (use-after-free-...) is rejected too.
_IMPERATIVES = frozenset({
    "add",
    "always",
    "apply",
    "ask",
    "avoid",
    "choose",
    "compare",
    "consider",
    "curate",
    "define",
    "do",
    "dont",
    "ensure",
    "fix",
    "give",
    "include",
    "isolate",
    "keep",
    "make",
    "never",
    "prefer",
    "put",
    "remove",
    "replace",
    "require",
    "show",
    "tell",
    "treat",
    "try",
    "use",
    "validate",
    "verify",
    "wrap",
})
_INSTRUCTION_FIX = 'rename to a declarative claim such as "x-is-y" and update links'


def instruction_word(stem: str) -> str | None:
    """The imperative that makes a knowledge file stem read as an instruction, else None.

    Looked at: the first token and the token right after a "so" or "then" token.
    """
    tokens = stem.split("-")
    positions = [0] + [i + 1 for i, t in enumerate(tokens[:-1]) if t in {"so", "then"}]
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
    return (
        None
        if isinstance(v, str) and _PART_OF.fullmatch(v)
        else "use <synthesis handle>#<section handle>"
    )


def _part_hash(v: Any) -> str | None:
    return (
        None
        if isinstance(v, str) and re.fullmatch(r"(?:u:)?[0-9a-f]{10}", v)
        else "set the 10-hex fingerprint of the section (`u:` first for a per-note one)"
    )


def _handle_value(v: Any) -> str | None:
    return None if isinstance(v, str) and v.strip() else "use the handle of a note"


def _handle_list(v: Any) -> str | None:
    ok = isinstance(v, list) and all(isinstance(h, str) and h.strip() for h in v)
    return None if ok else "set a list of note handles"


_DISPUTE_KEYS = ("date", "fact", "source", "quote")


def _disputed(v: Any) -> str | None:
    hint = (
        "set a non-empty list of {date, fact, source, quote} entries (mem note dispute writes them)"
    )
    if not isinstance(v, list) or not v:
        return hint
    for entry in v:
        if not isinstance(entry, dict) or set(entry) != set(_DISPUTE_KEYS):
            return hint
        if (
            _date(entry["date"]) is not None
            or any(not isinstance(entry[k], str) or not entry[k].strip() for k in _DISPUTE_KEYS[1:])
            or _url(entry["source"]) is not None
        ):
            return hint
    return None


LEVELS = ("basic", "beginner", "intermediate", "advanced", "expert", "niche")
# Fields a note may omit. Empty since 2026-11-07: `level` became required once every note had one (ADR 0004).
OPTIONAL_FIELDS: frozenset[str] = frozenset({
    "part_of",
    "part_of_hash",
    "superseded_by",
    "distinct_from",
    "disputed",
})

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
