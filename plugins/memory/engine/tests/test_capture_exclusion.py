"""Persistent per-transcript automatic capture exclusions."""

import os
import subprocess

from core import jobs
from test_capture_auto import CAPTURE, auto, env_of, hook, offset_of, world
from test_capture_sweep import DAY, start, swept
from test_capture_sweep_codex import here, mod, rollout

__all__ = ["here", "mod", "world"]


def exclude(world, transcript):
    return subprocess.run(
        [*CAPTURE, "exclude", "--transcript", str(transcript)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_excluded_thread_is_never_automatically_read(world, mod, here, monkeypatch):
    excluded = rollout(world, "excluded", days_ago=1)
    eligible = rollout(world, "eligible", days_ago=1, age=2 * DAY)
    before = list((world.project / ".memory").rglob("*"))
    assert exclude(world, excluded).returncode == 0
    for trigger in ("pre-compact", "session-end"):
        assert auto(world, trigger=trigger, stdin=hook(world, transcript=excluded)).returncode == 0
    start(mod, world, monkeypatch, transcript=here)
    assert swept(world) == [eligible.stem]
    assert offset_of(world, excluded) == 0
    assert len(world.calls()) == 1
    assert list((world.project / ".memory").rglob("*")) == before


def test_bad_exclusion_registry_fails_closed(world):
    world.cdir.mkdir(parents=True, exist_ok=True)
    (world.cdir / "excluded.json").write_text("{bad")
    assert auto(world).returncode == 0
    assert not world.calls()
    assert offset_of(world) == 0
    assert exclude(world, world.transcript).returncode != 0


def test_exclusion_waits_for_capture_lock(world):
    fd = jobs.take_run_lock(world.cdir)
    assert fd is not None
    try:
        done = subprocess.run(
            [*CAPTURE, "exclude", "--transcript", str(world.transcript)],
            check=False,
            env={**os.environ, "MEM_CAPTURE_LOCK_WAIT": "0"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert done.returncode != 0
    finally:
        os.close(fd)
    assert exclude(world, world.transcript).returncode == 0
    assert auto(world).returncode == 0
    assert not world.calls()


def test_queued_capture_rechecks_exclusion(world):
    process = subprocess.Popen(
        [*CAPTURE, "auto", "--trigger", "pre-compact", "--claude", str(world.fake)],
        env=env_of(world, extra={"MEM_CAPTURE_DELAY": "1"}),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    process.stdin.write(hook(world))
    process.stdin.close()
    process.stdin = None
    assert exclude(world, world.transcript).returncode == 0
    process.communicate(timeout=30)
    assert process.returncode == 0
    assert not world.calls()
    assert offset_of(world) == 0


def test_excluded_start_does_not_read_its_body(world, mod, here, monkeypatch):
    eligible = rollout(world, "eligible", days_ago=1)
    assert exclude(world, here).returncode == 0
    original = mod._first_line

    def first_line(path):
        assert path != here
        return original(path)

    monkeypatch.setattr(mod, "_first_line", first_line)
    monkeypatch.setattr(mod, "first_cwd", lambda path: world.project if path != here else None)
    start(mod, world, monkeypatch, transcript=here)
    assert swept(world) == [eligible.stem]
