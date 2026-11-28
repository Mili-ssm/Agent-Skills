#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.15"  # an upper bound: a newer Python may have no prebuilt pyyaml yet
# dependencies = ["pyyaml"]
# ///
"""Memory engine: parsing primitives and the mem commands."""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING, Any

from commands import (
    admin,
    common,
    curate,
    edit,
    hooks,
    integrate,
    memory,
    read,
    sources,
    split,
    synthesis,
)
from commands.diagnostics import add_parser as _parser_add_diagnostics
from commands.install import add_parser as _parser_add_install
from core import config, safe_io
from memories import matching, records, rules
from notes import check as check_rules
from notes import due as due_queries
from notes import fields as note_fields
from notes import index as index_files
from notes import links as link_rules
from notes import note as note_files
from notes import search as note_search
from notes.fields import (
    LEVELS,
)
from notes.index import (
    INDEX_FOLDERS,
)
from syntheses import project as project_syntheses

if TYPE_CHECKING:
    import datetime
    from collections.abc import Mapping
    from pathlib import Path


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
    "commands.synthesis": synthesis,
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
    "FrontmatterError": "notes.note",
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
    "_write_logged_changes": "commands.synthesis",
    "_write_marks": "commands.curate",
    "_write_passes": "commands.curate",
    "_yaml_problem": "notes.note",
    "_year": "notes.fields",
    "ancestors": "notes.note",
    "apply_index": "notes.index",
    "build_corpus": "notes.search",
    "check": "notes.check",
    "data_dir": "commands.common",
    "descendants": "notes.note",
    "discover_notes": "notes.note",
    "find": "notes.search",
    "html_to_text": "commands.sources",
    "key_line": "notes.note",
    "leaf_topics": "notes.note",
    "load_topics": "notes.note",
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
    "split_frontmatter": "notes.note",
    "tokenize": "memories.matching",
    "topic_tree": "commands.read",
    "unlinked_mentions": "notes.search",
}


def __getattr__(name: str) -> object:
    if module := _MOVED.get(name):
        return getattr(_MOVED_MODULES[module], name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    "install-command",
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
    recover = sub.add_parser("import-recover", help="roll back an interrupted import")
    recover.set_defaults(func=sources.cmd_import_recover)
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
    ps_parser.set_defaults(func=synthesis.cmd_project_synthesis)


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


def _parser_add_synthesis(sub: Any) -> None:
    synthesis_parser = sub.add_parser(
        "synthesis", help="create and extend syntheses, the long documents behind notes"
    )
    synthesis_sub = synthesis_parser.add_subparsers(dest="synthesis_command", required=True)
    _parser_synthesis_write(synthesis_sub)
    synthesis.parser_sections(synthesis_sub, _OWNER_APPROVED)
    synthesis.parser_links(synthesis_sub)
    integrate.register(synthesis_sub)
    split.register(synthesis_sub)
    synthesis_parser.set_defaults(func=synthesis.cmd_synthesis)


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
        _parser_add_install,
        _parser_add_diagnostics,
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
    writes = (
        args.command in _WRITE_COMMANDS
        or (args.command == "synthesis" and args.synthesis_command in _SYNTHESIS_WRITES)
        or (
            args.command == "synthesis"
            and args.synthesis_command == "split"
            and bool(args.apply or args.undo or args.recover)
        )
    )
    if writes and not records.store_is_writable(root):
        return (
            f"mem: {args.command} writes to the store, which is read-only: it has no mem-store.yaml "
            '(create a store with "mem init").'
        )
    return None


def _dispatch_store(args: argparse.Namespace) -> int | None:
    """Resolve the store into `args.root`; the exit code of a refusal, or None to run the command."""
    if args.command in {"init", "diagnostics", "terms", "history"}:
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
