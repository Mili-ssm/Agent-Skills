"""`mem-integrate --undo RUN` and `status`: an undo restores a run's groups only while each is still the newest
change of every file it wrote."""

from __future__ import annotations

import json
from subprocess import CompletedProcess

from entry import integrate as entry
from integrate import state as run_state
from integrate import undo as run_undo
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


def _second_run(world, monkeypatch):
    """A second run that integrates one more note into the same synthesis; returns both run ids."""
    first = world.record().run_id
    monkeypatch.setattr(
        entry.os, "getpid", lambda: 99999999
    )  # run id = time + pid: keep two runs apart, the newer sorting last
    run_state.write_done(
        world.folder, {}
    )  # the first run offered n-two and marked it done; offer it again
    row = world.row("n-two")
    world.answers(
        "spent", "spent", row, row
    )  # the fake claude's counter went past the first run's two answers
    _, text = world.run()
    second = world.record().run_id
    assert second != first and len(world.record().groups) == 1, (text, world.mem_log)
    return first, second


def test_undo_two_runs_into_one_synthesis_newest_first(world, monkeypatch):
    world.store.new_note("n-two", "Alpha takes a second claim.")
    before = snapshot(world.store.root, ignore=LOGS)
    _applied(world)
    first, second = _second_run(world, monkeypatch)
    assert world.undo(second).rc == 0
    out = world.undo(first)  # the restore markers of the newer undo must not block the older group
    assert out.rc == 0, out.err
    assert snapshot(world.store.root, ignore=LOGS) == before


class FakeMem:
    """A `mem` callable that changes nothing, answers with the given exit code and text, and records its calls."""

    def __init__(self, code=0, out="", err=""):
        self.reply = (code, out, err)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *argv):
        self.calls.append(argv)
        code, out, err = self.reply
        return CompletedProcess(argv, code, out, err)


def test_undo_stops_when_restore_undid_another_change(world):
    group = _applied(world)
    mem = FakeMem(out="s:alpha\trestored to before append of 2026-11-27\n")
    result = run_undo.undo(world.store.root, world.folder, world.record().run_id, mem)
    assert result.undone == 0 and result.remaining == 1
    assert result.refusal and "another change" in result.refusal and "s:alpha" in result.refusal
    assert not world.record().groups[0].undone
    assert group.group_id in result.refusal


def test_undo_stops_when_restore_counts_other_files(world):
    _applied(world)
    mem = FakeMem(out="s:alpha\trestored to before integrate of 2026-11-27 (99 files)\n")
    result = run_undo.undo(world.store.root, world.folder, world.record().run_id, mem)
    assert result.refusal and "another change" in result.refusal
    assert not world.record().groups[0].undone


def test_undo_reports_a_partial_restore(world):
    _applied(world)
    mem = FakeMem(code=2, err="mem: disk full")
    result = run_undo.undo(world.store.root, world.folder, world.record().run_id, mem)
    assert result.undone == 0 and result.remaining == 1
    assert result.refusal and "partly restored" in result.refusal
    assert "s:alpha" in result.refusal and "disk full" in result.refusal
    assert not world.record().groups[0].undone


def test_cli_partial_restore_exits_2(world, monkeypatch):
    _applied(world)
    monkeypatch.setattr(
        entry.sp, "mem", lambda _store, _env, *a: CompletedProcess(a, 2, "", "mem: disk full")
    )
    out = world.undo()
    assert out.rc == REFUSED and "partly restored" in out.err and "remaining: 1" in out.out


def test_undo_refuses_a_group_id_the_log_does_not_know(world, monkeypatch):
    _applied(world)
    record = world.record()
    record.groups[0].group_id = "f" * 32
    run_state.write_record(world.folder, record)
    mem = FakeMem()
    monkeypatch.setattr(entry.sp, "mem", lambda _store, _env, *argv: mem(*argv))
    out = world.undo()
    assert out.rc == REFUSED and "f" * 32 in out.err
    assert not mem.calls
    assert not world.record().groups[0].undone


def test_undo_never_restores_when_the_check_refuses(world, monkeypatch):
    _applied(world)
    world.edit_note("n-new")
    calls = []
    monkeypatch.setattr(entry.sp, "mem", lambda _store, _env, *a: calls.append(a))
    assert world.undo().rc == REFUSED
    assert not calls


def test_undo_of_two_groups_refused_then_both_undone(world):
    world.store.add_beta()
    world.store.new_note("n-beta", "Beta takes another claim.")
    world.store.set_line("n-beta", "topics", ["algorithms"])
    before = snapshot(world.store.root, ignore=LOGS)
    alpha, beta = world.row("n-new"), world.row("n-beta", handle="beta")
    world.answers(alpha, alpha, beta, beta)
    world.run()
    path = world.store.note_path("n-beta")
    applied = path.read_bytes()
    world.edit_note("n-beta")
    out = world.undo()
    assert out.rc == REFUSED and "remaining: 2" in out.out and "undone: 0" in out.out
    path.write_bytes(applied)
    out = world.undo()
    assert out.rc == 0 and "undone: 2" in out.out and "remaining: 0" in out.out
    assert world.store.meta("n-new").get("part_of") != "alpha#basics"
    assert before != {}


def _log_lines(world):
    return (world.store.root / ".curation-log").read_text(encoding="utf-8").split("\n")


def _mark_restored(world, group_id, handle):
    """Appends the marker `mem restore` writes for the group's entry on `handle` (the way a restore that stopped
    after its first member leaves the log)."""
    for number, line in enumerate(_log_lines(world)):
        entry_ = json.loads(line) if line else {}
        if entry_.get("group") == group_id and entry_.get("handle") == handle:
            marker = {"action": "restore", "handle": handle, "undone": number}
            with (world.store.root / ".curation-log").open("a", encoding="utf-8") as log:
                log.write(json.dumps(marker) + "\n")
            return
    raise AssertionError(handle)


def _watch_mem(world, monkeypatch):
    mem = FakeMem()
    monkeypatch.setattr(entry.sp, "mem", lambda _store, _env, *argv: mem(*argv))
    return mem


def test_undo_refuses_a_partly_restored_group(world, monkeypatch):
    world.store.new_note("n-two", "Alpha takes a second claim.")
    _applied(world)
    _, second = _second_run(world, monkeypatch)
    (group,) = world.record().groups
    handles = [
        e["handle"]
        for e in map(json.loads, filter(None, _log_lines(world)))
        if e.get("group") == group.group_id
    ]
    (synthesis,) = [h for h in handles if "n-two" not in h]
    _mark_restored(world, group.group_id, synthesis)  # only the synthesis of the group is cancelled
    mid = snapshot(world.store.root)
    mem = _watch_mem(world, monkeypatch)
    out = world.undo(second)
    assert out.rc == REFUSED and "partly restored" in out.err and "n-two" in out.err
    assert synthesis not in out.err.split("still live:")[1]
    assert "remaining: 1" in out.out and not mem.calls
    assert snapshot(world.store.root) == mid
    assert not world.record().groups[0].undone


def test_undo_marks_an_already_restored_group_without_restoring(world, monkeypatch):
    _applied(world)
    assert world.mem("restore", "s:alpha").rc == 0  # the owner restored it by hand
    mid = snapshot(world.store.root)
    mem = _watch_mem(world, monkeypatch)
    out = world.undo()
    assert out.rc == 0, out.err
    assert "already restored" in out.out and "remaining: 0" in out.out and not mem.calls
    assert world.record().groups[0].undone
    assert snapshot(world.store.root) == mid
