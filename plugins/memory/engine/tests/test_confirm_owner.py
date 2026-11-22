import datetime
import subprocess

import pytest

import mem
import records

K1 = "0123456789ab"
K2 = "ba9876543210"
CLAIM = "Retries need idempotency keys."


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return folder


def remember(*extra):
    return mem.main(["remember", "--global", "--kind", "lesson", "--claim", CLAIM, "--origin", "transcript", *extra])


def only(folder):
    (m,) = records.load_memories(folder, "global")
    return m


def test_by_owner_releases_a_quarantined_record(gfolder):
    assert remember("--weight", "strong", "--source", "session s project " + K1) == 0
    m = only(gfolder)
    assert records.quarantined(m) and m.valid_until is not None
    assert mem.main(["confirm", "--global", m.handle, "--by-owner"]) == 0
    m = only(gfolder)
    assert m.owner_confirmed == datetime.date.today() and m.released == datetime.date.today()
    assert m.triage is None and m.valid_until is None and not records.quarantined(m)
    assert mem.main(["confirm", "--global", m.handle, "--by-owner"]) == 3


def test_confirm_source_adds_the_project(gfolder):
    assert remember("--source", "session s") == 0
    handle = only(gfolder).handle
    args = ["confirm", "--global", handle, "--source", "session s project " + K1]
    assert mem.main(args) == 0
    assert only(gfolder).sources == ["session s project " + K1]
    assert mem.main(args) == 3


def test_remember_again_adds_the_keyed_entry(gfolder):
    assert remember("--source", "session s") == 0
    assert remember("--source", "session s project " + K1) == 3
    assert only(gfolder).sources == ["session s project " + K1]
    assert remember("--source", "session s project " + K1) == 3
    assert only(gfolder).observed == 1


def test_remember_with_two_projects_is_released(gfolder):
    assert remember("--weight", "strong", "--source", "session a project " + K1,
                    "--source", "session b project " + K2, "--source", "session c project " + K1) == 0
    m = only(gfolder)
    assert m.released == datetime.date.today() and m.triage == "pending" and m.valid_until is None


def test_by_owner_on_a_released_record_ends_triage(gfolder):
    assert remember("--weight", "strong", "--source", "session a project " + K1,
                    "--source", "session b project " + K2, "--source", "session c project " + K1) == 0
    m = only(gfolder)
    assert m.triage == "pending"
    released = m.released
    assert mem.main(["confirm", "--global", m.handle, "--by-owner"]) == 0
    m = only(gfolder)
    assert m.triage is None and m.released == released and m.owner_confirmed == datetime.date.today()


def test_by_owner_refuses_an_inactive_record(gfolder, capsys):
    assert remember("--source", "session s project " + K1) == 0
    handle = only(gfolder).handle
    assert mem.main(["refute", "--global", handle]) == 0
    assert mem.main(["confirm", "--global", handle, "--by-owner"]) == 2
    assert "refuted" in capsys.readouterr().err
    assert only(gfolder).owner_confirmed is None


def test_merge_of_one_session_with_two_keys_is_one_project(gfolder):
    assert remember("--weight", "light", "--source", "session a project " + K1) == 0
    assert mem.main(["remember", "--global", "--kind", "lesson", "--claim", "Other claim entirely about queues.",
                     "--origin", "transcript", "--weight", "light", "--source", "session a project " + K2]) == 0
    keep, drop = sorted(records.load_memories(gfolder, "global"), key=lambda m: m.claim != CLAIM)
    assert mem.main(["merge", "--global", keep.handle, drop.handle, "--force"]) == 0
    (m,) = [x for x in records.load_memories(gfolder, "global") if x.status == "active"]
    assert records.sessions(m) == ["session a"] and len(records.projects(m)) == 1
    assert records.standing(m) == "unconfirmed" and m.triage is None


@pytest.mark.parametrize("source", ["session a project short", "session a project " + K1 + "zz"])
def test_remember_refuses_a_malformed_sighting(gfolder, capsys, source):
    assert remember("--source", source) == 2
    assert "session <id>" in capsys.readouterr().err
    assert records.load_memories(gfolder, "global") == []
