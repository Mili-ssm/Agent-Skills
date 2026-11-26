"""mem-corroborate: `digest`, a heading per topic and a line per lesson for the session start."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import NamedTuple

from core import jobs
from digest import lessons as dg
from memories import records

from corroborate import decide as corroborate_decide
from corroborate import run as corroborate_run
from corroborate import state as corroborate_state

logger = logging.getLogger(__name__)

DIGEST_ATTEMPTS_NAME = "digest-attempts.json"


DIGEST_WRITER_OUT = "digest-write.json"


DIGEST_CHECK_OUT = "digest-check.json"


def _digest_state(cdir: Path) -> dict:
    """The step's memory, read defensively: a missing or broken file is an empty state."""
    data = jobs.read_json(cdir / DIGEST_ATTEMPTS_NAME)
    tries = data.get("tries")
    failures = data.get("failures")
    tries = (
        {k: v for k, v in tries.items() if isinstance(k, str) and isinstance(v, int) and v > 0}
        if isinstance(tries, dict)
        else {}
    )
    failures = failures if isinstance(failures, dict) else {}
    count = failures.get("count")
    return {
        "tries": tries,
        "failures": {
            "count": count if isinstance(count, int) and count > 0 else 0,
            "fingerprint": failures.get("fingerprint"),
        },
    }


def _one_line(text: object) -> str:
    return " ".join(str(text).split())


def _digest_pair_text(pairs: list) -> str:
    """What the checker reads: per lesson `id`, `claim`, `context` when there is one, `heading`, `line`; a blank line between."""
    blocks = []
    for ident, m, head, text in pairs:
        rows = [f"id: {ident}", f"claim: {_one_line(m.claim)}"]
        if m.context:
            rows.append(f"context: {_one_line(m.context)}")
        rows += [f"heading: {_one_line(head)}", f"line: {_one_line(text)}"]
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def _digest_verdicts(payload: object) -> tuple[dict, dict] | None:
    """({id: {"fits", "faithful"}}, {id: reason}) from the checker's answer, or None when it is not one. Only the value
    `true` counts; an id the checker left out is neither."""
    if not isinstance(payload, dict) or not isinstance(payload.get("verdicts"), list):
        return None
    verdicts, reasons = {}, {}
    for v in payload["verdicts"]:
        if isinstance(v, dict) and isinstance(v.get("id"), str) and v["id"] not in verdicts:
            verdicts[v["id"]] = {
                "fits": v.get("fits") is True,
                "faithful": v.get("faithful") is True,
            }
            if isinstance(v.get("reason"), str):
                reasons[v["id"]] = v["reason"]
    return verdicts, reasons


def _digest_sheet(path: Path, rows: list[tuple]) -> None:
    lines = [
        "| topic | heading | id | claim | short form | line | outcome | checker's reason |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(corroborate_run._cell(x) for x in row) + " |" for row in rows]
    corroborate_state.write_private(path, "\n".join(lines) + "\n")


class _Params(NamedTuple):
    claude: str | None
    budget: float
    apply: bool
    sheet: Path | None


class _Inputs(NamedTuple):
    """What the step reads before it asks anything: the data folder, the stored digest and state, the topics and the work."""

    data: Path
    stored: dict
    state: dict
    topics: dict
    works: list[dg.Work]


class _Sessions(NamedTuple):
    """What the writer and checker sessions gave, or `failure` (why a session gave no usable answer)."""

    proposed: dict
    verdicts: dict
    reasons: dict[str, str]
    failure: str | None = None


class _Sheet(NamedTuple):
    """What the sheet's rows are made of."""

    proposed: dict
    verdicts: dict
    reasons: dict[str, str]
    new_digest: dict
    apply: bool


class _TopicView(NamedTuple):
    work: dg.Work
    proposed: dict
    paired: dict
    stored_topic: dict
    head_text: str | None


def _finish(result: dict, **changes) -> dict:
    result.update(changes)
    result["cost"] = round(result["cost"], 6)
    return result


def digest_auto(
    claude: str | None, budget: float, *, apply: bool = True, sheet: Path | None = None
) -> dict:
    """Writes the digest of the loaded lessons, with nobody reading it first: a writer session (a heading per topic, a
    line per lesson), the code checks (`digest.decide`), a second session that checks every line against its claim, then
    the digest file and the step's state. It writes no record and runs no `mem` command: nothing to journal or undo. With
    `apply` false it writes neither file (the sessions still run, and cost). Never raises: a failure is a counted result
    with `stopped` set."""
    result = {
        "topics": 0,
        "headings_written": 0,
        "lines_written": 0,
        "refused_code": 0,
        "refused_check": 0,
        "missing": 0,
        "unjudged": 0,
        "cost": 0.0,
        "stopped": None,
    }
    try:
        return _digest_guarded(_Params(claude, budget, apply, sheet), result)
    except Exception:
        logger.debug("digest step failed", exc_info=True)
        return _finish(result, stopped="the step failed")


def _digest_guarded(params: _Params, result: dict) -> dict:
    cdir = corroborate_state.corroborate_dir(corroborate_state.data_dir())
    lock = jobs.take_run_lock(cdir)
    if lock is None:
        return {**result, "stopped": "a run is going"}
    try:
        return _digest_locked(params, cdir, result)
    finally:
        os.close(lock)


def _digest_locked(params: _Params, cdir: Path, result: dict) -> dict:
    data = corroborate_state.data_dir()
    lessons = [
        m
        for m in records.load_memories(records.global_memories_root(os.environ), "global")
        if m.error is None
    ]
    stored = dg.read(data)
    state = _digest_state(cdir)
    topics = dg.topics_of(lessons, datetime.date.today())
    works = dg.work(topics, stored, state)
    result["topics"] = len(works)
    return _DigestPass(params, cdir, result, _Inputs(data, stored, state, topics, works)).run()


class _DigestPass:
    """One run of the step past the lock: the sessions, the checks, the files and the sheet."""

    def __init__(self, params: _Params, cdir: Path, result: dict, inputs: _Inputs) -> None:
        self.params, self.cdir, self.result = params, cdir, result
        self.data, self.stored, self.state, self.topics, self.works = inputs
        self.failures = self.state["failures"]
        self.fingerprint = ""

    def run(self) -> dict:
        if not self.works:
            return self._idle()
        keys = sorted([
            *(
                dg._heading_key(w.topic, w.lessons)
                for w in self.works
                if w.heading_state == "write"
            ),
            *(dg._line_key(m, w.lessons) for w in self.works for m in w.write),
        ])
        self.fingerprint = hashlib.sha256(json.dumps(keys).encode()).hexdigest()
        if self.failures["fingerprint"] != self.fingerprint:
            self.failures["count"] = 0
        if self.failures["count"] >= corroborate_decide.FILL_FAILURES:
            return _finish(self.result, stopped="waiting for the lessons to change", topics=0)
        claude = self.params.claude
        if not claude:
            return _finish(self.result, stopped="no claude binary")
        return self._attempt(claude)

    def _idle(self) -> dict:
        if self.params.apply:  # nothing to ask, but what no longer applies still goes
            pruned_digest, pruned_state = dg.pruned(self.stored, self.state, self.topics)
            if pruned_digest != self.stored:
                dg.write(self.data, pruned_digest)
            if pruned_state != self.state:
                jobs.write_json(self.cdir / DIGEST_ATTEMPTS_NAME, pruned_state)
        return _finish(self.result)

    def _attempt(self, claude: str) -> dict:
        sessions = self._sessions(claude)
        if sessions.failure is not None:
            return self._failed_session(sessions.failure)
        new_digest, new_state, counts = dg.decide(
            self.works, sessions.proposed, sessions.verdicts, self.stored, self.state
        )
        new_digest, new_state = dg.pruned(new_digest, new_state, self.topics)
        new_state["failures"] = {"count": 0, "fingerprint": None}
        if self.params.apply and not self._write_files(new_digest, new_state):
            return self._failed_session("the digest or its state could not be written")
        self.result.update(counts)
        if not self.params.apply:  # as the rewording: a dry run reports nothing as written
            self.result["headings_written"] = self.result["lines_written"] = 0
        return self._sheet_result(sessions, new_digest)

    def _save_state(self, new: dict) -> None:
        if self.params.apply:
            jobs.write_json(self.cdir / DIGEST_ATTEMPTS_NAME, new)

    def _failed_session(self, why: str) -> dict:
        self.failures["count"] += 1
        self.failures["fingerprint"] = self.fingerprint
        try:
            self._save_state(self.state)
        except Exception:  # the state file may be what cannot be written: the result still says so
            logger.debug("digest state not saved", exc_info=True)
        return _finish(self.result, stopped=why)

    def _write_files(self, new_digest: dict, new_state: dict) -> bool:
        try:
            dg.write(self.data, new_digest)
            self._save_state(new_state)
        except Exception:
            logger.debug("digest or state not written", exc_info=True)
            return False
        return True

    def _sessions(self, claude: str) -> _Sessions:
        scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-digest-"))
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
            return _Sessions({}, {}, {}, "the writer session gave no usable answer")
        pairs = dg.pairs(self.works, proposed)
        if not pairs:
            return _Sessions(proposed, {}, {})
        return self._ask_checker(claude, scratch, proposed, pairs)

    def _ask_writer(self, claude: str, scratch: Path) -> dict | None:
        limits = corroborate_run.SessionLimits(corroborate_run.PROPOSE_MODEL, self.params.budget)
        job = corroborate_run.AskJob(
            corroborate_run.DIGEST_BRIEF, dg.blocks(self.works), "topics", DIGEST_WRITER_OUT
        )
        payload, cost, ok = corroborate_run._ask(claude, scratch, "write", limits, job)
        self.result["cost"] += cost
        try:
            return dg.validate(payload, self.works) if ok else None
        except ValueError:
            return None

    def _ask_checker(self, claude: str, scratch: Path, proposed: dict, pairs: list) -> _Sessions:
        limits = corroborate_run.SessionLimits(corroborate_run.CHECK_MODEL, self.params.budget)
        job = corroborate_run.AskJob(
            corroborate_run.DIGEST_CHECK_BRIEF, _digest_pair_text(pairs), "pairs", DIGEST_CHECK_OUT
        )
        payload, cost, ok = corroborate_run._ask(claude, scratch, "check", limits, job)
        self.result["cost"] += cost
        checked = _digest_verdicts(payload) if ok else None
        if checked is None:
            return _Sessions({}, {}, {}, "the checker session gave no usable answer")
        return _Sessions(proposed, *checked)

    def _sheet_result(self, sessions: _Sessions, new_digest: dict) -> dict:
        sheet = self.params.sheet
        if sheet is not None:
            ctx = _Sheet(
                sessions.proposed,
                sessions.verdicts,
                sessions.reasons,
                new_digest,
                self.params.apply,
            )
            if not self._write_sheet(sheet, ctx):
                return _finish(
                    self.result, stopped=self.result["stopped"] or "the sheet could not be written"
                )
        return _finish(self.result)

    def _write_sheet(self, sheet: Path, ctx: _Sheet) -> bool:
        """False when the sheet could not be written: the run is done, so that must not turn it into a failed step."""
        try:
            _digest_sheet(sheet, _sheet_rows(ctx, self.works))
        except Exception:
            logger.debug("digest sheet not written", exc_info=True)
            return False
        return True


def _sheet_rows(ctx: _Sheet, works: list[dg.Work]) -> list[tuple]:
    rows: list[tuple] = []
    for w in works:
        rows += _topic_rows(ctx, w)
    return rows


def _topic_rows(ctx: _Sheet, w: dg.Work) -> list[tuple]:
    p = ctx.proposed.get(w.topic, {})
    paired = {m.handle: (ident, head, text) for ident, m, head, text in dg.pairs([w], ctx.proposed)}
    head_text = p.get("heading") if w.heading_state == "write" else w.heading
    view = _TopicView(w, p, paired, ctx.new_digest["topics"].get(w.topic, {}), head_text)
    rows = []
    if w.heading_state == "write" and isinstance(head_text, str):
        outcome, why = _heading_outcome(ctx, view, head_text)
        rows.append((w.topic, head_text, "", "", "", "", outcome, why))
    for m in w.lessons:
        row = _lesson_row(ctx, view, m)
        if row is not None:
            rows.append(row)
    return rows


def _heading_outcome(ctx: _Sheet, view: _TopicView, head_text: str) -> tuple[str, str | None]:
    problem = dg.heading_problem(head_text)
    if problem is not None:
        return "refused_code", problem
    if view.stored_topic.get("heading") == head_text:
        return ("would be written" if not ctx.apply else "written"), None
    if not any(isinstance(ctx.verdicts.get(ident), dict) for ident, _h, _t in view.paired.values()):
        return "unjudged", None
    return "refused_check", None


def _lesson_row(ctx: _Sheet, view: _TopicView, m) -> tuple | None:
    topic = view.work.topic
    if m.handle in view.paired:
        ident, head, text = view.paired[m.handle]
        return (
            topic,
            head,
            ident,
            m.claim,
            m.short,
            text,
            _paired_outcome(ctx, view, m, ident, text),
            ctx.reasons.get(ident),
        )
    text = (view.proposed.get("lines") or {}).get(m.handle)
    if m in view.work.write and isinstance(text, str):
        head_text = view.head_text
        problem = (
            dg.line_problem(text, m)
            if (head_text is not None and dg.heading_problem(head_text) is None)
            else None
        )
        outcome, why = (
            ("refused_code", problem) if problem else ("unjudged", "its heading was refused")
        )
        return (topic, head_text, f"g:{m.handle}", m.claim, m.short, text, outcome, why)
    return None


def _paired_outcome(ctx: _Sheet, view: _TopicView, m, ident: str, text: object) -> str:
    line = view.stored_topic.get("lines", {}).get(m.handle)
    if line is not None and line["text"] == text:
        outcome = "written" if m in view.work.write else "kept"
        return f"would be {outcome}" if not ctx.apply and outcome == "written" else outcome
    return "unjudged" if not isinstance(ctx.verdicts.get(ident), dict) else "refused_check"
