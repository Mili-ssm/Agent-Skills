"""mem-integrate: joins loose knowledge notes to the parts of syntheses with two cheap read-only sessions each
(plan 2026-11-26-memory-seamless-stage-3-integration). Not measured: opt-in by running it. Claude only: a Codex
default is ignored, `--runner codex` exits 2 (Codex placed 0 of 17 appends in 4 runs, ADR 0037 trial 2026-11-27).

`run`: takes the `mem-auto` run lock (busy: nothing starts), commits the store, asks `mem synthesis integrate
--candidates`, drops the notes the done list already holds, and per synthesis runs (1) a place session that answers
`note | part | append|unit N | fingerprint` lines and (2) a check session that lists the rows it accepts (its stray
lines are ignored and logged: only a row the place session proposed can be kept). Only rows
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
import json
import logging
import math
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core import auto_state, codex_pass, headless, jobs, runner
from integrate import answers, plan
from integrate import state as run_state
from integrate import undo as run_undo
from integrate.rows import row_line
from synthesize import pipeline as sp
from synthesize import run as synth_run

from entry import integrate_self_check

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


def _budget_arg(text: str) -> str:
    """The `--budget` text when it is a finite number above 0; a usage error naming it otherwise."""
    try:
        ok = 0 < float(text) < math.inf
    except ValueError:
        ok = False
    if not ok:
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number above 0")
    return text


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


def session_spec(
    claude: str, work: Path, brief: str, settings: Path, max_budget: float
) -> headless.Session:
    return headless.Session(
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


def session_cmd(
    claude: str, work: Path, brief: str, settings: Path, max_budget: float
) -> list[str]:
    """One Haiku session. Only Read exists and only inside `work` (`//` is an absolute path in a rule); no shell,
    no web, no write; hooks are disabled by `settings`."""
    return headless.command(session_spec(claude, work, brief, settings, max_budget))


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
        if self.spent_up():
            self.fail("budget spent")
            return None
        work.mkdir(parents=True, exist_ok=True)
        input_file = work / f"{name}.json"
        input_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
        brief = sp.brief(name, briefs=INTEGRATE_BRIEFS, INPUT_FILE=str(input_file))
        start = time.monotonic()
        done = self.run_session(work, brief, settings, work / f"{name}.jsonl")
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

    def spent_up(self) -> bool:
        return self.budget - self.record.cost <= EPSILON

    def run_session(self, work: Path, brief: str, settings: Path, log: Path) -> dict:
        """One session, its stream written to `log`; the `sp.parse` dict."""
        cmd = session_cmd(self.claude, work, brief, settings, self.budget - self.record.cost)
        raw = headless.run_raw(cmd, cwd=work, env=self.env, timeout=SESSION_TIMEOUT).stdout
        log.write_text(raw, encoding="utf-8")
        return sp.parse(raw)


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


def log_ignored(job: Job, ignored: list[str]) -> None:
    if ignored:
        shown = "; ".join(x[:80] for x in ignored[:3])
        job.log(f"check: {len(ignored)} lines ignored: {shown}")


def place_and_check(job: Job, work: Path, cand: dict, tally: Tally) -> list[Row] | None:
    """The rows both sessions agree on; None (a failure recorded) when a session failed or an answer is malformed.

    A malformed place answer fails the synthesis: nothing is applied for it. A check answer's stray lines are
    ignored (only rows place proposed can be kept); one that decides nothing fails it too."""
    placed = ask_readable(job, "place", work, cand, place_input(cand))
    if placed is None:
        return None
    lines = answers.answer_lines(placed[0])
    if lines is None:
        job.fail(f"{cand['synthesis']}: the place answer is not rows or none")
        return None
    rows, refusals = plan.placement_rows(lines, plan.offered_of(cand))
    tally.placed, tally.refused = len(rows), len(refusals)
    job.log("place refusals: " + "; ".join(refusals))
    if not rows:
        return []
    checked = ask_readable(job, "check", work, cand, check_input(cand, rows))
    if checked is None:
        return None
    kept = plan.agreed(rows, checked[0])
    log_ignored(job, plan.ignored_lines(rows, checked[0]))
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
        job = Job(
            store,
            run_env(store),
            claude or "",
            budget_of(budget_arg),
            folder,
            record,
        )
        jobs.private_dir(job.root)
        run_state.write_record(folder, record)
        if not job.claude:
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("command", nargs="?", choices=["run", "status"])
    parser.add_argument("--store", type=Path, help="default: the store `mem` resolves")
    parser.add_argument(
        "--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    )
    parser.add_argument("--undo", metavar="RUN", help="undo the groups of run RUN, newest first")
    parser.add_argument(
        "--budget", type=_budget_arg, help=f"USD per run (default {DEFAULT_BUDGET})"
    )
    runner.add_flag(parser)
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
        return integrate_self_check.self_check(sys.modules[__name__])
    if not args.command and not args.undo:
        parser.error("a command or --undo RUN is required")
    if (
        refused := codex_pass.refuse_codex(
            "mem-integrate", args.runner, why=codex_pass.WHY_INTEGRATE
        )
    ) is not None:
        return refused
    store = args.store.expanduser().resolve() if args.store else synth_run.default_store()
    if store is None or not (store / "mem-store.yaml").is_file():
        print(f"mem-integrate: no store at {store}", file=sys.stderr)
        return 2
    return _dispatch(args, store)
