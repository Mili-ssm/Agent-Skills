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
    assert remember("--weight", "light", "--source", "session a project " + K1,
                    "--source", "session b project " + K2) == 0
    m = only(gfolder)
    assert m.released == datetime.date.today() and m.triage == "pending" and m.valid_until is None
