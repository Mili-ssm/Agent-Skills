"""The curation handler (A5, ADR 0028): `curate`, and the session-start curation decisions (`_decisions`, the passes and marks files, the pair and note queues) with the logic only they use."""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import datetime
import hashlib
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack

from core import auto_state, safe_io, store_git
from corroborate import decide as corroborate_decide
from integrate.log import log_entries
from memories import records, rules
from notes import fields as note_fields
from notes import note as note_files
from notes import split_candidates
from syntheses import document, units
from syntheses import project as project_syntheses

from commands import common, edit, memory

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence


_CURATE_LINE_WORDS = 3  # `merge m:<keep> m:<drop>` and `attach <note> s:<h>#<section>`


def _got_worse(
    project: Sequence[records.Memory],
    global_: Sequence[records.Memory],
    today: datetime.date,
    choice: rules.Choice | None = None,
) -> list[tuple[records.Memory, bool]]:
    """The lessons whose present version got worse (records.got_worse) and that the rules block loads or leaves out
    over the cap; the flag says "loaded". `choose` gets both scopes so that the cap is the one of session start."""
    choice = choice if choice is not None else rules.choose(project, global_, today)
    found = [(m, True) for m in choice.loaded] + [
        (m, False) for m, why in choice.left if why == rules.OVER
    ]
    return [(m, loaded) for m, loaded in found if records.got_worse(m)]


_STALE_DAYS = 90


_FREQUENT = 3


_STANDING_KINDS = (
    "constraint",
    "decision",
    "state",
)  # no date makes them stale: only a refutation retires them


def _passes_file(env: Mapping[str, str]) -> Path | None:
    folder = common.data_dir(env)
    return folder / "curated.json" if folder is not None else None


def read_passes(env: Mapping[str, str]) -> dict[str, datetime.date]:
    """Date of the last pass per memory folder (resolved path), from the data folder; {} when unknown."""
    path = _passes_file(env)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path is not None else {}
        return {k: datetime.date.fromisoformat(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _write_passes(env: Mapping[str, str], covered: Sequence[Path], today: datetime.date) -> None:
    path = _passes_file(env)
    if path is None:
        raise OSError("no data folder: set MEM_DATA or HOME")
    known = {k: v.isoformat() for k, v in read_passes(env).items()}
    known.update({str(f.resolve()): today.isoformat() for f in covered})
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(path, (json.dumps(known, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _marks_file(env: Mapping[str, str]) -> Path | None:
    folder = common.data_dir(env)
    return folder / "curated-items.json" if folder is not None else None


def _parse_marks(text: str) -> dict[str, frozenset[str]]:
    try:
        return {
            k: frozenset(v)
            for k, v in json.loads(text).items()
            if isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
        }
    except (ValueError, AttributeError, TypeError):
        return {}


def read_marks(env: Mapping[str, str]) -> dict[str, frozenset[str]]:
    """Decision keys recorded by the last pass per memory folder (resolved path); anything unreadable reads as none."""
    path = _marks_file(env)
    try:
        return _parse_marks(path.read_text(encoding="utf-8")) if path is not None else {}
    except (OSError, ValueError):  # ValueError: not UTF-8
        return {}


def _write_marks(env: Mapping[str, str], covered: Mapping[Path, Collection[str]]) -> None:
    """Replace the keys of the covered folders only; `curated.json` is not touched (C100)."""
    path = _marks_file(env)
    if path is None:
        raise OSError("no data folder: set MEM_DATA or HOME")
    # a missing or malformed file starts empty; one that exists but cannot be read raises, so no key is dropped
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except UnicodeDecodeError:  # malformed, not unreadable
        text = ""
    known = {k: sorted(v) for k, v in _parse_marks(text).items()}
    known.update({str(f.resolve()): sorted(keys) for f, keys in covered.items()})
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(path, (json.dumps(known, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _tagged(m: records.Memory, extra: str = "") -> str:
    created = m.created.isoformat() if m.created else "undated"
    return f"  m:{m.handle}  [{m.kind}, {created}{extra}]  {memory._flat(m.claim)}"


def _differ_in(a: str, b: str) -> str:
    words = records.differing_words(a, b)
    return f"differ in: {', '.join(words)}" if words else "differ in: wording only"


_DECISION_LABELS = {
    "refuted": "refuted again",
    "pair": "same or opposite",
    "state": "newer state",
    "expired": "expired",
    "seen": "seen often",
    "stale": f"not confirmed in {_STALE_DAYS} days",
    "nofill": "no short form",
}


@dataclass(frozen=True)
class Decisions:
    """The decision items of one folder's curation queue (C98): `mem curate` prints them, the count counts them."""

    refuted: list[tuple[records.Memory, records.Memory]]  # (live, refuted)
    same: list[tuple[records.Memory, records.Memory]]
    state: list[tuple[records.Memory, records.Memory]]  # (old, new)
    expired: list[records.Memory]
    seen: list[records.Memory]
    stale: list[records.Memory]
    nofill: list[
        records.Memory
    ]  # established lessons the automatic short-form fill will not write (`fill_wont_write`)
    pairs_checked: bool

    def keys(self) -> dict[str, str]:
        """Each item's key (C100) with the label of its part."""
        found: dict[str, str] = {}
        for a, r in self.refuted:
            found[f"refuted:{a.handle}|{r.handle}"] = _DECISION_LABELS["refuted"]
        for a, b in self.same:
            found[f"pair:{'|'.join(sorted((a.handle, b.handle)))}"] = _DECISION_LABELS["pair"]
        for old, new in self.state:
            found[f"state:{old.handle}|{new.handle}"] = _DECISION_LABELS["state"]
        for name, items in (
            ("expired", self.expired),
            ("seen", self.seen),
            ("stale", self.stale),
            ("nofill", self.nofill),
        ):
            for m in items:
                found[f"{name}:{m.handle}"] = _DECISION_LABELS[name]
        return found


def _unconfirmed_handles(memories: Sequence[records.Memory]) -> set[str]:
    """Handles of the unconfirmed memories: they have their own category, so the other blocks skip them."""
    return {m.handle for m in memories if records.standing(m) == "unconfirmed"}


def _changed_since(live: Sequence[records.Memory], since: datetime.date) -> list[str]:
    """Handles of the memories changed on or after `since`, newest change first: created then, or its file written
    then (local time), or no `created`, or the file cannot be read."""
    found = []
    for m in live:
        try:
            written: datetime.date | None = datetime.date.fromtimestamp(m.path.stat().st_mtime)
        except OSError:
            written = None
        if m.created is not None and written is not None and m.created < since and written < since:
            continue
        found.append((
            max(m.created, written)
            if m.created is not None and written is not None
            else datetime.date.max,
            m.handle,
        ))
    found.sort(key=lambda t: (-t[0].toordinal(), t[1]))
    return [h for _, h in found]


class _DecisionOptions(TypedDict, total=False):
    """The keyword options of `_decisions`."""

    since: datetime.date | None
    budget: records.Budget | None
    attempts: dict | None
    root: Path | None
    tracked: frozenset[str] | None


def _decision_pairs(
    kept: list[records.Memory],
    today: datetime.date,
    among: list[str] | None,
    budget: records.Budget | None,
) -> tuple[
    list[tuple[records.Memory, records.Memory]], list[tuple[records.Memory, records.Memory]]
]:
    """The pairs of memories that may say the same: the ordinary ones, and the project `state` ones (oldest first)."""
    same: list[tuple[records.Memory, records.Memory]] = []
    state: list[tuple[records.Memory, records.Memory]] = []
    for a, b, _ in records.pairs(
        kept, today, tokenize=records.tokenize, among=among, budget=budget
    ):
        if (
            a.kind == "state" and b.kind == "state" and a.scope == b.scope == "project"
        ):  # C103: a project matter
            old, new = sorted((a, b), key=lambda m: (m.created or datetime.date.min, m.handle))
            state.append((old, new))
        else:
            same.append((a, b))
    return same, state


def _decision_stale(
    live: list[records.Memory], today: datetime.date, unconfirmed: set[str]
) -> list[records.Memory]:
    """The live memories nobody observed for `_STALE_DAYS` days; the standing kinds and unconfirmed ones never go stale."""
    cutoff = today - datetime.timedelta(days=_STALE_DAYS)
    return [
        m
        for m in live
        if m.kind not in _STANDING_KINDS
        and m.created is not None
        and m.handle not in unconfirmed
        and max(m.created, m.last_observed or m.created) <= cutoff
    ]


def _decision_nofill(
    kept: list[records.Memory],
    today: datetime.date,
    attempts: dict | None,
    root: Path | None,
    tracked: frozenset[str] | None,
) -> list[records.Memory]:
    """The memories the automatic short-form fill will not write; none unless `attempts` turns the kind on."""
    return [
        m
        for m in (records.mark_repository(kept, tracked) if root else kept)
        if attempts is not None and corroborate_decide.fill_wont_write(m, root, attempts, today)
    ]


def _decisions(
    loaded: Sequence[records.Memory],
    today: datetime.date,
    **options: Unpack[_DecisionOptions],
) -> Decisions:
    """The decision items of one folder from what `records.load_memories` returned: superseded memories and
    unreadable files are left out. With `since` the pair kinds compare only pairs with a memory changed since then;
    `budget` is spent by those comparisons. `attempts` (`_fill_attempts`) turns on the "no short form" kind; `root` is
    the project root of a project folder, None for the global one, and `tracked` its `records.tracked_memories`."""
    since = options.get("since")
    budget = options.get("budget")
    kept = [m for m in loaded if m.error is None and m.superseded_by is None]
    live = [m for m in kept if records.is_live(m, today)]
    among = _changed_since(live, since) if since is not None else None
    again = [
        (a, r)
        for a, r, _ in records.refuted_pairs(
            kept, today, tokenize=records.tokenize, among=among, budget=budget
        )
    ]
    same, state = _decision_pairs(kept, today, among, budget)
    unconfirmed = _unconfirmed_handles(kept)
    expired = [
        m
        for m in kept
        if m.status == "active"
        and m.valid_until is not None
        and m.valid_until < today
        and m.handle not in unconfirmed
    ]
    seen = [
        m for m in live if m.scope == "project" and m.observed >= _FREQUENT and not m.promote
    ]  # a global one cannot be promoted
    stale = _decision_stale(live, today, unconfirmed)
    nofill = _decision_nofill(
        kept,
        today,
        options.get("attempts"),
        options.get("root"),
        options.get("tracked", frozenset()),
    )
    return Decisions(
        again, same, state, expired, seen, stale, nofill, budget is None or not budget.exhausted
    )


type _MemoryPairs = Sequence[tuple[records.Memory, records.Memory]]


def _most_paired(pairs: _MemoryPairs) -> tuple[str, str]:
    """The (scope, handle) of the memory in the most pairs (ties by handle)."""
    count: collections.Counter = collections.Counter()
    for a, b in pairs:
        count.update([(a.scope, a.handle), (b.scope, b.handle)])
    return min(count, key=lambda k: (-count[k], k[1], k[0]))


def _pairs_of_member(
    left: _MemoryPairs, top: tuple[str, str]
) -> tuple[records.Memory, list[tuple[str, str, str]], list[tuple[records.Memory, records.Memory]]]:
    """The memory `top`, the lines of its partners (handle, tag and claim, differ line) and the pairs that do not hold it."""
    rest = []
    head = left[0][0]  # overwritten: `top` is a member of some pair
    lines = []
    for a, b in left:
        if (a.scope, a.handle) == top:
            head, other = a, b
        elif (b.scope, b.handle) == top:
            head, other = b, a
        else:
            rest.append((a, b))
            continue
        lines.append((
            other.handle,
            f"  {_tagged(other)}",
            f"      {_differ_in(head.claim, other.claim)}",
        ))
    return head, lines, rest


def _grouped_pairs(pairs: _MemoryPairs) -> list[str]:
    """C102: the memory in the most remaining pairs first (ties by handle) with its line, then one indented line per
    partner (its tag and claim, two spaces deeper) with its `differ in` below; each pair once."""
    left = list(pairs)
    out: list[str] = []
    while left:
        head, lines, left = _pairs_of_member(left, _most_paired(left))
        out.append(_tagged(head))
        for _, line, differ in sorted(lines):
            out += [line, differ]
    return out


TOPIC_CROWD = 8


TOPIC_LOOSE = 5  # of them, knowledge notes not yet part of any synthesis


def _note_line(note: note_files.Note) -> str:
    return (
        f"  {note_files._handle(note.rel)}  [{note.meta.get('confidence', '')}, {note.meta.get('updated', '')}]  "
        f"{memory._flat(str(note.meta.get('claim', '')))}"
    )


def _note_pairs(notes: Sequence[note_files.Note]) -> list[tuple[note_files.Note, note_files.Note]]:
    """Pairs of notes that share a topic and whose claims contain each other with at least `records.STRONG`,
    unless one names the other in `distinct_from`; the closest pair first."""
    notes = sorted(notes, key=lambda n: note_files._handle(n.rel))
    tokens = [set(records.tokenize(str(n.meta.get("claim", "")))) for n in notes]
    found = []
    for i, a in enumerate(notes):
        for j in range(i + 1, len(notes)):
            b = notes[j]
            if not set(a.meta.get("topics") or []) & set(b.meta.get("topics") or []):
                continue
            if note_files._handle(b.rel) in (
                a.meta.get("distinct_from") or []
            ) or note_files._handle(a.rel) in (b.meta.get("distinct_from") or []):
                continue
            score = max(
                records.containment(tokens[i], tokens[j]), records.containment(tokens[j], tokens[i])
            )
            if score >= records.STRONG:
                found.append((score, a, b))
    found.sort(key=lambda t: (-t[0], note_files._handle(t[1].rel), note_files._handle(t[2].rel)))
    return [(a, b) for _, a, b in found]


@dataclass(frozen=True)
class _NoteQueues:
    """The lines of the three note blocks of `mem curate --notes` that come from reading each note."""

    unattached: list[str] = dataclasses.field(default_factory=list)
    stale: list[str] = dataclasses.field(default_factory=list)
    disputed: list[str] = dataclasses.field(default_factory=list)


def _curate_notes_unattached(
    note: note_files.Note, name: str, synths: list[document.Synthesis], known: dict
) -> str | None:
    """The line of a note that is part of no synthesis though a synthesis covers its topic; None when none does."""
    topics = [t for t in note.meta.get("topics", []) if isinstance(t, str)]
    own = set(edit._own_topics(known, topics))
    covering = [x for x in synths if own & set(x.topics)]
    if not covering:
        return None
    return (
        f"  {name}  \u2192  {', '.join('s:' + x.handle for x in covering)}  "
        f"{memory._flat(str(note.meta.get('claim', '')))}"
    )


def _curate_notes_stale(
    note: note_files.Note, name: str, part: str, synths: list[document.Synthesis]
) -> str | None:
    """The line of a note older than the synthesis section it is part of; None when it is current."""
    handle, _, section = part.partition("#")
    syn = next((x for x in synths if x.handle == handle), None)
    sec = next((x for x in syn.sections if x.handle == section), None) if syn else None
    if sec is not None and not units.is_current(
        note.meta.get("part_of_hash"), sec.text, common._note_target(note.rel)
    ):
        return f"  {name}  s:{handle}#{section}"
    return None


def _curate_notes_file(
    note: note_files.Note, synths: list[document.Synthesis], known: dict, queues: _NoteQueues
) -> None:
    """Sort one knowledge note into the queues (disputed, not yet part of a synthesis, older than its section)."""
    if note.type != "knowledge" or note.error is not None or not isinstance(note.meta, dict):
        return
    if note_fields._disputed(note.meta.get("disputed")) is None:
        queues.disputed.append(
            f"  {note_files._handle(note.rel)}  {memory._flat(str(note.meta.get('claim', '')))}  "
            f"(source: {note.meta['disputed'][0]['source']})"
        )
    part = note.meta.get("part_of")
    name = note_files._handle(note.rel)
    if not isinstance(part, str):
        line = _curate_notes_unattached(note, name, synths, known)
        if line is not None:
            queues.unattached.append(line)
        return
    line = _curate_notes_stale(note, name, part, synths)
    if line is not None:
        queues.stale.append(line)


def _curate_notes_blocks(queues: _NoteQueues) -> list[str]:
    """The disputed, unattached and stale blocks: a heading with the decision to take, then the lines."""
    out: list[str] = []
    if queues.disputed:
        out.append(
            "notes disputed by a source (decide: correct the note with mem note edit, "
            "or mem note dispute <note> --clear)"
        )
        out += queues.disputed
    if queues.unattached:
        out.append(
            "notes on a topic that has a synthesis, not yet part of it (add what the note says to a part with "
            "mem synthesis append or add, then: mem synthesis attach <note> s:<h>#<section>)"
        )
        out += queues.unattached
    if queues.stale:
        out.append(
            "notes older than their section (rewrite the note from the section: mem show s:<h>#<section>)"
        )
        out += queues.stale
    return out


def _curate_notes_same(live: list[note_files.Note]) -> list[str]:
    """The block of knowledge notes that may say the same or the opposite."""
    same = _note_pairs([n for n in live if n.type == "knowledge"])
    if not same:
        return []
    out = [
        (
            "notes that say the same or the opposite? (decide: mem unify <keep> <other> --body-file \u2026, "
            "mem distinct <a> <b>, or leave)"
        )
    ]
    for a, b in same:
        out += [
            _note_line(a),
            _note_line(b),
            f"  {_differ_in(str(a.meta.get('claim', '')), str(b.meta.get('claim', '')))}",
        ]
    return out


def _curate_notes_crowded(
    live: list[note_files.Note], synths: list[document.Synthesis], known: dict
) -> list[str]:
    """The block of topics with many notes and no synthesis."""
    covered = {t for x in synths for t in x.topics}
    counts: collections.Counter = collections.Counter()
    loose: collections.Counter = (
        collections.Counter()
    )  # knowledge notes that are part of no synthesis
    for n in live:
        if n.type in {"knowledge", "literature"}:
            own = edit._own_topics(
                known, [t for t in n.meta.get("topics", []) if isinstance(t, str)]
            )
            counts.update(own)
            if n.type == "knowledge" and not n.meta.get("part_of"):
                loose.update(own)
    # A topic whose notes already sit in other syntheses is not worth a document of its own.
    crowded = sorted(
        (
            (t, c)
            for t, c in counts.items()
            if c >= TOPIC_CROWD and t not in covered and loose[t] >= TOPIC_LOOSE
        ),
        key=lambda tc: (-tc[1], tc[0]),
    )
    if not crowded:
        return []
    return [
        f"topics with {TOPIC_CROWD} notes or more and no synthesis (mem synthesis new)",
        *(f"  {t}  {c} notes" for t, c in crowded),
    ]


def _curate_notes(args: argparse.Namespace) -> int:
    root = args.root
    if root is None:
        print("mem: curate --notes needs a store", file=sys.stderr)
        return 2
    synths = [x for x in document.load(root / document.SYNTHESES_DIR) if x.error is None]
    try:
        known = note_files.load_topics(root)
    except note_files.FrontmatterError:
        known = {}
    queues = _NoteQueues()
    for note in note_files.discover_notes(root):
        _curate_notes_file(note, synths, known, queues)
    out = _curate_notes_blocks(queues)
    live = [
        n
        for n in note_files.discover_notes(root)
        if n.error is None and isinstance(n.meta, dict) and n.meta.get("superseded_by") is None
    ]
    out += _curate_notes_same(live)
    out += _curate_notes_crowded(live, synths, known)
    candidates = split_candidates.find_candidates(live, synths, known)
    if candidates:
        out.append("synthesis split candidates")
        out.extend(f"  s:{c.part}  {c.topic}  {len(c.notes)} notes" for c in candidates)
    if out:
        print("\n".join(out))
    return 0


_PROJECT_SYNTHESIS_MIN_MEMORIES = 5


def _curate_project_syntheses(
    scopes: Sequence[tuple[str, Path | None, list[records.Memory]]], today: datetime.date
) -> list[str]:
    """The two project synthesis blocks of `mem curate`: parts possibly stale, and none written yet."""
    context = _project_synthesis_context_quiet()
    if context is None:
        return []
    memory_dir, tree = context
    found, broken = project_syntheses.load_each(memory_dir)
    out: list[str] = []
    if broken:
        out.append("-- project syntheses: unreadable --")
        out += [f"{path}\t{error}" for path, error in broken]
    states = [
        (name, part, project_syntheses.freshness(tree, part.stamp))
        for name, parts in found.items()
        for part in parts
    ]
    stale = [
        (name, part, state) for name, part, state in states if state != project_syntheses.FRESH
    ]
    if stale:
        out.append("-- project syntheses: possibly stale --")
        out += [
            f"p:{name}#{part.handle}\t{project_syntheses.describe(state)}"
            for name, part, state in stale
        ]
    active = sum(
        1
        for scope, _, loaded in scopes
        if scope == "project"
        for m in loaded
        if m.error is None and records.is_live(m, today)
    )
    if not found and not broken and active >= _PROJECT_SYNTHESIS_MIN_MEMORIES:
        out += [
            "-- project syntheses: none yet --",
            f"{active} active memories and no project synthesis: organize them (see the memory-curation skill).",
        ]
    return out


def _project_synthesis_context_quiet() -> tuple[Path, Path] | None:
    """(memory folder, working tree) of the project the session is in; None outside a project, silently."""
    try:
        root = records.project_root(Path.cwd(), os.environ)
    except OSError:
        return None
    if root is None:
        return None
    return records.project_dir(root), project_syntheses.worktree(Path.cwd(), root, os.environ)


def _claim_key(claim: str) -> str:
    """A claim for the safe-merge test: case, whitespace and trailing punctuation do not count."""
    return " ".join(claim.lower().split()).rstrip(" .,;:!?")


def _parse_actions(text: str) -> list[tuple[str, list[str]]]:
    """(raw line, words) of each action line; blank lines and `#` comments dropped. ValueError on a known verb
    with the wrong number of arguments, so a malformed file applies nothing."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        words = line.split()
        if words[0] == "merge" and len(words) != _CURATE_LINE_WORDS:
            raise ValueError(f"malformed line (merge m:<keep> m:<drop>): {line}")
        if words[0] == "attach" and len(words) != _CURATE_LINE_WORDS:
            raise ValueError(f"malformed line (attach <note> s:<h>#<section>): {line}")
        out.append((" ".join(words), words))
    return out


def _last_error(buf: io.StringIO, default: str) -> str:
    lines = [ln.removeprefix("mem: ").strip() for ln in buf.getvalue().splitlines() if ln.strip()]
    return lines[-1] if lines else default


def _curate_merge_refusal(a: records.Memory, b: records.Memory) -> str | None:
    """Why two memories must not be merged automatically; None when they are the same claim, both active, in one
    scope."""
    if a.handle == b.handle:
        return "the same memory twice"
    if a.scope != b.scope:
        return "different scopes"
    for m in (a, b):
        if m.status != "active" or m.superseded_by is not None:
            return f"m:{m.handle} is {m.status}"
    if _claim_key(a.claim) != _claim_key(b.claim):
        return "the claims are not equal"
    return None


def _safe_merge(args: argparse.Namespace, keep: str, drop: str) -> str | None:
    """None after the merge ran; else why it was left. Only equal claims, both active, in one scope; never --force."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        found = memory._memory_of(args, [keep, drop])
    if found is None:
        return _last_error(err, "memories not found")
    refusal = _curate_merge_refusal(*found)
    if refusal is not None:
        return refusal
    ns = argparse.Namespace(**{**vars(args), "keep": keep, "drop": drop, "force": False})
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = memory.cmd_merge(ns)
    return None if code == 0 else _last_error(err, "the merge was refused")


def _curate_attach_refusal(root: Path, found: Path, target: str) -> str | None:
    """Why the note must not be attached automatically to `target`; None when the part's `Sources:` line links it and
    it is not part of a synthesis yet."""
    try:
        syn, sec = common._section_ref(root, target)
        part = note_files.split_frontmatter(note_files._read_text(found))[0].get("part_of")
    except (ValueError, OSError, note_files.FrontmatterError) as exc:
        return str(exc)
    if part:
        return f"the note is already part of s:{part}"
    cited = {(syn.path.parent / s).resolve() for s in sec.sources}
    if found.resolve() not in cited:
        return "the part's Sources line does not link the note"
    return None


def _safe_attach(args: argparse.Namespace, note: str, target: str) -> str | None:
    """None after the attach ran; else why it was left. Only when the part's `Sources:` line links the note and the
    note is not part of a synthesis yet."""
    root = args.root
    if not isinstance(root, Path) or not root.is_dir() or not records.store_is_writable(root):
        return "no writable store"
    found = common.resolve_note(root, note)
    if isinstance(found, list):
        return "the note name is ambiguous"
    if found is None:
        return "no such note"
    refusal = _curate_attach_refusal(root, found, target)
    if refusal is not None:
        return refusal
    ns = argparse.Namespace(root=root, note=note, target=target)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = edit._attach(ns)
    return None if code == 0 else _last_error(err, "the attach was refused")


def _curate_run_action(args: argparse.Namespace, words: list[str]) -> str | None:
    """None after the action ran; else why it was left."""
    if words[0] == "merge":
        return _safe_merge(args, words[1], words[2])
    if words[0] == "attach":
        return _safe_attach(args, words[1], words[2])
    return f"not a safe action ({words[0]})"


def _curate_apply(args: argparse.Namespace) -> int:
    """`mem curate apply --safe`: action lines from a file or stdin; only what the code can prove safe runs."""
    if not args.safe:
        print("mem: curate apply runs only with --safe: there is no unsafe mode.", file=sys.stderr)
        return 2
    try:
        text = (
            sys.stdin.read()
            if args.from_file in {None, "-"}
            else Path(args.from_file).read_text(encoding="utf-8")
        )
        actions = _parse_actions(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    applied = left = 0
    for line, words in actions:
        why = _curate_run_action(args, words)
        if why is None:
            applied += 1
            print(f"applied\t{line}")
        else:
            left += 1
            print(f"left\t{line}\t{why}")
    print(f"applied {applied}, left {left}")
    return 0


def _integrate_stamps(store: Path) -> dict[str, str]:
    """`{hub-relative path: digest}` of the text of each file that `mem synthesis integrate` left, or an undo of it
    put back, per the curation log read as a stack: the digest is the `after` of the file's newest live entry when
    that is an `integrate` entry, or that of the `before` text when the file's newest entry is a restore marker
    cancelling an `integrate` entry."""
    entries = log_entries(store)
    by_line = {e["line"]: e for _, e in entries}
    newest_live: dict[str, dict] = {}
    newest_any: dict[str, dict] = {}
    for gone, entry in entries:
        newest_any[entry["handle"]] = entry
        if entry.get("action") != "restore" and not gone:
            newest_live[entry["handle"]] = entry
    stamps = {
        handle: str(entry.get("after"))
        for handle, entry in newest_live.items()
        if entry.get("action") == "integrate"
    }
    for handle, marker in newest_any.items():
        undone = by_line.get(marker.get("undone")) if marker.get("action") == "restore" else None
        if (
            undone is not None
            and undone.get("action") == "integrate"
            and isinstance(undone.get("before"), str)
        ):
            stamps[handle] = hashlib.sha256(undone["before"].encode("utf-8")).hexdigest()
    return stamps


def _written_by_integrate(path: Path, store: Path, stamps: dict[str, str]) -> bool:
    """True when `mem synthesis integrate` wrote the file's current text: its mtime says nothing new."""
    if not path.is_relative_to(store):
        return False
    after = stamps.get(path.relative_to(store).as_posix())
    return after is not None and hashlib.sha256(path.read_bytes()).hexdigest() == after


def _curate_new_since(args: argparse.Namespace) -> int:
    """Print how many global memories and notes of the store were written after `--new-since` (epoch seconds) and
    after the last curation pass of the global memories (its day counts as passed). File times: an edit counts as new,
    except a note whose current text is what `mem synthesis integrate` last wrote. The trigger of `mem-auto`."""
    store = args.root
    cutoff = float(args.new_since)
    memories = records.memories_root(
        os.environ, store if store is not None and store.is_dir() else None
    )
    paths: list[Path] = []
    if memories is not None and memories.is_dir():
        last = read_passes(os.environ).get(str(memories.resolve()))
        if last is not None:
            cutoff = max(
                cutoff,
                datetime.datetime.combine(
                    last + datetime.timedelta(days=1), datetime.time.min
                ).timestamp(),
            )
        today = datetime.date.today()
        paths += [
            m.path
            for m in records.load_memories(memories, "global")
            if m.error is None and records.is_live(m, today) and m.origin is None
        ]  # a pipeline's own writes must not start the next run
    stamps: dict[str, str] = {}
    if store is not None and store.is_dir():
        paths += [store / n.rel for n in note_files.discover_notes(store) if n.error is None]
        stamps = _integrate_stamps(store)
    count = 0
    for path in paths:
        try:
            newer = path.stat().st_mtime > cutoff
            count += newer and not (
                store is not None and _written_by_integrate(path, store, stamps)
            )
        except OSError:
            continue
    print(count)
    return 0


type _CurateScopes = Sequence[tuple[str, Path | None, list[records.Memory]]]


@dataclass(frozen=True)
class _CuratePass:
    """The folders a `mem curate done` pass covers, with the decision keys and the scope label of each."""

    covered: list[Path]
    keys: dict[Path, set[str]]
    labels: dict[Path, str]


def _curate_pass_keys(folder: Path, scope: str, attempts: dict, today: datetime.date) -> set[str]:
    """The decision keys of one folder's queue, as `mem curate done` records them."""
    root = folder.parent if scope == "project" else None
    return set(
        _decisions(
            records.load_memories(folder, scope),
            today,
            attempts=attempts,
            root=root,
            tracked=records.tracked_memories(root) if root else frozenset(),
        ).keys()
    )


def _curate_pass_of(
    store: Path | None, scopes: _CurateScopes, attempts: dict, today: datetime.date
) -> _CuratePass | None:
    """The folders a pass covers; None after a message on stderr when one of them is read-only."""
    covered = []
    keys: dict[Path, set[str]] = {}
    labels: dict[Path, str] = {}
    for scope, folder, _ in scopes:
        if folder is None or not folder.is_dir():
            continue
        if common._read_only_store(store, folder.resolve()):
            print(
                common._READ_ONLY_PROJECT if scope == "project" else common._READ_ONLY_MEMORIES,
                file=sys.stderr,
            )
            return None
        covered.append(folder)
        keys[folder] = _curate_pass_keys(folder, scope, attempts, today)
        labels[folder] = scope
    return _CuratePass(covered, keys, labels)


def _curate_record_pass(passed: _CuratePass, today: datetime.date) -> int:
    """Write the marks and the pass dates of the covered folders and say how many items each held; 2 when the write
    fails."""
    if not passed.covered:
        return 0
    try:
        _write_marks(
            os.environ, passed.keys
        )  # first: a failed write leaves the pass date where it was
        _write_passes(os.environ, passed.covered, today)
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    for folder in sorted(passed.covered, key=lambda f: passed.labels[f] != "global"):
        n = len(passed.keys[folder])
        print(f"recorded {n} {'item' if n == 1 else 'items'} ({passed.labels[folder]})")
    return 0


def _curate_commit_pass(store: Path | None, today: datetime.date) -> None:
    """Commit the store after a pass and trim its logs."""
    if store is not None and store_git.is_repo(store):
        _, failed = common._commit_points(
            store, lambda n: f"curation pass {today.isoformat()}: {n} files"
        )
        # git holds the older states now: the logs keep 30 days. Not while an automatic run may be appending
        # to them, and under the commit lock so a commit never sees a half-written log.
        if not failed and not auto_state.run_lock_held(common.data_dir(os.environ), store):
            store_git.trim_logs_locked(store)


def _curate_done(
    args: argparse.Namespace, scopes: _CurateScopes, attempts: dict, today: datetime.date
) -> int:
    """`mem curate --done`: record the pass over the folders loaded."""
    store = common._optional_store(args)
    passed = _curate_pass_of(store, scopes, attempts, today)
    if passed is None:
        return 2
    code = _curate_record_pass(passed, today)
    if code != 0:
        return code
    _curate_commit_pass(store, today)
    return 0


def _curate_decisions(
    scopes: _CurateScopes, attempts: dict, today: datetime.date
) -> list[Decisions]:
    """The decision items of each scope, in order."""
    roots = [
        folder.parent if scope == "project" and folder else None for scope, folder, _ in scopes
    ]
    return [
        _decisions(
            loaded,
            today,
            attempts=attempts,
            root=root,
            tracked=records.tracked_memories(root) if root else frozenset(),
        )
        for root, (_, _, loaded) in zip(roots, scopes, strict=False)
    ]


def _curate_refuted_lines(found: Sequence[Decisions]) -> list[str]:
    again = [pair for d in found for pair in d.refuted]
    if not again:
        return []
    out = [
        (
            "written again after being refuted (decide: mem refute <h>, or mem distinct <a> <b> if it is a "
            "different claim)"
        )
    ]
    for a, r in again:
        out += [_tagged(a), _tagged(r, ", refuted")]
    return out


def _curate_same_lines(found: Sequence[Decisions]) -> list[str]:
    same = [pair for d in found for pair in d.same]
    if not same:
        return []
    header = (
        "same or opposite? (decide: mem merge <keep> <drop>, or keep both and say so in the body)"
    )
    return [header, *_grouped_pairs(same)]


def _curate_state_lines(found: Sequence[Decisions]) -> list[str]:
    state = [pair for d in found for pair in d.state]
    if not state:
        return []
    out = [
        "newer state of the same project? (decide: mem supersede <old> <new>, or mem distinct <a> <b>)"
    ]
    for old, new in state:
        out += [_tagged(old), f"    -> {_tagged(new).lstrip()}"]
    return out


def _curate_expired_lines(found: Sequence[Decisions]) -> list[str]:
    expired = [m for d in found for m in d.expired]
    if not expired:
        return []
    out = ["expired (decide: mem forget <h>, or mem confirm <h> --until <date> if it still holds)"]
    out += [
        f"  m:{m.handle}  valid until {m.valid_until.isoformat()}  {memory._flat(m.claim)}"
        for m in expired
        if m.valid_until is not None
    ]
    return out


def _curate_seen_lines(found: Sequence[Decisions]) -> list[str]:
    frequent = [m for d in found for m in d.seen]
    if not frequent:
        return []
    out = [f"seen {_FREQUENT} times or more: general enough for a global lesson? (mem promote <h>)"]
    out += [f"  m:{m.handle}  observed {m.observed}  {memory._flat(m.claim)}" for m in frequent]
    return out


def _curate_stale_lines(found: Sequence[Decisions]) -> list[str]:
    stale = [m for d in found for m in d.stale]
    if not stale:
        return []
    out = [f"not confirmed in {_STALE_DAYS} days (decide: mem confirm <h> or mem forget <h>)"]
    out += [
        f"  m:{m.handle}  {m.created.isoformat()}  {memory._flat(m.claim)}"
        for m in stale
        if m.created is not None
    ]
    return out


def _curate_awaiting_lines(live: Sequence[records.Memory]) -> list[str]:
    awaiting = [m for m in live if m.triage == "pending"]
    if not awaiting:
        return []
    out = [
        (
            "general lesson, out of quarantine, awaiting triage (decide: mem triage accept <h>, mem triage "
            "reject <h>, or reword it with mem memory edit <h> --global and then accept)"
        )
    ]
    for m in awaiting:
        n, p = len(records.sessions(m)), len(records.projects(m))
        out.append(
            f"  m:{m.handle}  {n} session{'' if n == 1 else 's'}, {p} project{'' if p == 1 else 's'}  "
            f"{memory._flat(m.claim)}"
        )
        if m.triage_reason:
            out.append(f"    held: {m.triage_reason}")
    return out


def _curate_worse_lines(
    args: argparse.Namespace,
    raw: dict[str, list[records.Memory]],
    scopes: _CurateScopes,
    today: datetime.date,
) -> list[str]:
    """The lessons whose balance got worse after loading; `raw` gets the scope not asked for, loaded quietly."""
    asked = {scope for scope, _, _ in scopes}
    for scope, folder in common._memory_folders(
        args
    ):  # the scope not asked for still counts toward the cap; loaded quietly
        if scope not in raw:
            raw[scope] = records.load_memories(folder, scope)
    worse = [
        (m, loaded)
        for m, loaded in _got_worse(raw.get("project", []), raw.get("global", []), today)
        if m.scope in asked and m.superseded_by is None
    ]
    if not worse:
        return []
    out = [
        (
            "balance got worse after loading (decide: reword it or go back with mem memory edit <h> --short, "
            "drop it with mem forget <h>, or keep the wording with mem triage accept <h>)"
        )
    ]
    for m, loaded in worse:
        state = (
            "rules off" if common._rules_off() else "loaded" if loaded else "left out by the cap"
        )
        note = records.reword_note(m)
        out.append(f"  m:{m.handle}  {state}{'; ' + note if note else ''}  {memory._flat(m.claim)}")
        found = records.tallies(m)[-2:]
        ends = [t.since for t in found[1:]] + [today]
        out += [f"    {common._tally_line(t, end)}" for t, end in zip(found, ends, strict=False)]
    return out


def _curate_quarantine_lines(every: Sequence[records.Memory]) -> list[str]:
    held = sum(
        1 for m in every if m.status == "active" and records.quarantined(m)
    )  # a lapsed one is still stored
    if not held:
        return []
    return [
        (
            f"in quarantine: {held} general lesson{'' if held == 1 else 's'}, not shown to a reader until corroborated "
            "(mem memories --global --quarantine)"
        )
    ]


def _curate_unconfirmed_lines(live: Sequence[records.Memory], unconfirmed: set[str]) -> list[str]:
    waiting = [m for m in live if m.handle in unconfirmed and not records.quarantined(m)]
    if not waiting:
        return []
    out = [
        (
            "from a transcript, not confirmed yet (decide: mem forget <h>, or leave it; it is confirmed only "
            "when another session shows it)"
        )
    ]
    for m in waiting:
        n = len(records.sessions(m))
        out.append(
            f"  m:{m.handle}  {m.weight or 'medium'}, {n} session{'' if n == 1 else 's'}  {memory._flat(m.claim)}"
        )
    return out


def _curate_unread_lines(live: Sequence[records.Memory]) -> list[str]:
    unread = [m for m in live if m.short_by == "model" and m.short]
    return [f"short forms nobody read: {len(unread)} (mem rules --unread)"] if unread else []


def _curate_nofill_lines(found: Sequence[Decisions]) -> list[str]:
    nofill = [m for d in found for m in d.nofill]
    if not nofill:
        return []
    out = [
        (
            "established, but the automatic fill will not write its short form (it gave up, or never "
            f"tries a repository-tracked or strong unconfirmed project lesson); write one of at most "
            f"{records.SHORT_LIMIT} characters and pick a topic: mem memory edit m:<h> --short '<text>' "
            "--topic <t>, with --global for a global lesson; add --user-read only when the owner wrote or read the text)"
        )
    ]
    out += [f"  m:{m.handle}  {memory._flat(m.claim)}" for m in nofill]
    return out


def _curate_report(
    args: argparse.Namespace,
    scopes: _CurateScopes,
    attempts: dict,
    today: datetime.date,
) -> int:
    """Print the curation queue: every decision the owner or the pipeline has to take."""
    raw = {scope: loaded for scope, _, loaded in scopes}
    scopes = [(s, f, [m for m in loaded if m.superseded_by is None]) for s, f, loaded in scopes]
    every = [m for _, _, loaded in scopes for m in loaded if m.error is None]
    live = [m for m in every if records.is_live(m, today)]
    found = _curate_decisions(scopes, attempts, today)
    unconfirmed = _unconfirmed_handles(every)  # their own category below
    out = [
        *_curate_refuted_lines(found),
        *_curate_same_lines(found),
        *_curate_state_lines(found),
        *_curate_expired_lines(found),
        *_curate_seen_lines(found),
        *_curate_stale_lines(found),
        *_curate_awaiting_lines(live),
        *_curate_worse_lines(args, raw, scopes, today),
        *_curate_quarantine_lines(every),
        *_curate_unconfirmed_lines(live, unconfirmed),
        *_curate_unread_lines(live),
        *_curate_nofill_lines(found),
    ]
    if not args.is_global:
        out += _curate_project_syntheses(scopes, today)
    if out:
        print("\n".join(out))
    return 0


def cmd_curate(args: argparse.Namespace) -> int:
    if args.action == "apply":
        return _curate_apply(args)
    if args.new_since is not None:
        return _curate_new_since(args)
    if args.notes:
        return _curate_notes(args)
    today = datetime.date.today()
    folders = common._memory_folders(args)
    if args.is_project or args.is_global:
        folders = [f for f in folders if (f[0] == "global") == args.is_global]
    scopes = memory._loaded(folders)
    attempts = common._fill_attempts(os.environ)
    if args.done:
        return _curate_done(args, scopes, attempts, today)
    return _curate_report(args, scopes, attempts, today)
