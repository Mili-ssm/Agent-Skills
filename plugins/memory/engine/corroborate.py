"""`corroborate`: what the background corroboration pass reads and what it does with the groups a model returns.

Pure: no model call, no file write, no subprocess. The command builds on it; this module only decides."""
from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import records

MAX_LESSONS = 150
MAX_GROUPS = 30
LAPSED_DAYS = 60  # an unconfirmed lesson stays readable this long after its valid_until


def counted_projects(registry: Mapping[str, Mapping[str, str]]) -> list[Path]:
    """Registered paths that exist, hold a memory folder and are not under a temporary folder; sorted."""
    found = set()
    for entry in registry.values():
        raw = entry.get("path") if isinstance(entry, Mapping) else None
        if not isinstance(raw, str) or not raw:
            continue
        path = Path(raw)
        if path.is_dir() and records.project_dir(path).is_dir() and not records.under_temp(path):
            found.add(path)
    return sorted(found)


@dataclass(frozen=True)
class Lesson:
    id: str  # "g:<handle>" or "p<n>:<handle>": no project name reaches the model
    scope: str  # "project" or "global"
    project: Path | None
    memory: records.Memory


def _readable(m: records.Memory, today: datetime.date) -> bool:
    if m.error is not None or m.status != "active" or m.origin != "transcript":
        return False
    if records.is_live(m, today):
        return True
    return (m.valid_until is not None and records.standing(m) == "unconfirmed"
            and 0 < (today - m.valid_until).days <= LAPSED_DAYS)


def _newest_first(lessons: list[Lesson]) -> list[Lesson]:
    lessons.sort(key=lambda x: x.memory.handle)
    lessons.sort(key=lambda x: x.memory.created or datetime.date.min, reverse=True)
    return lessons


def collect(projects: Sequence[Path], global_folder: Path | None, today: datetime.date) -> list[Lesson]:
    """Active transcript lessons, live or unconfirmed and lapsed for at most LAPSED_DAYS; a project record with
    `promote: no` or already linked to a global record is left out. Newest first, cut at MAX_LESSONS."""
    out: list[Lesson] = []
    for n, project in enumerate(projects, start=1):
        for m in records.load_memories(records.project_dir(project), "project"):
            if _readable(m, today) and m.promote != "no" and not m.general:
                out.append(Lesson(f"p{n}:{m.handle}", "project", project, m))
    for m in records.load_memories(global_folder, "global"):
        if _readable(m, today):
            out.append(Lesson(f"g:{m.handle}", "global", None, m))
    return _newest_first(out)[:MAX_LESSONS]


def lesson_fingerprint(lesson: Lesson) -> str:
    return hashlib.sha1("\n".join([lesson.id, *sorted(lesson.memory.sources)]).encode("utf-8")).hexdigest()


def fingerprint(lessons: Sequence[Lesson]) -> str:
    """Changes when a lesson appears, goes or gains a source; not with the order of the lessons."""
    text = "\n".join(sorted(f"{x.id} {lesson_fingerprint(x)}" for x in lessons))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _reach(lesson: Lesson) -> str:
    return "general" if lesson.scope == "global" else (lesson.memory.reach or "project")


def _line(text: str | None) -> str:
    return " ".join((text or "").split())


def lesson_lines(lessons: Sequence[Lesson]) -> list[str]:
    """`<id>\\t<reach, or "general" for a global record>\\t<claim>\\t<context>`, one line each."""
    return [f"{x.id}\t{_reach(x)}\t{_line(x.memory.claim)}\t{_line(x.memory.context)}" for x in lessons]


@dataclass(frozen=True)
class Group:
    ids: list[str]
    claim: str
    context: str


def validate_groups(raw: object, lessons: Sequence[Lesson]) -> tuple[list[Group], list[str]]:
    """The groups that hold and, for each one dropped, a reason. Dropped: not an object of the shape
    {"ids": [str], "claim": str, "context": str (optional)}, an unknown id, an id of an earlier group, an empty
    claim, or one member that is global or of reach `project`. At most MAX_GROUPS are kept."""
    if not isinstance(raw, list):
        return [], ["the answer is not a list of groups"]
    by_id = {x.id: x for x in lessons}
    kept: list[Group] = []
    reasons: list[str] = []
    used: set[str] = set()
    for i, item in enumerate(raw, start=1):
        why = None
        ids = item.get("ids") if isinstance(item, dict) else None
        claim = item.get("claim") if isinstance(item, dict) else None
        context = item.get("context", "") if isinstance(item, dict) else None
        if not isinstance(item, dict) or not isinstance(ids, list) or not ids \
                or not all(isinstance(x, str) for x in ids) or not isinstance(claim, str) \
                or not (context is None or isinstance(context, str)):
            why = "not an object with ids, claim and context"
        else:
            ids = list(dict.fromkeys(ids))
            unknown = [x for x in ids if x not in by_id]
            if unknown:
                why = f"unknown id {unknown[0]}"
            elif any(x in used for x in ids):
                why = "shares an id with an earlier group"
            elif not _line(claim):
                why = "empty claim"
            elif len(ids) == 1 and (by_id[ids[0]].scope == "global" or _reach(by_id[ids[0]]) != "general"):
                why = "one member that is global or of reach project"
            elif len(kept) >= MAX_GROUPS:
                why = f"more than {MAX_GROUPS} groups"
        if why:
            reasons.append(f"group {i}: {why}")
            continue
        used.update(ids)
        kept.append(Group(ids, _line(claim), _line(context)))
    return kept, reasons


@dataclass(frozen=True)
class Action:
    """What the pass does for one group; `kind` decides which fields are used.

    merge: `keep`, `drop` (lesson ids, one project), `project`.
    merge_global: `keep`, `drop` (lesson ids of two global records).
    write_global: `claim`, `context`, `record_kind`, `weight`, `entries` (sighting entries, each with the key
        of its project), `members` (ids of the project records that stand for it, after merges).
    sighting: `target` (a global handle; None when the target is this group's write_global), `entry`.
    link: `member` (lesson id), `project`, `target` (as for sighting)."""
    kind: str
    keep: str | None = None
    drop: str | None = None
    project: Path | None = None
    claim: str | None = None
    context: str | None = None
    record_kind: str | None = None
    weight: str | None = None
    entries: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    target: str | None = None
    entry: str | None = None
    member: str | None = None


def _oldest(lessons: Sequence[Lesson]) -> Lesson:
    return min(lessons, key=lambda x: (x.memory.created or datetime.date.max, x.memory.handle))


def actions(group: Group, lessons: Mapping[str, Lesson], global_records: Sequence[records.Memory]) -> list[Action]:
    """The steps for one group, in order: merges inside a project, a merge of global members, then for the
    members of reach `general` left: a write_global unless a global record is the target, one sighting per entry
    the target lacks, one link per project member. A merged record stands for the ones dropped into it: its
    sessions are their union, and it is general when any of them is. Members of reach `project` from different
    projects produce no action."""
    members = [lessons[i] for i in group.ids]
    out: list[Action] = []
    stands: dict[str, list[Lesson]] = {}  # kept project lesson id -> the lessons it stands for
    by_project: dict[Path, list[Lesson]] = {}
    for x in members:
        if x.scope == "project" and x.project is not None:
            by_project.setdefault(x.project, []).append(x)
    for project in sorted(by_project):
        same = by_project[project]
        keep = _oldest(same) if len(same) > 1 else same[0]
        stands[keep.id] = list(same)
        for other in sorted((x for x in same if x is not keep), key=lambda x: x.id):
            out.append(Action("merge", keep=keep.id, drop=other.id, project=project))
    globals_ = [x for x in members if x.scope == "global"]
    gkeep = _oldest(globals_) if globals_ else None
    for other in sorted((x for x in globals_ if x is not gkeep), key=lambda x: x.id):
        out.append(Action("merge_global", keep=gkeep.id, drop=other.id))

    general = sorted((lessons[k] for k, group_of in stands.items() if any(_reach(y) == "general" for y in group_of)),
                     key=lambda x: x.id)
    if not general:
        return out
    entries_of: dict[str, list[str]] = {}
    for x in general:
        key = records.project_key(x.project)
        sess = list(dict.fromkeys(s for y in stands[x.id] for s in records.sessions(y.memory)))
        entries_of[x.id] = [records.sighting_entry(s, key) for s in sess]
    entries = list(dict.fromkeys(e for x in general for e in entries_of[x.id]))

    target: records.Memory | None = gkeep.memory if gkeep else None
    if target is None:
        held = {s for x in general for y in stands[x.id] for s in records.sessions(y.memory)}
        holders = [g for g in global_records
                   if g.origin == "transcript" and g.status == "active" and g.error is None
                   and held & set(records.sessions(g))]
        if holders:
            target = min(holders, key=lambda g: (g.created or datetime.date.max, g.handle))
    if target is None:
        origin = _oldest([y for x in general for y in stands[x.id]])
        weights = [y.memory.weight or "medium" for x in general for y in stands[x.id]]
        out.append(Action("write_global", claim=group.claim, context=group.context or None,
                          record_kind=origin.memory.kind, weight=max(weights, key=records.WEIGHTS.index),
                          entries=entries, members=[x.id for x in general]))
        handle = None
    else:
        handle = target.handle
        for e in entries:
            if not records.counted(target, e):
                out.append(Action("sighting", target=handle, entry=e))
    for x in general:
        out.append(Action("link", member=x.id, project=x.project, target=handle))
    return out
