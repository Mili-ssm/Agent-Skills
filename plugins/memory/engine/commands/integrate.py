"""`mem synthesis integrate` (A3, A4): join knowledge notes to a part of a synthesis, all the rows of a file as one
logged, undoable group. No model text reaches the store: an appended sentence is the note's own claim, word for word,
plus its reference, so the secret and forbidden-term checks cannot be bypassed here."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from integrate.rows import check_claim, parse_rows
from memories import records
from notes import note as note_files
from syntheses import document, units
from syntheses import edit as synthesis_edit

from commands import common, edit
from commands import synthesis as synthesis_commands

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

    from integrate.rows import Row

_STATE_REFUSALS = (
    ("part_of", "already part of a synthesis"),
    ("superseded_by", "superseded"),
    ("disputed", "disputed"),
)
_DIGEST_LENGTH = 10


@dataclass
class IntegrateOutcome:
    """What `integrate` will write (each file with its old and new bytes), its output lines and how many rows it applied."""

    changes: dict[Path, tuple[bytes, bytes]]
    lines: list[str]
    applied: int


@dataclass
class _Part:
    """A part as it was read, and as the rows applied so far leave it."""

    path: Path
    original: bytes
    handle: str
    section: str
    old: str
    text: str
    count: int


@dataclass
class _Joined:
    """A note that joins a part: its path and bytes as read, its reference, and the part it goes to."""

    path: Path
    original: bytes
    rel: str
    part: _Part


@dataclass
class _Counts:
    appended: int = 0
    referenced: int = 0
    refused: int = 0


@dataclass
class _Build:
    root: Path
    env: Mapping[str, str]
    parts: dict[str, _Part | str] = field(default_factory=dict)
    joined: dict[Path, _Joined] = field(default_factory=dict)
    counts: dict[str, _Counts] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def _flat(text: object) -> str:
    return " ".join(str(text).split())


def _claim_of(meta: Mapping[str, Any]) -> str:
    """The note's claim on one line; empty when it is missing or not text."""
    claim = meta.get("claim")
    return _flat(claim) if isinstance(claim, str) else ""


def _state_refusal(meta: Mapping[str, Any]) -> str | None:
    """Why a note in this state cannot join a part, or None."""
    return next((reason for key, reason in _STATE_REFUSALS if meta.get(key) is not None), None)


def _is_knowledge_rel(rel: str) -> bool:
    """Whether the store-relative `rel` has the shape `knowledge/<topic>/<name>.md` that candidates list."""
    parts = rel.split("/")
    return (
        len(parts) == len(("knowledge", "topic", "name.md"))
        and parts[0] == "knowledge"
        and parts[2] != "README.md"
    )


def _target_of(rel: str) -> str:
    return common._note_target(rel)


def _read_part(root: Path, target: str) -> _Part:
    """The part `target` names as it was read; ValueError when it cannot take a note."""
    syn, sec = common._section_ref(root, target)
    original = syn.path.read_bytes()
    edit._lf(original.decode("utf-8"), syn.path.name)
    if sec.handle == document.SUMMARY or sum(s.handle == sec.handle for s in syn.sections) > 1:
        raise ValueError(f"the part {sec.handle!r} cannot take a note")
    count = len(units.units(sec.text)[0])
    return _Part(syn.path, original, syn.handle, sec.handle, sec.text, sec.text, count)


def _part_of_row(build: _Build, row: Row) -> _Part | str:
    """The part a row names as it was read, or why it cannot be read."""
    if row.target not in build.parts:
        try:
            build.parts[row.target] = _read_part(build.root, row.target)
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            build.parts[row.target] = str(exc)
    return build.parts[row.target]


def _find_note(root: Path, name: str) -> tuple[Path, str] | str:
    """(path, rel) of the knowledge note `name`, or why there is none."""
    found = common.resolve_note(root, name, prefix=False)
    if isinstance(found, list):
        return "ambiguous note"
    if found is None:
        return "no such note"
    rel = found.relative_to(root).as_posix()
    return (found, rel) if _is_knowledge_rel(rel) else "not a knowledge note"


def _note_of_row(build: _Build, row: Row) -> tuple[Path, str, dict[str, Any]] | str:
    """(path, rel, frontmatter) of the note a row names, or why it cannot join a part."""
    found = _find_note(build.root, row.note)
    if isinstance(found, str):
        return found
    path, rel = found
    meta = note_files.split_frontmatter(note_files._read_text(path))[0]
    if not isinstance(meta, dict):
        return "not a knowledge note"
    if path in build.joined:
        return "named twice in the file"
    return _state_refusal(meta) or (path, rel, meta)


def _new_text(build: _Build, row: Row, part: _Part, joined: tuple[str, str, str]) -> str:
    """The part's text after the row; ValueError with the reason when the row cannot be applied."""
    claim, stem, target = joined
    # Listed by target: the same note under another label is not listed twice.
    is_listed = f"({target})" in (synthesis_edit._sources_line(part.text) or "")
    sources = "" if is_listed else f"\n\nSources: [{stem}]({target})"
    if row.action == "append":
        if reason := check_claim(claim, build.env):
            raise ValueError(reason)
        return synthesis_edit.append_text(
            part.text, f"{claim} [{stem}]({target}){sources}", store=build.root
        )
    if row.unit is None or row.unit > part.count:
        raise ValueError(f"no such unit {row.unit}")
    # A reference can only name a note that the part's `Sources:` line lists: list it first.
    listed = (
        part.text if is_listed else synthesis_edit.append_text(part.text, sources, store=build.root)
    )
    new, why = synthesis_edit.change_references(
        listed, build.root / document.SYNTHESES_DIR, [(row.unit, "add", target)]
    )
    if why[0] is not None:
        raise ValueError(why[0])
    if found := document.validate_section(new, build.root):
        raise ValueError("; ".join(found))
    return new


def _apply_row(build: _Build, row: Row) -> str | None:
    """Apply one row to the working text of its part; the reason it is refused, or None."""
    part = _part_of_row(build, row)
    if isinstance(part, str):
        return part
    note = _note_of_row(build, row)
    if isinstance(note, str):
        return note
    path, rel, meta = note
    if not part.old or units.fingerprint(part.old) != row.fingerprint:
        return "part changed since it was read"
    if not (claim := _claim_of(meta)):
        return "claim is empty"
    try:
        new = _new_text(build, row, part, (claim, path.stem, _target_of(rel)))
    except ValueError as exc:
        return str(exc)
    part.text = new
    build.joined[path] = _Joined(path, path.read_bytes(), rel, part)
    return None


def _count(build: _Build, row: Row, reason: str | None) -> None:
    counts = build.counts.setdefault(row.target.partition("#")[0], _Counts())
    if reason is not None:
        counts.refused += 1
        build.lines.append(f"refused\t{row.note}\t{reason}")
        return
    if row.action == "append":
        counts.appended += 1
        label = "append"
    else:
        counts.referenced += 1
        label = f"unit {row.unit}"
    build.lines.append(f"applied\t{row.note}\t{row.target}\t{label}")


def _changes(build: _Build, today: datetime.date) -> dict[Path, tuple[bytes, bytes]]:
    """The synthesis files, the joined notes and the members of the changed parts, each with old and new bytes."""
    changes: dict[Path, tuple[bytes, bytes]] = {}
    files: dict[Path, tuple[bytes, str]] = {}
    changed = [p for p in build.parts.values() if isinstance(p, _Part) and p.text != p.old]
    for part in changed:
        _, text = files.get(part.path, (part.original, part.original.decode("utf-8")))
        files[part.path] = (
            part.original,
            synthesis_edit.apply_part_text(text, part.section, part.text),
        )
    for path, (original, text) in files.items():
        changes[path] = (original, synthesis_edit.bumped(text, today).encode("utf-8"))
    for part in changed:
        changes.update(
            synthesis_commands._refs_note_edits(
                build.root, part.handle, part.section, (part.old, part.text)
            )
        )
    for item in build.joined.values():
        text = edit._lf(item.original.decode("utf-8"), item.rel)
        stamp = units.note_fingerprint(item.part.text, _target_of(item.rel))
        part_of = f"{item.part.handle}#{item.part.section}"
        changes[item.path] = (item.original, edit._set_part_of(text, part_of, stamp).encode())
    return changes


def integrate_changes(
    root: Path, rows: list[Row], env: Mapping[str, str], today: datetime.date
) -> IntegrateOutcome:
    """Build in memory every change the rows make: the synthesis files once, each joined note with `part_of` and a
    `u:` stamp, and the members of a changed part re-stamped. Every row is judged against the part as it was read."""
    build = _Build(root, env)
    for row in rows:
        _count(build, row, _apply_row(build, row))
    for handle, c in build.counts.items():
        build.lines.append(
            f"{handle}: appended {c.appended}, referenced {c.referenced}, refused {c.refused}"
        )
    return IntegrateOutcome(_changes(build, today), build.lines, len(build.joined))


def _candidate_parts(syn: document.Synthesis) -> list[dict[str, Any]]:
    return [
        {
            "section": s.handle,
            "fingerprint": units.fingerprint(s.text),
            "units": [{"n": u.n, "text": u.text} for u in units.units(s.text)[0]],
        }
        for s in syn.sections
        if s.handle != document.SUMMARY and sum(x.handle == s.handle for x in syn.sections) == 1
    ]


def _loose_notes(root: Path) -> list[tuple[note_files.Note, list[str]]]:
    """Knowledge notes that are part of no synthesis, are not superseded or disputed, with their own topics."""
    try:
        known = note_files.load_topics(root)
    except note_files.FrontmatterError:
        known = {}
    found = []
    for note in note_files.discover_notes(root):
        if note.type != "knowledge" or note.error is not None or not isinstance(note.meta, dict):
            continue
        if _state_refusal(note.meta) or not _claim_of(note.meta) or not _is_knowledge_rel(note.rel):
            continue
        topics = [t for t in note.meta.get("topics", []) if isinstance(t, str)]
        found.append((note, edit._own_topics(known, topics)))
    return sorted(found, key=lambda item: note_files._handle(item[0].rel))


def candidates(root: Path) -> list[dict[str, Any]]:
    """Per synthesis, the loose notes its topics cover (a note only under the first synthesis) and its parts."""
    loose = _loose_notes(root)
    taken: set[str] = set()
    out = []
    for syn in document.load(root / document.SYNTHESES_DIR):
        if syn.error is not None:
            continue
        mine = [note for note, own in loose if note.rel not in taken and set(own) & set(syn.topics)]
        taken.update(note.rel for note in mine)
        if mine:
            out.append({
                "synthesis": syn.handle,
                "notes": [
                    {
                        "handle": note_files._handle(n.rel),
                        "claim": _claim_of(n.meta),
                        "digest": hashlib.sha256(n.path.read_bytes()).hexdigest()[:_DIGEST_LENGTH],
                    }
                    for n in mine
                ],
                "parts": _candidate_parts(syn),
            })
    return out


def _write(root: Path, changes: dict[Path, tuple[bytes, bytes]]) -> str:
    """Write the changes as one logged group; its id."""
    group: list[str] = []
    synthesis_commands._synthesis_require_writable(changes)
    synthesis_commands._write_logged_changes(
        changes,
        root / records.CURATION_LOG,
        lambda: group.append(synthesis_commands._log_group_ahead(root, changes, "integrate")),
    )
    return group[0]


def _run(args: argparse.Namespace, root: Path) -> int:
    if args.candidates:
        print(json.dumps(candidates(root), ensure_ascii=False))
        return 0
    rows, bad = parse_rows(Path(args.file).read_text(encoding="utf-8"))
    if bad:
        print("\n".join(f"mem: {m}" for m in bad), file=sys.stderr)
        return 2
    if not rows:
        print("no rows")
        return 0
    outcome = integrate_changes(root, rows, os.environ, datetime.date.today())
    group = _write(root, outcome.changes) if outcome.applied else None
    print("\n".join(outcome.lines))
    if group is not None:
        print(f"group\t{group}")
        common.log_usage(root, {"cmd": "synthesis", "action": "integrate"})
    return 0


def _integrate(args: argparse.Namespace) -> int:
    """`mem synthesis integrate FILE` or `--candidates`; 0 when the file parsed, 2 on a usage or store error."""
    if bool(args.file) == bool(args.candidates):
        print("mem: give a rows file or --candidates, not both", file=sys.stderr)
        return 2
    try:
        return _run(args, args.root.resolve())
    except (
        common.NewNoteError,
        OSError,
        UnicodeDecodeError,
        ValueError,
        note_files.FrontmatterError,
        yaml.YAMLError,
    ) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2


def register(synthesis_sub: Any) -> None:
    """Add `integrate` to the `mem synthesis` subcommands. The handler is set on the subparser, not in the
    synthesis dispatch table: that module cannot import this one, which imports it."""
    parser = synthesis_sub.add_parser(
        "integrate", help="join knowledge notes to parts of a synthesis from a file of rows"
    )
    parser.add_argument(
        "file",
        nargs="?",
        metavar="FILE",
        help="one row per line: NOTE | s:HANDLE#SECTION | append | FINGERPRINT  or  NOTE | s:HANDLE#SECTION | unit N | FINGERPRINT",
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="print as JSON the notes each synthesis could take and its parts, instead of reading rows",
    )
    parser.set_defaults(func=_integrate)
