#!/usr/bin/env python3
"""Routing trials: does an agent put each thing to remember in the right place?

Each case is one headless Claude Code session in a scratch git project, with this plugin loaded and a scratch
store. The script reads the session's tool calls and checks where the agent wrote: the project's `.memory/`,
the global memories folder (`mem remember --global`), and Claude Code's own auto memory.

Usage: run_trials.py --claude <path to the claude binary> [--model sonnet] [--case NAME]...
It costs model usage (about nine short sessions). It never touches a real store: everything lives in a temporary
folder, and the auto-memory folder the sessions create for the scratch project is removed at the end.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_env  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
FIXTURE = PLUGIN / "engine" / "tests" / "fixtures" / "valid"
FORBIDDEN = "Northwind"

# name, prompt (Spanish: the owner's language), expected writes: project, global, auto memory (None = either)
CASES = [
    ("preference", "Recuerda para siempre que prefiero que me respondas con tablas cortas y sin emojis.",
     False, False, True),
    ("project-discovery", "Hemos descubierto hoy que deploy.sh falla en silencio si la VPN no está activa: no da "
     "error y no despliega nada. Acuérdate de esto.", True, False, None),
    ("project-constraint", "En este proyecto el job nocturno de facturación tarda más de 3 horas si se lanza a la "
     "vez que el backup; por eso está programado a las 04:00. Guárdalo.", True, False, None),
    ("project-condition", "Ahora mismo el entorno de staging está caído hasta el viernes por una migración de "
     "base de datos. Recuérdalo y tenlo en cuenta.", True, False, True),
    ("business-name", f"Hemos visto que el cliente {FORBIDDEN} envía los pedidos con la zona horaria mal puesta "
     "y por eso nuestra importación descuadra las fechas. Guárdalo.", True, False, None),
    ("generic-lesson", "Depurando esto hemos aprendido algo que vale para cualquier proyecto: los reintentos sin "
     "clave de idempotencia duplican los efectos secundarios (por ejemplo, cobros dobles). Guárdalo.",
     False, True, None),
    ("research-docs", "He estado investigando y la documentación oficial de PostgreSQL "
     "(https://www.postgresql.org/docs/current/sql-vacuum.html) dice que VACUUM FULL reescribe la tabla entera y "
     "necesita un bloqueo exclusivo. Guárdalo para no tener que buscarlo otra vez.", False, True, None),
    ("research-tool", "Mirando la documentación de git he visto que 'git worktree remove' se niega a borrar un "
     "worktree con cambios sin confirmar salvo que uses --force (https://git-scm.com/docs/git-worktree). "
     "Apúntalo.", False, True, None),
    ("mixed", "Hoy hemos visto dos cosas: que en general pandas convierte en silencio a float las columnas de "
     "enteros con nulos, y que por eso nuestro informe de stock de este proyecto mostraba decimales en las "
     "unidades. Guárdalo.", True, True, None),
]


def tool_calls(stream: str) -> list[tuple[str, str]]:
    calls = []
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "assistant":
            continue
        for part in event["message"].get("content", []):
            if part.get("type") == "tool_use":
                data = part["input"]
                calls.append((part["name"], data.get("command") or data.get("file_path") or data.get("skill") or ""))
    return calls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude")
    parser.add_argument("--self-check", action="store_true", help="no model: prove the env stays under target/")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    if args.self_check:
        return trial_env.self_check("mem-routing-")
    if not args.claude:
        parser.error("--claude is required")
    cases = [c for c in CASES if not args.case or c[0] in args.case]
    work = trial_env.work_dir("mem-routing-")
    env = trial_env.make_env(work)
    (work / "cfg" / "agent-memory" / "forbidden-terms").write_text(FORBIDDEN + "\n")
    store = work / "store"
    subprocess.run([str(PLUGIN / "bin" / "mem"), "init", str(store)], env=env, check=True, capture_output=True)
    for name in ("literature", "knowledge", "topics.yaml"):
        source = FIXTURE / name
        shutil.copytree(source, store / name, dirs_exist_ok=True) if source.is_dir() else shutil.copy(source, store)
    settings = work / "settings.json"
    settings.write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
    failed = 0
    print(f"{'case':20} {'project':8} {'global':7} {'auto':5} result")
    for name, prompt, want_project, want_global, want_auto in cases:
        project = work / f"proj-{name}"
        project.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        (project / "deploy.sh").write_text("#!/bin/sh\necho deploying\n")
        before = {p.name for p in (store / "memories").glob("*.md")}
        run = subprocess.run(
            [args.claude, "-p", prompt, "--model", args.model, "--plugin-dir", str(PLUGIN), "--settings",
             str(settings), "--setting-sources", "project", "--allowedTools", "Bash(mem *)", "Skill", "Read",
             "Write", "Edit", "--output-format", "stream-json", "--verbose", "--no-session-persistence"],
            cwd=project, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        calls = tool_calls(run.stdout)
        got_project = any((project / ".memory").glob("*.md"))
        got_global = bool({p.name for p in (store / "memories").glob("*.md")} - before)
        got_auto = any(tool in ("Write", "Edit") and "/memory/" in value and ".claude" in value
                       for tool, value in calls)
        ok = (got_project == want_project and got_global == want_global
              and (want_auto is None or got_auto == want_auto))
        leaked = any(FORBIDDEN.lower() in p.read_text().lower() for p in store.rglob("*.md"))
        ok = ok and not leaked
        failed += not ok
        print(f"{name:20} {str(got_project):8} {str(got_global):7} {str(got_auto):5} "
              f"{'pass' if ok else 'FAIL'}{' (forbidden term in the store)' if leaked else ''}")
    if not failed:
        trial_env.clean(work)
    else:
        print(f"work folder kept for inspection: {work}")
    print(f"{len(cases) - failed} of {len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
