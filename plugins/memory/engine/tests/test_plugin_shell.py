import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import mem
import pytest
from core import store_git
from session import handoff
from test_capture_auto import hook as capture_hook
from test_capture_auto import world
from test_mem_capture import FAKE
from test_store_git import FULL_TAIL, NOTE

__all__ = ["world"]  # re-exported: pytest finds the fixture in this module by its name

MEM = Path(__file__).resolve().parents[2] / "bin" / "mem"
HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session-env.sh"

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")


def run(
    cmd, env
):  # PATH and HOME are carried over so uv keeps its cache; config and data go to tmp
    # XDG_DATA_HOME is always set: without it the default store would be the real one under HOME
    env = {
        "XDG_DATA_HOME": str(
            Path(env.get("XDG_CONFIG_HOME", env.get("MEM_DATA", "/nonexistent"))).parent / "share"
        ),
        **env,
    }
    return subprocess.run(
        cmd,
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **env},
        capture_output=True,
        text=True,
        check=False,
    )


@needs_uv
def test_mem_searches_the_configured_store(hub_root, tmp_path):
    r = run(
        [str(MEM), "search", "attention"],
        {
            "MEM_STORE": str(hub_root),
            "MEM_DATA": str(tmp_path / "d"),
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
        },
    )
    assert r.returncode == 0 and "attention" in r.stdout.lower()


@needs_uv
def test_mem_store_path_with_spaces(hub_root, tmp_path):
    spaced = tmp_path / "my store"
    shutil.copytree(hub_root, spaced)
    r = run(
        [str(MEM), "search", "attention"],
        {
            "MEM_STORE": str(spaced),
            "MEM_DATA": str(tmp_path / "d"),
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
        },
    )
    assert r.returncode == 0


@needs_uv
def test_mem_without_store(tmp_path):
    r = run(
        [str(MEM), "search", "x"],
        {"XDG_CONFIG_HOME": str(tmp_path / "c"), "MEM_DATA": str(tmp_path / "d")},
    )
    assert r.returncode == EXIT_USAGE and r.stderr.startswith("mem: no store is set.")


@pytest.mark.skipif(
    any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin"
)
def test_mem_without_uv(tmp_path):
    r = subprocess.run(
        [str(MEM), "search", "x"],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        r.returncode == EXIT_NOT_FOUND
        and r.stderr.strip() == "mem: uv is not installed (https://docs.astral.sh/uv/)"
    )


def test_hook_writes_config_and_env(tmp_path):
    envfile = tmp_path / "env"
    envfile.write_text("")
    r = run(
        [str(HOOK)],
        {
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
            "CLAUDE_PLUGIN_OPTION_STORE": "/a path/store",
            "CLAUDE_ENV_FILE": str(envfile),
        },
    )
    assert r.returncode == 0 and not r.stdout and not r.stderr
    assert (tmp_path / "c" / "agent-memory" / "store").read_text() == "/a path/store\n"
    out = subprocess.run(
        ["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_STORE\""],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert out == "/a path/store"


@needs_uv
def test_hook_without_option_makes_the_default_store_once(tmp_path):
    envfile = tmp_path / "env"
    envfile.write_text("")
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "c"),
        "XDG_DATA_HOME": str(tmp_path / "share"),
        "CLAUDE_ENV_FILE": str(envfile),
    }
    default = tmp_path / "share" / "agent-memory" / "store"
    r = run([str(HOOK)], env)
    assert r.returncode == 0 and not r.stdout and not r.stderr
    assert (default / "mem-store.yaml").is_file()
    assert (tmp_path / "c" / "agent-memory" / "forbidden-terms").is_file()
    assert not (tmp_path / "c" / "agent-memory" / "store").exists()
    out = subprocess.run(
        ["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_STORE\""],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert out == str(default)
    (default / "marker").write_text("x")
    assert run([str(HOOK)], env).returncode == 0
    assert (default / "marker").exists()  # an existing default store is not initialized again


def test_hook_without_option_is_silent_when_init_fails(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(blocker)})
    assert r.returncode == 0 and not r.stdout and not r.stderr


def test_hook_with_the_option_does_not_make_the_default_store(tmp_path):
    r = run(
        [str(HOOK)],
        {
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
            "XDG_DATA_HOME": str(tmp_path / "share"),
            "CLAUDE_PLUGIN_OPTION_STORE": "/s",
        },
    )
    assert r.returncode == 0 and not (tmp_path / "share").exists()


def test_hook_is_silent_when_the_env_file_cannot_be_written(tmp_path):
    r = run(
        [str(HOOK)],
        {
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
            "CLAUDE_PLUGIN_OPTION_STORE": "/s",
            "CLAUDE_ENV_FILE": str(tmp_path / "missing" / "env"),
        },
    )
    assert r.returncode == 0 and not r.stdout and not r.stderr


def test_hook_handles_the_memories_option_like_the_store(tmp_path):
    envfile = tmp_path / "env"
    envfile.write_text("")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c")}
    r = run(
        [str(HOOK)],
        {**env, "CLAUDE_PLUGIN_OPTION_MEMORIES": "/a path/mem", "CLAUDE_ENV_FILE": str(envfile)},
    )
    assert r.returncode == 0 and not r.stdout and not r.stderr
    assert (tmp_path / "c" / "agent-memory" / "memories").read_text() == "/a path/mem\n"
    assert not (tmp_path / "c" / "agent-memory" / "store").exists()
    out = subprocess.run(
        ["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_MEMORIES\""],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert out == "/a path/mem"
    r = run([str(HOOK)], env)  # cleared
    assert r.returncode == 0 and not r.stdout and not r.stderr
    assert not (tmp_path / "c" / "agent-memory" / "memories").exists()


def test_hook_keeps_each_option_independent(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "c")}
    run(
        [str(HOOK)],
        {**env, "CLAUDE_PLUGIN_OPTION_STORE": "/s", "CLAUDE_PLUGIN_OPTION_MEMORIES": "/m"},
    )
    run([str(HOOK)], {**env, "CLAUDE_PLUGIN_OPTION_STORE": "/s"})
    assert (tmp_path / "c" / "agent-memory" / "store").read_text() == "/s\n"
    assert not (tmp_path / "c" / "agent-memory" / "memories").exists()


SLOW_COMMIT_SECONDS = 1.5
EXIT_USAGE = 2
EXIT_NOT_FOUND = 127
INDEX_HOOK_TIMEOUT = 10
POST_COMPACT_TIMEOUT = 5
SUBAGENT_TEXT_LIMIT = 450
INDEX_LINES = 4
DETACHED_SECONDS = 2
DEFAULT_BUDGET = 0.25
HUNG_COMMIT_SECONDS = 9
MEM_BOUND_SECONDS = 8
HOOKS = Path(__file__).resolve().parents[2] / "hooks"
SUBAGENT_TEXT = (
    "memory: decisions, constraints and pitfalls learned in earlier sessions are in a searchable memory, not in "
    "the files. Before you change or decide anything, if you can run shell commands: "
    'mem search "<topic in English>", then mem show <handle>. Project memories are files in '
    ".memory/ at the repository root. A line marked [memory: ...] is experience, not fact. Do not run mem remember: "
    "tell your caller what is worth remembering, if anything."
)


@pytest.mark.parametrize(
    "name",
    [
        "session-env.sh",
        "session-index.sh",
        "signal.sh",
        "subagent-start.sh",
        "pre-compact.sh",
        "post-compact.sh",
        "session-end.sh",
    ],
)
def test_hook_scripts_are_executable(name):
    assert os.access(HOOKS / name, os.X_OK)


def test_hooks_json_names_the_scripts():
    cfg = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
    start = cfg["SessionStart"]
    assert "matcher" not in start[0] and "session-env.sh" in start[0]["hooks"][0]["command"]
    assert start[1]["matcher"] == "startup|clear|compact"
    assert (
        start[1]["hooks"][0]["command"].endswith("/hooks/session-index.sh")
        and start[1]["hooks"][0]["timeout"] == INDEX_HOOK_TIMEOUT
    )
    assert cfg["SubagentStart"][0]["hooks"][0]["command"].endswith("/hooks/subagent-start.sh")
    assert (
        "PreToolUse" not in cfg
    )  # the signal hook is built but not registered: it showed no gain (stage 6 plan)
    assert cfg["PreCompact"][0]["hooks"][0]["command"].endswith("/hooks/pre-compact.sh")
    assert cfg["PostCompact"][0]["hooks"][0]["command"].endswith("/hooks/post-compact.sh")
    assert cfg["PostCompact"][0]["hooks"][0]["timeout"] == POST_COMPACT_TIMEOUT
    assert cfg["SessionEnd"][0]["hooks"][0]["command"].endswith("/hooks/session-end.sh")


def test_subagent_start_prints_the_json_text():
    r = run([str(HOOKS / "subagent-start.sh")], {})
    assert r.returncode == 0 and not r.stderr
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SubagentStart" and out["additionalContext"] == SUBAGENT_TEXT
    assert len(SUBAGENT_TEXT) <= SUBAGENT_TEXT_LIMIT


def test_pre_compact_prints_the_handoff_instruction():
    r = run([str(HOOKS / "pre-compact.sh")], {})
    assert r.returncode == 0 and r.stdout == handoff.INSTRUCTION + "\n" and not r.stderr


@needs_uv
def test_session_index_hook_with_spaced_store_and_logs(hub_root, tmp_path):
    spaced = tmp_path / "my store"
    shutil.copytree(hub_root, spaced)
    proj = tmp_path / "p"
    proj.mkdir()
    r = subprocess.run(
        [str(HOOKS / "session-index.sh")],
        input=json.dumps({"cwd": str(proj), "source": "startup"}),
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "CLAUDE_PLUGIN_OPTION_STORE": str(spaced),
            "MEM_DATA": str(tmp_path / "d"),
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
            "MEM_PROJECT": str(proj),
            "XDG_DATA_HOME": str(tmp_path / "share"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    lines = r.stdout.split("\n")
    assert r.returncode == 0 and not r.stderr
    assert (
        lines[0].startswith("memory: the mem command")
        and " Store: " in lines[0]
        and len(lines) == INDEX_LINES
    )
    rec = json.loads((tmp_path / "d" / "hooks" / "log.jsonl").read_text().splitlines()[0])
    assert rec["source"] == "startup"


@pytest.mark.skipif(
    any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin"
)
def test_session_index_hook_without_uv_is_silent(tmp_path):
    r = subprocess.run(
        [str(HOOKS / "session-index.sh")],
        input="{}",
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not r.stdout and not r.stderr


@pytest.mark.skipif(
    any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin"
)
def test_post_compact_hook_without_uv_is_silent(tmp_path):
    summary = json.dumps({
        "compact_summary": "A summary with no block.",
        "cwd": str(tmp_path),
    })  # prints when uv is present
    r = subprocess.run(
        [str(HOOKS / "post-compact.sh")],
        input=summary,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not r.stdout and not r.stderr


def _signal_env(tmp_path, **extra):
    root = tmp_path / "proj"
    folder = root / ".memory"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "retry-keys.md").write_text(
        "---\nkind: lesson\nclaim: Retries without idempotency keys duplicate side effects\n"
        "created: 2026-11-01\nobserved: 1\nstatus: active\n---\n",
        encoding="utf-8",
    )
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "MEM_DATA": str(tmp_path / "d"),
        "XDG_CONFIG_HOME": str(tmp_path / "c"),
        "MEM_PROJECT": str(root),
        "XDG_DATA_HOME": str(tmp_path / "share"),
        **extra,
    }


def _signal(tmp_path, stdin, **extra):
    return subprocess.run(
        [str(HOOKS / "signal.sh")],
        input=stdin,
        env=_signal_env(tmp_path, **extra),
        capture_output=True,
        text=True,
        check=False,
    )


def _agent_input(prompt, tmp_path):
    return json.dumps({
        "tool_name": "Agent",
        "tool_input": {"prompt": prompt, "subagent_type": "Explore"},
        "cwd": str(tmp_path),
    })


@needs_uv
def test_signal_hook_prints_the_updated_input(tmp_path):
    brief = "Check how retries without idempotency keys duplicate side effects."
    r = _signal(tmp_path, _agent_input(brief, tmp_path))
    assert r.returncode == 0 and not r.stderr
    spec = json.loads(r.stdout)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse" and "permissionDecision" not in spec
    assert (
        spec["updatedInput"]["prompt"].startswith(brief)
        and "m:retry-keys" in spec["updatedInput"]["prompt"]
    )
    assert spec["updatedInput"]["subagent_type"] == "Explore"


@needs_uv
@pytest.mark.parametrize("stdin", ["", "not json", '{"tool_name": "Agent"}'])
def test_signal_hook_is_silent_on_bad_input(tmp_path, stdin):
    r = _signal(tmp_path, stdin)
    assert r.returncode == 0 and not r.stdout and not r.stderr


@needs_uv
def test_signal_hook_is_silent_without_a_match(tmp_path):
    r = _signal(tmp_path, _agent_input("Write a poem about the sea.", tmp_path))
    assert r.returncode == 0 and not r.stdout and not r.stderr


@pytest.mark.skipif(
    any(Path(d, "uv").exists() for d in ("/usr/bin", "/bin")), reason="uv is under /usr/bin or /bin"
)
def test_signal_hook_without_uv_is_silent(tmp_path):
    r = subprocess.run(
        [str(HOOKS / "signal.sh")],
        input=_agent_input("retries", tmp_path),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not r.stdout and not r.stderr


@pytest.mark.parametrize(
    "agent",
    [
        "memory:memory-researcher",
        "memory-recorder",
        "memory:memory-curator",
        "memory:memory-synthesizer",
        "memory:memory-status-checker",
    ],
)
def test_subagent_start_is_silent_for_the_plugins_own_agents(agent):
    r = subprocess.run(
        [str(HOOKS / "subagent-start.sh")],
        input=json.dumps({"agent_type": agent, "agent_id": "a1"}),
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not r.stdout and not r.stderr


def test_subagent_start_still_speaks_to_other_agents():
    r = subprocess.run(
        [str(HOOKS / "subagent-start.sh")],
        input=json.dumps({"agent_type": "Explore", "agent_id": "a1"}),
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] == SUBAGENT_TEXT


@needs_uv
def test_session_index_hook_finds_the_default_store(tmp_path):
    share = tmp_path / "share"
    proj = tmp_path / "p"
    proj.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "MEM_DATA": str(tmp_path / "d"),
        "XDG_CONFIG_HOME": str(tmp_path / "c"),
        "XDG_DATA_HOME": str(share),
        "MEM_PROJECT": str(proj),
    }
    assert (
        subprocess.run(
            [str(MEM), "init"], env=env, capture_output=True, text=True, check=False
        ).returncode
        == 0
    )
    r = subprocess.run(
        [str(HOOKS / "session-index.sh")],
        input=json.dumps({"cwd": str(proj), "source": "startup"}),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and not r.stderr and " Store: 0 notes." in r.stdout.split("\n")[0]


@needs_uv
def test_clearing_the_store_option_removes_the_old_config_file_and_falls_back_to_the_default(
    tmp_path,
):
    envfile = tmp_path / "env"
    envfile.write_text("")
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "c"),
        "XDG_DATA_HOME": str(tmp_path / "share"),
        "CLAUDE_ENV_FILE": str(envfile),
    }
    assert run([str(HOOK)], {**env, "CLAUDE_PLUGIN_OPTION_STORE": "/old/store"}).returncode == 0
    old = tmp_path / "c" / "agent-memory" / "store"
    assert old.read_text() == "/old/store\n"
    envfile.write_text("")
    r = run([str(HOOK)], env)  # the option is now empty
    assert r.returncode == 0 and not r.stdout and not r.stderr
    assert not old.exists()
    out = subprocess.run(
        ["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_STORE\""],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert out == str(tmp_path / "share" / "agent-memory" / "store")


def test_session_index_falls_back_to_the_fixed_rules_when_mem_cannot_run(tmp_path):
    # No uv on the path: the hook must still open the session with the rules, and they must be the engine's own.
    r = subprocess.run(
        [str(HOOKS / "session-index.sh")],
        input="{}",
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
            "MEM_DATA": str(tmp_path / "d"),
        },
        check=False,
    )
    if shutil.which("uv", path="/usr/bin:/bin"):
        pytest.skip("uv is in a system folder")
    assert r.returncode == 0 and not r.stderr
    assert r.stdout.rstrip("\n") == mem._INDEX_RULES


def _session_end(tmp_path, store, fake_git=None):
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "CLAUDE_PLUGIN_OPTION_STORE": str(store),
        "MEM_DATA": str(tmp_path / "d"),
        "XDG_CONFIG_HOME": str(tmp_path / "c"),
        "MEM_PROJECT": str(tmp_path / "p"),
        "XDG_DATA_HOME": str(tmp_path / "share"),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "gitconfig").write_text("", encoding="utf-8")
    if fake_git:
        bindir = tmp_path / "fake"
        bindir.mkdir()
        (bindir / "git").write_text(fake_git, encoding="utf-8")
        (bindir / "git").chmod(0o755)
        env["PATH"] = f"{bindir}:{env['PATH']}"
    return subprocess.run(
        [str(HOOKS / "session-end.sh")],
        input="{}",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@needs_uv
def test_session_end_hook_commits_the_store(hub_root, tmp_path):
    sys_path = str(Path(__file__).resolve().parents[1])
    subprocess.run(
        [
            "python3",
            "-c",
            (
                f"import sys; sys.path.insert(0, {sys_path!r}); from core import store_git; import pathlib; "
                f"store_git.init(pathlib.Path({str(hub_root)!r}))"
            ),
        ],
        check=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "HOME": str(tmp_path)},
    )
    (hub_root / "scratch-new.txt").write_text(
        "new\n", encoding="utf-8"
    )  # valid: an invalid note is held back
    r = _session_end(tmp_path, hub_root)
    assert r.returncode == 0 and not r.stdout and not r.stderr
    deadline = time.monotonic() + 5  # the commit runs detached from the hook
    subject = ""
    while time.monotonic() < deadline:
        subject = subprocess.run(
            ["git", "-C", str(hub_root), "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        if subject.startswith("session end "):
            break
        time.sleep(0.1)
    assert subject.startswith("session end ")
    log = tmp_path / "d" / "hooks" / "log.jsonl"
    while time.monotonic() < deadline and not (log.exists() and '"done"' in log.read_text()):
        time.sleep(0.1)  # the done record follows the commit
    hooks = [json.loads(x) for x in log.read_text().splitlines()]
    assert [x.get("phase") for x in hooks if x["hook"] == "session-end"] == ["started", "done"]
    rec = hooks[-1]
    assert rec["hook"] == "session-end" and "ms" in rec


@needs_uv
def test_session_end_hook_commits_a_valid_note_through_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("HOME", str(tmp_path))
    store = tmp_path / "store"
    monkeypatch.setenv("MEM_STORE", str(store))
    assert mem.main(["init", str(store)]) == 0
    store_git.init(store)
    folder = store / "knowledge" / "notes"
    folder.mkdir(parents=True)
    (folder / "good.md").write_text(NOTE.format(claim="good", tail=FULL_TAIL), encoding="utf-8")
    assert mem.main(["index"]) == 0
    r = _session_end(tmp_path, store)
    assert r.returncode == 0 and not r.stderr
    deadline = time.monotonic() + 10
    tracked = ""
    while time.monotonic() < deadline and "knowledge/notes/good.md" not in tracked:
        time.sleep(0.1)
        tracked = subprocess.run(
            ["git", "-C", str(store), "ls-files"], capture_output=True, text=True, check=False
        ).stdout
    assert "knowledge/notes/good.md" in tracked


@needs_uv
def test_session_end_hook_exits_0_when_git_fails(hub_root, tmp_path):
    subprocess.run(["git", "-C", str(hub_root), "init", "-q"], check=True)
    r = _session_end(tmp_path, hub_root, fake_git="#!/bin/sh\nexit 1\n")
    assert r.returncode == 0 and not r.stdout and not r.stderr


@needs_uv
@pytest.mark.skipif(shutil.which("timeout") is None, reason="no timeout command")
def test_session_end_hook_exits_0_when_git_hangs(hub_root, tmp_path):
    subprocess.run(["git", "-C", str(hub_root), "init", "-q"], check=True)
    started = time.monotonic()
    r = _session_end(tmp_path, hub_root, fake_git="#!/bin/sh\nsleep 30\n")
    assert (
        r.returncode == 0 and time.monotonic() - started < DETACHED_SECONDS
    )  # the commit is detached; its own timeout is 30 s


def _stub_plugin(tmp_path, commit_sleep):
    """A copy of the hook with stub `mem`, `mem-auto` and `mem-settle` that record their calls in order."""
    root = tmp_path / "plug"
    (root / "hooks").mkdir(parents=True)
    (root / "bin").mkdir()
    for name in ("session-end.sh", "find-claude.sh", "store-env.sh"):
        shutil.copy(HOOKS / name, root / "hooks" / name)
    order = tmp_path / "order.txt"
    stubs = {
        "mem": f'case "$*" in *"history commit"*) sleep {commit_sleep}; echo commit >> "{order}";; esac\n',
        "mem-auto": f'echo auto >> "{order}"\n',
        "mem-settle": f'echo settle >> "{order}"\n',
    }
    for name, body in stubs.items():
        (root / "bin" / name).write_text("#!/bin/sh\n" + body)
        (root / "bin" / name).chmod(0o755)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "CLAUDE_PLUGIN_OPTION_STORE": str(tmp_path),
        "CLAUDE_PLUGIN_OPTION_AUTO_CURATION": "true",
        "CLAUDE_PLUGIN_OPTION_AUTO_SETTLE": "true",
    }
    return root, env, order


def _wait_lines(path, count, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and len(path.read_text().split()) >= count:
            break
        time.sleep(0.1)
    return path.read_text().split() if path.exists() else []


def test_session_end_returns_before_commit_finishes(tmp_path):
    root, env, order = _stub_plugin(tmp_path, SLOW_COMMIT_SECONDS)
    started = time.monotonic()
    r = subprocess.run(
        [str(root / "hooks" / "session-end.sh")],
        input="{}",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and time.monotonic() - started < 1
    assert _wait_lines(order, 1, 5)[:1] == ["commit"]  # the marker appears within 5 s


def test_session_end_commits_before_auto_runs(tmp_path):
    root, env, order = _stub_plugin(tmp_path, 1)
    subprocess.run(
        [str(root / "hooks" / "session-end.sh")],
        input="{}",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = _wait_lines(order, 3)  # auto and settle start together, in no fixed order
    assert calls[0] == "commit" and sorted(calls[1:]) == ["auto", "settle"]


def test_plugin_declares_auto_capture():
    config = json.loads((Path(HOOKS).parent / ".claude-plugin" / "plugin.json").read_text())[
        "userConfig"
    ]
    assert (
        config["auto_capture"]["type"] == "boolean"
        and config["auto_capture"].get("default") is not True
    )
    assert config["auto_capture_budget"]["type"] == "number" and config["auto_capture_budget"][
        "default"
    ] == pytest.approx(DEFAULT_BUDGET)


def _capture_env(w, option, extra=None):
    """The hook's environment: the fake claude is found through CLAUDE_CODE_EXECPATH, as find-claude.sh does."""
    sleeper = w.tmp / "sleepy-claude"
    sleeper.write_text(
        FAKE.replace(
            "import json, os, shutil, sys\n",
            "import json, os, shutil, sys, time\ntime.sleep(float(os.environ.get('FAKE_SLEEP', '0')))\n",
            1,
        )
    )
    sleeper.chmod(0o755)
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"MEM_PROJECT", "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE"}
    }
    env.update({
        "CLAUDE_CODE_EXECPATH": str(sleeper),
        "FAKE_MODE": "good",
        "XDG_DATA_HOME": str(w.tmp / "share"),
        **(extra or {}),
    })
    if option is not None:
        env["CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE"] = option
    return env


def _run_hook(w, name, option, extra=None, fake_git=None):
    env = _capture_env(w, option, extra)
    if fake_git:
        bindir = w.tmp / "fakebin"
        bindir.mkdir()
        (bindir / "git").write_text(fake_git)
        (bindir / "git").chmod(0o755)
        env["PATH"] = f"{bindir}:{env['PATH']}"
    started = time.monotonic()
    done = subprocess.run(
        [str(HOOKS / name)],
        input=capture_hook(w),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return done, time.monotonic() - started


def _wait_calls(w, count, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if len(w.calls()) >= count:
            break
        time.sleep(0.1)
    return w.calls()


@needs_uv
def test_pre_compact_text_unchanged_with_capture_on(world):
    on, _ = _run_hook(world, "pre-compact.sh", "true")
    off, _ = _run_hook(world, "pre-compact.sh", None)
    assert (
        on.returncode == 0
        and off.returncode == 0
        and on.stdout == off.stdout == handoff.INSTRUCTION + "\n"
    )


@needs_uv
@pytest.mark.parametrize("name", ["pre-compact.sh", "session-end.sh"])
def test_hook_starts_capture_only_when_on(world, name):
    done, _ = _run_hook(world, name, None)
    assert done.returncode == 0
    time.sleep(1.5)
    assert world.calls() == []
    done, _ = _run_hook(world, name, "true")
    assert done.returncode == 0 and not done.stderr
    assert len(_wait_calls(world, 1)) == 1


@needs_uv
@pytest.mark.skipif(shutil.which("timeout") is None, reason="no timeout command")
def test_session_end_starts_capture_when_the_commit_hangs(world):
    store = world.tmp / "store"
    store.mkdir()
    subprocess.run(["git", "-C", str(store), "init", "-q"], check=True)
    real = shutil.which("git")  # only the store's commands hang; capture's own git calls go through
    fake = (
        f'#!/bin/sh\ncase "$*" in *status*|*commit*|*add*) sleep 30;; *) exec {real} "$@";; esac\n'
    )
    done, took = _run_hook(
        world,
        "session-end.sh",
        "true",
        extra={"CLAUDE_PLUGIN_OPTION_STORE": str(store)},
        fake_git=fake,
    )
    assert done.returncode == 0 and took < HUNG_COMMIT_SECONDS
    assert len(_wait_calls(world, 1)) == 1


@needs_uv
@pytest.mark.parametrize("name", ["pre-compact.sh", "session-end.sh"])
def test_hooks_return_fast_with_capture_on(world, name):
    done, took = _run_hook(world, name, "true", extra={"FAKE_SLEEP": "5"})
    assert done.returncode == 0 and took < DETACHED_SECONDS


def _session_index(w, option, extra=None):
    env = _capture_env(w, option, extra)
    env["MEM_PROJECT"] = str(w.project)
    return subprocess.run(
        [str(HOOKS / "session-index.sh")],
        input=capture_hook(w, transcript=w.tmp / "sessions" / "start-here.jsonl"),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _idle_session(w):
    old = w.tmp / "sessions" / "old.jsonl"
    old.write_text(
        "".join(
            json.dumps({**json.loads(x), "cwd": str(w.project)}) + "\n"
            for x in w.transcript.read_text().splitlines()
        )
    )
    stamp = time.time() - 86400
    os.utime(old, (stamp, stamp))


@needs_uv
def test_session_index_text_is_the_same_with_capture_on_and_off(world):
    on = _session_index(world, "true")
    off = _session_index(world, None)
    assert on.returncode == 0 and off.returncode == 0 and not on.stderr and not off.stderr
    assert on.stdout == off.stdout and on.stdout.startswith("memory: the mem command")


@needs_uv
def test_session_index_starts_the_sweep_only_when_on(world):
    _idle_session(world)
    off = _session_index(world, None)
    time.sleep(1.5)
    assert off.returncode == 0 and world.calls() == []
    on = _session_index(world, "true")
    assert on.returncode == 0 and on.stdout == off.stdout
    assert len(_wait_calls(world, 1)) == 1


@needs_uv
def test_session_index_exits_0_when_mem_capture_is_missing(world, tmp_path):
    plugin = tmp_path / "plugin"
    shutil.copytree(
        HOOKS.parent, plugin, ignore=shutil.ignore_patterns("tests", "__pycache__", "mem-capture")
    )
    env = _capture_env(world, "true")
    env["MEM_PROJECT"] = str(world.project)
    done = subprocess.run(
        [str(plugin / "hooks" / "session-index.sh")],
        input=capture_hook(world),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0 and done.stdout.startswith("memory: the mem command")


@needs_uv
def test_session_index_returns_fast_with_capture_on(world):
    _idle_session(world)
    started = time.monotonic()
    done = _session_index(world, "true", extra={"FAKE_SLEEP": "15"})
    assert (
        done.returncode == 0 and time.monotonic() - started < MEM_BOUND_SECONDS
    )  # mem is bounded by 4 s; the sweep is not waited on


def test_session_index_codex_fallback_has_no_auto_memory(tmp_path):
    r = subprocess.run(
        [str(HOOKS / "session-index.sh")],
        input="{}",
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
            "MEM_DATA": str(tmp_path / "d"),
            "MEM_HOST": "codex",
        },
        check=False,
    )
    if shutil.which("uv", path="/usr/bin:/bin"):
        pytest.skip("uv is in a system folder")
    assert r.returncode == 0 and not r.stderr
    assert "auto memory" not in r.stdout and "mem remember" in r.stdout
    assert f"run it as {HOOKS.parent.resolve()}/bin/mem, or install it once" in r.stdout


def test_codex_manifest_and_hooks_match_the_claude_plugin():
    root = HOOKS.parent
    claude = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    codex = json.loads((root / ".codex-plugin" / "plugin.json").read_text())
    assert codex["version"] == claude["version"] and codex["description"] == claude["description"]
    cfg = json.loads((root / codex["hooks"]).read_text())["hooks"]
    assert sorted(cfg) == ["SessionStart", "SubagentStart"]
    assert cfg["SessionStart"][0]["hooks"][0]["command"].startswith("MEM_HOST=codex ")
    assert cfg["SubagentStart"][0]["hooks"][0]["command"].startswith("MEM_HOST=codex ")
