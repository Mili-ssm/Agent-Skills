#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.15"  # an upper bound: a newer Python may have no prebuilt pyyaml yet
# dependencies = ["pyyaml"]
# ///
"""Memory engine: parsing primitives and the mem commands."""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import datetime
import io
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

import yaml
from capture import state as capture_state
from commands import admin, common, edit, read, sources
from core import auto_state, config, jobs, safe_io, store_git
from corroborate import decide as corroborate_decide
from digest import lessons as digest_lessons
from memories import model, records, rules
from memories.records import tokenize
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
    discover_notes,
    load_topics,
    root_of,
    split_frontmatter,
)
from session import handoff
from session import notices as session_notices
from settle import state as settle_state
from settle import verdicts as settle_verdicts
from syntheses import document, units
from syntheses import edit as synthesis_edit
from syntheses import project as project_syntheses

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

    from notes.note import (
        Note,
    )

# Names that live in check, fields, links, due, notes and index; callers may still read them from `mem`.
# Each maps to the one module that defines it; `_MOVED_MODULES` holds the already-imported module objects
# (no `importlib`: the import graph test bans it).
_MOVED_MODULES = {
    "commands.common": common,
    "commands.edit": edit,
    "commands.read": read,
    "commands.sources": sources,
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
    "_TOPIC_ID": "notes.check",
    "_UNTRACKED_DIRS": "notes.check",
    "_USER_AGENT": "commands.sources",
    "_authors": "notes.fields",
    "_blank": "notes.links",
    "_cell": "notes.index",
    "_check_terms": "commands.common",
    "_date": "notes.fields",
    "_disputed": "notes.fields",
    "_domain_notes": "notes.index",
    "_download": "commands.sources",
    "_edited_note_text": "commands.edit",
    "_enum": "notes.fields",
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
    "_yaml_problem": "notes.note",
    "_year": "notes.fields",
    "ancestors": "notes.note",
    "apply_index": "notes.index",
    "build_corpus": "notes.search",
    "data_dir": "commands.common",
    "find": "notes.search",
    "html_to_text": "commands.sources",
    "key_line": "notes.note",
    "leaf_topics": "notes.note",
    "load_yaml": "notes.note",
    "log_usage": "commands.common",
    "new_note": "commands.edit",
    "passages": "commands.read",
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
    "short_handles": "commands.read",
    "slugify": "notes.note",
    "source_text": "commands.read",
    "topic_tree": "commands.read",
    "unlinked_mentions": "notes.search",
}


def __getattr__(name: str) -> object:
    if module := _MOVED.get(name):
        return getattr(_MOVED_MODULES[module], name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


logger = logging.getLogger(__name__)


_CLAIM_PREVIEW_CHARS = 160  # a claim longer than this is cut in a listing
_CURATE_LINE_WORDS = 3  # `merge m:<keep> m:<drop>` and `attach <note> s:<h>#<section>`
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


def _register_project(project: Path | None) -> None:
    """Record the project in the local registry; never fails or prints, the command it follows has succeeded."""
    if project is None:
        return
    try:
        records.register_project(common.data_dir(os.environ), project, datetime.date.today())
    except Exception:
        logger.debug("registering the project failed", exc_info=True)


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
        body = _memory_body(args.body_file)
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


def _memory_body(source: str | None) -> str:
    """The text of `--body-file` (`-` is standard input); absent or empty gives an empty body."""
    if not source:
        return ""
    if source == "-":
        if sys.stdin.isatty():
            raise OSError("--body-file - needs the body on standard input, not a terminal")
        return sys.stdin.read().removeprefix("\ufeff").replace("\r\n", "\n")
    return Path(source).read_text(encoding="utf-8").replace("\r\n", "\n")


def _same_claim(a: str, b: str) -> bool:
    """Exact duplicate by word sequence in any script; claims with no word characters compare as stripped text."""
    wa, wb = re.findall(r"\w+", a.casefold()), re.findall(r"\w+", b.casefold())
    return wa == wb if wa or wb else a.strip() == b.strip()


_INDEX_HEAD = "memory: the mem command searches notes and memories (skill: memory)."
_INDEX_RULES = (
    _INDEX_HEAD + "\n"
    '- Before you act on this project, change something or research a topic: mem search "<topic in English>". '
    "It returns decisions, constraints and pitfalls recorded earlier that the files do not show.\n"
    "- To remember: preferences and personal matters -> auto memory; what a later session would need (a decision, "
    "constraint, pitfall or finding) -> mem remember, in English, with --global if it holds in any project and names "
    "no business; the project's current situation -> both."
)
# Only a project with a live state memory has written state for the status checker to read (ADR 0030).
_STATUS_LINE = (
    "- Resuming earlier work, or asked where things stand: dispatch memory:memory-status-checker "
    "before reading plans or the backlog yourself."
)
_INDEX_LIMIT = 1500
_CLAIM_LIMIT = 100


_SUPERSEDED_LINE = re.compile(r"^superseded_by:", re.MULTILINE)


def _is_superseded_file(path: Path) -> bool:
    """Whether the frontmatter at the top of the file has `superseded_by`; only the first 16 KB is read."""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            head = f.read(16384)
    except OSError:
        return False
    m = re.match(r"---\r?\n(.*?)\r?\n---", head, re.DOTALL)
    return m is not None and _SUPERSEDED_LINE.search(m.group(1)) is not None


def _count_notes(store: Path) -> int:
    """Notes by file name only: the index runs at every session start and must not read them."""
    try:
        files = [
            p
            for kind in ("literature", "knowledge")
            for p in store.glob(f"{kind}/*/*.md")
            if p.name != "README.md"
        ]
        files += list(store.glob("research/*/README.md"))
        return sum(1 for f in files if not _is_superseded_file(f))
    except OSError:
        return 0


def _readable(memories: Sequence[records.Memory], today: datetime.date) -> list[records.Memory]:
    """What a reader may be shown: live, and not a global lesson still in quarantine. The tools that corroborate or
    look a record up (the identical-claim check, handles, curate, the capture list) load unfiltered. `cmd_search`,
    `cmd_memories` and `cmd_signal` filter `records.quarantined` directly: the first two because `--all-memories` and
    `--dead` still show dead records, the third because it reads the folders itself and shows no liveness."""
    return [m for m in memories if records.is_live(m, today) and not records.quarantined(m)]


class SessionIndexOptions(TypedDict, total=False):
    """The keyword options of `session_index`; `tracked` defaults to an empty set, the rest to 0 or None."""

    limit: int
    passes: Mapping[str, datetime.date] | None
    notice: str | None
    stats: dict[str, int] | None
    marks: Mapping[str, frozenset[str]] | None
    tracked: frozenset[str] | None


@dataclasses.dataclass(frozen=True)
class _DueScan:
    """What the "Curation due" count of every folder shares."""

    today: datetime.date
    passes: Mapping[str, datetime.date] | None
    marks: Mapping[str, frozenset[str]] | None
    tracked: frozenset[str] | None
    budget: records.Budget  # one for both folders, the project's first (C101)


def _index_existing(store: Path | None, memories: Path | None) -> tuple[Path | None, Path | None]:
    """The store and the global folder, each None when it is not a folder."""
    try:
        has_store = store is not None and store.is_dir()
        has_memories = memories is not None and memories.is_dir()
    except OSError:
        return None, None
    return (store if has_store else None, memories if has_memories else None)


def _index_count_due(
    due: dict[str, int],
    folder: Path,
    loaded: list[records.Memory],
    root: Path | None,
    scan: _DueScan,
) -> bool:
    """Add the decision items of one folder to `due`; True when all its pairs were checked."""
    key = str(folder.resolve())
    found = _decisions(
        loaded,
        scan.today,
        since=(scan.passes or {}).get(key),
        budget=scan.budget,
        attempts=_fill_attempts(os.environ),
        root=root,
        tracked=scan.tracked,
    )
    known = (scan.marks or {}).get(key, frozenset())
    for k, label in found.keys().items():
        if k not in known:
            due[label] = due.get(label, 0) + 1
    return found.pairs_checked


def _index_add_due(
    due: dict[str, int],
    folder: Path,
    loaded: list[records.Memory],
    root: Path | None,
    scan: _DueScan,
) -> bool:
    """Like `_index_count_due`, but a failure leaves this folder out of the count (False): the rest prints."""
    try:
        return _index_count_due(due, folder, loaded, root, scan)
    except Exception:
        logger.debug("counting a store folder failed", exc_info=True)
        return False


def _index_due_counts(
    project: Path | None,
    loaded_project: list[records.Memory],
    memories: Path | None,
    loaded_global: list[records.Memory],
    scan: _DueScan,
) -> tuple[dict[str, int], bool]:
    """The decision items by label, and whether the count is complete; empty without `passes`."""
    due: dict[str, int] = {}
    complete = True
    if scan.passes is None:
        return due, complete
    if project is not None:
        complete = _index_add_due(due, project, loaded_project, project.parent, scan) and complete
    if memories is not None:
        complete = _index_add_due(due, memories, loaded_global, None, scan) and complete
    return due, complete


def _index_folder_lines(
    store: Path | None,
    memories: Path | None,
    loaded_global: list[records.Memory],
    today: datetime.date,
) -> list[str]:
    lines = []
    if store is not None:
        lines.append(f"Store: {_count_notes(store)} notes.")
    if memories is not None:
        lines.append(f"Global memories: {len(_readable(loaded_global, today))}.")
    return lines


def _index_due_line(due: dict[str, int], complete: bool) -> list[str]:
    total = sum(due.values())
    if not total:
        return []
    parts = ", ".join(
        f"{due[label]} {label}" for label in _DECISION_LABELS.values() if label in due
    )
    return [
        (
            f"Curation due: {'' if complete else 'at least '}{total} {'item' if total == 1 else 'items'} "
            f"({parts}) (after the current task: dispatch memory:memory-curator)."
        )
    ]


def _index_triage_line(loaded_global: list[records.Memory], today: datetime.date) -> list[str]:
    waiting = sum(1 for m in loaded_global if m.triage == "pending" and records.is_live(m, today))
    if not waiting:
        return []
    return [
        (
            f"Triage: {waiting} general lesson{' awaits' if waiting == 1 else 's await'} triage "
            "(mem curate --global)."
        )
    ]


def _index_choose_rules(
    loaded_project: list[records.Memory], loaded_global: list[records.Memory], today: datetime.date
) -> rules.Choice | None:
    try:
        return rules.choose(loaded_project, loaded_global, today)
    except Exception:
        logger.debug("loading the rules failed", exc_info=True)
        return None


def _index_worse_count(
    loaded_project: list[records.Memory],
    loaded_global: list[records.Memory],
    today: datetime.date,
    choice: rules.Choice,
) -> list[str]:
    worse = sum(
        1 for _, loaded in _got_worse(loaded_project, loaded_global, today, choice) if loaded
    )
    if not worse:
        return []
    return [
        f"Got worse: {worse} loaded lesson{' needs' if worse == 1 else 's need'} a decision (mem curate)."
    ]


def _index_worse_line(
    loaded_project: list[records.Memory],
    loaded_global: list[records.Memory],
    today: datetime.date,
    choice: rules.Choice | None,
) -> list[str]:
    """The "Got worse" line; nothing loads when the rules are off, so nothing "got worse after loading"."""
    if choice is None:
        return []
    try:
        return _index_worse_count(loaded_project, loaded_global, today, choice)
    except Exception:
        logger.debug("the session start usage tally failed", exc_info=True)
        return []


def _index_head_lines(mine: list[records.Memory], due: dict[str, int], complete: bool) -> list[str]:
    """The project count and the curation line, which sit between the folder counts and the triage line."""
    lines = [f"This project: {len(mine)} memories."] if mine else []
    return lines + _index_due_line(due, complete)


def _index_live_project(
    loaded_project: list[records.Memory], today: datetime.date
) -> list[records.Memory]:
    """The project's live memories, the current situation first, then the newest observed."""
    mine = [m for m in loaded_project if records.is_live(m, today)]
    mine.sort(key=lambda m: m.handle)  # stable sorts, least significant key first
    mine.sort(key=lambda m: m.created or datetime.date.min, reverse=True)
    mine.sort(key=lambda m: m.observed, reverse=True)
    mine.sort(key=lambda m: m.kind != "state")
    return mine


def _index_lines(
    head: list[str],
    mine: list[records.Memory],
    notice: str | None,
    store: Path | None,
    today: datetime.date,
) -> list[str]:
    """The head line, the rules, the status line, the notice and the store's due lines."""
    lines = [" ".join(head), *_INDEX_RULES.split("\n")[1:]]
    if any(m.kind == "state" for m in mine):
        lines.append(_STATUS_LINE)
    if notice:
        lines.append(notice)
    if store is not None:
        lines += session_notices.store_due_lines(store, today, common.data_dir(os.environ))
    return lines


def _index_rules_with_digest(
    choice: rules.Choice, layout: str, digest: dict | None, topics: dict | None
) -> list[str]:
    try:
        extra = rules.block(choice, layout, digest=digest, topics=topics)
        extra += rules.index_lines(choice, digest=digest, topics=topics)
    except Exception:  # a failure in the digest leaves the block without it
        logger.debug("the rules digest failed", exc_info=True)
        extra = rules.block(choice, "grouped" if layout == "digest" else layout)
        more = rules.more_line(choice)
        if more:
            extra.append(more)
    return extra


def _index_rules_lines(
    choice: rules.Choice,
    loaded_global: list[records.Memory],
    today: datetime.date,
    stats: dict[str, int] | None,
) -> list[str]:
    layout = _rules_layout()
    digest, topics = _rules_digest(loaded_global, today)
    extra = _index_rules_with_digest(choice, layout, digest, topics)
    if stats is not None:
        stats.update(
            rules=len(choice.loaded),
            rules_left=len(rules.not_fitted(choice)),
            rules_chars=len("\n".join(extra)),
        )
    return extra


def _index_rules_block(
    choice: rules.Choice | None,
    loaded_global: list[records.Memory],
    today: datetime.date,
    stats: dict[str, int] | None,
) -> list[str]:
    """The lessons that load as rules; `stats` receives their numbers. Empty when `choice` is None."""
    if choice is None:
        return []
    try:
        return _index_rules_lines(choice, loaded_global, today, stats)
    except Exception:
        logger.debug("the rules block failed", exc_info=True)
        return []


def _index_memory_rows(mine: list[records.Memory]) -> list[str]:
    rows = []
    for m in mine:
        claim = " ".join(m.claim.split())
        if len(claim) > _CLAIM_LIMIT:
            claim = claim[:_CLAIM_LIMIT] + "…"
        created = m.created.isoformat() if m.created else "undated"
        rows.append(f"  m:{m.handle} [{m.kind}, {created}] {claim}")
    return rows


def _index_fit(lines: list[str], extra: list[str], rows: list[str], limit: int) -> str:
    """The text with as many rows as fit `_INDEX_LIMIT` (the rules block does not count), at most `limit`."""
    shown = min(limit, len(rows))
    while True:
        tail = (
            [f'  … and {len(rows) - shown} more: mem search "<words>" --scope memories']
            if shown < len(rows)
            else []
        )
        text = "\n".join(lines + rows[:shown] + tail)
        if len(text) <= _INDEX_LIMIT or shown == 0:
            return "\n".join(lines + extra + rows[:shown] + tail)
        shown -= 1


def session_index(
    store: Path | None,
    project: Path | None,
    memories: Path | None,
    today: datetime.date,
    **options: Unpack[SessionIndexOptions],
) -> str:
    """Text for the start of a session: three generic lines with counts; the project's newest memories when limit > 0.

    `passes` (date of the last curation pass per resolved folder) turns on the "Curation due" count; None leaves it out.
    `marks` holds the decision keys each pass recorded (C100); the count is the keys of `_decisions` not in them.
    `notice` is one more line after the rules (the failure of the automatic curation run).
    The lessons that load as rules follow the notice; `stats`, when given, receives their numbers (rules, rules_left,
    rules_chars). `limit` and `_INDEX_LIMIT` apply to the text without them."""
    tracked = options.get("tracked", frozenset())
    stats = options.get("stats")
    store_dir, memories_dir = _index_existing(store, memories)
    loaded_global = records.load_memories(memories_dir, "global")
    loaded_project = records.mark_repository(records.load_memories(project, "project"), tracked)
    scan = _DueScan(
        today, options.get("passes"), options.get("marks"), tracked, records.Budget(PAIR_WORK)
    )
    due_counts = _index_due_counts(project, loaded_project, memories_dir, loaded_global, scan)
    mine = _index_live_project(loaded_project, today)
    rules_off = _rules_off()
    choice = None if rules_off else _index_choose_rules(loaded_project, loaded_global, today)
    head = [_INDEX_HEAD, *_index_folder_lines(store_dir, memories_dir, loaded_global, today)]
    head += _index_head_lines(mine, *due_counts)
    head += _index_triage_line(loaded_global, today)
    head += _index_worse_line(loaded_project, loaded_global, today, choice)
    lines = _index_lines(head, mine, options.get("notice"), store_dir, today)
    if rules_off and stats is not None:
        stats.update(rules=0, rules_left=0, rules_chars=0)
    extra = _index_rules_block(choice, loaded_global, today, stats)
    limit = options.get("limit", 0)
    if mine and limit > 0:
        return _index_fit(lines, extra, _index_memory_rows(mine), limit)
    return "\n".join(lines + extra)


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


def _hook_input() -> dict[str, Any]:
    """The hook's JSON from standard input; {} when it is missing or not an object."""
    try:
        if sys.stdin is None or sys.stdin.isatty():  # nothing piped: never wait for a terminal
            return {}
        data = json.load(sys.stdin)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _corroborate_failure_line(data: Path | None, now: float) -> str | None:
    """The line `mem session-index` adds after a failed corroboration pass (`mem-corroborate ack` clears it)."""
    if data is None:
        return None
    found = jobs.failure(jobs.read_json(data / "corroborate" / jobs.STATUS_NAME), now)
    if found is None:
        return None
    reason = " ".join(str(found["reason"]).split())[:200]
    return (
        f"memory: the last corroboration pass failed ({reason}): see mem-corroborate status, "
        "then mem-corroborate ack."
    )


@dataclasses.dataclass(frozen=True)
class _HookScope:
    """Where a hook runs: the store when it is a given path, the folder of the hook's `cwd`, the global folder."""

    store: Path | None
    cwd: Path
    memories: Path | None


def _hook_cwd(data: dict[str, Any]) -> Path:
    cwd = Path(data["cwd"]) if isinstance(data.get("cwd"), str) and data["cwd"] else Path.cwd()
    return cwd if cwd.is_dir() else Path.cwd()


def _hook_scope(args: argparse.Namespace, data: dict[str, Any]) -> _HookScope:
    store = args.root if isinstance(args.root, Path) else None
    cwd = _hook_cwd(data)
    memories = records.memories_root(
        os.environ, store if store is not None and store.is_dir() else None
    )
    return _HookScope(store, cwd, memories)


def _session_notice(make: Callable[[], str | None]) -> str | None:
    try:
        return make()
    except Exception:
        logger.debug("a session start notice failed", exc_info=True)
        return None


def _session_notices(store: Path | None, memories: Path | None) -> str | None:
    """The failure lines of the background runs, one per line; None when there are none."""
    notices = []
    for make in (
        lambda: auto_state.failure_line(common.data_dir(os.environ), store, time.time()),
        lambda: settle_state.failure_line(common.data_dir(os.environ), store, time.time()),
        lambda: capture_state.failure_line(common.data_dir(os.environ), time.time()),
        lambda: _corroborate_failure_line(common.data_dir(os.environ), time.time()),
        lambda: settle_state.settled_line(memories),
    ):
        found = _session_notice(make)
        if found:
            notices.append(found)
    return "\n".join(notices) or None


def _session_text(args: argparse.Namespace, data: dict[str, Any], stats: dict[str, int]) -> str:
    store = args.root if isinstance(args.root, Path) else None
    cwd = _hook_cwd(data)
    try:
        project = records.project_root(cwd, os.environ)
    except OSError:
        project = None
    memories = records.memories_root(
        os.environ, store if store is not None and store.is_dir() else None
    )
    notice = _session_notices(store, memories)
    return session_index(
        store,
        records.project_dir(project) if project else None,
        memories,
        datetime.date.today(),
        limit=max(args.list, 0),
        passes=read_passes(os.environ),
        notice=notice,
        stats=stats,
        marks=read_marks(os.environ),
        tracked=records.tracked_memories(project) if project else frozenset(),
    )


def cmd_session_index(args: argparse.Namespace) -> int:
    """Never fails: the rules matter most when nothing is configured yet. Writes only the hook log, with --hook,
    and the day's due-note count (session_notices.DUE_CACHE_NAME)."""
    started = time.monotonic()
    data = _hook_input() if args.hook else {}
    stats: dict[str, int] = {}
    try:
        text = _session_text(args, data, stats)
    except Exception:
        logger.debug("building the session start text failed", exc_info=True)
        text = _INDEX_RULES
        stats.clear()
    print(text)
    if args.hook:
        source = data.get("source")
        common._log_hook({
            "hook": "session-index",
            "source": source if isinstance(source, str) else None,
            "ms": int((time.monotonic() - started) * 1000),
            "chars": len(text),
            "rules": stats.get("rules", 0),
            "rules_left": stats.get("rules_left", 0),
            "rules_chars": stats.get("rules_chars", 0),
        })
    return 0


_COMPACT_PARSE_LIMIT = 1_000_000
_COMPACT_OUT_LIMIT = 300
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _compact_entry(
    data: dict[str, Any], summary: str, found: dict[str, str], lines: list[str], started: float
) -> dict[str, Any]:
    """The hook log line of a compaction: counts and flags only."""
    text = summary[:_COMPACT_PARSE_LIMIT]
    trigger, session = data.get("trigger"), data.get("session_id")
    return {
        "hook": "post-compact",
        "trigger": trigger if isinstance(trigger, str) and trigger in {"manual", "auto"} else None,
        "session": session if isinstance(session, str) and _SESSION_ID.fullmatch(session) else None,
        "chars": len(summary),
        "marker": handoff.has_marker(text),
        "handoff": [f for f in handoff.FIELDS if f in found],
        "plan_named": handoff.names_plan(found.get("plan", "")),
        "unrecorded": handoff.unrecorded(text),
        "mismatches": len(lines),
        "ms": int((time.monotonic() - started) * 1000),
    }


def _compact_log(args: argparse.Namespace, started: float) -> None:
    data = _hook_input() if args.hook else {}
    summary = data.get("compact_summary")
    if not isinstance(summary, str):
        return
    text = summary[:_COMPACT_PARSE_LIMIT]
    cwd = _hook_cwd(data)
    found = handoff.parse(text)
    lines = handoff.mismatches(found, cwd)
    if lines:
        print("\n".join(lines)[:_COMPACT_OUT_LIMIT])
    if args.hook:
        common._log_hook(_compact_entry(data, summary, found, lines, started))


def cmd_compact_log(args: argparse.Namespace) -> int:
    """Never fails and prints nothing on bad input. Prints the handoff mismatch lines and logs counts only."""
    started = time.monotonic()
    try:
        _compact_log(args, started)
    except Exception:
        logger.debug("logging the compact summary failed", exc_info=True)
    return 0


_SIGNAL_LIMIT = 400
_SIGNAL_HANDLES = 3


def signal_text(strong: Sequence[records.Related], possible: Sequence[records.Related]) -> str:
    """The block appended to a subagent's brief: handles and counts only, at most _SIGNAL_LIMIT characters."""
    if not strong:
        return ""
    shown = [
        f"{r.kind}:{r.handle}" for r in strong[:_SIGNAL_HANDLES]
    ]  # only strong matches are named

    def render(items: list[str]) -> str:
        return "\n".join([
            f"[memory] For information: memories related to this task exist (not read yet): {' '.join(items)}",
            (
                f"{len(strong)} strong, {len(possible)} possibly related. Read one with: mem show m:<handle> "
                "(they are files in .memory/)."
            ),
            (
                "They are experience, not fact: where one conflicts with this brief, the brief wins and you report "
                "the conflict."
            ),
        ])

    text = render(shown)
    while len(text) > _SIGNAL_LIMIT and len(shown) > 1:  # very long note names
        shown.pop()
        text = render(shown)
    return text


@dataclasses.dataclass(frozen=True)
class _SignalInput:
    """The brief a signal is for, and with --hook the hook's JSON and the tool input it came in."""

    data: dict[str, Any]
    tool_input: Any
    brief: str


def _signal_input(args: argparse.Namespace) -> _SignalInput | None:
    """None when there is no brief to signal: not an Agent call, or an empty brief."""
    data: dict[str, Any] = {}
    tool_input: Any = None
    if args.hook:
        data = _hook_input()
        tool_input = data.get("tool_input")
        if data.get("tool_name") != "Agent" or not isinstance(tool_input, dict):
            return None
        brief = tool_input.get("prompt")
    else:
        brief = None if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    if not isinstance(brief, str) or not brief.strip():
        return None
    return _SignalInput(data, tool_input, brief)


def _signal_related(
    args: argparse.Namespace, given: _SignalInput
) -> tuple[list[records.Related], list[records.Related]]:
    """The strong and the possibly related memories of the brief (memories only)."""
    scope = _hook_scope(args, given.data)
    project = records.project_root(scope.cwd, os.environ)
    found = records.load_memories(records.project_dir(project) if project else None, "project") + [
        m for m in records.load_memories(scope.memories, "global") if not records.quarantined(m)
    ]
    return records.related_records(found, [], given.brief, datetime.date.today(), tokenize=tokenize)


def _signal_log(
    given: _SignalInput,
    strong: Sequence[records.Related],
    possible: Sequence[records.Related],
    started: float,
) -> None:
    subagent_type = given.tool_input.get("subagent_type")
    common._log_hook({
        "hook": "signal",
        "ms": int((time.monotonic() - started) * 1000),
        "strong": len(strong),
        "possible": len(possible),
        "subagent_type": subagent_type if isinstance(subagent_type, str) else None,
        "words": len(given.brief.split()),
    })


def _signal_print(args: argparse.Namespace, given: _SignalInput, text: str) -> None:
    if not args.hook:
        print(text)
        return
    updated = {**given.tool_input, "prompt": f"{given.brief}\n\n{text}"}
    print(
        json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}})
    )


def _signal(args: argparse.Namespace, started: float) -> None:
    given = _signal_input(args)
    if given is None:
        return
    strong, possible = _signal_related(args, given)
    text = signal_text(strong, possible)
    if args.hook:
        _signal_log(given, strong, possible, started)
    if text:
        _signal_print(args, given, text)


def cmd_signal(args: argparse.Namespace) -> int:
    """Never fails. Without --hook: the brief on standard input, the signal text out. With --hook: the hook's JSON in,
    the brief with the signal appended out (updatedInput, never a permission decision), one line in the hook log."""
    started = time.monotonic()
    try:
        _signal(args, started)
    except Exception:
        logger.debug("the signal hook failed", exc_info=True)
    return 0


def _approval(args: argparse.Namespace) -> dict[str, bool]:
    return {"owner_approved": True} if getattr(args, "owner_approved", False) else {}


def _add_sightings(
    same: Sequence[records.Memory],
    args: argparse.Namespace,
    today: datetime.date,
    folder: Path,
    project: Path | None,
) -> bool:
    """An identical claim from another session: when both the existing record and this call come from a transcript,
    the session goes onto the existing record. True when the call was handled (the caller still exits 3)."""
    keys = [records.sighting_entry(*f) for f in map(records.sighting, args.source) if f]
    target = next((m for m in same if m.origin == "transcript"), None)
    if target is None or getattr(args, "origin", None) != "transcript" or not keys:
        return False
    added = cased = False
    for key in keys:
        if records.counted(target, key):
            print(f"mem: {key} is already counted for m:{target.handle}.", file=sys.stderr)
            explicit = getattr(args, "outcome", None)
            sid = records.session_key(key)
            if explicit and sid and not records.has_case(target, sid, explicit):
                records.log_before(target, "confirm")
                target, _ = records.add_case(
                    target, key, getattr(args, "seen_on", None) or today, explicit, today
                )
                cased = True
                print(f"mem: case {explicit} added to m:{target.handle}.", file=sys.stderr)
            continue
        records.log_before(target, "confirm")
        target, _ = records.add_sighting(
            target,
            key,
            today,
            outcome=getattr(args, "outcome", None) or "seen",
            on=getattr(args, "seen_on", None),
        )
        added = True
        print(f"mem: {key} added to m:{target.handle}.", file=sys.stderr)
    print(f"m:{target.handle}\t{'sighting' if added else 'case' if cased else 'already counted'}")
    return True


def _check_short_topic(args: argparse.Namespace) -> int | None:
    """Collapse the whitespace of `args.short`, then 2 after a message when it or `args.topic` is not valid
    (empty is allowed: it means none), else None."""
    if args.short and len(args.short.splitlines()) > 1:
        print("mem: the short form must be one line: it has a line break.", file=sys.stderr)
        return 2
    if args.short is not None:
        args.short = " ".join(args.short.split())
    if args.short and not records.valid_short(args.short):
        print(
            f"mem: the short form must be one line of at most {records.SHORT_LIMIT} characters.",
            file=sys.stderr,
        )
        return 2
    if args.topic and not records.valid_topic(args.topic):
        print(
            f"mem: the topic must be one or two lowercase words, at most {records.TOPIC_LIMIT} characters, "
            f'not "other".',
            file=sys.stderr,
        )
        return 2
    return None


def _check_short_claim(args: argparse.Namespace, claim: str) -> int | None:
    """2 after a message when `--user-read` has no `--short`, or a short form the owner did not read is stronger
    than the claim it will sit on; else None."""
    user_read = getattr(args, "user_read", False)
    if user_read and args.short is None:
        print(
            "mem: --user-read goes with --short: it says the owner read that text.", file=sys.stderr
        )
        return 2
    if args.short and not user_read and (reasons := model.short_problems(claim, args.short)):
        print(
            "mem: the short form is refused: "
            + "; ".join(reasons)
            + ". Reword it, or pass --user-read if the "
            "owner read this text.",
            file=sys.stderr,
        )
        return 2
    return None


class _RememberRefusalError(Exception):
    """`mem remember` refused the call, after a message on stderr; `code` is its exit code."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass(frozen=True)
class _RememberTarget:
    """Where a memory is written: its scope, the folder, and the project root for a project memory."""

    scope: str
    folder: Path
    project: Path | None


def _refuse(code: int | None) -> None:
    """Stop `mem remember` with `code` when a check returned one."""
    if code:
        raise _RememberRefusalError(code)


def _remember_check_args(args: argparse.Namespace) -> None:
    args.claim = " ".join(args.claim.split())
    if args.context is not None:
        args.context = " ".join(args.context.split()) or None
    if not args.claim:
        print("mem: the claim is empty.", file=sys.stderr)
        raise _RememberRefusalError(2)
    if args.kind not in records.KINDS:
        print(f"mem: unknown kind {args.kind!r}.", file=sys.stderr)
        raise _RememberRefusalError(2)
    _refuse(_check_short_topic(args))
    _refuse(_check_short_claim(args, args.claim))


def _remember_global_target(store: Path | None) -> _RememberTarget:
    folder = records.memories_root(os.environ, store)
    if folder is None:
        print(
            'mem: no folder for global memories: set the plugin\'s "memories" option, '
            'or MEM_MEMORIES, or use a store made with "mem init".',
            file=sys.stderr,
        )
        raise _RememberRefusalError(2)
    if common._read_only_store(store, folder.resolve()):
        print(common._READ_ONLY_MEMORIES, file=sys.stderr)
        raise _RememberRefusalError(2)
    return _RememberTarget("global", folder, None)


def _remember_project_target(store: Path | None) -> _RememberTarget:
    project = records.project_root(Path.cwd(), os.environ)
    if project is None:
        print(
            "mem: not inside a git repository: pass --global, or set MEM_PROJECT to the project folder.",
            file=sys.stderr,
        )
        raise _RememberRefusalError(2)
    folder = records.project_dir(project)
    if common._read_only_store(store, project) or common._read_only_store(store, folder.resolve()):
        print(common._READ_ONLY_PROJECT, file=sys.stderr)
        raise _RememberRefusalError(2)
    return _RememberTarget("project", folder, project)


def _remember_target(args: argparse.Namespace, store: Path | None) -> _RememberTarget:
    return _remember_global_target(store) if args.is_global else _remember_project_target(store)


def _remember_check_options(args: argparse.Namespace, today: datetime.date) -> None:
    if not args.source and (getattr(args, "outcome", None) or getattr(args, "seen_on", None)):
        print("mem: --outcome and --seen-on need --source.", file=sys.stderr)
        raise _RememberRefusalError(2)
    if getattr(args, "seen_on", None) is not None and args.seen_on > today:
        print("mem: --seen-on cannot be later than today.", file=sys.stderr)
        raise _RememberRefusalError(2)
    if args.kind in {"finding", "document"} and not args.source:
        print(f"mem: a {args.kind} needs at least one --source.", file=sys.stderr)
        raise _RememberRefusalError(2)


def _remember_body(args: argparse.Namespace) -> str:
    try:
        return _memory_body(args.body_file)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mem: cannot read the body: {exc}", file=sys.stderr)
        raise _RememberRefusalError(2) from exc


def _remember_check_text(args: argparse.Namespace, body: str) -> None:
    """Refuse a text that looks like a secret (4), and for the global scope one with a forbidden term."""
    if common._refuse_secret([
        args.claim,
        args.context or "",
        body,
        *args.source,
        args.short or "",
    ]):
        raise _RememberRefusalError(4)
    if args.is_global:
        _refuse(
            common._check_terms(
                [
                    args.claim,
                    args.context or "",
                    body,
                    *args.source,
                    records.slug_of(args.claim),
                    args.short or "",
                ],
                args.kind,
                args.owner_approved,
            )
        )


def _remember_check_sessions(args: argparse.Namespace) -> None:
    """A source of a transcript record that starts like a session entry must be one."""
    if getattr(args, "origin", None) != "transcript":
        return
    for source in args.source:
        if (
            " ".join(source.split()).lower().startswith(records.SESSION_PREFIX)
            and records.sighting(source) is None
        ):
            print(
                f"mem: --source {source!r} is not a session entry: write 'session <id>' or "
                f"'session <id> project <{records.PROJECT_KEY_LEN} hex characters>'.",
                file=sys.stderr,
            )
            raise _RememberRefusalError(2)


def _remember_check_valid_until(
    args: argparse.Namespace, target: _RememberTarget, today: datetime.date
) -> None:
    if getattr(args, "origin", None) != "transcript" or args.valid_until is None:
        return
    draft = records.Memory(
        target.scope,
        target.folder,
        "",
        args.kind,
        args.claim,
        today,
        1,
        "active",
        None,
        None,
        records.normalized_sources(args.source),
        "",
        None,
        origin="transcript",
        weight=getattr(args, "weight", None),
    )
    if records.standing(draft) != "established":
        print(
            f"mem: --valid-until is refused: the life of a record from a transcript is "
            f"{records.UNCONFIRMED_DAYS} days from the last session that showed it.",
            file=sys.stderr,
        )
        raise _RememberRefusalError(2)


def _remember_same_claim(
    args: argparse.Namespace, existing: list[records.Memory], live: list[records.Memory]
) -> list[records.Memory]:
    """The live memories with the claim, and, for a call from a session, the lapsed ones from a transcript."""
    from_session = getattr(args, "origin", None) == "transcript" and any(
        map(records.session_key, args.source)
    )
    lapsed = [
        m
        for m in existing
        if from_session
        and m.error is None
        and m.status == "active"
        and m.origin == "transcript"
        and m not in live
    ]
    return [m for m in live + lapsed if _same_claim(m.claim, args.claim)]


def _remember_check_duplicates(
    args: argparse.Namespace,
    target: _RememberTarget,
    today: datetime.date,
    existing: list[records.Memory],
    live: list[records.Memory],
) -> None:
    """Exit 3 when the claim exists, unless `--force`."""
    if args.force:
        return
    same = _remember_same_claim(args, existing, live)
    if not same:
        return
    if _add_sightings(same, args, today, target.folder, target.project):
        raise _RememberRefusalError(3)
    for m in same:
        print(f"m:{m.handle}\t{m.claim}", file=sys.stderr)
    print(
        f'mem: a memory with the same claim exists; run "mem observe m:{same[0].handle}" if it is the same, '
        "or repeat with --force to write a new one.",
        file=sys.stderr,
    )
    raise _RememberRefusalError(3)


def _remember_exclude_failed(project: Path | None) -> bool:
    """Keep `.memory/` out of git status for a project; True when that failed."""
    if project is None:
        return False
    try:
        records.ensure_excluded(project)
    except OSError:
        return True
    return False


def _remember_write(
    args: argparse.Namespace, target: _RememberTarget, body: str, today: datetime.date
) -> records.Memory:
    try:
        return records.write_memory(
            target.folder,
            target.scope,
            kind=args.kind,
            claim=args.claim,
            body=body,
            today=today,
            context=args.context,
            valid_until=args.valid_until,
            sources=args.source,
            origin=getattr(args, "origin", None),
            reach=getattr(args, "reach", None),
            weight=getattr(args, "weight", None),
            short=args.short or None,
            topic=args.topic or None,
            short_by="model" if args.short and not getattr(args, "user_read", False) else None,
            outcome=getattr(args, "outcome", None),
            on=getattr(args, "seen_on", None),
        )
    except (ValueError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        raise _RememberRefusalError(2) from exc


def _remember_report(
    m: records.Memory,
    target: _RememberTarget,
    exclude_failed: bool,
    related: Sequence[records.Memory],
) -> None:
    """The handle and path on stdout; the warning and the related memories on stderr."""
    _register_project(target.project)
    rel = m.path.relative_to(target.project if target.project is not None else target.folder)
    print(f"m:{m.handle}\t{rel.as_posix()}")
    if exclude_failed:
        print(
            "mem: could not add .memory/ to .git/info/exclude; the folder may appear in git status.",
            file=sys.stderr,
        )
    if related:
        print(
            'related memories (if one is the same, run "mem observe m:<handle>"; if one says the opposite, keep both):',
            file=sys.stderr,
        )
        for r in related:
            print(
                f"m:{r.handle}\t[{r.kind}, observed {r.observed}, {r.created.isoformat() if r.created else '?'}]\t{r.claim}",
                file=sys.stderr,
            )


def _remember_log(
    args: argparse.Namespace,
    store: Path | None,
    target: _RememberTarget,
    m: records.Memory,
    today: datetime.date,
) -> None:
    common.log_usage(store, {"cmd": "remember", "scope": target.scope, **_approval(args)})
    if (
        target.scope == "global"
        and getattr(args, "origin", None) != "pipeline"
        and not records.quarantined(m)
    ):
        settle_state.maybe_start(target.folder, store, os.environ, time.time(), today)


def _remember(args: argparse.Namespace) -> None:
    """The steps of `mem remember`; a refusal raises `_RememberRefusalError`."""
    today = datetime.date.today()
    store = common._optional_store(args)
    _remember_check_args(args)
    target = _remember_target(args, store)
    _remember_check_options(args, today)
    body = _remember_body(args)
    _remember_check_text(args, body)
    _remember_check_sessions(args)
    _remember_check_valid_until(args, target, today)
    existing = records.load_memories(target.folder, target.scope)
    live = [m for m in existing if records.is_live(m, today)]
    _remember_check_duplicates(args, target, today, existing, live)
    related = records.match_memories(
        _readable(live, today), tokenize(args.claim), today, tokenize=tokenize
    )
    exclude_failed = _remember_exclude_failed(target.project)
    m = _remember_write(args, target, body, today)
    _remember_report(m, target, exclude_failed, related)
    _remember_log(args, store, target, m, today)


def cmd_remember(args: argparse.Namespace) -> int:
    try:
        _remember(args)
    except _RememberRefusalError as refusal:
        return refusal.code
    return 0


def _memory_scopes(args: argparse.Namespace) -> dict[str, dict[str, records.Memory]]:
    """The memories of each scope by handle."""
    project = records.project_root(Path.cwd(), os.environ)
    folders = {
        "project": records.project_dir(project) if project else None,
        "global": records.memories_root(os.environ, common._optional_store(args)),
    }
    return {
        scope: {m.handle: m for m in records.load_memories(folder, scope)}
        for scope, folder in folders.items()
    }


def _memory_missing(
    loaded: dict[str, dict[str, records.Memory]], order: Sequence[str], handles: Sequence[str]
) -> str | None:
    """The first handle that no scope in `order` holds."""
    for handle in handles:
        if not any(handle.removeprefix("m:") in loaded[scope] for scope in order):
            return handle
    return None


def _memory_pick(
    loaded: dict[str, dict[str, records.Memory]], order: Sequence[str], handles: Sequence[str]
) -> list[records.Memory] | None:
    """The memories of the first scope in `order` that holds all `handles`; None after a message on stderr."""
    missing = _memory_missing(loaded, order, handles)
    if missing is not None:
        print(f"mem: no memory named {missing}", file=sys.stderr)
        return None
    names = [h.removeprefix("m:") for h in handles]
    scope = next((s for s in order if all(name in loaded[s] for name in names)), None)
    if scope is None:
        print(
            f"mem: {' and '.join('m:' + n for n in names)} are in different scopes: both must be in the same one.",
            file=sys.stderr,
        )
        return None
    return [loaded[scope][name] for name in names]


def _memory_refused(found: Sequence[records.Memory], store: Path | None) -> bool:
    """Whether a memory cannot be changed (an unreadable record, or a read-only store), after a message on stderr."""
    for m in found:
        if m.error is not None:
            print(f"mem: {m.path}: {m.error}", file=sys.stderr)
            return True
        if common._read_only_store(store, m.path.resolve()):
            print(
                common._READ_ONLY_PROJECT if m.scope == "project" else common._READ_ONLY_MEMORIES,
                file=sys.stderr,
            )
            return True
    return False


def _memory_of(args: argparse.Namespace, handles: Sequence[str]) -> list[records.Memory] | None:
    """The named memories, all in one scope: the project's unless --global; None after a message on stderr.

    A handle found in both scopes means the project one, as for any lookup; with several handles the scope is
    one that holds all of them, and handles that exist only in different scopes are refused."""
    loaded = _memory_scopes(args)
    order = ("global",) if args.is_global else ("project", "global")
    found = _memory_pick(loaded, order, handles)
    if found is None or _memory_refused(found, common._optional_store(args)):
        return None
    return found


def _with_note(body: str, heading: str, text: str) -> str:
    """The body with a heading line and the text under it added at the end."""
    head = body.rstrip("\n")
    return (
        f"{head}\n\n{heading}\n{text.strip()}\n" if head.strip() else f"{heading}\n{text.strip()}\n"
    )


def _reason_allowed(memory: records.Memory, because: str | None, approved: bool) -> int:
    """0 when the reason may be written: it goes through the secret patterns; one written into a global memory also
    through the term list, failing closed. Else the exit code, after a message."""
    if not because:
        return 0
    if common._refuse_secret([because]):
        return 4
    if memory.scope != "global":
        return 0
    return common._check_terms([because], memory.kind, approved)


def _act(
    args: argparse.Namespace,
    handles: Sequence[str],
    apply: Callable[[list[records.Memory], datetime.date], list[str]],
    name: str,
    because: str | None = None,
) -> int:
    found = _memory_of(args, handles)
    if found is None:
        return 2
    refused = _reason_allowed(found[0], because, getattr(args, "owner_approved", False))
    if refused:
        return refused
    try:
        lines = apply(found, datetime.date.today())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if found[0].scope == "project":
        _register_project(records.project_root(Path.cwd(), os.environ))
    print("\n".join(lines))
    common.log_usage(
        common._optional_store(args), {"cmd": name, "scope": found[0].scope, **_approval(args)}
    )
    return 0


def _add_plain_source(
    memory: records.Memory, source: str, today: datetime.date, note: str | None
) -> records.Memory:
    """A source (URL, path or session) appended once to a memory that is not from a transcript, with the note."""
    changes: dict = {}
    if source not in memory.sources:
        changes["sources"] = [*memory.sources, source]
    if note and note.strip():
        head = memory.body if memory.body.endswith("\n") or not memory.body else memory.body + "\n"
        changes["body"] = f"{head}{' '.join(note.split())}\n"
    return records.update(memory, today, **changes) if changes else memory


@dataclasses.dataclass(frozen=True)
class _ConfirmOptions:
    """The validated flags of `mem confirm`; `outcome` is None when none was given."""

    until: datetime.date | None
    source: str | None
    note: str | None
    outcome: str | None
    seen_on: datetime.date | None


def _confirm_options(args: argparse.Namespace, today: datetime.date) -> _ConfirmOptions:
    until = getattr(args, "until", None)
    if until is not None:
        try:
            until = datetime.date.fromisoformat(until)
        except ValueError:
            raise ValueError(f"--until needs a date as YYYY-MM-DD, not {until!r}") from None
    source = getattr(args, "source", None)
    if source is None and getattr(args, "note", None):
        raise ValueError("--note needs --source")
    if source is None and (getattr(args, "outcome", None) or getattr(args, "seen_on", None)):
        raise ValueError("--outcome and --seen-on need --source")
    if getattr(args, "seen_on", None) is not None and args.seen_on > today:
        raise ValueError("--seen-on cannot be later than today")
    return _ConfirmOptions(
        until,
        source,
        getattr(args, "note", None),
        getattr(args, "outcome", None),
        getattr(args, "seen_on", None),
    )


def _confirm_by_owner(
    options: _ConfirmOptions, m: records.Memory, today: datetime.date
) -> tuple[list[str], bool]:
    """The owner confirms a lesson captured from a transcript; True in the second place when it already was."""
    if options.source is not None or options.until is not None:
        raise ValueError("--by-owner stands alone: it takes no --source or --until")
    if m.origin != "transcript":
        raise ValueError(
            f"m:{m.handle} is not from a transcript: the owner's confirmation applies to a "
            "lesson captured from one"
        )
    if m.status != "active":
        raise ValueError(f"m:{m.handle} is {m.status}: the owner confirms only an active memory")
    if m.owner_confirmed:
        return [f"m:{m.handle}\talready confirmed by the owner: nothing changed"], True
    records.log_before(m, "confirm")
    after = dataclasses.replace(m, owner_confirmed=today)
    records.update(m, today, owner_confirmed=today, **records.standing_changes(m, after, today))
    return [f"m:{m.handle}\tconfirmed by the owner"], False


def _confirm_check_source(options: _ConfirmOptions, m: records.Memory) -> None:
    source = options.source
    if source is not None and not source.strip():
        raise ValueError("--source is empty")
    if source is not None and m.origin == "transcript" and records.session_key(source) is None:
        raise ValueError(f"--source takes a session ('session <id>'), not {source!r}")
    if options.until is not None and records.standing(m) == "unconfirmed":
        raise ValueError(
            "a record from a transcript is confirmed only by another session showing it: "
            "use --source 'session <id>', not --until"
        )
    if source is not None and m.status != "active":
        raise ValueError(f"m:{m.handle} is {m.status}: a source is added only to an active memory")


def _confirm_is_counted(options: _ConfirmOptions, m: records.Memory) -> bool:
    """Whether the source is already one of the memory's sources (a session already counted)."""
    source = options.source
    if source is None:
        return False
    if m.origin == "transcript":
        return records.counted(m, source)
    seen = {records.session_key(s) or s.strip() for s in m.sources}
    return (records.session_key(source) or source.strip()) in seen


def _confirm_add_case(
    options: _ConfirmOptions, source: str, found: list[records.Memory], today: datetime.date
) -> list[str]:
    """A counted session gets a case only on request: `--outcome` that the memory does not have yet."""
    outcome = options.outcome or "seen"
    records.log_before(found[0], "confirm")
    found[0], _ = records.add_case(found[0], source, options.seen_on or today, outcome, today)
    if options.until is None:
        return [f"m:{found[0].handle}\tcase {outcome} added"]
    records.update(found[0], today, valid_until=options.until)
    return [f"m:{found[0].handle}\tcase {outcome} added; valid until {options.until.isoformat()}"]


def _confirm_counted(
    options: _ConfirmOptions, found: list[records.Memory], today: datetime.date
) -> tuple[list[str], bool]:
    """The source is already counted: a case when asked for, else nothing but `--until`; True in the second place
    when the call changed nothing."""
    source = options.source
    m = found[0]
    key = records.session_key(source) if source is not None else None
    if (
        m.origin == "transcript"
        and key
        and source is not None  # a session key comes only from a source
        and options.outcome
        and not records.has_case(m, key, options.outcome)
    ):
        return _confirm_add_case(options, source, found, today), False
    if options.until is None:
        return [f"m:{m.handle}\t{source} is already a source: nothing changed"], True
    records.log_before(m, "confirm")  # the source is not counted again; the date is still set
    records.update(m, today, valid_until=options.until)
    return [
        f"m:{m.handle}\t{source} is already a source; valid until {options.until.isoformat()}"
    ], True


def _confirm_observe(
    options: _ConfirmOptions, m: records.Memory, today: datetime.date
) -> list[str]:
    """Count one more observation, with the source and the note when given, and `--until`."""
    source = options.source
    records.log_before(m, "confirm")
    if source is not None and m.origin == "transcript":
        updated, _ = records.add_sighting(
            m, source, today, options.note, outcome=options.outcome or "seen", on=options.seen_on
        )
    else:
        updated = records.observe(m, today)
        if source is not None:
            updated = _add_plain_source(updated, source.strip(), today, options.note)
    if options.until is not None:
        updated = records.update(updated, today, valid_until=options.until)
    return [f"m:{updated.handle}\tobserved {updated.observed}"]


def _confirm_apply(
    args: argparse.Namespace, found: list[records.Memory], today: datetime.date
) -> tuple[list[str], bool]:
    """The lines to print, and whether the call repeated what the memory already had."""
    options = _confirm_options(args, today)
    if getattr(args, "by_owner", False):
        return _confirm_by_owner(options, found[0], today)
    _confirm_check_source(options, found[0])
    if _confirm_is_counted(options, found[0]):
        return _confirm_counted(options, found, today)
    return _confirm_observe(options, found[0], today), False


def cmd_confirm(args: argparse.Namespace) -> int:
    repeated: list[bool] = []

    def apply(found, today):
        lines, again = _confirm_apply(args, found, today)
        if again:
            repeated.append(True)
        return lines

    code = _act(args, [args.handle], apply, args.command, because=getattr(args, "note", None))
    return 3 if code == 0 and repeated else code


def _text_change(
    found: list[records.Memory],
    key: str,
    heading: str,
    because: str | None,
    today: datetime.date,
    **extra,
) -> records.Memory:
    m = found[0]
    records.log_before(m, {"refuted": "refute", "forgotten": "forget"}[key])
    changes = {"status": key, key: today, **extra}
    if because and because.strip():
        changes["body"] = _with_note(m.body, f"{heading} {today.isoformat()}:", because)
    return records.update(m, today, **changes)


def cmd_refute(args: argparse.Namespace) -> int:
    def apply(found, today):
        _text_change(found, "refuted", "Refuted", args.because, today)
        return [f"m:{found[0].handle}\trefuted"]

    return _act(args, [args.handle], apply, "refute", args.because)


def cmd_forget(args: argparse.Namespace) -> int:
    def apply(found, today):
        _text_change(
            found, "forgotten", "Forgotten", args.because, today, triage=None, triage_reason=None
        )
        return [f"m:{found[0].handle}\tforgotten"]

    return _act(args, [args.handle], apply, "forget", args.because)


def _project_md_files(folder: Path, n: int, total: int) -> list[Path]:
    try:  # os.listdir raises on a folder that cannot be read; Path.glob would return nothing
        return [folder / name for name in os.listdir(folder) if name.endswith(".md")]
    except OSError as exc:
        raise ValueError(f"project memory folder {n} of {total} cannot be read ({exc})") from exc


def _linked_in_folder(
    handle: str, named: re.Pattern[str], folder: Path, files: list[Path]
) -> list[records.Memory]:
    found = []
    for m in records.load_memories(folder, "project"):
        if m.error is None:
            if m.general == handle:
                found.append(m)
        elif m.path in files and named.search(m.path.read_text(encoding="utf-8", errors="replace")):
            raise ValueError(
                f"project record m:{m.handle} names it in `general` but cannot be parsed "
                f"({m.error})"
            )
    return found


def _linked_in_counted_projects(handle: str) -> list[records.Memory]:
    named = re.compile(rf"^general:\s*['\"]?{re.escape(handle)}['\"]?\s*$", re.MULTILINE)
    found: list[records.Memory] = []
    projects = corroborate_decide.counted_projects(
        records.read_registry(common.data_dir(os.environ))
    )
    for n, project in enumerate(projects, 1):
        folder = records.project_dir(project)
        files = _project_md_files(folder, n, len(projects))
        found += _linked_in_folder(handle, named, folder, files)
    return found


def _linked_project_records(handle: str) -> list[records.Memory]:
    """Step 1 of a reject: every project record, in every counted project, whose `general` names `handle`.
    ValueError, with nothing changed yet, when a registry, a folder or a file that may name it cannot be read."""
    try:
        return _linked_in_counted_projects(handle)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"reject stopped while looking for the project records that name it: {exc}; "
            "no change was made"
        ) from exc


def _reject(found: list[records.Memory], today: datetime.date) -> list[str]:
    m = found[0]
    linked = _linked_project_records(
        m.handle
    )  # before any change: a refusal leaves everything as it was
    done: list[str] = []
    try:
        for record in linked:
            records.log_before(record, "triage")
            records.update(record, today, promote="no", general=None)
            done.append(f"m:{record.handle}")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(
            f"reject failed while unlinking the project records ({exc}); unlinked so far: "
            f"{', '.join(done) or 'none'}; the global record is still active"
        ) from exc
    try:
        _text_change(found, "forgotten", "Forgotten", None, today, triage=None, triage_reason=None)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(
            f"reject failed while retiring m:{m.handle} ({exc}); the project records were already "
            f"unlinked: {', '.join(done) or 'none'}; the global record is still active"
        ) from exc
    return [
        f"m:{m.handle}\trejected",
        f"unlinked {len(done)} project record{'' if len(done) == 1 else 's'}",
        *(f"{h}\tunlinked" for h in done),
    ]


def _triage_hold(m: records.Memory, today: datetime.date, because: str | None) -> list[str]:
    if m.status != "active":
        raise ValueError(f"m:{m.handle} is {m.status}: only an active lesson can be held")
    if records.quarantined(m):
        raise ValueError(
            f"m:{m.handle} is in quarantine: it is not shown anyway until corroborated"
        )
    records.log_before(m, "triage")
    records.update(m, today, triage="pending", triage_reason=because)
    return [f"m:{m.handle}\theld"]


def _triage_refuse_unawaited(m: records.Memory) -> None:
    """Raise: `m` is not awaiting triage, and say why."""
    if records.quarantined(m):
        raise ValueError(
            f"m:{m.handle} is still in quarantine: it leaves quarantine when seen in a second "
            "project or confirmed with mem confirm --by-owner"
        )
    raise ValueError(f"m:{m.handle} was already accepted or never awaited triage")


def _triage_decide(command: str, found: list[records.Memory], today: datetime.date) -> list[str]:
    """Accept or reject (`command`) the lesson `found[0]`, which must be active and awaiting triage."""
    m = found[0]
    if m.status != "active":
        raise ValueError(f"m:{m.handle} is {m.status}: only an active general lesson awaits triage")
    if command == "accept" and m.triage != "pending" and records.got_worse(m):
        records.log_before(m, "triage")
        records.update(m, today, reviewed=today)
        return [f"m:{m.handle}\tkept as worded"]
    if m.triage != "pending":
        _triage_refuse_unawaited(m)
    if command == "accept":
        records.log_before(m, "triage")
        records.update(m, today, triage=None, triage_reason=None)
        return [f"m:{m.handle}\taccepted"]
    return _reject(found, today)


def _triage_apply(
    args: argparse.Namespace,
    because: str | None,
    found: list[records.Memory],
    today: datetime.date,
) -> list[str]:
    m = found[0]
    if (
        getattr(args, "project_scope", False) and m.scope != "project"
    ):  # the lookup falls back to the global scope
        raise ValueError(f"no memory named m:{m.handle}")
    if args.triage_command == "hold":
        return _triage_hold(m, today, because)
    return _triage_decide(args.triage_command, found, today)


def cmd_triage(args: argparse.Namespace) -> int:
    """Accept or reject a general lesson that left quarantine, on the global scope; accept also keeps the wording
    of a lesson that got worse, and with --project-scope that lesson may be a project one."""
    args.is_global = not getattr(args, "project_scope", False)
    because = None
    if args.triage_command == "hold":
        because = " ".join((args.because or "").split())
        if not because or not records.valid_triage_reason(because):
            print(
                f"mem: hold needs --because, one line of at most {records.TRIAGE_REASON_LIMIT} characters.",
                file=sys.stderr,
            )
            return 2

    def apply(found, today):
        return _triage_apply(args, because, found, today)

    return _act(args, [args.handle], apply, f"triage-{args.triage_command}", because)


def _two(args: argparse.Namespace, first: str, second: str, name: str, apply) -> int:
    if first.removeprefix("m:") == second.removeprefix("m:"):
        print(f"mem: {name} needs two different memories.", file=sys.stderr)
        return 2
    return _act(args, [first, second], apply, name)


def _supersede_pair(old: records.Memory, new: records.Memory, today: datetime.date) -> list[str]:
    records.log_before(old, "supersede")
    records.update(old, today, status="superseded", superseded_by=new.handle)
    return [f"m:{old.handle}\tsuperseded by m:{new.handle}"]


def cmd_supersede(args: argparse.Namespace) -> int:
    def apply(found: list[records.Memory], today: datetime.date) -> list[str]:
        return _supersede_pair(found[0], found[1], today)

    return _two(args, args.old, args.new, "supersede", apply)


def _undo_failed_edit(
    m: records.Memory, original: bytes, updating: bool, log: Path, log_before: bytes | None
) -> None:
    """Put a memory file and its curation log back as they were before an edit that failed."""
    if updating and m.path.read_bytes() != original:
        common._swap_file(m.path, original)
    if log_before is None:
        log.unlink(missing_ok=True)
    else:
        safe_io.replace_file(log, log_before)


def _reword_failed_conflicts(args: argparse.Namespace) -> bool:
    """True when `--reword-failed` comes with another change."""
    others = (args.claim, args.context, args.body_file, args.short, args.topic)
    flags = (args.no_load, args.load, args.index_only, args.reworded, args.user_read)
    return any(o is not None for o in others) or any(flags)


def _reword_failed(args: argparse.Namespace) -> int:
    """`mem memory edit <h> --reword-failed`: note the version the automatic rewording gave up on; nothing else changes."""
    if _reword_failed_conflicts(args):
        print(
            "mem: --reword-failed stands alone: it changes no other part of the lesson.",
            file=sys.stderr,
        )
        return 2
    found = _memory_of(args, [args.handle])
    if found is None:
        return 2
    m = found[0]
    versions = records.version_list(m)
    if not versions:
        print(f"mem: m:{m.handle} has no short form version to give up on.", file=sys.stderr)
        return 2
    log = m.path.parent / records.CURATION_LOG
    log_before = log.read_bytes() if log.exists() else None
    original = m.path.read_bytes()
    updating = False
    try:
        records.log_before(m, "edit")
        updating = True
        records.update(m, datetime.date.today(), reword_failed=versions[-1][0])
    except (
        OSError,
        ValueError,
        yaml.YAMLError,
    ) as exc:  # any failure leaves the memory and its log as they were
        _undo_failed_edit(m, original, updating, log, log_before)
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"m:{m.handle}\tedited reword failed")
    common.log_usage(
        common._optional_store(args),
        {"cmd": "memory", "action": "edit", "scope": m.scope, **_approval(args)},
    )
    return 0


@dataclass(frozen=True)
class _MemoryEditInputs:
    """What `mem memory edit` was asked to write, cleaned: whitespace folded, the body file read."""

    claim: str | None
    context: str | None
    body: str | None
    texts: list[str]


def _memory_edit_flags_refused(args: argparse.Namespace) -> int | None:
    """The exit code of an edit whose flags contradict each other or ask for nothing; None when they are fine."""
    if args.reworded and (not args.short or args.user_read):
        print(
            "mem: --reworded goes with a non-empty --short and without --user-read: it marks a model's rewording.",
            file=sys.stderr,
        )
        return 2
    asks = (args.claim, args.context, args.body_file, args.short, args.topic)
    if all(a is None for a in asks) and not args.no_load and not args.load and not args.index_only:
        raise common.UsageError(
            "memory edit needs --claim, --context, --body-file, --short, --topic, --no-load, --index-only or --load"
        )
    return None


def _memory_edit_inputs(args: argparse.Namespace) -> _MemoryEditInputs | int:
    """The cleaned texts of an edit, or the exit code of the refusal (empty claim, bad short form, secret)."""
    claim = " ".join(args.claim.split()) if args.claim is not None else None
    context = " ".join(args.context.split()) if args.context is not None else None
    try:
        body = common._read_body(args.body_file) if args.body_file else None
    except common.NewNoteError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if claim is not None and not claim:
        print("mem: the claim is empty.", file=sys.stderr)
        return 2
    if (refused := _check_short_topic(args)) is not None:
        return refused
    texts = [t for t in (claim, context, body, args.short) if t]
    if common._refuse_secret(texts):
        return 4
    return _MemoryEditInputs(claim, context, body, texts)


def _memory_edit_target(args: argparse.Namespace, edit: _MemoryEditInputs) -> records.Memory | int:
    """The memory to edit, or the exit code of the refusal (unknown, not active, bad short form, forbidden terms)."""
    found = _memory_of(args, [args.handle])
    if found is None:
        return 2
    m = found[0]
    if m.status != "active":
        print(
            f"mem: m:{m.handle} is {m.status}: run mem restore m:{m.handle} to bring it back before editing it.",
            file=sys.stderr,
        )
        return 2
    if (
        refused := _check_short_claim(args, edit.claim if edit.claim is not None else m.claim)
    ) is not None:
        return refused
    if (
        m.scope == "global"
        and edit.texts
        and (
            refused := common._check_terms(
                edit.texts, m.kind, getattr(args, "owner_approved", False)
            )
        )
    ):
        return refused
    return m


def _memory_edit_wording(
    args: argparse.Namespace,
    m: records.Memory,
    edit: _MemoryEditInputs,
    changes: dict[str, Any],
    what: list[str],
) -> None:
    """Add the claim, context and body changes to `changes`, refusing a shrink the guard stops."""
    if edit.claim is not None:
        if not args.shrink:
            synthesis_edit._guard_shrink(m.claim, edit.claim, sentences=False)
        changes["claim"] = edit.claim
        what.append("claim")
    if edit.context is not None:
        changes["context"] = edit.context or None
        what.append("context")
    if edit.body is not None:
        if not args.shrink:
            synthesis_edit._guard_shrink(m.body.strip("\n"), edit.body.strip("\n"))
        changes["body"] = edit.body
        what.append("body")


def _memory_edit_short(
    args: argparse.Namespace,
    m: records.Memory,
    claim: str | None,
    changes: dict[str, Any],
    what: list[str],
) -> bool:
    """Add the short form change to `changes`; True when a new claim removed the old short form."""
    if args.short is not None:
        changes["short"] = args.short or None
        changes["short_by"] = "model" if args.short and not args.user_read else None
        if args.reworded:
            changes["reworded"] = datetime.date.today()
        what.append("short")
    elif claim is not None and claim != m.claim and (m.short or m.short_by):
        changes["short"] = None  # a short form never outlives the claim it was drawn from
        changes["short_by"] = None
        if m.short:
            what.append("short removed")
            return True
    return False


def _memory_edit_topic_load(
    args: argparse.Namespace, changes: dict[str, Any], what: list[str]
) -> None:
    """Add the topic and load changes to `changes`."""
    if args.topic is not None:
        changes["topic"] = args.topic or None
        what.append("topic")
    if args.no_load:
        changes["load"] = "no"
        what.append("load")
    elif args.index_only:
        changes["load"] = "index"
        what.append("load")
    elif args.load:
        changes["load"] = None
        what.append("load")


def _memory_edit_commit(
    m: records.Memory,
    changes: dict[str, Any],
    original: bytes,
    log: Path,
    log_before: bytes | None,
) -> None:
    """Write `changes` with undo: refused when the file changed since `original`, and any failure restores it."""
    updating = False
    try:
        records.log_before(m, "edit")
        if m.path.read_bytes() != original:
            raise ValueError(
                f"{m.path.name} changed since it was read, so nothing was written: run the command again"
            )
        updating = True
        records.update(m, datetime.date.today(), **changes)
    except BaseException:  # any failure leaves the memory and its log as they were
        _undo_failed_edit(m, original, updating, log, log_before)
        raise


def _memory_edit_write(
    args: argparse.Namespace,
    m: records.Memory,
    edit: _MemoryEditInputs,
    log: Path,
    log_before: bytes | None,
) -> tuple[list[str], bool]:
    """Write an edit; the parts it changed, and whether a new claim removed the short form."""
    original = m.path.read_bytes()
    what: list[str] = []
    changes: dict[str, Any] = {}
    _memory_edit_wording(args, m, edit, changes, what)
    short_removed = _memory_edit_short(args, m, edit.claim, changes, what)
    _memory_edit_topic_load(args, changes, what)
    _memory_edit_commit(m, changes, original, log, log_before)
    return what, short_removed


def _memory_edit_finish(
    args: argparse.Namespace, m: records.Memory, what: list[str], short_removed: bool
) -> None:
    """Report an edit that was written: register the project, print the result, log the use."""
    if m.scope == "project":
        _register_project(records.project_root(Path.cwd(), os.environ))
    if short_removed:
        print(
            "mem: the short form was removed with the old claim: write a new one with --short",
            file=sys.stderr,
        )
    print(f"m:{m.handle}\tedited {', '.join(what)}")
    common.log_usage(
        common._optional_store(args),
        {"cmd": "memory", "action": "edit", "scope": m.scope, **_approval(args)},
    )
    if m.scope == "global" and m.origin != "pipeline":
        settle_state.maybe_start(
            m.path.parent,
            common._optional_store(args),
            os.environ,
            time.time(),
            datetime.date.today(),
        )


def cmd_memory(args: argparse.Namespace) -> int:
    """`mem memory edit`: the claim, context or body of a memory, through the guard, with undo."""
    if args.reword_failed:
        return _reword_failed(args)
    if (refused := _memory_edit_flags_refused(args)) is not None:
        return refused
    edit = _memory_edit_inputs(args)
    if isinstance(edit, int):
        return edit
    m = _memory_edit_target(args, edit)
    if isinstance(m, int):
        return m
    log = m.path.parent / records.CURATION_LOG
    log_before = log.read_bytes() if log.exists() else None
    try:
        what, short_removed = _memory_edit_write(args, m, edit, log, log_before)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    _memory_edit_finish(args, m, what, short_removed)
    return 0


def _merge_session_changes(
    keep: records.Memory, drop: records.Memory, today: datetime.date
) -> dict[str, Any]:
    """The `sources` of a merge, and the standing that goes with them when the kept record came from a session."""
    sources = records.normalized_sources([*keep.sources, *drop.sources])
    changes: dict[str, Any] = {"sources": sources}
    if keep.origin == "transcript":
        after = dataclasses.replace(keep, sources=sources)
        standing_changes = records.standing_changes(keep, after, today)
        if records.standing(after) == "established" or len(records.sessions(after)) > len(
            records.sessions(keep)
        ):
            changes.update(
                standing_changes
            )  # enough evidence now, or a new session renews the 30 days
    return changes


def _merge_pair(keep: records.Memory, drop: records.Memory, today: datetime.date) -> list[str]:
    records.log_before(keep, "merge")
    records.log_before(drop, "merge")
    records.update(drop, today, status="superseded", superseded_by=keep.handle)
    changes: dict[str, Any] = {"observed": keep.observed + drop.observed}
    if drop.body.strip():
        changes["body"] = _with_note(
            keep.body, f"Merged from m:{drop.handle} on {today.isoformat()}:", drop.body
        )
    if "transcript" in {
        keep.origin,
        drop.origin,
    }:  # a session must survive the merge, whichever record holds it
        changes.update(_merge_session_changes(keep, drop, today))
    log = records.merged_log(keep, drop)
    if log != keep.log:
        changes["log"] = log
    versions = records.merged_versions(keep, drop, today)
    if versions and versions != keep.versions:
        changes["versions"] = versions
    updated = records.update(keep, today, **changes)
    return [f"m:{updated.handle}\tobserved {updated.observed}, merged m:{drop.handle}"]


def cmd_merge(args: argparse.Namespace) -> int:
    def apply(found, today):
        keep, drop = found
        flagged = records.flagged_words(keep.claim, drop.claim)
        if flagged and not args.force:
            raise ValueError(
                f"these claims differ in {', '.join(flagged)}: they may be opposites or different "
                "versions; use --force to merge anyway."
            )
        return _merge_pair(keep, drop, today)

    return _two(args, args.keep, args.drop, "merge", apply)


def _distinct_note_paths(args: argparse.Namespace, store: Path) -> tuple[Path, Path] | None:
    """The two notes `mem distinct` names; None when the arguments are not both notes of the store."""
    if args.a.startswith("m:") or args.b.startswith("m:"):
        return None
    first, second = common.resolve_note(store, args.a), common.resolve_note(store, args.b)
    if not isinstance(first, Path) or not isinstance(second, Path):
        return None
    return first, second


def _distinct_edit(path: Path, other_name: str) -> tuple[bytes, str]:
    """A note's current bytes, and its text with `other_name` added to `distinct_from`."""
    text = note_files._read_text(path)
    meta, _, _ = split_frontmatter(text)
    listed = meta.get("distinct_from") if isinstance(meta, dict) else None
    known = [h for h in listed if isinstance(h, str)] if isinstance(listed, list) else []
    return (
        path.read_bytes(),
        common._set_field(text, "distinct_from", sorted({*known, other_name})),
    )


def _distinct_write(root: Path, first: Path, second: Path) -> dict[Path, str]:
    """Mark the two notes as distinct from each other and log the group; the handle of each note."""
    names = {p: note_files._handle(p.relative_to(root).as_posix()) for p in (first, second)}
    originals, edits = {}, {}
    for path, other in ((first, second), (second, first)):
        originals[path], edits[path] = _distinct_edit(path, names[other])
    for path, text in edits.items():
        safe_io.replace_file(path, text.encode("utf-8"))
    common._log_group(root, originals, "distinct")
    return names


def _distinct_notes(args: argparse.Namespace, store: Path) -> int | None:
    """`mem distinct` for two notes of the store; None when the arguments are not both notes."""
    paths = _distinct_note_paths(args, store)
    if paths is None:
        return None
    first, second = paths
    root = _writable_store(args, "distinct")
    if root is None:
        return 2
    root = root.resolve()
    if first == second:
        print("mem: distinct needs two different notes.", file=sys.stderr)
        return 2
    try:
        names = _distinct_write(root, first, second)
    except (OSError, ValueError, FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"{names[first]}\tkept apart from {names[second]}")
    common.log_usage(root, {"cmd": "distinct", "scope": "note"})
    return 0


def _distinct_pair(a: records.Memory, b: records.Memory, today: datetime.date) -> list[str]:
    for m in (a, b):
        records.log_before(m, "distinct")
    for m, other in ((a, b), (b, a)):
        records.update(m, today, distinct_from=sorted({*m.distinct_from, other.handle}))
    return [f"m:{a.handle}\tkept apart from m:{b.handle}"]


def cmd_distinct(args: argparse.Namespace) -> int:
    store = common._optional_store(args)
    if store is not None and store.is_dir() and (done := _distinct_notes(args, store)) is not None:
        return done

    def apply(found: list[records.Memory], today: datetime.date) -> list[str]:
        return _distinct_pair(found[0], found[1], today)

    return _two(args, args.a, args.b, "distinct", apply)


def _writable_store(args: argparse.Namespace, command: str) -> Path | None:
    root = args.root
    if not isinstance(root, Path) or not root.is_dir():
        print(
            common.no_store_message(os.environ) if root is None else common.NO_STORE,
            file=sys.stderr,
        )
        return None
    if not records.store_is_writable(root):
        print(
            f"mem: {command} writes to the store, which is read-only: it has no mem-store.yaml "
            '(create a store with "mem init").',
            file=sys.stderr,
        )
        return None
    return root


def _synthesis_ref_path(root: Path, ref: str) -> tuple[str, Path] | None:
    """The handle and file of the synthesis `ref` names; None when it names no synthesis (or a section of one)."""
    handle, section = document.split_ref(ref)
    path = document.path_of(root / document.SYNTHESES_DIR, handle)
    if section is not None or path is None or not path.is_file():
        return None
    return handle, path


def _synthesis_newest_group(root: Path, rel: str, path: Path, entry: dict | None) -> dict | None:
    """The logged group action (rename or remove) that is the newest change to a synthesis; None when its own entry is."""
    group = records.last_log_entry(
        _StoreLog(root / "note", rel)
    )  # a rename or remove logs its files as a group
    if (
        group is not None
        and group.get("group")
        and (entry is None or common._sha(path.read_bytes()) == group.get("after"))
    ):
        # the file is as the group's action left it (or has no own entry): the group is the newest change; when
        # the file differs, a change came after the group and its own entry is the one to undo
        return group
    return None


def _restore_logged_text(syn: document.Synthesis, entry: dict) -> bool:
    """Put back the text before the logged change; False, with the error printed, when the file cannot be written."""
    if entry["skipped"]:
        print(
            f"mem: skipped {entry['skipped']} unreadable lines in the curation log", file=sys.stderr
        )
    try:
        records.restore(syn, entry)
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return False
    return True


def _restore_synthesis(args: argparse.Namespace) -> int:
    root = _writable_store(args, "restore")
    if root is None:
        return 2
    located = _synthesis_ref_path(root, args.handle)
    if located is None:
        print(f"mem: no synthesis named {args.handle}", file=sys.stderr)
        return 2
    handle, path = located
    syn = document.Synthesis(path, handle)
    entry = records.last_log_entry(syn)
    rel = f"{document.SYNTHESES_DIR}/{path.name}"
    group = _synthesis_newest_group(root, rel, path, entry)
    if group is not None:
        return _restore_group(root, rel, group, f"s:{handle}")
    if entry is None:
        print(f"mem: no logged text for s:{handle}: nothing to restore", file=sys.stderr)
        return 2
    if not _restore_logged_text(syn, entry):
        return 2
    print(f"s:{handle}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]}")
    common.log_usage(root, {"cmd": "restore", "scope": "synthesis"})
    return 0


@dataclass
class _StoreLog:
    """A note's entry in the store-level `.curation-log` (the log sits beside `path`, the store's root)."""

    path: Path
    handle: str


def _restore_log_record(line: str) -> dict | None:
    """A curation log line as a record; None for a line that is not JSON or not an object."""
    try:
        logged = json.loads(line)
    except ValueError:
        return None
    return logged if isinstance(logged, dict) else None


def _restore_group_members(root: Path, entry: dict) -> list[tuple[int, dict]]:
    """The log lines (number, record) of the group `entry` belongs to that no restore has undone yet."""
    lines = (root / records.CURATION_LOG).read_text(encoding="utf-8").split("\n")
    members: list[tuple[int, dict]] = []
    undone: set[int] = set()
    for number, line in enumerate(lines):
        logged = _restore_log_record(line)
        if logged is None:
            continue
        if logged.get("action") == "restore" and isinstance(logged.get("undone"), int):
            undone.add(logged["undone"])
        elif logged.get("group") == entry["group"] and isinstance(logged.get("before"), str):
            members.append((number, logged))
    return [(n, e) for n, e in members if n not in undone]


def _restore_file_current(root: Path, e: dict) -> bool:
    """True when the file of the logged change is still as that change left it."""
    return (root / e["handle"]).is_file() and common._sha(
        (root / e["handle"]).read_bytes()
    ) == e.get("after")


def _restore_member(root: Path, e: dict, number: int, stamp: str) -> None:
    """Undo one logged file change (moving a renamed note and its sources back) and log the undo."""
    target = root / e.get("from", e["handle"])
    safe_io.replace_file(target, e["before"].encode("utf-8"))
    if "from" in e:
        (root / e["handle"]).unlink()
        sources, was = (
            root / common.SOURCES_DIR / Path(e["handle"]).stem,
            root / common.SOURCES_DIR / Path(e["from"]).stem,
        )
        if sources.is_dir() and not was.exists():
            sources.rename(was)
    marker = {"t": stamp, "action": "restore", "handle": e["handle"], "undone": number}
    safe_io.append_text(root / records.CURATION_LOG, json.dumps(marker, ensure_ascii=False) + "\n")


def _restore_members(
    root: Path, members: list[tuple[int, dict]], rebuild: bool, stamp: str
) -> None:
    for number, e in members:
        _restore_member(root, e, number, stamp)
    if rebuild:
        index_files.apply_index(root)


def _restore_group(root: Path, rel: str, entry: dict, label: str | None = None) -> int:
    """Undo every file of the unify, rename or distinct that logged `entry`, or none: refused when any changed since.

    A README listing that changed since is left alone (not a refusal) and rebuilt by `apply_index`; one that is
    as the action left it gets its exact previous bytes back."""
    members = _restore_group_members(root, entry)
    listing = {n: link_rules._is_index_readme(e["handle"]) for n, e in members}
    moved = [
        e["handle"] for n, e in members if not listing[n] and not _restore_file_current(root, e)
    ]
    if moved:
        print(
            f"mem: {', '.join(moved)} changed since {entry.get('action')}, so nothing was restored: "
            "restore or edit those files by hand",
            file=sys.stderr,
        )
        return 2
    kept = [(n, e) for n, e in members if not listing[n] or _restore_file_current(root, e)]
    rebuild = not any(listing.values()) or len(kept) < len(members)
    members = kept
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        _restore_members(root, members, rebuild, stamp)
    except (OSError, FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(
        f"{label or note_files._handle(rel)}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]} "
        f"({len(members)} files)"
    )
    common.log_usage(root, {"cmd": "restore", "scope": "note"})
    return 0


def _restore_note(args: argparse.Namespace, root: Path, note: Path) -> int:
    rel = note.relative_to(root.resolve()).as_posix()
    log = _StoreLog(root / "note", rel)
    entry = records.last_log_entry(log)
    if entry is None:
        print(
            f"mem: no logged text for {note_files._handle(rel)}: nothing to restore",
            file=sys.stderr,
        )
        return 2
    if entry.get("group"):
        return _restore_group(root, rel, entry)
    try:
        safe_io.replace_file(note, entry["before"].encode("utf-8"))
        marker = {
            "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "action": "restore",
            "handle": rel,
            "undone": entry["line"],
        }
        safe_io.append_text(
            root / records.CURATION_LOG, json.dumps(marker, ensure_ascii=False) + "\n"
        )
    except OSError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(
        f"{note_files._handle(rel)}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]}"
    )
    common.log_usage(root, {"cmd": "restore", "scope": "note"})
    return 0


def _restore_store_note(args: argparse.Namespace) -> int | None:
    """Restore the note of the store that `args.handle` names; None when it names no note."""
    if args.handle.startswith("m:"):
        return None
    store = common._optional_store(args)
    if store is None or not isinstance(found := common.resolve_note(store, args.handle), Path):
        return None
    root = _writable_store(args, "restore")
    return 2 if root is None else _restore_note(args, root, found)


def _restore_memory_text(found: list[records.Memory], today: datetime.date) -> list[str]:
    m = found[0]
    entry = records.last_log_entry(m)
    if entry is None:
        raise ValueError(f"no logged text for m:{m.handle}: nothing to restore")
    if entry["skipped"]:
        print(
            f"mem: skipped {entry['skipped']} unreadable lines in the curation log",
            file=sys.stderr,
        )
    records.restore(m, entry)
    return [f"m:{m.handle}\trestored to before {entry.get('action')} of {str(entry.get('t'))[:10]}"]


def cmd_restore(args: argparse.Namespace) -> int:
    if args.handle.startswith("s:"):
        return _restore_synthesis(args)
    if (done := _restore_store_note(args)) is not None:
        return done
    return _act(args, [args.handle], _restore_memory_text, "restore")


def _global_memory_exists(args: argparse.Namespace, handle: str) -> bool:
    """True when a readable global memory has this handle."""
    return any(
        m.handle == handle and m.error is None
        for m in records.load_memories(
            records.memories_root(os.environ, common._optional_store(args)), "global"
        )
    )


def _promote_mark(args: argparse.Namespace, target: str | None) -> int:
    """`mem promote --no` or `--done`: mark each lesson as not to be promoted, or promoted (to `target`)."""
    value, text = ("no", "not to be promoted") if args.no else ("done", "promoted")
    extra = {"general": target} if target else {}

    def apply(found, today):
        records.log_before(found[0], "promote")
        records.update(found[0], today, promote=value, **extra)
        return [f"m:{found[0].handle}\t{text}"]

    for handle in args.handles:
        if _act(args, [handle], apply, "promote") != 0:
            return 2
    return 0


def _promote_draft(args: argparse.Namespace) -> int:
    """`mem promote`: print the lessons to rewrite as one general lesson, and the command that records the promotion."""
    found = []
    for handle in args.handles:
        got = _memory_of(args, [handle])
        if got is None:
            return 2
        found.append(got[0])
    print('Draft for: mem remember --global --kind lesson --claim "\u2026"')
    for m in found:
        print(f"m:{m.handle}\t{' '.join(m.claim.split())}")
        if m.context:
            print(f"  context: {' '.join(m.context.split())}")
    print(
        "Rewrite the claim in general terms, with no name of a project, system, client or person, "
        "before you run it; then run: mem promote --done <h>"
    )
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    args.is_global = False
    if args.to and not args.done:
        print("mem: --to goes with --done.", file=sys.stderr)
        return 2
    target = args.to.removeprefix("m:") if args.to else None
    if args.to and not _global_memory_exists(args, args.to.removeprefix("m:")):
        print(f"mem: --to names no global memory: {args.to}", file=sys.stderr)
        return 2
    if args.no or args.done:
        return _promote_mark(args, target)
    return _promote_draft(args)


def _loaded(
    folders: Sequence[tuple[str, Path | None]],
) -> list[tuple[str, Path | None, list[records.Memory]]]:
    out = []
    for scope, folder in folders:
        loaded = records.load_memories(folder, scope)
        for m in loaded:
            if m.error is not None:
                print(f"mem: skipped {m.path}: {m.error}", file=sys.stderr)
        out.append((scope, folder, loaded))
    return out


def _flat(text: str) -> str:
    return " ".join(text.split())  # a hand-edited tab or newline must not add a column


def cmd_memories(args: argparse.Namespace) -> int:
    today = datetime.date.today()
    if args.project:
        named = common._other_projects([args.project], False)
        if named is None:
            return 2
        folder = common._named_folder(args.project)
        if folder is not None and not folder.is_dir():
            print(
                f"mem: the memory folder of project {args.project} was not found: {folder} (moved or deleted?)",
                file=sys.stderr,
            )
            return 2
        folders = [("project", folder)]
    else:
        folders = common._memory_folders(args)
        if not args.all:
            folders = [f for f in folders if (f[0] == "global") == args.is_global]
    shown = [
        m
        for _, _, loaded in _loaded(folders)
        for m in loaded
        if m.error is None
        and (args.kind is None or m.kind == args.kind)
        and (
            args.dead or records.is_live(m, today) or (args.quarantine and m.status == "active")
        )  # a lapsed lesson in quarantine is still listed
        and records.quarantined(m) == args.quarantine
    ]
    shown.sort(
        key=lambda m: (m.kind != "state", -(m.created or datetime.date.min).toordinal(), m.handle)
    )
    for m in shown:
        dead = common._memory_status(m, today)
        created = m.created.isoformat() if m.created else "undated"
        print(
            f"m:{m.handle}\t[{m.kind}, observed {m.observed}, {created}{common._unconfirmed(m)}"
            f"{', quarantine' if args.quarantine else ''}"
            f"{', ' + dead if dead else ''}]\t{_flat(m.claim)}"
        )
    return 0


RULES_OFF_NOTICE = "Loaded rules are switched off (plugin option loaded_rules): nothing below loads at session start."


def _rules_layout(arg: str | None = None) -> str:
    """`--layout` wins, then MEM_RULES_LAYOUT (set by the hooks from the option rules_layout); only `grouped` and `digest` switch."""
    env = os.environ.get("MEM_RULES_LAYOUT")
    return arg or (env if env in {"grouped", "digest"} else "flat")


def _rules_digest(
    global_lessons: list[records.Memory], today: datetime.date
) -> tuple[dict | None, dict | None]:
    """The digest file and the topics it may speak for, (None, None) when either cannot be read: callers then print without it."""
    try:
        data = digest_lessons.read(common.data_dir(os.environ))
        return (
            (data, digest_lessons.topics_of(global_lessons, today))
            if data["topics"]
            else (None, None)
        )
    except Exception:
        logger.debug("reading the rules digest failed", exc_info=True)
        return None, None


def _rules_off() -> bool:
    return os.environ.get("MEM_LOADED_RULES") == "off"


def _rules_read_targets(
    args: argparse.Namespace, pool: list[records.Memory], unread: list[records.Memory]
) -> list[records.Memory] | None:
    """The memories `--read` names (`all` is every unread short form); None, with the error printed, when one is not live."""
    if args.read == ["all"]:
        return unread
    targets = []
    for raw in args.read:
        name = raw.removeprefix("m:")
        hit = next(
            (m for m in pool if m.handle == name), None
        )  # project first: the order of the scopes
        if hit is None:
            print(f"mem: no live memory named {raw}", file=sys.stderr)
            return None
        targets.append(hit)
    return targets


def _rules_read_only_refused(args: argparse.Namespace, targets: list[records.Memory]) -> bool:
    """True, with the reason printed, when a target sits in a store that cannot be written."""
    store = common._optional_store(args)
    for m in targets:
        if common._read_only_store(store, m.path.resolve()):
            print(
                common._READ_ONLY_PROJECT if m.scope == "project" else common._READ_ONLY_MEMORIES,
                file=sys.stderr,
            )
            return True
    return False


def _rules_print_unread(unread: list[records.Memory]) -> None:
    for m in unread:
        print(f"m:{m.handle}\t{m.scope}\t{m.short}\n\tclaim: {_flat(m.claim)}")
    if not unread:
        print("No short form is waiting to be read.")


def _rules_mark_read(targets: list[records.Memory], today: datetime.date) -> None:
    for m in targets:
        if m.short_by:
            records.log_before(m, "edit")
            records.update(m, today, short_by=None)
        print(f"m:{m.handle}\tread")


def _rules_unread(args: argparse.Namespace, today: datetime.date) -> int:
    """`--unread` lists the short forms a model wrote that nobody read; `--read` marks them read."""
    if args.unread and args.read:
        print("mem: --unread and --read cannot be used together.", file=sys.stderr)
        return 2
    scopes = _loaded(common._memory_folders(args))
    pool = [
        m
        for _, _, loaded in scopes
        for m in loaded
        if m.error is None and records.is_live(m, today)
    ]
    unread = [m for m in pool if m.short_by == "model" and m.short]
    if args.unread:
        _rules_print_unread(unread)
        return 0
    targets = _rules_read_targets(args, pool, unread)
    if targets is None or _rules_read_only_refused(args, targets):
        return 2
    _rules_mark_read(targets, today)
    return 0


def _rules_stuck(
    choice: rules.Choice, root: Path | None, attempts: dict, today: datetime.date
) -> int:
    """How many established lessons without a short form the automatic fill will not write."""
    if _rules_off():
        return 0  # the pass skips the fill while the loaded rules are off (`cmd_auto` of mem-corroborate)
    return sum(
        1
        for m in choice.unready_lessons
        if (root is not None or m.scope != "project")
        and corroborate_decide.fill_wont_write(
            m, root if m.scope == "project" else None, attempts, today
        )
    )


def _rules_unready_sentence(choice: rules.Choice, stuck: int) -> str:
    """The line about the established lessons that have no short form yet, and who writes it."""
    unready = f"{choice.unready} established lesson{' has' if choice.unready == 1 else 's have'} no short form yet"
    if _rules_off():
        return unready + "."
    if stuck == choice.unready:
        return (
            unready
            + ": the automatic fill will not write "
            + f"{'it, so it needs' if stuck == 1 else 'them, so they need'} curation (mem curate)."
        )
    if stuck:
        return (
            unready
            + f": {stuck} need{'s' if stuck == 1 else ''} curation (mem curate), the background pass writes the "
            + f"{'other' if choice.unready - stuck == 1 else 'others'} when auto_capture is on (mem-corroborate status shows the last one)."
        )
    return (
        unready
        + ": the background pass writes them when auto_capture is on (mem-corroborate status shows the last one)."
    )


def _rules_more_line(m: records.Memory, why: str) -> str:
    """One row of `mem rules --more`: a lesson that was left out, and why."""
    claim = _flat(m.claim)
    claim = (
        claim
        if len(claim) <= _CLAIM_PREVIEW_CHARS
        else claim[: _CLAIM_PREVIEW_CHARS - 1] + "\u2026"
    )
    return f"m:{m.handle}\t{m.scope}\t{why}\t{rules.standing_words(m)}\t{m.topic or '-'}\t{claim}\t{records.mark_words(m) or '-'}"


def _rules_more(more: str | bool, choice: rules.Choice, unready: str) -> int:
    """`mem rules --more [topic]`: list the lessons left out of the loaded rules (all, or one topic)."""
    topic = None if more is True else more
    shown = [
        (m, why)
        for m, why in choice.left
        if topic is None or (m.topic or "other") == topic or (topic == "other" and not m.topic)
    ]
    order = [t for t, _ in rules.topic_counts(choice)] + [None]
    for group in order:
        for m, why in (x for x in shown if x[0].topic == group):
            print(_rules_more_line(m, why))
    if shown:
        print("mem show m:<handle> prints a whole lesson.")
    else:
        print("No lessons left out" + (f" under {topic}." if topic else "."))
    if choice.unready:
        print(unready)
    return 0


def _rules_print(
    args: argparse.Namespace,
    choice: rules.Choice,
    global_: list[records.Memory],
    today: datetime.date,
    unready: str,
) -> int:
    """Print the rules block, the index lines and the lessons that failed after they loaded."""
    digest_data, topics = _rules_digest(global_, today)
    lines = rules.block(choice, _rules_layout(args.layout), digest=digest_data, topics=topics)
    print("\n".join(lines) if lines else "No rules loaded.")
    index = rules.index_lines(choice, digest=digest_data, topics=topics)
    if index:  # also alone: index-only lessons are reachable when no rule loads
        print("\n".join(index))
    if not lines and choice.unready:
        print(unready)
    failed = [
        (m, words)
        for m in [*choice.loaded, *(m for m, why in choice.left if why == rules.OVER)]
        if (words := records.mark_words(m))
    ]
    if failed:
        print("Failed after it loaded:")
        for m, words in failed:
            print(f"m:{m.handle}\t{words}")
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    """Print the rules block and the line after it exactly as session start does; --more lists what was left out."""
    today = datetime.date.today()
    if args.unread or args.read:
        return _rules_unread(args, today)
    (_, _, project), (_, _, global_) = _loaded(common._memory_folders(args))
    try:
        root = records.project_root(Path.cwd(), os.environ)
    except OSError:
        root = None
    project = records.mark_repository(
        project, records.tracked_memories(root) if root else frozenset()
    )
    choice = rules.choose(project, global_, today)
    if _rules_off():
        print(RULES_OFF_NOTICE)
    stuck = _rules_stuck(choice, root, _fill_attempts(os.environ), today)
    unready = _rules_unready_sentence(choice, stuck)
    if args.more is not None:
        return _rules_more(args.more, choice, unready)
    return _rules_print(args, choice, global_, today, unready)


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
    return f"  m:{m.handle}  [{m.kind}, {created}{extra}]  {_flat(m.claim)}"


def _differ_in(a: str, b: str) -> str:
    words = records.differing_words(a, b)
    return f"differ in: {', '.join(words)}" if words else "differ in: wording only"


PAIR_WORK = 150_000  # claim comparisons the session start line may spend on pair searches, both folders together
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


def _fill_attempts(env: Mapping[str, str]) -> dict:
    """The automatic short-form fill's attempts (`fill_key` -> entry), read defensively: a missing, unreadable or
    malformed state reads as no attempts, so curation never fails on it."""
    data = common.data_dir(env)
    lessons = (
        jobs.read_json(data / "corroborate" / "fill-attempts.json").get("lessons") if data else None
    )
    return lessons if isinstance(lessons, dict) else {}


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
    for a, b, _ in records.pairs(kept, today, tokenize=tokenize, among=among, budget=budget):
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
            kept, today, tokenize=tokenize, among=among, budget=budget
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


def _note_line(note: Note) -> str:
    return (
        f"  {note_files._handle(note.rel)}  [{note.meta.get('confidence', '')}, {note.meta.get('updated', '')}]  "
        f"{_flat(str(note.meta.get('claim', '')))}"
    )


def _note_pairs(notes: Sequence[Note]) -> list[tuple[Note, Note]]:
    """Pairs of notes that share a topic and whose claims contain each other with at least `records.STRONG`,
    unless one names the other in `distinct_from`; the closest pair first."""
    notes = sorted(notes, key=lambda n: note_files._handle(n.rel))
    tokens = [set(tokenize(str(n.meta.get("claim", "")))) for n in notes]
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
    note: Note, name: str, synths: list[document.Synthesis], known: dict
) -> str | None:
    """The line of a note that is part of no synthesis though a synthesis covers its topic; None when none does."""
    topics = [t for t in note.meta.get("topics", []) if isinstance(t, str)]
    own = set(edit._own_topics(known, topics))
    covering = [x for x in synths if own & set(x.topics)]
    if not covering:
        return None
    return (
        f"  {name}  \u2192  {', '.join('s:' + x.handle for x in covering)}  "
        f"{_flat(str(note.meta.get('claim', '')))}"
    )


def _curate_notes_stale(
    note: Note, name: str, part: str, synths: list[document.Synthesis]
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
    note: Note, synths: list[document.Synthesis], known: dict, queues: _NoteQueues
) -> None:
    """Sort one knowledge note into the queues (disputed, not yet part of a synthesis, older than its section)."""
    if note.type != "knowledge" or note.error is not None or not isinstance(note.meta, dict):
        return
    if note_fields._disputed(note.meta.get("disputed")) is None:
        queues.disputed.append(
            f"  {note_files._handle(note.rel)}  {_flat(str(note.meta.get('claim', '')))}  "
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


def _curate_notes_same(live: list[Note]) -> list[str]:
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
    live: list[Note], synths: list[document.Synthesis], known: dict
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
        known = load_topics(root)
    except FrontmatterError:
        known = {}
    queues = _NoteQueues()
    for note in discover_notes(root):
        _curate_notes_file(note, synths, known, queues)
    out = _curate_notes_blocks(queues)
    live = [
        n
        for n in discover_notes(root)
        if n.error is None and isinstance(n.meta, dict) and n.meta.get("superseded_by") is None
    ]
    out += _curate_notes_same(live)
    out += _curate_notes_crowded(live, synths, known)
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
        found = _memory_of(args, [keep, drop])
    if found is None:
        return _last_error(err, "memories not found")
    refusal = _curate_merge_refusal(*found)
    if refusal is not None:
        return refusal
    ns = argparse.Namespace(**{**vars(args), "keep": keep, "drop": drop, "force": False})
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cmd_merge(ns)
    return None if code == 0 else _last_error(err, "the merge was refused")


def _curate_attach_refusal(root: Path, found: Path, target: str) -> str | None:
    """Why the note must not be attached automatically to `target`; None when the part's `Sources:` line links it and
    it is not part of a synthesis yet."""
    try:
        syn, sec = common._section_ref(root, target)
        part = split_frontmatter(note_files._read_text(found))[0].get("part_of")
    except (ValueError, OSError, FrontmatterError) as exc:
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


def _curate_new_since(args: argparse.Namespace) -> int:
    """Print how many global memories and notes of the store were written after `--new-since` (epoch seconds) and
    after the last curation pass of the global memories (its day counts as passed). File times: an edit counts as new.
    The trigger of `mem-auto`."""
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
    if store is not None and store.is_dir():
        paths += [store / n.rel for n in discover_notes(store) if n.error is None]
    count = 0
    for path in paths:
        try:
            count += path.stat().st_mtime > cutoff
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
        f"  m:{m.handle}  valid until {m.valid_until.isoformat()}  {_flat(m.claim)}"
        for m in expired
        if m.valid_until is not None
    ]
    return out


def _curate_seen_lines(found: Sequence[Decisions]) -> list[str]:
    frequent = [m for d in found for m in d.seen]
    if not frequent:
        return []
    out = [f"seen {_FREQUENT} times or more: general enough for a global lesson? (mem promote <h>)"]
    out += [f"  m:{m.handle}  observed {m.observed}  {_flat(m.claim)}" for m in frequent]
    return out


def _curate_stale_lines(found: Sequence[Decisions]) -> list[str]:
    stale = [m for d in found for m in d.stale]
    if not stale:
        return []
    out = [f"not confirmed in {_STALE_DAYS} days (decide: mem confirm <h> or mem forget <h>)"]
    out += [
        f"  m:{m.handle}  {m.created.isoformat()}  {_flat(m.claim)}"
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
            f"{_flat(m.claim)}"
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
        state = "rules off" if _rules_off() else "loaded" if loaded else "left out by the cap"
        note = records.reword_note(m)
        out.append(f"  m:{m.handle}  {state}{'; ' + note if note else ''}  {_flat(m.claim)}")
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
            f"  m:{m.handle}  {m.weight or 'medium'}, {n} session{'' if n == 1 else 's'}  {_flat(m.claim)}"
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
    out += [f"  m:{m.handle}  {_flat(m.claim)}" for m in nofill]
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
    scopes = _loaded(folders)
    attempts = _fill_attempts(os.environ)
    if args.done:
        return _curate_done(args, scopes, attempts, today)
    return _curate_report(args, scopes, attempts, today)


def _settle_actions() -> settle_verdicts.Actions:
    return settle_verdicts.Actions(_merge_pair, _supersede_pair, _distinct_pair)


def _settle_reason_ok(reason: str) -> bool:
    return (
        not common._refuse_secret([reason]) and common._check_terms([reason], "lesson", False) == 0
    )


def _settle_missing_folder(command: str) -> int:
    """The exit code of a settle subcommand when there is no global memories folder."""
    if command == "due":
        return 1
    if command in {"pending", "log"}:
        return 0
    print("mem: there is no global memories folder.", file=sys.stderr)
    return 2


def _settle_due(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    count = settle_verdicts.due(folder, args.minutes, time.time(), today)
    if count is None:
        return 1
    print(count)
    return 0


def _settle_pending(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    with settle_verdicts.locked(folder):
        state = settle_verdicts.load_state(folder)
        found = settle_verdicts.pending(
            records.load_memories(folder, "global"), state, today, tokenize=tokenize
        )
        settle_verdicts.offer(folder, state, found, time.time())
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
    else:
        for p in found:
            flagged = f"  flagged: {', '.join(p['flagged_words'])}" if p["flagged_words"] else ""
            print(
                f"pair {p['pair']}  newer: m:{p['newer']}{flagged}\n  m:{p['a']}\t{p['claim_a']}\n  "
                f"m:{p['b']}\t{p['claim_b']}"
            )
    return 0


def _settle_apply(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    try:
        rows = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"mem: cannot read the verdicts: {exc}", file=sys.stderr)
        return 2
    try:
        with settle_verdicts.locked(folder):
            lines = settle_verdicts.apply_verdicts(
                folder,
                records.load_memories(folder, "global"),
                rows,
                today,
                time.time(),
                actions=_settle_actions(),
                reason_ok=_settle_reason_ok,
                tokenize=tokenize,
            )
    except settle_verdicts.NoListing as exc:
        print("\n".join(exc.lines))
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


def _settle_log(args: argparse.Namespace, folder: Path, _today: datetime.date) -> int:
    out = settle_verdicts.listing(folder, args.all)
    if out:
        print("\n".join(out))
    return 0


def _settle_ack(_args: argparse.Namespace, folder: Path, _today: datetime.date) -> int:
    print(f"acknowledged {settle_verdicts.ack(folder)}")
    return 0


def _settle_undo(args: argparse.Namespace, folder: Path, today: datetime.date) -> int:
    try:
        with settle_verdicts.locked(folder):
            print("\n".join(settle_verdicts.undo(folder, args.number, today)))
    except settle_verdicts.NothingToUndo as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    return 0


_SETTLE_HANDLERS: dict[str, Callable[[argparse.Namespace, Path, datetime.date], int]] = {
    "due": _settle_due,
    "pending": _settle_pending,
    "apply": _settle_apply,
    "log": _settle_log,
    "ack": _settle_ack,
}  # any other subcommand is `undo`


def cmd_settle(args: argparse.Namespace) -> int:
    """`mem settle`: the engine side of settling new global memories (see settle.py)."""
    store = common._optional_store(args)
    folder = records.memories_root(os.environ, store)
    command = args.settle_command
    if folder is None or not folder.is_dir():
        return _settle_missing_folder(command)
    if common._read_only_store(store, folder.resolve()):
        print(common._READ_ONLY_MEMORIES, file=sys.stderr)
        return 2
    today = datetime.date.today()
    try:
        return _SETTLE_HANDLERS.get(command, _settle_undo)(args, folder, today)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2


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
    remember_parser.set_defaults(func=cmd_remember)


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
    index_cmd.set_defaults(func=cmd_session_index)
    compact_cmd = sub.add_parser(
        "compact-log", help="check the handoff block of a compaction summary and log counts"
    )
    compact_cmd.add_argument(
        "--hook", action="store_true", help="read the hook's JSON from standard input"
    )
    compact_cmd.set_defaults(func=cmd_compact_log)
    signal_cmd = sub.add_parser(
        "signal", help="print the records related to a brief read from standard input"
    )
    signal_cmd.add_argument(
        "--hook",
        action="store_true",
        help="read a PreToolUse hook's JSON from standard input and print the brief with the signal appended",
    )
    signal_cmd.set_defaults(func=cmd_signal)


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
        confirm_parser.set_defaults(func=cmd_confirm)
    _parser_memory_command(
        sub, "refute", "mark a memory refuted", "handle", because=True
    ).set_defaults(func=cmd_refute)
    _parser_memory_command(
        sub, "forget", "mark a memory forgotten", "handle", because=True
    ).set_defaults(func=cmd_forget)


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
    triage_parser.set_defaults(func=cmd_triage)


def _parser_add_memory_pairs(sub: Any) -> None:
    _parser_memory_command(
        sub, "supersede", "mark OLD as superseded by NEW", "old", "new"
    ).set_defaults(func=cmd_supersede)
    merge_parser = _parser_memory_command(
        sub, "merge", "add DROP's count and body to KEEP and supersede DROP", "keep", "drop"
    )
    merge_parser.add_argument(
        "--force",
        action="store_true",
        help="merge although the claims differ by a negation or a number",
    )
    merge_parser.set_defaults(func=cmd_merge)
    _parser_memory_command(
        sub,
        "distinct",
        "record that two memories are different claims: the queue stops pairing them",
        "a",
        "b",
    ).set_defaults(func=cmd_distinct)
    _parser_memory_command(
        sub, "restore", "put back the text a memory had before its last curation action", "handle"
    ).set_defaults(func=cmd_restore)
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
    promote_parser.set_defaults(func=cmd_promote)


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
    memories_parser.set_defaults(func=cmd_memories)
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
    rules_parser.set_defaults(func=cmd_rules)
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
    curate_parser.set_defaults(func=cmd_curate)


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
    settle_parser.set_defaults(func=cmd_settle)


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
    memory_parser.set_defaults(func=cmd_memory)


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
