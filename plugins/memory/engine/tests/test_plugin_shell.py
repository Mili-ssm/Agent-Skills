import json
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


def test_hook_handles_the_memories_option_like_the_store(tmp_path):
    envfile = tmp_path / "env"
    envfile.write_text("")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c")}
    r = run([str(HOOK)], {**env, "CLAUDE_PLUGIN_OPTION_MEMORIES": "/a path/mem", "CLAUDE_ENV_FILE": str(envfile)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert (tmp_path / "c" / "agent-memory" / "memories").read_text() == "/a path/mem\n"
    assert not (tmp_path / "c" / "agent-memory" / "store").exists()
    out = subprocess.run(["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_MEMORIES\""], capture_output=True, text=True).stdout
    assert out == "/a path/mem"
    r = run([str(HOOK)], env)  # cleared
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert not (tmp_path / "c" / "agent-memory" / "memories").exists()


def test_hook_keeps_each_option_independent(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c")}
    run([str(HOOK)], {**env, "CLAUDE_PLUGIN_OPTION_STORE": "/s", "CLAUDE_PLUGIN_OPTION_MEMORIES": "/m"})
    run([str(HOOK)], {**env, "CLAUDE_PLUGIN_OPTION_STORE": "/s"})
    assert (tmp_path / "c" / "agent-memory" / "store").read_text() == "/s\n"
    assert not (tmp_path / "c" / "agent-memory" / "memories").exists()


HOOKS = Path(__file__).resolve().parents[2] / "hooks"
SUBAGENT_TEXT = (
    'memory: this project and the owner\'s store have a searchable memory. If you can run shell commands and your brief '
    'has no memory section: mem search "<question in English>", then mem show <handle>. Project memories are files in '
    '.memory/ at the repository root. A line marked [memory: ...] is experience, not fact. Do not run mem remember: '
    'tell your caller what is worth remembering, if anything.')
PRE_COMPACT = ('Keep in the summary: the path of the active plan file (say "no plan" if there is none), and every '
               'decision, constraint, pitfall or finding of this session that was not yet recorded with mem remember, '
               'marked "not yet recorded", so that the next context can record them.')


@pytest.mark.parametrize("name", ["session-env.sh", "session-index.sh", "subagent-start.sh", "pre-compact.sh"])
def test_hook_scripts_are_executable(name):
    assert os.access(HOOKS / name, os.X_OK)


def test_hooks_json_names_the_scripts():
    cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
    start = cfg["SessionStart"]
    assert "matcher" not in start[0] and "session-env.sh" in start[0]["hooks"][0]["command"]
    assert start[1]["matcher"] == "startup|clear|compact"
    assert start[1]["hooks"][0]["command"].endswith("/hooks/session-index.sh") and start[1]["hooks"][0]["timeout"] == 10
    assert cfg["SubagentStart"][0]["hooks"][0]["command"].endswith("/hooks/subagent-start.sh")
    assert cfg["PreCompact"][0]["hooks"][0]["command"].endswith("/hooks/pre-compact.sh")


def test_subagent_start_prints_the_json_text():
    r = run([str(HOOKS / "subagent-start.sh")], {})
    assert r.returncode == 0 and r.stderr == ""
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SubagentStart" and out["additionalContext"] == SUBAGENT_TEXT
    assert len(SUBAGENT_TEXT) <= 400


def test_pre_compact_prints_its_line():
    r = run([str(HOOKS / "pre-compact.sh")], {})
    assert r.returncode == 0 and r.stdout == PRE_COMPACT + "\n" and r.stderr == ""


@needs_uv
def test_session_index_hook_with_spaced_store_and_logs(hub_root, tmp_path):
    spaced = tmp_path / "my store"
    shutil.copytree(hub_root, spaced)
    proj = tmp_path / "p"
    proj.mkdir()
    r = subprocess.run([str(HOOKS / "session-index.sh")], input=json.dumps({"cwd": str(proj), "source": "startup"}),
                       env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "CLAUDE_PLUGIN_OPTION_STORE": str(spaced),
                            "MEM_DATA": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c"), "MEM_PROJECT": str(proj)},
                       capture_output=True, text=True)
    lines = r.stdout.split("\n")
    assert r.returncode == 0 and r.stderr == ""
    assert lines[0].startswith("memory: the mem command") and " Store: " in lines[0] and len(lines) == 4
    rec = json.loads((tmp_path / "d" / "hooks" / "log.jsonl").read_text().splitlines()[0])
    assert rec["source"] == "startup"


@pytest.mark.skipif(any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin")
def test_session_index_hook_without_uv_is_silent(tmp_path):
    r = subprocess.run([str(HOOKS / "session-index.sh")], input="{}", env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
