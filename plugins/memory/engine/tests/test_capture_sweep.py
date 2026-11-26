"""`bin/mem-capture sweep`: sessions of one folder that were left open and never ended, with a fake `claude`."""

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import capture_state
import jobs
import pytest
from test_capture_auto import (
    CAPTURE,
    SPEC,
    env_of,
    lines_for,
    load_capture,
    log_lines,
    status,
    world,
)
from test_mem_capture import entry

__all__ = ["world"]  # re-exported: pytest finds the fixture in this module by its name

DAY = 86400
SHORT_LOCK_WAIT = 0.1
SPEC_LINES = len(SPEC)
SWEEP_CAP = 4
SMALL_FILE_LINES = 3
LONG_FILE_LINES = 220
TWO_SLOTS = 2
LOCK_BOUND_SECONDS = 15


def make(w, name, age: float = DAY, cwd: str | Path | None = "project", spec=SPEC):
    """A transcript next to the starting session's, last changed `age` seconds ago; its lines carry `cwd`."""
    path = w.transcript.parent / f"{name}.jsonl"
    rows = []
    for i, kind in enumerate(spec):
        row = (
            entry("user", f"Owner line {i} that asks for something concrete in the project.")
            if kind == "O"
            else entry("assistant", [{"type": "text", "text": f"Working on item {i}."}])
        )
        if cwd is not None:
            row["cwd"] = str(w.project if cwd == "project" else cwd)
        rows.append(json.dumps(row))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def start(module, w, monkeypatch, transcript=None, env=True):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps({"transcript_path": str(transcript or w.transcript), "cwd": str(w.project)})
        ),
    )
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
    assert capture_state.read_session(world.data, "idle")["offset"] == SPEC_LINES
    assert (
        capture_state.swept_size(world.data, "idle")
        == (world.transcript.parent / "idle.jsonl").stat().st_size
    )


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
    assert len(swept(world)) == capture_state.SWEEP_MAX_PER_DAY == SWEEP_CAP
    assert capture_state.sweeps_today(world.data, time.time()) == SWEEP_CAP


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


@pytest.mark.parametrize(
    "stdin",
    ["", "not json", "[]", '{"cwd": "/x"}', '{"transcript_path": "/no/such/folder/a.jsonl"}'],
)
def test_bad_input_is_quiet(world, mod, monkeypatch, stdin, capsys):
    make(world, "idle")
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    mod.sweep(str(world.fake))
    assert swept(world) == [] and capsys.readouterr() == ("", "")


def test_the_first_cwd_is_found_without_reading_the_whole_file(world, mod):
    path = make(world, "big", spec="OA")
    with path.open("a") as f:
        f.write("x" * 5_000_000 + "\n")
    assert mod.first_cwd(path) == world.project
    assert mod.count_lines(path) == SMALL_FILE_LINES


def test_the_command_exits_0_and_prints_nothing(world):
    make(world, "idle")
    done = subprocess.run(
        [sys.executable, "-I", str(CAPTURE), "sweep", "--claude", str(world.fake)],
        input=json.dumps({"transcript_path": str(world.transcript), "cwd": str(world.project)}),
        env=env_of(world),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0 and not done.stdout and not done.stderr
    assert swept(world) == ["idle"] and status(world)["state"] == "ok"


def long_file(w, name, age=DAY):
    """An idle transcript of more than three windows, every line carrying the project's `cwd`."""
    path = w.transcript.parent / f"{name}.jsonl"
    rows = [json.loads(x) for x in lines_for("O" * LONG_FILE_LINES, pad=1900).splitlines()]
    path.write_text(
        "".join(json.dumps({**row, "cwd": str(w.project)}) + "\n" for row in rows), encoding="utf-8"
    )
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def spy_reads(mod, monkeypatch):
    reads = []
    for name in ("count_lines", "first_cwd"):
        real = getattr(mod, name)
        monkeypatch.setattr(
            mod,
            name,
            lambda path, real=real, name=name: (reads.append((name, path.stem)), real(path))[1],
        )
    return reads


def test_a_file_that_needs_no_sweep_is_read_once(world, mod, monkeypatch):
    make(world, "read")
    capture_state.save_session(world.data, "read", 12, 0)
    make(world, "nocwd", cwd=None)
    reads = spy_reads(mod, monkeypatch)
    start(mod, world, monkeypatch)
    first = list(reads)
    start(mod, world, monkeypatch)
    assert reads == first and {stem for _n, stem in first} == {"read", "nocwd"}
    assert (
        capture_state.swept_size(world.data, "read")
        == (world.transcript.parent / "read.jsonl").stat().st_size
    )
    assert (
        capture_state.swept_size(world.data, "nocwd")
        == (world.transcript.parent / "nocwd.jsonl").stat().st_size
    )
    assert swept(world) == []


def test_at_most_ten_candidates_are_examined(world, mod, monkeypatch):
    for n in range(12):
        make(world, f"s{n:02d}", cwd=None, age=DAY * (1 + n / 100))
    reads = spy_reads(mod, monkeypatch)
    start(mod, world, monkeypatch)
    assert {stem for _n, stem in reads} == {f"s{n:02d}" for n in range(10)}


def test_a_long_session_continues_at_the_next_start(world, mod, monkeypatch):
    long_file(world, "long")
    start(mod, world, monkeypatch)
    first = capture_state.read_session(world.data, "long")["offset"]
    assert 0 < first < LONG_FILE_LINES and capture_state.swept_size(world.data, "long") is None
    start(mod, world, monkeypatch)
    assert capture_state.read_session(world.data, "long")["offset"] > first
    assert swept(world) == ["long", "long"]


def test_a_session_read_to_the_end_is_not_swept_again(world, mod, monkeypatch):
    make(world, "idle")
    start(mod, world, monkeypatch)
    start(mod, world, monkeypatch)
    assert swept(world) == ["idle"] and capture_state.swept_size(world.data, "idle") is not None


def test_the_first_cwd_that_exists_is_used(world, mod):
    path = make(world, "late", cwd=world.tmp / "gone")
    rows = path.read_text().splitlines()
    rows[3] = json.dumps({**json.loads(rows[3]), "cwd": str(world.project)})
    path.write_text("\n".join(rows) + "\n")
    assert mod.first_cwd(path) == world.project


def test_a_valid_cwd_after_the_first_200_lines_is_not_looked_for(world, mod):
    path = make(world, "deep", cwd=world.tmp / "gone", spec="O" * 205)
    rows = path.read_text().splitlines()
    rows[202] = json.dumps({**json.loads(rows[202]), "cwd": str(world.project)})
    path.write_text("\n".join(rows) + "\n")
    assert mod.first_cwd(path) is None


def test_a_skipped_run_does_not_use_up_the_day(world, mod, monkeypatch):
    make(world, "idle")
    monkeypatch.setenv("MEM_CAPTURE_LOCK_WAIT", "0")
    fd = jobs.take_run_lock(world.cdir)
    assert fd is not None
    try:
        start(mod, world, monkeypatch)
    finally:
        os.close(fd)
    assert capture_state.sweeps_today(world.data, time.time()) == 0
    assert capture_state.swept_size(world.data, "idle") is None


def test_a_project_without_a_memory_folder_does_not_use_up_the_day(world, mod, monkeypatch):
    other = world.tmp / "plain"
    other.mkdir()
    make(world, "idle", cwd=other)
    start(mod, world, monkeypatch)
    assert capture_state.sweeps_today(world.data, time.time()) == 0


def test_a_run_that_used_the_model_counts(world, mod, monkeypatch):
    make(world, "idle")
    start(mod, world, monkeypatch)
    assert capture_state.sweeps_today(world.data, time.time()) == 1


def plain_project(w):
    other = w.tmp / "plain"
    other.mkdir(exist_ok=True)
    return other


def test_r2_r4_files_without_a_memory_folder_do_not_hide_an_older_valid_one(
    world, mod, monkeypatch
):
    other = plain_project(world)
    make(world, "new1", age=DAY, cwd=other)
    make(world, "new2", age=DAY * 1.1, cwd=other)
    make(world, "old", age=DAY * 3)
    start(mod, world, monkeypatch)
    assert swept(world) == ["old"]
    reads = spy_reads(mod, monkeypatch)
    start(mod, world, monkeypatch)
    assert reads == []  # the two settled files and the swept one cost one stat each
    for name in ("new1", "new2"):
        assert (
            capture_state.swept_size(world.data, name)
            == (world.transcript.parent / f"{name}.jsonl").stat().st_size
        )
    assert capture_state.sweeps_today(world.data, time.time()) == 1


def test_r2_r3_unchanged_files_are_not_examined(world, mod, monkeypatch):
    for n in range(11):
        path = make(world, f"s{n:02d}", age=DAY * (1 + n / 100))
        capture_state.save_swept_size(world.data, path.stem, path.stat().st_size)
    make(world, "old", age=DAY * 3)
    reads = spy_reads(mod, monkeypatch)
    start(mod, world, monkeypatch)
    assert swept(world) == ["old"] and {stem for _n, stem in reads} == {"old"}


def test_r3_r8_twelve_files_that_need_a_run_use_two_slots(world, mod, monkeypatch):
    for n in range(12):
        make(world, f"s{n:02d}", age=DAY * (1 + n / 100))
    start(mod, world, monkeypatch)
    assert (
        swept(world) == ["s00", "s01"]
        and capture_state.sweeps_today(world.data, time.time()) == TWO_SLOTS
    )


def test_r3_r8_twelve_files_that_settle_without_a_run_are_ten_examined(world, mod, monkeypatch):
    other = plain_project(world)
    for n in range(12):
        make(world, f"s{n:02d}", cwd=other, age=DAY * (1 + n / 100))
    reads = spy_reads(mod, monkeypatch)
    start(mod, world, monkeypatch)
    assert {stem for _n, stem in reads} == {f"s{n:02d}" for n in range(10)}
    assert capture_state.sweeps_today(world.data, time.time()) == 0 and swept(world) == []


def test_r6_r7_a_too_short_file_is_settled_and_uses_no_slot(world, mod, monkeypatch):
    short = make(
        world, "short", age=DAY, spec="OAOAAAAAAAAA"
    )  # 2 owner lines: too short for a window
    make(world, "b", age=DAY * 2)
    make(world, "c", age=DAY * 3)
    start(mod, world, monkeypatch)
    assert swept(world) == ["short", "b", "c"]
    assert capture_state.swept_size(world.data, "short") == short.stat().st_size
    assert (
        capture_state.sweeps_today(world.data, time.time()) == TWO_SLOTS
    )  # only b and c ran a model session


def test_r6_a_run_without_claude_uses_no_slot(world, mod, monkeypatch):
    for n in range(3):
        make(world, f"s{n}", age=DAY * (1 + n / 10))
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"transcript_path": str(world.transcript)}))
    )
    mod.sweep(None)
    assert swept(world) == ["s0", "s1", "s2"]  # a third file was tried: no slot was used up
    assert capture_state.sweeps_today(world.data, time.time()) == 0
    assert all(capture_state.swept_size(world.data, f"s{n}") is None for n in range(3))


def test_r5_a_held_lock_ends_the_sweep_soon_and_settles_nothing(world, mod, monkeypatch):
    for n in range(3):
        make(world, f"s{n}", age=DAY * (1 + n / 10))
    monkeypatch.delenv("MEM_CAPTURE_LOCK_WAIT", raising=False)
    monkeypatch.setattr(capture_state, "SWEEP_LOCK_WAIT_SECONDS", SHORT_LOCK_WAIT)
    fd = jobs.take_run_lock(world.cdir)
    assert fd is not None
    began = time.time()
    try:
        start(mod, world, monkeypatch)
    finally:
        os.close(fd)
    assert time.time() - began < LOCK_BOUND_SECONDS
    assert [x["skipped"] for x in log_lines(world)] == [
        "another capture is running"
    ] * 3  # no slot was used
    assert capture_state.sweeps_today(world.data, time.time()) == 0
    assert all(capture_state.swept_size(world.data, f"s{n}") is None for n in range(3))


def test_r7_a_failing_run_is_not_settled_and_is_retried(world, mod, monkeypatch):
    path = make(world, "idle")
    monkeypatch.setenv("FAKE_MODE", "exit1")
    start(mod, world, monkeypatch)
    assert (
        capture_state.swept_size(world.data, "idle") is None
        and capture_state.read_session(world.data, "idle")["offset"] == 0
    )
    assert (
        capture_state.sweeps_today(world.data, time.time()) == 1
    )  # a model session ran, though it left no cost
    monkeypatch.setenv("FAKE_MODE", "good")
    start(mod, world, monkeypatch)
    assert swept(world) == ["idle", "idle"]
    assert capture_state.read_session(world.data, "idle")["offset"] == SPEC_LINES
    assert capture_state.swept_size(world.data, "idle") == path.stat().st_size
