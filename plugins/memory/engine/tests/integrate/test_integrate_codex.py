"""`mem-integrate run` on the Codex runner (ADR 0037): a fake `codex` answers from a queue, read-only."""

from __future__ import annotations

from pathlib import Path

import codex_fake
import pytest
from core import runner as runners
from integrate_world import (  # ruff: ignore[unused-import]  (a fixture)
    store_with_part,
    world,
)

TOKENS = 1000
SESSIONS = 2
USAGE_ERROR = 2


@pytest.fixture
def codex(world, monkeypatch):
    return codex_fake.install(world.tmp, monkeypatch)


def test_codex_run_applies_the_rows_and_records_tokens_and_runner(world, codex):
    row = world.row("n-new")
    codex.plan({"answer": row, "tokens": TOKENS}, {"answer": row, "tokens": TOKENS})
    code, out = world.run()
    assert code == 0 and world.attached("n-new")
    record = world.record()
    assert (record.runner, record.tokens, record.cost) == ("codex", SESSIONS * TOKENS, 0.0)
    assert "tokens: 2000 of 500000 (codex)" in out
    assert "tokens=1000" in world.mem_log
    assert [c["argv"][c["argv"].index("-s") + 1] for c in codex.calls] == ["read-only"] * SESSIONS


def test_codex_environment_has_home_in_the_run_folder_and_no_store(world, codex):
    row = world.row("n-new")
    codex.plan({"answer": row}, {"answer": row})
    world.run()
    for call in codex.calls:
        assert Path(call["env"]["HOME"]).parent == Path(call["cwd"])
        assert "MEM_STORE" not in call["env"]


@pytest.mark.parametrize("step", [{"silent": True, "exit": 1}, {"answer": None}])
def test_a_codex_session_without_a_result_ends_the_run_like_a_missing_cost(world, codex, step):
    codex.plan(step)
    code, out = world.run()
    assert code == 0 and "failed: place session ended without a result" in out
    assert len(codex.calls) == 1 and not world.attached("n-new")


@pytest.mark.parametrize(
    ("step", "shown"),
    [
        ({"failed": "model overloaded", "exit": 1}, "model overloaded; exit 1"),
        ({"error": "quota exceeded", "stderr": "rate limited", "exit": 3}, "stderr: rate limited"),
    ],
)
def test_the_codex_failure_reason_reaches_the_failure_line(world, codex, step, shown):
    codex.plan(step)
    _, out = world.run()
    assert "place session ended without a result: " in out and shown in out


def test_a_codex_timeout_reaches_the_failure_line(world, codex, monkeypatch):
    monkeypatch.setattr(
        runners, "run_codex", lambda *a, **k: runners.CodexRaw("", True, None, "slow")
    )
    _, out = world.run()
    assert "the session timed out" in out


def test_the_token_cap_stops_the_second_session(world, codex, monkeypatch):
    monkeypatch.setenv("MEM_CODEX_TOKENS", str(TOKENS))
    row = world.row("n-new")
    codex.plan({"answer": row, "tokens": TOKENS}, {"answer": row, "tokens": TOKENS})
    _, out = world.run()
    assert "budget spent" in out and len(codex.calls) == 1
    assert not world.attached("n-new") and world.record().groups == []


def test_a_malformed_runner_setting_is_a_usage_error(world, monkeypatch):
    monkeypatch.setenv("MEM_RUNNER", "gemini")
    done = world._main("run")
    assert done.rc == USAGE_ERROR and "runner 'gemini'" in done.err


def test_the_flag_beats_mem_runner(world, codex, monkeypatch):
    monkeypatch.setenv("MEM_RUNNER", "claude")
    row = world.row("n-new")
    codex.plan({"answer": row}, {"answer": row})
    code, _ = world.run("--runner", "codex")
    assert code == 0 and world.record().runner == "codex"


def test_the_plugin_option_alone_picks_codex(world, codex, monkeypatch):
    monkeypatch.delenv("MEM_RUNNER")
    monkeypatch.setenv("MEM_RUNNER_OPTION", "codex")
    row = world.row("n-new")
    codex.plan({"answer": row}, {"answer": row})
    code, _ = world.run()
    assert code == 0 and world.record().runner == "codex"
