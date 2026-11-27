"""The sweep on Codex: rollouts of all projects share one folder per day (ADR 0038)."""

import datetime
import json
import os
import subprocess
import time

import pytest
from capture import state as capture_state
from test_capture_auto import SPEC, load_capture, world
from test_capture_sweep import DAY, start, swept

__all__ = ["world"]  # re-exported: pytest finds the fixture in this module by its name


def _day_folder(w, days_ago=0):
    day = datetime.date.fromtimestamp(time.time() - days_ago * DAY)
    folder = w.tmp / "codex" / "sessions" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def rollout(w, name, days_ago=0, age=DAY, **meta):
    """A Codex rollout in the day folder `days_ago` back, last changed `age` seconds ago."""
    where = str(meta.get("cwd", w.project))
    stamp = "2026-01-01T00:00:00.000Z"
    rows = [
        {
            "timestamp": stamp,
            "type": "session_meta",
            "payload": {"id": name, "cwd": where, "thread_source": meta.get("source", "user")},
        }
    ]
    for i, kind in enumerate(SPEC):
        role, part, text = (
            (
                "user",
                "input_text",
                f"Owner line {i} that asks for something concrete in the project.",
            )
            if kind == "O"
            else ("assistant", "output_text", f"Working on item {i}.")
        )
        rows.append({
            "timestamp": stamp,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": role,
                "content": [{"type": part, "text": text}],
            },
        })
    path = _day_folder(w, days_ago) / f"rollout-{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    stamp_at = time.time() - age
    os.utime(path, (stamp_at, stamp_at))
    return path


@pytest.fixture
def mod(world, monkeypatch):
    return load_capture(monkeypatch, world, world.tmp / "started")


@pytest.fixture
def here(world):
    """The starting session: a Codex rollout of today."""
    return rollout(world, "start", age=0)


def test_sweep_on_codex_day_folder_picks_codex_sessions_only(world, mod, here, monkeypatch):
    rollout(world, "mine")
    (world.transcript.parent / "claude-one.jsonl").write_text(world.transcript.read_text())
    os.utime(world.transcript.parent / "claude-one.jsonl", (time.time() - DAY, time.time() - DAY))
    start(mod, world, monkeypatch, transcript=here)
    assert swept(world) == ["rollout-mine"]


def test_sweep_reads_previous_day_folders(world, mod, here, monkeypatch):
    rollout(world, "yesterday", days_ago=1)
    rollout(world, "five-days", days_ago=5, age=5 * DAY)
    start(mod, world, monkeypatch, transcript=here)
    assert swept(world) == ["rollout-yesterday", "rollout-five-days"]


def test_other_project_rollouts_do_not_consume_examined(world, mod, here, monkeypatch):
    elsewhere = world.tmp / "elsewhere"
    elsewhere.mkdir()
    for n in range(capture_state.SWEEP_MAX_EXAMINED + 2):
        rollout(world, f"other{n}", cwd=elsewhere, age=DAY + n)
    rollout(world, "mine", age=3 * DAY)
    start(mod, world, monkeypatch, transcript=here)
    assert swept(world) == ["rollout-mine"]


def test_subagent_rollouts_not_swept(world, mod, here, monkeypatch):
    rollout(world, "child", source="subagent")
    rollout(world, "mine", age=2 * DAY)
    start(mod, world, monkeypatch, transcript=here)
    assert swept(world) == ["rollout-mine"]


def test_sweep_skips_folder_without_memory_dir(world, monkeypatch):
    plain = world.tmp / "plain"
    plain.mkdir()
    subprocess.run(["git", "init", "-q", str(plain)], check=True)
    mod = load_capture(monkeypatch, world, world.tmp / "started")
    here = rollout(world, "start", age=0, cwd=plain)
    rollout(world, "idle", cwd=plain)
    start(mod, world, monkeypatch, transcript=here)
    assert swept(world) == [] and capture_state.sweeps_today(world.data, time.time()) == 0
    assert (
        capture_state.swept_size(world.data, "rollout-idle") is not None
    )  # settled without a model run
