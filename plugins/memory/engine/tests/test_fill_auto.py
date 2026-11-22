"""The pure parts of the automatic fill: candidates with attempts, the key, the check's lines and verdicts."""
import datetime
from pathlib import Path

import pytest

import corroborate
import records

TODAY = datetime.date(2026, 11, 22)


@pytest.fixture(autouse=True)
def count_temp(monkeypatch):
    monkeypatch.setenv("MEM_COUNT_TEMP_PROJECTS", "1")


@pytest.fixture
def world(tmp_path):
    class World:
        pass

    w = World()
    w.project = tmp_path / "alpha"
    records.project_dir(w.project).mkdir(parents=True)
    w.folder = records.project_dir(w.project)
    w.gmem = tmp_path / "gmem"
    w.gmem.mkdir()

    def put(claim, weight="medium", scope="project", confirmed=False):
        m = records.write_memory(w.folder if scope == "project" else w.gmem, scope, kind="lesson", claim=claim,
                                 body="b\n", today=TODAY, sources=["session a", "session b"], origin="transcript", reach="general",
                                 weight=weight)
        return records.update(m, TODAY, owner_confirmed=TODAY.isoformat()) if confirmed else m

    w.put = put
    w.candidates = lambda **kw: corroborate.fill_candidates([w.project], w.gmem, TODAY, **kw)
    return w


def test_fill_key_is_the_same_whatever_the_registry_order(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert corroborate.fill_key(None, "h1") == "g:h1"
    assert corroborate.fill_key(a, "h1") == f"{records.project_key(a)}:h1"
    assert corroborate.fill_key(a, "h1") != corroborate.fill_key(b, "h1")


def test_candidates_drop_a_lesson_after_two_attempts_before_the_cap(world):
    for n in range(31):
        world.put(f"Invented lesson number {n} about checking a thing before using it.")
    first = world.candidates()
    assert len(first) == 30
    _i, m = first[0]
    attempts = {corroborate.fill_key(world.project, m.handle):
                {"digest": corroborate.claim_digest(m), "count": corroborate.FILL_ATTEMPTS}}
    asked = world.candidates(attempts=attempts)
    assert len(asked) == 30 and m.handle not in {x.handle for _i, x in asked}
    one = {k: {**v, "count": 1} for k, v in attempts.items()}
    assert m.handle in {x.handle for _i, x in world.candidates(attempts=one)}


def test_a_changed_claim_is_a_candidate_again(world):
    m = world.put("Invented lesson about naming a branch after its task.")
    attempts = {corroborate.fill_key(world.project, m.handle): {"digest": "old", "count": 5}}
    assert [x.handle for _i, x in world.candidates(attempts=attempts)] == [m.handle]


def test_a_strong_project_lesson_is_a_candidate_only_once_the_owner_confirmed_it(world):
    strong = world.put("Invented strong lesson about pinning a tool version.", weight="strong")
    assert [x.handle for _i, x in world.candidates(attempts={})] == []
    assert [x.handle for _i, x in world.candidates()] == []
    records.update(strong, TODAY, owner_confirmed=TODAY.isoformat())
    assert [x.handle for _i, x in world.candidates(attempts={})] == [strong.handle]


def test_candidates_without_attempts_are_what_they_were(world):
    strong = world.put("Invented strong lesson about pinning a tool version.", weight="strong", confirmed=True)
    plain = world.put("Invented lesson about reading a log from the end.")
    assert {x.handle for _i, x in world.candidates()} == {strong.handle, plain.handle}
    assert [x.handle for _i, x in world.candidates(attempts={})][0] == strong.handle   # the confirmed first, as ever


def test_validate_check_counts_only_an_exact_true():
    ids = ["a", "b", "c", "d", "e", "f"]
    payload = {"verdicts": [
        {"id": "a", "reason": "r", "faithful": True},
        {"id": "b", "reason": "r", "faithful": "yes"},
        {"id": "c", "reason": "r", "faithful": 1},
        {"id": "e", "reason": "r", "faithful": True},
        {"id": "e", "reason": "r", "faithful": True},
        {"id": "zz", "reason": "r", "faithful": True},
    ]}
    assert corroborate.validate_check(payload, ids) == {"a": True, "b": False, "c": False, "d": False,
                                                         "e": False, "f": False}


def test_validate_check_of_an_unusable_answer_is_none():
    for bad in ([], "text", {"verdicts": 3}, {}, None):
        assert corroborate.validate_check(bad, ["a"]) is None


def test_check_lines_puts_each_field_on_one_line_and_omits_an_empty_context():
    text = corroborate.check_lines([("p1:x", "A claim\nover two lines", "when testing", "Short one."),
                                    ("g:y", "Another claim", None, "Short two.")])
    assert text == ("id: p1:x\nclaim: A claim over two lines\ncontext: when testing\nshort: Short one.\n\n"
                    "id: g:y\nclaim: Another claim\nshort: Short two.\n")
