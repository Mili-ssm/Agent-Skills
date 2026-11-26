#!/usr/bin/env python3
"""Trial: does the grouped layout of the loaded rules (`mem rules --layout grouped`) keep the rules followed?

Condition F prints the flat block at session start, condition G the grouped one, from the same 16 lessons. Each run is
one headless Sonnet session in a fresh git project (the same easy task every time); three rules leave a trace and are
scored by code. Three runs a condition on one task can show a collapse of the grouped block, not a benefit and not
equivalence (see README.md).

Usage: run_trial.py --out <folder> [--runs 3] [--max-cost-usd 1.00] [--dry-run]
Everything the sessions touch lives in a temporary folder outside the repository; the owner's real memory folders and
the plugin's state folder are checksummed before the first model call and after the last one.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
import trial_env
from store import records

PLUGIN = trial_env.PLUGIN
REPO = trial_env.REPO
MEM = PLUGIN / "bin" / "mem"
PROMPT = "greet.py prints a misspelled greeting. Fix it and commit the change."
TOOLS = [
    "Read",
    "Edit",
    "Write",
    "Bash(./check.sh*)",
    "Bash(bash check.sh*)",
    "Bash(sh check.sh*)",
    "Bash(git *)",
    "Bash(python3 greet.py*)",
    "Bash(python greet.py*)",
    "Bash(echo *)",
    "Bash(printf *)",
    "Bash(cat *)",
    "Bash(ls*)",
    "Bash(tail *)",
    "Bash(head *)",
    "Bash(chmod +x check.sh)",
]  # bounded: no Bash(*), no network, no rm
MAX_VOID = 2  # a void run (a denial) is rerun once in its condition; more than two void runs stop the trial
PER_RUN_USD = 0.25
STOP_AFTER_FOUR_USD = 0.60
FOURTH_RUN = 4
LESSON_COUNT = 16
HEADING_COUNT = 7
PREFIX = re.compile(r"^(fix|feat|docs|chore)(\([^)]*\))?!?: ")

# (short form, topic, weight). Strong ones rank first, then medium, then light: the three trace rules sit in the middle.
TRACE = [
    (
        "Run ./check.sh before reporting a change and quote its last line in the reply.",
        "process",
        "medium",
    ),
    (
        "Start every commit message with a type prefix such as fix:, feat:, docs: or chore:.",
        "git",
        "medium",
    ),
    ("Add a line to NOTES.md describing each change you make.", "docs", "medium"),
]
OTHERS = [
    ("Quote shell variables so values with spaces survive.", "shell", "strong"),
    ("Pin a dependency to a version before relying on its behaviour.", "python", "strong"),
    (
        "Name a test after the behaviour it protects, not the function it calls.",
        "testing",
        "strong",
    ),
    ("Read the error message to the end before changing code.", "review", "strong"),
    ("Prefer a failing test over a comment that says the code is wrong.", "testing", "strong"),
    ("Use pathlib rather than string concatenation to build file paths.", "python", "light"),
    (
        "Set -eu at the top of a shell script that must not continue after a failure.",
        "shell",
        "light",
    ),
    ("Keep a test independent of the order in which tests run.", "testing", "light"),
    ("Ask what a reviewer will question first, and answer it in the change.", "review", "light"),
    (
        "Close files with a context manager instead of relying on garbage collection.",
        "python",
        "light",
    ),
    ("Print a command before running a destructive loop over many files.", "shell", "light"),
    ("Mock only what you cannot run cheaply.", "testing", "light"),
    ("Leave the code a reviewer reads with fewer surprises than you found.", "review", "light"),
]
SOURCES = [
    "session a project 0123456789ab",
    "session b project ba9876543210",
    "session c project aaaaaaaaaaaa",
]


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as e:
        return f"unreadable:{type(e).__name__}"


def checksums(folder: Path) -> dict[str, str]:
    if not folder.is_dir():
        return {}
    return {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def real_folders() -> dict[str, Path]:
    """The owner's real folders, resolved from the process environment (never from the trial's)."""
    memories = records.global_memories_root(dict(os.environ))
    state = (
        Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "agent-memory"
    )
    folders = {"project-memory": REPO / ".memory", "plugin-state": state}
    if memories is not None:
        folders["global-memories"] = Path(memories)
    return folders


def snapshot(folders: dict[str, Path]) -> dict[str, dict[str, str]]:
    return {name: checksums(path) for name, path in folders.items()}


def diff(before: dict, after: dict) -> dict[str, list[str]]:
    out = {}
    for name, b in before.items():
        a = after[name]
        changed = sorted(k for k in b.keys() | a.keys() if b.get(k) != a.get(k))
        if changed:
            out[name] = changed
    return out


def trial_env_for(work: Path) -> dict:
    env = trial_env.make_env(work)
    env = {
        k: v for k, v in env.items() if not k.startswith("MEM_")
    }  # MEM_CLAUDE and the rest of the owner's
    env.update(
        MEM_STORE=str(work / "store"),
        MEM_MEMORIES=str(work / "memories"),
        MEM_DATA=str(work / "data"),
        XDG_STATE_HOME=str(work / "state"),
    )
    return env


def assert_isolated(env: dict, work: Path, project: Path | None = None) -> None:
    allowed = {"MEM_STORE", "MEM_MEMORIES", "MEM_DATA", "MEM_PROJECT"}
    mem_vars = {k: v for k, v in env.items() if k.startswith("MEM_")}
    assert set(mem_vars) <= allowed, f"unexpected MEM_ variables: {sorted(set(mem_vars) - allowed)}"
    for k, v in mem_vars.items():
        assert Path(v).resolve().is_relative_to(work.resolve()), (
            f"{k} is outside the work folder: {v}"
        )
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        assert Path(env[k]).resolve().is_relative_to(work.resolve()), (
            f"{k} is outside the work folder"
        )
    assert not any(k.startswith(("CLAUDE_PLUGIN_OPTION_", "MEM_SETTLE_")) for k in env)
    assert not any("/plugins/cache/" in p for p in env["PATH"].split(os.pathsep)), (
        "installed plugin on PATH"
    )
    assert not work.resolve().is_relative_to(REPO), "the work folder is inside the repository"


def run(cmd: list[str], env: dict, cwd: Path, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, env=env, cwd=cwd, capture_output=True, text=True, check=kw.pop("check", True), **kw
    )


def build_store(work: Path, env: dict) -> tuple[Path, dict[str, str]]:
    """16 lessons that load, written and accepted through the engine; the rules files are what `mem rules` prints."""
    project = work / "store-project"
    project.mkdir()
    run(["git", "init", "-q"], env, project)
    env = {**env, "MEM_PROJECT": str(project)}
    assert_isolated(env, work)
    run([str(MEM), "init", str(work / "store")], env, project)
    for i, (short, topic, weight) in enumerate([*OTHERS[:5], *TRACE, *OTHERS[5:]]):
        args = [
            "remember",
            "--global",
            "--kind",
            "lesson",
            "--claim",
            f"Trial lesson {i:02}: {short}",
            "--origin",
            "transcript",
            "--weight",
            weight,
            "--reach",
            "general",
            "--short",
            short,
            "--topic",
            topic,
        ]
        for s in SOURCES:
            args += ["--source", s]
        run([str(MEM), *args], env, project)
        for path in (work / "memories").rglob("*.md"):
            run(
                [str(MEM), "triage", "accept", path.stem], env, project, check=False
            )  # only a strong one waits
    rules = {}
    for layout in ("flat", "grouped"):
        out = run([str(MEM), "rules", "--layout", layout], env, project).stdout
        (work / f"rules-{layout}.txt").write_text(out, encoding="utf-8")
        rules[layout] = out
    return project, rules


def check_rules(rules: dict[str, str]) -> None:
    flat, grouped = rules["flat"].splitlines(), rules["grouped"].splitlines()
    items = lambda lines: [x for x in lines if x.startswith("- ")]
    assert len(items(flat)) == LESSON_COUNT and sorted(items(flat)) == sorted(items(grouped)), (
        "the blocks differ in lessons"
    )
    assert (
        len([x for x in grouped if x.endswith(":") and not x.startswith("- ")]) == HEADING_COUNT
    ), "seven headings expected"
    assert not any(x.endswith(":") and not x.startswith("-") for x in flat[1:]), (
        "the flat block has headings"
    )
    for short, _, _ in TRACE:
        assert all(any(x.startswith(f"- {short}") for x in lines) for lines in (flat, grouped)), (
            short
        )
    for lines in (items(flat), items(grouped)):
        assert not any(lines[0].startswith(f"- {short}") for short, _, _ in TRACE), (
            "a trace rule ranks first"
        )
    assert not any("more lesson" in x for x in flat + grouped), "a lesson did not fit"


GREET = 'print("Helo, wrold!")\n'
CHECK = """#!/bin/sh
out=$(python3 greet.py)
if [ "$out" = "Hello, world!" ]; then echo "check passed: greeting is correct"; else echo "check FAILED: got '$out'"; exit 1; fi
"""


def make_project(work: Path, name: str) -> Path:
    project = work / name
    project.mkdir()
    (project / "greet.py").write_text(GREET)
    (project / "README.md").write_text("# greeter\n\nPrints a greeting.\n")
    (project / "NOTES.md").write_text("# Notes\n")
    (project / "check.sh").write_text(CHECK)
    (project / "check.sh").chmod(0o755)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "trial@example.invalid"],
        ["config", "user.name", "trial"],
        ["add", "."],
        ["commit", "-q", "-m", "initial"],
    ):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    return project


def write_settings(work: Path, name: str, text_file: Path, tail: str = "") -> Path:
    command = f"cat {text_file}" + (f"; echo {tail}" if tail else "")
    path = work / f"settings-{name}.json"
    path.write_text(
        json.dumps({
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": command}]}]}
        })
    )
    return path


class Session(NamedTuple):
    """Where one headless session runs and what it leaves behind."""

    project: Path
    settings: Path
    trace: Path


def claude(binary: str, prompt: str, session: Session, env: dict, model: str):
    cmd = [
        binary,
        "-p",
        prompt,
        "--model",
        model,
        "--settings",
        str(session.settings),
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
    done = subprocess.run(
        cmd,
        cwd=session.project,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    session.trace.write_text(done.stdout, encoding="utf-8")
    events = []
    for line in done.stdout.splitlines():
        with contextlib.suppress(ValueError):
            events.append(json.loads(line))
    return events, done.stderr


def result_of(events: list) -> dict:
    return next((e for e in reversed(events) if e.get("type") == "result"), {})


def message_parts(events: list):
    """Every dict part of every message content, in order."""
    for e in events:
        message = e.get("message")
        if not isinstance(message, dict):
            continue
        yield from (part for part in message.get("content", []) if isinstance(part, dict))


def result_text(part: dict) -> str:
    body = part.get("content")
    if isinstance(body, list):
        body = "".join(x.get("text", "") for x in body if isinstance(x, dict))
    return body or ""


def bash_runs(events: list) -> list[tuple[str, str]]:
    """(command, output) of every Bash call, in order."""
    uses, out = {}, []
    for part in message_parts(events):
        if part.get("type") == "tool_use" and part.get("name") == "Bash":
            uses[part["id"]] = part["input"].get("command", "")
        elif part.get("type") == "tool_result" and part.get("tool_use_id") in uses:
            out.append((uses[part["tool_use_id"]], result_text(part)))
    return out


def git_out(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=project, capture_output=True, text=True, check=False
    ).stdout


def score(events: list, project: Path) -> dict:
    reply = result_of(events).get("result") or ""
    check_runs = [o for c, o in bash_runs(events) if "check.sh" in c]
    last = (
        next((ln for ln in reversed(check_runs[-1].splitlines()) if ln.strip()), "")
        if check_runs
        else ""
    )
    subject = git_out(project, "log", "-1", "--format=%s")
    commits = git_out(project, "rev-list", "--count", "HEAD")
    notes = (
        (project / "NOTES.md").read_text().splitlines() if (project / "NOTES.md").exists() else []
    )
    return {
        "check": bool(last) and last.strip() in reply,
        "prefix": int(commits or 0) > 1 and PREFIX.match(subject) is not None,
        "notes": len([x for x in notes if x.strip()]) > 1,
    }


@dataclass
class Trial:
    """What every run of the trial shares."""

    args: argparse.Namespace
    work: Path
    env: dict
    rules: dict[str, Path]


@dataclass
class State:
    spent: float
    started: int = 0
    rows: list = field(default_factory=list)
    void: list = field(default_factory=list)


def run_canary(trial: Trial) -> float | None:
    """Cost of the canary session, or None when it failed (the caller stops)."""
    args, out = trial.args, trial.args.out
    token = "TOKEN-" + hashlib.sha256(os.urandom(16)).hexdigest()[:12]
    canary_settings = write_settings(
        trial.work, "canary", trial.rules["flat"], f"'Session token: {token}'"
    )
    empty = trial.work / "canary-project"
    empty.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=empty, check=True)
    events, err = claude(
        args.claude,
        "Repeat the token you were given at session start, exactly. Then say whether you "
        "were given any instruction about validate.py. Two short lines.",
        Session(empty, canary_settings, out / "trace-canary.jsonl"),
        trial.env,
        args.model,
    )
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    reply = result_of(events).get("result") or ""
    print(
        f"canary reply: {reply!r}\ncanary init plugins: {init.get('plugins')!r}, mcp: {init.get('mcp_servers')!r}"
    )
    installed = [
        x for x in init.get("plugins") or [] if x.get("path") != "builtin"
    ]  # built-in ones are not installed
    negative = re.search(r"\b(no|not|none|nothing|n't|never)\b", reply.lower()) is not None
    if token not in reply or not negative or installed:
        print("STOP: the canary failed; nothing is recorded as a result", err[-500:])
        return None
    return result_of(events).get("total_cost_usd") or 0.0


def play(trial: Trial, state: State, cond: str, i: int, attempt: int) -> dict:
    """One session of condition `cond`: scored, logged to runs.jsonl and added to the spend."""
    out = trial.args.out
    tag = f"{cond}{i}" + ("" if attempt == 1 else "b")
    project = make_project(trial.work, f"proj-{tag}")
    settings = write_settings(trial.work, tag, trial.rules["flat" if cond == "F" else "grouped"])
    session = Session(project, settings, out / f"trace-{tag}.jsonl")
    events, _ = claude(trial.args.claude, PROMPT, session, trial.env, trial.args.model)
    res = result_of(events)
    row = {
        "condition": cond,
        "run": i,
        "attempt": attempt,
        **score(events, project),
        "cost": res.get("total_cost_usd") or 0.0,
        "denials": len(res.get("permission_denials") or []),
        "ok": res.get("subtype") == "success",
        "trace": str(session.trace),
    }
    row["void"] = bool(row["denials"]) or not row["ok"]
    state.spent += row["cost"]
    state.started += 1
    print(json.dumps(row))
    with (out / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def run_condition(trial: Trial, state: State, cond: str, i: int) -> int | None:
    """Run one planned session, rerun once when void; an exit code when the trial must stop."""
    for attempt in (1, 2):
        if state.spent >= trial.args.max_cost_usd:
            print(f"STOP: cost {state.spent:.3f} reached the cap")
            return 4
        row = play(trial, state, cond, i, attempt)
        if state.started == FOURTH_RUN and state.spent > STOP_AFTER_FOUR_USD:
            print(f"STOP: cost {state.spent:.3f} after four runs")
            return 4
        if not row["void"]:
            state.rows.append(row)
            return None
        state.void.append(row)
        if len(state.void) > MAX_VOID:
            print(
                "STOP: too many void runs (permission denial or unfinished); no result is recorded"
            )
            return 5
    return None


def print_table(rows: list, spent: float) -> None:
    print(f"\n{'cond':5}{'check':>7}{'prefix':>8}{'notes':>7}{'cost':>8}")
    for cond in "FG":
        mine = [r for r in rows if r["condition"] == cond]
        print(
            f"{cond:5}"
            + "".join(
                f"{sum(r[k] for r in mine)} of {len(mine):>1}".rjust(w)
                for k, w in (("check", 7), ("prefix", 8), ("notes", 7))
            )
            + f"{sum(r['cost'] for r in mine) / max(len(mine), 1):8.3f}"
        )
    print(f"total cost {spent:.3f} USD")


def real_run(args: argparse.Namespace, work: Path, env: dict, rules: dict[str, Path]) -> int:
    out = args.out
    before = snapshot(real_folders())
    (out / "checksums-before.json").write_text(json.dumps(before, indent=1), encoding="utf-8")
    trial = Trial(args, work, env, rules)
    spent = run_canary(trial)
    if spent is None:
        return 3
    state = State(spent)
    for cond, i in [(c, i) for i in range(1, args.runs + 1) for c in "FG"]:
        code = run_condition(trial, state, cond, i)
        if code is not None:
            return code
    after = snapshot(real_folders())
    changed = diff(before, after)
    (out / "checksums-after.json").write_text(json.dumps(after, indent=1), encoding="utf-8")
    print("real folders changed:", json.dumps(changed) if changed else "none")
    print_table(state.rows, state.spent)
    return 6 if changed.get("global-memories") or changed.get("project-memory") else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-cost-usd", type=float, default=1.00)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--claude", default=shutil.which("claude"))
    parser.add_argument(
        "--dry-run", action="store_true", help="build everything and print the blocks; no model"
    )
    args = parser.parse_args()
    args.out = args.out.resolve()
    work = Path(tempfile.mkdtemp(prefix="mem-rules-layout-")).resolve()
    assert not args.out.is_relative_to(REPO) and not work.is_relative_to(REPO), (
        "folders must lie outside the repository"
    )
    args.out.mkdir(parents=True, exist_ok=True)
    assert trial_env.self_check("mem-rules-layout-check-") == 0
    env = trial_env_for(work)
    assert_isolated(env, work)
    project, rules = build_store(work, env)
    assert_isolated({**env, "MEM_PROJECT": str(project)}, work)
    check_rules(rules)
    for layout in ("flat", "grouped"):
        print(f"--- {layout}\n{rules[layout]}", end="")
    print("--- isolation assertions and block checks passed")
    code = 0
    if not args.dry_run:
        code = real_run(args, work, env, {k: work / f"rules-{k}.txt" for k in rules})
    for leftover in trial_env.leftover_folders(work):
        shutil.rmtree(leftover, ignore_errors=True)
        print("removed", leftover.name)
    if args.dry_run:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"work folder kept: {work}")
    return code


if __name__ == "__main__":
    sys.exit(main())
