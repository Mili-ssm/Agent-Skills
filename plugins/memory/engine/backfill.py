"""The backfill of inline references for existing syntheses (`mem-synthesize --backfill`).

A cheap session reads one synthesis's units and its source notes and answers `<part> | <number> | <path or none>`
lines; this module selects the parts, builds the session's input and command, parses the answer and keeps the done
list. The session never writes: Python turns its lines into `mem synthesis refs` proposals, so a wrong answer can be
a wrong reference, never a changed sentence."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import synth_pipeline as sp

ANSWER_LINE = re.compile(r"^\s*`?\s*(?P<part>[^|\s`]+)\s*\|\s*(?P<n>\d+)\s*\|\s*`?(?P<target>[^|`\s]+)`?\s*$")
FENCE_LINE = re.compile(r"^\s*(```|~~~)")
TIMEOUT = 900


def select(path: Path, done: dict[str, str]) -> list[dict]:
    """The parts of the synthesis file that the backfill sends: at least one note source, a unit without
    reference, and no done entry equal to the part's fingerprint (`done`: section handle -> fingerprint).

    Each: `handle`, `units` (all its units), `bare` (those without reference), `sources` (note targets, as on its
    `Sources:` line), `fingerprint`."""
    import syntheses
    chosen = []
    for section in syntheses.load_one(path).parts:
        sources = [t for t in section.sources if syntheses._is_ref(t)]
        found, _ = syntheses.units(section.text)
        bare = [u for u in found if not u.refs]
        fingerprint = syntheses.fingerprint(section.text)
        if sources and bare and done.get(section.handle) != fingerprint:
            chosen.append(dict(handle=section.handle, units=found, bare=bare, sources=sources, fingerprint=fingerprint))
    return chosen


def write_input(path: Path, parts: list[dict], work: Path) -> tuple[Path, Path]:
    """The units file restricted to `parts`, and the `target -> absolute path` list of their source notes."""
    import syntheses
    keep = {p["handle"] for p in parts}
    lines, inside = [], False
    for line in sp.units_text(path).splitlines():
        if line.startswith("## "):
            inside = line[3:] in keep
        if inside:
            lines.append(line)
    units, notes = work / "units-backfill.md", work / "notes-backfill.md"
    units.write_text("\n".join(lines) + "\n")
    seen = dict.fromkeys(t for p in parts for t in p["sources"])
    notes.write_text("".join(f"{t} -> {syntheses._resolved(path.parent, t)}\n" for t in seen))
    return units, notes


def session_cmd(claude: str, prompt: str, work: Path, store: Path, settings: Path, max_budget: float | None) -> list[str]:
    """Only Read exists (`--tools`, no MCP server) and the rules allow it inside the work folder and the store
    (`//` is an absolute path in a permission rule): no shell, no web, no write."""
    cmd = [claude, "-p", prompt, "--model", "haiku", "--effort", sp.CHEAP, "--settings", str(settings),
           "--setting-sources", "project", "--tools", "Read", "--strict-mcp-config",
           # --tools says which tools exist; a headless session still needs the permission to call them
           "--allowedTools", f"Read(/{work}/**)", f"Read(/{store}/**)",
           "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    if max_budget is not None:
        cmd += ["--max-budget-usd", f"{max_budget:.4f}"]
    return cmd


def run_session(cmd: list[str], work: Path, env: dict, log: Path) -> dict:
    start = time.monotonic()
    try:
        raw = subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=TIMEOUT).stdout
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    log.write_text(raw)
    result = sp.parse(raw)
    result["wall"] = time.monotonic() - start
    return result


def parse_answer(answer: str) -> tuple[list[tuple[str, int, str]], int]:
    """(`(part, number, target or "none")` in order without repeats, count of unreadable lines). Blank lines and
    code fence lines are ignored."""
    found, unreadable = [], 0
    for line in answer.splitlines():
        if not line.strip() or FENCE_LINE.match(line):
            continue
        m = ANSWER_LINE.match(line)
        if not m:
            unreadable += 1
            continue
        found.append((m["part"].removeprefix("s:").split("#")[-1], int(m["n"]), m["target"]))
    return list(dict.fromkeys(found)), unreadable


def load_done(path: Path) -> dict:
    """Store -> synthesis handle -> section handle -> fingerprint; empty when the file is missing or unreadable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_done(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)
