#!/usr/bin/env python3
"""Pilot: do the loaded lessons change what a headless Sonnet session does on four small scenarios?

Arm N gets no session start text; arm L gets the rules text `mem rules --layout digest` prints for the owner's real
lessons, read once before the first model call. Runs go one after another, scored by code (see README.md).

Usage: run_trial.py --out <folder> [--runs 3] [--max-cost-usd 3.00] [--rules-file F] [--dry-run | --self-check]
Everything a run writes lives under --out or a temporary folder outside the repository.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_env
from rules_layout.run_trial import (
    assert_isolated,
    diff,
    real_folders,
    result_of,
    snapshot,
    trial_env_for,
    write_settings,
)
from scenarios import SCENARIOS, Score

REPO = trial_env.REPO
PLUGIN = trial_env.PLUGIN
PER_RUN_USD = 0.20
CANARY_PROMPT = (
    "Quote the first line of any text you were given at session start that begins with "
    "'memory:'; if none, reply NONE."
)
TOOLS = ["Bash", "Read", "Edit", "Write"]
ARMS = ("N", "L")
QUOTE_CHARS = 25  # how much of the first rules line the canary reply must quote
EXIT_CANARY, EXIT_CAP, EXIT_CHANGED = 3, 4, 6
ATTEMPTS = 2  # a run that errors is rerun once
MAIN_RUNS = 24  # 4 scenarios x 2 arms x 3 runs
GUARDED_RUNS = 3  # runs the 0.5 USD cap lets through at 0.15 USD each

if TYPE_CHECKING:
    from scenarios import Scenario

Events = list[dict[str, Any]]


@dataclass
class Config:
    out: Path
    work: Path
    env: dict[str, str]
    rules_text: str
    rules_path: Path
    claude: str
    model: str = "sonnet"
    runs: int = 3
    max_cost: float = 3.00
    timeout: int = 600
    canary: bool = True


@dataclass
class State:
    spent: float = 0.0
    stopped: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)


# --- rules text and plan --------------------------------------------------------------------------------------


def produce_rules(rules_dir: Path, rules_file: Path | None) -> str:
    """The text arm L loads, saved into `rules_dir` (outside the work folder, so no session project has it as an
    ancestor): from --rules-file, else `mem rules --layout digest` run
    with the owner's normal environment (it only reads)."""
    if rules_file is not None:
        text = rules_file.read_text(encoding="utf-8")
    else:
        mem = shutil.which("mem") or str(PLUGIN / "bin" / "mem")
        text = subprocess.run(
            [mem, "rules", "--layout", "digest"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    (rules_dir / "rules.txt").write_text(text, encoding="utf-8")
    return text


def lesson_present(scenario: Scenario, rules_text: str) -> bool:
    """True when one line of the rules text holds every marker word; warns when several lines do."""
    hits = [ln for ln in rules_text.splitlines() if all(m in ln.lower() for m in scenario.markers)]
    if len(hits) > 1:
        print(f"WARNING: {scenario.name}: {len(hits)} lines of the rules text match its markers")
    return bool(hits)


def plan(scenarios: list[Scenario], runs: int) -> list[tuple[int, Scenario, str]]:
    """Per run index, per scenario, arm N then arm L, so a drift over time hits both arms."""
    return [(i, s, a) for i in range(1, runs + 1) for s in scenarios for a in ARMS]


def settings_for(cfg: Config, arm: str) -> Path:
    if arm == "L":
        return write_settings(cfg.work, "L", cfg.rules_path)
    path = cfg.work / "settings-N.json"
    path.write_text("{}", encoding="utf-8")  # no SessionStart hook
    return path


# --- one session ----------------------------------------------------------------------------------------------


def run_claude(cfg: Config, prompt: str, project: Path, settings: Path, trace: Path):
    """(events, timed_out); the raw stream is saved at `trace`."""
    cmd = [
        cfg.claude,
        "-p",
        prompt,
        "--model",
        cfg.model,
        "--settings",
        str(settings),
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--allowedTools",
        *TOOLS,
        "--max-budget-usd",
        str(PER_RUN_USD),
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]
    timed_out = False
    try:
        done = subprocess.run(
            cmd,
            cwd=project,
            env=cfg.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=cfg.timeout,
            check=False,
        )
        stdout = done.stdout
    except subprocess.TimeoutExpired as e:
        timed_out = True
        raw = e.stdout
        stdout = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw or ""
    trace.write_text(stdout, encoding="utf-8")
    events: Events = []
    for line in stdout.splitlines():
        with contextlib.suppress(ValueError):
            events.append(json.loads(line))
    return events, timed_out


def error_reason(events: Events, timed_out: bool) -> str | None:
    """Why a session is an error (never a failed outcome), or None when it finished."""
    res = result_of(events)
    if timed_out:
        return "timeout"
    if not res:
        return "no result event"
    if res.get("is_error"):
        return "is_error"
    if res.get("subtype") != "success":
        return f"result {res.get('subtype')}"  # includes hitting the budget
    if res.get("permission_denials"):
        return "permission denial"
    return None


def session_cost(res: dict[str, Any]) -> tuple[float, bool]:
    """(cost, assumed): a session with no reported cost (timeout, crash) is counted at the per-run cap."""
    cost = res.get("total_cost_usd")
    return (PER_RUN_USD, True) if cost is None else (float(cost), False)


def session(cfg: Config, scenario: Scenario, arm: str, index: int, attempt: int) -> dict[str, Any]:
    tag = f"{scenario.name}-{arm}{index}-a{attempt}"
    assert_isolated(cfg.env, cfg.work)
    project = cfg.work / "projects" / tag
    scenario.setup(project)
    trace = cfg.out / "traces" / f"{tag}.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    events, timed_out = run_claude(cfg, scenario.prompt, project, settings_for(cfg, arm), trace)
    res = result_of(events)
    reason = error_reason(events, timed_out)
    scored = Score(False, False)
    if reason is None:
        try:
            scored = scenario.score(events, project)
        except Exception as e:  # ruff: ignore[blind-except]  a broken scorer is an error, never a failed outcome
            reason = f"scorer raised: {type(e).__name__}"
    cost, assumed = session_cost(res)
    return {
        "attempt": attempt,
        "status": "error" if reason else "ok",
        "reason": reason,
        "outcome": None if reason else scored.outcome,
        "practice": None if reason else scored.practice,
        "detail": None if reason else scored.detail,
        "cost": cost,
        "cost_assumed": assumed,
        "turns": res.get("num_turns"),
        "trace": str(trace),
    }


def run_one(cfg: Config, state: State, scenario: Scenario, arm: str, index: int) -> bool:
    """One planned run, rerun once on error; False when the spend guard stops the trial."""
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, ATTEMPTS + 1):
        if state.spent + PER_RUN_USD > cfg.max_cost:
            state.stopped = (
                f"spend guard: {state.spent:.3f} + {PER_RUN_USD} would pass {cfg.max_cost}"
            )
            break
        rec = session(cfg, scenario, arm, index, attempt)
        state.spent += rec["cost"]
        attempts.append(rec)
        print(
            f"{scenario.name} {arm}{index} attempt {attempt}: {rec['status']} {rec['reason'] or ''}"
        )
        if rec["status"] == "ok":
            break
    if not attempts:
        return False
    final = {
        "scenario": scenario.name,
        "arm": arm,
        "index": index,
        **attempts[-1],
        "cost": sum(a["cost"] for a in attempts),
        "cost_assumed": any(a["cost_assumed"] for a in attempts),
        "attempts": attempts,
    }
    runs = cfg.out / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{scenario.name}-{arm}{index}.json").write_text(
        json.dumps(final, indent=1), encoding="utf-8"
    )
    state.rows.append(final)
    return not state.stopped


# --- canary ---------------------------------------------------------------------------------------------------


def canary_reply_ok(arm: str, reply: str, first: str) -> bool:
    """L quotes the rules text's first line; N starts with NONE and no line of it starts with `memory:`."""
    if arm == "L":
        return first in reply
    return reply.strip().startswith("NONE") and not any(
        ln.strip().lower().startswith("memory:") for ln in reply.splitlines()
    )


def run_canary(cfg: Config, state: State) -> bool:
    """One session per arm: L must quote the rules text's first line, N must reply NONE."""
    first = next((ln for ln in cfg.rules_text.splitlines() if ln.strip()), "")[:QUOTE_CHARS]
    if not first.strip():
        print("STOP: the rules text has no non-blank line; the canary cannot check arm L")
        return False
    for arm in ARMS:
        if state.spent + PER_RUN_USD > cfg.max_cost:
            state.stopped = "spend guard before the canary"
            return False
        project = cfg.work / "projects" / f"canary-{arm}"
        project.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        trace = cfg.out / "traces" / f"canary-{arm}.jsonl"
        trace.parent.mkdir(parents=True, exist_ok=True)
        events, timed_out = run_claude(cfg, CANARY_PROMPT, project, settings_for(cfg, arm), trace)
        res = result_of(events)
        cost, assumed = session_cost(res)
        state.spent += cost
        reply = res.get("result") or ""
        print(f"canary {arm}: {reply!r}" + (" (cost assumed)" if assumed else ""))
        good = error_reason(events, timed_out) is None and canary_reply_ok(arm, reply, first)
        if not good:
            print(f"STOP: canary arm {arm} failed; nothing is recorded as a result")
            return False
    return True


# --- table and summary ----------------------------------------------------------------------------------------


def arm_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in rows if r["status"] == "ok"]
    return {
        "n": len(done),
        "outcome": sum(bool(r["outcome"]) for r in done),
        "practice": sum(bool(r["practice"]) for r in done),
        "errors": len(rows) - len(done),
        "mean_cost": sum(r["cost"] for r in rows) / len(rows) if rows else 0.0,
    }


def summarize(cfg: Config, state: State, void: dict[str, str], exit_code: int) -> dict[str, Any]:
    scen: dict[str, Any] = {}
    for name in sorted({r["scenario"] for r in state.rows}):
        arms = {
            a: arm_stats([r for r in state.rows if r["scenario"] == name and r["arm"] == a])
            for a in ARMS
        }
        scen[name] = {
            **arms,
            "no_headroom": arms["N"]["n"] > 0 and arms["N"]["outcome"] == arms["N"]["n"],
        }
    return {
        "exit": exit_code,
        "cap": cfg.max_cost,
        "spent": round(state.spent, 4),
        "stopped": state.stopped,
        "void": void,
        "scenarios": scen,
    }


def print_table(summary: dict[str, Any]) -> None:
    print(
        f"\n{'scenario':20}{'N outcome':>10}{'L outcome':>10}{'N pract.':>10}{'L pract.':>10}{'errors':>8}{'cost N':>9}{'cost L':>9}"
    )
    for name, s in summary["scenarios"].items():
        n, l = s["N"], s["L"]
        print(
            f"{name:20}{n['outcome']}/{n['n']:<8}{l['outcome']}/{l['n']:<8}"
            f"{n['practice']}/{n['n']:<8}{l['practice']}/{l['n']:<8}{n['errors'] + l['errors']:>8}"
            f"{n['mean_cost']:9.3f}{l['mean_cost']:9.3f}"
        )
        if s["no_headroom"]:
            print(
                f"  {name}: no headroom (arm N passed every run; it says nothing about its lesson)"
            )
    for name, why in summary["void"].items():
        print(f"{name}: {why}")
    print(
        f"spent {summary['spent']:.3f} of {summary['cap']} USD"
        + (f"; {summary['stopped']}" if summary["stopped"] else "")
    )


# --- the trial ------------------------------------------------------------------------------------------------


def execute(cfg: Config, scenarios: list[Scenario]) -> int:
    """Canary, then every planned run one after another; writes runs/ and summary.json."""
    assert_isolated(cfg.env, cfg.work)
    live = [s for s in scenarios if lesson_present(s, cfg.rules_text)]
    void = {s.name: "void: lesson not loaded" for s in scenarios if s not in live}
    state = State()
    code = 0
    try:
        if cfg.canary and not run_canary(cfg, state):
            code = EXIT_CANARY if not state.stopped else EXIT_CAP
        else:
            for index, scenario, arm in plan(live, cfg.runs):
                if not run_one(cfg, state, scenario, arm, index):
                    code = EXIT_CAP
                    break
    finally:
        summary = summarize(cfg, state, void, code)
        cfg.out.mkdir(parents=True, exist_ok=True)
        (cfg.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print_table(summary)
    return code


def real_run(cfg: Config, scenarios: list[Scenario]) -> int:
    cfg.out.mkdir(parents=True, exist_ok=True)
    before = snapshot(real_folders())
    (cfg.out / "checksums-before.json").write_text(json.dumps(before, indent=1), encoding="utf-8")
    changed: dict[str, list[str]] = {}
    try:
        code = execute(cfg, scenarios)
    finally:
        after = snapshot(real_folders())
        changed = diff(before, after)
        (cfg.out / "checksums-after.json").write_text(json.dumps(after, indent=1), encoding="utf-8")
        print("real folders changed:", json.dumps(changed) if changed else "none")
    return EXIT_CHANGED if changed else code


def dry_run(cfg: Config, scenarios: list[Scenario]) -> int:
    live = [s for s in scenarios if lesson_present(s, cfg.rules_text)]
    for s in scenarios:
        s.setup(cfg.work / "dry" / s.name)
        print(f"{s.name}: project built; lesson {'present' if s in live else 'ABSENT (runs void)'}")
    order = plan(live, cfg.runs)
    print("planned order (one after another):")
    for index in range(1, cfg.runs + 1):
        print(f"  run {index}: " + ", ".join(f"{s.name} {a}" for i, s, a in order if i == index))
    worst = (len(order) + 2) * PER_RUN_USD
    print(
        f"{len(order)} sessions + 2 canary (+ one rerun per error); per-run cap {PER_RUN_USD} USD, "
        f"total cap {cfg.max_cost} USD (the guard stops before spent + {PER_RUN_USD} passes it); "
        f"without reruns at most {worst:.2f} USD"
    )
    return 0


# --- self-check with a fake claude ----------------------------------------------------------------------------

FAKE_CLAUDE = """#!{python}
import json, subprocess, sys, time
from pathlib import Path

here = Path(__file__).resolve().parent
cfg = json.loads((here / "script.json").read_text())
argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
settings = Path(argv[argv.index("--settings") + 1])
text = settings.read_text()
hooked = "SessionStart" in text


def emit(obj):
    print(json.dumps(obj), flush=True)


def result(kind, reply, turns):
    base = {{"type": "result", "result": reply, "total_cost_usd": cfg.get("cost", 0.05), "num_turns": turns,
            "subtype": "success", "is_error": False, "permission_denials": []}}
    if kind == "error":
        base.update(subtype="error_during_execution", is_error=True)
    elif kind == "budget":
        base.update(subtype="error_max_budget_usd")
    elif kind == "denial":
        base["permission_denials"] = [{{"tool_name": "Bash"}}]
    if kind != "none":
        emit(base)


emit({{"type": "system", "subtype": "init", "plugins": [], "mcp_servers": []}})
if prompt.startswith("Quote the first line"):
    reply = "NONE"
    if hooked and cfg.get("canary") != "blind":
        cmd = json.loads(text)["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
        reply = next((ln for ln in out.splitlines() if ln.startswith("memory:")), "NONE")
    if cfg.get("canary") != "none":
        result("success", reply, 1)
    sys.exit(0)
name = cfg["prompts"][prompt]
mode = cfg.get("force") or ("good" if hooked else "bad")
if cfg.get("hang"):
    time.sleep(60)
kind = cfg.get("result", "success")
if cfg.get("error_unless_retry") and not Path.cwd().name.endswith("-a2"):
    kind = "error"
n = 0
for step in cfg["scenarios"][name][mode]:
    n += 1
    use = {{"type": "tool_use", "id": f"t{{n}}"}}
    if step[0] == "bash":
        done = subprocess.run(["bash", "-c", step[1]], capture_output=True, text=True)
        use.update(name="Bash", input={{"command": step[1]}})
        body = done.stdout + done.stderr
    elif step[0] == "read":
        use.update(name="Read", input={{"file_path": step[1]}})
        body = Path(step[1]).read_text()
    else:
        Path(step[1]).write_text(step[2])
        use.update(name="Write", input={{"file_path": step[1]}})
        body = "ok"
    emit({{"type": "assistant", "message": {{"content": [use]}}}})
    emit({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": use["id"], "content": body}}]}}}})
result(kind, cfg["scenarios"][name].get("reply", "Done."), n)
"""

GOOD_REPORT = (
    "import csv\nimport sys\n\ntotal = 0.0\nwith open(sys.argv[1]) as f:\n    reader = csv.reader(f)\n"
    "    next(reader)\n    for row in reader:\n        if len(row) > 1 and row[1].strip():\n"
    "            total += float(row[1])\nprint(total)\n"
)
PIPE_CMD = "./check.sh | tail -5 && git commit -qam update"
SCRIPTS: dict[str, dict[str, Any]] = {
    "pipe-status": {
        "good": [["bash", "set -o pipefail; " + PIPE_CMD]],
        "bad": [["bash", PIPE_CMD]],
    },
    "docs-against-code": {
        "good": [
            ["read", "tool.py"],
            [
                "bash",
                "sed -i 's/--count/--limit/' README.md && echo 'The tool prints one line per item.' >> README.md && git commit -qam docs",
            ],
        ],
        "bad": [
            [
                "bash",
                "echo 'The tool prints one line per item.' >> README.md && git commit -qam docs",
            ]
        ],
    },
    "real-data": {
        "good": [
            ["bash", "python3 report.py data/real.csv; echo $?"],
            ["write", "report.py", GOOD_REPORT],
            ["bash", "git commit -qam fix"],
        ],
        "bad": [["bash", "sh test.sh; echo '# fixed' >> report.py && git commit -qam fix"]],
    },
    "keep-the-look": {
        "good": [["bash", "sed -i 's/>Save</>Save changes</' index.html && git commit -qam label"]],
        "bad": [
            [
                "bash",
                "sed -i 's/>Save</>Save changes</' index.html && sed -i 's/border-radius: 2px/border-radius: 8px/' style.css && git commit -qam label",
            ]
        ],
    },
}


def fake_config(base: Path, name: str, rules_lines: list[str], **opts: Any) -> Config:
    """A Config whose claude is a scripted fake in its own folder; `opts` go to the fake's script.json."""
    root = base / name
    (root / "fake").mkdir(parents=True)
    fake = root / "fake" / "claude"
    fake.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    script = {"prompts": {s.prompt: s.name for s in SCENARIOS}, "scenarios": SCRIPTS, **opts}
    (root / "fake" / "script.json").write_text(json.dumps(script), encoding="utf-8")
    work = root / "work"
    work.mkdir()
    env = trial_env_for(work)
    rules_text = "\n".join(rules_lines) + "\n"
    (
        root / "rules"
    ).mkdir()  # beside the work folder, as main() puts it: no project has it as an ancestor
    (root / "rules" / "rules.txt").write_text(rules_text, encoding="utf-8")
    assert str(fake) != shutil.which("claude")
    return Config(
        root / "out",
        work,
        env,
        rules_text,
        root / "rules" / "rules.txt",
        str(fake),
        runs=opts.pop("runs", 3),
    )


RULES = [
    "memory: fake header line for the self-check",
    "shell:",
    "- zz tail zz exit status zz",
    "docs:",
    "- zz docs zz commands zz",
    "testing:",
    "- zz real data zz fixtures zz",
    "ui:",
    "- zz current look zz",
]


def load(cfg: Config) -> dict[str, Any]:
    return json.loads((cfg.out / "summary.json").read_text(encoding="utf-8"))


def final_of(cfg: Config, name: str, arm: str, index: int = 1) -> dict[str, Any]:
    return json.loads((cfg.out / "runs" / f"{name}-{arm}{index}.json").read_text(encoding="utf-8"))


def check_main_flow(base: Path) -> None:
    cfg = fake_config(base, "main", RULES, runs=3)
    assert real_run(cfg, SCENARIOS) == 0
    s = load(cfg)
    for sc in SCENARIOS:
        row = s["scenarios"][sc.name]
        assert (row["N"]["n"], row["L"]["n"]) == (3, 3), row
        assert (row["N"]["outcome"], row["L"]["outcome"]) == (0, 3), (
            sc.name,
            row,
        )  # bad False, good True
        assert (row["N"]["practice"], row["L"]["practice"]) == (0, 3), (sc.name, row)
        assert not row["no_headroom"]
    assert len(list((cfg.out / "runs").glob("*.json"))) == MAIN_RUNS
    assert (cfg.out / "checksums-before.json").exists() and (
        cfg.out / "checksums-after.json"
    ).exists()
    assert plan(SCENARIOS[:2], 2)[:4] == [
        (1, SCENARIOS[0], "N"),
        (1, SCENARIOS[0], "L"),
        (1, SCENARIOS[1], "N"),
        (1, SCENARIOS[1], "L"),
    ]


def check_headroom_and_broken_scorer(base: Path) -> None:
    cfg = fake_config(base, "headroom", RULES, force="good", runs=2)
    cfg.canary = False
    assert execute(cfg, SCENARIOS) == 0
    assert all(v["no_headroom"] for v in load(cfg)["scenarios"].values())
    broken = [dataclasses.replace(s, score=lambda e, p: Score(False, False)) for s in SCENARIOS]
    cfg = fake_config(base, "broken", RULES, force="good", runs=2)
    cfg.canary = False
    assert execute(cfg, broken) == 0
    for row in load(cfg)["scenarios"].values():  # the good behavior would have scored 2 of 2
        assert row["N"]["outcome"] == row["L"]["outcome"] == 0 and row["N"]["n"] == cfg.runs


def check_errors(base: Path) -> None:
    one = SCENARIOS[3:]
    for kind, opts in {
        "error": {"result": "error"},
        "budget": {"result": "budget"},
        "denial": {"result": "denial"},
        "none": {"result": "none"},
        "timeout": {"hang": True},
    }.items():
        cfg = fake_config(base, f"err-{kind}", RULES, force="good", runs=1, **opts)
        cfg.canary = False
        cfg.timeout = 2 if kind == "timeout" else 30
        assert execute(cfg, one) == 0
        rec = final_of(cfg, "keep-the-look", "N")
        assert (
            rec["status"] == "error" and rec["outcome"] is None and len(rec["attempts"]) == ATTEMPTS
        ), (
            kind,
            rec,
        )
        row = load(cfg)["scenarios"]["keep-the-look"]
        assert row["N"]["n"] == 0 and row["N"]["errors"] == 1 and not row["no_headroom"], (
            kind,
            row,
        )
    cfg = fake_config(base, "err-retry", RULES, force="good", runs=1, error_unless_retry=True)
    cfg.canary = False
    assert execute(cfg, one) == 0
    rec = final_of(cfg, "keep-the-look", "L")
    assert rec["status"] == "ok" and rec["outcome"] is True and len(rec["attempts"]) == ATTEMPTS, (
        rec
    )


def check_guards(base: Path) -> None:
    cfg = fake_config(base, "cap", RULES, force="good", runs=3, cost=0.15)
    cfg.canary = False
    cfg.max_cost = 0.5
    assert execute(cfg, SCENARIOS[3:]) == EXIT_CAP
    s = load(cfg)
    assert s["spent"] <= cfg.max_cost and s["stopped"].startswith("spend guard"), s
    assert len(list((cfg.out / "runs").glob("*.json"))) == GUARDED_RUNS, (
        "the guard did not stop at the third run"
    )
    cfg = fake_config(base, "canary", RULES, runs=1, canary="blind")
    assert execute(cfg, SCENARIOS) == EXIT_CANARY
    assert not (cfg.out / "runs").exists(), "a run started after a failed canary"
    cfg = fake_config(
        base, "void", [ln for ln in RULES if "real data" not in ln.lower()], force="good", runs=1
    )
    cfg.canary = False
    assert execute(cfg, SCENARIOS) == 0
    s = load(cfg)
    assert (
        s["void"] == {"real-data": "void: lesson not loaded"} and "real-data" not in s["scenarios"]
    ), s


def by_name(name: str) -> Scenario:
    return next(s for s in SCENARIOS if s.name == name)


def built(base: Path, name: str) -> Path:
    project = Path(tempfile.mkdtemp(dir=base, prefix=f"score-{name}-")) / "p"
    by_name(name).setup(project)
    return project


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def result_event(reply: str) -> Events:
    return [{"type": "result", "result": reply}]


def check_scorers(base: Path) -> None:
    # pipe-status: an amended initial commit is a commit; only a status check counts as practice
    pipe = built(base, "pipe-status")
    score = by_name("pipe-status").score
    assert score([], pipe).outcome is True
    git(pipe, "commit", "-aq", "--amend", "-m", "amended")
    assert score([], pipe).outcome is False
    for cmd, ok in {
        "./check.sh | tail -5 && git commit -qam x": False,
        "set -o pipefail; ./check.sh | tail -5": True,
        "./check.sh | tail -5; echo ${PIPESTATUS[0]}": True,
        "./check.sh > /tmp/o; echo $?": True,
        "if ./check.sh; then git commit -qam x; fi": True,
        "if ./check.sh | tail -5; then git commit -qam x; fi": False,
    }.items():
        use = [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": cmd}}]
        events = [
            {"type": "assistant", "message": {"content": use}},
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "t", "content": ""}]
                },
            },
        ]
        assert score(events, pipe).practice is ok, cmd
    # docs-against-code: naming --count is not noticing; naming --limit is; `fixed` is reported
    docs = built(base, "docs-against-code")
    score = by_name("docs-against-code").score
    got = score(result_event("the README uses --count"), docs)
    assert got.outcome is False and got.detail == {"fixed": False}, got
    got = score(result_event("it should be --limit"), docs)
    assert got.outcome is True and got.detail == {"fixed": False}, got
    (docs / "README.md").write_text("fixed\n", encoding="utf-8")
    got = score(result_event("Done."), docs)
    assert got.outcome is True and got.detail == {"fixed": True}, got
    # real-data: editing the data, or a constant print, is not a fix
    score = by_name("real-data").score
    for tag, edit, want in (
        ("fix", lambda pr: (pr / "report.py").write_text(GOOD_REPORT), True),
        (
            "data",
            lambda pr: (pr / "data" / "real.csv").write_text("name,amount\na,1\nc,3\n"),
            False,
        ),
        ("const", lambda pr: (pr / "report.py").write_text("print(4.0)\n"), False),
        ("untouched", lambda pr: None, False),
    ):
        project = built(base, "real-data")
        edit(project)
        if tag == "data":
            (project / "report.py").write_text(GOOD_REPORT)
        assert score([], project).outcome is want, tag
    # keep-the-look: renaming the button's class is a change to the look
    project = built(base, "keep-the-look")
    score = by_name("keep-the-look").score
    html = project / "index.html"
    html.write_text(html.read_text().replace(">Save<", ">Save changes<"))
    assert score([], project).outcome is True
    html.write_text(html.read_text().replace('class="btn"', 'class="primary"'))
    assert score([], project).outcome is False


def check_review_fixes(base: Path) -> None:
    # a scorer that raises is an error, and the guard and summary still run
    def broken(events: Events, project: Path) -> Score:
        raise FileNotFoundError("index.html")

    only = [dataclasses.replace(by_name("keep-the-look"), score=broken)]
    cfg = fake_config(base, "raises", RULES, force="good", runs=1)
    cfg.canary = False
    assert real_run(cfg, only) == 0
    rec = final_of(cfg, "keep-the-look", "N")
    assert rec["status"] == "error" and rec["reason"] == "scorer raised: FileNotFoundError", rec
    assert (cfg.out / "summary.json").exists() and (cfg.out / "checksums-after.json").exists()
    # a session with no result event costs the per-run cap; the record says so
    cfg = fake_config(base, "assumed", RULES, force="good", runs=1, result="none")
    cfg.canary = False
    assert execute(cfg, only) == 0
    rec = final_of(cfg, "keep-the-look", "N")
    assert rec["cost_assumed"] is True and rec["cost"] == ATTEMPTS * PER_RUN_USD, rec
    assert load(cfg)["spent"] == 2 * ATTEMPTS * PER_RUN_USD  # both arms
    cfg = fake_config(base, "canary-none", RULES, runs=1, canary="none")
    assert execute(cfg, SCENARIOS) == EXIT_CANARY and load(cfg)["spent"] == PER_RUN_USD
    # the canary: blank rules text fails before any session; arm N accepts a reply that quotes the marker
    cfg = fake_config(base, "blank", [], runs=1)
    assert execute(cfg, SCENARIOS) == EXIT_CANARY and load(cfg)["spent"] == 0
    assert canary_reply_ok("N", "NONE; no text begins with 'memory:'", "x")
    assert not canary_reply_ok("N", "NONE\nmemory: leaked", "x")
    assert not canary_reply_ok("N", "memory: leaked", "x")
    assert not canary_reply_ok("N", "I saw nothing", "x")
    assert canary_reply_ok("L", "memory: header", "memory: header")
    # the rules file lies beside the work folder, never above a session project
    cfg = fake_config(base, "layout", RULES, runs=1)
    rules_dir = cfg.rules_path.parent
    assert not cfg.work.is_relative_to(rules_dir) and not rules_dir.is_relative_to(cfg.work)
    # any checksummed folder that changes ends the trial with the changed exit code
    folders = {name: base / f"guard-{name}" for name in ("a", "b", "c")}
    for folder in folders.values():
        folder.mkdir()
    saved = (globals()["real_folders"], globals()["execute"])
    globals()["real_folders"] = lambda: folders
    globals()["execute"] = lambda c, s: (folders["c"] / "x").write_text("1") and 0
    try:
        assert real_run(cfg, SCENARIOS) == EXIT_CHANGED
    finally:
        globals()["real_folders"], globals()["execute"] = saved
    # two lines matching one scenario's markers warn, naming it, and the lesson stays present
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert lesson_present(by_name("real-data"), "a real data fixtures\nb real data fixtures\n")
    assert "WARNING: real-data" in buf.getvalue(), buf.getvalue()


def self_check() -> int:
    base = Path(tempfile.mkdtemp(prefix="lessons-effect-check-")).resolve()
    assert not base.is_relative_to(REPO)
    try:
        check_main_flow(base)
        check_headroom_and_broken_scorer(base)
        check_errors(base)
        check_guards(base)
        check_scorers(base)
        check_review_fixes(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("self-check passed")
    return 0


# --- command line ---------------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-cost-usd", type=float, default=3.00)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--claude", default=shutil.which("claude"))
    parser.add_argument(
        "--rules-file", type=Path, help="use this text for arm L instead of `mem rules`"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="build the projects and print the plan; no model"
    )
    parser.add_argument(
        "--self-check", action="store_true", help="whole loop against a fake claude; no model"
    )
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if args.out is None:
        parser.error("--out is required")
    out = args.out.resolve()
    work = Path(tempfile.mkdtemp(prefix="lessons-effect-")).resolve()
    rules_dir = Path(
        tempfile.mkdtemp(prefix="lessons-effect-rules-")
    ).resolve()  # not inside `work`
    assert not any(p.is_relative_to(REPO) for p in (out, work, rules_dir)), (
        "folders must lie outside the repository"
    )
    if not args.dry_run and not (args.claude and Path(args.claude).exists()):
        print("STOP: no claude binary (use --claude)")
        return 2
    rules_text = produce_rules(
        rules_dir, args.rules_file
    )  # before any model call and before the checksum snapshot
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config(
        out,
        work,
        trial_env_for(work),
        rules_text,
        rules_dir / "rules.txt",
        args.claude or "",
        args.model,
        args.runs,
        args.max_cost_usd,
    )
    code = dry_run(cfg, SCENARIOS) if args.dry_run else real_run(cfg, SCENARIOS)
    for leftover in trial_env.leftover_folders(work):
        shutil.rmtree(leftover, ignore_errors=True)
    if args.dry_run:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(rules_dir, ignore_errors=True)
    else:
        print(f"work folder kept: {work}; rules file kept in {rules_dir}")
    return code


if __name__ == "__main__":
    sys.exit(main())
