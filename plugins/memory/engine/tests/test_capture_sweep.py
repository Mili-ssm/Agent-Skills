"""`bin/mem-capture sweep`: sessions of one folder that were left open and never ended, with a fake `claude`."""
import io
import json
import os
import time

import pytest

import capture_state
from test_capture_auto import (SPEC, build, load_capture, log_lines, world, status)  # noqa: F401  (the fixture)
from test_mem_capture import entry

DAY = 86400


def make(w, name, age=DAY, cwd="project", spec=SPEC, size_pad=0):
    """A transcript next to the starting session's, last changed `age` seconds ago; its lines carry `cwd`."""
    path = w.transcript.parent / f"{name}.jsonl"
    rows = []
    for i, kind in enumerate(spec):
        row = entry("user", f"Owner line {i} that asks for something concrete in the project.") if kind == "O" \
            else entry("assistant", [{"type": "text", "text": f"Working on item {i}."}])
        if cwd is not None:
            row["cwd"] = str(w.project if cwd == "project" else cwd)
        rows.append(json.dumps(row))
    path.write_text("\n".join(rows) + "\n" + "#" * size_pad, encoding="utf-8")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def start(module, w, monkeypatch, transcript=None, env=True):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"transcript_path": str(transcript or w.transcript),
                                                             "cwd": str(w.project)})))
    module.sweep(str(w.fake))


def swept(w):
    return [x["session"] for x in log_lines(w) if x["trigger"] == "sweep"]


@pytest.fixture
def mod(world, monkeypatch):
    return load_capture(monkeypatch, world, world.tmp / "started")


def test_takes_an_idle_file_with_unread_lines(world, mod, monkeypatch):
    make(world, "idle")
    start(mod, world, monkeypatch)
    assert swept(world) == ["idle"]
    assert capture_state.read_session(world.data, "idle")["offset"] == 12
    assert capture_state.swept_size(world.data, "idle") == (world.transcript.parent / "idle.jsonl").stat().st_size


def test_leaves_out_what_does_not_qualify(world, mod, monkeypatch):
    make(world, "recent", age=3600)
    make(world, "old", age=8 * DAY)
    make(world, "read")
    capture_state.save_session(world.data, "read", 12, 0)
    same = make(world, "same")
    capture_state.save_swept_size(world.data, "same", same.stat().st_size)
    make(world, "nocwd", cwd=None)
    make(world, "badcwd", cwd=world.tmp / "gone")
    (world.transcript.parent / "notes.txt").write_text("not a transcript")
    other = world.tmp / "elsewhere"
    other.mkdir()
    make_other = make(world, "elsewhere-session")
    make_other.rename(other / "elsewhere-session.jsonl")
    start(mod, world, monkeypatch)
    assert swept(world) == []


def test_never_the_starting_session(world, mod, monkeypatch):
    os.utime(world.transcript, (time.time() - DAY, time.time() - DAY))
    start(mod, world, monkeypatch)
    assert swept(world) == []


def test_at_most_two_newest_first(world, mod, monkeypatch):
    make(world, "c", age=3 * DAY)
    make(world, "a", age=DAY)
    make(world, "b", age=2 * DAY)
    start(mod, world, monkeypatch)
    assert swept(world) == ["a", "b"]


def test_a_file_that_did_not_change_is_not_swept_twice(world, mod, monkeypatch):
    make(world, "idle", spec="OAOAOAOAOAAA")
    capture_state.save_session(world.data, "idle", 0, 0)
    start(mod, world, monkeypatch)
    start(mod, world, monkeypatch)
    assert swept(world) == ["idle"]


def test_a_file_that_grew_is_swept_again(world, mod, monkeypatch):
    path = make(world, "idle")
    start(mod, world, monkeypatch)
    make(world, "idle", spec="OAOAOAOAOAAAOAOAOA")
    start(mod, world, monkeypatch)
    assert swept(world) == ["idle", "idle"] and path.is_file()


def test_the_cap_per_day(world, mod, monkeypatch):
    for n in range(6):
        make(world, f"s{n}", age=DAY * (1 + n / 10))
    start(mod, world, monkeypatch)
    start(mod, world, monkeypatch)
    start(mod, world, monkeypatch)
    assert len(swept(world)) == capture_state.SWEEP_MAX_PER_DAY == 4
    assert capture_state.sweeps_today(world.data, time.time()) == 4


def test_the_cap_restarts_the_next_utc_day(world, mod, monkeypatch):
    make(world, "idle")
    day = world.cdir / capture_state.SWEEP_DAY_NAME
    day.parent.mkdir(parents=True, exist_ok=True)
    day.write_text(json.dumps({"day": "2000-01-01", "count": 99}))
    start(mod, world, monkeypatch)
    assert swept(world) == ["idle"]


def test_option_off_does_nothing(world, mod, monkeypatch):
    make(world, "idle")
    monkeypatch.delenv(capture_state.OPTION)
    start(mod, world, monkeypatch)
    assert swept(world) == [] and not world.cdir.exists()


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"cwd": "/x"}', '{"transcript_path": "/no/such/folder/a.jsonl"}'])
def test_bad_input_is_quiet(world, mod, monkeypatch, stdin, capsys):
    make(world, "idle")
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    mod.sweep(str(world.fake))
    assert swept(world) == [] and capsys.readouterr() == ("", "")


def test_the_first_cwd_is_found_without_reading_the_whole_file(world, mod):
    path = make(world, "big", spec="OA", size_pad=0)
    with path.open("a") as f:
        f.write("x" * 5_000_000 + "\n")
    assert mod.first_cwd(path) == world.project
    assert mod.count_lines(path) == 3


def test_the_command_exits_0_and_prints_nothing(world):
    import subprocess
    import sys
    from test_capture_auto import CAPTURE, env_of
    make(world, "idle")
    done = subprocess.run([sys.executable, "-I", str(CAPTURE), "sweep", "--claude", str(world.fake)],
                          input=json.dumps({"transcript_path": str(world.transcript), "cwd": str(world.project)}),
                          env=env_of(world), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    assert swept(world) == ["idle"] and status(world)["state"] == "ok"
