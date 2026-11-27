"""The runner of a background pass: `claude` or `codex` (ADR 0037).

Resolution, the Codex binary, its argv and environment, its JSON-lines output, and one normalized `Outcome` for
both runners. Standard library plus `core`; builders do not use it yet (plan task 3).
"""

from __future__ import annotations

import codecs
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from core import config, headless

if TYPE_CHECKING:
    from collections.abc import Mapping

RUNNERS = ("claude", "codex")

# (claude tier, effort) -> (codex model, codex effort). A copy of what `scripts/port.py` derives from
# `shared/models.toml` (the installed plugin has no `shared/`); `scripts/tests/test_runner_models.py` keeps them equal.
CODEX_MODELS: dict[tuple[str, str], tuple[str, str]] = {
    ("haiku", "low"): ("gpt-6-luna", "low"),
    ("haiku", "medium"): ("gpt-6-luna", "low"),
    ("haiku", "high"): ("gpt-6-luna", "medium"),
    ("sonnet", "low"): ("gpt-6-luna", "high"),
    ("sonnet", "medium"): ("gpt-6.1-terra", "low"),
    ("sonnet", "high"): ("gpt-6.1-terra", "medium"),
    ("opus", "low"): ("gpt-6.2-sol", "low"),
    ("opus", "medium"): ("gpt-6.2-sol", "low"),
    ("opus", "high"): ("gpt-6.2-sol", "medium"),
}


def _choice(value: str, source: str) -> str:
    if value not in RUNNERS:
        raise ValueError(f"{source}: runner {value!r} is not one of {', '.join(RUNNERS)}")
    return value


def resolve_runner(flag: str | None, env: Mapping[str, str] | None = None) -> str:
    """The first set of `--runner`, `MEM_RUNNER`, the `runner` config file (first line), `MEM_RUNNER_OPTION`
    (the plugin setting), then `claude`; an empty value counts as unset, an invalid one raises naming its source."""
    env = os.environ if env is None else env
    lines = config.config_lines(env, "runner")
    sources = (
        ("--runner", flag or ""),
        ("MEM_RUNNER", env.get("MEM_RUNNER", "")),
        ("the runner config file", lines[0].strip() if lines else ""),
        ("MEM_RUNNER_OPTION", env.get("MEM_RUNNER_OPTION", "")),
    )
    for source, value in sources:
        if value.strip():
            return _choice(value.strip(), source)
    return "claude"


def _extension_version(binary: Path) -> tuple[int, ...]:
    """`openai.chatgpt-26.1120.41243-linux-x64` -> (26, 1120, 41243)."""
    found = re.search(r"openai\.chatgpt-([\d.]+)", binary.parent.parent.parent.name)
    return tuple(int(n) for n in found.group(1).split(".") if n) if found else ()


def find_codex(env: Mapping[str, str] | None = None) -> str | None:
    """`MEM_CODEX`, then `codex` on PATH, then the newest VS Code extension's binary. Found at run time, never stored."""
    env = os.environ if env is None else env
    if env.get("MEM_CODEX"):
        return env["MEM_CODEX"]
    on_path = shutil.which("codex", path=env.get("PATH"))
    if on_path:
        return on_path
    home = Path(env["HOME"]) if env.get("HOME") else Path.home()
    found = [
        p
        for p in home.glob(".vscode*/extensions/openai.chatgpt-*/bin/*/codex")
        if p.is_file() and os.access(p, os.X_OK)
    ]
    return str(max(found, key=_extension_version)) if found else None


def codex_command(
    session: headless.Session, codex: str, run_dir: Path, *, writes: bool
) -> list[str]:
    """The argv of a Codex session, prompt on stdin (`-`).

    The Session's `tools`, `allowed`, `disallowed`, `agent`, `plugin_dir`, `max_budget` and `settings` have no Codex
    equivalent and are ignored: the sandbox (`read-only` or `workspace-write` limited to `run_dir`) and the
    environment from `codex_env` are the isolation, and the token cap is enforced by the caller from `Outcome.tokens`.
    """
    model, effort = CODEX_MODELS[session.model, session.effort or "medium"]
    return [
        codex,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--disable",
        "hooks",
        "--skip-git-repo-check",
        "-s",
        "workspace-write" if writes else "read-only",
        "-C",
        str(run_dir),
        "-m",
        model,
        "-c",
        f"model_reasoning_effort={effort}",
        "-",
    ]


def codex_env(run_dir: Path) -> dict[str, str]:
    """`session_env()` with HOME and the XDG folders inside `run_dir`, and `CODEX_HOME` kept real so auth works.

    Codex's model shell is a login shell that re-sources `~/.profile`, which would put `mem` back on PATH
    (observed 2026-11-27); with HOME in the run folder it finds nothing."""
    env = headless.session_env()
    real_home = Path(os.environ.get("HOME") or Path.home())
    env["CODEX_HOME"] = os.environ.get("CODEX_HOME") or str(real_home / ".codex")
    env["HOME"] = str(run_dir / "home")
    for var, sub in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        env[var] = str(run_dir / "xdg" / sub)
    return env


class CodexRaw(NamedTuple):
    stdout: str
    timed_out: bool
    returncode: int | None


def run_codex(
    cmd: list[str], prompt: str, *, cwd: Path, env: dict[str, str], timeout: float
) -> CodexRaw:
    """Run a Codex session with the prompt on stdin (closed after it); a timeout returns the partial stdout with
    `timed_out=True` and no return code, an `OSError` propagates."""
    try:
        done = subprocess.run(
            cmd,
            check=False,
            cwd=cwd,
            env=env,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout
        if isinstance(partial, bytes):
            partial = codecs.getincrementaldecoder("utf-8")(errors="replace").decode(
                partial, final=False
            )
        return CodexRaw(partial or "", True, None)
    return CodexRaw(done.stdout, False, done.returncode)


@dataclass(frozen=True)
class Outcome:
    """What a builder needs from one session, whichever runner ran it.

    `has_result`: the session ended with a final answer (Claude: a `result` event; Codex: also exit 0).
    `text`: that answer. `tokens`: billed input plus output tokens (the cap of a Codex pass). `cost_usd`: Claude's
    reported cost, 0.0 for Codex. `commands`: (command, exit code or None) the session ran, Codex only (Claude's
    tool calls are tallied by the synthesizer). `error`: why it failed, empty when it did not."""

    has_result: bool
    text: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    commands: list[tuple[str, int | None]] = field(default_factory=list)
    error: str = ""


def _events(stdout: str) -> list[dict[str, Any]]:
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _count(usage: Any, *names: str) -> int:
    if not isinstance(usage, dict):
        return 0
    return sum(v for n in names if isinstance(v := usage.get(n), int))


def claude_outcome(stdout: str) -> Outcome:
    """Normalize a `stream-json` session: the last `result` event gives text, cost, usage and `is_error`."""
    final = next((e for e in reversed(_events(stdout)) if e.get("type") == "result"), None)
    if final is None:
        return Outcome(False, error="no result event")
    text = final.get("result") or ""
    failed = bool(final.get("is_error"))
    return Outcome(
        True,
        text=text,
        tokens=_count(
            final.get("usage"), "input_tokens", "cache_creation_input_tokens", "output_tokens"
        ),
        cost_usd=float(final.get("total_cost_usd") or 0.0),
        error=(text or "the session reported an error") if failed else "",
    )


def _error_message(event: dict[str, Any]) -> str:
    err = event.get("error")
    message = err.get("message") if isinstance(err, dict) else err
    return str(message or event.get("message") or event.get("type"))


def _item(event: dict[str, Any]) -> dict[str, Any]:
    item = event.get("item")
    return item if isinstance(item, dict) else {}


@dataclass
class _Tally:
    text: str = ""
    tokens: int = 0
    completed: bool = False
    commands: list[tuple[str, int | None]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        item = _item(event)
        if kind == "item.completed":
            self._item(item)
        elif kind == "turn.completed":
            self.completed = True
            self.tokens += _count(event.get("usage"), "input_tokens", "output_tokens")
        elif kind in {"turn.failed", "error"}:
            self.errors.append(_error_message(event))

    def _item(self, item: dict[str, Any]) -> None:
        if item.get("type") == "agent_message":
            self.text = item.get("text") or ""
        elif item.get("type") == "command_execution":
            self.commands.append((item.get("command") or "", item.get("exit_code")))


def parse_codex(stdout: str, returncode: int | None) -> Outcome:
    """Normalize `codex exec --json` events. `has_result` needs a `turn.completed`, an agent message and exit 0;
    `tokens` sums `input_tokens` and `output_tokens` (cached and reasoning tokens are parts of those)."""
    tally = _Tally()
    for event in _events(stdout):
        tally.add(event)
    has_result = tally.completed and bool(tally.text) and returncode == 0
    error = "; ".join(tally.errors)
    if not has_result and not error:
        error = "no final message" if tally.completed else "the session did not complete"
        if returncode not in {0, None}:
            error += f" (exit {returncode})"
    return Outcome(has_result, tally.text, tally.tokens, 0.0, tally.commands, error)
