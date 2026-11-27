"""The spec and the runner of `claude -p` sessions, shared by every builder that starts one.

Standard library only; it imports no plugin module."""

from __future__ import annotations

import codecs
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

SESSION_VARS = (
    "CLAUDE_ENV_FILE",
    "CLAUDE_PID",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
)


@dataclass(frozen=True)
class Session:
    claude: str
    prompt: str
    model: str
    settings: Path
    effort: str | None = None
    plugin_dir: Path | None = None
    tools: tuple[str, ...] | None = None
    allowed: tuple[str, ...] = ()
    disallowed: tuple[str, ...] = ()
    max_budget: float | None = None
    agent: str | None = None


class Raw(NamedTuple):
    stdout: str
    timed_out: bool


def _flag(name: str, value: object | None) -> list[str]:
    return [] if value is None else [name, str(value)]


def _values(name: str, values: tuple[str, ...]) -> list[str]:
    return [name, *values] if values else []


def command(session: Session) -> list[str]:
    """The argv of a session. The CLI reads flags by name, so the order is canonical, not any builder's old one."""
    tools = None if session.tools is None else ",".join(session.tools)
    budget = None if session.max_budget is None else f"{session.max_budget:.4f}"
    return [
        session.claude,
        "-p",
        session.prompt,
        "--model",
        session.model,
        *_flag("--effort", session.effort),
        *_flag("--plugin-dir", session.plugin_dir),
        "--settings",
        str(session.settings),
        "--setting-sources",
        "project",
        *_flag("--tools", tools),
        "--strict-mcp-config",
        *_values("--allowedTools", session.allowed),
        *_values("--disallowedTools", session.disallowed),
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        *_flag("--max-budget-usd", budget),
        *_flag("--agent", session.agent),
    ]


def run_raw(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    errors: str | None = None,
) -> Raw:
    """Run a session; a timeout returns the partial stdout with `timed_out=True`, an `OSError` propagates."""
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    if errors is not None:
        kwargs["errors"] = errors
    try:
        done = subprocess.run(cmd, check=False, **kwargs)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout
        if isinstance(partial, bytes):
            # A cut inside a multibyte character drops that fragment only; other invalid bytes keep `errors`.
            decoder = codecs.getincrementaldecoder("utf-8")(errors=errors or "strict")
            partial = decoder.decode(partial, final=False)
        return Raw(partial or "", True)
    return Raw(done.stdout, False)


def has_mem(folder: str) -> bool:
    try:
        return os.access(Path(folder) / "mem", os.X_OK) and (Path(folder) / "mem").is_file()
    except OSError:
        return False


def session_env() -> dict[str, str]:
    """The environment of every model session: no `MEM_*`, no `CLAUDE_PLUGIN_*`, no session variable of the process
    that started this one, and a PATH without any folder that holds `mem`."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("MEM_", "CLAUDE_PLUGIN")) and k not in SESSION_VARS
    }
    env["PATH"] = os.pathsep.join(
        p for p in env.get("PATH", "").split(os.pathsep) if p and not has_mem(p)
    )
    return env
