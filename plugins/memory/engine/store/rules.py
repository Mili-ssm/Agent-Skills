"""The lessons that load as rules at session start: which ones, in what order, and the text.

Pure: it takes lists of `Memory` and a date and returns data and strings; it reads no file and no environment.
The standing after each rule is computed here from the record, never taken from text a model wrote."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from store import fingerprints, sightings
from store.memory_model import is_live, valid_short

if TYPE_CHECKING:
    import datetime
    from collections.abc import Sequence

    from store.memory_model import Memory

HEADER = (
    "memory: lessons learned in earlier sessions. Apply them with judgment: follow one unless you have a reason "
    "not to, and mention a skipped one only when it matters to the user."
)
RULES_LIMIT = 3200
INDEX_LIMIT = 1600
# characters of topic headings printed; a heading is at most digest.HEADING_LIMIT
HEADINGS_LIMIT = 800
TOPICS_NAMED = 4
PROJECT_FIRST = 3
# a project lesson loads once this many sessions held it, unless the owner confirmed it
MIN_SESSIONS = 2
OVER, PENDING, INDEX = "over the limit", "awaits triage", "index only"
_WEIGHT = {"strong": 0, "medium": 1, "light": 2}


@dataclass
class Choice:
    loaded: list[Memory] = field(default_factory=list)
    left: list[tuple[Memory, str]] = field(default_factory=list)
    unready: int = 0  # lessons that would qualify but have no valid `short`
    # the same lessons, `unready` counts them
    unready_lessons: list[Memory] = field(default_factory=list)


def eligible(m: Memory, today: datetime.date) -> bool:
    """Every condition to load except `triage` and `short`."""
    if m.error is not None or not is_live(m, today) or m.origin != "transcript":
        return False
    if sightings.standing(m) != "established" or sightings.quarantined(m) or m.load == "no":
        return False
    return (
        m.scope == "global" or bool(m.owner_confirmed) or len(sightings.sessions(m)) >= MIN_SESSIONS
    )


def _rank(m: Memory) -> tuple:
    seen = m.last_observed
    return (
        m.owner_confirmed is None,
        _WEIGHT.get(m.weight or "medium", 1),
        -len(sightings.projects(m)),
        -len(sightings.sessions(m)),
        seen is None,
        -(seen.toordinal() if seen else 0),
        m.handle,
    )


def standing_words(m: Memory) -> str:
    if m.from_repository:
        return "(from repository)"
    if m.owner_confirmed:
        return "(the user vouched for it)"
    n, unit = (
        (len(sightings.projects(m)), "project")
        if m.scope == "global"
        else (len(sightings.sessions(m)), "session")
    )
    return f"(held in {n} {unit}{'' if n == 1 else 's'})"


def line(m: Memory) -> str:
    return f"- {m.short} {standing_words(m)}"


def _sorted_out(candidates: Sequence[Memory], out: Choice) -> list[Memory]:
    """Records into `out` the lessons that wait for triage, are index only or have no valid short form; returns the ready ones."""
    ready: list[Memory] = []
    for m in candidates:
        if m.triage == "pending":
            out.left.append((m, PENDING))
        elif m.load == "index":
            out.left.append((m, INDEX))
        elif not valid_short(m.short):
            out.unready += 1
            out.unready_lessons.append(m)
        else:
            ready.append(m)
    return ready


def _fill(ranked: Sequence[Memory], out: Choice) -> None:
    """Loads the lessons in order while the limit holds; the rest are left as over the limit."""
    used, full = 0, False
    for m in ranked:
        size = len(line(m)) + 1
        if not full and used + size <= RULES_LIMIT:
            out.loaded.append(m)
            used += size
        else:
            full = True  # the order decides: nothing ranked lower jumps ahead of a rule that did not fit
            out.left.append((m, OVER))


def choose(project: Sequence[Memory], global_: Sequence[Memory], today: datetime.date) -> Choice:
    out = Choice()
    globals_ = [m for m in global_ if eligible(m, today)]
    # ready to load and competing: an index-only global lesson must not hide its twin in the project it came from
    names = {
        m.handle
        for m in globals_
        if m.triage != "pending" and valid_short(m.short) and m.load is None
    }
    projects_ = [
        m
        for m in project
        if eligible(m, today) and (m.general or "").removeprefix("m:") not in names
    ]
    ready = _sorted_out([*projects_, *globals_], out)
    ordered = sorted((m for m in ready if m.scope == "project"), key=_rank)
    first = ordered[:PROJECT_FIRST]
    rest = sorted(
        [*ordered[PROJECT_FIRST:], *(m for m in ready if m.scope != "project")], key=_rank
    )
    _fill([*first, *rest], out)
    return out


LAYOUTS = ("flat", "grouped", "digest")


def _by_topic(choice: Choice) -> dict[str, list[Memory]]:
    groups: dict[str, list[Memory]] = {}
    for m in choice.loaded:
        groups.setdefault(m.topic or "other", []).append(m)
    if "other" in groups:
        groups["other"] = groups.pop("other")
    return groups


def grouped(choice: Choice) -> list[str]:
    """The loaded lessons under a `<topic>:` line each, topics in the order of their first lesson; no topic: `other:`, last."""
    return [x for topic, ms in _by_topic(choice).items() for x in (f"{topic}:", *map(line, ms))]


def _digested(choice: Choice, digest: dict, topics: dict) -> list[str]:
    """`grouped` with the digest's heading after a topic and its line for a global lesson, wherever they are fresh and fit.
    Under a printed heading the lessons with a digest line come first: a short form stands alone, a line leans on the heading."""
    return _printed(_digest_plan(choice, digest, topics))


def _digest_plan(
    choice: Choice, digest: dict, topics: dict
) -> list[tuple[str, str | None, list[tuple[Memory, str | None]]]]:
    """Per topic: its name, its heading when one fits, and (lesson, its fresh line) in the order they print."""
    used_heads = 0
    heads_open = True
    plan: list[tuple[str, str | None, list[tuple[Memory, str | None]]]] = []
    for topic, ms in _by_topic(choice).items():
        lessons = topics.get(topic)
        head = fingerprints.heading(digest, topic, lessons) if lessons else None
        items: list[tuple[Memory, str | None]]
        if lessons and head is not None and heads_open and used_heads + len(head) <= HEADINGS_LIMIT:
            used_heads += len(head)
            items = [
                (m, fingerprints.line(digest, topic, m, lessons) if m.scope == "global" else None)
                for m in ms
            ]
            items = [*(x for x in items if x[1] is not None), *(x for x in items if x[1] is None)]
        else:
            heads_open = (
                heads_open and head is None
            )  # a fresh heading that did not fit closes the rest
            head = None
            items = [(m, None) for m in ms]
        plan.append((topic, head, items))
    return plan


def _printed(plan: Sequence[tuple[str, str | None, list[tuple[Memory, str | None]]]]) -> list[str]:
    """The lines of a plan; a digest line prints only while every short form still to come fits under the limit."""
    pending = [
        len(line(m)) + 1 for _, _, items in plan for m, _ in items
    ]  # short forms still to print, in printed order
    out: list[str] = []
    used, lines_open = 0, True
    for topic, head, items in plan:
        out.append(f"{topic}: {head}" if head is not None else f"{topic}:")
        for m, text in items:
            short = pending.pop(0)
            printed = line(m)
            if text is not None and lines_open:
                digested = f"- {text} {standing_words(m)}"
                if used + len(digested) + 1 + sum(pending) <= RULES_LIMIT:
                    printed, short = digested, len(digested) + 1
                else:
                    lines_open = False
            used += short
            out.append(printed)
    return out


def block(
    choice: Choice, layout: str = "flat", *, digest: dict | None = None, topics: dict | None = None
) -> list[str]:
    if not choice.loaded:
        return []
    if layout == "digest":
        body = (
            _digested(choice, digest, topics or {})
            if digest and digest.get("topics")
            else grouped(choice)
        )
    else:
        body = grouped(choice) if layout == "grouped" else list(map(line, choice.loaded))
    return [HEADER, *body]


def topic_counts(choice: Choice) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for m, _ in choice.left:
        if m.topic:
            counts[m.topic] = counts.get(m.topic, 0) + 1
    return sorted(counts.items(), key=lambda t: (-t[1], t[0]))


def not_fitted(choice: Choice) -> list[tuple[Memory, str]]:
    """The lessons that qualify and did not fit. A global lesson awaiting triage is announced by the `Triage:` line."""
    return [(m, why) for m, why in choice.left if why in {OVER, INDEX}]


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
        if len(text) <= INDEX_LIMIT or not named:
            break
        named = named[:-1]
    return text if named else f"{total} more {noun}: mem rules --more"


def index_lines(
    choice: Choice, *, digest: dict | None = None, topics: dict | None = None
) -> list[str]:
    """The lines after the block for the lessons that did not fit: a line per topic when a fresh heading names one, else `more_line`."""
    left = not_fitted(choice)
    if left and digest and topics:
        counts = dict(topic_counts(Choice(left=left)))
        if other := sum(1 for m, _ in left if not m.topic):
            counts["other"] = other
        heads = {t: fingerprints.heading(digest, t, topics[t]) for t in counts if t in topics}
        if any(h is not None for h in heads.values()):
            names = sorted(counts.items(), key=lambda t: (-t[1], t[0]))
            entries = [
                f"- {t} ({n}): {heads[t]}" if heads.get(t) else f"- {t} ({n})" for t, n in names
            ]
            top = "More lessons, by topic (mem rules --more <topic>):"
            for kept in range(len(entries), -1, -1):
                rest = names[kept:]
                tail = (
                    [
                        f"- and {sum(n for _, n in rest)} more in {len(rest)} topic{'' if len(rest) == 1 else 's'}"
                    ]
                    if rest
                    else []
                )
                lines = [top, *entries[:kept], *tail]
                if len("\n".join(lines)) <= INDEX_LIMIT:
                    return lines
    more = more_line(choice)
    return [more] if more else []
