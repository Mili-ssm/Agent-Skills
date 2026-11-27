"""One Codex session of a background pass, in the shape the builders already read (ADR 0037).

`ask` runs a `headless.Session` through `codex exec` and returns a dict with the keys of `synthesize.pipeline.parse`
that the builders use (`has_result`, `error`, `answer`, `cost`), plus `tokens` and `raw`. The token cap is the budget
of a Codex pass (Codex reports tokens, not money); `refusal` is the message of a pass that stays on Claude.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from core import runner

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from core import headless

DEFAULT_TOKEN_CAP = (
    500_000  # about 44k input tokens of Codex's own prompt per call, observed 2026-11-27
)
NO_CODEX = "no codex binary (MEM_CODEX, PATH or the VS Code extension)"
PRIVATE_MODE = runner.PRIVATE_MODE
REFUSED_EXIT = 2


def token_cap(env: Mapping[str, str] | None = None) -> int:
    """`MEM_CODEX_TOKENS` when it is a positive integer, else `DEFAULT_TOKEN_CAP`."""
    env = os.environ if env is None else env
    try:
        value = int(env.get("MEM_CODEX_TOKENS", ""))
    except ValueError:
        return DEFAULT_TOKEN_CAP
    return value if value > 0 else DEFAULT_TOKEN_CAP


def over_cap(tokens: int) -> bool:
    return tokens >= token_cap()


def reason(done: dict) -> str:
    """`: <why>` for a failed Codex session (exit code, timeout, stderr tail), else ''; a Claude dict has no `failure`."""
    return f": {done['failure']}" if done.get("failure") else ""


def refusal(pass_name: str) -> str:
    return (
        f"{pass_name}: runs on Claude only (ADR 0037: Codex cannot remove the shell from this step); "
        "set runner=claude or pass --runner claude"
    )


def refuse_codex(pass_name: str, explicit: str | None = None) -> int | None:
    """For a pass that stays on Claude. An `explicit` request for `codex` (the pass's own `--runner`) prints
    `refusal` to stderr and returns the exit code to end with; an explicit `claude` ends the question. A `codex` that only comes from a default
    (`MEM_RUNNER`, the config file, `MEM_RUNNER_OPTION`) never disables the pass: one line on stderr says the
    default is ignored, the pass runs on Claude, and None is returned. A malformed setting is ignored silently."""
    if explicit == "codex":
        print(refusal(pass_name), file=sys.stderr)
        return REFUSED_EXIT
    if explicit == "claude":
        return None
    try:
        chosen = runner.resolve_runner(None)
    except ValueError:
        return None
    if chosen == "codex":
        print(
            f"{pass_name}: the default runner codex is ignored for this pass; it runs on Claude (ADR 0037)",
            file=sys.stderr,
        )
    return None


def ask(session: headless.Session, work: Path, *, writes: bool, timeout: float) -> dict:
    """Runs `session` with Codex in `work`, which is also its sandbox root and holds its HOME. `writes`: the step
    writes a file there (`workspace-write`), else the sandbox is read-only. `FileNotFoundError` when no binary."""
    codex = runner.find_codex()
    if codex is None:
        raise FileNotFoundError(NO_CODEX)
    for sub in ("home", "xdg"):
        (work / sub).mkdir(mode=PRIVATE_MODE, exist_ok=True)
    cmd = runner.codex_command(session, codex, work, writes=writes)
    try:
        raw = runner.run_codex(
            cmd, session.prompt, cwd=work, env=runner.codex_env(work), timeout=timeout
        )
    finally:
        runner.sync_auth(work)  # a refreshed token must not be lost, success or not
    out = runner.parse_codex(raw.stdout, raw.returncode, raw.stderr, raw.timed_out)
    return {
        "has_result": out.has_result,
        "error": not out.has_result,
        "answer": out.text,
        "cost": 0.0,
        "tokens": out.tokens,
        "raw": raw.stdout,
        "failure": out.error,
    }
