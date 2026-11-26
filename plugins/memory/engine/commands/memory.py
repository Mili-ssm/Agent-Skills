"""The memory-lifecycle handlers (A5, ADR 0028): `remember`, `confirm` (and `observe`), `refute`, `forget`, `triage`, `supersede`, `merge`, `distinct`, `restore`, `promote`, `memories`, `rules`, `memory` (edit) and `settle`, with the logic only they use."""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from core import safe_io
from corroborate import decide as corroborate_decide
from memories import model, records, rules
from notes import index as index_files
from notes import links as link_rules
from notes import note as note_files
from settle import state as settle_state
from settle import verdicts as settle_verdicts
from syntheses import document
from syntheses import edit as synthesis_edit

from commands import common

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)


_CLAIM_PREVIEW_CHARS = 160  # a claim longer than this is cut in a listing


def _register_project(project: Path | None) -> None:
    """Record the project in the local registry; never fails or prints, the command it follows has succeeded."""
    if project is None:
        return
    try:
        records.register_project(common.data_dir(os.environ), project, datetime.date.today())
    except Exception:
        logger.debug("registering the project failed", exc_info=True)


def _same_claim(a: str, b: str) -> bool:
    """Exact duplicate by word sequence in any script; claims with no word characters compare as stripped text."""
    wa, wb = re.findall(r"\w+", a.casefold()), re.findall(r"\w+", b.casefold())
    return wa == wb if wa or wb else a.strip() == b.strip()


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
        return common._memory_body(args.body_file)
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
        common._readable(live, today),
        records.tokenize(args.claim),
        today,
        tokenize=records.tokenize,
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
    meta, _, _ = note_files.split_frontmatter(text)
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
    except (OSError, ValueError, note_files.FrontmatterError) as exc:
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
    except (OSError, note_files.FrontmatterError) as exc:
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
    if common._rules_off():
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
    if common._rules_off():
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
    digest_data, topics = common._rules_digest(global_, today)
    lines = rules.block(
        choice, common._rules_layout(args.layout), digest=digest_data, topics=topics
    )
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
    if common._rules_off():
        print(RULES_OFF_NOTICE)
    stuck = _rules_stuck(choice, root, common._fill_attempts(os.environ), today)
    unready = _rules_unready_sentence(choice, stuck)
    if args.more is not None:
        return _rules_more(args.more, choice, unready)
    return _rules_print(args, choice, global_, today, unready)


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
            records.load_memories(folder, "global"), state, today, tokenize=records.tokenize
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
                tokenize=records.tokenize,
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
