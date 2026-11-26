"""The automatic curation run: `bin/mem-auto`, its launch from the SessionEnd hook and the failure line."""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import auto_state
import jobs
import mem
import pytest
from synthesize import pipeline as sp

PRIVATE_MODE = 0o700
RETURN_LIMIT = 5  # seconds a hook may take to return: the run must be detached
PLUGIN = Path(__file__).resolve().parents[2]
AUTO = PLUGIN / "bin" / "mem-auto"
SESSION_END = PLUGIN / "hooks" / "session-end.sh"

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
pytestmark = needs_uv

FAKE = """#!/bin/sh
echo call >> "$FAKE_CALLS"
if [ -n "$FAKE_FAIL" ]; then
  echo '{"type":"result","is_error":true,"result":"boom","total_cost_usd":0.02}'
else
  echo '{"type":"result","is_error":false,"result":"applied 0, left 0","total_cost_usd":0.05}'
fi
"""


@pytest.fixture
def world(tmp_path, hub_root):
    """A temporary store with a few global memories, a fake claude, and the environment a hook would give."""
    store = tmp_path / "store"
    subprocess.run(
        [str(PLUGIN / "bin" / "mem"), "init", str(store)],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "XDG_CONFIG_HOME": str(tmp_path / "mem-config"),
            "XDG_DATA_HOME": str(tmp_path / "mem-share"),
            "MEM_DATA": str(tmp_path / "mem-data"),
        },
    )
    (store / "memories").mkdir(exist_ok=True)
    fake = tmp_path / "fake-claude"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "MEM_DATA": os.environ["MEM_DATA"],
        "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"],
        "XDG_DATA_HOME": os.environ["XDG_DATA_HOME"],
        "MEM_PROJECT": os.environ["MEM_PROJECT"],
        "FAKE_CALLS": str(tmp_path / "calls"),
        "CLAUDE_PLUGIN_OPTION_AUTO_CURATION": "true",
    }

    w = SimpleNamespace()
    w.store, w.fake, w.env, w.calls, w.tmp = store, fake, env, tmp_path / "calls", tmp_path
    w.data = Path(env["MEM_DATA"])
    w.state = auto_state.auto_dir(w.data, store)
    return w


def memories(w, n):
    for i in range(n):
        (w.store / "memories" / f"m{i}.md").write_text(
            f"---\nkind: lesson\nclaim: claim number {i} about topic {i}\ncreated: '2026-11-01'\nobserved: 1\n"
            "status: active\n---\n",
            encoding="utf-8",
        )


def auto(w, *args, **env):
    return subprocess.run(
        [str(AUTO), *args], env={**w.env, **env}, capture_output=True, text=True, check=False
    )


def run(w, threshold="3", **env):
    return auto(
        w, "run", "--store", str(w.store), "--claude", str(w.fake), "--threshold", threshold, **env
    )


def calls(w):
    return len(w.calls.read_text().split()) if w.calls.exists() else 0


def status(w):
    return json.loads((w.state / "status.json").read_text())


def session_text(w):
    os.environ["MEM_DATA"] = str(w.data)
    return mem.session_index(
        w.store,
        None,
        None,
        __import__("datetime").date.today(),
        notice=auto_state.failure_line(w.data, w.store, time.time()),
    )


def test_the_option_off_or_not_exactly_true_starts_nothing(world):
    memories(world, 5)
    for value in (None, "false", "True", "1", ""):
        env = {k: v for k, v in world.env.items() if k != "CLAUDE_PLUGIN_OPTION_AUTO_CURATION"}
        if value is not None:
            env["CLAUDE_PLUGIN_OPTION_AUTO_CURATION"] = value
        done = subprocess.run(
            [
                str(AUTO),
                "run",
                "--store",
                str(world.store),
                "--claude",
                str(world.fake),
                "--threshold",
                "1",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0 and not done.stdout and not done.stderr
    assert calls(world) == 0 and not (world.state / "status.json").exists()


def test_under_the_threshold_nothing_runs_and_due_says_why(world):
    memories(world, 2)
    r = run(world)
    assert r.returncode == 0 and not r.stdout and calls(world) == 0
    out = auto(world, "due", "--store", str(world.store), "--threshold", "3").stdout
    assert (
        "records since the last run or pass: 2" in out
        and "threshold: 3" in out
        and "would not start" in out
    )


def test_at_the_threshold_one_run_records_status_and_cost_then_the_count_restarts(world):
    memories(world, 3)
    assert (
        "would start" in auto(world, "due", "--store", str(world.store), "--threshold", "3").stdout
    )
    r = run(world)
    assert r.returncode == 0 and not r.stdout and calls(world) == 1
    s = status(world)
    assert s["state"] == "ok" and s["cost"] == pytest.approx(0.05) and Path(s["log"]).is_file()
    out = auto(world, "due", "--store", str(world.store), "--threshold", "3").stdout
    assert "records since the last run or pass: 0" in out
    run(world)
    assert calls(world) == 1  # right after a run the count is 0
    text = auto(world, "status", "--store", str(world.store)).stdout
    assert "state ok" in text and "0.050 USD" in text


def test_a_run_that_holds_the_lock_makes_a_second_one_exit_silently(world):
    memories(world, 5)
    fd = jobs.take_run_lock(world.state)
    assert fd is not None
    try:
        r = run(world)
        assert r.returncode == 0 and not r.stdout and not r.stderr and calls(world) == 0
        assert not (world.state / "status.json").exists()
        assert (
            "a run holds the lock"
            in auto(world, "due", "--store", str(world.store), "--threshold", "1").stdout
        )
    finally:
        os.close(fd)


def test_a_failing_run_shows_one_line_in_the_session_text_until_ack(world):
    memories(world, 3)
    before = session_text(world)
    run(world, FAKE_FAIL="1")
    s = status(world)
    assert s["state"] == "failed" and "curator session failed" in s["reason"]
    shown = session_text(world)
    line = shown.splitlines()[len(before.splitlines())]
    assert line.startswith("Automatic curation failed on ") and "curator session failed" in line
    assert f"log: {s['log']} (mem-auto ack clears this)." in line
    assert (
        auto(world, "status", "--store", str(world.store)).stdout.count(
            "unacknowledged failure: yes"
        )
        == 1
    )
    assert auto(world, "ack", "--store", str(world.store)).returncode == 0
    assert session_text(world) == before  # byte-equal to the text with no failure


def test_a_success_after_a_failure_keeps_the_failure_until_ack(world):
    memories(world, 3)
    run(world, FAKE_FAIL="1")
    memories(world, 3)
    for p in (world.store / "memories").glob("*.md"):
        os.utime(p, (time.time() + 5, time.time() + 5))
    run(world)
    assert status(world)["state"] == "ok", status(world)["reason"]
    assert "Automatic curation failed" in session_text(world)


def test_a_running_status_two_hours_old_counts_as_failed_and_a_recent_one_does_not(world):
    jobs.private_dir(world.state)
    status_file = world.state / "status.json"
    base = session_text(world)
    jobs.write_json(
        status_file, {"state": "running", "started": time.time() - 600, "log": "/x/log.txt"}
    )
    assert session_text(world) == base
    jobs.write_json(
        status_file, {"state": "running", "started": time.time() - 7200, "log": "/x/log.txt"}
    )
    assert "Automatic curation failed on" in session_text(
        world
    ) and "did not finish" in session_text(world)
    assert "failed" in auto(world, "status", "--store", str(world.store)).stdout
    auto(world, "ack", "--store", str(world.store))
    assert session_text(world) == base


def test_the_subagent_start_text_has_no_failure_line(world):
    jobs.private_dir(world.state)
    jobs.write_json(
        world.state / "status.json", {"failure": {"at": time.time(), "reason": "x", "log": "/l"}}
    )
    os.environ["MEM_DATA"] = str(world.data)
    assert "Automatic curation" not in mem.signal_text([], [])


def test_state_folders_are_private(world):
    memories(world, 3)
    run(world)
    runs = list((world.state / "runs").iterdir())
    assert len(runs) == 1
    for folder in (world.state, world.state / "runs", runs[0]):
        assert stat.S_IMODE(folder.stat().st_mode) == PRIVATE_MODE, folder


def test_old_run_folders_are_pruned(world):
    memories(world, 3)
    old = world.state / "runs" / "19990101-000000"
    jobs.private_dir(old)
    past = time.time() - 31 * 86400
    os.utime(old, (past, past))
    run(world)
    assert not old.exists() and len(list((world.state / "runs").iterdir())) == 1


def test_a_run_over_its_budget_is_a_failure(world):
    memories(world, 3)
    auto(
        world,
        "run",
        "--store",
        str(world.store),
        "--claude",
        str(world.fake),
        "--threshold",
        "3",
        "--budget",
        "0.01",
    )
    s = status(world)
    assert s["state"] == "failed" and "over the budget" in s["reason"]


def test_curate_new_since_counts_memories_and_notes_and_honours_the_last_pass(
    world, monkeypatch, capsys
):
    for k, v in world.env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("MEM_PROJECT", raising=False)
    monkeypatch.setenv("MEM_PROJECT", str(world.tmp / "p"))
    memories(world, 4)
    assert mem.main(["--root", str(world.store), "curate", "--new-since", "0"]) == 0
    assert capsys.readouterr().out.strip() == "4"
    assert (
        mem.main(["--root", str(world.store), "curate", "--new-since", str(time.time() + 10)]) == 0
    )
    assert capsys.readouterr().out.strip() == "0"
    assert (
        mem.main(["--root", str(world.store), "curate", "--done"]) == 0
    )  # a pass today: its day is passed
    capsys.readouterr()
    assert mem.main(["--root", str(world.store), "curate", "--new-since", "0"]) == 0
    assert capsys.readouterr().out.strip() == "0"


# ---- the SessionEnd hook launches it ----


def hook(w, **env):
    e = {
        **w.env,
        "CLAUDE_PLUGIN_OPTION_STORE": str(w.store),
        "CLAUDE_CODE_EXECPATH": str(w.fake),
        "CLAUDE_PLUGIN_OPTION_AUTO_CURATION_THRESHOLD": "3",
        **env,
    }
    return subprocess.run(
        [str(SESSION_END)],
        input="{}",
        env=e,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def wait_status(w, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if (w.state / "status.json").exists() and status(w).get("state") in {"ok", "failed"}:
            return True
        time.sleep(0.2)
    return False


def test_session_end_hook_starts_the_run_detached_only_when_the_option_is_true(world):
    memories(world, 3)
    for value in ("false", ""):
        r = hook(world, CLAUDE_PLUGIN_OPTION_AUTO_CURATION=value)
        assert r.returncode == 0 and not r.stdout and not r.stderr
    time.sleep(1.5)
    assert calls(world) == 0 and not (world.state / "status.json").exists()
    started = time.time()
    r = hook(world)
    assert (
        r.returncode == 0 and not r.stdout and time.time() - started < RETURN_LIMIT
    )  # it returns: the run is detached
    assert wait_status(world) and status(world)["state"] == "ok" and calls(world) == 1


def test_session_end_hook_below_the_threshold_starts_no_model(world):
    memories(world, 1)
    hook(world)
    time.sleep(2)
    assert calls(world) == 0


def _session_end_done(w):
    path = w.data / "hooks" / "log.jsonl"
    if not path.exists():
        return []
    recs = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    return [r for r in recs if r.get("hook") == "session-end" and r.get("phase") == "done"]


def test_session_end_commit_skips_while_a_run_holds_the_lock(world):
    env = {**world.env, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    init = subprocess.run(
        [str(PLUGIN / "bin" / "mem"), "history", "init"],
        env={**env, "MEM_STORE": str(world.store)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert init.returncode == 0, init.stderr
    (world.store / "scratch-x.txt").write_text(
        "x\n"
    )  # a valid change: an invalid note would be held back
    held = jobs.take_run_lock(world.state)
    assert held is not None
    try:
        hook(
            world,
            CLAUDE_PLUGIN_OPTION_AUTO_CURATION="false",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
        )
        # the commit is detached: keep the lock until its run has logged that it looked and did not commit
        end = time.time() + 10
        while time.time() < end and not _session_end_done(world):
            time.sleep(0.1)
        done = _session_end_done(world)
        assert done and done[-1]["committed"] is False
    finally:
        os.close(held)
    log = subprocess.run(
        ["git", "-C", str(world.store), "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "session end" not in log
    hook(
        world,
        CLAUDE_PLUGIN_OPTION_AUTO_CURATION="false",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
    )
    deadline = time.time() + 5
    while time.time() < deadline and "session end" not in log:
        time.sleep(0.1)
        log = subprocess.run(
            ["git", "-C", str(world.store), "log", "--format=%s"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    assert "session end" in log


# ---- unknown and partial spend, per-step caps ----

NO_RESULT = '#!/bin/sh\necho call >> "$FAKE_CALLS"\necho "$@" > "$FAKE_CALLS.args"\n'


def test_a_session_without_a_result_event_ends_the_run_failed_with_no_more_sessions(world):
    memories(world, 3)
    world.fake.write_text(NO_RESULT)
    run(world)
    s = status(world)
    assert s["state"] == "failed" and s["reason"] == "a session ended without a cost report"
    assert calls(world) == 1


def test_every_session_gets_the_run_budget_as_its_cap(world):
    memories(world, 3)
    world.fake.write_text(FAKE + 'echo "$@" > "$FAKE_CALLS.args"\n')
    auto(
        world,
        "run",
        "--store",
        str(world.store),
        "--claude",
        str(world.fake),
        "--threshold",
        "3",
        "--budget",
        "0.7",
    )
    args = Path(str(world.calls) + ".args").read_text(encoding="utf-8").split()
    assert args[args.index("--max-budget-usd") + 1] == "0.7000"


def _loop(monkeypatch, tmp_path, results, left):
    sessions, ran = [], []

    def fake_session(*a, **k):
        ran.append(k.get("max_budget"))
        return {
            "writes": 0,
            "write_errors": 0,
            "denied": 0,
            "tool_errors": 0,
            "model_usage": {},
            "cost": 0.0,
            "wall": 0.0,
            "error": False,
            "answer": "",
            "has_result": True,
            **results.pop(0),
        }

    monkeypatch.setattr(sp, "run_session", fake_session)
    work = tmp_path / "w"
    work.mkdir()
    done = sp.lean_loop(
        "claude",
        {},
        tmp_path,
        tmp_path / "s",
        work,
        settings=tmp_path / "set",
        topic="t",
        sessions=sessions,
        left=left,
    )
    return done, sessions, ran


def test_the_loop_stops_when_a_session_has_no_cost_report(monkeypatch, tmp_path):
    done, sessions, ran = _loop(monkeypatch, tmp_path, [{"has_result": False}], lambda: 1.0)
    assert (
        done["why"] == "a session ended without a cost report"
        and len(sessions) == 1
        and ran == [1.0]
    )


def test_the_loop_starts_no_step_without_budget_left(monkeypatch, tmp_path):
    done, sessions, ran = _loop(monkeypatch, tmp_path, [], lambda: 0.0)
    assert done["why"] == "budget spent" and sessions == [] and ran == []


def _auto_module():
    loader = importlib.machinery.SourceFileLoader("mem_auto_under_test", str(AUTO))
    spec = importlib.util.spec_from_loader("mem_auto_under_test", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    loader.exec_module(mod)
    return mod


def test_a_failing_count_ends_in_a_failed_status_and_keeps_the_count_window(world, monkeypatch):
    mod = _auto_module()
    monkeypatch.setenv("MEM_DATA", str(world.data))
    monkeypatch.setenv("XDG_DATA_HOME", world.env["XDG_DATA_HOME"])
    monkeypatch.setenv(mod.OPTION, "true")
    monkeypatch.setattr(
        mod, "count_new", lambda *a: (_ for _ in ()).throw(RuntimeError("count broke"))
    )
    assert mod.cmd_run(world.store, str(world.fake), None, 1) == 0
    s = status(world)
    assert "count broke" in s["failure"]["reason"] and "started" not in s
    assert "Automatic curation failed" in session_text(world)
    assert not auto_state.run_lock_held(world.data, world.store)


def test_an_exception_after_a_session_still_records_what_was_spent(world, monkeypatch):
    mod = _auto_module()
    monkeypatch.setenv("MEM_DATA", str(world.data))
    monkeypatch.setenv("XDG_DATA_HOME", world.env["XDG_DATA_HOME"])
    monkeypatch.setenv(mod.OPTION, "true")
    monkeypatch.setenv("FAKE_CALLS", str(world.calls))
    memories(world, 3)
    monkeypatch.setattr(
        mod, "topics_due", lambda *a: (_ for _ in ()).throw(RuntimeError("notes broke"))
    )
    mod.cmd_run(world.store, str(world.fake), None, 3)
    s = status(world)
    assert (
        s["state"] == "failed" and "notes broke" in s["reason"] and s["cost"] == pytest.approx(0.05)
    )
