"""Reminders: one Markdown file with YAML front matter per reminder, in `<memory folder>/reminders/`.

A reminder is not a memory: it has its own record and folder, so no memory code (search, curation, capture) loads it.
Counts of sessions arrive as plain integers; `until` is only the end date, putting a reminder off sets `after` or `in_sessions`.
"""
from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from records import _date, _split, log_before, slug_of

FOLDER = "reminders"
TOPIC_LIMIT = 40
LIVE_LIMIT = 10
LEVELS = ("low", "medium", "high")
STATUSES = ("active", "done", "closed")
MAX_SESSIONS = 999

_KNOWN = ("topic", "created", "status", "armed_count", "after", "in_sessions", "until", "every", "effort", "risk",
          "done_note", "closed_reason", "ended", "shown_at_end", "shown_before", "times_done")


@dataclass
class Reminder:
    scope: str
    path: Path
    handle: str
    topic: str
    body: str
    created: datetime.date | None = None
    status: str = "active"
    armed_count: int = 0
    after: datetime.date | None = None
    in_sessions: int | None = None
    until: datetime.date | None = None
    every: str | None = None
    effort: str = "medium"
    risk: str = "medium"
    done_note: str | None = None
    closed_reason: str | None = None
    ended: datetime.date | None = None
    shown_at_end: int | None = None
    shown_before: list[int] = field(default_factory=list)
    times_done: int = 0
    error: str | None = None
    extra: dict = field(default_factory=dict)  # unknown front matter keys, kept on rewrite


def folder_of(memory_folder: Path) -> Path:
    return memory_folder / FOLDER


def parse_every(text: str) -> tuple[int, str]:
    m = re.fullmatch(r"([0-9]{1,3})([ds])", text.strip() if isinstance(text, str) else "")
    if not m or not 1 <= int(m.group(1)) <= MAX_SESSIONS:
        raise ValueError(f"repetition must be <N>d or <N>s with N from 1 to {MAX_SESSIONS}")
    return int(m.group(1)), m.group(2)


def _int(value, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return value


def _opt_int(value, name: str, minimum: int = 0) -> int | None:
    return None if value is None else _int(value, name, minimum)


def _opt_str(value, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _parse(path: Path, scope: str) -> Reminder:
    base = Reminder(scope, path, path.stem, "", "")
    try:
        meta, body = _split(path.read_text(encoding="utf-8"))
        topic = meta.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic is missing")
        status = meta.get("status", "active")
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        effort, risk = meta.get("effort", "medium"), meta.get("risk", "medium")
        if effort not in LEVELS:
            raise ValueError(f"unknown effort {effort!r}")
        if risk not in LEVELS:
            raise ValueError(f"unknown risk {risk!r}")
        every = _opt_str(meta.get("every"), "every")
        if every is not None:
            parse_every(every)
        shown_before = meta.get("shown_before") or []
        if not isinstance(shown_before, list):
            raise ValueError("shown_before must be a list of integers")
        return replace(
            base, topic=topic.strip(), body=body, created=_date(meta.get("created"), "created"), status=status,
            armed_count=_int(meta.get("armed_count", 0), "armed_count"), after=_date(meta.get("after"), "after"),
            in_sessions=_opt_int(meta.get("in_sessions"), "in_sessions", 1), until=_date(meta.get("until"), "until"),
            every=every, effort=effort, risk=risk, done_note=_opt_str(meta.get("done_note"), "done_note"),
            closed_reason=_opt_str(meta.get("closed_reason"), "closed_reason"), ended=_date(meta.get("ended"), "ended"),
            shown_at_end=_opt_int(meta.get("shown_at_end"), "shown_at_end"),
            shown_before=[_int(n, "shown_before") for n in shown_before],
            times_done=_int(meta.get("times_done", 0), "times_done"),
            extra={k: v for k, v in meta.items() if k not in _KNOWN})
    except Exception as e:  # one broken file must not break the rest
        return replace(base, error=f"{type(e).__name__}: {e}".splitlines()[0])


def load(memory_folder: Path | None, scope: str) -> list[Reminder]:
    try:
        if memory_folder is None:
            return []
        folder = folder_of(memory_folder)
        if not folder.is_dir():
            return []
        return [_parse(p, scope) for p in sorted(folder.glob("*.md"), key=lambda p: p.stem) if p.is_file()]
    except OSError:
        return []


def _render(r: Reminder) -> str:
    meta: dict = {"topic": r.topic}
    if r.created:
        meta["created"] = r.created.isoformat()
    meta["status"] = r.status
    meta["armed_count"] = r.armed_count
    for name in ("after", "until", "ended"):
        value = getattr(r, name)
        if value:
            meta[name] = value.isoformat()
    if r.in_sessions is not None:
        meta["in_sessions"] = r.in_sessions
    if r.every:
        meta["every"] = r.every
    meta["effort"], meta["risk"] = r.effort, r.risk
    for name in ("done_note", "closed_reason", "shown_at_end"):
        value = getattr(r, name)
        if value is not None:
            meta[name] = value
    if r.shown_before:
        meta["shown_before"] = list(r.shown_before)
    meta["times_done"] = r.times_done
    meta.update({k: v for k, v in r.extra.items() if k not in meta})
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6)
    return f"---\n{head}---\n{r.body}"


def _save(r: Reminder) -> None:
    tmp = r.path.with_name(f".{r.path.name}.tmp")
    tmp.write_text(_render(r), encoding="utf-8")
    os.replace(tmp, r.path)


def _check_levels(effort: str, risk: str) -> None:
    if effort not in LEVELS:
        raise ValueError(f"effort must be one of {', '.join(LEVELS)}")
    if risk not in LEVELS:
        raise ValueError(f"risk must be one of {', '.join(LEVELS)}")


def _check_sessions(n: int) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_SESSIONS:
        raise ValueError(f"sessions must be from 1 to {MAX_SESSIONS}")


def write(memory_folder: Path, scope: str, *, topic: str, body: str, today: datetime.date, count: int,
          after: datetime.date | None = None, in_sessions: int | None = None, until: datetime.date | None = None,
          every: str | None = None, effort: str = "medium", risk: str = "medium") -> Reminder:
    topic, body = topic.strip(), body.strip()
    if not topic:
        raise ValueError("topic is empty")
    if len(topic) > TOPIC_LIMIT:
        raise ValueError(f"topic is longer than {TOPIC_LIMIT} characters")
    if not body:
        raise ValueError("body is empty")
    _check_levels(effort, risk)
    if every is not None:
        parse_every(every)
    if in_sessions is not None:
        _check_sessions(in_sessions)
    if until is not None and until < today:
        raise ValueError("until is before today")
    if after is not None and until is not None and after > until:
        raise ValueError("after is later than until")
    folder = folder_of(memory_folder)
    folder.mkdir(parents=True, exist_ok=True)
    base = slug_of(topic)
    handle, n = base, 1
    while True:
        path = folder / f"{handle}.md"
        r = Reminder(scope, path, handle, topic, body + "\n", today, "active", count, after, in_sessions, until, every,
                     effort, risk)
        try:
            with path.open("x", encoding="utf-8") as f:  # exclusive: never overwrite
                f.write(_render(r))
            return r
        except FileExistsError:
            n += 1
            handle = f"{base}-{n}"


def is_live(r: Reminder, today: datetime.date) -> bool:
    return r.error is None and r.status == "active" and (r.until is None or not r.until < today)


def sessions_since(r: Reminder, count: int) -> int:
    return count - r.armed_count if count >= r.armed_count else count


def is_due(r: Reminder, today: datetime.date, count: int) -> bool:
    return (is_live(r, today) and (r.after is None or not r.after > today)
            and (r.in_sessions is None or sessions_since(r, count) >= r.in_sessions))


def _shown(r: Reminder, shown: int | None) -> list[int]:
    return r.shown_before if shown is None else [*r.shown_before, shown]


def _change(r: Reminder, action: str, **changes) -> Reminder:
    log_before(r, action)
    new = replace(r, **changes)
    _save(new)
    return new


def done(r: Reminder, today: datetime.date, count: int, note: str, shown: int | None) -> Reminder:
    if r.every is None:
        return _change(r, "done", status="done", ended=today, done_note=note, shown_at_end=shown)
    n, unit = parse_every(r.every)
    when = (dict(after=today + datetime.timedelta(days=n), in_sessions=None) if unit == "d"
            else dict(in_sessions=n, after=None))
    return _change(r, "done", times_done=r.times_done + 1, armed_count=count, shown_before=_shown(r, shown), **when)


def close(r: Reminder, today: datetime.date, reason: str, shown: int | None) -> Reminder:
    return _change(r, "close", status="closed", ended=today, closed_reason=reason, shown_at_end=shown)


def snooze(r: Reminder, today: datetime.date, count: int, shown: int | None, *, sessions: int | None = None,
           after: datetime.date | None = None) -> Reminder:
    if (sessions is None) == (after is None):
        raise ValueError("snooze takes exactly one of sessions or after")
    if sessions is not None:
        _check_sessions(sessions)
        when = dict(in_sessions=sessions, after=None)
    else:
        if r.until is not None and after > r.until:
            raise ValueError("after is later than until")
        when = dict(after=after, in_sessions=None)
    return _change(r, "snooze", armed_count=count, shown_before=_shown(r, shown), **when)
