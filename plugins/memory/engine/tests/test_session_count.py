import fcntl
import io
import json
import time

import pytest

import mem
import records
import session_count


def test_bump_counts_total_and_project(tmp_path):
    assert session_count.bump(tmp_path, "aaaaaaaaaaaa")["total"] == 1
    state = session_count.bump(tmp_path, "bbbbbbbbbbbb")
    assert state["total"] == 2 and state["projects"] == {"aaaaaaaaaaaa": 1, "bbbbbbbbbbbb": 1}
    assert session_count.count_for(state, "aaaaaaaaaaaa") == 1 and session_count.count_for(state, None) == 2


def test_bump_counts_showings_and_forget_returns_them(tmp_path):
    session_count.bump(tmp_path, None, ["project:k:x"], session="s1")
    session_count.bump(tmp_path, None, ["project:k:x"], session="s2")
    assert session_count.read(tmp_path)["shown"] == {"project:k:x": {"n": 2, "last": "s2"}}
    assert session_count.forget_shown(tmp_path, "project:k:x") == 2 and session_count.read(tmp_path)["shown"] == {}
    assert session_count.forget_shown(tmp_path, "project:k:x") == 0


def test_forgetting_an_absent_name_writes_nothing(tmp_path):
    assert session_count.forget_shown(tmp_path, "project:k:x") == 0
    assert not (tmp_path / "sessions.json").exists()
    session_count.bump(tmp_path, "k")
    before = (tmp_path / "sessions.json").read_text()
    assert session_count.forget_shown(tmp_path, "project:k:x") == 0
    assert (tmp_path / "sessions.json").read_text() == before


def test_a_compaction_in_the_same_session_raises_the_count_but_not_the_showing(tmp_path):
    for _ in range(3):
        state = session_count.bump(tmp_path, "k", ["project:k:x"], session="s1")
    assert state["total"] == 3 and state["shown"]["project:k:x"]["n"] == 1
    assert session_count.showings(state, "project:k:x", "s1") == 1 and session_count.showings(state, "project:k:x", "s2") == 2


def test_unwritable_or_missing_folder_returns_none_and_never_raises(tmp_path):
    assert session_count.bump(None, "k") is None
    assert session_count.forget_shown(None, "x") is None
    locked = tmp_path / "ro"
    locked.mkdir()
    locked.chmod(0o500)  # a real permission, not a patch
    try:
        assert session_count.bump(locked, "k") is None
        assert session_count.forget_shown(locked, "x") is None
    finally:
        locked.chmod(0o700)


def test_a_broken_file_reads_as_zero(tmp_path):
    (tmp_path / "sessions.json").write_text("{not json")
    assert session_count.read(tmp_path) == {"total": 0, "projects": {}, "shown": {}}
    assert session_count.bump(tmp_path, "k") is None and (tmp_path / "sessions.json").read_text() == "{not json"
    assert session_count.forget_shown(tmp_path, "x") is None and (tmp_path / "sessions.json").read_text() == "{not json"


def test_values_that_are_not_non_negative_integers_read_as_zero(tmp_path):
    (tmp_path / "sessions.json").write_text(json.dumps(
        {"total": -3, "projects": {"a": "x", "b": 2, "c": True}, "shown": {"n": {"n": 1.5, "last": 4}}}))
    assert session_count.read(tmp_path) == {"total": 0, "projects": {"a": 0, "b": 2, "c": 0},
                                            "shown": {"n": {"n": 0, "last": None}}}


def test_no_temporary_file_is_left_behind(tmp_path):
    session_count.bump(tmp_path, "k")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sessions.json", "sessions.lock"]


def test_a_held_lock_gives_up_within_a_second(tmp_path):
    with open(tmp_path / "sessions.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        for call in (lambda: session_count.bump(tmp_path, "k"), lambda: session_count.forget_shown(tmp_path, "x")):
            started = time.monotonic()
            assert call() is None
            assert time.monotonic() - started < 1.0  # at most 0.5 s each
    assert not (tmp_path / "sessions.json").exists()
    assert session_count.bump(tmp_path, "k")["total"] == 1


def hook(monkeypatch, stdin):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return mem.main(["session-index", "--hook"])


def last_log(data):
    return json.loads((data / "hooks" / "log.jsonl").read_text().splitlines()[-1])


@pytest.mark.parametrize("source,raised", [("startup", 1), ("clear", 1), ("compact", 1), ("resume", 0), (None, 0)])
def test_session_index_hook_raises_the_count_by_source(source, raised, monkeypatch, capsys, tmp_path):
    data = tmp_path / "mem-data"
    project = tmp_path / "mem-project"
    project.mkdir()
    payload = {"cwd": str(project), "session_id": "s1"}
    if source is not None:
        payload["source"] = source
    assert hook(monkeypatch, json.dumps(payload)) == 0
    state = session_count.read(data)
    assert state["total"] == raised
    assert state["projects"] == ({records.project_key(project): 1} if raised else {})
    assert last_log(data)["count"] == (raised or None)
    assert str(project) not in (data / "hooks" / "log.jsonl").read_text()


def test_session_index_without_hook_raises_nothing(monkeypatch, capsys, tmp_path):
    assert mem.main(["session-index"]) == 0
    assert not (tmp_path / "mem-data" / "sessions.json").exists()


def test_the_printed_text_does_not_change_when_the_count_cannot_be_written(monkeypatch, capsys, tmp_path):
    project = tmp_path / "mem-project"
    (project / ".memory").mkdir(parents=True)
    (project / ".memory" / "m1.md").write_text(
        "---\nkind: lesson\nclaim: a claim\ncreated: 2026-11-01\nobserved: 1\nstatus: active\n---\n", encoding="utf-8")
    payload = json.dumps({"cwd": str(project), "source": "startup"})
    hook(monkeypatch, payload)
    counted = capsys.readouterr().out
    assert "This project" in counted  # the full text, not the fallback rules
    data = tmp_path / "mem-data"
    (data / "sessions.json").write_text("{not json")
    hook(monkeypatch, payload)
    assert capsys.readouterr().out == counted
    assert last_log(data)["count"] is None


def test_readable_tells_a_missing_file_from_one_that_cannot_be_used(tmp_path):
    assert session_count.readable(None) is False
    assert session_count.readable(tmp_path) is True  # no file yet
    assert session_count.readable(tmp_path / "absent") is True
    (tmp_path / "sessions.json").write_text("{}")
    assert session_count.readable(tmp_path) is True
    (tmp_path / "sessions.json").write_text("[1]")
    assert session_count.readable(tmp_path) is False
    (tmp_path / "sessions.json").write_text("{not json")
    assert session_count.readable(tmp_path) is False
    (tmp_path / "sessions.json").write_text("{}")
    (tmp_path / "sessions.json").chmod(0)
    try:
        assert session_count.readable(tmp_path) is False
    finally:
        (tmp_path / "sessions.json").chmod(0o600)
    tmp_path.chmod(0)
    try:
        assert session_count.readable(tmp_path) is False
    finally:
        tmp_path.chmod(0o700)
