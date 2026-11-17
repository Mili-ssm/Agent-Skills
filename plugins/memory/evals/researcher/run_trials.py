#!/usr/bin/env python3
"""Researcher trials: does `memory-researcher` answer from the memory as well on Haiku as on Sonnet?

Plan: docs/superpowers/plans/2026-11-17-memory-researcher-haiku.md (its Design and decision rule bind this script).
A headless Haiku session only relays a question to the `memory-researcher` subagent (tools: `Agent` only); the
researcher runs on the arm's model. Every run gets its own copy of a store snapshot and its own scratch project
under `target/mem-trials/`; the owner's store is read once, to make the snapshot, and never written.

Usage: run_trials.py [--claude PATH] [--arm sonnet|haiku]... [--question ID]... [--runs 3] [--jobs 3]
                     [--work DIR (resume)] | --self-check
It costs model usage (60 sessions at the defaults, about 3 to 9 USD).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_env  # noqa: E402

PLUGIN = trial_env.PLUGIN
SOURCE = trial_env.TARGET / "researcher-source"
QUESTIONS = json.loads((Path(__file__).resolve().parent / "questions.json").read_text())
ARMS = ("sonnet", "haiku")
PROMPT = "Ask the memory-researcher subagent: {question}. Reply with its answer verbatim."
AGENT_NAME = re.compile(r"(memory:)?memory-researcher$")
STATE = "state.json"


# --- fixture -------------------------------------------------------------------------------------------------

def ensure_source() -> Path:
    """Copy the owner's default store once, read-only, without its history and curation log."""
    if (SOURCE / "mem-store.yaml").is_file():
        return SOURCE
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    real = Path(data) / "agent-memory" / "store"
    if not (real / "mem-store.yaml").is_file():
        sys.exit(f"no store to copy at {real}")
    shutil.copytree(real, SOURCE, ignore=shutil.ignore_patterns(".git", ".curation-log*"))
    return SOURCE


def make_plugin(work: Path, arm: str) -> Path:
    """The Sonnet arm runs the plugin as shipped; the Haiku arm a copy whose researcher says `model: haiku`."""
    if arm == "sonnet":
        return PLUGIN
    copy = work / "plugin-haiku"
    if not copy.exists():
        shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("evals", "tests", "__pycache__", ".pytest_cache"))
        agent = copy / "agents" / "memory-researcher.md"
        text = agent.read_text()
        new, n = re.subn(r"^model: .*$", "model: haiku", text, count=1, flags=re.M)
        assert n == 1, "the researcher has no model line"
        agent.write_text(new)
    return copy


def make_run(work: Path, name: str) -> tuple[Path, Path, Path]:
    base = work / "runs" / name
    store, project = base / "store", base / "proj"
    shutil.copytree(ensure_source(), store)
    project.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    settings = base / "settings.json"
    settings.write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
    return store, project, settings


# --- session -------------------------------------------------------------------------------------------------

def parse(stdout: str) -> dict:
    """Facts of one stream-json session: subagent dispatches, top-level tool use, subagent models, result."""
    out = dict(dispatches=[], top_tools=[], top_mem=0, sub_models=set(), sub_mem=0, sub_mem_errors=0,
               answer="", model_usage={}, cost=0.0, error=False)
    mem_ids: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        nested = bool(event.get("parent_tool_use_id"))
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content")
        if kind == "assistant" and isinstance(content, list):
            if nested and (message.get("model") or "").strip():
                out["sub_models"].add(message["model"])
            for part in content:
                if part.get("type") != "tool_use":
                    continue
                if not nested:
                    out["top_tools"].append(part["name"])
                    command = (part.get("input") or {}).get("command", "")
                    if part["name"] == "Bash" and command.lstrip().startswith("mem "):
                        out["top_mem"] += 1
                    if part["name"] in ("Agent", "Task"):
                        out["dispatches"].append((part.get("input") or {}).get("subagent_type", ""))
                elif part["name"] == "Bash" and (part.get("input") or {}).get("command", "").lstrip().startswith("mem "):
                    out["sub_mem"] += 1
                    mem_ids.add(part["id"])
        elif kind == "user" and nested and isinstance(content, list):
            for part in content:
                if part.get("type") == "tool_result" and part.get("tool_use_id") in mem_ids:
                    body = part.get("content")
                    text = body if isinstance(body, str) else " ".join(b.get("text", "") for b in body or [])
                    if part.get("is_error") or "Permission" in text or "permission" in text or "no store" in text.lower():
                        out["sub_mem_errors"] += 1
        elif kind == "result":
            out["answer"] = event.get("result") or ""
            out["model_usage"] = event.get("modelUsage") or {}
            out["cost"] = event.get("total_cost_usd") or 0.0
            out["error"] = bool(event.get("is_error"))
    return out


def model_family(model_id: str) -> str:
    return next((f for f in ("haiku", "sonnet", "opus") if f in model_id.lower()), model_id)


def cost_by_family(model_usage: dict) -> dict[str, float]:
    costs: dict[str, float] = {}
    for model, usage in model_usage.items():
        family = model_family(model)
        costs[family] = costs.get(family, 0.0) + float(usage.get("costUSD") or 0.0)
    return costs


def grade(question: dict, answer: str) -> dict:
    low = answer.lower()
    found = sum(any(m.lower() in low for m in f["match"]) for f in question.get("facts", []))
    distractor = question.get("distractor")
    return dict(
        found=found, expected=len(question.get("facts", [])),
        distractor=bool(distractor and any(m.lower() in low for m in distractor["match"])),
        not_covered_ok=(None if question["covered"]
                        else any(p in low for p in QUESTIONS["not_covered_patterns"])))


def valid(parsed: dict, arm: str) -> tuple[bool, str]:
    if parsed["error"] or not parsed["answer"]:
        return False, "no answer"
    if not any(AGENT_NAME.fullmatch(d) for d in parsed["dispatches"]):
        return False, "no researcher dispatch"
    if parsed["top_mem"] or any(t not in ("Agent", "Task") for t in parsed["top_tools"]):
        return False, "top-level tool use"
    costs = cost_by_family(parsed["model_usage"])
    if costs.get(arm, 0.0) <= 0:
        return False, f"{arm} missing from modelUsage"
    if not any(model_family(m) == arm for m in parsed["sub_models"]):
        return False, f"no {arm} message from the subagent"
    return True, ""


def run_session(claude: str, plugin: Path, settings: Path, project: Path, env: dict, question: str) -> dict:
    cmd = [claude, "-p", PROMPT.format(question=question.rstrip("?.")), "--model", "haiku",
           "--plugin-dir", str(plugin), "--settings", str(settings), "--setting-sources", "project",
           # Permissions are inherited by the subagent: the researcher needs mem and file reads; the main session's
           # own use of mem makes a run invalid (graded below). The web stays out so no finding leaks between runs.
           "--allowedTools", "Agent", "Bash(mem *)", "Read", "Grep", "Glob",
           "--disallowedTools", "WebSearch", "WebFetch",
           "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    try:
        done = subprocess.run(cmd, cwd=project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=600)
        raw = done.stdout
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    (project.parent / "stream.jsonl").write_text(raw)
    return parse(raw)


def one_run(claude: str, work: Path, env: dict, question: dict, arm: str, run: int) -> dict:
    name = f"{question['id']}-{arm}-{run}"
    store, project, settings = make_run(work, name)
    plugin = make_plugin(work, arm)
    parsed = run_session(claude, plugin, settings, project, env, question["question"])
    ok, why = valid(parsed, arm)
    row = dict(question=question["id"], arm=arm, run=run, valid=ok, why=why, **grade(question, parsed["answer"]),
               costs=cost_by_family(parsed["model_usage"]), cost=parsed["cost"], words=len(parsed["answer"].split()),
               sub_models=sorted(parsed["sub_models"]), sub_mem=parsed["sub_mem"],
               sub_mem_errors=parsed["sub_mem_errors"], model_usage_keys=sorted(parsed["model_usage"]),
               answer=parsed["answer"])
    shutil.rmtree(store, ignore_errors=True)   # large; the row and stream.jsonl keep the evidence
    return row


# --- report --------------------------------------------------------------------------------------------------

def table_line(r: dict) -> str:
    costs = " ".join(f"{k}={v:.3f}" for k, v in sorted(r["costs"].items()))
    nc = "-" if r["not_covered_ok"] is None else str(r["not_covered_ok"])
    return (f"{r['question']:30} {r['arm']:6} {r['run']:<3} {str(r['valid']):5} {r['found']}/{r['expected']:<3} "
            f"{str(r['distractor']):5} {nc:5} {costs:28} {r['words']:<5} {r['why']}")


HEADER = (f"{'question':30} {'arm':6} {'run':3} {'valid':5} {'facts':5} {'distr':5} {'nc_ok':5} "
          f"{'cost USD per model':28} words")


def decide(rows: list[dict]) -> list[str]:
    """The plan's decision rule, applied to the valid runs."""
    lines = []
    by = {a: [r for r in rows if r["arm"] == a and r["valid"]] for a in ARMS}
    stats = {}
    for arm, rs in by.items():
        answerable = [r for r in rs if r["expected"]]
        nc = [r for r in rs if r["not_covered_ok"] is not None]
        per_run: dict[int, int] = {}
        for r in answerable:
            per_run[r["run"]] = per_run.get(r["run"], 0) + r["found"]
        stats[arm] = dict(
            facts=sum(r["found"] for r in answerable), nc_ok=sum(bool(r["not_covered_ok"]) for r in nc), nc_n=len(nc),
            cost=statistics.median([r["cost"] for r in rs]) if rs else float("nan"),
            words=statistics.median([r["words"] for r in rs]) if rs else float("nan"),
            spread=(max(per_run.values()) - min(per_run.values())) if per_run else 0, n=len(rs),
            distractors=sum(r["distractor"] for r in answerable))
        s = stats[arm]
        lines.append(f"{arm:6} valid={s['n']} facts={s['facts']} distractors={s['distractors']} "
                     f"not-covered ok={s['nc_ok']}/{s['nc_n']} median cost={s['cost']:.4f} "
                     f"median words={s['words']:.0f} spread of run totals={s['spread']}")
    if not all(stats[a]["n"] for a in ARMS):
        return lines + ["Decision rule: not applicable, an arm has no valid run."]
    s, h = stats["sonnet"], stats["haiku"]
    inconclusive = max(s["spread"], h["spread"]) > 2
    facts_ok = h["facts"] >= s["facts"] - 2
    nc_ok = h["nc_n"] > 0 and h["nc_ok"] >= math.ceil(0.75 * h["nc_n"])
    cost_ok = h["cost"] <= s["cost"] / 2
    verdict = ("INCONCLUSIVE (an arm's run totals differ by more than 2 facts): no change" if inconclusive else
               "ADOPT Haiku" if facts_ok and nc_ok and cost_ok else "KEEP Sonnet and record the gap")
    lines.append(f"Decision rule: facts {h['facts']} >= {s['facts']}-2: {facts_ok}; haiku not-covered "
                 f"{h['nc_ok']}/{h['nc_n']} (needs 75%): {nc_ok}; cost {h['cost']:.4f} <= {s['cost']:.4f}/2: {cost_ok}")
    lines.append(f"Verdict: {verdict}")
    return lines


# --- main ----------------------------------------------------------------------------------------------------

def self_check() -> int:
    """No model: a run folder uses the store copy through `pluginConfigs`; the owner's store is untouched."""
    real = trial_env._real_store()
    before = trial_env._snapshot(real)
    work = trial_env.work_dir("mem-researcher-check-")
    try:
        source = ensure_source()
        assert source.resolve().is_relative_to(trial_env.TARGET) and source != real
        assert not (source / ".git").exists() and not list(source.glob(".curation-log*")), "history was copied"
        env = trial_env.make_env(work)
        store, project, settings = make_run(work, "check")
        configured = json.loads(settings.read_text())["pluginConfigs"]["memory"]["options"]["store"]
        assert Path(configured).resolve() == store.resolve() and store.resolve().is_relative_to(trial_env.TARGET)
        assert store.resolve() != real.resolve() and project.resolve().is_relative_to(trial_env.TARGET)
        assert (store / "mem-store.yaml").is_file() and (store / "syntheses").is_dir()
        # What the SessionStart hook does with the option: MEM_STORE for the session's shell commands.
        out = subprocess.run([str(PLUGIN / "bin" / "mem"), "search", "sleep caffeine vigilance", "--handles"],
                             cwd=project, env={**env, "MEM_STORE": configured}, capture_output=True, text=True)
        assert out.returncode == 0 and out.stdout.count("\n") > 1, f"mem search on the copy failed:\n{out.stderr}"
        assert "caffeine-raised" in out.stdout, f"no handle from the copy:\n{out.stdout[:300]}"
        haiku = make_plugin(work, "haiku")
        assert re.search(r"^model: haiku$", (haiku / "agents" / "memory-researcher.md").read_text(), re.M)
        assert re.search(r"^model: sonnet$", (PLUGIN / "agents" / "memory-researcher.md").read_text(), re.M)
        for q in QUESTIONS["questions"]:   # every fact is quoted from its note's part
            for f in q.get("facts", []) + ([q["distractor"]] if "distractor" in q else []):
                text = (source / f["note"]).read_text()
                part = re.search(rf"^## {re.escape(f['part'])}$(.*?)(?=^## |\Z)", text, re.S | re.M)
                assert part and f["match"][0].lower() in part.group(1).lower(), f"{q['id']}: {f['match'][0]!r}"
        assert trial_env._snapshot(real) == before, "a file of the owner's store changed"
    finally:
        trial_env.clean(work)
    print("self-check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude"))
    parser.add_argument("--self-check", action="store_true", help="no model: prove the fixture and the grading")
    parser.add_argument("--arm", action="append", choices=ARMS, default=[])
    parser.add_argument("--question", action="append", default=[], help="question id (repeatable)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--work", type=Path, help="resume the work folder of an earlier run")
    parser.add_argument("--keep", action="store_true", help="keep the work folder at the end")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if not args.claude:
        parser.error("--claude is required (no claude binary found)")
    questions = [q for q in QUESTIONS["questions"] if not args.question or q["id"] in args.question]
    unknown = set(args.question) - {q["id"] for q in questions}
    if unknown:
        parser.error(f"unknown question: {sorted(unknown)}")
    arms = args.arm or list(ARMS)
    work = args.work.resolve() if args.work else trial_env.work_dir("mem-researcher-")
    env = trial_env.make_env(work)
    state_file = work / STATE
    rows = json.loads(state_file.read_text()) if state_file.is_file() else []
    done = {(r["question"], r["arm"], r["run"]) for r in rows if r["valid"]}
    rows = [r for r in rows if r["valid"]]   # an invalid run is rerun on resume
    todo = [(q, a, n) for q in questions for a in arms for n in range(1, args.runs + 1)
            if (q["id"], a, n) not in done]
    lock = threading.Lock()
    print(f"work folder: {work}; {len(todo)} sessions to run, {len(done)} already done", flush=True)
    print(HEADER, flush=True)

    def task(item):
        q, arm, n = item
        row = one_run(args.claude, work, env, q, arm, n)
        with lock:
            rows.append(row)
            state_file.write_text(json.dumps(rows, indent=1))
            print(table_line(row), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(task, todo))
    print("\n" + "\n".join(decide(rows)))
    print(f"total cost USD: {sum(r['cost'] for r in rows):.3f}")
    if all(r["valid"] for r in rows) and not args.keep:
        # Results were printed above; a clean finish leaves nothing behind.
        trial_env.clean(work)
    else:
        print(f"work folder kept (state.json has every row): {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
