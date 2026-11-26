"""The hooks resolve the note store the same way: the option, else a marked default store."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / "hooks"
PRINTING = ("session-index.sh", "post-compact.sh", "signal.sh")
STUB = 'echo "STORE=${MEM_STORE-unset} MEMORIES=${MEM_MEMORIES-unset}"\n'


def _plugin(tmp_path):
    """A copy of the hooks with a stub `mem` that prints the store variables it was started with."""
    root = tmp_path / "plug"
    shutil.copytree(HOOKS, root / "hooks")
    (root / "bin").mkdir()
    mem = root / "bin" / "mem"
    mem.write_text("#!/bin/sh\n" + STUB)
    mem.chmod(0o755)
    return root


def _env(tmp_path, **extra):
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "share"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        **extra,
    }


def _default_store(tmp_path, marked):
    store = tmp_path / "share" / "agent-memory" / "store"
    store.mkdir(parents=True)
    if marked:
        (store / "mem-store.yaml").write_text("")
    return store


def _run(root, name, env):
    return subprocess.run(
        [str(root / "hooks" / name)],
        env=env,
        input="{}",
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


@pytest.mark.parametrize("name", PRINTING)
def test_the_option_is_handed_to_mem(tmp_path, name):
    root = _plugin(tmp_path)
    env = _env(
        tmp_path, CLAUDE_PLUGIN_OPTION_STORE="/a path/store", CLAUDE_PLUGIN_OPTION_MEMORIES="/m"
    )
    r = _run(root, name, env)
    assert r.returncode == 0 and not r.stderr
    assert "STORE=/a path/store MEMORIES=/m" in r.stdout


@pytest.mark.parametrize("name", PRINTING)
def test_no_option_uses_a_marked_default_store(tmp_path, name):
    root = _plugin(tmp_path)
    store = _default_store(tmp_path, marked=True)
    r = _run(root, name, _env(tmp_path))
    assert r.returncode == 0 and not r.stderr
    assert f"STORE={store} MEMORIES=unset" in r.stdout


@pytest.mark.parametrize("name", PRINTING)
def test_no_option_ignores_an_unmarked_default_folder(tmp_path, name):
    root = _plugin(tmp_path)
    _default_store(tmp_path, marked=False)
    r = _run(root, name, _env(tmp_path))
    assert r.returncode == 0 and not r.stderr
    assert "STORE=unset MEMORIES=unset" in r.stdout


@pytest.mark.parametrize("name", PRINTING)
def test_a_missing_store_file_keeps_the_hook_silent(tmp_path, name):
    root = _plugin(tmp_path)
    (root / "hooks" / "store-env.sh").unlink(missing_ok=True)
    r = _run(root, name, _env(tmp_path, CLAUDE_PLUGIN_OPTION_STORE="/s"))
    assert r.returncode == 0 and not r.stderr


@pytest.mark.parametrize("name", PRINTING)
def test_no_home_finds_no_default_store(tmp_path, name):
    root = _plugin(tmp_path)
    env = _env(tmp_path)
    del env["HOME"], env["XDG_DATA_HOME"]
    r = _run(root, name, env)
    assert r.returncode == 0 and not r.stderr
    assert "STORE=unset" in r.stdout


def _session_end(tmp_path, **extra):
    root = _plugin(tmp_path)
    out = tmp_path / "calls.txt"
    mem = root / "bin" / "mem"
    mem.write_text(f'#!/bin/sh\necho "STORE=${{MEM_STORE-unset}}" >> "{out}"\n')
    r = _run(root, "session-end.sh", _env(tmp_path, **extra))
    for _ in range(100):  # the commit runs detached
        if out.exists() and out.read_text():
            break
        time.sleep(0.1)
    return r, out.read_text() if out.exists() else ""


def test_session_end_gets_the_option(tmp_path):
    r, calls = _session_end(tmp_path, CLAUDE_PLUGIN_OPTION_STORE="/opt")
    assert r.returncode == 0 and not r.stderr
    assert "STORE=/opt" in calls


def test_session_end_gets_a_marked_default_store(tmp_path):
    store = _default_store(tmp_path, marked=True)
    r, calls = _session_end(tmp_path)
    assert r.returncode == 0 and not r.stderr
    assert f"STORE={store}" in calls


def test_session_end_ignores_an_unmarked_default_folder(tmp_path):
    _default_store(tmp_path, marked=False)
    r, calls = _session_end(tmp_path)
    assert r.returncode == 0 and not r.stderr
    assert "STORE=unset" in calls


def _env_file_run(tmp_path, **extra):
    root = _plugin(tmp_path)
    envfile = tmp_path / "envfile"
    envfile.write_text("")
    r = _run(root, "session-env.sh", _env(tmp_path, CLAUDE_ENV_FILE=str(envfile), **extra))
    return r, envfile.read_text()


def test_session_env_option_set(tmp_path):
    r, exported = _env_file_run(tmp_path, CLAUDE_PLUGIN_OPTION_STORE="/a path/store")
    assert r.returncode == 0 and not r.stderr
    assert (tmp_path / "cfg" / "agent-memory" / "store").read_text() == "/a path/store\n"
    assert "export MEM_STORE=" in exported


def test_session_env_option_cleared_removes_the_config_file(tmp_path):
    cfg = tmp_path / "cfg" / "agent-memory"
    cfg.mkdir(parents=True)
    (cfg / "store").write_text("/old\n")
    r, exported = _env_file_run(tmp_path)
    assert r.returncode == 0 and not r.stderr
    assert not (cfg / "store").exists()
    assert "MEM_STORE" not in exported


def test_session_env_hands_over_a_marked_default_store(tmp_path):
    store = _default_store(tmp_path, marked=True)
    r, exported = _env_file_run(tmp_path)
    assert r.returncode == 0 and not r.stderr
    assert f"MEM_STORE={store}" in exported


def test_session_env_ignores_an_unmarked_default_folder(tmp_path):
    _default_store(tmp_path, marked=False)
    r, exported = _env_file_run(tmp_path)
    assert r.returncode == 0 and not r.stderr
    assert "MEM_STORE" not in exported


def _logging_mem(root, tmp_path):
    """Replace the stub `mem` with one that records each call's arguments."""
    calls = tmp_path / "mem-calls.txt"
    (root / "bin" / "mem").write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
    return calls


def test_session_env_runs_no_init_without_a_data_folder(tmp_path):
    root = _plugin(tmp_path)
    calls = _logging_mem(root, tmp_path)
    envfile = tmp_path / "envfile"
    envfile.write_text("")
    env = _env(tmp_path, CLAUDE_ENV_FILE=str(envfile))
    del env["HOME"], env["XDG_DATA_HOME"]
    r = _run(root, "session-env.sh", env)
    assert r.returncode == 0 and not r.stderr
    assert not calls.exists()
    assert "MEM_STORE" not in envfile.read_text()


def test_session_env_without_its_helper_starts_no_init(tmp_path):
    root = _plugin(tmp_path)
    (root / "hooks" / "store-env.sh").unlink()
    calls = _logging_mem(root, tmp_path)
    _default_store(tmp_path, marked=True)
    envfile = tmp_path / "envfile"
    envfile.write_text("")
    r = _run(root, "session-env.sh", _env(tmp_path, CLAUDE_ENV_FILE=str(envfile)))
    assert r.returncode == 0 and not r.stderr
    assert not calls.exists() or "init" not in calls.read_text()
