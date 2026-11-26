import dataclasses
import datetime
import hashlib

import pytest
from store import records

K1 = "0123456789ab"
K2 = "ba9876543210"
TODAY = datetime.date(2026, 11, 22)


def make(tmp_path, scope="project", **kw):
    kw.setdefault("kind", "lesson")
    kw.setdefault("claim", "Retries need idempotency keys.")
    return records.write_memory(
        tmp_path / scope, scope, body="", today=TODAY, origin="transcript", **kw
    )


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
    assert key == hashlib.sha1(str(tmp_path.resolve()).encode("utf-8")).hexdigest()[:12]


def test_normalized_sources_keep_the_project():
    assert records.normalized_sources(["session a", "session a project " + K1, "https://x"]) == [
        "session a project " + K1,
        "https://x",
    ]


@pytest.mark.parametrize(
    "weight,entries,expected",
    [
        ("light", ["session a project " + K1], "unconfirmed"),
        ("light", ["session a project " + K1, "session b project " + K2], "established"),
        ("medium", ["session a project " + K1, "session b project " + K1], "unconfirmed"),
        ("strong", ["session a project " + K1, "session b project " + K2], "unconfirmed"),
        (
            "strong",
            ["session a project " + K1, "session b project " + K2, "session c project " + K2],
            "established",
        ),
        ("light", ["session a"], "unconfirmed"),
    ],
)
def test_global_standing(tmp_path, weight, entries, expected):
    m = make(tmp_path, "global", weight=weight, sources=entries)
    assert records.standing(m) == expected
    assert records.quarantined(m) == (expected == "unconfirmed")


def test_owner_confirmation_establishes(tmp_path):
    m = make(tmp_path, "global", weight="strong", sources=["session a project " + K1])
    assert records.standing(m) == "unconfirmed"
    assert records.standing(dataclasses.replace(m, owner_confirmed=TODAY)) == "established"


def test_release_marks_triage_once(tmp_path):
    m = make(
        tmp_path,
        "global",
        weight="strong",
        sources=["session a project " + K1, "session b project " + K2],
    )
    assert m.released is None and m.triage is None and m.valid_until is not None
    m, added = records.add_sighting(m, "session c project " + K1, TODAY)
    assert added and m.released == TODAY and m.triage == "pending" and m.valid_until is None
    later = TODAY + datetime.timedelta(days=3)
    m, _ = records.add_sighting(m, "session d project " + K1, later)
    assert m.released == TODAY and m.triage == "pending"


def test_write_with_two_projects_is_released(tmp_path):
    m = make(
        tmp_path,
        "global",
        weight="strong",
        sources=["session a project " + K1, "session b project " + K2, "session c project " + K1],
    )
    assert (reload(m).released, reload(m).triage, reload(m).valid_until) == (TODAY, "pending", None)
    light = make(
        tmp_path / "other",
        "global",
        weight="light",
        sources=["session a project " + K1, "session b project " + K2],
    )
    assert (reload(light).released, reload(light).triage) == (TODAY, None)


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
    m = records.update(
        m, TODAY, owner_confirmed=TODAY, released=TODAY, triage="pending", general="some-handle"
    )
    assert (m.owner_confirmed, m.released, m.triage, m.general) == (
        TODAY,
        TODAY,
        "pending",
        "some-handle",
    )
    assert records.update(m, TODAY, triage="done").triage is None


def test_entry_written_before_this_stage_loads(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    path = folder / "retries-need-keys.md"
    path.write_text(
        "---\nkind: lesson\nclaim: Retries need keys.\ncreated: '2026-11-01'\nobserved: 1\n"
        "status: active\nsources:\n- session a\n- session b\norigin: transcript\nweight: medium\n---\n"
    )
    (m,) = records.load_memories(folder, "project")
    assert m.error is None
    assert records.sessions(m) == ["session a", "session b"] and records.projects(m) == []
    assert records.standing(m) == "established"


def test_one_session_is_one_sighting():
    assert records.normalized_sources(["session a project " + K1, "Session A project " + K2]) == [
        "session a project " + K1
    ]
    assert records.normalized_sources([
        "session a",
        "session a project " + K2,
        "session a project " + K1,
    ]) == ["session a project " + K2]


def test_one_session_with_two_keys_is_one_project(tmp_path):
    m = make(
        tmp_path,
        "global",
        weight="light",
        sources=["session a project " + K1, "session a project " + K2],
    )
    assert records.standing(m) == "unconfirmed"
    m, added = records.add_sighting(m, "session a project " + K2, TODAY)
    assert not added and records.projects(m) == [K1]


def test_owner_confirmation_of_a_released_record_ends_triage(tmp_path):
    m = make(
        tmp_path,
        "global",
        weight="strong",
        sources=["session a project " + K1, "session b project " + K2, "session c project " + K1],
    )
    assert m.released == TODAY and m.triage == "pending"
    after = dataclasses.replace(m, owner_confirmed=TODAY)
    changes = records.standing_changes(m, after, TODAY)
    assert changes["triage"] is None and "released" not in changes
    assert records.update(m, TODAY, owner_confirmed=TODAY, **changes).triage is None


@pytest.mark.parametrize(
    "source", ["session a project", "session a project 0123456789ab extra", "session project"]
)
def test_a_keyed_entry_gone_wrong_is_no_sighting(source):
    assert records.sighting(source) is None and records.session_key(source) is None


def test_a_file_with_one_session_under_two_keys_counts_one_project(tmp_path):
    path = tmp_path / "two-keys.md"
    path.write_text(
        "---\nkind: lesson\nclaim: An invented lesson about two keys.\ncreated: 2026-01-01\nobserved: 1\n"
        "status: active\nsources:\n- session a project 0123456789ab\n- session a project ba9876543210\n"
        "origin: transcript\nreach: general\nweight: light\n---\n",
        encoding="utf-8",
    )
    (m,) = records.load_memories(tmp_path, "global")
    assert m.error is None and records.sessions(m) == ["session a"]
    assert records.projects(m) == ["0123456789ab"] and records.standing(m) == "unconfirmed"


def test_a_background_command_finds_the_global_folder_from_the_store_alone(tmp_path):
    store = tmp_path / "store"
    (store / records.GLOBAL_DIR).mkdir(parents=True)
    (store / records.STORE_MARKER).write_text("", encoding="utf-8")
    env = {"MEM_STORE": str(store), "HOME": str(tmp_path / "home")}
    assert records.memories_root(env, None) is None  # what the background commands used to ask
    assert records.global_memories_root(env) == store / records.GLOBAL_DIR
    default = tmp_path / "home" / ".local" / "share" / "agent-memory" / "store"
    default.mkdir(parents=True)
    (default / records.STORE_MARKER).write_text("", encoding="utf-8")
    assert (
        records.global_memories_root({"HOME": str(tmp_path / "home")})
        == default / records.GLOBAL_DIR
    )
    assert (
        records.global_memories_root({"MEM_MEMORIES": str(tmp_path / "m"), "HOME": str(tmp_path)})
        == tmp_path / "m"
    )
