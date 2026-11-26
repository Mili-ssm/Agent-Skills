#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.15"  # an upper bound: a newer Python may have no prebuilt pyyaml yet
# dependencies = ["pyyaml"]
# ///
"""Memory engine: parsing primitives and the mem commands."""

from __future__ import annotations

import argparse
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
from commands import admin, common, curate, edit, hooks, memory, read, sources
from core import config, safe_io
from memories import matching, records, rules
from notes import check as check_rules
from notes import due as due_queries
from notes import fields as note_fields
from notes import index as index_files
from notes import links as link_rules
from notes import note as note_files
from notes import search as note_search
from notes.check import (
    check,
)
from notes.fields import (
    LEVELS,
)
from notes.index import (
    INDEX_FOLDERS,
)
from notes.note import (
    FrontmatterError,
    descendants,
    load_topics,
    root_of,
    split_frontmatter,
)
from syntheses import document, units
from syntheses import edit as synthesis_edit
from syntheses import project as project_syntheses

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


# Names that live in check, fields, links, due, notes and index; callers may still read them from `mem`.
# Each maps to the one module that defines it; `_MOVED_MODULES` holds the already-imported module objects
# (no `importlib`: the import graph test bans it).
_MOVED_MODULES = {
    "commands.common": common,
    "commands.curate": curate,
    "commands.edit": edit,
    "commands.hooks": hooks,
    "commands.memory": memory,
    "commands.read": read,
    "commands.sources": sources,
    "memories.matching": matching,
    "notes.check": check_rules,
    "notes.due": due_queries,
    "notes.fields": note_fields,
    "notes.index": index_files,
    "notes.links": link_rules,
    "notes.note": note_files,
    "notes.search": note_search,
}
_MOVED: dict[str, str] = {
    "BASELINE_HEADING": "notes.check",
    "EXPERIMENT_DIRS": "notes.check",
    "HubLoader": "notes.note",
    "INDEX_END": "notes.index",
    "INDEX_START": "notes.index",
    "IndexTarget": "notes.index",
    "MAX_KNOWLEDGE_NAME": "notes.check",
    "MAX_FILE_BYTES": "notes.check",
    "MODEL_SPECIFIC_ROOT": "notes.due",
    "NO_STORE": "commands.common",
    "NewNoteError": "commands.common",
    "Note": "notes.note",
    "PAIR_WORK": "commands.hooks",
    "RELATIONS": "notes.search",
    "REQUIRED_HEADINGS": "notes.check",
    "REREAD_DAYS": "notes.due",
    "RESERVED_TOPIC": "notes.check",
    "RETEST_DAYS": "notes.due",
    "RULES": "notes.check",
    "Validator": "notes.fields",
    "_CODE_SPAN": "notes.links",
    "_CONCRETE_ID": "notes.due",
    "_DATE": "notes.fields",
    "_DISPUTE_KEYS": "notes.fields",
    "_DOMAIN_PURPOSE": "notes.index",
    "_DROPPED_TAGS": "notes.note",
    "_FENCE": "notes.links",
    "_IMPERATIVES": "notes.fields",
    "_INDEX_COLUMNS": "notes.index",
    "_INDEX_LIMIT": "commands.hooks",
    "_INDEX_RULES": "commands.hooks",
    "_INSTRUCTION_FIX": "notes.fields",
    "_INTENT_ID": "notes.due",
    "_LINK": "notes.links",
    "_LOCAL_DIRS": "notes.check",
    "_LONG_NAME_FIX": "notes.check",
    "_MONTH": "notes.fields",
    "_NAME_FIX": "notes.check",
    "_PART_OF": "notes.fields",
    "_REFDEF": "notes.links",
    "_REQUIREMENTS": "notes.due",
    "_SCHEME": "notes.links",
    "_STATUS_LINE": "commands.hooks",
    "_TOPIC_ID": "notes.check",
    "_UNTRACKED_DIRS": "notes.check",
    "_USER_AGENT": "commands.sources",
    "_authors": "notes.fields",
    "_blank": "notes.links",
    "_cell": "notes.index",
    "_changed_since": "commands.curate",
    "_check_terms": "commands.common",
    "_count_notes": "commands.hooks",
    "_date": "notes.fields",
    "_decisions": "commands.curate",
    "_disputed": "notes.fields",
    "_domain_notes": "notes.index",
    "_download": "commands.sources",
    "_edited_note_text": "commands.edit",
    "_enum": "notes.fields",
    "_fill_attempts": "commands.common",
    "_handle": "notes.note",
    "_handle_list": "notes.fields",
    "_handle_value": "notes.fields",
    "_has_committable_file": "notes.check",
    "_heading_problems": "notes.check",
    "_in_fence": "notes.links",
    "_index_cells": "notes.index",
    "_index_files": "commands.edit",
    "_index_row": "notes.index",
    "_indexable": "notes.index",
    "_is_hidden": "notes.note",
    "_is_index_readme": "notes.links",
    "_iso_date": "notes.due",
    "_markdown_files": "notes.links",
    "_marks_file": "commands.curate",
    "_matching_notes": "notes.search",
    "_mention_pattern": "notes.search",
    "_month": "notes.fields",
    "_no_duplicate_keys": "notes.note",
    "_nonempty_dir": "notes.check",
    "_note_files": "notes.note",
    "_parent": "notes.note",
    "_part_hash": "notes.fields",
    "_part_of": "notes.fields",
    "_read_note": "notes.note",
    "_read_text": "notes.note",
    "_relative_links": "notes.links",
    "_requirement_rows": "notes.due",
    "_rows_table": "notes.index",
    "_split_cells": "notes.due",
    "_starts_with_author": "notes.check",
    "_string": "notes.fields",
    "_strip_code": "notes.links",
    "_subtopics": "notes.index",
    "_swap_file": "commands.common",
    "_target_spans": "notes.links",
    "_topic_line": "notes.check",
    "_topics": "notes.fields",
    "_url": "notes.fields",
    "_visible": "notes.check",
    "_with_index": "notes.index",
    "_write_marks": "commands.curate",
    "_write_passes": "commands.curate",
    "_yaml_problem": "notes.note",
    "_year": "notes.fields",
    "ancestors": "notes.note",
    "apply_index": "notes.index",
    "build_corpus": "notes.search",
    "data_dir": "commands.common",
    "discover_notes": "notes.note",
    "find": "notes.search",
    "html_to_text": "commands.sources",
    "key_line": "notes.note",
    "leaf_topics": "notes.note",
    "load_yaml": "notes.note",
    "log_usage": "commands.common",
    "new_note": "commands.edit",
    "passages": "commands.read",
    "read_marks": "commands.curate",
    "read_passes": "commands.curate",
    "render_domain_index": "notes.index",
    "render_index": "notes.index",
    "resolve_note": "commands.common",
    "resolve_root": "commands.common",
    "rule_consistency": "notes.check",
    "root_topics": "notes.note",
    "rule_domain": "notes.check",
    "rule_file_size": "notes.check",
    "rule_flat": "notes.check",
    "rule_handles": "notes.check",
    "rule_index_fresh": "notes.check",
    "rule_links": "notes.links",
    "rule_names": "notes.check",
    "rule_placeholders": "notes.check",
    "rule_requirements": "notes.due",
    "rule_schema": "notes.check",
    "rule_supersession": "notes.check",
    "rule_syntheses": "notes.check",
    "rule_topics_file": "notes.check",
    "rule_topics_used": "notes.check",
    "search": "notes.search",
    "session_index": "commands.hooks",
    "short_handles": "commands.read",
    "signal_text": "commands.hooks",
    "slugify": "notes.note",
    "source_text": "commands.read",
    "tokenize": "memories.matching",
    "topic_tree": "commands.read",
    "unlinked_mentions": "notes.search",
}


def __getattr__(name: str) -> object:
    if module := _MOVED.get(name):
        return getattr(_MOVED_MODULES[module], name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_SETTLE_LOG_CELLS = 3  # `<section> | <unit> | add|remove <target>`
_SETTLE_ACTION_WORDS = 2  # `add|remove <target>`


_WRITE_COMMANDS = ("new", "note", "rename", "unify", "index", "fetch-sources", "import")
_SYNTHESIS_WRITES = (
    "new",
    "add",
    "edit",
    "append",
    "attach",
    "rename",
    "remove",
    "detach",
    "topics",
    "refs",
)
_NO_STORE_NEEDED = (
    "remember",
    "observe",
    "confirm",
    "refute",
    "supersede",
    "merge",
    "forget",
    "promote",
    "distinct",
    "restore",
    "triage",
    "memory",
    "memories",
    "curate",
    "settle",
    "session-index",
    "rules",
    "compact-log",
    "signal",
    "projects",
    "project-synthesis",
)


def store_source(cli_root: str | None, env: Mapping[str, str]) -> config.StoreSource | None:
    """Where the store path comes from: --root, MEM_STORE, the config file or the default store."""
    return config.store_source(cli_root, env)


# --- new -----------------------------------------------------------------------


DETAILS = ("paths", "titles", "facts", "snippet", "summary")


# --- rename --------------------------------------------------------------------


# --- unify ---------------------------------------------------------------------


# --- fetch-sources, import -----------------------------------------------------


# --- CLI ---------------------------------------------------------------------


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
            meta = split_frontmatter(text)[0]
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        if isinstance(meta, dict) and meta.get("part_of") == ref:
            found.append((path, text))
    return sorted(found)


def _log_group_ahead(root: Path, changes: Mapping[Path, tuple[bytes, bytes]], action: str) -> None:
    """The group entries `_log_group` writes, but before the files change: each holds the digest of the new bytes."""
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


def _logged_changes_unchanged(changes: Mapping[Path, tuple[bytes, bytes]]) -> None:
    """ValueError when a file is not as it was read."""
    for path, (old, _) in changes.items():
        if path.read_bytes() != old:
            raise ValueError(
                f"{path.name} changed since it was read, so nothing was written: run the command again"
            )


def _write_logged_changes(
    changes: Mapping[Path, tuple[bytes, bytes]], log: Path, write_log: Callable[[], None]
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
    write_log: Callable[[], None]


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
    meta = split_frontmatter(text)[0]
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
    known = load_topics(root)
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
    except (common.NewNoteError, OSError, ValueError, FrontmatterError, yaml.YAMLError) as exc:
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
        stored = (split_frontmatter(text)[0] or {}).get("part_of_hash")
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
    except (common.NewNoteError, OSError, ValueError, FrontmatterError, yaml.YAMLError) as exc:
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
    known = load_topics(root)
    domain = root_of(known, note.topics[0]) if note.topics and note.topics[0] in known else None
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
    if found := [p for p in check(root) if p.path == rel]:
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
    with contextlib.suppress(FrontmatterError, OSError):
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
        known = load_topics(args.root)
    except FrontmatterError:
        known = {}
    wanted = {args.topic, *descendants(known, args.topic)} if args.topic else None
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
    known = load_topics(root)
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


def cmd_synthesis(args: argparse.Namespace) -> int:
    handler = _synthesis_handlers().get(args.synthesis_command)
    if handler is not None:
        return handler(args)
    action = args.synthesis_command
    one_call = _synthesis_one_call(args, action)
    try:
        code = _synthesis_create(args) if action == "new" else _synthesis_part(args, one_call)
    except (ValueError, OSError, FrontmatterError, yaml.YAMLError, common.NewNoteError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    if code != 0:
        return code
    common.log_usage(args.root, {"cmd": "synthesis", "action": action})
    return 0


# --- note edit -----------------------------------------------------------------


def _today(value: str) -> datetime.date:
    if (date := due_queries._iso_date(value)) is None:
        raise argparse.ArgumentTypeError("use a real date as YYYY-MM-DD")
    return date


def _offset(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return n


def _limit(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


_KINDS = ("paper", "book", "article", "web", "talk", "repo", "dataset")
_CONFIDENCE = ("high", "medium", "low")
_ORIGINS = ("literature", "research", "experience")


_OWNER_APPROVED = "the owner agreed to a write that mentions a soft term: never add it on your own"


_USER_READ = (
    "with --short: the owner read this text, so it skips the code check and carries no mark; "
    "without it the short form is checked against the claim and marked as written by a model"
)


def _parser_add_search(sub: Any) -> None:
    check_parser = sub.add_parser("check", help="validate the hub rules")
    check_parser.add_argument(
        "paths", nargs="*", metavar="PATH", help="print only problems in these notes or folders"
    )
    check_parser.set_defaults(func=read.cmd_check)
    index_parser = sub.add_parser("index", help="regenerate the index blocks in the folder READMEs")
    index_parser.set_defaults(func=read.cmd_index)
    find_parser = sub.add_parser("find", help="list notes matching all filters")
    search_parser = sub.add_parser("search", help="rank notes by BM25 relevance to a query")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=_limit, default=10)
    search_parser.add_argument(
        "--offset", type=_offset, default=0, help="skip the first N results (default: 0)"
    )
    search_parser.add_argument(
        "--also",
        action="append",
        default=[],
        metavar="QUERY",
        help="another query over the same corpus (repeatable); each list is headed `== <query> ==`",
    )
    search_parser.add_argument(
        "--links",
        action="store_true",
        help="also list up to 10 notes linked to or from the first 10 printed results",
    )
    search_parser.add_argument(
        "--scope",
        choices=("all", "notes", "memories"),
        default="all",
        help="what to search: notes and memories (default), only notes, only memories",
    )
    search_parser.add_argument(
        "--deep",
        action="store_true",
        help="also rank source notes and investigations, and list syntheses "
        "(default: knowledge notes and memories)",
    )
    search_parser.add_argument(
        "--all-memories",
        action="store_true",
        help="also match refuted, superseded and expired memories",
    )
    search_parser.add_argument(
        "--project",
        action="append",
        default=[],
        metavar="NAME",
        help="also search this registered project's memories (repeatable; see mem projects list)",
    )
    search_parser.add_argument(
        "--all-projects",
        action="store_true",
        help="also search the memories of every registered project but the current one",
    )
    search_parser.set_defaults(func=read.cmd_search)
    for filtered in (find_parser, search_parser):
        filtered.add_argument("--type", choices=INDEX_FOLDERS)
        filtered.add_argument("--topic")
        filtered.add_argument("--kind", choices=_KINDS)
        filtered.add_argument("--status", choices=("idea", "active", "paused", "done", "abandoned"))
        filtered.add_argument("--confidence", choices=_CONFIDENCE)
        filtered.add_argument("--level", choices=LEVELS)
        filtered.add_argument(
            "--superseded", action="store_true", help="also list notes that a unified note replaced"
        )
        filtered.add_argument(
            "--handles",
            action="store_true",
            help="print a short handle in place of each path (accepted wherever a note is named)",
        )
        filtered.add_argument(
            "--detail",
            choices=DETAILS,
            default="titles",
            help="per result: path only, title, key facts, a matching line, or the lead section",
        )
    find_parser.add_argument(
        "--limit", type=_limit, default=50, help="print at most N notes (default: 50)"
    )
    find_parser.add_argument(
        "--offset", type=_offset, default=0, help="skip the first N notes (default: 0)"
    )
    find_parser.set_defaults(func=read.cmd_find)


def _parser_add_read(sub: Any) -> None:
    passages_parser = sub.add_parser(
        "passages", help="print the passages of a note's local source that best match"
    )
    passages_parser.add_argument("path", metavar="PATH")
    passages_parser.add_argument("query")
    passages_parser.add_argument(
        "--count", type=_limit, default=5, help="passages to print (default: 5)"
    )
    passages_parser.add_argument(
        "--words", type=_limit, default=500, help="words per passage (default: 500)"
    )
    passages_parser.set_defaults(func=read.cmd_passages)
    related_parser = sub.add_parser(
        "related", help="list a note's links, backlinks and most similar notes"
    )
    related_parser.add_argument("path", metavar="PATH")
    related_parser.add_argument(
        "--limit", type=_limit, default=5, help="print at most N similar notes (default: 5)"
    )
    related_parser.add_argument(
        "--detail",
        choices=DETAILS,
        default="titles",
        help="per result: path only, title, key facts, a matching line, or the lead section",
    )
    related_parser.add_argument(
        "--superseded", action="store_true", help="also list notes that a unified note replaced"
    )
    related_parser.add_argument(
        "--unlinked-mentions",
        action="store_true",
        help="print only the notes that name this one in their text without linking to it",
    )
    related_parser.set_defaults(func=read.cmd_related)
    show_parser = sub.add_parser("show", aliases=["read"], help="print chosen sections of notes")
    show_parser.add_argument("paths", nargs="+", metavar="PATH")
    show_parser.add_argument(
        "--section", action="append", help="a `## ` section to print (repeatable)"
    )
    show_parser.add_argument(
        "--outline", action="store_true", help="list headings with line numbers"
    )
    show_parser.add_argument(
        "--ranges",
        action="store_true",
        help="with --outline: print start-end lines and word count per heading",
    )
    show_parser.add_argument(
        "--all", action="store_true", help="a synthesis: print the whole file, not its outline"
    )
    show_parser.add_argument(
        "--project", metavar="NAME", help="read a memory of this registered project"
    )
    show_parser.add_argument(
        "--stored",
        action="store_true",
        help="a synthesis: print each reference as stored, not as `[n]`, the place of its note on the `Sources:` line",
    )
    show_parser.set_defaults(func=read.cmd_show)
    topics_parser = sub.add_parser("topics", help="print the topic tree with note counts")
    topics_parser.add_argument(
        "topic", nargs="?", metavar="ID", help="print only this topic's subtree"
    )
    topics_parser.set_defaults(func=read.cmd_topics)
    stats_parser = sub.add_parser("stats", help="print note, topic and size counts")
    stats_parser.add_argument(
        "--orphans", action="store_true", help="list notes no other file links to"
    )
    stats_parser.add_argument(
        "paths", nargs="*", metavar="PATH", help="with --orphans: only these notes or folders"
    )
    stats_parser.set_defaults(func=read.cmd_stats)
    review_parser = sub.add_parser(
        "review",
        help="list concrete requirements due for review and notes due for re-testing or re-reading",
    )
    review_parser.add_argument(
        "--today", type=_today, default=None, help="YYYY-MM-DD (default: today)"
    )
    review_parser.set_defaults(func=read.cmd_review)


def _parser_add_sources(sub: Any) -> None:
    fetch_parser = sub.add_parser(
        "fetch-sources", help="download literature note urls into .sources/"
    )
    fetch_parser.add_argument("paths", nargs="*", metavar="PATH")
    fetch_parser.add_argument("--force", action="store_true", help="refetch notes already cached")
    fetch_parser.add_argument(
        "--text-only",
        action="store_true",
        help="no download: write source.txt in cached folders that hold no .txt",
    )
    fetch_parser.set_defaults(func=sources.cmd_fetch_sources)
    eval_parser = sub.add_parser("search-eval", help="measure search recall on docs/search-eval.md")
    eval_parser.add_argument(
        "--min",
        type=float,
        help="exit 1 when recall@10 is below this (replaces the default revisit triggers)",
    )
    eval_parser.set_defaults(func=read.cmd_search_eval)
    rename_parser = sub.add_parser(
        "rename", help="rename a note in its folder and rewrite the links to it"
    )
    rename_parser.add_argument("note", metavar="NOTE")
    rename_parser.add_argument("new_stem", metavar="NEW-STEM", help="the new file name without .md")
    rename_parser.set_defaults(func=edit.cmd_rename)


def _parser_add_note(sub: Any) -> None:
    note_parser = sub.add_parser(
        "note", help="change a note through mem, never by editing its file"
    )
    note_sub = note_parser.add_subparsers(dest="note_command", required=True)
    note_edit = note_sub.add_parser(
        "edit", help="replace the text of one section, the claim or the topics of a note"
    )
    note_edit.add_argument("note", metavar="NOTE", help="a path or a handle, as in mem show")
    note_edit.add_argument(
        "--section", metavar="HEADING", help="the `## ` heading whose text is replaced"
    )
    note_edit.add_argument(
        "--body-file", metavar="PATH", help="the new section text; - reads standard input"
    )
    note_edit.add_argument(
        "--claim", metavar="TEXT", help="the new frontmatter claim (one sentence)"
    )
    note_edit.add_argument(
        "--topics", metavar="A,B", help="the new topic ids: in topics.yaml, in the note's domain"
    )
    note_edit.add_argument(
        "--shrink",
        action="store_true",
        help="accept a text that drops over 20%% of the words, a sentence or a link",
    )
    note_edit.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    note_parser.set_defaults(func=edit.cmd_note)
    for verb, what in (
        ("confirm", "append a source-confirmed line to the note's Evidence section"),
        ("dispute", "mark the note as contradicted by a source (the claim stays as it is)"),
    ):
        marked = note_sub.add_parser(verb, help=what)
        marked.add_argument(
            "note", metavar="NOTE", help="a path or a handle of a knowledge note, as in mem show"
        )
        marked.add_argument("--fact", metavar="TEXT", help="what the source says about the claim")
        marked.add_argument("--source", metavar="URL", help="the http(s) URL of the page")
        marked.add_argument("--quote", metavar="TEXT", help="the words of the page that show it")
        if verb == "dispute":
            marked.add_argument(
                "--clear", action="store_true", help="remove the mark: the owner settled it"
            )
        marked.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
        marked.set_defaults(func=edit.cmd_note_mark)


def _parser_add_import(sub: Any) -> None:
    import_parser = sub.add_parser(
        "import",
        help="copy the notes of another folder of notes into the store; the source is never changed",
    )
    import_parser.add_argument(
        "source",
        metavar="SOURCE",
        help="the folder to read (literature/, knowledge/, research/, topics.yaml)",
    )
    import_parser.add_argument(
        "--dry-run", action="store_true", help="change nothing; print the report a real run would"
    )
    import_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace files that differ (the old text goes to the curation log)",
    )
    import_parser.add_argument(
        "--with-sources", action="store_true", help="also copy the source's .sources/ folder"
    )
    import_parser.add_argument(
        "--research-data",
        action="store_true",
        help="also copy the data and code under research/ (by default only its Markdown files)",
    )
    import_parser.set_defaults(func=sources.cmd_import)
    unify_parser = sub.add_parser(
        "unify",
        help="replace several notes of one type with one, keeping the others as "
        "superseded files and pointing their links at it",
    )
    unify_parser.add_argument("keep", metavar="KEEP", help="the note that takes the unified text")
    unify_parser.add_argument("others", nargs="+", metavar="OTHER", help="notes that KEEP replaces")
    unify_parser.add_argument(
        "--body-file",
        required=True,
        metavar="PATH",
        help="the unified body (after the frontmatter); - reads standard input",
    )
    unify_parser.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    unify_parser.add_argument(
        "--drop", action="store_true", help="accept a unified text that lacks a link the notes had"
    )
    unify_parser.set_defaults(func=edit.cmd_unify)


def _parser_add_new(sub: Any) -> None:
    new_parser = sub.add_parser("new", help="create a note from its template")
    new_sub = new_parser.add_subparsers(dest="type", required=True)
    for note_type, flags in {
        "literature": {
            "title": {},
            "author": {},
            "year": {"type": int},
            "kind": {"choices": _KINDS},
            "level": {"choices": LEVELS},
            "url": {},
            "topics": {},
            "slug": {},
        },
        "knowledge": {
            "slug": {},
            "claim": {},
            "topics": {},
            "confidence": {"choices": _CONFIDENCE},
            "level": {"choices": LEVELS},
            "origin": {"choices": _ORIGINS},
        },
        "research": {"slug": {}, "title": {}, "question": {}, "topics": {}},
    }.items():
        type_parser = new_sub.add_parser(note_type)
        type_parser.add_argument(
            "--body-file",
            metavar="PATH",
            help="text (or - for standard input) that replaces the template body",
        )
        for flag, opts in flags.items():
            type_parser.add_argument(f"--{flag}", required=True, **opts)
        if note_type == "knowledge":
            type_parser.add_argument(
                "--part-of",
                metavar="s:HANDLE#SECTION",
                help="the synthesis section this note summarizes",
            )
        type_parser.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
        type_parser.set_defaults(func=edit.cmd_new)


def _parser_add_remember(sub: Any) -> None:
    remember_parser = sub.add_parser(
        "remember", help="write a memory in the project or, with --global, in the global folder"
    )
    remember_parser.add_argument("--kind", required=True, choices=records.KINDS)
    remember_parser.add_argument("--claim", required=True)
    remember_parser.add_argument(
        "--body-file", metavar="PATH", help="text (or - for standard input); may be empty"
    )
    remember_parser.add_argument("--context")
    remember_parser.add_argument(
        "--short",
        metavar="TEXT",
        help="the claim as one line of at most 120 characters, loaded at session start",
    )
    remember_parser.add_argument("--user-read", action="store_true", help=_USER_READ)
    remember_parser.add_argument(
        "--topic", metavar="TEXT", help="one or two lowercase words that group rules"
    )
    remember_parser.add_argument("--valid-until", type=_today, default=None, metavar="YYYY-MM-DD")
    remember_parser.add_argument("--source", action="append", default=[], metavar="URL_OR_PATH")
    remember_parser.add_argument(
        "--origin",
        choices=records.ORIGINS,
        help="where the claim came from when not a session: web (a finding), pipeline (a pipeline's write) "
        "or transcript (a lesson captured from a session transcript)",
    )
    remember_parser.add_argument(
        "--reach", choices=records.REACHES, help="how far the lesson reaches"
    )
    remember_parser.add_argument(
        "--weight",
        choices=records.WEIGHTS,
        help="how much it weighs: light needs 1 session to be established, medium 2, strong 3",
    )
    remember_parser.add_argument(
        "--outcome",
        choices=records.OUTCOMES,
        help="what the session showed about the lesson; recorded as a case of its log",
    )
    remember_parser.add_argument(
        "--seen-on",
        type=_today,
        default=None,
        metavar="YYYY-MM-DD",
        help="the day of the session, when it is not today",
    )
    remember_parser.add_argument("--global", dest="is_global", action="store_true")
    remember_parser.add_argument(
        "--force", action="store_true", help="write even when a memory has the same claim"
    )
    remember_parser.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    remember_parser.set_defaults(func=memory.cmd_remember)


def _parser_add_hooks(sub: Any) -> None:
    index_cmd = sub.add_parser(
        "session-index", help="print the text that opens a session: usage rules and counts"
    )
    index_cmd.add_argument(
        "--hook",
        action="store_true",
        help="read the hook's JSON from standard input (its cwd locates the project) and log the call",
    )
    index_cmd.add_argument(
        "--list",
        type=int,
        default=0,
        metavar="N",
        help="also list up to N of the project's newest memories",
    )
    index_cmd.set_defaults(func=hooks.cmd_session_index)
    compact_cmd = sub.add_parser(
        "compact-log", help="check the handoff block of a compaction summary and log counts"
    )
    compact_cmd.add_argument(
        "--hook", action="store_true", help="read the hook's JSON from standard input"
    )
    compact_cmd.set_defaults(func=hooks.cmd_compact_log)
    signal_cmd = sub.add_parser(
        "signal", help="print the records related to a brief read from standard input"
    )
    signal_cmd.add_argument(
        "--hook",
        action="store_true",
        help="read a PreToolUse hook's JSON from standard input and print the brief with the signal appended",
    )
    signal_cmd.set_defaults(func=hooks.cmd_signal)


def _parser_memory_command(
    sub: Any, name: str, help_text: str, *handles: str, because: bool = False
) -> argparse.ArgumentParser:
    cmd = sub.add_parser(name, help=help_text)
    for h in handles:
        cmd.add_argument(h, metavar="m:HANDLE")
    if because:
        cmd.add_argument(
            "--because", metavar="TEXT", help="the reason, appended to the memory's body"
        )
        cmd.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    cmd.add_argument(
        "--global",
        dest="is_global",
        action="store_true",
        help="act on the global memory when the handle exists in both scopes",
    )
    return cmd


def _parser_add_memory_marks(sub: Any) -> None:
    for name, text in (
        ("confirm", "count one more observation of a memory"),
        ("observe", "alias of confirm"),
    ):
        confirm_parser = _parser_memory_command(sub, name, text, "handle")
        confirm_parser.add_argument(
            "--until", metavar="YYYY-MM-DD", help="also set valid_until to this date"
        )
        confirm_parser.add_argument(
            "--source",
            metavar="'session ID'",
            help="another session shows it: add it as a source (exit 3 when already one)",
        )
        confirm_parser.add_argument(
            "--note", metavar="TEXT", help="with --source: a line added to the body"
        )
        confirm_parser.add_argument(
            "--outcome",
            choices=records.OUTCOMES,
            help="with --source: what that session showed about the lesson (default seen)",
        )
        confirm_parser.add_argument(
            "--seen-on",
            type=_today,
            default=None,
            metavar="YYYY-MM-DD",
            help="with --source: the day of that session (default today)",
        )
        confirm_parser.add_argument(
            "--by-owner",
            action="store_true",
            help="the owner vouches for a transcript lesson: it is established (exit 3 when already)",
        )
        confirm_parser.set_defaults(func=memory.cmd_confirm)
    _parser_memory_command(
        sub, "refute", "mark a memory refuted", "handle", because=True
    ).set_defaults(func=memory.cmd_refute)
    _parser_memory_command(
        sub, "forget", "mark a memory forgotten", "handle", because=True
    ).set_defaults(func=memory.cmd_forget)


def _parser_add_triage(sub: Any) -> None:
    triage_parser = sub.add_parser(
        "triage",
        help="decide what a corroborated general lesson becomes",
        description="Triage is deciding what a corroborated general lesson becomes: one seen in two projects leaves "
        "quarantine and waits here (mem curate --global lists it).",
    )
    triage_sub = triage_parser.add_subparsers(dest="triage_command", required=True)
    triage_hold = triage_sub.add_parser(
        "hold",
        help="keep a general lesson out of the rules until the owner decides",
        description="Hold: a global lesson is set to await triage, with the reason, and stops loading as a rule.",
    )
    triage_hold.add_argument("handle", metavar="m:HANDLE")
    triage_hold.add_argument(
        "--because", metavar="TEXT", help="why it is held (one line, at most 200 characters)"
    )
    for verb, text in (
        (
            "accept",
            "a general lesson that awaits triage stays a general lesson every project may read",
        ),
        (
            "reject",
            (
                "a general lesson that awaits triage is retired (mem restore brings it back), and "
                "its project records are marked so they are not promoted again"
            ),
        ),
    ):
        triage_verb = triage_sub.add_parser(
            verb, help=text, description=f"{verb.capitalize()}: {text}."
        )
        triage_verb.add_argument("handle", metavar="m:HANDLE")
        if verb == "accept":
            triage_verb.add_argument(
                "--project-scope",
                dest="project_scope",
                action="store_true",
                help="keep the wording of a project lesson that got worse",
            )
    triage_parser.set_defaults(func=memory.cmd_triage)


def _parser_add_memory_pairs(sub: Any) -> None:
    _parser_memory_command(
        sub, "supersede", "mark OLD as superseded by NEW", "old", "new"
    ).set_defaults(func=memory.cmd_supersede)
    merge_parser = _parser_memory_command(
        sub, "merge", "add DROP's count and body to KEEP and supersede DROP", "keep", "drop"
    )
    merge_parser.add_argument(
        "--force",
        action="store_true",
        help="merge although the claims differ by a negation or a number",
    )
    merge_parser.set_defaults(func=memory.cmd_merge)
    _parser_memory_command(
        sub,
        "distinct",
        "record that two memories are different claims: the queue stops pairing them",
        "a",
        "b",
    ).set_defaults(func=memory.cmd_distinct)
    _parser_memory_command(
        sub, "restore", "put back the text a memory had before its last curation action", "handle"
    ).set_defaults(func=memory.cmd_restore)
    promote_parser = sub.add_parser(
        "promote", help="print a draft of a global memory from project memories"
    )
    promote_parser.add_argument(
        "--no", action="store_true", help="record that the memory is not for a global note"
    )
    promote_parser.add_argument(
        "--done", action="store_true", help="record that the memory was promoted"
    )
    promote_parser.add_argument(
        "--to", metavar="m:HANDLE", help="with --done: the global memory it was promoted to"
    )
    promote_parser.add_argument("handles", nargs="+", metavar="m:HANDLE")
    promote_parser.set_defaults(func=memory.cmd_promote)


def _parser_add_memories(sub: Any) -> None:
    memories_parser = sub.add_parser("memories", help="list memories, newest first")
    curate_parser = sub.add_parser(
        "curate", help="list what needs a decision: pairs, expired, frequent, unconfirmed"
    )
    scope_group = memories_parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--global", dest="is_global", action="store_true", help="the global memories only"
    )
    scope_group.add_argument("--all", action="store_true", help="project and global memories")
    scope_group.add_argument(
        "--project", metavar="NAME", help="the memories of this registered project"
    )
    curate_scope = curate_parser.add_mutually_exclusive_group()
    curate_scope.add_argument(
        "--project", dest="is_project", action="store_true", help="the project's memories only"
    )
    curate_scope.add_argument(
        "--global", dest="is_global", action="store_true", help="the global memories only"
    )
    memories_parser.add_argument("--kind", choices=records.KINDS)
    memories_parser.add_argument(
        "--quarantine",
        action="store_true",
        help="only the global lessons in quarantine (not shown anywhere else until corroborated)",
    )
    memories_parser.add_argument(
        "--dead", action="store_true", help="also list refuted, superseded, forgotten and expired"
    )
    memories_parser.set_defaults(func=memory.cmd_memories)
    rules_parser = sub.add_parser(
        "rules", help="print the rules that load at session start; --more lists the rest"
    )
    rules_parser.add_argument(
        "--more",
        nargs="?",
        const=True,
        default=None,
        metavar="TOPIC",
        help="the lessons left out, grouped by topic; with TOPIC only that group (other: no topic)",
    )
    rules_parser.add_argument(
        "--layout",
        choices=rules.LAYOUTS,
        help="print the lessons flat or under a heading per topic (default: MEM_RULES_LAYOUT, else flat)",
    )
    rules_parser.add_argument(
        "--unread",
        action="store_true",
        help="list the short forms a model wrote that nobody read, with their claims",
    )
    rules_parser.add_argument(
        "--read",
        nargs="+",
        metavar="HANDLE",
        help="mark short forms as read: the handles, or all of those --unread lists",
    )
    rules_parser.set_defaults(func=memory.cmd_rules)
    curate_parser.add_argument(
        "--notes",
        action="store_true",
        help="list notes to attach to a synthesis part, and notes older than their part",
    )
    curate_parser.add_argument(
        "--done",
        action="store_true",
        help="record today as the date of the last pass over the scopes covered",
    )
    curate_parser.add_argument(
        "--new-since",
        type=float,
        metavar="EPOCH",
        help="print the number of global memories and notes written since EPOCH seconds (and since the last pass)",
    )
    curate_parser.add_argument(
        "action",
        nargs="?",
        choices=["apply"],
        help="apply: carry out the safe actions read from --from FILE or stdin (needs --safe)",
    )
    curate_parser.add_argument(
        "--safe",
        action="store_true",
        help="with apply: only merges of equal claims and attaches the part's Sources line backs",
    )
    curate_parser.add_argument(
        "--from",
        dest="from_file",
        metavar="FILE",
        help="with apply: the action lines (default or -: stdin)",
    )
    curate_parser.set_defaults(func=curate.cmd_curate)


def _parser_add_settle(sub: Any) -> None:
    settle_parser = sub.add_parser(
        "settle", help="settle new global memories against their look-alikes (verdicts from a file)"
    )
    settle_sub = settle_parser.add_subparsers(dest="settle_command", required=True)
    settle_pending = settle_sub.add_parser(
        "pending", help="list the look-alike pairs with a not yet judged side"
    )
    settle_pending.add_argument(
        "--json",
        action="store_true",
        help="a JSON list: pair, a, b, claim_a, claim_b, newer, flagged_words",
    )
    settle_apply = settle_sub.add_parser(
        "apply", help="carry out the verdicts the rules allow; refused rows are printed"
    )
    settle_apply.add_argument(
        "--verdicts",
        required=True,
        metavar="FILE",
        help='JSON list of {"a", "b", "decision": merge|supersede|distinct|nothing, "reason"}',
    )
    settle_log = settle_sub.add_parser("log", help="list the settlings not yet acknowledged")
    settle_log.add_argument(
        "--all", action="store_true", help="every settling, acknowledged and undone ones too"
    )
    settle_sub.add_parser("ack", help="mark every settling acknowledged")
    settle_undo = settle_sub.add_parser(
        "undo", help="undo settling N: both records back as they were"
    )
    settle_undo.add_argument("number", type=int, metavar="N")
    settle_due = settle_sub.add_parser(
        "due",
        help="exit 0 and print the count when new memories wait and the last apply is older than M minutes",
    )
    settle_due.add_argument("--minutes", type=float, required=True, metavar="M")
    settle_parser.set_defaults(func=memory.cmd_settle)


def _parser_add_project_synthesis(sub: Any) -> None:
    ps_parser = sub.add_parser(
        "project-synthesis",
        help="write, confirm and list the stamped parts of a project's syntheses",
    )
    ps_sub = ps_parser.add_subparsers(dest="ps_command", required=True)
    ps_add = ps_sub.add_parser(
        "add", help="write a part, or replace the one with the same heading; prints p:NAME#HANDLE"
    )
    ps_add.add_argument(
        "name", metavar="NAME", help="one of: " + ", ".join(project_syntheses.NAMES)
    )
    ps_add.add_argument("heading")
    ps_add.add_argument(
        "--paths", required=True, metavar="A,B", help="the project files or folders the part covers"
    )
    ps_add.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    ps_confirm = ps_sub.add_parser("confirm", help="stamp a part as checked today, text unchanged")
    ps_confirm.add_argument("part", metavar="p:NAME#HANDLE")
    ps_sub.add_parser("list", help="one line per part: handle, freshness, heading")
    ps_parser.set_defaults(func=cmd_project_synthesis)


def _parser_synthesis_write(synthesis_sub: Any) -> None:
    syn_new = synthesis_sub.add_parser("new", help="create syntheses/<slug>.md with its summary")
    syn_new.add_argument("--title", required=True)
    syn_new.add_argument("--topics", required=True, help="comma-separated topic ids")
    syn_new.add_argument("--slug", required=True)
    syn_new.add_argument(
        "--summary-file", metavar="PATH", help="the summary (or - for standard input)"
    )
    syn_add = synthesis_sub.add_parser(
        "add", help="append one section; its text must end with a `Sources:` line"
    )
    syn_add.add_argument("target", metavar="s:HANDLE")
    syn_add.add_argument("--section", required=True, metavar="HEADING")
    syn_add.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    syn_add.add_argument(
        "--note-slug",
        metavar="SLUG",
        help="also write a knowledge note that summarizes the section",
    )
    syn_add.add_argument("--note-claim", metavar="TEXT")
    syn_add.add_argument(
        "--note-body-file", metavar="PATH", help="the note's body (or - for standard input)"
    )
    syn_add.add_argument("--confidence", choices=_CONFIDENCE)
    syn_add.add_argument("--level", choices=LEVELS)
    syn_add.add_argument(
        "--origin", choices=_ORIGINS, help="default: taken from the section's Sources line"
    )
    syn_edit = synthesis_sub.add_parser(
        "edit", help="replace the text of one section; the rest of the file stays"
    )
    syn_edit.add_argument("target", metavar="s:HANDLE#SECTION")
    syn_edit.add_argument(
        "--body-file", required=True, metavar="PATH", help="the text (or - for standard input)"
    )
    syn_edit.add_argument(
        "--shrink", action="store_true", help="allow a text with fewer words or links than before"
    )
    syn_edit.add_argument(
        "--drop-references",
        action="store_true",
        help="allow a sentence kept unchanged to lose a reference (a note link in its body)",
    )
    syn_new.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    syn_add.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    syn_edit.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)


def _parser_synthesis_sections(synthesis_sub: Any) -> None:
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
    syn_append.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    syn_rename.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)


def _parser_synthesis_links(synthesis_sub: Any) -> None:
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


def _parser_add_synthesis(sub: Any) -> None:
    synthesis_parser = sub.add_parser(
        "synthesis", help="create and extend syntheses, the long documents behind notes"
    )
    synthesis_sub = synthesis_parser.add_subparsers(dest="synthesis_command", required=True)
    _parser_synthesis_write(synthesis_sub)
    _parser_synthesis_sections(synthesis_sub)
    _parser_synthesis_links(synthesis_sub)
    synthesis_parser.set_defaults(func=cmd_synthesis)


def _parser_add_registry(sub: Any) -> None:
    terms_parser = sub.add_parser(
        "terms", help="manage the terms that must not reach the global scope"
    )
    terms_sub = terms_parser.add_subparsers(dest="terms_command", required=True)
    terms_sub.add_parser("list", help="print hard<TAB>term and soft<TAB>term lines")
    terms_add = terms_sub.add_parser("add", help="add a term to the list")
    terms_add.add_argument("term")
    terms_add.add_argument(
        "--soft",
        action="store_true",
        help="a soft term: the owner must approve a write that holds it",
    )
    terms_add.add_argument(
        "--kind",
        choices=records.TERM_KINDS,
        help="with --soft: only for this kind of memory, or note or synthesis",
    )
    terms_remove = terms_sub.add_parser(
        "remove", help="remove every line that holds exactly this term"
    )
    terms_remove.add_argument("term")
    terms_parser.set_defaults(func=admin.cmd_terms)
    projects_parser = sub.add_parser(
        "projects", help="the local registry of projects whose memories can be searched"
    )
    projects_sub = projects_parser.add_subparsers(dest="projects_command", required=True)
    projects_sub.add_parser("list", help="one line per project: name, live memories, path")
    projects_add = projects_sub.add_parser("add", help="register a project by hand")
    projects_add.add_argument("path")
    projects_add.add_argument("--name")
    projects_remove = projects_sub.add_parser(
        "remove", help="forget a project; its files are not touched"
    )
    projects_remove.add_argument("name")
    projects_parser.set_defaults(func=admin.cmd_projects)
    init_parser = sub.add_parser(
        "init", help="make a folder a writable store (default: the default store)"
    )
    init_parser.add_argument("folder", metavar="FOLDER", nargs="?")
    init_parser.set_defaults(func=admin.cmd_init)


def _parser_add_history(sub: Any) -> None:
    history_parser = sub.add_parser("history", help="the store's git history: list, init, commit")
    history_parser.add_argument(
        "-n", type=int, default=10, metavar="N", help="how many commits to list"
    )
    history_sub = history_parser.add_subparsers(dest="history_command")
    history_init = history_sub.add_parser("init", help="make a writable store a git repository")
    history_init.add_argument("folder", metavar="STORE", nargs="?")
    history_commit = history_sub.add_parser("commit", help="commit what changed in the store")
    history_commit.add_argument("-m", dest="message", metavar="TEXT", help="the commit message")
    history_commit.add_argument(
        "--hook",
        action="store_true",
        help="the SessionEnd hook: a `session end` message, silent, always exit 0, log the call",
    )
    history_commit.add_argument(
        "--detached",
        action="store_true",
        help="with --hook: also log a `started` record before and a `done` one after, so a killed run shows",
    )
    history_parser.set_defaults(func=admin.cmd_history)


def _parser_add_memory_edit(sub: Any) -> None:
    memory_parser = sub.add_parser(
        "memory", help="change a memory through mem, never by editing its file"
    )
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_edit = memory_sub.add_parser(
        "edit", help="replace the claim, the context or the body of a memory"
    )
    memory_edit.add_argument("handle", metavar="m:HANDLE")
    memory_edit.add_argument("--claim", metavar="TEXT", help="the new claim (one sentence)")
    memory_edit.add_argument(
        "--context", metavar="TEXT", help="the new context; an empty text removes it"
    )
    memory_edit.add_argument(
        "--body-file", metavar="PATH", help="the new body; - reads standard input"
    )
    memory_edit.add_argument(
        "--short",
        metavar="TEXT",
        help="the one-line rule loaded at session start; an empty text removes it",
    )
    memory_edit.add_argument("--user-read", action="store_true", help=_USER_READ)
    memory_edit.add_argument(
        "--reworded",
        action="store_true",
        help="with --short: the automatic step wrote this text; marks the lesson as reworded",
    )
    memory_edit.add_argument(
        "--reword-failed",
        action="store_true",
        help="alone: note that the automatic rewording gave up on the last version",
    )
    memory_edit.add_argument(
        "--topic", metavar="TEXT", help="one or two lowercase words; an empty text removes it"
    )
    load_switch = memory_edit.add_mutually_exclusive_group()
    load_switch.add_argument(
        "--no-load", action="store_true", help="never load this lesson as a rule"
    )
    load_switch.add_argument(
        "--index-only",
        action="store_true",
        help="never load this lesson as a rule, but count it in the index line by topic",
    )
    load_switch.add_argument(
        "--load", action="store_true", help="remove --no-load and --index-only"
    )
    memory_edit.add_argument(
        "--shrink",
        action="store_true",
        help="accept a text that drops over 20%% of the words, a sentence or a link",
    )
    memory_edit.add_argument("--owner-approved", action="store_true", help=_OWNER_APPROVED)
    memory_edit.add_argument(
        "--global",
        dest="is_global",
        action="store_true",
        help="edit the global memory when the handle exists in both scopes",
    )
    memory_parser.set_defaults(func=memory.cmd_memory)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mem", description="Memory engine: search and read a store of notes."
    )
    parser.add_argument(
        "--root", default=None, help="store folder (default: $MEM_STORE, then the config file)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for add in (
        _parser_add_search,
        _parser_add_read,
        _parser_add_sources,
        _parser_add_note,
        _parser_add_import,
        _parser_add_new,
        _parser_add_remember,
        _parser_add_hooks,
        _parser_add_memory_marks,
        _parser_add_triage,
        _parser_add_memory_pairs,
        _parser_add_memories,
        _parser_add_settle,
        _parser_add_project_synthesis,
        _parser_add_synthesis,
        _parser_add_registry,
        _parser_add_history,
        _parser_add_memory_edit,
    ):
        add(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return _dispatch(argv)
    except safe_io.UnsafePath as exc:  # a symlink where a command refuses one
        print(f"mem: refused: {exc}", file=sys.stderr)
        return 2


def _no_store_folder(root: Path | None) -> bool:
    return root is None or not root.is_dir()


def _memories_need_no_store(args: argparse.Namespace, root: Path | None) -> bool:
    """True for a search of memories only, or a show of memory handles, when no store folder exists."""
    if args.command == "search":
        return args.scope == "memories" and _no_store_folder(root)
    if args.command == "show":
        return all(
            a.startswith(("m:", "p:")) or common._find_memory(args, a) for a in args.paths
        ) and _no_store_folder(root)
    return False


def _store_refusal(args: argparse.Namespace, root: Path | None) -> str | None:
    """The message that refuses `args.command` on this store, or None when the command may run."""
    if root is None:
        return common.no_store_message(os.environ)
    if root.exists() and not root.is_dir():
        return f"mem: the store is not a folder: {root}"
    if not root.is_dir():
        return f"mem: the store folder does not exist: {root}"
    writes = args.command in _WRITE_COMMANDS or (
        args.command == "synthesis" and args.synthesis_command in _SYNTHESIS_WRITES
    )
    if writes and not records.store_is_writable(root):
        return (
            f"mem: {args.command} writes to the store, which is read-only: it has no mem-store.yaml "
            '(create a store with "mem init").'
        )
    return None


def _dispatch_store(args: argparse.Namespace) -> int | None:
    """Resolve the store into `args.root`; the exit code of a refusal, or None to run the command."""
    if args.command in {
        "init",
        "terms",
        "history",
    }:  # history finds its own store: `history init` may name one
        return None
    if (
        args.command in _NO_STORE_NEEDED
    ):  # a project memory needs no store; a missing one is an error only where used
        args.root = common.resolve_root(args.root, os.environ)
        return None
    root = common.resolve_root(args.root, os.environ)
    if _memories_need_no_store(args, root):
        args.root = None  # memories need no store; only a project or a global folder
        return None
    refusal = _store_refusal(args, root)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    args.root_source = store_source(args.root, os.environ)
    args.root = root
    return None


def _dispatch(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "read":
        args.command = "show"
    if refusal := safe_io.sandbox_refusal(args.command, vars(args)):
        print(f"mem: {refusal}", file=sys.stderr)
        return 2
    try:
        code = _dispatch_store(args)
        return args.func(args) if code is None else code
    except (
        common.UsageError
    ) as exc:  # the parser's usage line and exit code 2, as argparse prints them
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
