"""`mem-settle run` on the Codex runner (ADR 0037): a fake `codex` writes the verdicts file and prints a recorded stream."""

from pathlib import Path

import codex_fake
import pytest
from core import codex_pass
from core import runner as runners
from entry import settle
from settle import state as settle_state
from test_settle_run import on, remember, seed, settle_run, status, world

__all__ = ["on", "world"]  # re-exported: pytest finds the fixture in this module by its name

WRITE_VERDICTS = (
    "pairs = json.load(open('pairs.json'))\n"
    "json.dump([{'a': p['a'], 'b': p['b'], 'decision': 'supersede', 'reason': 'the newer one corrects it'}"
    " for p in pairs], open('verdicts.json', 'w'))"
)
TOKENS = 1234


@pytest.fixture
def codex(world, monkeypatch):
    return codex_fake.install(world.tmp, monkeypatch)


def test_codex_run_applies_the_verdicts_and_records_tokens_and_runner(world, codex):
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, "answer": "1", "tokens": TOKENS})
    done = settle_run(world)
    assert done.returncode == 0 and not done.stderr
    s = status(world)
    assert s["state"] == "ok" and s["runner"] == "codex" and s["tokens"] == TOKENS
    assert s["cost"] == 0 and "1 applied" in s["summary"]
    assert "status: superseded" in (world.folder / "old-one.md").read_text()
    (call,) = codex.calls
    assert call["argv"][call["argv"].index("-s") + 1] == "workspace-write"
    assert Path(call["argv"][call["argv"].index("-C") + 1]) == Path(call["cwd"])


def test_codex_environment_has_home_in_the_run_folder_and_no_store(world, codex):
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, "answer": "1"})
    settle_run(world)
    (call,) = codex.calls
    assert Path(call["env"]["HOME"]).parent == Path(call["cwd"])
    assert "MEM_STORE" not in call["env"]


@pytest.mark.parametrize(
    "step", [{"silent": True, "exit": 1}, {"answer": None}, {"answer": "1", "exit": 3}]
)
def test_a_codex_session_without_a_result_is_a_failure_that_applies_nothing(world, codex, step):
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, **step})
    settle_run(world)
    s = status(world)
    assert s["state"] == "failed" and "without a result" in s["reason"]
    assert "status: superseded" not in (world.folder / "old-one.md").read_text()


@pytest.mark.parametrize(
    ("step", "shown"),
    [
        ({"failed": "model overloaded", "exit": 1}, "model overloaded; exit 1"),
        ({"error": "quota exceeded", "stderr": "rate limited", "exit": 3}, "stderr: rate limited"),
    ],
)
def test_the_codex_failure_reason_reaches_the_status(world, codex, step, shown):
    seed(world)
    codex.plan(step)
    settle_run(world)
    reason = status(world)["reason"]
    assert "the session ended without a result: " in reason and shown in reason


def test_a_codex_timeout_reaches_the_status(world, codex, monkeypatch):
    monkeypatch.setattr(
        runners, "run_codex", lambda *a, **k: runners.CodexRaw("", True, None, "slow")
    )
    seed(world)
    assert settle.cmd_run(world.store, "", None, 0) == 0
    assert "the session timed out" in status(world)["reason"]


def test_codex_tokens_at_the_cap_fail_the_run_too(world, codex, monkeypatch):
    monkeypatch.setenv("MEM_CODEX_TOKENS", str(TOKENS))
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, "answer": "1", "tokens": TOKENS})
    settle_run(world)
    assert f"reached the cap {TOKENS}" in status(world)["reason"]


def test_codex_tokens_over_the_cap_fail_the_run(world, codex, monkeypatch):
    monkeypatch.setenv("MEM_CODEX_TOKENS", "100")
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, "answer": "1", "tokens": TOKENS})
    settle_run(world)
    assert "reached the cap 100" in status(world)["reason"]


def test_no_codex_binary_is_a_failure(world, codex, monkeypatch):
    monkeypatch.setattr(runners, "find_codex", lambda env=None: None)
    seed(world)
    assert settle.cmd_run(world.store, "", None, 0) == 0
    assert codex_pass.NO_CODEX in status(world)["reason"] and not codex.calls


def test_the_flag_beats_mem_runner(world, codex):
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, "answer": "1", "tokens": TOKENS})
    done = settle_run(world, "--runner", "codex", env={"MEM_RUNNER": "claude"})
    assert done.returncode == 0 and status(world)["runner"] == "codex"
    assert len(codex.calls) == 1


def test_the_plugin_option_alone_picks_codex_for_a_started_run(world, codex, monkeypatch):
    """What a hook-started settle sees: `MEM_RUNNER_OPTION` and no `MEM_RUNNER`; Codex is found by `MEM_CODEX`."""
    monkeypatch.delenv("MEM_RUNNER")
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, "answer": "1", "tokens": TOKENS})
    done = settle_run(world, env={"MEM_RUNNER_OPTION": "codex"})
    assert done.returncode == 0 and status(world)["runner"] == "codex"
    assert len(codex.calls) == 1


def test_the_write_path_trigger_hands_the_plugin_option_to_the_run(world, on, monkeypatch):
    """`session-env.sh` puts `MEM_RUNNER_OPTION` in the session's shell commands; the settle run they start inherits
    it (`env=dict(environ)`) and never gets it as `MEM_RUNNER`."""
    seed(world, new=False)
    started = []
    monkeypatch.setattr(
        settle_state.subprocess, "Popen", lambda cmd, **kw: started.append(kw["env"])
    )
    monkeypatch.setenv("MEM_RUNNER_OPTION", "codex")
    monkeypatch.delenv("MEM_RUNNER", raising=False)
    assert remember(world) == 0
    (env,) = started
    assert env["MEM_RUNNER_OPTION"] == "codex" and "MEM_RUNNER" not in env


def test_the_codex_brief_carries_the_merge_addendum_and_the_claude_one_does_not(world, codex):
    seed(world)
    codex.plan({"py": WRITE_VERDICTS, "answer": "1"})
    settle_run(world)
    (call,) = codex.calls
    assert settle.CODEX_ADDENDUM in call["prompt"]
    assert settle.CODEX_ADDENDUM not in settle.sp.brief("settle", PAIRS_FILE="p", VERDICTS_FILE="v")
