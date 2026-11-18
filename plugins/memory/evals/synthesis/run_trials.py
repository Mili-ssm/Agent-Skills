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

Reference judgment (arms M and R, off with --no-ref-judge): a second judge session reads the synthesis with its
references (`ref-judge-brief.md`) and says which sentences state a finding and whether each linked note supports its
sentence; code computes coverage and wrong references from that report. For arm R, 20 wrong references are planted
over the judged syntheses to see whether the judge finds them (calibration). `--backfill-trial` runs
`mem-synthesize --backfill` on a copy of the prepared store and checks what it did, then undoes it with `mem restore`.

Usage: run_trials.py [--claude PATH] [--topic T]... [--arm S|L|M|R]... [--judge-model haiku] [--runs 1] [--jobs 2]
                     [--budget USD (10)] [--work DIR (resume)] [--keep] [--no-ref-judge]
       run_trials.py --backfill-trial [--synthesis HANDLE]... [--budget USD] [--claude PATH] [--keep] | --self-check
It costs model usage (9 pipelines and 9 judges at the defaults, about 7 to 9 USD); no pipeline starts once the summed
cost passes --budget. --rejudge reuses a kept pipeline folder (run an earlier pipeline with --keep).
"""
from __future__ import annotations

import argparse
import json
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
# Reference conditions of R (proposed; the owner fixes them before a run) and the calibration of the reference judge.
R_MIN_COVERAGE = 0.80          # covered findings / findings over all R rows
R_MAX_WRONG = 0.05             # wrong references / judged references over all R rows
R_MAX_SHOWN_GROWTH = 1.15      # R's mean tokens_shown / M's
REF_MAX_UNJUDGED = 0.10        # a reference report leaving more than this share of the units unjudged is unreliable
CALIBRATION_PLANTED = 20       # wrong references planted over the judged syntheses
CALIBRATION_MIN_FOUND = 16     # the judgment is valid when it marks this many of them `no` (scaled when fewer are plantable)
# Backfill trial.
BACKFILL_SAMPLE = 100          # new references sampled for the wrong count
BACKFILL_MAX_WRONG = 1         # wrong ones allowed in that sample
BACKFILL_MIN_COVERAGE = 0.60   # covered findings / findings after the backfill
BACKFILL_MAX_NONE = 0.20       # `none` answers / units sent
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
                 judge_model: str, ref_judge: bool = False, quota: Quota | None = None) -> dict:
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
    if ref_judge and synthesis.is_file():
        row["ref"], more = reference_run(claude, base, env, topic, judge_model, quota if arm == "R" else None)
        add_sessions(row, more)
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


# --- reference judgment --------------------------------------------------------------------------------------

_REPORT_LINE = re.compile(r"^(?:[-*+]\s+)?`*\s*([UP]):\s*(.*?)\s*`*$")


def _norm(target: str) -> str:
    return posixpath.normpath(target.strip().strip("`").strip())


def parse_ref_report(text: str) -> dict:
    """The reference judge's report: `units` ((part, number) -> finding|other), `pairs` ((part, number, path) -> True
    for yes), and `unreadable` (lines that start with `U:` or `P:` and do not parse). Tolerates a bullet, backticks
    and white space around a line; the last of two lines for the same key wins."""
    units: dict[tuple[str, int], str] = {}
    pairs: dict[tuple[str, int, str], bool] = {}
    unreadable = 0
    for raw in text.splitlines():
        m = _REPORT_LINE.match(raw.strip())
        if not m:
            continue
        kind, rest = m.groups()
        cells = [c.strip().strip("`").strip() for c in rest.split("|")]
        if len(cells) < 3 or not cells[1].isdigit():
            unreadable += 1
            continue
        key = (cells[0].split("#")[-1].strip(), int(cells[1]))
        if kind == "U" and len(cells) == 3 and cells[2].lower() in ("finding", "other"):
            units[key] = cells[2].lower()
        elif kind == "P" and len(cells) == 4 and cells[3].lower() in ("yes", "no"):
            pairs[key + (_norm(cells[2]),)] = cells[3].lower() == "yes"
        else:
            unreadable += 1
    return dict(units=units, pairs=pairs, unreadable=unreadable)


def file_units(path: Path) -> list[tuple[str, int, list[str]]]:
    """(part handle, unit number, normalized reference targets without repeats) for every unit of the file's parts."""
    out = []
    for section in syntheses.load_one(path).parts:
        found, _ = syntheses.units(section.text)
        out += [(section.handle, u.n, [_norm(t) for t in dict.fromkeys(u.refs)]) for u in found]
    return out


def score_refs(path: Path, parsed: dict | None, session_ok: bool = True) -> tuple[dict, dict]:
    """Facts of one reference report against the stored file, by code: `findings`, `covered` (findings whose unit
    carries a reference), `pairs` and `wrong` (judged references, those marked `no`), `unjudged` (units and references
    with no line), `unreliable`. Also the verdict of each judged pair, (part, number, path) -> True for yes."""
    expected = file_units(path)
    findings = covered = pairs = wrong = unjudged = 0
    verdicts: dict[tuple[str, int, str], bool] = {}
    for handle, n, refs in expected:
        kind = parsed["units"].get((handle, n)) if parsed else None
        if kind is None:
            unjudged += 1
        elif kind == "finding":
            findings += 1
            covered += bool(refs)
        for target in refs:
            verdict = parsed["pairs"].get((handle, n, target)) if parsed else None
            if verdict is None:
                unjudged += 1
            else:
                pairs += 1
                wrong += not verdict
                verdicts[(handle, n, target)] = verdict
    unreliable = parsed is None or not session_ok or unjudged > REF_MAX_UNJUDGED * len(expected)
    return (dict(units=len(expected), findings=findings, covered=covered, pairs=pairs, wrong=wrong, unjudged=unjudged,
                 unreadable=parsed["unreadable"] if parsed else 0, unreliable=unreliable, cal=None), verdicts)


def plant_references(path: Path, verdicts: dict, quota: int, rng: random.Random) -> tuple[str, list[tuple[str, int, str]]]:
    """The file's text with up to `quota` references swapped for a wrong one, and the planted pairs (part, number, path).

    A candidate is a trailing reference the judge marked `yes`, in a part with at least two note sources, on a unit that
    does not carry one of them: the reference's label and target become that source's. One swap per unit."""
    base, text = path.parent, path.read_text()
    chosen = []   # (part handle, unit number, reference, (label, target) of the source that replaces it)
    for section in syntheses.load_one(path).parts:
        sources: dict[Path, tuple[str, str]] = {}
        for m in syntheses._REF_LINK.finditer(syntheses._sources_line(section.text) or ""):
            if syntheses._is_ref(m.group(2)):
                sources.setdefault(syntheses._resolved(base, m.group(2)), (m.group(1), m.group(2)))
        if len(sources) < 2:
            continue
        found, refs, orphans, _ = syntheses._parse(section.text)
        orphan_at = {r.start for r in orphans}
        for unit in found:
            own = [r for r in refs if unit.span[0] <= r.start < unit.span[1] and r.start not in orphan_at]
            carried = {syntheses._resolved(base, r.target) for r in own}
            other = [v for k, v in sources.items() if k not in carried]
            ok = [r for r in own if r.trailing
                  and verdicts.get((section.handle, unit.n, _norm(syntheses._file_part(r.target)))) is True]
            if ok and other:
                chosen.append((section.handle, unit.n, ok, other))
    planted, edits = [], {}
    for handle, n, ok, other in rng.sample(chosen, min(quota, len(chosen))):
        ref, (label, target) = rng.choice(ok), rng.choice(other)
        edits.setdefault(handle, []).append((ref.start, ref.end, f"[{label}]({target})"))
        planted.append((handle, n, _norm(syntheses._file_part(target))))
    for section in syntheses.load_one(path).parts:
        if section.handle in edits:
            new = section.text
            for start, end, repl in sorted(edits[section.handle], reverse=True):
                new = new[:start] + repl + new[end:]
            text = syntheses.apply_part_text(text, section.handle, new)
    return text, planted


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
    return planted > 0 and found >= calibration_min(planted)


def ref_session(claude: str, base: Path, env: dict, handle: str, judge_model: str, role: str) -> tuple[dict | None, dict]:
    """One reference-judge session on `base/store`'s synthesis `handle`, as the file stands now; the parsed report
    (None when unreadable) and the session's summary."""
    store, work = base / "store", base / "work"
    synthesis = store / "syntheses" / f"{handle}.md"
    units, report = work / f"{role}-units-{handle}.md", work / f"{role}-report-{handle}.md"
    report.unlink(missing_ok=True)
    sp.write_units(synthesis, units)
    prompt = brief("ref-judge", HERE, SLUG=handle, STORE=str(store), UNITS_FILE=str(units), REPORT_FILE=str(report))
    s = run_session(claude, judge_model, prompt, work, base / "settings.json", env, base / f"{role}-{handle}.jsonl",
                    effort=CHEAP)
    s.update(role=role, model=judge_model, costs=cost_by_family(s["model_usage"]))
    parsed = parse_ref_report(report.read_text()) if report.is_file() else None
    if parsed is not None and not parsed["units"] and not parsed["pairs"]:
        parsed = None
    return parsed, summary(s)


def calibrate(claude: str, base: Path, env: dict, handle: str, judge_model: str, verdicts: dict, quota: int) -> tuple[dict, list[dict]]:
    """Plant up to `quota` wrong references in the synthesis `handle` for one reference-judge session, put the stored
    bytes back in a `finally`, and count the planted pairs the judge marks `no`."""
    synthesis = base / "store" / "syntheses" / f"{handle}.md"
    stored = synthesis.read_bytes()
    text, planted = plant_references(synthesis, verdicts, quota, random.Random(0))
    if not planted:
        return dict(planted=0, found=0), []
    synthesis.write_text(text)
    try:
        parsed, s = ref_session(claude, base, env, handle, judge_model, "ref-calibration")
    finally:
        synthesis.write_bytes(stored)
    found = sum(1 for key in planted if parsed is not None and parsed["pairs"].get(key) is False)
    return dict(planted=len(planted), found=found), [s]


def reference_run(claude: str, base: Path, env: dict, handle: str, judge_model: str, quota: Quota | None) -> tuple[dict, list[dict]]:
    """The reference judgment of the synthesis `handle` in `base/store` (its row's `ref`) and the sessions it started;
    with a `quota`, also the calibration of that judgment."""
    synthesis = base / "store" / "syntheses" / f"{handle}.md"
    parsed, s = ref_session(claude, base, env, handle, judge_model, "ref-judge")
    ref, verdicts = score_refs(synthesis, parsed, s["ok"])
    sessions = [s]
    if quota is not None:
        cal, more = calibrate(claude, base, env, handle, judge_model, verdicts, quota.take())
        quota.spent(cal["planted"])
        ref["cal"], sessions = cal, sessions + more
    return ref, sessions


def add_sessions(row: dict, sessions: list[dict]) -> None:
    """Fold the reference sessions into the row's judge cost (never the pipeline's), wall time and per-model costs."""
    row["sessions"] = row["sessions"] + sessions
    for s in sessions:
        row["cost"] += s["cost"]
        row["judge_cost"] += s["cost"]
        row["wall"] += s["wall"]
        for family, cost in s["costs"].items():
            row["costs"][family] = row["costs"].get(family, 0.0) + cost


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


def ref_totals(rows: list[dict]) -> dict:
    """Reference counts summed over the rows that have a reference judgment."""
    judged = [r["ref"] for r in rows if r.get("ref")]
    cals = [c for c in (x["cal"] for x in judged) if c]
    return dict(rows=len(judged), findings=sum(x["findings"] for x in judged), covered=sum(x["covered"] for x in judged),
                pairs=sum(x["pairs"] for x in judged), wrong=sum(x["wrong"] for x in judged),
                unreliable=sum(bool(x["unreliable"]) for x in judged), planted=sum(c["planted"] for c in cals),
                found=sum(c["found"] for c in cals))


def reference_conditions(r_rows: list[dict], m_rows: list[dict]) -> list[tuple[str, bool]]:
    """Conditions of R on references (none when the rows carry no reference judgment): coverage of findings, wrong
    references, and the size a reader gets (tokens shown) against M's."""
    t = ref_totals(r_rows)
    if not t["rows"]:
        return []
    coverage_ = t["covered"] / t["findings"] if t["findings"] else 0.0
    wrong = t["wrong"] / t["pairs"] if t["pairs"] else 1.0
    shown_r = statistics.mean(r.get("tokens_shown") or 0 for r in r_rows)
    shown_m = statistics.mean(r.get("tokens_shown") or 0 for r in m_rows)
    grew = not shown_m or shown_r > R_MAX_SHOWN_GROWTH * shown_m
    return [(f"reference coverage {coverage_:.2f} ({t['covered']}/{t['findings']}) >= {R_MIN_COVERAGE}",
             t["findings"] > 0 and coverage_ >= R_MIN_COVERAGE),
            (f"wrong references {wrong:.3f} ({t['wrong']}/{t['pairs']}) <= {R_MAX_WRONG}",
             t["pairs"] > 0 and wrong <= R_MAX_WRONG),
            (f"tokens shown {shown_r:.0f} <= {R_MAX_SHOWN_GROWTH} x M's {shown_m:.0f} = {R_MAX_SHOWN_GROWTH * shown_m:.0f}"
             + (" (do not adopt: shorten the label rule first)" if grew else ""), not grew)]


def reference_notes(r_rows: list[dict]) -> tuple[list[str], list[str]]:
    """The calibration line of R's reference judgment, and the reasons it makes the result preliminary."""
    t = ref_totals(r_rows)
    if not t["rows"]:
        return [], []
    need, valid = calibration_min(t["planted"]), calibration_valid(t["planted"], t["found"])
    line = (f"  reference judge calibration: {t['found']} of {t['planted']} planted wrong references found "
            f"(needs {need}): {'valid' if valid else 'NOT valid'}")
    notes = []
    if not valid:
        notes.append("the reference judge's calibration is not valid")
    elif t["planted"] < CALIBRATION_PLANTED:
        notes.append(f"only {t['planted']} wrong references could be planted (threshold scaled to {need})")
    if t["unreliable"]:
        notes.append(f"{t['unreliable']} of {t['rows']} reference reports are unreliable (over {REF_MAX_UNJUDGED:.0%} of "
                     f"the units unjudged)")
    return [line], notes


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
    ref_lines, notes = reference_notes(by["R"])
    if min(runs.values()) < PRELIM_MIN_RUNS:
        notes.append(f"fewer than {PRELIM_MIN_RUNS} runs per arm (R {runs['R']}, M {runs['M']})")
    if gap > PRELIM_MAX_GAP:
        notes.append(f"M's runs differ by {gap:.1f} points (> {PRELIM_MAX_GAP})")
    lines = [f"  R against M: {text}: {'passed' if ok else 'FAILED'}" for text, ok in checks] + ref_lines
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
        if (t := ref_totals(rs))["rows"]:
            lines.append(f"  {arm} references: coverage {t['covered']}/{t['findings']} findings, wrong {t['wrong']}/{t['pairs']}, "
                         f"{t['unreliable']} unreliable reports")
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


# --- backfill trial ------------------------------------------------------------------------------------------

def parse_backfill_table(text: str) -> tuple[list[dict], dict | None]:
    """The table `mem-synthesize --backfill` prints: (a dict per synthesis row, the `total` row or None), keyed by the
    header's column names, never by position. Cells are cut at the columns' starting offsets in the header, because a
    blank cell (the total row has some) leaves no field to split on."""
    lines = text.splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.startswith("synthesis") and "parts" in ln), None)
    if head is None:
        return [], None
    names = re.split(r"\s{2,}", lines[head].strip())
    starts, at = [], 0
    for name in names:
        at = lines[head].index(name, at)
        starts.append(at)
        at += len(name)
    ends = starts[1:] + [None]
    rows, total = [], None
    for line in lines[head + 1:]:
        if not line.strip() or line.startswith("total cost"):
            break
        row = {n: line[a:b].strip() for n, a, b in zip(names, starts, ends)}
        if row[names[0]] == "total":
            total = row
        else:
            rows.append(row)
    return rows, total


def number(value: str | None) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
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
    b = {s.handle: s.text for s in syntheses.load_one(before).parts}
    a = {s.handle: s.text for s in syntheses.load_one(after).parts}
    return [h for h in sorted(set(a) | set(b))
            if h not in a or h not in b or syntheses.without_references(a[h]) != syntheses.without_references(b[h])]


def decide_backfill(f: dict) -> list[str]:
    """The backfill trial's rule on its measured numbers `f`; each check is printed with PASS or FAILED."""
    def line(text: str, ok: bool) -> tuple[str, bool]:
        return f"  {text}: {'PASS' if ok else 'FAILED'}", ok
    cov = f["covered"] / f["findings"] if f["findings"] else 0.0
    none = f["none"] / f["units_sent"] if f["units_sent"] else 1.0
    checks = [line(f"wrong references in the sample {f['wrong']} <= {BACKFILL_MAX_WRONG} (sample of {f['sample']})",
                   f["wrong"] <= BACKFILL_MAX_WRONG),
              line(f"coverage of findings {cov:.2f} ({f['covered']}/{f['findings']}) >= {BACKFILL_MIN_COVERAGE}",
                   f["findings"] > 0 and cov >= BACKFILL_MIN_COVERAGE),
              line(f"`none` answers {none:.2f} ({f['none']}/{f['units_sent']} units sent) <= {BACKFILL_MAX_NONE}",
                   f["units_sent"] > 0 and none <= BACKFILL_MAX_NONE),
              line("every part keeps its words, `mem check` exits 0, no note falls behind its section", f["preserved"]),
              line("`mem restore` brought back every snapshotted file byte for byte", f["restored"])]
    notes = []
    if f["sample"] < BACKFILL_SAMPLE:
        notes.append(f"the sample holds {f['sample']} pairs, not {BACKFILL_SAMPLE}")
    if not calibration_valid(f["planted"], f["found"]):
        notes.append(f"calibration not valid ({f['found']} of {f['planted']} planted found, needs "
                     f"{calibration_min(f['planted'])})")
    if f["unreliable"]:
        notes.append(f"{f['unreliable']} reference reports are unreliable")
    ok = all(ok for _, ok in checks)
    return ([text for text, _ in checks] + (["preliminary: " + "; ".join(notes)] if notes else [])
            + [f"Verdict backfill: {'PASS' if ok else 'FAIL'}" + (" (preliminary)" if notes else "")])


def backfill_trial(claude: str, root: Path, env: dict, handles: list[str], budget: float, judge_model: str) -> int:
    source = ensure_source()
    missing = [h for h in handles if not (source / "syntheses" / f"{h}.md").is_file()]
    if missing:
        print(f"no synthesis named {', '.join(missing)} in the prepared source copy", file=sys.stderr)
        return 2
    base = root / "backfill"
    shutil.rmtree(base, ignore_errors=True)
    store, work = base / "store", base / "work"
    shutil.copytree(source, store)   # every synthesis stays
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    (base / "settings.json").write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
    before_dir = base / "before"
    before_dir.mkdir()
    snaps = {h: snapshot_files(store, h) for h in handles}
    for h in handles:
        shutil.copy(store / "syntheses" / f"{h}.md", before_dir / f"{h}.md")
    behind_before = behind_count(store, env)
    pairs_before = {h: {(p, n, t) for p, n, refs in file_units(before_dir / f"{h}.md") for t in refs} for h in handles}
    sizes_before = {h: (tokens(t := (before_dir / f"{h}.md").read_text()), tokens(syntheses.shown_file(t))) for h in handles}
    cmd = [str(PLUGIN / "bin" / "mem-synthesize"), "--backfill", *[f"s:{h}" for h in handles], "--budget", f"{budget}",
           "--claude", claude, "--store", str(store)]
    print("running: " + " ".join(cmd[1:]), flush=True)
    done = subprocess.run(cmd, cwd=base, env=env, capture_output=True, text=True, timeout=1800 * len(handles))
    (base / "backfill-output.txt").write_text(done.stdout + "\n--- stderr ---\n" + done.stderr)
    print(done.stdout)
    rows, total = parse_backfill_table(done.stdout)
    # step 4: words kept, mem check, nothing behind its section
    after_dir = base / "after"
    after_dir.mkdir()
    changed, preserved = {}, True
    for h in handles:
        shutil.copy(store / "syntheses" / f"{h}.md", after_dir / f"{h}.md")
        changed[h] = changed_parts(before_dir / f"{h}.md", after_dir / f"{h}.md")
        preserved &= not changed[h]
    check_exit = mem(store, env, "check").returncode
    behind_after = behind_count(store, env)
    preserved &= check_exit == 0 and behind_after <= behind_before
    # step 5: reference judgment and calibration over the backfilled syntheses
    quota, sessions = Quota(CALIBRATION_PLANTED, len(handles)), []
    refs, verdicts, planted, found = {}, {}, 0, 0
    for h in handles:
        parsed, s = ref_session(claude, base, env, h, judge_model, "ref-judge")
        refs[h], verdicts[h] = score_refs(store / "syntheses" / f"{h}.md", parsed, s["ok"])
        cal, more = calibrate(claude, base, env, h, judge_model, verdicts[h], quota.take())
        quota.spent(cal["planted"])
        refs[h]["cal"], sessions = cal, sessions + [s] + more
        planted, found = planted + cal["planted"], found + cal["found"]
    new = sorted((h, p, n, t) for h in handles for p, n, refs_ in file_units(after_dir / f"{h}.md") for t in refs_
                 if (p, n, t) not in pairs_before[h])
    sample = random.Random(0).sample(new, min(BACKFILL_SAMPLE, len(new)))
    wrong = sum(1 for h, p, n, t in sample if verdicts[h].get((p, n, t)) is False)
    # step 6: undo with `mem restore`, then compare bytes
    touched = [h for h in handles if (store / "syntheses" / f"{h}.md").read_bytes() != snaps[h][f"syntheses/{h}.md"]]
    restore_codes = {h: mem(store, env, "restore", f"s:{h}").returncode for h in handles}   # nothing to undo when untouched
    differs = [rel for h in handles for rel, data in snaps[h].items()
               if not (store / rel).is_file() or (store / rel).read_bytes() != data]
    restored = not differs and not any(restore_codes[h] for h in touched)
    f = dict(wrong=wrong, sample=len(sample), findings=sum(r["findings"] for r in refs.values()),
             covered=sum(r["covered"] for r in refs.values()), none=int(number((total or {}).get("none"))),
             units_sent=int(number((total or {}).get("units"))), preserved=preserved, restored=restored,
             planted=planted, found=found, unreliable=sum(bool(r["unreliable"]) for r in refs.values()))
    decision = decide_backfill(f)
    judge_cost = sum(s["cost"] for s in sessions)
    print("\n".join(decision))
    for row in rows:
        cost, parts = number(row.get("cost USD")), int(number(row.get("parts")))
        h = row.get("synthesis", "")
        before, after = sizes_before.get(h), None
        if h in handles:
            t = (after_dir / f"{h}.md").read_text()
            after = (tokens(t), tokens(syntheses.shown_file(t)))
        print(f"  {h}: cost {cost:.3f} USD over {parts} parts ({cost / parts:.3f} per part); tokens stored/shown "
              f"{fmt_tokens(before[0]) if before else '-'}/{fmt_tokens(before[1]) if before else '-'} before, "
              f"{fmt_tokens(after[0]) if after else '-'}/{fmt_tokens(after[1]) if after else '-'} after" if parts else
              f"  {h}: not run ({row.get('status')})")
    print(f"mem-synthesize exit {done.returncode}; mem check {check_exit}; notes behind their section "
          f"{behind_before} -> {behind_after}; judge sessions cost {judge_cost:.3f} USD")
    results = trial_env.TARGET / f"backfill-trial-{time.strftime('%Y%m%d-%H%M%S')}.json"
    results.write_text(json.dumps(dict(
        handles=handles, exit=done.returncode, rows=rows, total=total, changed_parts=changed, mem_check=check_exit,
        behind=[behind_before, behind_after], references=refs, new_pairs=len(new), numbers=f, decision=decision,
        restore_codes=restore_codes, files_not_restored=differs, judge_cost=judge_cost,
        sessions=sessions, tokens_before=sizes_before), indent=1))
    print(f"results: {results}")
    return 0


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

_TABLE_LINES = [("synthesis", "parts", "units", "proposed", "applied", "refused", "none", "extra", "unreadable", "repeated",
                "mem check", "cost USD", "status"),
                ("a", "2", "40", "30", "25", "2", "8", "1", "0", "0", "0", "0.120", "ok"),
                ("b", "1", "10", "6", "6", "0", "4", "0", "0", "0", "0", "0.050", "ok"),
                ("total", "3", "50", "36", "31", "2", "12", "1", "0", "0", "", "0.170", "")]
_WIDTHS = [max(len(r[i]) for r in _TABLE_LINES) for i in range(13)]   # laid out as mem-synthesize does: ljust, 2 spaces
TABLE = ("mem-synthesize --backfill: 2 syntheses (a, b), budget 3.00 USD, log /x/log.txt\n"
         + "\n".join("  ".join(c.ljust(w) for c, w in zip(r, _WIDTHS)).rstrip() for r in _TABLE_LINES)
         + "\ntotal cost USD 0.170; log /x/log.txt\n")


def ref_checks(root: Path) -> None:
    """No model: the reference judge's brief, report parser, scoring, planting and calibration, the conditions of R and
    the backfill trial's rule and table parser, all on invented text."""
    text = brief("ref-judge", HERE, SLUG="s", STORE="/st", UNITS_FILE="/u.md", REPORT_FILE="/r.md")
    assert not re.findall(r"\{[^}\n]*\}", text) and "/st/syntheses/s.md" in text and "/r.md" in text
    raw = (HERE / "ref-judge-brief.md").read_text()
    assert "/home/" not in raw and "/tmp/" not in raw and "~/" not in raw
    # the parser
    parsed = parse_ref_report(REPORT)
    assert parsed["units"] == {("forgetting", 1): "finding", ("forgetting", 2): "finding", ("forgetting", 3): "other",
                               ("forgetting", 4): "finding", ("single", 1): "finding"}, parsed
    assert parsed["pairs"] == {("forgetting", 1, "../knowledge/x/a.md"): True, ("forgetting", 2, "../knowledge/x/b.md"): False,
                               ("forgetting", 4, "../knowledge/x/c.md"): True, ("single", 1, "../knowledge/x/d.md"): True}, parsed
    assert parsed["unreadable"] == 1, parsed
    # scoring on the fixture: unit 5 and its pair have no line
    store = root / "ref-fixture"
    path = store / "syntheses" / "fix.md"
    path.parent.mkdir(parents=True)
    path.write_text(FIXTURE)
    got, verdicts = score_refs(path, parsed)
    assert (got["units"], got["findings"], got["covered"], got["pairs"], got["wrong"], got["unjudged"]) == (6, 4, 4, 4, 1, 2), got
    assert got["unreliable"] and got["unreadable"] == 1 and len(verdicts) == 4
    full = REPORT.replace("U: forgetting | x | finding\n", "U: forgetting | 5 | finding\nP: forgetting | 5 | ../knowledge/x/a.md | yes\nU: forgetting | 6 | other\n")
    full_got, _ = score_refs(path, parse_ref_report(full))
    assert full_got["unjudged"] == 0 and not full_got["unreliable"] and full_got["findings"] == 5, full_got
    assert score_refs(path, None)[0]["unreliable"] and score_refs(path, parsed, session_ok=False)[0]["unreliable"]
    # a finding without a reference is not covered
    bare = FIXTURE.replace("Sleep helps retention too. [Note C](../knowledge/x/c.md)", "Sleep helps retention too.")
    path.write_text(bare)
    assert score_refs(path, parsed)[0]["covered"] == 3
    path.write_text(FIXTURE)
    # planting: the requested number, each a source of its part that the unit did not carry; restored bytes
    every = {k: True for k in verdicts} | {("forgetting", 5, "../knowledge/x/a.md"): True}
    text_planted, planted = plant_references(path, every, 3, random.Random(0))
    assert len(planted) == 3 and len({(h, n) for h, n, _ in planted}) == 3, planted
    assert all(h == "forgetting" for h, _, _ in planted), "the Single part has one source: never planted"
    carried = {(h, n): set(refs) for h, n, refs in file_units(path)}
    after = {(h, n): set(refs) for h, n, refs in (lambda p: (p.write_text(text_planted), file_units(p))[1])(path)}
    for h, n, target in planted:
        assert target in {"../knowledge/x/a.md", "../knowledge/x/b.md", "../knowledge/x/c.md"} - carried[(h, n)], (h, n, target)
        assert target in after[(h, n)] and after[(h, n)] != carried[(h, n)], (h, n)
    assert text_planted != FIXTURE and "[Note" in text_planted and text_planted.count("](../knowledge/x/d.md)") == 2
    path.write_text(FIXTURE)
    assert len(plant_references(path, every, 50, random.Random(0))[1]) == 4   # at most one per candidate unit
    assert plant_references(path, {}, 3, random.Random(0))[1] == []
    path.write_text(FIXTURE)
    # calibration with a stub session: the judge sees the planted text and marks half of the planted pairs `no`
    base = root / "cal-base"
    shutil.copytree(store, base / "store")
    (base / "work").mkdir()
    (base / "settings.json").write_text("{}")
    kept = {}

    def stub(claude, model, prompt, work, settings, env_, log, **kw):
        seen = (base / "store" / "syntheses" / "fix.md").read_text()
        kept["seen"] = seen
        lines = [ln for ln in (work / "ref-calibration-units-fix.md").read_text().splitlines() if " | " in ln]
        assert seen != FIXTURE and lines
        flag = iter(["no", "yes", "no"] * 10)
        out = []
        for ln in lines:
            n, _, refs = (c.strip() for c in ln.split(" | ", 2))
            part = "single" if "d.md" in refs else "forgetting"
            out.append(f"U: {part} | {n} | finding")
            out += [f"P: {part} | {n} | {t.strip()} | {next(flag)}" for t in refs.split(",") if t.strip() != "-"]
        (work / "ref-calibration-report-fix.md").write_text("\n".join(out) + "\n")
        return dict(model_usage={"claude-haiku-4-5": dict(costUSD=0.01)}, has_result=True, error="", cost=0.01, wall=1.0,
                    writes=0, write_errors=0, denied=False, tool_errors=0, answer="")
    original = globals()["run_session"]
    globals()["run_session"] = stub
    try:
        cal, sess = calibrate("claude", base, {}, "fix", "haiku", every, 3)
    finally:
        globals()["run_session"] = original
    assert cal["planted"] == 3 and 0 <= cal["found"] <= 3 and len(sess) == 1 and sess[0]["role"] == "ref-calibration", cal
    assert (base / "store" / "syntheses" / "fix.md").read_bytes() == FIXTURE.encode(), "the stored text was not restored"
    assert kept["seen"] != FIXTURE
    q = Quota(20, 3)
    shares = []
    for planted_now in (7, 7, 6):   # each synthesis reports what it planted before the next takes its share
        shares.append(q.take())
        q.spent(planted_now)
    assert shares == [7, 7, 6] and q.left == 0
    q = Quota(20, 3)
    first = q.take()
    q.spent(2)   # the first synthesis could plant only 2: the other two share the 18 left
    assert (first, q.take(), q.left) == (7, 9, 18)
    # conditions of R
    def ref(findings, covered, pairs, wrong, planted=10, found=10, unreliable=False):
        return dict(findings=findings, covered=covered, pairs=pairs, wrong=wrong, units=findings, unjudged=0, unreadable=0,
                    unreliable=unreliable, cal=dict(planted=planted, found=found))

    def rows(arm, shown, **kw):
        return [dict(topic="human-memory", arm=arm, run=n, valid=True, checked=100, unsupported=5, used=6, denominator=6,
                     words=3000, mem_check=0, cost=0.85, pipeline_cost=0.45, judge_cost=0.4, tokens_stored=2000,
                     tokens_shown=shown, ref=ref(**kw) if arm == "R" else ref(100, 90, 100, 1, planted=0, found=0))
                for n in (1, 2)]
    good = dict(findings=100, covered=90, pairs=100, wrong=2)
    conds = reference_conditions(rows("R", 1000, **good), rows("M", 1000))
    assert len(conds) == 3 and all(ok for _, ok in conds), conds
    verdict = decide(rows("M", 1000) + rows("R", 1100, **good))
    assert verdict[-1] == "Verdict R against M: PASS" and any("calibration" in x and "valid" in x for x in verdict), verdict
    assert any("M references" in x for x in verdict)
    low = decide(rows("M", 1000) + rows("R", 1000, **{**good, "covered": 70}))
    assert low[-1] == "Verdict R against M: FAIL" and any("coverage" in x and "FAILED" in x for x in low), low
    bad = decide(rows("M", 1000) + rows("R", 1000, **{**good, "wrong": 9}))
    assert bad[-1] == "Verdict R against M: FAIL" and any("wrong references" in x and "FAILED" in x for x in bad), bad
    big = decide(rows("M", 1000) + rows("R", 1200, **good))
    assert big[-1] == "Verdict R against M: FAIL" and any("shorten the label rule first" in x and "FAILED" in x for x in big), big
    prelim = decide(rows("M", 1000) + rows("R", 1000, **good, planted=10, found=6))
    assert prelim[-1] == "Verdict R against M: PASS (preliminary)" and any("calibration is not valid" in x for x in prelim), prelim
    assert calibration_min(20) == 16 and calibration_min(10) == 8 and calibration_min(7) == 6 and calibration_valid(10, 8)
    assert not calibration_valid(10, 7) and not calibration_valid(0, 0)
    scaled = decide(rows("M", 1000) + rows("R", 1000, findings=100, covered=90, pairs=100, wrong=2, planted=5, found=4))
    assert scaled[-1] == "Verdict R against M: PASS (preliminary)" and any("threshold scaled to 8" in x for x in scaled), scaled
    unreliable = decide(rows("M", 1000) + rows("R", 1000, unreliable=True, **good))
    assert unreliable[-1].endswith("(preliminary)"), unreliable
    assert reference_conditions([dict(tokens_shown=1)], [dict(tokens_shown=1)]) == []   # no judgment: no condition
    # the backfill rule
    ok = dict(wrong=1, sample=100, findings=50, covered=35, none=10, units_sent=60, preserved=True, restored=True,
              planted=20, found=18, unreliable=0)
    assert decide_backfill(ok)[-1] == "Verdict backfill: PASS" and sum("PASS" in x for x in decide_backfill(ok)) == 6
    failing = decide_backfill({**ok, "wrong": 2})
    assert failing[-1] == "Verdict backfill: FAIL" and any("FAILED" in x and "wrong" in x for x in failing), failing
    assert decide_backfill({**ok, "sample": 40})[-1] == "Verdict backfill: PASS (preliminary)"
    assert any("sample holds 40 pairs" in x for x in decide_backfill({**ok, "sample": 40}))
    assert decide_backfill({**ok, "found": 10})[-1] == "Verdict backfill: PASS (preliminary)"
    for key, value in (("covered", 20), ("none", 20), ("preserved", False), ("restored", False)):
        assert decide_backfill({**ok, key: value})[-1] == "Verdict backfill: FAIL", key
    # the table, with a column the harness does not know and blank cells in the total row
    rows_, total = parse_backfill_table(TABLE)
    assert [r["synthesis"] for r in rows_] == ["a", "b"] and rows_[0]["none"] == "8" and rows_[0]["extra"] == "1", rows_
    assert total["units"] == "50" and total["none"] == "12" and total["applied"] == "31" and total["extra"] == "1", total
    assert total["mem check"] == "" and total["cost USD"] == "0.170" and total["status"] == "", total
    assert parse_backfill_table("no table here") == ([], None)
    assert snapshot_files is not None and number("0.170") == 0.17 and number("") == 0.0


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
        ref_checks(root)
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
    parser.add_argument("--no-ref-judge", action="store_true", help="skip the reference judgment and its calibration")
    parser.add_argument("--backfill-trial", action="store_true", help="run mem-synthesize --backfill on a copy of the "
                        "prepared store and check it (see the module docstring); --budget caps the backfill")
    parser.add_argument("--synthesis", action="append", default=[], metavar="HANDLE",
                        help="with --backfill-trial: a synthesis to backfill (repeatable; default: the default topics)")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if not args.claude:
        parser.error("--claude is required (no claude binary found)")
    topics, arms = args.topic or list(DEFAULT_TOPICS), args.arm or list(DEFAULT_ARMS)
    if args.backfill_trial:
        root = args.work.resolve() if args.work else trial_env.work_dir("mem-backfill-")
        code = backfill_trial(args.claude, root, trial_env.make_env(root), args.synthesis or list(DEFAULT_TOPICS),
                              args.budget, args.judge_model)
        if code in (0, 2) and not args.keep:   # 2: refused before any session
            trial_env.clean(root)
        else:
            print(f"work folder kept: {root}")
        return code
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
    ref_judge = not args.no_ref_judge
    quota = Quota(CALIBRATION_PLANTED, sum(1 for _, a, _ in todo if a == "R"))
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
        row = one_pipeline(args.claude, root, env, topic, arm, n, args.keep, args.judge_model,
                           ref_judge and arm in ("M", "R"), quota)
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
