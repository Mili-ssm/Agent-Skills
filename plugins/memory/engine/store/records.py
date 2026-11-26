"""Memory records: one Markdown file with YAML frontmatter per memory.

Imports nothing from mem.py (mem.py imports this module), so similarity and match_memories take tokens or a tokenizer.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Required, TypedDict, Unpack

import yaml
from core import safe_io

from store.journal import (
    CURATION_LOG,
    Logged,
    last_log_entry,
    log_before,
    restore,
)
from store.locations import (
    REGISTRY_FILE,
    _main_worktree,
    default_store,
    ensure_excluded,
    forget_project,
    global_memories_root,
    mark_repository,
    memories_root,
    project_dir,
    project_key,
    project_root,
    read_registry,
    register_project,
    tracked_memories,
    under_temp,
)
from store.matching import (
    MIN_TERMS,
    POSSIBLE,
    STOPWORDS,
    STRONG,
    MatchOptions,
    Related,
    containment,
    match_memories,
    related_records,
    tokenize,
)
from store.memory_model import (
    GLOBAL_DIR,
    GLOBAL_MIN_PROJECTS,
    KINDS,
    ORIGINS,
    OUTCOMES,
    PROJECT_DIR,
    PROJECT_KEY_LEN,
    REACHES,
    SESSION_PREFIX,
    SHORT_DATE_LEN,
    SHORT_LIMIT,
    SIGHTINGS_NEEDED,
    STATUSES,
    STORE_MARKER,
    TOPIC_LIMIT,
    TRIAGE_REASON_LIMIT,
    TRIAGES,
    UNCONFIRMED_DAYS,
    WEIGHTS,
    FieldTypeError,
    Memory,
    is_live,
    slug_of,
    valid_short,
    valid_topic,
    valid_triage_reason,
)
from store.notes import safe_load
from store.pairing import (
    OPPOSITES,
    Budget,
    differing_words,
    flagged_words,
    pairs,
    refuted_pairs,
    similarity,
)
from store.sightings import (
    FAILED_TO_LIST,
    MAX_SESSION_ID,
    Case,
    Tally,
    _version,
    case,
    case_entry,
    cases,
    counted,
    got_worse,
    has_case,
    mark_words,
    merged_log,
    merged_versions,
    normalized_sources,
    projects,
    quarantined,
    reword_note,
    session_key,
    sessions,
    sighting,
    sighting_entry,
    standing,
    standing_changes,
    tallies,
    version_entry,
    version_list,
)
from store.terms import (
    SECRET_PATTERNS,
    TERM_KINDS,
    TERMS_HEADER,
    ForbiddenListError,
    Term,
    ensure_terms_file,
    forbidden_file,
    forbidden_line,
    inside,
    parse_term,
    read_terms,
    secret_in,
    store_is_writable,
    term_hits,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "CURATION_LOG",
    "FAILED_TO_LIST",
    "GLOBAL_DIR",
    "GLOBAL_MIN_PROJECTS",
    "KINDS",
    "MAX_SESSION_ID",
    "MIN_TERMS",
    "OPPOSITES",
    "ORIGINS",
    "OUTCOMES",
    "POSSIBLE",
    "PROJECT_DIR",
    "PROJECT_KEY_LEN",
    "REACHES",
    "REGISTRY_FILE",
    "SECRET_PATTERNS",
    "SESSION_PREFIX",
    "SHORT_DATE_LEN",
    "SHORT_LIMIT",
    "SIGHTINGS_NEEDED",
    "STATUSES",
    "STOPWORDS",
    "STORE_MARKER",
    "STRONG",
    "TERMS_HEADER",
    "TERM_KINDS",
    "TOPIC_LIMIT",
    "TRIAGES",
    "TRIAGE_REASON_LIMIT",
    "UNCONFIRMED_DAYS",
    "WEIGHTS",
    "Budget",
    "Case",
    "FieldTypeError",
    "ForbiddenListError",
    "Logged",
    "MatchOptions",
    "Memory",
    "Path",
    "Related",
    "SightingOptions",
    "Tally",
    "Term",
    "WriteOptions",
    "_main_worktree",
    "_parse",
    "add_case",
    "add_sighting",
    "case",
    "case_entry",
    "cases",
    "containment",
    "counted",
    "datetime",
    "default_store",
    "differing_words",
    "ensure_excluded",
    "ensure_terms_file",
    "flagged_words",
    "forbidden_file",
    "forbidden_line",
    "forget_project",
    "global_memories_root",
    "got_worse",
    "has_case",
    "inside",
    "is_live",
    "last_log_entry",
    "load_memories",
    "log_before",
    "logger",
    "mark_repository",
    "mark_words",
    "match_memories",
    "memories_root",
    "merged_log",
    "merged_versions",
    "normalized_sources",
    "observe",
    "pairs",
    "parse_term",
    "project_dir",
    "project_key",
    "project_root",
    "projects",
    "quarantined",
    "read_registry",
    "read_terms",
    "refuted_pairs",
    "register_project",
    "related_records",
    "replace",
    "restore",
    "reword_note",
    "safe_load",
    "secret_in",
    "session_key",
    "sessions",
    "sighting",
    "sighting_entry",
    "similarity",
    "slug_of",
    "standing",
    "standing_changes",
    "store_is_writable",
    "tallies",
    "term_hits",
    "tokenize",
    "tracked_memories",
    "under_temp",
    "update",
    "valid_short",
    "valid_topic",
    "valid_triage_reason",
    "version_entry",
    "version_list",
    "write_memory",
]

logger = logging.getLogger(__name__)


def _date(value, name: str) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        raise FieldTypeError(f"{name} must be a date")
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.date.fromisoformat(value)
    raise FieldTypeError(f"{name} must be an ISO date")


def _split(text: str) -> tuple[dict, str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if not m:
        raise ValueError("no YAML frontmatter")
    meta = safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise FieldTypeError("frontmatter is not a mapping")
    return meta, text[m.end() :]


def _checked_kind(meta: dict) -> str:
    kind = meta.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    return kind


def _checked_claim(meta: dict) -> str:
    claim = meta.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim is missing")
    return claim


def _checked_observed(meta: dict) -> int:
    observed = meta.get("observed", 1)
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 1:
        raise ValueError("observed must be an integer of at least 1")
    return observed


def _checked_status(meta: dict) -> str:
    status = meta.get("status", "active")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return status


def _checked_context(meta: dict) -> str | None:
    context = meta.get("context")
    if context is not None and not isinstance(context, str):
        raise ValueError("context must be a string")
    return context


def _checked_sources(meta: dict) -> list[str]:
    sources = meta.get("sources") or []
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise ValueError("sources must be a list of strings")
    return list(sources)


def _required_fields(meta: dict) -> dict:
    """The fields a memory needs, each checked in this order; the first bad one raises ValueError."""
    return {
        "kind": _checked_kind(meta),
        "claim": _checked_claim(meta).strip(),
        "observed": _checked_observed(meta),
        "status": _checked_status(meta),
        "context": _checked_context(meta),
        "sources": _checked_sources(meta),
    }


# a bad value reads as absent: only curation reads these dates, and one must not hide the memory
_LENIENT_DATES = (
    "last_observed",
    "refuted",
    "reviewed",
    "reworded",
    "reword_failed",
    "owner_confirmed",
    "released",
)


def _lenient_date(meta: dict, key: str) -> datetime.date | None:
    try:
        return _date(meta.get(key), key)
    except ValueError:
        return None


_PROMOTE_NO = ("no", False)  # a tuple, not a set: a YAML list or mapping is unhashable


def _promote_of(meta: dict) -> str | None:
    value = meta.get("promote")  # YAML reads a bare no as False
    return "no" if value in _PROMOTE_NO else "done" if value == "done" else None


def _load_of(meta: dict) -> str | None:
    value = meta.get("load")  # YAML reads a bare no as False; 0 is not no
    return "index" if value == "index" else "no" if value == "no" or value is False else None


def _choice(meta: dict, key: str, allowed: Sequence[str]) -> str | None:
    value = meta.get(key)
    return value if value in allowed else None


def _text_fields(meta: dict) -> dict:
    """The optional text fields; a bad value reads as absent."""
    superseded_by = meta.get("superseded_by")
    general = meta.get("general")
    triage = _choice(meta, "triage", TRIAGES)
    reason = meta.get("triage_reason")
    return {
        "superseded_by": str(superseded_by) if superseded_by else None,
        "general": general if isinstance(general, str) and general.strip() else None,
        "short": meta.get("short") if valid_short(meta.get("short")) else None,
        "short_by": "model" if meta.get("short_by") == "model" else None,
        "triage": triage,
        "triage_reason": reason if triage == "pending" and valid_triage_reason(reason) else None,
        "topic": meta.get("topic") if valid_topic(meta.get("topic")) else None,
    }


def _list_fields(meta: dict) -> dict:
    """The optional list fields; a bad value reads as absent."""
    distinct = meta.get("distinct_from")
    raw_log = meta.get("log")
    raw_versions = meta.get("versions")
    return {
        "distinct_from": [str(h) for h in distinct] if isinstance(distinct, list) else [],
        "log": [e for e in raw_log if isinstance(e, str) and case(e)]
        if isinstance(raw_log, list)
        else [],
        "versions": sorted((e for e in raw_versions if _version(e)), key=lambda e: e[:10])
        if isinstance(raw_versions, list)
        else [],
    }


def _optional_fields(meta: dict) -> dict:
    return {
        **{key: _lenient_date(meta, key) for key in _LENIENT_DATES},
        **_text_fields(meta),
        **_list_fields(meta),
        "promote": _promote_of(meta),
        "load": _load_of(meta),
        "origin": _choice(meta, "origin", ORIGINS),
        "reach": _choice(meta, "reach", REACHES),
        "weight": _choice(meta, "weight", WEIGHTS),
    }


def _parse_text(base: Memory, text: str) -> Memory:
    meta, body = _split(text)
    required = _required_fields(meta)
    optional = _optional_fields(meta)
    return replace(
        base,
        **required,
        **optional,
        created=_date(meta.get("created"), "created"),
        valid_until=_date(meta.get("valid_until"), "valid_until"),
        body=body,
    )


def _parse(path: Path, scope: str) -> Memory:
    base = Memory(scope, path, path.stem, "lesson", "", None, 1, "active", None, None, [], "", None)
    try:
        return _parse_text(base, path.read_text(encoding="utf-8"))
    except Exception as e:  # one broken file must not break the rest
        logger.debug("cannot parse %s", path, exc_info=True)
        name = (
            "ValueError" if isinstance(e, FieldTypeError) else type(e).__name__
        )  # the error text predates the subclass
        return replace(base, error=f"{name}: {e}".splitlines()[0])


def load_memories(folder: Path | None, scope: str) -> list[Memory]:
    try:
        if folder is None or not folder.is_dir():
            return []
        if (
            scope == "project" and folder.is_symlink()
        ):  # a cloned repository's planted link; global folders may be synced links
            return []
        return [
            _parse(p, scope)
            for p in sorted(folder.glob("*.md"), key=lambda p: p.stem)
            if p.is_file() and not (scope == "project" and p.is_symlink())
        ]
    except OSError:
        return []


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
