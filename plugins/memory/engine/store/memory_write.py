"""Writing a memory: rendering the file, new memories, field updates, cases and sightings."""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import TYPE_CHECKING, Required, TypedDict, Unpack

import yaml
from core import safe_io

from store.memory_model import (
    KINDS,
    ORIGINS,
    OUTCOMES,
    REACHES,
    SHORT_LIMIT,
    TOPIC_LIMIT,
    WEIGHTS,
    Memory,
    slug_of,
    valid_short,
    valid_topic,
)
from store.memory_parse import _parse, _split
from store.sightings import (
    case_entry,
    counted,
    has_case,
    normalized_sources,
    session_key,
    sessions,
    sighting,
    sighting_entry,
    standing_changes,
    version_entry,
    version_list,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


# The frontmatter keys of a memory in file order; one is written when its value is set, `observed` and `status` always.
_RENDER_ORDER = (
    "created",
    "observed",
    "status",
    "context",
    "valid_until",
    "sources",
    "origin",
    "reach",
    "weight",
    "owner_confirmed",
    "triage",
    "triage_reason",
    "released",
    "general",
    "short",
    "short_by",
    "topic",
    "load",
    "log",
    "versions",
    "reviewed",
    "reworded",
    "reword_failed",
)
_RENDER_ALWAYS = ("observed", "status")


def _frontmatter_value(value: object) -> object:
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, list):
        return list(value)
    return value


def _render(m: Memory, extra: Mapping[str, str] | None = None) -> str:
    meta: dict = {"kind": m.kind, "claim": m.claim}
    for key in _RENDER_ORDER:
        value = getattr(m, key)
        if value or key in _RENDER_ALWAYS:
            meta[key] = _frontmatter_value(value)
    meta.update(extra or {})
    head = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6
    )
    return f"---\n{head}---\n{m.body}"


class WriteOptions(TypedDict, total=False):
    """The keyword options of `write_memory`; an omitted one is None, except `sources` (empty)."""

    kind: Required[str]
    claim: Required[str]
    body: Required[str]
    today: Required[datetime.date]
    context: str | None
    valid_until: datetime.date | None
    sources: Sequence[str]
    origin: str | None
    reach: str | None
    weight: str | None
    short: str | None
    topic: str | None
    short_by: str | None
    outcome: str | None
    on: datetime.date | None


def _check_choice(label: str, value: str | None, allowed: Sequence[str]) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"unknown {label} {value!r}")


def _check_write(options: WriteOptions) -> None:
    """The first invalid option of a `write_memory` call raises ValueError."""
    kind, sources = options["kind"], options.get("sources", ())
    _check_choice("outcome", options.get("outcome"), OUTCOMES)
    short, topic = options.get("short"), options.get("topic")
    if short is not None and not valid_short(short):
        raise ValueError(f"the short form must be one line of at most {SHORT_LIMIT} characters")
    if topic is not None and not valid_topic(topic):
        raise ValueError(
            f"the topic must be one or two lowercase words of at most {TOPIC_LIMIT} characters"
        )
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    _check_choice("origin", options.get("origin"), ORIGINS)
    _check_choice("reach", options.get("reach"), REACHES)
    _check_choice("weight", options.get("weight"), WEIGHTS)
    if not options["claim"].strip():
        raise ValueError("claim is empty")
    if kind in {"finding", "document"} and not sources:
        raise ValueError(f"a {kind} needs at least one source")


_DEFAULT_DAYS = {"finding": 90, "state": 30}  # how long a kind lasts when the caller names no end


def _standing_fields(
    template: Memory, today: datetime.date, valid_until: datetime.date | None
) -> tuple[datetime.date | None, datetime.date | None, str | None]:
    """(valid_until, released, triage) of a new memory: a transcript memory's standing decides them, before the
    per-kind defaults."""
    if template.origin == "transcript":
        changes = standing_changes(None, template, today)
        return (
            changes["valid_until"] if valid_until is None else valid_until,
            changes.get("released"),
            changes.get("triage"),
        )
    days = _DEFAULT_DAYS.get(template.kind)
    if valid_until is None and days is not None:
        valid_until = today + datetime.timedelta(days=days)
    return valid_until, None, None


def _write_new(folder: Path, template: Memory) -> Memory:
    """Write the memory to a new file named after its claim, -2, -3 ... when the name is taken."""
    base = slug_of(template.claim)
    handle, n = base, 1
    while True:
        m = replace(template, handle=handle, path=folder / f"{handle}.md")
        try:
            with m.path.open("x", encoding="utf-8") as f:  # exclusive: never overwrite
                f.write(_render(m))
            return m
        except FileExistsError:
            n += 1
            handle = f"{base}-{n}"


def write_memory(folder: Path, scope: str, **options: Unpack[WriteOptions]) -> Memory:
    _check_write(options)
    kind, today, short = options["kind"], options["today"], options.get("short")
    claim, body = options["claim"].strip(), options["body"]
    sources = normalized_sources(options.get("sources", ()))
    origin, weight = options.get("origin"), options.get("weight")
    draft = Memory(
        scope,
        folder,
        "",
        kind,
        claim,
        today,
        1,
        "active",
        None,
        None,
        sources,
        "",
        None,
        origin=origin,
        weight=weight,
    )
    valid_until, released, triage = _standing_fields(draft, today, options.get("valid_until"))
    if scope == "project":
        safe_io.refuse_symlink_chain(folder, folder)
    folder.mkdir(parents=True, exist_ok=True)
    outcome = options.get("outcome")
    log = (
        [
            case_entry(options.get("on") or today, key, outcome)
            for key in dict.fromkeys(filter(None, map(session_key, sources)))
        ]
        if outcome
        else []
    )
    template = Memory(
        scope,
        folder,
        "",
        kind,
        claim,
        today,
        1,
        "active",
        options.get("context"),
        valid_until,
        list(sources),
        body if body.endswith("\n") or not body else body + "\n",
        None,
        origin=origin,
        reach=options.get("reach"),
        weight=weight,
        triage=triage,
        released=released,
        short=short,
        short_by=options.get("short_by") if short else None,
        topic=options.get("topic"),
        log=log,
        versions=[version_entry(today, short)] if short else [],
    )
    return _write_new(folder, template)


def update(memory: Memory, today: datetime.date, **changes) -> Memory:
    """Rewrite the memory's file with the given frontmatter keys changed or added; a value of None removes the key.

    The reserved name `body` replaces the body instead. Keys this module does not know and the rest of the body
    survive; the file is replaced through a temporary one. `today` is the date of the action: callers put it into
    the keys they change, as dates are written as ISO strings. Returns the memory read back from the file."""
    meta, body = _split(memory.path.read_text(encoding="utf-8"))
    body = changes.pop("body", body)
    new_short = changes.get("short")
    if new_short is not None:
        current = _parse(memory.path, memory.scope)
        if new_short != current.short:
            kept = [(on, text) for on, text in version_list(current) if on != today]
            meta["versions"] = [
                version_entry(on, text)
                for on, text in sorted([*kept, (today, new_short)], key=lambda v: v[0])
            ]
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value.isoformat() if isinstance(value, datetime.date) else value
    head = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6
    )
    safe_io.replace_file(memory.path, f"---\n{head}---\n{body}".encode())
    return _parse(memory.path, memory.scope)


def observe(memory: Memory, today: datetime.date) -> Memory:
    return update(memory, today, observed=memory.observed + 1, last_observed=today)


def _log_with(memory: Memory, key: str, on: datetime.date, outcome: str) -> list[str] | None:
    """The log after adding the case of session `key`, or None when it adds nothing (see `has_case`)."""
    if has_case(memory, key, outcome):
        return None
    return [*memory.log, case_entry(on, key, outcome)]


def add_case(
    memory: Memory, session: str, on: datetime.date, outcome: str, today: datetime.date
) -> tuple[Memory, bool]:
    """Add the case of `session` (any spelling of a session source) to the log; False and no write when it adds
    nothing. Not a session or an unknown outcome: ValueError."""
    key = session_key(session)
    if key is None:
        raise ValueError(f"{session!r} is not a session source: write it as 'session <id>'")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    log = _log_with(memory, key, on, outcome)
    if log is None:
        return memory, False
    return update(memory, today, log=log), True


class SightingOptions(TypedDict, total=False):
    """The keyword options of `add_sighting`."""

    outcome: str  # "seen"
    on: datetime.date | None  # None: today


def _checked_sighting(session: str, outcome: str) -> tuple[str, str | None]:
    """(key, project) of the session entry; ValueError when it is no session source or the outcome is unknown."""
    found = sighting(session)
    if found is None:
        raise ValueError(f"{session!r} is not a session source: write it as 'session <id>'")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    return found


def _noted_body(memory: Memory, note: str | None) -> dict:
    """The `body` change that appends `note`, empty without a note."""
    if not (note and note.strip()):
        return {}
    head = memory.body if memory.body.endswith("\n") or not memory.body else memory.body + "\n"
    return {"body": f"{head}{' '.join(note.split())}\n"}


def add_sighting(
    memory: Memory,
    session: str,
    today: datetime.date,
    note: str | None = None,
    **options: Unpack[SightingOptions],
) -> tuple[Memory, bool]:
    """Record that another session shows the memory: `session` is a full source entry ("session <id>", with
    " project <key>" when known).

    Not a session entry: ValueError. Already counted (under any spelling, with its project when given): the memory
    unchanged and False, with no write. A session counted without a project that now comes with one gains the
    project (True, `observed` unchanged). Else the normalized entry is added, `observed` raised as `observe`
    does and the note appended to the body; a transcript memory also gets `standing_changes`.

    The case (`outcome`, dated `on` or today) goes to the log in the same write, unless the log already holds it;
    a counted session whose case is new still writes, and the flag stays False."""
    outcome = options.get("outcome", "seen")
    key, project = _checked_sighting(session, outcome)
    log = _log_with(memory, key, options.get("on") or today, outcome)
    changes: dict = {} if log is None else {"log": log}
    if key in sessions(memory):
        if counted(memory, session):
            return (memory, False) if log is None else (update(memory, today, **changes), False)
        sources = normalized_sources([
            sighting_entry(key, project) if (f := sighting(s)) and f[0] == key else s
            for s in memory.sources
        ])
    else:
        sources = [*memory.sources, sighting_entry(key, project)]
        changes.update({"observed": memory.observed + 1, "last_observed": today})
        changes.update(_noted_body(memory, note))
    changes["sources"] = sources
    if memory.origin == "transcript":
        changes.update(standing_changes(memory, replace(memory, sources=sources), today))
    return update(memory, today, **changes), True
