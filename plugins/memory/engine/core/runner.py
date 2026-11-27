"""The runner of a background pass: `claude` or `codex` (ADR 0037).

Resolution, the Codex binary, its argv and environment, its JSON-lines output, and one normalized `Outcome` for
both runners. Standard library plus `core`.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from core import config, headless

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

RUNNERS = ("claude", "codex")
PRIVATE_MODE = 0o700

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


def add_flag(parser: argparse.ArgumentParser) -> None:
    """`--runner` for a pass command; `pin_flag(args.runner)` applies it."""
    parser.add_argument(
        "--runner",
        choices=RUNNERS,
        help="claude or codex; outranks MEM_RUNNER, the runner config file and the plugin option (default claude)",
    )


def pin_flag(flag: str | None) -> None:
    """Make `--runner` outrank every other source for the rest of the process: `resolve_runner` reads `MEM_RUNNER`
    right after the flag, so setting it once at the entry reaches every call site."""
    if flag:
        os.environ["MEM_RUNNER"] = flag


def _extension_version(binary: Path) -> tuple[int, ...]:
    """`openai.chatgpt-26.1120.41243-linux-x64` -> (26, 1120, 41243)."""
    found = re.search(r"openai\.chatgpt-([\d.]+)", binary.parent.parent.parent.name)
    return tuple(int(n) for n in found.group(1).split(".") if n) if found else ()


def find_codex(env: Mapping[str, str] | None = None) -> str | None:
    """`MEM_CODEX` (when it is an executable file), then `codex` on PATH, then the newest VS Code extension's binary.
    Found at run time, never stored; a `MEM_CODEX` that is missing or not executable falls through."""
    env = os.environ if env is None else env
    chosen = env.get("MEM_CODEX")
    if chosen and Path(chosen).is_file() and os.access(chosen, os.X_OK):
        return chosen
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


def codex_model(session: headless.Session) -> tuple[str, str]:
    """The Codex (model, effort) of a session; no effort counts as `medium`. `ValueError` names an unmapped pair."""
    pair = (session.model, session.effort or "medium")
    try:
        return CODEX_MODELS[pair]
    except KeyError:
        raise ValueError(f"no Codex model for (model, effort) = {pair!r}") from None


def codex_command(
    session: headless.Session, codex: str, run_dir: Path, *, writes: bool
) -> list[str]:
    """The argv of a Codex session, prompt on stdin (`-`).

    The Session's `tools`, `allowed`, `disallowed`, `agent`, `plugin_dir`, `max_budget` and `settings` have no Codex
    equivalent and are ignored: the sandbox (`read-only` or `workspace-write` limited to `run_dir`) and the
    environment from `codex_env` are the isolation, and the token cap is enforced by the caller from `Outcome.tokens`.
    """
    model, effort = codex_model(session)
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


def _real_codex_home() -> Path:
    return Path(
        os.environ.get("CODEX_HOME") or Path(os.environ.get("HOME") or Path.home()) / ".codex"
    )


def _tokens(auth: object) -> dict:
    """The `tokens` object of a parsed `auth.json`, or `{}` for any other shape."""
    tokens = auth.get("tokens") if isinstance(auth, dict) else None
    return tokens if isinstance(tokens, dict) else {}


def _same_account(content: str, real: Path) -> bool:
    """The per-run file is a refresh of the real login: same `tokens.account_id`, non-empty tokens. The run folder
    is the sandbox's writable root, so a model could plant any file there; this keeps it from logging the owner
    out or swapping in another account. No real file means no login to refresh: `OSError`, so no sync. Raises
    `ValueError` or `OSError` on unreadable input."""
    fresh_tokens = _tokens(json.loads(content))
    real_tokens = _tokens(json.loads(real.read_text(encoding="utf-8")))
    return bool(
        real_tokens.get("account_id")
        and fresh_tokens.get("account_id") == real_tokens.get("account_id")
        and fresh_tokens.get("access_token")
        and fresh_tokens.get("refresh_token")
    )


def sync_auth(run_dir: Path) -> bool:
    """After a Codex run: when Codex replaced the `auth.json` symlink of `codex_env` with a regular file (write a
    temp file, rename it over), that file holds the token Codex refreshed and the real one may hold a rotated-out
    refresh token. A regular, newer file of the same account (`_same_account`) replaces the real `auth.json`
    atomically (mode 0600, same folder); a real path that is a symlink is left alone. An in-place write needs
    nothing: it went through the link. Never logs the token. True when it synced."""
    fresh = run_dir / "codex-home" / "auth.json"
    real = _real_codex_home() / "auth.json"
    try:
        if fresh.is_symlink() or not fresh.is_file() or real.is_symlink():
            return False
        if real.exists() and fresh.stat().st_mtime <= real.stat().st_mtime:
            return False
        content = fresh.read_text(encoding="utf-8")
        if not _same_account(content, real):
            return False
        fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=".auth-")
    except (OSError, ValueError):
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        Path(tmp).chmod(0o600)
        Path(tmp).replace(real)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        return False
    return True


def drop_codex_home(run_dir: Path) -> None:
    """After `sync_auth`: remove the run's `codex-home`, so no copy of a credential outlives the run (run folders
    are kept until pruned). Kept only when it holds a refreshed token that could not be synced because the real
    `auth.json` is a symlink: deleting it would lose that token."""
    home = run_dir / "codex-home"
    fresh = home / "auth.json"
    real = _real_codex_home() / "auth.json"
    with contextlib.suppress(OSError):
        if fresh.is_file() and not fresh.is_symlink() and real.is_symlink():
            return
        shutil.rmtree(home)


def codex_env(run_dir: Path) -> dict[str, str]:
    """`session_env()` with HOME and the XDG folders inside `run_dir`, and a clean `CODEX_HOME` there.

    Codex's model shell is a login shell that re-sources `~/.profile`, which would put `mem` back on PATH
    (observed 2026-11-27); with HOME in the run folder it finds nothing. The real `CODEX_HOME` would also load the
    owner's `AGENTS.md` and plugins into the prompt (`project_doc_max_bytes=0` does not drop them), so
    `<run_dir>/codex-home` (mode 0700) holds only a symlink to the real `auth.json`; the credential is never
    copied, and without a real `auth.json` the link is left out and Codex reports the missing login itself."""
    env = headless.session_env()
    real_codex = _real_codex_home()
    clean = run_dir / "codex-home"
    clean.mkdir(mode=PRIVATE_MODE, parents=True, exist_ok=True)
    link = clean / "auth.json"
    if (real_codex / "auth.json").is_file() and not link.is_symlink():
        link.symlink_to(real_codex / "auth.json")
    env["CODEX_HOME"] = str(clean)
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
    stderr: str = ""


def _text(data: str | bytes | None) -> str:
    if isinstance(data, bytes):
        return codecs.getincrementaldecoder("utf-8")(errors="replace").decode(data, final=False)
    return data or ""


def run_codex(
    cmd: list[str], prompt: str, *, cwd: Path, env: dict[str, str], timeout: float
) -> CodexRaw:
    """Run a Codex session with the prompt on stdin (closed after it); output decoded as UTF-8 with replacement. A
    timeout returns the partial output with `timed_out=True` and no return code, an `OSError` propagates."""
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        process.wait()
        return CodexRaw(_text(exc.stdout), True, None, _text(exc.stderr))
    return CodexRaw(_text(stdout), False, process.returncode, _text(stderr))


@dataclass(frozen=True)
class Outcome:
    """What a builder needs from one session, whichever runner ran it.

    `has_result`: a usable final answer exists (Claude: a `result` event that is not an error; Codex: also a
    completed turn and exit 0). `error`: why the run failed, non-empty exactly when `has_result` is False, for both
    runners. `text`: the final answer (Claude: also the error text of a failed run). `tokens`: Codex: input (cached
    included) plus output, so the cap of a Codex pass counts Codex's own ~44k-token prompt on every call; Claude:
    informational only (Claude budgets stay in USD). `cost_usd`: Claude's reported cost, 0.0 for Codex. `commands`:
    (command, exit code or None) the session ran, Codex only (Claude's tool calls are tallied by the
    synthesizer)."""

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
        not failed,
        text=text,
        tokens=_count(
            final.get("usage"), "input_tokens", "cache_creation_input_tokens", "output_tokens"
        ),
        cost_usd=float(final.get("total_cost_usd") or 0.0),
        error=(text or "the session reported an error") if failed else "",
    )


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
            self.errors.append(str(kind))

    def _item(self, item: dict[str, Any]) -> None:
        if item.get("type") == "agent_message":
            self.text = item.get("text") or ""
        elif item.get("type") == "command_execution":
            self.commands.append((item.get("command") or "", item.get("exit_code")))


def _failure(tally: _Tally, returncode: int | None, stderr: str, timed_out: bool) -> str:
    reasons = list(tally.errors)
    if timed_out:
        reasons.append("the session timed out")
    elif not reasons:
        reasons.append("no final message" if tally.completed else "the session did not complete")
    if returncode not in {0, None}:
        reasons.append(f"exit {returncode}")
    if stderr:
        reasons.append("stderr present")
    return "; ".join(reasons)


def parse_codex(
    stdout: str, returncode: int | None, stderr: str = "", timed_out: bool = False
) -> Outcome:
    """Normalize `codex exec --json` events. `has_result` needs a `turn.completed`, an agent message and exit 0;
    `error` is empty then, else event types, a timeout, exit code and whether stderr was present.
    `tokens` sums `input_tokens` and `output_tokens` (cached and reasoning tokens are parts of those)."""
    tally = _Tally()
    for event in _events(stdout):
        tally.add(event)
    has_result = tally.completed and bool(tally.text) and returncode == 0 and not timed_out
    error = "" if has_result else _failure(tally, returncode, stderr, timed_out)
    return Outcome(has_result, tally.text, tally.tokens, 0.0, tally.commands, error)
