#!/usr/bin/env python3
"""Trial of the background settling run (plan 2026-11-17-memory-seamless, stage W, "Trial before it is turned on").

Question: when new global memories that look like existing ones are settled by the real `mem-settle run`, how often is the
pair acted on rightly, and how often wrongly? Retrieval is part of what is measured: `mem settle pending` decides which
pairs the session is shown at all.

Flow: a store under `target/` (through `trial_env`) whose global memories are the `--base` records, all counted as
judged; each derived record is written with `mem remember --global` (so it is new); the pairs `pending` lists are
recorded (the state file is put back afterwards, so this look is not counted as an offer); `mem-settle run --minutes 0`
runs up to `--runs` times (a pair retained by an unfinished verdict list gets its second offer, then is logged `left`),
stopping when nothing is pending or the summed cost passes `--budget`; the settle log and the final records are graded.
Nothing outside `target/` is read or written.

Grading (fixed on 2026-11-18, before any run; a change needs a new date in the plan):
- `paraphrase` and `correction` (should be acted on): `merge` or `supersede` of the pair with its base, leaving the
  DERIVED record active and the base not, is `acted`; `distinct` is a `wrong` action; no decision or `left` is
  `not acted`; a merge or supersede that leaves the base active and the derived record not (wrong direction) is `wrong`.
- `version` and `unrelated` (should be left): `merge` or `supersede` is `wrong`; `distinct`, `nothing`, `left` or never
  shown is `correct`.
- A row `pending` never showed is a retrieval miss: reported apart, not a judgment.
- An action on a pair that is not (derived, its own base) is listed under `unexpected`, and is a wrong action only
  when it is a merge or supersede.
- Verdict: "retrieval finding" when fewer than 60% of the should-act rows were shown (12 of 20); else "adopt" when
  wrong actions <= 1 AND acted >= 60% of the should-act rows shown; else "keep the safe subset".

Usage: run_trial.py --base DIR --derived FILE --claude PATH [--budget USD (1.0)] [--runs N (2)] [--out DIR] | --self-check
`--base` must lie under the repository's `target/`. The results file holds text derived from private memories: its
folder is git-ignored, never commit it."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
import trial_env
from memories import records
from settle import state as settle_state
from synthesize import pipeline as sp

PLUGIN = trial_env.PLUGIN
MEM_SETTLE = PLUGIN / "bin" / "mem-settle"
TYPES = ("paraphrase", "correction", "version", "unrelated")
SHOULD_ACT = ("paraphrase", "correction")
ACTIONS = ("merge", "supersede")
LOGGED = ("merge", "supersede", "distinct", "left")
CLAIM_WIDTH = 50
EPSILON = 1e-9  # float slack on the share thresholds
MIN_SHOWN_SHARE = 0.6  # of the should-act rows (12 of 20)
MIN_ACTED_SHARE = 0.6  # of the should-act rows shown
MAX_WRONG = 1
OUT_DEFAULT = trial_env.TARGET / "settle-results"


def under_target(path: Path) -> bool:
    return path.resolve().is_relative_to(trial_env.TARGET.parent.resolve())


# --- fixture ----------------------------------------------------------------------------------------------------


def load_derived(path: Path, base_handles: set[str]) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(rows, list) and rows, "the derived file must hold a non-empty JSON list"
    for n, row in enumerate(rows, 1):
        assert isinstance(row, dict) and row.get("type") in TYPES, (
            f"row {n}: type must be one of {TYPES}"
        )
        assert all(
            isinstance(row.get(k), str) and row[k].strip() for k in ("base", "claim", "kind")
        ), f"row {n}: base, claim and kind are needed"
        row["base"] = row["base"].strip().removeprefix("m:")
        assert row["base"] in base_handles, f"row {n}: no base record {row['base']}"
    return rows


def build_store(work: Path, env: dict, base: Path) -> tuple[Path, Path]:
    store = work / "store"
    done = subprocess.run(
        [str(sp.MEM), "init", str(store)], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    folder = records.memories_root(env, store)
    assert folder is not None and folder.resolve().is_relative_to(work.resolve()), (
        f"global folder outside the trial: {folder}"
    )
    folder.mkdir(exist_ok=True)
    for source in sorted(base.glob("*.md")):
        shutil.copy2(source, folder / source.name)
    judged = sp.mem(
        store, env, "settle", "log"
    )  # the first use records every memory that exists as judged
    assert judged.returncode == 0, judged.stderr
    state = json.loads((folder / ".settle-state.json").read_text())
    assert set(state["judged"]) == {p.stem for p in folder.glob("*.md")}, (
        "the base records are not all judged"
    )
    return store, folder


def write_derived(store: Path, env: dict, rows: list[dict]) -> dict[str, dict]:
    """handle of the new record -> its row (also set as `derived` on the row); a row that could not be written gets
    `error` and no handle."""
    mapping: dict[str, dict] = {}
    for row in rows:
        done = sp.mem(
            store, env, "remember", "--global", "--kind", row["kind"], "--claim", row["claim"]
        )
        first = done.stdout.split("\t")[0].strip() if done.returncode == 0 else ""
        if first.startswith("m:"):
            row["derived"] = first[2:]
            mapping[row["derived"]] = row
        else:
            row["error"] = (
                f"mem remember exit {done.returncode}: {(done.stderr or done.stdout).strip()[:150]}"
            )
    return mapping


def listing(store: Path, env: dict, folder: Path) -> list[dict]:
    """The pairs `pending` shows now. The state file is restored: this look must not count as an offer."""
    path = folder / ".settle-state.json"
    saved = path.read_bytes()
    try:
        found = sp.mem(store, env, "settle", "pending", "--json")
    finally:
        path.write_bytes(saved)
    assert found.returncode == 0, found.stderr
    return json.loads(found.stdout)


# --- the runs ---------------------------------------------------------------------------------------------------


def due(store: Path, env: dict) -> bool:
    return sp.mem(store, env, "settle", "due", "--minutes", "0").returncode == 0


def run_once(store: Path, env: dict, claude: str, budget: float) -> dict:
    sd = settle_state.settle_dir(Path(env["MEM_DATA"]), store)
    before = json.loads((sd / "status.json").read_text()) if (sd / "status.json").is_file() else {}
    done = subprocess.run(
        [
            str(MEM_SETTLE),
            "run",
            "--store",
            str(store),
            "--claude",
            claude,
            "--budget",
            f"{budget:.4f}",
            "--minutes",
            "0",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    status = json.loads((sd / "status.json").read_text()) if (sd / "status.json").is_file() else {}
    started = status.get("started") != before.get("started")
    return {
        "started": started,
        "state": status.get("state") if started else "not started",
        "cost": float(status.get("cost") or 0.0) if started else 0.0,
        "pairs": status.get("pairs", 0) if started else 0,
        "reason": status.get("reason", "") if started else (done.stderr or "").strip()[:150],
        "summary": status.get("summary", "") if started else "",
    }


def run_loop(store: Path, env: dict, claude: str, budget: float, runs: int) -> list[dict]:
    out: list[dict] = []
    spent = 0.0
    for n in range(1, runs + 1):
        if not due(store, env):
            break
        if spent >= budget:
            out.append({"run": n, "started": False, "state": "budget reached", "cost": 0.0})
            break
        result = {"run": n, **run_once(store, env, claude, budget - spent)}
        out.append(result)
        spent += result["cost"]
        if not result["started"] or result["state"] != "ok":
            break  # a failed run is not retried at once by design
    return out


def verdict_rows(store: Path, env: dict) -> list[dict]:
    """Every verdict row the sessions wrote, in run order (the settle log has no line for `nothing`)."""
    sd = settle_state.settle_dir(Path(env["MEM_DATA"]), store) / "runs"
    out = []
    for folder in sorted(sd.glob("*")) if sd.is_dir() else []:
        try:
            rows = json.loads((folder / "work" / "verdicts.json").read_text())
        except (OSError, ValueError):
            continue
        out += [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    return out


# --- grading ----------------------------------------------------------------------------------------------------


def key(a: str, b: str) -> frozenset:
    return frozenset((a.removeprefix("m:"), b.removeprefix("m:")))


def _decisions(log: list[dict], verdicts: list[dict]) -> dict[frozenset, tuple[str, str]]:
    """pair -> (decision, reason): the settle log first, then a `nothing` verdict the log does not hold."""
    decisions: dict[frozenset, tuple[str, str]] = {}
    for e in log:
        if e.get("decision") in LOGGED:
            decisions[key(e["older"], e["newer"])] = (e["decision"], e.get("reason", ""))
    for v in (
        verdicts
    ):  # only for what the log does not hold: a `nothing` verdict, or one that was refused
        if not (isinstance(v.get("a"), str) and isinstance(v.get("b"), str)):
            continue
        if key(v["a"], v["b"]) not in decisions and v.get("decision") == "nothing":
            decisions[key(v["a"], v["b"])] = ("nothing", str(v.get("reason", "")))
    return decisions


def _grade_should_act(row_shown: bool, decision: str, direction_ok: bool) -> str:
    if not row_shown:
        return "retrieval miss"
    if decision in ACTIONS:
        return "acted" if direction_ok else "wrong"
    return "wrong" if decision == "distinct" else "not acted"


def _grade_row(
    r: dict, shown_keys: set, decisions: dict[frozenset, tuple[str, str]], live: dict[str, bool]
) -> dict:
    if "derived" not in r:
        return {
            "type": r["type"],
            "base": r["base"],
            "claim": r["claim"],
            "shown": False,
            "decision": "none",
            "reason": r["error"],
            "grade": "write failed",
        }
    pair = key(r["derived"], r["base"])
    decision, reason = decisions.get(pair, ("none", ""))
    row_shown = pair in shown_keys or decision != "none"
    direction_ok = live.get(r["derived"], False) and not live.get(r["base"], True)
    if r["type"] in SHOULD_ACT:
        result = _grade_should_act(row_shown, decision, direction_ok)
    else:
        result = "wrong" if decision in ACTIONS else "correct"
    return {
        "type": r["type"],
        "base": r["base"],
        "derived": r["derived"],
        "claim": r["claim"],
        "shown": row_shown,
        "decision": decision,
        "reason": reason,
        "grade": result,
    }


def _unexpected(
    shown: list[dict], decisions: dict[frozenset, tuple[str, str]], own: set
) -> list[dict]:
    out = []
    seen = set()
    for pair in [key(p["a"], p["b"]) for p in shown] + list(decisions):
        if pair in own or pair in seen:
            continue
        seen.add(pair)
        decision, reason = decisions.get(pair, ("none", ""))
        out.append({
            "pair": sorted(pair),
            "decision": decision,
            "reason": reason,
            "wrong": decision in ACTIONS,
        })
    return out


def grade(
    rows: list[dict],
    shown: list[dict],
    log: list[dict],
    verdicts: list[dict],
    live: dict[str, bool],
) -> dict:
    """Grades each row and the pairs outside the design. `live` says per handle whether the record is active."""
    decisions = _decisions(log, verdicts)
    shown_keys = {key(p["a"], p["b"]) for p in shown}
    own = {key(r["derived"], r["base"]) for r in rows if "derived" in r}
    return {
        "rows": [_grade_row(r, shown_keys, decisions, live) for r in rows],
        "unexpected": _unexpected(shown, decisions, own),
    }


def totals_and_verdict(graded: dict) -> dict:
    rows = graded["rows"]
    should = [r for r in rows if r["type"] in SHOULD_ACT]
    shown_should = [
        r for r in should if r["grade"] != "retrieval miss" and r["grade"] != "write failed"
    ]
    acted = sum(r["grade"] == "acted" for r in should)
    wrong_rows = sum(r["grade"] == "wrong" for r in rows)
    wrong_unexpected = sum(u["wrong"] for u in graded["unexpected"])
    wrong = wrong_rows + wrong_unexpected
    if len(shown_should) < MIN_SHOWN_SHARE * len(should) - EPSILON:
        verdict = "retrieval finding: record it and decide on the look-alike search before judging the model"
    elif wrong <= MAX_WRONG and acted >= MIN_ACTED_SHARE * len(shown_should) - EPSILON:
        verdict = "adopt"
    else:
        verdict = "keep the safe subset"
    return {
        "rows": len(rows),
        "should_act": len(should),
        "should_act_shown": len(shown_should),
        "acted": acted,
        "not_acted": sum(r["grade"] == "not acted" for r in rows),
        "retrieval_misses": sum(r["grade"] == "retrieval miss" for r in rows),
        "write_failed": sum(r["grade"] == "write failed" for r in rows),
        "wrong_actions": wrong,
        "wrong_in_rows": wrong_rows,
        "wrong_unexpected": wrong_unexpected,
        "verdict": verdict,
    }


def table(graded: dict, totals: dict, runs: list[dict]) -> str:
    lines = [f"{'type':<11} {'shown':<5} {'decision':<10} {'grade':<15} claim"]
    lines.extend(
        f"{r['type']:<11} {'yes' if r['shown'] else 'no':<5} {r['decision']:<10} {r['grade']:<15} {r['claim'][:CLAIM_WIDTH]}"
        for r in graded["rows"]
    )
    lines.extend(
        f"unexpected  {'yes':<5} {u['decision']:<10} {'WRONG' if u['wrong'] else 'ok':<15} {' | '.join(u['pair'])}"
        for u in graded["unexpected"]
    )
    lines.extend([
        "",
        f"runs: {len(runs)}; cost {sum(r['cost'] for r in runs):.3f} USD ("
        + ", ".join(f"run {r['run']}: {r['state']} {r['cost']:.3f}" for r in runs)
        + ")",
        (
            f"should-act rows shown {totals['should_act_shown']}/{totals['should_act']}, acted {totals['acted']}, "
            f"retrieval misses {totals['retrieval_misses']}, wrong actions {totals['wrong_actions']} of {totals['rows']}"
        ),
        f"verdict: {totals['verdict']}",
    ])
    return "\n".join(lines)


# --- the trial --------------------------------------------------------------------------------------------------


class TrialSpec(NamedTuple):
    base: Path
    derived_file: Path
    claude: str
    budget: float
    runs: int
    out: Path


def trial(spec: TrialSpec, work: Path) -> tuple[dict, str]:
    base, budget = spec.base, spec.budget
    env = trial_env.make_env(work)
    base_handles = {p.stem for p in base.glob("*.md")}
    rows = load_derived(spec.derived_file, base_handles)
    store, folder = build_store(work, env, base)
    write_derived(store, env, rows)
    shown = listing(store, env, folder)
    run_list = run_loop(store, env, spec.claude, budget, spec.runs)
    today = datetime.date.today()
    live = {m.handle: records.is_live(m, today) for m in records.load_memories(folder, "global")}
    graded = grade(rows, shown, settle_log(folder), verdict_rows(store, env), live)
    totals = totals_and_verdict(graded)
    result = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "budget": budget,
        "runs": run_list,
        "cost": sum(r["cost"] for r in run_list),
        "totals": totals,
        **graded,
    }
    spec.out.mkdir(parents=True, exist_ok=True)
    (spec.out / f"settle-results-{time.strftime('%Y-%m-%dT%H-%M-%S')}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return result, table(graded, totals, run_list)


def settle_log(folder: Path) -> list[dict]:
    try:
        lines = (folder / ".settle-log").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and "decision" in entry:
            out.append(entry)
    return out


# --- self-check -------------------------------------------------------------------------------------------------

BASES = {  # invented claims
    "base-lint": "Run the linter before every commit to catch style errors early.",
    "base-cache": "Keep the build cache warm between release builds to save time.",
    "base-backup": "Store the nightly backup archive on the secondary storage volume.",
    "base-review": "Request a code review from a teammate before merging a change.",
    "base-docs": "Write the migration guide for every public interface change.",
    "base-feed": "Cache the product feed responses for the mobile clients.",
}
DERIVED = [  # (base, type, claim, what the fake session answers)
    (
        "base-lint",
        "paraphrase",
        "Always run the linter before each commit to catch style errors early.",
        "merge",
    ),
    (
        "base-cache",
        "correction",
        "Keep the build cache warm between release builds to save much time, even on laptops.",
        "supersede",
    ),
    (
        "base-backup",
        "paraphrase",
        "Store the nightly backup archive on the secondary storage volume daily.",
        "distinct",
    ),
    (
        "base-review",
        "version",
        "Request a code review from two teammates before merging a change.",
        "merge",
    ),
    (
        "base-docs",
        "unrelated",
        "Write the changelog entry for every public interface change.",
        "nothing",
    ),
    (
        "base-feed",
        "paraphrase",
        "Cache the product feed responses for the mobile clients as well.",
        "omit",
    ),
]
FAKE = """#!/usr/bin/env python3
import json, os
plan = json.load(open(os.environ["FAKE_PLAN"]))
pairs = json.load(open("pairs.json"))
rows = []
for p in pairs:
    text = p["claim_a"] + " " + p["claim_b"]
    for marker, decision in plan.items():
        if marker in text and decision != "omit":
            rows.append({"a": p["a"], "b": p["b"], "decision": decision, "reason": "fake verdict for the self-check"})
json.dump(rows, open("verdicts.json", "w"))
print(json.dumps({"type": "result", "is_error": False, "result": "done", "total_cost_usd": 0.10}))
"""


def self_check() -> int:
    """No model, no real store: the whole flow on invented records with a fake `claude` that writes known verdicts."""
    work = trial_env.work_dir("settle-trial-check-")
    try:
        base = work / "base"
        base.mkdir()
        for handle, claim in BASES.items():
            (base / f"{handle}.md").write_text(
                f"---\nkind: lesson\nclaim: {claim}\ncreated: '2026-11-01'\nobserved: 1\nstatus: active\n---\n",
                encoding="utf-8",
            )
        derived = [{"base": b, "type": t, "claim": c, "kind": "lesson"} for b, t, c, _ in DERIVED]
        # a derived record sharing too few terms with its base is never listed: a retrieval miss
        derived.append({
            "base": "base-feed",
            "type": "correction",
            "claim": "Feed payloads are compressed on the edge.",
            "kind": "lesson",
        })
        derived_file = work / "derived.json"
        derived_file.write_text(json.dumps(derived))
        plan = {
            "linter": "merge",
            "build cache": "supersede",
            "backup archive": "distinct",
            "two teammates": "merge",
            "changelog": "nothing",
            "feed responses": "omit",
        }
        fake = work / "fake-claude"
        fake.write_text(FAKE)
        fake.chmod(0o755)
        plan_file = work / "plan.json"
        plan_file.write_text(json.dumps(plan))
        os.environ["FAKE_PLAN"] = str(plan_file)
        result, text = trial(
            TrialSpec(base, derived_file, str(fake), 1.0, 2, work / "results"), work
        )
        print(text)
        grades = {r["claim"]: (r["grade"], r["decision"]) for r in result["rows"]}
        assert grades[DERIVED[0][2]] == ("acted", "merge"), grades
        assert grades[DERIVED[1][2]] == ("acted", "supersede"), grades
        assert grades[DERIVED[2][2]] == ("wrong", "distinct"), (
            grades
        )  # distinct on a true duplicate
        assert grades[DERIVED[3][2]] == ("wrong", "merge"), grades  # a version merged
        assert grades[DERIVED[4][2]] == ("correct", "nothing"), grades
        assert grades[DERIVED[5][2]] == ("not acted", "left"), (
            grades
        )  # retained, then left after two offers
        assert grades[derived[-1]["claim"]][0] == "retrieval miss", grades
        t = result["totals"]
        assert (
            t["rows"],
            t["should_act"],
            t["should_act_shown"],
            t["acted"],
            t["wrong_actions"],
        ) == (7, 5, 4, 2, 2), t
        assert t["retrieval_misses"] == 1 and t["verdict"] == "keep the safe subset", t
        assert [r["state"] for r in result["runs"]] == ["ok", "ok"] and abs(
            result["cost"] - 0.2
        ) < EPSILON, result["runs"]
        assert not result["unexpected"], result["unexpected"]
        assert list((work / "results").glob("settle-results-*.json")), "no results file"

        # the verdict rule on its own
        def row(g: str, ty: str = "paraphrase") -> dict:
            return {"type": ty, "grade": g}

        good = {
            "rows": [row("acted")] * 3 + [row("not acted")] * 2 + [row("correct", "unrelated")],
            "unexpected": [],
        }
        assert totals_and_verdict(good)["verdict"] == "adopt"
        good["unexpected"] = [
            {"pair": ["x", "y"], "decision": "merge", "reason": "", "wrong": True}
        ] * 2
        assert totals_and_verdict(good)["verdict"] == "keep the safe subset"
        missed = {"rows": [row("acted")] + [row("retrieval miss")] * 3, "unexpected": []}
        assert totals_and_verdict(missed)["verdict"].startswith("retrieval finding")
        assert under_target(work)
    finally:
        os.environ.pop("FAKE_PLAN", None)
        trial_env.clean(work)
    print("self-check passed")
    return 0


def check_args(args: argparse.Namespace) -> None:
    for name, path in (("--base", args.base), ("--out", args.out)):
        if not under_target(path):
            sys.exit(
                f"{name} must lie under {trial_env.TARGET.parent}: the trial never touches anything else"
            )
    if not args.base.is_dir() or not args.derived.is_file():
        sys.exit("--base must be a folder and --derived a file")
    if args.budget <= 0 or args.runs < 1:
        sys.exit("--budget and --runs must be positive")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--base",
        type=Path,
        help="folder of record files used as the existing global memories (under target/)",
    )
    parser.add_argument("--derived", type=Path, help="JSON list of {base, type, claim, kind}")
    parser.add_argument("--claude", help="the claude binary the settling sessions run")
    parser.add_argument(
        "--budget", type=float, default=1.0, help="USD for the whole trial (default 1.0)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="settling runs at most (default 2: retained pairs get their second offer)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DEFAULT,
        help="folder of the results file (default under target/)",
    )
    parser.add_argument(
        "--self-check", action="store_true", help="no model: the whole flow with a fake claude"
    )
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if not (args.base and args.derived and args.claude):
        parser.error("--base, --derived and --claude are required")
    check_args(args)
    work = trial_env.work_dir("settle-trial-")
    _, text = trial(
        TrialSpec(args.base.resolve(), args.derived, args.claude, args.budget, args.runs, args.out),
        work,
    )
    print(text)
    print(f"work folder kept (private text, git-ignored): {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
