import os
import shutil
import subprocess
from pathlib import Path

import pytest

MEM = Path(__file__).resolve().parents[2] / "bin" / "mem"
HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session-env.sh"

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")


def run(cmd, env):  # PATH and HOME are carried over so uv keeps its cache; config and data go to tmp
    return subprocess.run(cmd, env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **env}, capture_output=True, text=True)


@needs_uv
def test_mem_searches_the_configured_store(hub_root, tmp_path):
    r = run([str(MEM), "search", "attention"], {"MEM_STORE": str(hub_root), "MEM_DATA": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c")})
    assert r.returncode == 0 and "attention" in r.stdout.lower()


@needs_uv
def test_mem_store_path_with_spaces(hub_root, tmp_path):
    spaced = tmp_path / "my store"
    shutil.copytree(hub_root, spaced)
    r = run([str(MEM), "search", "attention"], {"MEM_STORE": str(spaced), "MEM_DATA": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c")})
    assert r.returncode == 0


@needs_uv
def test_mem_without_store(tmp_path):
    r = run([str(MEM), "search", "x"], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "MEM_DATA": str(tmp_path / "d")})
    assert r.returncode == 2 and r.stderr.startswith("mem: no store is set.")


@pytest.mark.skipif(any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin")
def test_mem_without_uv(tmp_path):
    r = subprocess.run([str(MEM), "search", "x"], env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 127 and r.stderr.strip() == "mem: uv is not installed (https://docs.astral.sh/uv/)"


def test_hook_writes_config_and_env(tmp_path):
    envfile = tmp_path / "env"
    envfile.write_text("")
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "CLAUDE_PLUGIN_OPTION_STORE": "/a path/store", "CLAUDE_ENV_FILE": str(envfile)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert (tmp_path / "c" / "agent-memory" / "store").read_text() == "/a path/store\n"
    out = subprocess.run(["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_STORE\""], capture_output=True, text=True).stdout
    assert out == "/a path/store"


def test_hook_without_option_does_nothing(tmp_path):
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c")})
    assert r.returncode == 0 and r.stdout == "" and not (tmp_path / "c").exists()


def test_hook_is_silent_when_the_env_file_cannot_be_written(tmp_path):
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "CLAUDE_PLUGIN_OPTION_STORE": "/s",
                          "CLAUDE_ENV_FILE": str(tmp_path / "missing" / "env")})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_hook_removes_the_config_file_when_the_option_is_cleared(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c")}
    assert run([str(HOOK)], {**env, "CLAUDE_PLUGIN_OPTION_STORE": "/s"}).returncode == 0
    assert (tmp_path / "c" / "agent-memory" / "store").exists()
    r = run([str(HOOK)], env)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert not (tmp_path / "c" / "agent-memory" / "store").exists()
