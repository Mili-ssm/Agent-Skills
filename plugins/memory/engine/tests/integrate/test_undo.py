"""`mem-integrate --undo RUN` and `status`: an undo restores a run's groups only while each is still the newest
change of every file it wrote."""

from __future__ import annotations

import json

from integrate import state as run_state
from integrate.undo import newest_is_group
from integrate_world import (  # ruff: ignore[unused-import]  (a fixture)
    LOGS,
    snapshot,
    store_with_part,
    world,
)

REFUSED = 2


def _applied(world):
    row = world.row("n-new")
    world.answers(row, row)
    world.run()
    (group,) = world.record().groups
    return group


def test_undo_restores_run_bytes(world):
    before = snapshot(world.store.root, ignore=LOGS)
    _applied(world)
    assert snapshot(world.store.root, ignore=LOGS) != before
    out = world.undo()
    assert out.rc == 0, out.err
    assert snapshot(world.store.root, ignore=LOGS) == before  # every file byte for byte
    assert world.record().groups[0].undone


def test_undo_refuses_after_live_edit_of_a_written_note(world):
    _applied(world)
    world.edit_note("n-new")
    out = world.undo()
    assert out.rc == REFUSED and "n-new" in out.err and "remaining: 1" in out.out
    assert not world.record().groups[0].undone


def test_undo_refuses_after_live_append(world):
    _applied(world)
    code = world.mem("synthesis", "append", "s:alpha#basics", "--body-file", world.live_text()).rc
    assert code == 0
    mid = snapshot(world.store.root)
    out = world.undo()
    assert out.rc == REFUSED and "alpha" in out.err
    assert snapshot(world.store.root) == mid  # refused: nothing changed, not even a log line


def test_undo_continues_after_the_refusal_is_fixed(world):
    before = snapshot(world.store.root, ignore=LOGS)
    _applied(world)
    path = world.store.note_path("n-new")
    edited = path.read_bytes()
    world.edit_note("n-new")
    assert world.undo().rc == REFUSED
    path.write_bytes(edited)  # the owner put the note back
    out = world.undo()
    assert out.rc == 0 and "remaining: 0" in out.out
    assert snapshot(world.store.root, ignore=LOGS) == before


def test_second_undo_of_a_finished_run_changes_nothing(world):
    _applied(world)
    assert world.undo().rc == 0
    mid = snapshot(world.store.root)
    out = world.undo()
    assert out.rc == 0 and "remaining: 0" in out.out
    assert snapshot(world.store.root) == mid


def test_undo_unknown_run_exit_2(world):
    out = world.undo("no-such-run")
    assert out.rc == REFUSED and "no-such-run" in out.err


def test_undo_goes_newest_group_first(world):
    world.store.add_beta()
    world.store.new_note("n-beta", "Beta takes another claim.")
    world.store.set_line("n-beta", "topics", ["algorithms"])
    alpha, beta = world.row("n-new"), world.row("n-beta", handle="beta")
    world.answers(alpha, alpha, beta, beta)
    world.run()
    groups = world.record().groups
    assert [g.handles for g in groups] == [["s:alpha"], ["s:beta"]]
    world.edit_note(
        "n-beta"
    )  # the newer group is blocked, so the older one must not be undone either
    out = world.undo()
    assert out.rc == REFUSED and "n-beta" in out.err and "remaining: 2" in out.out
    assert world.store.meta("n-new")["part_of"] == "alpha#basics"


def test_newest_is_group_names_the_file_that_moved(world):
    group = _applied(world)
    assert newest_is_group(world.store.root, group) is None
    world.edit_note("n-new")
    refusal = newest_is_group(world.store.root, group)
    assert refusal is not None and "n-new" in refusal


def test_newest_is_group_refuses_a_group_the_log_does_not_know(world):
    group = _applied(world)
    group.group_id = "0" * 32
    refusal = newest_is_group(world.store.root, group)
    assert refusal is not None and group.group_id in refusal


def test_newest_is_group_refuses_when_a_later_entry_exists(world):
    group = _applied(world)
    assert (
        world.mem("synthesis", "append", "s:alpha#basics", "--body-file", world.live_text()).rc == 0
    )
    refusal = newest_is_group(world.store.root, group)
    assert refusal is not None and "alpha" in refusal


def test_status_prints_last_run(world):
    _applied(world)
    record = world.record()
    out = world.status()
    assert out.rc == 0 and record.run_id in out.out
    assert "groups: 1" in out.out and "undone: 0" in out.out and f"{record.cost:.3f}" in out.out
    world.undo()
    assert "undone: 1" in world.status().out


def test_status_shows_failure_lines(world):
    world.answers({"answer": "boom", "error": True})
    world.run()
    out = world.status()
    assert out.rc == 0 and "failed:" in out.out and "state: failed" in out.out


def test_status_with_no_run_says_so(world):
    out = world.status()
    assert out.rc == 0 and "no run yet" in out.out


def test_record_file_stays_readable_after_undo(world):
    _applied(world)
    world.undo()
    data = json.loads((world.folder / world.record().run_id / "record.json").read_text("utf-8"))
    assert data["groups"][0]["undone"] is True
    assert run_state.read_record(world.folder, data["run_id"]) is not None
