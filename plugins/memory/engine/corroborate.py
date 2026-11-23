"""`corroborate`: what the background corroboration pass reads and what it does with the groups a model returns.

Pure: no model call, no file write, no subprocess. The command builds on it; this module only decides."""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import capture
import records
import rules
import shortcheck

MAX_LESSONS = 150
MAX_GROUPS = 30
FILL_CAP = 30  # lessons one `fill` session is asked about
FILL_ATTEMPTS = 2  # automatic fills that may fail to give a lesson a short form before it is left alone
FILL_FAILURES = 3
REWORD_CAP = 5  # lessons one automatic rewording session is asked about
REWORD_ATTEMPTS = 2  # refused proposals for one version before the step gives up on it
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


def _reach(lesson: Lesson) -> str:
    return "general" if lesson.scope == "global" else (lesson.memory.reach or "project")


def _encoded(lesson: Lesson) -> str:
    """JSON of what the model is shown plus the sources, so two different lessons never give the same text."""
    m = lesson.memory
    return json.dumps([lesson.id, _reach(lesson), m.claim, m.context, sorted(m.sources)], ensure_ascii=False)


def lesson_fingerprint(lesson: Lesson) -> str:
    return hashlib.sha1(_encoded(lesson).encode("utf-8", "replace")).hexdigest()


def fingerprint(lessons: Sequence[Lesson]) -> str:
    """Changes when a lesson appears, goes, gains a source or changes what the model is shown (reach, claim,
    context); not with the order of the lessons."""
    text = json.dumps(sorted(_encoded(x) for x in lessons), ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


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
    """`raw` is the model's whole answer, {"groups": [...]}; anything else keeps nothing and gives one reason.
    The groups that hold and, for each one dropped, a reason. Dropped: not an object of the shape
    {"ids": [str], "claim": str, "context": str (optional)}, an unknown id, an id repeated inside the group, an id
    of an earlier group, an empty claim, or one member that is global or of reach `project`. At most MAX_GROUPS
    are kept."""
    items = raw.get("groups") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], ["the answer is not an object with a list `groups`"]
    raw = items
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
            unknown = [x for x in ids if x not in by_id]
            if unknown:
                why = f"unknown id {unknown[0]}"
            elif len(set(ids)) != len(ids):
                why = "names an id more than once"
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


def verification_lines(groups: Sequence[Group], lessons: Mapping[str, Lesson]) -> list[str]:
    """For each group a block for the verifying session: `group <n>`, one `<id>\\t<claim>\\t<context>` line per
    member, then `proposed\\t<claim>\\t<context>`. `<n>` counts from 1."""
    out: list[str] = []
    for n, g in enumerate(groups, start=1):
        out.append(f"group {n}")
        for i in g.ids:
            m = lessons[i].memory
            out.append(f"{i}\t{_line(m.claim)}\t{_line(m.context)}")
        out.append(f"proposed\t{_line(g.claim)}\t{_line(g.context)}")
    return out


_ANSWERS = ("same", "faithful", "general")


def validate_verdicts(raw: object, groups: Sequence[Group]) -> tuple[list[Group], list[str]]:
    """`raw` is {"verdicts": [{"group": n, "reason": str, "same": bool, "faithful": bool, "general": bool}]}.
    A group is kept only with exactly one verdict naming it, a non-empty reason and all three answers exactly
    `true` (a group of one needs no `same`; a group with a global member needs no `faithful`, because the global
    record's wording stays). Every group not kept gives a reason line; a malformed answer keeps
    nothing. Never raises."""
    items = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], ["the answer is not an object with a list `verdicts`"]
    by_group: dict[int, list[dict]] = {}
    reasons: list[str] = []
    for item in items:
        n = item.get("group") if isinstance(item, dict) else None
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(groups):
            # a verdict that cannot be placed may be a refusal of any group: nothing is kept
            return [], ["a verdict does not name an existing group by its number: nothing is kept"]
        else:
            by_group.setdefault(n, []).append(item)
    kept: list[Group] = []
    for n, g in enumerate(groups, start=1):
        found = by_group.get(n, [])
        if len(found) != 1:
            reasons.append(f"group {n}: {'no verdict' if not found else 'more than one verdict'}")
            continue
        v = found[0]
        failed = []
        if not (isinstance(v.get("reason"), str) and v["reason"].strip()):
            failed.append("reason is empty or missing")
        for key in _ANSWERS:
            if key == "faithful" and any(i.startswith("g:") for i in g.ids):
                continue  # a group with a global member keeps that record's wording: the proposed claim is not used
            answer = v.get(key, True if key == "same" and len(g.ids) == 1 else None)
            if answer is not True:
                failed.append(f"{key} is not true")
        if failed:
            reasons.append(f"group {n}: " + "; ".join(failed))
        else:
            kept.append(g)
    return kept, reasons


@dataclass(frozen=True)
class Action:
    """What the pass does for one group; `kind` decides which fields are used.

    merge: `keep`, `drop` (lesson ids, one project), `project`.
    merge_global: `keep`, `drop` (lesson ids of two global records).
    write_global: `claim`, `context`, `record_kind`, `weight`, `entries` (sighting entries, each session once with
        the key of the first project that holds it), `members` (ids of the kept project records that stand for it,
        after merges), `cases` (raw `log` entries of the member records for these sessions).
    sighting: `target` (a global handle; None when the target is this group's write_global), `entry`, `cases` (raw
        `log` entries of the member records for its session).
    cases: `target` (a global handle that already counts the session), `entry`, `cases` (only the raw `log` entries of
        the members that the target lacks).
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
    cases: list[str] = field(default_factory=list)


def _oldest(lessons: Sequence[Lesson]) -> Lesson:
    return min(lessons, key=lambda x: (x.memory.created or datetime.date.max, x.memory.handle))


def _cases_of(lessons: Sequence[Lesson], sessions: set[str]) -> list[str]:
    """The raw `log` entries of `lessons` whose case is for one of `sessions`, each once, by date (stable): of two
    records' entries for one session and outcome, the earlier is applied first."""
    found = ((e, records.case(e)) for y in lessons for e in y.memory.log)
    wanted = {e: c for e, c in found if c and c.session in sessions}
    return sorted(wanted, key=lambda e: wanted[e].on)


def actions(group: Group, lessons: Mapping[str, Lesson]) -> list[Action]:
    """The steps for one group, in order: merges inside a project, a merge of global members, then for the
    members of reach `general` left: a write_global unless a global record is the target, one sighting per entry
    the target lacks (a `cases` action for an entry it counts but lacks cases of), one link per project member. A merged record stands for the ones dropped into it: its
    sessions are their union, and it is general when any of them is. Members of reach `project` from different
    projects produce no action. Only a global member of the group is a target: a global record that merely shares
    a session with a member may state another lesson of that session, so a pass that stopped half way may write a
    second global record, which a later pass joins with the first as two global members."""
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

    sess_of = {k: list(dict.fromkeys(s for y in group_of for s in records.sessions(y.memory)))
               for k, group_of in stands.items()}
    # a member with no session holds no evidence: it is neither written, sighted nor linked
    general = sorted((lessons[k] for k, group_of in stands.items()
                      if sess_of[k] and any(_reach(y) == "general" for y in group_of)), key=lambda x: x.id)
    if not general:
        return out
    first: dict[str, str] = {}  # session -> entry of the first member, in order, that holds it
    for x in general:
        key = records.project_key(x.project)
        for s in sess_of[x.id]:
            first.setdefault(s, records.sighting_entry(s, key))
    entries = list(first.values())

    target: records.Memory | None = gkeep.memory if gkeep else None
    if target is None:
        origin = _oldest([y for x in general for y in stands[x.id]])
        weights = [y.memory.weight or "medium" for x in general for y in stands[x.id]]
        out.append(Action("write_global", claim=group.claim, context=group.context or None,
                          record_kind=origin.memory.kind, weight=max(weights, key=records.WEIGHTS.index),
                          entries=entries, members=[x.id for x in general],
                          cases=_cases_of([y for x in general for y in stands[x.id]], set(first))))
        handle = None
    else:
        handle = target.handle
        held = [y for x in general for y in stands[x.id]]
        for e in entries:
            key = records.session_key(e)
            carried = _cases_of(held, {key})
            if not records.counted(target, e):
                out.append(Action("sighting", target=handle, entry=e, cases=carried))
                continue
            missing = [r for r in carried if not records.has_case(target, key, records.case(r).outcome)]
            if missing:
                out.append(Action("cases", target=handle, entry=e, cases=missing))
    for x in general:
        out.append(Action("link", member=x.id, project=x.project, target=handle))
    return out


def fill_records(projects: Sequence[Path], global_folder: Path | None) -> list[tuple[str, Path | None, records.Memory]]:
    """Every readable record, as (id, project path or None, memory), with the ids of `collect`: `p<n>:<handle>` for
    the n-th project and `g:<handle>` for a global record."""
    out: list[tuple[str, Path | None, records.Memory]] = []
    for n, project in enumerate(projects, start=1):
        out += [(f"p{n}:{m.handle}", project, m) for m in records.load_memories(records.project_dir(project), "project")
                if m.error is None]
    out += [(f"g:{m.handle}", None, m) for m in records.load_memories(global_folder, "global") if m.error is None]
    return out


def fill_key(project: Path | None, handle: str) -> str:
    """The name of a lesson that does not change between runs (the ids of `fill_records` depend on the registry)."""
    return f"g:{handle}" if project is None else f"{records.project_key(project)}:{handle}"


def fill_candidates(projects: Sequence[Path], global_folder: Path | None, today: datetime.date,
                    cap: int = FILL_CAP, attempts: dict | None = None) -> list[tuple[str, records.Memory]]:
    """(id, memory) of the lessons that could load as a rule (`rules.eligible`) and are not awaiting triage, but
    lack a valid short form or topic. The confirmed first, then the most corroborated; at most `cap`.
    With `attempts` (`fill_key` -> {"digest", "count"}), the automatic fill's view: a lesson tried `FILL_ATTEMPTS`
    times on its present claim, a strong project lesson the owner has not confirmed, and a lesson that already has
    a valid short form (it may be one the owner read: the pass never replaces a short form), leave before the cap."""
    found = []
    for i, p, m in fill_records(projects, global_folder):
        if not (rules.eligible(m, today) and m.triage != "pending"
                and not (records.valid_short(m.short) and records.valid_topic(m.topic))):
            continue
        if attempts is not None:
            if attempt_count(attempts.get(fill_key(p, m.handle)), claim_digest(m)) >= FILL_ATTEMPTS:
                continue
            if p is not None and m.weight == "strong" and m.owner_confirmed is None:
                continue
            if records.valid_short(m.short):
                continue
        found.append((i, m))
    found.sort(key=lambda x: (x[1].owner_confirmed is None, -len(records.projects(x[1])),
                              -len(records.sessions(x[1])), x[0]))
    return found[:cap]


def attempt_count(entry: object, digest: str) -> int:
    """Attempts stored for a lesson on this claim digest; anything malformed (a bool included) reads as zero."""
    if not isinstance(entry, dict) or entry.get("digest") != digest:
        return 0
    count = entry.get("count")
    return count if isinstance(count, int) and not isinstance(count, bool) else 0


def claim_digest(m: records.Memory) -> str:
    """Identifies the claim as stored, so a proposal for an older wording is never written."""
    return hashlib.sha256((m.claim or "").encode("utf-8", "replace")).hexdigest()


def fill_lines(candidates: Sequence[tuple[str, records.Memory]]) -> str:
    """What the model reads: one block per lesson (id, claim, context), blocks separated by a blank line."""
    blocks = []
    for ident, m in candidates:
        block = [f"id: {ident}", f"claim: {_line(m.claim)}"]
        if _line(m.context):
            block.append(f"context: {_line(m.context)}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def fill_problem(short: str, topic: str) -> str | None:
    """Why a proposed short form or topic cannot be applied, in English, or None when both can."""
    found = []
    if not short.strip():
        found.append("short is empty")
    elif short != short.strip():
        found.append("short has spaces at its ends")
    elif len(short.splitlines()) != 1:
        found.append("short must be one line")
    elif not records.valid_short(short):
        found.append(f"short has {len(short)} characters, at most {records.SHORT_LIMIT}")
    if not records.valid_topic(topic):
        found.append("topic must be one or two lowercase words")
    return "; ".join(found) or None


def check_lines(items: Sequence[tuple[str, str, str | None, str]]) -> str:
    """What the checking model reads: (id, claim, context, short) as blocks of one line a field, blank line between."""
    blocks = []
    for ident, claim, context, short in items:
        block = [f"id: {ident}", f"claim: {_line(claim)}"]
        if _line(context):
            block.append(f"context: {_line(context)}")
        block.append(f"short: {_line(short)}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def validate_check(payload: object, ids: Sequence[str]) -> dict[str, bool] | None:
    """`payload` is {"verdicts": [{"id", "reason", "faithful"}]}: id -> faithful, where only an exact `true` counts.
    None when the answer is unusable: not an object with a list, or not exactly one verdict for every id asked
    (a verdict for an id not asked is ignored)."""
    verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
    if not isinstance(verdicts, list):
        return None
    seen: dict[str, bool] = {}
    known = set(ids)
    for v in verdicts:
        ident = v.get("id") if isinstance(v, dict) else None
        if not isinstance(ident, str) or ident not in known:
            continue
        if ident in seen:
            return None
        seen[ident] = v.get("faithful") is True
    return seen if len(seen) == len(known) else None


def validate_fill(payload: object, ids: Sequence[str]) -> tuple[dict[str, dict], list[str]]:
    """`payload` is the model's whole answer, {"items": [{"id", "short", "topic"}]}. The items by id, as {"short",
    "topic"} plus a "problem" (see `fill_problem`) when either is invalid: that item keeps the model's text (a
    short cut to 300 characters, a value that is not a string as "") so the owner can repair it. The first item of
    a known id decides. A reason for each dropped item: no usable id, unknown id, repeated id."""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}, ["the answer is not an object with a list `items`"]
    known = set(ids)
    kept: dict[str, dict] = {}
    reasons: list[str] = []
    for n, item in enumerate(items, start=1):
        ident = item.get("id") if isinstance(item, dict) else None
        if not isinstance(ident, str):
            reasons.append(f"item {n}: not an object with an id")
        elif ident not in known:
            reasons.append(f"item {n}: unknown id {ident}")
        elif ident in kept:
            reasons.append(f"item {n}: repeats {ident}")
        else:
            short, topic = item.get("short"), item.get("topic")
            short = short if isinstance(short, str) else ""
            topic = topic if isinstance(topic, str) else ""
            problem = fill_problem(short, topic)
            kept[ident] = {"short": short[:300], "topic": topic, **({"problem": problem} if problem else {})}
    return kept, reasons


# --- automatic rewording of a loaded lesson that got worse ---

def reword_key(project: Path | None, handle: str) -> str:
    """The key of a lesson in the rewording's state: the fill's, one per lesson."""
    return fill_key(project, handle)


def _entry(state: Mapping, key: str) -> Mapping:
    lessons = state.get("lessons") if isinstance(state, Mapping) else None
    entry = lessons.get(key) if isinstance(lessons, Mapping) else None
    return entry if isinstance(entry, Mapping) else {}


def _count(entry: Mapping, version: datetime.date) -> int:
    count = entry.get("count")
    if entry.get("version") != version.isoformat() or not isinstance(count, int) or isinstance(count, bool):
        return 0
    return count


def reword_candidates(projects: Sequence[Path], gfolder: Path | None, today: datetime.date, state: Mapping,
                      *, every: bool = False) -> list[tuple[str, records.Memory]]:
    """(id, memory) of the lessons the automatic rewording may take: loading (or left out only for the size limit
    of the block) in some project's view, got worse, not strong, never reworded, not kept by the owner, not given
    up on for the present version and not spent. Most failed on the present version first; at most `REWORD_CAP`.
    With `every`, the lessons that did not get worse are taken too, and there is no cap."""
    recs = fill_records(projects, gfolder)
    glob = [m for _, p, m in recs if p is None]
    found: dict[str, tuple[str, records.Memory]] = {}
    for project in projects or [None]:
        mine = [m for _, p, m in recs if p is not None and p == project]
        choice = rules.choose(mine, glob, today)
        taken = {id(m) for m in choice.loaded} | {id(m) for m, why in choice.left if why == rules.OVER}
        for i, p, m in recs:
            if id(m) in taken and (p is None or p == project):
                found.setdefault(reword_key(p, m.handle), (i, m))
    out = []
    for key, (i, m) in found.items():
        versions = records.version_list(m)
        entry = _entry(state, key)
        if (not versions or (not every and not records.got_worse(m)) or m.weight == "strong"
                or m.reworded is not None or m.reviewed is not None or m.reword_failed == versions[-1][0]
                or entry.get("spent") is True or _count(entry, versions[-1][0]) >= REWORD_ATTEMPTS):
            continue
        out.append((i, m))
    out.sort(key=lambda x: (-records.tallies(x[1])[-1].failed, x[0]))
    return out if every else out[:REWORD_CAP]


_SEEN_AGAIN = re.compile(r"Seen again \(([^)]*)\)")


def _failure_signals(body: str) -> list[str]:
    seen: list[str] = []
    for text in (body or "").splitlines():
        found = _SEEN_AGAIN.search(text)
        if found and capture.outcome(found.group(1)) == "failed" and found.group(1) not in seen:
            seen.append(found.group(1))
    return seen


def reword_blocks(items: Sequence[tuple[str, records.Memory]]) -> str:
    """What the writing session reads: one block per lesson (id, claim, context, each version with its tally, the
    failure signals recorded in the body; never an evidence quote), blank line between."""
    blocks = []
    for ident, m in items:
        block = [f"id: {ident}", f"claim: {_line(m.claim)}"]
        if _line(m.context):
            block.append(f"context: {_line(m.context)}")
        found = records.tallies(m)
        for t in found:
            mark = " (present)" if t is found[-1] else ""
            block.append(f"version {t.number} (worked {t.worked}, failed {t.failed}): {_line(t.text)}{mark}")
        signals = _failure_signals(m.body)
        block.append(f"failed after it loaded: {', '.join(signals) if signals else 'not recorded'}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def same_text(a: str, b: str) -> bool:
    def norm(x: str) -> str:
        return " ".join(x.lower().split()).strip(" .!;:")
    return norm(a) == norm(b)


def reword_problem(short: str, memory: records.Memory) -> str | None:
    """Why a proposed short form cannot be applied, or None."""
    if not short.strip():
        return "short is empty"
    if short != short.strip():
        return "short has spaces at its ends"
    if len(short.splitlines()) != 1:
        return "short must be one line"
    if not records.valid_short(short):
        return f"short has {len(short)} characters, at most {records.SHORT_LIMIT}"
    if any(same_text(short, text) for _, text in records.version_list(memory)):
        return "same as an earlier wording"
    return None


def validate_reword(payload: object, items: Sequence[tuple[str, records.Memory]]) -> dict[str, dict]:
    """The writer's answer {"items": [{"id", "short"}]} as {id: {"short", "problem"}} for the ids asked; an id the
    answer lacks is absent; the first item of an id wins. ValueError when the answer is not an object with a list."""
    listed = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(listed, list):
        raise ValueError("the answer is not an object with a list `items`")
    memories = dict(items)
    out: dict[str, dict] = {}
    for item in listed:
        ident = item.get("id") if isinstance(item, dict) else None
        if not isinstance(ident, str) or ident not in memories or ident in out:
            continue
        short = item.get("short")
        short = short if isinstance(short, str) else ""
        out[ident] = {"short": short[:300], "problem": reword_problem(short, memories[ident])}
    return out
