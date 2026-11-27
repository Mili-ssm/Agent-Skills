"""`mem-integrate --self-check`, the two briefs, and a session that could not read its input file."""

from __future__ import annotations

import pytest
from entry import integrate as entry
from integrate import state as run_state
from integrate_store import (  # ruff: ignore[unused-import]  (a fixture)
    store_with_part,
)
from synthesize import pipeline as sp
from test_run import world  # ruff: ignore[unused-import]  (a fixture)

UNREADABLE_ANSWERS = [
    "Permission denied: cannot open the file",
    "I cannot read the file you named.",
    "Could not read /x/place.json",
    "No such file or directory",
]


@pytest.mark.parametrize("name", ["place", "check"])
def test_briefs_fill_without_leftover_placeholders(name):
    text = sp.brief(name, briefs=entry.INTEGRATE_BRIEFS, INPUT_FILE="/work/in.json")
    assert "/work/in.json" in text and "{INPUT_FILE}" not in text


def test_self_check_passes_on_canned_answers(capsys):
    assert entry.self_check() == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "self-check passed"


@pytest.mark.parametrize("answer", UNREADABLE_ANSWERS)
def test_self_check_fails_when_a_session_could_not_read_its_file(answer, capsys):
    assert entry.self_check((answer, "none")) == 1
    out = capsys.readouterr().out
    assert "could not read its input file" in out and "self-check passed" not in out


def test_self_check_fails_on_a_flow_that_applies_nothing(capsys):
    assert entry.self_check(("none", "none")) == 1
    assert "not applied" in capsys.readouterr().out


def test_real_run_session_that_could_not_read_applies_nothing(world):
    world.answers("permission denied: /work/place.json")
    code, out = world.run()
    assert code == 0 and not world.attached("n-new")
    record = world.record()
    assert record.groups == [] and any(
        f.endswith("the session could not read its input file") for f in record.failures
    )
    assert "the session could not read its input file" in out
    assert len(world.sessions) == 1
    assert run_state.read_done(world.folder) == {}  # offered again after the permissions are fixed
