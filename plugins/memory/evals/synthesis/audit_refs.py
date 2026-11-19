#!/usr/bin/env python3
"""Reference audit of a note store: are the inline references of its syntheses right?

Draws a random sample of the (synthesis, part, unit, note) references of every synthesis in the store and has the trial's
reference judge (`ref-judge-brief.md`, one Haiku session per synthesis) say whether each linked note supports its sentence.
A session reads a units file holding only the sampled units, each with only its sampled target. To see whether the judge
still finds wrong references, calibration lines are mixed into those files: a unit that is not in the sample paired with
a note from another part's `Sources:` line. The judge cannot tell them apart, and nothing is written to a synthesis.

Works on a copy of the store under `target/mem-trials/`; the sessions get the trial environment and the tools and settings
of `run_trials.ref_session`, each capped at the reserve the budget holds for it. Verdict: PASS (exit 0), FAIL (1) or
PRELIMINARY (2, also a refusal before any session); a crash exits 3. An invalid calibration gives PRELIMINARY even when
the wrong count is over the limit: the judge was not shown to work.
It costs model usage (about 1 to 3 USD at the defaults); --budget is a cap. Results: `target/mem-trials/ref-audit-<time>.json`.

Usage: audit_refs.py [--store PATH] [--sample 100] [--planted 20] [--seed 0] [--budget 3.0] [--judge-model haiku]
                     [--claude PATH] [--work NEW_DIR] [--keep] [--dry-run] | --self-check
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_trials as rt  # noqa: E402
import trial_env  # noqa: E402
import synth_pipeline as sp  # noqa: E402
import syntheses  # noqa: E402

AUDIT_MAX_WRONG = 2         # wrong references allowed per 100 judged; scaled as round(2 * judged / 100)
AUDIT_MAX_UNJUDGED = 0.10   # sampled references the judge left without a verdict, over those sampled

Pair = tuple[str, str, int, str]   # synthesis handle, part handle, unit number, target (as the units file shows it)


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
            units = [(u.n, " ".join(u.plain.split()), list(dict.fromkeys(rt._norm(t) for t in u.refs))) for u in found]
            parts[section.handle] = dict(sources=[t for t in section.sources if syntheses._is_ref(t)], units=units)
            pairs += [(syn.handle, section.handle, n, t) for n, _, targets in units for t in targets]
        facts[syn.handle] = parts
    return pairs, facts


def draw(pairs: list[Pair], sample: int, seed: int, rng: random.Random | None = None) -> list[Pair]:
    rng = rng or random.Random(seed)
    return sorted(rng.sample(pairs, min(sample, len(pairs))))


def plant_candidates(parts: dict, sampled_units: set[tuple[str, int]]) -> list[tuple[str, int, str, list[str]]]:
    """Units of one synthesis that can carry a calibration line: (part, number, text, wrong targets).

    Mirrors the strong plant of `run_trials.plant_references` (which rewrites the file, so it is not called): the unit
    is not in the sample and has a reference of its own, and the target is on the `Sources:` line of another part and
    not on its own part's; a note the unit already links is no plant."""
    def key(t: str) -> str:
        return rt._norm(t)
    out = []
    for handle, part in parts.items():
        mine = {key(t) for t in part["sources"]}
        elsewhere = {key(t) for other, o in parts.items() if other != handle for t in o["sources"]} - mine
        for n, text, targets in part["units"]:
            far = sorted(elsewhere - set(targets))
            if targets and far and (handle, n) not in sampled_units:
                out.append((handle, n, text, far))
    return out


def plan(store: Path, sample: int, planted: int, seed: int) -> dict:
    """The audit's plan, a function of the store and the seed: `sampled` pairs, per synthesis the `lines` of its units
    file ({(part, n): (text, [targets], planted?)}) and the `planted` pairs."""
    pairs, facts = collect(store)
    rng = random.Random(seed)
    sampled = draw(pairs, sample, seed, rng)
    lines: dict[str, dict] = {}
    for syn, part, n, target in sampled:
        facts_part = dict((u[0], u) for u in facts[syn][part]["units"])
        _, text, _ = facts_part[n]
        lines.setdefault(syn, {}).setdefault((part, n), (text, [], False))[1].append(target)
    pool = {syn: plant_candidates(facts[syn], {(p, n) for p, n in lines[syn]}) for syn in lines}
    plants: list[Pair] = []
    while len(plants) < planted and any(pool.values()):   # one at a time over the files, so they share them evenly
        for syn in list(lines):
            if len(plants) >= planted or not pool[syn]:
                continue
            part, n, text, far = pool[syn].pop(rng.randrange(len(pool[syn])))
            target = rng.choice(far)
            pool[syn] = [c for c in pool[syn] if (c[0], c[1]) != (part, n)]
            lines[syn][(part, n)] = (text, [target], True)
            plants.append((syn, part, n, target))
    return dict(pairs=len(pairs), syntheses=len(facts), sampled=sampled, lines=lines, planted=plants, facts=facts)


def units_file(synthesis: str, lines: dict, facts: dict) -> str:
    """A units file in the format of `synth_pipeline.units_text`, holding only the planned units of the synthesis."""
    out = []
    for part in facts[synthesis]:
        mine = sorted(n for p, n in lines if p == part)
        if not mine:
            continue
        out.append(f"## {part}")
        out += [f"{n} | {lines[(part, n)][0]} | {', '.join(lines[(part, n)][1])}" for n in mine]
        out.append("Sources: " + ", ".join(facts[synthesis][part]["sources"]))
    return "\n".join(out) + "\n"


# --- judging -------------------------------------------------------------------------------------------------

def audit_session(claude: str, base: Path, env: dict, handle: str, judge_model: str, text: str) -> tuple[dict | None, dict]:
    """What `run_trials.ref_session` does, on a units file that is `text` instead of the whole synthesis: same brief,
    tools, settings, model and effort; the session's cap is the budget's reserve, so --budget holds. Returns the parsed report (None when unreadable) and the session summary."""
    store, work = base / "store", base / "work"
    units, report = work / f"audit-units-{handle}.md", work / f"audit-report-{handle}.md"
    report.unlink(missing_ok=True)
    units.write_text(text)
    prompt = rt.brief("ref-judge", rt.HERE, SLUG=handle, STORE=str(store), UNITS_FILE=str(units), REPORT_FILE=str(report))
    s = sp.run_session(claude, judge_model, prompt, work, base / "settings.json", env, base / f"audit-{handle}.jsonl",
                       effort=sp.CHEAP, max_budget=rt.RESERVE["ref"])
    s.update(role="audit", model=judge_model, costs=sp.cost_by_family(s["model_usage"]))
    parsed = rt.parse_ref_report(report.read_text()) if report.is_file() else None
    if parsed is not None and not parsed["units"] and not parsed["pairs"]:
        parsed = None
    summary = rt.capped_summary(s)
    summary["unreliable"] = parsed is None or bool(parsed["unreadable"]) or not parsed["counts_ok"]
    return parsed, summary


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
        for (part, n), (_, targets, _) in p["lines"][syn].items():
            for t in targets:
                if parsed is not None and (part, n, t) in parsed["pairs"]:
                    verdicts[(syn, part, n, t)] = parsed["pairs"][(part, n, t)]
    return dict(verdicts=verdicts, skipped=skipped, cost=cost, sessions=sessions, planted_judged=planted_in_judged,
                unreliable=unreliable)


def result(p: dict, j: dict) -> dict:
    """Counts and verdict from the plan and the judgment. Wrong pairs are the sampled ones the judge marked `no`."""
    sampled = p["sampled"]
    planted = set(p["planted"])
    done = [x for x in sampled if x in j["verdicts"]]
    wrong = [x for x in done if not j["verdicts"][x]]
    found = sum(1 for x in j["planted_judged"] if j["verdicts"].get(x) is False)
    judged, unjudged = len(done), len(sampled) - len(done)
    limit = audit_limit(judged)
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
    sentence = {(syn, part, n): text for syn, lines in p["lines"].items() for (part, n), (text, _, _) in lines.items()}
    assert not planted & set(wrong)
    return dict(verdict=verdict, sampled=len(sampled), judged=judged, wrong=len(wrong), limit=limit, unjudged=unjudged,
                unjudged_share=round(share, 3), planted=len(j["planted_judged"]), planted_found=found,
                planted_not_judged=len(planted) - len(j["planted_judged"]), calibration_valid=cal, cost=round(j["cost"], 4),
                sessions=j["sessions"], not_judged_syntheses=j["skipped"],
                unreliable_reports=j.get("unreliable", []),
                wrong_pairs=[dict(synthesis=s, part=pt, unit=n, target=t, sentence=sentence[(s, pt, n)])
                             for s, pt, n, t in wrong])


EXIT = dict(PASS=0, FAIL=1, PRELIMINARY=2)


def report_lines(r: dict) -> list[str]:
    out = [f"pairs sampled {r['sampled']}, judged {r['judged']}, wrong {r['wrong']} (limit {r['limit']}), "
           f"unjudged {r['unjudged']} ({r['unjudged_share']:.0%}, limit {AUDIT_MAX_UNJUDGED:.0%})",
           f"calibration: planted {r['planted']}, found {r['planted_found']}, valid {r['calibration_valid']}"
           + (f" ({r['planted_not_judged']} planted lines in files not judged)" if r["planted_not_judged"] else ""),
           f"cost USD {r['cost']:.3f} in {r['sessions']} sessions"]
    if r["unreliable_reports"]:
        out.append("reports with an unreadable line or a COUNTS line that disagrees: " + ", ".join(r["unreliable_reports"]))
    if r["not_judged_syntheses"]:
        out.append("not judged (budget): " + ", ".join(r["not_judged_syntheses"]))
    out += [f"wrong: {w['synthesis']} #{w['part']} unit {w['unit']} -> {w['target']}: {w['sentence']}" for w in r["wrong_pairs"]]
    return out + [r["verdict"]]


# --- running -------------------------------------------------------------------------------------------------

def dry_run(p: dict, budget: float) -> None:
    files = len(p["lines"])
    print(f"references in the store: {p['pairs']} in {p['syntheses']} syntheses")
    print(f"sample: {len(p['sampled'])} pairs in {files} units files")
    for syn, lines in p["lines"].items():
        print(f"  {syn}: {sum(1 for v in lines.values() if not v[2])} sampled units, "
              f"{sum(1 for v in lines.values() if v[2])} planted")
    print(f"planted lines: {len(p['planted'])} (a valid calibration needs {rt.CALIBRATION_MIN_PLANTED})")
    fit = int(budget // rt.RESERVE["ref"])
    print(f"cost estimate: at most {files * rt.RESERVE['ref']:.2f} USD ({files} sessions, capped at {rt.RESERVE['ref']} each); "
          f"--budget {budget:.2f} starts {min(fit, files)} of them")


def copy_store(real: Path, base: Path) -> Path:
    store = base / "store"
    shutil.rmtree(store, ignore_errors=True)
    shutil.copytree(real, store, ignore=shutil.ignore_patterns(".git", ".curation-log*"))
    return store


def run(args, parser) -> int:
    real = (args.store or rt.real_store()).resolve()
    if not (real / "mem-store.yaml").is_file() or not (real / "syntheses").is_dir():
        print(f"refused: no store with syntheses at {real}", file=sys.stderr)
        return 2
    if args.dry_run:
        dry_run(plan(real, args.sample, args.planted, args.seed), args.budget)
        return 0
    if not args.claude:
        parser.error("--claude is required (no claude binary found)")
    root = args.work.resolve() if args.work else trial_env.work_dir("mem-refaudit-")
    if root.exists() and any(root.iterdir()):   # the folder is deleted at the end: never one that holds something
        print(f"refused: --work {root} exists and is not empty", file=sys.stderr)
        return 2
    if root == real or real in root.parents or root in real.parents:
        print("refused: the work folder overlaps the store", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    store = copy_store(real, root)
    p = plan(store, args.sample, args.planted, args.seed)
    if not p["sampled"]:
        print("refused: the store holds no reference to judge", file=sys.stderr)
        trial_env.clean(root)
        return 2
    if rt.RESERVE["ref"] > args.budget:
        print(f"refused: --budget {args.budget:.2f} is below one session's reserve {rt.RESERVE['ref']}", file=sys.stderr)
        trial_env.clean(root)
        return 2
    env = trial_env.make_env(root)
    work = root / "work"
    work.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    (root / "settings.json").write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
    print(f"work folder: {root}; {len(p['sampled'])} pairs in {len(p['lines'])} units files, "
          f"{len(p['planted'])} planted", flush=True)
    j = judge_all(p, lambda syn, text: audit_session(args.claude, root, env, syn, args.judge_model, text),
                  rt.Budget(args.budget))
    r = result(p, j) | dict(seed=args.seed, budget=args.budget, judge_model=args.judge_model)
    r["planted_pairs"] = [dict(synthesis=s, part=pt, unit=n, target=t) for s, pt, n, t in p["planted"]]
    target = trial_env.TARGET / f"ref-audit-{time.strftime('%Y%m%d-%H%M%S')}.json"
    target.write_text(json.dumps(r, indent=1))
    print("\n".join(report_lines(r)))
    print(f"results: {target}")
    if not args.keep:
        trial_env.clean(root)
    return EXIT[r["verdict"]]


# --- self-check ----------------------------------------------------------------------------------------------

NAMES = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon "
         "phi chi psi omega").split()


def fixture(store: Path) -> None:
    """Three syntheses of four parts of six referenced sentences each; part k of a synthesis cites three of the 24 notes."""
    (store / "knowledge" / "x").mkdir(parents=True)
    (store / "syntheses").mkdir()
    (store / "mem-store.yaml").write_text("")
    for name in NAMES:
        (store / "knowledge" / "x" / f"{name}.md").write_text("A note.\n")
    for s in range(3):
        body = ["---", f"title: Fixture {s}", "topics: [demo]", "created: 2026-01-01", "updated: 2026-01-01", "---", "",
                "## Summary", "", "An invented summary.", ""]
        for k in range(4):
            own = [NAMES[(s * 8 + k * 3 + i) % len(NAMES)] for i in range(3)]
            link = lambda n: f"[{n}](../knowledge/x/{n}.md)"
            body += [f"## Part {k}", "", " ".join(f"Claim {i} of part {k} holds. {link(own[i % 3])}" for i in range(6)), "",
                     "Sources: " + ", ".join(link(n) for n in own), ""]
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
            out += [f"P: {part} | {n} | {t} | {'no' if (syn, part, int(n), t) in no else 'yes'}" for t in targets.split(", ")]
    pairs = sum(1 for x in out if x.startswith("P:"))
    out.append(f"COUNTS: units={len(out) - pairs} pairs={pairs} no={sum(x.endswith('| no') for x in out)}")
    return rt.parse_ref_report("\n".join(out))


def self_check() -> int:
    real_before = trial_env._snapshot(rt.real_store())
    with tempfile.TemporaryDirectory(prefix="refaudit-") as tmp:
        store = Path(tmp) / "store"
        fixture(store)
        before = trial_env._snapshot(store)
        p = plan(store, 30, 12, 7)
        assert p["pairs"] == 72 and p["syntheses"] == 3 and len(p["sampled"]) == 30, (p["pairs"], len(p["sampled"]))
        again = plan(store, 30, 12, 7)
        assert again["sampled"] == p["sampled"] and again["planted"] == p["planted"], "the draw is not reproducible"
        assert plan(store, 30, 12, 8)["sampled"] != p["sampled"], "another seed drew the same sample"
        assert trial_env._snapshot(store) == before, "planning wrote to the store"
        # the units files hold the sampled units and targets plus the plants, nothing else
        sampled_keys = {(s, pt, n): set() for s, pt, n, _ in p["sampled"]}
        for s, pt, n, t in p["sampled"]:
            sampled_keys[(s, pt, n)].add(t)
        assert len(p["planted"]) == 12, p["planted"]
        for syn in p["lines"]:
            shown = {}
            part = None
            for line in units_file(syn, p["lines"][syn], p["facts"]).splitlines():
                if line.startswith("## "):
                    part = line[3:]
                elif not line.startswith("Sources:"):
                    n, _, targets = (c.strip() for c in line.split(" | "))
                    shown[(syn, part, int(n))] = set(targets.split(", "))
            planted = {(s, pt, n): t for s, pt, n, t in p["planted"] if s == syn}
            assert set(shown) == {k for k in sampled_keys if k[0] == syn} | set(planted), "a unit is missing or extra"
            for key, targets in shown.items():
                assert targets == (sampled_keys.get(key) or {planted[key]}), f"targets of {key}: {targets}"
        # a plant is a unit outside the sample, paired with a note of another part's sources and not of its own
        for syn, part, n, t in p["planted"]:
            assert (syn, part, n) not in sampled_keys, "a planted unit is in the sample"
            parts = p["facts"][syn]
            assert t not in parts[part]["sources"] and any(t in o["sources"] for h, o in parts.items() if h != part)
            assert t not in dict((u[0], u[2]) for u in parts[part]["units"])[n], "the unit already links the plant"
        # scoring on three hand-made judge reports
        def judge(no: set):
            def session(syn, text):
                return fake_report(p, syn, text, no), dict(cost=0.1)
            return judge_all(p, session, rt.Budget(10.0))
        plants = set(p["planted"])
        limit = audit_limit(30)
        assert limit == 1
        ok = result(p, judge(plants))
        assert ok["verdict"] == "PASS" and ok["wrong"] == 0 and ok["planted_found"] == 12, ok
        bad = set(p["sampled"][:limit + 1])
        fail = result(p, judge(plants | bad))
        assert fail["verdict"] == "FAIL" and fail["wrong"] == limit + 1 and len(fail["wrong_pairs"]) == limit + 1, fail
        blind = result(p, judge(set()))
        assert blind["verdict"] == "PRELIMINARY" and not blind["calibration_valid"], blind
        broke = result(p, judge_all(p, lambda syn, text: (None, dict(cost=0.1)), rt.Budget(10.0)))
        assert broke["verdict"] == "PRELIMINARY" and broke["unjudged"] == 30, broke
        # the budget starts no session under one reserve, and says which syntheses it left
        short = judge_all(p, lambda syn, text: (fake_report(p, syn, text, plants), dict(cost=0.5)),
                          rt.Budget(rt.RESERVE["ref"] * 1.5))
        assert short["sessions"] == 1 and len(short["skipped"]) == 2, short["skipped"]
        assert result(p, short)["not_judged_syntheses"] == short["skipped"]
        # the work folder is a copy: it lives under target/ and apart from the store
        work = trial_env.work_dir("mem-refaudit-selfcheck-")
        try:
            copy = copy_store(store, work)
            assert copy != store and work.is_relative_to(trial_env.TARGET) and not work.is_relative_to(store)
            assert (copy / "syntheses" / "fixture-0.md").read_bytes() == (store / "syntheses" / "fixture-0.md").read_bytes()
        finally:
            trial_env.clean(work)
    assert trial_env._snapshot(rt.real_store()) == real_before, "a file of the owner's store changed"
    print("self-check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, help="the store to audit (default: the owner's, as the trials find it)")
    parser.add_argument("--sample", type=int, default=100, help="references to judge")
    parser.add_argument("--planted", type=int, default=20, help="calibration lines mixed into the units files")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--budget", type=float, default=3.0, help="USD cap; no session starts when what is left is "
                        "below the reference judgment's reserve")
    parser.add_argument("--judge-model", default="haiku")
    parser.add_argument("--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude"))
    parser.add_argument("--work", type=Path, help="a new or empty work folder (default: a new one under target/mem-trials/)")
    parser.add_argument("--keep", action="store_true", help="keep the work folder (store copy, units files, session logs)")
    parser.add_argument("--dry-run", action="store_true", help="no session: counts, the sample per synthesis, a cost estimate")
    parser.add_argument("--self-check", action="store_true", help="no model: prove the sampling, planting and verdicts")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    try:
        return run(args, parser)
    except Exception as exc:   # 1 is FAIL: a crash must not read as a verdict
        print(f"crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
