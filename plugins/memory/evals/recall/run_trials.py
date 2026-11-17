#!/usr/bin/env python3
"""Recall trials: does an agent consult the memory unasked, when the answer is only there?

Each case seeds memories that hold something the model cannot know or derive from the project's files, then
gives a request in a fresh headless Claude Code session with the plugin loaded. A case passes when the agent
ran a `mem` command and its answer carries the memory's key fact; the negative case passes when it ran none.

Usage: run_trials.py --claude <path to the claude binary> [--plugin DIR] [--model sonnet] [--runs 2] [--case NAME]...
It costs model usage. Everything lives in a temporary folder; the auto-memory folders the sessions create for the
scratch projects are removed at the end.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_env  # noqa: E402

DEFAULT_PLUGIN = Path(__file__).resolve().parents[2]
DELEGATE = False

# name, files of the scratch project, memories (scope, kind, claim), prompt (Spanish), words the answer must hold
CASES = [
    ("project-pitfall", {"deploy.sh": "#!/bin/sh\nrsync -a build/ deploy@host:/srv/app/\n"},
     [("project", "pitfall", "deploy.sh fails silently when the VPN is not active: it prints no error and "
       "deploys nothing.")],
     "Voy a lanzar deploy.sh ahora. ¿Algo que deba tener en cuenta antes?", ["VPN"]),
    ("project-constraint", {"crontab.txt": "0 4 * * * /srv/app/billing.sh\n0 1 * * * /srv/app/backup.sh\n"},
     [("project", "constraint", "The nightly billing job must not overlap the backup that starts at 01:00 and "
       "runs about two hours: when they overlap billing takes over three hours and misses the bank cut-off.")],
     "Cambia en crontab.txt el job de facturación para que corra a la 01:30; a las 04:00 es demasiado tarde.",
     ["backup"]),
    ("global-lesson", {"requirements.txt": "reportgen==3.1.4\nrequests==2.32.3\n"},
     [("global", "pitfall", "The reportgen library corrupts PDF exports from version 3.2 on; stay on 3.1 "
       "until its maintainers fix it.")],
     "Sube reportgen a la última versión 3.x en requirements.txt.", ["3.2", "PDF"]),
    ("unrelated", {"notes.txt": "x = 1\nprint(x)\n"},
     [("project", "pitfall", "deploy.sh fails silently when the VPN is not active.")],
     "En notes.txt renombra la variable x a total.", None),
]


def session(claude: str, model: str, plugin: Path, settings: Path, cwd: Path, env: dict, prompt: str):
    run = subprocess.run(
        [claude, "-p", prompt, "--model", model, "--plugin-dir", str(plugin), "--settings", str(settings),
         "--setting-sources", "project", "--allowedTools", "Bash(mem *)", "Skill", "Read", "Edit", "Write",
         *(["Agent"] if DELEGATE else []),
         "--output-format", "stream-json", "--verbose", "--no-session-persistence"],
        cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    mem_calls, answer = [], ""
    for line in run.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "assistant":
            for part in event["message"].get("content", []):
                if part.get("type") == "tool_use" and part["name"] == "Bash":
                    command = part["input"].get("command", "")
                    if command.lstrip().startswith("mem "):
                        mem_calls.append(command.split("\n")[0][:60])
        elif event.get("type") == "result":
            answer = event.get("result") or ""
    return mem_calls, answer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude")
    parser.add_argument("--self-check", action="store_true", help="no model: prove the env stays under target/")
    parser.add_argument("--plugin", type=Path, default=DEFAULT_PLUGIN)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--delegate", action="store_true",
                        help="tell the agent to hand the work to a subagent; a run then passes on the facts alone")
    args = parser.parse_args()
    if args.self_check:
        return trial_env.self_check("mem-recall-")
    if not args.claude:
        parser.error("--claude is required")
    global DELEGATE
    DELEGATE = args.delegate
    plugin = args.plugin.resolve()
    mem = str(plugin / "bin" / "mem")
    cases = [c for c in CASES if not args.case or c[0] in args.case]
    work = trial_env.work_dir("mem-recall-")
    env = trial_env.make_env(work)
    passed = total = 0
    print(f"{'case':20} {'run':3} {'mem calls':9} {'facts':5} result")
    for name, files, memories, prompt, facts in cases:
        for run in range(1, args.runs + 1):
            base = work / f"{name}-{run}"
            store, project = base / "store", base / "proj"
            project.mkdir(parents=True)
            subprocess.run([mem, "init", str(store)], env=env, check=True, capture_output=True)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            for file, text in files.items():
                (project / file).write_text(text)
            seed_env = {**env, "MEM_STORE": str(store)}
            for scope, kind, claim in memories:
                command = [mem, "remember", "--kind", kind, "--claim", claim]
                subprocess.run(command + (["--global"] if scope == "global" else []), cwd=project, env=seed_env,
                               check=True, capture_output=True)
            settings = base / "settings.json"
            settings.write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
            if DELEGATE:
                prompt = ("Delega este trabajo en un subagente general-purpose, sin hacerlo tú ni consultar nada antes, "
                          "y dame su resultado: " + prompt)
            calls, answer = session(args.claude, args.model, plugin, settings, project, env, prompt)
            has_facts = facts is not None and all(f.lower() in answer.lower() for f in facts)
            ok = (not calls) if facts is None else (has_facts if DELEGATE else bool(calls) and has_facts)
            passed += ok
            total += 1
            print(f"{name:20} {run:<3} {len(calls):<9} {('-' if facts is None else str(has_facts)):5} "
                  f"{'pass' if ok else 'FAIL'}", flush=True)
    if passed == total:
        trial_env.clean(work)
    else:
        print(f"work folder kept for inspection: {work}")
    print(f"{passed} of {total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
