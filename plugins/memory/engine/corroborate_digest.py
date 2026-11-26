"""mem-corroborate: `digest`, a heading per topic and a line per lesson for the session start."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import auto_state as au
import corroborate
import corroborate_run
import corroborate_state
import digest as dg
import records


DIGEST_ATTEMPTS_NAME = "digest-attempts.json"


DIGEST_WRITER_OUT = "digest-write.json"


DIGEST_CHECK_OUT = "digest-check.json"


def _digest_state(cdir: Path) -> dict:
    """The step's memory, read defensively: a missing or broken file is an empty state."""
    data = au.read_json(cdir / DIGEST_ATTEMPTS_NAME)
    tries = data.get("tries")
    failures = data.get("failures")
    tries = {k: v for k, v in tries.items() if isinstance(k, str) and isinstance(v, int) and v > 0} if isinstance(tries, dict) else {}
    failures = failures if isinstance(failures, dict) else {}
    count = failures.get("count")
    return {"tries": tries, "failures": {"count": count if isinstance(count, int) and count > 0 else 0,
                                         "fingerprint": failures.get("fingerprint")}}


def _digest_pair_text(pairs: list) -> str:
    """What the checker reads: per lesson `id`, `claim`, `context` when there is one, `heading`, `line`; a blank line between."""
    one = lambda t: " ".join(str(t).split())   # noqa: E731
    blocks = []
    for ident, m, head, text in pairs:
        rows = [f"id: {ident}", f"claim: {one(m.claim)}"]
        if m.context:
            rows.append(f"context: {one(m.context)}")
        rows += [f"heading: {one(head)}", f"line: {one(text)}"]
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
            verdicts[v["id"]] = {"fits": v.get("fits") is True, "faithful": v.get("faithful") is True}
            if isinstance(v.get("reason"), str):
                reasons[v["id"]] = v["reason"]
    return verdicts, reasons


def _digest_sheet(path: Path, rows: list[tuple]) -> None:
    lines = ["| topic | heading | id | claim | short form | line | outcome | checker's reason |", "|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(corroborate_run._cell(x) for x in row) + " |" for row in rows]
    corroborate_state.write_private(path, "\n".join(lines) + "\n")


def digest_auto(claude: str | None, budget: float, *, apply: bool = True, sheet: Path | None = None) -> dict:
    """Writes the digest of the loaded lessons, with nobody reading it first: a writer session (a heading per topic, a
    line per lesson), the code checks (`digest.decide`), a second session that checks every line against its claim, then
    the digest file and the step's state. It writes no record and runs no `mem` command: nothing to journal or undo. With
    `apply` false it writes neither file (the sessions still run, and cost). Never raises: a failure is a counted result
    with `stopped` set."""
    result = {"topics": 0, "headings_written": 0, "lines_written": 0, "refused_code": 0, "refused_check": 0, "missing": 0,
              "unjudged": 0, "cost": 0.0, "stopped": None}
    try:
        cdir = corroborate_state.corroborate_dir(corroborate_state.data_dir())
        lock = au.take_run_lock(cdir)
        if lock is None:
            return {**result, "stopped": "a run is going"}
        try:
            return _digest_locked(claude, budget, cdir, result, apply, sheet)
        finally:
            os.close(lock)
    except Exception:   # noqa: BLE001
        result["cost"] = round(result["cost"], 6)
        return {**result, "stopped": "the step failed"}


def _digest_locked(claude: str | None, budget: float, cdir: Path, result: dict, apply: bool, sheet: Path | None) -> dict:
    def finish(**changes) -> dict:
        result.update(changes)
        result["cost"] = round(result["cost"], 6)
        return result

    data = corroborate_state.data_dir()
    lessons = [m for m in records.load_memories(records.global_memories_root(os.environ), "global") if m.error is None]
    stored = dg.read(data)
    state = _digest_state(cdir)
    topics = dg.topics_of(lessons, datetime.date.today())
    works = dg.work(topics, stored, state)
    result["topics"] = len(works)
    if not works:
        if apply:   # nothing to ask, but what no longer applies still goes
            pruned_digest, pruned_state = dg.pruned(stored, state, topics)
            if pruned_digest != stored:
                dg.write(data, pruned_digest)
            if pruned_state != state:
                au.write_json(cdir / DIGEST_ATTEMPTS_NAME, pruned_state)
        return finish()
    keys = sorted([*(dg._heading_key(w.topic, w.lessons) for w in works if w.heading_state == "write"),
                   *(dg._line_key(m, w.lessons) for w in works for m in w.write)])
    fingerprint = hashlib.sha256(json.dumps(keys).encode()).hexdigest()
    failures = state["failures"]
    if failures["fingerprint"] != fingerprint:
        failures["count"] = 0
    if failures["count"] >= corroborate.FILL_FAILURES:
        return finish(stopped="waiting for the lessons to change", topics=0)
    if not claude:
        return finish(stopped="no claude binary")

    def save_state(new: dict) -> None:
        if apply:
            au.write_json(cdir / DIGEST_ATTEMPTS_NAME, new)

    def failed_session(why: str) -> dict:
        failures["count"] += 1
        failures["fingerprint"] = fingerprint
        try:
            save_state(state)
        except Exception:   # noqa: BLE001   (the state file may be what cannot be written: the result still says so)
            pass
        return finish(stopped=why)

    scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-digest-"))
    reasons: dict[str, str] = {}
    try:
        corroborate_state.write_private(scratch / "settings.json", json.dumps({"disableAllHooks": True}))
        payload, cost, ok = corroborate_run._ask(claude, scratch, "write", corroborate_run.PROPOSE_MODEL, budget, corroborate_run.DIGEST_BRIEF, dg.blocks(works), "topics",
                                 DIGEST_WRITER_OUT)
        result["cost"] += cost
        try:
            proposed = dg.validate(payload, works) if ok else None
        except ValueError:
            proposed = None
        if proposed is None:
            return failed_session("the writer session gave no usable answer")
        pairs = dg.pairs(works, proposed)
        verdicts: dict = {}
        if pairs:
            payload, cost, ok = corroborate_run._ask(claude, scratch, "check", corroborate_run.CHECK_MODEL, budget, corroborate_run.DIGEST_CHECK_BRIEF, _digest_pair_text(pairs),
                                     "pairs", DIGEST_CHECK_OUT)
            result["cost"] += cost
            checked = _digest_verdicts(payload) if ok else None
            if checked is None:
                return failed_session("the checker session gave no usable answer")
            verdicts, reasons = checked
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    new_digest, new_state, counts = dg.decide(works, proposed, verdicts, stored, state)
    new_digest, new_state = dg.pruned(new_digest, new_state, topics)
    new_state["failures"] = {"count": 0, "fingerprint": None}
    if apply:
        try:
            dg.write(data, new_digest)
            save_state(new_state)
        except Exception:   # noqa: BLE001
            return failed_session("the digest or its state could not be written")
    result.update(counts)
    if not apply:   # as the rewording: a dry run reports nothing as written
        result["headings_written"] = result["lines_written"] = 0
    if sheet is not None:
        try:   # the run is done: a sheet that cannot be written must not turn it into a failed step
            rows = []
            for w in works:
                p = proposed.get(w.topic, {})
                paired = {m.handle: (ident, head, text) for ident, m, head, text in dg.pairs([w], proposed)}
                stored_topic = new_digest["topics"].get(w.topic, {})
                head_text = p.get("heading") if w.heading_state == "write" else w.heading
                if w.heading_state == "write" and isinstance(head_text, str):
                    problem = dg.heading_problem(head_text)
                    if problem is not None:
                        outcome, why = "refused_code", problem
                    elif stored_topic.get("heading") == head_text:
                        outcome, why = ("would be written" if not apply else "written"), None
                    elif not any(isinstance(verdicts.get(ident), dict) for ident, _h, _t in paired.values()):
                        outcome, why = "unjudged", None
                    else:
                        outcome, why = "refused_check", None
                    rows.append((w.topic, head_text, "", "", "", "", outcome, why))
                for m in w.lessons:
                    ident, head, text = paired.get(m.handle) or (f"g:{m.handle}", head_text, (p.get("lines") or {}).get(m.handle))
                    if m.handle in paired:
                        line = stored_topic.get("lines", {}).get(m.handle)
                        if line is not None and line["text"] == text:
                            outcome = "written" if m in w.write else "kept"
                            outcome = f"would be {outcome}" if not apply and outcome == "written" else outcome
                        elif not isinstance(verdicts.get(ident), dict):
                            outcome = "unjudged"
                        else:
                            outcome = "refused_check"
                        why = reasons.get(ident)
                    elif m in w.write and isinstance(text, str):
                        problem = dg.line_problem(text, m) if (head_text is not None and dg.heading_problem(head_text) is None) else None
                        outcome, why = ("refused_code", problem) if problem else ("unjudged", "its heading was refused")
                    else:
                        continue
                    rows.append((w.topic, head, ident, m.claim, m.short, text, outcome, why))
            _digest_sheet(sheet, rows)
        except Exception:   # noqa: BLE001
            return finish(stopped=result["stopped"] or "the sheet could not be written")
    return finish()
