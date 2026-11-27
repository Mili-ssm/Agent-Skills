"""The hook handlers (A5, ADR 0028): `session-index`, `compact-log` and `signal`, with the logic only they use (the session start text, its due counts and notices, the compact summary check, the signal text)."""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

from capture import state as capture_state
from core import auto_state, jobs
from memories import records, rules
from session import handoff
from session import notices as session_notices
from settle import state as settle_state

from commands import common, curate, install

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence

logger = logging.getLogger(__name__)


_INDEX_HEAD = "memory: the mem command searches notes and memories (skill: memory)."
_INDEX_RULES = (
    _INDEX_HEAD + "\n"
    '- Before you act on this project, change something or research a topic: mem search "<topic in English>". '
    "It returns decisions, constraints and pitfalls recorded earlier that the files do not show.\n"
    "- To remember: preferences and personal matters -> auto memory; what a later session would need (a decision, "
    "constraint, pitfall or finding) -> mem remember, in English, with --global if it holds in any project and names "
    "no business; the project's current situation -> both."
)
# Codex has no auto memory (a Claude Code feature) and no memory:* subagents: its variants of the lines above.
_INDEX_RULES_CODEX = _INDEX_RULES.replace(
    "preferences and personal matters -> auto memory; what", "what"
).replace(
    "; the project's current situation -> both.",
    "; the project's current situation -> mem remember too.",
)
# Only a project with a live state memory has written state for the status checker to read (ADR 0030).
_STATUS_LINE = (
    "- Resuming earlier work, or asked where things stand: dispatch memory:memory-status-checker "
    "before reading plans or the backlog yourself."
)
_STATUS_LINE_CODEX = (
    "- Resuming earlier work, or asked where things stand: read the project's state memories with "
    "`mem memories --kind state` before reading plans or the backlog yourself."
)
_INDEX_LIMIT = 1500
_CLAIM_LIMIT = 100


_SUPERSEDED_LINE = re.compile(r"^superseded_by:", re.MULTILINE)


def _host() -> str:
    """The host that runs the hook: `codex` when the hook sets MEM_HOST=codex, otherwise `claude`."""
    return "codex" if os.environ.get("MEM_HOST") == "codex" else "claude"


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
    found = curate._decisions(
        loaded,
        scan.today,
        since=(scan.passes or {}).get(key),
        budget=scan.budget,
        attempts=common._fill_attempts(os.environ),
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
        lines.append(f"Global memories: {len(common._readable(loaded_global, today))}.")
    return lines


def _index_due_line(due: dict[str, int], complete: bool) -> list[str]:
    total = sum(due.values())
    if not total:
        return []
    parts = ", ".join(
        f"{due[label]} {label}" for label in curate._DECISION_LABELS.values() if label in due
    )
    action = (
        "run a curation pass with the memory-curation skill"
        if _host() == "codex"
        else "dispatch memory:memory-curator"
    )
    return [
        (
            f"Curation due: {'' if complete else 'at least '}{total} {'item' if total == 1 else 'items'} "
            f"({parts}) (after the current task: {action})."
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
        1 for _, loaded in curate._got_worse(loaded_project, loaded_global, today, choice) if loaded
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
    codex = _host() == "codex"
    lines = [" ".join(head), *(_INDEX_RULES_CODEX if codex else _INDEX_RULES).split("\n")[1:]]
    if any(m.kind == "state" for m in mine):
        lines.append(_STATUS_LINE_CODEX if codex else _STATUS_LINE)
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
    layout = common._rules_layout()
    digest, topics = common._rules_digest(loaded_global, today)
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
    rules_off = common._rules_off()
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
        passes=curate.read_passes(os.environ),
        notice=notice,
        stats=stats,
        marks=curate.read_marks(os.environ),
        tracked=records.tracked_memories(project) if project else frozenset(),
    )


def cmd_session_index(args: argparse.Namespace) -> int:
    """Never fails: the rules matter most when nothing is configured yet. Writes only the hook log and the plugin-root record, with --hook,
    and the day's due-note count (session_notices.DUE_CACHE_NAME)."""
    started = time.monotonic()
    data = _hook_input() if args.hook else {}
    stats: dict[str, int] = {}
    try:
        text = _session_text(args, data, stats)
    except Exception:
        logger.debug("building the session start text failed", exc_info=True)
        text = _INDEX_RULES_CODEX if _host() == "codex" else _INDEX_RULES
        stats.clear()
    if args.hook:
        install.record_root()
    if _host() == "codex" and install.launcher_missing():
        mem = shlex.quote(str(install.plugin_root() / "bin" / "mem"))
        text += (
            f"\nmemory: mem is not installed as a command; run it as {mem}, "
            f"or install it once: {mem} install-command"
        )
    print(text)
    if args.hook:
        source = data.get("source")
        common._log_hook({
            "hook": "session-index",
            "host": _host(),
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
    return records.related_records(
        found, [], given.brief, datetime.date.today(), tokenize=records.tokenize
    )


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


PAIR_WORK = 150_000  # claim comparisons the session start line may spend on pair searches, both folders together
