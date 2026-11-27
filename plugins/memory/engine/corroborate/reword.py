"""mem-corroborate: `reword`, a new short form for loaded lessons that got worse."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import NamedTuple, TypedDict, Unpack

from core import jobs
from core import runner as runners
from memories import records

from corroborate import decide as corroborate_decide
from corroborate import job as corroborate_job
from corroborate import run as corroborate_run
from corroborate import state as corroborate_state

logger = logging.getLogger(__name__)

REWORD_ATTEMPTS_NAME = "reword-attempts.json"


REWORD_WRITER_OUT = "reword.json"


REWORD_CHECK_OUT = "reword-check.json"


def _reword_state(cdir: Path) -> dict:
    """The step's memory, read defensively: a missing or broken file is an empty state."""
    data = jobs.read_json(cdir / REWORD_ATTEMPTS_NAME)
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
    watched = (
        [m.path] if project is not None else [m.path, m.path.parent / corroborate_run.SETTLE_STATE]
    )  # a global edit may update it
    before = applier.journal.watch(watched)
    done = applier.mem(
        ["memory", "edit", f"m:{m.handle}", *(["--global"] if project is None else []), *flags],
        project,
        drop_env=corroborate_run.SETTLE_VARS,
    )
    applier.journal.commit("reword", before)
    if done is not None and done.returncode == 0:
        return "ok"
    return "refused" if done is not None and done.returncode in REWORD_REFUSED_EXITS else "failed"


def _reword_sheet(path: Path, rows: list[tuple]) -> None:
    lines = [
        "| id | claim | present short form | proposed short form | outcome | checker's reason |",
        "|---|---|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(corroborate_job.cell(x) for x in row) + " |" for row in rows]
    corroborate_state.write_private(path, "\n".join(lines) + "\n")


class RewordOptions(TypedDict, total=False):
    """The keyword options of `reword_auto` (defaults: `every` False, `apply` True, `sheet` None, `limit` 30)."""

    every: bool
    apply: bool
    sheet: Path | None
    limit: int


class _Params(NamedTuple):
    claude: str | None
    budget: float
    every: bool
    apply: bool
    sheet: Path | None
    limit: int


class _World(NamedTuple):
    projects: list[Path]
    gfolder: Path | None
    candidates: list


class _Sessions(NamedTuple):
    """What the writer and checker sessions gave: the proposals, the ids the checker accepted and its reasons, or
    `failure` (why a session gave no usable answer)."""

    proposed: dict
    accepted: set[str]
    reasons: dict[str, str]
    failure: str | None = None


_finish = corroborate_job.finish


def reword_auto(claude: str | None, budget: float, **options: Unpack[RewordOptions]) -> dict:
    """Rewrites the short form of loaded lessons that got worse, with nobody reading it first: a writer session, the
    code check, a second session that checks the survivors against their claims, then one `mem memory edit
    --reworded` each. Follows `fill_auto`: every doubt ends in not writing; a session with no usable answer is a
    failed session that charges no lesson. With `apply` false it writes no record and saves no state (the sessions
    still run, and cost). Never raises: a failure is a counted result with `stopped` set."""
    result = {
        "asked": 0,
        "written": 0,
        "refused_code": 0,
        "refused_check": 0,
        "same_text": 0,
        "no_proposal": 0,
        "gave_up": 0,
        "changed": 0,
        "failed_edits": 0,
        "cost": 0.0,
        "stopped": None,
    }
    params = _Params(
        claude,
        budget,
        options.get("every", False),
        options.get("apply", True),
        options.get("sheet"),
        options.get("limit", 30),
    )
    try:
        return _reword_guarded(params, result)
    except Exception:
        logger.debug("reword step failed", exc_info=True)
        return _finish(result, stopped="the step failed")


def _reword_guarded(params: _Params, result: dict) -> dict:
    cdir = corroborate_state.corroborate_dir(corroborate_state.data_dir())
    lock = jobs.take_run_lock(cdir)
    if lock is None:
        return {**result, "stopped": "a run is going"}
    try:
        return _reword_locked(params, cdir, result)
    finally:
        os.close(lock)


def _reword_applier(cdir: Path, gfolder: Path | None) -> corroborate_run.Applier:
    run = _reword_run_folder(cdir)
    jobs.private_dir(run)
    corroborate_state.write_private(
        run / "fill", ""
    )  # marks the run: its undo leaves the pass's `seen.json` alone
    return corroborate_run.Applier(
        corroborate_state.Journal(run), {}, gfolder, run, lambda _text: None
    )


def _retry_give_ups(cdir: Path, state: dict, projects, gfolder: Path | None) -> int:
    """The `--reword-failed` edit of a give-up that did not run: every lesson the state counts REWORD_ATTEMPTS or more
    for its present version and whose record lacks the mark gets it again. Returns the marks written."""
    applier, done, seen = None, 0, set()
    for _i, p, m in corroborate_decide.fill_records(projects, gfolder):
        key, versions = corroborate_decide.reword_key(p, m.handle), records.version_list(m)
        if key in seen or not versions or m.reword_failed == versions[-1][0]:
            continue
        seen.add(key)
        if (
            corroborate_decide._count(corroborate_decide._entry(state, key), versions[-1][0])
            >= corroborate_decide.REWORD_ATTEMPTS
        ):
            applier = applier or _reword_applier(cdir, gfolder)
            if _reword_edit(applier, p, m, "--reword-failed") == "ok":
                done += 1
    return done


def _reword_candidates(params: _Params, state: dict, projects, gfolder: Path | None) -> list:
    candidates = corroborate_decide.reword_candidates(
        projects, gfolder, datetime.date.today(), state, every=params.every
    )
    return candidates[: max(params.limit, 0)] if params.every else candidates


def _reword_locked(params: _Params, cdir: Path, result: dict) -> dict:
    try:
        _data, projects, gfolder, _names = corroborate_run._fill_world()
    except ValueError:
        return _finish(result, stopped="the registry is unreadable")
    state = _reword_state(cdir)
    if params.apply:
        result["gave_up"] += _retry_give_ups(cdir, state, projects, gfolder)
    candidates = _reword_candidates(params, state, projects, gfolder)
    result["asked"] = len(candidates)
    if not candidates:
        return _finish(result)
    return _RewordPass(params, cdir, result, state, _World(projects, gfolder, candidates)).run()


def _still_open(seen, m) -> bool:
    """False when the owner edited, kept or reworded the lesson meanwhile: that must not be overwritten."""
    return (
        seen is not None
        and (seen.claim, seen.short) == (m.claim, m.short)
        and seen.status == "active"
        and corroborate_decide.reword_open(seen, records.version_list(seen)[-1][0])
    )


def _check_reasons(payload: object) -> dict[str, str]:
    verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
    return {
        v["id"]: v["reason"]
        for v in verdicts or []
        if isinstance(v, dict) and isinstance(v.get("id"), str) and isinstance(v.get("reason"), str)
    }


class _RewordPass:
    """One run of the step past the lock: the candidates, the sessions, the edits, the state and the sheet."""

    writer_why = ""  # why the writer session failed (`_ask`), for the stop text

    def __init__(
        self, params: _Params, cdir: Path, result: dict, state: dict, world: _World
    ) -> None:
        self.params, self.cdir, self.result, self.state = params, cdir, result, state
        self.projects, self.gfolder, self.candidates = world
        self.where = {
            i: p for i, p, _m in corroborate_decide.fill_records(self.projects, self.gfolder)
        }
        self.by_id = dict(self.candidates)
        keys = {
            i: corroborate_decide.reword_key(self.where[i], m.handle) for i, m in self.candidates
        }
        self.fingerprint = hashlib.sha256(
            json.dumps(
                sorted(
                    (keys[i], records.version_list(m)[-1][0].isoformat())
                    for i, m in self.candidates
                )
            ).encode()
        ).hexdigest()
        self.failures = state["failures"]
        if self.failures["fingerprint"] != self.fingerprint:
            self.failures["count"] = 0
        self.applier: corroborate_run.Applier | None = None
        self.spend = corroborate_run.Spend(runners.resolve_runner(None))  # one cap for all sessions

    def run(self) -> dict:
        claude = self.params.claude
        if self.failures["count"] >= corroborate_decide.FILL_FAILURES:
            return _finish(self.result, stopped="waiting for the lessons to change", asked=0)
        if not claude:
            return _finish(self.result, stopped="no claude binary")
        sessions = self._sessions(claude)
        if sessions.failure is not None:
            return self._failed_session(sessions.failure)
        outcome = corroborate_decide.reword_outcome(
            self.candidates, sessions.proposed, sessions.accepted
        )
        if self.params.apply:
            self._apply(sessions.proposed, outcome)
        self._tally(outcome)
        if self.params.sheet is not None and not self._write_sheet(
            self.params.sheet, sessions, outcome
        ):
            return _finish(
                self.result, stopped=self.result["stopped"] or "the sheet could not be written"
            )
        return _finish(self.result)

    def _save_state(self) -> None:
        if self.params.apply:
            jobs.write_json(self.cdir / REWORD_ATTEMPTS_NAME, self.state)

    def _count_failure(self) -> None:
        self.failures["count"] += 1
        self.failures["fingerprint"] = self.fingerprint

    def _failed_session(self, why: str) -> dict:
        self._count_failure()
        self._save_state()
        return _finish(self.result, stopped=why)

    def _get_applier(self) -> corroborate_run.Applier:
        self.applier = self.applier or _reword_applier(self.cdir, self.gfolder)
        return self.applier

    def _sessions(self, claude: str) -> _Sessions:
        scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-reword-"))
        try:
            return self._run_sessions(claude, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _run_sessions(self, claude: str, scratch: Path) -> _Sessions:
        corroborate_state.write_private(
            scratch / "settings.json", json.dumps({"disableAllHooks": True})
        )
        proposed = self._ask_writer(claude, scratch)
        if proposed is None:
            return _Sessions(
                {}, set(), {}, f"the writer session gave no usable answer{self.writer_why}"
            )
        kept, _refused = corroborate_decide.reword_survivors(proposed, self.candidates)
        if not kept:
            return _Sessions(proposed, set(), {})
        return self._ask_checker(claude, scratch, proposed, kept)

    def _ask_writer(self, claude: str, scratch: Path) -> dict | None:
        limits = corroborate_run.SessionLimits(corroborate_run.PROPOSE_MODEL, self.params.budget)
        job = corroborate_run.AskJob(
            corroborate_run.REWORD_BRIEF,
            corroborate_decide.reword_blocks(self.candidates),
            "lessons",
            REWORD_WRITER_OUT,
            self.spend,
        )
        payload, cost, ok, why = corroborate_run._ask(claude, scratch, "write", limits, job)
        self.writer_why = why
        self.result["cost"] += cost
        try:
            return corroborate_decide.validate_reword(payload, self.candidates) if ok else None
        except ValueError:
            return None

    def _ask_checker(self, claude: str, scratch: Path, proposed: dict, kept: list) -> _Sessions:
        text = corroborate_decide.check_lines([
            (i, m.claim, m.context, short) for i, m, short in kept
        ])
        limits = corroborate_run.SessionLimits(corroborate_run.CHECK_MODEL, self.params.budget)
        job = corroborate_run.AskJob(
            corroborate_run.CHECK_BRIEF, text, "pairs", REWORD_CHECK_OUT, self.spend
        )
        payload, cost, ok, why = corroborate_run._ask(claude, scratch, "check", limits, job)
        self.result["cost"] += cost
        checked = (
            corroborate_decide.validate_check(payload, [i for i, _m, _s in kept]) if ok else None
        )
        if checked is None:
            return _Sessions({}, set(), {}, f"the checker session gave no usable answer{why}")
        accepted = {i for i, faithful in checked.items() if faithful}
        return _Sessions(proposed, accepted, _check_reasons(payload))

    def _edit_written(self, proposed: dict, outcome: dict[str, str]) -> None:
        now = {
            i: m for i, _p, m in corroborate_decide.fill_records(self.projects, self.gfolder)
        }  # the owner may have edited meanwhile
        for i, m in self.candidates:
            if outcome[i] != "written":
                continue
            if not _still_open(now.get(i), m):
                outcome[i] = "changed"
                continue
            edit = _reword_edit(
                self._get_applier(),
                self.where[i],
                m,
                f"--short={proposed[i]['short']}",
                "--reworded",
            )
            outcome[i] = {"refused": "refused_code", "failed": "failed_edit"}.get(edit, outcome[i])

    def _apply(self, proposed: dict, outcome: dict[str, str]) -> None:
        self._edit_written(proposed, outcome)
        new_state, giveup = corroborate_decide.reword_state_after(
            self.state, self.candidates, outcome, datetime.date.today()
        )
        self.state["lessons"] = new_state["lessons"]
        if (
            "failed_edit" in outcome.values()
        ):  # as a failed session: repeated failures end in the wait
            self._count_failure()
        else:
            self.failures["count"], self.failures["fingerprint"] = 0, None
        self._save_state()
        for i in giveup:
            if (
                _reword_edit(self._get_applier(), self.where[i], self.by_id[i], "--reword-failed")
                == "ok"
            ):
                self.result["gave_up"] += 1

    def _tally(self, outcome: dict[str, str]) -> None:
        for word in ("refused_code", "refused_check", "same_text", "no_proposal", "changed"):
            self.result[word] = sum(1 for v in outcome.values() if v == word)
        self.result["failed_edits"] = sum(1 for v in outcome.values() if v == "failed_edit")
        self.result["written"] = (
            sum(1 for v in outcome.values() if v == "written") if self.params.apply else 0
        )

    def _write_sheet(self, sheet: Path, sessions: _Sessions, outcome: dict[str, str]) -> bool:
        """False when the sheet could not be written: the run is done, so that must not turn it into a failed step."""
        proposed, apply = sessions.proposed, self.params.apply
        try:
            _reword_sheet(
                sheet,
                [
                    (
                        i,
                        m.claim,
                        m.short,
                        proposed.get(i, {}).get("short"),
                        "would be written" if outcome[i] == "written" and not apply else outcome[i],
                        sessions.reasons.get(i),
                    )
                    for i, m in self.candidates
                ],
            )
        except Exception:
            logger.debug("reword sheet not written", exc_info=True)
            return False
        return True
