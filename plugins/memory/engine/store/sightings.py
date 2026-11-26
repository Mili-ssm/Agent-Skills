"""Sightings, cases and versions: the entries a memory's sources, log and versions hold, and what they add up to."""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING, NamedTuple

from store.memory_model import (
    GLOBAL_MIN_PROJECTS,
    OUTCOMES,
    PROJECT_KEY_LEN,
    SESSION_PREFIX,
    SHORT_DATE_LEN,
    SIGHTINGS_NEEDED,
    UNCONFIRMED_DAYS,
    valid_short,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from store.memory_model import Memory


MAX_SESSION_ID = 200  # characters of the id after "session "; longer is not a session
_PROJECT_PART = re.compile(r"(session \S.*?) project (\S+)")
_PROJECT_KEY = re.compile(rf"[0-9a-f]{{{PROJECT_KEY_LEN}}}")


def sighting(source: str) -> tuple[str, str | None] | None:
    """("session <id>", project key or None) of a sighting entry, normalized (stripped, whitespace collapsed,
    lower-cased), else None. A text after "project" that is not a 12-hex key makes the entry no sighting."""
    text = " ".join(source.split()).lower()
    if not text.startswith(SESSION_PREFIX) or len(text) == len(SESSION_PREFIX):
        return None
    key = None
    found = _PROJECT_PART.fullmatch(text)
    if found:
        text, key = found.group(1), found.group(2)
        if not _PROJECT_KEY.fullmatch(key):
            return None
    elif "project" in text[len(SESSION_PREFIX) :].split():
        return None  # "session a project" or "... project <key> extra": a keyed entry gone wrong, not a session id
    return (text, key) if len(text) - len(SESSION_PREFIX) <= MAX_SESSION_ID else None


def sighting_entry(session: str, key: str | None) -> str:
    return f"{session} project {key}" if key else session


def session_key(source: str) -> str | None:
    """The normalized "session <id>" part of a session source (the project, if any, is left out), else None:
    two spellings of one session are one key."""
    found = sighting(source)
    return found[0] if found else None


def _normalized_source(
    source: str, found: tuple[str, str | None] | None, first_key: dict[str, str]
) -> str | None:
    """`source` normalized, or None when it repeats a session that another entry names with a project."""
    if found is None:
        return source
    if found[0] in first_key and found[1] != first_key[found[0]]:
        return None
    return sighting_entry(*found)


def normalized_sources(sources: Iterable[str]) -> list[str]:
    """Session entries in their normalized form, one per session (the first one with a project when several
    occur: one session is one sighting, so it cannot count as two projects); other sources unchanged; order kept."""
    parsed = [(s, sighting(s)) for s in sources]
    first_key: dict[str, str] = {}
    for _, f in parsed:
        if f and f[1]:
            first_key.setdefault(f[0], f[1])
    out = (_normalized_source(s, f, first_key) for s, f in parsed)
    return list(dict.fromkeys(e for e in out if e is not None))


def sessions(memory: Memory) -> list[str]:
    """The distinct sessions of `sources` as normalized keys, in order."""
    return list(dict.fromkeys(k for k in map(session_key, memory.sources) if k))


def projects(memory: Memory) -> list[str]:
    """The distinct project keys of the sighting entries, in order: one per session, its first keyed entry, so a
    file that holds one session under two keys still counts one project."""
    first: dict[str, str] = {}
    for found in map(sighting, memory.sources):
        if found and found[1]:
            first.setdefault(found[0], found[1])
    return list(dict.fromkeys(first.values()))


def standing(memory: Memory) -> str | None:
    """None unless the memory comes from a transcript; then "established" once the owner confirmed it or enough
    distinct sessions show it (by its weight), else "unconfirmed". A global record also needs two projects (C31).
    Never computed from `observed`: a plain confirm, a merge and a curation pass raise it without being
    independent evidence."""
    if memory.origin != "transcript":
        return None
    if memory.owner_confirmed:
        return "established"
    weight = memory.weight or "medium"
    if memory.scope == "global":
        enough = len(projects(memory)) >= GLOBAL_MIN_PROJECTS and (
            weight != "strong" or len(sessions(memory)) >= SIGHTINGS_NEEDED["strong"]
        )
    else:
        enough = len(sessions(memory)) >= SIGHTINGS_NEEDED[weight]
    return "established" if enough else "unconfirmed"


def quarantined(memory: Memory) -> bool:
    return memory.scope == "global" and standing(memory) == "unconfirmed"


def standing_changes(before: Memory | None, after: Memory, today: datetime.date) -> dict:
    """The frontmatter changes that follow from the standing of `after` (a transcript record): its end date, and
    the release of a global record the first time it is established, awaiting triage unless the owner confirmed it
    (that confirmation is the triage). `before` is None for a record being written."""
    established = standing(after) == "established"
    changes: dict = {
        "valid_until": None if established else today + datetime.timedelta(days=UNCONFIRMED_DAYS)
    }
    if after.scope == "global" and established:
        if before is None or before.released is None:
            changes["released"] = today
            if not after.owner_confirmed and (after.weight or "medium") == "strong":
                changes["triage"] = "pending"
        if after.owner_confirmed:
            changes["triage"] = None
    return changes


def counted(memory: Memory, source: str) -> bool:
    """True when the sighting entry adds nothing: its session is counted and either it names no project or the
    session already carries one."""
    found = sighting(source)
    if found is None or found[0] not in sessions(memory):
        return False
    return not found[1] or any(
        f and f[0] == found[0] and f[1] for f in map(sighting, memory.sources)
    )


class Case(NamedTuple):
    on: datetime.date
    session: str  # the normalized "session <id>"
    outcome: str


_CASE = re.compile(r"(\d{4}-\d{2}-\d{2}) (session \S.*) (" + "|".join(OUTCOMES) + ")")


def case(entry: str) -> Case | None:
    """The case of a log entry "<YYYY-MM-DD> session <id> <outcome>", else None."""
    found = _CASE.fullmatch(entry) if isinstance(entry, str) else None
    if not found:
        return None
    try:
        on = datetime.date.fromisoformat(found.group(1))
    except ValueError:
        return None
    if session_key(found.group(2)) != found.group(2):
        return None
    return Case(on, found.group(2), found.group(3))


def case_entry(on: datetime.date, session: str, outcome: str) -> str:
    return f"{on.isoformat()} {session} {outcome}"


def cases(memory: Memory) -> list[Case]:
    """The valid cases of the log by date; entries of one day keep their file order."""
    return sorted((c for c in map(case, memory.log) if c), key=lambda c: c.on)


def _version(entry) -> tuple[datetime.date, str] | None:
    """(date, short form) of a version entry "<YYYY-MM-DD> <short form>", else None."""
    if not isinstance(entry, str):
        return None
    day, _, text = entry.partition(" ")
    try:
        on = datetime.date.fromisoformat(day)
    except ValueError:
        return None
    return (on, text) if len(day) == SHORT_DATE_LEN and valid_short(text) else None


def version_entry(on: datetime.date, short: str) -> str:
    return f"{on.isoformat()} {short}"


def version_list(memory: Memory) -> list[tuple[datetime.date, str]]:
    """The versions of the short form by date; a lesson written before versions existed reads as one version dated
    `released`, or `created`."""
    found = [v for v in map(_version, memory.versions) if v]
    if found:
        return found
    on = memory.released or memory.created
    return [(on, memory.short)] if memory.short and on else []


def merged_versions(keep: Memory, drop: Memory, today: datetime.date) -> list[str]:
    """The versions of a merged lesson: both records' versions (implicit ones included), one per day with the kept
    record's text winning, and the kept record's short form last, because that is the text that loads."""
    by_day: dict[datetime.date, str] = {}
    for on, text in [*version_list(keep), *version_list(drop)]:
        by_day.setdefault(on, text)  # keep's entries come first, so they win
    result = sorted(by_day.items())
    if keep.short and (not result or result[-1][1] != keep.short):
        result = [v for v in result if v[0] != today] + [(today, keep.short)]
    return [version_entry(on, text) for on, text in result]


def merged_log(keep: Memory, drop: Memory) -> list[str]:
    """The log of a merged lesson by date: one entry per (session, outcome), the earlier day kept, and a `seen` entry
    only for a session with no other entry. An entry that is not a case is kept once, as it is."""
    entries = list(dict.fromkeys([*keep.log, *drop.log]))
    earliest: dict[tuple[str, str], tuple[datetime.date, str]] = {}
    for e in entries:
        c = case(e)
        if c is not None:
            held = earliest.get((c.session, c.outcome))
            if held is None or c.on < held[0]:
                earliest[c.session, c.outcome] = (c.on, e)
    best = {key: e for key, (_, e) in earliest.items()}
    cased = {session for session, outcome in best if outcome != "seen"}
    chosen = {
        e for (session, outcome), e in best.items() if outcome != "seen" or session not in cased
    }
    result = [e for e in entries if case(e) is None or e in chosen]
    result.sort(key=lambda e: e[:10])
    return result


class Tally(NamedTuple):
    number: int
    since: datetime.date
    text: str
    worked: int
    failed: int

    @property
    def balance(self) -> int:
        return self.worked - self.failed


FAILED_TO_LIST = 2


def tallies(memory: Memory) -> list[Tally]:
    """One tally per version; a case counts for the last version dated earlier than the case."""
    versions = version_list(memory)
    counts = [[0, 0] for _ in versions]
    for c in cases(memory):
        if c.outcome == "seen":
            continue
        owners = [i for i, (on, _) in enumerate(versions) if on < c.on]
        if owners:
            counts[owners[-1]][c.outcome == "failed"] += 1
    return [
        Tally(i + 1, on, text, w, f)
        for i, ((on, text), (w, f)) in enumerate(zip(versions, counts, strict=False))
    ]


def reword_note(memory: Memory) -> str:
    """What the automatic rewording did to this lesson, for the owner's queue; "" when it did nothing that still applies."""
    versions = version_list(memory)
    last = versions[-1][0] if versions else None
    if memory.reworded is not None:
        if memory.reworded == last:
            return f"the automatic rewording of {memory.reworded.isoformat()} got worse too"
        return f"an automatic rewording was made on {memory.reworded.isoformat()}; this wording is the owner's"
    if memory.reword_failed is not None and memory.reword_failed == last:
        return "an automatic rewording could not be written"
    return ""


def got_worse(memory: Memory) -> bool:
    """The current version failed at least FAILED_TO_LIST times since `reviewed`, and failed more than it worked or
    stands below the version before it."""
    found = tallies(memory)
    if not found:
        return False
    cur, prev = found[-1], found[-2] if len(found) > 1 else None
    since = memory.reviewed
    recent = sum(
        1
        for c in cases(memory)
        if c.outcome == "failed" and (since is None or c.on > since) and c.on > cur.since
    )
    return recent >= FAILED_TO_LIST and (
        cur.failed > cur.worked or (prev is not None and cur.balance < prev.balance)
    )


def mark_words(memory: Memory) -> str:
    found = tallies(memory)
    if not found or not found[-1].failed:
        return ""
    cur = found[-1]
    return f"version {cur.number}: worked {cur.worked}, failed {cur.failed}"


def has_case(memory: Memory, key: str, outcome: str) -> bool:
    """True when a case of session `key` with `outcome` adds nothing: the session has an entry with that outcome,
    or the outcome is `seen` and the session has any entry."""
    mine = [c.outcome for c in cases(memory) if c.session == key]
    return outcome in mine or (outcome == "seen" and bool(mine))
