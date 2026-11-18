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

Usage: run_trials.py [--claude PATH] [--topic T]... [--arm S|L|M]... [--judge-model haiku] [--runs 1] [--jobs 2]
                     [--budget USD (10)] [--work DIR (resume)] [--keep] | --self-check
It costs model usage (9 pipelines and 9 judges at the defaults, about 7 to 9 USD); no pipeline starts once the summed
cost passes --budget. --rejudge reuses a kept pipeline folder (run an earlier pipeline with --keep).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
import trial_env  # noqa: E402
import synth_pipeline as sp  # noqa: E402
from synth_pipeline import (CHEAP, DELETE_ONLY, NOT_GIVEN, brief as _brief, changed_outside, cost_by_family, mem,  # noqa: E402,F401
                            parse_report, resolve_parts, run_session, scope_text, section_handle, split_parts,
                            summary)

HERE = Path(__file__).resolve().parent
PLUGIN = trial_env.PLUGIN
SOURCE = trial_env.TARGET / "synthesis-source"
ATTACHED = trial_env.TARGET / "synthesis-source-attached.json"
TOPICS = ("human-memory", "time-series-forecasting", "llm-evaluation", "mental-health")
DEFAULT_TOPICS = TOPICS[:3]
ARMS = ("S", "L", "M")
WRITER = {"S": ("sonnet", None), "L": ("sonnet", None), "M": ("haiku", "high")}   # model, effort
LEAN = ("L", "M")
STATE = "state.json"

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


def ensure_source() -> Path:
    """Copy the owner's default store once, read-only, without its history and curation log.

    The log is read, not copied: the handles it records as attached tell the notes that were attached to a synthesis
    from the ones a synthesis created itself (`--note-slug`)."""
    if (SOURCE / "mem-store.yaml").is_file() and ATTACHED.is_file():
        return SOURCE
    real = real_store()
    if not (real / "mem-store.yaml").is_file():
        sys.exit(f"no store to copy at {real}")
    shutil.rmtree(SOURCE, ignore_errors=True)
    shutil.copytree(real, SOURCE, ignore=shutil.ignore_patterns(".git", ".curation-log*"))
    attached: set[str] = set()
    log = real / ".curation-log"
    if log.is_file():
        for line in log.read_text().splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("action") == "attach" and entry.get("handle"):
                attached.add(entry["handle"])
    ATTACHED.write_text(json.dumps(sorted(attached)))
    return SOURCE


def brief(name: str, **values: str) -> str:
    """A brief: the writer's is the trial's own (the command uses the `memory-synthesizer` agent instead)."""
    return _brief(name, **values) if name != "writer" else _brief(name, HERE, **values)


def front_part_of(text: str) -> str | None:
    head = re.match(r"---\n(.*?)\n---\n", text, re.S)
    found = re.search(r'^part_of: "?([^"\n]+)"?$', head.group(1), re.M) if head else None
    return found.group(1) if found else None


def prepare_store(store: Path, env: dict, topic: str) -> list[str]:
    """Make the copy ready for a writer on `topic`; return the frozen denominator (knowledge notes of the topic)."""
    attached = set(json.loads(ATTACHED.read_text()))
    (store / "syntheses" / f"{topic}.md").unlink(missing_ok=True)
    for note in sorted((store / "knowledge").rglob("*.md")):
        rel = note.relative_to(store).as_posix()
        part = front_part_of(note.read_text())
        if part and part.startswith(f"{topic}#") and rel not in attached:
            note.unlink()   # a note the old synthesis created itself
    out = mem(store, env, "find", "--topic", topic)
    assert out.returncode == 0, out.stderr
    denominator = sorted(line.split("\t")[0] for line in out.stdout.splitlines() if line.startswith("knowledge/"))
    for rel in denominator:
        note = store / rel
        text = note.read_text()
        note.write_text(re.sub(r"^part_of(_hash)?: .*\n", "", text, flags=re.M))
    return denominator


# --- pipeline ------------------------------------------------------------------------------------------------

def synthesis_facts(path: Path) -> tuple[int, int]:
    text = path.read_text()
    return len(text.split()), len(re.findall(r"^## (?!Summary$)", text, re.M))


def judge_row(claude: str, base: Path, env: dict, topic: str, arm: str, run: int, judge_model: str, prior: dict) -> dict:
    """Judge the synthesis in `base/store` and build the row from the pipeline's `prior` facts."""
    store, work = base / "store", base / "work"
    settings = base / "settings.json"
    synthesis = store / "syntheses" / f"{topic}.md"
    sessions, why = list(prior["sessions"]), prior["why"]
    judged, check_exit, words, parts = None, None, 0, 0
    if synthesis.is_file():
        check_exit = mem(store, env, "check").returncode
        words, parts = synthesis_facts(synthesis)
        report = work / "judge-report.md"
        report.unlink(missing_ok=True)
        fill = dict(TOPIC=topic, SLUG=topic, STORE=str(store), WORK_DIR=str(work))
        units = work / "judge-units.md"
        sp.write_units(synthesis, units)
        s = run_session(claude, judge_model, brief("checker", **fill, REPORT_FILE=str(report), UNITS_FILE=str(units))
                        + JUDGE_EXTRA, work,
                        settings, env, base / f"{len(sessions) + 1:02d}-judge.jsonl", effort=CHEAP)
        s.update(role="judge", model=judge_model, costs=cost_by_family(s["model_usage"]))
        sessions.append(summary(s))
        judged = parse_report(report)
        if judged is None:
            why = why or "judge report unreadable"
    for s in sessions:
        if s["denied"]:
            why = f"permission denied in {s['role']}"
            break
    for s in sessions:
        if not s["ok"]:
            why = why or f"{s['role']} session failed"
        elif s["costs"].get(s["model"], 0.0) <= 0:
            why = why or f"{s['model']} missing from {s['role']} modelUsage"
    denominator = prior["denominator"]
    used = {rel for rel, state in (judged or {}).get("notes", {}).items() if state == "used"}
    pooled: dict[str, float] = {}
    for s in sessions:
        for family, cost in s["costs"].items():
            pooled[family] = pooled.get(family, 0.0) + cost
    arm_count = prior["arm_count"]
    return dict(
        topic=topic, arm=arm, run=run, valid=not why, why=why, denominator=len(denominator),
        checked=judged["checked"] if judged else 0, unsupported=judged["unsupported"] if judged else 0,
        words=words, parts=parts, used=len(used & set(denominator)), mem_check=check_exit, fix_rounds=prior["fixes"],
        arm_checked=arm_count["checked"] if arm_count else None,
        arm_unsupported=arm_count["unsupported"] if arm_count else None,
        deleted=prior.get("deleted", 0), scope_violations=prior.get("scope_violations", []),
        costs=pooled, cost=sum(s["cost"] for s in sessions),
        pipeline_cost=sum(s["cost"] for s in sessions if s["role"] != "judge"),
        judge_cost=sum(s["cost"] for s in sessions if s["role"] == "judge"),
        wall=sum(s["wall"] for s in sessions), sessions=sessions)


def one_pipeline(claude: str, root: Path, env: dict, topic: str, arm: str, run: int, keep: bool,
                 judge_model: str) -> dict:
    name = f"{topic}-{arm}-{run}"
    base = root / "runs" / name
    shutil.rmtree(base, ignore_errors=True)
    store, work = base / "store", base / "work"
    shutil.copytree(ensure_source(), store)
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    denominator = prepare_store(store, env, topic)
    settings = base / "settings.json"
    settings.write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
    fill = dict(TOPIC=topic, SLUG=topic, STORE=str(store), WORK_DIR=str(work))
    sessions: list[dict] = []
    synthesis = store / "syntheses" / f"{topic}.md"
    writer_model, writer_effort = WRITER[arm]
    s = run_session(claude, writer_model, brief("writer", **fill), work, settings, env, base / "01-writer.jsonl",
                    effort=writer_effort)
    s.update(role="writer", model=writer_model, costs=cost_by_family(s["model_usage"]))
    sessions.append(summary(s))
    done = dict(arm_count=None, why="no synthesis written", fixes=0, deleted=0, scope_violations=[])
    if synthesis.is_file():
        done = sp.lean_loop(claude, env, base, store, work, settings, topic, sessions, lean=arm in LEAN)
    prior = dict(sessions=sessions, why=done["why"], denominator=denominator, arm_count=done["arm_count"],
                 fixes=done["fixes"], deleted=done["deleted"], scope_violations=done["scope_violations"])
    (base / "pipeline.json").write_text(json.dumps(prior))   # what `--rejudge` needs besides the kept store
    row = judge_row(claude, base, env, topic, arm, run, judge_model, prior)
    if not keep:
        shutil.rmtree(store, ignore_errors=True)   # large; the row and the session streams keep the evidence
    return row


def rejudge(claude: str, root: Path, env: dict, base: Path, judge_model: str) -> dict:
    """Judge the final synthesis of a kept pipeline folder again; the row is recorded as arm S, run 1."""
    base = base.resolve()
    topic = base.name.rsplit("-", 2)[0]
    prior = json.loads((base / "pipeline.json").read_text())
    assert (base / "store" / "syntheses" / f"{topic}.md").is_file(), f"{base} keeps no store (use --keep)"
    prior["sessions"] = [s for s in prior["sessions"] if s["role"] != "judge"]
    return judge_row(claude, base, env, topic, "S", 1, judge_model, prior)


# --- report --------------------------------------------------------------------------------------------------

def rate(r: dict) -> float:
    return 100.0 * r["unsupported"] / r["checked"] if r["checked"] else float("nan")


def coverage(r: dict) -> float:
    return 100.0 * r["used"] / r["denominator"] if r["denominator"] else float("nan")


HEADER = (f"{'topic':24} {'arm':3} {'run':3} {'valid':5} {'unsup/100':9} {'checked':7} {'words':5} {'parts':5} "
          f"{'cover':9} {'check':5} {'arm vs judge':14} {'fix':3} {'del':3} {'pipe USD':8} {'judge USD':9} {'wall s':6} "
          f"{'unlisted parts changed'}")


def table_line(r: dict) -> str:
    arm = "-" if r["arm_checked"] is None else f"{r['arm_unsupported']}/{r['arm_checked']} v {r['unsupported']}/{r['checked']}"
    return (f"{r['topic']:24} {r['arm']:3} {r['run']:<3} {str(r['valid']):5} {rate(r):9.1f} {r['checked']:<7} "
            f"{r['words']:<5} {r['parts']:<5} {r['used']}/{r['denominator']:<7} {str(r['mem_check']):5} {arm:14} "
            f"{r['fix_rounds']:<3} {r['deleted']:<3} {r['pipeline_cost']:<8.3f} {r['judge_cost']:<9.3f} {r['wall']:<6.0f} "
            f"{','.join(r['scope_violations']) or 'none'} {r['why']}")


def pooled(rows: list[dict]) -> dict:
    checked = sum(r["checked"] for r in rows)
    return dict(n=len(rows), rate=100.0 * sum(r["unsupported"] for r in rows) / checked if checked else float("nan"),
                checked=statistics.mean(r["checked"] for r in rows), words=statistics.mean(r["words"] for r in rows),
                cover=statistics.mean(coverage(r) for r in rows),
                cost=statistics.mean(r["pipeline_cost"] for r in rows), judge=statistics.mean(r["judge_cost"] for r in rows),
                mem_ok=all(r["mem_check"] == 0 for r in rows))


def spread(rows: list[dict]) -> float:
    """Mean over topics of the gap between an arm's runs on one topic, in points of unsupported rate."""
    gaps = []
    for topic in {r["topic"] for r in rows}:
        rates = [rate(r) for r in rows if r["topic"] == topic]
        if len(rates) > 1:
            gaps.append(max(rates) - min(rates))
    return statistics.mean(gaps) if gaps else 0.0


def decide(rows: list[dict]) -> list[str]:
    """The plan's decision rule (2026-11-17, prompts and loop): among L and M, the cheapest arm that qualifies against S,
    on the valid pipelines pooled over topics and runs."""
    by = {a: [r for r in rows if r["arm"] == a and r["valid"]] for a in ARMS}
    lines, stats = [], {}
    for arm, rs in by.items():
        if not rs:
            continue
        stats[arm] = p = pooled(rs)
        lines.append(f"{arm} valid={p['n']} unsupported/100={p['rate']:.1f} claims checked={p['checked']:.0f} "
                     f"words={p['words']:.0f} coverage={p['cover']:.0f}% mem check all 0={p['mem_ok']} "
                     f"pipeline cost={p['cost']:.3f} (judge {p['judge']:.3f}) run gap={spread(rs):.1f} points")
    challengers = [a for a in LEAN if a in stats]
    if "S" not in stats or not challengers:
        return lines + ["Decision rule: not applicable, S or both lean arms have no valid pipeline."]
    s, qualifying = stats["S"], {}
    for arm in challengers:
        h = stats[arm]
        checks = {f"unsupported {h['rate']:.1f} <= {s['rate']:.1f}+2": h["rate"] <= s["rate"] + 2,
                  f"claims {h['checked']:.0f} >= 80% of {s['checked']:.0f}": h["checked"] >= 0.8 * s["checked"],
                  f"coverage {h['cover']:.0f} >= {s['cover']:.0f}-10": h["cover"] >= s["cover"] - 10,
                  f"every {arm} synthesis passes mem check": h["mem_ok"],
                  f"pipeline cost (judge excluded) {h['cost']:.3f} <= 80% of {s['cost']:.3f}": h["cost"] <= 0.8 * s["cost"]}
        lines += [f"  {arm}: {text}: {ok}" for text, ok in checks.items()]
        if all(checks.values()):
            qualifying[arm] = h["cost"]
    if max(len([r for r in by[a] if r["topic"] == t]) for a in ("S", *challengers) for t in TOPICS) <= 1:
        lines.append("preliminary (1 run per topic): the variance rule cannot apply")
    if qualifying:
        best = min(qualifying, key=qualifying.get)
        return lines + [f"Verdict: ADOPT arm {best} (cheapest that qualifies)"]
    return lines + ["Verdict: KEEP today's pipeline (arm S) and record the gaps"]


# --- self-check ----------------------------------------------------------------------------------------------

def self_check() -> int:
    """No model: the copy, the deletion, the detachment and `mem synthesis new`; the owner's store is untouched."""
    real = real_store()
    before = trial_env._snapshot(real)
    root = trial_env.work_dir("mem-synthesis-check-")
    try:
        source = ensure_source()
        assert source.resolve().is_relative_to(trial_env.TARGET) and source != real
        assert not (source / ".git").exists() and not list(source.glob(".curation-log*")), "history was copied"
        env = trial_env.make_env(root)
        for topic in TOPICS:
            store = root / topic
            shutil.copytree(source, store)
            assert store.resolve().is_relative_to(trial_env.TARGET) and store.resolve() != real.resolve()
            assert (store / "syntheses" / f"{topic}.md").is_file(), f"no synthesis of {topic} to delete"
            denominator = prepare_store(store, env, topic)
            assert not (store / "syntheses" / f"{topic}.md").exists()
            assert 6 <= len(denominator) <= 12, f"{topic}: denominator {len(denominator)}"
            for rel in denominator:
                assert (store / rel).is_file() and front_part_of((store / rel).read_text()) is None, rel
                assert "part_of_hash" not in (store / rel).read_text(), rel
            assert mem(store, env, "check").returncode == 0, f"{topic}: mem check fails on the prepared copy"
            made = mem(store, env, "synthesis", "new", "--title", f"{topic} check", "--topics", topic, "--slug", topic,
                       "--summary-file", "-", stdin="A summary of the topic for the self-check.\n")
            assert made.returncode == 0, f"{topic}: mem synthesis new failed:\n{made.stdout}{made.stderr}"
            print(f"{topic}: denominator {len(denominator)}, synthesis new ok")
            shutil.rmtree(store)
        for name in ("writer", "checker", "fixer"):
            brief(name, TOPIC="t", SLUG="t", STORE="s", WORK_DIR="w", REPORT_FILE="r")   # every placeholder is filled
            raw = ((HERE if name == "writer" else sp.BRIEFS) / f"{name}-brief.md").read_text()
            assert "/home/" not in raw and "/tmp/" not in raw and "~/" not in raw, f"{name}-brief.md has a private path"
        sample = root / "r.md"
        sample.write_text("1. x\nNOTE: ../knowledge/a/b.md used\nNOTE: ../literature/c.md unused\n"
                          "COUNTS: checked=40 unsupported=3 used=1 unused=1\n")
        got = parse_report(sample)
        assert got["notes"] == {"knowledge/a/b.md": "used", "../literature/c.md": "unused"} and got["claims"] == [], got
        assert (got["checked"], got["unsupported"], got["parts"]) == (40, 3, []), got
        # the checker's own format: one line per claim, then PARTS and COUNTS
        sample.write_text("spaced-study | Spacing helps in every setting studied | absolute | ../knowledge/a/b.md | "
                          "Spacing helped in the pooled studies.\n"
                          "testing | Practice testing beat rereading by | figure-origin | ../knowledge/a/c.md | \n"
                          "PARTS: spaced-study, testing\nCOUNTS: checked=30 unsupported=2\n")
        first = parse_report(sample)
        assert (first["checked"], first["unsupported"], first["parts"]) == (30, 2, ["spaced-study", "testing"]), first
        assert [c["kind"] for c in first["claims"]] == ["absolute", "figure-origin"], first
        assert first["claims"][0]["fix"] == "Spacing helped in the pooled studies." and first["claims"][1]["fix"] == "", first
        sample.write_text("Spaced study | A sentence of seven words or so here | overstated | n | x\n"
                          "PARTS: s:t#spaced-study, Spaced study\nCOUNTS: checked=3 unsupported=1\n")
        assert parse_report(sample)["parts"] == ["spaced-study"], parse_report(sample)   # a heading is read as its handle
        sample.write_text("COUNTS: checked=30 unsupported=0\n")
        clean = parse_report(sample)
        assert clean["unsupported"] == 0 and clean["claims"] == [] and clean["parts"] == [], clean
        sample.write_text("no counts here\n")
        assert parse_report(sample) is None and parse_report(root / "missing.md") is None
        # scoped second check: the fixer's report goes through {PARTS}; without one, the first report's claims do
        answer = "Parts edited: spaced-study. Sentences changed: Spacing helped in the pooled studies. 0 deleted."
        assert scope_text(first, answer) == answer
        assert "testing: Practice testing beat rereading by" in scope_text(first, "")
        fill = dict(TOPIC="t", SLUG="t", STORE="s", WORK_DIR="w", REPORT_FILE="r")
        scoped = brief("checker", **fill, PARTS=scope_text(first, answer))
        assert answer in scoped and "{PARTS}" not in scoped
        assert NOT_GIVEN in brief("checker", **fill)
        # delete-only step and the byte-equal guard
        old_text = "---\ntitle: x\n---\n\n## Summary\n\nS.\n\n## Spaced study\n\nA. B.\n\n## Testing\n\nC. D.\n"
        assert list(split_parts(old_text)) == ["summary", "spaced-study", "testing"]
        assert changed_outside(old_text, old_text.replace("A. B.", "A."), ["spaced-study"]) == []
        assert changed_outside(old_text, old_text.replace("A. B.", "A.").replace("D.", "E."), ["spaced-study"]) == ["testing"]
        assert changed_outside(old_text, old_text.replace("title: x", "title: y"), []) == [], "front matter is not a part"
        assert "delete only" in brief("fixer", **fill) + DELETE_ONLY
        assert len(first["claims"]) == first["unsupported"] == 2   # what the row records as deleted
        def fake(arm, cost, unsupported, checked=60):
            return dict(topic="human-memory", arm=arm, run=1, valid=True, checked=checked, unsupported=unsupported, used=6,
                        denominator=6, words=3000, mem_check=0, cost=cost + 0.4, pipeline_cost=cost, judge_cost=0.4)
        verdict = decide([fake("S", 1.0, 2), fake("L", 0.7, 3), fake("M", 0.4, 3)])
        assert "preliminary (1 run per topic)" in " ".join(verdict) and verdict[-1].startswith("Verdict: ADOPT arm M"), verdict
        assert decide([fake("S", 1.0, 2), fake("L", 0.7, 3), fake("M", 0.5, 6)])[-1].startswith("Verdict: ADOPT arm L")
        assert decide([fake("S", 1.0, 2), fake("L", 0.9, 3), fake("M", 0.85, 3)])[-1].startswith("Verdict: KEEP")
        assert decide([fake("S", 1.0, 2), fake("M", 0.4, 3, checked=30)])[-1].startswith("Verdict: KEEP")
        assert trial_env._snapshot(real) == before, "a file of the owner's store changed"
    finally:
        trial_env.clean(root)
    print("self-check passed")
    return 0


# --- main ----------------------------------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude"))
    parser.add_argument("--self-check", action="store_true", help="no model: prove the fixture")
    parser.add_argument("--topic", action="append", default=[], help="topic id (repeatable)")
    parser.add_argument("--arm", action="append", choices=ARMS, default=[], help="default: S, L and M")
    parser.add_argument("--judge-model", default="haiku", help=f"the judge's model (always at --effort {CHEAP})")
    parser.add_argument("--rejudge", type=Path, metavar="PIPELINE_DIR",
                        help="judge the final synthesis of a kept pipeline folder (runs/<topic>-<arm>-<n> of an "
                             "earlier --keep run) again, recorded as arm S, run 1; needs --work")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--budget", type=float, default=10.0, help="USD; no new pipeline starts once the summed cost passes it")
    parser.add_argument("--work", type=Path, help="resume the work folder of an earlier run")
    parser.add_argument("--keep", action="store_true", help="keep the work folder and the store copies at the end")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if not args.claude:
        parser.error("--claude is required (no claude binary found)")
    topics, arms = args.topic or list(DEFAULT_TOPICS), args.arm or list(ARMS)
    root = args.work.resolve() if args.work else trial_env.work_dir("mem-synthesis-")
    env = trial_env.make_env(root)
    state_file = root / STATE
    rows = json.loads(state_file.read_text()) if state_file.is_file() else []
    rows = [r for r in rows if r["valid"]]   # an invalid pipeline is rerun from scratch on resume
    if args.rejudge:
        if not args.work:
            parser.error("--rejudge needs --work (the folder whose state.json receives the row)")
        row = rejudge(args.claude, root, env, args.rejudge, args.judge_model)
        rows = [r for r in rows if (r["topic"], r["arm"], r["run"]) != (row["topic"], "S", 1)] + [row]
        state_file.write_text(json.dumps(rows, indent=1))
        print(HEADER + "\n" + table_line(row))
        return 0
    done = {(r["topic"], r["arm"], r["run"]) for r in rows}
    todo = [(t, a, n) for t in topics for a in arms for n in range(1, args.runs + 1) if (t, a, n) not in done]
    lock = threading.Lock()
    print(f"work folder: {root}; {len(todo)} pipelines to run, {len(done)} already done", flush=True)
    print(HEADER, flush=True)
    ensure_source()

    def task(item):
        topic, arm, n = item
        with lock:
            spent = sum(r["cost"] for r in rows)
        if spent > args.budget:
            print(f"budget {args.budget:.2f} USD passed ({spent:.2f}): {topic}-{arm}-{n} not started", flush=True)
            return
        row = one_pipeline(args.claude, root, env, topic, arm, n, args.keep, args.judge_model)
        with lock:
            rows.append(row)
            state_file.write_text(json.dumps(rows, indent=1))
            print(table_line(row), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(task, todo))
    print("\n" + "\n".join(decide(rows)))
    print(f"total cost USD over all sessions: {sum(r['cost'] for r in rows):.3f}")
    # The rows outlive the work folder: a clean run must not lose its results (it did once).
    results = trial_env.TARGET / f"synthesis-results-{time.strftime('%Y%m%d-%H%M%S')}.json"
    results.write_text(json.dumps({"rows": rows, "decision": decide(rows)}, indent=1))
    print(f"results: {results}")
    if all(r["valid"] for r in rows) and not args.keep:
        trial_env.clean(root)
    else:
        print(f"work folder kept (state.json has every row): {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
