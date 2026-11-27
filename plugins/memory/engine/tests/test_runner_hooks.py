"""The hooks hand the plugin option `runner` on as `MEM_RUNNER_OPTION` (ADR 0037): to the passes they start, and, for
shell commands, through `CLAUDE_ENV_FILE`; never as `MEM_RUNNER`, which would outrank the config file."""

import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
BINS = ("mem", "mem-auto", "mem-settle", "mem-capture")
STUB = '#!/bin/sh\necho "$(basename "$0") option=${MEM_RUNNER_OPTION-unset} runner=${MEM_RUNNER-unset}" > "$PASS_LOG"\n'
WAIT = 10  # seconds a started pass may take to report: a bound for a failure, never a delay
STARTS = {
    "session-end.sh": {"mem", "mem-auto", "mem-settle", "mem-capture"},
    "pre-compact.sh": {"mem-capture"},
    "session-index.sh": {"mem", "mem-capture"},
}


@pytest.fixture
def plugin(tmp_path):
    """A copy of the hooks whose `bin/` stubs report the runner variables each pass was started with."""
    root = tmp_path / "plug"
    shutil.copytree(HOOKS, root / "hooks")
    (root / "bin").mkdir()
    for name in BINS:
        (root / "bin" / name).write_text(STUB)
        (root / "bin" / name).chmod(0o755)
    return root


def _hook_env(tmp_path, log, **extra):
    store = tmp_path / "store"
    store.mkdir(exist_ok=True)
    (store / "mem-store.yaml").write_text("")
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "share"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "PASS_LOG": str(log),
        "MEM_STORE": str(store),
        "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE": "true",
        "CLAUDE_PLUGIN_OPTION_AUTO_CURATION": "true",
        "CLAUDE_PLUGIN_OPTION_AUTO_SETTLE": "true",
        **extra,
    }


def _started(plugin, hook, env, wanted):
    """Run the hook and read the stubs' lines from a FIFO until every wanted pass reported (or `WAIT` passes)."""
    log = Path(env["PASS_LOG"])
    os.mkfifo(log)
    fd = os.open(log, os.O_RDWR)  # a reader that is always there: no stub blocks on opening it
    try:
        subprocess.run(
            [str(plugin / "hooks" / hook)],
            env=env,
            input="{}",
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        seen: dict[str, str] = {}
        buffer = b""
        while wanted - seen.keys():
            if not select.select([fd], [], [], WAIT)[0]:
                break
            buffer += os.read(fd, 4096)
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                name, _, rest = line.decode().partition(" ")
                seen[name] = rest
        return seen
    finally:
        os.close(fd)


@pytest.mark.parametrize("hook", STARTS)
def test_a_hook_hands_the_option_to_every_pass_it_starts(plugin, tmp_path, hook):
    env = _hook_env(tmp_path, tmp_path / "log", CLAUDE_PLUGIN_OPTION_RUNNER="codex")
    seen = _started(plugin, hook, env, STARTS[hook])
    assert seen.keys() >= STARTS[hook]
    for name in STARTS[hook] - {"mem"}:
        assert seen[name] == "option=codex runner=unset", name


def test_no_option_starts_the_passes_with_an_empty_one(plugin, tmp_path):
    env = _hook_env(tmp_path, tmp_path / "log")
    seen = _started(plugin, "pre-compact.sh", env, {"mem-capture"})
    assert seen["mem-capture"] == "option= runner=unset"


def test_session_env_exports_the_option_for_shell_commands_and_never_as_mem_runner(
    plugin, tmp_path
):
    env_file = tmp_path / "claude-env"
    env = _hook_env(
        tmp_path,
        tmp_path / "log",
        CLAUDE_ENV_FILE=str(env_file),
        CLAUDE_PLUGIN_OPTION_STORE=str(tmp_path / "store"),
        CLAUDE_PLUGIN_OPTION_RUNNER="codex",
    )
    done = subprocess.run(
        [str(plugin / "hooks" / "session-env.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    lines = env_file.read_text().splitlines()
    assert done.returncode == 0
    assert "export MEM_RUNNER_OPTION=codex" in lines
    assert not any(line.startswith("export MEM_RUNNER=") for line in lines)


def test_session_env_without_the_option_exports_no_runner(plugin, tmp_path):
    env_file = tmp_path / "claude-env"
    env = _hook_env(
        tmp_path,
        tmp_path / "log",
        CLAUDE_ENV_FILE=str(env_file),
        CLAUDE_PLUGIN_OPTION_STORE=str(tmp_path / "store"),
    )
    subprocess.run(
        [str(plugin / "hooks" / "session-env.sh")],
        env=env,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert "RUNNER" not in env_file.read_text()


def test_a_trial_environment_drops_the_owners_runner_settings(tmp_path, monkeypatch):
    import importlib.util  # ruff: ignore[import-outside-top-level]

    spec = importlib.util.spec_from_file_location(
        "trial_env", Path(__file__).resolve().parents[2] / "evals" / "trial_env.py"
    )
    assert spec is not None and spec.loader is not None
    trial_env = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "trial_env", trial_env)  # registered before it runs
    spec.loader.exec_module(trial_env)
    names = ("MEM_RUNNER", "MEM_RUNNER_OPTION", "MEM_CODEX", "MEM_CODEX_TOKENS")
    for name in names:
        monkeypatch.setenv(name, "codex")
    env = trial_env.make_env(tmp_path)
    assert not any(name in env for name in names)
