"""mem-integrate: joins loose knowledge notes to the parts of syntheses with two cheap read-only sessions each
(plan 2026-11-26-memory-seamless, stage 3). Not measured: opt-in by running it.

`run`: takes the `mem-auto` run lock (busy: nothing starts), commits the store, asks `mem synthesis integrate
--candidates`, drops the notes the done list already holds, and per synthesis runs (1) a place session that answers
`note | part | append|unit N | fingerprint` lines and (2) a check session that lists the rows it accepts. Only rows
both answered, and that `placement_rows` kept, are written by Python to a rows file and applied with ONE
`mem synthesis integrate FILE` (one logged group per synthesis). The sessions only Read their input folder, so no
model text reaches the store. State: `<state folder>/integrate/<id>/` (`done.json`, `<run id>/record.json`, logs).

Usage: mem-integrate run [--store PATH] [--claude PATH] [--budget USD] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core import auto_state, headless, jobs
from integrate import answers, plan
from integrate import state as run_state
from integrate.rows import row_of
from synthesize import pipeline as sp
from synthesize import run as synth_run

if TYPE_CHECKING:
    from integrate.rows import Row

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
            tools=("Read",),
            allowed=(f"Read(/{work}/**)",),
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


def apply_rows(job: Job, work: Path, synthesis: str, rows: list[Row]) -> tuple[int, int]:
    """Applies the rows with one `mem synthesis integrate`; (applied, refused) and the group recorded."""
    rows_file = work / "rows.txt"
    rows_file.write_text("\n".join(row_line(r) for r in rows) + "\n", encoding="utf-8")
    found = sp.mem(job.store, job.env, "synthesis", "integrate", str(rows_file))
    job.log(f"apply: exit {found.returncode}\n{found.stdout.strip()}\n{found.stderr.strip()}")
    if found.returncode:
        job.fail(
            f"mem synthesis integrate failed: {(found.stderr or found.stdout).strip()[:FAILURE_CUT]}"
        )
        return 0, 0
    lines = found.stdout.splitlines()
    for line in lines:
        if line.startswith("group\t"):
            group = run_state.GroupRecord([f"s:{synthesis}"], line.split("\t", 1)[1], "integrate")
            job.record.groups.append(group)
            run_state.write_record(job.folder, job.record)
    count = {w: sum(x.startswith(w + "\t") for x in lines) for w in ("applied", "refused")}
    return count["applied"], count["refused"]


def place_and_check(job: Job, work: Path, cand: dict, tally: Tally) -> list[Row] | None:
    """The rows both sessions agree on; None (a failure recorded) when a session failed or an answer is malformed.

    The place answer is the only malformed one that stops the synthesis; a malformed check answer keeps none."""
    placed = job.ask("place", work, place_input(cand))
    if placed is None:
        return None
    tally.cost += placed[1]
    lines = answers.answer_lines(placed[0])
    if lines is None:
        job.fail(f"{cand['synthesis']}: the place answer is not rows or none")
        return None
    rows, refusals = plan.placement_rows(lines, offered_of(cand))
    tally.placed, tally.refused = len(rows), len(refusals)
    job.log("place refusals: " + "; ".join(refusals))
    if not rows:
        return []
    checked = job.ask("check", work, check_input(cand, rows))
    if checked is None:
        return None
    tally.cost += checked[1]
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
    work = job.root / "work" / str(index)
    kept = place_and_check(job, work, cand, tally)
    if kept is None:
        return  # nothing is marked done: a failed session is tried again
    if kept:
        applied, refused = apply_rows(job, work, syn, kept)
        tally.applied, tally.refused = applied, tally.refused + refused
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
    synth_run.history_commit(job.store, job.env, "mem-integrate: before", job.log)
    try:
        work_steps(job)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:  # a failure line; the groups so far stay recorded
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--store", type=Path, help="default: the store `mem` resolves")
    parser.add_argument(
        "--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    )
    parser.add_argument("--budget", help=f"USD per run (default {DEFAULT_BUDGET})")
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would run; start and change nothing"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = args.store.expanduser().resolve() if args.store else synth_run.default_store()
    if store is None or not (store / "mem-store.yaml").is_file():
        print(f"mem-integrate: no store at {store}", file=sys.stderr)
        return 2
    if args.dry_run:
        return cmd_dry_run(store, args.budget)
    for name in SESSION_VARS:  # left over from the session that started this process
        os.environ.pop(name, None)
    return cmd_run(store, args.claude, args.budget)
