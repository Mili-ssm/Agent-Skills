"""Shared pieces of `mem-synthesize`: constants, the store and session environment, the table helpers."""

from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING

import config
import jobs

from synthesize import pipeline as sp

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


AGENT = "memory:memory-synthesizer"


ESTIMATE_PER_TOPIC = (
    0.5  # USD: 0.25 measured at medium effort, doubled for the owner's high setting
)


TOPIC_LINE = re.compile(r"^  (\S+)  (\d+) notes\s*$")


ATTACH_LINE = re.compile(r"^(knowledge/\S+\.md)\t(s:[^\s#]+#[^\s#]+)\s*$")


ESTIMATE_PER_BACKFILL = (
    0.05  # USD per synthesis session: measured 0.035 to 0.053 (trial of 2026-11-18)
)


FAILED_WORDS_PER_FAKE_ROW = (
    2  # the self-check's fake claude: "failed" appears in the status and in the table row
)


BACKFILL_HEADER = (
    "synthesis",
    "parts",
    "units",
    "proposed",
    "applied",
    "refused",
    "none",
    "unreadable",
    "repeated",
    "mem check",
    "cost USD",
    "status",
)


HEADER = (
    "topic",
    "parts",
    "attached",
    "fixed",
    "deleted",
    "reverted",
    "refs",
    "refused",
    "none",
    "mem check",
    "cost USD",
    "status",
)


def default_store() -> Path | None:
    """The store `mem` falls back to: MEM_STORE, the config file, else the marked default store."""
    return config.resolve_store(None, os.environ)


state_dir = jobs.state_dir


def session_env(store: Path) -> dict:
    """The environment of the headless sessions and of the `mem` calls: aimed at `store` only; the installed
    plugin's `bin/` is dropped from PATH so the sessions run this plugin's `mem`."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"MEM_STORE", "MEM_MEMORIES", "MEM_PROJECT"}
        and not k.startswith("CLAUDE_PLUGIN_OPTION_")
    }
    env["PATH"] = os.pathsep.join(
        p for p in env.get("PATH", "").split(os.pathsep) if "/plugins/cache/" not in p
    )
    env["MEM_STORE"] = str(store)
    return env


def topics_without_synthesis(curate_output: str) -> list[str]:
    """Topic ids listed under "no synthesis" in the output of `mem curate --notes`."""
    topics, inside = [], False
    for line in curate_output.splitlines():
        if line and not line.startswith(" "):
            inside = "no synthesis" in line
        elif inside and (found := TOPIC_LINE.match(line)):
            topics.append(found.group(1))
    return topics


def attach_lines(answer: str) -> list[tuple[str, str]]:
    return [(m[1], m[2]) for m in map(ATTACH_LINE.match, answer.splitlines()) if m]


def part_of(note: Path) -> str | None:
    head = re.match(r"---\n(.*?)\n---\n", note.read_text(encoding="utf-8"), re.DOTALL)
    found = re.search(r'^part_of: "?([^"\n]+)"?$', head.group(1), re.MULTILINE) if head else None
    return found.group(1) if found else None


def history_commit(store: Path, env: dict, message: str, log) -> None:
    if not (store / ".git").exists():
        return
    done = sp.mem(store, env, "history", "commit", "-m", message)
    log(
        f"history commit ({message}): exit {done.returncode} {done.stdout.strip()} {done.stderr.strip()}"
    )


def _file_logger(log_file: Path) -> Callable[[str], None]:
    def log(text: str) -> None:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    return log


def _aligned(lines: list[tuple]) -> str:
    """`lines` as columns padded to the widest cell; the first line is the header."""
    widths = [max(len(str(line[i])) for line in lines) for i in range(len(lines[0]))]
    return "\n".join(
        "  ".join(str(c).ljust(w) for c, w in zip(line, widths, strict=True)).rstrip()
        for line in lines
    )


def count_parts(synthesis: Path) -> int:
    return len(re.findall(r"^## (?!Summary$)", synthesis.read_text(encoding="utf-8"), re.MULTILINE))


def say(text: str) -> None:
    print(text, flush=True)
