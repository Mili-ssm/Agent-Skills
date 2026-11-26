#!/usr/bin/env python3
"""Reference audit of a note store: are the inline references of its syntheses right?

Draws a random sample of the (synthesis, part, unit, note) references of every synthesis in the store and has the trial's
reference judge (`ref-judge-brief.md`, one Haiku session per synthesis) say whether each linked note supports its sentence.
A session reads a units file holding only the sampled units, each with all its references (a note may back one piece of
a sentence and another reference the rest); only the sampled pair is counted. To see whether the judge
still finds wrong references, calibration lines are mixed into those files: a unit that is not in the sample paired with
a note from another part's `Sources:` line. The judge cannot tell them apart, and nothing is written to a synthesis.

Works on a copy of the store under `target/mem-trials/`; the sessions get the trial environment and the tools and settings
of `run_trials.ref_session`, each capped at the reserve the budget holds for it. Verdict: PASS (exit 0), FAIL (1) or
PRELIMINARY (2, also a refusal before any session); a crash exits 3. An invalid calibration gives PRELIMINARY even when
the wrong count is over the limit: the judge was not shown to work.
It costs model usage (about 1 to 3 USD at the defaults); --budget is a cap. `--pairs` judges a given list instead of a
random sample (a second reading of flagged pairs) and `--max-wrong` sets an absolute limit for it. Results: `target/mem-trials/ref-audit-<time>.json`.

Usage: audit_refs.py [--store PATH] [--sample 100] [--planted 20] [--seed 0] [--pairs FILE] [--max-wrong N] [--budget 3.0] [--judge-model haiku]
                     [--claude PATH] [--work NEW_DIR] [--keep] [--dry-run] | --self-check
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_trials as rt
import synth_pipeline as sp
import syntheses
import trial_env

logger = logging.getLogger(__name__)

AUDIT_MAX_WRONG = 2  # wrong references allowed per 100 judged; scaled as round(2 * judged / 100)
AUDIT_MAX_UNJUDGED = 0.10  # sampled references the judge left without a verdict, over those sampled

Pair = tuple[
    str, str, int, str
]  # synthesis handle, part handle, unit number, target (as the units file shows it)


def audit_limit(judged: int) -> int:
    return round(AUDIT_MAX_WRONG * judged / 100)


# --- collecting and drawing ----------------------------------------------------------------------------------


def collect(store: Path) -> tuple[list[Pair], dict[str, dict]]:
    """Every reference pair of every synthesis, and per synthesis the facts planting needs: per part handle, its
    `sources` and its `units` as (number, plain text, targets)."""
    pairs: list[Pair] = []
    facts: dict[str, dict] = {}
    for path in sorted((store / "syntheses").glob("*.md")):
        syn = syntheses.load_one(path)
        if syn.error:
            continue
        parts = {}
        for section in syn.parts:
            found, _ = syntheses.units(section.text)
            units = [
                (u.n, " ".join(u.plain.split()), list(dict.fromkeys(rt._norm(t) for t in u.refs)))
                for u in found
            ]
            parts[section.handle] = {
                "sources": [t for t in section.sources if syntheses._is_ref(t)],
                "units": units,
            }
            pairs += [
                (syn.handle, section.handle, n, t) for n, _, targets in units for t in targets
            ]
        facts[syn.handle] = parts
    return pairs, facts


def draw(pairs: list[Pair], sample: int, seed: int, rng: random.Random | None = None) -> list[Pair]:
    rng = rng or random.Random(seed)
    return sorted(rng.sample(pairs, min(sample, len(pairs))))


def plant_candidates(
    parts: dict, sampled_units: set[tuple[str, int]]
) -> list[tuple[str, int, str, list[str]]]:
    """Units of one synthesis that can carry a calibration line: (part, number, text, wrong targets).

    Mirrors the strong plant of `run_trials.plant_references` (which rewrites the file, so it is not called): the unit
    is not in the sample and has a reference of its own, and the target is on the `Sources:` line of another part and
    not on its own part's; a note the unit already links is no plant."""

    def key(t: str) -> str:
        return rt._norm(t)

    out = []
    for handle, part in parts.items():
        mine = {key(t) for t in part["sources"]}
        elsewhere = {
            key(t) for other, o in parts.items() if other != handle for t in o["sources"]
        } - mine
        for n, text, targets in part["units"]:
            far = sorted(elsewhere - set(targets))
            if targets and far and (handle, n) not in sampled_units:
                out.append((handle, n, text, far))
    return out


def plan(store: Path, sample: int, planted: int, seed: int, only: list[Pair] | None = None) -> dict:
    """The audit's plan, a function of the store and the seed: `sampled` pairs, per synthesis the `lines` of its units
    file ({(part, n): (text, [targets], planted?)}) and the `planted` pairs. `only` replaces the draw with given pairs
    (a second reading of pairs an earlier run flagged); each must still be in the store."""
    pairs, facts = collect(store)
    rng = random.Random(seed)
    if only is not None:
        missing = set(only) - set(pairs)
        if missing:
            raise ValueError(
                f"{len(missing)} given pairs are not in the store, e.g. {min(missing)}"
            )
    sampled = sorted(set(only)) if only is not None else draw(pairs, sample, seed, rng)
    lines = _sampled_lines(facts, sampled)
    plants = _plant(lines, facts, planted, rng)
    return {
        "pairs": len(pairs),
        "syntheses": len(facts),
        "sampled": sampled,
        "lines": lines,
        "planted": plants,
        "facts": facts,
    }


def _sampled_lines(facts: dict, sampled: list[Pair]) -> dict[str, dict]:
    lines: dict[str, dict] = {}
    for syn, part, n, _ in sampled:
        facts_part = {u[0]: u for u in facts[syn][part]["units"]}
        _, text, own = facts_part[n]
        lines.setdefault(syn, {}).setdefault(
            (part, n), (text, list(own), False)
        )  # every reference of the unit
    return lines


def _plant(lines: dict, facts: dict, planted: int, rng: random.Random) -> list[Pair]:
    """Adds the calibration lines to `lines` (in place) and returns their pairs."""
    pool = {syn: plant_candidates(facts[syn], {(p, n) for p, n in lines[syn]}) for syn in lines}
    plants: list[Pair] = []
    while len(plants) < planted and any(
        pool.values()
    ):  # one at a time over the files, so they share them evenly
        for syn in list(lines):
            if len(plants) >= planted or not pool[syn]:
                continue
            part, n, text, far = pool[syn].pop(rng.randrange(len(pool[syn])))
            target = rng.choice(far)
            pool[syn] = [c for c in pool[syn] if (c[0], c[1]) != (part, n)]
            own = next(u[2] for u in facts[syn][part]["units"] if u[0] == n)
            lines[syn][part, n] = (text, [*own, target], True)
            plants.append((syn, part, n, target))
    return plants


def units_file(synthesis: str, lines: dict, facts: dict) -> str:
    """A units file in the format of `synth_pipeline.units_text`, holding only the planned units of the synthesis."""
    out = []
    for part in facts[synthesis]:
        mine = sorted(n for p, n in lines if p == part)
        if not mine:
            continue
        out.append(f"## {part}")
        out += [f"{n} | {lines[part, n][0]} | {', '.join(lines[part, n][1])}" for n in mine]
        out.append("Sources: " + ", ".join(facts[synthesis][part]["sources"]))
    return "\n".join(out) + "\n"


# --- judging -------------------------------------------------------------------------------------------------


class AuditContext(NamedTuple):
    claude: str
    base: Path
    env: dict
    judge_model: str


def audit_session(ctx: AuditContext, handle: str, text: str) -> tuple[dict | None, dict]:
    """What `run_trials.ref_session` does, on a units file that is `text` instead of the whole synthesis: same brief,
    tools, settings, model and effort; the session's cap is the budget's reserve, so --budget holds. Returns the parsed report (None when unreadable) and the session summary."""
    base = ctx.base
    store, work = base / "store", base / "work"
    units, report = work / f"audit-units-{handle}.md", work / f"audit-report-{handle}.md"
    report.unlink(missing_ok=True)
    units.write_text(text)
    prompt = rt.brief(
        "ref-judge",
        rt.HERE,
        SLUG=handle,
        STORE=str(store),
        UNITS_FILE=str(units),
        REPORT_FILE=str(report),
    )
    s = sp.run_session(
        ctx.claude,
        ctx.judge_model,
        prompt,
        work,
        base / "settings.json",
        ctx.env,
        base / f"audit-{handle}.jsonl",
        effort=sp.CHEAP,
        max_budget=rt.RESERVE["ref"],
    )
    s.update(role="audit", model=ctx.judge_model, costs=sp.cost_by_family(s["model_usage"]))
    parsed = rt.parse_ref_report(report.read_text()) if report.is_file() else None
    if parsed is not None and not parsed["units"] and not parsed["pairs"]:
        parsed = None
    summary = rt.capped_summary(s)
    summary["unreliable"] = parsed is None or bool(parsed["unreadable"]) or not parsed["counts_ok"]
    return parsed, summary


def _verdicts_of(syn: str, parsed: dict | None, lines: dict) -> dict[Pair, bool]:
    if parsed is None:
        return {}
    return {
        (syn, part, n, t): parsed["pairs"][part, n, t]
        for (part, n), (_, targets, _) in lines.items()
        for t in targets
        if (part, n, t) in parsed["pairs"]
    }


def judge_all(p: dict, session, budget: rt.Budget) -> dict:
    """One session per synthesis of the plan, as `session(handle, units file text)` -> (parsed report, summary), while
    the budget allows it. Returns the facts of the judgment."""
    verdicts: dict[Pair, bool] = {}
    skipped, cost, sessions, planted_in_judged, unreliable = [], 0.0, 0, [], []
    for syn in p["lines"]:
        if not budget.start("ref"):
            skipped.append(syn)
            continue
        parsed, s = session(syn, units_file(syn, p["lines"][syn], p["facts"]))
        budget.finish("ref", s["cost"])
        cost, sessions = cost + s["cost"], sessions + 1
        if s.get("unreliable"):
            unreliable.append(syn)
        planted_in_judged += [x for x in p["planted"] if x[0] == syn]
        verdicts.update(_verdicts_of(syn, parsed, p["lines"][syn]))
    return {
        "verdicts": verdicts,
        "skipped": skipped,
        "cost": cost,
        "sessions": sessions,
        "planted_judged": planted_in_judged,
        "unreliable": unreliable,
    }


def result(p: dict, j: dict) -> dict:
    """Counts and verdict from the plan and the judgment. Wrong pairs are the sampled ones the judge marked `no`."""
    sampled = p["sampled"]
    planted = set(p["planted"])
    done = [x for x in sampled if x in j["verdicts"]]
    wrong = [x for x in done if not j["verdicts"][x]]
    found = sum(1 for x in j["planted_judged"] if j["verdicts"].get(x) is False)
    judged, unjudged = len(done), len(sampled) - len(done)
    limit = p["max_wrong"] if p.get("max_wrong") is not None else audit_limit(judged)
    share = unjudged / len(sampled) if sampled else 1.0
    cal = rt.calibration_valid(len(j["planted_judged"]), found)
    if not cal:
        verdict = "PRELIMINARY"
    elif len(wrong) > limit:
        verdict = "FAIL"
    elif share > AUDIT_MAX_UNJUDGED:
        verdict = "PRELIMINARY"
    else:
        verdict = "PASS"
    sentence = {
        (syn, part, n): text
        for syn, lines in p["lines"].items()
        for (part, n), (text, _, _) in lines.items()
    }
    assert not planted & set(wrong)
    return {
        "verdict": verdict,
        "sampled": len(sampled),
        "judged": judged,
        "wrong": len(wrong),
        "limit": limit,
        "unjudged": unjudged,
        "unjudged_share": round(share, 3),
        "planted": len(j["planted_judged"]),
        "planted_found": found,
        "planted_not_judged": len(planted) - len(j["planted_judged"]),
        "calibration_valid": cal,
        "cost": round(j["cost"], 4),
        "sessions": j["sessions"],
        "not_judged_syntheses": j["skipped"],
        "unreliable_reports": j.get("unreliable", []),
        "wrong_pairs": [
            {"synthesis": s, "part": pt, "unit": n, "target": t, "sentence": sentence[s, pt, n]}
            for s, pt, n, t in wrong
        ],
    }


EXIT = {"PASS": 0, "FAIL": 1, "PRELIMINARY": 2}


def report_lines(r: dict) -> list[str]:
    out = [
        (
            f"pairs sampled {r['sampled']}, judged {r['judged']}, wrong {r['wrong']} (limit {r['limit']}), "
            f"unjudged {r['unjudged']} ({r['unjudged_share']:.0%}, limit {AUDIT_MAX_UNJUDGED:.0%})"
        ),
        f"calibration: planted {r['planted']}, found {r['planted_found']}, valid {r['calibration_valid']}"
        + (
            f" ({r['planted_not_judged']} planted lines in files not judged)"
            if r["planted_not_judged"]
            else ""
        ),
        f"cost USD {r['cost']:.3f} in {r['sessions']} sessions",
    ]
    if r["unreliable_reports"]:
        out.append(
            "reports with an unreadable line or a COUNTS line that disagrees: "
            + ", ".join(r["unreliable_reports"])
        )
    if r["not_judged_syntheses"]:
        out.append("not judged (budget): " + ", ".join(r["not_judged_syntheses"]))
    out += [
        f"wrong: {w['synthesis']} #{w['part']} unit {w['unit']} -> {w['target']}: {w['sentence']}"
        for w in r["wrong_pairs"]
    ]
    return [*out, r["verdict"]]


# --- running -------------------------------------------------------------------------------------------------


def dry_run(p: dict, budget: float) -> None:
    files = len(p["lines"])
    print(f"references in the store: {p['pairs']} in {p['syntheses']} syntheses")
    print(f"sample: {len(p['sampled'])} pairs in {files} units files")
    for syn, lines in p["lines"].items():
        print(
            f"  {syn}: {sum(1 for v in lines.values() if not v[2])} sampled units, "
            f"{sum(1 for v in lines.values() if v[2])} planted"
        )
    print(
        f"planted lines: {len(p['planted'])} (a valid calibration needs {rt.CALIBRATION_MIN_PLANTED})"
    )
    fit = int(budget // rt.RESERVE["ref"])
    print(
        f"cost estimate: at most {files * rt.RESERVE['ref']:.2f} USD ({files} sessions, capped at {rt.RESERVE['ref']} each); "
        f"--budget {budget:.2f} starts {min(fit, files)} of them"
    )


def copy_store(real: Path, base: Path) -> Path:
    store = base / "store"
    shutil.rmtree(store, ignore_errors=True)
    shutil.copytree(real, store, ignore=shutil.ignore_patterns(".git", ".curation-log*"))
    return store


def given(path: Path | None) -> list[Pair] | None:
    """The pairs of `--pairs`: a JSON list of {synthesis, part, unit, target}, or a results file (its `wrong_pairs`)."""
    if path is None:
        return None
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data["wrong_pairs"]
    return [(w["synthesis"], w["part"], int(w["unit"]), rt._norm(w["target"])) for w in data]


class _RefusedError(Exception):
    """A run the audit declines to start: `run` prints it as `refused: ...` and exits 2."""


def _check_root(root: Path, real: Path) -> None:
    if root.exists() and any(
        root.iterdir()
    ):  # the folder is deleted at the end: never one that holds something
        raise _RefusedError(f"--work {root} exists and is not empty")
    if root == real or real in root.parents or root in real.parents:
        raise _RefusedError("the work folder overlaps the store")


def _stage(args, real: Path, root: Path, only: list[Pair] | None) -> tuple[Path, dict]:
    """Copies the store into `root` and plans on the copy; a refusal removes `root` again."""
    root.mkdir(parents=True, exist_ok=True)
    store = copy_store(real, root)
    p = plan(store, args.sample, args.planted, args.seed, only)
    p["max_wrong"] = args.max_wrong
    try:
        if not p["sampled"]:
            raise _RefusedError("the store holds no reference to judge")
        if rt.RESERVE["ref"] > args.budget:
            raise _RefusedError(
                f"--budget {args.budget:.2f} is below one session's reserve {rt.RESERVE['ref']}"
            )
    except _RefusedError:
        trial_env.clean(root)
        raise
    return store, p


def _audit(args, real: Path, root: Path, only: list[Pair] | None) -> int:
    store, p = _stage(args, real, root, only)
    env = trial_env.make_env(root)
    work = root / "work"
    work.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    (root / "settings.json").write_text(
        json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}})
    )
    print(
        f"work folder: {root}; {len(p['sampled'])} pairs in {len(p['lines'])} units files, "
        f"{len(p['planted'])} planted",
        flush=True,
    )
    ctx = AuditContext(args.claude, root, env, args.judge_model)
    j = judge_all(p, lambda syn, text: audit_session(ctx, syn, text), rt.Budget(args.budget))
    r = result(p, j) | {
        "seed": args.seed,
        "budget": args.budget,
        "judge_model": args.judge_model,
        "pairs_file": str(args.pairs) if args.pairs else None,
        "max_wrong": args.max_wrong,
    }
    r["planted_pairs"] = [
        {"synthesis": s, "part": pt, "unit": n, "target": t} for s, pt, n, t in p["planted"]
    ]
    target = trial_env.TARGET / f"ref-audit-{time.strftime('%Y%m%d-%H%M%S')}.json"
    target.write_text(json.dumps(r, indent=1))
    print("\n".join(report_lines(r)))
    print(f"results: {target}")
    if not args.keep:
        trial_env.clean(root)
    return EXIT[r["verdict"]]


def _run(args, parser) -> int:
    real = (args.store or rt.real_store()).resolve()
    if not (real / "mem-store.yaml").is_file() or not (real / "syntheses").is_dir():
        raise _RefusedError(f"no store with syntheses at {real}")
    if args.max_wrong is not None and args.max_wrong < 0:
        parser.error("--max-wrong must be 0 or more")
    only = given(args.pairs)
    try:  # given pairs that are no longer in the store refuse the run before anything is copied
        checked = plan(real, args.sample, args.planted, args.seed, only)
    except ValueError as exc:
        raise _RefusedError(str(exc)) from exc
    if args.dry_run:
        dry_run(checked, args.budget)
        return 0
    if not args.claude:
        parser.error("--claude is required (no claude binary found)")
    root = args.work.resolve() if args.work else trial_env.work_dir("mem-refaudit-")
    _check_root(root, real)
    return _audit(args, real, root, only)


def run(args, parser) -> int:
    try:
        return _run(args, parser)
    except _RefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


# --- self-check ----------------------------------------------------------------------------------------------

NAMES = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "omicron",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "chi",
    "psi",
    "omega",
]


def fixture(store: Path) -> None:
    """Three syntheses of four parts of six referenced sentences each (the first with two references); part k of a synthesis cites three of the 24 notes."""
    (store / "knowledge" / "x").mkdir(parents=True)
    (store / "syntheses").mkdir()
    (store / "mem-store.yaml").write_text("")
    for name in NAMES:
        (store / "knowledge" / "x" / f"{name}.md").write_text("A note.\n")
    for s in range(3):
        body = [
            "---",
            f"title: Fixture {s}",
            "topics: [demo]",
            "created: 2026-01-01",
            "updated: 2026-01-01",
            "---",
            "",
            "## Summary",
            "",
            "An invented summary.",
            "",
        ]
        for k in range(4):
            own = [NAMES[(s * 8 + k * 3 + i) % len(NAMES)] for i in range(3)]
            link = lambda n: f"[{n}](../knowledge/x/{n}.md)"
            body += [
                f"## Part {k}",
                "",
                " ".join(
                    f"Claim {i} of part {k} holds. {link(own[i % 3])}"
                    + (f" {link(own[1])}" if i == 0 else "")
                    for i in range(6)
                ),
                "",
                "Sources: " + ", ".join(link(n) for n in own),
                "",
            ]
        (store / "syntheses" / f"fixture-{s}.md").write_text("\n".join(body))


def fake_report(p: dict, syn: str, text: str, no: set) -> dict:
    """A judge's report for the units file `text`, in the judge's format, with the pairs in `no` marked `no`."""
    out, part = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            part = line[3:]
        elif line.startswith("Sources:"):
            continue
        else:
            n, _, targets = (c.strip() for c in line.split(" | "))
            out.append(f"U: {part} | {n} | finding")
            out += [
                f"P: {part} | {n} | {t} | {'no' if (syn, part, int(n), t) in no else 'yes'}"
                for t in targets.split(", ")
            ]
    pairs = sum(1 for x in out if x.startswith("P:"))
    out.append(
        f"COUNTS: units={len(out) - pairs} pairs={pairs} no={sum(x.endswith('| no') for x in out)}"
    )
    return rt.parse_ref_report("\n".join(out))


CHECK_SAMPLE, CHECK_PLANTED, CHECK_SEED = 30, 12, 7
CHECK_PAIRS, CHECK_SYNTHESES, CHECK_SKIPPED = 84, 3, 2


def _judged(p: dict, no: set, cost: float = 0.1, budget: float = 10.0) -> dict:
    """`judge_all` over hand-made reports that mark the pairs in `no` as `no`."""

    def session(syn, text):
        return fake_report(p, syn, text, no), {"cost": cost}

    return judge_all(p, session, rt.Budget(budget))


def _sampled_keys(p: dict) -> dict[tuple[str, str, int], set[str]]:
    keys: dict[tuple[str, str, int], set[str]] = {(s, pt, n): set() for s, pt, n, _ in p["sampled"]}
    for s, pt, n, t in p["sampled"]:
        keys[s, pt, n].add(t)
    return keys


def _check_draw(store: Path, p: dict, before: dict) -> None:
    assert (
        p["pairs"] == CHECK_PAIRS
        and p["syntheses"] == CHECK_SYNTHESES
        and len(p["sampled"]) == CHECK_SAMPLE
    ), (p["pairs"], len(p["sampled"]))
    again = plan(store, CHECK_SAMPLE, CHECK_PLANTED, CHECK_SEED)
    assert again["sampled"] == p["sampled"] and again["planted"] == p["planted"], (
        "the draw is not reproducible"
    )
    assert plan(store, CHECK_SAMPLE, CHECK_PLANTED, CHECK_SEED + 1)["sampled"] != p["sampled"], (
        "another seed drew the same sample"
    )
    assert trial_env._snapshot(store) == before, "planning wrote to the store"
    assert len(p["planted"]) == CHECK_PLANTED, p["planted"]


def _shown_units(syn: str, p: dict) -> dict:
    """The units of `syn`'s units file: (synthesis, part, number) -> its targets."""
    shown = {}
    part = None
    for line in units_file(syn, p["lines"][syn], p["facts"]).splitlines():
        if line.startswith("## "):
            part = line[3:]
        elif not line.startswith("Sources:"):
            n, _, targets = (c.strip() for c in line.split(" | "))
            shown[syn, part, int(n)] = set(targets.split(", "))
    return shown


def _check_units_files(p: dict, sampled_keys: dict) -> None:
    """The units files hold the sampled units with all their references, and the plants, nothing else."""
    for syn in p["lines"]:
        shown = _shown_units(syn, p)
        planted = {(s, pt, n): t for s, pt, n, t in p["planted"] if s == syn}
        assert set(shown) == {k for k in sampled_keys if k[0] == syn} | set(planted), (
            "a unit is missing or extra"
        )
        for key, targets in shown.items():
            own = {x for u in p["facts"][syn][key[1]]["units"] if u[0] == key[2] for x in u[2]}
            assert targets == own | ({planted[key]} if key in planted else set()), (
                f"targets of {key}: {targets}"
            )
            assert sampled_keys.get(key, set()) <= own and (
                key not in planted or planted[key] not in own
            )


def _check_plants(p: dict, sampled_keys: dict) -> None:
    """A plant is a unit outside the sample, paired with a note of another part's sources and not of its own."""
    for syn, part, n, t in p["planted"]:
        assert (syn, part, n) not in sampled_keys, "a planted unit is in the sample"
        parts = p["facts"][syn]
        assert t not in parts[part]["sources"] and any(
            t in o["sources"] for h, o in parts.items() if h != part
        )
        assert t not in {u[0]: u[2] for u in parts[part]["units"]}[n], (
            "the unit already links the plant"
        )


def _check_scoring(p: dict) -> None:
    """Scoring on hand-made judge reports."""
    plants = set(p["planted"])
    limit = audit_limit(CHECK_SAMPLE)
    assert limit == 1
    ok = result(p, _judged(p, plants))
    assert ok["verdict"] == "PASS" and ok["wrong"] == 0 and ok["planted_found"] == CHECK_PLANTED, ok
    bad = set(p["sampled"][: limit + 1])
    fail = result(p, _judged(p, plants | bad))
    assert (
        fail["verdict"] == "FAIL"
        and fail["wrong"] == limit + 1
        and len(fail["wrong_pairs"]) == limit + 1
    ), fail
    blind = result(p, _judged(p, set()))
    assert blind["verdict"] == "PRELIMINARY" and not blind["calibration_valid"], blind
    # another reference of a sampled sentence marked `no` is not counted: only the sampled pair is
    others = {
        (s, pt, n, x)
        for s, pt, n, _ in p["sampled"]
        for x in next(u[2] for u in p["facts"][s][pt]["units"] if u[0] == n)
    } - set(p["sampled"])
    assert others, "the fixture has no sentence with a second reference"
    co = result(p, _judged(p, plants | others))
    assert co["verdict"] == "PASS" and co["wrong"] == 0, co


def _check_given_pairs(store: Path, p: dict) -> None:
    """--pairs and --max-wrong: a given list replaces the draw; an absolute limit replaces the scaled one."""
    some = p["sampled"][:3]
    q = plan(store, CHECK_SAMPLE, CHECK_PLANTED, CHECK_SEED, some)
    q["max_wrong"] = 2
    assert q["sampled"] == sorted(some) and not {(s, pt, n) for s, pt, n, _ in q["planted"]} & {
        x[:3] for x in some
    }
    assert result(q, _judged(q, set(q["planted"]) | set(some[:2])))["verdict"] == "PASS"
    try:
        plan(
            store,
            CHECK_SAMPLE,
            CHECK_PLANTED,
            CHECK_SEED,
            [("fixture-0", "part-0", 999, "../knowledge/x/alpha.md")],
        )
        raise AssertionError("a pair not in the store was accepted")
    except ValueError:
        pass


def _check_budget(p: dict) -> None:
    broke = result(p, judge_all(p, lambda syn, text: (None, {"cost": 0.1}), rt.Budget(10.0)))
    assert broke["verdict"] == "PRELIMINARY" and broke["unjudged"] == CHECK_SAMPLE, broke
    # the budget starts no session under one reserve, and says which syntheses it left
    short = _judged(p, set(p["planted"]), cost=0.5, budget=rt.RESERVE["ref"] * 1.5)
    assert short["sessions"] == 1 and len(short["skipped"]) == CHECK_SKIPPED, short["skipped"]
    assert result(p, short)["not_judged_syntheses"] == short["skipped"]


def _check_work_copy(store: Path) -> None:
    """The work folder is a copy: it lives under target/ and apart from the store."""
    work = trial_env.work_dir("mem-refaudit-selfcheck-")
    try:
        copy = copy_store(store, work)
        assert (
            copy != store
            and work.is_relative_to(trial_env.TARGET)
            and not work.is_relative_to(store)
        )
        assert (copy / "syntheses" / "fixture-0.md").read_bytes() == (
            store / "syntheses" / "fixture-0.md"
        ).read_bytes()
    finally:
        trial_env.clean(work)


def self_check() -> int:
    real_before = trial_env._snapshot(rt.real_store())
    with tempfile.TemporaryDirectory(prefix="refaudit-") as tmp:
        store = Path(tmp) / "store"
        fixture(store)
        before = trial_env._snapshot(store)
        p = plan(store, CHECK_SAMPLE, CHECK_PLANTED, CHECK_SEED)
        _check_draw(store, p, before)
        sampled_keys = _sampled_keys(p)
        _check_units_files(p, sampled_keys)
        _check_plants(p, sampled_keys)
        _check_scoring(p)
        _check_given_pairs(store, p)
        _check_budget(p)
        _check_work_copy(store)
    assert trial_env._snapshot(rt.real_store()) == real_before, (
        "a file of the owner's store changed"
    )
    print("self-check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--store",
        type=Path,
        help="the store to audit (default: the owner's, as the trials find it)",
    )
    parser.add_argument("--sample", type=int, default=100, help="references to judge")
    parser.add_argument(
        "--planted", type=int, default=20, help="calibration lines mixed into the units files"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--pairs",
        type=Path,
        help="judge these pairs (JSON list of {synthesis, part, unit, target}) "
        "instead of a random sample",
    )
    parser.add_argument(
        "--max-wrong",
        type=int,
        help="wrong pairs allowed, instead of the limit scaled from "
        f"{AUDIT_MAX_WRONG} per 100 judged",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=3.0,
        help="USD cap; no session starts when what is left is "
        "below the reference judgment's reserve",
    )
    parser.add_argument("--judge-model", default="haiku")
    parser.add_argument(
        "--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    )
    parser.add_argument(
        "--work",
        type=Path,
        help="a new or empty work folder (default: a new one under target/mem-trials/)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the work folder (store copy, units files, session logs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="no session: counts, the sample per synthesis, a cost estimate",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="no model: prove the sampling, planting and verdicts",
    )
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    try:
        return run(args, parser)
    except Exception as exc:  # 1 is FAIL: a crash must not read as a verdict
        logger.debug("audit crashed", exc_info=True)
        print(f"crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
