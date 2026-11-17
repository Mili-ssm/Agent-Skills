#!/usr/bin/env python3
"""Project-synthesis trials: does a stamped project synthesis help an agent find its way in a real project, and does
the "possibly stale" stamp keep it from trusting text that went out of date?

The design and the decision rule are fixed in docs/superpowers/plans/2026-11-17-memory-plugin-project-syntheses.md
(Task 4). The project under test is a copy of this repository at its HEAD, without the files that hold the answers
(CLAUDE.md, the plans, the eval folder), with its own `git init`; each session works in its own copy of a prepared
folder. Phases, run in this order (each keeps its results in a state file in the work folder and skips what is done):

  pilot  each candidate question twice, no syntheses; the 4 with the most tool calls become the orientation cases
  write  one Sonnet session organizes the project into project syntheses; the script adds its own part, then renames
         two files in a commit (the staleness cases)
  ab     arm A (no syntheses) against arm B (syntheses), on the pilot's cases
  stale  S1 (parts as they are: possibly stale) and S2 (stamps rewritten to the new HEAD: fresh), same stale text
  decide the decision rule's action, from the rows in the state file (`all` runs every phase, then this)

Usage: run_trials.py --claude <claude binary> --phase NAME [--work DIR] [--runs N] [--case NAME]... [--jobs 4]
It costs model usage. The work folder is kept (print it, resume with --work); `--phase clean` deletes it. The
auto-memory folders sessions create under ~/.claude/projects are removed after every phase.
`--self-check` runs the harness checks without a model.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[1]
MEM = str(PLUGIN / "bin" / "mem")
LEAVE_OUT = ("CLAUDE.md", "docs/superpowers/plans", "plugins/memory/evals")
TOOLS = ["Read", "Grep", "Glob", "Skill", "Bash(mem *)"]  # identical in every arm, the pilot and the writer
ANSWER_FORMAT = " Responde con la ruta completa del archivo, relativa a la raíz del repositorio, y una frase de justificación."

# Each candidate: name, question (Spanish), a substring of the right path, and the chain that leads to it (verified by
# reading the code at the commit this script was written on). The two with `moved` are the staleness cases: the file
# is renamed inside its folder in a commit and the answer must then hold the new base name, not the old one.
CANDIDATES = [
    {"name": "root-worktree",
     "question": "El comando `mem` busca la carpeta `.memory/` de un proyecto. Si la sesión está dentro de un worktree "
                 "enlazado de git, ¿en qué archivo se decide qué carpeta se toma como raíz del proyecto?",
     "expect": "memory/engine/records.py",
     # mem.py cmd_session_index / _project_synthesis_context call records.project_root(cwd, env), which returns
     # MEM_PROJECT or records._main_worktree(cwd) (the first entry of `git worktree list --porcelain`).
     },
    {"name": "synthesis-shrink",
     "question": "`mem synthesis edit` rechaza un texto nuevo que borra demasiado de la sección que se reescribe. "
                 "¿En qué archivo está la regla que decide cuánto texto se puede perder?",
     "expect": "memory/engine/syntheses.py",
     # mem.py cmd_synthesis edit (syntheses.edit_section(..., shrink=args.shrink), mem.py ~4332) -> syntheses.edit_section
     # -> _guard_shrink, which compares word counts with SHRINK_RATIO = 0.8.
     },
    {"name": "git-wait",
     "question": "Al comprobar si una parte de una síntesis de proyecto sigue vigente se llama a git. ¿En qué archivo "
                 "se fija cuántos segundos se espera como máximo a esa llamada?",
     "expect": "memory/engine/project_syntheses.py",
     # mem.py _part_line / _project_synthesis_block call project_syntheses.freshness -> _git(), whose subprocess.run
     # passes timeout=GIT_TIMEOUT (= 2) defined at the top of project_syntheses.py.
     },
    {"name": "default-store",
     "question": "Una persona instala el plugin de memoria sin configurar la opción `store`. ¿Qué archivo crea el "
                 "almacén por defecto en el primer arranque de una sesión, dándole un máximo de 4 segundos?",
     "expect": "memory/hooks/session-env.sh", "moved": ("plugins/memory/hooks/session-env.sh", "session-setup.sh"),
     # hooks.json SessionStart runs hooks/session-env.sh, whose default_store() calls `timeout 4 .../bin/mem init`
     # when the store marker is missing. Decoy: hooks/session-index.sh also has `timeout 4` (the index, not the init).
     },
    {"name": "fallback-rules",
     "question": "Cuando ni siquiera llega a ejecutarse `mem` al abrir la sesión (sin `uv`, caché fría o tiempo "
                 "agotado), la sesión aún recibe las reglas de memoria sin recuentos. ¿En qué archivo está escrito "
                 "ese texto de reserva?",
     "expect": "memory/hooks/session-index.sh",
     # hooks.json SessionStart (startup|clear|compact) -> hooks/session-index.sh: `else cat <<'TXT'` branch when `out`
     # is empty. Decoy: mem.py _INDEX_RULES is the same text, used only when mem runs and raises.
     },
    {"name": "policy-embed",
     "question": "Los casos de evaluación `*-with-policy` de agent-skills deben llevar incrustada, idéntica, la "
                 "política de offload de `user-config/`. ¿Qué archivo comprueba eso y señala la primera línea que "
                 "difiere?",
     "expect": "scripts/validate.py", "moved": ("scripts/validate.py", "check_repo.py"),
     # scripts/validate.py main() -> check_offload_policy(): globs evals/offload/*-with-policy/case.yaml, compares the
     # append_system_prompt block with user-config/offload-policy.md, reports first_difference(). Decoys: the case
     # files themselves and scripts/port.py (which copies the policy to the ports).
     },
    {"name": "copilot-tools",
     "question": "Un agente de origen declara `tools` y `disallowedTools`. ¿En qué archivo se calcula la lista final "
                 "de herramientas que recibe su versión portada a Copilot?",
     "expect": "scripts/port.py",
     # ports/copilot/** only holds generated output; scripts/port.py copilot_tools() maps agent_tools(fm) (tools minus
     # disallowedTools) through TOOL_MAP and drops duplicates (and Skill).
     },
    {"name": "stale-advice",
     "question": "`mem curate` lista las partes de síntesis de proyecto que pueden estar obsoletas. ¿Qué archivo de "
                 "instrucciones dice al agente qué hacer con una de ellas (reescribirla o confirmarla)?",
     "expect": "skills/memory-curation/SKILL.md",
     # mem.py _curate_project_syntheses only prints `p:NAME#HANDLE <description>`; the advice ("check its files, then
     # add again with the corrected text, or confirm when it still holds") is in skills/memory-curation/SKILL.md.
     },
]
BY_NAME = {c["name"]: c for c in CANDIDATES}
MOVED = [c for c in CANDIDATES if "moved" in c]

# The script's own part: covers the two folders, names the two files by the paths they have before the rename.
OWN_HEADING = "Hook scripts and repository scripts"
OWN_PATHS = "plugins/memory/hooks,scripts"
OWN_BODY = """Two folders hold the scripts the other parts do not describe.

- `plugins/memory/hooks/`: the session hooks of the memory plugin. `plugins/memory/hooks/session-env.sh` hands the
  plugin options to shell commands and, with no `store` option, creates the default store on the first run (bounded
  to 4 seconds). `plugins/memory/hooks/session-index.sh` prints the session index and carries the fallback rules.
- `scripts/`: the repository's maintenance scripts. `scripts/validate.py` is the validator run before every commit;
  among other checks it verifies that the offload evals embed the shipped policy. `scripts/port.py` generates the
  Copilot and Codex ports."""

STAMP = re.compile(r"Covers: (?P<paths>[^|]+?) \| updated (?P<date>\d{4}-\d{2}-\d{2}) at (?P<commit>[0-9a-f]{12}|no-commit)")
SYNTH_USE = re.compile(r"\bmem\s+(?:show\b[^|;&\n]*\bp:|project-synthesis\b)")
WRITER_PROMPT = (
    "Load the memory-curation skill. Then organize this project into project syntheses so that a later agent can "
    "orient itself: where things live and which files hold which behaviour. Read the project first (Read, Grep, "
    "Glob), then write each part with `mem project-synthesis add <name> \"<heading>\" --paths <files or folders it "
    "covers> --body-file -`, passing the text on standard input with a heredoc (you cannot create files). The names "
    "are organization, plans, pending and conventions: use the ones that fit. One topic per part. Stop when the parts "
    "are written and say how many you wrote.")
LOCK = threading.Lock()


# --- harness: folders, git, environment --------------------------------------------------------------------

def git(cwd: Path, *args: str, check: bool = True) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    run = subprocess.run(["git", "-C", str(cwd), *args], env=env, capture_output=True, text=True, check=check)
    return run.stdout


def make_env(work: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("MEM_STORE", "MEM_MEMORIES", "MEM_PROJECT")}
    # An installed copy of the plugin puts its own (older) `mem` on PATH when the controller runs inside Claude Code;
    # the session must get the one under test, which --plugin-dir adds.
    env["PATH"] = os.pathsep.join(d for d in env.get("PATH", "").split(os.pathsep) if "/plugins/cache/" not in d)
    env.update(XDG_CONFIG_HOME=str(work / "cfg"), MEM_DATA=str(work / "data"), XDG_DATA_HOME=str(work / "xdg-data"))
    (work / "cfg" / "agent-memory").mkdir(parents=True, exist_ok=True)
    (work / "cfg" / "agent-memory" / "forbidden-terms").write_text("")
    (work / "data").mkdir(exist_ok=True)
    (work / "xdg-data").mkdir(exist_ok=True)
    return env


def build_base(dest: Path) -> None:
    """Copy of this repository's HEAD without the answers, in its own git repository with one commit."""
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "HEAD"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
    for rel in LEAVE_OUT:
        target = dest / rel
        shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "config", "user.name", "trial")
    git(dest, "config", "user.email", "trial@example.invalid")
    git(dest, "config", "commit.gpgsign", "false")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "base")


def copy_tree(src: Path, dest: Path) -> Path:
    shutil.copytree(src, dest, symlinks=True)
    return dest


def mem(env: dict, cwd: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([MEM, *args], cwd=cwd, env=env, input=stdin, capture_output=True, text=True)


def part_states(env: dict, tree: Path) -> list[tuple[str, str]]:
    """(handle, freshness) of every part, from `mem project-synthesis list`."""
    out = mem(env, tree, "project-synthesis", "list")
    rows = [line.split("\t") for line in out.stdout.splitlines() if line.startswith("p:")]
    return [(r[0], r[1]) for r in rows]


def add_own_part(env: dict, tree: Path) -> None:
    run = mem(env, tree, "project-synthesis", "add", "organization", OWN_HEADING, "--paths", OWN_PATHS,
              "--body-file", "-", stdin=OWN_BODY)
    if run.returncode != 0:
        raise RuntimeError(f"adding the script's own part failed: {run.stderr.strip()}")


def rename_files(tree: Path) -> None:
    for c in MOVED:
        old, new_base = c["moved"]
        git(tree, "mv", old, posixpath.join(posixpath.dirname(old), new_base))
    git(tree, "commit", "-q", "-m", "rename two files")


def new_names() -> list[tuple[str, str]]:
    """(old base name, new base name) of the two moved files."""
    return [(posixpath.basename(c["moved"][0]), c["moved"][1]) for c in MOVED]


def nearest_existing(tree: Path, path: str) -> str:
    while path and not (tree / path).exists():
        path = posixpath.dirname(path)
    return path or "."


def synthesis_files(tree: Path) -> list[Path]:
    return sorted((tree / ".memory" / "syntheses").glob("*.md"))


def strip_stamps(text: str) -> str:
    return "\n".join(ln for ln in text.split("\n") if not STAMP.fullmatch(ln))


def rewrite_stamps(tree: Path) -> None:
    """S2: every stamp gets the new HEAD, each covered path that is gone becomes its nearest existing parent."""
    head = git(tree, "rev-parse", "HEAD").strip()[:12]
    for path in synthesis_files(tree):
        before = path.read_text(encoding="utf-8")
        lines = []
        for ln in before.split("\n"):
            m = STAMP.fullmatch(ln)
            if m:
                paths = list(dict.fromkeys(nearest_existing(tree, p) for p in m["paths"].split(", ")))
                ln = f"Covers: {', '.join(paths)} | updated {m['date']} at {head}"
            lines.append(ln)
        after = "\n".join(lines)
        if strip_stamps(after) != strip_stamps(before):
            raise RuntimeError(f"{path.name}: the rewrite changed more than stamp lines")
        path.write_text(after, encoding="utf-8")


def check_s2(env: dict, tree: Path) -> None:
    states = part_states(env, tree)
    if not states or any(state != "fresh" for _, state in states):
        raise RuntimeError(f"S2 project is not fresh everywhere: {states}")


# --- one model session ---------------------------------------------------------------------------------------

def session(claude: str, model: str, settings: Path, cwd: Path, env: dict, prompt: str, timeout: int = 600) -> dict:
    try:
        run = subprocess.run(
            [claude, "-p", prompt, "--model", model, "--plugin-dir", str(PLUGIN), "--settings", str(settings),
             "--setting-sources", "project", "--allowedTools", *TOOLS,
             "--output-format", "stream-json", "--verbose", "--no-session-persistence"],
            cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        stdout = run.stdout
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    return parse_stream(stdout)


def parse_stream(stdout: str) -> dict:
    seen, calls, used, answer, usage, cost = set(), 0, False, "", {}, None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "assistant":
            for part in event["message"].get("content", []):
                if part.get("type") != "tool_use" or part.get("id") in seen:
                    continue
                seen.add(part.get("id"))
                calls += 1
                data = part.get("input") or {}
                if part["name"] == "Bash" and SYNTH_USE.search(str(data.get("command", ""))):
                    used = True
                elif part["name"] == "Read" and ".memory/syntheses/" in str(data.get("file_path", "")):
                    used = True
        elif event.get("type") == "result":
            answer = event.get("result") or ""
            usage = event.get("usage") or {}
            cost = event.get("total_cost_usd")
    tokens = (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
    return {"answer": answer, "calls": calls, "tokens": tokens, "used": used, "cost": cost, "ok_result": bool(usage)}


def grade(case: dict, arm: str, answer: str) -> bool:
    low = answer.lower()
    if arm in ("S1", "S2"):
        old, new = next((posixpath.basename(c["moved"][0]), c["moved"][1]) for c in MOVED if c is case)
        return new.lower() in low and old.lower() not in low
    return case["expect"].lower() in low


# --- state ---------------------------------------------------------------------------------------------------

class State:
    def __init__(self, work: Path):
        self.path = work / "state.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"rows": []}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=1, ensure_ascii=False))

    def done(self, phase: str, arm: str, case: str, run: int) -> bool:
        return any((r["phase"], r["arm"], r["case"], r["run"]) == (phase, arm, case, run) for r in self.data["rows"])

    def rows(self, phase: str, arm: str | None = None) -> list[dict]:
        return [r for r in self.data["rows"] if r["phase"] == phase and (arm is None or r["arm"] == arm)]


ROW_HEADER = f"{'phase':6} {'arm':3} {'case':16} {'run':3} {'ok':5} {'calls':5} {'tokens':8} {'syn':3} {'cost':6}"


def format_row(r: dict) -> str:
    cost = f"{r['cost']:.2f}" if isinstance(r.get("cost"), (int, float)) else "-"
    return (f"{r['phase']:6} {r['arm']:3} {r['case']:16} {r['run']:<3} {str(r['ok']):5} {r['calls']:<5} "
            f"{r['tokens']:<8} {'yes' if r['used'] else 'no':3} {cost:6}")


def summarize(rows: list[dict], label: str) -> str:
    if not rows:
        return f"{label}: no rows"
    return (f"{label}: correct {sum(r['ok'] for r in rows)}/{len(rows)}, median calls "
            f"{statistics.median(r['calls'] for r in rows):g}, median tokens "
            f"{statistics.median(r['tokens'] for r in rows):g}, used syntheses {sum(r['used'] for r in rows)}/{len(rows)}")


def run_sessions(args, work: Path, env: dict, state: State, jobs: list[tuple[str, str, dict, int, Path]]) -> None:
    """jobs: (phase, arm, case, run, prepared folder). Skips rows already in the state unless --force."""
    settings = work / "settings.json"
    if not settings.exists():
        store = work / "store"
        subprocess.run([MEM, "init", str(store)], env=env, check=True, capture_output=True)
        settings.write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
    todo = [j for j in jobs if args.force or not state.done(j[0], j[1], j[2]["name"], j[3])]
    if args.force:
        state.data["rows"] = [r for r in state.data["rows"] if (r["phase"], r["arm"], r["case"], r["run"]) not in
                              {(j[0], j[1], j[2]["name"], j[3]) for j in todo}]
    print(ROW_HEADER, flush=True)

    def one(job):
        phase, arm, case, run, prepared = job
        cwd = copy_tree(prepared, work / "sessions" / f"{phase}-{arm}-{case['name']}-{run}")
        try:
            out = session(args.claude, args.model, settings, cwd, env, case["question"] + ANSWER_FORMAT)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        row = {"phase": phase, "arm": arm, "case": case["name"], "run": run, "ok": grade(case, arm, out["answer"]),
               "calls": out["calls"], "tokens": out["tokens"], "used": out["used"], "cost": out["cost"],
               "answer": out["answer"][:300]}
        with LOCK:
            state.data["rows"].append(row)
            state.save()
            print(format_row(row) + ("" if out["ok_result"] else "  (no result event)"), flush=True)

    with ThreadPoolExecutor(max_workers=max(args.jobs, 1)) as pool:
        list(pool.map(one, todo))


# --- phases --------------------------------------------------------------------------------------------------

def phase_pilot(args, work, env, state) -> None:
    runs = args.runs or 2
    cases = [BY_NAME[n] for n in args.case] if args.case else CANDIDATES
    base = work / "base"
    if not base.exists():
        build_base(base)
    run_sessions(args, work, env, state, [("pilot", "P", c, r, base) for c in cases for r in range(1, runs + 1)])
    medians = {c["name"]: statistics.median(r["calls"] for r in state.rows("pilot") if r["case"] == c["name"])
               for c in CANDIDATES if any(r["case"] == c["name"] for r in state.rows("pilot"))}
    print("pilot medians of tool calls: " + ", ".join(f"{n}={m:g}" for n, m in medians.items()))
    if len(medians) < len(CANDIDATES):
        print("partial pilot: the rule is not applied")
        return
    enough = [n for n, m in medians.items() if m >= 4]
    ranked = sorted(medians, key=lambda n: (-medians[n], -statistics.mean(
        r["tokens"] for r in state.rows("pilot") if r["case"] == n)))
    state.data["pilot"] = {"medians": medians, "stopped": len(enough) < 4, "cases": ranked[:4]}
    state.save()
    if len(enough) < 4:
        print(f"PILOT STOP: only {len(enough)} cases have a median of 4 calls or more; the measure could not show a "
              "saving. Do not run the other phases.")
    else:
        print("orientation cases: " + ", ".join(ranked[:4]))


def need_pilot(state: State) -> list[dict]:
    pilot = state.data.get("pilot")
    if not pilot or pilot["stopped"]:
        raise SystemExit("the pilot has not chosen cases (run --phase pilot over all candidates; it may have stopped)")
    return [BY_NAME[n] for n in pilot["cases"]]


def phase_write(args, work, env, state) -> None:
    base = work / "base"
    if not base.exists():
        build_base(base)
    written = work / "written"
    if not written.exists():
        copy_tree(base, written)
        settings = work / "settings.json"
        if not settings.exists():
            store = work / "store"
            subprocess.run([MEM, "init", str(store)], env=env, check=True, capture_output=True)
            settings.write_text(json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}))
        out = session(args.claude, args.model, settings, written, env, WRITER_PROMPT, timeout=1800)
        print(f"writer: {out['calls']} tool calls, tokens {out['tokens']}, cost {out['cost']}; says: {out['answer'][:200]!r}")
    parts = part_states(env, written)
    print(f"writer parts: {len(parts)}: " + " ".join(h for h, _ in parts))
    if not parts:
        shutil.rmtree(written)
        raise SystemExit("the writer wrote no part: rerun --phase write")
    prepare_stale(work, env, state, written)
    state.data["writer"] = {"parts": [h for h, _ in parts]}
    state.save()


def prepare_stale(work: Path, env: dict, state: State, written: Path) -> None:
    s1, s2 = work / "stale1", work / "stale2"
    for p in (s1, s2):
        shutil.rmtree(p, ignore_errors=True)
    copy_tree(written, s1)
    add_own_part(env, s1)
    rename_files(s1)
    states = part_states(env, s1)
    if not any(h.startswith("p:organization#") and s == "changed" for h, s in states):
        raise RuntimeError(f"S1 shows no part as possibly stale: {states}")
    copy_tree(s1, s2)
    rewrite_stamps(s2)
    check_s2(env, s2)
    state.data["stale"] = {"s1": states, "s2": part_states(env, s2)}
    print("S1 parts: " + " ".join(f"{h}={s}" for h, s in states))
    print("S2 parts: " + " ".join(f"{h}={s}" for h, s in part_states(env, s2)))


def phase_ab(args, work, env, state) -> None:
    cases = need_pilot(state)
    if args.case:
        cases = [c for c in cases if c["name"] in args.case]
    runs = args.runs or 4
    base, written = work / "base", work / "written"
    if not written.exists():
        raise SystemExit("run --phase write first")
    arms = [("A", base), ("B", written)]
    jobs = [("ab", arm, c, r, folder) for c in cases for r in range(1, runs + 1) for arm, folder in arms
            if not args.arm or arm in args.arm]
    run_sessions(args, work, env, state, jobs)
    for arm, _ in arms:
        print(summarize(state.rows("ab", arm), f"arm {arm}"))


def phase_stale(args, work, env, state) -> None:
    runs = args.runs or 4
    if not (work / "stale1").exists():
        raise SystemExit("run --phase write first")
    cases = [c for c in MOVED if not args.case or c["name"] in args.case]
    jobs = [("stale", arm, c, r, work / ("stale1" if arm == "S1" else "stale2"))
            for c in cases for r in range(1, runs + 1) for arm in ("S1", "S2")]
    run_sessions(args, work, env, state, jobs)
    for arm in ("S1", "S2"):
        print(summarize(state.rows("stale", arm), f"arm {arm}"))


def decide(state: State) -> None:
    A, B, S1, S2 = (state.rows("ab", "A"), state.rows("ab", "B"), state.rows("stale", "S1"), state.rows("stale", "S2"))
    for label, rows in (("A", A), ("B", B), ("S1", S1), ("S2", S2)):
        print(summarize(rows, f"arm {label}"))
    if not (A and B and S1):
        print("decision: needs arms A, B and S1 (and S2 for the stamp's effect)")
        return
    ok = lambda rows: sum(r["ok"] for r in rows)
    med = lambda rows: statistics.median(r["calls"] for r in rows)
    expected = {"A": 16, "B": 16, "S1": 8, "S2": 8}
    for label, rows in (("A", A), ("B", B), ("S1", S1), ("S2", S2)):
        if rows and len(rows) != expected[label]:
            print(f"note: arm {label} has {len(rows)} sessions, the design says {expected[label]}; thresholds scaled")
    scale = len(S1) / 8
    if ok(B) <= ok(A) - 2 or ok(S1) < 6 * scale:
        action = "Do not merge; record the negative result"
    elif sum(r["used"] for r in B) < len(B) / 2:
        action = ("The session sentence does not work: reword it once, rerun B once (--phase ab --arm B --force), then "
                  "apply this table again from the top; a second time, keep the commands and remove the sentence")
    elif med(B) <= 0.75 * med(A) or ok(B) >= ok(A) + 2:
        action = "Keep everything; propose merging to the owner"
    else:
        action = "Keep the commands, remove the session sentence (no measurable gain)"
    print(f"DECISION: {action}")
    tok = lambda rows: f"median {statistics.median(r['tokens'] for r in rows):g}, mean {statistics.mean(r['tokens'] for r in rows):.0f}"
    print("tokens per arm: " + "; ".join(f"{n} {tok(rows)}" for n, rows in (("A", A), ("B", B), ("S1", S1), ("S2", S2)) if rows))
    if S2:
        diff = ok(S1) - ok(S2)
        print(f"S1 minus S2: {diff}" + ("" if diff >= 2 else "; the stamp showed no effect at this sample size"))


# --- self-check, without a model -----------------------------------------------------------------------------

def self_check(work: Path) -> None:
    env = make_env(work)
    base = work / "base"
    build_base(base)
    for rel in (".memory", ".superpowers", "CLAUDE.md", "docs/superpowers/plans", "plugins/memory/evals"):
        assert not (base / rel).exists(), f"{rel} reached the copy"
    assert str(Path.home()) not in Path(__file__).read_text(), "home path in the script"
    for c in CANDIDATES:
        assert any(str(p.relative_to(base)).endswith(c["expect"]) for p in base.rglob(posixpath.basename(c["expect"]))), c["expect"]
    for c in MOVED:
        assert (base / c["moved"][0]).is_file(), c["moved"][0]
    assert not git(base, "status", "--porcelain").strip(), "copy is not clean"
    written = copy_tree(base, work / "written")
    run = mem(env, written, "project-synthesis", "add", "conventions", "Check conventions", "--paths", "scripts",
              "--body-file", "-", stdin="Scripts are run from the repository root.\n")
    assert run.returncode == 0, run.stderr
    assert part_states(env, written) == [("p:conventions#check-conventions", "fresh")], part_states(env, written)
    s1 = copy_tree(written, work / "stale1")
    add_own_part(env, s1)
    rename_files(s1)
    states = dict(part_states(env, s1))
    assert all(v == "changed" for v in states.values()) and len(states) == 2, states
    shown = mem(env, s1, "show", "p:organization#" + next(iter(states)).split("#")[1]).stdout
    assert "possibly stale" in shown, shown
    s2 = copy_tree(s1, work / "stale2")
    before = {p.name: strip_stamps(p.read_text()) for p in synthesis_files(s2)}
    rewrite_stamps(s2)
    check_s2(env, s2)
    assert before == {p.name: strip_stamps(p.read_text()) for p in synthesis_files(s2)}, "bodies differ"
    own = (s2 / ".memory" / "syntheses" / "organization.md").read_text()
    assert "session-env.sh" in own and "validate.py" in own, "the old names left the body"
    index = mem(env, s2, "session-index").stdout
    assert "Store:" not in index, f"a store count shows in the session index: {index!r}"
    assert "Project syntheses:" in index, index
    assert grade(MOVED[0], "S1", "El archivo es plugins/memory/hooks/session-setup.sh")
    assert not grade(MOVED[0], "S1", "plugins/memory/hooks/session-env.sh")
    assert grade(MOVED[1], "S2", "scripts/check_repo.py")
    stream = "\n".join(json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "1", "name": "Bash",
                                                       "input": {"command": "mem show p:organization#x"}}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "1", "name": "Bash", "input": {}},
                                                      {"type": "tool_use", "id": "2", "name": "Read", "input": {}}]}},
        {"type": "result", "result": "ok", "usage": {"input_tokens": 3, "cache_read_input_tokens": 10}}])
    parsed = parse_stream(stream)
    assert (parsed["calls"], parsed["tokens"], parsed["used"]) == (2, 13, True), parsed
    assert shutil.which("mem", path=env["PATH"]) is None, "an installed `mem` is still on PATH"
    print("self-check passed")
    print("  copy: no .memory, .superpowers, CLAUDE.md, plans, evals; clean tree")
    print(f"  S1: {sorted(states.items())}")
    print(f"  S2: {part_states(env, s2)}, bodies byte-equal")
    print("  session-index without a store option: no `Store:` count; no installed `mem` on PATH")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", help="path to the claude binary")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--phase", choices=["pilot", "write", "ab", "stale", "decide", "all", "clean"], default="all")
    parser.add_argument("--pilot", action="store_true", help="same as --phase pilot")
    parser.add_argument("--work", type=Path, help="work folder of an earlier phase (resume); default: a new one")
    parser.add_argument("--runs", type=int, help="per case and arm (pilot 2, ab and stale 4)")
    parser.add_argument("--case", action="append", default=[], help="candidate name; pilot: any, ab: the chosen, stale: the moved")
    parser.add_argument("--arm", action="append", default=[], help="ab only: A or B (e.g. to rerun B)")
    parser.add_argument("--jobs", type=int, default=4, help="parallel sessions")
    parser.add_argument("--force", action="store_true", help="rerun sessions that already have a row")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.pilot:
        args.phase = "pilot"
    for name in args.case:
        if name not in BY_NAME:
            parser.error(f"unknown case {name!r}; candidates: {', '.join(BY_NAME)}")
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="mem-syn-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        if args.self_check:
            self_check(work)
            return 0
        if args.phase == "clean":
            if not args.work:
                parser.error("--phase clean needs --work")
            return 0
        if not args.claude:
            parser.error("--claude is required")
        env = make_env(work)
        state = State(work)
        print(f"work folder: {work}\nstate file:  {state.path}", flush=True)
        phases = {"pilot": phase_pilot, "write": phase_write, "ab": phase_ab, "stale": phase_stale}
        for name in (["pilot", "write", "ab", "stale"] if args.phase == "all" else [args.phase]):
            if name in phases:
                phases[name](args, work, env, state)
                state.save()
                if name == "pilot" and state.data.get("pilot", {}).get("stopped"):
                    return 1
        if args.phase in ("all", "decide"):
            decide(state)
        return 0
    finally:
        encoded = "".join(c if c.isalnum() else "-" for c in work.name)
        for leftover in (Path.home() / ".claude" / "projects").glob(f"*{encoded}*"):
            shutil.rmtree(leftover, ignore_errors=True)
        if args.self_check or args.phase == "clean":
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
