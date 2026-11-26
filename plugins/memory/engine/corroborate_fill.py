"""mem-corroborate: `fill`, the short form and topic of the lessons that lack them."""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import auto_state as au
import corroborate
import corroborate_run
import corroborate_state
import records
import rules
import shortcheck


ATTEMPTS_NAME = "fill-attempts.json"


CHECK_REFUSAL = "the checker did not find the short form faithful to the claim"


APPLY_REFUSAL = "mem refused to write the short form"


def fill_dry_run(args) -> int:
    if not args.claude:
        print("mem-corroborate: no claude binary (--claude, CLAUDE_CODE_EXECPATH or PATH)", file=sys.stderr)
        return 1
    folder = Path(args.out).expanduser().resolve().parent
    if not (folder.is_dir() and os.access(folder, os.W_OK | os.X_OK)):
        print(f"mem-corroborate: --out: {folder} is not a folder that can be written", file=sys.stderr)
        return 2
    repo = corroborate_run.repo_above(folder)
    if repo is not None:
        print(f"mem-corroborate: --out is inside a repository ({repo}); the result holds memory text", file=sys.stderr)
        return 2
    try:
        _data, projects, gfolder, names = corroborate_run._fill_world()
    except ValueError as exc:
        print(f"mem-corroborate: registry unreadable: {exc}", file=sys.stderr)
        return 1
    candidates = corroborate.fill_candidates(projects, gfolder, datetime.date.today())
    where = {i: p for i, p, _m in corroborate.fill_records(projects, gfolder)}
    by_id = dict(candidates)
    kept: dict[str, dict] = {}
    reasons: list[str] = []
    cost = 0.0
    if candidates:
        scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-fill-"))
        try:
            settings = scratch / "settings.json"
            corroborate_state.write_private(settings, json.dumps({"disableAllHooks": True}))
            work = scratch / "fill"
            work.mkdir(mode=0o700)
            corroborate_state.write_private(work / "lessons.txt", corroborate.fill_lines(candidates))
            out = work / "fill.json"
            brief = corroborate_run.FILL_BRIEF.format(lessons=work / "lessons.txt", out=out)
            done = corroborate_run.run_session(corroborate_run.session_cmd(args.claude, work, brief, settings, corroborate_run.SessionLimits(corroborate_run.PROPOSE_MODEL, args.budget)), work)
            cost = done["cost"] if done["has_result"] else 0.0
            if not done["has_result"] or done["error"]:
                print("mem-corroborate: the session failed; nothing was written", file=sys.stderr)
                return 1
            kept, reasons = corroborate.validate_fill(corroborate_run.read_object(out), list(by_id))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    for ident in by_id:
        kept.setdefault(ident, {"short": "", "topic": "", "problem": "no proposal"})
    items = []
    for ident, fields in kept.items():
        m = by_id[ident]
        project = where[ident]
        items.append({"id": ident, "handle": m.handle, "scope": "global" if project is None else names.get(project, str(project)),
                      "claim": m.claim, "short": fields["short"], "topic": fields["topic"],
                      "load": "index" if m.load == "index" else "yes",
                      "claim_digest": corroborate.claim_digest(m), **({"problem": fields["problem"]} if "problem" in fields else {})})
    to_edit = sum("problem" in i for i in items)
    corroborate_state.write_private(Path(args.out).expanduser(), json.dumps(items, ensure_ascii=False, indent=1) + "\n")
    print(f"mem-corroborate: fill: {len(candidates)} lessons asked, {len(items) - to_edit} kept, {to_edit} to edit, {len(reasons)} dropped, "
          f"cost {cost:.3f} USD; read {args.out}, edit or cut it, then run fill --items {args.out}")
    for why in reasons:
        print(f"  not kept: {why}", file=sys.stderr)
    return 0


def apply_fill(items: list[dict], run: Path, user_read: bool) -> dict:
    """Writes the items into the records and journals them in `run` (the caller holds the run lock). Returns
    {"written", "dropped", "failed", "applied", "refused"}; `applied` holds the id of each item written and `refused`
    the id of each one `mem memory edit` refused. Without `user_read` (the automatic fill) an item never sets `load`:
    a record turned off is dropped, and a record's load stays as the owner has it."""
    _data, projects, gfolder, names = corroborate_run._fill_world()
    au.private_dir(run)
    corroborate_state.write_private(run / "fill", "")   # marks the run: its undo leaves the pass's `seen.json` alone

    def log(text: str) -> None:
        fd = os.open(run / "log.txt", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    known = {i: (p, m) for i, p, m in corroborate.fill_records(projects, gfolder)}
    applier = corroborate_run.Applier(corroborate_state.Journal(run), {}, gfolder, run, log)
    written = dropped = failed = 0
    applied: list[str] = []
    refused: list[str] = []
    used: set[str] = set()
    today = datetime.date.today()
    for n, item in enumerate(items, start=1):
        ident = item.get("id") if isinstance(item, dict) else None
        short = item.get("short") if isinstance(item, dict) else None
        topic = item.get("topic") if isinstance(item, dict) else None
        load = item.get("load") if isinstance(item, dict) and user_read else None
        why = None
        if not all(isinstance(x, str) for x in (ident, short, topic)):
            why = "not an object with id, short and topic"
        elif ident not in known:
            why = f"unknown id {ident}"
        elif ident in used:
            why = f"repeats {ident}"
        elif not records.valid_short(short):
            why = "short is not one line of at most 120 characters"
        elif not records.valid_topic(topic):
            why = "topic is not one or two lowercase words"
        elif user_read and "load" in item and load not in ("yes", "index", "no"):
            why = "load must be yes, index or no"
        else:
            project, m = known[ident]
            scope = "global" if project is None else names.get(project, str(project))
            if item.get("handle", m.handle) != m.handle or item.get("scope", scope) != scope:
                why = "handle or scope does not match its id"
            elif m.triage == "pending" or not rules.eligible(
                    dataclasses.replace(m, load=None) if m.load == "no" and load is not None else m, today):
                why = "not a lesson that can load"   # a record turned off may be turned on again by an item that names `load`
        if why:
            dropped += 1
            log(f"item {n} dropped: {why}")
            continue
        used.add(ident)
        if item.get("claim_digest") != corroborate.claim_digest(m):
            failed += 1
            log(f"item {n} failed: {ident} changed its claim since the file was made")
            continue
        watched = [m.path] if project is not None else [m.path, m.path.parent / corroborate_run.SETTLE_STATE]   # an edit of a global record may update it
        before = applier.journal.watch(watched)
        done = applier.mem(["memory", "edit", f"m:{m.handle}", *(["--global"] if project is None else []),
                            f"--short={short}", *(["--user-read"] if user_read else []), f"--topic={topic}",
                            *{"yes": ["--load"], "index": ["--index-only"], "no": ["--no-load"]}.get(load, [])], project, drop_env=corroborate_run.SETTLE_VARS)
        applier.journal.commit("fill", before)
        if done is not None and done.returncode == 0:
            written += 1
            applied.append(ident)
        else:
            failed += 1
            refused.append(ident)
            log(f"item {n} failed: mem refused or could not run for {ident}")
    return {"written": written, "dropped": dropped, "failed": failed, "applied": applied, "refused": refused}


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
    start = time.time()
    try:
        run = cdir / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-fill"
        result = apply_fill(items, run, user_read=True)
        written, dropped, failed = result["written"], result["dropped"], result["failed"]
        line = {"t": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "fill": {"asked": len(items), "written": written, "dropped": dropped, "failed": failed},
                "ms": int((time.time() - start) * 1000)}
        corroborate_state.append_log(cdir, line)
        print(f"mem-corroborate: fill: {len(items)} asked, {written} written, {dropped} dropped, {failed} failed; "
              f"undo with: mem-corroborate undo {run.name}")
        return 1 if failed else 0
    except Exception as exc:   # noqa: BLE001
        print(f"mem-corroborate: fill failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        os.close(lock)


def _fill_state(cdir: Path) -> dict:
    """The automatic fill's memory, read defensively: a missing or broken file is an empty state."""
    data = au.read_json(cdir / ATTEMPTS_NAME)
    lessons = data.get("lessons")
    failures = data.get("failures")
    lessons = {k: v for k, v in lessons.items() if isinstance(v, dict)} if isinstance(lessons, dict) else {}
    failures = failures if isinstance(failures, dict) else {}
    count = failures.get("count")
    return {"lessons": lessons, "failures": {"count": count if isinstance(count, int) and count > 0 else 0,
                                             "fingerprint": failures.get("fingerprint")}}


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
    result = {"asked": 0, "written": 0, "dropped": 0, "refused_code": 0, "refused_check": 0, "to_triage": 0, "left": 0,
              "cost": 0.0, "stopped": None}
    lock = au.take_run_lock(cdir)
    if lock is None:
        return {**result, "stopped": "a run is going"}
    try:
        return _fill_locked(claude, budget, cdir, result)
    finally:
        os.close(lock)


def _fill_locked(claude: str | None, budget: float, cdir: Path, result: dict) -> dict:
    def finish(**changes) -> dict:
        result.update(changes)
        result["cost"] = round(result["cost"], 6)
        corroborate_state.save_status(cdir, fill=dict(result))
        return result

    try:
        _data, projects, gfolder, names = corroborate_run._fill_world()
    except ValueError:
        return finish(stopped="the registry is unreadable")
    state = _fill_state(cdir)
    candidates = corroborate.fill_candidates(projects, gfolder, datetime.date.today(), attempts=state["lessons"])
    where = {i: p for i, p, _m in corroborate.fill_records(projects, gfolder)}
    result["asked"] = len(candidates)
    keys = {i: corroborate.fill_key(where[i], m.handle) for i, m in candidates}
    digests = {i: corroborate.claim_digest(m) for i, m in candidates}

    if not candidates:
        return finish()
    fingerprint = hashlib.sha256(json.dumps(sorted((keys[i], digests[i]) for i, _m in candidates)).encode()).hexdigest()
    failures = state["failures"]
    if failures["fingerprint"] != fingerprint:
        failures["count"] = 0

    def save_state() -> None:
        au.write_json(cdir / ATTEMPTS_NAME, state)

    if failures["count"] >= corroborate.FILL_FAILURES:
        return finish(stopped="waiting for the lessons to change", asked=0)
    if not claude:
        return finish(stopped="no claude binary")

    def failed_session(why: str) -> dict:
        failures["count"] += 1
        failures["fingerprint"] = fingerprint
        save_state()
        return finish(stopped=why)

    by_id = dict(candidates)
    scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-fill-"))
    try:
        corroborate_state.write_private(scratch / "settings.json", json.dumps({"disableAllHooks": True}))
        payload, cost, ok = corroborate_run._ask(claude, scratch, "write", corroborate_run.SessionLimits(corroborate_run.PROPOSE_MODEL, budget), corroborate_run.AskJob(corroborate_run.FILL_BRIEF,
                                 corroborate.fill_lines(candidates), "lessons", "fill.json"))
        result["cost"] += cost
        if not (ok and isinstance(payload, dict) and isinstance(payload.get("items"), list)):
            return failed_session("the writer session gave no usable answer")
        kept, _dropped_reasons = corroborate.validate_fill(payload, list(by_id))
        reason: dict[str, str] = {}      # id -> why the lesson was refused
        passed: list[tuple[str, dict]] = []
        for i in by_id:
            item = kept.get(i)
            if item is None:
                reason[i] = "no proposal"
            elif "problem" in item:
                reason[i] = item["problem"]
            elif found := shortcheck.problems(by_id[i].claim, item["short"]):
                reason[i] = found[0]
            else:
                passed.append((i, item))
        result["refused_code"] = len(reason)   # every refusal before the checker, a missing proposal included
        faithful: dict[str, bool] = {}
        if passed:
            text = corroborate.check_lines([(i, by_id[i].claim, by_id[i].context, item["short"]) for i, item in passed])
            payload, cost, ok = corroborate_run._ask(claude, scratch, "check", corroborate_run.SessionLimits(corroborate_run.CHECK_MODEL, budget), corroborate_run.AskJob(corroborate_run.CHECK_BRIEF, text, "pairs",
                                     "verdicts.json"))
            result["cost"] += cost
            checked = corroborate.validate_check(payload, [i for i, _x in passed]) if ok else None
            if checked is None:
                return failed_session("the checker session gave no usable answer")
            faithful = checked
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    items = []
    for i, fields in passed:
        if not faithful[i]:
            reason[i] = CHECK_REFUSAL
            result["refused_check"] += 1
            continue
        m = by_id[i]
        project = where[i]
        items.append({"id": i, "handle": m.handle, "scope": "global" if project is None else names.get(project, str(project)),
                      "claim": m.claim, "short": fields["short"], "topic": fields["topic"], "claim_digest": digests[i]})
    applied: list[str] = []
    apply_failed = False
    if items:
        run = _fill_run_folder(cdir)
        try:
            done = apply_fill(items, run, user_read=False)
        except Exception:   # an apply that raised is an outcome: what reached the records is read back from them
            apply_failed = True
            applied = _written_ids(items)
            for x in items:
                if x["id"] not in applied:
                    reason[x["id"]] = APPLY_REFUSAL
        else:
            applied = done["applied"]
            for i in done["refused"]:
                reason[i] = APPLY_REFUSAL
            corroborate_state.write_private(run / "applied.json", json.dumps([by_id[i].handle for i in applied]))
            result["written"], result["dropped"], result["left"] = done["written"], done["dropped"], done["failed"]
    for i in applied:
        state["lessons"][keys[i]] = {"digest": digests[i], "count": corroborate.FILL_ATTEMPTS}
    holds: list[tuple[str, str]] = []
    for i, why in reason.items():
        count = corroborate.attempt_count(state["lessons"].get(keys[i]), digests[i]) + 1
        state["lessons"][keys[i]] = {"digest": digests[i], "count": count}
        if count >= corroborate.FILL_ATTEMPTS:
            holds.append((i, why))
    if apply_failed:
        failures["count"] += 1
        failures["fingerprint"] = fingerprint
    else:
        failures["count"], failures["fingerprint"] = 0, None
    save_state()
    for i, why in holds:
        if where[i] is None and _hold(by_id[i].handle, why, cdir, gfolder):
            result["to_triage"] += 1
        else:
            result["left"] += 1
    return finish(stopped="the apply failed") if apply_failed else finish()


def _written_ids(items: list[dict]) -> list[str]:
    """The ids of the items whose short form is in the records now: what an `apply_fill` that raised had written."""
    try:
        _data, projects, gfolder, _names = corroborate_run._fill_world()
        known = {i: m for i, _p, m in corroborate.fill_records(projects, gfolder)}
    except ValueError:
        return []
    return [x["id"] for x in items if x["id"] in known and known[x["id"]].short == x["short"]
            and known[x["id"]].short_by == "model"]


def _hold(handle: str, why: str, cdir: Path, gfolder: Path | None) -> bool:
    applier = corroborate_run.Applier(None, {}, gfolder, cdir, lambda _text: None)
    done = applier.mem(["triage", "hold", f"m:{handle}", "--because", why[:200]], None, drop_env=corroborate_run.SETTLE_VARS)
    return done is not None and done.returncode == 0
