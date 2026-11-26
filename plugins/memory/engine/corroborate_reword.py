"""mem-corroborate: `reword`, a new short form for loaded lessons that got worse."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import auto_state as au
import corroborate
import corroborate_run
import corroborate_state
import records


REWORD_ATTEMPTS_NAME = "reword-attempts.json"


REWORD_WRITER_OUT = "reword.json"


REWORD_CHECK_OUT = "reword-check.json"


def _reword_state(cdir: Path) -> dict:
    """The step's memory, read defensively: a missing or broken file is an empty state."""
    data = au.read_json(cdir / REWORD_ATTEMPTS_NAME)
    lessons = data.get("lessons")
    failures = data.get("failures")
    lessons = {k: v for k, v in lessons.items() if isinstance(v, dict)} if isinstance(lessons, dict) else {}
    failures = failures if isinstance(failures, dict) else {}
    count = failures.get("count")
    return {"lessons": lessons, "failures": {"count": count if isinstance(count, int) and count > 0 else 0,
                                             "fingerprint": failures.get("fingerprint")}}


def _reword_run_folder(cdir: Path) -> Path:
    base = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    run, n = cdir / "runs" / f"{base}-reword", 1
    while run.exists():
        n += 1
        run = cdir / "runs" / f"{base}-{n}-reword"
    return run


# Only exit 4 of `mem memory edit` (a secret, a forbidden term) refuses the text. Exit 2 is also a usage error, "not found"
# or "not active": counting it as a refusal would make every lesson give up if the command line were ever wrong, and the
# step has run the same code check itself before the edit.
REWORD_REFUSED_EXITS = (4,)


def _reword_edit(applier: corroborate_run.Applier, project: Path | None, m, *flags: str) -> str:
    """One `mem memory edit` of the step, journaled: "ok", "refused" (exit 4: the command refused the text) or "failed"
    (it could not run, timed out or exited otherwise: nothing says the text is bad, so no attempt is spent)."""
    watched = [m.path] if project is not None else [m.path, m.path.parent / corroborate_run.SETTLE_STATE]   # a global edit may update it
    before = applier.journal.watch(watched)
    done = applier.mem(["memory", "edit", f"m:{m.handle}", *(["--global"] if project is None else []), *flags], project,
                       drop_env=corroborate_run.SETTLE_VARS)
    applier.journal.commit("reword", before)
    if done is not None and done.returncode == 0:
        return "ok"
    return "refused" if done is not None and done.returncode in REWORD_REFUSED_EXITS else "failed"


def _reword_sheet(path: Path, rows: list[tuple]) -> None:
    lines = ["| id | claim | present short form | proposed short form | outcome | checker's reason |", "|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(corroborate_run._cell(x) for x in row) + " |" for row in rows]
    corroborate_state.write_private(path, "\n".join(lines) + "\n")


def reword_auto(claude: str | None, budget: float, *, every: bool = False, apply: bool = True,
                sheet: Path | None = None, limit: int = 30) -> dict:
    """Rewrites the short form of loaded lessons that got worse, with nobody reading it first: a writer session, the
    code check, a second session that checks the survivors against their claims, then one `mem memory edit
    --reworded` each. Follows `fill_auto`: every doubt ends in not writing; a session with no usable answer is a
    failed session that charges no lesson. With `apply` false it writes no record and saves no state (the sessions
    still run, and cost). Never raises: a failure is a counted result with `stopped` set."""
    result = {"asked": 0, "written": 0, "refused_code": 0, "refused_check": 0, "same_text": 0, "no_proposal": 0,
              "gave_up": 0, "changed": 0, "failed_edits": 0, "cost": 0.0, "stopped": None}
    try:
        cdir = corroborate_state.corroborate_dir(corroborate_state.data_dir())
        lock = au.take_run_lock(cdir)
        if lock is None:
            return {**result, "stopped": "a run is going"}
        try:
            return _reword_locked(claude, budget, cdir, result, every, apply, sheet, limit)
        finally:
            os.close(lock)
    except Exception:   # noqa: BLE001
        result["cost"] = round(result["cost"], 6)
        return {**result, "stopped": "the step failed"}


def _reword_applier(cdir: Path, gfolder: Path | None) -> corroborate_run.Applier:
    run = _reword_run_folder(cdir)
    au.private_dir(run)
    corroborate_state.write_private(run / "fill", "")   # marks the run: its undo leaves the pass's `seen.json` alone
    return corroborate_run.Applier(corroborate_state.Journal(run), {}, gfolder, run, lambda _text: None)


def _retry_give_ups(cdir: Path, state: dict, projects, gfolder: Path | None) -> int:
    """The `--reword-failed` edit of a give-up that did not run: every lesson the state counts REWORD_ATTEMPTS or more
    for its present version and whose record lacks the mark gets it again. Returns the marks written."""
    applier, done, seen = None, 0, set()
    for _i, p, m in corroborate.fill_records(projects, gfolder):
        key, versions = corroborate.reword_key(p, m.handle), records.version_list(m)
        if key in seen or not versions or m.reword_failed == versions[-1][0]:
            continue
        seen.add(key)
        if corroborate._count(corroborate._entry(state, key), versions[-1][0]) >= corroborate.REWORD_ATTEMPTS:
            applier = applier or _reword_applier(cdir, gfolder)
            if _reword_edit(applier, p, m, "--reword-failed") == "ok":
                done += 1
    return done


def _reword_locked(claude: str | None, budget: float, cdir: Path, result: dict, every: bool, apply: bool,
                   sheet: Path | None, limit: int) -> dict:
    def finish(**changes) -> dict:
        result.update(changes)
        result["cost"] = round(result["cost"], 6)
        return result

    try:
        _data, projects, gfolder, _names = corroborate_run._fill_world()
    except ValueError:
        return finish(stopped="the registry is unreadable")
    state = _reword_state(cdir)
    if apply:
        result["gave_up"] += _retry_give_ups(cdir, state, projects, gfolder)
    candidates = corroborate.reword_candidates(projects, gfolder, datetime.date.today(), state, every=every)
    if every:
        candidates = candidates[:max(limit, 0)]
    result["asked"] = len(candidates)
    if not candidates:
        return finish()
    where = {i: p for i, p, _m in corroborate.fill_records(projects, gfolder)}
    by_id = dict(candidates)
    keys = {i: corroborate.reword_key(where[i], m.handle) for i, m in candidates}
    fingerprint = hashlib.sha256(json.dumps(sorted(
        (keys[i], records.version_list(m)[-1][0].isoformat()) for i, m in candidates)).encode()).hexdigest()
    failures = state["failures"]
    if failures["fingerprint"] != fingerprint:
        failures["count"] = 0

    def save_state() -> None:
        if apply:
            au.write_json(cdir / REWORD_ATTEMPTS_NAME, state)

    if failures["count"] >= corroborate.FILL_FAILURES:
        return finish(stopped="waiting for the lessons to change", asked=0)
    if not claude:
        return finish(stopped="no claude binary")

    def failed_session(why: str) -> dict:
        failures["count"] += 1
        failures["fingerprint"] = fingerprint
        save_state()
        return finish(stopped=why)

    scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-reword-"))
    reasons: dict[str, str] = {}
    try:
        corroborate_state.write_private(scratch / "settings.json", json.dumps({"disableAllHooks": True}))
        payload, cost, ok = corroborate_run._ask(claude, scratch, "write", corroborate_run.PROPOSE_MODEL, budget, corroborate_run.REWORD_BRIEF,
                                 corroborate.reword_blocks(candidates), "lessons", REWORD_WRITER_OUT)
        result["cost"] += cost
        try:
            proposed = corroborate.validate_reword(payload, candidates) if ok else None
        except ValueError:
            proposed = None
        if proposed is None:
            return failed_session("the writer session gave no usable answer")
        kept, _refused = corroborate.reword_survivors(proposed, candidates)
        accepted: set[str] = set()
        if kept:
            text = corroborate.check_lines([(i, m.claim, m.context, short) for i, m, short in kept])
            payload, cost, ok = corroborate_run._ask(claude, scratch, "check", corroborate_run.CHECK_MODEL, budget, corroborate_run.CHECK_BRIEF, text, "pairs",
                                     REWORD_CHECK_OUT)
            result["cost"] += cost
            checked = corroborate.validate_check(payload, [i for i, _m, _s in kept]) if ok else None
            if checked is None:
                return failed_session("the checker session gave no usable answer")
            accepted = {i for i, faithful in checked.items() if faithful}
            reasons = {v["id"]: v["reason"] for v in payload["verdicts"]
                       if isinstance(v, dict) and isinstance(v.get("id"), str) and isinstance(v.get("reason"), str)}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    outcome = corroborate.reword_outcome(candidates, proposed, accepted)
    if apply:
        applier = None
        now = {i: m for i, _p, m in corroborate.fill_records(projects, gfolder)}   # the owner may have edited meanwhile
        for i, m in candidates:
            if outcome[i] != "written":
                continue
            seen = now.get(i)
            # keeping a wording (`reviewed`) or a rewording made meanwhile must not be overwritten
            if (seen is None or (seen.claim, seen.short) != (m.claim, m.short) or seen.status != "active"
                    or not corroborate.reword_open(seen, records.version_list(seen)[-1][0])):
                outcome[i] = "changed"
                continue
            applier = applier or _reword_applier(cdir, gfolder)
            edit = _reword_edit(applier, where[i], m, f"--short={proposed[i]['short']}", "--reworded")
            if edit == "refused":
                outcome[i] = "refused_code"
            elif edit == "failed":
                outcome[i] = "failed_edit"
        new_state, giveup = corroborate.reword_state_after(state, candidates, outcome, datetime.date.today())
        state["lessons"] = new_state["lessons"]
        if "failed_edit" in outcome.values():   # as a failed session: repeated failures end in the wait
            failures["count"] += 1
            failures["fingerprint"] = fingerprint
        else:
            failures["count"], failures["fingerprint"] = 0, None
        save_state()
        for i in giveup:
            applier = applier or _reword_applier(cdir, gfolder)
            if _reword_edit(applier, where[i], by_id[i], "--reword-failed") == "ok":
                result["gave_up"] += 1
    for word in ("refused_code", "refused_check", "same_text", "no_proposal", "changed"):
        result[word] = sum(1 for v in outcome.values() if v == word)
    result["failed_edits"] = sum(1 for v in outcome.values() if v == "failed_edit")
    result["written"] = sum(1 for v in outcome.values() if v == "written") if apply else 0
    if sheet is not None:
        try:   # the run is done: a sheet that cannot be written must not turn it into a failed step
            _reword_sheet(sheet, [(i, m.claim, m.short, proposed.get(i, {}).get("short"),
                                   "would be written" if outcome[i] == "written" and not apply else outcome[i], reasons.get(i))
                                  for i, m in candidates])
        except Exception:   # noqa: BLE001
            return finish(stopped=result["stopped"] or "the sheet could not be written")
    return finish()
