"""The run state of `mem-integrate`: the done list, the run record, and the `--new-since` skip rule."""

from __future__ import annotations

import hashlib
import json
import stat

import mem
from integrate.state import (
    GroupRecord,
    RunRecord,
    is_done,
    mark_done,
    read_done,
    read_record,
    write_done,
    write_record,
)
from integrate_store import (  # ruff: ignore[unused-import]  (fixtures)
    LONG_AGO,
    store_after_integrate,
    store_with_part,
)

CUTOFF = LONG_AGO + 1000
FAILED_COST = 0.25
OWNER_ONLY = 0o600


def test_record_lists_groups_with_handles_and_ids(tmp_path):
    record = RunRecord(
        "r1",
        "2026-11-27T10:00:00Z",
        [
            GroupRecord(["s:alpha", "n-new", "n-other"], "g1", "integrate"),
            GroupRecord(["s:beta"], "g2", "integrate", undone=True),
        ],
        FAILED_COST,
        ["budget spent"],
    )
    write_record(tmp_path, record)
    back = read_record(tmp_path, "r1")
    assert back == record
    assert back is not None
    assert back.groups[0].handles == ["s:alpha", "n-new", "n-other"]
    assert [g.group_id for g in back.groups] == ["g1", "g2"]
    assert [g.undone for g in back.groups] == [False, True]


def test_group_is_not_undone_by_default():
    assert GroupRecord(["s:a"], "g", "integrate").undone is False


def test_record_is_rewritten_with_more_groups(tmp_path):
    record = RunRecord("r1", "t", [GroupRecord(["s:a"], "g1", "integrate")], 0.0, [])
    write_record(tmp_path, record)
    record.groups.append(GroupRecord(["s:b"], "g2", "integrate"))
    write_record(tmp_path, record)
    back = read_record(tmp_path, "r1")
    assert back is not None
    assert [g.group_id for g in back.groups] == ["g1", "g2"]


def test_missing_or_broken_record_reads_as_none(tmp_path):
    assert read_record(tmp_path, "nope") is None
    write_record(tmp_path, RunRecord("r2", "t", [], 0.0, []))
    (tmp_path / "r2" / "record.json").write_text("{not json", encoding="utf-8")
    assert read_record(tmp_path, "r2") is None


def test_record_ignores_unknown_keys(tmp_path):
    record = RunRecord("r3", "t", [GroupRecord(["s:a"], "g", "integrate")], 0.0, [])
    write_record(tmp_path, record)
    path = tmp_path / "r3" / "record.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["extra"] = 1
    data["groups"][0]["extra"] = 1
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_record(tmp_path, "r3") == record


def test_state_files_are_owner_only(tmp_path):
    write_record(tmp_path, RunRecord("r4", "t", [], 0.0, []))
    mark_done(tmp_path, "n1", "d1")
    for path in (tmp_path / "r4" / "record.json", tmp_path / "done.json"):
        assert stat.S_IMODE(path.stat().st_mode) == OWNER_ONLY


def test_done_list_matches_handle_and_digest(tmp_path):
    done = read_done(tmp_path)
    assert done == {} and not is_done(done, "n1", "d1")
    mark_done(tmp_path, "n1", "d1")
    done = read_done(tmp_path)
    assert is_done(done, "n1", "d1")
    assert not is_done(done, "n1", "d2")  # the note changed since
    assert not is_done(done, "n2", "d1")


def test_done_list_survives_a_broken_file(tmp_path):
    (tmp_path / "done.json").write_text("[1, 2]", encoding="utf-8")
    assert read_done(tmp_path) == {}
    write_done(tmp_path, {"n1": "d1"})
    assert json.loads((tmp_path / "done.json").read_text(encoding="utf-8")) == {"n1": "d1"}


def _new_since(store, capsys) -> int:
    capsys.readouterr()
    assert mem.main(["--root", str(store.root), "curate", "--new-since", str(CUTOFF)]) == 0
    return int(capsys.readouterr().out.strip())


def test_new_since_skips_restamped_member(store_after_integrate, capsys):
    store = store_after_integrate
    assert store.note_path("n-new").stat().st_mtime > CUTOFF  # the command did write it
    assert _new_since(store, capsys) == 0
    # a file no integration touched keeps counting as it did: edit one after the run
    other = store.note_path("n-dup")
    other.write_text(other.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    assert _new_since(store, capsys) == 1


def test_new_since_counts_live_edit_after_run(store_after_integrate, capsys):
    store = store_after_integrate
    path = store.note_path("n-new")
    path.write_text(path.read_text(encoding="utf-8") + "\nAn owner edit.\n", encoding="utf-8")
    assert _new_since(store, capsys) == 1


def test_new_since_counts_integrate_entry_with_other_sha(store_after_integrate, capsys):
    store = store_after_integrate
    log = store.root / ".curation-log"
    entries = store.log_lines()
    for entry in entries:
        if entry["action"] == "integrate":
            entry["after"] = "0" * 64
    log.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    assert _new_since(store, capsys) == 1


def _append_entry(store, action: str) -> None:
    """A later log entry for `n-new` with `action` and the sha of the file as it is now."""
    path = store.note_path("n-new")
    handle = path.relative_to(store.root).as_posix()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    entry = {"handle": handle, "action": action, "after": sha}
    with (store.root / ".curation-log").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def test_new_since_only_the_newest_log_entry_counts(store_after_integrate, capsys):
    store = store_after_integrate
    _append_entry(store, "edit")  # newer than the integrate entry, same sha as the file
    assert _new_since(store, capsys) == 1


def test_new_since_newest_entry_must_be_an_integrate_write(store_after_integrate, capsys):
    store = store_after_integrate
    log = store.root / ".curation-log"
    entries = [e for e in store.log_lines() if e["action"] != "integrate"]
    log.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    _append_entry(store, "edit")  # no integrate entry at all, sha matches
    assert _new_since(store, capsys) == 1
