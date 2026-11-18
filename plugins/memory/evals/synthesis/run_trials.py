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

Arm R: M's models and effort with the current texts (writer brief, skill, checker and fixer briefs). Arm M runs on the
frozen texts of `main` (`frozen-main/`), so M and R compare the pipeline before and after inline references. The judge is
the same for every arm: the frozen checker brief, reading the synthesis with its references removed.

Usage: run_trials.py [--claude PATH] [--topic T]... [--arm S|L|M|R]... [--judge-model haiku] [--runs 1] [--jobs 2]
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
import syntheses  # noqa: E402
from synth_pipeline import (CHEAP, DELETE_ONLY, NOT_GIVEN, brief as _brief, changed_outside, cost_by_family, mem,  # noqa: E402,F401
                            parse_report, resolve_parts, run_session, scope_text, section_handle, split_parts,
                            summary)

HERE = Path(__file__).resolve().parent
PLUGIN = trial_env.PLUGIN
SOURCE = trial_env.TARGET / "synthesis-source"
ATTACHED = trial_env.TARGET / "synthesis-source-attached.json"
TOPICS = ("human-memory", "time-series-forecasting", "llm-evaluation", "mental-health")
DEFAULT_TOPICS = TOPICS[:3]
ARMS = ("S", "L", "M", "R")
DEFAULT_ARMS = ("S", "L", "M")
WRITER = {"S": ("sonnet", None), "L": ("sonnet", None), "M": ("haiku", "high"), "R": ("haiku", "high")}   # model, effort
LEAN = ("L", "M", "R")
FROZEN = HERE / "frozen-main"
FROZEN_ARMS = ("M",)   # the control runs the texts of `main`
PREPARED = trial_env.TARGET / "synthesis-source-prepared.json"   # what making the copy changed in it
# The proposed rule of R against M (owner fixes it before a run; constants, never options).
R_RATE_MARGIN = 2.0      # R's unsupported/100 <= M's + max(this, gap between M's runs), in points
R_COST_FACTOR = 1.3      # R's mean pipeline cost must stay below this times M's
PRELIM_MIN_RUNS = 2      # fewer runs per arm than this: preliminary
PRELIM_MAX_GAP = 4.0     # M's runs differing by more than this many points: preliminary
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
    if (SOURCE / "mem-store.yaml").is_file() and ATTACHED.is_file() and PREPARED.is_file():
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
    PREPARED.write_text(json.dumps({"refs_removed": drop_unlisted_references(SOURCE)}))
    return SOURCE


def drop_unlisted_references(store: Path) -> int:
    """Remove from the (trial) copy `store` every reference that names a note missing from its part's `Sources:` line,
    the case `syntheses.validate_section` refuses; return how many were removed. Never run it on a real store."""
    base, total = store / syntheses.SYNTHESES_DIR, 0
    for path in sorted(base.glob("*.md")):
        text, syn = path.read_text(), syntheses.load_one(path)
        if syn.error:
            continue
        for part in syn.parts:
            line = syntheses._sources_line(part.text) or ""
            listed = {syntheses._resolved(base, t) for t in syntheses._links(line) if syntheses._relative(t)}
            _, every, _, body_end = syntheses._parse(part.text)
            bad = [r for r in every if syntheses._resolved(base, r.target) not in listed]
            if bad:
                new = syntheses._remove(part.text, 0, body_end, bad) + part.text[body_end:]
                text, total = syntheses.apply_part_text(text, part.handle, new), total + len(bad)
        path.write_text(text)
    return total


def references_removed() -> int:
    """How many references `ensure_source` removed from the trial copy of the store."""
    return json.loads(PREPARED.read_text())["refs_removed"]


def texts(arm: str) -> dict:
    """Where an arm's writer brief, skill and checker/fixer briefs are read from."""
    if arm in FROZEN_ARMS:
        return dict(writer=FROZEN, skill=FROZEN / "SKILL.md", briefs=FROZEN)
    return dict(writer=HERE, skill=sp.SKILL, briefs=sp.BRIEFS)


def without_references_text(path: Path) -> str:
    """The synthesis file's text with the references of every part's body (Summary included) removed."""
    text = path.read_text()
    for section in syntheses.load_one(path).sections:
        text = syntheses.apply_part_text(text, section.handle, syntheses.without_references(section.text))
    return text


def tokens(text: str) -> float:
    return len(text) / 4


def brief(name: str, folder: Path | None = None, **values: str) -> str:
    """A brief from `folder`: by default the writer's is the trial's own (the command uses the `memory-synthesizer`
    agent instead) and the others are the engine's."""
    return _brief(name, folder or (HERE if name == "writer" else sp.BRIEFS), **values)


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
    judged, check_exit, words, parts, size = None, None, 0, 0, dict(tokens_stored=None, tokens_shown=None)
    if synthesis.is_file():
        check_exit = mem(store, env, "check").returncode
        words, parts = synthesis_facts(synthesis)
        stored = synthesis.read_text()
        size = dict(tokens_stored=tokens(stored), tokens_shown=tokens(syntheses.shown_file(stored)))
        report = work / "judge-report.md"
        report.unlink(missing_ok=True)
        fill = dict(TOPIC=topic, SLUG=topic, STORE=str(store), WORK_DIR=str(work))
        # The judge reads the file in place without its references (the same count for every arm and the baseline);
        # the stored text is put back afterwards, so a later step measures the run's own synthesis.
        synthesis.write_text(without_references_text(synthesis))
        try:
            s = run_session(claude, judge_model, brief("checker", FROZEN, **fill, REPORT_FILE=str(report)) + JUDGE_EXTRA,
                            work, settings, env, base / f"{len(sessions) + 1:02d}-judge.jsonl", effort=CHEAP)
        finally:
            synthesis.write_text(stored)
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
        words=words, parts=parts, **size, used=len(used & set(denominator)), mem_check=check_exit, fix_rounds=prior["fixes"],
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
    t = texts(arm)
    s = run_session(claude, writer_model, brief("writer", t["writer"], SKILL_FILE=str(t["skill"]), **fill), work, settings, env, base / "01-writer.jsonl",
                    effort=writer_effort)
    s.update(role="writer", model=writer_model, costs=cost_by_family(s["model_usage"]))
    sessions.append(summary(s))
    done = dict(arm_count=None, why="no synthesis written", fixes=0, deleted=0, scope_violations=[])
    if synthesis.is_file():
        done = sp.lean_loop(claude, env, base, store, work, settings, topic, sessions, lean=arm in LEAN,
                            briefs=t["briefs"])
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
          f"{'tok file':8} {'tok shown':9} {'cover':9} {'check':5} {'arm vs judge':14} {'fix':3} {'del':3} {'pipe USD':8} {'judge USD':9} {'wall s':6} "
          f"{'unlisted parts changed'}")


def fmt_tokens(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def table_line(r: dict) -> str:
    arm = "-" if r["arm_checked"] is None else f"{r['arm_unsupported']}/{r['arm_checked']} v {r['unsupported']}/{r['checked']}"
    return (f"{r['topic']:24} {r['arm']:3} {r['run']:<3} {str(r['valid']):5} {rate(r):9.1f} {r['checked']:<7} "
            f"{r['words']:<5} {r['parts']:<5} {fmt_tokens(r.get('tokens_stored')):8} {fmt_tokens(r.get('tokens_shown')):9} {r['used']}/{r['denominator']:<7} {str(r['mem_check']):5} {arm:14} "
            f"{r['fix_rounds']:<3} {r['deleted']:<3} {r['pipeline_cost']:<8.3f} {r['judge_cost']:<9.3f} {r['wall']:<6.0f} "
            f"{','.join(r['scope_violations']) or 'none'} {r['why']}")


def pooled(rows: list[dict]) -> dict:
    checked = sum(r["checked"] for r in rows)
    return dict(n=len(rows), rate=100.0 * sum(r["unsupported"] for r in rows) / checked if checked else float("nan"),
                checked=statistics.mean(r["checked"] for r in rows), words=statistics.mean(r["words"] for r in rows),
                cover=statistics.mean(coverage(r) for r in rows),
                tok_stored=statistics.mean(r.get("tokens_stored") or 0 for r in rows),
                tok_shown=statistics.mean(r.get("tokens_shown") or 0 for r in rows),
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


def run_gap(rows: list[dict]) -> float:
    """The absolute gap between an arm's runs: each run's rate pooled over its topics, largest minus smallest (0 with one run)."""
    rates = [pooled([r for r in rows if r["run"] == n])["rate"] for n in sorted({r["run"] for r in rows})]
    return max(rates) - min(rates) if len(rates) > 1 else 0.0


def reference_conditions(r_rows: list[dict], m_rows: list[dict]) -> list[tuple[str, bool]]:
    """Conditions on reference coverage and wrong references: added by the task that judges references."""
    return []


def decide_r_against_m(by: dict, stats: dict) -> list[str]:
    """The proposed rule of R against M, on the valid pipelines pooled over topics and runs."""
    if not by["R"] or not by["M"]:
        return ["R against M: not applicable, R or M has no valid pipeline."]
    r, m = stats["R"], stats["M"]
    gap = run_gap(by["M"])
    margin = max(R_RATE_MARGIN, gap)
    checks = [(f"unsupported {r['rate']:.1f} <= M's {m['rate']:.1f} + max({R_RATE_MARGIN}, run gap {gap:.1f}) = "
               f"{m['rate'] + margin:.1f}", r["rate"] <= m["rate"] + margin),
              (f"pipeline cost {r['cost']:.3f} < {R_COST_FACTOR} x M's {m['cost']:.3f} = {R_COST_FACTOR * m['cost']:.3f}",
               r["cost"] < R_COST_FACTOR * m["cost"])]
    checks += reference_conditions(by["R"], by["M"])
    runs = {a: len({x["run"] for x in by[a]}) for a in ("R", "M")}
    notes = []
    if min(runs.values()) < PRELIM_MIN_RUNS:
        notes.append(f"fewer than {PRELIM_MIN_RUNS} runs per arm (R {runs['R']}, M {runs['M']})")
    if gap > PRELIM_MAX_GAP:
        notes.append(f"M's runs differ by {gap:.1f} points (> {PRELIM_MAX_GAP})")
    lines = [f"  R against M: {text}: {'passed' if ok else 'FAILED'}" for text, ok in checks]
    if notes:
        lines.append("preliminary: " + "; ".join(notes))
    ok = all(ok for _, ok in checks)
    return lines + [f"Verdict R against M: {'PASS' if ok else 'FAIL'}" + (" (preliminary)" if notes else "")]


def decide(rows: list[dict]) -> list[str]:
    """The plan's decision rule (2026-11-17, prompts and loop) among S, L and M, then R against M."""
    by = {a: [r for r in rows if r["arm"] == a and r["valid"]] for a in ARMS}
    lines, stats = [], {}
    for arm, rs in by.items():
        if not rs:
            continue
        stats[arm] = p = pooled(rs)
        lines.append(f"{arm} valid={p['n']} unsupported/100={p['rate']:.1f} claims checked={p['checked']:.0f} "
                     f"words={p['words']:.0f} tokens file={p['tok_stored']:.0f} shown={p['tok_shown']:.0f} "
                     f"coverage={p['cover']:.0f}% mem check all 0={p['mem_ok']} "
                     f"pipeline cost={p['cost']:.3f} (judge {p['judge']:.3f}) run gap={spread(rs):.1f} points")
    if by["R"]:
        lines += decide_r_against_m(by, stats)
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


def harness_checks(root: Path, env: dict) -> None:
    """No model and no real store: frozen texts, the arms' files, the judge's copy, the store preparation, rule F."""
    fill = dict(TOPIC="t", SLUG="t", STORE="s", WORK_DIR="w", REPORT_FILE="r")
    for name in ("writer", "checker", "fixer"):
        assert (FROZEN / f"{name}-brief.md").is_file(), name
    assert (FROZEN / "SKILL.md").is_file() and (FROZEN / "README.md").is_file()
    for arm in ARMS:
        t = texts(arm)
        for name in ("writer", "checker", "fixer"):
            text = brief(name, t["writer"] if name == "writer" else t["briefs"], SKILL_FILE=str(t["skill"]), **fill)
            assert not re.findall(r"\{[A-Z_]+\}", text), (arm, name)
    assert "--stored" in (FROZEN / "fixer-brief.md").read_text() and "{UNITS_FILE}" not in (FROZEN / "checker-brief.md").read_text()
    assert texts("M") == dict(writer=FROZEN, skill=FROZEN / "SKILL.md", briefs=FROZEN)
    assert texts("R") == texts("S") == texts("L") == dict(writer=HERE, skill=sp.SKILL, briefs=sp.BRIEFS)
    assert "M" in LEAN and "R" in LEAN and "R" not in DEFAULT_ARMS and WRITER["R"] == WRITER["M"]
    # store preparation (D) on an invented store
    store = root / "demo-store"
    (store / "syntheses").mkdir(parents=True)
    for rel in ("knowledge/x/a.md", "literature/b.md"):
        (store / rel).parent.mkdir(parents=True, exist_ok=True)
        (store / rel).write_text("note\n")
    path = store / "syntheses" / "demo.md"
    path.write_text(DEMO)
    assert drop_unlisted_references(store) == 2   # Alpha's two Beta references; Beta's own and the Summary's stay
    prepared = path.read_text()
    assert prepared == DEMO.replace(" [Beta note](../literature/b.md) [Alpha", " [Alpha").replace("see [Beta note](../literature/b.md) here", "see Beta note here"), prepared
    for part in syntheses.load_one(path).parts:
        assert not [p for p in syntheses.validate_section(part.text, store) if "not on the `Sources:` line" in p], part.handle
    assert drop_unlisted_references(store) == 0
    # the judge's copy has no reference in a body while the run's file keeps them
    path.write_text(DEMO)
    stripped = without_references_text(path)
    for section in syntheses.load_one(path).sections:
        assert syntheses.references(section.text), section.handle
    path.write_text(stripped)
    assert all(not syntheses.references(sec.text) for sec in syntheses.load_one(path).sections)
    assert [ln for ln in stripped.splitlines() if ln.startswith("Sources:")] == [ln for ln in DEMO.splitlines() if ln.startswith("Sources:")]
    path.write_text(DEMO)
    # judge_row with a stub session: sees the stripped file and the frozen checker brief, leaves the stored file back
    base = root / "judge-fixture"
    shutil.copytree(store, base / "store")
    (base / "work").mkdir()
    (base / "settings.json").write_text("{}")
    seen = {}

    def stub(claude, model, prompt, work, settings, env_, log, **kw):
        seen["file"] = (base / "store" / "syntheses" / "demo.md").read_text()
        seen["prompt"] = prompt
        (work / "judge-report.md").write_text("COUNTS: checked=10 unsupported=1 used=1 unused=0\n")
        return dict(model_usage={"claude-haiku-4-5": dict(costUSD=0.01)}, has_result=True, error="", cost=0.01, wall=1.0,
                    writes=0, write_errors=0, denied=False, tool_errors=0, answer="")
    original = globals()["run_session"]
    globals()["run_session"] = stub
    try:
        (base / "store" / "syntheses" / "demo.md").write_text(DEMO)
        row = judge_row("claude", base, env, "demo", "M", 1, "haiku",
                        dict(sessions=[], why="", denominator=["knowledge/x/a.md"], arm_count=None, fixes=0))
    finally:
        globals()["run_session"] = original
    seen_path = root / "seen.md"
    seen_path.write_text(seen["file"])
    assert all(not syntheses.references(sec.text) for sec in syntheses.load_one(seen_path).sections), seen["file"]
    assert seen["file"].count("Sources:") == 2
    assert (base / "store" / "syntheses" / "demo.md").read_text() == DEMO, "the run's file was not restored"
    assert (FROZEN / "checker-brief.md").read_text().split("{")[0] in seen["prompt"] and JUDGE_EXTRA in seen["prompt"]
    assert row["tokens_stored"] == len(DEMO) / 4 and row["tokens_shown"] == len(syntheses.shown_file(DEMO)) / 4
    assert row["tokens_shown"] < row["tokens_stored"] and row["checked"] == 10, row
    # rule F on three synthetic result sets
    def runs(arm, rates, cost):
        return [dict(topic="human-memory", arm=arm, run=n, valid=True, checked=100, unsupported=rate, used=6, denominator=6,
                     words=3000, mem_check=0, cost=cost + 0.4, pipeline_cost=cost, judge_cost=0.4)
                for n, rate in enumerate(rates, 1)]
    ok = decide(runs("M", [5, 6], 0.4) + runs("R", [6, 7], 0.45))
    assert ok[-1] == "Verdict R against M: PASS" and not any(x.startswith("preliminary") for x in ok), ok
    bad = decide(runs("M", [5, 6], 0.4) + runs("R", [12, 12], 0.45))
    assert bad[-1] == "Verdict R against M: FAIL" and any("FAILED" in x and "unsupported" in x for x in bad), bad
    assert decide(runs("M", [5, 6], 0.4) + runs("R", [6, 7], 0.6))[-1] == "Verdict R against M: FAIL"   # cost 0.6 >= 1.3 x 0.4
    assert decide(runs("M", [5], 0.4) + runs("R", [6], 0.45))[-1] == "Verdict R against M: PASS (preliminary)"
    assert decide(runs("M", [3, 9], 0.4) + runs("R", [6, 7], 0.45))[-1].endswith("(preliminary)")
    assert run_gap(runs("M", [3, 9], 0.4)) == 6.0 and run_gap(runs("M", [3], 0.4)) == 0.0

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
        harness_checks(root, env)
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
    parser.add_argument("--arm", action="append", choices=ARMS, default=[], help="default: S, L and M; R is M's models with the current texts")
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
    topics, arms = args.topic or list(DEFAULT_TOPICS), args.arm or list(DEFAULT_ARMS)
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
    print(f"references removed from the trial copy of the store: {references_removed()}")
    print(f"total cost USD over all sessions: {sum(r['cost'] for r in rows):.3f}")
    # The rows outlive the work folder: a clean run must not lose its results (it did once).
    results = trial_env.TARGET / f"synthesis-results-{time.strftime('%Y%m%d-%H%M%S')}.json"
    results.write_text(json.dumps({"rows": rows, "decision": decide(rows), "source_refs_removed": references_removed()},
                                  indent=1))
    print(f"results: {results}")
    if all(r["valid"] for r in rows) and not args.keep:
        trial_env.clean(root)
    else:
        print(f"work folder kept (state.json has every row): {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
