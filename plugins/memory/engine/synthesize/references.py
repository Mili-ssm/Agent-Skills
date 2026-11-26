"""The backfill of inline references for existing syntheses (`mem-synthesize --backfill`).

A cheap session reads one synthesis's units and its source notes and answers `<part> | <number> | <path or none>`
lines; this module selects the parts, builds the session's input and command, parses the answer and keeps the done
list. The session never writes: Python turns its lines into `mem synthesis refs` proposals, so a wrong answer can be
a wrong reference, never a changed sentence."""

from __future__ import annotations

import json
import os
import re
import time
from typing import TYPE_CHECKING, NamedTuple, TypedDict, Unpack

from core import headless
from notes import syntheses

from synthesize import pipeline as sp

if TYPE_CHECKING:
    from pathlib import Path

ANSWER_LINE = re.compile(
    r"^\s*`?\s*(?P<part>[^|\s`]+)\s*\|\s*(?P<n>\d+)\s*\|\s*`?(?P<target>[^|`\s]+)`?\s*$"
)
FENCE_LINE = re.compile(r"^\s*(```|~~~)")
TIMEOUT = 900


def select(path: Path, done: dict[str, str]) -> list[dict]:
    """The parts of the synthesis file that the backfill sends: at least one note source, a unit without
    reference, and no done entry equal to the part's fingerprint (`done`: section handle -> fingerprint).

    Each: `handle`, `units` (all its units), `bare` (those without reference), `sources` (note targets, as on its
    `Sources:` line), `fingerprint`."""
    chosen = []
    for section in syntheses.load_one(path).parts:
        sources = [t for t in section.sources if syntheses._is_ref(t)]
        found, _ = syntheses.units(section.text)
        bare = [u for u in found if not u.refs]
        fingerprint = syntheses.fingerprint(section.text)
        if sources and bare and done.get(section.handle) != fingerprint:
            chosen.append({
                "handle": section.handle,
                "units": found,
                "bare": bare,
                "sources": sources,
                "fingerprint": fingerprint,
            })
    return chosen


def write_input(path: Path, parts: list[dict], work: Path) -> tuple[Path, Path]:
    """The units file restricted to `parts`, and the `target -> absolute path` list of their source notes."""
    keep = {p["handle"] for p in parts}
    lines, inside = [], False
    for line in sp.units_text(path).splitlines():
        if line.startswith("## "):
            inside = line[3:] in keep
        if inside:
            lines.append(line)
    units, notes = work / "units-backfill.md", work / "notes-backfill.md"
    units.write_text("\n".join(lines) + "\n", encoding="utf-8")
    seen = dict.fromkeys(t for p in parts for t in p["sources"])
    notes.write_text(
        "".join(f"{t} -> {syntheses._resolved(path.parent, t)}\n" for t in seen), encoding="utf-8"
    )
    return units, notes


class SessionOptions(TypedDict):
    settings: Path
    max_budget: float | None


def session_cmd(
    claude: str, prompt: str, work: Path, store: Path, **options: Unpack[SessionOptions]
) -> list[str]:
    """Only Read exists (`--tools`, no MCP server) and the rules allow it inside the work folder and the store
    (`//` is an absolute path in a permission rule): no shell, no web, no write."""
    return headless.command(
        headless.Session(
            claude=claude,
            prompt=prompt,
            model="haiku",
            effort=sp.CHEAP,
            settings=options["settings"],
            tools=("Read",),
            # --tools says which tools exist; a headless session still needs the permission to call them
            allowed=(f"Read(/{work}/**)", f"Read(/{store}/**)"),
            max_budget=options["max_budget"],
        )
    )


def run_session(cmd: list[str], work: Path, env: dict, log: Path) -> dict:
    start = time.monotonic()
    raw = headless.run_raw(cmd, cwd=work, env=env, timeout=TIMEOUT).stdout
    log.write_text(raw, encoding="utf-8")
    result = sp.parse(raw)
    result["wall"] = time.monotonic() - start
    return result


class Answer(NamedTuple):
    found: list[tuple[str, int, str]]  # (part, number, target or "none") in order without repeats
    unreadable: int
    repeated: int  # readable lines dropped as repeats: found + unreadable + repeated = the non-blank, non-fence lines
    nothing: bool  # the answer is exactly the word `nothing`: an explicit empty result


def parse_answer(answer: str) -> Answer:
    """Blank lines and code fence lines are ignored; `None`/`NONE` mean `none`; backticks, angle brackets and a
    trailing full stop around a target are stripped."""
    if re.fullmatch(r"\s*nothing\.?\s*", answer, re.IGNORECASE):
        return Answer([], 0, 0, True)
    found, unreadable, lines = [], 0, 0
    for line in answer.splitlines():
        if not line.strip() or FENCE_LINE.match(line):
            continue
        lines += 1
        m = ANSWER_LINE.match(line)
        if not m:
            unreadable += 1
            continue
        target = m["target"].strip("`<>").removesuffix(".").strip("`<>")
        if target.lower() == "none":
            target = "none"
        found.append((m["part"].removeprefix("s:").split("#")[-1], int(m["n"]), target))
    unique = list(dict.fromkeys(found))
    return Answer(unique, unreadable, len(found) - len(unique), False)


def load_done(path: Path) -> tuple[dict, bool]:
    """(store -> synthesis handle -> section handle -> fingerprint, readable). A missing file is `({}, True)`; a file
    that exists but is not that shape is `({}, False)`, so the caller can refuse to go on."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, True
    except (OSError, ValueError):
        return {}, False
    ok = isinstance(data, dict) and all(
        isinstance(syns, dict)
        and all(
            isinstance(parts, dict) and all(isinstance(fp, str) for fp in parts.values())
            for parts in syns.values()
        )
        for syns in data.values()
    )
    return (data, True) if ok else ({}, False)


def save_done(path: Path, store: str, handle: str, entries: dict[str, str]) -> None:
    """Merge one synthesis's part entries into the file as it is now, so a run on another synthesis keeps its own."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data, ok = load_done(path)
    if not ok:
        raise ValueError(f"{path} is not a readable done list")
    data.setdefault(store, {}).setdefault(handle, {}).update(entries)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
