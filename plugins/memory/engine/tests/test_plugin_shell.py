import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import handoff

MEM = Path(__file__).resolve().parents[2] / "bin" / "mem"
HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session-env.sh"

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")


def run(cmd, env):  # PATH and HOME are carried over so uv keeps its cache; config and data go to tmp
    # XDG_DATA_HOME is always set: without it the default store would be the real one under HOME
    env = {"XDG_DATA_HOME": str(Path(env.get("XDG_CONFIG_HOME", env.get("MEM_DATA", "/nonexistent"))).parent / "share"), **env}
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


@needs_uv
def test_hook_without_option_makes_the_default_store_once(tmp_path):
    envfile = tmp_path / "env"
    envfile.write_text("")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(tmp_path / "share"), "CLAUDE_ENV_FILE": str(envfile)}
    default = tmp_path / "share" / "agent-memory" / "store"
    r = run([str(HOOK)], env)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert (default / "mem-store.yaml").is_file()
    assert (tmp_path / "c" / "agent-memory" / "forbidden-terms").is_file()
    assert not (tmp_path / "c" / "agent-memory" / "store").exists()
    out = subprocess.run(["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_STORE\""], capture_output=True, text=True).stdout
    assert out == str(default)
    (default / "marker").write_text("x")
    assert run([str(HOOK)], env).returncode == 0
    assert (default / "marker").exists()  # an existing default store is not initialized again


def test_hook_without_option_is_silent_when_init_fails(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(blocker)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_hook_with_the_option_does_not_make_the_default_store(tmp_path):
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(tmp_path / "share"),
                          "CLAUDE_PLUGIN_OPTION_STORE": "/s"})
    assert r.returncode == 0 and not (tmp_path / "share").exists()


def test_hook_is_silent_when_the_env_file_cannot_be_written(tmp_path):
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "CLAUDE_PLUGIN_OPTION_STORE": "/s",
                          "CLAUDE_ENV_FILE": str(tmp_path / "missing" / "env")})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


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
    'memory: decisions, constraints and pitfalls learned in earlier sessions are in a searchable memory, not in '
    'the files. Before you change or decide anything, if you can run shell commands: '
    'mem search "<topic in English>", then mem show <handle>. Project memories are files in '
    '.memory/ at the repository root. A line marked [memory: ...] is experience, not fact. Do not run mem remember: '
    'tell your caller what is worth remembering, if anything.')


@pytest.mark.parametrize("name", ["session-env.sh", "session-index.sh", "signal.sh", "subagent-start.sh", "pre-compact.sh", "post-compact.sh", "session-end.sh"])
def test_hook_scripts_are_executable(name):
    assert os.access(HOOKS / name, os.X_OK)


def test_hooks_json_names_the_scripts():
    cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
    start = cfg["SessionStart"]
    assert "matcher" not in start[0] and "session-env.sh" in start[0]["hooks"][0]["command"]
    assert start[1]["matcher"] == "startup|clear|compact"
    assert start[1]["hooks"][0]["command"].endswith("/hooks/session-index.sh") and start[1]["hooks"][0]["timeout"] == 10
    assert cfg["SubagentStart"][0]["hooks"][0]["command"].endswith("/hooks/subagent-start.sh")
    assert "PreToolUse" not in cfg  # the signal hook is built but not registered: it showed no gain (stage 6 plan)
    assert cfg["PreCompact"][0]["hooks"][0]["command"].endswith("/hooks/pre-compact.sh")
    assert cfg["PostCompact"][0]["hooks"][0]["command"].endswith("/hooks/post-compact.sh")
    assert cfg["PostCompact"][0]["hooks"][0]["timeout"] == 5
    assert cfg["SessionEnd"][0]["hooks"][0]["command"].endswith("/hooks/session-end.sh")


def test_subagent_start_prints_the_json_text():
    r = run([str(HOOKS / "subagent-start.sh")], {})
    assert r.returncode == 0 and r.stderr == ""
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SubagentStart" and out["additionalContext"] == SUBAGENT_TEXT
    assert len(SUBAGENT_TEXT) <= 450


def test_pre_compact_prints_the_handoff_instruction():
    r = run([str(HOOKS / "pre-compact.sh")], {})
    assert r.returncode == 0 and r.stdout == handoff.INSTRUCTION + "\n" and r.stderr == ""


@needs_uv
def test_session_index_hook_with_spaced_store_and_logs(hub_root, tmp_path):
    spaced = tmp_path / "my store"
    shutil.copytree(hub_root, spaced)
    proj = tmp_path / "p"
    proj.mkdir()
    r = subprocess.run([str(HOOKS / "session-index.sh")], input=json.dumps({"cwd": str(proj), "source": "startup"}),
                       env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "CLAUDE_PLUGIN_OPTION_STORE": str(spaced),
                            "MEM_DATA": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c"), "MEM_PROJECT": str(proj),
                            "XDG_DATA_HOME": str(tmp_path / "share")},
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


@pytest.mark.skipif(any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin")
def test_post_compact_hook_without_uv_is_silent(tmp_path):
    summary = json.dumps({"compact_summary": "A summary with no block.", "cwd": str(tmp_path)})  # prints when uv is present
    r = subprocess.run([str(HOOKS / "post-compact.sh")], input=summary, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def _signal_env(tmp_path, **extra):
    root = tmp_path / "proj"
    folder = root / ".memory"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "retry-keys.md").write_text(
        "---\nkind: lesson\nclaim: Retries without idempotency keys duplicate side effects\n"
        "created: 2026-11-01\nobserved: 1\nstatus: active\n---\n", encoding="utf-8")
    return {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "MEM_DATA": str(tmp_path / "d"),
            "XDG_CONFIG_HOME": str(tmp_path / "c"), "MEM_PROJECT": str(root), "XDG_DATA_HOME": str(tmp_path / "share"),
            **extra}


def _signal(tmp_path, stdin, **extra):
    return subprocess.run([str(HOOKS / "signal.sh")], input=stdin, env=_signal_env(tmp_path, **extra),
                          capture_output=True, text=True)


def _agent_input(prompt, tmp_path):
    return json.dumps({"tool_name": "Agent", "tool_input": {"prompt": prompt, "subagent_type": "Explore"},
                       "cwd": str(tmp_path)})


@needs_uv
def test_signal_hook_prints_the_updated_input(tmp_path):
    brief = "Check how retries without idempotency keys duplicate side effects."
    r = _signal(tmp_path, _agent_input(brief, tmp_path))
    assert r.returncode == 0 and r.stderr == ""
    spec = json.loads(r.stdout)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse" and "permissionDecision" not in spec
    assert spec["updatedInput"]["prompt"].startswith(brief) and "m:retry-keys" in spec["updatedInput"]["prompt"]
    assert spec["updatedInput"]["subagent_type"] == "Explore"


@needs_uv
@pytest.mark.parametrize("stdin", ["", "not json", '{"tool_name": "Agent"}'])
def test_signal_hook_is_silent_on_bad_input(tmp_path, stdin):
    r = _signal(tmp_path, stdin)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


@needs_uv
def test_signal_hook_is_silent_without_a_match(tmp_path):
    r = _signal(tmp_path, _agent_input("Write a poem about the sea.", tmp_path))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


@pytest.mark.skipif(any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin")
def test_signal_hook_without_uv_is_silent(tmp_path):
    r = subprocess.run([str(HOOKS / "signal.sh")], input=_agent_input("retries", tmp_path),
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


@pytest.mark.parametrize("agent", ["memory:memory-researcher", "memory-recorder", "memory:memory-curator"])
def test_subagent_start_is_silent_for_the_plugins_own_agents(agent):
    r = subprocess.run([str(HOOKS / "subagent-start.sh")], input=json.dumps({"agent_type": agent, "agent_id": "a1"}),
                       env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_subagent_start_still_speaks_to_other_agents():
    r = subprocess.run([str(HOOKS / "subagent-start.sh")], input=json.dumps({"agent_type": "Explore", "agent_id": "a1"}),
                       env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
    assert json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] == SUBAGENT_TEXT


@needs_uv
def test_session_index_hook_finds_the_default_store(tmp_path):
    share = tmp_path / "share"
    proj = tmp_path / "p"
    proj.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "MEM_DATA": str(tmp_path / "d"),
           "XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(share), "MEM_PROJECT": str(proj)}
    assert subprocess.run([str(MEM), "init"], env=env, capture_output=True, text=True).returncode == 0
    r = subprocess.run([str(HOOKS / "session-index.sh")], input=json.dumps({"cwd": str(proj), "source": "startup"}),
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0 and r.stderr == "" and " Store: 0 notes." in r.stdout.split("\n")[0]


@needs_uv
def test_clearing_the_store_option_removes_the_old_config_file_and_falls_back_to_the_default(tmp_path):
    envfile = tmp_path / "env"
    envfile.write_text("")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(tmp_path / "share"), "CLAUDE_ENV_FILE": str(envfile)}
    assert run([str(HOOK)], {**env, "CLAUDE_PLUGIN_OPTION_STORE": "/old/store"}).returncode == 0
    old = tmp_path / "c" / "agent-memory" / "store"
    assert old.read_text() == "/old/store\n"
    envfile.write_text("")
    r = run([str(HOOK)], env)  # the option is now empty
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert not old.exists()
    out = subprocess.run(["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_STORE\""], capture_output=True, text=True).stdout
    assert out == str(tmp_path / "share" / "agent-memory" / "store")


def test_session_index_falls_back_to_the_fixed_rules_when_mem_cannot_run(tmp_path):
    # No uv on the path: the hook must still open the session with the rules, and they must be the engine's own.
    import mem
    r = subprocess.run([str(HOOKS / "session-index.sh")], input="{}", capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path / "data"),
                            "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "MEM_DATA": str(tmp_path / "d")})
    if shutil.which("uv", path="/usr/bin:/bin"):
        pytest.skip("uv is in a system folder")
    assert r.returncode == 0 and r.stderr == ""
    assert r.stdout.rstrip("\n") == mem._INDEX_RULES


def _session_end(tmp_path, store, fake_git=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home"), "CLAUDE_PLUGIN_OPTION_STORE": str(store),
           "MEM_DATA": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c"), "MEM_PROJECT": str(tmp_path / "p"),
           "XDG_DATA_HOME": str(tmp_path / "share"), "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_CONFIG_SYSTEM": os.devnull}
    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "gitconfig").write_text("", encoding="utf-8")
    if fake_git:
        bindir = tmp_path / "fake"
        bindir.mkdir()
        (bindir / "git").write_text(fake_git, encoding="utf-8")
        (bindir / "git").chmod(0o755)
        env["PATH"] = f"{bindir}:{env['PATH']}"
    return subprocess.run([str(HOOKS / "session-end.sh")], input="{}", env=env, capture_output=True, text=True)


@needs_uv
def test_session_end_hook_commits_the_store(hub_root, tmp_path):
    sys_path = str(Path(__file__).resolve().parents[1])
    subprocess.run(["python3", "-c", f"import sys; sys.path.insert(0, {sys_path!r}); import store_git, pathlib; "
                    f"store_git.init(pathlib.Path({str(hub_root)!r}))"], check=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "HOME": str(tmp_path)})
    (hub_root / "knowledge" / "new.md").write_text("new\n", encoding="utf-8")
    r = _session_end(tmp_path, hub_root)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    subject = subprocess.run(["git", "-C", str(hub_root), "log", "-1", "--format=%s"], capture_output=True, text=True).stdout
    assert subject.startswith("session end ")
    rec = json.loads((tmp_path / "d" / "hooks" / "log.jsonl").read_text().splitlines()[-1])
    assert rec["hook"] == "session-end" and "ms" in rec


@needs_uv
def test_session_end_hook_exits_0_when_git_fails(hub_root, tmp_path):
    subprocess.run(["git", "-C", str(hub_root), "init", "-q"], check=True)
    r = _session_end(tmp_path, hub_root, fake_git="#!/bin/sh\nexit 1\n")
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


@needs_uv
@pytest.mark.skipif(shutil.which("timeout") is None, reason="no timeout command")
def test_session_end_hook_exits_0_when_git_hangs(hub_root, tmp_path):
    subprocess.run(["git", "-C", str(hub_root), "init", "-q"], check=True)
    started = time.monotonic()
    r = _session_end(tmp_path, hub_root, fake_git="#!/bin/sh\nsleep 30\n")
    assert r.returncode == 0 and time.monotonic() - started < 9
