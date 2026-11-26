#!/usr/bin/env python3
"""Synthesis trials: is a synthesis written by Haiku and fixed in a lean Haiku loop as accurate and complete as one
written by Sonnet with one Haiku fact-check and one Sonnet fix, and at what cost?

Plan: docs/superpowers/plans/2026-11-17-memory-prompts-and-loop.md (its "Loop design" and decision rule bind this script).
Arm S: writer sonnet -> check -> sonnet fixer, no second check. Arm L: writer sonnet -> lean loop. Arm M: writer haiku
(high effort) -> lean loop. Lean loop: check (one line per unsupported claim) -> one haiku fixer that changes only the
listed sentences -> one check scoped to the parts and sentences the fixer reports -> when it still lists claims, one
delete-only haiku step removes those sentences; no third pass. Checker, lean fixer and judge are haiku at high effort (the trial of 2026-11-17 ran at medium).
The judge is blind to the arm; its count is the quality measure. Each step is its own `claude -p` session. Every
pipeline works on its own copy of a store snapshot under `target/mem-trials/` in which the topic's synthesis is gone and
its notes are detached; the owner's store is read once, to make the snapshot, and never written.

Arm R: M's models and effort with the current texts (writer brief, skill, checker and fixer briefs), and the step
`mem-synthesize` ends a topic with: after the loop, `add_references` (one read-only Haiku session, code applies the
references) runs before every measurement, so sizes, judges and calibration see the final text; its cost is in the
pipeline cost and a failure makes the row invalid. Arm M is `main`
as shipped: its own harness, run from a git worktree of `main` (`target/mem-trials/main-worktree`), makes the synthesis
and the pipeline cost, and this script only judges it, so M and R compare the pipeline before and after inline
references. The judge is the same for every arm: the frozen checker brief (`frozen-main/`), reading the synthesis with
its references removed.

Reference judgment (arms M and R, off with --no-ref-judge): a second judge session reads the synthesis with its
references (`ref-judge-brief.md`) and says which sentences state a finding and whether each linked note supports its
sentence; code computes coverage and wrong references from that report. For arm R, 20 wrong references are planted
over the judged syntheses to see whether the judge finds them (calibration). `--backfill-trial` runs
`mem-synthesize --backfill` on a copy of the prepared store and checks what it did, then undoes it with `mem restore`.

Usage: run_trials.py [--claude PATH] [--topic T]... [--arm S|L|M|R]... [--judge-model haiku] [--runs 1] [--jobs 2]
                     [--budget USD (10)] [--work DIR (resume)] [--keep] [--no-ref-judge] [--control-results FILE]
       run_trials.py --backfill-trial [--synthesis HANDLE]... [--budget USD] [--claude PATH] [--keep] | --self-check
It costs model usage (9 pipelines and 9 judges at the defaults, about 7 to 9 USD). --budget is a cap: before any
pipeline, judge, reference judgment or calibration starts, the cost so far plus the reserve of the work in flight plus
the step's reserve must fit under it, and every session this script starts gets `--max-budget-usd` SESSION_CAP_USD.
--rejudge reuses a kept pipeline folder (run an earlier pipeline with --keep).
--control-results FILE reuses the arm M rows of an earlier results file instead of running M, provided `plugins/memory`
is the same in `main` and at the commit that file records (the control's code is unchanged); not paid again.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import os
import posixpath
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Required, TypedDict, Unpack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
import trial_env
from syntheses import document
from syntheses import units as synthesis_units
from synthesize import pipeline as sp
from synthesize import topics as synthesize_topics
from synthesize.pipeline import (
    CHEAP,
    DELETE_ONLY,
    NOT_GIVEN,
    changed_outside,
    cost_by_family,
    mem,
    parse_report,
    run_session,
    scope_text,
    split_parts,
    summary,
)
from synthesize.pipeline import (
    brief as _brief,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

logger = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
PLUGIN = trial_env.PLUGIN
SOURCE = trial_env.TARGET / "synthesis-source"
ATTACHED = trial_env.TARGET / "synthesis-source-attached.json"
TOPICS = ("human-memory", "time-series-forecasting", "llm-evaluation", "mental-health")
DEFAULT_TOPICS = TOPICS[:3]
ARMS = ("S", "L", "M", "R")
DEFAULT_ARMS = ("S", "L", "M")
WRITER = {
    "S": ("sonnet", None),
    "L": ("sonnet", None),
    "M": ("haiku", "high"),
    "R": ("haiku", "high"),
}  # model, effort
LEAN = ("L", "M", "R")
FROZEN = HERE / "frozen-main"  # only the judge's brief
MAIN_WORKTREE = trial_env.TARGET / "main-worktree"  # `main`'s own harness makes arm M's rows
CONTROL_TIMEOUT = 3 * 3600
# Budget: a cap, not a stop signal (constants: the rule is fixed before a run).
SESSION_CAP_USD = 1.5  # --max-budget-usd of every session this script starts
RESERVE = {"pipeline": 1.0, "judge": 0.3, "ref": 0.5, "calibration": 0.5}
RESERVE["control"] = (
    RESERVE["pipeline"] + RESERVE["judge"]
)  # main's harness: its pipeline and its own judge
PREPARED = trial_env.TARGET / "synthesis-source-prepared.json"  # what making the copy changed in it
# The proposed rule of R against M (owner fixes it before a run; constants, never options).
R_RATE_MARGIN = 2.0  # R's unsupported/100 <= M's + max(this, gap between M's runs), in points
R_COST_FACTOR = 1.3  # R's mean pipeline cost must stay below this times M's
PRELIM_MIN_RUNS = 2  # fewer runs per arm than this: preliminary
PRELIM_MAX_GAP = 4.0  # M's runs differing by more than this many points: preliminary
# Reference conditions of R (proposed; the owner fixes them before a run) and the calibration of the reference judge.
R_MIN_COVERAGE = 0.80  # covered findings / findings over all R rows
R_MAX_WRONG = 0.05  # wrong references / judged references over all R rows
R_MAX_SHOWN_GROWTH = 1.15  # R's mean tokens_shown / M's
REF_MAX_UNJUDGED = (
    0.10  # a reference report leaving more than this share of the units unjudged is unreliable
)
CALIBRATION_PLANTED = 20  # wrong references planted over the judged syntheses
CALIBRATION_MIN_FOUND = 16  # the judgment is valid when it marks this many of them `no` (scaled when fewer are plantable)
CALIBRATION_MIN_PLANTED = 10  # strong plants needed for a valid calibration
# Backfill trial.
BACKFILL_SAMPLE = 100  # new references sampled for the wrong count
BACKFILL_MAX_WRONG = 1  # wrong ones allowed in that sample
BACKFILL_MIN_COVERAGE = 0.60  # covered findings / findings after the backfill
BACKFILL_MAX_NONE = 0.20  # `none` answers / units sent
STATE = "state.json"
# Cell counts of a backfill table line (`U`: part, unit, kind; `P`: part, unit, label, verdict).
UNIT_CELLS = 3
PAIR_CELLS = 4
# Values the self-checks compare against, named so each check reads as the number it pins.
TWO, THREE, FOUR, FIVE, EIGHT, TEN = 2, 3, 4, 5, 8, 10
NINE_USD = 9.0
DENOMINATOR_MIN, DENOMINATOR_MAX = (
    6,
    12,
)  # units a prepared synthesis may have (the denominator of coverage)
COST_TOLERANCE = 1e-9  # the self-checks sum costs written with two decimals


def exactly(a: float, b: float) -> bool:
    """`a == b` for floats (no tolerance); written as `isclose` with both tolerances 0 for RUF069."""
    return math.isclose(a, b, rel_tol=0.0, abs_tol=0.0)


JUDGE_EXTRA = """
## Additional instruction for this check

Also mark each note cited in any `Sources:` line of the synthesis as `used` (a part of the synthesis states something
that comes from that note) or `unused` (cited, but nothing in the part rests on it). Write one line per cited note,
exactly `NOTE: <path> used` or `NOTE: <path> unused`, the path from the store root (e.g. `knowledge/<domain>/<file>.md`),
each note once, after the claim lines and before the `PARTS:` line. The very last line of the file is then exactly
`COUNTS: checked=<N> unsupported=<M> used=<A> unused=<B>` (integers; A and B count the NOTE lines).
"""

# --- fixture -------------------------------------------------------------------------------------------------


def real_store() -> Path:
    return trial_env._real_store()


def attached_handles(log: Path) -> set[str]:
    """The handles the curation `log` records as attached (none when it does not exist)."""
    attached: set[str] = set()
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("action") == "attach" and entry.get("handle"):
                attached.add(entry["handle"])
    return attached


def ensure_source() -> Path:
    """Copy the owner's default store once, read-only, without its history and curation log.

    The log is read, not copied: the handles it records as attached tell the notes that were attached to a synthesis
    from the ones a synthesis created itself (`--note-slug`)."""
    if (SOURCE / "mem-store.yaml").is_file() and ATTACHED.is_file() and PREPARED.is_file():
        return SOURCE
    real = real_store()
    if not (real / "mem-store.yaml").is_file():
        sys.exit(f"no store to copy at {real}")
    shutil.rmtree(SOURCE, ignore_errors=True)
    shutil.copytree(real, SOURCE, ignore=shutil.ignore_patterns(".git", ".curation-log*"))
    ATTACHED.write_text(json.dumps(sorted(attached_handles(real / ".curation-log"))))
    PREPARED.write_text(json.dumps({"refs_removed": drop_unlisted_references(SOURCE)}))
    return SOURCE


def drop_unlisted_references(store: Path) -> int:
    """Remove from the (trial) copy `store` every reference that names a note missing from its part's `Sources:` line,
    the case `document.validate_section` refuses; return how many were removed. Never run it on a real store."""
    base, total = store / document.SYNTHESES_DIR, 0
    for path in sorted(base.glob("*.md")):
        text, syn = path.read_text(), document.load_one(path)
        if syn.error:
            continue
        for part in syn.parts:
            line = document._sources_line(part.text) or ""
            listed = {
                document._resolved(base, t)
                for t in document._links(line)
                if synthesis_units._relative(t)
            }
            _, every, _, body_end = synthesis_units._parse(part.text)
            bad = [r for r in every if document._resolved(base, r.target) not in listed]
            if bad:
                new = synthesis_units._remove(part.text, 0, body_end, bad) + part.text[body_end:]
                text, total = document.apply_part_text(text, part.handle, new), total + len(bad)
        path.write_text(text)
    return total


def references_removed() -> int:
    """How many references `ensure_source` removed from the trial copy of the store."""
    return json.loads(PREPARED.read_text())["refs_removed"]


class Budget:
    """`--budget` as a cap: a step starts only when the cost so far, the reserve of the work in flight and this step's
    reserve fit under the total (checked and taken under one lock); `finish` swaps the reserve for the real cost."""

    def __init__(self, total: float, spent: float = 0.0):
        self.total, self.spent, self.reserved, self.lock = total, spent, 0.0, threading.Lock()

    def hold(self, amount: float) -> bool:
        with self.lock:
            if self.spent + self.reserved + amount > self.total + 1e-9:
                return False
            self.reserved += amount
            return True

    def settle(self, amount: float, cost: float) -> None:
        with self.lock:
            self.reserved -= amount
            self.spent += cost

    def start(self, kind: str) -> bool:
        return self.hold(RESERVE[kind])

    def finish(self, kind: str, cost: float) -> None:
        self.settle(RESERVE[kind], cost)


def started(budget: Budget | None, kind: str) -> bool:
    return budget is None or budget.start(kind)


def finished(budget: Budget | None, kind: str, cost: float) -> None:
    if budget is not None:
        budget.finish(kind, cost)


def assume_cap(sessions: list[dict]) -> list[dict]:
    """A session summary that reports no cost is counted at SESSION_CAP_USD, and says so in `cost_assumed`."""
    for s in sessions:
        if s["cost"] <= 0 and not s.get("cost_assumed"):
            s.update(cost=SESSION_CAP_USD, cost_assumed=True)
    return sessions


def capped_summary(s: dict) -> dict:
    return assume_cap([summary(s)])[0]


def row_cost(r: dict) -> float:
    """What a row cost over all sessions, main's own judge (arm M's control run) included."""
    return r["cost"] + r.get("control_judge_cost", 0.0)


def without_references_text(path: Path) -> str:
    """The synthesis file's text with the references of every part's body (Summary included) removed."""
    text = path.read_text(encoding="utf-8")
    for section in document.load_one(path).sections:
        text = document.apply_part_text(
            text, section.handle, synthesis_units.without_references(section.text)
        )
    return text


def tokens(text: str) -> float:
    return len(text) / 4


def brief(name: str, folder: Path | None = None, /, **values: str) -> str:
    """A brief from `folder`: by default the writer's is the trial's own (the command uses the `memory-synthesizer`
    agent instead) and the others are the engine's."""
    return _brief(name, folder or (HERE if name == "writer" else sp.BRIEFS), **values)


def front_part_of(text: str) -> str | None:
    head = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    found = re.search(r'^part_of: "?([^"\n]+)"?$', head.group(1), re.MULTILINE) if head else None
    return found.group(1) if found else None


def prepare_store(store: Path, env: dict, topic: str) -> list[str]:
    """Make the copy ready for a writer on `topic`; return the frozen denominator (knowledge notes of the topic)."""
    attached = set(json.loads(ATTACHED.read_text()))
    (store / "syntheses" / f"{topic}.md").unlink(missing_ok=True)
    for note in sorted((store / "knowledge").rglob("*.md")):
        rel = note.relative_to(store).as_posix()
        part = front_part_of(note.read_text())
        if part and part.startswith(f"{topic}#") and rel not in attached:
            note.unlink()  # a note the old synthesis created itself
    out = mem(store, env, "find", "--topic", topic)
    assert out.returncode == 0, out.stderr
    denominator = sorted(
        line.split("\t")[0] for line in out.stdout.splitlines() if line.startswith("knowledge/")
    )
    for rel in denominator:
        note = store / rel
        text = note.read_text()
        note.write_text(re.sub(r"^part_of(_hash)?: .*\n", "", text, flags=re.MULTILINE))
    return denominator


# --- pipeline ------------------------------------------------------------------------------------------------


def synthesis_facts(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    return len(text.split()), len(re.findall(r"^## (?!Summary$)", text, re.MULTILINE))


class JudgeSessionOptions(TypedDict):
    judge_model: str
    sessions: list[dict]


class JudgeRowOptions(TypedDict, total=False):
    arm: Required[str]
    run: Required[int]
    judge_model: Required[str]
    prior: Required[dict]
    judge: bool


def stored_facts(store: Path, env: dict, topic: str) -> dict:
    """What the stored synthesis `topic` says about itself: `mem check` exit, words, parts and the tokens stored and
    shown (all empty when there is no file)."""
    synthesis = store / "syntheses" / f"{topic}.md"
    if not synthesis.is_file():
        return {
            "mem_check": None,
            "words": 0,
            "parts": 0,
            "tokens_stored": None,
            "tokens_shown": None,
        }
    check_exit = mem(store, env, "check").returncode
    words, parts = synthesis_facts(synthesis)
    stored = synthesis.read_text()
    return {
        "mem_check": check_exit,
        "words": words,
        "parts": parts,
        "tokens_stored": tokens(stored),
        "tokens_shown": tokens(document.shown_file(stored)),
    }


def judge_stored_synthesis(
    claude: str, base: Path, env: dict, topic: str, **options: Unpack[JudgeSessionOptions]
) -> dict | None:
    """Run the judge on the synthesis in `base/store` and append its session to `options["sessions"]`; the parsed
    report (None when unreadable)."""
    store, work = base / "store", base / "work"
    synthesis = store / "syntheses" / f"{topic}.md"
    stored = synthesis.read_text()
    report = work / "judge-report.md"
    report.unlink(missing_ok=True)
    fill = {"TOPIC": topic, "SLUG": topic, "STORE": str(store), "WORK_DIR": str(work)}
    # The judge reads the file in place without its references (the same count for every arm and the baseline);
    # the stored text is put back afterwards, so a later step measures the run's own synthesis.
    synthesis.write_text(without_references_text(synthesis))
    try:
        s = run_session(
            claude,
            options["judge_model"],
            brief("checker", FROZEN, **fill, REPORT_FILE=str(report)) + JUDGE_EXTRA,
            work,
            base / "settings.json",
            env=env,
            log=base / f"{len(options['sessions']) + 1:02d}-judge.jsonl",
            effort=CHEAP,
            max_budget=SESSION_CAP_USD,
        )
    finally:
        synthesis.write_text(stored)
    s.update(role="judge", model=options["judge_model"], costs=cost_by_family(s["model_usage"]))
    options["sessions"].append(capped_summary(s))
    return parse_report(report)


def failure_reason(sessions: list[dict], why: str) -> str:
    """`why` completed with what the sessions show: a denied permission, a failed session, a model missing from the
    usage the session reported."""
    for s in sessions:
        if s["denied"]:
            return f"permission denied in {s['role']}"
    for s in sessions:
        if not s["ok"]:
            why = why or f"{s['role']} session failed"
        elif s["costs"].get(s["model"], 0.0) <= 0:
            why = why or f"{s['model']} missing from {s['role']} modelUsage"
    return why


def session_totals(sessions: list[dict]) -> dict:
    """The row's cost block: per-model costs, totals, the pipeline's share and the judge's, wall time, the sessions."""
    pooled: dict[str, float] = {}
    for s in sessions:
        for family, cost in s["costs"].items():
            pooled[family] = pooled.get(family, 0.0) + cost
    return {
        "costs": pooled,
        "cost": sum(s["cost"] for s in sessions),
        "cost_assumed": sum(bool(s.get("cost_assumed")) for s in sessions),
        "pipeline_cost": sum(s["cost"] for s in sessions if s["role"] != "judge"),
        "judge_cost": sum(s["cost"] for s in sessions if s["role"] == "judge"),
        "wall": sum(s["wall"] for s in sessions),
        "sessions": sessions,
    }


def judge_row(
    claude: str, base: Path, env: dict, topic: str, **options: Unpack[JudgeRowOptions]
) -> dict:
    """Judge the synthesis in `base/store` and build the row from the pipeline's `prior` facts (`judge=False`: the
    judge step is not started, the row has no count)."""
    prior = options["prior"]
    sessions, why = list(prior["sessions"]), prior["why"]
    facts = stored_facts(base / "store", env, topic)
    judged = None
    if facts["mem_check"] is not None and not options.get("judge", True):
        (base / "work" / "judge-report.md").unlink(missing_ok=True)
    elif facts["mem_check"] is not None:
        judged = judge_stored_synthesis(
            claude, base, env, topic, judge_model=options["judge_model"], sessions=sessions
        )
        if judged is None:
            why = why or "judge report unreadable"
    why = failure_reason(sessions, why)
    denominator = prior["denominator"]
    used = {rel for rel, state in (judged or {}).get("notes", {}).items() if state == "used"}
    arm_count = prior["arm_count"]
    return dict(
        topic=topic,
        arm=options["arm"],
        run=options["run"],
        valid=not why,
        why=why,
        denominator=len(denominator),
        checked=judged["checked"] if judged else 0,
        unsupported=judged["unsupported"] if judged else 0,
        words=facts["words"],
        parts=facts["parts"],
        tokens_stored=facts["tokens_stored"],
        tokens_shown=facts["tokens_shown"],
        used=len(used & set(denominator)),
        mem_check=facts["mem_check"],
        fix_rounds=prior["fixes"],
        arm_checked=arm_count["checked"] if arm_count else None,
        arm_unsupported=arm_count["unsupported"] if arm_count else None,
        deleted=prior.get("deleted", 0),
        scope_violations=prior.get("scope_violations", []),
        backfill=prior.get("backfill"),
        **session_totals(sessions),
    )


def lost_row(topic: str, arm: str, run: int, step: str) -> dict:
    """A row for a step the budget did not allow to start: no count, not valid for the decision."""
    prior = {"sessions": [], "why": "", "denominator": [], "arm_count": None, "fixes": 0}
    return mark_lost(
        judge_row(
            "",
            Path("/nonexistent"),
            {},
            topic,
            arm=arm,
            run=run,
            judge_model="",
            prior=prior,
            judge=False,
        ),
        [step],
    )


def mark_lost(row: dict, lost: list[str]) -> dict:
    """Record steps `not started: budget`; such a row is never valid for the decision."""
    if lost:
        text = f"not started: budget ({', '.join(lost)})"
        row.update(
            valid=False,
            why="; ".join(x for x in (row["why"], text) if x),
            budget_lost=row.get("budget_lost", []) + lost,
        )
    return row


class JudgeAndRefsOptions(TypedDict):
    arm: str
    run: int
    judge_model: str
    prior: dict
    ref_judge: bool
    quota: Quota | None
    budget: Budget | None


def judge_and_refs(
    claude: str, base: Path, env: dict, topic: str, **options: Unpack[JudgeAndRefsOptions]
) -> dict:
    """Judge (and, for arms M and R, judge the references of) the synthesis in `base/store`; a step the budget does not
    allow is recorded in the row's `budget_lost` and makes it invalid."""
    budget, judge_model, arm = options["budget"], options["judge_model"], options["arm"]
    judge_ok = started(budget, "judge")
    row = judge_row(
        claude,
        base,
        env,
        topic,
        arm=arm,
        run=options["run"],
        judge_model=judge_model,
        prior=options["prior"],
        judge=judge_ok,
    )
    lost = []
    if not judge_ok:
        lost.append("judge")
    else:
        finished(budget, "judge", row["judge_cost"])
        if options["ref_judge"] and (base / "store" / "syntheses" / f"{topic}.md").is_file():
            row["ref"], more, lost_refs = reference_run(
                claude,
                base,
                env,
                topic,
                judge_model=judge_model,
                quota=options["quota"] if arm == "R" else None,
                budget=budget,
            )
            add_sessions(row, more)
            lost += lost_refs
    return mark_lost(row, lost)


def load_synthesize() -> ModuleType:
    """`synthesize.topics`: the one implementation of the reference step (`add_references`, `ReferenceOptions`)."""
    return synthesize_topics


def reference_backfill(claude: str, base: Path, env: dict, topic: str) -> dict:
    """Run `mem-synthesize`'s reference step (`add_references`) on the synthesis in `base/store`; the facts for the row
    (`status` is `ok`, `nothing due` or the failure) and the cost. The done list is not touched."""
    settings = base / "settings-references.json"
    settings.write_text(json.dumps({"disableAllHooks": True}))
    start = time.monotonic()

    def log(text: str) -> None:
        with (base / "references-log.txt").open("a") as f:
            f.write(text + "\n")

    row = load_synthesize().add_references(
        claude,
        env,
        base / "references",
        base / "store",
        topic,
        settings=settings,
        log=log,
        budget_left=SESSION_CAP_USD,
    )
    if row is None:
        return {
            "status": "nothing due",
            "proposed": 0,
            "applied": 0,
            "refused": 0,
            "none": 0,
            "cost": 0.0,
            "wall": 0.0,
            "ran": False,
        }
    return {
        "status": row["status"],
        "proposed": row["proposed"],
        "applied": row["applied"],
        "refused": row["refused"],
        "none": row["none"],
        "cost": row["cost"],
        "wall": time.monotonic() - start,
        "ran": True,
    }


class PipelineOptions(TypedDict, total=False):
    arm: Required[str]
    run: Required[int]
    keep: Required[bool]
    judge_model: Required[str]
    ref_judge: bool
    quota: Quota | None
    budget: Budget | None


def prepare_pipeline_dir(base: Path, env: dict, topic: str) -> list[str]:
    """A fresh run folder `base`: the store copy prepared for `topic` (its frozen denominator is returned), the work
    folder as a git repository and the settings that point the memory plugin at the copy."""
    shutil.rmtree(base, ignore_errors=True)
    store, work = base / "store", base / "work"
    shutil.copytree(ensure_source(), store)
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    denominator = prepare_store(store, env, topic)
    (base / "settings.json").write_text(
        json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}})
    )
    return denominator


def writer_session(claude: str, base: Path, env: dict, topic: str, arm: str) -> dict:
    """The session of the arm's writer, summarized."""
    store, work = base / "store", base / "work"
    fill = {"TOPIC": topic, "SLUG": topic, "STORE": str(store), "WORK_DIR": str(work)}
    writer_model, writer_effort = WRITER[arm]
    s = run_session(
        claude,
        writer_model,
        brief("writer", HERE, SKILL_FILE=str(sp.SKILL), **fill),
        work,
        base / "settings.json",
        env=env,
        log=base / "01-writer.jsonl",
        effort=writer_effort,
        max_budget=SESSION_CAP_USD,
    )
    s.update(role="writer", model=writer_model, costs=cost_by_family(s["model_usage"]))
    return capped_summary(s)


def pipeline_sessions(
    claude: str, base: Path, env: dict, topic: str, arm: str
) -> tuple[list[dict], dict]:
    """The sessions of the writer and of the fix loop on its synthesis (lean for the lean arms) and the loop's result,
    or the result of a trial that wrote no synthesis."""
    sessions = [writer_session(claude, base, env, topic, arm)]
    if not (base / "store" / "syntheses" / f"{topic}.md").is_file():
        return sessions, {
            "arm_count": None,
            "why": "no synthesis written",
            "fixes": 0,
            "deleted": 0,
            "scope_violations": [],
        }
    done = sp.lean_loop(
        claude,
        env,
        base,
        base / "store",
        base / "work",
        settings=base / "settings.json",
        topic=topic,
        sessions=sessions,
        lean=arm in LEAN,
        left=lambda: SESSION_CAP_USD,
    )
    assume_cap(sessions)
    return sessions, done


def backfill_stage(claude: str, base: Path, env: dict, topic: str, sessions: list[dict]) -> dict:
    """The reference backfill of arm R, its session added to `sessions` when it ran; the backfill's facts."""
    refs = reference_backfill(claude, base, env, topic)
    if refs["ran"]:
        sessions.append({
            "role": "backfill",
            "model": "haiku",
            "costs": {"haiku": refs["cost"]},
            "cost": refs["cost"],
            "wall": refs["wall"],
            "writes": 0,
            "write_errors": 0,
            "denied": False,
            "tool_errors": 0,
            "ok": refs["status"] == "ok",
        })
        assume_cap(sessions)
    return refs


def one_pipeline(
    claude: str, root: Path, env: dict, topic: str, **options: Unpack[PipelineOptions]
) -> dict:
    arm, run, budget = options["arm"], options["run"], options.get("budget")
    assert arm != "M", "arm M is run by main's own harness (control_row)"
    if not started(budget, "pipeline"):
        return lost_row(topic, arm, run, "pipeline")
    base = root / "runs" / f"{topic}-{arm}-{run}"
    denominator = prepare_pipeline_dir(base, env, topic)
    sessions, done = pipeline_sessions(claude, base, env, topic, arm)
    refs = None
    if (
        arm == "R" and (base / "store" / "syntheses" / f"{topic}.md").is_file() and not done["why"]
    ):  # the last step, before every measurement
        refs = backfill_stage(claude, base, env, topic, sessions)
        if refs["status"] not in {"ok", "nothing due"}:
            done["why"] = f"reference backfill failed: {refs['status']}"
    finished(budget, "pipeline", sum(x["cost"] for x in sessions))
    prior = {
        "sessions": sessions,
        "why": done["why"],
        "denominator": denominator,
        "arm_count": done["arm_count"],
        "fixes": done["fixes"],
        "deleted": done["deleted"],
        "scope_violations": done["scope_violations"],
        "backfill": refs,
    }
    (base / "pipeline.json").write_text(
        json.dumps(prior)
    )  # what `--rejudge` needs besides the kept store
    row = judge_and_refs(
        claude,
        base,
        env,
        topic,
        arm=arm,
        run=run,
        judge_model=options["judge_model"],
        prior=prior,
        ref_judge=options.get("ref_judge", False),
        quota=options.get("quota"),
        budget=budget,
    )
    if not options["keep"]:
        shutil.rmtree(
            base / "store", ignore_errors=True
        )  # large; the row and the session streams keep the evidence
    return row


# --- arm M: main's own harness ---------------------------------------------------------------------------------


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or trial_env.REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def ensure_main_worktree(path: Path = MAIN_WORKTREE, run_git=git) -> dict:
    """The worktree of `main` that runs arm M: created when missing, reused only when its HEAD is `main`'s tip.
    Returns its path and `main`'s short commit."""
    tip = run_git("rev-parse", "main")
    if path.exists():
        head = run_git("rev-parse", "HEAD", cwd=path)
        if head != tip:
            raise RuntimeError(
                f"{path} is at {head[:7]}, `main` is at {tip[:7]}: remove it with "
                f"`git worktree remove --force {path}` and run again"
            )
    else:
        run_git("worktree", "add", "--detach", str(path), "main")
    return {"path": path, "commit": run_git("rev-parse", "--short", "main")}


def load_control_results(path: Path, run_git=git) -> dict:
    """The arm M rows of an earlier results file (`--control-results`), reused instead of a new control run.

    Reads `control_commit` (the `main` commit that produced them) and the rows with `arm == "M"`. Refused unless
    `plugins/memory` is the same at that commit and in `main` now: the control's code must be unchanged. Returns the
    rows (each marked `reused_from`), both commits and the file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    recorded = data.get("control_commit")
    if not recorded:
        raise RuntimeError(
            f"{path} records no control_commit: it has no arm M rows from `main`'s harness"
        )
    try:
        run_git("diff", "--quiet", recorded, "main", "--", "plugins/memory")
    except subprocess.CalledProcessError as exc:
        why = (
            "differs" if exc.returncode == 1 else f"cannot be compared (git exit {exc.returncode})"
        )
        raise RuntimeError(
            f"plugins/memory {why} between {recorded} (recorded in {path.name}) and `main`: the control's "
            f"code changed, so its rows cannot stand for it; run arm M again"
        ) from None
    rows = [dict(r, reused_from=str(path)) for r in data["rows"] if r["arm"] == "M"]
    if not rows:
        raise RuntimeError(f"{path} holds no arm M rows")
    return {
        "rows": rows,
        "recorded": recorded,
        "main": run_git("rev-parse", "--short", "main"),
        "file": str(path),
    }


def control_env() -> dict:
    """The environment of main's harness: the owner's own, because it reads the real store once (read-only) from
    `XDG_DATA_HOME` and then builds the isolated environment of its sessions itself (`trial_env.make_env`)."""
    return dict(os.environ)


def run_control(cmd: list[str], env: dict, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


_CONTROL_SOURCE = (
    threading.Lock()
)  # main's harness copies the real store once: two first runs must not copy together


def control_command(claude: str, control: dict, topic: str, work: Path) -> list[str]:
    return [
        "python3",
        str(control["path"] / "plugins" / "memory" / "evals" / "synthesis" / "run_trials.py"),
        "--arm",
        "M",
        "--topic",
        topic,
        "--runs",
        "1",
        "--keep",
        "--work",
        str(work),
        "--budget",
        f"{RESERVE['control']}",
        "--claude",
        claude,
    ]


class ControlRowOptions(TypedDict):
    run: int
    keep: bool
    judge_model: str
    ref_judge: bool
    budget: Budget | None
    control: dict


def run_control_pipeline(claude: str, control: dict, topic: str, work: Path) -> str:
    """Run `main`'s harness for one pipeline in `work`; what went wrong, or an empty string."""
    ready = (control["path"] / "target" / "mem-trials" / "synthesis-source-attached.json").is_file()
    try:
        with contextlib.nullcontext() if ready else _CONTROL_SOURCE:
            done = run_control(
                control_command(claude, control, topic, work), control_env(), CONTROL_TIMEOUT
            )
        (work / "control-output.txt").write_text(done.stdout + "\n--- stderr ---\n" + done.stderr)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"control run failed: {type(exc).__name__}"
    return f"control run exited {done.returncode}" if done.returncode else ""


def control_record(work: Path, topic: str) -> dict | None:
    """The control run's state record for its one pipeline, None when it left none."""
    state = work / STATE
    if not state.is_file():
        return None
    return next(
        (
            r
            for r in json.loads(state.read_text())
            if (r["topic"], r["arm"], r["run"]) == (topic, "M", 1)
        ),
        None,
    )


def control_prior(base: Path, record: dict | None, problem: str) -> dict:
    """The pipeline facts of the control run for `judge_row`: what it kept in `base`, or why it left nothing."""
    if record is None or not (base / "pipeline.json").is_file():
        return {
            "sessions": [],
            "why": problem or "control run left no result",
            "denominator": [],
            "arm_count": None,
            "fixes": 0,
        }
    prior = json.loads((base / "pipeline.json").read_text())
    prior["sessions"] = [
        x for x in prior["sessions"] if x["role"] != "judge"
    ]  # main's own judge stays out
    prior["why"] = prior["why"] or problem
    return prior


def control_row(
    claude: str, root: Path, env: dict, topic: str, **options: Unpack[ControlRowOptions]
) -> dict:
    """Arm M: `main`'s own harness runs the pipeline (and judges it with its own judge, a cost kept apart as
    `control_judge_cost`); this script takes the kept store and the pipeline cost, drops the references the copy of the
    real store carries, and judges as for every arm. Never `one_pipeline`."""
    budget, control = options["budget"], options["control"]
    if not started(budget, "control"):
        return lost_row(topic, "M", options["run"], "control pipeline")
    work = root / "control" / f"{topic}-M-{options['run']}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    problem = run_control_pipeline(claude, control, topic, work)
    record = control_record(work, topic)
    base = work / "runs" / f"{topic}-M-1"
    prior = control_prior(base, record, problem)
    finished(
        budget, "control", record["cost"] if record else RESERVE["control"]
    )  # unknown: counted at its reserve
    store = base / "store"
    if (store / "syntheses" / f"{topic}.md").is_file():
        drop_unlisted_references(
            store
        )  # main's copy of the real store was not prepared by this script
    row = judge_and_refs(
        claude,
        base,
        env,
        topic,
        arm="M",
        run=options["run"],
        judge_model=options["judge_model"],
        prior=prior,
        ref_judge=options["ref_judge"],
        quota=None,
        budget=budget,
    )
    if record is not None:
        row.update(pipeline_cost=record["pipeline_cost"], control_judge_cost=record["judge_cost"])
        row["cost"] = row["pipeline_cost"] + row["judge_cost"]
    row.update(control_commit=control["commit"])
    if not options["keep"]:
        shutil.rmtree(work, ignore_errors=True)
    return row


class OneRowOptions(TypedDict):
    arm: str
    run: int
    keep: bool
    judge_model: str
    ref_judge: bool
    quota: Quota | None
    budget: Budget | None
    control: dict | None


def one_row(
    claude: str, root: Path, env: dict, topic: str, **options: Unpack[OneRowOptions]
) -> dict:
    """One row of the trial: arm M comes from `main`'s own harness, every other arm from this script's pipeline."""
    arm, control = options["arm"], options["control"]
    if arm == "M":
        if control is None:
            raise ValueError("arm M needs the control run's description")
        return control_row(
            claude,
            root,
            env,
            topic,
            run=options["run"],
            keep=options["keep"],
            judge_model=options["judge_model"],
            ref_judge=options["ref_judge"],
            budget=options["budget"],
            control=control,
        )
    return one_pipeline(
        claude,
        root,
        env,
        topic,
        arm=arm,
        run=options["run"],
        keep=options["keep"],
        judge_model=options["judge_model"],
        ref_judge=options["ref_judge"] and arm == "R",
        quota=options["quota"],
        budget=options["budget"],
    )


def rejudge(claude: str, root: Path, env: dict, base: Path, judge_model: str) -> dict:
    """Judge the final synthesis of a kept pipeline folder again; the row is recorded as arm S, run 1."""
    base = base.resolve()
    topic = base.name.rsplit("-", 2)[0]
    prior = json.loads((base / "pipeline.json").read_text())
    assert (base / "store" / "syntheses" / f"{topic}.md").is_file(), (
        f"{base} keeps no store (use --keep)"
    )
    prior["sessions"] = [s for s in prior["sessions"] if s["role"] != "judge"]
    return judge_row(claude, base, env, topic, arm="S", run=1, judge_model=judge_model, prior=prior)


# --- reference judgment --------------------------------------------------------------------------------------

_REPORT_LINE = re.compile(
    r"^(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*)?`*\s*([UP]):(?:\*\*)?\s*(.*?)\s*`*(?:\*\*)?$"
)
_LOOSE_LINE = re.compile(r"\b[UP]:[^|\n]*\|")
_COUNTS_LINE = re.compile(r"^\W*COUNTS:\s*units=(\d+)\s+pairs=(\d+)\s+no=(\d+)\b", re.MULTILINE)


def _norm(target: str) -> str:
    return posixpath.normpath(target.strip().strip("`").strip())


def parse_ref_report(text: str) -> dict:
    """The reference judge's report: `units` ((part, number) -> finding|other), `pairs` ((part, number, path) -> True
    for yes), `unreadable` (lines that hold `U:` or `P:` and a `|` and do not parse) and `counts_ok` (the report's
    `COUNTS` line agrees with the lines parsed; a missing one disagrees). Tolerates a bullet or a list number, bold
    markers, backticks and white space around a line; the last of two lines for the same key wins."""
    units: dict[tuple[str, int], str] = {}
    pairs: dict[tuple[str, int, str], bool] = {}
    unreadable = u_lines = p_lines = no_lines = 0
    for raw in text.splitlines():
        m = _REPORT_LINE.match(raw.strip())
        if not m:
            unreadable += bool(_LOOSE_LINE.search(raw))
            continue
        kind, rest = m.groups()
        cells = [c.strip().strip("`*").strip() for c in rest.split("|")]
        if len(cells) < UNIT_CELLS or not cells[1].isdigit():
            unreadable += 1
            continue
        key = (cells[0].split("#")[-1].strip(), int(cells[1]))
        if kind == "U" and len(cells) == UNIT_CELLS and cells[2].lower() in {"finding", "other"}:
            units[key] = cells[2].lower()
            u_lines += 1
        elif kind == "P" and len(cells) == PAIR_CELLS and cells[3].lower() in {"yes", "no"}:
            pairs[*key, _norm(cells[2])] = cells[3].lower() == "yes"
            p_lines += 1
            no_lines += cells[3].lower() == "no"
        else:
            unreadable += 1
    counts = _COUNTS_LINE.findall(text)
    counts_ok = bool(counts) and tuple(int(x) for x in counts[-1]) == (u_lines, p_lines, no_lines)
    return {"units": units, "pairs": pairs, "unreadable": unreadable, "counts_ok": counts_ok}


def file_units(path: Path) -> list[tuple[str, int, list[str]]]:
    """(part handle, unit number, normalized reference targets without repeats) for every unit of the file's parts."""
    out = []
    for section in document.load_one(path).parts:
        found, _ = synthesis_units.units(section.text)
        out += [(section.handle, u.n, [_norm(t) for t in dict.fromkeys(u.refs)]) for u in found]
    return out


def unreliable_report(
    parsed: dict | None, session_ok: bool, counts_ok: bool, unjudged: int, units: int
) -> bool:
    """A reference report that cannot be trusted: none, a failed session, `COUNTS` that disagree or too many units and
    pairs without a line."""
    return parsed is None or not session_ok or not counts_ok or unjudged > REF_MAX_UNJUDGED * units


def score_refs(
    path: Path,
    parsed: dict | None,
    session_ok: bool = True,
    had_ref: set[tuple[str, int]] | None = None,
) -> tuple[dict, dict]:
    """Facts of one reference report against the stored file, by code: `findings`, `covered` (findings whose unit
    carries a reference), `pairs` and `wrong` (judged references, those marked `no`) as the report states them (best
    case), `unjudged_units` and `unjudged_pairs` (no line), the worst case in which every unjudged unit is a finding
    without a reference (`findings_worst`) and every unjudged pair is wrong (`pairs_worst`, `wrong_worst`), and
    `unreliable`. With `had_ref` (the units that carried a reference before a backfill), the same findings and coverage
    over the units that had none (`findings_new`, `covered_new`, `findings_new_worst`). Also the verdict of each judged
    pair, (part, number, path) -> True for yes."""
    expected = file_units(path)
    findings = covered = pairs = wrong = unjudged_units = unjudged_pairs = 0
    findings_new = covered_new = unjudged_new = 0
    verdicts: dict[tuple[str, int, str], bool] = {}
    for handle, n, refs in expected:
        kind = parsed["units"].get((handle, n)) if parsed else None
        fresh = had_ref is not None and (handle, n) not in had_ref
        if kind is None:
            unjudged_units += 1
            unjudged_new += fresh
        elif kind == "finding":
            findings += 1
            covered += bool(refs)
            findings_new += fresh
            covered_new += fresh and bool(refs)
        for target in refs:
            verdict = parsed["pairs"].get((handle, n, target)) if parsed else None
            if verdict is None:
                unjudged_pairs += 1
            else:
                pairs += 1
                wrong += not verdict
                verdicts[handle, n, target] = verdict
    counts_ok = bool(parsed) and parsed.get("counts_ok", True)
    return (
        {
            "units": len(expected),
            "findings": findings,
            "covered": covered,
            "pairs": pairs,
            "wrong": wrong,
            "unjudged": unjudged_units + unjudged_pairs,
            "unjudged_units": unjudged_units,
            "unjudged_pairs": unjudged_pairs,
            "findings_worst": findings + unjudged_units,
            "pairs_worst": pairs + unjudged_pairs,
            "wrong_worst": wrong + unjudged_pairs,
            "findings_new": findings_new,
            "covered_new": covered_new,
            "findings_new_worst": findings_new + unjudged_new,
            "unreadable": parsed["unreadable"] if parsed else 0,
            "counts_ok": counts_ok,
            "unreliable": unreliable_report(
                parsed, session_ok, counts_ok, unjudged_units + unjudged_pairs, len(expected)
            ),
            "cal": None,
        },
        verdicts,
    )


@dataclass(frozen=True)
class PlantScope:
    """What one part gives the search for references to swap: the synthesis folder, the part's handle, its own `Sources:`
    notes (`mine`), the notes only other parts cite (`elsewhere`) and the judge's verdicts."""

    base: Path
    handle: str
    mine: dict[Path, tuple[str, str]]
    elsewhere: dict[Path, tuple[str, str]]
    verdicts: dict


def part_sources(base: Path, parts: list) -> dict[str, dict[Path, tuple[str, str]]]:
    """For each part handle, the notes its `Sources:` line cites: resolved path -> (label, target)."""
    sources: dict[str, dict[Path, tuple[str, str]]] = {}
    for section in parts:
        sources[section.handle] = mine = {}
        for m in synthesis_units._REF_LINK.finditer(document._sources_line(section.text) or ""):
            if synthesis_units._is_ref(m.group(2)):
                mine.setdefault(document._resolved(base, m.group(2)), (m.group(1), m.group(2)))
    return sources


def cited_elsewhere(handle: str, sources: dict) -> dict[Path, tuple[str, str]]:
    """The notes that parts other than `handle` cite and `handle` does not."""
    mine = sources[handle]
    elsewhere: dict[Path, tuple[str, str]] = {}
    for other, theirs in sources.items():
        if other != handle:
            elsewhere.update({k: v for k, v in theirs.items() if k not in mine})
    return elsewhere


def unit_candidate(scope: PlantScope, n: int, own: list) -> tuple[bool, tuple] | None:
    """The swap a unit allows, or None: (strong, (part handle, unit number, references the judge marked yes,
    replacements)). `own` holds the unit's references; a strong swap needs a note only other parts cite, a weak one a
    source of this part that the unit does not carry."""
    carried = {document._resolved(scope.base, r.target) for r in own}
    ok = [
        r
        for r in own
        if r.trailing
        and scope.verdicts.get((scope.handle, n, _norm(synthesis_units._file_part(r.target))))
        is True
    ]
    if not ok:
        return None
    far = [v for k, v in scope.elsewhere.items() if k not in carried]
    if far:
        return True, (scope.handle, n, ok, far)
    near = [v for k, v in scope.mine.items() if k not in carried]
    return (False, (scope.handle, n, ok, near)) if near else None


def part_candidates(scope: PlantScope, text: str, kinds: dict) -> tuple[list, list]:
    """The strong and the weak swap candidates of one part's `text`, over the units the judge marked `finding`."""
    found, refs, orphans, _ = synthesis_units._parse(text)
    orphan_at = {r.start for r in orphans}
    strong, weak = [], []
    for unit in found:
        if kinds.get((scope.handle, unit.n)) != "finding":
            continue
        own = [
            r for r in refs if unit.span[0] <= r.start < unit.span[1] and r.start not in orphan_at
        ]
        picked = unit_candidate(scope, unit.n, own)
        if picked is not None:
            (strong if picked[0] else weak).append(picked[1])
    return strong, weak


def choose_swaps(
    strong: list, weak: list, quota: int, rng: random.Random
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]], dict]:
    """The units to swap (strong ones first, weak ones fill the rest of `quota`), the planted pairs of each kind and the
    edits by part handle: (start, end, new link). One swap per unit."""
    chosen = rng.sample(strong, min(quota, len(strong)))
    chosen_weak = rng.sample(weak, min(max(0, quota - len(chosen)), len(weak)))
    planted, planted_weak, edits = [], [], {}
    for group, out in ((chosen, planted), (chosen_weak, planted_weak)):
        for handle, n, ok, other in group:
            ref, (label, target) = rng.choice(ok), rng.choice(other)
            edits.setdefault(handle, []).append((ref.start, ref.end, f"[{label}]({target})"))
            out.append((handle, n, _norm(synthesis_units._file_part(target))))
    return planted, planted_weak, edits


def plant_references(
    path: Path, verdicts: dict, quota: int, rng: random.Random, kinds: dict
) -> tuple[str, list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """The file's text with up to `quota` references swapped for a wrong one, and the planted pairs (part, number, path):
    the strong ones, then the weak ones.

    A candidate is a trailing reference the judge marked `yes`, on a unit it marked `finding` (`kinds`). A strong plant
    replaces it with a note that is a source of another part of the same synthesis and not a source of this part, so it
    is about another subject. Only a unit with no such note gets a weak plant: another source of the same part that
    the unit did not carry (it may support the sentence too). Weak plants fill what the strong ones leave of `quota`.
    One swap per unit; the label and target of the reference become the replacements'."""
    base, text = path.parent, path.read_text(encoding="utf-8")
    parts = document.load_one(path).parts
    sources = part_sources(base, parts)
    strong, weak = [], []
    for section in parts:
        scope = PlantScope(
            base,
            section.handle,
            sources[section.handle],
            cited_elsewhere(section.handle, sources),
            verdicts,
        )
        part_strong, part_weak = part_candidates(scope, section.text, kinds)
        strong += part_strong
        weak += part_weak
    planted, planted_weak, edits = choose_swaps(strong, weak, quota, rng)
    for section in parts:
        if section.handle in edits:
            new = section.text
            for start, end, repl in sorted(edits[section.handle], reverse=True):
                new = new[:start] + repl + new[end:]
            text = document.apply_part_text(text, section.handle, new)
    return text, planted, planted_weak


class Quota:
    """The planted references still to place, shared out over the syntheses as evenly as they allow: each one takes its
    share of what is left and gives back what it could not plant."""

    def __init__(self, total: int, syntheses_left: int):
        self.left, self.rows, self.lock = total, syntheses_left, threading.Lock()

    def take(self) -> int:
        with self.lock:
            share = -(-self.left // max(1, self.rows))
            self.rows -= 1
            return share

    def spent(self, planted: int) -> None:
        with self.lock:
            self.left -= planted


def calibration_min(planted: int) -> int:
    """Planted references the judge must find: CALIBRATION_MIN_FOUND of CALIBRATION_PLANTED, scaled (rounded up)."""
    return -(-CALIBRATION_MIN_FOUND * planted // CALIBRATION_PLANTED)


def calibration_valid(planted: int, found: int) -> bool:
    """Valid with at least CALIBRATION_MIN_PLANTED strong plants, of which the scaled threshold was found."""
    return planted >= CALIBRATION_MIN_PLANTED and found >= calibration_min(planted)


class RefSessionOptions(TypedDict):
    judge_model: str
    role: str


def ref_session(
    claude: str, base: Path, env: dict, handle: str, **options: Unpack[RefSessionOptions]
) -> tuple[dict | None, dict]:
    """One reference-judge session on `base/store`'s synthesis `handle`, as the file stands now; the parsed report
    (None when unreadable) and the session's summary."""
    store, work, role = base / "store", base / "work", options["role"]
    synthesis = store / "syntheses" / f"{handle}.md"
    units, report = work / f"{role}-units-{handle}.md", work / f"{role}-report-{handle}.md"
    report.unlink(missing_ok=True)
    sp.write_units(synthesis, units)
    prompt = brief(
        "ref-judge",
        HERE,
        SLUG=handle,
        STORE=str(store),
        UNITS_FILE=str(units),
        REPORT_FILE=str(report),
    )
    s = run_session(
        claude,
        options["judge_model"],
        prompt,
        work,
        base / "settings.json",
        env=env,
        log=base / f"{role}-{handle}.jsonl",
        effort=CHEAP,
        max_budget=SESSION_CAP_USD,
    )
    s.update(role=role, model=options["judge_model"], costs=cost_by_family(s["model_usage"]))
    parsed = parse_ref_report(report.read_text()) if report.is_file() else None
    if parsed is not None and not parsed["units"] and not parsed["pairs"]:
        parsed = None
    return parsed, capped_summary(s)


class CalibrateOptions(TypedDict):
    judge_model: str
    verdicts: dict
    quota: int
    kinds: dict


def calibrate(
    claude: str, base: Path, env: dict, handle: str, **options: Unpack[CalibrateOptions]
) -> tuple[dict, list[dict]]:
    """Plant up to `quota` strong wrong references (and weak ones, counted apart) in the synthesis `handle` for one
    reference-judge session, put the stored bytes back in a `finally`, and count the planted pairs the judge marks
    `no`. The planted text is read only by that session."""
    synthesis = base / "store" / "syntheses" / f"{handle}.md"
    stored = synthesis.read_bytes()
    text, strong, weak = plant_references(
        synthesis, options["verdicts"], options["quota"], random.Random(0), options["kinds"]
    )
    if not strong and not weak:
        return {"planted": 0, "found": 0, "weak_planted": 0, "weak_found": 0}, []
    synthesis.write_text(text)
    try:
        parsed, s = ref_session(
            claude, base, env, handle, judge_model=options["judge_model"], role="ref-calibration"
        )
    finally:
        synthesis.write_bytes(stored)

    def marked(keys):
        return sum(1 for key in keys if parsed is not None and parsed["pairs"].get(key) is False)

    return {
        "planted": len(strong),
        "found": marked(strong),
        "weak_planted": len(weak),
        "weak_found": marked(weak),
    }, [s]


class ReferenceRunOptions(TypedDict, total=False):
    judge_model: Required[str]
    quota: Required[Quota | None]
    budget: Budget | None


def reference_run(
    claude: str, base: Path, env: dict, handle: str, **options: Unpack[ReferenceRunOptions]
) -> tuple[dict | None, list[dict], list[str]]:
    """The reference judgment of the synthesis `handle` in `base/store` (its row's `ref`, None when the budget did not
    allow it), the sessions it started and the steps the budget did not allow; with a `quota`, also the calibration."""
    synthesis = base / "store" / "syntheses" / f"{handle}.md"
    budget, quota, judge_model = options.get("budget"), options["quota"], options["judge_model"]
    if not started(budget, "ref"):
        return None, [], ["reference judgment"]
    parsed, s = ref_session(claude, base, env, handle, judge_model=judge_model, role="ref-judge")
    finished(budget, "ref", s["cost"])
    ref, verdicts = score_refs(synthesis, parsed, s["ok"])
    sessions, lost = [s], []
    if quota is not None:
        share = quota.take()
        if started(budget, "calibration"):
            cal, more = calibrate(
                claude,
                base,
                env,
                handle,
                judge_model=judge_model,
                verdicts=verdicts,
                quota=share,
                kinds=parsed["units"] if parsed else {},
            )
            finished(budget, "calibration", sum(x["cost"] for x in more))
            quota.spent(cal["planted"])
            ref["cal"], sessions = cal, sessions + more
        else:
            quota.spent(0)
            lost.append("calibration")
    return ref, sessions, lost


def add_sessions(row: dict, sessions: list[dict]) -> None:
    """Fold the reference sessions into the row's judge cost (never the pipeline's), wall time and per-model costs."""
    row["sessions"] += sessions
    for s in sessions:
        row["cost"] += s["cost"]
        row["cost_assumed"] = row.get("cost_assumed", 0) + bool(s.get("cost_assumed"))
        row["judge_cost"] += s["cost"]
        row["wall"] += s["wall"]
        for family, cost in s["costs"].items():
            row["costs"][family] = row["costs"].get(family, 0.0) + cost


# --- report --------------------------------------------------------------------------------------------------


def rate(r: dict) -> float:
    return 100.0 * r["unsupported"] / r["checked"] if r["checked"] else float("nan")


def coverage(r: dict) -> float:
    return 100.0 * r["used"] / r["denominator"] if r["denominator"] else float("nan")


HEADER = (
    f"{'topic':24} {'arm':3} {'run':3} {'valid':5} {'unsup/100':9} {'checked':7} {'words':5} {'parts':5} "
    f"{'tok file':8} {'tok shown':9} {'cover':9} {'check':5} {'arm vs judge':14} {'fix':3} {'del':3} {'pipe USD':8} {'judge USD':9} {'wall s':6} "
    f"{'unlisted parts changed'}"
)


def fmt_tokens(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def table_line(r: dict) -> str:
    arm = (
        "-"
        if r["arm_checked"] is None
        else f"{r['arm_unsupported']}/{r['arm_checked']} v {r['unsupported']}/{r['checked']}"
    )
    return (
        f"{r['topic']:24} {r['arm']:3} {r['run']:<3} {r['valid']!s:5} {rate(r):9.1f} {r['checked']:<7} "
        f"{r['words']:<5} {r['parts']:<5} {fmt_tokens(r.get('tokens_stored')):8} {fmt_tokens(r.get('tokens_shown')):9} {r['used']}/{r['denominator']:<7} {r['mem_check']!s:5} {arm:14} "
        f"{r['fix_rounds']:<3} {r['deleted']:<3} {r['pipeline_cost']:<8.3f} {r['judge_cost']:<9.3f} {r['wall']:<6.0f} "
        f"{','.join(r['scope_violations']) or 'none'} {r['why']}"
    )


def pooled(rows: list[dict]) -> dict:
    checked = sum(r["checked"] for r in rows)
    return {
        "n": len(rows),
        "rate": 100.0 * sum(r["unsupported"] for r in rows) / checked if checked else float("nan"),
        "checked": statistics.mean(r["checked"] for r in rows),
        "words": statistics.mean(r["words"] for r in rows),
        "cover": statistics.mean(coverage(r) for r in rows),
        "tok_stored": statistics.mean(r.get("tokens_stored") or 0 for r in rows),
        "tok_shown": statistics.mean(r.get("tokens_shown") or 0 for r in rows),
        "cost": statistics.mean(r["pipeline_cost"] for r in rows),
        "judge": statistics.mean(r["judge_cost"] for r in rows),
        "mem_ok": all(r["mem_check"] == 0 for r in rows),
    }


def spread(rows: list[dict]) -> float:
    """Mean over topics of the gap between an arm's runs on one topic, in points of unsupported rate."""
    gaps = []
    for topic in {r["topic"] for r in rows}:
        rates = [rate(r) for r in rows if r["topic"] == topic]
        if len(rates) > 1:
            gaps.append(max(rates) - min(rates))
    return statistics.mean(gaps) if gaps else 0.0


def run_gap(rows: list[dict]) -> float:
    """The absolute gap between an arm's runs: each run's rate pooled over its topics, largest minus smallest (0 with one run)."""
    rates = [
        pooled([r for r in rows if r["run"] == n])["rate"] for n in sorted({r["run"] for r in rows})
    ]
    return max(rates) - min(rates) if len(rates) > 1 else 0.0


def ref_totals(rows: list[dict]) -> dict:
    """Reference counts summed over the rows that have a reference judgment: as the reports state them and in the worst
    case (`*_worst`: every unjudged unit a finding without a reference, every unjudged pair wrong)."""
    judged = [r["ref"] for r in rows if r.get("ref")]
    cals = [c for c in (x["cal"] for x in judged) if c]
    keys = ("findings", "covered", "pairs", "wrong", "findings_worst", "pairs_worst", "wrong_worst")
    return dict(
        rows=len(judged),
        **{k: sum(x[k] for x in judged) for k in keys},
        unreliable=sum(bool(x["unreliable"]) for x in judged),
        planted=sum(c["planted"] for c in cals),
        found=sum(c["found"] for c in cals),
        weak_planted=sum(c.get("weak_planted", 0) for c in cals),
        weak_found=sum(c.get("weak_found", 0) for c in cals),
    )


def reference_conditions(r_rows: list[dict], m_rows: list[dict]) -> list[tuple[str, bool]]:
    """Conditions of R on references (none when the rows carry no reference judgment): coverage of findings and wrong
    references, each decided on the worst case (best case printed), and the size a reader gets (tokens shown) against M's."""
    t = ref_totals(r_rows)
    if not t["rows"]:
        return []
    cov_worst = t["covered"] / t["findings_worst"] if t["findings_worst"] else 0.0
    cov_best = t["covered"] / t["findings"] if t["findings"] else 0.0
    wrong_worst = t["wrong_worst"] / t["pairs_worst"] if t["pairs_worst"] else 1.0
    wrong_best = t["wrong"] / t["pairs"] if t["pairs"] else 1.0
    shown_r = statistics.mean(r.get("tokens_shown") or 0 for r in r_rows)
    shown_m = statistics.mean(r.get("tokens_shown") or 0 for r in m_rows)
    grew = not shown_m or shown_r > R_MAX_SHOWN_GROWTH * shown_m
    return [
        (
            (
                f"reference coverage, worst case {cov_worst:.2f} ({t['covered']}/{t['findings_worst']}) >= {R_MIN_COVERAGE} "
                f"(best case {cov_best:.2f}, {t['covered']}/{t['findings']})"
            ),
            t["findings_worst"] > 0 and cov_worst >= R_MIN_COVERAGE,
        ),
        (
            (
                f"wrong references, worst case {wrong_worst:.3f} ({t['wrong_worst']}/{t['pairs_worst']}) <= {R_MAX_WRONG} "
                f"(best case {wrong_best:.3f}, {t['wrong']}/{t['pairs']})"
            ),
            t["pairs_worst"] > 0 and wrong_worst <= R_MAX_WRONG,
        ),
        (
            f"tokens shown {shown_r:.0f} <= {R_MAX_SHOWN_GROWTH} x M's {shown_m:.0f} = {R_MAX_SHOWN_GROWTH * shown_m:.0f}"
            + (" (do not adopt: shorten what `mem show` prints first)" if grew else ""),
            not grew,
        ),
    ]


def reference_notes(r_rows: list[dict]) -> tuple[list[str], list[str]]:
    """The calibration line of R's reference judgment, and the reasons it makes the result preliminary."""
    t = ref_totals(r_rows)
    if not t["rows"]:
        return [], []
    need, valid = calibration_min(t["planted"]), calibration_valid(t["planted"], t["found"])
    line = (
        f"  reference judge calibration: {t['found']} of {t['planted']} strong planted wrong references found "
        f"(needs {need}, and at least {CALIBRATION_MIN_PLANTED} planted): {'valid' if valid else 'NOT valid'}; "
        f"weak plants (another source of the same part, not counted): {t['weak_found']} of {t['weak_planted']} found"
    )
    notes = []
    if not valid:
        notes.append("the reference judge's calibration is not valid")
    elif t["planted"] < CALIBRATION_PLANTED:
        notes.append(
            f"only {t['planted']} wrong references could be planted (threshold scaled to {need})"
        )
    if t["unreliable"]:
        notes.append(
            f"{t['unreliable']} of {t['rows']} reference reports are unreliable (over {REF_MAX_UNJUDGED:.0%} of "
            f"the units unjudged, or the report's COUNTS line disagrees with its lines)"
        )
    return [line], notes


def r_against_m_checks(by: dict, stats: dict, gap: float) -> list[tuple[str, bool]]:
    """The conditions of R against M, each with its printed text and whether it holds."""
    r, m = stats["R"], stats["M"]
    margin = max(R_RATE_MARGIN, gap)
    clean = sum(x["mem_check"] == 0 for x in by["R"])
    checks = [
        (
            (
                f"unsupported {r['rate']:.1f} <= M's {m['rate']:.1f} + max({R_RATE_MARGIN}, run gap {gap:.1f}) = "
                f"{m['rate'] + margin:.1f}"
            ),
            r["rate"] <= m["rate"] + margin,
        ),
        (
            f"pipeline cost {r['cost']:.3f} < {R_COST_FACTOR} x M's {m['cost']:.3f} = {R_COST_FACTOR * m['cost']:.3f}",
            r["cost"] < R_COST_FACTOR * m["cost"],
        ),
        (f"every R synthesis passes mem check ({clean}/{len(by['R'])})", clean == len(by["R"])),
    ]
    return checks + reference_conditions(by["R"], by["M"])


def preliminary_notes(by: dict, gap: float, lost: int) -> list[str]:
    """What makes a verdict of R against M preliminary: too few runs, runs of M that differ, rows lost to the budget."""
    runs = {a: len({x["run"] for x in by[a]}) for a in ("R", "M")}
    notes = []
    if min(runs.values()) < PRELIM_MIN_RUNS:
        notes.append(f"fewer than {PRELIM_MIN_RUNS} runs per arm (R {runs['R']}, M {runs['M']})")
    if gap > PRELIM_MAX_GAP:
        notes.append(f"M's runs differ by {gap:.1f} points (> {PRELIM_MAX_GAP})")
    if lost:
        notes.append(f"{lost} rows were lost to the budget")
    return notes


def decide_r_against_m(by: dict, stats: dict, lost: int = 0) -> list[str]:
    """The proposed rule of R against M, on the valid pipelines pooled over topics and runs."""
    if not by["R"] or not by["M"]:
        return ["R against M: not applicable, R or M has no valid pipeline."]
    gap = run_gap(by["M"])
    checks = r_against_m_checks(by, stats, gap)
    ref_lines, notes = reference_notes(by["R"])
    notes += preliminary_notes(by, gap, lost)
    lines = [
        f"  R against M: {text}: {'passed' if ok else 'FAILED'}" for text, ok in checks
    ] + ref_lines
    if notes:
        lines.append("preliminary: " + "; ".join(notes))
    if ref_totals(by["R"])["rows"] < len(
        by["R"]
    ):  # a verdict without the reference judgment is never PASS
        return [*lines, "Verdict R against M: PRELIMINARY: reference judgment not run"]
    ok = all(ok for _, ok in checks)
    return [
        *lines,
        f"Verdict R against M: {'PASS' if ok else 'FAIL'}" + (" (preliminary)" if notes else ""),
    ]


def decide(rows: list[dict]) -> list[str]:
    """The plan's decision rule (2026-11-17, prompts and loop) among S, L and M, then R against M."""
    by = {a: [r for r in rows if r["arm"] == a and r["valid"]] for a in ARMS}
    lost = sum(bool(r.get("budget_lost")) for r in rows)
    lines, stats = (
        [f"rows lost to the budget (a step was not started, not valid for the decision): {lost}"],
        {},
    )
    for arm, rs in by.items():
        if not rs:
            continue
        stats[arm] = p = pooled(rs)
        lines.append(
            f"{arm} valid={p['n']} unsupported/100={p['rate']:.1f} claims checked={p['checked']:.0f} "
            f"words={p['words']:.0f} tokens file={p['tok_stored']:.0f} shown={p['tok_shown']:.0f} "
            f"coverage={p['cover']:.0f}% mem check all 0={p['mem_ok']} "
            f"pipeline cost={p['cost']:.3f} (judge {p['judge']:.3f}) run gap={spread(rs):.1f} points"
        )
        if (t := ref_totals(rs))["rows"]:
            lines.append(
                f"  {arm} references: coverage {t['covered']}/{t['findings']} findings (worst case "
                f"{t['covered']}/{t['findings_worst']}), wrong {t['wrong']}/{t['pairs']} (worst case "
                f"{t['wrong_worst']}/{t['pairs_worst']}), {t['unreliable']} unreliable reports"
            )
    if by["R"]:
        lines += decide_r_against_m(by, stats, lost)
    if "S" in stats or not by["R"]:
        lines += decide_s(by, stats)
    return lines


def decide_s(by: dict, stats: dict) -> list[str]:
    """Among L and M, the cheapest arm that qualifies against S."""
    lines = []
    challengers = [a for a in ("L", "M") if a in stats]
    if "S" not in stats or not challengers:
        return ["Decision rule: not applicable, S or both lean arms have no valid pipeline."]
    s, qualifying = stats["S"], {}
    for arm in challengers:
        h = stats[arm]
        checks = {
            f"unsupported {h['rate']:.1f} <= {s['rate']:.1f}+2": h["rate"] <= s["rate"] + 2,
            f"claims {h['checked']:.0f} >= 80% of {s['checked']:.0f}": h["checked"]
            >= 0.8 * s["checked"],
            f"coverage {h['cover']:.0f} >= {s['cover']:.0f}-10": h["cover"] >= s["cover"] - 10,
            f"every {arm} synthesis passes mem check": h["mem_ok"],
            f"pipeline cost (judge excluded) {h['cost']:.3f} <= 80% of {s['cost']:.3f}": h["cost"]
            <= 0.8 * s["cost"],
        }
        lines += [f"  {arm}: {text}: {ok}" for text, ok in checks.items()]
        if all(checks.values()):
            qualifying[arm] = h["cost"]
    if (
        max(len([r for r in by[a] if r["topic"] == t]) for a in ("S", *challengers) for t in TOPICS)
        <= 1
    ):
        lines.append("preliminary (1 run per topic): the variance rule cannot apply")
    if qualifying:
        best = min(qualifying, key=lambda a: qualifying[a])
        return [*lines, f"Verdict: ADOPT arm {best} (cheapest that qualifies)"]
    return [*lines, "Verdict: KEEP today's pipeline (arm S) and record the gaps"]


# --- backfill trial ------------------------------------------------------------------------------------------


def parse_backfill_table(text: str) -> tuple[list[dict], dict | None]:
    """The table `mem-synthesize --backfill` prints: (a dict per synthesis row, the `total` row or None), keyed by the
    header's column names, never by position. Cells are cut at the columns' starting offsets in the header, because a
    blank cell (the total row has some) leaves no field to split on."""
    lines = text.splitlines()
    head = next(
        (i for i, ln in enumerate(lines) if ln.startswith("synthesis") and "parts" in ln), None
    )
    if head is None:
        return [], None
    names = re.split(r"\s{2,}", lines[head].strip())
    starts, at = [], 0
    for name in names:
        at = lines[head].index(name, at)
        starts.append(at)
        at += len(name)
    ends = [*starts[1:], None]
    rows, total = [], None
    for line in lines[head + 1 :]:
        if not line.strip() or line.startswith("total cost"):
            break
        row = {n: line[a:b].strip() for n, a, b in zip(names, starts, ends, strict=False)}
        if row[names[0]] == "total":
            total = row
        else:
            rows.append(row)
    return rows, total


def number(value: str | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def behind_count(store: Path, env: dict) -> int:
    """How many notes `mem curate --notes` lists as older than their section."""
    inside, count = False, 0
    for line in mem(store, env, "curate", "--notes").stdout.splitlines():
        if line and not line.startswith(" "):
            inside = line.startswith("notes older than their section")
        elif inside and line.strip():
            count += 1
    return count


def snapshot_files(store: Path, handle: str) -> dict[str, bytes]:
    """The bytes of the synthesis file and of the notes that are members of its parts, by path in the store."""
    out = {f"syntheses/{handle}.md": (store / "syntheses" / f"{handle}.md").read_bytes()}
    for note in sorted(store.rglob("*.md")):
        rel = note.relative_to(store)
        if rel.parts[0] != "syntheses" and not any(p.startswith(".") for p in rel.parts):
            part = front_part_of(note.read_text(errors="replace"))
            if part and part.startswith(f"{handle}#"):
                out[rel.as_posix()] = note.read_bytes()
    return out


def changed_parts(before: Path, after: Path) -> list[str]:
    """The parts whose words changed (references aside) or that exist on one side only."""
    b = {s.handle: s.text for s in document.load_one(before).parts}
    a = {s.handle: s.text for s in document.load_one(after).parts}
    return [
        h
        for h in sorted(set(a) | set(b))
        if h not in a
        or h not in b
        or synthesis_units.without_references(a[h]) != synthesis_units.without_references(b[h])
    ]


def decide_backfill(f: dict) -> list[str]:
    """The backfill trial's rule on its measured numbers `f`; each check is printed with PASS or FAILED. Two
    preconditions come first (a trial that applied nothing, or has no sample, proves nothing); when one fails the other
    conditions are not read. Wrong references and coverage are decided on the worst case (unjudged units are findings
    without a reference, unjudged pairs are wrong); the best case is printed."""

    def line(text: str, ok: bool) -> tuple[str, bool]:
        return f"  {text}: {'PASS' if ok else 'FAILED'}", ok

    applied = f["applied"]
    pre = [
        line(f"the sample is not empty ({f['sample']} new pairs)", f["sample"] > 0),
        line(
            "the backfill applied at least one reference in every chosen synthesis ("
            + ", ".join(f"{h} {n}" for h, n in applied.items())
            + ")",
            bool(applied) and all(n > 0 for n in applied.values()),
        ),
    ]
    if not all(ok for _, ok in pre):
        return [text for text, _ in pre] + [
            "Verdict backfill: FAIL (a precondition failed; the other conditions are not read)"
        ]
    cov_all = f["covered"] / f["findings_worst"] if f["findings_worst"] else 0.0
    cov_new = f["covered_new"] / f["findings_new_worst"] if f["findings_new_worst"] else 0.0
    none = f["none"] / f["units_sent"] if f["units_sent"] else 1.0
    info = (
        f"  coverage of all findings, worst case {cov_all:.2f} ({f['covered']}/{f['findings_worst']}; best case "
        f"{f['covered']}/{f['findings']}): reported, not decided"
    )
    checks = [
        line(
            f"wrong references in the sample, worst case {f['wrong_worst']} <= {BACKFILL_MAX_WRONG} (sample of "
            f"{f['sample']}; best case {f['wrong']})",
            f["wrong_worst"] <= BACKFILL_MAX_WRONG,
        ),
        line(
            f"coverage of the findings that had no reference before, worst case {cov_new:.2f} "
            f"({f['covered_new']}/{f['findings_new_worst']}; best case {f['covered_new']}/{f['findings_new']}) >= "
            f"{BACKFILL_MIN_COVERAGE}",
            f["findings_new_worst"] > 0 and cov_new >= BACKFILL_MIN_COVERAGE,
        ),
        line(
            f"`none` answers {none:.2f} ({f['none']}/{f['units_sent']} units sent) <= {BACKFILL_MAX_NONE}",
            f["units_sent"] > 0 and none <= BACKFILL_MAX_NONE,
        ),
        line(
            "every part keeps its words, `mem check` exits 0, no note falls behind its section",
            f["preserved"],
        ),
        line("`mem restore` brought back every snapshotted file byte for byte", f["restored"]),
    ]
    notes = []
    if f["sample"] < BACKFILL_SAMPLE:
        notes.append(f"the sample holds {f['sample']} pairs, not {BACKFILL_SAMPLE}")
    if not calibration_valid(f["planted"], f["found"]):
        notes.append(
            f"calibration not valid ({f['found']} of {f['planted']} strong planted found, needs "
            f"{calibration_min(f['planted'])} and at least {CALIBRATION_MIN_PLANTED} planted)"
        )
    if f["unreliable"]:
        notes.append(f"{f['unreliable']} reference reports are unreliable")
    ok = all(ok for _, ok in pre + checks)
    return (
        [text for text, _ in pre]
        + [info]
        + [text for text, _ in checks]
        + (["preliminary: " + "; ".join(notes)] if notes else [])
        + [f"Verdict backfill: {'PASS' if ok else 'FAIL'}" + (" (preliminary)" if notes else "")]
    )


def run_mem_synthesize(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, **kw)


@dataclass
class BackfillTrial:
    """One backfill trial: the steps run on the copy in `base/store`, the numbers measured by each step (`m`), and what
    went wrong (`failures`). Every step after the copy is attempted on its own: the money is spent, so the results
    file must survive a step that fails."""

    claude: str
    env: dict
    handles: list[str]
    base: Path
    judge_model: str
    budget_usd: float
    backfill_budget: float
    results: Path

    def __post_init__(self) -> None:
        self.store, self.work = self.base / "store", self.base / "work"
        self.before_dir, self.after_dir = self.base / "before", self.base / "after"
        self.budget = Budget(self.budget_usd)
        self.m: dict = {
            "done": None,
            "rows": [],
            "total": None,
            "changed": {},
            "check_exit": None,
            "behind": [None, None],
            "refs": {},
            "new": [],
            "sample": [],
            "restore_codes": {},
            "differs": [],
            "restored": False,
            "preserved": False,
            "sessions": [],
            "planted": 0,
            "found": 0,
            "weak_planted": 0,
            "weak_found": 0,
            "none": 0,
            "units_sent": 0,
            "sizes_before": {},
            "wrong": 0,
            "wrong_worst": 0,
            "applied": {},
            "backfill_cost": None,
        }
        self.failures: list[str] = []
        self.snaps: dict = {}
        self.pairs_before: dict = {}
        self.had_ref: dict = {}
        self.verdicts: dict = {}
        self.quota = Quota(CALIBRATION_PLANTED, len(self.handles))
        self.numbers: dict = {}
        self.decision: list[str] = []

    @property
    def judge_cost(self) -> float:
        return sum(x["cost"] for x in self.m["sessions"])

    def attempt(self, name: str, fn) -> None:
        try:
            fn()
        except (
            Exception
        ) as exc:  # every step after the copy: the money is spent, the results must survive
            logger.debug("%s failed", name, exc_info=True)
            self.failures.append(f"{name}: {type(exc).__name__}: {exc}"[:300])

    def setup(self) -> None:
        m = self.m
        self.work.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.base / "settings.json").write_text(
            json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(self.store)}}}})
        )
        self.before_dir.mkdir()
        self.after_dir.mkdir()
        for h in self.handles:
            self.snaps[h] = snapshot_files(self.store, h)
            shutil.copy(self.store / "syntheses" / f"{h}.md", self.before_dir / f"{h}.md")
        m["behind"][0] = behind_count(self.store, self.env)
        for h in self.handles:
            units_before = file_units(self.before_dir / f"{h}.md")
            self.pairs_before[h] = {(p, n, t) for p, n, refs in units_before for t in refs}
            self.had_ref[h] = {(p, n) for p, n, refs in units_before if refs}
            t = (self.before_dir / f"{h}.md").read_text()
            m["sizes_before"][h] = (tokens(t), tokens(document.shown_file(t)))

    def backfill(self) -> None:
        m = self.m
        cmd = [
            str(PLUGIN / "bin" / "mem-synthesize"),
            "--backfill",
            *[f"s:{h}" for h in self.handles],
            "--budget",
            f"{self.backfill_budget}",
            "--claude",
            self.claude,
            "--store",
            str(self.store),
        ]
        print("running: " + " ".join(cmd[1:]), flush=True)
        self.budget.hold(self.backfill_budget)  # its own cap; nothing else is running yet
        cost = None  # unknown (a timeout, no table): counted at its cap
        try:
            m["done"] = run_mem_synthesize(
                cmd,
                cwd=self.base,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=1800 * len(self.handles),
            )
            (self.base / "backfill-output.txt").write_text(
                m["done"].stdout + "\n--- stderr ---\n" + m["done"].stderr
            )
            print(m["done"].stdout)
            m["rows"], m["total"] = parse_backfill_table(m["done"].stdout)
            if m["total"] and (m["total"].get("cost USD") or "").strip():
                cost = number(m["total"]["cost USD"])
        finally:
            m["backfill_cost"] = cost
            self.budget.settle(self.backfill_budget, self.backfill_budget if cost is None else cost)
        m["none"], m["units_sent"] = (
            int(number((m["total"] or {}).get("none"))),
            int(number((m["total"] or {}).get("units"))),
        )

    def words_kept(self) -> None:  # words kept, mem check, nothing behind its section
        m = self.m
        preserved = True
        for h in self.handles:
            shutil.copy(self.store / "syntheses" / f"{h}.md", self.after_dir / f"{h}.md")
            m["changed"][h] = changed_parts(self.before_dir / f"{h}.md", self.after_dir / f"{h}.md")
            preserved &= not m["changed"][h]
        m["check_exit"] = mem(self.store, self.env, "check").returncode
        m["behind"][1] = behind_count(self.store, self.env)
        m["preserved"] = preserved and m["check_exit"] == 0 and m["behind"][1] <= m["behind"][0]

    def new_pairs(self) -> None:
        m = self.m
        m["new"] = sorted(
            (h, p, n, t)
            for h in self.handles
            for p, n, refs_ in file_units(self.after_dir / f"{h}.md")
            for t in refs_
            if (p, n, t) not in self.pairs_before[h]
        )
        m["applied"] = {h: sum(1 for x in m["new"] if x[0] == h) for h in self.handles}

    def judge_one(self, h: str) -> None:
        m, budget = self.m, self.budget
        if not budget.start("ref"):
            raise RuntimeError(f"not started: budget (reference judgment of {h})")
        parsed, s = ref_session(
            self.claude, self.base, self.env, h, judge_model=self.judge_model, role="ref-judge"
        )
        budget.finish("ref", s["cost"])
        m["sessions"].append(s)
        m["refs"][h], self.verdicts[h] = score_refs(
            self.store / "syntheses" / f"{h}.md", parsed, s["ok"], self.had_ref[h]
        )
        share = self.quota.take()
        if not budget.start("calibration"):
            self.quota.spent(0)
            raise RuntimeError(f"not started: budget (calibration of {h})")
        cal, more = calibrate(
            self.claude,
            self.base,
            self.env,
            h,
            judge_model=self.judge_model,
            verdicts=self.verdicts[h],
            quota=share,
            kinds=parsed["units"] if parsed else {},
        )
        budget.finish("calibration", sum(x["cost"] for x in more))
        self.quota.spent(cal["planted"])
        m["refs"][h]["cal"], m["sessions"] = cal, m["sessions"] + more
        for key in ("planted", "found", "weak_planted", "weak_found"):
            m[key] += cal[key]

    def choose_sample(self) -> None:
        """The sample of new pairs the judge's verdicts are counted over: wrong (best case) and wrong or unjudged."""
        m = self.m
        sample = random.Random(0).sample(m["new"], min(BACKFILL_SAMPLE, len(m["new"])))
        m["sample"] = sample
        m["wrong"] = sum(
            1 for h, p, n, t in sample if self.verdicts.get(h, {}).get((p, n, t)) is False
        )
        m["wrong_worst"] = sum(
            1 for h, p, n, t in sample if self.verdicts.get(h, {}).get((p, n, t)) is not True
        )

    def restore(self) -> None:  # undo with `mem restore`, then compare bytes
        m, store, handles = self.m, self.store, self.handles
        touched = [
            h
            for h in handles
            if (store / "syntheses" / f"{h}.md").read_bytes() != self.snaps[h][f"syntheses/{h}.md"]
        ]
        m["restore_codes"] = {
            h: mem(store, self.env, "restore", f"s:{h}").returncode for h in handles
        }  # nothing to undo when untouched
        m["differs"] = [
            rel
            for h in handles
            for rel, data in self.snaps[h].items()
            if not (store / rel).is_file() or (store / rel).read_bytes() != data
        ]
        m["restored"] = not m["differs"] and not any(m["restore_codes"][h] for h in touched)

    def run_steps(self) -> None:
        self.attempt("setup", self.setup)
        if self.failures:
            return
        self.attempt("mem-synthesize --backfill", self.backfill)
        self.attempt("words kept and mem check", self.words_kept)
        self.attempt("new references", self.new_pairs)
        for h in self.handles:
            self.attempt(
                f"reference judgment and calibration of {h}", lambda h=h: self.judge_one(h)
            )
        self.choose_sample()
        self.attempt("mem restore", self.restore)

    def measured_numbers(self) -> dict:
        """The numbers `decide_backfill` reads."""
        m, refs = self.m, self.m["refs"]
        return {
            "wrong": m["wrong"],
            "wrong_worst": m["wrong_worst"],
            "sample": len(m["sample"]),
            "applied": m["applied"],
            "findings": sum(r["findings"] for r in refs.values()),
            "findings_worst": sum(r["findings_worst"] for r in refs.values()),
            "covered": sum(r["covered"] for r in refs.values()),
            "findings_new": sum(r["findings_new"] for r in refs.values()),
            "findings_new_worst": sum(r["findings_new_worst"] for r in refs.values()),
            "covered_new": sum(r["covered_new"] for r in refs.values()),
            "none": m["none"],
            "units_sent": m["units_sent"],
            "preserved": m["preserved"],
            "restored": m["restored"],
            "planted": m["planted"],
            "found": m["found"],
            "weak_planted": m["weak_planted"],
            "weak_found": m["weak_found"],
            "unreliable": sum(bool(r["unreliable"]) for r in refs.values()),
        }

    def run(self) -> None:
        """Every step, the numbers and the decision; the results file is written even when one of them raises."""
        try:
            self.run_steps()
            self.numbers = self.measured_numbers()
            self.decision = (
                [f"  failed step: {x}" for x in self.failures]
                + [f"Verdict backfill: FAILED: {self.failures[0].split(':')[0]}"]
                if self.failures
                else decide_backfill(self.numbers)
            )
        finally:
            self.write_results()

    def write_results(self) -> None:
        m, failures = self.m, self.failures
        done = m["done"]
        self.results.write_text(
            json.dumps(
                {
                    "handles": self.handles,
                    "exit": done.returncode if done else None,
                    "rows": m["rows"],
                    "total": m["total"],
                    "changed_parts": m["changed"],
                    "mem_check": m["check_exit"],
                    "behind": m["behind"],
                    "references": m["refs"],
                    "new_pairs": len(m["new"]),
                    "numbers": self.numbers,
                    "decision": self.decision,
                    "failed_step": failures[0].split(":")[0] if failures else None,
                    "failures": failures,
                    "restore_codes": m["restore_codes"],
                    "files_not_restored": m["differs"],
                    "judge_cost": self.judge_cost,
                    "backfill_cost": m["backfill_cost"],
                    "spent": self.budget.spent,
                    "sessions_assumed_at_cap": sum(
                        bool(x.get("cost_assumed")) for x in m["sessions"]
                    ),
                    "sessions": m["sessions"],
                    "tokens_before": m["sizes_before"],
                },
                indent=1,
                default=str,
            )
        )

    def print_report(self) -> None:
        """The decision, one line per synthesis the backfill ran on and the totals."""
        m = self.m
        print("\n".join(self.decision))
        for row in m["rows"]:
            cost, parts = number(row.get("cost USD")), int(number(row.get("parts")))
            h = row.get("synthesis", "")
            before, after = m["sizes_before"].get(h), None
            if h in self.handles and (self.after_dir / f"{h}.md").is_file():
                t = (self.after_dir / f"{h}.md").read_text()
                after = (tokens(t), tokens(document.shown_file(t)))
            print(
                f"  {h}: cost {cost:.3f} USD over {parts} parts ({cost / parts:.3f} per part); tokens stored/shown "
                f"{fmt_tokens(before[0]) if before else '-'}/{fmt_tokens(before[1]) if before else '-'} before, "
                f"{fmt_tokens(after[0]) if after else '-'}/{fmt_tokens(after[1]) if after else '-'} after"
                if parts
                else f"  {h}: not run ({row.get('status')})"
            )
        done = m["done"]
        print(
            f"mem-synthesize exit {done.returncode if done else '-'}; mem check {m['check_exit']}; notes behind their section "
            f"{m['behind'][0]} -> {m['behind'][1]}; judge sessions cost {self.judge_cost:.3f} USD; total {self.budget.spent:.3f} of "
            f"--budget {self.budget_usd:.2f} USD (backfill, reference judgments and calibrations; "
            f"{sum(bool(x.get('cost_assumed')) for x in m['sessions'])} sessions returned no cost and are counted at their cap "
            f"{SESSION_CAP_USD})"
        )
        print(f"results: {self.results}")


class BackfillOptions(TypedDict, total=False):
    budget_usd: Required[float]
    judge_model: Required[str]
    results_dir: Path


def backfill_trial(
    claude: str, root: Path, env: dict, handles: list[str], **options: Unpack[BackfillOptions]
) -> int:
    """Exit 0 when it ran to the end, 1 when a step failed (the results file is written either way), 2 when it refused
    before any session, 3 when `root` already holds a backfill trial."""
    budget_usd = options["budget_usd"]
    source = ensure_source()
    missing = [h for h in handles if not (source / "syntheses" / f"{h}.md").is_file()]
    if missing:
        print(
            f"no synthesis named {', '.join(missing)} in the prepared source copy", file=sys.stderr
        )
        return 2
    base = root / "backfill"
    if base.exists() or any(root.rglob("backfill-done.json")):
        print(
            f"{root} already holds a backfill trial: its done list would make mem-synthesize skip the parts it "
            f"finished, so nothing would be checked. Pass a new --work or delete the folder.",
            file=sys.stderr,
        )
        return 3
    judges = len(handles) * (
        RESERVE["ref"] + RESERVE["calibration"]
    )  # what the judgments of the syntheses may need
    backfill_budget = budget_usd - judges
    if backfill_budget <= 0:
        print(
            f"--budget {budget_usd:.2f} leaves nothing for the backfill after reserving {judges:.2f} USD for the "
            f"{len(handles)} reference judgments and calibrations",
            file=sys.stderr,
        )
        return 2
    shutil.copytree(source, base / "store")  # every synthesis stays
    results = (
        options.get("results_dir", trial_env.TARGET)
        / f"backfill-trial-{time.strftime('%Y%m%d-%H%M%S')}.json"
    )
    trial = BackfillTrial(
        claude, env, handles, base, options["judge_model"], budget_usd, backfill_budget, results
    )
    trial.run()
    trial.print_report()
    return 1 if trial.failures else 0


# --- self-check ----------------------------------------------------------------------------------------------

DEMO = """---
title: Demo
topics: [demo]
created: 2026-01-01
updated: 2026-01-01
---

## Summary

An invented summary. [Alpha note](../knowledge/x/a.md)

## Alpha

Spacing helps recall. [Alpha note](../knowledge/x/a.md) Testing helps too. [Beta note](../literature/b.md) [Alpha note](../knowledge/x/a.md)
Practice is useful, see [Beta note](../literature/b.md) here.

Sources: [Alpha note](../knowledge/x/a.md)

## Beta

Rest helps. [Beta note](../literature/b.md)

Sources: [Beta note](../literature/b.md)
"""


def frozen_text_checks() -> None:
    """The frozen judge brief, the filled briefs and the arm tables."""
    fill = {"TOPIC": "t", "SLUG": "t", "STORE": "s", "WORK_DIR": "w", "REPORT_FILE": "r"}
    assert sorted(x.name for x in FROZEN.iterdir()) == ["README.md", "checker-brief.md"], (
        "frozen-main holds the judge's brief only"
    )
    assert "{UNITS_FILE}" not in (FROZEN / "checker-brief.md").read_text()
    for name in ("writer", "checker", "fixer"):
        text = brief(name, SKILL_FILE=str(sp.SKILL), **fill)
        assert not re.findall(r"\{[A-Z_]+\}", text), name
    assert "texts" not in globals() and "FROZEN_ARMS" not in globals(), (
        "arm M no longer resolves to frozen texts"
    )
    assert "M" in LEAN and "R" in LEAN and "R" not in DEFAULT_ARMS and WRITER["R"] == WRITER["M"]


def store_preparation_checks(root: Path) -> tuple[Path, Path]:
    """Store preparation (D) on an invented store; return the store and its demo synthesis."""
    store = root / "demo-store"
    (store / "syntheses").mkdir(parents=True)
    for rel in ("knowledge/x/a.md", "literature/b.md"):
        (store / rel).parent.mkdir(parents=True, exist_ok=True)
        (store / rel).write_text("note\n")
    path = store / "syntheses" / "demo.md"
    path.write_text(DEMO)
    assert (
        drop_unlisted_references(store) == TWO
    )  # Alpha's two Beta references; Beta's own and the Summary's stay
    prepared = path.read_text()
    assert prepared == DEMO.replace(" [Beta note](../literature/b.md) [Alpha", " [Alpha").replace(
        "see [Beta note](../literature/b.md) here", "see Beta note here"
    ), prepared
    for part in document.load_one(path).parts:
        assert not [
            p
            for p in document.validate_section(part.text, store)
            if "not on the `Sources:` line" in p
        ], part.handle
    assert drop_unlisted_references(store) == 0
    return store, path


def judge_copy_checks(path: Path) -> None:
    """The judge's copy has no reference in a body while the run's file keeps them."""
    path.write_text(DEMO, encoding="utf-8")
    stripped = without_references_text(path)
    for section in document.load_one(path).sections:
        assert document.references(section.text), section.handle
    path.write_text(stripped, encoding="utf-8")
    assert all(not document.references(sec.text) for sec in document.load_one(path).sections)
    assert [ln for ln in stripped.splitlines() if ln.startswith("Sources:")] == [
        ln for ln in DEMO.splitlines() if ln.startswith("Sources:")
    ]
    path.write_text(DEMO, encoding="utf-8")


def judge_row_checks(root: Path, env: dict, store: Path) -> None:
    """`judge_row` with a stub session: sees the stripped file and the frozen checker brief, leaves the stored file
    back."""
    base = root / "judge-fixture"
    shutil.copytree(store, base / "store")
    (base / "work").mkdir()
    (base / "settings.json").write_text("{}")
    seen = {}

    def stub(*args, **kw):
        prompt, work = args[2], args[3]
        seen["file"] = (base / "store" / "syntheses" / "demo.md").read_text()
        seen["prompt"] = prompt
        (work / "judge-report.md").write_text("COUNTS: checked=10 unsupported=1 used=1 unused=0\n")
        return {
            "model_usage": {"claude-haiku-4-5": {"costUSD": 0.01}},
            "has_result": True,
            "error": "",
            "cost": 0.01,
            "wall": 1.0,
            "writes": 0,
            "write_errors": 0,
            "denied": False,
            "tool_errors": 0,
            "answer": "",
        }

    original = globals()["run_session"]
    globals()["run_session"] = stub
    try:
        (base / "store" / "syntheses" / "demo.md").write_text(DEMO)
        row = judge_row(
            "claude",
            base,
            env,
            "demo",
            arm="M",
            run=1,
            judge_model="haiku",
            prior={
                "sessions": [],
                "why": "",
                "denominator": ["knowledge/x/a.md"],
                "arm_count": None,
                "fixes": 0,
            },
        )
    finally:
        globals()["run_session"] = original
    seen_path = root / "seen.md"
    seen_path.write_text(seen["file"])
    assert all(
        not document.references(sec.text) for sec in document.load_one(seen_path).sections
    ), seen["file"]
    assert seen["file"].count("Sources:") == TWO
    assert (base / "store" / "syntheses" / "demo.md").read_text() == DEMO, (
        "the run's file was not restored"
    )
    assert (FROZEN / "checker-brief.md").read_text().split("{")[0] in seen[
        "prompt"
    ] and JUDGE_EXTRA in seen["prompt"]
    assert (
        row["tokens_stored"] == len(DEMO) / 4
        and row["tokens_shown"] == len(document.shown_file(DEMO)) / 4
    )
    assert row["tokens_shown"] < row["tokens_stored"] and row["checked"] == TEN, row


def rule_f_runs(arm, rates, cost, refs=True, mem_check=0):
    """Synthetic result rows for rule F; the R rows carry a reference judgment unless `refs` is False."""
    extra = {}
    if refs:
        extra = {
            "tokens_shown": 1000,
            "tokens_stored": 2000,
            "ref": {
                "findings": 100,
                "covered": 90,
                "pairs": 100,
                "wrong": 1,
                "findings_worst": 100,
                "pairs_worst": 100,
                "wrong_worst": 1,
                "unreliable": False,
                "cal": {"planted": 20, "found": 20, "weak_planted": 0, "weak_found": 0},
            }
            if arm == "R"
            else None,
        }
    return [
        dict(
            topic="human-memory",
            arm=arm,
            run=n,
            valid=True,
            checked=100,
            unsupported=rate,
            used=6,
            denominator=6,
            words=3000,
            mem_check=mem_check if arm == "R" else 0,
            cost=cost + 0.4,
            pipeline_cost=cost,
            judge_cost=0.4,
            **extra,
        )
        for n, rate in enumerate(rates, 1)
    ]


def rule_f_checks() -> None:
    """Rule F on synthetic result sets."""
    runs = rule_f_runs
    ok = decide(runs("M", [5, 6], 0.4) + runs("R", [6, 7], 0.45))
    assert ok[-1] == "Verdict R against M: PASS" and not any(
        x.startswith("preliminary") for x in ok
    ), ok
    bad = decide(runs("M", [5, 6], 0.4) + runs("R", [12, 12], 0.45))
    assert bad[-1] == "Verdict R against M: FAIL" and any(
        "FAILED" in x and "unsupported" in x for x in bad
    ), bad
    assert (
        decide(runs("M", [5, 6], 0.4) + runs("R", [6, 7], 0.6))[-1] == "Verdict R against M: FAIL"
    )  # cost 0.6 >= 1.3 x 0.4
    assert (
        decide(runs("M", [5], 0.4) + runs("R", [6], 0.45))[-1]
        == "Verdict R against M: PASS (preliminary)"
    )
    assert decide(runs("M", [3, 9], 0.4) + runs("R", [6, 7], 0.45))[-1].endswith("(preliminary)")
    assert exactly(run_gap(runs("M", [3, 9], 0.4)), 6.0) and exactly(
        run_gap(runs("M", [3], 0.4)), 0.0
    )
    # finding 2: no reference judgment (--no-ref-judge) is never a PASS
    for rows_ in (
        runs("M", [5, 6], 0.4, refs=False) + runs("R", [6, 7], 0.45, refs=False),
        runs("M", [5, 6], 0.4, refs=False)
        + runs("R", [6, 7], 0.45, refs=False)[:1]
        + runs("R", [6, 7], 0.45)[1:],
    ):
        out = decide(rows_)
        assert (
            out[-1] == "Verdict R against M: PRELIMINARY: reference judgment not run"
            and "PASS" not in out[-1]
        ), out
    # finding 3: an R synthesis that fails `mem check` fails the decision, with its count
    broken = decide(runs("M", [5, 6], 0.4) + runs("R", [6, 7], 0.45, mem_check=1))
    assert broken[-1] == "Verdict R against M: FAIL" and any(
        "every R synthesis passes mem check (0/2)" in x and "FAILED" in x for x in broken
    ), broken
    one = runs("R", [6, 7], 0.45)
    one[0]["mem_check"] = 1
    assert any("(1/2)" in x and "FAILED" in x for x in decide(runs("M", [5, 6], 0.4) + one))


def harness_checks(root: Path, env: dict) -> None:
    """No model and no real store: frozen texts, the arms' files, the judge's copy, the store preparation, rule F."""
    frozen_text_checks()
    store, path = store_preparation_checks(root)
    judge_copy_checks(path)
    judge_row_checks(root, env, store)
    rule_f_checks()


FIXTURE = """---
title: Fixture
topics: [demo]
created: 2026-01-01
updated: 2026-01-01
---

## Summary

An invented summary of the fixture topic.

## Forgetting

Recall drops quickly after learning. [Note A](../knowledge/x/a.md) Review spread over days keeps more. [Note B](../knowledge/x/b.md) Inference: both effects may share a cause. Sleep helps retention too. [Note C](../knowledge/x/c.md) Tests beat rereading. [Note A](../knowledge/x/a.md)

Sources: [Note A](../knowledge/x/a.md), [Note B](../knowledge/x/b.md), [Note C](../knowledge/x/c.md)

## Single

One thing holds. [Note D](../knowledge/x/d.md)

Sources: [Note D](../knowledge/x/d.md)
"""

REPORT = """Some chatter the parser ignores.
- U: forgetting | 1 | finding
`P: forgetting | 1 | ../knowledge/x/a.md | yes`
  U:  forgetting | 2 | finding
P: forgetting | 2 | ../knowledge/x/b.md | no
U: forgetting | 3 | other
U: forgetting | 4 | finding
P: forgetting | 4 | `../knowledge/x/c.md` | yes
U: forgetting | x | finding
U: single | 1 | finding
P: single | 1 | ../knowledge/x/d.md | yes
COUNTS: units=6 pairs=4 no=1
"""

_TABLE_LINES = [
    (
        "synthesis",
        "parts",
        "units",
        "proposed",
        "applied",
        "refused",
        "none",
        "extra",
        "unreadable",
        "repeated",
        "mem check",
        "cost USD",
        "status",
    ),
    ("a", "2", "40", "30", "25", "2", "8", "1", "0", "0", "0", "0.120", "ok"),
    ("b", "1", "10", "6", "6", "0", "4", "0", "0", "0", "0", "0.050", "ok"),
    ("total", "3", "50", "36", "31", "2", "12", "1", "0", "0", "", "0.170", ""),
]
_WIDTHS = [
    max(len(r[i]) for r in _TABLE_LINES) for i in range(13)
]  # laid out as mem-synthesize does: ljust, 2 spaces
TABLE = (
    "mem-synthesize --backfill: 2 syntheses (a, b), budget 3.00 USD, log /x/log.txt\n"
    + "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(r, _WIDTHS, strict=False)).rstrip()
        for r in _TABLE_LINES
    )
    + "\ntotal cost USD 0.170; log /x/log.txt\n"
)


GOOD_REFS = {"findings": 100, "covered": 90, "pairs": 100, "wrong": 2}


def reference_stub(findings, covered, pairs, wrong, **options):
    """An invented reference judgment; `options` set the calibration (`planted`, `found`), `unreliable` and `worst`."""
    planted, found = options.get("planted", 10), options.get("found", 10)
    w = options.get("worst") or {}
    return {
        "findings": findings,
        "covered": covered,
        "pairs": pairs,
        "wrong": wrong,
        "units": findings,
        "unjudged": 0,
        "unreadable": 0,
        "findings_worst": w.get("findings", findings),
        "pairs_worst": w.get("pairs", pairs),
        "wrong_worst": w.get("wrong", wrong),
        "unreliable": options.get("unreliable", False),
        "cal": {"planted": planted, "found": found, "weak_planted": 0, "weak_found": 0},
    }


def reference_rows(arm, shown, **kw):
    return [
        {
            "topic": "human-memory",
            "arm": arm,
            "run": n,
            "valid": True,
            "checked": 100,
            "unsupported": 5,
            "used": 6,
            "denominator": 6,
            "words": 3000,
            "mem_check": 0,
            "cost": 0.85,
            "pipeline_cost": 0.45,
            "judge_cost": 0.4,
            "tokens_stored": 2000,
            "tokens_shown": shown,
            "ref": reference_stub(**kw)
            if arm == "R"
            else reference_stub(100, 90, 100, 1, planted=0, found=0),
        }
        for n in (1, 2)
    ]


def ref_parser_checks() -> dict:
    """The reference judge's brief and its report parser; return the parsed fixture report."""
    text = brief("ref-judge", HERE, SLUG="s", STORE="/st", UNITS_FILE="/u.md", REPORT_FILE="/r.md")
    assert not re.findall(r"\{[^}\n]*\}", text) and "/st/syntheses/s.md" in text and "/r.md" in text
    raw = (HERE / "ref-judge-brief.md").read_text()
    assert "/home/" not in raw and "/tmp/" not in raw and "~/" not in raw
    # the parser
    parsed = parse_ref_report(REPORT)
    assert parsed["units"] == {
        ("forgetting", 1): "finding",
        ("forgetting", 2): "finding",
        ("forgetting", 3): "other",
        ("forgetting", 4): "finding",
        ("single", 1): "finding",
    }, parsed
    assert parsed["pairs"] == {
        ("forgetting", 1, "../knowledge/x/a.md"): True,
        ("forgetting", 2, "../knowledge/x/b.md"): False,
        ("forgetting", 4, "../knowledge/x/c.md"): True,
        ("single", 1, "../knowledge/x/d.md"): True,
    }, parsed
    assert parsed["unreadable"] == 1 and parsed["counts_ok"] is False, (
        parsed
    )  # the judge counted the unreadable U line
    # finding 9: decorated lines are read, other lines that look like U:/P: lines are counted, COUNTS is compared
    deco = parse_ref_report(
        "**U: forgetting | 1 | finding**\n1. U: forgetting | 2 | other\n2) **P: forgetting | 1 | ../knowledge/x/a.md | yes**\n"
        "U:** single | 1 | finding\nsee U: forgetting | 3 | finding for details\nP: broken | line | here |\n"
        "COUNTS: units=3 pairs=1 no=0\n"
    )
    assert deco["units"] == {
        ("forgetting", 1): "finding",
        ("forgetting", 2): "other",
        ("single", 1): "finding",
    }, deco
    assert deco["pairs"] == {("forgetting", 1, "../knowledge/x/a.md"): True}, deco
    assert deco["unreadable"] == TWO and deco["counts_ok"] is True, (
        deco
    )  # "see U: ..." and "P: broken | line | here |"
    assert (
        parse_ref_report("U: a | 1 | finding\nCOUNTS: units=2 pairs=0 no=0\n")["counts_ok"] is False
    )
    assert (
        parse_ref_report("U: a | 1 | finding\n")["counts_ok"] is False
    )  # a missing COUNTS line disagrees
    assert parse_ref_report(
        "U: a | 1 | finding\nP: a | 1 | ../knowledge/x/a.md | no\nCOUNTS: units=1 pairs=1 no=1\n"
    )["counts_ok"]
    return parsed


def ref_scoring_checks(root: Path, parsed: dict) -> tuple[Path, Path, dict]:
    """Scoring on the fixture; return its store, its synthesis path and the verdicts."""
    store = root / "ref-fixture"
    path = store / "syntheses" / "fix.md"
    path.parent.mkdir(parents=True)
    path.write_text(FIXTURE)
    got, verdicts = score_refs(path, parsed)
    assert (
        got["units"],
        got["findings"],
        got["covered"],
        got["pairs"],
        got["wrong"],
        got["unjudged"],
    ) == (6, 4, 4, 4, 1, 2), got
    assert got["unreliable"] and got["unreadable"] == 1 and len(verdicts) == FOUR
    full = REPORT.replace(
        "U: forgetting | x | finding\n",
        "U: forgetting | 5 | finding\nP: forgetting | 5 | ../knowledge/x/a.md | yes\nU: forgetting | 6 | other\n",
    )
    full = full.replace("COUNTS: units=6 pairs=4 no=1", "COUNTS: units=7 pairs=5 no=1")
    full_got, _ = score_refs(path, parse_ref_report(full))
    assert (
        full_got["unjudged"] == 0 and not full_got["unreliable"] and full_got["findings"] == FIVE
    ), full_got
    assert score_refs(path, parse_ref_report(full.replace("units=7", "units=6")))[0][
        "unreliable"
    ], "a COUNTS mismatch is unreliable"
    # finding 8: unjudged units are worst-case findings without a reference, unjudged pairs are wrong
    assert (got["unjudged_units"], got["unjudged_pairs"]) == (1, 1), got
    assert (
        got["findings"],
        got["findings_worst"],
        got["pairs"],
        got["pairs_worst"],
        got["wrong"],
        got["wrong_worst"],
    ) == (4, 5, 4, 5, 1, 2), got
    assert (full_got["findings_worst"], full_got["wrong_worst"], full_got["pairs_worst"]) == (
        5,
        1,
        5,
    ), full_got
    nothing = score_refs(path, None)[0]
    assert (
        nothing["findings"],
        nothing["findings_worst"],
        nothing["wrong_worst"],
        nothing["pairs_worst"],
    ) == (0, 6, 5, 5), nothing
    assert (
        score_refs(path, None)[0]["unreliable"]
        and score_refs(path, parsed, session_ok=False)[0]["unreliable"]
    )
    # a finding without a reference is not covered
    bare = FIXTURE.replace(
        "Sleep helps retention too. [Note C](../knowledge/x/c.md)", "Sleep helps retention too."
    )
    path.write_text(bare)
    assert score_refs(path, parsed)[0]["covered"] == THREE
    path.write_text(FIXTURE)
    return store, path, verdicts


def ref_planting_checks(path: Path, verdicts: dict) -> tuple[dict, dict]:
    """Planting (finding 10); return the verdicts with the unit-5 pair and the unit kinds."""
    every = dict.fromkeys(verdicts, True) | {("forgetting", 5, "../knowledge/x/a.md"): True}
    kinds = {(h, n): "finding" for h, n, _ in file_units(path)}
    text_planted, planted, weak = plant_references(path, every, 3, random.Random(0), kinds)
    assert len(planted) == THREE and weak == [] and len({(h, n) for h, n, _ in planted}) == THREE, (
        planted,
        weak,
    )
    carried = {(h, n): set(refs) for h, n, refs in file_units(path)}
    path.write_text(text_planted, encoding="utf-8")
    after = {(h, n): set(refs) for h, n, refs in file_units(path)}
    for h, n, target in planted:
        own_sources = (
            {"../knowledge/x/a.md", "../knowledge/x/b.md", "../knowledge/x/c.md"}
            if h == "forgetting"
            else {"../knowledge/x/d.md"}
        )
        assert target not in own_sources, (h, n, target)  # never a source of the unit's own part
        assert after[h, n] == {target} and after[h, n] != carried[h, n], (h, n)
    assert text_planted != FIXTURE and "[Note" in text_planted
    path.write_text(FIXTURE, encoding="utf-8")
    return every, kinds


def ref_planting_limit_checks(path: Path, every: dict, kinds: dict) -> None:
    """The planting quota, the units the judge did not mark `finding` and a part with no unrelated source."""
    assert (
        len(plant_references(path, every, 50, random.Random(0), kinds)[1]) == FIVE
    )  # at most one per candidate unit
    assert plant_references(path, {}, 3, random.Random(0), kinds)[1:] == ([], [])
    assert plant_references(path, every, 3, random.Random(0), {})[1:] == ([], []), (
        "no unit marked finding: nothing planted"
    )
    only = plant_references(
        path,
        every,
        50,
        random.Random(0),
        {("forgetting", 1): "finding", ("forgetting", 2): "other", ("single", 1): "other"},
    )
    assert [(h, n) for h, n, _ in only[1]] == [("forgetting", 1)] and only[2] == [], (
        only
    )  # `other` units are never planted
    # a part whose sources are all in the other parts' sources too has no unrelated note: weak plants, counted apart
    solo = FIXTURE.split("## Single", maxsplit=1)[0]
    path.write_text(solo, encoding="utf-8")
    _, strong_only, weak_only = plant_references(path, every, 3, random.Random(0), kinds)
    assert (
        strong_only == []
        and len(weak_only) == THREE
        and all(h == "forgetting" for h, _, _ in weak_only)
    ), (strong_only, weak_only)
    path.write_text(FIXTURE, encoding="utf-8")


def ref_calibration_checks(root: Path, store: Path, every: dict, kinds: dict) -> None:
    """Calibration with a stub session: the judge sees the planted text and marks half of the planted pairs `no`."""
    base = root / "cal-base"
    shutil.copytree(store, base / "store")
    (base / "work").mkdir()
    (base / "settings.json").write_text("{}")
    kept = {}

    def stub(*args, **kw):
        work = args[3]
        seen = (base / "store" / "syntheses" / "fix.md").read_text()
        kept["seen"] = seen
        raw = (work / "ref-calibration-units-fix.md").read_text().splitlines()
        assert seen != FIXTURE and any(" | " in ln for ln in raw)
        flag = iter(["no", "yes", "no"] * 10)
        out, part = [], ""
        for ln in raw:
            if ln.startswith("## "):
                part = ln[3:].strip()
            elif " | " in ln:
                n, _, refs = (c.strip() for c in ln.split(" | ", 2))
                out.append(f"U: {part} | {n} | finding")
                out += [
                    f"P: {part} | {n} | {t.strip()} | {next(flag)}"
                    for t in refs.split(",")
                    if t.strip() != "-"
                ]
        (work / "ref-calibration-report-fix.md").write_text("\n".join(out) + "\n")
        return {
            "model_usage": {"claude-haiku-4-5": {"costUSD": 0.01}},
            "has_result": True,
            "error": "",
            "cost": 0.01,
            "wall": 1.0,
            "writes": 0,
            "write_errors": 0,
            "denied": False,
            "tool_errors": 0,
            "answer": "",
        }

    original = globals()["run_session"]
    globals()["run_session"] = stub
    try:
        cal, sess = calibrate(
            "claude", base, {}, "fix", judge_model="haiku", verdicts=every, quota=3, kinds=kinds
        )
    finally:
        globals()["run_session"] = original
    assert (
        cal["planted"] == THREE
        and 0 <= cal["found"] <= THREE
        and cal["weak_planted"] == 0
        and len(sess) == 1
        and sess[0]["role"] == "ref-calibration"
    ), cal
    assert (base / "store" / "syntheses" / "fix.md").read_bytes() == FIXTURE.encode(), (
        "the stored text was not restored"
    )
    assert kept["seen"] != FIXTURE


def ref_quota_checks() -> None:
    """Each synthesis reports what it planted before the next takes its share."""
    q = Quota(20, 3)
    shares = []
    for planted_now in (
        7,
        7,
        6,
    ):  # each synthesis reports what it planted before the next takes its share
        shares.append(q.take())
        q.spent(planted_now)
    assert shares == [7, 7, 6] and q.left == 0
    q = Quota(20, 3)
    first = q.take()
    q.spent(2)  # the first synthesis could plant only 2: the other two share the 18 left
    assert (first, q.take(), q.left) == (7, 9, 18)


def ref_condition_checks() -> None:
    """The conditions of R and the calibration rules, through `decide`."""
    conds = reference_conditions(reference_rows("R", 1000, **GOOD_REFS), reference_rows("M", 1000))
    assert len(conds) == THREE and all(ok for _, ok in conds), conds
    verdict = decide(reference_rows("M", 1000) + reference_rows("R", 1100, **GOOD_REFS))
    assert verdict[-1] == "Verdict R against M: PASS" and any(
        "calibration" in x and "valid" in x for x in verdict
    ), verdict
    assert any("M references" in x for x in verdict)
    low = decide(
        reference_rows("M", 1000) + reference_rows("R", 1000, **{**GOOD_REFS, "covered": 70})
    )
    assert low[-1] == "Verdict R against M: FAIL" and any(
        "coverage" in x and "FAILED" in x for x in low
    ), low
    bad = decide(reference_rows("M", 1000) + reference_rows("R", 1000, **{**GOOD_REFS, "wrong": 9}))
    assert bad[-1] == "Verdict R against M: FAIL" and any(
        "wrong references" in x and "FAILED" in x for x in bad
    ), bad
    big = decide(reference_rows("M", 1000) + reference_rows("R", 1200, **GOOD_REFS))
    assert big[-1] == "Verdict R against M: FAIL" and any(
        "shorten what `mem show` prints first" in x and "FAILED" in x for x in big
    ), big
    prelim = decide(
        reference_rows("M", 1000) + reference_rows("R", 1000, **GOOD_REFS, planted=10, found=6)
    )
    assert prelim[-1] == "Verdict R against M: PASS (preliminary)" and any(
        "calibration is not valid" in x for x in prelim
    ), prelim
    assert (calibration_min(20), calibration_min(10), calibration_min(7)) == (
        16,
        8,
        6,
    ) and calibration_valid(10, 8)
    assert not calibration_valid(10, 7) and not calibration_valid(0, 0)
    scaled = decide(
        reference_rows("M", 1000)
        + reference_rows(
            "R", 1000, findings=100, covered=90, pairs=100, wrong=2, planted=5, found=4
        )
    )
    assert scaled[-1] == "Verdict R against M: PASS (preliminary)" and any(
        "threshold scaled to 8" in x for x in scaled
    ), scaled
    # finding 10: fewer than 10 strong plants is not a valid calibration, whatever was found
    few = decide(
        reference_rows("M", 1000)
        + reference_rows(
            "R", 1000, findings=100, covered=90, pairs=100, wrong=2, planted=4, found=4
        )
    )
    assert few[-1] == "Verdict R against M: PASS (preliminary)" and any(
        "calibration is not valid" in x for x in few
    ), few
    assert not calibration_valid(9, 9) and calibration_valid(10, 8)


def ref_worst_case_checks() -> None:
    """Finding 8: the decision reads the worst case."""
    worst = {"findings": 110, "pairs": 100, "wrong": 2}
    lifted = decide(
        reference_rows("M", 1000) + reference_rows("R", 1000, worst=worst, **GOOD_REFS)
    )  # best case 0.90, worst case 180/220 = 0.82
    assert lifted[-1] == "Verdict R against M: PASS" and any(
        "worst case 0.82" in x and "best case 0.90" in x for x in lifted
    ), lifted
    worse = decide(
        reference_rows("M", 1000)
        + reference_rows("R", 1000, worst={"findings": 130, "pairs": 100, "wrong": 2}, **GOOD_REFS)
    )  # 180/260 = 0.69
    assert worse[-1] == "Verdict R against M: FAIL" and any(
        "coverage" in x and "FAILED" in x for x in worse
    ), worse
    unjudged_pairs = decide(
        reference_rows("M", 1000)
        + reference_rows("R", 1000, worst={"findings": 100, "pairs": 110, "wrong": 12}, **GOOD_REFS)
    )
    assert any(
        "wrong references" in x and "FAILED" in x and "worst case" in x for x in unjudged_pairs
    ), unjudged_pairs
    unreliable = decide(
        reference_rows("M", 1000) + reference_rows("R", 1000, unreliable=True, **GOOD_REFS)
    )
    assert unreliable[-1].endswith("(preliminary)"), unreliable
    assert (
        reference_conditions([{"tokens_shown": 1}], [{"tokens_shown": 1}]) == []
    )  # no judgment: no condition


def backfill_rule_checks() -> None:
    """The backfill trial's rule."""
    ok = {
        "wrong": 0,
        "wrong_worst": 1,
        "sample": 100,
        "applied": {"a": 30, "b": 20},
        "findings": 50,
        "findings_worst": 50,
        "covered": 45,
        "findings_new": 40,
        "findings_new_worst": 40,
        "covered_new": 30,
        "none": 10,
        "units_sent": 60,
        "preserved": True,
        "restored": True,
        "planted": 20,
        "found": 18,
        "unreliable": 0,
    }
    assert (
        decide_backfill(ok)[-1] == "Verdict backfill: PASS"
        and sum("PASS" in x for x in decide_backfill(ok)) == EIGHT
    )
    failing = decide_backfill({**ok, "wrong_worst": 2})
    assert failing[-1] == "Verdict backfill: FAIL" and any(
        "FAILED" in x and "wrong" in x for x in failing
    ), failing
    assert decide_backfill({**ok, "sample": 40})[-1] == "Verdict backfill: PASS (preliminary)"
    assert any("sample holds 40 pairs" in x for x in decide_backfill({**ok, "sample": 40}))
    assert decide_backfill({**ok, "found": 10})[-1] == "Verdict backfill: PASS (preliminary)"
    assert (
        decide_backfill({**ok, "planted": 9, "found": 9})[-1]
        == "Verdict backfill: PASS (preliminary)"
    )
    for key, value in (("none", 20), ("preserved", False), ("restored", False)):
        assert decide_backfill({**ok, key: value})[-1] == "Verdict backfill: FAIL", key
    # finding 4: nothing applied, an empty sample or a synthesis without a new reference fails before the rest is read
    for bad_ in (
        {"applied": {"a": 30, "b": 0}},
        {"applied": {"a": 0, "b": 0}},
        {"applied": {}},
        {"sample": 0},
    ):
        out = decide_backfill({**ok, **bad_})
        assert (
            out[-1].startswith("Verdict backfill: FAIL")
            and "not read" in out[-1]
            and any("FAILED" in x for x in out)
        ), out
        assert not any("coverage" in x or "`none`" in x or "wrong references" in x for x in out), (
            out
        )
    # coverage is reported twice; BACKFILL_MIN_COVERAGE binds the findings that had no reference before
    carried = {
        **ok,
        "covered": 50,
        "covered_new": 20,
    }  # every finding covered, but only 20/40 = 0.50 of the new ones
    out = decide_backfill(carried)
    assert out[-1] == "Verdict backfill: FAIL" and any(
        "had no reference before" in x and "FAILED" in x for x in out
    ), out
    assert any("coverage of all findings" in x and "reported, not decided" in x for x in out), out
    # finding 8: unjudged units are findings without a reference in the denominator
    assert (
        decide_backfill({**ok, "findings_new_worst": 60})[-1] == "Verdict backfill: FAIL"
    )  # 30/60 = 0.50
    assert (
        decide_backfill({**ok, "findings_new_worst": 0, "findings_new": 0, "covered_new": 0})[-1]
        == "Verdict backfill: FAIL"
    )


def backfill_table_checks() -> None:
    """The backfill table, with a column the harness does not know and blank cells in the total row."""
    rows_, total = parse_backfill_table(TABLE)
    assert total is not None
    assert (
        [r["synthesis"] for r in rows_] == ["a", "b"]
        and rows_[0]["none"] == "8"
        and rows_[0]["extra"] == "1"
    ), rows_
    assert (
        total["units"] == "50"
        and total["none"] == "12"
        and total["applied"] == "31"
        and total["extra"] == "1"
    ), total
    assert not total["mem check"] and total["cost USD"] == "0.170" and not total["status"], total
    assert parse_backfill_table("no table here") == ([], None)
    assert (
        snapshot_files is not None and exactly(number("0.170"), 0.17) and exactly(number(""), 0.0)
    )


def ref_checks(root: Path) -> None:
    """No model: the reference judge's brief, report parser, scoring, planting and calibration, the conditions of R and
    the backfill trial's rule and table parser, all on invented text."""
    parsed = ref_parser_checks()
    store, path, verdicts = ref_scoring_checks(root, parsed)
    every, kinds = ref_planting_checks(path, verdicts)
    ref_planting_limit_checks(path, every, kinds)
    ref_calibration_checks(root, store, every, kinds)
    ref_quota_checks()
    ref_condition_checks()
    ref_worst_case_checks()
    backfill_rule_checks()
    backfill_table_checks()


def fake_session(
    calls: list,
    cost: float = 0.01,
    usage: bool = True,
    report: str = "COUNTS: checked=10 unsupported=1 used=1 unused=0\n",
):
    """A stand-in for `run_session`: records what it was called with and answers like a session with a cost."""

    def stub(*args, **kw):
        model, work, log = args[1], args[3], kw["log"]
        calls.append(dict(model=model, work=work, **kw))
        store = work.parent / "store"
        if "writer" in log.name and (store / "syntheses").is_dir():
            (store / "syntheses" / "human-memory.md").write_text(DEMO)
        (work / "judge-report.md").write_text(report)
        return {
            "model_usage": {"claude-haiku-4-5": {"costUSD": cost}} if usage else {},
            "has_result": True,
            "error": "",
            "cost": cost if usage else 0.0,
            "wall": 1.0,
            "writes": 0,
            "write_errors": 0,
            "denied": False,
            "tool_errors": 0,
            "answer": "",
        }

    return stub


def budget_cap_checks() -> None:
    """The cap: reserves are taken under the lock and swapped for the real cost."""
    b = Budget(2.0)
    assert (
        b.start("pipeline")
        and b.start("pipeline")
        and not b.start("pipeline")
        and exactly(b.reserved, 2.0)
    )
    b.finish("pipeline", 0.2)
    assert (
        (b.spent, b.reserved) == (0.2, 1.0)
        and b.start("judge")
        and not b.hold(0.6)
        and b.start("ref")
    )  # 0.2 + 1.0 + 0.3 + 0.5 = 2.0
    assert (
        not b.start("calibration")
        and Budget(1.2).start("calibration")
        and not Budget(1.2).start("control")
    )  # control 1.3
    assert assume_cap([{"cost": 0.0}]) == [{"cost": SESSION_CAP_USD, "cost_assumed": True}]
    assert assume_cap([{"cost": 0.2}]) == [{"cost": 0.2}] and exactly(SESSION_CAP_USD, 1.5)
    assert (RESERVE["pipeline"], RESERVE["judge"], RESERVE["ref"], RESERVE["calibration"]) == (
        1.0,
        0.3,
        0.5,
        0.5,
    )


def pipeline_cap_checks(root: Path, env: dict) -> None:
    """Every session of a pipeline gets the cap; a session with no cost is counted at it; the lean loop gets `left`."""
    calls: list = []
    seen: dict = {}

    def loop(*_args, **kw):
        left = kw.get("left")
        seen["left"] = left() if left else None
        return {"arm_count": None, "why": "", "fixes": 0, "deleted": 0, "scope_violations": []}

    original, original_loop, original_refs = (
        globals()["run_session"],
        sp.lean_loop,
        globals()["reference_backfill"],
    )
    globals()["run_session"], sp.lean_loop = fake_session(calls, cost=0.0, usage=False), loop
    globals()["reference_backfill"] = lambda *a: {
        "status": "nothing due",
        "proposed": 0,
        "applied": 0,
        "refused": 0,
        "none": 0,
        "cost": 0.0,
        "wall": 0.0,
        "ran": False,
    }  # tested apart (reference_checks)
    try:
        row = one_pipeline(
            "claude",
            root / "cap",
            env,
            "human-memory",
            arm="R",
            run=1,
            keep=False,
            judge_model="haiku",
            ref_judge=False,
            quota=None,
            budget=Budget(10.0),
        )
        assert calls and all(c["max_budget"] == SESSION_CAP_USD for c in calls), calls
        assert seen["left"] == SESSION_CAP_USD, seen
        assert row["cost_assumed"] >= TWO and row["pipeline_cost"] == SESSION_CAP_USD, (
            row
        )  # writer and judge had no cost
        # the budget decides before each step: no pipeline, then no judge
        calls.clear()
        none = one_pipeline(
            "claude",
            root / "cap",
            env,
            "human-memory",
            arm="R",
            run=1,
            keep=False,
            judge_model="haiku",
            ref_judge=False,
            quota=None,
            budget=Budget(0.9),
        )
        assert (
            not calls
            and not none["valid"]
            and none["budget_lost"] == ["pipeline"]
            and "not started: budget" in none["why"]
        ), none
        short = Budget(1.2)
        no_judge = one_pipeline(
            "claude",
            root / "cap",
            env,
            "human-memory",
            arm="R",
            run=1,
            keep=False,
            judge_model="haiku",
            ref_judge=False,
            quota=None,
            budget=short,
        )
        assert no_judge["budget_lost"] == ["judge"] and not no_judge["valid"] and len(calls) == 1, (
            no_judge,
            calls,
        )  # the writer only
        assert exactly(short.reserved, 0.0) and short.spent == SESSION_CAP_USD
        out = decide([no_judge, none])
        assert (
            out[0]
            == "rows lost to the budget (a step was not started, not valid for the decision): 2"
        ), out
    finally:
        globals()["run_session"], sp.lean_loop, globals()["reference_backfill"] = (
            original,
            original_loop,
            original_refs,
        )


CONTROL_TOPIC = "demo"


@dataclass
class ControlFixture:
    """What the arm M checks share: the work root, the environment, the control and the stand-ins' records."""

    root: Path
    env: dict
    control: dict
    ran: dict
    calls: list
    fake_control: Callable[..., subprocess.CompletedProcess]


def fake_control_run(root: Path, ran: dict) -> Callable[..., subprocess.CompletedProcess]:
    """A stand-in for `run_control`: main's own harness leaves its row, its pipeline file and a store copy."""
    topic = CONTROL_TOPIC

    def fake_control(cmd, env_, timeout):
        ran.update(cmd=cmd, env=env_)
        work = Path(cmd[cmd.index("--work") + 1])
        main_base = work / "runs" / f"{topic}-M-1"
        shutil.copytree(root / "demo-store", main_base / "store")
        (main_base / "work").mkdir(parents=True)
        (main_base / "settings.json").write_text("{}")
        done = lambda role, cost: {
            "role": role,
            "model": "haiku",
            "costs": {"haiku": cost},
            "cost": cost,
            "wall": 1.0,
            "writes": 0,
            "write_errors": 0,
            "denied": False,
            "tool_errors": 0,
            "ok": True,
        }
        (main_base / "pipeline.json").write_text(
            json.dumps({
                "sessions": [done("writer", 0.3), done("checker", 0.12), done("judge", 0.17)],
                "why": "",
                "denominator": ["knowledge/x/a.md"],
                "arm_count": None,
                "fixes": 1,
                "deleted": 0,
                "scope_violations": [],
            })
        )
        (work / STATE).write_text(
            json.dumps([
                {
                    "topic": topic,
                    "arm": "M",
                    "run": 1,
                    "valid": True,
                    "cost": 0.59,
                    "pipeline_cost": 0.42,
                    "judge_cost": 0.17,
                }
            ])
        )
        return subprocess.CompletedProcess(cmd, 0, "main's table\n", "")

    return fake_control


def control_row_cost_checks(fx: ControlFixture) -> None:
    """Arm M: main's own harness makes the row; the budget pays it once and the control folder goes without `--keep`."""
    root, env, control, ran, calls = fx.root, fx.env, fx.control, fx.ran, fx.calls
    topic = CONTROL_TOPIC
    (root / "demo-store" / "syntheses" / "demo.md").write_text(DEMO)
    paid = Budget(5.0)
    row = one_row(
        "claude",
        root / "m",
        env,
        topic,
        arm="M",
        run=1,
        keep=False,
        judge_model="haiku",
        ref_judge=False,
        quota=None,
        budget=paid,
        control=control,
    )
    work = root / "m" / "control" / f"{topic}-M-1"
    assert ran["cmd"] == [
        "python3",
        str(control["path"] / "plugins/memory/evals/synthesis/run_trials.py"),
        "--arm",
        "M",
        "--topic",
        topic,
        "--runs",
        "1",
        "--keep",
        "--work",
        str(work),
        "--budget",
        "1.3",
        "--claude",
        "claude",
    ], ran["cmd"]
    assert row["arm"] == "M" and row["valid"] and row["control_commit"] == "abc1234", row
    assert (
        exactly(row["pipeline_cost"], 0.42)
        and exactly(row["control_judge_cost"], 0.17)
        and exactly(row["judge_cost"], 0.01)
    ), row
    assert [x["role"] for x in row["sessions"]] == ["writer", "checker", "judge"] and len(
        calls
    ) == 1, row["sessions"]  # main's judge dropped
    assert (
        abs(row_cost(row) - 0.60) < COST_TOLERANCE
        and abs(paid.spent - 0.60) < COST_TOLERANCE
        and exactly(paid.reserved, 0.0)
    ), (row, paid.spent)
    assert not work.exists(), "the control folder is removed without --keep"
    assert ran["env"].get("XDG_DATA_HOME") == os.environ.get("XDG_DATA_HOME"), (
        "main's harness reads the real store itself"
    )


def control_row_edge_checks(fx: ControlFixture) -> None:
    """Arm M: the copy of the real store loses its references before judging, a dying control run leaves an invalid row and a small budget starts nothing."""
    root, env, control, ran, calls = fx.root, fx.env, fx.control, fx.ran, fx.calls
    topic = CONTROL_TOPIC
    # the references the copy of the real store carries are dropped before judging
    kept = root / "m2"
    one_row(
        "claude",
        kept,
        env,
        topic,
        arm="M",
        run=1,
        keep=True,
        judge_model="haiku",
        ref_judge=False,
        quota=None,
        budget=None,
        control=control,
    )
    stored = (
        kept
        / "control"
        / f"{topic}-M-1"
        / "runs"
        / f"{topic}-M-1"
        / "store"
        / "syntheses"
        / "demo.md"
    ).read_text()
    assert stored != DEMO and "](../literature/b.md)" not in stored.split("## Beta")[0], stored

    # a control run that dies leaves an invalid row; a budget too small starts nothing
    def dies(cmd, env_, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    globals()["run_control"] = dies
    dead = one_row(
        "claude",
        root / "m3",
        env,
        topic,
        arm="M",
        run=1,
        keep=False,
        judge_model="haiku",
        ref_judge=False,
        quota=None,
        budget=Budget(5.0),
        control=control,
    )
    assert not dead["valid"] and "control run failed" in dead["why"], dead
    calls.clear()
    globals()["run_control"] = fx.fake_control
    ran.clear()
    poor = one_row(
        "claude",
        root / "m4",
        env,
        topic,
        arm="M",
        run=1,
        keep=False,
        judge_model="haiku",
        ref_judge=False,
        quota=None,
        budget=Budget(1.0),
        control=control,
    )
    assert (
        not ran and not calls and poor["budget_lost"] == ["control pipeline"] and not poor["valid"]
    ), poor


def control_row_checks(root: Path, env: dict) -> None:
    """Arm M: main's own harness makes the row; this file's pipeline is never called."""
    control = {"path": root / "no-main-worktree", "commit": "abc1234"}
    ran: dict = {}
    calls: list = []
    fx = ControlFixture(root, env, control, ran, calls, fake_control_run(root, ran))

    def no_pipeline(*a, **kw):
        raise AssertionError("arm M must not run this file's pipeline")

    originals = (globals()["run_control"], globals()["one_pipeline"], globals()["run_session"])
    globals()["run_control"], globals()["one_pipeline"], globals()["run_session"] = (
        fx.fake_control,
        no_pipeline,
        fake_session(calls),
    )
    try:
        control_row_cost_checks(fx)
        control_row_edge_checks(fx)
    finally:
        globals()["run_control"], globals()["one_pipeline"], globals()["run_session"] = originals


def main_worktree_checks(root: Path) -> None:
    """The worktree of `main`: created when missing, reused at main's tip, refused when stale; stubbed, never created here."""
    gitcalls: list = []

    def fake_git(head):
        answers = {
            ("rev-parse", "main"): "a" * 40,
            ("rev-parse", "--short", "main"): "aaaaaaa",
            ("rev-parse", "HEAD"): head,
        }

        def run(*args, cwd=None):
            gitcalls.append(args)
            return answers.get(args, "")

        return run

    wt = root / "worktree"
    wt.mkdir()
    try:
        ensure_main_worktree(wt, fake_git("b" * 40))
        raise AssertionError("a stale worktree was accepted")
    except RuntimeError as exc:
        assert "bbbbbbb" in str(exc) and "aaaaaaa" in str(exc) and "worktree remove" in str(exc), (
            exc
        )
    gitcalls.clear()
    assert ensure_main_worktree(wt, fake_git("a" * 40)) == {"path": wt, "commit": "aaaaaaa"}
    assert not any(c[0] == "worktree" for c in gitcalls), gitcalls
    gitcalls.clear()
    assert ensure_main_worktree(root / "absent", fake_git("a" * 40))["commit"] == "aaaaaaa"
    assert ("worktree", "add", "--detach", str(root / "absent"), "main") in gitcalls, gitcalls
    assert MAIN_WORKTREE == trial_env.TARGET / "main-worktree"


def backfill_trial_checks(root: Path, env: dict) -> None:
    """The backfill trial: a work folder that holds one is refused; a failed step still writes the results."""
    bf = root / "bf"
    (bf / "backfill").mkdir(parents=True)
    calls: list = []
    originals = (globals()["run_session"], globals()["run_mem_synthesize"])
    globals()["run_session"] = fake_session(calls)
    try:
        assert (
            backfill_trial(
                "claude",
                bf,
                env,
                ["human-memory"],
                budget_usd=10.0,
                judge_model="haiku",
                results_dir=bf,
            )
            == THREE
            and not calls
        )
        (root / "bf2" / "data").mkdir(parents=True)
        (root / "bf2" / "data" / "backfill-done.json").write_text("{}")
        assert (
            backfill_trial(
                "claude",
                root / "bf2",
                env,
                ["human-memory"],
                budget_usd=10.0,
                judge_model="haiku",
                results_dir=bf,
            )
            == THREE
        )
        assert (
            backfill_trial(
                "claude",
                root / "bf3",
                env,
                ["human-memory"],
                budget_usd=1.0,
                judge_model="haiku",
                results_dir=bf,
            )
            == TWO
        )  # nothing left for the backfill

        def timeout(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)

        globals()["run_mem_synthesize"] = timeout
        fresh = root / "bf4"
        fresh.mkdir()
        assert (
            backfill_trial(
                "claude",
                fresh,
                env,
                ["human-memory"],
                budget_usd=10.0,
                judge_model="haiku",
                results_dir=bf,
            )
            == 1
        )
        written = sorted(bf.glob("backfill-trial-*.json"))
        assert len(written) == 1, written
        result = json.loads(written[0].read_text())
        assert (
            result["failed_step"] == "mem-synthesize --backfill"
            and result["decision"][-1] == "Verdict backfill: FAILED: mem-synthesize --backfill"
        ), result
        assert result["backfill_cost"] is None and result["spent"] >= NINE_USD, (
            result
        )  # unknown cost: counted at the backfill's cap
        assert all(c["max_budget"] == SESSION_CAP_USD for c in calls), calls
        assert (
            backfill_trial(
                "claude",
                fresh,
                env,
                ["human-memory"],
                budget_usd=10.0,
                judge_model="haiku",
                results_dir=bf,
            )
            == THREE
        )  # the second run in it
    finally:
        globals()["run_session"], globals()["run_mem_synthesize"] = originals


def budget_checks(root: Path, env: dict) -> None:
    """No model: the budget as a cap (finding 5), arm M from `main`'s own harness (finding 1), the backfill trial's
    refusal of a used work folder and its results after a failed step (findings 6 and 7)."""
    budget_cap_checks()
    pipeline_cap_checks(root, env)
    control_row_checks(root, env)
    main_worktree_checks(root)
    backfill_trial_checks(root, env)


@dataclass
class RefStepFixture:
    """The stand-ins for arm R's reference step: what ran and in which order, and the loop's answer."""

    root: Path
    env: dict
    order: list
    ran: list
    arm_now: list
    loop_ok: dict
    state: dict
    inner: Callable[..., dict]

    def session(self, *args, **kw):
        self.order.append("judge" if "judge" in kw["log"].name else "writer")
        return self.inner(*args, **kw)

    def backfill_stub(self, status, cost=0.05):
        def stub(claude, base, env_, topic):
            self.order.append("backfill")
            self.ran.append((self.arm_now[0], topic))
            with (base / "store" / "syntheses" / f"{topic}.md").open("a") as f:
                f.write("\nFive more words after references.\n")
            return {
                "status": status,
                "proposed": 3,
                "applied": 2,
                "refused": 1,
                "none": 4,
                "cost": cost,
                "wall": 1.0,
                "ran": True,
            }

        return stub

    def row_checks(self):
        row = one_pipeline(
            "claude",
            self.root / "refs",
            self.env,
            "human-memory",
            arm="R",
            run=1,
            keep=False,
            judge_model="haiku",
        )
        assert self.ran == [("R", "human-memory")] and self.order == [
            "writer",
            "backfill",
            "judge",
        ], (
            self.ran,
            self.order,
        )
        assert row["valid"] and (
            row["backfill"]["applied"],
            row["backfill"]["refused"],
            row["backfill"]["none"],
        ) == (2, 1, 4), row
        assert (
            abs(row["pipeline_cost"] - 0.06) < COST_TOLERANCE
            and row["sessions"][-2]["role"] == "backfill"
        ), row  # writer 0.01 + 0.05
        assert row["words"] == len(DEMO.split()) + 5, row[
            "words"
        ]  # measured on the text after the step

    def other_arm_checks(self):
        for arm in ("S", "L"):  # only R runs the step
            self.ran.clear()
            self.arm_now[0] = arm
            assert (
                one_pipeline(
                    "claude",
                    self.root / "refs",
                    self.env,
                    "human-memory",
                    arm=arm,
                    run=1,
                    keep=False,
                    judge_model="haiku",
                )["backfill"]
                is None
                and not self.ran
            )

    def failure_checks(self):
        self.order.clear()
        failed = None
        globals()["reference_backfill"] = self.backfill_stub("failed: refs: boom", cost=0.02)
        self.arm_now[0] = "R"
        failed = one_pipeline(
            "claude",
            self.root / "refs",
            self.env,
            "human-memory",
            arm="R",
            run=1,
            keep=False,
            judge_model="haiku",
        )
        assert (
            not failed["valid"] and "reference backfill failed: failed: refs: boom" in failed["why"]
        ), failed
        self.ran.clear()
        self.state["loop"] = {
            **self.loop_ok,
            "why": "the checker failed",
        }  # a failed loop gets no step
        one_pipeline(
            "claude",
            self.root / "refs",
            self.env,
            "human-memory",
            arm="R",
            run=1,
            keep=False,
            judge_model="haiku",
        )
        assert not self.ran


def reference_step_checks(root: Path, env: dict) -> None:
    """Arm R's reference step: once, after the loop, before the judges; a failure invalidates the row; the other arms
    and a failed loop run no step."""
    loop_ok = {"arm_count": None, "why": "", "fixes": 0, "deleted": 0, "scope_violations": []}
    fx = RefStepFixture(
        root=root,
        env=env,
        order=[],
        ran=[],
        arm_now=["R"],
        loop_ok=loop_ok,
        state={"loop": loop_ok},
        inner=fake_session([], cost=0.01),
    )
    originals = globals()["run_session"], sp.lean_loop, globals()["reference_backfill"]
    globals()["run_session"], sp.lean_loop = fx.session, lambda *a, **kw: fx.state["loop"]
    try:
        globals()["reference_backfill"] = fx.backfill_stub("ok")
        fx.row_checks()
        fx.other_arm_checks()
        fx.failure_checks()
    finally:
        globals()["run_session"], sp.lean_loop, globals()["reference_backfill"] = originals


def control_result_rows(arm, rates, cost, **extra):
    ref = {
        "findings": 100,
        "covered": 90,
        "pairs": 100,
        "wrong": 1,
        "findings_worst": 100,
        "pairs_worst": 100,
        "wrong_worst": 1,
        "unreliable": False,
        "cal": {"planted": 20, "found": 20, "weak_planted": 0, "weak_found": 0},
    }
    return [
        dict(
            topic="human-memory",
            arm=arm,
            run=n,
            valid=True,
            checked=100,
            unsupported=rate,
            used=6,
            denominator=6,
            words=3000,
            mem_check=0,
            cost=cost + 0.4,
            pipeline_cost=cost,
            judge_cost=0.4,
            tokens_shown=1000,
            tokens_stored=2000,
            ref=ref if arm == "R" else None,
            **extra,
        )
        for n, rate in enumerate(rates, 1)
    ]


def git_diff_stub(gits: list, differing: set):
    """A stand-in for `git`: `rev-parse` answers a short hash, `diff --quiet` fails for the commits in `differing`."""

    def run_git(*args, cwd=None):
        gits.append(args)
        if args[0] == "diff":
            if args[2] in differing:
                raise subprocess.CalledProcessError(1, args)
            return ""
        return "aaaaaaa"

    return run_git


def control_results_checks(root: Path) -> tuple[Path, list]:
    """`--control-results`: the rows load and the decision is the one fresh rows give; return the file and the R rows."""
    m_rows, r_rows = (
        control_result_rows("M", [5, 6], 0.4, control_commit="oldc0de"),
        control_result_rows("R", [6, 7], 0.45),
    )
    results = root / "earlier-results.json"
    results.write_text(
        json.dumps({
            "rows": control_result_rows("S", [2], 1.0) + m_rows + r_rows,
            "control_commit": "oldc0de",
        })
    )
    gits: list = []

    loaded = load_control_results(results, git_diff_stub(gits, set()))
    assert ("diff", "--quiet", "oldc0de", "main", "--", "plugins/memory") in gits, (
        gits
    )  # only plugins/memory is compared
    assert (loaded["recorded"], loaded["main"], loaded["file"]) == (
        "oldc0de",
        "aaaaaaa",
        str(results),
    ), loaded
    assert [r["arm"] for r in loaded["rows"]] == ["M", "M"] and all(
        r["reused_from"] == str(results) for r in loaded["rows"]
    )
    assert decide(loaded["rows"] + r_rows) == decide(m_rows + r_rows) and decide(m_rows + r_rows)[
        -1
    ].startswith("Verdict R against M")
    return results, r_rows


def control_results_refusal_checks(results: Path, r_rows: list) -> None:
    """`--control-results` refuses changed control code and a file without a control commit."""
    try:
        load_control_results(results, git_diff_stub([], {"oldc0de"}))
        raise AssertionError("a results file with changed control code was accepted")
    except RuntimeError as exc:
        assert "oldc0de" in str(exc) and "plugins/memory differs" in str(exc), exc
    assert (
        load_control_results(results, git_diff_stub([], {"another"}))["recorded"] == "oldc0de"
    )  # it differs elsewhere only
    results.write_text(json.dumps({"rows": r_rows, "control_commit": None}), encoding="utf-8")
    try:
        load_control_results(results, git_diff_stub([], set()))
        raise AssertionError("a file without a control commit was accepted")
    except RuntimeError as exc:
        assert "control_commit" in str(exc), exc


def arm_m_control_results_check(results: Path) -> None:
    """`--arm M` with `--control-results` is refused."""
    old_argv = sys.argv
    sys.argv = [
        "run_trials.py",
        "--claude",
        "claude",
        "--arm",
        "M",
        "--control-results",
        str(results),
    ]
    try:
        main()
        raise AssertionError("--arm M with --control-results was accepted")
    except SystemExit as exc:
        assert exc.code == TWO
    finally:
        sys.argv = old_argv


def reference_checks(root: Path, env: dict) -> None:
    """No model: arm R's reference step (once, after the loop, before the judges, a failure invalidates the row) and
    `--control-results` (the rows load, the decision is the one fresh rows give, the commit check)."""
    reference_step_checks(root, env)
    results, r_rows = control_results_checks(root)
    control_results_refusal_checks(results, r_rows)
    arm_m_control_results_check(results)


def prepared_copy_checks(root: Path, env: dict, source: Path, real: Path) -> None:
    """Each topic: the copy, the deletion of its synthesis, the denominator and `mem synthesis new` on the copy."""
    for topic in TOPICS:
        store = root / topic
        shutil.copytree(source, store)
        assert (
            store.resolve().is_relative_to(trial_env.TARGET) and store.resolve() != real.resolve()
        )
        assert (store / "syntheses" / f"{topic}.md").is_file(), f"no synthesis of {topic} to delete"
        denominator = prepare_store(store, env, topic)
        assert not (store / "syntheses" / f"{topic}.md").exists()
        assert DENOMINATOR_MIN <= len(denominator) <= DENOMINATOR_MAX, (
            f"{topic}: denominator {len(denominator)}"
        )
        for rel in denominator:
            assert (store / rel).is_file() and front_part_of((store / rel).read_text()) is None, rel
            assert "part_of_hash" not in (store / rel).read_text(), rel
        assert mem(store, env, "check").returncode == 0, (
            f"{topic}: mem check fails on the prepared copy"
        )
        made = mem(
            store,
            env,
            "synthesis",
            "new",
            "--title",
            f"{topic} check",
            "--topics",
            topic,
            "--slug",
            topic,
            "--summary-file",
            "-",
            stdin="A summary of the topic for the self-check.\n",
        )
        assert made.returncode == 0, (
            f"{topic}: mem synthesis new failed:\n{made.stdout}{made.stderr}"
        )
        print(f"{topic}: denominator {len(denominator)}, synthesis new ok")
        shutil.rmtree(store)


def brief_placeholder_checks() -> None:
    """Every placeholder of a brief is filled and no brief holds a private path."""
    for name in ("writer", "checker", "fixer"):
        brief(
            name, TOPIC="t", SLUG="t", STORE="s", WORK_DIR="w", REPORT_FILE="r"
        )  # every placeholder is filled
        raw = ((HERE if name == "writer" else sp.BRIEFS) / f"{name}-brief.md").read_text()
        assert "/home/" not in raw and "/tmp/" not in raw and "~/" not in raw, (
            f"{name}-brief.md has a private path"
        )


def report_parser_checks(root: Path) -> dict:
    """The judge's report: its notes, its own format with one line per claim, a heading read as its handle, a report
    with no counts; return the parsed second report."""
    sample = root / "r.md"
    sample.write_text(
        "1. x\nNOTE: ../knowledge/a/b.md used\nNOTE: ../literature/c.md unused\n"
        "COUNTS: checked=40 unsupported=3 used=1 unused=1\n"
    )
    got = parse_report(sample)
    assert got is not None
    assert (
        got["notes"] == {"knowledge/a/b.md": "used", "../literature/c.md": "unused"}
        and got["claims"] == []
    ), got
    assert (got["checked"], got["unsupported"], got["parts"]) == (40, 3, []), got
    # the checker's own format: one line per claim, then PARTS and COUNTS
    sample.write_text(
        "spaced-study | Spacing helps in every setting studied | absolute | ../knowledge/a/b.md | "
        "Spacing helped in the pooled studies.\n"
        "testing | Practice testing beat rereading by | figure-origin | ../knowledge/a/c.md | \n"
        "PARTS: spaced-study, testing\nCOUNTS: checked=30 unsupported=2\n"
    )
    first = parse_report(sample)
    assert first is not None
    assert (first["checked"], first["unsupported"], first["parts"]) == (
        30,
        2,
        ["spaced-study", "testing"],
    ), first
    assert [c["kind"] for c in first["claims"]] == ["absolute", "figure-origin"], first
    assert (
        first["claims"][0]["fix"] == "Spacing helped in the pooled studies."
        and not first["claims"][1]["fix"]
    ), first
    sample.write_text(
        "Spaced study | A sentence of seven words or so here | overstated | n | x\n"
        "PARTS: s:t#spaced-study, Spaced study\nCOUNTS: checked=3 unsupported=1\n"
    )
    reread = parse_report(sample)
    assert reread is not None
    assert reread["parts"] == ["spaced-study"], reread  # a heading is read as its handle
    sample.write_text("COUNTS: checked=30 unsupported=0\n")
    clean = parse_report(sample)
    assert clean is not None
    assert clean["unsupported"] == 0 and clean["claims"] == [] and clean["parts"] == [], clean
    sample.write_text("no counts here\n")
    assert parse_report(sample) is None and parse_report(root / "missing.md") is None
    return first


def scoped_check_checks(first: dict) -> None:
    """The scoped second check, the delete-only step and the byte-equal guard."""
    # scoped second check: the fixer's report goes through {PARTS}; without one, the first report's claims do
    answer = "Parts edited: spaced-study. Sentences changed: Spacing helped in the pooled studies. 0 deleted."
    assert scope_text(first, answer) == answer
    assert "testing: Practice testing beat rereading by" in scope_text(first, "")
    fill = {"TOPIC": "t", "SLUG": "t", "STORE": "s", "WORK_DIR": "w", "REPORT_FILE": "r"}
    scoped = brief("checker", **fill, PARTS=scope_text(first, answer))
    assert answer in scoped and "{PARTS}" not in scoped
    assert NOT_GIVEN in brief("checker", **fill)
    # delete-only step and the byte-equal guard
    old_text = "---\ntitle: x\n---\n\n## Summary\n\nS.\n\n## Spaced study\n\nA. B.\n\n## Testing\n\nC. D.\n"
    assert list(split_parts(old_text)) == ["summary", "spaced-study", "testing"]
    assert changed_outside(old_text, old_text.replace("A. B.", "A."), ["spaced-study"]) == []
    assert changed_outside(
        old_text, old_text.replace("A. B.", "A.").replace("D.", "E."), ["spaced-study"]
    ) == ["testing"]
    assert changed_outside(old_text, old_text.replace("title: x", "title: y"), []) == [], (
        "front matter is not a part"
    )
    assert "delete only" in brief("fixer", **fill) + DELETE_ONLY
    assert len(first["claims"]) == first["unsupported"] == TWO  # what the row records as deleted


def fake_row(arm, cost, unsupported, checked=60):
    return {
        "topic": "human-memory",
        "arm": arm,
        "run": 1,
        "valid": True,
        "checked": checked,
        "unsupported": unsupported,
        "used": 6,
        "denominator": 6,
        "words": 3000,
        "mem_check": 0,
        "cost": cost + 0.4,
        "pipeline_cost": cost,
        "judge_cost": 0.4,
    }


def decision_checks() -> None:
    """The verdict among the arms S, L and M."""
    verdict = decide([fake_row("S", 1.0, 2), fake_row("L", 0.7, 3), fake_row("M", 0.4, 3)])
    assert "preliminary (1 run per topic)" in " ".join(verdict) and verdict[-1].startswith(
        "Verdict: ADOPT arm M"
    ), verdict
    assert decide([fake_row("S", 1.0, 2), fake_row("L", 0.7, 3), fake_row("M", 0.5, 6)])[
        -1
    ].startswith("Verdict: ADOPT arm L")
    assert decide([fake_row("S", 1.0, 2), fake_row("L", 0.9, 3), fake_row("M", 0.85, 3)])[
        -1
    ].startswith("Verdict: KEEP")
    assert decide([fake_row("S", 1.0, 2), fake_row("M", 0.4, 3, checked=30)])[-1].startswith(
        "Verdict: KEEP"
    )


def self_check() -> int:
    """No model: the copy, the deletion, the detachment and `mem synthesis new`; the owner's store is untouched."""
    real = real_store()
    before = trial_env._snapshot(real)
    root = trial_env.work_dir("mem-synthesis-check-")
    try:
        source = ensure_source()
        assert source.resolve().is_relative_to(trial_env.TARGET) and source != real
        assert not (source / ".git").exists() and not list(source.glob(".curation-log*")), (
            "history was copied"
        )
        env = trial_env.make_env(root)
        prepared_copy_checks(root, env, source, real)
        brief_placeholder_checks()
        scoped_check_checks(report_parser_checks(root))
        decision_checks()
        harness_checks(root, env)
        ref_checks(root)
        budget_checks(root, env)
        reference_checks(root, env)
        assert trial_env._snapshot(real) == before, "a file of the owner's store changed"
    finally:
        trial_env.clean(root)
    print("self-check passed")
    return 0


# --- main ----------------------------------------------------------------------------------------------------


class TrialRefusedError(Exception):
    """A refusal `main` already reported on stderr: it exits 2."""


@dataclass(frozen=True)
class RunContext:
    """What one `main` run shares: its arguments, work folder, environment, result rows and the worktree of `main`."""

    args: argparse.Namespace
    root: Path
    env: dict
    rows: list
    control: dict | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    )
    parser.add_argument("--self-check", action="store_true", help="no model: prove the fixture")
    parser.add_argument("--topic", action="append", default=[], help="topic id (repeatable)")
    parser.add_argument(
        "--arm",
        action="append",
        choices=ARMS,
        default=[],
        help="default: S, L and M; R is M's models with the current texts",
    )
    parser.add_argument(
        "--judge-model", default="haiku", help=f"the judge's model (always at --effort {CHEAP})"
    )
    parser.add_argument(
        "--control-results",
        type=Path,
        metavar="FILE",
        help="reuse the arm M rows of an earlier results file instead of running M (not paid again); "
        "refused unless plugins/memory is the same in `main` as at the commit the file records; "
        "do not combine with --arm M",
    )
    parser.add_argument(
        "--rejudge",
        type=Path,
        metavar="PIPELINE_DIR",
        help="judge the final synthesis of a kept pipeline folder (runs/<topic>-<arm>-<n> of an "
        "earlier --keep run) again, recorded as arm S, run 1; needs --work",
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument(
        "--budget",
        type=float,
        default=10.0,
        help=f"USD, a cap on everything this command starts: a pipeline, judge, reference judgment or "
        f"calibration starts only when the cost so far + the reserve of the work in flight + its own "
        f"reserve (pipeline {RESERVE['pipeline']}, judge {RESERVE['judge']}, reference judgment "
        f"{RESERVE['ref']}, calibration {RESERVE['calibration']}; arm M's control run "
        f"{RESERVE['control']}) fits under it, else the row is `not started: budget` and not valid; "
        f"every session of this script gets --max-budget-usd {SESSION_CAP_USD}, and one without a "
        f"cost is counted at that cap. Arm M's sessions run in main's own harness and are not capped "
        f"by this script. With --backfill-trial it also pays the judgments: mem-synthesize gets what "
        f"is left after their reserve",
    )
    parser.add_argument("--work", type=Path, help="resume the work folder of an earlier run")
    parser.add_argument(
        "--keep", action="store_true", help="keep the work folder and the store copies at the end"
    )
    parser.add_argument(
        "--no-ref-judge",
        action="store_true",
        help="skip the reference judgment and its calibration",
    )
    parser.add_argument(
        "--backfill-trial",
        action="store_true",
        help="run mem-synthesize --backfill on a copy of the "
        "prepared store and check it (see the module docstring); refuses a --work that holds one",
    )
    parser.add_argument(
        "--synthesis",
        action="append",
        default=[],
        metavar="HANDLE",
        help="with --backfill-trial: a synthesis to backfill (repeatable; default: the default topics)",
    )
    return parser


def reused_control_rows(
    parser: argparse.ArgumentParser, args: argparse.Namespace, topics: list
) -> dict:
    """The arm M rows `--control-results` reuses, after the checks on the file; `TrialRefusedError` when it cannot
    serve."""
    if "M" in args.arm:
        parser.error("--control-results replaces arm M: do not give --arm M with it")
    try:
        reused = load_control_results(args.control_results.resolve())
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"--control-results refused: {exc}", file=sys.stderr)
        raise TrialRefusedError from exc
    reused["rows"] = [r for r in reused["rows"] if r["topic"] in topics and r["run"] <= args.runs]
    if not reused["rows"]:
        print(
            f"--control-results refused: {args.control_results} has no arm M row for these topics and runs",
            file=sys.stderr,
        )
        raise TrialRefusedError
    print(
        f"arm M: {len(reused['rows'])} rows reused from {reused['file']}, run at `main` {reused['recorded']}; `main` is "
        f"at {reused['main']} and plugins/memory is identical in both, so the control's code is unchanged",
        flush=True,
    )
    return reused


def backfill_main(args: argparse.Namespace) -> int:
    """`--backfill-trial`: the backfill trial on a work folder, cleaned unless kept or failed."""
    root = args.work.resolve() if args.work else trial_env.work_dir("mem-backfill-")
    code = backfill_trial(
        args.claude,
        root,
        trial_env.make_env(root),
        args.synthesis or list(DEFAULT_TOPICS),
        budget_usd=args.budget,
        judge_model=args.judge_model,
    )
    if code in {0, 2} and not args.keep:  # 2: refused before any session
        trial_env.clean(root)
    else:
        print(f"work folder kept: {root}")
    return code


def rejudge_main(
    parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path, env: dict, rows: list
) -> int:
    """`--rejudge`: judge a kept pipeline folder again and record the row as arm S, run 1."""
    if not args.work:
        parser.error("--rejudge needs --work (the folder whose state.json receives the row)")
    row = rejudge(args.claude, root, env, args.rejudge, args.judge_model)
    rows = [r for r in rows if (r["topic"], r["arm"], r["run"]) != (row["topic"], "S", 1)] + [row]
    (root / STATE).write_text(json.dumps(rows, indent=1))
    print(HEADER + "\n" + table_line(row))
    return 0


def control_worktree(todo: list) -> dict | None:
    """The worktree of `main` when arm M has a row to run; `TrialRefusedError` when it cannot be made."""
    if not any(a == "M" for _, a, _ in todo):
        return None
    try:
        control = ensure_main_worktree()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"arm M needs a worktree of `main`: {exc}", file=sys.stderr)
        raise TrialRefusedError from exc
    print(
        f"arm M: `main` at {control['commit']}, run by its own harness in {control['path']}",
        flush=True,
    )
    return control


def run_pipelines(ctx: RunContext, todo: list, skipped: int) -> None:
    """Run the pending rows on the pool, each under the budget the earlier rows left."""
    args, root, env, rows, control = ctx.args, ctx.root, ctx.env, ctx.rows, ctx.control
    state_file = root / STATE
    lock = threading.Lock()
    budget = Budget(
        args.budget, spent=sum(row_cost(r) for r in rows if not r.get("reused_from"))
    )  # reused rows were paid earlier
    ref_judge = not args.no_ref_judge
    quota = Quota(CALIBRATION_PLANTED, sum(1 for _, a, _ in todo if a == "R"))
    print(f"work folder: {root}; {len(todo)} pipelines to run, {skipped} already done", flush=True)
    print(HEADER, flush=True)
    ensure_source()

    def task(item):
        topic, arm, n = item
        row = one_row(
            args.claude,
            root,
            env,
            topic,
            arm=arm,
            run=n,
            keep=args.keep,
            judge_model=args.judge_model,
            ref_judge=ref_judge,
            quota=quota,
            budget=budget,
            control=control,
        )
        with lock:
            rows.append(row)
            state_file.write_text(json.dumps(rows, indent=1))
            print(table_line(row), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(task, todo))


def write_results(ctx: RunContext, reused: dict | None) -> int:
    """Print the decision and the costs, save the rows where the work folder's cleaning cannot lose them."""
    args, root, rows, control = ctx.args, ctx.root, ctx.rows, ctx.control
    decision = decide(rows)
    print("\n" + "\n".join(decision))
    print(f"references removed from the trial copy of the store: {references_removed()}")
    assumed = sum(r.get("cost_assumed", 0) for r in rows if not r.get("reused_from"))
    total = sum(row_cost(r) for r in rows if not r.get("reused_from"))
    print(
        f"total cost USD {total:.3f} of --budget {args.budget:.2f}, which covered pipelines, judges, reference judgments, "
        f"calibrations and arm M's control run with main's own judge ({sum(r.get('control_judge_cost', 0.0) for r in rows):.3f} "
        f"of it); {assumed} sessions returned no cost and are counted at their cap {SESSION_CAP_USD}"
    )
    # The rows outlive the work folder: a clean run must not lose its results (it did once).
    results = trial_env.TARGET / f"synthesis-results-{time.strftime('%Y%m%d-%H%M%S')}.json"
    results.write_text(
        json.dumps(
            {
                "rows": rows,
                "decision": decision,
                "source_refs_removed": references_removed(),
                "control_commit": control["commit"]
                if control
                else (reused["recorded"] if reused else None),
                "control_results": reused and {k: reused[k] for k in ("file", "recorded", "main")},
                "budget": args.budget,
                "total_cost": total,
                "sessions_assumed_at_cap": assumed,
            },
            indent=1,
        )
    )
    print(f"results: {results}")
    if all(r["valid"] for r in rows) and not args.keep:
        trial_env.clean(root)
    else:
        print(f"work folder kept (state.json has every row): {root}")
    return 0


def run_trials(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Every mode of `main` after the arguments are checked; `TrialRefusedError` for a refusal already reported."""
    topics, arms = args.topic or list(DEFAULT_TOPICS), args.arm or list(DEFAULT_ARMS)
    reused = None
    if args.control_results:
        reused = reused_control_rows(parser, args, topics)
        arms = [a for a in arms if a != "M"]
    if args.backfill_trial:
        return backfill_main(args)
    root = args.work.resolve() if args.work else trial_env.work_dir("mem-synthesis-")
    env = trial_env.make_env(root)
    state_file = root / STATE
    rows = json.loads(state_file.read_text()) if state_file.is_file() else []
    rows = [r for r in rows if r["valid"]]  # an invalid pipeline is rerun from scratch on resume
    if reused:
        rows = [r for r in rows if not r.get("reused_from")] + reused["rows"]
    if args.rejudge:
        return rejudge_main(parser, args, root, env, rows)
    done = {(r["topic"], r["arm"], r["run"]) for r in rows}
    todo = [
        (t, a, n)
        for t in topics
        for a in arms
        for n in range(1, args.runs + 1)
        if (t, a, n) not in done
    ]
    ctx = RunContext(args, root, env, rows, control_worktree(todo))
    run_pipelines(ctx, todo, len(done))
    return write_results(ctx, reused)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if not args.claude:
        parser.error("--claude is required (no claude binary found)")
    try:
        return run_trials(parser, args)
    except TrialRefusedError:
        return 2


if __name__ == "__main__":
    sys.exit(main())
