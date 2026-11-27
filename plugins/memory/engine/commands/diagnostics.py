"""Read-only report of local memory configuration and observed hook delivery."""

from __future__ import annotations

import json
import os
import shutil
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from core import config, runner

from commands import common

PLUGIN = Path(__file__).resolve().parents[2]
ROLES = (
    "memory-curator",
    "memory-recorder",
    "memory-researcher",
    "memory-status-checker",
    "memory-synthesizer",
)


def _hook_stamp(line: str, host: str) -> dict[str, str] | None:
    try:
        record = json.loads(line)
        if not isinstance(record, dict) or record.get("host") != host:
            return None
        hook = record.get("hook")
        if hook not in {"session-index", "session-end", "post-compact", "signal"}:
            return None
        stamp = datetime.fromisoformat(record["t"]).isoformat()
        return {"hook": hook, "time": stamp}
    except (TypeError, ValueError, KeyError, RecursionError):
        return None


def _last_hook(data: Path | None, host: str) -> dict[str, str] | None:
    if data is None:
        return None
    try:
        with (data / "hooks" / "log.jsonl").open(encoding="utf-8") as stream:
            recent = deque(stream, maxlen=1000)
    except (OSError, UnicodeError):
        return None
    return next((stamp for line in reversed(recent) if (stamp := _hook_stamp(line, host))), None)


def cmd_diagnostics(args: Any) -> int:
    env = os.environ
    host = (
        args.host or env.get("MEM_HOST") or ("codex" if env.get("CODEX_THREAD_ID") else "unknown")
    )
    if host not in {"codex", "claude"}:
        host = "unknown"
    manifest = PLUGIN / "hooks" / ("codex.json" if host == "codex" else "hooks.json")
    configured: dict[str, bool] = {}
    if host != "unknown":
        try:
            hooks = json.loads(manifest.read_text(encoding="utf-8")).get("hooks", {})
            configured = {
                key: bool(hooks.get(key))
                for key in (
                    "SessionStart",
                    "SessionEnd",
                    "SubagentStart",
                    "PreCompact",
                    "PostCompact",
                )
            }
        except (OSError, ValueError, AttributeError):
            pass
    home = Path(env["HOME"]) if env.get("HOME") else None
    codex_home = (
        Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else (home / ".codex" if home else None)
    )
    roles = {
        name: bool(codex_home and (codex_home / "agents" / (name + ".toml")).is_file())
        for name in ROLES
    }
    root = config.resolve_store(args.root, env)
    result = {
        "plugin_path": str(PLUGIN),
        "host": host,
        "hooks": {
            "manifest": str(manifest) if host != "unknown" else None,
            "configured": configured,
            "trust": "unknown",
            "last_observed": _last_hook(common.data_dir(env), host),
        },
        "roles": {"installed": roles, "session_visibility": "unknown"},
        "store": {
            "path": str(root) if root else None,
            "source": config.store_source(args.root, env),
            "readable": bool(root and root.is_dir() and os.access(root, os.R_OK | os.X_OK)),
        },
        "dependencies": {
            "uv": shutil.which("uv"),
            "claude": shutil.which("claude"),
            "codex": runner.find_codex(env),
        },
    }
    print(json.dumps(result, indent=2))
    return 0


def add_parser(sub: Any) -> None:
    parser = sub.add_parser(
        "diagnostics", help="report local host configuration and observed hook delivery"
    )
    parser.add_argument(
        "--host",
        choices=("claude", "codex"),
        help="host to inspect (otherwise detected where possible)",
    )
    parser.set_defaults(func=cmd_diagnostics)
