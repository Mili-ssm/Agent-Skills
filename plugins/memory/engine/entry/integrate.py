"""mem-integrate: joins loose knowledge notes to the parts of syntheses with two cheap read-only sessions each
(plan 2026-11-26-memory-seamless, stage 3). Not measured: opt-in by running it.

`run`: takes the `mem-auto` run lock (busy: nothing starts), commits the store, asks `mem synthesis integrate
--candidates`, drops the notes the done list already holds, and per synthesis runs (1) a place session that answers
`note | part | append|unit N | fingerprint` lines and (2) a check session that lists the rows it accepts. Only rows
both answered, and that `placement_rows` kept, are written by Python to a rows file and applied with ONE
`mem synthesis integrate FILE` (one logged group per synthesis). The sessions only Read their input folder, so no
model text reaches the store. State: `<state folder>/integrate/<id>/` (`done.json`, `<run id>/record.json`, logs).

`--undo RUN` undoes a run's groups newest first (exit 2 when a file changed since: nothing is restored, stdout says
how many groups remain); `status` prints the last run.

Usage: mem-integrate run [--store PATH] [--claude PATH] [--budget USD] [--dry-run] | status | --undo RUN | --self-check
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from core import auto_state, headless, jobs
from integrate import answers, plan
from integrate import state as run_state
from integrate import undo as run_undo
from integrate.rows import row_of
from synthesize import pipeline as sp
from synthesize import run as synth_run

if TYPE_CHECKING:
    from integrate.rows import Row

logger = logging.getLogger(__name__)

DEFAULT_BUDGET = 0.50  # USD per run
SESSION_TIMEOUT = 600
PRIVATE_MODE = 0o700
CHARS_PER_TOKEN = 4
EPSILON = 1e-9
FAILURE_CUT = 150
INTEGRATE_BRIEFS = Path(__file__).resolve().parents[1] / "integrate" / "briefs"
SESSION_VARS = (
    "CLAUDE_ENV_FILE",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_DATA",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PID",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
)
UNREADABLE = re.compile(r"permission denied|cannot read|could not read|no such file", re.IGNORECASE)
UNREADABLE_FAILURE = "the session could not read its input file"
COLUMNS = ("synthesis", "notes", "placed", "checked", "applied", "refused", "cost")


def budget_of(value: str | float | None) -> float:
    if value is None:
        return DEFAULT_BUDGET
    try:
        number = float(value)
    except ValueError:
        return DEFAULT_BUDGET
    return number if number > 0 else DEFAULT_BUDGET


def state_folder(store: Path) -> Path:
    """`<state folder>/integrate/<id>`: the done list and one folder per run."""
    ident = hashlib.sha1(str(store.resolve()).encode()).hexdigest()[:12]
    return synth_run.state_dir() / "integrate" / ident


def run_env(store: Path) -> dict:
    """The `mem` calls and the sessions: aimed at `store`; a configured memories folder is kept."""
    env = synth_run.session_env(store)
    if os.environ.get("MEM_MEMORIES"):
        env["MEM_MEMORIES"] = os.environ["MEM_MEMORIES"]
    return env


def row_line(row: Row) -> str:
    """The row as a line of a rows file, built from its parsed fields."""
    action = "append" if row.unit is None else f"unit {row.unit}"
    return f"{row.note} | {row.target} | {action} | {row.fingerprint}"


def session_cmd(
    claude: str, work: Path, brief: str, settings: Path, max_budget: float
) -> list[str]:
    """One Haiku session. Only Read exists and only inside `work` (`//` is an absolute path in a rule); no shell,
    no web, no write; hooks are disabled by `settings`."""
    return headless.command(
        headless.Session(
            claude=claude,
            prompt=brief,
            model="haiku",
            settings=settings,
            effort="medium",
            tools=("Read",),
            allowed=(f"Read(/{work}/**)",),
            disallowed=("Bash", "WebSearch", "WebFetch"),
            max_budget=max_budget,
        )
    )


@dataclass
class Tally:
    """One synthesis's row of the summary table."""

    synthesis: str
    notes: int = 0
    placed: int = 0
    checked: int = 0
    applied: int = 0
    refused: int = 0
    cost: float = 0.0

    def cells(self) -> list[str]:
        return [
            self.synthesis,
            str(self.notes),
            str(self.placed),
            str(self.checked),
            str(self.applied),
            str(self.refused),
            f"{self.cost:.3f}",
        ]


@dataclass
class Job:
    """One started run: its folder, its record (rewritten after every group) and what it spent."""

    store: Path
    env: dict
    claude: str
    budget: float
    folder: Path
    record: run_state.RunRecord
    tallies: list[Tally] = field(default_factory=list)
    current: Tally | None = (
        None  # the synthesis being worked on: every session's cost lands in its row
    )

    @property
    def root(self) -> Path:
        return self.folder / self.record.run_id

    def log(self, text: str) -> None:
        fd_log = os.open(self.root / "log.txt", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd_log, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def fail(self, text: str) -> None:
        self.record.failures.append(text)
        self.log(f"failure: {text}")
        run_state.write_record(self.folder, self.record)

    def ask(self, name: str, work: Path, data: Any) -> tuple[str, float] | None:
        """Runs session `name` over `data` written to `work`; (answer, cost), or None with a failure recorded."""
        if self.budget - self.record.cost <= EPSILON:
            self.fail("budget spent")
            return None
        work.mkdir(parents=True, exist_ok=True)
        input_file = work / f"{name}.json"
        input_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
        brief = sp.brief(name, briefs=INTEGRATE_BRIEFS, INPUT_FILE=str(input_file))
        cmd = session_cmd(self.claude, work, brief, settings, self.budget - self.record.cost)
        start = time.monotonic()
        raw = headless.run_raw(cmd, cwd=work, env=self.env, timeout=SESSION_TIMEOUT).stdout
        (work / f"{name}.jsonl").write_text(raw, encoding="utf-8")
        done = sp.parse(raw)
        self.record.cost += done["cost"]
        if self.current is not None:
            self.current.cost += done["cost"]
        self.log(
            f"{name}: has_result={done['has_result']} error={done['error']} cost={done['cost']:.3f} "
            f"wall={time.monotonic() - start:.1f}s answer={' '.join(done['answer'].split())[:200]}"
        )
        if not done["has_result"] or done["error"]:
            self.fail(f"{name} session {'failed' if done['has_result'] else sp.NO_COST}")
            return None
        return done["answer"], done["cost"]


def candidates(job: Job) -> list[dict] | None:
    """The synthesis candidates minus the notes the done list holds; None (a failure recorded) when `mem` gave none."""
    found = sp.mem(job.store, job.env, "synthesis", "integrate", "--candidates")
    try:
        data = json.loads(found.stdout) if found.returncode == 0 else None
    except ValueError:
        data = None
    if not isinstance(data, list):
        text = (found.stderr or found.stdout).strip()[:FAILURE_CUT]
        job.fail(f"mem synthesis integrate --candidates failed: {text}")
        return None
    done = run_state.read_done(job.folder)
    out = []
    for cand in data:
        cand["notes"] = [
            n for n in cand["notes"] if not run_state.is_done(done, n["handle"], n["digest"])
        ]
        if cand["notes"]:
            out.append(cand)
    return out


def place_input(cand: dict) -> dict:
    """What the place session reads: the notes with their claims, the parts with fingerprint and numbered units."""
    syn = cand["synthesis"]
    return {
        "synthesis": syn,
        "notes": [{"note": n["handle"], "claim": n["claim"]} for n in cand["notes"]],
        "parts": [
            {
                "part": f"s:{syn}#{p['section']}",
                "fingerprint": p["fingerprint"],
                "units": p["units"],
            }
            for p in cand["parts"]
        ],
    }


def offered_of(cand: dict) -> plan.Offered:
    syn = cand["synthesis"]
    return plan.Offered(
        frozenset(n["handle"] for n in cand["notes"]),
        {
            f"s:{syn}#{p['section']}": plan.PartInfo(p["fingerprint"], len(p["units"]))
            for p in cand["parts"]
        },
    )


def check_input(cand: dict, rows: list[Row]) -> list[dict]:
    """What the check session reads: each proposed row with the note's claim and the text it would touch."""
    claims = {n["handle"]: n["claim"] for n in cand["notes"]}
    parts = {f"s:{cand['synthesis']}#{p['section']}": p["units"] for p in cand["parts"]}
    items = []
    for row in rows:
        units = parts[row.target]
        if row.unit is None:
            target = {"part_text": " ".join(u["text"] for u in units)}
        else:
            target = {"unit": row.unit, "sentence": units[row.unit - 1]["text"]}
        items.append({"row": row_line(row), "claim": claims[row.note], **target})
    return items


def agreed(rows: list[Row], check_answer: str) -> list[Row] | None:
    """The rows the check answer lists too; None when that answer is malformed (it keeps none)."""
    lines = answers.answer_lines(check_answer)
    if lines is None:
        return None
    accepted = {row_of(x) for x in lines if x != "none" and not x.startswith("#")}
    return [row for row in rows if row in accepted]


def apply_rows(job: Job, work: Path, synthesis: str, rows: list[Row]) -> tuple[int, int] | None:
    """Applies the rows with one `mem synthesis integrate`; (applied, refused) and the group recorded, or None
    (a failure recorded) when the command failed."""
    rows_file = work / "rows.txt"
    rows_file.write_text("\n".join(row_line(r) for r in rows) + "\n", encoding="utf-8")
    found = sp.mem(job.store, job.env, "synthesis", "integrate", str(rows_file))
    job.log(f"apply: exit {found.returncode}\n{found.stdout.strip()}\n{found.stderr.strip()}")
    if found.returncode:
        job.fail(
            f"mem synthesis integrate failed: {(found.stderr or found.stdout).strip()[:FAILURE_CUT]}"
        )
        return None
    lines = found.stdout.splitlines()
    for line in lines:
        if line.startswith("group\t"):
            group = run_state.GroupRecord([f"s:{synthesis}"], line.split("\t", 1)[1], "integrate")
            job.record.groups.append(group)
            run_state.write_record(job.folder, job.record)
    count = {w: sum(x.startswith(w + "\t") for x in lines) for w in ("applied", "refused")}
    return count["applied"], count["refused"]


def ask_readable(
    job: Job, name: str, work: Path, cand: dict, data: Any
) -> tuple[str, float] | None:
    """`Job.ask`, and None with a failure recorded when the answer says the session could not read its file."""
    asked = job.ask(name, work, data)
    if asked is not None and UNREADABLE.search(asked[0]):
        job.fail(f"{cand['synthesis']}: {UNREADABLE_FAILURE}")
        return None
    return asked


def place_and_check(job: Job, work: Path, cand: dict, tally: Tally) -> list[Row] | None:
    """The rows both sessions agree on; None (a failure recorded) when a session failed or an answer is malformed.

    The place answer is the only malformed one that stops the synthesis; a malformed check answer keeps none."""
    placed = ask_readable(job, "place", work, cand, place_input(cand))
    if placed is None:
        return None
    lines = answers.answer_lines(placed[0])
    if lines is None:
        job.fail(f"{cand['synthesis']}: the place answer is not rows or none")
        return None
    rows, refusals = plan.placement_rows(lines, offered_of(cand))
    tally.placed, tally.refused = len(rows), len(refusals)
    job.log("place refusals: " + "; ".join(refusals))
    if not rows:
        return []
    checked = ask_readable(job, "check", work, cand, check_input(cand, rows))
    if checked is None:
        return None
    kept = agreed(rows, checked[0])
    if kept is None:
        job.fail(f"{cand['synthesis']}: the check answer is not rows or none")
        return None
    tally.checked = len(kept)
    return kept


def integrate_synthesis(job: Job, index: int, cand: dict) -> None:
    syn = cand["synthesis"]
    tally = Tally(syn, notes=len(cand["notes"]))
    job.tallies.append(tally)
    job.current = tally
    work = job.root / "work" / str(index)
    kept = place_and_check(job, work, cand, tally)
    if kept is None:
        return  # nothing is marked done: a failed session is tried again
    if kept:
        counts = apply_rows(job, work, syn, kept)
        if counts is None:
            return  # a failed apply marks nothing done: the notes are offered again
        tally.applied, tally.refused = counts[0], tally.refused + counts[1]
    for note in cand["notes"]:
        run_state.mark_done(job.folder, note["handle"], note["digest"])


def table(tallies: list[Tally]) -> str:
    rows = [list(COLUMNS), *(t.cells() for t in tallies)]
    widths = [max(len(r[i]) for r in rows) for i in range(len(COLUMNS))]
    return "\n".join(
        " | ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)).rstrip() for r in rows
    )


def report(job: Job) -> None:
    if job.tallies:
        print(table(job.tallies))
    for text in job.record.failures:
        print(f"failed: {text}")
    print(f"cost: {job.record.cost:.3f} USD of {job.budget:.2f}; run {job.record.run_id}")


def work_steps(job: Job) -> None:
    found = candidates(job)
    for index, cand in enumerate(found or []):
        integrate_synthesis(job, index, cand)
        if job.record.failures and job.record.failures[-1] == "budget spent":
            return


def cmd_run(store: Path, claude: str | None, budget_arg: str | None) -> int:
    folder = state_folder(store)
    fd = jobs.take_run_lock(auto_state.auto_dir(synth_run.state_dir(), store))
    if fd is None:
        print("mem-integrate: a run holds the lock")
        return 0
    try:
        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        record = run_state.RunRecord(run_id, time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        job = Job(store, run_env(store), claude or "", budget_of(budget_arg), folder, record)
        jobs.private_dir(job.root)
        run_state.write_record(folder, record)
        if not claude:
            job.fail("no claude binary (--claude, CLAUDE_CODE_EXECPATH or PATH)")
        else:
            _guarded(job)
        report(job)
    finally:
        os.close(fd)
    return 0


def _guarded(job: Job) -> None:
    try:
        synth_run.history_commit(job.store, job.env, "mem-integrate: before", job.log)
        work_steps(job)
    except (
        Exception
    ) as exc:  # anything after the lock ends as a failure line; the groups so far stay recorded
        logger.debug("integrate run failed", exc_info=True)
        job.fail(f"{type(exc).__name__}: {exc}"[:FAILURE_CUT])
    finally:
        synth_run.history_commit(job.store, job.env, "mem-integrate: after", job.log)


def cmd_dry_run(store: Path, budget_arg: str | None) -> int:
    """Lists what a run would do; starts no session and changes nothing."""
    env = run_env(store)
    found = sp.mem(store, env, "synthesis", "integrate", "--candidates")
    try:
        data = json.loads(found.stdout) if found.returncode == 0 else None
    except ValueError:
        data = None
    if not isinstance(data, list):
        print(
            f"mem-integrate: no candidates: {(found.stderr or found.stdout).strip()[:FAILURE_CUT]}"
        )
        return 0
    done = run_state.read_done(state_folder(store))
    for cand in data:
        notes = [n for n in cand["notes"] if not run_state.is_done(done, n["handle"], n["digest"])]
        if notes:
            size = len(json.dumps(place_input({**cand, "notes": notes}), ensure_ascii=False))
            print(
                f"{cand['synthesis']}: {len(notes)} notes, 2 sessions (place, check), "
                f"place input about {size // CHARS_PER_TOKEN} tokens"
            )
    if jobs.lock_held(auto_state.auto_dir(synth_run.state_dir(), store)):
        print("would not start: a run holds the lock")
    print(f"budget: {budget_of(budget_arg):.2f} USD per run; nothing was started or changed")
    return 0


UNDO_REFUSED = 2


def cmd_undo(store: Path, run_id: str) -> int:
    """Undoes the groups of run `run_id`; exit 2 on a refusal (stderr names the file) or an unknown run."""
    fd = jobs.take_run_lock(auto_state.auto_dir(synth_run.state_dir(), store))
    if fd is None:
        print("mem-integrate: a run holds the lock; nothing was undone", file=sys.stderr)
        return UNDO_REFUSED
    env = run_env(store)
    try:
        result = run_undo.undo(
            store, state_folder(store), run_id, lambda *args: sp.mem(store, env, *args)
        )
    finally:
        os.close(fd)
    for group_id in result.already_restored:
        print(f"already restored: group {group_id}")
    print(f"undone: {result.undone}")
    print(f"remaining: {result.remaining}")
    if result.refusal:
        print(f"mem-integrate: {result.refusal}", file=sys.stderr)
        return UNDO_REFUSED
    return 0


def cmd_status(store: Path) -> int:
    """The last run's id, state, cost, groups and failure lines."""
    folder = state_folder(store)
    run_id = run_state.last_run_id(folder)
    record = run_state.read_record(folder, run_id) if run_id else None
    if record is None:
        print("mem-integrate: no run yet")
        return 0
    undone = sum(g.undone for g in record.groups)
    state = (
        "failed"
        if record.failures
        else "undone"
        if record.groups and undone == len(record.groups)
        else "ok"
    )
    print(f"run: {record.run_id} (started {record.started})")
    print(f"state: {state}")
    print(f"cost: {record.cost:.3f} USD")
    print(f"groups: {len(record.groups)}")
    print(f"undone: {undone}")
    for text in record.failures:
        print(f"failed: {text}")
    return 0


class SelfCheckError(Exception):
    """A self-check step failed; the message says which."""


def _require(ok: object, reason: str) -> None:
    if not ok:
        raise SelfCheckError(reason)


FAKE_CLAUDE = """#!/usr/bin/env python3
import json
plan_file, count_file = {plan!r}, {count!r}
plan = json.load(open(plan_file))
try:
    n = int(open(count_file).read())
except OSError:
    n = 0
open(count_file, "w").write(str(n + 1))
answer = plan[n] if n < len(plan) else "none"
print(json.dumps({{"type": "result", "is_error": False, "result": answer,
                  "total_cost_usd": 0.0, "modelUsage": {{}}}}))
"""
CHECK_PART = "Values have exactly one owner.[old-note](../knowledge/notes/old-note.md)"
NOTE_BODY = (
    "## Claim\n\n{claim}\n\n## Evidence\n\nObserved.\n\n## Applies when\n\nAlways.\n\n"
    "## Does not apply when\n\nNever.\n"
)


def _check_briefs() -> None:
    for name in ("place", "check"):
        try:
            text = sp.brief(name, briefs=INTEGRATE_BRIEFS, INPUT_FILE="/tmp/input.json")
        except AssertionError as exc:
            raise SelfCheckError(f"the {name} brief: {exc}") from exc
        _require("/tmp/input.json" in text, f"the {name} brief does not name its input file")


def _check_parser() -> None:
    row = "n | s:a#b | append | ab12cd34ef"
    _require(answers.answer_lines(f"```\n{row}\n```") == [row], "a good answer was refused")
    _require(answers.answer_lines("none") == ["none"], "`none` was refused")
    _require(answers.answer_lines("I think n fits.") is None, "a malformed answer was accepted")
    _require(answers.answer_lines(f"none\n{row}") is None, "`none` with a row was accepted")


def _mem(store: Path, env: dict, *args: str) -> str:
    found = sp.mem(store, env, *args)
    _require(
        found.returncode == 0, f"mem {' '.join(args[:2])} failed: {found.stderr.strip()[:200]}"
    )
    return found.stdout


def _build_store(tmp: Path) -> tuple[Path, dict]:
    """A store with synthesis `alpha` (part `basics`, member `old-note`) and one loose note, `new-note`."""
    store = tmp / "store"
    env = run_env(store)
    found = subprocess.run(
        [str(sp.MEM), "init", str(store)],
        env=env,
        cwd=tmp,
        capture_output=True,
        text=True,
        check=False,
    )
    _require(found.returncode == 0, f"mem init failed: {found.stderr.strip()[:200]}")
    for slug, claim in (("old-note", "Ownership is tracked."), ("new-note", "Moves are default.")):
        body = tmp / f"{slug}.md"
        body.write_text(NOTE_BODY.format(claim=claim), encoding="utf-8")
        _mem(
            store, env, "new", "knowledge", "--slug", slug, "--claim", claim, "--topics", "notes",
            "--confidence", "low", "--level", "basic", "--origin", "experience",
            "--body-file", str(body),
        )  # fmt: skip
    summary, part = tmp / "summary.md", tmp / "part.md"
    summary.write_text("Rust ownership.\n", encoding="utf-8")
    part.write_text(
        f"{CHECK_PART}\n\nSources: [old-note](../knowledge/notes/old-note.md)\n",
        encoding="utf-8",
    )
    _mem(
        store, env, "synthesis", "new", "--title", "Alpha", "--topics", "notes", "--slug", "alpha",
        "--summary-file", str(summary),
    )  # fmt: skip
    _mem(
        store, env, "synthesis", "add", "s:alpha", "--section", "Basics", "--body-file", str(part)
    )  # fmt: skip
    _mem(store, env, "synthesis", "attach", "old-note", "s:alpha#basics")
    return store, env


def _fake_claude(tmp: Path, replies: list[str]) -> Path:
    (tmp / "plan.json").write_text(json.dumps(replies), encoding="utf-8")
    script = tmp / "fake-claude"
    script.write_text(
        FAKE_CLAUDE.format(plan=str(tmp / "plan.json"), count=str(tmp / "count")), encoding="utf-8"
    )
    script.chmod(0o755)
    return script


def _isolate(tmp: Path) -> None:
    """Point every state folder at `tmp`, so the check never touches the owner's data. Changes `os.environ`:
    call it inside `mock.patch.dict(os.environ)`."""
    for name in [k for k in os.environ if k.startswith("MEM_")]:
        os.environ.pop(name)  # every one the check does not set below
    for name, folder in (
        ("MEM_DATA", "data"),
        ("XDG_DATA_HOME", "share"),
        ("MEM_PROJECT", "project"),
        ("XDG_CONFIG_HOME", "cfg"),
    ):
        os.environ[name] = str(tmp / folder)


def _check_flow(place_check: tuple[str, str] | None) -> None:
    with (
        tempfile.TemporaryDirectory(prefix="mem-integrate-check-") as tmp_name,
        mock.patch.dict(os.environ),
    ):
        _isolate(Path(tmp_name))
        _flow(Path(tmp_name), place_check)


def _flow(tmp: Path, place_check: tuple[str, str] | None) -> None:
    store, env = _build_store(tmp)
    cands = json.loads(_mem(store, env, "synthesis", "integrate", "--candidates"))
    _require(cands and cands[0]["parts"], "the fixture store offers no candidate")
    row = f"new-note | s:alpha#basics | append | {cands[0]['parts'][0]['fingerprint']}"
    replies = list(place_check or (row, row))
    claude = _fake_claude(tmp, replies)
    captured = io.StringIO()
    with redirect_stdout(captured):
        code = cmd_run(store, str(claude), None)
    _require(code == 0, f"the run exited {code}")
    folder = state_folder(store)
    run_id = max(p.name for p in folder.iterdir() if p.is_dir())
    record = run_state.read_record(folder, run_id)
    _require(record is not None, "the run left no record")
    failures = record.failures if record else []
    _require(
        not any(UNREADABLE_FAILURE in f for f in failures),
        f"a session could not read its input file: {failures}",
    )
    _require(not failures, f"the run failed: {failures}")
    attached = next(iter(store.glob("knowledge/*/new-note.md"))).read_text(encoding="utf-8")
    _require(
        re.search(r"(?m)^part_of: \"?alpha#basics", attached), "the agreed row was not applied"
    )
    _require(
        record is not None and [g.kind for g in record.groups] == ["integrate"],
        "the run did not record one integrate group",
    )


def self_check(answers_given: tuple[str, str] | None = None) -> int:
    """No cost: the briefs fill, the answer parser on canned input, then the whole flow (a run against a fake
    `claude`) on a small store built in a temp folder. `answers_given` replaces the fake's place and check answers."""
    try:
        _check_briefs()
        _check_parser()
        _check_flow(answers_given)
    except SelfCheckError as exc:
        print(f"self-check failed: {exc}")
        return 1
    except Exception as exc:  # any broken step ends as a line, not a traceback
        logger.debug("self-check failed", exc_info=True)
        print(f"self-check failed: {type(exc).__name__}: {exc}")
        return 1
    print("self-check passed")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("command", nargs="?", choices=["run", "status"])
    parser.add_argument("--store", type=Path, help="default: the store `mem` resolves")
    parser.add_argument(
        "--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    )
    parser.add_argument("--undo", metavar="RUN", help="undo the groups of run RUN, newest first")
    parser.add_argument("--budget", help=f"USD per run (default {DEFAULT_BUDGET})")
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would run; start and change nothing"
    )
    parser.add_argument(
        "--self-check", action="store_true", help="no model: prove the briefs, parser and flow"
    )
    return parser


def _dispatch(args: argparse.Namespace, store: Path) -> int:
    if args.undo:
        return cmd_undo(store, args.undo)
    if args.command == "status":
        return cmd_status(store)
    if args.dry_run:
        return cmd_dry_run(store, args.budget)
    for name in SESSION_VARS:  # left over from the session that started this process
        os.environ.pop(name, None)
    return cmd_run(store, args.claude, args.budget)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    if not args.command and not args.undo:
        parser.error("a command or --undo RUN is required")
    store = args.store.expanduser().resolve() if args.store else synth_run.default_store()
    if store is None or not (store / "mem-store.yaml").is_file():
        print(f"mem-integrate: no store at {store}", file=sys.stderr)
        return 2
    return _dispatch(args, store)
