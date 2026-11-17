"""Background settling: `bin/mem-settle`, the write-path trigger, the hooks and the session start lines."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import mem
import settle
import settle_state

PLUGIN = Path(__file__).resolve().parents[2]
SETTLE = PLUGIN / "bin" / "mem-settle"
SESSION_ENV = PLUGIN / "hooks" / "session-env.sh"
SESSION_END = PLUGIN / "hooks" / "session-end.sh"
OLD, NEW = "Use the build cache for every release build.", "Use the build cache for every release build today."

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")

FAKE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MODE", "good")
if mode in ("good", "badjson"):
    if mode == "badjson":
        open("verdicts.json", "w").write("not json")
    else:
        pairs = json.load(open("pairs.json"))
        json.dump([{"a": p["a"], "b": p["b"], "decision": "supersede", "reason": "the newer one corrects it"}
                   for p in pairs], open("verdicts.json", "w"))
if mode == "error":
    print(json.dumps({"type": "result", "is_error": True, "result": "boom", "total_cost_usd": 0.02}))
else:
    print(json.dumps({"type": "result", "is_error": False, "result": "2", "total_cost_usd": 0.03}))
"""


def put(folder, handle, claim, created):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{handle}.md").write_text(
        f"---\nkind: lesson\nclaim: {claim}\ncreated: '{created}'\nobserved: 1\nstatus: active\n---\n", encoding="utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    store = tmp_path / "store"
    subprocess.run([str(PLUGIN / "bin" / "mem"), "init", str(store)], check=True, capture_output=True, env=os.environ)
    folder = store / "memories"
    folder.mkdir(exist_ok=True)
    fake = tmp_path / "fake-claude"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    monkeypatch.setenv("FAKE_CALLS", str(tmp_path / "calls"))
    monkeypatch.setenv("MEM_STORE", str(store))
    monkeypatch.setenv("HOME", str(tmp_path))

    class World:
        pass

    w = World()
    w.store, w.folder, w.fake, w.calls, w.tmp = store, folder, fake, tmp_path / "calls", tmp_path
    w.state = settle_state.settle_dir(Path(os.environ["MEM_DATA"]), store)
    return w


def seed(w, new=True):
    """An old memory judged by the first use, then (optionally) a new look-alike."""
    put(w.folder, "old-one", OLD, "2026-11-01")
    assert mem.main(["--root", str(w.store), "settle", "log"]) == 0
    if new:
        put(w.folder, "new-one", NEW, "2026-11-16")


def settle_run(w, *args, mode="good", env=None):
    return subprocess.run([str(SETTLE), "run", "--store", str(w.store), "--claude", str(w.fake), *args],
                          env={**os.environ, "FAKE_MODE": mode, **(env or {})}, capture_output=True, text=True)


def calls(w):
    return len(w.calls.read_text().splitlines()) if w.calls.exists() else 0


def status(w):
    return json.loads((w.state / "status.json").read_text())


def wait_status(w, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        if (w.state / "status.json").exists() and status(w).get("state") in ("ok", "failed"):
            return True
        time.sleep(0.2)
    return False


def text_of(w, capsys):
    capsys.readouterr()
    assert mem.main(["--root", str(w.store), "session-index"]) == 0
    return capsys.readouterr().out


def test_a_run_with_pairs_starts_one_limited_session_and_applies_the_verdicts(world):
    seed(world)
    done = settle_run(world)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    assert calls(world) == 1
    args = json.loads(world.calls.read_text())
    assert args[args.index("--model") + 1] == "haiku" and args[args.index("--effort") + 1] == "medium"
    assert args[args.index("--max-budget-usd") + 1] == "0.2500"
    allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
    assert not any("Bash" in t for t in allowed) and [t[:5] for t in allowed] == ["Read(", "Write", "Edit("]
    s = status(world)
    assert s["state"] == "ok" and s["pairs"] == 1 and s["cost"] == pytest.approx(0.03) and "1 applied" in s["summary"]
    assert "status: superseded" in (world.folder / "old-one.md").read_text()
    assert "status: active" in (world.folder / "new-one.md").read_text()


def test_a_run_without_pairs_starts_no_session(world):
    seed(world, new=False)
    put(world.folder, "other-one", "Zebra migration windows differ per region.", "2026-11-16")
    done = settle_run(world)
    assert done.returncode == 0 and calls(world) == 0
    assert status(world)["state"] == "ok" and status(world)["pairs"] == 0


def test_nothing_new_starts_nothing_and_leaves_no_status(world):
    seed(world, new=False)
    assert settle_run(world).returncode == 0 and calls(world) == 0 and not (world.state / "status.json").exists()


@pytest.mark.parametrize("mode,why", [("nofile", "no verdicts file"), ("badjson", "not valid JSON"),
                                      ("error", "session failed")])
def test_a_bad_session_is_a_failure_that_applies_nothing_and_shows_at_session_start(world, capsys, mode, why):
    seed(world)
    settle_run(world, mode=mode)
    s = status(world)
    assert s["state"] == "failed" and why in s["reason"] and s["failure"]["reason"] == s["reason"]
    assert "status: superseded" not in (world.folder / "old-one.md").read_text()
    line = [ln for ln in text_of(world, capsys).splitlines() if ln.startswith("Automatic settling failed")]
    assert len(line) == 1 and why in line[0] and "mem-settle ack" in line[0]
    subprocess.run([str(SETTLE), "ack", "--store", str(world.store)], env=os.environ, check=True, capture_output=True)
    assert "Automatic settling failed" not in text_of(world, capsys)


def test_a_failed_run_is_not_retried_within_the_minutes(world):
    seed(world)
    settle_run(world, "--minutes", "30", mode="nofile")
    settle_run(world, "--minutes", "30")
    assert calls(world) == 1 and status(world)["state"] == "failed"
    settle_run(world, "--minutes", "0")
    assert calls(world) == 2 and status(world)["state"] == "ok"


def test_a_held_lock_makes_a_second_run_exit_silently(world):
    seed(world)
    from auto_state import take_run_lock
    fd = take_run_lock(world.state)
    try:
        done = settle_run(world)
        assert done.returncode == 0 and done.stdout == "" and done.stderr == "" and calls(world) == 0
    finally:
        os.close(fd)


def test_dry_run_starts_and_changes_nothing(world):
    seed(world)
    done = subprocess.run([str(SETTLE), "run", "--dry-run", "--store", str(world.store), "--minutes", "0"],
                          env=os.environ, capture_output=True, text=True)
    assert "would start" in done.stdout and calls(world) == 0 and not (world.state / "status.json").exists()


def test_the_session_start_text_has_one_settled_line_until_ack_or_undo(world, capsys):
    seed(world)
    settle_run(world)
    line = [ln for ln in text_of(world, capsys).splitlines() if "settled since" in ln]
    assert len(line) == 1 and "1 superseded" in line[0] and "mem settle undo <n>" in line[0] and "mem settle ack" in line[0]
    assert mem.main(["--root", str(world.store), "settle", "ack"]) == 0
    assert "settled since" not in text_of(world, capsys)


# ---- the trigger in the write path ----

@pytest.fixture
def on(monkeypatch, world):
    monkeypatch.setenv(settle_state.ENV_FLAG, "1")
    monkeypatch.setenv(settle_state.ENV_MINUTES, "30")
    monkeypatch.setenv(settle_state.ENV_CLAUDE, str(world.fake))


def remember(w, *extra, claim=NEW):
    return mem.main(["--root", str(w.store), "remember", "--global", "--kind", "lesson", "--claim", claim, *extra])


def test_a_global_write_starts_the_run_when_the_variables_are_set(world, on):
    seed(world, new=False)
    started = time.time()
    assert remember(world) == 0 and time.time() - started < 5
    assert wait_status(world) and status(world)["state"] == "ok" and calls(world) == 1


def test_a_memory_edit_starts_the_run_too(world, on, capsys):
    seed(world, new=False)
    put(world.folder, "new-one", "A different claim about zebra windows.", "2026-11-16")
    assert mem.main(["--root", str(world.store), "settle", "ack"]) == 0   # state exists; new-one is unjudged
    settle.save_state(world.folder, {**settle.load_state(world.folder), "judged": ["old-one"]})
    assert mem.main(["--root", str(world.store), "memory", "edit", "m:new-one", "--global", "--claim", NEW]) == 0
    assert wait_status(world) and calls(world) == 1


def test_no_variable_no_trigger(world, monkeypatch):
    seed(world, new=False)
    for name in (settle_state.ENV_FLAG, settle_state.ENV_MINUTES, settle_state.ENV_CLAUDE):
        monkeypatch.delenv(name, raising=False)
    assert remember(world) == 0
    time.sleep(1.5)
    assert calls(world) == 0 and not (world.state / "status.json").exists()


def test_a_pipeline_write_does_not_trigger(world, on):
    seed(world, new=False)
    assert remember(world, "--origin", "pipeline") == 0
    time.sleep(1.5)
    assert calls(world) == 0 and not (world.state / "status.json").exists()


def test_a_project_write_does_not_trigger(world, on, tmp_path, monkeypatch):
    seed(world, new=False)
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(project))
    assert mem.main(["--root", str(world.store), "remember", "--kind", "lesson", "--claim", NEW]) == 0
    time.sleep(1.5)
    assert calls(world) == 0 and not (world.state / "status.json").exists()


def test_a_broken_trigger_never_fails_the_write(world, on, monkeypatch):
    seed(world, new=False)

    def boom(*a, **k):
        raise OSError("no process")
    monkeypatch.setattr(settle_state.subprocess, "Popen", boom)
    assert remember(world) == 0
    monkeypatch.setattr(settle, "due", lambda *a, **k: 1 / 0)
    assert remember(world, claim="Another unrelated claim about zebras.") == 0


def test_a_recent_apply_keeps_the_trigger_quiet(world, on):
    seed(world, new=False)
    state = settle.load_state(world.folder)
    settle.save_state(world.folder, {**state, "last_apply": time.time()})
    assert remember(world) == 0
    time.sleep(1.5)
    assert calls(world) == 0


# ---- the hooks ----

def hook_env(w, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    return {**env, "CLAUDE_PLUGIN_OPTION_STORE": str(w.store), "CLAUDE_CODE_EXECPATH": str(w.fake), **extra}


def test_session_start_hook_exports_the_variables_and_initializes_the_state_only_when_on(world):
    put(world.folder, "old-one", OLD, "2026-11-01")
    off = world.tmp / "env-off"
    subprocess.run([str(SESSION_ENV)], env=hook_env(world, CLAUDE_ENV_FILE=str(off)), input="{}", text=True, timeout=20)
    assert "MEM_SETTLE" not in (off.read_text() if off.exists() else "")
    assert not (world.folder / settle.STATE_NAME).exists()
    on_file = world.tmp / "env-on"
    done = subprocess.run([str(SESSION_ENV)], env=hook_env(world, CLAUDE_ENV_FILE=str(on_file),
                          CLAUDE_PLUGIN_OPTION_AUTO_SETTLE="true", CLAUDE_PLUGIN_OPTION_AUTO_SETTLE_MINUTES="12"),
                          input="{}", text=True, capture_output=True, timeout=20)
    text = on_file.read_text()
    assert done.returncode == 0 and done.stdout == "" and "export MEM_SETTLE_AUTO=1" in text
    assert "MEM_SETTLE_MINUTES=12" in text and f"MEM_SETTLE_CLAUDE={world.fake}" in text
    assert "old-one" in json.loads((world.folder / settle.STATE_NAME).read_text())["judged"]


def test_session_end_hook_starts_the_run_only_when_the_option_is_true(world):
    seed(world)
    for value in ("false", ""):
        done = subprocess.run([str(SESSION_END)], env=hook_env(world, CLAUDE_PLUGIN_OPTION_AUTO_SETTLE=value),
                              input="{}", text=True, capture_output=True, timeout=20)
        assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    time.sleep(1.5)
    assert calls(world) == 0
    started = time.time()
    done = subprocess.run([str(SESSION_END)], env=hook_env(world, CLAUDE_PLUGIN_OPTION_AUTO_SETTLE="true"),
                          input="{}", text=True, capture_output=True, timeout=20)
    assert done.returncode == 0 and time.time() - started < 5
    assert wait_status(world) and status(world)["state"] == "ok" and calls(world) == 1
