"""The pure parts of the automatic fill: candidates with attempts, the key, the check's lines and verdicts."""

import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from corroborate import decide as corroborate_decide
from memories import records

TODAY = datetime.date(2026, 11, 22)
FILL_CAP = 30
ATTEMPTS_RECORDED = 2
SESSIONS_OF_STRONG = 3


@pytest.fixture(autouse=True)
def count_temp(monkeypatch):
    monkeypatch.setenv("MEM_COUNT_TEMP_PROJECTS", "1")


class World:
    project: Path
    folder: Path
    gmem: Path
    put: Callable[..., Any]
    candidates: Callable[..., Any]


@pytest.fixture
def world(tmp_path):
    w = World()
    w.project = tmp_path / "alpha"
    records.project_dir(w.project).mkdir(parents=True)
    w.folder = records.project_dir(w.project)
    w.gmem = tmp_path / "gmem"
    w.gmem.mkdir()

    def put(claim, weight="medium", scope="project", confirmed=False):
        m = records.write_memory(
            w.folder if scope == "project" else w.gmem,
            scope,
            kind="lesson",
            claim=claim,
            body="b\n",
            today=TODAY,
            sources=["session a", "session b"],
            origin="transcript",
            reach="general",
            weight=weight,
        )
        return records.update(m, TODAY, owner_confirmed=TODAY.isoformat()) if confirmed else m

    w.put = put
    w.candidates = lambda **kw: corroborate_decide.fill_candidates([w.project], w.gmem, TODAY, **kw)
    return w


def test_fill_key_is_the_same_whatever_the_registry_order(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert corroborate_decide.fill_key(None, "h1") == "g:h1"
    assert corroborate_decide.fill_key(a, "h1") == f"{records.project_key(a)}:h1"
    assert corroborate_decide.fill_key(a, "h1") != corroborate_decide.fill_key(b, "h1")


def test_candidates_drop_a_lesson_after_two_attempts_before_the_cap(world):
    for n in range(31):
        world.put(f"Invented lesson number {n} about checking a thing before using it.")
    first = world.candidates()
    assert len(first) == FILL_CAP
    _i, m = first[0]
    attempts = {
        corroborate_decide.fill_key(world.project, m.handle): {
            "digest": corroborate_decide.claim_digest(m),
            "count": corroborate_decide.FILL_ATTEMPTS,
        }
    }
    asked = world.candidates(attempts=attempts)
    assert len(asked) == FILL_CAP and m.handle not in {x.handle for _i, x in asked}
    one = {k: {**v, "count": 1} for k, v in attempts.items()}
    assert m.handle in {x.handle for _i, x in world.candidates(attempts=one)}


def test_a_changed_claim_is_a_candidate_again(world):
    m = world.put("Invented lesson about naming a branch after its task.")
    attempts = {corroborate_decide.fill_key(world.project, m.handle): {"digest": "old", "count": 5}}
    assert [x.handle for _i, x in world.candidates(attempts=attempts)] == [m.handle]


def test_a_strong_project_lesson_is_a_candidate_only_once_the_owner_confirmed_it(world):
    strong = world.put("Invented strong lesson about pinning a tool version.", weight="strong")
    assert [x.handle for _i, x in world.candidates(attempts={})] == []
    assert [x.handle for _i, x in world.candidates()] == []
    records.update(strong, TODAY, owner_confirmed=TODAY.isoformat())
    assert [x.handle for _i, x in world.candidates(attempts={})] == [strong.handle]


def test_candidates_without_attempts_are_what_they_were(world):
    strong = world.put(
        "Invented strong lesson about pinning a tool version.", weight="strong", confirmed=True
    )
    plain = world.put("Invented lesson about reading a log from the end.")
    assert {x.handle for _i, x in world.candidates()} == {strong.handle, plain.handle}
    assert (
        next(x.handle for _i, x in world.candidates(attempts={})) == strong.handle
    )  # the confirmed first, as ever


def test_validate_check_counts_only_an_exact_true():
    ids = ["a", "b", "c"]
    payload = {
        "verdicts": [
            {"id": "a", "reason": "r", "faithful": True},
            {"id": "b", "reason": "r", "faithful": "yes"},
            {"id": "c", "reason": "r", "faithful": 1},
            {"id": "zz", "reason": "r", "faithful": True},
        ]
    }
    assert corroborate_decide.validate_check(payload, ids) == {"a": True, "b": False, "c": False}


def test_validate_check_of_a_missing_or_repeated_verdict_is_none():
    ids = ["a", "b"]
    one = {"id": "a", "reason": "r", "faithful": True}
    assert corroborate_decide.validate_check({"verdicts": [one]}, ids) is None
    assert (
        corroborate_decide.validate_check({"verdicts": [one, one, {**one, "id": "b"}]}, ids) is None
    )


def test_validate_check_of_an_unusable_answer_is_none():
    for bad in ([], "text", {"verdicts": 3}, {}, None):
        assert corroborate_decide.validate_check(bad, ["a"]) is None


def test_check_lines_puts_each_field_on_one_line_and_omits_an_empty_context():
    text = corroborate_decide.check_lines([
        ("p1:x", "A claim\nover two lines", "when testing", "Short one."),
        ("g:y", "Another claim", None, "Short two."),
    ])
    assert text == (
        "id: p1:x\nclaim: A claim over two lines\ncontext: when testing\nshort: Short one.\n\n"
        "id: g:y\nclaim: Another claim\nshort: Short two.\n"
    )


def test_a_non_numeric_stored_count_counts_as_zero(world):
    m = world.put("Invented lesson about reading a log from the end.")
    for bad in ("2", None, 2.0, True, [2]):
        attempts = {
            corroborate_decide.fill_key(world.project, m.handle): {
                "digest": corroborate_decide.claim_digest(m),
                "count": bad,
            }
        }
        assert [x.handle for _i, x in world.candidates(attempts=attempts)] == [m.handle]


def test_attempt_count_reads_a_bool_or_a_foreign_digest_as_zero():
    assert corroborate_decide.attempt_count({"digest": "d", "count": True}, "d") == 0
    assert corroborate_decide.attempt_count({"digest": "x", "count": 2}, "d") == 0
    assert corroborate_decide.attempt_count(None, "d") == 0
    assert corroborate_decide.attempt_count({"digest": "d", "count": 2}, "d") == ATTEMPTS_RECORDED


def test_a_strong_project_lesson_with_three_sessions_waits_for_the_owner(world):
    strong = records.write_memory(
        world.folder,
        "project",
        kind="lesson",
        claim="Invented strong lesson about pinning a tool version.",
        body="b\n",
        today=TODAY,
        sources=["session a", "session b", "session c"],
        origin="transcript",
        reach="general",
        weight="strong",
    )
    assert len(records.sessions(strong)) == SESSIONS_OF_STRONG
    assert [x.handle for _i, x in world.candidates(attempts={})] == []
    records.update(strong, TODAY, owner_confirmed=TODAY.isoformat())
    assert [x.handle for _i, x in world.candidates(attempts={})] == [strong.handle]


def test_a_lesson_with_a_short_form_and_no_topic_is_not_a_candidate_of_the_automatic_fill(world):
    """The pass never replaces a short form: it may be one the owner read."""
    m = records.update(
        world.put("Read the plan before each task."), TODAY, short="Read the plan before each task."
    )
    assert [x.handle for _i, x in world.candidates()] == [
        m.handle
    ]  # `fill --dry-run` still proposes its topic
    assert world.candidates(attempts={}) == []
