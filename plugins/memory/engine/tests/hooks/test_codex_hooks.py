"""Codex runs the session-end and pre-compact hooks (ADR 0038)."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[3]
HOOKS = PLUGIN / "hooks"
SESSION_END_TIMEOUT = 3
PRE_COMPACT_TIMEOUT = 5


def _commands(event):
    hooks = json.loads((HOOKS / "codex.json").read_text())["hooks"][event][0]["hooks"][0]
    return hooks["command"], hooks["timeout"]


def test_codex_json_declares_session_end_and_pre_compact():
    for event, script, timeout in (
        ("SessionEnd", "session-end.sh", SESSION_END_TIMEOUT),
        ("PreCompact", "pre-compact.sh", PRE_COMPACT_TIMEOUT),
    ):
        command, got = _commands(event)
        assert command.startswith("MEM_HOST=codex ") and command.endswith(f"/hooks/{script}")
        assert got == timeout


def _plugin_copy(tmp_path):
    """A copy of the hooks with a `bin/mem-capture` that records its arguments."""
    root = tmp_path / "plugin"
    shutil.copytree(HOOKS, root / "hooks")
    (root / "bin").mkdir()
    stub = root / "bin" / "mem-capture"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/calls"\n')
    stub.chmod(0o755)
    return root


def _run(root, tmp_path, name, host, option_file=None):
    cfg = tmp_path / "xdg" / "agent-memory"
    cfg.mkdir(parents=True, exist_ok=True)
    if option_file is not None:
        (cfg / "auto_capture").write_text(option_file)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_PLUGIN_OPTION_", "MEM_HOST"))
    }
    env.update({
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "XDG_DATA_HOME": str(tmp_path / "share"),
    })
    if host:
        env["MEM_HOST"] = host
    return subprocess.run(
        [str(root / "hooks" / name)],
        input='{"transcript_path": "/x.jsonl", "cwd": "/x"}',
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _calls(tmp_path, seconds=10):
    calls = tmp_path / "calls"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not calls.exists():
        time.sleep(0.1)
    return calls.read_text().splitlines() if calls.exists() else []


def test_pre_compact_prints_nothing_on_codex(tmp_path):
    root = _plugin_copy(tmp_path)
    done = _run(root, tmp_path, "pre-compact.sh", "codex", "true\n")
    assert done.returncode == 0 and not done.stdout and not done.stderr
    assert _calls(tmp_path)[0].startswith("auto --trigger pre-compact")


def test_pre_compact_claude_output_unchanged(tmp_path):
    root = _plugin_copy(tmp_path)
    done = _run(root, tmp_path, "pre-compact.sh", None)
    assert done.returncode == 0 and done.stdout.startswith("End the summary with this block")
    assert done.stdout.rstrip().endswith("so that the next context can record them.")


def test_session_end_and_pre_compact_read_option_files_on_codex(tmp_path):
    root = _plugin_copy(tmp_path)
    for name, trigger in (("session-end.sh", "session-end"), ("pre-compact.sh", "pre-compact")):
        (tmp_path / "calls").unlink(missing_ok=True)
        (tmp_path / "xdg" / "agent-memory" / "auto_capture").unlink(missing_ok=True)
        assert _run(root, tmp_path, name, "codex").returncode == 0  # no option file: nothing starts
        time.sleep(0.5)
        assert not (tmp_path / "calls").exists()
        assert _run(root, tmp_path, name, "codex", " true \n").returncode == 0
        assert _calls(tmp_path)[0].startswith(f"auto --trigger {trigger}")
