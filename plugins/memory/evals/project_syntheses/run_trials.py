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
  decide the decision rule's action, from the rows in the state file (`all` runs every phase, then this); it gives
         none, and exits 1, while an arm has fewer valid rows than planned
  decide-stale  the staleness verdict alone (S1 and S2), when A and B were not run (`decide` does the same when the
         state has no ab rows)

Usage: run_trials.py --claude <claude binary> --phase NAME [--work DIR] [--runs N] [--case NAME]... [--jobs 4]
It costs model usage. The work folder is kept (print it, resume with --work); `--phase clean` deletes it. The
auto-memory folders sessions create under ~/.claude/projects are removed after every phase.
`--self-check` runs the harness checks without a model.
"""

from __future__ import annotations

import argparse
import contextlib
import io
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
from typing import Any, NamedTuple

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[1]


class PluginCopy:
    """The plugin copy the sessions run: make_env replaces `path` with the copy without evals/ (the sessions must not
    see the answers)."""

    path: Path = PLUGIN


LEAVE_OUT = ("CLAUDE.md", "docs/superpowers/plans", "plugins/memory/evals")
TOOLS = [
    "Read",
    "Grep",
    "Glob",
    "Skill",
    "Bash(mem *)",
]  # identical in every arm, the pilot and the writer
# Only the path: a justification could name the old file to say it moved, which the staleness grading counts as wrong.
ANSWER_FORMAT = " Responde solo con la ruta completa del archivo, relativa a la raíz del repositorio, sin más texto."

# Each candidate: name, question (Spanish), a substring of the right path, and the chain that leads to it (verified by
# reading the code at the commit this script was written on). The two with `moved` are the staleness cases: the file
# is renamed inside its folder in a commit and the answer must then hold the new base name, not the old one.
CANDIDATES = [
    {
        "name": "root-worktree",
        "question": "El comando `mem` busca la carpeta `.memory/` de un proyecto. Si la sesión está dentro de un worktree "
        "enlazado de git, ¿en qué archivo se decide qué carpeta se toma como raíz del proyecto?",
        "expect": "memory/engine/memories/locations.py",
        # mem.py cmd_session_index / _project_synthesis_context call records.project_root(cwd, env) (the facade re-exports
        # memories/locations.py), which returns
        # MEM_PROJECT or locations._main_worktree(cwd) (the first entry of `git worktree list --porcelain`).
    },
    {
        "name": "synthesis-shrink",
        "question": "`mem synthesis edit` rechaza un texto nuevo que borra demasiado de la sección que se reescribe. "
        "¿En qué archivo está la regla que decide cuánto texto se puede perder?",
        "expect": "memory/engine/syntheses/document.py",
        # mem.py cmd_synthesis edit (document.edit_section(..., shrink=args.shrink), mem.py ~4332) -> document.edit_section
        # -> _guard_shrink, which compares word counts with SHRINK_RATIO = 0.8.
    },
    {
        "name": "git-wait",
        "question": "Al comprobar si una parte de una síntesis de proyecto sigue vigente se llama a git. ¿En qué archivo "
        "se fija cuántos segundos se espera como máximo a esa llamada?",
        "expect": "memory/engine/syntheses/project.py",
        # mem.py _part_line / _project_synthesis_block call project_syntheses.freshness -> _git(), whose subprocess.run
        # passes timeout=GIT_TIMEOUT (= 2) defined at the top of syntheses/project.py.
    },
    {
        "name": "default-store",
        "question": "Una persona instala el plugin de memoria sin configurar la opción `store`. ¿Qué archivo crea el "
        "almacén por defecto en el primer arranque de una sesión, dándole un máximo de 4 segundos?",
        "expect": "memory/hooks/session-env.sh",
        "moved": ("plugins/memory/hooks/session-env.sh", "session-setup.sh"),
        # hooks.json SessionStart runs hooks/session-env.sh, whose default_store() calls `timeout 4 .../bin/mem init`
        # when the store marker is missing. Decoy: hooks/session-index.sh also has `timeout 4` (the index, not the init).
    },
    {
        "name": "fallback-rules",
        "question": "Cuando ni siquiera llega a ejecutarse `mem` al abrir la sesión (sin `uv`, caché fría o tiempo "
        "agotado), la sesión aún recibe las reglas de memoria sin recuentos. ¿En qué archivo está escrito "
        "ese texto de reserva?",
        "expect": "memory/hooks/session-index.sh",
        # hooks.json SessionStart (startup|clear|compact) -> hooks/session-index.sh: `else cat <<'TXT'` branch when `out`
        # is empty. Decoy: mem.py _INDEX_RULES is the same text, used only when mem runs and raises.
    },
    {
        "name": "policy-embed",
        "question": "Los casos de evaluación `*-with-policy` de agent-skills deben llevar incrustada, idéntica, la "
        "política de offload de `user-config/`. ¿Qué archivo comprueba eso y señala la primera línea que "
        "difiere?",
        "expect": "scripts/validate.py",
        "moved": ("scripts/validate.py", "check_repo.py"),
        # scripts/validate.py main() -> check_offload_policy(): globs evals/offload/*-with-policy/case.yaml, compares the
        # append_system_prompt block with user-config/offload-policy.md, reports first_difference(). Decoys: the case
        # files themselves and scripts/port.py (which copies the policy to the ports).
    },
    {
        "name": "copilot-tools",
        "question": "Un agente de origen declara `tools` y `disallowedTools`. ¿En qué archivo se calcula la lista final "
        "de herramientas que recibe su versión portada a Copilot?",
        "expect": "scripts/port.py",
        # ports/copilot/** only holds generated output; scripts/port.py copilot_tools() maps agent_tools(fm) (tools minus
        # disallowedTools) through TOOL_MAP and drops duplicates (and Skill).
    },
    {
        "name": "stale-advice",
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

STAMP = re.compile(
    r"Covers: (?P<paths>[^|]+?) \| updated (?P<date>\d{4}-\d{2}-\d{2}) at (?P<commit>[0-9a-f]{12}|no-commit)"
)
SYNTH_USE = re.compile(r"\bmem\s+(?:show\b[^|;&\n]*\bp:|project-synthesis\b)")
WRITER_PROMPT = (
    "Load the memory-curation skill. Then organize this project into project syntheses so that a later agent can "
    "orient itself: where things live and which files hold which behaviour. Read the project first (Read, Grep, "
    'Glob), then write each part with `mem project-synthesis add <name> "<heading>" --paths <files or folders it '
    "covers> --body-file -`, passing the text on standard input with a heredoc (you cannot create files). The names "
    "are organization, plans, pending and conventions: use the ones that fit. One topic per part. Stop when the parts "
    "are written and say how many you wrote."
)
LOCK = threading.Lock()

# Thresholds of the pilot and of the decision rule (the plan's Task 4).
PILOT_CASES = 4  # the cases with the most tool calls become the orientation cases
PILOT_MIN_CALLS = 4  # a case needs this median of tool calls to count as an orientation case
S1_MIN_CORRECT = 6  # fewer correct answers in S1: the stamp does not protect the reader
MIN_EFFECT = 2  # the smallest difference in correct answers that counts as an effect
MAX_DIFFS_SHOWN = 5
EXPECTED_PARTS = 2  # the self-check's conventions part plus the script's own part


# --- harness: folders, git, environment --------------------------------------------------------------------


def git(cwd: Path, *args: str, check: bool = True) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    run = subprocess.run(
        ["git", "-C", str(cwd), *args], env=env, capture_output=True, text=True, check=check
    )
    return run.stdout


def clean_env() -> dict:
    env = {
        k: v for k, v in os.environ.items() if k not in {"MEM_STORE", "MEM_MEMORIES", "MEM_PROJECT"}
    }
    # An installed copy of the plugin puts its own (older) `mem` on PATH when the controller runs inside Claude Code;
    # the session must get the one under test, which --plugin-dir adds.
    env["PATH"] = os.pathsep.join(
        d for d in env.get("PATH", "").split(os.pathsep) if "/plugins/cache/" not in d
    )
    return env


def sync_plugin_copy(copy: Path) -> None:
    """Creates the plugin copy, or refuses a resumed one that differs from the current plugin."""
    if not copy.exists():
        # A session that loads a skill sees the plugin's base folder, and evals/ holds the expected answers.
        shutil.copytree(
            PLUGIN, copy, symlinks=True, ignore=shutil.ignore_patterns("evals", "__pycache__")
        )
        return
    diff = plugin_diff(PLUGIN, copy)
    if diff:
        raise SystemExit(
            "the work folder's plugin copy differs from the current plugins/memory ("
            + "; ".join(diff[:MAX_DIFFS_SHOWN])
            + (f"; {len(diff) - MAX_DIFFS_SHOWN} more" if len(diff) > MAX_DIFFS_SHOWN else "")
            + "): start a new work folder"
        )


def make_env(work: Path) -> dict:
    env = clean_env()
    PluginCopy.path = work / "plugin"
    sync_plugin_copy(PluginCopy.path)
    env.update(
        XDG_CONFIG_HOME=str(work / "cfg"),
        MEM_DATA=str(work / "data"),
        XDG_DATA_HOME=str(work / "xdg-data"),
    )
    (work / "cfg" / "agent-memory").mkdir(parents=True, exist_ok=True)
    (work / "cfg" / "agent-memory" / "forbidden-terms").write_text("", encoding="utf-8")
    (work / "data").mkdir(exist_ok=True)
    (work / "xdg-data").mkdir(exist_ok=True)
    return env


def plugin_files(root: Path) -> dict[str, str]:
    """Relative path -> content (symlinks: their target) of the plugin files a session sees (no evals/, no caches)."""
    found = {}
    for here, dirs, files in os.walk(root):
        rel = Path(here).relative_to(root)
        dirs[:] = [
            d for d in dirs if d != "__pycache__" and not (rel == Path(".") and d == "evals")
        ]
        for name in dirs + files:
            path = Path(here) / name
            key = str(rel / name)
            if path.is_symlink():
                found[key] = "link:" + os.readlink(path)
            elif path.is_file():
                found[key] = "file:" + path.read_bytes().hex()
    return found


def plugin_diff(src: Path, copy: Path) -> list[str]:
    a, b = plugin_files(src), plugin_files(copy)
    return (
        [f"{k} missing from the copy" for k in sorted(a.keys() - b.keys())]
        + [f"{k} only in the copy" for k in sorted(b.keys() - a.keys())]
        + [f"{k} differs" for k in sorted(k for k in a.keys() & b.keys() if a[k] != b[k])]
    )


def build_base(dest: Path) -> None:
    """Copy of this repository's HEAD without the answers, in its own git repository with one commit."""
    dest.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-C", str(REPO), "archive", "HEAD"], capture_output=True, check=True
    ).stdout
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


def mem_bin() -> str:
    return str(PluginCopy.path / "bin" / "mem")


def mem(env: dict, cwd: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [mem_bin(), *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def part_states(env: dict, tree: Path) -> list[tuple[str, str]]:
    """(handle, freshness) of every part, from `mem project-synthesis list`."""
    out = mem(env, tree, "project-synthesis", "list")
    rows = [line.split("\t") for line in out.stdout.splitlines() if line.startswith("p:")]
    return [(r[0], r[1]) for r in rows]


def strip_to_syntheses(tree: Path) -> list[str]:
    """Arm B must differ from A only by the syntheses: the writer may also have written memories (it has `mem *`)."""
    removed = []
    for entry in sorted((tree / ".memory").iterdir()) if (tree / ".memory").is_dir() else []:
        if entry.name == "syntheses":
            continue
        shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
        removed.append(entry.name)
    return removed


def add_own_part(env: dict, tree: Path) -> None:
    run = mem(
        env,
        tree,
        "project-synthesis",
        "add",
        "organization",
        OWN_HEADING,
        "--paths",
        OWN_PATHS,
        "--body-file",
        "-",
        stdin=OWN_BODY,
    )
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


def restamp(tree: Path, line: str, head: str) -> str:
    """The line with the new HEAD and the covered paths that still exist when it is a stamp; any other line as it is."""
    m = STAMP.fullmatch(line)
    if not m:
        return line
    paths = list(dict.fromkeys(nearest_existing(tree, p) for p in m["paths"].split(", ")))
    return f"Covers: {', '.join(paths)} | updated {m['date']} at {head}"


def rewrite_stamps(tree: Path) -> None:
    """S2: every stamp gets the new HEAD, each covered path that is gone becomes its nearest existing parent."""
    head = git(tree, "rev-parse", "HEAD").strip()[:12]
    for path in synthesis_files(tree):
        before = path.read_text(encoding="utf-8")
        after = "\n".join(restamp(tree, line, head) for line in before.split("\n"))
        if strip_stamps(after) != strip_stamps(before):
            raise RuntimeError(f"{path.name}: the rewrite changed more than stamp lines")
        path.write_text(after, encoding="utf-8")


def check_s2(env: dict, tree: Path) -> None:
    states = part_states(env, tree)
    if not states or any(state != "fresh" for _, state in states):
        raise RuntimeError(f"S2 project is not fresh everywhere: {states}")


def check_s1(env: dict, tree: Path) -> None:
    states = part_states(env, tree)
    if not any(h.startswith("p:organization#") and s == "changed" for h, s in states):
        raise RuntimeError(f"S1 shows no part as possibly stale: {states}")
    shown = mem(
        env, tree, "show", next(h for h, _ in states if h.startswith("p:organization#"))
    ).stdout
    if "possibly stale" not in shown:
        raise RuntimeError("S1: the organization part does not read as possibly stale")


# --- one model session ---------------------------------------------------------------------------------------


class Launch(NamedTuple):
    """What every model session shares: the claude binary, the model and the settings file."""

    claude: str
    model: str
    settings: Path


def session(launch: Launch, cwd: Path, env: dict, prompt: str, timeout: int = 600) -> dict:
    error = None
    try:
        run = subprocess.run(
            [
                launch.claude,
                "-p",
                prompt,
                "--model",
                launch.model,
                "--plugin-dir",
                str(PluginCopy.path),
                "--settings",
                str(launch.settings),
                "--setting-sources",
                "project",
                "--allowedTools",
                *TOOLS,
                "--output-format",
                "stream-json",
                "--verbose",
                "--no-session-persistence",
            ],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = run.stdout
        if run.returncode != 0:
            error = f"exit code {run.returncode}: {run.stderr.strip()[-200:]}"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        error = f"timeout after {timeout}s"
    out = parse_stream(stdout)
    error = error or out["error"]
    if error is None and not out["has_result"]:
        error = "no final result event"
    out["error"] = error
    return out


def uses_syntheses(part: dict) -> bool:
    """Whether a tool call reads the project syntheses (a `mem` command about them, or a Read of their folder)."""
    data = part.get("input") or {}
    if part["name"] == "Bash":
        return bool(SYNTH_USE.search(str(data.get("command", ""))))
    return part["name"] == "Read" and ".memory/syntheses/" in str(data.get("file_path", ""))


def new_tool_uses(event: dict, seen: set) -> list[dict]:
    """The tool calls of an assistant event whose id was not seen yet (the stream repeats them)."""
    parts = []
    for part in event["message"].get("content", []):
        if part.get("type") != "tool_use" or part.get("id") in seen:
            continue
        seen.add(part.get("id"))
        parts.append(part)
    return parts


def stream_events(stdout: str) -> list[Any]:
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def parse_stream(stdout: str) -> dict:
    seen: set = set()
    calls, used, results = 0, False, []
    for event in stream_events(stdout):
        if event.get("type") == "assistant":
            parts = new_tool_uses(event, seen)
            calls += len(parts)
            used = used or any(uses_syntheses(part) for part in parts)
        elif event.get("type") == "result":
            results.append(event)
    last = results[-1] if results else {}
    answer = last.get("result") or ""
    usage = last.get("usage") or {}
    errors = [e for e in results if e.get("is_error")]
    error = f"result is an error: {(errors[-1].get('result') or '')[:200]}" if errors else None
    tokens = (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
    return {
        "answer": answer,
        "calls": calls,
        "tokens": tokens,
        "used": used,
        "cost": last.get("total_cost_usd"),
        "has_result": bool(results),
        "error": error,
    }


def grade(case: dict, arm: str, answer: str) -> bool:
    low = answer.lower()
    if arm in {"S1", "S2"}:
        old, new = next(
            (posixpath.basename(c["moved"][0]), c["moved"][1]) for c in MOVED if c is case
        )
        return new.lower() in low and old.lower() not in low
    return case["expect"].lower() in low


# --- state ---------------------------------------------------------------------------------------------------


class State:
    def __init__(self, work: Path):
        self.path = work / "state.json"
        self.data: dict[str, Any] = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else {"rows": []}
        )

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")

    def done(self, phase: str, arm: str, case: str, run: int) -> bool:
        """A row with an error is not done: a resumed run retries it."""
        return any(
            (r["phase"], r["arm"], r["case"], r["run"]) == (phase, arm, case, run)
            and not r.get("error")
            for r in self.data["rows"]
        )

    def rows(self, phase: str, arm: str | None = None) -> list[dict]:
        """Valid rows only: error rows stay out of medians and of the decision."""
        return [r for r in self.errors_and_valid(phase, arm) if not r.get("error")]

    def errors(self, phase: str, arm: str | None = None) -> list[dict]:
        return [r for r in self.errors_and_valid(phase, arm) if r.get("error")]

    def errors_and_valid(self, phase: str, arm: str | None) -> list[dict]:
        return [
            r for r in self.data["rows"] if r["phase"] == phase and (arm is None or r["arm"] == arm)
        ]


ROW_HEADER = f"{'phase':6} {'arm':3} {'case':16} {'run':3} {'ok':5} {'calls':5} {'tokens':8} {'syn':3} {'cost':6}"


def format_row(r: dict) -> str:
    if r.get("error"):
        return f"{r['phase']:6} {r['arm']:3} {r['case']:16} {r['run']:<3} error: {r['error']}"
    cost = f"{r['cost']:.2f}" if isinstance(r.get("cost"), (int, float)) else "-"
    return (
        f"{r['phase']:6} {r['arm']:3} {r['case']:16} {r['run']:<3} {r['ok']!s:5} {r['calls']:<5} "
        f"{r['tokens']:<8} {'yes' if r['used'] else 'no':3} {cost:6}"
    )


def summarize(rows: list[dict], label: str, errors: int = 0) -> str:
    label = f"{label} ({errors} failed sessions excluded)" if errors else label
    if not rows:
        return f"{label}: no rows"
    return (
        f"{label}: correct {sum(r['ok'] for r in rows)}/{len(rows)}, median calls "
        f"{statistics.median(r['calls'] for r in rows):g}, median tokens "
        f"{statistics.median(r['tokens'] for r in rows):g}, used syntheses {sum(r['used'] for r in rows)}/{len(rows)}"
    )


class Ctx(NamedTuple):
    """What every session of a phase shares."""

    args: Any
    work: Path
    env: dict
    state: State
    settings: Path


def ensure_settings(env: dict, store: Path, settings: Path) -> None:
    """A store of its own for the sessions, named in a settings file; kept when it already exists."""
    if settings.exists():
        return
    subprocess.run([mem_bin(), "init", str(store)], env=env, check=True, capture_output=True)
    settings.write_text(
        json.dumps({"pluginConfigs": {"memory": {"options": {"store": str(store)}}}}),
        encoding="utf-8",
    )


def run_job(ctx: Ctx, job: tuple[str, str, dict, int, Path]) -> None:
    phase, arm, case, run, prepared = job
    cwd = copy_tree(prepared, ctx.work / "sessions" / f"{phase}-{arm}-{case['name']}-{run}")
    try:
        launch = Launch(ctx.args.claude, ctx.args.model, ctx.settings)
        out = session(launch, cwd, ctx.env, case["question"] + ANSWER_FORMAT)
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    row = {
        "phase": phase,
        "arm": arm,
        "case": case["name"],
        "run": run,
        "ok": not out["error"] and grade(case, arm, out["answer"]),
        "calls": out["calls"],
        "tokens": out["tokens"],
        "used": out["used"],
        "cost": out["cost"],
        "answer": out["answer"][:300],
    }
    if out["error"]:
        row["error"] = out["error"]
    with LOCK:
        ctx.state.data["rows"].append(row)
        ctx.state.save()
        print(format_row(row), flush=True)


def run_sessions(
    args, work: Path, env: dict, state: State, jobs: list[tuple[str, str, dict, int, Path]]
) -> None:
    """jobs: (phase, arm, case, run, prepared folder). Skips rows already in the state unless --force."""
    settings = work / "settings.json"
    ensure_settings(env, work / "store", settings)
    todo = [j for j in jobs if args.force or not state.done(j[0], j[1], j[2]["name"], j[3])]
    # Rows about to be rerun (forced, or failed earlier) are replaced by the new ones.
    redo = {(j[0], j[1], j[2]["name"], j[3]) for j in todo}
    state.data["rows"] = [
        r for r in state.data["rows"] if (r["phase"], r["arm"], r["case"], r["run"]) not in redo
    ]
    print(ROW_HEADER, flush=True)
    ctx = Ctx(args, work, env, state, settings)
    with ThreadPoolExecutor(max_workers=max(args.jobs, 1)) as pool:
        list(pool.map(lambda job: run_job(ctx, job), todo))


# --- phases --------------------------------------------------------------------------------------------------


def phase_pilot(args, work, env, state) -> None:
    runs = args.runs or 2
    cases = [BY_NAME[n] for n in args.case] if args.case else CANDIDATES
    base = work / "base"
    if not base.exists():
        build_base(base)
    run_sessions(
        args,
        work,
        env,
        state,
        [("pilot", "P", c, r, base) for c in cases for r in range(1, runs + 1)],
    )
    valid = {
        c["name"]: [r for r in state.rows("pilot") if r["case"] == c["name"]] for c in CANDIDATES
    }
    for n, rows in valid.items():
        if rows and len(rows) < runs:
            print(
                f"pilot case {n}: {len(rows)} valid of {runs} planned: not ranked (rerun the phase)"
            )
    medians = {
        n: statistics.median(r["calls"] for r in rows)
        for n, rows in valid.items()
        if len(rows) >= runs
    }
    print("pilot medians of tool calls: " + ", ".join(f"{n}={m:g}" for n, m in medians.items()))
    if len(medians) < len(CANDIDATES):
        print(
            "partial pilot (cases missing, not run or short of valid runs): the rule is not applied"
        )
        return
    enough = [n for n, m in medians.items() if m >= PILOT_MIN_CALLS]
    ranked = sorted(
        medians,
        key=lambda n: (
            -medians[n],
            -statistics.mean(r["tokens"] for r in state.rows("pilot") if r["case"] == n),
        ),
    )
    state.data["pilot"] = {
        "medians": medians,
        "stopped": len(enough) < PILOT_CASES,
        "cases": ranked[:PILOT_CASES],
    }
    state.save()
    if len(enough) < PILOT_CASES:
        print(
            f"PILOT STOP: only {len(enough)} cases have a median of 4 calls or more; the measure could not show a "
            "saving. Do not run the other phases."
        )
    else:
        print("orientation cases: " + ", ".join(ranked[:PILOT_CASES]))


def need_pilot(state: State) -> list[dict]:
    pilot = state.data.get("pilot")
    if not pilot or pilot["stopped"]:
        raise SystemExit(
            "the pilot has not chosen cases (run --phase pilot over all candidates; it may have stopped)"
        )
    return [BY_NAME[n] for n in pilot["cases"]]


def phase_write(args, work, env, state) -> None:
    base = work / "base"
    if not base.exists():
        build_base(base)
    written = work / "written"
    if not written.exists():
        copy_tree(base, written)
        # The writer gets a store, data and global-memory folders of its own: what it records there with
        # `mem remember` must not reach the arms, which read work/store.
        wenv = {
            **env,
            "MEM_DATA": str(work / "writer-data"),
            "XDG_DATA_HOME": str(work / "writer-xdg-data"),
        }
        settings = work / "writer-settings.json"
        ensure_settings(wenv, work / "writer-store", settings)
        out = session(
            Launch(args.claude, args.model, settings), written, wenv, WRITER_PROMPT, timeout=1800
        )
        if out["error"]:
            shutil.rmtree(written)
            raise SystemExit(f"the writer session failed ({out['error']}): rerun --phase write")
        print(
            f"writer: {out['calls']} tool calls, tokens {out['tokens']}, cost {out['cost']}; says: {out['answer'][:200]!r}"
        )
    removed = strip_to_syntheses(written)
    print("removed from the written copy's .memory/: " + (", ".join(removed) or "nothing"))
    state.data["writer_removed"] = sorted(set(state.data.get("writer_removed", [])) | set(removed))
    state.data["written_stripped"] = True
    parts = part_states(env, written)
    print(f"writer parts: {len(parts)}: " + " ".join(h for h, _ in parts))
    if not parts:
        shutil.rmtree(written)
        raise SystemExit("the writer wrote no part: rerun --phase write")
    state.data["writer"] = {"parts": [h for h, _ in parts]}
    state.save()


def need_written(work: Path, state: State) -> Path:
    written = work / "written"
    if not written.exists():
        raise SystemExit("run --phase write first")
    memory = written / ".memory"
    if not state.data.get("written_stripped") or (
        memory.is_dir() and [p.name for p in memory.iterdir()] != ["syntheses"]
    ):
        raise SystemExit(
            "the written copy was not cleaned to its syntheses by --phase write: start a new work folder"
        )
    return written


def prepare_stale(work: Path, env: dict, state: State, written: Path) -> None:
    """Builds S1 and S2 once, from the written copy that `strip_to_syntheses` has processed; a resume keeps them."""
    s1, s2 = work / "stale1", work / "stale2"
    if s1.exists() and s2.exists() and state.data.get("stale"):
        return
    for p in (s1, s2):
        shutil.rmtree(p, ignore_errors=True)
    copy_tree(written, s1)
    add_own_part(env, s1)
    rename_files(s1)
    copy_tree(s1, s2)
    rewrite_stamps(s2)
    state.data["stale"] = {"s1": part_states(env, s1), "s2": part_states(env, s2)}
    state.save()


def phase_ab(args, work, env, state) -> None:
    cases = need_pilot(state)
    if args.case:
        cases = [c for c in cases if c["name"] in args.case]
    runs = args.runs or 4
    base, written = work / "base", need_written(work, state)
    arms = [("A", base), ("B", written)]
    jobs = [
        ("ab", arm, c, r, folder)
        for c in cases
        for r in range(1, runs + 1)
        for arm, folder in arms
        if not args.arm or arm in args.arm
    ]
    run_sessions(args, work, env, state, jobs)
    for arm, _ in arms:
        print(summarize(state.rows("ab", arm), f"arm {arm}", len(state.errors("ab", arm))))


def phase_stale(args, work, env, state) -> None:
    runs = args.runs or 4
    prepare_stale(work, env, state, need_written(work, state))
    try:
        check_s1(env, work / "stale1")
        check_s2(env, work / "stale2")
    except RuntimeError as exc:
        raise SystemExit(f"no S session was run: {exc}") from exc
    print("S1 parts: " + " ".join(f"{h}={s}" for h, s in part_states(env, work / "stale1")))
    print("S2 parts: " + " ".join(f"{h}={s}" for h, s in part_states(env, work / "stale2")))
    cases = [c for c in MOVED if not args.case or c["name"] in args.case]
    jobs = [
        ("stale", arm, c, r, work / ("stale1" if arm == "S1" else "stale2"))
        for c in cases
        for r in range(1, runs + 1)
        for arm in ("S1", "S2")
    ]
    run_sessions(args, work, env, state, jobs)
    for arm in ("S1", "S2"):
        print(summarize(state.rows("stale", arm), f"arm {arm}", len(state.errors("stale", arm))))


PLANNED = {("ab", "A"): 16, ("ab", "B"): 16, ("stale", "S1"): 8, ("stale", "S2"): 8}


def short_arms(state: State, needed: list[tuple[str, str]]) -> list[str]:
    """Arms with fewer valid rows than planned; also prints `N valid of M planned` for each arm needed."""
    short = []
    for phase, arm in needed:
        valid, planned = len(state.rows(phase, arm)), PLANNED[phase, arm]
        print(f"arm {arm}: {valid} valid of {planned} planned")
        if valid < planned:
            short.append(arm)
    return short


def correct(rows: list[dict]) -> int:
    return sum(r["ok"] for r in rows)


def median_calls(rows: list[dict]) -> float:
    return statistics.median(r["calls"] for r in rows)


def decide_stale(state: State) -> int:
    short = short_arms(state, [("stale", "S1"), ("stale", "S2")])
    if short:
        print(
            f"decision: none; arm(s) {', '.join(short)} lack valid rows: run --phase stale again to retry"
        )
        return 1
    s1, s2 = state.rows("stale", "S1"), state.rows("stale", "S2")
    for label, rows in (("S1", s1), ("S2", s2)):
        print(
            summarize(rows, f"arm {label}")
            + f"; tokens mean {statistics.mean(r['tokens'] for r in rows):.0f}"
        )
    diff = correct(s1) - correct(s2)
    print(
        f"S1 correct of {len(s1)}: {correct(s1)}; S2 correct of {len(s2)}: {correct(s2)}; S1 minus S2: {diff}"
    )
    print(f"syntheses used: S1 {sum(r['used'] for r in s1)}, S2 {sum(r['used'] for r in s2)}")
    if correct(s1) < S1_MIN_CORRECT:
        verdict = "the stamp does not protect the reader: do not merge"
    elif diff >= MIN_EFFECT:
        verdict = "the stamp has an effect"
    else:
        verdict = "the stamp showed no effect at this sample size"
    print(f"VERDICT: {verdict}")
    return 0


def choose_action(a: list[dict], b: list[dict], s1: list[dict]) -> str:
    """The decision rule's action from the rows of arms A, B and S1."""
    if correct(b) <= correct(a) - MIN_EFFECT or correct(s1) < S1_MIN_CORRECT:
        return "Do not merge; record the negative result"
    if sum(r["used"] for r in b) < len(b) / 2:
        return (
            "The session sentence does not work: reword it once, rerun B once (--phase ab --arm B --force), then "
            "apply this table again from the top; a second time, keep the commands and remove the sentence"
        )
    if median_calls(b) <= 0.75 * median_calls(a) or correct(b) >= correct(a) + MIN_EFFECT:
        return "Keep everything; propose merging to the owner"
    return "Keep the commands, remove the session sentence (no measurable gain)"


def decide(state: State) -> int:
    if not state.errors_and_valid("ab", None):
        return decide_stale(state)
    arms = [("ab", "A"), ("ab", "B"), ("stale", "S1"), ("stale", "S2")]
    short = short_arms(state, arms)
    if short:
        print(
            f"decision: none; arm(s) {', '.join(short)} lack valid rows: rerun the phases to retry the failed or missing sessions"
        )
        return 1
    a, b, s1, s2 = (state.rows(p, arm) for p, arm in arms)
    action = choose_action(a, b, s1)
    for label, rows in (("A", a), ("B", b), ("S1", s1), ("S2", s2)):
        print(
            summarize(rows, f"arm {label}")
            + f"; tokens mean {statistics.mean(r['tokens'] for r in rows):.0f}"
        )
    print(f"DECISION: {action}")
    diff = correct(s1) - correct(s2)
    print(
        f"S1 minus S2: {diff}"
        + ("" if diff >= MIN_EFFECT else "; the stamp showed no effect at this sample size")
    )
    return 0


# --- self-check, without a model -----------------------------------------------------------------------------


def check_base(env: dict, work: Path) -> Path:
    """The copy of the plugin and the base project: no answers in them."""
    base = work / "base"
    assert PluginCopy.path != PLUGIN and not (PluginCopy.path / "evals").exists(), (
        "the plugin copy still has evals/"
    )
    assert (PLUGIN / "evals").exists() and (PluginCopy.path / "skills").exists(), (
        "plugin copy incomplete"
    )
    assert mem(env, work, "--help").returncode == 0, "the copy's bin/mem does not run"
    build_base(base)
    for rel in (
        ".memory",
        ".superpowers",
        "CLAUDE.md",
        "docs/superpowers/plans",
        "plugins/memory/evals",
    ):
        assert not (base / rel).exists(), f"{rel} reached the copy"
    assert str(Path.home()) not in Path(__file__).read_text(encoding="utf-8"), (
        "home path in the script"
    )
    for c in CANDIDATES:
        assert any(
            str(p.relative_to(base)).endswith(c["expect"])
            for p in base.rglob(posixpath.basename(c["expect"]))
        ), c["expect"]
    for c in MOVED:
        assert (base / c["moved"][0]).is_file(), c["moved"][0]
    assert not git(base, "status", "--porcelain").strip(), "copy is not clean"
    return base


def check_writer_cleanup(env: dict, work: Path, base: Path) -> Path:
    """A written copy keeps only its syntheses after the cleanup."""
    written = copy_tree(base, work / "written")
    run = mem(
        env,
        written,
        "project-synthesis",
        "add",
        "conventions",
        "Check conventions",
        "--paths",
        "scripts",
        "--body-file",
        "-",
        stdin="Scripts are run from the repository root.\n",
    )
    assert run.returncode == 0, run.stderr
    assert part_states(env, written) == [("p:conventions#check-conventions", "fresh")], part_states(
        env, written
    )
    (written / ".memory" / "memories").mkdir()
    (written / ".memory" / "memories" / "note.md").write_text("x", encoding="utf-8")
    (written / ".memory" / "stray.json").write_text("{}", encoding="utf-8")
    removed = strip_to_syntheses(written)
    assert removed == ["memories", "stray.json"], removed
    assert [p.name for p in (written / ".memory").iterdir()] == ["syntheses"], (
        "more than syntheses left"
    )
    assert strip_to_syntheses(written) == []
    assert part_states(env, written) == [("p:conventions#check-conventions", "fresh")], (
        "cleaning hurt the part"
    )
    return written


def check_stale_copies(env: dict, work: Path, written: Path) -> tuple[Path, Path, dict]:
    """S1 (parts as they are) reads as possibly stale; S2 (stamps rewritten) is fresh with the same bodies."""
    s1 = copy_tree(written, work / "stale1")
    add_own_part(env, s1)
    rename_files(s1)
    states = dict(part_states(env, s1))
    assert all(v == "changed" for v in states.values()) and len(states) == EXPECTED_PARTS, states
    shown = mem(env, s1, "show", "p:organization#" + next(iter(states)).split("#")[1]).stdout
    assert "possibly stale" in shown, shown
    s2 = copy_tree(s1, work / "stale2")
    before = {p.name: strip_stamps(p.read_text(encoding="utf-8")) for p in synthesis_files(s2)}
    rewrite_stamps(s2)
    check_s2(env, s2)
    assert before == {
        p.name: strip_stamps(p.read_text(encoding="utf-8")) for p in synthesis_files(s2)
    }, "bodies differ"
    own = (s2 / ".memory" / "syntheses" / "organization.md").read_text(encoding="utf-8")
    assert "session-env.sh" in own and "validate.py" in own, "the old names left the body"
    index = mem(env, s2, "session-index").stdout
    assert "Store:" not in index, f"a store count shows in the session index: {index!r}"
    assert "Project syntheses:" in index, index
    return s1, s2, states


def check_grading_and_stream(env: dict, work: Path) -> None:
    assert grade(MOVED[0], "S1", "El archivo es plugins/memory/hooks/session-setup.sh")
    assert not grade(MOVED[0], "S1", "plugins/memory/hooks/session-env.sh")
    assert grade(MOVED[1], "S2", "scripts/check_repo.py")
    stream = "\n".join(
        json.dumps(e)
        for e in [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "1",
                            "name": "Bash",
                            "input": {"command": "mem show p:organization#x"},
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "1", "name": "Bash", "input": {}},
                        {"type": "tool_use", "id": "2", "name": "Read", "input": {}},
                    ]
                },
            },
            {
                "type": "result",
                "result": "ok",
                "usage": {"input_tokens": 3, "cache_read_input_tokens": 10},
            },
        ]
    )
    parsed = parse_stream(stream)
    assert (parsed["calls"], parsed["tokens"], parsed["used"]) == (2, 13, True), parsed
    fail = session(Launch("/bin/false", "m", work / "x.json"), work, env, "p", timeout=30)
    assert fail["error"], "a failed process gave no error"
    assert (
        parse_stream(stream)["error"] is None
        and parse_stream(stream.split("\n")[0])["has_result"] is False
    )


def check_leftovers(env: dict, work: Path) -> None:
    projects = work / "projects"
    for name in (
        encode_cwd(work),
        encode_cwd(work / "sessions" / "ab-A-x-1"),
        encode_cwd(work) + "x",
        "other",
    ):
        (projects / name).mkdir(parents=True)
    assert encode_cwd(Path("/a/b.c/d_e")) == "-a-b-c-d-e"
    assert sorted(p.name for p in leftover_folders(projects, work)) == sorted([
        encode_cwd(work),
        encode_cwd(work / "sessions" / "ab-A-x-1"),
    ]), "wrong leftover folders"
    assert shutil.which("mem", path=env["PATH"]) is None, "an installed `mem` is still on PATH"


def check_plugin_copy_diff(work: Path) -> None:
    """A fresh plugin copy matches the plugin; a changed one is refused on resume."""
    assert plugin_diff(PLUGIN, PluginCopy.path) == [], "a fresh plugin copy differs"
    (PluginCopy.path / "bin" / "mem").write_bytes(
        (PluginCopy.path / "bin" / "mem").read_bytes() + b"#"
    )
    (PluginCopy.path / "extra.txt").write_text("x", encoding="utf-8")
    diff = plugin_diff(PLUGIN, PluginCopy.path)
    assert sorted(diff) == ["bin/mem differs", "extra.txt only in the copy"], diff
    try:
        make_env(work)
        raise AssertionError("a changed plugin copy was accepted on resume")
    except SystemExit as exc:
        assert "differs" in str(exc), exc


def check_written_state(work: Path) -> State:
    """A written copy is accepted only after the cleanup that --phase write records."""
    state = State(work / "synthetic")
    assert state.data["rows"] == []
    try:
        need_written(work, state)
        raise AssertionError("an unprocessed written copy was accepted")
    except SystemExit as exc:
        assert "was not cleaned" in str(exc), exc
    state.data["written_stripped"] = True
    assert need_written(work, state) == work / "written"
    return state


def synth(state: State, key: tuple[str, str], ok_count: int, n: int = 8, errors: int = 0) -> None:
    """Replaces the rows of one (phase, arm) with n synthetic rows, ok_count of them correct, the first `errors` failed."""
    phase, arm = key
    state.data["rows"] = [r for r in state.data["rows"] if (r["phase"], r["arm"]) != (phase, arm)]
    for i in range(n):
        row = {
            "phase": phase,
            "arm": arm,
            "case": "c",
            "run": i,
            "ok": i < ok_count,
            "calls": 3,
            "tokens": 100,
            "used": True,
        }
        state.data["rows"].append({**row, "error": "boom"} if i < errors else row)


def verdict(state: State, call) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = call(state)
    return code, out.getvalue()


def check_decisions(state: State) -> None:
    synth(state, ("stale", "S1"), 8)
    synth(state, ("stale", "S2"), 5, n=7)
    code, out = verdict(state, decide)
    assert code == 1 and "S2: 7 valid of 8 planned" in out and "VERDICT" not in out, out
    synth(state, ("stale", "S2"), 5, errors=1)
    assert verdict(state, decide_stale)[0] == 1, "an error row counted as valid"
    for s1_ok, s2_ok, text in (
        (5, 5, "does not protect the reader: do not merge"),
        (8, 5, "has an effect"),
        (7, 6, "showed no effect at this sample size"),
    ):
        synth(state, ("stale", "S1"), s1_ok)
        synth(state, ("stale", "S2"), s2_ok)
        code, out = verdict(state, decide)
        assert code == 0 and ("VERDICT: the stamp " + text) in out, out
        assert f"S1 correct of 8: {s1_ok}; S2 correct of 8: {s2_ok}" in out, out
    synth(state, ("ab", "A"), 4, 16)
    synth(state, ("ab", "B"), 4, 15)
    code, out = verdict(state, decide)
    assert code == 1 and "B: 15 valid of 16 planned" in out and "DECISION" not in out, out


def self_check(work: Path) -> None:
    env = make_env(work)
    base = check_base(env, work)
    written = check_writer_cleanup(env, work, base)
    s1, s2, states = check_stale_copies(env, work, written)
    check_grading_and_stream(env, work)
    check_leftovers(env, work)
    check_s1(env, s1)
    check_plugin_copy_diff(work)
    check_decisions(check_written_state(work))
    print("self-check passed")
    print(
        "  plugin copy: no evals/, bin/mem runs; writer cleanup keeps only syntheses/; failed session -> error row; "
        "leftover cleanup matches only the work folder's own prefix"
    )
    print("  copy: no .memory, .superpowers, CLAUDE.md, plans, evals; clean tree")
    print(f"  S1: {sorted(states.items())}")
    print(f"  S2: {part_states(env, s2)}, bodies byte-equal")
    print("  session-index without a store option: no `Store:` count; no installed `mem` on PATH")
    print(
        "  resume: a changed plugin copy and an unprocessed written copy are refused; decide: missing rows -> no "
        "action and exit 1; stale-only verdict by the three rules"
    )


def encode_cwd(path: Path) -> str:
    """How Claude Code names a project folder: every character that is not a letter or a digit becomes `-`."""
    return "".join(c if c.isalnum() else "-" for c in str(path))


def leftover_folders(projects: Path, work: Path) -> list[Path]:
    """Auto-memory folders of sessions that ran inside the work folder; no other folder is ever returned."""
    prefix = encode_cwd(work)
    if not projects.is_dir():
        return []
    return [
        p
        for p in projects.iterdir()
        if p.is_dir() and (p.name == prefix or p.name.startswith(prefix + "-"))
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--claude", help="path to the claude binary")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument(
        "--phase",
        choices=["pilot", "write", "ab", "stale", "decide", "decide-stale", "all", "clean"],
        default="all",
    )
    parser.add_argument("--pilot", action="store_true", help="same as --phase pilot")
    parser.add_argument(
        "--work", type=Path, help="work folder of an earlier phase (resume); default: a new one"
    )
    parser.add_argument(
        "--runs",
        type=int,
        help="per case and arm (pilot 2, ab and stale 4; decide needs the design's 4)",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="candidate name; pilot: any, ab: the chosen, stale: the moved",
    )
    parser.add_argument(
        "--arm", action="append", default=[], help="ab only: A or B (e.g. to rerun B)"
    )
    parser.add_argument("--jobs", type=int, default=4, help="parallel sessions")
    parser.add_argument(
        "--force", action="store_true", help="rerun sessions that already have a row"
    )
    parser.add_argument("--self-check", action="store_true")
    return parser


def run_phases(args, work: Path, env: dict, state: State) -> bool:
    """Runs the requested phases; False when the pilot stopped the run."""
    phases = {"pilot": phase_pilot, "write": phase_write, "ab": phase_ab, "stale": phase_stale}
    for name in ["pilot", "write", "ab", "stale"] if args.phase == "all" else [args.phase]:
        if name not in phases:
            continue
        phases[name](args, work, env, state)
        state.save()
        if name == "pilot" and state.data.get("pilot", {}).get("stopped"):
            return False
    return True


def run_trials(args, work: Path) -> int:
    env = make_env(work)
    state = State(work)
    print(f"work folder: {work}\nstate file:  {state.path}", flush=True)
    if not run_phases(args, work, env, state):
        return 1
    if args.phase == "decide-stale":
        return decide_stale(state)
    if args.phase in {"all", "decide"}:
        return decide(state)
    return 0


def execute(parser: argparse.ArgumentParser, args, work: Path) -> int:
    if args.self_check:
        self_check(work)
        return 0
    if args.phase == "clean":
        if not args.work:
            parser.error("--phase clean needs --work")
        return 0
    if not args.claude:
        parser.error("--claude is required")
    return run_trials(args, work)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.pilot:
        args.phase = "pilot"
    for name in args.case:
        if name not in BY_NAME:
            parser.error(f"unknown case {name!r}; candidates: {', '.join(BY_NAME)}")
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="mem-syn-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        return execute(parser, args, work)
    finally:
        for leftover in leftover_folders(Path.home() / ".claude" / "projects", work):
            shutil.rmtree(leftover, ignore_errors=True)
        if args.self_check or args.phase == "clean":
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
