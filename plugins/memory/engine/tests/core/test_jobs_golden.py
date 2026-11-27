"""Golden behavior, at plan base (A3), of the job pieces that move to `jobs.py`: state folder, JSON-lines log, 30-day
prune, failure line, run lock. Every expected value is a literal, never computed by the code under test. Each row also
checks that the copies agree on the same inputs: that cross-check is Task 2 scaffolding, so Task 4 may retarget which
function a golden calls, never an expected value."""

import importlib
import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from core import auto_state, jobs
from corroborate import state as corroborate_state
from research import pipeline as research_pipeline
from settle import state as settle_state
from synthesize import run as sr

PLUGIN = Path(__file__).resolve().parents[3]
DAY = 86400
NOW = 1_700_100_000.0
FAILED_AT = 1_700_049_600  # 2023-11-15 12:00 UTC: the same date in every time zone
FAILED_DATE = "2023-11-15"
STALE_AGE = jobs.STALE_RUNNING_SECONDS + 1
LOG_MODE = 0o600
DIR_MODE = 0o700
FRESH_DAYS, OLD_DAYS = 29, 31
ENV_NAMES = ("MEM_DATA", "XDG_STATE_HOME", "HOME")


ENTRIES = {
    "mem-auto": "entry.auto",
    "mem-capture": "entry.capture",
    "mem-settle": "entry.settle",
}  # launchers: the module they run lives in `engine/entry`


def load_bin(name: str) -> ModuleType:
    if name in ENTRIES:
        return importlib.import_module(ENTRIES[name])
    path = PLUGIN / "bin" / name
    loader = importlib.machinery.SourceFileLoader(
        f"jobs_golden_{name.replace('-', '_')}", str(path)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mem_capture() -> Any:
    return load_bin("mem-capture")


@pytest.fixture(scope="module")
def mem_auto() -> Any:
    return load_bin("mem-auto")


@pytest.fixture(scope="module")
def mem_settle() -> Any:
    return load_bin("mem-settle")


@pytest.fixture(scope="module")
def mem_synthesize() -> Any:
    return sr


# ---- row 1: state folder (identical in all four copies) ----

STATE_CASES = [
    pytest.param({"MEM_DATA": "/d/data"}, "/d/data", id="mem-data"),
    pytest.param(
        {"MEM_DATA": "/d/data", "XDG_STATE_HOME": "/x", "HOME": "/h"}, "/d/data", id="mem-data-wins"
    ),
    pytest.param({"XDG_STATE_HOME": "/x/state"}, "/x/state/agent-memory", id="xdg"),
    pytest.param(
        {"XDG_STATE_HOME": "/x/state", "HOME": "/h"}, "/x/state/agent-memory", id="xdg-wins"
    ),
    pytest.param({"HOME": "/h"}, "/h/.local/state/agent-memory", id="home"),
    pytest.param(
        {"MEM_DATA": "", "HOME": "/h"}, "/h/.local/state/agent-memory", id="mem-data-empty"
    ),
    pytest.param(
        {"XDG_STATE_HOME": "", "HOME": "/h"}, "/h/.local/state/agent-memory", id="xdg-empty"
    ),
    pytest.param(
        {"MEM_DATA": "", "XDG_STATE_HOME": "/x/state"},
        "/x/state/agent-memory",
        id="mem-data-empty-xdg",
    ),
]


@pytest.mark.parametrize(("env", "expected"), STATE_CASES)
def test_state_folder_of_every_copy(monkeypatch, mem_capture, mem_synthesize, env, expected):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    # the four modules bind jobs.state_dir
    copies = [
        mem_capture.data_dir,
        corroborate_state.data_dir,
        mem_synthesize.state_dir,
        research_pipeline.state_dir,
    ]
    for copy in copies:
        assert copy() == Path(expected)


# ---- row 2: JSON-lines log (identical in two copies) ----

LOG_TEXT = '{"a": 1, "b": "é"}\n{"c": [1, 2]}\n'


def test_json_lines_log_content_and_mode(tmp_path, mem_capture):
    # both modules bind jobs.append_log
    for index, append in enumerate([mem_capture.append_log, corroborate_state.append_log]):
        folder = tmp_path / f"c{index}"
        append(folder, {"a": 1, "b": "é"})
        append(folder, {"c": [1, 2]})
        log = folder / "log.jsonl"
        assert log.read_text(encoding="utf-8") == LOG_TEXT
        assert stat.S_IMODE(log.stat().st_mode) == LOG_MODE
        assert stat.S_IMODE(folder.stat().st_mode) == DIR_MODE


# ---- row 3: 30-day prune (identical in mem-auto and mem-settle) ----


def aged_runs(runs: Path) -> None:
    for name, days in (("fresh", FRESH_DAYS), ("old", OLD_DAYS)):
        folder = runs / name
        folder.mkdir(parents=True)
        (folder / "log.txt").write_text("x")
        os.utime(folder, (NOW - days * DAY, NOW - days * DAY))
    (runs / "stray.txt").write_text("x")
    os.utime(runs / "stray.txt", (NOW - OLD_DAYS * DAY, NOW - OLD_DAYS * DAY))


@pytest.mark.parametrize("script", ["mem_auto", "mem_settle"])
def test_prune_keeps_runs_under_30_days_and_drops_older(request, monkeypatch, tmp_path, script):
    module = request.getfixturevalue(script)
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    state = module.State(tmp_path / "store")
    runs = state.dir / "runs"
    aged_runs(runs)
    module.prune(state, NOW)
    assert sorted(p.name for p in runs.iterdir()) == ["fresh", "stray.txt"]


def test_prune_without_a_runs_folder_does_nothing(monkeypatch, tmp_path, mem_auto, mem_settle):
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    for module in (mem_auto, mem_settle):
        state = module.State(tmp_path / "store")
        module.prune(state, NOW)
        assert not state.dir.exists()


# ---- row 4: failure_line (identical text shape in auto and settle) ----

AT_ISO = FAILED_DATE
FAILURE = {"at": FAILED_AT, "reason": "the  curator\nfailed", "log": "/l/log.txt"}
AUTO_FAILED = f"Automatic curation failed on {AT_ISO}: the curator failed; log: /l/log.txt (mem-auto ack clears this)."
SETTLE_FAILED = f"Automatic settling failed on {AT_ISO}: the curator failed; log: /l/log.txt (mem-settle ack clears this)."
AUTO_STALE = f"Automatic curation failed on {AT_ISO}: the run did not finish; log: /l/run.txt (mem-auto ack clears this)."
SETTLE_STALE = f"Automatic settling failed on {AT_ISO}: the run did not finish; log: /l/run.txt (mem-settle ack clears this)."
AUTO_NO_LOG = (
    f"Automatic curation failed on {AT_ISO}: boom; log: (none) (mem-auto ack clears this)."
)
SETTLE_NO_LOG = (
    f"Automatic settling failed on {AT_ISO}: boom; log: (none) (mem-settle ack clears this)."
)


def write_status(folder: Path, status: dict) -> None:
    folder.mkdir(parents=True)
    (folder / "status.json").write_text(json.dumps(status))


def failure_lines(tmp_path: Path, status: dict | None, now: float) -> tuple[str | None, str | None]:
    data, store = tmp_path / "data", tmp_path / "store"
    if status is not None:
        write_status(auto_state.auto_dir(data, store), status)
        write_status(settle_state.settle_dir(data, store), status)
    return (
        auto_state.failure_line(data, store, now),
        settle_state.failure_line(data, store, now),
    )


def test_failure_line_with_a_recorded_failure(tmp_path):
    assert failure_lines(tmp_path, {"state": "failed", "failure": FAILURE}, NOW) == (
        AUTO_FAILED,
        SETTLE_FAILED,
    )


def test_failure_line_without_a_log(tmp_path):
    status = {"failure": {"at": FAILED_AT, "reason": "boom"}}
    assert failure_lines(tmp_path, status, NOW) == (AUTO_NO_LOG, SETTLE_NO_LOG)


def test_failure_line_of_a_stale_running_state(tmp_path):
    status = {"state": "running", "started": FAILED_AT, "log": "/l/run.txt"}
    assert failure_lines(tmp_path, status, FAILED_AT + STALE_AGE) == (AUTO_STALE, SETTLE_STALE)


def test_no_failure_line_for_a_fresh_running_state(tmp_path):
    status = {"state": "running", "started": FAILED_AT}
    assert failure_lines(tmp_path, status, FAILED_AT + 1) == (None, None)


def test_no_failure_line_without_a_failure(tmp_path):
    assert failure_lines(tmp_path, {"state": "ok", "failure": None}, NOW) == (None, None)
    assert failure_lines(tmp_path / "nothing", None, NOW) == (None, None)


def test_no_failure_line_without_data_or_store(tmp_path):
    for line in (auto_state.failure_line, settle_state.failure_line):
        assert line(None, tmp_path, NOW) is None
        assert line(tmp_path, None, NOW) is None


# ---- row 5: run lock (auto_state.run_lock_held and mem-settle `_lock_held`) ----


def test_run_lock_held_only_while_the_lock_is_taken(tmp_path):
    data, store = tmp_path / "data", tmp_path / "store"
    folder = auto_state.auto_dir(data, store)
    assert auto_state.run_lock_held(data, store) is False  # no folder yet, and none is made
    assert not folder.exists()
    fd = jobs.take_run_lock(folder)
    assert fd is not None
    try:
        assert auto_state.run_lock_held(data, store) is True
    finally:
        os.close(fd)
    assert auto_state.run_lock_held(data, store) is False
    assert auto_state.run_lock_held(None, store) is False


def test_settle_lock_held_only_while_the_lock_is_taken(monkeypatch, tmp_path, mem_settle):
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    state = mem_settle.State(tmp_path / "store")
    assert mem_settle._lock_held(state) is False
    assert not state.dir.exists()
    fd = jobs.take_run_lock(state.dir)
    assert fd is not None
    try:
        assert mem_settle._lock_held(state) is True
    finally:
        os.close(fd)
    assert mem_settle._lock_held(state) is False
