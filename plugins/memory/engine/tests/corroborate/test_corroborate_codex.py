"""`mem-corroborate` (the run and the automatic fill) on the Codex runner (ADR 0037): a fake `codex` writes the output
file the brief names and prints a recorded stream."""

from pathlib import Path

import codex_fake
import pytest
from corroborate import fill as corroborate_fill
from corroborate_world import (
    globals_,
    group,
    log_lines,
    model,
    run,
    status,
    two_projects,
    w,
)
from test_corroborate_fill import answers, one_lesson

__all__ = ["w"]  # re-exported: pytest finds the fixture in this module by its name

TOKENS = 1000
TWO_SESSIONS = 2
WRITE_ANSWER = (
    "import re, shutil\n"
    "out = re.search(r'Write (\\S+) as JSON', prompt).group(1)\n"
    "src = os.environ['FAKE_VERDICTS' if out.endswith('verdicts.json') else 'FAKE_GROUPS' if out.endswith('groups.json') else 'FAKE_FILL']\n"
    "shutil.copy(src, out)"
)
STEP = {"py": WRITE_ANSWER, "answer": "done", "tokens": TOKENS}


@pytest.fixture
def codex(w, monkeypatch):
    return codex_fake.install(w.tmp, monkeypatch)


def test_codex_run_applies_the_group_and_records_tokens_and_runner(w, codex):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    codex.plan(STEP, STEP)
    done = run(w)
    assert done.returncode == 0, done.stderr
    (g,) = globals_(w)
    assert g.claim.startswith("Hand a subagent the check")
    line = log_lines(w)[-1]
    assert (line["runner"], line["tokens"], line["cost"], line["failed"]) == (
        "codex",
        TWO_SESSIONS * TOKENS,
        0.0,
        None,
    )
    assert status(w)["runner"] == "codex" and status(w)["tokens"] == TWO_SESSIONS * TOKENS
    assert [c["argv"][c["argv"].index("-s") + 1] for c in codex.calls] == ["workspace-write"] * 2


def test_codex_environment_has_home_in_the_run_folder_and_no_store(w, codex):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    codex.plan(STEP, STEP)
    run(w)
    for call in codex.calls:
        assert Path(call["env"]["HOME"]).parent == Path(call["cwd"])
        assert "MEM_STORE" not in call["env"]


@pytest.mark.parametrize("step", [{"silent": True, "exit": 1}, {"answer": None}])
def test_a_codex_session_without_a_result_ends_the_run(w, codex, step):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    codex.plan(step)
    run(w)
    assert log_lines(w)[-1]["failed"] == "session error" and len(codex.calls) == 1
    assert not globals_(w)


@pytest.mark.parametrize(
    ("step", "shown"),
    [
        ({"failed": "model overloaded", "exit": 1}, "model overloaded; exit 1"),
        ({"error": "quota exceeded", "stderr": "rate limited", "exit": 3}, "stderr: rate limited"),
    ],
)
def test_the_codex_failure_reason_reaches_the_status_and_the_log(w, codex, step, shown):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    codex.plan(step)
    run(w)
    assert (
        status(w)["failure"]["reason"] == "session error"
    )  # the status keeps a fixed reason; the run log has the detail
    logged = (next((w.cdir / "runs").iterdir()) / "log.txt").read_text()
    assert "the proposing session ended without a result: " in logged and shown in logged


def test_a_malformed_runner_setting_fails_the_run_naming_its_source(w, codex, monkeypatch):
    monkeypatch.setenv("MEM_RUNNER", "gpt")
    a, b = two_projects(w)
    model(w, [group(a, b)])
    run(w)
    assert status(w)["failure"]["reason"] == "runner setting" and not codex.calls
    assert "MEM_RUNNER: runner 'gpt'" in (next((w.cdir / "runs").iterdir()) / "log.txt").read_text()


def test_an_early_stop_still_logs_the_codex_runner(w, codex):
    run(w)  # no lessons: the run is skipped before any session
    line = log_lines(w)[-1]
    assert line["skipped"] and line["runner"] == "codex"


def test_the_token_cap_stops_the_second_session(w, codex, monkeypatch):
    monkeypatch.setenv("MEM_CODEX_TOKENS", str(TOKENS))
    a, b = two_projects(w)
    model(w, [group(a, b)])
    codex.plan(STEP, STEP)
    run(w)
    assert len(codex.calls) == 1 and log_lines(w)[-1]["failed"] == "token cap"
    assert not globals_(w)


def test_fill_auto_on_codex_writes_and_records_tokens(w, codex, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    codex.plan(STEP, STEP)
    result = corroborate_fill.fill_auto(str(w.fake), 0.25)
    assert (result["runner"], result["tokens"], result["cost"]) == ("codex", 2 * TOKENS, 0.0)
    assert result["written"] == 1
    assert len(codex.calls) == TWO_SESSIONS


def test_fill_auto_token_cap_fails_the_second_session(w, codex, monkeypatch):
    monkeypatch.setenv("MEM_CODEX_TOKENS", str(TOKENS))
    one_lesson(w)
    answers(w, monkeypatch)
    codex.plan(STEP, STEP)
    result = corroborate_fill.fill_auto(str(w.fake), 0.25)
    assert len(codex.calls) == 1 and "checker" in result["stopped"] and result["written"] == 0


def _staged_run(w, codex, *args, **env):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    codex.plan(STEP, STEP)
    return run(w, *args, env=env)


def test_the_flag_beats_mem_runner(w, codex):
    done = _staged_run(w, codex, "--runner", "codex", MEM_RUNNER="claude")
    assert done.returncode == 0, done.stderr
    assert status(w)["runner"] == "codex"


def test_the_plugin_option_alone_picks_codex(w, codex, monkeypatch):
    monkeypatch.delenv("MEM_RUNNER")
    done = _staged_run(w, codex, MEM_RUNNER_OPTION="codex")
    assert done.returncode == 0, done.stderr
    assert status(w)["runner"] == "codex"
