"""The lessons that load as rules at session start: which ones, in what order, and the text.

Pure: it takes lists of `Memory` and a date and returns data and strings; it reads no file and no environment.
The standing after each rule is computed here from the record, never taken from text a model wrote."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Sequence

import records
from records import Memory

HEADER = ("memory: lessons learned in earlier sessions. Apply them with judgment: follow one unless you have a reason "
          "not to, and mention a skipped one only when it matters to the user.")
RULES_MAX = 16
RULES_LIMIT = 2400
MORE_LIMIT = 200
TOPICS_NAMED = 4
PROJECT_FIRST = 3
OVER, PENDING, INDEX = "over the limit", "awaits triage", "index only"
_WEIGHT = {"strong": 0, "medium": 1, "light": 2}


@dataclass
class Choice:
    loaded: list[Memory] = field(default_factory=list)
    left: list[tuple[Memory, str]] = field(default_factory=list)
    unready: int = 0  # lessons that would qualify but have no valid `short`


def eligible(m: Memory, today: datetime.date) -> bool:
    """Every condition to load except `triage` and `short`."""
    if m.error is not None or not records.is_live(m, today) or m.origin != "transcript":
        return False
    if records.standing(m) != "established" or records.quarantined(m) or m.load == "no":
        return False
    return m.scope == "global" or bool(m.owner_confirmed) or len(records.sessions(m)) >= 2


def _rank(m: Memory) -> tuple:
    seen = m.last_observed
    return (m.owner_confirmed is None, _WEIGHT.get(m.weight or "medium", 1), -len(records.projects(m)),
            -len(records.sessions(m)), seen is None, -(seen.toordinal() if seen else 0), m.handle)


def standing_words(m: Memory) -> str:
    if m.owner_confirmed:
        return "(the user vouched for it)"
    n, unit = (len(records.projects(m)), "project") if m.scope == "global" else (len(records.sessions(m)), "session")
    return f"(held in {n} {unit}{'' if n == 1 else 's'})"


def line(m: Memory) -> str:
    return f"- {m.short} {standing_words(m)}"


def choose(project: Sequence[Memory], global_: Sequence[Memory], today: datetime.date) -> Choice:
    out = Choice()
    globals_ = [m for m in global_ if eligible(m, today)]
    # ready to load and competing: an index-only global lesson must not hide its twin in the project it came from
    names = {m.handle for m in globals_ if m.triage != "pending" and records.valid_short(m.short) and m.load is None}
    projects_ = [m for m in project if eligible(m, today) and (m.general or "").removeprefix("m:") not in names]
    ready: list[Memory] = []
    for m in [*projects_, *globals_]:
        if m.triage == "pending":
            out.left.append((m, PENDING))
        elif m.load == "index":
            out.left.append((m, INDEX))
        elif not records.valid_short(m.short):
            out.unready += 1
        else:
            ready.append(m)
    ordered = sorted((m for m in ready if m.scope == "project"), key=_rank)
    first = ordered[:PROJECT_FIRST]
    rest = sorted([*ordered[PROJECT_FIRST:], *(m for m in ready if m.scope != "project")], key=_rank)
    used, full = 0, False
    for m in [*first, *rest]:
        size = len(line(m)) + 1
        if not full and len(out.loaded) < RULES_MAX and used + size <= RULES_LIMIT:
            out.loaded.append(m)
            used += size
        else:
            full = True  # the order decides: nothing ranked lower jumps ahead of a rule that did not fit
            out.left.append((m, OVER))
    return out


LAYOUTS = ("flat", "grouped")


def grouped(choice: Choice) -> list[str]:
    """The loaded lessons under a `<topic>:` line each, topics in the order of their first lesson; no topic: `other:`, last."""
    groups: dict[str, list[str]] = {}
    for m in choice.loaded:
        groups.setdefault(m.topic or "other", []).append(line(m))
    if "other" in groups:
        groups["other"] = groups.pop("other")
    return [x for topic, lines in groups.items() for x in (f"{topic}:", *lines)]


def block(choice: Choice, layout: str = "flat") -> list[str]:
    if not choice.loaded:
        return []
    return [HEADER, *(grouped(choice) if layout == "grouped" else map(line, choice.loaded))]


def topic_counts(choice: Choice) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for m, _ in choice.left:
        if m.topic:
            counts[m.topic] = counts.get(m.topic, 0) + 1
    return sorted(counts.items(), key=lambda t: (-t[1], t[0]))


def not_fitted(choice: Choice) -> list[tuple[Memory, str]]:
    """The lessons that qualify and did not fit. A global lesson awaiting triage is announced by the `Triage:` line."""
    return [(m, why) for m, why in choice.left if why in (OVER, INDEX)]


def more_line(choice: Choice) -> str | None:
    left = not_fitted(choice)
    total = len(left)
    if not total:
        return None
    noun = "lesson" if total == 1 else "lessons"
    topics = topic_counts(Choice(left=left))
    if not topics:
        return f"{total} more {noun}: mem rules --more"
    named = topics[:TOPICS_NAMED]
    while True:
        other = total - sum(n for _, n in named)
        parts = [f"{t} {n}" for t, n in named] + ([f"other {other}"] if other else [])
        text = f"{total} more {noun} by topic: {', '.join(parts)} (mem rules --more <topic>, when a topic fits your task)"
        if len(text) <= MORE_LIMIT or not named:
            break
        named = named[:-1]
    return text if named else f"{total} more {noun}: mem rules --more"
