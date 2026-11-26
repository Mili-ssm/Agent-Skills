"""`capture_state`: the state of background captures (per-session offsets, failure line, run pruning)."""

import os
import subprocess
import sys
import time
from pathlib import Path

from capture import state as capture_state
from core import jobs

OFFSET = 42
PRIVATE_FILE = 0o600
PRIVATE_DIR = 0o700
KEPT_RUNS = 20


def test_session_round_trip_and_private_modes(tmp_path):
    assert capture_state.read_session(tmp_path, "s-1") == {"offset": 0, "attempts": 0}
    capture_state.save_session(tmp_path, "s-1", OFFSET, 1)
    assert capture_state.read_session(tmp_path, "s-1")["offset"] == OFFSET
    assert capture_state.read_session(tmp_path, "s-1")["attempts"] == 1
    path = capture_state.session_path(tmp_path, "s-1")
    assert path.parent == tmp_path / "capture" / "sessions" and "s-1" not in path.name
    assert (path.stat().st_mode & 0o777) == PRIVATE_FILE
    assert (path.parent.stat().st_mode & 0o777) == PRIVATE_DIR
    assert (capture_state.capture_dir(tmp_path).stat().st_mode & 0o777) == PRIVATE_DIR


def test_an_unreadable_session_file_reads_as_zeros(tmp_path):
    capture_state.save_session(tmp_path, "s-2", 7, 1)
    capture_state.session_path(tmp_path, "s-2").write_text("{not json")
    assert capture_state.read_session(tmp_path, "s-2") == {"offset": 0, "attempts": 0}


def test_failure_line(tmp_path):
    now = time.time()
    assert capture_state.failure_line(None, now) is None
    assert capture_state.failure_line(tmp_path, now) is None
    status = capture_state.capture_dir(tmp_path) / jobs.STATUS_NAME
    jobs.private_dir(status.parent)
    jobs.write_json(
        status, {"failure": {"at": now, "reason": "no claude binary", "log": "/x/y.log"}}
    )
    line = capture_state.failure_line(tmp_path, now)
    assert line is not None
    assert (
        line.startswith("Automatic capture failed on ")
        and "no claude binary; log: /x/y.log" in line
    )
    assert line.endswith("(mem-capture ack clears this).")
    started = now - jobs.STALE_RUNNING_SECONDS - 10
    jobs.write_json(status, {"state": "running", "started": started})
    running = capture_state.failure_line(tmp_path, now)
    assert running is not None
    assert "the run did not finish" in running


def test_prune_runs_keeps_the_newest_and_drops_the_old(tmp_path):
    now = time.time()
    for i in range(22):
        folder = tmp_path / f"run-{i:02d}"
        folder.mkdir()
        os.utime(folder, (now - i * 60, now - i * 60))
    old = tmp_path / "run-old"
    old.mkdir()
    os.utime(old, (now - 15 * 86400, now - 15 * 86400))
    capture_state.prune_runs(tmp_path, capture_state.KEEP_RUNS, capture_state.KEEP_RUN_DAYS, now)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert (
        len(left) == KEPT_RUNS
        and "run-old" not in left
        and "run-00" in left
        and "run-21" not in left
    )


def test_prune_runs_age_alone_removes_an_old_folder(tmp_path):
    now = time.time()
    for name, age in (("a", 60), ("b", 120), ("old", 15 * 86400)):
        (tmp_path / name).mkdir()
        os.utime(tmp_path / name, (now - age, now - age))
    capture_state.prune_runs(tmp_path, 20, 14, now)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a", "b"]


def test_prune_runs_ignores_symlinks_and_files(tmp_path):
    now = time.time()
    runs, outside = tmp_path / "runs", tmp_path / "outside"
    runs.mkdir()
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    (runs / "link").symlink_to(outside, target_is_directory=True)
    (runs / "file.txt").write_text("x")
    for i in range(2):
        (runs / f"r{i}").mkdir()
        os.utime(runs / f"r{i}", (now - 100 - i, now - 100 - i))
    os.utime(outside, (now, now))
    capture_state.prune_runs(runs, 2, 14, now)
    assert (
        (outside / "keep.txt").exists()
        and (runs / "link").is_symlink()
        and (runs / "file.txt").exists()
    )
    assert (runs / "r0").is_dir() and (runs / "r1").is_dir()  # the link did not take a keep slot


def test_read_session_accepts_only_non_negative_ints(tmp_path):
    for bad in (True, -1, "5", [3], 2.5):
        capture_state.save_session(tmp_path, "s", 1, 1)
        jobs.write_json(capture_state.session_path(tmp_path, "s"), {"offset": bad, "attempts": bad})
        assert capture_state.read_session(tmp_path, "s") == {"offset": 0, "attempts": 0}, bad


def test_failure_line_survives_a_malformed_at(tmp_path):
    status = capture_state.capture_dir(tmp_path) / jobs.STATUS_NAME
    jobs.private_dir(status.parent)
    jobs.write_json(status, {"failure": {"at": "x", "reason": "r"}})
    now = time.time()
    line = capture_state.failure_line(tmp_path, now)
    assert line is not None
    assert line.startswith("Automatic capture failed on ") and "r; log:" in line


def test_capture_state_imports_without_yaml_records_or_capture_extract():
    engine = str(Path(capture_state.__file__).parent.parent)
    code = (
        "import sys\nfor n in ('yaml', 'memories', 'notes', 'capture.extract'):\n    sys.modules[n] = None\n"
        f"sys.path.insert(0, {engine!r})\nfrom capture import state\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
