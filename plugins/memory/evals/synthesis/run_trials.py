#!/usr/bin/env python3
"""Synthesis trials: is a synthesis written by Haiku and fixed in a Haiku checker loop as accurate and complete
as one written by Sonnet with one Haiku fact-check, and at what cost?

Plan: docs/superpowers/plans/2026-11-17-memory-synthesis-haiku.md (its Design and decision rule bind this script).
Arm S: writer sonnet -> checker haiku -> fixer sonnet. Arm Y (default with S): writer sonnet -> checker haiku (medium effort) and
fixer haiku (high effort), up to 2 fix rounds, ending on a check. Arm H (not a default): writer haiku -> (checker haiku -> fixer haiku), up to
2 fix rounds, ending on a check. A Haiku judge at high effort, blind to the arm, fact-checks every final synthesis; the judge's
count is the quality measure. Each step is its own `claude -p` session. Every pipeline works on its own copy of a
store snapshot under `target/mem-trials/` in which the topic's synthesis is gone and its notes are detached; the
owner's store is read once, to make the snapshot, and never written.

Usage: run_trials.py [--claude PATH] [--topic T]... [--arm S|Y|H]... [--judge-model haiku] [--runs 1] [--jobs 2] [--work DIR (resume)]
                     [--keep] | --self-check
It costs model usage (8 pipelines and 8 judges at the defaults, about 8 to 10 USD).
--rejudge reuses a kept pipeline folder (run an earlier pipeline with --keep).
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
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_env  # noqa: E402

HERE = Path(__file__).resolve().parent
PLUGIN = trial_env.PLUGIN
MEM = PLUGIN / "bin" / "mem"
SOURCE = trial_env.TARGET / "synthesis-source"
ATTACHED = trial_env.TARGET / "synthesis-source-attached.json"
TOPICS = ("human-memory", "time-series-forecasting", "llm-evaluation", "mental-health")
ARMS = ("S", "Y", "H")   # H (Haiku writer) is kept, but not run by default
DEFAULT_ARMS = ("S", "Y")
STATE = "state.json"
SKILL = PLUGIN / "skills" / "memory-synthesis" / "SKILL.md"
MAX_FIX_ROUNDS = 2
COUNTS = re.compile(r"^COUNTS: checked=(\d+) unsupported=(\d+)(?: used=(\d+) unused=(\d+))?\s*$", re.M)
NOTE_LINE = re.compile(r"^NOTE: (\S+) (used|unused)\s*$", re.M)
DENIED = re.compile(r"requested permissions|haven't granted|permission.{0,40}denied|denied.{0,40}permission", re.I)

JUDGE_EXTRA = """
## Additional instruction for this check

Besides the numbered list, mark each note cited in any `Sources:` line of the synthesis as `used` (a part of the
synthesis states something that comes from that note) or `unused` (cited, but nothing in the part rests on it).
Just before the last line of the report, write one line per cited note, exactly `NOTE: <path> used` or
`NOTE: <path> unused`, the path from the store root (e.g. `knowledge/<domain>/<file>.md`), each note once. The very
last line of the file is then exactly `COUNTS: checked=<N> unsupported=<M> used=<A> unused=<B>` (integers; A and B
count the NOTE lines).
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


def mem(store: Path, env: dict, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(MEM), *args], env={**env, "MEM_STORE": str(store)}, input=stdin, capture_output=True,
                          text=True, cwd=store)


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


# --- briefs --------------------------------------------------------------------------------------------------

def brief(name: str, **values: str) -> str:
    text = (HERE / f"{name}-brief.md").read_text()
    values.setdefault("SKILL_FILE", str(SKILL))
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    left = re.findall(r"\{[A-Z_]+\}", text)
    assert not left, f"{name}-brief.md has unfilled placeholders: {left}"
    return text


# --- sessions ------------------------------------------------------------------------------------------------

def model_family(model_id: str) -> str:
    return next((f for f in ("haiku", "sonnet", "opus") if f in model_id.lower()), model_id)


def cost_by_family(model_usage: dict) -> dict[str, float]:
    costs: dict[str, float] = {}
    for model, usage in model_usage.items():
        family = model_family(model)
        costs[family] = costs.get(family, 0.0) + float(usage.get("costUSD") or 0.0)
    return costs


def parse(stdout: str) -> dict:
    """Facts of one stream-json session: writes with their exit status, denials, cost per model, result."""
    out = dict(writes=0, write_errors=0, denied=0, tool_errors=0, model_usage={}, cost=0.0, error=True, answer="",
               has_result=False)
    uses: dict[str, tuple[str, str]] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content")
        if kind == "assistant" and isinstance(content, list):
            for part in content:
                if part.get("type") == "tool_use":
                    uses[part["id"]] = (part["name"], (part.get("input") or {}).get("command", ""))
        elif kind == "user" and isinstance(content, list):
            for part in content:
                if part.get("type") != "tool_result":
                    continue
                name, command = uses.get(part.get("tool_use_id"), ("", ""))
                body = part.get("content")
                text = body if isinstance(body, str) else " ".join(b.get("text", "") for b in body or [])
                failed = bool(part.get("is_error"))
                if failed:
                    out["tool_errors"] += 1
                    if DENIED.search(text):
                        out["denied"] += 1
                if name == "Write" or (name == "Bash" and re.match(r"\s*mem synthesis (new|add|edit|append)\b", command)):
                    out["writes"] += 1
                    out["write_errors"] += failed
        elif kind == "result":
            out["has_result"] = True
            out["answer"] = event.get("result") or ""
            out["model_usage"] = event.get("modelUsage") or {}
            out["cost"] = float(event.get("total_cost_usd") or 0.0)
            out["error"] = bool(event.get("is_error"))
    return out


def run_session(claude: str, model: str, prompt: str, work: Path, settings: Path, env: dict, log: Path,
                timeout: int = 1500, effort: str | None = None) -> dict:
    cmd = [claude, "-p", prompt, "--model", model, "--plugin-dir", str(PLUGIN), "--settings", str(settings),
           "--setting-sources", "project",
           # Headless --allowedTools also limits what a session may run: exactly what a step needs. Body files go
           # in the work folder (`//` is an absolute path in a permission rule; a new file needs the Edit rule too); the
           # web stays out.
           "--allowedTools", "Bash(mem *)", "Read", "Grep", "Glob",
           f"Write(/{work}/**)", f"Edit(/{work}/**)",
           "--disallowedTools", "WebSearch", "WebFetch",
           "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    if effort:
        cmd += ["--effort", effort]
    start = time.monotonic()
    try:
        done = subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout)
        raw = done.stdout
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    log.write_text(raw)
    result = parse(raw)
    result["wall"] = time.monotonic() - start
    return result


def parse_report(path: Path) -> dict | None:
    """The report's last COUNTS line and its NOTE lines; None when the file or the line is missing."""
    if not path.is_file():
        return None
    text = path.read_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    found = COUNTS.fullmatch(lines[-1]) if lines else None
    if not found:
        return None
    notes = {}
    for rel, state in NOTE_LINE.findall(text):
        at = rel.find("knowledge/")
        notes[rel[at:] if at >= 0 else rel] = state
    checked, unsupported = int(found.group(1)), int(found.group(2))
    return dict(checked=checked, unsupported=unsupported, notes=notes)


# --- pipeline ------------------------------------------------------------------------------------------------

def synthesis_facts(path: Path) -> tuple[int, int]:
    text = path.read_text()
    return len(text.split()), len(re.findall(r"^## (?!Summary$)", text, re.M))


def summary(s: dict) -> dict:
    return dict(role=s["role"], model=s["model"], costs=s["costs"], cost=s["cost"], wall=s["wall"], writes=s["writes"],
                write_errors=s["write_errors"], denied=s["denied"], tool_errors=s["tool_errors"],
                ok=s["has_result"] and not s["error"])


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
        s = run_session(claude, judge_model, brief("checker", **fill, REPORT_FILE=str(report)) + JUDGE_EXTRA, work,
                        settings, env, base / f"{len(sessions) + 1:02d}-judge.jsonl", effort="high")
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
        costs=pooled, cost=sum(s["cost"] for s in sessions),
        pipeline_cost=sum(s["cost"] for s in sessions if s["role"] != "judge"),
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
    # Arm Y runs its Haiku checker at medium effort and its Haiku fixer at high; S and H at the default.
    check_effort, fix_effort = ("medium", "high") if arm == "Y" else (None, None)

    def step(role: str, model: str, text: str, level: str | None = None) -> dict:
        s = run_session(claude, model, text, work, settings, env, base / f"{len(sessions) + 1:02d}-{role}.jsonl",
                        effort=level)
        s.update(role=role, model=model, costs=cost_by_family(s["model_usage"]))
        sessions.append(summary(s))
        return s

    def check(n: int) -> dict | None:
        report = work / f"report-{n}.md"
        step("checker", "haiku", brief("checker", **fill, REPORT_FILE=str(report)), check_effort)
        return parse_report(report)

    synthesis = store / "syntheses" / f"{topic}.md"
    step("writer", "haiku" if arm == "H" else "sonnet", brief("writer", **fill))
    arm_count, why, fixes = None, "", 0
    if not synthesis.is_file():
        why = "no synthesis written"
    else:
        arm_count = check(1)
        if arm == "S":
            if arm_count and arm_count["unsupported"]:
                step("fixer", "sonnet", brief("fixer", **fill, REPORT_FILE=str(work / "report-1.md")))
                fixes = 1
        else:
            while arm_count and arm_count["unsupported"] and fixes < MAX_FIX_ROUNDS:
                step("fixer", "haiku", brief("fixer", **fill, REPORT_FILE=str(work / f"report-{fixes + 1}.md")), fix_effort)
                fixes += 1
                arm_count = check(fixes + 1)
        if arm_count is None:
            why = "arm checker report unreadable"
    prior = dict(sessions=sessions, why=why, denominator=denominator, arm_count=arm_count, fixes=fixes)
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
          f"{'cover':9} {'check':5} {'arm vs judge':14} {'cost USD per model':30} {'total':6} {'wall s':6}")


def table_line(r: dict) -> str:
    costs = " ".join(f"{k}={v:.3f}" for k, v in sorted(r["costs"].items()))
    arm = "-" if r["arm_checked"] is None else f"{r['arm_unsupported']}/{r['arm_checked']} v {r['unsupported']}/{r['checked']}"
    return (f"{r['topic']:24} {r['arm']:3} {r['run']:<3} {str(r['valid']):5} {rate(r):9.1f} {r['checked']:<7} "
            f"{r['words']:<5} {r['parts']:<5} {r['used']}/{r['denominator']:<7} {str(r['mem_check']):5} {arm:14} "
            f"{costs:30} {r['cost']:<6.3f} {r['wall']:<6.0f} {r['why']}")


def pooled(rows: list[dict]) -> dict:
    checked = sum(r["checked"] for r in rows)
    return dict(n=len(rows), rate=100.0 * sum(r["unsupported"] for r in rows) / checked if checked else float("nan"),
                checked=statistics.mean(r["checked"] for r in rows), words=statistics.mean(r["words"] for r in rows),
                cover=statistics.mean(coverage(r) for r in rows),
                cost=statistics.mean(r["pipeline_cost"] for r in rows), judge=statistics.mean(r["cost"] - r["pipeline_cost"] for r in rows),
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
    """The plan's decision rule (redesign of 2026-11-17: challenger Y against S), on the valid pipelines pooled
    over topics and runs. Arm H, when it was run, is held to the original rule (cost at most half of S)."""
    by = {a: [r for r in rows if r["arm"] == a and r["valid"]] for a in ARMS}
    lines, stats = [], {}
    for arm, rs in by.items():
        if not rs:
            continue
        stats[arm] = p = pooled(rs)
        lines.append(f"{arm} valid={p['n']} unsupported/100={p['rate']:.1f} claims checked={p['checked']:.0f} "
                     f"words={p['words']:.0f} coverage={p['cover']:.0f}% mem check all 0={p['mem_ok']} "
                     f"pipeline cost={p['cost']:.3f} (judge {p['judge']:.3f}) run gap={spread(rs):.1f} points")
    challenger = next((a for a in ("Y", "H") if a in stats), None)
    if "S" not in stats or challenger is None:
        return lines + ["Decision rule: not applicable, S or its challenger has no valid pipeline."]
    s, h = stats["S"], stats[challenger]
    share = 0.8 if challenger == "Y" else 0.5
    single = max(len([r for r in by[a] if r["topic"] == t]) for a in ("S", challenger) for t in TOPICS) <= 1
    gap = max(spread(by["S"]), spread(by[challenger]))
    checks = {f"unsupported {h['rate']:.1f} <= {s['rate']:.1f}+2": h["rate"] <= s["rate"] + 2,
              f"claims {h['checked']:.0f} >= 80% of {s['checked']:.0f}": h["checked"] >= 0.8 * s["checked"],
              f"coverage {h['cover']:.0f} >= {s['cover']:.0f}-10": h["cover"] >= s["cover"] - 10,
              f"every {challenger} synthesis passes mem check": h["mem_ok"],
              f"pipeline cost (judge excluded) {h['cost']:.3f} <= {share:.0%} of {s['cost']:.3f}":
                  h["cost"] <= share * s["cost"]}
    lines += [f"  {text}: {ok}" for text, ok in checks.items()]
    if single:
        lines.append("preliminary (1 run per topic): the variance rule cannot apply")
    verdict = (f"INCONCLUSIVE (the runs of an arm differ by {gap:.1f} > 2 points on a topic, pooled over topics): "
               "no change" if gap > 2 else
               f"ADOPT arm {challenger}" if all(checks.values()) else "KEEP today's pipeline (arm S) and record the gap")
    return lines + [f"Verdict: {verdict}"]


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
            raw = (HERE / f"{name}-brief.md").read_text()
            assert "/home/" not in raw and "/tmp/" not in raw and "~/" not in raw, f"{name}-brief.md has a private path"
        sample = root / "r.md"
        sample.write_text("1. x\nNOTE: ../knowledge/a/b.md used\nNOTE: ../literature/c.md unused\n"
                          "COUNTS: checked=40 unsupported=3 used=1 unused=1\n")
        got = parse_report(sample)
        assert got == dict(checked=40, unsupported=3, notes={"knowledge/a/b.md": "used", "../literature/c.md": "unused"}), got
        def fake(arm, cost, unsupported):
            return dict(topic="human-memory", arm=arm, run=1, valid=True, checked=60, unsupported=unsupported, used=6,
                        denominator=6, words=3000, mem_check=0, cost=cost + 0.4, pipeline_cost=cost)
        verdict = decide([fake("S", 1.0, 2), fake("Y", 0.7, 3)])
        assert "preliminary (1 run per topic)" in " ".join(verdict) and verdict[-1].startswith("Verdict: ADOPT arm Y")
        assert decide([fake("S", 1.0, 2), fake("Y", 0.9, 3)])[-1].startswith("Verdict: KEEP")
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
    parser.add_argument("--arm", action="append", choices=ARMS, default=[], help="default: S and Y")
    parser.add_argument("--judge-model", default="haiku", help="the judge's model (always at --effort high)")
    parser.add_argument("--rejudge", type=Path, metavar="PIPELINE_DIR",
                        help="judge the final synthesis of a kept pipeline folder (runs/<topic>-<arm>-<n> of an "
                             "earlier --keep run) again, recorded as arm S, run 1; needs --work")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--work", type=Path, help="resume the work folder of an earlier run")
    parser.add_argument("--keep", action="store_true", help="keep the work folder and the store copies at the end")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if not args.claude:
        parser.error("--claude is required (no claude binary found)")
    topics, arms = args.topic or list(TOPICS), args.arm or list(DEFAULT_ARMS)
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
