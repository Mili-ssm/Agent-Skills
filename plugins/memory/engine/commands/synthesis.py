"""The synthesis handlers (A5, ADR 0028): `synthesis` and `project-synthesis`, with the logic only they use (the structure and refs commands, section-with-note writes, the logged multi-file write, the project-synthesis handlers)."""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml
from core import safe_io
from memories import records
from notes import check as check_rules
from notes import index as index_files
from notes import note as note_files
from syntheses import document, units
from syntheses import edit as synthesis_edit
from syntheses import project as project_syntheses

from commands import common, edit

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence

_SETTLE_LOG_CELLS = 3  # `<section> | <unit> | add|remove <target>`


_SETTLE_ACTION_WORDS = 2  # `add|remove <target>`


def _warn_uncommitted(ref: str) -> None:
    print(
        f"mem: {ref} covers files with uncommitted changes; "
        "it will read possibly stale until you confirm it after committing.",
        file=sys.stderr,
    )


def _ps_list(args: argparse.Namespace, memory_dir: Path, tree: Path) -> int:
    found, broken = project_syntheses.load_each(memory_dir)
    for name, parts in found.items():
        for part in parts:
            print(common._part_line(name, part, tree))
    for path, error in broken:
        print(f"mem: skipped {path}: {error}", file=sys.stderr)
    return 1 if broken else 0


def _ps_check_name(name: str) -> None:
    if name not in project_syntheses.NAMES:
        raise project_syntheses.ProjectSynthesisError(
            f"unknown project synthesis {name!r}; use one of: {', '.join(project_syntheses.NAMES)}"
        )


def _ps_add(args: argparse.Namespace, memory_dir: Path, tree: Path) -> int:
    try:
        body = common._memory_body(args.body_file)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mem: cannot read the body: {exc}", file=sys.stderr)
        return 2
    _ps_check_name(args.name)
    paths = [p for p in (item.strip() for item in args.paths.split(",")) if p]
    project_syntheses._check_paths(
        tree, paths
    )  # before the secret scan, so a bad path is not reported as a secret
    if common._refuse_secret([args.heading, body]):
        return 4
    handle = project_syntheses.write_part(
        memory_dir,
        tree,
        project_syntheses.NewPart(args.name, args.heading, body, paths),
        datetime.date.today(),
    )
    ref = f"p:{args.name}#{handle}"
    print(ref)
    if project_syntheses.covers_uncommitted(tree, paths):
        _warn_uncommitted(ref)
    return 0


def _ps_confirm(args: argparse.Namespace, memory_dir: Path, tree: Path) -> int:
    name, handle = common._split_part_ref(args.part)
    found = common._load_project_syntheses(memory_dir, name)
    if handle is None or name not in found or handle not in [p.handle for p in found[name]]:
        raise project_syntheses.Unavailable(
            f"no part {args.part!r}; parts that exist: {common._existing_parts(found)}"
        )
    project_syntheses.confirm_part(memory_dir, tree, name, handle, datetime.date.today())
    print(
        f"p:{name}#{handle}\tconfirmed at {project_syntheses.head_commit(tree) or project_syntheses.NO_COMMIT}"
    )
    part = next(p for p in found[name] if p.handle == handle)
    if project_syntheses.covers_uncommitted(tree, part.stamp.paths):
        _warn_uncommitted(f"p:{name}#{handle}")
    return 0


_PS_HANDLERS = {"list": _ps_list, "add": _ps_add}


def cmd_project_synthesis(args: argparse.Namespace) -> int:
    context = common._project_synthesis_context()
    if context is None:
        return 2
    memory_dir, tree, _ = context
    try:
        return _PS_HANDLERS.get(args.ps_command, _ps_confirm)(args, memory_dir, tree)
    except project_syntheses.ProjectSynthesisError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1 if isinstance(exc, project_syntheses.Unavailable) else 2


def _synthesis_text(source: str | None) -> str | None:
    try:
        return common._read_body(source) if source else ""
    except common.NewNoteError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return None


def _long_note(handle: str, path: Path, section: str) -> None:
    sec = next((x for x in document.load_one(path).sections if x.handle == section), None)
    if sec is not None and (n := units.word_count(sec.text)) > document.LONG_SECTION_WORDS:
        print(
            f"mem: s:{handle}#{section} has {n} words: consider splitting it into two parts "
            "(mem synthesis add).",
            file=sys.stderr,
        )


def _part_of_notes(root: Path, ref: str) -> list[tuple[Path, str]]:
    """(path, text) of each note whose `part_of` is `ref` (`<synthesis>#<section>`), sorted by path."""
    found = []
    for _, path in note_files._note_files(root):
        try:
            text = path.read_bytes().decode("utf-8")
            meta = note_files.split_frontmatter(text)[0]
        except (OSError, UnicodeDecodeError, note_files.FrontmatterError):
            continue
        if isinstance(meta, dict) and meta.get("part_of") == ref:
            found.append((path, text))
    return sorted(found)


def _log_group_ahead(root: Path, changes: Mapping[Path, tuple[bytes, bytes]], action: str) -> str:
    """The group entries `_log_group` writes, but before the files change: each holds the digest of the new bytes.
    Returns the group id."""
    group = uuid.uuid4().hex
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_io.append_text(
        root / records.CURATION_LOG,
        "".join(
            json.dumps(
                {
                    "t": stamp,
                    "action": action,
                    "handle": path.relative_to(root).as_posix(),
                    "group": group,
                    "before": old.decode("utf-8"),
                    "after": common._sha(new),
                },
                ensure_ascii=False,
            )
            + "\n"
            for path, (old, new) in changes.items()
        ),
    )
    return group


def _logged_changes_unchanged(changes: Mapping[Path, tuple[bytes, bytes]]) -> None:
    """ValueError when a file is not as it was read."""
    for path, (old, _) in changes.items():
        if path.read_bytes() != old:
            raise ValueError(
                f"{path.name} changed since it was read, so nothing was written: run the command again"
            )


def _write_logged_changes(
    changes: Mapping[Path, tuple[bytes, bytes]], log: Path, write_log: Callable[[], object]
) -> None:
    """Log the undo with `write_log`, then swap each file from its old bytes to its new ones; a file that is not as
    it was read, or any failure, puts every file and `log` back as they were."""
    log_before = log.read_bytes() if log.exists() else None
    write_log()
    swapped: list[Path] = []
    try:
        _logged_changes_unchanged(changes)
        for path, (_, new) in changes.items():
            common._swap_file(path, new)
            swapped.append(path)
    except BaseException:
        for path in swapped:
            common._swap_file(path, changes[path][0])
        if log_before is None:
            log.unlink(missing_ok=True)
        else:
            safe_io.replace_file(log, log_before)
        raise


def _synthesis_require_writable(changes: Mapping[Path, tuple[bytes, bytes]]) -> None:
    """ValueError naming the files of `changes` that cannot be written."""
    locked = [
        p.name for p in changes if not os.access(p, os.W_OK) or not os.access(p.parent, os.W_OK)
    ]
    if locked:
        raise ValueError(f"not writable: {', '.join(locked)}")


@dataclass(frozen=True)
class _StructurePlan:
    """What a `mem synthesis` structure command will write: the files with their old and new bytes, the output
    lines, the curation log and the function that logs the undo."""

    changes: dict[Path, tuple[bytes, bytes]]
    lines: list[str]
    log: Path
    write_log: Callable[[], object]


@dataclass(frozen=True)
class _StructureTarget:
    """The synthesis (and section, when given) a structure command acts on."""

    root: Path
    handle: str
    section: str | None
    path: Path
    today: datetime.date


@dataclass(frozen=True)
class _SectionEdit:
    """The new text of a synthesis after a section changed, the output lines, and how each member note changes."""

    old: str
    new: str
    lines: list[str]
    edit_note: Callable[[str, str], str]


def _structure_detach_plan(root: Path, note: str) -> _StructurePlan | None:
    """The plan to detach a note from its synthesis; None after an ambiguity message on stderr."""
    found = common.resolve_note(root, note)
    if isinstance(found, list):
        common._ambiguous(note, found)
        return None
    if found is None or found not in {p.resolve() for _, p in note_files._note_files(root)}:
        raise ValueError(f"no note {note}")
    rel = found.relative_to(root).as_posix()
    original = found.read_bytes()
    text = original.decode("utf-8")
    meta = note_files.split_frontmatter(text)[0]
    part = meta.get("part_of") if isinstance(meta, dict) else None
    if not isinstance(part, str):
        raise edit.NoteFormatError(f"{note_files._handle(rel)} is not part of a synthesis")
    return _StructurePlan(
        {found: (original, _detached(text, rel).encode("utf-8"))},
        [f"{note_files._handle(rel)}\tdetached from s:{part}"],
        root / records.CURATION_LOG,
        lambda: edit._log_note(root, found, rel, "detach"),
    )


def _structure_topic_ids(args: argparse.Namespace, root: Path) -> list[str]:
    """The topic ids of `mem synthesis topics`, each one known; ValueError otherwise."""
    topics = list(dict.fromkeys(t.strip() for t in args.topic_ids.split(",") if t.strip()))
    known = note_files.load_topics(root)
    if not topics:
        raise ValueError("at least one topic is required")
    for t in topics:
        if t not in known:
            raise ValueError(f"unknown topic '{t}': use an id from topics.yaml or add it there")
    return topics


def _structure_topic_clash(root: Path, handle: str, topics: Sequence[str]) -> None:
    """ValueError when another synthesis already covers one of `topics`."""
    for other in document.load(root / document.SYNTHESES_DIR):
        if (
            other.error is None
            and other.handle != handle
            and (clash := [t for t in topics if t in other.topics])
        ):
            raise ValueError(f"s:{other.handle} already covers the topic {clash[0]}")


def _structure_topics_plan(args: argparse.Namespace, target: _StructureTarget) -> _StructurePlan:
    if target.section is not None:
        raise ValueError("topics takes s:<handle>")
    topics = _structure_topic_ids(args, target.root)
    _structure_topic_clash(target.root, target.handle, topics)
    old, new = synthesis_edit.with_topics(target.path, topics, target.today)
    return _StructurePlan(
        {target.path: (old.encode("utf-8"), new.encode("utf-8"))},
        [f"s:{target.handle}\ttopics {', '.join(topics)}"],
        target.root / document.SYNTHESES_DIR / records.CURATION_LOG,
        lambda: records.log_before(document.Synthesis(target.path, target.handle), "topics"),
    )


def _structure_rename_edit(
    args: argparse.Namespace, target: _StructureTarget, members: Sequence[tuple[Path, str]]
) -> _SectionEdit:
    section = cast("str", target.section)
    old, new, new_section = synthesis_edit.renamed_section(
        target.path, section, args.heading, target.today
    )
    return _SectionEdit(
        old,
        new,
        [
            f"s:{target.handle}#{new_section}\trenamed from {section}",
            *[
                f"{note_files._handle(p.relative_to(target.root).as_posix())}\tpart of s:{target.handle}#{new_section}"
                for p, _ in members
            ],
        ],
        lambda text, rel: _renamed_part_of(text, rel, f"{target.handle}#{new_section}"),
    )


def _structure_remove_edit(
    target: _StructureTarget, members: Sequence[tuple[Path, str]]
) -> _SectionEdit:
    section = cast("str", target.section)
    old, new = synthesis_edit.without_section(target.path, section, target.today)
    ref = f"{target.handle}#{section}"
    return _SectionEdit(
        old,
        new,
        [
            f"s:{ref}\tremoved",
            *[
                f"{note_files._handle(p.relative_to(target.root).as_posix())}\tdetached from s:{ref}"
                for p, _ in members
            ],
        ],
        _detached,
    )


def _structure_section_plan(
    args: argparse.Namespace, target: _StructureTarget, action: str
) -> _StructurePlan:
    """The plan to rename or remove one section, with the member notes that follow it."""
    if target.section is None:
        raise ValueError(f"{action} takes s:<handle>#<section handle>")
    root = target.root
    members = _part_of_notes(root, f"{target.handle}#{target.section}")
    edit = (
        _structure_rename_edit(args, target, members)
        if action == "rename"
        else _structure_remove_edit(target, members)
    )
    changes = {target.path: (edit.old.encode("utf-8"), edit.new.encode("utf-8"))}
    for note, text in members:
        changes[note] = (
            text.encode("utf-8"),
            edit.edit_note(text, note.relative_to(root).as_posix()).encode("utf-8"),
        )
    return _StructurePlan(
        changes,
        edit.lines,
        root / records.CURATION_LOG,
        lambda: _log_group_ahead(root, changes, action),
    )


def _structure_plan(
    args: argparse.Namespace, root: Path, action: str, today: datetime.date
) -> _StructurePlan | None:
    """The plan of a structure command; None after a message on stderr."""
    if action == "detach":
        return _structure_detach_plan(root, args.note)
    handle, section = document.split_ref(args.target)
    path = document.path_of(root / document.SYNTHESES_DIR, handle)
    if path is None or not path.is_file():
        raise ValueError(f"no synthesis named {args.target}")
    target = _StructureTarget(root, handle, section, path, today)
    if action == "topics":
        return _structure_topics_plan(args, target)
    return _structure_section_plan(args, target, action)


def _structure_heading_refused(args: argparse.Namespace) -> int:
    """0 when the new heading may be written, else the exit code after a message on stderr."""
    if common._refuse_secret([args.heading]):
        return 4
    return common._check_terms([args.heading], "synthesis", getattr(args, "owner_approved", False))


def _structure_run(
    args: argparse.Namespace, root: Path, action: str, today: datetime.date
) -> tuple[int, list[str]]:
    """(exit code, output lines) after the files of the command were written; the lines only when the code is 0."""
    if action == "rename":
        refused = _structure_heading_refused(args)
        if refused:
            return refused, []
    plan = _structure_plan(args, root, action, today)
    if plan is None:
        return 2, []
    _synthesis_require_writable(plan.changes)
    _write_logged_changes(plan.changes, plan.log, plan.write_log)
    return 0, plan.lines


def _structure(args: argparse.Namespace) -> int:
    """`mem synthesis rename | remove | detach | topics`: one line per changed record, errors on stderr with exit 2."""
    root = args.root.resolve()
    action = args.synthesis_command
    try:
        code, lines = _structure_run(args, root, action, datetime.date.today())
    except (
        common.NewNoteError,
        OSError,
        ValueError,
        note_files.FrontmatterError,
        yaml.YAMLError,
    ) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if code != 0:
        return code
    print("\n".join(lines))
    common.log_usage(root, {"cmd": "synthesis", "action": action})
    return 0


@dataclass(frozen=True)
class _RefsPart:
    """One part of a synthesis with the reference changes proposed for it, each (line, unit, op, target)."""

    part: document.Section
    items: list[tuple[str, int, str, str]]
    folder: Path
    root: Path


@dataclass(frozen=True)
class _RefsPartOutcome:
    """What the proposals for one part came to: refused lines, the summary line (None when the part was refused as
    a whole), the units added and removed, and (old, new) text of the part when it changed."""

    refused: list[str]
    count_line: str | None
    added: int
    removed: int
    change: tuple[str, str] | None


@dataclass(frozen=True)
class _RefsOutcome:
    """What the proposals came to over the whole synthesis: its new text, the member notes to rewrite, one summary
    line per part, the refused lines and the totals."""

    new_file: str
    notes: dict[Path, tuple[bytes, bytes]]
    counts: list[str]
    refused: list[str]
    added: int
    removed: int


@dataclass(frozen=True)
class _RefsRun:
    """The result of `mem synthesis refs` before it prints: exit code, output lines, whether a file changed."""

    code: int
    lines: list[str]
    changed: bool


def _refs_target(target: str, folder: Path) -> tuple[str, Path] | None:
    """(handle, path) of the synthesis named; None after a message on stderr when there is none."""
    handle, section = document.split_ref(target)
    path = document.path_of(folder, handle)
    if path is None or not path.is_file():
        print(f"mem: no synthesis named {target}", file=sys.stderr)
        return None
    if section is not None:
        raise ValueError("refs takes s:<handle>")
    return handle, path


def _refs_read_file(file: str) -> str | None:
    """The proposal file; None after a message on stderr when it cannot be read."""
    try:
        return Path(file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mem: cannot read the file: {exc}", file=sys.stderr)
        return None


def _refs_parse_line(line: str) -> tuple[str, tuple[str, int, str, str]] | None:
    """(section handle, (line, unit, op, target)) of a proposal line; None when it is not one."""
    cells = [c.strip() for c in line.split("|", 2)]
    action = cells[2].split(None, 1) if len(cells) == _SETTLE_LOG_CELLS else []
    if not (
        len(cells) == _SETTLE_LOG_CELLS
        and cells[1].isdigit()
        and len(action) == _SETTLE_ACTION_WORDS
        and action[0] in {"add", "remove"}
    ):
        return None
    return cells[0], (line.strip(), int(cells[1]), action[0], action[1].strip())


def _refs_proposals(
    raw: str,
) -> tuple[dict[str, list[tuple[str, int, str, str]]], list[str]]:
    """The proposals of the file by section handle, and a refused line for each one that is malformed."""
    refused: list[str] = []
    by_part: dict[str, list[tuple[str, int, str, str]]] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parsed = _refs_parse_line(line)
        if parsed is None:
            refused.append(
                f"refused: {line.strip()}: not `<section> | <unit> | add|remove <target>`"
            )
            continue
        by_part.setdefault(parsed[0], []).append(parsed[1])
    return by_part, refused


def _refs_refusal(
    sections: Sequence[document.Section], name: str, part: document.Section | None
) -> str | None:
    """Why no reference may change in the part `name`; None when it may."""
    if name == document.SUMMARY:
        return "the Summary takes no references"
    if part is None:
        return f"no section {name!r}"
    if sum(1 for x in sections if x.handle == name) > 1:
        return f"the handle {name!r} is repeated: rename one heading first"
    return None


def _refs_attempt(unit: _RefsPart, picked: list[int]) -> tuple[str, list[str | None], str | None]:
    """The part's text with the picked proposals applied, the reason each was refused, and a problem with the
    result as a whole (None when it is sound)."""
    part = unit.part
    text, why_not = synthesis_edit.change_references(
        part.text,
        unit.folder,
        [(unit.items[i][1], unit.items[i][2], unit.items[i][3]) for i in picked],
    )
    if text == part.text:
        return text, why_not, None
    if units.without_references(text) != units.without_references(part.text):
        return (
            text,
            why_not,
            "the command would change a word of the part (a bug: nothing of it was written)",
        )
    if found := document.validate_section(text, unit.root):
        return text, why_not, "the part would fail its checks: " + "; ".join(found)
    return text, why_not, None


def _refs_resolve(unit: _RefsPart) -> tuple[str, list[str | None]]:
    """The part's new text and the reason each proposal was refused (None when applied)."""
    everyone = list(range(len(unit.items)))
    new, reasons, problem = _refs_attempt(unit, everyone)
    if problem:
        # One line that breaks the part is refused alone; the others are applied unit by unit.
        reasons, kept = list(reasons), []
        for i in everyone:
            if reasons[i] is not None:
                continue
            if (trial := _refs_attempt(unit, [*kept, i]))[2]:
                reasons[i] = trial[2]
            else:
                kept.append(i)
        new = _refs_attempt(unit, kept)[0]
    return new, reasons


def _refs_count(
    items: Sequence[tuple[str, int, str, str]], reasons: Sequence[str | None], op: str
) -> int:
    """How many proposals of kind `op` were applied."""
    return sum(1 for (_, _, o, _), r in zip(items, reasons, strict=False) if r is None and o == op)


def _refs_part_outcome(
    sections: Sequence[document.Section],
    handle: str,
    root: Path,
    name: str,
    items: list[tuple[str, int, str, str]],
) -> _RefsPartOutcome:
    part = {s.handle: s for s in sections}.get(name)
    why = _refs_refusal(sections, name, part)
    if why or part is None:  # `part` is None only when `why` is set
        return _RefsPartOutcome([f"refused: {line}: {why}" for line, *_ in items], None, 0, 0, None)
    new, reasons = _refs_resolve(_RefsPart(part, items, root / document.SYNTHESES_DIR, root))
    failed = [
        f"refused: {line}: {r}"
        for (line, *_), r in zip(items, reasons, strict=False)
        if r is not None
    ]
    added = _refs_count(items, reasons, "add")
    removed = _refs_count(items, reasons, "remove")
    return _RefsPartOutcome(
        failed,
        f"s:{handle}#{name}: added {added}, removed {removed}, refused {len(failed)}",
        added,
        removed,
        (part.text, new) if new != part.text else None,
    )


def _refs_note_edits(
    root: Path, handle: str, name: str, change: tuple[str, str]
) -> dict[Path, tuple[bytes, bytes]]:
    """The member notes of a changed part that were current and get the new `part_of_hash`."""
    old, new = change
    notes: dict[Path, tuple[bytes, bytes]] = {}
    for note, text in _part_of_notes(root, f"{handle}#{name}"):
        stored = (note_files.split_frontmatter(text)[0] or {}).get("part_of_hash")
        rel = note.relative_to(root).as_posix()
        new_fp = units.note_fingerprint(new, common._note_target(rel))
        if units.is_current(stored, old, common._note_target(rel)) and stored != new_fp:
            notes[note] = (
                text.encode("utf-8"),
                common._set_field(edit._lf(text, rel), "part_of_hash", new_fp).encode("utf-8"),
            )
    return notes


def _refs_collect(
    syn: document.Synthesis,
    handle: str,
    root: Path,
    by_part: dict[str, list[tuple[str, int, str, str]]],
    file_text: str,
) -> _RefsOutcome:
    """Apply the proposals part by part, in order, to the text of the synthesis."""
    outcomes = []
    new_file = file_text
    notes: dict[Path, tuple[bytes, bytes]] = {}
    for name, items in by_part.items():
        outcome = _refs_part_outcome(syn.sections, handle, root, name, items)
        outcomes.append(outcome)
        if outcome.change is not None:
            new_file = synthesis_edit.apply_part_text(new_file, name, outcome.change[1])
            notes.update(_refs_note_edits(root, handle, name, outcome.change))
    return _RefsOutcome(
        new_file,
        notes,
        [o.count_line for o in outcomes if o.count_line is not None],
        [line for o in outcomes for line in o.refused],
        sum(o.added for o in outcomes),
        sum(o.removed for o in outcomes),
    )


def _refs_write(
    path: Path, original: bytes, outcome: _RefsOutcome, root: Path, today: datetime.date
) -> None:
    """Write the synthesis and the member notes as one logged group."""
    changes = {
        path: (original, synthesis_edit.bumped(outcome.new_file, today).encode("utf-8")),
        **outcome.notes,
    }
    _synthesis_require_writable(changes)
    _write_logged_changes(
        changes, root / records.CURATION_LOG, lambda: _log_group_ahead(root, changes, "refs")
    )


def _refs_run(args: argparse.Namespace, root: Path, today: datetime.date) -> _RefsRun:
    """Read the proposals, apply them and write the files; the lines are printed by the caller."""
    target = _refs_target(args.target, root / document.SYNTHESES_DIR)
    if target is None:
        return _RefsRun(1, [], False)
    handle, path = target
    raw = _refs_read_file(args.file)
    if raw is None:
        return _RefsRun(1, [], False)
    syn = document.load_one(path)
    if syn.error:
        raise ValueError(f"{path.name}: {syn.error}")
    original = path.read_bytes()
    file_text = original.decode("utf-8")
    edit._lf(file_text, path.name)
    by_part, malformed = _refs_proposals(raw)
    if not (by_part or malformed):
        print("mem: the file holds no proposal", file=sys.stderr)
        return _RefsRun(1, [], False)
    outcome = _refs_collect(syn, handle, root, by_part, file_text)
    changed = bool(outcome.added or outcome.removed)
    if changed:
        _refs_write(path, original, outcome, root, today)
    refused = [*malformed, *outcome.refused]
    summary = (
        f"s:{handle}: added {outcome.added}, removed {outcome.removed}, refused {len(refused)}"
    )
    return _RefsRun(0, [*outcome.counts, *refused, summary], changed)


def _refs(args: argparse.Namespace) -> int:
    """`mem synthesis refs s:<handle> --file F`: add or remove references by unit number and source target, never
    by text. Every changed part, and each member note that stays current, is written as one logged group."""
    root = args.root.resolve()
    try:
        run = _refs_run(args, root, datetime.date.today())
    except (
        common.NewNoteError,
        OSError,
        ValueError,
        note_files.FrontmatterError,
        yaml.YAMLError,
    ) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if run.code != 0:
        return run.code
    print("\n".join(run.lines))
    if run.changed:
        common.log_usage(root, {"cmd": "synthesis", "action": "refs"})
    return 0


def _detached(text: str, rel: str) -> str:
    """The note's text without `part_of` and `part_of_hash`."""
    return common._set_field(
        common._set_field(edit._lf(text, rel), "part_of", None), "part_of_hash", None
    )


def _renamed_part_of(text: str, rel: str, part_of: str) -> str:
    """The note's text with `part_of` set to `part_of`; `part_of_hash` stays, so a stale note stays listed."""
    return common._set_field(edit._lf(text, rel), "part_of", part_of)


@dataclass(frozen=True)
class _SectionNote:
    """The knowledge note that summarizes a section just added: its topics, origin, text and `part_of` link, and the
    section text its fingerprint stands for."""

    topics: list[str]
    origin: str
    body: str | None
    part_of: str
    cleaned: str


def _synthesis_note_origin(cleaned: str) -> str:
    """The origin of the note that summarizes a section, from the kinds of source the section cites."""
    kinds = document.source_kinds(cleaned)
    if kinds & {"literature", "url"}:
        return "literature"
    if "research" in kinds:
        return "research"
    return "experience" if "experience" in kinds else "literature"


def _synthesis_note_new(
    args: argparse.Namespace, root: Path, note: _SectionNote, today: datetime.date
) -> tuple[Path, bool]:
    """Create the note; (its path, whether its domain folder is new)."""
    known = note_files.load_topics(root)
    domain = (
        note_files.root_of(known, note.topics[0])
        if note.topics and note.topics[0] in known
        else None
    )
    created = not (root / "knowledge" / str(domain)).exists()
    target = edit.new_note(
        root,
        "knowledge",
        slug=args.note_slug,
        topics=note.topics,
        today=today,
        body=note.body,
        claim=args.note_claim,
        confidence=args.confidence,
        level=args.level,
        origin=note.origin,
        part_of=note.part_of,
        part_of_hash=units.fingerprint(note.cleaned),
    )
    return target, created


def _synthesis_note_checked(root: Path, target: Path, cleaned: str) -> str:
    """Stamp the note's `part_of_hash` and require that it has no check problem; returns its path."""
    rel = target.relative_to(root).as_posix()
    if (stamp := units.note_fingerprint(cleaned, common._note_target(rel))) != units.fingerprint(
        cleaned
    ):
        safe_io.replace_file(
            target,
            common._set_field(note_files._read_text(target), "part_of_hash", stamp).encode("utf-8"),
        )
    if found := [p for p in check_rules.check(root) if p.path == rel]:
        raise common.NewNoteError(
            f"the note has {len(found)} problems, so nothing was written: "
            + "; ".join(str(p) for p in found)
        )
    return rel


def _synthesis_note_discard(root: Path, target: Path, created: bool) -> None:
    """Remove the note of a failed add, with its domain folder when the add created it, and refresh the listings."""
    target.unlink(missing_ok=True)
    if created:
        shutil.rmtree(target.parent, ignore_errors=True)
    with contextlib.suppress(note_files.FrontmatterError, OSError):
        index_files.apply_index(root)


def _add_with_note(
    args: argparse.Namespace, path: Path, handle: str, body: str, today: datetime.date
) -> str:
    """The section and the knowledge note that summarizes it, both or neither; returns the note's path."""
    root = args.root
    syn = document.load_one(path)
    note_body = common._read_body(args.note_body_file)
    section_handle, _, cleaned = synthesis_edit.prepare_add(path, args.section, body, today)
    note = _SectionNote(
        topics=list(syn.topics),
        origin=args.origin or _synthesis_note_origin(cleaned),
        body=note_body,
        part_of=f"{handle}#{section_handle}",
        cleaned=cleaned,
    )
    undo = synthesis_edit.snapshot(path)
    synthesis_edit.add_section(path, args.section, body, today)
    target = None
    created = False
    try:
        target, created = _synthesis_note_new(args, root, note, today)
        rel = _synthesis_note_checked(root, target, cleaned)
    except Exception:
        if target is not None:
            _synthesis_note_discard(root, target, created)
        undo()
        raise
    return rel


def _synthesis_list(args: argparse.Namespace) -> int:
    """`mem synthesis list`: one line per synthesis, those of `--topic` and its descendants only."""
    listed = document.load(args.root / document.SYNTHESES_DIR)
    try:
        known = note_files.load_topics(args.root)
    except note_files.FrontmatterError:
        known = {}
    wanted = {args.topic, *note_files.descendants(known, args.topic)} if args.topic else None
    for syn in listed:
        if syn.error:
            print(f"mem: skipped {syn.path}: {syn.error}", file=sys.stderr)
        elif wanted is None or wanted & set(syn.topics):
            print(f"s:{syn.handle}\t{len(syn.parts)} parts, updated {syn.updated}\t{syn.title}")
    return 0


def _synthesis_handlers() -> dict[str, Callable[[argparse.Namespace], int]]:
    """The subcommands that read or restructure; any other one writes a synthesis or one of its parts."""
    return {
        "list": _synthesis_list,
        "attach": edit._attach,
        "rename": _structure,
        "remove": _structure,
        "detach": _structure,
        "topics": _structure,
        "refs": _refs,
    }


def _synthesis_one_call(args: argparse.Namespace, action: str) -> bool:
    """Whether `add` also writes the note that summarizes the section; the five options go together."""
    note_group = (
        [args.note_slug, args.note_claim, args.note_body_file, args.confidence, args.level]
        if action == "add"
        else []
    )
    one_call = any(note_group)
    if one_call and not all(note_group):
        raise common.UsageError(
            "--note-slug, --note-claim, --note-body-file, --confidence and --level go together"
        )
    return one_call


def _synthesis_new_topics(args: argparse.Namespace, root: Path) -> list[str]:
    """The topics of a new synthesis; ValueError when one is unknown, none is given or another synthesis covers one."""
    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    known = note_files.load_topics(root)
    if not topics:
        raise ValueError("at least one topic is required")
    for t in topics:
        if t not in known:
            raise ValueError(f"unknown topic '{t}': use an id from topics.yaml or add it there")
    for other in document.load(root / document.SYNTHESES_DIR):
        if other.error is None and (clash := [t for t in topics if t in other.topics]):
            raise ValueError(
                f"s:{other.handle} already covers the topic {clash[0]}; add a part to it."
            )
    return topics


def _synthesis_create(args: argparse.Namespace) -> int:
    """`mem synthesis new`: the file of a synthesis with its summary."""
    root = args.root
    topics = _synthesis_new_topics(args, root)
    summary = _synthesis_text(args.summary_file)
    if summary is None:
        return 1
    if common._refuse_secret([args.title, summary]):
        return 4
    approved = getattr(args, "owner_approved", False)
    if refused := common._check_terms([args.title, args.slug, summary], "synthesis", approved):
        return refused
    text = synthesis_edit.render_new(
        (common._TEMPLATES / "synthesis.md").read_text(encoding="utf-8"),
        title=args.title,
        topics=topics,
        summary=summary,
        today=datetime.date.today(),
    )
    path = synthesis_edit.create(root / document.SYNTHESES_DIR, args.slug, text)
    print(f"s:{path.stem}\t{path.relative_to(root).as_posix()}")
    return 0


@dataclass(frozen=True)
class _SynthesisWrite:
    """What a command that writes a part of a synthesis carries: the file, its handle, the part the reference names
    (None for `add`), the text and whether `add` also writes a note."""

    path: Path
    handle: str
    section: str | None
    body: str
    one_call: bool


def _synthesis_note_texts(args: argparse.Namespace, one_call: bool) -> list[str] | None:
    """The claim and the text of the note an `add` also writes ([] when it writes none); None when the text is unreadable."""
    if not one_call:
        return []
    note_body = _synthesis_text(args.note_body_file)
    return None if note_body is None else [args.note_claim, note_body]


def _synthesis_refused(args: argparse.Namespace, body: str, note_texts: list[str]) -> int:
    """0 when the texts may be written, else the exit code after a message on stderr."""
    heading = getattr(args, "section", None) or ""
    approved = getattr(args, "owner_approved", False)
    if common._refuse_secret([heading, body, *note_texts]):
        return 4
    if refused := common._check_terms([heading, body], "synthesis", approved):
        return refused
    if note_texts:
        return common._check_terms([*note_texts, args.note_slug], "note", approved)
    return 0


def _synthesis_require_valid_section(body: str, root: Path) -> None:
    """ValueError listing the problems of a section text; a blank text has none."""
    problems = document.validate_section(body, root) if body.strip() else []
    if problems:
        raise ValueError("; ".join(problems))


def _synthesis_section_of(args: argparse.Namespace, write: _SynthesisWrite) -> str:
    """The section the reference names; ValueError when `append` or `edit` got none."""
    if write.section is None:
        raise ValueError(f"{args.synthesis_command} takes s:<handle>#<section handle>")
    return write.section


def _synthesis_add(args: argparse.Namespace, write: _SynthesisWrite) -> str:
    """`mem synthesis add`: a new section, with its note in one call; returns the new section's handle."""
    if write.section is not None:
        raise ValueError("add takes s:<handle>, not a section")
    _synthesis_require_valid_section(write.body, args.root)
    today = datetime.date.today()
    note_rel = ""
    if write.one_call:
        note_rel = _add_with_note(args, write.path, write.handle, write.body, today)
        new_handle = document.section_handle(args.section)
    else:
        new_handle = synthesis_edit.add_section(write.path, args.section, write.body, today)
    print(f"s:{write.handle}#{new_handle}\tadded")
    if write.one_call:
        print(note_rel)
    return new_handle


def _synthesis_append(args: argparse.Namespace, write: _SynthesisWrite) -> str:
    """`mem synthesis append`: text added to a section; returns the section's handle."""
    section = _synthesis_section_of(args, write)
    synthesis_edit.append_section(
        write.path, section, write.body, datetime.date.today(), store=args.root
    )
    print(f"s:{write.handle}#{section}\tappended")
    return section


def _synthesis_edit(args: argparse.Namespace, write: _SynthesisWrite) -> str:
    """`mem synthesis edit`: a section's text replaced; returns the section's handle."""
    section = _synthesis_section_of(args, write)
    if section != document.SUMMARY:
        _synthesis_require_valid_section(write.body, args.root)
    synthesis_edit.edit_section(
        write.path,
        section,
        write.body,
        datetime.date.today(),
        shrink=args.shrink,
        drop_references=args.drop_references,
    )
    print(f"s:{write.handle}#{section}\tedited")
    return section


def _synthesis_part(args: argparse.Namespace, one_call: bool) -> int:
    """`mem synthesis add | append | edit`: the text of one part, checked before anything is written."""
    ref = args.target
    handle, section = document.split_ref(ref)
    path = document.path_of(args.root / document.SYNTHESES_DIR, handle)
    if path is None or not path.is_file():
        raise ValueError(f"no synthesis named {ref}")
    body = _synthesis_text(args.body_file)
    note_texts = _synthesis_note_texts(args, one_call) if body is not None else None
    if body is None or note_texts is None:
        return 1
    if refused := _synthesis_refused(args, body, note_texts):
        return refused
    write = _SynthesisWrite(path, handle, section, body, one_call)
    writers = {"add": _synthesis_add, "append": _synthesis_append}
    shown = writers.get(args.synthesis_command, _synthesis_edit)(args, write)
    _long_note(handle, path, shown)
    return 0


def parser_links(synthesis_sub: Any) -> None:
    """The `refs`, `topics` and `list` subcommands of `mem synthesis`."""
    syn_refs = synthesis_sub.add_parser(
        "refs", help="add or remove inline note references from a file of proposals"
    )
    syn_refs.add_argument("target", metavar="s:HANDLE")
    syn_refs.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="one proposal per line: SECTION | UNIT | add TARGET  or  SECTION | UNIT | remove TARGET",
    )
    syn_topics = synthesis_sub.add_parser("topics", help="replace a synthesis's topics")
    syn_topics.add_argument("target", metavar="s:HANDLE")
    syn_topics.add_argument("topic_ids", metavar="TOPICS", help="comma-separated topic ids")
    syn_list = synthesis_sub.add_parser("list", help="one line per synthesis")
    syn_list.add_argument("--topic")


def cmd_synthesis(args: argparse.Namespace) -> int:
    handler = _synthesis_handlers().get(args.synthesis_command)
    if handler is not None:
        return handler(args)
    action = args.synthesis_command
    one_call = _synthesis_one_call(args, action)
    try:
        code = _synthesis_create(args) if action == "new" else _synthesis_part(args, one_call)
    except (
        ValueError,
        OSError,
        note_files.FrontmatterError,
        yaml.YAMLError,
        common.NewNoteError,
    ) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    if code != 0:
        return code
    common.log_usage(args.root, {"cmd": "synthesis", "action": action})
    return 0


def parser_sections(synthesis_sub: Any, owner_approved: str) -> None:
    syn_append = synthesis_sub.add_parser(
        "append", help="add text at the end of a section, before its Sources line"
    )
    syn_append.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_append.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    syn_attach = synthesis_sub.add_parser(
        "attach", help="make a knowledge note the short recall of a section"
    )
    syn_attach.add_argument("note", metavar="NOTE")
    syn_attach.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_rename = synthesis_sub.add_parser(
        "rename", help="rename a section's heading; its notes follow"
    )
    syn_rename.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_rename.add_argument("heading", metavar="NEW_HEADING")
    syn_remove = synthesis_sub.add_parser(
        "remove", help="take a section out; its notes lose part_of"
    )
    syn_remove.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_detach = synthesis_sub.add_parser("detach", help="remove a note's part_of")
    syn_detach.add_argument("note", metavar="NOTE")
    syn_append.add_argument("--owner-approved", action="store_true", help=owner_approved)
    syn_rename.add_argument("--owner-approved", action="store_true", help=owner_approved)
