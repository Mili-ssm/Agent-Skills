import datetime

import pytest

import records

K1 = "0123456789ab"
K2 = "ba9876543210"
TODAY = datetime.date(2026, 11, 22)


def make(tmp_path, scope="project", **kw):
    kw.setdefault("kind", "lesson")
    kw.setdefault("claim", "Retries need idempotency keys.")
    return records.write_memory(tmp_path / scope, scope, body="", today=TODAY, origin="transcript", **kw)


def reload(m):
    return records._parse(m.path, m.scope)


def test_old_entry_still_counts(tmp_path):
    m = make(tmp_path, weight="medium", sources=["session a", "Session  A", "session b"])
    assert records.sessions(m) == ["session a", "session b"] and records.projects(m) == []
    assert records.standing(m) == "established"


def test_entry_with_project():
    assert records.sighting("Session  X1 project 0123456789AB") == ("session x1", "0123456789ab")
    assert records.sighting("session x1") == ("session x1", None)
    assert records.sighting("session x1 project short") is None
    assert records.session_key("session x1 project short") is None
    assert records.session_key("session x1 project 0123456789ab") == "session x1"
    assert records.sighting_entry("session x1", "0123456789ab") == "session x1 project 0123456789ab"
    assert records.sighting_entry("session x1", None) == "session x1"


def test_project_key_is_twelve_hex_of_the_path(tmp_path):
    key = records.project_key(tmp_path)
    assert len(key) == records.PROJECT_KEY_LEN and int(key, 16) >= 0
    assert key == records.project_key(tmp_path / ".")


def test_normalized_sources_keep_the_project():
    assert records.normalized_sources(["session a", "session a project " + K1, "https://x"]) == \
        ["session a project " + K1, "https://x"]


@pytest.mark.parametrize("weight,entries,expected", [
    ("light", ["session a project " + K1], "unconfirmed"),
    ("light", ["session a project " + K1, "session b project " + K2], "established"),
    ("medium", ["session a project " + K1, "session b project " + K1], "unconfirmed"),
    ("strong", ["session a project " + K1, "session b project " + K2], "unconfirmed"),
    ("strong", ["session a project " + K1, "session b project " + K2, "session c project " + K2], "established"),
    ("light", ["session a"], "unconfirmed"),
])
def test_global_standing(tmp_path, weight, entries, expected):
    m = make(tmp_path, "global", weight=weight, sources=entries)
    assert records.standing(m) == expected
    assert records.quarantined(m) == (expected == "unconfirmed")


def test_owner_confirmation_establishes(tmp_path):
    m = make(tmp_path, "global", weight="strong", sources=["session a project " + K1])
    assert records.standing(m) == "unconfirmed"
    assert records.standing(__import__("dataclasses").replace(m, owner_confirmed=TODAY)) == "established"


def test_release_marks_triage_once(tmp_path):
    m = make(tmp_path, "global", weight="medium", sources=["session a project " + K1])
    assert m.released is None and m.triage is None and m.valid_until is not None
    m, added = records.add_sighting(m, "session b project " + K2, TODAY)
    assert added and m.released == TODAY and m.triage == "pending" and m.valid_until is None
    later = TODAY + datetime.timedelta(days=3)
    m, _ = records.add_sighting(m, "session c project " + K1, later)
    assert m.released == TODAY and m.triage == "pending"


def test_write_with_two_projects_is_released(tmp_path):
    m = make(tmp_path, "global", weight="light", sources=["session a project " + K1, "session b project " + K2])
    assert (reload(m).released, reload(m).triage, reload(m).valid_until) == (TODAY, "pending", None)


def test_project_record_never_gets_triage(tmp_path):
    m = make(tmp_path, weight="medium", sources=["session a"])
    m, _ = records.add_sighting(m, "session b", TODAY)
    assert records.standing(m) == "established"
    assert m.triage is None and m.released is None and m.valid_until is None


def test_add_sighting_adds_the_project_to_a_counted_session(tmp_path):
    m = make(tmp_path, "global", sources=["session a"])
    m, added = records.add_sighting(m, "session a project " + K1, TODAY)
    assert added and m.sources == ["session a project " + K1] and m.observed == 1
    again, added = records.add_sighting(m, "session a project " + K1, TODAY)
    assert not added and again.sources == m.sources
    _, added = records.add_sighting(m, "session a", TODAY)
    assert not added


def test_new_fields_round_trip_and_unknown_triage_is_none(tmp_path):
    m = make(tmp_path, "global", sources=["session a project " + K1])
    m = records.update(m, TODAY, owner_confirmed=TODAY, released=TODAY, triage="pending", general="some-handle")
    assert (m.owner_confirmed, m.released, m.triage, m.general) == (TODAY, TODAY, "pending", "some-handle")
    assert records.update(m, TODAY, triage="done").triage is None
