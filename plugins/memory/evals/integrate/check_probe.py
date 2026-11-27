#!/usr/bin/env python3
"""Probe of the check session of `mem-integrate` (plan 2026-11-27-memory-integrate-check-append, task 1).

Question: given fixed right and wrong placement rows, which does the check session accept? Only the check session is
run (place is not): the input is the production input, built with the engine's own `candidates`, `Row`, `check_input`
and `row_line`, and the session runs through `Job.ask`, so the shipped brief, settings and session command apply.
`--brief PATH` swaps the check brief for one run without touching the shipped file.

The row table below is fixed in code BEFORE any paid run; do not tune it afterwards (a tuned table measures nothing).
Superseded and disputed notes never reach check in production, so they are not rows. See README.md.

Usage: check_probe.py --self-check | --budget USD [--claude PATH] [--runs N] [--brief PATH] [--out DIR]
The paid run needs the owner's cap (`--budget`) and is never started by `--self-check`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
import run_trial
import trial_env
from core import jobs
from entry import integrate as engine
from integrate import plan
from integrate import state as run_state
from integrate.rows import Row, row_line

if TYPE_CHECKING:
    from collections.abc import Iterable

OUT_DEFAULT = trial_env.TARGET / "check-probe"
DEFAULT_RUNS = 2
CONTRA_PREFIX = "probe-contra-"
FAKE_SESSION_COST = 0.001

RIGHT_APPEND = "right-append"
RIGHT_UNIT = "right-unit"
NO_FIT = "no-fit"
WRONG_PART = "wrong-part"
CONTRADICTION = "contradiction"
WRONG_UNIT = "wrong-unit"
RIGHT_GROUPS = (RIGHT_APPEND, RIGHT_UNIT)
WRONG_GROUPS = (NO_FIT, WRONG_PART, CONTRADICTION, WRONG_UNIT)
GROUPS = (*RIGHT_GROUPS, *WRONG_GROUPS)


class Spec(NamedTuple):
    group: str
    note: str  # a seed note handle, or `probe-contra-N` for an injected claim
    section: str  # the part: the section handle of the candidate (`structures`, ...)
    unit: int | None  # None: `append`; N: `unit N`
    claim: str | None = (
        None  # only for an injected claim (a contradiction that is not a note of the store)
    )


def _appends(group: str, section: str, *notes: str) -> list[Spec]:
    return [Spec(group, n, section, None) for n in notes]


# Right rows: the seed's own labels (`append` with its part; `belongs-existing-sentence` and
# `duplicate-of-existing` with part and sentence).
_RIGHT: list[Spec] = [
    *_appends(
        RIGHT_APPEND,
        "structures",
        "radix-shared-prefix",
        "fulltext-word-map",
        "spatial-bounding-box",
        "clustered-key-order",
        "lsm-buffered-writes",
        "secondary-row-pointer",
    ),
    *_appends(
        RIGHT_APPEND,
        "selection",
        "index-join-columns",
        "function-defeats-index",
        "leading-wildcard",
        "foreign-key-index",
        "start-from-slow-queries",
    ),
    *_appends(
        RIGHT_APPEND,
        "maintenance",
        "concurrent-build",
        "usage-statistics",
        "monitor-index-size",
        "load-then-index",
        "long-transactions",
        "reorganize-vs-rebuild",
    ),
    Spec(RIGHT_UNIT, "sorted-range-equality", "structures", 1),
    Spec(RIGHT_UNIT, "hash-single-key", "structures", 3),
    Spec(RIGHT_UNIT, "worth-when-filtering", "selection", 1),
    Spec(RIGHT_UNIT, "each-index-slows-writes", "maintenance", 1),
    Spec(RIGHT_UNIT, "first-column-rule", "selection", 3),
    Spec(RIGHT_UNIT, "index-only-answer", "selection", 5),
    Spec(RIGHT_UNIT, "reindex-compactness", "maintenance", 4),
    Spec(RIGHT_UNIT, "hash-unordered-sort", "structures", 4),
]

# Wrong rows. `no-fit`: same broad subject, no part fits; each goes to the part nearest to it.
_NO_FIT: list[Spec] = [
    Spec(NO_FIT, "pooling-limits", "maintenance", None),
    Spec(NO_FIT, "replica-lag", "maintenance", None),
    Spec(NO_FIT, "tls-in-transit", "structures", None),
    Spec(NO_FIT, "row-level-security", "selection", None),
]
# `wrong-part`: a real append note, put into the plausible part that is not its own.
_WRONG_PART: list[Spec] = [
    Spec(WRONG_PART, "usage-statistics", "selection", None),
    Spec(WRONG_PART, "load-then-index", "selection", None),
    Spec(WRONG_PART, "clustered-key-order", "selection", None),
    Spec(WRONG_PART, "function-defeats-index", "structures", None),
]
# `contradiction`: a claim that negates a sentence of the part it is appended to. Not notes of the store: injected
# into the check input only (check reads the row, the claim and the part text). The last two repeat the claims of the
# seed's disputed and superseded notes, which never reach check in production.
CONTRADICTIONS: tuple[tuple[str, str, str], ...] = (
    ("structures", "Hash indexes serve range lookups well.", "Hash indexes ... cannot serve ranges (unit 3)"),
    ("structures", "B-tree indexes keep their keys in no particular order.", "B-tree indexes keep keys sorted (unit 1)"),
    ("selection", "An index pays off on columns where nearly every row matches the filter.", "pays off on columns that filter out most rows (unit 1)"),
    ("selection", "Equality columns belong after range columns in a composite index.", "Equality columns belong before range columns (unit 4)"),
    ("maintenance", "Indexes add no cost to inserts and updates.", "Every index slows down inserts and updates (unit 1)"),
    ("maintenance", "Table statistics never need to be refreshed.", "Table statistics must be refreshed (unit 5)"),
    ("selection", "Indexes make every query faster.", "pays off only on selective columns (units 1, 2)"),
    ("maintenance", "Create an index on every column to be safe.", "every index slows writes; drop unused ones (units 1, 2)"),
)  # fmt: skip
_CONTRADICTION: list[Spec] = [
    Spec(CONTRADICTION, f"{CONTRA_PREFIX}{n}", section, None, claim)
    for n, (section, claim, _) in enumerate(CONTRADICTIONS, 1)
]
# `wrong-unit`: an append note joined as `unit N` to a sentence of its own part that does not state it.
_WRONG_UNIT: list[Spec] = [
    Spec(WRONG_UNIT, "radix-shared-prefix", "structures", 5),
    Spec(WRONG_UNIT, "index-join-columns", "selection", 2),
    Spec(WRONG_UNIT, "concurrent-build", "maintenance", 5),
    Spec(WRONG_UNIT, "long-transactions", "maintenance", 2),
    Spec(WRONG_UNIT, "start-from-slow-queries", "selection", 4),
]

TABLE: tuple[Spec, ...] = (*_RIGHT, *_NO_FIT, *_WRONG_PART, *_CONTRADICTION, *_WRONG_UNIT)


# --- input ------------------------------------------------------------------------------------------------------


def probe_candidate(cand: dict) -> dict:
    """The candidate with the injected contradiction claims added as notes, so `check_input` reads them like any."""
    claims = [{"handle": s.note, "claim": s.claim} for s in TABLE if s.claim is not None]
    return {**cand, "notes": [*cand["notes"], *claims]}


def rows_of(cand: dict) -> list[tuple[Spec, Row]]:
    """Each table entry with its `Row`: the part handle and fingerprint come from the candidate's own parts."""
    parts = {
        p["section"]: (f"s:{cand['synthesis']}#{p['section']}", p["fingerprint"])
        for p in cand["parts"]
    }
    out = []
    for spec in TABLE:
        target, fingerprint = parts[spec.section]
        action = "append" if spec.unit is None else "unit"
        out.append((spec, Row(spec.note, target, action, spec.unit, fingerprint)))
    return out


def probe_items(cand: dict) -> tuple[list[tuple[Spec, Row]], list[dict]]:
    """(the entries with their rows, the check input for all of them): what `place_and_check` would give the check
    session if place had proposed exactly these rows."""
    entries = rows_of(cand)
    return entries, engine.check_input(probe_candidate(cand), [row for _, row in entries])


# --- grading ----------------------------------------------------------------------------------------------------


def grade(entries: list[tuple[Spec, Row]], answer: str | None) -> dict:
    """Per group accepted/total for one answer. `answer` None (a failed session) accepts nothing and is `failed`.
    A malformed answer is judged as the engine does: nothing is kept (`malformed`)."""
    rows = [row for _, row in entries]
    kept = plan.agreed(rows, answer) if answer is not None else []
    accepted = set(kept or [])
    groups = {g: {"accepted": 0, "total": 0} for g in GROUPS}
    wrong_accepted = []
    for spec, row in entries:
        groups[spec.group]["total"] += 1
        if row in accepted:
            groups[spec.group]["accepted"] += 1
            if spec.group in WRONG_GROUPS:
                wrong_accepted.append({"group": spec.group, "row": row_line(row)})
    return {
        "groups": groups,
        "wrong_accepted": wrong_accepted,
        "failed": answer is None,
        "malformed": answer is not None and kept is None,
    }


def totals(runs: list[dict]) -> dict:
    """The groups summed over the runs, with the runs' failures."""
    groups = {g: {"accepted": 0, "total": 0} for g in GROUPS}
    for run in runs:
        for g, count in run["groups"].items():
            groups[g]["accepted"] += count["accepted"]
            groups[g]["total"] += count["total"]
    return {
        "groups": groups,
        "wrong_accepted": [w for run in runs for w in run["wrong_accepted"]],
        "failed_runs": sum(r["failed"] for r in runs),
        "malformed_runs": sum(r["malformed"] for r in runs),
    }


def table_text(runs: list[dict]) -> str:
    cells = [["group", *(f"run {i}" for i, _ in enumerate(runs, 1)), "total"]]
    summed = totals(runs)["groups"]
    cells.extend(
        [
            g,
            *(f"{r['groups'][g]['accepted']}/{r['groups'][g]['total']}" for r in runs),
            f"{summed[g]['accepted']}/{summed[g]['total']}",
        ]
        for g in GROUPS
    )
    widths = [max(len(r[i]) for r in cells) for i in range(len(cells[0]))]
    lines = [" | ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in cells]
    for i, run in enumerate(runs, 1):
        if run["failed"]:
            lines.append(f"run {i}: the session failed (nothing accepted)")
        if run["malformed"]:
            lines.append(f"run {i}: the answer was malformed (nothing accepted)")
    wrong = totals(runs)["wrong_accepted"]
    lines.append(f"wrong rows accepted: {len(wrong)}")
    lines += [f"  [{w['group']}] {w['row']}" for w in wrong]
    return "\n".join(lines)


# --- the runs ---------------------------------------------------------------------------------------------------


def _job(store: Path, env: dict, claude: str, budget: float, work: Path) -> engine.Job:
    folder = work / "state"
    record = run_state.RunRecord("probe", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    job = engine.Job(store, env, claude, budget, folder, record)
    jobs.private_dir(job.root)
    return job


def _swap_brief(brief: Path | None, work: Path) -> None:
    """The check brief of `Job.ask` is read from `engine.INTEGRATE_BRIEFS`: point it at a copy holding `brief`."""
    if brief is None:
        return
    folder = work / "briefs"
    folder.mkdir()
    shutil.copy(brief, folder / "check-brief.md")
    engine.INTEGRATE_BRIEFS = folder


class Setup(NamedTuple):
    """Where and how the sessions run: the seeded store, the environment, the claude binary, the work folder."""

    store: Path
    env: dict
    claude: str
    work: Path


def probe(setup: Setup, budget: float, runs: int, brief: Path | None = None) -> dict:
    """`runs` check sessions over the table through `Job.ask`; stops when the budget is spent."""
    store, env, claude, work = setup
    saved = engine.INTEGRATE_BRIEFS
    _swap_brief(brief, work)
    try:
        job = _job(store, env, claude, budget, work)
        found = engine.candidates(job)
        assert found and len(found) == 1, job.record.failures
        entries, items = probe_items(found[0])
        results = []
        for n in range(1, runs + 1):
            asked = job.ask("check", work / f"run-{n}", items)
            if asked is None and job.record.failures[-1] == "budget spent":
                break
            results.append(grade(entries, asked[0] if asked else None))
    finally:
        engine.INTEGRATE_BRIEFS = saved
    return {
        "runs": results,
        "cost": job.record.cost,
        "failures": job.record.failures,
        "brief": str(brief) if brief else "shipped",
        "rows": len(entries),
    }


def save(result: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"check-probe-{time.strftime('%Y-%m-%dT%H-%M-%S')}.json"
    data = {**result, **totals(result["runs"])}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# --- self-check -------------------------------------------------------------------------------------------------

FAKE = """#!/usr/bin/env python3
import json, os, re, sys
found = re.search(r"(/\\S+/check\\.json)", " ".join(sys.argv))
data = json.load(open(found.group(1)))
accept = {tuple(k) for k in json.load(open(os.environ["FAKE_ACCEPT"]))}
lines = [i["row"] for i in data if tuple(p.strip() for p in i["row"].split("|")[:3]) in accept]
print(json.dumps({"type": "result", "is_error": False, "result": "\\n".join(lines) or "none",
                  "total_cost_usd": FAKE_COST, "modelUsage": {}}))
""".replace("FAKE_COST", str(FAKE_SESSION_COST))


def _key(row: Row) -> list[str]:
    action = "append" if row.unit is None else f"unit {row.unit}"
    return [row.note, row.target, action]


def _fake(work: Path, name: str, accept: Iterable[Row]) -> tuple[dict, str]:
    env = trial_env.make_env(work)
    listing = work / f"accept-{name}.json"
    listing.write_text(json.dumps([_key(r) for r in accept]), encoding="utf-8")
    env["FAKE_ACCEPT"] = str(listing)
    fake = work / f"fake-claude-{name}"
    fake.write_text(FAKE, encoding="utf-8")
    fake.chmod(0o755)
    return env, str(fake)


def self_check() -> int:
    """No model, no cost: a fake `claude` that accepts the right rows (the grade must come out clean), then once
    also one wrong row (the probe must report exactly it)."""
    seed = run_trial.load_seed()
    work = trial_env.work_dir("check-probe-check-")
    try:
        env, fake = _fake(work, "base", [])
        store = run_trial.build_store(work, env, seed)
        cand = engine.candidates(_job(store, env, fake, 1.0, work / "cand"))
        assert cand, "no candidate"
        entries = rows_of(cand[0])
        right = [row for spec, row in entries if spec.group in RIGHT_GROUPS]
        wrong = next(row for spec, row in entries if spec.group == WRONG_PART)
        clean = _run_fake(store, work, "right", right)
        assert not clean["wrong_accepted"] and not clean["failed"] and not clean["malformed"], clean
        assert clean["groups"][RIGHT_APPEND] == {"accepted": 17, "total": 17}, clean
        assert clean["groups"][RIGHT_UNIT] == {"accepted": 8, "total": 8}, clean
        bad = _run_fake(store, work, "wrong", [*right, wrong])
        assert [w["row"] for w in bad["wrong_accepted"]] == [row_line(wrong)], bad
        assert bad["groups"][WRONG_PART]["accepted"] == 1, bad
        assert trial_env.TARGET in work.parents
    finally:
        trial_env.clean(work)
    print("self-check passed")
    return 0


def _run_fake(store: Path, work: Path, name: str, accept: list[Row]) -> dict:
    env, fake = _fake(work, name, accept)
    done = probe(Setup(store, env, fake, work / f"probe-{name}"), 1.0, 1)
    assert not done["failures"], done["failures"]
    print(table_text(done["runs"]))
    return done["runs"][0]


# --- command ----------------------------------------------------------------------------------------------------


def _amount(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number above 0")
    return value


def cmd_paid(args: argparse.Namespace) -> int:
    seed = run_trial.load_seed()
    work = trial_env.work_dir("check-probe-")
    try:
        env = trial_env.make_env(work)
        for name in engine.SESSION_VARS:
            env.pop(name, None)
        store = run_trial.build_store(work, env, seed)
        result = probe(
            Setup(store, env, args.claude, work / "probe"), args.budget, args.runs, args.brief
        )
        print(table_text(result["runs"]))
        print(f"cost: {result['cost']:.3f} USD of {args.budget:.2f}")
        for text in result["failures"]:
            print(f"failed: {text}")
        print(f"results: {save(result, args.out)}")
    finally:
        trial_env.clean(work)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--self-check", action="store_true", help="no model: a fake claude")
    parser.add_argument("--budget", type=_amount, help="USD for the paid run (the owner's cap)")
    parser.add_argument(
        "--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    )
    parser.add_argument(
        "--runs", type=int, default=DEFAULT_RUNS, help=f"check sessions (default {DEFAULT_RUNS})"
    )
    parser.add_argument(
        "--brief", type=Path, help="a check brief to use instead of the shipped one"
    )
    parser.add_argument(
        "--out", type=Path, default=OUT_DEFAULT, help="results folder (default under target/)"
    )
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    if not (args.budget and args.claude and args.runs > 0):
        parser.error(
            "a paid run needs --budget USD (the owner's cap), a claude binary and --runs above 0"
        )
    if args.brief and not args.brief.is_file():
        parser.error(f"--brief {args.brief} is not a file")
    if not args.out.resolve().is_relative_to(trial_env.TARGET.parent.resolve()):
        sys.exit(f"--out must lie under {trial_env.TARGET.parent}")
    return cmd_paid(args)


if __name__ == "__main__":
    os.environ.pop("MEM_STORE", None)
    sys.exit(main(sys.argv[1:]))
