"""mem-corroborate: `fill`, the short form and topic of the lessons that lack them."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

import auto_state as au
import corroborate
import corroborate_run
import corroborate_state
import records
import rules
import shortcheck

logger = logging.getLogger(__name__)

ATTEMPTS_NAME = "fill-attempts.json"


CHECK_REFUSAL = "the checker did not find the short form faithful to the claim"


APPLY_REFUSAL = "mem refused to write the short form"


def _scope(project: Path | None, names: dict) -> str:
    return "global" if project is None else names.get(project, str(project))


def _dry_run_refusal(args) -> int | None:
    """The exit code of a dry run that cannot start, or None."""
    if not args.claude:
        print(
            "mem-corroborate: no claude binary (--claude, CLAUDE_CODE_EXECPATH or PATH)",
            file=sys.stderr,
        )
        return 1
    folder = Path(args.out).expanduser().resolve().parent
    if not (folder.is_dir() and os.access(folder, os.W_OK | os.X_OK)):
        print(
            f"mem-corroborate: --out: {folder} is not a folder that can be written", file=sys.stderr
        )
        return 2
    repo = corroborate_run.repo_above(folder)
    if repo is not None:
        print(
            f"mem-corroborate: --out is inside a repository ({repo}); the result holds memory text",
            file=sys.stderr,
        )
        return 2
    return None


def _propose_in(args, scratch: Path, candidates: list) -> tuple[dict, list[str], float] | None:
    """One writer session in `scratch`: (the kept items, the reasons for the dropped ones, the cost), or None when
    the session failed."""
    settings = scratch / "settings.json"
    corroborate_state.write_private(settings, json.dumps({"disableAllHooks": True}))
    work = scratch / "fill"
    work.mkdir(mode=0o700)
    corroborate_state.write_private(work / "lessons.txt", corroborate.fill_lines(candidates))
    out = work / "fill.json"
    brief = corroborate_run.FILL_BRIEF.format(lessons=work / "lessons.txt", out=out)
    limits = corroborate_run.SessionLimits(corroborate_run.PROPOSE_MODEL, args.budget)
    done = corroborate_run.run_session(
        corroborate_run.session_cmd(args.claude, work, brief, settings, limits), work
    )
    if not done["has_result"] or done["error"]:
        print("mem-corroborate: the session failed; nothing was written", file=sys.stderr)
        return None
    kept, reasons = corroborate.validate_fill(
        corroborate_run.read_object(out), [i for i, _m in candidates]
    )
    return kept, reasons, done["cost"]


def _propose(args, candidates: list) -> tuple[dict, list[str], float] | None:
    scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-fill-"))
    try:
        return _propose_in(args, scratch, candidates)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _dry_items(kept: dict, by_id: dict, where: dict, names: dict) -> list[dict]:
    """The file the owner edits: an item for every candidate; one with no proposal says so in `problem`."""
    for ident in by_id:
        kept.setdefault(ident, {"short": "", "topic": "", "problem": "no proposal"})
    items = []
    for ident, fields in kept.items():
        m = by_id[ident]
        items.append({
            "id": ident,
            "handle": m.handle,
            "scope": _scope(where[ident], names),
            "claim": m.claim,
            "short": fields["short"],
            "topic": fields["topic"],
            "load": "index" if m.load == "index" else "yes",
            "claim_digest": corroborate.claim_digest(m),
            **({"problem": fields["problem"]} if "problem" in fields else {}),
        })
    return items


def _write_dry_run(args, items: list[dict], asked: int, reasons: list[str], cost: float) -> None:
    to_edit = sum("problem" in i for i in items)
    corroborate_state.write_private(
        Path(args.out).expanduser(), json.dumps(items, ensure_ascii=False, indent=1) + "\n"
    )
    print(
        f"mem-corroborate: fill: {asked} lessons asked, {len(items) - to_edit} kept, {to_edit} to edit, {len(reasons)} dropped, "
        f"cost {cost:.3f} USD; read {args.out}, edit or cut it, then run fill --items {args.out}"
    )
    for why in reasons:
        print(f"  not kept: {why}", file=sys.stderr)


def fill_dry_run(args) -> int:
    refused = _dry_run_refusal(args)
    if refused is not None:
        return refused
    try:
        _data, projects, gfolder, names = corroborate_run._fill_world()
    except ValueError as exc:
        print(f"mem-corroborate: registry unreadable: {exc}", file=sys.stderr)
        return 1
    candidates = corroborate.fill_candidates(projects, gfolder, datetime.date.today())
    where = {i: p for i, p, _m in corroborate.fill_records(projects, gfolder)}
    kept: dict[str, dict] = {}
    reasons: list[str] = []
    cost = 0.0
    if candidates:
        proposed = _propose(args, candidates)
        if proposed is None:
            return 1
        kept, reasons, cost = proposed
    items = _dry_items(kept, dict(candidates), where, names)
    _write_dry_run(args, items, len(candidates), reasons, cost)
    return 0


LOAD_FLAGS = {"yes": ["--load"], "index": ["--index-only"], "no": ["--no-load"]}


class _Item(NamedTuple):
    """An item of the fill file that has an id, a short form and a topic; `load` is the item's own value, unchecked."""

    ident: str
    short: str
    topic: str
    load: object
    raw: dict


class _Known(NamedTuple):
    project: Path | None
    m: records.Memory
    scope: str


class _Outcome:
    def __init__(self) -> None:
        self.written = self.dropped = self.failed = 0
        self.applied: list[str] = []
        self.refused: list[str] = []

    def as_dict(self) -> dict:
        return {
            "written": self.written,
            "dropped": self.dropped,
            "failed": self.failed,
            "applied": self.applied,
            "refused": self.refused,
        }


def _parse_item(raw: object, user_read: bool) -> _Item | None:
    """None when `raw` is not an object with a string id, short and topic. Without `user_read` the item's `load` is ignored."""
    if not isinstance(raw, dict):
        return None
    ident, short, topic = raw.get("id"), raw.get("short"), raw.get("topic")
    if not (isinstance(ident, str) and isinstance(short, str) and isinstance(topic, str)):
        return None
    return _Item(ident, short, topic, raw.get("load") if user_read else None, raw)


def _valid_load(load: object) -> bool:
    """`load` comes from a file the owner edits: any JSON value, a list included, so it is never hashed."""
    return isinstance(load, str) and load in {"yes", "index", "no"}


def _load_flags(load: object) -> list[str]:
    return LOAD_FLAGS.get(load, []) if isinstance(load, str) else []


class _Filler:
    """Applies the items one at a time into the records, journaling them in a run folder."""

    def __init__(self, run: Path, user_read: bool) -> None:
        _data, projects, gfolder, names = corroborate_run._fill_world()
        au.private_dir(run)
        corroborate_state.write_private(
            run / "fill", ""
        )  # marks the run: its undo leaves the pass's `seen.json` alone
        self.user_read = user_read
        self.known = {
            i: _Known(p, m, _scope(p, names))
            for i, p, m in corroborate.fill_records(projects, gfolder)
        }
        self.applier = corroborate_run.Applier(
            corroborate_state.Journal(run), {}, gfolder, run, self._log
        )
        self.outcome = _Outcome()
        self.used: set[str] = set()
        self.today = datetime.date.today()

    def _log(self, text: str) -> None:
        fd = os.open(self.applier.cwd / "log.txt", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def _refusal(self, item: _Item) -> str | None:
        if item.ident not in self.known:
            return f"unknown id {item.ident}"
        if item.ident in self.used:
            return f"repeats {item.ident}"
        if not records.valid_short(item.short):
            return "short is not one line of at most 120 characters"
        if not records.valid_topic(item.topic):
            return "topic is not one or two lowercase words"
        if self.user_read and "load" in item.raw and not _valid_load(item.load):
            return "load must be yes, index or no"
        return self._record_refusal(item)

    def _record_refusal(self, item: _Item) -> str | None:
        _project, m, scope = self.known[item.ident]
        if item.raw.get("handle", m.handle) != m.handle or item.raw.get("scope", scope) != scope:
            return "handle or scope does not match its id"
        turned_on = (
            m.load == "no" and item.load is not None
        )  # a record turned off may be turned on again by an item that names `load`
        if m.triage == "pending" or not rules.eligible(
            dataclasses.replace(m, load=None) if turned_on else m, self.today
        ):
            return "not a lesson that can load"
        return None

    def _edit(self, item: _Item, known: _Known) -> bool:
        project, m, _scope_name = known
        watched = (
            [m.path]
            if project is not None
            else [m.path, m.path.parent / corroborate_run.SETTLE_STATE]
        )  # an edit of a global record may update it
        before = self.applier.journal.watch(watched)
        done = self.applier.mem(
            [
                "memory",
                "edit",
                f"m:{m.handle}",
                *(["--global"] if project is None else []),
                f"--short={item.short}",
                *(["--user-read"] if self.user_read else []),
                f"--topic={item.topic}",
                *_load_flags(item.load),
            ],
            project,
            drop_env=corroborate_run.SETTLE_VARS,
        )
        self.applier.journal.commit("fill", before)
        return done is not None and done.returncode == 0

    def step(self, n: int, raw: object) -> None:
        out = self.outcome
        item = _parse_item(raw, self.user_read)
        why = "not an object with id, short and topic" if item is None else self._refusal(item)
        if item is None or why:
            out.dropped += 1
            self._log(f"item {n} dropped: {why}")
            return
        self.used.add(item.ident)
        known = self.known[item.ident]
        if item.raw.get("claim_digest") != corroborate.claim_digest(known.m):
            out.failed += 1
            self._log(f"item {n} failed: {item.ident} changed its claim since the file was made")
        elif self._edit(item, known):
            out.written += 1
            out.applied.append(item.ident)
        else:
            out.failed += 1
            out.refused.append(item.ident)
            self._log(f"item {n} failed: mem refused or could not run for {item.ident}")


def apply_fill(items: list[dict], run: Path, user_read: bool) -> dict:
    """Writes the items into the records and journals them in `run` (the caller holds the run lock). Returns
    {"written", "dropped", "failed", "applied", "refused"}; `applied` holds the id of each item written and `refused`
    the id of each one `mem memory edit` refused. Without `user_read` (the automatic fill) an item never sets `load`:
    a record turned off is dropped, and a record's load stays as the owner has it."""
    filler = _Filler(run, user_read)
    for n, item in enumerate(items, start=1):
        filler.step(n, item)
    return filler.outcome.as_dict()


def _apply_items(items: list, cdir: Path) -> int:
    start = time.time()
    run = cdir / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-fill"
    result = apply_fill(items, run, user_read=True)
    written, dropped, failed = result["written"], result["dropped"], result["failed"]
    line = {
        "t": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "fill": {"asked": len(items), "written": written, "dropped": dropped, "failed": failed},
        "ms": int((time.time() - start) * 1000),
    }
    corroborate_state.append_log(cdir, line)
    print(
        f"mem-corroborate: fill: {len(items)} asked, {written} written, {dropped} dropped, {failed} failed; "
        f"undo with: mem-corroborate undo {run.name}"
    )
    return 1 if failed else 0


def fill_items(args) -> int:
    path = Path(args.items).expanduser()
    items = corroborate_run.read_object(path)
    if not isinstance(items, list):
        print(f"mem-corroborate: {path} is not a JSON list of items", file=sys.stderr)
        return 2
    cdir = corroborate_state.corroborate_dir(corroborate_state.data_dir())
    lock = au.take_run_lock(cdir)
    if lock is None:
        print("mem-corroborate: a run is going: try again later", file=sys.stderr)
        return 1
    try:
        return _apply_items(items, cdir)
    except Exception as exc:
        logger.debug("fill failed", exc_info=True)
        print(f"mem-corroborate: fill failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        os.close(lock)


def _fill_state(cdir: Path) -> dict:
    """The automatic fill's memory, read defensively: a missing or broken file is an empty state."""
    data = au.read_json(cdir / ATTEMPTS_NAME)
    lessons = data.get("lessons")
    failures = data.get("failures")
    lessons = (
        {k: v for k, v in lessons.items() if isinstance(v, dict)}
        if isinstance(lessons, dict)
        else {}
    )
    failures = failures if isinstance(failures, dict) else {}
    count = failures.get("count")
    return {
        "lessons": lessons,
        "failures": {
            "count": count if isinstance(count, int) and count > 0 else 0,
            "fingerprint": failures.get("fingerprint"),
        },
    }


def _fill_run_folder(cdir: Path) -> Path:
    """`<stamp>-<pid>-fill`, with a number before `-fill` when a run of this process already took the second."""
    base = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    run, n = cdir / "runs" / f"{base}-fill", 1
    while run.exists():
        n += 1
        run = cdir / "runs" / f"{base}-{n}-fill"
    return run


def fill_auto(claude: str | None, budget: float) -> dict:
    """Writes the short forms of the lessons that lack one, with nobody reading them first: a writer session, the
    code check (`shortcheck`), a second session that checks the survivors against their claims, then `apply_fill`.
    Every doubt ends in not writing. A session with no usable answer is a failed session: no lesson is charged an
    attempt and nothing is applied. The result holds numbers and `stopped` only; the same dict is the saved status."""
    cdir = corroborate_state.corroborate_dir(corroborate_state.data_dir())
    result = {
        "asked": 0,
        "written": 0,
        "dropped": 0,
        "refused_code": 0,
        "refused_check": 0,
        "to_triage": 0,
        "left": 0,
        "cost": 0.0,
        "stopped": None,
    }
    lock = au.take_run_lock(cdir)
    if lock is None:
        return {**result, "stopped": "a run is going"}
    try:
        return _fill_locked(claude, budget, cdir, result)
    finally:
        os.close(lock)


class _SessionError(Exception):
    """A session gave no usable answer; the message says which."""


class _Lesson(NamedTuple):
    m: records.Memory
    project: Path | None
    key: str
    digest: str


@dataclasses.dataclass
class _Auto:
    """One automatic fill: the lessons asked, the attempts state and the status the run saves."""

    cdir: Path
    result: dict
    state: dict
    lessons: dict[str, _Lesson]
    names: dict
    gfolder: Path | None
    fingerprint: str

    def save(self) -> None:
        au.write_json(self.cdir / ATTEMPTS_NAME, self.state)


class _Verdicts(NamedTuple):
    reason: dict[str, str]  # id -> why the lesson was refused
    passed: list[tuple[str, dict]]
    faithful: dict[str, bool]


def _finish(cdir: Path, result: dict, **changes) -> dict:
    result.update(changes)
    result["cost"] = round(result["cost"], 6)
    corroborate_state.save_status(cdir, fill=dict(result))
    return result


def _lessons(projects: list, gfolder: Path | None, state: dict) -> dict[str, _Lesson]:
    candidates = corroborate.fill_candidates(
        projects, gfolder, datetime.date.today(), attempts=state["lessons"]
    )
    where = {i: p for i, p, _m in corroborate.fill_records(projects, gfolder)}
    return {
        i: _Lesson(
            m, where[i], corroborate.fill_key(where[i], m.handle), corroborate.claim_digest(m)
        )
        for i, m in candidates
    }


def _plan(cdir: Path, result: dict) -> _Auto | dict:
    """The run's context, or the finished status when there is nothing to ask or the run must wait."""
    try:
        _data, projects, gfolder, names = corroborate_run._fill_world()
    except ValueError:
        return _finish(cdir, result, stopped="the registry is unreadable")
    state = _fill_state(cdir)
    lessons = _lessons(projects, gfolder, state)
    result["asked"] = len(lessons)
    if not lessons:
        return _finish(cdir, result)
    fingerprint = hashlib.sha256(
        json.dumps(sorted((x.key, x.digest) for x in lessons.values())).encode()
    ).hexdigest()
    failures = state["failures"]
    if failures["fingerprint"] != fingerprint:
        failures["count"] = 0
    if failures["count"] >= corroborate.FILL_FAILURES:
        return _finish(cdir, result, stopped="waiting for the lessons to change", asked=0)
    return _Auto(cdir, result, state, lessons, names, gfolder, fingerprint)


def _failed_session(ctx: _Auto, why: str) -> dict:
    failures = ctx.state["failures"]
    failures["count"] += 1
    failures["fingerprint"] = ctx.fingerprint
    ctx.save()
    return _finish(ctx.cdir, ctx.result, stopped=why)


def _writer_session(
    ctx: _Auto, claude: str, scratch: Path, budget: float
) -> tuple[dict[str, str], list[tuple[str, dict]]]:
    """The writer's proposals through the code check: (id -> why refused, the (id, item) pairs that passed)."""
    lines = corroborate.fill_lines([(i, x.m) for i, x in ctx.lessons.items()])
    limits = corroborate_run.SessionLimits(corroborate_run.PROPOSE_MODEL, budget)
    payload, cost, ok = corroborate_run._ask(
        claude,
        scratch,
        "write",
        limits,
        corroborate_run.AskJob(corroborate_run.FILL_BRIEF, lines, "lessons", "fill.json"),
    )
    ctx.result["cost"] += cost
    if not (ok and isinstance(payload, dict) and isinstance(payload.get("items"), list)):
        raise _SessionError("the writer session gave no usable answer")
    kept, _dropped_reasons = corroborate.validate_fill(payload, list(ctx.lessons))
    reason: dict[str, str] = {}
    passed: list[tuple[str, dict]] = []
    for i, x in ctx.lessons.items():
        item = kept.get(i)
        if item is None:
            reason[i] = "no proposal"
        elif "problem" in item:
            reason[i] = item["problem"]
        elif found := shortcheck.problems(x.m.claim, item["short"]):
            reason[i] = found[0]
        else:
            passed.append((i, item))
    ctx.result["refused_code"] = len(
        reason
    )  # every refusal before the checker, a missing proposal included
    return reason, passed


def _checker_session(
    ctx: _Auto, claude: str, scratch: Path, budget: float, passed: list[tuple[str, dict]]
) -> dict[str, bool]:
    text = corroborate.check_lines([
        (i, ctx.lessons[i].m.claim, ctx.lessons[i].m.context, item["short"]) for i, item in passed
    ])
    limits = corroborate_run.SessionLimits(corroborate_run.CHECK_MODEL, budget)
    payload, cost, ok = corroborate_run._ask(
        claude,
        scratch,
        "check",
        limits,
        corroborate_run.AskJob(corroborate_run.CHECK_BRIEF, text, "pairs", "verdicts.json"),
    )
    ctx.result["cost"] += cost
    checked = corroborate.validate_check(payload, [i for i, _x in passed]) if ok else None
    if checked is None:
        raise _SessionError("the checker session gave no usable answer")
    return checked


def _sessions_in(ctx: _Auto, claude: str, scratch: Path, budget: float) -> _Verdicts:
    corroborate_state.write_private(
        scratch / "settings.json", json.dumps({"disableAllHooks": True})
    )
    reason, passed = _writer_session(ctx, claude, scratch, budget)
    faithful = _checker_session(ctx, claude, scratch, budget, passed) if passed else {}
    return _Verdicts(reason, passed, faithful)


def _sessions(ctx: _Auto, claude: str, budget: float) -> _Verdicts:
    """The writer session, the code check and the checker session. Raises `_SessionError` for an unusable answer."""
    scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-fill-"))
    try:
        return _sessions_in(ctx, claude, scratch, budget)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _checked_items(ctx: _Auto, verdicts: _Verdicts) -> list[dict]:
    """The faithful short forms as fill items; the others are refused, with the checker's reason."""
    items = []
    for i, fields in verdicts.passed:
        if not verdicts.faithful[i]:
            verdicts.reason[i] = CHECK_REFUSAL
            ctx.result["refused_check"] += 1
            continue
        x = ctx.lessons[i]
        items.append({
            "id": i,
            "handle": x.m.handle,
            "scope": _scope(x.project, ctx.names),
            "claim": x.m.claim,
            "short": fields["short"],
            "topic": fields["topic"],
            "claim_digest": x.digest,
        })
    return items


def _apply_checked(ctx: _Auto, items: list[dict], reason: dict[str, str]) -> tuple[list[str], bool]:
    """Applies the items: (the ids written, whether the apply raised)."""
    if not items:
        return [], False
    run = _fill_run_folder(ctx.cdir)
    try:
        done = apply_fill(items, run, user_read=False)
    except (
        Exception
    ):  # an apply that raised is an outcome: what reached the records is read back from them
        logger.debug("the apply raised", exc_info=True)
        applied = _written_ids(items)
        for x in items:
            if x["id"] not in applied:
                reason[x["id"]] = APPLY_REFUSAL
        return applied, True
    for i in done["refused"]:
        reason[i] = APPLY_REFUSAL
    corroborate_state.write_private(
        run / "applied.json", json.dumps([ctx.lessons[i].m.handle for i in done["applied"]])
    )
    ctx.result["written"], ctx.result["dropped"], ctx.result["left"] = (
        done["written"],
        done["dropped"],
        done["failed"],
    )
    return done["applied"], False


def _count_attempts(
    ctx: _Auto, applied: list[str], reason: dict[str, str]
) -> list[tuple[str, str]]:
    """Charges an attempt to every refused lesson; returns (id, why) of those that used the last one."""
    attempts = ctx.state["lessons"]
    for i in applied:
        attempts[ctx.lessons[i].key] = {
            "digest": ctx.lessons[i].digest,
            "count": corroborate.FILL_ATTEMPTS,
        }
    holds: list[tuple[str, str]] = []
    for i, why in reason.items():
        x = ctx.lessons[i]
        count = corroborate.attempt_count(attempts.get(x.key), x.digest) + 1
        attempts[x.key] = {"digest": x.digest, "count": count}
        if count >= corroborate.FILL_ATTEMPTS:
            holds.append((i, why))
    return holds


def _settle(ctx: _Auto, holds: list[tuple[str, str]], apply_failed: bool) -> None:
    """Saves the attempts and the failure count, then sends the lessons that used their last attempt to triage."""
    failures = ctx.state["failures"]
    if apply_failed:
        failures["count"] += 1
        failures["fingerprint"] = ctx.fingerprint
    else:
        failures["count"], failures["fingerprint"] = 0, None
    ctx.save()
    for i, why in holds:
        x = ctx.lessons[i]
        if x.project is None and _hold(x.m.handle, why, ctx.cdir, ctx.gfolder):
            ctx.result["to_triage"] += 1
        else:
            ctx.result["left"] += 1


def _fill_locked(claude: str | None, budget: float, cdir: Path, result: dict) -> dict:
    ctx = _plan(cdir, result)
    if isinstance(ctx, dict):
        return ctx
    if not claude:
        return _finish(cdir, result, stopped="no claude binary")
    try:
        verdicts = _sessions(ctx, claude, budget)
    except _SessionError as exc:
        return _failed_session(ctx, str(exc))
    items = _checked_items(ctx, verdicts)
    applied, apply_failed = _apply_checked(ctx, items, verdicts.reason)
    _settle(ctx, _count_attempts(ctx, applied, verdicts.reason), apply_failed)
    return (
        _finish(cdir, result, stopped="the apply failed") if apply_failed else _finish(cdir, result)
    )


def _written_ids(items: list[dict]) -> list[str]:
    """The ids of the items whose short form is in the records now: what an `apply_fill` that raised had written."""
    try:
        _data, projects, gfolder, _names = corroborate_run._fill_world()
        known = {i: m for i, _p, m in corroborate.fill_records(projects, gfolder)}
    except ValueError:
        return []
    return [
        x["id"]
        for x in items
        if x["id"] in known
        and known[x["id"]].short == x["short"]
        and known[x["id"]].short_by == "model"
    ]


def _hold(handle: str, why: str, cdir: Path, gfolder: Path | None) -> bool:
    applier = corroborate_run.Applier(
        corroborate_state.Journal(cdir), {}, gfolder, cdir, lambda _text: None
    )
    done = applier.mem(
        ["triage", "hold", f"m:{handle}", "--because", why[:200]],
        None,
        drop_env=corroborate_run.SETTLE_VARS,
    )
    return done is not None and done.returncode == 0
